"""
scratch/transition_apply_probe.py
Bằng chứng cho LỚP ÁP DỤNG chuyển tiếp: công thức trong core/transitions.py phải
thực sự hiện lên khung hình, và preview (Player Canvas) phải khớp export
(FrameComposer) từng pixel một.

Ba loại gate:
  - parity  : cùng một model, cùng thời điểm t, ảnh grab từ scene của canvas thật
              và ảnh từ bộ dựng hình xuất phải gần như identical (MAE nhỏ).
  - shape   : đường cong ĐO ĐƯỢC trên ảnh phải khớp smoothstep chứ không khớp ramp
              tuyến tính. Parity so một bộ dựng hình với chính nó nên không bao
              giờ phát hiện loại lỗi "có áp dụng nhưng áp sai công thức"; gate
              này thì có.
  - revert  : bỏ chuyển tiếp thì khung hình phải trở về nguyên bản — chứng minh
              thứ ta đo là chuyển tiếp, không phải một hiệu ứng khác tình cờ đi
              theo.

Media là video tĩnh tự sinh (màu phẳng), vì junction transition chỉ sống trên Main
Storyline tức track VIDEO. Video tĩnh để mọi pixel thay đổi đều đến từ chuyển tiếp
chứ không đến từ nội dung; và vì hai đường giải mã (theo frame index ở preview,
theo msec ở export) phải đọc đúng cùng một nguồn.

QMediaPlayer thật được thay bằng recorder: logic chọn nguồn, đổi nguồn ở điểm
crossover, tính seek và đặt volume vẫn chạy y nguyên, chỉ thiết bị phát là giả để
probe không phát tiếng ra loa.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/transition_apply_probe.py
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
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

import core.project_storage as project_storage
from core import transitions
from core.frame_composer import FrameComposer
from core.timeline_model import TrackType, track_type_for_media

W, H = 640, 360
DUR = 5.0
OVERLAP = 1.0
PS = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9]
JUNCTIONS = ["Cross Dissolve", "Zoom In", "Slide Left", "Wipe Right"]
# (ten, giay dau cua ramp, dao nguc tien do hay khong)
LOCALS = [("Fade In", 0.0, False), ("Fade Out", 3.0, True)]

A_MP4 = os.path.join(OUT, "transition_apply_A.mp4")
B_MP4 = os.path.join(OUT, "transition_apply_B.mp4")
A_PNG = os.path.join(OUT, "transition_apply_A.png")
CLINQ = os.path.join(OUT, "transition_apply_project.clinq")

A_RGB = (200, 30, 30)     # nền clip "đi"
B_RGB = (30, 60, 200)     # nền clip "đến" — hai màu đối lập để đo bằng kênh màu

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def near(label, got, want, tol):
    ok = abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %r want %r+-%r" % (label, got, want, tol))
    print("%-58s %s got=%r want~%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def smooth(p):
    return p * p * (3.0 - 2.0 * p)


def below(label, value, limit):
    """Gate kem theo SO DO, khong chi True/False — de doc bang chung duoc."""
    ok = value < limit
    if not ok:
        fails.append("%s: got %.2f want < %.2f" % (label, value, limit))
    print("%-58s %s diff=%.2f limit=%.2f" % (label, "PASS" if ok else "FAIL", value, limit))
    return ok


# ── Sinh media ──────────────────────────────────────────────────

def write_still_video(path, rgb, seconds=6.0, fps=12.0):
    """Video một màu duy nhất, không chuyển động: mọi khác biệt pixel đều là sản
    phẩm của transition chứ không phải của nội dung."""
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


def to_qimage(arr) -> QImage:
    data = np.clip(arr, 0, 255).astype(np.uint8)
    h, w = data.shape[0], data.shape[1]
    img = QImage(data.tobytes(), w, h, 4 * w, QImage.Format.Format_RGBA8888)
    return img.copy()


def mae(a, b) -> float:
    return float(np.abs(a[:, :, :3] - b[:, :, :3]).mean())


def mean_red(arr) -> float:
    return float(arr[:, :, 0].mean())


def column_tints(arr):
    """(R trung bình theo cột, B trung bình theo cột) — dài đúng W cột."""
    return arr[:, :, 0].mean(axis=0), arr[:, :, 2].mean(axis=0)


def first_true(flags):
    """Index cột đầu tiên thỏa điều kiện, hoặc len(flags) nếu không có cột nào."""
    if not np.any(flags):
        return len(flags)
    return int(np.argmax(flags))


def changed_width(arr, ref, threshold=10):
    """Bề rộng vùng ảnh khác với ref — thước đo kích thước clip đang phóng to."""
    mask = np.abs(arr[:, :, :3] - ref[:, :, :3]).max(axis=2) > threshold
    cols = mask.any(axis=0)
    if not cols.any():
        return 0
    last = len(cols) - 1 - int(np.argmax(cols[::-1]))
    return last - first_true(cols) + 1


def shape_gate(label, measured, smooth_pred, linear_pred, tol):
    """Đường cong đo được phải bám smoothstep, không phải ramp tuyến tính."""
    err_s = max(abs(m - s) for m, s in zip(measured, smooth_pred))
    err_l = max(abs(m - l) for m, l in zip(measured, linear_pred))
    print("    %-22s meas=%s err smooth=%.1f linear=%.1f"
          % (label, ",".join("%.0f" % m for m in measured), err_s, err_l))
    check(label + ": matches the smoothstep curve", err_s <= tol, True)
    check(label + ": is not a linear ramp", err_s < err_l, True)


# ── Player giả ──────────────────────────────────────────────────

class FakePlayer:
    """Ghi lại mọi lệnh app gửi tới media player; không giải mã, không phát tiếng."""

    def __init__(self):
        self._source = QUrl()
        self.position_ms = 0
        self.state = QMediaPlayer.PlayingState
        self.calls = []
        # QMediaPlayer thật có playback rate; app đổi nhịp phát theo tốc độ clip
        # nên fake phải nhớ con số đó, không được im lặng bỏ qua.
        self.rate = 1.0

    def source(self):
        return self._source

    def position(self):
        return self.position_ms

    def playbackRate(self):
        return self.rate

    def isPlaybackRateSupported(self, rate):
        return 0.25 <= float(rate) <= 4.0

    def setPlaybackRate(self, rate):
        self.calls.append(("setPlaybackRate", float(rate)))
        self.rate = float(rate)

    def playbackState(self):
        return self.state

    def setSource(self, url):
        self.calls.append(("setSource", url.toLocalFile()))
        self._source = url

    def setPosition(self, ms):
        self.calls.append(("setPosition", int(ms)))

    def play(self):
        self.calls.append(("play",))
        self.state = QMediaPlayer.PlayingState

    def pause(self):
        self.calls.append(("pause",))
        self.state = QMediaPlayer.PausedState

    def stop(self):
        self.calls.append(("stop",))
        self.state = QMediaPlayer.StoppedState


# ── Dựng model trên MainWindow thật ─────────────────────────────

def clear_model(win):
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    model.project_ratio = "16:9"
    model.playhead = 0.0
    return model


def build_pair(win, name):
    """Hai clip video nối tiếp trên Main Storyline; clip sau mang transition."""
    model = clear_model(win)
    track = model.add_track(TrackType.VIDEO, "Main")
    check("pair: the row is the magnetic Main Storyline", bool(track.is_main_track), True)
    clip_a = model.add_clip(track.track_id, A_MP4, "video", 0.0, DUR, "left.mp4")
    clip_b = model.add_clip(track.track_id, B_MP4, "video", 0.0, DUR, "right.mp4")
    check("pair: both clips landed on the main row",
          [clip_a is not None, clip_b is not None], [True, True])
    if name:
        check("ripple: apply %s to the incoming clip" % name,
              model.set_transition(clip_b.clip_id, name, OVERLAP), True)
    win._sync_canvas()
    window = (clip_b.start_time, clip_a.end_time) if name else None
    return model, clip_a, clip_b, window


def build_single(win, name):
    """Một clip ảnh duy nhất mang transition local — local không cần cặp và không
    cần Main Storyline nên chạy được cả trên overlay track."""
    model = clear_model(win)
    track = model.add_track(track_type_for_media("image"), "Overlay")
    clip = model.add_clip(track.track_id, A_PNG, "image", 0.0, 4.0, "only.png")
    check("local: clip exists", clip is not None, True)
    if name:
        check("apply local %s" % name, model.set_transition(clip.clip_id, name, 1.0), True)
    win._sync_canvas()
    return model, clip


def export_frame(model, t) -> QImage:
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def preview_frame(win) -> QImage:
    """Vẽ đúng scene mà Player Canvas đang hiển thị, ở cỡ project rồi hạ cỡ xuất."""
    scene = win.preview_panel.canvas.scene()
    rect = scene.sceneRect()
    cw, ch = int(rect.width()), int(rect.height())
    img = QImage(cw, ch, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        scene.render(painter, QRectF(0, 0, cw, ch), rect)
    finally:
        painter.end()
    return img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def pair_frames(win, model, t):
    """(khung hình xuất, khung hình preview) tại t — cả hai qua code sản xuất."""
    win._sync_canvas_frames_at_time(t)
    return to_array(export_frame(model, t)), to_array(preview_frame(win))


def export_only(win, model, t):
    win._sync_canvas_frames_at_time(t)
    return to_array(export_frame(model, t))


# ── Gate ────────────────────────────────────────────────────────

def gate_baseline(win):
    """Không chuyển tiếp: tại t giữa cửa sổ tương lai vẫn chỉ là clip A."""
    model, clip_a, clip_b, _ = build_pair(win, "")
    check("baseline: no transition keeps the row gapless",
          round(clip_b.start_time, 3), DUR)
    t = DUR - 0.5 * OVERLAP
    exp, prev = pair_frames(win, model, t)
    plain_a = export_only(win, model, 2.0)
    check("baseline: frame at t=%.2f is plain clip A" % t, mae(exp, plain_a) < 2.0, True)
    # Video nen phai qua hai lan resample o preview (640 -> 1920 -> 640) nen
    # lech vai don vi mau la het su; chuyen tiep lech hang chuc don vi.
    below("baseline: preview == export with no transition", mae(exp, prev), 6.0)

    # Nền B thuần: video đứng một mình, dùng để chắc rằng khung hình có chuyển
    # tiếp không đơn giản là "nhảy sang clip sau" sớm hơn.
    model = clear_model(win)
    track = model.add_track(TrackType.VIDEO, "Main")
    model.add_clip(track.track_id, B_MP4, "video", 0.0, DUR, "b.mp4")
    return exp, to_array(export_frame(model, 2.0))


def kind_predict(name, p, a_red, b_red):
    """Giá trị đo được kỳ vọng tại tiến độ p: (smoothstep, ramp tuyến tính)."""
    g, lin = smooth(p), p
    if name == "Cross Dissolve":
        return (a_red + (b_red - a_red) * g, a_red + (b_red - a_red) * lin)
    if name == "Wipe Right":
        return (W * g, W * lin)
    if name == "Slide Left":
        return (W * (1 - g), W * (1 - lin))
    if name == "Zoom In":
        return (W * (0.55 + 0.45 * g), W * (0.55 + 0.45 * lin))
    raise AssertionError(name)


def measure(name, arr, a_ref):
    if name == "Cross Dissolve":
        return mean_red(arr)
    if name == "Wipe Right":
        r_col, b_col = column_tints(arr)
        return float(first_true(r_col > b_col))
    if name == "Slide Left":
        r_col, b_col = column_tints(arr)
        return float(first_true(b_col > r_col))
    return float(changed_width(arr, a_ref))


def gate_junctions(win, a_ref, b_ref):
    a_red, b_red = mean_red(a_ref), mean_red(b_ref)
    check("probe media: A and B are far apart in red", abs(a_red - b_red) > 100, True)
    tiles, mid = [], {}

    for name in JUNCTIONS:
        model, clip_a, clip_b, window = build_pair(win, name)
        near("%s: overlap window equals the duration" % name,
             window[1] - window[0], OVERLAP, 0.001)

        meas, s_pred, l_pred = [], [], []
        worst_parity = 0.0
        row_exp, row_prev = [], []
        for p in PS:
            t = window[0] + p * (window[1] - window[0])
            exp, prev = pair_frames(win, model, t)
            worst_parity = max(worst_parity, mae(exp, prev))
            meas.append(measure(name, exp, a_ref))
            s_pred.append(kind_predict(name, p, a_red, b_red)[0])
            l_pred.append(kind_predict(name, p, a_red, b_red)[1])
            row_exp.append(to_qimage(exp))
            row_prev.append(to_qimage(prev))
            if p == 0.5:
                mid[name] = exp

        below("%s: preview matches export at every step" % name, worst_parity, 6.0)
        visible = sum(1 for item in win.preview_panel.canvas._clip_items.values()
                      if item.isVisible())
        check("%s: one timeline point draws both clips" % name, visible, 2)

        keep = [i for i, p in enumerate(PS)
                if p > 0.0 and (name != "Zoom In" or p >= 0.25)]
        tol = 8.0 if name == "Cross Dissolve" else 22.0
        shape_gate("%s curve" % name,
                   [meas[i] for i in keep], [s_pred[i] for i in keep],
                   [l_pred[i] for i in keep], tol)

        mid_t = window[0] + 0.5 * OVERLAP
        painted = export_only(win, model, mid_t)
        check("%s really paints over the plain frame" % name,
              mae(painted, a_ref) > 6.0, True)
        check("%s really paints over the next clip" % name,
              mae(painted, b_ref) > 6.0, True)

        check("%s: clearing the transition reports success" % name,
              model.set_transition(clip_b.clip_id, ""), True)
        win._sync_canvas()
        exp, prev = pair_frames(win, model, mid_t)
        check("%s cleared: export reverts to plain clip A" % name, mae(exp, a_ref) < 2.0, True)
        below("%s cleared: preview reverts too" % name, mae(prev, a_ref), 6.0)

        tiles.append(("%s export" % name, row_exp))
        tiles.append(("%s preview" % name, row_prev))

    for i, a in enumerate(JUNCTIONS):
        for b in JUNCTIONS[i + 1:]:
            check("%s and %s are visibly different" % (a, b), mae(mid[a], mid[b]) > 4.0, True)
    return tiles, mid


def gate_locals(win, a_ref):
    """Fade In/Out là kiểu local: chạy trên overlay track, chỉ cần một clip."""
    tiles = []
    # Noi dung local dung anh PNG nen phai lay moc chuẩn tu chinh PNG do,
    # khong dung a_ref cua video (mau nanh nen ap sang khac nhau vai %).
    ref_model, ref_clip = build_single(win, "")
    own_ref = to_array(export_frame(ref_model, 2.0))
    a_red = mean_red(own_ref)
    for name, fade_start, inverted in LOCALS:
        model, clip = build_single(win, name)
        meas, s_pred, l_pred = [], [], []
        worst_parity = 0.0
        row_exp, row_prev = [], []
        for p in PS:
            t = clip.start_time + fade_start + p * 1.0
            exp, prev = pair_frames(win, model, t)
            worst_parity = max(worst_parity, mae(exp, prev))
            prog = (1.0 - p) if inverted else p
            meas.append(mean_red(exp))
            s_pred.append(a_red * smooth(prog))
            l_pred.append(a_red * prog)
            row_exp.append(to_qimage(exp))
            row_prev.append(to_qimage(prev))
        below("%s: preview matches export at every step" % name, worst_parity, 6.0)
        keep = [i for i, p in enumerate(PS) if p > 0.0]
        shape_gate("%s brightness curve" % name,
                   [meas[i] for i in keep], [s_pred[i] for i in keep],
                   [l_pred[i] for i in keep], 8.0)

        outside_t = clip.start_time + (2.0 if name == "Fade In" else 0.5)
        exp, prev = pair_frames(win, model, outside_t)
        check("%s outside its span leaves the frame alone" % name,
              mae(exp, own_ref) < 2.0, True)
        below("%s outside its span still matches export" % name, mae(exp, prev), 6.0)
        tiles.append(("%s export" % name, row_exp))
        tiles.append(("%s preview" % name, row_prev))
    return tiles


def gate_audio(win):
    model, clip_a, clip_b, window = build_pair(win, "Cross Dissolve")
    player = FakePlayer()
    win._audio_player = player
    win._play_timer.start(20000)   # active để code không tự pre-buffer, nhưng không tick

    p025 = window[0] + 0.25 * OVERLAP
    p075 = window[0] + 0.75 * OVERLAP
    ga = model.transition_gain(clip_a, p025)
    gb = model.transition_gain(clip_b, p025)
    near("audio: outgoing gain at p=0.25", ga, 1 - smooth(0.25), 0.001)
    near("audio: incoming gain at p=0.25", gb, smooth(0.25), 0.001)
    near("audio: the two gains sum to one", ga + gb, 1.0, 0.001)

    owner, _ = win._preview_audio_owner(p025)
    check("audio: owner before the crossover is clip A", owner.clip_id == clip_a.clip_id, True)
    owner, _ = win._preview_audio_owner(p075)
    check("audio: owner after the crossover is clip B", owner.clip_id == clip_b.clip_id, True)

    path_url = QUrl.fromLocalFile(clip_a.source_path)
    # Qt tra ve duong dan gach cheo, project luu gach nguoc: app phai so duoc
    # hai lieu nay chu khong doi duong dan trong tay nhau.
    check("audio: QUrl path still matches the clip path",
          win._same_media(path_url.toLocalFile(), clip_a.source_path), True)
    player.setSource(path_url)

    win._apply_preview_audio(p025)
    near("audio: QAudioOutput volume tracks the gain",
         win._audio_output.volume(), ga, 0.001)
    check("audio: staying with the same owner does not reload the media",
          any(c[0] == "setSource" and win._same_media(c[1], clip_b.source_path)
              for c in player.calls), False)

    player.calls.clear()
    win._apply_preview_audio(p075)
    swaps = [c[1] for c in player.calls if c[0] == "setSource"]
    check("audio: the crossover loads the new source",
          bool(swaps) and win._same_media(swaps[-1], clip_b.source_path), True)
    seeks = [c[1] for c in player.calls if c[0] == "setPosition"]
    check("audio: the crossover seeks before playing", bool(seeks), True)
    near("audio: the seek lands on B local time", seeks[-1] / 1000.0,
         p075 - clip_b.start_time + clip_b.in_point, 0.001)
    near("audio: volume tracks the new owner", win._audio_output.volume(),
         model.transition_gain(clip_b, p075), 0.001)

    # Đổi nguồn cũng là một lần seek: position có thể còn 0 trong lúc file mới nạp.
    # Đồng hồ không được vì thế mà kéo playhead nhảy ngược về đầu timeline.
    model.playhead = p075
    player.position_ms = 0
    win._on_play_step()
    check("playhead never rewinds when the source changes", model.playhead > p075, True)

    win._apply_preview_audio(model.duration + 5.0)
    near("audio: no owner under the playhead restores full volume",
         win._audio_output.volume(), 1.0, 0.001)

    win._audio_output.setVolume(0.3)
    win._on_play_toggled(False)
    near("pause resets the volume", win._audio_output.volume(), 1.0, 0.001)

    win._audio_output.setVolume(0.4)
    win._stop_playback_at_end()
    near("end of playback resets the volume", win._audio_output.volume(), 1.0, 0.001)

    # Một bước play thường phải TỰ áp gain — đây là mối nối thật trong app
    win._play_timer.start(20000)
    model.playhead = window[0]
    player.setSource(QUrl.fromLocalFile(clip_a.source_path))
    player.state = QMediaPlayer.PlayingState
    player.position_ms = int((window[0] + 0.4 - clip_a.start_time + clip_a.in_point) * 1000)
    win._on_play_step()
    check("stepping playback advances the playhead", round(model.playhead, 3), 4.4)
    near("stepping playback applies the transition gain",
         win._audio_output.volume(), 1 - smooth(0.4), 0.002)
    win._play_timer.stop()


def gate_persistence(win, a_ref, b_ref):
    """Đã áp dụng thì phải sống sót qua lưu/nạp — không chỉ nằm trong RAM."""
    model, clip_a, clip_b, window = build_pair(win, "Wipe Right")
    if os.path.exists(CLINQ):
        os.remove(CLINQ)
    project_storage.save_project_to_file(model, CLINQ, {"project_name": "apply-probe"})
    project = project_storage.load_project_from_file(CLINQ)
    check("persistence: project file written", bool(project), True)

    # Nạp lại vào ĐÚNG model đang bind với UI, như khi người dùng mở dự án
    project_storage.restore_model_from_clinq(model, project)
    clips = [c for track in model.tracks for c in track.clips]
    check("persistence: transition name survives the round-trip",
          [c.transition.get("name", "") for c in clips], ["", "Wipe Right"])
    near("persistence: the overlap survives the round-trip",
         clips[1].start_time, window[0], 0.001)

    win._sync_canvas()
    t = window[0] + 0.5 * OVERLAP
    exp, prev = pair_frames(win, model, t)
    check("persistence: reloaded project still paints the wipe",
          mae(exp, a_ref) > 6.0 and mae(exp, b_ref) > 6.0, True)
    below("persistence: reloaded project matches preview", mae(exp, prev), 6.0)


# ── Ảnh bằng chứng ──────────────────────────────────────────────

def evidence(tiles, mid):
    tw, th = 214, 120
    label_w, pad = 200, 6
    height = 40 + len(tiles) * (th + 20 + pad) + th + 44
    img = QImage(label_w + (tw + pad) * len(PS) + pad, height,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(14, 16, 20))
    painter = QPainter(img)
    painter.setPen(QColor(150, 220, 255))
    painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
    painter.drawText(8, 26,
                     "Transitions: one timeline through the exporter and through the player canvas")

    small = QFont("Segoe UI", 8)
    y = 40
    for label, frames in tiles:
        painter.setFont(small)
        painter.setPen(QColor(235, 235, 235))
        painter.drawText(6, y + th // 2, label)
        x = label_w
        for i, frame in enumerate(frames):
            painter.drawImage(QRectF(x, y, tw, th),
                              frame.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            painter.setPen(QColor(150, 150, 160))
            painter.drawText(x + 2, y + th + 13, "p=%.2f" % PS[i])
            x += tw + pad
        y += th + 20 + pad

    painter.setFont(small)
    painter.setPen(QColor(235, 235, 235))
    painter.drawText(6, y + th // 2, "four junction kinds at p=0.50")
    x = label_w
    for name in JUNCTIONS:
        painter.drawImage(QRectF(x, y, tw, th),
                          to_qimage(mid[name]).scaled(tw, th, Qt.IgnoreAspectRatio,
                                                      Qt.SmoothTransformation))
        painter.setPen(QColor(150, 150, 160))
        painter.drawText(x + 2, y + th + 13, name)
        x += tw + pad
    painter.end()
    path = os.path.join(OUT, "transition_apply_evidence.png")
    img.save(path)
    print("  saved", path, "%dx%d" % (img.width(), img.height()))


def main():
    app = QApplication(sys.argv)
    try:
        from theme import theme_manager
        app.setStyleSheet(theme_manager.stylesheet())
    except Exception as exc:
        print("  (theme skipped: %s)" % exc)

    # Autosave của app tuyệt đối không được đè lên file thật của người dùng.
    project_storage.AUTO_SAVE_FILE = os.path.join(OUT, "transition_apply_autosave.json")
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

    print("  transition table:", ", ".join(sorted(transitions.TRANSITIONS)))
    a_ref, b_ref = gate_baseline(win)
    tiles, mid = gate_junctions(win, a_ref, b_ref)
    tiles += gate_locals(win, a_ref)
    gate_audio(win)
    gate_persistence(win, a_ref, b_ref)
    evidence(tiles, mid)

    # Canvas giu decoder per clip; phai dong lai thi file moi xoa duoc
    for reader in getattr(win, "_video_readers", {}).values():
        reader.close()

    for path in (A_MP4, B_MP4, A_PNG, CLINQ,
                 project_storage.AUTO_SAVE_FILE):
        if os.path.exists(path):
            os.remove(path)

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))

    # Don cac doi tuong Qt theo thu tu co chu dich. De Python tu giai phong thi
    # QApplication co the bi huy truoc cua so, va C++ fast-fail luc thoat
    # (0xC0000409) che mat ket qua probe.
    win.close()
    app.processEvents()
    win = None
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
