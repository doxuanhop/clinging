"""Do bo cuc mac dinh: timeline chiem bao nhieu phan tram cua so.

So sanh trang thai trong (khong track) va luc da co track, kem anh capture
de mat nhin duoc ket qua, khong chi doc so.
"""
import ctypes
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QSplitter
from theme import theme_manager
from ui.main_window import MainWindow

FAILS = []


def check(label, got, want):
    ok = got == want
    print("%-52s %s  got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append(label)
    return ok


def pump(app, times=8):
    for _ in range(times):
        app.processEvents()


def grab(window, path):
    """PrintWindow toan bo cua so (memory: tooling-win-window-screenshot)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    from PIL import Image
    import ctypes.wintypes as wt
    hwnd = wt.HWND(int(window.winId()))
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    dc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(dc)
    bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)
    info = BIH()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    ok = gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    image = None
    if ok:
        image = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        image.save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, dc)
    return image


def report(window, tag, expect_ratio_pct):
    vs = next(s for s in window.findChildren(QSplitter)
              if s.orientation().name == "Vertical")
    sizes = vs.sizes()
    pct = 100.0 * sizes[1] / sum(sizes)
    tl = window.timeline_panel
    print("\n[%s] splitter sizes=%s -> timeline %.1f%%  (panel %dpx, min %d, header %d)"
          % (tag, sizes, pct, tl.height(), tl.minimumHeight(), tl.header.height()))
    print("      preview panel: %dpx" % window.preview_panel.height())
    near = abs(pct - expect_ratio_pct) <= 3.0
    print("%-52s %s  (%.1f%% vs muc tieu %.1f%%)"
          % ("%s: timeline ~%.0f%%" % (tag, expect_ratio_pct),
             "PASS" if near else "FAIL", pct, expect_ratio_pct))
    if not near:
        FAILS.append(tag + " ratio")
    return pct


def main():
    ctypes.windll.user32.SetProcessDPIAware()
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())
    win = MainWindow()
    win.resize(1920, 1035)
    win.show()
    pump(app)

    report(win, "empty", 30)
    image = grab(win, os.path.join(ROOT, "scratch", "timeline_default_empty.png"))
    check("co anh capture luc timeline trong", image is not None, True)

    # Them 3 track + clip de xem timeline co con giu duoc 30% va scroll duoc.
    model = win.timeline_panel.model
    from core.timeline_model import TrackType
    for i in range(3):
        track = model.add_track(TrackType.VIDEO)
        model.add_clip(track.track_id, "clip%d.mp4" % i, "video", i * 2.0, 2.0,
                       "clip%d" % i)
    pump(app)
    report(win, "3 tracks", 30)
    from core.timeline_model import TIMELINE_RULER_HEIGHT, TIMELINE_TRACK_GAP
    tl = win.timeline_panel
    needed = TIMELINE_RULER_HEIGHT + 20.0 + sum(
        t.height + TIMELINE_TRACK_GAP for t in model.tracks[:3])
    viewport = tl.view.viewport().height()
    bar = tl.view.verticalScrollBar()
    print("      3 hang can %.0fpx, viewport %dpx, scroll range %d"
          % (needed, viewport, bar.maximum()))
    check("3 track: hang thu 3 vua hoac cuon duoc toi",
          viewport >= needed or bar.maximum() > 0, True)
    image = grab(win, os.path.join(ROOT, "scratch", "timeline_default_tracks.png"))
    check("co anh capture luc co 3 track", image is not None, True)

    # Cua so thap: timeline khong duoc nuot gan het cho; no dung o min hop ly.
    win.resize(1400, 700)
    pump(app)
    tl = win.timeline_panel
    vs = next(s for s in win.findChildren(QSplitter)
              if s.orientation().name == "Vertical")
    sizes = vs.sizes()
    print("\n[1400x700] sizes=%s -> timeline %.1f%%, panel %dpx"
          % (sizes, 100.0 * sizes[1] / sum(sizes), tl.height()))
    check("o 1400x700 timeline dung bang min, khong bi phình",
          tl.height(), tl.minimumHeight())
    check("o 1400x700 preview van du 380px cao",
          win.preview_panel.height() >= 380, True)

    print("\n%s (%d fail)" % ("ALL PASS" if not FAILS else "FAILED: " + "; ".join(FAILS),
                              len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
