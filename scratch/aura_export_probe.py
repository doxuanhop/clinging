"""Chứng minh aura vẽ thật trong khung hình EXPORT, không chỉ trong aura_paint.

Cùng một project, cùng một t; khác nhau đúng một EffectData Aura. Nếu exporter
không gọi seam thì ảnh hai bên giống hệt nhau -> probe đỏ.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from core.aura_paint import aura_margin
from core.frame_composer import FrameComposer
from core.timeline_model import ClipModel, EffectData, TimelineModel, TrackType

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "scratch", "align_1track.png")
OUT = os.path.join(HERE, "scratch", "aura_export_evidence.png")


def build(with_aura, t_label):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.IMAGE)
    clip = model.add_clip(track.track_id, SRC, "image", 0.0, 4.0, name=t_label)
    if clip is None:
        raise RuntimeError("add_clip trả None: track/loai media khong khop")
    # Cùng đường layout mà core.commands.AddClip dùng (fit/auto), để transform
    # mang đúng _media_w/original_w như project thật của người dùng.
    from core.canvas_utils import apply_auto_fit
    apply_auto_fit(clip, 1920, 1080)
    # Phóng nhỏ để chừa vùng quanh clip mà aura có thể tràn ra.
    clip.transform.scale_x = 0.45
    clip.transform.scale_y = 0.45
    if with_aura:
        clip.effects.append(EffectData(
            name="Hỏa Diệm", category="Aura", params={"aura": "fire"}))
    return model, clip


def qimage_to_array(img: QImage) -> np.ndarray:
    """Đọc đúng RGBA8888 mà render_frame trả về (khớp export -> ffmpeg)."""
    assert img.format() == QImage.Format.Format_RGBA8888, img.format()
    row = img.bytesPerLine() // 4
    return np.frombuffer(img.constBits(), np.uint8,
                         count=row * 4 * img.height()).reshape(
        img.height(), row, 4)[:, :img.width()].astype(np.int16)


def main():
    app = QApplication.instance() or QApplication([])  # noqa: F841
    model_a, clip_a = build(False, "khong aura")
    model_b, clip_b = build(True, "co aura")
    composer_a = FrameComposer(model_a, 640, 360)
    composer_b = FrameComposer(model_b, 640, 360)

    for t in (0.4, 1.9):
        ia = composer_a.render_frame(t)
        ib = composer_b.render_frame(t)
        if ia.isNull() or ib.isNull():
            raise RuntimeError("render_frame tra anh trong: exporter chay khong den")
        aa, ab = qimage_to_array(ia), qimage_to_array(ib)
        diff = (np.abs(aa - ab).max(axis=2) > 8)
        changed = float(diff.mean())
        if changed < 0.002:
            raise RuntimeError("t=%.1f aura KHONG doi khung export (%.4f)" % (t, changed))

        # Aura phải vẽ NGOÀI rect clip: quy rect clip trong toanh canvas cua
        # khung 640x360 tu scale cua clip va canvas goc cua model.
        rect = _clip_rect_in_frame(composer_b, clip_b, ia.width(), ia.height())
        outside = diff.copy()
        outside[max(0, rect.top()):min(diff.shape[0], rect.bottom()),
                max(0, rect.left()):min(diff.shape[1], rect.right())] = False
        out_frac = float(outside.sum())
        if out_frac < 20:
            raise RuntimeError("t=%.1f khong co pixel nao ngoai rect clip (%d)"
                              % (t, out_frac))

        if t == 0.4:
            ia.save(OUT.replace(".png", "_plain.png"))
            ib.save(OUT)
            from PySide6.QtCore import QRectF
            bw, bh = composer_b._base_size(clip_b)
            clip_rect_canvas = QRectF(0, 0, bw * clip_b.transform.scale_x,
                                      bh * clip_b.transform.scale_y)
            print(json.dumps({
                "t": t, "changed": round(changed, 4), "outside_rect_px": out_frac,
                "clip_rect": [rect.left(), rect.top(), rect.width(), rect.height()],
                "aura_margin_canvas_px": round(
                    aura_margin(clip_rect_canvas, clip_b.effects), 1),
            }, ensure_ascii=False))
    print("OK aura hiện trong khung export và tràn ra ngoài rect clip")


def _clip_rect_in_frame(composer, clip, fw, fh):
    """Rect clip trong toanh pixel khung in, tinh bang dung _base_size cua exporter."""
    from PySide6.QtCore import QRect
    base_w, base_h = composer._base_size(clip)
    kx, ky = fw / composer.canvas_w, fh / composer.canvas_h
    w = base_w * clip.transform.scale_x * kx
    h = base_h * clip.transform.scale_y * ky
    cx = fw / 2.0 + clip.transform.x * kx
    cy = fh / 2.0 + clip.transform.y * ky
    return QRect(int(cx - w / 2), int(cy - h / 2), int(w), int(h))


if __name__ == "__main__":
    sys.exit(main())
