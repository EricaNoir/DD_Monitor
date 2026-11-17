import html
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QTextBrowser
from .services import safe_image
from .runtime import configure_qt_tls


def message_html(message, names=True):
    name = html.escape(message.get('name', '观众'))
    text = html.escape(message.get('text', ''))
    for token, url in sorted(message.get('images', {}).items(), key=lambda pair: -len(pair[0])):
        url = safe_image(url)
        if url:
            text = text.replace(html.escape(token), f'<img width="24" height="24" src="{html.escape(url, quote=True)}">')
    emoji = safe_image(message.get('emoji', ''))
    if emoji:
        text = f'<img width="48" height="48" alt="{text}" src="{html.escape(emoji, quote=True)}">'
    medal = ''
    if names and message.get('medal'):
        medal = f'<span style="color:#bcbcbc;background-color:#353535;"> {html.escape(message["medal"])} {html.escape(message.get("level", ""))} </span> '
    sender = f'<span style="color:#a9a9a9;">{name}</span><span style="color:#888888;">：</span>' if names else ''
    return f'<p style="margin:6px 0;line-height:140%;">{medal}{sender}<span style="color:#dedede;">{text}</span></p>'


class ChatView(QTextBrowser):
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
        if self.follow and at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)

    def show_history(self, history):
        self.setHtml(''.join(message_html(message, self.names) for message in history))
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
