"""End-to-end Auto Captions probe: real ASR run through the dialog's worker
thread, clips on the Timeline, undo, and a rendered frame per caption.

Usage: QT_QPA_PLATFORM=windows python scratch/captions_probe.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")

MEDIA = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
W, H = 640, 360
# Bcut nhận dạng cả bài hát ~2 phút; giữ nguyên 30s để không phải chờ lại mạng.
CACHE = os.path.join(OUT, "captions_segments.json")

# Bảng chữ Trung Quốc/Nhật trong transcript không in được ra console cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from core import auto_captions
from core.frame_composer import FrameComposer
from core.timeline_model import TrackType

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))


def caption_clips(model):
    return [clip for track in model.tracks if track.track_type == TrackType.TEXT
            for clip in track.clips]


def main():
    app = QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    check("system ffmpeg found", bool(auto_captions.ffmpeg_path()), True)
    check("mp4 needs conversion before upload",
          auto_captions.needs_audio_conversion(MEDIA), True)
    mp3 = auto_captions.extract_audio(MEDIA)
    check("audio excerpt exists and is non-empty",
          os.path.exists(mp3) and os.path.getsize(mp3) > 1000, True)
    print("  excerpt:", mp3, os.path.getsize(mp3), "bytes")

    from ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1680, 940)
    model = win.timeline_panel.model
    model.project_ratio = "16:9"
    video_track = model.add_track(TrackType.VIDEO, "Main")
    clip = model.add_clip(video_track.track_id, MEDIA, "video", 0.0, 30.0, "source.mp4")

    dialog = win._open_auto_captions()
    check("dialog lists the timeline source",
          dialog.combo_source.currentData() == MEDIA, True)
    dialog.combo_engine.setCurrentText("Bcut (Bilibili)")
    dialog.check_file.setChecked(True)
    dialog.check_timeline.setChecked(True)

    cached = None
    if os.path.exists(CACHE):
        import json
        with open(CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)

    if cached is None:
        # Đường đi thật: worker thread -> Bcut -> signal queued về GUI thread
        dialog._on_run()
        deadline = time.time() + 300
        while time.time() < deadline and not dialog._segments and dialog._busy:
            app.processEvents()
            time.sleep(0.05)
        app.processEvents()
        if dialog._segments:
            import json
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(dialog._segments, f, ensure_ascii=False)
    else:
        # Cùng một đoạn thẳng, nhưng phải qua đúng các bước GUI như khi chạy thật
        dialog._segments = []
        dialog._on_done(cached)
        for _ in range(5):
            app.processEvents()
    print("  transcript source:", "cache" if cached else "live Bcut run")

    segments = dialog._segments
    check("worker thread returned segments", len(segments) > 0, True)
    check("worker finished (not stuck busy)", dialog._busy, False)
    if not segments:
        print("  status text:", dialog.lbl_status.text())
        return 1

    print("  %d lines, first: %r" % (len(segments), segments[0]))
    for seg in segments[:5]:
        print("   %8.3f-%8.3f  %s" % (seg["start_ms"] / 1000.0,
                                       seg["end_ms"] / 1000.0, seg["text"]))

    # Kết quả phải nằm trên Timeline, đúng mốc, đúng kiểu phụ đề
    text_tracks = [tr for tr in model.tracks if tr.track_type == TrackType.TEXT]
    check("captions stay on one text lane", len(text_tracks), 1)
    created = caption_clips(model)
    check("caption clips landed on a text track", len(created), len(segments))
    check("table mirrors the transcript", dialog.table.rowCount(), len(segments))

    want = sorted((round(s, 2), t) for s, _d, t in auto_captions._plan(segments))
    got = sorted((round(c.start_time, 2), c.name) for c in created)
    check("every line sits at its own time with its own text", got == want, True)
    check("captions never overlap (no collision lane)",
          all(created[i].end_time <= created[i + 1].start_time + 1e-6
              for i in range(len(created) - 1)), True)
    if created:
        first = min(created, key=lambda c: c.start_time)
        check("caption text is non-empty", bool(first.name.strip()), True)
        check("caption uses the shared text style", first.font_size,
              auto_captions.DEFAULT_STYLE["font_size"])
        check("caption sits at the bottom of the frame",
              first.transform.y > 0, True)

    # Một bước undo phải dọn sạch cả loạt
    win.timeline_panel.undo_stack.undo()
    check("one undo removes every caption", len(caption_clips(model)), 0)
    win.timeline_panel.undo_stack.redo()
    check("redo restores every caption", len(caption_clips(model)), len(segments))

    # File phụ đề ghi ra thật
    written = dialog._write_file(segments, MEDIA)
    check("subtitle file written", os.path.exists(written) and
          os.path.getsize(written) > 0, True)
    print("  wrote", written)
    with open(written, "r", encoding="utf-8") as f:
        head = f.read(160).replace("\n", " | ")
    print("  head:", head)

    # Bằng chứng nhìn được: khung hình dựng thật, có chữ phụ đề đè lên video
    tiles = []
    for c in sorted(created, key=lambda c: c.start_time)[:6]:
        t = c.start_time + c.duration / 2.0
        tiles.append((t, c.name, export_frame(model, t)))
    strip = build_strip(tiles)
    path = os.path.join(OUT, "captions_evidence.png")
    strip.save(path)
    print("  saved", path)

    dialog.grab().save(os.path.join(OUT, "captions_dialog.png"))
    print("  saved captions_dialog.png")

    # Đường menu thật: phát signal phải mở được hộp thoại
    win.title_bar.autoCaptionsRequested.emit()
    opened = getattr(win, "_captions_dialog", None)
    check("menu action opens the captions dialog",
          opened is not None and opened.isVisible(), True)
    check("menu reuses the same dialog", opened is dialog, True)
    opened.hide()

    # Dong theo thu tu truoc khi ra: nếu cửa sổ còn sống tới lúc interpreter
    # shutdown, PySide6 huy C++ object sai thu tu va proc chet bang
    # 0xC0000409 (bash quy ra rc=127) du MOI GATE deu PASS — exit code luc do
    # khong con noi len noi dung probe nua.
    dialog.deleteLater()
    win.close()
    for _ in range(8):
        app.processEvents()

    print("\nsummary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
    return 1 if fails else 0


def export_frame(model, t):
    composer = FrameComposer(model, W, H)
    try:
        return composer.render_frame(t)
    finally:
        composer.close()


def build_strip(tiles):
    from PySide6.QtGui import QColor, QFont
    tw, th = 320, 180
    cols = 2
    rows = -(-len(tiles) // cols)
    canvas = QImage(tw * cols, (th + 34) * rows, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor("#0B0C10"))
    p = QPainter(canvas)
    p.setPen(Qt.GlobalColor.white)
    p.setFont(QFont("Arial", 9))
    for i, (t, text, frame) in enumerate(tiles):
        x = (i % cols) * tw
        y = (i // cols) * (th + 34)
        p.drawImage(QRectF(x, y, tw, th),
                    frame.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        p.drawText(QRectF(x + 4, y + th + 2, tw - 8, 30),
                   Qt.AlignLeft | Qt.TextWordWrap, "t=%.2fs  %s" % (t, text[:60]))
    p.end()
    return canvas


if __name__ == "__main__":
    sys.exit(main())
