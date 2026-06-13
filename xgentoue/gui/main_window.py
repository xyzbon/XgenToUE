"""XgenToUE main window.

The :class:`XgenToUETool` widget hosts the Export Single Frame / Export Animation
/ Settings tabs and drives the underlying core export workflows. Per-tab
widgets (Source / Output / Preview / progress / Export button) live inside
the tab composites under :mod:`xgentoue.gui.panels`.
"""

import json
import logging
import os
import traceback

from maya import cmds

from xgentoue import __version__
from xgentoue.core.abc_process import (
    _safe_remove,
    add_animation_groom_attributes,
    flatten_guide_groups,
    merge_and_process_abc,
)
from xgentoue.core.maya_env import clean_xgen_preview, ensure_plugins_loaded
from xgentoue.core.maya_export import (
    collect_spline_descriptions,
    export_group,
    export_groups_batch,
    export_interactive_groom,
    get_description_mesh_map,
)
from xgentoue.gui import utils
from xgentoue.gui.checker import check_scene
from xgentoue.gui.panels.action_bar import ActionBar
from xgentoue.gui.panels.animation_tab import AnimationTab
from xgentoue.gui.panels.character_list_panel import CharacterListPanel
from xgentoue.gui.panels.frame_tab import FrameTab
from xgentoue.gui.panels.log_panel import LogPanel
from xgentoue.gui.panels.preview_table import PreviewTable
from xgentoue.gui.panels.source_panel import SourcePanel
from xgentoue.gui.qtcompat import QtCore, QtWidgets

FILTER_ALL = 'all'
FILTER_DESCRIPTIONS = 'descriptions'
FILTER_PATCHES = 'patches'
FILTER_GUIDES = 'guides'

log = logging.getLogger('xgentoue')


