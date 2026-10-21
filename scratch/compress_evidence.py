"""Anh chung minh + duong UI that cho nhom nen/toi uu tep.

Bon dieu selftest khong the noi (diagnostics chi goi ham core, khong mo hop
thoai): (1) card video trong Thu vien co dung mot hanh "Nen / toi uu tep" con
card audio THI KHONG — gate `kind == "video"` la that, khong phai chu;
(2) bam hanh dong ay sinh ra hop thoai THAT cua `ui.compress_dialog` voi dung
nguoi duoc bam; (3) thang do ve ra co pixel, khong phai mot khung trong;
(4) moi con so tren SHEET la do tu mot lan chay that, khong phai so cua tai lieu.

Fixture ty sinh trong scratch/ (6 s 1280x720, cung cong thuc ma
scratch/compress_cost_probe.py dung nen so so sanh duoc), khong dung video cua
nguoi dung, `AUTO_SAVE_FILE` chi ra tam, rac xoa o finally. Mot lan bi cat giua
chung thi `_compress_ev_*` con sot trong scratch/ — lan chay sau bao cho duoc
het, va sheet `*_evidence.png` luu lai de mo ra xem.

```bash
python -u scratch/compress_evidence.py
```
"""

import ctypes
import gc
import os
import shutil
import subprocess
import sys
import time

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

import core.project_storage as project_storage

PREFIX = os.path.join(OUT, "_compress_ev")
SRC = PREFIX + "_src.mp4"
WAV = PREFIX + "_audio.wav"
AUTOSAVE = PREFIX + "_autosave.json"
SHOT_REMUX = PREFIX + "_dialog_remux.png"
SHOT_VP9 = PREFIX + "_dialog_vp9.png"
SHOT_BLOCKED = PREFIX + "_dialog_blocked.png"
SHEET = PREFIX + "_evidence.png"

fails = []
runs = []
notes = {}


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-58s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def truthy(label, value, detail=""):
    ok = bool(value)
    if not ok:
        fails.append("%s: %s" % (label, detail or "False"))
    print("%-58s %s %s" % (label, "PASS" if ok else "FAIL", detail))
    return ok


def fmt_bytes(value):
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB"):
        if size < 1024.0 or unit == "MB":
            return ("%d B" % size) if unit == "B" else ("%.1f %s" % (size, unit))
        size /= 1024.0
    return "%d B" % value


def build_fixtures():
    from core import external_tools
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        raise SystemExit("khong tim thay ffmpeg trong bundle")
    video = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=1280x720:rate=25:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", SRC],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600)
    if video.returncode != 0 or not os.path.isfile(SRC) or \
            os.path.getsize(SRC) < 100_000:
        raise SystemExit("fixture video loi rc=%d %s"
                         % (video.returncode, video.stderr[-200:]))
    # Card audio chi de doi chieu menu (gate `kind == "video"`), nen wav can
    # dung nen PCM: `aac` trong container `wav` bi ffmpeg tu choi.
    sound = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=330:duration=2", "-c:a", "pcm_s16le", WAV],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300)
    if sound.returncode != 0 or os.path.getsize(WAV) < 1000:
        raise SystemExit("fixture audio loi rc=%d" % sound.returncode)


def alpha_count(pixmap):
    """Dem pixel co alpha — mot hop thoai chua nap style van grab duoc va bao
    thanh cong, nen khong the chi kiem file PNG ton tai."""
    from PySide6.QtGui import QImage
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    stride = image.bytesPerLine() // 4
    arr = np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), stride, 4)
    return int((arr[..., 3] > 10).sum())


def shot(dialog, path):
    pixmap = dialog.grab()
    pixmap.save(path, "PNG")
    return alpha_count(pixmap)


