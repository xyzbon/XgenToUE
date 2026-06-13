#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alembic post-processing for groom data.

Combines strand and guide Alembic archives exported from Maya into a single
Unreal Engine compatible groom file. The arbGeomParams attributes that UE's
Groom system requires (``groom_group_name``, ``groom_group_id`` and
``groom_root_uv``) are populated on the strand curves; guide curves retain
the attributes Maya wrote for them at export time.

The public entry point is :func:`merge_and_process_abc`.
"""

import gc
import json
import os
import pathlib
import alembic
import imath
import cask

import logging

log = logging.getLogger('xgentoue')


# Optional accelerators for the UV-lookup fast path. Each is wrapped in a
# broad except so a broken install (e.g. scipy's walrus operator under
# Python 3.7 in Maya 2022 raises SyntaxError, not ImportError) does not
# crash module import — the pure-Python BVH fallback is always available.
NUMPY_AVAILABLE = False
TRIMESH_AVAILABLE = False
SCIPY_AVAILABLE = False

# The trimesh -> pure-Python fallback warning is logged once per process;
# otherwise it repeats for every description in an export.
_TRIMESH_FALLBACK_WARNED = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except (ImportError, SyntaxError, AttributeError):
    pass

try:
    import trimesh as _trimesh
    # NOTE: trimesh.proximity.closest_point (the accurate closest-point-
    # on-surface query) uses scipy.spatial.cKDTree internally. trimesh
    # imports fine without scipy, but the call raises
    # ModuleNotFoundError('scipy') mid-export. So the trimesh fast path
    # is gated on SCIPY_AVAILABLE in find_closest_uv_on_mesh (and wrapped
    # in try/except), and we fall back to the equally-accurate pure-Python
    # BVH when scipy isn't present. rtree is NOT required.
    TRIMESH_AVAILABLE = True
except (ImportError, SyntaxError, AttributeError):
    pass

try:
    from scipy.spatial import cKDTree
    SCIPY_AVAILABLE = True
except (ImportError, SyntaxError, AttributeError):
    pass


def get_or_create_arbGeomParams(curve_obj):
    """
    Get or create the .arbGeomParams compound property on a Curve object.

    :param curve_obj: cask.Curve object
    :return: cask.Property for .arbGeomParams
    """
    geom = curve_obj.properties.get('.geom', None)
    if geom is None:
        raise ValueError(f'Curve {curve_obj.path()} does not have a ".geom" property.')

    arbGeomParams = geom.properties.get('.arbGeomParams', None)
    if arbGeomParams is None:
        # Create .arbGeomParams compound property without a dummy ICompoundProperty.
        # Setting _klass directly ensures is_compound() returns True.
        arbGeomParams = cask.Property(name='.arbGeomParams', time_sampling_id=0)
        arbGeomParams._klass = alembic.Abc.OCompoundProperty
        geom.properties['.arbGeomParams'] = arbGeomParams

    return arbGeomParams


def add_userProperties(curve_obj):
    """
    Add .userProperties compound property to the .geom compound property.
    This creates an empty compound property with 0 sub-properties.

    :param curve_obj: cask.Curve object
    """
    geom = curve_obj.properties.get('.geom', None)
    if geom is None:
        raise ValueError(f'Curve {curve_obj.path()} does not have a ".geom" property.')

    userProperties = geom.properties.get('.userProperties', None)
    if userProperties is None:
        # Create .userProperties compound property without any sub-properties
        # Setting _klass directly ensures is_compound() returns True.
        userProperties = cask.Property(name='.userProperties', time_sampling_id=0)
        userProperties._klass = alembic.Abc.OCompoundProperty
        # Try to get iobject from parent if it exists
        if geom.iobject and hasattr(geom.iobject, 'getProperty'):
            try:
                userProperties._iobject = geom.iobject.getProperty('.userProperties')
            except:
                pass  # Property doesn't exist in the input file
        geom.properties['.userProperties'] = userProperties
        log.info(f'    Added .geom/.userProperties compound property (0 sub-properties)')


def remove_uv_from_geom(curve_obj):
    """
    Remove the 'uv' property from under the .geom compound property.

    :param curve_obj: cask.Curve object
    """
    geom = curve_obj.properties.get('.geom', None)
    if geom is None:
        return

    # Remove 'uv' property if it exists under .geom
    if 'uv' in geom.properties:
        del geom.properties['uv']
        log.info(f'    Removed .geom/uv property')


def remove_non_geom_properties(curve_obj):
    """
    Remove all properties except the .geom compound property from a Curve object.
    Also removes the 'uv' attribute under .geom.

    :param curve_obj: cask.Curve object
    """
    # Remove all top-level properties except .geom
    properties_to_remove = []
    for prop_name in list(curve_obj.properties.keys()):
        if prop_name != '.geom':
            properties_to_remove.append(prop_name)

    for prop_name in properties_to_remove:
        del curve_obj.properties[prop_name]
        log.info(f'    Removed property: {prop_name}')

    # Also remove 'uv' from under .geom
    remove_uv_from_geom(curve_obj)


def _write_groom_group_name_attr(arbGeomParams, value):
    """Internal: add the ``groom_group_name`` OArrayProperty under
    an existing ``.arbGeomParams`` compound. Idempotent.
    """
    if arbGeomParams.properties.get('groom_group_name') is not None:
        return
    prop = cask.Property(name='groom_group_name', time_sampling_id=0)
    str_array = imath.StringArray(1)
    str_array[0] = value
    prop.set_value(str_array)
    prop._datatype = alembic.AbcCoreAbstract.DataType(
        alembic.Util.POD.kStringPOD, 1,
    )
    prop.metadata['arrayExtent'] = '1'
    prop.metadata['isGeomParam'] = 'true'
    prop.metadata['podExtent'] = '1'
    prop.metadata['podName'] = 'string'
    arbGeomParams.properties['groom_group_name'] = prop


def _add_userproperties_pad(curve_obj):
    """Add a throwaway int16 named ``_pad`` inside ``.userProperties``.

    Cask drops empty compound properties during ``write_to_file``
    (its save loop only touches a property's ``oobject`` when there
    are children to iterate), so an empty ``.userProperties`` we add
    via :func:`add_userProperties` never makes it to disk. UE's Groom
    Import only reads ``.arbGeomParams`` - it never inspects
    ``.userProperties`` contents - so a single harmless padding value
    is invisible to the importer and gets cask to serialize the
    compound. This matches what Maya's native AbcExport produces
    structurally (the slot exists), differing only in that the
    reference file's compound is truly empty whereas ours has a
    single ``_pad`` child.
    """
    geom = curve_obj.properties.get('.geom', None)
    if geom is None:
        return
    user_props = geom.properties.get('.userProperties', None)
    if user_props is None:
        return
    if user_props.properties.get('_pad') is not None:
        return
    pad = cask.Property(name='_pad', time_sampling_id=0)
    arr = imath.ShortArray(1)
    arr[0] = 0
    pad.set_value(arr)
    pad._datatype = alembic.AbcCoreAbstract.DataType(
        alembic.Util.POD.kInt16POD, 1,
    )
    user_props.properties['_pad'] = pad


def _write_groom_short_attr(arbGeomParams, name, value, geo_scope='con'):
    """Internal: add an ``int16`` OArrayProperty under an existing
    ``.arbGeomParams`` compound. Used for ``groom_group_id`` and
    ``groom_guide`` which share the same shape - only the name,
    value, and geo_scope differ.
    """
    if arbGeomParams.properties.get(name) is not None:
        return
    prop = cask.Property(name=name, time_sampling_id=0)
    short_array = imath.ShortArray(1)
    short_array[0] = value
    prop.set_value(short_array)
    prop._datatype = alembic.AbcCoreAbstract.DataType(
        alembic.Util.POD.kInt16POD, 1,
    )
    prop.metadata['arrayExtent'] = '1'
    if geo_scope:
        prop.metadata['geoScope'] = geo_scope
    prop.metadata['isGeomParam'] = 'true'
    prop.metadata['podExtent'] = '1'
    prop.metadata['podName'] = 'int16_t'
    arbGeomParams.properties[name] = prop


def add_groom_attributes(curve_obj, groom_group_name, groom_group_id):
    """
    Add groom_group_name and groom_group_id attributes to a Curve object.
    Also adds .userProperties compound property for splineDescription curves.

    :param curve_obj: cask.Curve object
    :param groom_group_name: string value for groom_group_name attribute
    :param groom_group_id: int value for groom_group_id attribute
    """
    # First remove all non-.geom properties
    remove_non_geom_properties(curve_obj)

    # Add .userProperties for splineDescription curves
    path = curve_obj.path()
    if '_splineDescription' in path:
        add_userProperties(curve_obj)

    arbGeomParams = get_or_create_arbGeomParams(curve_obj)

    # Add groom_group_name (string) property with proper metadata
    # UE expects OArrayProperty (not OScalarProperty).
    # Using imath.StringArray ensures cask classifies this as OArrayProperty,
    # because bare strings / single-element lists get _delist'd to scalars.
    prop_name = arbGeomParams.properties.get('groom_group_name', None)
    if prop_name is None:
        prop_name = cask.Property(name='groom_group_name', time_sampling_id=0)
        str_array = imath.StringArray(1)
        str_array[0] = groom_group_name
        prop_name.set_value(str_array)
        # Explicitly set DataType to bypass cask's POD_EXTENT lookup
        prop_name._datatype = alembic.AbcCoreAbstract.DataType(
            alembic.Util.POD.kStringPOD, 1
        )
        # Set metadata to match Maya's export format for UE compatibility
        # NOTE: groom_group_name does NOT have geoScope in Maya's export
        prop_name.metadata['arrayExtent'] = '1'
        prop_name.metadata['isGeomParam'] = 'true'
        prop_name.metadata['podExtent'] = '1'
        prop_name.metadata['podName'] = 'string'
        arbGeomParams.properties['groom_group_name'] = prop_name

    # Add groom_group_id (int16) property with proper metadata
    # UE expects OArrayProperty with constant scope.
    # Using imath.ShortArray ensures cask classifies this as OArrayProperty
    # and writes kInt16POD, matching Maya's attributeType='short'.
    prop_id = arbGeomParams.properties.get('groom_group_id', None)
    if prop_id is None:
        prop_id = cask.Property(name='groom_group_id', time_sampling_id=0)
        short_array = imath.ShortArray(1)
        short_array[0] = groom_group_id
        prop_id.set_value(short_array)
        # Explicitly set DataType — imath.ShortArray is NOT in cask's
        # POD_EXTENT mapping, so get_pod_extent() would fail without this.
        prop_id._datatype = alembic.AbcCoreAbstract.DataType(
            alembic.Util.POD.kInt16POD, 1
        )
        # Set metadata to match Maya's export format for UE compatibility
        prop_id.metadata['arrayExtent'] = '1'
        prop_id.metadata['geoScope'] = 'con'  # constant scope
        prop_id.metadata['isGeomParam'] = 'true'
        prop_id.metadata['podExtent'] = '1'
        prop_id.metadata['podName'] = 'int16_t'
        arbGeomParams.properties['groom_group_id'] = prop_id


def _strip_export_suffix(name, suffix):
    """Trim the configured guide-children suffix (case-insensitive)
    and any trailing underscore from ``name``.

    e.g. ``'charA:brow_a_follicles'`` + suffix ``'_follicles'`` ->
    ``'charA:brow_a'``. Namespace is preserved on purpose - the
    reference ``charA_guides.abc`` stores the namespace as part of
    ``groom_group_name`` so UE's groom system can tell characters
    apart in multi-character imports.
    """
    if not suffix:
        return name
    idx = name.lower().rfind(suffix.lower())
    if idx == -1:
        return name
    return name[:idx].rstrip('_')


def _iter_curves(obj):
    """Yield every Curve IObject in ``obj`` and its descendants."""
    if obj.type() == 'Curve':
        yield obj
        return
    children = getattr(obj, 'children', None)
    if not children:
        return
    for child in children.values():
        for c in _iter_curves(child):
            yield c


def _m44_to_list(m):
    """Copy an ``imath.M44d`` into a plain 4x4 Python list."""
    return [[m[i][j] for j in range(4)] for i in range(4)]


def _matmul4(a, b):
    """Multiply two 4x4 row-major matrices (Maya/Alembic row-vector
    convention: a point transforms as ``v' = v * M``)."""
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def _bake_matrix_into_points(curve, mat):
    """Transform every point of every time sample of ``curve`` by the
    4x4 ``mat`` (a parent-Xform world matrix), writing the result back.

    Animation is preserved: the same static parent matrix is applied to
    each sample, so per-frame motion in the local points survives - only
    the constant world offset/orientation is folded in.
    """
    geom = curve.properties.get('.geom', None)
    if geom is None:
        return
    pp = geom.properties.get('P', None)
    if pp is None:
        return
    samples = pp.values
    for si in range(len(samples)):
        s = samples[si]
        n = len(s)
        new = imath.V3fArray(n)
        for k in range(n):
            x, y, z = s[k][0], s[k][1], s[k][2]
            new[k] = imath.V3f(
                x * mat[0][0] + y * mat[1][0] + z * mat[2][0] + mat[3][0],
                x * mat[0][1] + y * mat[1][1] + z * mat[2][1] + mat[3][1],
                x * mat[0][2] + y * mat[1][2] + z * mat[2][2] + mat[3][2],
            )
        pp.set_value(new, index=si)


def flatten_guide_groups(abc_path, fps=24):
    """Flatten a guide export so each merged ``<description>_guides``
    curve sits at the archive top level with its world offset baked
    into the points.

    The guide export roots ``AbcExport`` at the guide-root transform
    (e.g. ``guide_grp``) with ``riCurves`` on each ``<description>_guides``
    child. ``riCurves`` merges each description's guide curves into ONE
    ``Curve``, but it stays parented under the guide-root Xform - and on
    a shot that Xform carries the character's world placement (e.g.
    ``translateX = -15``) while the merged curve's points remain in
    local space. UE's groom importer also rejects the un-flattened
    shape, reporting "Some groups have 0 curves" for the intermediate
    Xform that holds no direct curves.

    This promotes every merged Curve to the top level, baking the
    accumulated parent-Xform matrix into its points, then drops the now
    empty guide-root Xform. The result matches the native reference
    export: a clean top-level Curve whose points already carry the world
    offset (so it is correct whether or not UE applies parent
    transforms), with animation intact.

    Mutates the file in place via a released ``.tmp`` swap, same as
    :func:`add_animation_groom_attributes`.
    """
    tmp_path = abc_path + '.tmp'
    archive = cask.Archive(abc_path, fps=fps)
    moved = []
    dropped = []  # wrapper Xforms removed from the graph (still hold handles)
    wrote = False
    walk = top_name = top_obj = None
    try:

        def walk(obj, mat):
            for child in list(obj.children.values()):
                kind = child.type()
                if kind == 'Curve':
                    _bake_matrix_into_points(child, mat)
                    moved.append(child)
                elif kind == 'Xform':
                    walk(child, _matmul4(_m44_to_list(child.matrix(0)), mat))

        for top_name, top_obj in list(archive.top.children.items()):
            if top_obj.type() != 'Xform':
                continue  # already a top-level Curve, or not ours
            before = len(moved)
            walk(top_obj, _m44_to_list(top_obj.matrix(0)))
            # Only drop the wrapper Xform if we actually extracted curves
            # from it - never silently delete a branch that held none.
            if len(moved) > before:
                dropped.append(archive.top.children.pop(top_name))

        if not moved:
            log.warning(
                'flatten_guide_groups: no curves under a wrapper Xform in '
                '%s (left unchanged)', abc_path,
            )
            return

        for curve in moved:
            archive.top.children[curve.name] = curve

        log.info('flatten_guide_groups: promoted %d curve(s) in %s',
                 len(moved), abc_path)
        archive.write_to_file(tmp_path)
        wrote = True
    finally:
        # Every cask object we still hold keeps its own read-side alembic
        # handle alive, so the IArchive refcount only hits zero (and
        # Windows releases the file) once they're ALL dropped. The
        # promoted curves (`moved`) and especially the wrapper Xforms we
        # popped OUT of the graph (`dropped`, which _release_archives
        # can't reach) must be cleared explicitly, along with the loop
        # vars that still point at the last wrapper.
        del moved[:]
        del dropped[:]
        walk = top_name = top_obj = None
        _release_archives([archive])
        archive = None

    if wrote:
        _safe_replace(tmp_path, abc_path)


def add_animation_groom_attributes(abc_path, suffix='_guides', fps=24):
    """Add groom attributes to a freshly-exported animation .abc.

    Animation exports skip the in-Maya ``create_guide_attributes``
    DAG manipulation (no reparent, no reference-edits, no scene
    reopen). Instead we run a clean ``cmds.AbcExport`` on the
    original ``<description>_Guides`` transforms and then call THIS
    function to bake the same attributes UE's groom system expects
    onto every Curve in the file.

    For each Curve IObject in path-sorted order:
        - ``.geom/.arbGeomParams/groom_group_name`` (string)
        - ``.geom/.arbGeomParams/groom_group_id`` (int16, geoScope='con')
        - ``.geom/.arbGeomParams/groom_guide`` (int16, value=1)
        - ``.geom/.userProperties`` (empty compound, for UE compat)

    ``groom_group_name`` is derived from the Curve's nearest non-
    Curve ancestor name (the ``<description>_Guides`` wrapper),
    with the configured ``suffix`` stripped. Curves that share an
    ancestor share a ``groom_group_id``. This handles both the
    one-Curve-per-description and multiple-Curves-per-description
    structures - whichever AbcExport produces, sibling curves stay
    grouped.

    Mutates the file in place by writing to ``<abc_path>.tmp`` first
    and atomically replacing the original. Writing to the same path
    while cask still holds the read handle is what triggers Maya's
    "Could not open file" error on the next AbcExport run - the
    OArchive destructor lags Python GC.
    """
    tmp_path = abc_path + '.tmp'
    archive = cask.Archive(abc_path, fps=fps)
    try:
        # Group Curves by their nearest non-Curve ancestor (the
        # description wrapper transform). Curves directly at the top
        # level are their own group.
        groups = {}  # ordered: dict preserves insertion order
        for top_child in archive.top.children.values():
            wrapper_name = top_child.name
            for curve in _iter_curves(top_child):
                groups.setdefault(wrapper_name, []).append(curve)

        if not groups:
            log.warning(
                'add_animation_groom_attributes: no curves found in %s',
                abc_path,
            )
            return

        # Sort groups by stripped name so groom_group_id is stable
        # across reruns (otherwise dict iteration order could shift
        # ids between exports of the same scene).
        ordered_names = sorted(
            groups.keys(),
            key=lambda n: _strip_export_suffix(n, suffix),
        )
        for group_id, wrapper_name in enumerate(ordered_names):
            groom_group_name = _strip_export_suffix(wrapper_name, suffix)
            for curve in groups[wrapper_name]:
                arbGeomParams = get_or_create_arbGeomParams(curve)
                _write_groom_group_name_attr(arbGeomParams, groom_group_name)
                # groom_group_id and groom_guide are CONSTANT-scope int16
                # geom params (one value per curve). groom_group_id MUST
                # carry geoScope='con' - matching add_groom_attributes, the
                # native AbcExport, and the documented UE requirement. Without
                # it UE reads the id as non-constant and mis-groups / scatters
                # the strands. (A previous "no geoScope" note here was wrong.)
                _write_groom_short_attr(
                    arbGeomParams, 'groom_group_id', group_id,
                    geo_scope='con',
                )
                _write_groom_short_attr(
                    arbGeomParams, 'groom_guide', 1, geo_scope='con',
                )
                add_userProperties(curve)
                _add_userproperties_pad(curve)
            log.info(
                'add_animation_groom_attributes: %s (id=%d, %d curve(s))',
                groom_group_name, group_id, len(groups[wrapper_name]),
            )

        log.info(
            'add_animation_groom_attributes: writing %s', tmp_path,
        )
        archive.write_to_file(tmp_path)
    finally:
        # Forcibly drop cask's internal alembic refs so the C++
        # IArchive destructor runs NOW. See _release_archives for
        # why ``_iobject`` / ``_top`` are the right attribute names
        # (the earlier ``_iarchive`` target was a no-op).
        _release_archives([archive])
        archive = None

    # Atomic swap: replace original only after we're sure cask
    # released its read handle. os.replace is atomic on Windows
    # (Python 3.3+) and does the right thing even if the target
    # exists.
    os.replace(tmp_path, abc_path)


# ---------------------------------------------------------------------------
# Vector math helpers (pure Python, no dependencies)
# ---------------------------------------------------------------------------

def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_dist_sq(a, b):
    d = _vec_sub(a, b)
    return _vec_dot(d, d)


# ---------------------------------------------------------------------------
# Mesh / UV helpers for groom_root_uv (no Maya dependency)
# ---------------------------------------------------------------------------

def load_description_mesh_map(json_path):
    """Load description-to-mesh mapping from JSON file.

    Returns dict like {"desc_b1": ["|pPlane1"]}.
    """
    with open(json_path, 'r') as f:
        return json.load(f)


def load_mesh_from_abc(patches_abc_or_archive, mesh_transform_name):
    """Load mesh data (positions, faces, UVs) from a patches Alembic file.

    :param patches_abc_or_archive: path to patches .abc file OR an already-open cask.Archive
    :param mesh_transform_name: Maya transform name (e.g. "|pPlane1" or "pPlane1")
    :return: dict with positions, face_counts, face_indices, uv_vals, uv_indices
    """
    # Accept either a path string or an already-open archive for efficiency
    if isinstance(patches_abc_or_archive, str):
        archive = cask.Archive(patches_abc_or_archive)
    else:
        archive = patches_abc_or_archive

    transform_name = mesh_transform_name.lstrip('|')

    # Try the exact name first, then the namespace-stripped form.
    # patches.abc is exported with AbcExport's -stripNamespaces flag
    # while mesh_map.json carries the original Maya transform names
    # (which still have the leading <namespace>: prefix in shot
    # files). Looking up 'charA1:hair_patch' in an archive that only
    # has 'hair_patch' has to succeed, otherwise groom_root_uv never
    # gets written for the strand.
    xform = archive.top.children.get(transform_name)
    if xform is None and ':' in transform_name:
        stripped = transform_name.rsplit(':', 1)[-1]
        xform = archive.top.children.get(stripped)
        if xform is not None:
            transform_name = stripped
    if xform is None:
        raise ValueError(f"Transform '{transform_name}' not found in {patches_abc_or_archive}")

    # Find the PolyMesh child
    mesh_obj = None
    for child in xform.children.values():
        if child.type() == 'PolyMesh':
            mesh_obj = child
            break

    if mesh_obj is None:
        raise ValueError(f"No PolyMesh found under '{transform_name}'")

    mesh = alembic.AbcGeom.IPolyMesh(
        mesh_obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting
    )
    schema = mesh.getSchema()
    mesh_sample = schema.getValue()

    positions = [(p[0], p[1], p[2]) for p in mesh_sample.getPositions()]
    face_counts = list(mesh_sample.getFaceCounts())
    face_indices = list(mesh_sample.getFaceIndices())

    # Read UVs
    uv_param = schema.getUVsParam()
    uv_sample = uv_param.getIndexedValue()
    uv_vals = [(uv[0], uv[1]) for uv in uv_sample.getVals()]
    uv_indices = list(uv_sample.getIndices())

    return {
        'positions': positions,
        'face_counts': face_counts,
        'face_indices': face_indices,
        'uv_vals': uv_vals,
        'uv_indices': uv_indices,
    }


def triangulate_mesh(positions, face_counts, face_indices, uv_vals, uv_indices):
    """Fan-triangulate polygons into a list of triangle dicts.

    Each triangle dict has keys: v0, v1, v2 (3D positions) and uv0, uv1, uv2 (2D UVs).
    """
    triangles = []
    idx_offset = 0
    for n_verts in face_counts:
        for i in range(n_verts - 2):
            v0_idx = face_indices[idx_offset]
            v1_idx = face_indices[idx_offset + i + 1]
            v2_idx = face_indices[idx_offset + i + 2]

            uv0_idx = uv_indices[idx_offset]
            uv1_idx = uv_indices[idx_offset + i + 1]
            uv2_idx = uv_indices[idx_offset + i + 2]

            triangles.append({
                'v0': positions[v0_idx],
                'v1': positions[v1_idx],
                'v2': positions[v2_idx],
                'uv0': uv_vals[uv0_idx],
                'uv1': uv_vals[uv1_idx],
                'uv2': uv_vals[uv2_idx],
            })
        idx_offset += n_verts
    return triangles


def closest_point_on_triangle(point, v0, v1, v2):
    """Find closest point on triangle to query point (Voronoi region method).

    Based on Ericson's "Real-Time Collision Detection" Section 5.1.5.
    Returns (closest_point, barycentric_coords) where barycentric_coords is
    (u, v, w) such that closest_point = u*v0 + v*v1 + w*v2.
    """
    ab = _vec_sub(v1, v0)
    ac = _vec_sub(v2, v0)
    ap = _vec_sub(point, v0)

    d1 = _vec_dot(ab, ap)
    d2 = _vec_dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return v0, (1.0, 0.0, 0.0)

    bp = _vec_sub(point, v1)
    d3 = _vec_dot(ab, bp)
    d4 = _vec_dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return v1, (0.0, 1.0, 0.0)

    cp = _vec_sub(point, v2)
    d5 = _vec_dot(ab, cp)
    d6 = _vec_dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return v2, (0.0, 0.0, 1.0)

    # Edge AB region
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        t = d1 / (d1 - d3)
        closest = (v0[0] + t * ab[0], v0[1] + t * ab[1], v0[2] + t * ab[2])
        return closest, (1.0 - t, t, 0.0)

    # Edge AC region
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        t = d2 / (d2 - d6)
        closest = (v0[0] + t * ac[0], v0[1] + t * ac[1], v0[2] + t * ac[2])
        return closest, (1.0 - t, 0.0, t)

    # Edge BC region
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        closest = (
            v1[0] + t * (v2[0] - v1[0]),
            v1[1] + t * (v2[1] - v1[1]),
            v1[2] + t * (v2[2] - v1[2]),
        )
        return closest, (0.0, 1.0 - t, t)

    # Inside triangle
    denom = 1.0 / (va + vb + vc)
    bv = vb * denom
    bw = vc * denom
    closest = (
        v0[0] + ab[0] * bv + ac[0] * bw,
        v0[1] + ab[1] * bv + ac[1] * bw,
        v0[2] + ab[2] * bv + ac[2] * bw,
    )
    return closest, (1.0 - bv - bw, bv, bw)


def _tri_aabb(tri):
    """Compute axis-aligned bounding box for a triangle.

    :return: (min_x, min_y, min_z, max_x, max_y, max_z)
    """
    v0, v1, v2 = tri['v0'], tri['v1'], tri['v2']
    return (
        min(v0[0], v1[0], v2[0]), min(v0[1], v1[1], v2[1]), min(v0[2], v1[2], v2[2]),
        max(v0[0], v1[0], v2[0]), max(v0[1], v1[1], v2[1]), max(v0[2], v1[2], v2[2]),
    )


def _merge_aabb(a, b):
    return (
        min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]),
        max(a[3], b[3]), max(a[4], b[4]), max(a[5], b[5]),
    )


