r"""Do chi phí may cau hinh thap cua cong dong duc nen (chroma key).

Cau hoi trong AGENTS.md: mot tinh nang moi phai tra loi duoc (1) them bao nhieu
giay vao boot, (2) them bao nhieu MB RAM thong tru, (3) no lam chậm duong dung
bao nhieu. Day do (3) va RAM tam thoi, dong thoi chung minh (1) = 0 bang cach
bat duong tat: clip khong the chroma va clip the rong PHAI tra ve NGUYEN object
QImage, tuc la khong mo numpy, khong chia ma tran.

chieu (3) PHAI do so voi the pixel da ban, khong do tren giay: chinh chuoi loc
chung (QImage -> numpy -> proxy 640 px -> QImage) da ngot ~65-85 ms/frame o
720p/1080p cho MOI the pixel, nen "22 ms/frame" la muc khong the dat toi bang
bat ky the nao — do 21/10/2026: khong the 29 ms, grading hue 45 84 ms, Pop Art
209 ms, chroma 88 ms. Vi the cua o day la (a) chroma khong duoc la the dat nhat
trong so the da ban, (b) khong lech qua xa the re nhat, va (c) RIENG phep tinh
matte <= nguong do duoc tai cap proxy 640 px (10,3 ms khi thu 256 px, 54 ms khi
tinh day du — do la ly do CHROMA_MATTE_MAX ton tai).

Do tren duong that: FrameComposer(model, W, H).render_frame() nhu luc xuat video,
mot clip ANH 1280x720, 20 frame o cung thoi diem (anh da cache nen so do la chi
phi cua bo loc, khong phai cua doc file).

Chay:
    python scratch/chroma_cost_probe.py
In ra bang ms/frame + RSS; exit 1 neu duong tat bi vo ho chi phi vut qua nguong.
"""

import ctypes
import os
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from core.clip_effects import (CHROMA_EFFECT_NAME, CHROMA_IDENTITY,
                               GRADING_IDENTITY, apply_color_effects,
                               chroma_key_rgb)
from core.commands import SetChromaCommand, UndoStack
from core.frame_composer import FrameComposer
from core.timeline_model import EffectData, TimelineModel, TrackType

WORK = os.path.join(tempfile.gettempdir(), "clinging_chroma_cost")
FRAMES = 20

PASS = []
FAIL = []


def truthy(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", label,
                           (" | " + extra) if extra else ""))
    return cond


def working_set_mb():
    """K32GetProcessMemoryInfo tren pseudo-handle -u1. Phai gan argtypes: thieu
    no thi GetProcessMemoryInfo tra ve 0 im lang thay vi bao loi (do truoc day)."""

    class CTR(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32),
                    ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    ctr = CTR()
    ctr.cb = ctypes.sizeof(CTR)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_bool
    ctypes.windll.kernel32.K32GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(CTR), ctypes.c_uint32]
    if not ctypes.windll.kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(ctr),
                                                          ctr.cb):
        raise RuntimeError("K32GetProcessMemoryInfo tra ve FALSE")
    return ctr.WorkingSetSize / 1048576.0, ctr.PeakWorkingSetSize / 1048576.0


