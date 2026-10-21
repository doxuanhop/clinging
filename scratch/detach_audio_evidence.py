"""Anh + so do RMS cho dong selftest `tach tieng video thanh clip audio rieng`.

Ba o timeline ve bang CHINH TimelineScene san xuat (scene duoc dung luc model
con rong, moi item mot lan clip duoc them qua dung signal cua model — khong co
ClipItem gia), con chuoi so do lay tu wav do `core.audio_mix.render_audio` —
dung ham ma exporter goi — sinh ra, lai duoc lap bang mo `wave` cua stdlib.

Nguon la video 4 giay co TIENG HAI TON: 440 Hz tu 0..2s, 880 Hz tu 2..4s. Diem
doi ton do bang mat cat zero-crossing tung o 100 ms, khong nhin bang mat. That
khong phai do "co tieng/khong co tieng": noi dung giong het ma khong lech nua
giay cung khong phat hien duoc bang RMS toan file.

  1. Timeline truoc khi tach — mot hang video, tieng nam trong chinh no.
  2. Sau khi tach — them hang audio nam ngay dung cho, hang video im lang.
     wav xuat ra PHAI giong o 1 den < 2 dB: tach ra la thao tac cau truc,
     khong phai thao tac am thanh.
  3. Sau khi keo clip tach ro sang +1,0 giay — tieng phai nhay theo: diem doi
     ton di tu ~2,0s len ~3,0s, va 0..1s im lang tuyen doi. Do la bang chung
     no la clip doc lap, khong phai bong ma cua clip video.
  4. Ctrl+Z — hang audio bien mat, video lai co tieng, wav quay ve nhu o 1.

```bash
python scratch/detach_audio_evidence.py
```
"""

import json
import os
import shutil
import time
import struct
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch", "detach_audio_evidence.png")
JSON_OUT = os.path.join(ROOT, "scratch", "detach_audio_evidence.json")

CELL_W, CELL_H, GAP, LABEL_H = 620, 190, 14, 30
TONE_WINDOW = 0.1          # do dai o do mat cat zero-crossing (giay)
# 440 Hz ~ 880 lan cat 0/giay, 880 Hz ~ 1760 lan/giay: 1300 nam giua hai cac.
HIGH_TONE_MIN = 1300.0


