"""
core/frame_composer.py
Bộ dựng frame HEADLESS dùng chung cho Export — vẽ timeline tại thời điểm t
sao cho GIỐNG HỆT Canvas preview.

Nguyên tắc để "xuất giống xem trước":
    1. Dựng frame ở đúng độ phân giải project-canvas (ASPECT_RATIOS[ratio]),
       dùng cùng hệ tọa độ tâm và cùng công thức fit/scale như CanvasClipItem.
    2. Tái sử dụng NGUYÊN pipeline hiệu ứng của preview qua core.clip_effects
       (lọc màu + animation) và nội suy keyframe qua ClipModel.get_value_at_time.
    3. Cuối cùng scale toàn khung về độ phân giải xuất mong muốn.

Nhờ vẽ ở project-canvas rồi scale, offset x/y (vốn lưu theo pixel canvas) luôn
đúng tỉ lệ ở mọi độ phân giải xuất.
"""

import os

from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtCore import Qt, QRectF

from core.canvas_utils import (
    ASPECT_RATIOS, calculate_fit_and_center, get_media_dimensions,
)
from core import anim_engine
from core import transitions
from core.aura_paint import paint_aura_for_effects
from core import recap_overlay
from core.clip_effects import apply_color_effects, compute_animation_offsets
from core.media_frame import SequentialVideoReader, extract_frame_image, qimage_from_bgr
from core.transition_paint import apply_wipe


