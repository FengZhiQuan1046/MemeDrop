import base64
import ctypes
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit

from memedrop import desktop as windows
from memedrop.library import Library
from memedrop.ui import MainWindow, STYLE, clipboard_data

APP = QApplication.instance() or QApplication([])
APP.setStyle('Fusion')
APP.setStyleSheet(STYLE)


class UiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        image = QImage(240, 180, QImage.Format.Format_RGB32)
        image.fill(QColor('#8b70e9'))
        image.save(str(self.lib.media_dir / '開心.png'))
        # Tiny real GIF fixture; originals must remain GIF when copied automatically.
        (self.lib.media_dir / '貓.gif').write_bytes(base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'))
        self.win = MainWindow(self.lib, native=False)
        self.win.show()
        QTest.qWait(30)

    def tearDown(self):
        APP.clipboard().clear()
        self.win.cleanup()
        self.win.close()
        self.win.deleteLater()
        APP.processEvents()
        self.lib.close()
        self.temp.cleanup()

    def select(self, name):
        for index in range(self.win.grid.count()):
            if self.win.grid.item(index).data(Qt.ItemDataRole.UserRole).name == name:
                self.win.grid.setCurrentRow(index)
                APP.processEvents()
                return
        self.fail('Fixture not found')

    def test_tags_favorites_and_filter_flow(self):
        self.select('開心')
        self.win.tag_edit.setText('快樂, 上班')
        self.win.save_tags()
        self.win.toggle_favorite()
        self.win.collections.setCurrentRow(1)
        self.assertEqual(self.win.grid.count(), 1)
        self.win.search.setText('上班')
        QTest.qWait(180)
        self.assertEqual(self.win.grid.count(), 1)
        self.win.search.setText('沒有')
        QTest.qWait(180)
        self.assertEqual(self.win.grid.count(), 0)
        self.assertEqual(self.win.grid_stack.currentIndex(), 1)

    def test_image_copy(self):
        self.select('開心')
        self.assertTrue(self.win.copy_selected())
        mime = APP.clipboard().mimeData()
        self.assertTrue(mime.hasImage())
        self.assertTrue(mime.hasFormat('image/png'))
        self.assertFalse(mime.hasUrls())

    def test_media_backend_is_available(self):
        self.assertTrue(self.win.player.isAvailable(), 'Qt multimedia backend is missing')

    def test_kaomoji_category_and_search(self):
        self.lib.seed_kaomoji()
        self.win.rescan()
        self.win.kind_combo.setCurrentIndex(self.win.kind_combo.findData('image'))
        self.win.collections.setCurrentRow(4)
        self.assertEqual(self.win.grid.count(), 240)
        self.win.search.setText('开心')
        QTest.qWait(180)
        self.assertEqual(self.win.grid.count(), 15)
        self.win.grid.setCurrentRow(0)
        self.assertEqual(self.win.preview.text(), self.win.selected_memes()[0].content)
        self.assertFalse(self.win.paste_mode.isEnabled())

    def test_custom_kaomoji_copy_drag_favorite_and_scan(self):
        text = '¯\\_(ツ)_/¯ <3'
        mid = self.lib.save_kaomoji(text, '隨你囉', ['無奈'])
        self.win.rescan()
        self.select('隨你囉')
        for mode in ('auto', 'file', 'image'):
            self.win.paste_mode.setCurrentIndex(self.win.paste_mode.findData(mode))
            self.assertTrue(self.win.copy_selected())
            mime = APP.clipboard().mimeData()
            self.assertEqual(mime.text(), text)
            self.assertFalse(mime.hasUrls())
            self.assertFalse(mime.hasImage())
        self.assertEqual(self.win.grid.selection_mime_data().text(), text)
        self.win.toggle_favorite()
        self.win.collections.setCurrentRow(1)
        self.assertEqual(self.win.grid.count(), 1)
        self.win.rescan()
        self.assertEqual(self.win.selected_memes()[0].id, mid)
        self.assertEqual(self.win.preview.text(), text)

    def test_mixed_drag_does_not_drop_either_selection_silently(self):
        self.lib.save_kaomoji('(^test^)', '測試', [])
        self.win.rescan()
        self.win.grid.selectAll()
        self.assertIsNone(self.win.grid.selection_mime_data())

    def test_add_kaomoji_dialog_saves_and_selects_new_item(self):
        def fill_dialog():
            dialog = APP.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            for field, text in zip(fields, ('打起精神', '(^dialog^)و', '自訂, 加油')):
                field.setText(text)
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(50, fill_dialog)
        self.win.edit_kaomoji()
        self.assertEqual(self.win.collection, 'kaomoji')
        self.assertEqual(self.win.selected_memes()[0].content, '(^dialog^)و')
        self.assertEqual(set(self.win.selected_memes()[0].tags), {'自訂', '加油'})

    def test_gif_original_copy(self):
        self.select('貓')
        self.assertTrue(self.win.copy_selected())
        mime = APP.clipboard().mimeData()
        self.assertTrue(mime.hasUrls())
        self.assertFalse(mime.hasImage())
        self.assertTrue(mime.urls()[0].toLocalFile().endswith('貓.gif'))

    def test_video_format_and_missing_file(self):
        path = self.lib.media_dir / 'demo.mp4'
        path.write_bytes(b'fixture')
        mime = clipboard_data(path, 'video', 'auto')
        self.assertTrue(mime.hasUrls())
        with self.assertRaises(ValueError):
            clipboard_data(path, 'video', 'image')
        with self.assertRaises(FileNotFoundError):
            clipboard_data(path.with_name('missing.png'), 'image', 'auto')

    def test_no_target_only_copies_without_typing(self):
        self.select('開心')
        with patch.object(windows, 'paste') as paste:
            self.win.send_selected()
            paste.assert_not_called()
        self.assertTrue(self.win.isVisible())
        self.assertEqual(self.lib.items(collection='recent'), [])

    @unittest.skipUnless(windows.AVAILABLE, 'Requires native Win32 API; run on Windows')
    def test_foreground_guard_prevents_wrong_window(self):
        with patch.object(windows.backend, 'external_window', return_value=True), \
             patch.object(windows.backend, 'foreground', return_value=456), \
             patch.object(windows.backend.user32, 'SendInput') as send:
            self.assertFalse(windows.paste(123))
            send.assert_not_called()

    @unittest.skipUnless(windows.AVAILABLE, 'Requires native Win32 layout; run on Windows')
    def test_win32_input_layout(self):
        self.assertEqual(ctypes.sizeof(windows.backend.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    @unittest.skipIf(windows.AVAILABLE, 'Container-only desktop boundary check')
    def test_container_does_not_claim_native_desktop_support(self):
        self.assertFalse(self.win.native)
        self.assertFalse(windows.register_hotkey(0, 'M'))
        self.assertFalse(windows.paste(0))


if __name__ == '__main__':
    unittest.main()
