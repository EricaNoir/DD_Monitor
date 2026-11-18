"""All payment writes are mocked. This suite never spends batteries."""
import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFontDatabase
from studio.payments import PaymentAPI, PaymentUnknown, Quote, battery, gift_limit
from studio.payment_dialog import PaymentDialog
from studio.services import parse_activity
from studio.chat import ChatView, message_html

ROOT = Path(__file__).resolve().parents[1]
ROOM = {'room_id': 123, 'uid': 456, 'area_id': 1, 'parent_area_id': 2}
GIFT = {'id': 7, 'name': '示例礼物', 'price': 100, 'max_send_limit': 10,
        'coin_type': 'gold', 'gift_type': 0, 'goods_id': 15}
SC = {'price_configs': [{'id': 8, 'level': 1, 'price': 30, 'limit': 40, 'second': 60}]}


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.api = PaymentAPI({'SESSDATA': 'test-only', 'bili_jct': 'test-only'})
        self.api.identity = Mock(return_value=99)
        self.api.room_details = Mock(return_value=ROOM)
        self.api.gifts = Mock(return_value=[GIFT])
        self.api.sc_config = Mock(return_value=SC)
        self.api.wallet = Mock(return_value=100000)
        self.api.session.post = Mock(return_value=Mock(json=Mock(return_value={'code': 0, 'data': {}})))

    def test_price_units_and_gift_limits(self):
        self.assertEqual([battery(n) for n in (10, 100, 1000, 30000)], ['0.1', '1', '10', '300'])
        self.assertEqual(gift_limit({'max_send_limit': -1}), 9999)
        self.assertEqual(self.api.prepare(123, 'gift', 7, 3).total, 300)
        self.assertEqual(self.api.prepare(123, 'sc', 8, text='你好').total, 30000)

    def test_gift_payload_uses_exact_recipient_quantity_and_gold(self):
        quote = self.api.prepare(123, 'gift', 7, 3)
        self.api.send(quote)
        self.api.session.post.assert_called_once()
        args, kwargs = self.api.session.post.call_args
        self.assertTrue(args[0].endswith('/gift/sendGoldMultiUser'))
        body = kwargs['data']
        self.assertEqual((body['uid'], body['ruid'], body['biz_id']), (99, 456, 123))
        self.assertEqual((body['gift_num'], body['price'], body['coin_type']), (3, 100, 'gold'))
        self.assertEqual(json.loads(body['receive_users']), [{'uid': 456}])
        self.assertEqual(body['csrf'], 'test-only')
        self.assertFalse(kwargs['allow_redirects'])

    def test_sc_payload_and_pending_receipt(self):
        self.api.session.post.return_value.json.return_value = {'code': 0, 'data': {'order_id': 'abc', 'status': 2}}
        result = self.api.send(self.api.prepare(123, 'sc', 8, text='测试留言'))
        body = self.api.session.post.call_args.kwargs['data']
        self.assertEqual((body['context_id'], body['ruid'], body['goods_id'], body['pay_gold']), (123, 456, 12, 30000))
        self.assertEqual(json.loads(body['biz_extra']), {'msg': '测试留言', 'level': 1, 'trans_key': '', 'biz_id': 8, 'sc_image_id': 0})
        self.assertEqual(result['order_id'], 'abc')
        self.assertIn('等待', result['text'])
        self.assertNotIn('已完成', result['text'])

    def test_changed_quote_never_posts(self):
        quote = self.api.prepare(123, 'gift', 7)
        for changed in (replace(quote, unit_gold=200), replace(quote, ruid=111), replace(quote, uid=111)):
            with patch.object(self.api, 'prepare', return_value=changed), self.assertRaises(ValueError):
                self.api.send(quote)
        self.api.session.post.assert_not_called()

    def test_insufficient_balance_and_unavailable_tiers(self):
        self.api.wallet.return_value = 0
        with self.assertRaisesRegex(ValueError, '余额不足'):
            self.api.prepare(123, 'gift', 7)
        self.api.sc_config.return_value = {'price_configs': [dict(SC['price_configs'][0], type_detail={'can_buy': False})]}
        with self.assertRaisesRegex(ValueError, '不可购买'):
            self.api.prepare(123, 'sc', 8, text='hello')
        self.api.session.post.assert_not_called()

    def test_sc_utf16_limit_ban_and_quantity(self):
        with self.assertRaises(ValueError):
            self.api.prepare(123, 'sc', 8, text='😀' * 21)
        with self.assertRaises(ValueError):
            self.api.prepare(123, 'gift', 7, 11)
        self.api.sc_config.return_value = dict(SC, user_ban_info={'limited': True})
        with self.assertRaises(ValueError):
            self.api.prepare(123, 'sc', 8, text='hi')

    def test_timeout_is_unknown_and_never_retries(self):
        self.api.session.post.side_effect = requests.Timeout()
        with self.assertRaises(PaymentUnknown):
            self.api.send(self.api.prepare(123, 'gift', 7))
        self.api.session.post.assert_called_once()

    def test_server_rejection_and_malformed_response(self):
        quote = self.api.prepare(123, 'gift', 7)
        self.api.session.post.return_value.json.return_value = {'code': -101, 'message': '登录失效'}
        with self.assertRaisesRegex(ValueError, '登录失效'):
            self.api.send(quote)
        self.api.session.post.return_value.json.return_value = []
        with self.assertRaises(PaymentUnknown):
            self.api.send(quote)

    def test_missing_csrf_stops_before_network(self):
        api = PaymentAPI({'SESSDATA': 'test-only'})
        with patch.object(api, 'get') as get, self.assertRaises(ValueError):
            api.identity()
        get.assert_not_called()

    def test_catalog_filters_special_gifts_and_uses_discount(self):
        api = PaymentAPI()
        cfg = {'list': [GIFT, dict(GIFT, id=9, gift_type=6), dict(GIFT, id=10)]}
        panel = {'room_gift_list': {'gold_list': [{'gift_id': 7}, {'gift_id': 9}]},
                 'discount_gift_list': [{'gift_id': 7, 'discount_price': 80}]}
        with patch.object(api, 'get', side_effect=[cfg, panel]):
            gifts = api.gifts(ROOM)
        self.assertEqual([(g['id'], g['price']) for g in gifts], [(7, 80)])


