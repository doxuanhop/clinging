"""Dung video mau POP ART bang chinh RenderWorker cua app (khong phai ham phong).

Ba lan xuat tren CUNG mot model, chi khac hieu ung:

  goc      — khong hieu ung (duoi nay dung de do "pop art co that den file")
  popart   — chi co hieu ung mau Pop Art
  mau      — Pop Art + Ken Burns Out (san pham_gui_nhan, co _audio.mp3)

Moi khoa doc pixel/PCM NGAY TREN FILE MP4 DA TAO RA, khong phai mang frame
trong bo nho: mot hieu ung bi rot roi trong luc encode van bi bat duoc.

  1. File mau phai co ca video lan audio stream, dung luong luong.
  2. Audio khong im lang (RMS do tu PCM giai ma), va sidecar _audio.mp3 cung
     co am luong gan bang long truyen trong mp4.
  3. Pop art phai doi anh sau khi encode (so voi lan "goc").
  4. Ken Burns phai doi khung hinh theo thoi gian sau khi encode (so voi lan
     "popart" cung mau, chi khac hoat an) — do la bang chung "video co hoat
     anh" di den tan file.
  5. Bang chung hinh: 3 mốc thời gian x 3 lan xuat, giai ma tu file.

Chay: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/popart_sample_render.py
"""

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")
TMP = os.path.join(OUT, "popart_sample_tmp")
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
EVIDENCE = os.path.join(OUT, "clinging_popart_sample.png")

W, H, FPS, DUR = 1280, 720, 24, 8.0
REUSE = os.environ.get("CLINGING_REUSE_SAMPLES") == "1"
TIMESTAMPS = (1.0, 4.0, 7.0)
RUNS = (("goc", []),
        ("popart", [{"name": "Pop Art", "category": "Sắc thái",
                     "icon": "fa6s.circle-dot"}]),
        ("mau", [{"name": "Pop Art", "category": "Sắc thái",
                  "icon": "fa6s.circle-dot"},
                 {"name": "Ken Burns Out", "category": "Hoạt ảnh",
                  "icon": "fa6s.magnifying-glass-minus"}]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want ~%r+-%r" % (label, got, want, tol))
    print("%-56s %s got=%r want~%.2f+-%.2f"
          % (label, "PASS" if ok else "FAIL", got, want, tol))
    return ok


def above(label, got, limit):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-56s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def run(cmd, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit("lenh that bai %r:\n%s"
                         % (cmd[:6], proc.stderr.decode("utf-8", "replace")[-800:]))
    return proc


# ── dung mo hinh bang dung lenh production ──────────────────────

def build_model(cards):
    from core.commands import ApplyEffectCommand, UndoStack
    from core.timeline_model import TimelineModel, TrackType
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.VIDEO, "Main")
    clip = model.add_clip(track.track_id, VIDEO, "video", 0.0, DUR, "mau")
    stack = UndoStack()
    for card in cards:
        stack.push(ApplyEffectCommand(model, clip.clip_id, card))
    return model


def render(cards, out_path):
    from PySide6.QtWidgets import QApplication
    from ui.export_dialog import RenderWorker
    app = QApplication.instance() or QApplication([])  # noqa: F841
    if REUSE and os.path.exists(out_path):
        # Chi de thu nhanh khi sua mot khoa do luong; lan xuat hang that luon
        # chay voi REUSE tat de file mp4 sinh ra dung sau code hien tai.
        print("   (tai dung %s — CLINGING_REUSE_SAMPLES=1)" % os.path.basename(out_path))
        return 0.0
    for extra in (out_path, out_path + "_audio.mp3"):
        if os.path.exists(extra):
            os.remove(extra)
    worker = RenderWorker(build_model(cards), out_path, W, H, FPS, "16:9", True)
    errors, done = [], []
    worker.errorOccurred.connect(errors.append)
    worker.finished_ok.connect(done.append)
    t0 = time.perf_counter()
    worker.run()
    dt = time.perf_counter() - t0
    check("%s: khong loi xuat" % os.path.basename(out_path)[:16], bool(errors), False)
    check("%s: phoi finished_ok" % os.path.basename(out_path)[:16], done, [out_path])
    return dt


# ── do duoc tren FILE ───────────────────────────────────────────

def probe_streams(path):
    proc = run(["ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name:format=duration", "-of",
                "json", path])
    data = __import__("json").loads(proc.stdout.decode("utf-8", "replace"))
    return ([s.get("codec_type") + ":" + str(s.get("codec_name"))
             for s in data.get("streams", [])],
            float(data.get("format", {}).get("duration", 0.0)))


def frame_at(path, t, png):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ss", "%.3f" % t,
         "-frames:v", "1", png])
    import cv2
    img = cv2.imread(png, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("khong giai ma duoc frame %s@%.1f" % (path, t))
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float64)


