"""
ui/graphics/clip_item.py
Đối tượng clip trên QGraphicsScene — thành phần cốt lõi của Timeline.

Mỗi ClipItem tương ứng với một ClipModel và hiển thị:
  - Body gradient (màu theo loại media)
  - Tên file
  - Resize handles ở 2 đầu (trim in/out)
  - Hover highlight + selection border
  - Context menu (cắt, xóa, nhân bản, tách tiếng)
"""

import math
import os

from PySide6.QtCore import Qt, QRectF, QPointF, QThread, Signal, QObject
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient,
    QCursor, QPainterPath, QPixmap, QImage
)
from PySide6.QtWidgets import (
    QGraphicsRectItem, QGraphicsItem, QMenu, QGraphicsSceneMouseEvent, QGraphicsPolygonItem
)

from core.timeline_model import (
    ClipModel, TIMELINE_RULER_HEIGHT,
    TIMELINE_TRACK_TOP_PADDING, TIMELINE_TRACK_GAP,
)
from core.time_mapper import TimePixelMapper
from core.keyframe_manager import (EASINGS, EASE_LABELS, apply_ease,
                                   frame_ease, frame_time, frame_value,
                                   make_frame, normalize_ease)
from core import keyframe_graph, settings, transitions
from widgets.common import font_icon, icon_pixmap

# Màu gradient cho từng loại media
CLIP_COLORS = {
    "video":   ("#2563EB", "#1D4ED8"),   # xanh dương
    "audio":   ("#EA580C", "#C2410C"),   # cam
    "image":   ("#059669", "#047857"),   # xanh lá
    "text":    ("#9333EA", "#7C3AED"),   # tím
    "effect":  ("#DB2777", "#BE185D"),   # hồng
    "sticker": ("#0891B2", "#0E7490"),   # teal
}

# Chiều rộng vùng resize handle
HANDLE_WIDTH = 8.0
THUMB_CELL_WIDTH = 72.0
WAVEFORM_COLUMN_WIDTH = 2.0


