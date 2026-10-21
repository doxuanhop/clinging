"""
ui/timeline_panel.py
DYNAMIC TIMELINE v2: QGraphicsScene-based engine.

Thay thế hoàn toàn phiên bản v1 (QVBoxLayout + DropZone).
Tích hợp:
    - TimelineScene + TimelineView (Render Pipeline)
    - TrackHeaderScene (Fixed Track Headers)
    - TimelineModel + TimePixelMapper (Core Engine)
    - SnapEngine + UndoStack (Interaction + Optimization)
    - TimelineHeader (giữ nguyên từ v1)
    - Scroll Synchronization (đồng bộ thanh cuộn dọc)

Dùng Font Awesome 6 Solid icons (prefix: fa6s).
"""

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSlider, QSizePolicy, QComboBox, QScrollBar,
    QGraphicsView
)

from widgets.common import IconButton, VSeparator, set_label_icon, _qta, icon_color
from theme import theme_manager

from core import external_tools
from core.timeline_model import (
    TimelineModel, TrackType,
    TIMELINE_RULER_HEIGHT, TIMELINE_TRACK_TOP_PADDING, TIMELINE_TRACK_GAP,
)
from core.time_mapper import TimePixelMapper
from core.snap_engine import SnapEngine
from core.commands import (
    UndoStack, MoveClipCommand, ResizeClipCommand,
    AddClipCommand, RemoveClipCommand, SplitClipCommand, DuplicateClipCommand,
    DetachAudioCommand, PasteClipsCommand
)
from core.clip_clipboard import ClipClipboard

from ui.graphics.timeline_scene import TimelineScene
from ui.graphics.timeline_view import TimelineView
from ui.graphics.track_header_scene import TrackHeaderScene
from ui.custom_dialog import CustomDialog


# ── Loại media → TrackType mapping ─────────────────────────────

MEDIA_TO_TRACK = {
    "video":   TrackType.VIDEO,
    "audio":   TrackType.AUDIO,
    "image":   TrackType.IMAGE,
    "text":    TrackType.TEXT,
    "sticker": TrackType.OVERLAY,
    "effect":  TrackType.EFFECT,
}

# ── Nhận diện định dạng tệp từ đuôi file ────────────────────────
EXTENSION_KIND_MAP = {
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".wmv": "video", ".flv": "video", ".webm": "video", ".m4v": "video",
    ".mp3": "audio", ".wav": "audio", ".aac": "audio", ".flac": "audio",
    ".ogg": "audio", ".wma": "audio", ".m4a": "audio",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".bmp": "image", ".gif": "image", ".svg": "image", ".tiff": "image",
    ".psd": "image", ".ico": "image",
    ".txt": "text", ".srt": "text", ".ass": "text",
}


def identify_media_kind(file_path: str) -> str:
    """
    Tự động nhận diện loại media từ đuôi tệp tin.
    Trả về: 'video', 'audio', 'image', 'text', hoặc 'video' (mặc định).
    """
    import os
    ext = os.path.splitext(file_path)[1].lower()
    return EXTENSION_KIND_MAP.get(ext, "video")


