"""scratch/settings_gate_probe.py

Bằng chứng ĐO ĐƯỢC cho cài đặt ứng dụng.

Nguyên tắc: một khóa chỉ được coi là "có tác dụng" khi đổi nó làm thay đổi HÀNH
VI đo được của đúng những object mà bản chạy thật dùng — SnapEngine của cú kéo
clip, clamp zoom của slider, UndoStack của Ctrl+Z, QTimer tự động lưu, số frame
mũi tên bước đi, nơi tạo thư mục dự án, và pixel thật mà ClipItem vẽ lên
timeline. Probe không dựng lại logic: nó nạp ui/main_window.py,
ui/timeline_panel.py, core/snap_engine.py, core/commands.py,
core/project_storage.py và ui/settings_dialog.py của chính app.

Mỗi gate đều có counterfactual: chạy lại phép đo với giá trị cài đặt khác phải
đổi kết quả. Gate mà mọi giá trị đều PASS thì không chứng minh gì.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/settings_gate_probe.py
"""

import json
import os
import shutil
import subprocess
import sys
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scratch"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

OUT = os.path.join(ROOT, "scratch")
SETTINGS_FILE = os.path.join(OUT, "settings_probe_settings.json")
PROBE_PROJECTS = os.path.join(OUT, "settings_probe_projects")
PROBE_PROJECTS_B = os.path.join(OUT, "settings_probe_projects_b")
os.environ["CLINGING_SETTINGS_PATH"] = SETTINGS_FILE

TONE_WAV = os.path.join(OUT, "clip_audio_tone.wav")
SEG_MP4 = os.path.join(OUT, "clip_audio_segments.mp4")
EVIDENCE = os.path.join(OUT, "settings_evidence.png")

import numpy as np
from PIL import Image, ImageDraw

from core import settings
from core.timeline_model import TrackType
from theme import theme_manager

FAILS = []
STATS = {"gates": 0}
EXPECTED_KEYS = {
    "theme", "project_dir", "default_fps", "playhead_step",
    "snapping_enabled", "snap_playhead", "snap_clip_edges", "snap_threshold",
    "min_zoom_px_per_sec", "show_waveform", "show_thumbnails", "undo_steps",
    "auto_save", "auto_save_interval",
}

# Giá trị CỐ Ý khác DEFAULTS: nếu code âm thầm dùng DEFAULTS thì các gate dưới
# FAIL而不是 trùng khớp.
WIN_SETTINGS = {
    "theme": "light",
    "project_dir": PROBE_PROJECTS,
    "default_fps": 24,
    "playhead_step": 3,
    "snapping_enabled": True,
    "snap_playhead": False,
    "snap_clip_edges": True,
    "snap_threshold": 20,
    "min_zoom_px_per_sec": 12,
    "show_waveform": True,
    "show_thumbnails": True,
    "undo_steps": 10,
    "auto_save": False,
    "auto_save_interval": 3,
}


def check(name, got, want):
    STATS["gates"] += 1
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def near(name, got, want, tol):
    STATS["gates"] += 1
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        FAILS.append("%s: got %r want %r tol %r" % (name, got, want, tol))
    print("%s  %s  (got=%.6f want=%.6f tol=%.6f)"
          % ("PASS" if ok else "FAIL", name, float(got), float(want), tol))
    return ok


def pump(times=6):
    from PySide6.QtWidgets import QApplication
    for _ in range(times):
        QApplication.processEvents()


def apply_map(**changes):
    """Đổi cài đặt bằng đúng đường production: cache là thứ app đọc."""
    values = settings.values()
    values.update(changes)
    settings.use(values)
    return values


def ensure_fixtures():
    if os.path.exists(TONE_WAV) and os.path.exists(SEG_MP4):
        return
    import clip_audio_probe
    clip_audio_probe.build_fixtures()


# ── 1. Hợp đồng module: chỉ khóa có hook mới được sống ─────────

