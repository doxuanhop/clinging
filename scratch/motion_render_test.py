"""Evidence for the Motion tab's "Render file" button.

Drives ClingingApp._render_motion_file (the button handler) for a few effects and
judges each produced file from its own frames: does it exist, does it change over
time, how far is it from the source.  Replaces the pre-rewrite motion_test.py.

Usage: python scratch/motion_render_test.py
"""
import ctypes
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import main as appmod
import tkinter as tk

SRC = os.path.join(ROOT, "scratch", "motion_still.mp4")
OUT_DIR = os.path.join(ROOT, "data", "video")
EFFECTS = ["zoom_in", "spin", "fade_in", "slide_left"]
TIMES = [0.05, 0.5, 1.0, 1.5, 1.95]

dialogs = []
state = {"done": None}


class Recorder:
    def showinfo(self, title, msg, *a, **k):
        return self("info", title, msg)

    def showwarning(self, title, msg, *a, **k):
        return self("warning", title, msg)

    def showerror(self, title, msg, *a, **k):
        return self("error", title, msg)

    def askyesno(self, title, msg, *a, **k):
        return self("askyesno", title, msg) or False

    def __call__(self, kind, title, msg):
        dialogs.append((kind, title, str(msg).replace("\n", " | ")))
        state["done"] = (kind, title)
        return "ok"


appmod.messagebox = Recorder()


def frames_of(path, norm=None):
    from moviepy import VideoFileClip
    clip = VideoFileClip(path)
    shape = tuple(clip.size)
    out = []
    try:
        for t in TIMES:
            if t < clip.duration:
                arr = np.asarray(clip.get_frame(t))
                if norm and (arr.shape[1], arr.shape[0]) != tuple(norm):
                    arr = np.array(Image.fromarray(arr).resize(
                        (int(norm[0]), int(norm[1])), Image.Resampling.LANCZOS))
                out.append(arr.astype(np.int16))
    finally:
        clip.close()
    return out, shape


def moved_pct(a, b):
    d = np.abs(b - a).max(axis=2)
    return round(float((d > 16).sum()) * 100.0 / (d.shape[0] * d.shape[1]), 3)


def wait(app, seconds=180):
    started = time.time()
    while state["done"] is None:
        app.root.update()
        if time.time() - started > seconds:
            return False
        time.sleep(0.05)
    return True


def run(app):
    clip = app.timeline_clips[0]
    app.selected_clips = [clip]
    app.render_motion_graphics_tab()
    app.root.update()

    src, src_shape = frames_of(SRC)
    print("source:", src_shape, "frames:", len(src))
    rows, results = [], []
    for effect in EFFECTS:
        out_path = os.path.join(OUT_DIR, "%s_motion_%s.mp4"
                                % (os.path.splitext(os.path.basename(SRC))[0], effect))
        if os.path.exists(out_path):
            os.remove(out_path)
        dialogs.clear()
        state["done"] = None
        clip.motion_effect = effect
        clip.motion_intensity = 6
        app._motion_effect_type.set(effect)
        app._render_motion_file()
        finished = wait(app)
        exists = os.path.exists(out_path)
        size = os.path.getsize(out_path) if exists else 0
        verdict, peak = "no output file", 0.0
        if exists:
            try:
                mf, mshape = frames_of(out_path, norm=src_shape)
                peak = max(moved_pct(mf[i], mf[i + 1]) for i in range(len(mf) - 1))
                verdict = "ANIMATED" if peak > 0.05 else "STATIC OUTPUT"
                rows.append([Image.fromarray(np.uint8(f)) for f in mf])
            except BaseException as exc:
                verdict = "unreadable: %s" % type(exc).__name__
        print("%-10s out=%-5s bytes=%-8s peak_move=%-7s %-14s %s"
              % (effect, exists, size, peak, verdict,
                 " / ".join(t for _, t, _ in dialogs) or "-"), flush=True)
        results.append((effect, exists, size, peak, verdict))

    # "none" must refuse to render, and no selection must warn.
    dialogs.clear()
    state["done"] = None
    clip.motion_effect = "none"
    app._render_motion_file()
    wait(app, 20)
    print("render with effect=none dialogs:", dialogs)
    none_dialogs = list(dialogs)

    dialogs.clear()
    state["done"] = None
    app.selected_clips = []
    app._render_motion_file()
    wait(app, 20)
    print("render with no selection dialogs:", dialogs)
    empty_dialogs = list(dialogs)

    if rows:
        font = ImageFont.truetype("arial.ttf", 14)
        cols = len(rows[0])
        tw, th = rows[0][0].size
        sheet = Image.new("RGB", (150 + (tw + 6) * cols, (th + 24) * len(rows) + 6),
                          (14, 14, 18))
        d = ImageDraw.Draw(sheet)
        y = 3
        for (effect, _e, _s, _p, _v), tiles in zip(results, rows):
            if len(tiles) != cols:
                continue
            d.text((6, y + th // 2 - 7), effect, fill=(235, 235, 235), font=font)
            x = 150
            for i, t in enumerate(tiles):
                sheet.paste(t, (x, y))
                d.text((x + 2, y + th + 5), "t=%.2f" % TIMES[i], fill=(150, 150, 160), font=font)
                x += tw + 6
            y += th + 24
        path = os.path.join(ROOT, "scratch", "motion_render_strip.png")
        sheet.save(path)
        print("saved", path, sheet.size)

    ok = [r for r in results if r[1] and r[3] > 0.05]
    print("\nGATE 4 render-file produced animated files: %d/%d" % (len(ok), len(results)))
    for r in results:
        if r not in ok:
            print("   FAIL", r)
    print("GATE 5 'none' refuses instead of writing:",
          any(k == "info" for k, _, _ in none_dialogs))
    print("GATE 6 empty selection warns:", any(k == "warning" for k, _, _ in empty_dialogs))

    for effect in EFFECTS:
        p = os.path.join(OUT_DIR, "%s_motion_%s.mp4"
                         % (os.path.splitext(os.path.basename(SRC))[0], effect))
        if os.path.exists(p):
            os.remove(p)
    print("cleaned generated files from data/video")
    app.root.destroy()


def _boom(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _boom

app = appmod.ClingingApp({"id": "motionrender", "name": "motionrender", "clips": [
    {"file_path": SRC, "start_time": 0, "duration": 2, "clip_type": "video", "track_idx": 0},
]})
app.root.after(1000, lambda: run(app))
app.root.mainloop()
