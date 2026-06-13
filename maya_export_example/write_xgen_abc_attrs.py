#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Write groom_group_name and groom_group_id attributes to XGen Alembic curves.

This script reads an XGen spline Alembic file (exported from Maya), adds
groom_group_name (string) and groom_group_id (int16) attributes to each
Curve object's .arbGeomParams, and writes to a new output file.

Usage:
    mayapy write_xgen_abc_attrs.py
"""

import json
import os
import pathlib
import alembic
import imath
import cask

# Optional: numpy/trimesh/scipy for fast UV computation
NUMPY_AVAILABLE = False
TRIMESH_AVAILABLE = False
SCIPY_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    pass

try:
    import trimesh as _trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    pass

try:
    from scipy.spatial import cKDTree
    SCIPY_AVAILABLE = True
except ImportError:
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
        print(f'    Added .geom/.userProperties compound property (0 sub-properties)')


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
        print(f'    Removed .geom/uv property')


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
        print(f'    Removed property: {prop_name}')

    # Also remove 'uv' from under .geom
    remove_uv_from_geom(curve_obj)


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

    Returns dict like {"my_description1": ["|pPlane1"]}.
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

    xform = archive.top.children.get(transform_name)
    if xform is None:
        raise ValueError(f"Transform '{transform_name}' not found in {patches_abc}")

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

    # Fast path: trimesh (accurate + fast)
    if TRIMESH_AVAILABLE and NUMPY_AVAILABLE:
        return _find_uv_trimesh(query_points, triangles)

    # Medium path: scipy nearest-vertex (fast but less accurate)
    if SCIPY_AVAILABLE and NUMPY_AVAILABLE:
        return _find_uv_scipy(query_points, triangles)

    # Slow path: pure-Python BVH fallback
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
        /my_description_splineDescription/SplineGrp0 -> my_description
        /guide_grp/my_description_Guides/xgGuide3_tempCurve -> my_description
        /hair_out_a_follicles -> hair_out_a

    :param curve_obj: cask.Curve object
    :return: groom_group_name string
    """
    path = curve_obj.path()
    # Get the path parts
    # e.g., /my_description_splineDescription/SplineGrp0 -> ['my_description_splineDescription', 'SplineGrp0']
    # e.g., /guide_grp/my_description_Guides/xgGuide3_tempCurve -> ['guide_grp', 'my_description_Guides', 'xgGuide3_tempCurve']
    # e.g., /hair_out_a_follicles -> ['hair_out_a_follicles']
    parts = path.strip('/').split('/')

    for part in parts:
        # Handle XGen spline description: my_description_splineDescription -> my_description
        if '_splineDescription' in part:
            groom_name = part.split('_splineDescription')[0]
            return groom_name

        # Handle XGen guides: my_description_Guides -> my_description
        if '_guides' in part:
            groom_name = part.split('_guides')[0]
            return groom_name

        # Handle XGen follicles (guides): hair_out_a_follicles -> hair_out_a
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
            print(f'  Warning: No Curve found under {xform_name}, skipping')
            continue

        # Remove the Xform and replace with the Curve directly
        del output_archive.top.children[xform_name]

        # Rename the curve to match the description name
        curve_child._name = xform_name
        output_archive.top.children[xform_name] = curve_child

        print(f'  Restructured: {xform_name} (Xform->Curve)')


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

    strands_archive = cask.Archive(strands_abc, fps=fps)
    guides_archive = cask.Archive(guides_abc, fps=fps)
    groom_archive = guides_archive

    for archive in [strands_archive, guides_archive]:
        print(f'Reading: {archive}')
        source_archives.append(archive)  # prevent GC of source archives
        print(f'  Frame range: {archive.start_frame()} - {archive.end_frame()}, FPS: {archive.fps}')

        # Copy all children from source archive
        for name, child in archive.top.children.items():
            child_type = child.type()
            print(f'  Copying: {child.path()} (type: {child_type})')
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

    print('\nRestructuring strands hierarchy:')
    for xform_name, xform in items_to_restructure:
        # Find the first Curve child (usually SplineGrp0)
        curve_child = None
        for child_name, child in xform.children.items():
            if child.type() == "Curve":
                curve_child = child
                break

        if curve_child is None:
            print(f'  Warning: No Curve found under {xform_name}, skipping')
            continue

        # Replace the Xform with the Curve
        curve_child._name = xform_name
        all_children[xform_name] = curve_child
        print(f'  Restructured: {xform_name} (Xform->Curve)')

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
    print('\nOrdering children:')
    print(f'  Groom groups found: {sorted(groom_groups.keys())}')
    for groom_name in sorted(groom_groups.keys()):
        if groom_name == '__other__':
            continue
        group = groom_groups[groom_name]
        print(f'  Processing group: {groom_name}, has: {list(group.keys())}')

        # Add follicles first
        if 'follicles' in group:
            name, child = group['follicles']
            groom_archive.top.children[name] = child
            print(f'    Added: {name}')

        # Then splineDescription
        if 'splineDescription' in group:
            name, child = group['splineDescription']
            groom_archive.top.children[name] = child
            print(f'    Added: {name}')

    # Verify order in groom_archive
    print('\n  Verification - children order in groom_archive:')
    for i, name in enumerate(list(groom_archive.top.children.keys())[:10]):
        print(f'    {i}: {name}')

    # Add any other objects at the end
    if '__other__' in groom_groups:
        for name, (n, child) in groom_groups['__other__'].items():
            groom_archive.top.children[name] = child
            print(f'  Added (other): {name}')

    # Collect all Curve objects from merged archive
    all_curves = []
    collect_curves(groom_archive.top, all_curves)
    print(f'\nTotal curves found: {len(all_curves)}')

    if not all_curves:
        print('No curves found in the archives.')
        return

    # Separate strands and guides
    strands = []
    guides = []
    for curve in all_curves:
        path = curve.path()
        if '_splineDescription' in path:
            strands.append(curve)
        elif '_guides' in path or '_follicles' in path:
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

    print('\nAdding groom attributes (strands only):')
    for groom_name, curve in strand_info:
        if groom_name not in name_to_id:
            name_to_id[groom_name] = current_id
            current_id += 1

        groom_group_id = name_to_id[groom_name]
        print(f'  Curve: {curve.path()}')
        print(f'    groom_group_name: {groom_name}')
        print(f'    groom_group_id: {groom_group_id}')

        add_groom_attributes(curve, groom_name, groom_group_id)

    # Add groom_root_uv if mesh data is provided
    if patches_abc and mesh_map_json:
        if TRIMESH_AVAILABLE and NUMPY_AVAILABLE:
            print('\nAdding groom_root_uv (using trimesh - fast):')
        elif SCIPY_AVAILABLE and NUMPY_AVAILABLE:
            print('\nAdding groom_root_uv (using scipy cKDTree - fast, nearest-vertex):')
        else:
            print('\nAdding groom_root_uv (using pure-Python BVH fallback):')
        mesh_map = load_description_mesh_map(mesh_map_json)

        # Open patches.abc ONCE and reuse for all meshes (lazy loading)
        print(f"  Opening patches.abc: {patches_abc}")
        patches_archive = cask.Archive(patches_abc)

        # Pre-load and triangulate meshes, build BVH (cache by transform name)
        mesh_cache = {}  # transform_name -> (triangles, bvh)

        for groom_name, curve in strand_info:
            mesh_transforms = mesh_map.get(groom_name)
            if not mesh_transforms:
                print(f'  Warning: No mesh mapping for groom "{groom_name}", skipping UV')
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
                print(f'  Loaded mesh: {transform_name} ({len(triangles)} triangles, BVH built)')

            triangles, bvh = mesh_cache[transform_name]
            roots = get_curve_root_positions(curve)
            uv_values = find_closest_uv_on_mesh(roots, triangles, bvh=bvh)
            add_groom_root_uv(curve, uv_values)
            print(f'  {curve.path()}: {len(uv_values)} UV values')
            # for i, (u, v) in enumerate(uv_values):
            #     print(f'    [{i}] u={u:.6f}, v={v:.6f}')

    # Print summary
    print(f'\nSummary:')
    print(f'  Strands curves: {len(strands)} (attributes added)')
    print(f'  Guides curves: {len(guides)} (attributes from Maya)')
    print(f'  Total curves: {len(all_curves)}')

    # Write to output file
    print(f'\nWriting: {groom_abc}')
    groom_archive.write_to_file(groom_abc)
    print('Done!')