def _aabb_dist_sq(pt, aabb):
    """Squared distance from point to AABB (0 if inside)."""
    dx = max(aabb[0] - pt[0], 0.0, pt[0] - aabb[3])
    dy = max(aabb[1] - pt[1], 0.0, pt[1] - aabb[4])
    dz = max(aabb[2] - pt[2], 0.0, pt[2] - aabb[5])
    return dx * dx + dy * dy + dz * dz


def _build_bvh(tri_indices, aabbs, centroids, axis=0):
    """Build a BVH node over the given triangle indices.

    Returns a tuple tree: (aabb, left, right) for internal nodes,
    or (aabb, tri_index) for leaf nodes.
    """
    n = len(tri_indices)
    if n == 1:
        return (aabbs[tri_indices[0]], tri_indices[0])
    if n == 2:
        left = (aabbs[tri_indices[0]], tri_indices[0])
        right = (aabbs[tri_indices[1]], tri_indices[1])
        return (_merge_aabb(left[0], right[0]), left, right)

    # Sort by centroid along current axis and split in half
    tri_indices.sort(key=lambda i: centroids[i][axis])
    mid = n // 2
    next_axis = (axis + 1) % 3
    left = _build_bvh(tri_indices[:mid], aabbs, centroids, next_axis)
    right = _build_bvh(tri_indices[mid:], aabbs, centroids, next_axis)
    return (_merge_aabb(left[0], right[0]), left, right)