def measure_runs():
    """Ba kieu nen chay THAT qua chinh `compress_file` ma hop thoai goi."""
    from core import external_tools
    from core import media_compress as compress
    ffmpeg = external_tools.find("ffmpeg")
    facts = compress.source_facts(SRC)
    notes["src"] = facts
    notes["src_atoms"] = [name for name, _ in compress.top_level_atoms(SRC)]
    # Canary: fixture phai CHUA faststart. Neu no da faststart thi ca phep
    # "remux day moov len dau" xanh ma khong can lam gi.
    truthy("canary: fixture chua faststart", not compress.is_faststart(SRC),
           "atoms=%s" % ">".join(notes["src_atoms"]))
    cases = ((compress.MODE_REMUX, "remux (copy luong)", None, None, ".mp4"),
             (compress.MODE_X264, "x264 CRF 28 veryfast", 28, "veryfast", ".mp4"),
             # preset = None de build_command tu lay DEFAULT_PRESET — do 21/10/2026
             # tren may nay (8 CPU logich) `-cpu-used 8` chay 29,68 s ma ra cung
             # 1.861.055 B nhu `5` (26,45 s), nen vet thu ba phai la mac dinh ban
             # ra, khong phai con so do hon.
             (compress.MODE_VP9, "vp9 CRF 33 cpu-used 5 (mac dinh)", 33, None,
              ".webm"))
    for mode, label, crf, preset, extension in cases:
        output = "%s_%s%s" % (PREFIX, mode, extension)
        started = time.perf_counter()
        result = compress.compress_file(SRC, output, mode=mode, crf=crf,
                                        preset=preset)
        seconds = time.perf_counter() - started
        if not result["ok"]:
            fails.append("chay that %s that bai: %s" % (mode, result["error"]))
            continue
        atoms = [name for name, _ in compress.top_level_atoms(output)]
        # `top_level_atoms` la doc header 8 byte kieu MP4. Cho no vao mot file
        # .webm thi no doc the EBML thanh ten atom lung tung — in ra la NOI DO,
        # nen chi doc o container ma `+faststart` co nghia.
        mp4_like = extension in compress.FASTSTART_CONTAINERS
        atom_text = ">".join(atoms) if mp4_like else "n/a (webm khong co moov)"
        fast = compress.is_faststart(output) if mp4_like else "n/a"
        out_duration = compress.source_facts(output)["duration"]
        runs.append((label, seconds, result["input_bytes"],
                     result["output_bytes"], atom_text,
                     "%.3f->%.3f s faststart=%s" %
                     (result["duration_in"], out_duration, fast)))
        truthy("%s giu thoi luong" % mode,
               abs(out_duration - result["duration_in"]) < 0.15,
               "%.3f vs %.3f" % (out_duration, result["duration_in"]))
        if mode == compress.MODE_REMUX:
            truthy("remux DOI thu tu atom: moov truoc mdat",
                   compress.is_faststart(output), ">".join(atoms))
        if mode == compress.MODE_X264:
            truthy("x264 CRF 28 nhe hon nguon",
                   result["output_bytes"] < result["input_bytes"],
                   "%s -> %s" % (fmt_bytes(result["input_bytes"]),
                                 fmt_bytes(result["output_bytes"])))
    commands = {}
    for mode, extension in ((compress.MODE_REMUX, ".mp4"),
                            (compress.MODE_X264, ".mp4"),
                            (compress.MODE_X265, ".mp4"),
                            (compress.MODE_VP9, ".webm")):
        commands[mode] = compress.build_command(ffmpeg, SRC,
                                                PREFIX + "_lenh" + extension, mode)
    joined = {mode: " ".join(cmd) for mode, cmd in commands.items()}
    truthy("lenh remux co +faststart", "-movflags +faststart" in joined["remux"])
    truthy("lenh vp9 KHONG co -preset", "-preset" not in joined["vp9"])
    truthy("lenh vp9 co -cpu-used va -b:v 0",
           "-cpu-used" in joined["vp9"] and "-b:v 0" in joined["vp9"],
           joined["vp9"][:70])
    truthy("lenh x265 trong mp4 co tag hvc1", "-tag:v hvc1" in joined["x265"])
    truthy("lenh mkv copy phu de",
           "-c:s copy" in " ".join(compress.build_command(
               ffmpeg, SRC, PREFIX + "_lenh.mkv", compress.MODE_X264)))
    return joined


def block_legs():
    """To hop vo nghia phai dung thanh lenh truoc khi kip lay ffmpeg chay."""
    from core import media_compress as compress
    webm = PREFIX + "_x264.webm"
    result = compress.compress_file(SRC, webm, mode=compress.MODE_X264)
    notes["blocked"] = result["error"]
    truthy("x264 ra webm bi chan bang cau doc duoc", bool(result["error"]),
           result["error"][:70])
    truthy("x264 ra webm khong de lai file", not os.path.exists(webm))
    # Chieu thu hai cua bang: `remux` khong chon encoder nen phai do codec cua
    # NGUON. h264 khong nam trong webm — khong chan thi nguoi dung co mot file
    # khong phat duoc va tuong da toi uu xong.
    remux_bad = compress.pair_error(PREFIX + "_r.webm", compress.MODE_REMUX,
                                    "h264")
    truthy("remux nguon h264 ra webm bi chan (chieu codec nguon)",
           bool(remux_bad), remux_bad[:70])
    check("mkv nhan moi codec",
          compress.pair_error(PREFIX + ".mkv", compress.MODE_REMUX, "h264"), "")
    return (compress.container_choices(compress.MODE_X264),
            compress.container_choices(compress.MODE_VP9))


