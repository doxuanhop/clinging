"""
ui/graphics/track_header_scene.py
QGraphicsScene cho cột Track Header cố định bên trái Timeline.

Hiển thị: tên track, icon loại (Font Awesome), nút Lock/Visible/Mute.
Không cuộn ngang — chỉ cuộn dọc đồng bộ với Timeline View.
"""

from PySide6.QtCore import Qt, QRectF, Signal, QSize
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QPixmap, QImage
)
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsRectItem, QGraphicsItem
)

from core.timeline_model import (
    TimelineModel, TrackModel, TrackType,
    TIMELINE_RULER_HEIGHT, TIMELINE_TRACK_TOP_PADDING, TIMELINE_TRACK_GAP,
    timeline_tracks_height, timeline_scene_height,
)


# ── Font Awesome icon names cho từng loại track ──────────────────
TRACK_ICONS = {
    TrackType.VIDEO:   "fa6s.film",
    TrackType.AUDIO:   "fa6s.music",
    TrackType.IMAGE:   "fa6s.image",
    TrackType.TEXT:    "fa6s.font",
    TrackType.EFFECT:  "fa6s.wand-magic-sparkles",
    TrackType.OVERLAY: "fa6s.face-smile",
}

# ── Font Awesome icon names cho nút toggle ────────────────────────
ICON_VISIBLE_ON = "fa6s.eye"
ICON_VISIBLE_OFF = "fa6s.eye-slash"
ICON_MUTE_ON = "fa6s.volume-xmark"
ICON_MUTE_OFF = "fa6s.volume-high"
ICON_LOCK_ON = "fa6s.lock"
ICON_LOCK_OFF = "fa6s.lock-open"


def _qta():
    """Lazy import qtawesome."""
    import qtawesome
    return qtawesome


def _icon_pixmap(icon_name: str, size: int = 16, color: str = "#AAAAAA") -> QPixmap:
    """Tạo QPixmap từ Font Awesome icon name."""
    return _qta().icon(icon_name, color=color).pixmap(QSize(size, size))


