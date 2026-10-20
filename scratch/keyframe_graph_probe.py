"""
scratch/keyframe_graph_probe.py
Bằng chứng cho ĐỒ THỊ ĐƯỜNG CONG keyframe.

Sáu câu hỏi phải trả lời bằng số đo, không bằng lời văn:

  1. PHEP CHIEU: keo node toi pixel nao thi model phải nhận ĐÚNG giá trị của
     pixel đó — hai chiều phải nghịch đảo chính xác, kể cả khi dải giá trị
     suy biến (một moc, mọi moc bằng nhau, không moc nào).
  2. DUONG CONG: duong nguoi ta NHIN thấy trên đồ thị phải là duong
     interpolate_keyframes trả ra, vì đó là duong preview va export render.
     Do bang pixel tren anh grab: cot anh tai thoi diem t phai nam dung
     y_of(gia tri model).
  3. PHAN CHUNG: gia lap EASINGS = linear giua chung thi cot anh PHAI DI CHU
     theo va van khop gia tri model moi. Mot khoa khong the sai khong duoc
     tinh la khoa. Tuong tu: cu keo bat dau o NGOAI ban kinh bam thi model
     khong duoc doi — chung to thay doi den tu node, khong tu duong dan.
  4. SUA: keo hai chieu, them moc, xoa moc, doi duong cong — tat ca di qua
     lenh that, undo/redo duoc, va giu duong cong cua moc.
  5. DONG BO: playhead chay theo model; moc doi thoi gian thi viên kim cuong
     tren timeline cung doi cho — KHONG goi _sync tay, do signal tu view lam.
  6. DIEM VAO: muc menu chuot phai va nut o the thuoc tinh chi co khi clip
     that su co keyframe; hop thoai duoc dung lai chu khong nhan ban.

Chay: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/keyframe_graph_probe.py
"""

import os
import sys
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

import numpy as np

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication

from core import keyframe_graph as graph
from core.keyframe_manager import (EASINGS, EASE_LABELS, frame_ease,
                                   frame_time, frame_value,
                                   interpolate_keyframes, make_frame)
from core.timeline_model import track_type_for_media
from diagnostics import LANE_FIXTURE, action_connection, orphan_baseline
from ui.keyframe_graph_dialog import (AXIS_HEIGHT, AXIS_TEXT, GUTTER_LEFT,
                                      HIT_RADIUS, LANE_GAP, LANE_MIN_HEIGHT,
                                      VALUE_LABEL_RIGHT, KeyframeGraphDialog,
                                      color_of, label_divisions)

SHEET = os.path.join(OUT, "clinging_keyframe_graph.png")
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL",
                                       got, want))
    return ok


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want ~%r+-%r" % (label, got, want, tol))
    print("%-58s %s got=%r want~%.2f+-%.2f"
          % (label, "PASS" if ok else "FAIL", got, want, tol))
    return ok


