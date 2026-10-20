"""Gate: the 14 ported text effects animate, preview == export, and the
properties panel writes through to the model instead of the canvas item.

Run with the real Qt platform plugin so fonts exist:
    QT_QPA_PLATFORM=windows python scratch/text_qt_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")

DUR = 4.0
W, H = 640, 360
CW, CH = 1920, 1080
TEXT = "XIN CHAO\nBAN THE NAO"

import numpy as np

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

from core import anim_engine
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, track_type_for_media
from ui.graphics_canvas_item import TextClipItem

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))


def build_model(effect_key, intensity=0.6):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(track_type_for_media("text"), "Captions")
    clip = model.add_clip(track.track_id, "", "text", 0.0, DUR, TEXT)
    clip.text_effect = effect_key
    clip.text_effect_intensity = intensity
    clip.font_family = "Arial"
    clip.font_size = 96.0
    clip.font_bold = True
    return model, clip


def to_array(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape((img.height(), img.width(), 4)).astype(np.int16)


def changed_fraction(a, b):
    return float((np.abs(a - b).max(axis=2) > 16).mean())


def ink_fraction(a):
    return float((a[:, :, 0].astype(np.int16) > 40).mean())


def export_frame(model, t):
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def preview_frame(clip, t):
    """Vẽ canvas thật ở cỡ project-canvas rồi hạ về cỡ xuất như FrameComposer."""
    scene = QGraphicsScene()
    scene.setSceneRect(-CW / 2.0, -CH / 2.0, CW, CH)
    item = TextClipItem(clip)
    scene.addItem(item)
    item.sync_from_model()
    item.set_local_time(t)
    img = QImage(CW, CH, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    try:
        scene.render(p, QRectF(0, 0, CW, CH), scene.sceneRect())
    finally:
        p.end()
    return img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def main():
    app = QApplication(sys.argv)
    from PySide6.QtGui import QFontDatabase
    fams = QFontDatabase.families()
    check("font database has real families", "Arial" in fams, True)

    # Nhịp lấy mẫu cố tình lệch chu kỳ: wave/scroll chạy vài vòng mỗi clip, và
    # các mốc tròn (0.25/0.5/0.75) rơi đúng pha cũ nên không thấy chữ nhúc nhích.
    times = [DUR * f for f in (0.0, 0.13, 0.29, 0.53, 0.87)]

    # Baseline: chữ đứng yên phải hiện lên và hai bên phải trùng nhau.
    base_model, base_clip = build_model("none")
    base = [to_array(export_frame(base_model, t)) for t in times]
    check("static text draws ink", ink_fraction(base[0]) > 0.002, True)
    check("static text does not animate", changed_fraction(base[0], base[2]) < 0.002, True)
    base_drift = max(float(np.abs(base[i] - to_array(preview_frame(base_clip, times[i]))).mean())
                     for i in range(len(times)))
    print("  static preview-vs-export MAE=%.3f" % base_drift)
    check("static text: preview matches export", base_drift < 8.0, True)

    # Phản chứng: nếu hai đường vẽ thật sự so với nhau thì lệch nhịp phải bị phát
    # hiện. Không có phép thử này, một con số MAE=0.00 có thể chỉ là so ảnh với
    # chính nó.
    cf_model, cf_clip = build_model("slide_in_left")
    mismatch = float(np.abs(to_array(export_frame(cf_model, times[1]))
                            - to_array(preview_frame(cf_clip, times[3]))).mean())
    match = float(np.abs(to_array(export_frame(cf_model, times[1]))
                         - to_array(preview_frame(cf_clip, times[1]))).mean())
    print("  counterfactual: same-phase MAE=%.3f, off-phase MAE=%.3f" % (match, mismatch))
    check("gate detects a phase mismatch", mismatch > max(2.0, 20.0 * match), True)

    tiles = []
    for key, name, _ in anim_engine.TEXT_EFFECTS:
        model, clip = build_model(key)
        frames = [export_frame(model, t) for t in times]
        arrs = [to_array(f) for f in frames]
        peak = max(changed_fraction(arrs[0], a) for a in arrs[1:])
        best_ink = max(ink_fraction(a) for a in arrs)
        drift = max(float(np.abs(arrs[i] - to_array(preview_frame(clip, times[i]))).mean())
                    for i in range(len(times)))
        print("  %-15s ink=%.4f peak=%.3f preview-vs-export MAE=%.3f"
              % (key, best_ink, peak, drift))
        check("%s draws text at some point" % key, best_ink > 0.002, True)
        check("%s animates the frame" % key, key == "none" or peak > 0.002, True)
        check("%s preview matches export" % key, drift < 8.0, True)
        tiles.append(frames)

    ui_checks(tiles)

    tw, th = 256, 144
    strip = QImage(tw * 5 + 150, th * len(tiles), QImage.Format.Format_ARGB32_Premultiplied)
    strip.fill(Qt.GlobalColor.black)
    p = QPainter(strip)
    p.setPen(Qt.GlobalColor.white)
    for row, (key, _, _) in enumerate(anim_engine.TEXT_EFFECTS):
        p.drawText(QRectF(4, row * th + th / 2 - 8, 142, 16), key)
        for col, frame in enumerate(tiles[row]):
            p.drawImage(QRectF(150 + col * tw, row * th, tw, th),
                        frame.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    p.end()
    path = os.path.join(OUT, "text_qt_strip.png")
    strip.save(path)
    print("  saved", path)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


def ui_checks(_tiles):
    """Panel thuộc tính phải ghi vào model — model mới là thứ export đọc."""
    from ui.properties_panel import ClipPropertiesWidget

    model, clip = build_model("none")
    widget = ClipPropertiesWidget(clip)

    check("text card visible for a text clip", widget.card_text.isVisibleTo(widget), True)
    check("motion card visible for a text clip", widget.card_motion.isVisibleTo(widget), True)
    check("form seeded from model font", widget.spin_font_size.value(), 96.0)
    check("form seeded from model bold", widget.btn_bold.isChecked(), True)
    check("form seeded from model effect", widget.combo_text_effect.currentData(), "none")

    widget.spin_font_size.setValue(64.0)
    check("size spin writes model", clip.font_size, 64.0)
    widget.btn_italic.click()
    check("italic button writes model", clip.font_italic, True)
    widget.btn_underline.click()
    check("underline button writes model", clip.font_underline, True)
    widget.combo_text_effect.setCurrentIndex(max(0, widget.combo_text_effect.findData("wave")))
    check("effect combo writes model", clip.text_effect, "wave")
    widget.slider_text_intensity.setValue(35)
    check("intensity slider writes model 0..1", round(clip.text_effect_intensity, 2), 0.35)
    widget.text_edit.setPlainText("HELLO")
    check("content edit writes model name", clip.name, "HELLO")
    check("content edit syncs title field", widget.input_name.text(), "HELLO")

    # Model đổi từ nơi khác (undo, ASR) thì form phải đọc lại theo.
    clip.font_family = "Arial Black"
    clip.text_effect = "typewriter"
    clip.text_effect_intensity = 0.9
    clip.name = "FROM MODEL"
    widget.update_values(clip)
    check("form re-reads font from model", widget.combo_font.currentFont().family(), "Arial Black")
    check("form re-reads effect from model", widget.combo_text_effect.currentData(), "typewriter")
    check("form re-reads intensity from model", widget.slider_text_intensity.value(), 90)
    check("form re-reads text from model", widget.text_edit.toPlainText(), "FROM MODEL")

    # item trên canvas phải lấy style từ model, không phải từ widget
    scene = QGraphicsScene()
    scene.setSceneRect(-CW / 2.0, -CH / 2.0, CW, CH)
    item = TextClipItem(clip)
    scene.addItem(item)
    item.refresh_style()
    check("canvas item font follows model", item.font().family(), "Arial Black")
    check("canvas item text follows model", item.toPlainText(), "FROM MODEL")


if __name__ == "__main__":
    sys.exit(main())
