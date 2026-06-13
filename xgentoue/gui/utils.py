"""Shared GUI helpers for XgenToUE.

Pure helpers - no Qt widgets, no panel state. Anything that needs to be reused
across the source / output / action panels lives here, including the
preview-row builders that the Export Single Frame / Export Animation tabs use to
populate their preview tables.
"""

import dataclasses
import logging
import os
import subprocess
import sys

from maya import cmds
import maya.OpenMayaUI as OpenMayaUI

from xgentoue.core.maya_export import (
    get_description_mesh_map,
    get_description_mesh_map_by_path,
)
from xgentoue.gui.qtcompat import QtWidgets, wrapInstance

log = logging.getLogger('xgentoue')


# ----- status constants ----------------------------------------------------

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_ERROR = 'error'


@dataclasses.dataclass
class PreviewRow:
    """One row in a preview table.

    name      : the scene-side identifier shown to the user (original,
                unmodified)
    kind      : 'Description' / 'Guide Group' / 'Mesh Patch' / 'Reference'
    detail    : free-form context column (paired item, ref file basename, ...)
    output    : Alembic file name this row contributes to
    status    : 'ok' / 'warning' / 'error'
    message   : tooltip text for the status icon
    path      : full Maya DAG path used for selecting the underlying node
                when the user clicks the row (empty for synthetic rows)
    match_key : normalised form of ``name`` used for cross-kind pairing
                (e.g. Description ``brow_aShape`` paired with Guide
                ``brow_a_guides``). Defaults to ``name`` when empty.
    """

    name: str
    kind: str
    detail: str = ''
    output: str = ''
    status: str = STATUS_OK
    message: str = ''
    path: str = ''
    match_key: str = ''


def get_maya_main_window():
    """Return the QWidget wrapping Maya's main window (for parenting dialogs)."""
    ptr = OpenMayaUI.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def default_export_dir(last_used=''):
    """Pick the default export directory.

    Priority: (1) ``last_used`` (typically from QSettings), (2) the current
    Maya scene's parent directory, (3) empty string.
    No project-layout parsing — the previous heuristic baked in a
    studio-specific ``/assets/`` / ``/scenes/`` convention.
    """
    if last_used and os.path.isdir(last_used):
        return last_used
    scene_path = cmds.file(q=True, sceneName=True)
    if scene_path:
        return os.path.dirname(scene_path.replace('\\', '/'))
    return ''


def scene_xgen_dir():
    """Return ``<current_scene_parent>/xgen`` or empty if no scene is saved.

    This is the conventional per-shot drop point for groom Alembic
    files. Used as the per-character default Dir and by the various
    "reset to scene xgen" actions.
    """
    scene_path = cmds.file(q=True, sceneName=True) or ''
    if not scene_path:
        return ''
    scene_dir = os.path.dirname(scene_path.replace('\\', '/'))
    if not scene_dir:
        return ''
    return '{}/xgen'.format(scene_dir.rstrip('/'))


def find_guide_grps(guide_root):
    """Find guide-root transforms in the scene (namespaced and non-namespaced).

    Returns a list of long paths, de-duplicated.
    """
    namespaced = cmds.ls('*:' + guide_root, long=True, type='transform') or []
    plain = cmds.ls(guide_root, long=True, type='transform') or []
    seen = []
    for item in namespaced + plain:
        if item not in seen:
            seen.append(item)
    return seen


def detect_suffix(guide_root, candidates=('_guides',)):
    """Auto-detect the most common suffix used by children of ``guide_root``.

    Returns the best-matching suffix from ``candidates`` or ``None`` if no
    child name ended with any of them.
    """
    if not guide_root:
        return None
    roots = find_guide_grps(guide_root)
    if not roots:
        return None
    child_names = []
    for root in roots:
        child_names.extend(cmds.listRelatives(root, children=True) or [])
    if not child_names:
        log.debug('No children under guide root %r', guide_root)
        return None
    best = None
    best_count = 0
    for suffix in candidates:
        count = sum(1 for n in child_names if n.lower().endswith(suffix.lower()))
        if count > best_count:
            best_count = count
            best = suffix
    if best is None:
        log.debug(
            'No child of %r ended with any of %r', guide_root, candidates,
        )
    return best


