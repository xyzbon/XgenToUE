"""XgenToUE drag-and-drop installer for Autodesk Maya.

USAGE
    1. In a running Maya session, drag this ``install_XgenToUE.py`` file
       from a file browser into the Maya viewport.
    2. A confirmation dialog appears once the install finishes.
    3. A shelf called ``XgenToUE`` is added to your shelf tabs with a
       single launch button.

    The file name is deliberately UNIQUE: Maya's drag-drop handler imports
    the dropped file as a module named after the file, and on a re-drag
    ``importlib.import_module`` returns the sys.modules-CACHED entry for
    that name instead of re-reading the file. A generic ``install.py``
    therefore collides with itself across re-drags and with OTHER tools'
    ``install.py`` dragged in the same session; ``install_XgenToUE``
    cannot collide.

WHAT IT DOES
    * Copies the unpacked XgenToUE package and the bundled ``lib/``
      directory into ``<userAppDir>/scripts/XgenToUE/``.
    * Creates the ``XgenToUE`` shelf and a launch button on it. The button
      itself puts the install folder on ``sys.path`` before importing, so
      it works in every future session WITHOUT touching ``userSetup.py``
      (a bootstrap block appended by older installers is removed).
    * Makes the freshly installed copy importable in the current session.
"""

import os
import shutil
import sys


SOURCE_NAME = 'XgenToUE'
PACKAGE_NAME = 'xgentoue'
INSTALL_ROOT_NAME = 'XgenToUE'

INCLUDES = (
    PACKAGE_NAME,
    'lib',
    'samples',
    'docs',
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
    'README.md',
    'README.txt',  # generated into the zip by build_release_zip.py
)

# The shelf button is self-bootstrapping: it resolves the install dir and
# puts it on sys.path BEFORE importing, so launching never depends on
# userSetup.py edits -- the shelf file Maya saves carries everything needed.
SHELF_COMMAND = """\
import os
import sys
from maya import cmds
_xg_root = os.path.join(cmds.internalVar(userAppDir=True), 'scripts', '{install_root}')
if _xg_root not in sys.path:
    sys.path.insert(0, _xg_root)
from xgentoue.launch import load
load()
""".format(install_root=INSTALL_ROOT_NAME)


def onMayaDroppedPythonFile(*_):
    """Entry point called by Maya when this file is dragged into the viewport."""
    try:
        _install()
    except Exception as exc:  # broad except — installer must never crash Maya
        import traceback
        traceback.print_exc()
        _confirm(
            'Install failed',
            'XgenToUE install failed:\n\n{}\n\nSee the Script Editor for details.'.format(exc),
            icon='critical',
        )
    finally:
        # Maya's drop handler loads this file via importlib.import_module,
        # which returns the CACHED module on a re-drag -- the second drag
        # would re-run whatever code the FIRST drag loaded (even after the
        # file changed on disk). Evict ourselves so every drag executes the
        # file actually dropped.
        if __name__ != '__main__':
            sys.modules.pop(__name__, None)


def _install():
    from maya import cmds, mel

    source_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(
        cmds.internalVar(userAppDir=True), 'scripts', INSTALL_ROOT_NAME,
    )

    # Dragging the installer from the installed folder itself (e.g. after
    # the manual zip-extract install, to get the shelf button) means there
    # is nothing to copy -- skip straight to the shelf/session wiring
    # instead of copying every file onto itself (shutil.SameFileError).
    if not _same_file(source_dir, target_dir):
        _copy_tree(source_dir, target_dir, INCLUDES)
    _remove_user_setup_block(cmds)
    _purge_stale_modules()
    _ensure_on_syspath(source_dir, target_dir)
    _ensure_shelf(cmds, mel)

    _confirm(
        'XgenToUE installed',
        'Installed into:\n{}\n\nA "{}" shelf has been added — click the button to launch.'.format(
            target_dir, INSTALL_ROOT_NAME,
        ),
    )


