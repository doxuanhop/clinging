"""End-to-end evidence for the animation work.

Checks three things through the production paths: the player really animates a
clip for every motion effect, the Motion and Text Animation panels build without
errors, and the exported file matches the player frame-for-frame at the same
timestamps.

Usage: python scratch/anim_e2e.py
"""
import ctypes.wintypes
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
OUT = os.path.join(ROOT, "scratch")
EXPORT = os.path.join(ROOT, "scratch", "anim_e2e_export.mp4")
TIMES = [0.0, 0.4, 0.8, 1.2, 1.6]
FPS = 30.0
MOTION_CASES = ["zoom_in", "slide_left", "fade_in", "spin", "bounce", "pulse"]
TEXT_CASES = ["scroll_left", "typewriter", "roll_up", "wave"]

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


def print_window(hwnd):
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.wintypes.WORD),
                    ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                    ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
                    ("biClrImportant", ctypes.wintypes.DWORD)]

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(dc)
    bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    user32.PrintWindow(hwnd, mem_dc, 2)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, dc)
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


def moved_pct(a, b):
    """Fraction of pixels that visibly changed between two frames."""
    d = np.abs(np.asarray(b.convert("RGB"), dtype=np.int16) -
               np.asarray(a.convert("RGB"), dtype=np.int16)).max(axis=2)
    return round(float((d > 16).sum()) * 100.0 / (d.shape[0] * d.shape[1]), 3)


def mean_diff(a, b):
    return round(float(np.abs(np.asarray(a.convert("RGB"), dtype=np.int16) -
                              np.asarray(b.convert("RGB"), dtype=np.int16)).mean()), 3)


def player_frames(app, times):
    out = []
    for t in times:
        app.draw_preview_frame(int(round(t * FPS)))
        app.root.update()
        out.append(app._last_preview_pil.convert("RGB").copy())
    return out


