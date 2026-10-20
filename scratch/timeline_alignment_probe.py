"""Do lech hang track: Track Header (view trai) vs Lane (body phai).

Nguoi dung bao "phai thang hang nhau". Probe nay khong do bang loi van; no
map top cua lane body va top cua header item cung mot track ra toa do toan
cua so roi so sanh, kem anh capture.
"""
import ctypes
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication

from theme import theme_manager
from ui.main_window import MainWindow
from core.timeline_model import TrackType

FAILS = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s  got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append(label)
    return ok


def pump(app, times=10):
    for _ in range(times):
        app.processEvents()


def grab(window, path):
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
    image = None
    if gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0):
        image = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        image.save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, dc)
    return image


def tops(tl, track_id):
    """(global_y_body, global_y_header, chi tiết) cho một track."""
    lane = tl.scene._track_lanes[track_id]
    item = tl.header_scene._header_items[track_id]

    lane_scene_y = lane.pos().y() + lane.rect().y()
    item_scene_y = item.pos().y() + item.rect().y()

    lane_vp = tl.view.mapFromScene(QPointF(0.0, lane_scene_y))
    item_vp = tl.header_view.mapFromScene(QPointF(0.0, item_scene_y))

    lane_glob = tl.view.mapToGlobal(QPoint(int(round(lane_vp.x())),
                                           int(round(lane_vp.y()))))
    item_glob = tl.header_view.mapToGlobal(QPoint(int(round(item_vp.x())),
                                                  int(round(item_vp.y()))))
    return lane_glob.y(), item_glob.y(), {
        "lane_scene_y": lane_scene_y, "item_scene_y": item_scene_y,
        "lane_vp_y": lane_vp.y(), "item_vp_y": item_vp.y(),
        "lane_h": lane.rect().height(), "item_h": item.rect().height(),
    }


def scenario(app, win, label, n_tracks):
    tl = win.timeline_panel
    model = tl.model
    print("\n=== %s ===" % label)
    print("    scene rect      %s" % (tl.scene.sceneRect(),))
    print("    header rect     %s" % (tl.header_scene.sceneRect(),))
    print("    body viewport   %dx%d  scroll v=%d max=%d  align=%s"
          % (tl.view.viewport().width(), tl.view.viewport().height(),
             tl.view.verticalScrollBar().value(),
             tl.view.verticalScrollBar().maximum(), tl.view.alignment()))
    print("    hdr  viewport   %dx%d  scroll v=%d max=%d  align=%s"
          % (tl.header_view.viewport().width(),
             tl.header_view.viewport().height(),
             tl.header_view.verticalScrollBar().value(),
             tl.header_view.verticalScrollBar().maximum(),
             tl.header_view.alignment()))
    print("    TRACK_TOP_PADDING body=%.1f header=%.1f"
          % (tl.scene.TRACK_TOP_PADDING, tl.header_scene.TRACK_TOP_PADDING))
    worst = 0
    for track in model.tracks:
        body_y, hdr_y, detail = tops(tl, track.track_id)
        diff = body_y - hdr_y
        worst = max(worst, abs(diff))
        print("    %-18s body_global=%4d header_global=%4d diff=%+4d  h %.0f/%.0f"
              % (track.name[:18], body_y, hdr_y, diff,
                 detail["lane_h"], detail["item_h"]))
    check("%s: header va body lech nhau 0px" % label, worst <= 1, True)
    return worst


def main():
    ctypes.windll.user32.SetProcessDPIAware()
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())
    win = MainWindow()
    win.resize(1920, 1035)
    win.show()
    pump(app)

    tl = win.timeline_panel
    model = tl.model
    print("tracks mac dinh cua model: %s" % [t.name for t in model.tracks])

    # 1) Mot track video co clip - dung nhu hinh nguoi dung.
    main_track = next((t for t in model.tracks if t.is_main_track), None)
    if main_track is None:
        main_track = model.add_track(TrackType.VIDEO, is_main_track=True)
    model.add_clip(main_track.track_id, "Recording.mp4", "video", 0.0, 4.8,
                   "Recording")
    pump(app)
    scenario(app, win, "1 track", 1)
    image = grab(win, os.path.join(ROOT, "scratch", "align_1track.png"))
    check("co anh capture 1 track", image is not None, True)

    # 2) Ba track - truong hop overflow + scroll.
    for i in range(2):
        track = model.add_track(TrackType.VIDEO)
        model.add_clip(track.track_id, "extra%d.mp4" % i, "video",
                       i * 1.5, 1.5, "extra%d" % i)
    pump(app)
    scenario(app, win, "3 track", 3)
    image = grab(win, os.path.join(ROOT, "scratch", "align_3track.png"))
    check("co anh capture 3 track", image is not None, True)

    # 3) Cuon body den cuoi - header phai di theo.
    bar = tl.view.verticalScrollBar()
    print("\nscroll range body = %d" % bar.maximum())
    if bar.maximum() > 0:
        bar.setValue(bar.maximum())
        pump(app)
        scenario(app, win, "3 track, cuon toi day", 3)
        image = grab(win, os.path.join(ROOT, "scratch", "align_scrolled.png"))
        check("co anh capture khi da cuon", image is not None, True)
    else:
        print("    (khong co range cuon - bo qua buoc 3)")

    # 4) Cuon giữa + đổi kích thước: padding và range phải được tính lại
    #    giống nhau cho cả hai scene, không riêng lúc khởi động.
    if bar.maximum() > 2:
        bar.setValue(bar.maximum() // 2)
        pump(app)
        scenario(app, win, "3 track, cuon giữa", 3)

    win.resize(1400, 760)
    pump(app, 14)
    scenario(app, win, "3 track sau khi doi kich thuoc cua so", 3)
    image = grab(win, os.path.join(ROOT, "scratch", "align_resized.png"))
    check("co anh capture sau khi doi kich thuoc", image is not None, True)

    print("\n%s (%d fail)" % ("ALL PASS" if not FAILS else "FAILED: " + "; ".join(FAILS),
                              len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
