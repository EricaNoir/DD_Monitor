import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from studio.services import room_number, plain, safe_image, parse_chat
from studio.chat import message_html
from studio.state import load_state, save_json
from studio.app import StudioWindow, SearchDialog
from studio.player import PlayerTile

ROOT = Path(__file__).resolve().parents[1]


class DataTests(unittest.TestCase):
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
        cls.app.setStyleSheet((ROOT / 'studio/theme.qss').read_text(encoding='utf-8'))

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
        w.library_toggle.click()
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

    def test_search_selection_and_stale_response(self):
        dialog = SearchDialog({}, 0, 4, self.window)
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
        w.library_toggle.setChecked(False)
        w.save()
        saved = load_state(self.path)
        self.assertFalse(saved['chat_visible'])
        self.assertFalse(saved['library_visible'])
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

    def test_avatar_rail_can_restore_sidebar_and_focus_without_reload(self):
        w = self.window
        room = {'id': '123', 'name': '测试主播', 'live': True, 'title': '直播标题'}
        w.rooms = {'123': room}
        w.tiles[1].room = room
        w.refresh_library()
        width = w.library.width()
        w.library_filter.setText('无匹配')
        self.assertEqual(w.room_list.count(), 0)
        w.library_toggle.click()
        self.app.processEvents()
        self.assertTrue(w.library.isVisible())
        self.assertEqual(w.room_list.count(), 1)
        self.assertTrue(w.library_toggle.isVisible() and w.library_add.isVisible())
        self.assertLess(w.library_toggle.x(), 60)
        self.assertLessEqual(w.library.width(), 56)
        self.assertIn('测试主播', w.room_list.item(0).toolTip())
        generation = w.tiles[1].generation
        w.room_list.itemClicked.emit(w.room_list.item(0))
        self.assertEqual(w.active, 1)
        self.assertEqual(w.tiles[1].generation, generation)
        w.library_toggle.click()
        self.app.processEvents()
        self.assertLess(abs(w.library.width() - width), 20)
        self.assertEqual(w.library_filter.text(), '无匹配')

    def test_collapsed_sidebar_persists_as_avatar_rail(self):
        w = self.window
        w.demo = False
        w.library_toggle.setChecked(False)
        w.save()
        again = StudioWindow(ROOT, demo=True, state_path=self.path)
        again.show()
        self.app.processEvents()
        self.assertTrue(again.library.isVisible())
        self.assertLessEqual(again.library.width(), 56)
        self.assertTrue(again.library_toggle.isVisible())
        again.close()

    def test_preview(self):
        w = self.window
        w.rooms = {str(i): {'id': str(i), 'name': name, 'title': '预览内容', 'live': i != 3}
                   for i, name in enumerate(['OA-LEAVE7', 'OA-Guxue8', 'OA-SHY', '收藏的直播间'], 1)}
        w.refresh_library()
        for tile, room in zip(w.tiles, w.rooms.values()):
            tile.room = room
            tile.name.setText(f'{tile.index + 1:02d}   {room["name"]}')
            tile.empty_title.setText('直播画面')
            tile.empty_hint.setText('界面预览 · 实际运行时显示直播视频')
        for tile in w.tiles[:4]:
            tile.empty_add.hide()
            tile.chat_connection.setText('已连接')
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
