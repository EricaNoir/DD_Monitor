from .theme import COLORS, SIZES, horizontal_scrollbar_style
"""A fixed avatar rail for favorite rooms."""
import hashlib
import json
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, QUrl, QSize, QRectF, QMimeData, QEvent, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPixmap, QDrag, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QApplication, QListWidget, QStyledItemDelegate, QStyle, QAbstractItemView, QToolTip, QMenu, QScrollArea, QFrame
from .icons import icon, paint_icon
from .runtime import configure_qt_tls
from .services import safe_image


class AvatarStore(QObject):
    changed = Signal()

    def __init__(self, cache_dir, parent=None, enabled=True):
        super().__init__(parent)
        configure_qt_tls()
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.images, self.requested, self.queue = {}, set(), deque()
        self.running = 0
        self.network = QNetworkAccessManager(self)

    def cached_path(self, address):
        return self.cache_dir / (hashlib.sha256(address.encode()).hexdigest() + '.png')

    def get(self, address):
        address = safe_image(address)
        if not address:
            return None
        if address in self.images:
            return self.images[address]
        path = self.cached_path(address)
        if path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.images[address] = pixmap
                return pixmap
        if self.enabled and address not in self.requested:
            self.requested.add(address)
            self.queue.append(address)
            self.pump()
        return None

    def pump(self):
        while self.queue and self.running < 4:
            address = self.queue.popleft()
            request = QNetworkRequest(QUrl(address))
            request.setTransferTimeout(10000)
            reply = self.network.get(request)
            self.running += 1
            reply.downloadProgress.connect(lambda size, total, r=reply: r.abort() if size > 2_000_000 else None)
            reply.finished.connect(lambda a=address, r=reply: self.finish(a, r))

    def finish(self, address, reply):
        self.running -= 1
        if reply.error() == QNetworkReply.NoError:
            data = bytes(reply.readAll())
            pixmap = QPixmap()
            if len(data) <= 2_000_000 and pixmap.loadFromData(data):
                pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.images[address] = pixmap
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    pixmap.save(str(self.cached_path(address)), 'PNG')
                except OSError:
                    pass
                self.changed.emit()
        reply.deleteLater()
        self.pump()


class RoomDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        room = index.data(Qt.UserRole) or {}
        view = self.parent()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(option.rect).adjusted(4, 4, -4, -4)
        current = room.get('id') in view.visible_rooms
        hovered = bool(option.state & QStyle.State_MouseOver)
        if current or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS['selected'] if current else COLORS['field']))
            painter.drawRoundedRect(area, 7, 7)
        avatar = QRectF(0, 0, 26, 26)
        avatar.moveCenter(QRectF(option.rect).center())
        clip = QPainterPath()
        clip.addEllipse(avatar)
        painter.save()
        painter.setClipPath(clip)
        pixmap = view.avatars.get(room.get('face', ''))
        if pixmap is not None:
            side = min(pixmap.width(), pixmap.height())
            source = QRectF((pixmap.width() - side) / 2, (pixmap.height() - side) / 2, side, side)
            painter.drawPixmap(avatar, pixmap, source)
        else:
            painter.fillRect(avatar, QColor(COLORS['avatar']))
            painter.setPen(QColor(COLORS['text']))
            name = room.get('name', '?').split('-')[-1][:1]
            painter.drawText(avatar, Qt.AlignCenter, name)
        painter.restore()
        painter.setPen(QPen(QColor(COLORS['surface']), 2))
        painter.setBrush(QColor(COLORS['live'] if room.get('live') else COLORS['offline']))
        size = SIZES['avatar_status_dot']
        painter.drawEllipse(QRectF(avatar.right() - size + 2, avatar.bottom() - size + 2, size, size))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(SIZES['rail'], SIZES['rail'])


class FavoritesScroll(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(SIZES['rail'])
        self.setMinimumWidth(2 * SIZES['rail'])
        self.setToolTip('收藏直播间，可用滚轮横向滚动')

    def wheelEvent(self, event):
        delta = event.pixelDelta().x() or event.pixelDelta().y()
        if not delta:
            delta = (event.angleDelta().x() or event.angleDelta().y()) / 2
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - int(delta))
        event.accept()


