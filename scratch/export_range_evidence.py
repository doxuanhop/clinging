"""Anh cho dong selftest `vung xuat in/out + preset chat luong`.

Bon o, do trong MOT lan chay, dung CUNG thuoc do voi `diagnostics._export_range_ok`
(goi lai `diagnostics._frame_hue_track`, khong mo mot duong doan thong ke thu
hai — bai hoc `-shortest`):

  A. ExportDialog THAT o chieu cao SHIP nho nhat (1120x520), DA CUON TOI HAN,
     o ca hai che do: toan bo va vung 1,20->2,40. `lbl_duration` in dong ho
     mm:ss cho toan bo con CON SO (giay + khung hinh) cho vung in, va
     `lbl_format` in dung x264 preset + CRF cua lenh.
  B. Day frame: hai hang tren la 24 khung cua file toan bo, hang duoi la 12
     khung cua file vung. So duoi moi o = lech goc mau voi khung tuong ung.
     Lech theo CHI SO frame phai <= 15 do ("vung la cat cua toan bo"), lech
     voi 12 khung DAU phai > 20 do ("hai nua nguon khong giong nhau").
  C. Nam lan xuat THAT qua RenderWorker, do lai bang ffprobe `-count_frames`
     (so khung hinh THAT giai ma duoc) va `os.path.getsize`.
  D. RMS cua hai cua so nam trong doan co tieng: 0->0,6 s (am) va 0,6->1,2 s
     (tam). Do la bang chung `-ss` cua export_range nam trong lenh xuat video,
     chu khong chi trong doan mp3 sidecar.

```bash
python scratch/export_range_evidence.py
```
Mo `scratch/export_range_evidence.png` ra XEM — log PASS khong phai bang chung.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PNG = os.path.join(ROOT, "scratch", "export_range_evidence.png")
JSON_OUT = os.path.join(ROOT, "scratch", "export_range_evidence.json")
SHOT_FULL = os.path.join(ROOT, "scratch", "_xre_dialog_full.png")
SHOT_WIN = os.path.join(ROOT, "scratch", "_xre_dialog_window.png")

FPS = 10
WIDTH, HEIGHT = 256, 144
LOUD, QUIET = 1.2, 1.2
TOTAL = LOUD + QUIET
RAMP = 0.6

CHECKS = []


def truthy(name, ok, detail=""):
    CHECKS.append((name, bool(ok), str(detail)))
    print("%-46s %s  %s" % (name, "PASS" if ok else "FAIL", detail))


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=300, check=False,
                          creationflags=0x08000000 if os.name == "nt" else 0)


def main():
    import diagnostics
    from core import export_range, external_tools
    from core.timeline_model import TimelineModel, TrackType

    ffmpeg = external_tools.find("ffmpeg")
    ffprobe = external_tools.find("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit(external_tools.missing_message("ffmpeg"))

    def measure(path):
        probe = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                     "-count_frames", "-show_entries",
                     "stream=nb_read_frames:format=duration", "-of",
                     "default=nw=1", path])
        frames = seconds = 0
        for line in probe.stdout.decode("utf-8", "replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "nb_read_frames":
                frames = int(float(value or 0))
            elif key.strip() == "duration":
                seconds = float(value or 0.0)
        return frames, seconds, os.path.getsize(path)

    def rms(path):
        proc = run([ffmpeg, "-v", "error", "-i", path, "-vn", "-ac", "1",
                    "-ar", "8000", "-f", "f32le", "-"])
        if proc.returncode != 0 or not proc.stdout:
            return None
        import numpy as np
        data = np.frombuffer(proc.stdout, np.float32)
        return float(np.sqrt(np.mean(data.astype(np.float64) ** 2))) if data.size else None

    folder = tempfile.mkdtemp(prefix="xre_")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])

    try:
        # ── fixture: nhu het diagnostics._export_range_ok ──
        loud = os.path.join(folder, "dau.mp4")
        quiet = os.path.join(folder, "cuoi.mp4")
        make = run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x120:rate=25:duration=%g,hue=h=t*60" % TOTAL,
                    "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=%g,"
                    "volume=volume='if(lt(t,%g),1.0,0.02)':eval=frame"
                    % (LOUD, RAMP),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-t", "%.6f" % TOTAL, loud])
        truthy("fixture co tieng", make.returncode == 0 and os.path.isfile(loud),
               make.stderr.decode("utf-8", "replace")[-90:])
        make = run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x120:rate=25:duration=%g,hue=h=72+t*60" % QUIET,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-an", quiet])
        truthy("fixture im lang", make.returncode == 0 and os.path.isfile(quiet),
               make.stderr.decode("utf-8", "replace")[-90:])

        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.VIDEO)
        model.add_clip(track.track_id, loud, "video", 0.0, LOUD, "dau")
        model.add_clip(track.track_id, quiet, "video", LOUD, QUIET, "cuoi")

        # ── A. ExportDialog THAT, hai che do, da cuon toi han ──
        from PySide6.QtCore import QPoint
        from ui.export_dialog import ExportDialog, RenderWorker

        dialog = ExportDialog(model)
        dialog.resize(1120, 520)
        dialog.show()
        for _ in range(4):
            app.processEvents()
        scroll = dialog.content_scroll
        bar = scroll.verticalScrollBar()
        view_h = scroll.viewport().height()
        shots = {}
        for label, mode, frm, to in (("full", export_range.RANGE_FULL, 0.0, TOTAL),
                                     ("win", export_range.RANGE_WINDOW, LOUD, TOTAL)):
            dialog.combo_range.setCurrentIndex(dialog.combo_range.findData(mode))
            dialog.spin_from.setValue(frm)
            dialog.spin_to.setValue(to)
            dialog.combo_quality.setCurrentIndex(
                dialog.combo_quality.findData("can_bang"))
            bar.setValue(bar.maximum())
            for _ in range(4):
                app.processEvents()
            top = dialog.spin_to.mapTo(scroll.viewport(), QPoint(0, 0)).y()
            bottom = top + dialog.spin_to.height()
            truthy("A %s: o Den nam trong viewport" % label,
                   0 <= top and bottom <= view_h + 1,
                   "y %d..%d trong %d px, bar toi da %d" % (top, bottom, view_h,
                                                            bar.maximum()))
            path = SHOT_FULL if label == "full" else SHOT_WIN
            dialog.grab().save(path)
            shots[label] = (path, dialog.lbl_duration.text(),
                            dialog.lbl_format.text(), dialog._current_window(),
                            dialog._current_fps())
        dialog.close()
        dialog.deleteLater()
        for _ in range(2):
            app.processEvents()

        # Nhan do dai PHAI doi theo che do: vung in duoi 1 giay la hop le nen
        # mm:ss cua no in ra "00:00" ngay canh nut Xuat; do lan chay 22/10/2026
        # va do vet 15 trong scratch/export_range_counterfactual.py phan biet.
        win_w = shots["win"][3]
        truthy("A: che do vung in in do dai bang con so giay + khung hinh",
               ("%.2f s" % win_w["span"]) in shots["win"][1]
               and ("%d frame" % win_w["frames"]) in shots["win"][1]
               and "00:00" not in shots["win"][1],
               repr(shots["win"][1]))
        truthy("A: preset in dung CRF cua lenh", "CRF 21" in shots["win"][2],
               repr(shots["win"][2]))
        truthy("A: che do toan bo van dung dong ho mm:ss",
               "00:02" in shots["full"][1] and "frame" not in shots["full"][1],
               repr(shots["full"][1]))

        # ── C. nam lan xuat THAT ──
        def export(label, start, end, quality):
            out = os.path.join(folder, label + ".mp4")
            window = None
            if start is not None:
                window = export_range.resolve_window(start, end, model.duration, FPS)
            errors, done = [], []
            worker = RenderWorker(model, out, WIDTH, HEIGHT, FPS, "16:9", False,
                                  window=window, quality=quality)
            worker.errorOccurred.connect(errors.append)
            worker.finished_ok.connect(done.append)
            worker.run()
            if errors or not done:
                raise SystemExit("%s: RenderWorker bao loi %r" % (label, errors))
            frames, seconds, size = measure(out)
            return {"label": label, "frames": frames, "seconds": seconds,
                    "bytes": size, "rms": rms(out), "path": out,
                    "window": window}

        runs = [export("toan_bo", None, None, None),
                export("vung", LOUD, TOTAL, "cao"),
                export("vung_nhe", LOUD, TOTAL, "nhe"),
                export("tieng", 0.0, RAMP, "cao"),
                export("vung_cat", RAMP, LOUD, "cao")]
        by = {r["label"]: r for r in runs}
        truthy("C: toan bo giu du doan cuoi im lang",
               by["toan_bo"]["frames"] == int(TOTAL * FPS), by["toan_bo"])
        truthy("C: vung 1,2->2,4 = 12 frame",
               by["vung"]["frames"] == int(QUIET * FPS), by["vung"])
        truthy("C: preset doi byte cung noi dung",
               by["vung_nhe"]["bytes"] * 1.15 < by["vung"]["bytes"]
               and by["vung_nhe"]["frames"] == by["vung"]["frames"],
               "%d vs %d B" % (by["vung_nhe"]["bytes"], by["vung"]["bytes"]))

        # ── D. hai cua so co tieng ──
        truthy("D: tieng 0->0,6 = 6 frame 0,6 s",
               by["tieng"]["frames"] == int(RAMP * FPS)
               and abs(by["tieng"]["seconds"] - RAMP) <= 1.0 / FPS, by["tieng"])
        truthy("D: vung_cat 0,6->1,2 = 6 frame 0,6 s",
               by["vung_cat"]["frames"] == int(RAMP * FPS)
               and abs(by["vung_cat"]["seconds"] - RAMP) <= 1.0 / FPS,
               by["vung_cat"])
        ratio = (by["tieng"]["rms"] or 0.0) / max(by["vung_cat"]["rms"] or 0.0, 1e-9)
        truthy("D: -ss cat dung doan tam cua ramp",
               by["tieng"]["rms"] and by["vung_cat"]["rms"]
               and by["vung_cat"]["rms"] * 4.0 < by["tieng"]["rms"],
               "%.4f am vs %.4f tam (%.1fx)" % (by["tieng"]["rms"] or 0.0,
                                                by["vung_cat"]["rms"] or 0.0, ratio))

        # ── B. day frame, dung thuoc do cua gate ──
        dirs = {}
        for label in ("full", "win"):
            dirs[label] = os.path.join(folder, "frames_" + label)
            os.mkdir(dirs[label])
        full_hue = diagnostics._frame_hue_track(by["toan_bo"]["path"], dirs["full"])
        win_hue = diagnostics._frame_hue_track(by["vung"]["path"], dirs["win"])
        skip = int(LOUD * FPS)

        def angle(a, b):
            return round(min(abs(a - b), 360.0 - abs(a - b)), 1)

        cut = [angle(full_hue[skip + i], win_hue[i]) for i in range(len(win_hue))]
        head = [angle(full_hue[i], win_hue[i]) for i in range(len(win_hue))]
        truthy("B: vung = cat cua toan bo (moi frame)", max(cut) <= 15.0, cut)
        truthy("B: vung KHONG giong doan dau", min(head) > 20.0, head)
        truthy("B: du 24 + 12 khung giai ma duoc",
               len(full_hue) == int(TOTAL * FPS) and len(win_hue) == int(QUIET * FPS)
               and None not in full_hue and None not in win_hue,
               "%d + %d" % (len(full_hue), len(win_hue)))

        draw_sheet(by, shots, dirs, cut, head, full_hue, win_hue, ratio)
        with open(JSON_OUT, "w", encoding="utf-8") as handle:
            json.dump({"runs": [{k: v for k, v in r.items() if k != "path"}
                                for r in runs],
                       "hue_cut": cut, "hue_head": head,
                       "dialog": {k: v[1:3] for k, v in shots.items()},
                       "checks": CHECKS}, handle, ensure_ascii=False, indent=1)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    bad = [name for name, ok, _ in CHECKS if not ok]
    print("\n%d cua, %s" % (len(CHECKS), "ALL PASS" if not bad else "FAIL: "
                            + ", ".join(bad)))
    print(PNG)
    return 0 if not bad else 1


def draw_sheet(by, shots, dirs, cut, head, full_hue, win_hue, ratio):
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1560, 1380
    sheet = Image.new("RGB", (W, H), (18, 19, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
        small = ImageFont.truetype("arial.ttf", 12)
        big = ImageFont.truetype("arial.ttf", 19)
    except OSError:
        font = small = big = ImageFont.load_default()
    teal, white, dim = (64, 224, 208), (232, 234, 240), (150, 154, 166)
    good, bad = (120, 240, 160), (255, 96, 96)

    def panel(x, y, w, h, name):
        draw.rectangle([x, y, x + w, y + h], outline=(60, 62, 72))
        draw.text((x + 10, y + 6), name, fill=teal, font=big)

    def text(x, y, line, fill=white, use=None):
        draw.text((x, y), line, fill=fill, font=use or font)

    def paste(path, x, y, box_w):
        image = Image.open(path).convert("RGB")
        box_h = int(box_w * image.height / float(image.width))
        sheet.paste(image.resize((box_w, box_h), Image.LANCZOS), (x, y))
        draw.rectangle([x - 1, y - 1, x + box_w + 1, y + box_h + 1],
                       outline=(90, 94, 106))
        return box_h

    text(20, 10, "Xuat theo vung in/out + preset - moi con so do trong lan "
                 "chay nay (scratch/export_range_evidence.py)", teal, big)

    # Panel A phai cao du cho HAI dong nhan nam duoi anh 700 px (anh 325 px
    # bat dau tu y=76 -> nhan cuoi o 441): ban 1330 px de nhan tran ra ngoai
    # va de duong len nhau voi tieu de B.
    panel(20, 40, 1520, 420, "A. ExportDialog that, 1120x520, da cuon toi han")
    for column, key, caption in ((0, "full", "che do TOAN BO @%d fps"),
                                 (1, "win", "che do VUNG 1,20 -> 2,40 @%d fps")):
        x = 40 + column * 760
        h = paste(shots[key][0], x, 76, 700)
        text(x, 76 + h + 6, caption % shots[key][4], dim, small)
        text(x, 76 + h + 24, shots[key][1], white, small)
        text(x, 76 + h + 40, shots[key][2], white, small)

    panel(20, 472, 1520, 456, "B. 24 khung file toan bo (hai hang tren) va 12 "
                              "khung file vung (hang duoi)")
    cw, ch, gap = 116, 66, 8
    y0 = 510
    rows = (("toan bo frame 0..11", [(os.path.join(dirs["full"], "f%03d.png" % (i + 1)),
                                     full_hue[i], None) for i in range(12)]),
            ("toan bo frame 12..23", [(os.path.join(dirs["full"], "f%03d.png" % (i + 13)),
                                       full_hue[i + 12], cut[i]) for i in range(12)]),
            ("vung frame 0..11", [(os.path.join(dirs["win"], "f%03d.png" % (i + 1)),
                                  win_hue[i], head[i]) for i in range(12)]))
    for r, (name, cells) in enumerate(rows):
        y = y0 + r * 118
        text(36, y - 14, name, dim, small)
        for i, (path, hue, delta) in enumerate(cells):
            x = 36 + i * (cw + gap)
            paste(path, x, y, cw)
            text(x + 2, y + ch + 4, "hue %.0f" % hue, dim, small)
            if delta is not None:
                text(x + 2, y + ch + 18,
                     ("cat %.1f" if r == 1 else "dau %.1f") % delta,
                     good if (r == 1) == (delta <= 15.0) else bad, small)
    text(36, y0 + 3 * 118 - 8,
         "dong 'cat' = lech voi khung cung chi so cua file toan bo (phai <= 15); "
         "dong 'dau' = lech voi 12 khung DAU (phai > 20)", dim, small)

    panel(20, 940, 900, 420, "C. ffprobe -count_frames tren file ra")
    y = 976
    for label, note in (("toan_bo", "duong MAC DINH, window=None"),
                        ("vung", "1,2->2,4, CRF 18"),
                        ("vung_nhe", "1,2->2,4, CRF 24"),
                        ("tieng", "0->0,6 (doan AM)"),
                        ("vung_cat", "0,6->1,2 (doan TAM)")):
        r = by[label]
        text(40, y, "%-9s %2d frame  %5.2fs  %7d B  rms %s" %
             (label, r["frames"], r["seconds"], r["bytes"],
              ("%.4f" % r["rms"]) if r["rms"] is not None else "-"), white, font)
        text(560, y, note, dim, small)
        y += 26
    y += 12
    text(40, y, "toan_bo van 24 frame: doan cuoi KHONG co tieng nhung khong bi "
                "an nua (-shortest da di)", dim, small)
    y += 22
    text(40, y, "vung_nhe cung %d frame nhu vung, it hon %d B (%.0f%%)" %
         (by["vung"]["frames"], by["vung"]["bytes"] - by["vung_nhe"]["bytes"],
          by["vung_nhe"]["bytes"] / float(by["vung"]["bytes"]) * 100.0),
         good, small)

    panel(940, 940, 600, 420, "D. RMS hai cua so trong doan co tieng")
    y = 976
    text(960, y, "ramp: sine 440 Hz gain 1,0 den 0,6s roi 0,02", dim, small)
    y += 24
    text(960, y, "tieng    0,0->0,6 s  rms %.4f" % (by["tieng"]["rms"] or 0.0),
         white, small)
    y += 24
    text(960, y, "vung_cat 0,6->1,2 s  rms %.4f" % (by["vung_cat"]["rms"] or 0.0),
         white, small)
    y += 24
    text(960, y, "ty le %.1fx (gate doi >= 4x)" % ratio, good, small)
    y += 30
    for line in ("day la phep thu DUY NHAT do duoc `-ss` cua export_range di qua",
                 "lenh xuat video: co_names nhin thay no qua duong mp3 sidecar",
                 "nen mot vet xoa `-ss` o duong video chi lo ra o day.",
                 "",
                 "khong co ramp thi hai con so bang nhau va phep thu vo nghia -",
                 "vet `fixture_khong_con_ramp` trong phan chung do chinh dieu do."):
        text(960, y, line, dim if line else white, small)
        y += 20

    sheet.save(PNG)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.exit(main())