def derive_export_name(grp_path, fallback='guides'):
    """Derive an Alembic file name from a guide-root transform.

    Uses the namespace as the file stem; if multiple references of the same
    file exist and the namespace ends with a trailing digit (e.g. ``hero``,
    ``hero1``, ``hero2``), the digit is preserved as a separator. If the node
    has no namespace, returns ``fallback``.
    """
    short = grp_path.split('|')[-1]
    if ':' not in short:
        return fallback
    namespace = short.rsplit(':', 1)[0]
    return namespace or fallback


def ensure_writable_dir(path):
    """Create ``path`` if missing and confirm it is writable.

    Raises :class:`PermissionError` (with a friendly message) if the directory
    cannot be created or is not writable.
    """
    if not path:
        raise ValueError('Export directory is not set.')
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError as exc:
            raise PermissionError(
                'Could not create export directory {!r}: {}'.format(path, exc)
            )
    if not os.access(path, os.W_OK):
        raise PermissionError(
            'Export directory {!r} is not writable.'.format(path)
        )
    return path


def reveal_in_explorer(path):
    """Open ``path`` in the OS file manager (Windows / macOS / Linux).

    Returns True on success, False if no suitable opener was available.
    """
    if not path or not os.path.exists(path):
        return False
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)  # noqa: S606  Windows-only API
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except OSError as exc:
        log.warning('Could not open %s: %s', path, exc)
        return False


# ----- xgmDescription queries ---------------------------------------------

def list_xgm_descriptions():
    """Return the long paths of every XGen description **shape** in the scene.

    Includes both legacy ``xgmDescription`` and Interactive Groom
    ``xgmSplineDescription`` shapes - the export handles both, so the
    preview surfaces both. Use :func:`list_xgm_description_names` when you
    want the short names artists see (and that guide groups match against).
    """
    return cmds.ls(
        type=('xgmDescription', 'xgmSplineDescription'), long=True,
    ) or []


def _strip_shape_suffix(name):
    """Strip a trailing ``Shape`` from a Maya node name (case-sensitive).

    Maya auto-suffixes shape nodes with ``Shape``; some XGen setups end
    up with that suffix baked into the description transform name as
    well. Stripping it normalises the artist-facing name so guide groups
    pair cleanly.
    """
    if name.endswith('Shape') and len(name) > len('Shape'):
        return name[:-len('Shape')]
    return name


def list_xgm_description_transforms():
    """Return ``[(short_name, long_path)]`` for every xgmDescription.

    ``short_name`` is the ORIGINAL xgmDescription SHAPE name (typically
    ends in ``Shape``) - that's the artist-facing identifier shown in
    the Outliner / XGen Editor and the one users expect to see in the
    preview. ``long_path`` is the parent transform's long DAG path,
    which is what downstream callers use to select the node in Maya
    and to look it up in the path-keyed mesh map.

    Callers pairing descriptions with guide groups (which never have
    ``Shape``) should apply :func:`_strip_shape_suffix` to compute a
    match key.

    Does NOT deduplicate by short name - in multi-reference scenes
    (e.g. ``charA``, ``charA1``, ``charA2``) several characters share the
    same short names. Each long path is a distinct description and
    must be returned so namespace-scoped filters can keep the right
    ones.
    """
    out = []
    seen_paths = set()
    for shape in list_xgm_descriptions():
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        long_path = parents[0]
        if long_path in seen_paths:
            continue
        seen_paths.add(long_path)
        # Pick the clean, artist-facing name. Legacy xgmDescription carries
        # it on the SHAPE (e.g. 'brow_aShape') - the parent transform is
        # Maya's auto-created grouping node. An Interactive Groom
        # xgmSplineDescription is the reverse: the TRANSFORM is clean
        # ('hair') and the shape is 'hair_Shape'. Either way a trailing
        # 'Shape' is stripped later for guide-group pairing.
        if cmds.nodeType(shape) == 'xgmSplineDescription':
            short = long_path.split('|')[-1].rsplit(':', 1)[-1]
        else:
            short = shape.split('|')[-1].rsplit(':', 1)[-1]
        out.append((short, long_path))
    return out


