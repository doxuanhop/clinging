"""
core/canvas_layout.py

BO CUC (layout) va PHONG CACH (chat lieu nen) CAP DU AN — cay thanh that tu mo
hinh `CanvaLayout` + `stylePreset` trong du an zip nguoi dung gui
(`trinh-chinh-sua-video-9_16-canva-&-aura.zip`, 22/10/2026): 12 kieu bo cuc va
10 chat lieu giay. O day mo hinh chi la mot dict tren TimelineModel; TOAN BO hinh
hoc va net nam trong module nay de preview va export goi chung một ham.

Vi sao la module rieng (dung kieu core/recap_overlay.py):
  * Nen va khung bo cuc ve len TOAN khung hình, không gắn với một clip nào, nên
    chúng không thể sống trong core.clip_effects (lọc màu theo clip, không có
    đồng hồ, không biết kích thước canvas).
  * Hai ben xem/xuat phai ra cung mot anh: cung `slots()`, cung `paint_background`,
    cung `paint_foreground`. Khong co nhanh rieng cho ben nao — day la bai hoc
    cua the "Bien doi" (preview lat, export khong lat).
  * Moi thu dan xuat tu t mot cach giai tich (nhep audio-meter cua camera-lcd =
    sin(t*k)), nen tua toi lui ra dung khung va export tuan tu khop preview.

Sinh nen bang QPainter tren mot QImage DAM (cache theo kieu + w + h), khong phai
GaussianBlur moi khung: may cau thap khong tra noi convolution 1080p, va net
 cua chat lieu thi bat dong trong ca du an nen mot lan ve dung cho moi khung.
"""

import hashlib
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen

# ── Bo cuc: 12 kieu cua ban mo ──────────────────────────────────
# moi kieu = (nhan, the loai, danh sach o theo ti LE khung hinh
#             (x, y, w, h) voi 0..1, net ve tien canh).
# O la ti le vi cung mot bo cuc phai dung cho 16:9 lan 9:16; `slots()` nhan
# kich thuoc canvas that va sinh toa do thiet bi.
LAYOUT_STYLES = {
    "none": ("Khong bo cuc (tron khung)", "aesthetic", ((0.0, 0.0, 1.0, 1.0),),
             "plain"),
    "split": ("Chia doi ngang tren/dưới", "aesthetic",
              ((0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)), "dividers"),
    "split-3": ("Chia ba doc bang nhau", "aesthetic",
                ((0.0, 0.0, 1.0, 1 / 3), (0.0, 1 / 3, 1.0, 1 / 3),
                 (0.0, 2 / 3, 1.0, 1 / 3)), "dividers"),
    "split-4": ("Luoi 2x2", "aesthetic",
                ((0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 0.5, 0.5),
                 (0.0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)), "dividers"),
    "split-5": ("Nam o pha cach", "aesthetic",
                ((0.0, 0.0, 0.6, 0.55), (0.6, 0.0, 0.4, 0.55),
                 (0.0, 0.55, 0.34, 0.45), (0.34, 0.55, 0.33, 0.45),
                 (0.67, 0.55, 0.33, 0.45)), "dividers"),
    "split-6": ("Luoi 6 o", "aesthetic",
                tuple((c * 0.5, r / 3.0, 0.5, 1 / 3)
                      for r in range(3) for c in range(2)), "dividers"),
    "split-3-vlog": ("Chia ba, o giua gap doi", "vlog",
                     ((0.0, 0.0, 1.0, 0.25), (0.0, 0.25, 1.0, 0.5),
                      (0.0, 0.75, 1.0, 0.25)), "dividers"),
    "classic-frame": ("Khung dien co tinh", "cinematic",
                      ((0.06, 0.15, 0.88, 0.64),), "classic"),
    "vlog-lower-third": ("Vlog bang thong tin duoi", "vlog",
                         ((0.0, 0.0, 1.0, 1.0),), "lower_third"),
    "magazine-editorial": ("Bia tap chi", "magazine",
                           ((0.08, 0.17, 0.84, 0.60),), "editorial"),
    "polaroid-retro": ("Kỷ niem Polaroid", "polaroid",
                       ((0.09, 0.09, 0.82, 0.62),), "polaroid"),
    "manga-grid": ("Luoi truyen Manga", "magazine",
                   ((0.0, 0.0, 0.55, 0.42), (0.55, 0.0, 0.45, 0.60),
                    (0.0, 0.42, 0.38, 0.58), (0.38, 0.60, 0.62, 0.40)),
                   "manga"),
    "camera-lcd": ("Khung ngam may anh LCD", "vlog",
                   ((0.0, 0.0, 1.0, 1.0),), "lcd"),
}

