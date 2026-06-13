"""Source panel — guide-root, suffix, and detection feedback."""

from xgentoue.gui.qtcompat import QtCore, QtGui, QtWidgets
from xgentoue.gui import utils


def _make_x_icon(size=16, color=(220, 220, 220)):
    """Build a QIcon containing an X drawn with QPainter lines.

    Used as the trailing action icon on the Suffix combobox's
    lineEdit. We avoid ``QStyle.standardIcon`` and unicode glyphs
    because both render as nothing under some Maya stylesheets; two
    explicit drawLine calls always paint.
    """
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(*color))
    pen.setWidth(2)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(pen)
    m = 4  # margin from edge
    painter.drawLine(m, m, size - m, size - m)
    painter.drawLine(size - m, m, m, size - m)
    painter.end()
    return QtGui.QIcon(pix)


class SourcePanel(QtWidgets.QGroupBox):
    """Group box that lets the user pick the guide-root transform and the
    naming suffix on its children.

    Emits :pyattr:`changed` whenever the user edits any field, so the main
    window can persist the new state and refresh detection info.
    """

    changed = QtCore.Signal()
    detect_clicked = QtCore.Signal()

    # NOTE: trailing comma is required - ('_guides') is a STRING
    # in Python, not a tuple. Without the comma `list(self.KNOWN_SUFFIXES)`
    # iterates characters and seeds the dropdown with '_', 'g', 'u', ...
    KNOWN_SUFFIXES = ('_guides',)

    def __init__(self, parent=None):
        super(SourcePanel, self).__init__('Source', parent)
        self._build()

    def _build(self):
        layout = QtWidgets.QGridLayout(self)
        layout.setColumnStretch(1, 1)

        layout.addWidget(QtWidgets.QLabel('Guide Root'), 0, 0)
        self.guide_root_edit = QtWidgets.QLineEdit('guide_grp')
        self.guide_root_edit.editingFinished.connect(self._on_guide_root_changed)
        self.guide_root_edit.setMinimumHeight(34)
        self.guide_root_edit.setToolTip(
            'Name of the transform that holds your XGen guide groups. '
            'Usually "guide_grp" in asset files; for shot files the '
            'character is referenced so the tool finds every matching '
            'transform automatically (e.g. "charB:guide_grp", '
            '"charA:guide_grp").'
        )
        layout.addWidget(self.guide_root_edit, 0, 1)

        detect_btn = QtWidgets.QPushButton('Detect')
        detect_btn.setToolTip('Auto-detect the suffix used by children of the guide root')
        detect_btn.clicked.connect(self.detect_suffix)
        layout.addWidget(detect_btn, 0, 2)

        layout.addWidget(QtWidgets.QLabel('Suffix'), 1, 0)
        self.suffix_combo = QtWidgets.QComboBox()
        self.suffix_combo.setEditable(True)
        # We auto-register typed values ourselves via editingFinished,
        # so disable Qt's built-in insert policy to avoid duplicate
        # / inconsistent behavior between Enter and focus-loss.
        self.suffix_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.suffix_combo.addItems(list(self.KNOWN_SUFFIXES))
        self.suffix_combo.setCurrentText(self.KNOWN_SUFFIXES[0])
        self.suffix_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        # editingFinished fires on both Enter and focus loss inside the
        # combobox lineEdit - the right moment to commit a freshly-
        # typed suffix into the dropdown so it joins the history.
        self.suffix_combo.lineEdit().editingFinished.connect(
            self._on_suffix_edit_finished,
        )
        self.suffix_combo.setMinimumHeight(34)
        self.suffix_combo.setToolTip(
            'Pick a known suffix or type a custom one. Click the ✕ '
            'button to the right to pick which custom suffix to remove '
            'from history. The built-in entries ({}) are protected.'.format(
                ', '.join(self.KNOWN_SUFFIXES),
            )
        )
        # Sibling button - delegate / lineEdit-action approaches were
        # both invisible under Maya's stylesheet. A real QToolButton
        # is a concrete widget and always renders.
        self.suffix_remove_btn = QtWidgets.QToolButton()
        self.suffix_remove_btn.setText(u'✕')
        self.suffix_remove_btn.setToolTip(
            'Pick a custom suffix to remove from history.'
        )
        self.suffix_remove_btn.setMinimumHeight(34)
        self.suffix_remove_btn.setAutoRaise(False)
        # Always clickable - the popup tells the user when there's
        # nothing to remove instead of leaving them stuck with a
        # greyed-out button.
        self.suffix_remove_btn.clicked.connect(self._show_remove_menu)
        # Keep the keyboard shortcut (Delete / Backspace) in the
        # dropdown for users who prefer it.
        self.suffix_combo.view().installEventFilter(self)
        layout.addWidget(self.suffix_combo, 1, 1)
        layout.addWidget(self.suffix_remove_btn, 1, 2)

        self.info_label = QtWidgets.QLabel('')
        self.info_label.setObjectName('DetectInfo')
        layout.addWidget(self.info_label, 2, 0, 1, 3)

    # ----- public API ------------------------------------------------------

    def guide_root(self):
        return self.guide_root_edit.text().strip()

    def suffix(self):
        return self.suffix_combo.currentText()

    def set_guide_root(self, value):
        if value:
            self.guide_root_edit.setText(value)

    def set_suffix(self, value):
        if not value:
            return
        # If the user previously typed a custom suffix (not in
        # KNOWN_SUFFIXES), add it to the dropdown so it's selectable
        # next time too - not just sitting in the line edit.
        if value not in self._combo_items():
            self.suffix_combo.addItem(value)
        self.suffix_combo.setCurrentText(value)

    def custom_suffixes(self):
        """Return every dropdown entry the user added on top of
        :attr:`KNOWN_SUFFIXES`.

        The main window persists this list to QSettings so suffix
        history survives across sessions.
        """
        return [
            item for item in self._combo_items()
            if item not in self.KNOWN_SUFFIXES
        ]

    def set_custom_suffixes(self, values):
        """Append previously-saved custom suffixes to the dropdown.

        Called once during settings load BEFORE :meth:`set_suffix`, so
        the restored suffix lands on a fully-populated dropdown
        instead of being inserted as a brand-new entry. Built-in
        entries and already-present items are skipped.
        """
        existing = set(self._combo_items())
        for v in values or []:
            v = (v or '').strip()
            if v and v not in existing and v not in self.KNOWN_SUFFIXES:
                self.suffix_combo.addItem(v)
                existing.add(v)

    def _combo_items(self):
        return [
            self.suffix_combo.itemText(i)
            for i in range(self.suffix_combo.count())
        ]

    def detect_suffix(self):
        """Inspect the scene and update the suffix combo + info label."""
        root = self.guide_root()
        guess = utils.detect_suffix(root, self.KNOWN_SUFFIXES)
        roots = utils.find_guide_grps(root) if root else []
        if guess:
            self.suffix_combo.setCurrentText(guess)
            self.info_label.setText(
                'Detected {} guide group(s); suffix "{}".'.format(len(roots), guess)
            )
        elif roots:
            self.info_label.setText(
                '{} guide group(s) found, but no recognised suffix.'.format(len(roots))
            )
        else:
            self.info_label.setText('No guide groups found for "{}".'.format(root))
        self.changed.emit()
        # Fires AFTER `changed` so subscribers see a re-scanned scene
        # before they react to the explicit Detect click (e.g. reset
        # per-row Dir fields to <scene>/xgen).
        self.detect_clicked.emit()

    # ----- internal --------------------------------------------------------

    def _on_guide_root_changed(self):
        self.detect_suffix()

    def _remove_suffix_row(self, row):
        """Remove a custom suffix from the dropdown by row index.

        Built-in entries (``KNOWN_SUFFIXES``) are protected. If the
        removed row was the active selection, the combo snaps back to
        the first built-in entry so the field never goes blank.
        """
        item_text = self.suffix_combo.itemText(row)
        if not item_text or item_text in self.KNOWN_SUFFIXES:
            return
        was_current = self.suffix_combo.currentText() == item_text
        self.suffix_combo.removeItem(row)
        if was_current and self.KNOWN_SUFFIXES:
            self.suffix_combo.setCurrentText(self.KNOWN_SUFFIXES[0])
        self.changed.emit()

    def _show_remove_menu(self):
        """Pop a menu listing every custom suffix; choosing one drops
        it from the dropdown.

        This frees the user from having to select a suffix first and
        then click remove - they can prune any custom entry from one
        click on the X button.
        """
        customs = [
            item for item in self._combo_items()
            if item not in self.KNOWN_SUFFIXES
        ]
        anchor = self.suffix_remove_btn.mapToGlobal(
            QtCore.QPoint(0, self.suffix_remove_btn.height()),
        )
        if not customs:
            QtWidgets.QToolTip.showText(
                anchor, 'No custom suffixes to remove.',
                self.suffix_remove_btn,
            )
            return
        menu = QtWidgets.QMenu(self)
        for suffix_text in customs:
            action = menu.addAction(u'Remove "{}"'.format(suffix_text))
            action.triggered.connect(
                lambda _checked=False, t=suffix_text: self._remove_by_text(t)
            )
        menu.exec_(anchor)

    def _remove_by_text(self, text):
        row = self.suffix_combo.findText(text)
        if row >= 0:
            self._remove_suffix_row(row)

    def _on_suffix_edit_finished(self):
        """Auto-register a freshly-typed suffix into the dropdown.

        Fires on Enter or focus-loss inside the combobox lineEdit.
        The new value joins the history so the user can re-select it
        without retyping; ``changed`` emits so the main window can
        persist the updated history to QSettings.
        """
        typed = self.suffix_combo.currentText().strip()
        if not typed or typed in self._combo_items():
            return
        self.suffix_combo.addItem(typed)
        self.changed.emit()

    def eventFilter(self, obj, event):
        # Allow the user to remove custom suffixes from the dropdown by
        # selecting one and pressing Delete / Backspace. Built-in
        # entries from KNOWN_SUFFIXES are never removed.
        if obj is self.suffix_combo.view() and event.type() == QtCore.QEvent.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                index = self.suffix_combo.view().currentIndex()
                if index.isValid():
                    row = index.row()
                    item_text = self.suffix_combo.itemText(row)
                    if item_text and item_text not in self.KNOWN_SUFFIXES:
                        self._remove_suffix_row(row)
                        return True  # consume the event
        return super(SourcePanel, self).eventFilter(obj, event)
