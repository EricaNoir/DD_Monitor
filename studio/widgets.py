from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QComboBox


class BelowComboBox(QComboBox):
    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        position = self.mapToGlobal(QPoint(0, self.height() + 3))
        available = self.screen().availableGeometry()
        width = min(max(self.width(), popup.width()), available.width())
        height = min(popup.height(), max(30, available.bottom() - position.y()))
        x = max(available.left(), min(position.x(), available.right() - width + 1))
        popup.setGeometry(x, position.y(), width, height)
