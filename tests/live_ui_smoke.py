"""Opt-in integrated GUI/network check using an offscreen window and silent VLC."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
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
app.setStyleSheet((ROOT / 'studio/theme.qss').read_text(encoding='utf-8'))
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
    window.add_rooms([{'id': '31294374', 'name': 'OA-LEAVE7', 'live': True, 'title': ''}], 0)
def finish():
    tile = window.tiles[0]
    media = tile.player.get_media()
    stats = vlc.MediaStats()
    if media:
        media.get_stats(stats)
    result['frames'] = stats.decoded_video
    print('PLAYER_STATUS', tile.status.text(), tile.player.get_state(),
          'PENDING', tile.request_pending, 'HAS_MEDIA', bool(media), flush=True)
    result['messages'] = len(tile.history)
    before = len(tile.history)
    window.chat_toggle.click()
    app.processEvents()
    result['hidden'] = not window.chat_panel.isVisible()
    window.chat_toggle.click()
    app.processEvents()
    result['restored'] = window.chat_panel.isVisible() and len(tile.history) >= before
    result['displayed'] = bool(window.chat_view.toPlainText())
    print('INTEGRATED_UI', result, flush=True)
    window.close()
QTimer.singleShot(100, start)
QTimer.singleShot(23000, finish)
app.exec()
QThreadPool.globalInstance().waitForDone(15000)
instance.release()
if not all(result.values()):
    raise SystemExit('Integrated UI smoke check failed')