def rms_of(path):
    """RMS cua am thanh trong file, do tren PCM 48k da giai ma."""
    wav = os.path.join(TMP, "rms_%d.wav" % (abs(hash(path)) % 100000))
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn",
         "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", wav])
    import wave
    with wave.open(wav, "rb") as fh:
        n, ch, rate, width = fh.getnframes(), fh.getnchannels(), fh.getframerate(), fh.getsampwidth()
        raw = fh.readframes(n)
    os.remove(wav)
    samples = np.frombuffer(raw, np.int16).astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(samples ** 2))), n / float(rate), ch


def main():
    if not os.path.exists(VIDEO):
        raise SystemExit("khong co media that: %s" % VIDEO)
    if not REUSE:
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    paths = {}
    times = {}
    for name, cards in RUNS:
        path = os.path.join(TMP, "sample_%s.mp4" % name)
        print("\n-- xuat '%s' (%d hieu ung) --" % (name, len(cards)))
        times[name] = render(cards, path)
        print("   %.1f giay cho %.0f frame %dx%d" % (times[name], DUR * FPS, W, H))
        paths[name] = path
        above("file %s co dung luong" % name, os.path.getsize(path), 100000)

    print("\n== 1. luong trong file mau ==")
    codecs, dur = probe_streams(paths["mau"])
    check("mau co video h264", "video:h264" in codecs, True)
    check("mau co audio aac", "audio:aac" in codecs, True)
    near("luong file mau = %.0f giay" % DUR, dur, DUR, 0.25)

    print("\n== 2. am thanh that, khong im lang ==")
    rms_video, secs_video, ch_video = rms_of(paths["mau"])
    sidecar = os.path.join(TMP, "sample_mau_audio.mp3")
    check("co sidecar _audio.mp3", os.path.exists(sidecar), True)
    rms_mp3, secs_mp3, _ = rms_of(sidecar)
    above("RMS trong mp4 > nguong im lang", rms_video, 0.005)
    above("RMS trong _audio.mp3 > nguong im lang", rms_mp3, 0.005)
    check("mp4 co 2 kenh am thanh", ch_video, 2)
    near("sidecar cung luong voi mp4", secs_mp3, secs_video, 0.5)
    near("sidecar va mp4 cung am luong", rms_mp3 / rms_video, 1.0, 0.35)

    print("\n== 3. pop art song sau khi encode ==")
    diffs = []
    grid = []
    for t in TIMESTAMPS:
        row = []
        for name, _cards in RUNS:
            row.append(frame_at(paths[name], t,
                                os.path.join(TMP, "f_%s_%.0f.png" % (name, t))))
        grid.append(row)
        d = float(np.abs(row[2] - row[0]).mean())
        diffs.append(d)
        print("   t=%.1fs  goc->popart+zoom doi %.1f mau" % (t, d))
    above("moi mốc thoi gian deu khac ban goc", min(diffs), 12.0)
    above("ca ba mốc deu doi tren 30 gia tri mau", min(diffs), 30.0)

    print("\n== 4. hoat anh song sau khi encode ==")
    # Cung mau Pop Art, chi khac Ken Burns. _m_zoom_out (core/anim_engine.py)
    # la scale = 1 + 0.02*(1 - ease_smooth(p)): bat dau o 1.02 va TRA VE 1.0
    # o cuoi clip, nen do lech hai lan xuat PHAI giam dan theo thoi gian. Do
    # lech tang nguoc lai co nghia la hoat anh bi dao chieu hoac co dinh.
    zoom = [float(np.abs(grid[i][2] - grid[i][1]).mean()) for i in range(len(TIMESTAMPS))]
    above("Ken Burns doi hinh so voi khong co hoat anh", min(zoom), 3.0)
    check("ken burns lui dan: do lech giam theo thoi gian",
          all(zoom[i] > zoom[i + 1] for i in range(len(zoom) - 1)), True)
    print("   zoom t=%s: %s" % (list(TIMESTAMPS), [round(z, 1) for z in zoom]))

    print("\n== 5. dong goi & tai lai ==")
    deliverable = os.path.join(OUT, "clinging_popart_sample.mp4")
    shutil.copyfile(paths["mau"], deliverable)
    shutil.copyfile(sidecar, os.path.join(OUT, "clinging_popart_sample_audio.mp3"))
    again, again_dur = probe_streams(deliverable)
    check("file giao duoc mo duoc voi 2 luong", len(again), 2)
    near("file giao duoc giu nguyen luong", again_dur, dur, 0.05)

    write_evidence(grid, paths, times, rms_video)
    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