class RoomList(QListWidget):
    remove_requested = Signal(dict)
    reordered = Signal(list)

    def __init__(self, avatars):
        super().__init__()
        self.avatars = avatars
        self.collapsed = True
        self.drag_start = None
        self.drag_room = None
        self.dragged = False
        self.drop_y = None
        self.drop_point = None
        self.drag_scroll = QTimer(self)
        self.drag_scroll.setInterval(70)
        self.drag_scroll.timeout.connect(self.scroll_drag)
        self.setObjectName('AvatarRail')
        self.active_room = None
        self.visible_rooms = set()
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setItemDelegate(RoomDelegate(self))
        self.setDragEnabled(False)  # Explicit dragging works with NoSelection.
        self.setAcceptDrops(True)
        self.setAutoScroll(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setMinimumWidth(0)
        self.setFixedHeight(SIZES['rail'])
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setGridSize(QSize(SIZES['rail'], SIZES['rail']))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        avatars.changed.connect(self.viewport().update)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.context_menu = None

    def show_context_menu(self, point):
        item = self.itemAt(point)
        if item is None:
            return
        room = dict(item.data(Qt.UserRole))
        self.setCurrentItem(item)
        if self.context_menu is not None:
            self.context_menu.close()
            self.context_menu.deleteLater()
        self.context_menu = QMenu(self)
        action = self.context_menu.addAction(icon('trash'), '移除收藏')
        action.triggered.connect(lambda: self.remove_requested.emit(room))
        self.context_menu.popup(self.viewport().mapToGlobal(point))

    def mousePressEvent(self, event):
        self.dragged = False
        self.drag_start = None
        self.drag_room = None
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                self.setCurrentItem(item)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                self.drag_start = event.position().toPoint()
                self.drag_room = dict(item.data(Qt.UserRole))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.drag_start is not None and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self.drag_start).manhattanLength() >= QApplication.startDragDistance()):
            self.dragged = True
            self.drag_start = None
            self.startDrag(Qt.CopyAction)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        if self.dragged:
            self.dragged = False
            self.drag_room = None
            event.accept()
            return
        if event.button() == Qt.RightButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def startDrag(self, supported_actions):
        room = self.drag_room
        if room:
            mime = QMimeData()
            mime.setData('application/x-dd-room', json.dumps(room).encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)
            self.drop_y = None
            self.drag_scroll.stop()
            self.viewport().update()

    def internal_drop(self, event):
        return event.source() is self and event.mimeData().hasFormat('application/x-dd-room')

    def dragEnterEvent(self, event):
        if self.internal_drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def insertion_index(self, point):
        item = self.itemAt(point)
        if item is None:
            return self.count()
        rect = self.visualItemRect(item)
        return self.row(item) + int(point.x() > rect.center().x())

    def dragMoveEvent(self, event):
        if not self.internal_drop(event):
            event.ignore()
            return
        self.drop_point = event.position().toPoint()
        self.update_drop_indicator()
        self.drag_scroll.start()
        event.acceptProposedAction()

    def update_drop_indicator(self):
        index = self.insertion_index(self.drop_point)
        self.drop_y = (self.visualItemRect(self.item(index)).left() if index < self.count()
                       else self.visualItemRect(self.item(self.count() - 1)).right()) if self.count() else 0
        self.viewport().update()

    def scroll_drag(self):
        if self.drop_point is None:
            return
        scroll = getattr(self, 'scroll_area', None)
        if scroll is None:
            return
        point = self.viewport().mapTo(scroll.viewport(), self.drop_point)
        delta = -12 if point.x() < 20 else (12 if point.x() > scroll.viewport().width() - 20 else 0)
        if delta:
            bar = scroll.horizontalScrollBar()
            previous = bar.value()
            bar.setValue(bar.value() + delta)
            self.drop_point.setX(self.drop_point.x() + bar.value() - previous)
            self.update_drop_indicator()

    def wheelEvent(self, event):
        if getattr(self, 'scroll_area', None) is not None:
            self.scroll_area.wheelEvent(event)
        else:
            super().wheelEvent(event)

    def dragLeaveEvent(self, event):
        self.drop_y = None
        self.drag_scroll.stop()
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        self.drop_y = None
        self.drag_scroll.stop()
        self.viewport().update()
        if not self.internal_drop(event):
            event.ignore()
            return
        try:
            rid = json.loads(bytes(event.mimeData().data('application/x-dd-room')))['id']
        except (ValueError, KeyError, TypeError):
            event.ignore()
            return
        ids = [self.item(i).data(Qt.UserRole)['id'] for i in range(self.count())]
        if rid not in ids:
            event.ignore()
            return
        index = self.insertion_index(event.position().toPoint())
        previous = ids.index(rid)
        ids.pop(previous)
        ids.insert(index - int(previous < index), rid)
        self.reordered.emit(ids)
        event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_y is not None:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(COLORS['icon']), 2))
            painter.drawLine(self.drop_y, 6, self.drop_y, self.viewport().height() - 6)
            painter.end()