def test_contract():
    print("\n== 1. module contract ==")
    check("DEFAULTS là đúng 14 khóa đã nối hook",
          sorted(settings.DEFAULTS), sorted(EXPECTED_KEYS))
    for ghost in ("gpu_accel", "preview_fps", "telemetry", "cache_policy",
                  "screen_record_dir", "auto_scroll", "language", "min_zoom",
                  "dynamic_timeline", "shortcut_preset"):
        check("khóa ma '%s' không còn tồn tại" % ghost,
              ghost in settings.DEFAULTS, False)

    clean = settings.sanitize({"theme": "LIGHT", "snapping_enabled": "true",
                               "snap_threshold": 999, "undo_steps": "7",
                               "playhead_step": 3.7, "bogus": 1})
    check("theme viết hoa về khóa chuẩn", clean["theme"], "light")
    check("chuỗi 'true' thành bool thật", clean["snapping_enabled"], True)
    check("threshold ngoài khoảng bị kẹp chứ không bị loại",
          clean["snap_threshold"], 50)
    check("chuỗi số '7' thành int rồi kẹp theo min", clean["undo_steps"], 10)
    check("3.7 frame làm tròn thành 4", clean["playhead_step"], 4)
    check("khóa lạ bị bỏ, không nhân bản vào file", "bogus" in clean, False)
    check("unknown_keys báo đúng khóa lạ",
          settings.unknown_keys({"bogus": 1, "theme": "dark"}), ["bogus"])

    check("project_dir None không hóa thành chuỗi 'None'",
          settings.sanitize({"project_dir": None})["project_dir"],
          settings.DEFAULTS["project_dir"])
    check("project_dir rỗng cũng vậy",
          settings.sanitize({"project_dir": "   "})["project_dir"],
          settings.DEFAULTS["project_dir"])
    check("file rác trả về mặc định chứ không ném lỗi",
          settings.sanitize("not a dict"), dict(settings.DEFAULTS))


# ── 2. Sống sót qua một process khác (restart thật) ────────────

def test_restart():
    print("\n== 2. values survive a second process ==")
    if os.path.exists(SETTINGS_FILE):
        os.remove(SETTINGS_FILE)
    saved = settings.save(WIN_SETTINGS)
    check("save trả về đúng bộ khóa đã validate", sorted(saved),
          sorted(EXPECTED_KEYS))
    with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
        on_disk = json.load(handle)
    check("file chỉ chứa các khóa app thật sự đọc", sorted(on_disk),
          sorted(EXPECTED_KEYS))

    code = ("import json,sys;sys.path.insert(0,r'%s');"
            "from core import settings;"
            "print(json.dumps(settings.reload()))" % ROOT)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          timeout=120, env=dict(os.environ))
    check("process thứ hai thoát 0", proc.returncode, 0)
    child = json.loads(proc.stdout.decode("utf-8"))
    check("process thứ hai đọc lại đúng giá trị đã ghi", child, saved)

    other = dict(os.environ)
    other["CLINGING_SETTINGS_PATH"] = os.path.join(OUT, "settings_absent.json")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          timeout=120, env=other)
    fresh = json.loads(proc.stdout.decode("utf-8"))
    check("counterfactual: file khác => đúng DEFAULTS", fresh,
          dict(settings.DEFAULTS))
    check("DEFAULTS không bị ai sửa trong bộ nhớ", settings.DEFAULTS["undo_steps"], 100)


# ── 3. Theme đổi là đổi thật ───────────────────────────────────

def test_theme():
    print("\n== 3. theme ==")
    from widgets.common import icon_color

    emits = []
    theme_manager.themeChanged.connect(lambda mode: emits.append(mode))
    theme_manager.set_mode("dark")
    before = theme_manager.stylesheet()
    color_dark = icon_color()
    changed = theme_manager.set_mode("dark")
    check("set_mode cùng giá trị không phát tín hiệu thừa", changed, False)
    check("và không có themeChanged giả", len(emits), 0)

    theme_manager.set_mode("light")
    after = theme_manager.stylesheet()
    check("mode đọc lại là light", theme_manager.mode, "light")
    check("một tín hiệu thật đã phát", emits, ["light"])
    check("stylesheet light khác dark", before != after, True)
    check("và độ dài stylesheet đổi thật",
          abs(len(before) - len(after)) > 200, True)
    check("icon color đảo theo theme", (color_dark, icon_color()),
          ("#FFFFFF", "#4A4D5A"))


# ── 4. Cửa sổ thật: mỗi khóa phải đổi hành vi đo được ─────────

def snap_kind(panel, start, end, exclude):
    """Loại snap trả về dạng chuỗi — None làm FAIL rõ hơn là abort cả probe."""
    result = panel.scene.request_snap(start, end, exclude)
    return result.snap_type if result else None


def clear_tracks(model):
    for track in list(model.tracks):
        model.remove_track(track.track_id)


def wait_for(item, attr, times=600):
    for _ in range(times):
        pump(1)
        if getattr(item, attr, None):
            return True
    return False


def view_rect(view, item):
    """mapFromScene(QRectF) trả về QPolygonF, không có .top() — chiếu 2 góc."""
    from PySide6.QtCore import QPointF, QRectF
    box = item.sceneBoundingRect()
    top_left = view.mapFromScene(QPointF(box.left(), box.top()))
    bottom_right = view.mapFromScene(QPointF(box.right(), box.bottom()))
    return QRectF(top_left, bottom_right).toAlignedRect()


