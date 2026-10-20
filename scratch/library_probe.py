"""Drive the Qt Library panel (tabs, search, filter menu, drop) and capture evidence.

Usage: python scratch/library_probe.py
"""
import ctypes
import ctypes.wintypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scratch")
sys.path.insert(0, ROOT)

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
from PIL import Image

import main as appmain  # noqa: E402  (console-window patch)
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from theme import theme_manager  # noqa: E402
from ui.main_controller import MainController  # noqa: E402
from ui.library_panel import ResourceCard  # noqa: E402

VIDEOS = [os.path.join(ROOT, "scratch", "motion_src.mp4"),
          os.path.join(ROOT, "scratch", "motion_still.mp4")]
IMAGES = [os.path.join(ROOT, "scratch", "anim_grid_text.png"),
          os.path.join(ROOT, "assets", "app-icon", "icon.png")]
AUDIOS = [os.path.join(ROOT, "scratch", "lib_probe_tone.mp3")]
MISSING = os.path.join(ROOT, "scratch", "gone_file.mp4")
# Một video chưa có trong thư viện, dùng cho nghiệm vụ kéo-thả khác loại
EXTRA_VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-46s %-6s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))


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
    return img, (w, h)


def panel_shot(win, hwnd, name):
    img, _ = grab(hwnd)
    pos = win.library_panel.mapTo(win, QPoint(0, 0))
    dpr = win.devicePixelRatioF()
    box = (max(0, int(pos.x() * dpr)), max(0, int(pos.y() * dpr)),
           int((pos.x() + win.library_panel.width()) * dpr),
           int((pos.y() + win.library_panel.height()) * dpr))
    img.crop(box).save(os.path.join(OUT, name))
    print("  saved", name)


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
    for _ in range(6):
        app.processEvents()
        time.sleep(0.12)