def above(label, got, limit):
    ok = got is not None and got > limit
    if not ok:
        fails.append("%s: got %r want > %r" % (label, got, limit))
    print("%-58s %s value=%r limit=%r"
          % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def pump(n=8):
    for _ in range(n):
        QApplication.processEvents()


def ink(icon):
    """So pixel co muc cua icon — isNull() khong phat hien icon in hoa don."""
    pix = icon.pixmap(16, 16)
    if pix.isNull():
        return 0
    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    arr = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(
        (img.height(), img.width(), 4))
    return int(((arr[:, :, 3] > 8) & arr[:, :, :3].any(axis=2)).sum())


# ── 1. Toan chieu thuan nghich ────────────────────────────────

def gate_math():
    print("\n== 1. phep chieu pixel <-> du lieu ==")
    for t0, t1, x0, x1 in ((0.0, 2.0, 128.0, 860.0), (0.0, 0.5, 0.0, 40.0),
                           (0.0, 30.0, 200.0, 900.0)):
        worst = 0.0
        for i in range(41):
            time = t0 + (t1 - t0) * i / 40.0
            back = graph.x_to_time(graph.time_to_x(time, t0, t1, x0, x1),
                                   t0, t1, x0, x1)
            worst = max(worst, abs(back - time))
        check("chieu thoi gian round-trip (%.1f..%.1fs)" % (t0, t1),
              worst < 1e-9, True)
    worst_y = 0.0
    for i in range(41):
        shown = 100.0 * i / 40.0
        back = graph.y_to_value(graph.value_to_y(shown, -20.0, 120.0, 10.0,
                                                 300.0), -20.0, 120.0, 10.0,
                                300.0)
        worst_y = max(worst_y, abs(back - shown))
    check("chieu gia tri round-trip (10..300 px)", worst_y < 1e-9, True)

    # Dai gia tri suy bien: khong duoc chia cho 0 o bat ky dau nao.
    flat = graph.value_domain([(0.0, 0.5, "linear"), (1.0, 0.5, "linear")],
                              "opacity", 0.5)
    check("moi moc bang nhau van co chieu cao", flat[1] > flat[0], True)
    near("dai phang cua opacity = min span 10%", round(flat[1] - flat[0], 3),
         10.0, 0.001)
    check("duong phang can giua chu lech ve mot phia",
          (round(flat[0], 2), round(flat[1], 2)), (45.0, 55.0))
    one = graph.value_domain([], "rotation", 45.0)
    check("khong co moc nao thi lay gia tri hien tai",
          (round(one[0], 1), round(one[1], 1)), (40.0, 50.0))
    scale = graph.value_domain([(0.0, 1.0, "linear")], "scale_x", 1.0)
    check("dai phang cua scale tinh theo lan, khong theo %",
          round(scale[1] - scale[0], 3), 0.100)

    # opacity luu tho 0..1 nhung truc tung doc theo %.
    check("opacity 0.4 <-> 40%",
          (graph.display_value("opacity", 0.4),
           graph.raw_value("opacity", 40.0)), (40.0, 0.4))
    check("property khac khong bi chia scale",
          graph.display_value("x", -600.0), -600.0)
    check("nhuan don vi theo tung loai",
          [graph.format_value(p, v) for p, v in
           (("x", 12.4), ("opacity", 0.5), ("rotation", 12.4),
            ("scale_x", 1.234))],
          ["12px", "50%", "12°", "1.23×"])
    check("khong co so am khong duong tren truc",
          [graph.format_value(p, v) for p, v in
           (("x", -0.4), ("rotation", -0.02), ("scale_x", -0.001),
            ("x", -0.6))],
          ["0px", "0°", "0.00×", "-1px"])

    # hit_test do bang pixel, khong theo nguong thoi gian.
    frames = [make_frame(0.0, -600.0), make_frame(1.0, 600.0),
              make_frame(2.0, -100.0)]
    lx0, lx1, ly0, ly1 = 128.0, 860.0, 20.0, 220.0
    lo, hi = graph.value_domain(frames, "x", -600.0)
    args = ("x", 0.0, 2.0, lo, hi, lx0, lx1, ly0, ly1)

    def hit_at(time, value, dx=0.0, dy=0.0, radius=HIT_RADIUS, on=None):
        """Diem bam = dinh moc (time, value) lech dx/dy PIXEL."""
        return graph.hit_test(on if on is not None else frames,
                              graph.time_to_x(time, 0.0, 2.0, lx0, lx1) + dx,
                              graph.value_to_y(graph.display_value("x", value),
                                               lo, hi, ly0, ly1) + dy,
                              *args, radius=radius)

    found = hit_at(1.0, 600.0)
    check("bam dung node thi ra dung node ay",
          (found[0], round(found[1][1], 2)), (1, 600.0))
    check("bam sat trong ban kinh thi van ra node",
          hit_at(1.0, 600.0, dx=HIT_RADIUS - 1.0)[0], 1)
    check("roi mot pixel ra ngoai ban kinh thi mat node",
          hit_at(1.0, 600.0, dx=HIT_RADIUS + 1.0), None)
    check("lech duoi ban kinh o truc doc cung mat node",
          hit_at(1.0, 600.0, dy=HIT_RADIUS + 1.0), None)
    close = [make_frame(1.0, 600.0), make_frame(1.02, -600.0)]
    check("hai moc chong nhau thi bam vao gan nhat",
          hit_at(1.01, 600.0, on=close)[0], 0)


# ── 2. Duong ve = duong cua model ─────────────────────────────

def grab_array(widget):
    """(mang RGBA, he so thu phong) — do truc tiep tren anh widget render ra."""
    widget.update()
    pump(4)
    pix = widget.grab()
    dpr = pix.devicePixelRatio() or 1.0
    img = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    arr = np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.float64)
    return arr, dpr


def curve_row(arr, dpr, lane, time, accent):
    """(dong pixel trung binh, so dong co muc, so doan muc roi rac)."""
    x = int(round(lane.x_of(time) * dpr))
    top = int(round(lane.rect.top() * dpr))
    bottom = int(round(lane.rect.bottom() * dpr))
    if not 0 <= x < arr.shape[1]:
        return None, 0, 0
    target = np.array([accent.red(), accent.green(), accent.blue()], float)
    column = arr[top:bottom + 1, x, :3]
    hit = np.abs(column - target).sum(axis=1) < 150.0
    if not hit.any():
        return None, 0, 0
    rows = np.nonzero(hit)[0]
    runs = int((np.diff(rows) > max(2, int(round(2 * dpr)))).sum()) + 1
    return (rows.mean() + top) / dpr, int(hit.sum()), runs


