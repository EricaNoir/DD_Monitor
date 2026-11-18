import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QPoint, QMimeData
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from studio.theme import stylesheet
from studio.services import room_number, plain, safe_image, parse_chat, BiliAPI
from studio.chat import message_html
from studio.state import load_state, save_json
from studio.app import StudioWindow, SearchDialog
from studio.player import PlayerTile

ROOT = Path(__file__).resolve().parents[1]


class DataTests(unittest.TestCase):
    def test_favorite_status_batches_preserve_unknown_rooms(self):
        api = BiliAPI()
        rooms = [{'id': str(i), 'uid': i, 'name': str(i), 'live': True} for i in range(1, 53)]
        with patch.object(api, 'get', side_effect=[{'1': {'live_status': 0}, '2': {'live_status': 1}}, {}]) as get:
            updated = api.room_statuses(rooms)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(get.call_args_list[0].kwargs['uids[]']), 50)
        self.assertEqual([(r['id'], r['live']) for r in updated], [('1', False), ('2', True)])
        self.assertTrue(rooms[0]['live'])

    def test_room_input(self):
        self.assertEqual(room_number('https://live.bilibili.com/31294374?from=feed'), '31294374')
        self.assertEqual(room_number('4792266'), '4792266')
        self.assertIsNone(room_number('https://evil.example/31294374'))
        self.assertIsNone(room_number('OA-LEAVE7'))
        self.assertIsNone(room_number('0'))

    def test_search_and_chat_html_are_escaped(self):
        self.assertEqual(plain('<em>主播</em>&amp;伙伴'), '主播&伙伴')
        markup = message_html({'name': '<img src=x>', 'text': '<script>alert(1)</script>', 'medal': '<b>', 'level': '5'})
        self.assertNotIn('<script>', markup)
        self.assertNotIn('<img src=x>', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertEqual(safe_image('https://evil.example/image.png'), '')
        self.assertTrue(safe_image('//i0.hdslb.com/test.png').startswith('https:'))

    def test_raw_chat_keeps_sender_and_medal(self):
        info = [[0] * 16, '你好', [123, '昵称'], [21, '粉丝牌']]
        info[0][15] = {'extra': '{}'}
        message = parse_chat({'cmd': 'DANMU_MSG:4:0:2', 'info': info})
        self.assertEqual((message['name'], message['uid'], message['level']), ('昵称', '123', '21'))
        self.assertIsNone(parse_chat({'cmd': 'SEND_GIFT'}))

    def test_follow_state_distinguishes_unknown_from_not_following(self):
        rooms = [{'id': str(i), 'uid': i} for i in (1,2,3)]
        api = BiliAPI()
        with patch.object(api, 'get') as get:
            result = api.with_follow_state({'rooms': rooms, 'more': False})
            get.assert_not_called()
            self.assertEqual(result['follow_state'], 'login_required')
            self.assertTrue(all(r['following'] is None for r in rooms))
        api = BiliAPI({'SESSDATA': 'test-only'})
        with patch.object(api, 'get', side_effect=[{'isLogin': True}, {'1': {'attribute': 6}, '2': {'attribute': 0}}]):
            result = api.with_follow_state({'rooms': rooms, 'more': False})
            self.assertEqual([r['following'] for r in rooms], [True, False, None])
        with patch.object(api, 'get', side_effect=ValueError('unavailable')):
            result = api.with_follow_state({'rooms': rooms, 'more': False})
            self.assertEqual(result['follow_state'], 'unavailable')
            self.assertTrue(all(r['following'] is None for r in rooms))

    def test_medal_has_italic_color_without_background(self):
        markup = message_html({'name':'观众','text':'消息','medal':'粉丝牌','level':'21'})
        self.assertIn('font-style:italic', markup)
        self.assertNotIn('background-color', markup)
        self.assertIn('粉丝牌 21</span>', markup)


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen Windows plugin does not enumerate system fonts.
        for name in ('msyh.ttc', 'msyhbd.ttc'):
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(stylesheet())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'studio.json'
        self.window = StudioWindow(ROOT, demo=True, state_path=self.path)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_component_heights_align_and_sidebar_has_no_left_gutter(self):
        w = self.window
        self.assertEqual(w.layout_choice.height(), 32)
        self.assertEqual(w.controls_toggle.height(), 32)
        self.assertEqual(w.library.mapTo(w.centralWidget(), QPoint()).x(), 0)
        tile = w.tiles[0]
        self.assertEqual(tile.quality.height(), 28)
        self.assertEqual(tile.play_button.height(), 28)
        self.assertEqual(tile.composer.input.height(), tile.composer.button.height())
        dialog = SearchDialog({}, 0, 4, w)
        dialog.tabs.setCurrentIndex(1)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.follow_filter.height(), 32)
        self.assertEqual(dialog.input.height(), dialog.search_button.height())
        dialog.close()

    def test_account_status_ignores_stale_results(self):
        w = self.window
        w.cookies = {}
        w.refresh_account_status()
        ticket = w.account_ticket
        self.assertIn('未登录', w.account.text())
        w.account_status_ready(ticket - 1, {'isLogin': True, 'uname': '旧账号'})
        self.assertIn('未登录', w.account.text())
        w.account_status_ready(ticket, {'isLogin': True, 'uname': '示例账号'})
        self.assertIn('示例账号', w.account.text())
        w.account_status_failed(ticket, '登录失效 (-101)')
        self.assertIn('已过期', w.account.text())

    def test_status_refresh_sorts_without_reloading_players(self):
        w = self.window
        w.rooms = {str(i): {'id': str(i), 'uid': i, 'name': str(i), 'live': False} for i in range(1, 4)}
        w.favorites = {'1', '2'}
        dialog = SearchDialog({}, 0, 4, w)
        w.dialogs.append(dialog)
        dialog.show()
        dialog.favorite_strip.item(1).setCheckState(Qt.Checked)
        before = [t.generation for t in w.tiles]
        w.favorite_poll_pending = True
        w.favorite_status_ready([dict(w.rooms['2'], live=True), dict(w.rooms['3'], live=True)])
        self.assertFalse(w.favorite_poll_pending)
        self.assertEqual(w.room_list.item(0).data(Qt.UserRole)['id'], '2')
        self.assertEqual(dialog.favorite_strip.item(0).data(Qt.UserRole)['id'], '2')
        self.assertEqual(dialog.favorite_strip.item(0).checkState(), Qt.Checked)
        self.assertFalse(w.rooms['3']['live'])
        self.assertEqual(before, [t.generation for t in w.tiles])
        w.favorite_status_failed('network')
        self.assertTrue(w.rooms['2']['live'])
        self.assertEqual(w.favorite_timer.interval(), 30000)
        w.demo = False
        with patch('studio.app.QThreadPool') as pool:
            w.refresh_favorite_status()
            w.refresh_favorite_status()
            pool.globalInstance.return_value.start.assert_called_once()
        w.demo = True
        dialog.close()

    def test_avatar_drag_works_without_selection_and_does_not_click(self):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        w = self.window
        room = {'id': '88', 'uid': 88, 'name': '拖拽示例'}
        w.rooms, w.favorites = {'88': room}, {'88'}
        w.refresh_library()
        rail = w.room_list
        point = rail.visualItemRect(rail.item(0)).center()
        clicked = Mock()
        rail.itemClicked.connect(clicked)
        w.tiles[0].set_room = Mock()
        with patch('studio.sidebar.QDrag') as drag:
            QTest.mousePress(rail.viewport(), Qt.LeftButton, pos=point)
            small = QMouseEvent(QEvent.MouseMove, QPointF(point + QPoint(1, 0)), QPointF(point + QPoint(1, 0)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
            rail.mouseMoveEvent(small)
            drag.assert_not_called()
            move = QMouseEvent(QEvent.MouseMove, QPointF(point + QPoint(25, 0)), QPointF(point + QPoint(25, 0)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
            rail.mouseMoveEvent(move)
            mime = drag.return_value.setMimeData.call_args.args[0]
            event = SimpleNamespace(mimeData=lambda: mime, acceptProposedAction=Mock())
            w.tiles[0].dropEvent(event)
            QTest.mouseRelease(rail.viewport(), Qt.LeftButton, pos=point)
        w.tiles[0].set_room.assert_called_once_with(room)
        clicked.assert_not_called()

    def test_first_sc_after_room_clear_keeps_bubble_inside_view(self):
        from studio.chat import ChatView
        view = ChatView()
        view.resize(185, 270)
        view.show()
        view.add_message({'name': '旧房间', 'text': '消息'})
        view.clear()
        view.add_message({'kind': 'sc', 'price': '2', 'name': 'Med1umWe11_Yan', 'text': '胖宝宝胖宝宝我来了'})
        view.add_message({'kind': 'gift', 'name': '示例观众', 'text': '赠送 粉丝团灯牌 × 1'})
        self.app.processEvents()
        first = view.document().begin()
        rect = view.document().documentLayout().blockBoundingRect(first)
        self.assertGreaterEqual(rect.top(), 8)
        self.assertEqual(view.document().rootFrame().frameFormat().topMargin(), 10)
        self.assertNotIn(' · ', view.toPlainText())
        from PySide6.QtGui import QColor
        from studio.theme import COLORS
        rendered = view.viewport().grab().toImage()
        self.assertEqual(rendered.pixelColor(rendered.width() - 14, int(rect.top()) + 5).name(),
                         QColor(COLORS['sc_surface']).name())
        folder = ROOT / '.qa'
        folder.mkdir(exist_ok=True)
        view.grab().save(str(folder / 'fresh-room-sc-gift.png'))
        view.close()

    def test_live_sc_spacing_matches_history_and_gift_icon_is_local(self):
        from studio.chat import ChatView
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument
        live, history = ChatView(), ChatView()
        messages = [{'name': '观众', 'text': '普通聊天'},
                    {'kind': 'sc', 'price': '2', 'name': '示例观众', 'text': '这是一条比较长的留言，用来检查换行与气泡内边距。'},
                    {'kind': 'sc', 'price': '2', 'name': '另一位观众', 'text': '喵'},
                    {'name': '观众', 'text': '下一条普通聊天'},
                    {'kind': 'gift', 'name': '示例观众', 'text': '赠送 粉丝团灯牌 × 1'}]
        for view in (live, history):
            view.resize(190, 440)
            view.show()
        for message in messages:
            live.add_message(message)
        history.show_history(messages)
        self.app.processEvents()
        a, b = live.document().begin(), history.document().begin()
        while a.isValid() and b.isValid():
            self.assertEqual(a.blockFormat().properties(), b.blockFormat().properties())
            self.assertAlmostEqual(live.document().documentLayout().blockBoundingRect(a).height(),
                                   history.document().documentLayout().blockBoundingRect(b).height(), delta=1)
            a, b = a.next(), b.next()
        with patch.object(live.network, 'get') as get:
            glyph = live.loadResource(QTextDocument.ImageResource, QUrl('studio-icon:gift'))
            self.assertFalse(glyph.isNull())
            get.assert_not_called()
        self.assertNotIn('礼物 ·', live.toPlainText())
        folder = ROOT / '.qa'
        folder.mkdir(exist_ok=True)
        live.grab().save(str(folder / 'live-sc-spacing.png'))
        history.grab().save(str(folder / 'history-sc-spacing.png'))
        live.close()
        history.close()

    def test_send_scrolls_to_latest_without_moving_chat_or_input(self):
        tile = self.window.tiles[0]
        c = tile.composer
        c.set_room({'id': '123'}, {'SESSDATA': 'test', 'bili_jct': 'test'}, load=False)
        c.ready(c.ticket, 80)
        c.run_job = Mock()
        tile.chat_status = '已连接'
        tile.refresh_chat_status()
        for i in range(120):
            tile.receive_chat(None, {'uid': '1', 'name': '观众', 'text': f'历史消息 {i}'})
        self.app.processEvents()
        tile.chat_view.follow = False
        bar = tile.chat_view.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        def positions():
            return [(w.mapTo(tile, QPoint()), w.size()) for w in (c.input, tile.chat_view, c)]
        before = positions()
        c.input.setText('我的消息')
        c.send()
        self.app.processEvents()
        self.assertEqual(positions(), before)
        self.assertIn('发送中…', c.input.toolTip())
        c.sent(c.ticket, '我的消息', '99')
        self.app.processEvents()
        self.assertEqual(positions(), before)
        self.assertEqual(c.status_text, '')
        self.assertEqual(c.input.toolTip(), '')
        self.assertEqual(bar.value(), bar.maximum())
        bar.setValue(0)
        tile.receive_chat(None, {'uid': '99', 'name': '我', 'text': '我的消息'})
        self.app.processEvents()
        self.assertEqual(bar.value(), bar.maximum())
        self.assertFalse(tile.chat_view.follow)
        c.failed(c.ticket, '发送失败，请稍后重试。' * 10 + '\n网络错误')
        self.app.processEvents()
        self.assertEqual(positions(), before)
        self.assertIn('网络错误', c.input.toolTip())
        c.status('')
        folder = ROOT / '.qa'
        folder.mkdir(exist_ok=True)
        tile.chat_panel.grab().save(str(folder / 'chat-send-stable.png'))

    def test_protobuf_gifts_reach_chat_and_batch_is_not_dropped(self):
        from studio.services import parse_messages
        from test_gift_proto import broadcast
        tile = self.window.tiles[0]
        messages = parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': broadcast()}})
        for message in messages + messages:
            tile.receive_chat(None, message)
        self.assertEqual(len(tile.history), 2)
        text = tile.chat_view.toPlainText()
        self.assertIn('示例赠送者', text)
        self.assertIn('小花花 × 3', text)
        self.assertIn('赞 × 2', text)

    def test_chat_tabs_filter_history_and_new_messages_and_persist(self):
        tile = self.window.tiles[0]
        for message in ({'name': '观众', 'text': '普通聊天'},
                        {'kind': 'gift', 'name': '观众', 'text': '赠送礼物'},
                        {'kind': 'sc', 'id': '1', 'name': '观众', 'text': '醒目留言', 'price': '30'}):
            tile.receive_chat(None, message)
        tile.chat_tabs.setCurrentIndex(2)
        self.assertIn('赠送礼物', tile.chat_view.toPlainText())
        self.assertNotIn('普通聊天', tile.chat_view.toPlainText())
        self.window.toggle_names(False)
        self.assertNotIn('醒目留言', tile.chat_view.toPlainText())
        tile.receive_chat(None, {'name': '观众', 'text': '新的聊天'})
        self.assertNotIn('新的聊天', tile.chat_view.toPlainText())
        tile.chat_tabs.setCurrentIndex(1)
        self.assertIn('新的聊天', tile.chat_view.toPlainText())
        self.assertNotIn('赠送礼物', tile.chat_view.toPlainText())
        self.window.demo = False
        self.window.save()
        self.assertEqual(load_state(self.path)['slot_settings']['0']['chat_filter'], 1)

    def test_sc_overlay_uses_remaining_server_time_and_expires_independently(self):
        import time
        now = time.time()
        tile = self.window.tiles[0]
        message = {'kind': 'sc', 'id': 'timer', 'event_id': 'sc:timer', 'name': '示例观众',
                   'text': '这是 SC 浮层预览，感谢今天的直播！', 'price': '30',
                   'start_time': now - 50, 'end_time': now + 10, 'duration': 60}
        tile.chat_tabs.setCurrentIndex(1)
        tile.receive_chat(None, message)
        self.app.processEvents()
        overlay = tile.sc_overlay
        self.assertTrue(overlay.isVisible())
        self.assertNotIn('SC 浮层', tile.chat_view.toPlainText())
        self.assertLessEqual(overlay.cards[0][2].value(), 167)
        self.assertTrue(overlay.windowFlags() & Qt.WindowTransparentForInput)
        tile.chat_toggle.setChecked(False)
        overlay.sync(now + 1)
        self.assertTrue(overlay.isVisible())
        tile.chat_toggle.setChecked(True)
        tile.chat_tabs.setCurrentIndex(0)
        self.app.processEvents()
        overlay.sync(now + 1)
        folder = ROOT / '.qa'
        folder.mkdir(exist_ok=True)
        overlay.grab().save(str(folder / 'sc-overlay.png'))
        tile.grab().save(str(folder / 'chat-tabs-composer.png'))
        overlay.sync(now + 11)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(overlay.active)
        self.assertIn('SC 浮层', tile.chat_view.toPlainText())

    def test_sc_overlay_delete_and_clear_do_not_leave_floating_windows(self):
        import time
        now = time.time()
        tile = self.window.tiles[0]
        message = {'kind': 'sc', 'id': 'delete', 'name': '观众', 'text': 'SC', 'price': '30',
                   'start_time': now - 5, 'end_time': now + 60}
        tile.receive_chat(None, message)
        tile.receive_chat(None, {'kind': 'sc_delete', 'ids': ['delete']})
        self.assertFalse(tile.sc_overlay.active)
        tile.receive_chat(None, dict(message, id='other'))
        tile.clear()
        self.assertFalse(tile.sc_overlay.isVisible())
        self.assertFalse(tile.sc_overlay.active)

    def test_sc_overlay_hidden_window_still_expires_and_future_sc_waits(self):
        import time
        now = time.time()
        overlay = self.window.tiles[0].sc_overlay
        message = {'id': 'future', 'name': '观众', 'text': 'SC', 'price': '30',
                   'start_time': now + 10, 'end_time': now + 70}
        overlay.add_message(message, now)
        self.assertFalse(overlay.isVisible())
        overlay.sync(now + 11)
        self.assertTrue(overlay.isVisible())
        self.window.hide()
        overlay.sync(now + 20)
        self.assertFalse(overlay.isVisible())
        self.assertTrue(overlay.active)
        overlay.sync(now + 71)
        self.window.show()
        self.app.processEvents()
        self.assertFalse(overlay.active)
        self.assertFalse(overlay.isVisible())

    def test_activity_is_per_room_deduplicated_and_sc_delete_is_applied(self):
        tile, other = self.window.tiles[:2]
        event = {'kind': 'sc', 'id': '42', 'event_id': 'sc:42', 'name': '观众', 'text': '醒目留言', 'price': '30'}
        tile.receive_chat(None, event)
        tile.receive_chat(None, event)
        self.assertEqual(len(tile.history), 1)
        self.assertEqual(len(other.history), 0)
        tile.chat_toggle.setChecked(False)
        tile.receive_chat(None, {'kind': 'gift', 'name': '观众', 'text': '赠送 花 × 1', 'event_id': 'gift:1:2'})
        tile.chat_toggle.setChecked(True)
        self.assertIn('花', tile.chat_view.toPlainText())
        tile.receive_chat(None, {'kind': 'sc_delete', 'ids': ['42']})
        tile.receive_chat(None, event)
        self.assertEqual(len(tile.history), 1)
        self.assertNotIn('醒目留言', tile.chat_view.toPlainText())
        tile.clear()
        self.assertFalse(tile.gift_button.isEnabled())
        self.assertFalse(tile.deleted_sc)

    def test_chat_toggle_keeps_history_and_restores_width(self):
        w = self.window
        tile = w.tiles[0]
        tile.receive_chat(None, {'name': '观众', 'text': '固定聊天列表'})
        width = tile.chat_panel.width()
        original_video_width = tile.stack.width()
        w.chat_toggle.click()
        self.app.processEvents()
        self.assertFalse(tile.chat_panel.isVisible())
        self.assertGreater(tile.stack.width(), original_video_width)
        w.chat_toggle.click()
        self.app.processEvents()
        self.assertTrue(tile.chat_panel.isVisible())
        self.assertIn('固定聊天列表', tile.chat_view.toPlainText())
        self.assertLess(abs(tile.chat_panel.width() - width), 20)

    def test_independent_panels_and_chat_switch(self):
        w = self.window
        a, b = w.tiles[:2]
        a.receive_chat(None, {'name': 'A', 'text': '房间一'})
        b.receive_chat(None, {'name': 'B', 'text': '房间二'})
        w.select_tile(1)
        self.assertIn('房间一', a.chat_view.toPlainText())
        self.assertNotIn('房间二', a.chat_view.toPlainText())
        self.assertIn('房间二', b.chat_view.toPlainText())
        self.assertNotIn('房间一', b.chat_view.toPlainText())
        self.assertTrue(a.chat_panel.isVisible() and b.chat_panel.isVisible())
        a.chat_toggle.click()
        self.assertFalse(a.chat_panel.isVisible())
        self.assertTrue(b.chat_panel.isVisible())
        w.controls_toggle.click()
        self.assertTrue(w.library.isVisible())
        self.assertLessEqual(w.library.width(), 56)
        self.assertFalse(w.global_controls.isVisible())
        self.assertTrue(b.chat_panel.isVisible())
        self.assertFalse(a.controls.isVisible())
        w.controls_toggle.click()
        self.assertTrue(a.controls.isVisible())

    def test_individual_chat_settings_persist(self):
        w = self.window
        w.demo = False
        w.tiles[0].chat_width = 215
        w.tiles[0].chat_toggle.setChecked(False)
        w.save()
        saved = load_state(self.path)
        self.assertFalse(saved['slot_settings']['0']['chat_visible'])
        self.assertTrue(saved['slot_settings']['1']['chat_visible'])
        again = StudioWindow(ROOT, demo=True, state_path=self.path)
        again.show()
        self.app.processEvents()
        self.assertFalse(again.tiles[0].chat_panel.isVisible())
        self.assertTrue(again.tiles[1].chat_panel.isVisible())
        again.close()

    def test_followings_live_first_across_pages_preserves_checks(self):
        dialog = SearchDialog({}, 0, 4, self.window)
        def room(rid, live):
            return {'id': rid, 'name': rid, 'live': live, 'following': True}
        def order():
            return [item.data(Qt.UserRole)['id'] for item in dialog.items(dialog.results)]
        dialog.show_results(dialog.ticket, {'rooms': [room('1', False), room('2', True)],
                                           'more': True, 'follow_state': 'ok'})
        self.assertEqual(order(), ['2', '1'])
        dialog.results.item(1).setCheckState(Qt.Checked)
        dialog.query = '关注内搜索'
        dialog.show_results(dialog.ticket, {'rooms': [room('3', False), room('4', True)],
                                           'more': False, 'follow_state': 'ok', 'page': 2})
        self.assertEqual(order(), ['2', '4', '1', '3'])
        self.assertEqual([r['id'] for r in dialog.selected_rooms()], ['1'])
        dialog.close()

    def test_search_selection_and_stale_response(self):
        dialog = SearchDialog({}, 0, 4, self.window)
        dialog.mode = 'search'
        dialog.ticket = 2
        room = {'id': '123', 'name': '匹配主播', 'title': '游戏', 'live': True}
        dialog.show_results(1, {'rooms': [room], 'more': False})
        self.assertEqual(dialog.results.count(), 0)
        dialog.show_results(2, {'rooms': [room], 'more': True})
        self.assertEqual(dialog.results.count(), 1)
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.results.item(0).setCheckState(Qt.Checked)
        self.assertTrue(dialog.add_button.isEnabled())
        added = []
        dialog.rooms_added.connect(lambda rooms, target: added.append((rooms, target)))
        dialog.add_selected()
        self.assertEqual(added[0], ([room], 0))

    def test_settings_and_cleared_slots_persist(self):
        w = self.window
        w.demo = False
        w.chat_toggle.setChecked(False)
        w.chat_font.setValue(17)
        w.save()
        saved = load_state(self.path)
        self.assertFalse(saved['chat_visible'])
        self.assertNotIn('library_visible', saved)
        self.assertEqual(saved['chat_font'], 17)
        self.assertEqual(saved['slots'], [None] * 9)

    def test_hidden_players_suspend_and_focus_returns(self):
        w = self.window
        w.focus_tile(2)
        self.assertFalse(w.tiles[2].suspended)
        self.assertTrue(w.tiles[0].suspended)
        w.exit_focus()
        self.assertFalse(w.tiles[0].suspended)
        self.assertTrue(w.tiles[4].suspended)

    def test_chat_font_is_not_overridden_by_global_theme(self):
        self.window.chat_font.setValue(21)
        self.app.processEvents()
        self.assertEqual(self.window.tiles[0].chat_view.font().pixelSize(), 21)

    def test_stale_stream_cannot_replace_cleared_room(self):
        tile = self.window.tiles[0]
        tile.generation = 10
        tile.room = {'id': '1', 'name': '旧房间'}
        tile.clear()
        tile.got_stream(10, {'room': {'id': '2', 'name': '过期结果'}, 'url': None})
        self.assertIsNone(tile.room)

    def test_close_button_notifies_and_clears_chat(self):
        tile = self.window.tiles[0]
        tile.room = {'id': '1', 'name': '主播'}
        tile.history.append({'name': '观众', 'text': '旧消息'})
        self.window.select_tile(0)
        changed = []
        tile.changed.connect(lambda: changed.append(True))
        self.window.controls_toggle.setChecked(False)
        self.app.processEvents()
        self.assertTrue(tile.remove.isVisible())
        self.assertLess(tile.remove.y(), tile.content_splitter.y())
        self.assertGreater(tile.remove.x(), tile.width() - 60)
        tile.remove.click()
        self.assertTrue(changed)
        self.assertIsNone(tile.room)
        self.assertEqual(tile.chat_view.toPlainText(), '')

    def test_single_toolbar_and_narrow_window_controls(self):
        tile = PlayerTile(0, None, {})
        try:
            tile.resize(480, 300)
            tile.show()
            self.app.processEvents()
            self.assertEqual(tile.toolbar.height(), 36)
            self.assertGreaterEqual(tile.content_splitter.height(), tile.height() - 40)
            self.assertFalse(tile.status.isVisible())
            self.assertTrue(tile.more.isVisible())
            self.assertFalse(tile.volume.isVisible())
            self.assertTrue(tile.play_button.isVisible() and tile.mute_button.isVisible())
            self.assertTrue(tile.remove.isVisible())
            tile.menu_volume.setValue(67)
            self.assertEqual(tile.volume.value(), 67)
            tile.volume.setValue(19)
            self.assertEqual(tile.menu_volume.value(), 19)
            with patch.object(tile, 'reload') as reload:
                tile.retry_action.trigger()
                reload.assert_called_once_with(reconnect_chat=True)
            tile.resize(900, 400)
            self.app.processEvents()
            self.assertTrue(tile.volume.isVisible() and tile.retry.isVisible())
            self.assertFalse(tile.more.isVisible())
            self.assertEqual(tile.toolbar.height(), 36)
        finally:
            tile.shutdown()
            tile.close()

    def test_fixed_avatar_rail_focuses_without_reload_and_ignores_old_width(self):
        w = self.window
        room = {'id': '123', 'name': '测试主播', 'live': True, 'title': '直播标题'}
        w.rooms = {'123': room}
        w.favorites = {'123'}
        w.tiles[1].room = room
        w.refresh_library()
        self.assertEqual(w.library.width(), 42)
        self.assertTrue(w.library_add.isVisible())
        self.assertFalse(hasattr(w, 'library_toggle'))
        self.assertFalse(hasattr(w, 'splitter'))
        self.assertIn('测试主播', w.room_list.item(0).toolTip())
        generation = w.tiles[1].generation
        w.room_list.itemClicked.emit(w.room_list.item(0))
        self.assertEqual(w.active, 1)
        self.assertEqual(w.tiles[1].generation, generation)
        self.path.write_text(json.dumps({'library_visible': True, 'splitter': [400, 500]}), encoding='utf-8')
        again = StudioWindow(ROOT, demo=True, state_path=self.path)
        again.show()
        self.app.processEvents()
        self.assertEqual(again.library.width(), 42)
        again.close()

    def test_preview(self):
        w = self.window
        w.rooms = {str(i): {'id': str(i), 'name': name, 'title': '预览内容', 'live': i != 3}
                   for i, name in enumerate(['OA-LEAVE7', 'OA-Guxue8', 'OA-SHY', '收藏的直播间'], 1)}
        w.favorites = set(w.rooms)
        w.refresh_library()
        for tile, room in zip(w.tiles, w.rooms.values()):
            tile.room = room
            tile.update_title()
            tile.empty_title.setText('直播画面')
            tile.empty_hint.setText('界面预览 · 示例聊天数据')
        for tile in w.tiles[:4]:
            tile.empty_add.hide()
            tile.chat_status = '已连接'
            tile.refresh_chat_status()
            for i in range(12):
                tile.receive_chat(None, {'name': ['山间的风', '一只观众', '周末看直播'][i % 3],
                    'text': [f'这里是 {tile.room["name"]} 的聊天', '这个操作可以！', '每个房间的消息分开看'][i % 3],
                    'medal': '观众牌' if i % 3 == 0 else '', 'level': '21'})
        w.select_tile(0)
        w.notice.setText('界面预览 · 示例聊天数据，不代表真实直播内容')
        self.app.processEvents()
        output = ROOT / '.qa'
        output.mkdir(exist_ok=True)
        self.assertTrue(w.grab().save(str(output / 'studio-preview.png')))
        w.chat_toggle.click()
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(output / 'studio-chat-hidden.png')))

    def test_click_fills_empty_and_full_grid_never_replaces_but_drag_can(self):
        w = self.window
        room = {'id':'88','name':'新增主播','title':'测试','uid':88}
        w.rooms = {'88':room}
        w.favorites = {'88'}
        w.refresh_library()
        for i,tile in enumerate(w.tiles[:4]):
            tile.room = {'id':str(i),'name':str(i)}
            tile.set_room = Mock()
        w.tiles[2].room = None
        w.activate_library(w.room_list.item(0))
        w.tiles[2].set_room.assert_called_once_with(room)
        w.tiles[2].set_room.reset_mock()
        w.tiles[2].room = {'id':'2','name':'已有主播'}
        w.activate_library(w.room_list.item(0))
        self.assertTrue(all(t.set_room.call_count == 0 for t in w.tiles[:4]))
        mime = QMimeData()
        mime.setData('application/x-dd-room',json.dumps(room).encode())
        event = SimpleNamespace(mimeData=lambda:mime,acceptProposedAction=Mock())
        w.tiles[0].dropEvent(event)
        w.tiles[0].set_room.assert_called_once_with(room)
        self.assertNotIn('点击',w.room_list.item(0).toolTip())

    def test_tile_drop_swaps_live_widgets_and_persists_order(self):
        w = self.window
        a, b = w.tiles[0], w.tiles[3]
        for tile, rid in ((a, '101'), (b, '102')):
            tile.room = {'id': rid, 'name': rid, 'title': '标题'}
            w.rooms[rid] = tile.room
            tile.update_title()
            tile.receive_chat(None, {'name': rid, 'text': '聊天记录' + rid})
        a.volume.setValue(17)
        a.paused = True
        a.chat_toggle.setChecked(False)
        handle = int(a.surface.winId())
        w.select_tile(0)
        w.demo = False
        mime = QMimeData()
        mime.setData('application/x-dd-tile', b'0')
        event = SimpleNamespace(mimeData=lambda: mime, source=lambda: a, acceptProposedAction=Mock())
        with patch.object(a, 'reload') as reload_a, patch.object(b, 'reload') as reload_b:
            b.dropEvent(event)
            reload_a.assert_not_called()
            reload_b.assert_not_called()
        event.acceptProposedAction.assert_called_once()
        self.assertIs(w.tiles[3], a)
        self.assertIs(w.tiles[0], b)
        self.assertEqual((a.index, b.index, w.active), (3, 0, 3))
        self.assertEqual(int(a.surface.winId()), handle)
        self.assertEqual(a.volume.value(), 17)
        self.assertTrue(a.paused)
        self.assertFalse(a.chat_toggle.isChecked())
        self.assertIn('聊天记录101', a.chat_view.toPlainText())
        self.assertIn('聊天记录102', b.chat_view.toPlainText())
        self.assertTrue(a.name.text().startswith('04'))
        saved = load_state(self.path)
        self.assertEqual(saved['slots'][:4], ['102', None, None, '101'])
        self.assertEqual(saved['slot_settings']['3']['volume'], 17)
        b.name.click()
        self.assertEqual(w.active, 0)
        a.solo.click()
        self.assertEqual(w.active, 3)
        self.assertFalse(a.muted)
        self.assertTrue(b.muted)
        w.swap_tiles(3, 1)
        self.assertIs(w.tiles[1], a)
        self.assertIsNone(w.tiles[3].room)
        self.assertTrue(w.tiles[3].name.text().startswith('04'))
        unchanged = list(w.tiles)
        w.swap_tiles(0, 8)
        self.assertEqual(w.tiles, unchanged)

    def test_audio_startup_never_unmutes_before_volume_succeeds(self):
        tile = self.window.tiles[0]
        tile.volume.setValue(17)
        tile.player = Mock()
        tile.player.audio_set_volume.return_value = -1
        tile.player.get_state.return_value = 'State.Playing'
        tile._audio_pending = True
        tile.audio_startup.start()
        tile.finish_audio_startup()
        self.assertTrue(tile._audio_pending)
        self.assertTrue(tile.audio_startup.isActive())
        tile.player.audio_set_mute.assert_called_once_with(True)
        tile.player.reset_mock()
        tile.player.audio_set_volume.return_value = 0
        tile.finish_audio_startup()
        self.assertFalse(tile._audio_pending)
        self.assertFalse(tile.audio_startup.isActive())
        self.assertEqual([c[0] for c in tile.player.mock_calls][-2:], ['audio_set_volume', 'audio_set_mute'])
        tile.player.audio_set_volume.assert_called_once_with(17)
        tile.player.audio_set_mute.assert_called_once_with(False)
        tile.player.reset_mock()
        tile.monitor_playback()
        tile.player.audio_set_volume.assert_not_called()
        tile.player.audio_set_mute.assert_not_called()

    def test_single_mute_does_not_write_other_players_or_repeat_each_tick(self):
        w = self.window
        a, b = w.tiles[:2]
        for tile in (a, b):
            tile.room = {'id': str(tile.index), 'name': str(tile.index)}
            tile.player = Mock()
            tile.player.audio_set_volume.return_value = 0
            tile.player.get_state.return_value = 'State.Playing'
            tile.set_muted(False)
            tile.apply_audio()
            tile.player.reset_mock()
        changes = []
        a.changed.connect(lambda: changes.append(True))
        a.mute_button.click()
        a.player.audio_set_mute.assert_called_once_with(True)
        a.player.audio_set_volume.assert_not_called()
        self.assertFalse(b.player.mock_calls)
        self.assertFalse(b.muted)
        self.assertEqual(len(changes), 1)
        for _ in range(4):
            a.monitor_playback()
            b.monitor_playback()
        a.player.audio_set_mute.assert_called_once_with(True)
        b.player.audio_set_mute.assert_not_called()
        b.player.audio_set_volume.assert_not_called()
        a.player.reset_mock()
        a.set_muted(False)
        a.player.audio_set_mute.assert_called_once_with(False)
        self.assertEqual(len(changes), 2)
        a.set_muted(False)
        a.player.audio_set_mute.assert_called_once_with(False)
        self.assertEqual(len(changes), 2)
        a.player.reset_mock()
        a.volume.setValue(27)
        a.player.audio_set_volume.assert_called_once_with(27)
        a.player.audio_set_mute.assert_not_called()
        a.player.reset_mock()
        a._audio_pending = True
        a.monitor_playback()
        a.monitor_playback()
        a.player.audio_set_mute.assert_called_once_with(False)
        a.player.audio_set_volume.assert_called_once_with(27)

    def test_title_drag_threshold_and_source_validation(self):
        w = self.window
        tile = w.tiles[0]
        with patch('studio.player.QDrag') as drag_type:
            QTest.mousePress(tile.name, Qt.LeftButton, pos=QPoint(10, 10))
            QTest.mouseMove(tile.name, QPoint(12, 10))
            drag_type.assert_not_called()
            QTest.mouseMove(tile.name, QPoint(60, 10))
            QTest.mouseRelease(tile.name, Qt.LeftButton, pos=QPoint(60, 10))
            drag_type.assert_called_once_with(tile)
            drag_type.return_value.exec.assert_called_once_with(Qt.MoveAction)
            mime = drag_type.return_value.setMimeData.call_args.args[0]
            self.assertTrue(mime.hasFormat('application/x-dd-tile'))
        mime = QMimeData()
        mime.setData('application/x-dd-tile', b'0')
        for source in (None, tile, w.tiles[8]):
            event = SimpleNamespace(mimeData=lambda: mime, source=lambda: source, acceptProposedAction=Mock())
            tile.dropEvent(event)
            event.acceptProposedAction.assert_not_called()

    def test_favorite_star_and_quick_selection_persist(self):
        w = self.window
        w.demo = False
        w.cookies = {}
        w.open_search(2)
        dialog = w.dialogs[-1]
        dialog.mode = 'search'
        room = {'id':'99','name':'收藏测试','uid':99,'title':'标题','following':None}
        dialog.show_results(dialog.ticket, {'rooms':[room],'more':False,'follow_state':'login_required'})
        self.app.processEvents()
        item = dialog.results.item(0)
        star = dialog.result_delegate.favorite_rect(dialog.results.visualItemRect(item)).center().toPoint()
        QTest.mouseClick(dialog.results.viewport(),Qt.LeftButton,pos=star)
        self.assertIn('99',w.favorites)
        self.assertEqual(item.checkState(),Qt.Unchecked)
        self.assertEqual(w.room_list.count(),1)
        self.assertEqual(load_state(self.path)['favorites'],['99'])
        dialog.close()
        w.open_search(1)
        quick = w.dialogs[-1]
        self.assertEqual(quick.mode,'following')
        self.assertEqual(quick.favorite_strip.item(0).data(Qt.UserRole)['id'],'99')
        self.assertEqual(quick.target.currentData(),1)
        quick.toggle_favorite('99')
        self.assertNotIn('99',w.favorites)
        self.assertEqual(w.room_list.count(),0)
        self.assertEqual(quick.favorite_strip.count(),1)
        self.assertFalse(quick.favorite_strip.item(0).data(Qt.UserRole+1))
        quick.toggle_favorite('99')
        self.assertTrue(quick.favorite_strip.item(0).data(Qt.UserRole+1))
        quick.toggle_favorite('99')
        quick.close()
        w.open_search(1)
        self.assertEqual(w.dialogs[-1].favorite_strip.count(), 0)
        w.dialogs[-1].close()

    def test_favorite_avatar_selects_and_star_does_not_remove_until_close(self):
        w = self.window
        w.rooms = {str(i): {'id':str(i),'name':f'主播{i}','live':i==2} for i in (1,2,3)}
        w.favorites = set(w.rooms)
        w.open_search(0)
        d = w.dialogs[-1]
        self.app.processEvents()
        first = d.favorite_strip.item(0)
        self.assertEqual(first.data(Qt.UserRole)['id'], '2')
        rect = d.favorite_strip.visualItemRect(first)
        QTest.mouseClick(d.favorite_strip.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(first.checkState(), Qt.Checked)
        self.assertEqual([r['id'] for r in d.selected_rooms()], ['2'])
        star = d.favorite_strip.itemDelegate().favorite_rect(rect).center().toPoint()
        QTest.mouseClick(d.favorite_strip.viewport(), Qt.LeftButton, pos=star)
        self.assertNotIn('2', w.favorites)
        self.assertEqual(d.favorite_strip.count(), 3)
        self.assertEqual(first.checkState(), Qt.Checked)
        d.close()

    def test_sidebar_right_click_removes_only_target_favorite(self):
        w = self.window
        w.rooms = {str(i): {'id':str(i),'name':f'主播{i}','live':False} for i in (1,2)}
        w.favorites = set(w.rooms)
        w.tiles[0].room = dict(w.rooms['2'])
        w.refresh_library()
        self.app.processEvents()
        item = w.room_list.item(1)
        position = w.room_list.visualItemRect(item).center()
        with patch.object(w.tiles[0], 'set_room') as play:
            QTest.mouseClick(w.room_list.viewport(), Qt.RightButton, pos=position)
            w.room_list.show_context_menu(position)
            self.assertEqual(w.room_list.context_menu.actions()[0].text(), '移除收藏')
            w.room_list.context_menu.actions()[0].trigger()
            w.room_list.context_menu.close()
            play.assert_not_called()
        self.assertEqual(w.favorites, {'1'})
        self.assertEqual(w.tiles[0].room['id'], '2')

    def test_sidebar_highlights_all_visible_rooms_and_tracks_layout_and_focus(self):
        w = self.window
        for index, tile in enumerate(w.tiles[:5]):
            tile.room = {'id':str(index+1),'name':f'主播{index+1}'}
        w.sync_sidebar_visible()
        self.assertEqual(w.room_list.visible_rooms, {'1','2','3','4'})
        w.select_tile(2)
        self.assertEqual(w.room_list.visible_rooms, {'1','2','3','4'})
        w.focus_tile(2)
        self.assertEqual(w.room_list.visible_rooms, {'3'})
        w.exit_focus()
        self.assertEqual(w.room_list.visible_rooms, {'1','2','3','4'})
        w.layout_choice.setCurrentIndex(w.layout_choice.findData(2))
        self.assertEqual(w.room_list.visible_rooms, {'1','2'})
        w.tiles[0].clear()
        self.assertEqual(w.room_list.visible_rooms, {'2'})

    def test_follow_filter_excludes_unknown_and_hidden_selections(self):
        dialog = SearchDialog({},0,4,self.window)
        dialog.mode = 'search'
        rooms = [{'id':str(i),'name':str(i),'following':state} for i,state in enumerate((True,False,None))]
        dialog.show_results(dialog.ticket,{'rooms':rooms,'more':True,'follow_state':'ok'})
        dialog.results.item(0).setCheckState(Qt.Checked)
        dialog.follow_filter.setCurrentIndex(2)
        self.assertTrue(dialog.results.item(0).isHidden())
        self.assertFalse(dialog.results.item(1).isHidden())
        self.assertTrue(dialog.results.item(2).isHidden())
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.close()

    def test_top_icons_help_popup_title_and_dropdown_position(self):
        w = self.window
        self.assertLess(w.global_controls.mapToGlobal(QPoint()).y(),w.content.mapToGlobal(QPoint()).y())
        self.assertLess(w.centralWidget().height()-w.content.geometry().bottom(),20)
        for control in (w.pause_all,w.mute_all,w.reload_button,w.chat_toggle,w.info_button,w.tiles[0].play_button,w.tiles[0].remove):
            self.assertTrue(control.text() == '' and not control.icon().isNull() and control.toolTip())
        self.assertFalse(hasattr(w.tiles[0],'add_button'))
        self.assertFalse(any('替换' in a.text() for a in w.tiles[0].more_menu.actions()))
        w.tiles[0].room = {'id':'1','name':'主播昵称','title':'今晚的直播标题'}
        w.tiles[0].update_title()
        self.assertIn('主播昵称 · 今晚的直播标题',w.tiles[0].name.text())
        w.show_help()
        self.app.processEvents()
        self.assertTrue(w.help_dialog.isVisible())
        w.help_dialog.hide()
        w.layout_choice.showPopup()
        self.app.processEvents()
        self.assertGreaterEqual(w.layout_choice.view().window().geometry().top(),w.layout_choice.mapToGlobal(QPoint(0,w.layout_choice.height())).y())
        w.layout_choice.hidePopup()


if __name__ == '__main__':
    unittest.main(verbosity=2)
