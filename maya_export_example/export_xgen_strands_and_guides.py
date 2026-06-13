#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Creating Attributes
import os
import json
from maya import cmds


def get_description_mesh_map():
    # {'GroundPlane_Collection': ['description8']}
    palette_descriptions_map = {}
    # for palette in xg.palettes():
    #     descriptions = xg.descriptions(palette)
    #     palette_descriptions_map[palette] = list(descriptions)

    '''
    |pPlane1
    |pPlane1|pPlaneShape1
    |collection1
    |collection1|description1
    |collection1|description1|description1Shape
    |collection1|description1|pPlane1_description1
    |collection1|description1|pPlane1_description1|pPlane1_description1Shape
    '''
    cmds.select(clear=True)

    description_mesh_map = {}

    # ['description1Shape']
    descriptions_shape = cmds.ls(type='xgmDescription')
    for description_shape in descriptions_shape:
        # ['description1']
        description = cmds.listRelatives(description_shape, parent=True, path=True)[0]
        description_short_name = description.split('|')[-1]
        # Record description and its mesh patches
        description_mesh_map[description_short_name] = []

        # ['pPlane1_description1Shape']
        patches_shape = cmds.listRelatives(description, type='xgmSubdPatch', allDescendents=True, path=True)
        for patch_shape in patches_shape:
            # Geometry Shape
            # ['pPlaneShape1']
            conns = cmds.listConnections(patch_shape + '.geometry', source=True, destination=False, shapes=True, skipConversionNodes=True)
            # Means has patch geometry
            if conns:
                # 'pPlaneShape1'
                geometry_shape = conns[0]
                # 'pPlane1'
                geometry = cmds.listRelatives(geometry_shape, parent=True, fullPath=True)[0]
                # {'my_description1': [['|pPlane1']]}
                description_mesh_map[description_short_name].append(geometry)

    return description_mesh_map

def get_repeated_names():
    repeated_names = []
    for node in cmds.ls():
        if '|' in node:
            repeated_names.append(cmds.ls(node, long=True))
    return repeated_names

def rollback_guide_attributes(guide_groups, rollback_map, delete_guide_groups=True):
    for uuid, target_parent in rollback_map.items():
        from_guide_group = cmds.ls(uuid)[0]
        cmds.parent(from_guide_group, target_parent, shape=True, absolute=True)

    if delete_guide_groups:
        cmds.delete(guide_groups)


# Create Guide Attributes
def create_guide_attributes(root='xgGroom', suffix='_guides'):
    attr_name = 'groom_guide'
    groups = cmds.listRelatives(root, fullPath=True)
    groups.sort()
    output_guides_group = []
    rollback_map = {}

    for groom_group_id, group in enumerate(groups):
        print('group', group)

        # '|xgGroom|description_a_Guides'
        group_name = group.split('|')[-1]

        # create new group
        guides_group = cmds.createNode('transform', name=group_name)
        print('guides_group', guides_group)
        output_guides_group.append(guides_group)

        # set groom_group_name
        # 'description_a_Guides' -> 'description_a'
        groom_group_name = group_name.strip('|')
        _index = group_name.lower().rfind(suffix.lower())
        if _index != -1:
            groom_group_name = group_name[:_index].strip('|')
        # groom_group_name = group_name.split(suffix)[0].strip('|')
        print('groom_group_name', groom_group_name)
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

    # if cmds.objExists(root):
    #     cmds.delete(root)
    return output_guides_group, rollback_map


