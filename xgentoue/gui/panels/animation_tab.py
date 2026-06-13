"""Export Animation tab.

Holds the FrameRangePanel. CharacterList + ActionBar + PreviewTable
live at the main window level; per-row export Dirs on each
CharacterRow are the source of truth for output paths (there is no
tab-level Output Dir - it was only confusing duplicate state).
"""

import logging

from xgentoue.gui.panels.frame_range_panel import FrameRangePanel
from xgentoue.gui.qtcompat import QtCore, QtWidgets

log = logging.getLogger('xgentoue')


class AnimationTab(QtWidgets.QWidget):
    """Animation export tab - one ABC per guide-root over a frame range."""

    changed = QtCore.Signal()

    def __init__(self, parent=None, source_panel=None):
        super(AnimationTab, self).__init__(parent)
        if source_panel is None:
            raise ValueError(
                'AnimationTab requires a shared SourcePanel instance.'
            )
        self.source_panel = source_panel
        self._build()
        self._wire()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.frame_range_panel = FrameRangePanel()
        layout.addWidget(self.frame_range_panel)

        # Animation export scrubs the whole timeline, so a live XGen
        # preview re-evaluates on every frame. Cleaning it first speeds
        # the scrub up. It's non-restoring (the preview stays off after),
        # hence opt-out via this checkbox. Single-frame export doesn't
        # scrub, so it never touches the preview.
        self.clean_preview_check = QtWidgets.QCheckBox(
            'Clean XGen preview before export'
        )
        self.clean_preview_check.setToolTip(
            'Turn off the live XGen preview before exporting so Maya '
            'does not re-evaluate it on every frame of the timeline '
            'scrub (faster, more stable). The preview is left off '
            'afterwards - regenerate it from the XGen editor if needed. '
            'Uncheck to keep your live preview untouched.'
        )
        self.clean_preview_check.setChecked(True)
        layout.addWidget(self.clean_preview_check)

        layout.addStretch(1)

    def _wire(self):
        self.frame_range_panel.changed.connect(self._on_range_changed)

    def on_shared_source_changed(self):
        pass

    # ----- public API ------------------------------------------------------

    def guide_root(self):
        return self.source_panel.guide_root()

    def suffix(self):
        return self.source_panel.suffix()

    def frame_range(self):
        return self.frame_range_panel.frame_range()

    def set_guide_root(self, _value):
        pass

    def set_suffix(self, _value):
        pass

    def set_frame_range(self, start, end):
        self.frame_range_panel.set_frame_range(start, end)

    def clean_preview_before_export(self):
        return self.clean_preview_check.isChecked()

    def set_clean_preview_before_export(self, value):
        self.clean_preview_check.setChecked(bool(value))

    def _on_range_changed(self):
        # Frame range doesn't affect the preview - just persist.
        self.changed.emit()
