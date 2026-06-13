"""Frame range picker for the Export Animation tab.

Defaults the start / end values to Maya's current playback range. Edits
fire :pyattr:`changed` so the parent tab can refresh its preview and
persist the new range.
"""

from maya import cmds

from xgentoue.gui.qtcompat import QtCore, QtWidgets


class FrameRangePanel(QtWidgets.QWidget):
    """'Frame Range' label + start / end spin boxes, all on one row."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super(FrameRangePanel, self).__init__(parent)
        self._build()

    def _build(self):
        layout = QtWidgets.QHBoxLayout(self)
        # No group box any more - the parent tab supplies the outer
        # margins, so keep this row flush and let the label lead it.
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel('Frame Range'))
        layout.addSpacing(8)

        self.frame_start_spin = QtWidgets.QSpinBox()
        self.frame_start_spin.setRange(-100000, 100000)
        self.frame_start_spin.setValue(
            int(cmds.playbackOptions(q=True, minTime=True))
        )
        self.frame_start_spin.setToolTip(
            'First frame to sample in the animation export. '
            'Defaults to Maya\'s current playback start. Click the '
            '↻ button to snap back to the playback range.'
        )
        self.frame_start_spin.valueChanged.connect(lambda _: self.changed.emit())

        self.frame_end_spin = QtWidgets.QSpinBox()
        self.frame_end_spin.setRange(-100000, 100000)
        self.frame_end_spin.setValue(
            int(cmds.playbackOptions(q=True, maxTime=True))
        )
        self.frame_end_spin.setToolTip(
            'Last frame to sample in the animation export (inclusive). '
            'Defaults to Maya\'s current playback end.'
        )
        self.frame_end_spin.valueChanged.connect(lambda _: self.changed.emit())

        layout.addWidget(QtWidgets.QLabel('Start'))
        layout.addWidget(self.frame_start_spin)
        layout.addSpacing(8)
        layout.addWidget(QtWidgets.QLabel('End'))
        layout.addWidget(self.frame_end_spin)

        self.reset_btn = QtWidgets.QToolButton()
        self.reset_btn.setText(u'↻')
        self.reset_btn.setToolTip("Reset to Maya's current playback range")
        self.reset_btn.clicked.connect(self.reset_to_scene_range)
        layout.addWidget(self.reset_btn)

        layout.addStretch(1)

    # ----- public API ------------------------------------------------------

    def frame_range(self):
        return self.frame_start_spin.value(), self.frame_end_spin.value()

    def set_frame_range(self, start, end):
        if start is not None:
            self.frame_start_spin.setValue(int(start))
        if end is not None:
            self.frame_end_spin.setValue(int(end))

    def reset_to_scene_range(self):
        """Snap Start/End to Maya's current playback range.

        Uses ``playbackOptions(minTime/maxTime)``, i.e. the range
        bracketed by Maya's timeline slider - what artists actually
        see and scrub. ``animationStartTime/animationEndTime`` would
        give the full scene range, which is usually wider.
        """
        start = int(cmds.playbackOptions(q=True, minTime=True))
        end = int(cmds.playbackOptions(q=True, maxTime=True))
        # setValue fires valueChanged -> changed for each spin box; the
        # parent tab reacts to the single resulting changed emission.
        self.frame_start_spin.setValue(start)
        self.frame_end_spin.setValue(end)
