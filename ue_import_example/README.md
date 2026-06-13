# ue_import_example

Scripts for importing groom Alembic files into Unreal Engine as Groom Assets and Groom Caches.

---

## Scripts

| Script | Purpose |
|--------|---------|
| `import_groom_asset.py` | Imports `groom.abc` (merged strands + guides) as a **GroomAsset** |
| `import_groom_cache.py` | Imports animated `guides.abc` as a **GroomCache**, referencing an existing GroomAsset |

**Import order matters**: GroomAsset must be imported before GroomCache (the cache references the asset).

---

## Prerequisites

Enable these plugins in your UE project (Edit > Plugins):

- **Groom** (`HairStrandsCore`)
- **Alembic Hair Importer** (`AlembicHairImporter`)

---

## Path Mapping

### Groom Asset (single-frame, per character)

| | Path |
|---|---|
| Maya export | `/path/to/assets/CHARACTER/{character}/abc/groom.abc` |
| UE destination | `/Game/assets/CHARACTER/{character}/groom` |

### Groom Cache (animated, per shot)

| | Path |
|---|---|
| Maya export | `/path/to/scenes/{scene}/{shot}/{character}/abc/guides.abc` |
| UE destination | `/Game/scenes/{scene}/{shot}/{character}/guides_guides_cache` |

---

## How to Run

### Method 1 -- Commandlet (headless, recommended for CI/pipeline)

```
"<UEInstallDir>/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" ^
    "<YourProjectDir>/MyProject5_7/MyProject5_7.uproject" ^
    -run=pythonscript ^
    -script="<RepoRoot>/ue_import_example/import_groom_asset.py"
```

### Method 2 -- Full Editor (loads all assets, closes after)

```
"<UEInstallDir>/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe" ^
    "<YourProjectDir>/MyProject5_7/MyProject5_7.uproject" ^
    -ExecutePythonScript="<RepoRoot>/ue_import_example/import_groom_asset.py"
```

### Method 3 -- Interactive Editor (stays open)

```
"<UEInstallDir>/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe" ^
    "<YourProjectDir>/MyProject5_7/MyProject5_7.uproject" ^
    -ExecCmds="py <RepoRoot>/ue_import_example/import_groom_asset.py"
```

Replace `import_groom_asset.py` with `import_groom_cache.py` for cache import.

---

## Import Settings Reference

Settings match the Groom Import Options dialog (see screenshots).

### Conversion (both scripts)

| Setting | Value | Purpose |
|---------|-------|---------|
| Rotation | `(90.0, 0.0, 0.0)` | Maya Y-up to UE Z-up |
| Scale | `(1.0, -1.0, 1.0)` | Mirror Y axis for coordinate handedness |

### Groom Asset (`import_groom_asset.py`)

| Setting | Value |
|---------|-------|
| Detected Attributes | Root UV, Width |
| Groups | 2 (one per groom description) |

### Groom Cache (`import_groom_cache.py`)

| Setting | Value |
|---------|-------|
| Import Groom Cache | True |
| Import Type | Guides |
| Frame Start | 0 |
| Frame End | 30 |
| Skip Empty Frames | False |
| Import Groom Asset | False (already imported) |
| Groom Asset | `/Game/assets/CHARACTER/{character}/groom` |

---

## Troubleshooting

- **"GroomAsset not found"** -- Run `import_groom_asset.py` before `import_groom_cache.py`. The cache needs a reference to the asset.
- **Import produces no asset** -- Verify the Groom and AlembicHairImporter plugins are enabled and the project has been restarted after enabling them.
- **`HairStrandsFactory` not found** -- Some UE versions may not expose this class to Python. Try removing the `task.factory` line; UE can auto-detect the factory from the `.abc` extension.
- **Property name errors** -- `GroomCacheImportSettings` property names may vary by UE version. Check `dir(unreal.GroomCacheImportSettings())` in the UE Python console to see available properties.
- **Wrong orientation in viewport** -- Verify the conversion settings match: rotation `(90, 0, 0)` and scale `(1, -1, 1)`.

---

## Pipeline Order

```
Maya scene
    |
    +-- export_xgen_strands_and_guides.py  (single frame)
    |       |
    |       +-- strands.abc + guides.abc + patches.abc
    |
    +-- write_xgen_abc_attrs.py  (post-process)
    |       |
    |       +-- groom.abc
    |
    +-- import_groom_asset.py  (UE import)  <-- this folder
    |       |
    |       +-- /Game/.../groom  (GroomAsset)
    |
    +-- export_xgen_strands_and_guides.py  (animation)
    |       |
    |       +-- guides.abc  (per-shot, with frame range)
    |
    +-- import_groom_cache.py  (UE import)  <-- this folder
            |
            +-- /Game/.../guides_guides_cache  (GroomCache)
```