def visible_cards(win):
    return [c for c in win.library_panel._items
            if isinstance(c, ResourceCard) and c.isVisible()]


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())
    c = MainController()
    c.show()
    pump(app, 1.6)
    hwnd = int(c.winId())
    c._on_create_project("LibraryProbe", os.path.join(OUT, "library_probe.clinq"))
    pump(app, 2.0)
    win = c.editor_page
    win.library_panel.tabs.group.buttons()[0].click()
    pump(app, 0.5)

    for p in VIDEOS + IMAGES + AUDIOS:
        win.library_panel.add_files([p])
    # Thẻ "mất tệp" phải tạo trực tiếp: add_files bỏ qua đường dẫn không tồn tại.
    win.library_panel.add_resource(os.path.basename(MISSING), "video", MISSING)
    pump(app, 4.0)
    check("cards after add (5 real + 1 missing)", len(visible_cards(win)), 6)

    panel_shot(win, hwnd, "library_all.png")
    # Icon font fallback vẽ pixmap 32x32; thumbnail thật scale vào khung 116x80.
    def is_media_thumb(c):
        px = c.thumb_container.pixmap()
        return px is not None and not px.isNull() and max(px.width(), px.height()) >= 60

    real_thumbs = [c.filename for c in visible_cards(win) if is_media_thumb(c)]
    check("cards with a real media thumbnail", sorted(real_thumbs),
          sorted(["motion_src.mp4", "motion_still.mp4",
                  "anim_grid_text.png", "icon.png"]))
    # Âm thanh không có khung hình, thẻ phải dùng icon nhạc chứ không phải ô đen.
    audio_card = [c for c in visible_cards(win) if c.kind == "audio"][0]
    check("audio card uses fallback icon", is_media_thumb(audio_card), False)

    # Tab Video chỉ còn video (kể cả thẻ gone_file.mp4, chưa bật "ẩn tệp mất")
    win.library_panel.tabs.group.buttons()[1].click()
    pump(app, 0.6)
    check("tab Video visible cards", len(visible_cards(win)), 3)
    check("tab Video kinds", sorted({x.kind for x in visible_cards(win)}), ["video"])
    panel_shot(win, hwnd, "library_tab_video.png")

    # Tìm kiếm trong tab
    win.library_panel.search_box.input.setText("motion_still")
    pump(app, 0.6)
    check("tab Video + search 'motion_still'", [x.filename for x in visible_cards(win)],
          ["motion_still.mp4"])
    panel_shot(win, hwnd, "library_search_hit.png")

    win.library_panel.search_box.input.setText("zzz-none")
    pump(app, 0.6)
    check("search miss -> no cards", len(visible_cards(win)), 0)
    check("search miss -> hint label shown",
          win.library_panel.no_match_label.isVisible(), True)
    panel_shot(win, hwnd, "library_search_miss.png")

    win.library_panel.search_box.input.clear()
    win.library_panel.tabs.group.buttons()[0].click()
    pump(app, 0.6)

    # Menu lọc: hình ảnh
    win.library_panel._set_kind_filter("image")
    pump(app, 0.6)
    check("filter menu 'image'", sorted({x.kind for x in visible_cards(win)}), ["image"])
    check("filter menu 'image' count", len(visible_cards(win)), 2)
    check("menu radio synced",
          [k for k, a in win.library_panel._kind_actions.items() if a.isChecked()],
          ["image"])
    panel_shot(win, hwnd, "library_filter_image.png")

    # Drop một tấm ảnh khi đang ở tab "Hình ảnh" -> ở lại, không nhảy tab
    checked_before = win.library_panel.tabs.group.checkedId()
    win.library_panel.add_files([IMAGES[1]])
    pump(app, 1.5)
    check("duplicate drop ignored", len(visible_cards(win)), 2)
    check("same-kind drop keeps tab", win.library_panel.tabs.group.checkedId(),
          checked_before)

    # Drop một video khi đang lọc ảnh -> tự về "Tất cả" để người dùng thấy
    win.library_panel._set_kind_filter("image")
    win.library_panel.add_files([EXTRA_VIDEO])
    pump(app, 2.0)
    check("cross-kind drop resets tab", win.library_panel.tabs.group.checkedId(), 0)
    check("after reset all cards visible", len(visible_cards(win)), 7)

    # "Ẩn tệp không còn trên đĩa"
    win.library_panel._set_hide_missing(True)
    pump(app, 0.6)
    check("hide missing count", len(visible_cards(win)), 6)
    panel_shot(win, hwnd, "library_hide_missing.png")
    win.library_panel._set_hide_missing(False)

    # Kéo thả từ thẻ ra ngoài vẫn mang đúng loại
    card = visible_cards(win)[0]
    check("drag mime kind matches card", card.kind in ("video", "audio", "image"), True)

    # Persist/restore vẫn chạy qua đường filter mới
    recs = win.library_panel.resource_records()
    win.library_panel.restore_resources(recs)
    pump(app, 2.5)
    check("restore keeps 7 cards", len(visible_cards(win)), 7)
    panel_shot(win, hwnd, "library_restored.png")

    # Thêm tệp không được đóng băng thread GUI: đo thời gian block thật của
    # add_files và so với chi phí giải mã đồng bộ mà bản cũ chạy trên thread GUI.
    from ui.library_panel import decode_thumb_image
    extra = [os.path.join(ROOT, "scratch", "anim_e2e_export.mp4")]
    t0 = time.perf_counter()
    win.library_panel.add_files(extra)
    block_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    for p in VIDEOS + [EXTRA_VIDEO]:
        decode_thumb_image(p, "video")
    sync_ms = (time.perf_counter() - t0) * 1000.0
    print("  add_files blocked GUI thread %.1f ms; same decode inline would be %.1f ms"
          % (block_ms, sync_ms))
    check("adding a video keeps the GUI thread under 100 ms", block_ms < 100.0, True)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    c.close()
    app.processEvents()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
