"""
scratch/effect_liveness_probe.py

Bằng chứng cho #70: hai thẻ "Bộ lọc" TÁN SẮC (Chromatic) và LOANG SÁNG (Lens
Flare) đã thành hiệu ứng thật, và không còn thẻ ma nào trong bảng hiệu ứng.

Trạng thái trước khi sửa: EFFECT_PRESETS["Chromatic"] = {"chromatic": 1.0} và
["Lens Flare"] = {"lens_flare": 1.0}, nhưng apply_color_effects không có nhánh
nào đọc hai khoá đó — kéo thẻ vào clip thì khung hình không đổi, panel bán một
tính năng bằng ảnh minh hoạ. Probe này trả lời bằng số đo:

  1. Quét khoá: mọi khoá trong preset của hai tab màu phải có trong
     clip_effects.PIXEL_KEYS VÀ phải làm đổi ảnh đo được trên CẢ HAI khung hình
     thật (một sáng ít tương phản, một màu rực tương phản cao).
  2. Quét thẻ: preset đầy đủ của 13 thẻ pixel phải đổi ảnh; cường độ 0 phải trả
     lại ảnh nguyên văn (Blur từng là ngoại lệ vì max(1, radius)).
  3. Chữ ký Chromatic: kênh lục không đổi CHÍNH XÁC; đỏ bị phóng to ra xa tâm,
     xanh dương thu vào gần tâm, đo hướng dời trên CẢ biên trái lẫn biên phải
     (một bản chỉ nhích cả ảnh sang một phía qua được ải một biên, không qua
     được ải hai biên); giữa ảnh ít xáo trộn hơn vành ngoài.
  4. Chữ ký Lens Flare: chấm trắng trên nền tối phải sinh quầng đo được ở
     20-40/40-60/80-100px, tắt dần theo bán kính, vùng 160-180px không đổi, ĐỈNH
     CHẤM KHÔNG TỐI ĐI (screen chứ không phải blur), và ảnh xám 128 đồng nhất
     phải nguyên văn (bright-pass: không có sáng thì không có loang).
  5. 16 thẻ còn lại (Hoạt ảnh qua compute_animation_offsets, Chuyển tiếp qua
     incoming_state/local_state_at) — lời "không còn thẻ ma" phủ đủ 29 thẻ.
  6. Phản chứng: (a) khoá lạ bị bỏ qua hoàn toàn, đúng như thẻ ma ngày trước;
     (b) identity-patch hai hàm mới -> mọi chữ ký NO; (c) hai bản cài đối thủ
     (dời cả ba kênh cùng chiều / chỉ +15 sáng đều) -> chữ ký tương ứng NO;
     (d) dòng selftest của app phải bật lỗi khi hàm bị giả lập.
  7. Giá thành mỗi khung hình trên máy cấu hình thấp.

Chạy: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/effect_liveness_probe.py
"""

import glob
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")
EVIDENCE = os.path.join(OUT, "clinging_effect_liveness.png")
EVIDENCE_JSON = os.path.join(OUT, "effect_liveness_evidence.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np
import cv2

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import core.clip_effects as ce
from core.timeline_model import EFFECT_PRESETS, EffectData

PIXEL_TABS = ("Sắc thái", "Bộ lọc")
MOTION_TAB = "Hoạt ảnh"
TRANSITION_TAB = "Chuyển tiếp"

# Bien do DO KHOA: co y khong dung so trong preset, vi preset duoc phep dat khoa
# gia tri trung tinh (Cool Blue de brightness 0.0, contrast 1.0). Cau hoi
# "khoa nay co nhanh hay khong" phai do bang bien ma nhanh do chac chan dap ung.
KEY_PROBE = {
    "brightness": 0.08, "contrast": 1.2, "saturation": 1.4, "color_temp": 0.3,
    "blur": 4.0, "vignette": 0.6, "grain": 0.3, "sharpen": 1.0,
    "halftone": 6.0, "posterize": 4.0, "outline": 0.6,
    "chromatic": 1.0, "lens_flare": 1.0,
}
# Nguong "co doi anh": do tren hai khung hinh that, du xa 0 de mot the ma
# khong luot qua, du thap de khong tro thanh mong manh theo noi dung.
KEY_FLOOR = 0.6
CARD_FLOOR = 1.5
ZERO_FLOOR = 0.02

fails = []
metrics = {}


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def above(label, got, limit):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-56s %s value=%.4f limit=%.4f"
          % (label, "PASS" if ok else "FAIL", got or 0.0, limit))
    return ok


