"""Log panel — a read-only text widget fed by the ``xgentoue`` logger."""

import logging

from xgentoue.gui.qtcompat import QtCore, QtGui, QtWidgets


class _LogEmitter(QtCore.QObject):
    """Carries the Qt signal that the logging handler fires into the GUI."""

    record_emitted = QtCore.Signal(str, int)


class _QtLogHandler(logging.Handler):
    """Logging handler that forwards records to the GUI thread via a signal.

    Uses composition (rather than multiple inheritance with QObject) because
    PySide signals defined on a class that mixes ``logging.Handler`` and
    ``QObject`` do not initialise as descriptors properly.
    """

    def __init__(self, parent=None):
        super(_QtLogHandler, self).__init__()
        self.setLevel(logging.INFO)
        self.setFormatter(
            logging.Formatter('%(asctime)s  %(levelname)-7s  %(message)s', '%H:%M:%S')
        )
        self.emitter = _LogEmitter(parent)

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.emitter.record_emitted.emit(msg, record.levelno)


class LogPanel(QtWidgets.QWidget):
    """Read-only log view. Owns a logging.Handler attached to the
    ``xgentoue`` logger; coloured by level.
    """

    LEVEL_COLORS = {
        logging.DEBUG: '#888888',
        logging.INFO: '#cfcfcf',
        logging.WARNING: '#e2c75a',
        logging.ERROR: '#e07070',
        logging.CRITICAL: '#ff4444',
    }

    def __init__(self, parent=None):
        super(LogPanel, self).__init__(parent)
        self._build()
        self._install_handler()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel('Log'))
        header.addStretch(1)
        clear_btn = QtWidgets.QToolButton()
        clear_btn.setText('Clear')
        clear_btn.clicked.connect(lambda: self.text.clear())
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        layout.addWidget(self.text)

    def _install_handler(self):
        self.handler = _QtLogHandler(self)
        self.handler.emitter.record_emitted.connect(self._append)
        logger = logging.getLogger('xgentoue')
        logger.setLevel(logging.INFO)
        logger.addHandler(self.handler)

    def _append(self, message, level):
        color = self.LEVEL_COLORS.get(level, '#cfcfcf')
        # Use HTML so different levels are visually distinct.
        cursor = self.text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.text.setTextCursor(cursor)
        self.text.appendHtml(
            '<span style="color: {}; white-space: pre">{}</span>'.format(
                color,
                QtCore.Qt.escape(message) if hasattr(QtCore.Qt, 'escape') else _escape(message),
            )
        )

    def detach(self):
        """Remove our handler from the ``xgentoue`` logger."""
        try:
            logging.getLogger('xgentoue').removeHandler(self.handler)
        except Exception:
            pass


def _escape(text):
    return (
        text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
    )