def list_xgm_description_names():
    """Return just the short names from :func:`list_xgm_description_transforms`."""
    return [name for name, _ in list_xgm_description_transforms()]


# ----- animation export plan (shared between preview + export flow) -------

def build_animation_plan(guide_grps):
    """Inspect each guide-root transform and decide where its output goes.

    Returns a list of tuples: ``(short_name, file_name, ref_file_or_None)``.
    The same list shape used by ``_export_animation`` so the preview and the
    actual export are guaranteed to agree.
    """
    plan = []
    for grp_path in guide_grps:
        short = grp_path.split('|')[-1]
        file_name = derive_export_name(grp_path)
        ref_file = None
        try:
            if cmds.referenceQuery(grp_path, isNodeReferenced=True):
                ref_node = cmds.referenceQuery(grp_path, referenceNode=True)
                ref_file = cmds.referenceQuery(
                    ref_node, filename=True, withoutCopyNumber=True,
                )
        except RuntimeError:
            pass
        plan.append((short, file_name, ref_file))
    return plan


# ----- preview row builders -----------------------------------------------

def _guide_child_entries(guide_root):
    """Return ``[(short_name, long_path)]`` for every direct child of
    ``guide_root`` (deduped). Namespaces stripped from the short name.
    """
    if not guide_root:
        return []
    seen_short = set()
    out = []
    for root in find_guide_grps(guide_root):
        for child in cmds.listRelatives(root, children=True, fullPath=True) or []:
            short = child.split('|')[-1].rsplit(':', 1)[-1]
            if short in seen_short:
                continue
            seen_short.add(short)
            out.append((short, child))
    return out


def _guide_child_names(guide_root):
    """Backwards-compatible name-only view of :func:`_guide_child_entries`."""
    return [name for name, _ in _guide_child_entries(guide_root)]


def _stem_for_guide_child(child_short, suffix):
    """Strip ``suffix`` (case-insensitive) from a guide group child name.

    Also strips any trailing underscore so the user can type either
    ``follicles`` or ``_follicles`` as the suffix and still get a clean
    stem (``hair_in_b_follicles`` -> ``hair_in_b`` either way).
    """
    if suffix:
        idx = child_short.lower().rfind(suffix.lower())
        if idx != -1:
            return child_short[:idx].rstrip('_')
    return child_short


def _matches_namespace(long_path, namespace):
    """Return True if ``long_path`` belongs to the given Maya namespace.

    Empty / None ``namespace`` matches everything (no filter).
    """
    if not namespace:
        return True
    token = ':{}:'.format(namespace)
    return token in long_path or long_path.startswith('|{}:'.format(namespace))


@dataclasses.dataclass
class FramePreview:
    """The Export Single Frame preview, partitioned by kind."""

    descriptions: list = dataclasses.field(default_factory=list)
    patches: list = dataclasses.field(default_factory=list)
    guides: list = dataclasses.field(default_factory=list)

    def all_rows(self):
        return self.descriptions + self.patches + self.guides

    def total(self):
        return len(self.descriptions) + len(self.patches) + len(self.guides)