def gate_curve(view, clip, shots, notes):
    print("\n== 2. duong tren man hinh la duong cua model ==")
    frames = graph.frames_of(clip, "x")
    default = graph.default_value(clip, "x")
    samples = graph.sample_curve(frames, "x", default, 0.0, clip.duration,
                                 samples=61)
    check("sample_curve tra dung so mau", len(samples), 61)
    drift = max(abs(v - interpolate_keyframes(frames, t, default))
                for t, v in samples)
    check("moi mau la mot diem cua interpolate_keyframes", drift < 1e-12, True)
    check("mau dau/cuoi tron hai dau khoang thoi gian",
          (round(samples[0][0], 3), round(samples[-1][0], 3)), (0.0, 2.0))
    times = [t for t, _ in samples]
    check("cac mau tang dan tuyet doi, khong keo nguoc ve trai",
          all(b > a for a, b in zip(times, times[1:])), True)

    arr, dpr = grab_array(view)
    lane = view.lane_for("x")
    rows = {}
    deltas = []
    for time in (0.25, 0.45, 0.72, 1.62):
        want_y = lane.y_of(interpolate_keyframes(frames, time, default))
        got_y, count, _runs = curve_row(arr, dpr, lane, time, color_of("x"))
        near("cot anh tai %.2fs nam tren duong model" % time, got_y, want_y,
             2.5)
        above("cot do duoc co net that (%.2fs)" % time, count, 1)
        rows[time] = got_y
        deltas.append(abs(got_y - want_y))

    # Duong cong la ham MỘT giá trị theo thời gian, nen moi cot chi duoc co
    # mot doan net. Diem cuoi mau ghi nham thanh t0 (tung co) keo mot net
    # cheo nguoc qua ca lane: moi cot te ra hai doan va do la duong cong
    # khong ton tai trong model.
    node_times = [frame_time(f) for f in frames]
    worst_runs, worst_at, cols = 0, None, 0
    for i in range(1, 14):
        time = clip.duration * i / 16.0
        if min(abs(time - nt) for nt in node_times) < 0.08:
            continue
        _y, _c, runs = curve_row(arr, dpr, lane, time, color_of("x"))
        cols += 1
        if runs > worst_runs:
            worst_runs, worst_at = runs, time
    check("moi cot chi co MOT doan net (%d cot, %.3fs)" % (cols, worst_at),
          worst_runs, 1)
    shots["curve"] = (arr, dpr)
    notes.append("lech lon nua giua duong ve va interpolate_keyframes: "
                 "%.2f px (4 cot do bang pixel)" % max(deltas))

    # Doan cong THAT su khac doan thang. Do o 1/4 doan chu khong o 1/2:
    # ease_in_out doi xung nen mid diem cua no TRUNG voi duong thang.
    mid = interpolate_keyframes(frames, 0.25, default)
    straight = frames[0][1] + (frames[1][1] - frames[0][1]) * 0.25
    above("doan ease_in_out lech khoi duong thang", abs(mid - straight), 40.0)

    # Phan chung: xoa bang duong cong thi duong ve PHAI doi theo model.
    originals = dict(EASINGS)
    try:
        for key in list(EASINGS):
            EASINGS[key] = lambda t: min(1.0, max(0.0, t))
        flat_frames = [make_frame(0.0, -600.0, "linear"),
                       make_frame(1.0, 600.0, "linear"),
                       make_frame(2.0, -100.0, "linear")]
        arr2, dpr2 = grab_array(view)
        moved = 0.0
        for time in (0.25, 0.45, 0.72):
            want2 = lane.y_of(interpolate_keyframes(flat_frames, time, default))
            got2, _c2, _r2 = curve_row(arr2, dpr2, lane, time, color_of("x"))
            near("counterfactual: cot anh van theo model khi xoa bang cong",
                 got2, want2, 2.5)
            moved = max(moved, abs(got2 - rows[time]))
        above("counterfactual: cot anh DI CHU that (khoa phan biet duoc)",
              moved, 3.0)
        notes.append("counterfactual: lam phang EASINGS lam %d cot do dich "
                     "%.1f px va van khop model moi" % (3, moved))
    finally:
        EASINGS.clear()
        EASINGS.update(originals)
    arr3, dpr3 = grab_array(view)
    back, _b2, _b3 = curve_row(arr3, dpr3, lane, 0.25, color_of("x"))
    near("bang cong duoc phoi lai nguyen ven", back, rows[0.25], 0.6)


# ── 3. Sua qua lenh that ──────────────────────────────────────

def gutter_runs(arr, dpr, y_top, y_bottom, color=AXIS_TEXT):
    """Cac doan ink doc trong cot nhan gia tri, theo toa do widget.

    Do TREN ANH, khong do bang cong thuc: loi la hai dong chu de len nhau —
    khong crash, khong sai so, chi in ra mot bo so khong doc duoc, nen phai
    dem xem thuc su co bao nhieu dong va no cao bao nhieu pixel.
    """
    x0 = int(round((VALUE_LABEL_RIGHT - 70) * dpr))
    x1 = int(round((VALUE_LABEL_RIGHT + 2) * dpr))
    top = int(round(y_top * dpr))
    bottom = int(round(y_bottom * dpr))
    band = arr[max(0, top):max(0, bottom), max(0, x0):max(0, x1), :3]
    if band.size == 0:
        return []
    target = np.array([color.red(), color.green(), color.blue()], float)
    hit = (np.abs(band - target).sum(axis=2) < 90.0).any(axis=1)
    rows = np.nonzero(hit)[0]
    if not rows.size:
        return []
    runs, start, prev = [], int(rows[0]), int(rows[0])
    for row in rows[1:]:
        # LECH 3 DONG trang moi la hai nhan khac nhau: hai dong nhan 12 px
        # cach nhau (lane 48 px, 5 nhan) de len nhau va in ra mot khoi ink
        # lien mach, nen tach som hon thi khong bao gio phat hien loi.
        if int(row) - prev > 3:
            runs.append((start, prev))
            start = int(row)
        prev = int(row)
    runs.append((start, prev))
    return [((a + top) / dpr, (b + top) / dpr) for a, b in runs]


def send(widget, kind, pos, button=Qt.LeftButton):
    from PySide6.QtGui import QMouseEvent
    held = button if kind in (QEvent.MouseButtonPress,
                              QEvent.MouseButtonDblClick, QEvent.MouseMove) \
        else Qt.MouseButton.NoButton
    QApplication.sendEvent(widget, QMouseEvent(
        kind, QPointF(pos), widget.mapToGlobal(pos.toPoint()), button, held,
        Qt.KeyboardModifier.NoModifier))


