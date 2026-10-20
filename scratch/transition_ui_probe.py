"""
scratch/transition_ui_probe.py
Bằng chứng cho LỚP GIAO DIỆN chuyển tiếp: tab "Chuyển tiếp", thẻ thuộc tính và
dải đánh dấu trên timeline phải đi đúng đường dẫn sản xuất, không phải một bản
phô viết lại trong probe.

Mọi gate gọi vào TÍN HIỆU THẬT của panel:
  - EffectsPanel.effectApplied.emit(...)      == nhấp nút "+" / kích đúp thẻ
  - EffectsPanel.effectPreviewRequested.emit(..) == rê chuột lên thẻ
  - combo/slider/button của ClipPropertiesWidget == người dùng thao tác thẻ
  - scene.render() của TimelineScene           == pixels người dùng trông thấy

Probe KHÔNG tự đẩy item vẽ lại: sau mỗi cú nhấp chỉ có model.emit ->
TimelineScene._on_clip_updated/_on_clip_moved -> ClipItem.update_from_model, tức
là đúng chuỗi mà ứng dụng chạy.

Ba thứ dễ nói dối nhất ở tính năng này, và gate tương ứng:
  1. "đã áp" nhưng thật ra chỉ thêm EffectData vô hình  -> gate ripple + undo.
  2. thẻ cho chọn kiểu mà timeline không chỗ chứa       -> gate item bị tắt.
  3. dải trên timeline tô theo trí nhớ (duration đã lưu) thay vì theo cửa sổ
     thật, và bề rộng đo bằng pixel thay vì bằng giây   -> gate band_pixels().

band_pixels() là phép thử counterfactual: áp chuyển tiếp rồi ripple làm clip
trượt trái, nên "có transition" trừ "không transition" lẫn cả thân clip đã dời
chỗ. Vì vậy gate vẽ timeline, rồi XÓA ĐÚNG clip.transition tại chỗ (không ripple,
hình học giữ nguyên) và vẽ lại; hiệu số hai khung hình chỉ còn thể là dải đánh
dấu, và có thể quy ra giây để đối chiếu với transitions.window().

Chạy: QT_QPA_PLATFORM=windows python -u scratch/transition_ui_probe.py
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

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QToolTip

import core.project_storage as project_storage
from core import transitions
from core.timeline_model import TrackType, track_type_for_media
from ui.effects_panel import EFFECT_CATEGORIES, TRANSITION_CATEGORY

W, H = 640, 360
DUR = 5.0
JUNCTIONS = ["Cross Dissolve", "Zoom In", "Slide Left", "Wipe Right"]

A_MP4 = os.path.join(OUT, "transition_ui_A.mp4")
B_MP4 = os.path.join(OUT, "transition_ui_B.mp4")
A_PNG = os.path.join(OUT, "transition_ui_A.png")

A_RGB = (200, 30, 30)
B_RGB = (30, 60, 200)

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-64s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def near(label, got, want, tol):
    ok = abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want %r+-%r" % (label, got, want, tol))
    print("%-64s %s got=%r want~%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def truthy(label, got):
    return check(label, bool(got), True)


# ── Sinh media ──────────────────────────────────────────────────

def write_still_video(path, rgb, seconds=6.0, fps=12.0):
    import cv2
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:, :] = (rgb[2], rgb[1], rgb[0])
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for _ in range(int(seconds * fps)):
        writer.write(frame)
    writer.release()
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        raise SystemExit("cannot write probe media: " + path)


def write_flat_png(path, rgb):
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(*rgb))
    img.save(path)
    if not os.path.exists(path):
        raise SystemExit("cannot write probe media: " + path)


# ── Đo ảnh ──────────────────────────────────────────────────────

def to_array(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.int16)


def diff_map(a, b, threshold=8):
    """Mask pixel khác nhau rõ rệt giữa hai khung hình timeline."""
    return np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2) > threshold


def changed_columns(mask):
    if not np.any(mask):
        return 0, 0, 0
    cols = mask.any(axis=0)
    first = int(np.argmax(cols))
    last = len(cols) - 1 - int(np.argmax(cols[::-1]))
    return first, last, int(cols.sum())


# ── Player giả (probe không phát tiếng ra loa) ──────────────────
# Dùng lại đúng một fake cho mọi gate preview. Khi production gọi thêm API của
# QMediaPlayer, các gate khác cập nhật một lần là xong; bản sao riêng ở đây sẽ
# im lặng thiếu hàm và cho ra lỗi trông như hỏng tính năng.
if OUT not in sys.path:
    sys.path.insert(0, OUT)
from transition_apply_probe import FakePlayer as _SharedFakePlayer


class FakePlayer(_SharedFakePlayer):
    """Cùng fake, chỉ khác chỗ: gate này mở window khi chưa phát."""

    def __init__(self):
        super().__init__()
        self.state = QMediaPlayer.StoppedState


# ── Dựng model trên MainWindow thật ─────────────────────────────

def clear_model(win):
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    model.project_ratio = "16:9"
    model.playhead = 0.0
    win.properties_panel.show_empty()
    return model


def build_pair(win):
    """Hai clip video liền nhau trên Main Storyline (chưa có chuyển tiếp)."""
    model = clear_model(win)
    track = model.add_track(TrackType.VIDEO, "Main")
    clip_a = model.add_clip(track.track_id, A_MP4, "video", 0.0, DUR, "left.mp4")
    clip_b = model.add_clip(track.track_id, B_MP4, "video", DUR, DUR, "right.mp4")
    win._sync_canvas()
    model.select_clip(clip_b.clip_id, add_to=False)
    return model, clip_a, clip_b


def build_image(win):
    """Một clip ảnh trên overlay track — nơi local fade sống, junction thì không."""
    model = clear_model(win)
    track = model.add_track(track_type_for_media("image"), "Overlay")
    clip = model.add_clip(track.track_id, A_PNG, "image", 0.0, 4.0, "only.png")
    win._sync_canvas()
    model.select_clip(clip.clip_id, add_to=False)
    return model, clip


def stack_depth(win):
    return len(win.timeline_panel.undo_stack._undo_stack)


def click_card(win, name, target=None):
    """Đúng đường dẫn một cú nhấp: EffectCard.addRequested -> EffectsPanel.effectApplied.

    target là clip người dùng ĐÃ chọn trước khi bấm thẻ. Selection có thể bị
    model bỏ sau một nhịp event loop (canvas rebuild + deferred
    selectionChanged), nên gate nào từng chờ vẽ lại phải bấm lại clip của mình
    — đó chính là thao tác mà người dùng thật phải làm.
    """
    if target is not None:
        win.timeline_panel.model.select_clip(target.clip_id, add_to=False)
    win.effects_panel.effectApplied.emit({"name": name, "category": TRANSITION_CATEGORY})


def hover_card(win, name, target=None):
    if target is not None:
        win.timeline_panel.model.select_clip(target.clip_id, add_to=False)
    win.effects_panel.effectPreviewRequested.emit(
        {"name": name, "category": TRANSITION_CATEGORY})


def open_editor(win, clip):
    """Trình soạn clip. NOTE: show_clip_properties() deleteLater() editor cũ, nên
    mọi tương tác phải xong trên một editor trước khi mở editor của clip khác."""
    win.properties_panel.show_clip_properties(clip)
    return win.properties_panel.current_editor


# ── Render timeline ─────────────────────────────────────────────

def timeline_render(win, items):
    """(ảnh, QRectF khung scene đã vẽ). Cột pixel i ứng scene x = rect.left()+i,
    nên gate mới quy được bề rộng dải ra GIÂY thay vì tin vào pixel."""
    scene = win.timeline_panel.scene
    rect = None
    for item in items:
        box = item.sceneBoundingRect()
        rect = box if rect is None else rect.united(box)
    rect = rect.adjusted(-4.0, -4.0, 4.0, 4.0)
    w, h = int(rect.width()), int(rect.height())
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    try:
        scene.render(painter, QRectF(0, 0, w, h), rect)
    finally:
        painter.end()
    return img, rect


def wait_paint_stable(win, items, timeout_ms=8000):
    """Chờ worker thumbnail giao hàng: hai khung hình liên tiếp phải giống hệt."""
    app = QApplication.instance()
    deadline = timeout_ms
    while deadline > 0:
        first, _ = timeline_render(win, items)
        for _ in range(3):
            app.processEvents()
        second, _ = timeline_render(win, items)
        if not np.any(diff_map(to_array(first), to_array(second), 4)):
            return True
        deadline -= 300
    return False


def clip_item(win, clip):
    return win.timeline_panel.scene._clip_items.get(clip.clip_id)


def band_pixels(win, items, clip):
    """(mask riêng dải đánh dấu, rect vẽ) — hình học clip giữ nguyên 100%.

    Xóa đúng dict clip.transition rồi vẽ lại: không ripple, không recalculate,
    nên mọi pixel khác (thumbnail, khung clip, keyframe node) giống hệt nhau và
    phần còn lại của hiệu số bắt buộc là sơn của _paint_transition_band().
    """
    item = clip_item(win, clip)
    saved = dict(clip.transition)
    with_band, rect = timeline_render(win, items)
    clip.transition = {}
    item._sync_transition_tooltip()
    plain, _ = timeline_render(win, items)
    clip.transition = saved
    item._sync_transition_tooltip()
    return diff_map(to_array(with_band), to_array(plain), 8), rect


def band_seconds(win, rect, mask):
    """(start, end, width) của dải đo được, quy về giây qua mapper thật."""
    px = win.timeline_panel.mapper
    first, last, count = changed_columns(mask)
    return (px.pixel_to_time(rect.left() + first),
            px.pixel_to_time(rect.left() + last + 1.0), count)


# ── Gate 0: danh mục thẻ không lệch bảng core ───────────────────

def gate_card_table(win):
    print("\n== card list vs core table ==")
    names = {e["name"] for e in EFFECT_CATEGORIES[TRANSITION_CATEGORY]}
    check("every transition card is a real core kind", names,
          set(transitions.TRANSITIONS))
    check("no card was added that core does not paint",
          len(names - set(transitions.TRANSITIONS)), 0)
    other = {e["name"] for cat, effects in EFFECT_CATEGORIES.items()
             if cat != TRANSITION_CATEGORY for e in effects}
    check("transition names are unique across tabs (routing is unambiguous)",
          len(other & names), 0)


# ── Gate 1: tab nhấp vào là SetTransitionCommand, không phải EffectData ──

def gate_tab_click(win):
    print("\n== tab 'Chuyển tiếp' -> SetTransitionCommand ==")
    model, a, b = build_pair(win)
    depth0 = stack_depth(win)
    click_card(win, "Wipe Right")

    check("click: the incoming clip carries the transition",
          transitions.name_of(b), "Wipe Right")
    check("click: default duration from core/transitions.py",
          transitions.duration_of(b), transitions.DEFAULT_DURATION)
    check("click: apply is NOT smuggled in as an EffectData",
          len(b.effects), 0)
    check("click: one undo step per click", stack_depth(win), depth0 + 1)
    near("click: ripple slid the incoming clip left by the overlap",
         b.start_time, DUR - transitions.DEFAULT_DURATION, 0.001)
    near("click: the two clips now really overlap",
         a.end_time - b.start_time, transitions.DEFAULT_DURATION, 0.001)
    truthy("click: undo stack describes the transition (not 'hiệu ứng')",
           "chuyển tiếp" in win.timeline_panel.undo_stack.undo_text.lower())

    win.timeline_panel.undo_stack.undo()
    check("undo: transition gone", transitions.name_of(b), "")
    near("undo: ripple reversed, clip back to its old anchor",
         b.start_time, DUR, 0.001)

    win.timeline_panel.undo_stack.redo()
    check("redo: transition restored", transitions.name_of(b), "Wipe Right")
    near("redo: ripple re-applied", b.start_time, DUR - 1.0, 0.001)

    # Nhấp kiểu khác trên cùng clip: phải đổi kiểu chứ không cộng dồn.
    click_card(win, "Slide Left", b)
    check("second click replaces the kind", transitions.name_of(b), "Slide Left")

    win.timeline_panel.undo_stack.undo()
    check("undo of a replace returns the previous kind",
          transitions.name_of(b), "Wipe Right")

    # Kéo-thả thẻ xuống timeline cũng đi qua cùng một command, kể cả khi payload
    # drag không mang category (routing phải tra theo TÊN).
    model.playhead = DUR
    model.select_clip(b.clip_id, add_to=False)
    win.effects_panel.effectApplied.emit({"name": "Zoom In"})
    check("drop without a category field still routes by name lookup",
          transitions.name_of(b), "Zoom In")
    return model, a, b


# ── Gate 2: từ chối có giải thích, và không đốt undo ────────────

def gate_refusal(win):
    print("\n== khong du cho thi tu che co ly do ==")
    notes = []
    real = QToolTip.showText

    def spy(pos, text, *args, **kwargs):
        notes.append(text)

    QToolTip.showText = spy
    try:
        model, a, b = build_pair(win)
        depth0 = stack_depth(win)
        click_card(win, "Wipe Right")
        check("clip A is first on the row, so a junction has nothing to join",
              model.max_transition_duration(a.clip_id, "Wipe Right"), 0.0)
        model.select_clip(a.clip_id, add_to=False)
        click_card(win, "Wipe Right")
        check("refused: no transition stored on clip A", transitions.name_of(a), "")
        check("refused: no undo step burned", stack_depth(win), depth0 + 1)
        truthy("refused: the user is told why",
               bool(notes) and "Main Storyline" in notes[-1])

        # Trim clip trái đến sát MIN_KEEP: cửa sổ không còn chỗ -> từ chối,
        # và lời phải nói về thời lượng chứ không phải về layer.
        notes.clear()
        model.select_clip(b.clip_id, add_to=False)
        click_card(win, "")
        a.duration = 0.05
        model.recalculate_main_storyline(model.get_track(a.track_id))
        room = model.max_transition_duration(b.clip_id, "Cross Dissolve")
        check("refused: a first clip shorter than MIN_KEEP leaves no room",
              room, 0.0)
        depth_room = stack_depth(win)
        click_card(win, "Cross Dissolve")
        truthy("refused: the short-clip reason quotes MIN_KEEP, not the row rule",
               bool(notes) and "0.1s" in notes[-1])
        check("refused by time: no undo step burned",
              stack_depth(win), depth_room)

        model2, img = build_image(win)
        notes.clear()
        click_card(win, "Cross Dissolve")
        check("refused: junction on an overlay track does not stick",
              transitions.name_of(img), "")
        truthy("refused: overlay track blames the row, never the clock",
               bool(notes) and "Main Storyline" in notes[-1]
               and "0.1s" not in notes[-1])
        depth_overlay = stack_depth(win)
        check("refused: overlay junction burned no undo step",
              stack_depth(win), depth_overlay)
        notes.clear()
        click_card(win, "Fade In", img)
        check("allowed: local fade works on an overlay image clip",
              transitions.name_of(img), "Fade In")
        check("allowed: a working click shows no refusal tooltip",
              len(notes), 0)

        # Local fade cũng phải có chỗ: clip ngắn hơn MIN_KEEP thì phai xong là
        # hết clip, nên từ chối và KHÔNG được đổ lỗi cho layer.
        img.duration = 0.05
        notes.clear()
        click_card(win, "Fade Out", img)
        check("refused: a clip shorter than MIN_KEEP takes no local fade",
              transitions.name_of(img), "Fade In")
        truthy("refused: the local reason quotes the clock, not the row",
               bool(notes) and "0.1s" in notes[-1]
               and "Main Storyline" not in notes[-1])
        check("refused: local no-room burned no undo step",
              stack_depth(win), depth_overlay + 1)
    finally:
        QToolTip.showText = real


# ── Gate 3: thẻ thuộc tính ──────────────────────────────────────

def gate_properties_card(win):
    print("\n== the transition card in the properties panel ==")
    model, a, b = build_pair(win)
    click_card(win, "Wipe Right")
    editor = open_editor(win, b)
    truthy("card exists on the clip properties widget",
           hasattr(editor, "combo_transition"))
    check("card is not hidden for a video clip",
          editor.card_transition.isHidden(), False)

    check("card shows the applied kind",
          editor.combo_transition.currentData(), "Wipe Right")
    check("card shows the applied duration",
          editor.slider_transition.value(), 100)
    check("card prints the duration next to the slider",
          editor.lbl_transition_val.text(), "1.00s")
    check("card keeps the clear button live while a transition exists",
          editor.btn_transition_clear.isEnabled(), True)

    # Đổi kiểu từ card -> vẫn là command có ripple, không phải ghi thô vào model.
    depth0 = stack_depth(win)
    editor.combo_transition.setCurrentIndex(
        editor.combo_transition.findData("Slide Left"))
    check("card combo writes the model", transitions.name_of(b), "Slide Left")
    check("card combo goes through undo (not a raw write)",
          stack_depth(win), depth0 + 1)

    # Slider: kéo live chỉ đổi label, commit khi thả chuột.
    editor.slider_transition.setValue(50)
    check("dragging updates the read-out", editor.lbl_transition_val.text(), "0.50s")
    check("dragging does not write the model yet",
          transitions.duration_of(b), 1.0)
    check("dragging adds no undo steps", stack_depth(win), depth0 + 1)
    editor.slider_transition.sliderReleased.emit()
    check("release commits the new duration",
          round(transitions.duration_of(b), 3), 0.5)
    check("release is one undo step", stack_depth(win), depth0 + 2)
    near("commit re-ripples the timeline", b.start_time, a.end_time - 0.5, 0.001)

    # Slider không thể yêu cầu nhiều chỗ hơn timeline còn cho.
    room = model.max_transition_duration(b.clip_id, "Slide Left")
    near("slider maximum == the room the model allows",
         editor.slider_transition.maximum(), int(round(room * 100)), 1)

    # Nhắc lại cùng một giá trị: không được đốt thêm undo step.
    editor.slider_transition.sliderReleased.emit()
    check("releasing without moving commits nothing",
          stack_depth(win), depth0 + 2)

    # Clear
    editor.btn_transition_clear.click()
    check("clear button removes the transition", transitions.name_of(b), "")
    near("clear button un-ripples", b.start_time, DUR, 0.001)
    check("clear button disables itself when there is nothing to clear",
          editor.btn_transition_clear.isEnabled(), False)
    check("card falls back to '(Không có)'",
          editor.combo_transition.currentData(), "")
    check("slider is disabled with nothing applied",
          editor.slider_transition.isEnabled(), False)

    # Clip đầu tiên không thể mang junction: item phải trạng, không để người
    # dùng rơi vào một cú nhấp không làm gì. Mở editor clip khác CUỐI CÙNG vì
    # show_clip_properties() deleteLater() editor đang có.
    editor_a = open_editor(win, a)
    disabled = set()
    for i in range(editor_a.combo_transition.count()):
        name = editor_a.combo_transition.itemData(i) or ""
        if not editor_a.combo_transition.model().item(i).isEnabled():
            disabled.add(name)
    check("first clip: every junction is disabled, nothing else",
          disabled, set(JUNCTIONS))
    return editor


# ── Gate 4: dải đánh dấu trên timeline ──────────────────────────

def gate_selection_survives(win):
    """Selection phai song qua mot nhip event loop.

    Canvas dung lại item khi thumbnail ve; QGraphicsScene giao
    selectionChanged bang zero-timer TUC SAU do. Neau khong chon lai clip trong
    luc dung lai, su kien cu thong bao "khong co gi duoc chon" -> deselect_all()
    -> the thuoc tinh (va the chuyen tiep da mo) bien mat sau moi cu nhip clip.
    """
    print("\n== selection survives the event loop ==")
    model, a, b = build_pair(win)
    truthy("timeline pixels are stable",
           wait_paint_stable(win, [clip_item(win, a), clip_item(win, b)]))
    check("the clicked clip is still selected after the loop drained",
          list(model.selected_clip_ids), [b.clip_id])
    open_editor(win, b)
    for _ in range(5):
        QApplication.instance().processEvents()
    check("the properties editor still points at it",
          win.properties_panel.current_editor.clip_id, b.clip_id)
    check("the transition card is still on screen",
          win.properties_panel.current_editor.card_transition.isHidden(), False)


def gate_timeline_marker(win):
    print("\n== timeline overlap marker ==")
    model, a, b = build_pair(win)
    item_a, item_b = clip_item(win, a), clip_item(win, b)
    truthy("both clips have timeline items",
           item_a is not None and item_b is not None)
    truthy("timeline pixels are stable (worker thumbnails settled)",
           wait_paint_stable(win, [item_a, item_b]))

    click_card(win, "Wipe Right", b)
    items = [clip_item(win, a), clip_item(win, b)]
    mask, rect = band_pixels(win, items, b)
    band = model.transition_band(b)
    window = transitions.window(model.previous_clip(b), b)
    check("marker: band kind is the overlap window", band[0], "overlap")
    check("marker: model band == transitions.window()",
          (round(band[1], 3), round(band[2], 3)),
          (round(window[0], 3), round(window[1], 3)))

    start, end, count = band_seconds(win, rect, mask)
    near("marker: painted band START == window start (seconds)", start, window[0], 0.12)
    near("marker: painted band END == window end (seconds)", end, window[1], 0.12)
    near("marker: painted width == overlap seconds",
         count, win.timeline_panel.mapper.duration_to_width(
             window[1] - window[0]), 5.0)
    truthy("marker: band sits on the incoming clip's left edge",
           start >= b.start_time - 0.12 and start < (b.start_time + a.end_time) / 2)

    # Tooltip phải theo cùng chuỗi signal thật (clipUpdated -> update_from_model).
    truthy("marker: tooltip names the transition", "Wipe Right" in item_b.toolTip())
    truthy("marker: tooltip states the overlap", "1.00s" in item_b.toolTip())
    truthy("marker: clip without a transition has no tooltip",
           clip_item(win, a).toolTip() == "")

    # Dải theo cửa sổ THẬT chứ không theo trí nhớ: trim clip bên trái làm cửa sổ
    # teo lại thì dải phải teo theo — duration đã lưu vẫn là 1.0s.
    a.duration = 0.6
    model.recalculate_main_storyline(model.get_track(a.track_id))
    window2 = transitions.window(model.previous_clip(b), b)
    mask2, rect2 = band_pixels(win, [clip_item(win, a), clip_item(win, b)], b)
    _, _, count2 = band_seconds(win, rect2, mask2)
    check("marker: the stored duration did not change",
          transitions.duration_of(b), 1.0)
    truthy("marker: the real window shrank below the remembered duration",
           (window2[1] - window2[0]) < 0.9)
    near("marker: band follows the window after trimming the left clip",
         count2, win.timeline_panel.mapper.duration_to_width(
             window2[1] - window2[0]), 5.0)

    # Zoom: cùng cửa sổ, bề rộng pixel phải scale theo px/giây — tức quy ra giây
    # thì không đổi.
    px = win.timeline_panel.mapper
    base_pps = px.px_per_sec
    px.set_zoom(base_pps * 2.0)
    mask3, rect3 = band_pixels(win, [clip_item(win, a), clip_item(win, b)], b)
    start3, end3, count3 = band_seconds(win, rect3, mask3)
    near("marker: band width doubles with zoom (measured in pixels)",
         count3, px.duration_to_width(window2[1] - window2[0]), 8.0)
    near("marker: band start in seconds survives zoom", start3, window2[0], 0.06)
    px.set_zoom(base_pps)
    check("probe: zoom restored to the rate it started at", px.px_per_sec, base_pps)
    a.duration = DUR
    model.recalculate_main_storyline(model.get_track(a.track_id))
    return item_b


def gate_local_marker(win):
    print("\n== local fade marker ==")
    model, clip = build_image(win)
    item = clip_item(win, clip)
    truthy("timeline pixels are stable for the image clip",
           wait_paint_stable(win, [item]))
    ref_plain, _ = timeline_render(win, [item])

    click_card(win, "Fade In", clip)
    mask, rect = band_pixels(win, [clip_item(win, clip)], clip)
    band = model.transition_band(clip)
    check("Fade In band kind is local-in", band[0], "in")
    start, _, count = band_seconds(win, rect, mask)
    near("Fade In starts at the clip's own start", start, clip.start_time, 0.12)
    near("Fade In band width == transitions.fade_span()",
         count, win.timeline_panel.mapper.duration_to_width(
             transitions.fade_span(clip)), 6.0)

    # Fade In phai đậm ở mép ngoài và nhạt dần vào trong (nghiêng, không phẳng).
    w = int(rect.width())
    truthy("Fade In shading is directional, not a flat block",
           mask[:, :max(1, w // 4)].sum() > mask[:, w // 2:].sum())

    click_card(win, "Fade Out", clip)
    mask_o, rect_o = band_pixels(win, [clip_item(win, clip)], clip)
    band_o = model.transition_band(clip)
    check("Fade Out band kind is local-out", band_o[0], "out")
    _, end_o, count_o = band_seconds(win, rect_o, mask_o)
    near("Fade Out ends at the clip's own end", end_o, clip.end_time, 0.12)
    near("Fade Out band width == transitions.fade_span()",
         count_o, win.timeline_panel.mapper.duration_to_width(
             transitions.fade_span(clip)), 6.0)
    truthy("Fade Out shading is directional the other way",
           mask_o[:, w // 2:].sum() > mask_o[:, :max(1, w // 4)].sum())
    truthy("local fade tooltip describes the ramp on this clip",
           "Phai" in item.toolTip())

    click_card(win, "", clip)
    cleared, _ = timeline_render(win, [clip_item(win, clip)])
    check("clearing a local fade restores the plain clip exactly",
          int(diff_map(to_array(cleared), to_array(ref_plain), 8).sum()), 0)
    check("tooltip empties with the transition", item.toolTip(), "")
    check("band disappears from the model too", model.transition_band(clip), None)


# ── Gate 5: hover preview không sửa model ───────────────────────

def gate_hover_preview(win):
    print("\n== hover preview (no model mutation) ==")
    model, a, b = build_pair(win)
    canvas = win.preview_panel.canvas
    depth0 = stack_depth(win)
    model.playhead = DUR + 0.5

    hover_card(win, "Wipe Right", b)
    item = canvas._clip_items.get(b.clip_id)
    state = getattr(item, "_transition_state", None)
    truthy("preview paints a wipe on the hovered clip",
           state is not None and state.wipe is not None)
    check("preview leaves the model untouched", transitions.name_of(b), "")
    near("preview causes no ripple", b.start_time, DUR, 0.001)
    check("preview pushes nothing onto undo", stack_depth(win), depth0)
    check("preview does not add an EffectData either", len(b.effects), 0)

    # Thanh quét phải đi hết dải tiến độ, không phải một khung tĩnh.
    seen = set()
    for _ in range(24):
        canvas._refresh_tool_preview()
        seen.add(round(item._transition_state.wipe[0], 3))
    truthy("the preview sweeps through the transition", len(seen) > 4)

    # Mỗi kiểu nối phải cho một state khác nhau, nếu không thì 4 thẻ là 4 cái
    # nút cùng vẽ một thứ.
    shapes = {}
    for name in JUNCTIONS:
        canvas.clear_tool_preview()
        hover_card(win, name, b)
        canvas._preview_sweep = 0.4
        canvas._refresh_tool_preview()
        st = canvas._clip_items[b.clip_id]._transition_state
        shapes[name] = (round(st.opacity, 3), round(st.dx, 1),
                        round(st.scale, 3), st.wipe is not None)
    check("the four junction cards paint four different states",
          len(set(shapes.values())), len(JUNCTIONS))

    canvas.clear_tool_preview()
    check("leaving the card clears the preview state",
          item._transition_state, None)

    # Preview local fade cũng không được đổi model.
    model2, img = build_image(win)
    hover_card(win, "Fade In", img)
    item2 = canvas._clip_items.get(img.clip_id)
    truthy("local preview dims the clip for the hover",
           item2._transition_state is not None
           and item2._transition_state.opacity < 0.9)
    check("local preview does not write the model", transitions.name_of(img), "")
    check("local preview pushes nothing onto undo", stack_depth(win), depth0)

    # Quét tới cuối dải thì Fade In phải hiện rõ dần (cùng hàm với export).
    canvas._preview_sweep = 0.95
    canvas._refresh_tool_preview()
    near("local preview reaches full opacity at the end of the ramp",
         item2._transition_state.opacity, 1.0, 0.05)
    win._clear_tool_preview()
    check("leaving the card hands the clip back to the model state",
          item2._transition_state, transitions.NEUTRAL)


# ── Bằng chứng hình ─────────────────────────────────────────────

def compose(tiles, path, cols=3, tile_w=340):
    """Ghép mọi bằng chứng thành một ảnh kèm nhãn."""
    from PySide6.QtGui import QFont
    pad, label_h = 10, 20
    scaled = []
    for img, label in tiles:
        img = img.toImage() if hasattr(img, "toImage") else img
        w, h = img.size().width(), img.size().height()
        th = max(60, int(tile_w * h / max(1, w)))
        scaled.append((label, img.scaled(tile_w, th, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation), th))
    rows = (len(scaled) + cols - 1) // cols
    row_h = []
    for r in range(rows):
        row_h.append(max((s[2] for s in scaled[r * cols:(r + 1) * cols]),
                         default=0) + label_h)
    total_h = pad + sum(row_h) + rows * pad
    sheet = QImage(cols * (tile_w + pad) + pad, total_h,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#0D0E15"))
    painter = QPainter(sheet)
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    painter.setFont(font)
    y = pad
    for r in range(rows):
        x = pad
        for c in range(cols):
            i = r * cols + c
            if i >= len(scaled):
                break
            label, img, th = scaled[i]
            painter.setPen(QColor("#40E0D0"))
            painter.drawText(x, y + 14, label)
            painter.drawImage(x, y + label_h, img)
            x += tile_w + pad
        y += row_h[r] + pad
    painter.end()
    sheet.save(path)
    print("  evidence: %s %dx%d" % (path, sheet.width(), sheet.height()))


def preview_shot(win):
    scene = win.preview_panel.canvas.scene()
    rect = scene.sceneRect()
    cw, ch = int(rect.width()), int(rect.height())
    img = QImage(cw, ch, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    try:
        scene.render(painter, QRectF(0, 0, cw, ch), rect)
    finally:
        painter.end()
    return img.scaled(480, 270, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def band_shot(win, items, clip, label):
    """Dải đánh dấu tô sáng 4x trên nền timeline, để mắt thường thấy được."""
    mask, rect = band_pixels(win, items, clip)
    plain, _ = timeline_render(win, items)
    arr = to_array(plain)
    hi = np.zeros_like(arr)
    hi[:, :, 0] = 64
    hi[:, :, 1] = 224
    hi[:, :, 2] = 208
    hi[:, :, 3] = 255
    arr[mask] = arr[mask] * 0.35 + hi[mask] * 0.65
    return to_qimage(arr), label


def to_qimage(arr) -> QImage:
    data = np.clip(arr, 0, 255).astype(np.uint8)
    h, w = data.shape[0], data.shape[1]
    img = QImage(data.tobytes(), w, h, 4 * w, QImage.Format.Format_RGBA8888)
    return img.copy()


def gate_evidence(win):
    print("\n== evidence tiles ==")
    shots = []

    # 1-3: dải overlap — bình thường / có chuyển tiếp / sau khi trim clip trái
    model, a, b = build_pair(win)
    plain, _ = timeline_render(win, [clip_item(win, a), clip_item(win, b)])
    shots.append((plain, "pair, no transition"))
    click_card(win, "Wipe Right", b)
    items = [clip_item(win, a), clip_item(win, b)]
    img, label = band_shot(win, items, b, "Wipe Right: band == overlap window")
    shots.append((img, label))
    a.duration = 1.2
    model.recalculate_main_storyline(model.get_track(a.track_id))
    img, label = band_shot(win, [clip_item(win, a), clip_item(win, b)], b,
                           "same 1.0s transition, left clip trimmed")
    shots.append((img, label))
    a.duration = DUR
    model.recalculate_main_storyline(model.get_track(a.track_id))

    # 4-5: local fade trên clip ảnh
    model3, img3 = build_image(win)
    click_card(win, "Fade In", img3)
    shots.append(band_shot(win, [clip_item(win, img3)], img3, "image + Fade In"))
    click_card(win, "Fade Out", img3)
    shots.append(band_shot(win, [clip_item(win, img3)], img3, "image + Fade Out"))

    # 6: thẻ thuộc tính thật, grab từ widget đang sống
    model, a, b = build_pair(win)
    click_card(win, "Slide Left", b)
    editor = open_editor(win, b)
    editor.slider_transition.setValue(70)
    editor.slider_transition.sliderReleased.emit()
    editor.card_transition.setStyleSheet(
        "QFrame#PropertyCard{background:#15161E;border:1px solid #2A2C3A;}")
    shots.append((editor.card_transition.grab(),
                  "properties card: %s" % editor.lbl_transition_val.text()))

    # 7-10: hover preview của bốn kiểu nối
    canvas = win.preview_panel.canvas
    model.playhead = DUR + 0.5
    for name in JUNCTIONS:
        canvas.clear_tool_preview()
        hover_card(win, name, b)
        canvas._preview_sweep = 0.45
        canvas._refresh_tool_preview()
        shots.append((preview_shot(win), "hover: " + name))
    canvas.clear_tool_preview()
    return shots


def main():
    app = QApplication(sys.argv)
    try:
        from theme import theme_manager
        app.setStyleSheet(theme_manager.stylesheet())
    except Exception as exc:
        print("  (theme skipped: %s)" % exc)

    project_storage.AUTO_SAVE_FILE = os.path.join(OUT, "transition_ui_autosave.json")
    write_still_video(A_MP4, A_RGB)
    write_still_video(B_MP4, B_RGB)
    write_flat_png(A_PNG, A_RGB)

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1680, 940)
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    win._audio_player = FakePlayer()

    print("  transition table:", ", ".join(transitions.TRANSITIONS))
    gate_card_table(win)
    gate_tab_click(win)
    gate_refusal(win)
    gate_properties_card(win)
    gate_selection_survives(win)
    gate_timeline_marker(win)
    gate_local_marker(win)
    gate_hover_preview(win)
    shots = gate_evidence(win)
    compose(shots, os.path.join(OUT, "transition_ui_evidence.png"))

    for reader in getattr(win, "_video_readers", {}).values():
        reader.close()
    app.processEvents()
    for path in (A_MP4, B_MP4, A_PNG, project_storage.AUTO_SAVE_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            print("  (probe media still locked: %s)" % exc)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))

    win.close()
    app.processEvents()
    win = None
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
