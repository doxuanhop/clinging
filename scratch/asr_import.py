"""Verify Import Subtitles: only the file picker is stubbed, the production
_import_subtitles body runs against a real .srt produced by the ASR engine.

Usage: python scratch/asr_import.py <subtitle file>
"""
import ctypes
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

import tkinter as tk
from PIL import Image
import main as appmod


def _raise_callback_errors(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _raise_callback_errors

SUB = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "scratch/e2c_Bcut.srt")
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")

shown = []
appmod.messagebox.showinfo = lambda *a, **k: shown.append(("info", a))
appmod.messagebox.showerror = lambda *a, **k: shown.append(("error", a))
appmod.messagebox.showwarning = lambda *a, **k: shown.append(("warn", a))
appmod.filedialog.askopenfilename = lambda *a, **k: SUB

app = appmod.ClingingApp({"id": "asrimport", "name": "asrimport", "clips": [
    {"file_path": VIDEO, "start_time": 0, "duration": 5, "clip_type": "video", "track_idx": 0},
]})


def run():
    before = len([c for c in app.timeline_clips if c.clip_type == "text"])
    app._import_subtitles()
    after = [c for c in app.timeline_clips if c.clip_type == "text"]
    print("text clips before/after:", before, len(after))
    for c in after[:3]:
        print("  %.2fs +%.2fs lane %d  %r" % (c.start_time, c.duration, c.track_idx,
                                              c.text_content[:24]))
    print("status:", app.top_status_lbl.cget("text"))
    for kind, args in shown:
        print("MESSAGEBOX[%s]: %s" % (kind, " | ".join(str(a) for a in args[1:]).replace("\n", " / ")))
    app.root.update_idletasks()
    app.root.update()

    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    from PIL import Image
    img = ImageGrab_window(hwnd)
    iw, ih = img.size
    img.crop((0, int(0.62 * ih), iw, ih)).save("scratch/asr_import_timeline.png")
    print("saved scratch/asr_import_timeline.png")
    app.root.destroy()


def ImageGrab_window(hwnd):
    import ctypes.wintypes
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


app.root.after(900, run)
app.root.mainloop()
