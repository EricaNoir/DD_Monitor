"""Opt-in read-only following list/search and actual add-dialog preview."""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from studio.runtime import isolate_process
isolate_process(ROOT)
import requests
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtGui import QFontDatabase
from studio.app import StudioWindow
from studio.state import load_credentials
from studio.services import BiliAPI

original = requests.Session.request
def reads_only(session, method, *args, **kwargs):
    if method.upper() not in ('GET', 'HEAD'):
        raise AssertionError('Following smoke test prohibits writes')
    return original(session, method, *args, **kwargs)

if __name__ == '__main__':
    with patch.object(requests.Session, 'request', reads_only):
        cookies = load_credentials(ROOT)
        api = BiliAPI(cookies)
        first = api.followings()
        last_page = max(1, (first['total'] + 49) // 50)
        last = api.followings(page=last_page)
        print({'total_followings':first['total'], 'first_page':len(first['rooms']),
               'last_page':last_page,'last_page_count':len(last['rooms']), 'last_has_more':last['more']}, flush=True)
        assert not last['more']
        app = QApplication([])
        for name in ('msyh.ttc','msyhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / name))
        app.setStyle('Fusion')
        app.setStyleSheet((ROOT/'studio/theme.qss').read_text(encoding='utf-8'))
        window = StudioWindow(ROOT, demo=True)
        window.cookies = cookies
        window.avatars.enabled = True
        window.open_search(0)
        dialog = window.dialogs[-1]
        state = {'phase':0, 'deadline':time.monotonic()+25, 'ok':False}
        def check():
            if time.monotonic() > state['deadline']:
                dialog.close(); window.close(); app.quit(); return
            if not dialog.search_button.isEnabled():
                return
            if state['phase'] == 0 and dialog.results.count():
                # Allow cached/remote avatars to finish before taking preview.
                state['phase'] = 1
                QTimer.singleShot(2500, preview)
            elif state['phase'] == 2 and dialog.results.count():
                assert dialog.mode == 'following'
                assert all(dialog.results.item(i).data(256)['following'] for i in range(dialog.results.count()))
                dialog.grab().save(str(ROOT/'.qa/followings-search.png'))
                print({'following_search_results':dialog.results.count(),'favorite_avatars':dialog.favorite_strip.count(),'http_writes':0}, flush=True)
                state['ok'] = True
                dialog.close(); window.close(); app.quit()
        def preview():
            (ROOT/'.qa').mkdir(exist_ok=True)
            dialog.grab().save(str(ROOT/'.qa/favorites-followings.png'))
            dialog.input.setText('JDG')
            state['phase'] = 2
            dialog.search()
        timer = QTimer()
        timer.timeout.connect(check)
        timer.start(100)
        app.exec()
        QThreadPool.globalInstance().waitForDone(15000)
        if not state['ok']:
            raise SystemExit('Following dialog did not complete; check account or room search results.')
