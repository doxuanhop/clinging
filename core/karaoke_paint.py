"""
core/karaoke_paint.py
Tám kiểu phụ đề karaoke + quét sáng theo TỪNG TỪ — một đường vẽ cho preview lẫn export.

Vì sao tách khỏi core/anim_engine: anim_engine mô tả hình HỌC của cả khối chữ
(vị trí, tỷ lệ, độ mờ, reveal theo ký tự), còn karaoke mô tả MÀU của từng từ
trong khối đó. Hai thứ độc lập nên nhân vào nhau: chữ vẫn chạy wave mà vẫn quét
sáng được. Gộp chung một hàm state sẽ thành tổ hợp 8x hiệu ứng.

Ràng buộc như mọi seam vẽ khác của repo:
  * Mọi trạng thái suy ra giải tích từ (sweep, t). Không bộ đếm, không random
    toàn cục, không trạng thái giữ giữa hai lần vẽ — cùng cặp (sweep, t) ra
    cùng một ảnh, dù là lần vẽ thứ nhất hay thứ chín mươi, preview hay export.
  * Không đổi hình HỌC của chữ: mỗi từ vẽ trong rect đúng bằng bề rộng của nó
    với căn chỉnh y hệt nhánh vẽ cả dòng, nên bật/tắt kiểu không làm dòng chữ
    dịch một pixel nào (đo ở sweep=0, nơi mọi từ còn pending).

Ba sự thật về QPainter trên máy này, ĐÃ ĐO chứ không suy ra từ tài liệu, và chúng
quyết định toàn bộ kỹ thuật vẽ dưới đây:
  1. drawText chỉ dùng MÀU của bút. Bề rộng bút bị bỏ qua hoàn toàn (bút 1px và
     6px cho ra đúng cùng số pixel), nên không có chuyện "nét viền đậm";
  2. brush của painter không tô được chữ — setBrush(gradient) + drawText cho ra
     0 pixel, kể cả brush đặc; và chiều ngược của ý tưởng đó cũng hỏng: đặt
     composition mode RỒI mới drawText thì mode bị bỏ qua (DestinationIn sau
     một nền đặc không xoá được pixel nào). Tô màu chữ vì thế phải theo một
     chiều duy nhất: vẽ nét chữ trước, rồi SourceIn phủ màu lên;
  3. QPainterPath.addText thì tô được bằng fillPath, nhưng trên nền font dự
     phòng (headless không còn font nào) nó trả về HÌNH CHỮ NHẬT thay vì đường
     viền chữ — tức là không kiểm chứng được bằng ảnh bằng chứng.

Vì vậy: hào quang/quang viền làm bằng NHIỀU BẢN Sao LỆCH NHỎ của chính nét chữ
(kiểu "poor man's glow"): các bản lệch chìa ra ngoài thân chữ thành quầng sáng
thật, chi phí là vài chục drawText ngắn cho một dòng, không phải GaussianBlur
cả lớp 1920x1080 mỗi khung hình. Chỉ riêng hai kiểu chuyển sắc (lửa, chuyển sắc)
phải qua lớp che ở ``_fill``.
"""

import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPen)

_WORD_RE = re.compile(r"\S+")

# (khoá, nhãn tiếng Việt trong hộp chọn). "none" không nằm ở đây: đó là giá trị
# mặc định, nghĩa là "vẽ như chữ thường".
KARAOKE_STYLES = (
    ("glow", "Hào quang trắng"),
    ("flame", "Lửa"),
    ("neon", "Neon"),
    ("gradient", "Chuyển sắc"),
    ("rainbow", "Cầu vồng"),
    ("shadow", "Đổ bóng"),
    ("outline", "Viền chữ"),
    ("soft", "Nhẹ nhàng"),
)

STYLE_KEYS = tuple(key for key, _ in KARAOKE_STYLES)
STYLE_LABELS = {key: name for key, name in KARAOKE_STYLES}

PENDING, ACTIVE, LIT = "pending", "active", "lit"

# 8 hướng lệch đều nhau; bán kính tính theo cỡ chữ nên quầng sáng không đổi
# hình khi người dùng phóng to thu nhỏ cỡ chữ.
_RING = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
         (0.707, 0.707), (-0.707, 0.707), (0.707, -0.707), (-0.707, -0.707))

# Từ ĐANG HÁT nhấp nháy chậm theo đồng hồ clip — giải tích, không tích luỹ.
_ACTIVE_PULSE = 2.4

