"""Anh cho dong selftest `the Cat in/out trong bang thuoc tinh`.

Ba duong cung thay doi khi cua so nguon dich di, va ca ba deu la duong SAN
XUAT:

  1. `ui.graphics.timeline_scene.TimelineScene` that — clip ngan lai va doi
     cho tren truc thoi gian.
  2. `core.frame_composer.FrameComposer.render_frame` — bo giai ma ma exporter
     dung. "Tai giay t tren timeline thi thay khuc nao cua nguon" do chinh no
     tra ra, khong phai do probe tu tinh in_point.
  3. `core.audio_mix.render_audio` — cung ham exporter goi; wav doc lai bang
     `wave` stdlib de do "tieng bat dau luc nao" va "diem doi ton nam dau",
     tuc la `atrim=start/duration` + `adelay` bien thanh con so.

Nguon: video 6 giay,moi giay MOT MAU TUOI (do, luc, lam, vang, nat, hong) nen
"do mau" la biet doan nguon nao dang chay, khong can so lech pixel. Tieng 440
Hz trong 0..3s va 880 Hz trong 3..6s: diem doi ton la moc PHAI cua cua so
nguon, va no phai dung yen khi cat tu ben trai — do la noi dung cua "giu meg
ben kia".

Bon o:
  A. goc             — clip 0..4s, In=0, Out=4.
  B. cat dau In=2,0  — do `spin_trim_in` cua widget THAT; start nhich len 2,0,
                       moc phai van 4,0: tieng bat dau tre 2,0s con diem doi
                       ton o nguyen 3,0s.
  C. cat cuoi Out=2,0 — tu goc, moc trai dung yen: tieng van bat dau 0,0s, va
                       diem doi ton bien mat vi 880 Hz nam ngoai cua so.
  D. Ctrl+Z          — ca ba duong quay ve dung A.

```bash
python scratch/trim_evidence.py
```
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import types
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch", "trim_evidence.png")
JSON_OUT = os.path.join(ROOT, "scratch", "trim_evidence.json")

CELL_W, CELL_H, GAP = 640, 150, 14
STRIP_T = (0.5, 1.5, 2.5, 3.5)          # bon thoi diem timeline do bang nhau
# Moi khuc 1 giay cua nguon, mau tach nhau ro de yuv420p khong lam nhat tri.
BLOCKS = (("do", (255, 0, 0), "red"),
          ("luc", (0, 200, 0), "lime"),
          ("lam", (0, 0, 255), "blue"),
          ("vang", (255, 235, 0), "yellow"),
          ("nat", (0, 235, 235), "cyan"),
          ("hong", (255, 0, 255), "magenta"))
EMPTY = ("den", (8, 8, 8))              # khung trang = o do khong co clip nao
HIGH_TONE_MIN = 1300.0   # 440 Hz ~ 880 lan cat 0/giay, 880 Hz ~ 1760 lan/giay
TONE_WINDOW = 0.1
CLIP_START, CLIP_DURATION, END = 0.0, 4.0, 4.0
PROJECT_SPAN = 6.0   # lang do dai giu co dinh de bon o so cung bon thoi diem


def build_source(ffmpeg, path):
    """Video 6s: sau khuc mau 1 giay + tieng 440 Hz roi 880 Hz."""
    cmd = [ffmpeg, "-y", "-v", "error"]
    for _, _, name in BLOCKS:
        cmd += ["-f", "lavfi", "-i",
                "color=c=%s:s=320x240:r=25:d=1" % name]
    cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=3"]
    cmd += ["-filter_complex",
            "[0:v][1:v][2:v][3:v][4:v][5:v]concat=n=6:v=1:a=0[v];"
            "[6:a][7:a]concat=n=2:v=0:a=1[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", path]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   timeout=240, check=False, creationflags=0x08000000)
    if not os.path.isfile(path):
        raise RuntimeError("khong tao duoc nguon 6s mau+tieng")


def read_pcm(path):
    """Doc wav PCM 16-bit cua render_audio -> list sample mono -1..1."""
    with wave.open(path, "rb") as handle:
        channels, width, rate, frames = (handle.getnchannels(),
                                         handle.getsampwidth(),
                                         handle.getframerate(),
                                         handle.getnframes())
        raw = handle.readframes(frames)
    if width != 2 or channels not in (1, 2):
        raise RuntimeError("wav khong phai 16-bit mono/stereo: %d/%d"
                           % (width, channels))
    words = struct.unpack("<%dh" % (len(raw) // 2), raw)
    if channels == 2:
        words = [(words[i] + words[i + 1]) / 2.0 for i in
                 range(0, len(words) - 1, 2)]
    return [value / 32768.0 for value in words], rate


def rms(samples, start_s, end_s, rate):
    i, j = int(start_s * rate), min(len(samples), int(end_s * rate))
    window = samples[i:j]
    if not window:
        return 0.0
    return (sum(value * value for value in window) / len(window)) ** 0.5


def crossings_per_sec(samples, rate, start_s, end_s):
    i, j = int(start_s * rate), min(len(samples), int(end_s * rate))
    window = samples[i:j]
    if len(window) < 3:
        return 0.0
    count = sum(1 for k in range(1, len(window))
                if (window[k] >= 0.0) != (window[k - 1] >= 0.0))
    return count / max(1e-6, (end_s - start_s))


def first_loud(samples, rate, threshold=0.02):
    """Giay dau tien wav co tieng — doan clip nay bat dau chay luc nao."""
    step = int(0.05 * rate)
    if step <= 0:
        return None
    for start in range(0, len(samples) - step, step):
        if rms(samples, start / rate, (start + step) / rate, rate) > threshold:
            return start / rate
    return None


def tone_switch_time(samples, rate):
    """Giay dau tien bao 880 Hz; None neu doan do nam ngoai cua so nguon."""
    step = int(TONE_WINDOW * rate)
    for start in range(0, len(samples) - step, step):
        density = crossings_per_sec(samples[start:start + step], rate,
                                    0.0, TONE_WINDOW)
        if density > HIGH_TONE_MIN:
            return start / rate
    return None


def grab_scene(scene, width, height):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    shot = QImage(width, height, QImage.Format_RGB32)
    shot.fill(0xFF0B0C10)
    painter = QPainter(shot)
    scene.render(painter, QRectF(shot.rect()), QRectF(0, 0, width, height))
    painter.end()
    return shot


def opaque_fraction(image):
    """Ty le pixel sang hon nen — o timeline trang ran thi phai bang 0."""
    from PySide6.QtGui import qRed, qGreen, qBlue
    hits = total = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            color = image.pixel(x, y)
            total += 1
            if (qRed(color) + qGreen(color) + qBlue(color)) > 90:
                hits += 1
    return hits / max(1, total)


def classify(rgb):
    """Doan gan nhat — biet khuc nguon nao dang chay, khong phai do lech mau."""
    best, best_distance = None, None
    for name, expected in (EMPTY,) + tuple(BLOCKS_RGB()):
        distance = sum((a - b) ** 2 for a, b in zip(rgb, expected)) ** 0.5
        if best_distance is None or distance < best_distance:
            best, best_distance = name, distance
    return best, round(best_distance, 1)


def BLOCKS_RGB():
    return [(name, rgb) for name, rgb, _ in BLOCKS]


def main():
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from core import external_tools
    from core.audio_mix import collect_audio_clips, render_audio
    from core.commands import UndoStack
    from core.frame_composer import FrameComposer
    from core.snap_engine import SnapEngine
    from core.time_mapper import TimePixelMapper
    from core.timeline_model import TimelineModel, TrackType
    from ui.graphics.timeline_scene import TimelineScene
    from ui.properties_panel import ClipPropertiesWidget

    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    app = QApplication.instance() or QApplication([])

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))

    folder = os.path.join(tempfile.gettempdir(), "clinging_trim_evidence")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    src = os.path.join(folder, "mau_tieng.mp4")
    build_source(ffmpeg, src)

    results = []

    def check(label, actual, expected):
        ok = actual == expected
        results.append({"label": label, "actual": actual,
                        "expected": expected, "ok": ok})
        print("%-54s %s  actual=%r expected=%r" %
              (label, "PASS" if ok else "FAIL", actual, expected))

    def settle(seconds=1.2):
        """Cho worker thumbnail/song chay xong roi moi grab. Bon o phai cung
        mot thuoc do, neu khong o cuoi lech o dau vi doan anh kip luc."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)

    model = TimelineModel()
    model.project_ratio = "16:9"
    mapper = TimePixelMapper()
    mapper.set_zoom(120.0)
    scene = TimelineScene(model, mapper, SnapEngine(mapper))
    spine = model.add_track(TrackType.VIDEO)
    overlay = model.add_track(TrackType.VIDEO)
    model.add_track(TrackType.AUDIO)
    if not spine.is_main_track:
        raise RuntimeError("hang thu nhat khong phai truc chinh nhu gate gia dinh")

    # Clip dat tren Overlay: tren truc chinh thi ripple keo no ve 0 va khong
    # con gi phan biet "cat dau thi moc trai nhich, cat cuoi thi moc trai yen".
    clip = model.add_clip(overlay.track_id, src, "video", CLIP_START,
                          CLIP_DURATION, name="mau-tieng")
    if clip is None:
        raise RuntimeError("add_clip tra ve None")
    clip.in_point = 0.0
    clip.speed = 1.0
    clip.source_duration = 6.0
    clip.refresh_out_point()
    model.duration = 6.0

    host = QWidget()
    host.setObjectName("MainWindow")
    stack = UndoStack()
    host.timeline_panel = types.SimpleNamespace(
        model=model, undo_stack=stack,
        scene=types.SimpleNamespace(_clip_items={}))
    editor = ClipPropertiesWidget(clip, parent=host)
    if editor.card_trim.isHidden():
        raise RuntimeError("the Cat an tren clip co nguon that")

    def spin_set(spin, value):
        """Do `valueChanged` cua Qt co the tiep nhan muon nen van phai quay
        vong su kien: day la duong spin -> TrimClipCommand that."""
        spin.setValue(float(value))
        settle(0.4)

    def measure(tag):
        """Ba duong cung do tai mot trang thai: hinh, frame render, tieng."""
        # `active_visual_clips_at` GIU KHUNG CUOI khi playhead nam qua het
        # do dai du an (core/timeline_model.py:1457), neu khong thi sau khi cat
        # cuoi, o 2,5s va 3,5s van "co hinh" chi vi du an bi rut theo clip. Phai
        # giu mot lang do dai co dinh thi bon o moi so duoc cung mot luc.
        model.duration = PROJECT_SPAN
        geometry = [round(clip.start_time, 3), round(clip.duration, 3),
                    round(clip.in_point, 3), round(clip.out_point, 3)]
        composer = FrameComposer(model, 320, 180)
        frames = []
        from PySide6.QtGui import qRed, qGreen, qBlue
        try:
            for t in STRIP_T:
                image = composer.render_frame(t)
                pixel = image.pixel(160, 90)
                name, distance = classify((qRed(pixel), qGreen(pixel),
                                           qBlue(pixel)))
                frames.append({"t": t, "colour": name, "distance": distance,
                               "source": round(clip.source_time(t), 3),
                               "image": image})
        finally:
            composer.close()
        clips = collect_audio_clips(model)
        wav_path = os.path.join(folder, "%s.wav" % tag)
        render_audio(model, clips, model.duration, wav_path)
        samples, rate = read_pcm(wav_path)
        return {"tag": tag, "geometry": geometry, "frames": frames,
                "spin_in": round(editor.spin_trim_in.value(), 3),
                "spin_out": round(editor.spin_trim_out.value(), 3),
                "first_loud": first_loud(samples, rate),
                "switch": tone_switch_time(samples, rate),
                "rms_head": round(rms(samples, 0.3, 1.7, rate), 5),
                "rms_tail": round(rms(samples, 2.3, 3.7, rate), 5),
                "wav": os.path.basename(wav_path)}

    def colours(state):
        return [frame["colour"] for frame in state["frames"]]

    def near(value, target, tolerance=0.12):
        return value is not None and abs(value - target) <= tolerance

    def audio_line(state):
        return "tieng: moc dau=%s  doi ton 440->880=%s  RMS 0,3..1,7=%.4f  " \
               "RMS 2,3..3,7=%.4f" % (
                   fmt_s(state["first_loud"]), fmt_s(state["switch"]),
                   state["rms_head"], state["rms_tail"])

    def fmt_s(value):
        return "%.2fs" % value if value is not None else "khong co"

    settle()
    states = []

    # -- A. trang thai goc ------------------------------------------------
    state_a = measure("a_goc")
    settle()
    states.append(("A. goc: clip 0..4s, In=0, Out=4",
                   grab_scene(scene, CELL_W, CELL_H), state_a))

    # -- B. cat dau bang spin THAT ---------------------------------------
    spin_set(editor.spin_trim_in, 2.0)
    settle()
    state_b = measure("b_cat_dau")
    settle()
    states.append(("B. cat dau In=2,0s (spin that): moc phai dung yen",
                   grab_scene(scene, CELL_W, CELL_H), state_b))
    check("B giu meg phai o 4,0s", round(clip.end_time, 3), END)
    check("B start_time nhich dung 2,0s", round(clip.start_time, 3), 2.0)
    check("B mot lan keo spin = mot buoc undo", stack.undo_count, 1)

    stack.undo()
    # Ctrl+Z khong tu ve lai bang thuoc tinh: panel chi doc lai model khi clip
    # duoc chon lai. Goi dung duong do de range cua spin khong con la range cua
    # trang thai B (neu khong, Out = 2,0 bi chan thanh 2,1 va "cat cuoi" do
    # mot cai cat khac).
    editor.update_values(clip)
    settle(0.5)

    # -- C. cat cuoi bang spin THAT --------------------------------------
    spin_set(editor.spin_trim_out, 2.0)
    settle()
    state_c = measure("c_cat_cuoi")
    settle()
    states.append(("C. cat cuoi Out=2,0s (spin that): moc trai dung yen",
                   grab_scene(scene, CELL_W, CELL_H), state_c))
    check("C giu meg trai o 0,0s", round(clip.start_time, 3), CLIP_START)
    check("C dong cua so nguon tai 2,0s", round(clip.out_point, 3), 2.0)

    # -- D. Ctrl+Z ve dung A ---------------------------------------------
    stack.undo()
    # Duong that ma panel dung de doc lai model khi clip duoc chon lai
    # (PropertiesPanel.show_clip_properties goi update_values).
    editor.update_values(clip)
    settle()
    state_d = measure("d_hoan_tac")
    settle()
    states.append(("D. Ctrl+Z: ca ba duong quay ve nhu A",
                   grab_scene(scene, CELL_W, CELL_H), state_d))

    # Nguon: 0..1 do | 1..2 luc | 2..3 lam | 3..4 vang.
    check("A: mau theo t=0,5/1,5/2,5/3,5 la do-luc-lam-vang",
          colours(state_a), ["do", "luc", "lam", "vang"])
    check("B: cat dau 2s dich cua so nguon len 2s",
          colours(state_b), ["den", "den", "lam", "vang"])
    check("C: cat cuoi 2s chan doan cuoi, dau khong doi",
          colours(state_c), ["do", "luc", "den", "den"])
    check("D: Ctrl+Z tra lai dung khung hinh A",
          colours(state_d), colours(state_a))
    check("D: Ctrl+Z tra lai dung hinh hoc A",
          state_d["geometry"], state_a["geometry"])
    check("A: do 440->880 Hz nam tai 3,0s", near(state_a["switch"], 3.0), True)
    check("B: cat dau van giu diem doi ton o 3,0s",
          near(state_b["switch"], 3.0), True)
    check("B: tieng bat dau tre 2,0s sau khi cat dau",
          near(state_b["first_loud"], 2.0), True)
    check("C: tieng van bat dau 0,0s khi cat cuoi",
          near(state_c["first_loud"], state_a["first_loud"] or 0.0), True)
    check("C: doan 880 Hz bi loai khoi cua so nguon", state_c["switch"], None)
    check("B: doan 0,3..1,7s im lang tuyen doi", state_b["rms_head"] < 0.001, True)
    check("C: doan 2,3..3,7s im lang tuyen doi", state_c["rms_tail"] < 0.001, True)
    check("A: ca hai doan deu co tieng",
          [state_a["rms_head"] > 0.05, state_a["rms_tail"] > 0.05],
          [True, True])
    check("D: Ctrl+Z bat lai ca hai doan",
          [state_d["rms_head"] > 0.05, state_d["rms_tail"] > 0.05],
          [True, True])
    blank = [label for label, shot, _ in states if opaque_fraction(shot) < 0.01]
    check("khong o timeline nao trang ran", blank, [])
    # Anh phai do duoc cai gi: ba trang thai phai cho ba chuoi mau khac het,
    # neu khong thi bon o chi la bon ban in cua cung mot khung.
    check("A/B/C cho ba chuoi mau khac nhau het",
          len({tuple(colours(s)) for _, _, s in states[:3]}), 3)
    check("spin doc lai dung gia tri model sau Ctrl+Z",
          [state_d["spin_in"], state_d["spin_out"]], [0.0, 4.0])
    # Neu bang mau doc duoc gan voi mot mau gan nhat thi "do mau" khong con la
    # doan nguon nao dang chay, va ca bon phep do o tren chi la doan ket luan
    # cua mot phep do nhat tri.
    far = [(state["tag"], frame["t"], frame["colour"], frame["distance"])
           for _, _, state in states for frame in state["frames"]
           if frame["distance"] > 80.0]
    check("moi khung hinh doc duoc mot mau ro", far, [])

    # -- Canvas ------------------------------------------------------------
    # Moi hang: grab TimelineScene THAT o tren, ben duoi la bon khung do
    # FrameComposer.render_frame — tuc la "cat xong thi ban xuat ra gi", khong
    # phai "cat xong thi preview ve duoc bao gi".
    SCENE_H, TILE_W, TILE_H = 150, 152, 86
    canvas_w = 900
    row_h = 20 + SCENE_H + 8 + TILE_H + 14 + 26
    canvas_h = 44 + GAP + row_h * len(states) + GAP + 30
    canvas = QImage(canvas_w, canvas_h, QImage.Format_RGB32)
    canvas.fill(0xFF15171C)
    painter = QPainter(canvas)
    painter.setPen(QColor("#9AA3BF"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(GAP, 22,
                     "The Cat in/out — TimelineScene that + FrameComposer "
                     "(duong xuat) + wav do tu render_audio")
    y = 44 + GAP
    for label, shot, state in states:
        painter.setPen(QColor("#D8DCE0"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(GAP, y + 13, label)
        painter.drawImage(QRectF(GAP, y + 20, CELL_W, SCENE_H), shot)
        x = GAP + CELL_W + GAP
        painter.setPen(QColor("#9AA3AD"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(x, y + 30, "khung hinh xuat (FrameComposer)")
        painter.drawText(x, y + 46, "start/dur/in/out:")
        painter.setPen(QColor("#40E0D0"))
        painter.drawText(x + 8, y + 60,
                         "/".join("%.1f" % v for v in state["geometry"]))
        painter.setPen(QColor("#9AA3AD"))
        painter.drawText(x, y + 78, "spin In/Out:")
        painter.setPen(QColor("#40E0D0"))
        painter.drawText(x + 8, y + 92, "%.2f / %.2f" % (
            state["spin_in"], state["spin_out"]))
        for index, frame in enumerate(state["frames"]):
            tile_x = GAP + index * (TILE_W + 6)
            tile_y = y + 20 + SCENE_H + 8
            painter.drawImage(QRectF(tile_x, tile_y, TILE_W, TILE_H),
                              frame["image"])
            painter.setPen(QColor("#9AA3AD"))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(tile_x, tile_y + TILE_H + 12,
                             "t=%.2fs -> %s" % (frame["t"], frame["colour"]))
        painter.setPen(QColor("#9AA3AD"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(GAP, y + 20 + SCENE_H + TILE_H + 34, audio_line(state))
        y += row_h
    failed = [row["label"] for row in results if not row["ok"]]
    painter.setPen(QColor("#EF4444" if failed else "#7DD3A0"))
    painter.setFont(QFont("Consolas", 9))
    painter.drawText(GAP, canvas_h - 14,
                     "%d/%d phep do PASS | failed: %s" %
                     (len(results) - len(failed), len(results),
                      ", ".join(failed) or "khong co"))
    painter.end()
    canvas.save(OUT)

    with open(JSON_OUT, "w", encoding="utf-8") as handle:
        json.dump({"png": os.path.basename(OUT), "checks": results,
                   "failed": failed,
                   "source_blocks": [name for name, _, _ in BLOCKS],
                   "strip_times": list(STRIP_T),
                   "states": [{**{k: v for k, v in state.items() if k != "frames"},
                               "frames": [{k: v for k, v in frame.items()
                                           if k != "image"}
                                          for frame in state["frames"]]}
                              for _, _, state in states]},
                  handle, ensure_ascii=False, indent=2)
    print("saved %s (%dx%d)" % (os.path.basename(OUT),
                                canvas.width(), canvas.height()))
    print("ALL PASS" if not failed else "CO %d KET QUA FAIL" % len(failed))
    shutil.rmtree(folder, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
