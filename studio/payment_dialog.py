from decimal import Decimal
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QPlainTextEdit, QFormLayout, QWidget, QFrame, QTabBar)
from .widgets import BelowComboBox, StudioSpinBox as QSpinBox
from .services import Job
from .payments import PaymentAPI, PaymentUnknown, battery, gift_limit


class PaymentConfirmation(QDialog):
    def __init__(self, room, quote, parent=None):
        super().__init__(parent)
        self.setWindowTitle('确认使用电池')
        self.setMinimumWidth(420)
        self.resize(440, 340 if not quote.text else 470)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 22, 24, 20)
        box.setSpacing(18)

        def label(text, kind=None):
            widget = QLabel(text)
            widget.setTextFormat(Qt.PlainText)
            widget.setWordWrap(True)
            if kind:
                widget.setObjectName(kind)
            return widget

        box.addWidget(label('确认发送 SC' if quote.kind == 'sc' else '确认送礼', 'Heading'))
        recipient = QVBoxLayout()
        recipient.setSpacing(5)
        recipient.addWidget(label('发送给', 'Muted'))
        recipient.addWidget(label(str(room['name']), 'Heading'))
        recipient.addWidget(label(f'直播间 {quote.room_id}', 'Muted'))
        box.addLayout(recipient)

        summary = QFrame()
        summary.setObjectName('PaymentSummary')
        details = QVBoxLayout(summary)
        details.setContentsMargins(16, 14, 16, 14)
        details.setSpacing(14)
        item = QHBoxLayout()
        item.addWidget(label(quote.name), 1)
        item.addWidget(label(f'× {quote.quantity}', 'Muted'))
        details.addLayout(item)
        line = QFrame()
        line.setFixedHeight(1)
        line.setObjectName('Divider')
        details.addWidget(line)
        total = QHBoxLayout()
        total.addWidget(label('合计', 'Muted'), 1)
        amount = label(f'{battery(quote.total)} 电池')
        amount.setObjectName('Amount')
        total.addWidget(amount)
        details.addLayout(total)
        box.addWidget(summary)

        if quote.text:
            message = QPlainTextEdit(quote.text)
            message.setReadOnly(True)
            message.setFixedHeight(110)
            box.addWidget(message)
        box.addWidget(label(f'付款账号  UID {quote.uid}', 'Muted'))
        box.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        self.cancel_button = QPushButton('取消')
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.confirm_button = QPushButton(f'确认发送 · {battery(quote.total)} 电池')
        self.confirm_button.setObjectName('Primary')
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        footer.addWidget(self.confirm_button)
        box.addLayout(footer)
        self.cancel_button.setFocus()


