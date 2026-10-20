"""
core/aura_paint.py
Hào quang (aura) vẽ theo thời gian — MỘT đường vẽ duy nhất cho preview lẫn export.

Vì sao không nằm trong core/clip_effects.apply_color_effects: pipeline lọc màu đó
là hàm THUẦN trên pixel của RIÊNG khung clip, không nhận `t` và không vẽ được ra
ngoài biên ảnh. Aura thì ngược lại: nó là hạt bay, tia sét, vòng sáng, dải sóng
sống theo đồng hồ clip và tràn ra mép khung. Nên nó cần một seam riêng, và seam
đó phải nhận đúng hai thứ mà cả hai bên đều có sẵn: QPainter đang ở hệ toạ độ
clip + local_time.

Ràng buộc quan trọng nhất: mọi trạng thái phải suy ra giải tích từ `t`, không
được giữ mảng hạt mutable như bản web gốc. Lý do:

  * preview chạy theo nhịp chuột/timer, export chạy theo frame tuần tự. Nếu hạt
    tiến bằng cộng dồn mỗi lần vẽ thì hai bên cho hai quỹ đạo khác nhau, và tua
    lại một mốc thời gian sẽ ra một ảnh khác — đúng cái bug "xem một kiểu, xuất
    một kiểu" mà cả kiến trúc này đang chống.
  * mỗi hạt i có seed cố định, vị trí là frac(t/period + phase). Cùng `t` là
    cùng ảnh, không phụ thuộc lịch sử.

Độ sáng mô phỏng bằng nhiều nét loang chồng nhau (halo + core) thay vì
GaussianBlur mỗi khung hình: blur một lớp 1920x1080 ở 30fps là mất thời gian
thật trên máy cấu hình thấp, trong khi chồng nét cho cảm giác phát sáng tương
đương với chi phí không đổi.
"""

import math
import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

# Khoá params mà một hiệu ứng aura mang. clip_effects.PIXEL_KEYS quản lý họ
# lọc màu; họ aura đứng riêng nên gate vẫn phải đo được từng khoá.
AURA_KEYS = ("aura",)

_TAU = math.pi * 2.0
_MATRIX_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$@#&"


def _rng(*parts):
    """PRNG tất định theo bộ khoá — cùng khoá là cùng dãy số."""
    return random.Random("|".join(str(p) for p in parts))


def _frac(x):
    return x - math.floor(x)


def _rgba(color, alpha):
    r, g, b = color[:3]
    return QColor(int(r), int(g), int(b), int(max(0.0, min(1.0, alpha)) * 255))


# kind = hình thái vẽ, colors = bảng màu mặc định, margin = phần tràn ra ngoài
# biên clip tính theo cạnh ngắn nhất của khung (preview nới boundingRect theo
# số này, export dùng chính nó nên hai bên cùng vùng vẽ).
AURA_EFFECTS = {
    "fire": {
        "label": "Hỏa Diệm", "desc": "Hạt lửa bay lên từ mép dưới",
        "icon": "fa6s.fire", "kind": "sparks", "margin": 0.16,
        "colors": [(255, 138, 40), (255, 60, 30), (255, 214, 90)],
    },
    "electric": {
        "label": "Lôi Điện", "desc": "Viền sáng + tia sét giật quanh khung",
        "icon": "fa6s.bolt", "kind": "electric", "margin": 0.10,
        "colors": [(34, 211, 238), (255, 255, 255)],
    },
    "divine": {
        "label": "Thánh Quang", "desc": "Vòng hào quang lan ra từ tâm",
        "icon": "fa6s.sun", "kind": "rings", "margin": 0.12,
        "colors": [(255, 238, 102), (251, 191, 36)],
    },
    "shadow": {
        "label": "Hắc Ám", "desc": "Khói tím đen cuộn lên",
        "icon": "fa6s.moon", "kind": "smoke", "margin": 0.20,
        "colors": [(102, 0, 170), (40, 0, 70)],
    },
    "aurora": {
        "label": "Cực Quang", "desc": "Dải sóng xanh-lá-tím chảy ngang khung",
        "icon": "fa6s.asterisk", "kind": "ribbons", "margin": 0.06,
        "colors": [(51, 255, 153), (34, 211, 238), (168, 85, 247)],
    },
    "matrix": {
        "label": "Mã Ma Trận", "desc": "Mưa ký tự xanh rơi dọc khung",
        "icon": "fa6s.terminal", "kind": "matrix", "margin": 0.04,
        "colors": [(34, 197, 94), (134, 239, 172)],
    },
    "sakura": {
        "label": "Anh Đào Bay", "desc": "Cánh hoa hồng trôi chéo, có xoay",
        "icon": "fa6s.spa", "kind": "petals", "margin": 0.14,
        "colors": [(244, 114, 182), (251, 207, 232)],
    },
    "cyberpunk": {
        "label": "Neon Hồng Tím", "desc": "Hoa lửa hồng/cyan hai màu luân phiên",
        "icon": "fa6s.spray-can-sparkles", "kind": "sparks", "margin": 0.18,
        "colors": [(236, 72, 153), (6, 182, 212)],
    },
}


