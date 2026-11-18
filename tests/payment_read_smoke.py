"""Opt-in authenticated READS only. Every HTTP mutation is blocked in this process."""
import os
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from studio.runtime import isolate_process
isolate_process(ROOT)
import requests
from PySide6.QtCore import QCoreApplication, QTimer
from studio.payments import PaymentAPI
from studio.services import ChatWorker
from studio.state import load_credentials

original = requests.Session.request
def reads_only(session, method, *args, **kwargs):
    if method.upper() not in ('GET', 'HEAD'):
        raise AssertionError('Payment smoke test prohibits HTTP mutations')
    return original(session, method, *args, **kwargs)

if __name__ == '__main__':
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 4792266
    cookies = load_credentials(ROOT)
    with patch.object(requests.Session, 'request', reads_only):
        api = PaymentAPI(cookies)
        panel = api.load_panel(rid)
        assert panel['uid'] and isinstance(panel['gold'], int)
        print({'logged_in': True, 'wallet_available': True, 'gifts': len(panel['gifts']),
               'sc_tiers': len(panel['sc'].get('price_configs') or [])}, flush=True)
        app = QCoreApplication([])
        counts = Counter()
        worker = ChatWorker(rid, cookies)
        worker.message.connect(lambda m: counts.update([m.get('kind', 'chat')]))
        worker.finished.connect(app.quit)
        worker.start()
        QTimer.singleShot(25000, worker.stop)
        app.exec()
        worker.wait(5000)
        print({'received_event_counts': dict(counts), 'payment_posts': 0}, flush=True)
        if not counts:
            raise SystemExit('No live events observed; rerun in an active room.')
