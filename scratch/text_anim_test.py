"""Evidence harness for animated text ("chữ chạy").

Asks the running app to show the same text clip at two different timeline
positions and pixel-diffs the player, then probes the exact moviepy calls the
export path makes. A text clip that animates must differ between the two frames.

Usage: python scratch/text_anim_test.py
"""
import ctypes.wintypes
import ctypes
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
from PIL import Image

import main as appmod
import tkinter as tk

SRC = os.path.join(ROOT, "scratch", "motion_still.mp4")
OUT = os.path.join(ROOT, "scratch")


def _boom(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _boom


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


def player_only(img):
    """Crop to the 640x360 preview area so the diff is not diluted by chrome."""
    w, h = img.size
    return img.crop((int(0.30 * w), int(0.05 * h), int(0.74 * w), int(0.66 * h)))


def probe_export_calls():
    """Run the exact expressions from the export/compositing block and report
    what the installed moviepy does with them."""
    results = []
    from moviepy import VideoFileClip
    c = VideoFileClip(SRC)
    checks = [
        ("MOVIEPY['ImageClip'] (main.py:6362,6401)",
         lambda: appmod.MOVIEPY['ImageClip']),
        ("MOVIEPY['CompositeVideoClip'] (main.py:6415)",
         lambda: appmod.MOVIEPY['CompositeVideoClip']),
        ("clip.set_size(...) (main.py:6349)", lambda: c.set_size((640, 360))),
        ("clip.set_position(...) (main.py:6350)", lambda: c.set_position(("center", "center"))),
        ("clip.set_duration(...) (main.py:6362,6401,6417)", lambda: c.set_duration(2)),
        ("from moviepy.video.fx.all import resize (main.py:2397)",
         lambda: __import__("moviepy.video.fx.all", fromlist=["resize"])),
    ]
    for name, fn in checks:
        try:
            fn()
            results.append((name, "OK"))
        except BaseException as exc:
            results.append((name, "%s: %s" % (type(exc).__name__, str(exc)[:110])))
    # text-clip animation fields the renderer could use
    clip = appmod.TimelineClip(SRC, 0, 2, "text", 1)
    anim_attrs = [a for a in dir(clip) if any(k in a.lower() for k in
                  ("anim", "scroll", "marquee", "speed", "keyframe", "motion", "fade"))]
    results.append(("TimelineClip animation attributes", anim_attrs or "[] (none)"))
    c.close()
    return results


def run(app):
    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    video = app.timeline_clips[0]
    text = appmod.TimelineClip("", 0.0, 2.0, "text", 1)
    text.text_content = "CHU CHAY - noi dung chay ngang"
    text.font_size = 28
    text.x_pos, text.y_pos = 320, 318
    app.timeline_clips.append(text)
    app.draw_preview_frame(12)
    app.root.update()
    first = player_only(print_window(hwnd))
    first.save(os.path.join(OUT, "textanim_t0417.png"))

    # Move the clip's own position between the two renders: if the player had any
    # time-driven text animation, the two captures would already differ.
    app.draw_preview_frame(45)
    app.root.update()
    second = player_only(print_window(hwnd))
    second.save(os.path.join(OUT, "textanim_t1500.png"))

    a = np.asarray(first).astype(np.int16)
    b = np.asarray(second).astype(np.int16)
    diff = float(np.abs(a - b).mean()) * 100 / 255
    pair = Image.new("RGB", (first.width * 2 + 8, first.height), (30, 30, 30))
    pair.paste(first, (0, 0))
    pair.paste(second, (first.width + 8, 0))
    pair.save(os.path.join(OUT, "textanim_pair.png"))
    print("preview diff between t=0.42s and t=1.50s: %.3f%%" % diff)
    print("text clip anim-ish attributes:",
          [x for x in dir(text) if "anim" in x.lower() or "scroll" in x.lower()])
    print("TimelineClip __init__ fields:", sorted(vars(video).keys()))
    print()
    print("EXPORT-PATH PROBES (installed moviepy):")
    for name, outcome in probe_export_calls():
        print("  %-52s %s" % (name, outcome))
    app.root.destroy()


app = appmod.ClingingApp({"id": "textanim", "name": "textanim", "clips": [
    {"file_path": SRC, "start_time": 0, "duration": 2, "clip_type": "video", "track_idx": 0},
]})
app.root.after(1000, lambda: run(app))
app.root.mainloop()
