"""Phan chung cho nhom D (bo chinh mau) tren DUONG GIAO DIEN THAT.

Selftest đo pixel qua apply_color_effects; no khong chung minh duoc rang nguoi
dung bam nam núm thi sao. File nay dung MainWindow that (cung lop ma
`main._boot()` mo), keo slider that, bam nut "Chon .cube..." that (chi
QFileDialog duoc cho tra ve mot file tam trong scratch), va Ctrl+Z that.

Ba dieu de noi doi nhat o tang nay, va tuong ung voi ba gate:
  1. the le ra nhưng gia tri khong bao gio toi model  -> do clip.effects sau moi cu keo.
  2. model doi nhung khong lenh nao duoc day          -> do do sau cua undo_stack + Ctrl+Z.
  3. keo 20 nấc trong một lần = 20 buoc hoan tac      -> do so buoc sau mot dot keo le.

Khong fixture nguoi dung: moi media ty sinh trong scratch/, AUTO_SAVE_FILE chi ra
tam, media xoa trong finally.

Chay:
    python -u scratch/color_grading_ui_probe.py
"""

import gc
import json
import os
import sys
import ctypes
import time
import wave

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
from PySide6.QtWidgets import QApplication

import core.project_storage as project_storage
from core.clip_effects import GRADING_EFFECT_NAME, GRADING_IDENTITY
from core.timeline_model import TrackType

W, H = 640, 360
DUR = 4.0
A_RGB = (200, 30, 30)          # do ruong - hue quay no di, LUT swap doi no thanh lam

MP4 = os.path.join(OUT, "color_grading_ui_A.mp4")
PNG = os.path.join(OUT, "color_grading_ui_A.png")
WAV = os.path.join(OUT, "color_grading_ui_A.wav")
CUBE = os.path.join(OUT, "color_grading_ui_swap.cube")
AUTOSAVE = os.path.join(OUT, "color_grading_ui_autosave.json")
CLINQ = os.path.join(OUT, "color_grading_ui_project.clinq")

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-62s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def truthy(label, got):
    return check(label, bool(got), True)


# ── Media ty sinh ───────────────────────────────────────────────

def write_still_video(path, rgb, seconds=6.0, fps=12.0):
    import cv2
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:, :] = (rgb[2], rgb[1], rgb[0])
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for _ in range(int(seconds * fps)):
        writer.write(frame)
    writer.release()
    assert os.path.getsize(path) > 1000, path


def write_flat_png(path, rgb):
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(*rgb))
    assert img.save(path), path


def write_tone_wav(path, seconds=2.0):
    import math
    import struct
    rate = 8000
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        for i in range(int(seconds * rate)):
            f.writeframes(struct.pack(
                "<h", int(math.sin(2 * math.pi * 220 * i / rate) * 12000)))


def write_swap_cube(path, n=17):
    """.cube viet theo thu tu kenh LAM doi nhanh nhat, nen mot entry = (b, g, r)
    cua toa do (r, g, b). File nay hoan vi R va B: do thuan -> lam thuan.
    """
    lines = ["TITLE \"probe swap R/B\"", "LUT_3D_SIZE %d" % n,
             "DOMAIN_MIN 0.0", "DOMAIN_MAX 1.0", ""]
    for ri in range(n):
        for gi in range(n):
            for bi in range(n):
                r, g, b = ri / (n - 1.0), gi / (n - 1.0), bi / (n - 1.0)
                lines.append("%.6f %.6f %.6f" % (b, g, r))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ── Do anh ──────────────────────────────────────────────────────

