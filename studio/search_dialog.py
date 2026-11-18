from pathlib import Path
from PySide6.QtCore import Qt, QThreadPool, Signal, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QLineEdit, QListWidget, QListWidgetItem, QAbstractItemView, QTabBar, QToolButton)
from .services import BiliAPI, Job
from .sidebar import AvatarStore, SearchResultDelegate, FavoritesStrip
from .widgets import BelowComboBox
from .icons import icon
from .theme import SIZES


def label(text, kind='Muted'):
    widget = QLabel(text)
    widget.setObjectName(kind)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget


class SearchDialog(QDialog):
    rooms_added = Signal(list, int)
    favorite_changed = Signal(dict, bool)

    def __init__(self, cookies, target, count, parent=None):
        super().__init__(parent)
        self.cookies = cookies
        self.page, self.ticket, self.query = 1, 0, ''
        self.mode = 'following'
        self.total = 0
        self.rooms_unavailable = False
        self.favorite_ids = set(getattr(parent, 'favorites', ()))
        self.setWindowTitle('添加直播间')
        self.resize(800, 660)
        self.setMinimumSize(640, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.favorite_heading = label('已收藏', 'Heading')
        layout.addWidget(self.favorite_heading)
        avatars = parent.avatars if parent and hasattr(parent, 'avatars') else AvatarStore(Path(__file__).resolve().parents[1] / 'user-data/avatars', self)
        self.favorite_strip = FavoritesStrip(avatars, self)
        self.favorite_strip.itemDelegate().favorite_clicked.connect(self.toggle_favorite)
        self.favorite_strip.itemChanged.connect(lambda item: self.selection_changed(item, self.favorite_strip))
        layout.addWidget(self.favorite_strip)
        self.favorite_empty = label('还没有收藏，点击主播旁的星标即可加入。')
        layout.addWidget(self.favorite_empty)

        modes = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setObjectName('SearchTabs')
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab('我的关注')
        self.tabs.addTab('全站搜索')
        self.tabs.currentChanged.connect(self.switch_mode)
        modes.addWidget(self.tabs)
        modes.addStretch()
        self.login_button = QPushButton('登录 B 站')
        self.login_button.clicked.connect(lambda: parent.login() if parent and hasattr(parent, 'login') else None)
        modes.addWidget(self.login_button)
        layout.addLayout(modes)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setClearButtonEnabled(True)
        self.input.setFixedHeight(SIZES['control'])
        for clear in self.input.findChildren(QToolButton):
            clear.setIcon(icon('close'))
            clear.setIconSize(QSize(SIZES['inline_icon'], SIZES['inline_icon']))
        self.input.setPlaceholderText('搜索我关注的 UP 主，留空查看全部关注')
        self.input.returnPressed.connect(self.search)
        self.input.textEdited.connect(self.input_edited)
        self.search_button = QPushButton('搜索')
        self.search_button.setObjectName('Primary')
        self.search_button.clicked.connect(self.search)
        row.addWidget(self.input, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        filters = QHBoxLayout()
        self.follow_filter = BelowComboBox()
        for text, value in [('全部', 'all'), ('已关注', 'following'), ('未关注', 'not_following')]:
            self.follow_filter.addItem(text, value)
        self.follow_filter.currentIndexChanged.connect(self.apply_filter)
        self.follow_filter.hide()
        filters.addWidget(self.follow_filter)
        self.follow_hint = label('')
        self.follow_hint.hide()
        filters.addWidget(self.follow_hint, 1)
        layout.addLayout(filters)
        self.status = label('')
        layout.addWidget(self.status)
        self.results = QListWidget()
        self.results.avatars = avatars
        self.result_delegate = SearchResultDelegate(self.results)
        self.results.setItemDelegate(self.result_delegate)
        self.result_delegate.favorite_clicked.connect(self.toggle_favorite)
        self.results.setMouseTracking(True)
        self.results.setSelectionMode(QAbstractItemView.NoSelection)
        self.results.itemChanged.connect(lambda item: self.selection_changed(item, self.results))
        avatars.changed.connect(self.results.viewport().update)
        layout.addWidget(self.results, 1)
        self.more = QPushButton('加载更多')
        self.more.clicked.connect(lambda: self.search(more=True))
        self.more.hide()
        layout.addWidget(self.more, alignment=Qt.AlignCenter)
        footer = QHBoxLayout()
        self.target = BelowComboBox()
        self.target.addItem('仅收藏到侧栏', -1)
        for index in range(count):
            self.target.addItem(f'加入并播放到画面 {index + 1}', index)
        self.target.setCurrentIndex(target + 1)
        footer.addWidget(self.target)
        footer.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.add_button = QPushButton('添加选中 (0)')
        self.add_button.setObjectName('Primary')
        self.add_button.clicked.connect(self.add_selected)
        footer.addWidget(self.add_button)
        layout.addLayout(footer)
        self.finished.connect(lambda _: self.invalidate())
        self.show_favorites()
        self.search()

    def invalidate(self):
        self.ticket += 1

    def items(self, view):
        return (view.item(i) for i in range(view.count()))

    @staticmethod
    def room_key(room):
        return ('room:' + str(room['id'])) if room.get('id') else ('uid:' + str(room.get('uid', '')))

    def show_favorites(self):
        parent = self.parent()
        self.sync_favorites(getattr(parent, 'rooms', {}), set(getattr(parent, 'favorites', self.favorite_ids)))

    def sync_favorites(self, rooms, favorite_ids):
        """Removed favorites stay in this dialog's strip until the dialog closes."""
        self.favorite_ids = set(favorite_ids)
        existing = {item.data(Qt.UserRole)['id']: item for item in self.items(self.favorite_strip)}
        self.favorite_strip.blockSignals(True)
        for rid, item in existing.items():
            if rid in rooms:
                item.setData(Qt.UserRole, dict(rooms[rid]))
                room = rooms[rid]
                item.setToolTip(room['name'] + (' · 直播中' if room.get('live') else ' · 未开播'))
            item.setData(Qt.UserRole + 1, rid in self.favorite_ids)
        additions = [room for rid, room in rooms.items() if rid in self.favorite_ids and rid not in existing]
        additions.sort(key=lambda room: not room.get('live', False))
        for room in additions:
            item = QListWidgetItem(room['name'])
            item.setData(Qt.UserRole, dict(room))
            item.setData(Qt.UserRole + 1, True)
            item.setToolTip(room['name'] + (' · 直播中' if room.get('live') else ' · 未开播'))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = any(row.data(Qt.UserRole).get('id') == room['id'] and row.checkState() == Qt.Checked for row in self.items(self.results))
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            item.setSizeHint(QSize(84, 94))
            index = self.favorite_strip.count()
            if room.get('live'):
                index = next((i for i in range(self.favorite_strip.count()) if not self.favorite_strip.item(i).data(Qt.UserRole).get('live')), index)
            self.favorite_strip.insertItem(index, item)
        ordered = sorted(self.items(self.favorite_strip), key=lambda item: not item.data(Qt.UserRole).get('live', False))
        for index, item in enumerate(ordered):
            current = self.favorite_strip.row(item)
            if current != index:
                self.favorite_strip.insertItem(index, self.favorite_strip.takeItem(current))
        self.favorite_strip.blockSignals(False)
        self.results.blockSignals(True)
        for item in self.items(self.results):
            item.setData(Qt.UserRole + 1, item.data(Qt.UserRole).get('id') in self.favorite_ids)
        self.results.blockSignals(False)
        self.favorite_heading.setText(f'已收藏 · {len(self.favorite_ids)}')
        self.favorite_empty.setVisible(not self.favorite_strip.count())
        self.favorite_strip.setVisible(bool(self.favorite_strip.count()))
        self.update_count()

    def toggle_favorite(self, rid):
        room = next((item.data(Qt.UserRole) for view in (self.results, self.favorite_strip)
                     for item in self.items(view) if item.data(Qt.UserRole).get('id') == rid), None)
        if not room or not rid:
            return
        added = rid not in self.favorite_ids
        if added:
            self.favorite_ids.add(rid)
        else:
            self.favorite_ids.discard(rid)
        self.sync_favorites({rid: room}, self.favorite_ids)
        self.favorite_changed.emit(room, added)

    def selection_changed(self, item, source):
        rid = item.data(Qt.UserRole).get('id')
        if not rid:
            return
        other = self.results if source is self.favorite_strip else self.favorite_strip
        other.blockSignals(True)
        for row in self.items(other):
            if row.data(Qt.UserRole).get('id') == rid:
                row.setCheckState(item.checkState())
        other.blockSignals(False)
        self.update_count()

    def selected_rooms(self):
        rooms = {}
        for view in (self.favorite_strip, self.results):
            for item in self.items(view):
                room = item.data(Qt.UserRole)
                if room.get('id') and item.checkState() == Qt.Checked and not item.isHidden():
                    rooms[room['id']] = room
        return list(rooms.values())

    def update_count(self, *_):
        count = len(self.selected_rooms())
        self.add_button.setText(f'添加选中 ({count})')
        self.add_button.setEnabled(bool(count))

    def switch_mode(self, *_):
        self.mode = 'following' if self.tabs.currentIndex() == 0 else 'search'
        self.input.setPlaceholderText('搜索我关注的 UP 主，留空查看全部关注' if self.mode == 'following'
                                      else '搜索 UP 主昵称，或粘贴直播间链接 / 房号')
        self.follow_filter.setVisible(self.mode == 'search')
        self.follow_hint.setVisible(self.mode == 'search')
        self.search()

    def input_edited(self, text):
        if self.mode == 'following' and not text and self.query:
            self.search()

    def search(self, checked=False, more=False):
        query = self.input.text().strip()
        self.ticket += 1
        ticket = self.ticket
        page = self.page + 1 if more and query == self.query else 1
        if page == 1:
            self.results.clear()
        self.query = query
        self.more.hide()
        self.search_button.setEnabled(True)
        self.update_count()
        self.login_button.setVisible(not self.cookies.get('SESSDATA'))
        if self.mode == 'following' and not self.cookies.get('SESSDATA'):
            self.status.setText('登录 B 站后查看关注列表；上方收藏仍可直接选择。')
            return
        if self.mode == 'search' and not query:
            self.status.setText('输入昵称、直播间链接或房号开始搜索。')
            return
        self.status.setText('正在搜索关注列表…' if self.mode == 'following' and query else
                            ('正在加载关注列表…' if self.mode == 'following' else f'正在搜索「{query}」…'))
        self.search_button.setEnabled(False)
        api, mode = BiliAPI(self.cookies), self.mode
        job = Job(lambda: api.followings(query, page) if mode == 'following' else api.search_with_follow(query, page))
        job.signals.done.connect(lambda data: self.show_results(ticket, dict(data, page=page)))
        job.signals.error.connect(lambda error: self.show_error(ticket, error))
        QThreadPool.globalInstance().start(job)

    def show_results(self, ticket, data):
        if ticket != self.ticket:
            return
        self.page = data.get('page', self.page)
        self.total = data.get('total', len(data['rooms']))
        self.rooms_unavailable = data.get('rooms_unavailable', False)
        existing = {self.room_key(item.data(Qt.UserRole)): item for item in self.items(self.results)}
        self.results.blockSignals(True)
        for room in data['rooms']:
            key = self.room_key(room)
            if key in existing:
                existing[key].setData(Qt.UserRole, room)
                continue
            item = QListWidgetItem(room['name'])
            item.setData(Qt.UserRole, dict(room))
            item.setData(Qt.UserRole + 1, room.get('id') in self.favorite_ids)
            item.setToolTip(room['name'] + '\n' + room.get('title', ''))
            if room.get('id'):
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                selected = any(row.data(Qt.UserRole).get('id') == room['id'] and row.checkState() == Qt.Checked for row in self.items(self.favorite_strip))
                item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setSizeHint(QSize(0, 70))
            self.results.addItem(item)
            existing[key] = item
        if self.mode == 'following':
            # Include previous pages so newly loaded live rooms join the front.
            ordered = sorted(self.items(self.results), key=lambda item: not item.data(Qt.UserRole).get('live', False))
            for index, item in enumerate(ordered):
                current = self.results.row(item)
                if current != index:
                    self.results.insertItem(index, self.results.takeItem(current))
        self.results.blockSignals(False)
        known = any(item.data(Qt.UserRole).get('following') is not None for item in self.items(self.results))
        self.follow_filter.setEnabled(known)
        if not known:
            self.follow_filter.setCurrentIndex(0)
        state = data.get('follow_state', 'login_required')
        self.follow_hint.setText('按当前账号筛选已加载的搜索结果' if state == 'ok' else '登录后可筛选关注状态')
        self.login_button.setVisible(state not in ('ok', 'pending'))
        self.apply_filter()
        self.search_button.setEnabled(True)
        self.more.setVisible(data['more'])
        self.more.setEnabled(True)

    def apply_filter(self, *_):
        mode = self.follow_filter.currentData() if self.mode == 'search' else 'all'
        visible = 0
        for item in self.items(self.results):
            following = item.data(Qt.UserRole).get('following')
            shown = mode == 'all' or (mode == 'following' and following is True) or (mode == 'not_following' and following is False)
            item.setHidden(not shown)
            visible += int(shown)
        if self.mode == 'following':
            prefix = f'关注内搜索 · 共 {self.total} 位' if self.query else f'我的关注 · 共 {self.total} 位'
            self.status.setText(f'{prefix}，已加载 {self.results.count()} 位。' if self.total else '没有匹配的关注账号。')
            if self.rooms_unavailable:
                self.status.setText(self.status.text() + ' 直播间信息暂不可用，可重新搜索刷新。')
        else:
            self.status.setText(f'已加载 {self.results.count()} 个直播间，显示 {visible} 个。' if self.results.count() else '没有找到匹配的直播间。')
        self.update_count()

    def show_error(self, ticket, error):
        if ticket != self.ticket:
            return
        self.status.setText(error)
        self.search_button.setEnabled(True)
        if '登录' in error:
            self.login_button.show()
        self.more.setEnabled(True)
        self.more.setVisible(bool(self.results.count()))

    def refresh_account(self, cookies):
        self.cookies = cookies
        if self.mode == 'following' or self.input.text().strip():
            self.search()

    def add_selected(self):
        rooms = self.selected_rooms()
        if rooms:
            self.rooms_added.emit(rooms, self.target.currentData())
            self.accept()