class XgenToUETool(QtWidgets.QWidget):
    """Top-level tool window."""

    WINDOW_TITLE = 'XgenToUE'
    OBJECT_NAME = 'XgenToUEWindow'
    SETTINGS_ORG = 'XgenToUE'
    SETTINGS_APP = 'XgenToUETool'

    def __init__(self, parent=None):
        super(XgenToUETool, self).__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        # Title carries the version so users can tell at a glance
        # which build is running - matters when supporting older
        # installs in shot files.
        self.setWindowTitle('{} v{}'.format(self.WINDOW_TITLE, __version__))
        self.setWindowFlags(QtCore.Qt.Window)
        self.setMinimumSize(760, 620)
        self._build()
        self._load_settings()

    # ----- construction ----------------------------------------------------

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        # root.setContentsMargins(10, 10, 10, 10)
        # root.setSpacing(6)

        # title = QtWidgets.QLabel(self.WINDOW_TITLE)
        # title.setObjectName('TitleBar')
        # root.addWidget(title)
        #
        # version = QtWidgets.QLabel(
        #     'v{}  -  Maya XGen to Unreal Engine groom exporter'.format(__version__)
        # )
        # version.setObjectName('VersionLabel')
        # root.addWidget(version)

        # Shared preview state - one PreviewTable for both tabs.
        self._current_filter = FILTER_GUIDES
        self._last_preview = utils.FramePreview()
        self._applying_pair = False

        # Shared SourcePanel + CharacterListPanel - both live in the
        # LEFT column of the splitter. Source is at the top, the
        # character list expands underneath, and the tabs sit at the
        # bottom of the column. Both export modes read this same state.
        self.source_panel = SourcePanel()
        self.character_list = CharacterListPanel()

        # Shared ActionBar - its button label updates per active tab.
        self.action_bar = ActionBar(button_label='Export Single Frame')
        self.action_bar.export_clicked.connect(self._on_export_clicked)
        self.action_bar.check_clicked.connect(self._on_check_clicked)

        # Shared LogPanel - one logger handler captures both modes' output.
        self.log_panel = LogPanel()

        left_column = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self.source_panel)
        left_layout.addWidget(self._build_tabs())

        # Vertical splitter between Characters (top) and the
        # ActionBar + LogPanel block (bottom). Lets users give the
        # log panel more or less room without resizing the whole
        # window. Source + tabs stay above the splitter since their
        # height is naturally fixed.
        action_bottom = QtWidgets.QWidget()
        action_bottom_layout = QtWidgets.QVBoxLayout(action_bottom)
        action_bottom_layout.setContentsMargins(0, 0, 0, 0)
        action_bottom_layout.setSpacing(6)
        action_bottom_layout.addWidget(self.action_bar)
        action_bottom_layout.addWidget(self.log_panel, 1)

        self.left_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.left_splitter.addWidget(self.character_list)
        self.left_splitter.addWidget(action_bottom)
        # Characters grows when the window grows; the action / log
        # block stays at its preferred size unless the user drags.
        self.left_splitter.setStretchFactor(0, 1)
        self.left_splitter.setStretchFactor(1, 0)
        self.left_splitter.setSizes([500, 200])
        left_layout.addWidget(self.left_splitter, 1)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.main_splitter.addWidget(left_column)
        self.main_splitter.addWidget(self._build_preview_area())
        # Both panes grow when the window grows; right gets twice the
        # extra space so the preview table (the data-dense column)
        # stays readable instead of the source/log block dominating.
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 2)
        # Don't pin the left column to a fixed width - let it size from
        # its content and the stretch factors so users can drag the
        # handle freely on small monitors / dock setups. (A saved
        # splitter state, if any, is applied later in _restore_settings.)
        self.main_splitter.setChildrenCollapsible(False)
        root.addWidget(self.main_splitter, 1)

        self.source_panel.changed.connect(self._on_shared_source_changed)
        # Clicking Detect refreshes every row's Dir to <scene>/xgen,
        # the same target the per-row ↻ button uses. Per-row Dir is
        # the only Dir on either tab now, so this single wire covers
        # both Single Frame and Animation.
        self.source_panel.detect_clicked.connect(
            self.character_list.reset_all_dirs_to_scene_xgen,
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # CharacterListPanel no longer has a Refresh button; clicks on
        # SourcePanel's Detect (or edits to Guide Root / Suffix) drive
        # the re-scan via _on_shared_source_changed.
        self.character_list.active_changed.connect(self._refresh_preview)
        self.character_list.state_changed.connect(self._refresh_preview)
        # Mirror the active character into Maya's selection so the
        # user's outliner / viewport selection tracks the highlighted
        # row.
        self.character_list.active_changed.connect(self._on_active_character)

        # Initial discovery + preview pass once the event loop spins up.
        QtCore.QTimer.singleShot(0, self._initial_populate)

    def _initial_populate(self):
        self.character_list.refresh(self.source_panel.guide_root())
        self._on_tab_changed(self.tabs.currentIndex())
        self._refresh_preview()

    def _build_tabs(self):
        self.tabs = QtWidgets.QTabWidget()
        # The tabs widget should not grow taller than the current tab's
        # body. Otherwise an empty Frame body would waste space sized
        # for the (taller) Animation body.
        self.tabs.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Maximum,
        )

        self.frame_tab = FrameTab(source_panel=self.source_panel)
        self.animation_tab = AnimationTab(source_panel=self.source_panel)
        self.tabs.addTab(self.frame_tab, 'Export Single Frame')
        self.tabs.addTab(self.animation_tab, 'Export Animation')

        self.animation_tab.changed.connect(self._on_animation_tab_changed)

        return self.tabs

    def _compact_tab_sizes(self):
        """Shrink the tab widget to the currently-active tab's height.

        QTabWidget normally sizes its body to the max of all tab
        sizeHints, so an empty Frame body still reserves space for the
        (taller) Animation body. We work around that by forcing the
        tab widget's ``maximumHeight`` after each tab change.
        """
        current = self.tabs.currentWidget()
        if current is None:
            return
        bar_h = self.tabs.tabBar().sizeHint().height()
        body_h = max(current.sizeHint().height(), 0)
        # `+ 12` gives the frame border a little breathing room.
        self.tabs.setMaximumHeight(bar_h + body_h + 12)
        self.tabs.updateGeometry()

    def _on_export_clicked(self):
        """ActionBar's Export button - dispatch based on the active tab."""
        current = self.tabs.currentWidget()
        if current is self.frame_tab:
            self._export_single_frame()
        elif current is self.animation_tab:
            self._export_animation()

    def _on_check_clicked(self):
        """ActionBar's Check button - validate the scene, write nothing.

        Scopes the checks to the checked character rows' namespaces;
        with no rows checked, ``check_scene`` validates the whole scene
        (namespace ``None``). The dry-run conversion it runs is wrapped
        in an undo chunk and cleaned up, so the scene is left untouched.
        """
        rows = self.character_list.checked_rows()
        suffix = self.source_panel.suffix()
        guide_root = self.source_panel.guide_root()
        cmds.waitCursor(state=True)
        self.action_bar.set_enabled(False)
        try:
            # check_scene runs its own plugin check and turns a missing
            # plugin into an ERROR issue, so a plugin problem is reported
            # in the results rather than aborting the check.
            issues = check_scene(rows, suffix, guide_root)
        except Exception as exc:
            self._report_failure(exc)
            return
        finally:
            cmds.waitCursor(state=False)
            self.action_bar.set_enabled(True)
        self._show_check_results(issues)

    def _show_check_results(self, issues):
        """Log each :class:`CheckIssue` and pop a summary dialog.

        Worst severity drives the dialog icon; the body lists one line
        per issue (worst first), capped so a huge scene doesn't produce
        an unbounded dialog - the full set is always in the log panel.
        """
        rank = {
            utils.STATUS_ERROR: 0,
            utils.STATUS_WARNING: 1,
            utils.STATUS_OK: 2,
        }
        tag = {
            utils.STATUS_ERROR: 'ERROR',
            utils.STATUS_WARNING: 'WARN',
            utils.STATUS_OK: 'OK',
        }
        for issue in issues:
            line = 'Check - %s: %s' % (issue.target, issue.message)
            if issue.severity == utils.STATUS_ERROR:
                log.error(line)
            elif issue.severity == utils.STATUS_WARNING:
                log.warning(line)
            else:
                log.info(line)

        n_err = sum(1 for i in issues if i.severity == utils.STATUS_ERROR)
        n_warn = sum(1 for i in issues if i.severity == utils.STATUS_WARNING)
        ordered = sorted(issues, key=lambda i: rank.get(i.severity, 9))
        body = [
            '{:<5} {}  ->  {}'.format(
                tag.get(i.severity, '?'), i.target, i.message,
            )
            for i in ordered
        ]
        cap = 30
        if len(body) > cap:
            extra = len(body) - cap
            body = body[:cap]
            body.append('... and {} more (see the log panel).'.format(extra))

        summary = 'Scene check: {} error(s), {} warning(s).'.format(
            n_err, n_warn,
        )
        full_text = summary + '\n\n' + '\n'.join(body)
        if n_err:
            QtWidgets.QMessageBox.critical(self, 'Scene check', full_text)
        elif n_warn:
            QtWidgets.QMessageBox.warning(self, 'Scene check', full_text)
        else:
            QtWidgets.QMessageBox.information(self, 'Scene check', full_text)

    def _build_preview_area(self):
        side = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Row 1: Show: + filter radios. Hidden on the Animation tab.
        type_row = QtWidgets.QHBoxLayout()
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(8)
        type_row.addWidget(QtWidgets.QLabel('Show:'))
        self.filter_group = QtWidgets.QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.radio_all = QtWidgets.QRadioButton('All')
        self.radio_all.setToolTip(
            'Show every row kind in the preview (descriptions, '
            'mesh patches, guide groups).'
        )
        self.radio_desc = QtWidgets.QRadioButton('Descriptions')
        self.radio_desc.setToolTip(
            'Show only xgmDescription rows in the preview.'
        )
        self.radio_patches = QtWidgets.QRadioButton('Patches')
        self.radio_patches.setToolTip(
            'Show only mesh-patch rows in the preview - the source '
            'meshes that each description is bound to.'
        )
        self.radio_guides = QtWidgets.QRadioButton('Guides')
        self.radio_guides.setToolTip(
            'Show only guide-group rows in the preview. The default '
            '- guides are the primary thing being exported.'
        )
        self.radio_guides.setChecked(True)
        for radio, key in (
            (self.radio_all, FILTER_ALL),
            (self.radio_guides, FILTER_GUIDES),
            (self.radio_desc, FILTER_DESCRIPTIONS),
            (self.radio_patches, FILTER_PATCHES),
        ):
            self.filter_group.addButton(radio)
            radio.setProperty('filter_key', key)
            radio.toggled.connect(self._on_filter_changed)
            type_row.addWidget(radio)
        type_row.addStretch(1)
        self._filter_widget = QtWidgets.QWidget()
        self._filter_widget.setLayout(type_row)
        layout.addWidget(self._filter_widget)

        # Row 2: auto-pair checkbox on the left, summary label on the right.
        pair_row = QtWidgets.QHBoxLayout()
        pair_row.setContentsMargins(0, 0, 0, 0)
        pair_row.setSpacing(8)
        self.pair_check = QtWidgets.QCheckBox(
            'Auto-select paired Description / Guide'
        )
        self.pair_check.setToolTip(
            'When a Description or Guide Group row is selected, also select '
            'its name-matched partner.'
        )
        self.pair_check.setChecked(True)
        pair_row.addWidget(self.pair_check)
        pair_row.addStretch(1)
        self.summary_label = QtWidgets.QLabel('0 items')
        self.summary_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        pair_row.addWidget(self.summary_label)
        self._pair_widget = QtWidgets.QWidget()
        self._pair_widget.setLayout(pair_row)
        layout.addWidget(self._pair_widget)

        # Row 3+: the preview itself. show_header=False because we've
        # already lifted the summary out of the table into row 2 and
        # the Source-panel Detect button replaces the Refresh button.
        self.preview = PreviewTable(show_header=False)
        self.preview.set_empty_message(
            'No items- click Detect to try.'
        )
        self.preview.selection_changed.connect(self._on_preview_selection)
        layout.addWidget(self.preview, 1)

        return side

    # ----- settings persistence -------------------------------------------

    def _settings(self):
        return QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

    def _load_settings(self):
        s = self._settings()

        last_root = s.value('source/guide_root', '', type=str)
        last_suffix = s.value('source/suffix', '', type=str)
        # Restore the user's custom suffix history BEFORE applying the
        # last-used suffix - otherwise a custom value would be added
        # as a brand-new entry instead of selecting the existing one.
        custom_suffixes = s.value('source/custom_suffixes', [], type=list)
        if custom_suffixes:
            self.source_panel.set_custom_suffixes(custom_suffixes)
        if last_root:
            self.source_panel.set_guide_root(last_root)
        if last_suffix:
            self.source_panel.set_suffix(last_suffix)

        anim_start = s.value('anim/frame_start', None)
        anim_end = s.value('anim/frame_end', None)
        if anim_start is not None and anim_end is not None:
            try:
                self.animation_tab.set_frame_range(int(anim_start), int(anim_end))
            except (TypeError, ValueError):
                pass

        geom = s.value('window/geometry')
        if geom is not None:
            self.restoreGeometry(geom)
        main_split = s.value('window/main_splitter')
        if main_split is not None:
            self.main_splitter.restoreState(main_split)
        left_split = s.value('window/left_splitter')
        if left_split is not None:
            self.left_splitter.restoreState(left_split)

        # Shared preview filter + auto-pair preference
        filter_key = s.value('frame/filter', '', type=str)
        if filter_key:
            self.set_filter(filter_key)
        auto_pair = s.value('frame/auto_pair', True, type=bool)
        self.set_auto_pair(bool(auto_pair))

        cleanup_intermediates = s.value(
            'frame/cleanup_intermediates', True, type=bool,
        )
        self.frame_tab.set_cleanup_intermediate_files(cleanup_intermediates)

        self.animation_tab.set_clean_preview_before_export(
            s.value('anim/clean_preview', True, type=bool),
        )

        # Restore last-used Prefix / Suffix patterns (just the menu
        # highlight - rows are NOT auto-populated, user clicks once
        # per session).
        last_pattern = s.value('prefix/pattern', '', type=str)
        if last_pattern:
            self.character_list.set_last_pattern(last_pattern)
        last_custom_prefix = s.value('prefix/custom_text', '', type=str)
        if last_custom_prefix:
            self.character_list.set_last_custom_prefix(last_custom_prefix)
        last_suffix_pattern = s.value('suffix/pattern', '', type=str)
        if last_suffix_pattern:
            self.character_list.set_last_suffix_pattern(last_suffix_pattern)
        last_custom_suffix = s.value('suffix/custom_text', '', type=str)
        if last_custom_suffix:
            self.character_list.set_last_custom_suffix(last_custom_suffix)

        last_tab = s.value('window/active_tab', 0, type=int)
        try:
            self.tabs.setCurrentIndex(int(last_tab))
        except (TypeError, ValueError):
            pass

    def _on_active_character(self, row):
        """Select the active character's guide group in the Maya scene.

        Mirrors the active CharacterRow into the user's selection so
        the viewport / outliner highlight tracks what the panel calls
        out. Failures (node renamed, etc.) are logged but never block
        the UI update.
        """
        if row is None:
            return
        try:
            cmds.select(row.long_path, replace=True, noExpand=True)
        except (RuntimeError, ValueError) as exc:
            log.debug('Could not select %s in Maya: %s', row.long_path, exc)

    def _on_shared_source_changed(self):
        """Persist Source values and re-discover the character list."""
        s = self._settings()
        s.setValue('source/guide_root', self.source_panel.guide_root())
        s.setValue('source/suffix', self.source_panel.suffix())
        # Persist user-typed suffix history (add / remove) so it
        # survives across sessions.
        s.setValue(
            'source/custom_suffixes', self.source_panel.custom_suffixes(),
        )
        # Re-scan with the new guide-root pattern; this fires
        # active_changed -> _refresh_preview automatically.
        self.character_list.refresh(self.source_panel.guide_root())

    # ----- shared preview controller --------------------------------------

    def _on_tab_changed(self, _index):
        # Shrink the tab widget down to just the active tab's body so
        # Characters can take the freed vertical space.
        self._compact_tab_sizes()
        is_frame = self.tabs.currentWidget() is self.frame_tab
        is_animation = self.tabs.currentWidget() is self.animation_tab
        # The filter widget only applies to single-frame mode.
        self._filter_widget.setVisible(is_frame)
        # Auto-pair only makes sense in Single-Frame mode (it pairs a
        # Description row with its matching Guide row in the preview).
        # Animation rows are one-per-guide-group; pairing is moot.
        self.pair_check.setVisible(is_frame)
        # Each tab shows a different subset of per-row fields:
        #   frame     -> Prefix / Suffix / Groom / Patches / Dir
        #   animation -> Prefix / Suffix / Guides / Dir
        #   (other)   -> nothing
        if is_frame:
            self.character_list.set_mode('frame')
        elif is_animation:
            self.character_list.set_mode('animation')
        else:
            self.character_list.set_mode('hidden')
        self.preview.setVisible(is_frame or is_animation)
        # Update the shared Export button label + tooltip to match the
        # active tab.
        if is_frame:
            self.action_bar.set_button_label('Export Single Frame')
            self.action_bar.export_btn.setToolTip(
                'Export the groom at the CURRENT frame of the Maya timeline. '
                'Uses each checked character row\'s Groom / Patches / Dir.'
            )
            self.action_bar.set_enabled(True)
        elif is_animation:
            self.action_bar.set_button_label('Export Animation')
            self.action_bar.export_btn.setToolTip(
                'Export the groom over the configured frame range '
                '(from the Animation tab).'
            )
            self.action_bar.set_enabled(True)
        else:  # Settings tab
            self.action_bar.set_button_label('Export')
            self.action_bar.export_btn.setToolTip('')
            self.action_bar.set_enabled(False)
        self._refresh_preview()

    def _on_filter_changed(self, checked):
        if not checked:
            return
        radio = self.sender()
        key = radio.property('filter_key') if radio is not None else FILTER_ALL
        if key == self._current_filter:
            return
        self._current_filter = key
        self._refresh_preview()

    def filter_key(self):
        return self._current_filter

    def set_filter(self, key):
        for radio in (self.radio_all, self.radio_desc,
                      self.radio_patches, self.radio_guides):
            if radio.property('filter_key') == key:
                radio.setChecked(True)
                return

    def auto_pair_enabled(self):
        return self.pair_check.isChecked()

    def set_auto_pair(self, enabled):
        self.pair_check.setChecked(bool(enabled))

    def _refresh_preview(self):
        """Re-query the active tab's data source and repopulate the preview."""
        current = self.tabs.currentWidget()
        if current is self.frame_tab:
            self._refresh_frame_preview()
        elif current is self.animation_tab:
            self._refresh_animation_preview()
        else:
            # Settings tab: leave the preview content alone but blank
            # its rows so it doesn't look stale.
            self._last_preview = utils.FramePreview()
            self.preview.set_rows([])
            self._update_summary_label([])

    def _refresh_frame_preview(self):
        active = self.character_list.active_row()
        namespace = active.namespace if active is not None else ''
        guide_root = (
            active.guide_root if active is not None
            else self.source_panel.guide_root()
        )
        # Mirror the ACTIVE row's per-row Groom / Patches names
        # (decorated with its Prefix / Suffix) into the preview so
        # editing those line edits visually updates the Output column.
        groom_filename = None
        patches_filename = None
        if active is not None:
            groom_filename = self._decorate(
                self._ensure_abc(active.output_name() or 'groom.abc'),
                active.prefix(), active.suffix(),
            )
            patches_filename = self._decorate(
                self._ensure_abc(active.patches_name() or 'patches.abc'),
                active.prefix(), active.suffix(),
            )
        try:
            self._last_preview = utils.frame_preview_groups(
                guide_root, self.source_panel.suffix(),
                namespace=namespace,
                groom_filename=groom_filename,
                patches_filename=patches_filename,
            )
        except Exception:
            self._last_preview = utils.FramePreview()
        rows = self._rows_for_filter(self._current_filter)
        self.preview.set_rows(rows)
        self._update_summary_label(rows)

    def _refresh_animation_preview(self):
        # Animation rows have no filter / no namespace scoping.
        self._last_preview = utils.FramePreview()
        all_rows = self.character_list.all_rows()
        checked_rows = self.character_list.checked_rows()

        # If the scene has guide groups but the user unchecked all of
        # them, surface that explicitly instead of showing the generic
        # "no nodes found" message - the nodes ARE there, just opted-
        # out for this export.
        if all_rows and not checked_rows:
            self.preview.set_empty_message('No characters checked.')
            self.preview.set_rows([])
            self._update_summary_label([])
            return
        self.preview.set_empty_message('No items- click Detect to try.')

        # Mirror each checked CharacterRow's per-row Guides filename
        # (decorated with the row's Prefix / Suffix) into the preview's
        # Output column so users see exactly what gets written.
        name_by_path = {}
        dir_by_path = {}
        for row in checked_rows:
            base = self._ensure_abc(row.guides_name() or 'guides.abc')
            name_by_path[row.long_path] = self._decorate(
                base, row.prefix(), row.suffix(),
            )
            dir_by_path[row.long_path] = row.export_dir() or ''
        checked_paths = {r.long_path for r in checked_rows}
        try:
            scene_is_saved = bool(cmds.file(q=True, sceneName=True))
            rows = utils.animation_preview_rows(
                self.source_panel.guide_root(), scene_is_saved,
                name_by_path=name_by_path,
                # None = no filter (scene-empty case); otherwise the
                # checked-path set.
                included_paths=checked_paths if checked_paths else None,
                dir_by_path=dir_by_path,
            )
        except Exception:
            rows = []
        self.preview.set_rows(rows)
        self._update_summary_label(rows)

    def _update_summary_label(self, rows):
        total = len(rows)
        if total == 0:
            self.summary_label.setText(self.preview._empty_message)
            return
        warnings = sum(1 for r in rows if r.status == utils.STATUS_WARNING)
        errors = sum(1 for r in rows if r.status == utils.STATUS_ERROR)
        parts = ['{} item{}'.format(total, '' if total == 1 else 's')]
        if warnings:
            parts.append('{} warning{}'.format(warnings, '' if warnings == 1 else 's'))
        if errors:
            parts.append('{} error{}'.format(errors, '' if errors == 1 else 's'))
        self.summary_label.setText(' - '.join(parts))

    def _rows_for_filter(self, key):
        p = self._last_preview
        if key == FILTER_DESCRIPTIONS:
            return list(p.descriptions)
        if key == FILTER_PATCHES:
            return list(p.patches)
        if key == FILTER_GUIDES:
            return list(p.guides)
        return p.all_rows()

    def _on_preview_selection(self, paths):
        if self._applying_pair:
            return
        all_paths = list(paths)
        if (self.tabs.currentWidget() is self.frame_tab
                and self.pair_check.isChecked()):
            pair_paths = self._find_paired_paths(paths)
            if pair_paths:
                self._select_pair_rows(pair_paths)
                for p in pair_paths:
                    if p not in all_paths:
                        all_paths.append(p)
        try:
            if all_paths:
                cmds.select(all_paths, replace=True, noExpand=True)
            else:
                cmds.select(clear=True)
        except (RuntimeError, ValueError) as exc:
            log.debug('Could not select %s in Maya: %s', all_paths, exc)

    def _find_paired_paths(self, selected_paths):
        suffix = self.source_panel.suffix()
        selected = set(selected_paths)
        desc_rows = self._last_preview.descriptions
        guide_rows = self._last_preview.guides
        # Use match_key when present (descriptions strip "Shape" from
        # their displayed name; guides keep their bare stem); fall
        # back to .name so legacy rows still pair.
        desc_by_match = {(r.match_key or r.name): r for r in desc_rows}
        guide_by_match = {(r.match_key or r.name): r for r in guide_rows}

        out = []
        for row in (desc_rows + guide_rows):
            if row.path not in selected or not row.path:
                continue
            if row.kind == 'Description':
                partner = guide_by_match.get(row.match_key or row.name)
            elif row.kind == 'Guide Group':
                # Guide row's match_key already strips the suffix.
                key = row.match_key or self._stem_for(row.name, suffix)
                partner = desc_by_match.get(key)
            else:
                partner = None
            if partner is not None and partner.path and partner.path not in selected:
                if partner.path not in out:
                    out.append(partner.path)
        return out

    @staticmethod
    def _stem_for(child_short, suffix):
        if not suffix:
            return child_short
        idx = child_short.lower().rfind(suffix.lower())
        if idx != -1:
            return child_short[:idx].rstrip('_')
        return child_short

    def _select_pair_rows(self, pair_paths):
        if not pair_paths:
            return
        table = self.preview.table
        self._applying_pair = True
        try:
            for r in range(table.rowCount()):
                item = table.item(r, 0)
                if item is None:
                    continue
                if item.data(QtCore.Qt.UserRole) in pair_paths:
                    sm = table.selectionModel()
                    index = table.model().index(r, 0)
                    sm.select(
                        index,
                        sm.SelectionFlag.Select | sm.SelectionFlag.Rows,
                    )
        finally:
            self._applying_pair = False

    def _save_anim_range(self):
        s = self._settings()
        start, end = self.animation_tab.frame_range()
        s.setValue('anim/frame_start', int(start))
        s.setValue('anim/frame_end', int(end))

    def closeEvent(self, event):
        s = self._settings()
        s.setValue('window/geometry', self.saveGeometry())
        s.setValue('window/main_splitter', self.main_splitter.saveState())
        s.setValue('window/left_splitter', self.left_splitter.saveState())
        s.setValue('frame/filter', self.filter_key())
        s.setValue('frame/auto_pair', self.auto_pair_enabled())
        s.setValue('window/active_tab', self.tabs.currentIndex())
        s.setValue('source/guide_root', self.source_panel.guide_root())
        s.setValue('source/suffix', self.source_panel.suffix())
        s.setValue(
            'source/custom_suffixes', self.source_panel.custom_suffixes(),
        )
        s.setValue(
            'frame/cleanup_intermediates',
            self.frame_tab.cleanup_intermediate_files(),
        )
        s.setValue(
            'anim/clean_preview',
            self.animation_tab.clean_preview_before_export(),
        )
        s.setValue('prefix/pattern', self.character_list.last_pattern())
        s.setValue(
            'prefix/custom_text', self.character_list.last_custom_prefix(),
        )
        s.setValue(
            'suffix/pattern', self.character_list.last_suffix_pattern(),
        )
        s.setValue(
            'suffix/custom_text', self.character_list.last_custom_suffix(),
        )
        self._save_anim_range()
        self.log_panel.detach()
        super(XgenToUETool, self).closeEvent(event)

    def _on_animation_tab_changed(self):
        self._save_anim_range()

    # ----- failure dialog --------------------------------------------------

    def _report_failure(self, exc):
        log.error('%s', exc)
        log.error(traceback.format_exc())
        QtWidgets.QMessageBox.critical(
            self,
            'Export failed',
            '{}\n\nSee the log panel for details.'.format(exc),
        )

    # ----- save-changes guard ---------------------------------------------

    def _confirm_save_changes(self):
        if not cmds.file(query=True, modified=True):
            return True
        scene = cmds.file(query=True, sceneName=True) or 'untitled'
        result = cmds.confirmDialog(
            title='Save Changes',
            message='Save changes to {}?'.format(scene),
            button=['Save', "Don't Save", 'Cancel'],
            defaultButton='Save',
            cancelButton='Cancel',
            dismissString='Cancel',
        )
        if result == 'Save':
            cmds.file(save=True, force=True)
        elif result == 'Cancel':
            return False
        return True

    # ----- single frame ---------------------------------------------------

    def _frame_progress(self, percent, message=''):
        self.action_bar.set_progress(percent, message)
        QtWidgets.QApplication.processEvents()

    def _export_single_frame(self):
        cmds.waitCursor(state=True)
        cmds.undoInfo(openChunk=True)
        self.action_bar.set_enabled(False)
        first_dir = None
        # riCurves attrs we temporarily add to guide-group children
        # for AbcExport. Cleaned up in the finally block - works on
        # referenced nodes (transient ref-edit pair, evaporates if
        # the user closes Maya without saving).
        added_ri_curves_frame = []
        # Descriptions that produced no strands, per row: [(label, [names])].
        # Surfaced as a single warning summary after all rows run.
        failed_descriptions = []
        total = 0
        export_ok = False
        try:
            # Guarantee the export commands exist. Single-frame export
            # does NOT scrub the timeline, so it deliberately leaves the
            # live XGen preview alone (preview cleaning is an Animation-
            # tab opt-in). ensure_plugins_loaded raises a clear error if
            # a required plugin is genuinely unavailable.
            ensure_plugins_loaded()
            rows = self.character_list.checked_rows()
            if not rows:
                raise ValueError(
                    'No guide groups checked - tick at least one row in '
                    'the Characters list.'
                )

            suffix = self.source_panel.suffix()
            total = len(rows)

            for index, row in enumerate(rows):
                resolved_dir = self._export_single_frame_for_row(
                    row, suffix, index, total,
                    added_ri_curves=added_ri_curves_frame,
                    failed_accum=failed_descriptions,
                )
                if first_dir is None:
                    first_dir = resolved_dir

            if first_dir:
                self.action_bar.set_last_export_dir(first_dir)
            log.info('Single-frame export complete: %d row(s)', total)
            export_ok = True

            if failed_descriptions:
                lines = [
                    '{}: {}'.format(label, ', '.join(names))
                    for label, names in failed_descriptions
                ]
                log.warning(
                    'Export finished with skipped descriptions:\n%s',
                    '\n'.join(lines),
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    'Groom export incomplete',
                    'Some descriptions produced no strands and were '
                    'skipped:\n\n{}\n\nThis usually means their XGen data '
                    '(paint maps / clump guides) is missing at the resolved '
                    'xgDataPath. The .abc files were still written, minus '
                    'those groom groups.'.format('\n'.join(lines)),
                )

        except Exception as exc:
            self._report_failure(exc)
            self.action_bar.reset()
        finally:
            # The export isn't really "done" until the teardown below
            # (riCurves rollback + preview refresh) has run, so show a
            # Finalizing state here and hold the Done label until the very
            # end - otherwise the UI says Done while work is still going.
            if export_ok:
                self._frame_progress(96, 'Finalizing')
            # Roll back the riCurves attributes we added to source
            # transforms. On referenced nodes this leaves a transient
            # add+remove ref-edit pair that disappears as soon as the
            # user closes Maya without saving.
            for node, attr in added_ri_curves_frame:
                try:
                    if cmds.attributeQuery(attr, node=node, exists=True):
                        cmds.deleteAttr('{}.{}'.format(node, attr))
                except (RuntimeError, ValueError):
                    pass
            cmds.undoInfo(closeChunk=True)
            cmds.waitCursor(state=False)
            self.action_bar.set_enabled(True)
            # Export converts/deletes temporary spline nodes and toggles
            # riCurves attrs; rebuild the preview from the now-clean scene
            # so it reflects reality. Without this the preview kept its
            # pre-export rows and looked stale/doubled until the user
            # clicked a row or Detect to refresh manually.
            try:
                self._refresh_preview()
            except Exception:
                pass
            # Everything is finished now - show Done last (success only).
            if export_ok:
                self._frame_progress(100, 'Done {}/{}'.format(total, total))

    def _export_single_frame_for_row(self, row, suffix, index, total,
                                     added_ri_curves=None, failed_accum=None):
        """Run the single-frame export for one CharacterListPanel row.

        File-name policy:
        - Base names come from the row's ``Groom`` / ``Patches`` fields
          (defaults: 'groom.abc' / 'patches.abc').
        - The row's ``Prefix`` and ``Suffix`` fields decorate every
          output file. ``decorate(base, prefix, suffix)`` produces
          ``<prefix>_<stem>_<suffix>.<ext>`` with the underscore
          separators only when the prefix / suffix are non-empty.
            * Prefix '', Suffix ''       -> 'groom.abc' / 'strands.abc' ...
            * Prefix 'charB', Suffix '' -> 'charB_groom.abc' ...
            * Prefix 'charB', Suffix 'v2' -> 'charB_groom_v2.abc' ...

        Returns the resolved export directory used.
        """
        row_dir = row.export_dir()
        if not row_dir:
            raise ValueError(
                'Row "{}" has no Export Dir set. Fill it in (or click '
                'the "..." button) before exporting.'.format(row.short_name)
            )
        export_dir = utils.ensure_writable_dir(row_dir)
        guide_root = row.guide_root

        row_prefix = row.prefix()
        row_suffix = row.suffix()
        output_name = self._decorate(
            self._ensure_abc(row.output_name() or 'groom.abc'),
            row_prefix, row_suffix,
        )
        patches_name = self._decorate(
            self._ensure_abc(row.patches_name() or 'patches.abc'),
            row_prefix, row_suffix,
        )
        strands_name = self._decorate('strands.abc', row_prefix, row_suffix)
        guides_name = self._decorate('guides.abc', row_prefix, row_suffix)
        mesh_map_name = self._decorate(
            'description_mesh_map.json', row_prefix, row_suffix,
        )

        # Stems (no '.abc') for export helpers that append it.
        def stem(name):
            return name[:-4] if name.endswith('.abc') else name

        per_row_start = int(index / total * 90)
        per_row_step = (1.0 / total) * 90.0

        def step_progress(fraction, message):
            self._frame_progress(
                int(per_row_start + per_row_step * fraction),
                '[{}/{}] {}'.format(index + 1, total, message),
            )

        log.info(
            'Exporting row %d/%d: guide_root=%r output=%r patches=%r dir=%s',
            index + 1, total, guide_root, output_name, patches_name, export_dir,
        )

        # Filter descriptions / mesh patches / strands by the
        # active row's namespace. In a shot file with both
        # ``charA:`` and ``charA1:`` referenced, exporting unfiltered
        # collapses both characters' data after -stripNamespaces
        # (same short name -> one overwrites the other), leaving
        # the merged groom with the wrong strand counts and a
        # missing brow_a_splineDescription.
        ns = row.namespace
        step_progress(0.05, 'Collecting descriptions')
        description_mesh_map = get_description_mesh_map(namespace=ns)
        dump_map = {
            k: [p.split('|')[-1] for p in v]
            for k, v in description_mesh_map.items()
        }
        with open(os.path.join(export_dir, mesh_map_name), 'w') as fh:
            json.dump(dump_map, fh, indent=4)

        step_progress(0.15, 'Exporting patches')
        mesh_patches = list({p for v in description_mesh_map.values() for p in v})
        if mesh_patches:
            export_group(mesh_patches, export_dir, file_name=stem(patches_name))

        step_progress(0.35, 'Exporting strands')
        # collect_spline_descriptions returns BOTH the freshly-
        # converted xgmDescriptions AND any pre-existing
        # xgmSplineDescriptions in the namespace. The second list
        # is what catches characters like brow_a whose description
        # is already an Interactive Groom and so doesn't surface
        # through xgmGroomConvert.
        all_splines, temp_splines, failed = collect_spline_descriptions(
            namespace=ns,
        )
        if failed:
            label = row.top_group_name or ns or '?'
            log.warning(
                'Row %s: %d description(s) produced NO strands and were '
                'skipped: %s. Usual cause: the description\'s XGen data '
                '(density paint map / clump guides) is missing at the '
                'resolved xgDataPath, so it generates 0 primitives. The '
                'exported groom will lack these groom groups.',
                label, len(failed), ', '.join(sorted(failed)),
            )
            if failed_accum is not None:
                failed_accum.append((label, sorted(failed)))
        if all_splines:
            export_interactive_groom(
                all_splines, export_dir, file_name=stem(strands_name),
            )
            # Only delete the ones xgmGroomConvert created on the
            # fly - the pre-existing artist-authored splines must
            # stay in the scene.
            if temp_splines:
                cmds.delete(temp_splines)

        step_progress(0.60, 'Exporting guides')
        # Tag each <description>_guides child with `riCurves` so AbcExport
        # merges its guide curves into ONE Curve (UE rejects the un-merged
        # shape with "Some groups have 0 curves"), and export rooted at
        # guide_root itself so the character's world offset stays on the
        # exported guide_root Xform (rooting at the children under
        # -worldSpace drops that parent offset). flatten_guide_groups then
        # bakes that offset into the points and promotes each merged curve
        # to a clean top-level Curve. riCurves is rolled back in the
        # caller's finally (a transient ref-edit on referenced nodes).
        guide_children = cmds.listRelatives(
            guide_root, children=True, fullPath=True, type='transform',
        ) or []
        if not guide_children:
            raise ValueError(
                'No child transforms under {!r} - nothing to export.'.format(
                    guide_root,
                )
            )
        for child in guide_children:
            if not cmds.attributeQuery('riCurves', node=child, exists=True):
                cmds.addAttr(
                    child, longName='riCurves', attributeType='bool',
                    defaultValue=1, keyable=True,
                )
                if added_ri_curves is not None:
                    added_ri_curves.append((child, 'riCurves'))
            cmds.setAttr('{}.riCurves'.format(child), 1)
        export_group([guide_root], export_dir, file_name=stem(guides_name))
        # Flatten the riCurves-merged groups to clean top-level Curves
        # (baking in the world offset), then bake the groom attributes UE's
        # groom system expects - matching the known-good reference layout.
        fps = self._scene_fps()
        guides_abc_path = os.path.join(export_dir, guides_name)
        flatten_guide_groups(guides_abc_path, fps=fps)
        add_animation_groom_attributes(guides_abc_path, suffix=suffix, fps=fps)

        step_progress(0.80, 'Merging and adding groom attributes')
        strands_abc = os.path.join(export_dir, strands_name)
        guides_abc = os.path.join(export_dir, guides_name)
        groom_abc = os.path.join(export_dir, output_name)
        patches_abc = os.path.join(export_dir, patches_name)
        mesh_map_json = os.path.join(export_dir, mesh_map_name)
        merge_and_process_abc(
            strands_abc, guides_abc, groom_abc,
            patches_abc=patches_abc if os.path.exists(patches_abc) else None,
            mesh_map_json=mesh_map_json if os.path.exists(mesh_map_json) else None,
        )

        # Strands/guides Alembics and the description-mesh JSON are
        # intermediate inputs to merge_and_process_abc - groom.abc
        # and patches.abc are the only outputs downstream tools
        # consume. The FrameTab checkbox lets the user keep them
        # around when debugging an export, but the default is to
        # tidy up.
        if self.frame_tab.cleanup_intermediate_files():
            for path in (strands_abc, guides_abc, mesh_map_json):
                if os.path.exists(path) and _safe_remove(path):
                    log.info('Removed intermediate %s', path)

        step_progress(1.0, 'Done')
        log.info('Exported %s -> %s', row.namespace or row.guide_root, groom_abc)
        return export_dir

    @staticmethod
    def _ensure_abc(name):
        """Normalize a user-typed filename to end in '.abc'."""
        name = name.strip()
        if not name:
            return ''
        if not name.lower().endswith('.abc'):
            name = name + '.abc'
        return name

    @staticmethod
    def _decorate(base_name, prefix, suffix):
        """Insert ``<prefix>_`` and ``_<suffix>`` into ``base_name``.

        The separators only appear when the corresponding piece is
        non-empty. Works for any extension (``.abc``, ``.json``, ...).

            decorate('groom.abc', '', '')           -> 'groom.abc'
            decorate('groom.abc', 'charB', '')    -> 'charB_groom.abc'
            decorate('groom.abc', 'charB', 'v2')  -> 'charB_groom_v2.abc'
            decorate('description_mesh_map.json', 'charB', '')
                                                    -> 'charB_description_mesh_map.json'
        """
        prefix = (prefix or '').strip()
        suffix = (suffix or '').strip()
        if not base_name:
            return ''
        dot = base_name.rfind('.')
        if dot > 0:
            stem = base_name[:dot]
            ext = base_name[dot:]
        else:
            stem = base_name
            ext = ''
        parts = [p for p in (prefix, stem, suffix) if p]
        return '_'.join(parts) + ext

    # ----- animation ------------------------------------------------------

    def _anim_progress(self, percent, message=''):
        self.action_bar.set_progress(percent, message)
        QtWidgets.QApplication.processEvents()

    def _export_animation(self):
        """Export every checked character in ONE AbcExport pass.

        Workflow:

        1. Validate every row's Dir + decorated filename up front.
        2. For each row, list the ``<description>_Guides`` child
           transforms directly under ``row.long_path`` - these are
           the AbcExport roots. We do NOT mutate Maya's DAG (no
           reparent, no temp transforms), so referenced guide groups
           don't need to be imported and the scene doesn't need to
           be reopened afterwards.
        3. Submit ONE ``cmds.AbcExport`` with N jobs (one .abc per
           character, possibly multiple ``-root`` args inside a
           single job) - Maya scrubs the timeline once for the
           entire batch.
        4. Post-process each output ``.abc`` with
           :func:`add_animation_groom_attributes` to bake the
           groom_group_name / groom_group_id / groom_guide /
           ``.userProperties`` attributes that UE's groom system
           expects. This replaces what
           ``create_guide_attributes`` used to do in Maya, but on
           the .abc file - so referenced nodes are never edited.
        """
        cmds.waitCursor(state=True)
        self.action_bar.set_enabled(False)
        anim_ok = False
        added_ri_curves = []  # (node, attr_name) we temporarily added
        try:
            # Load required plugins, and (opt-in) quiet the live preview
            # before the whole-timeline AbcExport scrub - preview re-eval
            # per frame is the expensive case the checkbox avoids. It's
            # non-restoring, so it's off unless the user ticks it.
            ensure_plugins_loaded()
            if self.animation_tab.clean_preview_before_export():
                clean_xgen_preview()
            suffix = self.source_panel.suffix()
            frame_start, frame_end = self.animation_tab.frame_range()

            checked_rows = self.character_list.checked_rows()
            if not checked_rows:
                raise ValueError(
                    'No guide groups checked - tick at least one row in '
                    'the Characters list.'
                )

            # Validate dirs + decorate filenames + resolve the
            # AbcExport root set per row, all up front so we never
            # start an export only to fail halfway through.
            plan = []
            for row in checked_rows:
                row_dir = row.export_dir()
                if not row_dir:
                    raise ValueError(
                        'Row "{}" has no Export Dir set. Fill it in (or '
                        'click the "..." button) before exporting.'.format(
                            row.short_name,
                        )
                    )
                resolved_dir = utils.ensure_writable_dir(row_dir)
                base_name = self._ensure_abc(row.guides_name() or 'guides.abc')
                decorated = self._decorate(
                    base_name, row.prefix(), row.suffix(),
                )
                # The AbcExport root is the guide-root transform itself
                # (guide_grp), NOT its children. Rooting at guide_grp and
                # tagging each <description>_guides child with `riCurves`
                # makes AbcExport (a) merge each description's guide curves
                # into ONE Curve and (b) keep the character's world offset
                # on the exported guide_grp Xform (rooting at the children
                # under -worldSpace drops that parent offset). The offset is
                # then baked into the points by flatten_guide_groups.
                # AbcExport samples curves through the DG regardless of
                # whether they're referenced, so this works for shot files
                # without importing the reference.
                child_groups = cmds.listRelatives(
                    row.long_path, children=True, fullPath=True,
                    type='transform',
                ) or []
                if not child_groups:
                    raise ValueError(
                        'Row "{}" has no child transforms under {} - '
                        'nothing to export.'.format(
                            row.short_name, row.long_path,
                        )
                    )
                plan.append({
                    'row': row,
                    'roots': [row.long_path],
                    'child_groups': child_groups,
                    'file_name': decorated,
                    'dir': resolved_dir,
                })

            # Refuse to export when two rows resolve to the SAME output
            # file (same dir + filename) - one would silently overwrite
            # the other. Different dirs with the same filename are fine.
            seen_outputs = {}
            for entry in plan:
                full = os.path.normpath(
                    os.path.join(entry['dir'], entry['file_name'])
                )
                key = full.lower()  # Windows paths are case-insensitive
                if key in seen_outputs:
                    raise ValueError(
                        'Two characters would export to the same file:\n  '
                        '{}\n("{}" and "{}"). Give them different Dirs or '
                        'Guides filenames before exporting.'.format(
                            full, seen_outputs[key], entry['row'].short_name,
                        )
                    )
                seen_outputs[key] = entry['row'].short_name

            # Tag each <description>_guides child with `riCurves` so
            # AbcExport merges its guide curves into ONE Curve (UE rejects
            # the un-merged shape with "Some groups have 0 curves"). We add
            # the attr on the source nodes and roll it back in `finally`;
            # on referenced shot nodes this is a transient add/remove
            # ref-edit pair. The export then roots at guide_grp (set in the
            # plan above) so the character's world offset is preserved, and
            # flatten_guide_groups bakes that offset into the points.
            for entry in plan:
                for child in entry['child_groups']:
                    if not cmds.attributeQuery(
                        'riCurves', node=child, exists=True,
                    ):
                        cmds.addAttr(
                            child, longName='riCurves',
                            attributeType='bool', defaultValue=1,
                            keyable=True,
                        )
                        added_ri_curves.append((child, 'riCurves'))
                    cmds.setAttr('{}.riCurves'.format(child), 1)

            self._anim_progress(
                10, 'Exporting {} character(s) in one timeline pass'.format(
                    len(plan),
                ),
            )
            jobs = []
            for entry in plan:
                stem = entry['file_name']
                if stem.endswith('.abc'):
                    stem = stem[:-4]
                jobs.append({
                    'groups': entry['roots'],
                    'export_dir': entry['dir'],
                    'file_name': stem,
                    'frame_start': frame_start,
                    'frame_end': frame_end,
                })
            export_groups_batch(jobs)

            # Cask post-process: flatten each riCurves-merged guide group
            # to a clean top-level Curve (baking the guide_grp world offset
            # into the points), then bake the groom attributes UE's groom
            # system expects. Together these replace what
            # create_guide_attributes used to do in Maya.
            fps = self._scene_fps()
            for i, entry in enumerate(plan):
                pct = 60 + int((i + 1) / len(plan) * 35)
                self._anim_progress(
                    pct, 'Adding groom attributes to {}'.format(
                        entry['file_name'],
                    ),
                )
                abc_path = os.path.join(entry['dir'], entry['file_name'])
                flatten_guide_groups(abc_path, fps=fps)
                add_animation_groom_attributes(abc_path, suffix=suffix, fps=fps)

            # Each per-row Dir gets its own anim_meta.json so artists
            # who split characters into separate folders still have
            # FPS / frame range alongside their .abc files.
            unique_dirs = []
            for entry in plan:
                if entry['dir'] not in unique_dirs:
                    unique_dirs.append(entry['dir'])
            for d in unique_dirs:
                self._write_anim_metadata(d, frame_start, frame_end)

            self.action_bar.set_last_export_dir(
                plan[0]['dir'] if plan else '',
            )
            log.info(
                'Animation export complete: %d row(s) in 1 AbcExport '
                'pass into %s', len(plan), ', '.join(unique_dirs),
            )
            anim_ok = True

        except Exception as exc:
            self._report_failure(exc)
            self.action_bar.reset()
        finally:
            # Hold the Done label until teardown + refresh have run (see
            # _export_single_frame) so the UI doesn't read Done early.
            if anim_ok:
                self._anim_progress(96, 'Finalizing')
            # Roll back the riCurves attributes we added so the scene
            # is left in the state we found it. On referenced nodes
            # this leaves a transient add+remove ref-edit pair that
            # disappears the moment the user closes Maya without
            # saving.
            for node, attr in added_ri_curves:
                try:
                    if cmds.attributeQuery(attr, node=node, exists=True):
                        cmds.deleteAttr('{}.{}'.format(node, attr))
                except (RuntimeError, ValueError):
                    pass
            cmds.waitCursor(state=False)
            self.action_bar.set_enabled(True)
            # Rebuild the preview from the now-clean scene (see the
            # matching note in _export_single_frame).
            try:
                self._refresh_preview()
            except Exception:
                pass
            # Everything is finished now - show Done last (success only).
            if anim_ok:
                self._anim_progress(100, 'Done')

    @staticmethod
    def _scene_fps():
        """Resolve Maya's current time unit to a numeric FPS.

        Used both for the cask post-process (so time samples are read
        back at the scene's real rate) and for anim_meta.json.
        """
        fps_name = cmds.currentUnit(query=True, time=True)
        fps_map = {
            'game': 15, 'film': 24, 'pal': 25, 'ntsc': 30,
            'show': 48, 'palf': 50, 'ntscf': 60,
        }
        fps_value = fps_map.get(fps_name)
        if fps_value is None:
            try:
                fps_value = float(str(fps_name).replace('fps', ''))
            except (ValueError, AttributeError):
                fps_value = 24
        return fps_value

    @classmethod
    def _write_anim_metadata(cls, export_dir, frame_start, frame_end):
        meta = {
            'fps': cls._scene_fps(),
            'frame_start': frame_start,
            'frame_end': frame_end,
        }
        with open(os.path.join(export_dir, 'anim_meta.json'), 'w') as fh:
            json.dump(meta, fh, indent=4)


def show():
    """Open (or re-open) the XgenToUE tool window."""
    parent = utils.get_maya_main_window()
    if parent is not None:
        for existing in parent.findChildren(
            QtWidgets.QWidget, XgenToUETool.OBJECT_NAME,
        ):
            existing.close()
            existing.deleteLater()
    tool = XgenToUETool(parent=parent)
    tool.show()
    return tool
