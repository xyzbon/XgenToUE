"""Reusable read-only preview table for XgenToUE tabs.

The table shows two columns - **Name** and **Output** - and lets the user
multi-select rows. The selection is mirrored into Maya via the
:pyattr:`selection_changed` signal that carries the underlying node
paths. Status info (warning / error) is conveyed by tinting the row text;
tooltips on hover show the kind, detail, and status message.
"""

from xgentoue.gui import utils
from xgentoue.gui.qtcompat import QtCore, QtGui, QtWidgets


# Row-tint colours per status.
_TINTS = {
    utils.STATUS_OK: None,
    utils.STATUS_WARNING: QtGui.QColor('#e2c75a'),
    utils.STATUS_ERROR: QtGui.QColor('#e07070'),
}


class PreviewTable(QtWidgets.QWidget):
    """Header row (summary + Refresh) + a QTableWidget."""

    refresh_requested = QtCore.Signal()
    selection_changed = QtCore.Signal(list)  # list[str] of Maya node paths

    COLUMNS = ['Name', 'Output', 'Status']
    DEFAULT_MIN_VISIBLE_ROWS = 3

    def __init__(self, parent=None, show_header=True):
        super(PreviewTable, self).__init__(parent)
        self._empty_message = 'No items to preview.'
        self._row_paths = []  # parallel to table rows
        self._show_header = show_header
        self._build()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if self._show_header:
            header = QtWidgets.QHBoxLayout()
            self.summary_label = QtWidgets.QLabel('')
            self.summary_label.setObjectName('DetectInfo')
            header.addWidget(self.summary_label, 1)

            self.refresh_btn = QtWidgets.QToolButton()
            self.refresh_btn.setText('Refresh')
            self.refresh_btn.setToolTip('Re-scan the scene')
            # NOTE: clicked emits a 'checked' bool. If we connect directly
            # to ``self.refresh_requested.emit`` (a Signal() with no
            # args) PySide silently drops the call. Wrap in a lambda to
            # discard the bool arg.
            self.refresh_btn.clicked.connect(
                lambda _=False: self.refresh_requested.emit()
            )
            header.addWidget(self.refresh_btn)
            layout.addLayout(header)
        else:
            self.summary_label = None
            self.refresh_btn = None

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(True)
        # Name column gets the most fixed space; Status (last) absorbs
        # extra width via stretchLastSection.
        header_view.setSectionResizeMode(
            0, QtWidgets.QHeaderView.Interactive,
        )
        header_view.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents,
        )
        header_view.resizeSection(0, 200)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)
        self.set_minimum_visible_rows(self.DEFAULT_MIN_VISIBLE_ROWS)

    # ----- public API ------------------------------------------------------

    def set_empty_message(self, text):
        self._empty_message = text or ''

    def row_count(self):
        return self.table.rowCount()

    def set_minimum_visible_rows(self, n):
        """Size the table so at least ``n`` rows are visible by default."""
        row_h = self.table.verticalHeader().defaultSectionSize() or 24
        header_h = self.table.horizontalHeader().height() or 24
        min_h = int(n * row_h + header_h + 4)
        self.table.setMinimumHeight(min_h)

    def set_rows(self, rows):
        """Populate the table from a list of :class:`PreviewRow`."""
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        self._row_paths = [''] * len(rows)

        warnings = 0
        errors = 0
        for r, row in enumerate(rows):
            self._populate_row(r, row)
            self._row_paths[r] = row.path or ''
            if row.status == utils.STATUS_WARNING:
                warnings += 1
            elif row.status == utils.STATUS_ERROR:
                errors += 1

        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        self._update_summary(len(rows), warnings, errors)

    # ----- helpers ---------------------------------------------------------

    def _populate_row(self, r, row):
        composed = []
        if row.kind:
            composed.append(row.kind)
        if row.detail:
            composed.append(row.detail)
        if row.message:
            composed.append(row.message)
        tooltip = ' - '.join(composed) if composed else ''

        # The Status column shows the warning/error message inline so
        # users don't have to hover every row to see what's wrong.
        if row.status == utils.STATUS_OK:
            status_text = ''
        else:
            status_text = row.message or row.status

        tint = _TINTS.get(row.status)
        for col, value in enumerate((row.name, row.output, status_text)):
            item = QtWidgets.QTableWidgetItem(str(value))
            if tooltip:
                item.setToolTip(tooltip)
            if tint is not None:
                item.setForeground(tint)
            # Stash the row's Maya path on the first column item so
            # selection lookup works even after sorting.
            if col == 0:
                item.setData(QtCore.Qt.UserRole, row.path or '')
            self.table.setItem(r, col, item)

    def _update_summary(self, total, warnings, errors):
        if self.summary_label is None:
            return
        if total == 0:
            self.summary_label.setText(self._empty_message)
            return
        parts = ['{} item{}'.format(total, '' if total == 1 else 's')]
        if warnings:
            parts.append('{} warning{}'.format(
                warnings, '' if warnings == 1 else 's',
            ))
        if errors:
            parts.append('{} error{}'.format(
                errors, '' if errors == 1 else 's',
            ))
        self.summary_label.setText(' - '.join(parts))

    def _on_selection_changed(self):
        paths = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is None:
                continue
            path = item.data(QtCore.Qt.UserRole)
            if path:
                paths.append(path)
        self.selection_changed.emit(paths)
