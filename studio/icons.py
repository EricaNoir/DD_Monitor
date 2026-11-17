"""One consistent set of 24px outline icons, rendered crisply at HiDPI."""
from math import cos, sin, pi
from PySide6.QtCore import Qt, QRectF, QPointF, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QPolygonF

_cache = {}


def icon(name):
    if name in _cache:
        return _cache[name]
    image = QPixmap(48, 48)
    image.fill(Qt.transparent)
    image.setDevicePixelRatio(2)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor('#dcdcdc'), 1.65, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
    def circle(x,y,r):
        p.drawEllipse(QPointF(x,y),r,r)
    if name == 'pause':
        p.drawRoundedRect(QRectF(6,5,3,14),.6,.6); p.drawRoundedRect(QRectF(15,5,3,14),.6,.6)
    elif name == 'play':
        p.drawPolygon(QPolygonF([QPointF(7,4),QPointF(19,12),QPointF(7,20)]))
    elif name in ('volume','muted'):
        p.drawPolygon(QPolygonF([QPointF(3,9),QPointF(6,9),QPointF(11,5),QPointF(11,19),QPointF(6,15),QPointF(3,15)]))
        if name == 'muted':
            line(16,9,21,15); line(21,9,16,15)
        else:
            p.drawArc(QRectF(9,7,10,10),-55*16,110*16); p.drawArc(QRectF(7,3,16,18),-50*16,100*16)
    elif name == 'reload':
        p.drawArc(QRectF(5,5,14,14),35*16,290*16); line(19,3,19,8); line(19,8,14,8)
    elif name == 'headphones':
        p.drawArc(QRectF(5,4,14,16),0,180*16)
        p.drawRoundedRect(QRectF(4,11,4,8),1.3,1.3); p.drawRoundedRect(QRectF(16,11,4,8),1.3,1.3)
    elif name in ('expand','collapse'):
        for x,y,sx,sy in [(4,4,1,1),(20,4,-1,1),(4,20,1,-1),(20,20,-1,-1)]:
            if name == 'collapse': x,y,sx,sy=x+sx*5,y+sy*5,-sx,-sy
            line(x,y,x+sx*5,y); line(x,y,x,y+sy*5)
    elif name == 'chat':
        path=QPainterPath(); path.moveTo(5,4); path.lineTo(19,4); path.quadTo(21,4,21,6)
        path.lineTo(21,15); path.quadTo(21,17,19,17); path.lineTo(10,17); path.lineTo(5,21)
        path.lineTo(5,17); path.quadTo(3,17,3,15); path.lineTo(3,6); path.quadTo(3,4,5,4)
        p.drawPath(path); line(7,9,17,9); line(7,13,13,13)
    elif name == 'add':
        line(5,12,19,12); line(12,5,12,19)
    elif name == 'close':
        line(6,6,18,18); line(18,6,6,18)
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
        circle(12,12,6); circle(12,12,2)
        for i in range(8):
            a=i*pi/4; line(12+7*cos(a),12+7*sin(a),12+9*cos(a),12+9*sin(a))
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
            p.setBrush(QColor('#d9c794'))
            p.setPen(QPen(QColor('#d9c794'),1.5))
        p.drawPolygon(QPolygonF(points))
    else:
        p.end()
        raise ValueError(f'Unknown icon: {name}')
    p.end()
    result=QIcon(image)
    _cache[name]=result
    return result


def decorate(button, name, description, size=28):
    button.setText('')
    button.setProperty('iconOnly', True)
    button.setIcon(icon(name))
    button.setIconSize(QSize(18,18))
    button.setFixedSize(size,size)
    button.setToolTip(description)
    button.setAccessibleName(description)
    return button
