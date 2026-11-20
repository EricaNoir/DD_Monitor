from .theme import COLORS, SIZES
from collections import deque
import time
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool, QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QStackedWidget, QSplitter, QMenu, QWidgetAction,
                               QSizePolicy, QStylePainter, QStyleOptionButton, QStyle, QApplication, QTabBar)
from .chat import ChatView
from .composer import ChatComposer
from .sc_overlay import SCOverlay
from .services import BiliAPI, Job, ChatWorker
from .icons import decorate, icon
from .widgets import BelowComboBox as QComboBox, StatusDot
from .audio_balance import LevelController
from .room_metrics import elapsed_text


class RoomTitle(QPushButton):
    drag_requested = Signal()

    def __init__(self, text):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(64)
        self.drag_start = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        self.drag_start = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.drag_start is not None and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self.drag_start).manhattanLength() >= QApplication.startDragDistance()):
            self.drag_start = None
            self.setDown(False)
            self.drag_requested.emit()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, self.width() - 14))
        painter.drawControl(QStyle.CE_PushButton, option)


class PlayerTile(QFrame):
    selected = Signal(int)
    swap_requested = Signal(int, int)
    gift_requested = Signal(int)
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
        self.audience = None
        self.audience_at = 0.0
        self.generation = 0
        self.chat_worker = None
        self.retiring = []
        self.history = deque(maxlen=500)
        self.deleted_sc = deque(maxlen=500)
        self.chat_status = '选择直播间后显示聊天'
        self.pending_sent = None
        self.muted = index != 0
        self.paused = False
        self.suspended = False
        self._audio_volume = None
        self._audio_muted = None
        self._audio_pending = False
        self.audio_balanced = False
        self.owns_instance = False
        self.level_controller = LevelController()
        self._balance_gain = 0.0
        self._balance_position = None
        self._balance_progress = None
        self.request_pending = False
        self.request_started = 0.0
        self.retry_at = None
        self.retry_attempts = 0
        self.progress_at = time.monotonic()
        self.media_time = None
        self.healthy_since = None
        self.chat_width = 195
        self.setObjectName('VideoTile')
        self.setMinimumSize(290, 205)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.toolbar = QWidget()
        self.toolbar.setObjectName('TileToolbar')
        self.toolbar.setFixedHeight(SIZES['tile_toolbar'])
        header = QHBoxLayout(self.toolbar)
        header.setContentsMargins(6, 3, 6, 3)
        header.setSpacing(SIZES['control_gap'])
        self.name = RoomTitle(f'{index + 1:02d}   选择一个直播间')
        self.name.setObjectName('Ghost')
        self.name.setStyleSheet('text-align: left; border: 0; font-weight: 600;')
        self.name.clicked.connect(lambda: self.selected.emit(self.index))
        self.name.drag_requested.connect(self.start_tile_drag)
        header.addWidget(self.name, 1)
        self.status_light = StatusDot()
        header.addWidget(self.status_light)
        for label, tooltip, callback in [('放大', '聚焦此画面 / 返回多屏', lambda: self.focus_requested.emit(self.index))]:
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.setFixedHeight(30)
            button.clicked.connect(callback)
            header.addWidget(button)
            self.focus_button = decorate(button, 'expand', tooltip)
        self.chat_toggle = QPushButton('弹幕')
        self.gift_button = decorate(QPushButton(), 'gift', '送礼物 / 发 SC')
        self.gift_button.setEnabled(False)
        self.gift_button.clicked.connect(lambda: self.gift_requested.emit(self.index))
        header.addWidget(self.gift_button)
        self.chat_toggle.setCheckable(True)
        self.chat_toggle.setChecked(True)
        self.chat_toggle.setToolTip('显示 / 收起这个直播间的聊天')
        decorate(self.chat_toggle, 'chat', '显示 / 收起这个直播间的聊天')
        header.addWidget(self.chat_toggle)
        self.remove = QPushButton('×')
        self.remove.setObjectName('ClosePlayer')
        self.remove.setFixedSize(28, 28)
        self.remove.setToolTip('关闭当前直播，保留在主播库')
        self.remove.clicked.connect(lambda: self.clear())
        decorate(self.remove, 'close', '关闭当前直播，保留在主播库')
        header.addWidget(self.remove)
        layout.addWidget(self.toolbar)
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
        self.empty_add = QPushButton('添加直播间')
        self.empty_add.setIcon(icon('add', COLORS['inverse']))
        self.empty_add.setIconSize(self.remove.iconSize())
        self.empty_add.setObjectName('Primary')
        self.empty_add.clicked.connect(lambda: self.add_requested.emit(self.index))
        empty_layout.addWidget(self.empty_add, alignment=Qt.AlignCenter)
        empty_layout.addStretch()
        self.stack.addWidget(self.empty)
        self.surface = QFrame()
        self.surface.setObjectName('Surface')
        self.surface.setAttribute(Qt.WA_NativeWindow)
        self.stack.addWidget(self.surface)
        self.sc_overlay = SCOverlay(self.stack)
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
        self.chat_tabs = QTabBar()
        self.chat_tabs.setObjectName('ChatTabs')
        self.chat_tabs.setExpanding(True)
        self.chat_tabs.setDrawBase(False)
        self.chat_tabs.setUsesScrollButtons(False)
        for title, kind in [('全部', 'all'), ('聊天', 'chat'), ('礼物', 'gift'), ('SC', 'sc')]:
            tab = self.chat_tabs.addTab(title)
            self.chat_tabs.setTabData(tab, kind)
        self.chat_tabs.currentChanged.connect(self.change_chat_filter)
        chat_layout.addWidget(self.chat_tabs)
        self.chat_view = ChatView()
        chat_layout.addWidget(self.chat_view, 1)
        self.composer = ChatComposer(self)
        chat_layout.addWidget(self.composer)
        self.refresh_chat_status()
        self.composer.message_sent.connect(self.scroll_after_send)
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
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(SIZES['control_gap'])
        self.play_button = QPushButton('暂停')
        self.play_button.clicked.connect(self.toggle_pause)
        decorate(self.play_button, 'pause', '暂停直播')
        controls.addWidget(self.play_button)
        self.mute_button = QPushButton('静音')
        self.mute_button.setCheckable(True)
        self.mute_button.setChecked(self.muted)
        self.mute_button.toggled.connect(self.set_muted)
        decorate(self.mute_button, 'muted' if self.muted else 'volume', '取消静音' if self.muted else '静音')
        controls.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(35)
        self.volume.setFixedWidth(68)
        self.volume.setFixedHeight(SIZES['compact'])
        self.volume.setToolTip('此画面音量')
        self.volume.valueChanged.connect(self.set_volume)
        controls.addWidget(self.volume, 1)
        self.solo = QPushButton('独听')
        self.solo.setToolTip('只听这个直播间')
        self.solo.clicked.connect(lambda: self.solo_requested.emit(self.index))
        decorate(self.solo, 'headphones', '只听这个直播间')
        controls.addWidget(self.solo)
        self.quality = QComboBox(compact=True)
        for title, value in [('流畅', 80), ('超清', 250), ('蓝光', 400), ('原画', 10000)]:
            self.quality.addItem(title, value)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip('当前画面的清晰度')
        self.quality.currentIndexChanged.connect(lambda: self.reload())
        controls.addWidget(self.quality)
        self.retry = QPushButton('重连')
        self.retry.setToolTip('重新连接视频和聊天')
        self.retry.clicked.connect(lambda: self.reload(reconnect_chat=True))
        decorate(self.retry, 'reload', '重新连接视频和聊天')
        controls.addWidget(self.retry)
        header.insertWidget(2, self.controls)
        self.more = QPushButton('⋯')
        self.more.setObjectName('MoreControls')
        self.more.setFixedSize(28, 28)
        self.more.setToolTip('更多直播控制')
        self.more.setAccessibleName('更多直播控制')
        decorate(self.more, 'more', '更多直播控制')
        self.more_menu = QMenu(self)
        volume_widget = QWidget()
        volume_row = QHBoxLayout(volume_widget)
        volume_row.addWidget(QLabel('音量'))
        self.menu_volume = QSlider(Qt.Horizontal)
        self.menu_volume.setRange(0, 100)
        self.menu_volume.setValue(self.volume.value())
        self.menu_volume.setFixedWidth(120)
        self.menu_volume.valueChanged.connect(self.volume.setValue)
        self.volume.valueChanged.connect(self.menu_volume.setValue)
        volume_row.addWidget(self.menu_volume)
        volume_action = QWidgetAction(self.more_menu)
        volume_action.setDefaultWidget(volume_widget)
        self.more_menu.addAction(volume_action)
        self.solo_action = self.more_menu.addAction('只听这个直播间', lambda: self.solo_requested.emit(self.index))
        self.retry_action = self.more_menu.addAction('重新连接', lambda: self.reload(reconnect_chat=True))
        self.focus_action = self.more_menu.addAction('聚焦此画面 / 返回多屏', lambda: self.focus_requested.emit(self.index))
        self.gift_action = self.more_menu.addAction('送礼物 / 发 SC', lambda: self.gift_requested.emit(self.index))
        self.more.setMenu(self.more_menu)
        header.insertWidget(header.indexOf(self.chat_toggle), self.more)
        self.metrics = QLabel()
        self.metrics.setObjectName('RoomMetrics')
        self.metrics.setTextFormat(Qt.PlainText)
        self.metrics.setAlignment(Qt.AlignVCenter)
        self.metrics.hide()
        header.insertWidget(1, self.metrics)
        self.status = QLabel(self)
        self.status.hide()
        self.set_status('等待添加 · 支持拖入主播')
        self.monitor = QTimer(self)
        self.monitor.timeout.connect(self.monitor_playback)
        self.monitor.start(1000)
        self.audio_startup = QTimer(self)
        self.audio_startup.setInterval(50)
        self.audio_startup.timeout.connect(self.finish_audio_startup)
        self.balance_timer = QTimer(self)
        self.balance_timer.setInterval(250)
        self.balance_timer.timeout.connect(self.balance_audio)
        self.apply_audio()
        self.update_toolbar()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'more'):
            self.update_toolbar()

    def update_toolbar(self):
        compact = self.width() < 640
        narrow = self.width() < 520
        for widget in (self.volume, self.solo, self.retry):
            widget.setVisible(not compact)
        self.more.setVisible(compact)
        self.focus_button.setVisible(not narrow)
        self.gift_button.setVisible(not narrow)
        self.focus_action.setVisible(narrow)
        self.gift_action.setVisible(narrow)
        if hasattr(self, 'metrics'):
            self.update_metrics()

    def update_metrics(self):
        self.gift_action.setEnabled(bool(self.room))
        self.metrics.setVisible(bool(self.room))
        if not self.room:
            return
        if self.room.get('live') is False:
            self.audience = None
            self.metrics.setText('未开播')
            self.metrics.setToolTip('主播当前未开播')
            return
        duration = elapsed_text(self.room.get('live_start'), time.time(), self.width() < 640)
        fresh = self.audience is not None and time.monotonic() - self.audience_at < 120
        people = self.audience['text'] if fresh else '—'
        self.metrics.setText(f'{duration}  在线 {people}')
        full_duration = elapsed_text(self.room.get('live_start'), time.time())
        self.metrics.setToolTip(f'本场直播时长：{full_duration}\n在线人数：{people}\n'
                               '时长从主播实际开播时间计算；在线人数由 B 站实时推送，平台数值可能有上限。\n'
                               '未收到或超过两分钟未更新时，人数显示 —。')

    def update_room_status(self, status):
        if not self.room or status.get('id') != self.room['id']:
            return
        if (status.get('live') is False or
                status.get('live_start') != self.room.get('live_start')):
            self.audience = None
        self.room.update(status)
        self.update_title()

    def receive_audience(self, worker, audience):
        if worker is self.chat_worker and self.room and self.room.get('live') is not False:
            self.audience = audience
            self.audience_at = time.monotonic()
            self.update_metrics()

    def set_status(self, text):
        self.status.setText(text)
        details = (self.room.get('name', '') + ' · ' + self.room.get('title', '') + '\n' if self.room else '') + text
        self.name.setToolTip(details)
        self.status_light.setToolTip(details)
        warning = any(word in text for word in ('失败', '超时', '中断', '停滞'))
        color = COLORS['live'] if text.startswith('直播中') else (COLORS['warning'] if warning else COLORS['offline'])
        self.status_light.set_color(color)

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
        changed = self.muted != bool(value)
        self.muted = bool(value)
        blocked = self.mute_button.blockSignals(True)
        self.mute_button.setChecked(self.muted)
        self.mute_button.blockSignals(blocked)
        decorate(self.mute_button, 'muted' if self.muted else 'volume', '取消静音' if self.muted else '静音')
        self.apply_audio()
        if changed:
            self.changed.emit()

    def apply_audio(self, force=False):
        if self.player:
            volume = self.volume.value()
            muted = self.muted or self.suspended or self.paused
            if force or self._audio_volume != volume:
                if self.player.audio_set_volume(volume) == 0:
                    self._audio_volume = volume
                else:
                    # Never unmute an output until its intended volume is set.
                    self._audio_volume = self._audio_muted = None
                    self.player.audio_set_mute(True)
                    return False
            if force or self._audio_muted != muted:
                self.player.audio_set_mute(muted)
                self._audio_muted = muted
            return True
        return False

    def set_audio_balance(self, enabled):
        enabled = bool(enabled)
        if enabled == self.audio_balanced:
            return
        if self.player:
            from .audio_balance import set_player_balance
            set_player_balance(self.player, enabled)
            # Existing outputs snapshot their filter chain. Reopen the same
            # media to apply it, retaining chat, volume, mute, pause and solo.
            state = str(self.player.get_state()).split('.')[-1]
            if state in ('Playing', 'Paused', 'Opening', 'Buffering'):
                self.player.audio_set_mute(True)
                self.player.stop()
                self._audio_volume = self._audio_muted = None
                self.player.play()
                self._audio_pending = True
                self.audio_startup.start()
                self.progress_at = time.monotonic()
                self.media_time = None
                self.healthy_since = None
        self.audio_balanced = enabled
        self.reset_balance()
        if enabled:
            self.balance_timer.start()
        else:
            self.balance_timer.stop()
            self.volume.setToolTip(f'音量 {self.volume.value()}%')

    def reset_balance(self):
        self.level_controller.reset()
        self._balance_gain = 0.0
        self._balance_position = None
        self._balance_progress = None
        if self.audio_balanced and self.player:
            from .audio_balance import set_player_gain
            set_player_gain(self.player, 0)

    def balance_audio(self):
        if not self.audio_balanced or not self.player or not self.room:
            return
        if self.paused or self.suspended or str(self.player.get_state()).split('.')[-1] != 'Playing':
            self.level_controller.samples.clear()
            self.level_controller.updated = None
            return
        now = time.monotonic()
        position = self.player.get_time()
        if position != self._balance_position:
            self._balance_position, self._balance_progress = position, now
        elif self._balance_progress is None or now - self._balance_progress > 1:
            self.level_controller.samples.clear()
            self.level_controller.updated = None
            return
        from .audio_balance import read_player_peak, set_player_gain
        try:
            gain = self.level_controller.update(read_player_peak(self.player), now)
            if abs(gain - self._balance_gain) >= .1 and set_player_gain(self.player, gain):
                self._balance_gain = gain
            self.level_controller.gain_db = self._balance_gain
            self.volume.setToolTip(f'手动音量 {self.volume.value()}%\n动态平衡补偿 {self._balance_gain:+.1f} dB')
        except (OSError, AttributeError, KeyError, RuntimeError):
            self.balance_timer.stop()
            import logging
            logging.exception('Dynamic level measurement unavailable')

    def finish_audio_startup(self):
        if not self.player or not self._audio_pending:
            self.audio_startup.stop()
            return
        state = str(self.player.get_state()).split('.')[-1]
        if state == 'Playing' and (self.paused or self.suspended):
            self.player.set_pause(True)
        if state in ('Playing', 'Paused') and self.apply_audio(force=True):
            self._audio_pending = False
            self.audio_startup.stop()
        elif state in ('Error', 'Ended'):
            self.audio_startup.stop()

    def toggle_pause(self):
        if not self.room:
            return
        self.paused = not self.paused
        decorate(self.play_button, 'play' if self.paused else 'pause', '继续播放' if self.paused else '暂停直播')
        if self.player:
            self.player.set_pause(self.paused or self.suspended)
            self.apply_audio()

    def suspend(self, hidden):
        self.suspended = hidden
        if self.player and self.room:
            self.player.set_pause(hidden or self.paused)
            self.apply_audio()

    def set_room(self, room):
        self.clear(emit=False)
        self.room = dict(room)
        self.composer.set_room(self.room, self.cookies, load=bool(self.instance))
        self.gift_button.setEnabled(True)
        self.update_title()
        self.name.setToolTip(room.get('title', '') + '\n房号 ' + room['id'])
        self.selected.emit(self.index)
        self.start_chat()
        self.reload()
        self.changed.emit()

    def update_title(self):
        self.update_metrics()
        if self.room:
            title = f'{self.index + 1:02d}   {self.room["name"]}'
            if self.room.get('title'):
                title += ' · ' + self.room['title']
            self.name.setText(title)
        else:
            self.name.setText(f'{self.index + 1:02d}   选择一个直播间')
            self.empty_title.setText(f'画面 {self.index + 1:02d}')

    def reload(self, reconnect_chat=False, automatic=False):
        if not self.room:
            return
        self.retry_at = None
        if not automatic:
            self.retry_attempts = 0
        self.request_started = time.monotonic()
        self.progress_at = self.request_started
        self.media_time = None
        self.healthy_since = None
        if reconnect_chat:
            self.start_chat()
        self.generation += 1
        ticket = self.generation
        self.request_pending = True
        self.set_status('正在获取直播画面…')
        self.empty_title.setText(self.room['name'])
        self.empty_hint.setText('正在连接直播间…')
        api = BiliAPI(self.cookies)
        rid, quality = self.room['id'], self.quality.currentData()
        task = Job(lambda: api.stream(rid, quality), owner=self)
        task.signals.done.connect(lambda result: self.got_stream(ticket, result))
        task.signals.error.connect(lambda error: self.failed(ticket, error))
        QThreadPool.globalInstance().start(task)

    def got_stream(self, ticket, result):
        if ticket != self.generation or not self.room:
            return
        self.request_pending = False
        if (result['room'].get('live') is False or
                result['room'].get('live_start') != self.room.get('live_start')):
            self.audience = None
        self.room = result['room']
        self.room_resolved.emit(self.room)
        self.update_title()
        if not result['url']:
            if self.player:
                self.player.stop()
            self.stack.setCurrentIndex(0)
            self.empty_title.setText(self.room['name'])
            self.empty_hint.setText('主播暂未开播，自动检查开播状态')
            self.set_status('未开播，自动检查开播状态')
            self.schedule_reconnect('主播暂未开播', delay=30)
            return
        if not self.player:
            self.failed(ticket, 'VLC 未加载，无法播放')
            return
        media = self.instance.media_new(result['url'])
        media.add_option(':network-caching=1200')
        media.add_option(':http-user-agent=Mozilla/5.0')
        media.add_option(':http-referrer=https://live.bilibili.com/')
        self.player.set_media(media)
        self.reset_balance()
        self._audio_volume = self._audio_muted = None
        self.apply_audio(force=True)
        self.player.play()
        self.progress_at = time.monotonic()
        self._audio_pending = True
        self.audio_startup.start()
        media.release()
        self.stack.setCurrentIndex(1)
        self.set_status('正在缓冲…')

    def failed(self, ticket, error):
        if ticket != self.generation:
            return
        self.request_pending = False
        self.set_status(error)
        self.empty_hint.setText(error)
        self.schedule_reconnect(error)

    def schedule_reconnect(self, reason, delay=None):
        if not self.player or not self.room or self.retry_at is not None:
            return
        if delay is None:
            delay = min(30, 3 * 2 ** min(self.retry_attempts, 4))
            self.retry_attempts += 1
        self.retry_at = time.monotonic() + delay
        self.healthy_since = None
        text = f'{reason}，{delay} 秒后自动重连'
        self.set_status(text)
        self.empty_hint.setText(text)

    def monitor_playback(self):
        self.update_metrics()
        if not self.player or not self.room:
            return
        now = time.monotonic()
        if self.paused or self.suspended:
            self.progress_at = now
            self.healthy_since = None
            if str(self.player.get_state()).split('.')[-1] == 'Playing':
                self.player.set_pause(True)
            return
        if self.request_pending:
            if now - self.request_started >= 45:
                self.generation += 1  # Ignore any late result from this request.
                self.request_pending = False
                self.schedule_reconnect('获取直播画面超时')
            return
        if self.retry_at is not None:
            if now >= self.retry_at:
                self.reload(automatic=True)
            return
        state = str(self.player.get_state()).split('.')[-1]
        if state != 'Playing':
            self.healthy_since = None
        if state == 'Playing':
            if self.apply_audio(force=self._audio_pending):
                self._audio_pending = False
                self.audio_startup.stop()
            position = self.player.get_time()
            if isinstance(position, (int, float)) and position >= 0:
                if position != self.media_time:
                    self.media_time = position
                    self.progress_at = now
                    if self.healthy_since is None:
                        self.healthy_since = now
                    elif now - self.healthy_since >= 15:
                        self.retry_attempts = 0
                elif now - self.progress_at >= 20:
                    self.schedule_reconnect('播放进度停滞')
                    return
            self.set_status('直播中  ·  ' + self.room.get('title', ''))
        elif state in ('Error', 'Ended', 'Stopped'):
            self.schedule_reconnect('直播连接中断')
        elif state == 'Paused':
            self.set_status('已暂停')
        elif now - self.progress_at >= 25:
            self.schedule_reconnect('直播缓冲超时')

    def start_chat(self):
        self.retire_chat()
        self.audience = None
        self.update_metrics()
        if self.room:
            worker = ChatWorker(self.room['id'], self.cookies, self)
            self.chat_worker = worker
            worker.message.connect(lambda msg: self.receive_chat(worker, msg))
            worker.status.connect(lambda text: self.set_chat_status(worker, text))
            worker.audience.connect(lambda audience: self.receive_audience(worker, audience))
            worker.start()

    def receive_chat(self, worker, message):
        if worker is self.chat_worker:
            if message.get('kind') == 'sc_delete':
                ids = set(message.get('ids', []))
                self.deleted_sc.extend(ids)
                self.sc_overlay.remove_ids(ids)
                kept = [m for m in self.history if not (m.get('kind') == 'sc' and m.get('id') in ids)]
                self.history.clear()
                self.history.extend(kept)
                self.refresh_chat()
                return
            if message.get('kind') == 'sc' and message.get('id') in self.deleted_sc:
                return
            event_id = message.get('event_id')
            if event_id and any(m.get('event_id') == event_id for m in self.history):
                return
            self.history.append(message)
            if message.get('kind') == 'sc':
                self.sc_overlay.add_message(message)
            if self.accepts_chat(message):
                self.chat_view.add_message(message)
            if self.pending_sent:
                uid, text, deadline = self.pending_sent
                if time.monotonic() > deadline:
                    self.pending_sent = None
                elif str(message.get('uid', '')) == uid and message.get('text') == text:
                    self.pending_sent = None
                    self.scroll_chat_latest()
            self.chat_received.emit(self.index, message)

    def scroll_chat_latest(self):
        bar = self.chat_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scroll_after_send(self, uid, text):
        self.pending_sent = (uid, text, time.monotonic() + 15) if uid else None
        self.scroll_chat_latest()
        QTimer.singleShot(0, self.scroll_chat_latest)

    def refresh_chat_status(self):
        self.chat_tabs.setToolTip(self.chat_status)

    def accepts_chat(self, message):
        kind = self.chat_tabs.tabData(self.chat_tabs.currentIndex())
        return kind == 'all' or message.get('kind', 'chat') == kind

    def refresh_chat(self):
        self.chat_view.show_history(m for m in self.history if self.accepts_chat(m))

    def change_chat_filter(self, *_):
        self.refresh_chat()
        self.changed.emit()

    def set_chat_status(self, worker, text):
        if worker is self.chat_worker:
            self.chat_status = text
            self.refresh_chat_status()

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
        self.reset_balance()
        self.audio_startup.stop()
        self.generation += 1
        self.request_pending = False
        self.retry_at = None
        self.retry_attempts = 0
        self.media_time = None
        self.progress_at = time.monotonic()
        self.healthy_since = None
        if self.player:
            self.player.stop()
        self._audio_volume = None
        self._audio_muted = None
        self._audio_pending = False
        self.retire_chat()
        self.history.clear()
        self.pending_sent = None
        self.sc_overlay.clear()
        self.composer.set_room(None, {})
        self.deleted_sc.clear()
        self.chat_view.clear()
        self.room = None
        self.audience = None
        self.update_metrics()
        self.gift_button.setEnabled(False)
        self.paused = False
        decorate(self.play_button, 'pause', '暂停直播')
        self.name.setText(f'{self.index + 1:02d}   选择一个直播间')
        self.empty_title.setText(f'画面 {self.index + 1:02d}')
        self.empty_hint.setText('搜索 UP 主，或粘贴直播间链接')
        self.stack.setCurrentIndex(0)
        self.set_status('等待添加 · 支持拖入主播')
        self.chat_status = '选择直播间后显示聊天'
        self.refresh_chat_status()
        if emit:
            self.changed.emit()

    def shutdown(self):
        self.balance_timer.stop()
        self.monitor.stop()
        self.sc_overlay.shutdown()
        self.clear(emit=False)
        for worker in list(self.retiring):
            worker.stop()
        if self.player:
            self.player.release()
            self.player = None
        if self.owns_instance and self.instance:
            self.instance.release()
            self.instance = None

    def start_tile_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData('application/x-dd-tile', str(self.index).encode('ascii'))
        drag.setMimeData(mime)
        drag.setPixmap(self.name.grab().scaledToWidth(min(360, self.name.width()), Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)

    def accepts_tile_drag(self, event):
        source = event.source()
        return (isinstance(source, PlayerTile) and source is not self
                and source.window() is self.window() and source.isVisible() and self.isVisible())

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-dd-tile'):
            if self.accepts_tile_drag(event):
                event.acceptProposedAction()
        elif event.mimeData().hasFormat('application/x-dd-room'):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat('application/x-dd-tile'):
            if self.accepts_tile_drag(event):
                self.swap_requested.emit(event.source().index, self.index)
                event.acceptProposedAction()
            return
        import json
        try:
            room = json.loads(bytes(event.mimeData().data('application/x-dd-room')))
            self.set_room(room)
            event.acceptProposedAction()
        except (ValueError, KeyError):
            pass
