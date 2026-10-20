"""
ui/graphics/playhead_item.py
Vạch playhead đỏ — luôn hiển thị trên cùng (ZValue=999).

Cấu tạo:
    ┌──▼──┐   ← Tam giác đầu (PlayheadHead)
    │     │
    ┃     ┃   ← Đường thẳng đỏ xuyên toàn bộ track
    ┃     ┃
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QPainterPath, QBrush
from PySide6.QtWidgets import (
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsItem
)

from core.time_mapper import TimePixelMapper


class PlayheadItem(QGraphicsLineItem):
    """
    Vạch chỉ thời gian đỏ trên Timeline Scene.

    Features:
        - ZValue = 999 → luôn trên cùng
        - Kéo được theo trục X (constraint Y)
        - Tam giác đầu phía trên
        - Kết nối TimePixelMapper để chuyển vị trí ↔ thời gian
    """

    def __init__(self, mapper: TimePixelMapper, scene_height: float = 600,
                 parent=None):
        super().__init__(parent)
        self._mapper = mapper
        self._scene_height = scene_height
        self._dragging = False
        self._time = 0.0

        # Visual setup
        color = QColor("#FF4D4F")
        pen = QPen(color, 2)
        pen.setCosmetic(True)   # Không bị ảnh hưởng bởi zoom
        self.setPen(pen)
        self.setZValue(999)

        # Tam giác đầu
        self._head = _PlayheadHead(color, self)
        self._head.setPos(0, 0)

        # Interaction
        self.setFlag(QGraphicsItem.ItemIsMovable, False)  # custom drag
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeHorCursor)
        self.setAcceptHoverEvents(True)

        # Vị trí ban đầu
        self.set_time(0.0)

    # ── Public API ──────────────────────────────────────────────

    def set_time(self, t: float):
        """Đặt playhead tại thời gian `t` (giây)."""
        self._time = max(0.0, float(t))
        x = self._mapper.time_to_pixel(self._time)
        self.setLine(x, 0, x, self._scene_height)
        self._head.setPos(x, 0)

    def get_time(self) -> float:
        """Lấy thời gian hiện tại của playhead."""
        return self._time

    def update_height(self, h: float):
        """Cập nhật chiều cao khi thêm/xóa track."""
        self._scene_height = h
        x = self.line().x1()
        self.setLine(x, 0, x, h)

    # ── Mouse Interaction ───────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            x = max(self._mapper.LEFT_MARGIN, event.scenePos().x())
            t = self._mapper.pixel_to_time(x)
            self.set_time(t)
            # Scene sẽ lắng nghe qua polling hoặc timer
            scene = self.scene()
            if scene and hasattr(scene, "playhead_moved"):
                scene.playhead_moved.emit(t)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#FF7875"), 3))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(QColor("#FF4D4F"), 2))
        super().hoverLeaveEvent(event)


class _PlayheadHead(QGraphicsPathItem):
    """Tam giác nhỏ trên đầu playhead."""

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        path = QPainterPath()
        # Tam giác hướng xuống, rộng 12px, cao 10px
        path.moveTo(-6, 0)
        path.lineTo(6, 0)
        path.lineTo(0, 10)
        path.closeSubpath()
        self.setPath(path)
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(999)
