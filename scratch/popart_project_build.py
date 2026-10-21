"""Tao du an "Pop Art Demo" (.clinq) + ban xuat MP4 bang DUNG duong production.

Du an duoc lap bang chinh nhung ham cua app — khong co ban ve phong ban:
  tao thu muc  → ui.home_page.create_project_folder  (nut "Tao du an moi")
  media       → ffmpeg lavfi sinh trong Assets/ cua du an (KHONG dung video
                cua nguoi dung: hop dong lam viec, rule 4)
  lap day     → core.commands (AddClip/ApplyEffect/SetGrading/SetClipText/
                SetClipAudio/SetTransition) day qua UndoStack that
  luu / mo lai→ core.project_storage.save_project_to_file + restore_model_from_clinq
  xuat        → ui.export_dialog.RenderWorker (FrameComposer + ffmpeg pipe)

Nam lan xuat tren CUNG mot bo clip, chi khac mot lop phu, de moi khoa do tach
duoc tung thu mot:
  goc          — khong hieu ung, khong chu, khong chuyen tiep
  khong_popart — bo HAI the Pop Art, van du chu + hoat anh + chuyen tiep + chinh
                 mau (hai khoa "the Pop Art doi anh" va "luoi 6 px" so voi ben nay)
  khong_grade  — Pop Art + chu + hoat anh + chuyen tiep, nhung bo bo chinh mau
  khong_chu    — dung nhu chuan tru clip chu (khoa "chu ve ra file" so voi ben nay)
  chuan        — du nhu du an trong file .clinq (san pham giao)

Moi khoa do anh/am thanh tinh tren FILE mp4 da giai ma, khong phai frame trong
bo nho: mot hieu ung bi rot roi luc encode van bi bat duoc.

  python -u scratch/popart_project_build.py
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")
EVIDENCE_PNG = os.path.join(OUT, "popart_project_evidence.png")
EVIDENCE_JSON = os.path.join(OUT, "popart_project_evidence.json")
MEASURES_JSON = os.path.join(OUT, "popart_project_measures.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from core import external_tools                                    # noqa: E402

FFMPEG = external_tools.require("ffmpeg")
FFPROBE = external_tools.require("ffprobe")

PROJECT_NAME = "Pop Art Demo"
W, H, FPS = 1280, 720, 24
DUR_A = DUR_B = 6.0
TRANSITION = ("Cross Dissolve", 0.5)
TIMESTAMPS = (2.5, 6.0, 9.0)
# Chu phai bao tron CA BA moc do (1.0 -> 11.0): khoa do lech vung chu lay
# min(chuan - khong_chu) nen mot moc roi ra khoi dong chu tinh lech bang 0.
TEXT_IN, TEXT_LEN = 1.0, 10.0
TEXT_BAND = (int(H * 0.30), int(H * 0.62))       # vung chu dung de dem pixel
# Nguong do TREN CHINH LAN XUAT 11/2026 (1280x720@24, 11,5 s, ba moc 2,5/6,0/
# 9,0 s), khong phai du doan: lech trong o 6px cua ban Pop Art tru ban bo the
# Pop Art dat min 44,1 / median 66,2 / max 130,7; do lech anh binh quan/pixel
# giua hai ban dat min 20,9; ty le pixel dai chu doi >30 don vi dat min 8,61%.
# Lay nguong khoang 1/2 den 1/3 so do de lan ngan (SHORT) van xanh.
LATTICE_MARGIN = 25.0
POPART_DIFF_MIN = 10.0
TEXT_FRAC_MIN = 3.0
REUSE = os.environ.get("CLINGING_POPART_REUSE") == "1"
# SHORT = ban do ngan dung RIENG cho phan chung (scratch/popart_project_
# counterfactual.py): 1 s/clip thay vi 6 s (du de do lech cua tung lop o ba moc
# do), media va .clinq nam trong scratch/, KHONG cham thu muc du an that cua
# nguoi dung va KHONG ghi vao MRU. Lan chang chinh van chay che do day du.
SHORT = os.environ.get("CLINGING_POPART_SHORT") == "1"
if SHORT:
    DUR_A = DUR_B = 1.0
    TRANSITION = ("Cross Dissolve", 0.4)
    # Clip chu PHAI ket trong pham vi co tieng (1,6 s): buoc ghep trong
    # ui/export_dialog.py:877 dung `-shortest`, nen chu chay qua sau clip audio
    # bi CAT DUOI im lang (do 21/10/2026: file ra 1,6 s trong khi model.duration
    # 1,9 s). Do la defect cua app, khong phai cua probe nen o day fixture ep
    # chu nam trong 1,5 s; ba moc do cung phai nam trong dai chu.
    TEXT_IN, TEXT_LEN = 0.2, 1.3
    TIMESTAMPS = (0.4, 0.9, 1.4)
    PROJECT_NAME = "Pop Art CF"
fails = []
measures = {}


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def above(label, got, limit):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-58s %s value=%.4f limit=%r"
          % (label, "PASS" if ok else "FAIL", got or -1, limit))
    return ok


def run(cmd, timeout=1800):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit("lenh that bai %r:\n%s"
                         % (cmd[:6], proc.stderr.decode("utf-8", "replace")[-900:]))
    return proc


# ── 1. thu muc du an + media tong hop ──────────────────────────

def make_project():
    from pathlib import Path
    from core import settings
    from ui.home_page import create_project_folder

    projects_dir = Path(OUT if SHORT else settings.get("project_dir"))
    if SHORT:
        projects_dir = projects_dir / "popart_cf"
        shutil.rmtree(projects_dir, ignore_errors=True)
        projects_dir.mkdir(parents=True, exist_ok=True)
    proj = create_project_folder(PROJECT_NAME, save_location=str(projects_dir),
                                 resolution=(W, H), fps=FPS, aspect_ratio="16:9")
    assets = proj / "Assets"
    src_a = assets / "fixture_gradient.mp4"
    src_b = assets / "fixture_pattern.mp4"
    lavfi = [
        (src_a, "gradients=s=%dx%d:d=%g:n=4:c0=0xFF2E63:c1=0x00C2FF:"
                "c2=0xFFD60A:c3=0x08F7A0:speed=0.06:r=%d" % (W, H, DUR_A, FPS), 320),
        (src_b, "testsrc2=s=%dx%d:d=%g:r=%d" % (W, H, DUR_B, FPS), 520),
    ]
    for path, video, tone in lavfi:
        if path.exists():
            os.remove(path)
        run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", video,
             "-f", "lavfi", "-i", "sine=frequency=%d:duration=%g" % (tone, DUR_A),
             "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", str(path)])
        # Nguong 20 000 chu khong phai 50 000: ban do ngan (SHORT) tung in ra
        # fixture 47 772 byte, nguong cu DO that vi x264 khong tat dinh. Kich
        # thuoc chi chung minh "khong phai vo", noi dung that do RMS + luoi do.
        above("fixture %s co dung luong" % path.name, os.path.getsize(path), 20000)
    return proj, str(proj / ("%s.clinq" % PROJECT_NAME)), str(src_a), str(src_b)


def register_in_mru(clinq):
    """Dung cach Trang chu dang lam khi tao du an an.

    Co ghi that: du an phai mo duoc tu Home thi moi la "du an" theo nghia
    nguoi dung hoi, khong phai mot file trong oc.
    """
    from ui.home_page import load_recent_projects, save_recent_projects
    projects = load_recent_projects()
    if clinq in projects:
        projects.remove(clinq)
    projects.insert(0, clinq)
    save_recent_projects(projects[:10])
    return clinq in load_recent_projects()


# ── 2. lap du an bang lenh that ────────────────────────────────

def build_model(src_a, src_b, pop_art=True, grading=True, anim=True,
                text=True, transition=True):
    from core.commands import (AddClipCommand, ApplyEffectCommand,
                               SetClipAudioCommand, SetClipTextCommand,
                               SetGradingCommand, SetTransitionCommand,
                               UndoStack)
    from core.timeline_model import TimelineModel, TrackType

    model = TimelineModel()
    model.project_ratio = "16:9"
    stack = UndoStack()
    track = model.add_track(TrackType.VIDEO, "Main", is_main_track=True)

    cmd_a = AddClipCommand(model, track.track_id, src_a, "video", 0.0, DUR_A, "fixture A")
    stack.push(cmd_a)
    clip_a = model.get_clip(cmd_a._clip_id)
    cmd_b = AddClipCommand(model, track.track_id, src_b, "video", DUR_A, DUR_B, "fixture B")
    stack.push(cmd_b)
    clip_b = model.get_clip(cmd_b._clip_id)

    if pop_art:
        for clip in (clip_a, clip_b):
            stack.push(ApplyEffectCommand(model, clip.clip_id, {
                "name": "Pop Art", "category": "Sắc thái",
                "icon": "fa6s.circle-dot"}))
    if grading:
        # Ca HAI clip deu bo chinh mau: that la mot du an pop art, va khoa do
        # "gain lam sang file" tinh median tren ca 3 moc do — neu chi gan len
        # clip A thi 2 moc roi sang clip B cho lech 0 va median tra ve 0,007.
        for clip in (clip_a, clip_b):
            stack.push(SetGradingCommand(model, clip.clip_id,
                                         {"hue_shift": 0.06, "gain": 1.10}))
    if anim:
        stack.push(ApplyEffectCommand(model, clip_b.clip_id, {
            "name": "Ken Burns Out", "category": "Hoạt ảnh",
            "icon": "fa6s.magnifying-glass-minus"}))
    if transition:
        stack.push(SetTransitionCommand(model, clip_b.clip_id, TRANSITION[0],
                                        TRANSITION[1]))
    stack.push(SetClipAudioCommand(model, clip_a.clip_id, volume=0.9, fade_in=0.5))
    stack.push(SetClipAudioCommand(model, clip_b.clip_id, volume=0.8, fade_out=0.5))

    text_id = None
    if text:
        text_track = model.add_track(TrackType.TEXT, "Text 1")
        cmd_t = AddClipCommand(model, text_track.track_id, "POP ART!", "text",
                               TEXT_IN, TEXT_LEN, "POP ART!")
        stack.push(cmd_t)
        text_id = cmd_t._clip_id
        clip_t = model.get_clip(text_id)
        from core.canvas_utils import calculate_fit_and_center
        layout = calculate_fit_and_center(400, 100, 1920, 1080)
        clip_t.transform.x = layout["x"]
        clip_t.transform.y = layout["y"]
        stack.push(SetClipTextCommand(
            model, text_id, name="POP ART!", font_family="Arial Black",
            font_size=96.0, font_bold=True, font_color="#FFD60A",
            text_style="outline", text_outline_color="#101010",
            text_outline_width=9.0, text_shadow_color="#FF2E63",
            text_shadow_dx=7.0, text_shadow_dy=7.0, text_shadow_blur=0.0,
            text_box_color="#00C2FF", text_box_alpha=0.30, text_box_radius=14.0,
            text_box_padding=26.0, text_align="center"))
    return model, {"a": clip_a.clip_id, "b": clip_b.clip_id, "text": text_id}


# ── 3. xuat bang RenderWorker ─────────────────────────────────

def peak_ws_kib():
    class C(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(C), wt.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wt.BOOL
    c = C()
    c.cb = ctypes.sizeof(c)
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise SystemExit("K32GetProcessMemoryInfo tra 0 — tem RAM hong")
    return int(c.PeakWorkingSetSize // 1024)


def render(model, out_path, label):
    from PySide6.QtWidgets import QApplication
    from ui.export_dialog import RenderWorker
    app = QApplication.instance() or QApplication([])          # noqa: F841
    if REUSE and os.path.exists(out_path):
        # Duong tat do nhanh khi chi sua mot khoa do luong. Lan chay chang chinh
        # PHAI chay voi REUSE tat: file mp4 deu do code hien tai sinh ra.
        # So do van tai cua lan xuat that, do MEASURES_JSON luu lai.
        print("   (tai dung %s — CLINGING_POPART_REUSE=1)" % os.path.basename(out_path))
        saved = json.load(open(MEASURES_JSON, encoding="utf-8")) if \
            os.path.exists(MEASURES_JSON) else {}
        measures.setdefault(label, {}).update(saved.get(label, {}))
        above("%s: file co dung luong" % label, os.path.getsize(out_path), 100000)
        return out_path
    for extra in (out_path, out_path + "_audio.mp3"):
        if os.path.exists(extra):
            os.remove(extra)
    worker = RenderWorker(model, out_path, W, H, FPS, "16:9", True)
    errors, done = [], []
    worker.errorOccurred.connect(errors.append)
    worker.finished_ok.connect(done.append)
    t0 = time.perf_counter()
    worker.run()
    dt = time.perf_counter() - t0
    check("%s: khong loi xuat" % label, bool(errors), False)
    check("%s: phoi finished_ok" % label, done, [out_path])
    n_frames = int(round(model.duration * FPS))
    measures[label] = {"s": round(dt, 2), "frames": n_frames,
                       "s_per_frame": round(dt / max(1, n_frames), 4),
                       "peak_ws_kib": peak_ws_kib()}
    print("   %s: %d frame trong %.1f s = %.3f s/frame, peak WS %d KiB"
          % (label, n_frames, dt, dt / max(1, n_frames), measures[label]["peak_ws_kib"]))
    above("%s: file co dung luong" % label, os.path.getsize(out_path), 40000)
    return out_path


# ── 4. do tren FILE ───────────────────────────────────────────

def probe_streams(path):
    proc = run([FFPROBE, "-v", "error", "-show_entries",
                "stream=codec_type,codec_name:format=duration", "-of", "json", path])
    data = json.loads(proc.stdout.decode("utf-8", "replace"))
    return ([s.get("codec_type") + ":" + str(s.get("codec_name"))
             for s in data.get("streams", [])],
            float(data.get("format", {}).get("duration", 0.0)))


def frame_at(path, t, png):
    run([FFMPEG, "-y", "-loglevel", "error", "-ss", "%.3f" % t, "-i", path,
         "-frames:v", "1", png])
    import cv2
    img = cv2.imread(png, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("khong giai ma duoc frame %s@%.1f" % (path, t))
    return img


def rms_of(path):
    import numpy as np
    wav = os.path.join(TMP, "rms_%d.wav" % (abs(hash(path)) % 100000))
    run([FFMPEG, "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "2",
         "-ar", "48000", "-c:a", "pcm_s16le", wav])
    import wave
    with wave.open(wav, "rb") as fh:
        n, ch, rate = fh.getnframes(), fh.getnchannels(), fh.getframerate()
        raw = fh.readframes(n)
    os.remove(wav)
    samples = np.frombuffer(raw, np.int16).astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(samples ** 2))), n / float(rate), ch


def lattice_range(bgr, cell=6):
    """Can nang trung binh tren o `cell` px, do o vung NGOAI dai chu.

    halftone_rgb in moi o bang HAI gia tri (muc = rgb*0,30+8, giay = rgb*1,06+26)
    nen o nao co cham lech nhau hang chuc don vi, trong khi gradient sau khi
    qua h264 chi lech vai don vi. Do tren vung khong chu vi net chu Arial Black
    96 re hon ca cham in, va lay max tren ca 36 lech pha vi FrameComposer co the
    doi le luoi so với goc anh.
    """
    import numpy as np
    lum = np.asarray(bgr, dtype=np.float64).mean(axis=2)
    lum = np.concatenate([lum[:TEXT_BAND[0]], lum[TEXT_BAND[1]:]], axis=0)
    best = 0.0
    for dy in range(cell):
        for dx in range(cell):
            hy = (lum.shape[0] - dy) // cell
            hx = (lum.shape[1] - dx) // cell
            if hy < 1 or hx < 1:
                continue
            blk = lum[dy:dy + hy * cell, dx:dx + hx * cell].reshape(
                hy, cell, hx, cell)
            best = max(best, float((blk.max(axis=(1, 3))
                                    - blk.min(axis=(1, 3))).mean()))
    return best


def changed_pixels(a, b):
    """% pixel trong dai chu doi > 30 don vi giua hai ban chi lech nhau clip chu."""
    import numpy as np
    ca = np.asarray(a, dtype=np.float64)[TEXT_BAND[0]:TEXT_BAND[1]]
    cb = np.asarray(b, dtype=np.float64)[TEXT_BAND[0]:TEXT_BAND[1]]
    d = np.abs(ca - cb).max(axis=2)
    return float((d > 30).mean() * 100.0)


def mean_luma(bgr):
    import numpy as np
    return float(np.asarray(bgr, dtype=np.float64).mean())


# ── 5. round-trip .clinq ──────────────────────────────────────

def roundtrip_gates(clinq, model):
    from core.project_storage import load_project_from_file, restore_model_from_clinq
    from core.timeline_model import TimelineModel
    revived = TimelineModel()
    project = load_project_from_file(clinq)
    check("mo lai: file giai duoc JSON", bool(project), True)
    restore_model_from_clinq(revived, project,
                             media_roots=[os.path.dirname(clinq)])

    def cards(clip):
        return sorted(e.name for e in clip.effects)

    src = {c.clip_id: c for t in model.tracks for c in t.clips}
    dst = {c.clip_id: c for t in revived.tracks for c in t.clips}
    check("mo lai: so clip guyen ven", len(dst), len(src))
    check("mo lai: so track guyen ven", len(revived.tracks), len(model.tracks))
    same_ids = set(src) == set(dst)
    check("mo lai: clip_id khong doi", same_ids, True)
    for cid, clip in src.items():
        got = dst.get(cid)
        if got is None:
            fails.append("mo lai: mat clip %s" % cid)
            continue
        check("mo lai: %s dung luong" % clip.name, round(got.duration, 3),
              round(clip.duration, 3))
        check("mo lai: %s dung hieu ung" % clip.name, cards(got), cards(clip))
        for field in ("volume", "speed", "fade_in", "fade_out"):
            if abs(getattr(clip, field) - getattr(got, field)) > 1e-6:
                fails.append("mo lai: %s.%s %r != %r"
                             % (clip.name, field, getattr(got, field), getattr(clip, field)))
        for field in ("text_style", "text_outline_color", "text_outline_width",
                      "text_shadow_dx", "text_box_alpha", "text_align",
                      "font_family", "font_size"):
            if getattr(clip, field) != getattr(got, field):
                fails.append("mo lai: %s.%s %r != %r"
                             % (clip.name, field, getattr(got, field), getattr(clip, field)))
        if getattr(clip, "transition", {}) and \
                got.transition.get("name") != clip.transition.get("name"):
            fails.append("mo lai: %s mat chuyen tiep" % clip.name)
    # Tim the card "Chinh mau" tren TOAN BO clip, khong phai clip dau tien:
    # add_track(TrackType.TEXT) xep track cho vao TRUOC main video (thuat toan
    # NLE overlay > main > audio), nen list(src)[0] la clip chu — khong bao gio
    # co the chinh mau va khoa do FAIL ma khong co loi nao trong file.
    graded = [e for c in dst.values() for e in c.effects if e.name == "Chinh mau"]
    check("mo lai: dung HAI the Chinh mau (ca hai clip)", len(graded), 2)
    check("mo lai: bo chinh mau con nguyen 5 khoa",
          sorted(graded[0].params) if graded else None,
          ["gain", "gamma", "hue_shift", "lift", "lut_path"])
    check("mo lai: gain van la 1.1", round(graded[0].params["gain"], 3) if graded else None, 1.1)
    paths = [c.source_path for c in dst.values() if c.media_type == "video"]
    check("mo lai: media dinh vi duoc ca hai clip",
          all(os.path.isfile(p) for p in paths) and len(paths), 2)
    if fails:
        print("  (round-trip co %d khoa FAIL)" % len([f for f in fails if f.startswith("mo lai")]))


# ── 6. anh chung minh ─────────────────────────────────────────

def write_evidence(grid, expected_dur):
    import cv2
    import numpy as np
    cols = ("goc", "khong_popart", "khong_grade", "khong_chu", "chuan")
    labels = ["goc", "bo the Pop Art", "bo chinh mau", "bo clip chu",
              "SAN PHAM (du .clinq)"]
    tile_w, tile_h = 256, 144
    band, gap, foot = 34, 6, 112
    sheet = np.full((band + len(TIMESTAMPS) * (tile_h + 20) + foot,
                     gap + len(cols) * (tile_w + gap), 3), 18, np.uint8)
    for c, text in enumerate(labels):
        cv2.putText(sheet, text, (gap + c * (tile_w + gap) + 4, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (238, 238, 238), 1, cv2.LINE_AA)
    for r, t in enumerate(TIMESTAMPS):
        y0 = band + r * (tile_h + 20)
        cv2.putText(sheet, "t = %.1f s (giai ma truc tiep tu mp4)" % t,
                    (gap, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (200, 200, 120), 1, cv2.LINE_AA)
        for c, name in enumerate(cols):
            tile = cv2.resize(grid[name][r], (tile_w, tile_h))
            sheet[y0 + 18:y0 + 18 + tile_h,
                  gap + c * (tile_w + gap):gap + c * (tile_w + gap) + tile_w] = tile
    m = measures.get("chuan", {})
    runs = ", ".join("%s %.1fs (%.3f s/frame)" % (k, measures[k]["s"],
                                                   measures[k]["s_per_frame"])
                     for k in cols if k in measures)
    lines = [
        "du an: %s   %dx%d@%d   %.2f s   2 clip video + 1 clip chu + 1 chuyen tiep"
        % (PROJECT_NAME, W, H, FPS, expected_dur),
        "xuat bang RenderWorker: %s" % runs,
        "peak working set luc xuat: %s KiB   RMS %.4f   do lech goc->chuan: %s"
        % (m.get("peak_ws_kib"), measures.get("rms", 0.0),
           measures.get("diff_goc_chuan")),
        "do lech Pop Art->chuan: %s (nguong %.1f)   margin luoi 6px %.2f (nguong %.1f)"
        % (measures.get("diff_popart_chuan"), POPART_DIFF_MIN,
           measures.get("lattice_margin", -1), LATTICE_MARGIN),
        "nang luong trong o 6px: chuan %s | bo Pop Art %s"
        % (measures.get("lattice_chuan"), measures.get("lattice_khong_popart")),
        "%% dai chu doi so voi ban bo chu: %s (nguong %.1f)   grading lift min %.2f"
        % (measures.get("text_changed_pct"), TEXT_FRAC_MIN,
           measures.get("grading_lift", -1.0)),
    ]
    for i, text in enumerate(lines):
        cv2.putText(sheet, text, (gap, sheet.shape[0] - 100 + i * 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (205, 205, 205), 1, cv2.LINE_AA)
    if not cv2.imwrite(EVIDENCE_PNG, sheet):
        raise SystemExit("khong ghi duoc anh bang chung")
    print("anh chung minh: %s (%d bytes, %dx%d)"
          % (EVIDENCE_PNG, os.path.getsize(EVIDENCE_PNG), sheet.shape[1], sheet.shape[0]))


# ── main ─────────────────────────────────────────────────────

TMP = os.path.join(OUT, "popart_cf_tmp" if SHORT else "popart_project_tmp")
EVIDENCE_PNG = os.path.join(OUT, "popart_cf_evidence.png" if SHORT else EVIDENCE_PNG)
EVIDENCE_JSON = os.path.join(OUT, "popart_cf_evidence.json" if SHORT
                             else EVIDENCE_JSON)
MEASURES_JSON = os.path.join(OUT, "popart_cf_measures.json" if SHORT
                             else MEASURES_JSON)


def main():
    if not REUSE:
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    print("== 1. tao thu muc du an + media tong hop ==")
    proj, clinq, src_a, src_b = make_project()
    check("du an: thu muc Assets/Cache/Exports ton tai",
          all(os.path.isdir(proj / d) for d in ("Assets", "Cache", "Exports")), True)
    check("du an: file .clinq do create_project_folder ghi ra",
          os.path.isfile(clinq), True)
    if SHORT:
        print("du an: BO qua dang ky MRU (che do SHORT khong cham du lieu nguoi dung)")
    else:
        check("du an: xuat hien trong danh sach gan day", register_in_mru(clinq), True)

    print("\n== 2. lap day bang lenh production ==")
    full, ids = build_model(src_a, src_b)
    check("model: 2 track (video + chu)", len(full.tracks), 2)
    check("model: 3 clip (2 video + 1 chu)",
          len([c for t in full.tracks for c in t.clips]), 3)
    expected_dur = full.duration
    print("   thoi luong du an: %.2f s (%d frame)" % (expected_dur,
                                                       int(round(expected_dur * FPS))))
    print("\n== 3. luu .clinq va mo lai ==")
    from core.project_storage import save_project_to_file
    ok = save_project_to_file(full, clinq, {
        "project_name": PROJECT_NAME, "resolution": {"width": W, "height": H},
        "fps": FPS, "aspect_ratio": "16:9"})
    check("luu: save_project_to_file tra True", ok, True)
    roundtrip_gates(clinq, full)

    print("\n== 4. nam lan xuat tren cung bo clip ==")
    # Mot lan xuat bo dung MOT lop, de moi khoa do duoi luoi chi do lop do:
    # goc = khong gi ca, khong_popart = bo hai the Pop Art, khong_grade = bo
    # chinh mau, khong_chu = bo clip chu, chuan = du nhu trong .clinq.
    base, _ids = build_model(src_a, src_b, pop_art=False, grading=False,
                             anim=False, text=False, transition=False)
    nopop, _i4 = build_model(src_a, src_b, pop_art=False)
    nograde, _i2 = build_model(src_a, src_b, grading=False)
    notext, _i3 = build_model(src_a, src_b, text=False)
    p_goc = render(base, os.path.join(TMP, "goc.mp4"), "goc")
    p_nop = render(nopop, os.path.join(TMP, "khong_popart.mp4"), "khong_popart")
    p_nog = render(nograde, os.path.join(TMP, "khong_grade.mp4"), "khong_grade")
    p_not = render(notext, os.path.join(TMP, "khong_chu.mp4"), "khong_chu")
    p_full = render(full, os.path.join(TMP, "chuan.mp4"), "chuan")

    # Chi phi tren may cau hinh thap: nguong la tran chon TU So DO, khong phai
    # du doan — hai lan chay day du tren cung bo clip 1280x720@24 cho 0,285 va
    # 0,519 s/frame (HDD + cache lens), 217-220 MiB peak. Lay 1,20 de lech doi
    # doi van xanh nhung tuong phat thanh thi do.
    # O che do ngan (SHORT, 38 frame) khoa nay VO NGHIA: tien khoi dong Qt +
    # bo giai ma + ffmpeg pipe khong kip amortize, do 21/10/2026 ra 0,626
    # s/frame trong khi cung bo clip day du chi 0,285. Chi in so do.
    if not SHORT:
        above("chi phi xuat: duong tren 1,20 s/frame",
              1.20 - measures["chuan"]["s_per_frame"], 0.0)
    above("chi phi RAM: peak working set du 400 MiB",
          400 * 1024 - measures["chuan"]["peak_ws_kib"], 0.0)
    print("   do that: %s" % ", ".join(
        "%s %.3f s/frame / peak %d KiB" % (k, measures[k]["s_per_frame"],
                                           measures[k]["peak_ws_kib"])
        for k in ("goc", "khong_popart", "khong_grade", "khong_chu", "chuan")
        if k in measures))
    print("   pop art + chu + hieu ung dat them %.2f s/frame so voi ban goc (%.3f)"
          % (measures["chuan"]["s_per_frame"] - measures["goc"]["s_per_frame"],
             measures["goc"]["s_per_frame"]))

    print("\n== 5. do tren FILE mp4 ==")
    codecs, dur = probe_streams(p_full)
    check("chuan co video h264", "video:h264" in codecs, True)
    check("chuan co audio aac", "audio:aac" in codecs, True)
    check("chuan: thoi luong file = thoi luong du an", round(dur, 1),
          round(expected_dur, 1))
    rms, secs, ch = rms_of(p_full)
    measures["rms"] = round(rms, 5)
    above("am thanh trong file > nguong im lang", rms, 0.005)
    check("file co 2 kenh am thanh", ch, 2)
    check("luong am thanh khong ngan hon file", abs(secs - dur) < 0.6, True)

    grid = {}
    for name, path in (("goc", p_goc), ("khong_popart", p_nop),
                       ("khong_grade", p_nog), ("khong_chu", p_not),
                       ("chuan", p_full)):
        grid[name] = [frame_at(path, t, os.path.join(TMP, "%s_%.1f.png" % (name, t)))
                      for t in TIMESTAMPS]

    import numpy as np

    def diff_rows(other):
        return [float(np.abs(a.astype(np.float64) - b.astype(np.float64)).mean())
                for a, b in zip(grid[other], grid["chuan"])]

    # So voi khong_popart (da co du chu, hoat anh, chuyen tiep, chinh mau), khong
    # phai voi goc: lech voi goc tron ca ba lop khac va van xanh khi the Pop Art
    # bi tat — do la mot khoa gia.
    diffs = diff_rows("khong_popart")
    measures["diff_popart_chuan"] = [round(d, 2) for d in diffs]
    measures["diff_goc_chuan"] = [round(d, 2) for d in diff_rows("goc")]
    above("the Pop Art doi anh sau khi encode (moi moc)", min(diffs),
          POPART_DIFF_MIN)

    # Posterize VA halftone KHONG do duoc bang "so mau doc lap trong file": do
    # lech do tren chinh cac file nay va ket luan nguoc — luong tu hoa 4 bit
    # tang tu [141, 855, 1126] len [1797, 2378, 2551], vi luoi cham Ben-Day ve
    # MUC va GIAY tu mau goc cua tung o (rgb*0.30+8 / rgb*1.06+26) va bo
    # resampler cua FrameComposer mo lai cac bac da nen. Nam 2026 thay nang
    # luong dai tan so 0,20-0,45 cua o 6px CUNG gia: ban bo the Pop Art (chu
    # Arial Black 96 net sach) dat 0,238-0,285 ngan ban co luoi cham
    # (0,256-0,275) vi net chu va net vien bang pop art re hon ca cham in.
    # Khoa do o day lay nang luong trong o 6px tren vung KHONG co chu, so voi
    # chinh ban bo the Pop Art, va tung lop duoc gate o don vi cua no:
    #   posterize + halftone + outline + contrast -> dong "phong cach pop art"
    #   trong main.py --selftest (diagnostics.py:1571 do 2/4/8 bac tren duoi
    #   mau 96 muc, do muc/giay theo do toi, do mang phang nguyen ven).
    lat_nop = [lattice_range(f) for f in grid["khong_popart"]]
    lat_full = [lattice_range(f) for f in grid["chuan"]]
    lat_goc = [lattice_range(f) for f in grid["goc"]]
    measures["lattice_khong_popart"] = [round(v, 2) for v in lat_nop]
    measures["lattice_chuan"] = [round(v, 2) for v in lat_full]
    measures["lattice_goc"] = [round(v, 2) for v in lat_goc]
    margin = min(a - b for a, b in zip(lat_full, lat_nop))
    measures["lattice_margin"] = round(margin, 2)
    above("luoi 6 px: o cua ban Pop Art lech trong o lon hon ban bo the Pop Art",
          margin, LATTICE_MARGIN)
    print("   nang luong trong o 6px: goc %s | bo Pop Art %s | chuan %s"
          % ([round(v, 1) for v in lat_goc], [round(v, 1) for v in lat_nop],
             [round(v, 1) for v in lat_full]))

    luma_g = [mean_luma(f) for f in grid["chuan"]]
    luma_n = [mean_luma(f) for f in grid["khong_grade"]]
    lift = min(a - b for a, b in zip(luma_g, luma_n))
    measures["grading_lift"] = round(lift, 3)
    above("bo chinh mau (gain 1.10) lam sang file sau khi encode", lift, 1.0)
    print("   luma chuan %s vs khong grade %s"
          % ([round(v, 1) for v in luma_g], [round(v, 1) for v in luma_n]))

    # Chu do lech voi chinh noi dung pop art khong co chu — khong so voi ban
    # goc, vi ban goc thieu ca hai lop va lech se tron chu voi luoi cham.
    # Dem theo TY LE pixel thay doi manh trong dai chu: dem "pixel toi" nhu
    # ban cu da do FAIL that (hop chu #00C2FF trong suot 30% LAM SANG vung nen
    # so pixel toi giam, 279242 -> 286540 o moc 6 s), nen no khong phai bang
    # chung cho "chu ve ra file".
    frac = [changed_pixels(a, b) for a, b in zip(grid["chuan"], grid["khong_chu"])]
    measures["text_changed_pct"] = [round(v, 2) for v in frac]
    above("chu ve ra file: dai chu doi > nguong o moi moc do", min(frac),
          TEXT_FRAC_MIN)
    print("   %% pixel dai chu doi >30 so voi ban bo chu: %s" % [round(v, 2) for v in frac])

    print("\n== 6. dong goi san pham ==")
    exports = proj / "Exports"
    deliverable = str(exports / "pop_art_demo.mp4")
    shutil.copyfile(p_full, deliverable)
    sidecar = p_full + "_audio.mp3"
    if os.path.exists(sidecar):
        shutil.copyfile(sidecar, str(exports / "pop_art_demo_audio.mp3"))
    again, again_dur = probe_streams(deliverable)
    check("file giao duoc mo voi 2 luong", len(again), 2)
    check("file giao giu nguyen thoi luong", round(again_dur, 1), round(dur, 1))

    write_evidence(grid, expected_dur)
    data = {"project": PROJECT_NAME, "clinq": clinq, "deliverable": deliverable,
            "expected_dur": round(expected_dur, 3), "measures": measures,
            "fails": fails}
    json.dump(data, open(EVIDENCE_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if not REUSE:
        # So do cua LAN XUAT THAT, de lan do lai (REUSE) van in du ra tran chi phi.
        json.dump({k: v for k, v in measures.items() if isinstance(v, dict)},
                  open(MEASURES_JSON, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    print("JSON:", EVIDENCE_JSON)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