class SearchResultDelegate(QStyledItemDelegate):
    favorite_clicked = Signal(str)

    def favorite_rect(self, rect):
        return QRectF(rect.right()-39, rect.center().y()-15, 30, 30)

    def paint(self, painter, option, index):
        room = index.data(Qt.UserRole) or {}
        checked = index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if checked or option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS['selected'] if checked else COLORS['field']))
            painter.drawRoundedRect(QRectF(rect).adjusted(1,2,-1,-2),6,6)
        check = QRectF(rect.left()+8, rect.center().y()-7,14,14)
        painter.setPen(QPen(QColor(COLORS['offline']),1))
        painter.setBrush(QColor(COLORS['icon'] if checked else COLORS['field']))
        if room.get('id'):
            painter.drawRoundedRect(check,3,3)
        if checked and room.get('id'):
            paint_icon(painter, 'check', check, size=14, color=COLORS['inverse'])
        avatar=QRectF(rect.left()+34,rect.top()+14,40,40)
        clip=QPainterPath();clip.addEllipse(avatar)
        painter.save();painter.setClipPath(clip)
        pixmap=self.parent().avatars.get(room.get('face',''))
        if pixmap is not None:
            side=min(pixmap.width(),pixmap.height())
            painter.drawPixmap(avatar,pixmap,QRectF((pixmap.width()-side)/2,(pixmap.height()-side)/2,side,side))
        else:
            painter.fillRect(avatar,QColor(COLORS['avatar']))
            painter.setPen(QColor(COLORS['icon']))
            painter.drawText(avatar,Qt.AlignCenter,room.get('name','?')[:1])
        painter.restore()
        x=rect.left()+88
        width=max(10,rect.right()-x-48)
        painter.setPen(QColor(COLORS['text']))
        dot_size = SIZES['status_dot']
        dot_gap = SIZES['gap']
        title_width = max(1, width - dot_size - dot_gap) if room.get('id') else width
        title = option.fontMetrics.elidedText(room.get('name', ''), Qt.ElideRight, title_width)
        painter.drawText(QRectF(x,rect.top()+10,title_width,24),Qt.AlignVCenter,title)
        if room.get('id'):
            dot_x = x + option.fontMetrics.horizontalAdvance(title) + dot_gap
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS['live'] if room.get('live') else COLORS['offline']))
            painter.drawEllipse(QRectF(dot_x, rect.top()+22-dot_size/2, dot_size, dot_size))
        status='已关注' if room.get('following') is True else ('未关注' if room.get('following') is False else '关注状态未知')
        subtitle=f'{status}  ·  {room.get("id", "")}  ·  {room.get("title", "")}' if room.get('id') else ('直播间信息暂不可用' if room.get('room_known') is False else '未开通直播间')
        painter.setPen(QColor(COLORS['text_muted']))
        painter.drawText(QRectF(x,rect.top()+35,width,24),Qt.AlignVCenter,
                         option.fontMetrics.elidedText(subtitle,Qt.ElideRight,width))
        favorite = bool(index.data(Qt.UserRole+1))
        if room.get('id'):
            paint_icon(painter, 'star_filled' if favorite else 'star', self.favorite_rect(rect))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not (index.data(Qt.UserRole) or {}).get('id'):
            return False
        clicked=event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton
        pressed=event.type()==QEvent.KeyPress and event.key()==Qt.Key_Space
        if clicked and self.favorite_rect(option.rect).contains(event.position()):
            self.favorite_clicked.emit(index.data(Qt.UserRole)['id'])
            return True
        if clicked or pressed:
            value=Qt.Unchecked if index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value) else Qt.Checked
            # QAbstractItemModel check roles must store an integer, not a Python enum.
            # Otherwise the delegate paints a check but QListWidgetItem.checkState() reads Unchecked.
            return model.setData(index,value.value,Qt.CheckStateRole)
        return False

    def helpEvent(self, event, view, option, index):
        if (index.data(Qt.UserRole) or {}).get('id') and self.favorite_rect(option.rect).contains(event.pos()):
            QToolTip.showText(event.globalPos(), '取消收藏' if index.data(Qt.UserRole+1) else '收藏到左侧边栏', view)
            return True
        return super().helpEvent(event, view, option, index)

    def sizeHint(self, option, index):
        return QSize(0,70)


