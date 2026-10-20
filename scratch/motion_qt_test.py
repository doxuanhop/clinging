"""Gate: the 12 ported motion effects animate, and preview == export.

Renders a STILL image clip so every changed pixel must come from the effect,
then compares the live preview canvas against the headless export compositor at
the same clip-local time.

Usage: python scratch/motion_qt_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")

SRC = os.path.join(ROOT, "scratch", "motion_frame_src.png")
DUR = 4.0
W, H = 640, 360

import numpy as np

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

from core import anim_engine
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, EffectData
from ui.graphics_canvas_item import CanvasClipItem

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-52s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))


def build_model(effect_key):
    from core.timeline_model import track_type_for_media
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(track_type_for_media("image"), "Main")
    clip = model.add_clip(track.track_id, SRC, "image", 0.0, DUR, "src.png")
    clip.effects = [EffectData(name=effect_key, category="Hoạt ảnh",
                               intensity=1.0, params={effect_key: 1.0})]
    return model, clip


def to_array(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape((img.height(), img.width(), 4)).astype(np.int16)


def changed_fraction(a, b):
    diff = np.abs(a - b).max(axis=2)
    return float((diff > 16).mean())


def export_frame(model, t):
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def preview_frame(clip, t):
    """Vẽ đúng như canvas thật: item có rect theo project canvas 1920x1080,
    nên phải render ở cỡ đó rồi mới hạ về cỡ xuất như FrameComposer."""
    cw, ch = 1920, 1080
    scene = QGraphicsScene()
    scene.setSceneRect(-cw / 2.0, -ch / 2.0, cw, ch)
    item = CanvasClipItem(clip)
    scene.addItem(item)
    item.set_local_time(t)
    img = QImage(cw, ch, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        scene.render(p, QRectF(0, 0, cw, ch), QRectF(-cw / 2.0, -ch / 2.0, cw, ch))
    finally:
        p.end()
    return img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def main():
    app = QApplication(sys.argv)

    # Baseline: cùng một ảnh, không hiệu ứng, phải cho hai khung gần như identical
    base_model, base_clip = build_model("none")
    b0 = to_array(export_frame(base_model, 0.0))
    b1 = to_array(export_frame(base_model, DUR * 0.5))
    check("static clip does not animate on its own", changed_fraction(b0, b1) < 0.002, True)
    check("static clip: preview matches export",
          np.abs(b0 - to_array(preview_frame(base_clip, 0.0))).mean() < 6.0, True)

    tiles = []
    for key, name, _ in anim_engine.MOTION_EFFECTS:
        model, clip = build_model(key)
        times = [0.0, DUR * 0.25, DUR * 0.5, DUR * 0.75, DUR * 0.999]
        frames = [export_frame(model, t) for t in times]
        arrs = [to_array(f) for f in frames]
        moved = changed_fraction(arrs[0], arrs[2])
        peak = max(changed_fraction(arrs[0], a) for a in arrs[1:])

        # Preview và export phải cùng một khung hình tại cùng nhịp tiến độ.
        drift = max(float(np.abs(arrs[i] - to_array(preview_frame(clip, times[i]))).mean())
                    for i in range(len(times)))

        print("  %-12s moved=%.3f peak=%.3f preview-vs-export MAE=%.2f"
              % (key, moved, peak, drift))
        check("%s animates the frame" % key, key == "none" or peak > 0.004, True)
        check("%s preview matches export" % key, drift < 6.0, True)
        tiles.append(frames)

    # bằng chứng nhìn được: mỗi hàng một hiệu ứng, 5 cột là 5 nhịp tiến độ
    tw, th = 256, 144
    strip = QImage(tw * 5 + 120, th * len(tiles), QImage.Format.Format_ARGB32_Premultiplied)
    strip.fill(Qt.GlobalColor.black)
    p = QPainter(strip)
    p.setPen(Qt.GlobalColor.white)
    for row, (key, _, _) in enumerate(anim_engine.MOTION_EFFECTS):
        p.drawText(QRectF(4, row * th + th / 2 - 8, 112, 16), key)
        for col, frame in enumerate(tiles[row]):
            p.drawImage(QRectF(120 + col * tw, row * th, tw, th),
                        frame.scaled(tw, th, Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation))
    p.end()
    path = os.path.join(OUT, "motion_qt_strip.png")
    strip.save(path)
    print("  saved", path)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
