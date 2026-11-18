"""Owned, input-transparent window: stays above VLC's native video surface."""
import math
import time
from PySide6.QtCore import Qt, QTimer, QEvent, QPoint
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QProgressBar, QApplication


def sc_interval(message):
    try:
        start = float(message.get('start_time') or 0)
        end = float(message.get('end_time') or 0)
        duration = float(message.get('duration') or 0)
        if not all(math.isfinite(v) for v in (start, end, duration)):
            return None
        if end <= 0 and start > 0 and duration > 0:
            end = start + duration
        if start <= 0 and end > 0 and duration > 0:
            start = end - duration
        return (start, end) if 0 < start < end else None
    except (TypeError, ValueError):
        return None


class SCOverlay(QFrame):
    def __init__(self, host):
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.WindowTransparentForInput)
        self.host = host
        self.active = {}
        self.cards = []
        self.signature = None
        self.watching = False
        self.setObjectName('SCOverlay')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet('''QFrame#SCOverlay { background: transparent; }
            QFrame#SCCard { background: rgba(38,35,29,235); border: 1px solid #65563b; border-radius: 6px; }
            QLabel { background: transparent; color: #f3ead8; border: 0; font-size: 12px; }
            QProgressBar { background: #494033; border: 0; border-radius: 1px; }
            QProgressBar::chunk { background: #c5a669; border-radius: 1px; }''')
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.sync)

    def watch(self, enabled):
        if enabled == self.watching:
            return
        self.watching = enabled
        app = QApplication.instance()
        if enabled:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.WindowStateChange):
            if watched in (self.host, self.host.parentWidget(), self.host.window()):
                if event.type() == QEvent.Hide:
                    self.hide()
                elif self.active:
                    QTimer.singleShot(0, self.sync)
        return False

    def add_message(self, message, now=None):
        now = time.time() if now is None else now
        sid = str(message.get('id') or '')
        interval = sc_interval(message)
        if not sid or not interval or interval[1] <= now or sid in self.active:
            return
        self.active[sid] = (dict(message), interval)
        self.watch(True)
        if len(self.active) > 200:
            del self.active[min(self.active, key=lambda key: self.active[key][1][1])]
        self.timer.start()
        self.sync(now)

    def remove_ids(self, ids):
        for sid in ids:
            self.active.pop(str(sid), None)
        self.sync()

    def clear(self):
        self.active.clear()
        self.timer.stop()
        self.watch(False)
        self.signature = None
        self.hide()

    def sync(self, now=None):
        now = time.time() if now is None else now
        self.active = {sid: item for sid, item in self.active.items() if item[1][1] > now}
        if not self.active:
            self.timer.stop()
            self.watch(False)
            self.hide()
            return
        window = self.host.window()
        if not self.host.isVisible() or not window.isVisible() or window.isMinimized():
            self.hide()
            return
        width = min(320, self.host.width() - 20)
        capacity = min(3, max(0, (self.host.height() - 38) // 105))
        if width < 100 or not capacity:
            self.hide()
            return
        current = [(sid, item) for sid, item in self.active.items() if item[1][0] <= now]
        visible = current[-capacity:]
        more = len(current) - len(visible)
        if not visible:
            self.hide()
            return
        signature = (tuple(sid for sid, _ in visible), width, more)
        if signature != self.signature:
            self.signature = signature
            while self.box.count():
                widget = self.box.takeAt(0).widget()
                if widget:
                    widget.hide()
                    widget.deleteLater()
            self.cards = []
            self.setFixedWidth(width)
            for sid, (message, interval) in visible:
                card = QFrame()
                card.setObjectName('SCCard')
                card.setFixedHeight(99)
                layout = QVBoxLayout(card)
                layout.setContentsMargins(10, 7, 10, 7)
                layout.setSpacing(4)
                heading = QLabel()
                heading.setTextFormat(Qt.PlainText)
                layout.addWidget(heading)
                body = QLabel(message.get('text', ''))
                body.setTextFormat(Qt.PlainText)
                body.setWordWrap(True)
                layout.addWidget(body, 1)
                progress = QProgressBar()
                progress.setRange(0, 1000)
                progress.setTextVisible(False)
                progress.setFixedHeight(3)
                layout.addWidget(progress)
                self.box.addWidget(card)
                self.cards.append((sid, heading, progress))
            if more:
                extra = QLabel(f'另有 {more} 条 SC · 在 SC 标签查看')
                extra.setFixedHeight(16)
                self.box.addWidget(extra)
            self.setFixedHeight(len(visible) * 105 - 6 + (22 if more else 0))
        for sid, heading, progress in self.cards:
            message, (start, end) = self.active[sid]
            seconds = max(0, math.ceil(end - now))
            remaining = f'{seconds // 60}:{seconds % 60:02d}'
            title = f'SC ¥{message.get("price", "")} · {message.get("name", "观众")} · {remaining}'
            heading.setText(heading.fontMetrics().elidedText(title, Qt.ElideMiddle, width - 22))
            progress.setValue(max(0, min(1000, int(1000 * (end - now) / (end - start)))))
        self.move(self.host.mapToGlobal(QPoint(10, 10)))
        if not self.isVisible():
            self.show()

    def shutdown(self):
        self.clear()
