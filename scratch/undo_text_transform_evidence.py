"""Anh chung minh A3: lenh undo chu + hinh hoc THAT DOI va THAT HOI PHUONG-TU.

Gate --selftest kiem tra model/stack; anh nay kiem dieu nguoi dung nhin thay:
duong ve cua FrameComposer (la duong preview va export cung dung) phai khac
nhau giu truoc/sau khi doi, va TRAI NGHIET ve bang het khung hinh goc sau
Ctrl+Z. Nen ve bang QApplication that (khong offscreen) vi offscreen o may nay
khong co font -> chi thay tofu.
"""
import os, sys, tempfile
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
from core import commands as core_commands
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType

OUT = os.path.join(tempfile.gettempdir(), "clinging_undo_evidence.png")


def px(image):
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(img.constBits()[:img.sizeInBytes()])


def diff_count(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


model = TimelineModel()
track = model.add_track(TrackType.TEXT)
clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, "Clinging")
stack = core_commands.UndoStack()
composer = FrameComposer(model, 640, 360)
T = 1.0  # clip dang hoat dong (0..4)

frame_a = composer.render_frame(T)

# 1) Doi chu qua lenh that (SetClipTextCommand) -> ve -> undo -> ve.
stack.push(core_commands.SetClipTextCommand(
    model, clip.clip_id, text_effect="karaoke", text_effect_intensity=0.9,
    font_size=120.0))
frame_b = composer.render_frame(T)
stack.undo()
frame_c = composer.render_frame(T)

# 2) Doi hinh hoc qua lenh that (SetClipTransformCommand) -> ve -> undo -> ve.
stack.push(core_commands.SetClipTransformCommand(
    model, clip.clip_id, x=210.0, y=90.0, scale_x=1.6, scale_y=1.6))
frame_d = composer.render_frame(T)
stack.undo()
frame_e = composer.render_frame(T)
composer.close()

a, b, c, d, e = (px(f) for f in (frame_a, frame_b, frame_c, frame_d, frame_e))
changed_text = diff_count(a, b)
restored_text = diff_count(a, c)
changed_geom = diff_count(a, d)
restored_geom = diff_count(a, e)

print("pixels khac sau doi chu        :", changed_text)
print("pixels khac sau undo chu        :", restored_text)
print("pixels khac sau doi hinh hoc    :", changed_geom)
print("pixels khac sau undo hinh hoc   :", restored_geom)

labels = [
    ("A: ban goc", frame_a),
    ("B: sau doi chu (lenh)", frame_b),
    ("C: sau Ctrl+Z chu -> phai bang A", frame_c),
    ("D: sau doi hinh hoc (lenh)", frame_d),
    ("E: sau Ctrl+Z hinh hoc -> phai bang A", frame_e),
]
tile_w, tile_h = 640, 360
label_h = 26
sheet = QImage(tile_w, (tile_h + label_h) * len(labels),
               QImage.Format.Format_ARGB32_Premultiplied)
sheet.fill(QColor("#101014"))
p = QPainter(sheet)
font = QFont("Segoe UI", 11)
p.setFont(font)
y0 = 0
for text, img in labels:
    p.drawImage(0, y0, img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
    p.setPen(QColor("#e8e8ee"))
    p.drawText(4, y0 + tile_h + 18, text)
    y0 += tile_h + label_h
p.end()
if not sheet.save(OUT):
    raise RuntimeError("khong luu duoc anh chung minh")

ok = (changed_text > 0 and restored_text == 0 and
      changed_geom > 0 and restored_geom == 0)
print("EVIDENCE_IMAGE:", OUT)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