LAYOUT_ORDER = tuple(LAYOUT_STYLES)

# ── Phong cách: 10 chat lieu cua ban mo ─────────────────────────
# base/ink la mau nen va mau net; `kind` chon lop ve trong `_paint_texture`.
TEXTURES = {
    "meme": ("Giấy o ly", "#F5FAFF", "#9BB8D3", "grid"),
    "lined-paper": ("Trang ke ngang", "#FFFDF4", "#A6BBD1", "lines"),
    "pastel": ("Cham bi pastel", "#FFF2F6", "#F5BFD4", "dots"),
    "dark": ("Quiet carbon", "#121317", "#1F2229", "carbon"),
    "vintage": ("Go ke co dien", "#C7A067", "#8B6A3E", "wood"),
    "y2k": ("Hologram Y2K", "#EFE4FF", "#FFFFFF", "hologram"),
    "corkboard": ("Ban go cork", "#C79158", "#8E6134", "cork"),
    "parchment": ("Giấy da de", "#EFDFBE", "#B99C6E", "parchment"),
    "blueprint": ("Ban ve ky thuat", "#123A6B", "#BFD8F2", "blueprint"),
    "comic-half": ("Manga half", "#FFFFFF", "#111111", "halftone"),
}

TEXTURE_ORDER = tuple(TEXTURES)

BACKGROUND_MODES = ("black", "color", "texture")

BACKGROUND_MODE_LABELS = {
    "black": "Den (mac dinh cu)",
    "color": "Mau tu chon",
    "texture": "Chat lieu (phong cach)",
}

# Font cua hai vung chu: `display`/`serif`/`mono`/`sans` duoc quy ve ten that
# o `_font()` — khong hardcode font may nguoi dung khong co.
FONT_FAMILIES = ("sans", "serif", "mono", "display")

LAYOUT_DEFAULTS = {
    "enabled": False,
    "layout": "none",
    "background_mode": "black",
    "background_color": "#0B0B0F",
    "texture": "meme",
    "texture_scale": 1.0,        # phong kich thuoc net cua chat lieu
    "overlay_opacity": 0.0,      # 0..1, tan mau len toan khung sau khi ve clip
    "slot_gap": 0.0,             # lech giua cac o, ti le canh ngan khung
    "header_text": "",
    "footer_text": "",
    "header_font": "sans",
    "footer_font": "mono",
    "header_size": 42,           # px o khung cao 1080, `slots()` ty le theo canvas
    "footer_size": 30,
    "header_bold": True,
    "footer_bold": False,
    "text_color": "#FFFFFF",
    "frame_color": "#FFFFFF",
    "auto_fit": True,            # "dan bo cuc" tu fit/fill theo ti le o
    "play_sequentially": False,  # khong phat song song ma lan luot tung o
    "slot_seconds": 2.0,         # do dai moi o khi phat tuan tu
    "manga_rotate_interval": 0.0,  # 0 = tat; 3/5/10/15 = trao noi dung duoi o
}

# Nen ve bang QPainter roi dam lai: mot lan cho moi (kieu, w, h). Loai cu nhat
# khi vuot qua so nay de project_ratio khong phình bộ nhớ khi tua khung.
_BACKDROP_LIMIT = 6
_BACKDROP_CACHE = {}

# Tham chieu so do cua recap_overlay: moi net de u theo khung 720 px.
_REF_SHORT = 720.0


