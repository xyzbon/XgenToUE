# XgenToUE

**XgenToUE** exports Maya XGen hair and guides as Unreal Engine
compatible Alembic with the metadata required by UE5's Groom system —
in one click.

It is dependency-free — the UV computation is pure-Python — so artists
do not need to `pip install` anything or touch `mayapy`.

## Demo

<video src="https://github.com/xyzbon/XgenToUE/raw/master/XgenToUE.mp4" controls width="100%"></video>

▶️ **[Watch the demo video](XgenToUE.mp4)** — a Maya XGen groom exported with
XgenToUE and imported into Unreal Engine 5 (in case the player above doesn't
load in your Markdown viewer).

---

## Supported Maya versions

| Maya | Python |
|------|--------|
| 2022 | 3.7    |
| 2023 | 3.9    |
| 2024 | 3.10   |
| 2025 | 3.11   |
| 2026 | 3.11   |

No setup is needed on any platform — XgenToUE is dependency-free (see
[docs/install_matrix.md](docs/install_matrix.md)).

## Install

1. Unzip the downloaded `XgenToUE_v<version>_win64.zip` anywhere on
   disk. Keep the folder structure intact.
2. With Maya running, drag the `install_XgenToUE.py` file from a file
   browser into the Maya viewport.
3. Wait for the *XgenToUE installed* confirmation dialog. A shelf
   named **XgenToUE** is now in your shelf tabs.

The installer copies the package into
`<Documents>/maya/scripts/XgenToUE/`. The shelf button itself puts that
folder on `sys.path` before launching, so it keeps working across Maya
restarts without modifying your `userSetup.py`.

### Manual install (no drag-and-drop)

Prefer not to run the installer? Extract the zip's `XgenToUE` folder
straight into `<Documents>/maya/scripts/` (so the tree is
`.../maya/scripts/XgenToUE/xgentoue/`), then launch with this snippet in
the Script Editor (Python) — middle-drag it onto a shelf to keep a
button:

```python
import os
import sys
from maya import cmds
_xg_root = os.path.join(cmds.internalVar(userAppDir=True), 'scripts', 'XgenToUE')
if _xg_root not in sys.path:
    sys.path.insert(0, _xg_root)
from xgentoue.launch import load
load()
```

This is exactly what the installer's shelf button runs — drag-and-drop
just saves you creating the button yourself. (You can also drag
`install_XgenToUE.py` from the extracted folder afterwards to create the
shelf button; it detects the in-place layout and skips the copy.)

## Quickstart

1. Open your scene (one or more XGen descriptions and a `guide_grp`
   transform). To try the bundled demo instead, **set your Maya project to
   the `samples/` folder** and open `samples/assets/charA/charA.ma` for a
   single frame (or `samples/scenes/shot.ma` for the animated multi-character
   demo) — see [samples/README.md](samples/README.md).
2. Click the **XgenToUE** shelf button.
3. In the *Source* panel, confirm the **Guide Root** matches your scene
   (default: `guide_grp`). Click **Detect** to auto-pick the suffix used
   by your guide groups (`_guides` or `_follicles`).
4. In the *Characters* list, tick the characters to export. Each row has
   its own **Dir** (output folder, defaulting to `<scene>/xgen` — use the
   **...** button to change it) plus optional **Prefix** / **Suffix** for
   the file names.
5. *(Optional)* Click **Check** to validate the scene before exporting —
   it flags descriptions with no paired guide group, missing mesh
   patches, and grooms that would come out empty, without writing
   anything.
6. Click **Export Single Frame** for a groom at the current frame, or
   switch to the **Export Animation** tab (set the frame range; leave
   **Clean XGen preview before export** ticked for a faster timeline
   scrub) and click **Export Animation**.

Outputs land in the chosen folder:

| File | Contents |
|------|----------|
| `groom.abc`            | Merged strands + guides with the UE-required attributes — **this is the file you import into Unreal**. |
| `strands.abc`          | XGen splineDescription cache, intermediate. |
| `guides.abc`           | Guide curves, intermediate. |
| `patches.abc`          | Mesh patches the XGen descriptions are bound to. |
| `description_mesh_map.json` | Description → mesh patch mapping. |
| `anim_meta.json`       | FPS + frame range (animation export only). |

Import `groom.abc` into Unreal Engine via the standard
*Import → Groom Asset* flow.

## Dependencies (none)

XgenToUE computes `groom_root_uv` with a **pure-Python**
closest-point-on-surface BVH that ships with the tool — no `pip`, no
bundled wheels, no `mayapy` setup. It works on any platform, on Maya
2022–2026, out of the box.

> **Design principle:** XgenToUE always uses the most accurate method
> available. The pure-Python BVH is a true closest-point-on-surface
> query, so the UVs are exactly as accurate as a C-backed library would
> produce — with nothing to install.

## Troubleshooting

**The shelf button does nothing / errors on launch.**
Open the Script Editor and look for the traceback. The most common
cause is a stale install: re-drag `install_XgenToUE.py` to refresh.

**`No guide_grp nodes found in scene`.**
XgenToUE looks for a transform called `guide_grp` (or any name you
type into the *Guide Root* field). Either rename your top guide
transform, or update the field and click *Detect*.

**Some hair is missing from the exported groom.**
A description that exports with 0 strands is usually missing its XGen
data (density paint map / clump guides) at the resolved data path, so it
generates no primitives. Click **Check** before exporting to see exactly
which descriptions are affected.

## License

XgenToUE is released under the [MIT License](LICENSE).
Bundled third-party software is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## References

* [Maya XGen documentation](https://help.autodesk.com/view/MAYAUL/2024/ENU/?guid=GUID-33ECC43B-5CF6-4BE1-8EAE-8C6C0D698020)
* [Unreal Engine — XGen guidelines for hair creation](https://dev.epicgames.com/documentation/en-us/unreal-engine/xgen-guidelines-for-hair-creation-in-unreal-engine)
