from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QMimeData, QSize, Qt,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QDrag, QIcon, QImage,
                           QImageReader, QKeySequence, QMovie, QPainter, QPixmap, QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSlider, QSplitter, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import desktop as windows
from .library import EXTENSIONS, Library, Meme, parse_tags

STYLE = '''
QWidget { background: #11131b; color: #e9eaf2; font-family: "Microsoft JhengHei UI", "Segoe UI"; font-size: 13px; }
QMainWindow { background: #11131b; }
QLabel#brand { font-size: 24px; font-weight: 800; color: #b9abff; }
QLabel#heading { font-size: 23px; font-weight: 700; }
QLabel#muted { color: #9095ac; }
QLabel#preview { background: #191c28; border: 1px solid #2d3145; border-radius: 14px; }
QLineEdit, QComboBox { background: #1c2030; border: 1px solid #34394e; border-radius: 8px; padding: 9px; selection-background-color: #7460d9; }
QLineEdit:focus { border-color: #a595ff; }
QPushButton { background: #252a3b; border: 1px solid #343a50; padding: 9px 13px; border-radius: 8px; }
QPushButton:hover { background: #343b53; border-color: #8070ca; }
QPushButton:disabled { color: #686f85; background: #1c202d; }
QPushButton#primary { background: #9980ff; color: #12121a; font-weight: 700; border: none; }
QPushButton#primary:hover { background: #b19dff; }
QPushButton#primary:disabled { background: #353044; color: #797285; }
QPushButton:checked { background: #40335f; color: #cfc2ff; border-color: #8e76d4; }
QListWidget { border: none; background: transparent; outline: none; }
QListWidget::item { padding: 8px; border-radius: 9px; }
QListWidget::item:selected { background: #37304f; color: #e4dcff; }
QListWidget::item:hover { background: #262b3e; }
QListWidget#grid::item { background: #1b1f2d; border: 1px solid #2a3043; }
QListWidget#grid::item:selected { background: #38304e; border: 2px solid #ae95ff; }
QFrame#divider { background: #2c3041; max-height: 1px; }
QMenu { background: #202535; border: 1px solid #464d64; padding: 5px; }
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #4d4071; }
QToolTip { background: #252a3b; color: #eeeeff; border: 1px solid #635487; padding: 6px; }
QSplitter::handle { background: #292e40; width: 1px; }
QScrollBar:vertical { background: #171b27; width: 9px; }
QScrollBar::handle:vertical { background: #464d66; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { color: #9299b1; border-top: 1px solid #292e40; }
'''


def icon_pixmap(text: str, color: str = '#a991ff', width: int = 144, height: int = 102) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor('#222739'))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(color))
    font = painter.font()
    font.setPixelSize(25)
    font.setBold(True)
    painter.setFont(font)
    while painter.fontMetrics().horizontalAdvance(text) > width - 16 and font.pixelSize() > 9:
        font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
    text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width - 16)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def clipboard_data(path: Path, kind: str, mode: str) -> QMimeData:
    if not path.is_file():
        raise FileNotFoundError('檔案不存在，請重新整理素材庫。')
    data = QMimeData()
    use_image = mode == 'image' or (mode == 'auto' and kind == 'image')
    if use_image:
        if kind == 'video':
            raise ValueError('影片請使用「自動」或「原始檔案」模式。')
        image = QImage(str(path))
        if image.isNull():
            raise ValueError('無法解碼圖片，請改用「原始檔案」模式。')
        data.setImageData(image)
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        data.setData('image/png', encoded)
    else:
        # Qt maps file URLs to native Windows CF_HDROP, preserving GIF/video bytes.
        data.setUrls([QUrl.fromLocalFile(str(path))])
    return data


class MediaGrid(QListWidget):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('grid')
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(144, 102))
        self.setGridSize(QSize(174, 166))
        self.setSpacing(7)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.filesDropped.emit([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def startDrag(self, actions):
        data = self.selection_mime_data()
        if data is not None:
            drag = QDrag(self)
            drag.setMimeData(data)
            drag.exec(Qt.DropAction.CopyAction)

    def selection_mime_data(self):
        selected = self.selectedItems()
        if not selected:
            return None
        text_items = [item.data(Qt.ItemDataRole.UserRole) for item in selected
                      if item.data(Qt.ItemDataRole.UserRole).kind == 'kaomoji']
        data = QMimeData()
        if text_items:
            if len(text_items) != len(selected):
                return None  # Mixed text/file drags cannot preserve both types reliably.
            data.setText('\n'.join(m.content for m in text_items))
        else:
            data.setUrls([QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole + 1)) for item in selected])
        return data


