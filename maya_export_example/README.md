# maya_export_example

Scripts for exporting XGen groom data from Maya and post-processing Alembic files for Unreal Engine.

---

## Exported Files

For example testing, All files are written to a per-character directory:
`/path/to/assets/CHARACTER/{character}/abc/`

### From `export_xgen_strands_and_guides.py` (run inside Maya)

#### Single-frame export (groom setup)

Output directory: `/path/to/assets/CHARACTER/{character}/abc/`

| File | Description |
|------|-------------|
| `strands.abc` | XGen spline descriptions exported via `cmds.xgmSplineCache()`. Contains the actual hair strands as Alembic Curves. |
| `guides.abc` | XGen guide curves exported via `cmds.AbcExport()`. Includes groom attributes (`groom_group_name`, `groom_group_id`, `groom_guide`, `riCurves`) set directly on the Maya transform before export. |
| `patches.abc` | Mesh patches (skin geometry) that the hair descriptions are bound to. Used later to compute root UV coordinates. |
| `description_mesh_map.json` | JSON mapping each XGen description name to its bound mesh patches. Example: `{"description1": ["pPlane1"]}`. Required by the post-process step to look up UVs per groom group. |

#### Animation export (per shot)

For example testing, Output directory: `/path/to/scenes/{scene}/{shot}/{character}/abc/`

| File | Description |
|------|-------------|
| `guides.abc` | Guide curves exported over a frame range. Imported into Unreal Engine as a **Groom Cache** to drive groom animation. Only guides are exported for animation (strands are driven by guides at runtime in UE). Carries the same groom attributes as the single-frame guides. |

### From `write_xgen_abc_attrs.py` (run via mayapy, after Maya export)

| File | Description |
|------|-------------|
| `groom.abc` | Final merged Alembic file imported into Unreal Engine as a **Groom Asset**. Contains both strands and guides. Strands have groom attributes (`groom_group_name`, `groom_group_id`, `groom_root_uv`) added to `.geom/.arbGeomParams`. Guide attributes come through unchanged from the Maya export. |

---

## Pipeline Order

```
Maya scene
    │
    ├── export_xgen_strands_and_guides.py  (inside Maya, single frame)
    │       │
    │       ├── strands.abc
    │       ├── guides.abc
    │       ├── patches.abc
    │       └── description_mesh_map.json
    │
    ├── export_xgen_strands_and_guides.py  (inside Maya, animation)
    │       │
    │       └── guides.abc  (per-shot, with frame range) ──► UE Groom Cache
    │
    └── write_xgen_abc_attrs.py  (mayapy, post-process)
            │
            └── groom.abc  ──► UE Groom Asset
```

## Attribute Details

| Attribute | Added by | Type | Scope | Purpose |
|-----------|----------|------|-------|---------|
| `groom_group_name` | Maya export (guides) / post-process (strands) | `StringArray` | — | Identifies the groom group name |
| `groom_group_id` | Maya export (guides) / post-process (strands) | `ShortArray` | constant | Numeric ID per groom group, required by UE |
| `groom_guide` | Maya export (guides only) | `short` | constant | Marks curves as guide curves |
| `groom_root_uv` | post-process (strands only) | `V2dArray` | uniform | Root UV on the skin mesh for each strand |
| `riCurves` | Maya export | `bool` | — | Forces Maya to export curves as a single group |
