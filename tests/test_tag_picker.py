import os
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from memedrop.library import parse_tags
from memedrop.tag_picker import TagPicker

APP = QApplication.instance() or QApplication([])


class TagPickerTests(unittest.TestCase):
    def setUp(self):
        self.picker = TagPicker('保留')
        self.picker.set_options(['貓咪', 'Happy', '上班'])
        self.picker.show()
        self.picker.show_popup()

    def tearDown(self):
        self.picker.close()
        self.picker.deleteLater()
        APP.processEvents()

    def click_tag(self, tag):
        item = next(self.picker.choices.item(i) for i in range(self.picker.choices.count())
                    if self.picker.choices.item(i).text() == tag)
        QTest.mouseClick(self.picker.choices.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.picker.choices.visualItemRect(item).center())

    def test_multiple_row_selections_and_removal_keep_popup_open(self):
        self.click_tag('貓咪')
        self.click_tag('Happy')
        self.assertEqual(set(parse_tags(self.picker.text())), {'保留', '貓咪', 'Happy'})
        self.click_tag('保留')
        self.assertEqual(set(parse_tags(self.picker.text())), {'貓咪', 'Happy'})
        self.assertTrue(self.picker.popup.isVisible())

    def test_normalized_search_and_new_tags_with_enter(self):
        for query, expected in [('猫咪', '貓咪'), ('HAPPY', 'Happy')]:
            self.picker.query.setText(query)
            self.assertEqual(self.picker.choices.count(), 1)
            self.assertEqual(self.picker.choices.item(0).text(), expected)
            self.click_tag(expected)
        self.picker.query.setText('新標籤，另一個')
        QTest.keyClick(self.picker.query, Qt.Key.Key_Return)
        self.assertEqual(set(parse_tags(self.picker.text())), {'保留', '貓咪', 'Happy', '新標籤', '另一個'})
        self.assertEqual(self.picker.query.text(), '')
        self.assertTrue(self.picker.popup.isVisible())

    def test_refresh_options_and_direct_entry(self):
        self.picker.setText('直接輸入, 新增')
        self.picker.set_options(['本區塊'])
        self.assertEqual({self.picker.choices.item(i).text() for i in range(self.picker.choices.count())},
                         {'直接輸入', '新增', '本區塊'})
        self.picker.popup.hide()
        QTest.keyClick(self.picker, Qt.Key.Key_Down)
        self.assertTrue(self.picker.popup.isVisible())
