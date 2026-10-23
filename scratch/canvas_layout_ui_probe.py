"""Cổng UI cho nhóm "Bố cục & Phong cách" — chạy trên MainWindow THẬT.

--selftest do pixel qua core/canvas_layout; nó không chứng minh được bốn điều mà
người dùng sẽ gặp:
  1. nút mở hộp thoại có thật và có nối (đo bằng click() thật, không đo isNull),
  2. hộp thoại cao đủ cho HET dieu khien — một dòng bị fold thì người dùng
     không bao giờ thấy lỗi nhập của chính mình (bẫy SplitDialog 22/10: cua do
     `verticalScrollBar().maximum() == 0` ra 423 px tren platform that, nen do
     tren platform windows, khong phai offscreen),
  3. keo thanh trượt = model đổi NGAY, đóng hộp thoại = DUNG MỘT mục undo,
  4. "Dàn clip vào ô" viết transform THAT (tâm clip trùng tâm ô) và Ctrl+Z tra
     lai nguyen vi tri cu.

Khong fixture nguoi dung: media tu sinh trong scratch/, AUTO_SAVE_FILE va
media_cache.cache_root chi ra tam, moi thu bi xoa trong finally.

Chay:
    python -u scratch/canvas_layout_ui_probe.py
"""

import gc
import json
import os
import shutil
import sys
import time
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QSlider,
    QSpinBox, QWidget,
)

import core.media_cache as media_cache
import core.project_storage as project_storage
from core import canvas_layout
from core.canvas_utils import ASPECT_RATIOS, base_display_size
from core.timeline_model import TrackType

AUTOSAVE = os.path.join(OUT, "canvas_layout_ui_autosave.json")
CACHE_DIR = os.path.join(OUT, "canvas_layout_ui_cache")
STILLS = [os.path.join(OUT, "canvas_layout_ui_%d.png" % i) for i in range(3)]
REPORT = os.path.join(OUT, "canvas_layout_ui.json")

CONTROLS = (QComboBox, QLineEdit, QSpinBox, QSlider, QCheckBox, QPushButton)
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-62s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def truthy(label, value, detail=""):
    ok = bool(value)
    if not ok:
        fails.append("%s: %s" % (label, detail))
    print("%-62s %s %s" % (label, "PASS" if ok else "FAIL", detail))
    return ok


def pump(app, times=8):
    for _ in range(times):
        app.processEvents()
        time.sleep(0.008)


def write_still(path, rgb):
    img = QImage(640, 360, QImage.Format_RGB32)
    img.fill(QColor(*rgb))
    painter = QPainter(img)
    painter.setPen(QColor(255, 255, 255))
    painter.drawRect(40, 30, 560, 300)
    painter.end()
    img.save(path, "PNG")
    return os.path.isfile(path)


def apply_state(dialog, app, **patch):
    settings = dict(canvas_layout.LAYOUT_DEFAULTS)
    settings.update(patch)
    dialog._loading = True
    dialog._model.set_project_layout(canvas_layout.normalize(settings), emit=False)
    dialog._load_from(dialog._model.project_layout)
    dialog._loading = False
    pump(app, 4)


def rows_by_key(dialog):
    return {row.key: row for row in dialog._rows()}


def click_close(dialog, app):
    for widget in dialog.findChildren(QPushButton):
        if widget.text() == "Đóng":
            widget.click()
            pump(app, 3)
            return True
    return False


# ── A. điểm vào ───────────────────────────────────────────────────
def gate_entry(win, app):
    header = win.timeline_panel.header
    truthy("nut Boc cuc nam trong header",
           isinstance(getattr(header, "btn_layout", None), QWidget),
           "btn_layout=%r" % type(getattr(header, "btn_layout", None)).__name__)
    truthy("nut co chu thich", bool(header.btn_layout.toolTip()),
           header.btn_layout.toolTip())
    first = getattr(win, "_canvas_layout_dialog", None)
    header.btn_layout.click()
    pump(app, 6)
    dialog = getattr(win, "_canvas_layout_dialog", None)
    truthy("bam nut mo hop thoai (lan 1)", first is None and dialog is not None)
    check("loai hop thoai", type(dialog).__name__, "CanvasLayoutDialog")
    truthy("hop thoai dang hien", dialog.isVisible())
    header.btn_layout.click()
    pump(app, 4)
    truthy("bam lan 2 dung mot instance lap lai",
           getattr(win, "_canvas_layout_dialog", None) is dialog)
    return dialog


