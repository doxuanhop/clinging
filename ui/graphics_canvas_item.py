"""
ui/graphics_canvas_item.py
Các QGraphicsItem dùng cho Canvas Trình phát Video (Player Canvas).
Cho phép kéo thả, di chuyển, co giãn trực tiếp bằng chuột.

Kỹ thuật (CanvasClipItem):
  - rect() LUÔN đại diện cho kích thước thực tế trên canvas
  - QTransform chỉ dùng cho rotation (không dùng cho scale)
  - Scale = thay đổi trực tiếp kích thước rect → không double-scale
  - Aspect ratio LUÔN được giữ nguyên khi resize (không cần giữ Shift)
  - prepareGeometryChange() gọi TRƯỚC khi thay đổi rect

Kỹ thuật (TextClipItem):
  - setScale() uniform (1 giá trị duy nhất) → không méo text
  - QTransform chỉ dùng cho rotation
"""

import math

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QBrush, QFont, QLinearGradient, QTransform, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem

from core.aura_paint import aura_reserve
from core.timeline_model import ClipModel
from core.transition_paint import apply_wipe

HANDLE_SIZE = 8.0
HANDLE_HITZone = 12.0
# Tay nắm xoay nằm CAO HƠN mép trên của khung một khoảng cố định. Phải là hằng
# số, không phải số đo theo trạng thái: boundingRect/shape mà đổi theo thì Qt
# dọn vùng dirty sai và cú nhấp đầu tiên hụt (xem bẫy "boundingRect tĩnh").
ROTATE_OFFSET = 24.0
ROTATE_HIT = 10.0
# Nhãn độ vẽ phía trên tay nắm nên vùng dành cho hàng xoay rộng hơn tay nắm một
# chút. Vẫn là hằng số: 52 px cho mọi trạng thái.
ROTATE_ROOM = ROTATE_OFFSET + ROTATE_HIT + 18.0
SMART_GUIDE_THRESHOLD = 10.0
SMART_GUIDE_RELEASE_THRESHOLD = 18.0
SMART_GUIDE_COLOR = QColor("#35D6C5")


def _normalize_angle(deg):
    """Gói góc về (-180, 180] — dải mà QTransform và atan2 của sync_to_model nói cùng một tiếng.

    Để góc 270 độ sống nguyên thì lần sync đầu tiên model nhận -90, và ô spin
    trên panel nhảy số ngay dưới tay người dùng.
    """
    a = float(deg) % 360.0
    return a - 360.0 if a > 180.0 else a


def _smart_snap_position(item, proposed_pos):
    """Bắt dính tâm và bốn mép item vào tâm/mép canvas.

    Ngưỡng nhả lớn hơn ngưỡng hít tạo cảm giác nam châm: item khựng
    nhẹ ở mốc chuẩn nhưng vẫn thoát ra khi người dùng kéo tiếp.
    """
    scene = item.scene()
    if scene is None:
        return proposed_pos

    sr = scene.sceneRect()
    target = sr.center()
    # shape() mới là footprint người dùng thao tác; boundingRect của clip video
    # còn nở sẵn chỗ cho aura loang, dùng nó thì mép clip không bao giờ hít được
    # vào mép canvas.
    current_rect = item.mapRectToScene(item.shape().boundingRect())
    delta = proposed_pos - item.pos()
    next_rect = current_rect.translated(delta)
    snapped = QPointF(proposed_pos)

    x_pairs = ((next_rect.center().x(), target.x()),
               (next_rect.left(), sr.left()), (next_rect.right(), sr.right()))
    y_pairs = ((next_rect.center().y(), target.y()),
               (next_rect.top(), sr.top()), (next_rect.bottom(), sr.bottom()))

    def nearest(pairs, axis):
        previous = getattr(item, f"_smart_snap_{axis}", None)
        limit = SMART_GUIDE_RELEASE_THRESHOLD if previous is not None else SMART_GUIDE_THRESHOLD
        candidates = [(abs(a - b), a, b) for a, b in pairs]
        if previous is not None:
            sticky = [c for c in candidates if abs(c[2] - previous) < 0.01]
            if sticky:
                candidates = sticky
        best = min(candidates, key=lambda value: value[0])
        return best if best[0] <= limit else None

    sx, sy = nearest(x_pairs, "x"), nearest(y_pairs, "y")
    if sx:
        snapped.setX(proposed_pos.x() + sx[2] - sx[1])
        item._smart_snap_x = sx[2]
    else:
        item._smart_snap_x = None
    if sy:
        snapped.setY(proposed_pos.y() + sy[2] - sy[1])
        item._smart_snap_y = sy[2]
    else:
        item._smart_snap_y = None

    _update_smart_guides(item, bool(sx), bool(sy),
                         QPointF(sx[2] if sx else target.x(), sy[2] if sy else target.y()), sr)
    return snapped


def _update_smart_guides(item, vertical, horizontal, center, scene_rect):
    scene = item.scene()
    if scene is None:
        return
    _clear_smart_guides(item)
    pen = QPen(SMART_GUIDE_COLOR, 2.0, Qt.SolidLine)
    if vertical:
        line = scene.addLine(center.x(), scene_rect.top(), center.x(), scene_rect.bottom(), pen)
        line.setZValue(10000)
        item._smart_v_guide = line
    if horizontal:
        line = scene.addLine(scene_rect.left(), center.y(), scene_rect.right(), center.y(), pen)
        line.setZValue(10000)
        item._smart_h_guide = line


