"""
scratch/transition_probe.py
Bằng chứng cho lớp model/toán/undo của chuyển tiếp (task #22).

Chạy: QT_QPA_PLATFORM=windows python -u scratch/transition_probe.py

Phạm vi: model (chồng lấn + compact + ripple), toán (core/transitions.py), undo
(core/commands.py), persistence (core/project_storage.py). Ảnh bằng chứng ở đây
là ĐỒ THỊ CÔNG THỨC chứ không phải khung hình dựng thật — bằng chứng pixel thuộc
task áp state vào FrameComposer/preview.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtWidgets import QApplication                       # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QFont  # noqa: E402
from PySide6.QtCore import Qt                                    # noqa: E402

from core import transitions                                     # noqa: E402
from core.timeline_model import TimelineModel, TrackType, ClipModel  # noqa: E402
from core.commands import UndoStack, SetTransitionCommand         # noqa: E402
from core import project_storage                                 # noqa: E402

FAILS = []
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CANVAS = (1920.0, 1080.0)


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def near(name, got, want, tol=1e-6):
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        FAILS.append("%s: got %r want %r tol %r" % (name, got, want, tol))
    print("%s  %s  (got=%r want=%r)" % ("PASS" if ok else "FAIL", name, got, want))
    return ok


def positions(model):
    return {c.name: round(c.start_time, 4)
            for t in model.tracks for c in t.clips}


def story(durations=(5.0, 4.0, 3.0)):
    """Main Storyline gapless: A 0-5, B 5-9, C 9-12."""
    model = TimelineModel()
    track = model.add_track(TrackType.VIDEO)
    clips = [model.add_clip(track.track_id, "media%d.mp4" % i, "video",
                            0.0, duration, "clip%d" % i)
             for i, duration in enumerate(durations)]
    return model, track, clips


# ── 1. Model: chồng lấn, thứ tự vẽ, cửa sổ ─────────────────────

def test_model_layer():
    print("\n== 1. model: overlap / ordering / window ==")
    model, track, (a, b, c) = story()
    check("baseline gapless positions", positions(model),
          {"clip0": 0.0, "clip1": 5.0, "clip2": 9.0})
    check("baseline duration", round(model.duration, 3), 12.0)

    check("apply junction transition",
          model.set_transition(b.clip_id, "Cross Dissolve", 1.0), True)
    # B và C trượt trái đúng 1s -> chồng lấn thật giữa A và B.
    check("ripple after transition", positions(model),
          {"clip0": 0.0, "clip1": 4.0, "clip2": 8.0})
    check("duration shrank by overlap", round(model.duration, 3), 11.0)
    check("stored transition", b.transition,
          {"name": "Cross Dissolve", "duration": 1.0})
    check("transition survives deepcopy (undo snapshots)",
          bool(__import__("copy").deepcopy(b).transition), True)

    check("window is [B.start, A.end]",
          transitions.window(model.previous_clip(b), b), (4.0, 5.0))

    active = model.active_visual_clips_at(4.5)
    check("both clips active mid-window", [x.clip_id for x in active],
          [a.clip_id, b.clip_id])
    check("incoming clip draws last (on top)", active[-1].clip_id, b.clip_id)

    # Counterfactual: bỏ transition thì ripple trả lại chỗ cũ.
    model.set_transition(b.clip_id, "", 0.0)
    check("clear restores gapless", positions(model),
          {"clip0": 0.0, "clip1": 5.0, "clip2": 9.0})
    check("clear restores duration", round(model.duration, 3), 12.0)
    check("clear kills the window",
          transitions.window(model.previous_clip(b), b), None)


# ── 2. Toán: tiến độ, làm mượt, từng kiểu ──────────────────────

def test_math():
    print("\n== 2. math: progress / smoothing / kinds ==")
    model, track, (a, b, c) = story()
    model.set_transition(b.clip_id, "Cross Dissolve", 1.0)

    near("dissolve opacity at p=0",
         model.transition_state(b, 4.0, *CANVAS).opacity, 0.0)
    near("outgoing clip fully visible at p=0",
         model.transition_state(a, 4.0, *CANVAS).opacity, 1.0)

    mid = model.transition_state(b, 4.25, *CANVAS).opacity
    near("dissolve opacity at p=0.25 is smoothstep", mid, 0.15625)
    # Probe phải PHÂN BIỆT được smoothstep với linear: linear(0.25) = 0.25.
    check("probe discriminates linear vs smooth", abs(mid - 0.25) > 0.05, True)

    near("dissolve opacity at p=0.5",
         model.transition_state(b, 4.5, *CANVAS).opacity, 0.5)
    check("window is half-open: p=1 hands over",
          model.transition_state(b, 5.0, *CANVAS), transitions.NEUTRAL)

    samples = [model.transition_state(b, 4.0 + i / 20.0, *CANVAS).opacity
               for i in range(21)]
    check("dissolve monotonic non-decreasing",
          all(y >= x - 1e-12 for x, y in zip(samples, samples[1:])), True)

    near("slide incoming dx at p=0",
         transitions.incoming_state("Slide Left", 0.0, *CANVAS).dx, CANVAS[0])
    near("slide incoming dx at p=1",
         transitions.incoming_state("Slide Left", 1.0, *CANVAS).dx, 0.0)
    near("slide outgoing dx at p=1",
         transitions.outgoing_state("Slide Left", 1.0, *CANVAS).dx, -CANVAS[0])
    dx_series = [transitions.incoming_state("Slide Left", i / 20.0, *CANVAS).dx
                 for i in range(21)]
    check("slide incoming moves left monotonically",
          all(x >= y - 1e-9 for x, y in zip(dx_series, dx_series[1:])), True)

    check("wipe edge at p=0",
          transitions.incoming_state("Wipe Right", 0.0, *CANVAS).wipe[0], 0.0)
    near("wipe edge at p=1",
         transitions.incoming_state("Wipe Right", 1.0, *CANVAS).wipe[0], 1.0)
    check("wipe has a feather",
          transitions.incoming_state("Wipe Right", 0.5, *CANVAS).wipe[1] > 0.0, True)
    near("zoom scale at p=0",
         transitions.incoming_state("Zoom In", 0.0, *CANVAS).scale, 0.55)
    near("zoom scale at p=1",
         transitions.incoming_state("Zoom In", 1.0, *CANVAS).scale, 1.0)

    # Năng lượng âm thanh: hai gain bù nhau trong suốt cửa sổ.
    pairs = [(model.transition_gain(a, 4.0 + i / 10.0) +
              model.transition_gain(b, 4.0 + i / 10.0)) for i in range(11)]
    check("audio gains sum to 1 across window",
          all(abs(p - 1.0) < 1e-9 for p in pairs), True)
    near("incoming audio starts silent", model.transition_gain(b, 4.0), 0.0)
    near("outgoing audio ends silent", model.transition_gain(a, 5.0), 0.0)
    near("audio gain outside window", model.transition_gain(b, 6.0), 1.0)

    # afade cho exporter tính theo DÒNG CHẢY CỦA CLIP (exporter đã atrim theo
    # in_point và reset PTS), nên in_point không được dịch ramp nữa.
    check("afade plan is stream-local",
          transitions.audio_fades(b, a, c), [("in", 0.0, 1.0)])
    check("neighbour that hands over gets the mirror ramp",
          transitions.audio_fades(a, None, b), [("out", 4.0, 1.0)])
    b.in_point = 12.0
    check("in_point does not move the ramp",
          transitions.audio_fades(b, a, c), [("in", 0.0, 1.0)])
    b.in_point = 0.0


# ── 3. Local fade: không cần clip pair ─────────────────────────

def test_local_fades():
    print("\n== 3. local fades ==")
    model, track, clips = story((4.0,))
    solo = clips[0]

    check("fade in accepted on lone clip",
          model.set_transition(solo.clip_id, "Fade In", 1.0), True)
    near("fade in opacity at t=0",
         model.transition_state(solo, 0.0, *CANVAS).opacity, 0.0)
    near("fade in opacity at t=0.25",
         model.transition_state(solo, 0.25, *CANVAS).opacity, 0.15625)
    near("fade in complete after duration",
         model.transition_state(solo, 1.0, *CANVAS).opacity, 1.0)
    near("fade in audio gain at t=0", model.transition_gain(solo, 0.0), 0.0)

    model.set_transition(solo.clip_id, "Fade Out", 1.0)
    near("fade out still opaque mid-clip",
         model.transition_state(solo, 1.5, *CANVAS).opacity, 1.0)
    near("fade out at clip end",
         model.transition_state(solo, 4.0, *CANVAS).opacity, 0.0)
    near("fade out audio gain at end", model.transition_gain(solo, 4.0), 0.0)
    check("fade plan for exporter", transitions.audio_fades(solo, None, None),
          [("out", 3.0, 1.0)])

    # Local fade không được ripple vị trí.
    check("local fade keeps position", round(solo.start_time, 4), 0.0)

    audio_track = model.add_track(TrackType.AUDIO)
    tone = model.add_clip(audio_track.track_id, "tone.wav", "audio",
                          0.0, 2.0, "tone")
    check("audio clip can fade",
          model.set_transition(tone.clip_id, "Fade In", 0.5), True)
    check("afade plan for audio fade", transitions.audio_fades(tone, None, None),
          [("in", 0.0, 0.5)])

    tiny = model.add_clip(audio_track.track_id, "tick.wav", "audio",
                          2.0, 0.1, "tick")
    near("0.1s clip has no fade room",
         model.max_transition_duration(tiny.clip_id, "Fade In"), 0.0)
    check("0.1s clip rejects fade",
          model.set_transition(tiny.clip_id, "Fade In", 1.0), False)


# ── 4. Validation ──────────────────────────────────────────────

def test_validation():
    print("\n== 4. validation ==")
    model, track, (a, b, c) = story()
    model.set_transition(b.clip_id, "Cross Dissolve", 99.0)
    near("clamp to min(A,B)-MIN_KEEP", b.transition["duration"], 3.9)
    near("clamped ripple equals clamped duration", b.start_time,
         a.end_time - b.transition["duration"])

    model2, track2, clips2 = story((5.0, 0.15, 3.0))
    b2 = clips2[1]
    near("very short clip has tiny room",
         model2.max_transition_duration(b2.clip_id, "Cross Dissolve"), 0.05)
    check("very short clip still accepts transition at max",
          model2.set_transition(b2.clip_id, "Cross Dissolve", 5.0), True)
    near("short clip stored clamped duration", b2.transition["duration"], 0.05)

    model3, track3, clips3 = story((4.0,))
    lone = clips3[0]
    check("first clip has no junction partner",
          model3.max_transition_duration(lone.clip_id, "Cross Dissolve"), 0.0)
    check("first clip rejects junction",
          model3.set_transition(lone.clip_id, "Cross Dissolve", 1.0), False)
    check("rejected junction left no state", lone.transition, {})

    # Overlay track: junction chưa hỗ trợ (collision logic nhảy layer sẽ phá chồng lấn).
    model4, track4, clips4 = story()
    overlay = model4.add_track(TrackType.VIDEO)
    x = model4.add_clip(overlay.track_id, "x.mp4", "video", 0.0, 3.0, "x")
    y = model4.add_clip(overlay.track_id, "y.mp4", "video", 3.0, 3.0, "y")
    check("second video row is not the main storyline",
          overlay.is_main_track, False)
    check("overlay rejects junction",
          model4.max_transition_duration(y.clip_id, "Cross Dissolve"), 0.0)
    check("overlay still allows local fade",
          model4.max_transition_duration(y.clip_id, "Fade In") > 0.0, True)
    check("unknown name rejected",
          model4.set_transition(y.clip_id, "Nyan Cat Special", 1.0), False)
    track4.is_locked = True
    check("locked track rejects transition",
          model4.set_transition(clips4[1].clip_id, "Cross Dissolve", 1.0), False)
    track4.is_locked = False
    check("video clip on audio-only kind still needs a partner",
          model4.max_transition_duration(x.clip_id, "Cross Dissolve"), 0.0)


# ── 5. Chuyển tiếp sống sót các phép edit khác ─────────────────

def test_edits_keep_transitions():
    print("\n== 5. edits keep the overlap alive ==")
    model, track, (a, b, c) = story()
    model.set_transition(b.clip_id, "Cross Dissolve", 1.0)

    # Thêm clip mới phải nối vào ĐUÔI thật (max end), không phải tổng duration.
    d = model.add_clip(track.track_id, "d.mp4", "video", 0.0, 2.0, "d")
    check("magnetic append uses real end", round(d.start_time, 4), 11.0)
    check("window valid after append",
          transitions.window(model.previous_clip(b), b), (4.0, 5.0))

    model.resize_clip(b.clip_id, 3.0)
    check("window survives trim", transitions.window(model.previous_clip(b), b),
          (4.0, 5.0))

    right = model.split_clip(b.clip_id, 5.5)
    check("split right half drops the transition", right.transition, {})
    check("split keeps the overlap on the left half",
          transitions.window(model.previous_clip(b), b), (4.0, 5.0))
    check("split halves stay adjacent", round(b.end_time, 4) == round(right.start_time, 4),
          True)

    model.place_clip_ripple(d.clip_id, 30.0)
    check("window survives reorder", transitions.window(model.previous_clip(b), b),
          (4.0, 5.0))

    # Xóa clip phía trước: transition thành vô hiệu, không crash, không vẽ gì lạ.
    model.remove_clip(a.clip_id)
    check("orphaned window becomes inert",
          transitions.window(model.previous_clip(b), b), None)
    check("inert window renders neutral",
          model.transition_state(b, 4.0, *CANVAS), transitions.NEUTRAL)
    check("clip after removal still plays at full opacity",
          model.transition_state(b, 2.0, *CANVAS), transitions.NEUTRAL)


# ── 6. Undo / Redo ────────────────────────────────────────────

def test_undo():
    print("\n== 6. undo / redo ==")
    model, track, (a, b, c) = story()
    stack = UndoStack()
    before = positions(model)

    stack.push(SetTransitionCommand(model, b.clip_id, "Wipe Right", 1.0))
    applied = positions(model)
    check("command applied ripple", applied,
          {"clip0": 0.0, "clip1": 4.0, "clip2": 8.0})
    stack.undo()
    check("undo restores every position", positions(model), before)
    check("undo clears transition", b.transition, {})
    check("undo restores duration", round(model.duration, 3), 12.0)
    stack.redo()
    check("redo re-applies ripple", positions(model), applied)
    check("redo restores transition", b.transition,
          {"name": "Wipe Right", "duration": 1.0})

    # Đổi kiểu chuyển tiếp cũng là MỘT bước undo.
    stack.push(SetTransitionCommand(model, b.clip_id, "Zoom In", 0.5))
    check("switch stores one transition only", b.transition,
          {"name": "Zoom In", "duration": 0.5})
    check("switch re-ripples", round(b.start_time, 4), 4.5)
    stack.undo()
    check("undo of switch returns to previous kind", b.transition,
          {"name": "Wipe Right", "duration": 1.0})
    check("undo of switch returns to previous position",
          round(b.start_time, 4), 4.0)
    stack.redo()
    check("redo of switch lands again", (b.transition["name"], round(b.start_time, 4)),
          ("Zoom In", 4.5))

    # Xóa chuyển tiếp bằng command rồi hoàn tác phải dựng lại đủ chồng lấn.
    stack.push(SetTransitionCommand(model, b.clip_id, "", 0.0))
    check("clear command ripples back", positions(model), before)
    stack.undo()
    check("undo of clear rebuilds the overlap", positions(model),
          {"clip0": 0.0, "clip1": 4.5, "clip2": 8.5})
    check("undo of clear restores state", b.transition,
          {"name": "Zoom In", "duration": 0.5})

    # Command thất bại không được để lại trạng thái lửng.
    snapshot = positions(model)
    stack.push(SetTransitionCommand(model, a.clip_id, "Cross Dissolve", 1.0))
    check("failed command left clip untouched", a.transition, {})
    check("failed command left positions untouched", positions(model), snapshot)


# ── 7. Persistence ────────────────────────────────────────────

def test_persistence():
    print("\n== 7. persistence ==")
    model, track, (a, b, c) = story()
    model.set_transition(b.clip_id, "Cross Dissolve", 1.0)
    model.add_clip(track.track_id, "tail.mp4", "video", 0.0, 2.0, "tail")

    clinq = os.path.join(OUT_DIR, "transition_project.clinq")
    check("save_project_to_file",
          project_storage.save_project_to_file(model, clinq), True)
    restored = TimelineModel()
    project_storage.restore_model_from_clinq(
        restored, project_storage.load_project_from_file(clinq))
    clips = [cl for t in restored.tracks for cl in t.clips]
    check("clinq round-trip transition",
          [cl.transition for cl in clips if cl.transition],
          [{"name": "Cross Dissolve", "duration": 1.0}])
    check("clinq round-trip positions", positions(restored),
          {"clip0": 0.0, "clip1": 4.0, "clip2": 8.0, "tail": 11.0})
    check("clinq round-trip duration", round(restored.duration, 3), 13.0)
    incoming = restored.get_clip(b.clip_id)
    check("restored transition still animates",
          restored.transition_state(incoming, 4.5, *CANVAS).opacity < 1.0, True)
    check("restored partner lookup works",
          restored.previous_clip(incoming).clip_id, a.clip_id)

    # Legacy autosave: trỏ file tạm để KHÔNG đụng vào autosave.json thật.
    real = project_storage.AUTO_SAVE_FILE
    project_storage.AUTO_SAVE_FILE = os.path.join(OUT_DIR, "transition_autosave.json")
    try:
        check("legacy autosave write", project_storage.save_project(model), True)
        legacy_model = TimelineModel()
        project_storage.restore_model(legacy_model, project_storage.load_project())
        check("autosave round-trip positions", positions(legacy_model),
              {"clip0": 0.0, "clip1": 4.0, "clip2": 8.0, "tail": 11.0})
    finally:
        project_storage.AUTO_SAVE_FILE = real
        for name in ("transition_autosave.json",):
            path = os.path.join(OUT_DIR, name)
            if os.path.exists(path):
                os.remove(path)

    # Project cũ (không có field) / dữ liệu rác phải được tha thứ.
    check("missing transition tolerated",
          project_storage.deserialize_transition(None), {})
    check("junk transition name tolerated",
          project_storage.deserialize_transition(
              {"name": "Ghost Effect", "duration": 2}), {})
    check("string duration tolerated",
          project_storage.deserialize_transition(
              {"name": "Fade In", "duration": "0.7"}),
          {"name": "Fade In", "duration": 0.7})
    legacy_clip = ClipModel(name="old", duration=4.0)
    check("clip without the field still renders",
          transitions.clip_state(legacy_clip, None, None, 1.0, *CANVAS),
          transitions.NEUTRAL)


# ── 8. Đồ thị công thức (bằng chứng ảnh của lớp toán) ──────────

class _FadeClip:
    """Chỉ đủ hai thuộc tính local_fade_state cần; không thay model thật."""

    def __init__(self, duration, span):
        self.duration = duration
        self.transition = {"name": "Fade In", "duration": span}


def draw_curves():
    print("\n== 8. formula chart ==")
    junction = (("dissolve", "Cross Dissolve", lambda s: s.opacity),
                ("zoom scale", "Zoom In", lambda s: (s.scale - 0.55) / 0.45),
                ("slide dx", "Slide Left", lambda s: s.dx / CANVAS[0]),
                ("wipe edge", "Wipe Right", lambda s: s.wipe[0] if s.wipe else 1.0))
    steps = [i / 60.0 for i in range(61)]
    series = []
    for label, name, read in junction:
        series.append((label, [(p, float(read(
            transitions.incoming_state(name, p, *CANVAS)))) for p in steps]))
    series.append(("audio in", [(p, transitions._smooth(p)) for p in steps]))
    series.append(("audio out", [(p, 1.0 - transitions._smooth(p)) for p in steps]))

    # Local fade có cửa sổ riêng (d giây đầu clip) nên lấy mẫu theo local_time.
    fade = _FadeClip(4.0, 1.0)
    series.append(("fade in (t/clip len)", [(local / 4.0, transitions.local_fade_state(
        "Fade In", fade, local).opacity) for local in steps[:]]))

    w, h = 960, 560
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#101014"))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setFont(QFont("Segoe UI", 9))
    left, top, plot_w, plot_h = 60, 48, w - 110, h - 230

    painter.setPen(QPen(QColor("#2A2A33"), 1))
    for i in range(11):
        x = left + plot_w * i / 10.0
        painter.drawLine(int(x), top, int(x), top + plot_h)
        y = top + plot_h * i / 10.0
        painter.drawLine(left, int(y), left + plot_w, int(y))
    painter.setPen(QColor("#9A9AA8"))
    painter.drawText(left, top - 24, 700, 16, Qt.AlignLeft,
                     "core/transitions.py math: normalized value vs progress p across the overlap window")
    for value, text in ((1.0, "1.0"), (0.5, "0.5"), (0.0, "0.0")):
        painter.drawText(0, int(top + plot_h * (1.0 - value)), left - 8, 16,
                         Qt.AlignRight, text)
    for tick in range(11):
        painter.drawText(int(left + plot_w * tick / 10.0) - 12,
                         top + plot_h + 4, 30, 14, Qt.AlignHCenter,
                         "%.1f" % (tick / 10.0))

    colors = ["#8B5CF6", "#EC4899", "#4FC3F7", "#EF4444", "#22C55E", "#F59E0B"]
    for index, (label, pts) in enumerate(series):
        color = QColor(colors[index % len(colors)])
        painter.setPen(QPen(color, 2))
        for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
            painter.drawLine(
                int(left + plot_w * p0),
                int(top + plot_h * (1.0 - max(0.0, min(1.0, v0)))),
                int(left + plot_w * p1),
                int(top + plot_h * (1.0 - max(0.0, min(1.0, v1)))))
        # Chú giải có ô màu: đặt nhãn rời dọc trục hoành từng bị đọc nhầm thành
        # "mỗi đường chỉ là một đoạn" của cùng một phép nội suy.
        row, column = divmod(index, 4)
        lx = left + column * 250
        ly = top + plot_h + 34 + row * 22
        painter.setPen(QPen(color, 3))
        painter.drawLine(lx, ly + 6, lx + 22, ly + 6)
        painter.setPen(QColor("#C8C8D4"))
        text_x = lx + 30
        limit = (left + 250 - 12) if column == 0 else (left + plot_w - 6)
        metrics = painter.fontMetrics()
        check("legend label '%s' fits" % label,
              metrics.horizontalAdvance(label) <= limit - text_x, True)
        painter.drawText(text_x, ly, limit - text_x, 16,
                         Qt.AlignLeft | Qt.AlignVCenter, label)
    painter.end()

    path = os.path.join(OUT_DIR, "transition_curves.png")
    check("curve chart saved", img.save(path), True)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    check("curve chart not trivial", size > 8000, True)
    print("   chart: %s (%d bytes, %d series)" % (path, size, len(series)))

    # Đường vẽ phải đến từ hàm production, không phải công thức chép lại trong probe.
    near("chart series matches shipped incoming_state", series[0][1][15][1],
         transitions.incoming_state("Cross Dissolve", 0.25, *CANVAS).opacity)
    check("chart is not a linear ramp", abs(series[0][1][15][1] - 0.25) > 0.05, True)
    check("every chart value stayed in range",
          all(0.0 <= v <= 1.0 for _l, pts in series for _p, v in pts), True)


def main():
    app = QApplication(sys.argv)
    test_model_layer()
    test_math()
    test_local_fades()
    test_validation()
    test_edits_keep_transitions()
    test_undo()
    test_persistence()
    draw_curves()
    print("\n" + "=" * 62)
    if FAILS:
        print("%d FAIL:" % len(FAILS))
        for line in FAILS:
            print("  - " + line)
        return 1
    print("summary: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