def frame_preview_groups(guide_root, suffix, namespace=None,
                         groom_filename=None, patches_filename=None):
    """Build the Export Single Frame preview grouped by kind.

    Returns a :class:`FramePreview` with three parallel row lists:
    descriptions, mesh patches, and guide groups. Each list uses
    :class:`PreviewRow` and follows the same status / message rules the
    flat builder used.

    Args:
        guide_root: The guide-root search string (e.g. ``guide_grp`` or
            ``charB:guide_grp``).
        suffix: The guide-children suffix (e.g. ``_guides``).
        namespace: Optional Maya namespace string. If given, descriptions
            and mesh patches outside this namespace are filtered out.
            Pass an empty string or ``None`` to include everything (the
            default, used by single-character asset files).
        groom_filename: Optional override for the Output column on
            Description and Guide Group rows. Pass the decorated
            filename (e.g. ``'charB_groom_v02.abc'``) so the preview
            mirrors what the export flow will actually write. Falls
            back to ``'groom.abc'``.
        patches_filename: Same idea for Mesh Patch rows. Falls back to
            ``'patches.abc'``.
    """
    groom_filename = groom_filename or 'groom.abc'
    patches_filename = patches_filename or 'patches.abc'
    preview = FramePreview()

    # Path-keyed mesh map - safe for multi-reference shots where
    # several namespaces share the same description short names.
    mesh_map_by_path = {}
    try:
        mesh_map_by_path = get_description_mesh_map_by_path()
    except Exception as exc:  # best-effort; never block preview
        log.debug('get_description_mesh_map_by_path failed during preview: %s', exc)

    desc_entries = list_xgm_description_transforms()
    if namespace:
        desc_entries = [
            (n, p) for n, p in desc_entries if _matches_namespace(p, namespace)
        ]
        # Restrict the path-keyed mesh map to the descriptions that
        # survived the namespace filter.
        keep_paths = {p for _, p in desc_entries}
        mesh_map_by_path = {
            k: v for k, v in mesh_map_by_path.items() if k in keep_paths
        }
    # Per-description match key (Shape stripped) for cross-kind
    # pairing. The ORIGINAL ``desc`` stays in the row's ``name`` so
    # the user sees the real transform name in the preview.
    desc_match_by_orig = {desc: _strip_shape_suffix(desc) for desc, _ in desc_entries}
    desc_match_set = set(desc_match_by_orig.values())
    if not desc_entries:
        preview.descriptions.append(PreviewRow(
            name='(none)',
            kind='Description',
            detail='-',
            output='-',
            status=STATUS_ERROR,
            message='No XGen descriptions found in the scene.',
        ))

    child_entries = _guide_child_entries(guide_root)
    child_names = [name for name, _ in child_entries]
    guide_stems = {
        _stem_for_guide_child(c, suffix): c for c in child_names
    } if suffix else {}

    # Descriptions
    for desc, desc_path in desc_entries:
        desc_match = desc_match_by_orig[desc]
        patches = mesh_map_by_path.get(desc_path, []) or []
        patch_short = [p.split('|')[-1] for p in patches]
        if not patches:
            status = STATUS_WARNING
            message = 'No mesh patches bound to this description.'
        elif desc_match not in guide_stems:
            status = STATUS_WARNING
            # Message uses the match key (no Shape) since that's the
            # name the guide-group naming convention would produce.
            message = (
                'No guide group named "{}{}" - exported without paired guide.'
                .format(desc_match, suffix or '')
            )
        else:
            status = STATUS_OK
            message = ''
        preview.descriptions.append(PreviewRow(
            name=desc,
            kind='Description',
            detail=', '.join(patch_short) if patch_short else '(no mesh)',
            output=groom_filename,
            status=status,
            message=message,
            path=desc_path,
            match_key=desc_match,
        ))

    # Mesh patches (one row per unique mesh transform)
    seen_patches = set()
    # Build a {desc_path: short_name} lookup so each patch row can say
    # which description it's bound to using artist-readable names.
    desc_short_by_path = dict(
        (p, n) for n, p in desc_entries
    )
    for desc_path, patches in mesh_map_by_path.items():
        for patch in patches or []:
            short = _strip_shape_suffix(
                patch.split('|')[-1].rsplit(':', 1)[-1]
            )
            if short in seen_patches:
                continue
            seen_patches.add(short)
            preview.patches.append(PreviewRow(
                name=short,
                kind='Mesh Patch',
                detail='bound to {}'.format(
                    desc_short_by_path.get(desc_path, '(unknown)')
                ),
                output=patches_filename,
                status=STATUS_OK,
                message='',
                path=patch,
            ))

    # Guide groups (children of guide root)
    for child, child_path in child_entries:
        stem = _stem_for_guide_child(child, suffix)
        if stem in desc_match_set:
            status = STATUS_OK
            message = ''
            detail = 'matches "{}"'.format(stem)
        else:
            status = STATUS_WARNING
            message = (
                'Orphan guide group - no xgmDescription named "{}".'.format(stem)
            )
            detail = 'no matching description'
        preview.guides.append(PreviewRow(
            name=child,
            kind='Guide Group',
            detail=detail,
            output=groom_filename,
            status=status,
            message=message,
            path=child_path,
            match_key=stem,
        ))

    return preview


