"""Screenshot the properties panels whose help labels now use _props_wrap().

Usage: python scratch/props_wrap_shot.py
"""
import ctypes.wintypes
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

from PIL import Image

import main as appmod

SRC = os.path.join(ROOT, "scratch", "motion_still.mp4")
OUT = os.path.join(ROOT, "scratch")


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


def panel(app):
    hwnd = ctypes.windll.user32.FindWindowW(None, "Clinging - Video Editor")
    img = print_window(hwnd)
    left = img.width - 400
    return img.crop((max(0, left), 90, img.width, min(img.height, 700)))


def run(app):
    video = app.timeline_clips[0]
    app.selected_clips = [video]
    tiles = []
    for tab, renderer in (("Video/Adjust (placeholder)", lambda: (
                            setattr(app, "current_video_tab", "Adjust"),
                            app.render_video_tab_content())),
                          ("Video/Cut", lambda: (
                            setattr(app, "current_video_tab", "Cut"),
                            app.render_video_tab_content())),
                          ("Video/Logo Removal", lambda: (
                            setattr(app, "current_video_tab", "Logo Removal"),
                            app.render_video_tab_content())),
                          ("Text/Animation", lambda: (
                            setattr(app, "_selected_clip", app.timeline_clips[1]),
                            setattr(app, "current_text_tab", "Animation"),
                            app.update_properties_panel()))):
        renderer()
        app.root.update()
        app.root.update_idletasks()
        tiles.append((tab, panel(app)))
        print(tab, "wrap:", app._props_wrap())

    gap = 8
    w = max(t.width for _, t in tiles)
    h = sum(t.height for _, t in tiles) + gap * len(tiles) + 26 * len(tiles)
    sheet = Image.new("RGB", (w + gap, h), (12, 12, 16))
    y = 0
    for name, t in tiles:
        sheet.paste(t, (gap, y + 22))
        from PIL import ImageDraw, ImageFont
        ImageDraw.Draw(sheet).text((gap + 2, y + 4), name, fill=(150, 220, 255),
                                   font=ImageFont.truetype("arial.ttf", 15))
        y += 22 + t.height + gap
    path = os.path.join(OUT, "props_wrap_panels.png")
    sheet.save(path)
    print("saved", path, sheet.size)
    app.root.destroy()


app = appmod.ClingingApp({"id": "wrapshot", "name": "wrapshot", "clips": [
    {"file_path": SRC, "start_time": 0, "duration": 2, "clip_type": "video", "track_idx": 0},
]})
tc = appmod.TimelineClip("", 0.0, 2.0, "text", 1)
tc.text_content = "Chữ chạy trên video"
app.timeline_clips.append(tc)
app.root.after(900, lambda: run(app))
app.root.mainloop()
