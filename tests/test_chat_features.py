import asyncio
import os
import unittest
from unittest.mock import Mock, patch, AsyncMock
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtWidgets import QApplication
from studio.composer import ChatComposer
from studio.services import BiliAPI, ChatWorker, parse_activity
from studio.sc_overlay import sc_interval, display_interval

COOKIES = {'SESSDATA': 'test-only', 'bili_jct': 'test-only'}
NAV = {'isLogin': True, 'mid': 99, 'wbi_img': {'img_url': 'https://i0.hdslb.com/' + 'a'*32 + '.png',
                                 'sub_url': 'https://i0.hdslb.com/' + 'b'*32 + '.png'}}
CONFIG = {'property': {'danmu': {'length': 80}}}


class ChatSendTests(unittest.TestCase):
    def setUp(self):
        self.api = BiliAPI(COOKIES)
        self.api.get = Mock(side_effect=[CONFIG, NAV])
        self.api.session.post = Mock(return_value=Mock(json=Mock(return_value={'code': 0, 'message': ''})))

    def test_plain_danmaku_payload_csrf_wbi_and_no_retry(self):
        self.assertEqual(self.api.send_chat('123', '测试 弹幕!'), {'uid':'99', 'text':'测试 弹幕!'})
        self.api.session.post.assert_called_once()
        args, kwargs = self.api.session.post.call_args
        self.assertTrue(args[0].endswith('/msg/send'))
        self.assertEqual((kwargs['data']['roomid'], kwargs['data']['msg']), (123, '测试 弹幕!'))
        self.assertEqual(kwargs['data']['csrf'], 'test-only')
        self.assertEqual(kwargs['params']['web_location'], '444.8')
        self.assertEqual(len(kwargs['params']['w_rid']), 32)
        self.assertFalse(kwargs['allow_redirects'])

    def test_server_limit_utf16_and_missing_auth_prevent_post(self):
        with self.assertRaisesRegex(ValueError, '80'):
            self.api.send_chat('123', '😀'*41)
        self.api.session.post.assert_not_called()
        with self.assertRaisesRegex(ValueError, '登录'):
            BiliAPI().send_chat(123, 'hello')

    def test_zero_code_with_rejection_text_is_not_success(self):
        self.api.session.post.return_value.json.return_value = {'code': 0, 'msg': '发送频率过快'}
        with self.assertRaisesRegex(ValueError, '频率'):
            self.api.send_chat(123, '测试')

    def test_timeout_never_retries(self):
        self.api.session.post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(ValueError, '未确认'):
            self.api.send_chat(123, '测试')
        self.api.session.post.assert_called_once()

    def test_sc_times_preserved_and_no_invented_duration(self):
        message = parse_activity({'cmd': 'SUPER_CHAT_MESSAGE', 'data': {'id': 1, 'start_time': 100,
                                 'end_time': 160, 'time': 60, 'message': 'hello'}})
        self.assertEqual(sc_interval(message), (100, 160))
        self.assertEqual(sc_interval({'start_time': 100, 'duration': 60}), (100, 160))
        self.assertIsNone(sc_interval({'duration': 60}))
        self.assertIsNone(sc_interval({'start_time': 100, 'end_time': float('nan')}))

    def test_preload_only_emits_still_active_sc(self):
        worker = ChatWorker(123, {})
        result = []
        worker.message.connect(result.append)
        response = Mock(status=200)
        response.json = AsyncMock(return_value={'code': 0, 'data': {'list': [
            {'id': 1, 'start_time': 50, 'end_time': 150}, {'id': 2, 'start_time': 1, 'end_time': 90}]}})
        context = AsyncMock()
        context.__aenter__.return_value = response
        session = Mock(get=Mock(return_value=context))
        with patch('studio.services.time.time', return_value=100):
            asyncio.run(worker.load_active_sc(session))
        self.assertEqual([m['id'] for m in result], ['1'])

    def test_overlay_short_duration_respects_reading_floor_and_late_arrival(self):
        message = {'start_time': 100, 'end_time': 400, 'text': '短留言'}
        self.assertEqual(display_interval(message, 100), (100, 130))
        self.assertEqual(display_interval(dict(message, end_time=160), 100), (100, 106))
        self.assertEqual(display_interval(dict(message, end_time=160, text='字' * 100), 100), (100, 122))
        self.assertEqual(display_interval(dict(message, end_time=160), 159), (159, 165))
        self.assertEqual(display_interval(message, 90), (100, 130))
        self.assertIsNone(display_interval(message, 400))


class ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.composer = ChatComposer()
        self.composer.set_room({'id': '123'}, COOKIES, load=False)
        self.composer.ready(self.composer.ticket, 80)
        self.composer.run_job = Mock()

    def tearDown(self):
        self.composer.close()

    def test_double_click_does_not_send_twice_and_failure_keeps_draft(self):
        c = self.composer
        c.input.setText('我的草稿')
        c.send()
        c.send()
        c.run_job.assert_called_once()
        c.limit_failed(c.ticket, '配置读取超时')
        self.assertTrue(c.sending)
        self.assertFalse(c.button.isEnabled())
        c.failed(c.ticket, '发送失败')
        self.assertEqual(c.input.text(), '我的草稿')
        self.assertTrue(c.button.isEnabled())

    def test_old_room_callback_cannot_clear_new_room_draft(self):
        c = self.composer
        old = c.ticket
        c.set_room({'id': '456'}, COOKIES, load=False)
        c.input.setText('新房间草稿')
        c.sent(old, '旧房间内容')
        self.assertEqual(c.input.text(), '新房间草稿')
        c.sent(c.ticket, '新房间草稿')
        self.assertEqual(c.input.text(), '')
        self.assertTrue(c.cooldown.isActive())

    def test_loading_shorter_limit_does_not_destroy_existing_draft(self):
        c = self.composer
        c.input.setText('字' * 60)
        c.ready(c.ticket, 20)
        self.assertEqual(c.input.text(), '字' * 60)
        self.assertFalse(c.button.isEnabled())
        self.assertIn('60/20', c.status_text)


if __name__ == '__main__':
    unittest.main()