def menu_titles(card):
    return [action.text() for action in card.context_menu().actions()]


def gate_ui(win, app):
    """Toan bo duong vao: card -> menu -> hanh dong -> hop thoai cua MainWindow."""
    from ui.library_panel import ResourceCard
    from core import media_compress as compress

    panel = win.library_panel
    video_card = panel.add_resource(os.path.basename(SRC), "video", SRC)
    audio_card = panel.add_resource(os.path.basename(WAV), "audio", WAV)
    truthy("card video tao qua duong that cua LibraryPanel",
           isinstance(video_card, ResourceCard))

    notes["video_menu"] = menu_titles(video_card)
    notes["audio_menu"] = menu_titles(audio_card)
    truthy("menu video co hanh Nen / toi uu",
           any("Nén" in title and "tối ưu" in title for title in
               notes["video_menu"]), " | ".join(notes["video_menu"]))
    truthy("menu audio KHONG co hanh Nen (gate kind == video)",
           not any("Nén" in title for title in notes["audio_menu"]),
           " | ".join(notes["audio_menu"]))

    compress_action = next(item for item in video_card.context_menu().actions()
                           if "Nén" in item.text())
    compress_action.trigger()
    for _ in range(8):
        app.processEvents()
    dialog = getattr(win, "_compress_dialog", None)
    truthy("bam menu sinh CompressDialog cua MainWindow",
           dialog is not None and dialog.isVisible(), repr(dialog is not None))
    check("hop thoai chon dung nguoi bam", dialog._current_source(), SRC)
    check("mac dinh la kieu remux", dialog._current_mode(), compress.MODE_REMUX)
    check("nut Nen dang bat", dialog.btn_run.isEnabled(), True)

    notes["summary_remux"] = dialog.lbl_summary.text()
    truthy("tom tat remux noi khong ma hoa lai",
           "Không mã hoá lại" in dialog.lbl_summary.text(),
           dialog.lbl_summary.text().replace("\n", " / ")[:90])
    notes["px_remux"] = shot(dialog, SHOT_REMUX)

    # VP9: thang toc do PHAI doi thanh cpu-used va duoi goi y doi sang .webm.
    # Gui `-preset` cho libvpx-vp9 thi ffmpeg bao "Invalid preset".
    vp9_index = next(i for i in range(dialog.combo_mode.count())
                     if dialog.combo_mode.itemData(i) == compress.MODE_VP9)
    dialog.combo_mode.setCurrentIndex(vp9_index)
    app.processEvents()
    check("vp9 do thang toc do thanh cpu-used",
          dialog.combo_preset.currentText().startswith("cpu-used"), True)
    check("vp9 mac dinh -cpu-used 5", dialog.combo_preset.currentData(),
          compress.DEFAULT_PRESET[compress.MODE_VP9])
    truthy("goi y file vp9 doi duoi .webm",
           dialog.edit_out.text().lower().endswith(".webm"),
           os.path.basename(dialog.edit_out.text()))
    notes["summary_vp9"] = dialog.lbl_summary.text()
    truthy("tom tat vp9 co uoc luong thoi gian may nay",
           "ước tính" in dialog.lbl_summary.text(),
           dialog.lbl_summary.text().replace("\n", " / ")[:90])
    notes["px_vp9"] = shot(dialog, SHOT_VP9)

    # x264 ghi ra .webm: hop thoai phai in ra cau chan, va bam Nen cung khong
    # duoc phep sinh file.
    x264_index = next(i for i in range(dialog.combo_mode.count())
                      if dialog.combo_mode.itemData(i) == compress.MODE_X264)
    dialog.combo_mode.setCurrentIndex(x264_index)
    app.processEvents()
    wrong = PREFIX + "_tu_ui.webm"
    dialog.edit_out.setText(wrong)
    dialog._update_summary()
    app.processEvents()
    notes["summary_blocked"] = dialog.lbl_summary.text()
    truthy("hop thoai hien loi chan to hop",
           "không ghi được" in dialog.lbl_summary.text(),
           dialog.lbl_summary.text().replace("\n", " / ")[-90:])
    notes["px_blocked"] = shot(dialog, SHOT_BLOCKED)
    dialog._on_run()
    for _ in range(6):
        app.processEvents()
    truthy("bam Nen khi bi chan khong chay ffmpeg",
           not os.path.exists(wrong) and not dialog._busy,
           dialog.lbl_status.text()[:70])
    dialog.reject()
    win._compress_dialog = None
    panel.clear_resources()
    app.processEvents()
    for name, path in (("remux", SHOT_REMUX), ("vp9", SHOT_VP9),
                       ("blocked", SHOT_BLOCKED)):
        truthy("grab %s co noi dung (%d pixel)" % (name, notes["px_" + name]),
               notes["px_" + name] > 40000, os.path.basename(path))


