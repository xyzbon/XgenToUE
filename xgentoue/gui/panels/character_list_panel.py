"""Per-character guide-group list (shared between Export Single Frame
and Export Animation).

Each :class:`CharacterRow` is FOUR visual rows so even long paths and
file names stay readable on a narrow window:

    [check] short_name
    Dir     [...........................]  [↻]  [...]
    Output  [groom.abc........................................]
    Patches [patches.abc......................................]

The Dir / Output / Patches widgets are Single-Frame-only - the main
window hides them when the Animation tab is active.
"""

import logging
import os

from maya import cmds

from xgentoue.gui import utils
from xgentoue.gui.qtcompat import QtCore, QtWidgets, isValid

log = logging.getLogger('xgentoue')


def _set_text_quiet(line_edit, value):
    """``setText`` without emitting ``textChanged``.

    Programmatic field sets (row-rebuild carry-over, bulk Prefix/Suffix
    pattern apply) must not trigger a per-row preview refresh - those
    paths emit ``state_changed`` once themselves. Only the user typing
    in a field (the live ``textChanged`` connection) should refresh.
    """
    blocked = line_edit.blockSignals(True)
    line_edit.setText(value)
    line_edit.blockSignals(blocked)


DEFAULT_OUTPUT_NAME = 'groom.abc'
DEFAULT_PATCHES_NAME = 'patches.abc'
DEFAULT_GUIDES_NAME = 'guides.abc'

MODE_FRAME = 'frame'
MODE_ANIMATION = 'animation'
MODE_HIDDEN = 'hidden'


class _DirLineEdit(QtWidgets.QLineEdit):
    """QLineEdit that adds an 'Open in Explorer' entry to its
    right-click context menu while keeping the default text-edit
    actions (cut / copy / paste). Useful on the per-character Dir
    field so artists can jump from the path text straight to the
    folder in Windows Explorer without copy-pasting.
    """

    open_explorer_requested = QtCore.Signal()

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if menu is None:
            return super(_DirLineEdit, self).contextMenuEvent(event)
        menu.addSeparator()
        open_action = menu.addAction('Open in Explorer')
        # Disabled (still visible) when the field is empty so the
        # menu reads correctly without firing on a no-op.
        open_action.setEnabled(bool(self.text().strip()))
        open_action.triggered.connect(
            lambda _checked=False: self.open_explorer_requested.emit()
        )
        menu.exec_(event.globalPos())

# Bulk-Prefix pattern keys. Round-tripped to QSettings as the
# `prefix/pattern` value so the next session re-highlights the same
# menu action.
PREFIX_PATTERN_NAMESPACE = 'namespace'
PREFIX_PATTERN_TOP_GROUP = 'top_group'
PREFIX_PATTERN_CUSTOM = 'custom'
PREFIX_PATTERN_CLEAR = 'clear'
PREFIX_PATTERNS = (
    PREFIX_PATTERN_NAMESPACE,
    PREFIX_PATTERN_TOP_GROUP,
    PREFIX_PATTERN_CUSTOM,
    PREFIX_PATTERN_CLEAR,
)


