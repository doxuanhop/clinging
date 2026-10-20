"""Xem FrameComposer vẽ gì khi nền là ảnh trắng 1920x1080 (tái hiện dòng selftest)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType

W, H = 1920, 1080
png = os.path.join(os.environ["TEMP"], "clinging_recap_report", "nen_trang.png")
print("png", os.path.exists(png), png)

settings = {"enabled": True, "border": True, "border_color": "#3673FE",
            "reticle": True, "reticle_shape": "scope",
            "reticle_color": "#00FFFF", "rec": True, "rec_fps": 30}

model = TimelineModel()
model.project_ratio = "16:9"
track = model.add_track(TrackType.IMAGE)
clip = model.add_clip(track.track_id, png, "image", 0.0, 2.0, name="recap")
print("clip", clip is not None, getattr(clip, "media_type", None))
model.set_recap_overlay(settings)

c = FrameComposer(model, W, H)
img = c.render_frame(0.5).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
c.close()
print("img", img.width(), img.height(), img.format())

row = img.bytesPerLine() // 4
a = np.frombuffer(img.constBits(), np.uint8, count=row * 4 * img.height()
                  ).reshape(img.height(), row, 4)[:, :img.width(), :3]
rgb = a[:, :, ::-1].astype(np.int16)


def count(hexcolor, tol=60):
    q = QColor(hexcolor)
    d = np.abs(rgb - np.array([q.red(), q.green(), q.blue()], np.int16))
    m = d.max(axis=2) <= tol
    return int(m.sum())


for name in ("#3673FE", "#00FFFF", "#FF0000", "#FFFFFF", "#000000"):
    print("%-8s %8d" % (name, count(name)))
print("mean", rgb.mean(axis=(0, 1)).round(1))
img.save(os.path.join(os.environ["TEMP"], "clinging_recap_report", "dbg_white.png"))