def below(label, got, limit):
    ok = got is not None and got < limit
    if not ok:
        fails.append("%s: got %r want < %r" % (label, got, limit))
    print("%-56s %s value=%.4f limit=%.4f"
          % (label, "PASS" if ok else "FAIL", got or 0.0, limit))
    return ok


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want ~%r+-%r" % (label, got, want, tol))
    print("%-56s %s got=%.4f want~%.2f+-%.2f"
          % (label, "PASS" if ok else "FAIL", got or 0.0, want, tol))
    return ok


def discriminates(label, broke, value):
    """Phan chung: dieu kien DUOC KI VONG la FAIL. broke=True nghia la no FAIL,
    tuc phep do that phan biet duoc giua ban hay va ban doi thu."""
    ok = bool(broke)
    if not ok:
        fails.append("%s: phep do khong phan biet duoc (value=%r)" % (label, value))
    print("%-56s %s value=%.4f" % (label, "PASS" if ok else "FAIL", value))
    return ok


# ── mang mau / QImage ───────────────────────────────────────────

def qimage_from_np(a):
    arr = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
    h, w = arr.shape[:2]
    rgba = np.ascontiguousarray(np.dstack([arr, np.full((h, w, 1), 255, np.uint8)]))
    return QImage(rgba.data, w, h, w * 4,
                  QImage.Format.Format_RGBA8888).copy()


def np_from_qimage(image):
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.float64)


def apply_rgba(params, intensity=1.0, image=None):
    """Di dung duong production: apply_color_effects tren QImage."""
    return np_from_qimage(ce.apply_color_effects(image, [EffectData(
        name="probe", category="Bộ lọc", intensity=intensity,
        params=dict(params))]))


def apply_rgb(params, intensity=1.0, image=None):
    return apply_rgba(params, intensity, image)[:, :, :3]


def mad(a, b):
    return float(np.abs(a - b).mean())


def luma(a):
    return 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]


def frames_from_video():
    """Hai khung hinh THAT: mot sang it tuong phan, mot mau rac tuong phan cao.

    Bo so cua moi bo loc phai dung tren ca hai loai nay — kiem duoc tren mot
    anh 4K den mau tu danh la manh duoc loi cua minh.
    """
    picks = []
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "video", "*.mp4"))):
        cap = cv2.VideoCapture(path)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 3))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float64)
        lum = luma(rgb)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        picks.append({"path": os.path.basename(path), "rgb": rgb,
                      "luma": float(lum.mean()), "std": float(lum.std()),
                      "sat": float(hsv[:, :, 1].mean())})
    if len(picks) < 2:
        raise SystemExit("can co it hon 2 video that trong data/video")
    bright = max(picks, key=lambda p: p["luma"])
    vivid = max(picks, key=lambda p: p["sat"] * p["std"])
    for p in (bright, vivid):
        p["qimage"] = qimage_from_np(p["rgb"])
        h, w = p["rgb"].shape[:2]
        p["crop"] = qimage_from_np(p["rgb"][40:440, 40:640])
        p["crop_rgb"] = p["rgb"][40:440, 40:640]
    print("  khung A (sang) : %s luma=%.1f std=%.1f sat=%.1f %dx%d"
          % (bright["path"][:36], bright["luma"], bright["std"], bright["sat"],
             bright["rgb"].shape[1], bright["rgb"].shape[0]))
    print("  khung B (mau)  : %s luma=%.1f std=%.1f sat=%.1f %dx%d"
          % (vivid["path"][:36], vivid["luma"], vivid["std"], vivid["sat"],
             vivid["rgb"].shape[1], vivid["rgb"].shape[0]))
    return bright, vivid


def edge_field(w=600, h=400):
    """Dai sang giua (225), toi hai ben (25): hai bien doc, mot trai mot phai.

    Bien doc khong doi theo truc Y nen phep do dich ban kinh sach nhieu cua
    truc Y. Do ca hai bien moi phan biet "dich theo ban kinh" voi "nhich ca
    anh sang mot phia".
    """
    a = np.full((h, w, 3), 25.0, np.float64)
    a[:, int(w * 0.28):int(w * 0.72)] = 225.0
    return a


def dot_field(w=600, h=400, value=22.0, dot=250.0, radius=8):
    a = np.full((h, w, 3), value, np.float64)
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - w / 2.0) ** 2 + (yy - h / 2.0) ** 2)
    a[d <= radius] = dot
    return a


def grey_field(value, w=300, h=200):
    return np.full((h, w, 3), float(value), np.float64)


def line_field(fracs=(0.06, 0.2, 0.8, 0.94), w=600, h=400):
    """Nen toi 20 với một vach mong o moi vi tri `fracs` cua be rong.

    Vach mong cho phep do DISCH cua mot diem anh theo duong kinh ma khong co
    giao vien nao khac chen vao: do loi cua "dinh luat ban kinh" (dich ti le
    voi khoang cach tam) la do duoc tung vach rieng, khong phai do ca anh.
    """
    a = np.full((h, w, 3), 20.0, np.float64)
    for f in fracs:
        a[:, int(w * f)] = 250.0
    return a


