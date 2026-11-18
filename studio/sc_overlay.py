"""Owned, input-transparent window: stays above VLC's native video surface."""
import math
import time
from .theme import SIZES, FONTS
from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, QRect
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QApplication


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


def display_interval(message, now):
    interval = sc_interval(message)
    if not interval or interval[1] <= now:
        return None
    start, end = interval
    # Allow roughly five characters per second, plus time to notice the card.
    characters = sum(not char.isspace() for char in str(message.get('text', '')))
    reading_time = max(6, 2 + math.ceil(characters / 5))
    visible_start = max(now, start)
    return visible_start, visible_start + max((end - start) / 10, reading_time)


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
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(SIZES['sc_overlay_gap'])
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
        interval = display_interval(message, now)
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
        inset = SIZES['sc_overlay_inset']
        gap = SIZES['sc_overlay_gap']
        width = min(SIZES['sc_overlay_width'], self.host.width() - 2 * inset)
        if width < 100:
            self.hide()
            return
        current = [(sid, item) for sid, item in self.active.items() if item[1][0] <= now]
        font = QFont(self.font())
        font.setPixelSize(FONTS['caption'])
        metrics = QFontMetrics(font)
        heights = {sid: max(SIZES['sc_overlay_height'], metrics.height() + 12 +
                           metrics.boundingRect(QRect(0, 0, width - 14, 10000), Qt.TextWordWrap,
                                                str(item[0].get('text', ''))).height())
                   for sid, item in current}
        visible, used = [], 0
        for entry in reversed(current[-3:]):
            height = heights[entry[0]]
            if used + height + gap > self.host.height() - 2 * inset - 20:
                break
            visible.insert(0, entry)
            used += height + gap
        more = len(current) - len(visible)
        if not visible:
            self.hide()
            return
        signature = (tuple((sid, heights[sid]) for sid, _ in visible), width, more)
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
                card.setFixedHeight(heights[sid])
                layout = QVBoxLayout(card)
                layout.setContentsMargins(6, 4, 6, 4)
                layout.setSpacing(2)
                heading = QLabel()
                heading.setFont(font)
                heading.setTextFormat(Qt.PlainText)
                title = f'SC ¥{message.get("price", "")} {message.get("name", "观众")}'
                heading.setText(metrics.elidedText(title, Qt.ElideRight, width - 14))
                layout.addWidget(heading)
                body = QLabel(message.get('text', ''))
                body.setFont(font)
                body.setMinimumWidth(0)
                body.setTextFormat(Qt.PlainText)
                body.setWordWrap(True)
                layout.addWidget(body, 1)
                self.box.addWidget(card)
                self.cards.append((sid, heading))
            if more:
                extra = QLabel(f'另有 {more} 条 SC')
                extra.setFixedHeight(16)
                self.box.addWidget(extra)
            self.setFixedHeight(used - gap + (16 + gap if more else 0))
        self.move(self.host.mapToGlobal(QPoint(inset, inset)))
        if not self.isVisible():
            self.show()

    def shutdown(self):
        self.clear()
