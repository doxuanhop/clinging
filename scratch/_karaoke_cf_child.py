"""Một khớp bị cắt, trong bộ nhớ, cho karaoke_probe chạy thật.

Parent spawn process con cho từng mode; con nạp karaoke_probe như một module
(không phải __main__ nên nó không tự chạy), vá đúng MỘT hàm, rồi gọi main().
Không file nào trên đĩa bị sửa — mọi lỗi chỉ sống trong process con.

Mỗi mode nhắm vào MỘT gate. Đỏ vì lỗi khác coi như phản chứng thất bại.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mode = sys.argv[1] if len(sys.argv) > 1 else "clean"

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPen,  # noqa: E402
                           QPainter)

from core import karaoke_paint  # noqa: E402


def _old_fill_direction(painter, rect, word, space, stops, horizontal=False):
    """Đúng bản đầu của ``_fill``: tô gradient trước rồi DestinationIn bằng nét
    chữ. Qt bỏ qua composition mode khi vẽ chữ, nên đây là khối đặc."""
    font = painter.font()
    pad = max(2, int(max(8, font.pixelSize()) * 0.12))
    w = max(1, int(rect.width()) + 2 * pad)
    h = max(1, int(rect.height()) + 2 * pad)
    layer = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)
    if horizontal:
        start = pad - (rect.left() - space.left())
        grad = QLinearGradient(start, 0.0, start + space.width(), 0.0)
    else:
        start = pad - (rect.top() - space.top())
        grad = QLinearGradient(0.0, start, 0.0, start + space.height())
    for stop, color in stops:
        grad.setColorAt(stop, QColor(color))
    lp = QPainter(layer)
    lp.fillRect(layer.rect(), QBrush(grad))
    lp.setFont(font)
    lp.setPen(QPen(QColor(255, 255, 255)))
    lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    karaoke_paint._draw(lp, QRectF(pad, pad, rect.width(), rect.height()), word)
    lp.end()
    painter.drawImage(QPointF(rect.left() - pad, rect.top() - pad), layer)


def apply():
    orig_paint_word = karaoke_paint.paint_word

    if mode == "normalize":
        def norm(value):
            return str(value or "none").strip().lower()
        karaoke_paint.normalize_style = norm

    elif mode == "pending":
        # Khôi phục lỗi thật đã gặp: "outline" có màu pending riêng, sáng gần
        # bằng lúc hát -> trên nền tối, nhịp quét biến mất.
        def patched(painter, rect, word, style, state, base_color, font_px, t,
                    index, line_rect):
            if style == "outline" and state == karaoke_paint.PENDING:
                karaoke_paint._solid(painter, rect, word,
                                     karaoke_paint._shade(base_color, 0.85))
                return
            return orig_paint_word(painter, rect, word, style, state, base_color,
                                   font_px, t, index, line_rect)
        karaoke_paint.paint_word = patched

    elif mode == "geometry":
        def patched(painter, rect, word, style, state, base_color, font_px, t,
                    index, line_rect):
            return orig_paint_word(
                painter, QRectF(rect.left() + 6.0, rect.top(), rect.width(),
                                rect.height()), word, style, state, base_color,
                font_px, t, index, line_rect)
        karaoke_paint.paint_word = patched

    elif mode == "sweep":
        karaoke_paint.lit_count = lambda total, sweep: total

    elif mode == "staircase":
        # Hai trang thai thay vi bon: quyet dinh "bo qua mot tu" cua probe phai
        # do, vi day dung la loi khien ca dong chi sang len theo nua nhip.
        karaoke_paint.lit_count = lambda total, sweep: (
            total if sweep >= 0.5 else 0)

    elif mode == "layout":
        # Cộng dồn "advance(cả dòng đã đi) + advance(dấu cách)" thay vì advance
        # của tiền tố: khoảng trắng thật khác advance ký tự ' ' nên lệch cộng dồn.
        def boxes(fm, line):
            out, x = [], 0.0
            for chunk in line.split(" "):
                if not chunk:
                    continue
                out.append((chunk, int(round(x)), int(round(fm.horizontalAdvance(chunk)))))
                x += fm.horizontalAdvance(chunk) + fm.horizontalAdvance(" ") * 3
            return out
        karaoke_paint.word_boxes = boxes

    elif mode == "fill":
        karaoke_paint._fill = _old_fill_direction

    elif mode == "ring":
        def ring(painter, rect, word, color, radius, steps=karaoke_paint._RING):
            pen = QPen(QColor(color))
            pen.setWidthF(max(1.0, radius * 2.0))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            karaoke_paint._draw(painter, rect, word)
        karaoke_paint._ring = ring

    elif mode == "shadow":
        def patched(painter, rect, word, style, state, base_color, font_px, t,
                    index, line_rect):
            if style == "shadow" and state != karaoke_paint.PENDING:
                off = max(1.0, font_px * 0.055)
                karaoke_paint._solid(painter, rect, word, QColor(0, 0, 0, 190),
                                     dx=-off, dy=-off)
                karaoke_paint._solid(painter, rect, word, QColor(255, 255, 255))
                return
            return orig_paint_word(painter, rect, word, style, state, base_color,
                                   font_px, t, index, line_rect)
        karaoke_paint.paint_word = patched

    elif mode == "export":
        # Export không còn nhận kiểu karaoke: preview vẫn đẹp, file vẫn sai.
        from core.frame_composer import FrameComposer
        orig = FrameComposer._draw_text

        def patched(self, painter, clip, x, y, sx, sy, rot, opacity, local_time,
                    state=None):
            style = getattr(clip, "text_style", "none")
            clip.text_style = "none"
            try:
                return orig(self, painter, clip, x, y, sx, sy, rot, opacity,
                            local_time, state)
            finally:
                clip.text_style = style
        FrameComposer._draw_text = patched

    elif mode != "clean":
        raise SystemExit("mode khong ton tai: %s" % mode)


apply()

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "karaoke_probe_cf", os.path.join(ROOT, "scratch", "karaoke_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
sys.exit(probe.main())
