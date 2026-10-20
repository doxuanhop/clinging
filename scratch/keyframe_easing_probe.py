"""
scratch/keyframe_easing_probe.py
Bằng chứng cho #40 ĐƯỜNG CONG NỘI SUY KEYFRAME.

Bốn câu hỏi probe này phải trả lời bằng số đo, không bằng lời văn:
  1. EASINGS có thật là đường cong không — do 101 mẫu mỗi cong: đầu/cuộc, đơn
     điệu, nằm trong [0,1], và giá trị giữa đoạn khác nhau giữa các cong.
  2. Preview và export có dùng CHUNG một lời nội suy không — đo vị trí khối đỏ
     trên ảnh xuất của FrameComposer và ảnh grab từ Player Canvas thật, so với
     giá trị đường cong dự đoán.
  3. Đường cong có sống qua undo/redo, kéo thả, auto-keyframe và cắt-luu-mo?
  4. Người dùng chốt được đường cong bằng chuột thật chưa — menu của node,
     action thật được trigger, model thật thay đổi và hoàn tác được.

Phản chứng (counterfactual): bảng EASINGS bị giả lập thành linear giữa chứng.
Mọi khoa "các cong phải cho giá trị khác nhau" NO. Một khoa không thể sai thì
không được tính là khoa.

Chạy: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/keyframe_easing_probe.py
"""

import json
import os
import shutil
import sys
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")
TMP = os.path.join(OUT, "kf_ease_tmp")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

import core.project_storage as project_storage
from core.keyframe_manager import (
    DEFAULT_EASE, EASINGS, EASE_LABELS, apply_ease, frame_ease, frame_time,
    frame_value, interpolate_keyframes, make_frame, normalize_ease,
)
from core.timeline_model import TimelineModel, track_type_for_media
from diagnostics import action_connection, orphan_baseline

W, H = 640, 360
CLINQ = os.path.join(TMP, "project.clinq")
LEGACY = os.path.join(TMP, "legacy.clinq")
EVIDENCE = os.path.join(OUT, "clinging_keyframe_easing.png")

