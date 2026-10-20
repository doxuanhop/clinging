"""
core/text_paint.py
Vẽ chữ CÓ HOẠT ẢNH bằng QPainter — một đường vẽ duy nhất cho preview và export.

Trước đây preview dùng QGraphicsTextItem (xếp chữ theo document), export dùng
painter.drawText, và cỡ chữ lấy theo pointSize nên đổi theo DPI màn hình. Hai
bên vì thế không bao giờ ra cùng một khung hình. Module này:

    * setPixelSize cho cỡ chữ (không phụ thuộc DPI),
    * tự xếp dòng và căn giữa trong một hộp cố định,
    * đọc trạng thái chuyển động từ core.anim_engine theo nhịp tiến độ.

Cả hai phía chỉ cần đưa cùng text/font/khung hình là ra cùng ảnh.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter

from core import anim_engine, karaoke_paint


def make_font(family, pixel_size, bold, italic=False, underline=False):
    font = QFont(family or "Arial")
    font.setPixelSize(max(6, int(round(pixel_size))))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    font.setUnderline(bool(underline))
    return font


def clip_font(clip):
    """Một định nghĩa font cho cả preview lẫn export."""
    return make_font(getattr(clip, "font_family", "Arial"),
                     max(8.0, float(getattr(clip, "font_size", 40.0))),
                     bool(getattr(clip, "font_bold", True)),
                     bool(getattr(clip, "font_italic", False)),
                     bool(getattr(clip, "font_underline", False)))


# Mười một trường style chữ nằm trên ClipModel; mặc định ở đây PHẢI khớp với
# mặc định trong core/timeline_model.py, nếu không project cũ thiếu key sẽ
# đọc ra giá trị khác giữa preview và export.
_STYLING_DEFAULTS = {
    "text_outline_color": "#000000",
    "text_outline_width": 0.0,
    "text_shadow_color": "#000000",
    "text_shadow_dx": 0.0,
    "text_shadow_dy": 0.0,
    "text_shadow_blur": 0.0,
    "text_box_color": "#000000",
    "text_box_alpha": 0.0,
    "text_box_radius": 8.0,
    "text_box_padding": 12.0,
    "text_align": "center",
}
_NUMBER_STYLING = ("text_outline_width", "text_shadow_dx", "text_shadow_dy",
                   "text_shadow_blur", "text_box_alpha", "text_box_radius",
                   "text_box_padding")


def text_style_of(clip):
    """Đọc mười một trường style của clip thành dict chuẩn hoá.

    Một hàm duy nhất cho cả Canvas preview lẫn FrameComposer export: hai bên
    phải dựng ra cùng một dict thì paint_animated_text mới ra cùng một ảnh.
    """
    out = {}
    for key, default in _STYLING_DEFAULTS.items():
        value = getattr(clip, key, default)
        out[key] = float(value) if key in _NUMBER_STYLING else value
    return out


def _styling_active(s):
    """True khi có ít nhất một hiệu ứng nền/bóng/viền cần lớp composite.

    text_align KHÔNG nằm ở đây: căn lề chỉ đổi hình thức drawText, đi theo
    đường vẽ trực tiếp mà không cần dựng lớp, nên bật riêng nó vẫn nhanh."""
    if not s:
        return False
    try:
        if float(s.get("text_outline_width", 0.0)) > 0.0:
            return True
        if float(s.get("text_box_alpha", 0.0)) > 0.0:
            return True
        if float(s.get("text_shadow_blur", 0.0)) > 0.0:
            return True
        if abs(float(s.get("text_shadow_dx", 0.0))) > 0.0:
            return True
        if abs(float(s.get("text_shadow_dy", 0.0))) > 0.0:
            return True
    except (TypeError, ValueError):
        return False
    return False


def _split_reveal(lines, reveal):
    """Cắt dần theo ký tự trên toàn khối chữ, giữ nguyên ngắt dòng."""
    if reveal >= 0.999:
        return lines
    budget = int(round(sum(len(l) for l in lines) * reveal))
    out = []
    for line in lines:
        if budget <= 0:
            out.append("")
            continue
        out.append(line[:budget])
        budget -= len(line)
    return out


def _blur_layer(layer, radius_px):
    try:
        import numpy as np
        import cv2
    except ImportError:
        return layer
    w, h = layer.width(), layer.height()
    img = layer.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    arr = np.frombuffer(raw, np.uint8).reshape((h, w, 4)).astype(np.float32)
    k = max(3, int(radius_px) * 2 + 1)
    blurred = cv2.GaussianBlur(arr, (k, k), 0)
    out = np.ascontiguousarray(np.clip(blurred, 0, 255).astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


_ALIGN_FLAGS = {
    "left": Qt.AlignmentFlag(Qt.AlignLeft | Qt.AlignVCenter),
    "right": Qt.AlignmentFlag(Qt.AlignRight | Qt.AlignVCenter),
    "center": Qt.AlignmentFlag(Qt.AlignHCenter | Qt.AlignVCenter),
}


def _align_of(align):
    return _ALIGN_FLAGS.get((align or "center").lower(), _ALIGN_FLAGS["center"])


def paint_animated_text(painter, text, font, color, frame_w, frame_h,
                        center_x, center_y, effect="none", p=0.0,
                        intensity=1.0, style="none", t=0.0, styling=None):
    """Vẽ khối chữ đã hoạt ảnh trong hệ toạ độ của khung hình đang vẽ.

    ``style`` là một khoá karaoke (core.karaoke_paint) — "none" nghĩa là chữ
    một màu như trước. ``p`` (tiến độ trong clip) quyết định QUÉT tới từ nào,
    ``t`` (giây cục bộ của clip) quyết định lửa chớp, màu cầu vồng xoay.
    Hai thứ đó nhân với nhau chứ không loại trừ: hoạt ảnh của anim_engine vẫn
    chạy đầy đủ trên khối chữ karaoke.

    ``styling`` là dict của core.text_paint.text_style_of: viền, bóng, hộp nền
    và căn lề. Không có style nào bật thì đi thẳng đường vẽ trực tiếp (không
    dựng lớp ảnh), nên bật tính năng không đánh thuế lên chữ thường dùng."""
    full = (text or "").split("\n")
    if not "".join(full).strip():
        return
    st = anim_engine.text_state(effect, p, intensity)
    lines = _split_reveal(full, st.reveal) if effect == "typewriter" else full
    if not "".join(lines).strip():
        return

    font_px = font.pixelSize()
    wave = effect == "wave" and st.wave_amp > 0.0
    karaoke = karaoke_paint.normalize_style(style)
    # Typewriter luôn ghim trái bất kể người dùng chọn gì: mép trái đứng yên
    # là thứ làm hiệu ứng gõ chữ đọc được.
    align = "left" if effect == "typewriter" else (styling or {}).get(
        "text_align", "center")

    painter.save()
    painter.setFont(font)
    painter.setPen(QColor(color))

    fm = painter.fontMetrics()
    line_h = max(1, int(fm.lineSpacing()))
    # Hộp chữ luôn đo theo VĂN BẢN ĐẦY ĐỦ: typewriter lớn dần trong cái hộp
    # đó chứ không nhảy vào giữa, và mép trái phải đứng yên.
    box_w = max(fm.horizontalAdvance(l) for l in full) or 1
    box_h = line_h * len(full)

    # ±1 trên trục nào là lệch trọn nửa khung hình cộng nửa hộp chữ, tức khối
    # chữ nằm hẳn ngoài mép đó.
    off_x = st.dx * (frame_w / 2.0 + box_w / 2.0)
    off_y = st.dy * (frame_h / 2.0 + box_h / 2.0)

    args = (fm, line_h, box_w, box_h, wave, st, font_px,
            align, karaoke, p, t, QColor(color))
    if _styling_active(styling):
        _paint_styled(painter, lines, args, styling, font, color,
                      center_x + off_x, center_y + off_y, st, font_px)
    elif st.blur > 0.0:
        margin = int(font_px * (1.0 + 2.0 * st.blur)) + 4
        layer_w = max(1, box_w + 2 * margin)
        layer_h = max(1, box_h + 2 * margin)
        layer = QImage(layer_w, layer_h, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setFont(font)
        lp.setPen(QColor(color))
        _paint_lines(lp, lines, layer_w / 2.0, layer_h / 2.0, *args)
        lp.end()
        layer = _blur_layer(layer, st.blur * font_px)
        painter.setOpacity(painter.opacity() * st.opacity)
        painter.drawImage(QRectF(center_x + off_x - layer_w / 2.0,
                                 center_y + off_y - layer_h / 2.0,
                                 layer_w, layer_h), layer)
    else:
        painter.setOpacity(painter.opacity() * st.opacity)
        painter.translate(center_x + off_x, center_y + off_y)
        if abs(st.scale - 1.0) > 1e-6:
            painter.scale(st.scale, st.scale)
        _paint_lines(painter, lines, 0.0, 0.0, *args)
    painter.restore()


def _silhouette(glyph, tint):
    """Lớp bóng đặc màu ``tint`` lấy nguyên alpha từ lớp glyph."""
    sil = glyph.copy()
    sp = QPainter(sil)
    sp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    sp.fillRect(sil.rect(), QColor(tint))
    sp.end()
    return sil


def _paint_styled(painter, lines, args, styling, font, color, cx, cy, st,
                  font_px):
    """Composite hộp nền → bóng → viền → chữ lên một lớp rồi blit theo animation.

    Dựng chữ vào một lớp ARGB trong suốt một lần, rồi lấy alpha của nó làm
    bóng và viền (đổ màu đặc qua _silhouette). Vì bóng/vền/hộp đều nằm trong
    cùng lớp, transform của anim_engine (vị trí, scale, opacity, blur) áp lên
    cả khối — preview và export đi đúng một đường nên cho ra cùng ảnh.
    """
    fm, line_h, box_w, box_h = args[0], args[1], args[2], args[3]
    outline_w = max(0.0, float(styling.get("text_outline_width", 0.0)))
    shadow_dx = float(styling.get("text_shadow_dx", 0.0))
    shadow_dy = float(styling.get("text_shadow_dy", 0.0))
    shadow_blur = max(0.0, float(styling.get("text_shadow_blur", 0.0)))
    box_alpha = min(1.0, max(0.0, float(styling.get("text_box_alpha", 0.0))))
    pad = float(styling.get("text_box_padding", 12.0)) if box_alpha > 0.0 else 0.0
    radius = float(styling.get("text_box_radius", 8.0))

    # Vùng đệm phải chứa trọn viền loang ra, bóng lệch + mờ, và hộp padding.
    spread = max(outline_w,
                 abs(shadow_dx) + shadow_blur,
                 abs(shadow_dy) + shadow_blur)
    margin = int(math.ceil(pad + spread)) + 4
    layer_w = max(1, int(box_w) + 2 * margin)
    layer_h = max(1, int(box_h) + 2 * margin)
    lcx, lcy = layer_w / 2.0, layer_h / 2.0

    # 1. Lớp glyph màu — nguồn alpha cho viền/bóng và là nét chữ sắc trên cùng.
    glyph = QImage(layer_w, layer_h, QImage.Format.Format_ARGB32_Premultiplied)
    glyph.fill(Qt.GlobalColor.transparent)
    gp = QPainter(glyph)
    gp.setFont(font)
    gp.setPen(QColor(color))
    _paint_lines(gp, lines, lcx, lcy, *args)
    gp.end()

    result = QImage(layer_w, layer_h, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    rp = QPainter(result)

    # 2. Hộp nền (lớp dưới cùng).
    if box_alpha > 0.0:
        bg = QColor(styling.get("text_box_color", "#000000"))
        bg.setAlphaF(box_alpha)
        rp.setPen(Qt.PenStyle.NoPen)
        rp.setBrush(QBrush(bg))
        bw = box_w + 2 * pad
        bh = box_h + 2 * pad
        rp.drawRoundedRect(QRectF(lcx - bw / 2.0, lcy - bh / 2.0, bw, bh),
                           max(0.0, radius), max(0.0, radius))

    # 3. Bóng đổ: silhouette lệch (dx,dy), làm mờ nếu có bán kính.
    has_shadow = (abs(shadow_dx) > 0.0 or abs(shadow_dy) > 0.0
                  or shadow_blur > 0.0)
    if has_shadow:
        sh = _silhouette(glyph, styling.get("text_shadow_color", "#000000"))
        if shadow_blur > 0.0:
            sh = _blur_layer(sh, shadow_blur)
        rp.setBrush(Qt.BrushStyle.NoBrush)
        rp.drawImage(QPointF(shadow_dx, shadow_dy), sh)

    # 4. Viền: vòng các bản silhouette màu viền quanh nét chữ, lấp kín mọi
    #    hướng (16 nấc) cho tới đúng bán kính outline_width.
    if outline_w > 0.0:
        ol = _silhouette(glyph, styling.get("text_outline_color", "#000000"))
        steps = max(1, int(round(outline_w)))
        rp.setBrush(Qt.BrushStyle.NoBrush)
        for rad in range(1, steps + 1):
            for k in range(16):
                ang = (math.tau / 16) * k
                rp.drawImage(QPointF(rad * math.cos(ang),
                                     rad * math.sin(ang)), ol)

    # 5. Nét chữ màu lên trên cùng.
    rp.setBrush(Qt.BrushStyle.NoBrush)
    rp.drawImage(QPointF(0.0, 0.0), glyph)
    rp.end()

    if st.blur > 0.0:
        result = _blur_layer(result, st.blur * font_px)

    painter.setOpacity(painter.opacity() * st.opacity)
    painter.translate(cx, cy)
    if abs(st.scale - 1.0) > 1e-6:
        painter.scale(st.scale, st.scale)
    painter.drawImage(QRectF(-result.width() / 2.0, -result.height() / 2.0,
                             result.width(), result.height()), result)


def _paint_lines(painter, lines, cx, cy, fm, line_h, box_w, box_h, wave, st,
                 font_px, align, style, sweep, t, base_color):
    top = cy - box_h / 2.0
    if style != "none" and not wave:
        # Karaoke vẽ theo từ nên tự lo phần xếp chữ; nhánh dưới đây chỉ vẽ cả
        # dòng một màu.
        _paint_karaoke(painter, lines, fm, line_h, box_w, box_h, cx, cy, style,
                       sweep, t, font_px, align, base_color)
        return
    for i, line in enumerate(lines):
        if not line:
            continue
        rect = QRectF(cx - box_w / 2.0, top + i * line_h, box_w, line_h)
        if wave:
            # Từng ký tự nhô theo sin nhưng cả dòng vẫn neo vào giữa hộp chữ.
            widths = [fm.horizontalAdvance(ch) for ch in line]
            x = rect.center().x() - sum(widths) / 2.0
            for index, ch in enumerate(line):
                adv = widths[index]
                if ch != " ":
                    dy = st.wave_amp * font_px * 0.5 * math.sin(
                        st.wave_phase + index * 0.55)
                    painter.drawText(QRectF(x, rect.top() + dy, adv, rect.height()),
                                     Qt.AlignCenter, ch)
                x += adv
        else:
            painter.drawText(rect, _align_of(align), line)


def _paint_karaoke(painter, lines, fm, line_h, box_w, box_h, cx, cy, style,
                   sweep, t, font_px, align, base_color):
    total = sum(len(karaoke_paint.word_boxes(fm, line)) for line in lines)
    lit = karaoke_paint.lit_count(total, sweep)
    # Cùng một hộp với nhánh vẽ cả dòng: bật kiểu karaoke không được làm dòng
    # chữ dịch một pixel nào, kể cả khi sweep=1.0 (mọi từ đều đã hát).
    top = cy - box_h / 2.0
    done = 0
    for i, line in enumerate(lines):
        boxes = karaoke_paint.word_boxes(fm, line)
        done_this_line = len(boxes)
        if not boxes:
            continue
        line_w = fm.horizontalAdvance(line)
        # Neo theo lề trong hộp box_w đúng như nhánh drawText cả dòng: dòng
        # ngắn nằm trái/phải/giữa mép hộp chứ không nhảy tuỳ bề rộng riêng.
        align_lower = (align or "center").lower()
        if align_lower == "left":
            left = cx - box_w / 2.0
        elif align_lower == "right":
            left = cx + box_w / 2.0 - line_w
        else:
            left = cx - line_w / 2.0
        line_rect = QRectF(left, top + i * line_h, line_w, line_h)
        for j, (word, wx, ww) in enumerate(boxes):
            k = done + j
            state = (karaoke_paint.LIT if k < lit
                     else karaoke_paint.ACTIVE if k == lit
                     else karaoke_paint.PENDING)
            karaoke_paint.paint_word(
                painter, QRectF(left + wx, line_rect.top(), ww, line_h), word,
                style, state, base_color, font_px, t, j, line_rect)
        done += done_this_line