def aura_names():
    return list(AURA_EFFECTS)


def aura_spec(effects):
    """Trả về (tên, màu ghi đè, mật độ, cường độ) của aura cuối cùng trên clip.

    None nếu clip không có aura. Nhiều aura trên một clip là hợp lệ về dữ liệu
    nhưng vô nghĩa về hình ảnh, nên cái cuối thắng — đúng quy tắc mà
    apply_color_effects đang áp cho bộ lọc màu.
    """
    spec = None
    for effect in effects or []:
        params = getattr(effect, "params", None) or {}
        name = params.get("aura")
        if name in AURA_EFFECTS:
            spec = (name, params.get("aura_color", "") or "",
                    float(params.get("aura_density", 1.0)),
                    float(getattr(effect, "intensity", 1.0)))
    return spec


def aura_margin(rect, effects):
    """Số pixel aura tràn ra ngoài biên clip — công thức export dùng."""
    spec = aura_spec(effects)
    if not spec:
        return 0.0
    short = min(rect.width(), rect.height())
    return AURA_EFFECTS[spec[0]]["margin"] * short


# Vùng tràn rộng nhất trong registry — hiện Hắc Ám (0.20) đang giữ.
_MAX_AURA_MARGIN = max(effect["margin"] for effect in AURA_EFFECTS.values())


def aura_reserve(rect):
    """Vùng preview phải dành sẵn quanh khung clip cho mọi aura.

    boundingRect() của item KHÔNG được phụ thuộc clip.effects. Scene cache vùng
    của item lúc addToIndex và chỉ nhận được vùng mới qua
    prepareGeometryChange(); đổi rect sau lưng nó thì index hỏng và process
    abort giữa app.processEvents() — bấm liên tiếp bốn thẻ aura khác nhau trong
    một phiên là đủ tái hiện, không có traceback Python nào cả.
    """
    return _MAX_AURA_MARGIN * min(rect.width(), rect.height())


def paint_aura_for_effects(painter, rect, t, effects):
    """Điểm vào DUY NHẤT mà preview và export cùng gọi.

    Cả hai bên tự đưa rect mà mình vừa tô ảnh clip vào đó, nên aura bám đúng
    khung hình đã vẽ kể cả khi clip bị fit-letterbox trong rect.
    """
    spec = aura_spec(effects)
    if not spec:
        return
    paint_aura(painter, rect, t, spec[0], color=spec[1], density=spec[2],
               intensity=spec[3])