def _query_bvh(node, pt, triangles, best_dist, best_uv):
    """Query BVH for the closest triangle to pt.

    :return: (best_dist_sq, best_uv)
    """
    aabb = node[0]
    if _aabb_dist_sq(pt, aabb) >= best_dist:
        return best_dist, best_uv

    if len(node) == 2 and isinstance(node[1], int):
        # Leaf node
        tri = triangles[node[1]]
        closest, bary = closest_point_on_triangle(
            pt, tri['v0'], tri['v1'], tri['v2']
        )
        dist = _vec_dist_sq(pt, closest)
        if dist < best_dist:
            u = bary[0] * tri['uv0'][0] + bary[1] * tri['uv1'][0] + bary[2] * tri['uv2'][0]
            v = bary[0] * tri['uv0'][1] + bary[1] * tri['uv1'][1] + bary[2] * tri['uv2'][1]
            return dist, (u, v)
        return best_dist, best_uv

    # Internal node — traverse closer child first
    left, right = node[1], node[2]
    left_dist = _aabb_dist_sq(pt, left[0])
    right_dist = _aabb_dist_sq(pt, right[0])

    if left_dist <= right_dist:
        best_dist, best_uv = _query_bvh(left, pt, triangles, best_dist, best_uv)
        best_dist, best_uv = _query_bvh(right, pt, triangles, best_dist, best_uv)
    else:
        best_dist, best_uv = _query_bvh(right, pt, triangles, best_dist, best_uv)
        best_dist, best_uv = _query_bvh(left, pt, triangles, best_dist, best_uv)

    return best_dist, best_uv