# ── B. 22 khoá: mọi điều khiển phản ánh được giá trị model ────────
def gate_fields(dialog, app):
    collected = dialog._collect()
    check("so khoa hop thoai thu duoc", len(collected), len(canvas_layout.LAYOUT_DEFAULTS))
    check("tap khoa = LAYOUT_DEFAULTS",
          sorted(collected), sorted(canvas_layout.LAYOUT_DEFAULTS))
    unmatched = []
    for key in sorted(canvas_layout.LAYOUT_DEFAULTS):
        target = canvas_layout.normalize(_with_other_value(key))
        apply_state(dialog, app, **{key: target[key]})
        got = dialog._collect()[key]
        if not _same(got, target[key]):
            unmatched.append("%s: model=%r dieu khien=%r" % (key, target[key], got))
    truthy("moi khoa co dieu khien doc/ghi duoc", not unmatched,
           "; ".join(unmatched))


def _with_other_value(key):
    """Gia tri KHAC mac dinh va nam trong mien cua chinh dieu khien do.

    Mac dinh trung gia tri cu thi phep thu 'dieu khien phan anh model' xanh ma
    khong do gi; gia tri ngoai mien widget (interval 1.0 khong nam trong
    ROTATE_CHOICES) khien combo tu dong nhay ve muc 0 va cua do do sai o chinh
    do lap lai, nen roi rieng no.
    """
    value = canvas_layout.LAYOUT_DEFAULTS[key]
    if key == "manga_rotate_interval":
        return {key: 3.0}
    if isinstance(value, bool):
        return {key: not value}
    if isinstance(value, (int, float)):
        return {key: float(value) + (0.05 if abs(value) < 1 else 1.0)}
    if key in canvas_layout.LAYOUT_STYLES:
        return {key: "split-4"}
    if key in canvas_layout.TEXTURES:
        return {key: "blueprint"}
    if key in canvas_layout.FONT_FAMILIES:
        return {key: "serif"}
    if key in canvas_layout.BACKGROUND_MODES:
        return {key: "color"}
    if isinstance(value, str) and value.startswith("#"):
        return {key: "#FF8800"}
    if isinstance(value, str):
        return {key: "CHU THU NGHIEM"}
    return {key: value}


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 0.051
    return a == b


# ── C. không điều khiển nào bị fold ──────────────────────────────
def gate_no_fold(dialog, app):
    states = {
        "tat": {"enabled": False},
        "den + none": {"enabled": True, "background_mode": "black",
                       "layout": "none"},
        "chat lieu + chu": {"enabled": True, "background_mode": "texture",
                            "texture": "blueprint",
                            "layout": "magazine-editorial",
                            "header_text": "Tuan 42", "footer_text": "Canva aura"},
        "luoi 6 o + tuan tu": {"enabled": True, "layout": "split-6",
                               "slot_gap": 0.2, "play_sequentially": True,
                               "manga_rotate_interval": 5.0, "auto_fit": False},
    }
    screen = QApplication.primaryScreen().availableGeometry()
    counted_seen = 0
    for name, patch in states.items():
        apply_state(dialog, app, **patch)
        bar = dialog._scroll.verticalScrollBar()
        check("khong the cuon [%s]" % name, bar.maximum(), 0)
        outside, counted = _outside_viewport(dialog)
        truthy("moi dieu khien nam trong viewport [%s]" % name, not outside,
               "ngoai: %s" % outside)
        truthy("cua khong vuot man hinh [%s]" % name,
               dialog.height() <= screen.height(),
               "dialog=%d screen=%d" % (dialog.height(), screen.height()))
        counted_seen = max(counted_seen, counted)
    # Gate phai chet khi khong tim thay gi de do: mot hop thoai rong (0 dieu
    # khien) cung "vua" neu thieu dong nay. 24 = 22 khoa + 2 nut (dan, dong).
    truthy("dem du dieu khien de do fold", counted_seen >= 24,
           "dem duoc = %d" % counted_seen)