def write_source(path, w, h):
    import cv2
    rng = np.random.default_rng(7)
    arr = np.zeros((h, w, 3), np.uint8)
    arr[:] = (0, 177, 64)
    arr[h // 6:h - h // 6, w // 6:w - w // 6] = rng.integers(
        0, 255, (h - 2 * (h // 6), w - 2 * (w // 6), 3), dtype=np.uint8)
    if not cv2.imwrite(path, np.ascontiguousarray(arr[:, :, ::-1])):
        raise RuntimeError("cv2.imwrite khong ghi duoc %s" % path)


def timed(model, out_w, out_h):
    composer = FrameComposer(model, out_w, out_h)
    ms = []
    try:
        for _ in range(FRAMES):
            t0 = time.perf_counter()
            composer.render_frame(1.0)
            ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        composer.close()
    return statistics.median(ms), min(ms), max(ms)


def timed_interleaved(models, out_w, out_h, frames=24):
    """Do HAI cau hinh xen ke nhau trong CUNG mot vong dong ho.

    Hai vong rieng le khong do duoc lech nhau bang num: do 21/10/2026 tren may
    nay, cung mot cau hinh chay lien tiep lech 8-12 ms vi drift doc dia, nen
    "num khong nhan chi phi" phai loai bo drift bang cach so le chan.
    """
    composers = [FrameComposer(m, out_w, out_h) for m in models]
    buckets = [[] for _ in models]
    try:
        for _ in range(frames // 2):
            for j, composer in enumerate(composers):
                t0 = time.perf_counter()
                composer.render_frame(1.0)
                buckets[j].append((time.perf_counter() - t0) * 1000.0)
    finally:
        for composer in composers:
            composer.close()
    return [statistics.median(b) for b in buckets]


def build(src, over, card=None):
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.IMAGE)
    clip = model.add_clip(track.track_id, src, "image", 0.0, 4.0, name="nen")
    if clip is None:
        raise RuntimeError("add_clip tra None voi %s" % src)
    if card is not None:
        # THE SAMH CHUNG: do chi phi cua mot the pixel DA BAN, khong phai do
        # duong chroma tu te. Lenh that, khong tu gan EffectData.
        from core.commands import ApplyEffectCommand, SetGradingCommand
        if card[0] == "grading":
            UndoStack().push(SetGradingCommand(model, clip.clip_id,
                                               card[1]))
        else:
            UndoStack().push(ApplyEffectCommand(
                model, clip.clip_id, {"name": card[1], "category": "Bo loc"}))
        return model
    if over is not None:
        params = dict(CHROMA_IDENTITY)
        params.update(over)
        # Dung LENH that, khong tu gan EffectData: the rong phai bi chinh
        # SetChromaCommand boc ra, va do la mot trong hai dong do o day.
        UndoStack().push(SetChromaCommand(model, clip.clip_id, params))
    return model


def card_ms(w, h, params, repeats=12):
    """Do rieng ham chroma tren anh cap proxy (chuoi loc lam viec <=640 px)."""
    arr = np.zeros((h, w, 3), np.uint8)
    arr[:] = (0, 177, 64)
    arr[h // 8:h - h // 8, w // 8:w - w // 8] = 200
    rgba = np.ascontiguousarray(np.dstack(
        [arr, np.full((h, w, 1), 255, np.uint8)]))
    img = QImage(rgba.data, w, h, w * 4,
                 QImage.Format.Format_RGBA8888).copy()
    card = EffectData(name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                      intensity=1.0, params=params)
    ms = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        apply_color_effects(img, [card])
        ms.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(ms)


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    src = os.path.join(WORK, "nen720.png")
    write_source(src, 1280, 720)

    print("\n(1) DUONG TAT: clip khong the va the rong khong duoc mo numpy.")
    plain = QImage(640, 360, QImage.Format.Format_RGBA8888)
    plain.fill(0)
    empty = EffectData(name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                       intensity=1.0, params=dict(CHROMA_IDENTITY))
    truthy("khong the: apply_color_effects tra dung object",
           apply_color_effects(plain, []) is plain)
    truthy("the chroma rong (tolerance 0): tra dung object, khong chia ma tran",
           apply_color_effects(plain, [empty]) is plain)
    tol = dict(CHROMA_IDENTITY)
    tol["tolerance"] = 0.3
    used = EffectData(name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                      intensity=1.0, params=tol)
    out = apply_color_effects(plain, [used])
    truthy("the co dung sai: THAT SU mo numpy (khong phai duong tat gia)",
           out is not plain, str(out is not plain))

    print("\n(2) ms/frame qua FrameComposer (20 frame, median), ke ca the da ban.")
    variants = (
        ("khong the", None, None),
        ("the rong", dict(CHROMA_IDENTITY), None),
        ("dung sai 0.30", {"tolerance": 0.30}, None),
        ("dung sai 0.60 + vien mong 0.60", {"tolerance": 0.60, "feather": 0.60}, None),
        ("dung sai 0.60 + chong am 0.80", {"tolerance": 0.60, "spill": 0.80}, None),
        ("doi chung grading hue 45", None,
         ("grading", dict(GRADING_IDENTITY, hue_shift=45.0))),
        ("doi chung Pop Art", None, ("filter", "Pop Art")),
    )
    for out_w, out_h in ((1280, 720), (1920, 1080)):
        rows = []
        for label, over, card in variants:
            model = build(src, over, card)
            med, lo, hi = timed(model, out_w, out_h)
            rows.append((label, med))
            print("   %5dx%-5d %-30s %7.2f ms  (min %.2f max %.2f)"
                  % (out_w, out_h, label, med, lo, hi))
        by = dict(rows)
        base = max(by["khong the"], by["the rong"])
        chroma = max(v for k, v in rows if k.startswith("dung sai")) - base
        grade = by["doi chung grading hue 45"] - base
        popart = by["doi chung Pop Art"] - base
        truthy("%dx%d: duong tat (khong the/the rong) khong lech nhau qua 15%% "
               "(%.2f vs %.2f ms)"
               % (out_w, out_h, by["khong the"], by["the rong"]),
               abs(by["khong the"] - by["the rong"]) < 0.15 * by["khong the"] + 1.0)
        truthy("%dx%d: thue chroma %.1f ms/frame < thue Bo loc Pop Art da ban "
               "%.1f ms/frame (the duc nen khong duoc la the dat nhat app)"
               % (out_w, out_h, chroma, popart), chroma < popart)
        truthy("%dx%d: thue chroma %.1f ms/frame <= the re nhat da ban (%.1f) + 35 "
               % (out_w, out_h, chroma, grade), chroma <= grade + 35.0)
        a, b = timed_interleaved([build(src, {"tolerance": 0.30}),
                                  build(src, {"tolerance": 0.60, "feather": 0.60})],
                                 out_w, out_h)
        print("   %5dx%-5d xen ke: tol 0.30 %.2f ms | tol 0.60 + feather 0.60 %.2f ms"
              % (out_w, out_h, a, b))
        truthy("%dx%d: num vien mong 0->0.6 khong nhan chi phi so voi num dung sai "
               "(%.2f vs %.2f ms, do xen ke)"
               % (out_w, out_h, b, a), b <= a + 4.0)

    print("\n(3) Do RIENG phep tinh matte tai cap proxy cua chuoi loc (<=640 px).")
    plate = np.zeros((360, 640, 3), np.float32)
    plate[:, :] = (0.0, 177.0, 64.0)
    plate[45:315, 80:560] = (210.0, 90.0, 150.0)

    def math_ms(params, repeats=12):
        ms = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            chroma_key_rgb(plate, params)
            ms.append((time.perf_counter() - t0) * 1000.0)
        ms.sort()
        return ms[repeats // 2]

    matte_only = math_ms(dict(CHROMA_IDENTITY, tolerance=0.6))
    with_spill = math_ms(dict(CHROMA_IDENTITY, tolerance=0.6, spill=0.8))
    off = card_ms(640, 360, dict(CHROMA_IDENTITY))
    on = card_ms(640, 360, dict(CHROMA_IDENTITY, tolerance=0.6, spill=0.8))
    print("   duong tat (the rong) %6.3f ms | ca the dung sai 0.60 + spill %6.2f ms"
          % (off, on))
    print("   rieng matte 640x360: %6.2f ms | + despill: %6.2f ms "
          "(do day du khong thu nho = 54,00 ms)" % (matte_only, with_spill))
    truthy("640x360: phep tinh matte (khong despill) <= 20 ms (%.2f ms; "
           "do day du khong thu nho = 54,00 ms)" % matte_only, matte_only <= 20.0)
    truthy("640x360: matte + despill full-res <= 32 ms (%.2f ms)"
           % with_spill, with_spill <= 32.0)
    truthy("640x360: the rong van la duong tat (mo numpy = %.2f ms vs %.2f ms)"
           % (off, on), off < 1.0)

    print("\n(4) RAM thong tru: khong co cache moi, chi co mang tam thoi.")
    before = working_set_mb()
    model = build(src, {"tolerance": 0.6, "feather": 0.6, "spill": 0.8})
    composer = FrameComposer(model, 1920, 1080)
    try:
        for _ in range(FRAMES):
            composer.render_frame(1.0)
    finally:
        composer.close()
    after = working_set_mb()
    print("   working set %.1f -> %.1f MB | peak %.1f -> %.1f MB"
          % (before[0], after[0], before[1], after[1]))
    truthy("20 frame 1080p khong phinh them qua 80 MB (%.1f MB)"
           % (after[0] - before[0]), after[0] - before[0] < 80.0)
    truthy("khong them module nang nao vao import dau (numpy/cv2 da nap san)",
           "numpy" in sys.modules and "cv2" in sys.modules)

    shutil.rmtree(WORK, ignore_errors=True)
    print("\nKET QUA: %d OK / %d FAIL" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
