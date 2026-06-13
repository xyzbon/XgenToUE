"""Runtime sys.path injection for the OPTIONAL per-Maya site-packages dir.

XgenToUE is dependency-free by default (pure-Python UV computation), so
this is a no-op for most installs. If you opt into the C-backed speed
path by dropping ``trimesh`` + ``scipy`` wheels under
``<install_root>/lib/site-packages/maya<N>/``, this module detects the
running Maya version at import time and prepends the matching directory
to ``sys.path`` so those wheels become importable.

When that directory does not exist (the common case) we use whatever
``mayapy`` already has — and ultimately the pure-Python BVH path inside
:mod:`xgentoue.core.abc_process`.
"""

import os
import sys


def _resolve_install_root():
    """Return the directory that contains ``lib/site-packages/``.

    ``__file__`` lives at ``<install_root>/xgentoue/_bootstrap.py`` so the
    install root is two directories up.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def add_lib_dir():
    """Prepend the bundled ``lib/`` dir to ``sys.path``.

    The tool vendors its Alembic helper as ``lib/cask.py`` and imports it as
    a top-level module (``import cask``). The installer / userSetup only put
    the install ROOT on ``sys.path`` (so ``xgentoue`` imports), so without
    this ``cask`` is unresolvable from a clean install or an unzipped release
    -- it happened to work only because the dev harness inserts ``repo/lib``
    by hand. Returns the directory added, or ``None`` if it doesn't exist.
    Idempotent -- safe to call more than once.
    """
    lib_dir = os.path.join(_resolve_install_root(), 'lib')
    if not os.path.isdir(lib_dir):
        return None
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    return lib_dir


def _resolve_maya_version():
    """Return the running Maya major version, or ``None`` outside Maya."""
    try:
        from maya import cmds
    except ImportError:
        return None
    try:
        return int(cmds.about(version=True))
    except Exception:
        return None


def add_bundled_site_packages():
    """Prepend ``lib/site-packages/maya<N>/`` to ``sys.path`` if it exists.

    Returns the directory that was added, or ``None`` if no bundle matches.
    Safe to call multiple times — the same path is not added twice.
    """
    major = _resolve_maya_version()
    if major is None:
        return None
    # Maya 2026 ships Python 3.11, same ABI as Maya 2025, so they share a bundle.
    target = 2025 if major >= 2025 else major
    candidate = os.path.join(
        _resolve_install_root(), 'lib', 'site-packages', 'maya{}'.format(target)
    )
    if not os.path.isdir(candidate):
        return None
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
    return candidate
