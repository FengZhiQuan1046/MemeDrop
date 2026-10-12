"""Optional Windows integration check. No keystrokes or chat messages are sent.

Run directly (outside offscreen unit tests): python tests/native_check.py
Temporarily replaces then restores clipboard MIME data.
"""
import ctypes
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

from memedrop import windows
from memedrop.library import Library
from memedrop.ui import MainWindow, clipboard_data

app = QApplication([])
window = QWidget()  # Native HWND is created but never shown.
hwnd = int(window.winId())
clipboard = app.clipboard()
saved = QMimeData()
original = clipboard.mimeData()
if original:
    for format_name in original.formats():
        saved.setData(format_name, original.data(format_name))

result = {}
user32 = windows.user32
user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
registered = False
try:
    for key in 'MZYX':
        if windows.register_hotkey(hwnd, key):
            registered = True
            result['native_hotkey_registration'] = True
            windows.unregister_hotkey(hwnd)
            registered = False
            break
    assert result.get('native_hotkey_registration'), 'No test hotkey available'
    with tempfile.TemporaryDirectory(prefix='memedrop-native-') as directory:
        path = Path(directory) / '圖片.png'
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        image.fill(QColor('#a595ff'))
        image.save(str(path))
        clipboard.setMimeData(clipboard_data(path, 'image', 'auto'))
        app.processEvents()
        assert user32.IsClipboardFormatAvailable(8), 'CF_DIB missing'
        result['native_image_CF_DIB'] = True
        clipboard.setMimeData(clipboard_data(path, 'image', 'file'))
        app.processEvents()
        assert user32.IsClipboardFormatAvailable(15), 'CF_HDROP missing'
        result['native_file_CF_HDROP'] = True
        urls = clipboard.mimeData().urls()
        assert urls and Path(urls[0].toLocalFile()) == path
        result['unicode_file_path_roundtrip'] = True
        library = Library(Path(directory))
        picker = MainWindow(library, native=False)
        try:
            picker.grid.setCurrentRow(0)
            expected_text = picker.selected_memes()[0].content
            QTest.qWait(100)
            assert expected_text and picker.copy_selected()
            app.processEvents()
            assert user32.IsClipboardFormatAvailable(13), 'CF_UNICODETEXT missing'
            assert clipboard.text() == expected_text, 'Kaomoji text changed during copy'
            result['kaomoji_native_CF_UNICODETEXT'] = True
        finally:
            picker.cleanup()
            picker.close()
            picker.deleteLater()
            library.close()
finally:
    if registered:
        windows.unregister_hotkey(hwnd)
    clipboard.setMimeData(saved)
    app.processEvents()
    window.close()
print(json.dumps(result, indent=2))
