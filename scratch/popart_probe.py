"""
scratch/popart_probe.py
Bằng chứng cho #41 (bộ lọc màu POP ART) và #45 (công thức contrast đã sửa).

Sáu câu hỏi probe này phải trả lời bằng số đo, không bằng lời văn:
  1. Tương phản có thật sự là HỆ SỐ NHÂN quanh trục giữa không — mọi preset
     "Sắc thái" đã bán phải giữ nguyên chiều sáng tối (tương quan > 0.9), vì
     công thức cũ biến Warm Tone/B&W/Cinematic/Neon Glow thành ảnh đảo màu.
  2. Ba chặng vẽ (halftone / posterize / outline) có làm đúng điều tên nó nói
     không: lưới chấm tuần hoàn đúng ô, bậc màu đúng số bậc, viền chỉ nằm trên
     biên độ sáng.
  3. Cường độ 0 có trả nguyên ảnh không, và mỗi chặng có đổi ảnh thật không.
  4. Preview và export có cùng một khung hình pop art không.
  5. Hiệu ứng có sống qua undo và qua file .clinq không; thẻ trong bảng hiệu
     ứng có vẽ ra icon thật không.
  6. Dong --selftest cua app that bai duoc khong — danh dau ca ham thanh
     identity thi no phai noi.

Phản chứng: ba hàm vẽ và hàm tương phản bị giả lập thành "trả nguyên ảnh" giữa
chứng. Mọi khoa "nhìn thấy khác" phải NO. Một khoa không thể sai thì không
được tính là khoa.

Chạy: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/popart_probe.py
"""

import json
import os
import shutil
import statistics
import sys
import time
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")
TMP = os.path.join(OUT, "popart_tmp")
SRC_FRAME = os.path.join(OUT, "popart_src.png")
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
CLINQ = os.path.join(TMP, "project.clinq")
EVIDENCE = os.path.join(OUT, "clinging_popart.png")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QGraphicsScene

import core.clip_effects as ce
from core.timeline_model import EFFECT_PRESETS, EffectData, TimelineModel, track_type_for_media

W, H = 640, 360          # cỡ khung xuất
CW, CH = 1920, 1080      # cỡ canvas của project 16:9
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want ~%r+-%r" % (label, got, want, tol))
    print("%-58s %s got=%r want~%.2f+-%.2f"
          % (label, "PASS" if ok else "FAIL", got, want, tol))
    return ok