def build_source(ffmpeg, path):
    """Video 4s: nen testsrc2 + tieng 440 Hz roi 880 Hz (noi dung co cau truc)."""
    cmd = [ffmpeg, "-y", "-v", "error",
           "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=4",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
           "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
           "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
           "-map", "0:v", "-map", "[a]",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", path]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   timeout=240, check=False, creationflags=0x08000000)
    if not os.path.isfile(path):
        raise RuntimeError("khong tao duoc nguon 4s co tieng hai ton")


def read_pcm(path):
    """Doc wav PCM 16-bit stereo cua render_audio -> list sample mono -1..1."""
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
    """Mat do zero-crossing trong mot o — 440 Hz vs 880 Hz cach nhau 2 lan."""
    i, j = int(start_s * rate), min(len(samples), int(end_s * rate))
    window = samples[i:j]
    if len(window) < 3:
        return 0.0
    count = sum(1 for k in range(1, len(window))
                if (window[k] >= 0.0) != (window[k - 1] >= 0.0))
    return count / max(1e-6, (end_s - start_s))


def tone_switch_time(samples, rate):
    """Giay dau tien ma am thanh bao 880 Hz — diem doi ton, khong phai diem co
    noi dung (cua im lang cung duoc dem la "chua doi")."""
    step = int(TONE_WINDOW * rate)
    if step <= 0:
        return None
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
    scene.render(painter, QRectF(shot.rect()),
                 QRectF(0, 0, width, height))
    painter.end()
    return shot


def opaque_fraction(image):
    """Ty le pixel sang hon nen — o timeline rong thi phai bang 0."""
    from PySide6.QtGui import qRed, qGreen, qBlue
    hits = total = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            color = image.pixel(x, y)
            total += 1
            if (qRed(color) + qGreen(color) + qBlue(color)) > 90:
                hits += 1
    return hits / max(1, total)


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from core import external_tools
    from core.audio_mix import collect_audio_clips, render_audio
    from core.commands import DetachAudioCommand, UndoStack
    from core.snap_engine import SnapEngine
    from core.time_mapper import TimePixelMapper
    from core.timeline_model import TimelineModel, TrackType
    from ui.graphics.timeline_scene import TimelineScene

    sys.stdout.reconfigure(encoding="utf-8")
    app = QApplication.instance() or QApplication([])  # noqa: F841

    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))

    folder = os.path.join(tempfile.gettempdir(), "clinging_detach_evidence")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    src = os.path.join(folder, "hai_ton.mp4")
    build_source(ffmpeg, src)

    def settle(seconds=4.0):
        """Cho worker thumbnail/song chay xong roi moi grab.

        Neu khong, o cuoi khac ba o dau chi vi doan anh kip luc giai phong xong
        — khong phai vi Ctrl+Z. Bon o phai cung mot trang thai do.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)

    results = []

    def check(label, actual, expected):
        ok = actual == expected
        results.append({"label": label, "actual": actual,
                        "expected": expected, "ok": ok})
        print("%-52s %s  actual=%r expected=%r" %
              (label, "PASS" if ok else "FAIL", actual, expected))

    # Model rong -> scene -> moi item sinh ra qua signal that cua model.
    model = TimelineModel()
    mapper = TimePixelMapper()
    mapper.set_zoom(90.0)
    scene = TimelineScene(model, mapper, SnapEngine(mapper))
    video_track = model.add_track(TrackType.VIDEO)
    audio_track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(video_track.track_id, src, "video", 0.0, 4.0, "Hai ton")
    model.duration = 5.0

    def export_wav(tag):
        clips = collect_audio_clips(model)
        path = os.path.join(folder, "%s.wav" % tag)
        render_audio(model, clips, model.duration, path)
        samples, rate = read_pcm(path)
        return path, samples, rate, [c.clip_id for c in clips]

    def audio_ids():
        return [c.clip_id for t in model.tracks
                if t.track_type == TrackType.AUDIO for c in t.clips]

    # ── 1. Trang thai goc: tieng nam trong chinh clip video ──────────
    before_path, before, before_rate, before_ids = export_wav("truoc")
    before_switch = tone_switch_time(before, before_rate)
    settle()
    shot_before = grab_scene(scene, CELL_W, CELL_H)

    # ── 2. Tach tieng qua dung lenh UndoStack ────────────────────────
    stack = UndoStack()
    stack.push(DetachAudioCommand(model, clip.clip_id))
    app.processEvents()
    detached_ids = audio_ids()
    after_path, after, after_rate, after_ids = export_wav("sau")
    after_switch = tone_switch_time(after, after_rate)
    settle()
    shot_after = grab_scene(scene, CELL_W, CELL_H)

    check("tach ra dung 1 clip audio", len(detached_ids), 1)
    check("export chi con doc clip audio tach ro", after_ids, detached_ids)
    check("diem doi ton KHONG doi sau khi tach",
          round(after_switch, 2) if after_switch else None,
          round(before_switch, 2) if before_switch else None)
    # Tieng tach ra la thao tac CAU TRUC, khong phai thao tac am thanh: RMS toan
    # file hai ben phai cham nhau duoi 2 dB, neu khong thi "tach" da doi bai nghe.
    before_rms = rms(before, 0, 5, before_rate)
    ratio = rms(after, 0, 5, after_rate) / max(1e-9, before_rms)
    import math
    db = abs(20.0 * math.log10(max(1e-9, ratio)))
    check("RMS toan file lech duoi 2 dB", db < 2.0, True)
    check("o timeline sau co khoi (khong phai trang ran)",
          opaque_fraction(shot_after) > opaque_fraction(shot_before), True)

    # ── 3. Keo clip tach ro +1,0 giay: tieng phai di theo ────────────
    moved = model.get_clip(detached_ids[0])
    model.move_clip(moved.clip_id, 1.0)
    app.processEvents()
    moved_path, moved_samples, moved_rate, moved_ids = export_wav("dich")
    moved_switch = tone_switch_time(moved_samples, moved_rate)
    settle()
    shot_moved = grab_scene(scene, CELL_W, CELL_H)

    check("dich 1,0s van la clip do trong export", moved_ids, detached_ids)
    check("diem doi ton nhay +1,0s (≈3,0s)",
          moved_switch is not None and abs(moved_switch - 3.0) < 0.15, True)
    check("0..1s im lang tuyen doi sau khi dich",
          rms(moved_samples, 0.0, 0.9, moved_rate) < 0.001, True)
    check("1,0..2,9s van co tieng 440 Hz",
          rms(moved_samples, 1.2, 2.8, moved_rate) > 0.05, True)

    # ── 4. Ctrl+Z: mot buoc tra lai ca hai nua ───────────────────────
    stack.undo()
    app.processEvents()
    undo_path, undo_samples, undo_rate, undo_ids = export_wav("hoan_tac")
    undo_switch = tone_switch_time(undo_samples, undo_rate)
    settle()
    shot_undo = grab_scene(scene, CELL_W, CELL_H)

    check("Ctrl+Z xoa clip audio tach ro", audio_ids(), [])
    check("Ctrl+Z khong de lai clip audio trong export",
          [i for i in undo_ids if i in detached_ids], [])
    check("Ctrl+Z tra lai dung noi dung nhu ban goc",
          round(undo_switch, 2), round(before_switch, 2))
    check("Ctrl+Z bat lai tieng cho clip video", clip.audio_muted, False)

    # ── Canvas chung minh ────────────────────────────────────────────
    canvas_w = CELL_W * 2 + GAP * 3
    canvas_h = (CELL_H + LABEL_H) * 2 + GAP * 3 + 96
    canvas = QImage(canvas_w, canvas_h, QImage.Format_RGB32)
    canvas.fill(0xFF15171C)
    painter = QPainter(canvas)
    painter.setPen(QColor("#9AA3AD"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(GAP, 22,
                     "Tach am thanh — TimelineScene that + wav do bang "
                     "core.audio_mix.render_audio")
    painter.setPen(QColor("#40E0D0"))
    painter.setFont(QFont("Consolas", 9))
    painter.drawText(
        GAP, 44,
        "doi ton: goc %.2fs | tach %.2fs | dich +1,0s %.2fs | Ctrl+Z %.2fs   "
        "RMS goc %.4f sau %.4f" % (
            before_switch, after_switch, moved_switch, undo_switch,
            rms(before, 0, 5, before_rate), rms(after, 0, 5, after_rate)))
    cells = (("1. goc: tieng nam trong clip video", shot_before),
             ("2. tach tieng: hang audio cung cho, video im lang", shot_after),
             ("3. keo clip tach ro +1,0s: tieng nhay theo", shot_moved),
             ("4. Ctrl+Z: hang audio bien mat, video lai co tieng", shot_undo))
    for index, (label, shot) in enumerate(cells):
        x = GAP + (index % 2) * (CELL_W + GAP)
        y = GAP * 2 + 56 + (index // 2) * (CELL_H + LABEL_H + GAP)
        painter.drawImage(QRectF(x, y, CELL_W, CELL_H), shot)
        painter.setPen(QColor("#D8DCE0"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(x, y + CELL_H + 18, label)
    failed = [row["label"] for row in results if not row["ok"]]
    # Dem tra bang so: grab nao gan trang ran thi o do khong co gi de xem, va mot
    # anh chung minh toan den la anh GIA. Do ca o bang dung thuoc do o 2.
    blank_cells = [label for label, shot in cells
                   if opaque_fraction(shot) < 0.01]
    check("anh co du 4 o va khong o nao trang ran", len(blank_cells), 0)
    painter.setPen(QColor("#EF4444" if failed else "#7DD3A0"))
    painter.setFont(QFont("Consolas", 9))
    painter.drawText(GAP, canvas_h - 18,
                     "%d/%d phep do PASS | failed: %s" %
                     (len(results) - len(failed), len(results),
                      ", ".join(failed) or "khong co"))
    painter.end()
    canvas.save(OUT)

    with open(JSON_OUT, "w", encoding="utf-8") as handle:
        json.dump({"png": os.path.basename(OUT), "checks": results,
                   "failed": failed,
                   "measure": {"tone_switch_s": {
                       "truoc": before_switch, "tach": after_switch,
                       "dich_1s": moved_switch, "hoan_tac": undo_switch},
                       "rms_full": {"truoc": rms(before, 0, 5, before_rate),
                                    "tach": rms(after, 0, 5, after_rate),
                                    "dich_1s": rms(moved_samples, 0, 5,
                                                   moved_rate),
                                    "hoan_tac": rms(undo_samples, 0, 5,
                                                    undo_rate)},
                       "wav": [os.path.basename(p) for p in
                               (before_path, after_path, moved_path,
                                undo_path)]}},
                  handle, ensure_ascii=False, indent=2)
    print("saved %s (%dx%d)" % (os.path.basename(OUT),
                                canvas.width(), canvas.height()))
    print("ALL PASS" if not failed else "CO %d KET QUA FAIL" % len(failed))
    shutil.rmtree(folder, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