def drag(view, lane, from_time, from_value, to_time, to_value, dx=0.0, dy=0.0):
    """Cu keo that, bat dau tai (node + dx/dy pixel) va ket thuc tai diem moi."""
    start = QPointF(lane.x_of(from_time) + dx, lane.y_of(from_value) + dy)
    end = QPointF(lane.x_of(to_time), lane.y_of(to_value))
    send(view, QEvent.MouseButtonPress, start)
    send(view, QEvent.MouseMove, end)
    send(view, QEvent.MouseButtonRelease, end)


def double_click(view, point):
    """Duong that cua nhich kep: Qt bao luon gui Press -> DblClick -> Release.

    Gui rieng mot event DblClick thi khong co Release kep theo, va view con
    giu ban keo du — moc them sau do tinh theo ban keo ma nguoi dung khong
    he tao ra.
    """
    send(view, QEvent.MouseButtonPress, point)
    send(view, QEvent.MouseButtonDblClick, point)
    send(view, QEvent.MouseButtonRelease, point)


def gate_editing(win, view, clip):
    print("\n== 3. keo / them / xoa qua chuot that ==")
    model = win.timeline_panel.model
    stack = win.timeline_panel.undo_stack
    clip_id = clip.clip_id
    lane = view.lane_for("x")

    start = stack.undo_count
    drag(view, lane, 2.0, -100.0, 1.5, 250.0)
    pump()
    frames = model.get_clip(clip_id).keyframes["x"]
    check("keo doi ca thoi gian lan gia tri",
          (round(frame_time(frames[2]), 3), round(frame_value(frames[2]), 1)),
          (1.5, 250.0))
    check("keo giu duong cong cua moc", frame_ease(frames[2]), "ease_out_expo")
    check("mot cu keo = mot buoc undo", stack.undo_count - start, 1)
    sel = view._selected
    check("moc vua keo duoc chon",
          sel is not None and sel[0] == "x" and abs(sel[1] - 1.5) < 0.01, True)

    # Phan chung cua duong bam: bat dau NGOAI ban kinh thi cung cu chi khong
    # duoc cham vao model. Bam TRONG ban kinh thi phai keo duoc — hai mot
    # doan cua cung nguong, khong phai hai loi khac nhau.
    stack.undo()
    pump()
    quiet = stack.undo_count
    drag(view, view.lane_for("x"), 2.0, -100.0, 0.2, -500.0,
         dx=HIT_RADIUS + 4.0, dy=HIT_RADIUS + 4.0)
    pump()
    frames = model.get_clip(clip_id).keyframes["x"]
    check("counterfactual: ngoai ban kinh thi khong sua duoc",
          (round(frame_time(frames[2]), 3), round(frame_value(frames[2]), 1)),
          (2.0, -100.0))
    check("counterfactual khong de lai lenh rac trong undo",
          stack.undo_count, quiet)
    check("ngoai ban kinh thi cung khong chon nham", view._selected, None)
    drag(view, view.lane_for("x"), 2.0, -100.0, 1.5, 250.0,
         dx=HIT_RADIUS - 5.0, dy=0.0)
    pump()
    frames = model.get_clip(clip_id).keyframes["x"]
    check("trong ban kinh thi van keo duoc (nguong co hai mot)",
          (round(frame_time(frames[2]), 3), round(frame_value(frames[2]), 1)),
          (1.5, 250.0))
    stack.undo()
    pump()
    frames = model.get_clip(clip_id).keyframes["x"]
    check("undo tra dung moc cu",
          (round(frame_time(frames[2]), 3), round(frame_value(frames[2]), 1)),
          (2.0, -100.0))
    stack.redo()
    pump()
    frames = model.get_clip(clip_id).keyframes["x"]
    check("redo dat lai dung moc moi",
          (round(frame_time(frames[2]), 3), round(frame_value(frames[2]), 1)),
          (1.5, 250.0))
    stack.undo()
    pump()

    # Bam vao node roi tha tai cho: khong duoc de lai lenh rong.
    before = stack.undo_count
    drag(view, view.lane_for("x"), 0.0, -600.0, 0.0, -600.0)
    pump()
    check("keo khong di = khong co buoc undo", stack.undo_count, before)

    # Nhich kep vao cho trong: them moc dung tren duong cong.
    lane = view.lane_for("opacity")
    before = len(model.get_clip(clip_id).keyframes["opacity"])
    quiet = stack.undo_count
    double_click(view, QPointF(lane.x_of(0.8), lane.y_of(0.62)))
    pump()
    op = model.get_clip(clip_id).keyframes["opacity"]
    check("nhich kep them duoc moc", len(op) - before, 1)
    check("them moc = mot buoc undo", stack.undo_count - quiet, 1)
    check("nhich kep xong thi khong con ban keo du", view._drag, None)
    new = [f for f in op if abs(frame_time(f) - 0.8) < 0.02]
    check("moc moi dung vi tri va gia tri bam xuong",
          (round(frame_time(new[0]), 2), round(frame_value(new[0]), 2)),
          (0.8, 0.62))
    check("moc moi noi tiep duong cong cua doan truoc",
          frame_ease(new[0]), "linear")

    # Nhich kep vao DINH node co san khong duoc nhan doi node, cung khong
    # duoc de lai mot buoc undo rong.
    before = len(model.get_clip(clip_id).keyframes["opacity"])
    quiet = stack.undo_count
    double_click(view, QPointF(lane.x_of(0.8), lane.y_of(0.62)))
    pump()
    check("nhich kep vao moc san khong tao moc trung",
          len(model.get_clip(clip_id).keyframes["opacity"]), before)
    check("nhich kep vao moc san khong tao buoc undo",
          stack.undo_count, quiet)
    check("nhich kep lenh node cung khong con ban keo du", view._drag, None)

    # Xoa bang phim Delete.
    view.setFocus()
    pump()
    check("view nhan duoc focus de bam phim", view.hasFocus(), True)
    view._selected = ("opacity", frame_time(new[0]))
    from PySide6.QtGui import QKeyEvent
    QApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete,
                                           Qt.KeyboardModifier.NoModifier))
    pump()
    check("phim Delete xoa moc dang chon",
          len(model.get_clip(clip_id).keyframes["opacity"]), before - 1)
    stack.undo()
    pump()
    check("undo cua Delete tra lai dung frame",
          [round(frame_value(f), 2) for f in
           model.get_clip(clip_id).keyframes["opacity"]
           if abs(frame_time(f) - 0.8) < 0.02], [0.62])
    stack.undo()
    pump()

    # Them moc tai playhead cho moi dang trong.
    model.playhead = clip.start_time + 1.0
    pump()
    before = {p: len(model.get_clip(clip_id).keyframes[p])
              for p in ("x", "opacity")}
    print("  trang thai truoc add_at_playhead: drag=%r opacity=%r"
          % (view._drag, model.get_clip(clip_id).keyframes["opacity"]))
    check("khong con ban keo du sau moi lan thao tac chuot", view._drag, None)
    check("them moc tai playhead", view.add_at_playhead(), True)
    after = {p: len(model.get_clip(clip_id).keyframes[p])
             for p in ("x", "opacity")}
    check("lane chua co moc o playhead thi co them",
          after["opacity"] - before["opacity"], 1)
    check("lane da co moc o playhead khong bi nhan doi", after["x"],
          before["x"])
    at = [f for f in model.get_clip(clip_id).keyframes["opacity"]
          if abs(frame_time(f) - 1.0) < 0.02]
    others = [f for f in graph.frames_of(model.get_clip(clip_id), "opacity")
              if abs(frame_time(f) - 1.0) > 0.02]
    check("moc moi nam DUNG TREN duong cong", round(frame_value(at[0]), 3),
          round(interpolate_keyframes(others, 1.0,
                                      graph.default_value(
                                          model.get_clip(clip_id),
                                          "opacity")), 3))
    model.playhead = clip.start_time + 9.0
    check("playhead ngoai clip thi khong them duoc", view.add_at_playhead(),
          False)


