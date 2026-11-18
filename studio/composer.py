from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton
from .services import BiliAPI, Job
from .icons import decorate


class ChatComposer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ticket = 0
        self.room = None
        self.api = None
        self.sending = False
        self.limit = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.input = QLineEdit()
        self.input.setMinimumWidth(0)
        self.input.setPlaceholderText('发弹幕…')
        self.input.setAccessibleName('发送到当前直播间的弹幕')
        self.input.returnPressed.connect(self.send)
        self.input.textChanged.connect(self.update_button)
        row.addWidget(self.input, 1)
        self.button = decorate(QPushButton(), 'send', '发送弹幕 · Enter', 26)
        self.button.clicked.connect(self.send)
        row.addWidget(self.button)
        box.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName('Muted')
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.PlainText)
        self.hint.hide()
        box.addWidget(self.hint)
        self.cooldown = QTimer(self)
        self.cooldown.setSingleShot(True)
        self.cooldown.timeout.connect(self.update_button)
        self.set_room(None, {})

    def status(self, text):
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def run_job(self, work, done, failed):
        job = Job(work)
        job.signals.done.connect(done)
        job.signals.error.connect(failed)
        QThreadPool.globalInstance().start(job)

    def set_room(self, room, cookies, load=True):
        self.ticket += 1
        self.room = dict(room) if room else None
        self.api = BiliAPI(cookies)
        self.limit = 0
        self.sending = False
        self.cooldown.stop()
        self.input.clear()
        self.input.setMaxLength(500)
        self.input.setEnabled(bool(room))
        self.status('')
        self.update_button()
        if not room:
            return
        if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
            self.input.setPlaceholderText('登录后发弹幕')
            return
        self.input.setPlaceholderText('发弹幕…')
        self.limit = 500  # send_chat always rechecks the actual server limit.
        self.update_button()
        ticket, api, rid = self.ticket, self.api, room['id']
        if load:
            self.run_job(lambda: api.chat_limit(rid), lambda limit: self.ready(ticket, limit),
                         lambda error: self.limit_failed(ticket, error))

    def limit_failed(self, ticket, error):
        # A background config read must never unlock an in-flight send.
        if ticket == self.ticket and not self.sending and not self.hint.text():
            self.status(error)

    def ready(self, ticket, limit):
        if ticket != self.ticket:
            return
        self.limit = limit
        self.input.setPlaceholderText(f'发弹幕 · 最多 {limit} 字')
        self.update_button()

    def update_button(self, *_):
        length = len(self.input.text().encode('utf-16-le')) // 2
        if self.limit and length > self.limit:
            self.status(f'超出字数：{length}/{self.limit}')
        elif self.hint.text().startswith('超出字数：'):
            self.status('')
        self.button.setEnabled(bool(self.room and self.limit and self.input.text().strip())
                               and length <= self.limit
                               and not self.sending and not self.cooldown.isActive())

    def send(self):
        if not self.button.isEnabled():
            return
        ticket, api, rid, text = self.ticket, self.api, self.room['id'], self.input.text()
        self.sending = True
        self.input.setEnabled(False)
        self.update_button()
        self.status('发送中…')
        self.run_job(lambda: api.send_chat(rid, text), lambda _: self.sent(ticket, text),
                     lambda error: self.failed(ticket, error))

    def sent(self, ticket, text):
        if ticket != self.ticket:
            return
        self.sending = False
        self.input.setEnabled(True)
        if self.input.text() == text:
            self.input.clear()
        self.status('已发送')
        self.cooldown.start(1500)
        self.update_button()
        self.input.setFocus()

    def failed(self, ticket, error):
        if ticket != self.ticket:
            return
        self.sending = False
        self.input.setEnabled(bool(self.room))
        self.status(error)
        self.update_button()