# Quầng lửa: (bán kính khi đã hát xong, gốc khi ĐANG HÁT, biên độ nhấp nháy,
# alpha). Bốn số này là MỘT bộ, đo bằng scratch/karaoke_flame_density_probe.py:
# quầng là 8 bản sao lệch của nét chữ chồng nhau, nên alpha hiệu dụng ở giữa
# thân chữ là 1-(1-a/255)^8. Với alpha 90 con số đó là 0.95 — tức mọi lỗ chữ
# (a, o, u) bị lấp kín và từ đang hát thành một KHỐI cam đặc, kể cả ở 40px.
# Bán kính nhỏ hơn cũng không cứu được nếu còn alpha đó; hai thứ phải đi đôi.
# Bán kính 0.03/0.045 và alpha 60 là bộ duy nhất trong dải đã thử (5 bộ, xem
# scratch/karaoke_flame_density_probe.py) vừa giữ được quầng lửa (+85..+420
# pixel mực so với chữ thường ở 12->40px) vừa giữ lỗ chữ mở (>=2 lỗ ở MỌI khổ).
# Alpha 90 cũ cho 0 lỗ ở mọi khổ: đó là khối đặc.
_FLAME_HALO = (0.03, 0.045, 0.02, 60)


def normalize_style(value):
    """Khoá hợp lệ hoặc "none". Giá trị rác từ file cũ không được làm hỏng bản vẽ."""
    key = str(value or "none").strip().lower()
    return key if key in STYLE_KEYS else "none"


def word_boxes(fm, line):
    """[(từ, x_trái, bề_rộng)] tính từ 0, theo ĐÚNG vị trí Qt xếp chữ.

    Vị trí lấy bằng advance của TIỀN TỐ ("Xin ch" -> đo tới đúng ký tự đó"),
    không phải "advance của từ + advance dấu cách". Đã đo trên máy này: với font
    dự phòng, khoảng trắng thật trong dòng khác advance của ký tự ' ', nên cộng
    dồn bị lệch tới 40px — karaoke sẽ vẽ chữ ĐÈN LÊN sai chỗ so với chữ thường.
    """
    out = []
    for match in _WORD_RE.finditer(line):
        word = match.group()
        out.append((word, fm.horizontalAdvance(line[:match.start()]),
                    fm.horizontalAdvance(word)))
    return out


def lit_count(total, sweep):
    """Số từ đã hát xong. Phần tử thứ đúng bằng giá trị này là từ ĐANG HÁT."""
    if total <= 0:
        return 0
    return max(0, min(total, int(math.floor(
        max(0.0, min(1.0, sweep)) * (total + 1) + 1e-9))))


def _shade(base, factor, alpha=255):
    c = QColor(base)
    return QColor(min(255, int(c.red() * factor)),
                  min(255, int(c.green() * factor)),
                  min(255, int(c.blue() * factor)), alpha)


def _place(rect, dx, dy):
    return QRectF(rect.left() + dx, rect.top() + dy, rect.width(), rect.height())


def _draw(painter, rect, word, dx=0.0, dy=0.0):
    """Mọi nét của một từ đi qua đây: cùng rect, cùng AlignVCenter như nhánh
    vẽ cả dòng, nên hình học của dòng chữ không đổi khi bật kiểu."""
    painter.drawText(_place(rect, dx, dy),
                     Qt.AlignLeft | Qt.AlignVCenter, word)