class FavoriteAvatarDelegate(SearchResultDelegate):
    def favorite_rect(self, rect):
        return QRectF(rect.right() - 24, rect.top() + 2, 24, 24)

    def paint(self, painter, option, index):
        room = index.data(Qt.UserRole) or {}
        checked = index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if checked or option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS['selected'] if checked else COLORS['field']))
            painter.drawRoundedRect(QRectF(rect).adjusted(2, 1, -2, -2), 7, 7)
        avatar = QRectF(rect.left() + 16, rect.top() + 9, 50, 50)
        clip = QPainterPath()
        clip.addEllipse(avatar)
        painter.save()
        painter.setClipPath(clip)
        pixmap = self.parent().avatars.get(room.get('face', ''))
        if pixmap is not None:
            side = min(pixmap.width(), pixmap.height())
            painter.drawPixmap(avatar, pixmap, QRectF((pixmap.width()-side)/2, (pixmap.height()-side)/2, side, side))
        else:
            painter.fillRect(avatar, QColor(COLORS['avatar']))
            painter.setPen(QColor(COLORS['text']))
            painter.drawText(avatar, Qt.AlignCenter, room.get('name', '?')[:1])
        painter.restore()
        if checked:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(COLORS['icon']), 2))
            painter.drawEllipse(avatar.adjusted(-3, -3, 3, 3))
        painter.setPen(QPen(QColor(COLORS['surface']), 2))
        painter.setBrush(QColor(COLORS['live'] if room.get('live') else COLORS['offline']))
        painter.drawEllipse(QRectF(avatar.right()-8, avatar.bottom()-8, 10, 10))
        painter.setPen(QColor(COLORS['text'] if checked else COLORS['text_secondary']))
        text_rect = QRectF(rect.left()+3, rect.top()+65, rect.width()-6, 22)
        text = option.fontMetrics.elidedText(room.get('name', ''), Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignCenter, text)
        paint_icon(painter, 'star_filled' if index.data(Qt.UserRole+1) else 'star', self.favorite_rect(rect))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(84, 94)


class FavoritesStrip(QListWidget):
    def __init__(self, avatars, parent=None):
        super().__init__(parent)
        self.avatars = avatars
        self.setObjectName('FavoritesStrip')
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListWidget.Static)
        self.setResizeMode(QListWidget.Adjust)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(104)
        self.horizontalScrollBar().setObjectName('FavoriteScroll')
        self.horizontalScrollBar().setStyleSheet(horizontal_scrollbar_style())
        self.setSpacing(3)
        self.setMouseTracking(True)
        self.setItemDelegate(FavoriteAvatarDelegate(self))
        avatars.changed.connect(self.viewport().update)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                rect = self.visualItemRect(item)
                if self.itemDelegate().favorite_rect(rect).contains(event.position()):
                    self.itemDelegate().favorite_clicked.emit(item.data(Qt.UserRole)['id'])
                else:
                    item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentItem():
            item = self.currentItem()
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        amount = event.angleDelta().x() or event.angleDelta().y()
        if amount:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - amount)
            event.accept()
        else:
            super().wheelEvent(event)
