"""Export Single Frame tab.

Frame mode's UI lives mostly at the main window level (Source,
Characters, Preview, ActionBar, LogPanel are all shared). The tab body
only carries options that are specific to single-frame export.
"""

import logging

from xgentoue.gui.qtcompat import QtCore, QtWidgets

log = logging.getLogger('xgentoue')


class FrameTab(QtWidgets.QWidget):
    """Single-frame export tab - frame-only options live here."""

    changed = QtCore.Signal()

    def __init__(self, parent=None, source_panel=None):
        super(FrameTab, self).__init__(parent)
        if source_panel is None:
            raise ValueError(
                'FrameTab requires a shared SourcePanel instance.'
            )
        self.source_panel = source_panel

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Single-frame produces five files per character but only
        # groom.abc + patches.abc are wanted downstream. The other
        # three (strands.abc / guides.abc / description_mesh_map.json)
        # are intermediates fed into merge_and_process_abc and are
        # safe to delete afterwards.
        # Keep the label short: a QCheckBox can't wrap or elide its
        # text, so a long label sets a wide minimum width that floors
        # the whole left column and stops users from narrowing it. The
        # specifics (which files) live in the tooltip instead.
        self.cleanup_check = QtWidgets.QCheckBox(
            'Delete intermediate files after merge'
        )
        self.cleanup_check.setToolTip(
            'After the per-character merge produces groom.abc and '
            'patches.abc, remove the intermediate files (strands.abc, '
            'guides.abc, *_mesh_map.json) so the export folder stays '
            'tidy. Uncheck if you want to inspect or debug the '
            'intermediate Alembics.'
        )
        self.cleanup_check.setChecked(True)
        self.cleanup_check.toggled.connect(lambda _=False: self.changed.emit())
        layout.addWidget(self.cleanup_check)

        layout.addStretch(1)

    def on_shared_source_changed(self):
        pass

    # ----- public API ------------------------------------------------------

    def cleanup_intermediate_files(self):
        return self.cleanup_check.isChecked()

    def set_cleanup_intermediate_files(self, value):
        self.cleanup_check.setChecked(bool(value))

    # Legacy shims kept for older _load_settings paths.
    def set_guide_root(self, _value):
        pass

    def set_suffix(self, _value):
        pass
