#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Import an Alembic file as a Groom Asset in Unreal Engine.

This script creates a GroomAsset from a processed groom.abc file
(containing merged strands and guides with groom attributes).

Usage (UE Python console or commandlet):
    # Interactive
    import import_groom_asset
    import_groom_asset.import_groom_asset(
        abc_path='/path/to/CHARACTER/MyCharacter/abc/groom.abc',
        destination_path='/Game/assets/CHARACTER/MyCharacter',
        destination_name='groom',
    )

    # Commandlet (headless)
    UnrealEditor-Cmd.exe MyProject.uproject -run=pythonscript -script="import_groom_asset.py"

    # Full editor (closes after)
    UnrealEditor.exe MyProject.uproject -ExecutePythonScript="import_groom_asset.py"

    # Interactive editor (stays open)
    UnrealEditor.exe MyProject.uproject -ExecCmds="py import_groom_asset.py"

Prerequisites:
    - Groom plugin enabled in UE project
    - AlembicHairImporter plugin enabled in UE project
"""

import unreal


def import_groom_asset(abc_path, destination_path, destination_name,
                       rotation=(90.0, 0.0, 0.0),
                       scale=(1.0, -1.0, 1.0),
                       replace_existing=True,
                       save=True):
    """
    Import an Alembic file as a GroomAsset.

    :param abc_path: absolute path to the .abc file on disk
    :param destination_path: UE content path (e.g. '/Game/assets/CHARACTER/MyCharacter')
    :param destination_name: asset name without extension (e.g. 'groom')
    :param rotation: (X, Y, Z) conversion rotation in degrees (Maya Y-up to UE Z-up)
    :param scale: (X, Y, Z) conversion scale (mirror Y for coordinate handedness)
    :param replace_existing: overwrite if asset already exists
    :param save: auto-save after import
    :return: imported asset object, or None on failure
    """
    unreal.log('=' * 60)
    unreal.log('Import Groom Asset')
    unreal.log('=' * 60)
    unreal.log('  Source:      {}'.format(abc_path))
    unreal.log('  Destination: {}/{}'.format(destination_path, destination_name))
    unreal.log('  Rotation:    {}'.format(rotation))
    unreal.log('  Scale:       {}'.format(scale))

    # Conversion settings (Maya Y-up -> UE Z-up)
    conversion_settings = unreal.GroomConversionSettings()
    conversion_settings.rotation = unreal.Vector(*rotation)
    conversion_settings.scale = unreal.Vector(*scale)

    # Import options
    import_options = unreal.GroomImportOptions()
    import_options.conversion_settings = conversion_settings

    # Build the import task
    task = unreal.AssetImportTask()
    task.filename = abc_path
    task.destination_path = destination_path
    task.destination_name = destination_name
    task.automated = True
    task.replace_existing = replace_existing
    task.save = save
    task.factory = unreal.HairStrandsFactory()
    task.options = import_options

    # Execute
    unreal.log('\nImporting...')
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    # Check result
    imported_paths = task.get_editor_property('imported_object_paths')
    unreal.log('\nimported_paths')
    unreal.log('  {}'.format(imported_paths))

    if imported_paths:
        asset_path = str(imported_paths[0])
        unreal.log('\nSuccess!')
        unreal.log('  Imported asset: {}'.format(asset_path))

        asset = unreal.load_asset('{}/{}'.format(destination_path, destination_name))
        return asset
    else:
        # Fallback: check if the asset exists (some UE versions don't populate imported_object_paths)
        asset_path = '{}/{}'.format(destination_path, destination_name)
        asset = unreal.load_asset(asset_path)
        if asset:
            unreal.log('\nSuccess! (asset found at destination)')
            unreal.log('  Imported asset: {}'.format(asset_path))
            return asset

        unreal.log('\nFailed! No asset was imported.')
        unreal.log('  Check that the Groom and AlembicHairImporter plugins are enabled.')
        unreal.log('  Check that the source file exists: {}'.format(abc_path))
        return None


if __name__ == '__main__':
    # ---- Configuration ----
    character = 'MyCharacter'
    abc_path = '/path/to/CHARACTER/{}/abc/groom.abc'.format(character)
    destination_path = '/Game/assets/CHARACTER/{}'.format(character)
    destination_name = 'groom'

    # Maya Y-up to UE Z-up conversion (matches Groom Import Options dialog)
    rotation = (90.0, 0.0, 0.0)
    scale = (1.0, -1.0, 1.0)

    asset = import_groom_asset(
        abc_path=abc_path,
        destination_path=destination_path,
        destination_name=destination_name,
        rotation=rotation,
        scale=scale,
    )

    # Expected result:
    # /Script/HairStrandsCore.GroomAsset'/Game/assets/CHARACTER/MyCharacter/groom.groom'
