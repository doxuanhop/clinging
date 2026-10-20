"""Lớp phủ recap phải hiện ở CẢ HAI đường vẽ, cùng hình dạng, và tắt sạch khi master off.

Preview : PreviewCanvas.drawForeground  (widget thật, grab() thật)
Export  : FrameComposer.render_frame    (đúng đường video_writer đi qua)

Gate:
  1. enabled=False nhưng mọi lớp con BẬT  -> ảnh preview giống hệt từng byte.
  2. Bật viền + tâm ngắm + REC -> đủ px màu viền / cyan / đỏ, và tâm cyan nằm
     đúng giữa khung (bắt lỗi vẽ lệch gốc tọa độ).
  3. Cùng settings + cùng t: tỉ lệ px mỗi lớp ở preview và export sát nhau, và
     tâm cyan ở hai khung cùng là 0.5 -> một seam, hai đường vẽ.
  4. Nền kính mờ: góc khung phải tối đi rõ rệt (blur + Multiply + vignette) và
     ảnh chụp scene phải có nội dung (không phải khung đen).
"""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType
from ui.preview_panel import PreviewCanvas

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLID = os.path.join(HERE, "scratch", "recap_solid_orange.png")
EVIDENCE = os.path.join(HERE, "scratch", "recap_overlay_evidence.png")
VIEW_W, VIEW_H = 1920, 1080
EXP_W, EXP_H = 1920, 1080

APP = QApplication.instance() or QApplication([])
# Console của máy này là cp1252; dòng báo cáo có dấu tiếng Việt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_source():
    """Ảnh nguồn một màu camNoR — nền sạch để đếm màu lớp phủ."""
    if not os.path.exists(SOLID):
        img = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#FF7A00"))
        img.save(SOLID)
    return SOLID


def make_model(settings):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.IMAGE)
    clip = model.add_clip(track.track_id, make_source(), "image", 0.0, 4.0, name="n")
    if clip is None:
        raise RuntimeError("add_clip tra None (track/media khong khop)")
    from core.canvas_utils import apply_auto_fit
    apply_auto_fit(clip, 1920, 1080)
    model.set_recap_overlay(settings)
    model.playhead = 1.0
    return model


def grab_view(model):
    """grab() đúng widget PreviewCanvas — không tự vẽ lại bằng tay."""
    view = PreviewCanvas()
    view.resize(VIEW_W, VIEW_H)
    view.sync_scene_from_model(model, lambda c: None)
    for item in view._clip_items.values():
        item.set_local_time(float(model.playhead))
    pm = view.grab()
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if img.width() != VIEW_W or img.height() != VIEW_H:
        raise RuntimeError("grab() ra %dx%d khong phai %dx%d (DPR?) - moi so san"
                           % (img.width(), img.height(), VIEW_W, VIEW_H))
    view.scene_obj.clear()
    view.deleteLater()
    return img


def render_export(model):
    composer = FrameComposer(model, EXP_W, EXP_H)
    img = composer.render_frame(1.0)
    composer.close()
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def rgb(img):
    row = img.bytesPerLine() // 4
    a = np.frombuffer(img.constBits(), np.uint8,
                      count=row * 4 * img.height()).reshape(
        img.height(), row, 4)[:, :img.width()]
    return a[:, :, 2::-1].astype(np.int16)          # BGR -> RGB


def near(img, hexcolor, tol=36):
    c = QColor(hexcolor)
    m = np.abs(rgb(img) - np.array([c.red(), c.green(), c.blue()], dtype=np.int16))
    return m.max(axis=2) <= tol


def frac(img, hexcolor, tol=36):
    return float(near(img, hexcolor, tol).mean())


def centroid(img, hexcolor, tol=36):
    m = near(img, hexcolor, tol)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    h, w = m.shape
    return (float(xs.mean() + 0.5) / w, float(ys.mean() + 0.5) / h)


