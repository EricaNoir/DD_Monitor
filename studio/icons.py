"""One consistent set of 24px outline icons, rendered crisply at HiDPI."""
from math import cos, sin, pi
from PySide6.QtCore import Qt, QRectF, QPointF, QSize
from PySide6.QtGui import QIcon, QPixmap, QImage, QPainter, QPen, QColor, QPainterPath, QPolygonF
from .theme import COLORS, SIZES, ICON_STROKE

_cache = {}
_images = {}


def icon_image(name, size=18, color=None, dpr=2):
    color = color or COLORS['icon']
    key = (name, size, color, dpr)
    if key in _images:
        return _images[key]
    image = QImage(size * dpr, size * dpr, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    image.setDevicePixelRatio(dpr)
    p = QPainter(image)
    p.scale(size / 24, size / 24)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), ICON_STROKE, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
    def circle(x,y,r):
        p.drawEllipse(QPointF(x,y),r,r)
    if name == 'pause':
        line(8,5,8,19); line(16,5,16,19)
    elif name == 'play':
        p.drawPolygon(QPolygonF([QPointF(7,4),QPointF(19,12),QPointF(7,20)]))
    elif name in ('volume','muted'):
        p.drawPolygon(QPolygonF([QPointF(3,9),QPointF(6,9),QPointF(11,5),QPointF(11,19),QPointF(6,15),QPointF(3,15)]))
        if name == 'muted':
            line(16,9,21,15); line(21,9,16,15)
        else:
            p.drawArc(QRectF(7,7,10,10),-55*16,110*16); p.drawArc(QRectF(5,3,16,18),-50*16,100*16)
    elif name == 'reload':
        p.drawArc(QRectF(4,4,16,16),35*16,290*16); line(20,4,20,9); line(20,9,15,9)
    elif name == 'headphones':
        p.drawArc(QRectF(5,5,14,14),0,180*16)
        p.drawRoundedRect(QRectF(4,11,4,8),1.3,1.3); p.drawRoundedRect(QRectF(16,11,4,8),1.3,1.3)
    elif name in ('expand','collapse'):
        for x,y,sx,sy in [(4,4,1,1),(20,4,-1,1),(4,20,1,-1),(20,20,-1,-1)]:
            if name == 'collapse': x,y,sx,sy=x+sx*5,y+sy*5,-sx,-sy
            line(x,y,x+sx*5,y); line(x,y,x,y+sy*5)
    elif name == 'chat':
        path=QPainterPath(); path.moveTo(6,4); path.lineTo(18,4); path.quadTo(20,4,20,6)
        path.lineTo(20,16); path.quadTo(20,18,18,18); path.lineTo(8,18); path.lineTo(4,20)
        path.lineTo(4,6); path.quadTo(4,4,6,4)
        p.drawPath(path); line(8,9,16,9); line(8,13,13,13)
    elif name == 'send':
        p.drawPolygon(QPolygonF([QPointF(4,4), QPointF(21,12), QPointF(4,20), QPointF(7,12)]))
        line(7,12,15,12)
    elif name == 'gift':
        p.drawRect(QRectF(4, 8, 16, 4)); p.drawRect(QRectF(6, 12, 12, 8))
        line(12, 8, 12, 20)
        p.drawEllipse(QRectF(5, 4, 7, 4)); p.drawEllipse(QRectF(12, 4, 7, 4))
    elif name == 'add':
        line(5,12,19,12); line(12,5,12,19)
    elif name == 'close':
        line(5,5,19,19); line(19,5,5,19)
    elif name in ('chevron_down', 'chevron_up'):
        if name == 'chevron_down':
            line(6,9,12,15); line(12,15,18,9)
        else:
            line(6,15,12,9); line(12,9,18,15)
    elif name == 'check':
        line(5,12,10,17); line(10,17,19,7)
    elif name == 'more':
        for x in (5,12,19): circle(x,12,.9)
    elif name == 'info':
        circle(12,12,9); circle(12,7.5,.6); line(12,11,12,17)
    elif name == 'user':
        circle(12,8,4); p.drawArc(QRectF(4,14,16,13),0,180*16)
    elif name == 'sidebar':
        p.drawRoundedRect(QRectF(3,4,18,16),2,2); line(9,4,9,20)
    elif name == 'controls':
        for x,y in [(5,9),(12,16),(19,7)]:
            line(x,4,x,y-2); line(x,y+2,x,20); circle(x,y,2)
    elif name == 'settings':
        points = []
        for i in range(8):
            for offset, radius in ((-2,7),(-1,9),(1,9),(2,7)):
                a = (i * 6 + offset) * pi / 24
                points.append(QPointF(12 + radius*cos(a), 12 + radius*sin(a)))
        p.drawPolygon(QPolygonF(points)); circle(12,12,3)
    elif name == 'bottom':
        line(12,4,12,16); line(7,11,12,16); line(17,11,12,16); line(5,20,19,20)
    elif name == 'trash':
        line(5,7,19,7); line(9,4,15,4); line(7,7,8,20); line(8,20,16,20); line(16,20,17,7)
        line(10,10,10,17); line(14,10,14,17)
    elif name in ('star','star_filled'):
        points=[]
        for i in range(10):
            angle=-pi/2+i*pi/5
            r=9 if i%2==0 else 4.3
            points.append(QPointF(12+r*cos(angle),12+r*sin(angle)))
        if name == 'star_filled':
            p.setBrush(QColor(COLORS['favorite']))
            p.setPen(QPen(QColor(COLORS['favorite']), ICON_STROKE, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolygon(QPolygonF(points))
    else:
        p.end()
        raise ValueError(f'Unknown icon: {name}')
    p.end()
    _images[key] = image
    return image


def icon(name, color=None):
    key = (name, color)
    if key in _cache:
        return _cache[key]
    result = QIcon()
    for size in (12, 16, 18, 24, 32):
        result.addPixmap(QPixmap.fromImage(icon_image(name, size, color)))
        result.addPixmap(QPixmap.fromImage(icon_image(name, size, COLORS['text_disabled'])), QIcon.Disabled)
    _cache[key] = result
    return result


def paint_icon(painter, name, rect, size=None, color=None):
    size = size or SIZES['icon']
    target = QRectF(0, 0, size, size)
    target.moveCenter(QRectF(rect).center())
    icon(name, color).paint(painter, target.toRect())


def decorate(button, name, description, size=None):
    button.setText('')
    button.setProperty('iconOnly', True)
    button.setIcon(icon(name))
    button.setIconSize(QSize(SIZES['icon'], SIZES['icon']))
    size = size or SIZES['compact']
    button.setProperty('density', 'regular' if size == SIZES['control'] else 'compact')
    button.setFixedSize(size,size)
    button.setToolTip(description)
    button.setAccessibleName(description)
    return button