def grab_clip_region(view, item, path):
    from PySide6.QtCore import QRect
    rect = view_rect(view, item)
    shot = view.viewport().grab()
    crop = shot.copy(QRect(rect.x(), rect.y(),
                           max(1, rect.width()), max(1, rect.height())))
    crop.save(path, "PNG")
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).astype(int)


def ink_count(arr, target, tol):
    return int((np.abs(arr - np.array(target)).sum(axis=2) <= tol).sum())


# 4 màu khối mà fixture mp4 thật sự chứa (clip_audio_probe.build_fixtures).
# Ngưỡng L1=60 vẫn bắt được ~19k pixel frame giải mã nhưng loại được màu dự
# phòng của ClipItem (32,57,114, lệch 115 so với khối xanh) — tol 150 thì hai
# màu này chồng nhau và gate "tắt thumbnail" PASS mà không đo gì.
FRAME_COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]


def frame_ink(arr, tol=60):
    mask = np.zeros(arr.shape[:2], bool)
    for color in FRAME_COLORS:
        mask |= np.abs(arr - np.array(color)).sum(axis=2) <= tol
    return int(mask.sum())


def test_live_window(win, panel):
    print("\n== 4. the running window obeys the file ==")
    model = panel.model
    values = settings.values()

    # auto_save + auto_save_interval
    check("auto_save tắt thì timer nghỉ thật",
          win._auto_save_timer.isActive(), False)
    check("interval lấy từ số phút trong file", win._auto_save_timer.interval(),
          values["auto_save_interval"] * 60 * 1000)
    apply_map(auto_save=True, auto_save_interval=10)
    win._apply_settings()
    check("bật lên thì timer chạy", win._auto_save_timer.isActive(), True)
    check("đổi số phút đổi interval ngay", win._auto_save_timer.interval(),
          600000)
    apply_map(auto_save=False, auto_save_interval=3)
    win._apply_settings()
    check("counterfactual: tắt là dừng", win._auto_save_timer.isActive(), False)
    apply_map(auto_save=values["auto_save"],
              auto_save_interval=values["auto_save_interval"])
    win._apply_settings()

    # min_zoom_px_per_sec
    slider = panel.header.zoom_slider
    check("slider nhận min từ cài đặt", slider.minimum(),
          values["min_zoom_px_per_sec"])
    slider.setValue(1)
    pump()
    check("kéo xuống 1 vẫn không dưới mức cài đặt",
          panel.mapper.px_per_sec, float(values["min_zoom_px_per_sec"]))
    apply_map(min_zoom_px_per_sec=5)
    win._apply_settings()
    slider.setValue(1)
    pump()
    check("counterfactual: min 5 thì xuống được 5",
          panel.mapper.px_per_sec, 5.0)
    check("mapper instances không kéo theo class-level",
          float(panel.mapper.MIN_PX_PER_SEC), 5.0)
    apply_map(min_zoom_px_per_sec=values["min_zoom_px_per_sec"])
    win._apply_settings()
    check("và class gốc vẫn là 5.0 cho window khác",
          type(panel.mapper).MIN_PX_PER_SEC, 5.0)

    # undo_steps, bằng lệnh thật của panel
    clear_tracks(model)
    track = model.add_track(TrackType.VIDEO)
    from core.commands import AddClipCommand
    for index in range(14):
        panel.undo_stack.push(AddClipCommand(
            model, track.track_id, "a.mp4", "video", index * 6.0, 4.0,
            "clip%02d" % index))
    check("undo_steps=10 nên lịch sử dừng ở 10",
          panel.undo_stack.undo_count, 10)
    check("giới hạn nằm trên object đang chạy",
          panel.undo_stack.max_history, 10)
    panel.undo_stack.set_max_history(4)
    check("hạ giới hạn thì cắt ngay, không chờ lệnh mới",
          panel.undo_stack.undo_count, 4)
    check("và undo vẫn dùng được sau khi cắt", panel.undo_stack.can_undo, True)
    apply_map(undo_steps=100)
    win._apply_settings()
    for index in range(20):
        panel.undo_stack.push(AddClipCommand(
            model, track.track_id, "a.mp4", "video", 100.0 + index * 6.0, 4.0,
            "x%02d" % index))
    check("counterfactual: 100 bước thì không cắt bớt",
          panel.undo_stack.undo_count, 24)
    apply_map(undo_steps=values["undo_steps"])
    win._apply_settings()
    check("giới hạn trở về 10 và cắt ngay về 10",
          panel.undo_stack.undo_count, 10)

    # snapping, đo qua đúng scene.request_snap mà ClipItem.itemChange gọi
    panel.mapper.set_zoom(48.0)
    clear_tracks(model)
    track = model.add_track(TrackType.VIDEO)
    # keep dài 6s (5.0–11.0), clip kéo dài 4s. Hai mép PHẢI có độ dài khác nhau:
    # nếu kéo một clip đúng bằng 6s vào 5.2 thì cả hai mép cách điểm hút 0.2s
    # như nhau và kết quả flip theo từng bit làm dấu — gate không còn đo gì.
    keep = model.add_clip(track.track_id, "a.mp4", "video", 5.0, 6.0, "keep")
    dragged = model.add_clip(track.track_id, "b.mp4", "video", 20.0, 4.0, "drag")
    # Main Storyline là magnetic: add_clip NỐI ĐUÔI và bỏ qua start_time xin
    # ở trên. Drag thật định vị bằng đúng phép gán mà ClipItem.itemChange làm,
    # nên fixture phải chốt mép bằng đó rồi ĐO lại — gate snap mà mép không nằm
    # đúng chỗ thì chỉ chứng minh là probe tự lừa mình.
    keep.start_time = 5.0
    dragged.start_time = 20.0
    model.playhead = 8.0
    panel.snap.end_drag()
    check("fixture: mép clip giữ nằm đúng 5.0–11.0",
          [round(keep.start_time, 3), round(keep.end_time, 3)], [5.0, 11.0])
    check("fixture: clip đang kéo cách mép mọi phía",
          [round(dragged.start_time, 3), round(dragged.end_time, 3)],
          [20.0, 24.0])
    check("fixture: exclude là clip đang kéo, không phải clip giữ",
          dragged.clip_id == keep.clip_id, False)

    near("ngưỡng giây tính từ pixel và zoom đang chạy",
         panel.snap.threshold_time, values["snap_threshold"] / 48.0, 1e-9)
    result = panel.scene.request_snap(5.2, 9.2, dragged.clip_id)
    check("mép đầu clip hút mép đầu đang kéo (edges bật)",
          [result.snap_type if result else None,
           round(result.snapped_time, 3) if result else None],
          ["clip_start", 5.0])
    result = panel.scene.request_snap(7.05, 11.05, dragged.clip_id)
    check("mép cuối clip cũng hút (kéo cả khối, trả về start đã dịch)",
          [result.snap_type if result else None,
           round(result.snapped_time, 3) if result else None],
          ["clip_end", 7.0])
    result = panel.scene.request_snap(8.05, 12.05, dragged.clip_id)
    check("snap_playhead TẮT nên playhead không hút nữa", result, None)

    apply_map(snap_playhead=True, snap_clip_edges=False)
    win._apply_settings()
    panel.snap.end_drag()
    result = panel.scene.request_snap(8.05, 12.05, dragged.clip_id)
    check("đảo cờ thì playhead hút còn mép clip thì không",
          [result.snap_type if result else None,
           round(result.snapped_time, 3) if result else None],
          ["playhead", 8.0])
    check("và mép clip 5.0 thành vô hình",
          panel.scene.request_snap(5.2, 9.2, dragged.clip_id), None)
    check("mép cuối 11.0 cũng vô hình",
          panel.scene.request_snap(7.05, 11.05, dragged.clip_id), None)

    apply_map(snap_playhead=values["snap_playhead"],
              snap_clip_edges=values["snap_clip_edges"])
    win._apply_settings()
    panel.snap.end_drag()
    check("trở lại cờ gốc thì hút mép trở lại",
          snap_kind(panel, 5.2, 9.2, dragged.clip_id), "clip_start")
    apply_map(snapping_enabled=False)
    win._apply_settings()
    check("tắt snapping là hết snap, kể cả ngay trên mép",
          panel.scene.request_snap(5.0, 9.0, dragged.clip_id), None)
    apply_map(snapping_enabled=True, snap_threshold=2)
    win._apply_settings()
    near("threshold 2 px @ 48 px/s = 0.0417 s", panel.snap.threshold_time,
         2 / 48.0, 1e-9)
    check("0.2 s cách mép thì KHÔNG bị hút với ngưỡng 2 px",
          panel.scene.request_snap(5.2, 9.2, dragged.clip_id), None)
    apply_map(snap_threshold=values["snap_threshold"])
    win._apply_settings()
    check("cùng input đó với ngưỡng 20 px thì bị hút",
          snap_kind(panel, 5.2, 9.2, dragged.clip_id), "clip_start")

    # project_dir + default_fps: tạo dự án thật, đọc file .clinq thật
    from ui.home_page import create_project_folder, get_projects_dir
    check("thư mục dự án đến từ cài đặt, không phải Path.home()",
          str(get_projects_dir()), PROBE_PROJECTS)
    if os.path.isdir(PROBE_PROJECTS):
        shutil.rmtree(PROBE_PROJECTS)
    folder = create_project_folder("ProbeProj")
    clinq = folder / "ProbeProj.clinq"
    check("dự án mới nằm trong thư mục cài đặt", clinq.exists(), True)
    with open(clinq, "r", encoding="utf-8") as handle:
        meta = json.load(handle)["project_meta"]
    check("fps trong metadata đến từ default_fps", meta["fps"],
          values["default_fps"])

    # playhead_step: đo bằng chính _step_frame mà phím mũi tên gọi
    from core.project_storage import ProjectManager
    ProjectManager().project_path = str(clinq)
    near("FPS của dự án vừa mở là số cài đặt",
         ProjectManager().project_meta.get("fps"), values["default_fps"], 1e-9)
    model.duration = 30.0
    model.playhead = 0.0
    win._step_frame(1)
    near("mũi tên phải bước đúng playhead_step frame", model.playhead,
         values["playhead_step"] / float(meta["fps"]), 1e-9)
    model.playhead = 0.0
    apply_map(playhead_step=1)
    win._apply_settings()
    win._step_frame(1)
    near("counterfactual: step=1 thì bước 1 frame", model.playhead,
         1.0 / float(meta["fps"]), 1e-9)
    model.playhead = 0.0
    apply_map(playhead_step=5)
    win._apply_settings()
    win._step_frame(-1)
    check("và lùi vẫn âm bước, không nhảy lung tung", model.playhead, 0.0)
    model.playhead = 1.0
    win._step_frame(-1)
    near("lùi 5 frame ở 24 fps", model.playhead, 1.0 - 5 / 24.0, 1e-9)
    apply_map(playhead_step=values["playhead_step"])
    win._apply_settings()

    # project_dir đổi là ăn ngay, không cần dựng lại app
    apply_map(project_dir=PROBE_PROJECTS_B)
    check("đổi project_dir là get_projects_dir đổi theo ngay",
          str(get_projects_dir()), PROBE_PROJECTS_B)
    check("và thư mục mới thật sự tồn tại", os.path.isdir(PROBE_PROJECTS_B), True)
    apply_map(project_dir=values["project_dir"])