def get_arbGeomParams_info(curve_obj):
    """
    Get the .arbGeomParams properties info from a Curve object.

    :param curve_obj: cask.Curve object
    :return: dict of property name -> property info
    """
    info = {}
    geom = curve_obj.properties.get('.geom', None)
    if geom is None:
        return info

    arbGeomParams = geom.properties.get('.arbGeomParams', None)
    if arbGeomParams is None:
        return info

    for prop_name, prop in arbGeomParams.properties.items():
        prop_info = {
            'name': prop_name,
            'metadata': dict(prop.metadata) if hasattr(prop, 'metadata') else {},
        }
        # Try to get values
        try:
            values = prop.values
            if values:
                prop_info['values'] = [str(v)[:50] for v in values[:3]]  # First 3 values, truncated
        except:
            pass
        info[prop_name] = prop_info

    return info


def print_archive_structure(archive, label="Archive"):
    """
    Print detailed structure of an Alembic archive.

    :param archive: cask.Archive
    :param label: label for the archive
    """
    print(f'\n{"=" * 10} {label} {"=" * 10}')

    def print_obj(obj, indent=0):
        prefix = "  " * indent
        obj_type = obj.type()
        path = obj.path()

        # Get arbGeomParams info for Curves
        arbGeom_info = ""
        if obj_type == "Curve":
            params = get_arbGeomParams_info(obj)
            if params:
                param_names = sorted(params.keys())
                arbGeom_info = f"  arbGeomParams: {param_names}"

        print(f'{prefix}{obj_type}: {obj.name}  path={path}{arbGeom_info}')

        for child in obj.children.values():
            print_obj(child, indent + 1)

    print_obj(archive.top)


