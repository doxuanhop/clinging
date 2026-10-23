r"""Anh chung minh "Bo cuc & Phong cach" — ve qua duong SAN XUAT.

Ba bang duoc dung boi `core.frame_composer.FrameComposer` voi trang thai do
CHINH `ui/canvas_layout_dialog.py` ghi xuong model (thay combo, bam nut "Dan
clip vao o" that), tuc la dung doan ve nen/tien canh ma ban xuat dung —
`paint_background` + `paint_foreground` nhu cong cua 30/31 cua report do.
Them mot lan chup THAT cua so hop thoai tren man hinh (qua
scratch/popart_window_shot.py), vi `widget.grab()` bo tron stylesheet nen khong
phai la thu nguoi dung nhin thay.

    python scratch/canvas_layout_evidence.py [bang.png [cua_so.png]]

Mac dinh: scratch/canvas_layout_evidence.png + scratch/canvas_layout_window.png.
In bang so va exit 1 neu bat ky o nao TRUNG mot digest: hai o giong het nhau
nghia la mot kieu o hoac mot chat lieu ve ra chang khac gi, va bang do mat gia
tri dan chung.

Ly do probe nay ton tai: `--canvas-layout-report` do bang CON SO (bg_px,
divider_px, texture_steps, header_px) ma con so khong cho thay thu nguoi dung
nhin thay. Vet da tra gia hom 22/10 o SplitDialog: duong do pixel XANH trong khi
dong lenh nam duoi fold — chi mo anh ra moi bat duoc.
"""

import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scratch"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
# So logic cua Qt == pixel thiet bi: cua so that do theo toa do man hinh.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

import numpy as np                                                 # noqa: E402
import popart_window_shot as shot                                  # noqa: E402
from PySide6.QtCore import QRect                                   # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter           # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

TW, TH = 640, 360           # kich thuoc mot o tren bang
LABEL_H = 26
PAD = 10
BAND_H = 34
WORK = os.path.join(tempfile.gettempdir(), "clinging_canvas_layout_evidence")

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r"
          % (label[:56], "PASS" if ok else "FAIL", got, want))


def above(label, got, limit):
    ok = float(got) > float(limit)
    if not ok:
        fails.append("%s: got %r khong lon hon %r" % (label, got, limit))
    print("%-56s %s value=%.4f limit=%r"
          % (label[:56], "PASS" if ok else "FAIL", got, limit))


def digest(image):
    """Chu ky byte cua mot o — hai o trung nhau la dieu khien do khong ve gi."""
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    row = img.bytesPerLine()
    return hashlib.sha256(bytes(img.constBits()[: row * img.height()])
                          ).hexdigest()[:12]


