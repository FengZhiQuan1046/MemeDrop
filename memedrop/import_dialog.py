from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QProgressDialog

from .import_text import recognize_import_text


class ImportTextWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.texts = {}

    def run(self):
        self.texts = recognize_import_text(self.paths, self.progress.emit, self.isInterruptionRequested)


def recognize_with_progress(paths, parent):
    dialog = QProgressDialog('準備辨識圖片文字…', '取消匯入', 0, 100, parent)
    dialog.setWindowTitle('匯入表情包')
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setAutoClose(False)
    worker = ImportTextWorker(paths, dialog)
    worker.progress.connect(lambda value, text: (dialog.setValue(value), dialog.setLabelText(text)))
    worker.finished.connect(dialog.accept)
    dialog.canceled.connect(worker.requestInterruption)
    worker.start()
    dialog.exec()
    was_cancelled = dialog.wasCanceled()
    if was_cancelled:
        worker.requestInterruption()
    worker.wait()
    result = None if was_cancelled else worker.texts
    dialog.deleteLater()
    return result