class TrackHeaderItem(QGraphicsRectItem):
    """
    Một hàng header tương ứng với một TrackModel.
    Vẽ tên, icon (Font Awesome), và 3 nút toggle (visible, mute, lock).
    """

    CONTROL_WIDTH = 120.0
    COVER_WIDTH = 56.0
    HEADER_WIDTH = CONTROL_WIDTH + COVER_WIDTH

    def __init__(self, track_model: TrackModel, lane_index: int,
                 parent=None):
        super().__init__(parent)
        self.track_model = track_model
        self._lane_index = lane_index
        self._hover = False

        self._calc_geometry()

        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(5)

    def _calc_geometry(self):
        gap = 2.0
        y = self._lane_index * (self.track_model.height + gap)
        self.setRect(0, y, self.HEADER_WIDTH, self.track_model.height)

    def update_geometry(self, lane_index: int, track_y: float | None = None):
        self._lane_index = lane_index
        self.prepareGeometryChange()
        if track_y is None:
            self._calc_geometry()
        else:
            self.setRect(0, track_y, self.HEADER_WIDTH, self.track_model.height)
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.rect()
        h = rect.height()
        y = rect.y()

        # Nền xen kẽ sáng/tối
        is_even = self._lane_index % 2 == 0
        bg = QColor("#0F1015") if is_even else QColor("#12131A")
        if self._hover:
            bg = bg.lighter(115)
        painter.fillRect(rect, bg)

        # Đường kẻ dưới
        painter.setPen(QPen(QColor("#1C1E27"), 1))
        painter.drawLine(int(rect.x()), int(y + h - 1),
                         int(rect.x() + rect.width()), int(y + h - 1))

        # Divider between controls, the fixed Cover slot and Track Body.
        painter.setPen(QPen(QColor("#242731"), 1))
        painter.drawLine(int(self.CONTROL_WIDTH), int(y),
                         int(self.CONTROL_WIDTH), int(y + h))
        painter.drawLine(int(self.HEADER_WIDTH - 1), int(y),
                         int(self.HEADER_WIDTH - 1), int(y + h))

        # Thanh color indicator bên trái
        track_color = QColor(self.track_model.color)
        painter.fillRect(QRectF(0, y, 3, h), track_color)

        # Compact single-row controls, matching professional NLE track headers.
        is_cover = (self.track_model.is_main_track and
                    self.track_model.track_type == TrackType.VIDEO)
        icon_name = TRACK_ICONS.get(
            self.track_model.track_type, "fa6s.film")
        icon_pixmap = _icon_pixmap(
            icon_name, size=14, color="#AAAAAA"
        )
        icon_x = 8
        icon_y = int(y + (h - 14) / 2)
        painter.drawPixmap(icon_x, icon_y, icon_pixmap)
        self._cover_rect = QRectF()

        # Tên track
        font = QFont("Segoe UI", 8)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#D1D5DB"))
        name_rect = QRectF(26, y, 40, h)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft,
                         self.track_model.name)

        # ── 3 nút toggle (Font Awesome icons) ──

        # Con mắt (Visible)
        has_visual = self.track_model.track_type != TrackType.AUDIO
        has_audio = self.track_model.track_type in (TrackType.VIDEO, TrackType.AUDIO)
        self._visible_rect = QRectF(66, y, 18, h) if has_visual else QRectF()
        if has_visual:
            visible_color = "#40E0D0" if self.track_model.is_visible else "#444444"
            visible_icon = ICON_VISIBLE_ON if self.track_model.is_visible else ICON_VISIBLE_OFF
            visible_pm = _icon_pixmap(visible_icon, size=11, color=visible_color)
            painter.drawPixmap(int(self._visible_rect.center().x() - 5),
                               int(self._visible_rect.center().y() - 5), visible_pm)

        # Loa (Mute)
        self._mute_rect = QRectF(84, y, 18, h) if has_audio else QRectF()
        if has_audio:
            mute_color = "#444444" if self.track_model.is_muted else "#40E0D0"
            mute_icon = ICON_MUTE_ON if self.track_model.is_muted else ICON_MUTE_OFF
            mute_pm = _icon_pixmap(mute_icon, size=11, color=mute_color)
            painter.drawPixmap(int(self._mute_rect.center().x() - 5),
                               int(self._mute_rect.center().y() - 5), mute_pm)

        # Khóa (Lock)
        self._lock_rect = QRectF(102, y, 18, h)
        lock_color = "#40E0D0" if self.track_model.is_locked else "#888888"
        lock_icon = ICON_LOCK_ON if self.track_model.is_locked else ICON_LOCK_OFF
        lock_pm = _icon_pixmap(lock_icon, size=11, color=lock_color)
        painter.drawPixmap(
            int(self._lock_rect.center().x() - 5),
            int(self._lock_rect.center().y() - 5),
            lock_pm
        )

        # CapCut-style fixed Cover tile: it sits immediately before the
        # horizontally scrolling Track Body, never inside the time canvas.
        if is_cover:
            self._cover_rect = QRectF(
                self.CONTROL_WIDTH + 3, y + 3,
                self.COVER_WIDTH - 6, h - 6)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#4B5563"), 1))
            painter.setBrush(QColor("#182126"))
            painter.drawRoundedRect(self._cover_rect, 4, 4)

            cover_icon = _icon_pixmap(
                "fa6s.image", size=15, color="#B9FFF6")
            painter.drawPixmap(
                int(self._cover_rect.center().x() - 7),
                int(self._cover_rect.top() + 5), cover_icon)
            pencil = _icon_pixmap(
                "fa6s.pen", size=8, color="#FFFFFF")
            painter.drawPixmap(
                int(self._cover_rect.right() - 11),
                int(self._cover_rect.top() + 3), pencil)

            cover_font = QFont("Segoe UI", 7)
            cover_font.setWeight(QFont.DemiBold)
            painter.setFont(cover_font)
            painter.setPen(QColor("#E5E7EB"))
            painter.drawText(
                QRectF(self._cover_rect.left(),
                       self._cover_rect.bottom() - 18,
                       self._cover_rect.width(), 16),
                Qt.AlignCenter, "Ảnh bìa")

    def mousePressEvent(self, event):
        pos = event.pos()

        if hasattr(self, "_cover_rect") and self._cover_rect.contains(pos):
            scene = self.scene()
            if scene and hasattr(scene, "cover_requested"):
                scene.cover_requested.emit(self.track_model)
            event.accept()
            return

        if hasattr(self, "_visible_rect") and self._visible_rect.contains(pos):
            self.track_model.is_visible = not self.track_model.is_visible
            self.update()
            scene = self.scene()
            if scene and hasattr(scene, "track_state_changed"):
                scene.track_state_changed.emit(
                    self.track_model, "visible", self.track_model.is_visible
                )
            event.accept()
            return

        if hasattr(self, "_mute_rect") and self._mute_rect.contains(pos):
            self.track_model.is_muted = not self.track_model.is_muted
            self.update()
            scene = self.scene()
            if scene and hasattr(scene, "track_state_changed"):
                scene.track_state_changed.emit(
                    self.track_model, "mute", self.track_model.is_muted
                )
            event.accept()
            return

        if hasattr(self, "_lock_rect") and self._lock_rect.contains(pos):
            self.track_model.is_locked = not self.track_model.is_locked
            self.update()
            scene = self.scene()
            if scene and hasattr(scene, "track_state_changed"):
                scene.track_state_changed.emit(
                    self.track_model, "lock", self.track_model.is_locked
                )
            event.accept()
            return

        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            # Header chỉ kéo theo trục dọc; ID track_model là binding
            # duy nhất với Track Body.
            return value.__class__(0.0, max(0.0, value.y()))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene and hasattr(scene, "request_track_move"):
            scene.request_track_move(self.track_model.track_id,
                                     self.sceneBoundingRect().center().y())

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()