class TimelineHeader(QWidget):
    """Header bar: title, undo/redo, edit tools, track manager, time counter, zoom."""

    undoRequested = Signal()
    redoRequested = Signal()
    splitRequested = Signal()
    deleteRequested = Signal()
    duplicateRequested = Signal()
    themeToggleRequested = Signal()
    recapOverlayRequested = Signal()
    fitModeChanged = Signal(str)  # "fit" hoặc "fill"
    focusModeToggled = Signal(bool)  # True = timeline chiếm gần hết cửa sổ
    mutedToggled = Signal(bool)   # True = câm ở ô nghe thử

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 6)
        layout.setSpacing(8)

        # ── Undo / Redo ──
        self.btn_undo = IconButton("", "Hoàn tác (Ctrl+Z)",
                                   object_name="TimelineIconBtn", size=28,
                                   icon_name="fa6s.rotate-left")
        self.btn_redo = IconButton("", "Làm lại (Ctrl+Y)",
                                   object_name="TimelineIconBtn", size=28,
                                   icon_name="fa6s.rotate-right")
        self.btn_undo.clicked.connect(self.undoRequested.emit)
        self.btn_redo.clicked.connect(self.redoRequested.emit)
        layout.addWidget(self.btn_undo)
        layout.addWidget(self.btn_redo)

        layout.addWidget(VSeparator(height=18))

        # ── Edit tools ──
        self.btn_split = IconButton("", "Cắt tại Playhead (S)",
                                    object_name="TimelineIconBtn", size=28,
                                    icon_name="fa6s.scissors")
        self.btn_delete = IconButton("", "Xóa (Delete)",
                                     object_name="TimelineIconBtn", size=28,
                                     icon_name="fa6s.trash")
        self.btn_duplicate = IconButton("", "Nhân bản (Ctrl+D)",
                                        object_name="TimelineIconBtn", size=28,
                                        icon_name="fa6s.clone")

        self.btn_split.clicked.connect(self.splitRequested.emit)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        self.btn_duplicate.clicked.connect(self.duplicateRequested.emit)

        layout.addWidget(self.btn_split)
        layout.addWidget(self.btn_delete)
        layout.addWidget(self.btn_duplicate)

        # ── Vùng Playback Ngang (Playback Controls) ──
        layout.addStretch(1)
        self.btn_prev = IconButton("", "Khung trước", object_name="TimelineIconBtn", size=28,
                                   icon_name="fa6s.backward")
        self.btn_play = IconButton("", "Phát / Tạm dừng", object_name="PlayBtnMain", size=30,
                                   icon_name="fa6s.play")
        self.btn_play.setCheckable(True)
        self.btn_next = IconButton("", "Khung kế tiếp", object_name="TimelineIconBtn", size=28,
                                   icon_name="fa6s.forward")
        # Tắt tiếng CHỈ ảnh hưởng ô nghe thử — cùng quyết định với nút loa trên
        # từng track: project data nằm ở track.is_muted và volume của clip.
        self.btn_mute = IconButton("", "Tắt tiếng xem trước (M)", object_name="TimelineIconBtn",
                                   size=28, icon_name="fa6s.volume-high")
        self.btn_mute.setCheckable(True)
        self.btn_mute.clicked.connect(self._on_mute_clicked)

        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.btn_mute)
        layout.addStretch(1)

        # ── Bộ Chọn Tỉ Lệ Khung Hình Aspect Ratio ──
        layout.addSpacing(14)
        lbl_ratio = QLabel("Tỉ lệ:")
        lbl_ratio.setStyleSheet("color: #888888; font-size: 11px;")
        
        self.combo_aspect_ratio = QComboBox()
        self.combo_aspect_ratio.addItems([
            "16:9 - Ngang chuẩn",
            "19:6 - Siêu rộng",
            "9:16 - Đứng Shorts/Tiktok",
            "1:1 - Vuông",
            "4:3 - Cổ điển"
        ])
        # Để Qt tự tính bề rộng theo item dài nhất: setFixedWidth(120) từng
        # khiến "16:9 - Ngang chuẩn" và "9:16 - Đứng Shorts/Tiktok" bị cắt chữ.
        self.combo_aspect_ratio.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_aspect_ratio.setMinimumWidth(120)
        self.combo_aspect_ratio.setStyleSheet("""
            QComboBox { 
                background-color: #252836; 
                color: #FFFFFF; 
                border: 1px solid #333340; 
                border-radius: 4px; 
                padding: 2px 6px; 
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
        """)
        layout.addWidget(lbl_ratio)
        layout.addWidget(self.combo_aspect_ratio)

        # ── Fit / Fill Mode Buttons ──
        layout.addSpacing(8)
        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setCheckable(True)
        self.btn_fit.setChecked(True)
        self.btn_fit.setFixedHeight(26)
        self.btn_fit.setFixedWidth(40)
        self.btn_fit.setCursor(Qt.PointingHandCursor)
        self.btn_fit.setObjectName("FitFillTimelineBtn")
        self.btn_fit.setStyleSheet("""
            QPushButton#FitFillTimelineBtn {
                background-color: #252836;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#FitFillTimelineBtn:hover {
                background-color: #3A3D4E;
                color: #FFFFFF;
            }
            QPushButton#FitFillTimelineBtn:checked {
                background-color: #2C6E64;
                color: #FFFFFF;
                border-color: #40E0D0;
            }
        """)
        self.btn_fit.clicked.connect(lambda: self.fitModeChanged.emit("fit"))

        self.btn_fill = QPushButton("Fill")
        self.btn_fill.setCheckable(True)
        self.btn_fill.setFixedHeight(26)
        self.btn_fill.setFixedWidth(40)
        self.btn_fill.setCursor(Qt.PointingHandCursor)
        self.btn_fill.setObjectName("FitFillTimelineBtn")
        self.btn_fill.setStyleSheet("""
            QPushButton#FitFillTimelineBtn {
                background-color: #252836;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#FitFillTimelineBtn:hover {
                background-color: #3A3D4E;
                color: #FFFFFF;
            }
            QPushButton#FitFillTimelineBtn:checked {
                background-color: #2C6E64;
                color: #FFFFFF;
                border-color: #40E0D0;
            }
        """)
        self.btn_fill.clicked.connect(lambda: self.fitModeChanged.emit("fill"))

        layout.addWidget(self.btn_fit)
        layout.addWidget(self.btn_fill)

        # Track do app tự tạo khi thả tài nguyên — không có hộp thoại quản lý
        # track nào đứng sau, nên nút "Quản lý track" đã bị bỏ thay vì nối vào
        # một xử lý bịa ra.
        layout.addSpacing(10)

        layout.addStretch(1)

        # ── Time counter ──
        self.time_current = QLabel("00:00.0")
        self.time_current.setObjectName("TimeCounter")
        slash = QLabel(" / ")
        slash.setObjectName("TimeCounterMuted")
        self.time_total = QLabel("00:30.0")
        self.time_total.setObjectName("TimeCounterMuted")
        layout.addWidget(self.time_current)
        layout.addWidget(slash)
        layout.addWidget(self.time_total)

        # ── Lớp phủ recap (cấu hình cả dự án, mở hộp thoại riêng) ──
        self.btn_recap = IconButton("", "Lớp phủ recap",
                                    object_name="TimelineIconBtn", size=28,
                                    icon_name="fa6s.crosshairs")
        self.btn_recap.clicked.connect(self.recapOverlayRequested.emit)
        layout.addWidget(self.btn_recap)

        # ── Theme Toggle Button ──
        layout.addSpacing(10)
        self.btn_theme = IconButton("", "Chuyển Sáng / Tối",
                                    object_name="TimelineIconBtn", size=28,
                                    icon_name="fa6s.circle-half-stroke")
        self.btn_theme.clicked.connect(self.themeToggleRequested.emit)
        layout.addWidget(self.btn_theme)

        # ── Zoom ──
        layout.addSpacing(14)
        zoom_out = IconButton("", "Thu nhỏ timeline",
                              object_name="TimelineIconBtn", size=28,
                              icon_name="fa6s.magnifying-glass-minus")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.setRange(5, 500)
        self.zoom_slider.setValue(48)
        zoom_in = IconButton("", "Phóng to timeline",
                             object_name="TimelineIconBtn", size=28,
                             icon_name="fa6s.magnifying-glass-plus")
        fullscreen = IconButton("", "Toàn màn hình timeline",
                                object_name="TimelineIconBtn", size=28,
                                icon_name="fa6s.expand")
        fullscreen.setCheckable(True)
        fullscreen.setToolTip("Thu vùng xem / trả lại (toàn màn hình timeline)")
        self.btn_focus = fullscreen
        fullscreen.clicked.connect(self._on_focus_toggled)

        zoom_out.clicked.connect(lambda: self.zoom_slider.setValue(
            max(self.zoom_slider.minimum(), self.zoom_slider.value() - 10)))
        zoom_in.clicked.connect(lambda: self.zoom_slider.setValue(
            min(self.zoom_slider.maximum(), self.zoom_slider.value() + 10)))

        layout.addWidget(zoom_out)
        layout.addWidget(self.zoom_slider)
        layout.addWidget(zoom_in)
        layout.addWidget(fullscreen)

        # Center playback independently from the unequal tool groups.
        for button in (self.btn_prev, self.btn_play, self.btn_next,
                       self.btn_mute):
            layout.removeWidget(button)
        self._playback_center = QWidget(self)
        self._playback_center.setObjectName("TimelinePlaybackCenter")
        playback_layout = QHBoxLayout(self._playback_center)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(3)
        playback_layout.addWidget(self.btn_prev)
        playback_layout.addWidget(self.btn_play)
        playback_layout.addWidget(self.btn_next)
        playback_layout.addWidget(self.btn_mute)
        # Absolute positioning overlapped the ratio and track controls.
        playback_insert = layout.indexOf(self.btn_duplicate) + 2
        layout.insertWidget(playback_insert, self._playback_center)

    def _on_mute_clicked(self, checked):
        """Đổi cả hình lẫn tín hiệu: nút loa đứng nguyên hình khi đã câm là UI nói dối."""
        name = "fa6s.volume-xmark" if checked else "fa6s.volume-high"
        self.btn_mute.setIcon(_qta().icon(name, color=icon_color()))
        self.mutedToggled.emit(bool(checked))

    def _on_focus_toggled(self, checked):
        name = "fa6s.compress" if checked else "fa6s.expand"
        self.btn_focus.setIcon(_qta().icon(name, color=icon_color()))
        self.focusModeToggled.emit(bool(checked))


