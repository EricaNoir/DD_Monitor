from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QComboBox, QSpinBox, QAbstractSpinBox, QStyleOptionSpinBox, QStyle
from .icons import paint_icon
from .theme import COLORS, SIZES


class BelowComboBox(QComboBox):
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.setProperty('density', 'compact' if compact else 'regular')
        self.setFixedHeight(SIZES['compact' if compact else 'control'])

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        paint_icon(painter, 'chevron_down', QRectF(self.width() - 24, 0, 22, self.height()),
                   size=SIZES['inline_icon'], color=COLORS['icon' if self.isEnabled() else 'text_disabled'])

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        position = self.mapToGlobal(QPoint(0, self.height() + 3))
        available = self.screen().availableGeometry()
        width = min(max(self.width(), popup.width()), available.width())
        height = min(popup.height(), max(30, available.bottom() - position.y()))
        x = max(available.left(), min(position.x(), available.right() - width + 1))
        popup.setGeometry(x, position.y(), width, height)


class StudioSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(SIZES['control'])

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        for control, name, flag in ((QStyle.SC_SpinBoxUp, 'chevron_up', QAbstractSpinBox.StepEnabledFlag.StepUpEnabled),
                                    (QStyle.SC_SpinBoxDown, 'chevron_down', QAbstractSpinBox.StepEnabledFlag.StepDownEnabled)):
            rect = self.style().subControlRect(QStyle.CC_SpinBox, option, control, self)
            enabled = self.isEnabled() and bool(self.stepEnabled() & flag)
            paint_icon(painter, name, rect, size=SIZES['stepper_icon'],
                       color=COLORS['icon' if enabled else 'text_disabled'])