def normalize(settings) -> dict:
    """Dien khoa con thieu + kep gia tri ve mien hop le.

    File .clinq cua nguoi dung moi (va cua 1.0.5 tro ve truoc) khong co muc
    `layout`, nen khong duoc phep co khoa nao tra None trong luc ve.
    """
    out = dict(LAYOUT_DEFAULTS)
    for key, value in (settings or {}).items():
        if key in out:
            out[key] = value
    if out["layout"] not in LAYOUT_STYLES:
        out["layout"] = "none"
    if out["texture"] not in TEXTURES:
        out["texture"] = "meme"
    if out["background_mode"] not in BACKGROUND_MODES:
        out["background_mode"] = "black"
    if out["header_font"] not in FONT_FAMILIES:
        out["header_font"] = "sans"
    if out["footer_font"] not in FONT_FAMILIES:
        out["footer_font"] = "mono"
    out["overlay_opacity"] = max(0.0, min(1.0, float(out["overlay_opacity"])))
    out["slot_gap"] = max(0.0, min(0.2, float(out["slot_gap"])))
    out["texture_scale"] = max(0.25, min(4.0, float(out["texture_scale"])))
    out["header_size"] = max(6.0, float(out["header_size"]))
    out["footer_size"] = max(6.0, float(out["footer_size"]))
    out["slot_seconds"] = max(0.1, float(out["slot_seconds"]))
    out["manga_rotate_interval"] = max(0.0, float(out["manga_rotate_interval"]))
    if not QColor(out["background_color"]).isValid():
        out["background_color"] = LAYOUT_DEFAULTS["background_color"]
    if not QColor(out["text_color"]).isValid():
        out["text_color"] = "#FFFFFF"
    if not QColor(out["frame_color"]).isValid():
        out["frame_color"] = "#FFFFFF"
    return out


def layout_active(settings) -> bool:
    """Co thi ve/giam giup that khong — cua `enabled` va mot lop nao do bat.

    Nen `black` la nguyen trang thai cu cua 1.0.5, nen no KHONG tinh la "bat":
    mo bo cuc len ma chi chon den thi khung hinh phai y het nhu cu.
    """
    s = normalize(settings)
    if not s["enabled"]:
        return False
    if s["layout"] != "none":
        return True
    if s["background_mode"] in ("color", "texture"):
        return True
    if s["overlay_opacity"] > 0.0:
        return True
    return bool((s["header_text"] or "").strip() or (s["footer_text"] or "").strip())


def style_of(key: str) -> tuple:
    return LAYOUT_STYLES.get(key, LAYOUT_STYLES["none"])


def slot_frictions(settings) -> tuple:
    """Toa do ti le cua cac o — thu tu o la thu tu gan clip khi dan bo cuc."""
    return style_of(normalize(settings)["layout"])[2]


def _unit(w, h):
    return max(0.2, min(w, h) / _REF_SHORT)


def slots(w, h, settings) -> list:
    """Danh sach (x, y, rộng, cao) theo toa do thiet bi cua khung w x h.

    `slot_gap` trach deu vao trong tung o (tinh theo canh ngan), de luoi split
    khong dan sat mép ma van khong doi so luong o.
    """
    s = normalize(settings)
    k = _unit(w, h)
    gap = s["slot_gap"] * min(w, h)
    out = []
    for fx, fy, fw, fh in style_of(s["layout"])[2]:
        x = fx * w + gap
        y = fy * h + gap
        ww = max(1.0, fw * w - 2 * gap)
        hh = max(1.0, fh * h - 2 * gap)
        out.append((x, y, ww, hh))
    return out


def slot_rect(w, h, settings, index: int) -> tuple:
    """O so `index`, an toàn khi clip nhieu hon o: cu lap lai o cuoi."""
    boxes = slots(w, h, settings)
    if not boxes:
        return (0.0, 0.0, float(w), float(h))
    return boxes[min(max(0, int(index)), len(boxes) - 1)]


def fit_into_slot(base_w, base_h, box: tuple, fill: bool = False) -> tuple:
    """Tra (x, y, scale) theo HE TAM canvas — dung nghia cua transform.x/y.

    Preview va FrameComposer cung doc `transform.x/y` la do lech khoi tam, nen
    moi phep dan o phai tra ve he do; tra toa goi goc tren-trai la clip nhay
    mot nữa khung hình.
    """
    bx, by, bw, bh = box
    if base_w <= 0 or base_h <= 0 or bw <= 0 or bh <= 0:
        return (0.0, 0.0, 1.0)
    ratio = (max if fill else min)(bw / base_w, bh / base_h)
    return (bx + bw / 2.0, by + bh / 2.0, ratio)


def transform_for_slot(base_w, base_h, canvas_w, canvas_h, box: tuple,
                       fill: bool = False) -> dict:
    """`fit_into_slot` + tru tam canvas -> bo dict ghi thang vao ClipTransform."""
    cx, cy, scale = fit_into_slot(base_w, base_h, box, fill)
    return {"x": cx - canvas_w / 2.0, "y": cy - canvas_h / 2.0,
            "scale": scale}