def _outside_viewport(dialog):
    """Dieu khien nao nam ngoai viewport cua QScrollArea = bi fold.

    Widget disabled VAN TINH: master tat chi lam no xam chu khong lam no bien
    mat khoi layout, nen phep do khong duoc doi theo che do bat/tat.
    """
    viewport = dialog._scroll.viewport()
    top_left = viewport.mapToGlobal(viewport.rect().topLeft())
    bottom_right = viewport.mapToGlobal(viewport.rect().bottomRight())
    bad = []
    counted = 0
    for widget in dialog._body.findChildren(QWidget):
        if not isinstance(widget, CONTROLS):
            continue
        if not widget.isVisible():
            continue
        counted += 1
        origin = widget.mapToGlobal(widget.rect().topLeft())
        end = widget.mapToGlobal(widget.rect().bottomRight())
        if not (top_left.x() <= origin.x() and top_left.y() <= origin.y()
                and end.x() <= bottom_right.x() and end.y() <= bottom_right.y()):
            bad.append("%s/%s" % (type(widget).__name__,
                                 widget.objectName() or "slider"))
    return bad, counted


# ── D. master off và chế độ nền ẩn đúng điều khiển ───────────────
def gate_enablement(dialog, app):
    rows = rows_by_key(dialog)
    apply_state(dialog, app, enabled=False, background_mode="texture",
                layout="split-4")
    check("master tat -> slider khe tat", rows["slot_gap"].isEnabled(), False)
    check("master tat -> combo chat lieu tat", dialog.combo_texture.isEnabled(), False)
    check("master tat -> nut dan clip tat", dialog.btn_arrange.isEnabled(), False)
    apply_state(dialog, app, enabled=True, background_mode="color", layout="split-4")
    check("nen MAU -> o mau nen bat", dialog.btn_bg_color.isEnabled(), True)
    check("nen MAU -> combo chat lieu tat", dialog.combo_texture.isEnabled(), False)
    apply_state(dialog, app, enabled=True, background_mode="texture", layout="split-4")
    check("nen CHAT LIEU -> combo bat", dialog.combo_texture.isEnabled(), True)
    check("nen CHAT LIEU -> o mau nen tat", dialog.btn_bg_color.isEnabled(), False)
    apply_state(dialog, app, enabled=True, background_mode="texture", layout="none")
    check("bo cuc none -> slider khe tat", rows["slot_gap"].isEnabled(), False)
    apply_state(dialog, app, enabled=True, layout="split-3")
    check("bo cuc 3 o -> slider khe bat", rows["slot_gap"].isEnabled(), True)


# ── E. kéo slider = model đổi; đóng = một bước undo ──────────────
def gate_live_and_undo(dialog, win, app):
    stack = win.timeline_panel.undo_stack
    apply_state(dialog, app, enabled=True, layout="split", background_mode="color",
                background_color="#3673FE")
    dialog._opening = dict(dialog._model.project_layout)
    base_count = stack.undo_count
    click_close(dialog, app)
    check("dong khong doi gi -> 0 muc undo", stack.undo_count, base_count)

    slider = rows_by_key(dialog)["slot_gap"].slider
    slider.setValue(12)
    pump(app, 3)
    check("keo slider -> model doi ngay", dialog._model.project_layout["slot_gap"], 0.12)
    grab = win.preview_panel.canvas.viewport().grab()
    check("canvas ve lai (khong rong)", grab.isNull(), False)
    click_close(dialog, app)
    check("keo 1 slider roi dong -> 1 muc undo", stack.undo_count, base_count + 1)
    stack.undo()
    pump(app, 3)
    check("undo tra gia tri cu", dialog._model.project_layout["slot_gap"], 0.0)
    dialog.refresh()
    check("refresh doc lai dieu khien", slider.value(), 0)
    stack.redo()
    pump(app, 3)
    check("redo khoi phuc gia tri", dialog._model.project_layout["slot_gap"], 0.12)