def build_triangle_bvh(triangles):
    """Build a BVH from a list of triangles for fast closest-point queries.

    :param triangles: list of triangle dicts from triangulate_mesh()
    :return: BVH root node
    """
    if not triangles:
        return None
    aabbs = [_tri_aabb(tri) for tri in triangles]
    centroids = [
        ((a[0] + a[3]) * 0.5, (a[1] + a[4]) * 0.5, (a[2] + a[5]) * 0.5)
        for a in aabbs
    ]
    return _build_bvh(list(range(len(triangles))), aabbs, centroids)


def _find_uv_trimesh(query_points, triangles):
    """Fast closest-point UV lookup using trimesh (C-backed BVH).

    :param query_points: list of (x, y, z) tuples
    :param triangles: list of triangle dicts from triangulate_mesh()
    :return: list of (u, v) tuples
    """
    # Build vertex array and face index array from triangles
    # Each triangle has unique vertices (unshared) to preserve per-face UVs
    n_tri = len(triangles)
    vertices = np.empty((n_tri * 3, 3), dtype=np.float64)
    faces = np.empty((n_tri, 3), dtype=np.int32)
    uv_per_vertex = np.empty((n_tri * 3, 2), dtype=np.float64)

    for i, tri in enumerate(triangles):
        base = i * 3
        vertices[base] = tri['v0']
        vertices[base + 1] = tri['v1']
        vertices[base + 2] = tri['v2']
        faces[i] = [base, base + 1, base + 2]
        uv_per_vertex[base] = tri['uv0']
        uv_per_vertex[base + 1] = tri['uv1']
        uv_per_vertex[base + 2] = tri['uv2']

    mesh = _trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    points = np.array(query_points, dtype=np.float64)

    # Batch closest-point query (all points at once)
    closest_points, _distances, triangle_ids = _trimesh.proximity.closest_point(mesh, points)

    uvs = []
    for i, tri_id in enumerate(triangle_ids):
        if tri_id < 0:
            uvs.append((0.0, 0.0))
            continue
        face = faces[tri_id]
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        # Barycentric coordinates of closest point
        e0 = v1 - v0
        e1 = v2 - v0
        ep = closest_points[i] - v0
        d00 = np.dot(e0, e0)
        d01 = np.dot(e0, e1)
        d11 = np.dot(e1, e1)
        d20 = np.dot(ep, e0)
        d21 = np.dot(ep, e1)
        denom = d00 * d11 - d01 * d01
        if abs(denom) < 1e-12:
            bv = bw = 1.0 / 3.0
            bu = 1.0 / 3.0
        else:
            bv = (d11 * d20 - d01 * d21) / denom
            bw = (d00 * d21 - d01 * d20) / denom
            bu = 1.0 - bv - bw
        uv0 = uv_per_vertex[face[0]]
        uv1 = uv_per_vertex[face[1]]
        uv2 = uv_per_vertex[face[2]]
        interp = bu * uv0 + bv * uv1 + bw * uv2
        uvs.append((float(interp[0]), float(interp[1])))
    return uvs


