"""GATE cho dot toi uu may cau hinh thap.

Ba dieu phai dung luc nay:
  1. Xuat video NHANH THAT, do tren chinh duong cua app (FrameComposer +
     RenderWorker), so voi baseline da luu trong scratch/perf_baseline.json.
  2. Frame phat ra PHAI DUNG — khong phai "khac it" ma la khop PTS that cua
     ffmpeg. Ground truth lay bang cach giai ma THUAN TIEP ca doan frame va
     chon frame co |pts - t| nho nhat; khong dung seek cua bat cu ben nao.
  3. Cache phai phuc vu LAN HAI, va pha khi nguon thay doi hoac muc bi hong.

 Moi khoa "no nhanh hon / no thay doi" deu co counterfactual: patch duong moi
 ve duong cu thi khoa PHAI DAO CHIEU. Mot khoa khong the fail la khoa trang tri.

Chay: PYTHONIOENCODING=utf-8 python -u scratch/perf_probe.py
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
TMP = os.path.join(ROOT, "scratch", "perf_tmp")
BASELINE = os.path.join(ROOT, "scratch", "perf_baseline.json")
EVIDENCE = os.path.join(ROOT, "scratch", "clinging_perf_evidence.png")

OUT_W, OUT_H, FPS, DUR = 1280, 720, 24, 4.0
SRC_FPS = 60.0
LO, HI = 118, 152
CHECK_TIMES = [2.0 + i / 24.0 for i in range(8)]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def below(label, got, limit, unit=""):
    ok = got is not None and got < limit
    if not ok:
        fails.append("%s: got %r want < %r" % (label, got, limit))
    print("%-58s %s value=%.4f%s limit=%.4f%s"
          % (label, "PASS" if ok else "FAIL", got, unit, limit, unit))
    return ok


def above(label, got, limit, unit=""):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-58s %s value=%.4f%s limit=%.4f%s"
          % (label, "PASS" if ok else "FAIL", got, unit, limit, unit))
    return ok


def run(cmd, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit("lenh that bai %r\n%s"
                         % (cmd[:5], proc.stderr.decode("utf-8", "replace")[-900:]))
    return proc


def build_model(cards=(), dur=DUR, speed=1.0):
    from core.commands import ApplyEffectCommand, UndoStack
    from core.timeline_model import TimelineModel, TrackType
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.VIDEO, "Main")
    clip = model.add_clip(track.track_id, VIDEO, "video", 0.0, dur, "mau")
    if speed != 1.0:
        clip.speed = speed
    stack = UndoStack()
    for card in cards:
        stack.push(ApplyEffectCommand(model, clip.clip_id, card))
    return model


def baseline(key, default=None):
    with open(BASELINE, encoding="utf-8") as handle:
        data = json.load(handle)
    entry = data.get(key)
    if entry is None:
        if default is None:
            raise SystemExit("thieu baseline %s — chay scratch/perf_baseline.py truoc" % key)
        return default
    return float(entry["value"])


# ── 1. VAN TOC ──────────────────────────────────────────────────

def composer_cost(frames=48):
    from core.frame_composer import FrameComposer
    composer = FrameComposer(build_model(), OUT_W, OUT_H)
    t0 = time.perf_counter()
    images = [composer.render_frame(i / float(FPS) + 2.0) for i in range(frames)]
    dt = (time.perf_counter() - t0) / frames
    composer.close()
    return dt, images


def section_speed():
    print("\n== 1. Van toc: dung nay so voi baseline da luu ==")
    base_compose = baseline("M2.canvas_1080p_scale_ms_moi_frame")   # ms/frame
    dt, images = composer_cost()
    ms = dt * 1000.0
    print("   compose %d frame: %.1f ms/frame (baseline %.1f ms/frame)"
          % (len(images), ms, base_compose))
    below("compose/frame < 1/3 baseline may", ms, base_compose / 3.0, " ms")
    check("moi frame co du kich thuoc xuat",
          {(i.width(), i.height()) for i in images}, {(OUT_W, OUT_H)})
    check("khong co frame trang", sum(1 for i in images if i.isNull()), 0)
    uniq = {hashlib.sha256(i.constBits().tobytes()).hexdigest() for i in images}
    check("decoder tien: khong co frame lap lai o 1x", len(uniq), len(images))

    from PySide6.QtWidgets import QApplication
    from ui.export_dialog import RenderWorker
    app = QApplication.instance() or QApplication([])  # noqa: F841
    out = os.path.join(TMP, "probe_export.mp4")
    for extra in (out, out + "_audio.mp3"):
        if os.path.exists(extra):
            os.remove(extra)
    worker = RenderWorker(build_model(), out, OUT_W, OUT_H, FPS, "16:9", True)
    errors, done = [], []
    worker.errorOccurred.connect(errors.append)
    worker.finished_ok.connect(done.append)
    t0 = time.perf_counter()
    worker.run()
    wall = time.perf_counter() - t0
    base_full = baseline("M0.xuat_tron_ven_giay")
    check("xuat khong loi", bool(errors), False)
    check("xuat phoi finished_ok", done, [out])
    print("   toan bo xuat %d frame: %.1f s (baseline %.1f s)"
          % (int(DUR * FPS), wall, base_full))
    below("xuat tron ven < 1/3 baseline may", wall, base_full / 3.0, " s")
    above("file xuat co dung luong", os.path.getsize(out) / 1024.0, 100.0, " KB")
    return wall, ms


# ── 2. DUNG FRAME (PTS that cua ffmpeg) ─────────────────────────

def ffmpeg_range(path, lo, hi):
    """Giai ma THUAN TIEP lo..hi, tra [(index, pts, rgb ndarray)] — ground truth."""
    n = hi - lo + 1
    raw = os.path.join(TMP, "gt_%d_%d.raw" % (lo, hi))
    cmd = ["ffmpeg", "-y", "-loglevel", "info", "-i", path, "-vf", "showinfo",
           "-ss", "%.6f" % (lo / SRC_FPS), "-frames:v", str(n),
           "-f", "rawvideo", "-pix_fmt", "rgb24", raw]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise SystemExit("ffmpeg ground truth loi: %s" % stderr[-500:])
    pts = [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", stderr)]
    # showinfo chay TRUOC bo loc -ss nen log co ca frame bi bo: cat theo doan
    # frame that su ghi ra file.
    half = 0.5 / SRC_FPS
    start = next((k for k, p in enumerate(pts) if p >= lo / SRC_FPS - half), None)
    if start is None or len(pts) < start + n:
        raise SystemExit("showinfo khong du pts (%d) cho %d frame" % (len(pts), n))
    pts = pts[start:start + n]
    blob = np.fromfile(raw, dtype=np.uint8)
    os.remove(raw)
    h, w = 720, 1280
    if blob.size != w * h * 3 * n:
        raise SystemExit("so byte ground truth %d khong khop %d frame" % (blob.size, n))
    views = blob.reshape(n, h, w, 3)
    return [(lo + i, pts[i], views[i]) for i in range(n)]


def mad(a, b):
    return float(np.abs(a.astype(np.int32) - b.astype(np.int32)).mean())


def section_correctness():
    print("\n== 2. Doc tuan tu co tra DUNG frame theo PTS that? ==")
    from core.media_frame import SequentialVideoReader, frame_index_at
    ref = ffmpeg_range(VIDEO, LO, HI)
    reader = SequentialVideoReader(VIDEO)
    worst = 0.0
    wrong = 0
    for t in CHECK_TIMES:
        want_idx, want_pts, want_arr = min(ref, key=lambda row: abs(row[1] - t))
        frame = reader.read_bgr(t)
        if frame is None:
            fails.append("reader tra None tai t=%.4f" % t)
            wrong += 1
            continue
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        d = mad(rgb, want_arr)
        worst = max(worst, d)
        picked = frame_index_at(t, SRC_FPS)
        ok = d < 3.0 and reader._last_index == picked
        if not ok:
            wrong += 1
            print("   t=%.4f chon frame %d, PTS muon %d, mad %.2f  <- SAI"
                  % (t, reader._last_index, want_idx, d))
    reader.close()
    check("moi moc thoi gian khop PTS (mad<3, dung chi so)", wrong, 0)
    print("   lech lon nhat so voi frame PTS: %.2f/255 (2 decoder khac nhau"
          " lech vai LSB la binh thuong)" % worst)
    print("   LUU Y: khoa nay bat sai sot ro, KHONG phat hien lech 1 frame tren"
          " doan cam xuong (mad lien ke trung binh 2,08/255 gan bang nhieu decoder"
          " noise 1,54). Phan biet 1 frame la nhiem vu cua khoa marker o muc 2b.")
    below("mad toi da < 3,0", worst, 3.0)

    # Clip chay cham hon 1x: nguon 60fps, xuat 24fps nen phai toi speed < 0.4
    # hai buoc xuat MOI va vào cùng một chi so frame. Voi 0.25x, day so hoc la
    # round(120 + k*0.625): k=1 va k=2 cung ra 121. Lan thu hai PHAI tra dung
    # frame da nho va KHONG duoc seek nguoc — seek nguoc con cham hon ban cu.
    step = 0.25 / float(FPS)
    t1, t2 = 2.0 + step, 2.0 + 2 * step
    check("0.25x: hai buoc xuat roi vao cung mot chi so nguon",
          frame_index_at(t1, SRC_FPS), frame_index_at(t2, SRC_FPS))
    reader = SequentialVideoReader(VIDEO)
    reader.read_bgr(2.0)

    # cv2.VideoCapture la lop pybind11, instance Gan thuoc tinh read-only →
    # kh the dan den set. Thay capture bang proxy dem set: moi lan seek qua
    # day duoc tinh, va doc nguoc duoi cung phai lam dem nhay len (kiem tra
    # duoi day) chung to dem khong bao gio chay khong.
    class SeekCounter:
        def __init__(self, cap):
            self._cap, self.seeks = cap, 0

        def isOpened(self):
            return self._cap.isOpened()

        def get(self, *a):
            return self._cap.get(*a)

        def release(self):
            return self._cap.release()

        def grab(self):
            return self._cap.grab()

        def read(self):
            return self._cap.read()

        def set(self, *a, **kw):
            self.seeks += 1
            return self._cap.set(*a, **kw)

    counter = SeekCounter(reader._cap)
    reader._cap = counter
    a = reader.read_bgr(t1)
    b = reader.read_bgr(t2)
    check("0.25x: frame lap lai khong khi nao seek", counter.seeks, 0)
    check("0.25x: lan hai tra dung pixel lan mot",
          a is not None and b is not None and np.array_equal(a, b), True)
    # Cung proxy nay, doc ve moc cu HON phai seek — neu dem van 0 thi phe
    # kiem tren chi la do trong, khong phai bang chung.
    reader.read_bgr(1.0)
    above("0.25x: proxy dem seek phan biet duoc (doc nguoc van thay seek)",
          counter.seeks, 0)
    reader.close()


# ── 2b. MARKER: chi so frame tra ve do bang DEM, khong do bang ANH ────────

MARK_W, MARK_H, MARK_N = 640, 360, 240
MARKER = os.path.join(TMP, "bitmark_60fps.mp4")
# Lech mot phan tu frame de round() va floor() khong doi mat nhau: 1/24s cua
# timeline crop 0,004s = 0,24 frame nguon, nen le 24fps duoc 4 moc round-len
# va 4 moc round-xuong. Nam ngang 0,5 frame (kieu CHECK_TIMES o tren) thi
# round/floor/PTS cung do le nhau — khong co gi de phan biet.
MARK_TIMES = [2.0 + i / 24.0 + 0.004 for i in range(8)]
_PTS_CACHE = {}


def build_marker_clip():
    """Clip 4 giay 60fps, frame thu k mang chinh so k: 8 khoi trang = 8 bit.

    Ly do khong dung video that cho khoa nay: tren doan 60fps cua chinh clip
    jimeng, hai frame lien ke lech trung binh 2,08 va nho nhat 0,98 diem/255
    (do bang ffmpeg showinfo + rawvideo), trong khi HAI DECODER KHAC nhau tra
    ve cung mot frame da lech toi 1,54/255. So sanh anh vi the bat duoc sai
    sot ro (sai ca doan, sai canvas) nhung VO HOP voi lech MOT frame — dung
    cai lech ma round()/floor() gay ra. Marker doc ra so nguyen, lech mot
    frame la lech mot don vi dem duoc, khong co nguong mo.
    """
    if os.path.exists(MARKER):
        return
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", "%dx%d" % (MARK_W, MARK_H), "-r", "60",
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-g", str(MARK_N), "-pix_fmt", "yuv420p", "-an", MARKER],
        stdin=subprocess.PIPE)
    for k in range(MARK_N):
        frame = np.zeros((MARK_H, MARK_W, 3), dtype=np.uint8)
        for bit in range(8):
            if (k >> (7 - bit)) & 1:
                x0 = bit * (MARK_W // 8) + 4
                frame[40:320, x0:x0 + 72] = 255
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait(timeout=900) != 0:
        raise SystemExit("khong dung duoc clip marker")


def read_marker(frame):
    """Chi so frame ma chinh no tu khai (lam tron vung cua tung khoi bit)."""
    band = frame.mean(axis=2)[60:300]
    value = 0
    for bit in range(8):
        x0 = bit * (MARK_W // 8) + 8
        if band[:, x0:x0 + 64].mean() > 120.0:
            value |= 1 << (7 - bit)
    return value


def marker_pts():
    """pts that cua tung frame clip marker, lay tu chinh ffmpeg."""
    if MARKER not in _PTS_CACHE:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "info", "-i", MARKER,
             "-vf", "showinfo", "-f", "null", "-"],
            capture_output=True, timeout=600)
        _PTS_CACHE[MARKER] = [float(m.group(1)) for m in re.finditer(
            r"pts_time:([0-9.]+)", proc.stderr.decode("utf-8", "replace"))]
    return _PTS_CACHE[MARKER]


def marker_check():
    """Doc clip marker qua duong that; dem moc tra ve chi so khac PTS gan nhat.

    KHONG dung frame_index_at o day: mong doi lay tu pts ffmpeg, nen phep thu
    bat duoc ca hai loi — chon sai frame va chon dung frame theo mot quy tac
    khong trung voi PTS.
    """
    import core.media_frame as mf
    pts = marker_pts()
    if len(pts) < MARK_N:
        raise SystemExit("clip marker thieu pts (%d/%d)" % (len(pts), MARK_N))
    reader = mf.SequentialVideoReader(MARKER)
    bad, detail = 0, []
    try:
        for t in MARK_TIMES:
            want = min(range(len(pts)), key=lambda i: abs(pts[i] - t))
            frame = reader.read_bgr(t)
            got = -1 if frame is None else read_marker(frame)
            if got != want:
                bad += 1
            detail.append((t, want, got))
    finally:
        reader.close()
    return bad, detail


def section_marker():
    print("\n== 2b. Chi so frame tra ve do bang marker (phan biet duoc 1 frame) ==")
    build_marker_clip()
    bad, detail = marker_check()
    for t, want, got in detail:
        print("   t=%.4fs  PTS muon frame %3d  reader tra ve %3d%s"
              % (t, want, got, "" if got == want else "   <- SAI"))
    check("quy tac hien hanh tra dung chi so moi moc", bad, 0)


# ── 3. PREVIEW TRONG MainWindow THAT ────────────────────────────

PREVIEW_STEPS = 24
PREVIEW_T0 = 2.0
PREVIEW_EVIDENCE = os.path.join(ROOT, "scratch", "clinging_perf_preview.png")


class _OldPreviewReader:
    """DUNG code giai ma cua preview hom qua: capture cu, chi seek khi chi so
    doi. De khoa van toc co doi chieu that, khong phai do ta tuong tuong.
    """

    caps = {}

    def __init__(self, path):
        import cv2
        cap = _OldPreviewReader.caps.get(path)
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(path)
            _OldPreviewReader.caps[path] = cap
        self._cap = cap
        self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    @property
    def dead(self):
        return not self._cap.isOpened()

    def read_bgr(self, seconds):
        import cv2
        from core.media_frame import frame_index_at
        idx = frame_index_at(seconds, self._fps)
        if int(self._cap.get(cv2.CAP_PROP_POS_FRAMES)) != idx:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self):
        pass


def _preview_window():
    """MainWindow that + mot clip video, lap lai cach dung cua probe khac."""
    from core import project_storage
    from core.timeline_model import TrackType
    from ui.main_window import MainWindow
    project_storage.AUTO_SAVE_FILE = os.path.join(TMP, "preview_autosave.json")
    win = MainWindow()
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    win._play_timer.stop()
    # Do rieng chi phi giai ma: _pre_buffer_active_audio khong lien quan den
    # decoder va duoc ap dung giong het cho CA HAI dau do (moi lan cu).
    win._pre_buffer_active_audio = lambda: None
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    track = model.add_track(TrackType.VIDEO, "perf")
    model.add_clip(track.track_id, VIDEO, "video", 0.0, 4.0, "perf")
    win._sync_canvas()
    return win, model


def _reset_readers(win):
    for reader in win._video_readers.values():
        reader.close()
    win._video_readers.clear()


def _preview_step_ms(win):
    t0 = time.perf_counter()
    for i in range(PREVIEW_STEPS):
        win._sync_canvas_frames_at_time(PREVIEW_T0 + i / float(FPS))
    return (time.perf_counter() - t0) * 1000.0 / PREVIEW_STEPS


def section_preview(app):
    print("\n== 3. Preview trong MainWindow: chi phi moi buoc playhead ==")
    import cv2
    import core.media_frame as mf
    win, model = _preview_window()
    try:
        check("canvas co dung 1 clip video de do",
              len(win.preview_panel.canvas._clip_items), 1)

        _reset_readers(win)
        new_ms = _preview_step_ms(win)
        real_reader = mf.SequentialVideoReader
        mf.SequentialVideoReader = _OldPreviewReader
        try:
            _reset_readers(win)
            old_ms = _preview_step_ms(win)
        finally:
            mf.SequentialVideoReader = real_reader
            _reset_readers(win)
        print("   moi %.1f ms/buoc  vs  cu %.1f ms/buoc  (%.1fx)"
              % (new_ms, old_ms, old_ms / max(new_ms, 1e-9)))
        below("preview moi < 1/3 ban cu do cung may", new_ms, old_ms / 3.0, " ms")
        below("preview kip buoc 24fps (< 60 ms/buoc)", new_ms, 60.0, " ms")
        # Khoa tuyet doi phai dao chieu khi quay lai seek: chung to 60 ms khong
        # phai con so an toan du thuc te chay nhanh.
        above("quay lai kieu cu khien khoa 60 ms/buoc DAO CHIEU", old_ms, 60.0, " ms")

        # Preview ve DUNG frame ma export xuat ra.
        item = list(win.preview_panel.canvas._clip_items.values())[0]

        def old_preview_frame(path, t):
            cap = cv2.VideoCapture(path)
            cap.set(cv2.CAP_PROP_POS_FRAMES,
                    mf.frame_index_at(t, cap.get(cv2.CAP_PROP_FPS)))
            ok, frame = cap.read()
            cap.release()
            return frame if ok else None

        rows, diffs = [], []
        for t in (2.0, 2.5, 3.0):
            win._sync_canvas_frames_at_time(t)
            drawn = qimage_to_bgr(item.current_frame_pixmap.toImage())
            ref = old_preview_frame(VIDEO, t)
            if ref is None or drawn.shape != ref.shape:
                raise SystemExit("preview khong so sanh duoc tai %.1f" % t)
            d = float(np.abs(drawn.astype(np.int32)
                             - ref.astype(np.int32)).mean())
            diffs.append(d)
            rows.append((t, drawn, ref))
        check("preview ve dung frame cua duong cu (mad==0)",
              [round(d, 3) for d in diffs], [0.0, 0.0, 0.0])

        # Khong con duong seek cu sot ra trong ham preview.
        import inspect
        src = inspect.getsource(win._sync_canvas_frames_at_time)
        check("ham preview khong con cv2.VideoCapture",
              "cv2.VideoCapture" in src, False)

        # Mo du an khac (clip bien khoi model) phai dong decoder cu.
        clip_id = model.tracks[0].clips[0].clip_id
        model.remove_clip(clip_id)
        win._sync_canvas()
        check("clip bi xoa thi decoder cung bi dong",
              len(win._video_readers), 0)

        tiles = []
        for t, drawn, ref in rows:
            delta = np.clip(np.abs(drawn.astype(np.int32)
                                   - ref.astype(np.int32)) * 8, 0, 255
                            ).astype(np.uint8)
            control = old_preview_frame(VIDEO, t + 1.0 / 60.0)
            boost = np.clip(np.abs(drawn.astype(np.int32)
                                   - control.astype(np.int32)) * 8,
                            0, 255).astype(np.uint8)
            tiles.append(np.concatenate([drawn, ref, delta, boost], axis=1))
        strip = np.concatenate(tiles, axis=0)
        scale = 960.0 / strip.shape[1]
        strip = cv2.resize(strip, (int(strip.shape[1] * scale),
                                   int(strip.shape[0] * scale)),
                           interpolation=cv2.INTER_AREA)
        sheet = np.full((strip.shape[0] + 78, strip.shape[1] + 12, 3), 18, np.uint8)
        sheet[58:58 + strip.shape[0], 6:6 + strip.shape[1]] = strip
        for i, text in enumerate([
                "Clinging - preview (MainWindow that) vs duong giai ma cu",
                "cot 1 frame preview ve len canvas | cot 2 mo+seek+doc cu "
                "| cot 3 lech x8 | cot 4 lech voi frame ke can x8",
                "t = 2.0, 2.5, 3.0 s    lech %s mau/255    %.1f ms/buoc (cu %.1f)"
                % (", ".join("%.2f" % d for d in diffs), new_ms, old_ms)]):
            cv2.putText(sheet, text, (8, 16 + i * 17), cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (232, 232, 232), 1, cv2.LINE_AA)
        if not cv2.imwrite(PREVIEW_EVIDENCE, sheet):
            raise SystemExit("khong ghi duoc anh preview")
        print("   evidence: %s (%d bytes, %dx%d)"
              % (PREVIEW_EVIDENCE, os.path.getsize(PREVIEW_EVIDENCE),
                 sheet.shape[1], sheet.shape[0]))
    finally:
        _reset_readers(win)
        for cap in _OldPreviewReader.caps.values():
            cap.release()
        _OldPreviewReader.caps.clear()
        win.close()
        app.processEvents()


# ── 3b. PREVIEW = EXPORT (quy tac chon frame) ───────────────────

def section_parity():
    print("\n== 3b. Preview va Export dung CHUNG mot quy tac chon frame ==")
    import cv2
    from core.media_frame import SequentialVideoReader, frame_index_at

    def preview_style(path, t):
        """Cac buoc preview TUNG chay: mo capture, tinh chi so, seek, doc.
        Day la NGHIA cua preview (frame gan nhat theo chi so) — duong moi phai
        tra dung nghia do, khong phai mot thu gi gan gan."""
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        idx = frame_index_at(t, fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        cap.release()
        return frame if ok else None

    reader = SequentialVideoReader(VIDEO)
    diffs = []
    for t in CHECK_TIMES:
        p = preview_style(VIDEO, t)
        e = reader.read_bgr(t)
        if p is None or e is None:
            diffs.append(None)
        else:
            diffs.append(mad(p[:, :, ::-1], e[:, :, ::-1]))
    reader.close()
    check("khong co luong doc that bai", sum(1 for d in diffs if d is None), 0)
    check("preview va export tra cung pixel moi moc",
          [round(d, 3) for d in diffs], [0.0] * len(CHECK_TIMES))
    # Khoa nguon: preview va export phai DI QUA CUNG MOT LOAI, khong duoc phep
    # tinh round(t*fps) roi o hai noi — do chinh la loi cu.
    src_ui = open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8").read()
    src_cf = open(os.path.join(ROOT, "core", "frame_composer.py"), encoding="utf-8").read()
    check("ui/main_window.py dung SequentialVideoReader",
          "SequentialVideoReader(" in src_ui, True)
    check("core/frame_composer.py dung SequentialVideoReader",
          "SequentialVideoReader(" in src_cf, True)
    check("chi mot noi tinh round(t*fps): core/media_frame.frame_index_at",
          src_ui.count("frame_index_at(") + src_cf.count("frame_index_at("), 0)
    check("khong con round(source_time * fps) noi loan o preview",
          "int(round(source_time * fps))" in src_ui, False)


# ── 4. COUNTERFACTUAL ───────────────────────────────────────────

def section_counterfactual():
    print("\n== 4. Chung minh cac khoa tren CO THE FAIL ==")
    import core.media_frame as mf
    import core.frame_composer as fc

    real_read = mf.SequentialVideoReader.read_bgr

    def old_way(self, seconds):
        """Dung lai kieu cu: mo + seek msec + doc + dong MOI frame."""
        import cv2
        cap = cv2.VideoCapture(VIDEO)
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = cap.read()
        cap.release()
        return frame if ok else None

    mf.SequentialVideoReader.read_bgr = old_way
    try:
        slow_ms, _ = composer_cost(frames=16)
    finally:
        mf.SequentialVideoReader.read_bgr = real_read
    fast_ms, _ = composer_cost(frames=16)
    print("   cu %.0f ms/frame  vs  moi %.0f ms/frame  (gap %.1fx)"
          % (slow_ms * 1000, fast_ms * 1000, slow_ms / max(fast_ms, 1e-9)))
    above("patch ve kieu cu khien khoa van TOC dao chieu",
          slow_ms, fast_ms * 2.0, " ms")

    # Khoa PTS phai nhay cam voi phep quy doi: cat nguyen (floor) thay vi round
    # thi moc phai doc duoc chi so khac PTS. Do tren clip marker vi tren video
    # that lech 1 frame nam duoi nguong phan biet cua hai decoder (xem
    # build_marker_clip).
    real_rule = mf.frame_index_at
    floor_rule = lambda s, f: max(0, int(float(s) * float(f)))
    mf.frame_index_at = floor_rule
    try:
        bad, detail = marker_check()
    finally:
        mf.frame_index_at = real_rule
    print("   voi quy tac floor(): %d/%d moc doc sai chi so %s"
          % (bad, len(MARK_TIMES), [(w, g) for _, w, g in detail if g != w]))
    above("doi round() thanh floor() khien khoa MARKER dao chieu", bad, 0)
    check("frame_index_at da duoc phuc hoi", mf.frame_index_at, real_rule)
    back, _ = marker_check()
    check("phuc hoi xong thi khoa MARKER lai pass", back, 0)


# ── 5. CACHE DIA ────────────────────────────────────────────────

def section_cache(app):
    print("\n== 5. Cache anh nho + dang song ==")
    from core import media_cache
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage
    from core.media_frame import extract_frame_image

    media_cache.clear()
    check("cache khoi dong trong", media_cache.stats()[0], 0)

    calls = {"n": 0}
    import core.media_frame as mf
    real = mf.extract_frame_image

    def counting(path, seconds=0.0, target_size=None):
        calls["n"] += 1
        return real(path, seconds, target_size)

    mf.extract_frame_image = counting
    try:
        from ui.graphics.clip_item import MediaExtractionWorker
        worker = MediaExtractionWorker(VIDEO, "video", "mau", 60, 0.0, 6.0, 1.0)
        shots = []
        worker.thumbnailReady.connect(lambda v: shots.append(list(v)))
        t0 = time.perf_counter()
        worker.run()
        cold = time.perf_counter() - t0
        cold_calls = calls["n"]
        first = shots[-1] if shots else []

        calls["n"] = 0
        shots2 = []
        worker2 = MediaExtractionWorker(VIDEO, "video", "mau", 60, 0.0, 6.0, 1.0)
        worker2.thumbnailReady.connect(lambda v: shots2.append(list(v)))
        t0 = time.perf_counter()
        worker2.run()
        warm = time.perf_counter() - t0
        warm_calls = calls["n"]
        second = shots2[-1] if shots2 else []
    finally:
        mf.extract_frame_image = real

    print("   lan 1: %.1f s / %d luot giai ma — lan 2: %.1f s / %d luot"
          % (cold, cold_calls, warm, warm_calls))
    above("lan 1 giai ma that", cold_calls, 0)
    check("lan 2 KHONG giai ma lai frame nao", warm_calls, 0)
    check("so anh nho hai lan giong nhau", len(first), len(second))
    above("dinh dang anh nho ra file PNG that", len(first), 0)
    below("lan 2 nhanh hon lan 1", warm, cold, " s")
    # So sanh pixel phai qua ARGB32: bytesPerLine cua RGB888 duoc Qt dem len
    # boi 4 va phan dem KHONG dc khoi tao, nen so truc tiep constBits() se
    # khac nhau giua hai lan doc cho cung mot anh.
    def canon(img):
        from PySide6.QtGui import QImage
        conv = img.convertToFormat(QImage.Format.Format_ARGB32)
        bits = conv.constBits()
        try:
            return bits.tobytes()
        except AttributeError:
            return bytes(bits)

    same = (len(first) == len(second)
            and all(canon(a) == canon(b) for a, b in zip(first, second)))
    check("pixel hai lan giong het nhau", same, True)
    above("co file tren dia", media_cache.stats()[0], 0)

    # Khoa phai theo noi dung nguon: doi file la khac khoa.
    tmp_src = os.path.join(TMP, "cache_probe_src.mp4")
    if not os.path.exists(tmp_src):
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", VIDEO, "-ss", "2",
             "-t", "1", "-c", "copy", tmp_src])
    k1 = media_cache.image_key(tmp_src, "timeline", 0.5, 160, 60)
    before = os.stat(tmp_src).st_mtime_ns
    os.utime(tmp_src, ns=(before + 10 ** 9, before + 10 ** 9))
    k2 = media_cache.image_key(tmp_src, "timeline", 0.5, 160, 60)
    check("doi mtime nguon sinh khoa khac", k1 != k2, True)

    # Muc bi hong: khong duoc crash, khong duoc tra anh rac, phai tinh lai.
    with open(k1, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n ra rac khong phai PNG")
    check("doc muc hong tra QImage trong", media_cache.read_image(k1).isNull(), True)
    check("doc muc hong khong lam hop thu", media_cache.read_waveform(k1), None)
    media_cache.remove_path(k1)
    check("go muc hong khoi dia", os.path.exists(k1), False)

    # Waveform: lan 2 khong chay ffmpeg; va [] (file khong co tieng) cung phai
    # duoc cache — khong thi mo project lai chay ffmpeg vo ich.
    from core.media_extractor import extract_audio_waveform
    import core.media_extractor as me
    real_run = me.subprocess.run
    runs = {"n": 0}

    def counting_run(cmd, *a, **kw):
        runs["n"] += 1
        return real_run(cmd, *a, **kw)

    me.subprocess.run = counting_run
    try:
        media_cache.clear()
        w1 = extract_audio_waveform(VIDEO, num_samples=180, start=0.0, duration=4.0)
        n_first = runs["n"]
        w2 = extract_audio_waveform(VIDEO, num_samples=180, start=0.0, duration=4.0)
        n_second = runs["n"]
    finally:
        me.subprocess.run = real_run
    check("waveform khong rong", len(w1), 180)
    check("lan 1 chay ffmpeg dung 1 lan", n_first, 1)
    check("lan 2 khong chay ffmpeg", n_second - n_first, 0)
    check("waveform tu cache giong het ban tinh lai", w2 == w1, True)

    # Goi DANG MA CU (khong ghi duration) — dung duong clip_audio_probe dung:
    # duration=None khong duoc lam khoa cache no vu dung.
    me.subprocess.run = counting_run
    try:
        media_cache.clear()
        n_base = runs["n"]
        d1 = extract_audio_waveform(VIDEO, 60)
        n_d1 = runs["n"]
        d2 = extract_audio_waveform(VIDEO, 60)
        n_d2 = runs["n"]
        missing = extract_audio_waveform(os.path.join(TMP, "khong_ton_tai.mp4"), 60)
    finally:
        me.subprocess.run = real_run
    check("goi khong duration van tra song + cache",
          (len(d1), n_d1 - n_base, n_d2 - n_d1), (60, 1, 0))
    check("song cua mac dinh giong ban tu tinh", d2, d1)
    check("file khong ton tai tra list rong, khong loi", missing, [])
    return cold, warm, cold_calls, warm_calls


# ── 6. ANH BANG CHUNG ───────────────────────────────────────────

def qimage_to_bgr(img):
    """QImage (moi kieu) -> ndarray BGR, xu ly dung bytesPerLine hay bi dem."""
    import cv2
    from PySide6.QtGui import QImage
    conv = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = conv.width(), conv.height()
    bpl = conv.bytesPerLine()
    bits = conv.constBits()
    try:
        raw = bits.tobytes()
    except AttributeError:
        raw = bytes(bits)
    plane = np.frombuffer(raw[:bpl * h], np.uint8).reshape(h, bpl)
    rgb = plane[:, :w * 3].reshape(h, w, 3)
    return cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)


def section_evidence():
    print("\n== 6. Anh bang chung: giai ma qua duong MOI vs duong CU ==")
    import cv2
    from core.media_frame import SequentialVideoReader, extract_frame_image
    ts = [2.0, 2.5, 3.0]
    reader = SequentialVideoReader(VIDEO)
    tiles, diffs = [], []
    for t in ts:
        new = reader.read_bgr(t)
        old_img = extract_frame_image(VIDEO, t)
        # Frame KE CANH (t + 1/60s) lam mau dieu khien: nee "lech x8" chi la
        # bang den mac dinh thi cot 3 den lang khong noi len dieu gi. Cot 4 cung
        # phep tru do, voi mot frame khac that, phai sang buoc.
        neigh = reader.read_bgr(t + 1.0 / 60.0)
        if new is None or old_img.isNull() or neigh is None:
            raise SystemExit("khong giai ma duoc frame bang chung tai %.1f" % t)
        old = qimage_to_bgr(old_img)
        if old.shape != new.shape:
            old = cv2.resize(old, (new.shape[1], new.shape[0]))
        d = float(np.abs(new.astype(np.int32) - old.astype(np.int32)).mean())
        diffs.append(d)

        def boosted(other):
            # |moi - khac| nhan 8 lan de lech nut nhin thay duoc bang mat.
            return np.clip(np.abs(new.astype(np.int32)
                                  - other.astype(np.int32)) * 8,
                           0, 255).astype(np.uint8)

        tiles.append(np.concatenate([new, old, boosted(old), boosted(neigh)], axis=1))
    reader.close()
    strip = np.concatenate(tiles, axis=0)
    # Scale TUNG chieu theo strip da ghep (khong dung chieu cao mot o): dung
    # chieu cao o roi thi sheet bi nen doc 3 lan va ô trông nhu frame bi hong.
    scale = 960.0 / strip.shape[1]
    strip = cv2.resize(strip, (int(strip.shape[1] * scale), int(strip.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    sheet = np.full((strip.shape[0] + 78, strip.shape[1] + 12, 3), 18, np.uint8)
    sheet[58:58 + strip.shape[0], 6:6 + strip.shape[1]] = strip
    labels = [
        "Clinging - toi uu may cau hinh thap: moi hang la mot moc thoi gian",
        "cot 1 MOI (doc tuan tu) | cot 2 CU (mo+seek msec+dong) "
        "| cot 3 lech MOI-CU x8 | cot 4 lech voi frame ke can x8 (mau dieu khien)",
        "t = %s s    lech binh quan %s mau/255"
        % (", ".join("%.1f" % t for t in ts), ", ".join("%.2f" % d for d in diffs)),
    ]
    for i, text in enumerate(labels):
        cv2.putText(sheet, text, (8, 16 + i * 17), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (232, 232, 232), 1, cv2.LINE_AA)
    if not cv2.imwrite(EVIDENCE, sheet):
        raise SystemExit("khong ghi duoc anh bang chung")
    print("   evidence: %s (%d bytes, %dx%d)"
          % (EVIDENCE, os.path.getsize(EVIDENCE), sheet.shape[1], sheet.shape[0]))
    print("   lech binh quan hai duong: %s mau/255" % [round(d, 2) for d in diffs])


def main():
    for path in (VIDEO, BASELINE):
        if not os.path.exists(path):
            raise SystemExit("thieu %s" % path)
    os.makedirs(TMP, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841

    section_speed()
    section_correctness()
    section_marker()
    section_preview(app)
    section_parity()
    section_counterfactual()
    section_cache(app)
    section_evidence()

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