def compare_archives(archive1_path, archive2_path, fps=24):
    """
    Compare two Alembic archives in detail.

    :param archive1_path: path to first .abc file (real/correct)
    :param archive2_path: path to second .abc file (our output)
    :param fps: frames per second
    """
    archive1 = cask.Archive(archive1_path, fps=fps)
    archive2 = cask.Archive(archive2_path, fps=fps)

    print_archive_structure(archive1, f"real_groom_abc (correct)")
    print_archive_structure(archive2, f"output_abc (our output)")

    # Compare children at top level
    children1 = set(archive1.top.children.keys())
    children2 = set(archive2.top.children.keys())

    print(f'\n{"=" * 10} Comparison {"=" * 10}')

    missing_in_output = children1 - children2
    extra_in_output = children2 - children1

    if missing_in_output:
        print(f'\nMissing in output ({len(missing_in_output)}):')
        for name in sorted(missing_in_output):
            print(f'  - {name}')

    if extra_in_output:
        print(f'\nExtra in output ({len(extra_in_output)}):')
        for name in sorted(extra_in_output):
            print(f'  + {name}')

    # Compare common children
    common = children1 & children2
    print(f'\nCommon children: {len(common)}')

    # Check order
    list1 = list(archive1.top.children.keys())
    list2 = list(archive2.top.children.keys())

    print(f'\nOrder in real_groom_abc (first 10):')
    for i, name in enumerate(list1[:10]):
        print(f'  {i}: {name}')

    print(f'\nOrder in output_abc (first 10):')
    for i, name in enumerate(list2[:10]):
        print(f'  {i}: {name}')

    # Compare attributes for a sample curve
    print(f'\n{"=" * 10} Sample Curve Comparison {"=" * 10}')
    for name in sorted(common)[:4]:
        obj1 = archive1.top.children[name]
        obj2 = archive2.top.children[name]

        print(f'\nCurve: {name}')
        print(f'  Type in real: {obj1.type()}')
        print(f'  Type in output: {obj2.type()}')

        params1 = get_arbGeomParams_info(obj1)
        params2 = get_arbGeomParams_info(obj2)

        print(f'  arbGeomParams in real: {sorted(params1.keys())}')
        print(f'  arbGeomParams in output: {sorted(params2.keys())}')

        # Show details
        for pname in sorted(set(params1.keys()) | set(params2.keys())):
            p1 = params1.get(pname, {})
            p2 = params2.get(pname, {})
            if p1 != p2:
                print(f'    {pname}:')
                print(f'      real: {p1}')
                print(f'      output: {p2}')


if __name__ == '__main__':
    import time

    import sys
    # Add the repo root to sys.path so `import cask` resolves lib/cask.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

    # Merge multiple files and process (all in one go)
    characters = ['MyCharacter']
    character = characters[0]
    abc_dir = '/path/to/CHARACTER/{}/abc'.format(character)

    patches_abc = "{}/patches.abc".format(abc_dir)
    mesh_map_json = "{}/description_mesh_map.json".format(abc_dir)
    strands_abc = "{}/strands.abc".format(abc_dir)
    guides_abc = "{}/guides.abc".format(abc_dir)
    groom_abc = "{}/groom.abc".format(abc_dir)

    fps = 30
    # First, process the files
    start_time = time.time()
    merge_and_process_abc(
        strands_abc,
        guides_abc,
        groom_abc,
        fps=fps,
        patches_abc=patches_abc,
        mesh_map_json=mesh_map_json,
    )
    elapsed_time = time.time() - start_time
    print(f'\n{"=" * 50}')
    print(f'Total execution time: {elapsed_time:.2f} seconds')
    print(f'{"=" * 50}')

    # Then compare with the real groom abc
    # print('\n\n' + '=' * 60)
    # print('COMPARING OUTPUT WITH REAL GROOM ABC')
    # print('=' * 60)
    # real_groom_abc = "/path/to/CHARACTER/MyCharacter/abc/groom_correct.abc"
    # compare_archives(real_groom_abc, groom_abc, fps=fps)