def _find_uv_scipy(query_points, triangles):
    """Nearest-vertex UV lookup using scipy cKDTree.

    Less accurate than closest-point-on-surface but very fast.
    :param query_points: list of (x, y, z) tuples
    :param triangles: list of triangle dicts from triangulate_mesh()
    :return: list of (u, v) tuples
    """
    # Collect all unique vertices and their UVs
    all_verts = []
    all_uvs = []
    for tri in triangles:
        for vk, uvk in [('v0', 'uv0'), ('v1', 'uv1'), ('v2', 'uv2')]:
            all_verts.append(tri[vk])
            all_uvs.append(tri[uvk])

    verts_arr = np.array(all_verts, dtype=np.float64)
    uvs_arr = np.array(all_uvs, dtype=np.float64)
    points = np.array(query_points, dtype=np.float64)

    tree = cKDTree(verts_arr)
    _, indices = tree.query(points)

    return [(float(uvs_arr[idx][0]), float(uvs_arr[idx][1])) for idx in indices]


def find_closest_uv_on_mesh(query_points, triangles, bvh=None):
    """For each query point, find the closest point on the triangulated mesh
    and return the interpolated UV coordinate.

    Uses the fastest available backend:
    1. trimesh (C-backed BVH, accurate closest-point-on-surface)
    2. scipy cKDTree (C-backed, nearest-vertex approximation)
    3. Pure-Python BVH fallback

    :param query_points: list of (x, y, z) tuples
    :param triangles: list of triangle dicts from triangulate_mesh()
    :param bvh: optional prebuilt BVH node for pure-Python fallback
    :return: list of (u, v) tuples
    """
    if not query_points or not triangles:
        return [(0.0, 0.0)] * len(query_points)

    # Fast path: trimesh closest-point-on-surface (accurate). It needs
    # scipy (cKDTree) at call time, so gate on scipy AND wrap in
    # try/except - any runtime failure must fall through to a working
    # backend rather than aborting the whole export.
    if TRIMESH_AVAILABLE and SCIPY_AVAILABLE and NUMPY_AVAILABLE:
        try:
            return _find_uv_trimesh(query_points, triangles)
        except Exception as exc:
            global _TRIMESH_FALLBACK_WARNED
            if not _TRIMESH_FALLBACK_WARNED:
                log.warning(
                    'trimesh closest-point unavailable (%s); using the '
                    'pure-Python BVH for this export', exc,
                )
                _TRIMESH_FALLBACK_WARNED = True

    # Medium path: scipy nearest-vertex (fast but less accurate). Only
    # reached if trimesh itself is unavailable.
    if SCIPY_AVAILABLE and NUMPY_AVAILABLE:
        try:
            return _find_uv_scipy(query_points, triangles)
        except Exception as exc:
            log.warning(
                'scipy nearest-vertex failed (%s); falling back to the '
                'pure-Python BVH', exc,
            )

    # Slow path: pure-Python BVH fallback (accurate, zero dependencies)
    if bvh is None:
        bvh = build_triangle_bvh(triangles)

    uvs = []
    for pt in query_points:
        _, uv = _query_bvh(bvh, pt, triangles, float('inf'), (0.0, 0.0))
        uvs.append(uv)
    return uvs


