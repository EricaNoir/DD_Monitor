"""Opt-in integrated read-only check; never posts chat or spends batteries."""
import os
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from studio.runtime import configure_vlc
dll = configure_vlc(ROOT)
import requests
import vlc
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QApplication
from studio.app import StudioWindow
from studio.state import load_credentials

original = requests.Session.request
def reads_only(session, method, *args, **kwargs):
    if method.upper() not in ('GET', 'HEAD'):
        raise AssertionError('Read-only test prohibits sending')
    return original(session, method, *args, **kwargs)

if __name__ == '__main__':
    rid = sys.argv[1] if len(sys.argv) > 1 else '22603245'
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet((ROOT / 'studio/theme.qss').read_text(encoding='utf-8'))
    instance = vlc.Instance('--quiet', '--vout=dummy', '--aout=dummy')
    window = StudioWindow(ROOT, instance, demo=True)
    window.closed.connect(app.quit)
    tile = window.tiles[0]
    tile.player.set_hwnd(0)
    tile.cookies = load_credentials(ROOT)
    counts = Counter()
    observed = {'sc_with_remaining_time': 0, 'sc_overlay_visible': 0}
    def received(index, message):
        counts.update([message.get('kind', 'chat')])
        if message.get('kind') == 'sc' and float(message.get('end_time') or 0) > time.time():
            observed['sc_with_remaining_time'] += 1
            observed['sc_overlay_visible'] += int(tile.sc_overlay.isVisible())
    tile.chat_received.connect(received)
    def start():
        tile.set_room({'id': rid, 'name': '只读验证', 'live': True, 'title': ''})
    result = {}
    def finish():
        stats = vlc.MediaStats()
        media = tile.player.get_media()
        if media:
            media.get_stats(stats)
        tile.chat_tabs.setCurrentIndex(2)
        gift_filtered = all(m.get('kind') == 'gift' for m in tile.history if tile.accepts_chat(m))
        result.update(decoded_frames=stats.decoded_video, messages=dict(counts), **observed,
                      chat_limit=tile.composer.limit, gift_filter_correct=gift_filtered, posts=0)
        print(result, flush=True)
        window.close()
    window.show()
    with patch.object(requests.Session, 'request', reads_only):
        QTimer.singleShot(100, start)
        QTimer.singleShot(25000, finish)
        app.exec()
        QThreadPool.globalInstance().waitForDone(15000)
    instance.release()
    if not result.get('decoded_frames') or not counts or not result['gift_filter_correct']:
        raise SystemExit('No active stream/messages or failed filter; check selected room.')
    if observed['sc_with_remaining_time'] != observed['sc_overlay_visible']:
        raise SystemExit('Active SC did not show on the video overlay.')