def px_of(image):
    """QImage -> (H, W, 3) int16 tren nen den, cung kieu do `rgb_of` trong report."""
    flat = QImage(image.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("#000000"))
    p = QPainter(flat)
    p.drawImage(0, 0, image)
    p.end()
    flat = flat.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    buf = flat.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    px = np.frombuffer(raw, np.uint8).reshape(
        (flat.height(), flat.bytesPerLine() // 4, 4))[:, :flat.width(), :3]
    return px[:, :, ::-1].astype(np.int16)


def count_color(px, hexcolor, tol=40):
    c = QColor(hexcolor)
    d = np.abs(px - np.array([c.red(), c.green(), c.blue()], np.int16))
    return int((d.max(axis=2) <= tol).sum())


def diff_pct(a, b):
    return round(100.0 * float((np.abs(a - b).max(axis=2) > 24).mean()), 2)


def main():
    from core import canvas_layout, project_storage
    from core.canvas_utils import ASPECT_RATIOS
    from core.frame_composer import FrameComposer
    from core.timeline_model import TrackType

    out_sheet = (sys.argv[1] if len(sys.argv) > 1 else
                 os.path.join(ROOT, "scratch", "canvas_layout_evidence.png"))
    out_window = (sys.argv[2] if len(sys.argv) > 2 else
                  os.path.join(ROOT, "scratch", "canvas_layout_window.png"))

    app = QApplication.instance() or QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(times=3):
        for _ in range(times):
            app.processEvents()
            time.sleep(0.03)

    # 4 anh fixture mau khac nhau, co khung + cham trang de lech ty le hoac vi
    # tri lo ra mat — khong dung anh cua nguoi dung (rang buoc 4).
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    stills = []
    for index in range(4):
        path = os.path.join(WORK, "still%d.png" % index)
        tile = QImage(640, 360, QImage.Format.Format_RGB32)
        tile.fill(QColor(40 + 55 * index, 90 + 40 * index, 210 - 35 * index))
        mark = QPainter(tile)
        mark.setPen(QColor(255, 255, 255))
        mark.drawRect(30, 24, 580, 312)
        mark.setBrush(QColor(255, 255, 255))
        mark.drawEllipse(300, 168, 40, 40)
        mark.end()
        if not tile.save(path, "PNG"):
            raise RuntimeError("khong ghi duoc fixture %s" % path)
        stills.append(path)

    # Probe mo MainWindow that nen keo theo thumbnail cua FIXTURE xuong cache
    # nguoi dung (vet 23/10 phia style-report): redirect cache + autosave +
    # recovery, van di qua DUNG duong ghi that, chi khac goc.
    cache_state = None
    real_autosave = project_storage.AUTO_SAVE_FILE
    real_recovery = project_storage.RECOVERY_DIR
    win = dialog = composer = None
    frames = []                       # QImage song den khi xong bang
    tiles_a, tiles_b, tiles_c = [], [], []
    window_img = second = bbox = None
    blank = None
    try:
        from diagnostics import _cache_guard_start
        cache_state = _cache_guard_start("canvas_layout_evidence")
        project_storage.AUTO_SAVE_FILE = os.path.join(WORK, "autosave.json")
        project_storage.RECOVERY_DIR = os.path.join(WORK, "recovery")

        from ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        timer = getattr(win, "_autosave_timer", None)
        if timer is not None:
            timer.stop()
        pump(12)

        model = win.timeline_panel.model
        for index, path in enumerate(stills):
            # TrackType.IMAGE: `track_accepts_media` tu choi "image" tren track
            # VIDEO, va track IMAGE khong tu hap nen ca bon clip cung nam o
            # [0, 4) — playhead 1,0 tinh ca bon la dang hien.
            track = model.add_track(TrackType.IMAGE, name="evidence %d" % index)
            clip = model.add_clip(track.track_id, path, "image", 0.0, 4.0,
                                  name="still%d" % index)
            if clip is None:
                raise RuntimeError("khong tao duoc clip fixture %d" % index)
        model.playhead = 1.0
        dialog = win._open_canvas_layout()
        pump(4)

        def set_field(key, value):
            """Ghi MOT khoa QUA WIDGET that de tin hieu `_apply` chay nhu bam."""
            if key == "enabled":
                dialog.chk_enabled.setChecked(bool(value))
            elif key == "layout":
                dialog.combo_layout.setCurrentIndex(
                    canvas_layout.LAYOUT_ORDER.index(value))
            elif key == "background_mode":
                dialog.combo_mode.setCurrentIndex(
                    canvas_layout.BACKGROUND_MODES.index(value))
            elif key == "texture":
                dialog.combo_texture.setCurrentIndex(
                    canvas_layout.TEXTURE_ORDER.index(value))
            elif key in ("header_font", "footer_font"):
                combo = (dialog.combo_header_font if key == "header_font"
                         else dialog.combo_footer_font)
                combo.setCurrentIndex(canvas_layout.FONT_FAMILIES.index(value))
            elif key in ("header_text", "footer_text"):
                (dialog.edit_header if key == "header_text"
                 else dialog.edit_footer).setText(value)
            elif key in ("header_size", "footer_size"):
                spin = (dialog.spin_header_size if key == "header_size"
                        else dialog.spin_footer_size)
                spin.setValue(int(value))
            elif key in ("auto_fit", "play_sequentially", "header_bold",
                         "footer_bold"):
                {"auto_fit": dialog.chk_auto_fit,
                 "play_sequentially": dialog.chk_sequential,
                 "header_bold": dialog.chk_header_bold,
                 "footer_bold": dialog.chk_footer_bold}[key].setChecked(
                    bool(value))
            elif key in ("background_color", "text_color", "frame_color"):
                # Duong cua nut chon mau: son button (tooltip la noi duy nhat
                # luu mau) roi Goi `_apply` — hop thoai khong co setter truc thai.
                dialog._paint_color_buttons(
                    dict(dialog._model.project_layout, **{key: value}))
                dialog._apply()
            else:
                raise RuntimeError("evidence khong co dieu khien cho %s" % key)
            pump(2)
            got = dialog._model.project_layout[key]
            if got != value:
                raise RuntimeError("widget %s ghi sai: %r != %r"
                                   % (key, got, value))

        def frame():
            img = composer.render_frame(model.playhead)
            frames.append(img)
            return img

        composer = FrameComposer(model, TW, TH)
        canvas_w, canvas_h = ASPECT_RATIOS.get(
            getattr(model, "project_ratio", "16:9"), (1920, 1080))

        # ── Bang A: 12 kieu bo cuc tren 4 clip dan bang nut that ──
        set_field("enabled", True)
        set_field("background_mode", "color")
        set_field("background_color", "#0B0B0F")
        set_field("layout", "none")
        dialog.btn_arrange.click()
        pump(3)
        tiles_a.append((frame(), "Khong bo cuc (tham chieu)", "none"))
        for key in canvas_layout.LAYOUT_ORDER:
            if key == "none":
                continue
            set_field("layout", key)
            dialog.btn_arrange.click()
            pump(3)
            boxes = canvas_layout.slots(canvas_w, canvas_h,
                                        model.project_layout)
            check("A %-20s: so o == bang kieu" % key[:20],
                  len(boxes), len(canvas_layout.LAYOUT_STYLES[key][2]))
            tiles_a.append((frame(), canvas_layout.LAYOUT_STYLES[key][0], key))

        # ── Bang B: 10 chat lieu nen, khung khong clip de net lo het ──
        # Khong the "doi choi" den luc het clip: `playhead.setter` Kep ve
        # `model._duration` (4,0) va `active_visual_clips_at(4,0)` TINH clip
        # dang hien (do truc tiep hom 23/10), nen cach duy nhat co mot khung
        # khong noi dung la XOA clip. Van dung model that, khong dung model moi.
        # Cua "so mau khac nhau >= 6" da bi bo: do 23/10 dem RGB that o 640x360
        # thi lined-paper 4 mau, dark 3, blueprint 5 — carbon #1F2229 nam trong
        # tol 40 cua nen #121317 va net mong bi tron khi ha tu 1920x1080. Cua
        # phan biet thuc su la digest (10 chat lieu -> 10 anh khac nhau) duoi
        # duoi, con 10 buoc ve khac nhau thi do bang `--canvas-layout-report`.
        for track in list(model.tracks):
            for clip in list(track.clips):
                model.remove_clip(clip.clip_id)
            if not track.clips:
                model.remove_track(track.track_id)
        check("B: khong con clip nao tren timeline",
              len([c for t in model.tracks for c in t.clips]), 0)
        pump(3)
        set_field("layout", "none")
        set_field("background_mode", "texture")
        for name in canvas_layout.TEXTURE_ORDER:
            set_field("texture", name)
            img = frame()
            px = px_of(img)
            base = canvas_layout.TEXTURES[name][1]
            tiles_b.append((img, canvas_layout.TEXTURES[name][0], name))
            above("B %-14s: pixel mau nen %s (%s)"
                  % (name, base, digest(img)),
                  count_color(px, base), 0.5 * TW * TH)

        # ── Bang C: hai vung chu + khoa nen den/mau ──────────────
        set_field("background_mode", "color")
        set_field("background_color", "#101820")
        set_field("text_color", "#FFD400")
        set_field("header_size", 64)
        set_field("header_bold", True)
        set_field("header_text", "")
        set_field("footer_text", "")
        blank = frame()
        tiles_c.append((blank, "(khong chu)", ""))
        head = canvas_layout.header_rect(canvas_w, canvas_h,
                                         model.project_layout)
        hx = [int(v * TW / float(canvas_w)) for v in head]
        for font in canvas_layout.FONT_FAMILIES:
            set_field("header_font", font)
            set_field("header_text", "Bo cuc %s" % font)
            img = frame()
            px = px_of(img)[hx[1]:hx[1] + hx[3], hx[0]:hx[0] + hx[2]]
            tiles_c.append((img, "chu dau %s / %s"
                            % (font, canvas_layout._font(font, 64, True)
                               .family()), font))
            above("C chu dau %-8s: mau chu trong vung > 400 px" % font,
                  count_color(px, "#FFD400"), 400)
        set_field("header_text", "")
        set_field("footer_font", "mono")
        set_field("footer_text", "chan trang")
        set_field("background_mode", "black")
        tiles_c.append((frame(), "chu cuoi tren nen den", ""))
        set_field("background_mode", "color")
        set_field("background_color", "#FF6A3D")
        tiles_c.append((frame(), "chu cuoi tren nen mau", ""))

        # ── Cua so that: chup CA MAN HINH, editor dang ve bo cuc ─
        # Anh nao vao docs phai la cua so THAT (AGENTS: anh commit la anh CHUP
        # THAT cua so editor, khong phai panel ghep nen toi), nen grab khung
        # MainWindow: preview dang ve manga-grid tren blueprint + chu dau, hop
        # thoai mo de len tren. Clip duoc NAP LAI qua model that vi mot khung
        # trong khong noi duoc tinh nang "dan clip vao o".
        set_field("footer_text", "")
        set_field("background_mode", "texture")
        set_field("texture", "blueprint")
        set_field("layout", "manga-grid")
        set_field("header_text", "Tuan 42")
        for index, path in enumerate(stills):
            track = model.add_track(TrackType.IMAGE, name="shot %d" % index)
            if model.add_clip(track.track_id, path, "image", 0.0, 4.0,
                              name="shot%d" % index) is None:
                raise RuntimeError("khong nap lai duoc clip %d" % index)
        model.playhead = 1.0
        dialog.btn_arrange.click()
        pump(8)
        sw, sh = shot.screen_size()
        user32 = ctypes.windll.user32
        user32.SetWindowPos(ctypes.c_void_p(int(win.winId())), None,
                            0, 0, sw, sh, 0x0040)
        pump(20)
        win_rect = shot.frame_bounds(int(win.winId()))
        win_bbox = (win_rect.left, win_rect.top, win_rect.right,
                    win_rect.bottom)
        before = None
        for _ in range(40):
            pump(4)
            cand = shot.grab_screen(win_rect)
            if shot.mean_luma(cand) > 8.0:
                before = cand
                break
        dialog.show()
        dialog.raise_()
        pump(10)
        dhwnd = int(dialog.winId())
        user32.SetWindowPos(ctypes.c_void_p(dhwnd), None, int(sw * 0.30),
                            int(sh * 0.10), max(dialog.width(), 720),
                            max(dialog.height(), 500), 0x0040)
        user32.BringWindowToTop(ctypes.c_void_p(dhwnd))
        pump(12)
        rect = shot.frame_bounds(dhwnd)
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        for _ in range(40):
            pump(4)
            cand = shot.grab_screen(win_rect)
            if shot.mean_luma(cand) > 8.0:
                window_img = cand
                break
        time.sleep(0.6)
        pump(15)
        second = shot.grab_screen(win_rect)
        dlg_box = (bbox[0] - win_bbox[0], bbox[1] - win_bbox[1],
                   bbox[2] - win_bbox[0], bbox[3] - win_bbox[1])

        # ── Ghep bang ────────────────────────────────────────────
        cols = (4, 5, 5)
        rows = [(len(tiles_a) + cols[0] - 1) // cols[0],
                (len(tiles_b) + cols[1] - 1) // cols[1],
                (len(tiles_c) + cols[2] - 1) // cols[2]]
        cell_w, cell_h = TW + PAD, TH + LABEL_H + PAD
        sheet = QImage(cols[1] * cell_w + PAD,
                       3 * BAND_H + sum(rows) * cell_h + 4 * PAD,
                       QImage.Format.Format_RGB32)
        sheet.fill(QColor("#0b0b0f"))
        painter = QPainter(sheet)
        band_font = QFont("Segoe UI", 13, QFont.Bold)
        tile_font = QFont("Segoe UI", 9)
        top = PAD
        for title, items, ncols, nrow in (
                ("A. 12 kieu bo cuc - 4 clip dan vao o qua nut that",
                 tiles_a, cols[0], rows[0]),
                ("B. 10 chat lieu nen (khung khong clip)", tiles_b, cols[1],
                 rows[1]),
                ("C. Vung chu dau/cuoi + khoa nen den/mau", tiles_c, cols[2],
                 rows[2])):
            painter.setFont(band_font)
            painter.setPen(QColor("#7FE8DC"))
            painter.drawText(PAD + 2, top + 22, title)
            top += BAND_H
            for i, (img, name, key) in enumerate(items):
                x = PAD + (i % ncols) * cell_w
                y = top + (i // ncols) * cell_h
                # Blit vao QRect theo kich thuoc THIET BI: drawImage(x, y, image)
                # o DPR>1 tu le anh ve 80% va an dau tru (vet hom 22/10).
                painter.drawImage(QRect(x, y, TW, TH), img)
                painter.setFont(tile_font)
                painter.setPen(QColor("#e8e8ee"))
                painter.drawText(x + 2, y + TH + 16,
                                 ("%s  [%s]" % (name, key)).strip())
            top += nrow * cell_h + PAD
        painter.end()
        if not sheet.save(out_sheet, "PNG"):
            raise RuntimeError("khong luu duoc bang chung")
        if window_img is not None:
            window_img.save(out_window)

        # ── Phan chung: moi o phai la mot hinh ───────────────────
        check("A: 13 o la 13 anh khac nhau",
              len({digest(t[0]) for t in tiles_a}), len(tiles_a))
        ref_px = px_of(tiles_a[0][0])
        for img, name, key in tiles_a[1:]:
            above("A %-24s lech voi tron khung (%%)" % key[:24],
                  diff_pct(px_of(img), ref_px), 0.05)
        check("B: 10 chat lieu la 10 anh khac nhau",
              len({digest(t[0]) for t in tiles_b}),
              len(canvas_layout.TEXTURE_ORDER))
        check("C: %d o chu la %d anh khac nhau" % (len(tiles_c), len(tiles_c)),
              len({digest(t[0]) for t in tiles_c}), len(tiles_c))
        blank_px = px_of(blank)
        for img, name, _k in tiles_c[1:]:
            above("C %-26s lech voi o khong chu (%%)" % name[:26],
                  diff_pct(px_of(img), blank_px), 0.02)
        check("W: lan chay co chup duoc cua so", window_img is not None, True)
        check("W: co frame sang TRUOC khi mo hop thoai", before is not None,
              True)
        if window_img is not None and before is not None:
            check("W: anh chup la KHUNG MAINWINDOW (khong phai widget tu ve)",
                  [window_img.width, window_img.height],
                  [win_rect.right - win_rect.left,
                   win_rect.bottom - win_rect.top])
            vp = win.preview_panel.canvas.viewport()
            a_pt = vp.mapToGlobal(vp.rect().topLeft())
            b_pt = vp.mapToGlobal(vp.rect().bottomRight())
            prev_box = (a_pt.x() - win_bbox[0], a_pt.y() - win_bbox[1],
                        b_pt.x() - win_bbox[0], b_pt.y() - win_bbox[1])
            prev = window_img.crop(prev_box)
            above("W: preview co noi dung (> 120 mau)", shot.n_colors(prev),
                  120)
            # Chat lieu phai nam trong vung preview: do la thu duy nhat phat
            # hien "hop thoai mo, model doi, ma khung van nguyen nen den".
            check("W: preview chua mau nen blueprint #123A6B",
                  sum(1 for p in prev.getdata()
                      if abs(p[0] - 0x12) < 40 and abs(p[1] - 0x3A) < 40
                      and abs(p[2] - 0x6B) < 40) > 2000, True)
            above("W: hop thoai duoc ve de len preview (lech > 5 %)",
                  shot.pct_moved(before.crop(dlg_box),
                                 window_img.crop(dlg_box)) - 5.0, 0.0)
            above("W: hai lan chup on dinh (1% - lech)",
                  1.0 - shot.pct_moved(window_img, second), 0.0)
    finally:
        extra = []
        if cache_state is not None:
            from diagnostics import _cache_guard_finish
            extra = _cache_guard_finish(cache_state)
        project_storage.AUTO_SAVE_FILE = real_autosave
        project_storage.RECOVERY_DIR = real_recovery
        if composer is not None:
            composer.close()
        # Dong CUA truoc khi ra lenh: mot cua song luc teardown la abort
        # 0xC0000409 va an toan bo stdout (vet hom 23/10).
        for widget in (dialog, win):
            if widget is not None:
                try:
                    widget.close()
                except Exception:
                    pass
        pump(4)
        shutil.rmtree(WORK, ignore_errors=True)
        check("H: khong them muc vao cache nguoi dung", extra, [])

    print("\nEVIDENCE_SHEET:", out_sheet, os.path.getsize(out_sheet), "B")
    if window_img is not None:
        print("EVIDENCE_WINDOW:", out_window, os.path.getsize(out_window), "B")
    print("RESULT:", "FAIL (%d)" % len(fails) if fails else "ALL PASS")
    for line in fails:
        print("  -", line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