def above(label, got, limit):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-58s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def below(label, got, limit):
    ok = got is not None and got < limit
    if not ok:
        fails.append("%s: got %r want < %r" % (label, got, limit))
    print("%-58s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


# ── mảng màu ────────────────────────────────────────────────────

def ramp_rgb(w=256, h=96):
    """Dải sáng đều 0..255 theo trục X, lặp lại theo trục Y."""
    x = np.linspace(0.0, 255.0, w, dtype=np.float32)
    return np.repeat(x[None, :, None], h, axis=0).repeat(3, axis=2)


def mid_ramp_rgb(w=256, h=96):
    """Dải 40..215 — du lieu that, khong sat hai mép 0/255 cua anh.

    Can cho phep do tuong phan: anh 0..255 sau khi nhân quanh 128 van bi kep
    ve 0..255 nen "mo dai" khong the hien ra.
    """
    x = np.linspace(40.0, 215.0, w, dtype=np.float32)
    return np.repeat(x[None, :, None], h, axis=0).repeat(3, axis=2)


def blocks_rgb(w=256, h=256):
    """Bốn khối màu bão hoà cao — nơi lỗi đảo màu lộ ra ngay."""
    a = np.zeros((h, w, 3), np.float32)
    a[:h // 2, :w // 2] = (232, 48, 64)
    a[:h // 2, w // 2:] = (40, 176, 96)
    a[h // 2:, :w // 2] = (48, 96, 232)
    a[h // 2:, w // 2:] = (240, 200, 40)
    return a


def grey_rgb(value, w=192, h=192):
    return np.full((h, w, 3), float(value), np.float32)


def edge_rgb(w=192, h=192):
    """Trai 245 / phai 120: net vien o bien phai toi hon 120 - 40 moi nhin thay."""
    a = np.zeros((h, w, 3), np.float32)
    a[:, :w // 2] = 245.0
    a[:, w // 2:] = 120.0
    return a


def luma(a):
    return 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]


def corr(a, b):
    x = np.asarray(a, np.float64).ravel()
    y = np.asarray(b, np.float64).ravel()
    return float(np.corrcoef(x, y)[0, 1])


def qimage_from_np(a):
    arr = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
    h, w = arr.shape[:2]
    rgb = np.dstack([arr, np.full((h, w, 1), 255, np.uint8)])
    rgb = np.ascontiguousarray(rgb)
    return QImage(rgb.data, w, h, w * 4,
                  QImage.Format.Format_RGBA8888).copy()


def np_from_qimage(image):
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4))[:, :, :3].astype(np.float64)


def apply_params(params, intensity=1.0, image=None):
    """Đi đúng đường production: apply_color_effects trên QImage."""
    src = image if image is not None else ramp_qimage
    return np_from_qimage(ce.apply_color_effects(
        src, [EffectData(name="Pop Art", category="Sắc thái",
                         intensity=intensity, params=dict(params))]))


# ── 1. tuong phan: he so nhan, khong phai do lech ───────────────

def gate_contrast():
    """Doi tuong phan tren dai 40..215, KHONG phai 0..255.

    Với dải 0..255, đối chiếu "mo dai" không bao giờ thấy gì: ảnh nào cũng
    chạm hai mép 0 và 255 sau khi kẹp, nên hệ số 1.1 trông như không đổi.
    Dải giữa 40..215 cho phép phép nhân quanh 128 thực sự nới/bóp khoảng màu.
    """
    old_formula = lambda c: (259.0 * (c * 255 + 255)) / (255.0 * (259 - c * 255))
    presets = {n: p for n, p in EFFECT_PRESETS.items() if "contrast" in p}
    above("preset co khoa contrast", len(presets), 4)
    base = np_from_qimage(mid_qimage)
    base_lum = luma(base)
    base_spread = float(base.max() - base.min())
    for name, params in sorted(presets.items()):
        out = apply_params({"contrast": params["contrast"]}, image=mid_qimage)
        r = corr(base_lum, luma(out))
        check("%-12s khong dao mau (tuong quan sang)" % name, r > 0.9, True)
        c = params["contrast"]
        spread = float(out.max() - out.min())
        if abs(c - 1.0) > 1e-9:
            want = spread > base_spread if c > 1 else spread < base_spread
            check("%-12s contrast %.2f %s dai (%.0f->%.0f)"
                  % (name, c, "mo" if c > 1 else "hut", base_spread, spread),
                  bool(want), True)
        # Phan chung: cong thuc cu DAO anh tren chinh du lieu that.
        if c > 259.0 / 255.0:
            check("%-12s cong thuc cu cho he so am" % name, old_formula(c) < 0, True)
    # B&W phai mat het mau that (sat == 0), khong phai den san do dao mau.
    bw = apply_params(EFFECT_PRESETS["B&W"])
    near("B&W cho ba kenh bang nhau", float(np.abs(bw[:, :, 0] - bw[:, :, 2]).max()), 0.0, 1.0)


# ── 2. ba chang ve ──────────────────────────────────────────────

def ink_fraction(grey_value, cell=6.0):
    """Ty le pixel la muc in, DO TRUC TIEP tren anh ra.

    Khong dung lai hang so muc/giay cua production: mot o da in ra dung hai
    muc (cham muc va nen giay), nen dem pixel o muc thap hon. Ban "tra nguyen
    anh" chi con MOT muc -> tra None -> moi khoa sach muc phai NO.
    """
    out = np.round(ce.halftone_rgb(grey_rgb(grey_value), cell)[:, :, 0], 2)
    lo, hi = float(out.min()), float(out.max())
    if hi - lo < 1.0:
        return None
    return float(np.mean(out <= (lo + hi) / 2.0))


def poster_levels(out, levels):
    """So gia tri khac biet o mot kenh — dung np.unique vi slice la mang 2 chieu."""
    return int(len(np.unique(np.round(out[:, :, 0], 3))))


def gate_stages():
    a = np_from_qimage(ramp_qimage).astype(np.float32)

    for levels in (2, 4, 6, 8):
        uniq = poster_levels(ce.posterize_rgb(a, levels), levels)
        check("posterize %d bac cho dung %d bac" % (levels, levels), uniq, levels)
    p4 = ce.posterize_rgb(a, 4.0)
    check("posterize khong doi hai dau 0/255",
          (round(float(p4[0, 0, 0]), 3), round(float(p4[0, -1, 0]), 3)), (0.0, 255.0))
    check("posterize lap lai khong con doi (idempotent)",
          bool(np.allclose(ce.posterize_rgb(p4, 4.0), p4, atol=1e-3)), True)

    cell = 6.0
    # Dong 0 cua o luoi LUON nam ngoai cham (ban kinh cham < nua o), nen do
    # tuan hoan phai lay dong qua tam o — dong 3 voi luoi 6px.
    row = luma(ce.halftone_rgb(grey_rgb(128.0), cell))[int(cell) // 2]
    d = row - row.mean()
    ac = np.correlate(d, d, mode="full")[len(d) - 1:]
    lag = int(np.argmax(ac[2:40])) + 2
    check("luu cham bi tuan hoan dung theo kich thuoc o", lag, int(cell))
    above("luu cham bi co dot that (bien thien)", float(row.std()), 5.0)
    near("o trung tinh in duoc ty le muc vo ly", ink_fraction(128.0, cell), 0.33, 0.14)

    # Dinh luat halftone: dien tich muc in tang theo do toi. Tu 240 tro len thi
    # cham nho hon mot pixel mau nen in ra GIAY TRANG — do la gioi han that cua
    # luoi cham, nen que do chi lay 16..224 (cong nhan vung in duoc).
    tones = np.arange(16.0, 225.0, 16.0)
    fracs = [ink_fraction(v, cell) for v in tones]
    check("halftone con du hai muc muc/giay trong vung in duoc",
          all(f is not None for f in fracs), True)
    if all(f is not None for f in fracs):
        dark = 1.0 - tones / 255.0
        slope = float(np.polyfit(dark, fracs, 1)[0])
        above("dien tich muc in ti le thuan do toi (tuong quan)", corr(dark, fracs), 0.90)
        above("he so goc duong sach muc in", slope, 0.45)
        below("cham khong lap day kin o (he so goc)", slope, 0.85)
        check("muc in khong tang khi anh sang dan",
              all(fracs[i] >= fracs[i + 1] for i in range(len(fracs) - 1)), True)
        below("o sang nhat in rat it muc", float(fracs[-1]), 0.20)
        above("o toi nhat nap muc ran", float(fracs[0]), 0.50)

    flat = grey_rgb(128.0)
    check("vien khong cham vung phang",
          float(np.abs(ce.outline_rgb(flat, 0.9) - flat).max()), 0.0)
    e = edge_rgb()
    on_edge = ce.outline_rgb(e, 0.35)[:, :, 0] < e[:, :, 0] - 40.0
    near("vien nam dung bien do sang (cot)", float(np.argmax(on_edge[0, :]) + 1),
         e.shape[1] // 2, 2.0)
    check("vien khong lan ca mien sang",
          float(on_edge[:, :e.shape[1] // 2 - 3].mean()), 0.0)
    thin = float(ce.outline_rgb(e, 0.05)[:, :, 0].min())
    thick = float(ce.outline_rgb(e, 0.95)[:, :, 0].min())
    check("tang do nhay thi net dam hon", thick < thin, True)

    b = ce._blend(a, ce.posterize_rgb(a, 4.0), 0.0)
    check("chen k=0 tra nguyen ven", bool(np.array_equal(b, a)), True)
    check("chen k=1 tra dung ket qua chang ve",
          bool(np.array_equal(ce._blend(a, ce.posterize_rgb(a, 4.0), 1.0),
                              ce.posterize_rgb(a, 4.0))), True)
    mid = ce._blend(a, ce.posterize_rgb(a, 4.0), 0.5)
    check("chen k=0.5 nam giua hai dau",
          bool(np.all((mid > np.minimum(a, ce.posterize_rgb(a, 4.0)) - 1e-3)
                      & (mid < np.maximum(a, ce.posterize_rgb(a, 4.0)) + 1e-3))), True)


# ── 3. phan chung: xoa ca chang ve thi khoa phai NO ─────────────

def counterfactual_stages():
    originals = {n: getattr(ce, n) for n in
                 ("posterize_rgb", "halftone_rgb", "outline_rgb", "contrast_rgb")}
    identity = lambda arr, *a, **k: arr
    full = dict(EFFECT_PRESETS["Pop Art"])
    base = np_from_qimage(ramp_qimage)
    try:
        for n in originals:
            setattr(ce, n, identity)
        dead = apply_params(full)
        diff_dead = float(np.abs(dead - base).mean())
        check("phan chung: xoa het chang ve thi anh khong doi", diff_dead < 1.0, True)
        check("phan chung: khoa 'pop art doi anh' phai NO khi xoa ham ve",
              diff_dead > 10.0, False)
        check("phan chung: posterize khong con nen bac",
              poster_levels(ce.posterize_rgb(base.astype(np.float32), 4.0), 4) <= 4,
              False)
    finally:
        for n, fn in originals.items():
            setattr(ce, n, fn)
    check("ham ve duoc khoi phuc dung ban goc",
          all(getattr(ce, n) is fn for n, fn in originals.items()), True)
    alive = float(np.abs(apply_params(full) - base).mean())
    above("sau khi khoi phuc, pop art lai doi anh that", alive, 10.0)
    # Dong selftest cua app cung phai that bai duoc khi ham ve bi xoa.
    import diagnostics
    try:
        for n in originals:
            setattr(ce, n, identity)
        ok_when_dead = diagnostics._popart_ok()
        check("dong selftest pop art van chay khi ham ve bi xoa (SAI)",
              "KHONG the xay ra", "exception")
    except Exception as exc:
        check("dong selftest pop art NO khi ham ve bi xoa",
              bool(str(exc)), True)
    finally:
        for n, fn in originals.items():
            setattr(ce, n, fn)


# ── 4. preview vs export ────────────────────────────────────────

def build_clip(model, params, intensity=1.0):
    track = model.add_track(track_type_for_media("image"), "Main")
    clip = model.add_clip(track.track_id, SRC_FRAME, "image", 0.0, 4.0, "src.png")
    clip.effects = [EffectData(name="Pop Art", category="Sắc thái",
                               intensity=intensity, params=dict(params))]
    return track, clip


def to_array(image):
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.float64)


def export_frame(model, t):
    from core.frame_composer import FrameComposer
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def preview_frame(clip, t):
    from ui.graphics_canvas_item import CanvasClipItem
    scene = QGraphicsScene()
    scene.setSceneRect(-CW / 2.0, -CH / 2.0, CW, CH)
    item = CanvasClipItem(clip)
    scene.addItem(item)
    item.set_local_time(t)
    img = QImage(CW, CH, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    from PySide6.QtGui import QPainter
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        scene.render(p, QRectF(0, 0, CW, CH), QRectF(-CW / 2.0, -CH / 2.0, CW, CH))
    finally:
        p.end()
    return img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def gate_parity():
    plain = TimelineModel()
    plain.project_ratio = "16:9"
    _, plain_clip = build_clip(plain, {})
    pop = TimelineModel()
    pop.project_ratio = "16:9"
    _, pop_clip = build_clip(pop, EFFECT_PRESETS["Pop Art"])

    base = to_array(export_frame(plain, 1.0))
    art = to_array(export_frame(pop, 1.0))
    changed = float((np.abs(base - art).max(axis=2) > 16).mean())
    above("pop art thay doi anh xuat (khong phai khoa trong rong)", changed, 0.2)

    drift = float(np.abs(art - to_array(preview_frame(pop_clip, 1.0))).mean())
    near("preview va export cung mot khung pop art", drift, 0.0, 6.0)
    above("khung xuat co noi dung that (std)", float(art.std()), 5.0)
    above("pop art doi nhieu hon 20% pixel", changed, 0.2)
    return {"base": base, "art": art,
            "preview": to_array(preview_frame(pop_clip, 1.0))}


# ── 5. undo + file .clinq ───────────────────────────────────────

def gate_undo_and_file():
    from core.commands import ApplyEffectCommand, RemoveEffectCommand, UndoStack
    model = TimelineModel()
    model.project_ratio = "16:9"
    track, clip = build_clip(model, {})
    clip.effects = []
    stack = UndoStack()
    card = {"name": "Pop Art", "category": "Sắc thái", "icon": "fa6s.circle-dot"}
    stack.push(ApplyEffectCommand(model, clip.clip_id, card))
    got = model.get_clip(clip.clip_id).effects
    check("lenh ap hieu ung dung dung preset", len(got), 1)
    check("ap hieu ung ghi dung ten", got[0].name, "Pop Art")
    check("ap hieu ung mang theo du tham so ve",
          sorted(k for k in got[0].params if k in ("halftone", "posterize", "outline")),
          ["halftone", "outline", "posterize"])
    stack.undo()
    check("hoan tac go bo hieu ung", len(model.get_clip(clip.clip_id).effects), 0)
    stack.redo()
    check("redo tra lai hieu ung", len(model.get_clip(clip.clip_id).effects), 1)

    import core.project_storage as ps
    os.makedirs(TMP, exist_ok=True)
    ps.AUTO_SAVE_FILE = os.path.join(TMP, "autosave.json")
    ps.save_project_to_file(model, CLINQ, {"name": "popart-probe"})
    reloaded = ps.load_project_from_file(CLINQ)
    check("file mo duoc", reloaded is not None, True)
    model2 = TimelineModel()
    ps.restore_model_from_clinq(model2, reloaded)
    clip2 = model2.get_clip(clip.clip_id)
    check("clip khoi phuc", clip2 is not None, True)
    eff = clip2.effects[0]
    check("ten hieu ung song qua file", eff.name, "Pop Art")
    check("toan bo tham so ve song qua file",
          {k: round(v, 4) for k, v in sorted(eff.params.items())},
          {k: round(v, 4) for k, v in sorted(EFFECT_PRESETS["Pop Art"].items())})
    art_file = to_array(export_frame(model2, 1.0))
    near("frame xuat tu file da mo van la pop art",
         float(np.abs(art_file - gate_parity_cache["art"]).mean()), 0.0, 1.0)


# ── 6. the trong bang hieu ung ──────────────────────────────────

def gate_card():
    from ui.effects_panel import EFFECT_CATEGORIES
    from widgets.common import icon_pixmap
    cards = EFFECT_CATEGORIES["Sắc thái"]
    pop = [c for c in cards if c["name"] == "Pop Art"]
    check("the Pop Art nam trong tab Sac thai", len(pop), 1)
    card = pop[0]
    check("the co mo ta bang tieng Viet", bool(card.get("desc")), True)
    check("the co hai mau doc lap", bool(card.get("color1")) and bool(card.get("color2")), True)
    all_names = [c["name"] for lst in EFFECT_CATEGORIES.values() for c in lst]
    check("ten hieu ung khong trung lap giua cac tab",
          len(all_names), len(set(all_names)))
    check("moi the Sac thai deu co preset trong core",
          all(c["name"] in EFFECT_PRESETS for c in cards), True)
    pm = icon_pixmap(card["icon"], 22, "#FFFFFF")
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    alpha = np.frombuffer(raw, np.uint8).reshape((img.height(), img.width(), 4))[:, :, 3]
    above("icon cua the ve ra pixel that", int((alpha > 0).sum()), 100)


# ── 7. gia thanh moi frame ──────────────────────────────────────

def gate_cost():
    samples = []
    ce.apply_color_effects(ramp_qimage_big, [
        EffectData(name="Pop Art", category="Sắc thái", intensity=1.0,
                   params=EFFECT_PRESETS["Pop Art"])])
    for _ in range(5):
        t0 = time.perf_counter()
        ce.apply_color_effects(ramp_qimage_big, [
            EffectData(name="Pop Art", category="Sắc thái", intensity=1.0,
                       params=EFFECT_PRESETS["Pop Art"])])
        samples.append((time.perf_counter() - t0) * 1000.0)
    med = statistics.median(samples)
    print("  pop art moi frame 1280x720: %s ms (trung vi %.1f)"
          % ([round(s, 1) for s in samples], med))
    below("gia thanh van du cho preview chiu dung duoc", med, 220.0)
    return med


# ── 8. bang chung hinh ─────────────────────────────────────────

def evidence(frames, cost_ms):
    import cv2
    labels = ["1. goc", "2. +posterize %g bac" % EFFECT_PRESETS["Pop Art"]["posterize"],
              "3. +luu cham bi", "4. pop art (them vien)"]
    p = EFFECT_PRESETS["Pop Art"]
    steps = [{"posterize": p["posterize"]},
             {"posterize": p["posterize"], "halftone": p["halftone"]},
             dict(p)]
    rows = []
    for src in frames:
        base = np_from_qimage(qimage_from_np(src))
        tiles = [base]
        for p in steps:
            tiles.append(apply_params(p, image=qimage_from_np(src)))
        rows.append(tiles)

    tile_w, tile_h = 288, 162
    strip = []
    for tiles in rows:
        imgs = [cv2.cvtColor(t.astype(np.uint8), cv2.COLOR_RGB2BGR) for t in tiles]
        strip.append(np.hstack([cv2.resize(i, (tile_w, tile_h)) for i in imgs]))
    grid = np.vstack(strip)
    gap, band, foot = 6, 34, 24
    sheet = np.full((band + gap * 2 + grid.shape[0] + foot,
                     grid.shape[1] + gap, 3), 18, np.uint8)
    for i, text in enumerate(labels):
        x = gap + i * tile_w + 6
        cv2.putText(sheet, text, (x, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                    (235, 235, 235), 1, cv2.LINE_AA)
    sheet[band + gap:band + gap + grid.shape[0], gap:gap + grid.shape[1]] = grid
    note = ("dong 1: ca khung 1280x720   dong 2: phong to 400x800   "
            "trung vi %.1f ms/frame" % cost_ms)
    cv2.putText(sheet, note, (gap, sheet.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                0.44, (200, 200, 200), 1, cv2.LINE_AA)
    path = EVIDENCE
    if not cv2.imwrite(path, sheet):
        raise SystemExit("cannot write evidence image")
    print("evidence image: %s (%d bytes, %dx%d, %.1f ms/frame)"
          % (path, os.path.getsize(path), sheet.shape[1], sheet.shape[0], cost_ms))


# ── main ────────────────────────────────────────────────────────

def write_source_frame():
    import cv2
    if not os.path.exists(VIDEO):
        raise SystemExit("khong co media that: %s" % VIDEO)
    cap = cv2.VideoCapture(VIDEO)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 3))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("khong doc duoc frame tu video nguon")
    cv2.imwrite(SRC_FRAME, frame)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32)
    return [rgb, rgb[100:500, 200:1000]]


def main():
    global ramp_qimage, ramp_qimage_big, mid_qimage, gate_parity_cache
    app = QApplication(sys.argv)
    frames = write_source_frame()
    ramp_qimage = qimage_from_np(ramp_rgb())
    mid_qimage = qimage_from_np(mid_ramp_rgb())
    ramp_qimage_big = qimage_from_np(frames[0])

    print("\n== 1. tuong phan la he so nhan ==")
    gate_contrast()
    print("\n== 2. ba chang ve ==")
    gate_stages()
    print("\n== 3. phan chung ==")
    counterfactual_stages()
    print("\n== 4. preview vs export ==")
    gate_parity_cache = gate_parity()
    print("\n== 5. undo + file .clinq ==")
    gate_undo_and_file()
    print("\n== 6. the trong bang hieu ung ==")
    gate_card()
    print("\n== 7. gia thanh ==")
    cost = gate_cost()
    print("\n== 8. bang chung hinh ==")
    evidence(frames, cost)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    CODE = main()
    sys.exit(CODE)