def to_array(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    return np.frombuffer(raw, np.uint8).reshape(
        (img.height(), img.width(), 4)).astype(np.int16)


def preview_shot(win) -> np.ndarray:
    """Frame preview qua dung scene.render() cua CanvasClipItem - preview lan
    export deu di qua apply_color_effects nen do o day la do duong that.
    """
    scene = win.preview_panel.canvas.scene()
    rect = scene.sceneRect()
    cw, ch = int(rect.width()), int(rect.height())
    img = QImage(max(1, cw), max(1, ch), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    try:
        scene.render(painter, QRectF(0, 0, cw, ch), rect)
    finally:
        painter.end()
    return to_array(img)


def changed(a, b, threshold=8):
    return int((np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2) > threshold).sum())


# ── Dung model tren MainWindow that ─────────────────────────────

def depth(win):
    return len(win.timeline_panel.undo_stack._undo_stack)


def has_grading(clip):
    return any(e.name == GRADING_EFFECT_NAME for e in clip.effects)


def grading_params(clip):
    for e in clip.effects:
        if e.name == GRADING_EFFECT_NAME:
            merged = dict(GRADING_IDENTITY)
            merged.update(e.params or {})
            return merged
    return dict(GRADING_IDENTITY)


def build_clips(win):
    """Video + anh + chu + audio, moi thu mot track, playhead nam giua clip video."""
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    win.timeline_panel.undo_stack.clear()
    vt = model.add_track(TrackType.VIDEO)
    it = model.add_track(TrackType.IMAGE)
    tt = model.add_track(TrackType.TEXT)
    at = model.add_track(TrackType.AUDIO)
    vid = model.add_clip(vt.track_id, MP4, "video", 0.0, DUR, "grade.mp4")
    # Anh va chu dat sau playhead: neu de chung che chop o thoi diem do, pixel
    # đo duoc la cua clip NAM TREN (chưa chỉnh), khong phai clip video mang bo
    # chinh mau - do la ly do lan dau tien gate nay bao "0 px doi".
    img = model.add_clip(it.track_id, PNG, "image", 20.0, DUR, "grade.png")
    txt = model.add_clip(tt.track_id, "", "text", 20.0, DUR, "chu")
    aud = model.add_clip(at.track_id, WAV, "audio", 0.0, DUR, "tone.wav")
    model.playhead = 1.0
    win._sync_canvas()
    QApplication.instance().processEvents()
    return model, vid, img, txt, aud


def open_editor(win, clip):
    win.properties_panel.show_clip_properties(clip)
    QApplication.instance().processEvents()
    return win.properties_panel.current_editor


def slider_of(editor, key):
    return editor._grading_widgets[key][0]


def label_of(editor, key):
    return editor._grading_widgets[key][1].text()


# ── Gate 1: the chi xuat hien tren clip ve ra pixel ─────────────

def gate_card_visibility(win):
    print("\n== the chi cho clip co pixel ==")
    model, vid, img, txt, aud = build_clips(win)
    seen = {}
    for label, clip in (("video", vid), ("image", img), ("text", txt),
                        ("audio", aud)):
        editor = open_editor(win, clip)
        seen[label] = not editor.card_grading.isHidden()
    check("video + anh co the, text + audio khong co the",
          seen, {"video": True, "image": True, "text": False, "audio": False})

    ov = model.add_track(TrackType.OVERLAY)
    sticker = model.add_clip(ov.track_id, PNG, "sticker", 0.0, DUR, "sticker.png")
    win._sync_canvas()
    editor = open_editor(win, sticker)
    truthy("sticker cung co the chinh mau", not editor.card_grading.isHidden())
    model.remove_clip(sticker.clip_id)
    win._sync_canvas()

    icon = editor.btn_lut.icon()
    pm = icon.pixmap(16, 16)
    arr = to_array(pm.toImage())
    truthy("nuit .cube co ve glyph (khong phai icon rong)",
           int((arr[:, :, 3] > 8).sum()) > 20)


# ── Gate 2: keo núm -> model -> preview, va Ctrl+Z ──────────────

def gate_hue_drag(win):
    print("\n== keo núm ton mau ==")
    model, vid, _img, _txt, _aud = build_clips(win)
    editor = open_editor(win, vid)
    before = preview_shot(win)
    d0 = depth(win)

    slider_of(editor, "hue_shift").setValue(45)
    QApplication.instance().processEvents()

    check("model nhan dung mot EffectData chinh mau", has_grading(vid), True)
    check("gia tri hue vao model", grading_params(vid)["hue_shift"], 45.0)
    check("do undo tang dung mot buoc", depth(win), d0 + 1)
    check("nhan tren the doi theo", label_of(editor, "hue_shift"), "+45°")

    after = preview_shot(win)
    lit = int((before[:, :, :3].max(axis=2) > 12).sum())
    truthy("preview co khung hinh truoc khi do (%d px sang)" % lit, lit > 1000)
    n = changed(before, after)
    truthy("preview doi pixel that (%d px)" % n, n > 1000)
    # Nguon do thuan: hue +45 khong lam luc thang the, no thu hep lech do-luc
    # (200,30,30 -> 166,115,0 do R-G tu 170 xuong 51). Do lech mean cua ca khung
    # hinh, khong do huong tong mau, de gate van dung tren nguon khac.
    gap_before = float((before[:, :, 0] - before[:, :, 1]).mean())
    gap_after = float((after[:, :, 0] - after[:, :, 1]).mean())
    truthy("hue +45 thu hep lech do-luc (%.1f -> %.1f)" % (gap_before, gap_after),
           gap_after < gap_before - 20)

    win._undo_step()
    QApplication.instance().processEvents()
    check("Ctrl+Z xoa het so duoi khoi model", has_grading(vid), False)
    check("Ctrl+Z tra núm ve 0 o panel", slider_of(editor, "hue_shift").value(), 0)
    check("Ctrl+Z tra nhan ve dinh", label_of(editor, "hue_shift"), "+0°")
    restored = preview_shot(win)
    check("Ctrl+Z tra preview ve dung khung hinh cu", changed(before, restored), 0)

    win._redo_step()
    QApplication.instance().processEvents()
    check("Ctrl+Y dat lai duoc bo chinh mau", grading_params(vid)["hue_shift"], 45.0)
    check("Ctrl+Y dat lai duoc preview", changed(before, preview_shot(win)) > 1000, True)
    win._undo_step()


# ── Gate 3: mot dot keo = mot buoc hoan tac ─────────────────────

def gate_merge(win):
    print("\n== gom nấc keo ==")
    model, vid, _img, _txt, _aud = build_clips(win)
    editor = open_editor(win, vid)
    d0 = depth(win)
    slider = slider_of(editor, "gamma")
    for value in (110, 125, 140, 155, 170):
        slider.setValue(value)
        QApplication.instance().processEvents()
    check("nam nấc gamma lien tiep = mot buoc undo", depth(win), d0 + 1)
    check("gamma luu con la gia tri cuoi", grading_params(vid)["gamma"], 1.70)
    win._undo_step()
    check("mot lan Ctrl+Z xoa ca dot keo", has_grading(vid), False)


# ── Gate 4: nut "Chon .cube..." that ────────────────────────────

class FakeDialog:
    """Chi thay getOpenFileName: moi thu khac trong QFileDialog van nguyen ban."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def getOpenFileName(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.answer, ""


def gate_lut_button(win, answer):
    print("\n== nut chon LUT ==")
    import PySide6.QtWidgets as qw
    real = qw.QFileDialog
    qw.QFileDialog = FakeDialog(answer)
    try:
        model, vid, _img, _txt, _aud = build_clips(win)
        editor = open_editor(win, vid)
        before = preview_shot(win)
        d0 = depth(win)
        editor.btn_lut.click()          # dung tin hieu clicked that cua nut
        QApplication.instance().processEvents()
    finally:
        qw.QFileDialog = real
    check("nut mo cua so va luu duong dan vao model",
          grading_params(vid)["lut_path"], os.path.normpath(answer))
    check("the hien ten file LUT", editor.lbl_lut_name.text(),
          os.path.basename(os.path.normpath(answer)))
    check("duong dan nam trong tooltip de doi chieu",
          editor.lbl_lut_name.toolTip(), os.path.normpath(answer))
    check("do undo tang mot", depth(win), d0 + 1)

    after = preview_shot(win)
    n = changed(before, after)
    truthy("LUT swap doi pixel preview (%d px)" % n, n > 1000)
    b_minus_r_before = float((before[:, :, 2] - before[:, :, 0]).mean())
    b_minus_r_after = float((after[:, :, 2] - after[:, :, 0]).mean())
    truthy("LUT swap keo kenh lam len tren kenh do (%.1f -> %.1f)" % (
        b_minus_r_before, b_minus_r_after), b_minus_r_after > b_minus_r_before + 20)

    win._undo_step()
    check("Ctrl+Z go bo LUT khoi model", grading_params(vid)["lut_path"], "")
    check("Ctrl+Z tra nhan LUT ve trong", editor.lbl_lut_name.text(),
          "(không dùng LUT)")
    check("Ctrl+Z tra preview ve dung khung cu", changed(before, preview_shot(win)), 0)


# ── Gate 5: nut "Ve mac dinh" ──────────────────────────────────

def gate_reset(win):
    print("\n== ve mac dinh ==")
    model, vid, _img, _txt, _aud = build_clips(win)
    editor = open_editor(win, vid)
    slider_of(editor, "hue_shift").setValue(90)
    slider_of(editor, "gain").setValue(150)
    QApplication.instance().processEvents()
    truthy("truoc khi reset co bo chinh mau", has_grading(vid))

    d0 = depth(win)
    editor.btn_grading_reset.click()
    QApplication.instance().processEvents()
    check("reset duoc day thanh mot buoc undo", depth(win), d0 + 1)
    check("reset ve trung tinh thi xoa EffectData (may cau hinh thap)",
          has_grading(vid), False)
    check("reset duoc luu ten trong history",
          "Chỉnh màu" in win.timeline_panel.undo_stack.undo_text, True)

    win._undo_step()
    check("Ctrl+Z cua reset tra lai bo so", grading_params(vid)["hue_shift"], 90.0)
    check("panel cung doc lai bo so", label_of(editor, "gain"), "1.50")
    editor.btn_grading_reset.click()


# ── Gate 6: doi clip la doi so ──────────────────────────────────

def gate_resync(win):
    print("\n== doi clip ==")
    model, vid, img, _txt, _aud = build_clips(win)
    e1 = open_editor(win, vid)
    slider_of(e1, "hue_shift").setValue(30)
    QApplication.instance().processEvents()
    e2 = open_editor(win, img)
    check("clip chua chinh thi núm ve 0", label_of(e2, "hue_shift"), "+0°")
    check("clip chua chinh thi khong co EffectData", has_grading(img), False)
    back = open_editor(win, vid)
    check(" quay lai clip cu thi panel doc dung so cua no",
          grading_params(back._clip())["hue_shift"], 30.0)
    win._undo_step()


# ── Gate 7: luu/mo file va do lech preview vs export ────────────

def gate_roundtrip_and_parity(win):
    print("\n== luu file + preview vs export ==")
    model, vid, img, _txt, _aud = build_clips(win)
    editor = open_editor(win, vid)
    slider_of(editor, "hue_shift").setValue(45)
    slider_of(editor, "gamma").setValue(160)
    editor._push_grading(lut_path=os.path.normpath(CUBE))
    QApplication.instance().processEvents()
    truthy("luu du an thanh cong",
           bool(project_storage.save_project_to_file(model, CLINQ)))

    data = json.loads(open(CLINQ, encoding="utf-8").read())
    rows = [c for t in data["timeline"]["tracks"] for c in t["clips"]
            if c["clip_id"] == vid.clip_id]
    grade = [e for e in rows[0]["effects"] if e["name"] == GRADING_EFFECT_NAME]
    check("file .clinq luu dung mot the chinh mau", len(grade), 1)
    check("cac gia tri float con la float trong file",
          [isinstance(grade[0]["params"][k], float)
           for k in ("hue_shift", "gamma")], [True, True])

    from core.timeline_model import TimelineModel
    fresh = TimelineModel()
    project_storage.restore_model_from_clinq(
        fresh, project_storage.load_project_from_file(CLINQ))
    back = [c for t in fresh.tracks for c in t.clips if c.clip_id == vid.clip_id]
    check("mo lai con dung mot the chinh mau", len(back), 1)
    check("mo lai giu duoc hue", grading_params(back[0])["hue_shift"], 45.0)
    check("mo lai giu duoc gamma", grading_params(back[0])["gamma"], 1.60)
    check("mo lai giu duoc duong dan LUT",
          grading_params(back[0])["lut_path"], os.path.normpath(CUBE))

    # Preview (scene.render cua CanvasClipItem) va export (FrameComposer) cung
    # bo so tren mot mau dan toan: lay o giua 40x40 cua moi khung hinh va so
    # tranh tung kenh. Media dan mau nen o giua hai ben la cung mot vung anh,
    # bat chấp hai khung hinh co kich thuoc khac nhau.
    def center(arr, half=20):
        h, w = arr.shape[0], arr.shape[1]
        return arr[h // 2 - half:h // 2 + half,
                   w // 2 - half:w // 2 + half, :3].astype(np.float64)

    from core.frame_composer import FrameComposer
    composer = FrameComposer(model, 640, 360)
    prev = center(preview_shot(win))
    exp = center(to_array(composer.render_frame(1.0)))
    composer.close()
    shift = float((prev[:, :, 2] - prev[:, :, 0]).mean())
    truthy("bo chinh mau dich preview sang kenh lam (B-R=%.1f)" % shift,
           shift > 20)
    worst = float(np.abs(prev.mean(axis=(0, 1)) - exp.mean(axis=(0, 1))).max())
    print("   preview mean=%s export mean=%s" % (
        np.round(prev.mean(axis=(0, 1)), 1).tolist(),
        np.round(exp.mean(axis=(0, 1)), 1).tolist()))
    truthy("preview = export tung kenh (%.1f/255 lech nhau)" % worst, worst < 12.0)


# ── Gate 8: file LUT hong khong giot cua so ─────────────────────

def gate_broken_lut(win):
    print("\n== LUT hong ==")
    junk = os.path.join(OUT, "color_grading_ui_junk.cube")
    with open(junk, "w", encoding="utf-8", newline="\n") as f:
        f.write("LUT_3D_SIZE 9\n0.0 0.0\nran\n")
    model, vid, _img, _txt, _aud = build_clips(win)
    editor = open_editor(win, vid)
    editor._push_grading(lut_path=junk)
    QApplication.instance().processEvents()
    truthy("clip van con sau khi nap file cube rac",
           win.timeline_panel.model.get_clip(vid.clip_id) is not None)
    preview_shot(win)          # phai ve duoc, khong duoc boc exception qua Qt
    truthy("preview van do duoc voi LUT vo dung", True)
    win._undo_step()


def main():
    write_still_video(MP4, A_RGB)
    write_flat_png(PNG, A_RGB)
    write_tone_wav(WAV)
    write_swap_cube(CUBE)
    project_storage.AUTO_SAVE_FILE = AUTOSAVE

    app = QApplication.instance() or QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1680, 940)
    win.show()
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    for _ in range(12):
        app.processEvents()

    missing = [p for p in (MP4, PNG, WAV, CUBE) if not os.path.exists(p)]
    if missing:
        raise SystemExit("thieu media ty sinh: %s" % missing)

    try:
        gate_card_visibility(win)
        gate_hue_drag(win)
        gate_merge(win)
        gate_lut_button(win, CUBE)
        gate_reset(win)
        gate_resync(win)
        gate_roundtrip_and_parity(win)
        gate_broken_lut(win)
    finally:
        # cv2.VideoCapture giu handle den khi object cuoi cung mat tham chieu.
        # Quet TOAN BO gc cho reader/composer con song (khong chi dict cua win):
        # export va preview tao composer rieng, va mot lenh close() theo duong
        # win._video_readers bo sot nen file van khoa sau 2 s retry.
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
        # QMediaPlayer (WMF backend) giu source mo ca sau khi close(): clip
        # video o day co WAV kem nen player tro thang vao file MP4 va file khong
        # xoa duoc; phai bo source trong mot vong processEvents truoc khi xoa.
        try:
            win._audio_player.stop()
            win._audio_player.setSource(QUrl())
        except Exception:
            pass
        app.processEvents()
        win.close()
        app.processEvents()
        gc.collect()
        # Loi o day PHAI bi tinh la rac con sot (fail), khong duoc in mot dong
        # roi bo qua.
        for path in (MP4, PNG, WAV, CUBE, AUTOSAVE, CLINQ,
                     os.path.join(OUT, "color_grading_ui_junk.cube")):
            for attempt in range(20):
                if not os.path.exists(path):
                    break
                try:
                    os.remove(path)
                except OSError:
                    app.processEvents()
                    gc.collect()
                    time.sleep(0.1)
            if os.path.exists(path):
                fails.append("media probe van con sot: %s" % path)
                print("  (rac con sot: %s)" % path)

    if fails:
        print("\nFAILURES:")
        for line in fails:
            print("  -", line)
        return 1
    print("\nALL PASS: 8 gate giao dien chinh mau tren MainWindow that")
    return 0


if __name__ == "__main__":
    sys.exit(main())