def paint_aura(painter, rect, t, name, color="", density=1.0, intensity=1.0):
    """Vẽ aura `name` quanh rect tại thời điểm t (giây, cục bộ theo clip).

    Painter phải đang ở hệ toạ độ của khung hình chứa rect (item local với
    preview, canvas với export) — hàm không đụng transform để hai bên tự lo
    phần xoay/thu phóng của chính mình.
    """
    effect = AURA_EFFECTS.get(name)
    if effect is None or rect.width() < 8 or rect.height() < 8:
        return
    intensity = max(0.0, min(1.0, float(intensity)))
    if intensity <= 0.0:
        return
    colors = effect["colors"]
    if color:
        parsed = QColor(color)
        if parsed.isValid():
            colors = [(parsed.red(), parsed.green(), parsed.blue())] + list(colors)
    density = max(0.15, min(2.5, float(density)))

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    kind = effect["kind"]
    try:
        if kind == "sparks":
            _paint_sparks(painter, rect, t, colors, density, intensity)
        elif kind == "smoke":
            _paint_smoke(painter, rect, t, colors, density, intensity)
        elif kind == "electric":
            _paint_electric(painter, rect, t, colors, intensity)
        elif kind == "rings":
            _paint_rings(painter, rect, t, colors, intensity)
        elif kind == "ribbons":
            _paint_ribbons(painter, rect, t, colors, intensity)
        elif kind == "matrix":
            _paint_matrix(painter, rect, t, colors, density, intensity)
        elif kind == "petals":
            _paint_petals(painter, rect, t, colors, density, intensity)
    finally:
        painter.restore()


# ── Hình thái vẽ ────────────────────────────────────────────────

def _paint_sparks(painter, rect, t, colors, density, intensity):
    """Hạt sáng bay lên: halo loang + core nhỏ, hai màu luân phiên như bản gốc."""
    count = int(26 * density)
    short = min(rect.width(), rect.height())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for i in range(count):
        r = _rng("sparks", i)
        x0 = r.random()
        phase = r.random()
        period = 1.5 + r.random() * 1.7
        drift = (r.random() - 0.5) * 0.14
        wobble = 0.008 + r.random() * 0.028
        wf = 0.5 + r.random() * 1.3
        size = (0.006 + r.random() * 0.012) * short
        u = _frac(t / period + phase)
        x = rect.left() + rect.width() * (
            x0 + drift * u + wobble * math.sin(_TAU * (wf * t + phase)))
        y = rect.bottom() + rect.height() * (0.06 - u * 1.12)
        color = colors[i % len(colors)]
        fade = (1.0 - u) * intensity
        painter.setBrush(_rgba(color, fade * 0.22))
        painter.drawEllipse(QRectF(x - size * 2.4, y - size * 2.4,
                                   size * 4.8, size * 4.8))
        painter.setBrush(_rgba(color, fade * 0.85))
        painter.drawEllipse(QRectF(x - size, y - size, size * 2, size * 2))


def _paint_smoke(painter, rect, t, colors, density, intensity):
    """Khói: blob lớn hơn, chậm hơn, to dần rồi tan — nền tối mới thấy rõ."""
    count = int(18 * density)
    short = min(rect.width(), rect.height())
    painter.setPen(Qt.PenStyle.NoPen)
    for i in range(count):
        r = _rng("smoke", i)
        x0 = r.random()
        phase = r.random()
        period = 2.4 + r.random() * 2.2
        drift = (r.random() - 0.5) * 0.10
        start = (0.012 + r.random() * 0.026) * short
        u = _frac(t / period + phase)
        x = rect.left() + rect.width() * (x0 + drift * u)
        y = rect.bottom() + rect.height() * (0.04 - u * 1.05)
        size = start * (1.0 + 1.8 * u)
        alpha = (1.0 - u) * 0.30 * intensity
        color = colors[i % len(colors)]
        painter.setBrush(_rgba(color, alpha * 0.45))
        painter.drawEllipse(QRectF(x - size * 1.6, y - size * 1.6,
                                   size * 3.2, size * 3.2))
        painter.setBrush(_rgba(color, alpha))
        painter.drawEllipse(QRectF(x - size, y - size, size * 2, size * 2))


