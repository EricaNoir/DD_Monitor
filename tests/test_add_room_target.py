import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QEvent, QCoreApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.app import StudioWindow
from studio.player import PlayerTile
from studio.state import load_state


class AddRoomTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'studio.json'
        self.window = StudioWindow(Path(__file__).resolve().parents[1], demo=True, state_path=self.path)
        self.original = [dict(id=str(i+1), name=f'Original {i+1}', live=False) for i in range(4)]
        self.window.rooms = {r['id']: r for r in self.original}
        self.window.favorites = set(self.window.rooms)
        for tile, room in zip(self.window.tiles, self.original):
            tile.room = dict(room)
        self.window.refresh_library()
        # Exercise real set_room/clear/state changes; only external reads are mocked.
        for name in ('start_chat', 'reload'):
            mock = patch.object(PlayerTile, name)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)
        self.window.show()

    def tearDown(self):
        self.window.demo = True
        for dialog in self.window.dialogs:
            dialog.close()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def select(self, rooms, target=1):
        self.window.open_search(target)
        dialog = self.window.dialogs[-1]
        dialog.show_results(dialog.ticket, dict(rooms=rooms, total=len(rooms), more=False, follow_state='ok'))
        self.app.processEvents()
        for i in range(len(rooms)):
            rect = dialog.results.visualItemRect(dialog.results.item(i))
            QTest.mouseClick(dialog.results.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(dialog.add_button.text(), f'添加选中 ({len(rooms)})')
        return dialog

    def test_button_replaces_explicit_occupied_target_and_persists(self):
        room = dict(id='7902350', name='Sample live room', live=True)
        dialog = self.select([room])
        # Turn on persistence without starting real background account/status reads.
        with patch.object(self.window, 'hydrate_avatars'):
            self.window.demo = False
            QTest.mouseClick(dialog.add_button, Qt.LeftButton)
        self.assertEqual([t.room['id'] for t in self.window.tiles[:4]], ['1', '7902350', '3', '4'])
        self.assertFalse(dialog.isVisible())
        self.reload.assert_called_once()
        self.assertEqual(load_state(self.path)['slots'][:4], ['1', '7902350', '3', '4'])
        self.assertEqual(self.window.favorites, {'1', '2', '3', '4'})

    def test_multiple_rooms_fill_target_then_empty_slot_only(self):
        self.window.tiles[3].room = None
        rooms = [dict(id=str(10+i), name=f'Sample {i}', live=True) for i in range(2)]
        dialog = self.select(rooms)
        QTest.mouseClick(dialog.add_button, Qt.LeftButton)
        self.assertEqual([t.room['id'] for t in self.window.tiles[:4]], ['1', '10', '3', '11'])
        self.assertEqual(self.reload.call_count, 2)

    def test_over_capacity_is_explained_without_partial_add(self):
        rooms = [dict(id=str(10+i), name=f'Sample {i}', live=True) for i in range(2)]
        dialog = self.select(rooms)
        QTest.mouseClick(dialog.add_button, Qt.LeftButton)
        self.assertTrue(dialog.isVisible())
        self.assertIn('最多可添加 1 个', dialog.status.text())
        self.assertEqual([t.room['id'] for t in self.window.tiles[:4]], ['1', '2', '3', '4'])
        self.reload.assert_not_called()

    def test_favorite_only_never_replaces_playing_room(self):
        room = dict(id='7902350', name='Sample live room', live=True)
        dialog = self.select([room], target=-1)
        dialog.target.setCurrentIndex(0)
        QTest.mouseClick(dialog.add_button, Qt.LeftButton)
        self.assertIn('7902350', self.window.favorites)
        self.assertEqual([t.room['id'] for t in self.window.tiles[:4]], ['1', '2', '3', '4'])
        self.reload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
