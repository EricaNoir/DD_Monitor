from collections import deque
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool
from PySide6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QComboBox, QStackedWidget, QSplitter)
from .chat import ChatView
from .services import BiliAPI, Job, ChatWorker


class PlayerTile(QFrame):
    selected = Signal(int)
    add_requested = Signal(int)
    chat_requested = Signal(int)
    focus_requested = Signal(int)
    solo_requested = Signal(int)
    changed = Signal()
    chat_received = Signal(int, dict)
    room_resolved = Signal(dict)

    def __init__(self, index, instance, cookies, parent=None):
        super().__init__(parent)
        self.index, self.instance, self.cookies = index, instance, cookies
        self.room = None
        self.generation = 0
        self.chat_worker = None
        self.retiring = []
        self.history = deque(maxlen=500)
        self.chat_status = '选择直播间后显示聊天'
        self.muted = index != 0
        self.paused = False
        self.suspended = False
        self.request_pending = False
        self.chat_width = 195
        self.setObjectName('VideoTile')
        self.setMinimumSize(290, 205)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(9, 6, 9, 6)
        self.name = QPushButton(f'{index + 1:02d}   选择一个直播间')
        self.name.setObjectName('Ghost')
        self.name.setStyleSheet('text-align: left; border: 0; font-weight: 600;')
        self.name.clicked.connect(lambda: self.selected.emit(index))
        header.addWidget(self.name, 1)
        for label, tooltip, callback in [('+', '添加或替换直播间', lambda: self.add_requested.emit(index)),
                                          ('放大', '聚焦此画面 / 返回多屏', lambda: self.focus_requested.emit(index))]:
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.setFixedHeight(30)
            button.clicked.connect(callback)
            header.addWidget(button)
        self.chat_toggle = QPushButton('弹幕')
        self.chat_toggle.setCheckable(True)
        self.chat_toggle.setChecked(True)
        self.chat_toggle.setToolTip('显示 / 收起这个直播间的聊天')
        header.addWidget(self.chat_toggle)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        self.empty_title = QLabel(f'画面 {index + 1:02d}')
        self.empty_title.setObjectName('Heading')
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_hint = QLabel('搜索 UP 主，或粘贴直播间链接')
        self.empty_hint.setObjectName('Hint')
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.empty_hint)
        self.empty_add = QPushButton('＋ 添加直播间')
        self.empty_add.setObjectName('Primary')
        self.empty_add.clicked.connect(lambda: self.add_requested.emit(index))
        empty_layout.addWidget(self.empty_add, alignment=Qt.AlignCenter)
        empty_layout.addStretch()
        self.stack.addWidget(self.empty)
        self.surface = QFrame()
        self.surface.setObjectName('Surface')
        self.surface.setAttribute(Qt.WA_NativeWindow)
        self.stack.addWidget(self.surface)
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(4)
        self.stack.setMinimumWidth(160)
        self.content_splitter.addWidget(self.stack)
        self.chat_panel = QFrame()
        self.chat_panel.setObjectName('RoomChat')
        self.chat_panel.setMinimumWidth(145)
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(6, 6, 6, 5)
        chat_layout.setSpacing(4)
        self.chat_view = ChatView()
        chat_layout.addWidget(self.chat_view, 1)
        chat_footer = QHBoxLayout()
        self.chat_connection = QLabel('等待连接')
        self.chat_connection.setObjectName('Muted')
        self.chat_connection.setToolTip(self.chat_status)
        chat_footer.addWidget(self.chat_connection, 1)
        self.chat_bottom = QPushButton('最新 ↓')
        self.chat_bottom.setToolTip('回到最新消息')
        self.chat_bottom.clicked.connect(lambda: self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum()))
        chat_footer.addWidget(self.chat_bottom)
        chat_layout.addLayout(chat_footer)
        self.content_splitter.addWidget(self.chat_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([420, self.chat_width])
        self.content_splitter.splitterMoved.connect(self.remember_chat_width)
        self.chat_toggle.toggled.connect(self.toggle_chat)
        layout.addWidget(self.content_splitter, 1)
        self.player = instance.media_player_new() if instance else None
        if self.player:
            self.player.set_hwnd(int(self.surface.winId()))
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)

        self.controls = QWidget()
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(8, 5, 8, 5)
        controls.setSpacing(5)
        self.play_button = QPushButton('暂停')
        self.play_button.clicked.connect(self.toggle_pause)
        controls.addWidget(self.play_button)
        self.mute_button = QPushButton('静音')
        self.mute_button.setCheckable(True)
        self.mute_button.setChecked(self.muted)
        self.mute_button.toggled.connect(self.set_muted)
        controls.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(35)
        self.volume.setMinimumWidth(45)
        self.volume.setToolTip('此画面音量')
        self.volume.valueChanged.connect(self.set_volume)
        controls.addWidget(self.volume, 1)
        self.solo = QPushButton('独听')
        self.solo.setToolTip('只听这个直播间')
        self.solo.clicked.connect(lambda: self.solo_requested.emit(index))
        controls.addWidget(self.solo)
        self.quality = QComboBox()
        for title, value in [('流畅', 80), ('超清', 250), ('蓝光', 400), ('原画', 10000)]:
            self.quality.addItem(title, value)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip('当前画面的清晰度')
        self.quality.currentIndexChanged.connect(lambda: self.reload())
        controls.addWidget(self.quality)
        self.retry = QPushButton('重连')
        self.retry.setToolTip('重新连接视频和聊天')
        self.retry.clicked.connect(lambda: self.reload(reconnect_chat=True))
        controls.addWidget(self.retry)
        self.remove = QPushButton('×')
        self.remove.setToolTip('关闭当前直播，保留在主播库')
        self.remove.clicked.connect(lambda: self.clear())
        controls.addWidget(self.remove)
        layout.addWidget(self.controls)
        self.status = QLabel('等待添加 · 支持拖入主播')
        self.status.setObjectName('Muted')
        self.status.setWordWrap(True)
        self.status.setContentsMargins(10, 0, 10, 5)
        layout.addWidget(self.status)
        self.monitor = QTimer(self)
        self.monitor.timeout.connect(self.monitor_playback)
        self.monitor.start(1000)
        self.apply_audio()

    def remember_chat_width(self, *_):
        if self.chat_toggle.isChecked():
            self.chat_width = self.content_splitter.sizes()[1]
        self.changed.emit()

    def toggle_chat(self, shown):
        if not shown and not self.chat_panel.isHidden():
            self.chat_width = self.content_splitter.sizes()[1] or self.chat_width
        self.chat_panel.setVisible(shown)
        if shown:
            total = sum(self.content_splitter.sizes())
            self.content_splitter.setSizes([max(160, total - self.chat_width), self.chat_width])
        self.changed.emit()

    def set_active(self, value):
        self.setProperty('active', value)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_volume(self, value):
        self.volume.setToolTip(f'音量 {value}%')
        self.apply_audio()
        self.changed.emit()

    def set_muted(self, value):
        self.muted = bool(value)
        self.mute_button.setChecked(self.muted)
        self.apply_audio()
        self.changed.emit()

    def apply_audio(self):
        if self.player:
            self.player.audio_set_volume(self.volume.value())
            self.player.audio_set_mute(self.muted or self.suspended)

    def toggle_pause(self):
        if not self.room:
            return
        self.paused = not self.paused
        self.play_button.setText('播放' if self.paused else '暂停')
        if self.player:
            self.player.set_pause(self.paused or self.suspended)

    def suspend(self, hidden):
        self.suspended = hidden
        if self.player and self.room:
            self.player.set_pause(hidden or self.paused)
            self.apply_audio()

    def set_room(self, room):
        self.clear(emit=False)
        self.room = dict(room)
        self.name.setText(f'{self.index + 1:02d}   {room["name"]}')
        self.name.setToolTip(room.get('title', '') + '\n房号 ' + room['id'])
        self.selected.emit(self.index)
        self.start_chat()
        self.reload()
        self.changed.emit()

    def reload(self, reconnect_chat=False):
        if not self.room:
            return
        if reconnect_chat:
            self.start_chat()
        self.generation += 1
        ticket = self.generation
        self.request_pending = True
        self.status.setText('正在获取直播画面…')
        self.empty_hint.setText('正在连接直播间…')
        api = BiliAPI(self.cookies)
        rid, quality = self.room['id'], self.quality.currentData()
        task = Job(lambda: api.stream(rid, quality))
        task.signals.done.connect(lambda result: self.got_stream(ticket, result))
        task.signals.error.connect(lambda error: self.failed(ticket, error))
        QThreadPool.globalInstance().start(task)

    def got_stream(self, ticket, result):
        if ticket != self.generation or not self.room:
            return
        self.request_pending = False
        self.room = result['room']
        self.room_resolved.emit(self.room)
        self.name.setText(f'{self.index + 1:02d}   {self.room["name"]}')
        if not result['url']:
            if self.player:
                self.player.stop()
            self.stack.setCurrentIndex(0)
            self.empty_title.setText(self.room['name'])
            self.empty_hint.setText('主播暂未开播，可以查看聊天或切换其他房间')
            self.status.setText('未开播 · 点击 ↻ 重新检查')
            return
        if not self.player:
            self.failed(ticket, 'VLC 未加载，无法播放')
            return
        media = self.instance.media_new(result['url'])
        media.add_option(':network-caching=1200')
        media.add_option(':http-user-agent=Mozilla/5.0')
        media.add_option(':http-referrer=https://live.bilibili.com/')
        self.player.set_media(media)
        self.player.play()
        media.release()
        self.stack.setCurrentIndex(1)
        self.status.setText('正在缓冲…')
        self.apply_audio()

    def failed(self, ticket, error):
        if ticket != self.generation:
            return
        self.request_pending = False
        self.status.setText(error)
        self.empty_hint.setText(error + '\n点击下方 ↻ 重试')

    def monitor_playback(self):
        if not self.player or not self.room or self.request_pending:
            return
        state = str(self.player.get_state()).split('.')[-1]
        if state == 'Playing':
            self.apply_audio()
            if self.paused or self.suspended:
                self.player.set_pause(True)
            self.status.setText('直播中  ·  ' + self.room.get('title', ''))
        elif state == 'Error':
            self.status.setText('播放连接失败 · 点击 ↻ 重试或降低清晰度')
        elif state == 'Paused':
            self.status.setText('已暂停')

    def start_chat(self):
        self.retire_chat()
        if self.room:
            worker = ChatWorker(self.room['id'], self.cookies, self)
            self.chat_worker = worker
            worker.message.connect(lambda msg: self.receive_chat(worker, msg))
            worker.status.connect(lambda text: self.set_chat_status(worker, text))
            worker.start()

    def receive_chat(self, worker, message):
        if worker is self.chat_worker:
            self.history.append(message)
            self.chat_view.add_message(message)
            self.chat_received.emit(self.index, message)

    def set_chat_status(self, worker, text):
        if worker is self.chat_worker:
            self.chat_status = text
            self.chat_connection.setText('已连接' if '已连接' in text else ('连接中' if '连接' in text else text))
            self.chat_connection.setToolTip(text)

    def retire_chat(self):
        worker = self.chat_worker
        self.chat_worker = None
        if worker:
            worker.stop()
            self.retiring.append(worker)
            worker.finished.connect(lambda: self.retired(worker))

    def retired(self, worker):
        if worker in self.retiring:
            self.retiring.remove(worker)
        worker.deleteLater()

    def clear(self, emit=True):
        self.generation += 1
        self.request_pending = False
        if self.player:
            self.player.stop()
        self.retire_chat()
        self.history.clear()
        self.chat_view.clear()
        self.chat_connection.setText('等待连接')
        self.room = None
        self.paused = False
        self.play_button.setText('暂停')
        self.name.setText(f'{self.index + 1:02d}   选择一个直播间')
        self.empty_title.setText(f'画面 {self.index + 1:02d}')
        self.empty_hint.setText('搜索 UP 主，或粘贴直播间链接')
        self.stack.setCurrentIndex(0)
        self.status.setText('等待添加 · 支持拖入主播')
        self.chat_status = '选择直播间后显示聊天'
        if emit:
            self.changed.emit()

    def shutdown(self):
        self.monitor.stop()
        self.clear(emit=False)
        for worker in list(self.retiring):
            worker.stop()
        if self.player:
            self.player.release()
            self.player = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-dd-room'):
            event.acceptProposedAction()

    def dropEvent(self, event):
        import json
        try:
            room = json.loads(bytes(event.mimeData().data('application/x-dd-room')))
            self.set_room(room)
            event.acceptProposedAction()
        except (ValueError, KeyError):
            pass
