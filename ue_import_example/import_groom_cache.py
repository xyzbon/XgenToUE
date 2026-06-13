#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Import an Alembic file as a Groom Cache in Unreal Engine.

This script creates a GroomCache from an animated guides.abc file,
referencing an existing GroomAsset. The cache drives groom animation
at runtime (guides only, strands are simulated from guides in UE).

Usage (UE Python console or commandlet):
    # Interactive
    import import_groom_cache
    import_groom_cache.import_groom_cache(
        abc_path='/path/to/scenes/MyScene/MyShot/MyCharacter/abc/guides.abc',
        destination_path='/Game/scenes/MyScene/MyShot/MyCharacter',
        destination_name='guides_guides_cache',
        groom_asset_path='/Game/assets/CHARACTER/MyCharacter/groom',
    )

    # Commandlet (headless)
    UnrealEditor-Cmd.exe MyProject.uproject -run=pythonscript -script="import_groom_cache.py"

    # Full editor (closes after)
    UnrealEditor.exe MyProject.uproject -ExecutePythonScript="import_groom_cache.py"

    # Interactive editor (stays open)
    UnrealEditor.exe MyProject.uproject -ExecCmds="py import_groom_cache.py"

Prerequisites:
    - Groom plugin enabled in UE project
    - AlembicHairImporter plugin enabled in UE project
    - The referenced GroomAsset must already be imported (run import_groom_asset.py first)
"""

import unreal


def import_groom_cache(abc_path, destination_path, destination_name,
                       groom_asset_path,
                       frame_start=0, frame_end=30,
                       rotation=(90.0, 0.0, 0.0),
                       scale=(1.0, -1.0, 1.0),
                       replace_existing=True,
                       save=True):
    """
    Import an Alembic file as a GroomCache, referencing an existing GroomAsset.

    :param abc_path: absolute path to the animated guides .abc file on disk
    :param destination_path: UE content path (e.g. '/Game/scenes/MyScene/MyShot/MyCharacter')
    :param destination_name: asset name without extension (e.g. 'guides_guides_cache')
    :param groom_asset_path: UE content path to existing GroomAsset (e.g. '/Game/assets/CHARACTER/MyCharacter/groom')
    :param frame_start: first frame to import
    :param frame_end: last frame to import
    :param rotation: (X, Y, Z) conversion rotation in degrees
    :param scale: (X, Y, Z) conversion scale
    :param replace_existing: overwrite if asset already exists
    :param save: auto-save after import
    :return: imported asset object, or None on failure
    """
    unreal.log('=' * 60)
    unreal.log('Import Groom Cache')
    unreal.log('=' * 60)
    unreal.log('  Source:       {}'.format(abc_path))
    unreal.log('  Destination:  {}/{}'.format(destination_path, destination_name))
    unreal.log('  Groom Asset:  {}'.format(groom_asset_path))
    unreal.log('  Frame Range:  {} - {}'.format(frame_start, frame_end))
    unreal.log('  Rotation:     {}'.format(rotation))
    unreal.log('  Scale:        {}'.format(scale))

    # Load the existing GroomAsset
    groom_asset = unreal.load_asset(groom_asset_path)
    if groom_asset is None:
        unreal.log('\nError: GroomAsset not found at: {}'.format(groom_asset_path))
        unreal.log('  Import the GroomAsset first using import_groom_asset.py')
        return None
    unreal.log('\n  Loaded GroomAsset: {}'.format(groom_asset.get_path_name()))

    # Cache import settings
    cache_settings = unreal.GroomCacheImportSettings()
    cache_settings.import_groom_cache = True
    cache_settings.import_groom_asset = False  # already imported
    cache_settings.groom_asset = unreal.SoftObjectPath(groom_asset.get_path_name())
    cache_settings.frame_start = frame_start
    cache_settings.frame_end = frame_end
    cache_settings.skip_empty_frames = False

    # Import options
    # Note: GroomCacheImportOptions does not have conversion_settings.
    # Conversion is inherited from the referenced GroomAsset.
    import_options = unreal.GroomCacheImportOptions()
    import_options.import_settings = cache_settings

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
    if imported_paths:
        asset_path = str(imported_paths[0])
        unreal.log('\nSuccess!')
        unreal.log('  Imported asset: {}'.format(asset_path))

        asset = unreal.load_asset('{}/{}'.format(destination_path, destination_name))
        return asset
    else:
        # Fallback: check if the asset exists
        asset_path = '{}/{}'.format(destination_path, destination_name)
        asset = unreal.load_asset(asset_path)
        if asset:
            unreal.log('\nSuccess! (asset found at destination)')
            unreal.log('  Imported asset: {}'.format(asset_path))
            return asset

        unreal.log('\nFailed! No asset was imported.')
        unreal.log('  Check that the Groom and AlembicHairImporter plugins are enabled.')
        unreal.log('  Check that the source file exists: {}'.format(abc_path))
        unreal.log('  Check that the GroomAsset is valid: {}'.format(groom_asset_path))
        return None


if __name__ == '__main__':
    # ---- Configuration ----
    character = 'MyCharacter'

    # Source ABC (animated guides, per-shot)
    abc_path = '/path/to/scenes/MyScene/MyShot/{}/abc/guides.abc'.format(character)

    # UE destination
    destination_path = '/Game/scenes/MyScene/MyShot/{}'.format(character)
    destination_name = 'guides_guides_cache'

    # Reference to the already-imported GroomAsset
    groom_asset_path = '/Game/assets/CHARACTER/{}/groom'.format(character)

    # Frame range
    frame_start = 0
    frame_end = 30

    # Maya Y-up to UE Z-up conversion (matches Groom Import Options dialog)
    rotation = (90.0, 0.0, 0.0)
    scale = (1.0, -1.0, 1.0)

    asset = import_groom_cache(
        abc_path=abc_path,
        destination_path=destination_path,
        destination_name=destination_name,
        groom_asset_path=groom_asset_path,
        frame_start=frame_start,
        frame_end=frame_end,
        rotation=rotation,
        scale=scale,
    )

    # Expected result:
    # /Script/HairStrandsCore.GroomCache'/Game/scenes/MyScene/MyShot/MyCharacter/guides_guides_cache.guides_guides_cache'
