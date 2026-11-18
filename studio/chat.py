import html
from PySide6.QtCore import QUrl, Qt, QRectF
from PySide6.QtGui import QImage, QTextDocument, QTextCursor, QTextFormat, QPainter, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QTextBrowser
from .services import safe_image
from .runtime import configure_qt_tls


def message_html(message, names=True):
    name = html.escape(message.get('name', '观众'))
    text = html.escape(message.get('text', ''))
    if message.get('kind') == 'gift':
        sender = name + ' ' if names else ''
        return f'<p style="margin:6px 0;color:#cbbd98;">礼物 · {sender}{text}</p>'
    if message.get('kind') == 'sc':
        price = html.escape(str(message.get('price', '')))
        sender = ' · ' + name if names else ''
        return (f'<p style="margin:20px 10px;line-height:145%;">'
                f'<span style="color:#e8cd91;font-weight:600;">SC ¥{price}{sender}</span>'
                f'<br><span style="color:#f0e9db;">{text.replace(chr(10), "<br>")}</span></p>')
    for token, url in sorted(message.get('images', {}).items(), key=lambda pair: -len(pair[0])):
        url = safe_image(url)
        if url:
            text = text.replace(html.escape(token), f'<img width="24" height="24" src="{html.escape(url, quote=True)}">')
    emoji = safe_image(message.get('emoji', ''))
    if emoji:
        text = f'<img width="48" height="48" alt="{text}" src="{html.escape(emoji, quote=True)}">'
    medal = ''
    if names and message.get('medal'):
        medal = f'<span style="color:#bba5d2;font-style:italic;">{html.escape(message["medal"])} {html.escape(message.get("level", ""))}</span>&nbsp;&nbsp;'
    sender = f'<span style="color:#a9a9a9;">{name}</span><span style="color:#888888;">：</span>' if names else ''
    return f'<p style="margin:6px 0;line-height:140%;">{medal}{sender}<span style="color:#dedede;">{text}</span></p>'


class ChatView(QTextBrowser):
    SC_BUBBLE = int(QTextFormat.UserProperty) + 1

    def __init__(self):
        super().__init__()
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(500)
        configure_qt_tls()
        self.network = QNetworkAccessManager(self)
        self.pending = set()
        self.images = {}
        self.follow = True
        self.names = True
        self.setPlaceholderText('等待这个直播间的消息')

    def loadResource(self, resource_type, url):
        if resource_type != QTextDocument.ImageResource:
            return super().loadResource(resource_type, url)
        address = safe_image(url.toString())
        if not address:
            return QImage()
        if address in self.images:
            return self.images[address]
        if address not in self.pending and len(self.pending) < 32:
            self.pending.add(address)
            request = QNetworkRequest(QUrl(address))
            request.setTransferTimeout(10000)
            reply = self.network.get(request)
            reply.finished.connect(lambda: self.image_ready(address, reply))
        return QImage()

    def image_ready(self, address, reply):
        self.pending.discard(address)
        if reply.error() == QNetworkReply.NoError:
            data = bytes(reply.readAll())
            image = QImage.fromData(data) if len(data) < 2_000_000 else QImage()
            if not image.isNull():
                if len(self.images) >= 200:
                    self.images.pop(next(iter(self.images)))
                self.images[address] = image
                self.document().addResource(QTextDocument.ImageResource, QUrl(address), image)
                self.document().markContentsDirty(0, self.document().characterCount())
        reply.deleteLater()

    def add_message(self, message):
        bar = self.verticalScrollBar()
        position = bar.value()
        at_bottom = bar.maximum() - position < 32
        self.append(message_html(message, self.names))
        self.mark_bubble(self.document().lastBlock(), message)
        if self.follow and at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)

    def show_history(self, history):
        messages = list(history)[-500:]
        self.setHtml(''.join(message_html(message, self.names) for message in messages))
        block = self.document().begin()
        for message in messages:
            self.mark_bubble(block, message)
            block = block.next()
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def mark_bubble(self, block, message):
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        fmt.setProperty(self.SC_BUBBLE, message.get('kind') == 'sc')
        cursor.setBlockFormat(fmt)

    def paintEvent(self, event):
        # QTextDocument does not support CSS border-radius. Paint behind its
        # text instead so SC messages keep normal selection, copy and wrapping.
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(event.rect())
        painter.setBrush(QColor('#34312b'))
        painter.setPen(QColor('#484238'))
        block = self.document().begin()
        layout = self.document().documentLayout()
        while block.isValid():
            if block.blockFormat().property(self.SC_BUBBLE):
                rect = layout.blockBoundingRect(block)
                rect.translate(-self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
                if rect.bottom() >= 0 and rect.top() <= self.viewport().height():
                    lines = block.layout()
                    width = max((lines.lineAt(i).naturalTextWidth() for i in range(lines.lineCount())), default=0)
                    top = max(1, rect.top() - 7) if block == self.document().begin() else rect.top() - 7
                    bubble = QRectF(rect.left() + 2, top,
                                    min(rect.width() - 4, width + 16), rect.bottom() + 7 - top)
                    painter.drawRoundedRect(bubble, 8, 8)
            block = block.next()
        painter.end()
        super().paintEvent(event)