def corner_lum(img):
    """Độ sáng dải 6% biên — nơi kính mờ phải lộ ra."""
    a = rgb(img)[:, :, :3].max(axis=2)
    h, w = a.shape
    mx, my = max(1, int(w * 0.06)), max(1, int(h * 0.06))
    band = np.concatenate([a[:my].ravel(), a[-my:].ravel(),
                           a[:, :mx].ravel(), a[:, -mx:].ravel()])
    return float(band.mean())


def full():
    return {"enabled": True, "glass": False, "border": True,
            "border_color": "#3673FE", "reticle": True, "reticle_shape": "cross",
            "reticle_color": "#00FFFF", "rec": True, "rec_fps": 30}


def expect(w, h):
    """Số px dẫn xuất trên GIẤY từ spec tham chiếu (viền 4px, cánh 8->28, chấm
    REC r5, tất cả ở khung 720). Không đọc hằng số trong core/recap_overlay,
    nên sai hệ số k hay thiếu một cánh là gate đỏ ngay."""
    k = max(0.2, min(w, h) / 720.0)
    return {
        "border": 2 * (w + h) * (4.0 * k),
        "reticle": 4 * (28 - 8) * k * (2.0 * k) + math.pi * (2.0 * k) ** 2,
        "rec_dot": math.pi * (5.0 * k) ** 2,
    }


def red_mask(img):
    return (np.abs(rgb(img) - np.array([220, 0, 0], dtype=np.int16)).max(axis=2) <= 45)


def hot_mask(img):
    a = rgb(img)
    return (a[:, :, 0] > 150) & (a[:, :, 1] < 90) & (a[:, :, 2] < 90)


def check_layer(name, img, mask, ratio_lo=0.45, ratio_hi=1.7):
    w, h = img.width(), img.height()
    got = float(mask.sum())
    want = expect(w, h)[name]
    if not (ratio_lo * want <= got <= ratio_hi * want):
        raise RuntimeError("lop %s: do duoc %.0f px, giai tích %.0f px (%.2fx)"
                           % (name, got, want, got / want))
    return got, want


def rec_geometry(img):
    """Chấm REC phải ở góc trên trái; vạch đỏ đỉnh phải vắt ngang khung."""
    m = red_mask(img)
    h, w = m.shape
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        raise RuntimeError("khong co px nao mau do REC")
    dot = np.zeros_like(m)
    cx, cy = int(0.025 * w), int(0.0417 * h)          # (32,30) o khung 720 x k
    r = int(0.012 * w)
    dot[max(0, cy - r):cy + r, max(0, cx - r):cx + r] = True
    if not (m & dot).any():
        raise RuntimeError("thieu cham REC goc tren trai (%d,%d)" % (cx, cy))
    line = hot_mask(img) & (np.arange(h)[:, None] < int(0.03 * h))
    lx = np.nonzero(line.any(axis=0))[0]
    if len(lx) < 0.8 * w:
        raise RuntimeError("vach do dinh chi dai %.0f/%d px" % (len(lx), w))
    return int((m & dot).sum()), int(len(lx))


