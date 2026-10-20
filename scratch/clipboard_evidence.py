"""Anh chung minh nhom B: Ctrl+V dan them mot ban lon khac (id moi, cung kieu),
Ctrl+Z gach ban do di, va ban dan ve GIONG HET ban goc.

Gate --selftest kiem model/stack; anh nay kiem tren FrameComposer (duong preview
va export cung dung). Mot clip chu tinh (khong keyframe, text_effect none) ve nhu
nhau o moi thoi diem trong cua no, nen ban dan tai t=10s (local 1s) phai tra
nghiet bang het ban goc tai t=1s (local 1s).

Mot clip nen "BG" song 0..20s giu duration du lon de `active_visual_clips_at`
KHONG clamp ve cuoi (clamp o day tung lam frame sau undo van con in chu cua ban
goc, che mat bang chung rang undo da gach ban dan). Nen nay khong bao gio bi
copy/paste.

Cam fixture nguoi dung: moi clip dung tai cho bang add_clip(''), ve vao file tam.
"""
import os, sys, tempfile
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from core import commands as core_commands
from core.clip_clipboard import ClipClipboard
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType

OUT = os.path.join(tempfile.gettempdir(), "clinging_clipboard_evidence.png")


def px(image):
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(img.constBits()[:img.sizeInBytes()])


def diff_count(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


model = TimelineModel()
track = model.add_track(TrackType.TEXT)
bg = model.add_clip(track.track_id, "", "text", 0.0, 20.0, "NEN-BG")
bg.font_size = 40.0
bg.transform.x = 30.0
bg.transform.y = 300.0
src = model.add_clip(track.track_id, "", "text", 0.0, 4.0, "Clinging")
src.font_size = 96.0
src.transform.x = 120.0
src.transform.y = 60.0

composer = FrameComposer(model, 640, 360)
SRC_T, PASTE_T, ANCHOR = 1.0, 10.0, 9.0

frame_src = composer.render_frame(SRC_T)      # goc + nen
frame_empty = composer.render_frame(PASTE_T)  # chi nen (chua paste)

stack = core_commands.UndoStack()
cb = ClipClipboard()
model.select_clips([src.clip_id])             # chi copy "Clinging", khong copy nen
cb.copy_from(model, model.selected_clip_ids)
stack.push(core_commands.PasteClipsCommand(model, cb.entries(), ANCHOR))

frame_paste = composer.render_frame(PASTE_T)  # ban dan + nen
stack.undo()
frame_after = composer.render_frame(PASTE_T)  # nen again (undo da gach ban dan)
composer.close()

src_, empty_, paste_, after_ = (px(f) for f in
                                (frame_src, frame_empty, frame_paste, frame_after))
fidelity = diff_count(src_, paste_)     # paste phai giong het goc
added = diff_count(empty_, paste_)      # paste them noi dung that
undone = diff_count(empty_, after_)     # undo tra ve dung frame moc

print("pixels ban dan khac ban goc  (muon 0):", fidelity)
print("pixels paste them so voi moc (muon >0):", added)
print("pixels sau undo khac moc     (muon 0):", undone)

labels = [
    ("A: clip goc 'Clinging' tai t=%.0fs (+nen)" % SRC_T, frame_src),
    ("B: t=%.0fs CHUA paste - chi co nen (moc)" % PASTE_T, frame_empty),
    ("C: t=%.0fs SAU paste - 'Clinging' xuat hien, bang A" % PASTE_T, frame_paste),
    ("D: t=%.0fs sau Ctrl+Z - lai chi co nen, bang B" % PASTE_T, frame_after),
]
tile_w, tile_h = 640, 360
label_h = 26
sheet = QImage(tile_w, (tile_h + label_h) * len(labels),
               QImage.Format.Format_ARGB32_Premultiplied)
sheet.fill(QColor("#101014"))
p = QPainter(sheet)
p.setFont(QFont("Segoe UI", 11))
y0 = 0
for text, img in labels:
    p.drawImage(0, y0, img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
    p.setPen(QColor("#e8e8ee"))
    p.drawText(4, y0 + tile_h + 18, text)
    y0 += tile_h + label_h
p.end()
if not sheet.save(OUT):
    raise RuntimeError("khong luu duoc anh chung minh")

ok = fidelity == 0 and added > 0 and undone == 0
print("EVIDENCE_IMAGE:", OUT)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
