"""Do BASELINE hieu nang tren may cau hinh THAT truoc khi toi uu.

May nay that: i7-2720QM (4C/8T, 2011), 12 GB RAM, Quadro 1000M + HD3000,
media nam tren HDD 5400 rpm. Khong mo phong — moi con so doc tu machine nay.

Tat ca cac phep deu di qua duong cua PRODUCTION (media_frame, FrameComposer,
RenderWorker), khong co ham phong. Ket qua in ra bang va ghi JSON
scratch/perf_baseline.json de lan sau so sinh.

  M0  RenderWorker tron ven (4 giay @24fps 1280x720) — con so dau tien nguoi
      dung thay: may giay moi xong 1 file.
  M1  3 kieu doc frame: open+seek+release moi frame (hien tai) vs
      seek tren 1 capture mo san vs doc thuan tiep — va PARITY: kieu doc
      nhanh co tra ve DUNG pixel nhu kieu cu khong.
  M2  Canvas 1920x1080 roi scale ve 720p (hien tai) vs render thang 720p,
      do ca thoi lan lech pixel.
  M3  x264 preset medium/fast/veryfast tren CUNG mot luong frame — bao
      nhieu thoi gian la do encoder.
  M4  Startup: thoi gian import tung module nang.
  M5  RSS khi render.
  M6  Duong tai lai project: thumbnail 12 frame + waveform cho 1 clip.

Chay: PYTHONIOENCODING=utf-8 python -u scratch/perf_baseline.py
"""

import json
import os
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
TMP = os.path.join(ROOT, "scratch", "perf_tmp")
JSON_OUT = os.path.join(ROOT, "scratch", "perf_baseline.json")

OUT_W, OUT_H, FPS, DUR = 1280, 720, 24, 4.0
N_DECODE = 24
START_T = 2.0

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

RESULTS = {}


def row(metric, value, unit="", note=""):
    RESULTS[metric] = {"value": value, "unit": unit, "note": note}
    print("%-52s %10s %-6s %s" % (metric, ("%.1f" % value) if isinstance(value, float)
                                  else value, unit, note))


def run(cmd, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit("lenh that bai %r\n%s"
                         % (cmd[:5], proc.stderr.decode("utf-8", "replace")[-900:]))
    return proc


def build_model(cards=(), dur=DUR):
    from core.commands import ApplyEffectCommand, UndoStack
    from core.timeline_model import TimelineModel, TrackType
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.VIDEO, "Main")
    clip = model.add_clip(track.track_id, VIDEO, "video", 0.0, dur, "mau")
    stack = UndoStack()
    for card in cards:
        stack.push(ApplyEffectCommand(model, clip.clip_id, card))
    return model


# ── M0: ca dây xuat qua RenderWorker that ───────────────────────

def m0_full_export(app):
    from ui.export_dialog import RenderWorker
    print("\n== M0: RenderWorker tron ven %.0fs @%dfps %dx%d ==" % (DUR, FPS, OUT_W, OUT_H))
    out = os.path.join(TMP, "m0.mp4")
    for extra in (out, out + "_audio.mp3"):
        if os.path.exists(extra):
            os.remove(extra)
    worker = RenderWorker(build_model(), out, OUT_W, OUT_H, FPS, "16:9", True)
    errors, done = [], []
    worker.errorOccurred.connect(errors.append)
    worker.finished_ok.connect(done.append)
    t0 = time.perf_counter()
    worker.run()
    dt = time.perf_counter() - t0
    frames = int(DUR * FPS)
    if errors:
        raise SystemExit("M0 loi xuat: %s" % errors)
    row("M0.xuat_tron_ven_giay", round(dt, 1), "s", "%d frame -> %.2f s/frame" % (frames, dt / frames))
    row("M0.giay_moi_frame", round(dt / frames, 3), "s", "baseline dau ra cua may nay")
    row("M0.kich_thuoc_file", os.path.getsize(out) / 1024.0, "KB")


# ── M1: ba kieu doc frame + parity ──────────────────────────────