class PaymentDialog(QDialog):
    def __init__(self, room, cookies, parent=None, autoload=True):
        super().__init__(parent)
        self.room = dict(room)
        self.api = PaymentAPI(cookies)
        self.panel = None
        self.busy = self.sending = self.terminal = False
        self.order_id = ''
        self.setWindowTitle('送礼物 / 发 SC')
        self.resize(490, 440)
        self.setMinimumWidth(440)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(14)
        title = QLabel(f'送给 {room["name"]}  ·  房间 {room["id"]}')
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setObjectName('Heading')
        box.addWidget(title)
        row = QHBoxLayout()
        self.balance = QLabel('正在读取电池余额…')
        row.addWidget(self.balance, 1)
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        box.addLayout(row)
        self.form = QWidget()
        form = QFormLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(14)
        self.kind = QTabBar()
        self.kind.setObjectName('SearchTabs')
        self.kind.setExpanding(True)
        self.kind.setDrawBase(False)
        self.kind.setAccessibleName('礼物或 SC')
        self.kind.setTabData(self.kind.addTab('礼物'), 'gift')
        self.kind.setTabData(self.kind.addTab('SC'), 'sc')
        form.addRow(self.kind)
        self.item = BelowComboBox()
        form.addRow('选择', self.item)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 9999)
        self.quantity_label = QLabel('数量')
        form.addRow(self.quantity_label, self.quantity)
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText('输入醒目留言')
        self.message.setMinimumHeight(100)
        self.message_label = QLabel('留言')
        form.addRow(self.message_label, self.message)
        box.addWidget(self.form)
        self.total = QLabel('')
        box.addWidget(self.total)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setWordWrap(True)
        self.status.setObjectName('Muted')
        box.addWidget(self.status, 1)
        footer = QHBoxLayout()
        self.query = QPushButton('查询 SC 结果')
        self.query.hide()
        self.query.clicked.connect(self.query_result)
        footer.addWidget(self.query)
        footer.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        self.send_button = QPushButton('确认发送')
        self.send_button.setObjectName('Primary')
        self.send_button.setAutoDefault(False)
        self.send_button.clicked.connect(self.prepare)
        footer.addWidget(self.send_button)
        box.addLayout(footer)
        self.kind.currentChanged.connect(self.populate)
        self.item.currentIndexChanged.connect(self.update_total)
        self.quantity.valueChanged.connect(self.update_total)
        self.message.textChanged.connect(self.update_total)
        self.populate()
        if autoload:
            self.reload()

    def run_job(self, work, done, error=None):
        job = Job(work)
        job.signals.done.connect(done)
        job.signals.error.connect(error or self.failed)
        QThreadPool.globalInstance().start(job)

    def set_busy(self, value):
        self.busy = value
        self.form.setEnabled(not value and not self.terminal)
        self.refresh_button.setEnabled(not value and not self.terminal)
        self.query.setEnabled(not value)
        self.update_total()

    def reload(self):
        if self.busy or self.terminal:
            return
        self.set_busy(True)
        self.status.setText('正在读取当前房间的礼物、SC 和余额…')
        self.run_job(lambda: self.api.load_panel(self.room['id']), self.loaded)

    def loaded(self, panel):
        self.panel = panel
        self.balance.setText(f'余额  {battery(panel["gold"])} 电池')
        self.status.setText('')
        self.populate()
        self.set_busy(False)

    def populate(self, *_):
        sc = self.kind.tabData(self.kind.currentIndex()) == 'sc'
        self.quantity.setVisible(not sc)
        self.quantity_label.setVisible(not sc)
        self.message.setVisible(sc)
        self.message_label.setVisible(sc)
        self.item.blockSignals(True)
        self.item.clear()
        if self.panel:
            if sc:
                for entry in self.panel['sc'].get('price_configs') or []:
                    if (entry.get('type_detail') or {}).get('can_buy') is False:
                        continue
                    amount = int(Decimal(str(entry['price'])) * 1000)
                    suffix = (entry.get('type_detail') or {}).get('button_text', '')
                    self.item.addItem(f'{battery(amount)} 电池 · {entry["second"]} 秒 {suffix}', entry)
                self.status.setText(self.panel.get('sc_error') or '')
            else:
                for entry in self.panel['gifts']:
                    self.item.addItem(f'{entry["name"]} · {battery(entry["price"])} 电池', entry)
                self.status.setText(self.panel.get('gift_error') or '普通电池礼物；活动、盲盒和大航海商品暂未接入。')
        self.item.blockSignals(False)
        self.update_total()

    def update_total(self, *_):
        entry = self.item.currentData()
        valid = bool(entry and self.panel)
        if valid:
            sc = self.kind.tabData(self.kind.currentIndex()) == 'sc'
            if sc:
                total = int(Decimal(str(entry['price'])) * 1000)
                length = len(self.message.toPlainText().encode('utf-16-le')) // 2
                self.total.setText(f'合计 {battery(total)} 电池  ·  {length}/{entry["limit"]} 字')
                valid = bool(self.message.toPlainText().strip()) and length <= int(entry['limit'])
                ban = self.panel['sc'].get('user_ban_info') or {}
                valid = valid and not ban.get('limited')
                if ban.get('limited') and not self.terminal:
                    self.status.setText(ban.get('limited_tip') or '当前账号暂时不能发送 SC。')
            else:
                self.quantity.setMaximum(gift_limit(entry))
                total = int(entry['price']) * self.quantity.value()
                self.total.setText(f'合计 {battery(total)} 电池')
            valid = valid and total <= self.panel['gold']
            if total > self.panel['gold']:
                self.total.setText(self.total.text() + '  ·  余额不足')
        else:
            self.total.setText('暂无可发送项目')
        self.send_button.setEnabled(valid and not self.busy and not self.terminal)

    def prepare(self):
        if not self.send_button.isEnabled():
            return
        entry = self.item.currentData()
        kind, count, text = self.kind.tabData(self.kind.currentIndex()), self.quantity.value(), self.message.toPlainText()
        self.set_busy(True)
        self.status.setText('正在核对价格、余额和发送资格…')
        self.run_job(lambda: self.api.prepare(self.room['id'], kind, entry['id'], count, text), self.confirm)

    def confirm(self, quote):
        confirm = PaymentConfirmation(self.room, quote, self)
        if confirm.exec() != QDialog.Accepted:
            self.set_busy(False)
            self.status.setText('已取消，未发送。')
            return
        self.sending = True
        self.status.setText('正在发送，请稍候…')
        def submit():
            try:
                return {'result': self.api.send(quote)}
            except PaymentUnknown as error:
                return {'unknown': str(error)}
        self.run_job(submit, self.sent, self.failed)

    def sent(self, data):
        self.sending = False
        self.terminal = True
        self.set_busy(False)
        if 'unknown' in data:
            self.status.setText(data['unknown'])
            return
        result = data['result']
        self.order_id = result.get('order_id', '')
        self.query.setVisible(bool(self.order_id))
        self.status.setText(result['text'] + (f'\n订单号：{self.order_id}' if self.order_id else ''))
        self.run_job(self.api.wallet, lambda gold: self.balance.setText(f'余额  {battery(gold)} 电池'),
                     lambda _: self.balance.setText('余额待刷新'))

    def failed(self, error):
        # A nonzero payment response can still need manual reconciliation.
        if self.sending:
            self.terminal = True
        self.sending = False
        self.set_busy(False)
        self.status.setText(error)

    def query_result(self):
        if not self.order_id or self.busy:
            return
        self.set_busy(True)
        def done(text):
            self.set_busy(False)
            self.status.setText(f'{text}\n订单号：{self.order_id}')
        self.run_job(lambda: self.api.sc_result(self.order_id), done)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
