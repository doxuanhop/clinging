"""Open the Qt reference app's editor page with real media and capture it.

Usage: python scratch/qt_ref_editor.py
"""
import ctypes.wintypes
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "reference")
OUT = os.path.join(ROOT, "scratch")
sys.path.insert(0, REF)

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

from PIL import Image

import main as refmain  # noqa: E402  (applies the console-window patch)

from PySide6.QtWidgets import QApplication  # noqa: E402
from theme import theme_manager  # noqa: E402
from ui.main_controller import MainController  # noqa: E402

CLIP = os.path.join(ROOT, "scratch", "motion_src.mp4")
IMG = os.path.join(ROOT, "scratch", "anim_grid_text.png")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD)]


def grab(hwnd):
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
    ok = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(info), 0)
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1) if ok else None
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, dc)
    return img


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
    time.sleep(0.05)
    for _ in range(6):
        app.processEvents()
        time.sleep(0.15)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())
    c = MainController()
    c.show()
    pump(app, 2.0)
    hwnd = int(c.winId())

    c._on_create_project("Demo", os.path.join(OUT, "qt_ref_demo.clinq"))
    pump(app, 2.5)
    grab(hwnd).save(os.path.join(OUT, "qt_ref_editor_empty.png"))
    print("saved editor (empty)")

    editor = c.editor_page
    lib = editor.library_panel
    lib.add_resource(os.path.basename(CLIP), "video", CLIP)
    lib.add_resource(os.path.basename(IMG), "image", IMG)
    pump(app, 3.0)
    grab(hwnd).save(os.path.join(OUT, "qt_ref_editor_library.png"))
    print("saved editor (library populated)")

    print("library resources:", [r for r in getattr(lib, "resources", [])][:6]
          if hasattr(lib, "resources") else "n/a")

    # Drop the video onto the timeline through the model, the way a drop would.
    model = editor.timeline_panel.model
    print("model:", type(model).__name__)
    try:
        clips_before = len(model.get_clips()) if hasattr(model, "get_clips") else "?"
    except Exception as exc:
        clips_before = "err %s" % exc
    print("clips before:", clips_before)

    c.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
