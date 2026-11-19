import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from studio.room_metrics import live_start, elapsed_text, audience_update
from studio.services import BiliAPI
from studio.player import PlayerTile


class MetricsTests(unittest.TestCase):
    def test_start_time_uses_beijing_time_and_survives_long_streams(self):
        self.assertEqual(live_start('2026-11-19 19:40:09'), 1795088409)
        self.assertEqual(elapsed_text(1000, 1000 + 25 * 3600 + 61), '25:01:01')
        self.assertEqual(elapsed_text(1000, 4661, True), '01:01')
        for value in (None, 0, '0000-00-00 00:00:00', 'nan', 'inf', 'bad'):
            self.assertEqual(elapsed_text(value, time.time()), '—')
        self.assertEqual(elapsed_text(2000, 1000), '—')

    def test_online_is_not_popularity_rank_or_cumulative_viewers(self):
        for command in ({'cmd': '_HEARTBEAT', 'data': {'popularity': 999}},
                        {'cmd': 'WATCHED_CHANGE', 'data': {'num': 999}},
                        {'cmd': 'ONLINE_RANK_COUNT', 'data': {'count': 999}}):
            self.assertIsNone(audience_update(command))
        for value in (-1, None, True, 'bad', 1.5):
            self.assertIsNone(audience_update({'cmd': 'ONLINE_RANK_COUNT', 'data': {'online_count': value}}))
        self.assertEqual(audience_update({'cmd': 'ONLINE_RANK_COUNT', 'data': {
            'count': 12, 'online_count': 10000, 'online_count_text': '1万+'}}),
            {'count': 10000, 'text': '1万+'})
        self.assertEqual(audience_update({'cmd': 'ONLINE_RANK_COUNT', 'data': {
            'online_count': 0, 'online_count_text': '<b>99</b>'}})['text'], '0')

    def test_batch_refresh_carries_actual_start(self):
        api = BiliAPI()
        with patch.object(api, 'get', return_value={'5': {'live_status': 1, 'live_time': 1795088409}}):
            room = api.room_statuses([{'id': '1', 'uid': 5, 'name': 'test'}])[0]
        self.assertEqual(room['live_start'], 1795088409)
        self.assertTrue(room['live'])


class MetricsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_counts_expire_and_never_leak_across_rooms_or_sessions(self):
        tile = PlayerTile(0, None, {})
        try:
            tile.room = {'id': '1', 'name': 'test', 'live': True, 'live_start': time.time() - 3600}
            current, retired = object(), object()
            tile.chat_worker = current
            tile.receive_audience(retired, {'count': 999, 'text': '999'})
            self.assertIsNone(tile.audience)
            tile.receive_audience(current, {'count': 0, 'text': '0'})
            self.assertIn('在线 0', tile.metrics.text())
            tile.audience_at -= 121
            tile.update_metrics()
            self.assertIn('在线 —', tile.metrics.text())
            tile.receive_audience(current, {'count': 20, 'text': '20'})
            tile.update_room_status({'id': '1', 'live': False})
            self.assertEqual(tile.metrics.text(), '未开播')
            self.assertIsNone(tile.audience)
            tile.receive_audience(current, {'count': 999, 'text': '999'})
            self.assertIsNone(tile.audience)
            tile.update_room_status({'id': '1', 'live': True, 'live_start': time.time()})
            self.assertIn('在线 —', tile.metrics.text())
            tile.receive_audience(current, {'count': 20, 'text': '20'})
            tile.update_room_status({'id': '1', 'live': True, 'live_start': time.time() + 1})
            self.assertIsNone(tile.audience)
            tile.chat_worker = None
            tile.clear()
            self.assertTrue(tile.metrics.isHidden())
        finally:
            tile.chat_worker = None
            tile.shutdown()

    def test_clock_continues_while_video_is_paused(self):
        tile = PlayerTile(0, None, {})
        try:
            tile.resize(900, 300)
            tile.room = {'id': '1', 'name': 'test', 'live': True, 'live_start': 1000}
            tile.paused = True
            with patch('studio.player.time.time', return_value=4661):
                tile.monitor_playback()
            self.assertIn('01:01:01', tile.metrics.text())
        finally:
            tile.shutdown()


if __name__ == '__main__':
    unittest.main()
