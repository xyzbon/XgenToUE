#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Maya-side environment / robustness helpers.

Small utilities that harden the export against a Maya session that isn't
in the exact state the export code assumes:

* :func:`ensure_plugins_loaded` - load the plugins the export commands
  need (``xgmGroomConvert`` / ``AbcExport``) instead of failing with a
  cryptic "unknown command" error.
* :func:`suppress_xgen_ui_errors` - swallow the XGen FX-stack UI error
  spam that ``xgmGroomConvert`` / editor refreshes throw on scenes with
  broken modules.
* :func:`clean_xgen_preview` - quiet the live XGen preview before a
  timeline scrub so AbcExport doesn't re-evaluate it every frame.

Top-level imports are kept to the standard library + ``maya.cmds`` so
this module imports cleanly even without XGen present; ``mel`` and
``xgenm`` are imported lazily inside :func:`clean_xgen_preview`.
"""

import contextlib
import io
import logging
import sys

from maya import cmds

log = logging.getLogger('xgentoue')


def ensure_plugins_loaded(plugins=('xgenToolkit', 'AbcExport')):
    """Load each plugin in ``plugins`` if it isn't already loaded.

    The export pipeline calls ``cmds.xgmGroomConvert`` /
    ``cmds.xgmSplineCache`` (xgenToolkit) and ``cmds.AbcExport``
    (AbcExport). In a fresh Maya, a mayapy session, or a scene opened
    before the plugins auto-loaded, those commands don't exist yet and
    the export dies with a confusing ``RuntimeError: Unknown object
    type`` / ``AttributeError``. Loading them up front turns that into a
    clear, actionable failure.

    ``AbcImport`` is deliberately NOT included - xgentoue reads Alembic
    back with the pure-Python ``cask`` library, never through Maya.

    Raises:
        RuntimeError: if a required plugin cannot be loaded.
    """
    for plugin in plugins:
        try:
            already = cmds.pluginInfo(plugin, query=True, loaded=True)
        except RuntimeError:
            # Unknown / unregistered plugin name - treat as not loaded so
            # the loadPlugin below raises the friendlier message.
            already = False
        if already:
            continue
        try:
            cmds.loadPlugin(plugin)
        except RuntimeError as exc:
            raise RuntimeError(
                'Required Maya plugin {!r} could not be loaded: {}. Enable '
                'it in the Plug-in Manager and try again.'.format(plugin, exc)
            )
        log.info('Loaded Maya plugin %r', plugin)


@contextlib.contextmanager
def suppress_xgen_ui_errors():
    """Temporarily swallow XGen's UI error spam, then restore.

    Scenes where a description's FX stack has a broken module (e.g. an
    empty ``fxType``) make every ``setCurrentDescription`` /
    ``refresh("Full")`` - and the editor rebuild that ``xgmGroomConvert``
    triggers - raise ``KeyError('TabUI')`` inside
    ``xgFXStackTab.createModuleWidget``. That surfaces as a
    ``print("Error refreshing UI for ...")`` on stdout, a
    ``traceback.print_exc()`` on stderr, and a
    ``// Error: XGen: Object not found ...`` line in the script editor.
    These are pre-existing scene-data problems, not something our export
    caused, and they shouldn't flood the log on every export.

    This context manager redirects stdout/stderr and suppresses script
    editor output for the duration of the block, restoring everything on
    exit. The script-editor restore is deferred to the next event loop
    because XGen pushes its C++ "Object not found" prints through
    ``executeDeferred`` - so they don't actually print until after the
    ``with`` block ends.

    Note: this only quiets *display* output. It does not swallow real
    exceptions raised in the block, and it does not affect the export's
    own ``failed``-description detection (which is based on whether the
    converted node exists, not on parsed error text).
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_err = cmds.scriptEditorInfo(query=True, suppressErrors=True)
    old_warn = cmds.scriptEditorInfo(query=True, suppressWarnings=True)
    old_info = cmds.scriptEditorInfo(query=True, suppressInfo=True)
    old_result = cmds.scriptEditorInfo(query=True, suppressResults=True)

    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    cmds.scriptEditorInfo(
        edit=True,
        suppressErrors=True,
        suppressWarnings=True,
        suppressInfo=True,
        suppressResults=True,
    )

    def _restore_script_editor():
        try:
            cmds.scriptEditorInfo(
                edit=True,
                suppressErrors=old_err,
                suppressWarnings=old_warn,
                suppressInfo=old_info,
                suppressResults=old_result,
            )
        except Exception:
            pass

    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        # XGen rebuilds its UI through executeDeferred, so the C++ side
        # "// Error: XGen: Object not found ..." prints land AFTER this
        # block. Defer the scriptEditorInfo restore to the next event
        # loop so those late prints stay suppressed too.
        try:
            cmds.evalDeferred(_restore_script_editor, lowestPriority=True)
        except Exception:
            _restore_script_editor()


def clean_xgen_preview():
    """Turn off the live XGen preview before an export. Best-effort.

    A visible XGen preview re-evaluates on every timeline change, so a
    whole-timeline AbcExport pass pays that cost on every frame. Cleaning
    the preview first speeds the scrub up and avoids preview-related
    instability. This is purely a viewport/UI change - it does not touch
    the data being exported.

    Never raises: ``mel`` / ``xgenm`` are imported lazily and the whole
    body is guarded, so a missing module or an absent preview just logs
    at debug level and returns. The preview is left off (not restored) -
    regenerating it is expensive and the user explicitly asked to export.
    """
    try:
        import maya.mel as mel
        import xgenm.xgGlobal as xgg
    except Exception as exc:  # XGen not available / not initialised
        log.debug('clean_xgen_preview: XGen modules unavailable: %s', exc)
        return
    try:
        editor = getattr(xgg, 'DescriptionEditor', None)
        if editor and editor.isVisible():
            editor.setPlayblast(False)
        mel.eval('xgmPreview -clean')
        log.info('Cleaned XGen preview before export')
    except Exception as exc:
        log.debug('clean_xgen_preview failed (non-fatal): %s', exc)