class ActivityTests(unittest.TestCase):
    def test_gift_and_sc_parse_escape_and_delete(self):
        gift = parse_activity({'cmd': 'SEND_GIFT', 'data': {'uid': 1, 'uname': '<b>', 'giftName': '花', 'num': 3, 'tid': 'x'}})
        self.assertEqual((gift['kind'], gift['quantity']), ('gift', 3))
        self.assertIn('&lt;b&gt;', message_html(gift))
        sc = parse_activity({'cmd': 'SUPER_CHAT_MESSAGE', 'data': {'id': 2, 'uinfo': {'base': {'name': '观众'}}, 'price': 30, 'message': '<script>\n谢谢'}})
        self.assertEqual(sc['name'], '观众')
        self.assertIn('SC ¥30', message_html(sc))
        self.assertNotIn('<script>', message_html(sc))
        self.assertEqual(parse_activity({'cmd': 'SUPER_CHAT_MESSAGE_DELETE', 'data': {'ids': [2]}})['ids'], ['2'])

    def test_skip_combo_and_malformed_events(self):
        for cmd in ('COMBO_SEND', 'SUPER_CHAT_MESSAGE_JPN'):
            self.assertIsNone(parse_activity({'cmd': cmd, 'data': {'id': 2}}))
        self.assertIsNone(parse_activity({'cmd': 'SEND_GIFT', 'data': {'num': 'bad'}}))
        self.assertIsNone(parse_activity({'cmd': 'SUPER_CHAT_MESSAGE', 'data': {'id': 1, 'user_info': 'bad'}}))
        # rnd is not a unique gift ID; separate purchases must not be deduplicated by it.
        self.assertEqual(parse_activity({'cmd': 'SEND_GIFT', 'data': {'num': 1, 'rnd': 4}})['event_id'], '')


class PaymentUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for font in ('msyh.ttc', 'msyhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / font))
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet((ROOT / 'studio/theme.qss').read_text(encoding='utf-8'))

    def setUp(self):
        self.dialog = PaymentDialog({'id': '123', 'name': '示例主播'}, {}, autoload=False)
        self.dialog.loaded({'uid': 99, 'gold': 100000, 'gifts': [GIFT], 'sc': SC})

    def tearDown(self):
        self.dialog.busy = False
        self.dialog.close()

    def test_cancel_and_double_click_cannot_post(self):
        d = self.dialog
        d.run_job = Mock()
        d.set_busy(True)
        d.prepare()
        d.run_job.assert_not_called()
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.Cancel):
            d.confirm(Quote('gift', 123, 456, 99, '礼物', 7, 100, 1))
        d.run_job.assert_not_called()
        self.assertFalse(d.busy)

    def test_balance_and_sc_text_control_send(self):
        d = self.dialog
        self.assertTrue(d.send_button.isEnabled())
        d.kind.setCurrentIndex(1)
        self.assertFalse(d.send_button.isEnabled())
        d.message.setPlainText('测试留言')
        self.assertTrue(d.send_button.isEnabled())
        d.panel['gold'] = 0
        d.update_total()
        self.assertFalse(d.send_button.isEnabled())
        self.assertIn('余额不足', d.total.text())

    def test_unknown_result_locks_resend(self):
        d = self.dialog
        d.sent({'unknown': '需要核对余额'})
        self.assertTrue(d.terminal)
        self.assertFalse(d.send_button.isEnabled())

    def test_chat_is_bounded_with_sc_and_render_previews(self):
        chat = ChatView()
        chat.resize(280, 460)
        sc = {'kind': 'sc', 'name': '示例观众', 'text': '示例留言，谢谢今天的直播！', 'price': '30'}
        for _ in range(520):
            chat.add_message(sc)
        self.assertLessEqual(chat.document().blockCount(), 500)
        chat.show_history([{'name': '示例观众', 'text': '以下为界面示例，并非真实送礼。'},
                           {'kind': 'gift', 'name': '示例观众', 'text': '赠送 示例礼物 × 3'}, sc])
        folder = ROOT / '.qa'
        folder.mkdir(exist_ok=True)
        chat.show()
        self.dialog.show()
        self.app.processEvents()
        chat.grab().save(str(folder / 'gift-sc-chat.png'))
        self.dialog.grab().save(str(folder / 'gift-panel.png'))
        self.dialog.kind.setCurrentIndex(1)
        self.dialog.message.setPlainText('示例留言，谢谢今天的直播！')
        self.app.processEvents()
        self.dialog.grab().save(str(folder / 'sc-panel.png'))
        chat.close()


if __name__ == '__main__':
    unittest.main()