def main():

    # --- 1. master off khong duoc cham vao anh -----------------------------
    off = dict(full())
    off["enabled"] = False
    a = grab_view(make_model(off))
    b = grab_view(make_model({"enabled": False}))
    if not np.array_equal(rgb(a), rgb(b)):
        raise RuntimeError("master off nhung preview van doi (%d px lech)"
                           % int((np.abs(rgb(a) - rgb(b)).max(axis=2) > 6).sum()))
    if frac(a, "#00FFFF") > 0.0005:
        raise RuntimeError("enabled=False ma van thay tam ngam cyan")

    # --- 2. ba lop vector phai hien o preview ------------------------------
    img = grab_view(make_model(full()))
    measured = {}
    measured["border"] = check_layer("border", img, near(img, "#3673FE", 45))
    measured["reticle"] = check_layer("reticle", img, near(img, "#00FFFF", 45))
    measured["rec_dot"] = check_layer("rec_dot", img, red_mask(img))
    dot_px, line_px = rec_geometry(img)
    cen = centroid(img, "#00FFFF")
    if cen is None or abs(cen[0] - 0.5) > 0.02 or abs(cen[1] - 0.5) > 0.02:
        raise RuntimeError("tam ngam lech tam khung: %s" % (cen,))

    # --- 3. parity preview <-> export --------------------------------------
    e = render_export(make_model(full()))
    ec = centroid(e, "#00FFFF")
    if ec is None or abs(ec[0] - 0.5) > 0.02 or abs(ec[1] - 0.5) > 0.02:
        raise RuntimeError("export ve tam ngam lech: %s" % (ec,))
    e_dot, e_line = rec_geometry(e)
    pair = {}
    for name, mask in (("border", lambda im: near(im, "#3673FE", 45)),
                       ("reticle", lambda im: near(im, "#00FFFF", 45)),
                       ("rec_dot", red_mask)):
        pv = float(mask(img).sum())
        ex = float(mask(e).sum())
        if ex <= 0 or not (0.8 <= pv / ex <= 1.25):
            raise RuntimeError("preview/export lech lop %s: %.0f vs %.0f px" % (name, pv, ex))
        pair[name] = [int(pv), int(ex)]
    if abs(dot_px - e_dot) > max(40, 0.25 * e_dot) or abs(line_px - e_line) > 0.15 * e_line:
        raise RuntimeError("REC lech git hai duong: dot %d/%d, vach %d/%d"
                           % (dot_px, e_dot, line_px, e_line))

    # --- 4. nen kinh mo ------------------------------------------------------
    glass = dict(full())
    glass["glass"] = True
    g = grab_view(make_model(glass))
    plain_lum, glass_lum = corner_lum(img), corner_lum(g)
    if glass_lum >= plain_lum * 0.75:
        raise RuntimeError("kinh mo khong toi goc khung (%.1f -> %.1f)"
                           % (plain_lum, glass_lum))
    if corner_lum(g) < 8.0:
        raise RuntimeError("goc kinh mo den het = anh chup scene rong")
    ge = corner_lum(render_export(make_model(glass)))
    if ge >= corner_lum(e) * 0.75:
        raise RuntimeError("export khong co kinh mo (%.1f vs %.1f)" % (corner_lum(e), ge))

    # --- anh chung minh: 4 o (vector / glass / xuat vector / xuat glass) -----
    from PySide6.QtCore import QRectF
    cell_w, cell_h = VIEW_W // 2, VIEW_H // 2
    sheet = QImage(cell_w * 2, cell_h * 2, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#09090b"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    shots = [img, g, e, render_export(make_model(glass))]
    for i, shot in enumerate(shots):
        p.drawImage(QRectF((i % 2) * cell_w, (i // 2) * cell_h, cell_w, cell_h), shot)
    p.setPen(QColor("#ffffff"))
    for i, t in enumerate(("preview vector", "preview glass", "export vector", "export glass")):
        p.drawText(QPointF(12 + (i % 2) * cell_w, 20 + (i // 2) * cell_h), t)
    p.end()
    sheet.save(EVIDENCE)

    print(json.dumps({
        "measured_vs_analytic": {k: [int(v[0]), int(v[1])] for k, v in measured.items()},
        "preview_export_pair": pair,
        "rec_dot_and_top_line": [dot_px, line_px, e_dot, e_line],
        "reticle_centre_preview": [round(v, 4) for v in cen],
        "reticle_centre_export": [round(v, 4) for v in ec],
        "corner_lum_plain_vs_glass_preview": [round(plain_lum, 1), round(glass_lum, 1)],
        "corner_lum_plain_vs_glass_export": [round(corner_lum(e), 1), round(ge, 1)],
        "evidence": EVIDENCE,
    }, ensure_ascii=False))
    print("OK: lop phu recap hien o ca preview lan export, tat sạch khi master off")


if __name__ == "__main__":
    sys.exit(main())