class CharacterRow(QtWidgets.QFrame):
    """One discovered guide_grp with its per-character export overrides."""

    activated = QtCore.Signal(object)   # passes self
    state_changed = QtCore.Signal()

    def __init__(self, long_path, parent=None):
        super(CharacterRow, self).__init__(parent)
        self._long_path = long_path
        self._short = long_path.split('|')[-1]
        self._namespace = (
            self._short.split(':', 1)[0] if ':' in self._short else ''
        )
        self._active = False
        # Use a stylesheet with a 1px-transparent border baked in, so
        # the row never changes size when active or hovered. The active
        # state just swaps the border colour; hover adds a subtle
        # background tint via Qt's :hover pseudo-state.
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setAutoFillBackground(True)
        self.setProperty('rowActive', False)
        # Hover uses a faint white overlay (~12% opacity) so it visibly
        # LIGHTENS the row regardless of the underlying palette.
        # Active adds a light-blue border + a very subtle blue tint so
        # the user can spot which character drives the preview.
        self.setStyleSheet(
            'CharacterRow { border: 1px solid transparent; border-radius: 3px; }'
            'CharacterRow:hover { background-color: rgba(255, 255, 255, 30); }'
            'CharacterRow[rowActive="true"] { '
            '  border-color: #6cb1f6; '
            '  background-color: rgba(108, 177, 246, 35); '
            '}'
        )
        self._build()

    # ----- construction ----------------------------------------------------

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # ----- Row 1: checkbox + name + Prefix + Suffix -------------------
        row1 = QtWidgets.QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(4)

        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.setToolTip(
            'Include this character in the next Export Single Frame / '
            'Export Animation run. Unchecked rows are skipped entirely.'
        )
        self.checkbox.toggled.connect(lambda _=False: self.state_changed.emit())
        row1.addWidget(self.checkbox)

        self.label = QtWidgets.QLabel(self._short)
        self.label.setMinimumWidth(140)
        self.label.setToolTip(
            'Click to make this character the active preview target.\n'
            'Full path: {}'.format(self._long_path)
        )
        # Hand cursor on the name + on the row hints "clickable".
        self.label.setCursor(QtCore.Qt.PointingHandCursor)
        row1.addWidget(self.label, 1)

        # Prefix + Suffix - decorate the Groom / Patches names. Both
        # default empty; the export flow only inserts them when
        # non-empty.
        self.prefix_inline_label = QtWidgets.QLabel('Prefix')
        row1.addWidget(self.prefix_inline_label)
        self.prefix_edit = QtWidgets.QLineEdit()
        self.prefix_edit.setPlaceholderText('(none)')
        self.prefix_edit.setMaximumWidth(110)
        self.prefix_edit.setToolTip(
            "Optional text prepended to the Groom / Patches file names "
            "(e.g. 'charB' -> 'charB_groom.abc')."
        )
        self.prefix_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        row1.addWidget(self.prefix_edit)

        self.suffix_inline_label = QtWidgets.QLabel('Suffix')
        row1.addWidget(self.suffix_inline_label)
        self.suffix_edit = QtWidgets.QLineEdit()
        self.suffix_edit.setPlaceholderText('(none)')
        self.suffix_edit.setMaximumWidth(110)
        self.suffix_edit.setToolTip(
            "Optional text appended to the Groom / Patches file names "
            "before '.abc' (e.g. 'v2' -> 'groom_v2.abc')."
        )
        self.suffix_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        row1.addWidget(self.suffix_edit)
        outer.addLayout(row1)

        # ----- Row 2: Dir field + refresh + browse ------------------------
        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)

        self.dir_label = QtWidgets.QLabel('Dir')
        row2.addWidget(self.dir_label)

        self.dir_edit = _DirLineEdit()
        self.dir_edit.setPlaceholderText('Required - pick an export folder')
        self.dir_edit.setToolTip(
            'Folder this character\'s .abc files get written to. '
            'Right-click for "Open in Explorer".'
        )
        # Default per-row Dir is the conventional <scene>/xgen drop
        # point, falling back to default_export_dir() (which uses the
        # scene folder, or the last-used Dir from QSettings) when no
        # scene is open yet.
        default_dir = utils.scene_xgen_dir() or utils.default_export_dir()
        if default_dir:
            self.dir_edit.setText(default_dir)
        self.dir_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        self.dir_edit.open_explorer_requested.connect(
            self._open_dir_in_explorer,
        )
        row2.addWidget(self.dir_edit, 1)

        self.dir_refresh_btn = QtWidgets.QToolButton()
        self.dir_refresh_btn.setText(u'↻')
        self.dir_refresh_btn.setToolTip(
            "Reset to <current scene folder>/xgen"
        )
        self.dir_refresh_btn.clicked.connect(self.reset_dir_to_scene_xgen)
        row2.addWidget(self.dir_refresh_btn)

        self.browse_btn = QtWidgets.QToolButton()
        self.browse_btn.setText(u'…')
        self.browse_btn.setToolTip("Browse for this row's export directory")
        self.browse_btn.clicked.connect(self._browse)
        row2.addWidget(self.browse_btn)
        outer.addLayout(row2)

        # ----- Row 3: file names ------------------------------------------
        # Single-Frame mode shows Groom + Patches.
        # Animation mode shows Guides only.
        # Visibility is toggled via set_mode(); both rows of widgets are
        # always built so the layout doesn't have to be torn down.
        row3 = QtWidgets.QHBoxLayout()
        row3.setContentsMargins(0, 0, 0, 0)
        row3.setSpacing(4)

        self.output_label = QtWidgets.QLabel('Groom')
        row3.addWidget(self.output_label)
        self.output_edit = QtWidgets.QLineEdit(DEFAULT_OUTPUT_NAME)
        self.output_edit.setPlaceholderText(DEFAULT_OUTPUT_NAME)
        self.output_edit.setToolTip(
            'Filename for the merged groom Alembic (single-frame). '
            'Prefix / Suffix are inserted around the stem, so '
            '"groom.abc" with prefix "charB" becomes '
            '"charB_groom.abc".'
        )
        self.output_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        row3.addWidget(self.output_edit, 1)

        self.patches_label = QtWidgets.QLabel('Patches')
        row3.addWidget(self.patches_label)
        self.patches_edit = QtWidgets.QLineEdit(DEFAULT_PATCHES_NAME)
        self.patches_edit.setPlaceholderText(DEFAULT_PATCHES_NAME)
        self.patches_edit.setToolTip(
            'Filename for the mesh-patches Alembic that ships with '
            'the groom (single-frame). Decorated with the same '
            'Prefix / Suffix as the Groom filename.'
        )
        self.patches_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        row3.addWidget(self.patches_edit, 1)

        self.guides_label = QtWidgets.QLabel('Guides')
        row3.addWidget(self.guides_label)
        self.guides_edit = QtWidgets.QLineEdit(DEFAULT_GUIDES_NAME)
        self.guides_edit.setPlaceholderText(DEFAULT_GUIDES_NAME)
        self.guides_edit.setToolTip(
            'Filename for this character\'s animated guides '
            'Alembic (Export Animation tab). Prefix / Suffix '
            'decorate it the same way as Groom / Patches.'
        )
        self.guides_edit.textChanged.connect(
            lambda *_: self.state_changed.emit()
        )
        row3.addWidget(self.guides_edit, 1)

        # Animation-mode widgets start hidden; set_mode() flips them.
        self.guides_label.setVisible(False)
        self.guides_edit.setVisible(False)

        outer.addLayout(row3)

        # Tooltip + cursor on the whole row to surface clickability.
        self.setToolTip(
            'Click anywhere outside an input to make this character the '
            'active preview target.'
        )
        self.setMouseTracking(True)

    def set_mode(self, mode):
        """Toggle the row's visible widgets per export mode.

        ``mode == 'frame'``     - Prefix / Suffix / Dir / Groom / Patches
                                  (single-frame fields)
        ``mode == 'animation'`` - Prefix / Suffix / Dir / Guides
                                  (animation file-name only)
        ``mode == 'hidden'``    - just checkbox + name
        """
        is_frame = mode == MODE_FRAME
        is_anim = mode == MODE_ANIMATION
        show_extras = is_frame or is_anim

        # Common extras (visible on either export mode)
        for widget in (
            self.prefix_inline_label, self.prefix_edit,
            self.suffix_inline_label, self.suffix_edit,
            self.dir_label, self.dir_edit,
            self.dir_refresh_btn, self.browse_btn,
        ):
            widget.setVisible(show_extras)

        # Frame-only fields
        for widget in (
            self.output_label, self.output_edit,
            self.patches_label, self.patches_edit,
        ):
            widget.setVisible(is_frame)

        # Animation-only field
        for widget in (self.guides_label, self.guides_edit):
            widget.setVisible(is_anim)

    # Backwards-compat shim - older callers still pass a bool.
    def set_extras_visible(self, visible):
        self.set_mode(MODE_FRAME if visible else MODE_HIDDEN)

    # ----- public API ------------------------------------------------------

    @property
    def long_path(self):
        return self._long_path

    @property
    def short_name(self):
        return self._short

    @property
    def namespace(self):
        return self._namespace

    @property
    def top_group_name(self):
        """Topmost DAG ancestor's short name (namespace stripped).

        For a row whose long_path is
        ``|world|charB:assemble|charB:guide_grp`` this returns
        ``world``. When the guide_grp is parented directly under the
        world (no ancestors) we fall back to the namespace so the
        result is never empty for a namespaced character.
        """
        parts = [p for p in self._long_path.split('|') if p]
        if len(parts) <= 1:
            return self._namespace  # nothing above the guide group
        return parts[0].rsplit(':', 1)[-1]

    @property
    def guide_root(self):
        """The value to pass into the existing export flow's guide_root."""
        return self._short

    def is_checked(self):
        return self.checkbox.isChecked()

    def set_checked(self, value):
        self.checkbox.setChecked(bool(value))

    def prefix(self):
        """Optional prefix decorating the Groom / Patches file names."""
        return self.prefix_edit.text().strip()

    def set_prefix(self, value):
        _set_text_quiet(self.prefix_edit, value or '')

    def suffix(self):
        """Optional suffix decorating the Groom / Patches file names."""
        return self.suffix_edit.text().strip()

    def set_suffix(self, value):
        _set_text_quiet(self.suffix_edit, value or '')

    def guides_name(self):
        """Filename for the animation guides output (e.g. 'guides.abc')."""
        return self.guides_edit.text().strip()

    def set_guides_name(self, value):
        _set_text_quiet(self.guides_edit, value or DEFAULT_GUIDES_NAME)

    def output_name(self):
        """Filename for the final groom output (e.g. 'groom.abc')."""
        return self.output_edit.text().strip()

    def set_output_name(self, value):
        _set_text_quiet(self.output_edit, value or DEFAULT_OUTPUT_NAME)

    def patches_name(self):
        """Filename for the patches Alembic (e.g. 'charB_patches.abc')."""
        return self.patches_edit.text().strip()

    def set_patches_name(self, value):
        _set_text_quiet(self.patches_edit, value or DEFAULT_PATCHES_NAME)

    def export_dir(self):
        return self.dir_edit.text().strip()

    def set_export_dir(self, value):
        self.dir_edit.setText(value or '')

    def is_active(self):
        return self._active

    def set_active(self, active):
        self._active = bool(active)
        # Flip the dynamic property and reapply styles so the
        # CharacterRow[rowActive="true"] selector kicks in. Border
        # colour is the only thing that changes; size stays the same
        # because the border was already present (as transparent).
        self.setProperty('rowActive', self._active)
        self.style().unpolish(self)
        self.style().polish(self)

    # ----- events ----------------------------------------------------------

    def mousePressEvent(self, event):
        super(CharacterRow, self).mousePressEvent(event)
        widget_under = self.childAt(event.pos())
        non_inputs = (None, self.label)
        if widget_under in non_inputs:
            self.activated.emit(self)

    def contextMenuEvent(self, event):
        """Right-click on the row name (or empty row area) - offer
        clipboard copy of the various name forms.

        Skipped when the right-click lands on a child input (line edit
        / spin box etc.) so the default text-context menu still works.
        """
        widget_under = self.childAt(event.pos())
        if widget_under not in (None, self.label):
            return super(CharacterRow, self).contextMenuEvent(event)

        # Split short into namespace + bare name. For non-namespaced
        # rows the two namespace-specific entries are disabled rather
        # than hidden so the menu shape stays predictable.
        name_no_ns = (
            self._short.split(':', 1)[1] if ':' in self._short else self._short
        )

        menu = QtWidgets.QMenu(self)
        copy_short = menu.addAction('Copy short name')
        copy_ns = menu.addAction('Copy namespace')
        copy_no_ns = menu.addAction('Copy name without namespace')
        copy_full = menu.addAction('Copy full path')
        if not self._namespace:
            copy_ns.setEnabled(False)
            copy_no_ns.setEnabled(False)

        chosen = menu.exec_(event.globalPos())
        if chosen is None:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        if chosen is copy_short:
            clipboard.setText(self._short)
        elif chosen is copy_ns:
            clipboard.setText(self._namespace)
        elif chosen is copy_no_ns:
            clipboard.setText(name_no_ns)
        elif chosen is copy_full:
            clipboard.setText(self._long_path)

    # ----- internal --------------------------------------------------------

    def _browse(self):
        start = self.dir_edit.text().strip() or utils.default_export_dir()
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Select Export Directory', start,
        )
        if chosen:
            self.dir_edit.setText(chosen)
            self.state_changed.emit()

    def _open_dir_in_explorer(self):
        """Reveal the row's Dir path in the OS file manager.

        Wired to the right-click context menu on ``self.dir_edit``.
        Empty paths and missing folders are no-ops - the file
        manager would just show an error dialog.
        """
        path = self.dir_edit.text().strip()
        if not path:
            return
        if not utils.reveal_in_explorer(path):
            log.warning('Could not open %r in Explorer', path)

    def reset_dir_to_scene_xgen(self):
        """Set Dir to ``<current_scene_path.parent>/xgen``.

        Falls back to the existing default-export-dir helper when no
        scene is saved. Public so the main window can drive all rows
        at once (e.g. when the user clicks the Source panel's Detect).
        """
        target = utils.scene_xgen_dir() or utils.default_export_dir()
        if target:
            self.dir_edit.setText(target)
            self.state_changed.emit()