X0, X1 = -700.0, 700.0
T_MID = 0.5
PX_TOL = 3.0          # dung sai tam khoi do tren anh 640x360
EASES_MEASURED = ("linear", "ease_in", "ease_out", "ease_in_cubic",
                  "ease_out_expo", "ease_in_expo")
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
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
    print("%-58s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def below(label, got, limit):
    ok = got is not None and got < limit
    if not ok:
        fails.append("%s: got %r want < %r" % (label, got, limit))
    print("%-58s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


# ── Nguon do ────────────────────────────────────────────────────

def write_probe_media():
    """Que do la clip CHỮ, khong can file media.

    Clip anh bi "fit" day canvas nen cham bien va mat thong tin vi tri; chu thi
    nho, di tron doan ma khong bi cat. Ca hai duong deu ve chu qua
    core.text_paint, nen so duoc la so cung mot lobe ve.
    """
    os.makedirs(TMP, exist_ok=True)


def to_array(image) -> np.ndarray:
    qimage = image.toImage() if hasattr(image, "toImage") else image
    img = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.float64)


def centroid_x(arr):
    """Tam nut theo do do (R - G): tra None neu khung hinh rong."""
    weight = np.clip(arr[:, :, 0] - arr[:, :, 1], 0.0, None)
    total = float(weight.sum())
    if total < 500.0:
        return None
    columns = weight.sum(axis=0)
    xs = np.arange(arr.shape[1], dtype=np.float64)
    return float((columns * xs).sum() / total)


def clear_model(win):
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    model.project_ratio = "16:9"
    model.playhead = 0.0
    return model


def build_eased_clip(win, ease):
    """Mot clip chu, hai keyframe x; keyframe dau mang duong cong `ease`."""
    model = clear_model(win)
    track = model.add_track(track_type_for_media("text"), "Easing")
    clip = model.add_clip(track.track_id, "", "text", 0.0, 2.0, "8")
    clip.transform.x = X0
    clip.transform.y = 0.0
    clip.font_color = "#FF2020"
    clip.font_size = 220.0
    clip.add_keyframe("x", 0.0, X0, ease)
    clip.add_keyframe("x", 1.0, X1, "linear")
    win._sync_canvas()
    resync_nodes(win, clip)
    return model, clip


def clip_item_for(win, clip):
    for item in win.timeline_panel.scene.items():
        if getattr(item, "clip_model", None) is clip:
            return item
    return None


def resync_nodes(win, clip):
    """Vẽ lại kim cương trên timeline qua đúng slot mà production nối.

    ClipItem của một clip vừa được add_clip sinh ra khi model còn TRỐNG keyframe
    (add_clip phát clipAdded trước khi probe kịp ghi keyframe). Trong app thật,
    chính `ClipPropertiesWidget.keyframeStateChanged` gọi lại slot này sau mỗi
    lần bấm nút kim cương (properties_panel.py:1010), nên probe đi cùng đường.
    """
    item = clip_item_for(win, clip)
    if item is not None:
        item.sync_keyframe_nodes_from_model()
    return item


def export_frame(model, t):
    from core.frame_composer import FrameComposer
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def project_rect(win):
    """Vùng hiển thị thật của preview — rect của viền do _setup_scene vẽ.

    sceneRect của scene bị nong thêm bằng margin tay nắm của item
    (HANDLE_SIZE + 4), nên lấy sceneRect so với ảnh xuất sẽ lệch ~1.2% khung
    và làm hỏng phép đo tam khoi khi khoi cham bien.
    """
    return win.preview_panel.canvas._border_rect.rect()


def preview_frame(win):
    """Vẽ đúng khung dự án mà Player Canvas đang hiển thị, rồi hạ về cỡ xuất."""
    from core.canvas_utils import ASPECT_RATIOS
    rect = project_rect(win)
    cw, ch = int(rect.width()), int(rect.height())
    img = QImage(cw, ch, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        scene = win.preview_panel.canvas.scene()
        scene.render(painter, QRectF(0, 0, cw, ch), rect)
    finally:
        painter.end()
    # Cung mot buoc ha co nhu FrameComposer: ve o canvas project roi scale ve output.
    return img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def measure_paths(win, model, ease):
    """Do hai dau va giua doan o CA HAI duong — tat ca qua code sản xuất."""
    win._sync_canvas_frames_at_time(0.0)
    c0e = centroid_x(to_array(export_frame(model, 0.0)))
    c0p = centroid_x(to_array(preview_frame(win)))
    win._sync_canvas_frames_at_time(1.0)
    c1e = centroid_x(to_array(export_frame(model, 1.0)))
    c1p = centroid_x(to_array(preview_frame(win)))
    win._sync_canvas_frames_at_time(T_MID)
    export_img = export_frame(model, T_MID)
    preview_img = preview_frame(win)
    return {"ease": ease, "c0_export": c0e, "c1_export": c1e,
            "c0_preview": c0p, "c1_preview": c1p,
            "mid_export": centroid_x(to_array(export_img)),
            "mid_preview": centroid_x(to_array(preview_img)),
            "export_img": export_img, "preview_img": preview_img}


# ── 1. Bang duong cong ──────────────────────────────────────────

def gate_curve_table():
    check("so duong cong trong bang", len(EASINGS), 9)
    check("moi duong cong co nhan tieng Viet",
          sorted(EASINGS) == sorted(EASE_LABELS), True)
    for name in sorted(EASINGS):
        samples = [apply_ease(name, i / 100.0) for i in range(101)]
        check("cong %s: f(0)=0 va f(1)=1" % name,
              abs(samples[0]) < 1e-12 and abs(samples[-1] - 1.0) < 1e-12, True)
        check("cong %s: khong overshoot ra ngoai [0,1]" % name,
              all(-1e-12 <= s <= 1.0 + 1e-12 for s in samples), True)
        check("cong %s: don dieu tang" % name,
              all(samples[i + 1] >= samples[i] - 1e-12 for i in range(100)), True)

    mids = {name: apply_ease(name, 0.5) for name in sorted(EASINGS)}
    check("cong cham dan duoi 0.5 o giua doan",
          all(mids[n] < 0.5 - 1e-6 for n in
              ("ease_in", "ease_in_cubic", "ease_in_expo")), True)
    check("cong nhanh dan tren 0.5 o giua doan",
          all(mids[n] > 0.5 + 1e-6 for n in
              ("ease_out", "ease_out_cubic", "ease_out_expo")), True)
    check("linear o giua doan dung bang 0.5", abs(mids["linear"] - 0.5), 0.0)
    above("so gia tri giua doan phan biet nhau",
          len({round(v, 6) for v in mids.values()}), 6)
    near("expo cham o giua doan = 2^-5", mids["ease_in_expo"], 0.03125, 1e-4)
    near("expo nhanh o giua doan = 1-2^-5", mids["ease_out_expo"], 0.96875, 1e-4)


# ── 2. Funnel noi suy ───────────────────────────────────────────

def predict(ease, t=T_MID):
    return X0 + (X1 - X0) * apply_ease(ease, t)


def funnel_value(ease, t=T_MID):
    return interpolate_keyframes([make_frame(0.0, X0, ease),
                                  make_frame(1.0, X1, "linear")], t, 0.0)


def gate_funnel():
    for name in sorted(EASINGS):
        near("funnel theo cong %s" % name, funnel_value(name), predict(name), 1e-6)
    vals = {round(funnel_value(n), 6) for n in sorted(EASINGS)}
    above("funnel sinh gia tri phan biet giua cac cong", len(vals), 6)
    check("sau keyframe cuoi gi gia tri cuoi",
          round(funnel_value("ease_in_expo", 3.0), 3), round(X1, 3))
    check("truoc keyframe dau gi gia tri dau",
          round(funnel_value("ease_in_expo", -1.0), 3), round(X0, 3))
    check("ten cong la quy ve linear, khong noi",
          funnel_value("khong_ton_tai"), predict("linear"))
    check("frame 2 phan tu doc nhu linear",
          interpolate_keyframes([(0.0, X0), (1.0, X1)], T_MID, 0.0),
          predict("linear"))
    check("frame 3 phan tu giu duong cong",
          frame_ease(make_frame(0.0, X0, "ease_out")), "ease_out")
    check("make_frame luon tra 3 phan tu", len(make_frame(1.0, 2.0)), 3)
    check("normalize_ease khong tra ten la", normalize_ease("rubbish"),
          DEFAULT_EASE)
    near("cong nam tren keyframe A, ap cho doan A->B",
         interpolate_keyframes([make_frame(0.0, 0.0, "ease_out"),
                                make_frame(1.0, 100.0, "ease_in")], 0.5, 0.0),
         75.0, 1e-6)


def counterfactual_funnel():
    """Gia lap EASINGS = linear giua chung: moi khoa phan biet PHAI NO."""
    originals = dict(EASINGS)
    rows = []
    try:
        for key in list(EASINGS):
            EASINGS[key] = lambda t: min(1.0, max(0.0, t))
        flat = {round(funnel_value(n), 6) for n in sorted(EASINGS)}
        rows.append(("gia tri gom lai thanh MOT khi xoa bang cong",
                     len(flat), 1))
        rows.append(("linear van o giua doan khi bang cong bi xoa",
                     flat.pop(), round(predict("linear"), 6)))
    finally:
        EASINGS.clear()
        EASINGS.update(originals)
    back = {n: round(funnel_value(n), 6) for n in sorted(EASINGS)}
    rows.append(("bang cong duoc phoi lai nguyen ven",
                 back, {n: round(predict(n), 6) for n in sorted(EASINGS)}))
    rows.append(("khoa phan biet sau khi phoi lai", len(back) > 6, True))
    for label, got, want in rows:
        check("counterfactual: " + label, got, want)


def gate_one_funnel_only():
    """Khong cho phep noi suy boi o ngoai — thu doan nay no neu co ai tu che."""
    for path in (os.path.join(ROOT, "core", "frame_composer.py"),
                 os.path.join(ROOT, "ui", "main_window.py")):
        text = open(path, encoding="utf-8").read()
        name = os.path.basename(path)
        check("%s goi model 6 lan (x, y, scale_x, scale_y, rotation, opacity)"
              % name, text.count("clip.get_value_at_time("), 6)
        check("%s khong tu goi interpolate_keyframes" % name,
              text.count("interpolate_keyframes("), 0)
        check("%s khong tu goi apply_ease" % name, text.count("apply_ease("), 0)
    owners = set()
    for folder in ("core", "ui"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                full = os.path.join(dirpath, filename)
                if "interpolate_keyframes(" in open(full, encoding="utf-8").read():
                    owners.add(os.path.relpath(full, ROOT).replace("\\", "/"))
    check("chi lop model nam toi loi noi suy",
          sorted(owners), sorted(["core/keyframe_manager.py",
                                  "core/keyframe_graph.py",
                                  "core/timeline_model.py"]))
    # core/keyframe_graph.py duoc xuat hien o tren VÌ nó goi lai
    # interpolate_keyframes cho do thi, khong phai vi nó tu noi suy. Khoa nay
    # phan biet hai dieu do: neu do thi ve mot duong cong tu tinh, no sẽ co
    # so san cua mot phep noi suy va khoa NO.
    graph_src = open(os.path.join(ROOT, "core", "keyframe_graph.py"),
                     encoding="utf-8").read()
    check("do thi chi goi loi noi suy cua model, khong tu viet cong thuc",
          ["interpolate_keyframes(" in graph_src,
           graph_src.count("apply_ease("),
           graph_src.count("val_b - val_a")], [True, 0, 0])
    view_src = open(os.path.join(ROOT, "ui", "keyframe_graph_dialog.py"),
                    encoding="utf-8").read()
    check("view do thi khong cham truc tiep loi noi suy",
          view_src.count("interpolate_keyframes("), 0)
    lerps = []
    for folder in ("core", "ui", "widgets"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                full = os.path.join(dirpath, filename)
                text = open(full, encoding="utf-8").read()
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                if "val_b - val_a" in text and rel != "core/keyframe_manager.py":
                    lerps.append(rel)
    check("khong ban sao cong thuc noi suy o cho khac", lerps, [])


# ── 3. Do tren anh that ─────────────────────────────────────────

def gate_pixels(win):
    from core.canvas_utils import ASPECT_RATIOS
    want_frame = ASPECT_RATIOS.get("16:9", (1920, 1080))
    rect = project_rect(win)
    check("khung do cua preview la dung khung du an 16:9",
          (int(rect.width()), int(rect.height())), want_frame)

    rows = []
    for ease in EASES_MEASURED:
        model, clip = build_eased_clip(win, ease)
        check("clip mang cong %s nam trong model" % ease,
              frame_ease(clip.keyframes["x"][0]), ease)
        rows.append(measure_paths(win, model, ease))

    for row in rows:
        ease = row["ease"]
        span_e = row["c1_export"] - row["c0_export"]
        span_p = row["c1_preview"] - row["c0_preview"]
        check("hai dau cach nhau duoc do giong nhau o hai duong (%s)" % ease,
              round(span_e) == round(span_p), True)
        above("do dai doan do duoc (%s)" % ease, abs(span_e), 300.0)

        f = apply_ease(ease, T_MID)
        near("anh xuat dung cong %s" % ease, row["mid_export"],
             row["c0_export"] + span_e * f, PX_TOL)
        near("anh preview dung cong %s" % ease, row["mid_preview"],
             row["c0_preview"] + span_p * f, PX_TOL)
        below("preview va export trung khop %s" % ease,
              abs(row["mid_export"] - row["mid_preview"]), PX_TOL)

    # Neu easing bi vo hieu hoa thi diem giua nam chinh gitua hai dau. Do lech
    # do duoc PHAI lon hon dung sai — do la khoa phan biet tren anh.
    # "linear" vi tri chinh xac gitua hai dau — loai no ra thi khoa nay moi do
    # duoc con nao bi vo hieu hoa hoan toan.
    worst = min((r for r in rows if r["ease"] != "linear"),
                key=lambda r: abs(apply_ease(r["ease"], T_MID) - 0.5))
    above("do lech khoi diem tuyen tinh (%s)" % worst["ease"],
          abs(worst["mid_export"]
              - (worst["c0_export"] + worst["c1_export"]) / 2.0), PX_TOL)
    above("do phung vi tri giua cac cong tren anh xuat",
          max(r["mid_export"] for r in rows) - min(r["mid_export"] for r in rows),
          250.0)
    above("do phung vi tri giua cac cong tren anh preview",
          max(r["mid_preview"] for r in rows) - min(r["mid_preview"] for r in rows),
          250.0)
    return rows


# ── 4. Undo / keo tha / auto-keyframe ───────────────────────────

def gate_undo(win):
    from core.commands import (AutoKeyframeCommand, DragKeyframeCommand,
                               SetKeyframeEaseCommand)
    model, clip = build_eased_clip(win, "ease_in_cubic")
    stack = win.timeline_panel.undo_stack
    stack.clear()
    check("undo stack khoi diem rong", stack.undo_count, 0)
    check("cong khoi diem", frame_ease(clip.keyframes["x"][0]), "ease_in_cubic")

    stack.push(SetKeyframeEaseCommand(model, clip.clip_id, "x", 0.0, "ease_out"))
    clip = model.get_clip(clip.clip_id)
    check("doi cong -> model doi theo", frame_ease(clip.keyframes["x"][0]),
          "ease_out")
    check("lenh doi cong khong cham gia tri",
          frame_value(clip.keyframes["x"][0]), X0)
    check("lenh doi cong nam trong stack", stack.undo_count, 1)
    stack.undo()
    check("undo tra lai cong cu",
          frame_ease(model.get_clip(clip.clip_id).keyframes["x"][0]),
          "ease_in_cubic")
    stack.redo()
    check("redo dat lai cong moi",
          frame_ease(model.get_clip(clip.clip_id).keyframes["x"][0]), "ease_out")

    stack.push(DragKeyframeCommand(model, clip.clip_id, "x", 0.0, 0.25, X0))
    clip = model.get_clip(clip.clip_id)
    check("keo tha doi thoi gian", round(frame_time(clip.keyframes["x"][0]), 3),
          0.25)
    check("keo tha van giu duong cong", frame_ease(clip.keyframes["x"][0]),
          "ease_out")
    stack.undo()
    clip = model.get_clip(clip.clip_id)
    check("undo keo tha tra lai thoi gian",
          round(frame_time(clip.keyframes["x"][0]), 3), 0.0)
    check("undo keo tha khong xoa duong cong",
          frame_ease(clip.keyframes["x"][0]), "ease_out")

    stack.push(AutoKeyframeCommand(model, clip.clip_id, "x", 0.0, X0, -540.0))
    clip = model.get_clip(clip.clip_id)
    check("auto-keyframe ghi de gia tri", frame_value(clip.keyframes["x"][0]),
          -540.0)
    check("auto-keyframe giu duong cong", frame_ease(clip.keyframes["x"][0]),
          "ease_out")
    stack.undo()
    clip = model.get_clip(clip.clip_id)
    check("undo auto-keyframe tra gia tri cu", frame_value(clip.keyframes["x"][0]),
          X0)
    check("undo auto-keyframe tra ca duong cong",
          frame_ease(clip.keyframes["x"][0]), "ease_out")

    clip.add_keyframe("x", 0.0, -300.0)
    check("add_keyframe khong am tham reset cong",
          frame_ease(clip.keyframes["x"][0]), "ease_out")
    check("add_keyframe van ghi de gia tri", frame_value(clip.keyframes["x"][0]),
          -300.0)
    clip.set_keyframe_ease("x", 0.0, "bogus")
    check("ten cong la bi tra ve linear an toan",
          frame_ease(clip.keyframes["x"][0]), DEFAULT_EASE)
    check("doi cong tai moc khong ton tai thi that bai",
          clip.set_keyframe_ease("x", 42.0, "ease_in"), False)
    check("lay cong tai moc khong ton tai thi linear",
          clip.get_keyframe_ease("x", 42.0), DEFAULT_EASE)
    stack.clear()


# ── 5. Cat – luu – mo ───────────────────────────────────────────

def all_clip_rows(project):
    """Clips nam trong timeline > tracks > clips — khong phai key "clips" ngoai cung."""
    return [row for track in project.get("timeline", {}).get("tracks", [])
            for row in track.get("clips", [])]


def gate_persistence(win):
    model, clip = build_eased_clip(win, "ease_in")
    clip_id = clip.clip_id
    clip.add_keyframe("opacity", 0.35, 0.2, "ease_out_cubic")
    clip.add_keyframe("rotation", 0.7, 25.0, "linear")

    dumped = project_storage.serialize_keyframes(model.get_clip(clip_id).keyframes)
    check("moi keyframe serialize ra 3 phan tu",
          all(len(row) == 3 for rows in dumped.values() for row in rows), True)
    check("phan tu thu ba la ten cong",
          dumped["x"][0][2], "ease_in")

    project_storage.save_project_to_file(model, CLINQ, {"name": "easing probe"})
    project = project_storage.load_project_from_file(CLINQ)
    check("file mo duoc", project is not None, True)
    check("file chua clip da luu",
          any(row["clip_id"] == clip_id for row in all_clip_rows(project)), True)

    fresh = TimelineModel()
    project_storage.restore_model_from_clinq(fresh, project)
    saved = fresh.get_clip(clip_id)
    check("clip duoc khoi phuc", saved is not None, True)
    check("cong x song qua file", frame_ease(saved.keyframes["x"][0]), "ease_in")
    check("cong opacity song qua file",
          frame_ease(saved.keyframes["opacity"][0]), "ease_out_cubic")
    check("thoi gian va gia tri khong doi",
          [round(frame_time(saved.keyframes["x"][0]), 3),
           round(frame_value(saved.keyframes["x"][0]), 3)], [0.0, X0])
    near("noi suy sau khi mo file van theo cong",
         saved.get_value_at_time("x", T_MID, X0), predict("ease_in"), 1e-6)
    check("mo file khong sinh frame 2 phan tu",
          all(len(f) == 3 for frames in saved.keyframes.values() for f in frames),
          True)

    legacy = json.loads(json.dumps(project))
    for row in all_clip_rows(legacy):
        for prop, frames in row.get("keyframes", {}).items():
            row["keyframes"][prop] = [f[:2] for f in frames]
    with open(LEGACY, "w", encoding="utf-8") as handle:
        json.dump(legacy, handle)
    old_project = project_storage.load_project_from_file(LEGACY)
    check("project cu (2 phan tu) mo duoc", old_project is not None, True)
    old_model = TimelineModel()
    project_storage.restore_model_from_clinq(old_model, old_project)
    old_clip = old_model.get_clip(clip_id)
    check("keyframe cu duoc hieu la linear",
          frame_ease(old_clip.keyframes["x"][0]), DEFAULT_EASE)
    near("noi suy project cu dung lerp",
         old_clip.get_value_at_time("x", T_MID, X0), predict("linear"), 1e-6)
    check("luu lai project cu thi day du 3 phan tu",
          all(len(f) == 3 for frames in
              project_storage.serialize_keyframes(old_clip.keyframes).values()
              for f in frames), True)


# ── 6. Node + menu chuot phai ───────────────────────────────────

def render_node(node, scale=4.0):
    """Ve rieng mot KeyframeNode thanh anh ro nen.

    KeyframeNode la QGraphicsItem chu khong phai QWidget nen khong co grab().
    Cach duy nhat de tach no ra khoi clip cha la goi thang paint() cua no —
    dung ham ma QGraphicsView van goi khi hien thi timeline.
    """
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QStyleOptionGraphicsItem
    rect = node.boundingRect()
    pixmap = QPixmap(max(2, int(rect.width() * scale)),
                     max(2, int(rect.height() * scale)))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(scale, scale)
    painter.translate(-rect.left(), -rect.top())
    node.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    return pixmap


def node_for(clip_item, property_key, time_sec):
    for node in clip_item._keyframe_nodes:
        if node.property_key == property_key and \
                abs(node.time_sec - time_sec) < 0.01:
            return node
    return None


def gate_node_ui(win):
    model, clip = build_eased_clip(win, "ease_in")
    scene = win.timeline_panel.scene
    clip_item = clip_item_for(win, clip)
    check("timeline co ClipItem cua clip", clip_item is not None, True)
    if clip_item is None:
        return {}
    total_frames = sum(len(f) for f in clip.keyframes.values())
    check("node duoc spawn dung bang so keyframe model",
          len(clip_item._keyframe_nodes), total_frames)

    node = node_for(clip_item, "x", 0.0)
    check("node tai t=0 ton tai", node is not None, True)
    check("node mang dung cong cua model", node.ease, "ease_in")
    check("node khong phai cuoi track nen co tay cong", node.is_last_of_track(),
          False)

    handles = {}
    tiles = {}
    for name in sorted(EASINGS):
        node.set_ease(name)
        handles[name] = (round(node.handle_vector().x(), 3),
                         round(node.handle_vector().y(), 3))
        tiles[name] = render_node(node)
    above("so huong tay cong phan biet giua cac cong",
          len(set(handles.values())), 8)
    check("tay cong chi ve phia ben phai (chiep di toi keyframe ke tiep)",
          all(v[0] > 0.0 for v in handles.values()), True)
    above("tay expo-nhanh doc hon tay expo-cham",
          abs(handles["ease_out_expo"][1]), abs(handles["ease_in_expo"][1]))
    check("tay cong linear nghieng 45 do",
          round(handles["linear"][0], 1) == round(-handles["linear"][1], 1), True)
    node.set_ease("ease_in")

    masks = {}
    for name in sorted(EASINGS):
        node.set_ease(name)
        alpha = to_array(tiles[name])[:, :, 3] > 0
        above("node ve co pixel that (%s)" % name, int(alpha.sum()), 40)
        masks[name] = json.dumps(alpha.astype(int).tolist())
    node.set_ease("ease_in")
    check("hinh dang node doi theo duong cong, khong phai ky hieu trang tri",
          len(set(masks.values())), len(masks))

    menu = node.build_ease_menu()
    baseline = orphan_baseline(menu)
    entries = [a for a in menu.actions() if a.isEnabled() and a.isCheckable()]
    check("menu co mot header bi khoa",
          sum(1 for a in menu.actions() if not a.isEnabled()), 1)
    check("menu co dung mot muc moi duong cong", len(entries), len(EASINGS))
    check("moi muc co nhan tieng Viet dung bang",
          all(a.text() == EASE_LABELS[a.data()] for a in entries), True)
    check("dung mot muc duoc chot theo cong hien tai",
          [a.data() for a in entries if a.isChecked()], ["ease_in"])
    groups = {a.actionGroup() for a in entries}
    check("cac muc nam trong MỘT nhom doc nhat", len(groups), 1)
    check("nhom do bat ky doc nhat", groups.pop().isExclusive(), True)
    check("moi muc co slot ngoai Qt (nhieu hon mo cua menu)",
          all(action_connection(a) > baseline for a in entries), True)

    target = next(a for a in entries if a.data() == "ease_out_cubic")
    target.trigger()
    for _ in range(6):
        QApplication.processEvents()
    clip = model.get_clip(clip.clip_id)
    check("click menu doi duong cong trong model",
          frame_ease(clip.keyframes["x"][0]), "ease_out_cubic")
    stack = win.timeline_panel.undo_stack
    check("click menu la mot buoc undo that", stack.can_undo, True)
    stack.undo()
    check("hoan tac click menu tra lai cong cu",
          frame_ease(model.get_clip(clip.clip_id).keyframes["x"][0]), "ease_in")

    clip_item = clip_item_for(win, model.get_clip(clip.clip_id))
    node = node_for(clip_item, "x", 0.0)
    check("node sau khi rebuild van doc model", node.ease, "ease_in")
    check("tooltip cua node noi ro chuc nang",
          "tới keyframe kế tiếp" in node.toolTip(), True)
    check("tooltip goi dung ten cong", EASE_LABELS["ease_in"] in node.toolTip(),
          True)
    stack.clear()
    return tiles


# ── 7. Bang chung hinh ─────────────────────────────────────────

def evidence(rows, node_tiles):
    left, top_chart = 20, 46
    box = QRectF(left, top_chart, 190, 190)
    row_h = 78
    sheet_w = 860
    sheet_h = int(top_chart + box.height() + 40 + row_h * len(rows) + 130)
    img = QImage(sheet_w, sheet_h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#101418"))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(QPen(QColor("#E6ECFF")))
    painter.drawText(left, 28,
                     "#40 duong cong keyframe: bang EASINGS, anh xuat va anh preview do duoc")

    painter.setPen(QPen(QColor("#2A3038"), 1))
    painter.drawRect(box)
    painter.setPen(QPen(QColor("#5A6472"), 1))
    painter.drawLine(int(box.left()), int(box.center().y()),
                     int(box.right()), int(box.center().y()))
    colors = ["#7C5CFF", "#FFB454", "#2ED573", "#FF4D6D", "#4DA6FF",
              "#E7DBFF", "#B36B00", "#00A6A6", "#C0C0C0"]
    for index, name in enumerate(sorted(EASINGS)):
        path = QPainterPath()
        for step in range(61):
            t = step / 60.0
            x = box.left() + box.width() * t
            y = box.bottom() - box.height() * apply_ease(name, t)
            if step == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        color = QColor(colors[index % len(colors)])
        painter.setPen(QPen(color, 1.8))
        painter.drawPath(path)
        painter.setPen(QPen(color))
        painter.drawText(220, int(top_chart + 12 + index * 16),
                         "%-18s f(0.5)=%.3f" % (name, apply_ease(name, 0.5)))

    y0 = int(top_chart + box.height() + 26)
    painter.setPen(QPen(QColor("#E6ECFF")))
    painter.drawText(left, y0, "tam khoi do do tren anh — trai: FrameComposer (export), "
                               "phai: Player Canvas (preview)")
    text_col, export_col, preview_col = left, 300, 430
    for index, row in enumerate(rows):
        top = y0 + 10 + index * row_h
        span = row["c1_export"] - row["c0_export"]
        want = row["c0_export"] + span * apply_ease(row["ease"], T_MID)
        painter.setPen(QPen(QColor("#C7CEEA")))
        painter.drawText(QRectF(text_col, top + 6, 265, row_h - 10),
                         Qt.AlignLeft | Qt.TextWordWrap,
                         "%s\nxuat %.1f · preview %.1f\nmong %.1f · lech %.2fpx" % (
                             row["ease"], row["mid_export"], row["mid_preview"],
                             want, abs(row["mid_export"] - row["mid_preview"])))
        painter.drawImage(QRectF(export_col, top, 110, 66), row["export_img"])
        painter.drawImage(QRectF(preview_col, top, 110, 66), row["preview_img"])
        painter.setPen(QPen(QColor("#5A6472")))
        painter.drawRect(QRectF(export_col, top, 110, 66))
        painter.drawRect(QRectF(preview_col, top, 110, 66))

    y1 = y0 + 10 + len(rows) * row_h + 16
    painter.setPen(QPen(QColor("#E6ECFF")))
    painter.drawText(left, y1, "node tren timeline (ve bang chinh paint() cua KeyframeNode), theo thu tu:")
    x = left
    for index, name in enumerate(sorted(EASINGS)):
        tile = node_tiles[name].toImage().scaled(
            64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage(QRectF(x + index * 92, y1 + 8, 64, 64), tile)
        painter.setPen(QPen(QColor("#8A93A5")))
        painter.drawText(x + index * 92, y1 + 86, name.replace("ease_", ""))

    painter.end()
    if not img.save(EVIDENCE):
        raise SystemExit("cannot write evidence image")
    print("evidence image: %s (%d bytes, %dx%d)"
          % (EVIDENCE, os.path.getsize(EVIDENCE), img.width(), img.height()))


# ── main ────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    try:
        from theme import theme_manager
        app.setStyleSheet(theme_manager.stylesheet())
    except Exception as exc:
        print("  (theme skipped: %s)" % exc)

    # Autosave cua app tuyet doi khong duoc de len file that cua nguoi dung.
    project_storage.AUTO_SAVE_FILE = os.path.join(TMP, "autosave.json")
    write_probe_media()

    print("\n== 1. bang duong cong ==")
    gate_curve_table()
    print("\n== 2. funnel noi suy ==")
    gate_funnel()
    counterfactual_funnel()
    gate_one_funnel_only()

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1680, 940)
    win.show()
    for _ in range(20):
        app.processEvents()
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()

    print("\n== 3. do tren anh that: xuat vs preview ==")
    rows = gate_pixels(win)
    print("\n== 4. undo / keo tha / auto-keyframe ==")
    gate_undo(win)
    print("\n== 5. cat - luu - mo ==")
    gate_persistence(win)
    print("\n== 6. node + menu chuot phai ==")
    tiles = gate_node_ui(win)

    print("\n== 7. bang chung hinh ==")
    evidence(rows, tiles)

    print("\nsummary:", "ALL PASS" if not fails else
          "FAILURES\n  " + "\n  ".join(fails))

    # Dong co chu dich: de Qt ty giai phong thi C++ fast-fail luc thoat
    # (0xC0000409 -> rc=127) che mat ket qua probe.
    for row in rows:
        row.pop("export_img", None)
        row.pop("preview_img", None)
    tiles.clear()
    win.close()
    for _ in range(8):
        app.processEvents()
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        CODE = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(CODE)
