from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem)

from .library import parse_tags


class TagHierarchyDialog(QDialog):
    def __init__(self, library, section, parent=None, tag=''):
        super().__init__(parent)
        self.library, self.section = library, section
        self.setWindowTitle('管理標籤層級')
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        hint = QLabel('每個標籤可有多個父標籤、子標籤。選取下方關係可編輯；清空父／子欄位可解除關係。\n篩選父標籤會包含子孫標籤的表情；表情卡片只顯示最末端的已套用標籤。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.tag = QLineEdit()
        self.parents = QLineEdit()
        self.children = QLineEdit()
        for title, widget in [('標籤', self.tag), ('父標籤（逗號分隔）', self.parents), ('子標籤（逗號分隔）', self.children)]:
            form.addRow(title, widget)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        save = QPushButton('儲存此標籤的父子關係')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['父標籤', '子標籤'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(lambda row, col: self.load(self.table.item(row, col).text()))
        layout.addWidget(self.table, 1)
        close = QPushButton('完成')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.refresh()
        self.load(tag)

    def load(self, tag):
        edges = self.library.tag_edges(self.section)
        self.tag.setText(tag)
        self.parents.setText(', '.join(p for p, c in edges if c == tag))
        self.children.setText(', '.join(c for p, c in edges if p == tag))

    def refresh(self):
        edges = self.library.tag_edges(self.section)
        self.table.setRowCount(len(edges))
        for row, edge in enumerate(edges):
            for col, text in enumerate(edge):
                item = QTableWidgetItem(text)
                from PySide6.QtCore import Qt
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, col, item)

    def save(self):
        try:
            self.library.set_tag_relations(self.tag.text(), parse_tags(self.parents.text()),
                                           parse_tags(self.children.text()), self.section)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText('父子關係已儲存。')
        self.refresh()