class TrackHeaderScene(QGraphicsScene):
    """
    Scene chứa các TrackHeaderItem.
    Quản lý thêm/xóa/sắp xếp lại header khi model thay đổi.
    """

    # (track_model, action_type, is_active)
    track_state_changed = Signal(object, str, bool)
    cover_requested = Signal(object)

    RULER_HEIGHT = TIMELINE_RULER_HEIGHT
    TRACK_TOP_PADDING = TIMELINE_TRACK_TOP_PADDING
    TRACK_GAP = TIMELINE_TRACK_GAP
    HEADER_WIDTH = TrackHeaderItem.HEADER_WIDTH

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._header_items: dict[str, TrackHeaderItem] = {}

        self.setBackgroundBrush(QColor("#0D0E14"))
        self._relayout()

        # Lắng nghe model
        model.trackAdded.connect(self._on_track_added)
        model.trackRemoved.connect(self._on_track_removed)
        model.tracksReordered.connect(self._relayout)
        model.durationChanged.connect(self._on_duration_changed)

    # ── Model Event Handlers ────────────────────────────────────

    def _on_track_added(self, track: TrackModel):
        lane_index = self._model.tracks.index(track)
        item = TrackHeaderItem(track, lane_index)
        item.setPos(0, self.RULER_HEIGHT)
        self.addItem(item)
        self._header_items[track.track_id] = item
        self._update_scene_rect()

    def _on_track_removed(self, track_id: str):
        item = self._header_items.pop(track_id, None)
        if item:
            self.removeItem(item)
        self._relayout()
        self._update_scene_rect()

    def _on_duration_changed(self, d: float):
        pass  # Header scene không phụ thuộc duration

    def request_track_move(self, track_id: str, center_y: float):
        """Map vị trí thả sang index model, sau đó relayout cả hai scene."""
        y = self.RULER_HEIGHT + self.TRACK_TOP_PADDING
        new_index = len(self._model.tracks) - 1
        for index, track in enumerate(self._model.tracks):
            if center_y < y + track.height / 2.0:
                new_index = index
                break
            y += track.height + self.TRACK_GAP
        if not self._model.move_track(track_id, new_index):
            self._relayout()

    # ── Relayout ────────────────────────────────────────────────

    def _relayout(self):
        y = self.TRACK_TOP_PADDING
        for i, track in enumerate(self._model.tracks):
            item = self._header_items.get(track.track_id)
            if item:
                item.update_geometry(i, y)
                item.setPos(0, self.RULER_HEIGHT)
            y += track.height + self.TRACK_GAP
        self._update_scene_rect()

    def _total_tracks_height(self) -> float:
        return timeline_tracks_height(self._model.tracks,
                                      self.TRACK_TOP_PADDING)

    def _update_scene_rect(self):
        # Cùng một chiều cao với TimelineScene: hai range cuộn phải khớp nhau
        # thì header mới bám được body khi người dùng cuộn hàng.
        h = timeline_scene_height(self._model.tracks, self.TRACK_TOP_PADDING)
        self.setSceneRect(0, 0, self.HEADER_WIDTH, h)

    # ── Background Drawing ──────────────────────────────────────

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)

        # Vùng ruler trên cùng (chỉ nền đen, không có vạch thời gian)
        ruler_rect = QRectF(rect.left(), 0,
                            rect.right() - rect.left(), self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#0D0E14"))

        # Đường kẻ dưới ruler
        painter.setPen(QPen(QColor("#1C1E27"), 1))
        painter.drawLine(int(rect.left()), int(self.RULER_HEIGHT),
                         int(rect.right()), int(self.RULER_HEIGHT))
