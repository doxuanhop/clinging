"""
ui/graphics/track_lane_item.py
Nền track trên QGraphicsScene — hiển thị nền xen kẽ và đường kẻ phân cách.

Lưu ý: Track Header (tên, icon, nút lock/mute/visible) đã được tách
ra thành TrackHeaderScene/TrackHeaderItem trong track_header_scene.py
để hiển thị cố định bên trái khi cuộn Timeline.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsItem

from core.timeline_model import TrackModel, TrackType
from core.time_mapper import TimePixelMapper


class TrackLaneItem(QGraphicsRectItem):
    """
    Nền track trên Timeline Scene.

    Mỗi TrackLaneItem chiếm toàn bộ chiều rộng scene và có chiều cao
    bằng track_model.height. Chỉ vẽ nền xen kẽ và đường kẻ phân cách.
    Track Header đã được tách sang TrackHeaderScene.

    Attributes:
        track_model: TrackModel liên kết
        mapper: TimePixelMapper dùng chung
        lane_index: Thứ tự track (0 = trên cùng)
    """

    def __init__(self, track_model: TrackModel, mapper: TimePixelMapper,
                 lane_index: int = 0, scene_width: float = 3000,
                 parent=None):
        super().__init__(parent)
        self.track_model = track_model
        self._mapper = mapper
        self._lane_index = lane_index
        self._scene_width = scene_width
        self._hover = False

        # Tính vị trí Y
        y = self._calc_y()
        h = track_model.height
        self.setRect(0, y, scene_width, h)

        # Không selectable, không movable
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)
        # The view is the only drop controller. A lane accepting the event here
        # swallowed it before TimelineView could create the ClipModel.
        self.setAcceptDrops(False)
        self.setZValue(0)  # Nền ở lớp dưới cùng

    def _calc_y(self) -> float:
        """Tính tọa độ Y dựa trên lane_index và chiều cao các track trước."""
        # Đơn giản: mỗi track cách nhau bằng height + gap
        gap = 2.0
        return self._lane_index * (self.track_model.height + gap)

    @property
    def track_y(self) -> float:
        return self.rect().y()

    @property
    def track_height(self) -> float:
        return self.rect().height()

    def update_geometry(self, lane_index: int, scene_width: float,
                        track_y: float | None = None):
        """Cập nhật vị trí khi thêm/xóa track hoặc zoom."""
        self._lane_index = lane_index
        self._scene_width = scene_width
        y = self._calc_y() if track_y is None else track_y
        self.setRect(0, y, scene_width, self.track_model.height)

    # ── Paint ───────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.rect()
        h = rect.height()
        y = rect.y()

        # Nền track (xen kẽ sáng/tối)
        is_even = self._lane_index % 2 == 0
        if (self.track_model.is_main_track and
                self.track_model.track_type == TrackType.VIDEO):
            bg = QColor("#15191A")
        else:
            bg = QColor("#0F1015") if is_even else QColor("#12131A")
        if self._hover:
            bg = bg.lighter(115)
        painter.fillRect(rect, bg)

        # Đường kẻ phân cách dưới
        painter.setPen(QPen(QColor("#1C1E27"), 1))
        painter.drawLine(int(rect.x()), int(y + h - 1),
                         int(rect.x() + rect.width()), int(y + h - 1))

    # ── Hover ───────────────────────────────────────────────────

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()

    # ── Drop ────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            self._hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._hover = False
        self.update()

    def dropEvent(self, event):
        self._hover = False
        self.update()
        # Drop handling sẽ do TimelineScene xử lý qua signal
        event.acceptProposedAction()