def frame_preview_rows(guide_root, suffix):
    """Backwards-compatible flat view of :func:`frame_preview_groups`.

    Concatenates descriptions + patches + guides. Older callers that don't
    care about the partitioning can stay on this signature.
    """
    return frame_preview_groups(guide_root, suffix).all_rows()


def animation_preview_rows(guide_root, scene_is_saved, name_by_path=None,
                           included_paths=None, dir_by_path=None):
    """Build preview rows for the Export Animation tab.

    One row per guide-root transform (namespaced or plain). Marks
    referenced guides as needing scene-save; flags duplicate output
    filenames as errors.

    Args:
        guide_root: The guide-root search string.
        scene_is_saved: True if the current Maya scene has a saved path.
        name_by_path: Optional ``{guide_grp_long_path: filename}`` map.
            When provided, each row's ``output`` is taken from here
            (already includes the ``.abc`` extension and any per-row
            prefix / suffix decoration). Paths absent from the map fall
            back to the auto-derived ``<namespace>.abc`` name.
        included_paths: Optional iterable of guide-group long paths
            that should appear in the preview. ``None`` (the default)
            includes everything discovered in the scene; an empty
            iterable yields no rows. Use this to mirror the user's
            per-character checkbox selection.
        dir_by_path: Optional ``{guide_grp_long_path: export_dir}`` map.
            Duplicate-output detection keys on dir + filename, so two
            characters writing the same filename to DIFFERENT dirs is
            allowed - only a real same-path collision is flagged.
    """
    name_by_path = name_by_path or {}
    dir_by_path = dir_by_path or {}
    rows = []
    guide_grps = find_guide_grps(guide_root)
    if included_paths is not None:
        included_set = set(included_paths)
        guide_grps = [p for p in guide_grps if p in included_set]
    if not guide_grps:
        rows.append(PreviewRow(
            name='(none)',
            kind='Guide Group',
            detail='-',
            output='-',
            status=STATUS_ERROR,
            message='No "{}" nodes found in the scene.'.format(guide_root),
        ))
        return rows

    plan = build_animation_plan(guide_grps)

    # Map short name -> long path (first occurrence wins; long paths from
    # find_guide_grps are unique).
    path_by_short = {}
    for grp_path in guide_grps:
        short = grp_path.split('|')[-1]
        path_by_short.setdefault(short, grp_path)

    # Resolve each plan row's output up front so duplicate detection
    # works against the SAME full paths the export flow will write.
    # Key on dir + filename: two rows sharing a filename in DIFFERENT
    # dirs don't collide, so they must not be flagged as duplicates.
    resolved_outputs = []  # display filename per row
    full_keys = []         # dir+filename collision key per row
    for short_name, file_name, _ in plan:
        grp_path = path_by_short.get(short_name, '')
        override = name_by_path.get(grp_path)
        fname = override if override else file_name + '.abc'
        resolved_outputs.append(fname)
        row_dir = dir_by_path.get(grp_path, '')
        key = os.path.normpath(os.path.join(row_dir, fname)) if row_dir else fname
        full_keys.append(key.lower())  # Windows paths are case-insensitive

    output_counts = {}
    for key in full_keys:
        output_counts[key] = output_counts.get(key, 0) + 1

    for (short_name, _file_name, ref_file), resolved, key in zip(
            plan, resolved_outputs, full_keys):
        if ref_file is None:
            kind = 'Local'
            detail = ''
        else:
            kind = 'Referenced'
            detail = os.path.basename(ref_file)

        if output_counts[key] > 1:
            status = STATUS_ERROR
            message = (
                'Duplicate output "{}" - two guide groups write the same '
                'file (same Dir + filename). Change one row\'s Dir or its '
                'Guides filename.'.format(resolved)
            )
        elif ref_file is not None and not scene_is_saved:
            status = STATUS_WARNING
            message = 'Scene must be saved before exporting referenced guides.'
        else:
            status = STATUS_OK
            message = ''

        rows.append(PreviewRow(
            name=short_name,
            kind=kind,
            detail=detail,
            output=resolved,
            status=status,
            message=message,
            path=path_by_short.get(short_name, ''),
        ))

    return rows
