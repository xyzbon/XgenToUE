# Dependencies

**XgenToUE is dependency-free.** The `groom_root_uv` computation uses a
pure-Python closest-point-on-surface BVH that ships with the tool, so
there is **nothing to `pip install`**, no `mayapy` setup, and no per-Maya
wheel bundle to manage.

Just install the tool (drag `install_XgenToUE.py` into Maya) and export — it runs
the same on Windows, macOS, and Linux across Maya 2022–2026, with no
external packages.

The UVs come from a true closest-point-on-surface query, so they are
accurate; the backend is logged at INFO level in the tool's log panel on
each export.