def get_curve_root_positions(curve_obj):
    """Extract the root position (first vertex) of each curve in a Curves object.

    :param curve_obj: cask.Curve object
    :return: list of (x, y, z) tuples, one per curve
    """
    icurves = alembic.AbcGeom.ICurves(
        curve_obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting
    )
    schema = icurves.getSchema()
    sample = schema.getValue()

    positions = sample.getPositions()
    n_vertices = sample.getCurvesNumVertices()

    roots = []
    offset = 0
    for count in n_vertices:
        p = positions[offset]
        roots.append((p[0], p[1], p[2]))
        offset += count
    return roots


def add_groom_root_uv(curve_obj, uv_values):
    """Add groom_root_uv attribute to a Curve object's .arbGeomParams.

    :param curve_obj: cask.Curve object
    :param uv_values: list of (u, v) tuples, one per curve
    """
    arbGeomParams = get_or_create_arbGeomParams(curve_obj)

    if 'groom_root_uv' in arbGeomParams.properties:
        return

    prop = cask.Property(name='groom_root_uv', time_sampling_id=0)
    v2d_array = imath.V2dArray(len(uv_values))
    for i, (u, v) in enumerate(uv_values):
        v2d_array[i] = imath.V2d(u, v)
    prop.set_value(v2d_array)

    # V2dArray is not in cask's POD_EXTENT mapping, so set _datatype explicitly
    prop._datatype = alembic.AbcCoreAbstract.DataType(
        alembic.Util.POD.kFloat64POD, 2
    )

    prop.metadata['arrayExtent'] = '1'
    prop.metadata['geoScope'] = 'uni'
    prop.metadata['interpretation'] = 'vector'
    prop.metadata['isArray'] = '1'
    prop.metadata['isGeomParam'] = 'true'
    prop.metadata['podExtent'] = '2'
    prop.metadata['podName'] = 'float64_t'

    arbGeomParams.properties['groom_root_uv'] = prop


def collect_curves(obj, curves_list):
    """
    Recursively collect all Curve objects from the archive.

    :param obj: cask object (Top, Xform, Curve, etc.)
    :param curves_list: list to append Curve objects to
    """
    if obj.type() == "Curve":
        curves_list.append(obj)

    for child in obj.children.values():
        collect_curves(child, curves_list)


def derive_groom_name(curve_obj):
    """
    Derive groom_group_name from the curve's parent Xform path.

    Examples:
        /desc_b_splineDescription/SplineGrp0 -> desc_b
        /guide_grp/desc_b_Guides/xgGuide3_tempCurve -> desc_b
        /desc_a_follicles -> desc_a

    :param curve_obj: cask.Curve object
    :return: groom_group_name string
    """
    path = curve_obj.path()
    # Get the path parts
    # e.g., /desc_b_splineDescription/SplineGrp0 -> ['desc_b_splineDescription', 'SplineGrp0']
    # e.g., /guide_grp/desc_b_Guides/xgGuide3_tempCurve -> ['guide_grp', 'desc_b_Guides', 'xgGuide3_tempCurve']
    # e.g., /desc_a_follicles -> ['desc_a_follicles']
    parts = path.strip('/').split('/')

    for part in parts:
        # Handle XGen spline description: desc_b_splineDescription -> desc_b
        if '_splineDescription' in part:
            groom_name = part.split('_splineDescription')[0]
            return groom_name

        # Handle XGen guides: desc_b_Guides -> desc_b
        if '_guides' in part:
            groom_name = part.split('_guides')[0]
            return groom_name

        # Handle XGen follicles (guides): desc_a_follicles -> desc_a
        if '_follicles' in part:
            groom_name = part.split('_follicles')[0]
            return groom_name

    # Fallback: use the curve's own name
    return curve_obj.name


def restructure_strands(output_archive):
    """
    Restructure XGen spline hierarchy to match Maya's export format.

    Original: /description_splineDescription (Xform) -> /SplineGrp0 (Curve)
    Output:   /description_splineDescription (Curve directly)

    :param output_archive: cask.Archive to restructure
    :return: None (modifies archive in place)
    """
    # Find all splineDescription Xforms that need restructuring
    items_to_restructure = []
    for xform_name, xform in list(output_archive.top.children.items()):
        if '_splineDescription' not in xform_name:
            continue
        if xform.type() != "Xform":
            continue  # Already a Curve, skip
        items_to_restructure.append((xform_name, xform))

    for xform_name, xform in items_to_restructure:
        # Find the first Curve child (usually SplineGrp0)
        curve_child = None
        for child_name, child in xform.children.items():
            if child.type() == "Curve":
                curve_child = child
                break

        if curve_child is None:
            log.warning(f'  Warning: No Curve found under {xform_name}, skipping')
            continue

        # Remove the Xform and replace with the Curve directly
        del output_archive.top.children[xform_name]

        # Rename the curve to match the description name
        curve_child._name = xform_name
        output_archive.top.children[xform_name] = curve_child

        log.info(f'  Restructured: {xform_name} (Xform->Curve)')