# ── 4. Menu duong cong ────────────────────────────────────────

def gate_menu(view, clip):
    print("\n== 4. menu 9 duong cong cua moc ==")
    model = view._model
    clip_id = view.clip_id
    frame = graph.frames_of(model.get_clip(clip_id), "x")[0]
    menu = view.curve_menu("x", frame)
    baseline = orphan_baseline(menu)
    entries = [a for a in menu.actions() if a.isEnabled() and a.isCheckable()]
    check("menu co dung mot muc moi duong cong", len(entries), len(EASINGS))
    check("moi muc mang ten duong cong de truy", [a.data() for a in entries],
          list(EASINGS))
    check("moi muc co nhan tieng Viet dung bang",
          all(a.text() == EASE_LABELS[a.data()] for a in entries), True)
    check("moc dang o dau thi muc ay duoc chot",
          [a.data() for a in entries if a.isChecked()], [frame_ease(frame)])
    group = entries[0].actionGroup()
    check("cac muc nam trong MỘT nhom doc nhat",
          all(a.actionGroup() is group for a in entries), True)
    check("nhom do bat ky doc nhat", group.isExclusive(), True)
    check("moi muc co slot ngoai Qt", all(action_connection(a) > baseline
                                          for a in entries), True)
    remove = [a for a in menu.actions() if a.data() == "__remove__"]
    check("menu co muc xoa rieng, khong vao nhom chon", len(remove), 1)
    above("muc xoa in ra duoc muc (khong phai hoa don)", ink(remove[0].icon()),
          10)

    stack = view._undo
    before = stack.undo_count
    target = next(a for a in entries if a.data() == "ease_in_expo")
    target.trigger()
    pump()
    now = graph.frames_of(model.get_clip(clip_id), "x")[0]
    check("click menu doi duong cong trong model", frame_ease(now),
          "ease_in_expo")
    check("click menu khong doi gia tri hay thoi gian",
          (round(frame_time(now), 3), round(frame_value(now), 2)),
          (round(frame_time(frame), 3), round(frame_value(frame), 2)))
    check("click menu la mot buoc undo that", stack.undo_count - before, 1)
    check("sau khi click chi con DUNG MỘT muc duoc chot",
          sum(1 for a in entries if a.isChecked()), 1)
    stack.undo()
    pump()
    check("hoan tac click menu tra lai cong cu",
          frame_ease(model.get_clip(clip_id).keyframes["x"][0]),
          frame_ease(frame))

    before = stack.undo_count
    remove[0].trigger()
    pump()
    check("muc xoa xoa het moc do",
          len(model.get_clip(clip_id).keyframes["x"]), 2)
    check("muc xoa cung la mot buoc undo", stack.undo_count - before, 1)
    stack.undo()
    pump()
    check("undo cua muc xoa tra lai dung frame",
          (round(frame_time(model.get_clip(clip_id).keyframes["x"][0]), 3),
           frame_ease(model.get_clip(clip_id).keyframes["x"][0])),
          (round(frame_time(frame), 3), frame_ease(frame)))
    stack.undo()
    pump()


