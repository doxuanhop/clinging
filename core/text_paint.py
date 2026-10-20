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

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

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


def paint_animated_text(painter, text, font, color, frame_w, frame_h,
                        center_x, center_y, effect="none", p=0.0,
                        intensity=1.0, style="none", t=0.0):
    """Vẽ khối chữ đã hoạt ảnh trong hệ toạ độ của khung hình đang vẽ.

    ``style`` là một khoá karaoke (core.karaoke_paint) — "none" nghĩa là chữ
    một màu như trước. ``p`` (tiến độ trong clip) quyết định QUÉT tới từ nào,
    ``t`` (giây cục bộ của clip) quyết định lửa chớp, màu cầu vồng xoay.
    Hai thứ đó nhân với nhau chứ không loại trừ: hoạt ảnh của anim_engine vẫn
    chạy đầy đủ trên khối chữ karaoke.
    """
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
            effect == "typewriter", karaoke, p, t, QColor(color))
    if st.blur > 0.0:
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


def _paint_lines(painter, lines, cx, cy, fm, line_h, box_w, box_h, wave, st,
                 font_px, left_align, style, sweep, t, base_color):
    top = cy - box_h / 2.0
    if style != "none" and not wave:
        # Karaoke vẽ theo từ nên tự lo phần xếp chữ; nhánh dưới đây chỉ vẽ cả
        # dòng một màu.
        _paint_karaoke(painter, lines, fm, line_h, box_w, box_h, cx, cy, style,
                       sweep, t, font_px, left_align, base_color)
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
        elif left_align:
            painter.drawText(QRectF(rect.left(), rect.top(), box_w, rect.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, line)
        else:
            painter.drawText(rect, Qt.AlignHCenter | Qt.AlignVCenter, line)


def _paint_karaoke(painter, lines, fm, line_h, box_w, box_h, cx, cy, style,
                   sweep, t, font_px, left_align, base_color):
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
        # Căn chỉnh đúng như nhánh vẽ cả dòng: AlignHCenter trên hộp box_w nghĩa
        # là dòng ngắn tự do nằm giữa theo bề rộng RIÊNG của nó.
        left = (cx - box_w / 2.0) if left_align else cx - line_w / 2.0
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
