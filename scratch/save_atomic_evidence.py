"""Anh chung minh cho `luu du an: ghi hong khong pha ban cu`.

Ba khung hinh ve tu FrameComposer cua MOT du an 320x180, di qua dung ba ham san
xuat: `save_project_to_file`, `load_project_from_file`, `restore_model_from_clinq`.
Cua so ben trai la file .clinq dang dung, cua giua la ban recovery da bi de lan
gan nhat, cua phai la hieu doi x8. Voi cung mot trang thai thi trai == giua va
hieu doi bang 0; doi noi dung thi hieu doi khong cong 0, chung ba o khong phai
ba ban sao cua mot khung.

```bash
python scratch/save_atomic_evidence.py
```
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch", "save_atomic_evidence.png")
JSON_OUT = os.path.join(ROOT, "scratch", "save_atomic_evidence.json")


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from core import project_storage
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType

    # FrameComposer dung QPainter nen can co app that; khong thi process
    # fastfail 0xC0000409 luc teardown va stdout mat het.
    app = QApplication.instance() or QApplication([])  # noqa: F841

    folder = os.path.join(tempfile.gettempdir(), "clinging_save_evidence")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")
    project_storage.AUTO_SAVE_FILE = os.path.join(folder, "autosave.json")

    def seed(name, hexcolor):
        """Ba dai duong chen de khung ve khong phai mot mau phang: chung nao
        FrameComposer stage dung anh cua clip, khong phai tra nen trang."""
        path = os.path.join(folder, name)
        img = QImage(320, 180, QImage.Format.Format_RGB32)
        img.fill(QColor(hexcolor))
        painter = QPainter(img)
        for index in range(4):
            tone = QColor("#FFFFFF") if index % 2 else QColor("#000000")
            painter.fillRect(20 + index * 70, 30, 40, 120, tone)
        painter.end()
        if not img.save(path):
            raise RuntimeError("khong ghi duoc %s" % path)
        return path

    red = seed("do.png", "#C0392B")
    blue = seed("lam.png", "#2E86C1")

    def build(source, marker):
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, source, "image", 0.0, 2.0,
                              name=marker)
        if clip is None:
            raise RuntimeError("add_clip tra None")
        return model

    def frame(model):
        composer = FrameComposer(model, 320, 180)
        try:
            return composer.render_frame(0.5).convertToFormat(
                QImage.Format.Format_RGB32)
        finally:
            composer.close()

    def restored():
        """Round-trip qua ham that: model -> file -> doc -> model moi."""
        data = project_storage.load_project_from_file(path)
        if not data:
            raise RuntimeError("load_project_from_file tra rong")
        fresh = TimelineModel()
        project_storage.restore_model_from_clinq(fresh, data)
        return fresh

    path = os.path.join(folder, "chung.clinq")
    if not project_storage.save_project_to_file(build(red, "A"), path):
        raise RuntimeError("lan ghi A that bai")
    live_a = frame(build(red, "A"))
    roundtrip_a = frame(restored())

    # Lan ghi thu hai day ban A vao RECOVERY_DIR va thay bang mau lam.
    if not project_storage.save_project_to_file(build(blue, "B"), path):
        raise RuntimeError("lan ghi B that bai")
    copies = sorted(os.listdir(project_storage.RECOVERY_DIR))
    if len(copies) != 1:
        raise RuntimeError("mong 1 ban recovery, thay %s" % copies)

    live_b = frame(build(blue, "B"))
    copy_data = project_storage.load_project_from_file(
        os.path.join(project_storage.RECOVERY_DIR, copies[0]))
    if not copy_data:
        raise RuntimeError("ban recovery khong phai JSON mo duoc")
    model_from_copy = TimelineModel()
    project_storage.restore_model_from_clinq(model_from_copy, copy_data)
    from_copy = frame(model_from_copy)
    marker_from_copy = model_from_copy.tracks[0].clips[0].name

    def diff_px(a, b):
        if a.size() != b.size():
            return -1
        pa, pb = a.constBits(), b.constBits()
        ba = pa.tobytes() if hasattr(pa, "tobytes") else bytes(pa)
        bb = pb.tobytes() if hasattr(pb, "tobytes") else bytes(pb)
        return sum(1 for x, y in zip(ba, bb) if x != y)

    same_ab = diff_px(live_a, roundtrip_a)
    same_copy = diff_px(live_a, from_copy)
    changed = diff_px(live_a, live_b)
    if marker_from_copy != "A":
        raise RuntimeError("ban recovery khong phai trang thai A: %s"
                           % marker_from_copy)
    if same_ab != 0 or same_copy != 0:
        raise RuntimeError("ban recovery khung khac file dang dung (%d/%d byte lech)"
                           % (same_ab, same_copy))
    if changed == 0:
        raise RuntimeError("doi noi dung ma khong doi pixel: ba o la ba ban sao")

    canvas = QImage(320 * 3 + 40, 180, QImage.Format.Format_RGB32)
    canvas.fill(QColor("#111111"))
    painter = QPainter(canvas)
    painter.drawImage(0, 0, live_a)
    painter.drawImage(340, 0, from_copy)
    delta = QImage(320, 180, QImage.Format.Format_RGB32)
    delta.fill(QColor("#000000"))
    for y in range(180):
        for x in range(320):
            d = abs(live_a.pixelColor(x, y).red() - live_b.pixelColor(x, y).red())
            delta.setPixelColor(x, y, QColor(min(255, d * 8), 0, 0))
    painter.drawImage(680, 0, delta)
    painter.end()
    if not canvas.save(OUT):
        raise RuntimeError("khong luu duoc %s" % OUT)

    payload = {
        "png": OUT,
        "live_A_lech_roundtrip_A": same_ab,
        "live_A_lech_recovery_A": same_copy,
        "byte_khac_giua_A_va_B": changed,
        "marker_trong_ban_recovery": marker_from_copy,
        "ban_recovery": copies,
    }
    with open(JSON_OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("ALL PASS " + json.dumps(payload, ensure_ascii=False))
    shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
