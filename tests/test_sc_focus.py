import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.app import StudioWindow


class SCFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = StudioWindow(Path(__file__).resolve().parents[1], demo=True,
                                   state_path=Path(self.temp.name) / 'state.json')
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        self.now = time.time()
        for i, tile in enumerate(self.window.tiles[:4]):
            tile.stack.setCurrentWidget(tile.surface)
            tile.receive_chat(None, self.message(str(i)))
        self.app.processEvents()

    def message(self, sid):
        return dict(kind='sc', id=sid, name='Local sample', price='30', text='Local SC',
                    start_time=self.now, end_time=self.now + 600)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def test_focus_button_never_hides_selected_overlay_or_restarts_lifetime(self):
        tile = self.window.tiles[1]
        overlay = tile.sc_overlay
        deadline = overlay.active['1'][1][1]
        events = []
        original = overlay.hideEvent
        overlay.hideEvent = lambda event: (events.append(event.type()), original(event))[-1]
        QTest.mouseClick(tile.focus_button, Qt.LeftButton)
        self.assertTrue(overlay.isVisible(), 'selected SC must not wait for its 250ms timer to return')
        self.app.processEvents()
        self.assertEqual(events, [], 'a selected live video and its overlay must not be hidden on focus')
        self.assertEqual(overlay.pos(), tile.stack.mapToGlobal(QPoint(8, 8)))
        self.assertTrue(all(not t.sc_overlay.isVisible() for t in self.window.tiles[:4] if t is not tile))
        self.assertEqual(overlay.active['1'][1][1], deadline)
        QTest.mouseClick(tile.focus_button, Qt.LeftButton)
        self.app.processEvents()
        self.assertEqual(events, [])
        self.assertTrue(all(t.sc_overlay.isVisible() for t in self.window.tiles[:4]))
        self.assertEqual(overlay.active['1'][1][1], deadline)

    def test_new_sc_in_focused_room_and_fullscreen_then_back_to_grid(self):
        tile = self.window.tiles[1]
        self.window.focus_tile(1)
        self.app.processEvents()
        tile.receive_chat(None, self.message('focused-new'))
        self.assertIn('focused-new', tile.sc_overlay.active)
        self.assertTrue(tile.sc_overlay.isVisible())
        self.window.toggle_fullscreen()
        self.app.processEvents()
        tile.sc_overlay.sync()
        self.assertTrue(tile.sc_overlay.isVisible())
        self.assertEqual(tile.sc_overlay.pos(), tile.stack.mapToGlobal(QPoint(8, 8)))
        self.window.exit_focus()
        self.app.processEvents()
        tile.sc_overlay.sync()
        self.assertTrue(tile.sc_overlay.isVisible())
        tile.sc_overlay.sync(self.now + 601)
        self.assertFalse(tile.sc_overlay.isVisible())
        self.window.focus_tile(1)
        self.app.processEvents()
        self.assertFalse(tile.sc_overlay.isVisible(), 'focus must not resurrect expired SC')


if __name__ == '__main__':
    unittest.main()