def write_evidence(grid, paths, times, rms):
    import cv2
    labels = ["goc (khong hieu ung)", "chi Pop Art", "Pop Art + Ken Burns (file giao)"]
    tile_w, tile_h = 426, 240
    gap, band, foot = 6, 32, 46
    sheet = np.full((band + gap + len(grid) * (tile_h + 18) + foot,
                     gap + len(labels) * (tile_w + gap), 3), 18, np.uint8)
    for c, text in enumerate(labels):
        cv2.putText(sheet, text, (gap + c * (tile_w + gap) + 4, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (238, 238, 238), 1, cv2.LINE_AA)
    for r, (t, row) in enumerate(zip(TIMESTAMPS, grid)):
        y0 = band + gap + r * (tile_h + 18)
        cv2.putText(sheet, "t = %.1f s (giai ma truc tiep tu file mp4)" % t,
                    (gap, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (200, 200, 120), 1, cv2.LINE_AA)
        for c, arr in enumerate(row):
            tile = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)
            tile = cv2.resize(tile, (tile_w, tile_h))
            sheet[y0 + 16:y0 + 16 + tile_h,
                  gap + c * (tile_w + gap):gap + c * (tile_w + gap) + tile_w] = tile
    lines = ["nguon: data/video/jimeng-2026-01-30-2619_new_audio.mp4   %dx%d@%d   %.0f giay"
             % (W, H, FPS, DUR),
             "RenderWorker cua app, khong co duong tat: %s"
             % ", ".join("%s %.1fs" % (n, times[n]) for n, _ in RUNS),
             "am thanh: aac 192k trong mp4 + sidecar _audio.mp3, RMS %.4f" % rms]
    for i, text in enumerate(lines):
        cv2.putText(sheet, text, (gap, sheet.shape[0] - 30 + i * 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (205, 205, 205), 1, cv2.LINE_AA)
    if not cv2.imwrite(EVIDENCE, sheet):
        raise SystemExit("khong ghi duoc anh bang chung")
    print("evidence image: %s (%d bytes, %dx%d)"
          % (EVIDENCE, os.path.getsize(EVIDENCE), sheet.shape[1], sheet.shape[0]))


if __name__ == "__main__":
    sys.exit(main())
