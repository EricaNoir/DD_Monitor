"""Opt-in integrated GUI/network check using an offscreen window and silent VLC."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from studio.theme import stylesheet
from studio.runtime import configure_vlc
dll = configure_vlc(ROOT)
import vlc
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from studio.app import StudioWindow
from studio.state import load_credentials
app = QApplication([])
for name in ('msyh.ttc', 'msyhbd.ttc'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
app.setStyle('Fusion')
app.setStyleSheet(stylesheet())
instance = vlc.Instance('--quiet', '--vout=dummy', '--aout=dummy')
window = StudioWindow(ROOT, instance, demo=True)
window.closed.connect(app.quit)
window.cookies = load_credentials(ROOT)
for tile in window.tiles:
    tile.cookies = window.cookies
    tile.player.set_hwnd(0)  # An offscreen Qt winId is not a real HWND.
window.show()
result = {}
def start():
    window.add_rooms([{'id': '31294374', 'name': 'OA-LEAVE7', 'live': True, 'title': ''},
                      {'id': '4792266', 'name': 'OA-Guxue8', 'live': True, 'title': ''}], 0)
def finish():
    for tile in window.tiles[:2]:
        media = tile.player.get_media()
        stats = vlc.MediaStats()
        if media:
            media.get_stats(stats)
        result[f'frames_{tile.index}'] = stats.decoded_video
        result[f'messages_{tile.index}'] = len(tile.history)
        result[f'displayed_{tile.index}'] = bool(tile.chat_view.toPlainText())
    before = [len(t.history) for t in window.tiles[:2]]
    window.chat_toggle.click()
    app.processEvents()
    result['hidden'] = all(not t.chat_panel.isVisible() for t in window.tiles[:2])
    window.chat_toggle.click()
    app.processEvents()
    result['restored'] = all(t.chat_panel.isVisible() and len(t.history) >= n
                             for t, n in zip(window.tiles[:2], before))
    window.tiles[0].chat_toggle.click()
    result['independent_toggle'] = not window.tiles[0].chat_panel.isVisible() and window.tiles[1].chat_panel.isVisible()
    print('INTEGRATED_UI', result, flush=True)
    window.close()
QTimer.singleShot(100, start)
QTimer.singleShot(23000, finish)
app.exec()
QThreadPool.globalInstance().waitForDone(15000)
instance.release()
if not all(result.values()):
    raise SystemExit('Integrated UI smoke check failed')