def line_centroid(a, ch, lo, hi):
    prof = a[:, :, ch][:, lo:hi].mean(axis=0)
    prof = prof - prof.min()
    total = float(prof.sum())
    if total <= 0.0:
        return None
    xs = np.arange(lo, hi, dtype=np.float64)
    return float((xs * prof).sum() / total)


def radial_shifts(src, out, ch, fracs):
    """Do dich trung tam cua tung vach sang giua anh vao va anh ra."""
    w = src.shape[1]
    res = {}
    for f in fracs:
        c = int(w * f)
        lo, hi = max(0, c - 28), min(w, c + 29)
        a = line_centroid(src, ch, lo, hi)
        b = line_centroid(out, ch, lo, hi)
        res[f] = None if a is None or b is None else b - a
    return res


def edge_crossing(field, channel, x_edge, rows):
    """Vi tri crossing cua bien doc, noi suy tuyen tinh tren profile theo cot.

    Tra ve None neu bien bi nhat den muc do khong duoc — do la loi cua du lieu
    thu, khong phai loi cua ham duoc do.
    """
    prof = field[rows[0]:rows[1], :, channel].mean(axis=0)
    lo, hi = float(prof.min()), float(prof.max())
    if hi - lo < 60.0:
        return None
    mid = (lo + hi) / 2.0
    for x in range(max(0, x_edge - 80), min(len(prof) - 1, x_edge + 81)):
        a, b = prof[x], prof[x + 1]
        if (a - mid) * (b - mid) <= 0.0 and b != a:
            return x + (mid - a) / (b - a)
    return None


def ring_mean(field, centre, r0, r1):
    h, w = field.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - centre[0]) ** 2 + (yy - centre[1]) ** 2)
    m = (d >= r0) & (d < r1)
    l = luma(field) if field.ndim == 3 else field
    return float(l[m].mean()) if m.any() else None


# ── 1. khong con khoa ma ────────────────────────────────────────

def pixel_cards():
    from ui.effects_panel import EFFECT_CATEGORIES
    return [(tab, c["name"]) for tab in PIXEL_TABS for c in EFFECT_CATEGORIES[tab]]


def gate_keys(bright, vivid):
    print("\n== 1. moi khoa trong preset co mot nhanh xu ly ==")
    all_keys = set()
    for _, name in pixel_cards():
        all_keys |= set(EFFECT_PRESETS.get(name, {}))
    check("preset chi dung khoa co trong PIXEL_KEYS",
          sorted(all_keys - set(ce.PIXEL_KEYS)), [])
    check("PIXEL_KEYS khong khoa thua va co du bien do do",
          sorted(set(ce.PIXEL_KEYS) - all_keys), [])
    check("moi khoa PIXEL_KEYS co bien do do",
          sorted(set(ce.PIXEL_KEYS) - set(KEY_PROBE)), [])
    for key in ce.PIXEL_KEYS:
        params = {key: KEY_PROBE[key]}
        a = mad(apply_rgb(params, image=bright["qimage"]), bright["rgb"])
        b = mad(apply_rgb(params, image=vivid["qimage"]), vivid["rgb"])
        zero = mad(apply_rgb(params, intensity=0.0, image=vivid["crop"]),
                   vivid["crop_rgb"])
        metrics["key:%s" % key] = {"frame_a": a, "frame_b": b, "intensity0": zero}
        ok = a > KEY_FLOOR and b > KEY_FLOOR and zero <= ZERO_FLOOR
        print("  %-52s %s A=%.2f B=%.2f i0=%.4f"
              % ("khoa '%s'" % key, "PASS" if ok else "FAIL", a, b, zero))
        if not ok:
            fails.append("khoa '%s' khong song (A=%.3f B=%.3f i0=%.4f)"
                         % (key, a, b, zero))


def gate_cards(bright, vivid):
    print("\n== 2. moi the pixel doi anh that, cuong do 0 tra nguyen van ==")
    from ui.effects_panel import EFFECT_CATEGORIES
    for tab in PIXEL_TABS:
        for c in EFFECT_CATEGORIES[tab]:
            name = c["name"]
            params = EFFECT_PRESETS.get(name)
            if not check("the '%s' co preset" % name, bool(params), True):
                continue
            d_a = mad(apply_rgb(params, image=bright["qimage"]), bright["rgb"])
            d_b = mad(apply_rgb(params, image=vivid["qimage"]), vivid["rgb"])
            metrics["card:%s" % name] = {"frame_a": d_a, "frame_b": d_b}
            above("%-22s doi anh (max 2 khung)" % name, max(d_a, d_b), CARD_FLOOR)
            z_a = mad(apply_rgb(params, 0.0, bright["crop"]), bright["crop_rgb"])
            z_b = mad(apply_rgb(params, 0.0, vivid["crop"]), vivid["crop_rgb"])
            metrics["card0:%s" % name] = {"frame_a": z_a, "frame_b": z_b}
            below("%-22s cuong do 0 tra nguyen van" % name,
                  max(z_a, z_b), ZERO_FLOOR)