# ── F. dàn clip vào ô: transform thật + MỘT lệnh undo ────────────
def gate_arrange(dialog, win, app):
    model = dialog._model
    for track in list(model.tracks):
        for clip in list(track.clips):
            model.remove_clip(clip.clip_id)
    w, h = ASPECT_RATIOS.get(model.project_ratio, (1920, 1080))
    clips = []
    for index, path in enumerate(STILLS):
        # TrackType.IMAGE: `track_accepts_media` tu choi "image" tren track VIDEO,
        # va mot track IMAGE khong tu hap nen ba clip cung nam o [0, 4) duoc —
        # playhead 1,0 tinh ca ba la dang hien, dung nhu nguoi dung xep ba lop.
        track = model.add_track(TrackType.IMAGE, name="slot %d" % index)
        clip = model.add_clip(track.track_id, path, "image", 0.0, 4.0,
                              name="still%d" % index)
        if clip is None:
            raise SystemExit("khong tao duoc clip fixture %d" % index)
        clips.append(clip)
    model.playhead = 1.0
    apply_state(dialog, app, enabled=True, layout="split", slot_gap=0.0,
                auto_fit=True, background_mode="color",
                background_color="#0B0B0F")
    before = [_transform(c) for c in clips]
    stack = win.timeline_panel.undo_stack
    base_count = stack.undo_count
    dialog.btn_arrange.click()
    pump(app, 4)
    check("dan clip day DUNG MOT lenh undo", stack.undo_count, base_count + 1)
    moved = sum(1 for c, snapshot in zip(clips, before)
                if _transform(c) != snapshot)
    boxes = canvas_layout.slots(w, h, dialog._model.project_layout)
    check("bo cuc split co 2 o", len(boxes), 2)
    check("chi 2 clip duoc dan (3 clip / 2 o)", moved, len(boxes))
    # Quy tac cua `_arrange`: `model.tracks` di duoi-len-tren nen track CUOI la
    # lop tren cung va nhan o 0. Doi chieu theo thu tu do, khong theo thu tu tao
    # clip: neu zip theo `clips` thi phep do tam lech nhin sang ben clip chua di
    # chuyen va bao "tam lech" cho mot nan nhan sai (do lan chay 23/10).
    order = list(reversed(clips))[:len(boxes)]
    leftover = [c for c in clips if c not in order]
    bad = []
    for clip, box in zip(order, boxes):
        base_w, base_h = base_display_size(clip, w, h)
        drawn_w = base_w * clip.transform.scale_x
        drawn_h = base_h * clip.transform.scale_y
        cx = w / 2.0 + clip.transform.x
        cy = h / 2.0 + clip.transform.y
        if abs(cx - (box[0] + box[2] / 2.0)) > 0.75 or abs(cy - (box[1] + box[3] / 2.0)) > 0.75:
            bad.append("tam lech %s" % clip.name)
        if drawn_w > box[2] + 0.75 or drawn_h > box[3] + 0.75:
            bad.append("trao o %s (%.0fx%.0f > %.0fx%.0f)"
                       % (clip.name, drawn_w, drawn_h, box[2], box[3]))
    for clip in leftover:
        if _transform(clip) != before[clips.index(clip)]:
            bad.append("clip thua %s bi lat vao o" % clip.name)
    truthy("clip nam dung tam va trong o (auto_fit)", not bad, "; ".join(bad))
    truthy("nut dan bao ro hop du o hay lap o cuoi",
           ("du o" if not leftover else "lap o cuoi") in dialog.lbl_arrange.text(),
           dialog.lbl_arrange.text())
    stack.undo()
    pump(app, 4)
    check("Ctrl+Z tra nguyen vi tri cu",
          [_transform(c) for c in clips], before)
    # Khong co clip nao tai playhead thi nut dan PHAI tu choi va khong day lenh
    # nay la thu duy nhat phat hien mot `active` rong (neu khong, cua "dan clip"
    # xanh vi mo hinh da san ro).
    model.playhead = 4.0
    count_empty = stack.undo_count
    dialog.btn_arrange.click()
    pump(app, 3)
    check("khong co clip o playhead -> khong day lenh", stack.undo_count, count_empty)
    truthy("nut dan bao cho nguoi dung biet ly do",
           "clip" in dialog.lbl_arrange.text().lower(),
           dialog.lbl_arrange.text())
    model.playhead = 1.0
    apply_state(dialog, app, enabled=True, layout="split", slot_gap=0.0,
                auto_fit=False)
    count = stack.undo_count
    dialog.btn_arrange.click()
    pump(app, 3)
    check("che do fill cung day duoc lenh", stack.undo_count, count + 1)
    boxes = canvas_layout.slots(w, h, dialog._model.project_layout)
    order = list(reversed(clips))[:len(boxes)]
    fills = []
    for clip, box in zip(order, boxes):
        base_w, base_h = base_display_size(clip, w, h)
        drawn_w = base_w * clip.transform.scale_x
        drawn_h = base_h * clip.transform.scale_y
        if drawn_w < box[2] - 0.75 and drawn_h < box[3] - 0.75:
            fills.append("%s khong lap day o" % clip.name)
    truthy("fill: o duoc lap day theo chieu doc hoac ngang", not fills,
           "; ".join(fills))
    stack.undo()
    pump(app, 3)


def _transform(clip):
    t = clip.transform
    return (round(t.x, 3), round(t.y, 3), round(t.scale_x, 5), round(t.scale_y, 5))


