"""Window-level action row: progress bar + Check + Export buttons.

The Export button label is parameterised so the same widget serves the
single-frame and animation flows; :meth:`set_button_label` swaps it on
tab change. The Check button runs a read-only scene validation and never
changes label.
"""

from xgentoue.gui.qtcompat import QtCore, QtWidgets


class ActionBar(QtWidgets.QWidget):
    """Action row with a read-only Check and a primary Export.

    Layout: ``[progress bar (stretch)] [Check] [Export ...]``
    """

    export_clicked = QtCore.Signal()
    check_clicked = QtCore.Signal()

    def __init__(self, button_label='Export', parent=None):
        super(ActionBar, self).__init__(parent)
        self._button_label = button_label
        self._build()

    def _build(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat('Idle')
        layout.addWidget(self.progress, 1)

        # Read-only validation - sits to the LEFT of the primary Export.
        self.check_btn = QtWidgets.QPushButton('Check')
        self.check_btn.setToolTip(
            'Validate the scene without exporting - reports missing '
            'descriptions, unpaired guide groups, and grooms that would '
            'export with 0 strands.'
        )
        self.check_btn.clicked.connect(self.check_clicked.emit)
        layout.addWidget(self.check_btn)

        self.export_btn = QtWidgets.QPushButton(self._button_label)
        self.export_btn.setObjectName('PrimaryAction')
        # Default tooltip - main_window.on_tab_changed overrides this
        # per active tab so the message stays in sync with the actual
        # action (Export Single Frame vs Export Animation).
        self.export_btn.setToolTip(
            'Run the export for every checked row in the Characters list.'
        )
        self.export_btn.clicked.connect(self.export_clicked.emit)
        layout.addWidget(self.export_btn)

    # ----- public API ------------------------------------------------------

    def set_progress(self, percent, message=''):
        self.progress.setValue(max(0, min(100, int(percent))))
        if message:
            self.progress.setFormat('{}  %p%'.format(message))
        else:
            self.progress.setFormat('%p%')

    def reset(self):
        self.progress.setValue(0)
        self.progress.setFormat('Idle')

    def set_enabled(self, enabled):
        self.export_btn.setEnabled(enabled)
        self.check_btn.setEnabled(enabled)

    def set_button_label(self, text):
        """Change the visible label of the Export button at runtime."""
        self.export_btn.setText(text)

    def set_last_export_dir(self, _path):
        """Kept as a no-op for back-compat - the Open Output button is gone."""
        pass
