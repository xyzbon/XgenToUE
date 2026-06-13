# XgenToUE samples

Ready-to-export demo scenes for verifying a fresh install. They use
classic (legacy) XGen descriptions, so they open and edit normally in the
XGen Editor. Authored in Maya 2024 — open in Maya 2024+.

## Important: set your Maya project first

These scenes form a Maya **project** (XGen resolves its data paths against
the project). Before opening anything:

> **File > Set Project...** and choose this `samples/` folder.

Then open the scenes below.

## Assets — `assets/charA/charA.ma`, `assets/charB/charB.ma`

Each is a single-character asset: a polygon mesh with one XGen description
(`hair` in charA, `fur` in charB — palettes `charA_col` / `charB_col`)
plus a `guide_grp` transform whose `<description>_guides` child holds
guide curves. Use these to test **Export Single Frame**.

## Shot — `scenes/shot.ma`

References both assets under namespaces `charA:` and `charB:`,
demonstrating the multi-character, namespace-scoped export. The two
characters are placed apart, and both their **meshes and guides** are
animated over **frames 1-25** (the scene runs at **25 fps / PAL**) — the
guides sway in a gentle up-and-down loop — so **Export Animation** produces
moving grooms. The shot workflow exports the guides over the frame range
and does not re-convert the referenced descriptions. The references are
project-relative, so keep `scenes/` and `assets/` together under this
project (and set the project to `samples/`).

## How to use

1. **Set Project** to this `samples/` folder.
2. Open `assets/charA/charA.ma` (or `scenes/shot.ma`).
3. Click the **XgenToUE** shelf button.
4. In *Source*, confirm **Guide Root** is `guide_grp` and click **Detect**
   (suffix `_guides`).
5. Tick the character row(s) and set each row's **Dir**.
6. *(Optional)* click **Check** — it should report no problems.
7. Click **Export Single Frame** (assets) or **Export Animation** (shot).

`groom.abc` in the chosen folder plus an export-complete log = your
install works.
