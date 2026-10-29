import base64
import ctypes
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QMessageBox

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
        self.win.collection_filter.setCurrentIndex(self.win.collection_filter.findData('favorites'))
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
        self.win.activate_section('builtin_kaomoji')
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
        self.win.activate_section('my_kaomoji')
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
        self.win.collection_filter.setCurrentIndex(self.win.collection_filter.findData('favorites'))
        self.assertEqual(self.win.grid.count(), 1)
        self.win.rescan()
        self.assertEqual(self.win.selected_memes()[0].id, mid)
        self.assertEqual(self.win.preview.text(), text)

    def test_sections_prevent_mixed_text_and_media_selection(self):
        self.lib.save_kaomoji('(^test^)', '測試', [])
        self.win.rescan()
        self.win.grid.selectAll()
        self.assertTrue(self.win.grid.selection_mime_data().hasUrls())
        self.assertEqual(len(self.win.selected_memes()), 2)
        self.win.activate_section('my_kaomoji')
        self.assertFalse(self.win.selected_memes())
        self.win.grid.selectAll()
        self.assertEqual(self.win.grid.selection_mime_data().text(), '(^test^)')

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
        self.assertEqual(self.win.collection, 'my_kaomoji')
        self.assertEqual(self.win.selected_memes()[0].content, '(^dialog^)و')
        self.assertEqual(set(self.win.selected_memes()[0].tags), {'自訂', '加油'})

    def test_section_tags_and_filters_stay_separate(self):
        self.lib.seed_kaomoji()
        custom = self.lib.save_kaomoji('(^private^)', '私人', ['私人標籤'])
        self.select('開心')
        self.win.tag_edit.setText('圖片標籤')
        self.win.save_tags()
        self.win.select_tag(self.win.tags_list.item(0))
        self.win.search.setText('開心')
        self.win.collection_filter.setCurrentIndex(1)
        self.win.activate_section('my_kaomoji')
        self.assertIsNone(self.win.active_tag)
        self.assertEqual(self.win.search.text(), '')
        self.assertEqual(self.win.collection_filter.currentData(), 'all')
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.win.grid.item(0).data(Qt.ItemDataRole.UserRole).id, custom)
        self.assertEqual(self.win.tags_list.count(), 1)
        self.assertEqual(self.win.tags_list.item(0).data(Qt.ItemDataRole.UserRole), '私人標籤')
        self.win.activate_section('builtin_kaomoji')
        self.assertEqual(self.win.grid.count(), 240)
        self.assertNotIn('私人標籤', [self.win.tags_list.item(i).data(Qt.ItemDataRole.UserRole)
                                   for i in range(self.win.tags_list.count())])

    def test_series_creation_move_and_import(self):
        with patch('memedrop.ui.QInputDialog.getText', return_value=('貓咪系列', True)):
            self.win.create_series()
        section = self.win.collection
        self.assertTrue(section.startswith('series:'))
        self.assertEqual(self.win.grid.count(), 0)
        self.assertIn('系列還沒有', self.win.empty_label.text())
        self.win.activate_section('my_memes')
        self.select('貓')
        self.win.tag_edit.setText('系列專用')
        self.win.save_tags()
        self.win.move_to_series(int(section.split(':')[1]))
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.win.tags_list.count(), 0)
        self.win.activate_section(section)
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.win.tags_list.item(0).data(Qt.ItemDataRole.UserRole), '系列專用')
        source = self.root / 'new.png'
        source.write_bytes((self.lib.media_dir / '開心.png').read_bytes())
        self.win.import_paths([source])
        self.assertEqual(self.win.grid.count(), 2)
        self.win.collection_filter.setCurrentIndex(1)
        self.assertEqual(self.win.grid.count(), 0)
        self.win.activate_section('my_memes')
        self.assertEqual(self.win.grid.count(), 1)

    def test_tag_menu_rename_and_delete_only_affect_current_section(self):
        custom = self.lib.save_kaomoji('(^scoped^)', '私人', ['共用名稱'])
        self.select('開心')
        self.win.tag_edit.setText('共用名稱')
        self.win.save_tags()
        rename, delete = object(), object()
        with patch('memedrop.ui.QMenu') as menu_class, \
             patch('memedrop.ui.QInputDialog.getText', return_value=('圖片名稱', True)):
            menu_class.return_value.addAction.side_effect = [rename, delete]
            menu_class.return_value.exec.return_value = rename
            self.win.tag_menu(self.win.tags_list.visualItemRect(self.win.tags_list.item(0)).center())
        self.assertEqual(self.lib.items(section='my_kaomoji')[0].tags, ('共用名稱',))
        self.assertEqual(self.lib.tag_counts('my_memes'), [('圖片名稱', 1)])

        with patch('memedrop.ui.QMenu') as menu_class, \
             patch('memedrop.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            menu_class.return_value.addAction.side_effect = [rename, delete]
            menu_class.return_value.exec.return_value = delete
            self.win.tag_menu(self.win.tags_list.visualItemRect(self.win.tags_list.item(0)).center())
        self.assertEqual(self.lib.tag_counts('my_memes'), [])
        self.assertEqual(self.lib.items(section='my_kaomoji')[0].id, custom)
        self.assertEqual(self.lib.tag_counts('my_kaomoji'), [('共用名稱', 1)])

    def test_rename_button_updates_file_and_keeps_selection_and_tags(self):
        self.select('開心')
        mid = self.win.current_meme.id
        self.win.tag_edit.setText('圖片標籤')
        self.win.save_tags()
        with patch('memedrop.ui.QInputDialog.getText', return_value=('新的開心.png', True)):
            self.win.rename_button.click()
        self.assertEqual(self.win.current_meme.id, mid)
        self.assertEqual(self.win.current_meme.name, '新的開心')
        self.assertEqual(self.win.current_meme.tags, ('圖片標籤',))
        self.assertTrue((self.lib.media_dir / '新的開心.png').is_file())
        self.assertFalse((self.lib.media_dir / '開心.png').exists())
        with patch('memedrop.ui.QInputDialog.getText', return_value=('bad.gif', True)), \
             patch.object(self.win, 'show_error') as error:
            self.win.rename_button.click()
        error.assert_called_once()
        self.assertTrue((self.lib.media_dir / '新的開心.png').is_file())

    def test_recycle_buttons_restore_and_disable_sending_from_trash(self):
        self.select('貓')
        mid = self.win.current_meme.id
        self.win.tag_edit.setText('貓咪')
        self.win.save_tags()
        self.win.trash_button.click()
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.lib.tag_counts('my_memes'), [])
        self.win.activate_section('trash')
        self.assertEqual(self.win.grid.count(), 1)
        self.win.grid.setCurrentRow(0)
        self.assertEqual(self.win.current_meme.id, mid)
        self.assertFalse(self.win.send_button.isEnabled())
        self.assertFalse(self.win.copy_button.isEnabled())
        self.assertFalse(self.win.tag_edit.isEnabled())
        self.assertFalse(self.win.copy_selected())
        self.assertIsNone(self.win.grid.selection_mime_data())
        self.assertTrue(self.win.restore_button.isEnabled())
        self.win.restore_button.click()
        self.assertEqual(self.win.grid.count(), 0)
        self.assertFalse(self.win.empty_trash_button.isEnabled())
        self.assertIn('回收站是空的', self.win.empty_label.text())
        self.win.activate_section('my_memes')
        self.select('貓')
        self.assertEqual(self.win.current_meme.id, mid)
        self.assertEqual(self.win.current_meme.tags, ('貓咪',))

    def test_batch_delete_confirmation_and_empty_trash_ignore_search_filter(self):
        self.win.grid.selectAll()
        self.win.trash_button.click()
        self.win.activate_section('trash')
        self.win.grid.selectAll()
        with patch('memedrop.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            self.win.delete_button.click()
        self.assertEqual(self.win.grid.count(), 2)
        self.win.search.setText('開心')
        self.win.refresh_items()
        self.assertEqual(self.win.grid.count(), 1)
        with patch('memedrop.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.win.empty_trash_button.click()
        self.assertEqual(self.lib.items(section='trash'), [])
        self.assertFalse((self.lib.media_dir / '開心.png').exists())
        self.assertFalse((self.lib.media_dir / '貓.gif').exists())

    def test_trash_rejects_import_and_kaomoji_uses_same_recycle_flow(self):
        mid = self.lib.save_kaomoji('(^recycle_ui^)', '我的文字', ['私人'])
        self.win.activate_section('my_kaomoji')
        self.win.grid.setCurrentRow(0)
        self.assertFalse(self.win.rename_button.isEnabled())
        self.win.trash_button.click()
        self.win.activate_section('trash')
        source = self.root / 'outside.png'
        source.write_bytes(b'not imported')
        self.win.import_paths([source])
        self.assertFalse((self.lib.media_dir / source.name).exists())
        self.win.grid.setCurrentRow(0)
        self.assertEqual(self.win.current_meme.id, mid)
        self.win.restore_button.click()
        self.win.activate_section('my_kaomoji')
        self.assertEqual(self.win.grid.count(), 1)
        self.win.grid.setCurrentRow(0)
        self.assertEqual(self.win.current_meme.tags, ('私人',))

    def test_search_box_normalizes_case_and_chinese_in_every_section(self):
        self.select('開心')
        mid = self.win.current_meme.id
        self.lib.rename_file(mid, '快樂Cat.png')
        self.lib.set_tags([mid], ['歡迎'])
        self.win.rescan()
        for query in ('快乐cAT 欢迎', '快樂CAT 歡迎'):
            self.win.search.setText(query)
            QTest.qWait(180)
            self.assertEqual(self.win.grid.count(), 1)
            self.assertEqual(self.win.grid.item(0).data(Qt.ItemDataRole.UserRole).id, mid)
        self.lib.save_kaomoji('(可愛MiXeD)', '感谢你HELLO', ['开心'])
        self.win.activate_section('my_kaomoji')
        self.win.search.setText('感謝你hello 可爱mixed 開心')
        QTest.qWait(180)
        self.assertEqual(self.win.grid.count(), 1)
        self.lib.trash_items([mid])
        self.win.activate_section('trash')
        self.win.search.setText('快乐cat 欢迎')
        QTest.qWait(180)
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.win.grid.item(0).data(Qt.ItemDataRole.UserRole).id, mid)

    def test_series_name_search_rename_and_full_merge_ignore_item_filter(self):
        source = self.lib.create_series('電影Happy')
        target = self.lib.create_series('目標集合')
        ids = [m.id for m in self.lib.items()]
        self.lib.set_series(ids, source)
        self.lib.set_tags(ids, ['保留'])
        self.win.rescan()
        self.win.series_search.setText('电影hAPPY')
        self.assertEqual(self.win.series_list.count(), 1)
        self.assertEqual(self.win.series_list.item(0).data(Qt.ItemDataRole.UserRole), f'series:{source}')
        self.win.activate_section(f'series:{source}')
        with patch('memedrop.ui.QInputDialog.getText', return_value=('新集合', True)):
            self.win.rename_series(source)
        self.assertEqual(self.win.heading.text(), '新集合')
        self.win.search.setText('不會匹配任何素材')
        self.win.refresh_items()
        self.assertEqual(self.win.grid.count(), 0)
        with patch('memedrop.ui.QInputDialog.getItem', return_value=('目標集合', True)), \
             patch('memedrop.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.win.merge_series(source)
        self.assertEqual(self.win.collection, f'series:{target}')
        self.assertEqual(self.win.grid.count(), 2)
        self.assertEqual(self.lib.items(section=f'series:{source}'), [])
        self.assertTrue(all(m.tags == ('保留',) for m in self.lib.items(section=f'series:{target}')))

    def test_video_dialog_worker_previews_edits_and_imports_subtitle_frames(self):
        import cv2
        import numpy as np
        from memedrop.series_dialog import VideoSeriesDialog
        video = self.root / '測試影片.avi'
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 4, (320, 180))
        self.assertTrue(writer.isOpened())
        for _ in range(8):
            writer.write(np.full((180, 320, 3), 45, dtype=np.uint8))
        writer.release()
        srt = self.root / '字幕.srt'
        srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n'
                       '2\n00:00:01,000 --> 00:00:02,000\n第二句\n', encoding='utf-8')
        dialog = VideoSeriesDialog(self.lib, self.win, video=video)
        try:
            dialog.subtitle_path.setText(str(srt))
            dialog.start_extraction()
            deadline = time.monotonic() + 10
            while dialog.worker.isRunning() and time.monotonic() < deadline:
                QTest.qWait(20)
            QTest.qWait(30)
            self.assertFalse(dialog.worker.isRunning(), dialog.status.text())
            self.assertEqual(dialog.table.rowCount(), 2, dialog.status.text())
            dialog.table.item(0, 1).setText('修改後的台詞?')
            dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
            self.assertTrue(dialog.import_button.isEnabled())
            dialog.import_button.click()
            self.assertIsNotNone(dialog.saved_series_id, dialog.status.text())
            items = self.lib.items(section=f'series:{dialog.saved_series_id}')
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].name, '修改後的台詞？')
            self.assertEqual(items[0].content, '修改後的台詞?')
        finally:
            dialog.cleanup()
            dialog.close()
            dialog.deleteLater()

    def test_video_dialog_close_cancels_worker_before_cleanup(self):
        from memedrop.series_dialog import VideoSeriesDialog
        video = self.root / 'cancel.mp4'
        video.write_bytes(b'fixture')

        def slow_extract(*args, cancelled, **kwargs):
            while not cancelled():
                time.sleep(.01)
            return []

        dialog = VideoSeriesDialog(self.lib, self.win, video=video)
        try:
            with patch('memedrop.series_dialog.extract_caption_frames', slow_extract):
                dialog.start_extraction()
                dialog.reject()
                self.assertTrue(dialog.close_pending)
                deadline = time.monotonic() + 5
                while dialog.worker.isRunning() and time.monotonic() < deadline:
                    QTest.qWait(20)
                QTest.qWait(20)
                self.assertFalse(dialog.worker.isRunning())
        finally:
            dialog.cleanup()
            dialog.close()
            dialog.deleteLater()

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

    def test_import_uses_recognized_name_and_cancel_copies_nothing(self):
        source = self.root / 'outside.png'
        source.write_bytes((self.lib.media_dir / '開心.png').read_bytes())
        with patch('memedrop.import_dialog.recognize_with_progress', return_value={source: '辨識文字?'}):
            self.win.import_paths([source])
        self.assertTrue((self.lib.media_dir / '辨識文字？.png').is_file())
        self.assertTrue(source.is_file())
        before = {m.id for m in self.lib.items()}
        with patch('memedrop.import_dialog.recognize_with_progress', return_value=None):
            self.win.import_paths([source])
        self.assertEqual({m.id for m in self.lib.items()}, before)

    def test_hierarchy_editor_leaf_display_and_untagged_filter(self):
        from memedrop.tag_dialog import TagHierarchyDialog
        self.select('開心')
        mid = self.win.current_meme.id
        self.lib.set_tags([mid], ['動物', '貓', '橘貓', '開心'])
        dialog = TagHierarchyDialog(self.lib, 'my_memes', self.win)
        try:
            dialog.tag.setText('貓')
            dialog.parents.setText('動物, 可愛')
            dialog.children.setText('橘貓')
            dialog.save()
            self.assertEqual(self.lib.tag_ancestors('my_memes')['橘貓'], {'貓', '動物', '可愛'})
        finally:
            dialog.deleteLater()
        self.win.refresh_tags()
        self.win.refresh_items()
        self.select('開心')
        self.assertEqual(set(self.win.current_meme.display_tags), {'橘貓', '開心'})
        self.assertNotIn('#動物', self.win.grid.currentItem().text())
        self.assertIn('#橘貓', self.win.grid.currentItem().text())
        self.assertEqual(set(self.win.tag_edit.text().split(', ')), {'橘貓', '開心'})
        self.win.filter_untagged()
        self.assertEqual(self.win.grid.count(), 1)
        self.assertEqual(self.win.grid.item(0).data(Qt.ItemDataRole.UserRole).name, '貓')

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