def m1_decode_strategies():
    import cv2
    from core.media_frame import extract_frame_image
    print("\n== M1: doc frame — open/seek/release vs seek san vs thuan tiep ==")
    times = [START_T + i / float(FPS) for i in range(N_DECODE)]

    def current():
        return [extract_frame_image(VIDEO, t) for t in times]

    def seek_persistent():
        cap = cv2.VideoCapture(VIDEO)
        try:
            out = []
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                out.append(qimage_from_bgr(frame) if ok else None)
            return out
        finally:
            cap.release()

    # Doc thuan tiep: chi seek MOT LAN, sau do cap.read() lien tuc. Nguon 60fps
    # xuat 24fps nen phai "grab" bo qua frame trung gian thay vi seek.
    def forward():
        cap = cv2.VideoCapture(VIDEO)
        try:
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
            cap.set(cv2.CAP_PROP_POS_MSEC, times[0] * 1000.0)
            out = []
            for t in times:
                want = int(round(t * src_fps))
                while int(cap.get(cv2.CAP_PROP_POS_FRAMES)) < want:
                    if not cap.grab():
                        break
                ok, frame = cap.read()
                out.append(qimage_from_bgr(frame) if ok else None)
            return out
        finally:
            cap.release()

    def timed(fn):
        gc_off()
        t0 = time.perf_counter()
        frames = fn()
        dt = time.perf_counter() - t0
        return frames, dt / len(frames) * 1000.0

    for label, fn in (("hien_tai_open_seek_release", current),
                      ("seek_tren_capture_mo_san", seek_persistent),
                      ("thuan_tiep_khong_seek", forward)):
        frames, ms = timed(fn)
        got = [f for f in frames if f is not None]
        row("M1.%s_ms_moi_frame" % label, round(ms, 1), "ms",
            "%d/%d frame doc duoc" % (len(got), len(frames)))
        RESULTS["M1.%s.frames" % label] = [qimage_stats(f) for f in got]

    base = RESULTS["M1.hien_tai_open_seek_release.frames"]
    for label in ("seek_tren_capture_mo_san", "thuan_tiep_khong_seek"):
        alt = RESULTS["M1.%s.frames" % label]
        n = min(len(base), len(alt))
        same = sum(1 for i in range(n) if base[i] == alt[i])
        row("M1.parity_%s" % label, "%d/%d" % (same, n), "frame giong het",
            "so sanh hash pixel voi kieu hien tai")


def gc_off():
    import gc
    gc.collect()


def qimage_stats(img):
    """Hash noi dung + kich thuoc cua QImage — dung so sanh parity frame."""
    import hashlib
    from PySide6.QtGui import QImage
    if img is None or img.isNull():
        return None
    conv = img.convertToFormat(QImage.Format.Format_ARGB32)
    return {"w": conv.width(), "h": conv.height(),
            "sha": hashlib.sha256(qimage_bytes(conv)).hexdigest()[:16]}


def qimage_from_bgr(frame):
    import cv2
    from PySide6.QtGui import QImage
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, c = rgb.shape
    return QImage(rgb.data, w, h, c * w, QImage.Format_RGB888).copy()


# ── M2: canvas 1080p roi scale vs render thang bang output ──────

def m2_canvas_size(app):
    from core import canvas_utils
    from core.frame_composer import FrameComposer
    print("\n== M2: canvas 1920x1080 -> scale 720p  vs  canvas 720p thang ==")
    times = [START_T + i / float(FPS) for i in range(8)]
    for label, canvas in (("canvas_1080p_scale", (1920, 1080)),
                          ("canvas_bang_output", (OUT_W, OUT_H))):
        orig = dict(canvas_utils.ASPECT_RATIOS)
        canvas_utils.ASPECT_RATIOS["16:9"] = canvas
        try:
            composer = FrameComposer(build_model(), OUT_W, OUT_H)
            t0 = time.perf_counter()
            frames = [composer.render_frame(t) for t in times]
            dt = (time.perf_counter() - t0) / len(frames) * 1000.0
            composer.close()
        finally:
            canvas_utils.ASPECT_RATIOS.clear()
            canvas_utils.ASPECT_RATIOS.update(orig)
        row("M2.%s_ms_moi_frame" % label, round(dt, 1), "ms",
            "canvas %dx%d -> output %dx%d" % (canvas[0], canvas[1], OUT_W, OUT_H))
        RESULTS["M2.%s.hashes" % label] = [qimage_stats(f) for f in frames]
    a = RESULTS["M2.canvas_1080p_scale.hashes"]
    b = RESULTS["M2.canvas_bang_output.hashes"]
    same = sum(1 for i in range(min(len(a), len(b))) if a[i] == b[i])
    row("M2.parity_frame_giong_het", "%d/%d" % (same, len(a)), "frame",
        "hash ARGB32; khac nhau = do net khi scale, phai ngam mat")


# ── M3: x264 preset tren cung mot luong frame ───────────────────