def sheet(rows, path, title):
    font = ImageFont.truetype("arial.ttf", 15)
    small = ImageFont.truetype("arial.ttf", 12)
    cols = len(rows[0][1])
    tile_w, tile_h = rows[0][1][0].size
    label_w, pad = 210, 6
    img = Image.new("RGB", (label_w + (tile_w + pad) * cols + pad,
                            30 + (tile_h + 22 + pad) * len(rows)), (16, 16, 20))
    d = ImageDraw.Draw(img)
    d.text((8, 7), title, fill=(150, 220, 255), font=font)
    y = 26
    for name, frames, notes in rows:
        d.text((8, y + tile_h // 2 - 8), name, fill=(235, 235, 235), font=small)
        x = label_w
        for i, f in enumerate(frames):
            img.paste(f, (x, y))
            d.text((x + 2, y + tile_h + 4), notes[i], fill=(150, 150, 160), font=small)
            x += tile_w + pad
        y += tile_h + 22 + pad
    img.save(path)
    print("saved", path, img.size)


def file_frames(path, times, size):
    from moviepy import VideoFileClip
    clip = VideoFileClip(path)
    frames = []
    try:
        for t in times:
            frames.append(Image.fromarray(np.asarray(clip.get_frame(min(t, clip.duration - 0.01))))
                          .convert("RGB").resize(size))
    finally:
        clip.close()
    return frames


def run_motion_tab(app, video_clip):
    app.selected_clips = [video_clip]
    app.current_video_tab = "Motion"
    app.render_video_tab_content()
    app.root.update()
    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    print_window(hwnd).save(os.path.join(OUT, "anim_ui_motion.png"))

    rows, results = [], []
    for effect in MOTION_CASES:
        app._motion_effect_type.set(effect)
        app._on_motion_choice()
        frames = player_frames(app, TIMES)
        steps = [moved_pct(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
        results.append((effect, max(steps)))
        rows.append(("player  %s" % effect, frames, ["d=%s" % s for s in ["-"] + steps]))
    return rows, results


def run_text_tab(app, text_clip):
    app._selected_clip = text_clip
    app.current_text_tab = "Animation"
    app.update_properties_panel()
    app.root.update()
    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    print_window(hwnd).save(os.path.join(OUT, "anim_ui_textanim.png"))

    rows, results = [], []
    for effect in TEXT_CASES:
        # Rebuild the panel so the widgets under test are the real ones, then use
        # the same handler a radio click would fire.
        text_clip.text_effect = effect
        app.update_properties_panel()
        app.root.update()
        app._text_effect_type.set(effect)
        app._on_text_choice()
        frames = player_frames(app, TIMES)
        steps = [moved_pct(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
        results.append(("text:" + effect, max(steps)))
        rows.append(("player  text %s" % effect, frames, ["d=%s" % s for s in ["-"] + steps]))
    return rows, results


def run(app):
    video = app.timeline_clips[0]
    text = app.timeline_clips[1]
    motion_rows, motion_results = run_motion_tab(app, video)
    text_rows, text_results = run_text_tab(app, text)

    # Export the same timeline the player just showed: Ken Burns on the clip and
    # a marquee caption, so both effect families land in the file.
    video.motion_effect = "zoom_in"
    video.motion_intensity = 8
    text.text_effect = "scroll_left"
    text.text_intensity = 5
    if os.path.exists(EXPORT):
        os.remove(EXPORT)
    state["done"] = None
    dialogs.clear()
    app._render_clips_to_file(app.timeline_clips, EXPORT, size=(640, 360), fps=12)
    started = time.time()
    while state["done"] is None:
        app.root.update()
        if time.time() - started > 240:
            print("EXPORT TIMED OUT")
            break
        time.sleep(0.05)
    print("export dialogs:", dialogs)
    print("export file exists:", os.path.exists(EXPORT),
          os.path.getsize(EXPORT) if os.path.exists(EXPORT) else 0)

    parity = []
    if os.path.exists(EXPORT):
        video.motion_effect = "zoom_in"
        text.text_effect = "scroll_left"
        player = player_frames(app, TIMES)
        rendered = file_frames(EXPORT, TIMES, player[0].size)
        for i, t in enumerate(TIMES):
            parity.append((t, mean_diff(player[i], rendered[i])))
        worst = max(p[1] for p in parity)
        print("preview vs export mean abs diff per timestamp:", parity)
        print("worst diff:", worst, "(0-8 expected: encoder loss only)")
        sheet([("player", player, ["t=%.1f" % t for t in TIMES]),
               ("exported file", rendered, ["t=%.1f" % t for t in TIMES])],
              os.path.join(OUT, "anim_preview_vs_export.png"),
              "Same timeline through the player and through the exporter")

    all_rows = motion_rows + text_rows
    sheet(all_rows, os.path.join(OUT, "anim_player_cases.png"),
          "Player captures - motion effects then text effects")

    failures = [name for name, peak in motion_results + text_results if peak <= 0.05]
    print("\nGATE 1 player animates: %d/%d cases moved" %
          (len(motion_results + text_results) - len(failures),
           len(motion_results + text_results)))
    for name in failures:
        print("   FAIL", name)
    gate2 = os.path.exists(EXPORT) and os.path.getsize(EXPORT) > 20000
    print("GATE 2 export produced a real file:", gate2)
    gate3 = not any(k == "error" for k, _, _ in dialogs)
    print("GATE 3 no error dialog during export:", gate3)
    app.root.destroy()


def _boom(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _boom

app = appmod.ClingingApp({"id": "anime2e", "name": "anime2e", "clips": [
    {"file_path": SRC, "start_time": 0, "duration": 2, "clip_type": "video", "track_idx": 0},
]})
text_clip = appmod.TimelineClip("", 0.0, 2.0, "text", 1)
text_clip.text_content = "Chữ chạy trên video"
text_clip.font_size = 30
text_clip.x_pos, text_clip.y_pos = 320, 300
text_clip.text_effect = "scroll_left"
app.timeline_clips.append(text_clip)
app.root.after(1000, lambda: run(app))
app.root.mainloop()
