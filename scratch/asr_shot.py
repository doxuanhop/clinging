"""Evidence harness for the AsrTools auto-caption integration.

Drives the real production path (ClingingApp._run_asr / _asr_write / _asr_clips),
then writes two images: the main window with caption clips on the timeline, and
the Auto Captions dialog itself.

Usage: python scratch/asr_shot.py <out_prefix.png> [engine] [format]
"""
import ctypes
import ctypes.wintypes
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must run before any GDI/PIL use: a DPI-unaware process gets virtualized
# window rects and the capture silently loses the right-hand column.
ctypes.windll.user32.SetProcessDPIAware()

from PIL import Image

import main as appmod
import tkinter as tk


def _raise_callback_errors(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _raise_callback_errors

VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
ENGINE = sys.argv[2] if len(sys.argv) > 2 else "Bcut (Bilibili)"
FORMAT = sys.argv[3] if len(sys.argv) > 3 else "SRT"
PREFIX = sys.argv[1] if len(sys.argv) > 1 else "scratch/asr_shot"


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


def shot(img, path, crop=None):
    img.save(path)
    print("saved", path, img.size)
    if crop:
        iw, ih = img.size
        img.crop(tuple(int(v) for v in
                       (crop[0] * iw, crop[1] * ih, crop[2] * iw, crop[3] * ih))).save(
            path.replace(".png", "_crop.png"))
        print("saved", path.replace(".png", "_crop.png"))


def on_timeline(app, segments):
    clips = app._asr_clips(segments)
    print("caption clips:", len(clips))
    print("first:", clips[0].start_time, clips[0].duration, repr(clips[0].text_content))
    print("lane ids:", sorted({c.track_idx for c in app.timeline_clips}))
    app.root.update_idletasks()
    app.root.update()
    shot(print_window(ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")),
         PREFIX + "_timeline.png", crop=(0.0, 0.62, 1.0, 1.0))
    # preview should composite the caption over the video frame
    app.draw_preview_frame(int(clips[0].start_time * 30) + 1)
    app.root.update()
    shot(print_window(ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")),
         PREFIX + "_preview.png", crop=(0.28, 0.04, 0.76, 0.70))
    app._auto_captions()
    app.root.after(1200, lambda: finish(app))


def finish(app):
    dlg = ctypes.windll.user32.FindWindowW(None, "Auto Captions")
    if dlg:
        shot(print_window(dlg), PREFIX + "_dialog.png")
    else:
        print("ERROR: Auto Captions dialog window not found")
    app.root.destroy()


def worker(app):
    def report(pct, text):
        print("   progress %3d%%  %s" % (pct, text))

    if os.environ.get("ASR_FAKE"):
        # Exercises the same production write/clip/preview path with Vietnamese copy.
        segments = [
            {"text": "Xin chào, hôm nay chúng ta dựng video", "start_ms": 1200, "end_ms": 4200},
            {"text": "Cảnh thứ hai: thêm phụ đề tự động", "start_ms": 4600, "end_ms": 7800},
            {"text": "Nhấp Đúp để sửa cỡ chữ và vị trí", "start_ms": 8200, "end_ms": 11400},
        ]
        print("FAKE segments:", len(segments))
        app.root.after(0, lambda: on_timeline(app, segments))
        return

    try:
        segments = app._run_asr(VIDEO, ENGINE, "Auto", report)
        saved = app._asr_write(segments, VIDEO, FORMAT)
        print("engine:", ENGINE, "| segments:", len(segments), "| wrote:", saved)
        print("sample:", [s["text"][:16] for s in segments[:4]])
        app.root.after(0, lambda: on_timeline(app, segments))
    except BaseException as exc:
        print("ASR PIPELINE FAILED:", type(exc).__name__, exc)
        traceback.print_exc()
        app.root.after(0, lambda: on_timeline(app, [
            {"text": "offline fallback line one", "start_ms": 1200, "end_ms": 3400},
            {"text": "offline fallback line two", "start_ms": 4000, "end_ms": 6100},
            {"text": "offline fallback line three", "start_ms": 7000, "end_ms": 9200},
        ]))


import threading

app = appmod.ClingingApp({"id": "asrcapture", "name": "asrcapture", "clips": [
    {"file_path": VIDEO, "start_time": 0, "duration": 5, "clip_type": "video", "track_idx": 0},
]})
app.root.after(900, lambda: threading.Thread(target=worker, args=(app,), daemon=True).start())
app.root.mainloop()