def m3_encoder_presets(app):
    from core import canvas_utils
    from core.frame_composer import FrameComposer
    print("\n== M3: x264 preset — bao nhieu thoi gian la do encoder ==")
    orig = dict(canvas_utils.ASPECT_RATIOS)
    canvas_utils.ASPECT_RATIOS["16:9"] = (OUT_W, OUT_H)
    try:
        composer = FrameComposer(build_model(), OUT_W, OUT_H)
        frames = []
        for i in range(48):
            img = composer.render_frame(START_T + i / float(FPS))
            frames.append(img)
        composer.close()
    finally:
        canvas_utils.ASPECT_RATIOS.clear()
        canvas_utils.ASPECT_RATIOS.update(orig)
    payload = [frame_to_rgba(img) for img in frames]
    total_bytes = sum(len(p) for p in payload)
    row("M3.frame_rgba_da_render", len(payload), "frame",
        "%.0f MB tho day vong ffmpeg" % (total_bytes / 2**20))
    for preset in ("medium", "fast", "veryfast", "faster"):
        out = os.path.join(TMP, "m3_%s.mp4" % preset)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
               "-pix_fmt", "rgba", "-s", "%dx%d" % (OUT_W, OUT_H), "-r", str(FPS),
               "-i", "pipe:0", "-c:v", "libx264", "-preset", preset, "-crf", "18",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        t0 = time.perf_counter()
        for blob in payload:
            proc.stdin.write(blob)
        proc.stdin.close()
        proc.wait()
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            raise SystemExit("M3 ffmpeg loi: %s" % proc.stderr.decode("utf-8", "replace")[-500:])
        row("M3.%s_encode_giay" % preset, round(dt, 2), "s",
            "%.0f frame -> %.3f s/frame, file %.0f KB"
            % (len(payload), dt / len(payload), os.path.getsize(out) / 1024.0))


def frame_to_rgba(img):
    from PySide6.QtGui import QImage
    conv = img if img.format() == QImage.Format.Format_RGBA8888 \
        else img.convertToFormat(QImage.Format.Format_RGBA8888)
    return qimage_bytes(conv)


def qimage_bytes(img):
    bits = img.constBits()
    try:
        return bits.tobytes()
    except AttributeError:
        return bytes(bits)


# ── M4: startup ─────────────────────────────────────────────────

def m4_startup():
    print("\n== M4: startup — thoi gian import tung module nang ==")
    for mod in ("numpy", "cv2", "PySide6.QtWidgets", "PySide6.QtMultimedia",
                "qtawesome", "core.media_extractor", "ui.main_window"):
        code = ("import sys, time;"
                "t0=time.perf_counter();import %s;"
                "print('%%.3f' %% (time.perf_counter()-t0))" % mod)
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              cwd=ROOT, timeout=180)
        secs = proc.stdout.decode().strip().splitlines()
        row("M4.import_%s" % mod, float(secs[-1]) if secs else -1.0, "s",
            "tu mot tiến trình mới" if not proc.stderr else
            proc.stderr.decode("utf-8", "replace")[-60:].strip())


# ── M5: RSS ─────────────────────────────────────────────────────

def m5_memory():
    print("\n== M5: bo nho ==")
    try:
        import psutil
    except ImportError:
        row("M5.psutil", "khong co", "", "bo qua")
        return
    p = psutil.Process()
    row("M5.rss_sau_import", p.memory_info().rss / 2**20, "MB")
    from core.media_frame import extract_frame_image
    for _ in range(12):
        extract_frame_image(VIDEO, 3.0)
    row("M5.rss_sau_12_frame", p.memory_info().rss / 2**20, "MB")


# ── M6: duong tai lai project (thumbnail + waveform) ────────────

def m6_project_load():
    from core.media_frame import extract_frame_image
    from core.media_extractor import extract_audio_waveform
    from PySide6.QtCore import QSize
    print("\n== M6: tai lai project — thumbnail + waveform (khong co cache dia) ==")
    t0 = time.perf_counter()
    for i in range(12):
        extract_frame_image(VIDEO, 1.0 + i, QSize(160, 90))
    ms = (time.perf_counter() - t0) / 12.0 * 1000.0
    row("M6.thumbnail_ms_moi_frame", round(ms, 1), "ms",
        "12 frame/clip — clip nay 6..24 frame, moi lan mo project la chay lai")
    t0 = time.perf_counter()
    wf = extract_audio_waveform(VIDEO, 180)
    row("M6.waveform_giay", round(time.perf_counter() - t0, 2), "s",
        "%d mau, ffmpeg decode 8kHz mono" % (len(wf) if wf else 0))


def main():
    if not os.path.exists(VIDEO):
        raise SystemExit("khong co media that: %s" % VIDEO)
    os.makedirs(TMP, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    t0 = time.perf_counter()
    m1_decode_strategies()
    m2_canvas_size(app)
    m3_encoder_presets(app)
    m4_startup()
    m5_memory()
    m6_project_load()
    m0_full_export(app)
    row("TONG_thoi_gian_do", round(time.perf_counter() - t0, 1), "s")
    with open(JSON_OUT, "w", encoding="utf-8") as handle:
        json.dump(RESULTS, handle, ensure_ascii=False, indent=1, default=str)
    print("\njson: %s (%d bytes)" % (JSON_OUT, os.path.getsize(JSON_OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