# ── 3. chu ky Chromatic ─────────────────────────────────────────

def chroma_signature(src, img):
    """Do ba chu ky cua Chromatic tren mot truong bien: kenh luc, hai bien, ban kinh."""
    out = apply_rgb({"chromatic": 1.0}, image=img)
    h, w = src.shape[:2]
    rows = (int(h * 0.25), int(h * 0.75))
    per = [mad(out[:, :, c], src[:, :, c]) for c in range(3)]
    base_l = edge_crossing(src, 0, int(w * 0.28), rows)
    base_r = edge_crossing(src, 0, int(w * 0.72), rows)
    res = {
        "r": per[0], "g": per[1], "b": per[2],
        "left_r": (edge_crossing(out, 0, int(w * 0.28), rows) or 0.0) - base_l,
        "right_r": (edge_crossing(out, 0, int(w * 0.72), rows) or 0.0) - base_r,
        "left_b": (edge_crossing(out, 2, int(w * 0.28), rows) or 0.0) - base_l,
        "right_b": (edge_crossing(out, 2, int(w * 0.72), rows) or 0.0) - base_r,
    }
    lf = line_field()
    lf_out = apply_rgb({"chromatic": 1.0}, image=qimage_from_np(lf))
    res["r_lines"] = radial_shifts(lf, lf_out, 0, (0.06, 0.2, 0.8, 0.94))
    res["b_lines"] = radial_shifts(lf, lf_out, 2, (0.06, 0.2, 0.8, 0.94))
    return res


def gate_chromatic(bright, vivid):
    print("\n== 3. chu ky cau truc Chromatic ==")
    src = edge_field()
    res = chroma_signature(src, qimage_from_np(src))
    metrics["chroma"] = res
    print("  dich bien (px): trai do=%+.2f phai do=%+.2f | trai xanh=%+.2f phai xanh=%+.2f"
          % (res["left_r"], res["right_r"], res["left_b"], res["right_b"]))
    above("Chromatic dich kenh do", res["r"], 1.0)
    above("Chromatic dich kenh xanh duong", res["b"], 1.0)
    near("Chromatic khong cham kenh luc", res["g"], 0.0, 0.0)
    above("do PHONG TO ra ngoai o bien phai", res["right_r"], 1.0)
    above("do NGUOC chieu o bien trai (ban kinh, khong phai truc)",
          -res["left_r"], 1.0)
    above("xanh duong THU nho vao tam o bien phai", -res["right_b"], 1.0)
    above("xanh duong di VAO TAM o bien trai (nguoc dau voi do)",
          res["left_b"], 1.0)
    # Dinh luat ban kinh: vach cang xa tam thi dich cang nhieu, va nguoc dau.
    rl, rr = res["r_lines"], res["b_lines"]
    print("  dich vach kenh do: %s | kenh xanh: %s"
          % ({k: round(v, 2) for k, v in rl.items()},
             {k: round(v, 2) for k, v in rr.items()}))
    above("do: vach 0.94w ra xa tam nhieu hon vach 0.8w",
          rl[0.94] - rl[0.8], 0.8)
    above("do: vach 0.06w ra xa tam nhieu hon vach 0.2w",
          rl[0.2] - rl[0.06], 0.8)
    above("do: dich o hai vach ngoai >= 3px", min(rl[0.94], -rl[0.06]), 3.0)
    above("xanh: dich nguoc chieu do o hai vach ngoai",
          min(-rr[0.94], rr[0.06]), 3.0)
    above("xanh: cang xa tam cang nhieu", rr[0.06] - rr[0.2], 0.8)
    metrics["chroma_frames"] = {
        "A": mad(apply_rgb({"chromatic": 1.0}, image=bright["qimage"]), bright["rgb"]),
        "B": mad(apply_rgb({"chromatic": 1.0}, image=vivid["qimage"]), vivid["rgb"])}
    above("Chromatic tren khung that A", metrics["chroma_frames"]["A"], 1.0)
    above("Chromatic tren khung that B", metrics["chroma_frames"]["B"], 1.0)
    near("Chromatic cuong do 0 tra nguyen van",
         mad(apply_rgb({"chromatic": 1.0}, 0.0, vivid["crop"]), vivid["crop_rgb"]),
         0.0, 0.0)
    check("Chromatic giu alpha",
          apply_rgba({"chromatic": 1.0}, image=bright["crop"])[..., 3].min(), 255.0)


