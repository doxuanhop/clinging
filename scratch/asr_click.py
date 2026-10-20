"""Click the real Transcribe button in the Auto Captions dialog and verify the
whole worker-thread -> main-thread apply flow. Message boxes are recorded, not shown.

Usage: python scratch/asr_click.py <out_prefix.png> [engine]
"""
import ctypes
import ctypes.wintypes
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

from PIL import Image
import tkinter as tk
import customtkinter as ctk

import main as appmod


def _raise_callback_errors(_self, exc, val, tb):
    traceback.print_exception(exc, val, tb)
    raise val


tk.Tk.report_callback_exception = _raise_callback_errors

VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
ENGINE = sys.argv[2] if len(sys.argv) > 2 else "Bcut (Bilibili)"
PREFIX = sys.argv[1] if len(sys.argv) > 1 else "scratch/asr_click"

calls = []
appmod.messagebox.showinfo = lambda *a, **k: calls.append(("info", a))
appmod.messagebox.showerror = lambda *a, **k: calls.append(("error", a))
appmod.messagebox.showwarning = lambda *a, **k: calls.append(("warn", a))


def print_window(hwnd):
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


def find_buttons(widget, out):
    for child in widget.winfo_children():
        if isinstance(child, ctk.CTkButton):
            out.append(child)
        find_buttons(child, out)
    return out


def open_dialog(app):
    app._auto_captions()
    app.root.after(1400, lambda: click(app))


def click(app):
    dlg_hwnd = ctypes.windll.user32.FindWindowW(None, "Auto Captions")
    print("dialog hwnd:", dlg_hwnd)
    buttons = []
    for top in app.root.winfo_children():
        if isinstance(top, ctk.CTkToplevel):
            find_buttons(top, buttons)
    labels = [b.cget("text") for b in buttons]
    print("dialog buttons:", labels)
    run_btn = [b for b in buttons if b.cget("text") == "Transcribe"][0]
    run_btn.invoke()
    app.root.after(400, lambda: poll(app, 0))


def poll(app, tries):
    if calls:
        done(app)
        return
    if tries > 100:
        print("TIMEOUT: Transcribe never reported back")
        app.root.destroy()
        return
    app.root.after(300, lambda: poll(app, tries + 1))


def done(app):
    for kind, args in calls:
        print("MESSAGEBOX[%s]: %s" % (kind, " | ".join(str(a) for a in args[1:]).replace("\n", " / ")))
    clips = [c for c in app.timeline_clips if c.clip_type == "text"]
    print("text clips:", len(clips), "| lanes:", sorted({c.track_idx for c in app.timeline_clips}))
    print("first clip:", clips[0].start_time, clips[0].duration, repr(clips[0].text_content[:24]))
    app.draw_preview_frame(int(clips[0].start_time * 30) + 1)
    app.root.update_idletasks()
    app.root.update()
    shot = print_window(ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor"))
    shot.save(PREFIX + "_main.png")
    print("saved", PREFIX + "_main.png", shot.size)
    dlg = print_window(ctypes.windll.user32.FindWindowW(None, "Auto Captions"))
    dlg.save(PREFIX + "_dialog.png")
    print("saved", PREFIX + "_dialog.png", dlg.size)
    app.root.destroy()


app = appmod.ClingingApp({"id": "asrclick", "name": "asrclick", "clips": [
    {"file_path": VIDEO, "start_time": 0, "duration": 5, "clip_type": "video", "track_idx": 0},
]})
app.root.after(900, lambda: open_dialog(app))
app.root.mainloop()