# ── 5. Cài đặt đổi là pixel đổi ────────────────────────────────

def test_paint(win, panel):
    print("\n== 5. what the settings paint ==")
    from PySide6.QtCore import QUrl
    ensure_fixtures()

    model = panel.model
    win._audio_player.setSource(QUrl())
    clear_tracks(model)
    audio_track = model.add_track(TrackType.AUDIO)
    video_track = model.add_track(TrackType.VIDEO)
    audio_clip = model.add_clip(audio_track.track_id, TONE_WAV, "audio",
                                0.0, 4.0, "tone")
    video_clip = model.add_clip(video_track.track_id, SEG_MP4, "video",
                                0.0, 4.0, "seg")
    panel.mapper.set_zoom(120.0)
    panel.view.horizontalScrollBar().setValue(0)
    pump(10)

    scene = panel.scene
    a_item = scene._clip_items.get(audio_clip.clip_id)
    v_item = scene._clip_items.get(video_clip.clip_id)
    check("clip audio có item trên scene", a_item is not None, True)
    check("clip video có item trên scene", v_item is not None, True)
    a_item.refresh_media_extraction()
    v_item.refresh_media_extraction()
    check("sóng thật được giải mã từ file wav",
          wait_for(a_item, "audio_amplitudes"), True)
    check("thumbnail thật được giải mã từ file mp4",
          wait_for(v_item, "thumbnail_cache"), True)
    pump(10)

    view = panel.view
    vp = view.viewport().rect()
    rect_a = view_rect(view, a_item)
    rect_v = view_rect(view, v_item)
    check("clip audio nằm gọn trong viewport để đo pixel",
          rect_a.top() >= 0 and rect_a.bottom() <= vp.bottom()
          and rect_a.right() <= vp.right() and rect_a.width() > 60, True)
    check("clip video nằm gọn trong viewport",
          rect_v.top() >= 0 and rect_v.bottom() <= vp.bottom()
          and rect_v.right() <= vp.right() and rect_v.width() > 60, True)

    def shot(item, tag):
        return grab_clip_region(view, item,
                                os.path.join(OUT, "settings_shot_%s.png" % tag))

    on_wave = shot(a_item, "wave_on")
    on_thumb = shot(v_item, "thumb_on")
    cyan_on = ink_count(on_wave, (0, 255, 204), 90)
    seg_on = frame_ink(on_thumb)
    check("bật waveform thì pixel màu sóng xuất hiện", cyan_on > 200, True)
    check("bật thumbnail thì màu frame thật xuất hiện", seg_on > 1000, True)

    apply_map(show_waveform=False)
    win._apply_settings()
    pump(10)
    off_wave = shot(a_item, "wave_off")
    cyan_off = ink_count(off_wave, (0, 255, 204), 90)
    check("tắt waveform thì sạch hết pixel sóng", cyan_off, 0)
    check("và ảnh đổi thật chứ không phải ảnh cũ",
          int(np.abs(off_wave - on_wave).max()) > 20, True)

    apply_map(show_waveform=True, show_thumbnails=False)
    win._apply_settings()
    pump(10)
    off_thumb = shot(v_item, "thumb_off")
    seg_off = frame_ink(off_thumb)
    check("tắt thumbnail thì không còn pixel màu frame nào", seg_off, 0)
    check("và màu dự phòng vẫn được vẽ, không phải clip biến mất",
          ink_count(off_thumb, (32, 57, 114), 30) > 1000, True)
    apply_map(show_thumbnails=True)
    win._apply_settings()
    pump(10)
    check("counterfactual: bật lại là màu frame về",
          frame_ink(shot(v_item, "thumb_back")) > 1000, True)

    # theme cũng phải đổi pixel của chính timeline header
    theme_pixel = {}
    for mode in ("light", "dark"):
        apply_map(theme=mode)
        win._apply_settings()
        pump(10)
        path = os.path.join(OUT, "settings_theme_%s.png" % mode)
        panel.header.grab().save(path, "PNG")
        with Image.open(path) as image:
            theme_pixel[mode] = np.asarray(image.convert("RGB")).astype(int)
    check("theme light và dark cho hai ảnh header khác nhau",
          int(np.abs(theme_pixel["light"] - theme_pixel["dark"]).max()) > 40,
          True)
    bright = float(theme_pixel["light"].mean())
    dark = float(theme_pixel["dark"].mean())
    check("light sáng hơn dark trên cùng một widget", bright > dark, True)

    a_item.shutdown_extraction()
    v_item.shutdown_extraction()
    apply_map(theme="light", show_waveform=True, show_thumbnails=True)
    win._apply_settings()
    return {"on_wave": on_wave, "off_wave": off_wave,
            "on_thumb": on_thumb, "off_thumb": off_thumb,
            "cyan": (cyan_on, cyan_off), "seg": (seg_on, seg_off),
            "theme": theme_pixel}