def _same_file(a, b):
    """True when ``a`` and ``b`` resolve to the same file/folder on disk.

    ``os.path.samefile`` sees through slash style, case, and junctions /
    symlinks; fall back to a normalized string compare when either path
    does not exist yet.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return (os.path.normcase(os.path.normpath(a))
                == os.path.normcase(os.path.normpath(b)))


def _copy_tree(source_dir, target_dir, includes):
    """Copy each entry in ``includes`` from ``source_dir`` to ``target_dir``.

    Files overwrite. Directories are merged: existing files in the target
    are overwritten, files only in the target are left alone.
    """
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)

    for name in includes:
        src = os.path.join(source_dir, name)
        dst = os.path.join(target_dir, name)
        if not os.path.exists(src):
            continue
        if os.path.isdir(src):
            _merge_dir(src, dst)
        elif not (os.path.exists(dst) and _same_file(src, dst)):
            shutil.copy2(src, dst)


def _merge_dir(src, dst):
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out_root = dst if rel == '.' else os.path.join(dst, rel)
        if not os.path.isdir(out_root):
            os.makedirs(out_root)
        for name in files:
            if name.endswith('.pyc') or '__pycache__' in root:
                continue
            src_f = os.path.join(root, name)
            dst_f = os.path.join(out_root, name)
            if os.path.exists(dst_f) and _same_file(src_f, dst_f):
                continue  # aliased via junction/symlink -- already in place
            shutil.copy2(src_f, dst_f)


def _remove_user_setup_block(cmds):
    """Strip the sys.path block OLDER installers appended to userSetup.py.

    The shelf button now bootstraps ``sys.path`` itself, so installing no
    longer modifies ``userSetup.py`` at all. This only removes the
    marker-delimited block a previous XgenToUE install added (if any),
    leaving everything else in the file untouched.
    """
    user_setup = os.path.join(
        cmds.internalVar(userAppDir=True), 'scripts', 'userSetup.py',
    )
    if not os.path.isfile(user_setup):
        return
    with open(user_setup, 'r', encoding='utf-8') as fh:
        lines = fh.readlines()

    out, skipping, removed = [], False, False
    for line in lines:
        if not skipping and '# --- XgenToUE bootstrap' in line:
            skipping = removed = True
            if out and out[-1].strip() == '':
                out.pop()  # the blank line the old block prepended
            continue
        if skipping:
            if '# --- end XgenToUE' in line:
                skipping = False
            continue
        out.append(line)

    if removed:
        with open(user_setup, 'w', encoding='utf-8') as fh:
            fh.writelines(out)


def _purge_stale_modules():
    """Evict cached ``xgentoue``/``cask`` modules from ``sys.modules``.

    If a launch was attempted earlier in this session (e.g. straight after a
    previous drag-install), Python cached those modules from wherever they
    were first found -- typically the unzipped drag-source folder. The cache
    wins over ``sys.path``, so without this the session keeps running the
    drag-source copy even after the install, and breaks entirely if the user
    then deletes that folder.
    """
    for name in list(sys.modules):
        if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + '.') or name == 'cask':
            del sys.modules[name]


def _ensure_on_syspath(source_dir, target_dir):
    """Put ``target_dir`` on ``sys.path`` so imports use the INSTALLED copy.

    Maya's drag-and-drop handler (``executeDroppedPythonFile``, same in Maya
    2022-2026) does ``sys.path.insert(0, <dropped dir>)`` before running this
    file and a blind ``sys.path.pop(0)`` after it returns. If we insert
    ``target_dir`` at 0 here, Maya's pop removes OUR entry and leaves the
    drag-source (e.g. ``Downloads/XgenToUE``) as the import source for the
    whole session. So while the drag-source sits at ``sys.path[0]``, slot the
    install dir in at index 1: the trailing pop then removes the source and
    leaves the install at the front.
    """
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    target_norm = norm(target_dir)
    if sys.path and norm(sys.path[0]) == norm(source_dir):
        # Mid-drop: Maya's entry for the dropped dir is at [0] and will be
        # popped. Keep it there UNTOUCHED -- even when the dropped dir IS the
        # install dir (installer dragged from the installed folder) -- and
        # slot our entry in right below, so the pop leaves ours at the front.
        head, rest = sys.path[0], sys.path[1:]
        sys.path[:] = [head, target_dir] + [p for p in rest if norm(p) != target_norm]
    else:
        sys.path[:] = [p for p in sys.path if norm(p) != target_norm]
        sys.path.insert(0, target_dir)

    # Belt and braces: once Maya is idle the drop handler has long returned
    # (and done its pop), so re-asserting the front slot then always sticks.
    def _reassert():
        sys.path[:] = [p for p in sys.path if norm(p) != target_norm]
        sys.path.insert(0, target_dir)
    try:
        import maya.utils
        maya.utils.executeDeferred(_reassert)
    except Exception:
        pass


def _ensure_shelf(cmds, mel):
    """Create (or refresh) a Maya shelf with a single XgenToUE launch button."""
    shelf_name = INSTALL_ROOT_NAME
    top_shelf = mel.eval('global string $gShelfTopLevel; $tmp = $gShelfTopLevel;')

    if not cmds.shelfLayout(shelf_name, exists=True):
        mel.eval('addNewShelfTab "{}"'.format(shelf_name))

    # Remove any existing XgenToUE buttons so re-running install replaces them.
    children = cmds.shelfLayout(shelf_name, query=True, childArray=True) or []
    for child in children:
        try:
            label = cmds.shelfButton(child, query=True, label=True)
        except RuntimeError:
            continue
        if label == 'XgenToUE':
            cmds.deleteUI(child)

    cmds.setParent(top_shelf + '|' + shelf_name)
    cmds.shelfButton(
        label='XgenToUE',
        annotation='Launch the XgenToUE XGen exporter',
        image='pythonFamily.png',
        imageOverlayLabel='Groom',
        sourceType='python',
        command=SHELF_COMMAND,
    )


def _confirm(title, message, icon='information'):
    try:
        from maya import cmds
        cmds.confirmDialog(title=title, message=message, button=['OK'], icon=icon)
    except Exception:
        print('[{}] {}'.format(title, message))