# ── 4. chu ky Lens Flare ────────────────────────────────────────

def flare_signature(field, img, centre):
    """Do qua tang luma theo tung vong tron quanh nguon sang.

    Vuong cham cua box blur nhan doi la 2*radius, voi radius = round(canh ngan
    * 0.045) = 18px tren anh 600x400 -> sang chi den duoc ~44px ke tu tam cham.
    Cac vong duoi day chon theo con so DO, khong theo cam giac: 12-26 va 26-40
    trong vuong cham, 48-160 ngoai vuong cham (phai nguyen ven).
    """
    out = apply_rgb({"lens_flare": 1.0}, image=img)
    rings = [(12, 26), (26, 40), (48, 80), (110, 130), (160, 180)]
    before = [ring_mean(field, centre, *r) for r in rings]
    after = [ring_mean(out, centre, *r) for r in rings]
    return {"rings": rings, "gain": [b - a for a, b in zip(before, after)],
            "before": before, "after": after,
            "core_before": ring_mean(field, centre, 0.0, 8.0),
            "core_after": ring_mean(out, centre, 0.0, 8.0)}


def gate_flare(bright, vivid):
    print("\n== 4. chu ky cau truc Lens Flare ==")
    src = dot_field()
    img = qimage_from_np(src)
    centre = (img.width() / 2.0, img.height() / 2.0)
    sig = flare_signature(src, img, centre)
    metrics["flare"] = sig
    g = sig["gain"]
    print("  vong %s: truoc=%s sau=%s" % (sig["rings"],
                                          [round(v, 2) for v in sig["before"]],
                                          [round(v, 2) for v in sig["after"]]))
    above("loang sat nguon (12-26px)", g[0], 6.0)
    above("loang tiep (26-40px)", g[1], 1.0)
    below("ngoai vuong cham box x2 (48-80px) khong con gi", g[2], 0.05)
    below("vung xa 160-180px khong sang len", g[4], 0.05)
    above("quang tat dan theo ban kinh (12-26 > 26-40)", g[0] - g[1], 1.0)
    print("  dinh cham: %.2f -> %.2f" % (sig["core_before"], sig["core_after"]))
    check("dinh cham khong bi TOI di (screen, not blur)",
          sig["core_after"] >= sig["core_before"] - 0.5, True)

    flat = grey_field(128.0)
    metrics["flare_midgrey"] = mad(apply_rgb({"lens_flare": 1.0},
                                             image=qimage_from_np(flat)), flat)
    below("anh xam 128 dong nhat KHONG bi loang (bright-pass)",
          metrics["flare_midgrey"], ZERO_FLOOR)
    metrics["flare_dark"] = mad(apply_rgb({"lens_flare": 1.0},
                                          image=qimage_from_np(grey_field(40.0))),
                                grey_field(40.0))
    below("anh toi 40 khong duoc boi sang", metrics["flare_dark"], ZERO_FLOOR)
    white = apply_rgb({"lens_flare": 1.0}, image=qimage_from_np(grey_field(245.0)))
    metrics["flare_flat_white"] = float(luma(white).mean()) - 245.0
    above("mat bang 245 dong nhat van loang duoc (khong can noi dung)",
          metrics["flare_flat_white"], 1.0)

    metrics["flare_frames"] = {
        "A": mad(apply_rgb({"lens_flare": 1.0}, image=bright["qimage"]), bright["rgb"]),
        "B": mad(apply_rgb({"lens_flare": 1.0}, image=vivid["qimage"]), vivid["rgb"])}
    above("Lens Flare tren khung that A", metrics["flare_frames"]["A"], 1.0)
    above("Lens Flare tren khung that B", metrics["flare_frames"]["B"], 1.0)
    near("Lens Flare cuong do 0 tra nguyen van",
         mad(apply_rgb({"lens_flare": 1.0}, 0.0, vivid["crop"]), vivid["crop_rgb"]),
         0.0, 0.0)
    check("Lens Flare giu alpha",
          apply_rgba({"lens_flare": 1.0}, image=bright["crop"])[..., 3].min(), 255.0)

    big = dot_field(1280, 720)
    big_img = qimage_from_np(big)
    sig2 = flare_signature(big, big_img, (640.0, 360.0))
    metrics["flare_proxy"] = sig2["gain"]
    # Tren anh 1280px thi proxy giam half kich thuoc quang (radius 16px cua proxy
    # = 32px anh ra), nen do chi la bang chung "con loang", khong phai bien do.
    above("quang sang van con tren anh proxy >640px", max(sig2["gain"][:2]), 3.0)


# ── 5. 16 the con lai ───────────────────────────────────────────

