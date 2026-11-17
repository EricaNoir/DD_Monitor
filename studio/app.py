import io
import json
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData, QThreadPool, QTimer, Signal, QSize
from PySide6.QtGui import QDrag, QFont, QKeySequence, QPixmap, QShortcut, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QDialog, QSplitter, QCheckBox, QSpinBox, QSlider, QMessageBox)
from .services import BiliAPI, Job
from .player import PlayerTile
from .chat import ChatView
from .state import load_state, save_json, load_credentials


def button(text, callback=None, primary=False, checkable=False):
    widget = QPushButton(text)
    widget.setCheckable(checkable)
    if primary:
        widget.setObjectName('Primary')
    if callback:
        widget.clicked.connect(callback)
    return widget


def label(text, kind='Muted'):
    widget = QLabel(text)
    widget.setObjectName(kind)
    return widget


class RoomList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setSpacing(3)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        mime.setData('application/x-dd-room', json.dumps(item.data(Qt.UserRole)).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class SearchDialog(QDialog):
    rooms_added = Signal(list, int)

    def __init__(self, cookies, target, count, parent=None):
        super().__init__(parent)
        self.cookies, self.page, self.ticket, self.query = cookies, 1, 0, ''
        self.setWindowTitle('添加直播间')
        self.resize(760, 580)
        self.setMinimumSize(620, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label('找到想看的 UP 主', 'Heading'))
        layout.addWidget(label('按昵称搜索，也可以直接粘贴直播间链接或房号。'))
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('例如 OA-LEAVE7 / 31294374 / 直播间链接')
        self.input.returnPressed.connect(self.search)
        self.search_button = button('搜索', self.search, True)
        row.addWidget(self.input, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.status = label('输入昵称后按 Enter 开始搜索。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.results = QListWidget()
        self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results.itemChanged.connect(self.update_count)
        self.results.itemDoubleClicked.connect(self.toggle_item)
        layout.addWidget(self.results, 1)
        self.more = button('加载更多', lambda: self.search(more=True))
        self.more.setVisible(False)
        layout.addWidget(self.more, alignment=Qt.AlignCenter)
        row = QHBoxLayout()
        self.target = QComboBox()
        self.target.addItem('只加入主播库', -1)
        for index in range(count):
            self.target.addItem(f'加入并播放到画面 {index + 1}', index)
        self.target.setCurrentIndex(target + 1)
        row.addWidget(self.target)
        row.addStretch()
        row.addWidget(button('取消', self.reject))
        self.add_button = button('添加选中 (0)', self.add_selected, True)
        self.add_button.setEnabled(False)
        row.addWidget(self.add_button)
        layout.addLayout(row)

    def toggle_item(self, item):
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def update_count(self, *_):
        count = sum(self.results.item(i).checkState() == Qt.Checked for i in range(self.results.count()))
        self.add_button.setText(f'添加选中 ({count})')
        self.add_button.setEnabled(count > 0)

    def search(self, checked=False, more=False):
        query = self.input.text().strip()
        if not query:
            self.status.setText('先输入 UP 主昵称、房号或直播间链接。')
            self.input.setFocus()
            return
        self.ticket += 1
        ticket = self.ticket
        if not more or query != self.query:
            self.page = 1
            self.results.clear()
        else:
            self.page += 1
        self.query = query
        self.status.setText(f'正在搜索「{query}」…')
        self.search_button.setEnabled(False)
        self.more.setEnabled(False)
        api, page = BiliAPI(self.cookies), self.page
        job = Job(lambda: api.search(query, page))
        job.signals.done.connect(lambda data: self.show_results(ticket, data))
        job.signals.error.connect(lambda error: self.show_error(ticket, error))
        QThreadPool.globalInstance().start(job)

    def show_results(self, ticket, data):
        if ticket != self.ticket:
            return
        existing = {self.results.item(i).data(Qt.UserRole)['id'] for i in range(self.results.count())}
        for room in data['rooms']:
            if room['id'] in existing:
                continue
            status = '● 直播中' if room.get('live') else '○ 未开播'
            item = QListWidgetItem(f'{room["name"]}    {status}\n房号 {room["id"]}  ·  {room.get("title", "")}')
            item.setData(Qt.UserRole, room)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setSizeHint(QSize(0, 70))
            self.results.addItem(item)
        self.status.setText(f'找到 {self.results.count()} 个直播间，勾选要添加的主播。' if self.results.count()
                            else '没有找到匹配直播间。试试完整昵称，或直接粘贴直播间链接。')
        self.search_button.setEnabled(True)
        self.more.setVisible(data['more'])
        self.more.setEnabled(True)

    def show_error(self, ticket, error):
        if ticket == self.ticket:
            self.status.setText(error + ' 也可以用房号或直播间链接添加。')
            self.search_button.setEnabled(True)
            self.more.setEnabled(True)
            self.page = max(1, self.page - 1)

    def add_selected(self):
        rooms = [self.results.item(i).data(Qt.UserRole) for i in range(self.results.count())
                 if self.results.item(i).checkState() == Qt.Checked]
        if rooms:
            self.rooms_added.emit(rooms, self.target.currentData())
            self.accept()


class LoginDialog(QDialog):
    authenticated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('登录 Bilibili')
        self.setFixedSize(370, 440)
        self.api, self.key = BiliAPI(), None
        self.polling = False
        self.alive = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label('扫码登录 Bilibili', 'Heading'))
        layout.addWidget(label('使用 B 站 App 扫码，在手机上确认登录。'))
        self.picture = QLabel('正在生成二维码…')
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setFixedHeight(280)
        layout.addWidget(self.picture)
        self.status = label('登录信息仅保存在这台电脑。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.finished.connect(self.finish)
        job = Job(self.api.qr)
        job.signals.done.connect(self.show_qr)
        job.signals.error.connect(self.status.setText)
        QThreadPool.globalInstance().start(job)

    def show_qr(self, data):
        if not self.alive:
            return
        import qrcode
        output = io.BytesIO()
        qrcode.make(data['url']).save(output, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(output.getvalue())
        self.picture.setPixmap(pixmap.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.key = data['qrcode_key']
        self.timer.start(2200)

    def poll(self):
        if self.polling or not self.key:
            return
        self.polling = True
        job = Job(lambda: self.api.poll_qr(self.key))
        job.signals.done.connect(self.poll_result)
        job.signals.error.connect(self.poll_error)
        QThreadPool.globalInstance().start(job)

    def poll_error(self, error):
        self.polling = False
        self.status.setText(error)

    def poll_result(self, result):
        self.polling = False
        if not self.alive:
            return
        if result['status'] == 0:
            self.authenticated.emit(result['cookies'])
            self.accept()
        elif result['status'] == 86038:
            self.timer.stop()
            self.status.setText('二维码已过期，请关闭后重新打开登录。')
        elif result['status'] == 86090:
            self.status.setText('已扫码，请在手机上确认登录。')
        else:
            self.status.setText('等待扫码。登录信息仅保存在这台电脑。')

    def finish(self, *_):
        self.alive = False
        self.timer.stop()


class StudioWindow(QMainWindow):
    closed = Signal()

    def __init__(self, root, instance=None, demo=False, state_path=None):
        super().__init__()
        self.root, self.instance, self.demo = Path(root), instance, demo
        self.state_path = Path(state_path) if state_path else self.root / 'user-data' / 'studio.json'
        self.state = load_state(self.state_path)
        self.cookies = {} if demo else load_credentials(self.root)
        self.rooms = {room['id']: room for room in self.state['rooms']}
        self.active, self.focused = 0, None
        self.count = int(self.state['layout'])
        self.dialogs = []
        self.closing = False
        self.ready = False
        self.setWindowTitle('DD Monitor Studio · 多屏直播工作台')
        self.resize(1760, 960)
        self.setMinimumSize(1050, 650)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header_frame = QFrame()
        header_frame.setObjectName('Header')
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(16, 10, 16, 10)
        header.setSpacing(10)
        header.addWidget(label('DD Monitor', 'Brand'))
        self.account = button('已读取本机登录' if self.cookies else '登录 Bilibili', self.login)
        self.account.setToolTip('点击重新扫码登录')
        header.addWidget(self.account)
        header.addStretch()
        self.layout_choice = QComboBox()
        for value, title in [(1, '单画面'), (2, '双画面'), (4, '四宫格'), (6, '六宫格'), (9, '九宫格')]:
            self.layout_choice.addItem(title, value)
        self.layout_choice.setCurrentIndex(max(0, self.layout_choice.findData(self.count)))
        self.layout_choice.currentIndexChanged.connect(self.change_layout)
        header.addWidget(self.layout_choice)
        self.library_toggle = button('主播库', checkable=True)
        self.controls_toggle = button('控制条', checkable=True)
        self.chat_toggle = button('弹幕', checkable=True)
        self.chat_toggle.setToolTip('显示 / 隐藏所有直播间的聊天  Ctrl+J')
        for widget in (self.library_toggle, self.controls_toggle, self.chat_toggle):
            header.addWidget(widget)
        header.addWidget(button('设置', lambda: self.chat_settings.show()))
        self.add = button('＋ 添加直播间', lambda: self.open_search(self.active), True)
        header.addWidget(self.add)
        outer.addWidget(header_frame)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(5)
        self.splitter.setChildrenCollapsible(False)
        self.library = self.build_library()
        self.splitter.addWidget(self.library)
        self.video_area = QWidget()
        self.video_grid = QGridLayout(self.video_area)
        self.video_grid.setContentsMargins(0, 0, 0, 0)
        self.video_grid.setSpacing(8)
        self.tiles = [PlayerTile(index, instance, self.cookies, self) for index in range(9)]
        for tile in self.tiles:
            tile.selected.connect(self.select_tile)
            tile.add_requested.connect(self.open_search)
            tile.focus_requested.connect(self.focus_tile)
            tile.solo_requested.connect(self.solo_tile)
            tile.room_resolved.connect(self.update_room)
            tile.changed.connect(self.tile_changed)
            saved = self.state['slot_settings'].get(str(tile.index), {})
            tile.volume.setValue(saved.get('volume', self.state['volume']))
            tile.set_muted(saved.get('muted', tile.index != 0))
            tile.quality.setCurrentIndex(max(0, tile.quality.findData(saved.get('quality', 250))))
            tile.chat_width = max(145, int(saved.get('chat_width', 195)))
            tile.chat_toggle.setChecked(saved.get('chat_visible', self.state['chat_visible']))
            tile.toggle_chat(tile.chat_toggle.isChecked())
        self.splitter.addWidget(self.video_area)
        self.chat_settings = self.build_chat_settings()
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        content = QHBoxLayout()
        content.setContentsMargins(10, 8, 10, 8)
        content.addWidget(self.splitter)
        outer.addLayout(content, 1)

        self.global_controls = QFrame()
        footer = QHBoxLayout(self.global_controls)
        footer.setContentsMargins(20, 7, 20, 10)
        self.pause_all = button('全部暂停', self.toggle_all_pause, checkable=True)
        footer.addWidget(self.pause_all)
        footer.addWidget(button('全部重连', self.reload_all))
        self.mute_all = button('全部静音', self.toggle_all_mute, checkable=True)
        footer.addWidget(self.mute_all)
        footer.addWidget(label('统一音量'))
        self.master_volume = QSlider(Qt.Horizontal)
        self.master_volume.setRange(0, 100)
        self.master_volume.setValue(self.state['volume'])
        self.master_volume.setFixedWidth(140)
        self.master_volume.valueChanged.connect(self.set_all_volume)
        footer.addWidget(self.master_volume)
        footer.addStretch()
        footer.addWidget(label('拖入主播开始播放  ·  Ctrl+K 添加  ·  Ctrl+J 聊天  ·  F11 全屏'))
        outer.addWidget(self.global_controls)
        self.notice = label('Ctrl+K 添加直播间  ·  Ctrl+J 显示 / 收起所有弹幕')
        self.notice.setContentsMargins(22, 0, 20, 10)
        outer.addWidget(self.notice)

        self.library_toggle.toggled.connect(self.toggle_library)
        self.controls_toggle.toggled.connect(self.toggle_controls)
        self.library_toggle.setChecked(bool(self.state['library_visible']))
        self.controls_toggle.setChecked(bool(self.state['controls_visible']))
        self.chat_toggle.setChecked(any(t.chat_toggle.isChecked() for t in self.tiles))
        self.chat_toggle.toggled.connect(self.toggle_chat)
        self.library.setVisible(self.library_toggle.isChecked())
        self.toggle_controls(self.controls_toggle.isChecked())
        self.splitter.splitterMoved.connect(lambda *_: self.save())
        sizes = self.state['splitter']
        self.splitter.setSizes([sizes[0], sum(sizes[1:])])
        self.library_width = self.state['splitter'][0]
        self.shortcuts = []
        for keys, callback in [('Ctrl+K', lambda: self.open_search(self.active)), ('Ctrl+J', self.chat_toggle.click),
                               ('Ctrl+B', self.library_toggle.click), ('F11', self.toggle_fullscreen),
                               ('Escape', self.exit_focus)]:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.refresh_library()
        self.arrange()
        self.ready = True
        self.select_tile(0)
        if not demo:
            QTimer.singleShot(100, self.restore_rooms)

    def build_library(self):
        frame = QFrame()
        frame.setObjectName('Library')
        frame.setMinimumWidth(195)
        frame.setMaximumWidth(420)
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 17, 14, 14)
        row = QHBoxLayout()
        row.addWidget(label('我的直播间', 'Heading'), 1)
        row.addWidget(button('收起', lambda: self.library_toggle.setChecked(False)))
        box.addLayout(row)
        self.library_filter = QLineEdit()
        self.library_filter.setPlaceholderText('筛选已添加的主播')
        self.library_filter.textChanged.connect(self.refresh_library)
        box.addWidget(self.library_filter)
        self.room_list = RoomList()
        self.room_list.itemDoubleClicked.connect(lambda item: self.play_library(item))
        box.addWidget(self.room_list, 1)
        self.library_empty = label('还没有收藏的直播间\n点击「添加直播间」搜索主播')
        self.library_empty.setAlignment(Qt.AlignCenter)
        self.library_empty.setWordWrap(True)
        box.addWidget(self.library_empty)
        box.addWidget(button('播放到当前画面', lambda: self.play_library(self.room_list.currentItem()), True))
        box.addWidget(button('＋ 添加直播间', lambda: self.open_search(self.active)))
        box.addWidget(button('移出主播库', self.remove_library))
        box.addWidget(label('双击播放 · 拖动到指定画面'))
        return frame

    def build_chat_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('弹幕设置')
        dialog.setMinimumWidth(340)
        box = QVBoxLayout(dialog)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(16)
        box.addWidget(label('弹幕显示', 'Heading'))
        box.addWidget(label('应用到每个直播间，栏宽可分别拖动调整。'))
        row = QHBoxLayout()
        row.addWidget(label('文字大小'))
        self.chat_font = QSpinBox()
        self.chat_font.setRange(10, 24)
        self.chat_font.setValue(self.state['chat_font'])
        self.chat_font.valueChanged.connect(self.set_chat_font)
        row.addWidget(self.chat_font)
        box.addLayout(row)
        self.show_names = QCheckBox('显示昵称和粉丝牌')
        self.show_names.setChecked(self.state.get('chat_names', True))
        self.show_names.toggled.connect(self.toggle_names)
        box.addWidget(self.show_names)
        self.follow = QCheckBox('跟随新消息')
        self.follow.setChecked(self.state['chat_follow'])
        self.follow.toggled.connect(self.set_follow)
        box.addWidget(self.follow)
        box.addWidget(button('完成', dialog.accept, True))
        self.set_chat_font(self.chat_font.value())
        self.toggle_names(self.show_names.isChecked())
        self.set_follow(self.follow.isChecked())
        return dialog

    def update_room(self, room):
        self.rooms[room['id']] = room
        self.refresh_library()
        self.save()

    def refresh_library(self, *_):
        if not hasattr(self, 'room_list'):
            return
        current = self.room_list.currentItem()
        selected_id = current.data(Qt.UserRole)['id'] if current else None
        self.room_list.clear()
        query = self.library_filter.text().strip().casefold()
        for room in self.rooms.values():
            if query and query not in (room['name'] + ' ' + room['id']).casefold():
                continue
            state = '● 直播中' if room.get('live') else '○ 未开播'
            item = QListWidgetItem(f'{room["name"]}\n{state}  ·  {room["id"]}')
            item.setToolTip(room.get('title', ''))
            item.setData(Qt.UserRole, room)
            item.setSizeHint(QSize(0, 68))
            self.room_list.addItem(item)
            if room['id'] == selected_id:
                self.room_list.setCurrentItem(item)
        self.library_empty.setVisible(not self.rooms)

    def open_search(self, target=0):
        target = target if 0 <= target < self.count else 0
        dialog = SearchDialog(self.cookies, target, self.count, self)
        dialog.rooms_added.connect(self.add_rooms)
        self.dialogs.append(dialog)
        dialog.show()
        dialog.input.setFocus()

    def add_rooms(self, rooms, target):
        for room in rooms:
            self.rooms[room['id']] = room
        if target >= 0:
            targets = [target] + [i for i in range(self.count) if i != target and not self.tiles[i].room]
            for room, index in zip(rooms, targets):
                self.tiles[index].set_room(room)
        self.refresh_library()
        self.notice.setText(f'已添加 {len(rooms)} 个直播间。可从左侧拖入任意画面。')
        self.save()

    def play_library(self, item):
        if item:
            self.tiles[self.active].set_room(item.data(Qt.UserRole))

    def remove_library(self):
        item = self.room_list.currentItem()
        if item:
            self.rooms.pop(item.data(Qt.UserRole)['id'], None)
            self.refresh_library()
            self.save()

    def select_tile(self, index):
        if not 0 <= index < len(self.tiles):
            return
        self.active = index
        for tile in self.tiles:
            tile.set_active(tile.index == index)

    def tile_changed(self):
        if self.ready:
            self.chat_toggle.blockSignals(True)
            self.chat_toggle.setChecked(any(t.chat_toggle.isChecked() for t in self.tiles[:self.count]))
            self.chat_toggle.blockSignals(False)
            self.save()

    def change_layout(self, *_):
        self.count = self.layout_choice.currentData()
        self.focused = None
        self.arrange()
        if self.active >= self.count:
            self.select_tile(0)
        self.save()

    def arrange(self):
        for tile in self.tiles:
            self.video_grid.removeWidget(tile)
            tile.hide()
        indices = [self.focused] if self.focused is not None else list(range(self.count))
        columns = 1 if len(indices) == 1 else (2 if len(indices) <= 4 else 3)
        for i in range(9):
            self.video_grid.setRowStretch(i, 0)
            self.video_grid.setColumnStretch(i, 0)
        for position, index in enumerate(indices):
            row, col = divmod(position, columns)
            self.video_grid.addWidget(self.tiles[index], row, col)
            self.video_grid.setRowStretch(row, 1)
            self.video_grid.setColumnStretch(col, 1)
            self.tiles[index].show()
        for tile in self.tiles:
            tile.suspend(tile.index not in indices)

    def focus_tile(self, index):
        self.focused = None if self.focused == index else index
        self.select_tile(index)
        self.arrange()

    def exit_focus(self):
        if self.isFullScreen():
            self.showNormal()
        if self.focused is not None:
            self.focused = None
            self.arrange()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def toggle_chat(self, shown):
        for tile in self.tiles:
            tile.chat_toggle.setChecked(shown)
        self.save()

    def toggle_library(self, shown):
        if not shown and self.library.isVisible():
            self.library_width = self.splitter.sizes()[0]
        self.library.setVisible(shown)
        if shown and hasattr(self, 'library_width'):
            sizes = self.splitter.sizes()
            width = self.library_width or 235
            self.splitter.setSizes([width, max(400, sum(sizes) - width)])
        self.save()

    def toggle_controls(self, shown):
        if hasattr(self, 'global_controls'):
            self.global_controls.setVisible(shown)
        for tile in self.tiles:
            tile.controls.setVisible(shown)
        self.save()

    def set_chat_font(self, size):
        font = QFont('Microsoft YaHei UI')
        font.setPixelSize(size)
        for tile in self.tiles:
            tile.chat_view.setStyleSheet(f'QTextBrowser {{ font-size: {size}px; }}')
            tile.chat_view.document().setDefaultFont(font)
        self.save()

    def toggle_names(self, shown):
        for tile in self.tiles:
            tile.chat_view.names = shown
            tile.chat_view.show_history(tile.history)
        self.save()

    def set_follow(self, follow):
        for tile in self.tiles:
            tile.chat_view.follow = follow
            if follow:
                tile.chat_view.verticalScrollBar().setValue(tile.chat_view.verticalScrollBar().maximum())
        self.save()

    def set_all_volume(self, value):
        for tile in self.tiles:
            tile.volume.setValue(value)
        self.save()

    def toggle_all_pause(self, paused):
        for tile in self.tiles:
            if tile.room and tile.paused != paused:
                tile.toggle_pause()
        self.pause_all.setText('全部继续' if paused else '全部暂停')

    def toggle_all_mute(self, muted):
        for tile in self.tiles:
            tile.set_muted(muted)

    def solo_tile(self, index):
        for tile in self.tiles:
            tile.set_muted(tile.index != index)
        self.mute_all.blockSignals(True)
        self.mute_all.setChecked(False)
        self.mute_all.blockSignals(False)
        self.select_tile(index)

    def reload_all(self):
        for tile in self.tiles:
            if not tile.suspended:
                tile.reload(reconnect_chat=True)

    def login(self):
        dialog = LoginDialog(self)
        dialog.authenticated.connect(self.logged_in)
        self.dialogs.append(dialog)
        dialog.show()

    def logged_in(self, cookies):
        self.cookies = cookies
        save_json(self.root / 'user-data' / 'credentials.json', cookies)
        self.account.setText('已登录 Bilibili')
        for tile in self.tiles:
            tile.cookies = cookies
            if tile.room:
                tile.reload(reconnect_chat=True)
        self.notice.setText('登录成功，已刷新视频与聊天连接。')

    def restore_rooms(self):
        for index, rid in enumerate(self.state['slots'][:9]):
            if rid and rid in self.rooms:
                self.tiles[index].set_room(self.rooms[rid])
        self.select_tile(0)

    def save(self):
        if not self.ready or self.closing or self.demo:
            return
        sizes = self.splitter.sizes()
        if not self.library_toggle.isChecked():
            sizes[0] = getattr(self, 'library_width', 235)
        self.state.update({'rooms': list(self.rooms.values()), 'slots': [tile.room['id'] if tile.room else None for tile in self.tiles],
                          'layout': self.count, 'chat_visible': self.chat_toggle.isChecked(),
                          'library_visible': self.library_toggle.isChecked(), 'controls_visible': self.controls_toggle.isChecked(),
                          'chat_font': self.chat_font.value(), 'chat_follow': self.follow.isChecked(),
                          'chat_names': self.show_names.isChecked(),
                          'splitter': sizes, 'volume': self.master_volume.value(),
                          'slot_settings': {str(tile.index): {'volume': tile.volume.value(), 'muted': tile.muted,
                                            'quality': tile.quality.currentData(),
                                            'chat_visible': tile.chat_toggle.isChecked(),
                                            'chat_width': tile.chat_width} for tile in self.tiles}})
        save_json(self.state_path, self.state)

    def closeEvent(self, event):
        if not self.closing:
            self.save()
            self.closing = True
            for tile in self.tiles:
                tile.shutdown()
        # Never destroy a live QThread; finish network cancellation before exit.
        if any(worker.isRunning() for tile in self.tiles for worker in tile.retiring):
            event.ignore()
            self.hide()
            QTimer.singleShot(150, self.close)
            return
        event.accept()
        self.closed.emit()


def main(root, demo=False):
    import os
    import sys
    root = Path(root)
    os.chdir(root)
    from .runtime import configure_vlc
    dll_handle = None if demo else configure_vlc(root)
    app = QApplication(sys.argv)
    app.setApplicationName('DD Monitor Studio')
    app.setWindowIcon(QIcon(str(root / 'favicon.ico')))
    app.setStyle('Fusion')
    app.setStyleSheet((root / 'studio' / 'theme.qss').read_text(encoding='utf-8'))
    instance = None
    if not demo:
        import vlc
        instance = vlc.Instance('--quiet', '--no-video-title-show', '--avcodec-hw=any')
    if not demo and not instance:
        QMessageBox.critical(None, '播放器初始化失败', '找不到 VLC 运行库，请检查 libvlc.dll 和 plugins 目录。')
        return 1
    window = StudioWindow(root, instance, demo)
    window.closed.connect(app.quit)
    window.show()
    result = app.exec()
    QThreadPool.globalInstance().waitForDone(15000)
    if instance:
        instance.release()
    return result