# ── 5. Dong bo voi timeline ───────────────────────────────────

TEAL = np.array([64.0, 224.0, 208.0])


def teal_mask(arr):
    return np.abs(arr[:, :, :3] - TEAL).sum(axis=2) < 150.0


def playhead_column(arr, base, dpr, lane):
    """Cot co them net mau playhead so voi anh goc -> thoi diem do duoc."""
    added = (teal_mask(arr).sum(axis=0) - base.sum(axis=0)).astype(np.int64)
    x = int(added.argmax())
    return lane.time_at(x / dpr), int(added.max())


def node_times(item, prop):
    return sorted(round(node.time_sec, 3) for node in item._keyframe_nodes
                  if node.property_key == prop)


def gate_sync(win, view, clip, notes):
    print("\n== 5. playhead va kim cuong tren timeline ==")
    model = win.timeline_panel.model
    item = win.timeline_panel.scene._clip_items[clip.clip_id]
    lane = view.lane_for("x")

    # Anh goc: playhead NGOAI clip -> duoi net cua no khong duoc ton tai.
    model.playhead = clip.start_time + 9.0
    pump()
    base_arr, dpr = grab_array(view)
    base = teal_mask(base_arr)
    check("anh goc chua playhead khong co cot nao them",
          playhead_column(base_arr, base, dpr, lane)[1], 0)
    for local in (0.35, 1.20):
        model.playhead = clip.start_time + local
        pump()
        arr, _ = grab_array(view)
        got_t, extra = playhead_column(arr, base, dpr, lane)
        near("do duoc vi tri playhead tai %.2fs" % local, got_t, local, 0.02)
        above("net playhead o %.2fs dai du do" % local, extra, 20)
    notes.append("cot playhead do duoc o dung 0.35s/1.20s; ngoai clip thi "
                 "khong con cot nao them")

    # Moc doi thoi gian thi vien kim cuong phai di theo — KHONG goi _sync
    # tay: signal edited cua view moi la duong that cua app.
    before = node_times(item, "x")
    check("bo kim cuong khop model truoc khi keo", before,
          sorted(round(frame_time(f), 3) for f in
                 graph.frames_of(model.get_clip(clip.clip_id), "x")))
    drag(view, lane, 0.0, -600.0, 0.4, -600.0)
    pump()
    after = node_times(item, "x")
    check("kim cuong timeline di theo moc tren do thi",
          (0.4 in after, 0.0 in after), (True, False))
    check("chi dich mot moc, hai moc kia giu nguyen",
          sorted(set(after) - set(before)), [0.4])
    view._undo.undo()
    pump()
    check("undo tu do thi (khong qua hop thoai) cung doi lai kim cuong",
          node_times(item, "x"), before)


# ── 6. Diem vao ───────────────────────────────────────────────

def gate_entries(win, model, clip, plain_clip):
    print("\n== 6. diem vao ==")
    scene_items = {}
    for gitem in win.timeline_panel.scene.items():
        cm = getattr(gitem, "clip_model", None)
        if cm is not None:
            scene_items[cm.clip_id] = gitem
    _menu, rows = scene_items[clip.clip_id]._build_context_menu()
    check("clip co moc: menu co muc do thi",
          [a.text() for a in rows],
          ["Cắt tại Playhead", "Nhân bản clip", "Đồ thị đường cong…",
           "Xóa clip"])
    _menu2, rows2 = scene_items[plain_clip.clip_id]._build_context_menu()
    check("clip chua co moc: menu khong moi moc ao",
          [a.text() for a in rows2],
          ["Cắt tại Playhead", "Nhân bản clip", "Xóa clip"])
    check("moi muc menu in ra duoc icon",
          [a.text() for a in rows if ink(a.icon()) < 10], [])

    routed = []
    win.timeline_panel.keyframeGraphRequested.connect(routed.append)
    win.timeline_panel.scene.graph_requested.emit(clip.clip_id)
    pump()
    check("scene phat duoc len panel", routed, [clip.clip_id])

    first = win._open_keyframe_graph(clip.clip_id)
    again = win._open_keyframe_graph(plain_clip.clip_id)
    check("mo clip khac dung lai MỘT hop thoai", again is first, True)
    check("hop thoai tro dung clip duoc mo", again.view.clip_id,
          plain_clip.clip_id)
    check("hop thoai khong chan bang hinh", again.isModal(), False)
    again.set_clip(clip.clip_id)
    check("doi clip thi nhan deu doi theo",
          again.lbl_title.text().startswith("Đồ thị đường cong — " + clip.name),
          True)
    again.close()

    # Nut o the thuoc tinh dung cung mot quy tac voi menu.
    win.properties_panel.show_clip_properties(model.get_clip(
        plain_clip.clip_id))
    pump()
    check("clip tinh: an nut do thi",
          win.properties_panel.current_editor.btn_graph.isVisibleTo(
              win.properties_panel), False)
    win.properties_panel.show_clip_properties(model.get_clip(clip.clip_id))
    pump()
    editor = win.properties_panel.current_editor
    check("clip co moc: hien nut do thi",
          editor.btn_graph.isVisibleTo(win.properties_panel), True)
    opened = editor._open_keyframe_graph()
    check("nut do thi mo dung clip dang chon", opened.clip_id, clip.clip_id)
    opened.close()