# Create Group ID Attributes
def create_group_id_attributes(groups):
    attr_name = 'groom_group_id'

    for groom_group_id, group_name in enumerate(groups):
        try:
            # set groom_group_name
            # 'description_a_Guides' -> 'description_a'
            groom_group_name = group_name.split('_splineDescription')[0].strip('|')
            cmds.addAttr(group_name, longName='groom_group_name', dataType='string', keyable=True)
            cmds.setAttr('{}.groom_group_name'.format(group_name), groom_group_name, type='string')

            # tag group with group id
            cmds.addAttr(group_name, longName=attr_name, attributeType='short', defaultValue=groom_group_id, keyable=True)
            cmds.addAttr(group_name, longName='riCurves', attributeType='bool', defaultValue=1, keyable=True)

            # add attribute scope
            # forces Maya's alembic to export data as GeometryScope::kConstantScope
            cmds.addAttr(group_name, longName='{}_AbcGeomScope'.format(attr_name), dataType='string', keyable=True)
            cmds.setAttr('{}.{}_AbcGeomScope'.format(group_name, attr_name), 'con', type='string')
        except Exception as e:
            raise e


def export_groom(groups, export_dir, frame_start=0, frame_end=0):
    for groom_group_id, group_name in enumerate(groups):
        # Export Alembic Command
        cmds.select(group_name, replace=True)
        root = cmds.ls(group_name, long=True)[0]
        # AbcExport -j "-frameRange 0 0 -attr groom_group_id -attrPrefix xgen -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa -root |MyCharacter__root|hair|guide_grp|hair_style_a_follicles -file /path/to/output/folicles.abc";
        attrs = '-attr groom_group_id -attr groom_guide -attr groom_root_uv -attr groom_group_name -attrPrefix xgen'
        command = '-frameRange {} {} {} -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa -root {} -file {}/{}.abc'.format(
                frame_start,
                frame_end,
                attrs,
                root,
                export_dir,
                group_name
            )
        print('cmds.AbcExport(j="{}")'.format(command))
        cmds.AbcExport(j=command)
    print('Done!')


def export_group(groups, export_dir, file_name='guides', frame_start=0, frame_end=0):
    attrs = '-attr groom_group_id -attr groom_guide -attr groom_root_uv -attr groom_group_name -attrPrefix xgen'
    command = '-frameRange {} {} {} -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa'.format(frame_start, frame_end, attrs)
    cmds.select(groups, replace=True)

    for groom_group_id, group_name in enumerate(groups):
        # Export Alembic Command
        root = cmds.ls(group_name, long=True)[0]
        command += ' -root {}'.format(root)

    command += ' -file {}/{}.abc'.format(export_dir, file_name)

    print('cmds.AbcExport(j="{}")'.format(command))
    # AbcExport -j "-frameRange 0 0 -attr groom_group_id -attrPrefix xgen -uvWrite -wholeFrameGeo -worldSpace -eulerFilter -dataFormat ogawa -root |MyCharacter__root|hair|guide_grp|hair_style_a_follicles -file /path/to/output/folicles.abc";
    cmds.AbcExport(j=command)
    print('Done!')


def convert_to_interactive_groom(descriptions):
    if not descriptions:
        return []
    # ['face_description', 'hand_description']
    cmds.select(descriptions, replace=True)
    # ['face_description_splineDescriptionShape', 'hand_description_splineDescriptionShape']
    spline_description_shapes = cmds.xgmGroomConvert()
    # ['face_description_splineDescription', 'hand_description_splineDescription']
    spline_descriptions = cmds.listRelatives(spline_description_shapes, parent=True, fullPath=True)
    return spline_descriptions


def export_interactive_groom(spline_descriptions, export_dir, file_name, frame_start=0, frame_end=0):
    job_command = ''
    for spline_description in spline_descriptions:
        job_command += " -obj " + spline_description
    # '|my_description_splineDescription' -> 'my_description'
    # group_name = spline_description.split('|')[-1].split('_splineDescription')[0]
    # XXX:/dir/my_description.abc
    abc_file = os.path.join(export_dir, '{}.abc'.format(file_name))
    # Remove file
    if os.path.exists(abc_file):
        os.remove(abc_file)
    job_command += ' -file {}'.format(abc_file)
    job_command += ' -df "ogawa" -fr {} {} -step 1 -wfw'.format(
        frame_start,
        frame_end,
    )
    print("job_command = '{}'".format(job_command))
    cmds.xgmSplineCache(export=True, j=job_command)
    # Check file export success
    if os.path.exists(abc_file):
        print('Exported {} successfully!'.format(abc_file))




