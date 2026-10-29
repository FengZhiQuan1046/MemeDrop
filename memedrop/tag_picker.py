"""Editable, scoped multi-tag picker shared by the library editors."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from .library import parse_tags
from .search import matches_search


class TagChoices(QListWidget):
    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            self.setCurrentItem(item)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
            event.accept()
        else:
            super().mousePressEvent(event)


class TagPicker(QLineEdit):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.options = []
        self.popup = None
        self._toggling = False
        self.setPlaceholderText('下拉勾選標籤，或直接輸入新標籤')
        self.setToolTip('點右側箭頭可多選已有標籤；也可直接輸入，以逗號分隔多個標籤。')
        arrow = QPixmap(20, 20)
        arrow.fill(Qt.GlobalColor.transparent)
        painter = QPainter(arrow)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#b9abff'), 2))
        painter.drawLine(5, 7, 10, 12)
        painter.drawLine(10, 12, 15, 7)
        painter.end()
        action = QAction(QIcon(arrow), '選擇標籤', self)
        action.triggered.connect(self.show_popup)
        self.addAction(action, QLineEdit.ActionPosition.TrailingPosition)
        self.textChanged.connect(self.refresh_choices)

    def set_options(self, options):
        self.options = sorted(set(options), key=str.casefold)
        self.refresh_choices()

    def show_popup(self):
        if not self.isEnabled():
            return
        if self.popup is None:
            self.popup = QFrame(self, Qt.WindowType.Popup)
            self.popup.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QVBoxLayout(self.popup)
            self.query = QLineEdit()
            self.query.setPlaceholderText('搜尋或輸入新標籤')
            self.query.textChanged.connect(self.refresh_choices)
            self.query.returnPressed.connect(self.add_typed_tags)
            layout.addWidget(self.query)
            self.choices = TagChoices()
            self.choices.itemChanged.connect(self.toggle_choice)
            layout.addWidget(self.choices, 1)
            self.empty_hint = QLabel('此區塊尚無標籤，可在上方輸入並新增。')
            self.empty_hint.setWordWrap(True)
            layout.addWidget(self.empty_hint)
            buttons = QHBoxLayout()
            self.add_button = QPushButton('新增輸入的標籤')
            self.add_button.clicked.connect(self.add_typed_tags)
            buttons.addWidget(self.add_button)
            done = QPushButton('完成選擇')
            done.clicked.connect(self.popup.hide)
            buttons.addWidget(done)
            layout.addLayout(buttons)
        self.query.clear()
        self.refresh_choices()
        screen = self.screen().availableGeometry()
        width = min(max(self.width(), 340), screen.width())
        height = min(360, screen.height())
        self.popup.resize(width, height)
        below = self.mapToGlobal(QPoint(0, self.height()))
        y = below.y() if below.y() + height <= screen.bottom() + 1 else self.mapToGlobal(QPoint()).y() - height
        self.popup.move(max(screen.left(), min(below.x(), screen.right() - width + 1)),
                        max(screen.top(), y))
        self.popup.show()
        self.query.setFocus()

    def refresh_choices(self, *_):
        if self.popup is None or self._toggling:
            return
        selected = set(parse_tags(self.text()))
        query = self.query.text().strip()
        self.choices.blockSignals(True)
        self.choices.clear()
        for tag in sorted(set(self.options) | selected, key=str.casefold):
            if query and not matches_search(tag, query):
                continue
            item = QListWidgetItem(tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tag in selected else Qt.CheckState.Unchecked)
            self.choices.addItem(item)
        self.choices.blockSignals(False)
        self.empty_hint.setVisible(self.choices.count() == 0)
        self.empty_hint.setText('沒有符合的標籤，可新增上方輸入的內容。' if query else '此區塊尚無標籤，可在上方輸入並新增。')
        self.add_button.setEnabled(bool(parse_tags(query)))

    def toggle_choice(self, item):
        selected = set(parse_tags(self.text()))
        if item.checkState() == Qt.CheckState.Checked:
            selected.add(item.text())
        else:
            selected.discard(item.text())
        self._toggling = True
        try:
            self.setText(', '.join(sorted(selected, key=str.casefold)))
        finally:
            self._toggling = False

    def add_typed_tags(self):
        tags = parse_tags(self.query.text())
        if tags:
            selected = set(parse_tags(self.text())) | set(tags)
            self.setText(', '.join(sorted(selected, key=str.casefold)))
            self.query.clear()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Down:
            self.show_popup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        if self.popup is not None:
            self.popup.hide()
        super().hideEvent(event)