def sequential_index(settings, t: float, n_slots: int) -> int:
    """O dang phat tai giay `t` khi bat `play_sequentially`.

    De thuan tuy (khong doc file, khong cham Qt) de gate do duoc bang so:
    do dai moi o = `slot_seconds`, het o cuoi thi quay vong dau.
    """
    s = normalize(settings)
    n = max(1, int(n_slots))
    if not s["play_sequentially"]:
        return -1
    span = max(0.1, float(s["slot_seconds"]))
    return int(max(0.0, float(t)) // span) % n


def rotated_slot_source(settings, t: float, count: int, slot: int,
                        pool: int) -> int:
    """Vo o cua `slot` tai giay `t` khi bat `manga_rotate_interval`.

    `pool` la so noi dung co the (anh/clip cung kieu). Cong don `slot` de moi o
    lay mot dac cua luong, va ket qua tuan hoan: tua lai cung `t` ra cung so.
    """
    s = normalize(settings)
    interval = s["manga_rotate_interval"]
    n = max(1, int(pool))
    if interval <= 0.0 or n <= 1:
        return int(slot) % n
    step = int(max(0.0, float(t)) // interval)
    return (int(slot) + step * max(1, int(count))) % n


# ── Nen: chat lieu ve mot lan, dam lai ──────────────────────────

def backdrop(settings, w, h) -> QImage:
    """QImage nen cho (chat lieu, kich thuoc) — cache toàn tiến trình.

    Cache la bat buoc cho may cau thap: ve 10 lop net tren 1080x1920 moi khung
    hinh la khong kha thi, ma nen thi bat dong trong ca du an.
    """
    s = normalize(settings)
    key = (s["texture"], int(w), int(h), round(s["texture_scale"], 3),
           s["background_color"])
    hit = _BACKDROP_CACHE.get(key)
    if hit is not None:
        return hit
    image = QImage(int(w), int(h), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    _paint_texture(painter, int(w), int(h), s)
    painter.end()
    if len(_BACKDROP_CACHE) >= _BACKDROP_LIMIT:
        _BACKDROP_CACHE.pop(next(iter(_BACKDROP_CACHE)))
    _BACKDROP_CACHE[key] = image
    return image


def _paint_texture(painter, w, h, s):
    label, base, ink, kind = TEXTURES[s["texture"]]
    scale = max(0.25, s["texture_scale"])
    k = _unit(w, h) * scale
    color_base = QColor(base)
    if s["background_mode"] == "color":
        color_base = QColor(s["background_color"])
    painter.fillRect(QRectF(0, 0, w, h), color_base)
    line = QColor(ink)
    pen = QPen(line)
    pen.setWidthF(max(1.0, 1.0 * k))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if kind == "grid":
        step = 26.0 * k
        x = 0.0
        while x < w:
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = 0.0
        while y < h:
            painter.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        margin = QColor("#D2555F")
        painter.setPen(QPen(margin, max(1.0, 2.0 * k)))
        painter.drawLine(QPointF(0.08 * w, 0), QPointF(0.08 * w, h))
    elif kind == "lines":
        step = 34.0 * k
        y = step
        while y < h:
            painter.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        painter.setPen(QPen(QColor("#D2555F"), max(1.0, 2.0 * k)))
        painter.drawLine(QPointF(0.09 * w, 0), QPointF(0.09 * w, h))
    elif kind == "dots":
        step = 42.0 * k
        r = 6.0 * k
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line)
        row = 0
        y = step / 2.0
        while y < h:
            offset = (step / 2.0) if row % 2 else 0.0
            x = step / 2.0 + offset
            while x < w:
                painter.drawEllipse(QPointF(x, y), r, r)
                x += step
            y += step
            row += 1
    elif kind == "carbon":
        painter.setPen(QPen(line, max(1.0, 5.0 * k)))
        d = 18.0 * k
        pos = -h
        while pos < w + h:
            painter.drawLine(QPointF(pos, 0), QPointF(pos + h, h))
            pos += d
    elif kind == "wood":
        plank = 96.0 * k
        x = 0.0
        while x < w:
            painter.setPen(QPen(QColor(ink).darker(140), max(1.0, 2.0 * k)))
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            grain = QColor(ink)
            grain.setAlphaF(0.35)
            painter.setPen(QPen(grain, max(1.0, 1.0 * k)))
            y = 6.0 * k
            while y < h:
                wob = 9.0 * k * math.sin(y / (22.0 * k) + x / (30.0 * k))
                painter.drawLine(QPointF(x + 4 * k + wob, y),
                                 QPointF(x + plank - 4 * k + wob, y))
                y += 13.0 * k
            x += plank
    elif kind == "hologram":
        grad = QLinearGradient(0, 0, w, h)
        for i, stop in enumerate(("#FFC9E8", "#C9E8FF", "#D8FFC9", "#FFEAC9",
                                  "#E8C9FF", "#FFC9E8")):
            grad.setColorAt(i / 5.0, QColor(stop))
        painter.fillRect(QRectF(0, 0, w, h), grad)
        painter.setPen(QPen(QColor(255, 255, 255, 120), max(1.0, 1.5 * k)))
        d = 26.0 * k
        pos = -h
        while pos < w + h:
            painter.drawLine(QPointF(pos, 0), QPointF(pos + h, h))
            pos += d
    elif kind in ("cork", "parchment"):
        # Cham deterministic theo hash toa do: khong dung random() de hai lan
        # chay ra cung mot nen (gate do pixel ma khong the dung ngu lieu ngau nhien).
        step = (11.0 if kind == "cork" else 15.0) * k
        tone = QColor(ink)
        painter.setPen(Qt.PenStyle.NoPen)
        y = step / 2.0
        row = 0
        while y < h:
            x = step / 2.0
            col = 0
            while x < w:
                seed = (col * 73856093) ^ (row * 19349663)
                n = (seed % 997) / 997.0
                r = (0.8 + 2.4 * n) * k
                c = QColor(tone)
                c.setAlphaF(0.10 + 0.30 * n)
                painter.setBrush(c)
                painter.drawEllipse(QPointF(x, y), r, r)
                x += step
                col += 1
            if kind == "parchment" and row % 7 == 3:
                band = QColor(tone)
                band.setAlphaF(0.12)
                painter.setBrush(band)
                painter.drawRect(QRectF(0, y - step, w, step * 0.7))
            y += step
            row += 1
    elif kind == "blueprint":
        minor = 22.0 * k
        painter.setPen(QPen(QColor(ink), max(1.0, 0.8 * k)))
        x = 0.0
        while x < w:
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            x += minor
        y = 0.0
        while y < h:
            painter.drawLine(QPointF(0, y), QPointF(w, y))
            y += minor
        major = minor * 5.0
        painter.setPen(QPen(QColor(ink), max(1.5, 1.8 * k)))
        x = 0.0
        while x < w:
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            x += major
        y = 0.0
        while y < h:
            painter.drawLine(QPointF(0, y), QPointF(w, y))
            y += major
    elif kind == "halftone":
        step = 16.0 * k
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line)
        y = step / 2.0
        row = 0
        while y < h:
            x = step / 2.0
            col = 0
            while x < w:
                d = abs((x / max(1.0, w)) - (y / max(1.0, h)))
                r = max(0.6 * k, (1.0 - min(1.0, d * 2.2)) * 5.0 * k)
                painter.drawEllipse(QPointF(x, y), r, r)
                x += step
                col += 1
            y += step
            row += 1
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def paint_background(painter, w, h, settings):
    """Ve nen TRUOC khi ve clip. Khong co nhanh preview/export.

    `enabled` khong bat thi day la nguyen hanh vi 1.0.5: khung hinh van nen
    den, du bo cuc trong file .clinq da dien du khoa. Guard o day (thay vi o
    noi Goi) de khong the co ben nao vo hoi goi khi chuc nang tat.
    """
    s = normalize(settings)
    if not s["enabled"] or s["background_mode"] == "black":
        return
    if s["background_mode"] == "color":
        painter.fillRect(QRectF(0, 0, w, h), QColor(s["background_color"]))
        return
    if s["background_mode"] == "texture":
        painter.drawImage(0, 0, backdrop(s, w, h))
        return


# ── Tien canh: khung, o, hai vung chu ───────────────────────────

def _font(kind: str, px: float, bold: bool) -> QFont:
    family = {"sans": "Segoe UI", "serif": "Georgia", "mono": "Courier New",
              "display": "Impact"}[kind]
    font = QFont(family)
    font.setPixelSize(max(6, int(round(px))))
    font.setBold(bool(bold))
    return font


def header_rect(w, h, settings) -> tuple:
    """Vung chu dau: nom tren voi cua kieu frame, day dac o cac kieu khac."""
    s = normalize(settings)
    chrome = style_of(s["layout"])[3]
    k = _unit(w, h)
    line = s["header_size"] * k * 1.9
    if chrome in ("classic", "editorial"):
        return (0.06 * w, 0.03 * h, 0.88 * w, line)
    if chrome == "polaroid":
        return (0.09 * w, 0.015 * h, 0.82 * w, line * 0.7)
    return (0.04 * w, 0.025 * h, 0.92 * w, line)


def footer_rect(w, h, settings) -> tuple:
    s = normalize(settings)
    chrome = style_of(s["layout"])[3]
    k = _unit(w, h)
    line = s["footer_size"] * k * 1.9
    if chrome == "polaroid":
        # Polaroid de dac cho vung viet tay duoi anh: day hon, cham hon.
        return (0.11 * w, 0.73 * h, 0.78 * w, 0.20 * h)
    if chrome in ("classic", "editorial"):
        return (0.06 * w, 0.815 * h, 0.88 * w, line)
    if chrome == "lower_third":
        return (0.06 * w, h - line * 2.4, 0.7 * w, line)
    return (0.04 * w, h - line * 1.5, 0.92 * w, line)


def paint_foreground(painter, w, h, settings, t: float = 0.0):
    """Ve khung/o/chu LEN TRÊN clip. Thu tu lop la co do: khung -> chu -> scrim."""
    s = normalize(settings)
    if not s["enabled"]:
        return
    chrome = style_of(s["layout"])[3]
    k = _unit(w, h)
    painter.save()
    if chrome == "dividers":
        _paint_dividers(painter, w, h, s, k)
    elif chrome == "classic":
        _paint_classic(painter, w, h, s, k)
    elif chrome == "lower_third":
        _paint_lower_third(painter, w, h, s, k)
    elif chrome == "editorial":
        _paint_editorial(painter, w, h, s, k)
    elif chrome == "polaroid":
        _paint_polaroid(painter, w, h, s, k)
    elif chrome == "manga":
        _paint_manga(painter, w, h, s, k)
    elif chrome == "lcd":
        _paint_lcd(painter, w, h, s, k, t)
    _paint_text_zones(painter, w, h, s, k)
    if s["overlay_opacity"] > 0.0:
        veil = QColor(0, 0, 0)
        veil.setAlphaF(s["overlay_opacity"])
        painter.fillRect(QRectF(0, 0, w, h), veil)
    painter.restore()


def _paint_dividers(painter, w, h, s, k):
    """Gach ngan cua: o chia doi/luoi nhin thay rieng, ke ca khi clip giong het nhau."""
    pen = QPen(QColor(s["frame_color"]))
    pen.setWidthF(max(1.0, 2.0 * k))
    painter.setPen(pen)
    boxes = slots(w, h, s)
    for i, (x, y, bw, bh) in enumerate(boxes):
        if i == 0 and len(boxes) == 1:
            continue
        # O ke nhau trong split-*/luoi thi ve duong chung; split-5/split-3-vlog
        # co the le, nen ve dem theo cac canh cua tung o.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x, y, bw, bh))


def _paint_classic(painter, w, h, s, k):
    box = slots(w, h, s)[0]
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(s["frame_color"]), max(1.0, 2.0 * k)))
    painter.drawRect(QRectF(box[0] - 2 * k, box[1] - 2 * k, box[2] + 4 * k,
                            box[3] + 4 * k))


