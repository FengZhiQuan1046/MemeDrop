from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .library import VIDEO_EXTENSIONS
from .video_series import CaptionFrame, extract_caption_frames


class ExtractionWorker(QThread):
    progress = Signal(int, str)
    ready = Signal(list)
    failed = Signal(str)

    def __init__(self, video, output_dir, options, parent=None):
        super().__init__(parent)
        self.video, self.output_dir, self.options = video, output_dir, options

    def run(self):
        try:
            frames = extract_caption_frames(self.video, self.output_dir, **self.options,
                progress=self.progress.emit, cancelled=self.isInterruptionRequested)
            self.ready.emit(frames)
        except Exception as exc:
            self.failed.emit(str(exc))


class VideoSeriesDialog(QDialog):
    def __init__(self, library, parent=None, series_id=None, video=None):
        super().__init__(parent)
        self.library = library
        self.worker = None
        self.close_pending = False
        self.frames = []
        self.saved_series_id = None
        self.run_number = 0
        self.temp = tempfile.TemporaryDirectory(prefix='caption-preview-', dir=library.data_dir)
        self.setWindowTitle('從影片建立表情包系列')
        self.resize(920, 720)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.video_path = QLineEdit(str(video) if video else '')
        self.video_path.setPlaceholderText('選擇含字幕台詞的影片')
        self.subtitle_path = QLineEdit()
        self.subtitle_path.setPlaceholderText('選填：SRT／VTT；留空時辨識影片畫面上的字幕')
        for label, field, callback in [('影片', self.video_path, self.choose_video),
                                       ('外掛字幕', self.subtitle_path, self.choose_subtitles)]:
            row = QHBoxLayout()
            row.addWidget(field)
            browse = QPushButton('選擇…')
            browse.clicked.connect(callback)
            row.addWidget(browse)
            container = QWidget()
            container.setLayout(row)
            form.addRow(label, container)
        self.destination = QComboBox()
        self.destination.addItem('建立新系列', None)
        for sid, name, _ in library.series_counts():
            self.destination.addItem(name, sid)
        if series_id is not None:
            self.destination.setCurrentIndex(max(0, self.destination.findData(series_id)))
        self.series_name = QLineEdit(Path(video).stem[:80] if video else '')
        self.series_name.setMaxLength(80)
        self.series_name.setPlaceholderText('例如：電影名稱・經典台詞')
        self.destination.currentIndexChanged.connect(lambda: self.series_name.setEnabled(self.destination.currentData() is None))
        self.series_name.setEnabled(self.destination.currentData() is None)
        form.addRow('加入集合', self.destination)
        form.addRow('新系列名稱', self.series_name)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 5)
        self.interval.setSingleStep(0.1)
        self.interval.setValue(0.5)
        self.interval.setSuffix(' 秒')
        self.region = QComboBox()
        for name, fraction in [('畫面下方 40%', 0.4), ('畫面下方 60%', 0.6), ('整個畫面', 1.0)]:
            self.region.addItem(name, fraction)
        self.subtitle_source = QComboBox()
        self.subtitle_source.addItem('自動：內嵌文字字幕優先，否則辨識畫面字幕', True)
        self.subtitle_source.addItem('只辨識畫面字幕（OCR）', False)
        self.draw_subtitles = QCheckBox('將文字字幕繪入截圖（影片已含字幕時可取消）')
        self.draw_subtitles.setChecked(True)
        form.addRow('字幕來源', self.subtitle_source)
        form.addRow('辨識間隔', self.interval)
        form.addRow('字幕範圍', self.region)
        form.addRow('', self.draw_subtitles)
        self.options_widget = QWidget()
        self.options_widget.setLayout(form)
        layout.addWidget(self.options_widget)
        hint = QLabel('先擷取並預覽，可修改台詞、取消不需要的截圖；匯入後以台詞命名，重複檔名自動加序號。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['截圖／選取', '台詞（可直接修改）', '影片時間'])
        self.table.setIconSize(QSize(120, 70))
        self.table.setColumnWidth(0, 154)
        self.table.setColumnWidth(2, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self.update_import_button)
        self.table.cellDoubleClicked.connect(self.preview_frame)
        layout.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel('影片和字幕會在本機處理。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.start_button = QPushButton('開始擷取')
        self.start_button.clicked.connect(self.start_extraction)
        self.cancel_button = QPushButton('停止擷取')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_extraction)
        self.import_button = QPushButton('加入系列')
        self.import_button.setObjectName('primary')
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_selected)
        close = QPushButton('關閉')
        close.clicked.connect(self.reject)
        for button in (self.start_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def choose_video(self):
        name, _ = QFileDialog.getOpenFileName(self, '選擇影片', '',
            '影片 (' + ' '.join('*' + ext for ext in sorted(VIDEO_EXTENSIONS)) + ')')
        if name:
            self.video_path.setText(name)
            if not self.series_name.text():
                self.series_name.setText(Path(name).stem[:80])

    def choose_subtitles(self):
        name, _ = QFileDialog.getOpenFileName(self, '選擇字幕', '', '字幕 (*.srt *.vtt)')
        if name:
            self.subtitle_path.setText(name)

    def start_extraction(self):
        if self.worker and self.worker.isRunning():
            return
        video = Path(self.video_path.text())
        if not video.is_file() or video.suffix.lower() not in VIDEO_EXTENSIONS:
            self.status.setText('請選擇有效的影片檔案。')
            return
        subtitle = Path(self.subtitle_path.text()) if self.subtitle_path.text().strip() else None
        if subtitle is not None and not subtitle.is_file():
            self.status.setText('字幕檔案不存在。')
            return
        self.frames = []
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.run_number += 1
        self.worker = ExtractionWorker(video, Path(self.temp.name) / str(self.run_number),
            {'interval': self.interval.value(), 'bottom_fraction': self.region.currentData(),
             'subtitles': subtitle, 'draw_subtitles': self.draw_subtitles.isChecked(),
             'embedded': self.subtitle_source.currentData()}, self)
        self.worker.progress.connect(self.show_progress)
        self.worker.ready.connect(self.show_frames)
        self.worker.failed.connect(lambda message: self.status.setText('擷取失敗：' + message))
        self.worker.finished.connect(self.worker_finished)
        self.options_widget.setEnabled(False)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.import_button.setEnabled(False)
        self.status.setText('正在讀取影片…')
        self.worker.start()

    def show_progress(self, value, message):
        self.progress.setValue(value)
        self.status.setText(message)

    def show_frames(self, frames):
        self.frames = frames
        self.table.blockSignals(True)
        self.table.setRowCount(len(frames))
        for row, frame in enumerate(frames):
            thumbnail = QTableWidgetItem(QIcon(QPixmap(str(frame.path)).scaled(120, 70,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)), '')
            thumbnail.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            thumbnail.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, thumbnail)
            self.table.setItem(row, 1, QTableWidgetItem(frame.text))
            seconds = frame.seconds
            timestamp = QTableWidgetItem(f'{int(seconds // 60):02d}:{seconds % 60:04.1f}')
            timestamp.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 2, timestamp)
            self.table.setRowHeight(row, 78)
        self.table.blockSignals(False)
        self.status.setText(f'找到 {len(frames)} 張台詞截圖，可修改台詞後加入系列。' if frames else
                            '沒有找到字幕。可擴大字幕範圍、縮短辨識間隔，或選擇對應的 SRT／VTT 字幕。')

    def update_import_button(self, *args):
        running = self.worker is not None and self.worker.isRunning()
        self.import_button.setEnabled(not running and any(self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(self.table.rowCount())))

    def preview_frame(self, row, column):
        if column != 0 or row >= len(self.frames):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.table.item(row, 1).text())
        layout = QVBoxLayout(dialog)
        image = QLabel()
        image.setPixmap(QPixmap(str(self.frames[row].path)).scaled(960, 540,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(image)
        dialog.exec()

    def worker_finished(self):
        self.options_widget.setEnabled(True)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.update_import_button()
        if self.close_pending:
            super().reject()

    def cancel_extraction(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.status.setText('正在停止；已完成的截圖仍可預覽與匯入。')

    def import_selected(self):
        selected = [CaptionFrame(self.table.item(row, 1).text(), frame.path, frame.seconds)
                    for row, frame in enumerate(self.frames)
                    if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
        try:
            self.saved_series_id, count = self.library.save_caption_series(selected,
                name=self.series_name.text(), series_id=self.destination.currentData())
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.setText('匯入失敗：' + str(exc))
            return
        self.accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.close_pending = True
            self.cancel_extraction()
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

    def cleanup(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        self.temp.cleanup()
