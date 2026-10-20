r"""Anh chung minh C4: style chu (vien / bong / bong mo / hop nen / can le) ve ra
that duong export FrameComposer — cung seam text_style_of ma preview dung.

Gate --selftest do pixel bang numpy; anh nay de NGUOI MO RA XEM: moi o la mot
clip text da dat truong style, ve qua FrameComposer(model, W, H). Nen dung
QApplication THAT (khong offscreen): offscreen o may nay khong co font nen chi
thay tofu, khong phan duoc vien hay bong.

Chay:
    python scratch/text_styling_evidence.py
In ra bang so pixel lech va EVIDENCE_IMAGE; exit 1 neu bat ky lech nao bang 0.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType

OUT = os.path.join(tempfile.gettempdir(), "clinging_text_styling_evidence.png")
TW, TH = 520, 300

# (nhan, {truong style dat tren clip}) — tat ca di qua dung text_style_of.
CASES = [
    ("1. chu thuong (khong style)", {}),
    ("2. vien do 6px", {"text_outline_color": "#FF2D2D", "text_outline_width": 6.0}),
    ("3. bong lech 12px", {"text_shadow_color": "#2D6DFF",
                           "text_shadow_dx": 12.0, "text_shadow_dy": 12.0}),
    ("4. bong mo blur 8", {"text_shadow_color": "#00E5FF", "text_shadow_dx": 6.0,
                           "text_shadow_dy": 6.0, "text_shadow_blur": 8.0}),
    ("5. hop nen luc 60%", {"text_box_color": "#2DC86D", "text_box_alpha": 0.6,
                           "text_box_padding": 34.0, "text_box_radius": 16.0}),
    ("6. can le TRAI", {"text_align": "left"}),
    ("7. can le PHAI", {"text_align": "right"}),
    ("8. vien + hop + bong", {"text_outline_color": "#FFD400", "text_outline_width": 5.0,
                              "text_box_color": "#3A1E5C", "text_box_alpha": 0.5,
                              "text_shadow_color": "#000000", "text_shadow_dx": 8.0,
                              "text_shadow_dy": 8.0}),
]

STYLE_KEYS = list({k for _, over in CASES for k in over})


def render_case(over, line="Style chu"):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.TEXT)
    clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, name=line)
    clip.font_size = 64.0
    clip.font_color = "#FFFFFF"
    for key in STYLE_KEYS:
        setattr(clip, key, over.get(key, getattr(clip, key)))
    composer = FrameComposer(model, TW, TH)
    try:
        return composer.render_frame(1.0).convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied)
    finally:
        composer.close()


def rgb(image):
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    row = img.bytesPerLine()
    buf = img.constBits()
    raw = bytes(buf[: row * img.height()])
    return raw


def diff_px(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


images = []
base = None
report = []
for label, over in CASES:
    img = render_case(over)
    images.append((label, img))
    if base is None:
        base = rgb(img)

# So lech voi o 1 (chu thuong). Rieng can le so trai vs phai (cung ben trong 6/7).
diffs = []
for (label, img), (_, _) in zip(images, CASES):
    diffs.append((label, diff_px(base, rgb(img))))
left_right = diff_px(rgb(images[5][1]), rgb(images[6][1]))

print("lech pixel so voi chu thuong:")
for label, n in diffs[1:]:
    print("  %-26s %d" % (label, n))
print("  can le trai vs phai        %d" % left_right)

# Ghép sheet 2 cot.
cols, rows = 2, (len(images) + 1) // 2
label_h = 24
pad = 8
sheet = QImage(cols * (TW + pad) + pad, rows * (TH + label_h + pad) + pad,
               QImage.Format.Format_ARGB32_Premultiplied)
sheet.fill(QColor("#0c0c10"))
p = QPainter(sheet)
p.setFont(QFont("Segoe UI", 11))
for i, (label, img) in enumerate(images):
    cx = i % cols
    cy = i // cols
    x = pad + cx * (TW + pad)
    y = pad + cy * (TH + label_h + pad)
    p.drawImage(x, y, img)
    p.setPen(QColor("#e8e8ee"))
    p.drawText(x + 2, y + TH + 16, label)
p.end()
if not sheet.save(OUT):
    raise RuntimeError("khong luu duoc anh chung minh")

# Gate: moi hieu ung phai lech > 0; hop nen/vien phai ro (>= 500 byte lech).
worst = min(n for _, n in diffs[1:])
ok = worst > 0 and left_right > 0 and all(
    n >= 500 for label, n in diffs[1:] if not label.startswith("6") and not label.startswith("7"))
print("EVIDENCE_IMAGE:", OUT)
print("WORST_LECH:", worst, "| LECH_TR_AI_PHAI:", left_right)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