class CharacterListPanel(QtWidgets.QGroupBox):
    """Holds the list of :class:`CharacterRow` instances.

    Re-discovery is driven externally (e.g. via SourcePanel.Detect or
    a Source-field edit) - this panel no longer carries its own Refresh
    button.
    """

    active_changed = QtCore.Signal(object)   # CharacterRow or None
    state_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super(CharacterListPanel, self).__init__('Characters', parent)
        self._rows = []
        self._active_row = None
        # Remember the currently-selected export mode so refresh() can
        # reapply it to any new rows discovered later. Without this, a
        # rebuild while the Animation tab is active would create rows
        # in their CharacterRow.__init__ defaults (Output/Patches
        # visible, Guides hidden), and the user would see Frame-mode
        # widgets flash in until the next set_mode() call.
        self._mode = MODE_FRAME
        # Most-recently-applied Prefix / Suffix patterns. We don't
        # auto-apply at startup, but we round-trip these through
        # QSettings so the "Set Prefix..." / "Set Suffix..." menus
        # can pre-highlight the user's last pick.
        self._last_pattern = PREFIX_PATTERN_NAMESPACE
        self._last_custom_prefix = ''
        self._last_suffix_pattern = PREFIX_PATTERN_CLEAR
        self._last_custom_suffix = ''
        self._build()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(4)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self.summary_label = QtWidgets.QLabel('No guide groups detected.')
        header_row.addWidget(self.summary_label, 1)
        # Bulk-apply Prefix to every row in one click.
        self.prefix_btn = QtWidgets.QToolButton()
        self.prefix_btn.setText('Set Prefix...')
        self.prefix_btn.setToolTip(
            'Bulk-fill every character\'s Prefix using a chosen pattern '
            '(namespace, top group, custom text, or clear).'
        )
        self.prefix_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._prefix_menu = QtWidgets.QMenu(self.prefix_btn)
        # Rebuild on aboutToShow so the live sample (first row's value)
        # stays current as rows are discovered / renamed.
        self._prefix_menu.aboutToShow.connect(self._rebuild_prefix_menu)
        self.prefix_btn.setMenu(self._prefix_menu)
        header_row.addWidget(self.prefix_btn)

        # Same pattern picker for Suffix - useful for stamping a
        # version tag (e.g. 'v02') across every row at once. Same
        # menu options for symmetry; the default-highlighted entry
        # is Clear (since empty is the most common Suffix value).
        self.suffix_btn = QtWidgets.QToolButton()
        self.suffix_btn.setText('Set Suffix...')
        self.suffix_btn.setToolTip(
            'Bulk-fill every character\'s filename Suffix using a chosen '
            'pattern (namespace, top group, custom text, or clear). '
            'Typical use: stamp a version tag like "v02" across all rows.'
        )
        self.suffix_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._suffix_menu = QtWidgets.QMenu(self.suffix_btn)
        self._suffix_menu.aboutToShow.connect(self._rebuild_suffix_menu)
        self.suffix_btn.setMenu(self._suffix_menu)
        header_row.addWidget(self.suffix_btn)

        layout.addLayout(header_row)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._inner = QtWidgets.QWidget()
        self._inner_layout = QtWidgets.QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(2)
        self._inner_layout.addStretch(1)
        self.scroll.setWidget(self._inner)
        layout.addWidget(self.scroll, 1)

    # ----- public API ------------------------------------------------------

    def refresh(self, guide_root_pattern):
        """Discover guide groups for ``guide_root_pattern`` and rebuild
        the row list. Existing rows whose long path is still present are
        preserved (checkbox + output names + dir).
        """
        new_paths = utils.find_guide_grps(guide_root_pattern)
        previous = {row.long_path: row for row in self._rows}

        for row in self._rows:
            self._inner_layout.removeWidget(row)
            # `setParent(None)` would make the row a top-level window;
            # if Python's GC was slow, it would briefly pop up as a
            # floating Maya dialog. Hide + deleteLater destroys the
            # C++ widget immediately on the next event-loop spin and
            # never reparents to root.
            row.hide()
            row.deleteLater()
        self._rows = []
        self._active_row = None

        for path in new_paths:
            old = previous.get(path)
            row = CharacterRow(path, parent=self._inner)
            # Apply the current export mode BEFORE inserting into the
            # layout so the user never sees Frame-mode widgets flash on
            # rows that should be in Animation mode (and vice-versa).
            row.set_mode(self._mode)
            if old is not None:
                row.set_checked(old.is_checked())
                row.set_prefix(old.prefix())
                row.set_suffix(old.suffix())
                row.set_output_name(old.output_name())
                row.set_patches_name(old.patches_name())
                row.set_guides_name(old.guides_name())
                row.set_export_dir(old.export_dir())
            row.state_changed.connect(self._on_row_state_changed)
            row.activated.connect(self._on_row_activated)
            self._inner_layout.insertWidget(
                self._inner_layout.count() - 1, row,
            )
            self._rows.append(row)

        if self._rows:
            self._activate(self._rows[0])
        else:
            self.active_changed.emit(None)
        self._refresh_summary()
        self.state_changed.emit()

    def all_rows(self):
        return list(self._rows)

    def checked_rows(self):
        return [r for r in self._rows if r.is_checked()]

    def active_row(self):
        """Return the current active CharacterRow, or None.

        The cached ``self._active_row`` can outlive its underlying
        Qt object - ``refresh()`` calls ``deleteLater()`` on the old
        rows, which means the Python wrapper still exists and ``is
        None`` still says False, but touching any widget on it
        raises ``RuntimeError: Internal C++ object already deleted``.
        Validate here so every caller (preview refresh, export
        flow, signal handlers) gets either a live row or None - no
        third state.
        """
        if not isValid(self._active_row):
            self._active_row = None
        return self._active_row

    def set_extras_visible(self, visible):
        for r in self._rows:
            r.set_extras_visible(visible)

    def set_mode(self, mode):
        """Forward to every row so all rows share the same export mode.

        Also remembered on the panel so refresh() can reapply it to any
        newly-discovered rows.
        """
        self._mode = mode
        for r in self._rows:
            r.set_mode(mode)

    # ----- Prefix pattern API ---------------------------------------------

    def apply_prefix_pattern(self, pattern, custom_text=''):
        """Set every row's Prefix according to ``pattern``.

        ``pattern`` is one of the ``PREFIX_PATTERN_*`` constants. For
        ``PREFIX_PATTERN_CUSTOM`` the same ``custom_text`` is applied
        to every row. Unknown patterns are silently ignored.

        Emits :pyattr:`state_changed` exactly once so the main window
        persists / refreshes preview without firing N times.
        """
        if pattern not in PREFIX_PATTERNS:
            return
        for row in self._rows:
            if pattern == PREFIX_PATTERN_NAMESPACE:
                value = row.namespace
            elif pattern == PREFIX_PATTERN_TOP_GROUP:
                value = row.top_group_name
            elif pattern == PREFIX_PATTERN_CUSTOM:
                value = custom_text
            else:  # PREFIX_PATTERN_CLEAR
                value = ''
            row.set_prefix(value or '')
        self._last_pattern = pattern
        if pattern == PREFIX_PATTERN_CUSTOM:
            self._last_custom_prefix = custom_text or ''
        self._refresh_summary()
        self.state_changed.emit()

    def last_pattern(self):
        return self._last_pattern

    def set_last_pattern(self, pattern):
        if pattern in PREFIX_PATTERNS:
            self._last_pattern = pattern

    def last_custom_prefix(self):
        return self._last_custom_prefix

    def set_last_custom_prefix(self, text):
        self._last_custom_prefix = text or ''

    def apply_suffix_pattern(self, pattern, custom_text=''):
        """Set every row's Suffix according to ``pattern``.

        Same pattern keys as :meth:`apply_prefix_pattern` for
        symmetry; the realistic Suffix use case is CUSTOM (version
        tag like ``v02``) or CLEAR, but the Namespace / Top group
        options are available too for consistency.
        """
        if pattern not in PREFIX_PATTERNS:
            return
        for row in self._rows:
            if pattern == PREFIX_PATTERN_NAMESPACE:
                value = row.namespace
            elif pattern == PREFIX_PATTERN_TOP_GROUP:
                value = row.top_group_name
            elif pattern == PREFIX_PATTERN_CUSTOM:
                value = custom_text
            else:  # PREFIX_PATTERN_CLEAR
                value = ''
            row.set_suffix(value or '')
        self._last_suffix_pattern = pattern
        if pattern == PREFIX_PATTERN_CUSTOM:
            self._last_custom_suffix = custom_text or ''
        self._refresh_summary()
        self.state_changed.emit()

    def last_suffix_pattern(self):
        return self._last_suffix_pattern

    def set_last_suffix_pattern(self, pattern):
        if pattern in PREFIX_PATTERNS:
            self._last_suffix_pattern = pattern

    def last_custom_suffix(self):
        return self._last_custom_suffix

    def set_last_custom_suffix(self, text):
        self._last_custom_suffix = text or ''

    def reset_all_dirs_to_scene_xgen(self):
        """Set every row's Dir to ``<current_scene_path.parent>/xgen``."""
        for r in self._rows:
            r.reset_dir_to_scene_xgen()

    # ----- internal --------------------------------------------------------

    def _activate(self, row):
        if self._active_row is row:
            return
        # The previous active row may have been deleteLater()'d by a
        # refresh that happened between activations. Its Python
        # wrapper still exists, but touching the C++ side raises
        # RuntimeError. Treat that as "no previous active row" so
        # we can still promote the new one.
        if self._active_row is not None:
            try:
                self._active_row.set_active(False)
            except RuntimeError:
                log.debug(
                    'Previous active row was deleted; skipping '
                    'set_active(False).',
                )
        self._active_row = row
        if row is not None:
            row.set_active(True)
        self.active_changed.emit(row)

    def _on_row_activated(self, row):
        self._activate(row)

    def _on_row_state_changed(self):
        self._refresh_summary()
        self.state_changed.emit()

    def _refresh_summary(self):
        total = len(self._rows)
        if total == 0:
            self.summary_label.setText('No guide groups detected.')
            return
        checked = sum(1 for r in self._rows if r.is_checked())
        self.summary_label.setText(
            '{} found, {} selected'.format(total, checked)
        )

    def _rebuild_prefix_menu(self):
        """Refresh the Set-Prefix popup actions and pre-highlight the
        last-used pattern. Called lazily on aboutToShow so action
        labels can carry a live sample of the first row's value.
        """
        self._prefix_menu.clear()
        sample_row = self._rows[0] if self._rows else None

        def with_sample(label, value):
            if sample_row is None or not value:
                return label
            return '{}  ({})'.format(label, value)

        ns_action = self._prefix_menu.addAction(
            with_sample(
                'Use namespace',
                sample_row.namespace if sample_row else '',
            )
        )
        ns_action.triggered.connect(
            lambda: self.apply_prefix_pattern(PREFIX_PATTERN_NAMESPACE)
        )

        top_action = self._prefix_menu.addAction(
            with_sample(
                'Use top group',
                sample_row.top_group_name if sample_row else '',
            )
        )
        top_action.triggered.connect(
            lambda: self.apply_prefix_pattern(PREFIX_PATTERN_TOP_GROUP)
        )

        custom_action = self._prefix_menu.addAction(
            with_sample('Custom prefix...', self._last_custom_prefix)
        )
        custom_action.triggered.connect(self._prompt_custom_prefix)

        self._prefix_menu.addSeparator()
        clear_action = self._prefix_menu.addAction('Clear')
        clear_action.triggered.connect(
            lambda: self.apply_prefix_pattern(PREFIX_PATTERN_CLEAR)
        )

        # Highlight the last-used pattern (visual cue for the user's
        # most recent choice).
        default_by_pattern = {
            PREFIX_PATTERN_NAMESPACE: ns_action,
            PREFIX_PATTERN_TOP_GROUP: top_action,
            PREFIX_PATTERN_CUSTOM: custom_action,
            PREFIX_PATTERN_CLEAR: clear_action,
        }
        default_action = default_by_pattern.get(self._last_pattern)
        if default_action is not None:
            self._prefix_menu.setActiveAction(default_action)
            font = default_action.font()
            font.setBold(True)
            default_action.setFont(font)

    def _prompt_custom_prefix(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'Custom Prefix',
            'Apply this prefix to every character:',
            QtWidgets.QLineEdit.Normal,
            self._last_custom_prefix,
        )
        if not ok:
            return
        self.apply_prefix_pattern(
            PREFIX_PATTERN_CUSTOM, custom_text=text.strip(),
        )

    def _rebuild_suffix_menu(self):
        """Mirror of :meth:`_rebuild_prefix_menu` for the Suffix
        button. Same four options + live sample preview."""
        self._suffix_menu.clear()
        sample_row = self._rows[0] if self._rows else None

        def with_sample(label, value):
            if sample_row is None or not value:
                return label
            return '{}  ({})'.format(label, value)

        ns_action = self._suffix_menu.addAction(
            with_sample(
                'Use namespace',
                sample_row.namespace if sample_row else '',
            )
        )
        ns_action.triggered.connect(
            lambda: self.apply_suffix_pattern(PREFIX_PATTERN_NAMESPACE)
        )

        top_action = self._suffix_menu.addAction(
            with_sample(
                'Use top group',
                sample_row.top_group_name if sample_row else '',
            )
        )
        top_action.triggered.connect(
            lambda: self.apply_suffix_pattern(PREFIX_PATTERN_TOP_GROUP)
        )

        custom_action = self._suffix_menu.addAction(
            with_sample('Custom suffix...', self._last_custom_suffix)
        )
        custom_action.triggered.connect(self._prompt_custom_suffix)

        self._suffix_menu.addSeparator()
        clear_action = self._suffix_menu.addAction('Clear')
        clear_action.triggered.connect(
            lambda: self.apply_suffix_pattern(PREFIX_PATTERN_CLEAR)
        )

        default_by_pattern = {
            PREFIX_PATTERN_NAMESPACE: ns_action,
            PREFIX_PATTERN_TOP_GROUP: top_action,
            PREFIX_PATTERN_CUSTOM: custom_action,
            PREFIX_PATTERN_CLEAR: clear_action,
        }
        default_action = default_by_pattern.get(self._last_suffix_pattern)
        if default_action is not None:
            self._suffix_menu.setActiveAction(default_action)
            font = default_action.font()
            font.setBold(True)
            default_action.setFont(font)

    def _prompt_custom_suffix(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'Custom Suffix',
            'Apply this suffix to every character\n'
            '(e.g. a version tag like "v02"):',
            QtWidgets.QLineEdit.Normal,
            self._last_custom_suffix,
        )
        if not ok:
            return
        self.apply_suffix_pattern(
            PREFIX_PATTERN_CUSTOM, custom_text=text.strip(),
        )
