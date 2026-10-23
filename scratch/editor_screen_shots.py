"""scratch/editor_screen_shots.py

Bon anh CHUP TREN MAN HINH that cua cua so Clingying dang chay, dung cho tai
lieu (khong phai bang chung minh to hop nen den). Ly do anh phai la pixel tren
man hinh: mot hop thoai la top-level KHAC, nen `widget.grab()` va PrintWindow
cua cua so chinh khong bao gio chua no — anh "tu render" khong the noi nguoi
dung thay gi khi mo hop thoai.

Bon buc:
  editor-project-window.png  editor dang mo du an (preview + timeline + thu vien)
  editor-split-dialog.png    SplitDialog kieu "Diem cat tu dat", moc 9.0 roi ra
                             ngoai khoang nen dong "1 moc bi bo..." PHAI nhin
                             thay duoc — do la dong cua do `_fit_height` (do
                             22/10/2026: no nam duoc fold, grab() khong nhin
                             thay no nen khong bao gio do)
  editor-export-dialog.png   ExportDialog che do "Vung chi dinh (tu -> den)"
  editor-sfx-dialog.png      SfxDialog mo bang THAT nut tren thanh thoi: ca
                             pack liet ke du pack, va dong tim kiem cat dung
                             so dong — so dong do `core.sfx.entries()` sinh ra,
                             khong phai so do anh tu dem

An toan du lieu nguoi dung — bon chan song song:
  - fixture tu sinh bang lavfi trong %PUBLIC% (KHONG phai %TEMP% va cung KHONG
    phai thu muc du an that), media ten `shot_*.mp4`; video cua nguoi dung khong
    duoc doc;
  - `.clinq` nam trong goc do, nen `_auto_save` / autosave.json / recovery/
    khong the cham `~/.clinqing` hay `~/Clinging_Projects`; ba duong do van
    duoc redirect that ve goc tam;
  - handle cua so lay tu `winId()` cua chinh widget va doi voi `os.getpid()`,
    khong tim theo tieu de — mot cua theo ten co the bat dung cua cua nguoi dung
    dang mo;
  - hai cua doi chieu: cache nguoi dung khong them file, va recent_projects.json
    khong doi byte.

Chay:
    python -u scratch/editor_screen_shots.py
    python -u scratch/editor_screen_shots.py --pixels    # phan chung tren anh
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# QT_ENABLE_HIGHDPI_SCALING=0 de so logic cua Qt == pixel thiet bi: cac cua
# "chuoi do PHAI nam trong vung grab" quy chieu toa do mapToGlobal thang tro.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

import popart_window_shot as shot                     # noqa: E402
from PIL import Image, ImageDraw                      # noqa: E402
from core import external_tools                       # noqa: E402

UIX = os.path.join(ROOT, "assets", "uiux")
FFMPEG = external_tools.require("ffmpeg")
FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}

# %PUBLIC% = C:\Users\Public, co tren moi may Windows va KHONG chua ten dang
# nhap. Do 22/10/2026: %TEMP% chua `doxuanhop`, nen mot truong duong dan trong
# hop thoai Xuat se in ten nguoi dung len anh commit.
PUBLIC = os.environ.get("PUBLIC") or os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "Users", "Public")
WORK = os.path.join(PUBLIC, "ClingingEditorShot")
PROJECT = "Editor Shot"
W, H, FPS = 1280, 720, 24
CLIP_DUR = 6.0
MARKS = "1.5, 3.0, 9.0"            # 9.0 roi ra ngoai khoang -> "1 moc bi bo"
EXPORT_FROM, EXPORT_TO = 1.25, 5.75   # le: khong nguyen hoa thanh mm:ss duoc
QUALITY_KEY = "can_bang"

SHOTS = {
    "editor": os.path.join(UIX, "editor-project-window.png"),
    "split": os.path.join(UIX, "editor-split-dialog.png"),
    "export": os.path.join(UIX, "editor-export-dialog.png"),
    "sfx": os.path.join(UIX, "editor-sfx-dialog.png"),
}
# Vung do mau, tinh theo ty le anh toan man hinh 1920x1080 cua lan chay nay.
FULL_BOX = (0.0, 0.0, 1.0, 1.0)
CENTER_BOX = (0.30, 0.30, 0.70, 0.70)     # canvas preview
TIMELINE_BOX = (0.10, 0.72, 0.99, 0.96)   # lane clip duoi day
# Nguong mau: mot vung bi boi den hoan toan do ra 1 mau (do 22/10/2026 tren
# chinh ba anh nay: blanked_full=1, blanked_timeline=1, blanked_center=1),
# trong khi anh that 211..3016 mau va dao theo tung frame cua preview. Lay 120
# de mot frame gan nhu phang van xanh, ma mat noi dung thi do.
CONTENT_FLOOR = 120

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def above(label, got, limit):
    ok = got is not None and float(got) > float(limit)
    if not ok:
        fails.append("%s: got %r not above %r" % (label, got, limit))
    print("%-58s %s value=%.4f limit=%r"
          % (label, "PASS" if ok else "FAIL", got if got is not None else -1, limit))
    return ok


def frac_box(img, box):
    return (int(img.width * box[0]), int(img.height * box[1]),
            int(img.width * box[2]), int(img.height * box[3]))


def n_colors(img, box, step=29):
    return len(set(list(img.crop(frac_box(img, box)).getdata())[::step]))


def rect_of(rect):
    return (rect.left, rect.top, rect.right, rect.bottom)


def own_hwnd(widget):
    """HWND (s nguyen) cua chinh widget nay + pid so huu no. Khong tim theo
    ten cua: mot cua theo ten co the bat dung cua cua nguoi dung dang mo."""
    handle = int(widget.winId())
    got = wt.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wt.HWND(handle),
                                                  ctypes.byref(got))
    return handle, got.value


def place(hwnd, x, y, w, h):
    ctypes.windll.user32.SetWindowPos(wt.HWND(int(hwnd)), wt.HWND(-1), x, y, w,
                                      h, 0x0040)   # SWP_SHOWWINDOW
    ctypes.windll.user32.BringWindowToTop(wt.HWND(int(hwnd)))


def count_files(folder):
    if not os.path.isdir(folder):
        return 0
    return sum(len(f) for _r, _d, f in os.walk(folder))


def mru_bytes():
    from ui.home_page import RECENT_FILE, get_app_data_dir
    path = os.path.join(str(get_app_data_dir()), RECENT_FILE)
    if not os.path.isfile(path):
        return None
    return open(path, "rb").read()


def shoot(tag, bbox, app, pump, deadline=25.0):
    """Hai lan chup tren CUNG bbox; tra ve anh da ve xong.

    `mean_luma > 8` la dieu kien tien quyet: grab ngay sau `show()` tra ve
    khung den khi du an con nap (do 21/10/2026 trong popart_window_shot).
    """
    end = time.time() + deadline
    first = None
    while time.time() < end:
        pump(6)
        cand = shot.grab_screen(bbox)
        if shot.mean_luma(cand) > 8.0:
            first = cand
            break
    if first is None:
        fails.append("%s: 25 s van khong co frame sang" % tag)
        return None
    time.sleep(0.8)
    pump(20)
    second = shot.grab_screen(bbox)
    moved = shot.pct_moved(first, second)
    above("%s: hai lan chup on dinh (1 %% - lech > 0)" % tag, 1.0 - moved, 0.0)
    return first


def privacy_offenders(paths, work_root):
    """Duong dan tuyet doi NGOAI goc fixture = anh se lo du lieu nguoi dung."""
    root = os.path.abspath(work_root).lower().rstrip("\\") + os.sep
    return [p for p in paths
            if p and os.path.isabs(p)
            and not os.path.abspath(p).lower().startswith(root)]


def fixture_paths(clinq):
    """Moi chuoi duong dan tuyet doi trong chinh file .clinq se mo."""
    import json
    data = json.loads(open(clinq, encoding="utf-8").read())
    found = [a.get("path", "") for a in data.get("assets", {}).values()]
    for track in data.get("timeline", {}).get("tracks", []):
        found += [c.get("source_path", "") for c in track.get("clips", [])]
    return [p for p in found if p]


def project_storage_real_recovery():
    """Cay recovery THAT, doc truoc khi main() redirect cua no."""
    from core.project_storage import APP_DIR
    return os.path.join(APP_DIR, "recovery")


# ── fixture ────────────────────────────────────────────────────

def make_media():
    from pathlib import Path
    proj = Path(WORK) / PROJECT
    for d in ("Assets", "Cache", "Exports"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    sources = [("shot_gradient.mp4",
                "gradients=s=%dx%d:d=%g:n=4:c0=0xFF2E63:c1=0x00C2FF:c2=0xFFD60A:"
                "c3=0x08F7A0:speed=0.06:r=%d" % (W, H, CLIP_DUR, FPS)),
               ("shot_pattern.mp4",
                "testsrc2=s=%dx%d:d=%g:r=%d" % (W, H, CLIP_DUR, FPS))]
    out = []
    for name, video in sources:
        path = proj / "Assets" / name
        if path.exists():
            os.remove(path)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        video, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                       check=True, timeout=300, **FLAGS)
        above("fixture %s > 20 000 B" % name, os.path.getsize(path), 20000)
        out.append(str(path))
    return proj, out


def build_model(src_a, src_b):
    """Lap du an bang chinh core.commands + UndoStack ma nut bam trong UI dung."""
    from core.commands import (AddClipCommand, ApplyEffectCommand,
                               SetClipTextCommand, UndoStack)
    from core.timeline_model import TimelineModel, TrackType

    model = TimelineModel()
    model.project_ratio = "16:9"
    stack = UndoStack()
    track = model.add_track(TrackType.VIDEO, "Main", is_main_track=True)
    for name, path, start in (("shot A", src_a, 0.0), ("shot B", src_b, CLIP_DUR)):
        cmd = AddClipCommand(model, track.track_id, path, "video", start,
                             CLIP_DUR, name)
        stack.push(cmd)
        stack.push(ApplyEffectCommand(model, cmd._clip_id, {
            "name": "Pop Art", "category": "Sắc thái",
            "icon": "fa6s.circle-dot"}))
    text_track = model.add_track(TrackType.TEXT, "Text 1")
    cmd_t = AddClipCommand(model, text_track.track_id, "CLINGING DEMO", "text",
                           1.0, 8.0, "CLINGING DEMO")
    stack.push(cmd_t)
    stack.push(SetClipTextCommand(model, cmd_t._clip_id, name="CLINGING DEMO",
                                  font_family="Arial Black", font_size=96.0,
                                  font_bold=True, font_color="#FFD60A",
                                  text_style="outline",
                                  text_outline_color="#101010",
                                  text_outline_width=9.0))
    return model


# ── phan chung ────────────────────────────────────────────────

def pixels_selfcheck():
    """Cua do anh phai DO vi dung ly do, khong phai vi duoi dan khong co gi."""
    print("== phan chung anh ==")
    black = Image.new("RGB", (1920, 1080), (5, 5, 8))
    luma_black = shot.mean_luma(black)
    print("[A] khuc khung den    luma=%.2f -> %s"
          % (luma_black, "DO dung" if luma_black <= 8.0 else "XANH SAI"))
    if luma_black > 8.0:
        fails.append("[A] khung den khong bi phat hien - cua gia")
    real = {}
    for tag, path in SHOTS.items():
        if not os.path.exists(path):
            print("[B] %s chua co anh -> bo qua" % tag)
            continue
        img = Image.open(path).convert("RGB")
        real[tag] = img
        c_full, c_time = n_colors(img, FULL_BOX), n_colors(img, TIMELINE_BOX)
        c_center = n_colors(img, CENTER_BOX)
        print("[B] %-16s %dx%d luma=%.1f toan anh=%d mau timeline=%d mau "
              "center=%d mau"
              % (tag, img.width, img.height, shot.mean_luma(img), c_full,
                 c_time, c_center))
        # Cua "preview co noi dung" CHI ap dung cho anh A: ba anh hop thoai che
        # mat canvas, nen do mau o giua tren chung la do hop thoai (do 22/10/2026:
        # anh C chi con 149 mau o giua).
        ok = (shot.mean_luma(img) > 8.0 and c_full > CONTENT_FLOOR
              and c_time > CONTENT_FLOOR
              and (tag != "editor" or c_center > CONTENT_FLOOR))
        if not ok:
            fails.append("[B] %s khong qua cua cua chinh" % tag)
        if tag == "editor":
            tampered = img.copy()
            ImageDraw.Draw(tampered).rectangle(frac_box(tampered, CENTER_BOX),
                                               fill=(6, 6, 6))
            if n_colors(tampered, CENTER_BOX) > CONTENT_FLOOR:
                fails.append("[C] %s: boi preview ma van xanh - cua preview gia"
                             % tag)
        blanked = img.copy()
        ImageDraw.Draw(blanked).rectangle(frac_box(blanked, TIMELINE_BOX),
                                          fill=(6, 6, 6))
        if n_colors(blanked, TIMELINE_BOX) > CONTENT_FLOOR:
            fails.append("[D] %s: xoa timeline ma van xanh - cua timeline gia"
                         % tag)
        wiped = img.copy()
        ImageDraw.Draw(wiped).rectangle((0, 0, img.width, img.height),
                                        fill=(6, 6, 6))
        if n_colors(wiped, FULL_BOX) > CONTENT_FLOOR:
            fails.append("[G] %s: xoa ca anh ma van xanh - cua mau toan anh gia"
                         % tag)
    for other in ("split", "export", "sfx"):
        if "editor" in real and other in real:
            d = shot.pct_moved(real["editor"], real[other])
            print("[E] editor vs %-6s lech %.2f%% (khong phai mot anh doi ten)"
                  % (other, d))
            if d <= 1.0:
                fails.append("[E] editor vs %s giong het nhau" % other)
    inside = [os.path.join(WORK, PROJECT, "Assets", "shot_gradient.mp4")]
    leaky = inside + [r"C:\Users\me\Clinging_Projects\Du an 2\video.mp4"]
    check("[F] fixture cua day anh khong lo duong dan",
          privacy_offenders(inside, WORK), [])
    check("[F] mot duong dan nguoi dung bi phat hien",
          privacy_offenders(leaky, WORK),
          [r"C:\Users\me\Clinging_Projects\Du an 2\video.mp4"])
    for f in fails:
        print("GATE FAIL:", f)
    print("ALL PASS" if not fails else "CO FAIL: %d" % len(fails))
    return 0 if not fails else 1


# ── lan chay chinh ────────────────────────────────────────────

def main():
    from core import media_cache, project_storage
    from core.project_storage import save_project_to_file

    real_cache_root = media_cache.cache_root      # gi lai TRUOC khi redirect
    user_cache_before = count_files(real_cache_root())
    mru_before = mru_bytes()
    recovery_before = project_storage_real_recovery()

    shutil.rmtree(WORK, ignore_errors=True)
    media_cache.cache_root = lambda: os.path.join(WORK, "_cache")
    project_storage.AUTO_SAVE_FILE = os.path.join(WORK, "_autosave.json")
    project_storage.RECOVERY_DIR = os.path.join(WORK, "_recovery")

    app = ctrl = editor = None
    dialogs = []
    try:
        print("== 1. fixture ==")
        check("goc fixture khong chua ten dang nhap",
              os.environ.get("USERNAME", "").lower()
              in os.path.abspath(WORK).lower(), False)
        proj, (src_a, src_b) = make_media()
        clinq = str(proj / ("%s.clinq" % PROJECT))
        check("luu: save_project_to_file tra True",
              save_project_to_file(build_model(src_a, src_b), clinq, {
                  "project_name": PROJECT,
                  "resolution": {"width": W, "height": H},
                  "fps": FPS, "aspect_ratio": "16:9"}), True)
        check(".clinq mo ra khong chua duong dan ngoai fixture",
              privacy_offenders(fixture_paths(clinq), WORK), [])

        print("\n== 2. cua so that ==")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        def pump(times=8, pause=0.03):
            for _ in range(times):
                app.processEvents()
                time.sleep(pause)

        from ui.main_controller import MainController
        ctrl = MainController()
        ctrl.show()
        pump(10)
        check("mo du an qua duong production (open_project_path)",
              ctrl.open_project_path(clinq), True)
        pump(30)
        sw, sh = shot.screen_size()
        print("   man hinh: %dx%d" % (sw, sh))
        main_hwnd, main_pid = own_hwnd(ctrl)
        check("handle cua chinh thuoc ve pid nay", main_pid, os.getpid())
        place(main_hwnd, 0, 0, sw, sh)
        pump(6)
        editor = ctrl.editor_page          # noqa: F841 (bound cho teardown)
        model = editor.timeline_panel.model
        # Duong dan nam tren ProjectManager singleton, KHONG phai tren model:
        # do chinh la object `_auto_save()` dung, nen no phai tro ve fixture.
        from core.project_storage import ProjectManager
        check("editor mo du an cua fixture (khong phai du an nguoi dung)",
              os.path.abspath(ProjectManager().project_path or "").startswith(
                  os.path.abspath(WORK)), True)
        check("so clip trong du an",
              len([c for t in model.tracks for c in t.clips]), 3)
        check("ten du an in tren title bar",
              editor.title_bar.project_name.text(), PROJECT)
        model.playhead = 2.0
        pump(40)

        print("\n== 3. anh A: editor ==")
        bbox_a = shot.frame_bounds(main_hwnd)
        rect_a = rect_of(bbox_a)
        img_a = shoot("A", bbox_a, app, pump)
        if img_a is None:
            raise RuntimeError("khong chup duoc anh A")
        check("A la anh CA MAN HINH (khong phai widget tu ve)",
              [img_a.width, img_a.height], [sw, sh])
        above("A: preview co noi dung (> 120 mau)",
              n_colors(img_a, CENTER_BOX), CONTENT_FLOOR)
        above("A: vung timeline co clip (> 120 mau)",
              n_colors(img_a, TIMELINE_BOX), CONTENT_FLOOR)

        print("\n== 4. anh B: SplitDialog kieu diem cat ==")
        dlg_b = editor._open_media_split(src_a)
        dialogs.append(dlg_b)
        pump(8)
        keys = [dlg_b.combo_style.itemData(i)
                for i in range(dlg_b.combo_style.count())]
        dlg_b.combo_style.setCurrentIndex(keys.index("points"))
        dlg_b.edit_points.setText(MARKS)
        pump(12)
        src_text = dlg_b.combo_source.currentText()
        check("B: nguon la file cua fixture", "shot_gradient" in src_text, True)
        check("B: ten nguon khong lo duong dan tuyet doi", ":" in src_text, False)
        summary = dlg_b.lbl_summary.text()
        check("B: hien dong bao moc bi bo", "mốc bị bỏ" in summary, True)
        sa = dlg_b._scroll
        check("B: hop thoai khong phai cuon (khong con dong duoi fold)",
              [sa.verticalScrollBar().maximum(),
               sa.widget().sizeHint().height() <= sa.viewport().height()],
              [0, True])
        # Dong chu do phai nam TRONG viewport, khong chi trong hop thoai:
        # `mapToGlobal` cua chinh nhan moi la toa do nguoi dung nhin thay.
        seen = dlg_b.lbl_summary.mapToGlobal(
            dlg_b.lbl_summary.rect().bottomLeft())
        vp_bottom = sa.viewport().mapToGlobal(
            sa.viewport().rect().bottomLeft())
        check("B: dong chu do duoc ve trong viewport va tron trong anh",
              [seen.y() <= vp_bottom.y(),
               rect_a[0] <= seen.x() < rect_a[2]
               and rect_a[1] <= seen.y() < rect_a[3]],
              [True, True])
        dlg_hwnd_b, dlg_pid_b = own_hwnd(dlg_b)
        check("B: handle hop thoai thuoc ve pid nay", dlg_pid_b, os.getpid())
        place(dlg_hwnd_b, int(sw * 0.42), int(sh * 0.14),
              max(dlg_b.width(), 600), max(dlg_b.height(), 520))
        pump(10)
        rect_b = rect_of(shot.frame_bounds(dlg_hwnd_b))
        check("B: hop thoai dang hien theo chinh Qt", dlg_b.isVisible(), True)
        check("B: hop thoai nam TRON trong anh toan man hinh",
              [rect_a[0] <= rect_b[0], rect_b[2] <= rect_a[2],
               rect_a[1] <= rect_b[1], rect_b[3] <= rect_a[3]], [True] * 4)
        img_b = shoot("B", bbox_a, app, pump)
        if img_b is None:
            raise RuntimeError("khong chup duoc anh B")
        above("B: hop thoai that su duoc ve (lech vs anh A trong vung cua no > 5 %)",
              shot.pct_moved(img_a.crop(rect_b), img_b.crop(rect_b)) - 5.0, 0.0)
        above("B: anh co noi dung (> 120 mau toan anh)",
              n_colors(img_b, FULL_BOX), CONTENT_FLOOR)

        print("\n== 5. anh C: ExportDialog vung chi dinh ==")
        dlg_b.close()
        pump(6)
        from core import export_range
        from ui.export_dialog import ExportDialog
        # `_on_export()` goi dung `dialog.exec()` (khoa event loop) nen o day
        # lap lai dung doi so construct cua no roi `show()`: moi thu khac
        # (cong thoi luong, preset, layout) van la ExportDialog that.
        dlg_c = ExportDialog(model, parent=editor)
        dialogs.append(dlg_c)
        # `show()` la buoc bat buoc, khong phai thoi quen: `winId()` +
        # SetWindowPos(SWP_SHOWWINDOW) lam cua co that tren Win32 nhung Qt van
        # coi widget la an nen khong ve no. Lan chay 22/10/2026 that bai o day:
        # lech vung hop thoai voi anh A = 0,00% (cua trong anh van la editor).
        dlg_c.show()
        dlg_c.raise_()
        dlg_c.activateWindow()
        pump(10)
        rkeys = [dlg_c.combo_range.itemData(i)
                 for i in range(dlg_c.combo_range.count())]
        dlg_c.combo_range.setCurrentIndex(rkeys.index(export_range.RANGE_WINDOW))
        dlg_c.spin_from.setValue(EXPORT_FROM)
        dlg_c.spin_to.setValue(EXPORT_TO)
        qkeys = [dlg_c.combo_quality.itemData(i)
                 for i in range(dlg_c.combo_quality.count())]
        dlg_c.combo_quality.setCurrentIndex(qkeys.index(QUALITY_KEY))
        pump(12)
        info = dlg_c._current_window()
        check("C: cua so tu hai so nhap tay la HOP LE", info["ok"], True)
        # So PHI NGUYEN hoa: neu span tron ve so nguyen thi "mm:ss" cung in ra
        # duoc con so do va cua nay xanh gia (bẫy do 22/10).
        above("C: span le, mm:ss khong the thay no",
              abs(info["span"] - round(info["span"])) - 0.01, 0.0)
        want = "Thời lượng: %.2f s, %d frame / %s" % (
            info["span"], info["frames"],
            dlg_c._fmt_time(dlg_c._project_duration()))
        check("C: chu thoi luong dung = chuoi do seam sinh ra",
              dlg_c.lbl_duration.text(), want)
        check("C: preset chat luong dang chon",
              dlg_c.combo_quality.currentData(), QUALITY_KEY)
        check("C: preset in ra CRF cua chinh no",
              "CRF %d" % export_range.preset_of(QUALITY_KEY)[3]
              in dlg_c.lbl_format.text(), True)
        dlg_hwnd_c, dlg_pid_c = own_hwnd(dlg_c)
        check("C: handle hop thoai thuoc ve pid nay", dlg_pid_c, os.getpid())
        place(dlg_hwnd_c, int(sw * 0.28), int(sh * 0.08),
              max(dlg_c.width(), 900), max(dlg_c.height(), 640))
        pump(10)
        rect_c = rect_of(shot.frame_bounds(dlg_hwnd_c))
        check("C: hop thoai dang hien theo chinh Qt", dlg_c.isVisible(), True)
        check("C: hop thoai nam TRON trong anh toan man hinh",
              [rect_a[0] <= rect_c[0], rect_c[2] <= rect_a[2],
               rect_a[1] <= rect_c[1], rect_c[3] <= rect_a[3]], [True] * 4)
        img_c = shoot("C", bbox_a, app, pump)
        if img_c is None:
            raise RuntimeError("khong chup duoc anh C")
        above("C: hop thoai that su duoc ve (lech vs anh A trong vung cua no > 5 %)",
              shot.pct_moved(img_a.crop(rect_c), img_c.crop(rect_c)) - 5.0, 0.0)
        above("C: anh co noi dung (> 120 mau toan anh)",
              n_colors(img_c, FULL_BOX), CONTENT_FLOOR)

        print("\n== 6. anh D: SfxDialog (kho hieu ung am thanh) ==")
        dlg_c.close()
        pump(6)
        # Nut THAT tren thanh thoi -> `MainWindow._open_sfx` (import trong than
        # ham) -> `self._sfx_dialog`: dung chuoi duong dien ra tren may nguoi
        # dung, khong construct SfxDialog theo cach rieng cua probe.
        from core import sfx as sfx_core
        pack = sfx_core.entries()
        editor.timeline_panel.header.btn_sfx.click()
        pump(8)
        dlg_d = getattr(editor, "_sfx_dialog", None)
        dialogs.append(dlg_d)
        check("D: bam nut mo duoc hop thoai cua duong dien", dlg_d is not None, True)
        if dlg_d is None:
            raise RuntimeError("nut SFX khong mo duoc hop thoai")
        check("D: hop thoai liet ke du pack", dlg_d.list.count(), len(pack))
        needle = (pack[0].get("label") or "")[:3]
        want_rows = [r for r in pack if needle.casefold() in (
            "%s %s %s" % (r.get("label"), r.get("key"),
                          r.get("group"))).casefold()]
        dlg_d.search.setText(needle)
        pump(6)
        check("D: tim kiem cat dung so dong (%r -> %d)" % (needle, len(want_rows)),
              dlg_d.list.count(), len(want_rows))
        dlg_d.search.clear()
        dlg_d.list.setCurrentRow(0)
        pump(6)
        check("D: co dong dang chon de nguoi dung thay highlight",
              dlg_d.list.currentRow(), 0)
        # Khong bam "Nghe thu": `setSource()` cua QMediaPlayer gi file mp3 toi
        # luc teardown va `shutil.rmtree(ignore_errors=True)` xoa im lang khong
        # bao loi — dung lai cai bẫy da ke o doan finally duoi day.
        check("D: khong mo nguon tieng nao trong probe nay",
              dlg_d._player.source().isEmpty(), True)
        dlg_hwnd_d, dlg_pid_d = own_hwnd(dlg_d)
        check("D: handle hop thoai thuoc ve pid nay", dlg_pid_d, os.getpid())
        place(dlg_hwnd_d, int(sw * 0.33), int(sh * 0.06),
              dlg_d.width(), dlg_d.height())
        pump(10)
        rect_d = rect_of(shot.frame_bounds(dlg_hwnd_d))
        check("D: hop thoai dang hien theo chinh Qt", dlg_d.isVisible(), True)
        check("D: hop thoai nam TRON trong anh toan man hinh",
              [rect_a[0] <= rect_d[0], rect_d[2] <= rect_a[2],
               rect_a[1] <= rect_d[1], rect_d[3] <= rect_a[3]], [True] * 4)
        check("D: hop thoai khong che vung timeline do mau",
              rect_d[3] <= int(sh * 0.72), True)
        img_d = shoot("D", bbox_a, app, pump)
        if img_d is None:
            raise RuntimeError("khong chup duoc anh D")
        above("D: hop thoai that su duoc ve (lech vs anh A trong vung cua no > 5 %)",
              shot.pct_moved(img_a.crop(rect_d), img_d.crop(rect_d)) - 5.0, 0.0)
        above("D: anh co noi dung (> 120 mau toan anh)",
              n_colors(img_d, FULL_BOX), CONTENT_FLOOR)

        print("\n== 7. luu anh ==")
        os.makedirs(UIX, exist_ok=True)
        for tag, img in (("editor", img_a), ("split", img_b), ("export", img_c),
                         ("sfx", img_d)):
            path = SHOTS[tag]
            img.save(path, optimize=True)
            with Image.open(path) as back:
                check("%s: mo lai duoc %dx%d" % (tag, back.width, back.height),
                      [back.width, back.height], [img.width, img.height])
            print("   %s  %d bytes  sha256[:16]=%s"
                  % (path, os.path.getsize(path),
                     hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]))
        print("\nchu thich anh B: %s" % summary.replace("\n", " | "))
        print("chu thich anh C: %s" % want)
        print("chu thich anh D: pack %d muc, loc %r con %d dong"
              % (len(pack), needle, len(want_rows)))

        print("\n== 8. khong de lai rac ==")
        check("cache nguoi dung khong them file",
              count_files(real_cache_root()), user_cache_before)
        check("recent_projects.json khong doi byte", mru_bytes(), mru_before)
        check("recovery cua nguoi dung khong them ban cua doan nay",
              [n for n in os.listdir(recovery_before)
               if n.startswith(PROJECT + "__")]
              if os.path.isdir(recovery_before) else [], [])
    finally:
        for dlg in dialogs:
            try:
                dlg.close()
            except Exception:
                pass
        # KEO FILE LAI thu nhat cua lan chay 22/10/2026 KHONG phai QMediaPlayer
        # ma la `MainWindow._video_readers` (SequentialVideoReader -> cv2
        # VideoCapture, ui/main_window.py:1293): no chi dong khi clip bien khoi
        # model (ui/main_window.py:628), con dong cua thi gi nguyen handle.
        # rmtree(ignore_errors=True) xoa that bai ma khong bao loi, nen goc
        # %PUBLIC%\ClingingEditorShot con lai shot_gradient.mp4.
        try:
            if editor is not None:
                for reader in editor._video_readers.values():
                    reader.close()
                editor._video_readers.clear()
                from PySide6.QtCore import QUrl
                editor._audio_player.stop()
                editor._audio_player.setSource(QUrl())
                pump(8)
        except Exception:
            pass
        if ctrl is not None:
            ctrl.close()
        if app is not None:
            for _ in range(8):
                app.processEvents()
                time.sleep(0.02)
        for _ in range(25):
            shutil.rmtree(WORK, ignore_errors=True)
            if not os.path.exists(WORK):
                break
            time.sleep(0.2)
        check("goc fixture da xoa SACH (khong co file bi player giu lai)",
              os.path.exists(WORK), False)

    for f in fails:
        print("GATE FAIL:", f)
    print("ALL PASS" if not fails else "CO FAIL: %d" % len(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--pixels" in sys.argv:
        sys.exit(pixels_selfcheck())
    sys.exit(main())