class TimelinePanel(QWidget):
    """
    Panel chính chứa header + QGraphicsScene timeline.

    Orchestrates:
        - TimelineModel (data)
        - TimePixelMapper (coordinates)
        - SnapEngine (magnet)
        - UndoStack (undo/redo)
        - TimelineScene + TimelineView (rendering)
    """

    # Signal cho main_window khi clip được thêm/chọn
    clipAdded = Signal(str)           # clip name
    clipSelected = Signal(str)        # clip name
    keyframeGraphRequested = Signal(str)   # clip_id muon mo do thi duong cong
    themeToggleRequested = Signal()
    coverRequested = Signal(object)   # Main Storyline video clip
    recapOverlayRequested = Signal()
    focusModeToggled = Signal(bool)  # nút toàn màn hình timeline

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TimelinePanel")
        # Min cu 330 px buoc timeline chiem hon mot phan ba cua so, mau thuan
        # bo cuc 70/30 ma main_window khai bao. Hang thua gio do thi cuon duoc
        # (xem _update_track_scroll_mode), khong bi cat lang.
        self.setMinimumHeight(240)

        # ── Core Engine ──
        self.model = TimelineModel()
        self.mapper = TimePixelMapper()
        self.snap = SnapEngine(self.mapper)
        self.undo_stack = UndoStack()
        # Clipboard clip trong RAM, sống đúng một phiên editor.
        self.clipboard = ClipClipboard()

        # ── Layout ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        self.header = TimelineHeader()
        outer.addWidget(self.header)

        # Banner
        # Giữ thuộc tính tương thích cho code cũ, nhưng không hiển thị banner.
        self.banner = QLabel()
        self.banner.hide()

        # ── Split View: Header (trái) + Timeline (phải) ──
        timeline_row = QHBoxLayout()
        timeline_row.setContentsMargins(0, 0, 0, 0)
        timeline_row.setSpacing(0)

        # 1) Fixed Track controls + Cover slot. Track Body scrolls separately.
        self.header_scene = TrackHeaderScene(self.model)
        self.header_view = QGraphicsView(self.header_scene)
        self.header_view.setObjectName("TrackHeaderView")
        header_width = int(self.header_scene.HEADER_WIDTH)
        self.header_view.setFixedWidth(header_width)
        self.header_view.setMinimumWidth(header_width)
        self.header_view.setMaximumWidth(header_width)
        self.header_view.setTransform(QTransform())
        self.header_view.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.header_view.setResizeAnchor(QGraphicsView.NoAnchor)
        self.header_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.header_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.header_view.setInteractive(True)
        self.header_view.setFrameShape(QFrame.NoFrame)
        self.header_view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.header_view.setViewportUpdateMode(
            QGraphicsView.FullViewportUpdate
        )
        self.header_view.setStyleSheet("""
            QGraphicsView {
                border: none;
                border-top: 1px solid #1C1E27;
                border-right: 1px solid #2A2D3A;
                background-color: #0D0E14;
            }
        """)

        # 2) Timeline Scene + View (bên phải — cuộn tự do)
        self.scene = TimelineScene(self.model, self.mapper, self.snap)
        self.scene.undo_stack = self.undo_stack
        self.view = TimelineView(self.scene, self.mapper)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        # Hai viewport phải cao bằng nhau và bắt đầu cùng một y. TimelineView
        # đã có border-top 1px nên header cũng phải có; thiếu nó là mọi hàng
        # lệch nhau 1px và range cuộn khác nhau ngay khi còn 1 track.
        self.header_view.setViewportMargins(0, 0, 0, 0)

        timeline_row.addWidget(self.header_view)
        timeline_row.addWidget(self.view, 1)
        outer.addLayout(timeline_row, 1)

        # ── Scroll Synchronization (LINH HỒN) ──
        self._syncing_scroll = False
        self._connect_scroll_sync()

        # ── Wire Events ──
        self._wire_header()
        self._wire_scene()
        self._wire_model()
        self._wire_header_scene()

        # Đặt horizontal scroll SAU khi layout hoàn tất (deferred)
        QTimer.singleShot(0, self._init_scroll_position)
        QTimer.singleShot(0, self._center_tracks_vertically)

        # Cài đặt có hiệu lực ngay khi panel vừa dựng xong, không chờ người
        # dùng mở hộp thoại Cài đặt lần đầu.
        from core import settings
        self.apply_settings(settings.values())

    # ── Event Wiring ────────────────────────────────────────────

    def _wire_header(self):
        """Kết nối header buttons → actions."""
        self.header.undoRequested.connect(self.undo_stack.undo)
        self.header.redoRequested.connect(self.undo_stack.redo)
        self.header.splitRequested.connect(self._on_split_selected)
        self.header.deleteRequested.connect(self._on_delete_selected)
        self.header.duplicateRequested.connect(self._on_duplicate_selected)
        self.header.themeToggleRequested.connect(self.themeToggleRequested.emit)
        self.header.recapOverlayRequested.connect(self.recapOverlayRequested.emit)
        self.header.focusModeToggled.connect(self.focusModeToggled.emit)

        # Zoom slider ↔ TimePixelMapper
        self.header.zoom_slider.valueChanged.connect(self._set_timeline_zoom)
        self.mapper.zoomChanged.connect(self._sync_zoom_slider)

        # Connect command state once. Keeping these in the zoom callback used
        # to add duplicate signal handlers on every slider step.
        self.undo_stack.stateChanged.connect(self._update_undo_buttons)
        self.undo_stack.undoTextChanged.connect(
            lambda t: self.header.btn_undo.setToolTip(t or "Hoàn tác"))
        self.undo_stack.redoTextChanged.connect(
            lambda t: self.header.btn_redo.setToolTip(t or "Làm lại"))

    def _sync_zoom_slider(self, px_per_sec):
        previous = self.header.zoom_slider.blockSignals(True)
        self.header.zoom_slider.setValue(int(round(px_per_sec)))
        self.header.zoom_slider.blockSignals(previous)

    def set_min_zoom_px_per_sec(self, px_per_sec):
        """Hạ trần thu nhỏ: mapper kẹp zoom hiện tại, slider bắt buộc khớp."""
        low = float(self.mapper.set_min_zoom(px_per_sec))
        slider = self.header.zoom_slider
        previous = slider.blockSignals(True)
        slider.setMinimum(int(low))
        slider.blockSignals(previous)
        self._sync_zoom_slider(self.mapper.px_per_sec)
        return low

    def apply_settings(self, values: dict):
        """Đẩy cài đặt đang chạy vào engine, slider zoom và lịch sử undo."""
        self.snap.enabled = bool(values["snapping_enabled"])
        self.snap.snap_to_playhead = bool(values["snap_playhead"])
        self.snap.snap_to_clip_edges = bool(values["snap_clip_edges"])
        self.snap.threshold_px = int(values["snap_threshold"])
        self.set_min_zoom_px_per_sec(int(values["min_zoom_px_per_sec"]))
        self.undo_stack.set_max_history(int(values["undo_steps"]))
        # Waveform/thumbnail đọc cài đặt ngay trong paint(), nên phải vẽ lại.
        self.scene.invalidate(self.scene.sceneRect())

    def _set_timeline_zoom(self, value):
        """Zoom Track Body while keeping the playhead anchored on screen."""
        # Track Header is a separate fixed view. Never apply the time scale to
        # it; reset defensively in case a platform gesture changed its matrix.
        self.header_view.setTransform(QTransform())
        old_x = self.mapper.time_to_pixel(self.model.playhead)
        old_scroll = self.view.horizontalScrollBar().value()
        self.mapper.set_zoom(float(value))
        new_x = self.mapper.time_to_pixel(self.model.playhead)
        target_scroll = old_scroll + int(round(new_x - old_x))
        # QGraphicsView refreshes the scroll range after the sceneRect change;
        # apply the anchor once that range is current.
        QTimer.singleShot(
            0,
            lambda target=target_scroll:
                self.view.horizontalScrollBar().setValue(target),
        )

    def _wire_scene(self):
        """Kết nối scene signals → panel handlers."""
        self.scene.playhead_moved.connect(self._on_playhead_moved)
        self.scene.resource_dropped.connect(self._on_resource_dropped)
        self.scene.clip_move_finished.connect(self._on_clip_move_finished)
        self.scene.clip_resized.connect(self._on_clip_resized)
        self.scene.split_requested.connect(self._on_split_clip)
        self.scene.duplicate_requested.connect(self._on_duplicate_clip)
        self.scene.delete_requested.connect(self._on_delete_clip)
        self.scene.graph_requested.connect(self.keyframeGraphRequested.emit)
        self.scene.audio_detach_requested.connect(self._on_detach_audio)

    def _wire_model(self):
        """Kết nối model signals → UI updates."""
        self.model.durationChanged.connect(self._update_total_time)
        self.model.clipAdded.connect(
            lambda c: self.clipAdded.emit(c.name)
        )
        self.model.selectionChanged.connect(self._on_selection_changed)
        self.model.trackAdded.connect(lambda _track: self._update_track_layout())
        self.model.trackRemoved.connect(lambda _track_id: self._update_track_layout())
        self.model.tracksReordered.connect(self._update_track_layout)
        self._update_track_scroll_mode()

    def _update_track_scroll_mode(self):
        """Cuộn khi hàng không vừa viewport, không chỉ khi đếm được 4 track.

        Bo cuc 70/30 cua main_window cho timeline ~240 px, ma 3 hang 60 px da
        can ~236 px chua ruler + padding. Neu chi dem track thi hang thu 3 bi
        cat va khong cuon duoc de tim lai.
        """
        needed = TIMELINE_RULER_HEIGHT + 20.0 + sum(
            track.height + TIMELINE_TRACK_GAP
            for track in self.model.tracks[:3])
        overflow = needed > float(self.view.viewport().height())
        self.view.set_vertical_scroll_enabled(
            len(self.model.tracks) >= 4 or overflow)

    def _update_track_layout(self):
        self._update_track_scroll_mode()
        QTimer.singleShot(0, self._center_tracks_vertically)
        QTimer.singleShot(1, self._scroll_to_main_storyline)

    def _center_tracks_vertically(self):
        """Keep Header and Body centered with one shared dynamic top offset."""
        if not hasattr(self, "view") or not hasattr(self, "header_scene"):
            return
        viewport_h = max(1.0, float(self.view.viewport().height()))
        # Three compact rows form the centered visible group. Additional rows
        # extend the scene and therefore create a real (hidden) scroll range.
        centered_h = sum(
            track.height + TIMELINE_TRACK_GAP
            for track in self.model.tracks[:3]
        )
        usable_h = max(0.0, viewport_h - TIMELINE_RULER_HEIGHT)
        top_padding = max(20.0, (usable_h - centered_h) / 2.0)
        self.scene.TRACK_TOP_PADDING = top_padding
        self.header_scene.TRACK_TOP_PADDING = top_padding
        self.scene._relayout_tracks()
        self.scene._update_scene_rect()
        self.header_scene._relayout()

    def _scroll_to_main_storyline(self):
        """On overflow keep the lower Main Storyline visible by default."""
        bar = self.view.verticalScrollBar()
        if bar.maximum() > 0:
            bar.setValue(bar.maximum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_track_scroll_mode)
        QTimer.singleShot(0, self._center_tracks_vertically)

    def _connect_scroll_sync(self):
        """
        Kết nối thanh cuộn dọc giữa Header View và Timeline View.

        Khi người dùng cuộn Timeline → Header cuộn theo.
        Khi người dùng cuộn Header → Timeline cuộn theo.
        Dùng cờ _syncing_scroll để tránh vòng lặp vô hạn.
        """
        scroll_timeline = self.view.verticalScrollBar()
        scroll_header = self.header_view.verticalScrollBar()

        def _on_timeline_scroll(value):
            if self._syncing_scroll:
                return
            self._syncing_scroll = True
            scroll_header.setValue(value)
            self._syncing_scroll = False

        def _on_header_scroll(value):
            if self._syncing_scroll:
                return
            self._syncing_scroll = True
            scroll_timeline.setValue(value)
            self._syncing_scroll = False

        scroll_timeline.valueChanged.connect(_on_timeline_scroll)
        scroll_header.valueChanged.connect(_on_header_scroll)

    def _init_scroll_position(self):
        """Đặt vị trí scroll ban đầu sau khi layout hoàn tất."""
        self.view.horizontalScrollBar().setValue(0)

    def _wire_header_scene(self):
        """Kết nối TrackHeaderScene signals → clip item updates."""
        self.header_scene.track_state_changed.connect(
            self._on_track_state_changed
        )
        self.header_scene.cover_requested.connect(self._on_cover_requested)

    def _on_cover_requested(self, track_model):
        """Open the cover picker for the video under the playhead."""
        if (not track_model.is_main_track or
                track_model.track_type != TrackType.VIDEO):
            return
        videos = [clip for clip in track_model.clips
                  if clip.media_type == "video" and clip.source_path]
        if not videos:
            CustomDialog.information(
                self.window(), "Ảnh bìa",
                "Hãy thêm video vào Main Storyline trước khi tạo ảnh bìa."
            )
            return
        clip = next((clip for clip in videos
                     if clip.start_time <= self.model.playhead < clip.end_time),
                    videos[0])
        self.coverRequested.emit(clip)

    def _on_track_state_changed(self, track_model, action_type, is_active):
        """
        Xử lý khi người dùng bấm nút Lock/Visible/Mute trên Track Header.

        ``is_active`` là trạng thái MỚI của chính cờ trên track_model.
        """
        from PySide6.QtWidgets import QGraphicsItem

        clips_on_track = track_model.clips

        if action_type == "lock":
            for clip in clips_on_track:
                item = self.scene._clip_items.get(clip.clip_id)
                if item:
                    item.setFlag(
                        QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                        not is_active
                    )
                    item.setFlag(
                        QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                        not is_active
                    )
                    item.setOpacity(0.5 if is_active else 1.0)

        elif action_type in ("visible", "mute"):
            # Hai cái cờ từng ghi ở đây — item.is_video_hidden và
            # item.is_audio_muted — không có chỗ nào đọc: canvas nghe
            # track.is_visible, loa nghe track.is_muted. Việc thật của nhánh này
            # chỉ là báo các clip vẽ lại theo hàng, vì cây sóng giờ đổi màu khi
            # hàng im lặng, và xin canvas dựng lại frame hiện tại.
            for clip in clips_on_track:
                item = self.scene._clip_items.get(clip.clip_id)
                if item is not None:
                    item.update()
            self.scene.invalidate(self.scene.sceneRect())
            window = self.window()
            if hasattr(window, "_sync_canvas"):
                window._sync_canvas()

    # ── Playhead ────────────────────────────────────────────────

    def _on_playhead_moved(self, t: float):
        """Cập nhật time counter khi playhead di chuyển."""
        self.model.playhead = t
        mins, secs = divmod(t, 60)
        self.header.time_current.setText(f"{int(mins):02d}:{secs:04.1f}")

    # ── Resource Drop ───────────────────────────────────────────

    def _on_resource_dropped(self, name: str, kind: str, drop_time: float, drop_y: float = -1.0):
        """Khi resource kéo từ Library thả vào Timeline."""
        import os
        
        # Nhận diện loại media từ đuôi file
        detected_kind = identify_media_kind(name)
        if detected_kind != "video" or kind == "video":
            final_kind = detected_kind if detected_kind != "video" else kind
        else:
            final_kind = kind

        track_type = MEDIA_TO_TRACK.get(final_kind, TrackType.VIDEO)
        
        # Lấy tên file (không có đường dẫn)
        display_name = os.path.basename(name)
        
        # Lấy thời lượng thực tế từ file
        duration = self._get_media_duration(name, final_kind)
        
        # Xác định track dựa trên toạ độ Y
        ruler_height = TIMELINE_RULER_HEIGHT
        
        target_track = None
        
        # Nếu có thông số Y hợp lệ
        if drop_y >= ruler_height:
            track_index = self.model.track_index_at_y(
                drop_y, ruler_height, self.scene.TRACK_TOP_PADDING)
            
            # Nếu người dùng thả vào một track cụ thể đã tồn tại
            if 0 <= track_index < len(self.model.tracks):
                target_track = self.model.tracks[track_index]
                # The narrow gray activation strip at the top of Main Storyline
                # behaves like CapCut's "new overlay track" drop target.
                lane_top = ruler_height + self.scene.TRACK_TOP_PADDING + sum(
                    track.height + TIMELINE_TRACK_GAP
                    for track in self.model.tracks[:track_index]
                )
                local_y = drop_y - lane_top
                if (target_track.is_main_track and final_kind in ("video", "image")
                        and local_y < min(18.0, target_track.height * 0.3)):
                    target_track = self.model.add_track(track_type)
                from core.timeline_model import track_accepts_media
                if not track_accepts_media(target_track.track_type, final_kind):
                    target_track = self.model.add_track(track_type)
            else:
                # Thả xuống vùng trống bên dưới các track -> tạo track mới tự động
                target_track = self.model.add_track(track_type)
        else:
            # Drop ngoài scene hoặc không có toạ độ Y -> tìm hoặc tạo track mặc định
            target_track = self.model.find_or_create_track(track_type)

        if not target_track:
            target_track = self.model.find_or_create_track(track_type)

        # Tạo clip qua undo stack
        cmd = AddClipCommand(
            self.model, target_track.track_id, name,
            media_type=final_kind,
            start_time=drop_time,
            duration=duration,
            name=display_name
        )
        self.undo_stack.push(cmd)

        # Ẩn banner sau khi thêm clip đầu tiên
        self.banner.setVisible(False)
        return self.model.get_clip(cmd._clip_id)

    def add_resource(self, name: str, kind: str = "video"):
        """API ngoài: thêm resource vào timeline (từ Library double-click, etc.)."""
        detected_kind = identify_media_kind(name)
        final_kind = detected_kind if detected_kind != "video" else kind
        # name đã là full path từ library, truyền đúng cho drop handler
        self._on_resource_dropped(name, final_kind, self.model.playhead, -1.0)

    # ── Clip Move / Resize ──────────────────────────────────────

    def _on_clip_move_finished(self, clip_id: str,
                                old_start: float, new_start: float):
        """Clip đã kéo xong — push undo command."""
        if abs(old_start - new_start) < 0.01:
            return
        clip = self.model.get_clip(clip_id)
        if clip:
            # Item đã preview vị trí khi kéo; trả về state cũ rồi thực thi command.
            clip.start_time = old_start
        cmd = MoveClipCommand(self.model, clip_id, old_start, new_start)
        self.undo_stack.push(cmd)

    def _on_clip_resized(self, clip_id: str, old_start: float,
                          old_dur: float, new_start: float, new_dur: float,
                          old_in: float, new_in: float):
        """Clip đã resize xong — push undo command."""
        clip, track = self.model._find_clip(clip_id)
        if clip and track and track.is_main_track:
            # The graphics item previews only the dragged clip.  Commit the
            # magnetic ripple here so every later item follows its new edge.
            self.model.recalculate_main_storyline(track)
            new_start = clip.start_time
        else:
            self.model.recalculate_project_duration()
        cmd = ResizeClipCommand(
            self.model, clip_id,
            old_dur, new_dur, old_start, new_start,
            old_in=old_in, new_in=new_in,
        )
        self.undo_stack._undo_stack.append(cmd)
        self.undo_stack._redo_stack.clear()
        self.undo_stack._emit_state()

    def _get_media_duration(self, file_path: str, media_type: str) -> float:
        """Lấy thời lượng thực tế của file media (nhanh, không load toàn bộ file)."""
        import os
        from core.media_extractor import get_media_duration
        if os.path.exists(file_path):
            duration = get_media_duration(file_path, media_type)
            if duration > 0:
                return duration
        import subprocess
        import json as _json
        from core.media_locator import locate

        actual_path = locate(file_path) or file_path

        if not os.path.exists(actual_path):
            return 5.0

        try:
            if media_type == "video":
                import cv2
                import os
                old_stderr = os.dup(2)
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, 2)
                try:
                    cap = cv2.VideoCapture(actual_path)
                finally:
                    os.dup2(old_stderr, 2)
                    os.close(old_stderr)
                    os.close(devnull)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    cap.release()
                    if fps > 0:
                        return frame_count / fps
                return 10.0

            elif media_type == "image":
                return 5.0

            elif media_type == "audio":
                # Dùng ffprobe để lấy duration nhanh (không load toàn bộ file)
                ffprobe = external_tools.find("ffprobe")
                if ffprobe:
                    try:
                        result = subprocess.run(
                            [ffprobe, "-v", "quiet", "-print_format", "json",
                             "-show_format", actual_path],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=5
                        )
                        if result.returncode == 0:
                            info = _json.loads(result.stdout)
                            duration = float(info.get("format", {}).get("duration", 0))
                            if duration > 0:
                                return duration
                    except (subprocess.TimeoutExpired, FileNotFoundError, _json.JSONDecodeError):
                        pass

                # Fallback: dùng pydub nhưng chỉ đọc 1 giây đầu để ước tính
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(actual_path, duration=1)
                    # Ước tính duration từ file size ratio
                    file_size = os.path.getsize(actual_path)
                    # Giả sử bitrate ~128kbps = 16000 bytes/sec
                    estimated_duration = file_size / 16000
                    return max(1.0, min(estimated_duration, 600.0))
                except Exception:
                    pass

        except Exception:
            pass

        return 5.0

    # ── Edit Actions ────────────────────────────────────────────

    def _on_split_selected(self):
        """Cắt clip đang chọn tại vị trí playhead."""
        for clip_id in self.model.selected_clip_ids:
            self._on_split_clip(clip_id)

    def _on_split_clip(self, clip_id: str):
        """Cắt clip tại playhead."""
        cmd = SplitClipCommand(self.model, clip_id, self.model.playhead)
        self.undo_stack.push(cmd)

    def _on_delete_selected(self):
        """Xóa tất cả clip đang chọn."""
        for clip_id in list(self.model.selected_clip_ids):
            self._on_delete_clip(clip_id)

    def _on_delete_clip(self, clip_id: str):
        clip = self.model.get_clip(clip_id)
        track = self.model.get_track(clip.track_id) if clip else None
        if (clip and track and track.is_main_track and
                clip.media_type == "video"):
            confirmed = CustomDialog.question(
                self.window(), "Xóa video gốc",
                "Bạn có muốn xóa video gốc khỏi Main Storyline không?\n\n"
                "Các clip trên trục chính sẽ tự động dồn lại. Tệp nguồn "
                "trên máy tính sẽ không bị xóa.",
                buttons=[("Xóa video gốc", "danger"), ("Hủy", "reject")],
            )
            if not confirmed:
                return
        """Xóa clip."""
        cmd = RemoveClipCommand(self.model, clip_id)
        self.undo_stack.push(cmd)

    def _on_duplicate_selected(self):
        """Nhân bản clip đang chọn."""
        for clip_id in list(self.model.selected_clip_ids):
            self._on_duplicate_clip(clip_id)

    def _on_duplicate_clip(self, clip_id: str):
        """Nhân bản clip."""
        self.undo_stack.push(DuplicateClipCommand(self.model, clip_id))

    def _on_detach_audio(self, clip_id: str):
        """Tách tiếng clip video thành một clip audio ngay dưới.

        Một lệnh, một bước Ctrl+Z: thêm hàng tiếng và tắt tiếng video là hai nửa
        của cùng một thao tác, undo rời rạc sẽ để lại hàng tiếng câm.
        """
        self.undo_stack.push(DetachAudioCommand(self.model, clip_id))

    # ── Clipboard (Ctrl+C / Ctrl+V) ─────────────────────────────

    def _on_copy_selected(self):
        """Copy các clip đang chọn vào clipboard trong bộ nhớ.

        Trả về số clip đã copy để caller bật thông báo; selection rỗng thì
        clipboard giữ nguyên (không xóa nội dung lần copy trước).
        """
        ids = list(self.model.selected_clip_ids)
        if not ids:
            return 0
        return self.clipboard.copy_from(self.model, ids)

    def _on_paste_selected(self):
        """Dán cả nhóm clipboard tại playhead — một bước undo."""
        if self.clipboard.is_empty:
            return 0
        self.undo_stack.push(
            PasteClipsCommand(self.model, self.clipboard.entries(),
                              self.model.playhead))
        return self.clipboard.entry_count

    # ── Selection ───────────────────────────────────────────────

    def _on_selection_changed(self, ids: list):
        """Cập nhật UI khi selection thay đổi."""
        if ids:
            clip = self.model.get_clip(ids[0])
            if clip:
                self.clipSelected.emit(clip.name)

    # ── UI Helpers ──────────────────────────────────────────────

    def _update_total_time(self, d: float):
        mins, secs = divmod(d, 60)
        self.header.time_total.setText(f"{int(mins):02d}:{secs:04.1f}")

    def _update_undo_buttons(self):
        self.header.btn_undo.setEnabled(self.undo_stack.can_undo)
        self.header.btn_redo.setEnabled(self.undo_stack.can_redo)

    # ── Keyboard Shortcuts ──────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_S and not event.modifiers():
            self._on_split_selected()
        elif event.key() == Qt.Key_Delete:
            self._on_delete_selected()
        elif event.key() == Qt.Key_D and event.modifiers() & Qt.ControlModifier:
            self._on_duplicate_selected()
        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            if event.modifiers() & Qt.ShiftModifier:
                self.undo_stack.redo()
            else:
                self.undo_stack.undo()
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self.undo_stack.redo()
        else:
            super().keyPressEvent(event)