def merge_and_process_abc(strands_abc, guides_abc, groom_abc, fps=24,
                          patches_abc=None, mesh_map_json=None):
    """
    Merge multiple Alembic files, restructure strands, add groom attributes to strands only,
    and write to output.

    Args:
        strands_abc (str): path to strands .abc file (XGen splineDescription)
        guides_abc (str): path to guides .abc file (XGen Guides/follicles)
        groom_abc (str): path to groom .abc file (contains both strands and guides)
        fps (int): frames per second for the output archive
        patches_abc (str): optional path to patches .abc file (mesh with UVs)
        mesh_map_json (str): optional path to description_mesh_map.json
    """

    # Collect all children from all input files first
    all_children = {}  # name -> child object
    source_archives = []  # keep references alive to prevent GC
    patches_archive = None  # set lazily in the UV branch below

    strands_archive = cask.Archive(strands_abc, fps=fps)
    guides_archive = cask.Archive(guides_abc, fps=fps)
    groom_archive = guides_archive

    # xgmSplineCache (the exporter behind strands.abc) has no
    # equivalent of AbcExport's -stripNamespaces flag, so strand
    # IObjects come in as 'charA1:fawei_a_splineDescription' even
    # though the follicles in guides.abc are clean. That breaks two
    # things:
    #   * the user-visible "object names should have no namespace"
    #     contract that the follicles already satisfy, and
    #   * the mesh_map.get(groom_name) lookup that adds
    #     groom_root_uv - get_description_mesh_map() keys are
    #     namespace-stripped, so 'charA1:fawei_a' never matches and
    #     the UV property silently never gets written.
    # Stripping here fixes both at once.
    _strip_top_level_namespaces(strands_archive)
    _strip_top_level_namespaces(guides_archive)

    for archive in [strands_archive, guides_archive]:
        log.info(f'Reading: {archive}')
        source_archives.append(archive)  # prevent GC of source archives
        log.info(f'  Frame range: {archive.start_frame()} - {archive.end_frame()}, FPS: {archive.fps}')

        # Copy all children from source archive
        for name, child in archive.top.children.items():
            child_type = child.type()
            log.info(f'  Copying: {child.path()} (type: {child_type})')
            all_children[name] = child


    # Restructure strands hierarchy - need to do this before adding to output
    # Find all splineDescription Xforms that need restructuring
    items_to_restructure = []
    for name, obj in list(all_children.items()):
        if '_splineDescription' not in name:
            continue
        if obj.type() != "Xform":
            continue  # Already a Curve, skip
        items_to_restructure.append((name, obj))

    log.info('\nRestructuring strands hierarchy:')
    for xform_name, xform in items_to_restructure:
        # Find the first Curve child (usually SplineGrp0)
        curve_child = None
        for child_name, child in xform.children.items():
            if child.type() == "Curve":
                curve_child = child
                break

        if curve_child is None:
            log.warning(f'  Warning: No Curve found under {xform_name}, skipping')
            continue

        # Replace the Xform with the Curve
        curve_child._name = xform_name
        all_children[xform_name] = curve_child
        log.info(f'  Restructured: {xform_name} (Xform->Curve)')

    # Group children by groom name for proper ordering
    # groom_name -> {'follicles': obj, 'splineDescription': obj}
    groom_groups = {}

    for name, child in all_children.items():
        if '_follicles' in name:
            groom_name = name.replace('_follicles', '')
            if groom_name not in groom_groups:
                groom_groups[groom_name] = {}
            groom_groups[groom_name]['follicles'] = (name, child)
        elif '_splineDescription' in name:
            groom_name = name.replace('_splineDescription', '')
            if groom_name not in groom_groups:
                groom_groups[groom_name] = {}
            groom_groups[groom_name]['splineDescription'] = (name, child)
        else:
            # Other objects, add to a special group
            if '__other__' not in groom_groups:
                groom_groups['__other__'] = {}
            groom_groups['__other__'][name] = (name, child)

    # Add children to output archive in proper order:
    # For each groom group (sorted by name), add follicles first, then splineDescription
    log.info('\nOrdering children:')
    log.info(f'  Groom groups found: {sorted(groom_groups.keys())}')
    for groom_name in sorted(groom_groups.keys()):
        if groom_name == '__other__':
            continue
        group = groom_groups[groom_name]
        log.info(f'  Processing group: {groom_name}, has: {list(group.keys())}')

        # Add follicles first
        if 'follicles' in group:
            name, child = group['follicles']
            groom_archive.top.children[name] = child
            log.info(f'    Added: {name}')

        # Then splineDescription
        if 'splineDescription' in group:
            name, child = group['splineDescription']
            groom_archive.top.children[name] = child
            log.info(f'    Added: {name}')

    # Verify order in groom_archive
    log.info('\n  Verification - children order in groom_archive:')
    for i, name in enumerate(list(groom_archive.top.children.keys())[:10]):
        log.info(f'    {i}: {name}')

    # Add any other objects at the end
    if '__other__' in groom_groups:
        for name, (n, child) in groom_groups['__other__'].items():
            groom_archive.top.children[name] = child
            log.info(f'  Added (other): {name}')

    # Collect all Curve objects from merged archive
    all_curves = []
    collect_curves(groom_archive.top, all_curves)
    log.info(f'\nTotal curves found: {len(all_curves)}')

    if not all_curves:
        log.info('No curves found in the archives.')
        return

    # Separate strands and guides
    strands = []
    guides = []
    for curve in all_curves:
        path = curve.path()
        if '_splineDescription' in path:
            strands.append(curve)
        elif '_guides' in path:
            guides.append(curve)

    # Sort strands by groom_group_name
    strand_info = []
    for curve in strands:
        groom_name = derive_groom_name(curve)
        strand_info.append((groom_name, curve))
    strand_info.sort(key=lambda x: x[0])

    # Assign groom_group_id based on unique groom_group_name
    name_to_id = {}
    current_id = 0

    log.info('\nAdding groom attributes (strands only):')
    for groom_name, curve in strand_info:
        if groom_name not in name_to_id:
            name_to_id[groom_name] = current_id
            current_id += 1

        groom_group_id = name_to_id[groom_name]
        log.info(f'  Curve: {curve.path()}')
        log.info(f'    groom_group_name: {groom_name}')
        log.info(f'    groom_group_id: {groom_group_id}')

        add_groom_attributes(curve, groom_name, groom_group_id)

    # Add groom_root_uv if mesh data is provided
    if patches_abc and mesh_map_json:
        if TRIMESH_AVAILABLE and SCIPY_AVAILABLE and NUMPY_AVAILABLE:
            log.info('\nAdding groom_root_uv (trimesh closest-point - fast):')
        elif SCIPY_AVAILABLE and NUMPY_AVAILABLE:
            log.info('\nAdding groom_root_uv (scipy nearest-vertex - fast, less accurate):')
        else:
            log.info('\nAdding groom_root_uv (pure-Python BVH - accurate, no deps):')
        mesh_map = load_description_mesh_map(mesh_map_json)

        # Open patches.abc ONCE and reuse for all meshes (lazy loading)
        log.info(f"  Opening patches.abc: {patches_abc}")
        patches_archive = cask.Archive(patches_abc)  # noqa: F841 (also released at function exit)

        # Pre-load and triangulate meshes, build BVH (cache by transform name)
        mesh_cache = {}  # transform_name -> (triangles, bvh)

        for groom_name, curve in strand_info:
            mesh_transforms = mesh_map.get(groom_name)
            if not mesh_transforms:
                log.warning(f'  Warning: No mesh mapping for groom "{groom_name}", skipping UV')
                continue

            transform_name = mesh_transforms[0]
            if transform_name not in mesh_cache:
                mesh_data = load_mesh_from_abc(patches_archive, transform_name)
                triangles = triangulate_mesh(
                    mesh_data['positions'], mesh_data['face_counts'],
                    mesh_data['face_indices'], mesh_data['uv_vals'],
                    mesh_data['uv_indices'],
                )
                bvh = build_triangle_bvh(triangles)
                mesh_cache[transform_name] = (triangles, bvh)
                log.info(f'  Loaded mesh: {transform_name} ({len(triangles)} triangles, BVH built)')

            triangles, bvh = mesh_cache[transform_name]
            roots = get_curve_root_positions(curve)
            uv_values = find_closest_uv_on_mesh(roots, triangles, bvh=bvh)
            add_groom_root_uv(curve, uv_values)
            log.info(f'  {curve.path()}: {len(uv_values)} UV values')
            # for i, (u, v) in enumerate(uv_values):
            #     log.info(f'    [{i}] u={u:.6f}, v={v:.6f}')

    # Print summary
    log.info(f'\nSummary:')
    log.info(f'  Strands curves: {len(strands)} (attributes added)')
    log.info(f'  Guides curves: {len(guides)} (attributes from Maya)')
    log.info(f'  Total curves: {len(all_curves)}')

    # Align groom_group_id across follicles + strands so curves
    # sharing groom_group_name share the same id. UE Groom Import
    # pairs guides with strands by id - if a row's follicle is id
    # 22 but the matching strand is id 21 (because the strand list
    # is missing one name from the follicle list, e.g. brow_a),
    # UE never pairs them and the group renders empty on one side.
    # The known-good reference file has fully-aligned ids; we have
    # to too. This pass walks every Curve, collects unique names,
    # and rewrites groom_group_id 1:1 with name.
    _align_groom_group_ids(groom_archive)

    log.info(f'\nWriting: {groom_abc}')
    groom_archive.write_to_file(groom_abc)

    # Forcibly release every cask archive so the underlying alembic
    # IArchive destructors run NOW instead of at some indeterminate
    # GC pass. Without this, Windows keeps a read lock on the input
    # files and the caller can't os.remove() the intermediates or
    # re-export to the same paths on the next run.
    _release_archives(
        [strands_archive, guides_archive, groom_archive, patches_archive],
        source_archives, all_children,
    )

    log.info('Done!')