def _clear_smart_guides(item):
    scene = item.scene()
    for attr in ("_smart_v_guide", "_smart_h_guide"):
        line = getattr(item, attr, None)
        if line is not None and scene is not None and line.scene() is scene:
            scene.removeItem(line)
        setattr(item, attr, None)


class CanvasClipItem(QGraphicsRectItem):
    """
    Clip video/ảnh trên Canvas Player.
    Hỗ trợ: di chuyển, co giãn 8 neo, giữ tỷ lệ, xoay.

    Kỹ thuật: rect() luôn đại diện cho kích thước thực tế trên canvas.
    QTransform chỉ dùng cho rotation. Scale được thao tác trực tiếp lên rect.
    """
    def __init__(self, clip_model: ClipModel, on_transform_callback=None,
                 on_edit_commit=None, parent=None):
        super().__init__(parent)
        self.clip_model = clip_model
        self.on_transform_callback = on_transform_callback
        self.on_edit_commit = on_edit_commit
        self._gesture_before = None

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)

        self._hover = False
        self._resizing_handle = None
        self._rotating = False
        self._rotate_base = 0.0
        self._rotate_start_rot = 0.0
        self._rotate_shown = 0.0
        self._drag_start_pos = QPointF()
        self._resize_orig_w = 0.0
        self._resize_orig_h = 0.0
        self._aspect_ratio = 1.0

        self._media_w = 0.0
        self._media_h = 0.0
        self._calc_rect_from_media()

        self.current_frame_pixmap = None
        self._transition_state = None
        self.sync_from_model()

    def set_transition_state(self, state):
        """Nhận TransitionState từ core/transitions.py — preview vẽ đúng công
        thức mà FrameComposer sẽ xuất, nên không còn "xem một kiểu, xuất một kiểu".
        """
        if getattr(self, "_transition_state", None) == state:
            return
        self._transition_state = state
        self.update()

    def _apply_transition_to_painter(self, painter, rect):
        state = getattr(self, "_transition_state", None)
        if state is None:
            return None
        painter.setOpacity(painter.opacity() * max(0.0, min(1.0, state.opacity)))
        center = rect.center()
        if state.dx or state.dy or abs(state.scale - 1.0) > 0.0001:
            painter.translate(center.x() + state.dx, center.y() + state.dy)
            painter.scale(state.scale, state.scale)
            painter.translate(-center.x(), -center.y())
        return state

    def _calc_rect_from_media(self):
        """Tính rect dựa trên kích thước media."""
        from core.canvas_utils import get_media_dimensions, calculate_fit_and_center, ASPECT_RATIOS

        if hasattr(self.clip_model.transform, '_media_w') and self.clip_model.transform._media_w > 0:
            w = self.clip_model.transform._media_w
            h = self.clip_model.transform._media_h
        else:
            media_type = self.clip_model.media_type
            if media_type == "sticker":
                # Sticker is an overlay, never a source that should Fit/Fill the
                # whole project frame.  Use a practical default canvas size.
                media_w, media_h = 220.0, 220.0
                self._media_w = media_w
                self._media_h = media_h
                self.clip_model.transform._media_w = media_w
                self.clip_model.transform._media_h = media_h
                w, h = media_w, media_h
            else:
                # Dùng original_w/original_h neu co, nguoi lai doc tu file
                media_w = getattr(self.clip_model.transform, 'original_w', 0)
                media_h = getattr(self.clip_model.transform, 'original_h', 0)
                if media_w <= 0 or media_h <= 0:
                    media_w, media_h = get_media_dimensions(
                        self.clip_model.source_path, media_type
                    )
                if media_w <= 0 or media_h <= 0:
                    media_w, media_h = 400, 300
                self._media_w = media_w
                self._media_h = media_h
                # Dung canvas size tu project ratio
                ratio_key = getattr(self.clip_model, '_project_ratio', '16:9')
                canvas_w, canvas_h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))
                layout = calculate_fit_and_center(media_w, media_h, canvas_w, canvas_h)
                w = layout['new_w']
                h = layout['new_h']

        self._aspect_ratio = w / h if h > 0 else 1.0
        self.prepareGeometryChange()
        self.setRect(QRectF(-w / 2, -h / 2, w, h))

    def _set_rect_size(self, new_w, new_h):
        """Thay đổi kích thước rect, giữ center."""
        self.prepareGeometryChange()
        self.setRect(QRectF(-new_w / 2, -new_h / 2, new_w, new_h))

    def sync_from_model(self):
        """Khôi phục vị trí, tỉ lệ, góc xoay từ model."""
        self.prepareGeometryChange()
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        self.setPos(self.clip_model.transform.x, self.clip_model.transform.y)

        sx = self.clip_model.transform.scale_x
        sy = self.clip_model.transform.scale_y
        rot = self.clip_model.transform.rotation

        base_w = self._orig_base_w()
        base_h = self._orig_base_h()
        self.setRect(QRectF(-base_w * sx / 2, -base_h * sy / 2, base_w * sx, base_h * sy))

        t = QTransform()
        t.rotate(rot)
        self.setTransform(t)

        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.update()

    def _orig_base_w(self):
        return self.clip_model.transform._media_w if hasattr(self.clip_model.transform, '_media_w') and self.clip_model.transform._media_w > 0 else self.rect().width() / max(self.clip_model.transform.scale_x, 0.01)

    def _orig_base_h(self):
        return self.clip_model.transform._media_h if hasattr(self.clip_model.transform, '_media_h') and self.clip_model.transform._media_h > 0 else self.rect().height() / max(self.clip_model.transform.scale_y, 0.01)

    def sync_to_model(self):
        """Lưu lại tọa độ và biến hình hiện tại vào model."""
        import math
        self.clip_model.transform.x = self.pos().x()
        self.clip_model.transform.y = self.pos().y()

        t = self.transform()
        # PySide6 QTransform khong co .rotation(), lay tu matrix elements
        self.clip_model.transform.rotation = math.degrees(math.atan2(t.m12(), t.m11()))

        r = self.rect()
        base_w = self._orig_base_w()
        base_h = self._orig_base_h()
        self.clip_model.transform.scale_x = r.width() / base_w if base_w > 0 else 1.0
        self.clip_model.transform.scale_y = r.height() / base_h if base_h > 0 else 1.0

        if self.on_transform_callback:
            self.on_transform_callback(self.clip_model)

    def boundingRect(self):
        # boundingRect bắt buộc ở hệ tọa độ local. Qt tự áp rotation/scale khi
        # hit-test; map transform tại đây lần nữa làm vùng chọn bị lệch/cắt.
        #
        # Vùng dành cho aura là HẰNG SỐ (lớn nhất trong registry), không lấy theo
        # hiệu ứng đang gắn trên clip: xem core.aura_paint.aura_reserve.
        #
        # Canh trên nở thêm ROTATE_ROOM cho tay nắm xoay + nhãn độ. Cũng phải là
        # hằng số: boundingRect đổi theo trạng thái thì Qt dọn vùng dirty sai và
        # lưu ảnh mờ dưới tay nắm (đã trả giá vụ "boundingRect tĩnh").
        bounding = self.rect()
        margin = HANDLE_SIZE + 4.0 + aura_reserve(bounding)
        return bounding.adjusted(-margin, -margin - ROTATE_ROOM, margin, margin)

    def shape(self):
        """Vùng chạm chuột: khung media + tay nắm, KHÔNG tính chỗ aura loang.

        boundingRect phải nở sẵn để Qt dọn vùng dirty cho nét vẽ tràn ra ngoài
        khung; nếu để vùng đó quyết định hit-test thì mọi clip đều "dính" từ rất
        xa mép, và mỗi lần gắn aura lại đổi tầm với của con trỏ.
        """
        margin = HANDLE_SIZE + 4.0
        path = QPainterPath()
        path.addRect(self.rect().adjusted(-margin, -margin, margin, margin))
        pt = self._rotate_handle_pos()
        path.addRect(QRectF(pt.x() - ROTATE_HIT, pt.y() - ROTATE_HIT,
                            ROTATE_HIT * 2, ROTATE_HIT * 2))
        return path

    def itemChange(self, change, value):
        # Z-value do thứ tự Track quyết định; không khóa thay đổi
        # tại item, nếu không Canvas sẽ mãi render theo thứ tự add.
        if change == QGraphicsItem.ItemPositionChange and self.scene() and self.isSelected():
            return _smart_snap_position(self, value)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self._clamp_to_scene()
            self.sync_to_model()
        elif change == QGraphicsItem.ItemTransformHasChanged:
            self.sync_to_model()
        return super().itemChange(change, value)

    def _clamp_to_scene(self):
        """Giữ clip trong phạm vi scene, tránh kéo ra ngoài."""
        scene = self.scene()
        if not scene:
            return
        sr = scene.sceneRect()
        pos = self.pos()
        # Chỉ dùng nội dung media, không tính handle của bounding box.
        media_bounds = self.transform().mapRect(self.rect())
        hw = media_bounds.width() / 2
        hh = media_bounds.height() / 2

        x = sr.center().x() if hw * 2 >= sr.width() else max(sr.left() + hw, min(pos.x(), sr.right() - hw))
        y = sr.center().y() if hh * 2 >= sr.height() else max(sr.top() + hh, min(pos.y(), sr.bottom() - hh))
        if pos.x() != x or pos.y() != y:
            self.setPos(x, y)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        media_type = self.clip_model.media_type

        painter.save()
        painter.setOpacity(getattr(self, '_keyframe_opacity', self.clip_model.transform.opacity))
        state = self._apply_transition_to_painter(painter, rect)

        pixmap = self._load_media_pixmap()

        if pixmap and not pixmap.isNull():
            all_effects = list(getattr(self.clip_model, "effects", []))
            preview_effect = getattr(self, "_preview_effect", None)
            if preview_effect is not None:
                all_effects.append(preview_effect)
            effect_signature = tuple(
                (e.name, round(e.intensity, 3), repr(sorted(e.params.items())))
                for e in all_effects
            )
            cache_key = (
                pixmap.cacheKey(), int(rect.width()), int(rect.height()),
                effect_signature
            )
            if (effect_signature and
                    getattr(self, "_effect_cache_key", None) == cache_key):
                scaled = self._effect_cache_pixmap
            else:
                scaled = pixmap.scaled(
                    rect.toRect().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                if effect_signature:
                    scaled = self._apply_effects(scaled)
                    self._effect_cache_key = cache_key
                    self._effect_cache_pixmap = scaled
            self._apply_animation_to_painter(painter, rect, all_effects)
            if state is not None and state.wipe is not None:
                # Mask wipe dùng chung với export; chỉ tính trên pixmap của frame
                # đang vẽ nên không bao giờ dính vào cache hiệu ứng.
                scaled = QPixmap.fromImage(
                    apply_wipe(scaled.toImage(), state.wipe[0], state.wipe[1]))
            x = rect.x() + (rect.width() - scaled.width()) / 2
            y = rect.y() + (rect.height() - scaled.height()) / 2
            # Lật quanh TÂM rect — cùng phép biến đổi mà FrameComposer._draw_media
            # dùng lúc xuất, nên hai đường không thể mỗi bên một kiểu.
            fx = -1.0 if getattr(self.clip_model.transform, "flip_h", False) else 1.0
            fy = -1.0 if getattr(self.clip_model.transform, "flip_v", False) else 1.0
            if fx < 0.0 or fy < 0.0:
                painter.translate(rect.center().x(), rect.center().y())
                painter.scale(fx, fy)
                painter.translate(-rect.center().x(), -rect.center().y())
            painter.drawPixmap(int(x), int(y), scaled)
            # Aura đi qua đúng hàm mà FrameComposer gọi, trong cùng transform
            # và cùng local_time, nên ô xem thử và file xuất ra không lệch nhau.
            from core.aura_paint import paint_aura_for_effects
            paint_aura_for_effects(
                painter, QRectF(x, y, scaled.width(), scaled.height()),
                getattr(self, "_local_time", 0.0), all_effects)
        else:
            self._paint_fallback(painter, rect, media_type)

        painter.restore()

        if self.isSelected() or self._hover:
            painter.setPen(QPen(QColor("#40E0D0"), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

            painter.setPen(QPen(QColor("#40E0D0"), 1.5))
            painter.setBrush(QBrush(Qt.white))
            for pt in self._get_handles():
                painter.drawRect(
                    pt.x() - HANDLE_SIZE / 2, pt.y() - HANDLE_SIZE / 2,
                    HANDLE_SIZE, HANDLE_SIZE
                )

            stem = self._rotate_handle_pos()
            painter.drawLine(QPointF(rect.center().x(), rect.top()), stem)
            painter.drawEllipse(stem, HANDLE_SIZE / 2.0, HANDLE_SIZE / 2.0)
            if self._rotating:
                # Nhan do goc lien tuc suot cu keo (270 van la 270), khong doc tu
                # model: model da bi atan2 goi ve (-180,180] nen nho nhay -90
                # trong luc tay nguoi dung keo vong qua dau.
                label = "%.0f°" % self._rotate_shown
                box = QRectF(stem.x() - 34.0, stem.y() - ROTATE_HIT - 20.0, 68.0, 18.0)
                painter.setFont(QFont("Outfit", 10, QFont.Bold))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#40E0D0"))
                painter.drawRoundedRect(box, 4.0, 4.0)
                painter.setPen(QPen(QColor("#06222A")))
                painter.drawText(box, Qt.AlignCenter, label)

    def _apply_effects(self, pixmap):
        """Áp dụng toàn bộ hiệu ứng trong clip.effects lên pixmap.

        Ủy quyền cho core.clip_effects.apply_color_effects — pipeline lọc màu
        dùng chung với Export để "xuất giống hệt xem trước".
        """
        from core.clip_effects import apply_color_effects

        effects = list(getattr(self.clip_model, 'effects', []))
        preview_effect = getattr(self, "_preview_effect", None)
        if preview_effect is not None:
            effects.append(preview_effect)
        if not effects:
            return pixmap

        img = apply_color_effects(pixmap.toImage(), effects)
        return QPixmap.fromImage(img)

    def set_local_time(self, local_time: float):
        """Thời gian cục bộ của clip tại playhead hiện tại.

        Preview từng lấy mốc bằng time.monotonic(), còn export dùng local_time,
        nên hai bên không bao giờ vẽ cùng một khung hình.
        """
        self._local_time = max(0.0, float(local_time))

    def _apply_animation_to_painter(self, painter, rect, effects):
        """Animate preview without ever changing the persisted clip transform."""
        from core.clip_effects import compute_animation_offsets

        off = compute_animation_offsets(
            effects, getattr(self, "_local_time", 0.0),
            rect.width(), rect.height(), self.clip_model.duration)
        painter.setOpacity(painter.opacity() * off.opacity)
        if off.dx or off.dy or off.rotation or abs(off.scale - 1.0) > 0.0001:
            center = rect.center()
            painter.translate(center.x() + off.dx, center.y() + off.dy)
            painter.rotate(off.rotation)
            painter.scale(off.scale, off.scale)
            painter.translate(-center.x(), -center.y())

    def _load_media_pixmap(self):
        from PySide6.QtGui import QPixmap

        if self.current_frame_pixmap and not self.current_frame_pixmap.isNull():
            return self.current_frame_pixmap

        file_path = self.clip_model.source_path
        media_type = self.clip_model.media_type

        if media_type == "image":
            from core.media_locator import locate
            pixmap = QPixmap()
            found = locate(file_path)
            if found:
                pixmap.load(found)
            if not pixmap.isNull():
                self.current_frame_pixmap = pixmap
                return pixmap

        elif media_type == "video":
            pixmap = self._extract_video_frame(file_path)
            if pixmap and not pixmap.isNull():
                self.current_frame_pixmap = pixmap
                return pixmap

        elif media_type == "sticker":
            pixmap = self._render_sticker_pixmap()
            if pixmap and not pixmap.isNull():
                self.current_frame_pixmap = pixmap
                return pixmap

        return None

    def _render_sticker_pixmap(self):
        """Render only the sticker artwork; its library title stays in Timeline."""
        from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
        from PySide6.QtCore import Qt, QRectF
        from widgets.common import icon_pixmap

        size = 200
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        icon_name = getattr(self.clip_model, "sticker_icon", "")
        if icon_name:
            try:
                artwork = icon_pixmap(
                    icon_name, 156,
                    getattr(self.clip_model, "sticker_color", "#FFFFFF")
                )
                # A restrained shadow keeps white stickers visible on bright video.
                painter.setOpacity(0.32)
                painter.drawPixmap(25, 29, artwork)
                painter.setOpacity(1.0)
                painter.drawPixmap(22, 22, artwork)
            except Exception:
                icon_name = ""

        if not icon_name:
            # Backward compatibility: old projects stored "emoji + title" in
            # name.  Draw the first token only, never the title text.
            sticker_glyph = (self.clip_model.name or "●").strip().split()[0]
            font = QFont("Segoe UI Emoji", 76)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, sticker_glyph)

        painter.end()
        return pixmap

    def _extract_video_frame(self, file_path: str):
        # Shared extractor includes an FFmpeg fallback for WMV/codec variants
        # that OpenCV cannot decode, so Main Storyline is never born black.
        from core.media_frame import extract_frame
        pixmap = extract_frame(file_path, 0.0)
        if not pixmap.isNull():
            return pixmap
        import os
        try:
            import cv2
            from PySide6.QtGui import QImage, QPixmap
            from core.media_locator import locate

            actual_path = locate(file_path)
            if not actual_path:
                return None

            import os as _os
            old_stderr = _os.dup(2)
            devnull = _os.open(_os.devnull, _os.O_WRONLY)
            _os.dup2(devnull, 2)
            try:
                cap = cv2.VideoCapture(actual_path)
            finally:
                _os.dup2(old_stderr, 2)
                _os.close(old_stderr)
                _os.close(devnull)
            if not cap.isOpened():
                return None

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None

            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w

            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            return QPixmap.fromImage(q_img)

        except Exception:
            return None

    def _paint_fallback(self, painter, rect, media_type):
        if media_type == "video":
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#1E3A8A"))
            grad.setColorAt(1.0, QColor("#3B82F6"))
            painter.fillRect(rect, grad)
            painter.setPen(QPen(QColor("#60A5FA"), 2))
            painter.drawRect(rect)
            painter.setBrush(QColor(255, 255, 255, 200))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon([QPointF(-15, -20), QPointF(-15, 20), QPointF(20, 0)])

        elif media_type == "image":
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#064E3B"))
            grad.setColorAt(1.0, QColor("#10B981"))
            painter.fillRect(rect, grad)
            painter.setPen(QPen(QColor("#34D399"), 2))
            painter.drawRect(rect)

        elif media_type == "text":
            painter.setPen(Qt.white)
            font = QFont("Outfit", 18, QFont.Bold)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self.clip_model.name)

        elif media_type == "sticker":
            # Sticker: vẽ emoji text lớn ở centre
            painter.setPen(Qt.white)
            font = QFont("Segoe UI Emoji", max(16, int(min(rect.width(), rect.height()) * 0.4)))
            painter.setFont(font)
            sticker_text = self.clip_model.name or "?"
            painter.drawText(rect, Qt.AlignCenter, sticker_text)

        else:
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#7C3AED"))
            grad.setColorAt(1.0, QColor("#A78BFA"))
            painter.fillRect(rect, grad)

    def _get_handles(self):
        r = self.rect()
        return [
            r.topLeft(),
            QPointF(r.center().x(), r.top()),
            r.topRight(),
            QPointF(r.right(), r.center().y()),
            r.bottomRight(),
            QPointF(r.center().x(), r.bottom()),
            r.bottomLeft(),
            QPointF(r.left(), r.center().y())
        ]

    def _hit_test_handle(self, pos):
        """Kiểm tra pos có trúng resize handle nào không. Trả về index hoặc -1."""
        handles = self._get_handles()
        for i, pt in enumerate(handles):
            hit_rect = QRectF(
                pt.x() - HANDLE_HITZone, pt.y() - HANDLE_HITZone,
                HANDLE_HITZone * 2, HANDLE_HITZone * 2
            )
            if hit_rect.contains(pos):
                return i
        return -1

    def _rotate_handle_pos(self):
        """Tâm tay nắm xoay, ở hệ tọa độ local của item — nên xoay cùng khung."""
        r = self.rect()
        return QPointF(r.center().x(), r.top() - ROTATE_OFFSET)

    def _hit_test_rotate(self, pos):
        pt = self._rotate_handle_pos()
        return QRectF(pt.x() - ROTATE_HIT, pt.y() - ROTATE_HIT,
                      ROTATE_HIT * 2, ROTATE_HIT * 2).contains(pos)

    def _scene_angle(self, scene_pos):
        """Góc của con trỏ quanh tâm clip, đo ở HỆ SCENE.

        Không dùng mapFromScene: tọa độ local đã bị trừ sẵn rotation của item
        nên hiệu hai lần đọc luôn trả 0 và cú quay không nhúc nhích.
        """
        center = self.mapToScene(self.rect().center())
        return math.degrees(math.atan2(scene_pos.y() - center.y(),
                                       scene_pos.x() - center.x()))

    def _apply_rotation(self, scene_pos):
        delta = self._scene_angle(scene_pos) - self._rotate_base
        # _rotate_shown đếm nối tiếp suốt cú kéo (qua 180 vẫn tới 200) để nhãn
        # không nhảy -179 -> 179 giữa tay; QTransform nhận góc đã gói vì
        # sync_to_model đọc lại bằng atan2, dải (-180, 180].
        self._rotate_shown = self._rotate_start_rot + delta
        self.setTransform(QTransform().rotate(_normalize_angle(self._rotate_shown)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            from core.commands import transform_snapshot
            self._gesture_before = transform_snapshot(self.clip_model)
            pos = event.pos()
            if self._hit_test_rotate(pos):
                # Không rơi xuống super: ItemIsMovable còn bật thì clip bị kéo
                # lê thay vì quay, và _clamp_to_scene trả nó về giữa canvas.
                self._rotating = True
                self._rotate_base = self._scene_angle(event.scenePos())
                self._rotate_start_rot = self.clip_model.transform.rotation
                self._rotate_shown = self._rotate_start_rot
                self.setCursor(Qt.CrossCursor)
                event.accept()
                return
            handle = self._hit_test_handle(pos)
            if handle >= 0:
                self._resizing_handle = handle
                self._drag_start_pos = event.scenePos()
                r = self.rect()
                self._resize_orig_w = r.width()
                self._resize_orig_h = r.height()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return

            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rotating:
            self._apply_rotation(event.scenePos())
            self.update()
            event.accept()
            return

        if self._resizing_handle is not None:
            delta = event.scenePos() - self._drag_start_pos
            h = self._resizing_handle

            orig_w = self._resize_orig_w
            orig_h = self._resize_orig_h

            new_w = orig_w
            new_h = orig_h

            if h in (2, 3, 4):
                new_w = orig_w + delta.x()
            elif h in (0, 6, 7):
                new_w = orig_w - delta.x()

            if h in (4, 5, 6):
                new_h = orig_h + delta.y()
            elif h in (0, 1, 2):
                new_h = orig_h - delta.y()

            new_w = max(20, new_w)
            new_h = max(20, new_h)

            # "Khóa tỷ lệ" là cờ trên model, không phải sở thích của item: dùng
            # tỉ lệ của rect LÚC BẤM chứ không phải tỉ lệ media, vì clip đã
            # kéo tự do (scale_x != scale_y) sẽ nhảy về hình gốc giữa cú kéo.
            if getattr(self.clip_model.transform, "uniform_scale", True):
                ratio = orig_w / orig_h if orig_h > 0 else 1.0
                if ratio > 0:
                    if abs(delta.x()) >= abs(delta.y()):
                        new_h = new_w / ratio
                    else:
                        new_w = new_h * ratio

            self._set_rect_size(new_w, new_h)

            self.update()
            self.sync_to_model()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        _clear_smart_guides(self)
        if self._rotating:
            self._rotating = False
            self.setCursor(Qt.OpenHandCursor)
            self._commit_gesture()
            event.accept()
            return
        self._commit_gesture()
        if self._resizing_handle is not None:
            self._resizing_handle = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def _get_handle_cursor(self, handle_index):
        cursors = {
            0: Qt.SizeFDiagCursor,
            1: Qt.SizeVerCursor,
            2: Qt.SizeBDiagCursor,
            3: Qt.SizeHorCursor,
            4: Qt.SizeFDiagCursor,
            5: Qt.SizeVerCursor,
            6: Qt.SizeBDiagCursor,
            7: Qt.SizeHorCursor,
        }
        return cursors.get(handle_index, Qt.SizeAllCursor)

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
        pos = event.pos()
        handle = self._hit_test_handle(pos)
        if self._hit_test_rotate(pos):
            self.setCursor(Qt.CrossCursor)
        elif handle >= 0:
            self.setCursor(self._get_handle_cursor(handle))
        else:
            self.setCursor(Qt.OpenHandCursor)


    def _commit_gesture(self):
        """Goi mot lan keo chuot tren Canvas thanh MOT lenh undo.

        `before` lay tu luc bam chuot: item da ghi ket qua vao model o tung lan
        mouseMove, neu lenh tu snapshot luc nang chuot thi Ctrl+Z tra lai dung
        gia tri vua keo va nguoi dung tuong nut undo hong.
        """
        before, self._gesture_before = self._gesture_before, None
        if before is None or self.on_edit_commit is None:
            return
        from core.commands import transform_snapshot
        self.on_edit_commit(self.clip_model, "transform",
                            transform_snapshot(self.clip_model), before)

class TextClipItem(QGraphicsTextItem):
    """
    Văn bản trên Canvas Player.
    Hỗ trợ kéo dãn, di chuyển, xoay và chỉnh sửa nội dung.
    """

    def __init__(self, clip_model: ClipModel, on_transform_callback=None,
                 on_edit_commit=None, parent=None):
        super().__init__(clip_model.name, parent)
        self.clip_model = clip_model
        self.on_transform_callback = on_transform_callback
        self.on_edit_commit = on_edit_commit
        self._gesture_before = None

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)

        self.document().setDocumentMargin(0)
        self.refresh_style()

        # Một click dành cho chọn/kéo; double-click mới chuyển sang sửa chữ.
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self._hover = False
        self._resizing_handle = None
        self._drag_start_pos = QPointF()
        self._resize_orig_scale = 1.0
        self._resize_orig_w = 0.0
        self._resize_orig_h = 0.0
        self._aspect_ratio = 1.0

        self.sync_from_model()

    def set_local_time(self, local_time: float):
        """Nhịp của clip tại playhead — text animation vẽ theo mốc này."""
        self._local_time = max(0.0, float(local_time))

    def set_transition_state(self, state):
        """Chuyển tiếp của chữ cũng đi qua core/transitions.py như export."""
        if getattr(self, "_transition_state", None) == state:
            return
        self._transition_state = state
        self.update()

    def _commit_gesture(self):
        """Goi mot lan keo chuot tren Canvas thanh MOT lenh undo.

        `before` lay tu luc bam chuot: item da ghi ket qua vao model o tung lan
        mouseMove, neu lenh tu snapshot luc nang chuot thi Ctrl+Z tra lai dung
        gia tri vua keo va nguoi dung tuong nut undo hong.
        """
        before, self._gesture_before = self._gesture_before, None
        if before is None or self.on_edit_commit is None:
            return
        from core.commands import transform_snapshot
        self.on_edit_commit(self.clip_model, "transform",
                            transform_snapshot(self.clip_model), before)

    def refresh_style(self):
        """Đọc lại font/màu từ model — model là nguồn sự thật cho cả export."""
        from core.text_paint import clip_font
        self._font = clip_font(self.clip_model)
        self.setFont(self._font)
        self.setDefaultTextColor(QColor(getattr(self.clip_model, "font_color", "#FFFFFF")))
        self.setPlainText(self.clip_model.name or "")
        self.prepareGeometryChange()
        self.update()

    def sync_from_model(self):
        self.prepareGeometryChange()
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        sx = self.clip_model.transform.scale_x
        sy = self.clip_model.transform.scale_y
        uniform_scale = (sx + sy) / 2.0

        t = QTransform()
        t.rotate(self.clip_model.transform.rotation)
        self.setTransform(t)
        self.setScale(uniform_scale)
        self.set_center_position(
            self.clip_model.transform.x, self.clip_model.transform.y
        )

        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.update()

    def sync_to_model(self):
        import math
        center = self.mapRectToScene(super().boundingRect()).center()
        self.clip_model.transform.x = center.x()
        self.clip_model.transform.y = center.y()

        t = self.transform()
        # PySide6 QTransform khong co .rotation(), lay tu matrix elements
        self.clip_model.transform.rotation = math.degrees(math.atan2(t.m12(), t.m11()))

        uniform_scale = self.scale()
        self.clip_model.transform.scale_x = uniform_scale
        self.clip_model.transform.scale_y = uniform_scale

        if self.on_transform_callback:
            self.on_transform_callback(self.clip_model)

    def set_center_position(self, x, y):
        """Đặt tâm hình học của text tại tọa độ canvas (x, y)."""
        center_now = self.mapRectToScene(super().boundingRect()).center()
        self.setPos(self.pos() + QPointF(x, y) - center_now)

    def apply_keyframe_transform(self, x, y, scale_x, scale_y, rotation, opacity):
        """Áp transform khi playback mà không dùng API rect của image/video."""
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        self.setScale((scale_x + scale_y) / 2.0)
        t = QTransform()
        t.rotate(rotation)
        self.setTransform(t)
        self.set_center_position(x, y)
        self.setOpacity(opacity)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def boundingRect(self):
        rect = super().boundingRect()
        margin = HANDLE_SIZE + 4.0
        return rect.adjusted(-margin, -margin, margin, margin)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() and self.isSelected():
            return _smart_snap_position(self, value)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self.sync_to_model()
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        if self.isSelected() or self._hover:
            rect = self.boundingRect()
            painter.setPen(QPen(QColor("#40E0D0"), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # Khi đang sửa thì để document vẽ (con trỏ, bôi đen); lúc còn lại dùng
        # đúng bộ vẽ chữ của export để hai bên không lệch nhau.
        editing = self.textInteractionFlags() != Qt.TextInteractionFlag.NoTextInteraction
        if editing:
            super().paint(painter, option, widget)
            return

        clip = self.clip_model
        from core.text_paint import clip_font, paint_animated_text, text_style_of
        from core import anim_engine

        scene_rect = self.scene().sceneRect() if self.scene() else QRectF(0, 0, 1920, 1080)
        uniform = max(0.01, float(self.scale()))
        center = super().boundingRect().center()
        font = clip_font(clip)

        state = getattr(self, "_transition_state", None)
        if state is not None:
            painter.setOpacity(painter.opacity()
                               * max(0.0, min(1.0, state.opacity)))
            if state.dx or state.dy or abs(state.scale - 1.0) > 0.0001:
                painter.translate(center.x() + state.dx, center.y() + state.dy)
                painter.scale(state.scale, state.scale)
                painter.translate(-center.x(), -center.y())

        paint_animated_text(
            painter, clip.name or "", font, getattr(clip, "font_color", "#FFFFFF"),
            scene_rect.width() / uniform, scene_rect.height() / uniform,
            center.x(), center.y(),
            effect=getattr(clip, "text_effect", "none") or "none",
            p=anim_engine.progress(getattr(self, "_local_time", 0.0), clip.duration),
            intensity=float(getattr(clip, "text_effect_intensity", 0.6)),
            style=getattr(clip, "text_style", "none") or "none",
            t=getattr(self, "_local_time", 0.0),
            styling=text_style_of(clip),
        )

    def _get_handles(self):
        r = self.boundingRect()
        return [
            r.topLeft(),
            QPointF(r.center().x(), r.top()),
            r.topRight(),
            QPointF(r.right(), r.center().y()),
            r.bottomRight(),
            QPointF(r.center().x(), r.bottom()),
            r.bottomLeft(),
            QPointF(r.left(), r.center().y())
        ]

    def _hit_test_handle(self, pos):
        handles = self._get_handles()
        for i, pt in enumerate(handles):
            hit_rect = QRectF(
                pt.x() - HANDLE_HITZone, pt.y() - HANDLE_HITZone,
                HANDLE_HITZone * 2, HANDLE_HITZone * 2
            )
            if hit_rect.contains(pos):
                return i
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            from core.commands import transform_snapshot
            self._gesture_before = transform_snapshot(self.clip_model)
            pos = event.pos()
            handle = self._hit_test_handle(pos)
            if handle >= 0:
                self._resizing_handle = handle
                self._drag_start_pos = event.scenePos()
                self._resize_orig_scale = self.scale()
                r = self.boundingRect()
                self._resize_orig_w = r.width()
                self._resize_orig_h = r.height()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return

            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing_handle is not None:
            delta = event.scenePos() - self._drag_start_pos
            h = self._resizing_handle

            orig_w = self._resize_orig_w
            orig_h = self._resize_orig_h

            new_w = orig_w
            new_h = orig_h

            if h in (2, 3, 4):
                new_w = orig_w + delta.x()
            elif h in (0, 6, 7):
                new_w = orig_w - delta.x()

            if h in (4, 5, 6):
                new_h = orig_h + delta.y()
            elif h in (0, 1, 2):
                new_h = orig_h - delta.y()

            new_w = max(20, new_w)
            new_h = max(20, new_h)

            if self._aspect_ratio > 0:
                if abs(delta.x()) >= abs(delta.y()):
                    new_h = new_w / self._aspect_ratio
                else:
                    new_w = new_h * self._aspect_ratio

            new_scale = new_w / orig_w if orig_w > 0 else self._resize_orig_scale
            new_scale = max(0.05, min(new_scale, 20.0))

            self.prepareGeometryChange()
            self.setScale(new_scale)
            self.sync_to_model()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        _clear_smart_guides(self)
        self._commit_gesture()
        if self._resizing_handle is not None:
            self._resizing_handle = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        text = self.toPlainText()
        if text and text != self.clip_model.name:
            if self.on_edit_commit is not None:
                self.on_edit_commit(self.clip_model, "text", {"name": text})
            else:
                self.clip_model.name = text
        self.sync_to_model()
        super().focusOutEvent(event)

    def _get_handle_cursor(self, handle_index):
        cursors = {
            0: Qt.SizeFDiagCursor,
            1: Qt.SizeVerCursor,
            2: Qt.SizeBDiagCursor,
            3: Qt.SizeHorCursor,
            4: Qt.SizeFDiagCursor,
            5: Qt.SizeVerCursor,
            6: Qt.SizeBDiagCursor,
            7: Qt.SizeHorCursor,
        }
        return cursors.get(handle_index, Qt.SizeAllCursor)

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
        pos = event.pos()
        handle = self._hit_test_handle(pos)
        if handle >= 0:
            self.setCursor(self._get_handle_cursor(handle))
        else:
            self.setCursor(Qt.OpenHandCursor)

    def update_text(self, new_text: str):
        self.setPlainText(new_text)
        self.clip_model.name = new_text
        self.update()
