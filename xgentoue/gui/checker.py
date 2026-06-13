#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only scene validation for the XgenToUE tool's "Check" button.

:func:`check_scene` runs the same pairing/coverage rules the preview
table already shows PLUS a dry-run strand conversion that catches
descriptions which would export 0 strands - something the live preview
cannot know without actually converting. It writes nothing and leaves
the scene exactly as it found it.

Lives in ``gui/`` (not ``core/``) because it composes the GUI-side
preview builder (:mod:`xgentoue.gui.utils`) with a core dry-run - the
same layering :mod:`xgentoue.gui.main_window` already uses. Putting it in
``core/`` would create a core -> gui import cycle.
"""

import dataclasses
import logging

from maya import cmds

from xgentoue.core.maya_env import (
    ensure_plugins_loaded,
    suppress_xgen_ui_errors,
)
from xgentoue.core.maya_export import collect_spline_descriptions
from xgentoue.gui import utils

log = logging.getLogger('xgentoue')


@dataclasses.dataclass
class CheckIssue:
    """One finding from :func:`check_scene`.

    severity : one of ``utils.STATUS_OK`` / ``STATUS_WARNING`` /
               ``STATUS_ERROR`` - reuses the preview's status vocabulary.
    target   : the scene-side thing the issue is about (description /
               guide group name, optionally namespace-qualified).
    message  : human-readable explanation.
    """

    severity: str
    target: str
    message: str


def _row_namespaces(rows):
    """Distinct namespaces among ``rows`` (order-preserving).

    A row with no namespace (single-character asset file) contributes
    ``None`` which scopes the checks to the whole scene. Returns
    ``[None]`` when there are no rows so the button still works before
    the user ticks anything.
    """
    namespaces = []
    for row in rows or []:
        ns = getattr(row, 'namespace', None) or None
        if ns not in namespaces:
            namespaces.append(ns)
    return namespaces or [None]


def _qualify(namespace, name):
    """Prefix ``name`` with its namespace for display, when present."""
    return '{}:{}'.format(namespace, name) if namespace else name


def _check_strands(namespace, issues):
    """Dry-run xgmGroomConvert for ``namespace`` and report empty grooms.

    This is the part the live preview can't do: a description can be
    present, bound to a mesh, and paired with a guide group yet still
    generate 0 primitives (e.g. its density paint map is missing at the
    resolved xgDataPath). We only learn that by converting.

    The conversion is wrapped in an undo chunk and the transient
    spline nodes it creates are deleted afterwards, so the scene is
    left untouched. Pre-existing artist-authored splines are NOT in the
    ``temp`` list and are never deleted.
    """
    opened = False
    temp_splines = []
    try:
        cmds.undoInfo(openChunk=True)
        opened = True
        # convert_to_interactive_groom already suppresses the FX-stack UI
        # spam around xgmGroomConvert; wrap the whole dry-run too so any
        # editor-refresh noise from the surrounding queries stays quiet.
        with suppress_xgen_ui_errors():
            _all_splines, temp_splines, failed = collect_spline_descriptions(
                namespace=namespace,
            )
        for name in sorted(failed):
            issues.append(CheckIssue(
                utils.STATUS_WARNING,
                _qualify(namespace, name),
                'Produces 0 strands - its XGen data (density paint map / '
                'clump guides) is likely missing at the resolved xgDataPath, '
                'so it would be absent from the exported groom.',
            ))
    except Exception as exc:  # never let the dry-run break the check
        issues.append(CheckIssue(
            utils.STATUS_WARNING,
            _qualify(namespace, '(strands)'),
            'Strand dry-run could not complete: {}'.format(exc),
        ))
    finally:
        if temp_splines:
            try:
                cmds.delete(temp_splines)
            except Exception as exc:
                log.debug('Dry-run temp cleanup failed: %s', exc)
        if opened:
            cmds.undoInfo(closeChunk=True)


def check_scene(rows, suffix, guide_root):
    """Validate the scene for a groom export. Returns ``[CheckIssue]``.

    Args:
        rows: the checked CharacterListPanel rows (used only to derive
            the set of namespaces to scope the checks to). May be empty
            - the whole scene is then checked.
        suffix: the guide-children suffix from the Source panel (e.g.
            ``'_guides'``).
        guide_root: the guide-root search string from the Source panel
            (e.g. ``'guide_grp'``).

    The result always contains at least one issue; when nothing is
    wrong it's a single ``STATUS_OK`` summary.
    """
    issues = []

    # 1. Plugins the export commands depend on.
    try:
        ensure_plugins_loaded()
    except RuntimeError as exc:
        issues.append(CheckIssue(utils.STATUS_ERROR, 'plugins', str(exc)))

    namespaces = _row_namespaces(rows)

    # 2. Reuse the preview's pairing / coverage rules. Every non-OK
    # PreviewRow becomes a CheckIssue - no duplicated logic.
    for ns in namespaces:
        try:
            preview = utils.frame_preview_groups(
                guide_root, suffix, namespace=ns,
            )
        except Exception as exc:
            issues.append(CheckIssue(
                utils.STATUS_ERROR,
                _qualify(ns, '(preview)'),
                'Could not build preview: {}'.format(exc),
            ))
            continue
        for prow in preview.all_rows():
            if prow.status == utils.STATUS_OK:
                continue
            issues.append(CheckIssue(
                prow.status,
                _qualify(ns, prow.name),
                prow.message or prow.detail or '',
            ))

    # 3. Dry-run strand conversion - the unique value over the preview.
    for ns in namespaces:
        _check_strands(ns, issues)

    # 4. All clear -> a single OK summary.
    has_problem = any(
        i.severity in (utils.STATUS_WARNING, utils.STATUS_ERROR)
        for i in issues
    )
    if not has_problem:
        count = len(utils.list_xgm_description_names())
        issues.append(CheckIssue(
            utils.STATUS_OK,
            'scene',
            '{} description(s) found - no problems detected.'.format(count),
        ))

    return issues
