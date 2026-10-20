"""Capture the editor UI for visual verification.

Usage: python scratch/ui_shot.py <out.png> [video_tab] [crop]
Drives the real ClingingApp: loads a project with a video clip, selects it,
renders the requested video tab, then grabs the window pixels while mapped.
"""
import ctypes
import ctypes.wintypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must run before any GDI/PIL use: a DPI-unaware process gets virtualized
# window rects and the capture silently loses the right-hand column.
ctypes.windll.user32.SetProcessDPIAware()

from PIL import Image, ImageGrab

import main as appmod

# The app installs a handler that mangles tracebacks; surface real errors here.
import tkinter as tk
import traceback


def _raise_callback_errors(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _raise_callback_errors

VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
TAB = sys.argv[2] if len(sys.argv) > 2 else "Video"
CTYPE = sys.argv[4] if len(sys.argv) > 4 else "video"
CROP = {
    "full": None,
    "props": (0.74, 0.05, 1.0, 0.68),
    "propsfull": (0.74, 0.05, 1.0, 1.0),
    "sidebar": (0.0, 0.05, 0.11, 0.72),
    "rail": (0.0, 0.0, 0.08, 1.0),
    "top": (0.0, 0.0, 1.0, 0.09),
    "media": (0.06, 0.04, 0.34, 0.72),
    "player": (0.30, 0.04, 0.75, 0.72),
    "timeline": (0.06, 0.68, 1.0, 1.0),
}[sys.argv[3] if len(sys.argv) > 3 else "full"]


def select(app):
    # Seed a few extra library items so the media grid looks like the mockup.
    for extra in sorted(os.listdir(os.path.join(ROOT, "data", "thumbs")))[:4]:
        path = os.path.join(ROOT, "data", "thumbs", extra)
        if path not in app.media_files:
            app.media_files.append(path)
            app.media_types.append("image")
            app.generate_thumbnail(path)
    app.refresh_thumbnails()

    clip = app.timeline_clips[0]
    clip.clip_type = CTYPE
    app.selected_clips = [clip]
    app._selected_clip = clip if CTYPE == "text" else None  # exercise each panel branch
    app.update_properties_panel()
    if CTYPE == "video":
        app.on_video_tab_click(TAB)
    if len(sys.argv) > 5:  # scroll fraction, to reach the lower sections
        app.root.after(600, lambda: app.props_scrollable._parent_canvas.yview_moveto(float(sys.argv[5])))
    app.root.after(1400, lambda: capture(app))


def capture(app):
    app.root.update_idletasks()
    app.root.update()
    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    img = print_window(hwnd)
    if CROP:
        iw, ih = img.size
        img = img.crop(tuple(int(v) for v in
                             (CROP[0] * iw, CROP[1] * ih, CROP[2] * iw, CROP[3] * ih)))
    img.save(sys.argv[1])
    print("saved", sys.argv[1], img.size)
    app.root.destroy()


def print_window(hwnd):
    """Render the window into a bitmap so an occluded or off-screen window still captures."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
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
    user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT

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


app = appmod.ClingingApp({"id": "uicapture", "name": "uicapture", "clips": [
    {"file_path": VIDEO, "start_time": 0, "duration": 5, "clip_type": "video", "track_idx": 0},
]})
app.root.after(1200, lambda: select(app))
app.root.mainloop()
