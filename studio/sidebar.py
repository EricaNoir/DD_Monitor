"""A persistent avatar rail that expands into the room library."""
import hashlib
import json
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, QUrl, QSize, QRectF, QMimeData, QEvent, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPixmap, QDrag, QPen, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QStyle, QAbstractItemView, QToolTip, QMenu
from .icons import icon
from .runtime import configure_qt_tls
from .services import safe_image


def sidebar_icon():
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#dddddd'), 1.5))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
    painter.drawLine(9, 4, 9, 20)
    painter.end()
    return QIcon(pixmap)


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
        area = QRectF(option.rect).adjusted(2, 2, -2, -2)
        current = room.get('id') in view.visible_rooms
        hovered = bool(option.state & QStyle.State_MouseOver)
        if current or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#393939' if current else '#292929'))
            painter.drawRoundedRect(area, 7, 7)
        avatar = QRectF(option.rect.left() + 7, option.rect.top() + 8, 26, 26)
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
            painter.fillRect(avatar, QColor('#454545'))
            painter.setPen(QColor('#dedede'))
            name = room.get('name', '?').split('-')[-1][:1]
            painter.drawText(avatar, Qt.AlignCenter, name)
        painter.restore()
        painter.setPen(QPen(QColor('#202020'), 2))
        painter.setBrush(QColor('#70bd91' if room.get('live') else '#777777'))
        painter.drawEllipse(QRectF(avatar.right() - 6, avatar.bottom() - 6, 8, 8))
        if not view.collapsed:
            painter.setPen(QColor('#e4e4e4'))
            text_rect = option.rect.adjusted(48, 0, -9, 0)
            text = option.fontMetrics.elidedText(room.get('name', ''), Qt.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(38, 42)


class RoomList(QListWidget):
    remove_requested = Signal(dict)

    def __init__(self, avatars):
        super().__init__()
        self.avatars = avatars
        self.collapsed = False
        self.active_room = None
        self.visible_rooms = set()
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setItemDelegate(RoomDelegate(self))
        self.setDragEnabled(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setMinimumWidth(38)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                self.setCurrentItem(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_collapsed(self, value):
        self.collapsed = value
        self.viewport().update()

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item:
            mime = QMimeData()
            mime.setData('application/x-dd-room', json.dumps(item.data(Qt.UserRole)).encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)


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
            painter.setBrush(QColor('#343434' if checked else '#292929'))
            painter.drawRoundedRect(QRectF(rect).adjusted(1,2,-1,-2),6,6)
        check = QRectF(rect.left()+8, rect.center().y()-7,14,14)
        painter.setPen(QPen(QColor('#777777'),1))
        painter.setBrush(QColor('#dddddd' if checked else '#262626'))
        if room.get('id'):
            painter.drawRoundedRect(check,3,3)
        if checked and room.get('id'):
            painter.setPen(QPen(QColor('#222222'),1.6))
            painter.drawLine(QPointF(check.x()+3,check.y()+7),QPointF(check.x()+6,check.y()+10))
            painter.drawLine(QPointF(check.x()+6,check.y()+10),QPointF(check.x()+11,check.y()+4))
        avatar=QRectF(rect.left()+34,rect.top()+14,40,40)
        clip=QPainterPath();clip.addEllipse(avatar)
        painter.save();painter.setClipPath(clip)
        pixmap=self.parent().avatars.get(room.get('face',''))
        if pixmap is not None:
            side=min(pixmap.width(),pixmap.height())
            painter.drawPixmap(avatar,pixmap,QRectF((pixmap.width()-side)/2,(pixmap.height()-side)/2,side,side))
        else:
            painter.fillRect(avatar,QColor('#484848'))
            painter.setPen(QColor('#dddddd'))
            painter.drawText(avatar,Qt.AlignCenter,room.get('name','?')[:1])
        painter.restore()
        x=rect.left()+88
        width=max(10,rect.right()-x-48)
        painter.setPen(QColor('#eeeeee'))
        title=room.get('name','') + (('  ·  直播中' if room.get('live') else '  ·  未开播') if room.get('id') else '')
        painter.drawText(QRectF(x,rect.top()+10,width,24),Qt.AlignVCenter,
                         option.fontMetrics.elidedText(title,Qt.ElideRight,width))
        status='已关注' if room.get('following') is True else ('未关注' if room.get('following') is False else '关注状态未知')
        subtitle=f'{status}  ·  {room.get("id", "")}  ·  {room.get("title", "")}' if room.get('id') else ('直播间信息暂不可用' if room.get('room_known') is False else '未开通直播间')
        painter.setPen(QColor('#9c9c9c'))
        painter.drawText(QRectF(x,rect.top()+35,width,24),Qt.AlignVCenter,
                         option.fontMetrics.elidedText(subtitle,Qt.ElideRight,width))
        favorite = bool(index.data(Qt.UserRole+1))
        if room.get('id'):
            icon('star_filled' if favorite else 'star').paint(painter, self.favorite_rect(rect).adjusted(5,5,-5,-5).toRect())
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
            return model.setData(index,value,Qt.CheckStateRole)
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
            painter.setBrush(QColor('#353535' if checked else '#292929'))
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
            painter.fillRect(avatar, QColor('#454545'))
            painter.setPen(QColor('#dedede'))
            painter.drawText(avatar, Qt.AlignCenter, room.get('name', '?')[:1])
        painter.restore()
        if checked:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#dcdcdc'), 2))
            painter.drawEllipse(avatar.adjusted(-3, -3, 3, 3))
        painter.setPen(QPen(QColor('#202020'), 2))
        painter.setBrush(QColor('#70bd91' if room.get('live') else '#777777'))
        painter.drawEllipse(QRectF(avatar.right()-8, avatar.bottom()-8, 10, 10))
        painter.setPen(QColor('#eeeeee' if checked else '#aaaaaa'))
        text_rect = QRectF(rect.left()+3, rect.top()+65, rect.width()-6, 22)
        text = option.fontMetrics.elidedText(room.get('name', ''), Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignCenter, text)
        icon('star_filled' if index.data(Qt.UserRole+1) else 'star').paint(painter, self.favorite_rect(rect).adjusted(3,3,-3,-3).toRect())
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
        self.horizontalScrollBar().setStyleSheet('''
            QScrollBar:horizontal { background: transparent; border: 0; height: 4px; margin: 0; }
            QScrollBar::handle:horizontal { background: #505050; border: 0; min-width: 24px; border-radius: 2px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; border: 0; background: transparent; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; border: 0; }
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal { width: 0; height: 0; border: 0; }
        ''')
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