# ── 7. Layout do duoc ────────────────────────────────────────

def gate_layout(view, clip, shots, tag=None):
    print("\n== 7. do layout (%s) ==" % (tag or clip.name))
    lanes = view._lanes(clip)
    check("moi property mot lane", [l.prop for l in lanes],
          list(graph.animated_properties(clip)))
    heights = [round(float(l.rect.height()), 1) for l in lanes]
    check("lane deu nhau", len(set(heights)), 1)
    above("moi lane du cao de keo", min(l.rect.height() for l in lanes),
          LANE_MIN_HEIGHT - 1e-9)
    gaps = [round(lanes[i + 1].rect.top() - lanes[i].rect.bottom(), 1)
            for i in range(len(lanes) - 1)]
    check("giua hai lane du cho hai dong nhan", gaps,
          [float(LANE_GAP)] * len(gaps))
    check("nhan thoi gian con nam trong vung ve",
          lanes[-1].rect.bottom() + 5 + AXIS_HEIGHT <= view.height(), True)
    check("khong co lane nao tran ra ngoai",
          all(l.rect.right() <= view.width() - 1 for l in lanes), True)
    check("le trai du cho nhan va cot so", lanes[0].rect.left(), GUTTER_LEFT)

    big = QFont(view.font())
    big.setPointSizeF(9.0)
    big.setBold(True)
    small = QFont(view.font())
    small.setPointSizeF(8.4)
    nf, vf = QFontMetrics(big), QFontMetrics(small)
    tight = []
    for lane in lanes:
        name_w = nf.horizontalAdvance(graph.PROPERTY_LABELS[lane.prop])
        vals = [graph.format_value(lane.prop, graph.raw_value(lane.prop, v))
                for v in (lane.lo, lane.hi, (lane.lo + lane.hi) / 2.0)]
        val_w = max(vf.horizontalAdvance(t) for t in vals)
        # Le ngang: ten bat dau o x=8, cot so ket thuc o VALUE_LABEL_RIGHT.
        tight.append((lane.prop, (VALUE_LABEL_RIGHT - val_w) - (8 + name_w)))
    print("  khoang trong le trai:", tight)
    check("ten lane va cot so khong de len nhau",
          [p for p, g in tight if g < 2], [])

    # Le doc: nhan ten o GIUA lane, gan nhat voi cot so cua vach tren/duoi.
    name_h, val_box = vf.height(), 16.0
    v_clear = [round(l.rect.height() / 2.0 - name_h / 2.0 - val_box / 2.0, 1)
               for l in lanes]
    print("  le doc ten/cot so:", v_clear)
    above("con le doc giua ten lane va cot so gan nhat", min(v_clear), 1.0)

    arr, dpr = grab_array(view)
    if tag is None:
        shots["lanes"] = (arr, dpr)
    above("do thi ve co net that", int((arr[:, :, 3] > 0).sum()), 20000)
    check("khong vung nao con trong o goc ve",
          arr[0, 0, 3] > 0 and arr[-1, -1, 3] > 0, True)

    # COT SO PHAI DOC DUOC. Mot lane 48 px (chieu cao that khi mo 6 property)
    # khong chua noi 5 dong chu 16 px: chung de len nhau thanh mot bo so. Do
    # bang pixel tren anh grab — moi dong nhan phai ngan hon mot dong chu, va
    # lane phai co it nhat hai dong (tren/duoi) de con doc duoc thang do.
    text_h = float(QFontMetrics(small).height())
    collided = []
    counted = []
    for lane in lanes:
        runs = gutter_runs(arr, dpr, lane.rect.top(), lane.rect.bottom())
        want = label_divisions(lane.rect.height(), text_h) + 1
        counted.append((lane.prop, len(runs), want))
        for a, b in runs:
            if b - a > text_h + 3.0:
                collided.append((lane.prop, "de len nhau: %d px" % round(b - a)))
        if len(runs) < want:
            collided.append((lane.prop, "%d dong, phai >= %d" % (len(runs),
                                                                 want)))
    print("  so dong nhan moi lane (thuc/dinh):", counted)
    check("cot so khong de len nhau o lane nao (cao chu %.0fpx)" % text_h,
          collided, [])

    # Ca hai loai va cham cung mot luc: trong mot lane VA giua hai lane ke
    # nhau (nhan o dinh/day lane keo dai qua le, de len lane lang gieng).
    every = gutter_runs(arr, dpr, 0.0, float(view.height()))
    merged = [(round(a, 1), round(b - a, 1)) for a, b in every
              if b - a > text_h + 3.0]
    touching = [(round(every[i][1], 1), round(every[i + 1][0] - every[i][1], 1))
                for i in range(len(every) - 1) if every[i + 1][0] - every[i][1] < 2]
    print("  %d dong nhan ca cot, cao nhat=%.1fpx, le hep nhat=%.1fpx"
          % (len(every), max([b - a for a, b in every] or [0]),
             min([every[i + 1][0] - every[i][1]
                  for i in range(len(every) - 1)] or [0])))
    check("ca cot so khong co dong nao doi cho nhau", [merged, touching],
          [[], []])
    check("so khoang nhan tu theo chieu cao lane",
          [label_divisions(h, text_h) for h in (48.3, 70.0, 90.0, 380.0)],
          [1, 2, 2, 4])