def _release_archives(archives, *aux_collections):
    """Null out cask's internal alembic refs on each archive in
    ``archives`` and clear any auxiliary collections that might hold
    child / curve references. Then force a GC pass.

    The attribute names matter: ``cask.Archive`` stores its
    underlying ``alembic.Abc.IArchive`` in ``self._iobject`` (NOT
    ``_iarchive``, which doesn't exist), and the cask-side Top
    wrapper in ``self._top``. Both have to be nulled out for the
    IArchive's refcount to drop to zero so Windows releases the
    underlying file handle. Earlier code targeted ``_iarchive`` and
    silently never released anything.

    Used at the end of any function that opened cask archives for
    read. Without this, the next AbcExport / ``os.remove`` on the
    same path hits ``WinError 32`` (file in use).
    """
    seen = set()
    for arc in archives:
        if arc is None or id(arc) in seen:
            continue
        seen.add(id(arc))
        for attr in ('_top', '_iobject'):
            try:
                setattr(arc, attr, None)
            except Exception:
                pass
    for col in aux_collections:
        try:
            col.clear()
        except AttributeError:
            try:
                del col[:]
            except Exception:
                pass
    gc.collect()


def _align_groom_group_ids(archive):
    """Re-number every Curve's ``groom_group_id`` so curves that
    share ``groom_group_name`` also share an id.

    UE Groom Import pairs guide and strand curves by ``groom_group_id``.
    If follicles are numbered 0..22 (including ``brow_a``) but strands
    are numbered 0..21 (no ``brow_a`` because brow has no spline
    description), the same name ends up with different ids on its two
    halves. UE then can't pair them, and the affected group renders
    with one half empty (the user-visible "curve 0" symptom).

    The known-good reference file ships with aligned ids - same name,
    same id, across follicles and strands. This pass produces the
    same shape.

    Implementation: walk every Curve once, collect the set of unique
    ``groom_group_name`` values, sort alphabetically, and rewrite
    each Curve's ``groom_group_id`` so id ↔ name is 1:1.
    """
    name_to_curves = {}
    for top_child in archive.top.children.values():
        for curve in _iter_curves(top_child):
            try:
                arb = curve.properties['.geom'].properties['.arbGeomParams']
                name = arb.properties['groom_group_name'].values[0][0]
            except (KeyError, IndexError, AttributeError):
                continue
            # Some splineDescription names carry a leading '|' (e.g.
            # '|fawei_a' in the reference file) - normalise for the
            # key so the strand and follicle halves share a bucket.
            key = name.lstrip('|')
            name_to_curves.setdefault(key, []).append(curve)

    if not name_to_curves:
        return

    ordered = sorted(name_to_curves.keys())
    name_to_id = {n: i for i, n in enumerate(ordered)}
    log.info(
        '_align_groom_group_ids: %d unique groom names -> ids 0..%d',
        len(ordered), len(ordered) - 1,
    )

    for key, curves in name_to_curves.items():
        new_id = name_to_id[key]
        for curve in curves:
            try:
                arb = curve.properties['.geom'].properties['.arbGeomParams']
                prop = arb.properties.get('groom_group_id')
            except (KeyError, AttributeError):
                continue
            if prop is None:
                continue
            arr = imath.ShortArray(1)
            arr[0] = new_id
            # clear + set so we replace the existing sample rather
            # than appending a second one (cask's set_value with no
            # explicit index appends).
            prop.clear_values()
            prop.set_value(arr)


def _strip_top_level_namespaces(archive):
    """Rename every ``archive.top`` child whose name carries a
    leading ``<namespace>:`` so the colon-prefix is removed.

    Mirrors what ``AbcExport -stripNamespaces`` does, for archives
    produced by tools (like ``xgmSplineCache``) that don't expose
    that flag. We only walk top-level - nested children either
    inherit the cleaned parent path or get pulled to the top by
    :func:`restructure_strands` later.

    Collisions (two namespaces would produce the same clean name)
    are skipped with a warning so we don't silently overwrite one
    description with another - in practice this only matters when a
    shot file mixes ``charA:guide_grp`` and ``charA1:guide_grp`` in
    the SAME export, which the per-character row split already
    prevents.
    """
    children = archive.top.children
    renames = []
    for name in list(children.keys()):
        if ':' not in name:
            continue
        clean = name.rsplit(':', 1)[-1]
        if not clean or clean == name:
            continue
        if clean in children:
            log.warning(
                'Skipping namespace strip for %r - %r already exists '
                'in the archive', name, clean,
            )
            continue
        renames.append((name, clean))
    for old, new in renames:
        obj = children.pop(old)
        try:
            obj._name = new
        except Exception:
            pass
        children[new] = obj
        log.info('Stripped namespace: %s -> %s', old, new)


def _safe_remove(path, retries=8, initial_delay=0.05):
    """Delete ``path`` with Windows-friendly retry / backoff.

    Cask + alembic don't release their file handles instantly even
    after :func:`_release_archives` runs - on local disks the file
    is usually free within one tick, but Z: network shares can keep
    the handle alive for a few hundred ms. We escalate the wait
    between tries instead of failing the export outright.

    Returns True on success, False if every retry hit
    ``WinError 32``. ``FileNotFoundError`` is treated as success
    (the goal is "file is not there", which it isn't).
    """
    import time as _time
    delay = initial_delay
    for attempt in range(retries):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            if attempt == retries - 1:
                log.warning(
                    'Could not remove %s after %d attempts: %s',
                    path, retries, exc,
                )
                return False
            gc.collect()
            _time.sleep(delay)
            delay = min(delay * 2, 0.5)
    return False


def _safe_replace(src, dst, retries=8, initial_delay=0.05):
    """``os.replace(src, dst)`` with the same Windows-friendly retry /
    backoff as :func:`_safe_remove`.

    A lingering cask read handle on ``dst`` (handles don't always drop
    the instant :func:`_release_archives` runs, especially on network
    shares) makes the replace fail with ``WinError 5/32``. Retrying with
    a ``gc.collect`` between attempts gives the IArchive destructor time
    to run. Raises the last error if every attempt fails.
    """
    import time as _time
    delay = initial_delay
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except OSError:
            if attempt == retries - 1:
                raise
            gc.collect()
            _time.sleep(delay)
            delay = min(delay * 2, 0.5)
