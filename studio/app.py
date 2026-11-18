from .theme import stylesheet, SIZES
import io
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, QSize, QPoint
from PySide6.QtGui import QFont, QKeySequence, QPixmap, QShortcut, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QAbstractItemView, QDialog, QSplitter, QCheckBox, QSlider, QMessageBox)
from .services import BiliAPI, Job
from .player import PlayerTile
from .sidebar import RoomList, AvatarStore
from .search_dialog import SearchDialog
from .icons import decorate, icon
from .widgets import BelowComboBox as QComboBox, StudioSpinBox as QSpinBox
from .payment_dialog import PaymentDialog
from .payments import PaymentAPI
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
        saved_favorites = self.state.get('favorites')
        self.favorites = set(self.rooms if saved_favorites is None else saved_favorites)
        self.avatars = AvatarStore(self.root / 'user-data/avatars', self, enabled=not demo)
        self.avatar_metadata_pending = set()
        self.avatar_pool = QThreadPool(self)
        self.avatar_pool.setMaxThreadCount(3)
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
        header.setContentsMargins(5, SIZES['gap'], 12, SIZES['gap'])
        header.setSpacing(SIZES['gap'])
        self.account_ticket = 0
        self.account = button('正在检查登录…' if self.cookies.get('SESSDATA') else '未登录 · 点击登录', self.login)
        self.account.setIcon(icon('user'))
        self.account.setIconSize(QSize(SIZES['icon'], SIZES['icon']))
        self.account.setToolTip('查看当前登录状态，点击扫码登录或切换账号')
        header.addWidget(self.account)
        header.addStretch()
        self.layout_choice = QComboBox()
        for value, title in [(1, '单画面'), (2, '双画面'), (4, '四宫格'), (6, '六宫格'), (9, '九宫格')]:
            self.layout_choice.addItem(title, value)
        self.layout_choice.setCurrentIndex(max(0, self.layout_choice.findData(self.count)))
        self.layout_choice.currentIndexChanged.connect(self.change_layout)
        header.addWidget(self.layout_choice)
        self.controls_toggle = button('控制条', checkable=True)
        self.chat_toggle = button('弹幕', checkable=True)
        decorate(self.controls_toggle, 'controls', '显示 / 收起播放控制', 32)
        decorate(self.chat_toggle, 'chat', '显示 / 隐藏所有直播间的聊天  Ctrl+J', 32)
        for widget in (self.controls_toggle, self.chat_toggle):
            header.addWidget(widget)
        self.settings_button = decorate(button('', lambda: self.chat_settings.show()), 'settings', '弹幕设置', 32)
        header.addWidget(self.settings_button)
        self.add = decorate(button('', lambda: self.open_search(self.active)), 'add', '添加直播间  Ctrl+K', 32)
        header.addWidget(self.add)
        self.info_button = decorate(button('', self.show_help), 'info', '操作指引与快捷键', 32)
        header.addWidget(self.info_button)
        outer.addWidget(header_frame)

        self.library = self.build_library()
        self.video_area = QWidget()
        self.video_grid = QGridLayout(self.video_area)
        self.video_grid.setContentsMargins(0, 0, 0, 0)
        self.video_grid.setSpacing(8)
        self.tiles = [PlayerTile(index, instance, self.cookies, self) for index in range(9)]
        for tile in self.tiles:
            tile.selected.connect(self.select_tile)
            tile.swap_requested.connect(self.swap_tiles)
            tile.gift_requested.connect(self.open_payment)
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
            tile.chat_tabs.setCurrentIndex(max(0, min(3, int(saved.get('chat_filter', 0)))))
            tile.chat_toggle.setChecked(saved.get('chat_visible', self.state['chat_visible']))
            tile.toggle_chat(tile.chat_toggle.isChecked())
        self.chat_settings = self.build_chat_settings()
        self.content = QWidget()
        content = QHBoxLayout(self.content)
        content.setContentsMargins(0, SIZES['gap'], SIZES['gap'], SIZES['gap'])
        content.setSpacing(0)
        content.addWidget(self.library)
        content.addWidget(self.video_area, 1)
        outer.addWidget(self.content, 1)

        self.global_controls = QFrame()
        self.global_controls.setFixedWidth(208)
        footer = QHBoxLayout(self.global_controls)
        footer.setContentsMargins(0, 0, 8, 0)
        footer.setSpacing(3)
        self.pause_all = decorate(button('', self.toggle_all_pause, checkable=True), 'pause', '全部暂停', 32)
        footer.addWidget(self.pause_all)
        self.reload_button = decorate(button('', self.reload_all), 'reload', '全部重连', 32)
        footer.addWidget(self.reload_button)
        self.mute_all = decorate(button('', self.toggle_all_mute, checkable=True), 'volume', '全部静音', 32)
        footer.addWidget(self.mute_all)
        self.master_volume = QSlider(Qt.Horizontal)
        self.master_volume.setRange(0, 100)
        self.master_volume.setValue(self.state['volume'])
        self.master_volume.setFixedWidth(90)
        self.master_volume.setToolTip(f'统一音量 {self.master_volume.value()}%')
        self.master_volume.valueChanged.connect(self.set_all_volume)
        footer.addWidget(self.master_volume)
        header.insertWidget(header.indexOf(self.layout_choice), self.global_controls)
        self.help_dialog = self.build_help()

        self.controls_toggle.toggled.connect(self.toggle_controls)
        self.controls_toggle.setChecked(bool(self.state['controls_visible']))
        self.chat_toggle.setChecked(any(t.chat_toggle.isChecked() for t in self.tiles))
        self.chat_toggle.toggled.connect(self.toggle_chat)
        self.toggle_controls(self.controls_toggle.isChecked())
        self.shortcuts = []
        for keys, callback in [('Ctrl+K', lambda: self.open_search(self.active)), ('Ctrl+J', self.chat_toggle.click),
                               ('F11', self.toggle_fullscreen),
                               ('Escape', self.exit_focus)]:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.refresh_library()
        self.arrange()
        self.ready = True
        self.select_tile(0)
        self.favorite_poll_pending = False
        self.favorite_timer = QTimer(self)
        self.favorite_timer.setInterval(30000)
        self.favorite_timer.timeout.connect(self.refresh_favorite_status)
        self.account_timer = QTimer(self)
        self.account_timer.setInterval(300000)
        self.account_timer.timeout.connect(self.refresh_account_status)
        if not demo:
            QTimer.singleShot(100, self.restore_rooms)
            QTimer.singleShot(250, self.hydrate_avatars)
            QTimer.singleShot(0, self.refresh_account_status)
            QTimer.singleShot(500, self.refresh_favorite_status)
            self.favorite_timer.start()
            self.account_timer.start()

    def build_help(self):
        dialog = QDialog(self, Qt.Popup)
        dialog.setObjectName('HelpPopup')
        box = QVBoxLayout(dialog)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(14)
        box.addWidget(label('操作指引', 'Heading'))
        guide = label('点击头像：优先填入空白窗口，已打开则定位\n窗口已满时点击不会替换；拖拽可指定窗口\n拖动窗口顶部主播名称栏到另一窗口：交换位置\n拖动视频与聊天之间的分隔线调整栏宽\n悬停图标查看功能\n\nCtrl+K   添加直播间\nCtrl+J    显示 / 收起所有弹幕\nF11       全屏\nEsc       退出全屏或单画面聚焦')
        box.addWidget(guide)
        self.notice = label('')
        self.notice.setWordWrap(True)
        box.addWidget(self.notice)
        return dialog

    def show_help(self):
        self.help_dialog.adjustSize()
        point = self.info_button.mapToGlobal(QPoint(self.info_button.width(), self.info_button.height() + 5))
        self.help_dialog.move(point.x() - self.help_dialog.width(), point.y())
        self.help_dialog.show()

    def build_library(self):
        frame = QFrame()
        frame.setObjectName('Library')
        frame.setFixedWidth(SIZES['rail'])
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.room_list = RoomList(self.avatars)
        self.room_list.remove_requested.connect(lambda room: self.set_favorite(room, False))
        self.room_list.itemClicked.connect(self.activate_library)
        self.room_list.itemActivated.connect(self.activate_library)
        box.addWidget(self.room_list, 1)
        self.library_add = button('', lambda: self.open_search(self.active))
        self.library_add.setIcon(icon('add'))
        self.library_add.setIconSize(QSize(SIZES['icon'], SIZES['icon']))
        self.library_add.setObjectName('SidebarAdd')
        self.library_add.setMinimumHeight(36)
        self.library_add.setToolTip('添加直播间  Ctrl+K')
        self.library_add.setAccessibleName('添加直播间')
        box.addWidget(self.library_add)
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
        for room in sorted(self.rooms.values(), key=lambda room: not room.get('live', False)):
            if room['id'] not in self.favorites:
                continue
            state = '● 直播中' if room.get('live') else '○ 未开播'
            item = QListWidgetItem(room['name'])
            item.setToolTip(f'{room["name"]} · {state}\n{room.get("title", "")}')
            item.setData(Qt.UserRole, room)
            item.setSizeHint(QSize(SIZES['rail'], SIZES['rail']))
            self.room_list.addItem(item)
            if room['id'] == selected_id:
                self.room_list.setCurrentItem(item)
        self.sync_sidebar_visible()

    def hydrate_avatars(self):
        if self.demo or self.closing:
            return
        for rid, room in self.rooms.items():
            if room.get('face') or rid in self.avatar_metadata_pending:
                continue
            self.avatar_metadata_pending.add(rid)
            api = BiliAPI(self.cookies)
            job = Job(lambda r=rid, a=api: a.room(r))
            job.signals.done.connect(lambda data, r=rid: self.avatar_metadata_ready(r, data))
            self.avatar_pool.start(job)

    def avatar_metadata_ready(self, rid, data):
        if not self.closing and rid in self.rooms:
            self.rooms[rid].update(data)
            self.refresh_library()
            self.save()

    def activate_library(self, item):
        if not item:
            return
        rid = item.data(Qt.UserRole)['id']
        for tile in self.tiles:
            if tile.room and tile.room['id'] == rid:
                if tile.suspended:
                    self.focus_tile(tile.index)
                else:
                    self.select_tile(tile.index)
                return
        for tile in self.tiles[:self.count]:
            if tile.room is None:
                tile.set_room(item.data(Qt.UserRole))
                return

    def open_payment(self, index):
        room = self.tiles[index].room
        if not room:
            return
        for dialog in self.dialogs:
            if isinstance(dialog, PaymentDialog) and dialog.isVisible():
                dialog.raise_()
                dialog.activateWindow()
                return
        dialog = PaymentDialog(room, self.cookies, self)
        self.dialogs.append(dialog)
        dialog.show()

    def open_search(self, target=0):
        target = target if 0 <= target < self.count else 0
        dialog = SearchDialog(self.cookies, target, self.count, self)
        dialog.rooms_added.connect(self.add_rooms)
        dialog.favorite_changed.connect(self.set_favorite)
        self.dialogs.append(dialog)
        dialog.show()
        dialog.input.setFocus()

    def add_rooms(self, rooms, target):
        for room in rooms:
            self.rooms[room['id']] = room
            if target == -1:
                self.favorites.add(room['id'])
        if target >= 0:
            targets = ([target] if not self.tiles[target].room else []) + [i for i in range(self.count) if i != target and not self.tiles[i].room]
            for room, index in zip(rooms, targets):
                self.tiles[index].set_room(room)
        self.refresh_library()
        self.notice.setText(f'已处理 {len(rooms)} 个直播间。侧栏显示已收藏的主播。')
        self.hydrate_avatars()
        self.save()

    def set_favorite(self, room, added):
        self.rooms[room['id']] = room
        if added:
            self.favorites.add(room['id'])
        else:
            self.favorites.discard(room['id'])
        self.refresh_library()
        for dialog in self.dialogs:
            if isinstance(dialog, SearchDialog) and dialog.isVisible():
                dialog.sync_favorites(self.rooms, self.favorites)
        self.save()

    def play_library(self, item):
        if item:
            self.tiles[self.active].set_room(item.data(Qt.UserRole))

    def remove_library(self):
        item = self.room_list.currentItem()
        if item:
            self.set_favorite(item.data(Qt.UserRole), False)

    def select_tile(self, index):
        if not 0 <= index < len(self.tiles):
            return
        self.active = index
        for tile in self.tiles:
            tile.set_active(tile.index == index)
        room = self.tiles[index].room
        self.room_list.active_room = room['id'] if room else None
        self.sync_sidebar_visible()

    def sync_sidebar_visible(self):
        if not hasattr(self, 'tiles'):
            return
        indices = [self.focused] if self.focused is not None else range(self.count)
        self.room_list.visible_rooms = {self.tiles[i].room['id'] for i in indices if self.tiles[i].room}
        self.room_list.viewport().update()

    def tile_changed(self):
        if self.ready:
            visible = [t for t in self.tiles[:self.count] if t.room]
            muted = bool(visible) and all(t.muted for t in visible)
            self.mute_all.blockSignals(True)
            self.mute_all.setChecked(muted)
            decorate(self.mute_all, 'muted' if muted else 'volume', '取消全部静音' if muted else '全部静音', 32)
            self.mute_all.blockSignals(False)
            room = self.tiles[self.active].room
            self.room_list.active_room = room['id'] if room else None
            self.sync_sidebar_visible()
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
            tile.focus_button.setIcon(icon('collapse' if self.focused == tile.index else 'expand'))
            tile.focus_button.setToolTip('返回多屏' if self.focused == tile.index else '放大这个画面')
        self.sync_sidebar_visible()

    def swap_tiles(self, source, target):
        if self.focused is not None or source == target or not (0 <= source < self.count and 0 <= target < self.count):
            return
        active_tile = self.tiles[self.active]
        self.tiles[source], self.tiles[target] = self.tiles[target], self.tiles[source]
        for index in (source, target):
            self.tiles[index].index = index
            self.tiles[index].update_title()
        self.arrange()
        self.select_tile(active_tile.index)
        self.save()

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
            tile.refresh_chat()
        self.save()

    def set_follow(self, follow):
        for tile in self.tiles:
            tile.chat_view.follow = follow
            if follow:
                tile.chat_view.verticalScrollBar().setValue(tile.chat_view.verticalScrollBar().maximum())
        self.save()

    def set_all_volume(self, value):
        self.master_volume.setToolTip(f'统一音量 {value}%')
        for tile in self.tiles:
            tile.volume.setValue(value)
        self.save()

    def toggle_all_pause(self, paused):
        for tile in self.tiles:
            if tile.room and tile.paused != paused:
                tile.toggle_pause()
        decorate(self.pause_all, 'play' if paused else 'pause', '全部继续' if paused else '全部暂停', 32)

    def toggle_all_mute(self, muted):
        decorate(self.mute_all, 'muted' if muted else 'volume', '取消全部静音' if muted else '全部静音', 32)
        for tile in self.tiles:
            tile.set_muted(muted)

    def solo_tile(self, index):
        for tile in self.tiles:
            tile.set_muted(tile.index != index)
        self.mute_all.blockSignals(True)
        self.mute_all.setChecked(False)
        decorate(self.mute_all, 'volume', '全部静音', 32)
        self.mute_all.blockSignals(False)
        self.select_tile(index)

    def reload_all(self):
        for tile in self.tiles:
            if not tile.suspended:
                tile.reload(reconnect_chat=True)

    def refresh_account_status(self):
        self.account_ticket += 1
        ticket = self.account_ticket
        if not self.cookies.get('SESSDATA'):
            self.account.setText('未登录 · 点击登录')
            self.account.setToolTip('点击扫码登录 B 站')
            return
        self.account.setText('正在检查登录…')
        api = BiliAPI(self.cookies)
        job = Job(lambda: api.get('https://api.bilibili.com/x/web-interface/nav'))
        job.signals.done.connect(lambda data: self.account_status_ready(ticket, data))
        job.signals.error.connect(lambda error: self.account_status_failed(ticket, error))
        QThreadPool.globalInstance().start(job)

    def account_status_ready(self, ticket, data):
        if self.closing or ticket != self.account_ticket:
            return
        if data.get('isLogin'):
            name = str(data.get('uname') or data.get('mid') or 'B 站账号')
            short = self.account.fontMetrics().elidedText(name, Qt.ElideRight, 170)
            self.account.setText(f'已登录 · {short}')
            self.account.setToolTip(f'{name}\n点击扫码切换账号')
        else:
            self.account.setText('登录已过期 · 重新登录')
            self.account.setToolTip('当前登录已失效，点击重新扫码')

    def account_status_failed(self, ticket, error):
        if self.closing or ticket != self.account_ticket:
            return
        if '(-101)' in error:
            self.account_status_ready(ticket, {'isLogin': False})
        else:
            self.account.setText('登录状态待确认')
            self.account.setToolTip(error + '\n点击扫码登录')

    def refresh_favorite_status(self):
        if self.demo or self.closing or self.favorite_poll_pending or not self.favorites:
            return
        rooms = [dict(self.rooms[rid]) for rid in self.favorites if rid in self.rooms]
        self.favorite_poll_pending = True
        api = BiliAPI(self.cookies)
        job = Job(lambda: api.room_statuses(rooms))
        job.signals.done.connect(self.favorite_status_ready)
        job.signals.error.connect(self.favorite_status_failed)
        QThreadPool.globalInstance().start(job)

    def favorite_status_failed(self, error):
        self.favorite_poll_pending = False
        # Keep last known states; a failed request does not mean offline.

    def favorite_status_ready(self, rooms):
        self.favorite_poll_pending = False
        if self.closing:
            return
        for room in rooms:
            if room['id'] in self.favorites and room['id'] in self.rooms:
                self.rooms[room['id']].update(room)
        self.refresh_library()
        for dialog in self.dialogs:
            if isinstance(dialog, SearchDialog) and dialog.isVisible():
                dialog.sync_favorites(self.rooms, self.favorites)
        self.save()

    def login(self):
        if any(isinstance(d, PaymentDialog) and d.busy for d in self.dialogs):
            self.notice.setText('请等送礼面板完成当前操作后再切换账号。')
            return
        dialog = LoginDialog(self)
        dialog.authenticated.connect(self.logged_in)
        self.dialogs.append(dialog)
        dialog.show()

    def logged_in(self, cookies):
        self.cookies = cookies
        save_json(self.root / 'user-data' / 'credentials.json', cookies)
        self.refresh_account_status()
        for tile in self.tiles:
            tile.cookies = cookies
            if tile.room:
                tile.composer.set_room(tile.room, cookies)
                tile.reload(reconnect_chat=True)
        self.notice.setText('登录成功，已刷新视频与聊天连接。')
        for dialog in self.dialogs:
            if isinstance(dialog, PaymentDialog) and dialog.isVisible() and not dialog.busy:
                dialog.api = PaymentAPI(cookies)
                if not dialog.terminal:
                    dialog.reload()
            if isinstance(dialog, SearchDialog) and dialog.isVisible():
                dialog.refresh_account(cookies)

    def restore_rooms(self):
        for index, rid in enumerate(self.state['slots'][:9]):
            if rid and rid in self.rooms:
                self.tiles[index].set_room(self.rooms[rid])
        self.select_tile(0)

    def save(self):
        if not self.ready or self.closing or self.demo:
            return
        self.state.pop('splitter', None)
        self.state.pop('library_visible', None)
        self.state.update({'rooms': list(self.rooms.values()), 'slots': [tile.room['id'] if tile.room else None for tile in self.tiles],
                          'favorites': sorted(self.favorites),
                          'layout': self.count, 'chat_visible': self.chat_toggle.isChecked(),
                          'controls_visible': self.controls_toggle.isChecked(),
                          'chat_font': self.chat_font.value(), 'chat_follow': self.follow.isChecked(),
                          'chat_names': self.show_names.isChecked(),
                          'volume': self.master_volume.value(),
                          'slot_settings': {str(tile.index): {'volume': tile.volume.value(), 'muted': tile.muted,
                                            'quality': tile.quality.currentData(),
                                            'chat_visible': tile.chat_toggle.isChecked(),
                                            'chat_width': tile.chat_width,
                                            'chat_filter': tile.chat_tabs.currentIndex()} for tile in self.tiles}})
        save_json(self.state_path, self.state)

    def closeEvent(self, event):
        if any(tile.composer.sending for tile in self.tiles):
            event.ignore()
            return
        if any(isinstance(d, PaymentDialog) and d.busy and d.isVisible() for d in self.dialogs):
            event.ignore()
            return
        if not self.closing:
            self.favorite_timer.stop()
            self.account_timer.stop()
            self.account_ticket += 1
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
    from .runtime import configure_vlc, create_vlc_instance
    dll_handle = None if demo else configure_vlc(root)
    app = QApplication(sys.argv)
    app.setApplicationName('DD Monitor Studio')
    app.setWindowIcon(QIcon(str(root / 'favicon.ico')))
    app.setStyle('Fusion')
    app.setStyleSheet(stylesheet())
    instance = None
    if not demo:
        instance = create_vlc_instance()
    if not demo and not instance:
        QMessageBox.critical(None, '播放器初始化失败', '找不到 VLC 运行库，请检查 libvlc.dll 和 plugins 目录。')
        return 1
    window = StudioWindow(root, instance, demo)
    window.closed.connect(app.quit)
    window.show()
    result = app.exec()
    QThreadPool.globalInstance().waitForDone(15000)
    window.avatar_pool.waitForDone(15000)
    if instance:
        instance.release()
    return result