# ── 6. Hộp thoại: không control nào nói dối ───────────────────

def test_dialog(win, panel):
    print("\n== 6. the dialog itself ==")
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                                   QLineEdit, QPushButton)
    from ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    dialog.settingsApplied.connect(win._apply_settings)
    dialog.show()
    pump(20)

    shots = {}
    for index, name in enumerate(("Chung", "Timeline")):
        dialog.tabs.setCurrentIndex(index)
        pump(8)
        path = os.path.join(OUT, "settings_dialog_tab%d.png" % index)
        dialog.tabs.widget(index).grab().save(path, "PNG")
        shots[name] = path
        with Image.open(path) as image:
            arr = np.asarray(image.convert("RGB"))
        check("tab %s có nội dung thật (nhiều màu, không phải khung trống)" % name,
              len(np.unique(arr.reshape(-1, 3), axis=0)) > 12, True)

    # Hai điều kiện phải đồng thời đúng: control đứng tên trong tab (không mồ
    # côi) VÀ đổi control làm merged_settings đổi thật. Detector cũ dựa vào
    # receivers("clicked()") — PySide6 luôn trả 0 cho tín hiệu overload nên nó
    # không chứng minh được gì; thay bằng đo đầu ra.
    orphans, dead = [], []
    interactive = (QComboBox, QCheckBox, QPushButton, QLineEdit)
    controls = []
    for tab in dialog.tabs_data:
        owned = set()
        for value in vars(tab).values():
            owned.add(id(value))
            if isinstance(value, dict):
                owned.update(id(inner) for inner in value.values())
        for widget in [w for cls in interactive for w in tab.findChildren(cls)]:
            if id(widget) not in owned:
                orphans.append("%s:%s" % (type(widget).__name__,
                                          widget.objectName() or widget.text()))
            else:
                controls.append((tab, widget))
    check("mọi control đều được tab giữ lại", orphans, [])

    general = dialog.tabs_data[0]
    timeline = dialog.tabs_data[1]
    for tab, widget in controls:
        before = dialog.merged_settings()
        if isinstance(widget, QComboBox):
            for row in range(widget.count()):
                if widget.itemText(row) != widget.currentText():
                    widget.setCurrentText(widget.itemText(row))
                    break
        elif isinstance(widget, QLineEdit):
            widget.setText(widget.text() + "_probe")
        elif isinstance(widget, QPushButton) and widget.isCheckable():
            widget.click()
        else:
            continue        # nút duyệt thư mục: đo riêng dưới kia
        changed = [k for k in sorted(EXPECTED_KEYS)
                   if dialog.merged_settings().get(k) != before.get(k)]
        if not changed:
            dead.append("%s(%s)" % (type(widget).__name__,
                                    widget.objectName() or "toggle"))
    check("mỗi control đều làm thay đổi giá trị sẽ ghi", dead, [])

    # Nút duyệt thư mục: click thật, không gọi thẳng handler.
    chosen = os.path.join(PROBE_PROJECTS, "browse_target")
    browse = general.dir_browse["project_dir"]
    general._browse = (
        lambda key, _p=chosen: general.dir_edits[key].setText(_p))
    browse.click()
    pump(4)
    check("nút duyệt thật sự ghi vào ô đường dẫn",
          dialog.merged_settings()["project_dir"], chosen)

    dialog.populate(settings.values())
    pump(6)
    check("control dựng lại từ đúng bộ giá trị đang có",
          sorted(dialog.merged_settings()), sorted(EXPECTED_KEYS))
    check("merged_settings phủ đúng bộ khóa",
          sorted(dialog.merged_settings()), sorted(EXPECTED_KEYS))

    # Đổi control -> bấm Lưu -> hành vi của cửa sổ đang chạy phải đổi theo.
    applied = []
    dialog.settingsApplied.connect(lambda v: applied.append(v["theme"]))
    general = dialog.tabs_data[0]
    timeline = dialog.tabs_data[1]
    general.theme_combo.setCurrentText("Tối")
    general.save_interval.setCurrentText("15")
    general.auto_save.setChecked(True)
    timeline.snap_threshold.setCurrentText("30")
    timeline.undo_steps.setCurrentText("50")
    timeline.show_waveform.click()
    dialog._on_save()
    pump(12)

    with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
        on_disk = json.load(handle)
    check("theme ghi xuống là dark", on_disk["theme"], "dark")
    check("ngưỡng snap ghi 30 px", on_disk["snap_threshold"], 30)
    check("undo ghi 50 bước", on_disk["undo_steps"], 50)
    check("interval ghi 15 phút", on_disk["auto_save_interval"], 15)
    check("waveform tắt", on_disk["show_waveform"], False)
    check("dialog báo cho cửa sổ đang chạy đúng một lần", applied, ["dark"])
    check("mode theme của app đổi thật", theme_manager.mode, "dark")
    check("SnapEngine nhận ngưỡng mới", panel.snap.threshold_px, 30)
    check("UndoStack nhận giới hạn mới", panel.undo_stack.max_history, 50)
    check("timer tự động lưu bật lại", win._auto_save_timer.isActive(), True)
    check("và interval là 15 phút", win._auto_save_timer.interval(), 900000)
    check("paint đọc theo cờ mới", settings.get("show_waveform"), False)

    # Nút Đặt lại phải thật sự trả về mặc định.
    reset = [child for child in dialog.findChildren(QPushButton)
             if "Đặt lại" in child.text()]
    check("có đúng một nút Đặt lại", len(reset), 1)
    dialog.show()
    pump(6)
    reset[0].click()
    pump(12)
    check("Đặt lại ghi DEFAULTS ra đĩa", settings.load(), dict(settings.DEFAULTS))
    check("control dựng lại đúng giá trị mặc định",
          sorted(dialog.merged_settings()), sorted(settings.DEFAULTS))
    check("waveform bật lại thành mặc định",
          dialog.tabs_data[1].show_waveform.isChecked(), True)
    check("auto_save mặc định bật", dialog.tabs_data[0].auto_save.isChecked(),
          True)
    check("tab mặc định là dark", dialog.tabs_data[0].theme_combo.currentText(),
          "Tối")

    dialog.deleteLater()
    pump(4)
    return shots