class FrameComposer:
    """Dựng từng frame của timeline thành QImage khớp với Canvas preview."""

    def __init__(self, model, out_width, out_height):
        self.model = model
        self.out_width = int(out_width)
        self.out_height = int(out_height)

        ratio = getattr(model, "project_ratio", "16:9")
        self.canvas_w, self.canvas_h = ASPECT_RATIOS.get(ratio, (1920, 1080))

        # Cache theo source_path để không mở lại/không đọc lại ảnh mỗi frame.
        self._image_cache = {}
        self._sticker_cache = {}
        # Mỗi clip video một decoder tuần tự (xem SequentialVideoReader).
        self._video_readers = {}

    # ── Public API ──────────────────────────────────────────────

    def render_frame(self, t: float) -> QImage:
        """Trả về QImage RGBA8888 kích thước xuất, đã vẽ mọi clip tại thời điểm t."""
        canvas = QImage(self.canvas_w, self.canvas_h,
                        QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(QColor("#000000"))

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        try:
            # active_visual_clips_at trả về đúng thứ tự nền -> tiền cảnh của preview.
            for clip in self.model.active_visual_clips_at(t):
                # Cùng một hàm toán với preview: transitions.clip_state cho hình
                # thái, ClipModel.local_time_at cho đồng hồ của clip.
                state = self.model.transition_state(
                    clip, t, self.canvas_w, self.canvas_h)
                self._draw_clip(painter, clip, clip.local_time_at(t), state)
        finally:
            painter.end()

        overlay = self.model.recap_overlay
        if recap_overlay.overlay_active(overlay):
            canvas = self._apply_recap_overlay(canvas, overlay, t)

        if (self.canvas_w, self.canvas_h) != (self.out_width, self.out_height):
            canvas = canvas.scaled(
                self.out_width, self.out_height,
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
        return canvas.convertToFormat(QImage.Format.Format_RGBA8888)

    def _apply_recap_overlay(self, content: QImage, settings: dict, t: float) -> QImage:
        """Pass cuối của bản xuất: nền kính mờ rồi viền/tâm ngắm/REC.

        Ảnh dựng được giữ nguyên trong `content`; kết quả vẽ ra là QImage mới ở
        đúng độ phân giải canvas, nên nét của overlay không bị bước scale phía
        sau làm nhoè. Preview gọi đúng hai hàm recap_overlay mà đây gọi.
        """
        w, h = self.canvas_w, self.canvas_h
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor("#000000"))
        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing)
        if settings["glass"]:
            recap_overlay.paint_backdrop(painter, w, h, content, settings)
            painter.drawImage(recap_overlay.content_rect(w, h, settings), content)
        else:
            painter.drawImage(0, 0, content)
        recap_overlay.paint_overlay(
            painter, w, h, settings, t,
            recap_overlay.resolution_label(w, h, settings))
        painter.end()
        return out

    def render_frame_bytes(self, t: float) -> bytes:
        """QImage RGBA8888 -> bytes thô để pipe thẳng vào ffmpeg (pix_fmt rgba)."""
        image = self.render_frame(t)
        bits = image.constBits()
        try:
            return bits.tobytes()
        except AttributeError:
            return bytes(bits)

    def close(self):
        self._image_cache.clear()
        self._sticker_cache.clear()
        for reader in self._video_readers.values():
            reader.close()
        self._video_readers.clear()

    # ── Drawing ─────────────────────────────────────────────────

    def _draw_clip(self, painter: QPainter, clip, local_time: float,
                   state=None):
        x = clip.get_value_at_time("x", local_time, clip.transform.x)
        y = clip.get_value_at_time("y", local_time, clip.transform.y)
        sx = clip.get_value_at_time("scale_x", local_time, clip.transform.scale_x)
        sy = clip.get_value_at_time("scale_y", local_time, clip.transform.scale_y)
        rot = clip.get_value_at_time("rotation", local_time, clip.transform.rotation)
        opacity = clip.get_value_at_time("opacity", local_time, clip.transform.opacity)

        if clip.media_type == "text":
            self._draw_text(painter, clip, x, y, sx, sy, rot, opacity, local_time,
                            state)
        else:
            self._draw_media(painter, clip, local_time, x, y, sx, sy, rot, opacity,
                             state)

    def _draw_media(self, painter, clip, local_time, x, y, sx, sy, rot, opacity,
                    state=None):
        source = self._load_source_image(clip, local_time)
        if source is None or source.isNull():
            return

        state = state if state is not None else transitions.NEUTRAL

        base_w, base_h = self._base_size(clip)
        rect_w = max(1, int(base_w * sx))
        rect_h = max(1, int(base_h * sy))

        # Giống preview: scale KeepAspectRatio vào rect rồi mới áp bộ lọc màu.
        scaled = source.scaled(rect_w, rect_h, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)

        effects = list(getattr(clip, "effects", []))
        if effects:
            scaled = apply_color_effects(scaled, effects)

        anim = compute_animation_offsets(effects, local_time, scaled.width(),
                                         scaled.height(), clip.duration)

        if state.wipe is not None:
            scaled = apply_wipe(scaled, state.wipe[0], state.wipe[1])
            if scaled.isNull():
                return

        cx = self.canvas_w / 2.0 + x + anim.dx + state.dx
        cy = self.canvas_h / 2.0 + y + anim.dy + state.dy
        total_scale = anim.scale * state.scale

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)) * anim.opacity
                           * state.opacity)
        painter.translate(cx, cy)
        painter.rotate(rot + anim.rotation)
        painter.scale(total_scale, total_scale)
        painter.drawImage(int(-scaled.width() / 2), int(-scaled.height() / 2), scaled)
        # Aura vẽ trong chính transform của clip nên nó xoay và co theo khung
        # hình, và dùng chung hàm với Canvas preview — không có nhánh riêng.
        paint_aura_for_effects(painter, QRectF(-scaled.width() / 2.0,
                                               -scaled.height() / 2.0,
                                               scaled.width(), scaled.height()),
                               local_time, effects)
        painter.restore()

    def _draw_text(self, painter, clip, x, y, sx, sy, rot, opacity, local_time,
                   state=None):
        """Vẽ chữ qua core.text_paint — cùng một đường vẽ với Canvas preview."""
        from core.text_paint import clip_font, paint_animated_text, text_style_of

        state = state if state is not None else transitions.NEUTRAL
        font = clip_font(clip)
        uniform = max(0.01, (sx + sy) / 2.0) * state.scale

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)) * state.opacity)
        painter.translate(self.canvas_w / 2.0 + x + state.dx,
                          self.canvas_h / 2.0 + y + state.dy)
        painter.rotate(rot)
        painter.scale(uniform, uniform)
        # Truyền khung hình đã chia scale để khoảng dịch của animation vẫn tính
        # theo đúng nửa canvas dù chữ đang bị phóng/thu.
        paint_animated_text(
            painter, clip.name or "", font,
            getattr(clip, "font_color", "#FFFFFF"),
            self.canvas_w / uniform, self.canvas_h / uniform, 0.0, 0.0,
            effect=getattr(clip, "text_effect", "none") or "none",
            p=anim_engine.progress(local_time, clip.duration),
            intensity=float(getattr(clip, "text_effect_intensity", 0.6)),
            style=getattr(clip, "text_style", "none") or "none",
            t=local_time,
            styling=text_style_of(clip),
        )
        painter.restore()

    # ── Sources & sizing ────────────────────────────────────────

    def _load_source_image(self, clip, local_time) -> QImage:
        media_type = clip.media_type

        if media_type == "image":
            cached = self._image_cache.get(clip.source_path)
            if cached is None:
                cached = QImage(clip.source_path) if os.path.exists(clip.source_path) else QImage()
                self._image_cache[clip.source_path] = cached
            return cached

        if media_type == "video":
            # source_at_local là ánh xạ DUY NHẤT timeline -> giây nguồn; nó nhân
            # speed, nên một clip 2x dựng ra cùng những frame mà ô nghe thử báo.
            seconds = clip.source_at_local(local_time)
            # Decoder tuần tự theo clip: export duyệt t tăng dần nên gần như mọi
            # frame chỉ cần read() tiếp, không seek. OpenCV mở được file nào thì
            # mới dùng; file lạ (WMV codec Qt/FFmpeg đọc được nhưng OpenCV không)
            # rơi về extract_frame_image như trước.
            reader = self._video_readers.get(clip.clip_id)
            if reader is None:
                reader = SequentialVideoReader(clip.source_path)
                self._video_readers[clip.clip_id] = reader
            if not reader.dead:
                frame = reader.read_bgr(seconds)
                if frame is not None:
                    return qimage_from_bgr(frame)
            return extract_frame_image(clip.source_path, seconds)

        if media_type == "sticker":
            return self._load_sticker_image(clip)

        return QImage()

    def _load_sticker_image(self, clip) -> QImage:
        icon_name = getattr(clip, "sticker_icon", "") or "fa6s.face-smile"
        color = getattr(clip, "sticker_color", "#FFFFFF")
        key = (icon_name, color)
        cached = self._sticker_cache.get(key)
        if cached is None:
            from widgets.common import icon_pixmap
            pm = icon_pixmap(icon_name, 220, color)
            cached = pm.toImage() if pm and not pm.isNull() else QImage()
            self._sticker_cache[key] = cached
        return cached

    def _base_size(self, clip):
        """Kích thước nền (đã fit-to-canvas) trước khi nhân scale — khớp preview."""
        tw = getattr(clip.transform, "_media_w", 0.0)
        th = getattr(clip.transform, "_media_h", 0.0)
        if tw > 0 and th > 0:
            return tw, th

        if clip.media_type == "sticker":
            return 220.0, 220.0

        media_w = getattr(clip.transform, "original_w", 0) or 0
        media_h = getattr(clip.transform, "original_h", 0) or 0
        if media_w <= 0 or media_h <= 0:
            media_w, media_h = get_media_dimensions(clip.source_path, clip.media_type)
        if media_w <= 0 or media_h <= 0:
            media_w, media_h = 400, 300

        layout = calculate_fit_and_center(media_w, media_h, self.canvas_w, self.canvas_h)
        return layout["new_w"], layout["new_h"]