# ── 8. Bang chung hinh ───────────────────────────────────────

def evidence(shots, notes):
    from PySide6.QtCore import QRectF
    order = [k for k in ("open", "after", "lanes") if k in shots]
    scale = 0.62
    box_w = int(max(a.shape[1] for a, _ in shots.values()) * scale)
    box_h = int(max(a.shape[0] for a, _ in shots.values()) * scale)
    pad, head = 18, 62
    foot = 22 * len(notes) + 8
    width = pad * 2 + (box_w + pad) * len(order)
    height = head + box_h + pad + foot
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#101418"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    title = QFont("Segoe UI", 11)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QPen(QColor("#E6ECFF")))
    p.drawText(pad, 30, "#65 do thi duong cong keyframe: duong ve = duong cua"
                        " model, do bang pixel tren anh grab")
    small = QFont("Segoe UI", 9)
    captions = {"open": "1. mo do thi (clip 2s, x co 3 moc)",
                "after": "2. sau khi keo / them / xoa moc",
                "lanes": "3. 6 property, 6 lane duoc bo cong"}
    x = pad
    for key in order:
        arr, _dpr = shots[key]
        buf = np.ascontiguousarray(arr.astype(np.uint8))
        src = QImage(buf.data, arr.shape[1], arr.shape[0],
                     arr.shape[1] * 4, QImage.Format.Format_RGBA8888).copy()
        p.drawImage(QRectF(x, head, box_w, box_h), src)
        p.setPen(QPen(QColor("#5A6472"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x, head, box_w, box_h))
        p.setFont(small)
        p.setPen(QPen(QColor("#9AA4B2")))
        p.drawText(x, head - 8, captions.get(key, key))
        x += box_w + pad
    p.setFont(small)
    p.setPen(QPen(QColor("#C8CBD4")))
    y = head + box_h + 22
    for line in notes:
        p.drawText(pad, y, line)
        y += 22
    p.end()
    img.save(SHEET)
    print("  saved", os.path.relpath(SHEET, ROOT))


# ── Chay ──────────────────────────────────────────────────────

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    shots = {}
    notes = []

    gate_math()

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1680, 940)
    win.show()
    pump(20)
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()

    model = win.timeline_panel.model
    track = model.add_track(track_type_for_media("text"), "Graph")
    clip = model.add_clip(track.track_id, "", "text", 0.0, 2.0, "Chuyen dong")
    clip.transform.x = -600.0
    clip.add_keyframe("x", 0.0, -600.0, "ease_in_out")
    clip.add_keyframe("x", 1.0, 600.0, "linear")
    clip.add_keyframe("x", 2.0, -100.0, "ease_out_expo")
    clip.add_keyframe("opacity", 0.0, 0.0, "linear")
    clip.add_keyframe("opacity", 2.0, 1.0, "ease_in_cubic")
    plain_track = model.add_track(track_type_for_media("text"), "Plain")
    plain = model.add_clip(plain_track.track_id, "", "text", 3.0, 2.0, "Tinh")
    win._sync_canvas()
    pump()
    for c in (clip, plain):
        win.timeline_panel.scene._clip_items[c.clip_id] \
            .sync_keyframe_nodes_from_model()

    dlg = KeyframeGraphDialog(win, clip.clip_id)
    dlg.move(400, 240)
    dlg.show()
    pump()
    view = dlg.view
    shots["open"] = grab_array(view)

    gate_layout(view, model.get_clip(clip.clip_id), shots)
    gate_curve(view, model.get_clip(clip.clip_id), shots, notes)
    gate_editing(win, view, model.get_clip(clip.clip_id))
    shots["after"] = grab_array(view)
    gate_menu(view, model.get_clip(clip.clip_id))
    gate_sync(win, view, model.get_clip(clip.clip_id), notes)
    gate_entries(win, model, clip, plain)

    notes.append("moi sua (keo/them/xoa/doi cong) di qua UndoStack cua "
                 "timeline: undo/redo tra lai dung frame ca duong cong")
    notes.append("ngoai ban kinh bam %d px thi cung cu keo khong cham vao "
                 "model; trong ban kinh thi keo duoc" % (HIT_RADIUS + 4))

    print("\n== 9. mo 6 lane ==")
    wide_track = model.add_track(track_type_for_media("text"), "Wide")
    wide = model.add_clip(wide_track.track_id, "", "text", 6.0, 7.0,
                          "Du property")
    for i, prop in enumerate(graph.PROPERTY_ORDER):
        first, second = LANE_FIXTURE[prop]
        wide.add_keyframe(prop, 0.0, first, "ease_in_out")
        wide.add_keyframe(prop, 1.0 + i, second, "ease_out")
    win._sync_canvas()
    pump()
    win.timeline_panel.scene._clip_items[wide.clip_id] \
        .sync_keyframe_nodes_from_model()
    dlg.set_clip(wide.clip_id)
    pump()
    wide_clip = model.get_clip(wide.clip_id)
    gate_layout(view, wide_clip, shots, tag="6 lane")
    check("sau property sau lane va dung thu tu do thi",
          [l.prop for l in view._lanes(wide_clip)],
          list(graph.PROPERTY_ORDER))
    shots["lanes"] = grab_array(view)
    dlg.close()

    print("\nsummary:", "ALL PASS" if not fails else
          "FAILURES\n  " + "\n  ".join(fails))
    evidence(shots, notes)

    win.close()
    pump(8)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