def _paint_lower_third(painter, w, h, s, k):
    fx, fy, fw, fh = footer_rect(w, h, s)
    bar = QColor(0, 0, 0)
    bar.setAlphaF(0.45)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bar)
    painter.drawRect(QRectF(fx, fy, fw + 24 * k, fh))
    accent = QColor(s["frame_color"])
    painter.setBrush(accent)
    painter.drawRect(QRectF(fx, fy, 6 * k, fh))


def _paint_editorial(painter, w, h, s, k):
    hx, hy, hw, hh = header_rect(w, h, s)
    fx, fy, fw, fh = footer_rect(w, h, s)
    painter.setPen(QPen(QColor(s["frame_color"]), max(1.0, 2.0 * k)))
    painter.drawLine(QPointF(hx, hy + hh), QPointF(hx + hw, hy + hh))
    painter.drawLine(QPointF(fx, fy), QPointF(fx + fw, fy))


def _paint_polaroid(painter, w, h, s, k):
    """Viền trắng dày, đáy dày hơn — chính là tỉ lệ Polaroid 1:1.06."""
    x, y, bw, bh = slots(w, h, s)[0]
    pad = 0.035 * min(w, h)
    bottom = pad * 3.2
    outer = QRectF(x - pad, y - pad, bw + 2 * pad, bh + pad + bottom)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(s["frame_color"]))
    painter.drawRect(outer)


