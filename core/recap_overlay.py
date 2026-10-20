"""
core/recap_overlay.py
Lớp phủ recap CẤP DỰ ÁN: viền màu, nền kính mờ + chỉnh sáng, tâm ngắm, badge REC.

Vì sao là một module riêng (giống aura_paint):
  * Đây là thứ vẽ lên TOÀN khung hình, không gắn với một clip nào, nên nó không
    thể sống trong core.clip_effects (lọc màu theo clip, không có đồng hồ).
  * Preview và export phải ra cùng một ảnh. Cả hai gọi đúng một hàm ở dưới,
    đưa vào (painter, rộng, cao, settings, t) — không có nhánh riêng cho bên nào.
  * Mọi thứ dẫn xuất từ t một cách giải tích (nhịp nhấp REC = sin(t*4)), nên
    tua tới lui cho ra đúng khung, và export tuần tự khớp preview.

Chữ REC vẽ bằng QFont: trên máy này nền offscreen có 0 họ chữ, nên mọi phép đo
trong gate chỉ dựa vào chấm đỏ + vạch đỏ đỉnh, không dựa vào glyph.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRadialGradient

# Nét viền mặc định lấy đúng màu của bản tham chiếu.
BORDER_SWATCHES = (
    "#3673FE", "#FF3B3B", "#FF8A00", "#FFD400", "#3DDC5C", "#00E5D0",
    "#00CFFF", "#7C5CFF", "#C77DFF", "#FF4FA3", "#FFFFFF", "#0B0B0F",
)

RETICLE_SHAPES = ("cross", "circle", "scope", "dot", "tactical")

RETICLE_LABELS = {
    "cross": "Chữ thập +",
    "circle": "Vòng tròn",
    "scope": "Scope",
    "dot": "Chấm tâm",
    "tactical": "Chiến thuật",
}

# Mặc định = bản tham chiếu lúc mở trang: tắt hết, người dùng bật từng lớp.
OVERLAY_DEFAULTS = {
    "enabled": False,
    "glass": False,          # nền kính mờ + sáng nền (blur + brightness)
    "bg_brightness": 0.35,   # 0..1  (tham chiếu: 35)
    "bg_blur": 35.0,         # px ở khung 720 rộng, scale theo khung
    "border": False,
    "border_color": "#3673FE",
    "border_width": 4.0,     # px ở khung 720
    "reticle": False,
    "reticle_shape": "cross",
    "reticle_color": "#00FFFF",
    "rec": False,
    "rec_label": "",         # rỗng = suy từ kích thước dự án + rec_fps
    "rec_fps": 0,            # fps của bản xuất; 0 = nhãn chỉ ghi độ phân giải
}

# Tham chiếu vẽ trên khung 720 px; mọi số đo dưới đây quy về đơn vị đó.
_REF_SHORT = 720.0


def normalize(settings) -> dict:
    """Điền khoá còn thiếu + kẹp giá trị về miền hợp lệ.

    File .clinq của người dùng cũ không có mục này, nên mọi khoá phải có mặc định
    — không được để paint() đọc phải None.
    """
    out = dict(OVERLAY_DEFAULTS)
    for key, value in (settings or {}).items():
        if key in out:
            out[key] = value
    out["bg_brightness"] = max(0.0, min(1.0, float(out["bg_brightness"])))
    out["bg_blur"] = max(0.0, float(out["bg_blur"]))
    out["border_width"] = max(1.0, float(out["border_width"]))
    if out["reticle_shape"] not in RETICLE_SHAPES:
        out["reticle_shape"] = "cross"
    return out


def overlay_active(settings) -> bool:
    s = normalize(settings)
    return bool(s["enabled"]) and any(
        s[key] for key in ("glass", "border", "reticle", "rec"))


def resolution_label(w, h, settings) -> str:
    """Nhãn góc dưới của badge REC.

    Tính từ KHUNG DỰ ÁN chứ không từ kích thước file xuất, để ô xem thử và video
    xuất ra ghi cùng một chữ — đây là chỗ duy nhất sinh ra nhãn đó.
    """
    s = normalize(settings)
    label = (s["rec_label"] or "").strip()
    if label:
        return label
    fps = int(s["rec_fps"] or 0)
    short = int(min(w, h))
    return "%dp%s" % (short, (" %dfps" % fps) if fps else "")


def _scale(w, h):
    """Hệ số phóng số đo từ khung 720 của tham chiếu sang khung đang vẽ."""
    return max(0.2, min(w, h) / _REF_SHORT)


def content_rect(w, h, settings):
    """Rect nội dung sắc nét khi bật nền kính mờ — thu vào trong viền.

    Khi tắt glass thì trả về nguyên khung hình, nên đường vẽ chung không cần
    nhánh if nào ở nơi gọi.
    """
    s = normalize(settings)
    if not (s["enabled"] and s["glass"]):
        return QRectF(0, 0, w, h)
    k = _scale(w, h)
    inset = 48.0 * k
    bw = s["border_width"] * k
    return QRectF(inset + bw, inset + bw,
                  max(1.0, w - 2 * (inset + bw)), max(1.0, h - 2 * (inset + bw)))


def blur_proxy(image: QImage, columns: int = 28) -> QImage:
    """Làm mờ kiểu 'kính mờ' bằng hạ/phóng độ phân giải, không convolution.

    GaussianBlur mỗi khung cho 1080p là thứ máy cấu hình thấp không trả nổi.
    Xuống còn `columns` px rồi phóng lên cho đúng chất mờ loang của bản gốc với
    chi phí cố định, và hai đường preview/export đi qua đúng hàm này nên giống
    nhau từng pixel.
    """
    if image.isNull():
        return image
    w = max(2, min(columns, image.width()))
    h = max(2, int(w * image.height() / max(1, image.width())))
    small = image.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return small.scaled(image.width(), image.height(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def paint_backdrop(painter, w, h, content: QImage, settings):
    """Nền kính mờ tối: ảnh loang + nhân sáng + vignette hướng tâm.

    Đưa `content` (ảnh đã dựng xong) vào, hàm tự lo phần mờ/tối rồi vẽ ra TOÀN
    khung hình. Nơi gọi sau đó vẽ lại content sắc vào trong content_rect().
    """
    s = normalize(settings)
    if content.isNull():
        return
    k = _scale(w, h)
    columns = max(6, int(28.0 * (s["bg_blur"] / 35.0)))
    soft = blur_proxy(content, columns)

    # brightness(d) của canvas 2D ~= nhân hệ số; làm bằng QPainter không cần numpy.
    painter.save()
    painter.setOpacity(1.0)
    painter.drawImage(0, 0, soft)
    brightness = s["bg_brightness"]
    if brightness < 1.0:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        tone = 255 * max(0.0, min(1.0, brightness))
        painter.fillRect(QRectF(0, 0, w, h), QColor(int(tone), int(tone), int(tone)))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    # slightly punch the saturation like the reference's saturate(1.1)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setOpacity(0.06)
    painter.drawImage(0, 0, soft)
    painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    # vignette hướng tâm: trong gần như không tối, ngoài tối theo 0.9 - 0.6*d
    grad_center = QPointF(w / 2.0, h / 2.0)
    inner = h * 0.2
    outer = max(inner + 1.0, h * 0.8)
    edge = max(0.1, 0.9 - brightness * 0.6)
    grad = QRadialGradient(grad_center, outer)
    grad.setColorAt(0.0, QColor(0, 0, 0, int(0.10 * 255)))
    grad.setColorAt(1.0, QColor(0, 0, 0, int(edge * 255)))
    painter.setBrush(grad)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(grad_center, outer, outer)
    painter.restore()


def paint_overlay(painter, w, h, settings, t: float = 0.0, resolution_label: str = ""):
    """Vẽ viền màu + tâm ngắm + badge REC lên trên cùng của khung hình.

    t là giây của timeline (để REC nhấp nhịp và đếm mm:ss). Hàm không đụng
    transform của painter nên nơi gọi tự quyết định toạ độ thiết bị.
    """
    s = normalize(settings)
    if not s["enabled"]:
        return
    k = _scale(w, h)
    if s["border"]:
        _paint_border(painter, w, h, s, k)
    if s["reticle"]:
        _paint_reticle(painter, w, h, s, k)
    if s["rec"]:
        _paint_rec(painter, w, h, s, k, t, resolution_label)


# ── từng lớp ────────────────────────────────────────────────────

def _glow_pen(color: QColor, width: float):
    """Bút phát sáng: nhiều lớp nét, KHÔNG dùng effect Gaussian mỗi khung."""
    pens = []
    for step, alpha in ((3.0, 0.16), (2.0, 0.30), (1.0, 1.0)):
        pen = QPen(color)
        pen.setWidthF(max(1.0, width * step if step > 1 else width))
        if step > 1:
            c = QColor(color)
            c.setAlphaF(alpha)
            pen.setColor(c)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pens.append(pen)
    return pens


def _paint_border(painter, w, h, s, k):
    color = QColor(s["border_color"])
    if not color.isValid():
        color = QColor("#3673FE")
    width = s["border_width"] * k
    radius = 24.0 * k
    # Viền nằm sát mép trong của khung, chừa nửa nét để không bị cắt.
    pad = width / 2.0 + 2 * k
    rect = QRectF(pad, pad, max(1.0, w - 2 * pad), max(1.0, h - 2 * pad))
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for pen in _glow_pen(color, width):
        painter.setPen(pen)
        painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def _paint_reticle(painter, w, h, s, k):
    color = QColor(s["reticle_color"])
    if not color.isValid():
        color = QColor("#00FFFF")
    cx, cy = w / 2.0, h / 2.0
    shape = s["reticle_shape"]
    painter.save()
    pen = QPen(color)
    pen.setWidthF(2.0 * k)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    # Mỗi hình tự đặt brush: để brush còn lại là màu thì ring() sẽ tô ĐẦY và
    # tâm ngắm biến thành một đốm tròn thay vì vòng nét.
    def dot(r):
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), r * k, r * k)

    def ring(r, width=2.0, alpha=1.0):
        c = QColor(color)
        c.setAlphaF(alpha)
        p = QPen(c)
        p.setWidthF(width * k)
        painter.setPen(p)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r * k, r * k)

    def arm(axis, a, b):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if axis == "v":
            painter.drawLine(QPointF(cx, cy - a * k), QPointF(cx, cy - b * k))
            painter.drawLine(QPointF(cx, cy + a * k), QPointF(cx, cy + b * k))
        else:
            painter.drawLine(QPointF(cx - a * k, cy), QPointF(cx - b * k, cy))
            painter.drawLine(QPointF(cx + a * k, cy), QPointF(cx + b * k, cy))

    if shape == "cross":
        arm("v", 8, 28)
        arm("h", 8, 28)
        dot(2)
    elif shape == "circle":
        ring(20)
        dot(3)
    elif shape == "scope":
        ring(26)
        arm("v", 14, 40)
        arm("h", 14, 40)
        dot(2)
    elif shape == "dot":
        dot(4)
        ring(8, width=1.0, alpha=0.5)
    else:  # tactical
        ring(30)
        ring(22, width=0.8, alpha=0.4)
        arm("v", 16, 44)
        arm("h", 16, 44)
        p3 = QPen(color)
        p3.setWidthF(3.0 * k)
        painter.setPen(p3)
        for off in (-30.0, 30.0):
            painter.drawLine(QPointF(cx + off * k, cy - 3 * k),
                             QPointF(cx + off * k, cy + 3 * k))
            painter.drawLine(QPointF(cx - 3 * k, cy + off * k),
                             QPointF(cx + 3 * k, cy + off * k))
        painter.setPen(QPen(color))
        dot(2)
    painter.restore()


def _paint_rec(painter, w, h, s, k, t, resolution_label):
    """Badge REC: chấm đỏ nhấp nhịp, mm:ss, vạch đỏ đỉnh, nhãn độ phân giải."""
    pulse = 0.85 + 0.15 * math.sin(t * 4.0)
    chip = QRectF(16 * k, 16 * k, 110 * k, 28 * k)
    label = resolution_label or s["rec_label"]

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 128))
    painter.drawRoundedRect(chip, 6 * k, 6 * k)

    red = QColor(255, 0, 0)
    red.setAlphaF(max(0.05, min(1.0, pulse)))
    painter.setBrush(red)
    painter.drawEllipse(QPointF(chip.left() + 16 * k, chip.center().y()), 5 * k, 5 * k)

    font = QFont("Courier New")
    font.setBold(True)
    font.setPixelSize(max(6, int(10 * k)))
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRectF(chip.left() + 28 * k, chip.top(), 30 * k, chip.height()),
                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "REC")
    painter.drawText(QRectF(chip.left() + 62 * k, chip.top(), 44 * k, chip.height()),
                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                     _mmss(t))

    # vạch đỏ chạy dọc mép trên — thứ dễ đo nhất trong gate vì không cần font
    line = QColor(220, 0, 0)
    line.setAlphaF(0.6)
    pen = QPen(line)
    pen.setWidthF(2.0 * k)
    painter.setPen(pen)
    painter.drawLine(QPointF(0, pen.widthF() / 2.0), QPointF(w, pen.widthF() / 2.0))

    if label:
        badge = QRectF(w - 140 * k, h - 34 * k, 124 * k, 20 * k)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 102))
        painter.drawRoundedRect(badge, 4 * k, 4 * k)
        small = QFont("Courier New")
        small.setPixelSize(max(5, int(8 * k)))
        painter.setFont(small)
        c = QColor(255, 255, 255)
        c.setAlphaF(0.6)
        painter.setPen(c)
        painter.drawText(badge.adjusted(-6 * k, 0, -6 * k, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         label)
    painter.restore()


def _mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return "%02d:%02d" % (total // 60, total % 60)