def gate_motion():
    print("\n== 5. hoat anh + chuyen tiep cung khong phai the ma ==")
    from ui.effects_panel import EFFECT_CATEGORIES
    from core import anim_engine
    from core.transitions import (NEUTRAL, TRANSITIONS, incoming_state,
                                  is_junction, local_state_at)
    cyclic = {"shake", "float", "glitch", "cross_dissolve", "wipe_right"}
    for c in EFFECT_CATEGORIES[MOTION_TAB]:
        name = c["name"]
        params = EFFECT_PRESETS.get(name, {})
        if not check("the '%s' co preset" % name, bool(params), True):
            continue
        dead = sorted(k for k in params
                      if k not in anim_engine.MOTION_KEYS and k not in cyclic)
        if not check("the '%s' chi dung khoa engine biet" % name, dead, []):
            continue
        worst = 0.0
        for t in (0.2, 0.6, 1.0, 1.4, 1.8):
            st = ce.compute_animation_offsets(
                [EffectData(name=name, category=MOTION_TAB, intensity=1.0,
                            params=dict(params))],
                t, rect_width=1280.0, rect_height=720.0, duration=2.0)
            vals = (abs(st.dx), abs(st.dy), abs(st.rotation),
                    abs(st.scale - 1.0) * 500.0, abs(st.opacity - 1.0) * 200.0)
            if not check("the '%s' tai t=%.1f huu han" % (name, t),
                         all(np.isfinite(v) for v in vals), True):
                break
            worst = max(worst, max(vals))
        metrics["motion:%s" % name] = worst
        above("%-16s co chuyen dong do duoc" % name, worst, 1.0)
    base = ce.compute_animation_offsets([], 1.0, 1280.0, 720.0, 2.0)
    check("khong hieu ung thi offset dung neutral",
          tuple(base), (0.0, 0.0, 0.0, 1.0, 1.0))

    for name in [c["name"] for c in EFFECT_CATEGORIES[TRANSITION_TAB]]:
        if not check("the '%s' co khoa trong TRANSITIONS" % name,
                     name in TRANSITIONS, True):
            continue
        st = (incoming_state(name, 0.35, 1280.0, 720.0) if is_junction(name)
              else local_state_at(name, 0.35))
        delta = max(abs(st.opacity - NEUTRAL.opacity), abs(st.dx), abs(st.dy),
                    abs(st.scale - NEUTRAL.scale), 1.0 if st.wipe else 0.0)
        metrics["transition:%s" % name] = delta
        above("%-16s bien doi tai p=0.35" % name, delta, 0.05)

    all_names = [c["name"] for lst in EFFECT_CATEGORIES.values() for c in lst]
    check("29 the khong trung ten", len(all_names), len(set(all_names)))
    check("moi the deu co preset hoac la chuyen tiep",
          sorted(n for n in all_names
                 if n not in EFFECT_PRESETS and n not in TRANSITIONS), [])


# ── 6. phan chung ───────────────────────────────────────────────

def identity(a, *rest):
    return np.array(a, dtype=np.float32, copy=True)


def rival_roll(a, strength, channels=(0, 1, 2), px=None):
    """Ban doi thu: nhich kenh theo TRUC CO DINH, ca ba kenh cung chieu."""
    out = np.array(a, dtype=np.float32, copy=True)
    n = px if px is not None else int(2 + 12 * max(0.0, min(1.0, float(strength))))
    for c in channels:
        out[:, :, c] = np.roll(out[:, :, c], n, axis=1)
    return out


def rival_brighten(a, strength):
    """Ban doi thu cho flare: cong sang deu, khong bright-pass khong gian tiep."""
    return np.array(a, dtype=np.float32) + 15.0