def _paint_manga(painter, w, h, s, k):
    """Viền ô vẽ tay: nét đen dày, lề không tuyệt đối thẳng cho ra chat bi."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for (x, y, bw, bh) in slots(w, h, s):
        for wob in (0.0, 1.0, 2.0):
            pen = QPen(QColor("#111111"), max(1.5, (5.0 - wob) * k))
            painter.setPen(pen)
            off = wob * k
            painter.drawRect(QRectF(x + off, y - off,
                                   max(1.0, bw - 2 * off),
                                   max(1.0, bh + off)))


def _paint_lcd(painter, w, h, s, k, t):
    """Khung ngam LCD: goc vet, tam ngam, pin, ISO/fps, vach nhay am thanh."""
    color = QColor(s["frame_color"])
    pen = QPen(color)
    pen.setWidthF(max(1.5, 3.0 * k))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arm = 46.0 * k
    pad = 26.0 * k
    for sx, sy in ((pad, pad), (w - pad, pad), (pad, h - pad), (w - pad, h - pad)):
        dx = arm if sx < w / 2 else -arm
        dy = arm if sy < h / 2 else -arm
        painter.drawLine(QPointF(sx, sy), QPointF(sx + dx, sy))
        painter.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy))
    cx, cy = w / 2.0, h / 2.0
    painter.drawRect(QRectF(cx - 30 * k, cy - 20 * k, 60 * k, 40 * k))
    # Pin: 4 thanh, so thanh sang theo t — de gate do duoc ma khong can doc chu.
    cells = max(0, min(4, 4 - int((t % 12.0) // 3.0)))
    for i in range(4):
        rect = QRectF(w - 92 * k + i * 11 * k, pad, 9 * k, 16 * k)
        if i < cells:
            painter.fillRect(rect, color)
        else:
            painter.drawRect(rect)
    # Audio meter: hai day nhay theo sin(t*k), bien doi thuan tuy theo t.
    for row, rate in enumerate((6.0, 8.5)):
        base = h - pad - (row + 1) * 14 * k
        for i in range(12):
            level = 0.5 + 0.5 * math.sin(t * rate + i * 0.55)
            seg = QRectF(pad + i * 11 * k, base, 9 * k, 9 * k)
            if i / 12.0 < level:
                painter.fillRect(seg, color)


def _paint_text_zones(painter, w, h, s, k):
    for rect, text, size_key, font_key, bold_key, align_key in (
        (header_rect(w, h, s), (s["header_text"] or "").strip(),
         "header_size", "header_font", "header_bold",
         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
        (footer_rect(w, h, s), (s["footer_text"] or "").strip(),
         "footer_size", "footer_font", "footer_bold",
         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
    ):
        if not text:
            continue
        fx, fy, fw, fh = rect
        font = _font(s[font_key], s[size_key] * k, s[bold_key])
        painter.setFont(font)
        painter.setPen(QColor(s["text_color"]))
        painter.drawText(QRectF(fx, fy, fw, fh), align_key, text)


def describe(settings) -> str:
    """Chu ngan cho dong selftest va payload — khong phai ten ham."""
    s = normalize(settings)
    parts = ["bo cuc %s" % s["layout"],
             "nen %s" % (s["texture"] if s["background_mode"] == "texture"
                         else s["background_mode"])]
    if s["play_sequentially"]:
        parts.append("tuan tu %ss/o" % _g(s["slot_seconds"]))
    if s["manga_rotate_interval"] > 0:
        parts.append("trao o %ss" % _g(s["manga_rotate_interval"]))
    return ", ".join(parts)


def _g(value: float) -> str:
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") or "0"


def fingerprint(settings) -> str:
    """sha256[:12] cua toan bo thong so bo cuc — de gate phat hien doi 1 khoa."""
    s = normalize(settings)
    blob = "|".join("%s=%r" % (key, s[key]) for key in sorted(s))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
