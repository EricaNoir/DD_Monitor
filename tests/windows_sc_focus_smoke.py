"""Opt-in Windows/VLC regression; local video and synthetic SC only."""
import ctypes
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.runtime import configure_vlc, create_vlc_instance
dll = configure_vlc(ROOT)
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.app import StudioWindow
from studio.theme import stylesheet


class HideObserver(QObject):
    def __init__(self, target):
        super().__init__(target)
        self.hidden = 0
        target.installEventFilter(self)

    def eventFilter(self, target, event):
        if event.type() == QEvent.Hide:
            self.hidden += 1
        return False


app = QApplication([])
app.setStyleSheet(stylesheet())
user = ctypes.WinDLL('user32')
user.IsWindowVisible.argtypes = [ctypes.c_void_p]
user.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user.GetWindow.restype = ctypes.c_void_p
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    fixture = folder / 'local-video.bmp'
    image = QImage(640, 360, QImage.Format_RGB32)
    image.fill(QColor('#174568'))
    assert image.save(str(fixture))
    instance = create_vlc_instance('--aout=dummy')
    window = StudioWindow(ROOT, demo=True, state_path=folder / 'studio.json')
    window.setWindowTitle('DD Monitor local SC display test')
    media = None
    try:
        window.resize(1200, 800)
        window.show()
        QTest.qWait(100)
        tile = window.tiles[1]
        tile.room = dict(id='local-fixture', name='Local sample', live=True)
        tile.player = instance.media_player_new()
        tile.player.set_hwnd(int(tile.surface.winId()))
        tile.player.video_set_mouse_input(False)
        tile.player.video_set_key_input(False)
        media = instance.media_new(str(fixture))
        media.add_option(':image-duration=60')
        tile.player.set_media(media)
        tile.player.play()
        tile.stack.setCurrentWidget(tile.surface)
        QTest.qWait(1500)
        now = time.time()
        message = dict(kind='sc', id='before', name='Local sample', text='Local SC display test',
                       price='30', start_time=now, end_time=now+600)
        tile.receive_chat(None, message)
        overlay = tile.sc_overlay

        def check(stage):
            QTest.qWait(100)
            assert tile.player.has_vout() > 0, stage + ': no native VLC output'
            assert overlay.isVisible() and user.IsWindowVisible(int(overlay.winId())), stage
            assert user.GetWindow(int(overlay.winId()), 4) == int(window.winId()), stage + ': owner'
            assert overlay.pos() == tile.stack.mapToGlobal(QPoint(8, 8)), stage + ': position'
            # The owned overlay must be above the window containing the native video.
            handle = user.GetWindow(int(window.winId()), 3)
            above = set()
            while handle and handle not in above:
                above.add(handle)
                handle = user.GetWindow(handle, 3)
            assert int(overlay.winId()) in above, stage + ': z-order'
            print('PASS:', stage, flush=True)

        check('grid with native VLC')
        observer = HideObserver(overlay)
        deadline = overlay.active['before'][1][1]
        for _ in range(3):
            QTest.mouseClick(tile.focus_button, Qt.LeftButton)
            assert overlay.isVisible() and observer.hidden == 0
            check('four-corner focus')
            QTest.mouseClick(tile.focus_button, Qt.LeftButton)
            assert overlay.isVisible() and observer.hidden == 0
            check('return to grid')
        assert overlay.active['before'][1][1] == deadline
        window.focus_tile(1)
        tile.receive_chat(None, dict(message, id='arrived-while-focused'))
        check('new SC while focused')
        window.toggle_fullscreen()
        check('F11 fullscreen')
        window.exit_focus()
        check('exit fullscreen and focus')
        overlay.sync(now + 601)
        assert not overlay.isVisible()
    finally:
        window.close()
        app.processEvents()
        if media is not None:
            media.release()
        instance.release()