# ── G. chi phí thật cho máy cấu hình thấp ────────────────────────
def measure_cost(win, app):
    dialog = win._canvas_layout_dialog
    dialog.close()
    pump(app, 4)
    del win._canvas_layout_dialog
    gc.collect()
    pump(app, 4)
    before = _private_kib()
    started = time.perf_counter()
    reopened = win._open_canvas_layout()
    pump(app, 6)
    took = round(time.perf_counter() - started, 3)
    after = _private_kib()
    reopened.close()
    pump(app, 4)
    return {"open_s": took,
            "ram_kib": after,
            "ram_delta_kib": (after - before) if before and after else 0}


def _private_kib():
    try:
        import psutil
        return int(psutil.Process().memory_info().private / 1024)
    except Exception:
        return 0


def _remove_fixtures():
    """Ranh gioi probe: anh fixture, autosave tam, cache tam.

    Retry 2 s TINH CHO TUNG file: mot deadline dung cho ca ba lan chay 23/10 da
    bi file dau tien (cv2.VideoCapture giu tay) nuot het 2 s, hai file sau buoc
    qua vong lap `while ... and time.time() < deadline` ma khong thu xoa lan nao,
    de lai rac trong scratch/.
    """
    for path in STILLS + [AUTOSAVE]:
        deadline = time.time() + 5.0
        last = None
        while os.path.isfile(path) and time.time() < deadline:
            try:
                os.remove(path)
                break
            except OSError as error:
                last = error
                time.sleep(0.2)
        else:
            if os.path.isfile(path):
                print("CANH BAO: xoa khong duoc %s: %r" % (path, last))
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    left = [p for p in STILLS + [AUTOSAVE] if os.path.exists(p)]
    if left:
        print("CANH BAO: con rac probe: %s" % left)


def main():
    for index, path in enumerate(STILLS):
        if not write_still(path, (60 + 60 * index, 120, 200)):
            raise SystemExit("khong tao duoc anh fixture: %s" % path)
    project_storage.AUTO_SAVE_FILE = AUTOSAVE
    real_cache_root = media_cache.cache_root
    os.makedirs(CACHE_DIR, exist_ok=True)
    media_cache.cache_root = lambda: CACHE_DIR

    app = QApplication.instance() or QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1680, 940)
    win.show()
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    pump(app, 16)

    cost = {}
    try:
        dialog = gate_entry(win, app)
        gate_fields(dialog, app)
        gate_no_fold(dialog, app)
        gate_enablement(dialog, app)
        gate_live_and_undo(dialog, win, app)
        gate_arrange(dialog, win, app)
        cost = measure_cost(win, app)
        truthy("mo hop thoai duoi 0,6 s tren may nay", cost["open_s"] < 0.6,
               "open_s=%r" % cost["open_s"])
        # Ràng buộc "máy cấu hình thấp" phai co so RAM, khong chi so giay.
        # _private_kib() tra 0 khi psutil chet im, nen cua doi do luon > 0 truoc
        # khi so nguong - khong duoc xanh vi do duoc 0 KiB.
        truthy("do duoc private RAM cua chinh process", cost["ram_kib"] > 0,
               "ram_kib=%r" % cost["ram_kib"])
        truthy("hop thoai chiem duoi 8 MiB private", cost["ram_delta_kib"] < 8192,
               "ram_delta_kib=%r" % cost["ram_delta_kib"])
    finally:
        media_cache.cache_root = real_cache_root
        for widget in list(app.topLevelWidgets()):
            try:
                widget.close()
            except Exception:
                pass
        for _ in range(6):
            app.processEvents()
        # QMediaPlayer (backend WMF) giu NGUON mo cho toi khi setSource(QUrl()),
        # ke ca sau stop()/close(). Do lan chay 23/10: psutil liet ke dung MOT
        # handle cua process nay tro vao canvas_layout_ui_0.png trong khi gc khong
        # con VideoCapture/reader nao, va file xoa duoc ngay sau khi process thoat.
        # `_audio_player` la nut that cua editor (main_window.py:599) nen pha bo
        # source trong vong processEvents truoc khi xoa fixture.
        player = getattr(win, "_audio_player", None)
        if player is not None:
            player.stop()
            player.setSource(QUrl())
        pump(app, 4)
        _remove_fixtures()
    with open(REPORT, "w", encoding="utf-8") as handle:
        json.dump({"failed": fails, "cost": cost}, handle,
                  ensure_ascii=False, indent=2)
    print("\n===== %d that bai =====" % len(fails))
    for row in fails:
        print("  - " + row)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
