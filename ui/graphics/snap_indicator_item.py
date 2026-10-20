"""
ui/graphics/snap_indicator_item.py
Đường kẻ xanh dương hiện ra khi clip snap vào điểm hít.
ZValue = 998 (ngay dưới playhead).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPen, QColor
from PySide6.QtWidgets import QGraphicsLineItem


class SnapIndicatorItem(QGraphicsLineItem):
    """
    Đường kẻ dọc hiển thị tạm thời khi snap kích hoạt.

    Sử dụng:
        indicator.show_at(x=150.0, height=400.0)   # hiện
        indicator.hide_indicator()                   # ẩn
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Nét đứt xanh dương, khá mảnh
        pen = QPen(QColor("#55D6FF"), 1, Qt.DashLine)
        pen.setCosmetic(True)
        pen.setDashPattern([6, 4])
        self.setPen(pen)

        self.setZValue(998)
        self.setVisible(False)

    def show_at(self, x: float, height: float = 2000.0):
        """Hiển thị indicator tại vị trí X."""
        self.setLine(x, 0, x, height)
        self.setVisible(True)

    def hide_indicator(self):
        """Ẩn indicator."""
        self.setVisible(False)