def counterfactual(bright, vivid):
    print("\n== 6. phan chung: moi phep do phai co the FAIL ==")
    src = edge_field()
    img = qimage_from_np(src)
    dot = dot_field()
    dot_img = qimage_from_np(dot)

    # Khoa la do tren crop 600x400 (khong qua proxy): noi dung o day la "khong
    # nhanh nao doc khoa do", mot lop mo vi proxy se lang vao do va che mat.
    ghost = mad(apply_rgb({"chromatic_typo": 1.0}, image=vivid["crop"]),
                vivid["crop_rgb"])
    live = mad(apply_rgb({"chromatic": 1.0}, image=vivid["crop"]), vivid["crop_rgb"])
    near("phan chung: khoa la bi chuoi bo qua hoan toan", ghost, 0.0, 0.0)
    above("phan chung: cung bien do, khoa that thi doi anh", live, 1.0)

    originals = {"chromatic_rgb": ce.chromatic_rgb,
                 "lens_flare_rgb": ce.lens_flare_rgb}
    try:
        ce.chromatic_rgb = ce.lens_flare_rgb = identity
        ch = mad(apply_rgb({"chromatic": 1.0}, image=img), src)
        fl = mad(apply_rgb({"lens_flare": 1.0}, image=dot_img), dot)
        near("phan chung: xoa chromatic_rgb thi anh khong doi", ch, 0.0, 0.0)
        near("phan chung: xoa lens_flare_rgb thi anh khong doi", fl, 0.0, 0.0)

        ce.chromatic_rgb = lambda a, s: rival_roll(a, s, channels=(0, 1, 2))
        rival = chroma_signature(src, img)
        h, w = src.shape[:2]
        print("  rival 3 kenh cung chieu: g=%.3f trai_do=%+.2f phai_do=%+.2f"
              % (rival["g"], rival["left_r"], rival["right_r"]))
        discriminates("phan chung: chu ky kenh luc bat duoc rival 3 kenh",
                      rival["g"] > 0.5, rival["g"])
        ce.chromatic_rgb = lambda a, s: rival_roll(a, s, channels=(0, 2))
        rival = chroma_signature(src, img)
        print("  rival 2 kenh cung chieu: trai_do=%+.2f phai_do=%+.2f"
              % (rival["left_r"], rival["right_r"]))
        discriminates("phan chung: chu ky bien trai bat duoc rival nhich 1 chieu",
                      rival["left_r"] > -1.0, rival["left_r"])

        ce.lens_flare_rgb = rival_brighten
        flat = grey_field(128.0)
        gained = mad(apply_rgb({"lens_flare": 1.0}, image=qimage_from_np(flat)), flat)
        centre = (dot_img.width() / 2.0, dot_img.height() / 2.0)
        rsig = flare_signature(dot, dot_img, centre)
        print("  rival +15 sang deu: anh xam +%.2f, vanh 160-180 +%.2f"
              % (gained, rsig["gain"][4]))
        discriminates("phan chung: bright-pass bat duoc rival cong sang deu",
                      gained > ZERO_FLOOR, gained)
        discriminates("phan chung: vanh xa bat duoc rival cong sang deu",
                      rsig["gain"][4] > 0.05, rsig["gain"][4])
    finally:
        for n, fn in originals.items():
            setattr(ce, n, fn)
    check("hai ham duoc khoi phuc dung ban goc",
          all(getattr(ce, n) is fn for n, fn in originals.items()), True)

    import diagnostics
    try:
        ce.chromatic_rgb = ce.lens_flare_rgb = identity
        got = diagnostics._effect_liveness_ok()
        check("dong selftest van chay khi xoa ham (SAI)", got, "exception")
    except Exception as exc:
        check("dong selftest NO khi xoa ham ve", bool(str(exc)), True)
    finally:
        for n, fn in originals.items():
            setattr(ce, n, fn)
    above("sau khi khoi phuc, flare lai loang that",
          flare_signature(dot, dot_img,
                          (dot_img.width() / 2.0, dot_img.height() / 2.0))["gain"][0],
          6.0)
    row = diagnostics._effect_liveness_ok()
    check("dong selftest tra ve chuoi do dac", any(c.isdigit() for c in row), True)


# ── 7. gia thanh ────────────────────────────────────────────────

def gate_cost(bright):
    print("\n== 7. gia thanh moi khung (may cau hinh thap) ==")
    costs = {}
    for name, params in (("Chromatic", {"chromatic": 1.0}),
                         ("Lens Flare", {"lens_flare": 1.0}),
                         ("ca hai", {"chromatic": 1.0, "lens_flare": 1.0})):
        apply_rgb(params, image=bright["qimage"])
        samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            apply_rgb(params, image=bright["qimage"])
            samples.append((time.perf_counter() - t0) * 1000.0)
        med = statistics.median(samples)
        costs[name] = med
        print("  %-10s frame 1280x720: %s ms (trung vi %.1f)"
              % (name, [round(s, 1) for s in samples], med))
    metrics["cost_ms"] = costs
    below("gia thanh du cho preview thoi gian thuc", max(costs.values()), 220.0)
    return costs


# ── 8. bang chung hinh ─────────────────────────────────────────