def draw_sheet(joined, choices_x264, choices_vp9):
    from PIL import Image, ImageDraw, ImageFont
    width, height = 1560, 1290
    sheet = Image.new("RGB", (width, height), (18, 19, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
        small = ImageFont.truetype("arial.ttf", 13)
        big = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font = small = big = ImageFont.load_default()
    teal, white, dim = (64, 224, 208), (232, 234, 240), (150, 154, 166)
    good, bad = (120, 240, 160), (255, 96, 96)

    def panel(x, y, w, h, name):
        draw.rectangle([x, y, x + w, y + h], outline=(60, 62, 72))
        draw.text((x + 12, y + 8), name, fill=teal, font=big)

    def text(x, y, line, fill=white, use=None):
        draw.text((x, y), line, fill=fill, font=use or font)

    def wrap(x, y, line, limit, fill=white, use=None, step=16):
        words, acc = line.split(), ""
        for word in words:
            trial = (acc + " " + word).strip()
            if len(trial) > limit and acc:
                text(x, y, acc, fill, use)
                y += step
                acc = word
            else:
                acc = trial
        if acc:
            text(x, y, acc, fill, use)
            y += step
        return y

    draw.text((24, 12), "Nen / toi uu tep video — moi con so do trong lan chay "
                        "nay, khong phai so tai lieu", fill=teal, font=big)

    panel(24, 48, 1512, 500, "A. CompressDialog that, mo tu menu cua card video")
    from PIL import Image as PILImage
    for column, (label, path, summary) in enumerate((
            ("remux (mac dinh)", SHOT_REMUX, notes["summary_remux"]),
            ("vp9: thang cpu-used + duoi goi y .webm", SHOT_VP9,
             notes["summary_vp9"]),
            ("x264 ghi ra .webm: chan truoc khi chay", SHOT_BLOCKED,
             notes["summary_blocked"]))):
        x = 44 + column * 500
        image = PILImage.open(path).convert("RGB")
        box_width = 400
        box_height = int(box_width * image.height / image.width)
        sheet.paste(image.resize((box_width, box_height), PILImage.LANCZOS),
                    (x, 92))
        draw.rectangle([x - 1, 91, x + box_width + 1, 92 + box_height + 1],
                       outline=(90, 94, 106))
        bottom = 92 + box_height
        text(x, bottom + 10, label, teal, small)
        wrap(x, bottom + 30, summary.replace("\n", " | "), 58, dim, small)

    panel(24, 564, 750, 340, "B. truoc/sau — stat + ffprobe, nguon %s"
          % fmt_bytes(notes["src"]["bytes"]))
    text(40, 600, "nguon              %10s  atom %s  faststart=False"
         % (fmt_bytes(notes["src"]["bytes"]), ">".join(notes["src_atoms"])),
         white, small)
    y = 628
    for label, seconds, in_bytes, out_bytes, atoms, detail in runs:
        ratio = out_bytes / float(in_bytes or 1) * 100.0
        text(40, y, "%-23s %10s  %+6.1f%%  %5.2fs" %
             (label, fmt_bytes(out_bytes), ratio - 100.0, seconds),
             good if out_bytes <= in_bytes else bad, small)
        y += 22
        text(64, y, "atom %s | %s" % (atoms, detail), dim, small)
        y += 34
    text(40, y + 2, "remux copy tung bit nen byte khong doi; chi khac THU TU "
                    "atom — do la toan bo loi ich cua no", dim, small)
    text(40, y + 26, "giay o cot cuoi la wall clock do tren may nay trong vong "
                     "nay, khong lay tu bang chi phi", dim, small)

    panel(798, 564, 738, 340, "C. lenh ffmpeg ma build_command sinh ra")
    y = 604
    for mode in ("remux", "x264", "x265", "vp9"):
        y = wrap(816, y, "%s: %s" % (mode, joined[mode]), 82, white, small)
        y += 4
    text(816, y + 2, "vp9 dung -cpu-used chu khong -preset; webm dung libopus "
                     "chu khong aac", dim, small)

    panel(24, 924, 750, 300, "D. duong vao va loi chan")
    text(40, 962, "menu card video : " + " | ".join(notes["video_menu"]), white,
         small)
    text(40, 990, "menu card audio : " + " | ".join(notes["audio_menu"]), dim,
         small)
    text(40, 1022, "duoi kieu x264 ghi duoc : " + ", ".join(choices_x264), white,
         small)
    text(40, 1050, "duoi kieu vp9 ghi duoc  : " + ", ".join(choices_vp9), white,
         small)
    ended = wrap(40, 1082, "loi chan to hop: " + notes["blocked"], 92, bad, small)
    filled = "%s  (khi bam Nen: %s)" % (
        "ffmpeg khong tao file" if not os.path.exists(PREFIX + "_x264.webm")
        else "CON SOT FILE DO", notes["summary_blocked"].replace("\n", " / ")[-40:])
    text(40, ended + 4, filled,
         good if not os.path.exists(PREFIX + "_x264.webm") else bad, small)

    panel(798, 924, 738, 300, "E. ba grab phai co pixel that")
    y = 964
    for name, path in (("remux", SHOT_REMUX), ("vp9", SHOT_VP9),
                       ("blocked", SHOT_BLOCKED)):
        count = notes["px_" + name]
        text(816, y, "%-9s %8d pixel da ve   %s" %
             (name, count, os.path.basename(path)),
             good if count > 40000 else bad, small)
        y += 26
    wrap(816, y + 10, "Mot hop thoai chua nap style van grab duoc ra file PNG "
                      "va van bao thanh cong — nen o day dem pixel alpha, "
                      "khong dem file ton tai.", 76, dim, small)

    text(24, height - 30, "san sinh boi scratch/compress_evidence.py", dim, small)
    sheet.save(SHEET, "PNG")
    size = os.path.getsize(SHEET)
    truthy("sheet da luu, du lon", size > 60000, "%s (%s)" % (SHEET,
                                                              fmt_bytes(size)))
    print("ANH: %s" % SHEET)


def cleanup(win, app):
    from PySide6.QtCore import QUrl
    from core.frame_composer import FrameComposer
    from core.media_frame import SequentialVideoReader
    for obj in gc.get_objects():
        if isinstance(obj, (SequentialVideoReader, FrameComposer)):
            try:
                obj.close()
            except Exception:
                pass
    for reader in getattr(win, "_video_readers", {}).values():
        try:
            reader.close()
        except Exception:
            pass
    getattr(win, "_video_readers", {}).clear()
    try:
        win._audio_player.stop()
        win._audio_player.setSource(QUrl())
    except Exception:
        pass
    win.close()
    app.processEvents()
    gc.collect()


def sweep_rac():
    """Rac cua CHINH probe nay, giu lai sheet de mo ra xem. Lan chay truoc bi
    cat giua chung de lai doan video dang chay — lan nay xoa het.

    Tra (da_xoa, con_sot): `con_sot` KHONG duoc phep in, phai tính la FAIL."""
    keep = {os.path.basename(SHEET)}
    deleted, leftovers = [], []
    for name in sorted(os.listdir(OUT)):
        if not name.startswith("_compress_ev_") or name in keep:
            continue
        path = os.path.join(OUT, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            continue
        for _ in range(20):
            if not os.path.exists(path):
                break
            try:
                os.remove(path)
            except OSError:
                gc.collect()
                time.sleep(0.1)
        (leftovers if os.path.exists(path) else deleted).append(name)
    return deleted, leftovers


def main():
    project_storage.AUTO_SAVE_FILE = AUTOSAVE
    deleted, stubborn = sweep_rac()
    if deleted:
        print("xoa %d rac con sot tu lan chay truoc" % len(deleted))
    if stubborn:
        raise SystemExit("rac lan truoc van bi khoa: %s" % ", ".join(stubborn))
    build_fixtures()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    for _ in range(12):
        app.processEvents()
    try:
        joined = measure_runs()
        choices_x264, choices_vp9 = block_legs()
        gate_ui(win, app)
        draw_sheet(joined, choices_x264, choices_vp9)
    finally:
        cleanup(win, app)
        deleted, left = sweep_rac()
        if left:
            fails.append("rac probe con sot: %s" % ", ".join(left))

    if fails:
        print("\nFAILURES:")
        for line in fails:
            print("  -", line)
        return 1
    print("\nALL PASS: nen tep — 3 lan chay that, 3 grab day pixel, "
          "menu video va audio phan biet nhau")
    return 0


if __name__ == "__main__":
    sys.exit(main())