def _solid(painter, rect, word, color, dx=0.0, dy=0.0):
    painter.setPen(QPen(QColor(color)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _draw(painter, rect, word, dx, dy)


def _ring(painter, rect, word, color, radius, steps=_RING):
    """Quầng sáng: vẽ chữ ở nhiều hướng lệch quanh chỗ của nó.

    Bán kính 0 thì đây chính là một nét chữ thường — các kiểu dùng chung một
    hàm để không có nhánh "không quầng" riêng dễ lệch nhau.
    """
    c = QColor(color)
    painter.setPen(QPen(c))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if radius <= 0.0:
        _draw(painter, rect, word)
        return
    for ux, uy in steps:
        _draw(painter, rect, word, ux * radius, uy * radius)


def _fill(painter, rect, word, space, stops, horizontal=False):
    """Chữ tô bằng gradient: VẼ NÉT CHỮ TRƯỚC, rồi SourceIn phủ màu lên.

    Chiều ngược lại (tô gradient rồi DestinationIn bằng nét chữ) là một vòng
    lặp RỖNG trên Qt raster: nét chữ vẽ bằng bút BỊ BỎ QUA hoàn toàn khi đặt
    composition mode. Đã đo trên lớp 200x60: fill gradient rồi mới bật
    DestinationIn thì alpha vẫn 255/12000 pixel (khối đặc); vẽ chữ trước rồi
    SourceIn bằng gradient thì còn đúng 943 pixel của nét chữ.
    """
    font = painter.font()
    pad = max(2, int(max(8, font.pixelSize()) * 0.12))
    w = max(1, int(rect.width()) + 2 * pad)
    h = max(1, int(rect.height()) + 2 * pad)
    layer = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)

    lp = QPainter(layer)
    lp.setRenderHint(QPainter.Antialiasing,
                     bool(painter.renderHints() & QPainter.Antialiasing))
    lp.setFont(font)
    lp.setPen(QPen(QColor(255, 255, 255)))
    _draw(lp, QRectF(pad, pad, rect.width(), rect.height()), word)

    if horizontal:
        start = pad - (rect.left() - space.left())
        grad = QLinearGradient(start, 0.0, start + space.width(), 0.0)
    else:
        start = pad - (rect.top() - space.top())
        grad = QLinearGradient(0.0, start, 0.0, start + space.height())
    for stop, color in stops:
        grad.setColorAt(stop, QColor(color))

    lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    lp.fillRect(layer.rect(), QBrush(grad))
    lp.end()
    painter.drawImage(QPointF(rect.left() - pad, rect.top() - pad), layer)


def paint_word(painter, rect, word, style, state, base_color, font_px, t, index,
               line_rect):
    """Vẽ MỘT từ theo một kiểu karaoke.

    ``rect`` là hộp riêng của từ (để căn chỉnh y hệt nhánh vẽ cả dòng),
    ``line_rect`` là hộp của cả dòng — gradient phải dựng trong toạ độ đó.
    """
    base = QColor(base_color)
    pulse = 0.5 + 0.5 * math.sin(t * _ACTIVE_PULSE + index * 0.7)

    if state == PENDING:
        # Chưa tới lượt: MỘT nét chữ thường tối hơn, giống hệt nhau cho mọi kiểu.
        # Không có quầng, không có bóng — nhờ vậy hộp mực lúc sweep=0 so được
        # trực tiếp với chữ thường để chứng minh karaoke không làm dịch dòng chữ.
        # (Kiểu "outline" từng được cho pending sáng gần bằng lúc hát; trên nền
        # tối khi đó dòng chữ không hề thay đổi theo nhịp quét.)
        _solid(painter, rect, word, _shade(base, 0.52))
        return

    hot = state == LIT

    if style == "glow":
        _ring(painter, rect, word, _shade(base, 1.0, 40), font_px * 0.16)
        _ring(painter, rect, word, _shade(base, 1.0, 80), font_px * 0.08)
        _solid(painter, rect, word, QColor(255, 255, 255) if hot else base)
        return

    if style == "flame":
        lit_r, hot_r, hot_swing, halo_alpha = _FLAME_HALO
        _ring(painter, rect, word, QColor(255, 120, 0, halo_alpha),
              font_px * (hot_r + hot_swing * pulse if state == ACTIVE else lit_r))
        _fill(painter, rect, word, line_rect, (
            (0.0, QColor(255, 232, 120) if hot else QColor(255, 244, 190)),
            (0.45, QColor(255, 148, 24)),
            (1.0, QColor(196, 24, 8)),
        ))
        return

    if style == "neon":
        _ring(painter, rect, word, QColor(255, 40, 190, 60), font_px * 0.18)
        _ring(painter, rect, word, QColor(255, 40, 190, 110), font_px * 0.09)
        _ring(painter, rect, word, QColor(40, 240, 255, 150), font_px * 0.045)
        _solid(painter, rect, word,
               QColor(235, 255, 255) if hot else QColor(255, 255, 255))
        return

    if style == "gradient":
        _fill(painter, rect, word, line_rect, (
            (0.0, QColor(80, 170, 255)),
            (0.55, QColor(150, 110, 255)),
            (1.0, QColor(235, 90, 220)),
        ), horizontal=True)
        return

    if style == "rainbow":
        # Sắc độ theo vị trí TRÊN DÒNG, không theo thứ tự đã hát: hai từ cạnh
        # nhau phải liền dải màu, nếu không dòng chữ nhấp nháy lúc quét.
        hue = int((index * 34.0 + t * 26.0) % 360)
        color = QColor.fromHsv(hue, 220 if hot else 180,
                               255 if hot else 235)
        _ring(painter, rect, word, _shade(color, 1.0, 70), font_px * 0.075)
        _solid(painter, rect, word, color)
        return

    if style == "shadow":
        off = max(1.0, font_px * 0.055)
        # Nét bóng là chính rect đó dịch đi, không phải một hộp đo lại.
        _solid(painter, rect, word, QColor(0, 0, 0, 190 if hot else 120),
               dx=off, dy=off)
        _solid(painter, rect, word, QColor(255, 255, 255) if hot else base)
        return

    if style == "outline":
        # Viền chữ = bóng đậm xung quanh (các bản lệch màu tối) rồi mới tới ruột
        # sáng. Không có nét pen đậm nào làm được việc này trên Qt.
        _ring(painter, rect, word, QColor(16, 14, 22, 230), font_px * 0.055)
        _solid(painter, rect, word, QColor(255, 255, 255) if hot else base)
        return

    # "soft"
    _ring(painter, rect, word, _shade(base, 1.0, 30), font_px * 0.11)
    _solid(painter, rect, word, _shade(base, 0.94) if hot else base)
