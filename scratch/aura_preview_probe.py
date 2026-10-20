"""Seam aura phải sống ở CẢ HAI đường vẽ và cho ra khung giống nhau theo t.

Preview: CanvasClipItem.paint -> QGraphicsScene.render
Export : FrameComposer.render_frame

Cùng một clip tại cùng local_time phải có aura ở hai bên, và quay lại đúng t
sau khi đã xem t khác phải ra ĐÚNG ảnh cũ — đó là bằng chứng trạng thái hạt
được suy ra giải tích từ t chứ không giữ trong biến nào.
"""
import gc
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

from core.aura_paint import aura_margin
from core.frame_composer import FrameComposer
from core.timeline_model import EffectData, TimelineModel, TrackType
from ui.graphics_canvas_item import CanvasClipItem

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "scratch", "align_1track.png")
OUT = os.path.join(HERE, "scratch", "aura_preview_evidence.png")
OUT_W, OUT_H = 640, 360
CANVAS_W, CANVAS_H = 1920, 1080

# app phải SỐNG SAU mọi item: PySide6 abort trong GC nếu QApplication bị giải
# phóng trước khi QGraphicsItem còn tham chiếu.
APP = QApplication.instance() or QApplication([])


def make_clip(with_aura=True):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.IMAGE)
    clip = model.add_clip(track.track_id, SRC, "image", 0.0, 4.0, name="aura")
    if clip is None:
        raise RuntimeError("add_clip tra None (loai track/media khong khop)")
    # Đúng đường mà core.commands.AddClip đi qua: transform._media_w chỉ được
    # gán ở đây, nên bỏ bước này thì preview coi scale như vô nghĩa.
    from core.canvas_utils import apply_auto_fit
    apply_auto_fit(clip, CANVAS_W, CANVAS_H)
    clip.transform.scale_x = clip.transform.scale_y = 0.45
    if with_aura:
        clip.effects.append(EffectData(name="Hỏa Diệm", category="Aura",
                                       params={"aura": "fire"}))
    return model, clip


def grab(clip, t):
    """Vẽ cả canvas qua đúng paint() của preview, downscale về 640x360."""
    scene = QGraphicsScene()
    scene.setSceneRect(-CANVAS_W / 2, -CANVAS_H / 2, CANVAS_W, CANVAS_H)
    item = CanvasClipItem(clip, lambda c: None)
    scene.addItem(item)
    item.set_local_time(t)
    img = QImage(OUT_W, OUT_H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, OUT_W, OUT_H),
                 QRectF(-CANVAS_W / 2, -CANVAS_H / 2, CANVAS_W, CANVAS_H))
    painter.end()
    # Rect media (chưa nhân scale) mà item vừa tự tính lúc paint.
    rect_px = item.rect()
    scene.removeItem(item)
    del item, scene
    gc.collect()
    return img, rect_px


def arr(img):
    row = img.bytesPerLine() // 4
    return np.frombuffer(img.constBits(), np.uint8,
                         count=row * 4 * img.height()).reshape(
        img.height(), row, 4)[:, :img.width()].astype(np.int16)


def moved(a, b):
    return float((np.abs(a - b).max(axis=2) > 8).mean())


def lit_outside(img, rect_px):
    """Pixel sáng ngoài rect clip — aura nhất thiết phải tràn ra cạnh."""
    lum = arr(img)[:, :, :3].max(axis=2)
    k = OUT_W / CANVAS_W
    w, h = rect_px.width() * k, rect_px.height() * k
    left, top = int(OUT_W / 2 - w / 2), int(OUT_H / 2 - h / 2)
    outside = lum.copy()
    outside[max(0, top):min(OUT_H, top + int(h)),
            max(0, left):min(OUT_W, left + int(w))] = 0
    return int((outside > 40).sum()), (left, top, int(w), int(h))


def main():
    model, clip = make_clip()
    _, plain_clip = make_clip(False)

    plain, rect_px = grab(plain_clip, 0.4)
    aura_img, _ = grab(clip, 0.4)
    lit, rect = lit_outside(aura_img, rect_px)
    if lit < 20:
        raise RuntimeError("preview khong co aura ngoai rect clip (%d px sang, rect %s)"
                           % (lit, rect))
    if moved(arr(plain), arr(aura_img)) < 0.002:
        raise RuntimeError("aura khong doi khung preview")

    if not np.array_equal(arr(grab(clip, 0.4)[0]), arr(aura_img)):
        raise RuntimeError("preview khong tat dinh: cung t ra hai anh khac nhau")
    grab(clip, 2.7)
    if not np.array_equal(arr(grab(clip, 0.4)[0]), arr(aura_img)):
        raise RuntimeError("preview bi nhiem sau khi xem t khac (particle state)")

    composer = FrameComposer(model, OUT_W, OUT_H)
    e1 = arr(composer.render_frame(0.4))
    composer.render_frame(2.7)
    e2 = arr(composer.render_frame(0.4))
    if not np.array_equal(e1, e2):
        raise RuntimeError("export khong tat dinh khi scrub nguoc (diff %.5f)"
                           % moved(e1, e2))
    composer.close()

    margin = aura_margin(rect_px, clip.effects)
    if margin <= 0:
        raise RuntimeError("aura_margin = 0 nen boundingRect khong du cho ve")

    aura_img.save(OUT)
    print(json.dumps({
        "preview_lit_outside_rect": lit,
        "preview_changed": round(moved(arr(plain), arr(aura_img)), 4),
        "clip_rect_px": list(rect),
        "export_scrub_diff": round(moved(e1, e2), 6),
        "aura_margin_canvas_px": round(margin, 1),
        "evidence": OUT,
    }, ensure_ascii=False))
    print("OK preview+export cùng vẽ aura và tất định theo t")


if __name__ == "__main__":
    sys.exit(main())
