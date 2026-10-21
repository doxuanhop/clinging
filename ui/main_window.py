"""
ui/main_window.py
Cửa sổ chính: ghép Title bar + Top toolbar + (Sidebar | Library | Preview |
Properties) + Timeline panel, dùng QSplitter để người dùng có thể kéo giãn.
"""

import os
from PySide6.QtCore import Qt, QPoint, QTimer, QUrl, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap, QIcon, QTransform, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGraphicsDropShadowEffect, QApplication, QGraphicsItem, QDialog
)
from ui.custom_dialog import CustomDialog as QMessageBox
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink

from theme import theme_manager
from ui.title_bar import TitleBar
from ui.sidebar import Sidebar
from ui.library_panel import LibraryPanel
from ui.preview_panel import PreviewPanel
from ui.properties_panel import PropertiesPanel
from ui.timeline_panel import TimelinePanel
from ui.presets_panel import PresetsPanel
from ui.effects_panel import EffectsPanel
from ui.cover_dialog import CoverDialog
from widgets.common import _qta, icon_color


def make_app_icon():
    from widgets.common import app_icon
    return app_icon()


class MainWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MainWindowEditor")
        # Decoder state must exist before signal wiring or autosave restore:
        # both may request a canvas frame during construction.
        self._video_readers = {}
        self._pending_canvas_time = 0.0
        self._last_tool_preview_key = None
        self._frame_sync_timer = QTimer(self)
        self._frame_sync_timer.setSingleShot(True)
        self._frame_sync_timer.setInterval(24)
        self._frame_sync_timer.timeout.connect(
            lambda: self._sync_canvas_frames_at_time(self._pending_canvas_time)
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        # ---- vùng làm việc chính (trái->phải) + timeline (dưới) ----
        self.work_splitter = work_splitter = QSplitter(Qt.Vertical)
        self._timeline_restore_sizes = None
        work_splitter.setHandleWidth(2)
        work_splitter.setChildrenCollapsible(False)
        # ---- vùng làm việc chính (trái->phải) dùng QSplitter ngang để tự co giãn linh hoạt ----
        horizontal_splitter = QSplitter(Qt.Horizontal)
        horizontal_splitter.setHandleWidth(2)
        horizontal_splitter.setChildrenCollapsible(False)

        self.sidebar = Sidebar()
        self.library_panel = LibraryPanel()
        self.preview_panel = PreviewPanel()
        self.properties_panel = PropertiesPanel()
        self.text_presets_panel = PresetsPanel("text")
        self.sticker_presets_panel = PresetsPanel("sticker")
        self.effects_panel = EffectsPanel()
        self.text_presets_panel.setVisible(False)
        self.sticker_presets_panel.setVisible(False)
        self.effects_panel.setVisible(False)

        # Tạo container chứa Sidebar và LibraryPanel + Presets
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.sidebar)
        left_layout.addWidget(self.library_panel)
        left_layout.addWidget(self.text_presets_panel)
        left_layout.addWidget(self.sticker_presets_panel)
        left_layout.addWidget(self.effects_panel)

        horizontal_splitter.addWidget(left_container)
        horizontal_splitter.addWidget(self.preview_panel)
        horizontal_splitter.addWidget(self.properties_panel)
        
        # Thiết lập tỉ lệ co dãn linh hoạt: Sidebar+Library (25%), Player (50%), Properties (25%)
        horizontal_splitter.setStretchFactor(0, 25)
        horizontal_splitter.setStretchFactor(1, 50)
        horizontal_splitter.setStretchFactor(2, 25)

        self.timeline_panel = TimelinePanel()
        self.timeline_panel.model.library_assets = []
        self.library_panel.resourcesChanged.connect(self._on_library_resources_changed)
        self.library_panel.thumbnailExportRequested.connect(
            self._open_thumbnail_export)
        self.library_panel.mediaSplitRequested.connect(
            self._open_media_split)
        self.library_panel.mediaCompressRequested.connect(
            self._open_media_compress)

        # VSplitter chia vùng làm việc chính (ở trên) và Timeline (ở dưới)
        work_splitter.addWidget(horizontal_splitter)
        work_splitter.addWidget(self.timeline_panel)
        
        # Thiết lập tỷ lệ co giãn dọc: Vùng trên (70%), Timeline (30%)
        work_splitter.setStretchFactor(0, 70)
        work_splitter.setStretchFactor(1, 30)

        # Bootstrap 70/30: Qt chia lại theo ti le, nen cap so nay khong phu thuoc
        # kich thuoc man hinh. Truoc do la [410, 440] -> timeline an 52% cua cua so.
        work_splitter.setSizes([700, 300])
        horizontal_splitter.setSizes([380, 700, 360])

        root_layout.addWidget(work_splitter, 1)

        self._wire_events()
        self._install_editor_shortcuts()
        self._apply_theme()
        theme_manager.themeChanged.connect(lambda _: self._apply_theme())

        # Auto-save setup
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setInterval(30000)  # tránh chặn UI khi đang kéo clip
        self._auto_save_timer.timeout.connect(self._auto_save)
        self._auto_save_timer.start()

        # Cài đặt người dùng chọn phải thắng giá trị hard-code ở trên.
        self._apply_settings()

        # Load autosave nếu có
        self._load_autosave()

    def _apply_settings(self) -> dict:
        """Đẩy cài đặt đang chạy vào cửa sổ này.

        Gọi lúc dựng và mỗi lần hộp thoại Cài đặt ghi file xong — không có
        đường nào khác, nên không tồn tại trạng thái 'đã lưu nhưng chưa áp'.
        """
        from core import settings
        values = settings.values()
        theme_manager.set_mode(values["theme"])
        self.timeline_panel.apply_settings(values)
        self._playhead_step_frames = int(values["playhead_step"])
        self._auto_save_timer.setInterval(
            int(values["auto_save_interval"]) * 60 * 1000)
        if values["auto_save"]:
            self._auto_save_timer.start()
        else:
            self._auto_save_timer.stop()
        self._apply_theme()
        return values

    def _on_theme_toggled(self):
        """Nút theme trên header ghi xuống cài đặt y như hộp thoại.

        Nếu chỉ đổi trong bộ nhớ thì lần mở app sau theme quay lại, và hộp
        thoại Cài đặt hiển thị một giá trị khác với gì người dùng đang thấy.
        """
        from core import settings
        mode = theme_manager.toggle()
        values = settings.values()
        values["theme"] = mode
        settings.save(values)
        return mode

    def _on_library_resources_changed(self, records):
        self.timeline_panel.model.library_assets = list(records)

    def _open_cover_dialog(self, clip):
        """Select a Main Storyline frame and store it for Home thumbnails."""
        from pathlib import Path
        from core.project_storage import ProjectManager

        manager = ProjectManager()
        base_dir = (Path(manager.project_path).parent if manager.project_path
                    else Path(clip.source_path).parent)
        playhead = self.timeline_panel.model.playhead
        source_time = clip.source_time(playhead)
        dialog = CoverDialog(clip, str(base_dir / "cover.png"), source_time, self)
        if dialog.exec() == QDialog.Accepted:
            manager.project_meta["cover_path"] = dialog.cover_path
            manager.project_meta["cover_time"] = dialog.selected_source_time
            manager.mark_modified()
            self._auto_save()
            QMessageBox.success(
                self, "Đã tạo ảnh bìa",
                "Ảnh bìa đã được lưu và sẽ hiển thị tại Dự án gần đây."
            )

    def restore_library_from_project(self, project):
        assets = project.get("assets") or project.get("library_assets") or []
        if not assets:
            records = []
            seen = set()
            tracks = project.get("tracks", project.get("timeline", {}).get("tracks", []))
            for track in tracks:
                for clip in track.get("clips", []):
                    path = clip.get("source_path", "")
                    kind = clip.get("media_type", "video")
                    key = os.path.normcase(path)
                    if path and kind in ("video", "audio", "image") and key not in seen:
                        seen.add(key)
                        records.append({"path": path, "type": kind,
                                        "name": clip.get("name") or os.path.basename(path)})
            assets = records
        self.library_panel.restore_resources(assets)

    # -------------------------------------------------------------
    # -------------------------------------------------------------
    def _wire_events(self):
        self.title_bar.save_btn.clicked.connect(self._on_save)
        self.title_bar.export_main.clicked.connect(self._on_export)
        self.title_bar.undoRequested.connect(self._undo_step)
        self.title_bar.redoRequested.connect(self._redo_step)
        self.title_bar.splitRequested.connect(self.timeline_panel._on_split_selected)
        self.title_bar.deleteRequested.connect(self.timeline_panel._on_delete_selected)
        self.title_bar.duplicateRequested.connect(self.timeline_panel._on_duplicate_selected)
        self.title_bar.playRequested.connect(self.timeline_panel.header.btn_play.click)
        self.title_bar.previousFrameRequested.connect(lambda: self._step_frame(-1))
        self.title_bar.nextFrameRequested.connect(lambda: self._step_frame(1))
        self.title_bar.autoCaptionsRequested.connect(self._open_auto_captions)
        self.title_bar.subtitleImportRequested.connect(self._open_subtitle_import)
        self.title_bar.shortcutsRequested.connect(self._show_shortcuts)
        self.title_bar.aboutRequested.connect(self._show_about)
        self.timeline_panel.themeToggleRequested.connect(self._on_theme_toggled)
        self.timeline_panel.coverRequested.connect(self._open_cover_dialog)
        self.timeline_panel.recapOverlayRequested.connect(self._open_recap_overlay)
        # Lớp phủ là cấu hình dự án nên model đổi là canvas phải vẽ lại ngay —
        # không có clip nào được chọn ở đây để mà dựa vào clipUpdated.
        self.timeline_panel.model.recapOverlayChanged.connect(
            self._on_recap_overlay_changed)
        self.preview_panel.canvas.bind_model(self.timeline_panel.model)
        self.timeline_panel.focusModeToggled.connect(self._on_timeline_focus)

        self.sidebar.currentChanged.connect(self._on_sidebar_changed)
        self.sidebar.toggleTimelineRequested.connect(self._on_toggle_timeline)

        # Kéo tài nguyên từ thư viện thả vào timeline (qua TimelineView)
        # Không cần kết nối từ PreviewCanvas nữa vì PreviewCanvas không nhận drop

        # Kết nối selection từ canvas → Properties Panel + Timeline selection
        self.preview_panel.canvas.itemSelected.connect(
            self._on_canvas_item_selected
        )
        self.preview_panel.canvas.resourceDropped.connect(
            self._on_resource_dropped_on_canvas
        )
        self.preview_panel.canvas.presetDropped.connect(
            self._on_preset_dropped_on_canvas
        )
        self.preview_panel.canvas.effectDropped.connect(
            lambda data, _x, _y: self._on_effect_applied(data)
        )
        self.preview_panel.canvas.previewRequested.connect(self._on_tool_preview)
        self.preview_panel.canvas.previewClearRequested.connect(self._clear_tool_preview)

        # Tool library: click = non-destructive preview, +/double click = commit.
        for panel in (self.text_presets_panel, self.sticker_presets_panel):
            panel.previewRequested.connect(self._on_tool_preview)
            panel.addRequested.connect(self._add_component_from_panel)
        self.effects_panel.effectPreviewRequested.connect(self._on_effect_preview)

        timeline_scene = self.timeline_panel.scene
        timeline_scene.preset_dropped.connect(self._on_preset_dropped_on_timeline)
        timeline_scene.effect_dropped.connect(self._on_effect_dropped_on_timeline)
        timeline_scene.tool_preview_requested.connect(self._on_tool_preview)
        timeline_scene.tool_preview_clear_requested.connect(self._clear_tool_preview)

        # Khởi tạo trạng thái project trống để tự động đổi tỉ lệ khung hình theo file đầu tiên
        self.is_project_empty = True

        # Khi timeline thay đổi (thêm, xóa, di chuyển clip) → vẽ lại Player Canvas
        def on_clip_added(clip_model):
            # Nếu dự án trống, tự động đổi tỉ lệ theo clip đầu tiên
            if self.is_project_empty:
                # Đọc kích thước file thực tế bằng OpenCV / QPixmap
                ratio_string = self._detect_media_aspect_ratio(clip_model.source_path, clip_model.media_type)
                # Kích hoạt signal đổi tỷ lệ khung hình
                self.timeline_panel.header.combo_aspect_ratio.setCurrentText(ratio_string)
                self.is_project_empty = False
            self._sync_canvas()

        self.timeline_panel.model.clipAdded.connect(on_clip_added)
        self.timeline_panel.model.clipRemoved.connect(self._on_clip_removed)
        self.timeline_panel.model.clipMoved.connect(self._sync_canvas)
        self.timeline_panel.model.clipResized.connect(self._sync_canvas)
        self.timeline_panel.model.clipUpdated.connect(self._on_clip_updated)
        self.timeline_panel.model.tracksReordered.connect(self._update_canvas_z_index)

        # Khi chọn clip trên Timeline → Hiển thị thuộc tính trên Properties Panel & Highlight trên Canvas
        self.timeline_panel.model.selectionChanged.connect(self._on_timeline_selection_changed)

        # Cập nhật 2 chiều: Khi người dùng kéo dãn trên Canvas → Cập nhật ngược lại Properties Panel
        # Canvas cập nhật trực tiếp vào model. Cần đồng bộ sang form bên phải.

        # Khi nhập trực tiếp số trên Properties Panel → Cập nhật model và đồng bộ sang Canvas + Timeline
        self.properties_panel.clipPropertiesChanged.connect(self._on_properties_changed_by_user)

        # Chuot phai tren clip co keyframe → mo do thi duong cong
        self.timeline_panel.keyframeGraphRequested.connect(
            self._open_keyframe_graph)

        # Khi playhead thay đổi (do nắm kéo hoặc do timer chạy) -> tự động cập nhật render frame tương ứng trên Canvas
        self.timeline_panel.model.playheadChanged.connect(self._schedule_canvas_frame_sync)

        # Cập nhật tổng thời gian khi có clip mới
        self.timeline_panel.clipAdded.connect(
            lambda name: self.timeline_panel.header.time_total.setText(
                f"{int(self.timeline_panel.model.duration // 60):02d}:"
                f"{self.timeline_panel.model.duration % 60:04.1f}"
            )
        )
        # Kết nối nút Play của Trình phát với chuyển động của Playhead trên Timeline
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)  # Khoảng 30 FPS
        self._play_timer.timeout.connect(self._on_play_step)
        # Kết nối từ Timeline Header Playback mới nằm ngang
        self.timeline_panel.header.btn_play.clicked.connect(self._on_timeline_play_clicked)
        self.timeline_panel.header.btn_prev.clicked.connect(lambda: setattr(self.timeline_panel.model, "playhead", max(0.0, self.timeline_panel.model.playhead - 1.0)))
        self.timeline_panel.header.btn_next.clicked.connect(lambda: setattr(self.timeline_panel.model, "playhead", min(self.timeline_panel.model.duration, self.timeline_panel.model.playhead + 1.0)))
        
        # Kết nối Aspect Ratio Combobox
        self.timeline_panel.header.combo_aspect_ratio.currentTextChanged.connect(self._on_aspect_ratio_changed)
        # Kết nối Fit/Fill mode buttons
        self.timeline_panel.header.fitModeChanged.connect(self._on_fit_mode_changed)
        # Kết nối Effects Panel → áp dụng hiệu ứng lên clip đang chọn
        self.effects_panel.effectApplied.connect(self._on_effect_applied)
        # Thiết lập tỷ lệ ban đầu mặc định 16:9
        self.timeline_panel.model.project_ratio = "16:9"
        self.preview_panel.canvas.update_aspect_ratio("16:9 - Ngang chuẩn")
        
        # Khởi tạo Audio Player
        self._init_audio_player()

    def _install_editor_shortcuts(self):
        """Phím tắt hoạt động trong toàn editor, không phụ thuộc panel đang focus."""
        # (nhãn, callback) — hộp "Phím tắt" in đúng nhãn này, nên danh sách
        # hiển thị không thể lệch khỏi phím thật được cài.
        bindings = {
            "Ctrl+S": ("Lưu dự án", self._on_save),
            "Ctrl+E": ("Xuất video", self._on_export),
            "Ctrl+Z": ("Hoàn tác", self._undo_step),
            "Ctrl+Shift+Z": ("Làm lại", self._redo_step),
            "Ctrl+Y": ("Làm lại", self._redo_step),
            "Ctrl+D": ("Nhân bản clip đang chọn",
                       self.timeline_panel._on_duplicate_selected),
            "Ctrl+C": ("Sao chép clip đang chọn",
                       lambda: self._invoke_unless_editing(
                           self.timeline_panel._on_copy_selected)),
            "Ctrl+V": ("Dán clip tại đầu phát",
                       lambda: self._invoke_unless_editing(
                           self.timeline_panel._on_paste_selected)),
            "Delete": ("Xóa clip đang chọn",
                       lambda: self._invoke_unless_editing(self.timeline_panel._on_delete_selected)),
            "Backspace": ("Xóa clip đang chọn",
                          lambda: self._invoke_unless_editing(self.timeline_panel._on_delete_selected)),
            "S": ("Tách clip đang chọn",
                  lambda: self._invoke_unless_editing(self.timeline_panel._on_split_selected)),
            "Space": ("Phát / dừng",
                      lambda: self._invoke_unless_editing(self.timeline_panel.header.btn_play.click)),
            "M": ("Tắt tiếng xem trước",
                  lambda: self._invoke_unless_editing(self.timeline_panel.header.btn_mute.click)),
            "Left": ("Lùi theo số frame trong Cài đặt",
                     lambda: self._invoke_unless_editing(lambda: self._step_frame(-1))),
            "Right": ("Tiến theo số frame trong Cài đặt",
                      lambda: self._invoke_unless_editing(lambda: self._step_frame(1))),
        }
        # Hội thoại "Phím tắt" đọc đúng dict này — danh sách in ra không bao
        # giờ lệch khỏi phím thật được cài.
        self._editor_bindings = dict(bindings)
        self._editor_shortcuts = []
        for sequence, (_label, callback) in bindings.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._editor_shortcuts.append(shortcut)

    @staticmethod
    def _invoke_unless_editing(callback):
        """Không chiếm phím gõ/xóa/điều hướng khi người dùng đang nhập liệu."""
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return
        callback()

    def _step_frame(self, direction: int):
        """Tiến/lùi đúng `playhead_step` frame theo FPS dự án."""
        from core import settings
        from core.project_storage import ProjectManager
        fps = max(1, int(ProjectManager().project_meta.get(
            "fps", settings.get("default_fps"))))
        step = max(1, int(getattr(self, "_playhead_step_frames", 1)))
        target = self.timeline_panel.model.playhead + (direction * step / fps)
        self.timeline_panel.model.playhead = max(
            0.0, min(self.timeline_panel.model.duration, target)
        )

    def _on_aspect_ratio_changed(self, ratio_text):
        """Xử lý khi người dùng thay đổi tỉ lệ khung hình."""
        old_ratio = getattr(self.timeline_panel.model, "project_ratio", "16:9")
        self.preview_panel.canvas.update_aspect_ratio(ratio_text)
        ratio_key = ratio_text.split(" - ")[0] if " - " in ratio_text else "16:9"
        self.timeline_panel.model.project_ratio = ratio_key
        from core.canvas_utils import fit_to_project_ratio, ASPECT_RATIOS
        old_w, old_h = ASPECT_RATIOS.get(old_ratio, (1920, 1080))
        new_w, new_h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))
        for track in self.timeline_panel.model.tracks:
            for clip in track.clips:
                if clip.media_type in ("video", "image"):
                    fit_to_project_ratio(clip, ratio_key)
                else:
                    # Overlay dùng tọa độ tương đối theo tâm canvas.
                    clip.transform.x = clip.transform.x / old_w * new_w
                    clip.transform.y = clip.transform.y / old_h * new_h
        self._sync_canvas()

    def _on_resource_dropped_on_canvas(self, name, kind, scene_x, scene_y):
        """Canvas và Timeline cùng ghi vào TimelineModel (single source of truth)."""
        from core.timeline_model import TrackType
        from core.commands import AddClipCommand
        from ui.timeline_panel import MEDIA_TO_TRACK

        track_type = MEDIA_TO_TRACK.get(kind, TrackType.OVERLAY)
        model = self.timeline_panel.model
        # Giống CapCut: video đầu tiên là Main Storyline; video kéo
        # trực tiếp lên canvas là một visual overlay riêng phía trên.
        if kind == "video" and any(t.is_main_track and t.clips for t in model.tracks):
            track = model.add_track(TrackType.VIDEO)
        else:
            track = model.find_or_create_track(track_type)
        duration = self.timeline_panel._get_media_duration(name, kind)
        cmd = AddClipCommand(
            self.timeline_panel.model, track.track_id, name,
            media_type=kind, start_time=self.timeline_panel.model.playhead,
            duration=duration, name=os.path.basename(name) if os.path.exists(name) else name
        )
        self.timeline_panel.undo_stack.push(cmd)
        clip = self.timeline_panel.model.get_clip(cmd._clip_id)
        if clip:
            clip.transform.x = scene_x
            clip.transform.y = scene_y
            self.timeline_panel.model.clipUpdated.emit(clip.clip_id)
        self.timeline_panel.banner.hide()
        self._sync_canvas()
        return clip

    @staticmethod
    def _apply_preset_style(clip, preset, kind):
        """Persist card styling on the clip so save/load and Canvas agree."""
        if not clip:
            return
        if kind == "text":
            clip.font_family = preset.get("font", "Arial")
            clip.font_size = float(preset.get("size", 40.0))
            clip.font_bold = bool(preset.get("bold", False))
            clip.font_color = preset.get("color", "#FFFFFF")
        elif kind == "sticker":
            clip.sticker_icon = preset.get("icon", "")
            clip.sticker_color = preset.get("color", "#FFFFFF")

    def _on_preset_dropped_on_canvas(self, preset, kind, scene_x, scene_y):
        self._clear_tool_preview()
        clip = self._on_resource_dropped_on_canvas(
            preset.get("label", kind.title()), kind, scene_x, scene_y
        )
        self._apply_preset_style(clip, preset, kind)
        if clip:
            self.timeline_panel.model.clipUpdated.emit(clip.clip_id)
            self.timeline_panel.model.select_clip(clip.clip_id)
        self._sync_canvas()

    def _on_preset_dropped_on_timeline(self, preset, kind, drop_time, drop_y):
        self._clear_tool_preview()
        clip = self.timeline_panel._on_resource_dropped(
            preset.get("label", kind.title()), kind, drop_time, drop_y
        )
        self._apply_preset_style(clip, preset, kind)
        if clip:
            self.timeline_panel.model.clipUpdated.emit(clip.clip_id)
            self.timeline_panel.model.select_clip(clip.clip_id)
        self._sync_canvas()

    def _add_component_from_panel(self, preset, kind):
        """The + button and double click add at the current playhead/centre."""
        self._on_preset_dropped_on_canvas(preset, kind, 0.0, 0.0)

    def _clear_tool_preview(self):
        self._last_tool_preview_key = None
        self.preview_panel.canvas.clear_tool_preview()
        # Hover-preview quét hết nhịp tiến độ của clip, nên khi rời chuột phải
        # vẽ lại đúng khung tại playhead, không đểค้าง ở khung giữa animation.
        self._sync_canvas_frames_at_time(self.timeline_panel.model.playhead)

    def _on_tool_preview(self, data, kind):
        key = (kind, data.get("name") or data.get("label"))
        if key == self._last_tool_preview_key:
            return
        self._last_tool_preview_key = key
        if kind == "effect":
            self._on_effect_preview(data)
        elif kind in ("text", "sticker"):
            self.preview_panel.canvas.preview_component(data, kind)

    def _effect_target_at(self, time_seconds=None):
        """Selected visual wins; otherwise use the top active visual layer."""
        model = self.timeline_panel.model
        for clip_id in model.selected_clip_ids:
            clip = model.get_clip(clip_id)
            if (time_seconds is not None and clip and
                    not (clip.start_time <= time_seconds < clip.end_time)):
                continue
            item = self.preview_panel.canvas._clip_items.get(clip_id)
            if item is not None and hasattr(item, "_apply_effects"):
                return clip
        t = model.playhead if time_seconds is None else time_seconds
        for clip in reversed(model.active_visual_clips_at(t)):
            item = self.preview_panel.canvas._clip_items.get(clip.clip_id)
            if item is not None and hasattr(item, "_apply_effects"):
                return clip
        return None

    def _on_effect_preview(self, effect_data):
        from core.timeline_model import EffectData, EFFECT_PRESETS
        target = self._effect_target_at()
        if not target:
            self.preview_panel.canvas.clear_tool_preview()
            return
        name = effect_data.get("name", "")
        from ui.effects_panel import TRANSITION_CATEGORY
        category = (self._effect_category(name)
                    or effect_data.get("category", ""))
        if category == TRANSITION_CATEGORY:
            canvas_rect = self.preview_panel.canvas.sceneRect()
            self.preview_panel.canvas.preview_transition(
                target.clip_id, name,
                canvas_rect.width(), canvas_rect.height())
            return
        effect = EffectData(
            name=effect_data.get("name", ""),
            category=effect_data.get("category", ""),
            intensity=1.0,
            params=dict(EFFECT_PRESETS.get(effect_data.get("name", ""), {})),
        )
        self.preview_panel.canvas.preview_effect(target.clip_id, effect)

    def _on_effect_dropped_on_timeline(self, effect_data, drop_time, _drop_y):
        target = self._effect_target_at(drop_time)
        self._apply_effect_to_clip(effect_data, target.clip_id if target else None)

    def _on_fit_mode_changed(self, mode):
        """Xử lý khi người dùng bấm Fit/Fill trên timeline header."""
        from core.canvas_utils import apply_auto_fit, ASPECT_RATIOS
        ratio_key = self.timeline_panel.header.combo_aspect_ratio.currentText()
        ratio_key = ratio_key.split(" - ")[0] if " - " in ratio_key else "16:9"
        canvas_w, canvas_h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))

        # Áp dụng cho tất cả clip đang chọn, hoặc clip đầu tiên
        selected_ids = self.timeline_panel.model.selected_clip_ids
        if selected_ids:
            for clip_id in selected_ids:
                clip = self.timeline_panel.model.get_clip(clip_id)
                if clip and clip.media_type in ("video", "image"):
                    clip.transform.fit_mode = mode
                    apply_auto_fit(clip, canvas_w, canvas_h)
                    canvas_item = self.preview_panel.canvas._clip_items.get(clip_id)
                    if canvas_item:
                        canvas_item.sync_from_model()
                        canvas_item.update()
        else:
            # Không có clip nào chọn → áp dụng cho tất cả clip video/image
            for track in self.timeline_panel.model.tracks:
                for clip in track.clips:
                    if clip.media_type in ("video", "image"):
                        clip.transform.fit_mode = mode
                        apply_auto_fit(clip, canvas_w, canvas_h)
            self._sync_canvas()

        # Cập nhật trạng thái nút Fit/Fill
        self.timeline_panel.header.btn_fit.setChecked(mode == "fit")
        self.timeline_panel.header.btn_fill.setChecked(mode == "fill")

    def _init_audio_player(self):
        """Khởi tạo Audio Engine."""
        self._audio_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._video_sink = QVideoSink(self)
        self._audio_player.setAudioOutput(self._audio_output)
        self._audio_player.setVideoSink(self._video_sink)
        self._video_sink.videoFrameChanged.connect(self._on_qt_video_frame)
        self._audio_output.setVolume(1.0)
        # Nút loa ở TimelineHeader. QAudioOutput.setMuted không ghi gì vào project
        # nên ô nghe thử im lặng mà file xuất vẫn đủ tiếng — cùng cách CapCut dùng.
        self.timeline_panel.header.mutedToggled.connect(self._audio_output.setMuted)
        # QTimer đọc player.position() làm đồng hồ duy nhất; positionChanged
        # trước đây khiến mỗi frame bị giải mã hai lần.
        self._audio_player.mediaStatusChanged.connect(self._on_media_status_changed)

    def _on_timeline_play_clicked(self):
        """Kích hoạt play/pause từ nút Play nằm ngang trên Timeline Header."""
        is_checked = self.timeline_panel.header.btn_play.isChecked()
        # Đổi icon
        self.timeline_panel.header.btn_play.setIcon(
            _qta().icon("fa6s.pause" if is_checked else "fa6s.play", color=icon_color())
        )
        self._on_play_toggled(is_checked)

    def _sync_canvas(self):
        """Đồng bộ hóa canvas trình phát với timeline model."""
        self.preview_panel.canvas.sync_scene_from_model(
            self.timeline_panel.model,
            self._on_canvas_item_transformed,
            self._on_canvas_edit_committed
        )
        # Canvas dung ClipItem moi sau lan dong bo nay; decoder cua clip da
        # khoi model (mo du an khac, hoan tac xoa) van giu file mo va mot frame
        # 2,7 MB trong RAM - phai dong theo.
        alive = {clip.clip_id for track in self.timeline_panel.model.tracks
                 for clip in track.clips}
        for clip_id in [k for k in self._video_readers if k not in alive]:
            self._video_readers.pop(clip_id).close()
        self._update_canvas_z_index()
        self._schedule_canvas_frame_sync(self.timeline_panel.model.playhead)

    def _on_clip_removed(self, clip_id):
        reader = self._video_readers.pop(clip_id, None)
        if reader is not None:
            reader.close()
        self.is_project_empty = not any(
            track.clips for track in self.timeline_panel.model.tracks
        )
        self._sync_canvas()

    def _playback_tracks(self):
        """Main Storyline is the master playback source, overlays follow it."""
        return sorted(
            self.timeline_panel.model.tracks,
            key=lambda track: (not track.is_main_track, -track.z_index),
        )

    def _on_qt_video_frame(self, frame):
        """Qt FFmpeg fallback for codecs OpenCV cannot decode (for example WMV)."""
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        source = os.path.normcase(os.path.abspath(
            self._audio_player.source().toLocalFile()
        ))
        model = self.timeline_panel.model
        candidates = []
        for track in model.tracks:
            if not track.is_visible:
                continue
            for clip in track.clips:
                clip_source = os.path.normcase(os.path.abspath(clip.source_path))
                if (clip.media_type == "video" and clip_source == source and
                        clip.start_time <= model.playhead < clip.end_time):
                    candidates.append((not track.is_main_track, track.z_index, clip))
        if not candidates:
            return
        clip = min(candidates, key=lambda entry: (entry[0], entry[1]))[2]
        item = self.preview_panel.canvas._clip_items.get(clip.clip_id)
        if item is not None:
            item.current_frame_pixmap = QPixmap.fromImage(image)
            item.setVisible(True)
            item.update()

    def _update_canvas_z_index(self):
        """Top-to-Bottom Timeline = Front-to-Back Canvas."""
        self.preview_panel.canvas.update_rendering_order(
            self.timeline_panel.model
        )

    def _on_timeline_selection_changed(self, selected_ids):
        canvas = self.preview_panel.canvas
        canvas._selecting_from_timeline = True
        canvas._expected_selection = list(selected_ids)
        try:
            canvas.scene_obj.clearSelection()
            for selected_id in selected_ids:
                selected_item = canvas._clip_items.get(selected_id)
                if selected_item:
                    selected_item.setSelected(True)
            if len(selected_ids) == 1:
                clip_id = selected_ids[0]
                clip = self.timeline_panel.model.get_clip(clip_id)
                if clip:
                    self.properties_panel.show_clip_properties(clip)
            else:
                # Zero or multi-selection has no unambiguous property target.
                self.properties_panel.show_empty()
        finally:
            canvas._selecting_from_timeline = False

    def _on_canvas_item_selected(self, selected_item):
        """Khi người dùng chọn item trên Canvas → đồng bộ Properties Panel + Timeline selection."""
        if selected_item is None:
            canvas = self.preview_panel.canvas
            model = self.timeline_panel.model
            # Qt giao selectionChanged bang zero-timer, tuc la RAT lau sau khi
            # _sync_canvas_frames_at_time() an clip. Mot clip ngoai playhead bi
            # an di thi scene bao "khong con gi duoc chon" — do KHONG phai
            # nguoi dung bam vao vung trong. De panel biet duoc dieu do thi
            # phoi canh o day: clear chi duoc phep khi clip ma timeline yeu cau
            # hien van con nam tren canvas.
            expected = set(canvas._expected_selection)
            visible_now = {clip_id for clip_id, item in canvas._clip_items.items()
                           if item.isVisible()}
            if not (expected & visible_now):
                return
            model.deselect_all()
            self.properties_panel.update_panel_for_item(None)
            return

        self.properties_panel.update_panel_for_item(selected_item)

        clip_model = getattr(selected_item, 'clip_model', None)
        if clip_model:
            self.timeline_panel.model.select_clip(clip_model.clip_id, add_to=False)

    def _on_canvas_item_transformed(self, clip_model):
        """Khi người dùng kéo dãn co tỷ lệ bằng neo trên canvas → cập nhật Properties Panel."""
        self.properties_panel.update_editor_values(clip_model)

    def _undo_step(self):
        self.timeline_panel.undo_stack.undo()
        self._sync_panel_after_history()

    def _redo_step(self):
        self.timeline_panel.undo_stack.redo()
        self._sync_panel_after_history()

    def _sync_panel_after_history(self):
        editor = self.properties_panel.current_editor
        if editor is None:
            return
        # Panel không tự đọc lại model khi lịch sử đổi: sau Ctrl+Z mà ô nhập vẫn
        # giữ giá trị vừa hoàn tác thì cú gõ tiếp theo sẽ ghi nguyên số cũ. Chỉ
        # làm ở đây, không làm lúc push, vì lúc đó con trỏ đang nằm trong chính
        # ô nhập và setText sẽ nhảy caret về cuối.
        clip = self.timeline_panel.model.get_clip(editor.clip_id)
        if clip is not None:
            self.properties_panel.update_editor_values(clip)

    def _on_clip_updated(self, clip_id):
        """Vẽ lại RIÊNG item của clip khi một lệnh sửa/hoàn tác phát clipUpdated.

        Trước đây Ctrl+Z của lệnh chữ không hiện lên Canvas vì clipUpdated chỉ
        có scene của timeline nghe. Không gọi _sync_canvas() ở đây: nó dựng lại
        mọi item, mà dựng lại item đang có focus thì con trỏ gõ chữ bị mất.
        """
        item = self.preview_panel.canvas._clip_items.get(clip_id)
        if item is None:
            return
        if hasattr(item, "refresh_style") and not item.hasFocus():
            item.refresh_style()
        item.sync_from_model()
        item.update()

    def _on_canvas_edit_committed(self, clip_model, kind, values, before=None):
        """Mot gesture tren Canvas (keo neo, sua chu inline) = MOT lenh undo.

        Item da ghi ket qua vao model trong luc keo nen lenh phai nhan `before`
        tu luc bam chuot; neu khong thi Ctrl+Z tra lai dung gia tri vua keo.
        """
        model = self.timeline_panel.model
        clip = model.get_clip(clip_model.clip_id)
        if clip is None or not values:
            return
        stack = self.timeline_panel.undo_stack
        if kind == "text":
            from core.commands import SetClipTextCommand
            stack.push(SetClipTextCommand(model, clip.clip_id, **values))
            return
        from core.commands import SetClipTransformCommand
        if before is None:
            return
        if all(abs(float(before[key]) - float(value)) < 0.005
               for key, value in values.items()):
            return
        stack.push(SetClipTransformCommand(model, clip.clip_id,
                                           before=before, **values))

    def _on_properties_changed_by_user(self, clip_id, name, scale_x, scale_y, rotation, opacity, x, y):
        """Khi người dùng nhập số trên Properties Panel → cập nhật Model & đồng bộ Canvas."""
        model = self.timeline_panel.model
        clip = model.get_clip(clip_id)
        if clip is None:
            return
        requested = {"name": name, "scale_x": scale_x, "scale_y": scale_y,
                     "rotation": rotation, "opacity": opacity, "x": x, "y": y}
        if any(clip.keyframes.values()):
            # Clip có keyframe: AutoKeyframeCommand đã là lệnh undo của thao tác
            # này. Đẩy thêm một lệnh hình học lên đầu stack buộc người dùng
            # Ctrl+Z hai lần cho một cú kéo spin.
            model.update_clip_properties(clip_id, **requested)
        else:
            from core.commands import SetClipTransformCommand, transform_snapshot
            current = transform_snapshot(clip)
            changed = any(abs(current[key] - float(value)) >= 0.005
                          for key, value in requested.items() if key != "name")
            if changed or str(name) != str(clip.name):
                self.timeline_panel.undo_stack.push(
                    SetClipTransformCommand(model, clip_id, **requested))
        canvas_item = self.preview_panel.canvas._clip_items.get(clip_id)
        if canvas_item:
            canvas_item.sync_from_model()

    def _on_effect_applied(self, effect_data):
        """Khi người dùng chọn 1 hiệu ứng từ EffectsPanel → áp dụng lên clip đang chọn."""
        target = self._effect_target_at()
        self._apply_effect_to_clip(effect_data, target.clip_id if target else None)

    def _effect_category(self, effect_name):
        """Tìm danh mục thật của thẻ hiệu ứng theo tên, ưu tiên hơn dữ liệu kéo-thả."""
        from ui.effects_panel import EFFECT_CATEGORIES
        for category, effects in EFFECT_CATEGORIES.items():
            if any(e.get("name") == effect_name for e in effects):
                return category
        return ""

    def _apply_effect_to_clip(self, effect_data, clip_id):
        self._clear_tool_preview()
        if not clip_id:
            return
        effect_name = effect_data.get("name", "")
        category = (self._effect_category(effect_name)
                    or effect_data.get("category", ""))
        from ui.effects_panel import TRANSITION_CATEGORY
        if category == TRANSITION_CATEGORY:
            # Nhóm này là chuyển tiếp, không phải EffectData: áp nhầm thì clip
            # có thêm một hiệu ứng không vẽ gì còn người dùng thì tưởng đã nối
            # hai clip.
            self._apply_transition(clip_id, effect_name)
            return
        from core.commands import ApplyEffectCommand
        cmd = ApplyEffectCommand(
            self.timeline_panel.model, clip_id,
            dict(effect_data, category=category))
        self.timeline_panel.undo_stack.push(cmd)
        # Cập nhật Properties Panel hiệu ứng tab
        clip = self.timeline_panel.model.get_clip(clip_id)
        if clip:
            self.properties_panel.update_effects_tab(clip)
        # Vẽ lại canvas
        self._sync_canvas()

    def _apply_transition(self, clip_id, name, duration=None):
        """Gắn/xóa chuyển tiếp qua SetTransitionCommand — có ripple, có undo."""
        model = self.timeline_panel.model
        if name and model.max_transition_duration(clip_id, name) <= 0.0:
            # Không đẩy command rỗng: mỗi cú nhấp thừa như vậy là một lần Ctrl+Z
            # trắng cho người dùng.
            self._explain_no_transition_room(clip_id, name)
            return False
        from core.commands import SetTransitionCommand
        self.timeline_panel.undo_stack.push(
            SetTransitionCommand(model, clip_id, name, duration))
        clip = model.get_clip(clip_id)
        if clip:
            self.properties_panel.show_clip_properties(clip)
        self._sync_canvas()
        return True

    def _explain_no_transition_room(self, clip_id, name):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QToolTip
        from core import transitions
        model = self.timeline_panel.model
        clip = model.get_clip(clip_id)
        track = model.get_track(clip.track_id) if clip else None
        if transitions.is_junction(name) and track is not None \
                and not track.is_main_track:
            reason = "Kiểu nối hai clip chỉ dùng được trên Main Storyline."
        elif transitions.is_junction(name):
            reason = ("Cần clip liền trước trên Main Storyline và mỗi bên còn "
                      "tối thiểu %.1fs." % transitions.MIN_KEEP)
        else:
            reason = ("Clip phải dài hơn %.1fs để hình còn thấy được khi phai."
                      % transitions.MIN_KEEP)
        QToolTip.showText(QCursor.pos(), "%s: không đủ chỗ\n%s" % (name, reason))

    def _on_play_toggled(self, playing):
        if playing:
            main_video_ends = [
                clip.end_time
                for track in self.timeline_panel.model.tracks
                for clip in track.clips
                if track.is_main_track and clip.media_type == "video"
            ]
            video_ends = main_video_ends or [
                clip.end_time
                for track in self.timeline_panel.model.tracks
                for clip in track.clips
                if clip.media_type == "video"
            ]
            self._playback_end_time = (
                max(video_ends) if video_ends else self.timeline_panel.model.duration
            )
            # Tìm clip đang nằm tại playhead hoặc clip đầu tiên để nạp âm thanh làm chuẩn
            source_file = ""
            active_clip = None
            for track in self._playback_tracks():
                if track.is_muted:
                    continue
                for clip in track.clips:
                    # Lấy clip có âm thanh/hình ảnh đang nằm dưới vạch playhead hoặc clip đầu tiên
                    if clip.start_time <= self.timeline_panel.model.playhead <= clip.end_time:
                        import os
                        if os.path.exists(clip.source_path):
                            source_file = clip.source_path
                            active_clip = clip
                            break
                if source_file:
                    break

            # Fallback lấy clip đầu tiên nếu không có clip nào dưới playhead
            if not source_file:
                for track in self._playback_tracks():
                    if track.is_muted:
                        continue
                    if track.clips:
                        import os
                        if os.path.exists(track.clips[0].source_path):
                            source_file = track.clips[0].source_path
                            active_clip = track.clips[0]
                            break

            if source_file and active_clip:
                self._audio_player.setSource(QUrl.fromLocalFile(source_file))
                # Di chuyển player tới vị trí playhead tương ứng (mili-giây), tính thêm in_point của clip và start_time
                local_pos_ms = int(active_clip.source_time(
                    self.timeline_panel.model.playhead) * 1000.0)
                self._audio_player.setPosition(max(0, local_pos_ms))
                self._apply_preview_rate(active_clip)
                self._audio_output.setVolume(min(
                    1.0, self.timeline_panel.model.transition_gain(
                        active_clip, self.timeline_panel.model.playhead)))
                
            self._audio_player.play()
            self._play_timer.start()
            self._sync_canvas_frames_at_time(self.timeline_panel.model.playhead)
        else:
            self._audio_player.pause()
            self._play_timer.stop()
            # Dừng giữa điểm crossover mà để gain nguyên thì lần play sau sẽ
            # bắt đầu bằng tiếng bé xíu; trả volume về mức bình thường.
            self._audio_output.setVolume(1.0)

    def _on_media_status_changed(self, status):
        """Media gốc kết thúc: giữ playhead tại điểm cuối, không tua về 0."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._play_timer.isActive():
            self._stop_playback_at_end()

    def _stop_playback_at_end(self):
        end_time = min(
            getattr(self, "_playback_end_time", self.timeline_panel.model.duration),
            self.timeline_panel.model.duration,
        )
        self._play_timer.stop()
        self._audio_player.stop()
        self._audio_output.setVolume(1.0)
        self.timeline_panel.model.playhead = end_time
        self.timeline_panel.header.btn_play.setChecked(False)
        self.timeline_panel.header.btn_play.setIcon(
            _qta().icon("fa6s.play", color=icon_color())
        )
        self._sync_canvas_frames_at_time(end_time)

    def _on_audio_position_changed(self, position_ms):
        """Khi đồng hồ gốc (Audio) di chuyển -> đồng bộ Playhead của Timeline."""
        if not self._play_timer.isActive():
            return
            
        current_source = self._audio_player.source().toLocalFile()
        active_clip = None
        for track in self._playback_tracks():
            if track.is_muted:
                continue
            for clip in track.clips:
                # So sánh qua _same_media: Qt trả đường dẫn gạch chéo trong khi
                # model có thể lưu gạch ngược. So chuỗi thô thì không clip nào
                # khớp, và nhánh "else" bên dưới lấy giây của FILE NGUỒN gán thẳng
                # vào playhead — clip 2x chạy sai nhịp, clip đã trim nhảy về đầu.
                if (self._same_media(clip.source_path, current_source) and
                        clip.start_time <= self.timeline_panel.model.playhead <= clip.end_time):
                    active_clip = clip
                    break
            if active_clip:
                break

        if active_clip:
            source_time = position_ms / 1000.0
            playhead_time = self._timeline_at_source(active_clip, source_time)
        else:
            playhead_time = position_ms / 1000.0
        # Cùng một lý do như _on_play_step: position về 0 khi nguồn mới nạp hoặc
        # khi vừa seek. Đồng hồ cũ còn hơn kéo playhead nhảy ngược về đầu timeline.
        if playhead_time + 0.05 < self.timeline_panel.model.playhead:
            return
        self.timeline_panel.model.playhead = playhead_time

    def _on_play_step(self):
        # Nếu đang phát và audio_player đang chạy, đồng bộ theo audio player
        if self._audio_player.playbackState() == QMediaPlayer.PlayingState:
            current_source = self._audio_player.source().toLocalFile()
            active_clip = None
            for track in self._playback_tracks():
                if track.is_muted:
                    continue
                for clip in track.clips:
                    if self._same_media(clip.source_path, current_source) and clip.start_time <= self.timeline_panel.model.playhead <= clip.end_time:
                        active_clip = clip
                        break
                if active_clip:
                    break
            if active_clip:
                source_time = self._audio_player.position() / 1000.0
                current_time = self._timeline_at_source(active_clip, source_time)
            else:
                current_time = self._audio_player.position() / 1000.0
            # Đổi nguồn ở điểm crossover cũng là một lần seek: position có thể còn
            # 0 trong lúc file mới nạp. Giữ đồng hồ cũ còn hơn kéo playhead nhảy
            # ngược về đầu timeline.
            if current_time + 0.05 < self.timeline_panel.model.playhead:
                current_time = self.timeline_panel.model.playhead + 0.033
        else:
            # Fallback nếu không có file âm thanh làm master clock
            current_time = self.timeline_panel.model.playhead + 0.033
            self.timeline_panel.model.playhead = current_time
            
        playback_end = getattr(
            self, "_playback_end_time", self.timeline_panel.model.duration
        )
        if current_time >= playback_end:
            self._stop_playback_at_end()
            return
            
        # Vẽ frame video/ảnh tương ứng tại thời điểm current_time trên Player Canvas
        self.timeline_panel.model.playhead = max(0.0, current_time)
        self._apply_preview_audio(max(0.0, current_time))

    def _schedule_canvas_frame_sync(self, current_time):
        """Gộp các sự kiện scrub/kéo dồn dập thành một lần giải mã mỗi frame UI."""
        self._pending_canvas_time = float(current_time)
        if not self._frame_sync_timer.isActive():
            self._frame_sync_timer.start()

    def _same_media(self, left, right):
        """So hai đường dẫn media bất chấp kiểu phân tách.

        Qt trả về source bằng dấu gạch chéo, nhưng một project cũ hay đường dẫn
        gõ tay có thể chứa gạch ngược. Nếu so chuỗi thô thì mỗi bước tick lại
        "đổi nguồn" một lần, và người dùng nghe thấy tiếng khựng mỗi 33ms.
        """
        import os
        if not left or not right:
            return False
        return os.path.normcase(os.path.normpath(left)) == \
            os.path.normcase(os.path.normpath(right))

    def _apply_preview_rate(self, clip):
        """Nhịp phát của master clock phải theo tốc độ clip.

        Có hai lý do phải hỏi backend trước khi đặt: backend từ chối rate ngoài
        khoảng nó hỗ trợ, và phép ánh xạ position -> playhead phải chia cho con số
        THỰC SỰ đang áp dụng chứ không phải con số ta xin. Nếu chia theo speed
        trong khi backend làm ngơ, playhead chạy nửa nhịp và hình chạy sai.
        """
        requested = float(getattr(clip, "speed_factor", 1.0)) or 1.0
        try:
            if not self._audio_player.isPlaybackRateSupported(requested):
                requested = 1.0
        except (AttributeError, RuntimeError):
            requested = 1.0
        if abs(self._audio_player.playbackRate() - requested) > 1e-3:
            self._audio_player.setPlaybackRate(requested)
        self._preview_rate = requested

    def _clock_rate(self) -> float:
        """Tốc độ thực đang áp cho luồng tiếng — mẫu số của phép đổi trục thời gian."""
        try:
            value = float(self._audio_player.playbackRate())
        except (AttributeError, RuntimeError, ValueError):
            return 1.0
        return value if value > 0.0 else 1.0

    def _timeline_at_source(self, clip, source_seconds: float) -> float:
        """Thời điểm timeline tương ứng một con số trên đồng hồ của file nguồn.

        Mẫu số là tốc độ THỰC đang áp (xem ``_apply_preview_rate``), không phải
        ``clip.speed``: backend có thể làm ngơ với rate ngoài khoảng nó nhận, và
        khi đó playhead phải chạy theo đúng những gì người dùng nghe được.
        """
        in_point = float(getattr(clip, "in_point", 0.0) or 0.0)
        return float(clip.start_time) + max(
            0.0, float(source_seconds) - in_point) / self._clock_rate()

    def _playback_owner_at(self, current_time):
        """Clip đồng hồ tại ``current_time``, bỏ qua track đã tắt tiếng.

        Track muted không được phép làm master clock: nếu có, playhead vẫn chạy
        theo file tiếng của nó nhưng người dùng bấm tắt tiếng rồi vẫn nghe —
        đúng cái bug mà nút loa trên đầu track hứa sẽ không làm.
        """
        import os
        for track in self._playback_tracks():
            if track.is_muted:
                continue
            for clip in track.clips:
                if (clip.start_time <= current_time <= clip.end_time
                        and clip.source_path
                        and os.path.exists(clip.source_path)):
                    return clip
        return None

    def _preview_audio_owner(self, current_time):
        """Clip nào gánh tiếng tại thời điểm này, kèm gain 0..1 của nó.

        Preview chỉ có MỘT QMediaPlayer, nên lúc hai clip chồng nhau vì chuyển
        tiếp không thể hòa hai luồng tiếng như export. Cách gần đúng: nghe theo
        clip có gain cao nhất và đổi người đúng ở điểm crossover.

        Clip tắt tiếng (``audio_muted``) đi theo con đường đó một cách tự nhiên:
        ``transitions.clip_volume`` trả 0.0 nên nó không bao giờ thắng một clip
        còn tiếng, nhưng khi nó là clip duy nhất thì vẫn giữ nhịp — tắt tiếng
        một clip không được quyền làm playhead chạy lệch giờ.
        """
        import os
        model = self.timeline_panel.model
        owner, owner_gain = None, -1.0
        for track in self._playback_tracks():
            if track.is_muted:
                continue
            for clip in track.clips:
                if (clip.media_type not in ("video", "audio")
                        or not (clip.start_time <= current_time < clip.end_time)
                        or not clip.source_path or not os.path.exists(clip.source_path)):
                    continue
                gain = model.transition_gain(clip, current_time)
                if gain > owner_gain:
                    owner, owner_gain = clip, gain
        return owner, max(0.0, min(1.0, owner_gain))

    def _apply_preview_audio(self, current_time):
        """Đổi nguồn ở điểm crossover và dựng volume theo đúng gain của transitions."""
        owner, gain = self._preview_audio_owner(current_time)
        if owner is None:
            self._audio_output.setVolume(1.0)
            return
        if not self._same_media(self._audio_player.source().toLocalFile(),
                                owner.source_path):
            from PySide6.QtCore import QUrl
            self._audio_player.setSource(QUrl.fromLocalFile(owner.source_path))
            seek_ms = int(owner.source_time(current_time) * 1000.0)
            self._audio_player.setPosition(max(0, seek_ms))
            self._audio_player.play()
        self._apply_preview_rate(owner)
        self._audio_output.setVolume(gain)

    def _pre_buffer_active_audio(self):
        """Pre-buffer file âm thanh dưới playhead để phát mượt mà không bị lag giật."""
        if self._play_timer.isActive():
            return

        model = self.timeline_panel.model
        # Trước đây vòng lặp này KHÔNG bỏ qua track.is_muted, nên một track đã
        # tắt tiếng vẫn được nạp làm master clock và phát tiếng khi bấm play.
        active_clip = self._playback_owner_at(model.playhead)
        if active_clip is None:
            for track in self._playback_tracks():
                if track.is_muted:
                    continue
                for clip in track.clips:
                    if clip.source_path and os.path.exists(clip.source_path):
                        active_clip = clip
                        break
                if active_clip:
                    break

        if active_clip is None:
            return

        source_file = active_clip.source_path
        if source_file and active_clip:
            current_source = self._audio_player.source().toLocalFile()
            if not self._same_media(current_source, source_file):
                self._audio_player.setSource(QUrl.fromLocalFile(source_file))

            local_pos_ms = int(active_clip.source_time(model.playhead) * 1000.0)
            self._audio_player.setPosition(max(0, local_pos_ms))
            self._apply_preview_rate(active_clip)
            self._audio_output.setVolume(min(
                1.0, model.transition_gain(active_clip, model.playhead)))

            # Kỹ thuật Pre-buffering: play rồi pause lập tức để hệ thống nạp dữ liệu giải mã vào RAM/GPU
            self._audio_player.play()
            self._audio_player.pause()

    def _sync_canvas_frames_at_time(self, current_time):
        if hasattr(self, "_frame_sync_timer") and self._frame_sync_timer.isActive():
            self._frame_sync_timer.stop()
        """Trích xuất và vẽ khung hình tại thời điểm phát cho toàn bộ clip có áp dụng nội suy Keyframe."""
        if not self._play_timer.isActive():
            self._pre_buffer_active_audio()
            
        from PySide6.QtGui import QPixmap, QTransform
        from core.media_frame import SequentialVideoReader, qimage_from_bgr
        
        # TimelineModel is the sole polling authority. It already filters
        # hidden tracks and returns the compositing order for this playhead.
        active_clips = self.timeline_panel.model.active_visual_clips_at(
            current_time)
        active_ids = {clip.clip_id for clip in active_clips}

        # Chuyển tiếp tính theo pixel canvas — cùng hệ tọa độ FrameComposer dùng
        # lúc xuất (sceneRect của preview cũng chính là frame dự án).
        canvas_rect = self.preview_panel.canvas.sceneRect()
        canvas_w, canvas_h = canvas_rect.width(), canvas_rect.height()

        for clip_id, canvas_item in self.preview_panel.canvas._clip_items.items():
            clip = canvas_item.clip_model
            
            # Kiểm tra xem clip có hoạt động tại thời điểm này không
            if clip_id in active_ids:
                canvas_item.setVisible(True)
                canvas_item.set_transition_state(
                    self.timeline_panel.model.transition_state(
                        clip, current_time, canvas_w, canvas_h))
                
                # Mốc thời gian cục bộ của clip: DUNG mot ham voi export
                # (ClipModel.local_time_at) — khong con phep tru thu cong o day.
                local_time = clip.local_time_at(current_time)
                # source_time dùng riêng cho decoder; keyframe vẫn theo thời gian clip.
                source_time = clip.source_at_local(local_time)
                # Hiệu ứng nhịp tiến độ cần đúng mốc này ở cả preview lẫn export.
                canvas_item.set_local_time(local_time)
                
                # Nội suy động từ hệ thống keyframe
                kf_x = clip.get_value_at_time("x", local_time, clip.transform.x)
                kf_y = clip.get_value_at_time("y", local_time, clip.transform.y)
                kf_scale_x = clip.get_value_at_time("scale_x", local_time, clip.transform.scale_x)
                kf_scale_y = clip.get_value_at_time("scale_y", local_time, clip.transform.scale_y)
                kf_rotation = clip.get_value_at_time("rotation", local_time, clip.transform.rotation)
                kf_opacity = clip.get_value_at_time("opacity", local_time, clip.transform.opacity)
                
                from ui.graphics_canvas_item import TextClipItem
                if isinstance(canvas_item, TextClipItem):
                    canvas_item.apply_keyframe_transform(
                        kf_x, kf_y, kf_scale_x, kf_scale_y,
                        kf_rotation, kf_opacity
                    )
                    canvas_item.update()
                    continue

                # Áp dụng lên toạ độ vị trí trên canvas (image/video/sticker)
                canvas_item.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
                canvas_item.setPos(kf_x, kf_y)
                
                # Tính lại kích thước rect dựa trên scale keyframe (giữ nguyên center)
                base_w = canvas_item._orig_base_w()
                base_h = canvas_item._orig_base_h()
                new_w = base_w * kf_scale_x
                new_h = base_h * kf_scale_y
                canvas_item.prepareGeometryChange()
                canvas_item.setRect(QRectF(-new_w / 2, -new_h / 2, new_w, new_h))
                
                # Chỉ áp dụng rotation qua QTransform (KHÔNG dùng scale ở đây
                # để tránh double-scale)
                t = QTransform()
                t.rotate(kf_rotation)
                canvas_item.setTransform(t)
                canvas_item.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
                
                # Lưu opacity tạm thời để QPainter vẽ, KHÔNG ghi đè model
                canvas_item._keyframe_opacity = kf_opacity
                
                # Trích xuất frame tại thời điểm tương đối cho video
                if clip.media_type == "video" and os.path.exists(clip.source_path):
                    # Decoder tuần tự giống hệt lúc xuất (core.frame_composer):
                    # bản cũ seek mỗi lần playhead = 486 ms/bước trên HDD, tức
                    # chỉ xem được ~2 fps. Bản mới đo được 34 ms/bước.
                    reader = self._video_readers.get(clip.clip_id)
                    if reader is None:
                        reader = SequentialVideoReader(clip.source_path)
                        self._video_readers[clip.clip_id] = reader
                    frame = None if reader.dead else reader.read_bgr(source_time)

                    if frame is not None:
                        # Cập nhật frame động lên canvas item (GIỮ nguyên rect đã tính ở trên)
                        canvas_item.current_frame_pixmap = QPixmap.fromImage(
                            qimage_from_bgr(frame))
                        canvas_item.update()
                    elif not self._play_timer.isActive():
                        # Codec WMV co the Qt/FFmpeg doc duoc ma OpenCV thi
                        # khong: giu cho thao luan (scrub) van con hinh.
                        from core.media_frame import extract_frame
                        pixmap = extract_frame(clip.source_path, source_time)
                        if not pixmap.isNull():
                            canvas_item.current_frame_pixmap = pixmap
                            canvas_item.update()
                else:
                    canvas_item.update()
            else:
                # Ẩn clip nếu không nằm trong phân cảnh thời gian hiện tại
                canvas_item.set_transition_state(None)
                canvas_item.setVisible(False)

    def _apply_theme(self):
        app = QApplication.instance()
        app.setStyleSheet(theme_manager.stylesheet())

    def _on_sidebar_changed(self, key):
        self.library_panel.setVisible(False)
        self.text_presets_panel.setVisible(False)
        self.sticker_presets_panel.setVisible(False)
        self.effects_panel.setVisible(False)

        if key == "library":
            self.library_panel.setVisible(True)
            self.library_panel.tabs.group.buttons()[0].click()
        elif key == "audio":
            self.library_panel.setVisible(True)
            self.library_panel.tabs.group.buttons()[2].click()
        elif key == "text":
            self.text_presets_panel.setVisible(True)
        elif key == "sticker":
            self.sticker_presets_panel.setVisible(True)
        elif key == "effects":
            self.effects_panel.setVisible(True)
            self.effects_panel.tabs.group.buttons()[0].click()
        elif key == "transition":
            self.effects_panel.setVisible(True)
            self.effects_panel.tabs.group.buttons()[1].click()
        elif key == "filter":
            self.effects_panel.setVisible(True)
            self.effects_panel.tabs.group.buttons()[3].click()

    def _on_toggle_timeline(self, visible):
        """Ẩn / Hiện timeline phía dưới."""
        self.timeline_panel.setVisible(visible)

    def _on_timeline_focus(self, enabled):
        """Thu vùng xem xuống mức tối thiểu để timeline chiếm cửa số; bấm lần hai
        trả đúng tỷ lệ người dùng đã kéo trước đó, không phải 70/30 mặc định."""
        sizes = self.work_splitter.sizes()
        total = sum(sizes) or 1
        if enabled:
            self._timeline_restore_sizes = list(sizes)
            top = max(60, int(total * 0.08))
            self.work_splitter.setSizes([top, total - top])
        else:
            restore = self._timeline_restore_sizes
            if restore:
                self.work_splitter.setSizes(restore)

    def _show_shortcuts(self):
        """In đúng registry đã cài ở _install_editor_shortcuts: không có danh
        sách thứ hai để lệch khỏi phím thật."""
        from ui.custom_dialog import CustomDialog
        rows = []
        for sequence, (label, _callback) in sorted(self._editor_bindings.items()):
            rows.append(sequence + "  —  " + label)
        CustomDialog("Phím tắt", chr(10).join(rows), self).exec()

    def _show_about(self):
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        from core import settings
        from core import external_tools
        from ui.custom_dialog import CustomDialog

        ffmpeg = external_tools.find("ffmpeg") or "không tìm thấy"
        ffmpeg_src = external_tools.source("ffmpeg")
        lines = [
            settings.APP_NAME + " " + settings.APP_VERSION,
            "",
            "Trình dựng video chạy trên máy của bạn.",
            "Python-Qt: PySide6 " + pyside_version + " / Qt " + qVersion(),
            "ffmpeg: " + ffmpeg + (" (bản đi kèm)" if ffmpeg_src == "bundled"
                                   else " (từ PATH)" if ffmpeg_src else ""),
            "Thư mục dự án: " + str(settings.get("project_dir")),
            "File cài đặt: " + str(settings.settings_path()),
        ]
        CustomDialog("Về Clinging", chr(10).join(lines), self).exec()

    def _add_text_to_timeline(self):
        """Thêm văn bản mới vào timeline (từ sidebar button)."""
        from core.timeline_model import TrackType
        from core.commands import AddClipCommand
        from core.canvas_utils import calculate_fit_and_center

        model = self.timeline_panel.model
        text_track = None
        for track in model.tracks:
            if track.track_type == TrackType.TEXT:
                text_track = track
                break

        if text_track is None:
            text_track = model.add_track(TrackType.TEXT, "Text 1")

        canvas_w, canvas_h = 1920, 1080
        layout = calculate_fit_and_center(400, 100, canvas_w, canvas_h)

        cmd = AddClipCommand(
            model, text_track.track_id, "Văn bản mới",
            media_type="text",
            start_time=model.playhead,
            duration=5.0,
            name="Văn bản mới"
        )
        self.timeline_panel.undo_stack.push(cmd)

        clip = model.get_clip(cmd._clip_id)
        if clip:
            clip.transform.x = layout['x']
            clip.transform.y = layout['y']
            clip.transform.scale_x = 1.0
            clip.transform.scale_y = 1.0
            clip.name = "Văn bản mới"

        self._sync_canvas()

    def _open_auto_captions(self):
        """Hộp thoại Phụ đề tự động — giữ một instance để không nhân bản worker."""
        from ui.auto_captions_dialog import AutoCaptionsDialog
        dialog = getattr(self, "_captions_dialog", None)
        if dialog is None:
            dialog = AutoCaptionsDialog(self)
            self._captions_dialog = dialog
        dialog.refresh_sources()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _open_subtitle_import(self):
        dialog = self._open_auto_captions()
        dialog._on_import()

    def _open_thumbnail_export(self, initial_path=""):
        """Hộp thoại trích xuất ảnh thu nhỏ — một instance duy nhất.

        Non-modal vi mot lot 2000 anh chay hang chuc giay: khoa ca editor de
        xem thanh tien trinh thi nguoi dung khong lam duoc gi khac.
        """
        from ui.thumbnail_dialog import ThumbnailDialog
        dialog = getattr(self, "_thumbnail_dialog", None)
        if dialog is None:
            dialog = ThumbnailDialog(self)
            self._thumbnail_dialog = dialog
        dialog.prepare(initial_path)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _open_media_split(self, initial_path=""):
        """Hộp thoại cắt một file thành N đoạn ra đĩa — một instance duy nhất.

        Non-modal vi cat mot file 4K dai co the keu hang chuc phut; khoa ca
        editor lai thi nguoi dung khong con duong nao xem tien trinh.
        """
        from ui.split_dialog import SplitDialog
        dialog = getattr(self, "_split_dialog", None)
        if dialog is None:
            dialog = SplitDialog(self)
            self._split_dialog = dialog
        dialog.prepare(initial_path)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _open_media_compress(self, initial_path=""):
        """Hộp thoại nén / tối ưu MỘT file trên đĩa — một instance duy nhất.

        Non-modal vi mot lan ma hoa lai co the keo hang chuc phut tren may cau
        hinh thap; modal thi thanh tien trinh va nut Huy chi de xem khi editor
        da bi khoa lai.
        """
        from ui.compress_dialog import CompressDialog
        dialog = getattr(self, "_compress_dialog", None)
        if dialog is None:
            dialog = CompressDialog(self)
            self._compress_dialog = dialog
        dialog.prepare(initial_path)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _open_recap_overlay(self):
        """Hộp thoại Lớp phủ recap — một instance, cấu hình sống theo dự án."""
        from ui.recap_overlay_dialog import RecapOverlayDialog
        dialog = getattr(self, "_recap_dialog", None)
        if dialog is None:
            dialog = RecapOverlayDialog(self)
            self._recap_dialog = dialog
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _on_recap_overlay_changed(self, _settings):
        self.preview_panel.canvas.viewport().update()

    def _open_keyframe_graph(self, clip_id):
        """Do thi duong cong keyframe — MỘT instance duy nhat, doi clip.

        Non-modal vi chinh do thi phai thay playhead chay va preview doi theo
        trong khi nguoi dung keo moc; mo mot hop thoai moi cho tung clip thi
        man hinh ngap hop thoai.
        """
        from ui.keyframe_graph_dialog import KeyframeGraphDialog
        dialog = getattr(self, "_graph_dialog", None)
        if dialog is None:
            dialog = KeyframeGraphDialog(self, clip_id)
            self._graph_dialog = dialog
        else:
            dialog.set_clip(clip_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _auto_save(self):
        """Tự động lưu trạng thái project vào file .clinq hiện tại."""
        from core.project_storage import ProjectManager
        pm = ProjectManager()
        if not pm.project_path:
            # Chưa có project → lưu autosave cũ
            from core.project_storage import save_project
            ratio_key = self.timeline_panel.header.combo_aspect_ratio.currentText()
            ratio_key = ratio_key.split(" - ")[0] if " - " in ratio_key else "16:9"
            save_project(
                self.timeline_panel.model,
                aspect_ratio=ratio_key,
                playhead=self.timeline_panel.model.playhead
            )
            return

        ratio_key = self.timeline_panel.header.combo_aspect_ratio.currentText()
        ratio_key = ratio_key.split(" - ")[0] if " - " in ratio_key else "16:9"

        # Lấy resolution từ project_meta
        resolution = pm.project_meta.get("resolution", {"width": 1920, "height": 1080})
        fps = pm.project_meta.get("fps", 30)

        pm.save(
            self.timeline_panel.model,
            resolution=resolution,
            fps=fps,
            aspect_ratio=ratio_key,
        )

    def _load_autosave(self):
        """Tải lại trạng thái project từ autosave nếu có."""
        from core.project_storage import (
            load_project, restore_model, has_autosave,
            ProjectManager, load_project_from_file, restore_model_from_clinq
        )

        pm = ProjectManager()

        # Ưu tiên: nếu có project_path đã lưu trước đó → load từ .clinq
        if pm.project_path and os.path.exists(pm.project_path):
            project = load_project_from_file(pm.project_path)
            if project:
                restore_model_from_clinq(
                    self.timeline_panel.model, project,
                    media_roots=[os.path.dirname(pm.project_path)])
                self.restore_library_from_project(project)
                ratio = project.get("project_meta", {}).get("aspect_ratio", "16:9")
                ratio_display = {
                    "16:9": "16:9 - Ngang chuẩn",
                    "19:6": "19:6 - Siêu rộng",
                    "9:16": "9:16 - Đứng Shorts/Tiktok",
                    "1:1": "1:1 - Vuông",
                    "4:3": "4:3 - Cổ điển",
                }.get(ratio, "16:9 - Ngang chuẩn")
                self.timeline_panel.header.combo_aspect_ratio.setCurrentText(ratio_display)
                self.is_project_empty = False
                self._sync_canvas()
                return

        # Fallback: load từ autosave cũ
        if not has_autosave():
            return
        project = load_project()
        if not project:
            return

        ratio = project.get("aspect_ratio", "16:9")
        ratio_display = {
            "16:9": "16:9 - Ngang chuẩn",
            "19:6": "19:6 - Siêu rộng",
            "9:16": "9:16 - Đứng Shorts/Tiktok",
            "1:1": "1:1 - Vuông",
            "4:3": "4:3 - Cổ điển",
        }.get(ratio, "16:9 - Ngang chuẩn")
        self.timeline_panel.header.combo_aspect_ratio.setCurrentText(ratio_display)

        restore_model(self.timeline_panel.model, project)
        self.restore_library_from_project(project)
        self.is_project_empty = False
        self._sync_canvas()

    def _on_export(self):
        from ui.export_dialog import ExportDialog
        dialog = ExportDialog(self.timeline_panel.model, parent=self)
        preset = self.property("preferredExportResolution")
        if preset:
            dialog.select_resolution_preset(str(preset))
            self.setProperty("preferredExportResolution", None)
        dialog.exec()
        self._toast_export_result(dialog)

    def _toast_export_result(self, dialog):
        """Toast "mở file" rơi lại trên cửa sổ editor nếu hộp thoại đã đóng
        mà người dùng chưa mở file. Tách thành hàm riêng để probe gọi đúng
        duong nay ma khong phai mo hop thoai modal.

        Da bam "Mo file" o hop thoai thi khong lap lai: hai banner cung mot
        hanh dong la hai lan ngan nguoi dung lam viec cua ho.
        """
        path = getattr(dialog, "exported_path", "")
        if path and not getattr(dialog, "file_opened", False):
            from widgets.common import Toast, open_local_file
            Toast.popup(self, "Xuất video xong", os.path.basename(path),
                        icon_name="fa6s.circle-check", action_label="Mở file",
                        action=lambda: open_local_file(path))

    def _on_save(self):
        """Lưu dự án vào file .clinq hiện tại."""
        from core.project_storage import ProjectManager
        pm = ProjectManager()

        ratio_key = self.timeline_panel.header.combo_aspect_ratio.currentText()
        ratio_key = ratio_key.split(" - ")[0] if " - " in ratio_key else "16:9"

        if pm.project_path:
            resolution = pm.project_meta.get("resolution", {"width": 1920, "height": 1080})
            fps = pm.project_meta.get("fps", 30)
            success = pm.save(
                self.timeline_panel.model,
                resolution=resolution,
                fps=fps,
                aspect_ratio=ratio_key,
            )
            if success:
                QMessageBox.information(self, "Lưu dự án",
                    f"Đã lưu dự án vào:\n{pm.project_path}")
            else:
                QMessageBox.warning(self, "Lỗi", "Không thể lưu dự án.")
        else:
            # Chưa có project → dùng autosave
            self._auto_save()
            QMessageBox.information(self, "Lưu dự án", "Đã lưu dự án (autosave).")

    def _detect_media_aspect_ratio(self, file_path, item_type):
        """Đọc kích thước thực tế của file media bằng OpenCV / QPixmap và quy đổi về Aspect Ratio combobox string."""
        import cv2
        from PySide6.QtGui import QPixmap
        import os
        
        from core.media_locator import locate

        width, height = 1920, 1080

        # Duong dan da dinh vi luc mo du an; day chi con truong hop doi ten sau
        # khi mo. Khong di bo thu muc hien hanh (cwd cua exe da cai co the la
        # System32).
        actual_path = locate(file_path) or file_path

        try:
            if item_type == "video" and os.path.exists(actual_path):
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
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
            elif item_type == "image" and os.path.exists(actual_path):
                pix = QPixmap(actual_path)
                if not pix.isNull():
                    width = pix.width()
                    height = pix.height()
        except Exception as e:
            pass
            
        if height == 0:
            return "16:9 - Ngang chuẩn"
            
        ratio = width / height
        
        # So khớp tỷ lệ với sai số nhỏ cho phép
        if abs(ratio - (16/9)) < 0.1:
            return "16:9 - Ngang chuẩn"
        elif abs(ratio - (9/16)) < 0.1:
            return "9:16 - Đứng Shorts/Tiktok"
        elif abs(ratio - 1.0) < 0.1:
            return "1:1 - Vuông"
        elif abs(ratio - (4/3)) < 0.1:
            return "4:3 - Cổ điển"
            
        return "16:9 - Ngang chuẩn"