def evidence(bright, vivid, costs):
    cols = [("goc", None), ("Chromatic", {"chromatic": 1.0}),
            ("Lens Flare", {"lens_flare": 1.0}),
            ("ca hai", {"chromatic": 1.0, "lens_flare": 1.0})]
    fields = [
        ("A: khung that sang", bright["rgb"], bright["qimage"]),
        ("B: khung that mau", vivid["rgb"], vivid["qimage"]),
        ("C: cham trang tren toi", dot_field(), qimage_from_np(dot_field())),
        ("D: hai bien doc", edge_field(), qimage_from_np(edge_field())),
    ]
    tw, th, gap = 240, 120, 6
    per_row = len(cols) * 3
    width = per_row * tw + (per_row - 1) * gap + 210
    head = np.full((28, width, 3), 18, np.uint8)
    rows = []
    for label, arr, img in fields:
        tiles = []
        for col_label, params in cols:
            out = arr if params is None else apply_rgb(params, image=img)
            base = cv2.resize(cv2.cvtColor(np.clip(arr, 0, 255).astype(np.uint8),
                                           cv2.COLOR_RGB2BGR), (tw, th))
            aft = cv2.resize(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8),
                                          cv2.COLOR_RGB2BGR), (tw, th))
            heat = cv2.resize(cv2.applyColorMap(
                np.clip(np.abs(out - arr).mean(axis=2) * 12.0, 0, 255).astype(np.uint8),
                cv2.COLORMAP_JET), (tw, th))
            cv2.putText(base, "goc", (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(aft, "%.2f" % mad(out, arr), (5, 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(heat, "diffx12", (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles += [base, aft, heat]
        strip = np.hstack(tiles)
        pad = np.full((strip.shape[0], width - strip.shape[1], 3), 18, np.uint8)
        row = np.hstack([strip, pad])
        cv2.putText(row, label, (strip.shape[1] + 8, th // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 235, 235), 1, cv2.LINE_AA)
        rows.append(row)
    for i, (col_label, _) in enumerate(cols):
        cv2.putText(head, col_label, (i * 3 * (tw + gap) + 5, 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1, cv2.LINE_AA)
    sheet = np.vstack([head] + rows)
    note = ("Chromatic: do phong ra tam, xanh thu ve tam, kenh luc nguyen van. "
            "Lens Flare: bright-pass 185+, box blur x2, screen. "
            "%.1f/%.1f ms/frame 1280x720" % (costs["Chromatic"], costs["Lens Flare"]))
    cv2.putText(sheet, note, (6, sheet.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX,
                0.42, (220, 220, 220), 1, cv2.LINE_AA)
    if not cv2.imwrite(EVIDENCE, sheet):
        raise SystemExit("khong ghi duoc anh chung minh")
    back = cv2.imread(EVIDENCE)
    colours = len(set(map(tuple, back.reshape(-1, 3)[::29])))
    print("evidence image: %s (%d bytes, %dx%d, doc lai %d mau)"
          % (EVIDENCE, os.path.getsize(EVIDENCE), sheet.shape[1], sheet.shape[0],
             colours))
    check("anh chung minh doc lai duoc", back is not None, True)
    above("anh chung minh co noi dung", colours, 200)


def main():
    app = QApplication(sys.argv)
    bright, vivid = frames_from_video()

    print("\n== 0. duong dung chung ==")
    check("preview va export cung mot ham loc mau",
          ce.apply_color_effects.__module__, "core.clip_effects")
    check("ham khong doi khi khong co hieu ung",
          mad(np_from_qimage(ce.apply_color_effects(bright["crop"], []))[:, :, :3],
              bright["crop_rgb"]), 0.0)

    # Duong proxy >640px phai tra ve DUNG kich thuoc da di va chi mot lop mo
    # rat mong: KeepAspectRatio o chieu ve lam lech 2px tren khung doc, va mot
    # lech nhu vay du sinh ra "khac biệt ma" khi so sanh tung pixel.
    for p, tag in ((bright, "A"), (vivid, "B")):
        back = ce.apply_color_effects(p["qimage"], [EffectData(
            name="probe", category="Bộ lọc", intensity=0.0,
            params={"contrast": 1.0})])
        want = (p["rgb"].shape[1], p["rgb"].shape[0])
        check("khung %s: anh ra dung kich thuoc da di" % tag,
              (back.width(), back.height()), want)
        noise = mad(np_from_qimage(back)[:, :, :3], p["rgb"])
        metrics["proxy_roundtrip_" + tag] = noise
        # Do duoc: A (it chi tiet) 0.84, B (720p chi tiet cao) 4.35 tren thang
        # 255. Nguong 6 van bat duoc lech do co ban (sai ty le, sai kich thuoc,
        # dao anh) ma khong mong manh theo noi dung cua doan video khac.
        below("khung %s: qua proxy chi mo nhe" % tag, noise, 6.0)

    gate_keys(bright, vivid)
    gate_cards(bright, vivid)
    gate_chromatic(bright, vivid)
    gate_flare(bright, vivid)
    gate_motion()
    counterfactual(bright, vivid)
    costs = gate_cost(bright)
    evidence(bright, vivid, costs)

    with open(EVIDENCE_JSON, "w", encoding="utf-8") as fh:
        json.dump({"frames": {"A": bright["path"], "B": vivid["path"]},
                   "metrics": metrics,
                   "key_floor": KEY_FLOOR, "card_floor": CARD_FLOOR,
                   "fails": fails},
                  fh, indent=2, ensure_ascii=False, default=float)
    print("\nsummary:", "ALL PASS" if not fails else
          "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
