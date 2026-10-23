"""diagnostics.py

Kiểm tra bundle đóng gói: chạy MỌI mảnh mà app cần lúc chạy, ngay trong chính
file exe đã đóng gói.

Lý do tồn tại: exe GUI windowed không in ra stdout, nên "app mở được cửa sổ"
không chứng minh được là src.asr, styles/*.qss, font icon, cv2 hay PySide6
QtMultimedia có thật trong bundle hay không. Chạy:

    Clinging.exe --selftest <duong-dan-bao-cao>

Exit code 0 = bundle đủ, 1 = có mục thiếu (kèm chi tiết trong file báo cáo).
"""

import json
import math
import os
import subprocess
import sys
import time
import types


def _report_path(argv):
    for arg in argv[1:]:
        if not arg.startswith("-"):
            return os.path.abspath(arg)
    return os.path.join(os.environ.get("TEMP", os.getcwd()),
                        "clinging_selftest.json")


class Collector:
    def __init__(self):
        self.rows = []

    def check(self, name, fn):
        try:
            detail = fn()
            self.rows.append({"name": name, "ok": True, "detail": str(detail)})
        except Exception as exc:
            self.rows.append({"name": name, "ok": False,
                              "detail": "%s: %s" % (type(exc).__name__, exc)})

    @property
    def failed(self):
        return [row for row in self.rows if not row["ok"]]


def _styles_ok():
    from theme import BASE_DIR, STYLES_DIR, theme_manager
    missing = [f for f in ("dark.qss", "light.qss", "style.qss")
               if not os.path.isfile(os.path.join(STYLES_DIR, f))]
    if missing:
        raise RuntimeError("thieu %s trong %s" % (missing, STYLES_DIR))
    dark = theme_manager.stylesheet()
    theme_manager.toggle()
    light = theme_manager.stylesheet()
    theme_manager.toggle()
    if len(dark) < 500 or len(light) < 500 or dark == light:
        raise RuntimeError("stylesheet rong hoac giong nhau: %d/%d"
                           % (len(dark), len(light)))
    return "%d+%d byte tu %s" % (len(dark), len(light), BASE_DIR)


def _icon_ok():
    from widgets.common import app_icon, app_icon_path
    path = app_icon_path()
    if not os.path.isfile(str(path)):
        raise RuntimeError("khong co %s" % path)
    if app_icon().isNull():
        raise RuntimeError("QIcon null")
    return "%s (%d bytes)" % (path.name, os.path.getsize(str(path)))


def _font_icon_ok():
    """Font icon phai ve duoc pixel that, ngay trong bundle nay.

    isNull() khong du: mot QIcon khong null van co the in ra o trong, va ban exe
    thieu .ttf/charmap cung chi bieu hien bang cac o trang. Do bang chinh helper
    cua UI de khong co duong tat, va dem ALPHA chu khong dem mau (o trong cua
    pixmap ARGB32_Premultiplied co blue = 0 nen dem mau may man cung du qua).

    Tu khi `widgets/fontawesome.py` thay qtawesome, dong nay con la noi bat
    hai loi hoi quy khac: (1) ai do goi lai `import qtawesome` trong bundle, va
    (2) bo ve im lang tra ve o trang cho mot ten glyph khong ton tai — ca hai
    deu khong lam do pixel, nen phai kiem tra truc tiep.
    """
    import sys
    import widgets.common as common
    import widgets.fontawesome as fontawesome
    if common._qta() is not fontawesome:
        raise RuntimeError("widgets.common._qta() khong con tro bo ve glyph cuc bo")
    if "qtawesome" in sys.modules and getattr(sys, "frozen", False):
        raise RuntimeError("bundle dong goi van nap qtawesome (~0,6 s boot thua)")

    total = 0
    for name in ("fa6s.film", "fa6s.xmark", "fa6s.wand-magic-sparkles"):
        image = common.font_icon(name, "#40E0D0").pixmap(16, 16).toImage()
        pixels = image.width() * image.height()
        solid = sum(1 for y in range(image.height()) for x in range(image.width())
                    if (image.pixel(x, y) >> 24) & 0xFF)
        if solid < max(1, int(0.02 * pixels)):
            raise RuntimeError("%s chi ve %d/%d pixel" % (name, solid, pixels))
        total += solid

    # Ten la phai chore, khong duoc ve o trang: day la phan chung cua chinh
    # dong do — neu ai thay glyph_for bang `.get(name, "")` thi ba do o tren
    # van xanh, chi co phep thu nay do duoc.
    for bogus in ("fa6s.khong-ton-tai-xyz", "fa6b.paintbrush"):
        try:
            fontawesome.glyph_for(bogus)
        except ValueError:
            continue
        raise RuntimeError("ten glyph roi %r khong bi bo ve tu choi" % bogus)

    return "%d glyph, 3 font icon ve %d pixel khong trong (nguon %s)" % (
        len(fontawesome.names()), total, fontawesome._TTF)


def _asr_ok():
    import requests
    import src.asr as asr
    names = sorted(cls.__name__ for _label, cls in asr.CLOUD_ENGINES)
    if len(names) != 3:
        raise RuntimeError("CLOUD_ENGINES = %r" % (names,))
    return "%s + requests %s" % (",".join(names), requests.__version__)


def _media_libs_ok():
    import cv2
    import numpy
    import psutil
    import pydub  # noqa: F401
    return "cv2 %s, numpy %s, psutil %s" % (cv2.__version__,
                                            numpy.__version__,
                                            psutil.__version__)


def _qt_modules_ok():
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
    from PySide6.QtSvg import QSvgRenderer  # noqa: F401
    from PySide6.QtWidgets import QGraphicsScene  # noqa: F401
    return "QtMultimedia + QtSvg + Widgets"


def _transition_audio_ok():
    """Ke hoach afade phai co that trong bundle, khong phai chi trong source."""
    from core import audio_mix, transitions
    from core.timeline_model import TimelineModel, TrackType
    if len(transitions.TRANSITIONS) != 6:
        raise RuntimeError("TRANSITIONS = %d kieu" % len(transitions.TRANSITIONS))
    model = TimelineModel()
    track = model.add_track(TrackType.VIDEO)
    a = model.add_clip(track.track_id, "a.mp4", "video", 0.0, 3.0, "a")
    b = model.add_clip(track.track_id, "b.mp4", "video", 0.0, 3.0, "b")
    if not model.set_transition(b.clip_id, "Cross Dissolve", 1.0):
        raise RuntimeError("khong gan duoc Cross Dissolve")
    graph = audio_mix.build_filter_complex(model, [a, b], model.duration)
    if graph.count("afade=") != 2 or "curve=hsin" not in graph:
        raise RuntimeError("chuoi filter khong co afade: %s" % graph[:120])
    return "6 kieu, 2 afade, overlap %.1f-%.1f" % (b.start_time, a.end_time)


def _clip_audio_ok():
    """Buoc nut am thanh cua tung clip phai di den tan chuoi filter cua bundle.

    Chi kiem tra model thi khong chung duoc dieu gi: nguoi dung mo ban cai dat,
    keo thanh Am luong roi xuat file, va file ay phai khac.
    """
    from core import audio_mix
    from core.timeline_model import TimelineModel, TrackType
    model = TimelineModel()
    track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(track.track_id, "a.wav", "audio", 0.0, 4.0, "a")
    applied = model.set_clip_audio(clip.clip_id, volume=0.5, speed=2.0,
                                   fade_in=1.0, fade_out=0.5)
    if (not isinstance(applied, dict) or applied.get("speed") != 2.0 or
            round(clip.duration, 3) != 2.0):
        raise RuntimeError("knob sai: %r duration=%r" % (applied, clip.duration))
    graph = audio_mix.build_filter_complex(model, [clip], model.duration)
    for token in ("atempo=2.000000,", "afade=t=in:", "afade=t=out:",
                  "volume=0.500000,"):
        if token not in graph:
            raise RuntimeError("thieu %s trong %s" % (token, graph[:160]))

    # Tat tieng phai di den cung mot chuoi filter: co volume=0 ma van giu
    # volume=0.5 trong model (bat lai khong mất con số), va clip khong duoc
    # con duoc ke vao danh sach nguon tieng cua exporter.
    from core import transitions
    clip.audio_muted = True
    muted_graph = audio_mix.build_filter_complex(model, [clip], model.duration)
    if ("volume=0.000000," not in muted_graph or
            "volume=0.500000," in muted_graph):
        raise RuntimeError("tat tieng khong vao chuoi ffmpeg: %s"
                           % muted_graph[:160])
    if transitions.clip_volume(clip) != 0.0 or clip.volume != 0.5:
        raise RuntimeError("tat tieng an mop volume: %r" % clip.volume)
    clip.audio_muted = False
    if transitions.clip_volume(clip) != 0.5:
        raise RuntimeError("bat lai tieng khong tra volume cu")
    return "volume + speed + fade + tat tieng den duoc chuoi ffmpeg"


def _settings_ok():
    """Cai dat phai that trong bundle — 14 khoa, moi khoa mot hook chay duoc.

    Mot bundle cu (con dict ~60 khoa, chua co core/settings.py) phai FAIL o
    day chu khong PASS roi im lang dung gia tri mac dinh.
    """
    import tempfile
    from core import settings

    if len(settings.DEFAULTS) != 14:
        raise RuntimeError("DEFAULTS = %d khoa" % len(settings.DEFAULTS))

    # Hop thoai khong duoc de khoa ma chang tab nao giu, cung khong duoc hai
    # tab cung ghi mot khoa (tab dung sau an tab dung truoc).
    from ui.settings_dialog import SettingsDialog
    claimed = []
    for tab_class, _name in SettingsDialog.TAB_CLASSES:
        claimed.extend(tab_class.KEYS)
    if sorted(claimed) != sorted(settings.DEFAULTS):
        raise RuntimeError("dialog khong phu kin 14 khoa: %s" % sorted(claimed))
    if len(set(claimed)) != len(claimed):
        raise RuntimeError("hai tab cung ghi de mot khoa")

    # Round-trip xuong dia that, bang file tam de khong cham file nguoi dung.
    probe = {"theme": "light", "snap_threshold": 999, "undo_steps": "7",
             "show_waveform": "false", "bogus": 1}
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "settings.json")
        saved = settings.save(probe, path)
        again = settings.load(path)
        if again != saved:
            raise RuntimeError("round-trip doi gia tri: %s != %s" % (again, saved))
    if saved["snap_threshold"] != settings.INT_RANGES["snap_threshold"][1]:
        raise RuntimeError("ngoai khoang phai kep, khong phai loai")
    if saved["undo_steps"] != 10 or saved["show_waveform"] is not False:
        raise RuntimeError("kieu du lieu bi ghi nguyen: %s" % saved)
    if "bogus" in saved:
        raise RuntimeError("khoa la len duoc vao file")

    # Bay gio moi hook phai chay that tren object that cua bundle.
    from core.commands import AddClipCommand, UndoStack
    from core.snap_engine import SnapEngine
    from core.time_mapper import TimePixelMapper
    from core.timeline_model import TimelineModel, TrackType
    from theme import ThemeManager

    mapper = TimePixelMapper(px_per_sec=48.0)
    mapper.set_min_zoom(20)
    mapper.set_zoom(1.0)
    if mapper.px_per_sec < 19.9:
        raise RuntimeError("min_zoom khong chan duoc zoom")

    model = TimelineModel()
    track = model.add_track(TrackType.VIDEO)
    model.add_clip(track.track_id, "a.mp4", "video", 0.0, 4.0, "a")
    model.playhead = 100.0
    engine = SnapEngine(mapper)
    engine.enabled, engine.threshold_px = True, 20
    engine.snap_to_playhead = engine.snap_to_grid = False
    engine.snap_to_clip_edges = True
    if engine.find_snap(4.2, model) is None:
        raise RuntimeError("mep clip khong hut duoc")
    engine.snap_to_clip_edges = False
    if engine.find_snap(4.2, model) is not None:
        raise RuntimeError("co snap_to_clip_edges khong co tac dung")

    stack = UndoStack()
    for index in range(20):
        stack.push(AddClipCommand(model, track.track_id, "b.mp4", "video",
                                  40.0 + index, 2.0, "x%02d" % index))
    if stack.undo_count != 20:
        raise RuntimeError("model khong giu du 20 lenh: %d" % stack.undo_count)
    # Ha gioi han PHAI cat ngay, khong cho den khi co lenh moi.
    stack.set_max_history(10)
    if stack.undo_count != 10 or not stack.can_undo:
        raise RuntimeError("undo_steps khong cat: %d" % stack.undo_count)
    # undo() co y khong tra gia tri, nen do bang dem cua chinh no.
    stack.undo()
    if stack.undo_count != 9 or not stack.can_redo:
        raise RuntimeError("undo khong chay sau khi cat lich su")

    manager = ThemeManager()
    seen = []
    manager.themeChanged.connect(seen.append)
    manager.set_mode(saved["theme"])
    if seen != ["light"] or manager.set_mode("light"):
        raise RuntimeError("set_mode phat tin hieu sai")

    settings.reload()
    return "14 khoa, %s, snap+zoom+undo+theme chay that" % saved["theme"]


def _ui_graph_ok():
    from ui.main_controller import MainController  # noqa: F401
    from core.frame_composer import FrameComposer  # noqa: F401
    from ui.export_dialog import RenderWorker  # noqa: F401
    from ui.thumbnail_dialog import ThumbnailDialog  # noqa: F401
    from ui.keyframe_graph_dialog import KeyframeGraphDialog  # noqa: F401
    return ("MainController + FrameComposer + RenderWorker + ThumbnailDialog"
            " + KeyframeGraphDialog")


def _keyframe_graph_ok():
    """Do thi duong cong keyframe trong ban chay nay: duong ve, phep chieu,
    lenh undo va diem vao — tat ca do that, khong phai nhin file nguon.

    Mot bundle thieu ui.keyframe_graph_dialog van mo duoc app va chi lo khi
    nguoi dung bam vao clip co keyframe, nen phai kiem ca import lan chu.
    """
    from core import keyframe_graph as kg
    from core.commands import (AddKeyframeCommand, EditKeyframeCommand,
                               RemoveKeyframeCommand, UndoStack)
    from core.keyframe_manager import (frame_ease, frame_time, frame_value,
                                       interpolate_keyframes)
    from core.timeline_model import TimelineModel, track_type_for_media

    model = TimelineModel()
    track = model.add_track(track_type_for_media("text"), "Graph")
    clip = model.add_clip(track.track_id, "", "text", 0.0, 2.0, "g")
    clip.transform.x = -400.0
    clip.add_keyframe("x", 0.0, -400.0, "ease_in_out")
    clip.add_keyframe("x", 2.0, 400.0, "linear")

    frames = kg.frames_of(clip, "x")
    default = kg.default_value(clip, "x")
    samples = kg.sample_curve(frames, "x", default, 0.0, clip.duration,
                              samples=41)
    if len(samples) != 41:
        raise RuntimeError("sample_curve tra %d mau" % len(samples))
    # Diem cuoi phai nam o CUOI khoang thoi gian: ghi nham thanh t0 thi mau
    # van "khop" interpolate_keyframes (no tu noi theo chinh no) ma duong
    # tren man hinh keo mot net nguoc qua ca lane.
    times = [t for t, _ in samples]
    if times[-1] != clip.duration or times[0] != 0.0:
        raise RuntimeError("mau dau/cuoi lech khoang thoi gian: %r" %
                           ((times[0], times[-1]),))
    if any(b <= a for a, b in zip(times, times[1:])):
        raise RuntimeError("mau duong cong khong tang dan")
    for time, value in samples:
        if abs(value - interpolate_keyframes(frames, time, default)) > 1e-9:
            raise RuntimeError("duong tren do thi khong phai duong cua model")

    for time in (0.0, 0.37, 1.0, 2.0):
        x = kg.time_to_x(time, 0.0, clip.duration, 128.0, 800.0)
        back = kg.x_to_time(x, 0.0, clip.duration, 128.0, 800.0)
        if abs(back - time) > 1e-9:
            raise RuntimeError("phep chieu thoi gian mat nghich dao")
    shown = kg.display_value("opacity", 0.4)
    if (shown, kg.raw_value("opacity", shown)) != (40.0, 0.4):
        raise RuntimeError("opacity khong quy duoc % ve model")
    flat_lo, flat_hi = kg.value_domain([(0.0, 0.5, "linear")], "opacity", 0.5)
    if not flat_hi > flat_lo:
        raise RuntimeError("duong nam ngang bi ep ve 0 chieu cao")
    if kg.format_value("x", -0.4) != "0px":
        raise RuntimeError("truc tung in ra so am khong duong (%r)"
                           % kg.format_value("x", -0.4))
    # Lane 48 px la chieu cao THAT khi mo du 6 property, khong chua noi 5 dong
    # chu 16 px: nhan phai gian cach, neu khong cot so de len nhau thanh mot bo
    # so khong doc duoc (khong crash, chi la in ra sai).
    from ui.keyframe_graph_dialog import label_divisions
    if [label_divisions(h, 16.0) for h in (48.3, 70.0, 90.0, 380.0)] != \
            [1, 2, 2, 4]:
        raise RuntimeError("nhan truc tung khong gian theo chieu cao lane")

    stack = UndoStack()
    stack.push(EditKeyframeCommand(model, clip.clip_id, "x", 2.0, 1.5, 90.0))
    moved = model.get_clip(clip.clip_id).keyframes["x"]
    if (round(frame_time(moved[1]), 3), round(frame_value(moved[1]), 3),
            frame_ease(moved[1])) != (1.5, 90.0, "linear"):
        raise RuntimeError("lenh keo moc sai: %r" % (moved[1],))
    stack.undo()
    if round(frame_time(model.get_clip(clip.clip_id).keyframes["x"][1]), 3) != 2.0:
        raise RuntimeError("undo keo moc khong tra lai")
    stack.redo()
    if round(frame_value(model.get_clip(clip.clip_id).keyframes["x"][1]), 3) != 90.0:
        raise RuntimeError("redo keo moc khong dat lai")

    stack.push(AddKeyframeCommand(model, clip.clip_id, "x", 0.75, 10.0,
                                  "ease_in"))
    if len(model.get_clip(clip.clip_id).keyframes["x"]) != 3:
        raise RuntimeError("lenh them moc khong chen")
    stack.undo()
    if len(model.get_clip(clip.clip_id).keyframes["x"]) != 2:
        raise RuntimeError("undo them moc khong xoa")
    stack.push(RemoveKeyframeCommand(model, clip.clip_id, "x", 0.0))
    left = model.get_clip(clip.clip_id).keyframes["x"]
    if len(left) != 1 or round(frame_time(left[0]), 3) != 1.5:
        raise RuntimeError("lenh xoa moc sai: %r" % (left,))
    stack.undo()
    if len(model.get_clip(clip.clip_id).keyframes["x"]) != 2:
        raise RuntimeError("undo xoa moc khong tra lai moc")

    from ui.graphics.timeline_scene import TimelineScene
    from ui.keyframe_graph_dialog import KeyframeGraphDialog  # noqa: F401
    from ui.main_window import MainWindow
    from ui.timeline_panel import TimelinePanel
    missing = [name for name, owner in (
        ("graph_requested", TimelineScene),
        ("keyframeGraphRequested", TimelinePanel),
        ("_open_keyframe_graph", MainWindow)) if not hasattr(owner, name)]
    if missing:
        raise RuntimeError("diem vao do thi bi thieu: %s" % ", ".join(missing))
    return ("41 mau khop interpolate_keyframes, 3 lenh undo/redo, "
            "3 diem vao, nhan truc tung gian theo lane")


def _project_launch_ok():
    """Duong mo du an tu file phai co trong bundle nay, do tren chuoi argv that.

    ``main.py`` duoc dong goi thanh ``__main__`` nen khong import lai duoc:
    parser nam trong ``core.project_storage`` va chinh app dung no. Mot bundle
    thieu ``open_project_path`` van mo duoc Home — nguoi dung nghi app hong,
    trong khi thuc chat la khong co loi vao.
    """
    import tempfile
    from core.project_storage import project_arg_from_argv
    from ui.main_controller import MainController

    for name in ("open_project_path", "_on_open_project"):
        if not hasattr(MainController, name):
            raise RuntimeError("thieu %s trong MainController" % name)

    here = os.path.abspath(__file__)
    if project_arg_from_argv(["Clinging.exe"]) is not None:
        raise RuntimeError("argv khong co du an ma parser mo ra")
    if project_arg_from_argv(["Clinging.exe", "--project-report", here]) is not None:
        raise RuntimeError("--project-report bi hieu nham la file mo")
    gone = os.path.join(tempfile.gettempdir(), "clinging_selftest_vang.clinq")
    if os.path.exists(gone):
        os.remove(gone)
    if project_arg_from_argv(["Clinging.exe", gone]) is not None:
        raise RuntimeError("file khong ton tai phai tra None, khong mo")
    if project_arg_from_argv(["Clinging.exe", here]) is not None:
        raise RuntimeError("duong dan khong phai .clinq phai bi tu choi")
    real = os.path.join(tempfile.gettempdir(), "clinging_selftest_mo.clinq")
    other = os.path.join(tempfile.gettempdir(), "clinging_selftest_khac.clinq")
    for path in (real, other):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{}")
    try:
        if project_arg_from_argv(["Clinging.exe", real]) != real:
            raise RuntimeError("Explorer dat ten file vao argv ma khong mo duoc")
        # ``--project`` phai thang: vong lap roi cuoi co the Trung mot file
        # .clinq khac trong thu muc hien hanh, va mo sai du an con te hon
        # mo khong duoc.
        if project_arg_from_argv(
                ["Clinging.exe", real, "--project", other]) != other:
            raise RuntimeError("--project khong co quyen uu tien")
    finally:
        for path in (real, other):
            os.remove(path)
    return ("parser doi duoc .clinq that/gia/khong co, --project thang, "
            "2 diem vao MainController con nguyen")


def _clip_teardown_ok():
    """Dong cua so: khong duoc de luong giai ma clip ton tai qua `close()`.

    ClipItem tu mo `QThread` + `MediaExtractionWorker` ngay trong ham construct
    (dong 96 cua no) va worker do block trong `cv2.VideoCapture.read()`. Truoc
    23/10/2026 khong co `closeEvent` o bat cu day UI nao: interpreter bat tay
    khi thread van chay, Qt tra ve 0xC0000409 khong kem traceback — lan do tren
    `--project-report` mo du an 4K cua nguoi dung ghi xong JSON
    `mo_duoc=True/o_editor=True` roi chet o ma do 3/3 lan tren ban cai 1.0.6.

    Do ba dieu, deu la dem duong, khong do thoi gian:
      * luc mo: MOI ClipItem co `_extractor_thread` khong None (khong thi phep
        thu xanh vi fixture rong);
      * luc dong: khong clip nao con `_extractor_thread` — tuc duong dong THAT
        di qua `shutdown_extraction()`;
      * sau dong: 0 `QThread.isRunning()` trong so thread da bat luc mo.
    `isRunning()` ma bi C++ xoa thi RuntimeError tinh la da chet: do la con
    duong `finished -> deleteLater` cua chinh `shutdown_extraction`.
    """
    import shutil
    import tempfile
    from PySide6.QtWidgets import QApplication
    from core import media_cache
    from core.project_storage import ProjectManager

    app = QApplication.instance() or QApplication([])
    work = tempfile.mkdtemp(prefix="clinging_teardown_")
    original_root = media_cache.cache_root
    media_cache.cache_root = lambda: os.path.join(work, "cache")
    original_project = ProjectManager().project_path
    fails = []
    try:
        if not hasattr(media_cache, "image_key"):
            raise RuntimeError("media_cache khong co image_key — dong nay gia")
        fixture, _data = _project_fixture()
        from ui.main_controller import MainController
        controller = MainController()
        controller.show()
        for _ in range(6):
            app.processEvents()
        if not controller.open_project_path(fixture):
            raise RuntimeError("mo fixture .clinq that bai")
        for _ in range(6):
            app.processEvents()
        scene = controller.editor_page.timeline_panel.scene
        if not hasattr(scene, "shutdown_clip_workers"):
            raise RuntimeError("TimelineScene thieu shutdown_clip_workers")
        items = list(scene._clip_items.values())
        if not items:
            raise RuntimeError("fixture mo ra 0 ClipItem — phep thu rong")
        threads = [getattr(item, "_extractor_thread", None) for item in items]
        started = len([t for t in threads if t is not None])
        if started != len(items):
            fails.append("luc mo: %d/%d clip khong co luong trich xuat"
                         % (started, len(items)))

        controller.close()
        for _ in range(4):
            app.processEvents()

        left = [clip_id for clip_id, item in scene._clip_items.items()
                if getattr(item, "_extractor_thread", None) is not None]
        if left:
            fails.append("dong cua so: %d/%d clip van con luong (%s)"
                         % (len(left), len(items), ",".join(sorted(left))))
        alive = 0
        for thread in threads:
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    alive += 1
            except RuntimeError:
                pass
        if alive:
            fails.append("dong cua so: %d QThread van isRunning" % alive)
    finally:
        ProjectManager().project_path = original_project
        media_cache.cache_root = original_root
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        raise RuntimeError("; ".join(fails))
    return "moi clip mo ra luong, close() dung het luong tru khi thoat"


def _save_atomic_ok():
    """Mot dong --selftest: lan ghi du an hong khong duoc pha ban dang co.

    `save_project_to_file` tung mo `open(path, "w")`, va phep mo cat ngat file
    that ngay tuc thi: moi loi sau do (payload serialize hong, dia day, process
    bi giet giua chung) de lai mot file ma `json.load` bo duoc nua. Autosay goi
    lai ham nay theo chu ky nen loi hiem thanh mat bai. Cua nay do bon bat
    buoc: ghi hong thi file van la ban cu tron ven, ban cu duoc quay vao
    RECOVERY_DIR va chi giu RECOVERY_KEEP ban, khong de lai `.tmp`, va ten file
    tuong doi (khong co thu muc) van luu duoc.
    """
    import shutil
    import tempfile
    from PySide6.QtGui import QColor, QImage
    from core import project_storage
    from core.timeline_model import TimelineModel, TrackType

    folder = os.path.join(tempfile.gettempdir(), "clinging_save_report")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    seed = os.path.join(folder, "nen.png")
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor("#202020"))
    if not img.save(seed):
        raise RuntimeError("khong tao duoc anh nen trong %s" % folder)

    real_recovery = project_storage.RECOVERY_DIR
    project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")
    path = os.path.join(folder, "gate.clinq")

    def build(marker):
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, seed, "image", 0.0, 2.0,
                              name="m" + marker)
        if clip is None:
            raise RuntimeError("add_clip tra None (track/media khong khop)")
        return model

    def read_bytes(target):
        with open(target, "rb") as handle:
            return handle.read()

    def markers_of_copies():
        if not os.path.isdir(project_storage.RECOVERY_DIR):
            return []
        out = []
        for name in sorted(os.listdir(project_storage.RECOVERY_DIR)):
            data = project_storage.load_project_from_file(
                os.path.join(project_storage.RECOVERY_DIR, name))
            out.append(data["timeline"]["tracks"][0]["clips"][0]["name"])
        return out

    try:
        if not project_storage.save_project_to_file(build("1"), path):
            raise RuntimeError("lan ghi dau tien tra False")
        first_bytes = read_bytes(path)
        if len(json.loads(first_bytes)) != 3:
            raise RuntimeError("file dau khong phai JSON ba khoa")
        if os.path.isdir(project_storage.RECOVERY_DIR) and \
                os.listdir(project_storage.RECOVERY_DIR):
            raise RuntimeError("lan ghi dau khong duoc tao ban recovery")

        hong = project_storage.save_project_to_file(
            build("2"), path, {"resolution": QColor(1, 2, 3)})
        if hong:
            raise RuntimeError("payload khong serialize duoc ma save tra True")
        if read_bytes(path) != first_bytes:
            raise RuntimeError("lan ghi hong da cham vao file that")
        if not project_storage.load_project_from_file(path):
            raise RuntimeError("file sau lan ghi hong khong doc lai duoc")

        # Duong LOI cua hai ham nay cung phai song: ham in bang chu co dau tung
        # raise UnicodeEncodeError tren console cp1252, loi doc bien thanh crash.
        # Do bang cach doc mot file JSON bi cat doi.
        dochi = os.path.join(folder, "cat_doi.clinq")
        with open(dochi, "w", encoding="utf-8") as handle:
            handle.write('{"project_meta": ')
        if project_storage.load_project_from_file(dochi) is not None:
            raise RuntimeError("file JSON cat doi phai tra None, khong mo")

        for marker in ("2", "3", "4", "5", "6", "7", "8"):
            if not project_storage.save_project_to_file(build(marker), path):
                raise RuntimeError("save %s tra False" % marker)
        # 7 lan de len quay ra 7 ban cu [m1..m7], prune con 5 ban gan nhat.
        kept = markers_of_copies()
        if kept != ["m3", "m4", "m5", "m6", "m7"]:
            raise RuntimeError("recovery khong quay/prune dung: %s" % kept)

        soc = [n for n in os.listdir(folder) if n.endswith(".tmp")]
        if soc:
            raise RuntimeError("con %d file .tmp sot lai: %s" % (len(soc), soc))

        cwd = os.getcwd()
        try:
            os.chdir(folder)
            if not project_storage.save_project_to_file(build("9"), "tuongdoi.clinq"):
                raise RuntimeError("ten file tuong doi khong luu duoc")
            if not os.path.isfile(os.path.join(folder, "tuongdoi.clinq")):
                raise RuntimeError("luu tuong doi ra ngoai thu muc")
        finally:
            os.chdir(cwd)
    finally:
        project_storage.RECOVERY_DIR = real_recovery
    return ("lan ghi hong gi duoc %d byte cu, 7 lan de len con %d ban recovery "
            "dung chu [m3..m7], 0 file .tmp, duong dan tuong doi luu duoc"
            % (len(first_bytes), project_storage.RECOVERY_KEEP))


# Cach cu dinh vi file media lac cho: di bo thu muc hien hanh theo ten. Phai
# giu lai mot ban dich tai luc chay de dong gate duoi day chung minh no do
# duoc cach nay, khong chi thay moi la xanh.
_WALK_CWD_RENDER = (
    "def f(source_path):\n"
    "    import os\n"
    "    for root, dirs, files in os.walk('.'):\n"
    "        if os.path.basename(source_path) in files:\n"
    "            return os.path.join(root, os.path.basename(source_path))\n"
    "    return None\n"
)


def _media_locator_ok():
    """File media bi don di cho: preview va export phai cung MOT duong dan.

    Preview tung tim lai file lac cho bang `os.walk(".")` o nam cho khac nhau
    trong `ui/` va `core/`, con export (`core/frame_composer.py`) chi tin
    `clip.source_path`. Thu muc hien hanh cua exe da cai khi mo tu Explorer la
    `C:\\Windows\\System32`, nen phep di do thanh cong that tuy theo noi nguoi
    dung bam mo: co clip sang tren timeline ma xuat ra lai trang lang. Tu khi
    co `core/media_locator.py`, viec dinh vi chi dien ra MOT lan luc mo du an
    (`restore_model_from_clinq` cho file .clinq, `restore_model` cho ban tam
    autosave), pham vi la thu muc cua chinh file cong thu muc chua .clinq, co
    chan kinh do (MAX_DEPTH/MAX_ENTRIES) de khong di bo ca o.
    """
    import shutil
    import tempfile
    from PySide6.QtGui import QColor, QImage
    from core import media_locator, project_storage
    from core.canvas_utils import get_media_dimensions
    from core.frame_composer import FrameComposer
    from core.media_locator import locate
    from core.timeline_model import ClipModel, TimelineModel, TrackType
    from ui.graphics.clip_item import MediaExtractionWorker
    from ui.graphics_canvas_item import CanvasClipItem
    from ui.main_window import MainWindow
    from ui.timeline_panel import TimelinePanel

    def walks_cwd(fn):
        return "walk" in fn.__code__.co_names

    def uses_locator(fn):
        code = fn.__code__.co_names
        return "locate" in code or "resolve_model" in code

    # Tu thu detector: cach cu phai bi bat, neu khong dong gate chi la do
    # "khong con tim thay" va van xanh khi loi quay lai.
    rival = {}
    exec(_WALK_CWD_RENDER, rival)
    if not walks_cwd(rival["f"]) or uses_locator(rival["f"]):
        raise RuntimeError("detector khong bat duoc os.walk('.') -> gate vo nghia")

    seams = [
        ("canvas_utils.get_media_dimensions", get_media_dimensions),
        ("MainWindow._detect_media_aspect_ratio",
         MainWindow._detect_media_aspect_ratio),
        ("TimelinePanel._get_media_duration", TimelinePanel._get_media_duration),
        ("CanvasClipItem._load_media_pixmap", CanvasClipItem._load_media_pixmap),
        ("CanvasClipItem._extract_video_frame", CanvasClipItem._extract_video_frame),
        ("MediaExtractionWorker.run", MediaExtractionWorker.run),
        ("project_storage.restore_model_from_clinq",
         project_storage.restore_model_from_clinq),
        ("project_storage.restore_model", project_storage.restore_model),
    ]
    bad = [name for name, fn in seams if walks_cwd(fn) or not uses_locator(fn)]
    if bad:
        raise RuntimeError("chieu dinh vi khong di qua core.media_locator: %s"
                           % ", ".join(bad))

    GREEN = "#00ff00"
    RED = "#ff0000"
    folder = os.path.join(tempfile.gettempdir(), "clinging_locator_report")
    shutil.rmtree(folder, ignore_errors=True)
    proj = os.path.join(folder, "proj")
    for rel in ("media/sub", "a1/a2/a3/a4", "b1/b2/b3/b4/b5"):
        os.makedirs(os.path.join(proj, *rel.split("/")), exist_ok=True)

    def solid(color, *parts):
        path = os.path.join(*parts)
        img = QImage(8, 8, QImage.Format.Format_RGB32)
        img.fill(QColor(color))
        if not img.save(path):
            raise RuntimeError("khong tao duoc %s" % path)
        return path

    moved = solid(GREEN, proj, "media", "clip.png")
    deep4 = solid(GREEN, proj, "a1", "a2", "a3", "a4", "chan.png")
    solid(GREEN, proj, "b1", "b2", "b3", "b4", "b5", "vuot.png")
    # Bo cam cung ten trong thu muc hien hanh: cach cu lay no, cach moi phai
    # bo qua. Mau DO khac mau XANH cua du an nen khung ve cung phan biet duoc.
    decoy = solid(RED, folder, "clip.png")

    gone = os.path.join(proj, "khong_ton_tai.png")
    cwd = os.getcwd()
    try:
        os.chdir(folder)
        if locate(moved) != moved:
            raise RuntimeError("file con nguyen cho bi dao vi")
        if locate(decoy, (proj,)) != decoy:
            raise RuntimeError("locate khong tra dung file dang con")
        found = locate(os.path.join(proj, "clip.png"), (proj,))
        if found != moved:
            raise RuntimeError("don file mot cap ma khong tim lai duoc: %s" % found)
        if locate(os.path.join(proj, "chan.png"), (proj,)) != deep4:
            raise RuntimeError("file trong gioi han sau %d cap ma khong tim thay"
                               % media_locator.MAX_DEPTH)
        if locate(os.path.join(proj, "vuot.png"), (proj,)) is not None:
            raise RuntimeError("chan kinh sau bi nong: file o cap %d van duoc tim"
                               % (media_locator.MAX_DEPTH + 1))
        if locate(gone, (proj,)) is not None:
            raise RuntimeError("file khong co that ma locate tra duong dan")
        if locate("", (proj,)) is not None:
            raise RuntimeError("duong dan rong phai tra None")

        # Duong that cua nguoi dung: luu .clinq, don file, mo lai.
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, moved, "image", 0.0, 2.0,
                              name="lac-cho")
        if clip is None:
            raise RuntimeError("add_clip tra None (track/media khong khop)")
        clinq = os.path.join(proj, "gate.clinq")
        if not project_storage.save_project_to_file(model, clinq):
            raise RuntimeError("khong luu duoc gate.clinq")
        relocated = os.path.join(proj, "media", "sub", "clip.png")
        os.replace(moved, relocated)
        if os.path.exists(moved):
            raise RuntimeError("don file that khong dien ra")
        data = project_storage.load_project_from_file(clinq)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        fresh = TimelineModel()
        project_storage.restore_model_from_clinq(fresh, data, media_roots=[proj])
        restored = [c for t in fresh.tracks for c in t.clips]
        if len(restored) != 1:
            raise RuntimeError("mo du an ra %d clip, mong 1" % len(restored))
        got = restored[0].source_path
        if got != relocated:
            raise RuntimeError("mo du an khong dinh vi lai file lac cho: %s" % got)
        if not os.path.exists(got):
            raise RuntimeError("duong dan sau restore khong ton tai: %s" % got)

        # Xuat ra: FrameComposer chi tin source_path, nen no phai ve duoc file
        # ma restore vua tim thay — mau xanh cua clip, khong phai den trung nom.
        composer = FrameComposer(fresh, 1920, 1080)
        try:
            frame = composer.render_frame(0.5)
        finally:
            composer.close()
        centre = QColor(frame.pixel(frame.width() // 2, frame.height() // 2))
        if centre.red() > 120 or centre.green() < 150:
            raise RuntimeError("xuat ra khong ve file da dinh vi: mau tam %s"
                               % centre.name())

        # Preview dung chung duong dan nay de do kho media.
        if get_media_dimensions(got, "image") != (8.0, 8.0):
            raise RuntimeError("get_media_dimensions doc sai file da dinh vi")

        # resolve_model: clip tim duoc thi ghi lai duong dan, clip vang mat
        # thi GIU NGUYEN duong dan cu va nam trong `missing` de caller bao.
        mixed = TimelineModel()
        mixed.project_ratio = "16:9"
        lane = mixed.add_track(TrackType.IMAGE)
        for path, dur in ((os.path.join(proj, "chan.png"), 1.0),
                          (gone, 1.0), (relocated, 1.0)):
            lane.clips.append(ClipModel(clip_id="c" + path[-8:-4],
                                        start_time=0.0, duration=dur,
                                        source_path=path, media_type="image",
                                        name=os.path.basename(path),
                                        track_id=lane.track_id))
        resolved, missing = media_locator.resolve_model(mixed, (proj,))
        if len(resolved) != 1 or len(missing) != 1:
            raise RuntimeError("resolve_model dem sai: resolved=%d missing=%d"
                               % (len(resolved), len(missing)))
        if lane.clips[0].source_path != deep4:
            raise RuntimeError("resolve_model khong ghi lai duong dan: %s"
                               % lane.clips[0].source_path)
        if lane.clips[1].source_path != gone:
            raise RuntimeError("file vang mat bi doi duong dan khi khong tim thay")
        if missing != [gone]:
            raise RuntimeError("missing khong dung duong dan cu: %s" % missing)
    finally:
        os.chdir(cwd)
    return ("8 seam di qua core.media_locator, detector bat duoc cach cu, "
            "don 1 cap + sau %d cap tim thay, sau %d cap bo, %d cam trong cwd "
            "khong bi dung, .clinq mo lai ra file moi va FrameComposer ve mau %s"
            % (media_locator.MAX_DEPTH, media_locator.MAX_DEPTH + 1, 1, GREEN))


def _clipboard_copy_paste_ok():
    """Nhom B: Ctrl+C / Ctrl+V phai snapshot dung, dan ra id moi giu nguyen
    font/hinh hoc, giu bo cuc tuong doi khi dan nhieu clip, va la dung MOT buoc
    undo per lenh dan.

    Cam fixture nguoi dung: moi clip dung tai cho bang add_clip('') tren track
    TEXT cua mot TimelineModel moi trong thu muc tam.
    """
    import os
    import shutil
    import tempfile

    from core import commands as core_commands
    from core.clip_clipboard import ClipClipboard
    from core.timeline_model import TimelineModel, TrackType
    from ui.main_window import MainWindow
    from ui.timeline_panel import TimelinePanel

    # (1) Seam cau truc: panel va lenh phai di qua helper that, khong dan thu cong.
    # Lambda cua bindings nam ma hoa trong co_consts cua _install_editor_shortcuts,
    # nen ten thuoc tinh (`_on_copy_selected`) roi vao co_names cua chinh no, khong
    # phai cua ham bao. Vi vay phai duyet co_consts de quy thi moi noi duoc ca hai.
    def walk_names(fn):
        seen = set()
        stack = [fn.__code__]
        while stack:
            code = stack.pop()
            seen.update(code.co_names)
            for const in code.co_consts:
                if hasattr(const, "co_names") and const not in seen:
                    stack.append(const)
        return seen

    seams = (
        ("TimelinePanel._on_copy_selected",
         TimelinePanel._on_copy_selected, "copy_from"),
        ("TimelinePanel._on_paste_selected",
         TimelinePanel._on_paste_selected, "PasteClipsCommand"),
        ("core.PasteClipsCommand.execute",
         core_commands.PasteClipsCommand.execute, "place_clip"),
        ("MainWindow._install_editor_shortcuts",
         MainWindow._install_editor_shortcuts, "_on_copy_selected"),
        ("MainWindow._install_editor_shortcuts",
         MainWindow._install_editor_shortcuts, "_on_paste_selected"),
    )
    missing = sorted({name for name, fn, helper in seams
                      if helper not in walk_names(fn)})
    if missing:
        raise RuntimeError("seam clipboard thieu: %s" % ", ".join(missing))

    # Detector phai bat duoc mot lenh dan "gia" khong goi place_clip, neu khong
    # thi dong gate nay chi xanh vi chua co cai de do.
    ns = {}
    exec(compile("class FakePaste:\n"
                 "    def execute(self):\n"
                 "        self.x = 1\n", "<mau>", "exec"), ns)
    if "place_clip" in walk_names(ns["FakePaste"].execute):
        raise RuntimeError("detector khong phan biet duoc lenh dan that va gia")

    folder = tempfile.mkdtemp(prefix="clinging_clipboard_")
    cwd = os.getcwd()
    os.chdir(folder)
    try:
        model = TimelineModel()
        track = model.add_track(TrackType.TEXT)
        a = model.add_clip(track.track_id, "", "text", 0.0, 2.0, "A")
        b = model.add_clip(track.track_id, "", "text", 3.0, 2.0, "B")
        a.font_size = 57.0
        a.text_effect = "karaoke"
        a.transform.x = 123.0
        known = {a.clip_id, b.clip_id}
        before = sum(len(t.clips) for t in model.tracks)

        stack = core_commands.UndoStack()
        cb = ClipClipboard()
        model.select_clips([a.clip_id, b.clip_id])
        copied = cb.copy_from(model, model.selected_clip_ids)
        if copied != 2:
            raise RuntimeError("copy khong lay du 2 clip dang chon (duoc %d)"
                               % copied)
        if cb.is_empty:
            raise RuntimeError("clipboard bao trong sau khi copy 2 clip")

        anchor = 10.0
        cmd1 = core_commands.PasteClipsCommand(model, cb.entries(), anchor)
        stack.push(cmd1)
        pasted = [c for cid in cmd1._pasted_ids
                  if (c := model.get_clip(cid)) is not None]
        if len(pasted) != 2:
            raise RuntimeError("paste khong ra 2 clip (duoc %d)" % len(pasted))
        if {c.clip_id for c in pasted} & known:
            raise RuntimeError("ban dan trung id voi clip goc")
        pa = next((c for c in pasted if abs(c.font_size - 57.0) < 0.001), None)
        if (pa is None or pa.text_effect != "karaoke"
                or abs(pa.transform.x - 123.0) > 0.001):
            raise RuntimeError("ban dan khong giu nguyen font/hinh hoc clip goc")
        starts = sorted(c.start_time for c in pasted)
        if (abs(starts[0] - anchor) > 0.001
                or abs(starts[1] - (anchor + 3.0)) > 0.001):
            raise RuntimeError("le bo cuc tuong doi khi dan nhieu clip: %s"
                               % starts)
        if sum(len(t.clips) for t in model.tracks) != before + 2:
            raise RuntimeError("paste thu nhat khong tang dung 2 clip")

        # Paste lan hai cung anchor -> clip trung choang nen phai nhay layer
        # (danh duong _create_collision_track cua place_clip), van du 2 clip.
        cmd2 = core_commands.PasteClipsCommand(model, cb.entries(), anchor)
        stack.push(cmd2)
        mid = sum(len(t.clips) for t in model.tracks)
        if mid != before + 4:
            raise RuntimeError("paste va cham khong them dung 2 clip (%d)" % mid)

        stack.undo()
        stack.undo()
        back = sum(len(t.clips) for t in model.tracks)
        if back != before:
            raise RuntimeError("undo hai lan paste khong tra ve %d clip (con %d)"
                               % (before, back))

        stack.redo()
        stack.redo()
        if sum(len(t.clips) for t in model.tracks) != before + 4:
            raise RuntimeError("redo paste khong lam lai du 4 clip")
        stack.undo()
        stack.undo()
    finally:
        os.chdir(cwd)
        shutil.rmtree(folder, ignore_errors=True)
    return ("5 seam clipboard qua co_names, detector bat duoc lenh dan gia, "
            "copy 2 clip, dan giu font_size=57/karaoke/x=123 + lech 3,0s, "
            "dan lan 2 va cham nhay layer van +2, undo/redo khop so clip")


def _undo_text_transform_ok():
    """Nhom A3: doi chu / doi hinh hoc phai thanh MOT buoc UndoStack.

    Chieu thu nhat cua ban cu: panel ghi thang vao clip_model nen Ctrl+Z bo qua
    moi thao tac chu. Chieu thu hai cua ban lam qua tay: neu moi ky tu go la mot
    lenh thi MAX_HISTORY = 100 bi dien sach chi vi mot doan chu. Ca hai chieu
    deu do tai day, tren widget that cua panel.
    """
    import shutil
    import tempfile
    import types

    from PySide6.QtWidgets import QWidget
    from core import commands as core_commands
    from core.timeline_model import TimelineModel, TrackType
    from ui.graphics_canvas_item import CanvasClipItem, TextClipItem
    from ui.main_window import MainWindow
    from ui.properties_panel import ClipPropertiesWidget

    TOL = 0.005

    def routes_through(fn, helper):
        """Handler phai goi helper va khong con cham thang vao clip_model."""
        names = fn.__code__.co_names
        return helper in names and "clip_model" not in names

    HANDLERS = ("_on_font_changed", "_on_font_size_changed", "_on_bold_toggled",
                "_on_italic_toggled", "_on_underline_toggled",
                "_on_text_color_clicked", "_on_text_content_changed",
                "_on_text_effect_changed", "_on_text_style_changed",
                "_on_text_intensity_changed")
    direct = [name for name in HANDLERS
              if not routes_through(getattr(ClipPropertiesWidget, name),
                                    "_push_text")]
    if len(HANDLERS) != 10 or direct:
        raise RuntimeError("handler chu khong di qua _push_text: %s"
                           % ", ".join(direct))

    # Detector phai bat duoc cach cu, neu khong thi no chi xanh vi code chua co
    # handler nao duoc kiem tra that.
    ns = {}
    exec(compile("class R:\n"
                 "    def _on_bold_toggled(self):\n"
                 "        self.clip_model.font_bold = True\n",
                 "<mau>", "exec"), ns)
    if routes_through(ns["R"]._on_bold_toggled, "_push_text"):
        raise RuntimeError("detector khong phan biet duoc ghi thang va ghi qua lenh")

    seams = (
        ("MainWindow._on_properties_changed_by_user",
         MainWindow._on_properties_changed_by_user, "SetClipTransformCommand"),
        ("MainWindow._on_canvas_edit_committed",
         MainWindow._on_canvas_edit_committed, "SetClipTransformCommand"),
        ("CanvasClipItem.mouseReleaseEvent",
         CanvasClipItem.mouseReleaseEvent, "_commit_gesture"),
        ("TextClipItem.mouseReleaseEvent",
         TextClipItem.mouseReleaseEvent, "_commit_gesture"),
        ("TextClipItem.focusOutEvent",
         TextClipItem.focusOutEvent, "on_edit_commit"),
        ("MainWindow._wire_events", MainWindow._wire_events, "_on_clip_updated"),
        ("MainWindow._wire_events", MainWindow._wire_events, "_undo_step"),
    )
    missing = sorted({name for name, fn, helper in seams
                      if helper not in fn.__code__.co_names})
    if missing:
        raise RuntimeError("seam undo thieu: %s" % ", ".join(missing))

    folder = tempfile.mkdtemp(prefix="clinging_undo_")
    cwd = os.getcwd()
    os.chdir(folder)
    host = None
    try:
        model = TimelineModel()
        track = model.add_track(TrackType.TEXT)
        clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, "Tieu de")
        stack = core_commands.UndoStack()
        host = QWidget()
        host.setObjectName("MainWindow")
        host.timeline_panel = types.SimpleNamespace(model=model, undo_stack=stack)
        host.preview_panel = types.SimpleNamespace(
            canvas=types.SimpleNamespace(_clip_items={}))
        seen = []
        host.properties_panel = types.SimpleNamespace(
            current_editor=None, update_editor_values=seen.append)
        # host dong vai MainWindow gia: _undo_step/_redo_step that goi
        # self._sync_panel_after_history(), ma QWidget tran khong co. Bind body
        # that cua MainWindow de Ctrl+Z van doc lai o nhap dung duong production.
        host._sync_panel_after_history = (
            lambda: MainWindow._sync_panel_after_history(host))
        editor = ClipPropertiesWidget(clip, parent=host)
        host.properties_panel.current_editor = editor

        for text in ("T", "Ti", "Tieu de moi"):
            editor.text_edit.setPlainText(text)
        if stack.undo_count != 1:
            raise RuntimeError("3 lan go chu tao %d buoc, phai la 1" % stack.undo_count)
        if clip.name != "Tieu de moi":
            raise RuntimeError("lenh chu khong ghi duoc vao model")
        stack.undo()
        if clip.name != "Tieu de":
            raise RuntimeError("Ctrl+Z khong tra lai chu cu: %s" % clip.name)
        stack.redo()
        if clip.name != "Tieu de moi":
            raise RuntimeError("Ctrl+Y khong lam lai duoc lenh chu")

        was_bold = bool(clip.font_bold)
        editor.btn_bold.click()
        if stack.undo_count != 2 or clip.font_bold == was_bold:
            raise RuntimeError("not chuot bold khong thanh mot buoc undo rieng")
        stack.undo()
        if bool(clip.font_bold) != was_bold or stack.undo_count != 1:
            raise RuntimeError("Ctrl+Z khong hoan tac buoc bold ve gia tri cu")
        stack.redo()

        size_before = float(clip.font_size)
        for size in (20.0, 26.0, 31.0):
            editor.spin_font_size.setValue(size)
        if stack.undo_count != 3:
            raise RuntimeError("3 nac spin tao %d buoc, phai la 1" % stack.undo_count)
        stack.undo()
        if abs(clip.font_size - size_before) > TOL:
            raise RuntimeError("hoan tac spin tra ve %s chu khong phai %s"
                               % (clip.font_size, size_before))
        stack.redo()
        if abs(clip.font_size - 31.0) > TOL:
            raise RuntimeError("Ctrl+Y khong lam lai duoc nac spin")

        def funnel(scale_x, scale_y, rotation, opacity, x, y, name=None):
            MainWindow._on_properties_changed_by_user(
                host, clip.clip_id, name if name is not None else clip.name,
                scale_x, scale_y, rotation, opacity, x, y)

        press = core_commands.transform_snapshot(clip)
        funnel(2.0, 1.0, 15.0, 0.5, 100.0, 200.0)
        moved = core_commands.transform_snapshot(clip)
        if stack.undo_count != 4:
            raise RuntimeError("nhap so tren panel khong tao buoc undo")
        if abs(moved["scale_x"] - 2.0) > TOL or abs(moved["rotation"] - 15.0) > TOL:
            raise RuntimeError("lenh hinh hoc khong ghi du so vao model")

        n = stack.undo_count
        funnel(moved["scale_x"], moved["scale_y"], moved["rotation"],
               moved["opacity"], moved["x"], moved["y"])
        if stack.undo_count != n:
            raise RuntimeError("go so khong doi gi van them mot buoc rong")

        stack.undo()
        restored = core_commands.transform_snapshot(clip)
        if any(abs(restored[k] - press[k]) > TOL for k in press):
            raise RuntimeError("Ctrl+Z hinh hoc sai: %s" % restored)

        # Clip co keyframe: AutoKeyframeCommand da la lenh undo cua thao tac,
        # them mot lenh hinh hoc nua buoc nguoi dung Ctrl+Z hai lan.
        clip.add_keyframe("scale_x", 0.0, 1.0)
        n = stack.undo_count
        funnel(3.0, 1.0, 0.0, 1.0, 0.0, 0.0)
        if stack.undo_count != n:
            raise RuntimeError("clip co keyframe bi them lenh hinh hoc dup")
        if abs(clip.transform.scale_x - 3.0) > TOL:
            raise RuntimeError("duong keyframe khong con ghi duoc so nhu cu")

        # keo neo tren Canvas: model da bi ghi truoc khi lenh chay, nen phai
        # nhan `before` tu luc bam chuot.
        clip.transform.x = 260.0
        after = core_commands.transform_snapshot(clip)
        before = dict(after)
        before["x"] = 0.0
        n = stack.undo_count
        MainWindow._on_canvas_edit_committed(host, clip, "transform", after, before)
        if stack.undo_count != n + 1:
            raise RuntimeError("ket thuc keo tren Canvas khong tao buoc undo")
        MainWindow._on_canvas_edit_committed(host, clip, "transform", after, after)
        if stack.undo_count != n + 1:
            raise RuntimeError("click khong keo tao buoc undo rong")
        MainWindow._undo_step(host)
        if abs(clip.transform.x) > TOL:
            raise RuntimeError("hoan tac keo tra ve %s chu khong phai 0.0"
                               % clip.transform.x)
        if not seen or seen[-1].clip_id != clip.clip_id:
            raise RuntimeError("Ctrl+Z khong doc lai o nhap tren panel")

        MainWindow._on_canvas_edit_committed(host, clip, "text",
                                            {"name": "Chu inline"})
        if clip.name != "Chu inline":
            raise RuntimeError("sua chu tren Canvas khong ghi vao model")
        MainWindow._undo_step(host)
        if clip.name == "Chu inline":
            raise RuntimeError("Ctrl+Z khong hoan tac duoc chu sua tren Canvas")

        return ("%d ky tu go = 1 buoc, %d nac spin = 1 buoc, %d seam struct + "
                "2 duong keyframe/gesture da kiem"
                % (3, 3, len(seams)))
    finally:
        os.chdir(cwd)
        if host is not None:
            host.deleteLater()
        shutil.rmtree(folder, ignore_errors=True)


def _recent_readonly_ok():
    """Mo app khong duoc phep ghi danh sach du an gan day cua nguoi dung.

    `HomePage._load_recent_projects()` tung ket thuc bang
    `save_recent_projects(valid_projects)`, tuc la duong DOC ghi file, va tinh
    xoa moi muc ma `os.path.exists()` tra False ngay luc do — cam o roi chua
    cam, doi ten thu muc, hay mo app "chi de xem" la mat mai muc trong MRU.
    Bundle khong con nguon .py de doc, nen gate lay `co_names` cua chinh ham
    trong process nay; chieu nguoc lai cung phai do: bon hanh dong tao/nhap/
    doi ten/xoa van phai ghi, neu khong thi "khong ghi khi doc" chi la vi da
    xoa luon duong ghi.

    `scratch/recent_projects_safety_probe.py` la bang chung hanh vi day du
    (boot that trong APPDATA tam, so md5 tung byte, kem phep phan chung dung
    lai hanh vi cu). Dong nay chi gi cho khong bi tai lap.
    """
    import ui.home_page as hp

    def writes_recent(fn):
        return "save_recent_projects" in fn.__code__.co_names

    # Tu thu detector: mot ban "doc-roi-ghi" dich tai luc chay phai bi bat.
    # Khong co buoc nay thi co_names co the trung mot cach viet khac va dong
    # gate xanh ngay ca khi loi con nguyen.
    rival_ns = {"load_recent_projects": hp.load_recent_projects,
                "save_recent_projects": hp.save_recent_projects, "os": os}
    exec("def rival(self):\n"
         "    recent = load_recent_projects()\n"
         "    save_recent_projects([p for p in recent if os.path.exists(p)])\n",
         rival_ns)
    if not writes_recent(rival_ns["rival"]):
        raise RuntimeError("detector khong bat duoc cach viet cu -> gate vo nghia")

    if writes_recent(hp.HomePage._load_recent_projects):
        raise RuntimeError("_load_recent_projects van ghi recent_projects.json "
                           "khi mo app")
    missing = [name for name in ("_on_template_clicked", "_on_import_project",
                                 "_on_rename_project", "_on_delete_project")
               if not writes_recent(getattr(hp.HomePage, name))]
    if missing:
        raise RuntimeError("hanh dong khong con ghi MRU: %s" % ", ".join(missing))
    return ("duong doc khong ghi, 4 hanh dong van ghi; detector bat duoc cach viet cu")


# Hai cach tu viet phep tinh moc thoi gian cua clip that su tung ton tai song
# song nhau (preview kep ve duration - 1e-6, export tru tho). Detector ben duoi
# phai do voi ca hai cach do va xanh voi diem vao chung, nen no duoc thu tren
# mot ham doi thu bien dich tai luc chay — khong the doc file .py vi bundle
# khong con nguon.
_HAND_RENDERS = (
    "def f(clip, t):\n"
    "    return max(0.0, min(t, clip.end_time - 1e-6) - clip.start_time)\n",
    "def f(clip, t):\n"
    "    return t - clip.start_time\n",
)


def _local_time_ok():
    """Preview va export phai lay moc thoi gian cuc bo cua clip tu MOT ham.

    ClipModel.local_time_at la diem vao chung, cung khuon voi source_time: khi
    moi ben tu tru ``t - clip.start_time`` thi bien clip co hai cach khac nhau,
    va khung hinh cuoi cua clip doc sang nguon qua moc o ben nay nhung khong o
    ben kia. Phep kiem nay do hai thu:

      1. Bien [0, duration) tai sau moc ngoai doi tuong — ke ca khi playhead
         nam qua mat clip hoac dung o cuoi du an.
      2. ``co_names`` cua hai ham san xuat that (FrameComposer.render_frame va
         MainWindow._sync_canvas_frames_at_time) phai goi local_time_at va
         KHONG duoc con tai ``start_time``. co_names doc duoc ca trong bundle
         da dong goi, khong can nguon.
    """
    from core.timeline_model import ClipModel

    clip = ClipModel(start_time=1.0, duration=2.0, in_point=0.5, speed=2.0)
    end = clip.end_time
    last = round(2.0 - 0.000001, 6)
    got = [(t, round(clip.local_time_at(t), 6)) for t in
           (0.0, 0.4, 1.0, 2.5, end, end + 5.0)]
    want = [(0.0, 0.0), (0.4, 0.0), (1.0, 0.0), (2.5, 1.5), (end, last),
            (end + 5.0, last)]
    if got != want:
        raise RuntimeError("bien local_time_at sai: %s != %s" % (got, want))
    limit = clip.in_point + clip.duration * clip.speed_factor
    over = clip.source_at_local(clip.local_time_at(end + 9.0))
    if over > limit + 1e-9:
        raise RuntimeError("moc cuoi doc nguon qua cua so clip: %.6f > %.6f"
                           % (over, limit))

    def hand_rolled(func):
        names = set(func.__code__.co_names)
        return "start_time" in names or "local_time_at" not in names

    for source in _HAND_RENDERS:
        ns = {}
        exec(compile(source, "<rival>", "exec"), ns)
        if not hand_rolled(ns["f"]):
            raise RuntimeError("detector bo lot cach tu viet phep tru")
    ns = {}
    exec(compile("def g(clip, t):\n    return clip.local_time_at(t)\n",
                 "<seam>", "exec"), ns)
    if hand_rolled(ns["g"]):
        raise RuntimeError("detector bao nhom khi dung diem vao chung")

    from core.frame_composer import FrameComposer
    from ui.main_window import MainWindow
    bad = [label for label, fn in (
        ("FrameComposer.render_frame", FrameComposer.render_frame),
        ("MainWindow._sync_canvas_frames_at_time",
         MainWindow._sync_canvas_frames_at_time),
    ) if hand_rolled(fn)]
    if bad:
        raise RuntimeError("tu tinh moc thoi gian cuc bo: " + ", ".join(bad))
    return ("6 moc bien khop [0,%s), nguon dung tai %.3fs, 2/2 diem goi "
            "dung local_time_at" % (last, limit))


def _decode_cache_ok():
    """Decoder tuan tu + cache dia phai co trong bundle va chay duoc that.

    Ba thu dung trong bundle ma ban source khong thay: rule chon frame, key
    cache khong duration (loi that da tung lam crash luc mo project), va mot
    file nguon khong ton tai phai tra ve "chet", khong ngoai le.
    """
    from core.media_cache import (image_key, read_image, read_waveform,
                                  remove_path, waveform_key, write_image,
                                  write_waveform)
    from core.media_frame import SequentialVideoReader, frame_index_at
    import tempfile
    if (frame_index_at(0.5, 24), frame_index_at(1.49, 24),
            frame_index_at(-3.0, 24)) != (12, 36, 0):
        raise RuntimeError("rule frame_index_at sai: %r" % (
            [frame_index_at(t, 24) for t in (0.5, 1.49, -3.0)],))

    src = os.path.join(tempfile.gettempdir(), "clinging_selftest_src.mp4")
    with open(src, "wb") as handle:
        handle.write(b"not a real video")
    wkey = ikey = None
    try:
        wkey = waveform_key(src, 60, 0.0, None)
        ikey = image_key(src, "timeline", 0.5, 160, 60)
        if not wkey or not ikey:
            raise RuntimeError("thieu tham so khoa cache")
        amps = [0.25, 0.5, 1.0, 0.125]
        if not write_waveform(wkey, amps) or read_waveform(wkey) != amps:
            raise RuntimeError("song khong luu duoc qua cache")
        from PySide6.QtGui import QImage
        img = QImage(16, 8, QImage.Format_RGB32)
        img.fill(0xFF00FF00)
        if not write_image(ikey, img) or read_image(ikey).size() != img.size():
            raise RuntimeError("anh nho khong luu duoc qua cache")
        if read_waveform(wkey + ".missing") is not None:
            raise RuntimeError("muc khong co phai tra None")
        dead = SequentialVideoReader(os.path.join(tempfile.gettempdir(),
                                                  "khong_co_file_nay.mp4"))
        if dead.read_bgr(1.0) is not None or not dead.dead:
            raise RuntimeError("nguon mat phai tra None + bao chet")
        dead.close()
    finally:
        for key in (wkey, ikey):
            if key:
                remove_path(key)
        try:
            os.remove(src)
        except OSError:
            pass
    return "round(t*fps), cache anh+song, nguon mat -> dead"


def _library_panel_ok():
    """Thu vien tai nguyen: mot luot doi luoi cho ca dot, o luoi chi doi khi lech,
    the bi an khong lay task, the da xoa bi cat dien.

    Dong nay nam bon su that ma lan toi uu 22/10/2026 dat tren duong production
    `restore_resources()` (ui/main_window.py:214 goi luc mo project). Do tren
    luoi 65 the cung may nay (scratch/_lib_report.json): 65 luot _apply_filter
    -> 1, median mot phim go 17,72 -> 2,11 ms, anh tinh 1600 px/7,3 MiB ->
    320 px/0,29 MiB, 20/20 luot giai ma cho dot da xoa -> 4.

    Khong do thoi gian o day: dong selftest phai chay duoc trong bundle tren
    moi may, con nguong ms thuoc ve `--library-report`. Day la cong CHUC NANG —
    no do khi ban toi uu BI XOA hoac BI BAT HOAT, khong do no cham.
    """
    import tempfile
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from core import media_cache
    import ui.library_panel as lp

    app = QApplication.instance() or QApplication([])  # noqa: F841
    work = tempfile.mkdtemp(prefix="clinging_lib_")
    original_root = media_cache.cache_root
    media_cache.cache_root = lambda: os.path.join(work, "cache")
    panel = lp.LibraryPanel()
    hidden_panel = lp.LibraryPanel()
    fails = []
    try:
        # Fixture anh THAT (PNG 1200x900, doc qua duong production) + video gia
        # danh: cua nay kiem "co ai dem task vao pool", khong kiem giai ma video
        # thanh cong, nen file byte ran la du va khong can ffmpeg. Duong dan
        # cua 22 the PHAI khac nhau: `add_resource` bo qua tep trung duong dan.
        pngs = []
        for i in range(2):
            p = os.path.join(work, "photo_%02d.png" % i)
            QImage(1200, 900, QImage.Format_RGB32).save(p)
            pngs.append(p)
        clips = []
        for i in range(20):
            p = os.path.join(work, "clip_%02d.mp4" % i)
            with open(p, "wb") as handle:
                handle.write(b"not a real video")
            clips.append(p)
        for path in pngs + clips:
            if not os.path.isfile(path):
                raise RuntimeError("fixture hong: %r" % path)

        # 1. Anh tinh: thu nho TRONG LUC doc + luu cache dia co khoa rieng.
        first = lp.decode_thumb_image(pngs[0], "image")
        if first.isNull() or first.width() > 320:
            fails.append("anh tinh >320 px: %dx%d" % (first.width(),
                                                      first.height()))
        key = media_cache.image_key(pngs[0], "img", 0.0, 320, 320)
        if not key or not os.path.isfile(key):
            fails.append("anh tinh khong ghi cache dia")
        if lp.decode_thumb_image(pngs[0], "image").width() != first.width():
            fails.append("lan doc thu hai tra anh khac kich thuoc")

        # 2. Mot dot nap = MOT luot doi luoi. Dem tren instance nhung goi thang
        #    ham cua lop nen doan duoc dung la code that trong bundle.
        passes = [0]
        real_filter = panel._apply_filter

        def counted():
            passes[0] += 1
            real_filter()
        panel._apply_filter = counted

        adds = [0]

        def counting_add(*args, **kw):
            adds[0] += 1
            return lp.QGridLayout.addWidget(panel.grid, *args, **kw)
        panel.grid.addWidget = counting_add

        assets = ([{"name": os.path.basename(p), "type": "image", "path": p}
                   for p in pngs]
                  + [{"name": os.path.basename(p), "type": "video", "path": p}
                     for p in clips])
        panel.restore_resources(assets)
        if passes[0] != 1:
            fails.append("restore 22 the chay %d luot doi luoi" % passes[0])
        cards = [w for w in panel._items if isinstance(w, lp.ResourceCard)]
        if len(cards) != 22:
            fails.append("thieu the: %d/22" % len(cards))

        # 3. O luoi chi doi khi o THUC SU doi: hai lan bo loc khong doi ket qua
        #    khong duoc ban lai widget nao (do 65 the: 130 lan ban moi lan go).
        before = [(id(w), getattr(w, "_grid_cell", None)) for w in panel._items]
        base_adds = adds[0]
        panel._apply_filter()
        panel._apply_filter()
        after = [(id(w), getattr(w, "_grid_cell", None)) for w in panel._items]
        if before != after:
            fails.append("bo nho o luoi bi lech khi lap lai bo loc")
        if adds[0] != base_adds:
            fails.append("%d lan ban lai o cu khi bo loc khong doi"
                         % (adds[0] - base_adds))

        # 4. The bi bo loc an khong duoc xep giai ma; the hien ra thi phai duoc.
        #    Panel thu hai dat tab "Video" TRUOC khi nap, dung like luc mo
        #    project trong thu vien dang hien tab khac. TAB_TO_KIND: 1=video,
        #    2=audio, 3=image — anh nam o 3, khong phai 2.
        hidden_panel._select_tab(1)
        hidden_panel.restore_resources(assets)
        img_cards = [c for c in hidden_panel._items
                     if isinstance(c, lp.ResourceCard) and c.kind == "image"]
        vid_cards = [c for c in hidden_panel._items
                     if isinstance(c, lp.ResourceCard) and c.kind == "video"]
        if len(img_cards) != 2 or len(vid_cards) != 20:
            fails.append("panel tab Video co %d anh/%d video"
                         % (len(img_cards), len(vid_cards)))
        if any(c._thumb_task is not None for c in img_cards):
            fails.append("the anh bi an van co task giai ma")
        if any(c._thumb_task is None for c in vid_cards):
            fails.append("the video dang hien khong duoc xep giai ma")
        hidden_panel._select_tab(3)
        if any(c._thumb_task is None for c in img_cards):
            fails.append("the anh hien ra roi van khong duoc xep giai ma")

        # 5. Xoa kho thi cat dien: task cua the khong con ton tai phai ngung.
        live = [c._thumb_task for c in cards]
        if not any(t is not None for t in live):
            fails.append("khong co task nao de kiem cat dien")
        panel.clear_resources(emit_change=False)
        if any(not t.cancelled for t in live if t is not None):
            fails.append("task cua the da xoa khong bi cat dien")
        hidden_panel.clear_resources(emit_change=False)

        lp.thumb_pool().waitForDone(5000)
        app.processEvents()
    finally:
        media_cache.cache_root = original_root
        for widget in (panel, hidden_panel):
            widget.deleteLater()
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    if fails:
        raise RuntimeError("; ".join(fails))
    return "1 luot luoi/dot, o luoi on dinh, the an khong giai ma, xoa la cat"


def _thumbnail_export_ok():
    """Mot dong trong --selftest: trích xuất ảnh hàng loạt chạy thật trong bundle này.

    Ba dieu ma dong khac khong thay: (1) plan_times phai theo cung quy tac
    lam tron voi preview, (2) hai moc sat nhau khong duoc ghi de len nhau,
    (3) mot video that phai sinh ra DUNG so anh, va file tren dia phai doc lai
    duoc — import du module ma khong ghi duoc PNG thi van la ban hong.
    """
    import tempfile
    from core import thumbnail_export as thumbs
    from core.media_frame import frame_index_at

    even = thumbs.plan_times(4.0, thumbs.MODE_COUNT, count=12)
    # [0.167, 0.5, 0.833]: lam TRON chu khong phai cat — cat thi ra 0.166.
    if len(even) != 12 or even[:3] != [0.167, 0.5, 0.833]:
        raise RuntimeError("plan deu sai: %r" % even[:3])
    periodic = thumbs.plan_times(4.0, thumbs.MODE_INTERVAL, interval=1.0)
    if periodic != [0.0, 1.0, 2.0, 3.0, 4.0]:
        raise RuntimeError("plan chu ky sai: %r" % periodic)
    clipped = thumbs.plan_times(4.0, thumbs.MODE_INTERVAL, interval=1.0,
                                start=1.0, end=3.0)
    if clipped != [1.0, 2.0, 3.0]:
        raise RuntimeError("plan trong khoang sai: %r" % clipped)
    if [frame_index_at(t, 24) for t in (0.167, 0.5)] != [4, 12]:
        raise RuntimeError("rule frame_index_at doi khac")

    dense = [0.0, 0.05, 0.1]
    digits = thumbs._naming_digits(dense)
    names = [thumbs.frame_name(t, digits) for t in dense]
    if len(set(names)) != 3 or digits != 3:
        raise RuntimeError("ten file trung nhau: %r" % names)
    if thumbs.time_label(0.05, digits) != "0.050s":
        raise RuntimeError("chuoi nhan label khop ten file")

    import cv2
    import numpy as np
    folder = tempfile.mkdtemp(prefix="clinging_thumb_")
    try:
        src = os.path.join(folder, "src.mp4")
        writer = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*"mp4v"), 30.0,
                                 (160, 90))
        if not writer.isOpened():
            raise RuntimeError("bundle nay khong tao duoc video ngan")
        for index in range(30):
            writer.write(np.full((90, 160, 3), index * 8 % 256, np.uint8))
        writer.release()
        out = os.path.join(folder, "ra")
        result = thumbs.export_video_thumbnails(src, out, count=4, width=160)
        written = result.get("written", [])
        if len(written) != 4 or result.get("missing"):
            raise RuntimeError("xuat 4 moc chi ra %d anh: %r"
                               % (len(written), result.get("missing")))
        on_disk = sorted(n for n in os.listdir(out) if n.startswith("frame_"))
        if on_disk != sorted(os.path.basename(p) for p in written):
            raise RuntimeError("anh tren dia khong khop ket qua: %r" % on_disk)
        for path in written:
            image = cv2.imread(path)
            if image is None or image.shape[1] != 160 or image.shape[0] != 90:
                raise RuntimeError("anh ghi ra doc lai khong duoc: %s" % path)
        sheets = result.get("sheets", [])
        if len(sheets) != 1 or not os.path.isfile(sheets[0]):
            raise RuntimeError("thieu anh tong hop: %r" % sheets)
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return "plan 12/5/3 moc, ten 3 so le, 4 anh + 1 sheet ghi ra that"


def _media_split_ok():
    """Mot dong trong --selftest: cat file ra ĐĨA chạy thật trong bundle nay.

    Selftest nay khong trung lap scratch/media_split_probe.py: no tra loi mot
    cau hoi khac — LIEU BUNDLE dong goi co du `core.media_splitter` +
    `ui.split_dialog` va goi duoc ffmpeg cua PATH de ra N file doc lai duoc
    hay khong. Ba dieu bat buoc cho MOI KIEU CAT (deu nhau / doi dai co dinh /
    moc tu dat): (1) ke hoach khong duoc an hay doi noi dung (tong span ==
    nguon, cac mei cat bang 0), (2) file ghi ra phai duoc ffprobe doc lai bang
    thoi luong that, (3) doan nao cung khong duoc rong.
    """
    import subprocess
    import tempfile

    from core import external_tools
    from core import media_splitter as splitter
    from ui.split_dialog import SplitDialog  # noqa: F401  (phai co trong bundle)

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    folder = tempfile.mkdtemp(prefix="clinging_split_")
    try:
        src = os.path.join(folder, "nguon.mp4")
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
             "color=c=red:s=160x120:d=6:r=25,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-g", "10", src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            check=False, creationflags=0x08000000)
        total = splitter.probe_duration(src)
        if total <= 0:
            raise RuntimeError("bundle nay khong tao/doc duoc video ngan")

        def one(label, expected, uneven=False, **plan_args):
            """Cat MOT ke hoach va do tren FILE — khong phai do lenh cat tu khai."""
            out = os.path.join(folder, "ra_" + label)
            result = splitter.split_media(src, out, **plan_args)
            rows = result["segments"]
            if len(rows) != expected or result["failed"] or result["cancelled"]:
                raise RuntimeError("kieu %s cat sai: %r" % (label, result))
            spans = [row["span"] for row in rows]
            if abs(sum(spans) - total) > 0.05:
                raise RuntimeError("kieu %s an/doi noi dung: %r vs %.3f"
                                   % (label, spans, total))
            if uneven and max(spans) - min(spans) < 0.1 * total:
                raise RuntimeError("kieu %s cho ra chia deu %r: moc/doi dai "
                                   "nhap vao khong duoc dung" % (label, spans))
            for index, row in enumerate(rows, start=1):
                if not os.path.isfile(row["path"]) or os.path.getsize(
                        row["path"]) < 1000:
                    raise RuntimeError("kieu %s doan %d khong co tren dia"
                                       % (label, index))
                if splitter.probe_duration(row["path"]) <= 0:
                    raise RuntimeError("kieu %s doan %d ffprobe khong doc duoc"
                                       % (label, index))
                if index > 1 and abs(row["start"]
                                     - (rows[index - 2]["start"]
                                        + rows[index - 2]["span"])) > 1e-6:
                    raise RuntimeError("kieu %s mei cat %d ho hoac choong"
                                       % (label, index))
            return len(rows)

        counts = [
            one("deu", 2, count=2),
            # 2,95 s tren nguon 6 s de lai du 0,10 s: doan du < 0,2 s phai ghep
            # vao doan ke truoc (con 2 doan), khong vet noi dung va khong tao
            # mot file 0,1 s khong ai xem.
            one("doi dai", 2, length=2.95),
            # Moc nguoi dung NHAP, khong phai so do vien ra: '1:02' la 62 s
            # (ngoai khoang nen bi bo), '0:01.6' sat '0:01.5' duoi 0,2 s (bi bo),
            # '5.95' sat met cuoi (bi ghep), 'abc' phai duoc bao ve.
            one("moc", 4, uneven=True,
                points=splitter.parse_cut_points(
                    "0:01.5, 0:01.6, 0:03.25, 0:04.4, 1:02, 5.95, 99, abc")[0]),
        ]
        # Ke hoach dung moc hay khong la do tren dia; con loc duoc moc nao thi
        # nguoi dung chi thay qua chinh dong bao loi nay.
        if splitter.parse_cut_points("0:02, abc, 1:02:03")[1] != ["abc"]:
            raise RuntimeError("moc sai khong duoc bao ve")
        if splitter.parse_cut_points("1:02:03")[0] != [3723.0]:
            raise RuntimeError("gio:phut:giay bi doc thanh so khac")
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return ("%d kieu cat (deu/doi dai/moc) ra %d doan that, tong span = nguon, "
            "ffprobe doc lai duoc" % (len(counts), sum(counts)))


def _media_compress_ok():
    """Mot dong trong --selftest: nen / toi uu MOT file tren dia, do bang so that.

    Khong trung lap scratch/compress_cost_probe.py (do chi phi), o day hoi bon
    dieu ma nguoi dung chi phat hien ra khi da mat video: (1) `remux` that su
    DI MOOV LEN DAU — do la toan bo loi ich cua "toi uu khong mat chat", va
    fixture phai CHUA faststart tu truoc khi chay neu khong dong nay xanh boi
    an; (2) moi loi phai tra ve mot cau doc duoc truoc khi kip lay lenh ffmpeg
    chua chay; (3) thang tien trinh doc duoc ca ba cach ffmpeg in moc thoi
    gian; (4) that bai thi khong de lai file ru mang duoi .mp4; (5)
    `ui.compress_dialog` phai doc duoc tu PYZ cua bundle — no chi duoc nap
    bang lenh import ben trong `MainWindow._open_media_compress`, nen neu ban
    dong goi thieu module thi menu "Nen / toi uu tep" crash luc nguoi dung
    bam trong khi moi cong chay tu source tree van xanh. Cung ly do do
    `ui.split_dialog` bi import thang vao dong cua no.
    """
    import subprocess
    import tempfile

    from core import external_tools
    from core import media_compress as compress
    from ui.compress_dialog import CompressDialog  # noqa: F401 (co trong bundle)

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    for mode in compress.MODES:
        encoder = compress.ENCODER_OF.get(mode)
        if encoder and not compress.encoder_present(encoder, ffmpeg):
            raise RuntimeError("ffmpeg cua bundle nay khong co %s (%s)"
                               % (encoder, mode))
    folder = tempfile.mkdtemp(prefix="clinging_compress_")
    numbers = {}
    try:
        src = os.path.join(folder, "nguon.mp4")
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=size=160x120:rate=25:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            check=False, creationflags=0x08000000)
        facts = compress.source_facts(src)
        if not facts["exists"] or facts["bytes"] <= 0:
            raise RuntimeError("khong dung duoc fixture 2s")
        if facts["video_codec"] != "h264":
            raise RuntimeError("fixture khong phai h264: %r"
                               % facts["video_codec"])
        # Canary: fixture PHAI chua faststart. Mot file da faststart thi
        # `is_faststart(out)` xanh ma khong can remux lam gi.
        if compress.is_faststart(src):
            raise RuntimeError("fixture da faststart san — dong nay khong "
                               "phan biet duoc gi")
        numbers["src_bytes"] = facts["bytes"]
        numbers["src_atoms"] = [name for name, _ in
                                compress.top_level_atoms(src)]

        out = os.path.join(folder, "ra_remux.mp4")
        remux = compress.compress_file(src, out, mode=compress.MODE_REMUX)
        if not remux["ok"]:
            raise RuntimeError("remux that bai: %s" % remux["error"])
        if not compress.is_faststart(out):
            raise RuntimeError("remux xong ma moov van nam cuoi file")
        probe = compress.source_facts(out)
        if abs(probe["duration"] - facts["duration"]) > 0.05:
            raise RuntimeError("remux an/doi noi dung: %.3f vs %.3f"
                               % (probe["duration"], facts["duration"]))
        numbers["remux_bytes"] = remux["output_bytes"]
        numbers["remux_atoms"] = [name for name, _ in
                                  compress.top_level_atoms(out)]

        encoded = os.path.join(folder, "ra_x264.mp4")
        run = compress.compress_file(src, encoded, mode=compress.MODE_X264,
                                     crf=28, preset="ultrafast")
        if not run["ok"]:
            raise RuntimeError("x264 that bai: %s" % run["error"])
        if abs(compress.source_facts(encoded)["duration"]
               - facts["duration"]) > 0.1:
            raise RuntimeError("x264 doi thoi luong: %.3f" % facts["duration"])
        numbers["x264_bytes"] = run["output_bytes"]

        # --- loi phai la mot cau, khong phai mot lenh da chay nua ---
        gone = compress.compress_file(os.path.join(folder, "khong_ton_tai.mp4"),
                                      os.path.join(folder, "a.mp4"))
        if gone["ok"] or not gone["error"]:
            raise RuntimeError("nguon khong ton tai ma van 'ok'")
        same = compress.compress_file(src, src, mode=compress.MODE_REMUX)
        if same["ok"] or "trùng file nguồn" not in same["error"]:
            raise RuntimeError("file ket qua trung file nguon: %r"
                               % same["error"])
        blocked = compress.compress_file(src, os.path.join(folder, "a.webm"),
                                         mode=compress.MODE_X264)
        if blocked["ok"] or "webm" not in blocked["error"].lower():
            raise RuntimeError("x264 ghi duoc vao webm: %r" % blocked["error"])
        wrong_mode = compress.compress_file(src, os.path.join(folder, "b.mp4"),
                                            mode="khong_co_thuc")
        if wrong_mode["ok"] or not wrong_mode["error"]:
            raise RuntimeError("kieu khong hop le ma khong bao loi")

        # --- that bai / dung giua chung thi khong de lai file rac ---
        junk = os.path.join(folder, "rac.mp4")
        with open(junk, "wb") as handle:
            handle.write(b"day la van ban, khong phai video")
        partial = os.path.join(folder, "ket_qua.mp4")
        failed = compress.compress_file(junk, partial)
        if failed["ok"] or not failed["error"]:
            raise RuntimeError("nguon rac ma bao thanh cong")
        if os.path.exists(partial):
            raise RuntimeError("that bai nhung de lai file do %s" % partial)
        cancelling = os.path.join(folder, "dang_chay.mp4")
        stop = compress.compress_file(src, cancelling, mode=compress.MODE_X264,
                                      crf=28, preset="ultrafast",
                                      should_cancel=lambda: True)
        if not stop["cancelled"] or not stop["error"]:
            raise RuntimeError("Huy khong duoc bao cao: %r" % stop)
        if os.path.exists(cancelling):
            raise RuntimeError("dung giua chung van con file do %s" % cancelling)

        # --- codec/do duoi: dieu ma build_command cu se sinh ra lenh vo nghia --
        vp9 = compress.build_command(ffmpeg, src, os.path.join(folder, "v.webm"),
                                     compress.MODE_VP9)
        text = " ".join(vp9)
        if "-preset" in text:
            raise RuntimeError("vp9 nhan -preset: ffmpeg bao 'Invalid preset'")
        if "-cpu-used" not in text or "-b:v 0" not in text:
            raise RuntimeError("vp9 thieu -cpu-used hoac -b:v 0: %s" % text)
        if "-c:a libopus" not in text:
            raise RuntimeError("webm ma mang aac: %s" % text)
        if not compress.suggest_output(
                src, compress.MODE_VP9).lower().endswith(".webm"):
            raise RuntimeError("goi y file cho vp9 khong doi duoi .webm")
        if compress.container_choices(compress.MODE_VP9) != [".mkv", ".webm"]:
            raise RuntimeError("bang container cua vp9 bi lech: %r"
                               % compress.container_choices(compress.MODE_VP9))
        if compress.pair_error(os.path.join(folder, "r.webm"),
                               compress.MODE_REMUX, "h264") == "":
            raise RuntimeError("remux video h264 ra webm khong bi chan")
        try:
            compress.build_command(ffmpeg, src, os.path.join(folder, "x.webm"),
                                   compress.MODE_X264)
            raise RuntimeError("build_command khong chan x264 trong webm")
        except ValueError:
            pass
        clamped = " ".join(compress.build_command(ffmpeg, src,
                                                  os.path.join(folder, "c.mp4"),
                                                  compress.MODE_X264, crf=99))
        if "-crf %d" % compress.CRF_MAX not in clamped:
            raise RuntimeError("CRF 99 khong bi chan ve CRF_MAX")
        low = " ".join(compress.build_command(ffmpeg, src,
                                              os.path.join(folder, "c.mp4"),
                                              compress.MODE_X264, crf=1))
        if "-crf %d" % compress.CRF_MIN not in low:
            raise RuntimeError("CRF 1 khong bi chan ve CRF_MIN")
        hevc = " ".join(compress.build_command(ffmpeg, src,
                                               os.path.join(folder, "h.mp4"),
                                               compress.MODE_X265))
        if "-tag:v hvc1" not in hevc or "-movflags +faststart" not in hevc:
            raise RuntimeError("hevc trong mp4 thieu tag hvc1/faststart")

        # --- thang tien trinh: ba cach ffmpeg in moc thoi gian ---
        if compress.read_progress("out_time_us=1500000", 3.0) != 50:
            raise RuntimeError("khong doc duoc out_time_us")
        if compress.read_progress("out_time_ms=1500000", 3.0) != 50:
            raise RuntimeError("khong doc duoc out_time_ms (ban cu)")
        if compress.read_progress("out_time=00:00:01.500000", 3.0) != 50:
            raise RuntimeError("khong doc duoc out_time=HH:MM:SS")
        if compress.read_progress("frame= 12 fps=0.0 q=28.0", 3.0) != -1:
            raise RuntimeError("dong khong phai moc bi hieu nham la tien do")
        if compress.estimate_seconds(compress.MODE_REMUX, 60.0) != 0.0:
            raise RuntimeError("remux duoc bao la ton thoi gian ma hoa")
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return ("nguon %d B moov-cuoi -> remux %d B moov-dau (%s), x264 %d B; "
            "5 loi hop-le + nguon rac/lenh Huy khong de lai file do; vp9 "
            "-cpu-used/-b:v 0/libopus; 3 cach doc tien do" %
            (numbers["src_bytes"], numbers["remux_bytes"],
             ">".join(numbers["remux_atoms"]), numbers["x264_bytes"]))


def _detach_audio_ok():
    """Mot dong trong --selftest: tach tieng clip video thanh clip audio rieng.

    Dong nay do tren CHUOI LOC MA EXPORTER SE CHAY (core.audio_mix), khong phai
    mot danh sach clip tu kiem tra — tach tieng ma export van doc hai clip cung
    nguon thi nguoi dung nghe tieng gon doi. Ba dieu bat buoc:

    (1) clip audio mang dung start_time/duration/in_point/speed/volume/fade cua
        clip video: lech nua giay la tieng khong con cua khung hinh do nua;
    (2) collect_audio_clips con lai DUNG clip audio, va filter_complex keo
        adelay = start_time — do la vi tri that cua no tren timeline;
    (3) Ctrl+Z tra lai ca hai nua cung luc va khong lam mat hang audio trong san
        co (remove_clip tu xoa hang khi clip cuoi bi go — do la bẫy cua no).

    Gate phai do khi nguon khong co luong tieng: mot file video im lang thi
    "tach" ra mot clip rang, nen do la dau hieu fixture hoac loader hong.
    """
    import subprocess
    import tempfile

    from core import external_tools
    from core.audio_mix import build_filter_complex, collect_audio_clips
    from core.commands import DetachAudioCommand, UndoStack
    from core.timeline_model import ClipModel, TimelineModel, TrackType

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    folder = tempfile.mkdtemp(prefix="clinging_detach_")
    try:
        src = os.path.join(folder, "nguon.mp4")
        subprocess.run(
            [ffmpeg, "-v", "error", "-y",
             "-f", "lavfi", "-i",
             "testsrc2=size=160x120:rate=25:duration=4",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
             "-shortest", src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
            check=False, creationflags=0x08000000)
        if not os.path.isfile(src):
            raise RuntimeError("khong tao duoc video co tieng de do")

        model = TimelineModel()
        model.add_track(TrackType.VIDEO)   # Main Storyline, de trong co tinh
        # Clip do nam tren hang Overlay: hang truc tu li dong nan clip ve 0 khi
        # xoa clip cung hang, nen doan 1.5s o day vo sinh — start_time phai duoc
        # giu nguyen de do dung duoc adelay cua exporter.
        video_track = model.add_track(TrackType.VIDEO)
        empty_audio = model.add_track(TrackType.AUDIO)
        empty_id = empty_audio.track_id
        clip = ClipModel(start_time=1.5, duration=1.0, source_path=src,
                         media_type="video", name="Nguon", in_point=0.2,
                         out_point=1.2, source_duration=4.0,
                         track_id=video_track.track_id)
        clip.speed = 2.0
        clip.volume = 0.7
        clip.fade_in = 0.1
        clip.fade_out = 0.2
        clip.refresh_out_point()
        video_track.clips.append(clip)
        model.recalculate_project_duration()
        model.clipAdded.emit(clip)

        from core.audio_mix import has_audio_stream
        if not has_audio_stream(src):
            raise RuntimeError("fixture khong co luong tieng, gate do gia")

        # Clip da tat tieng va clip chu: khong co gi de tach, va model khong
        # duoc phep tu "bat" lai tieng roi tach — do la doi hanh vi.
        silent = ClipModel(start_time=5.0, duration=1.0, source_path=src,
                           media_type="video", name="Im",
                           track_id=video_track.track_id, audio_muted=True)
        video_track.clips.append(silent)
        if model.detach_audio(silent.clip_id) is not None:
            raise RuntimeError("tach duoc tieng cua clip dang tat tieng")
        model.remove_clip(silent.clip_id)
        text_track = model.add_track(TrackType.TEXT)
        caption = model.add_clip(text_track.track_id, "", "text", 0.0, 1.0, "Chu")
        if model.detach_audio(caption.clip_id) is not None:
            raise RuntimeError("tach duoc tieng cua clip chu")

        stack = UndoStack()
        import copy
        clip_before_detach = copy.deepcopy(clip)
        stack.push(DetachAudioCommand(model, clip.clip_id))
        detached = [c for t in model.tracks if t.track_type == TrackType.AUDIO
                    for c in t.clips]
        if len(detached) != 1:
            raise RuntimeError("khong co dung 1 clip audio sau khi tach: %r"
                               % [(c.name, c.media_type) for c in detached])
        audio = detached[0]
        for field_name in ("start_time", "duration", "in_point", "out_point",
                           "speed_factor", "volume_level", "fade_in",
                           "fade_out"):
            left = getattr(audio, field_name)
            right = getattr(clip, field_name)
            if abs(float(left) - float(right)) > 1e-6:
                raise RuntimeError("lech %s: %.4f vs %.4f"
                                   % (field_name, left, right))
        if audio.source_path != clip.source_path or audio.media_type != "audio":
            raise RuntimeError("clip tach sai loai hoac sai nguon")
        if audio.audio_muted or not clip.audio_muted:
            raise RuntimeError("hai nua cua thao tac khong doi trang thai")
        if audio.track_id != empty_id:
            raise RuntimeError("tieng tach ro khong xuong hang audio co san")

        clips = collect_audio_clips(model)
        if [c.clip_id for c in clips] != [audio.clip_id]:
            raise RuntimeError("export con doc clip video da tach: %r"
                               % [c.name for c in clips])
        graph = build_filter_complex(model, clips, model.duration)
        if "adelay=1500:all=1" not in graph:
            raise RuntimeError("tieng tach ro nhay sai gio: %s" % graph[:200])

        stack.undo()
        after = [c for t in model.tracks if t.track_type == TrackType.AUDIO
                 for c in t.clips]
        if after or clip.audio_muted:
            raise RuntimeError("Ctrl+Z chi tra lai mot nua thao tac")
        if model.get_track(empty_id) is None:
            raise RuntimeError("Ctrl+Z lam mat hang audio trong cua nguoi dung")

        stack.redo()
        redone = [c for t in model.tracks if t.track_type == TrackType.AUDIO
                  for c in t.clips]
        if len(redone) != 1 or abs(redone[0].start_time - 1.5) > 1e-6:
            raise RuntimeError("redo khong dung lai vi tri cu")

        from types import SimpleNamespace

        from ui.graphics.clip_item import ClipItem
        from ui.graphics.timeline_scene import TimelineScene
        from ui.timeline_panel import TimelinePanel

        def detachable(item):
            return ClipItem._detachable_audio_clip(SimpleNamespace(
                clip_model=item))

        missing = [name for name, owner in (
            ("audio_detach_requested", TimelineScene),
            ("_on_detach_audio", TimelinePanel)) if not hasattr(owner, name)]
        if "audio_detach_requested" not in (
                ClipItem.contextMenuEvent.__code__.co_consts):
            missing.append("menu clip khong goi audio_detach_requested")
        # Panel goi thang model thi Ctrl+Z mat nen tach tieng khong hoan tac
        # duoc nua — do la ly do ten lenh phai nam trong code cua chinh handler.
        if "DetachAudioCommand" not in (
                TimelinePanel._on_detach_audio.__code__.co_names):
            missing.append("panel khong push DetachAudioCommand")
        # Dieu kien hien muc menu do ngay tren clip that, khong phai chuoi nguon:
        # muc "Tách âm thanh" phai moc len dung luc clip co tieng that va tat khi
        # tieng da mat — neu khong nguoi dung bam vao mot muc rong.
        if not detachable(clip_before_detach):
            missing.append("menu an muc khi clip co tieng")
        for item, ly_do in ((clip, "da tach va tat tieng"),
                            (audio, "la clip audio"),
                            (ClipModel(source_path=""), "khong co nguon")):
            if detachable(item):
                missing.append("menu hien khi %s" % ly_do)
        if missing:
            raise RuntimeError("diem vao tach tieng bi thieu: %s"
                               % ", ".join(missing))
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return ("1 clip audio trung nguon/trung noi dung, export thay [0:a] "
            "adelay=1500, Ctrl+Z tra lai ca hai nua + giu hang audio trong")


# Thang do cua kho SFX, lay tu lan do 22/10/2026 tren `tools/make_sfx.py` (lan
# build 3: 14 tieng / 181.167 B / 14,15 s tieng, 15/15 sha256[:16] trung voi lan
# chay lien truoc). Day la CUA DO chu khong phai so thich — them mot tieng, doi
# mot bitrate la phai sua day va phai chay lai `--sfx-report` (bẫy "cổng tự chấm"
# trong AGENTS.md: hang so cu theo duoc vao bundle cung chieu loi cat file 1.0.4).
SFX_PACK_ENTRIES = 14
SFX_PACK_GROUPS = 4
SFX_PACK_BYTE_BUDGET = 200_000
SFX_PACK_SECOND_BUDGET = 20.0
# Lan do 22/10/2026 tren chinh pack nay: ffprobe tra ve DUNG con so manifest cho
# ca 14 tieng (`duration_worst_dev` = 0,0) nen do lech = 0 la bang chung tot,
# khong phai dau hieu do hoi. Nguong 0,12 de cho mp3 padding mot lan build khac
# codec; con so nay phai doc tu payload, khong phai tu do luon.
SFX_DURATION_TOL = 0.12
SFX_RMS_TOL = 0.02


def _sfx_audio_row(path):
    """(giay thuc, rms, peak, zcr, sha16) cua mot tieng — do bang ffprobe/ffmpeg
    nhu `tools/make_sfx.py` do, khong tin manifest."""
    import hashlib
    import subprocess

    import numpy as np

    from core import external_tools
    from core.media_splitter import probe_duration

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", path, "-vn", "-ac", "1",
                           "-ar", "8000", "-f", "f32le", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=120, check=False, creationflags=0x08000000)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("ffmpeg khong doc duoc %s" % os.path.basename(path))
    data = np.frombuffer(proc.stdout, np.float32).astype(np.float64)
    if data.size < 8:
        raise RuntimeError("file khong co tieng: %s" % path)
    sign = np.signbit(data[1:]) != np.signbit(data[:-1])
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()[:16]
    return (probe_duration(path), float(np.sqrt(np.mean(data ** 2))),
            float(np.max(np.abs(data))), float(np.mean(sign)), digest)


def _sfx_pack_ok():
    """Mot dong trong --selftest: kho hieu ung am thanh dung san trong app.

    Dong nay tra loi ba cau hoi ma `--sfx-report` tra loi bang ca 22 cua, o day
    bang toi thieu cho mot lan selftest (~1,5 s thay vi 14 lan do file):

    (1) bundle/nguon co thuc su mang theo pack — `core/sfx.py` tim duoc manifest
        va 14 tieng trong manifest co mat tren dia, dung bang so byte da ghi;
    (2) ffprobe doc lai duoc ba tieng dau/giua/cuoi — manifest khong phai la mot
        danh sach tu xuong duoc ve minh;
    (3) chen qua ngan nap that cua timeline (`TimelinePanel._on_resource_dropped`)
        ra clip audio noi lien, mot lane, Ctrl+Z tra ve timeline trong.

    Khong dung MainWindow o day: no thu `--sfx-report`, con selftest phai chay
    duoc tren moi may khong co thiet bi am thanh.
    """
    from types import SimpleNamespace

    from core import sfx as sfx_core
    from ui.sfx_dialog import SfxDialog, insert_to_timeline
    from ui.timeline_panel import TimelinePanel

    rows = sfx_core.entries()
    if not rows:
        raise RuntimeError("khong doc duoc manifest o %s" % sfx_core.pack_dir())
    if len(rows) != SFX_PACK_ENTRIES:
        raise RuntimeError("pack co %d tieng, thang do ghi %d"
                           % (len(rows), SFX_PACK_ENTRIES))
    missing = sfx_core.missing_files()
    if missing:
        raise RuntimeError("thieu file tren dia: %s" % ", ".join(missing))
    wrong_size = [row["key"] for row in rows
                  if os.path.getsize(row["path"]) != int(row["bytes"])]
    if wrong_size:
        raise RuntimeError("byte khop manifest: %s" % ", ".join(wrong_size))
    total = sum(int(row["bytes"]) for row in rows)
    if total > SFX_PACK_BYTE_BUDGET:
        raise RuntimeError("pack %d B vuot ngan sach %d B"
                           % (total, SFX_PACK_BYTE_BUDGET))
    groups = sfx_core.groups()
    if len(groups) != SFX_PACK_GROUPS:
        raise RuntimeError("%d nhom, thang do ghi %d" % (len(groups),
                                                         SFX_PACK_GROUPS))

    for row in (rows[0], rows[len(rows) // 2], rows[-1]):
        seconds, _rms, _peak, _zcr, _sha = _sfx_audio_row(row["path"])
        if seconds <= 0 or abs(seconds - float(row["seconds"])) > SFX_DURATION_TOL:
            raise RuntimeError("%s: ffprobe %.2fs, manifest %.2fs"
                               % (row["key"], seconds, float(row["seconds"])))

    panel = TimelinePanel()
    window = SimpleNamespace(timeline_panel=panel)
    first = insert_to_timeline(window, rows[0])
    second = insert_to_timeline(window, rows[1])
    if first is None or second is None:
        raise RuntimeError("chen khong ra clip")
    clips = [c for t in panel.model.tracks if t.track_type.name == "AUDIO"
             for c in t.clips]
    if len(clips) != 2:
        raise RuntimeError("chen ra %d clip audio thay vi 2" % len(clips))
    overlap = (second.start_time - (first.start_time + first.duration))
    if abs(overlap) > 1e-6:
        raise RuntimeError("hai tieng chong/chenh nhau %.3f s" % overlap)
    audio_tracks = [t for t in panel.model.tracks if t.track_type.name == "AUDIO"]
    if len(audio_tracks) != 1:
        raise RuntimeError("chen tao %d lane audio, ky vong 1" % len(audio_tracks))
    if any(c.media_type != "audio" for c in clips):
        raise RuntimeError("clip chen vao khong phai kieu audio")

    dialog = SfxDialog(panel)
    dialog.refresh()
    if dialog.list.count() != SFX_PACK_ENTRIES:
        raise RuntimeError("hop tho liet %d dong, pack co %d tieng"
                           % (dialog.list.count(), SFX_PACK_ENTRIES))
    want_group = groups[0]
    expect = len([r for r in rows if r.get("group") == want_group])
    dialog.group_combo.setCurrentIndex(dialog.group_combo.findText(want_group))
    if dialog.list.count() != expect or expect >= SFX_PACK_ENTRIES:
        raise RuntimeError("loc nhom %s: %d dong, ky vong %d"
                           % (want_group, dialog.list.count(), expect))
    dialog.group_combo.setCurrentIndex(0)
    needle = (rows[0].get("label") or "")[:3]
    expect = len([r for r in rows if needle.casefold() in
                  ("%s %s %s" % (r.get("label"), r.get("key"),
                                 r.get("group"))).casefold()])
    dialog.search.setText(needle)
    if dialog.list.count() != expect or not expect:
        raise RuntimeError("tim %r: %d dong, ky vong %d"
                           % (needle, dialog.list.count(), expect))
    dialog.search.clear()
    # Pha phai MOI nguon THAT roi moi dung: neu chi goi `stop_preview()` tren
    # mot player chua tung phat thi `source()` rong san va phep thu xanh ma
    # khong do gi (phat hien 22/10 khi phan chung vet `setSource(QUrl())`).
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    dialog.list.setCurrentRow(0)
    dialog.icon_play.click()
    for _ in range(6):
        app.processEvents()
    loaded = not dialog._player.source().isEmpty()
    dialog.icon_play.click()
    for _ in range(4):
        app.processEvents()
    if not loaded:
        raise RuntimeError("bam Nghe thu khong mo duoc nguon audio")
    if not dialog._player.source().isEmpty():
        raise RuntimeError("dung nghe thu ma van giu nguon (file bi khoa)")
    dialog.deleteLater()

    for _ in range(2):
        panel.header.btn_undo.click()
    left = [c for t in panel.model.tracks if t.track_type.name == "AUDIO"
            for c in t.clips]
    if left:
        raise RuntimeError("Ctrl+Z con %d clip audio" % len(left))
    panel.deleteLater()
    return ("%d tieng / %d B / %d nhom, ffprobe khop manifest, "
            "2 clip noi lien tren 1 lane + Ctrl+Z sach"
            % (len(rows), total, len(groups)))


TRANSFORM_BUTTON_LABELS = ("Đặt lại", "Đồng nhất", "−90°", "+90°", "Ngang",
                           "Dọc", "Trái", "Giữa", "Phải", "Trên", "Dưới")
# "Giữa" xuat hien o CA hai hang (ngang/doc) nen so nut nhieu hon so nhan.
TRANSFORM_BUTTON_COUNT = 12   # dat lai + dong nhat + 2 xoay + 2 lat + 6 canh


def _transform_ui_ok():
    """Mot dong trong --selftest: nhom "Bien doi" (xoay, lat, khoa ty le, canh mep).

    Tinh nang theo video mau 22/10: tay nam xoay tu do tren Canvas, mot o
    "Tỷ lệ %" co nut "Đồng nhất", hai nut xoay ±90 goi lai duoi 180, lat
    ngang/doc, sau nut canh mep va mot nut "Đặt lại". Nam xich ma ma ban dong
    goi co the cat trom, do o day bang toi thieu (~2 s, khong ffmpeg):

    (1) ba CO hinh hoc (flip_h / flip_v / uniform_scale) phai co trong model
        voi mac dinh dung (khong lat, CO khoa), tron ven qua .clinq, va file CU
        khong co ba khoa ay van mo duoc khong doi hinh;
    (2) co phai la co: nam NGOAI PROPERTY_ORDER cua do thi keyframe ("lat 40%"
        khong ton tai) va SetClipTransformCommand phai dao nguoc duoc chung;
    (3) goc xoay phai trong (-180, 180] — QTransform va atan2 cua sync_to_model
        chi noi cung mot tieng trong dai do; ngoai ra spin keo 270 ve 180 im
        lang va hai lan doc cho hai goc khac nhau;
    (4) cac phep toan canh mep (rotated_box_size / align_center /
        base_display_size) phai dung, vi canh theo so CHUA xoay lech den 840 px
        tren canvas 1920x1080;
    (5) duong cua nguoi dung that: spin cua bang thuoc tinh di qua funnel
        `_on_properties_changed_by_user`, tay nam Canvas di qua
        `_on_canvas_edit_committed`, mot cu keo = MOT buoc undo, Ctrl+Z tra lai
        dung ca so lan co, va "Đặt lại" tren clip sach khong them buoc rong;
    (6) vung cham cua tay nam nam trong boundingRect TINH CO DONG (bat duoc
        bang `item.contains()` cua chinh Qt) — boundingRect theo goc xoay la
        loi da tra gia truoc day.

    Pixel cua lat/xoay trong FrameComposer do `--transform-report` va
    scratch/transform_evidence.py; o day chi do xich ma.
    """
    import math
    import shutil
    import tempfile
    import types

    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import (QGraphicsScene, QGraphicsSceneMouseEvent,
                                   QPushButton, QWidget)
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from core import keyframe_graph as kg
    from core import project_storage
    from core.canvas_utils import (align_center, apply_auto_fit,
                                   base_display_size, rotated_box_size)
    from core.commands import (GEOMETRY_FLAGS, GEOMETRY_KEYS, UndoStack,
                               SetClipTransformCommand, transform_snapshot)
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType, TransformData
    from ui.graphics_canvas_item import (CanvasClipItem, ROTATE_HIT,
                                        ROTATE_ROOM, _normalize_angle)
    from ui.main_window import MainWindow
    from ui.properties_panel import ClipPropertiesWidget

    TOL = 0.005
    near = lambda a, b: abs(float(a) - float(b)) <= TOL

    def mouse(item, kind, local, scene_pos):
        """Goi dung handler cua item voi toa do that (local + scene), khong
        tu dung mot ban mo phong: CanvasClipItem doc event.pos() de do va
        event.scenePos() de tinh goc. Do PHAI la QGraphicsSceneMouseEvent —
        QMouseEvent khong co scenePos(), nen item that khong doc duoc no."""
        held = (Qt.LeftButton if kind in (QEvent.MouseButtonPress,
                                         QEvent.MouseMove)
                else Qt.NoButton)
        ev = QGraphicsSceneMouseEvent(kind)
        ev.setPos(QPointF(local))
        ev.setScenePos(QPointF(scene_pos))
        ev.setScreenPos(QPoint(int(scene_pos.x()), int(scene_pos.y())))
        ev.setButton(Qt.LeftButton)
        ev.setButtons(held)
        ev.setModifiers(Qt.NoModifier)
        if kind == QEvent.MouseButtonPress:
            item.mousePressEvent(ev)
        elif kind == QEvent.MouseMove:
            item.mouseMoveEvent(ev)
        else:
            item.mouseReleaseEvent(ev)

    def click_button(widget, text):
        """Bam dung nut co nhan `text`; False neu khong tim thay (nut mat ten)."""
        for btn in widget.findChildren(QPushButton):
            if btn.text() == text:
                btn.click()
                return True
        return False

    def drag_rotate(item, clip, delta_deg):
        """Keo tay nam xoay them `delta_deg` do, tra ve goc ma model nhan duoc.

        Toa do lay tu `item.mapToScene`: tay nam da xoay cung item, nen nep
        toa do tu tinh (local + goc) la do mot dau vo nghia — press phai dung
        cho that cua tay nam ngay luc bay gio.
        """
        r = item.rect()
        handle = QPointF(item._rotate_handle_pos())
        centre = QPointF(item.mapToScene(QPointF(r.center())))
        press = QPointF(item.mapToScene(handle))
        radius = math.hypot(press.x() - centre.x(), press.y() - centre.y())
        start = math.degrees(math.atan2(press.y() - centre.y(),
                                        press.x() - centre.x()))
        end = math.radians(start + float(delta_deg))
        move = QPointF(centre.x() + radius * math.cos(end),
                       centre.y() + radius * math.sin(end))
        mouse(item, QEvent.MouseButtonPress, handle, press)
        mouse(item, QEvent.MouseMove, handle, move)
        mouse(item, QEvent.MouseButtonRelease, handle, move)
        return float(clip.transform.rotation)

    # (1) mac dinh cua co ────────────────────────────────────────────────
    fresh = TransformData()
    if (fresh.flip_h, fresh.flip_v, fresh.uniform_scale) != (False, False, True):
        raise RuntimeError("mac dinh co sai: %r (mong khong lat, CO khoa ty le)"
                           % ([fresh.flip_h, fresh.flip_v,
                               fresh.uniform_scale],))

    # (2) co dung ngoai do thi keyframe, lenh hinh hoc biet dao nguoc co ──
    if tuple(GEOMETRY_KEYS) != tuple(kg.PROPERTY_ORDER):
        raise RuntimeError("GEOMETRY_KEYS lech PROPERTY_ORDER: %s vs %s"
                           % (list(GEOMETRY_KEYS), list(kg.PROPERTY_ORDER)))
    if set(GEOMETRY_FLAGS) & set(kg.PROPERTY_ORDER):
        raise RuntimeError("co hinh hoc nam trong do thi keyframe: %s"
                           % sorted(set(GEOMETRY_FLAGS) & set(kg.PROPERTY_ORDER)))
    if tuple(SetClipTransformCommand.FIELDS) != tuple(GEOMETRY_KEYS) + tuple(GEOMETRY_FLAGS):
        raise RuntimeError("SetClipTransformCommand khong bao ca ba co: %s"
                           % list(SetClipTransformCommand.FIELDS))
    # Detector phai phan biet duoc "ghi thang model" va "ghi qua lenh".
    ns = {}
    exec(compile("class W:\n"
                 "    def _on_flip_clicked(self):\n"
                 "        self.clip_model.flip_h = True\n", "<mau>", "exec"), ns)
    if "SetClipTransformCommand" in ns["W"]._on_flip_clicked.__code__.co_names:
        raise RuntimeError("detector co_names khong phan biet duoc ghi thang/qua lenh")

    # (3) dai goc ────────────────────────────────────────────────────────
    out_of_band = [a for a in range(-720, 721, 5)
                   if not (-180.0 < _normalize_angle(a) <= 180.0)]
    if out_of_band:
        raise RuntimeError("_normalize_angle tra goc ngoai (-180,180]: %s"
                           % out_of_band[:4])
    if not near(_normalize_angle(270.0), -90.0) or not near(_normalize_angle(-90.0), -90.0):
        raise RuntimeError("270 khong goi ve -90 (ra %s)"
                           % [_normalize_angle(270.0), _normalize_angle(-90.0)])

    # (4) toan hoc canh mep ───────────────────────────────────────────────
    w90, h90 = rotated_box_size(100.0, 40.0, 90.0)
    if not near(w90, 40.0) or not near(h90, 100.0):
        raise RuntimeError("xoay 90 khong dao truc: %.1fx%.1f" % (w90, h90))
    d45 = rotated_box_size(100.0, 40.0, 45.0)
    want45 = (100.0 + 40.0) / math.sqrt(2.0)
    if not near(d45[0], want45) or not near(d45[1], want45):
        raise RuntimeError("hop bao 45 do sai: %.1fx%.1f (mong %.1f)"
                           % (d45[0], d45[1], want45))
    if rotated_box_size(100.0, 40.0, -135.0) != rotated_box_size(100.0, 40.0, 135.0):
        raise RuntimeError("hop bao doi chieu theo dau goc (canh meo lat chen)")
    if align_center(1920, 960, "start") != -480.0 or align_center(1920, 960, "end") != 480.0:
        raise RuntimeError("canh mep sai: %s / %s"
                           % (align_center(1920, 960, "start"),
                              align_center(1920, 960, "end")))
    if align_center(1920, 960, "center") != 0.0 or align_center(1920, 960, "rac") != 0.0:
        raise RuntimeError("canh giua hoac chu la khong tra ve 0.0")

    folder = os.path.join(tempfile.gettempdir(), "clinging_transform")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    seed = os.path.join(folder, "nen.png")
    img = QImage(960, 540, QImage.Format.Format_RGB32)
    img.fill(QColor("#3AA0FF"))
    if not img.save(seed):
        raise RuntimeError("khong tao duoc anh fixture trong %s" % folder)

    real_recovery = project_storage.RECOVERY_DIR
    project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")
    host = None
    try:
        # (1)+(2) vong doi .clinq cua sau so + ba co, va file cu thieu co ──
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, seed, "image", 0.0, 2.0,
                              name="Bien doi")
        if clip is None:
            raise RuntimeError("add_clip tra None (track/media khong khop)")
        want = {"x": -100.0, "y": 60.0, "scale_x": 0.5, "scale_y": 0.25,
                "rotation": -135.0, "opacity": 1.0, "flip_h": True,
                "flip_v": False, "uniform_scale": False}
        model.update_clip_properties(clip.clip_id, **want)

        path = os.path.join(folder, "gate.clinq")
        if not project_storage.save_project_to_file(model, path):
            raise RuntimeError("khong luu duoc gate.clinq")
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        restored_model = TimelineModel()
        project_storage.restore_model_from_clinq(restored_model, data,
                                                media_roots=[folder])
        reopened = [c for t in restored_model.tracks for c in t.clips]
        if len(reopened) != 1:
            raise RuntimeError("mo du an ra %d clip, mong 1" % len(reopened))
        back = reopened[0].transform
        leeway = [k for k, v in want.items()
                  if isinstance(v, bool) and bool(getattr(back, k)) != v]
        leeway += [k for k, v in want.items()
                   if not isinstance(v, bool)
                   and not near(getattr(back, k, 0.0), v)]
        if leeway:
            raise RuntimeError("luu mo lech o %s" % sorted(set(leeway)))
        if not isinstance(back.flip_h, bool) or not isinstance(back.uniform_scale, bool):
            raise RuntimeError("co bi bien thanh so khi doc lai: %r %r"
                               % (back.flip_h, back.uniform_scale))

        legacy = project_storage.serialize_transform(back)
        for key in GEOMETRY_FLAGS:
            legacy.pop(key, None)
        old_t = TransformData()
        project_storage.deserialize_transform(legacy, old_t)
        if (old_t.flip_h, old_t.flip_v, old_t.uniform_scale) != (False, False, True):
            raise RuntimeError("file cu bi gan co la: %r"
                               % [old_t.flip_h, old_t.flip_v, old_t.uniform_scale])
        if not near(old_t.rotation, -135.0):
            raise RuntimeError("file cu mat goc xoay: %s" % old_t.rotation)

        # (2) vong doi undo cua co ─────────────────────────────────────────
        stack = UndoStack()
        snap = transform_snapshot(clip)
        stack.push(SetClipTransformCommand(model, clip.clip_id, flip_h=False,
                                           uniform_scale=True))
        if (clip.transform.flip_h, clip.transform.uniform_scale) != (False, True):
            raise RuntimeError("lenh co khong ap: %r" % [clip.transform.flip_h,
                                                         clip.transform.uniform_scale])
        stack.undo()
        if transform_snapshot(clip) != snap:
            raise RuntimeError("Ctrl+Z khong tra lai dung co: %r vs %r"
                               % (transform_snapshot(clip), snap))
        if not isinstance(clip.transform.flip_h, bool):
            raise RuntimeError("undo bien co thanh %s" % type(clip.transform.flip_h).__name__)
        stack.redo()
        if clip.transform.flip_h is not False:
            raise RuntimeError("Ctrl+Y khong dat lai duoc co")
        while stack.undo_count:
            stack.undo()

        # (4) mot nguon kich thuoc cho ca ba ben ───────────────────────────
        apply_auto_fit(clip, 1920, 1080)
        base = base_display_size(clip, 1920, 1080)
        if not near(base[0], 1920.0) or not near(base[1], 1080.0):
            raise RuntimeError("base_display_size khong tra hop da fit: %s"
                               % (tuple(round(v, 1) for v in base),))

        # (6) tay nam xoay tren Canvas ────────────────────────────────────
        scene = QGraphicsScene()
        scene.setSceneRect(-960.0, -540.0, 1920.0, 1080.0)
        host = QWidget()
        host.setObjectName("MainWindow")
        host.timeline_panel = types.SimpleNamespace(
            model=model, undo_stack=stack,
            header=types.SimpleNamespace(combo_aspect_ratio=types.SimpleNamespace(
                currentText=lambda: "16:9 - Ngang chuẩn")))
        host.preview_panel = types.SimpleNamespace(
            canvas=types.SimpleNamespace(_clip_items={}))

        def on_commit(clip_model, kind, values, before=None):
            MainWindow._on_canvas_edit_committed(host, clip_model, kind,
                                                 values, before)

        model.update_clip_properties(clip.clip_id, rotation=0.0, x=-100.0,
                                     y=60.0, scale_x=0.5, scale_y=0.5,
                                     flip_h=False, flip_v=False)
        item = CanvasClipItem(clip, lambda c: None, on_commit)
        scene.addItem(item)
        apply_auto_fit(clip, 1920, 1080)
        item.sync_from_model()

        handle = item._rotate_handle_pos()
        rect = item.rect()
        if not handle.y() < rect.top():
            raise RuntimeError("tay nam khong o tren mep khung: y=%.1f vs top=%.1f"
                               % (handle.y(), rect.top()))
        if handle.x() != rect.center().x():
            raise RuntimeError("tay nam lech truc ngang khung: %s vs %s"
                               % (handle.x(), rect.center().x()))
        br = item.boundingRect()
        if br.top() > handle.y() - ROTATE_HIT:
            raise RuntimeError("vung xoay tron ngoai boundingRect: top=%.1f handle=%.1f"
                               % (br.top(), handle.y()))
        if not item.contains(QPointF(handle)):
            raise RuntimeError("Qt khong hit-test duoc tay nam (shape thieu vung xoay)")
        if item.contains(QPointF(handle.x(), handle.y() - ROTATE_HIT - 40.0)):
            raise RuntimeError("shape mo rong vo han, click loai bo cung duoc chon")

        before_geo = (clip.transform.x, clip.transform.y, clip.transform.scale_x,
                      clip.transform.scale_y)
        got = drag_rotate(item, clip, 45.0)
        if not near(got, 45.0):
            raise RuntimeError("keo tay nam +45 do ra goc %.2f trong model" % got)
        if (clip.transform.x, clip.transform.y) != before_geo[:2]:
            raise RuntimeError("keo xoay lam dich clip: %r -> %r"
                               % (before_geo[:2], (clip.transform.x,
                                                    clip.transform.y)))
        if not near(clip.transform.scale_x, before_geo[2]) or not near(
                clip.transform.scale_y, before_geo[3]):
            raise RuntimeError("keo xoay lam doi ty le clip: %r"
                               % [clip.transform.scale_x, clip.transform.scale_y])
        if stack.undo_count != 1:
            raise RuntimeError("mot cu xoay tao %d buoc undo, mong 1" % stack.undo_count)
        stack.undo()
        if abs(clip.transform.rotation) > TOL or stack.undo_count != 0:
            raise RuntimeError("Ctrl+Z khong tra ve goc 0 (con %.2f)"
                               % clip.transform.rotation)
        # boundingRect PHAI tinh co dong: no theo goc xoay thi Qt don vung sai
        # va de lai mo duoi tay nam (loi da tra gia).
        model.update_clip_properties(clip.clip_id, rotation=135.0, flip_h=True)
        item.sync_from_model()
        if item.boundingRect() != br:
            raise RuntimeError("boundingRect doi theo trang thai: %s -> %s"
                               % (br, item.boundingRect()))

        # (3) quay qua 180 van trong dai + item/model cung mot tieng ───────
        model.update_clip_properties(clip.clip_id, rotation=135.0, flip_h=False)
        item.sync_from_model()
        wrapped = drag_rotate(item, clip, 90.0)
        if not -180.0 < wrapped <= 180.0:
            raise RuntimeError("keo vuot 180 de lai goc %.2f ngoai dai" % wrapped)
        if not near(wrapped, -135.0):
            raise RuntimeError("keo 135+90 phai goi ve -135, ra %.2f" % wrapped)
        m = item.transform()
        same = math.degrees(math.atan2(m.m12(), m.m11()))
        if not near(same, clip.transform.rotation):
            raise RuntimeError("item va model khong cung goc: %.2f vs %.2f"
                               % (same, clip.transform.rotation))
        while stack.undo_count:
            stack.undo()
        # Gim model ve MOT trang thai biet truoc truoc khi mo the: cac vong undo
        # tren day tra lai co uniform_scale=False (cat tir phep luu .clinq), va
        # panel dung khoa/mo theo dung co do — do lech la do gate, khong phai UI.
        model.update_clip_properties(clip.clip_id, rotation=0.0, x=0.0, y=0.0,
                                     scale_x=1.0, scale_y=1.0, flip_h=False,
                                     flip_v=False, uniform_scale=True)
        item.sync_from_model()

        # (5) bang thuoc tinh ─────────────────────────────────────────────
        editor = ClipPropertiesWidget(clip, parent=host)
        editor.propertyChanged.connect(
            lambda *a: MainWindow._on_properties_changed_by_user(host, *a))
        if stack.undo_count != 0:
            raise RuntimeError("mo the Bien doi da tao %d buoc undo rong"
                               % stack.undo_count)

        # Do PHAI trong pham vi the Bien doi: ca bang thuoc tinh co them hang
        # "Canh le" cua chu (Trái/Giữa/Phải cho text_align), nam trong the
        # "Style chu" — tinh ca editor thi bo dem nhan doi va do oan.
        card = editor.card_transform
        new_btns = ([editor.btn_transform_reset, editor.chk_uniform]
                    + list(editor._flip_buttons.values()))
        if any(b not in card.findChildren(QPushButton) for b in new_btns):
            raise RuntimeError("nut Dat lại/Dong nhat/lat nam ngoai the Bien doi")
        rot_btns = [b for b in card.findChildren(QPushButton)
                    if b.text() in ("−90°", "+90°")]
        align_btns = [b for b in card.findChildren(QPushButton)
                      if b.text() in ("Trái", "Giữa", "Phải", "Trên", "Dưới")]
        got_labels = sorted([b.text() for b in new_btns]
                            + [b.text() for b in rot_btns]
                            + [b.text() for b in align_btns])
        # "Giữa" ca hai hang nen thang do ghi 12 nut, khong phai 11 nhan khac.
        want_labels = sorted(list(TRANSFORM_BUTTON_LABELS) + ["Giữa"])
        if got_labels != want_labels:
            raise RuntimeError("bo nut Bien doi lech: %s (thang do ghi %d nut)"
                               % (got_labels, TRANSFORM_BUTTON_COUNT))
        if len(new_btns) + len(rot_btns) + len(align_btns) != TRANSFORM_BUTTON_COUNT:
            raise RuntimeError("the co %d nut moi, thang do ghi %d"
                               % (len(new_btns) + len(rot_btns) + len(align_btns),
                                  TRANSFORM_BUTTON_COUNT))
        if len(editor._flip_buttons) != 2 or editor.chk_uniform is None:
            raise RuntimeError("nut lat/khoa khong duoc ghi nho de doc lai model")
        if editor.spin_rotation.minimum() != -180.0 or editor.spin_rotation.maximum() != 180.0:
            raise RuntimeError("spin goc khong o dai (-180,180]: %s..%s"
                               % (editor.spin_rotation.minimum(),
                                  editor.spin_rotation.maximum()))
        if not near(editor.spin_scale_pct.value(), 100.0):
            raise RuntimeError("% hien thi %.1f trong khi scale_x = 1.0"
                               % editor.spin_scale_pct.value())

        # Khoa: % ghi ca hai truc, va mot lan nhap = MOT lenh. Nhung phep do ke
        # tiep KHONG duoc so buoc undo: SetClipTransformCommand.merge trong 0,75 s
        # gop hai lan bam thanh mot buoc (dung y cua nguoi dung), ma 0,75 s do
        # lech theo toc do may — nen o day chi do NOI DUNG, con "toan bo ve duoc
        # trang thai goc" do bang vong undo ben duoi.
        baseline = transform_snapshot(clip)
        editor.spin_scale_pct.setValue(150.0)
        if not (near(clip.transform.scale_x, 1.5) and near(clip.transform.scale_y, 1.5)):
            raise RuntimeError("nhap 150%% ra %r (hai truc phai bang nhau)"
                               % [clip.transform.scale_x, clip.transform.scale_y])
        if stack.undo_count != 1:
            raise RuntimeError("mot lan nhap % tao %d buoc undo" % stack.undo_count)
        if editor.spin_scale_x.isEnabled() or not editor.spin_scale_pct.isEnabled():
            raise RuntimeError("khoa dong ma van cho nhap tung truc")
        editor.chk_uniform.click()
        if not editor.spin_scale_x.isEnabled() or editor.spin_scale_pct.isEnabled():
            raise RuntimeError("mo khoa roi ma spin truc van bi chan")
        if clip.transform.uniform_scale is not False:
            raise RuntimeError("mo khoa khong ghi co len model")
        editor.spin_scale_x.setValue(0.8)
        if not near(clip.transform.scale_x, 0.8) or near(clip.transform.scale_y, 0.8):
            raise RuntimeError("khoa mo thi hai truc phai doc lap: %r"
                               % [clip.transform.scale_x, clip.transform.scale_y])
        editor.chk_uniform.click()
        editor.spin_scale_pct.setValue(100.0)

        # Xoay ±90 goi lai duoi 180, khong dung chot o mep dai.
        editor.spin_rotation.setValue(135.0)
        if not near(clip.transform.rotation, 135.0):
            raise RuntimeError("spin goc khong ghi duoc model: %s"
                               % clip.transform.rotation)
        editor._flip_buttons["flip_h"].click()
        if clip.transform.flip_h is not True:
            raise RuntimeError("nut lat khong ghi co len model")
        if not click_button(editor, "+90°"):
            raise RuntimeError("khong tim thay nut +90° trong the Bien doi")
        # 135 + 90 = 225 phai goi thanh -135; neu de spin tu kep thi no dung
        # lai o 180 va nut "+90°" khong con quay toi dau.
        if not near(clip.transform.rotation, -135.0):
            raise RuntimeError("135 + 90 ra %.1f, mong -135 (goi nguoc hay kep?)"
                               % clip.transform.rotation)
        if not click_button(editor, "−90°"):
            raise RuntimeError("khong tim thay nut -90 trong the Bien doi")
        if not near(clip.transform.rotation, 135.0):
            raise RuntimeError("-90 tu -135 ra %.1f, mong 135"
                               % clip.transform.rotation)
        while stack.undo_count:
            stack.undo()
        if transform_snapshot(clip) != baseline:
            raise RuntimeError("undo khong ve duoc trang thai goc: %r vs %r"
                               % (transform_snapshot(clip), baseline))

        # Canh mep tren clip xoay 90: phai dung hop BAO, khong dung rect chua xoay.
        model.update_clip_properties(clip.clip_id, rotation=90.0, x=0.0, y=0.0,
                                     scale_x=0.5, scale_y=0.5, flip_h=False,
                                     uniform_scale=True)
        editor.update_values(clip)
        click_button(editor, "Trái")
        # 1920x1080 da fit, scale 0.5 -> 960x540; xoay 90 -> hop bao rong 540;
        # canh trai = -960 + 270 = -690. Canh theo 960 (chua xoay) ra -480.
        if not near(clip.transform.x, -690.0):
            raise RuntimeError("canh trai khi xoay 90 ra x=%.1f, mong -690.0"
                               % clip.transform.x)
        click_button(editor, "Dưới")
        # Hop bao cao 960 tren canvas 1080 -> canh duoi = 540 - 480 = 60.
        if not near(clip.transform.y, 60.0):
            raise RuntimeError("canh duoi khi xoay 90 ra y=%.1f, mong 60.0"
                               % clip.transform.y)
        click_button(editor, "Giữa")
        while stack.undo_count:
            stack.undo()

        # "Đặt lại": sach moi thu, MOT buoc (stack con trong luc bam), va Ctrl+Z
        # tra lai dung so cu — ke ca ba co.
        model.update_clip_properties(clip.clip_id, x=-300.0, y=120.0,
                                     scale_x=1.7, scale_y=0.4, rotation=-100.0,
                                     flip_h=True, flip_v=True, uniform_scale=False)
        editor.update_values(clip)
        saved = transform_snapshot(clip)
        if stack.undo_count:
            raise RuntimeError("stack khong trong truoc khi do Dat lai: %d"
                               % stack.undo_count)
        editor.btn_transform_reset.click()
        clean = {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0,
                 "rotation": 0.0, "flip_h": False, "flip_v": False,
                 "uniform_scale": True}
        bad = []
        for key, value in clean.items():
            got = getattr(clip.transform, key)
            if isinstance(value, bool):
                if bool(got) != value:
                    bad.append(key)
            elif not near(got, value):
                bad.append(key)
        if bad:
            raise RuntimeError("Dat lai con sot %s" % sorted(bad))
        if stack.undo_count != 1:
            raise RuntimeError("Dat lai tao %d buoc, mong 1" % stack.undo_count)
        if not near(editor.spin_scale_pct.value(), 100.0) or editor.spin_rotation.value() != 0.0:
            raise RuntimeError("spin khong doc lai sau khi Dat lai: %s / %s"
                               % (editor.spin_scale_pct.value(),
                                  editor.spin_rotation.value()))
        editor.btn_transform_reset.click()
        if stack.undo_count != 1:
            raise RuntimeError("Dat lai tren clip da sach them buoc rong (%d)"
                               % stack.undo_count)
        stack.undo()
        if transform_snapshot(clip) != saved:
            raise RuntimeError("Ctrl+Z sau Dat lai khong tra lai du so cu")
        editor.update_values(clip)
        if not near(editor.spin_scale_pct.value(), 170.0):
            raise RuntimeError("the khong doc lai %% sau undo (%.1f)"
                               % editor.spin_scale_pct.value())
        while stack.undo_count:
            stack.undo()

        # File cu (goc 0..360) phai goi khi doc, khong bi spin kep tham lang.
        model.update_clip_properties(clip.clip_id, rotation=270.0)
        editor.update_values(clip)
        if not near(editor.spin_rotation.value(), -90.0):
            raise RuntimeError("goc cu 270 doc thanh %.1f (kep 180 la mat 90 do)"
                               % editor.spin_rotation.value())
        model.update_clip_properties(clip.clip_id, rotation=0.0)

        # Clip chu khong co khung hinh: nut lat/canh/%/Dat lai khong duoc xuat hien.
        text_track = model.add_track(TrackType.TEXT)
        text_clip = model.add_clip(text_track.track_id, "", "text", 0.0, 2.0,
                                   name="Chu")
        text_editor = ClipPropertiesWidget(text_clip, parent=host)
        for attr in ("chk_uniform", "spin_scale_pct", "btn_transform_reset"):
            if hasattr(text_editor, attr):
                raise RuntimeError("clip chu co %s: khong co khung hinh de lat/canh"
                                   % attr)
        if getattr(text_editor, "_flip_buttons", {}):
            raise RuntimeError("clip chu co nut lat")
        # Chi quet trong the Bien doi: hang "Canh le" cua chu (Trái/Giữa/Phải)
        # song ở the Style chu va la dieu khung HOP LE o do.
        text_labels = [b.text() for b in text_editor.card_transform
                       .findChildren(QPushButton)]
        stray = [name for name in ("Đặt lại", "Đồng nhất", "Trái", "Ngang")
                 if name in text_labels]
        if stray:
            raise RuntimeError("clip chu con nut %s" % ", ".join(stray))

        # Seam dung chung preview/export + mot nguon kich thuoc (co_names).
        seams = (
            ("FrameComposer._draw_media", FrameComposer._draw_media,
             ("flip_h", "flip_v")),
            ("FrameComposer._base_size", FrameComposer._base_size,
             ("base_display_size",)),
            ("CanvasClipItem.paint", CanvasClipItem.paint,
             ("flip_h", "flip_v")),
            ("CanvasClipItem.mouseMoveEvent", CanvasClipItem.mouseMoveEvent,
             ("uniform_scale", "_apply_rotation")),
            ("CanvasClipItem.mousePressEvent", CanvasClipItem.mousePressEvent,
             ("_hit_test_rotate",)),
            ("CanvasClipItem.boundingRect", CanvasClipItem.boundingRect,
             ("ROTATE_ROOM",)),
            ("ClipPropertiesWidget._on_align_clicked",
             ClipPropertiesWidget._on_align_clicked,
             ("base_display_size", "rotated_box_size", "align_center")),
            ("ClipPropertiesWidget._on_transform_reset",
             ClipPropertiesWidget._on_transform_reset,
             ("SetClipTransformCommand", "transform_snapshot")),
            ("ClipPropertiesWidget._push_transform_flags",
             ClipPropertiesWidget._push_transform_flags,
             ("SetClipTransformCommand",)),
        )
        for label, fn, helpers in seams:
            code = fn.__code__
            # Lat/xoay doc qua getattr(transform, "flip_h") nen ten nam trong
            # hang so (co_consts), khong phai co_names — tinh ca hai, vet nao
            # bi xoa khoi ca hai la do.
            names = set(code.co_names) | {c for c in code.co_consts
                                          if isinstance(c, str)}
            miss = [h for h in helpers if h not in names]
            if miss:
                raise RuntimeError("%s thieu %s (hai ben khong con dung chung duong)"
                                   % (label, ", ".join(miss)))
        # Do luong tren la do bang TEN: thu vet ten xem no co do that khong.
        fake = compile("def f():\n    return align_center(1, 2)\n", "<cf>", "exec")
        canary = {}
        exec(fake, canary)
        if "align_center" not in set(canary["f"].__code__.co_names):
            raise RuntimeError(" detector co_names khong bat duoc ten ham goi "
                               "(seam do trong bang tren la gia)")
    finally:
        project_storage.RECOVERY_DIR = real_recovery
        if host is not None:
            host.deleteLater()
        shutil.rmtree(folder, ignore_errors=True)
    return ("3 co trong model + .clinq + undo, goc trong (-180,180], "
            "12 nut Bien doi, xoay/lat/canh dat do tren widget that")


def _trim_card_ok():
    """Mot dong trong --selftest: the "Cat" (in/out giay cua nguon) trong bang thuoc tinh.

    Do tren chinh ClipPropertiesWidget: so duoc ghi vao spin nhu nguoi dung ghi,
    lenh di qua undo_stack that cua panel. Bon dieu bat buoc:

    (1) In/Out do bang giay CUA NGUON con duration do bang giay timeline, nen moi
        phep quy doi phai chia cho toc do - clip 2x ma cong tru thang thi keo 1
        giay nguon nhat mat 2 giay thanh;
    (2) meg trai khong duoc lo nguon truoc giay 0 - cung tran ma handle keo dang
        dung (ui/graphics/clip_item.py:614);
    (3) cat tren Main Storyline la ripple: clip sau phai di theo meg vua thay;
    (4) mot lan doi so = mot buoc undo, Ctrl+Z tra lai du ca start_time lan goc.

    Gate phai do khi co thu de cat: clip chu khong co cua so nguon thi the PHAI
    an, hien cho no la UI noi doi va phep quy doi o tren vo nghia.
    """
    import subprocess
    import tempfile
    import types

    from PySide6.QtWidgets import QWidget
    from core import external_tools
    from core.audio_mix import build_filter_complex, collect_audio_clips
    from core.commands import TrimClipCommand, UndoStack
    from core.timeline_model import ClipModel, TimelineModel, TrackType
    from ui.properties_panel import ClipPropertiesWidget

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    folder = tempfile.mkdtemp(prefix="clinging_trim_")
    try:
        src = os.path.join(folder, "nguon.mp4")
        subprocess.run(
            [ffmpeg, "-v", "error", "-y",
             "-f", "lavfi", "-i",
             "testsrc2=size=160x120:rate=25:duration=6",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
             "-shortest", src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
            check=False, creationflags=0x08000000)
        if not os.path.isfile(src):
            raise RuntimeError("khong tao duoc video co tieng de do")

        model = TimelineModel()
        for old in list(model.tracks):
            model.remove_track(old.track_id)
        spine = model.add_track(TrackType.VIDEO)
        if not spine.is_main_track:
            raise RuntimeError("hang VIDEO dau khong phai Main Storyline")
        overlay = model.add_track(TrackType.VIDEO)

        def media_clip(track, start, duration, in_point, speed, name):
            clip = ClipModel(start_time=start, duration=duration,
                             source_path=src, media_type="video", name=name,
                             in_point=in_point, source_duration=6.0,
                             track_id=track.track_id)
            clip.speed = speed
            clip.refresh_out_point()
            track.clips.append(clip)
            model.recalculate_project_duration()
            model.clipAdded.emit(clip)
            return clip

        # Clip do nam tren Overlay de start_time vo sinh: tren truc chinh thi ripple
        # keo no ve 0 va khong con gi de phan biet phep chia toc do.
        subject = media_clip(overlay, 2.0, 2.0, 1.0, 2.0, "Cat")
        if abs(subject.out_point - 5.0) > 1e-6:
            raise RuntimeError("fixture sai of so nguon: %.3f" % subject.out_point)

        host = QWidget()
        host.setObjectName("MainWindow")
        stack = UndoStack()
        host.timeline_panel = types.SimpleNamespace(
            model=model, undo_stack=stack,
            scene=types.SimpleNamespace(_clip_items={}))
        editor = ClipPropertiesWidget(subject, parent=host)

        if editor.card_trim.isHidden():
            raise RuntimeError("the Cat an khi clip co nguon that")
        got = (editor.spin_trim_in.value(), editor.spin_trim_out.value(),
               editor.lbl_trim_duration.text())
        if got != (1.0, 5.0, "2.00 s"):
            raise RuntimeError("the Cat doc sai cua so nguon: %r" % (got,))
        # Tran duoi 0,1 s: do In toi da van phai con cho clip mot do dai dung
        # duoc, neu khong spin mo cho phep cat clip ve 0 giay.
        if not (editor.spin_trim_in.maximum() < subject.out_point
                and editor.spin_trim_out.minimum() > subject.in_point):
            raise RuntimeError("spin cho phep clip rong 0 giay")
        bounds = editor._trim_bounds(subject)
        # 1,0 giay nguon o do In = 0,5 giay o do duration: bo bon so nay la phan
        # chia cho toc do bi bo.
        if tuple(round(v, 3) for v in bounds) != (0.0, 4.8, 1.2, 6.0):
            raise RuntimeError("dai In/Out khong dung: %r"
                               % (tuple(round(v, 3) for v in bounds),))

        editor.spin_trim_out.setValue(3.0)
        geom = (subject.start_time, subject.duration, subject.in_point,
                subject.out_point)
        if geom != (2.0, 1.0, 1.0, 3.0) or stack.undo_count != 1:
            raise RuntimeError("cat cuoi sai tren clip 2x: %r (buoc %d)"
                               % (geom, stack.undo_count))
        editor.spin_trim_in.setValue(2.0)
        geom = (subject.start_time, subject.duration, subject.in_point,
                subject.out_point)
        # Cat dau giu nguyen meg phai: out van 3,0 trong khi start nhich 0,5.
        if geom != (2.5, 0.5, 2.0, 3.0) or stack.undo_count != 2:
            raise RuntimeError("cat dau khong giu meg phai: %r (buoc %d)"
                               % (geom, stack.undo_count))

        clips = collect_audio_clips(model)
        graph = build_filter_complex(model, clips, model.duration)
        if "atrim=start=2.000000:duration=1.000000" not in graph:
            raise RuntimeError("export cat sai doan nguon: %s" % graph[:220])
        if "adelay=2500:all=1" not in graph:
            raise RuntimeError("tieng chay sai gio sau khi cat dau: %s"
                               % graph[:220])

        stack.undo()
        if (subject.start_time, subject.duration, subject.in_point,
                subject.out_point) != (2.0, 1.0, 1.0, 3.0):
            raise RuntimeError("Ctrl+Z khong tra lai net cat dau")
        stack.undo()
        if (subject.start_time, subject.duration, subject.in_point,
                subject.out_point) != (2.0, 2.0, 1.0, 5.0):
            raise RuntimeError("Ctrl+Z khong tra lai net cat cuoi")
        stack.redo()
        if abs(subject.duration - 1.0) > 1e-6:
            raise RuntimeError("Ctrl+Y khong lam lai duoc net cat")

        # Mot nac cua spin tren clip 4x doi 0,0025 s timeline: du nho de model ap
        # nhung khong du cho mot buoc undo - do la ly do _apply_trim chan so.
        fast = media_clip(overlay, 0.0, 1.0, 0.0, 4.0, "Nhanh")
        fast_editor = ClipPropertiesWidget(fast, parent=host)
        before = (stack.undo_count, fast.in_point, fast.duration)
        fast_editor.spin_trim_in.setValue(fast_editor.spin_trim_in.value() + 0.01)
        if (stack.undo_count, fast.in_point, fast.duration) != before:
            raise RuntimeError("mot nac 0,01s tren clip 4x tao buoc undo gia")

        # Meg trai khong phai luc nao cung ve 0: clip co in_point lon hon
        # start_time*speed bi chan ngay giay 0 cua NGUON, va do le do la phep
        # nhan speed trong _trim_bounds. Clip nay keo ve het thi In = 2,0 chu
        # khong phai 2,5, con start_time ve tan 0,0.
        tight = media_clip(overlay, 0.5, 1.0, 3.0, 2.0, "Sat")
        tight_editor = ClipPropertiesWidget(tight, parent=host)
        bounds = tuple(round(v, 3) for v in tight_editor._trim_bounds(tight))
        if bounds != (2.0, 4.8, 3.2, 6.0):
            raise RuntimeError("meg trai toi da tinh sai vi chia toc do: %r"
                               % (bounds,))
        tight_editor.spin_trim_in.setValue(2.0)
        geom = (tight.start_time, tight.duration, tight.in_point,
                tight.out_point)
        if geom != (0.0, 1.5, 2.0, 5.0):
            raise RuntimeError("cat toi meg trai khong lo duoc toan bo nguon: %r"
                               % (geom,))

        # Track khoa: resize_clip tu choi im lang, lenh khong duoc ghi nhan la da
        # ap - neu khong undo se ghi nguoc mot hinh hoc chua tung duoc ap.
        overlay.is_locked = True
        geom_before = (subject.start_time, subject.duration, subject.in_point)
        editor.spin_trim_out.setValue(editor.spin_trim_out.value() - 0.5)
        cmd = stack._undo_stack[-1]
        if (subject.start_time, subject.duration, subject.in_point) != geom_before:
            raise RuntimeError("track khoa ma the Cat van ghi duoc")
        if not isinstance(cmd, TrimClipCommand) or cmd._applied:
            raise RuntimeError("lenh cat tren track khoa bi tinh la da ap")
        stack.undo()
        if (subject.start_time, subject.duration, subject.in_point) != geom_before:
            raise RuntimeError("Ctrl+Z pha hinh hoc clip tren track khoa")
        overlay.is_locked = False
        while stack.undo_count:
            stack.undo()

        # Ripple Main Storyline: cat dau clip A thi clip B phai bo theo meg moi,
        # va Ctrl+Z phai keo B ve cho cu.
        a = media_clip(spine, 0.0, 3.0, 0.0, 1.0, "A")
        b = media_clip(spine, 3.0, 3.0, 3.0, 1.0, "B")
        a_editor = ClipPropertiesWidget(a, parent=host)
        a_editor.spin_trim_in.setValue(1.0)
        if (a.duration, a.start_time, b.start_time) != (2.0, 0.0, 2.0):
            raise RuntimeError("cat tren truc chinh khong ripple: A=%.2f@%.2f B=%.2f"
                               % (a.duration, a.start_time, b.start_time))
        stack.undo()
        if (a.duration, b.start_time) != (3.0, 3.0):
            raise RuntimeError("Ctrl+Z khong tra lai ripple tren truc chinh")

        # Hai nut "Cat tai Playhead": playhead nam trong clip thi meg ben kia phai
        # giu nguyen; nam ngoai thi khong duoc them buoc nao.
        while stack.undo_count:
            stack.undo()
        tail = media_clip(overlay, 0.0, 4.0, 0.0, 1.0, "Duoi")
        tail_editor = ClipPropertiesWidget(tail, parent=host)
        steps = stack.undo_count
        model.playhead = 1.0
        tail_editor.btn_trim_head.click()
        if (tail.start_time, tail.duration, tail.in_point) != (1.0, 3.0, 1.0):
            raise RuntimeError("nut cat dau khong lay dung playhead")
        model.playhead = 2.0
        tail_editor.btn_trim_tail.click()
        if (tail.start_time, tail.duration, tail.in_point,
                tail.out_point) != (1.0, 1.0, 1.0, 2.0):
            raise RuntimeError("nut cat cuoi khong giu meg trai")
        if stack.undo_count != steps + 2:
            raise RuntimeError("hai nut cat tao %d buoc undo"
                               % (stack.undo_count - steps))
        model.playhead = 9.0
        before = (stack.undo_count, tail.start_time, tail.duration)
        tail_editor.btn_trim_head.click()
        tail_editor.btn_trim_tail.click()
        if (stack.undo_count, tail.start_time, tail.duration) != before:
            raise RuntimeError("playhead ngoai clip ma van cat")

        # Clip chu: khong co cua so nguon thi the phai an.
        text_track = model.add_track(TrackType.TEXT)
        caption = model.add_clip(text_track.track_id, "", "text", 0.0, 3.0, "Chu")
        if not ClipPropertiesWidget(caption, parent=host).card_trim.isHidden():
            raise RuntimeError("the Cat hien cho clip chu khong co nguon")

        missing = []
        if "card_trim" not in ClipPropertiesWidget.__init__.__code__.co_names:
            missing.append("__init__ khong dung the Cat")
        if "_sync_trim_card" not in (
                ClipPropertiesWidget.update_values.__code__.co_names):
            missing.append("update_values khong doc lai the Cat")
        for method in ("_apply_trim", "_trim_at_playhead"):
            code = getattr(ClipPropertiesWidget, method).__code__.co_names
            if "_push_trim" not in code:
                missing.append("%s khong di qua lenh" % method)
            if "resize_clip" in code:
                missing.append("%s goi thang model.resize_clip" % method)
        if "TrimClipCommand" not in (
                ClipPropertiesWidget._push_trim.__code__.co_names):
            missing.append("_push_trim khong push TrimClipCommand")
        if missing:
            raise RuntimeError("diem vao the cat bi thieu: %s" % ", ".join(missing))
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return ("cat tren clip 2x: in=2.0 dur=0.5@2.5s, export thay atrim=start=2.0 "
            "duration=1.0 + adelay=2500, ripple keo clip sau ve 2.0, Ctrl+Z 4/4")


def _export_range_ok():
    """Mot dong trong --selftest: xuat theo VUNG in/out + preset chat luong,
    do tren FILE mp4 that.

    Nam cau hoi ma khong probe nao khac tra loi duoc:
      (1) doan 1,2->2,4 s cua mot du an 2,4 s co ra file 1,2 s doc lai duoc
          khong, khi doan do KHONG CO TIENG — day chinh la noi `-shortest`
          tung an noi dung (model 1,9 s ra file 1,6 s, do 21/10/2026);
      (2) file vung co phai DUNG la cat cua file toan bo khong. So goc mau
          tung khung hinh, vi do dai thi "dat" ngay ca khi RenderWorker tu
          doi thoi diem;
      (3) preset "Tep nhe" co that su doi so byte cua file (CUNG noi dung,
          khac CRF) chu khong chi doi nhan tren combo;
      (4) hop thoai Xuat co dung hai che do vung + dung bang preset cua
          export_range, keo cuon toi nut xuat o chieu cao SHIP nho nhat, va
          vung sai thi `QFileDialog` KHONG duoc mo;
      (5) hai cua so nam TRONG doan co tieng (0->0,6 am, 0,6->1,2 tam) co
          ra dung do dai va dung tieng cua doan do khong — do la cach duy nhat
          phan biet `-ss`/`-t` cua export_range that su di qua lenh xuat video,
          vi `co_names` nhin thay ca duong mp3 sidecar nen khong do duoc no.

    Nam lan xuat, 60 khung hinh 256x144 @10fps + mot lan dung ExportDialog
    that — do la gia that cua viec do tren san pham, khong phai do tren ham phong.
    """
    import shutil
    import subprocess
    import tempfile

    from core import external_tools, export_range
    from core.timeline_model import TimelineModel, TrackType
    # Import thang trong dong test: PyInstaller chi nhin thay module khi co
    # lenh import duoc goi that, khong phai trong than mot nut bam.
    from ui.export_dialog import ExportDialog, RenderWorker  # noqa: F401

    ffmpeg = external_tools.find("ffmpeg")
    ffprobe = external_tools.find("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))

    FPS = 10
    WIDTH, HEIGHT = 256, 144
    LOUD, QUIET = 1.2, 1.2
    TOTAL = LOUD + QUIET
    # Diem noi tieng trong doan dau ro rang: 0 -> RAMP am, RAMP -> LOUD tam.
    RAMP = 0.6

    def run(command):
        return subprocess.run(command, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=300, check=False,
                              creationflags=0x08000000 if os.name == "nt" else 0)

    def measure(path):
        """Do file bang ffprobe -count_frames: so khung hinh PHAI la so that
        giai ma duoc, khong phai con so trong lenh cat. Lay theo KHOA-TEN
        ("nb_read_frames=24"), khong lay theo thu tu dong: vo khoa thi dong
        "24" bi doc thanh thoi luong va doan cuoi lai "bien mat" gian tiep
        (lan chay 22/10/2026 bao 0 frame tren mot file 24 frame)."""
        probe = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                     "-count_frames", "-show_entries",
                     "stream=nb_read_frames:format=duration",
                     "-of", "default=nw=1", path])
        if probe.returncode != 0:
            raise RuntimeError("ffprobe khong doc duoc file: %s"
                               % probe.stderr.decode("utf-8", "replace")[-200:])
        frames = 0
        seconds = 0.0
        for line in probe.stdout.decode("utf-8", "replace").splitlines():
            key, _, value = line.partition("=")
            value = value.strip()
            if key.strip() == "nb_read_frames":
                frames = int(float(value or 0))
            elif key.strip() == "duration":
                seconds = float(value or 0.0)
        if not frames or not seconds:
            raise RuntimeError("ffprobe khong tra du frame/thoi luong: %r"
                               % probe.stdout.decode("utf-8", "replace"))
        return frames, seconds, os.path.getsize(path)

    def rms(path):
        """RMS cua TIENG trong file, doc bang ffmpeg (`-vn -f f32le`) roi tinh
        bang numpy — khong phai do lenh cat. None khi file khong co audio
        stream de `vung` im lang khong bi tinh thanh 0,0 (rat yen)."""
        proc = run([ffmpeg, "-v", "error", "-i", path,
                    "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"])
        if proc.returncode != 0 or not proc.stdout:
            return None
        import numpy as np
        data = np.frombuffer(proc.stdout, np.float32)
        if not data.size:
            return None
        return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))

    def angle_between(a, b):
        return min(abs(a - b), 360.0 - abs(a - b))

    folder = tempfile.mkdtemp(prefix="clinging_export_range_")
    try:
        # ── 1. toan cua so, khong cham file ──
        full = export_range.resolve_window(0.0, TOTAL, TOTAL, FPS)
        if not full.get("ok") or full["mode"] != export_range.RANGE_FULL:
            raise RuntimeError("vung toan bo bi nhan dien sai: %r" % full)
        if full["frames"] != int(TOTAL * FPS):
            raise RuntimeError("toan bo sinh %d frame thay vi %d"
                               % (full["frames"], int(TOTAL * FPS)))
        clamped = export_range.resolve_window(-5.0, 999.0, TOTAL, FPS)
        if not clamped.get("ok") or clamped["start"] != 0.0:
            raise RuntimeError("ngoai pham vi khong duoc kep ve: %r" % clamped)
        # `clamped` tren day KHONG do duoc chan dau tren: khi start bi kep ve 0
        # thi nhanh RANGE_FULL reset moi thu nen bo qua luon lenh `end`. Cua so
        # 1,0 -> 999,0 moi nhin thay chan: khong chan thi ffmpeg ghi 9980 frame
        # (lan chay 22/10/2026 dong kep ve XANH vi ly do sai).
        low = export_range.resolve_window(-5.0, 1.0, TOTAL, FPS)
        if (low["mode"] != export_range.RANGE_WINDOW or low["start"] != 0.0
                or low["frames"] != FPS or abs(low["span"] - 1.0) > 1e-9):
            raise RuntimeError("kep ve dau duoi sinh ra %r" % low)
        high = export_range.resolve_window(1.0, 999.0, TOTAL, FPS)
        if (high["mode"] != export_range.RANGE_WINDOW
                or high["frames"] != int((TOTAL - 1.0) * FPS)
                or abs(high["span"] - (TOTAL - 1.0)) > 1e-9):
            raise RuntimeError("kep ve dau tren sinh ra %r" % high)
        tiny = export_range.resolve_window(TOTAL - 0.05, TOTAL, TOTAL, FPS)
        if tiny.get("ok") or tiny["frames"] or not tiny["error"]:
            raise RuntimeError("vung 0,05 s phai bi tu che: %r" % tiny)
        # Loi phai nen duoc CON SO, khong phai noi "qua ngan": nguoi dung
        # chinh ly do 0,05 s bi tu che khi biet toi thieu la bao nhieu.
        if str(export_range.MIN_WINDOW_FRAMES) not in tiny["error"]:
            raise RuntimeError("loi vung ngan khong nen toi thieu: %r"
                               % tiny["error"])
        # span PHAI la frames/fps, khong phai hieu hai so nhap tay: lech 1/fps
        # giua audio va video la lan lap moi lan xuat.
        quantal = export_range.resolve_window(0.0, 1.25, TOTAL, FPS)
        if quantal["span"] * FPS != quantal["frames"]:
            raise RuntimeError("span khong sinh tu so khung hinh: %r" % quantal)
        if export_range.audio_input_args(full):
            raise RuntimeError("xuat toan bo van -ss vo nghia")
        windowed = export_range.resolve_window(LOUD, TOTAL, TOTAL, FPS)
        if export_range.audio_input_args(windowed) != ["-ss", "%.6f" % LOUD]:
            raise RuntimeError("vung khong cat audio bang -ss truoc -i: %r"
                               % export_range.audio_input_args(windowed))
        keys = export_range.preset_keys()
        if len(set(keys)) != len(keys) or len(keys) != len(export_range.QUALITY_PRESETS):
            raise RuntimeError("preset trung key hoac thieu: %r" % (keys,))
        if export_range.encode_args(None) != export_range.encode_args(keys[0]):
            raise RuntimeError("preset la khong roi mac dinh CRF 18")
        if "-shortest" in " ".join(export_range.output_args(windowed)):
            raise RuntimeError("output_args dung lai -shortest")

        # ── 2. RenderWorker phai di qua export_range, khong ban phuc bac ──
        used = RenderWorker.run.__code__.co_names
        missing = [name for name in ("resolve_window", "frame_time",
                                     "encode_args", "audio_input_args",
                                     "output_args") if name not in used]
        if missing:
            raise RuntimeError("RenderWorker.run khong goi %s"
                               % ", ".join(missing))
        # `-shortest` tim trong co_consts cua HAM, khong bang grep van ban: grep
        # cham vao chinh dong comment giai thich no (lan chay 22/10/2026 dong
        # nay do RED vi mot dong chu), va `inspect.getsource` khong ton tai
        # trong bundle dong goi — co_consts thi co.
        if "-shortest" in RenderWorker.run.__code__.co_consts:
            raise RuntimeError("lenh xuat van mang hang so '-shortest'")
        # Hop thoai KHONG duoc tu phat cong thuc: o xem truoc, o loi va lenh
        # xuat phai la CUNG mot so do (bai hoc the Cat `9ed6125` — hinh hoc di
        # qua mot seam duy nhat de con chuot va spinner khong bao gio bat
        # dong). Do tren `co_names` cua ham, bundle dong goi van con no.
        if "resolve_window" not in ExportDialog._current_window.__code__.co_names:
            raise RuntimeError("ExportDialog._current_window khong goi "
                               "export_range.resolve_window: hop thoai tu tinh "
                               "cua so cua no")

        # ── 3. fixture: hai nua nguon khac nhau, mot nua co tieng ──
        # HAI nguon khac nhau: moi clip chay nguon cua no tu source t=0, nen
        # mot nguon duy nhat khiem mau cho ca hai nua va phep so sanh "vung =
        # cat cua toan bo" truong thanh lech 1 do (do lan chay 22/10/2026).
        # Nguon sau IM LANG va hue lech 72 do.
        # Tieng cua nguon dau CO RAMP bien doi (to den RAMP, thi bat sau do):
        # khong co no thi moi cua so nam trong doan co tieng deu cho cung mot
        # con so RMS va phep thu "-ss co mat hay khong" vo nghia. Do 22/10/2026:
        # 440 Hz gain 1,0 = 0,088, gain 0,02 = 0,0068 (hop le 12 lan).
        loud = os.path.join(folder, "dau.mp4")
        quiet = os.path.join(folder, "cuoi.mp4")
        make = run([ffmpeg, "-v", "error", "-y",
                    "-f", "lavfi", "-i",
                    "testsrc2=size=160x120:rate=25:duration=%g,hue=h=t*60"
                    % TOTAL,
                    "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=%g,"
                    "volume=volume='if(lt(t,%g),1.0,0.02)':eval=frame"
                    % (LOUD, RAMP),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
                    "-t", "%.6f" % TOTAL, loud])
        if make.returncode != 0 or not os.path.isfile(loud):
            raise RuntimeError("khong dung duoc fixture co tieng: %s"
                               % make.stderr.decode("utf-8", "replace")[-200:])
        make = run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x120:rate=25:duration=%g,hue=h=72+t*60"
                    % QUIET,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-an", quiet])
        if make.returncode != 0 or not os.path.isfile(quiet):
            raise RuntimeError("khong dung duoc fixture im lang: %s"
                               % make.stderr.decode("utf-8", "replace")[-200:])

        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.VIDEO)
        model.add_clip(track.track_id, loud, "video", 0.0, LOUD, "dau")
        model.add_clip(track.track_id, quiet, "video", LOUD, QUIET, "cuoi")
        if abs(model.duration - TOTAL) > 1e-6:
            raise RuntimeError("du an %r s thay vi %r s" % (model.duration, TOTAL))

        # ── 4. hop thoai va worker phai cung MỘT cửa sổ ──
        # ExportDialog lay model truc tiep (khong can MainWindow), nen doan
        # nay cham mat tien san pham that ma van khong doc du an cua nguoi
        # dung. `_update_preview` ve pixmap tuong trung, khong doc file nen
        # khong lai rac vao `core.media_cache` cua nguoi dung.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            raise RuntimeError("selftest khong co QApplication")
        dialog = ExportDialog(model)
        original_dialog = getattr(sys.modules["ui.export_dialog"],
                                  "QFileDialog", None)
        stubbed = []
        try:
            if [dialog.combo_quality.itemData(i)
                    for i in range(dialog.combo_quality.count())] != list(keys):
                raise RuntimeError("combo preset khong dung bang export_range: %r"
                                   % [dialog.combo_quality.itemData(i)
                                      for i in range(dialog.combo_quality.count())])
            modes = [dialog.combo_range.itemData(i)
                     for i in range(dialog.combo_range.count())]
            if modes != [export_range.RANGE_FULL, export_range.RANGE_WINDOW]:
                raise RuntimeError("combo vung xuat khong co dung hai che do: %r"
                                   % (modes,))
            if (dialog.content_scroll.verticalScrollBarPolicy()
                    != Qt.ScrollBarAsNeeded):
                raise RuntimeError("thanh cuon bi tat trong khi hai cot can "
                                   "555 px hon cua so 520 px")
            dialog.resize(1120, 520)   # chieu cao SHIP nho nhat cua no
            dialog.show()
            for _ in range(4):
                app.processEvents()
            # Keo cuon toi han o CA HAI che do roi do: `grab()` khong cuon nen
            # anh khong bao gio thay phan duoi fold, chi so do nay moi do
            # duoc (bay SplitDialog: 492 px can trong 410 px viewport).
            # Do bang mapTo(viewport): `content_scroll.mapFrom()` tra toa do lech
            # nen moi hat nam trong scroll area deu ra am o lan chay
            # 22/10/2026. Nut xuat lai nam o footer NGOAI scroll area (QFrame
            # 1120x62 tai y 458 cua dialog) nen no phai do theo rect cua dialog.
            scroll = dialog.content_scroll
            inner = scroll.widget()
            bar = scroll.verticalScrollBar()
            view_h = scroll.viewport().height()

            def reach(widget):
                bar.setValue(bar.maximum())
                for _ in range(3):
                    app.processEvents()
                if inner.isAncestorOf(widget):
                    top = widget.mapTo(scroll.viewport(), QPoint(0, 0)).y()
                    return top, top + widget.height(), view_h
                pos = widget.mapTo(dialog, QPoint(0, 0))
                return pos.y(), pos.y() + widget.height(), dialog.height()

            for index, widgets in (
                    (0, ((dialog.combo_quality, "combo preset"),
                         (dialog.toggle_audio, "nut am thanh"),
                         (dialog.btn_export, "nut xuat"))),
                    (1, ((dialog.combo_range, "combo vung"),
                         (dialog.spin_from, "o Tu"),
                         (dialog.spin_to, "o Den"),
                         (dialog.btn_export, "nut xuat")))):
                dialog.combo_range.setCurrentIndex(index)
                for _ in range(4):
                    app.processEvents()
                for widget, label in widgets:
                    top, bottom, limit = reach(widget)
                    if not (0 <= top and bottom <= limit + 1):
                        raise RuntimeError("%s nam ngoai khung nhin o chieu "
                                           "cao 520 px (y %d..%d trong %d px, "
                                           "che do %s)" % (label, top, bottom,
                                                            limit, index))

            # 1,25 s le theo fps cua hop thoai: neu no tu do dai bang hieu hai
            # so nhap tay thi span lech so khung hinh va phep so nay do duoc.
            # PHAI chang qua 30 fps: o 24 fps (mac dinh cua combo) 1,25 s tron
            # ven 30 frame nen `span` nhap tay bang y het `frames / fps`, va
            # vet phan chung "hop thoai tu do dai" XANH như không (do
            # 22/10/2026). 37,5 frame thi khong bao gio sinh ra tu phep nguyen
            # hoa nao.
            fps_index = dialog.combo_fps.findData(30)
            if fps_index < 0:
                raise RuntimeError("combo fps khong co 30 de do le so khung "
                                   "hinh: %r" % dialog.combo_fps.currentData())
            dialog.combo_fps.setCurrentIndex(fps_index)
            dialog.combo_range.setCurrentIndex(
                dialog.combo_range.findData(export_range.RANGE_WINDOW))
            dialog.spin_from.setValue(0.0)
            dialog.spin_to.setValue(1.25)
            for _ in range(3):
                app.processEvents()
            fps_d = float(dialog._current_fps())
            shown = dialog._current_window()
            if not shown.get("ok"):
                raise RuntimeError("hop thoai tu che vung 0->1,25 s: %s"
                                   % shown["error"])
            if abs(shown["span"] * fps_d - shown["frames"]) > 1e-6:
                raise RuntimeError("hop thoai do do dai bang hieu so nhap tay, "
                                   "khong bang khung hinh: %r" % shown)
            want = export_range.resolve_window(dialog.spin_from.value(),
                                               dialog.spin_to.value(),
                                               model.duration, fps_d)
            if shown != want:
                raise RuntimeError("hop thoai va worker ra hai cua so khac nhau:"
                                   " %r vs %r" % (shown, want))

            # Nguoi dung doc do dai o `lbl_duration`, khong doc dict. Vung
            # duoi mot giay la hop le (toi thieu 2 frame) nen chuoi mm:ss cua
            # toan bo bai video se in "00:00" ngay canh nut Xuat (do
            # 22/10/2026: vung 1,2 s in "00:01"). Do bang con so ma chinh
            # seam sinh ra, khong do bang do dai chuoi.
            dialog.spin_to.setValue(RAMP)
            for _ in range(3):
                app.processEvents()
            label = dialog.lbl_duration.text()
            tiny_w = dialog._current_window()
            if ("%d frame" % tiny_w["frames"]) not in label or "00:00" in label:
                raise RuntimeError("do dai vung %r s in ra %r — phai la con so "
                                   "giay + khung hinh, khong phai mm:ss"
                                   % (RAMP, label))

            # bam nut THAT voi vung sai: hop thoai chon cho luu khong duoc mo.
            # Cai bi thay la TEN TRONG MODULE `ui.export_dialog` (no import
            # QFileDialog vo namespace), khong phai static method cua Qt —
            # cai do PySide6 khong cho ghi de.
            class _NoSaveDialog(object):
                @staticmethod
                def getSaveFileName(*_args, **_kwargs):
                    stubbed.append(1)
                    return "", False

            sys.modules["ui.export_dialog"].QFileDialog = _NoSaveDialog
            dialog.spin_to.setValue(0.01)     # 0,01 s: duoi toi thieu khung hinh
            dialog._on_export_clicked()
            status = dialog.lbl_status.text()
            if stubbed or "Loi" not in status and "Lỗi" not in status:
                raise RuntimeError("vung 0,01 s van mo hop thoai luu file hoac "
                                   "khong in loi: status=%r" % status)
        finally:
            if original_dialog is not None:
                sys.modules["ui.export_dialog"].QFileDialog = original_dialog
            dialog.close()
            dialog.deleteLater()

        # ── 5. nam lan xuat THAT qua RenderWorker ──
        def export(label, start, end, quality):
            """Xuat qua RenderWorker THAT roi do file — khong do lenh cat."""
            out = os.path.join(folder, label + ".mp4")
            window = None
            if start is not None:
                window = export_range.resolve_window(start, end,
                                                     model.duration, FPS)
                if not window.get("ok"):
                    raise RuntimeError("vung %s bi tu che: %s"
                                       % (label, window["error"]))
            errors, done = [], []
            worker = RenderWorker(model, out, WIDTH, HEIGHT, FPS, "16:9", False,
                                  window=window, quality=quality)
            worker.errorOccurred.connect(errors.append)
            worker.finished_ok.connect(done.append)
            worker.run()
            if errors or not done:
                raise RuntimeError("%s: RenderWorker bao loi %r" % (label, errors))
            if not os.path.isfile(out):
                raise RuntimeError("%s: xong ma khong co file tren dia" % label)
            results = measure(out)
            return results

        # "toan bo" di duong MAC DINH (window=None): phai giu hanh vi cu.
        f_frames, f_seconds, _f_bytes = export("toan_bo", None, None, None)
        w_frames, w_seconds, w_bytes = export("vung", LOUD, TOTAL, "cao")
        n_frames, n_seconds, n_bytes = export("vung_nhe", LOUD, TOTAL, "nhe")
        # HAI cua so NAM TRONG DOAN CO TIENG. `vung` o tren nam hoan toan trong
        # doan im lang, nen no khong do duoc duong audio: `worker_bo_audio_seek`
        # XANH vi ly do do (lan chay 22/10/2026). 0->RAMP am, RAMP->LOUD tam:
        # bo `-ss` thi hai file giong het nhau ve tieng, bo `-t` thi ca hai dai
        # 2,4 s vi audio duoi day van chay het.
        t_frames, t_seconds, _t_bytes = export("tieng", 0.0, RAMP, "cao")
        c_frames, c_seconds, _c_bytes = export("vung_cat", RAMP, LOUD, "cao")

        if f_frames != int(TOTAL * FPS):
            raise RuntimeError("toan bo ra %d frame: doan cuoi im lang van bi an"
                               % f_frames)
        if abs(f_seconds - TOTAL) > 1.0 / FPS:
            raise RuntimeError("toan bo dai %r s thay vi %r s"
                               % (f_seconds, TOTAL))
        if w_frames != int(QUIET * FPS):
            raise RuntimeError("vung 1,2->2,4 s ra %d frame" % w_frames)
        if abs(w_seconds - QUIET) > 1.0 / FPS:
            raise RuntimeError("vung dai %r s thay vi %r s" % (w_seconds, QUIET))

        # Do dai cua hai cua so co tieng do bang NOI DUNG file ra, khong phai
        # do bang con so ma export_range tu sinh ra cho chinh no.
        for label, frames, seconds in (("tieng", t_frames, t_seconds),
                                       ("vung_cat", c_frames, c_seconds)):
            if frames != int(RAMP * FPS) or abs(seconds - RAMP) > 1.0 / FPS:
                raise RuntimeError(
                    "%s: %d frame/%r s thay vi %d/%r s — do dai file ra khong "
                    "phai do chinh export quyet" % (label, frames, seconds,
                                                    int(RAMP * FPS), RAMP))
        r_loud = rms(os.path.join(folder, "tieng.mp4"))
        r_quiet = rms(os.path.join(folder, "vung_cat.mp4"))
        if r_loud is None or r_quiet is None:
            raise RuntimeError("cua so co tieng ma file ra khong co audio "
                               "stream: %r vs %r" % (r_loud, r_quiet))
        # Ty le, khong hang so tuyet doi: AAC + aresample lam so nho doi, con
        # thieu `-ss` thi hai doan tra ve CUNG mot tieng to. Nguon fixture mat
        # ramp thi cung bi bat o day (r_loud < 0,01 hoac tieng gan bang nhau).
        if r_loud < 0.01 or r_quiet * 4.0 >= r_loud:
            raise RuntimeError("audio cua vung_cat khong duoc -ss cat theo "
                               "RAMP: RMS %r (am) vs %r (tam)"
                               % (r_loud, r_quiet))

        # ── 6. vung PHAI la cat cua toan bo, khong phai noi dung khac ──
        # So theo CHI SO FRAME (frame i cua vung = frame 12+i cua toan bo),
        # khong theo giay: `extract_frame_image` dat `-ss` TRUOC `-i` la fast
        # seek va file nay chi co MOT keyframe, nen lan chay 22/10/2026 no bao
        # lech 26,1 do tai 0,15 s trong khi ba lech con lai (0,5 / 1,05 s)
        # duoi 7 do — do la loi cua dong ho mua, khong phai cua RenderWorker.
        # Cung mot nhieu testsrc2 ma hai ben deu giai ra tu DUNG mot nguon nen
        # lech con lai la lech cat noi dung that (do duoc <=6,6 do).
        path_full = os.path.join(folder, "toan_bo.mp4")
        path_win = os.path.join(folder, "vung.mp4")
        shots = {}
        for label in ("full", "win"):
            shots[label] = os.path.join(folder, "frames_" + label)
            os.mkdir(shots[label])
        full_hue = _frame_hue_track(path_full, shots["full"])
        win_hue = _frame_hue_track(path_win, shots["win"])
        if len(full_hue) != int(TOTAL * FPS) or None in full_hue:
            raise RuntimeError("toan bo giai ra %r khung hinh mau, mong %d"
                               % (full_hue, int(TOTAL * FPS)))
        if len(win_hue) != int(QUIET * FPS) or None in win_hue:
            raise RuntimeError("vung giai ra %r khung hinh mau, mong %d"
                               % (win_hue, int(QUIET * FPS)))
        skip = int(LOUD * FPS)
        deltas = [round(angle_between(full_hue[skip + i], win_hue[i]), 1)
                  for i in range(len(win_hue))]
        if max(deltas) > 15.0:
            raise RuntimeError("frame %d+%d cua vung khong phai frame cua toan "
                               "bo: lech %r do" % (skip, deltas.index(max(deltas)),
                                                   deltas))
        # So 12 frame cua vung voi 12 frame DAU cua toan bo thi phai khac nhau
        # o MOI frame: neu hai nua nguon giong het nhau thi cua so o tren cung
        # XANH du cat sai noi dung. Nguon sau lech hue 72 do nen lech nho nhat
        # o day do duoc la 72 tru bien do cat.
        head = [round(angle_between(full_hue[i], win_hue[i]), 1)
                for i in range(len(win_hue))]
        if min(head) < 20.0:
            raise RuntimeError("vung giong ca doan dau toan bo (%r do): hai nua "
                               "nguon khong khac nhau, gate khong phan biet "
                               "duoc gi" % head)

        # ── 7. preset doi that so byte, cung noi dung ──
        if n_frames != w_frames:
            raise RuntimeError("preset doi ca so khung hinh: %d vs %d"
                               % (n_frames, w_frames))
        if not n_bytes * 1.15 < w_bytes:
            raise RuntimeError("CRF 24 khong nho hon CRF 18 nhuan 1,15: "
                               "%d vs %d B" % (n_bytes, w_bytes))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    return ("%d frame/%.2fs toan bo giu du doan im lang, vung %.2fs = %d frame "
            "cat cua no (lech mau %r do <=15), tieng %d f RMS %.4f vs tam %d f "
            "RMS %.4f (%.1f×), CRF24 %d B < CRF18 %d B cung frame"
            % (f_frames, f_seconds, w_seconds, w_frames, deltas,
               t_frames, r_loud, c_frames, r_quiet, r_loud / max(r_quiet, 1e-9),
               n_bytes, w_bytes))


def _captions_strip_ok():
    """Mot dong trong --selftest: thanh tien do Auto Captions mong trong bundle nay.

    Khong trung lap scratch/captions_bar_probe.py: probe do tra loi "code nguon
    co mong khong", dong nay tra loi "ban exe NGUOI DUNG NHAN co con kiem 20px
    vien 1px + chu trang trong no hay khong". Do tren chinh grab cua rieng thanh,
    bang dung thuoc bar_measure.py — ba noi (split, thumbnail, dong nay) phai
    chung mot so do, mot thuoc do thu hai la mot loi chung minh thu hai.

    Khong mo MainWindow: cua so that se tai/luoi du an .clinq cua nguoi dung,
    va selftest khong co quyen dong vao du lieu do. Hop thoai duoc dung truc
    tiep tu lop san xuat.

    Phep phan biet cung nam trong dong nay: ap lai kieu cu thi thuoc do phai
    chi DAY HON, neu khong thi "8px" chi la mot con so tu kiem tra.
    """
    from PySide6.QtWidgets import QApplication, QWidget
    import bar_measure
    from ui.auto_captions_dialog import AutoCaptionsDialog

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("selftest khong co QApplication")
    # Hop thoai goi refresh_sources() trong constructor, nen can mot
    # main_window gia lap co du timeline_panel.model.tracks rong. Gia lap o
    # day chu khong phai MainWindow that vi MainWindow tai/luoi du an .clinq
    # cua nguoi dung — selftest khong co quyen dong vao du lieu do.
    stub = types.SimpleNamespace(
        timeline_panel=types.SimpleNamespace(
            model=types.SimpleNamespace(tracks=[])))
    host = QWidget()
    dialog = AutoCaptionsDialog(stub, host)
    try:
        if dialog.progress.isVisible():
            raise RuntimeError("thanh 0% van nam chet giua form khi chua chay")
        if dialog.progress.isTextVisible():
            raise RuntimeError("thanh van in chu trong no")
        if dialog.progress.height() != 8:
            raise RuntimeError("thanh khai %dpx, mong 8px"
                               % dialog.progress.height())
        dialog.show()
        for _ in range(4):
            app.processEvents()
        # Slot THAT ma worker ASR goi — con so % phai chuyen sang lbl_status.
        dialog._on_progress(50, "đang nhận dạng")
        # _on_run moi la noi `setVisible(True)`; goi no trong bundle se khoi
        # dong worker mang that, nen ta bat hien theo dung cach no lam roi do.
        dialog.progress.setVisible(True)
        for _ in range(4):
            app.processEvents()
        folder = os.path.dirname(_report_path(sys.argv)) or os.getcwd()
        band = bar_measure.teal_band_height(
            dialog.progress, os.path.join(folder, "selftest_captions_bar.png"))
        dpr = float(dialog.progress.devicePixelRatioF())
        if not 3 < band <= dpr * 8 + 3:
            raise RuntimeError("bang teal %dpx vuot thanh 8px CSS (DPR %.2f)"
                               % (band, dpr))
        status = dialog.lbl_status.text()
        if not status.startswith("50%"):
            raise RuntimeError("con so %% bi mat khi thu thanh: %r" % status)

        dialog.progress.setFixedHeight(20)
        dialog.progress.setStyleSheet(
            "QProgressBar { border: 1px solid #262831; border-radius: 6px;"
            " background-color: #14151A; }")
        for _ in range(4):
            app.processEvents()
        old_band = bar_measure.teal_band_height(
            dialog.progress,
            os.path.join(folder, "selftest_captions_bar_oldstyle.png"))
        dialog.progress.setStyleSheet("")
        dialog.progress.setFixedHeight(8)
        for _ in range(4):
            app.processEvents()
        if old_band - band <= 3:
            raise RuntimeError("thuoc do khong phan biet kieu cu: %d vs %d"
                               % (old_band, band))
        back = bar_measure.teal_band_height(
            dialog.progress,
            os.path.join(folder, "selftest_captions_bar_restored.png"))
        if back != band:
            raise RuntimeError("phuc kieu mong khong tra lai so ban dau: %d vs %d"
                               % (back, band))

        # Hang "Ngôn ngữ" bi xoa cung luc voi Faster Whisper (local): khong co
        # engine nao con lai nhan duoc tham so ngon ngu, nen no la control chet.
        # Do so hang cua chinh form nay — khong phai tin vao review — va lap
        # toan bo hop thoai thanh anh bang chung cho ban da cai.
        from PySide6.QtWidgets import QFormLayout, QLabel
        form = dialog.findChild(QFormLayout)
        if form is None:
            raise RuntimeError("hop thoai khong con QFormLayout de do")
        captions = [label.text() for label in dialog.findChildren(QLabel)]
        if any("Ngôn ngữ" in text for text in captions):
            raise RuntimeError("hang chon ngon ngu van con, khong engine nao dung den no")
        if form.rowCount() != 2:
            raise RuntimeError("form %d hang, mong 2 (Nguon am thanh + Engine)"
                               % form.rowCount())
        dialog.grab().save(os.path.join(folder, "selftest_captions_dialog.png"))
        return ("bang teal %dpx (DPR %.2f) vs kieu cu %dpx, %% di sang "
                "lbl_status: %r; form %d hang, khong con ngon ngu"
                % (band, dpr, old_band, status, form.rowCount()))
    finally:
        dialog.close()
        for _ in range(4):
            app.processEvents()


def _writable_ok():
    from core.project_storage import APP_DIR
    os.makedirs(APP_DIR, exist_ok=True)
    probe = os.path.join(APP_DIR, "selftest.probe")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("ok")
    os.remove(probe)
    return APP_DIR


def _ffmpeg_note():
    """ffmpeg/ffprobe mà CHÍNH bản này tìm thấy, kèm nguồn của từng bản.

    Dòng này phải phân biệt được "bản đi kèm" với "bản mượn từ PATH": nếu
    installer thiếu file thì bundle vẫn xanh nhờ ffmpeg của máy lập trình, và
    đó là bản cài hỏng đem giao cho một máy sạch.
    """
    from core import external_tools
    rows = []
    missing = []
    for tool in ("ffmpeg", "ffprobe"):
        path = external_tools.find(tool)
        if not path:
            missing.append(tool)
            rows.append("%s=MISSING" % tool)
            continue
        try:
            out = subprocess.run([path, "-version"], capture_output=True,
                                 timeout=20)
            first = out.stdout.decode("utf-8", "replace").splitlines()
            if out.returncode == 0 and first:
                version = first[0].split(" Copyright")[0][:46]
            else:
                version = "rc=%d" % out.returncode
                missing.append(tool)
        except Exception as exc:
            version = "GOI KHONG DUOC (%s)" % type(exc).__name__
            missing.append(tool)
        rows.append("%s=%s [%s]" % (tool, version,
                                    external_tools.source(tool)))
    if missing:
        raise RuntimeError("; ".join(rows))
    return "; ".join(rows)


def _selftest_only(argv):
    """Lay cac `--only=<dieu tru ten dong>` tu argv (rong = chay du 38 dong).

    Ly do co bo nay (do 22/10/2026): `compress_counterfactual.py` doi 17 phep
    byte tren `core/media_compress.py`, moi phep chay tron `--selftest` 38 dong
    — tuc 17 lan ma hoa karaoke/pop art/chroma/nen tep THAT, ~20 phut, va no
    lam treo ca may dang lam viec. Bo loc chi cat giu dung dong dang do, van
    di qua dung lenh production `main.py --selftest` (khong phai goi ham `_ok`
    truc tiep, nen van co QApplication, co boundary cua bundle, co rc that).
    """
    flag = "--only="
    return [a[len(flag):] for a in argv[1:] if a.startswith(flag)]


def run_selftest(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    report = _report_path(argv)
    col = Collector()

    # QIcon/bo ve glyph nap font qua QGuiApplication, nen phai co app that —
    # dung cai app ma exe nay van tao ra khi mo binh thuong.
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841

    def frozen():
        if not getattr(sys, "frozen", False):
            return "running from source (not a bundle)"
        base = getattr(sys, "_MEIPASS", "")
        if not os.path.isdir(base):
            raise RuntimeError("khong co _MEIPASS")
        return "%s, %d entry" % (base, len(os.listdir(base)))

    rows = [
        ("bundle dong goi", frozen),
        ("styles/*.qss + theme", _styles_ok),
        ("icon ung dung", _icon_ok),
        ("font icon", _font_icon_ok),
        ("src.asr (Auto Captions)", _asr_ok),
        ("cv2/numpy/psutil/pydub", _media_libs_ok),
        ("PySide6 modules", _qt_modules_ok),
        ("cross-fade audio plan", _transition_audio_ok),
        ("audio cua tung clip", _clip_audio_ok),
        ("cai dat that (14 khoa + hook)", _settings_ok),
        ("toan bo do thi UI", _ui_graph_ok),
        ("chrome nhin thay duoc co slot that", _chrome_ok),
        ("duong cong easing cua keyframe", _keyframe_easing_ok),
        ("do thi duong cong keyframe", _keyframe_graph_ok),
        ("phong cach pop art", _popart_ok),
        ("13 the mau/loc do duoc pixel that", _effect_liveness_ok),
        ("8 aura to sang va chay theo dong ho clip", _aura_ok),
        ("lop phu recap: vien/REC/kinh mo + luu vao file", _recap_overlay_ok),
        ("bo cuc + phong cach cap du an (12 kieu, 10 chat lieu, luu vao file)",
         _project_layout_ok),
        ("8 kieu karaoke: quet theo tu + luu vao file", _karaoke_ok),
        ("mo du an tu file .clinq", _project_launch_ok),
        ("dong cua so: dung luong giai ma clip tru khi thoat", _clip_teardown_ok),
        ("luu du an: ghi hong khong pha ban cu", _save_atomic_ok),
        ("media lac cho: preview va export cung duong dan", _media_locator_ok),
        ("undo cho chu + hinh hoc clip", _undo_text_transform_ok),
        ("bien doi: xoay tu do + lat + canh le + khoa ty le", _transform_ui_ok),
        ("clipboard clip Ctrl+C/V", _clipboard_copy_paste_ok),
        ("style chu: vien/bong/hop nen/can le", _text_styling_ok),
        ("chinh mau: hue/lift-gamma-gain/LUT .cube", _color_grading_ok),
        ("duc nen chroma key: goc hue + alpha qua chuoi loc", _chroma_key_ok),
        ("doc MRU khong ghi du lieu nguoi dung", _recent_readonly_ok),
        ("giai ma tuan tu + cache dia", _decode_cache_ok),
        ("thu vien tai nguyen: 1 luot luoi + the an khong giai ma",
         _library_panel_ok),
        ("xem truoc = xuat: moc thoi gian cuc bo dung mot ham", _local_time_ok),
        ("trich xuat anh thumbnail", _thumbnail_export_ok),
        ("cat file thanh N doan ra dia", _media_split_ok),
        ("tach tieng video thanh clip audio rieng", _detach_audio_ok),
        ("kho hieu ung am thanh sfx: 14 tieng chen xuong timeline", _sfx_pack_ok),
        ("the Cat in/out trong bang thuoc tinh", _trim_card_ok),
        ("vung xuat in/out + preset chat luong", _export_range_ok),
        ("nen toi uu tep video: moov + codec-hop-container",
         _media_compress_ok),
        ("thanh tien do Auto Captions 8px", _captions_strip_ok),
        ("thu muc du lieu nguoi dung", _writable_ok),
        ("ffmpeg + ffprobe tim thay", _ffmpeg_note),
    ]

    only = _selftest_only(argv)
    if only:
        selected = [(name, fn) for name, fn in rows
                    if any(token in name for token in only)]

        def _nothing_selected():
            raise RuntimeError(
                "--only=%s khong trach duong nao trong %d dong tu"
                % (",".join(only), len(rows)))

        if not selected:
            # Mot bo loc khong trach gi PHAI do, khong duoc PASS vi dau rong
            # — cung hop dong cua `gate_discrimination_probe.py`.
            col.check("bo loc --only khong trach duong nao", _nothing_selected)
        rows = selected
    for name, fn in rows:
        col.check(name, fn)

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        # `only` khac None = day LA lan chay loc, khong phai 38 dong. Cong ty
        # doc JSON phai kiem tra khoa nay truoc khi bao "38 dong xanh".
        "only": only or None,
        "checks": col.rows,
        "failed": [row["name"] for row in col.failed],
    }
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0 if not col.failed else 1


def run_layout_report(argv=None):
    """Do ti le bo cuc mac dinh cua CHINH ban exe nay.

    selftest chi chung minh bundle du manh; no khong do duoc timeline chiem
    bao nhieu phan tram cua so. Nguoc lai, do bang source thi khong phai la
    ban da cai. nen can cay do nay.

    Clinging.exe --layout-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_layout")

    from PySide6.QtWidgets import QApplication, QSplitter
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1920, 1035)
    win.show()
    for _ in range(12):
        app.processEvents()

    vsplit = next(s for s in win.findChildren(QSplitter)
                  if s.orientation().name == "Vertical")
    sizes = list(vsplit.sizes())
    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "splitter_sizes": sizes,
        "timeline_pct": round(100.0 * sizes[1] / sum(sizes), 1),
        "timeline_height": win.timeline_panel.height(),
        "timeline_minimum_height": win.timeline_panel.minimumHeight(),
        "timeline_header_height": win.timeline_panel.header.height(),
        "preview_height": win.preview_panel.height(),
        "window_height": win.height(),
    }
    win.close()
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0


def run_alignment_report(argv=None):
    """Do lech hang track (header trai vs lane phai) cua CHINH ban exe nay.

    Bo cuc lech nhau chi lo khi co 2 scene + 2 view rieng va range cuộn khac
    nhau, nen do bang source la chưa đủ bằng chứng cho bản đã cài.

    Clinging.exe --alignment-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_alignment")

    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_window import MainWindow
    from core.timeline_model import TrackType

    def _diffs(tl):
        rows = []
        for track in tl.model.tracks:
            lane = tl.scene._track_lanes[track.track_id]
            item = tl.header_scene._header_items[track.track_id]
            body_y = tl.view.mapToGlobal(tl.view.mapFromScene(
                QPointF(0.0, lane.pos().y() + lane.rect().y())))
            head_y = tl.header_view.mapToGlobal(tl.header_view.mapFromScene(
                QPointF(0.0, item.pos().y() + item.rect().y())))
            rows.append({
                "track": track.name,
                "body_global_y": body_y.y(),
                "header_global_y": head_y.y(),
                "diff_px": body_y.y() - head_y.y(),
            })
        return rows

    def _geometry(tl):
        bar = tl.view.verticalScrollBar()
        hbar = tl.header_view.verticalScrollBar()
        return {
            "body_scene_h": tl.scene.sceneRect().height(),
            "header_scene_h": tl.header_scene.sceneRect().height(),
            "body_viewport_h": tl.view.viewport().height(),
            "header_viewport_h": tl.header_view.viewport().height(),
            "body_scroll": [bar.value(), bar.maximum()],
            "header_scroll": [hbar.value(), hbar.maximum()],
        }

    win = MainWindow()
    win.resize(1920, 1035)
    win.show()
    for _ in range(12):
        app.processEvents()

    tl = win.timeline_panel
    track = next((t for t in tl.model.tracks if t.is_main_track),
                 None) or tl.model.add_track(TrackType.VIDEO,
                                             is_main_track=True)
    tl.model.add_clip(track.track_id, "Recording.mp4", "video", 0.0, 4.8,
                      "Recording")
    for _ in range(12):
        app.processEvents()

    scenarios = {"1 track": {"geometry": _geometry(tl), "rows": _diffs(tl)}}
    for _ in range(2):
        extra = tl.model.add_track(TrackType.VIDEO)
        tl.model.add_clip(extra.track_id, "extra.mp4", "video", 0.0, 1.5,
                          "extra")
    for _ in range(12):
        app.processEvents()
    scenarios["3 track"] = {"geometry": _geometry(tl), "rows": _diffs(tl)}
    bar = tl.view.verticalScrollBar()
    bar.setValue(bar.maximum())
    for _ in range(12):
        app.processEvents()
    scenarios["3 track, cuon toi day"] = {
        "geometry": _geometry(tl), "rows": _diffs(tl)}

    worst = max(abs(row["diff_px"])
                for scene in scenarios.values() for row in scene["rows"])
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"
    win.grab().save(shot)
    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "worst_diff_px": worst,
        "aligned": worst <= 1,
        "screenshot": os.path.abspath(shot),
        "scenarios": scenarios,
    }
    win.close()
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0 if worst <= 1 else 1


def _report_video(seconds=4.0, fps=30.0, size=(160, 90)):
    """Mot file video ngan trong TEMP de ban da cai co thu can giai ma."""
    import cv2
    import numpy as np
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "clinging_thumbnail_report.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError("khong tao duoc video mau")
    for index in range(int(seconds * fps)):
        writer.write(np.full((size[1], size[0], 3), index * 7 % 256, np.uint8))
    writer.release()
    return path


def run_thumbnail_report(argv=None):
    """Hộp thoại trích xuất ảnh + kết quả ghi ra đĩa, đo từ CHÍNH bản exe này.

    --selftest chỉ chứng minh module có trong bundle. Cái người ta thấy là cửa
    sổ thật mở từ MainWindow, chạy worker thật, và PNG nằm lại trên đĩa — cả
    bốn thứ đó phải do bản đã cài tự đo, vì source luôn đúng.

    Clinging.exe --thumbnail-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_thumbnail")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    import cv2
    import tempfile
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QScrollArea
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    src = _report_video()
    out_dir = os.path.join(tempfile.gettempdir(), "clinging_thumbnail_report_out")
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    for _ in range(12):
        app.processEvents()

    dialog = win._open_thumbnail_export(src)
    dialog.edit_out.setText(out_dir)
    dialog.spin_count.setValue(6)
    scroll = dialog.findChild(QScrollArea)
    bar_before = {
        "visible": scroll.verticalScrollBar().isVisible(),
        "maximum": scroll.verticalScrollBar().maximum(),
        "progress_visible_before": dialog.progress.isVisible(),
    }
    dialog.btn_run.click()
    deadline = time.time() + 120
    while dialog._busy and time.time() < deadline:
        for _ in range(6):
            app.processEvents()
        time.sleep(0.03)
    result = dialog.last_result or {}
    for _ in range(10):
        app.processEvents()
    dialog.grab().save(shot)
    # Do day THAT cua thanh tien trinh tren pixel thiet bi cua chinh bundle
    # nay, bang dung mot thuoc do voi gate tren source (bar_measure.py).
    # Khong phai grab ca hop thoai: nut "Trích xuất" cung mau teal va cao hon
    # thanh rat nhieu, do tren cua so thi dinh dem chieu cao cai nut.
    import bar_measure
    progress_band = bar_measure.teal_band_height(
        dialog.progress, shot[:-4] + "_bar.png")

    names = sorted(n for n in os.listdir(out_dir)
                   if n.startswith("frame_")) if os.path.isdir(out_dir) else []
    # Kich thuoc mong doi lay tu chinh ham ma hop thoai da hien tren dong
    # tom tat: form hen 640x360 thi file phai 640x360, khong phai do hardcode.
    from core import thumbnail_export as thumbs
    expect_size = thumbs.cell_size(src, int(dialog.combo_width.currentData()))
    sizes = []
    for name in names:
        image = cv2.imread(os.path.join(out_dir, name))
        sizes.append(None if image is None else [image.shape[1], image.shape[0]])
    colors = 0
    if os.path.isfile(shot):
        grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
        colors = len({grabbed.pixel(x, y)
                      for x in range(0, grabbed.width(), 4)
                      for y in range(0, grabbed.height(), 4)})

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "source": src,
        "output_dir": out_dir,
        "dialog_title": dialog.windowTitle(),
        "selected_source": os.path.abspath(dialog._current_source() or ""),
        "chrome": bar_before,
        "progress_visible_after": dialog.progress.isVisible(),
        # 8 px CSS quy ra bao nhieu pixel thiet bi tuy may — so voi 14 cung
        # mot nguoc voi may 4K (8 x 2 = 16). Nen doi chieu voi chinh DPR cua
        # widget luc do.
        "progress_band_px": progress_band,
        "progress_dpr": float(dialog.progress.devicePixelRatioF()),
        "status": dialog.lbl_status.text(),
        "summary": dialog.lbl_summary.text(),
        "written": [os.path.basename(p) for p in result.get("written", [])],
        "on_disk": names,
        "decoded_sizes": sizes,
        "sheets": [os.path.basename(p) for p in result.get("sheets", [])],
        "missing": result.get("missing", []),
        "screenshot": os.path.abspath(shot),
        "distinct_colors": colors,
    }
    dialog.close()
    win.close()
    for _ in range(8):
        app.processEvents()
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    ok = (payload["selected_source"] == os.path.abspath(src)
          and bar_before["visible"] is False and bar_before["maximum"] == 0
          and bar_before["progress_visible_before"] is False
          and payload["progress_visible_after"] is True
          and 3 < payload["progress_band_px"] <= payload["progress_dpr"] * 8 + 3
          and len(names) == 6 and names == sorted(payload["written"])
          and all(s == list(expect_size) for s in sizes) and len(payload["sheets"]) == 1
          and not payload["missing"] and colors > 40 and os.path.isfile(shot))
    return 0 if ok else 1


def _image_mean_hue(image):
    """Góc màu trung bình (vòng tròn) của một QImage; None khi khung hinh tron."""
    import math

    import numpy as np
    from PySide6.QtGui import QImage

    if image is None or image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_RGB32)
    stride = image.bytesPerLine() // 4
    arr = np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), stride, 4)[:, :image.width(), :].astype(float)
    blue, green, red = arr[..., 0], arr[..., 1], arr[..., 2]
    high = np.maximum(np.maximum(red, green), blue)
    low = np.minimum(np.minimum(red, green), blue)
    chroma = high - low
    hue = np.zeros_like(red)
    mask = (chroma > 0) & (high == red)
    hue[mask] = (((green[mask] - blue[mask]) / chroma[mask]) % 6.0)
    mask = (chroma > 0) & (high == green)
    hue[mask] = ((blue[mask] - red[mask]) / chroma[mask]) + 2.0
    mask = (chroma > 0) & (high == blue)
    hue[mask] = ((red[mask] - green[mask]) / chroma[mask]) + 4.0
    angle = np.deg2rad(hue * 60.0)[chroma > 0]
    if angle.size == 0:
        return None
    return math.degrees(math.atan2(float(np.sin(angle).mean()),
                                   float(np.cos(angle).mean()))) % 360.0


def _mean_hue(path, seconds):
    """Góc màu tại MỘT giây, đọc bằng đúng decoder preview dùng (cv2/`-ss`).

    Chi dung cho phep do gan (mo cua, doan cat le nhau): `-ss` dat TRUOC `-i`
    la fast seek nen no nam len keyframe gan nhat, khong phai frame can tim.
    Doan nay do 22/10/2026: file 24 frame khong keyframe trung gian, goi tai
    0,15 s va 1,35 s ra HAI frame lech nhau 26 do chi vi dong ho mua, khong
    phai vi noi dung. So khung hinh voi nhau thi dung ``_frame_hue_track``.
    """
    from core.media_frame import extract_frame_image

    return _image_mean_hue(extract_frame_image(path, seconds))


def _frame_hue_track(path, out_dir):
    """Goc mau cua TUNG khung hinh theo thu tu, giai ma ca file MOT lan.

    ffmpeg ghi `f001.png, f002.png, ...` cung `-fps_mode passthrough` (khong
    nhan doi, khong drop), nen thu tu file tren dia = thu tu frame trong file.
    Thang do nay khong the noi gian: khong co seek, khong co keyframe, khong
    doan thoi luong ra so frame. `-vsync 0` KHONG dung duoc o day — ffmpeg 9.0.1
    trong `tools/ffmpeg` da xoa tuy chon do (rc khac 0, "Unrecognized option").
    `out_dir` phai ton tai va rong truoc lan goi.
    """
    from PySide6.QtGui import QImage

    from core import external_tools

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    proc = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", path, "-an",
                           "-fps_mode", "passthrough",
                           os.path.join(out_dir, "f%03d.png")],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=300, check=False,
                          creationflags=0x08000000 if os.name == "nt" else 0)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg khong giai ma duoc %s: %s"
                           % (os.path.basename(path),
                              proc.stderr.decode("utf-8", "replace")[-160:]))
    track = []
    for name in sorted(os.listdir(out_dir)):
        if not name.startswith("f") or not name.endswith(".png"):
            continue
        image = QImage()
        if image.load(os.path.join(out_dir, name)):
            track.append(_image_mean_hue(image))
    return track


# Menu cua card video LA BANG CHUNG SAN PHAM, khong phai chi mot con so.
# `--split-report` tung gate `len(menu_actions) == 2`, nen khi "Nen / toi uu
# tep" ra doi (commit b88f59f, dong 38 cua selftest) chinh report do do RED
# o may hom sau, tren may da cai, chu khong luc viet tinh nang. Danh dau du
# toan bo thu tu: them hay xoa mot hanh dong deu phai ngang qua day.
VIDEO_CARD_MENU = ["Trích xuất ảnh thu nhỏ…", "Cắt thành nhiều đoạn…",
                   "Nén / tối ưu tệp…"]

# Tung dieu kien mot ten, de phan chung (scratch/split_gate_counterfactual.py)
# do duoc vet cua RIENG no va bao khong term nao lang cung.
SPLIT_REPORT_CHECKS = (
    ("frozen", lambda p: p["frozen"]),
    ("dung nguon vua bam",
     lambda p: p["selected_source"] == os.path.abspath(p["source"])),
    ("menu card video", lambda p: p["menu_actions"] == VIDEO_CARD_MENU),
    ("3 doan nam tren dia", lambda p: len(p["on_disk"]) == 3),
    ("danh sach ham = danh sach dia",
     lambda p: p["on_disk"] == sorted(r["name"] for r in p["segments"])),
    ("khong doan nao that bai",
     lambda p: not p["failed"] and not p["cancelled"]),
    ("ffprobe doc lai tung doan",
     lambda p: all(r["probe"] > 0.5 for r in p["segments"])),
    ("mei cat khong ho khong choong",
     lambda p: all(abs(j) <= 1e-3 for j in p["joints"])),
    ("mau tung doan la mau trong nguon",
     lambda p: len(p["hue_gaps"]) == 3 and all(
         g is not None and g < 22.0 for g in p["hue_gaps"])),
    ("status ke so doan", lambda p: "3 đoạn" in p["status"]),
    # grab() cua widget an van ve duoc, nen con so do day phai di kem
    # "no dang hien tren man" — neu khong thi no chi la mot hinh chu nhat.
    ("thang tien do dang hien", lambda p: p["progress_visible_after"] is True),
    ("do day thang tien do hop ly",
     lambda p: 3 < p["progress_band_px"] <= p["progress_dpr"] * 8 + 3),
    ("cua so ve co that", lambda p: p["distinct_colors"] > 40),
    ("anh bang chung nam tren dia", lambda p: os.path.isfile(p["screenshot"])),
)


def split_report_fails(payload):
    """Ten cua tung dieu kien ma `--split-report` do khong dat (rong = dat het).

    Tach khoi run_split_report de phan chung chay duoc tren chinh payload do
    exe da cai ghi ra, khong phai mo lai hop thoai cat.
    """
    return [name for name, ok in SPLIT_REPORT_CHECKS if not ok(payload)]


def run_split_report(argv=None):
    """Cắt file thành N đoạn — mở bằng CHUỘT PHẢI thật, cắt thật, do từ bản exe
    đã cài.

    --selftest chỉ chứng minh module có trong bundle; probe trong scratch/ chứng
    minh core đúng trên source. Thứ mà hai cái đó không nói được: bundle có mở
    được hộp thoại từ menu của card thật, và ffmpeg mà NGƯỜI DÙNG có (không phải
    ffmpeg của người lập trình) có cắt ra file đọc lại được hay không. Nên mỗi
    đoạn ở đây vừa được ffprobe đo thời lượng, vừa được so MÀU với nguồn — một
    đoạn replay đoạn khác vẫn có thời lượng đẹp.

    Clinging.exe --split-report <duong-dan-json>
    """
    import shutil
    import subprocess
    import tempfile
    import time as _time

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_split")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(times=6):
        for _ in range(times):
            app.processEvents()
            _time.sleep(0.03)

    from core import external_tools

    # Ban nay console=False, nen mot exception khong ai bat se duoc PyInstaller
    # hien thi thanh HOP THOAI traceback mo — khong ai bam OK, va probe chay
    # report treo ca 10 phut. Thieu ffmpeg la truong hop da do duoc, nen bao
    # vao JSON roi ve, dung de no thoat len thanh cua so.
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"exe": os.path.abspath(sys.argv[0]),
                       "frozen": bool(getattr(sys, "frozen", False)),
                       "ok": False,
                       "error": external_tools.missing_message("ffmpeg"),
                       "ffmpeg_source": "", "segments": [], "on_disk": [],
                       "failed": [], "cancelled": True, "joints": [],
                       "hue_gaps": [], "progress_band_px": 0,
                       "progress_dpr": 0.0, "progress_visible_after": False,
                       "screenshot": os.path.abspath(shot),
                       "distinct_colors": 0, "menu_actions": [],
                       "dialog_title": None, "selected_source": "",
                       "duration": 0.0, "summary": "", "status": "",
                       "source": ""},
                      handle, ensure_ascii=False, indent=2)
        return 1

    src = os.path.join(tempfile.gettempdir(), "clinging_split_report.mp4")
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=red:s=320x240:d=6:r=25,format=yuv420p,hue=h='t*60'",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=6", "-shortest",
         "-c:v", "libx264", "-preset", "veryfast", "-g", "12",
         "-pix_fmt", "yuv420p", "-c:a", "aac", src],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300,
        check=False, creationflags=0x08000000)
    out_dir = os.path.join(tempfile.gettempdir(), "clinging_split_report_out")
    shutil.rmtree(out_dir, ignore_errors=True)

    from core import media_splitter as splitter
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(12)

    card = win.library_panel.add_resource("split_report.mp4", "video", src)
    menu = card.context_menu()
    actions = [action.text() for action in menu.actions()]
    cut = [action for action in menu.actions() if "Cắt" in action.text()]
    if cut:
        cut[0].trigger()
    pump(8)
    dialog = getattr(win, "_split_dialog", None)

    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "source": src, "output_dir": out_dir, "menu_actions": actions,
               "dialog_title": None if dialog is None else dialog.windowTitle(),
               "selected_source": "", "duration": 0.0, "status": "",
               "summary": "", "segments": [], "on_disk": [], "failed": [],
               "cancelled": True, "joints": [], "hue_gaps": [],
               "progress_band_px": 0, "progress_dpr": 0.0,
               "progress_visible_after": False,
               "ffmpeg_source": external_tools.source("ffmpeg"),
               "ffmpeg_path": ffmpeg,
               "screenshot": os.path.abspath(shot), "distinct_colors": 0}
    try:
        if dialog is None:
            raise RuntimeError("menu khong mo duoc hop thoai")
        dialog.edit_out.setText(out_dir)
        dialog.spin_count.setValue(3)
        payload["selected_source"] = os.path.abspath(
            dialog._current_source() or "")
        payload["duration"] = float(dialog._duration)
        payload["summary"] = dialog.lbl_summary.text()
        dialog.btn_run.click()
        deadline = _time.time() + 300
        while dialog._busy and _time.time() < deadline:
            pump(4)
        result = dialog.last_result or {}
        pump(6)
        dialog.grab().save(shot)
        # Do day thanh tien trinh tren pixel thiet bi cua bundle nay, bang
        # dung thuoc do voi gate tren source — grab ca hop thoai se lay chieu
        # cao nut "Cắt" (cung mau teal) chu khong lay thanh.
        import bar_measure
        payload["progress_visible_after"] = dialog.progress.isVisible()
        payload["progress_band_px"] = bar_measure.teal_band_height(
            dialog.progress, shot[:-4] + "_bar.png")
        payload["progress_dpr"] = float(dialog.progress.devicePixelRatioF())

        rows = result.get("segments", [])
        payload["status"] = dialog.lbl_status.text()
        payload["cancelled"] = bool(result.get("cancelled"))
        payload["failed"] = list(result.get("failed") or [])
        payload["segments"] = [{"name": os.path.basename(row["path"]),
                                "start": row["start"], "span": row["span"],
                                "mode": row["mode"], "actual": row["actual"]}
                               for row in rows]
        payload["joints"] = [round(rows[i]["start"] - (rows[i - 1]["start"]
                                                       + rows[i - 1]["span"]), 4)
                             for i in range(1, len(rows))]
        payload["on_disk"] = sorted(n for n in os.listdir(out_dir)) \
            if os.path.isdir(out_dir) else []
        for row, listed in zip(payload["segments"], rows):
            # Do LAI tren dia, bang ffprobe va bang mau, khong tin ket qua ham
            # tra ve: bundle phai tu chung minh file no ghi ra doc duoc.
            row["probe"] = splitter.probe_duration(listed["path"])
            source_hue = _mean_hue(src, listed["start"] + listed["span"] / 2.0)
            part_hue = _mean_hue(listed["path"], listed["span"] / 2.0)
            if source_hue is None or part_hue is None:
                payload["hue_gaps"].append(None)
                continue
            payload["hue_gaps"].append(round(min(
                abs(source_hue - part_hue),
                360.0 - abs(source_hue - part_hue)), 2))
        grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
        payload["distinct_colors"] = len({
            grabbed.pixel(x, y) for x in range(0, grabbed.width(), 4)
            for y in range(0, grabbed.height(), 4)})
    finally:
        if dialog is not None:
            dialog.close()
        card.deleteLater()
        win.close()
        pump(8)

    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    fails = split_report_fails(payload)
    for name in fails:
        print("  split-report DO: %s" % name)
    return 0 if not fails else 1


# Gia tri that cua tung loai property, dung cho fixture "du 6 lane" o ca
# --graph-report lan probe: mot do thi mo 6 lane ma opacity ghi "756%" thi
# khong con la bang chung cua mot ung dung that nua.
LANE_FIXTURE = {
    "x": (-600.0, 600.0),
    "y": (300.0, -300.0),
    "scale_x": (0.8, 1.4),
    "scale_y": (1.4, 0.8),
    "rotation": (-30.0, 45.0),
    "opacity": (0.2, 1.0),
}


def run_graph_report(argv=None):
    """Đồ thị đường cong keyframe — cửa thật, kéo thật, đo từ bản exe đã cài.

    --selftest chỉ chứng minh module có trong bundle. Năm thứ phải do chính
    file exe cài vào máy tự đo, vì source luôn đúng:
      * ``MainWindow._open_keyframe_graph`` mở được hộp thoại thật;
      * một cú kéo chuột thật đưa model tới ĐÚNG giá trị của pixel đích, và
        bắt đầu NGOÀI bán kính bam thì model không nhúc nhích (chứng minh thay
        đổi đến từ node, không phải từ đường dẫn chuột);
      * undo/redo trên stack của timeline làm viên kim cương trên timeline chạy
        theo — đi thẳng qua stack, không qua hộp thoại;
      * đường người ta nhìn thấy trên đồ thị là đường ``interpolate_keyframes``
        trả ra, đo bằng pixel trên ảnh grab;
      * cột số của sáu lane phải ĐỌC ĐƯỢC: không dòng nhãn nào đè lên dòng khác
        (đo bằng pixel mực, vì lỗi này không crash và không sai số);
      * ảnh bằng chứng phải là bản sao 1:1 của cửa thật: lane dán bằng QRect theo
        kích thước THIẾT BỊ, và số nhãn in ra có dấu trừ phải ĐÚNG BẰNG số lane
        có đáy miền âm. Dán ``drawPixmap(x, y, pm)`` ảnh DPR 1.25 lên canvas DPR 1
        co ảnh lại 80%: "-372px" mất nét trừ, ảnh tự nói sai mà không crash.

    Clinging.exe --graph-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_graph")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    import numpy as np
    from PySide6.QtCore import QEvent, QRect, QPointF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from core import keyframe_graph as kg
    from core.keyframe_manager import frame_ease, frame_time, frame_value
    from core.timeline_model import track_type_for_media
    from ui.keyframe_graph_dialog import HIT_RADIUS, color_of

    def pump(count=8):
        for _ in range(count):
            app.processEvents()

    def send(widget, kind, pos):
        """Kiem chuot that gui toi widget (bo bat su kien, khong mo hop thoai
        moi) — giong het duong ma probe da dung tren source."""
        held = (Qt.LeftButton if kind in (QEvent.MouseButtonPress,
                                         QEvent.MouseMove)
                else Qt.MouseButton.NoButton)
        QApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(pos), widget.mapToGlobal(pos.toPoint()),
            Qt.LeftButton, held, Qt.KeyboardModifier.NoModifier))

    def drag(view, lane, from_time, from_value, to_time, to_value, dx=0.0):
        start = QPointF(lane.x_of(from_time) + dx, lane.y_of(from_value))
        end = QPointF(lane.x_of(to_time), lane.y_of(to_value))
        send(view, QEvent.MouseButtonPress, start)
        send(view, QEvent.MouseMove, end)
        send(view, QEvent.MouseButtonRelease, end)
        pump()

    def frame_row(clip, prop):
        return [(round(frame_time(f), 4), round(frame_value(f), 4),
                 frame_ease(f)) for f in kg.frames_of(clip, prop)]

    def node_times(item, prop):
        return sorted(round(node.time_sec, 3) for node in item._keyframe_nodes
                      if node.property_key == prop)

    def curve_check(view, clip, times):
        """Do duong VE so voi duong MODEL: cot anh tai t phai nam dung
        y_of(gia tri interpolate_keyframes), va chi mot doan net moi cot."""
        lane = view.lane_for("x", clip)
        pix = view.grab()
        dpr = pix.devicePixelRatio() or 1.0
        img = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        arr = np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4)).astype(np.float64)
        accent = np.array([color_of("x").red(), color_of("x").green(),
                           color_of("x").blue()], float)
        default = kg.default_value(clip, "x")
        top = int(round(lane.rect.top() * dpr))
        bottom = int(round(lane.rect.bottom() * dpr))
        worst = 0.0
        runs = []
        for time in times:
            want = lane.y_of(kg.interpolate_at(lane.frames, "x", default, time))
            x = int(round(lane.x_of(time) * dpr))
            if not 0 <= x < arr.shape[1]:
                continue
            column = arr[top:bottom + 1, x, :3]
            hit = np.abs(column - accent).sum(axis=1) < 150.0
            if not hit.any():
                # Cot khong co net nao: lech vo so, gate tren payload se no.
                return None, len(runs), runs
            rows = np.nonzero(hit)[0]
            runs.append(int((np.diff(rows) > max(2, int(round(2 * dpr))
                                                 )).sum()) + 1)
            worst = max(worst, abs((rows.mean() + top) / dpr - want))
        return round(worst, 2), len(runs), runs

    def gutter_profile(source, source_dpr):
        """(cao dong nhan lon nhat, le hep nhat, so dong, cao chu, so nhan dau
        tru) cua cot so.

        Do tren ANH do chinh exe ve ra: loi cua cot so khong crash va khong sai
        so — no chi in hai dong chu de len nhau thanh mot bo so doc khong duoc,
        nen chi con cach dem pixel muc theo tung dong.

        ``source_dpr`` phai la ty le pixel cua ANH CHUA NHAN, khong phai cua
        thiet bi dang do: khi nhan bi ep xuong (ve vao canvas DPR 1) thi nhung
        net mong nhu dau tru bi nao hut mat, va mot con so am in ra khong con
        dau am. Dem dau tru cung luc nay de khong the im lang duoc nua.
        """
        from PySide6.QtGui import QFontMetrics
        from ui.keyframe_graph_dialog import AXIS_TEXT, VALUE_LABEL_RIGHT
        dpr = float(source_dpr) or 1.0
        img = (source.toImage() if hasattr(source, "toImage") else source)
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        arr = np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4)).astype(np.float64)
        target = np.array([AXIS_TEXT.red(), AXIS_TEXT.green(),
                           AXIS_TEXT.blue()], float)
        x0 = int(round((VALUE_LABEL_RIGHT - 70) * dpr))
        x1 = int(round((VALUE_LABEL_RIGHT + 2) * dpr))
        band = arr[:, max(0, x0):max(0, x1), :3]
        mask = (np.abs(band - target).sum(axis=2) < 90.0)
        hit = mask.any(axis=1)
        rows = [int(r) for r in np.nonzero(hit)[0]]
        runs, start, prev = [], None, None
        for row in rows:
            if start is None:
                start = prev = row
            elif row - prev > 3:
                runs.append((start, prev))
                start = row
            prev = row
        if start is not None:
            runs.append((start, prev))
        font = view.font()
        font.setPointSizeF(8.4)
        text_h = float(QFontMetrics(font).height()) / dpr
        heights = [(b - a + 1) / dpr for a, b in runs]
        gaps = [(runs[i + 1][0] - runs[i][1] - 1) / dpr
                for i in range(len(runs) - 1)]
        # Mot nhan co dau tru khi khoi dau no la mot dao mong (<= 6 px, cao
        # <= 2 px) tach roi khoi chu bang it nhat mot cot trong.
        minuses = 0
        for a, b in runs:
            cols = mask[a:b + 1, :].any(axis=0)
            ink = np.nonzero(cols)[0]
            if len(ink) < 3:
                continue
            head = [ink[0]]
            for c in ink[1:]:
                if c != head[-1] + 1:
                    break
                head.append(c)
            if len(head) > max(2, int(round(6 * dpr))):
                continue
            rows_hit = mask[a:b + 1, head[0]:head[-1] + 1].any(axis=1)
            if int(rows_hit.sum()) <= max(1, int(round(2 * dpr))) \
                    and len(ink) - len(head) > len(head):
                minuses += 1
        return (round(max(heights or [0]), 1), round(min(gaps or [0]), 1),
                len(runs), round(text_h, 1), minuses)

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
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
    win._sync_canvas()
    pump()
    item = win.timeline_panel.scene._clip_items[clip.clip_id]
    item.sync_keyframe_nodes_from_model()

    # Diem vao cua app: hop thoai dung lai, khong nhan ban khi mo clip khac.
    dialog = win._open_keyframe_graph(clip.clip_id)
    dialog.move(360, 200)
    pump()
    again = win._open_keyframe_graph(clip.clip_id)
    view = dialog.view
    stack = win.timeline_panel.undo_stack
    base = stack.undo_count
    before = frame_row(model.get_clip(clip.clip_id), "x")

    # 1. NGOAI ban kinh bam: cu keo khong duoc cham vao model.
    lane = view.lane_for("x")
    drag(view, lane, 1.0, 600.0, 0.4, 100.0, dx=HIT_RADIUS + 6)
    outside = frame_row(model.get_clip(clip.clip_id), "x")
    outside_delta = stack.undo_count - base
    outside_selected = view._selected

    # 2. TRONG ban kinh bam: model nhan dung (thoi gian, gia tri) cua pixel.
    drag(view, view.lane_for("x"), 2.0, -100.0, 1.5, 250.0)
    dragged = frame_row(model.get_clip(clip.clip_id), "x")
    drag_delta = stack.undo_count - base

    # 3. undo/redo tu STACK CUA TIMELINE (khong qua hop thoai) — kim cuong
    #    tren timeline phai di theo, khong duoc o lai vi tri cu.
    stack.undo()
    pump()
    undone = frame_row(model.get_clip(clip.clip_id), "x")
    undone_nodes = node_times(item, "x")
    stack.redo()
    pump()
    redone = frame_row(model.get_clip(clip.clip_id), "x")
    redone_nodes = node_times(item, "x")

    # 4. Duong tren man hinh = duong cua model, tai trang thai dang nhin thay.
    worst_px, columns, column_runs = curve_check(
        view, model.get_clip(clip.clip_id),
        (0.2, 0.5, 0.8, 1.2, 1.38))
    panel_dragged = dialog.grab()

    # 5. Sau property, sau lane — do thi phai tu co theo tung don vi.
    wide_track = model.add_track(track_type_for_media("text"), "Wide")
    wide = model.add_clip(wide_track.track_id, "", "text", 4.0, 7.0,
                          "Du property")
    for index, prop in enumerate(kg.PROPERTY_ORDER):
        first, second = LANE_FIXTURE[prop]
        wide.add_keyframe(prop, 0.0, first, "ease_in_out")
        wide.add_keyframe(prop, 1.0 + index, second, "ease_out")
    win._sync_canvas()
    pump()
    dialog.set_clip(wide.clip_id)
    pump()
    wide_lanes = view._lanes(model.get_clip(wide.clip_id))
    lanes = [l.prop for l in wide_lanes]
    lane_heights = [round(l.rect.height(), 1) for l in wide_lanes]
    # Bao nhieu lane co day so AM — do la so dau tru phai nam duoc tren ANH.
    want_minuses = sum(1 for l in wide_lanes if l.lo < 0)
    panel_lanes = view.grab()

    captions = [
        "exe: %s (frozen=%s)" % (os.path.abspath(sys.argv[0]),
                                 bool(getattr(sys, "frozen", False))),
        "keo ngoai %d px: model khong doi=%s, undo delta=%d, selection=%r"
        % (HIT_RADIUS + 6, outside == before, outside_delta, outside_selected),
        "keo dung tam: model=%r (muon (1.5, 250.0)), undo delta=%d"
        % (dragged[-1], drag_delta),
        "undo tu stack timeline: model=%r, kim cuong x=%r" % (undone[-1],
                                                             undone_nodes),
        "redo: model=%r, kim cuong x=%r" % (redone[-1], redone_nodes),
        "duong ve so voi model: lech lon nhat=%.2f px qua %d cot, doan net "
        "moi cot=%r" % (worst_px if worst_px is not None else -1, columns,
                        column_runs),
        "6 lane=%r cao=%r" % (lanes, lane_heights),
        None,
    ]
    pad, cap_h = 12, 20 + 20 * len(captions)
    width = pad * 3 + max(panel_dragged.width(), panel_lanes.width())
    height = pad * 3 + cap_h + panel_dragged.height() + panel_lanes.height()
    canvas = QImage(width, height, QImage.Format_RGB32)
    canvas.fill(QColor("#0F1014").rgb())
    lanes_y = pad * 2 + panel_dragged.height()
    painter = QPainter(canvas)
    # Ve vao QRect theo KICH THUOC THIET BI. drawPixmap(x, y, pm) tren canvas
    # DPR 1 hieu pixmap DPR 1.25 la kich thuoc LOGIC va ep no xuong 80%: nhung
    # net mong nhu dau tru o cot so bi nao hut mat, va anh chung in ra mot con
    # so AM khong con dau am — sai hon ca man hinh that.
    painter.drawPixmap(QRect(pad, pad, panel_dragged.width(),
                             panel_dragged.height()), panel_dragged)
    painter.drawPixmap(QRect(pad, lanes_y, panel_lanes.width(),
                             panel_lanes.height()), panel_lanes)
    painter.end()

    # Sau lane la luc cot so de len nhau nhat: moi lane chi con ~48 px. Do tren
    # vung anh vua ghe — tuc la do dung thu nguoi ta nhin thay.
    tallest, tightest, label_rows, glyph_h, minus_labels = gutter_profile(
        canvas.copy(QRect(pad, lanes_y, panel_lanes.width(),
                          panel_lanes.height())),
        panel_lanes.devicePixelRatio() or 1.0)
    captions[-1] = ("cot so 6 lane: %d dong, cao nhat=%.1fpx (chu %.1fpx), le "
                    "hep nhat=%.1fpx, dau tru=%d/%d"
                    % (label_rows, tallest, glyph_h, tightest, minus_labels,
                       want_minuses))
    painter = QPainter(canvas)
    painter.setFont(QFont("Segoe UI", 9))
    painter.setPen(QPen(QColor("#C8CBD4")))
    text_y = lanes_y + panel_lanes.height() + pad + 16
    for line in captions:
        painter.drawText(pad + 2, text_y, line)
        text_y += 20
    painter.end()
    canvas.save(shot)

    colors = 0
    if os.path.isfile(shot):
        grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
        colors = len({grabbed.pixel(x, p_)
                      for x in range(0, grabbed.width(), 4)
                      for p_ in range(0, grabbed.height(), 4)})

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "dialog_title": dialog.windowTitle(),
        "clip_title": dialog.lbl_title.text(),
        "hop_thoai_dung_lai": again is dialog,
        "modal": dialog.isModal(),
        "lanes": lanes,
        "lane_heights": lane_heights,
        "truoc_khi_keo": before,
        "keo_ngoai_ban_kinh": {"model": outside, "undo_delta": outside_delta,
                               "selected": outside_selected},
        "keo_dung_tam": {"model": dragged, "undo_delta": drag_delta},
        "undo": {"model": undone, "diamonds_x": undone_nodes},
        "redo": {"model": redone, "diamonds_x": redone_nodes},
        "duong_ve": {"max_lech_px": worst_px, "cot_do": columns,
                     "doan_net": column_runs},
        "cot_so": {"dong": label_rows, "cao_nhat_px": tallest,
                   "le_hep_nhat_px": tightest, "cao_chu_px": glyph_h,
                   "dau_tru": minus_labels, "dau_tru_muon": want_minuses},
        "screenshot": os.path.abspath(shot),
        "distinct_colors": colors,
        "captions": captions,
    }
    dialog.close()
    win.close()
    pump(8)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    ok = (payload["hop_thoai_dung_lai"] and not payload["modal"]
          and outside == before and outside_delta == 0
          and outside_selected is None
          and dragged[-1] == (1.5, 250.0, "ease_out_expo")
          and drag_delta == 1
          and undone[-1] == (2.0, -100.0, "ease_out_expo")
          and undone_nodes == [0.0, 1.0, 2.0]
          and redone[-1] == (1.5, 250.0, "ease_out_expo")
          and redone_nodes == [0.0, 1.0, 1.5]
          and worst_px is not None and worst_px <= 2.5 and columns >= 4
          and all(runs == 1 for runs in column_runs)
          and lanes == list(kg.PROPERTY_ORDER)
          and label_rows >= 2 * len(lanes) and tallest <= glyph_h + 3.0
          and tightest >= 2.0
          and want_minuses >= 3 and minus_labels == want_minuses
          and len(set(lane_heights)) == 1 and colors > 40
          and os.path.isfile(shot))
    return 0 if ok else 1


def _report_wav(seconds=4.0):
    """Mot file .wav that trong TEMP: plan xuat chi xet clip co tieng that."""
    import wave
    import tempfile
    frames = int(48000 * seconds)
    path = os.path.join(tempfile.gettempdir(), "clinging_audio_report.wav")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00\x00\x00" * frames)
    return path


def run_audio_report(argv=None):
    """Anh that the Am thanh + chuoi filter xuat, do tu DUNG ban exe nay.

    Nguon code nao ve cung cai card ay, nen anh chup bang source khong noi len
    duoc dieu gi ve ban da dong goi. Day chay MainWindow that, PropertiesPanel
    that, roi goi dung bo tao plan cua exporter.

    Clinging.exe --audio-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_audio")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_window import MainWindow
    from core.timeline_model import TrackType
    from core import audio_mix

    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    for _ in range(12):
        app.processEvents()

    tl = win.timeline_panel
    for old in list(tl.model.tracks):
        tl.model.remove_track(old.track_id)
    track = tl.model.add_track(TrackType.AUDIO)
    clip = tl.model.add_clip(track.track_id, _report_wav(), "audio", 0.0, 4.0,
                             "tone.wav")
    applied = tl.model.set_clip_audio(clip.clip_id, volume=0.45, speed=1.0,
                                      fade_in=0.5, fade_out=0.0)
    win.properties_panel.show_clip_properties(clip)
    for _ in range(12):
        app.processEvents()

    editor = win.properties_panel.current_editor
    card = getattr(editor, "card_audio", None)
    shown = card is not None and card.isVisible()
    sliders = ([editor.slider_volume.value(), editor.slider_speed.value(),
                editor.slider_fade_in.value(), editor.slider_fade_out.value()]
               if shown else None)
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"
    colors = 0
    if shown:
        image = card.grab().toImage()
        colors = len({image.pixel(x, y)
                      for x in range(0, image.width(), 3)
                      for y in range(0, image.height(), 3)})
        card.grab().save(shot)

    graph = audio_mix.build_filter_complex(
        tl.model, audio_mix.collect_audio_clips(tl.model, {}), tl.model.duration)
    tokens = [token for token in ("volume=0.450000,", "afade=t=in:")
              if token in graph]
    ok = (applied.get("volume") == 0.45 and applied.get("fade_in") == 0.5 and
          sliders == [45, 100, 50, 0] and colors > 20 and len(tokens) == 2 and
          os.path.isfile(shot))

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "card_visible": shown,
        "sliders": sliders,
        "distinct_colors": colors,
        "screenshot": os.path.abspath(shot) if shown else "",
        "export_tokens": tokens,
        "graph": graph[:200],
    }
    # Chon clip audio da keo QMediaPlayer cua MainWindow den file wav fixture va
    # cho no chay: window dong bang `win.close()` van de player song, va teardown
    # cua no abort 0xC0000409 (do 23/10/2026: rc=3221226505 tren CA tree nguon lan
    # worktree HEAD, sau khi payload da ghi xong) — nen rc cua --audio-report
    # vu kho tin. Phai dung + tha source roi moi dong window.
    from PySide6.QtCore import QUrl
    player = getattr(win, "_audio_player", None)
    if player is not None:
        player.stop()
        player.setSource(QUrl())
        for _ in range(6):
            app.processEvents()
    win.close()
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0 if ok else 1


def signal_names(widget):
    """Mọi tín hiệu của widget, tính cả tín hiệu thừa kế.

    PySide6 không phơi QMetaObject.Signal ra lớp QMetaObject, và phần "tín hiệu
    riêng của lớp này" của QPushButton chỉ có showMenu() — clicked nằm ở
    QAbstractButton. Lọc theo superClass sẽ bỏ đúng thứ cần tìm, nên phải quét
    cả metaObject và so sánh theo tên enum.
    """
    meta = widget.metaObject()
    out = []
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType().name != "Signal":
            continue
        signature = bytes(method.methodSignature()).decode()
        if signature not in out:
            out.append(signature)
    return out


def raw_receivers(obj):
    """Số receiver trên mọi tín hiệu "hành động" của obj, chưa trừ nền."""
    total = 0
    for signature in signal_names(obj):
        name = signature.split("(")[0]
        # Bỏ tín hiệu nội bộ Qt — app không bao giờ nối chúng.
        if name.startswith(("destroyed", "objectName", "customContextMenu",
                            "windowTitle", "modal", "enabled", "focus")):
            continue
        for spelling in ("2" + signature, signature):
            try:
                found = obj.receivers(spelling)
            except Exception:
                found = 0
            if found:
                total += found
                break
    return total


def _fresh_instance(cls):
    """Một instance của chính lớp đó, chưa nối gì, để đo nền.

    Lớp tùy biến (IconButton, PropTab...) không construct được không tham số;
    lùi theo MRO tới lớp gần nhất làm được — QToolButton là đủ cho IconButton.
    """
    for candidate in cls.__mro__:
        if candidate is object:
            continue
        try:
            return candidate()
        except Exception:
            continue
    return None


_BASELINE = {}


def baseline_count(obj):
    """Nền của một object chưa ai nối, đo trên đúng lớp của nó.

    QToolButton tự nối pressed()/released() vào slot riêng, QMenu tự nối
    triggered của mỗi action nó chứa — nên "có receivers" không đồng nghĩa với
    "app có xử lý". Không trừ nền thì mọi control chết đều bị báo là sống.
    """
    cls = type(obj)
    if cls not in _BASELINE:
        probe = _fresh_instance(cls)
        _BASELINE[cls] = raw_receivers(probe) if probe is not None else 0
    return _BASELINE[cls]


def own_connection_count(obj):
    return max(0, raw_receivers(obj) - baseline_count(obj))


def group_of(widget):
    """QButtonGroup chứa widget này, nếu có.

    AnimatedTabBar nối group.idClicked chứ không nối clicked của từng nút, nên
    một nút "0 receivers" vẫn sống thật. Bỏ qua đường này thì máy dò buộc phải
    sửa code đang chạy đúng.
    """
    from PySide6.QtWidgets import QButtonGroup
    parent = widget.parent()
    while parent is not None:
        for child in parent.children():
            if isinstance(child, QButtonGroup) and widget in child.buttons():
                return child
        parent = parent.parent()
    return None


def menu_of(widget):
    """QMenu mà widget bật lên khi bấm (QPushButton/QToolButton.setMenu).

    Nút kiểu này không cần ai nối clicked: Qt tự mở menu. Nó chỉ chết khi menu
    của nó không có action sống nào.
    """
    try:
        return widget.menu()
    except Exception:
        return None


def live_actions(menu):
    """Action trong menu này có slot của app — dùng để xử nút dạng menu."""
    base = orphan_baseline(menu)
    out = []
    for action in menu.actions():
        if action.isSeparator() or not action.isVisible() \
                or not action.isEnabled():
            continue
        if action_connection(action) > base:
            out.append(action)
    return out


def connection_count(widget):
    total = own_connection_count(widget)
    if total == 0:
        group = group_of(widget)
        if group is not None:
            total = own_connection_count(group)
    if total == 0:
        menu = menu_of(widget)
        if menu is not None:
            total = len(live_actions(menu))
    return total


def path_of(widget):
    parts = []
    node = widget
    while node is not None and len(parts) < 5:
        label = node.objectName() or type(node).__name__
        parts.append(label)
        node = node.parent()
    return "/".join(reversed(parts))


def describe(widget):
    text = ""
    for getter in ("text", "placeholderText", "toolTip"):
        try:
            value = getattr(widget, getter)()
        except Exception:
            value = ""
        if value:
            text = str(value)
            break
    return "%s(%r) @ %s" % (type(widget).__name__, text[:34], path_of(widget))


def visible_interactive(root):
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QLineEdit,
                                   QPushButton, QRadioButton, QSlider,
                                   QTabBar, QToolButton, QWidget)
    classes = (QPushButton, QToolButton, QCheckBox, QRadioButton, QComboBox,
               QLineEdit, QSlider, QTabBar)
    found = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, classes):
            continue
        if not widget.isVisible() or not widget.isEnabled():
            continue
        found.append(widget)
    return found


def collect_menus(root):
    """Mọi QMenu với tới được từ root, kể cả menu KHÔNG có cha.

    QToolButton.setMenu() và QAction.setMenu() không reparent cái menu, còn
    TitleBar giữ main_menu bằng thuộc tính Python. findChildren(QMenu) vì thế
    không thấy cả menu của nút "Menu" — audit im lặng bỏ sót đúng chỗ hay chết
    nhất.
    """
    from PySide6.QtWidgets import QMenu, QWidget
    found = []
    seen = set()

    def push(menu):
        if menu is None or id(menu) in seen:
            return
        seen.add(id(menu))
        found.append(menu)
        for action in menu.actions():
            try:
                push(action.menu())
            except Exception:
                pass

    for menu in root.findChildren(QMenu):
        push(menu)
    for widget in root.findChildren(QWidget):
        push(menu_of(widget))
        for action in widget.actions():
            try:
                push(action.menu())
            except Exception:
                pass
    return found


def menu_label(menu):
    return (menu.objectName() or menu.title() or path_of(menu)
            or type(menu).__name__)


def visible_menu_actions(root):
    """QMenu không 'visible' cho tới khi mở, nên phải soi cả action của nó."""
    out = []
    for menu in collect_menus(root):
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible() \
                    or not action.isEnabled():
                continue
            out.append((menu, action))
    return out


def action_connection(action):
    total = 0
    for signature in signal_names(action):
        for spelling in ("2" + signature, signature):
            try:
                found = action.receivers(spelling)
            except Exception:
                found = 0
            if found:
                total += found
                break
    return total


def orphan_baseline(menu):
    """Số receivers của một action vừa được thêm vào chính menu này.

    QMenu tự nối triggered của mỗi action nó chứa vào slot riêng của menu, nên
    một action mồ côi vẫn có receivers > 0. Đếm tuyệt đối sẽ báo "sống" cho mọi
    action trong menu — gate phải so với chuẩn do chính menu đó tạo ra.
    """
    from PySide6.QtGui import QAction
    probe = QAction("probe-mo-coi", menu)
    probe.setCheckable(True)
    menu.addAction(probe)
    baseline = action_connection(probe)
    menu.removeAction(probe)
    return baseline


def audit_chrome(label, root):
    """Liệt kê control tương tác nhìn thấy được mà không có slot nào."""
    dead = []
    widgets = visible_interactive(root)
    for widget in widgets:
        if connection_count(widget) == 0:
            dead.append(("widget", describe(widget)))
    menus = collect_menus(root)
    actions = visible_menu_actions(root)
    live = {}
    for menu, _action in actions:
        if menu not in live:
            live[menu] = {id(item) for item in live_actions(menu)}
    for menu, action in actions:
        if id(action) not in live[menu]:
            dead.append(("action", "%s:%s" % (menu_label(menu),
                                              action.text())))
    return {"label": label, "controls": len(widgets), "menus": len(menus),
            "menu_actions": len(actions),
            "dead": ["%s %s" % (kind, name) for kind, name in dead]}


def alpha_signature(button, size=24):
    """Chữ ký raster của icon đang gắn trên nút: số pixel đặc + tổng alpha.

    isNull() không chứng minh icon hiện ra (icon không màu cho pixmap rỗng
    vẫn not-null), và tên icon thì đổi được mà không đổi hình. Đây là pixel thật.
    """
    from PySide6.QtGui import QImage
    pixmap = button.icon().pixmap(size, size)
    if pixmap.isNull():
        return (0, 0)
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    solid = 0
    total_alpha = 0
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = image.pixel(x, y) & 0xFF
            total_alpha += alpha
            if alpha:
                solid += 1
    return (solid, total_alpha)


def measure_focus_toggle(window):
    """Bấm nút toàn màn hình timeline và đo hậu quả thật trên splitter."""
    from PySide6.QtWidgets import QApplication
    header = window.timeline_panel.header
    sizes0 = list(window.work_splitter.sizes())
    ink0 = alpha_signature(header.btn_focus)
    header.btn_focus.click()
    for _ in range(6):
        QApplication.processEvents()
    sizes1 = list(window.work_splitter.sizes())
    ink1 = alpha_signature(header.btn_focus)
    header.btn_focus.click()
    for _ in range(6):
        QApplication.processEvents()
    sizes2 = list(window.work_splitter.sizes())
    return {
        "before": sizes0, "focused": sizes1, "restored": sizes2,
        "timeline_grows": sizes1[1] > sizes0[1],
        "preview_shrinks": sizes1[0] < sizes0[0],
        "icon_pixels_before": ink0, "icon_pixels_focus": ink1,
        "icon_changed": ink0 != ink1 and ink1[0] > 0,
        "restore_exact": sizes2 == sizes0,
    }


def run_chrome_report(argv=None):
    """Kiểm tra "chrome sống" trên CHINH ban exe nay.

    Nút bấm không ra gì là loi nguoi dung thay ngay, nhưng no khong crash va
    khong de lai dấu vết nao trong log, nen chi co mot cay do ket noi that cua
    bundle da cai moi chung minh duoc. --selftest goi cay do nay;
    --chrome-report in ra ban ke chi tiet va anh bang chung.

    Clinging.exe --chrome-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_chrome")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from ui.main_controller import MainController
    controller = MainController()
    controller.show()
    for _ in range(25):
        app.processEvents()
    home = audit_chrome("Trang chủ", controller.home_page)

    from ui.main_window import MainWindow
    editor = MainWindow()
    editor.resize(1500, 900)
    editor.show()
    for _ in range(25):
        app.processEvents()
    editor_rows = audit_chrome("Editor", editor)

    shot = os.path.join(os.path.dirname(out) or ".", "clinging_chrome_focus.png")
    editor.timeline_panel.header.btn_focus.click()
    for _ in range(10):
        app.processEvents()
    editor.grab().save(shot)
    editor.timeline_panel.header.btn_focus.click()
    for _ in range(10):
        app.processEvents()

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "audit": [home, editor_rows],
        "dead": home["dead"] + editor_rows["dead"],
        "focus": measure_focus_toggle(editor),
        "screenshot": os.path.abspath(shot),
    }
    editor.close()
    controller.close()
    for _ in range(8):
        app.processEvents()
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    ok = (not payload["dead"]
          and all(payload["focus"][key] for key in
                  ("timeline_grows", "preview_shrinks", "icon_changed",
                   "restore_exact")))
    return 0 if ok else 1


def _chrome_ok():
    """Mot dong trong --selftest: 0 control nhin thay duoc ma khong co slot."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from ui.main_controller import MainController
    controller = MainController()
    controller.show()
    for _ in range(20):
        app.processEvents()
    rows = [audit_chrome("Trang chủ", controller.home_page)]

    from ui.main_window import MainWindow
    editor = MainWindow()
    editor.resize(1600, 900)
    editor.show()
    for _ in range(20):
        app.processEvents()
    rows.append(audit_chrome("Editor", editor))
    editor.close()
    controller.close()
    for _ in range(8):
        app.processEvents()

    dead = [item for row in rows for item in row["dead"]]
    if dead:
        raise RuntimeError("chat: %s" % dead[:6])
    return ", ".join("%s %d nut/%d menu/%d action" % (
        row["label"], row["controls"], row["menus"], row["menu_actions"])
        for row in rows)


def _keyframe_easing_ok():
    """Mot dong trong --selftest: bang cong easing that, va funnel noi suy dung no.

    Gate nay phai co that bai duoc: neu interpolate_keyframes quay ve lerp
    tuyen tinh thi ba ten cong cho cung mot gia tri o giua doan va dong nay no.
    """
    from core.keyframe_manager import EASINGS, apply_ease, interpolate_keyframes

    broken = []
    for name in sorted(EASINGS):
        samples = [apply_ease(name, i / 100.0) for i in range(101)]
        if abs(samples[0]) > 1e-9 or abs(samples[-1] - 1.0) > 1e-9:
            broken.append("%s: doi dau" % name)
        elif any(s < -1e-9 or s > 1.0 + 1e-9 for s in samples):
            broken.append("%s: vuot [0,1]" % name)
        elif any(samples[i + 1] < samples[i] - 1e-9 for i in range(100)):
            broken.append("%s: khong don dieu tang" % name)
    if broken:
        raise RuntimeError(", ".join(broken[:6]))

    # Doan 0s(gia tri 0) -> 1s(gia tri 100): gia tri do duoc o giua doan phai
    # bang 100 * f(0.5) cua dung cong cua keyframe dau.
    middle = {name: interpolate_keyframes([(0.0, 0.0, name), (1.0, 100.0)], 0.5)
              for name in sorted(EASINGS)}
    wrong = [name for name in middle
             if abs(middle[name] - 100.0 * apply_ease(name, 0.5)) > 1e-6]
    if wrong:
        raise RuntimeError("noi suy bo duong cong: %s" % wrong[:6])
    if len(set(round(v, 6) for v in middle.values())) < 4:
        raise RuntimeError("moi ten cong cho mot gia tri khac nhau o giua doan")
    return "%d duong cong, giua doan: linear %.1f / in %.1f / out %.1f" % (
        len(EASINGS), middle["linear"], middle["ease_in"], middle["ease_out"])


def _popart_ok():
    """Mot dong trong --selftest: bon chang ve pop art lam viec THAT.

    Gate nay phai co that bai duoc: neu posterize_rgb / halftone_rgb /
    outline_rgb / contrast_rgb bi gia lap thanh "tra nguyen anh" thi ca bon
    kich thuoc duoi day (so bac mau, dien tich muc, do toi bien, do roi cua
    duoi mau) dong loai no. Ham duoc goi qua thuoc tinh module
    (clip_effects.posterize_rgb) vi chinh le do, de phep gia lap ben ngoai
    nhìn thay duoc — do that cua module se vo hieu hoa phan chung nay.
    """
    import numpy as np
    from core import clip_effects

    w = 96
    ramp = np.linspace(0.0, 255.0, w, dtype=np.float32)
    grey = np.repeat(ramp[:, None], 3, axis=1)
    img = np.tile(grey[None, :, :], (w, 1, 1))  # (w, w, 3), doc ramp theo truc x

    # 1) Posterize: nen thi phai con DUNG so bac, khong phai giua nguyen 96 muc.
    for levels in (2, 4, 8):
        got = int(len(np.unique(np.round(clip_effects.posterize_rgb(img, levels)[:, :, 0], 3))))
        if got != levels:
            raise RuntimeError("posterize %d bac con %d bac" % (levels, got))

    # 2) Halftone: vung toi phai nap muc nhieu hon vung sang rat ro.
    def ink(v):
        out = clip_effects.halftone_rgb(np.full((w, w, 3), v, np.float32), 6.0)
        return float(np.mean(clip_effects._luma(out) < v - 1.0))

    dark, light = ink(32.0), ink(224.0)
    if not (dark > 0.30 and dark - light > 0.25):
        raise RuntimeError("halftone khong nap muc theo do toi: toi %.2f sang %.2f"
                           % (dark, light))

    # 3) Outline: mang phang nguyen ven 100%, bien do sang thi toi di.
    flat = np.full((w, w, 3), 128.0, np.float32)
    if float(np.abs(clip_effects.outline_rgb(flat, 0.9) - flat).max()) != 0.0:
        raise RuntimeError("outline cham ca vung phang")
    # Bien do sang phai toi mot ben duoi gia tri cua chinh no, nen cot ke ben
    # phai la 235 con cot ke ben phai la 120: net viem ro 30 -> 90 duoi nay
    # phan biet ham ve that voi ban "tra nguyen anh".
    cols = np.where(np.arange(w) < w // 2, 235.0, 120.0).astype(np.float32)
    edge = np.tile(cols[None, :, None], (w, 1, 3))
    edge_out = clip_effects.outline_rgb(edge, 0.35)
    seam = float(edge_out[:, w // 2, 0].min())       # cot dau tien cua ben toi
    lit = float(edge_out[:, 2, 0].mean())            # vung sang bang phang
    quiet = float(edge_out[:, w - 1, 0].mean())      # vung toi bang phang
    if seam > 120.0 - 30.0:
        raise RuntimeError("outline khong dam bien: seam %.1f" % seam)
    if abs(lit - 235.0) > 1.0 or abs(quiet - 120.0) > 1.0:
        raise RuntimeError("outline lan vung phang: sang %.1f toi %.1f" % (lit, quiet))

    # 4) Contrast: la HE SO nhan quanh 128 (kéo giãn duoi mau), khong phai
    #    cong thuc 259/(259-c) dao nguoc anh nhu ban cu.
    lifted = clip_effects.contrast_rgb(img, 1.25, 1.0)
    spread = float(lifted.std()) / float(img.std())
    corr = float(np.corrcoef(clip_effects._luma(lifted).ravel(),
                             clip_effects._luma(img).ravel())[0, 1])
    if spread <= 1.05:
        raise RuntimeError("contrast khong keo gian duoi mau (he so %.3f)" % spread)
    if corr <= 0.99:
        raise RuntimeError("contrast dao nguoc sang toi (tuong quan %.3f)" % corr)

    # 5) Preset + the trong phai co du khoa cho bon chang tren.
    from core.timeline_model import EFFECT_PRESETS
    params = EFFECT_PRESETS.get("Pop Art", {})
    missing = [k for k in ("contrast", "saturation", "halftone", "posterize",
                           "outline") if k not in params]
    if missing:
        raise RuntimeError("preset Pop Art thieu %s" % ", ".join(missing))
    from ui.effects_panel import EFFECT_CATEGORIES
    cards = [c["name"] for c in EFFECT_CATEGORIES.get("Sắc thái", [])]
    if "Pop Art" not in cards:
        raise RuntimeError("the Pop Art khong co trong muc Sac thai")
    return ("posterize 2/4/8 bac, halftone muc %.0f%%->%.0f%%, "
            "bien toi con %.0f, contrast x%.2f" %
            (dark * 100.0, light * 100.0, seam, spread))


def _effect_liveness_ok():
    """Một dòng --selftest: không còn "thẻ ma" nào trong bảng hiệu ứng.

    Chromatic và Lens Flare từng là hai thẻ bán bằng ảnh minh hoạ: preset có
    khoá nhưng chuỗi lọc màu không có nhánh nào đọc khoá đó, nên kéo thẻ vào
    clip không đổi lấy một pixel. Cửa này đo THẲNG qua apply_color_effects
    (cùng hàm preview và export gọi), nên cả ba lỗi đều lộ ra tại đây: thiếu
    nhánh, hàm bị identity-patch, hoặc key đổi tên.

    Hướng dời của tán sắc đo bằng hai vạch sáng mỏng ở hai bên tâm: phóng to
    thì vạch bên phải đi RA xa tâm còn vạch bên trái đi NGƯỢC chiều. Một bản
    chỉ nhích cả ảnh sang một phía (lỗi kinh điển của filter CA viết vội) qua
    được ải một vạch nhưng hỏng ải hai vạch.
    """
    import numpy as np
    from PySide6.QtGui import QImage
    from core import clip_effects
    from core.timeline_model import EFFECT_PRESETS, EffectData
    from ui.effects_panel import EFFECT_CATEGORIES

    def qimage(a):
        arr = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
        h, w = arr.shape[:2]
        rgba = np.ascontiguousarray(
            np.dstack([arr, np.full((h, w, 1), 255, np.uint8)]))
        return QImage(rgba.data, w, h, w * 4,
                      QImage.Format.Format_RGBA8888).copy()

    def rgb_of(image):
        img = image.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4))[:, :, :3].astype(np.float64)

    def run(a, params, intensity=1.0):
        src = qimage(a)
        return rgb_of(clip_effects.apply_color_effects(src, [EffectData(
            name="probe", category="Bộ lọc", intensity=intensity,
            params=dict(params))]))

    # 1) Khong the mau/loc nao duoc mang khoa ma chuoi loc khong biet, va
    #    PIXEL_KEYS phải đúng bằng tập khoá các preset đang bán (khong lech
    #    hai chieu: khoa mo coi trong preset thi vo sinh, khoa trong PIXEL_KEYS
    #    ma khong the nao dung thi la do ran).
    cards = [c["name"] for t in ("Sắc thái", "Bộ lọc")
             for c in EFFECT_CATEGORIES[t]]
    used, ghost = set(), []
    for name in cards:
        params = EFFECT_PRESETS.get(name) or {}
        if not params:
            ghost.append("%s(khong preset)" % name)
            continue
        used |= set(params)
        if set(params) - set(clip_effects.PIXEL_KEYS):
            ghost.append("%s(%s)" % (name, ",".join(
                sorted(set(params) - set(clip_effects.PIXEL_KEYS)))))
    if ghost:
        raise RuntimeError("the ma: %s" % ", ".join(ghost))
    if sorted(used) != sorted(clip_effects.PIXEL_KEYS):
        raise RuntimeError("PIXEL_KEYS lech preset: thieu %s thua %s" % (
            sorted(set(clip_effects.PIXEL_KEYS) - used),
            sorted(used - set(clip_effects.PIXEL_KEYS))))

    h, w = 400, 600

    def line_x(a, ch, frac):
        lo = int(w * frac) - 30
        return int(np.argmax(a[:, :, ch][:, lo:lo + 61].mean(axis=0))) + lo

    # 2) Tan sac: hai vach mong 0.2w va 0.8w, do huong dich tung kenh.
    lines = np.full((h, w, 3), 20.0, np.float64)
    lines[:, int(w * 0.2)] = 250.0
    lines[:, int(w * 0.8)] = 250.0
    out = run(lines, {"chromatic": 1.0})
    if float(np.abs(out[:, :, 1] - lines[:, :, 1]).max()) > 0.0:
        raise RuntimeError("chromatic cham ca kenh luc")
    moves = {
        "r_left": line_x(out, 0, 0.2) - line_x(lines, 0, 0.2),
        "r_right": line_x(out, 0, 0.8) - line_x(lines, 0, 0.8),
        "b_left": line_x(out, 2, 0.2) - line_x(lines, 2, 0.2),
        "b_right": line_x(out, 2, 0.8) - line_x(lines, 2, 0.8),
    }
    if not (moves["r_right"] >= 2 and moves["r_left"] <= -2):
        raise RuntimeError("do khong phong to ra tam: %s" % moves)
    if not (moves["b_right"] <= -2 and moves["b_left"] >= 2):
        raise RuntimeError("xanh duong khong thu ve tam: %s" % moves)

    # 3) Loang sang: cham trang sinh Quang, vong xa nguyen ven, dinh khong toi.
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - w / 2.0) ** 2 + (yy - h / 2.0) ** 2)
    dots = np.full((h, w, 3), 22.0, np.float64)
    dots[dist <= 8.0] = 250.0
    flare = run(dots, {"lens_flare": 1.0})
    near_l, far_l = clip_effects._luma(dots), clip_effects._luma(flare)

    def gain(r0, r1):
        m = (dist >= r0) & (dist < r1)
        return float(far_l[m].mean() - near_l[m].mean())

    near_gain, far_gain, core_gain = gain(12, 26), gain(160, 180), gain(0, 9)
    if near_gain < 3.0:
        raise RuntimeError("khong co quang sang: +%.2f o 12-26px" % near_gain)
    if far_gain > 0.05:
        raise RuntimeError("quang sang lan toi vong xa: +%.2f" % far_gain)
    if core_gain < -0.5:
        raise RuntimeError("dinh cham bi toi di (blur, khong phai screen): %.2f"
                           % core_gain)
    flat = np.full((120, 160, 3), 128.0, np.float64)
    still = float(np.abs(run(flat, {"lens_flare": 1.0}) - flat).mean())
    if still > 0.02:
        raise RuntimeError("nang sang ca anh khong co nguon sang: %.3f" % still)

    # 4) Cuong do 0 phai tra lai ANH NGUYEN VAN cho ca hai khoa moi.
    for key in ("chromatic", "lens_flare"):
        if not np.array_equal(rgb_of(qimage(dots)), run(dots, {key: 1.0}, 0.0)):
            raise RuntimeError("%s o cuong do 0 van doi anh" % key)
    return ("%d the mau/loc khong khoa ma, do dich do %+dpx/%+dpx, quang +%.1f, "
            "xam128 +%.3f" % (len(cards), moves["r_left"], moves["r_right"],
                              near_gain, still))


def _aura_ok():
    """Một dòng --selftest: 8 thẻ Aura vẽ thật, đổi pixel và đổi theo đồng hồ.

    Aura không đi qua apply_color_effects nên cửa liveness màu không nhìn thấy
    nó. Ở đây đo thẳng vào core.aura_paint — cùng hàm mà CanvasClipItem và
    FrameComposer gọi — trên nền đen tuyệt đối:

      * một thẻ không khớp preset, hoặc preset trỏ vào kiểu không tồn tại, thì
       _raise ngay (đó chính là cách thẻ ma bị loại khỏi họ Aura);
      * tổng độ sáng phải TĂNG so với nền trắng xoá, nếu không là thẻ minh hoạ;
      * hai mốc thời gian khác nhau phải cho hai ảnh khác nhau, vì aura là hiệu
        ứng chạy theo t chứ không phải ảnh tĩnh dán lên khung.
    """
    import numpy as np
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from core import aura_paint
    from core.timeline_model import EFFECT_PRESETS
    from ui.effects_panel import EFFECT_CATEGORIES

    cards = [c["name"] for c in EFFECT_CATEGORIES.get("Aura", [])]
    if len(cards) != len(aura_paint.AURA_EFFECTS):
        raise RuntimeError("the Aura %d cai but preset %d kieu" %
                           (len(cards), len(aura_paint.AURA_EFFECTS)))
    for name in cards:
        key = (EFFECT_PRESETS.get(name) or {}).get("aura")
        if key not in aura_paint.AURA_EFFECTS:
            raise RuntimeError("the Aura %s khong tro kieu aura nao co that" % name)

    W, H = 240, 320
    rect = QRectF(0, 0, W, H)

    def frame(name, t):
        img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.black)
        painter = QPainter(img)
        aura_paint.paint_aura(painter, rect, t, name)
        painter.end()
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape((H, W, 4))[:, :, :3]

    def lum(name, t):
        return float(frame(name, t).mean())

    floor = lum("__khong_ton_tai__", 0.0)
    if floor > 0.01:
        raise RuntimeError("nen den khong con den: %.3f" % floor)
    weakest = None
    still_moving = None
    for name in aura_paint.aura_names():
        a, b = frame(name, 0.0), frame(name, 1.37)
        bright = float(a.mean()) - floor
        if bright < 0.05:
            raise RuntimeError("aura %s khong to sang nen (%.3f)" % (name, bright))
        # "Chay theo dong ho" la pixel DI CHUYER, khong phai anh sang doi total:
        # dai song aurora troi ngang ma tong do sang khong le, nen do bang so
        # pixel lech nhau thi moi bat duoc kieu dung yen.
        moved = float((np.abs(a.astype(np.int16) - b.astype(np.int16)) > 8
                       ).any(axis=2).mean())
        if moved < 0.004:
            raise RuntimeError("aura %s dung yen theo t (%.4f pixel dich)"
                               % (name, moved))
        if weakest is None or bright < weakest[1]:
            weakest = (name, bright)
        if still_moving is None or moved < still_moving[1]:
            still_moving = (name, moved)
    return ("%d aura to sang (yeu nhat +%s %.2f), %s dich %.1f%% pixel theo t"
            % (len(cards), weakest[0], weakest[1], still_moving[0],
               still_moving[1] * 100.0))


def _recap_overlay_ok():
    """Một dòng --selftest: lớp phủ recap sống ở model, trong file dự án và ở cả hai đường vẽ.

    Không giống aura, đây là cấu hình CẢ DỰ ÁN nên bốn mắt xích phải khớp: mặc
    định tắt (file cũ không có khoá), clamp khi đọc, tròn-trip qua
    ``save_project_to_file``/``restore_model_from_clinq``, và FrameComposer phải
    đổi pixel thật. Đo ở đúng 1920x1080 vì FrameComposer vẽ lớp phủ TRƯỚC khi
    co về kích thước xuất: thử ở 640x360 thì nét 6px bị hạ xuống 2px và trôi
    màu, gate đỏ vì lý do kỹ thuật chứ không phải vì thiếu lớp phủ.
    """
    import numpy as np
    import tempfile
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from core import project_storage, recap_overlay
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType

    if recap_overlay.overlay_active({}):
        raise RuntimeError("mac dinh phai TAT nhung overlay_active({}) = True")
    clamped = recap_overlay.normalize({"bg_brightness": 9, "border_width": 0,
                                       "reticle_shape": "khong_co"})
    if clamped["bg_brightness"] != 1.0 or clamped["border_width"] < 1.0 \
            or clamped["reticle_shape"] != "cross":
        raise RuntimeError("normalize khong clamp: %s" % clamped)

    W, H = 1920, 1080
    folder = os.path.join(tempfile.gettempdir(), "clinging_recap_report")
    os.makedirs(folder, exist_ok=True)
    png = os.path.join(folder, "nen_trang.png")
    if not os.path.exists(png):
        seed = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        seed.fill(Qt.GlobalColor.white)
        seed.save(png)

    settings = {"enabled": True, "border": True, "border_color": "#3673FE",
                "reticle": True, "reticle_shape": "scope",
                "reticle_color": "#00FFFF", "rec": True, "rec_fps": 30}

    def build(overlay):
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, png, "image", 0.0, 2.0, name="recap")
        if clip is None:
            raise RuntimeError("add_clip tra None (track/media khong khop)")
        model.set_recap_overlay(overlay)
        return model

    def frame(model):
        composer = FrameComposer(model, W, H)
        try:
            img = composer.render_frame(0.5).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied)
        finally:
            composer.close()
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        row = img.bytesPerLine() // 4
        # ARGB32 trên máy little-endian nằm trong bộ nhớ theo thứ tự B,G,R,A,
        # nên phải đảo ba kênh đầu trước khi so với mã màu hex.
        px = np.frombuffer(raw, np.uint8).reshape((H, row, 4))[:, :W, :3]
        return px[:, :, ::-1].astype(np.int16)

    def count(px, hexcolor, tol):
        c = QColor(hexcolor)
        d = np.abs(px - np.array([c.red(), c.green(), c.blue()], np.int16))
        return int((d.max(axis=2) <= tol).sum())

    on = frame(build(settings))
    off = frame(build({"enabled": False}))
    border = count(on, "#3673FE", 60)
    reticle = count(on, "#00FFFF", 60)
    #Vien 4*k=2px quanh 640x360 ~ 4000px, tam ngam scope ~ 200px; bat ky lop nao
    #bang 0 la mat nui ve, con khac biet on/off = 0 la master off khong tat.
    if border < 1500 or reticle < 60:
        raise RuntimeError("lop phu khong hien khi bat (vien %d, tam ngam %d px)"
                           % (border, reticle))
    if np.array_equal(on, off):
        raise RuntimeError("bat full overlay ma khung khong doi pixel")
    if count(off, "#00FFFF", 60) or count(off, "#3673FE", 60):
        raise RuntimeError("master off van con ve lop phu")
    if not np.array_equal(on, frame(build(settings))):
        raise RuntimeError("cung settings + cung t ra hai khung khac nhau")

    path = os.path.join(folder, "Kiem recap.clinq")
    project_storage.save_project_to_file(build(settings), path)
    reloaded = TimelineModel()
    data = project_storage.load_project_from_file(path)
    if not data:
        raise RuntimeError("load_project_from_file tra rong")
    project_storage.restore_model_from_clinq(reloaded, data)
    if reloaded.recap_overlay != recap_overlay.normalize(settings):
        raise RuntimeError("recap_overlay khong tron ven qua file: %s"
                           % (reloaded.recap_overlay,))
    return ("vien %d px, tam ngam %d px, master off sach %d/%d, file giu nguyen %d khoa"
            % (border, reticle, int((np.abs(on - off).max(axis=2) > 6).sum()),
               W * H, len(reloaded.recap_overlay)))


def _project_layout_ok():
    """Một dòng --selftest: Bố cục & Phong cách cấp dự án, đo BẰNG PIXEL trên khung 1920x1080.

    Cùng khuân với `_recap_overlay_ok` (cấu hình CẢ DỰ ÁN: model + file + hai
    đường vẽ) nhưng phải chắn thêm ba mắt xích recap không có, vì bo cuc đổi
    HINH DANG va doi theo DONG HO:

      * clamp cua `normalize` — file `.clinq` cua 1.0.5 tro ve truoc khong co
        khoa `project_layout`, nen thieu mot khoa la ve trang tinh;
      * `slot_gap`/so o cua tung kieu bo cuc — do tren chinh `slots()`, khong
        tin bang anh;
      * `play_sequentially` va `manga_rotate_interval` la ham cua t, do bang so
        tren `sequential_index`/`rotated_slot_source`.

    Do o 1920x1080 vi FrameComposer ve lop phu TRUOC khi co ve kich thuoc xuat
    (ly do da chang o dong recap: net 2px o 720px bi ha xuong 1px khi do 640x360).

    `import ui.canvas_layout_dialog` o day la MAT NUI THU HAI cua quy tac hai
    cho: module UI chi duoc import trong than
    `MainWindow._open_canvas_layout` nen tree nguon luon xanh, con bundle thi
    PyInstaller chi git no neu `ClingingQt.spec` co no trong hiddenimports.
    """
    import numpy as np
    import tempfile
    from PySide6.QtGui import QColor, QImage
    from core import canvas_layout, project_storage
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel

    import ui.canvas_layout_dialog  # noqa: F401  (cua dong goi, xem docstring)

    if canvas_layout.layout_active({}):
        raise RuntimeError("mac dinh phai TAT nhung layout_active({}) = True")
    defaults = canvas_layout.normalize({})
    if defaults["enabled"] or defaults["layout"] != "none":
        raise RuntimeError("mac dinh bi doi: %s" % defaults)
    clamped = canvas_layout.normalize({
        "overlay_opacity": 5.0, "slot_gap": 9.0, "texture_scale": 0.1,
        "layout": "khong_co", "texture": "khong_co", "background_mode": "x",
        "header_font": "x", "header_size": 2, "slot_seconds": 0.0})
    got = tuple(clamped[key] for key in (
        "overlay_opacity", "slot_gap", "texture_scale", "layout", "texture",
        "background_mode", "header_font", "header_size", "slot_seconds"))
    if got != (1.0, 0.2, 0.25, "none", "meme", "black", "sans", 6.0, 0.1):
        raise RuntimeError("normalize khong clamp: %s" % (got,))

    W, H = 1920, 1080

    def boxes(**patch):
        settings = dict(canvas_layout.LAYOUT_DEFAULTS)
        settings.update(patch)
        return canvas_layout.slots(W, H, settings)

    if len(boxes(layout="none")) != 1:
        raise RuntimeError("bo cuc 'none' phai mot o")
    if tuple(round(v) for v in boxes(layout="none")[0]) != (0, 0, W, H):
        raise RuntimeError("mot o khong lap day khung: %s" % boxes(layout="none")[0])
    counts = {"split": 2, "split-3": 3, "split-4": 4, "split-6": 6}
    for key, want in counts.items():
        if len(boxes(layout=key)) != want:
            raise RuntimeError("%s phai %d o, do duoc %d"
                               % (key, want, len(boxes(layout=key))))
    outside = []
    for key in canvas_layout.LAYOUT_ORDER:
        for box in boxes(layout=key):
            if box[0] < -0.5 or box[1] < -0.5 or box[0] + box[2] > W + 0.5 \
                    or box[1] + box[3] > H + 0.5:
                outside.append("%s %s" % (key, tuple(round(v, 1) for v in box)))
    if outside:
        raise RuntimeError("o tro ra ngoai khung: %s" % outside[:4])
    # `slot_gap` phai THU HO o dung len (canh ngan lam don vi), khong doi so o.
    tight, loose = boxes(layout="split", slot_gap=0.2)[0], boxes(layout="split")[0]
    if not (tight[0] > loose[0] + 1.0 and tight[2] < loose[2] - 1.0):
        raise RuntimeError("slot_gap khong thu o: %.1f/%.1f vs %.1f/%.1f"
                          % (tight[0], tight[2], loose[0], loose[2]))

    folder = os.path.join(tempfile.gettempdir(), "clinging_canvas_layout")
    os.makedirs(folder, exist_ok=True)

    def qimage_rgb(img):
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        row = img.bytesPerLine() // 4
        px = np.frombuffer(raw, np.uint8).reshape(
            (img.height(), row, 4))[:, :img.width(), :3]
        # ARGB32 trên máy little-endian nằm trong bộ nhớ theo B,G,R,A.
        return px[:, :, ::-1].astype(np.int16)

    def tex(**patch):
        settings = dict(canvas_layout.LAYOUT_DEFAULTS, enabled=True,
                        background_mode="texture")
        settings.update(patch)
        return qimage_rgb(canvas_layout.backdrop(settings, 320, 240))

    def frame(**patch):
        model = TimelineModel()
        model.project_ratio = "16:9"
        settings = dict(canvas_layout.LAYOUT_DEFAULTS)
        settings.update(patch)
        model.set_project_layout(settings, emit=False)
        composer = FrameComposer(model, W, H)
        try:
            return qimage_rgb(composer.render_frame(0.5))
        finally:
            composer.close()

    def mask(px, hexcolor, tol=60):
        c = QColor(hexcolor)
        d = np.abs(px - np.array([c.red(), c.green(), c.blue()], np.int16))
        return d.max(axis=2) <= tol

    def count(px, hexcolor, tol=60):
        return int(mask(px, hexcolor, tol).sum())

    plain = frame(enabled=False)
    dark = frame(enabled=True, background_mode="black")
    # Nen "black" la NGUYEN hanh vi 1.0.5: mo bo cuc len ma chi chon den thi
    # khung hinh phai y het nhu cu, neu khong thi tat o day la mot lop ve an.
    if not np.array_equal(plain, dark):
        raise RuntimeError("enabled + nen den van doi %d pixel"
                           % int((np.abs(plain - dark).max(axis=2) > 6).sum()))
    blue = frame(enabled=True, background_mode="color", background_color="#3673FE")
    n_blue = count(blue, "#3673FE")
    if n_blue < 0.9 * W * H:
        raise RuntimeError("nen mau chi %d/%d px" % (n_blue, W * H))
    grid = frame(enabled=True, background_mode="color", background_color="#3673FE",
                 layout="split-4", frame_color="#00FFFF")
    n_grid = count(grid, "#00FFFF")
    # 4 o = 3 duong ke, moi duong ~2*1.5=3px dai 1080/1920 px ~ 9000 px; nguong
    # 3000 de mot duong bi mat van do, con 0 la mat ca nui ve.
    if n_grid < 3000:
        raise RuntimeError("gach ngan bo cuc khong hien (%d px cyan)" % n_grid)
    texture = frame(enabled=True, background_mode="texture", texture="blueprint")
    if np.array_equal(texture, plain):
        raise RuntimeError("bat chat lieu ma khung khong doi pixel")
    # Mot chat lieu phai la NET, khong phai lop son: dem mau phan biet trong
    # khung THAT. blueprint do 23/10 = 2 mau (nen cham + gach luoi sang), nen
    # nguong la 2 chu khong phai 4 — do la so do duoc, khong so thich.
    n_colors = len(np.unique(texture.reshape(-1, 3), axis=0))
    if n_colors < 2:
        raise RuntimeError("chat lieu ve thanh mot mau dac")
    # 10 chat lieu phai la 10 buoc ve khac nhau (khong phai mot anh dung chung),
    # va `texture_scale` phai doi duoc kich thuoc net. Do o 320x240 qua dung
    # `backdrop()` ma paint_background goi, khong pha them 10 khung 1080p.
    solids, means = [], []
    for name in canvas_layout.TEXTURE_ORDER:
        arr = tex(texture=name)
        if len(np.unique(arr.reshape(-1, 3), axis=0)) < 2:
            solids.append(name)
        means.append(round(float(arr.mean()), 1))
    if solids:
        raise RuntimeError("chat lieu in lang: %s" % solids)
    if len(set(means)) < 5:
        raise RuntimeError("%d chat lieu chi co %d muc sang khac nhau: %s"
                          % (len(means), len(set(means)), means))
    if np.array_equal(tex(texture="lined-paper", texture_scale=0.5),
                      tex(texture="lined-paper", texture_scale=2.0)):
        raise RuntimeError("texture_scale khong doi net (0,5 == 2,0)")
    veil = frame(enabled=True, background_mode="color", background_color="#FFFFFF",
                 overlay_opacity=0.5)
    mean_lum = float(veil.mean())
    if abs(mean_lum - 127.5) > 12.0:
        raise RuntimeError("overlay_opacity 0,5 khong toi xuong giua (%.1f)" % mean_lum)
    ink = frame(enabled=True, layout="none", text_color="#FF0000",
                header_font="sans", header_bold=True, header_size=64,
                header_text="TIEU DE THU")
    n_ink = count(ink, "#FF0000", 90)
    if n_ink < 400:
        raise RuntimeError("chu dau khong ve (%d px muc)" % n_ink)
    hit = mask(ink, "#FF0000", 90)
    ys, _xs = np.nonzero(hit)
    hrect = canvas_layout.header_rect(W, H, {"layout": "none",
                                             "header_size": 64})
    if ys.min() < hrect[1] - 2 or ys.max() > hrect[1] + hrect[3] + 2:
        raise RuntimeError("chu dau roi ngoai vung cua no (%d..%d, voi %.0f+%.0f)"
                          % (ys.min(), ys.max(), hrect[1], hrect[3]))
    if not np.array_equal(frame(enabled=True, layout="split"),
                          frame(enabled=True, layout="split")):
        raise RuntimeError("cung bo cuc ra hai khung khac nhau (khong tat)")

    seq = dict(canvas_layout.LAYOUT_DEFAULTS, play_sequentially=True,
               slot_seconds=2.0)
    steps = [canvas_layout.sequential_index(seq, t, 3)
             for t in (0.0, 1.9, 2.0, 5.9, 6.0, 7.5)]
    if steps != [0, 0, 1, 2, 0, 0]:
        raise RuntimeError("phat tuan tu sai vong o: %s" % steps)
    if canvas_layout.sequential_index(dict(seq, play_sequentially=False), 1.0, 3) != -1:
        raise RuntimeError("tat tuan tu ma van tinh o dang phat")
    rot = dict(canvas_layout.LAYOUT_DEFAULTS, manga_rotate_interval=5.0)
    if canvas_layout.rotated_slot_source(rot, 0.0, 3, 1, 4) != 1:
        raise RuntimeError("trao o tai t=0 khong giu dung o cua no")
    if canvas_layout.rotated_slot_source(rot, 5.0, 3, 1, 4) != (1 + 3) % 4:
        raise RuntimeError("trao o khong nhay theo interval")
    if canvas_layout.rotated_slot_source(dict(rot, manga_rotate_interval=0.0),
                                         9.0, 3, 2, 4) != 2:
        raise RuntimeError("interval 0 van trao noi dung")

    path = os.path.join(folder, "Kiem bo cuc.clinq")
    settings = dict(canvas_layout.LAYOUT_DEFAULTS, enabled=True,
                    layout="manga-grid", background_mode="texture",
                    texture="parchment", header_text="Tuan 42", slot_gap=0.05,
                    play_sequentially=True, manga_rotate_interval=5.0)
    model = TimelineModel()
    model.project_ratio = "16:9"
    model.set_project_layout(settings, emit=False)
    if not project_storage.save_project_to_file(model, path):
        raise RuntimeError("save_project_to_file tra False")
    data = project_storage.load_project_from_file(path)
    if not data:
        raise RuntimeError("load_project_from_file tra rong")
    if "project_layout" not in data.get("timeline", {}):
        raise RuntimeError("file .clinq khong ghi khoa project_layout")
    reloaded = TimelineModel()
    project_storage.restore_model_from_clinq(reloaded, data)
    if reloaded.project_layout != canvas_layout.normalize(settings):
        raise RuntimeError("bo cuc khong tron ven qua file: %s"
                           % (reloaded.project_layout,))
    # File cua 1.0.5 tro ve truoc: KHONG co khoa nao ca. Duong nay phai tra ve
    # mac dinh thay vi ve trang tinh hay crash.
    stale = dict(data)
    stale["timeline"] = {k: v for k, v in data["timeline"].items()
                         if k != "project_layout"}
    legacy = TimelineModel()
    project_storage.restore_model_from_clinq(legacy, stale)
    if legacy.project_layout != canvas_layout.LAYOUT_DEFAULTS:
        raise RuntimeError("file cu bi doc thanh bo cuc bat: %s"
                           % (legacy.project_layout,))
    return ("%d kieu bo cuc, %d chat lieu | nen mau %d px, gach %d px, chu %d px"
            " | tuan tu %s | file tron ven %d khoa, file cu tro ve %d mac dinh"
            % (len(canvas_layout.LAYOUT_ORDER) - 1, len(canvas_layout.TEXTURES),
               n_blue, n_grid, n_ink, steps, len(reloaded.project_layout),
               len(legacy.project_layout)))


# Khổ chữ đo "từ ĐANG HÁT có còn đọc được không": 40 là cỡ trong bản xuất,
# 12-16 là cỡ nó hiện ra trên khung preview của canvas.
_FLAME_SIZES = (40, 28, 20, 16, 12)
# Ba pha của nhịp nhấp nháy: đáy (pulse 0), giữa (0.5) và đỉnh (1).
_FLAME_PHASES = (0.0, math.pi * 1.5 / 2.4, math.pi / 2 / 2.4)


def _flame_legibility():
    """Đo từ đang hát của kiểu "lửa": còn lỗ chữ, hay đã thành một khối cam.

    Quầng lửa là 8 bản sao lệch của nét chữ chồng nhau, nên alpha hiệu dụng giữa
    thân chữ là 1-(1-a/255)^8. Với alpha 90 con số đó 0.95: mọi lỗ (a, o, u) bị
    lấp ở MỌI khổ, kể cả 40px — ảnh vẫn "đẹp" trên băng chứng khổ lớn nhưng chữ
    thì không đọc ra. Ba số đo phân biệt được khối đặc và chữ:

      * ``fill`` = mực / hộp khít của mực. Chữ thường 47-65%, khối đặc 75-80%.
      * ``lo``   = số vùng nền bị bao kín trong mực. Không lỗ = không chữ.
      * ``spill``= số pixel mực nhiều hơn chữ thường cùng từ. Đây là chốt CHỐNG
                   GIAN LẬN: gate ``fill`` một mình thì xanh ngay khi ai đó bỏ
                   hẳn quầng lửa, còn số này buộc quầng phải còn thật.

    Mỗi số là TE NHẤT trên cả ba pha, không phải số ở đỉnh nhấp nháy: bán kính
    nhỏ hơn lẽ ra mở chữ hơn, nhưng mode 'counter' của phản chứng đo ra 1 lỗ ở
    28px tại một pha trung gian — lưới pixel của 8 hướng lệch không đơn điệu
    theo bán kính. Vẽ qua đúng ``paint_animated_text`` (không có bản sao thứ hai
    của thuật toán) và chỉ đổi bộ hằng số ``karaoke_paint._FLAME_HALO``.
    """
    import cv2
    import numpy as np
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from core.text_paint import make_font, paint_animated_text

    W, H = 420, 160
    # Một từ + sweep này -> lit_count = 0 -> từ ở trạng thái ACTIVE.
    sweep = 0.2

    def ink_of(style, px, t):
        img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.black)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        paint_animated_text(p, "chao", make_font("Arial", px, True), "#FFFFFF",
                            W, H, W / 2.0, H / 2.0, effect="none", p=sweep,
                            intensity=1.0, style=style, t=t)
        p.end()
        row = img.bytesPerLine() // 4
        a = np.frombuffer(img.constBits(), np.uint8,
                          count=row * 4 * H).reshape(H, row, 4)[:, :W, :3]
        mask = a[:, :, ::-1].max(axis=2) > 40
        if not mask.any():
            return 0, 0.0, 0
        ys, xs = np.nonzero(mask)
        box = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        n, _, stats, _ = cv2.connectedComponentsWithStats(
            (~box).astype(np.uint8), 8)
        h, w = box.shape
        holes = sum(1 for i in range(1, n)
                    if stats[i][4] >= 2 and stats[i][0] > 0 and stats[i][1] > 0
                    and stats[i][0] + stats[i][2] < w
                    and stats[i][1] + stats[i][3] < h)
        return int(mask.sum()), round(100.0 * box.sum() / box.size, 1), holes

    out = {}
    for px in _FLAME_SIZES:
        rows = []
        for t in _FLAME_PHASES:
            plain_ink, _, _ = ink_of("none", px, t)
            hot_ink, hot_fill, hot_holes = ink_of("flame", px, t)
            rows.append((hot_ink, hot_fill, hot_holes, hot_ink - plain_ink))
        out[px] = {"muc": max(r[0] for r in rows),
                   "fill": max(r[1] for r in rows),
                   "lo": min(r[2] for r in rows),
                   "spill": min(r[3] for r in rows)}
    return out


def _flame_legibility_problems(leg):
    """Danh sách lỗi đọc được từ bảng số đo; rỗng là từ đang hát còn đọc được.

    Ngưỡng lấy từ phép quét 5 bộ hằng số ở
    scratch/karaoke_flame_density_probe.py, đo TE NHẤT trên cả chu kỳ: bộ đang
    ship cho fill 66.7-68.3 và >=1 lỗ ở mọi khổ/mọi pha, bộ cũ (alpha 90) cho
    fill 74.8-80.0 và 0 lỗ — hai dải cách nhau rõ nên gate không mong manh.

    ``spill`` chỉ bắt ở khổ 40px: ở 12-16px nó dao động vài chục pixel theo pha
    và theo font, đủ để một ngưỡng cứng đỏ sai trên máy khác.
    """
    bad = ["%dpx fill=%s lo=%s" % (px, m["fill"], m["lo"])
           for px, m in sorted(leg.items()) if m["lo"] < 1 or m["fill"] > 72.0]
    if bad:
        return ["tu_dang_hat_bi_lap_lo: " + "; ".join(bad)]
    if leg[_FLAME_SIZES[0]]["spill"] < 100:
        return ["khong_con_quang_lua (spill=%d)" % leg[_FLAME_SIZES[0]]["spill"]]
    return []


def _karaoke_ok():
    """Một dòng --selftest: tám kiểu phụ đề karaoke, nối đủ hai đường vẽ và qua file.

    Đo sâu (hộp mực từng từ, cầu thang sweep, bóng đổi hướng, gradient không
    được thành khối đặc, parity export = vẽ trực tiếp tới từng pixel) nằm ở
    scratch/karaoke_probe.py cùng 10 phản chứng
    scratch/karaoke_probe_counterfactual.py. Đây chỉ là năm mắt xích nối mà
    bundle đóng gói có quyền làm đứt: registry đủ 8 khoá, mỗi kiểu đổi pixel
    THẬT qua ``paint_animated_text``, 8 kiểu phải ra 8 ảnh KHÁC NHAU (so với
    chữ thường không bắt được lỗi cả 8 cùng vẽ một nét), quét theo từ và tất
    định, đường xuất đọc ``clip.text_style``, và khoá sống sót
    model → ``.clinq`` → model.

    Font phải là font THẬT. Headless không còn font nào thì Qt vẽ mọi ký tự ra
    hình chữ nhật, nên so nét chữ ở đó chỉ tạo ra màu xanh giả.
    """
    import numpy as np
    import tempfile
    from PySide6.QtGui import QColor, QImage, QPainter
    from core import karaoke_paint, project_storage
    from core.frame_composer import FrameComposer
    from core.text_paint import make_font, paint_animated_text
    from core.timeline_model import TimelineModel, TrackType

    keys = karaoke_paint.STYLE_KEYS
    if len(keys) != 8:
        raise RuntimeError("karaoke co %d kieu, khong phai 8" % len(keys))
    if karaoke_paint.normalize_style("khong_co_kieu_nay") != "none":
        raise RuntimeError("normalize_style chap nhan gia tri rac")
    for key in keys:
        if karaoke_paint.normalize_style("  %s  " % key.upper()) != key:
            raise RuntimeError("normalize_style lam mat kieu %s" % key)

    W, H = 900, 260
    font = make_font("Arial", 40, True)
    line = "Xin chao buoi sang"
    # "outline"/"shadow" là pigment TỐI màu: trên nền đen chúng vô hình thật,
    # nên đo chúng trên nền sáng — đúng chỗ người dùng cần đến chúng.
    home = {"outline": "#c8c8c8", "shadow": "#c8c8c8"}

    def render(style, sweep=0.0, t=0.0, bg="#000000"):
        img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(bg))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        paint_animated_text(p, line, font, "#FFFFFF", W, H, W / 2.0, H / 2.0,
                            effect="none", p=sweep, intensity=1.0,
                            style=style, t=t)
        p.end()
        return img

    def px(img):
        row = img.bytesPerLine() // 4
        a = np.frombuffer(img.constBits(), np.uint8,
                          count=row * 4 * img.height()).reshape(
            img.height(), row, 4)[:, :img.width(), :3]
        # ARGB32 little-endian là B,G,R,A — đảo trước khi so, nếu không mọi
        # kiểu đổi màu vẫn đọc là giống nhau.
        return a[:, :, ::-1].astype(np.int16)

    def diff(a, b):
        return int((np.abs(px(a) - px(b)).max(axis=2) > 24).sum())

    weakest = None
    for key in keys:
        bg = home.get(key, "#000000")
        n = diff(render(key, 0.34, 0.7, bg), render("none", 0.34, 0.7, bg))
        if n < 200:
            raise RuntimeError("kieu %s ve giong chu thuong (%d px lech tren %s)"
                               % (key, n, bg))
        if weakest is None or n < weakest[1]:
            weakest = (key, n)

    # Tam kieu PHAI ra tam anh khac nhau. So voi chu thuong khong du: ke duong
    # ve ve mot net chung cho ca tam kieu thi lech van > 200 px vi do ve tung
    # tu, nen phai so chung voi NHAU. Probe o scratch/karaoke_probe.py doi chieu
    # ca 28 cap; o day dem so van in chi can du de bat that bam.
    prints = set()
    for key in keys:
        prints.add(px(render(key, 0.34, 0.7, home.get(key, "#000000"))).tobytes())
    if len(prints) != len(keys):
        raise RuntimeError("%d kieu chi ra %d anh khac nhau (duong ve bi gop)"
                           % (len(keys), len(prints)))

    # Quét theo từ phải ĐỔI khung hình theo p, và cùng (p, t) phải ra cùng một
    # ảnh. Kiểm tra tất định phải chạy trên kiểu THỰC SỰ phụ thuộc t (lửa chớp,
    # cầu vồng xoay): trên glow/neon thì thêm bộ đếm toàn cục vào đường vẽ vẫn
    # cho ra hai ảnh giống hệt nhau, tức là gate xanh giả.
    for key in ("glow", "gradient"):
        if diff(render(key, 0.05), render(key, 0.95)) < 200:
            raise RuntimeError("kieu %s khong quet theo tu (p=0.05 ~ p=0.95)" % key)
    for key in ("flame", "rainbow"):
        if diff(render(key, 0.4, 0.0), render(key, 0.4, 0.9)) < 50:
            raise RuntimeError("kieu %s khong chay theo dong ho clip (t=0 ~ t=0.9)"
                               % key)
        if not np.array_equal(px(render(key, 0.4, 1.25)),
                              px(render(key, 0.4, 1.25))):
            raise RuntimeError("kieu %s khong tat dinh: cung (p, t) ra hai anh khac" % key)

    staircase = [karaoke_paint.lit_count(4, s / 100.0) for s in range(101)]
    if sorted(set(staircase)) != list(range(5)) \
            or any(b < a for a, b in zip(staircase, staircase[1:])):
        raise RuntimeError("cab thang sweep bo qua tu nao do (duoc %s)"
                           % sorted(set(staircase)))

    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.TEXT)
    clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, name=line)
    if clip is None:
        raise RuntimeError("add_clip text tra None (track loai TEXT khong nhan media text?)")
    clip.font_size = 44.0
    clip.font_bold = True

    # So ở ĐÚNG khổ canvas mà FrameComposer dựng: nó vẽ theo project_ratio rồi
    # mới co về khổ xuất, nên đo ở khổ nhỏ hơn là đo một ảnh đã bị hạ tỉ lệ.
    CW, CH = 1920, 1080

    def frame():
        composer = FrameComposer(model, CW, CH)
        try:
            return composer.render_frame(1.0).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied)
        finally:
            composer.close()

    clip.text_style = "none"
    off_img = frame()
    # "rainbow" chứ không phải "glow": kiểm tra tất định bên xuất chỉ có ý nghĩa
    # trên kiểu đổi theo t, nên cùng một lý do với vòng determinism ở trên.
    clip.text_style = "rainbow"
    on_img = frame()
    export_px = diff(on_img, off_img)
    if export_px < 200:
        raise RuntimeError("export bo qua clip.text_style (%d px lech)" % export_px)
    if not np.array_equal(px(on_img), px(frame())):
        raise RuntimeError("export cung thoi diem cho hai khung khac nhau")

    folder = os.path.join(tempfile.gettempdir(), "clinging_karaoke_report")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "Kiem karaoke.clinq")
    lost = []
    for key in keys:
        clip.text_style = key
        project_storage.save_project_to_file(model, path)
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        back = TimelineModel()
        project_storage.restore_model_from_clinq(back, data)
        got = [c.text_style for c in back.active_visual_clips_at(0.5)]
        if got != [key]:
            lost.append("%s->%s" % (key, got))
    if lost:
        raise RuntimeError("text_style mat khi quay qua file: %s" % ", ".join(lost))
    if karaoke_paint.normalize_style(
            back.active_visual_clips_at(0.5)[0].text_style) != keys[-1]:
        raise RuntimeError("kieu doc tu file khong phai la khoa karaoke hop le")

    # Từ ĐANG HÁT của kiểu "lửa" phải còn là CHỮ, không phải một khối cam. Mắt
    # xích này nằm CUỐI cùng có chủ đích: mọi gate phía trên đỏ trước nếu quầng
    # bị xoá sạch (mất luôn tính phụ thuộc t), nên để phép đo này ở đầu sẽ ăn cắp
    # red của gate nhịp quét / đồng hồ / bộ đếm — phản chứng đã đo ra ba vụ đó.
    # Khop spill vì vậy ở đây chỉ là DEP PHONG; no do THAT trong --style-report
    # (scratch/style_report_counterfactual.py: mode 'flame_no_halo').
    leg = _flame_legibility()
    problems = _flame_legibility_problems(leg)
    if problems:
        raise RuntimeError("flame_khong_khoi_dac RED (%s)" % "; ".join(problems))

    return ("8 kieu -> %d anh khac nhau, lech chu thuong nhat %s=%d px, "
            "quet %d px, export %d px, tu dang hat kieu lua con %d-%d lo "
            "chu (fill %s-%s), 8/8 khoa tron ven qua .clinq"
            % (len(prints), weakest[0], weakest[1],
               diff(render("glow", 0.05), render("glow", 0.95)), export_px,
               min(m["lo"] for m in leg.values()),
               max(m["lo"] for m in leg.values()),
               min(m["fill"] for m in leg.values()),
               max(m["fill"] for m in leg.values())))


def _text_styling_ok():
    """Nhom C: style chu (vien / bong / hop nen / can le) phai do pixel THAT,
    preview lan export di chung MOT seam ``text_style_of``, va tron ven qua file.

    Cam fixture nguoi dung: moi clip dung tai cho bang ``add_clip('')`` tren
    track TEXT cua mot ``TimelineModel`` moi trong thu muc tam. Font phai la
    font THAT: headless khong font thi Qt ve moi ky tu hinh chu nhat, so net
    chu thanh ra mau xanh gia.

    Do sau (vong 16 huong cua vien, do lech bong, alpha hop nen, parity
    preview=xuat tung pixel) nam trong scratch/text_styling_evidence.py cung
    6 phan chung scratch/text_styling_counterfactual.py. O day chi dem nam
    mat xich ma bundle dong goi co quyen lam dut.
    """
    import os
    import shutil
    import tempfile
    import numpy as np
    from PySide6.QtGui import QColor, QImage, QPainter
    from core import project_storage
    from core.frame_composer import FrameComposer
    from core.text_paint import (make_font, paint_animated_text, text_style_of,
                                 _styling_active)
    from core.timeline_model import TimelineModel, TrackType
    from ui.graphics_canvas_item import TextClipItem

    STYLING = ("text_outline_color", "text_outline_width", "text_shadow_color",
               "text_shadow_dx", "text_shadow_dy", "text_shadow_blur",
               "text_box_color", "text_box_alpha", "text_box_radius",
               "text_box_padding", "text_align")
    NUMERIC = ("text_outline_width", "text_shadow_dx", "text_shadow_dy",
               "text_shadow_blur", "text_box_alpha", "text_box_radius",
               "text_box_padding")

    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.TEXT)
    clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, name="Xin chao")
    if clip is None:
        raise RuntimeError("add_clip text tra None (track TEXT khong nhan text?)")

    # (1) text_style_of doc du 11 truong va chuan hoa so ve float (khong phai int).
    d = text_style_of(clip)
    absent = [k for k in STYLING if k not in d]
    if absent:
        raise RuntimeError("text_style_of thieu truong: %s" % ", ".join(absent))
    clip.text_outline_width = 3  # int tinh co -> phai ra float
    if not isinstance(text_style_of(clip)["text_outline_width"], float):
        raise RuntimeError("text_style_of khong chuan hoa so ve float")
    clip.text_outline_width = 0.0

    # (2) Seam cau truc: CA preview (TextClipItem.paint) lan export
    #     (FrameComposer._draw_text) phai goi dung text_style_of, neu khong thi
    #     hai ben ve hai khac nhau va nguoi dung thay chu khong nhu luc xuat ra.
    def walk_names(fn):
        seen = set()
        stack = [fn.__code__]
        while stack:
            code = stack.pop()
            seen.update(code.co_names)
            for const in code.co_consts:
                if hasattr(const, "co_names") and const not in seen:
                    stack.append(const)
        return seen

    seams = (("FrameComposer._draw_text", FrameComposer._draw_text, "text_style_of"),
             ("TextClipItem.paint", TextClipItem.paint, "text_style_of"))
    missing = sorted({name for name, fn, helper in seams
                      if helper not in walk_names(fn)})
    if missing:
        raise RuntimeError("seam style chu thieu: %s" % ", ".join(missing))
    ns = {}
    exec(compile("class FakeDraw:\n"
                 "    def _draw(self):\n"
                 "        return 1\n", "<mau>", "exec"), ns)
    if "text_style_of" in walk_names(ns["FakeDraw"]._draw):
        raise RuntimeError("detector khong phan biet ham goi va khong goi seam")

    W, H = 1000, 360
    font = make_font("Arial", 56, True)
    base = {"text_outline_color": "#FF2D2D", "text_outline_width": 0.0,
            "text_shadow_color": "#2D6DFF", "text_shadow_dx": 0.0,
            "text_shadow_dy": 0.0, "text_shadow_blur": 0.0,
            "text_box_color": "#2DC86D", "text_box_alpha": 0.0,
            "text_box_radius": 10.0, "text_box_padding": 16.0,
            "text_align": "center"}

    def px(img):
        row = img.bytesPerLine() // 4
        a = np.frombuffer(img.constBits(), np.uint8,
                          count=row * 4 * img.height()).reshape(
            img.height(), row, 4)[:, :img.width(), :3]
        # ARGB32 little-endian la B,G,R,A - dao truoc khi so.
        return a[:, :, ::-1].astype(np.int16)

    def diff(a, b):
        return int((np.abs(px(a) - px(b)).max(axis=2) > 24).sum())

    def render(over=None, line="Xin chao"):
        s = dict(base)
        s.update(over or {})
        img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#101014"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        paint_animated_text(p, line, font, "#FFFFFF", W, H, W / 2.0, H / 2.0,
                            effect="none", p=1.0, intensity=1.0, style="none",
                            t=0.0, styling=s)
        p.end()
        return img

    plain = render()

    # (3a) Vien / bong / bong mo / hop nen: moi cai PHAI lech chu thuong > 200 px.
    cases = {"vien": {"text_outline_width": 4.0},
             "bong": {"text_shadow_dx": 8.0, "text_shadow_dy": 8.0},
             "bong_mo": {"text_shadow_dx": 4.0, "text_shadow_dy": 4.0,
                         "text_shadow_blur": 6.0},
             "hop": {"text_box_alpha": 0.55}}
    weakest = None
    for label, over in cases.items():
        n = diff(render(over), plain)
        if n < 200:
            raise RuntimeError("%s ve giong chu thuong (%d px lech)" % (label, n))
        if weakest is None or n < weakest[1]:
            weakest = (label, n)

    # (3b) Can le dich khoi chu: do tren khoi nhieu dong de dong ngan nam trong
    #      box_w (box_w == line_w thi trai/phai giong het nhau, gate xanh gia).
    tall = "WWW WWW WWW\nHi"
    dl = diff(render({"text_align": "left"}, tall),
              render({"text_align": "right"}, tall))
    if dl < 100:
        raise RuntimeError("can le khong dich vi tri chu (%d px lech trai/phai)" % dl)

    # (3c) Chi bat can le KHONG duoc keo duong composite: phai van fast path.
    if _styling_active({**base, "text_align": "left"}):
        raise RuntimeError("align don thuan bi coi la can composite (ton kem may yeu)")

    # (4) Export that: FrameComposer phai doc styling cua clip (hop nen bat/tat).
    CW, CH = 1920, 1080

    def frame():
        composer = FrameComposer(model, CW, CH)
        try:
            return composer.render_frame(1.0).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied)
        finally:
            composer.close()

    clip.text_box_color = "#2DC86D"
    clip.text_box_alpha = 0.0
    clip.text_box_padding = 40.0
    off_img = frame()
    clip.text_box_alpha = 0.7
    on_img = frame()
    ex = diff(on_img, off_img)
    if ex < 200:
        raise RuntimeError("export bo qua style chu hop nen (%d px lech)" % ex)
    if not np.array_equal(px(on_img), px(frame())):
        raise RuntimeError("export cung thoi diem cho hai khung khac nhau")

    # (5) Ca nam truong song sot model -> .clinq -> model.
    values = {"text_outline_width": 5.0, "text_outline_color": "#FFAA00",
              "text_shadow_color": "#00FFAA", "text_shadow_dx": -7.0,
              "text_shadow_dy": 9.0, "text_shadow_blur": 3.0,
              "text_box_color": "#AA00FF", "text_box_alpha": 0.7,
              "text_box_radius": 14.0, "text_box_padding": 22.0,
              "text_align": "right"}
    for k, v in values.items():
        setattr(clip, k, v)
    folder = tempfile.mkdtemp(prefix="clinging_style_")
    cwd = os.getcwd()
    os.chdir(folder)
    try:
        path = os.path.join(folder, "Kiem style.clinq")
        if not project_storage.save_project_to_file(model, path):
            raise RuntimeError("save_project_to_file that bai (payload style bi tu choi)")
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        back = TimelineModel()
        project_storage.restore_model_from_clinq(back, data)
        got = back.active_visual_clips_at(0.5)[0]
        lost = [k for k in STYLING if getattr(got, k) != getattr(clip, k)]
        if lost:
            raise RuntimeError("style chu mat khi quay qua file: %s" % ", ".join(lost))
    finally:
        os.chdir(cwd)
        shutil.rmtree(folder, ignore_errors=True)

    return ("11 truong song qua .clinq, preview+export cung seam text_style_of, "
            "vien/bong/hop lech nhat %s=%d px, can le dich %d px, "
            "export hop nen %d px, fast path giu khi chi doi le"
            % (weakest[0], weakest[1], dl, ex))


def _color_grading_ok():
    """Một dòng --selftest: bo chinh mau (hue / lift-gamma-gain / LUT .cube) phai
    xoay mau DUNG CHUAN banh xe mau, preview lan export di chung MOT ham, va that
    tron ven qua file .clinq.

    Cam fixture nguoi dung: moi phep do dung mang numpy tai cho va file .cube ty
    le sinh trong thu muc tam. Ba sai lam cua .cube la duong thang giot cua so
    neu khong co cua nay: hieu nguoc thu tu kenh (xanh LAM doi nhanh nhat trong
    file, khong phai do), ap bang doc cho file rac, va giu bang cu trong cache khi
    nguoi dung sua file tai cho (do bang gia dinh cua `%.6f` luon co so byte bang
    nhau nen khoa cache theo GIAY khong phan biet duoc hai noi dung).

    Do sau nam o khac: 8 cua tren MainWindow that trong
    scratch/color_grading_ui_probe.py (preview doi pixel, nut LUT that, keo 5 nac
    = 1 buoc undo, preview = export lech 1.0/255), phan chung trong
    scratch/color_grading_counterfactual.py, anh trong
    scratch/color_grading_evidence.py. O day chi do nam xich ma ma bundle dong goi
    co the quyet: phep xoay, tung banh xe, bo doc LUT, seam dung chung, va vong
    doi cua lenh undo.
    """
    import os
    import shutil
    import tempfile
    import numpy as np
    from PySide6.QtGui import QImage
    from core import lut as lut_mod, project_storage
    from core.clip_effects import (GRADING_EFFECT_NAME, GRADING_IDENTITY,
                                   GRADING_KEYS, PIXEL_KEYS, apply_color_effects,
                                   grading_is_identity, hue_shift_rgb,
                                   lift_gamma_gain_rgb)
    from core.commands import SetGradingCommand, UndoStack
    from core.frame_composer import FrameComposer
    from core.timeline_model import EffectData, TimelineModel, TrackType
    from ui.graphics_canvas_item import CanvasClipItem
    from ui.properties_panel import ClipPropertiesWidget

    if set(GRADING_KEYS) & set(PIXEL_KEYS):
        raise RuntimeError("GRADING_KEYS trung PIXEL_KEYS: cua the ma mat nghia che do")

    def levels(*vals):
        """(len(vals), 1, 3): moi hang la mot mau phang co do sang = val."""
        a = np.asarray(vals, np.float32)
        return np.repeat(a[:, None, None], 3, axis=2)

    def grading_of(clip):
        for e in clip.effects:
            if e.name == GRADING_EFFECT_NAME:
                merged = dict(GRADING_IDENTITY)
                merged.update(e.params or {})
                return merged
        return dict(GRADING_IDENTITY)

    def qimage(a):
        arr = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
        h, w = arr.shape[:2]
        rgba = np.ascontiguousarray(
            np.dstack([arr, np.full((h, w, 1), 255, np.uint8)]))
        return QImage(rgba.data, w, h, w * 4,
                      QImage.Format.Format_RGBA8888).copy()

    def rgb_of(image):
        img = image.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4))[:, :, :3].astype(np.float64)

    def walk_names(fn):
        seen = set()
        stack = [fn.__code__]
        while stack:
            code = stack.pop()
            seen.update(code.co_names)
            for const in code.co_consts:
                if hasattr(const, "co_names") and const not in seen:
                    stack.append(const)
        return seen

    folder = tempfile.mkdtemp(prefix="clinging_grading_")
    try:
        # (1) hue = phep xoay quanh truc xam: anh xam PHAI dung yen, mau do PHAI
        #     dich ve phia luc. Mot ban "hue" chi cong/doi ba kenh (lenh kinh
        #     dien cua brightness-viet-voi) do duoc ải thứ hai nhung hong ải thứ
        #     nhat, va nguoc lai.
        grey = np.full((16, 16, 3), 137.0, np.float32)
        drift = float(np.abs(hue_shift_rgb(grey, 180.0) - grey).max())
        if drift > 1.0:
            raise RuntimeError("hue 180 doi mau xa (%.2f/255): khong phai xoay truc xam"
                               % drift)
        red = np.zeros((16, 16, 3), np.float32)
        red[:, :, 0] = 200.0
        red[:, :, 1] = 30.0
        gap_before = float((red[:, :, 0] - red[:, :, 1]).mean())
        rotated = hue_shift_rgb(red, 45.0)
        gap_after = float((rotated[:, :, 0] - rotated[:, :, 1]).mean())
        if gap_after > gap_before - 20.0:
            raise RuntimeError("hue +45 khong xoay mau (do-luc %.1f -> %.1f)"
                               % (gap_before, gap_after))
        if hue_shift_rgb(red, 0.0) is not red:
            raise RuntimeError("hue 0 do van chay ma tran (ton may cau hinh thap)")

        # (2) Ba banh xe lift/gamma/gain PHAI do duoc tung cai mot: chi banh
        #     xe cua vung toi nhuc, chi banh xe giua bongo midtone ma den van
        #     den, gain nhan tuyen tinh theo tung kenh.
        strip = levels(0.0, 10.0, 128.0, 250.0)
        lift_out = lift_gamma_gain_rgb(strip, 0.25, 1.0, 1.0)[:, 0, 0] - strip[:, 0, 0]
        if lift_out[1] < 20.0:
            raise RuntimeError("lift 0.25 khong nhuc vung toi (%+.1f o do 10)" % lift_out[1])
        if lift_out[3] > 3.0:
            raise RuntimeError("lift 0.25 cham ca vung sang (%+.1f o do 250)" % lift_out[3])
        gam_out = lift_gamma_gain_rgb(strip, 0.0, 1.6, 1.0)[:, 0, 0] - strip[:, 0, 0]
        if gam_out[2] < 20.0:
            raise RuntimeError("gamma 1.6 khong bentre midtone (%+.1f o do 128)" % gam_out[2])
        if abs(gam_out[0]) > 0.5:
            raise RuntimeError("gamma 1.6 lam chang den (%+.1f o do 0)" % gam_out[0])
        if abs(gam_out[3]) > 8.0:
            raise RuntimeError("gamma 1.6 cham vung sang (%+.1f o do 250)" % gam_out[3])
        gain_out = float(lift_gamma_gain_rgb(levels(100.0), 0.0, 1.0, 1.5)[0, 0, 0])
        if abs(gain_out - 150.0) > 1.0:
            raise RuntimeError("gain 1.5 khong nhan tuyen tinh (%.1f thay vi 150)" % gain_out)
        per = lift_gamma_gain_rgb(levels(100.0), 0.0, 1.0,
                                  [1.5, 1.0, 1.0])[0, 0]
        if (abs(per[0] - 150.0) > 1.0 or abs(per[1] - 100.0) > 0.5
                or abs(per[2] - 100.0) > 0.5):
            raise RuntimeError("gain 3 kenh bi lech thu tu kenh %s" % np.round(per, 1))
        if lift_gamma_gain_rgb(strip, 0.0, 1.0, 1.0) is not strip:
            raise RuntimeError("bo lift/gamma/gain trung tinh van mo numpy")
        if lift_gamma_gain_rgb(strip, "khong phai so", 1.0, 1.0) is not strip:
            raise RuntimeError("gia tri lac kieu tu file cu lam hong khung hinh")

        # (3) Bo doc + ap .cube: thu tu kenh, LUT 1D, file rac, va cache phai
        #     theo noi dung moi lan ghi de.
        def write_cube(path, n, value):
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("LUT_3D_SIZE %d\n" % n)
                for ri in range(n):
                    for gi in range(n):
                        for bi in range(n):
                            r, g, b = (ri / (n - 1.0), gi / (n - 1.0),
                                       bi / (n - 1.0))
                            handle.write("%.6f %.6f %.6f\n" % value(r, g, b))

        ident = os.path.join(folder, "identity17.cube")
        swap = os.path.join(folder, "swap17.cube")
        write_cube(ident, 17, lambda r, g, b: (r, g, b))
        write_cube(swap, 17, lambda r, g, b: (b, g, r))
        palette = np.array([[[200.0, 30.0, 30.0], [30.0, 200.0, 30.0],
                             [30.0, 30.0, 200.0]]], np.float32)
        id_err = float(np.abs(lut_mod.apply_lut(palette, ident) - palette).max())
        if id_err > 2.0:
            raise RuntimeError("LUT identity lech %.1f/255: bang bi hoan vi kenh "
                               "hoac doc sai thu tu xanh-lam-nhanh-nhat" % id_err)
        sw = lut_mod.apply_lut(palette, swap)
        sw_err = float(np.abs(sw - palette[:, :, ::-1]).max())
        if sw_err > 3.0:
            raise RuntimeError("LUT hoan vi kenh sai chieu (lech %.1f/255)" % sw_err)

        one_d = os.path.join(folder, "gamma1d.cube")
        n1 = 33
        with open(one_d, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("LUT_1D_SIZE %d\n" % n1)
            for i in range(n1):
                v = (i / (n1 - 1.0)) ** 0.45
                handle.write("%.6f %.6f %.6f\n" % (v, v, v))
        ramp = lut_mod.apply_lut(levels(0.0, 128.0, 255.0), one_d)[:, 0, 0]
        if ramp[1] < 148.0:
            raise RuntimeError("LUT 1D khong duoc ap (do 128 ra %.1f)" % ramp[1])
        if abs(ramp[0]) > 1.0 or abs(ramp[2] - 255.0) > 1.0:
            raise RuntimeError("LUT 1D lam hong hai dau %s" % np.round(ramp, 1))

        junk = os.path.join(folder, "rac.cube")
        with open(junk, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("LUT_3D_SIZE 9\n0.0 0.0\nran\n")
        if lut_mod.load_lut(junk) is not None:
            raise RuntimeError("file cube rac khong bi bo qua (load_lut khong tra None)")
        if lut_mod.apply_lut(palette, junk) is not palette:
            raise RuntimeError("LUT hong bi ap len anh thay vi bo qua")
        gone = os.path.join(folder, "khong-ton-tai.cube")
        if lut_mod.apply_lut(palette, gone) is not palette:
            raise RuntimeError("LUT vo duong dan phai tra nguyen mang")

        # Cache phai biet file da doi: bang `%.6f` co so byte co dinh, nen dung
        # khoa theo giay thi sua .cube tai cho khong bao gio duoc nap lai.
        mutable = os.path.join(folder, "doi.cube")
        write_cube(mutable, 9, lambda r, g, b: (r, g, b))
        before_re = float(np.abs(lut_mod.apply_lut(palette, mutable) - palette).max())
        write_cube(mutable, 9, lambda r, g, b: (0.0, 0.0, 0.0))
        after_re = float(np.abs(lut_mod.apply_lut(palette, mutable)).max())
        if after_re > 2.0:
            raise RuntimeError("LUT bi thay noi dung van dung ban cu trong cache "
                               "(con %.1f/255, size khong doi = %d byte)"
                               % (after_re, os.path.getsize(mutable)))
        if before_re > 2.0:
            raise RuntimeError("lan doc dau cua .cube da sai (%.1f/255)" % before_re)

        # (4) Chuoi loc mau DI QUA HAM CHUNG: QImage + EffectData like trong
        #     model that, hue va LUT deu phai de lai dau vet tren pixel.
        flat = np.zeros((8, 8, 3), np.float32)
        flat[:, :, 0] = 200.0
        flat[:, :, 1] = 30.0
        flat[:, :, 2] = 30.0

        def chain(a, params):
            return rgb_of(apply_color_effects(qimage(a), [EffectData(
                name=GRADING_EFFECT_NAME, category=GRADING_EFFECT_NAME,
                intensity=1.0, params=dict(params))]))

        hue_px = chain(flat, {"hue_shift": 45.0})
        hue_gap = float((hue_px[:, :, 0] - hue_px[:, :, 1]).mean())
        flat_gap = float((flat[:, :, 0] - flat[:, :, 1]).mean())
        if hue_gap > flat_gap - 20.0:
            raise RuntimeError("chuoi loc bo qua hue_shift (do-luc %.1f -> %.1f)"
                               % (flat_gap, hue_gap))
        lut_px = chain(flat, {"lut_path": swap})
        if abs(lut_px[0, 0, 0] - 30.0) > 2.0 or abs(lut_px[0, 0, 2] - 200.0) > 2.0:
            raise RuntimeError("chuoi loc bo qua lut_path (kenh 0=%.1f kenh 2=%.1f)"
                               % (lut_px[0, 0, 0], lut_px[0, 0, 2]))
        neutral = chain(flat, GRADING_IDENTITY)
        base_px = rgb_of(qimage(flat))
        if not np.array_equal(neutral, base_px):
            raise RuntimeError("bo trung tinh gan nhe vao anh (%.2f/255 lech)"
                               % float(np.abs(neutral - base_px).max()))
        src = qimage(flat)
        passthrough = apply_color_effects(src, [EffectData(
            name="probe", category="Aura", intensity=1.0,
            params={"aura_size": 1.0})])
        if passthrough is not src:
            raise RuntimeError("the khong co khoa pixel nao bi mo numpy (round-trip)")
        if apply_color_effects(src, []) is not src:
            raise RuntimeError("danh sach hieu ung rong van chay chuoi loc")

        # (5) Seam cau truc: preview va export phai cung goi MOT ham, panel phai
        #     ghi qua LENH (khong noi vong len clip), va Ctrl+Z phai duoc doc
        #     lai. Bundle dong goi khong con file .py de grep, nen do co_names.
        seams = (
            ("FrameComposer._draw_media", FrameComposer._draw_media, "apply_color_effects"),
            ("CanvasClipItem.paint", CanvasClipItem.paint, "_apply_effects"),
            ("CanvasClipItem._apply_effects", CanvasClipItem._apply_effects, "apply_color_effects"),
            ("ClipPropertiesWidget._push_grading", ClipPropertiesWidget._push_grading, "SetGradingCommand"),
            ("ClipPropertiesWidget._push_grading", ClipPropertiesWidget._push_grading, "undo_stack"),
            ("ClipPropertiesWidget.update_values", ClipPropertiesWidget.update_values, "_sync_grading_card"),
        )
        missing = sorted({"%s thieu %s" % (who, helper)
                          for who, fn, helper in seams if helper not in walk_names(fn)})
        if missing:
            raise RuntimeError("seam chinh mau: %s" % "; ".join(missing))
        ns = {}
        exec(compile("class FakeGrade:\n"
                     "    def _draw(self):\n"
                     "        return 1\n", "<mau>", "exec"), ns)
        if "apply_color_effects" in walk_names(ns["FakeGrade"]._draw):
            raise RuntimeError("detector seam khong phan biet ham goi va khong goi")

        # (6) Vong doi cua lenh tren UndoStack THAT: 4 nac gamma = 1 buoc, num
        #     khac khoa = buoc moi, qua ngac 0.75s = buoc moi, ve trung tinh =
        #     boc the, Ctrl+Z tra lai du bo so.
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, os.path.join(folder, "anh.png"),
                              "image", 0.0, 4.0, name="grade")
        if clip is None:
            raise RuntimeError("add_clip image tra None (track IMAGE khong nhan image?)")
        stack = UndoStack()
        for g in (1.1, 1.2, 1.3, 1.4):
            stack.push(SetGradingCommand(model, clip.clip_id, {"gamma": g}))
        if stack.undo_count != 1:
            raise RuntimeError("keo 4 nac gamma thanh %d buoc undo (MERGE_WINDOW_S bi vo)"
                               % stack.undo_count)
        cards = [e for e in clip.effects if e.name == GRADING_EFFECT_NAME]
        if len(cards) != 1:
            raise RuntimeError("mot clip co %d the chinh mau (lenh hop nhat bi vo)"
                               % len(cards))
        if abs(grading_of(clip)["gamma"] - 1.4) > 1e-6:
            raise RuntimeError("gamma sau 4 nac la %.3f chu khong phai 1.4"
                               % float(grading_of(clip)["gamma"]))
        stack.push(SetGradingCommand(model, clip.clip_id, {"hue_shift": 30.0}))
        if stack.undo_count != 2:
            raise RuntimeError("num khac khoa bi gom chung vao mot buoc undo")
        desc = SetGradingCommand(model, clip.clip_id, {"hue_shift": 1.0}).description()
        if not desc:
            raise RuntimeError("lenh chinh mau khong co mo ta (undo_text trong)")
        if desc not in stack.undo_text:
            raise RuntimeError("undo_text khong mo ta dung lenh chinh mau dang dinh")
        stack._undo_stack[-1]._at -= SetGradingCommand.MERGE_WINDOW_S + 0.25
        stack.push(SetGradingCommand(model, clip.clip_id, {"hue_shift": 31.0}))
        if stack.undo_count != 3:
            raise RuntimeError("qua ngac %.2fs van gom keo thanh mot buoc undo"
                               % SetGradingCommand.MERGE_WINDOW_S)
        stack.undo()
        mid = grading_of(clip)
        if abs(mid["hue_shift"] - 30.0) > 1e-6 or abs(mid["gamma"] - 1.4) > 1e-6:
            raise RuntimeError("Ctrl+Z buoc cuoi lam lech bo so (%s)"
                               % {k: mid[k] for k in ("hue_shift", "gamma")})
        stack.push(SetGradingCommand(model, clip.clip_id, dict(GRADING_IDENTITY)))
        if clip.effects:
            raise RuntimeError("tha het ve trung tinh ma the chinh mau van con (%d the)"
                               % len(clip.effects))
        if grading_is_identity(GRADING_IDENTITY) is not True:
            raise RuntimeError("grading_is_identity khong coi bo mac dinh la trung tinh")
        stack.undo()
        if abs(grading_of(clip)["gamma"] - 1.4) > 1e-6:
            raise RuntimeError("Ctrl+Z sau reset khong tra lai du bo so")

        # (7) Model -> .clinq -> model: nam khong so phai la float, LUT van dung
        #     duong dan, va chi co DUY NHAT mot the.
        stack.push(SetGradingCommand(model, clip.clip_id, {
            "hue_shift": 45.0, "gamma": 1.6, "gain": 1.2, "lut_path": swap}))
        path = os.path.join(folder, "Kiem chinh mau.clinq")
        if not project_storage.save_project_to_file(model, path):
            raise RuntimeError("save_project_to_file that bai (payload chinh mau bi tu choi)")
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        back = TimelineModel()
        project_storage.restore_model_from_clinq(back, data)
        revived = back.active_visual_clips_at(0.5)
        if len(revived) != 1:
            raise RuntimeError("mo lai file co %d clip thay vi 1" % len(revived))
        p = grading_of(revived[0])
        lost = [k for k, v in (("hue_shift", 45.0), ("gamma", 1.6), ("gain", 1.2))
                if abs(float(p[k]) - v) > 1e-6]
        if os.path.normpath(str(p.get("lut_path") or "")) != swap:
            lost.append("lut_path")
        if lost:
            raise RuntimeError("chinh mau mat khi quay qua file: %s" % ", ".join(lost))
        if not isinstance(p["gamma"], float):
            raise RuntimeError("gamma mo lai la int (slider lech sau khi mo file)")
        if len([e for e in revived[0].effects if e.name == GRADING_EFFECT_NAME]) != 1:
            raise RuntimeError("file .clinq chua %d the chinh mau cho mot clip"
                               % len([e for e in revived[0].effects
                                      if e.name == GRADING_EFFECT_NAME]))

        return ("xoay truc xam 0.00->%.1f do-luc, lift +%.1f toi/%.1f sang, "
                "gamma mid %.1f, gain %.1f, LUT identity %.2f swap %.2f 1D %.1f, "
                "4 nac = %d buoc undo, 6 seam nguyen"
                % (gap_after, lift_out[1], lift_out[3], gam_out[2], gain_out,
                   id_err, sw_err, ramp[1], stack.undo_count))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _chroma_key_ok():
    """Một dòng --selftest: bộ dục nền (chroma key) phải cắt theo GÓC hue của màu
    khoá, giữ pixel trung tính ở MỌI dung sai, và để lại alpha trên đúng QImage
    mà preview lẫn export cùng vẽ.

    Ba cái bẫy đã trả giá khi viết bản đầu, nay thành bất biến (số đo ghi trong
    comment của core/clip_effects.py):
      (1) Khoảng cách Cb/Cr tới màu khoá KHÔNG thể là dung sai. Màu trắng cách
          nền xanh #00B140 những 83.7 đơn vị bão hoà — bản "distance" khoét luôn
          chủ thể ngay khi người dùng kéo núm; bản này PHẢI trả alpha 255 cho
          trắng/xám ở tolerance 1,0.
      (2) Núm rộng ra KHÔNG được làm mất màu nhạt: ngưỡng bão hoà phải CỐ ĐỊNH.
      (3) Matte phải đo TRƯỚC chuỗi lọc màu, nếu không thứ tự thẻ quyết định kết
          quả và preview lệch export theo cách không tài nào tái.
    feather/spill/undo/persistence: mọi ngưỡng dưới đây lấy từ chính bảng đo của
    hàm thật, không có số nào tự bày.
    """
    import os
    import shutil
    import tempfile
    import numpy as np
    from PySide6.QtGui import QImage
    from core import project_storage
    from core.clip_effects import (CHROMA_EFFECT_NAME, CHROMA_IDENTITY,
                                   CHROMA_KEYS, CHROMA_MATTE_MAX,
                                   GRADING_EFFECT_NAME, GRADING_KEYS,
                                   PIXEL_KEYS, apply_color_effects,
                                   chroma_is_identity, chroma_key_rgb,
                                   key_color_rgb)
    from core.commands import SetChromaCommand, UndoStack
    from core.frame_composer import FrameComposer
    from core.timeline_model import (EFFECT_PRESETS, EffectData, TimelineModel,
                                     TrackType)
    from ui.graphics_canvas_item import CanvasClipItem
    from ui.properties_panel import ClipPropertiesWidget

    if set(CHROMA_KEYS) & (set(PIXEL_KEYS) | set(GRADING_KEYS)):
        raise RuntimeError("CHROMA_KEYS trung khoa khac: mot the doi hai chuc nang")
    if CHROMA_EFFECT_NAME in EFFECT_PRESETS:
        raise RuntimeError("Chroma nam trong EFFECT_PRESETS: cua the ma cua "
                           "_effect_liveness_ok chua biet cach do no")
    stolen = sorted(name for name, params in EFFECT_PRESETS.items()
                    if set(CHROMA_KEYS) & set(params))
    if stolen:
        raise RuntimeError("preset %s dung khoa chroma:Bo loc se duc nen luong bat"
                          % ", ".join(stolen))

    KEY = "#00B140"
    PLATE = (("nen", (0.0, 177.0, 64.0)),          # 0.0 do: chinh mau nen
             ("la-cay", (60.0, 200.0, 60.0)),      # 19.8 do
             ("lan", (60.0, 190.0, 200.0)),        # 40.8 do
             ("xanh-nhat", (120.0, 180.0, 140.0)),  # 1.7 do nhung bao hoa thap
             ("trang", (245.0, 245.0, 245.0)),
             ("xam", (130.0, 130.0, 130.0)),
             ("den-xam", (40.0, 40.0, 40.0)),
             # 0.0 do (collinear Cb/Cr voi nen) nhung bao hoa 16.7 < floor 20:
             # hue trung voi nen, thu duy nhat bao no la nguong bao hoa
             # -> do rieng CHROMA_MAG_FLOOR, khong do bang hue.
             ("xanh-rat-nhat", (196.0, 231.4, 208.8)))
    strip = np.array([[colour] for _name, colour in PLATE], np.float32)
    at = {name: i for i, (name, _c) in enumerate(PLATE)}

    def matte_at(tol, feather=0.25, spill=0.0):
        params = dict(CHROMA_IDENTITY)
        params.update(key_color=KEY, tolerance=tol, feather=feather, spill=spill)
        return chroma_key_rgb(strip, params)

    def row(name, tol, feather=0.25, spill=0.0):
        return float(matte_at(tol, feather, spill)[1][at[name], 0])

    # (1) Nền PHẢI bị cắt ở mọi dung sai; chủ thể trung tính PHẢI sống ở dung sai
    #     max. Hai bất biến này đối nghịch với bản "khoảng cách Cb/Cr": bản đó cho
    #     trắng 83.7 (lớn hơn nền 0.0) nên khoét trắng trước khi khoét nền.
    #     So SANH ĐẢO (`not v >= lo`): pixel trung tính co mag 0 nen floor = 0
    #     chia 0/0 ra NaN, va `min()`/`v < lo` deu im lang voi NaN — do 21/10/2026
    #     khi doi byte MAG_FLOOR xuyen qua ca cua do trang lan cua do la-cay.
    worst_neutral = 1.0
    for name in ("trang", "xam", "den-xam", "xanh-rat-nhat"):
        v = row(name, 1.0)
        if not v >= 0.999:
            raise RuntimeError("tolerance 1.0 duc ca mau trung tinh (%s alpha %.3f): "
                               "nguong bao hoa bi thay bang khoang cach hue"
                               % (name, v))
        worst_neutral = min(worst_neutral, v)
    for tol in (0.05, 0.25, 0.5, 1.0):
        if row("nen", tol) > 0.01:
            raise RuntimeError("mau cua chinh bo khoa van con o alpha %.3f "
                               "(tolerance %.2f)" % (row("nen", tol), tol))

    # (1c) Vien mem phai co THAT: ton tai mot (mau, dung sai) ma feather 0 con
    #      giu chu the nhung feather 1 da an. Do TRUOC kiem num dung sai de mot
    #      lenh "soft_span = 0" do vi ly do cua chinh vien mem.
    #      Nguong la DOI (>= 0.5), khong phai gia tri tuyet doi < 0.2: voi num
    #      dung sai bi ve 0 do thi la-cay van mong 1.000 -> 0.287 o tolerance
    #      0.98, nen no phai do o cua (2) chu khong phai o day.
    edge = ("la-cay", "lan", "xanh-nhat")
    found = None
    for tol_i in range(1, 50):
        t = tol_i * 0.02
        for name in edge:
            if (row(name, t, 0.0) > 0.9
                    and row(name, t, 0.0) - row(name, t, 1.0) > 0.5):
                found = (name, round(t, 2))
                break
        if found:
            break
    if found is None:
        raise RuntimeError("vien mem khong lam mong bien o bat ky dung sai nao: "
                           "khong mau nao co alpha > 0.9 (feather 0) va giam "
                           "> 0.5 khi feather len 1")

    # (2) Num dung sai PHAI mo rong vong hue thay vi chi to den: la cay 19.8 do
    #     cat dan 1.000 -> 0.303 -> 0.000, lan 40.8 do chi cat tu 0.5.
    if row("la-cay", 0.05) < 0.9:
        raise RuntimeError("la cay 19.8 do bi cat o tolerance 0.05 (alpha %.3f): "
                           "num khong con dong cua" % row("la-cay", 0.05))
    if not (0.05 < row("la-cay", 0.15) < 0.6):
        raise RuntimeError("tolerance 0.15 khong mo vong toi la cay (alpha %.3f)"
                           % row("la-cay", 0.15))
    if row("la-cay", 0.30) > 0.05 or row("lan", 0.15) < 0.9 or row("lan", 0.5) > 0.05:
        raise RuntimeError("vong hue khong mo theo dung sai (la-cay 0.30 = %.3f, "
                           "lan 0.15 = %.3f, lan 0.5 = %.3f)"
                           % (row("la-cay", 0.30), row("lan", 0.15), row("lan", 0.5)))
    sweep = [row("la-cay", 0.01 + i * 0.05) for i in range(20)]
    if any(b > a + 1e-6 for a, b in zip(sweep, sweep[1:])):
        raise RuntimeError("num dung sai khong don dieu: alpha la-cay %s"
                           % [round(v, 3) for v in sweep])
    # Bay so (2): neu nguong bao hoa PHONG theo tolerance thi num rong ra lai
    # LAM MAT mau nhat. Do (120,180,140): alpha 0,060 o 0,05 va phai khong lon
    # hon o 0,9 (ban floor*(1+tol*0,4) da bi 0,974 — nguoc ban chat keyer).
    pale_lo, pale_hi = row("xanh-nhat", 0.05), row("xanh-nhat", 0.9)
    if pale_hi > pale_lo + 1e-6 or pale_hi > 0.2:
        raise RuntimeError("nguong bao hoa phong theo tolerance: mau nhat alpha "
                           "%.3f o 0.05 -> %.3f o 0.9" % (pale_lo, pale_hi))

    # (3) Num vien mem PHAI nong bien, khong chang trang nen hay lam chu the bi an.
    hard, soft = row("la-cay", 0.15, 0.0), row("la-cay", 0.15, 1.0)
    if not (hard - soft > 0.5):
        raise RuntimeError("feather 0 -> 1 chi nong bien duoc %.3f (la-cay %.3f -> %.3f)"
                           % (hard - soft, hard, soft))
    if row("nen", 0.4, 1.0) > 0.01 or row("trang", 0.4, 1.0) < 0.999:
        raise RuntimeError("vien mem 1.0 an chu the hoac de nen song (%.3f / %.3f)"
                           % (row("nen", 0.4, 1.0), row("trang", 0.4, 1.0)))

    # (4) Spill chi dung kenh NONG cua mau nen va khong duoc cham vao matte.
    rgb_off, a_off = matte_at(0.6, 0.25, 0.0)
    rgb_on, a_on = matte_at(0.6, 0.25, 0.8)
    g_neutral = float(rgb_off[at["nen"], 0, 1])
    g_keyed = float(rgb_on[at["nen"], 0, 1])
    if not (g_neutral - g_keyed > 60.0):
        raise RuntimeError("spill 0.8 khong keo kenh xanh cua nen (%.0f -> %.0f)"
                           % (g_neutral, g_keyed))
    for name in ("nen", "la-cay", "trang"):
        i = at[name]
        if (abs(float(rgb_on[i, 0, 0] - rgb_off[i, 0, 0])) > 1.0
                or abs(float(rgb_on[i, 0, 2] - rgb_off[i, 0, 2])) > 1.0):
            raise RuntimeError("spill dong luon kenh khac cua %s" % name)
    if float(np.abs(a_off - a_on).max()) > 1e-6:
        raise RuntimeError("chong ám lam doi matte (alpha lech %.4f)"
                           % float(np.abs(a_off - a_on).max()))
    untouched, _ = matte_at(0.0)
    if untouched is not strip:
        raise RuntimeError("tolerance 0 van mo numpy va atan2 (may cau hinh thap)")
    if chroma_is_identity(CHROMA_IDENTITY) is not True:
        raise RuntimeError("bo nut mac dinh khong phai la trung tinh")
    if chroma_is_identity({"tolerance": 0.0, "feather": 0.9, "spill": 0.7}) is not True:
        raise RuntimeError("the tolerance 0 con feather/spill khong bi coi la rong")
    if chroma_is_identity({"tolerance": 0.4}) is not False:
        raise RuntimeError("tolerance 0.4 bi coi la trung tinh: the bi boc khi dang dung")
    if key_color_rgb("#FF0000") != (255.0, 0.0, 0.0):
        raise RuntimeError("key_color_rgb doc sai hex (%s)" % (key_color_rgb("#FF0000"),))
    for bad in ("", None, "#xyz", "khong phai mau"):
        if key_color_rgb(bad) != key_color_rgb(CHROMA_IDENTITY["key_color"]):
            raise RuntimeError("mau doc khong duoc (%r) khong tra ve nen mac dinh" % bad)

    def qimage_rgb(arr):
        a = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
        h, w = a.shape[:2]
        rgba = np.ascontiguousarray(
            np.dstack([a, np.full((h, w, 1), 255, np.uint8)]))
        return QImage(rgba.data, w, h, w * 4,
                      QImage.Format.Format_RGBA8888).copy()

    def rgba_of(image):
        img = image.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4)).astype(np.float64)

    # (4b) MATTE PHAI DUOC TINH O DO THU NHO. Do 21/10/2026 tren may nay
    #      (numpy 2.4.6, SIMD chi X86_V2): toan bo phep tinh matte tai 640x360
    #      = 54 ms/frame, trong do rieng atan2 11,8 ms/230k phan tu; rut ve 256
    #      px con 10,3 ms. Day la dieu kien "toi u cho may cau hinh thap" cua
    #      AGENTS.md, nen do ca HAI chieu: canh thu nho THAT SU chay (gate xanh
    #      vi nhanh bi vo hieu hoa thi vo nghia), va no KHONG doi quyet dinh ben
    #      trong vung dong nhat — chi duoc lam le duong bien.
    from core import clip_effects as _ce
    frame = np.zeros((360, 640, 3), np.float32)
    frame[:, :] = (0.0, 177.0, 64.0)
    frame[150:210, 290:350] = (200.0, 40.0, 190.0)     # chu the 60x60, hue xa nen
    big_params = dict(CHROMA_IDENTITY)
    big_params.update(key_color=KEY, tolerance=0.45, feather=0.25)
    small_plate, upscale_to = _ce._matte_plate(frame)
    if upscale_to is None or max(small_plate.shape[:2]) > CHROMA_MATTE_MAX:
        raise RuntimeError("branch thu nho matte khong chay o 640x360 "
                           "(plate %s, upscale %s): do luong 54 ms/frame van con "
                           "nguyen" % (small_plate.shape[:2], upscale_to))
    alpha_small = chroma_key_rgb(frame, big_params)[1]
    _saved_max = _ce.CHROMA_MATTE_MAX
    try:
        _ce.CHROMA_MATTE_MAX = 10 ** 9
        alpha_full = chroma_key_rgb(frame, big_params)[1]
    finally:
        _ce.CHROMA_MATTE_MAX = _saved_max
    core = np.zeros(frame.shape[:2], bool)
    core[165:195, 305:335] = True                      # 15 px le bien chu the
    far = np.ones(frame.shape[:2], bool)
    far[135:225, 275:365] = False                      # nen cach bien >= 15 px
    if alpha_small[core].min() < 0.98:
        raise RuntimeError("thu nho matte an chu the (alpha min %.3f o loi chu the)"
                           % float(alpha_small[core].min()))
    if alpha_small[far].max() > 0.02:
        raise RuntimeError("thu nho matte khong cat het nen (alpha max %.3f)"
                           % float(alpha_small[far].max()))
    agree = np.abs(alpha_small - alpha_full)
    agree_max = max(float(agree[core].max()), float(agree[far].max()))
    if agree_max > 0.02:
        raise RuntimeError("matte thu nho doi quyet dinh ben trong vung dong nhat "
                           "(lech %.3f so voi do day du)" % agree_max)

    folder = tempfile.mkdtemp(prefix="clinging_chroma_")
    try:
        # (5) Chuoi loc DI QUA HAM CHUNG: that su phai co kenh alpha tren QImage
        #     ma CanvasClipItem va FrameComposer cung ve. Moi DONG la mot mau.
        rows = (at["nen"], at["trang"], at["xam"], at["la-cay"])
        plate = strip[list(rows)].repeat(6, axis=1)        # (4,6,3)
        src = qimage_rgb(plate)

        def card(**over):
            params = dict(CHROMA_IDENTITY)
            params.update(key_color=KEY)
            params.update(over)
            return EffectData(name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                              intensity=1.0, params=params)

        keyed = rgba_of(apply_color_effects(src, [card(tolerance=0.4)]))
        base = rgba_of(src)
        for i, name in ((1, "trang"), (2, "xam")):
            got = keyed[i, :, 3].min()
            if got < 253.0:
                raise RuntimeError("%s bi duc o QImage that (alpha %.0f):chuoi loc "
                                   "khong giu kenh alpha" % (name, got))
        if keyed[0, :, 3].max() > 3.0:
            raise RuntimeError("nen con alpha %.0f trong QImage"
                               % keyed[0, :, 3].max())
        if keyed[3, :, 3].max() > 3.0:
            raise RuntimeError("la cay (19.8 do) con song o tolerance 0.4 trong QImage")
        kept_rgb = np.abs(keyed[1, :, :3] - base[1, :, :3]).max()
        if kept_rgb > 1.0:
            raise RuntimeError("mau giu nguyen bi xich %.1f/255 boi phep duc nen"
                               % kept_rgb)
        # (5b) Frame THAT (640x360 = dung cap proxy cua chuoi loc, nen matte
        #      dung canh thu nho) phai cat duoc nen va giu chu the qua dung
        #      duong QImage. Dat SAU cac dong o tren de hai phep doi byte
        #      "pre-pass bi tat" va "matte dao nguoc" do vi ly do cua chinh
        #      chung (nen con alpha / chu the bi duc), khong bi doan nay chan.
        keyed_chain = rgba_of(apply_color_effects(
            qimage_rgb(frame), [EffectData(
                name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                intensity=1.0, params=dict(big_params))]))[:, :, 3]
        if keyed_chain[core].min() < 248.0 or keyed_chain[far].max() > 6.0:
            raise RuntimeError("chuoi that tai 640x360: chu the %.0f, nen %.0f "
                               "(alpha tren QImage sau khi thu nho matte)"
                               % (keyed_chain[core].min(), keyed_chain[far].max()))
        # The trung tinh (tolerance 0) KHONG duoc mo numpy: day la duong tat
        # may cau hinh thap va la ly do SetChromaCommand boc the.
        if apply_color_effects(src, [card(tolerance=0.0)]) is not src:
            raise RuntimeError("the chroma trung tinh van chay chuoi loc")
        if apply_color_effects(src, [EffectData(
                name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME, intensity=1.0,
                params={"key_color": KEY, "feather": 0.8, "spill": 0.6})]) is not src:
            raise RuntimeError("the chroma khong co tolerance van mo numpy")

        # (6) Thu tu the KHONG duoc doi matte: phep tinh nam TRUOC vong lap loc
        #     mau, nen "Bo loc" (lam nhiem nen) dat truoc hay sau cung mot ket qua.
        rival = EffectData(name="Cool Blue", category="Sắc thái", intensity=1.0,
                           params={"brightness": 0.2, "contrast": 1.4,
                                   "saturation": 0.3, "color_temp": -0.2})
        grade = EffectData(name=GRADING_EFFECT_NAME, category=GRADING_EFFECT_NAME,
                           intensity=1.0, params={"hue_shift": 90.0})
        alpha_ref = rgba_of(apply_color_effects(
            src, [card(tolerance=0.4)]))[:, :, 3]
        alpha_rival = rgba_of(apply_color_effects(
            src, [rival, card(tolerance=0.4)]))[:, :, 3]
        if np.abs(alpha_ref - alpha_rival).max() > 1e-6:
            raise RuntimeError("loc mau dat truoc doi matte (lech %.1f/255):preview "
                               "va export khong the trung nhau"
                               % float(np.abs(alpha_ref - alpha_rival).max()))
        alpha_later = rgba_of(apply_color_effects(
            src, [card(tolerance=0.4), rival, grade]))[:, :, 3]
        if np.abs(alpha_ref - alpha_later).max() > 1e-6:
            raise RuntimeError("the chroma dat dau chuoi choi doi matte (%.1f/255)"
                               % float(np.abs(alpha_ref - alpha_later).max()))

        # (7) Seam cau truc: preview + export cung goi MOT ham, panel ghi qua LENH.
        seams = (
            ("apply_color_effects", apply_color_effects, "chroma_key_rgb"),
            ("FrameComposer._draw_media", FrameComposer._draw_media, "apply_color_effects"),
            ("CanvasClipItem._apply_effects", CanvasClipItem._apply_effects, "apply_color_effects"),
            ("ClipPropertiesWidget._push_chroma", ClipPropertiesWidget._push_chroma, "SetChromaCommand"),
            ("ClipPropertiesWidget._push_chroma", ClipPropertiesWidget._push_chroma, "undo_stack"),
            ("ClipPropertiesWidget.update_values", ClipPropertiesWidget.update_values, "_sync_chroma_card"),
        )

        def walk_names(fn):
            seen = set()
            stack = [fn.__code__]
            while stack:
                code = stack.pop()
                seen.update(code.co_names)
                for const in code.co_consts:
                    if hasattr(const, "co_names") and const not in seen:
                        stack.append(const)
            return seen

        missing = sorted({"%s thieu %s" % (who, helper)
                          for who, fn, helper in seams if helper not in walk_names(fn)})
        if missing:
            raise RuntimeError("seam chroma: %s" % "; ".join(missing))
        ns = {}
        exec(compile("class FakeKey:\n"
                     "    def _draw(self):\n"
                     "        return 1\n", "<mau>", "exec"), ns)
        if "chroma_key_rgb" in walk_names(ns["FakeKey"]._draw):
            raise RuntimeError("detector seam khong phan biet ham goi va khong goi")

        # (8) Vong doi cua lenh tren UndoStack THAT.
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, os.path.join(folder, "nen.png"),
                              "image", 0.0, 4.0, name="chroma")
        if clip is None:
            raise RuntimeError("add_clip image tra None (track IMAGE khong nhan image?)")

        def chroma_of(item):
            for e in item.effects:
                if e.name == CHROMA_EFFECT_NAME:
                    merged = dict(CHROMA_IDENTITY)
                    merged.update(e.params or {})
                    return merged
            return dict(CHROMA_IDENTITY)

        stack = UndoStack()
        for t in (0.1, 0.2, 0.3, 0.4):
            stack.push(SetChromaCommand(model, clip.clip_id, {"tolerance": t}))
        merged_steps = stack.undo_count
        if merged_steps != 1:
            raise RuntimeError("keo 4 nac dung sai thanh %d buoc undo (MERGE_WINDOW_S bi vo)"
                               % merged_steps)
        cards = [e for e in clip.effects if e.name == CHROMA_EFFECT_NAME]
        if len(cards) != 1:
            raise RuntimeError("mot clip co %d the chroma (lenh hop nhat bi vo)" % len(cards))
        if abs(chroma_of(clip)["tolerance"] - 0.4) > 1e-6:
            raise RuntimeError("dung sai sau 4 nac la %.3f chu khong phai 0.4"
                               % float(chroma_of(clip)["tolerance"]))
        stack.push(SetChromaCommand(model, clip.clip_id, {"key_color": "#FF0000"}))
        if stack.undo_count != 2:
            raise RuntimeError("num khac khoa bi gom chung vao mot buoc undo")
        desc = SetChromaCommand(model, clip.clip_id, {"key_color": "#FF0000"}).description()
        if not desc or desc not in stack.undo_text:
            raise RuntimeError("undo_text khong mo ta dung lenh chroma (%r / %r)"
                               % (desc, stack.undo_text))
        stack._undo_stack[-1]._at -= SetChromaCommand.MERGE_WINDOW_S + 0.25
        stack.push(SetChromaCommand(model, clip.clip_id, {"key_color": "#FF0000"}))
        if stack.undo_count != 3:
            raise RuntimeError("qua ngac %.2fs van gom keo thanh mot buoc undo"
                               % SetChromaCommand.MERGE_WINDOW_S)
        stack.undo()
        mid = chroma_of(clip)
        if abs(mid["tolerance"] - 0.4) > 1e-6 or mid["key_color"] != "#FF0000":
            raise RuntimeError("Ctrl+Z buoc cuoi lam lech bo so (%.3f / %s)"
                               % (float(mid["tolerance"]), mid["key_color"]))
        stack.push(SetChromaCommand(model, clip.clip_id, dict(CHROMA_IDENTITY)))
        if clip.effects:
            raise RuntimeError("tha het ve trung tinh ma the chroma van con (%d the)"
                               % len(clip.effects))
        stack.undo()
        if abs(chroma_of(clip)["tolerance"] - 0.4) > 1e-6:
            raise RuntimeError("Ctrl+Z sau reset khong tra lai dung sai")

        # (9) Model -> .clinq -> model: hex van la str, num van la float, dung mot the.
        stack.push(SetChromaCommand(model, clip.clip_id, {
            "key_color": "#123456", "tolerance": 0.6, "feather": 0.8, "spill": 0.5}))
        path = os.path.join(folder, "Duc nen.clinq")
        if not project_storage.save_project_to_file(model, path):
            raise RuntimeError("save_project_to_file that bai (payload chroma bi tu choi)")
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        back = TimelineModel()
        project_storage.restore_model_from_clinq(back, data)
        revived = back.active_visual_clips_at(0.5)
        if len(revived) != 1:
            raise RuntimeError("mo lai file co %d clip thay vi 1" % len(revived))
        p = chroma_of(revived[0])
        lost = [k for k, v in (("tolerance", 0.6), ("feather", 0.8), ("spill", 0.5))
                if abs(float(p[k]) - v) > 1e-6]
        if str(p.get("key_color")) != "#123456":
            lost.append("key_color")
        if lost:
            raise RuntimeError("chroma mat khi quay qua file: %s" % ", ".join(lost))
        if not isinstance(p["tolerance"], float):
            raise RuntimeError("tolerance mo lai la %s (slider lech sau khi mo file)"
                               % type(p["tolerance"]).__name__)
        if not isinstance(p["key_color"], str):
            raise RuntimeError("key_color mo lai la %s: QColor khong luu duoc trong JSON"
                               % type(p["key_color"]).__name__)
        n_cards = len([e for e in revived[0].effects if e.name == CHROMA_EFFECT_NAME])
        if n_cards != 1:
            raise RuntimeError("file .clinq chua %d the chroma cho mot clip" % n_cards)
        if not isinstance(apply_color_effects(src, [card(tolerance=0.4)]), QImage):
            raise RuntimeError("duc nen khong tra ve QImage: ca hai duong ve deu hong")

        return ("nen 0.000 moi dung sai, la-cay 19.8 do alpha %.3f->%.3f->%.3f theo "
                "num 0.05/0.15/0.30, lan 40.8 do cat tu 0.50, 4 mau trung tinh con "
                "%.3f o tolerance 1.0 (ke ca 0.0 do mag 16.7), bien mong %s tai "
                "tolerance %.2f, feather 0->1 "
                "lam mong %.3f->%.3f, spill %.0f->%.0f khong doi matte, "
                "matte %d px (lech %.4f so voi do day du tai 640x360), "
                "4 nac = %d buoc undo, %d seam, round-trip 1 the"
                % (row("la-cay", 0.05), row("la-cay", 0.15), row("la-cay", 0.30),
                   worst_neutral, found[0], found[1], hard, soft,
                   g_neutral, g_keyed, CHROMA_MATTE_MAX, agree_max,
                   merged_steps, len(seams)))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _project_fixture():
    """Một file ``.clinq`` thật trong TEMP, đủ giá trị cụ thể để đối chiếu.

    Dự án của người dùng không được dùng làm vật thử: báo cáo này mở project
    thật, và mở thì có autosave đè lên.
    """
    import json
    import tempfile
    video = _report_video()
    wav = _report_wav()
    folder = os.path.join(tempfile.gettempdir(), "clinging_project_report")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "Kiem chung.clinq")
    data = {
        "project_meta": {
            "project_id": "proj-report", "project_name": "Kiem chung mo tu file",
            "created_at": "2026-10-18T00:00:00", "last_modified": "2026-10-18T00:00:00",
            "resolution": {"width": 1080, "height": 1920}, "fps": 30,
            "aspect_ratio": "9:16", "version": "1.0",
        },
        "assets": {
            "a-video": {"type": "video", "path": video, "original_duration": 4.0},
            "a-audio": {"type": "audio", "path": wav, "original_duration": 4.0},
        },
        "timeline": {
            "duration": 6.0, "playhead": 0.0,
            # Clip trên track chính phải liền mạch: ``recalculate_main_storyline``
            # khép mọi khoảng hở ở đó, nên một khe hở 0.5 s trong file sẽ không
            # bao giờ xuất hiện lại trong model. Khe hở thật của phép thử nằm ở
            # track AUDIO (c-tone bắt đầu ở 1.0) — đó là chỗ phải giữ nguyên.
            "tracks": [
                {"track_id": "t-main", "track_type": "VIDEO", "name": "Main",
                 "z_index": 1, "is_main_track": True, "is_locked": False,
                 "is_visible": True, "is_muted": False, "color": "#4FC3F7",
                 "clips": [
                     {"clip_id": "c-one", "timeline_in": 0.0, "timeline_out": 2.0,
                      "duration": 2.0, "source_duration": 4.0, "asset_id": "a-video",
                      "source_path": video, "media_type": "video",
                      "name": "probe-a.mp4", "trim_in": 0.0, "trim_out": 2.0},
                     {"clip_id": "c-two", "timeline_in": 2.0, "timeline_out": 5.5,
                      "duration": 3.5, "source_duration": 4.0, "asset_id": "a-video",
                      "source_path": video, "media_type": "video",
                      "name": "probe-b.mp4", "trim_in": 0.5, "trim_out": 4.0},
                 ]},
                {"track_id": "t-music", "track_type": "AUDIO", "name": "Nhac",
                 "z_index": 0, "is_main_track": False, "is_locked": False,
                 "is_visible": True, "is_muted": False, "color": "#81C784",
                 "clips": [
                     {"clip_id": "c-tone", "timeline_in": 1.0, "timeline_out": 5.0,
                      "duration": 4.0, "source_duration": 4.0, "asset_id": "a-audio",
                      "source_path": wav, "media_type": "audio",
                      "name": "tone.wav", "trim_in": 0.0, "trim_out": 4.0},
                 ]},
            ],
        },
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return path, data


def _cache_guard_start(tag):
    """Don duong ghi cache anh cua MOT probe ra khoi %APPDATA% cua nguoi dung.

    Probe nay mo MainWindow that nen keo theo `ResourceCard` /
    `ClipTimelineItem._load_thumbnail` -> `media_cache.write_image`, tuc la moi
    lan chay them anh nho cua FIXTURE vao cache that. Do 23/10/2026: mot lan
    `--style-report` them 7 muc, mot lan `--project-report` them 6 muc duoi
    `%APPDATA%\Roaming\Clinging\cache\image`, trong khi `DOI: 0` (khong pha gi)
    nen selftest khong bao gio phat hien. Van di qua DUNG duong ghi that
    (temp + `os.replace` + budget) chi khac goc.
    """
    import shutil
    import tempfile
    from core import media_cache
    real_root = os.path.join(str(os.environ.get("APPDATA", "")), "Clinging",
                             "cache")

    def listing(root):
        found = set()
        if not os.path.isdir(root):
            return found
        for sub, _dirs, files in os.walk(root):
            for name in files:
                found.add(os.path.relpath(os.path.join(sub, name), root))
        return found

    folder = os.path.join(tempfile.gettempdir(), "clinging_%s_cache" % tag)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    state = {"real_cache_root": media_cache.cache_root, "folder": folder,
             "before": listing(real_root), "real_root": real_root,
             "shutil": shutil}
    media_cache.cache_root = lambda: folder
    return state


def _cache_guard_finish(state):
    """Khoi phuc `cache_root`, tra ve danh sach muc cache THAT bi them/mat.

    Rong = probe khong cham vao cache cua nguoi dung. Thu muc tam duoc xoa o
    day nen lan chay ke tiep khong de lai rac (%TEMP% la noi duy nhat no ghi).
    """
    from core import media_cache
    media_cache.cache_root = state["real_cache_root"]
    changed = sorted(state["before"] ^ _cache_listing(state["real_root"]))
    state["shutil"].rmtree(state["folder"], ignore_errors=True)
    return changed


def _cache_listing(root):
    found = set()
    if not os.path.isdir(root):
        return found
    for sub, _dirs, files in os.walk(root):
        for name in files:
            found.add(os.path.relpath(os.path.join(sub, name), root))
    return found


def run_project_report(argv=None):
    """Mở project từ dòng lệnh — đo từ chính bản exe đã cài.

    ``--selftest`` chỉ chứng minh module có trong bundle. Cái phải do file exe
    cài vào máy tự đo là: đường dẫn mà Explorer trao khi nhấp đúp một
    ``.clinq`` có thật đi tới ĐÚNG cửa dựng phim, với ĐÚNG dữ án — vì mọi lỗi
    ở đoạn này đều im lặng: app vẫn mở, chỉ là mở nhầm trang hoặc mở rỗng.

    Bốn thứ báo cáo này đo:
      * ``core.project_storage.project_arg_from_argv`` đọc ra đúng đường dẫn từ
        argv thật của process;
      * ``MainController.open_project_path`` đi qua ``_on_open_project`` —
        cùng hàm thẻ ở Home gọi — nên timeline có ĐÚNG ``(start, duration,
        media_type, source)`` của file đang mở, thư viện có đủ tài nguyên của
        file, tên dự án và tỉ lệ khung hình hiện đúng;
      * một đường dẫn KHÔNG có thật phải trả False và để nguyên cửa đang mở,
        không được thả người dùng vào một timeline trống;
      * ảnh bằng chứng là bản sao 1:1 của cửa thật sau khi mở.

    Kỳ vọng lấy từ chính file được mở (fixture chỉ là mặc định khi không có
    argv), nên cùng một lệnh chạy được trên dự án thật của người dùng:
    ``Clinging.exe --project-report <json> <duong-dan-clinq>``
    """
    argv = list(argv if argv is not None else sys.argv)
    fixture, fixture_data = _project_fixture()
    out = ""
    for arg in argv[1:]:
        if not arg.startswith("-") and arg.lower().endswith(".json"):
            out = os.path.abspath(arg)
    out = out or os.path.join(os.environ.get("TEMP", os.getcwd()),
                              "clinging_project.json")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"
    cache_state = _cache_guard_start("project_report")

    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(count=10):
        for _ in range(count):
            app.processEvents()

    from core.project_storage import project_arg_from_argv
    # Parse argv THAT của process này, không phải một danh sách tự dựng: lỗi
    # kiểu "mất đường dẫn vì dấu cách" chỉ tồn tại ở chuỗi Explorer gửi tới.
    argv_with_project = list(argv)
    if project_arg_from_argv(argv_with_project) is None:
        argv_with_project.append(fixture)
    parsed = project_arg_from_argv(argv_with_project)
    # Kỳ vọng ĐỌC TỪ CHÍNH FILE được mở, không phải từ fixture: cùng một báo
    # cáo phải nói được "Dự án 2.clinq của người dùng mở đúng", nếu không nó
    # chỉ là một bài kiểm tra tự đóng quanh dữ liệu của mình.
    from core.project_storage import load_project_from_file
    data = load_project_from_file(parsed) or fixture_data

    from core.project_storage import ProjectManager
    from ui.main_controller import MainController
    controller = MainController()
    controller.show()
    pump(14)
    home_first = controller.stack.currentWidget() is controller.home_page

    opened = controller.open_project_path(parsed)
    pump(14)

    editor = controller.editor_page
    on_editor = (opened and editor is not None
                 and controller.stack.currentWidget() is editor)
    model = editor.timeline_panel.model if editor else None
    clips = {}
    kinds = set()
    if model:
        for track in model.tracks:
            kinds.add(str(track.track_type))
            for clip in track.clips:
                clips[clip.clip_id] = (round(clip.start_time, 3),
                                       round(clip.duration, 3),
                                       clip.media_type,
                                       os.path.basename(clip.source_path))
    want = {c["clip_id"]: (c["timeline_in"], c["duration"], c["media_type"],
                           os.path.basename(c["source_path"]))
            for track in data["timeline"]["tracks"]
            for c in track["clips"]}
    resources = [(os.path.basename(r["path"]), r["type"])
                 for r in (editor.library_panel.resource_records()
                           if editor else [])]
    # THU TU la thuoc tinh phai do: thu vien tai hien theo dung tay file ghi
    # vao. Sap xep mot ben roi so voi danh sach chua sap xep o ben kia tao ra
    # mot FAIL sai (do chinh probe installed_app_probe bat duoc lan dau).
    want_resources = [(os.path.basename(a["path"]), a["type"])
                      for a in data["assets"].values()]
    title = editor.title_bar.project_name.text() if editor else ""
    ratio = (editor.timeline_panel.header.combo_aspect_ratio.currentText()
             if editor else "")
    pm_path = ProjectManager().project_path

    bogus = os.path.join(os.path.dirname(fixture), "khong-ton-tai.clinq")
    before_bogus = dict(clips)
    rejected = controller.open_project_path(bogus)
    pump(6)
    still_editor = (controller.stack.currentWidget() is editor
                    and dict(clips) == before_bogus
                    and len(model.tracks) > 0)

    panel = controller.grab()
    width = panel.width()
    height = panel.height() + 150
    canvas = QImage(width, height, QImage.Format_RGB32)
    canvas.fill(QColor("#0F1014").rgb())
    painter = QPainter(canvas)
    # QRect theo KICH THUOC THIET BI: drawPixmap(x, y, pm) tren canvas DPR 1 co
    # pm DPR 1.25 ep anh xuong 80% va lam mong manh net chu trong bang chung.
    painter.drawPixmap(QRect(0, 0, panel.width(), panel.height()), panel)
    painter.setFont(QFont("Segoe UI", 9))
    painter.setPen(QPen(QColor("#C8CBD4")))
    lines = [
        "exe: %s (frozen=%s)" % (os.path.abspath(sys.argv[0]),
                                 bool(getattr(sys, "frozen", False))),
        "argv -> %s" % (parsed or "(khong co)"),
        "mo = %s, dung editor = %s, tu Home = %s" % (opened, on_editor,
                                                     home_first),
        "clip = %d/%d khop (start, duration, kieu, nguon)" % (
            len([k for k in want if clips.get(k) == want[k]]), len(want)),
        "thu vien = %r, ten = %r, ti le = %r" % (resources, title, ratio),
        "duong gia = %r (muon False), cua van nguyen = %s" % (rejected,
                                                              still_editor),
    ]
    y = panel.height() + 24
    for line in lines:
        painter.drawText(8, y, line)
        y += 20
    painter.end()
    canvas.save(shot)

    colors = 0
    if os.path.isfile(shot):
        grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
        colors = len({grabbed.pixel(x_, p_)
                      for p_ in range(0, grabbed.height(), 7)
                      for x_ in range(0, grabbed.width(), 7)})

    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "frozen": bool(getattr(sys, "frozen", False)),
        "argv_duoc": parsed,
        "mo_duoc": opened,
        "o_editor": on_editor,
        "khoi_dong_tu_home": home_first,
        "project_path": pm_path,
        "clips": {k: list(v) for k, v in sorted(clips.items())},
        "clips_muon": {k: list(v) for k, v in sorted(want.items())},
        "loai_track": sorted(kinds),
        "thu_vien": resources,
        "thu_vien_muon": want_resources,
        "ten_du_an": title,
        "ti_le": ratio,
        "duong_gia": {"tra_ve": rejected, "nguyen_hien_tai": still_editor},
        "screenshot": os.path.abspath(shot),
        "distinct_colors": colors,
        "lines": lines,
    }
    controller.close()
    pump(8)
    cache_extra = _cache_guard_finish(cache_state)
    payload["user_cache_extra"] = cache_extra
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    # Moi ky vong doc TREN CHINH FILE mo ra, khong phai hardcode cho fixture:
    # cung cay do nay phai noi duoc "Du an 2.clinq cua nguoi dung mo dung",
    # neu khong no chi la bai kiem tra tu dong quanh du lieu no tu sinh.
    want_kinds = sorted("TrackType." + str(t.get("track_type", "")).upper()
                        for t in data["timeline"]["tracks"])
    ok = (opened and on_editor and home_first
          and os.path.abspath(parsed) == os.path.abspath(str(pm_path or ""))
          and clips == {k: tuple(v) for k, v in want.items()}
          and sorted(kinds) == want_kinds
          and resources == want_resources
          and payload["ten_du_an"] == data["project_meta"]["project_name"]
          and payload["ti_le"].startswith(data["project_meta"]["aspect_ratio"])
          and rejected is False and still_editor
          and colors > 40 and os.path.isfile(shot) and not cache_extra)
    return 0 if ok else 1


def run_startup_report(argv=None):
    """Do duong boot cua CHINH ban nay: tung pha mat bao lau va giu bao nhieu RAM.

    Ham goi thang `main._boot()` — dung duong ma nguoi dung di — nen khong co
    "ban phat cho do" chay nhanh hon ban that: duong thu hai la loi chung minh
    thu hai.

    Phep phan biet nam trong `control`: hai viec lech nhau hang chuc lan chi phi
    phai cho hai con so khac nhau; chung bang nhau nghia la dong ho hong,
    khong phai app nhanh. `checks` la phan ket luan — moi dong la mot dieu ban
    CHUA toi uu that bai (cv2 nam trong duong boot, tem RAM tra ve 0), nen xanh
    hom nay la do do, khong phai do phep do khong the do.

    Clinging.exe --startup-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    report = _report_path(argv).replace("clinging_selftest", "clinging_startup")

    entry = sys.modules.get("__main__")
    boot = getattr(entry, "_boot", None)
    marks = getattr(entry, "BOOT_MARKS", None)
    mark = getattr(entry, "_mark", None)
    if boot is None or marks is None or mark is None:
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"exe": os.path.abspath(sys.argv[0]),
                       "error": "main._boot khong co san de do"},
                      handle, ensure_ascii=False, indent=2)
        return 1

    app, controller = boot()
    deadline = time.time() + 10.0
    while time.time() < deadline and not controller.isVisible():
        app.processEvents()
        time.sleep(0.02)
    exposed = controller.isVisible()
    # Khoanh do DUNG luc cua so lo ra, khong phai luc ket thuc: cv2 tro ve bo nho
    # sau khi hang doi bia chay mot vai luot, va neu do o cuoi thi khong con phan
    # biet duoc "boot" voi "sau boot".
    cv2_at_window = "cv2" in sys.modules
    editor_at_window = "ui.main_window" in sys.modules
    psutil_at_window = "psutil" in sys.modules
    nen_at_window = ("ui.compress_dialog" in sys.modules
                     or "core.media_compress" in sys.modules)
    # Ten module phai ghi DUA CAI TEN THAT: `boot_khong_keo_nen` xanh khong ham
    # y "khong hop thoai nao bi keo vao boot" (bẫy 21/10 ở ngay duoi). Pack SFX
    # nam sau hai ten nay, va `ui.sfx_dialog` keo theo QAudioOutput.
    sfx_at_window = ("ui.sfx_dialog" in sys.modules or "core.sfx" in sys.modules)
    #Hop thoai "Boc cuc & Phong cach" chi can luc bam nut: no keo theo QColorDialog
    # va QScrollArea, con `core.canvas_layout` thi lenh ve cua canvas nam trong
    # duong boot cua cua so (core.timeline_model) nen do rieng ten module UI.
    bocuc_at_window = "ui.canvas_layout_dialog" in sys.modules
    mark("cua so lo ra")
    settle_until = time.time() + 1.5
    while time.time() < settle_until:
        app.processEvents()
        time.sleep(0.02)
    mark("ngam sau 1.5s")
    cv2_at_idle = "cv2" in sys.modules

    # Phep phan biet cua dong ho: hai viec co chi phi that bai khac nhau, do
    # bang cung mot cach. Nhe va nang ra so bang nhau nghia la dong ho hong,
    # khong phai app nhanh. (Dung `import cv2` lam phep thu la mot loi: no da
    # duoc nap truoc do nen luon ra 0 — do no o cv2_da_nap_luc_boot.)
    control = {}
    for label, size in (("nhe", 10), ("nang", 3000000)):
        started = time.perf_counter()
        sum(range(size))
        control[label + "_s"] = round(time.perf_counter() - started, 4)
    control["cv2_da_nap_luc_boot"] = cv2_at_window
    control["cv2_luc_ngam"] = cv2_at_idle

    # Bia do ho dong nap sau khi cua so da ve, nen phai kiem duoc no den noi:
    # moi card gan day phai mang mot QPixmap that, khong phai cho nem mac dinh.
    from ui.home_page import RecentProjectCard
    grid = getattr(controller.home_page, "recent_grid", None)
    cards = covers = 0
    for i in range(grid.count() if grid else 0):
        item = grid.itemAt(i)
        widget = item.widget() if item else None
        if isinstance(widget, RecentProjectCard):
            cards += 1
            if widget.thumb_label.pixmap() and not widget.thumb_label.pixmap().isNull():
                covers += 1
    shot = os.path.join(os.path.dirname(report),
                        os.path.basename(report).rsplit(".", 1)[0] + ".png")
    controller.grab().save(shot)

    phases, previous = [], 0.0
    for name, at, ram in marks:
        phases.append({"name": name, "dt_s": round(at - previous, 4),
                       "t_s": round(at, 4), "ram_kib": ram})
        previous = at
    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "python": sys.version.split()[0],
               "window_exposed": bool(exposed),
               "window_size": [controller.width(), controller.height()],
               "marks": [{"name": n, "t_s": round(t, 4), "ram_kib": r}
                         for n, t, r in marks],
               "phases": phases,
               "boot_to_window_s": next((t for n, t, _r in marks
                                         if n == "cua so lo ra"), 0.0),
               "ram_at_window_kib": next((r for n, _t, r in marks
                                          if n == "cua so lo ra"), 0),
               "ram_idle_kib": marks[-1][2] if marks else 0,
               "recent_cards": cards,
               "recent_covers": covers,
               "evidence_shot": shot,
               "control": control}
    try:
        import psutil
        maps = {}
        for row in psutil.Process().memory_maps(grouped=True):
            name = os.path.basename(row.path or "")
            if name:
                maps[name] = round(row.rss / 1024)
        top = sorted(maps.items(), key=lambda kv: -kv[1])[:15]
        payload["top_rss_modules"] = [{"name": n, "rss_kib": r} for n, r in top]
    except Exception as exc:
        payload["top_rss_modules"] = {"error": repr(exc)}

    # Phan ket luan: moi dong la mot dieu ma ban TRUOC khi toi uu that bai, khong
    # phai mot con so thoi. Boot 2s ma tem RAM tra ve 0 thi do la do khong chay,
    # khong phai do app nhanh.
    checks = {
        "cua_so_lo": bool(exposed),
        "tem_ram_con_song": payload["ram_at_window_kib"] > 0,
        "dong_ho_phan_biet": (control["nang_s"] >= 0.05
                              and control["nhe_s"] <= 0.005),
        "boot_khong_cv2": not cv2_at_window,
        # Trang Home khong can dung phim: `from ui.main_window import
        # MainWindow` o dau ui/main_controller keo theo toan bo panel (ui.graphics
        # 33,8 ms, timeline_panel 38,4 ms, PySide6.QtMultimedia 36,0 ms,
        # QtNetwork 16,1 ms theo `-X importtime`), trong khi MainWindow chi duoc
        # dung MOT lan trong MainController._init_editor. psutil cung vay:
        # 102 ms cum trong luc mo app chi de do CPU/RAM sau khi cua so da ve.
        "boot_khong_keo_trang_dung": not editor_at_window,
        "boot_khong_psutil": not psutil_at_window,
        # `boot_khong_keo_trang_dung` XANH KHONG chung minh duoc dieu nay: do
        # 21/10/2026, nap tay `ui.compress_dialog` o dau mot module duong boot
        # thi `ui.main_window` van vang (hop thoai nen goi lazy trong
        # MainWindow._open_media_compress) nen ca hai dong cu van True, trong
        # khi boot them 0,428 s va RAM luc cua so them 1 MiB. Do la 40% cua
        # ngan sach 1,083 s ma ban 1.0.3 dang chay tren may nay.
        "boot_khong_keo_nen": not nen_at_window,
        # Pack SFX (14 tep mp3 + manifest, 181.167 B) chi duoc doc khi nguoi dung
        # mo hop thoai: `MainWindow._open_sfx` import trong than ham, va
        # `ui/sfx_dialog.py` keo theo QAudioOutput. Neup mot dong `import
        # ui.sfx_dialog` len dau module duong boot thi dong nay do thanh do.
        "boot_khong_keo_sfx": not sfx_at_window,
        # Nhu `boot_khong_keo_nen`: `MainWindow._open_canvas_layout` import trong
        # than ham nen tree nguon luon xanh; do la ly do `ClingingQt.spec` phai co
        # `ui.canvas_layout_dialog` trong hiddenimports cung luc.
        "boot_khong_keo_bocuc": not bocuc_at_window,
        "bia_duoc_ve": covers == cards,
        "anh_chung_minh": os.path.isfile(shot),
    }
    payload["checks"] = checks
    payload["ok"] = all(checks.values())
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
        except Exception:
            pass
    for _ in range(6):
        app.processEvents()
        time.sleep(0.02)
    return 0 if payload["ok"] else 1


def run_style_report(argv=None):
    """Aura + lớp phủ recap + karaoke trên BẢN ĐÃ CÁI: chuột thật, pixel thật.

    ``--selftest`` của exe đã cài đã đo ba đường vẽ (``aura_paint``,
    ``recap_overlay``, ``karaoke_paint``) ngay trong bundle, nhưng nó không hề
    bấm vào đâu cả. Ba thứ chỉ hỏng được khi có người dùng:
      * nhóm "Aura" trong panel hiệu ứng phải có ĐỦ 8 thẻ, và một cú nhấp vào
        thẻ phải đưa khoá aura vào clip — tên thẻ khớp EFFECT_PRESETS, lệch một
        chữ là thẻ thành ảnh minh hoạ vô dụng mà không ai báo;
      * vùng hình học của clip trên canvas phải là HẰNG SỐ theo hiệu ứng: bản đã
        cài chết đứng giữa app.processEvents() chỉ vì bấm bốn thẻ aura khác nhau
        (boundingRect nở theo clip.effects làm scene mất định vị index);
      * nút "Lớp phủ recap" trên header phải mở được hộp thoại, bật master phải
        làm khung hình đổi thật, và đóng hộp thoại phải để lại ĐÚNG một mục
        lịch sử (đóng mà mất lịch sử thì Ctrl+Z kế tiếp xoá mất một nửa việc
        của người dùng);
      * combo "Kiểu karaoke" phải có 9 dòng (none + 8 kiểu) và chọn "Lửa" là
        khung preview đổi màu thật — hỏng ở đây thì video xuất ra vẫn đúng,
        nên không ai biết cho tới khi đem hai bên ra so.

    Clinging.exe --style-report <duong-dan-json>
    """
    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_style")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"
    cache_state = _cache_guard_start("style_report")

    import numpy as np
    from PySide6.QtCore import QPointF, QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from core import karaoke_paint, project_storage
    from core.aura_paint import aura_spec
    from core.timeline_model import TrackType, track_type_for_media
    from ui.effects_panel import CATEGORY_TABS, EffectCard
    from ui.graphics_canvas_item import HANDLE_SIZE

    # Báo cáo này thêm clip, gắn hiệu ứng và bật lớp phủ — tuyệt đối không được
    # để _auto_save() ghi lên file autosave của người dùng.
    project_storage.AUTO_SAVE_FILE = os.path.join(
        os.path.dirname(os.path.abspath(shot)), "clinging_style_autosave.json")

    def pump(count=10):
        for _ in range(count):
            app.processEvents()

    FORMAT = QImage.Format.Format_ARGB32_Premultiplied

    def grab(canvas):
        return canvas.grab().toImage().convertToFormat(FORMAT)

    def arr(img):
        row = img.bytesPerLine() // 4
        return np.frombuffer(img.constBits(), np.uint8,
                             count=row * 4 * img.height()).reshape(
            img.height(), row, 4)[:, :img.width(), :3].astype(int)

    def moved_px(a, b, threshold=24):
        return int((np.abs(arr(a) - arr(b)).max(axis=2) > threshold).sum())

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(20)
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()

    model = win.timeline_panel.model
    stack = win.timeline_panel.undo_stack
    canvas = win.preview_panel.canvas

    # --- 1. nền: một clip video thật để aura và lớp phủ có chỗ hiện ra -------
    # Fixture này là cái các report khác đã dùng từ lâu (đọc được, giải mã
    # được, không đánh thức đường ống nhập thư viện). Ảnh PNG thì khác: thêm
    # clip ảnh làm app tự sinh proxy, và cú đó abort cả process giữa pump().
    src = _report_video(seconds=3.0, fps=25.0, size=(320, 180))
    track = model.add_track(track_type_for_media("video"), "Style")
    clip = model.add_clip(track.track_id, src, "video", 0.0, 3.0, "nen")
    if clip is None:
        raise RuntimeError("model tu choi them clip nen (track khong nhan video)")
    model.playhead = 1.0
    win._sync_canvas()
    pump(16)
    if canvas._clip_items.get(clip.clip_id) is None:
        raise RuntimeError("Canvas khong co item cho clip nen (%s)" % clip.clip_id)

    # --- 2. Aura: 8 thẻ THAT, mot cú bam phai di het duong dan ---------------
    if "Aura" not in CATEGORY_TABS:
        raise RuntimeError("panel hieu ung khong co nhom Aura")
    tab = CATEGORY_TABS.index("Aura")
    win.effects_panel.tabs.group.buttons()[tab].click()
    pump(6)
    cards = win.effects_panel.stack.widget(tab).widget().findChildren(EffectCard)
    names = [c.effect_data.get("name") for c in cards]
    if len(cards) != 8:
        raise RuntimeError("nhom Aura co %d the, mong 8" % len(cards))

    # --- 2b. geometry cua item PHAI static ----------------------------------
    # Day khong phai phep thu hinh thuc: boundingRect() cua clip video ma doi
    # theo clip.effects thi scene mat ding index cua no (vung do item cache luc
    # addToIndex, chi cap nhat qua prepareGeometryChange), va process abort
    # giua app.processEvents() khong traceback — ban cai dat chet o the aura
    # thu tu 4 trong mot phien. Fix: preview danh tru cho loang theo margin LON
    # NHAT registry, khong theo hieu ung dang gay. Do THUONG XUYEN de loi do
    # bao thanh RED co thong bao, khong phai mot process chet giua chung.
    aura_item = canvas._clip_items[clip.clip_id]
    empty_rect = aura_item.boundingRect()
    cards[0].add_button.click()
    pump(8)
    full_rect = aura_item.boundingRect()
    frame = aura_item.rect()
    short = min(frame.width(), frame.height())
    reserved = (full_rect.height() - frame.height()) / 2.0 - (HANDLE_SIZE + 4.0)
    hit_width = aura_item.shape().boundingRect().width()
    geometry_ok = (empty_rect == full_rect
                   and reserved >= 0.19 * short
                   and hit_width <= frame.width() + 2 * (HANDLE_SIZE + 4.0) + 0.5)
    if not geometry_ok:
        # Dừng ở đây là có lý: với rect đổi theo hiệu ứng, mọi cú click tiếp
        # theo đều có thể abort process trước khi báo cáo kịp ghi ra đĩa (đã
        # đo: bản cũ chết ngay trong vòng 8 thẻ). Ném rõ nguyên nhân còn hơn
        # để probe kết luận "không có báo cáo".
        why = ("rect_doi_theo_hieu_ung" if empty_rect != full_rect else
               "khong_giu_cho_loang" if reserved < 0.19 * short else
               "vung_loang_bat_chuot")
        raise RuntimeError(
            "aura_khong_doi_geometry RED (%s): khong=%s co=%s loang=%.1f "
            "hit=%.1f frame=%.1f" % (why, empty_rect, full_rect, reserved,
                                     hit_width, frame.width()))
    for effect in list(clip.effects):
        clip.effects.remove(effect)
    win._sync_canvas()
    pump(6)

    plain = grab(canvas)
    aura_shot = None
    applied = {}
    weakest = (10 ** 9, None)
    for card in cards:
        for effect in list(clip.effects):        # do tung the, khong do tong
            clip.effects.remove(effect)
        win._sync_canvas()
        pump(4)
        card.add_button.click()
        pump(8)
        spec = aura_spec(clip.effects)
        if spec is None:
            raise RuntimeError("the '%s' bam vao nhung clip khong co aura"
                               % card.effect_data.get("name"))
        after = grab(canvas)
        delta = moved_px(after, plain)
        applied[card.effect_data.get("name")] = [spec[0], delta]
        if card.effect_data.get("name") == "Lôi Điện":
            aura_shot = after
        if delta < weakest[0]:
            weakest = (delta, card.effect_data.get("name"))
    # 8 the phai ra 8 kieu khac nhau — gate o dong "aura_du_8_khoa" duoi payload
    # de ban ghi van chay het va file JSON ghi ra duoc, khong chet giua chung.
    aura_ok = weakest[0] >= 200
    for effect in list(clip.effects):
        clip.effects.remove(effect)
    win._sync_canvas()
    pump(6)

    # --- 3. Lop phu recap: nut header -> hop thoai -> khung doi -> 1 muc undo -
    opening = dict(model.recap_overlay)
    if opening.get("enabled"):
        raise RuntimeError("mo cua da bat san lop phu, khong do duoc bang chung")
    btn = win.timeline_panel.header.btn_recap
    if not btn.isVisible():
        raise RuntimeError("nut lop phu recap bi cat mat tren header")
    btn.click()
    pump(8)
    dialog = getattr(win, "_recap_dialog", None)
    if dialog is None or not dialog.isVisible():
        raise RuntimeError("bam nut header khong mo duoc hop thoai lop phu")
    if dialog is not win._open_recap_overlay():
        raise RuntimeError("hop thoai lop phu khoi dong hai lan, moi lan mot cai")
    dialog.chk_enabled.setChecked(True)
    dialog.chk_border.setChecked(True)
    dialog.chk_reticle.setChecked(True)
    dialog.chk_rec.setChecked(True)
    pump(12)
    overlay_shot = grab(canvas)

    # Lịch sử PHẢI đo trước khi tự bấm model: set_recap_overlay() trực tiếp
    # không đi qua command, gọi sớm thì "before" của lệnh đóng hộp thoại không
    # còn là trạng thái lúc mở cửa nữa.
    depth = len(stack._undo_stack)
    dialog._on_close()
    pump(8)
    grew = len(stack._undo_stack) - depth
    stack.undo()
    pump(8)
    restored = model.recap_overlay == opening
    stack.redo()
    pump(8)

    on_shot = overlay_shot
    model.set_recap_overlay({"enabled": False})
    pump(10)
    off_shot = grab(canvas)
    model.set_recap_overlay({"enabled": True})
    pump(8)
    overlay_px = moved_px(on_shot, off_shot)
    diff = (np.abs(arr(on_shot) - arr(off_shot)).max(axis=2) > 24)
    h, w = diff.shape
    centre_px = int(diff[h // 2 - 26:h // 2 + 26, w // 2 - 26:w // 2 + 26].sum())
    from core.canvas_utils import ASPECT_RATIOS
    sw, sh = ASPECT_RATIOS.get(canvas._current_ratio_key, (1920, 1080))
    # mapFromScene là phép chiếu scene -> pixel của viewport; transform() trả
    # toạ độ world và cho ra số âm.
    tl = canvas.mapFromScene(QPointF(-sw / 2, -sh / 2))
    br = canvas.mapFromScene(QPointF(sw / 2, sh / 2))
    top, left = int(tl.y()), int(tl.x())
    chip = diff[top:top + max(1, int((br.y() - tl.y()) * 0.12)),
                left:left + max(1, int((br.x() - tl.x()) * 0.25))]
    chip_px = int(chip.sum())
    overlay_ok = (overlay_px >= 400 and centre_px >= 20 and chip_px >= 20
                  and grew == 1 and restored)

    # --- 4. Karaoke: combo 9 dong, chon kieu la preview doi mau -------------
    win._add_text_to_timeline()
    pump(12)
    text_track = [t for t in model.tracks if t.track_type == TrackType.TEXT][0]
    tclip = text_track.clips[0]
    tclip.name = "Xin chao buoi sang"
    win.properties_panel.show_clip_properties(tclip)
    pump(8)
    editor = getattr(win.properties_panel, "current_editor", None)
    combo = getattr(editor, "combo_text_style", None)
    if combo is None:
        raise RuntimeError("properties panel khong co combo kieu karaoke")
    keys = [combo.itemData(i) for i in range(combo.count())]
    if keys[0] != "none" or tuple(keys[1:]) != karaoke_paint.STYLE_KEYS:
        raise RuntimeError("combo khong dung 8 khoa karaoke (duoc %s)" % (keys,))
    model.playhead = tclip.start_time + tclip.duration * 0.5
    win._sync_canvas()
    pump(10)

    def karaoke_shot(style):
        combo.setCurrentIndex(max(0, combo.findData(style)))
        pump(12)
        if tclip.text_style != style:
            raise RuntimeError("chon %s o combo nhung model la %s"
                               % (style, tclip.text_style))
        return grab(canvas)

    k_none = karaoke_shot("none")
    k_flame = karaoke_shot("flame")
    k_neon = karaoke_shot("neon")
    karaoke_px = {"flame": moved_px(k_flame, k_none), "neon": moved_px(k_neon, k_none)}
    karaoke_ok = all(v >= 120 for v in karaoke_px.values())

    # "Doi mau that" khong hom voi "doc duoc". Tu DANG HAT cua kieu lua la noi
    # duy nhat trong app nguoi dung mong mot net chu BIEN DAI thanh mot khoi
    # mau, va khoi do xanh qua moi gate so sanh anh. Do bang chinh font cua ban
    # nay, o ca khổ preview (12-16px) lan khổ xuất (40px).
    leg = _flame_legibility()
    leg_bad = _flame_legibility_problems(leg)

    # --- 5. bang chung do chinh file exe nay xuat ra -------------------------
    if aura_shot is None:
        raise RuntimeError("the 'Loi Dien' khong de lai anh nao tren bang chung")
    tiles = [("aura (the Loi Dien)", aura_shot), ("lop phu recap", overlay_shot),
             ("karaoke flame", k_flame), ("karaoke thuong", k_none)]
    tile_w = min(t.width() for _, t in tiles)
    tile_h = max(t.height() for _, t in tiles)
    sheet = QImage(tile_w * len(tiles) + 10 * (len(tiles) + 1),
                   tile_h + 34, FORMAT)
    sheet.fill(QColor("#09090b"))
    p = QPainter(sheet)
    for i, (label, tile) in enumerate(tiles):
        x = 10 + i * (tile_w + 10)
        p.drawImage(QRect(x, 26, tile.width(), tile.height()), tile)
        p.setPen(QColor("#e4e4e7"))
        p.drawText(x, 18, label)
    p.end()
    sheet.save(shot)
    if not os.path.isfile(shot) or os.path.getsize(shot) < 20000:
        raise RuntimeError("anh chung minh khong co noi dung (%d byte)"
                           % (os.path.getsize(shot) if os.path.isfile(shot) else 0))
    # Doc LAI file tren dia: "da save" khong dong nghia "file co noi dung".
    saved = QImage(shot).convertToFormat(FORMAT)
    if saved.isNull() or saved.width() < tile_w * 2:
        raise RuntimeError("anh chung minh doc lai bi loi (%s)" % shot)
    colors = len({tuple(row) for row in arr(saved).reshape(-1, 3).tolist()[::61]})

    cache_extra = _cache_guard_finish(cache_state)
    checks = {
        "aura_du_8_the": len(cards) == 8,
        "aura_bam_duoc": len(applied) == 8,
        # Moi the phai ghi DUNG aura cua chinh no: mot panel noi chuyen voi
        # model qua EFFECT_PRESETS, lech mot chu la 8 the chi ra mot kieu.
        "aura_du_8_khoa": len({v[0] for v in applied.values()}) == 8,
        "aura_doi_khung": aura_ok,
        "aura_khong_doi_geometry": geometry_ok,
        "lop_phu_doi_khung": overlay_px >= 400,
        "tam_ngam_va_REC": centre_px >= 20 and chip_px >= 20,
        "dong_1_muc_undo": grew == 1,
        "undo_tra_dung_trang_thai": restored,
        "combo_du_9_dong": len(keys) == 9,
        "karaoke_doi_khung": karaoke_ok,
        "flame_khong_khoi_dac": not leg_bad,
        "anh_chung_minh": os.path.getsize(shot) >= 20000,
        # Do bang danh sach duong dan, khong bang boolean: mot lan chay truoc khi
        # co redirect de lai 7 muc anh nho FIXTURE duoi cache cua nguoi dung, va
        # `DOI: 0` khong he noi duoc dieu do (them muc moi khong phai doi muc cu).
        "khong_ghi_cache_nguoi_dung": not cache_extra,
    }
    payload = {
        "exe": os.path.abspath(sys.argv[0]),
        "user_cache_extra": cache_extra,
        "frozen": bool(getattr(sys, "frozen", False)),
        "the_aura": names,
        "aura_applied": applied,
        "aura_lech_nhat_px": [weakest[0], weakest[1]],
        "boundingRect_px": [round(empty_rect.width(), 1),
                            round(full_rect.width(), 1),
                            round(empty_rect.height(), 1),
                            round(full_rect.height(), 1)],
        "aura_loang_px": round(reserved, 1),
        "vung_chuot_px": round(hit_width, 1),
        "khung_clip_px": [round(frame.width(), 1), round(frame.height(), 1)],
        "lop_phu_px": [overlay_px, centre_px, chip_px],
        "muc_undo_khi_dong": grew,
        "combo_khoa": keys,
        "karaoke_lech_px": karaoke_px,
        "flame_tu_dang_hat": {str(px): [m["muc"], m["fill"], m["lo"], m["spill"]]
                              for px, m in sorted(leg.items())},
        "flame_loi": leg_bad,
        "mau_trong_anh": colors,
        "screenshot": os.path.abspath(shot),
        "checks": checks,
        "ok": all(checks.values()),
    }
    win.close()
    pump(4)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0 if payload["ok"] else 1


def run_import_report(argv=None):
    """Nap MOI module cua app trong chinh bundle nay, bao cao file nao khong nap duoc.

    --selftest chi co the kiem tra nhung module ma co dong do goi ten. Mot
    module chi duoc dung khi nguoi dung mo mot hop thoai nao do la module ma
    khong co gi chung minh no con nguyen ven trong ban cai: thieu no thi loi
    chi no ra luc bam nut, sau khi installer bao 'thanh cong'. Sweep nay doc
    het core/, ui/, src/ va theme/bar_measure/diagnostics, nen mot lan chay
    tra loi cau hoi "ban nay co du thu vien moi truong chay khong" thay vi
    tung cau hoi rieng cho tung tinh nang.

    Phep phan biet: cung may moc do phai THAT BAI duoc. tkinter bi exclude khoi
    bundle, nen neu no van import duoc trong ban da dong goi thi "0 loi" chi la
    do sweep khong that su chay trong bundle.

    Clinging.exe --import-report <duong-dan-json>
    """
    import importlib
    import pkgutil

    argv = list(argv if argv is not None else sys.argv)
    report = _report_path(argv).replace("clinging_selftest", "clinging_imports")
    packages = ("core", "ui", "src")
    singles = ("theme", "bar_measure", "diagnostics")

    names = list(singles)
    for pkg in packages:
        names.append(pkg)
        try:
            module = importlib.import_module(pkg)
            paths = list(module.__path__)
        except Exception:
            continue
        try:
            for info in pkgutil.walk_packages(paths, pkg + "."):
                names.append(info.name)
        except Exception:
            pass

    loaded, failures = [], []
    for name in sorted(set(names)):
        try:
            importlib.import_module(name)
            loaded.append(name)
        except BaseException as exc:      # SystemExit co the thoat tu import
            failures.append({"module": name,
                             "error": "%s: %s" % (exc.__class__.__name__, exc)})

    try:
        importlib.import_module("tkinter")
        tkinter_present = True
    except BaseException:
        tkinter_present = False

    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "attempted": len(set(names)),
               "loaded": loaded, "failures": failures,
               "tkinter_present": tkinter_present}
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    if payload["frozen"] and tkinter_present:
        print("counterfactual fail: tkinter van import duoc trong bundle")
        return 1
    return 1 if failures else 0


LIBRARY_FIXTURE = {"video": 6, "image": 4, "tiny": 56, "img_wh": [1600, 1200],
                   "batch": 20}


def _library_report_fixture(media_dir):
    """Video va anh THAT tren dia, sinh bang cv2 — khong lay media cua nguoi dung.

    N = 66 media (6 video 640x360 + 4 anh 1600x1200 + 56 clip nho 320x240): du an
    that dang mo co 18 the (`cards_real` trong scratch/library_perf.json), 66 la
    diem cao nhat cua thang do P9 (18/30/66 the). Do o dung diem do vi nguong
    "ms/the" can so duoc voi con so cu: 17,43 ms/the luc chua toi uu
    (scratch/_lib_report_head.json, cung batch 65 the nay).
    """
    import cv2
    import numpy as np
    import shutil

    shutil.rmtree(media_dir, ignore_errors=True)
    os.makedirs(media_dir, exist_ok=True)
    records = []

    def add(path, kind):
        if not os.path.isfile(path) or os.path.getsize(path) < 1500:
            raise RuntimeError("fixture hong: %r" % path)
        records.append({"path": path, "type": kind,
                        "name": os.path.basename(path)})

    for i in range(LIBRARY_FIXTURE["video"]):
        path = os.path.join(media_dir, "lib_clip_%02d.mp4" % i)
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24,
                                 (640, 360))
        for frame in range(12):
            image = np.zeros((360, 640, 3), np.uint8)
            image[:, :] = ((i * 31 + frame * 5) % 256, (i * 53) % 256,
                           (frame * 17) % 256)
            cv2.rectangle(image, (60, 40), (580, 320),
                          (255, (i * 40) % 256, 90), -1)
            writer.write(image)
        writer.release()
        add(path, "video")
    for i in range(LIBRARY_FIXTURE["image"]):
        ext = "jpg" if i % 2 else "png"
        path = os.path.join(media_dir, "lib_photo_%02d.%s" % (i, ext))
        image = np.zeros((LIBRARY_FIXTURE["img_wh"][1],
                          LIBRARY_FIXTURE["img_wh"][0], 3), np.uint8)
        ramp = np.linspace(0, 255, LIBRARY_FIXTURE["img_wh"][0], dtype=np.uint8)
        image[:, :, 0] = ramp
        image[:, :, 1] = (255 - ramp)
        image[:, :, 2] = (i * 60) % 256
        cv2.imwrite(path, image)
        add(path, "image")
    for i in range(LIBRARY_FIXTURE["tiny"]):
        path = os.path.join(media_dir, "lib_tiny_%02d.mp4" % i)
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10,
                                 (320, 240))
        for frame in range(6):
            image = np.zeros((240, 320, 3), np.uint8)
            image[:, :] = ((i * 29) % 256, (frame * 31) % 256, 120)
            writer.write(image)
        writer.release()
        add(path, "video")
    return records


# Nguong do tren may nay (i7-2720QM, 12 GB, media tren HDD 5400 rpm), so cu lay
# tu scratch/library_perf.json lan do TRUOC khi toi uu.
LIBRARY_REPORT_CHECKS = (
    # Do luoi PHAI co the moi so duoc — neu khong thi moi cua sau xanh vi
    # dau vao rong, tuc la mot cong gia (hop dong buoc 2).
    ("luoi da nap du the",
     lambda p: p["cards_loaded"] == p["cards_requested"]),
    # O(n^2): 65 lan them the tung ke 65 lan xay lai luoi = 944,3 ms trong tong
    # 1132,8 ms block cua dot nap (scratch/_lib_report_head.json).
    ("luoi xay dung 1 lan moi luot",
     lambda p: p["filter_passes_restore"] == 1),
    ("an nhat moi the duoi 8 ms",
     lambda p: 0 < p["block_ms_per_card"] <= 8.0),
    # The bi bo loc an thi khong ai nhin khung hinh cua no (P7: 6/6 luot giai
    # ma chay cho 0 the hien).
    ("the bi an khong giai ma",
     lambda p: p["hidden_image_decodes"] == 0
     and p["hidden_image_delivered"] == 0),
    # Nhap nhiet cua dong tren: bo de quyien di thi dong "the bi an" cung xanh.
    # Doi nay buoc luot giai ma van phai den khi the duoc hien ra, va CA HAI
    # chieu phai khop: anh hien thi phai ve du, video an (luot 1) cung phai ve du.
    ("the hien van giao anh du",
     lambda p: p["images_delivered"] == p["images_expected"] > 0
     and p["videos_delivered_p1"] == p["videos_expected_p1"] > 0),
    ("anh nho anh tinh duoi 320 px",
     lambda p: 0 < p["image_thumb_width"] <= 320),
    ("anh nho anh tinh co cache dia",
     lambda p: p["image_key_after_first"] and p["image_second_cached"]),
    ("go tim kiem median duoi 8 ms",
     lambda p: 0 < p["keystroke_median_ms"] <= 8.0),
    # P10 cu: 20/20 luot giai ma van chay cho nhung the khong con ton tai.
    # So voi ban cu tren CUNG batch nay: 20 luot, ban toi uu 4 luot (hai task
    # dang chay trong 3 thread cua pool khong the huy duoc nua).
    ("the da xoa khong giai ma them",
     lambda p: p["tasks_requested"] == LIBRARY_FIXTURE["batch"]
     and p["decodes_for_cleared"] <= 8),
    ("khong loi emit qua bien C++", lambda p: p["emit_errors"] == 0),
    # Cong gia neu redirect khong ghi gi: "khong sang cache nguoi dung" luc do
    # chi la "khong ai ghi lan nao".
    ("fixture ghi THAT o redirect", lambda p: p["redirect_image_files"] > 0),
    ("khong ghi vao cache nguoi dung", lambda p: not p["user_cache_changed"]),
    ("anh thu vien ve co that",
     lambda p: os.path.isfile(p["screenshot"]) and p["distinct_colors"] > 40),
)


def library_report_fails(payload):
    """Ten tung dieu kien ma `--library-report` do khong dat (rong = dat het)."""
    return [name for name, ok in LIBRARY_REPORT_CHECKS if not ok(payload)]


def run_library_report(argv=None):
    """Thu vien tai nguyen tren may cau hinh thap — do bang duong THAT cua exe nay.

    Nguoi dung bao "lag". Lag nam o dau phai do bang con so, va con so do phai
    di qua dung nhung ham ma nguoi dung cham vao:

      `MainWindow.restore_library_from_project()`  (duong mo project)
      `LibraryPanel.restore_resources/add_resource/clear_resources`
      `LibraryPanel._apply_filter()`               (go tim kiem, doi tab)
      `ResourceCard.request_thumbnail/_apply_thumb`
      `_ThumbTask.run()` + `thumb_pool()`          (pool That, 3 thread)
      `decode_thumb_image()` -> `core.media_cache` (cache dia That)

    Bong dong ho chi BOC lay ham production roi goi nguyen ham do, khong thay
    duong nao. Toan bo anh nho ghi vao `cache_root()` redirect trong %TEMP%:
    probe mo MainWindow tung de lai 1 muc vao cache cua nguoi dung (do 22/10),
    nen cua "khong ghi vao cache nguoi dung" di kem cua "fixture ghi THAT o
    redirect" — bo mot trong hai thi cua kia xanh gia.

    Clinging.exe --library-report <duong-dan-json>
    """
    import shutil
    import tempfile

    argv = list(argv if argv is not None else sys.argv)
    report = _report_path(argv).replace("clinging_selftest", "clinging_library")
    shot = report[:-5] + ".png" if report.endswith(".json") else report + ".png"
    work = os.path.join(tempfile.gettempdir(), "clinging_library_report")
    media_dir = os.path.join(work, "media")
    cache_dir = os.path.join(work, "cache")

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(times=6, pause=0.0):
        end = time.perf_counter() + pause
        for _ in range(times):
            app.processEvents()
            time.sleep(0.03)
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)

    def listing(root):
        out = {}
        if not os.path.isdir(root):
            return out
        for folder, _dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(folder, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                out[os.path.relpath(path, root)] = (stat.st_size,
                                                    stat.st_mtime_ns)
        return out

    real_cache = os.path.join(str(os.environ.get("APPDATA", "")), "Clinging",
                              "cache")

    from core import media_cache
    from ui import library_panel as lp

    counters = {"filters": [], "decodes": [], "delivered": [], "emit_errors": 0}
    saved = []

    def install_hooks():
        """Boc ham production = goi nguyen ban cua no + ghi chep so do."""
        def hook(cls, name, wrapper_factory):
            original = getattr(cls, name)
            setattr(cls, name, wrapper_factory(original))
            saved.append((cls, name, original))

        def timed_filter(original):
            def wrapper(self):
                started = time.perf_counter()
                original(self)
                counters["filters"].append(time.perf_counter() - started)
            return wrapper

        def counted_thumb(original):
            def wrapper(self, image):
                original(self, image)
                counters["delivered"].append(
                    (self.kind, self.full_path, image.width(), image.height()))
            return wrapper

        def counted_decode(original):
            def wrapper(path, kind, max_width=320):
                image = original(path, kind, max_width)
                counters["decodes"].append((kind, path, image.width()))
                return image
            return wrapper

        def guarded_run(original):
            def wrapper(self):
                try:
                    original(self)
                except RuntimeError as exc:
                    # "Signal source has been deleted" nam o day chu khong phai
                    # trong log: ngoai bien callback C++ thi process chet khong
                    # bang nhau (0xC0000409 / rc=1), nen gate khong the dua rc.
                    counters["emit_errors"] += 1
                    counters.setdefault("emit_messages", []).append(str(exc))
            return wrapper

        hook(lp.LibraryPanel, "_apply_filter", timed_filter)
        hook(lp.ResourceCard, "_apply_thumb", counted_thumb)
        hook(lp, "decode_thumb_image", counted_decode)
        hook(lp._ThumbTask, "run", guarded_run)

    def uninstall_hooks():
        for cls, name, original in reversed(saved):
            setattr(cls, name, original)
        del saved[:]

    def wait_workers(want, timeout=45.0):
        """Cho den khi DU `want` luot giai ma da chay (khong phai du pixmap).

        Dem decode chu khong dem pixmap: `ResourceCard._load_thumbnail()` dat
        ICON vao bang `set_label_icon()`, ma icon cung la QPixmap, nen "the da
        co anh" khong chung minh duoc luot giai ma nao xong.
        """
        end = time.time() + timeout
        while time.time() < end and len(counters["decodes"]) < want:
            pump(4)
            time.sleep(0.02)
        pump(6, 0.15)

    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "python": sys.version.split()[0],
               "machine_cards": LIBRARY_FIXTURE["video"]
                               + LIBRARY_FIXTURE["image"]
                               + LIBRARY_FIXTURE["tiny"]}
    records = []
    win = None
    try:
        records = _library_report_fixture(media_dir)
        shutil.rmtree(cache_dir, ignore_errors=True)
        os.makedirs(cache_dir, exist_ok=True)

        from ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(12)
        # Snapshot cache nguoi dung SAU khi cua so da on dinh: ban than boot da
        # ghi bia cac project gan day, do la duong cua no khong phai do probe.
        user_before = listing(real_cache)

        original_root = media_cache.cache_root
        media_cache.cache_root = lambda: cache_dir
        try:
            panel = win.library_panel
            install_hooks()

            # ── 1. Mo "project" 66 the luc dang o tab Video ───────────
            big = [r for r in records if "lib_clip" in r["name"]]
            images = [r for r in records if r["type"] == "image"]
            tiny = [r for r in records if "lib_tiny" in r["name"]]
            # Mot tam anh de ngoai batch: doan 5 can mot lock cache LAN DAU
            # tien duoc doc, neu no nam trong batch thi cache da nong tu luot 1.
            probe_image = images[-1]
            images_batch = images[:-1]
            batch = big + images_batch + tiny
            counters["filters"].clear()
            counters["decodes"].clear()
            counters["delivered"].clear()
            panel._select_tab(1)                 # tab Video -> anh bi an
            pump(6)
            counters["filters"].clear()
            started = time.perf_counter()
            win.restore_library_from_project({"assets": batch})
            block = time.perf_counter() - started
            passes = len(counters["filters"])
            hidden_decodes = sum(1 for kind, _p, _w in counters["decodes"]
                                 if kind == "image")
            wait_workers(len(batch) - len(images_batch))
            delivered = {}
            for kind, path, _w, _h in counters["delivered"]:
                delivered.setdefault(kind, set()).add(os.path.normcase(path))
            payload["cards_requested"] = len(batch)
            payload["cards_loaded"] = len(
                [c for c in panel._items if isinstance(c, lp.ResourceCard)])
            payload["filter_passes_restore"] = passes
            payload["restore_block_ms"] = round(block * 1000.0, 1)
            payload["block_ms_per_card"] = round(
                block * 1000.0 / max(1, len(batch)), 2)
            payload["filter_ms_total"] = round(
                sum(counters["filters"]) * 1000.0, 1)
            payload["hidden_image_decodes"] = hidden_decodes
            payload["hidden_image_delivered"] = len(delivered.get("image", ()))
            payload["videos_delivered_p1"] = len(delivered.get("video", ()))
            payload["videos_expected_p1"] = len(big) + len(tiny)
            payload["hidden_visible_cards"] = sum(
                1 for c in panel._items if isinstance(c, lp.ResourceCard)
                and c.isVisibleTo(panel.grid_host))

            # ── 2. Mo tab Anh: the tung bi an PHAI bat dau giai ma ────
            # TABS = ["Tất cả", "Video", "Âm thanh", "Hình ảnh"], nen "Anh" la
            # index 3 CHU khong phai 2. Nham o nay thi dong "the hien van giao
            # anh" choi tro xanh vi khong co the nao duoc hien ra.
            counters["decodes"].clear()
            counters["delivered"].clear()
            started = time.perf_counter()
            panel._select_tab(3)
            switch_ms = round((time.perf_counter() - started) * 1000.0, 1)
            wait_workers(len(images_batch))
            delivered = {}
            for kind, path, _w, _h in counters["delivered"]:
                delivered.setdefault(kind, set()).add(os.path.normcase(path))
            payload["tab_switch_ms"] = switch_ms
            payload["images_delivered"] = len(delivered.get("image", ()))
            payload["images_expected"] = len(images_batch)
            payload["delivered_widths"] = sorted(
                {w for kind, _p, w, _h in counters["delivered"]
                 if kind == "image"})

            # ── 3. Gõ mot ky tu vao ô tìm kiếm, luoi dang day 66 the ───
            panel._select_tab(0)
            pump(8, 0.4)
            strokes = []
            for term in ("", "l", "li", "lib", "b_", "p", "x", ""):
                counters["filters"].clear()
                started = time.perf_counter()
                panel.search_box.input.setText(term)
                app.processEvents()
                strokes.append(time.perf_counter() - started)
            strokes.sort()
            payload["keystroke_median_ms"] = round(
                strokes[len(strokes) // 2] * 1000.0, 2)
            payload["keystroke_max_ms"] = round(strokes[-1] * 1000.0, 2)

            # ── 4. Xoa the khi task dang xep hang ──────────────────────
            panel.search_box.input.setText("")
            lp.thumb_pool().waitForDone(60000)
            pump(8, 0.2)
            counters["decodes"].clear()
            counters["delivered"].clear()
            counters["emit_errors"] = 0
            counters["emit_messages"] = []
            subset = tiny[:LIBRARY_FIXTURE["batch"]]
            win.restore_library_from_project({"assets": subset})
            started = time.perf_counter()
            panel.clear_resources()
            clear_ms = round((time.perf_counter() - started) * 1000.0, 1)
            running = len(counters["decodes"])
            lp.thumb_pool().waitForDone(60000)
            pump(8, 0.3)
            payload["tasks_requested"] = len(subset)
            # `decodes_for_cleared` = Tong so luot giai ma MA CA LO AI NEM XOA
            # bay ra (do sau khi pool chay xong). Do "so luot sau luc clear"
            # thi khong phan biet duoc: ban cu kip giai ma 17/20 the TRUOC luc
            # clear nen chi con 3 luot sau, gan bang 2 cua ban moi (so cu
            # 22/10: HEAD 20 luot, toi uu 4).
            payload["decodes_at_clear"] = running
            payload["decodes_after_clear"] = max(
                0, len(counters["decodes"]) - running)
            payload["decodes_for_cleared"] = len(counters["decodes"])
            payload["clear_block_ms"] = clear_ms
            payload["emit_errors"] = counters["emit_errors"]
            payload["emit_messages"] = list(counters["emit_messages"])[:3]

            # ── 5. Anh tinh: thu nho + cache dia, do tren file that ────
            image_path = probe_image["path"]
            key = media_cache.image_key(image_path, "img", 0.0, 320, 320)
            counters["decodes"].clear()
            started = time.perf_counter()
            first = lp.decode_thumb_image(image_path, "image")
            cold_ms = time.perf_counter() - started
            # Phai lay duoc DUNG khoa cua tam anh nay sau lan doc dau. Dem so
            # file trong thu muc `image/` thi khong phan biet duoc: 62 thumbnail
            # video cung nam o do, nen cua "co cache dia" xanh ma duong anh tinh
            # khong ghi lan nao.
            key_after_first = bool(key) and os.path.isfile(key)
            started = time.perf_counter()
            warm = lp.decode_thumb_image(image_path, "image")
            warm_ms = time.perf_counter() - started
            payload["image_thumb_width"] = first.width()
            payload["image_thumb_height"] = first.height()
            payload["image_thumb_mib"] = round(
                first.bytesPerLine() * first.height() / 1048576.0, 3)
            payload["image_source_width"] = QImage(image_path).width()
            payload["image_cache_files"] = len(listing(
                os.path.join(cache_dir, "image")))
            payload["image_first_ms"] = round(cold_ms * 1000.0, 1)
            payload["image_second_ms"] = round(warm_ms * 1000.0, 1)
            payload["image_key_after_first"] = key_after_first
            payload["image_second_cached"] = bool(
                not warm.isNull() and key_after_first
                and warm.width() == first.width())

            # ── 6. Anh chung minh: panel that, thumbnail that ─────────
            counters["delivered"].clear()
            panel._select_tab(0)
            win.restore_library_from_project(
                {"assets": big + images + tiny[:8]})
            wait_workers(18)
            pump(10, 0.6)
            panel.grab().save(shot)
            grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
            payload["screenshot"] = os.path.abspath(shot)
            payload["shot_size"] = [grabbed.width(), grabbed.height()]
            payload["distinct_colors"] = len({
                grabbed.pixel(x, y)
                for x in range(0, grabbed.width(), 3)
                for y in range(0, grabbed.height(), 3)})
        finally:
            uninstall_hooks()
            media_cache.cache_root = original_root

        payload["user_cache_changed"] = listing(real_cache) != user_before
        payload["user_cache_files"] = len(user_before)
        payload["redirect_image_files"] = len(listing(
            os.path.join(cache_dir, "image")))
        payload["thumb_pool_threads"] = lp.thumb_pool().maxThreadCount()
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        pump(6)
        for attempt in range(20):
            shutil.rmtree(work, ignore_errors=True)
            if not os.path.isdir(work):
                break
            time.sleep(0.2)
        payload["work_dir_left"] = os.path.isdir(work)

    fails = library_report_fails(payload) if "error" not in payload else []
    if "error" in payload:
        # Mot exception o giua probe khong duoc tro thanh "ALL PASS": thang do
        # thieu truong thi KeyError, va KeyError bat qua bien callback C++ cua
        # Qt co the abort 0xC0000409 — do la lop loi repo da ghi.
        payload["checks"] = [{"name": name, "ok": False}
                             for name, _f in LIBRARY_REPORT_CHECKS]
        payload["failed"] = ["probe chay khong xong"]
        payload["ok"] = False
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print("library-report DO: probe chay khong xong — %s" % payload["error"])
        return 1
    payload["checks"] = [{"name": name, "ok": name not in fails}
                         for name, _f in LIBRARY_REPORT_CHECKS]
    payload["failed"] = fails
    payload["ok"] = not fails
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("library-report: %s  (%d cua, %d do)"
          % ("ALL PASS" if not fails else "DO", len(LIBRARY_REPORT_CHECKS),
             len(fails)))
    for name in fails:
        print("  library-report DO: %s" % name)
    return 0 if not fails else 1


# ── Kho SFX: thang do va cong --sfx-report ────────────────────────────────
# Dat thang do o day, giong SPLIT_REPORT_CHECKS: mot cong do duoc tren source
# VAN chay duoc tren bundle va tren ban cai, con `--selftest` chi tra loi
# "module co trong PYZ". Nhung gi day la do tren SAN PHAM: tieng co that khong,
# ffprobe co doc lai duoc khong, chen co ra clip audio khong, va nut tren thanh
# thoi co mo duoc hop thoai khong.
SFX_PEAK_CEILING = 0.95           # khop PEAK_CEIL cua tools/make_sfx.py
SFX_ZCR_SPREAD = 0.30             # 14 tieng phai khong giong nhau: do 0,0144..0,7536

SFX_REPORT_CHECKS = (
    # Cong gia neu pack vang: moi cua duoi xanh vi dau vao rong.
    ("doc duoc manifest",
     lambda p: p["entry_count"] > 0 and not p["missing_files"]),
    ("pack du %d tieng" % SFX_PACK_ENTRIES,
     lambda p: p["entry_count"] == SFX_PACK_ENTRIES),
    ("byte tren dia khop manifest", lambda p: p["byte_mismatches"] == []),
    ("pack duoi ngan sach byte",
     lambda p: 0 < p["pack_bytes"] <= SFX_PACK_BYTE_BUDGET),
    ("tong thoi luong duoi ngan sach",
     lambda p: 0 < p["pack_seconds"] <= SFX_PACK_SECOND_BUDGET),
    ("manifest dung mot tran voi thang do",
     lambda p: p["manifest_peak_ceiling"] == SFX_PEAK_CEILING
     and p["manifest_target_rms"] == 0.18),
    # Do LAI tung tieng bang ffprobe + f32le, khong tin con so trong manifest.
    # Chan duoi dat tren CON SO DO (khong tren do lech): do lech = 0 la manifest
    # khop tuyen tuy, con probe tra ve 0 s la ffprobe khong doc duoc tieng nao —
    # va do la dau hieu dau vao rong, khong phai dau hieu pack tot.
    ("ffprobe do lai tung tieng",
     lambda p: p["probed_count"] == p["entry_count"]
     and p["min_probe_seconds"] > 0.05
     and p["duration_worst_dev"] <= SFX_DURATION_TOL),
    ("RMS do lai khop manifest",
     lambda p: p["rms_max"] > 0.05 and p["rms_worst_dev"] <= SFX_RMS_TOL),
    ("peak duoi tran chong hoa mai",
     lambda p: 0 < p["peak_max"] <= p["manifest_peak_ceiling"]),
    ("14 tieng 14 hash", lambda p: p["distinct_hashes"] == p["entry_count"]),
    ("tieng khong giong het nhau", lambda p: p["zcr_spread"] >= SFX_ZCR_SPREAD),
    # Duong cua nguoi dung: bam nut tren thanh thoi -> hop thoai -> chen.
    ("nut thanh mo duoc hop thoai",
     lambda p: p["button_visible"] and p["dialog_opened"]),
    ("hop thoai liet du pack", lambda p: p["dialog_rows"] == p["entry_count"]),
    ("loc nhom rut dung nhom",
     lambda p: p["group_rows"] == p["group_expected"]
     and 0 < p["group_rows"] < p["entry_count"]),
    ("tim kiem loc theo nhan",
     lambda p: p["search_rows"] == p["search_expected"]
     and 0 < p["search_rows"] < p["entry_count"]),
    ("nghe thu tha khoa file khi dung",
     lambda p: p["preview_source_was_loaded"] and p["preview_source_cleared"]),
    ("chen ra clip audio tren timeline",
     lambda p: p["clip_count"] == 2 and p["clip_kinds"] == ["audio", "audio"]
     and p["clip_durations_audible"]),
    ("hai tieng noi lien khong chong",
     lambda p: p["overlap"] is not None and abs(p["overlap"]) <= 1e-6),
    ("chen tao mot lane audio", lambda p: p["audio_tracks"] == 1),
    ("playhead chay toi cuoi clip",
     lambda p: p["playhead_after"] is not None
     and abs(p["playhead_after"] - p["second_end"]) <= 1e-6),
    ("Ctrl+Z tra ve timeline trong", lambda p: p["clips_after_undo"] == 0),
    ("khong ghi vao cache nguoi dung", lambda p: not p["user_cache_changed"]),
    ("anh hop thoai ve co that",
     lambda p: os.path.isfile(p["screenshot"]) and p["distinct_colors"] > 40),
)


def sfx_report_fails(payload):
    """Ten tung dieu kien ma `--sfx-report` do khong dat (rong = dat het)."""
    return [name for name, ok in SFX_REPORT_CHECKS if not ok(payload)]


def run_sfx_report(argv=None):
    """Kho hiêu ứng âm thanh — đo từ chính cửa sổ thật của bản exe này.

    Bốn thứ mà `--selftest` không nói được và ở đây phải tự đo lại:

      * tung tieng trong pack duoc ffprobe va ffmpeg do LAI (thoi luong, RMS,
        peak, ZCR, sha256) roi so voi manifest do `tools/make_sfx.py` tu viet —
        manifest la loai "tu cham diem" ma AGENTS.md da goi ten;
      * nut tren thanh thoi mo duoc hop thoai that, hop thoai liet ke du pack,
        loc nhom va tim kiem cat dung so dong;
      * chen qua ngan nap that cua timeline (`_on_resource_dropped` + undo
        stack): clip audio, mot lane, noi lien, playhead tien, Ctrl+Z sach;
      * probe mo MainWindow khong duoc de lai vet trong cache cua nguoi dung
        (bẫy da tra gia 22/10 lan do thu vien).

    Clinging.exe --sfx-report <duong-dan-json>
    """
    import time as _time

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_sfx")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(times=6):
        for _ in range(times):
            app.processEvents()
            _time.sleep(0.03)

    def listing(root):
        snapshot = {}
        if not os.path.isdir(root):
            return snapshot
        for folder, _dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(folder, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                snapshot[os.path.relpath(path, root)] = (stat.st_size,
                                                         stat.st_mtime_ns)
        return snapshot

    real_cache = os.path.join(str(os.environ.get("APPDATA", "")), "Clinging",
                              "cache")
    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "report": os.path.abspath(out), "pack_dir": "",
               "entry_count": 0, "missing_files": [], "byte_mismatches": [],
               "pack_bytes": 0, "pack_seconds": 0.0, "probed_count": 0,
               "manifest_peak_ceiling": 0.0, "manifest_target_rms": 0.0,
               "duration_worst_dev": 0.0, "rms_worst_dev": 0.0,
               "min_probe_seconds": 0.0, "rms_max": 0.0,
               "peak_max": 0.0, "distinct_hashes": 0, "zcr_spread": 0.0,
               "measures": [], "button_visible": False, "dialog_opened": False,
               "dialog_rows": 0, "group_name": "", "group_rows": 0,
               "group_expected": 0, "search_needle": "", "search_rows": 0,
               "search_expected": 0, "preview_source_was_loaded": False,
               "preview_source_cleared": False,
               "clip_count": 0, "clip_kinds": [], "clip_durations_audible": False,
               "overlap": None, "audio_tracks": 0, "playhead_after": None,
               "second_end": -1.0, "clips_after_undo": -1,
               "user_cache_changed": True, "user_cache_files": 0,
               "screenshot": os.path.abspath(shot), "distinct_colors": 0,
               "shot_size": [0, 0]}

    from core import sfx as sfx_core
    from ui.main_window import MainWindow

    win = None
    dialog = None
    user_before = {}
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(12)
        # Snapshot cache NGAY SAU khi cua so on dinh: ban than boot ghi bia cac
        # project gan day, do la duong cua no chu khong phai do probe.
        user_before = listing(real_cache)
        payload["user_cache_files"] = len(user_before)

        panel = win.timeline_panel
        rows = sfx_core.entries()
        payload["pack_dir"] = sfx_core.pack_dir()
        payload["entry_count"] = len(rows)
        payload["missing_files"] = sfx_core.missing_files()
        payload["byte_mismatches"] = [
            row["key"] for row in rows if os.path.isfile(row["path"])
            and os.path.getsize(row["path"]) != int(row["bytes"])]
        payload["pack_bytes"] = sum(int(row["bytes"]) for row in rows)
        payload["pack_seconds"] = round(sum(float(row["seconds"])
                                            for row in rows), 3)
        doc = {}
        manifest_path = os.path.join(sfx_core.pack_dir(), sfx_core.MANIFEST_NAME)
        if os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8") as handle:
                doc = json.load(handle)
        payload["manifest_peak_ceiling"] = float(doc.get("peak_ceiling") or 0.0)
        payload["manifest_target_rms"] = float(doc.get("target_rms") or 0.0)

        for row in rows:
            seconds, rms, peak, zcr, digest = _sfx_audio_row(row["path"])
            payload["measures"].append({
                "key": row["key"], "probe_seconds": round(seconds, 3),
                "want_seconds": float(row["seconds"]),
                "dev": round(abs(seconds - float(row["seconds"])), 3),
                "rms": round(rms, 4), "want_rms": float(row["rms"]),
                "rms_dev": round(abs(rms - float(row["rms"])), 4),
                "peak": round(peak, 4), "zcr": round(zcr, 4), "sha16": digest})
        measured = payload["measures"]
        payload["probed_count"] = len(measured)
        payload["duration_worst_dev"] = max([m["dev"] for m in measured] or [0.0])
        payload["min_probe_seconds"] = min([m["probe_seconds"]
                                            for m in measured] or [0.0])
        payload["rms_max"] = max([m["rms"] for m in measured] or [0.0])
        payload["rms_worst_dev"] = max([m["rms_dev"] for m in measured] or [0.0])
        payload["peak_max"] = max([m["peak"] for m in measured] or [0.0])
        payload["distinct_hashes"] = len({m["sha16"] for m in measured})
        zcrs = [m["zcr"] for m in measured]
        payload["zcr_spread"] = round(max(zcrs) - min(zcrs), 4) if zcrs else 0.0

        # ── Duong that: bam nut -> hop thoai -> chen ─────────────────
        payload["button_visible"] = panel.header.btn_sfx.isVisible()
        panel.header.btn_sfx.click()
        pump(8)
        dialog = getattr(win, "_sfx_dialog", None)
        payload["dialog_opened"] = dialog is not None and dialog.isVisible()
        if dialog is None:
            raise RuntimeError("bam nut SFX khong mo duoc hop thoai")
        payload["dialog_rows"] = dialog.list.count()

        groups = sfx_core.groups()
        payload["group_name"] = groups[0] if groups else ""
        payload["group_expected"] = len([r for r in rows
                                         if r.get("group") == payload["group_name"]])
        dialog.group_combo.setCurrentIndex(
            dialog.group_combo.findText(payload["group_name"]))
        payload["group_rows"] = dialog.list.count()
        dialog.group_combo.setCurrentIndex(0)

        needle = (rows[0].get("label") or "")[:3]
        payload["search_needle"] = needle
        payload["search_expected"] = len([
            r for r in rows if needle.casefold() in ("%s %s %s" % (
                r.get("label"), r.get("key"),
                r.get("group"))).casefold()])
        dialog.search.setText(needle)
        payload["search_rows"] = dialog.list.count()
        dialog.search.clear()
        pump(2)

        dialog.list.setCurrentRow(0)
        dialog.icon_play.click()
        pump(4)
        # `preview_source_cleared` mot minh no xanh du khi khong ai mo nguon:
        # phai ghi lai ca chieu "bam Nghe thu co moi duoc source" de vet
        # `setSource(QUrl())` trong stop_preview do duoc.
        payload["preview_source_was_loaded"] = not dialog._player.source().isEmpty()
        dialog.icon_play.click()          # dung = stop_preview + setSource(QUrl())
        pump(2)
        payload["preview_source_cleared"] = dialog._player.source().isEmpty()

        dialog.list.setCurrentRow(0)
        dialog.icon_insert.click()
        pump(4)
        dialog.list.setCurrentRow(1)
        dialog.icon_insert.click()
        pump(4)
        audio = [c for t in panel.model.tracks if t.track_type.name == "AUDIO"
                 for c in t.clips]
        payload["clip_count"] = len(audio)
        payload["clip_kinds"] = [c.media_type for c in audio]
        payload["clip_durations_audible"] = bool(
            audio and all(c.duration > 0.05 for c in audio))
        payload["audio_tracks"] = len(
            [t for t in panel.model.tracks if t.track_type.name == "AUDIO"])
        if len(audio) >= 2:
            payload["overlap"] = round(audio[1].start_time
                                       - (audio[0].start_time
                                          + audio[0].duration), 6)
            payload["second_end"] = audio[1].start_time + audio[1].duration
        payload["playhead_after"] = round(float(panel.model.playhead), 6)

        dialog.refresh()
        pump(4)
        dialog.grab().save(shot)
        grabbed = QImage(shot).convertToFormat(QImage.Format_RGB32)
        payload["shot_size"] = [grabbed.width(), grabbed.height()]
        payload["distinct_colors"] = len({
            grabbed.pixel(x, y) for x in range(0, grabbed.width(), 3)
            for y in range(0, grabbed.height(), 3)})

        panel.header.btn_undo.click()
        panel.header.btn_undo.click()
        pump(4)
        payload["clips_after_undo"] = len(
            [c for t in panel.model.tracks if t.track_type.name == "AUDIO"
             for c in t.clips])
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if dialog is not None:
            try:
                dialog.stop_preview()
                dialog.close()
            except Exception:
                pass
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        pump(8)

    payload["user_cache_changed"] = listing(real_cache) != user_before

    if "error" in payload:
        # Mot exception o giua probe khong duoc tro thanh "ALL PASS": thang do
        # thieu truong thi KeyError, va KeyError bat qua bien callback C++ cua
        # Qt co the abort 0xC0000409 — do la lop loi repo da ghi.
        payload["checks"] = [{"name": name, "ok": False}
                             for name, _f in SFX_REPORT_CHECKS]
        payload["failed"] = ["probe chay khong xong"]
        payload["ok"] = False
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print("sfx-report DO: probe chay khong xong — %s" % payload["error"])
        return 1
    fails = sfx_report_fails(payload)
    payload["checks"] = [{"name": name, "ok": name not in fails}
                         for name, _f in SFX_REPORT_CHECKS]
    payload["failed"] = fails
    payload["ok"] = not fails
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("sfx-report: %s  (%d cua, %d do)"
          % ("ALL PASS" if not fails else "DO", len(SFX_REPORT_CHECKS),
             len(fails)))
    for name in fails:
        print("  sfx-report DO: %s" % name)
    return 0 if not fails else 1


TRANSFORM_REPORT_CHECKS = (
    # Fixture phai lech mau that: mot tam nen trang thi moi phep lat deu "dung".
    ("fixture lech mau bon goc", lambda p: p["fixture_ok"]),
    ("lat ngang dao hai nua mau", lambda p: p["flip_h_swaps"]),
    ("lat doc dao tren duoi", lambda p: p["flip_v_swaps"]),
    ("lat khong doi tam noi dung",
     lambda p: p["flip_center_dx"] <= 3.0 and p["flip_center_dy"] <= 3.0),
    ("xoay 90 dao rong cao", lambda p: p["rot90_swaps_axes"]),
    ("xoay 45 mo rong va van trong khung",
     lambda p: p["rot45_grows"] and p["rot45_inside"]),
    ("xoay 180 bang hai lan lat", lambda p: p["rot180_equals_double_flip"]),
    ("canh trai cham mep trai", lambda p: p["align_left_x0"] <= 3.0),
    ("canh phai cham mep phai", lambda p: p["align_right_edge"] <= 3.0),
    ("canh tren cham mep tren", lambda p: p["align_top_y0"] <= 3.0),
    ("canh duoi cham mep duoi", lambda p: p["align_bottom_edge"] <= 3.0),
    ("canh giua ve tam canvas",
     lambda p: p["align_center_dx"] <= 3.0 and p["align_center_dy"] <= 3.0),
    ("nhap % mo rong dung 1,5 lan",
     lambda p: 1.4 <= p["pct_width_ratio"] <= 1.6),
    ("xem truoc cung mat voi xuat sau lat", lambda p: p["preview_matches_export"]),
    ("the Bien doi ve co that",
     lambda p: os.path.isfile(p["screenshot"]) and p["card_colors"] > 40
     and p["sheet_colors"] > 60),
    ("the Bien doi ve du chieu cao tren sheet",
     lambda p: p["card_bottom_painted"]),
    ("khong ghi vao cache nguoi dung", lambda p: not p["user_cache_changed"]),
)


def transform_report_fails(payload):
    """Ten tung dieu kien ma `--transform-report` do khong dat (rong = dat het)."""
    return [name for name, ok in TRANSFORM_REPORT_CHECKS if not ok(payload)]


def run_transform_report(argv=None):
    """Nhom "Bien doi" — do TREN ANH, khong do tren so.

    `--selftest` dong "bien doi" chi noi rang xich ma noi: co ba co, goc dung
    dai, 12 nut nam trong the, keo tay nam ra dung mot buoc undo. No KHONG noi
    rang pixel doi mau — ma pixel doi mau moi la dieu nguoi dung nhin thay. Lo
    dien hinh o day la mot ben dung co, ben kia im lang bo qua (preview lat,
    export khong lat; hoac canh theo so CHUA xoay).

    Clinging.exe --transform-report <duong-dan-json>

    Moi con so duoc do tu QImage ma chinh `FrameComposer.render_frame` ve ra
    (duong xuat), va mot doi lan tu QGraphicsScene cua preview. Fixture la anh
    BON GOC bon mau — mot tam nen dong nhat khong the phat hien phep lat.
    """
    import shutil
    import tempfile
    import types

    from PySide6.QtCore import QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication, QGraphicsScene, QPushButton, QWidget
    from core import project_storage as core_project_storage

    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest", "clinging_transform")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    import numpy as np

    OUT_W, OUT_H = 960, 540
    CANVAS_W, CANVAS_H = 1920, 1080
    SCALE = 0.5           # clip chiem 960x540 tren canvas, 480x270 tren anh do

    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "report": os.path.abspath(out), "screenshot": os.path.abspath(shot),
               "fixture_ok": False, "flip_h_swaps": False, "flip_v_swaps": False,
               "flip_center_dx": 999.0, "flip_center_dy": 999.0,
               "rot90_swaps_axes": False, "rot45_grows": False,
               "rot45_inside": False, "rot180_equals_double_flip": False,
               "align_left_x0": 999.0, "align_right_edge": 999.0,
               "align_top_y0": 999.0, "align_bottom_edge": 999.0,
               "align_center_dx": 999.0, "align_center_dy": 999.0,
               "pct_width_ratio": 0.0, "preview_matches_export": False,
               "card_colors": 0, "sheet_colors": 0, "box": [],
               "card_bottom_painted": False,
               "user_cache_changed": True}

    folder = os.path.join(tempfile.gettempdir(), "clinging_transform_report")

    def arr(img):
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4))[:, :, :3].astype(np.float64)

    def region_mean(a, x0, x1, y0, y1):
        return tuple(float(v) for v in a[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0))

    def content_bbox(a, thr=60.0):
        """Hop cua noi dung sang tren nen den (0,0,0) — do bang MASK, khong do
        bang so tay nguoi dung ghi vao model."""
        mask = (a.max(axis=2) > thr)
        cols = np.nonzero(mask.any(axis=0))[0]
        rows = np.nonzero(mask.any(axis=1))[0]
        if not len(cols) or not len(rows):
            return None
        return (int(cols[0]), int(cols[-1]), int(rows[0]), int(rows[-1]))

    def close(a, b, tol=18.0):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    from core import media_cache
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType
    real_cache_root = media_cache.cache_root
    real_recovery = core_project_storage.RECOVERY_DIR
    real_user_cache = os.path.join(str(os.environ.get("APPDATA", "")), "Clinging",
                                   "cache")

    def listing(root):
        snapshot = set()
        if not os.path.isdir(root):
            return snapshot
        for sub, _dirs, files in os.walk(root):
            for name in files:
                snapshot.add(os.path.relpath(os.path.join(sub, name), root))
        return snapshot

    model = None
    host = None
    composer = None
    try:
        media_cache.cache_root = lambda: os.path.join(folder, "cache")
        core_project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)

        # Fixture: bon goc bon mau, khong goc nao giong goc nao, khong co mau nao
        # gan den — nen lat/luon xoay deu in ra lech mau do duoc bang so.
        fixture = os.path.join(folder, "fixture.png")
        src = QImage(320, 180, QImage.Format.Format_RGB32)
        src.fill(QColor("#000000"))
        quad = QPainter(src)
        try:
            quad.fillRect(0, 0, 160, 90, QColor(230, 30, 40))      # trai tren
            quad.fillRect(160, 0, 160, 90, QColor(40, 200, 90))    # phai tren
            quad.fillRect(0, 90, 160, 90, QColor(40, 60, 220))     # trai duoi
            quad.fillRect(160, 90, 160, 90, QColor(235, 235, 235))  # phai duoi
        finally:
            quad.end()
        if not src.save(fixture, "PNG"):
            raise RuntimeError("khong ghi duoc fixture.png")

        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, fixture, "image", 0.0, 2.0,
                              name="Bien doi")
        if clip is None:
            raise RuntimeError("add_clip tra None")
        from core.canvas_utils import apply_auto_fit
        apply_auto_fit(clip, CANVAS_W, CANVAS_H)
        model.update_clip_properties(clip.clip_id, x=0.0, y=0.0, scale_x=SCALE,
                                     scale_y=SCALE, rotation=0.0, opacity=1.0,
                                     flip_h=False, flip_v=False, uniform_scale=True)
        composer = FrameComposer(model, OUT_W, OUT_H)

        a0 = arr(composer.render_frame(1.0))
        box0 = content_bbox(a0)
        if box0 is None:
            raise RuntimeError("khung hinh goc rong: khong co noi dung de do")
        x0, x1, y0, y1 = box0
        payload["box"] = list(box0)
        # Sample nam giua moi nua, cach le 12 px de net mo cua scale khong len
        # vao mau do duoc.
        mx = (x0 + x1) // 2
        my = (y0 + y1) // 2
        left_base = region_mean(a0, x0 + 12, mx - 12, y0 + 12, y1 - 12)
        right_base = region_mean(a0, mx + 12, x1 - 12, y0 + 12, y1 - 12)
        top_base = region_mean(a0, x0 + 12, x1 - 12, y0 + 12, my - 12)
        bottom_base = region_mean(a0, x0 + 12, x1 - 12, my + 12, y1 - 12)
        halves = (left_base, right_base, top_base, bottom_base)
        # Mot tam nen trang thi moi phep lat deu "dung" va cua do xanh vi khong
        # co gi de dao: phai do RANG bon mui trung binh doi mau nhau lon hon
        # 60/255 tren moi cap, va khong mui nao gan den (ma noi dung nam duoi
        # nguong content_bbox). Do 23/10/2026: cach so sanh `left_base[0] > 150`
        # do RED + BLUE o nua trai ra 135, gan bang nua phai (GREEN + TRANG,
        # 137) nen cua do mau theo mot truc tu duy nhat luong cuoc sai.
        payload["fixture_ok"] = (
            min(max(c) for c in halves) > 60
            and min(max(abs(p - q) for p, q in zip(a, b))
                    for i, a in enumerate(halves) for b in halves[i + 1:]) > 60.0)

        def render_state(**changes):
            model.update_clip_properties(clip.clip_id, **changes)
            image = composer.render_frame(1.0)
            return arr(image), image

        # ── LAT ───────────────────────────────────────────────────────────
        model.update_clip_properties(clip.clip_id, flip_h=True)
        flipped = composer.render_frame(1.0)
        af = arr(flipped)
        bf = content_bbox(af)
        lf = region_mean(af, bf[0] + 12, (bf[0] + bf[1]) // 2 - 12,
                         bf[2] + 12, bf[3] - 12)
        rf = region_mean(af, (bf[0] + bf[1]) // 2 + 12, bf[1] - 12,
                         bf[2] + 12, bf[3] - 12)
        payload["flip_h_swaps"] = (close(lf, right_base) and close(rf, left_base))
        payload["flip_center_dx"] = abs(((bf[0] + bf[1]) / 2.0) - ((x0 + x1) / 2.0))
        payload["flip_center_dy"] = abs(((bf[2] + bf[3]) / 2.0) - ((y0 + y1) / 2.0))
        frame_flip_h = flipped

        model.update_clip_properties(clip.clip_id, flip_h=False, flip_v=True)
        frame_flip_v = composer.render_frame(1.0)
        av = arr(frame_flip_v)
        bv = content_bbox(av)
        tf = region_mean(av, bv[0] + 12, bv[1] - 12, bv[2] + 12,
                         (bv[2] + bv[3]) // 2 - 12)
        df = region_mean(av, bv[0] + 12, bv[1] - 12,
                         (bv[2] + bv[3]) // 2 + 12, bv[3] - 12)
        payload["flip_v_swaps"] = (close(tf, bottom_base) and close(df, top_base))

        # Xoay 180 = lat ca hai chieu: hai duong bien doi khac nhau trong
        # FrameComposer (painter.rotate vs painter.scale(-1)) phai ra CUNG
        # mot khung hinh mau.
        model.update_clip_properties(clip.clip_id, flip_v=False, rotation=180.0)
        a180 = arr(composer.render_frame(1.0))
        model.update_clip_properties(clip.clip_id, rotation=0.0, flip_h=True,
                                     flip_v=True)
        adf = arr(composer.render_frame(1.0))
        payload["rot180_equals_double_flip"] = (
            a180.shape == adf.shape
            and float(np.abs(a180 - adf).max()) <= 24.0)
        model.update_clip_properties(clip.clip_id, flip_h=False, flip_v=False)

        # ── XOAY ──────────────────────────────────────────────────────────
        model.update_clip_properties(clip.clip_id, rotation=90.0)
        frame_rot90 = composer.render_frame(1.0)
        ar90 = arr(frame_rot90)
        b90 = content_bbox(ar90)
        w0, h0 = x1 - x0, y1 - y0
        payload["rot90_swaps_axes"] = (b90 is not None
            and abs((b90[1] - b90[0]) - h0) <= 6 and abs((b90[3] - b90[2]) - w0) <= 6)
        model.update_clip_properties(clip.clip_id, rotation=45.0)
        frame_rot45 = composer.render_frame(1.0)
        a45 = arr(frame_rot45)
        b45 = content_bbox(a45)
        payload["rot45_grows"] = (b45 is not None
                                  and (b45[1] - b45[0]) > w0 and (b45[3] - b45[2]) > h0)
        payload["rot45_inside"] = (b45 is not None and b45[0] >= 0
                                   and b45[1] <= OUT_W - 1 and b45[2] >= 0
                                   and b45[3] <= OUT_H - 1)
        model.update_clip_properties(clip.clip_id, rotation=0.0)

        # ── CANH MEP + % qua chinh bang thuoc tinh ────────────────────────
        from core.commands import UndoStack
        from ui.graphics_canvas_item import CanvasClipItem
        from ui.main_window import MainWindow
        from ui.properties_panel import ClipPropertiesWidget

        user_before = listing(real_user_cache)

        host = QWidget()
        host.setObjectName("MainWindow")
        stack = UndoStack()
        host.timeline_panel = types.SimpleNamespace(
            model=model, undo_stack=stack,
            header=types.SimpleNamespace(combo_aspect_ratio=types.SimpleNamespace(
                currentText=lambda: "16:9 - Ngang chuan")))
        host.preview_panel = types.SimpleNamespace(
            canvas=types.SimpleNamespace(_clip_items={}))

        editor = ClipPropertiesWidget(clip, parent=host)
        editor.propertyChanged.connect(
            lambda *a: MainWindow._on_properties_changed_by_user(host, *a))

        def buttons(text):
            found = [b for b in editor.card_transform.findChildren(QPushButton)
                     if b.text() == text]
            if not found:
                raise RuntimeError("the Bien doi khong co nut %s" % text)
            return found

        def click(text):
            """Bam MOI nut mang nhan do: "Giữa" xuat hien o ca hai hang (ngang
            va doc), bam cai dau thi truc kia van nam ở mép va cua do lech."""
            for btn in buttons(text):
                btn.click()
            return len(buttons(text))

        def edge_of(image, label):
            b = content_bbox(arr(image))
            if b is None:
                raise RuntimeError("khong do duoc hop noi dung sau %s" % label)
            return b

        click("Trái")
        payload["align_left_x0"] = float(edge_of(composer.render_frame(1.0), "canh Trai")[0])
        click("Phải")
        payload["align_right_edge"] = float(
            OUT_W - 1 - edge_of(composer.render_frame(1.0), "canh Phai")[1])
        click("Trên")
        payload["align_top_y0"] = float(edge_of(composer.render_frame(1.0), "canh Tren")[2])
        click("Dưới")
        payload["align_bottom_edge"] = float(
            OUT_H - 1 - edge_of(composer.render_frame(1.0), "canh Duoi")[3])
        click("Giữa")
        bmid = edge_of(composer.render_frame(1.0), "canh Giua")
        payload["align_center_dx"] = abs((bmid[0] + bmid[1]) / 2.0 - OUT_W / 2.0)
        payload["align_center_dy"] = abs((bmid[2] + bmid[3]) / 2.0 - OUT_H / 2.0)

        before_w = bmid[1] - bmid[0]
        editor.spin_scale_pct.setValue(75.0)
        if not (close((clip.transform.scale_x, clip.transform.scale_y),
                      (0.75, 0.75), tol=0.01)):
            raise RuntimeError("nhap 75%% ra %r (khoa ty le phai bang hai truc)"
                               % [clip.transform.scale_x, clip.transform.scale_y])
        b75 = edge_of(composer.render_frame(1.0), "nhap 75%")
        payload["pct_width_ratio"] = (b75[1] - b75[0]) / float(before_w or 1)

        # ── XEM TRUOC == XUAT: cùng clip lật, do bang QImage cua hai ben ───
        model.update_clip_properties(clip.clip_id, scale_x=SCALE, scale_y=SCALE,
                                     rotation=0.0, x=0.0, y=0.0, flip_h=True)
        export_flip = arr(composer.render_frame(1.0))
        scene_host = QGraphicsScene()
        scene_host.setSceneRect(QRectF(-CANVAS_W / 2.0, -CANVAS_H / 2.0,
                                       CANVAS_W, CANVAS_H))
        item = CanvasClipItem(clip, lambda c: None, lambda *a, **k: None)
        scene_host.addItem(item)
        apply_auto_fit(clip, CANVAS_W, CANVAS_H)
        item.sync_from_model()
        preview_img = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32_Premultiplied)
        preview_img.fill(QColor("#000000"))
        pp = QPainter(preview_img)
        try:
            scene_host.render(pp)
        finally:
            pp.end()
        ap_ = arr(preview_img)
        bp = content_bbox(ap_)
        pmx = (bp[0] + bp[1]) // 2
        bx = content_bbox(export_flip)
        left_preview = region_mean(ap_, bp[0] + 24, pmx - 24, bp[2] + 24, bp[3] - 24)
        right_preview = region_mean(ap_, pmx + 24, bp[1] - 24, bp[2] + 24, bp[3] - 24)
        left_export = region_mean(export_flip, bx[0] + 12, (bx[0] + bx[1]) // 2 - 12,
                                  bx[2] + 12, bx[3] - 12)
        right_export = region_mean(export_flip, (bx[0] + bx[1]) // 2 + 12, bx[1] - 12,
                                   bx[2] + 12, bx[3] - 12)
        payload["preview_matches_export"] = (
            close(left_preview, left_export, tol=30.0)
            and close(right_preview, right_export, tol=30.0)
            and left_preview != right_preview)
        # apply_auto_fit o tren da doi scale cua clip ve Fit (1,0 cho nguon 16:9
        # tren canvas 16:9): phai kien lai SCALE 0,5 truoc khi dung sheet de ca
        # nam o "goc/lat/xoay" cung mot kich thuoc, neu khong o "goc" lo khung
        # trong khi bon o kia chiem nua cell (do 23/10/2026 qua anh chung minh).
        model.update_clip_properties(clip.clip_id, flip_h=False, scale_x=SCALE,
                                     scale_y=SCALE, x=0.0, y=0.0)

        # ── ANH CHUNG MINH ────────────────────────────────────────────────
        cell_w, cell_h = 320, 180
        card_pm = editor.card_transform.grab()
        card_raw = card_pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        # grab() cua card trong suot 87% (do 23/10/2026: 169.444/195.453 pixel
        # co alpha < 255, min 0) — ve thang len sheet thi Qt tron voi nen, nen
        # moi phep so sanh "card ve du chieu cao" khong bao gio khop. Flattening
        # di qua dung buoc composite that, roi moi do va moi ve.
        card_img = QImage(card_raw.width(), card_raw.height(),
                          QImage.Format.Format_RGB32)
        card_img.fill(QColor("#101014"))
        fp = QPainter(card_img)
        try:
            fp.drawImage(0, 0, card_raw)
        finally:
            fp.end()
        card_colors = len(set(map(
            tuple, arr(card_img).reshape(-1, 3)[::37].astype(int).tolist())))
        payload["card_colors"] = card_colors

        frames = [("goc", composer.render_frame(1.0)), ("lat ngang", frame_flip_h),
                  ("lat doc", frame_flip_v), ("xoay 45", frame_rot45),
                  ("xoay 90", frame_rot90)]
        # The card is drawn at its REAL grabbed size: thu nho no bang `// 2`
        # lam mat 4 hang cuoi cua the Bien doi va probe van PASS vi no khong
        # do toa do cua sheet (lan do 23/10/2026 thay "Do mo (%)" cat nan).
        card_w, card_h = card_img.width(), card_img.height()
        sheet_w = cell_w * len(frames) + card_w + 40
        sheet_h = max(cell_h + 110, card_h + 56)
        sheet = QImage(sheet_w, sheet_h, QImage.Format.Format_RGB32)
        sheet.fill(QColor("#101014"))
        sp = QPainter(sheet)
        try:
            x = 10
            for label, image in frames:
                sp.drawImage(QRect(x, 40, cell_w, cell_h),
                             image.convertToFormat(QImage.Format.Format_RGBA8888))
                sp.setPen(QColor("#E0E0E0"))
                sp.drawText(QRect(x, 12, cell_w, 24), Qt.AlignLeft, label)
                x += cell_w
            sp.drawImage(QRect(x + 10, 40, card_w, card_h), card_img)
            sp.drawText(QRect(x + 10, 12, card_w, 24), Qt.AlignLeft,
                        "the Bien doi")
        finally:
            sp.end()
        if not sheet.save(shot, "PNG"):
            raise RuntimeError("khong luu duoc anh chung minh")
        payload["sheet_colors"] = len(set(map(
            tuple, arr(sheet).reshape(-1, 3)[::101].astype(int).tolist())))

        # Do BANG PIXEL rang the Bien doi ve du chieu cao trong sheet. Lan do
        # 23/10/2026: `card_img.height() // 2` cat nan 4 hang cuoi cua the
        # ("Do mo (%)") ma probe van PASS vi no khong do toa do sheet — day
        # chinh la lop loi "dong duoi fold" cua bang chung minh.
        ash = arr(sheet)
        acard = arr(card_img)
        strip_sheet = ash[40 + card_h - 16: 40 + card_h - 8, x + 10: x + 10 + card_w]
        strip_card = acard[card_h - 16: card_h - 8]
        payload["card_bottom_painted"] = (
            strip_sheet.shape == strip_card.shape
            and float(np.abs(strip_sheet - strip_card).max()) <= 12.0)

        payload["user_cache_changed"] = listing(real_user_cache) != user_before
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        media_cache.cache_root = real_cache_root
        core_project_storage.RECOVERY_DIR = real_recovery
        if host is not None:
            host.deleteLater()
        if composer is not None:
            try:
                composer.close()
            except Exception:
                pass
        shutil.rmtree(folder, ignore_errors=True)

    if "error" in payload:
        payload["checks"] = [{"name": name, "ok": False}
                             for name, _f in TRANSFORM_REPORT_CHECKS]
        payload["failed"] = ["probe chay khong xong"]
        payload["ok"] = False
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print("transform-report DO: probe chay khong xong — %s" % payload["error"])
        return 1
    fails = transform_report_fails(payload)
    payload["checks"] = [{"name": name, "ok": name not in fails}
                         for name, _f in TRANSFORM_REPORT_CHECKS]
    payload["failed"] = fails
    payload["ok"] = not fails
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("transform-report: %s  (%d cua, %d do)  anh: %s"
          % ("ALL PASS" if not fails else "DO", len(TRANSFORM_REPORT_CHECKS),
             len(fails), payload["screenshot"]))
    for name in fails:
        print("  transform-report DO: %s" % name)
    return 0 if not fails else 1


# ── --canvas-layout-report ────────────────────────────────────
# `--selftest` dong "bo cuc" do pixel trong PYZ; no khong the noi nam dieu ma
# nguoi dung dung tay cham vao: nut tren thanh thoi co mo duoc hop thoai cua
# BAN NAY khong, 22 dieu khien co that ghi duoc vao model khong (mot khoa gui
# thieu trong `_collect` thi widget van xam ma khong doi gi), dong nao nam
# duoi thanh cuon khong (bẫy SplitDialog 22/10), bo cuc cua hop thoai co in
# ra khung xuat va co keo theo canvas preview khong, "Dan clip vao o" co viet
# transform that khong. Report nay do ca nam thu, tren MainWindow that.
#
# Moi muc duoi day la MOT khoa cua LAYOUT_DEFAULTS, KHAC mac dinh va nam TRONG
# mien cua chinh widget do: gia tri ngoai mien (interval 1.0 khong co trong
# ROTATE_CHOICES) khien combo tu nhay ve muc 0 nen phep do xanh ma khong do gi.
CANVAS_LAYOUT_TEST_VALUES = {
    "enabled": True,
    "layout": "split-4",
    "background_mode": "color",
    "background_color": "#FF8800",
    "texture": "blueprint",
    "texture_scale": 1.5,
    "overlay_opacity": 0.40,
    "slot_gap": 0.10,
    "header_text": "CHU DAU",
    "footer_text": "CHU CUOI",
    "header_font": "serif",
    "footer_font": "display",
    "header_size": 64,
    "footer_size": 48,
    "header_bold": False,
    "footer_bold": True,
    "text_color": "#00FF00",
    "frame_color": "#00FFFF",
    "auto_fit": False,
    "play_sequentially": True,
    "slot_seconds": 3.0,
    "manga_rotate_interval": 5.0,
}

# Ten widget phai TOM khi master tat. `chk_enabled` co y khong nam trong danh
# sach: no la cai ma nguoi dung vua bam.
CANVAS_LAYOUT_CHILD_WIDGETS = (
    "combo_layout", "combo_mode", "combo_texture", "btn_bg_color",
    "btn_slot_color", "btn_text_color", "chk_auto_fit", "edit_header",
    "edit_footer", "combo_header_font", "combo_footer_font",
    "spin_header_size", "spin_footer_size", "chk_header_bold",
    "chk_footer_bold", "chk_sequential", "spin_slot_seconds", "combo_rotate",
    "btn_arrange",
)

# Bon trang thai do fold: tat / nen toan-den (mat het dieu khien con) / chat
# lieu + hai vung chu / luoi 6 o + che do chay. Day la bon hop hinh that ma
# `sizeHint()` khac nhau; mot dong bi an o mot trong bon thi nguoi dung khong
# bao gio nhin thay loi nhap cua chinh minh.
CANVAS_LAYOUT_STATES = (
    ("tat", {"enabled": False}),
    ("den + none", {"enabled": True, "background_mode": "black",
                    "layout": "none"}),
    ("chat lieu + chu", {"enabled": True, "background_mode": "texture",
                         "texture": "blueprint", "layout": "magazine-editorial",
                         "header_text": "Tuan 42", "footer_text": "Canva aura"}),
    ("luoi 6 o + tuan tu", {"enabled": True, "layout": "split-6",
                            "slot_gap": 0.2, "play_sequentially": True,
                            "manga_rotate_interval": 5.0, "auto_fit": False}),
)

CANVAS_LAYOUT_REPORT_CHECKS = (
    # Cong gia neu hop thoai rong: count = 0 khong duoc xanh o bat cu cua nao.
    ("combo bo cuc du 13 kieu",
     lambda p: p["layout_combo_count"] == 13
     and p["layout_combo_count"] == p["layout_module_count"]),
    ("combo chat lieu du 10 phong cach",
     lambda p: p["texture_combo_count"] == 10
     and p["texture_combo_count"] == p["texture_module_count"]),
    ("bang thu du 22 khoa",
     lambda p: p["test_values_complete"] and p["widget_key_count"] == 22),
    ("moi khoa co dieu khien ghi duoc model", lambda p: p["unwired"] == []),
    ("nut thanh mo duoc hop thoai",
     lambda p: p["button_visible"] and p["dialog_opened"]),
    ("bam lan 2 dung mot instance", lambda p: p["reused"]),
    ("dem du dieu khien de do fold", lambda p: p["control_count"] >= 24),
    ("khong dieu khien nao bi fold",
     lambda p: p["folded"] == [] and p["fold_states"] == 4),
    ("hop thoai vua man hinh",
     lambda p: 0 < p["max_dialog_h"] <= p["screen_h"]),
    ("master tat an het dieu khien", lambda p: p["disabled_leak"] == []),
    ("mo hop thoai duoi 0,6 s", lambda p: 0 < p["open_s"] < 0.6),
    ("do duoc private RAM cua chinh process", lambda p: p["ram_kib"] > 0),
    ("hop thoai chiem duoi 8 MiB private", lambda p: p["ram_delta_kib"] < 8192),
    ("keo slider model doi ngay", lambda p: p["slider_live"]),
    ("canvas preview ve lai theo bo cuc",
     lambda p: p["preview_px_changed"] >= 20000),
    ("dong hop thoai dung MOT muc undo", lambda p: p["undo_rows"] == 1),
    ("Ctrl+Z tra bo cuc cu", lambda p: p["undo_restores"]),
    ("mo lai widget doc dung model", lambda p: p["refresh_widget_ok"]),
    ("dan clip ra transform dung tam o",
     lambda p: p["center_bad"] == [] and p["arranged"] == p["boxes"]
     and p["boxes"] > 0),
    ("clip thua khong bi lat vao o", lambda p: p["leftover_moved"] == []),
    ("dan clip la MOT lenh undo", lambda p: p["arrange_rows"] == 1),
    ("Ctrl+Z tra nguyen vi tri cu", lambda p: p["arrange_reverted"]),
    ("nut dan bao ro du o hay lap o cuoi", lambda p: p["hint_ok"]),
    ("khong co clip thi nut dan tu choi", lambda p: p["empty_refused"]),
    ("bo cuc hop thoai in ra khung xuat",
     lambda p: p["bg_px"] >= 0.9 * p["frame_px"]),
    ("gach ngan split-4 hien ra trong xuat", lambda p: p["divider_px"] >= 3000),
    ("10 chat lieu la 10 buoc ve khac nhau",
     lambda p: p["texture_solids"] == [] and p["texture_steps"] >= 5),
    ("chu dau ve trong vung cua no",
     lambda p: p["header_px"] >= 400 and p["header_inside"]),
    ("nen den khong lam doi khung", lambda p: p["black_same"]),
    ("slot_gap thu o dung len", lambda p: p["gap_shrinks"]),
    ("phat tuan tu quay dung vong o",
     lambda p: p["seq_steps"] == [0, 0, 1, 2, 0, 0] and p["seq_off_ok"]),
    ("trao o nhay theo interval", lambda p: p["rotate_ok"] and p["rotate_off_ok"]),
    ("bo cuc tron ven qua file .clinq",
     lambda p: p["round_trip_ok"] and p["round_trip_keys"] == 22),
    ("file cu khong key tro ve mac dinh",
     lambda p: p["legacy_ok"] and p["legacy_keys"] == 22),
    ("khong ghi vao cache nguoi dung", lambda p: not p["user_cache_extra"]),
    ("anh hop thoai ve co that",
     lambda p: p["shot_readable"] and p["shot_colors"] > 40
     and p["shot_bytes"] > 20000),
)


def canvas_layout_report_fails(payload):
    """Ten tung dieu kien ma `--canvas-layout-report` do khong dat (rong = dat het)."""
    return [name for name, ok in CANVAS_LAYOUT_REPORT_CHECKS if not ok(payload)]


def run_canvas_layout_report(argv=None):
    """Bố cục & Phong cách — đo từ chính cửa sổ thật của bản exe này.

    Nam mata xich o day chi lon len khi chay tren dung ban nguoi dung nhan,
    khong phai tren tree nguon:

      * nut "Bo cuc & Phong cach" tren header thanh thoi mo duoc hop thoai, va
        bam lan hai van dung MOT instance (khong mo chong);
      * du 22 khoa cua `LAYOUT_DEFAULTS` co widget va widget that ghi duoc model
        -- gui tung widget qua tin hieu `_apply`, tuc dung duong nguoi dung keo;
      * khong dieu khien nao nam ngoai viewport cua `QScrollArea` o ca BON
        trang thai, va chieu cao cua khong vuot vung lam viec cua man hinh
        (chinh xac la loi da an nut Dong cua SplitDialog 22/10);
      * bo cuc ma hop thoai ghi vao model in ra KHUNG XUAT that (do bang pixel
        qua `FrameComposer`) va keo theo canvas preview ve lai;
      * "Dan clip vao o" viet transform that, dung tam o, MỘT lenh undo, Ctrl+Z
        sach, va clip thua thi khong bi dong;
      * dong hop thoai chi day DUNG MOT muc undo, mo lai doc dung gia tri model.

    Clinging.exe --canvas-layout-report <duong-dan-json>
    """
    import gc
    import shutil
    import tempfile
    import time as _time

    import numpy as np
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QSlider,
        QSpinBox, QWidget,
    )
    from core import canvas_layout, project_storage
    from core.canvas_utils import ASPECT_RATIOS, base_display_size
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType

    argv = list(argv if argv is not None else sys.argv)
    out = _report_path(argv).replace("clinging_selftest",
                                     "clinging_canvas_layout")
    shot = out[:-5] + ".png" if out.endswith(".json") else out + ".png"

    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    def pump(times=6):
        for _ in range(times):
            app.processEvents()
            _time.sleep(0.03)

    W, H = 1920, 1080
    CONTROLS = (QComboBox, QLineEdit, QSpinBox, QSlider, QCheckBox, QPushButton)
    folder = os.path.join(tempfile.gettempdir(), "clinging_canvas_layout_report")
    stills = [os.path.join(folder, "slot%d.png" % i) for i in range(3)]

    payload = {"exe": os.path.abspath(sys.argv[0]),
               "frozen": bool(getattr(sys, "frozen", False)),
               "report": os.path.abspath(out), "screenshot": os.path.abspath(shot),
               "layout_combo_count": 0, "layout_module_count": 0,
               "texture_combo_count": 0, "texture_module_count": 0,
               "test_values_complete": False, "widget_key_count": 0,
               "unwired": [], "control_count": 0, "folded": [], "fold_states": 0,
               "max_dialog_h": 0, "screen_h": 0, "disabled_leak": [],
               "button_visible": False, "dialog_opened": False, "reused": False,
               "dialog_type": "", "open_s": 0.0, "ram_kib": 0,
               "ram_delta_kib": 0, "slider_live": False,
               "preview_px_changed": 0, "undo_rows": 0, "undo_restores": False,
               "refresh_widget_ok": False, "arranged": 0, "boxes": 0,
               "center_bad": [], "leftover_moved": [], "arrange_rows": 0,
               "arrange_reverted": False, "hint_ok": False,
               "empty_refused": False, "frame_px": W * H, "bg_px": 0,
               "divider_px": 0, "texture_solids": [], "texture_steps": 0,
               "header_px": 0, "header_inside": False, "black_same": False,
               "gap_shrinks": False, "seq_steps": [], "seq_off_ok": False,
               "rotate_ok": False, "rotate_off_ok": False,
               "round_trip_ok": False, "round_trip_keys": 0, "legacy_ok": False,
               "legacy_keys": 0, "user_cache_extra": [], "shot_readable": False,
               "shot_colors": 0, "shot_bytes": 0, "values_seen": {}}

    def rgb_of(image):
        """QImage/QPixmap -> (H, W, 3) int16, DA composite qua nen den truoc khi do.

        `grab()` cua widget bo tron stylesheet tra anh co alpha < 255 o DPR>1
        (vet da ghi trong AGENTS.md): hai lan grab deu trong suot thi hieu
        lech = 0 va cua do "canvas ve lai" do sai.

        `grab()` tra VE QPIXMAP khong QImage, ma `QPainter.drawImage(int, int, ...)`
        chi nhan QImage -- lan chay 23/10 abort 0xC0000409 o chinh do, va stdout
        cua probe mat het nen khong con dong DO nao.
        """
        if not isinstance(image, QImage):
            image = image.toImage()
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor("#000000"))
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        flat = flat.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        buf = flat.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        row = flat.bytesPerLine() // 4
        px = np.frombuffer(raw, np.uint8).reshape(
            (flat.height(), row, 4))[:, :flat.width(), :3]
        # ARGB32 nam trong bo nho theo thu tu B,G,R,A.
        return px[:, :, ::-1].astype(np.int16)

    def count_color(px, hexcolor, tol=60):
        c = QColor(hexcolor)
        d = np.abs(px - np.array([c.red(), c.green(), c.blue()], np.int16))
        return int((d.max(axis=2) <= tol).sum())

    def transform_of(clip):
        """Biet danh transform cua clip -- do lech cua "Dan clip vao o" bang so."""
        t = clip.transform
        return (round(t.x, 3), round(t.y, 3), round(t.scale_x, 5),
                round(t.scale_y, 5))

    def _close_to(got, want):
        if isinstance(want, bool) or isinstance(got, bool):
            return bool(got) == bool(want)
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            return abs(float(got) - float(want)) <= 0.011
        return got == want

    win = None
    dialog = None
    composer = None
    cache_state = None
    real_autosave = None
    real_recovery = None
    try:
        # Redirect cache ANH qua `_cache_guard_start`: probe mo MainWindow that
        # keo theo `ClipTimelineItem._load_thumbnail` cho ba anh fixture, va mot
        # lan chay truoc khi co redirect de lai 6 muc duoi cache cua nguoi dung
        # trong khi `DOI: 0` khong he bao (do 23/10, phia style-report).
        cache_state = _cache_guard_start("canvas_layout_report")
        real_autosave = project_storage.AUTO_SAVE_FILE
        real_recovery = project_storage.RECOVERY_DIR
        project_storage.AUTO_SAVE_FILE = os.path.join(folder, "autosave.json")
        project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)

        for index, path in enumerate(stills):
            tile = QImage(640, 360, QImage.Format.Format_RGB32)
            tile.fill(QColor(60 + 60 * index, 120, 200))
            mark = QPainter(tile)
            mark.setPen(QColor(255, 255, 255))
            mark.drawRect(40, 30, 560, 300)
            mark.end()
            if not tile.save(path, "PNG"):
                raise RuntimeError("khong ghi duoc fixture %s" % path)

        payload["test_values_complete"] = (
            sorted(CANVAS_LAYOUT_TEST_VALUES) == sorted(canvas_layout.LAYOUT_DEFAULTS))

        from ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        timer = getattr(win, "_autosave_timer", None)
        if timer is not None:
            timer.stop()
        pump(12)

        panel = win.timeline_panel
        header = panel.header
        stack = panel.undo_stack
        from ui.canvas_layout_dialog import ROTATE_CHOICES

        def rows_by_key():
            return {row.key: row for row in dialog._rows()}

        def touch(key, value):
            """Ghi mot khoa QUA WIDGET that de tin hieu `_apply` chay nhu nguoi dung."""
            rows = rows_by_key()
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
            elif key == "manga_rotate_interval":
                dialog.combo_rotate.setCurrentIndex(
                    list(ROTATE_CHOICES).index(value))
            elif key in ("header_text", "footer_text"):
                edit = (dialog.edit_header if key == "header_text"
                        else dialog.edit_footer)
                edit.setText(value)
            elif key in ("header_size", "footer_size"):
                spin = (dialog.spin_header_size if key == "header_size"
                        else dialog.spin_footer_size)
                spin.setValue(int(value))
            elif key in ("auto_fit", "play_sequentially", "header_bold",
                         "footer_bold"):
                widget = {"auto_fit": dialog.chk_auto_fit,
                          "play_sequentially": dialog.chk_sequential,
                          "header_bold": dialog.chk_header_bold,
                          "footer_bold": dialog.chk_footer_bold}[key]
                widget.setChecked(bool(value))
            elif key == "slot_seconds":
                dialog.spin_slot_seconds.setValue(int(value))
            elif key in rows:
                rows[key].slider.setValue(int(round(float(value) * 100)))
            elif key in ("background_color", "text_color", "frame_color"):
                # Duong cua nut chon mau: son lai button (tooltip la cho duy
                # nhat luu mau) roi Goi `_apply` -- khong them bom truc thai.
                dialog._paint_color_buttons(
                    dict(dialog._model.project_layout, **{key: value}))
                dialog._apply()
            else:
                raise RuntimeError("khong co dieu khien cho khoa %s" % key)
            pump(2)

        def load_state(**patch):
            """Nap ca bo 22 khoa qua `_load_from` cua hop thoai (do BOC DE).

            Khong phai `touch`: 4 trang thai x 22 khoa gui tung widget thieu
            gi ~5 s rieng cho vong do; duong widget -> model da do o cua
            "moi khoa co dieu khien ghi duoc model".
            """
            settings = canvas_layout.normalize(
                dict(canvas_layout.LAYOUT_DEFAULTS, **patch))
            dialog._loading = True
            dialog._model.set_project_layout(settings, emit=False)
            dialog._load_from(settings)
            dialog._loading = False
            pump(3)

        # ── A. diem vao ──────────────────────────────────────────
        payload["button_visible"] = header.btn_layout.isVisible()
        first = getattr(win, "_canvas_layout_dialog", None)
        header.btn_layout.click()
        pump(6)
        dialog = getattr(win, "_canvas_layout_dialog", None)
        payload["dialog_opened"] = dialog is not None and dialog.isVisible()
        if dialog is None:
            raise RuntimeError("bam nut Bo cuc khong mo duoc hop thoai")
        payload["dialog_type"] = type(dialog).__name__
        payload["reused"] = first is None
        header.btn_layout.click()
        pump(4)
        payload["reused"] = (payload["reused"]
                             and getattr(win, "_canvas_layout_dialog", None) is dialog)

        # ── B. bang dieu khien ───────────────────────────────────
        payload["layout_combo_count"] = dialog.combo_layout.count()
        payload["layout_module_count"] = len(canvas_layout.LAYOUT_ORDER)
        payload["texture_combo_count"] = dialog.combo_texture.count()
        payload["texture_module_count"] = len(canvas_layout.TEXTURE_ORDER)

        # ── C. 22 khoa: widget -> model, tung cai mot ────────────
        touch("enabled", True)
        unwired = []
        for key in sorted(canvas_layout.LAYOUT_DEFAULTS):
            if key == "enabled":
                continue
            want = CANVAS_LAYOUT_TEST_VALUES[key]
            touch(key, want)
            got = dialog._model.project_layout[key]
            if not _close_to(got, want):
                unwired.append("%s: widget muon %r model con %r" % (key, want, got))
            payload["values_seen"][key] = [CANVAS_LAYOUT_TEST_VALUES[key], got]
        payload["unwired"] = unwired
        payload["widget_key_count"] = len(dialog._collect())

        # ── D. fold + chieu cao cua o ca BON trang thai ──────────
        screen = QApplication.primaryScreen().availableGeometry()
        payload["screen_h"] = int(screen.height())
        folded, counted = [], 0
        for name, patch in CANVAS_LAYOUT_STATES:
            load_state(**patch)
            bar = dialog._scroll.verticalScrollBar()
            if bar.maximum() != 0:
                folded.append("%s:scroll=%d" % (name, bar.maximum()))
            viewport = dialog._scroll.viewport()
            top_left = viewport.mapToGlobal(viewport.rect().topLeft())
            bottom_right = viewport.mapToGlobal(viewport.rect().bottomRight())
            for widget in dialog._body.findChildren(QWidget):
                if not isinstance(widget, CONTROLS) or not widget.isVisible():
                    continue
                counted += 1
                origin = widget.mapToGlobal(widget.rect().topLeft())
                end = widget.mapToGlobal(widget.rect().bottomRight())
                if not (top_left.x() <= origin.x() and top_left.y() <= origin.y()
                        and end.x() <= bottom_right.x()
                        and end.y() <= bottom_right.y()):
                    folded.append("%s:%s" % (name, widget.objectName()
                                             or type(widget).__name__))
            if dialog.height() > payload["max_dialog_h"]:
                payload["max_dialog_h"] = int(dialog.height())
        payload["folded"] = sorted(set(folded))
        payload["fold_states"] = len(CANVAS_LAYOUT_STATES)
        payload["control_count"] = counted

        # ── E. master tat tom het dieu khien ─────────────────────
        load_state(**{"enabled": False})
        leak = []
        for attr in CANVAS_LAYOUT_CHILD_WIDGETS:
            widget = getattr(dialog, attr, None)
            if widget is None:
                leak.append("thieu:" + attr)
            elif widget.isEnabled():
                leak.append(attr)
        for row in dialog._rows():
            if row.isEnabled():
                leak.append("slider:" + row.key)
        payload["disabled_leak"] = leak

        # ── F. chi phi mo lai (do TRUOC vong pixel de RAM sach numpy) ──
        def _private_kib():
            try:
                import psutil
                return int(psutil.Process().memory_info().private / 1024)
            except Exception:
                return 0

        dialog.close()
        pump(4)
        del win._canvas_layout_dialog
        gc.collect()
        pump(4)
        ram_before = _private_kib()
        started = _time.perf_counter()
        dialog = win._open_canvas_layout()
        pump(6)
        payload["open_s"] = round(_time.perf_counter() - started, 3)
        ram_after = _private_kib()
        payload["ram_kib"] = ram_after
        payload["ram_delta_kib"] = (ram_after - ram_before
                                    if ram_before and ram_after else 0)

        # ── G. keo slider = model doi = canvas ve lai; dong = 1 undo ──
        load_state(enabled=True, layout="split", background_mode="color",
                   background_color="#3673FE", overlay_opacity=0.0,
                   slot_gap=0.0)
        # `refresh()` la duong ma hop thoai tu dung khi mo lai: no chap
        # `_opening` = model luc ay, nen lenh undo do `Dong` day LA snapshot that,
        # khong phai snapshot ma probe tu gian vao.
        dialog.refresh()
        pump(3)
        opening = dict(dialog._model.project_layout)
        grab_before = rgb_of(win.preview_panel.canvas.viewport().grab())
        slider = rows_by_key()["overlay_opacity"].slider
        slider.setValue(40)
        pump(3)
        payload["slider_live"] = _close_to(
            dialog._model.project_layout["overlay_opacity"], 0.40)
        grab_after = rgb_of(win.preview_panel.canvas.viewport().grab())
        payload["preview_px_changed"] = int(
            (np.abs(grab_after - grab_before).max(axis=2) > 24).sum())
        del grab_before, grab_after
        base_rows = stack.undo_count
        close_button = None
        for widget in dialog.findChildren(QPushButton):
            if widget.text() == "Đóng":
                close_button = widget
                break
        if close_button is None:
            raise RuntimeError("hop thoai khong co nut Dong")
        slider.setValue(60)
        pump(3)
        close_button.click()
        pump(3)
        payload["undo_rows"] = stack.undo_count - base_rows
        stack.undo()
        pump(3)
        payload["undo_restores"] = dict(dialog._model.project_layout) == opening
        dialog = win._open_canvas_layout()
        pump(3)
        payload["refresh_widget_ok"] = (
            rows_by_key()["overlay_opacity"].slider.value()
            == int(round(opening["overlay_opacity"] * 100)))

        # ── H. "Dan clip vao o": transform that + MOT undo ───────
        model = dialog._model
        w, h = ASPECT_RATIOS.get(getattr(model, "project_ratio", "16:9"), (W, H))
        clips = []
        for index, path in enumerate(stills):
            # TrackType.IMAGE: `track_accepts_media` tu choi "image" tren track
            # VIDEO, va track IMAGE khong tu hap nen ca ba clip cung nam o
            # [0, 4) -- playhead 1,0 tinh ca ba la dang hien.
            track = model.add_track(TrackType.IMAGE, name="slot %d" % index)
            clip = model.add_clip(track.track_id, path, "image", 0.0, 4.0,
                                 name="still%d" % index)
            if clip is None:
                raise RuntimeError("khong tao duoc clip fixture %d" % index)
            clips.append(clip)
        model.playhead = 1.0
        load_state(enabled=True, layout="split", slot_gap=0.0, auto_fit=True,
                   background_mode="color", background_color="#0B0B0F")
        before = [_transform(c) for c in clips]
        base_rows = stack.undo_count
        dialog.btn_arrange.click()
        pump(4)
        boxes = canvas_layout.slots(w, h, model.project_layout)
        payload["boxes"] = len(boxes)
        payload["arrange_rows"] = stack.undo_count - base_rows
        moved = sum(1 for c, snap in zip(clips, before)
                    if _transform(c) != snap)
        payload["arranged"] = moved
        # Quy tac cua `_arrange`: tracks di duoi-len-tren nen track CUOI la lop
        # tren cung va nhan o 0. Doi chieu theo thu tu do, khong theo thu tu tao
        # clip (do lan chay 23/10: zip theo `clips` do tam lech cua mot nan nhan
        # CHUA di chuyen va bao DO sai).
        order = list(reversed(clips))[:len(boxes)]
        leftover = [c for c in clips if c not in order]
        bad = []
        for clip, box in zip(order, boxes):
            base_w, base_h = base_display_size(clip, w, h)
            drawn_w = base_w * clip.transform.scale_x
            drawn_h = base_h * clip.transform.scale_y
            cx = w / 2.0 + clip.transform.x
            cy = h / 2.0 + clip.transform.y
            if abs(cx - (box[0] + box[2] / 2.0)) > 0.75:
                bad.append("tam lech ngang %s %.1f" % (clip.name, cx))
            if abs(cy - (box[1] + box[3] / 2.0)) > 0.75:
                bad.append("tam lech doc %s %.1f" % (clip.name, cy))
            if drawn_w > box[2] + 0.75 or drawn_h > box[3] + 0.75:
                bad.append("trao o %s" % clip.name)
        payload["center_bad"] = bad
        payload["leftover_moved"] = [c.name for c in leftover
                                    if _transform(c) != before[clips.index(c)]]
        payload["hint_ok"] = (("du o" if not leftover else "lap o cuoi")
                              in dialog.lbl_arrange.text())
        stack.undo()
        pump(4)
        payload["arrange_reverted"] = [_transform(c) for c in clips] == before
        # Playhead ngoai khoang clip: nut dan PHAI tu choi va khong day lenh.
        # Do la thu duy nhat phat hien mot `active` rong (neu khong, cua "dan
        # clip" xanh vi mo hinh da san ro).
        model.playhead = 4.0
        base_rows = stack.undo_count
        dialog.btn_arrange.click()
        pump(3)
        payload["empty_refused"] = (stack.undo_count == base_rows
                                    and "clip" in dialog.lbl_arrange.text().lower())
        model.playhead = 1.0
        for track in list(model.tracks):
            for clip in list(track.clips):
                model.remove_clip(clip.clip_id)
        for track in list(model.tracks):
            if not track.clips:
                model.remove_track(track.track_id)
        pump(4)

        # ── I. pixel tren KHUNG XUAT cua dung model ma hop thoai ghi ──
        composer = FrameComposer(model, W, H)

        def render(**patch):
            load_state(**patch)
            return rgb_of(composer.render_frame(0.5))

        plain = render(enabled=False)
        dark = render(enabled=True, background_mode="black", layout="none",
                      overlay_opacity=0.0)
        # Nen "black" la NGUYEN hanh vi 1.0.5: mo bo cuc len ma chi chon den thi
        # khung phai y het nhu cu, neu khong thi tat o day la mot lop ve an.
        payload["black_same"] = bool(np.array_equal(plain, dark))
        del plain
        blue = render(enabled=True, background_mode="color",
                      background_color="#3673FE")
        payload["bg_px"] = count_color(blue, "#3673FE")
        del blue
        grid = render(enabled=True, background_mode="color",
                      background_color="#3673FE", layout="split-4",
                      frame_color="#00FFFF")
        payload["divider_px"] = count_color(grid, "#00FFFF")
        del grid
        ink = render(enabled=True, layout="none", background_mode="black",
                     background_color="#0B0B0F", texture="meme",
                     overlay_opacity=0.0, frame_color="#FFFFFF",
                     text_color="#FF0000", header_font="sans",
                     header_bold=True, header_size=64, header_text="TIEU DE THU")
        payload["header_px"] = count_color(ink, "#FF0000", 90)
        hit = np.abs(ink - np.array([255, 0, 0], np.int16)).max(axis=2) <= 90
        ys, _xs = np.nonzero(hit)
        hrect = canvas_layout.header_rect(W, H, {"layout": "none",
                                                 "header_size": 64})
        payload["header_inside"] = bool(
            len(ys) and ys.min() >= hrect[1] - 2
            and ys.max() <= hrect[1] + hrect[3] + 2)
        del ink

        # 10 chat lieu phai la 10 buoc ve khac nhau, khong phai mot tam nen dung
        # chung. Do qua `backdrop()` ma `paint_background` goi, o 320x240.
        def tex(name):
            settings = canvas_layout.normalize(
                dict(canvas_layout.LAYOUT_DEFAULTS, enabled=True,
                     background_mode="texture", texture=name))
            return rgb_of(canvas_layout.backdrop(settings, 320, 240))

        solids, means = [], []
        for name in canvas_layout.TEXTURE_ORDER:
            arr = tex(name)
            if len(np.unique(arr.reshape(-1, 3), axis=0)) < 2:
                solids.append(name)
            means.append(round(float(arr.mean()), 1))
            del arr
        payload["texture_solids"] = solids
        payload["texture_steps"] = len(set(means))

        # ── J. dong ho cua bo cuc (khong co pixel nao o day) ─────
        tight = canvas_layout.slots(W, H, canvas_layout.normalize(
            dict(canvas_layout.LAYOUT_DEFAULTS, layout="split",
                 slot_gap=0.2)))[0]
        loose = canvas_layout.slots(W, H, canvas_layout.normalize(
            dict(canvas_layout.LAYOUT_DEFAULTS, layout="split",
                 slot_gap=0.0)))[0]
        payload["gap_shrinks"] = (tight[0] > loose[0] + 1.0
                                  and tight[2] < loose[2] - 1.0)
        seq = dict(canvas_layout.LAYOUT_DEFAULTS, play_sequentially=True,
                   slot_seconds=2.0)
        payload["seq_steps"] = [canvas_layout.sequential_index(seq, t, 3)
                                for t in (0.0, 1.9, 2.0, 5.9, 6.0, 7.5)]
        payload["seq_off_ok"] = (canvas_layout.sequential_index(
            dict(seq, play_sequentially=False), 1.0, 3) == -1)
        rot = dict(canvas_layout.LAYOUT_DEFAULTS, manga_rotate_interval=5.0)
        # pool = 4 KHAC so o 3: khi count == pool thi
        # `(slot + step*count) % n` = slot, tuc khong trao gi ca, va cua do xanh
        # ma khong do duoc gi (do lan chay 23/10).
        payload["rotate_ok"] = (
            canvas_layout.rotated_slot_source(rot, 0.0, 3, 1, 4) == 1
            and canvas_layout.rotated_slot_source(rot, 5.0, 3, 1, 4) == (1 + 3) % 4)
        payload["rotate_off_ok"] = (canvas_layout.rotated_slot_source(
            dict(rot, manga_rotate_interval=0.0), 9.0, 3, 2, 4) == 2)

        # ── K. van qua file .clinq (model THAT cua cua so nay) ────
        path = os.path.join(folder, "Kiem bo cuc.clinq")
        settings = canvas_layout.normalize(dict(canvas_layout.LAYOUT_DEFAULTS, **{
            "enabled": True, "layout": "manga-grid",
            "background_mode": "texture", "texture": "parchment",
            "header_text": "Tuan 42", "slot_gap": 0.05,
            "play_sequentially": True, "manga_rotate_interval": 5.0}))
        probe_model = TimelineModel()
        probe_model.project_ratio = "16:9"
        probe_model.set_project_layout(settings, emit=False)
        if not project_storage.save_project_to_file(probe_model, path):
            raise RuntimeError("save_project_to_file tra False")
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        if "project_layout" not in data.get("timeline", {}):
            raise RuntimeError("file .clinq khong ghi khoa project_layout")
        reloaded = TimelineModel()
        project_storage.restore_model_from_clinq(reloaded, data)
        payload["round_trip_keys"] = len(reloaded.project_layout)
        payload["round_trip_ok"] = (
            reloaded.project_layout == canvas_layout.normalize(settings))
        # File cua 1.0.5 tro ve truoc: KHONG co khoa nao ca. Duong nay phai tra
        # ve mac dinh thay vi ve trang tinh hay crash.
        stale = dict(data)
        stale["timeline"] = {k: v for k, v in data["timeline"].items()
                             if k != "project_layout"}
        legacy = TimelineModel()
        project_storage.restore_model_from_clinq(legacy, stale)
        payload["legacy_keys"] = len(legacy.project_layout)
        payload["legacy_ok"] = legacy.project_layout == canvas_layout.LAYOUT_DEFAULTS

        # ── L. anh chung minh: cua so THAT, nen THAT ─────────────
        load_state(enabled=True, layout="split-4", background_mode="texture",
                   texture="blueprint", frame_color="#00FFFF",
                   header_text="BO CUC", footer_text="Phong cach",
                   slot_gap=0.06)
        pump(6)
        raw = dialog.grab().toImage()
        sheet = QImage(raw.size(), QImage.Format.Format_RGB32)
        sheet.fill(QColor("#101215"))
        grabber = QPainter(sheet)
        grabber.drawImage(0, 0, raw)
        grabber.end()
        if not sheet.save(shot, "PNG"):
            raise RuntimeError("khong luu duoc anh hop thoai")
        back = QImage(shot)
        payload["shot_readable"] = (not back.isNull()
                                    and back.width() == sheet.width())
        payload["shot_bytes"] = os.path.getsize(shot) if os.path.isfile(shot) else 0
        flat = back.convertToFormat(QImage.Format.Format_RGB32)
        payload["shot_colors"] = len({flat.pixel(x, y)
                                      for x in range(0, flat.width(), 3)
                                      for y in range(0, flat.height(), 3)})
    except Exception as exc:
        # Mot exception o giua probe khong duoc tro thanh "ALL PASS": cua do thieu
        # truong thi KeyError, va KeyError bat qua bien callback C++ cua Qt co the
        # abort 0xC0000409 do la lop loi repo da ghi.
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
        # Traceback ra STDERR, flush ngay: lan chay 23/10 probe abort 0xC0000409
        # o dong 9664 va an TOAN BO stdout -- khong co dong nay thi chi biet "chet
        # im lang", khong biet chet o dau (3 lan chay moj de tìm 1 dong loi).
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
    finally:
        if dialog is not None:
            try:
                dialog.close()
            except Exception:
                pass
        if composer is not None:
            try:
                composer.close()
            except Exception:
                pass
        if win is not None:
            # QMediaPlayer (backend WMF) giu NGUON mo cho toi khi
            # setSource(QUrl()), ke ca sau stop()/close(): do lan chay 23/10,
            # psutil liet ke dung MOT handle cua process tro vao file fixture
            # trong khi gc khong con reader nao.
            player = getattr(win, "_audio_player", None)
            if player is not None:
                try:
                    player.stop()
                    player.setSource(QUrl())
                except Exception:
                    pass
            try:
                win.close()
            except Exception:
                pass
        pump(8)
        if cache_state is not None:
            payload["user_cache_extra"] = _cache_guard_finish(cache_state)
        project_storage.AUTO_SAVE_FILE = real_autosave
        project_storage.RECOVERY_DIR = real_recovery
        shutil.rmtree(folder, ignore_errors=True)

    if "error" in payload:
        payload["checks"] = [{"name": name, "ok": False}
                             for name, _f in CANVAS_LAYOUT_REPORT_CHECKS]
        payload["failed"] = ["probe chay khong xong"]
        payload["ok"] = False
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print("canvas-layout-report DO: probe chay khong xong — %s"
              % payload["error"])
        return 1
    fails = canvas_layout_report_fails(payload)
    payload["checks"] = [{"name": name, "ok": name not in fails}
                         for name, _f in CANVAS_LAYOUT_REPORT_CHECKS]
    payload["failed"] = fails
    payload["ok"] = not fails
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("canvas-layout-report: %s  (%d cua, %d do)  anh: %s"
          % ("ALL PASS" if not fails else "DO",
             len(CANVAS_LAYOUT_REPORT_CHECKS), len(fails), payload["screenshot"]))
    for name in fails:
        print("  canvas-layout-report DO: %s" % name)
    return 0 if not fails else 1


def _transform(clip):
    """Biet danh transform cua clip -- do lech cua "Dan clip vao o" so bang so."""
    t = clip.transform
    return (round(t.x, 3), round(t.y, 3), round(t.scale_x, 5), round(t.scale_y, 5))


if __name__ == "__main__":
    sys.exit(run_selftest())
