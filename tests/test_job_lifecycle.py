import gc
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from studio.services import Job, JobSignals
from studio.state import save_json, load_state
from studio.app import StudioWindow


class JobLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(8)
        self.owner = QObject()

    def drain(self):
        self.assertTrue(self.pool.waitForDone(5000))
        gc.collect()
        for _ in range(4):
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def tearDown(self):
        self.drain()

    def test_all_results_survive_runnable_deletion_and_run_on_gui_thread(self):
        received, threads = [], []
        gui_thread = threading.get_ident()
        def receive(value):
            received.append(value)
            threads.append(threading.get_ident())
        for number in range(100):
            job = Job(lambda n=number: (n, threading.get_ident()), owner=self.owner)
            job.signals.done.connect(receive)
            self.pool.start(job)
        del job
        # Deliberately hold the GUI loop until every auto-deleted worker is gone.
        self.drain()
        self.assertEqual(sorted(n for n, _ in received), list(range(100)))
        self.assertTrue(all(worker != gui_thread for _, worker in received))
        self.assertEqual(set(threads), {gui_thread})
        self.assertFalse(self.app.findChildren(JobSignals))

    def test_errors_delivered_once_and_dispatcher_released(self):
        errors, results = [], []
        for exception in (requests.Timeout(), requests.ConnectionError(), ValueError('test error')):
            def fail(error=exception):
                raise error
            job = Job(fail, owner=self.owner)
            job.signals.done.connect(results.append)
            job.signals.error.connect(errors.append)
            self.pool.start(job)
        del job
        self.drain()
        self.assertFalse(results)
        self.assertCountEqual(errors, ['连接超时，请重试。', '网络连接失败，请检查网络后重试。', 'test error'])
        self.assertFalse(self.app.findChildren(JobSignals))

    def test_destroyed_widget_does_not_receive_late_callback(self):
        release = threading.Event()
        received = []
        job = Job(lambda: release.wait(3), owner=self.owner)
        job.signals.done.connect(received.append)
        self.pool.start(job)
        del job
        delete(self.owner)
        release.set()
        self.drain()
        self.assertEqual(received, [])
        self.assertFalse(self.app.findChildren(JobSignals))


class AtomicSaveTests(unittest.TestCase):
    def test_concurrent_writers_have_distinct_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'studio.json'
            save_json(path, {'marker': 'original'})
            barrier = threading.Barrier(8)
            original_replace = Path.replace
            temps = []
            lock = threading.Lock()
            def replace(temp, destination):
                temps.append(temp)
                barrier.wait(timeout=5)
                # Isolate temp collision from Windows destination sharing behavior.
                with lock:
                    return original_replace(temp, destination)
            with patch.object(Path, 'replace', replace), ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: save_json(path, {'marker': i}), range(8)))
            self.assertEqual(len(set(temps)), 8)
            self.assertIn(load_state(path)['marker'], range(8))
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_failed_replace_preserves_previous_config_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'studio.json'
            save_json(path, {'marker': 'original'})
            with patch.object(Path, 'replace', side_effect=PermissionError('test denial')):
                with self.assertRaises(PermissionError):
                    save_json(path, {'marker': 'new'})
            self.assertEqual(load_state(path)['marker'], 'original')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_save_failure_does_not_prevent_window_shutdown(self):
        app = QApplication.instance() or QApplication([])
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'studio.json'
            save_json(path, {'rooms': [], 'favorites': ['preserved']})
            before = path.read_bytes()
            window = StudioWindow(root, demo=True, state_path=path)
            window.demo = False
            closed = []
            window.closed.connect(lambda: closed.append(True))
            with patch('studio.app.save_json', side_effect=PermissionError('test denial')):
                with self.assertLogs(level='ERROR'):
                    self.assertTrue(window.close())
            self.assertTrue(window.closing)
            self.assertEqual(closed, [True])
            self.assertEqual(path.read_bytes(), before)
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