class ClipItem(QGraphicsRectItem):
    """
    Clip trên Timeline Scene.

    Features:
        - Drag to move (ItemIsMovable + snap)
        - Resize handles ở 2 đầu (trim in/out)
        - Visual: gradient body, tên file, selection border
        - Context menu: cắt, xóa, nhân bản, đổi tên
        - itemChange() → snap logic + giới hạn di chuyển

    Attributes:
        clip_model: ClipModel liên kết
        mapper: TimePixelMapper dùng chung
    """

    def __init__(self, clip_model: ClipModel, mapper: TimePixelMapper,
                 track_y: float = 0, track_height: float = 60,
                 parent=None):
        super().__init__(parent)
        self.clip_model = clip_model
        self._mapper = mapper
        self._track_y = track_y
        self._track_height = track_height

        # Tính geometry từ model
        self._sync_rect_from_model()

        # Interaction flags
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10)   # Trên track lane

        # Bộ đệm thumbnail và mảng biên độ âm thanh cho audio/video
        self.thumbnail_cache = []
        self.audio_amplitudes = []
        
        # Danh sách chứa các đối tượng KeyframeNode đồ họa
        self._keyframe_nodes = []
        
        # Bắt đầu trích xuất ngầm để tránh đơ giao diện chính
        self._start_media_extraction()

        # Tạo ban đầu các keyframe nodes từ model
        self.sync_keyframe_nodes_from_model()

        # Internal state
        self._hover = False
        self._resizing = ""         # "", "left", "right"
        self._drag_start_x = 0.0
        self._drag_start_time = 0.0
        self._drag_start_duration = 0.0
        self._original_start = 0.0
        self._original_duration = 0.0
        self._original_in_point = 0.0

    # ── Audio state ─────────────────────────────────────────────

    def _audio_silent(self) -> bool:
        """Cây sóng có đang nói dối không? True nếu clip này im lặng.

        Đọc thẳng từ model thay vì một cờ bản địa: hai cờ ``is_audio_muted`` /
        ``is_video_hidden`` từng được TrackHeader ghi mỗi ngày nhưng không có ai
        đọc, nên nút loa trên hàng và sóng trên clip có thể bất đồng mà không lỗi
        nào lộ ra. Im lặng có hai nguồn — tắt riêng clip hoặc tắt cả hàng — và
        người dùng phải thấy cả hai.
        """
        if bool(getattr(self.clip_model, "audio_muted", False)):
            return True
        scene = self.scene()
        model = getattr(scene, "model", None) if scene is not None else None
        if model is None:
            return False
        track = model.get_track(self.clip_model.track_id)
        return bool(track is not None and track.is_muted)

    # ── Sync Model ↔ Rect ───────────────────────────────────────

    def _sync_rect_from_model(self):
        """Cập nhật rect từ dữ liệu model."""
        x = self._mapper.time_to_pixel(self.clip_model.start_time)
        w = self._mapper.duration_to_width(self.clip_model.duration)
        padding_v = 3.0
        self.setRect(x, self._track_y + padding_v,
                     w, self._track_height - padding_v * 2)

    def set_track_position(self, track_y: float, track_height: float):
        """Cập nhật vị trí Y khi track thay đổi."""
        self._track_y = track_y
        self._track_height = track_height
        self._sync_rect_from_model()
        self._sync_transition_tooltip()

    # ── Transition marker ───────────────────────────────────────

    def _transition_band(self):
        """(kind, QRectF) vùng chuyển tiếp trên clip này, hoặc None.

        Hình học hỏi TimelineModel chứ không tự tính từ clip.transition: cửa sổ
        thật có thể ngắn hơn duration đã lưu sau khi trim clip bên trái, và đánh
        dấu theo số cũ sẽ tô lên đoạn mà preview chẳng còn chồng hai clip.
        """
        scene = self.scene()
        model = getattr(scene, "model", None) if scene is not None else None
        if model is None:
            return None
        band = model.transition_band(self.clip_model)
        if band is None:
            return None
        kind, start, end = band
        rect = self.rect()
        left = max(rect.left(),
                   self._mapper.time_to_pixel(max(0.0, min(start, end))))
        right = min(rect.right(),
                    self._mapper.time_to_pixel(max(start, end)))
        if right - left <= 0.5:
            return None
        return kind, QRectF(left, rect.top(), right - left, rect.height())

    def _sync_transition_tooltip(self):
        from core import transitions
        name = transitions.name_of(self.clip_model)
        if not name:
            self.setToolTip("")
            return
        duration = transitions.duration_of(self.clip_model)
        if transitions.is_junction(name):
            note = ("Chồng lấn %.2fs với clip liền trước." % duration
                    if self._transition_band() is not None else
                    "%.2fs nhưng chưa có clip liền trước để nối — chưa vẽ gì cả."
                    % duration)
        else:
            note = "Phai %.2fs trên chính clip này." % duration
        self.setToolTip("%s\n%s" % (name, note))

    def _paint_transition_band(self, painter: QPainter):
        band = self._transition_band()
        if band is None:
            return
        kind, rect = band
        painter.setClipping(False)
        if kind == "overlap":
            painter.fillRect(rect, QColor(64, 224, 208, 46))
            pen = QPen(QColor("#40E0D0"), 1.5)
            painter.setPen(pen)
            # Hai mép của cửa sổ: chỗ chuyển tiếp BẮT ĐẦU và chỗ nó kết thúc.
            painter.drawLine(QPointF(rect.left(), rect.top()),
                             QPointF(rect.left(), rect.bottom()))
            painter.drawLine(QPointF(rect.right(), rect.top()),
                             QPointF(rect.right(), rect.bottom()))
            return
        # Fade In/Out: vẽ đúng chiều phai, đậm ở mép ngoài và nhạt dần vào trong.
        grad = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
        shade = QColor(0, 0, 0, 150)
        clear = QColor(0, 0, 0, 0)
        if kind == "in":
            grad.setColorAt(0.0, shade)
            grad.setColorAt(1.0, clear)
            edge_x = rect.left()
        else:
            grad.setColorAt(0.0, clear)
            grad.setColorAt(1.0, shade)
            edge_x = rect.right()
        painter.fillRect(rect, QBrush(grad))
        painter.setPen(QPen(QColor("#40E0D0"), 1.5))
        painter.drawLine(QPointF(edge_x, rect.top()), QPointF(edge_x, rect.bottom()))

    # ── Paint ───────────────────────────────────────────────────

    def _waveform_gain(self, progress: float) -> float:
        """Â lượng thực của clip tại một cột sóng (0 = đầu clip, 1 = cuối clip).

        Cây sóng phải nhỏ lại khi người dùng kéo Âm lượng hay Fade, nếu không
        timeline nói "tôi còn 100% tiếng" trong khi loa đã vặn xuống 20%.

        RIÊNG cờ tắt tiếng thì không được ăn vào đây: clip muted đổi sang màu xám
        để báo "không có tiếng", còn hình dạng biên độ vẫn phải giữ để người dùng
        thấy đúng đoạn mình vừa im lặng (nhân 0 thì sóng biến mất hẳn).
        """
        clip = self.clip_model
        at = float(clip.start_time) + max(0.0, min(1.0, progress)) * float(clip.duration)
        return transitions.local_gain(clip, at, ignore_mute=True)

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.rect()
        if rect.width() < 2:
            return

        painter.setRenderHint(QPainter.Antialiasing)

        # ── 1. Vẽ nền mờ (Background) ──
        bg_color = QColor("#1C1D24")
        painter.fillRect(rect, bg_color)

        # ── 2. Xử lý hiển thị theo từng loại tệp (Thumbnail / Waveform) ──
        media_type = self.clip_model.media_type
        
        # Chỉ dùng cache đã trích xuất bất đồng bộ. Tuyệt đối không
        # đọc file, os.walk hay chạy FFmpeg trong paint(): paint có thể được
        # Qt gọi hàng trăm lần mỗi giây khi cuộn/zoom.
        thumbnails = self.thumbnail_cache

        if (media_type in ["video", "image"] and thumbnails and
                settings.get("show_thumbnails")):
            # Thumbnail cells keep a fixed display width. Zoom changes the
            # number of visible cells and their sampled source time; it never
            # stretches one bitmap across the whole clip.
            target_h = max(1, int(rect.height()))

            painter.save()
            # Bo góc clip để hình ảnh không tràn ra ngoài
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            painter.setClipPath(path)

            # Virtualized paint: bắt đầu ngay ô thumbnail đầu tiên giao
            # viewport, không lặp qua toàn bộ clip dài hàng giờ.
            visible = option.exposedRect.intersected(rect)
            first_cell = max(
                0, int((visible.left() - rect.left()) // THUMB_CELL_WIDTH))
            last_cell = int((visible.right() - rect.left()) //
                            THUMB_CELL_WIDTH) + 1
            for cell_index in range(first_cell, last_cell + 1):
                current_x = rect.left() + cell_index * THUMB_CELL_WIDTH
                if current_x >= rect.right():
                    break
                cell_width = min(THUMB_CELL_WIDTH,
                                 rect.right() - current_x)
                progress = ((current_x + cell_width * 0.5 - rect.left()) /
                            max(1.0, rect.width()))
                frame_index = max(0, min(
                    len(thumbnails) - 1,
                    int(round(progress * (len(thumbnails) - 1))),
                ))
                frame = thumbnails[frame_index]
                source = QRectF(frame.rect())
                target_aspect = cell_width / max(1.0, target_h)
                source_aspect = source.width() / max(1.0, source.height())
                if source_aspect > target_aspect:
                    crop_width = source.height() * target_aspect
                    source.setLeft(source.center().x() - crop_width / 2.0)
                    source.setWidth(crop_width)
                elif source_aspect < target_aspect:
                    crop_height = source.width() / max(0.001, target_aspect)
                    source.setTop(source.center().y() - crop_height / 2.0)
                    source.setHeight(crop_height)
                painter.drawPixmap(
                    QRectF(current_x, rect.top(), cell_width, target_h),
                    frame, source,
                )
            painter.restore()
            
        elif (media_type == "audio" and self.audio_amplitudes and
                settings.get("show_waveform")):
            # Waveform thật đã downsample và cache bởi worker.
            amplitudes = self.audio_amplitudes
            silent = self._audio_silent()
            # Sóng xám = không có tiếng. Giữ nguyên biên độ để người dùng vẫn
            # thấy hình dạng âm thanh mình đang tắt.
            painter.setPen(QPen(QColor("#8a8a92") if silent else
                                QColor("#00FFCC"), 1.2))
            visible = option.exposedRect.intersected(rect)
            sample_count = len(amplitudes)
            first_column = max(0, int((visible.left() - rect.left()) /
                                      WAVEFORM_COLUMN_WIDTH))
            last_column = int((visible.right() - rect.left()) /
                              WAVEFORM_COLUMN_WIDTH) + 1
            for column in range(first_column, last_column + 1):
                x = rect.left() + column * WAVEFORM_COLUMN_WIDTH
                if x > rect.right():
                    break
                progress = (x - rect.left()) / max(1.0, rect.width())
                sample_index = min(sample_count - 1,
                                   max(0, int(progress * sample_count)))
                amp = amplitudes[sample_index] * self._waveform_gain(progress)
                line_h = (rect.height() - 10) * amp
                y1 = rect.y() + (rect.height() - line_h) / 2
                y2 = y1 + line_h
                painter.drawLine(int(x), int(y1), int(x), int(y2))
        else:
            # Fallback tô màu trơn mờ nhẹ cho Text/Sticker/Effect
            colors = CLIP_COLORS.get(media_type, CLIP_COLORS["video"])
            color1 = QColor(colors[0])
            painter.fillRect(rect, QColor(color1.red(), color1.green(), color1.blue(), 100))

        # Video clips combine a thumbnail strip with their embedded-audio
        # waveform in a compact band, like professional NLE timelines.
        if (media_type == "video" and self.audio_amplitudes and
                settings.get("show_waveform")):
            amplitudes = self.audio_amplitudes
            band_h = min(14.0, max(8.0, rect.height() * 0.28))
            band = QRectF(rect.left(), rect.bottom() - band_h,
                          rect.width(), band_h)
            painter.fillRect(band, QColor(5, 13, 20, 155))
            painter.setPen(QPen(QColor("#8a8a92") if self._audio_silent()
                                else QColor("#67E8D5"), 1.0))
            visible = option.exposedRect.intersected(band)
            sample_count = len(amplitudes)
            first_column = max(0, int((visible.left() - band.left()) /
                                      WAVEFORM_COLUMN_WIDTH))
            last_column = int((visible.right() - band.left()) /
                              WAVEFORM_COLUMN_WIDTH) + 1
            for column in range(first_column, last_column + 1):
                x = band.left() + column * WAVEFORM_COLUMN_WIDTH
                if x > band.right():
                    break
                progress = (x - band.left()) / max(1.0, band.width())
                sample_index = min(sample_count - 1,
                                   max(0, int(progress * sample_count)))
                amp = amplitudes[sample_index] * self._waveform_gain(progress)
                line_h = max(1.0, (band.height() - 3.0) * amp)
                center_y = band.center().y()
                painter.drawLine(int(x), int(center_y - line_h / 2.0),
                                 int(x), int(center_y + line_h / 2.0))

        # ── 3. Hover / Selection overlay ──
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        if self.isSelected():
            painter.fillPath(path, QColor(255, 255, 255, 30))
        elif self._hover:
            painter.fillPath(path, QColor(255, 255, 255, 15))

        # ── 4. Border (Viền trắng sắc nét khi được chọn) ──
        if self.isSelected():
            painter.setPen(QPen(QColor("#40E0D0"), 2))
        elif self._hover:
            painter.setPen(QPen(QColor("#2C7D73"), 1.5))
        else:
            painter.setPen(QPen(QColor("#3A3D4E"), 1))
        painter.drawRoundedRect(rect, 4, 4)

        # ── 5. Tên clip (Văn bản đè lên trên) ──
        if rect.width() > 35:
            painter.save()
            painter.setClipPath(path)
            font = QFont("Segoe UI", 8)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            
            # Đổ bóng nhẹ cho text dễ đọc trên ảnh nền
            painter.setPen(QColor(0, 0, 0, 180))
            text_rect = rect.adjusted(9, 2, -7, 0)
            elided = self.clip_model.name
            
            fm = painter.fontMetrics()
            available = int(text_rect.width())
            if fm.horizontalAdvance(elided) > available:
                elided = fm.elidedText(elided, Qt.ElideRight, available)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
            
            # Chữ trắng chính
            painter.setPen(QColor("#FFFFFF"))
            text_rect_main = rect.adjusted(8, 0, -8, 0)
            painter.drawText(text_rect_main, Qt.AlignVCenter | Qt.AlignLeft, elided)
            painter.restore()

        # ── 6. Thời lượng nhỏ góc phải ──
        if rect.width() > 80:
            dur = self.clip_model.duration
            dur_text = f"{dur:.1f}s"
            small_font = QFont("Segoe UI", 7)
            painter.setFont(small_font)
            painter.setPen(QColor(255, 255, 255, 180))
            dur_rect = rect.adjusted(0, 0, -6, 0)
            painter.drawText(dur_rect, Qt.AlignVCenter | Qt.AlignRight, dur_text)

        # ── 7. Huy hiệu hiệu ứng (Effect badge) ──
        # Effect được lưu theo clip (clip.effects) chứ không phải track riêng,
        # nên hiển thị ngay trên clip để người dùng biết clip đã có hiệu ứng.
        effects = getattr(self.clip_model, "effects", None)
        if effects:
            count = len(effects)
            painter.setClipping(False)
            if rect.width() > 44:
                glyph = icon_pixmap("fa6s.wand-magic-sparkles", 10, "#FFFFFF")
                text = str(count) if count > 1 else ""
                badge_font = QFont("Segoe UI", 7)
                badge_font.setBold(True)
                painter.setFont(badge_font)
                tw = (painter.fontMetrics().horizontalAdvance(text)
                      if text else 0)
                bw = 5 + 10 + (3 + tw if text else 0) + 5
                bh = 14.0
                badge_rect = QRectF(rect.right() - bw - 4, rect.top() + 4, bw, bh)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#DB2777"))
                painter.drawRoundedRect(badge_rect, 7, 7)
                painter.drawPixmap(int(badge_rect.left() + 5),
                                   int(badge_rect.center().y() - 5), glyph)
                if text:
                    painter.setPen(QColor("#FFFFFF"))
                    painter.drawText(
                        QRectF(badge_rect.left() + 18, badge_rect.top(),
                               bw - 18, bh),
                        Qt.AlignVCenter | Qt.AlignLeft, text)
            else:
                # Clip quá hẹp → chỉ chấm tròn hồng báo hiệu
                dot = QRectF(rect.right() - 10, rect.top() + 4, 6, 6)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#DB2777"))
                painter.drawEllipse(dot)

        # ── 7.5 Dải chuyển tiếp: chồng lấn ở mép trái clip, hoặc dải Fade In/Out
        # ở chính mép mà nó phai. Người dùng cần thấy đúng đoạn timeline mà
        # preview vẽ hai khung hình một lúc.
        self._paint_transition_band(painter)

        # ── 8. Resize handles (hiển thị khi hover) ──
        if self._hover or self.isSelected():
            handle_color = QColor(255, 255, 255, 80)
            # Handle trái
            hl = QRectF(rect.x(), rect.y(), HANDLE_WIDTH, rect.height())
            painter.fillRect(hl, handle_color)
            # Handle phải
            hr = QRectF(rect.right() - HANDLE_WIDTH, rect.y(),
                        HANDLE_WIDTH, rect.height())
            painter.fillRect(hr, handle_color)

        painter.setClipping(False)

    # ── Mouse Interaction ───────────────────────────────────────

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.setCursor(Qt.OpenHandCursor)
        self.update()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event):
        """Đổi cursor tùy vào vị trí hover (resize handle hay body)."""
        rect = self.rect()
        local_x = event.pos().x()

        if local_x < rect.x() + HANDLE_WIDTH:
            self.setCursor(Qt.SizeHorCursor)
        elif local_x > rect.right() - HANDLE_WIDTH:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene and hasattr(scene, "_snap"):
                scene._snap.begin_drag(scene.model, self.clip_model.clip_id)
            rect = self.rect()
            local_x = event.pos().x()

            self._drag_start_x = event.scenePos().x()
            self._drag_start_time = self.clip_model.start_time
            self._drag_start_duration = self.clip_model.duration
            self._original_start = self.clip_model.start_time
            self._original_duration = self.clip_model.duration
            self._original_in_point = self.clip_model.in_point

            if local_x < rect.x() + HANDLE_WIDTH:
                self._resizing = "left"
                self.setCursor(Qt.SizeHorCursor)
                event.accept()
                return
            elif local_x > rect.right() - HANDLE_WIDTH:
                self._resizing = "right"
                self.setCursor(Qt.SizeHorCursor)
                event.accept()
                return
            else:
                self._resizing = ""
                self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._resizing:
            self._handle_resize(event)
            return
        # Normal drag — let itemChange() handle snapping
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            if self._resizing:
                # Phát command cho undo stack thông qua scene
                scene = self.scene()
                if scene and hasattr(scene, "clip_resized"):
                    scene.clip_resized.emit(
                        self.clip_model.clip_id,
                        self._original_start,
                        self._original_duration,
                        self.clip_model.start_time,
                        self.clip_model.duration,
                        self._original_in_point,
                        self.clip_model.in_point,
                    )
                # Cửa sổ nguồn vừa đổi thật sự (trước đó mỗi lần mouseMove chỉ
                # là dự đoán). Refresh ở đây thay vì trong update_from_model để
                # không dựng/xem lại thread giải mã mỗi 60 lần kéo chuột.
                self.refresh_media_extraction()
                self._resizing = ""
            else:
                # Di chuyển xong — phát command
                # itemChange already tracks the true time in the model while the
                # item itself carries a temporary drag offset. rect().x() is the
                # pre-drag coordinate and previously bypassed ripple collision.
                new_time = self.clip_model.start_time
                if abs(new_time - self._original_start) > 0.01:
                    scene = self.scene()
                    if scene and hasattr(scene, "clip_move_finished"):
                        scene.clip_move_finished.emit(
                            self.clip_model.clip_id,
                            self._original_start,
                            new_time
                        )
                    # The command above synchronously commits model geometry.
                    # Remove the temporary QGraphicsItem drag offset so rect and
                    # model do not get counted twice on the next drag/paint.
                    self.setPos(0.0, TIMELINE_RULER_HEIGHT)
            self.setCursor(Qt.OpenHandCursor)
            scene = self.scene()
            if scene and hasattr(scene, "_snap"):
                scene._snap.end_drag()

        super().mouseReleaseEvent(event)

    def _handle_resize(self, event: QGraphicsSceneMouseEvent):
        """Xử lý kéo resize handle trái/phải."""
        delta_px = event.scenePos().x() - self._drag_start_x
        delta_time = self._mapper.width_to_duration(delta_px)
        speed = self.clip_model.speed_factor
        if self._resizing == "right":
            # Kéo handle phải → thay đổi duration
            new_duration = max(0.1, self._drag_start_duration + delta_time)
            if (self.clip_model.media_type in ("video", "audio") and
                    self.clip_model.source_duration > 0.0):
                # Phần nguồn bị ăn là duration x speed, nên trần của thanh trượt
                # phải chia cho tốc độ — nếu không clip 2x kéo dài gấp đôi nguồn.
                available = max(
                    0.1,
                    (self.clip_model.source_duration -
                     self.clip_model.in_point) / speed)
                new_duration = min(new_duration, available)
            self.clip_model.duration = new_duration
            self.clip_model.refresh_out_point()

        elif self._resizing == "left":
            # Anchor the old right edge while X and Width change together.
            old_right = self._drag_start_time + self._drag_start_duration
            min_duration = max(0.1, 10.0 / self._mapper.px_per_sec)
            lower_bound = 0.0
            generated_media = self.clip_model.media_type in (
                "image", "text", "sticker", "effect")
            if not generated_media:
                # A decoded clip cannot reveal media before source time zero.
                lower_bound = max(
                    0.0, self._drag_start_time -
                    self._original_in_point / speed)
            new_start = self._drag_start_time + delta_time
            new_start = max(lower_bound,
                            min(new_start, old_right - min_duration))
            new_duration = old_right - new_start
            self.clip_model.start_time = new_start
            self.clip_model.duration = new_duration
            if generated_media:
                self.clip_model.in_point = self._original_in_point
            else:
                consumed = (new_start - self._drag_start_time) * speed
                self.clip_model.in_point = max(
                    0.0, self._original_in_point + consumed)
            self.clip_model.refresh_out_point()

        self.prepareGeometryChange()
        self._sync_rect_from_model()
        self.update()

    # ── itemChange (Snap + Constrain) ───────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = QPointF(value)
            
            # Cho phép di chuyển trục Y để chuyển đổi giữa các track
            scene = self.scene()
            model = scene.model
            
            # Tính toán track dựa trên vị trí Y tương đối
            ruler_height = TIMELINE_RULER_HEIGHT
            track_top_padding = getattr(
                scene, "TRACK_TOP_PADDING", TIMELINE_TRACK_TOP_PADDING)
            gap = TIMELINE_TRACK_GAP
            
            # Toạ độ Y tuyệt đối trong scene
            absolute_y = self.rect().y() + new_pos.y()
            relative_y = max(
                0.0, absolute_y - ruler_height - track_top_padding)

            # Track có thể cao thấp khác nhau. Dùng cùng phép cộng
            # dồn với HeaderScene/TimelineScene để không lệch hàng.
            track_index = max(0, len(model.tracks) - 1)
            lane_top = 0.0
            target_lane_top = 0.0
            for index, candidate in enumerate(model.tracks):
                lane_bottom = lane_top + candidate.height + gap
                if relative_y < lane_bottom:
                    track_index = index
                    target_lane_top = lane_top
                    break
                lane_top = lane_bottom
            else:
                target_lane_top = sum(t.height + gap for t in model.tracks[:-1])
            
            # Đồng bộ thay đổi track trong model
            target_track = model.tracks[track_index]
            from core.timeline_model import track_accepts_media
            if not track_accepts_media(target_track.track_type, self.clip_model.media_type):
                current_track = model.get_track(self.clip_model.track_id)
                if current_track in model.tracks:
                    track_index = model.tracks.index(current_track)
                    target_track = current_track
            if target_track.track_id != self.clip_model.track_id:
                # Di chuyển clip sang track mới trong model
                current_track = model.get_track(self.clip_model.track_id)
                if current_track:
                    # Xoá khỏi track cũ
                    if self.clip_model in current_track.clips:
                        current_track.clips.remove(self.clip_model)
                    # Gán track mới
                    self.clip_model.track_id = target_track.track_id
                    target_track.clips.append(self.clip_model)

                    # Cập nhật ngay render order trên Canvas. Không dùng thời
                    # điểm add item làm thứ tự vẽ.
                    model._normalize_track_layers()
                    model.tracksReordered.emit()

                    # Phát signal cập nhật layout
                    scene._relayout_tracks()

            # Khóa Y về toạ độ của track tương ứng để clip thẳng hàng trên lane
            target_y = (ruler_height + track_top_padding
                        + target_lane_top + 4.0)
            new_pos.setY(target_y - self.rect().y())

            # Cập nhật model time từ pixel position
            new_x = self.rect().x() + new_pos.x()
            new_time = max(0.0, self._mapper.pixel_to_time(new_x))

            # Gọi snap engine thông qua scene
            if scene and hasattr(scene, "request_snap"):
                snap_result = scene.request_snap(
                    new_time,
                    new_time + self.clip_model.duration,
                    self.clip_model.clip_id
                )
                if snap_result:
                    new_time = snap_result.snapped_time
                    new_x = self._mapper.time_to_pixel(new_time)
                    new_pos.setX(new_x - self.rect().x())

            self.clip_model.start_time = new_time
            return new_pos

        return super().itemChange(change, value)

    # ── Context Menu ────────────────────────────────────────────

    def _build_context_menu(self):
        """Tao menu chu phai va tra ve (menu, [Cắt, Nhân bản, (Tách tiếng), (Đồ thị), Xóa]).

        "Tách âm thanh" chi co voi clip video co nguon va con tieng; "Đồ thị đường
        cong" chi co khi clip dang co keyframe. nen do dai danh sach khong co dinh
        — contextMenuEvent khong duoc dinh vi theo index, ma theo `action.data()`.

        Tach khoi contextMenuEvent vi menu.exec() mo event loop modal: khong
        the goi no trong probe kiem icon. Nay gate goi ham nay dung duong cua
        app, van kiem duoc QIcon cua tung muc.
        """
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #232323; color: #D8DCE0;
                border: 1px solid #3A3A3A; border-radius: 9px;
                padding: 6px;
            }
            QMenu::item { padding: 8px 24px 8px 12px; border-radius: 6px; }
            QMenu::item:selected { background: rgba(64, 224, 208, 0.16); color: #EAFFFB; }
            QMenu::separator { height: 1px; background: #3A3A3A; margin: 6px 4px; }
        """)

        def add(key, glyph, label, color="#D8DCE0"):
            action = menu.addAction(font_icon(glyph, color), label)
            action.setData(key)
            return action

        actions = [
            add("split", "fa6s.scissors", "Cắt tại Playhead"),
            add("duplicate", "fa6s.clone", "Nhân bản clip"),
        ]
        # Clip video da tat tieng thi khong con tieng de tach: net them mot hang
        # audio im lang roi + tat mot cai da im san la mot khong co gi de nghe.
        if self._detachable_audio_clip():
            actions.append(add("detach_audio", "fa6s.wave-square",
                               "Tách âm thanh"))
        # Do thi khong co gi de xem voi clip chua co moc nao — mo len chi thay
        # mot khung trong, nen muc nay chi xuat hien khi clip thuc chuyen dong.
        if keyframe_graph.animated_properties(self.clip_model):
            menu.addSeparator()
            actions.append(add("graph", "fa6s.bezier-curve",
                               "Đồ thị đường cong…"))
        menu.addSeparator()
        actions.append(add("delete", "fa6s.trash", "Xóa clip", "#EF4444"))
        return menu, actions

    def _detachable_audio_clip(self):
        """Clip này có tiếng thật để tách không — cùng điều kiện với model."""
        clip = self.clip_model
        return bool(clip.media_type == "video" and clip.source_path
                    and not clip.audio_muted
                    and os.path.exists(clip.source_path))

    def contextMenuEvent(self, event):
        menu, actions = self._build_context_menu()
        chosen = menu.exec(event.screenPos())
        scene = self.scene()
        if not scene or chosen is None or chosen not in actions:
            return
        # Ten signal = khoa trong action.data(): menu dai bao nhieu muc khong
        # quan trong, va gate goi tung signal duoc ma khong_phai theo sau thu tu.
        signal_name = {
            "split": "split_requested",
            "duplicate": "duplicate_requested",
            "detach_audio": "audio_detach_requested",
            "graph": "graph_requested",
            "delete": "delete_requested",
        }.get(chosen.data())
        if signal_name and hasattr(scene, signal_name):
            getattr(scene, signal_name).emit(self.clip_model.clip_id)

    # ── Media Extraction Worker (Asynchronous QThread) ──────────

    def _extraction_signature(self):
        """Cửa sổ nguồn mà dải hình + cây sóng đang mô tả."""
        clip = self.clip_model
        return (clip.media_type, clip.source_path,
                round(float(clip.in_point), 3),
                round(float(clip.duration), 3),
                round(float(clip.speed_factor), 4),
                int(self._track_height))

    def _start_media_extraction(self):
        """Khởi động luồng chạy ngầm trích xuất đa phương tiện thực tế."""
        self._extraction_key = self._extraction_signature()
        self._extractor_thread = QThread()
        self._extractor_worker = MediaExtractionWorker(
            self.clip_model.source_path,
            self.clip_model.media_type,
            self.clip_model.name,
            self._track_height,
            self.clip_model.in_point,
            self.clip_model.duration,
            self.clip_model.speed_factor,
        )
        self._extractor_worker.moveToThread(self._extractor_thread)
        self._extractor_thread.started.connect(self._extractor_worker.run)
        
        # Kết nối kết quả trả về
        self._extractor_worker.thumbnailReady.connect(self._on_thumbnail_ready)
        self._extractor_worker.waveformReady.connect(self._on_waveform_ready)
        self._extractor_worker.finished.connect(self._extractor_thread.quit)
        self._extractor_worker.finished.connect(self._extractor_worker.deleteLater)
        self._extractor_thread.finished.connect(self._extractor_thread.deleteLater)
        
        self._extractor_thread.start()

    def _on_thumbnail_ready(self, images):
        if isinstance(images, QImage):
            images = [images]
        pixmaps = [QPixmap.fromImage(image) for image in images
                   if isinstance(image, QImage) and not image.isNull()]
        if pixmaps:
            self.thumbnail_cache = pixmaps
            self.update()

    def _on_waveform_ready(self, amplitudes):
        if amplitudes:
            self.audio_amplitudes = amplitudes
            self.update()

    def refresh_media_extraction(self):
        """Trích xuất lại khi cửa sổ nguồn đổi (trim, duration, tốc độ).

        Không làm thì kéo thanh Tốc độ chỉ đổi hình trên canvas, còn dải hình và
        cây sóng trên clip vẫn vẽ theo đoạn nguồn cũ — hai thứ lệch nhau trông
        như app hỏng.
        """
        if self._extraction_signature() == getattr(self, "_extraction_key", None):
            return
        self.shutdown_extraction()
        self.thumbnail_cache = []
        self.audio_amplitudes = []
        self._start_media_extraction()

    def shutdown_extraction(self):
        """Dừng worker an toàn trước khi item bị hủy hoặc đổi dự án."""
        thread = getattr(self, "_extractor_thread", None)
        worker = getattr(self, "_extractor_worker", None)
        if thread is None:
            return
        try:
            if worker is not None:
                worker.thumbnailReady.disconnect(self._on_thumbnail_ready)
                worker.waveformReady.disconnect(self._on_waveform_ready)
        except (RuntimeError, TypeError):
            pass
        try:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(5000):
                    thread.wait()
        except RuntimeError:
            pass
        self._extractor_thread = None
        self._extractor_worker = None

    # ── Keyframe Nodes Management (Interactive Diamond Nodes) ──

    def sync_keyframe_nodes_from_model(self):
        """Khởi tạo và định vị các viên kim cương KeyframeNode tương tác được dựa theo dữ liệu model."""
        # Dọn dẹp các node cũ
        for node in self._keyframe_nodes:
            if self.scene():
                self.scene().removeItem(node)
            node.setParentItem(None)
        self._keyframe_nodes.clear()

        # Spawn các node mới từ model keyframes
        y_pos = self.rect().center().y()

        for prop_key, frames in self.clip_model.keyframes.items():
            for frame in frames:
                # Tính vị trí X tương ứng trong clip
                x_pos = (self.rect().left() +
                         self._mapper.duration_to_width(frame_time(frame)))

                node = KeyframeNode(prop_key, frame_time(frame),
                                    frame_value(frame), self,
                                    ease=frame_ease(frame))
                node.setPos(x_pos, y_pos)
                self._keyframe_nodes.append(node)

    def update_keyframe_time(self, node, new_time_sec):
        """Được gọi bởi KeyframeNode khi kéo thả xong trên trục X."""
        frames = self.clip_model.keyframes.get(node.property_key, [])

        # Tìm và sửa lại thời gian trong danh sách dữ liệu gốc
        for i, frame in enumerate(frames):
            if abs(frame[0] - node.time_sec) < 0.05:
                # Đổi thời gian nhưng giữ đúng đường cong đang chọn
                frames[i] = make_frame(new_time_sec, node.value,
                                       frame_ease(frame))
                node.time_sec = new_time_sec # Lưu lại trong node
                break
                
        # Sắp xếp lại danh sách keyframe để thuật toán nội suy Lerp hoạt động chính xác
        frames.sort(key=lambda k: k[0])
        
        # Yêu cầu vẽ lại
        self.update()

    # Định vị lại clip và các viên kim cương mỗi khi model đổi (undo/redo,
    # trim, zoom, hoặc sửa ở bảng thuộc tính / đồ thị đường cong).
    def update_from_model(self):
        self.prepareGeometryChange()
        self._sync_rect_from_model()
        self._sync_transition_tooltip()
        # Hoàn tác một lệnh thêm/xoá/dời mốc chỉ phát clipResized, nên nếu chỉ
        # định vị lại thì viên kim cương cũ ở lại (sai chỗ, sai số lượng) và
        # mốc mới không bao giờ xuất hiện. Bộ mốc khác model là lúc phải dựng
        # lại; còn zoom/trim giữ nguyên bộ mốc thì đi đường rẻ.
        if self._node_signature() != self._model_signature():
            self.sync_keyframe_nodes_from_model()
            self.update()
            return
        # Zoom only changes geometry. Reusing existing nodes avoids destroying
        # and recreating child graphics items on every slider tick.
        for node in self._keyframe_nodes:
            node.setPos(
                self.rect().left() +
                self._mapper.duration_to_width(node.time_sec),
                self.rect().center().y(),
            )
        self._sync_node_curves_from_model()
        self.update()

    def _node_signature(self):
        return sorted((node.property_key, round(node.time_sec, 6))
                      for node in self._keyframe_nodes)

    def _model_signature(self):
        return sorted((prop, round(frame_time(frame), 6))
                      for prop, frames in self.clip_model.keyframes.items()
                      for frame in frames)

    def _sync_node_curves_from_model(self):
        """Node đọc lại đường cong và giá trị từ model.

        Hoàn tác một lệnh đổi cong chỉ sửa model rồi phát clipResized; nếu node
        giữ bản sao riêng thì viên kim cương vẫn vẽ tay cong của cong cũ và lệnh
        keo tiep theo phat gia tri cu dung len. Vi tri cua node van la cua no
        (dang bi keo), nen chi dong duoc khi model co frame cung moc.
        """
        for node in self._keyframe_nodes:
            frames = self.clip_model.keyframes.get(node.property_key, [])
            near = [f for f in frames
                    if abs(frame_time(f) - node.time_sec) < 0.02]
            if not near:
                continue
            frame = near[0]
            if node.ease != frame_ease(frame):
                node.set_ease(frame_ease(frame))
            if abs(node.value - frame_value(frame)) > 1e-9:
                node.value = frame_value(frame)


from PySide6.QtGui import QPolygonF, QBrush
from PySide6.QtCore import QPointF

class KeyframeNode(QGraphicsPolygonItem):
    """
    Điểm Keyframe hình thoi (viên kim cương trắng) tương tác kéo thả được trên Timeline.
    Chỉ cho phép trượt theo chiều ngang (trục X) và giới hạn trong phạm vi clip cha.

    Chuột phải chọn đường cong nội suy cho đoạn đi tới keyframe kế tiếp. Tay cong
    ve ngay tren node la dao ham cua chinh bang EASINGS tai dau doan — cong "cham
    dan" nam ngang, cong "nhanh dan" doc — nen hinh node noi that dieu model dang
    chua, khong phai ky hieu trang tri.

    KeyframeNode khong phai QObject (QGraphicsItem trong Qt6 khong ke thua no),
    nen no thu moc Signal: PySide6 bao "Signal object has no attribute emit"
    ngay luc phat. Node khong gi trang thai rieng — ClipItem.update_from_model()
    doc lai no tu model sau moi lan model doi.
    """
    def __init__(self, property_key, time_sec, value, parent_clip: ClipItem,
                 ease: str = "linear"):
        super().__init__(parent=parent_clip)
        self.property_key = property_key
        self.time_sec = time_sec
        self.value = value
        self.parent_clip = parent_clip
        self.ease = normalize_ease(ease)

        # Thiết lập các cờ tương tác
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(100)  # Luôn nổi lên trên nội dung clip
        self.setCursor(Qt.SizeHorCursor)

        # Định dạng hình dáng kim cương (polygon hình thoi)
        size = 5.0
        diamond = QPolygonF([
            QPointF(0, -size), QPointF(size, 0),
            QPointF(0, size), QPointF(-size, 0)
        ])
        self.setPolygon(diamond)

        # Giao diện tím/trắng
        self.setBrush(QBrush(QColor("#FFFFFF")))
        self.setPen(QPen(QColor("#7C5CFF"), 1))
        self.sync_tooltip()

    def set_ease(self, ease: str):
        self.ease = normalize_ease(ease)
        self.sync_tooltip()
        self.update()

    def is_last_of_track(self) -> bool:
        frames = self.parent_clip.clip_model.keyframes.get(self.property_key, [])
        return bool(frames) and abs(frames[-1][0] - self.time_sec) < 0.05

    def sync_tooltip(self):
        label = EASE_LABELS.get(self.ease, self.ease)
        tail = (" — keyframe cuối, không có đoạn phía sau"
                if self.is_last_of_track()
                else " — áp dụng cho đoạn tới keyframe kế tiếp")
        self.setToolTip("%s @ %.2fs · đường cong: %s%s" % (
            self.property_key, self.time_sec, label, tail))

    def handle_vector(self):
        """Tay cong suy ra tu dao ham that cua bang EASINGS tai t=0."""
        step = 0.05
        slope = (apply_ease(self.ease, step) - apply_ease(self.ease, 0.0)) / step
        slope = max(-6.0, min(6.0, slope))
        angle = math.atan2(-slope, 1.0)
        length = 9.0
        return QPointF(length * math.cos(angle), length * math.sin(angle))

    def build_ease_menu(self, parent_widget=None):
        """Menu chọn đường cong — tách khỏi exec để probe đi tuần được nó.

        QMenu.exec là modal nên không thể mở trong probe; phần CHƯA chọn/đã
        chọn của menu ở đây được kiểm tra trực tiếp rồi trigger action thật,
        chỉ bước hiện cửa sổ là bỏ qua.
        """
        from PySide6.QtGui import QActionGroup
        menu = QMenu(parent_widget)
        header = menu.addAction("Đường cong tới keyframe kế tiếp")
        header.setEnabled(False)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for name in EASINGS:
            action = menu.addAction(EASE_LABELS.get(name, name))
            action.setData(name)
            action.setCheckable(True)
            action.setChecked(name == self.ease)
            group.addAction(action)
            action.triggered.connect(
                lambda checked=False, key=name: self.apply_ease_from_ui(key))
        return menu

    def contextMenuEvent(self, event):
        menu = self.build_ease_menu()
        menu.exec(event.globalPos())

    def apply_ease_from_ui(self, ease: str):
        """Doi cong qua undo stack — moi sua model deu phai hoan tac duoc."""
        scene = self.scene()
        clip = self.parent_clip.clip_model
        if scene is not None and hasattr(scene, "undo_stack"):
            from core.commands import SetKeyframeEaseCommand
            scene.undo_stack.push(SetKeyframeEaseCommand(
                scene._model, clip.clip_id, self.property_key,
                self.time_sec, ease))
        else:
            clip.set_keyframe_ease(self.property_key, self.time_sec, ease)
        self.set_ease(ease)
        self.sync_tooltip()
        self.parent_clip.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = QPointF(value)
            
            # 1. Khóa cứng trục Y luôn nằm giữa clip
            clip_rect = self.parent_clip.rect()
            new_pos.setY(clip_rect.center().y())
            
            # 2. Giới hạn trục X trượt trong chiều rộng clip
            min_x = clip_rect.left()
            max_x = clip_rect.right()
            if new_pos.x() < min_x:
                new_pos.setX(min_x)
            elif new_pos.x() > max_x:
                new_pos.setX(max_x)
                
            return new_pos
            
        elif change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            mapper = self.parent_clip._mapper
            new_time_sec = mapper.width_to_duration(
                self.pos().x() - self.parent_clip.rect().left())
            new_time_sec = max(0.0, min(new_time_sec, self.parent_clip.clip_model.duration))
            
            if abs(new_time_sec - self.time_sec) > 0.01:
                old_time = self.time_sec
                scene = self.scene()
                
                if scene and hasattr(scene, 'undo_stack'):
                    from core.commands import DragKeyframeCommand
                    cmd = DragKeyframeCommand(
                        scene._model,
                        self.parent_clip.clip_model.clip_id,
                        self.property_key,
                        old_time,
                        new_time_sec,
                        self.value,
                    )
                    scene.undo_stack.push(cmd)
                else:
                    self.parent_clip.update_keyframe_time(self, new_time_sec)
                
                self.time_sec = new_time_sec
                self.parent_clip.sync_keyframe_nodes_from_model()

        return super().itemChange(change, value)

    def boundingRect(self):
        # Tay cong ve ra ngoai vien kim cuong, nen boundingRect phai bao nó;
        # thiếu thì Qt cắt nét vẽ và để lại vệt khi node di chuyển.
        return super().boundingRect().adjusted(-10.0, -10.0, 10.0, 10.0)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Đổi sang màu tím khi được chọn, hoặc hover
        if self.isSelected():
            self.setBrush(QBrush(QColor("#8B5CF6")))
            self.setPen(QPen(QColor("#FFFFFF"), 1))
        else:
            self.setBrush(QBrush(QColor("#FFFFFF")))
            self.setPen(QPen(QColor("#7C5CFF"), 1))

        if not self.is_last_of_track():
            handle = self.handle_vector()
            curve_pen = QPen(QColor("#FFB454") if self.isSelected()
                             else QColor("#7C5CFF"), 1.4)
            painter.setPen(curve_pen)
            painter.drawLine(QPointF(0.0, 0.0), handle)
            painter.setBrush(QBrush(QColor("#FFB454") if self.isSelected()
                                    else QColor("#7C5CFF")))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(handle, 1.8, 1.8)
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            
        super().paint(painter, option, widget)


class MediaExtractionWorker(QObject):
    """
    Worker xử lý đọc và phân tích video/audio chạy ngầm bằng QThread.
    """
    thumbnailReady = Signal(object)  # Phát list[QImage]
    waveformReady = Signal(list)    # Phát list float
    finished = Signal()

    def __init__(self, file_path, item_type, clip_name, track_height,
                 in_point=0.0, clip_duration=5.0, speed=1.0):
        super().__init__()
        self.file_path = file_path
        self.item_type = item_type
        self.clip_name = clip_name
        self.track_height = track_height
        self.in_point = max(0.0, float(in_point))
        self.clip_duration = max(0.1, float(clip_duration))
        # Thumbnails và waveform cùng một ánh xạ timeline -> nguồn. Bỏ qua speed
        # thì dải hình nhảy sai đoạn còn cây sóng lại đúng, và hai thứ lệch nhau
        # trông như clip bị lỗi.
        self.speed = max(0.25, min(4.0, float(speed) or 1.0))

    def source_at(self, local_time: float) -> float:
        return self.in_point + max(0.0, float(local_time)) * self.speed

    def run(self):
        from core import media_cache
        from core.media_extractor import extract_audio_waveform
        from core.media_frame import extract_frame_image
        from PySide6.QtCore import QSize
        
        try:
            if self.item_type == "video":
                images = []
                # A time-distributed cache gives the dynamic thumbnail painter
                # enough distinct frames when zoomed in, while remaining
                # bounded for long source files.
                sample_count = max(
                    6, min(24, int(self.clip_duration / 2.0) + 1)
                )
                thumb_h = max(24, int(self.track_height))
                for index in range(sample_count):
                    if QThread.currentThread().isInterruptionRequested():
                        break
                    relative = (self.clip_duration * (index + 0.5) /
                                sample_count)
                    source_t = self.source_at(relative)
                    # Ảnh nhỡ chỉ phụ thuộc (file, mốc nguồn, kích thước) nên
                    # lưu được ra đĩa; 414 ms/ảnh trên HDD máy yếu và trước đây
                    # mỗi lần mở project là giải mã lại y hệt.
                    key = media_cache.image_key(self.file_path, "timeline",
                                                source_t, 160, thumb_h)
                    image = media_cache.read_image(key) if key else QImage()
                    if image.isNull():
                        image = extract_frame_image(
                            self.file_path, source_t, QSize(160, thumb_h))
                        if key and not image.isNull():
                            media_cache.write_image(key, image)
                    if not image.isNull():
                        images.append(image)
                        # Show the first frame immediately, then refine the
                        # strip progressively instead of leaving a blank clip.
                        if len(images) == 1 or len(images) % 4 == 0:
                            self.thumbnailReady.emit(list(images))
                if images:
                    self.thumbnailReady.emit(images)
                if not QThread.currentThread().isInterruptionRequested():
                    amplitudes = extract_audio_waveform(
                        self.file_path, num_samples=180,
                        start=self.in_point,
                        duration=self.clip_duration * self.speed)
                    self.waveformReady.emit(amplitudes)
            elif self.item_type == "image":
                from core.media_locator import locate

                image = QImage()
                found = locate(self.file_path)
                if found:
                    image.load(found)
                if not image.isNull():
                    scaled = image.scaledToHeight(int(self.track_height), Qt.SmoothTransformation)
                    self.thumbnailReady.emit(scaled)
            elif self.item_type == "audio":
                amps = extract_audio_waveform(
                    self.file_path, num_samples=150, start=self.in_point,
                    duration=self.clip_duration * self.speed)
                self.waveformReady.emit(amps)
        except Exception as e:
            # Console của app là cp1252: in nguyên văn tiếng Việt ở đây sẽ nổ
            # UnicodeEncodeError và nuốt mất lỗi thật.
            print("MediaExtractionWorker failed: %s" % ascii(str(e)))
        finally:
            self.finished.emit()