# ── 7. Ảnh bằng chứng ─────────────────────────────────────────

def draw_evidence(paint, dialog_shots):
    width = 1560
    height = 1240
    sheet = Image.new("RGB", (width, height), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 14),
              "SETTINGS GATE - every key measured on the running window",
              fill=(224, 224, 224))

    rects = {}

    def paste(img, x, y, title, max_w, max_h, tag):
        """Giữ nguyên tỉ lệ và CHỐT ô đã dán lại — gate đo đúng vùng này."""
        ratio = min(max_w / img.width, max_h / img.height, 1.0)
        if ratio < 1.0:
            img = img.resize((max(1, int(img.width * ratio)),
                              max(1, int(img.height * ratio))))
        sheet.paste(img, (x, y))
        draw.rectangle([x - 1, y - 1, x + img.width, y + img.height],
                       outline=(60, 62, 78))
        draw.text((x + 2, y - 15), title, fill=(180, 184, 200))
        rects[tag] = (x, y, img.width, img.height)
        return img.size

    def file_image(path):
        with Image.open(path) as image:
            return image.convert("RGB")

    def array_image(arr):
        return Image.fromarray(arr.astype(np.uint8))

    # Hàng 1: hai tab của hộp thoại, mỗi ô nửa bề ngang, cao tối đa 420.
    y = 44
    paste(file_image(dialog_shots["Chung"]), 20, y, "dialog: tab Chung",
          740, 420, "tab_general")
    paste(file_image(dialog_shots["Timeline"]), 800, y, "dialog: tab Timeline",
          740, 420, "tab_timeline")

    # Các hàng dưới: ảnh cắt từ đúng viewport đang chạy, 2 cột, không chồng nhau.
    y += 420 + 40
    rows = [
        ("wave", "waveform ON - %d cyan px" % paint["cyan"][0],
         "waveform OFF - %d cyan px" % paint["cyan"][1],
         array_image(paint["on_wave"]), array_image(paint["off_wave"]), 520),
        ("thumb", "thumbnails ON - %d frame px" % paint["seg"][0],
         "thumbnails OFF - %d frame px" % paint["seg"][1],
         array_image(paint["on_thumb"]), array_image(paint["off_thumb"]), 520),
        ("theme", "theme light - timeline header",
         "theme dark - timeline header",
         array_image(paint["theme"]["light"]),
         array_image(paint["theme"]["dark"]), 240),
    ]
    for tag, left_title, right_title, left_img, right_img, max_h in rows:
        _, h1 = paste(left_img, 20, y, left_title, 740, max_h, tag + "_L")
        _, h2 = paste(right_img, 800, y, right_title, 740, max_h, tag + "_R")
        y += max(h1, h2) + 40

    draw.text((20, height - 30),
              "undo on real AddClipCommand pushes - snap through "
              "scene.request_snap() - step through _step_frame() - restart "
              "gate ran a second python process",
              fill=(140, 144, 160))
    sheet.save(EVIDENCE)

    arr = np.asarray(Image.open(EVIDENCE).convert("RGB")).astype(int)
    check("ảnh bằng chứng ghi ra đĩa", os.path.exists(EVIDENCE), True)
    check("ảnh bằng chứng đủ lớn", os.path.getsize(EVIDENCE) > 20000, True)
    ink = int(np.abs(arr - np.array([16, 16, 20])).sum(axis=2).max())
    check("ảnh có nội dung vẽ", ink > 60, True)

    def cell(tag):
        x, yy, w, h = rects[tag]
        return arr[yy:yy + h, x:x + w]

    check("bằng chứng: không ô nào tràn ra ngoài ảnh",
          all(x + w <= width and yy + h <= height
              for x, yy, w, h in rects.values()), True)
    tags = sorted(rects)
    overlap = [("%s/%s" % (a, b)) for ia, a in enumerate(tags)
               for b in tags[ia + 1:]
               if _boxes_overlap(rects[a], rects[b])]
    check("bằng chứng: hai ô bất kỳ không chồng lên nhau", overlap, [])
    check("bằng chứng: mọi ô đều có nội dung thật",
          [t for t in tags if rects[t][2] < 40 or rects[t][3] < 8], [])

    check("hai ô waveform trên ảnh khác nhau",
          int(np.abs(cell("wave_L") - cell("wave_R")).max()) > 20, True)
    check("ô thumbnail ON trên ảnh vẫn đầy màu frame giải mã",
          frame_ink(cell("thumb_L")) > 1000, True)
    check("ô thumbnail OFF trên ảnh sạch màu frame",
          frame_ink(cell("thumb_R")), 0)
    check("hai ô header của hai theme trên ảnh khác nhau",
          int(np.abs(cell("theme_L") - cell("theme_R")).max()) > 40, True)
    return rects


def _boxes_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def main():
    if os.path.exists(SETTINGS_FILE):
        os.remove(SETTINGS_FILE)
    test_contract()
    test_restart()
    test_theme()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    settings.use(dict(WIN_SETTINGS))
    theme_manager.set_mode("dark")

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(20)
    panel = win.timeline_panel
    check("panel đọc cài đặt ngay khi vừa dựng, không chờ mở hộp thoại",
          [panel.snap.threshold_px, panel.undo_stack.max_history,
           panel.header.zoom_slider.minimum(), win._auto_save_timer.isActive()],
          [WIN_SETTINGS["snap_threshold"], WIN_SETTINGS["undo_steps"],
           WIN_SETTINGS["min_zoom_px_per_sec"], False])
    check("theme light đã áp lúc dựng window", theme_manager.mode, "light")

    settings.use(dict(WIN_SETTINGS))
    test_live_window(win, panel)
    settings.use(dict(WIN_SETTINGS))
    win._apply_settings()
    paint = test_paint(win, panel)
    dialog_shots = test_dialog(win, panel)
    draw_evidence(paint, dialog_shots)

    print("\n%d gates, %d FAIL" % (STATS["gates"], len(FAILS)))
    for line in FAILS:
        print("FAIL  " + line)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