class MainWindow(QMainWindow):
    def __init__(self, library: Library, native: bool = True):
        super().__init__()
        self.library = library
        self.native = native and windows.AVAILABLE
        self.target = 0
        self.target_locked = False
        self.hotkey_registered = False
        self.busy = False
        self.movie = None
        self.collection = 'all'
        self.active_tag = None
        self.current_meme = None
        self.thumb_queue = []
        self.thumb_cache = {}
        self.setWindowTitle('MemeDrop · 隨手傳遞你的情緒')
        self.setWindowIcon(QIcon(icon_pixmap('M', width=64, height=64)))
        self.resize(1220, 780)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.build_ui()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.errorOccurred.connect(lambda error, message: self.statusBar().showMessage('影片預覽失敗：' + message, 10000))
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(lambda duration: self.timeline.setRange(0, duration))
        self.timeline.sliderMoved.connect(self.player.setPosition)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setInterval(12)
        self.thumb_timer.timeout.connect(self.load_thumbnails)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(130)
        self.filter_timer.timeout.connect(self.refresh_items)
        self.search.textChanged.connect(lambda: self.filter_timer.start())
        self.foreground_timer = QTimer(self)
        self.foreground_timer.setInterval(120)
        self.foreground_timer.timeout.connect(self.track_target)
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(5000)
        self.scan_timer.timeout.connect(self.auto_scan)
        self.setup_tray()
        self.setup_shortcuts()
        self.rescan()
        if self.native:
            self.register_hotkey()
            self.foreground_timer.start()
            self.scan_timer.start()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 12)
        header = QHBoxLayout()
        brand = QLabel('MemeDrop')
        brand.setObjectName('brand')
        header.addWidget(brand)
        subtitle = QLabel('表情到位，心情就位。')
        subtitle.setObjectName('muted')
        header.addWidget(subtitle)
        header.addStretch()
        self.hotkey_label = QLabel()
        self.hotkey_label.setText('Ctrl + Alt + ' + self.library.setting('hotkey', 'M'))
        self.hotkey_label.setObjectName('muted')
        header.addWidget(self.hotkey_label)
        settings = QPushButton('設定')
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)
        outer.addLayout(header)
        outer.addSpacing(12)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)

        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 4, 18, 0)
        label = QLabel('我的素材庫')
        label.setObjectName('muted')
        side.addWidget(label)
        self.collections = QListWidget()
        self.collections.setFixedHeight(212)
        for title, key in [(':: 全部表情', 'all'), ('☆  我的收藏', 'favorites'), ('~  最近使用', 'recent'), ('#  尚未標籤', 'untagged'), (':) 顏文字', 'kaomoji')]:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.collections.addItem(item)
        self.collections.setCurrentRow(0)
        self.collections.currentItemChanged.connect(self.select_collection)
        side.addWidget(self.collections)
        tag_header = QHBoxLayout()
        tag_label = QLabel('標籤篩選')
        tag_label.setObjectName('muted')
        tag_header.addWidget(tag_label)
        clear = QPushButton('清除')
        clear.setFixedWidth(60)
        clear.clicked.connect(self.clear_tag)
        tag_header.addWidget(clear)
        side.addLayout(tag_header)
        self.tags_list = QListWidget()
        self.tags_list.itemClicked.connect(self.select_tag)
        self.tags_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tags_list.customContextMenuRequested.connect(self.tag_menu)
        side.addWidget(self.tags_list, 1)
        hint = QLabel('右鍵標籤可重新命名或移除\nCtrl / Shift 可多選素材')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        side.addWidget(hint)
        folder = QPushButton('開啟 memes 資料夾')
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.media_dir))))
        side.addWidget(folder)
        splitter.addWidget(sidebar)

        center = QWidget()
        content = QVBoxLayout(center)
        content.setContentsMargins(18, 0, 18, 0)
        row = QHBoxLayout()
        self.heading = QLabel('全部表情')
        self.heading.setObjectName('heading')
        row.addWidget(self.heading)
        row.addStretch()
        add_text = QPushButton('＋ 顏文字')
        add_text.clicked.connect(lambda: self.edit_kaomoji())
        row.addWidget(add_text)
        add = QPushButton('＋ 匯入素材')
        add.setObjectName('primary')
        add.clicked.connect(self.import_dialog)
        row.addWidget(add)
        content.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜尋檔名、顏文字或標籤…    Ctrl+F')
        self.search.setClearButtonEnabled(True)
        content.addWidget(self.search)
        filters = QHBoxLayout()
        self.kind_combo = QComboBox()
        for title, key in [('所有格式', 'all'), ('圖片', 'image'), ('GIF 動圖', 'animation'), ('影片', 'video'), ('顏文字', 'kaomoji')]:
            self.kind_combo.addItem(title, key)
        self.kind_combo.currentIndexChanged.connect(self.refresh_items)
        filters.addWidget(self.kind_combo)
        self.sort_combo = QComboBox()
        for title, key in [('最新加入', 'newest'), ('名稱排序', 'name'), ('最常使用', 'used')]:
            self.sort_combo.addItem(title, key)
        self.sort_combo.currentIndexChanged.connect(self.refresh_items)
        filters.addWidget(self.sort_combo)
        filters.addStretch()
        refresh = QPushButton('重新整理')
        refresh.clicked.connect(self.rescan)
        filters.addWidget(refresh)
        content.addLayout(filters)
        self.count_label = QLabel()
        self.count_label.setObjectName('muted')
        content.addWidget(self.count_label)
        self.grid = MediaGrid()
        self.grid.itemSelectionChanged.connect(self.selection_changed)
        self.grid.itemDoubleClicked.connect(lambda item: self.send_selected())
        self.grid.filesDropped.connect(self.import_paths)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.media_menu)
        self.grid_stack = QStackedWidget()
        self.grid_stack.addWidget(self.grid)
        self.empty_label = QLabel('')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setObjectName('muted')
        self.grid_stack.addWidget(self.empty_label)
        content.addWidget(self.grid_stack, 1)
        splitter.addWidget(center)

        panel = QWidget()
        panel.setMinimumWidth(260)
        details = QVBoxLayout(panel)
        details.setContentsMargins(18, 4, 0, 0)
        preview_header = QLabel('素材預覽')
        preview_header.setObjectName('muted')
        details.addWidget(preview_header)
        self.preview = QLabel('選一張表情，開始吧。')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setObjectName('preview')
        self.preview.setMinimumSize(230, 210)
        self.video = QVideoWidget()
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview)
        self.preview_stack.addWidget(self.video)
        self.preview_stack.setMinimumHeight(210)
        self.preview_stack.setMaximumHeight(280)
        details.addWidget(self.preview_stack)
        self.video_controls = QWidget()
        controls = QHBoxLayout(self.video_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        play = QPushButton('播放 / 暫停')
        play.clicked.connect(self.toggle_play)
        controls.addWidget(play)
        mute = QPushButton('靜音')
        mute.setCheckable(True)
        mute.setChecked(True)
        mute.toggled.connect(lambda checked: self.audio.setMuted(checked))
        controls.addWidget(mute)
        details.addWidget(self.video_controls)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        details.addWidget(self.timeline)
        self.video_controls.hide()
        self.timeline.hide()
        self.name_label = QLabel('尚未選取')
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setWordWrap(True)
        details.addWidget(self.name_label)
        self.meta_label = QLabel('支援圖片、GIF 與影片')
        self.meta_label.setObjectName('muted')
        self.meta_label.setWordWrap(True)
        details.addWidget(self.meta_label)
        self.favorite_button = QPushButton('☆ 加入收藏')
        self.favorite_button.clicked.connect(self.toggle_favorite)
        details.addWidget(self.favorite_button)
        details.addSpacing(10)
        details.addWidget(QLabel('標籤'))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText('例如：開心, 貓咪, 上班')
        details.addWidget(self.tag_edit)
        self.tag_mode = QComboBox()
        self.tag_mode.addItem('取代選取素材的標籤', False)
        self.tag_mode.addItem('追加標籤至選取素材', True)
        details.addWidget(self.tag_mode)
        self.save_tags_button = QPushButton('儲存標籤')
        self.save_tags_button.clicked.connect(self.save_tags)
        details.addWidget(self.save_tags_button)
        details.addStretch()
        self.target_label = QLabel('先在聊天輸入框按 Ctrl+Alt+M')
        self.target_label.setWordWrap(True)
        self.target_label.setObjectName('muted')
        details.addWidget(self.target_label)
        self.paste_mode = QComboBox()
        for title, key in [('自動 · 圖片 / 原檔', 'auto'), ('原始檔案 · 保留 GIF / 影片', 'file'), ('圖片 · 動圖僅貼上單幀', 'image')]:
            self.paste_mode.addItem(title, key)
        self.paste_mode.setCurrentIndex(max(0, self.paste_mode.findData(self.library.setting('paste_mode', 'auto'))))
        self.paste_mode.currentIndexChanged.connect(lambda: self.library.set_setting('paste_mode', self.paste_mode.currentData()))
        details.addWidget(self.paste_mode)
        self.send_button = QPushButton('貼到原視窗    Enter')
        self.send_button.setObjectName('primary')
        self.send_button.clicked.connect(self.send_selected)
        details.addWidget(self.send_button)
        self.copy_button = QPushButton('只複製    Ctrl+C')
        self.copy_button.clicked.connect(self.copy_selected)
        details.addWidget(self.copy_button)
        tip = QLabel('雙擊快速貼上 · 拖曳可傳原檔\n貼上後，請在聊天軟體確認發送。')
        tip.setObjectName('muted')
        tip.setWordWrap(True)
        details.addWidget(tip)
        splitter.addWidget(panel)
        splitter.setSizes([185, 705, 285])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        self.statusBar().showMessage('準備就緒')

    def setup_shortcuts(self):
        for sequence, callback in [('Ctrl+F', self.search.setFocus), ('Escape', self.hide_picker),
                                    ('F5', self.rescan)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        for sequence in ('Return', 'Enter'):
            shortcut = QShortcut(QKeySequence(sequence), self.grid)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self.send_selected)
        copy = QShortcut(QKeySequence('Ctrl+C'), self.grid)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy.activated.connect(self.copy_selected)
        self.search.returnPressed.connect(self.send_first)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('MemeDrop')
        menu = QMenu(self)
        menu.addAction('開啟 MemeDrop', self.show_picker)
        menu.addAction('重新整理素材', self.rescan)
        menu.addSeparator()
        menu.addAction('結束', QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_picker() if reason in
            (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        if self.native:
            self.tray.show()

    def register_hotkey(self):
        key = self.library.setting('hotkey', 'M')
        self.hotkey_label.setText(f'Ctrl + Alt + {key}')
        self.hotkey_registered = windows.register_hotkey(int(self.winId()), key)
        if not self.hotkey_registered:
            self.statusBar().showMessage('快捷鍵已被其他程式佔用，請在設定中更換；仍可使用系統匣開啟。')
            self.hotkey_label.setText(f'Ctrl + Alt + {key}（註冊失敗）')

    def nativeEvent(self, event_type, message):
        if self.native:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == windows.WM_HOTKEY and msg.wParam == windows.HOTKEY_ID:
                if self.isVisible() and windows.foreground() == int(self.winId()):
                    self.hide_picker()
                else:
                    hwnd = windows.foreground()
                    if windows.external_window(hwnd):
                        self.target = hwnd
                    self.show_picker()
                return True, 0
        return super().nativeEvent(event_type, message)

    def track_target(self):
        hwnd = windows.foreground()
        # Freeze the destination while the picker is in use, including its dialogs.
        if not self.target_locked and windows.external_window(hwnd):
            self.target = hwnd

    def show_picker(self):
        if self.busy:
            return
        self.target_locked = True
        self.update_target_label()
        self.rescan()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self.search.selectAll()

    def hide_picker(self):
        self.stop_preview()
        self.hide()
        self.target_locked = False

    def update_target_label(self):
        title = windows.window_title(self.target) if self.target else ''
        self.target_label.setText('貼上目標：' + title[:55] if title else
            '先點聊天輸入框，再按 ' + self.hotkey_label.text())
        self.target_label.setToolTip(title)

    def rescan(self):
        try:
            self.library.scan()
            self.refresh_tags()
            self.refresh_items()
            self.snapshot = self.file_snapshot()
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))

    def file_snapshot(self):
        return [(m.relative_path, self.library.path(m).stat().st_mtime_ns,
                 self.library.path(m).stat().st_size) for m in self.library.items()
                if m.kind != 'kaomoji' and self.library.path(m).is_file()]

    def auto_scan(self):
        if not self.isVisible() or self.busy:
            return
        try:
            self.library.scan()
            snapshot = self.file_snapshot()
            if snapshot != self.snapshot:
                self.snapshot = snapshot
                self.refresh_tags()
                self.refresh_items()
        except OSError:
            logging.exception('Automatic scan failed')

    def select_collection(self, item, previous=None):
        if item:
            self.collection = item.data(Qt.ItemDataRole.UserRole)
            self.heading.setText(item.text()[3:])
            if self.collection == 'kaomoji':
                self.kind_combo.blockSignals(True)
                self.kind_combo.setCurrentIndex(0)
                self.kind_combo.blockSignals(False)
            self.refresh_items()

    def select_tag(self, item):
        self.active_tag = item.data(Qt.ItemDataRole.UserRole)
        self.refresh_items()

    def clear_tag(self):
        self.active_tag = None
        self.tags_list.clearSelection()
        self.refresh_items()

    def refresh_tags(self):
        self.tags_list.clear()
        available = set()
        for tag, count in self.library.tag_counts():
            available.add(tag)
            item = QListWidgetItem(f'# {tag}   {count}')
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.tags_list.addItem(item)
            if tag == self.active_tag:
                item.setSelected(True)
        if self.active_tag not in available:
            self.active_tag = None

    def refresh_items(self, *args):
        if not hasattr(self, 'grid'):
            return
        selected = {m.id for m in self.selected_memes()}
        self.stop_preview()
        items = self.library.items(self.search.text(), self.active_tag, self.kind_combo.currentData(),
                                   self.collection, self.sort_combo.currentData())
        self.grid.blockSignals(True)
        self.grid.clear()
        self.thumb_queue = []
        for meme in items:
            kind = {'image': '圖片', 'animation': 'GIF', 'video': '影片', 'kaomoji': '顏文字'}[meme.kind]
            item = QListWidgetItem(('★ ' if meme.favorite else '') + meme.name + '\n' + kind)
            item.setData(Qt.ItemDataRole.UserRole, meme)
            item.setToolTip((meme.content if meme.kind == 'kaomoji' else meme.relative_path) + '\n' + ' · '.join(meme.tags))
            if meme.kind == 'kaomoji':
                cache_key = ('kaomoji', meme.content)
                if cache_key not in self.thumb_cache:
                    self.thumb_cache[cache_key] = icon_pixmap(meme.content, '#d7cbff')
                item.setIcon(QIcon(self.thumb_cache[cache_key]))
            else:
                item.setData(Qt.ItemDataRole.UserRole + 1, str(self.library.path(meme)))
                item.setIcon(QIcon(icon_pixmap('▶' if meme.kind == 'video' else 'GIF' if meme.kind == 'animation' else '▧')))
            self.grid.addItem(item)
            if meme.id in selected:
                item.setSelected(True)
            if meme.kind in ('image', 'animation'):
                self.thumb_queue.append(item)
        self.grid.blockSignals(False)
        self.count_label.setText(f'{len(items)} 個素材' + (f'  ·  #{self.active_tag}' if self.active_tag else ''))
        self.grid_stack.setCurrentIndex(0 if items else 1)
        total = self.library.db.execute('SELECT COUNT(*) FROM media WHERE available = 1').fetchone()[0]
        self.empty_label.setText('你的表情庫，等你填滿。\n\n把圖片、GIF 或影片拖進視窗，\n或點「＋ 匯入素材」。\n\n也可以直接放進 memes 資料夾。' if not total else
                                 '沒有符合的素材\n\n試試其他關鍵字、格式或標籤。')
        self.selection_changed()
        if self.thumb_queue:
            self.thumb_timer.start()

    def load_thumbnails(self):
        for _ in range(min(8, len(self.thumb_queue))):
            item = self.thumb_queue.pop(0)
            path = Path(item.data(Qt.ItemDataRole.UserRole + 1))
            try:
                cache_key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
                pixmap = self.thumb_cache.get(cache_key)
                if pixmap is None:
                    reader = QImageReader(str(path))
                    reader.setAutoTransform(True)
                    size = reader.size()
                    if size.isValid():
                        reader.setScaledSize(size.scaled(144, 102, Qt.AspectRatioMode.KeepAspectRatio))
                    pixmap = QPixmap.fromImage(reader.read())
                    if pixmap.isNull():
                        pixmap = icon_pixmap('?', '#dbaf7c')
                    if len(self.thumb_cache) > 800:
                        self.thumb_cache.clear()
                    self.thumb_cache[cache_key] = pixmap
                item.setIcon(QIcon(pixmap))
            except OSError:
                pass
        if not self.thumb_queue:
            self.thumb_timer.stop()

    def selected_memes(self) -> list[Meme]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.grid.selectedItems()]

    def stop_preview(self):
        if hasattr(self, 'player'):
            self.player.stop()
            self.player.setSource(QUrl())
        if self.movie:
            self.preview.setMovie(None)
            self.movie.stop()
            self.movie.setFileName('')
            self.movie.deleteLater()
            self.movie = None

    def selection_changed(self):
        self.stop_preview()
        memes = self.selected_memes()
        self.current_meme = memes[0] if len(memes) == 1 else None
        for widget in (self.favorite_button, self.save_tags_button, self.tag_edit, self.tag_mode):
            widget.setEnabled(bool(memes))
        for widget in (self.send_button, self.copy_button):
            widget.setEnabled(len(memes) == 1 and not self.busy)
        self.video_controls.hide()
        self.timeline.hide()
        self.preview_stack.setCurrentIndex(0)
        self.preview.clear()
        self.preview.setStyleSheet('')
        self.preview.setToolTip('')
        self.paste_mode.setEnabled(self.current_meme is not None and self.current_meme.kind != 'kaomoji')
        self.paste_mode.setToolTip('顏文字固定使用純文字貼上，不受媒體模式影響。' if self.current_meme and self.current_meme.kind == 'kaomoji' else '')
        self.tag_edit.clear()
        if not memes:
            self.preview.setText('選一張表情，開始吧。')
            self.name_label.setText('尚未選取')
            self.meta_label.setText('支援圖片、GIF 與影片')
            return
        all_favorite = all(m.favorite for m in memes)
        self.favorite_button.setText('★ 移除收藏' if all_favorite else '☆ 加入收藏')
        common = set(memes[0].tags)
        for meme in memes[1:]:
            common.intersection_update(meme.tags)
        self.tag_edit.setText(', '.join(sorted(common)))
        self.tag_mode.setCurrentIndex(1 if len(memes) > 1 else 0)
        if len(memes) > 1:
            self.preview.setText(f'已選取 {len(memes)} 個素材')
            self.name_label.setText('批次標籤與收藏')
            self.meta_label.setText('可追加標籤；選「取代」會覆蓋每個素材的標籤。')
            return
        meme = memes[0]
        self.name_label.setText(meme.name)
        if meme.kind == 'kaomoji':
            self.preview.setStyleSheet('font-size: 22px; color: #d7cbff; padding: 8px;')
            self.preview.setText(meme.content)
            self.preview.setToolTip(meme.content)
            self.meta_label.setText(f'顏文字 · {len(meme.content)} 字元 · 純文字貼上')
            self.meta_label.setToolTip('右鍵素材可編輯內容或移除。')
            return
        path = self.library.path(meme)
        try:
            size = path.stat().st_size / 1024
        except OSError:
            self.preview.setText('檔案不存在，請重新整理')
            return
        self.meta_label.setText(f'{path.suffix[1:].upper()} · {size / 1024:.1f} MB' if size > 1024 else f'{path.suffix[1:].upper()} · {size:.0f} KB')
        self.meta_label.setToolTip(meme.relative_path)
        if meme.kind == 'video':
            self.preview_stack.setCurrentIndex(1)
            self.video_controls.show()
            self.timeline.show()
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()
        else:
            reader = QImageReader(str(path))
            if reader.supportsAnimation():
                self.movie = QMovie(str(path))
                size = reader.size()
                if size.isValid():
                    self.movie.setScaledSize(size.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio))
                self.preview.setMovie(self.movie)
                self.movie.start()
            else:
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio))
                pixmap = QPixmap.fromImage(reader.read())
                if pixmap.isNull():
                    self.preview.setText('無法預覽，可嘗試以原始檔案貼上')
                else:
                    self.preview.setPixmap(pixmap)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_position(self, position):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(position)

    def save_tags(self):
        ids = [m.id for m in self.selected_memes()]
        self.library.set_tags(ids, parse_tags(self.tag_edit.text()), self.tag_mode.currentData())
        self.refresh_tags()
        self.refresh_items()
        self.statusBar().showMessage(f'已更新 {len(ids)} 個素材的標籤', 4000)

    def toggle_favorite(self):
        memes = self.selected_memes()
        self.library.set_favorite([m.id for m in memes], not all(m.favorite for m in memes))
        self.refresh_items()

    def tag_menu(self, pos):
        item = self.tags_list.itemAt(pos)
        if not item:
            return
        tag = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename = menu.addAction('重新命名 / 合併標籤')
        delete = menu.addAction('從所有素材移除此標籤')
        action = menu.exec(self.tags_list.mapToGlobal(pos))
        if action == rename:
            name, ok = QInputDialog.getText(self, '重新命名標籤', '新標籤名稱（已存在則合併）：', text=tag)
            if ok and name.strip():
                parsed = parse_tags(name)
                if len(parsed) != 1:
                    self.show_error('請輸入一個標籤名稱。')
                    return
                self.library.rename_tag(tag, parsed[0])
                if self.active_tag == tag:
                    self.active_tag = parsed[0]
        elif action == delete:
            if QMessageBox.question(self, '移除標籤', f'從所有素材移除「{tag}」？素材檔案會保留。') == QMessageBox.StandardButton.Yes:
                self.library.delete_tag(tag)
        self.refresh_tags()
        self.refresh_items()

    def media_menu(self, pos):
        if not self.grid.selectedItems():
            return
        menu = QMenu(self)
        if len(self.selected_memes()) == 1:
            menu.addAction('貼到原視窗', self.send_selected)
            menu.addAction('只複製', self.copy_selected)
            meme = self.selected_memes()[0]
            if meme.kind == 'kaomoji':
                menu.addAction('編輯顏文字', lambda: self.edit_kaomoji(meme))
                menu.addAction('移除顏文字', lambda: self.remove_kaomoji(meme))
            else:
                menu.addAction('用預設程式開啟', lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.library.path(meme)))))
        menu.addAction('切換收藏', self.toggle_favorite)
        menu.addAction('編輯標籤', self.tag_edit.setFocus)
        menu.exec(self.grid.mapToGlobal(pos))

    def edit_kaomoji(self, meme=None):
        dialog = QDialog(self)
        dialog.setWindowTitle('編輯顏文字' if meme else '新增顏文字')
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        title = QLineEdit(meme.name if meme else '')
        title.setMaxLength(80)
        title.setPlaceholderText('例如：今天也要加油')
        content = QLineEdit(meme.content if meme else '')
        content.setMaxLength(500)
        content.setPlaceholderText('٩(๑❛ᴗ❛๑)۶')
        tags = QLineEdit(', '.join(meme.tags) if meme else '')
        tags.setPlaceholderText('例如：加油, 上班')
        form.addRow('名稱', title)
        form.addRow('顏文字', content)
        form.addRow('標籤', tags)
        layout.addLayout(form)
        error = QLabel()
        error.setWordWrap(True)
        error.setStyleSheet('color: #ffabb4;')
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        new_id = []

        def save():
            try:
                new_id.append(self.library.save_kaomoji(content.text(), title.text(), parse_tags(tags.text()), meme.id if meme else None))
                dialog.accept()
            except ValueError as exc:
                error.setText(str(exc))

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        content.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.search.clear()
            self.active_tag = None
            self.kind_combo.setCurrentIndex(0)
            self.refresh_tags()
            for index in range(self.collections.count()):
                if self.collections.item(index).data(Qt.ItemDataRole.UserRole) == 'kaomoji':
                    self.collections.setCurrentRow(index)
                    break
            self.refresh_items()
            for index in range(self.grid.count()):
                item = self.grid.item(index)
                if item.data(Qt.ItemDataRole.UserRole).id == new_id[0]:
                    self.grid.setCurrentItem(item)
                    self.grid.scrollToItem(item)
                    break
            self.statusBar().showMessage('顏文字已儲存', 5000)

    def remove_kaomoji(self, meme):
        if QMessageBox.question(self, '移除顏文字', f'移除「{meme.name}」？此操作只影響這個顏文字。') == QMessageBox.StandardButton.Yes:
            self.library.remove_kaomoji(meme.id)
            self.refresh_tags()
            self.refresh_items()

    def import_dialog(self):
        names, _ = QFileDialog.getOpenFileNames(self, '匯入表情素材', str(self.library.media_dir),
            '媒體檔案 (' + ' '.join('*' + ext for ext in sorted(EXTENSIONS)) + ')')
        if names:
            self.import_paths([Path(name) for name in names])

    def import_paths(self, paths):
        count, errors = self.library.import_files(paths)
        self.rescan()
        self.statusBar().showMessage(f'已匯入 {count} 個素材', 6000)
        if errors:
            self.show_error('\n'.join(errors[:12]))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def copy_selected(self) -> bool:
        memes = self.selected_memes()
        if len(memes) != 1:
            return False
        try:
            meme = memes[0]
            if meme.kind == 'kaomoji':
                # Use Qt's dedicated text API for native CF_UNICODETEXT ownership.
                QApplication.clipboard().setText(meme.content)
            else:
                data = clipboard_data(self.library.path(meme), meme.kind, self.paste_mode.currentData())
                QApplication.clipboard().setMimeData(data)
            self.statusBar().showMessage('已複製，切回聊天輸入框按 Ctrl+V 貼上。', 7000)
            return True
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return False

    def send_first(self):
        if not self.grid.selectedItems() and self.grid.count():
            self.grid.setCurrentRow(0)
        self.send_selected()

    def send_selected(self):
        if self.busy:
            return
        memes = self.selected_memes()
        if len(memes) != 1 or not self.copy_selected():
            return
        if not self.native or not windows.external_window(self.target):
            self.statusBar().showMessage('已複製。請切回聊天輸入框手動 Ctrl+V；下次可從該視窗按快捷鍵叫出。', 12000)
            return
        self.busy = True
        self.send_button.setEnabled(False)
        target, mid = self.target, memes[0].id
        self.stop_preview()
        self.hide()
        if not windows.restore_target(target):
            self.finish_paste(False, mid)
            return
        deadline = time.monotonic() + 1.8

        def attempt():
            if windows.foreground() != target:
                self.finish_paste(False, mid)
            elif windows.modifiers_down() and time.monotonic() < deadline:
                QTimer.singleShot(50, attempt)
            else:
                self.finish_paste(windows.paste(target), mid)

        QTimer.singleShot(180, attempt)

    def finish_paste(self, success, mid):
        self.busy = False
        self.target_locked = False
        self.send_button.setEnabled(True)
        if success:
            self.library.record_use(mid)
        else:
            self.show_picker()
            self.statusBar().showMessage('已複製，但無法自動貼上。請切回目標輸入框按 Ctrl+V（系統權限或焦點限制）。', 15000)

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('MemeDrop 設定')
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        key = QComboBox()
        key.addItems(list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
        key.setCurrentText(self.library.setting('hotkey', 'M'))
        form.addRow('全域快捷鍵：Ctrl + Alt +', key)
        layout.addLayout(form)
        hint = QLabel('自動模式：靜態圖貼圖片；GIF 和影片貼原檔。\n若聊天軟體不接受，切換原始檔案模式或直接拖曳。\n\n關閉視窗後會留在系統匣；右鍵圖示可結束。\n標籤及收藏存在 .memedrop/library.sqlite3。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            old = self.library.setting('hotkey', 'M')
            new = key.currentText()
            if self.native:
                windows.unregister_hotkey(int(self.winId()))
                if not windows.register_hotkey(int(self.winId()), new):
                    self.hotkey_registered = windows.register_hotkey(int(self.winId()), old)
                    self.hotkey_label.setText(f'Ctrl + Alt + {old}' + ('' if self.hotkey_registered else '（註冊失敗）'))
                    self.show_error('這組快捷鍵已被佔用，未儲存變更。')
                    return
                self.hotkey_registered = True
            self.library.set_setting('hotkey', new)
            self.hotkey_label.setText(f'Ctrl + Alt + {new}')

    def show_error(self, message):
        QMessageBox.warning(self, 'MemeDrop', message)

    def closeEvent(self, event):
        if self.native and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide_picker()
        else:
            event.accept()
            if self.native:
                QApplication.instance().quit()

    def cleanup(self):
        self.stop_preview()
        self.tray.hide()
        if self.native and self.hotkey_registered:
            windows.unregister_hotkey(int(self.winId()))
