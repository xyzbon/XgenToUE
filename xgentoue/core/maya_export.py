#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Maya-side data collection and Alembic export helpers.

Runs inside ``maya.standalone`` / Maya GUI. The exposed helpers walk the XGen
scene graph (``xgmDescription``, ``xgmSubdPatch``) and produce the Alembic
files that :mod:`xgentoue.core.abc_process` later merges:

* :func:`get_description_mesh_map` builds the description-to-mesh mapping.
* :func:`create_guide_attributes` tags transient guide groups with the
  attributes required for round-tripping into Unreal Engine.
* :func:`export_interactive_groom` dumps strand caches via
  ``cmds.xgmSplineCache``.
* :func:`export_group` dumps guides and follicles via ``cmds.AbcExport``.
"""

import gc
import os
import json
import time
from maya import cmds

import logging

from xgentoue.core.maya_env import suppress_xgen_ui_errors

log = logging.getLogger('xgentoue')



# XGen "description" node types this tool understands: the legacy
# xgmDescription and the modern Interactive Groom xgmSplineDescription.
# The export handles both; these helpers let the preview / mesh-map see
# interactive grooms too (otherwise an interactive-groom-only scene looks
# empty to the preview even though it exports fine).
_DESCRIPTION_TYPES = ('xgmDescription', 'xgmSplineDescription')


def _bound_mesh_transforms(description_shape):
    """Return bound-mesh transform long paths for a description shape.

    Legacy ``xgmDescription`` binds through an ``xgmSubdPatch`` whose
    ``.geometry`` plug is connected to the mesh shape. An Interactive
    Groom ``xgmSplineDescription`` has no subd patch - its bind mesh
    sits upstream in the spline's construction history. Handle both.
    """
    meshes = []
    if cmds.nodeType(description_shape) == 'xgmSplineDescription':
        history = cmds.listHistory(description_shape) or []
        for mesh_shape in cmds.ls(history, type='mesh', long=True) or []:
            parent = cmds.listRelatives(mesh_shape, parent=True, fullPath=True)
            if parent:
                meshes.append(parent[0])
    else:
        description = cmds.listRelatives(
            description_shape, parent=True, fullPath=True,
        )[0]
        patches_shape = cmds.listRelatives(
            description, type='xgmSubdPatch', allDescendents=True, path=True,
        ) or []
        for patch_shape in patches_shape:
            conns = cmds.listConnections(
                patch_shape + '.geometry', source=True, destination=False,
                shapes=True, skipConversionNodes=True,
            )
            if conns:
                geometry = cmds.listRelatives(
                    conns[0], parent=True, fullPath=True,
                )
                if geometry:
                    meshes.append(geometry[0])
    # De-duplicate, preserving order.
    unique = []
    for mesh in meshes:
        if mesh not in unique:
            unique.append(mesh)
    return unique


def get_description_mesh_map(namespace=None):
    """Build ``{description_short_name: [mesh_long_paths]}``.

    When ``namespace`` is given (e.g. ``'charA1'``), only descriptions
    belonging to that Maya namespace are included. Without a filter,
    multi-reference scenes with ``charA:`` and ``charA1:`` would
    collide on the short-name dict key and the LAST one to be walked
    overwrites the others - the merge then sees only one character's
    mesh map and the wrong patches in patches.abc.
    """
    cmds.select(clear=True)

    description_mesh_map = {}

    # long=True so we can namespace-filter by the leading "|<ns>:" segment.
    descriptions_shape = cmds.ls(type=_DESCRIPTION_TYPES, long=True) or []
    for description_shape in descriptions_shape:
        if namespace and not _path_in_namespace(description_shape, namespace):
            continue
        description = cmds.listRelatives(
            description_shape, parent=True, fullPath=True,
        )[0]
        # Strip the leading "<namespace>:" and any trailing "Shape" so the
        # key matches what utils.list_xgm_description_transforms produces.
        description_short_name = description.split('|')[-1].rsplit(':', 1)[-1]
        if (description_short_name.endswith('Shape')
                and len(description_short_name) > len('Shape')):
            description_short_name = description_short_name[:-len('Shape')]
        description_mesh_map[description_short_name] = _bound_mesh_transforms(
            description_shape,
        )

    return description_mesh_map


def _path_in_namespace(long_path, namespace):
    """True when a Maya long DAG path lives in ``namespace``.

    Matches when ANY segment of the path starts with ``<ns>:`` -
    handles both the description shape itself being namespaced and
    its parent (the description transform) being namespaced.
    """
    if not namespace:
        return True
    token = ':{}:'.format(namespace)
    return (
        long_path.startswith('|{}:'.format(namespace))
        or token in long_path
    )


def list_xgm_descriptions_in_namespace(namespace):
    """Filtered companion to :func:`utils.list_xgm_descriptions`.

    Returns xgmDescription SHAPE long paths whose DAG path belongs
    to ``namespace``. An empty / None namespace returns all
    descriptions (the asset-file case).
    """
    descs = cmds.ls(type='xgmDescription', long=True) or []
    if not namespace:
        return descs
    return [d for d in descs if _path_in_namespace(d, namespace)]


def list_existing_spline_descriptions_in_namespace(namespace):
    """Return TRANSFORM long paths of xgmSplineDescription nodes in
    ``namespace``.

    A description that the artist created directly as an Interactive
    Groom (rather than converting from an xgmDescription) shows up
    as ``xgmSplineDescription`` already - ``xgmGroomConvert`` skips
    those. Returning them here lets the export include their
    strands too; without this they end up as guide-only groups in
    UE with "0 strand curves" (e.g. the user's ``brow_a``).

    Returns parent transforms - the same shape the export flow
    expects from :func:`convert_to_interactive_groom`.
    """
    shapes = cmds.ls(type='xgmSplineDescription', long=True) or []
    if namespace:
        shapes = [s for s in shapes if _path_in_namespace(s, namespace)]
    if not shapes:
        return []
    return cmds.listRelatives(shapes, parent=True, fullPath=True) or []


def _descriptions_without_strands(input_descriptions, converted_splines):
    """Short names of xgmDescriptions that produced no splineDescription.

    A description converts to ``<name>_splineDescription``. If
    xgmGroomConvert skips one (e.g. its XGen data is missing so it
    generates 0 primitives), it's absent from the converted list and
    the exported groom silently lacks those strands. Returns the
    short names so the caller can warn.
    """
    def short(path):
        return path.split('|')[-1].split(':')[-1]

    expected = {}  # short name -> description path
    for shape in input_descriptions:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if parents:
            expected[short(parents[0])] = parents[0]

    got = set()
    for spline in converted_splines:
        name = short(spline)
        if name.endswith('_splineDescription'):
            name = name[:-len('_splineDescription')]
        got.add(name)

    return [name for name in expected if name not in got]


def collect_spline_descriptions(namespace=None):
    """Return ``(all_splines, temp_to_delete, failed)`` for strand export.

    Combines two sources:
        1. ``xgmDescription`` nodes converted on-the-fly via
           ``xgmGroomConvert`` (transient - we created them, so
           the caller must delete them after the export).
        2. Pre-existing ``xgmSplineDescription`` nodes that the
           artist set up directly as Interactive Grooms (these
           stay - they're the artist's working data).

    The first two return values are parent transform long paths so
    the export can feed them to ``xgmSplineCache`` the same way.

    ``failed`` is the short names of any xgmDescription that produced
    no splineDescription (xgmGroomConvert skipped it - usually because
    its XGen data is missing at the resolved xgDataPath, so it
    generates 0 primitives). The caller should warn: those groom
    groups will be absent from the exported strands.
    """
    # 1. Convert old-style xgmDescriptions
    input_descriptions = list_xgm_descriptions_in_namespace(namespace)
    converted = convert_to_interactive_groom(input_descriptions)
    converted_set = set(converted)

    # Anything that went in but didn't come back out as a spline.
    failed = _descriptions_without_strands(input_descriptions, converted)

    # 2. Find pre-existing xgmSplineDescriptions - filter out the
    # ones we just created above (xgmGroomConvert produces nodes of
    # this type too, so they'd otherwise appear in BOTH lists).
    existing = [
        t for t in list_existing_spline_descriptions_in_namespace(namespace)
        if t not in converted_set
    ]

    return converted + existing, list(converted), failed

def get_description_mesh_map_by_path():
    """Like :func:`get_description_mesh_map` but keyed by description
    transform long path instead of the (namespace-stripped) short name.

    Multi-reference shots (e.g. ``charA``, ``charA1``, ``charA2``) have
    descriptions across different namespaces sharing the same short
    name. The short-name keyed version overwrites entries; this
    long-path keyed version keeps each character's mesh patches
    separately so the preview can scope correctly to the active
    character.
    """
    result = {}
    for shape in cmds.ls(type=_DESCRIPTION_TYPES, long=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        result[parents[0]] = _bound_mesh_transforms(shape)
    return result


# Create Guide Attributes
def create_guide_attributes(root='xgGroom', suffix='_guides'):
    attr_name = 'groom_guide'
    groups = cmds.listRelatives(root, fullPath=True)
    groups.sort()
    output_guides_group = []
    rollback_map = {}

    for groom_group_id, group in enumerate(groups):
        log.info('group %s', group)

        # '|xgGroom|description_a_Guides'
        group_name = group.split('|')[-1]

        # create new group
        guides_group = cmds.createNode('transform', name=group_name)
        log.info('guides_group %s', guides_group)
        output_guides_group.append(guides_group)

        # set groom_group_name
        # 'description_a_Guides' -> 'description_a'
        groom_group_name = group_name.strip('|')
        _index = group_name.lower().rfind(suffix.lower())
        if _index != -1:
            groom_group_name = group_name[:_index].strip('|')
        # groom_group_name = group_name.split(suffix)[0].strip('|')
        log.info('groom_group_name %s', groom_group_name)
        cmds.addAttr(guides_group, longName='groom_group_name', dataType='string', keyable=True)
        cmds.setAttr('{}.groom_group_name'.format(guides_group), groom_group_name, type='string')

        # set groom_group_id
        cmds.addAttr(guides_group, longName='groom_group_id', attributeType='short', defaultValue=groom_group_id, keyable=True)

        # tag group as groom_guide
        cmds.addAttr(guides_group, longName=attr_name, attributeType='short', defaultValue=1, keyable=True)

        # forces Maya's alembic to export curves as one group.
        cmds.addAttr(guides_group, longName='riCurves', attributeType='bool', defaultValue=1, keyable=True)

        # add attribute scope
        # forces Maya's alembic to export data as GeometryScope::kConstantScope
        cmds.addAttr(guides_group, longName='{}_AbcGeomScope'.format(attr_name), dataType='string', keyable=True)
        cmds.setAttr('{}.{}_AbcGeomScope'.format(guides_group, attr_name), 'con', type='string')

        # parent curves under guides group
        # get curves under xgGroom
        curves = cmds.listRelatives(group, allDescendents=True, type='nurbsCurve', path=True, noIntermediate=True)
        for curve in curves:
            uuid = cmds.ls(curve, uuid=True)[0]
            parent = cmds.listRelatives(curve, parent=True, fullPath=True)[0]
            rollback_map[uuid] = parent
            cmds.parent(curve, guides_group, shape=True, absolute=True)

    return output_guides_group, rollback_map


def _safe_replace(tmp_path, dst_path, retries=8, initial_delay=0.05):
    """``os.replace`` with Windows-friendly retry / backoff.

    A cask/alembic read handle a previous merge left on ``dst_path``
    (or antivirus / Z: network-share latency) can make the atomic swap
    fail with ``PermissionError [WinError 5]``. ``gc.collect()`` nudges
    any unreferenced cask archive into its C++ destructor; we then back
    off and retry before finally raising.
    """
    delay = initial_delay
    for attempt in range(retries):
        try:
            os.replace(tmp_path, dst_path)
            return
        except OSError:
            if attempt == retries - 1:
                raise
            gc.collect()
            time.sleep(delay)
            delay = min(delay * 2, 1.0)


def export_group(groups, export_dir, file_name='guides', frame_start=0, frame_end=0):
    """Run AbcExport for ``groups`` and atomically swap the result
    into ``<export_dir>/<file_name>.abc``.

    The temp-file + rename detour matters because cask (used by the
    merge step) doesn't release Windows file handles promptly even
    after our explicit ``_release_archives`` and ``gc.collect``. If
    a previous merge read the same path, writing straight to it
    hits ``RuntimeError: Can't write to file``. Writing to ``.tmp``
    sidesteps the lock entirely; ``os.replace`` is atomic on
    Windows (Python 3.3+) so consumers always see either the old
    file or the fully-written new one.

    A best-effort ``gc.collect`` at the start nudges any lingering
    cask refs from a previous export pass into destruction before
    the new write begins - cheap insurance.
    """
    gc.collect()

    abc_path = '{}/{}.abc'.format(export_dir, file_name)
    tmp_path = abc_path + '.tmp'
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    attrs = '-attr groom_group_id -attr groom_guide -attr groom_root_uv -attr groom_group_name -attrPrefix xgen'
    command = '-frameRange {} {} {} -stripNamespaces -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa'.format(frame_start, frame_end, attrs)
    cmds.select(groups, replace=True)

    for groom_group_id, group_name in enumerate(groups):
        # Export Alembic Command
        root = cmds.ls(group_name, long=True)[0]
        command += ' -root {}'.format(root)

    command += ' -file {}'.format(tmp_path)

    log.info('cmds.AbcExport(j="{}")'.format(command))
    # Example: AbcExport -j "-frameRange 0 0 -attr groom_group_id -attrPrefix xgen -stripNamespaces -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa -root |groom_grp|desc_a_follicles -file C:/exports/desc_a_follicles.abc";
    cmds.AbcExport(j=command)
    _safe_replace(tmp_path, abc_path)
    log.info('Wrote %s', abc_path)


_ABC_EXPORT_ATTRS = (
    '-attr groom_group_id -attr groom_guide -attr groom_root_uv '
    '-attr groom_group_name -attrPrefix xgen'
)
_ABC_EXPORT_FLAGS = (
    '-stripNamespaces -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa'
)


def export_groups_batch(jobs):
    """Run a SINGLE ``cmds.AbcExport`` call with N jobs.

    Each ``job`` becomes one ``-j`` spec inside the same AbcExport
    invocation, which means Maya scrubs the timeline once for the
    entire batch instead of once per character. For a 5-character
    shot at 1000 frames this turns ~5x the timeline cost into ~1x.

    Args:
        jobs: list of dicts. Each dict has:
            - ``groups``: list of guide-group transforms to export
              under ``-root`` for this job (one .abc, possibly
              multiple roots - same shape as :func:`export_group`).
            - ``export_dir``: writable directory.
            - ``file_name``: filename stem (no ``.abc``).
            - ``frame_start`` / ``frame_end``: per-job range. The
              speedup is biggest when all jobs share a range
              because Maya can advance the timeline once and write
              every output simultaneously.

    Jobs are submitted in list order; failure mid-batch leaves
    earlier files written and later files not - matching the
    natural AbcExport semantics.
    """
    if not jobs:
        return
    gc.collect()  # Release any lingering cask read handles first.

    # Build each job with a .tmp output path so a stale read lock on
    # the final path doesn't block the writer. We track the
    # tmp->final pairs for the atomic rename after AbcExport returns.
    job_strings = []
    rename_pairs = []
    for job in jobs:
        roots = ' '.join(
            '-root {}'.format(cmds.ls(g, long=True)[0])
            for g in job['groups']
        )
        abc_path = '{}/{}.abc'.format(job['export_dir'], job['file_name'])
        tmp_path = abc_path + '.tmp'
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        spec = (
            '-frameRange {fs} {fe} {attrs} {flags} {roots} '
            '-file {tmp}'
        ).format(
            fs=job['frame_start'], fe=job['frame_end'],
            attrs=_ABC_EXPORT_ATTRS, flags=_ABC_EXPORT_FLAGS,
            roots=roots, tmp=tmp_path,
        )
        job_strings.append(spec)
        rename_pairs.append((tmp_path, abc_path))
    log.info(
        'cmds.AbcExport with %d jobs in one timeline pass', len(job_strings),
    )
    cmds.AbcExport(j=job_strings)
    for tmp_path, abc_path in rename_pairs:
        _safe_replace(tmp_path, abc_path)
    log.info('Wrote %d file(s)', len(rename_pairs))


def convert_to_interactive_groom(descriptions):
    if not descriptions:
        return []
    # ['face_description', 'hand_description']
    cmds.select(descriptions, replace=True)
    # ['face_description_splineDescriptionShape', 'hand_description_splineDescriptionShape']
    # xgmGroomConvert rebuilds the XGen editor UI; on scenes with a
    # broken FX-stack module that throws KeyError('TabUI') / "Object not
    # found" spam. Suppress that display noise around the convert (real
    # exceptions still propagate, and failed-description detection is
    # based on the resulting node list, not on parsed error text).
    with suppress_xgen_ui_errors():
        spline_description_shapes = cmds.xgmGroomConvert()
    # xgmGroomConvert returns None / [] when it converts nothing (e.g. a
    # referenced description it can't edit). Guard so callers always get a
    # list back, never None.
    if not spline_description_shapes:
        return []
    # ['face_description_splineDescription', 'hand_description_splineDescription']
    spline_descriptions = cmds.listRelatives(
        spline_description_shapes, parent=True, fullPath=True,
    )
    return spline_descriptions or []


def export_interactive_groom(spline_descriptions, export_dir, file_name, frame_start=0, frame_end=0):
    job_command = ''
    for spline_description in spline_descriptions:
        job_command += " -obj " + spline_description
    abc_file = os.path.join(export_dir, '{}.abc'.format(file_name))
    # Remove file
    if os.path.exists(abc_file):
        os.remove(abc_file)
    job_command += ' -file {}'.format(abc_file)
    job_command += ' -df "ogawa" -fr {} {} -step 1 -wfw'.format(
        frame_start,
        frame_end,
    )
    log.info("job_command = '{}'".format(job_command))
    cmds.xgmSplineCache(export=True, j=job_command)
    # Check file export success
    if os.path.exists(abc_file):
        log.info('Exported {} successfully!'.format(abc_file))
