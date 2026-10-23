"""
ui/graphics/timeline_scene.py
QGraphicsScene engine cho Timeline — thay thế hoàn toàn QVBoxLayout.

Kiến trúc:
    TimelineScene
    ├── drawBackground()     → ruler marks, grid lines (CacheBackground)
    ├── TrackLaneItem[]      → nền track
    ├── ClipItem[]           → clip trên track
    ├── PlayheadItem         → vạch playhead đỏ
    └── SnapIndicatorItem    → đường snap xanh
"""

import math

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QGraphicsScene, QGraphicsLineItem

from core.timeline_model import (
    TimelineModel, TrackModel, ClipModel, TrackType,
    TIMELINE_RULER_HEIGHT, TIMELINE_TRACK_TOP_PADDING, TIMELINE_TRACK_GAP,
    timeline_tracks_height, timeline_scene_height,
)
from core.time_mapper import TimePixelMapper
from core.snap_engine import SnapEngine, SnapResult

from ui.graphics.track_lane_item import TrackLaneItem
from ui.graphics.clip_item import ClipItem
from ui.graphics.playhead_item import PlayheadItem
from ui.graphics.snap_indicator_item import SnapIndicatorItem

from typing import Optional


class TimelineScene(QGraphicsScene):
    """
    QGraphicsScene cốt lõi quản lý toàn bộ visual timeline.

    Signals:
        playhead_moved(float)          — playhead kéo đến thời gian mới
        clip_move_finished(str, float, float) — clip di chuyển xong
                                                (clip_id, old_start, new_start)
        clip_resized(str, float, float, float, float)
                                       — clip resize xong
                                         (clip_id, old_start, old_dur,
                                          new_start, new_dur)
        split_requested(str)           — yêu cầu cắt clip (clip_id)
        duplicate_requested(str)       — yêu cầu nhân bản clip (clip_id)
        delete_requested(str)          — yêu cầu xóa clip (clip_id)
        graph_requested(str)           — mở đồ thị đường cong của clip (clip_id)
        audio_detach_requested(str)    — tách tiếng clip video (clip_id)
        resource_dropped(str, str, float)  — resource drop (name, kind, time)
    """

    playhead_moved = Signal(float)
    clip_move_finished = Signal(str, float, float)
    clip_resized = Signal(str, float, float, float, float, float, float)
    split_requested = Signal(str)
    duplicate_requested = Signal(str)
    delete_requested = Signal(str)
    graph_requested = Signal(str)
    audio_detach_requested = Signal(str)
    resource_dropped = Signal(str, str, float, float)  # name, kind, time, drop_y
    preset_dropped = Signal(object, str, float, float)
    effect_dropped = Signal(object, float, float)
    tool_preview_requested = Signal(object, str)
    tool_preview_clear_requested = Signal()

    # Chiều cao ruler trên cùng
    RULER_HEIGHT = TIMELINE_RULER_HEIGHT
    TRACK_TOP_PADDING = TIMELINE_TRACK_TOP_PADDING
    TRACK_GAP = TIMELINE_TRACK_GAP

    def __init__(self, model: TimelineModel, mapper: TimePixelMapper,
                 snap_engine: SnapEngine, parent=None):
        super().__init__(parent)
        self._model = model
        self._mapper = mapper
        self._snap = snap_engine

        # Tối ưu hiệu năng
        self.setItemIndexMethod(QGraphicsScene.NoIndex)  # < 200 items
        self.setBackgroundBrush(QColor("#0B0C10"))

        # --- Items cố định ---
        self._playhead = PlayheadItem(mapper, scene_height=600)
        self.addItem(self._playhead)

        self._snap_indicator = SnapIndicatorItem()
        self.addItem(self._snap_indicator)

        self._drop_placeholder = QGraphicsLineItem()
        self._drop_placeholder.setPen(QPen(QColor("#40E0D0"), 2, Qt.DashLine))
        self._drop_placeholder.setZValue(10000)
        self._drop_placeholder.hide()
        self.addItem(self._drop_placeholder)

        # --- Item maps ---
        self._track_lanes: dict[str, TrackLaneItem] = {}
        self._clip_items: dict[str, ClipItem] = {}

        # --- Kết nối model signals ---
        model.trackAdded.connect(self._on_track_added)
        model.trackRemoved.connect(self._on_track_removed)
        model.tracksReordered.connect(self._relayout_tracks)
        model.clipAdded.connect(self._on_clip_added)
        model.clipRemoved.connect(self._on_clip_removed)
        model.clipMoved.connect(self._on_clip_moved)
        model.clipResized.connect(self._on_clip_resized)
        model.clipUpdated.connect(self._on_clip_updated)
        model.playheadChanged.connect(self._on_playhead_changed)
        model.durationChanged.connect(self._on_duration_changed)

        mapper.zoomChanged.connect(self._on_zoom_changed)

        # --- Scene signals (từ items) ---
        self.clip_move_finished.connect(self._handle_clip_move_finished)
        self.split_requested.connect(self._handle_split)
        self.duplicate_requested.connect(self._handle_duplicate)
        self.delete_requested.connect(self._handle_delete)

        # --- Kết nối Scene selectionChanged để đồng bộ hoá model ---
        # Hai chiều: model chọn clip (từ canvas hay từ code) thì scene phải sáng
        # lên, ngược lại scene bấm mới phải báo về model. Vòng lặp khóa chặt
        # được bởi cả hai handler đều so sánh tập hợp trước khi ghi, nên lần
        # báo trễ của QGraphicsScene không đổi được gì nữa.
        model.selectionChanged.connect(self._on_model_selection_changed)
        self.selectionChanged.connect(self._on_scene_selection_changed)
        self._on_model_selection_changed(model.selected_clip_ids)

        # Khởi tạo scene rect
        self._update_scene_rect()

    # ── Public API ──────────────────────────────────────────────

    @property
    def model(self) -> TimelineModel:
        return self._model

    @property
    def mapper(self) -> TimePixelMapper:
        return self._mapper

    @property
    def playhead(self) -> PlayheadItem:
        return self._playhead

    def request_snap(self, start_time: float, end_time: float,
                     exclude_id: str) -> Optional[SnapResult]:
        """Được gọi bởi ClipItem.itemChange() để tìm snap point."""
        result = self._snap.find_snap_for_edge(
            start_time, end_time, self._model, exclude_id
        )
        if result:
            self._snap_indicator.show_at(result.indicator_x,
                                          self._total_tracks_height() + 100)
        else:
            self._snap_indicator.hide_indicator()
        return result

    def show_drop_placeholder(self, scene_x: float, scene_y: float):
        index = self._model.track_index_at_y(
            scene_y, self.RULER_HEIGHT, self.TRACK_TOP_PADDING)
        if 0 <= index < len(self._model.tracks):
            top = self.RULER_HEIGHT + self.TRACK_TOP_PADDING + sum(
                track.height + self.TRACK_GAP
                for track in self._model.tracks[:index])
            height = self._model.tracks[index].height
        else:
            height = 54.0
            top = self.RULER_HEIGHT + self.TRACK_TOP_PADDING - height
        self._drop_placeholder.setLine(scene_x, top, scene_x, top + height)
        self._drop_placeholder.show()

    def hide_drop_placeholder(self):
        self._drop_placeholder.hide()

    # ── Background Drawing (Ruler + Grid) ───────────────────────

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Vẽ ruler marks và grid lines — được cache bởi CacheBackground."""
        super().drawBackground(painter, rect)

        # Chỉ vẽ vùng visible
        left = rect.left()
        right = rect.right()

        # ── Ruler nền ──
        ruler_rect = QRectF(left, 0, right - left, self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#0D0E14"))

        # Đường kẻ dưới ruler
        painter.setPen(QPen(QColor("#1C1E27"), 1))
        painter.drawLine(int(left), int(self.RULER_HEIGHT),
                         int(right), int(self.RULER_HEIGHT))

        # ── Ruler marks ──
        step, major_step, major_multiple = self._mapper.ruler_intervals()

        # Use integer tick indices. Repeated float addition (t += step) makes
        # fractional/millisecond ticks drift away from clips and playhead.
        visible_start = max(0.0, self._mapper.pixel_to_time(left))
        visible_end = max(visible_start, self._mapper.pixel_to_time(right))
        first_tick = max(0, int(math.floor(visible_start / step)))
        last_tick = int(math.ceil(visible_end / step))

        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        for tick_index in range(first_tick, last_tick + 1):
            t = tick_index * step
            x = self._mapper.time_to_pixel(t)

            # Vạch chính (major) vs vạch phụ (minor)
            is_major = tick_index % major_multiple == 0
            h = 14 if is_major else 7
            color = QColor("#3A3D4E") if is_major else QColor("#22242E")

            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x), int(self.RULER_HEIGHT - h),
                             int(x), int(self.RULER_HEIGHT))

            # Label cho vạch chính
            if is_major:
                painter.setPen(QColor("#6E7180"))
                label = self._format_ruler_time(t, major_step)
                painter.drawText(int(x + 3), 13, label)

            # Grid dọc nhẹ xuống vùng tracks
            if is_major:
                pen = QPen(QColor(30, 32, 40, 60), 1, Qt.DotLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                tracks_h = self._total_tracks_height()
                painter.drawLine(int(x), int(self.RULER_HEIGHT),
                                 int(x), int(self.RULER_HEIGHT + tracks_h))


    @staticmethod
    def _format_ruler_time(seconds: float, major_step: float) -> str:
        """Readable timecode whose precision follows the current zoom."""
        seconds = max(0.0, seconds)
        minutes = int(seconds // 60)
        remainder = seconds - minutes * 60
        if major_step < 0.1:
            return f"{minutes:02d}:{remainder:06.3f}"
        if major_step < 1.0:
            return f"{minutes:02d}:{remainder:04.1f}"
        return f"{minutes:02d}:{int(round(remainder)):02d}"

    # ── Model Event Handlers ────────────────────────────────────

    def _on_track_added(self, track: TrackModel):
        """Tạo TrackLaneItem cho track mới."""
        lane_index = self._model.tracks.index(track)
        scene_w = self._mapper.scene_width(self._model.duration)

        lane = TrackLaneItem(track, self._mapper, lane_index, scene_w)
        # Dịch Y xuống dưới ruler
        lane.setPos(0, self.RULER_HEIGHT)
        self.addItem(lane)
        self._track_lanes[track.track_id] = lane

        self._relayout_tracks()
        self._playhead.update_height(self._total_scene_height())

    def _on_track_removed(self, track_id: str):
        """Xóa TrackLaneItem."""
        lane = self._track_lanes.pop(track_id, None)
        if lane:
            self.removeItem(lane)
        self._relayout_tracks()
        self._update_scene_rect()

    def _on_clip_added(self, clip: ClipModel):
        """Tạo ClipItem cho clip mới."""
        lane = self._track_lanes.get(clip.track_id)
        if not lane:
            return

        clip_item = ClipItem(
            clip, self._mapper,
            track_y=lane.track_y,
            track_height=lane.track_height
        )
        # Dịch Y xuống dưới ruler (giống lane)
        clip_item.setPos(0, self.RULER_HEIGHT)
        self.addItem(clip_item)
        self._clip_items[clip.clip_id] = clip_item

    def _on_clip_removed(self, clip_id: str):
        """Xóa ClipItem."""
        item = self._clip_items.pop(clip_id, None)
        if item:
            item.shutdown_extraction()
            self.removeItem(item)

    def shutdown_clip_workers(self):
        """Dừng mọi luồng trích xuất còn sống — gọi trước khi cửa sổ đóng.

        Đóng app lúc dải hình clip vẫn đang giải mã là một abort không traceback:
        do 23/10/2026, `--project-report` mo du an that cua nguoi dung (hai clip
        AV1 3830x2160) ghi xong payload rồi chết ở 0xC0000409, faulthandler bắt
        được HAI thread ClipItem còn ở `MediaExtractionWorker.run()` qua
        `cv2.VideoCapture.read()` trong khi main thread đang `processEvents`
        (`docs/verification-gates.md`, muc "Dong cua so"; phan chung va fixture
        4K tu sinh nam trong `scratch/teardown_workers_counterfactual.py`).
        `close()` trên MainWindow không gửi close event xuống con, nên phép dựng
        phải nằm ở cửa sổ bị đóng thật — `MainController.closeEvent`.
        """
        for item in list(self._clip_items.values()):
            item.shutdown_extraction()

    def _on_clip_moved(self, clip_id: str, new_start: float):
        """Cập nhật vị trí ClipItem sau khi model thay đổi."""
        item = self._clip_items.get(clip_id)
        if item:
            item.update_from_model()
        self._snap_indicator.hide_indicator()

    def _on_clip_resized(self, clip_id: str, new_duration: float):
        """Cập nhật kích thước ClipItem sau khi model thay đổi."""
        item = self._clip_items.get(clip_id)
        if item:
            item.update_from_model()

    def _on_clip_updated(self, clip_id: str):
        """Cập nhật ClipItem khi model đổi thuộc tính không làm đổi hình học.

        Transition là trường hợp chính: ClipItem vẽ lại dải đánh dấu trong
        update_from_model(), nên set_transition() phải tới được đây.
        """
        item = self._clip_items.get(clip_id)
        if item:
            item.update_from_model()
            self.invalidate(item.sceneBoundingRect(), QGraphicsScene.ItemLayer)

    def _on_playhead_changed(self, t: float):
        """Cập nhật vị trí PlayheadItem."""
        self._playhead.set_time(t)

    def _on_duration_changed(self, d: float):
        """Cập nhật chiều rộng scene."""
        self._update_scene_rect()
        self._relayout_tracks()

    def _on_zoom_changed(self, px_per_sec: float):
        """Cập nhật tất cả items khi zoom thay đổi."""
        self._update_scene_rect()
        self._relayout_tracks()
        # Cập nhật tất cả clip items
        for item in self._clip_items.values():
            item.update_from_model()
        # Cập nhật playhead
        self._playhead.set_time(self._model.playhead)
        self.invalidate(self.sceneRect(), QGraphicsScene.BackgroundLayer)

    # ── Internal Helpers ────────────────────────────────────────

    def _total_tracks_height(self) -> float:
        """Tổng chiều cao tất cả track lanes."""
        return timeline_tracks_height(self._model.tracks,
                                      self.TRACK_TOP_PADDING)

    def _total_scene_height(self) -> float:
        return timeline_scene_height(self._model.tracks,
                                     self.TRACK_TOP_PADDING)

    def _update_scene_rect(self):
        """Cập nhật kích thước scene."""
        w = self._mapper.scene_width(self._model.duration)
        h = self._total_scene_height()
        self.setSceneRect(0, 0, w, h)

    def _relayout_tracks(self):
        """Sắp xếp lại tất cả track lanes và clip items."""
        scene_w = self._mapper.scene_width(self._model.duration)

        y = self.TRACK_TOP_PADDING
        for i, track in enumerate(self._model.tracks):
            lane = self._track_lanes.get(track.track_id)
            if lane:
                lane.update_geometry(i, scene_w, y)

                # Cập nhật clip items trên track này
                for clip in track.clips:
                    clip_item = self._clip_items.get(clip.clip_id)
                    if clip_item:
                        clip_item.set_track_position(lane.track_y,
                                                      lane.track_height)
            y += track.height + self.TRACK_GAP

        self._playhead.update_height(self._total_scene_height())

    def _on_model_selection_changed(self, ids):
        """Soi selection cua model vao ClipItem — chieu con lai cua dong doi.

        Truoc day scene khong bao gio duoc model cho biet clip nao duoc chon,
        nen moi lan scene phat selectionChanged (hang doi, zero-timer) thi
        selectedItems() trong trang = [] va _on_scene_selection_changed()
        tu dong deselect_all(): clip vua nham mat bi bo chon ngay sau do, lam
        bien mat the thuoc tinh.
        """
        wanted = set(ids)
        for clip_id, item in self._clip_items.items():
            item.setSelected(clip_id in wanted)

    def _on_scene_selection_changed(self):
        """Đồng bộ hóa các clip được chọn từ QGraphicsScene sang TimelineModel."""
        selected_items = self.selectedItems()
        # Lọc các items là ClipItem
        selected_clips = [item.clip_model.clip_id for item in selected_items if isinstance(item, ClipItem)]
        
        # Chỉ cập nhật model nếu có sự thay đổi thực sự. So sánh khong thu tu:
        # selectedItems() tra theo thu tu scene, con model theo thu tu nham,
        # neu so bang != thi hai ben nhay duong doi mai khong dung.
        if set(selected_clips) != set(self._model.selected_clip_ids):
            if selected_clips:
                self._model.select_clips(selected_clips)
            else:
                self._model.deselect_all()

    # ── Action Handlers (từ ClipItem context menu / signals) ────

    def _handle_clip_move_finished(self, clip_id: str,
                                    old_start: float, new_start: float):
        """ClipItem đã kéo xong — phát cho panel để tạo UndoCommand."""
        self._snap_indicator.hide_indicator()

    def _handle_split(self, clip_id: str):
        """Yêu cầu cắt clip tại vị trí playhead."""
        pass  # TimelinePanel sẽ xử lý

    def _handle_duplicate(self, clip_id: str):
        """Yêu cầu nhân bản clip."""
        pass  # TimelinePanel sẽ xử lý

    def _handle_delete(self, clip_id: str):
        """Yêu cầu xóa clip."""
        pass  # TimelinePanel sẽ xử lý

    # ── Drop Handling ───────────────────────────────────────────

    def dragEnterEvent(self, event):
        pass  # Handled by TimelineView

    def dragMoveEvent(self, event):
        pass  # Handled by TimelineView

    def dropEvent(self, event):
        pass  # Handled by TimelineView

    # ── Mouse Press on empty area → move playhead ───────────────

    def mousePressEvent(self, event):
        # Nếu click vào vùng ruler (trên cùng) → di chuyển playhead
        if event.scenePos().y() <= self.RULER_HEIGHT:
            t = self._mapper.pixel_to_time(event.scenePos().x())
            t = max(0.0, min(t, self._model.duration))
            self._model.playhead = t
            self.playhead_moved.emit(t)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if event.scenePos().y() <= self.RULER_HEIGHT + 5:
                t = self._mapper.pixel_to_time(event.scenePos().x())
                t = max(0.0, min(t, self._model.duration))
                self._model.playhead = t
                self.playhead_moved.emit(t)
                event.accept()
                return
        super().mouseMoveEvent(event)