if __name__ == '__main__':
    # cmds.file('/path/to/your/character/source.mb', open=True, force=True)

    characters = ['MyCharacter']
    character = characters[0]
    suffixes = ['_guides', '_follicles']
    suffix = suffixes[0]

    export_single_frame = False
    if export_single_frame:
        # ---------- Export single frame ----------
        export_dir = '/path/to/CHARACTER/{}/abc'.format(character)
        None if os.path.exists(export_dir) else os.makedirs(export_dir)

        # Check first
        # repeated_names = get_repeated_names()
        # if repeated_names:
        #     raise ValueError('Repeated names: %s' % repeated_names)

        # Get description and its mesh patches mapping
        # {'my_description1': [['|pPlane1|pPlaneShape1']]}
        description_mesh_map = get_description_mesh_map()
        _dump_description_mesh_map = {}
        for k, v in description_mesh_map.items():
            _dump_description_mesh_map[k] = []
            for _v in v:
                _dump_description_mesh_map[k].append(_v.split('|')[-1])
        json.dump(_dump_description_mesh_map, open(os.path.join(export_dir, 'description_mesh_map.json'), 'w'), indent=4)

        # Export mesh patches
        mesh_patches = []
        for k, v in description_mesh_map.items():
            mesh_patches.extend(v)
        export_group(list(set(mesh_patches)), export_dir, file_name='patches')

        # Export strands
        input_descriptions = cmds.ls(type='xgmDescription', long=True)
        spline_descriptions = convert_to_interactive_groom(input_descriptions)
        # Warn about any description that produced no splineDescription.
        # xgmGroomConvert silently skips a description that generates 0
        # primitives (usually its XGen data - density paint map / clump
        # guides - is missing at the resolved xgDataPath), so the strands
        # for that groom group are absent with no error.
        def _short(p):
            return p.split('|')[-1].split(':')[-1]
        _got = {_short(s).replace('_splineDescription', '')
                for s in (spline_descriptions or [])}
        _missing = []
        for _shape in (input_descriptions or []):
            _parents = cmds.listRelatives(_shape, parent=True, fullPath=True) or []
            if _parents and _short(_parents[0]) not in _got:
                _missing.append(_short(_parents[0]))
        if _missing:
            print('WARNING: {} description(s) produced NO strands and were '
                  'skipped: {}'.format(len(_missing), ', '.join(sorted(_missing))))
            print('         Usual cause: missing XGen data at the resolved '
                  'xgDataPath -> 0 primitives. The groom will lack these groups.')
        export_interactive_groom(spline_descriptions, export_dir, file_name='strands')
        cmds.delete(spline_descriptions)

        # Export guides
        guides_group, rollback_map = create_guide_attributes(root='guide_grp', suffix=suffix)
        export_group(guides_group, export_dir, file_name='guides')
        rollback_guide_attributes(guides_group, rollback_map, delete_guide_groups=True)

    else:
        # ---------- Export animation (Only export guides) ----------
        # export_dir = '/path/to/scenes/{}/abc'.format(character)
        # export_dir = '/path/to/scenes/{}/xgen'.format(character)
        export_dir = 'C:/MyProject/samples/shot/xgen'
        None if os.path.exists(export_dir) else os.makedirs(export_dir)

        frame_start, frame_end =  250, 405
        # frame_start, frame_end =  101, 200
        frame_start, frame_end =  0, 30
        frame_start, frame_end =  1, 25
        guides_group, rollback_map = create_guide_attributes(root='guide_grp', suffix=suffix)
        export_group(guides_group, export_dir, file_name='guides', frame_start=frame_start, frame_end=frame_end)
        rollback_guide_attributes(guides_group, rollback_map, delete_guide_groups=True)


    # ---------- Single Test ----------
    # groups = cmds.ls(selection=True, long=True)
    # groups.sort()
    # create_group_id_attributes(groups)
    # export_group(groups, export_dir, file_name='strands_with_attr')