def _jagged_path(painter, x1, y1, x2, y2, rng, steps=6, amp=12.0):
    """Đường gấp khúc giữa hai điểm, lệch vuông góc ngẫu nhiên theo seed.

    Bản gốc làm đúng như vậy (cộng nhiễu vuông góc trên từng đoạn) nên sét mới
    có răng cưa thay vì là một đường thẳng phát sáng.
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = dy / length, -dx / length
    path = QPainterPath()
    path.moveTo(x1, y1)
    for s in range(1, steps + 1):
        f = s / steps
        off = 0.0 if s == steps else (rng.random() - 0.5) * 2.0 * amp
        path.lineTo(x1 + dx * f + nx * off, y1 + dy * f + ny * off)
    painter.drawPath(path)


def _paint_electric(painter, rect, t, colors, intensity):
    """Viền khung phát sáng + tia sét đánh xuống từ mép trên, giật theo nhịp."""
    tint = colors[0]
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    box = rect.adjusted(-6, -6, 6, 6)
    for width, alpha in ((14.0, 0.16), (7.0, 0.30), (2.5, 0.85)):
        pen = QPen(_rgba(tint if width > 3 else (255, 255, 255),
                         alpha * intensity), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawRoundedRect(box, 10, 10)

    tick = int(t * 14.0)
    r = _rng("electric", tick)
    if r.random() < 0.55:
        x = rect.left() + rect.width() * r.random()
        pen = QPen(_rgba((255, 255, 255), 0.9 * intensity), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        _jagged_path(painter, x, rect.top() - 10,
                     x + (r.random() - 0.5) * rect.width() * 0.25,
                     rect.top() + rect.height() * (0.25 + r.random() * 0.5),
                     _rng("bolt", tick))


def _paint_rings(painter, rect, t, colors, intensity):
    """Vòng sáng đồng tâm lan ra rồi mờ dần — nhịp 4 vòng một chu kỳ."""
    cx = rect.center().x()
    cy = rect.center().y()
    reach = max(rect.width(), rect.height()) * 0.62
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for i in range(4):
        u = _frac(t / 2.2 + i / 4.0)
        radius = 12.0 + u * reach
        pen = QPen(_rgba(colors[i % len(colors)],
                         (1.0 - u) * 0.75 * intensity), 3.0)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(cx - radius, cy - radius,
                                   radius * 2, radius * 2))


def _paint_ribbons(painter, rect, t, colors, intensity):
    """Dải sóng sin chảy ngang khung, cộng màu (screen) và loang ba lớp."""
    bands = ((0.25, 0.008, 1.1, 40.0, 45.0), (0.40, 0.010, 0.7, 30.0, 50.0),
             (0.55, 0.007, 1.4, 50.0, 60.0))
    short = min(rect.width(), rect.height())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setClipRect(rect)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for index, (y_off, freq, speed, amp, thickness) in enumerate(bands):
        color = colors[index % len(colors)]
        amp *= short / 720.0
        thickness *= short / 720.0
        base = rect.top() + rect.height() * y_off
        for layer, (grow, alpha) in enumerate(((34.0, 0.06), (16.0, 0.10),
                                               (0.0, 0.16))):
            path = QPainterPath()
            first = True
            for x in range(int(rect.left()), int(rect.right()) + 1, 12):
                y = (base + amp * math.sin(x * freq + t * speed)
                     + 15.0 * math.cos(x * 0.003 - t * 0.4)
                     - grow - thickness / 2.0)
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)
            for x in range(int(rect.right()), int(rect.left()) - 1, -12):
                y = (base + amp * math.sin(x * freq + t * speed)
                     + 15.0 * math.cos(x * 0.003 - t * 0.4)
                     + grow + thickness / 2.0)
                path.lineTo(x, y)
            path.closeSubpath()
            painter.setBrush(_rgba(color, alpha * intensity))
            painter.drawPath(path)


def _paint_matrix(painter, rect, t, colors, density, intensity):
    """Mưa ký tự: mỗi cột có tốc độ + pha riêng, đầu sáng đuôi mờ."""
    short = min(rect.width(), rect.height())
    size = max(11.0, 0.026 * short)
    font = QFont("Consolas")
    font.setPixelSize(int(size))
    font.setBold(True)
    font.setStyleHint(QFont.StyleHint.Monospace)
    painter.setFont(font)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setClipRect(rect)
    columns = max(4, int(rect.width() / (size * 1.55)))
    trail = 7
    tick = int(t * 9.0)
    for c in range(columns):
        r = _rng("matrix", c)
        speed = 0.16 + r.random() * 0.30
        phase = r.random()
        x = rect.left() + (c + 0.5) * rect.width() / columns
        head = rect.top() + _frac(t * speed + phase) * (rect.height() + size * trail)
        # Vệt đuôi vẽ trước bằng chữ nhật, KHÔNG phụ thuộc font: máy không có
        # font monospace (nền offscreen, hoặc font đã gỡ) vẫn còn mưa xanh, chỉ
        # mất mấy ký tự. Nếu dựa hết vào drawText thì hiệu ứng thành số 0 mà
        # không có lỗi nào được báo.
        band = QRectF(x - size * 0.55, rect.top(), size * 1.1,
                      max(0.0, head - rect.top()))
        painter.fillRect(band, _rgba(colors[0], 0.10 * intensity))
        painter.fillRect(QRectF(x - size * 0.55, head - size * 0.7,
                                size * 1.1, size * 1.4),
                         _rgba((255, 255, 255), 0.55 * intensity))
        for k in range(trail):
            y = head - k * size * 1.25
            if y < rect.top() - size or y > rect.bottom() + size:
                continue
            if k == 0:
                color, alpha = (255, 255, 255), 0.95
            else:
                color = colors[0]
                alpha = 0.65 * (1.0 - k / trail)
            ch = _MATRIX_CHARS[_rng("glyph", c, k, tick).randrange(
                len(_MATRIX_CHARS))]
            painter.setPen(_rgba(color, alpha * intensity))
            painter.drawText(QRectF(x - size, y - size, size * 2.0, size * 1.4),
                             Qt.AlignmentFlag.AlignHCenter
                             | Qt.AlignmentFlag.AlignVCenter, ch)


def _paint_petals(painter, rect, t, colors, density, intensity):
    """Cánh hoa bay chéo từ phải sang trái, rơi dần và tự xoay."""
    count = int(22 * density)
    short = min(rect.width(), rect.height())
    painter.setPen(Qt.PenStyle.NoPen)
    for i in range(count):
        r = _rng("petals", i)
        y0 = -0.1 + r.random() * 1.1
        phase = r.random()
        period = 2.6 + r.random() * 2.6
        vx = -(0.9 + r.random() * 0.9)
        vy = 0.35 + r.random() * 0.5
        spin = (r.random() - 0.5) * 3.2
        size = (0.010 + r.random() * 0.012) * short
        u = _frac(t / period + phase)
        x = rect.right() + short * 0.15 + vx * period * u * rect.width() * 0.42
        y = rect.top() + short * 0.1 + (y0 - 0.1 + vy * period * u) * rect.height() * 0.5
        alpha = intensity * (1.0 - max(0.0, (u - 0.75) / 0.25)) * 0.85
        painter.save()
        painter.translate(x, y)
        painter.rotate(math.degrees(spin * t + phase * _TAU))
        painter.setBrush(_rgba(colors[i % len(colors)], alpha * 0.30))
        painter.drawEllipse(QRectF(-size * 2.0, -size * 1.5,
                                   size * 4.0, size * 3.0))
        painter.setBrush(_rgba(colors[i % len(colors)], alpha))
        painter.drawEllipse(QRectF(-size * 1.5, -size * 0.8,
                                   size * 3.0, size * 1.6))
        painter.restore()
