import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QToolButton
from studio.search_dialog import SearchDialog
from studio.sidebar import AvatarStore
from studio.theme import stylesheet

class PickerInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(stylesheet())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = QWidget()
        self.parent.avatars = AvatarStore(Path(self.temp.name), self.parent, enabled=False)
        self.parent.rooms = {}
        self.parent.favorites = set()
        self.dialog = SearchDialog({}, 1, 4, self.parent)
        self.room = dict(id='7902350', uid=1, name='测试主播', title='测试直播间', live=True, following=True)
        self.dialog.show_results(self.dialog.ticket, dict(rooms=[self.room], total=1, more=False, follow_state='ok'))
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.parent.close()
        self.dialog.deleteLater()
        self.parent.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def click_row(self, checkbox=False):
        rect = self.dialog.results.visualItemRect(self.dialog.results.item(0))
        point = QPoint(rect.left()+15, rect.center().y()) if checkbox else rect.center()
        QTest.mouseClick(self.dialog.results.viewport(), Qt.LeftButton, pos=point)
        self.app.processEvents()

    def test_checkbox_click_enables_add_and_emits_room_and_target(self):
        received = []
        self.dialog.rooms_added.connect(lambda rooms, target: received.append((rooms, target)))
        self.click_row(checkbox=True)
        self.assertEqual(self.dialog.results.item(0).checkState(), Qt.Checked)
        self.assertEqual(self.dialog.add_button.text(), '添加选中 (1)')
        self.assertTrue(self.dialog.add_button.isEnabled())
        QTest.mouseClick(self.dialog.add_button, Qt.LeftButton)
        self.assertEqual(received, [([self.room], 1)])

    def test_row_click_can_uncheck_and_keyboard_space_selects(self):
        self.click_row()
        self.assertEqual(len(self.dialog.selected_rooms()), 1)
        self.click_row()
        self.assertFalse(self.dialog.add_button.isEnabled())
        self.dialog.results.setCurrentRow(0)
        QTest.keyClick(self.dialog.results, Qt.Key_Space)
        self.assertEqual(self.dialog.add_button.text(), '添加选中 (1)')
        self.assertEqual(self.dialog.results.item(0).checkState(), Qt.Checked)

    def test_result_and_favorite_sync_and_count_only_once(self):
        self.dialog.sync_favorites({'7902350': self.room}, {'7902350'})
        self.click_row()
        self.assertEqual(self.dialog.favorite_strip.item(0).checkState(), Qt.Checked)
        self.assertEqual(len(self.dialog.selected_rooms()), 1)
        rect = self.dialog.favorite_strip.visualItemRect(self.dialog.favorite_strip.item(0))
        QTest.mouseClick(self.dialog.favorite_strip.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(self.dialog.results.item(0).checkState(), Qt.Unchecked)
        self.assertFalse(self.dialog.add_button.isEnabled())

    def test_clear_button_is_centered_and_click_clears_text(self):
        self.dialog.mode = 'search'
        for width in (640, 960):
            self.dialog.resize(width, 660)
            self.dialog.input.setText('测试昵称')
            self.app.processEvents()
            clear = self.dialog.input.findChild(QToolButton)
            rect = clear.geometry()
            self.assertTrue(self.dialog.input.rect().contains(rect))
            self.assertLessEqual(abs(rect.center().y()-self.dialog.input.rect().center().y()), 1)
            QTest.mouseClick(clear, Qt.LeftButton)
            self.assertEqual(self.dialog.input.text(), '')

if __name__ == '__main__':
    unittest.main()
