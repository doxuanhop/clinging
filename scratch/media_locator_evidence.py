"""Anh chung minh cho dong selftest `media lac cho: preview va export cung duong dan`.

Bon o 320x180 ve tu FrameComposer cua CUNG mot du an, di qua dung ba ham san
xuat (`save_project_to_file`, `load_project_from_file`,
`restore_model_from_clinq`) va qua `render_frame_bytes` — tuc la dung payload
ma exporter day thang vong ffmpeg.

  1. File media nam dung cho, clip con nguyen.
  2. Nguoi dung don file vao thu muc con sau hai cap, roi mo lai file .clinq:
     duong dan trong model duoc dinh vi lai, va byte xuat ra bang het o 1.
  3. Cam cung ten file dat ngoai thu muc an: o nay ve mau KHAC de chung hai
     ben khong the nham nhau; `locate` phai khong bao gio lay no.
  4. File vang mat that: khong ve gi ca, duong dan cu duoc giu nguyen va ten
     clip nam trong danh sach `missing` de caller bao nguoi dung.

```bash
python scratch/media_locator_evidence.py
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
OUT = os.path.join(ROOT, "scratch", "media_locator_evidence.png")
JSON_OUT = os.path.join(ROOT, "scratch", "media_locator_evidence.json")

CELL_W, CELL_H, GAP, LABEL_H = 320, 180, 16, 26


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from core import media_locator, project_storage
    from core.frame_composer import FrameComposer
    from core.timeline_model import ClipModel, TimelineModel, TrackType

    # FrameComposer dung QPainter: khong co app that thi process fastfail
    # 0xC0000409 luc teardown va stdout mat khong con mot dong.
    app = QApplication.instance() or QApplication([])  # noqa: F841

    folder = os.path.join(tempfile.gettempdir(), "clinging_locator_evidence")
    shutil.rmtree(folder, ignore_errors=True)
    proj = os.path.join(folder, "proj")
    os.makedirs(os.path.join(proj, "media", "deep", "deeper"), exist_ok=True)
    project_storage.RECOVERY_DIR = os.path.join(folder, "recovery")

    def raw(image):
        bits = image.constBits()
        return bits.tobytes() if hasattr(bits, "tobytes") else bytes(bits)

    def seed(dirpath, name, hexcolor):
        """Nen mau + hai dai sang/toi: o ve khong duoc phan biet nen bang
        khuyet diem, ma phai so tung byte."""
        path = os.path.join(dirpath, name)
        img = QImage(CELL_W, CELL_H, QImage.Format.Format_RGB32)
        img.fill(QColor(hexcolor))
        painter = QPainter(img)
        for index in range(4):
            tone = QColor("#FFFFFF") if index % 2 else QColor("#000000")
            painter.fillRect(20 + index * 70, 30, 40, 120, tone)
        painter.end()
        if not img.save(path):
            raise RuntimeError("khong ghi duoc %s" % path)
        return path

    # Hai file CUNG TEN o hai cho khac nhau: `live` la tai nguyen cua du an,
    # `decoy` nam ngoai pham vi tim kiem (thu muc cha cua no). Neu mau cua o 3
    # lan sang o 1/2 thi dinh vi da cham vao sai file.
    live = seed(proj, "clip.png", "#1E8449")
    decoy = seed(folder, "clip.png", "#943126")

    def build(source, marker):
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, source, "image", 0.0, 2.0,
                              name=marker)
        if clip is None:
            raise RuntimeError("add_clip tra None")
        return model

    def compose(model):
        """Tra (anh ve o, payload xuat ra) tu CUNG mot lan render."""
        composer = FrameComposer(model, CELL_W, CELL_H)
        try:
            image = composer.render_frame(0.5)
            payload = composer.render_frame_bytes(0.5)
        finally:
            composer.close()
        return image.convertToFormat(QImage.Format.Format_RGB32), payload

    # (1) Trang thai dung cho.
    before, before_bytes = compose(build(live, "A"))

    # (2) Luu .clinq nhu nguoi dung, roi DON file vao thu muc sau hai cap.
    clinq = os.path.join(proj, "du_an.clinq")
    if not project_storage.save_project_to_file(build(live, "A"), clinq):
        raise RuntimeError("khong luu duoc du_an.clinq")
    relocated = os.path.join(proj, "media", "deep", "deeper", "clip.png")
    shutil.move(live, relocated)
    if os.path.exists(live):
        raise RuntimeError("don file that khong dien ra")

    data = project_storage.load_project_from_file(clinq)
    restored = TimelineModel()
    project_storage.restore_model_from_clinq(
        restored, data, media_roots=[proj])
    clips = [c for t in restored.tracks for c in t.clips]
    if len(clips) != 1:
        raise RuntimeError("mong 1 clip, thay %d" % len(clips))
    got = clips[0].source_path
    if got != relocated:
        raise RuntimeError("khong dinh vi lai duoc file lac cho: %s" % got)
    after, after_bytes = compose(restored)
    if before_bytes != after_bytes:
        raise RuntimeError("payload xuat ra doi sau khi dinh vi: lech %d/byte"
                           % sum(1 for x, y in zip(before_bytes, after_bytes)
                                 if x != y))

    # (3) Cam trong thu muc hien hanh: o phai khac (1) va (2) thi mau moi la
    # thu phan biet, con `locate` lay no thi gate tren da do.
    decoy_frame, decoy_bytes = compose(build(decoy, "cam"))
    if decoy_bytes == after_bytes:
        raise RuntimeError("cam va file du an ve giong het nhau: khong phan biet duoc")
    if os.path.normcase(got) == os.path.normcase(decoy):
        raise RuntimeError("model tro ve cam trong thu muc hien hanh")

    # (4) Vang mat that: clip tro chi mot file khong ton tai o dau ca.
    ghost = TimelineModel()
    ghost.project_ratio = "16:9"
    lane = ghost.add_track(TrackType.IMAGE)
    missing_path = os.path.join(proj, "media", "khong_co.png")
    lane.clips.append(ClipModel(start_time=0.0, duration=2.0,
                                 source_path=missing_path, media_type="image",
                                 name="vang-mat", track_id=lane.track_id))
    resolved, missing = media_locator.resolve_model(ghost, (proj,))
    if resolved or missing != [missing_path]:
        raise RuntimeError("resolve_model dem sai: resolved=%s missing=%s"
                           % (resolved, missing))
    if lane.clips[0].source_path != missing_path:
        raise RuntimeError("clip vang mat bi doi duong dan")
    empty, empty_bytes = compose(ghost)
    if empty_bytes == after_bytes:
        raise RuntimeError("clip vang mat ve giong clip co that")

    canvas = QImage(CELL_W * 4 + GAP * 3, CELL_H + LABEL_H,
                    QImage.Format.Format_RGB32)
    canvas.fill(QColor("#141414"))
    painter = QPainter(canvas)
    painter.setFont(QFont("Arial", 11))
    painter.setPen(QColor("#E0E0E0"))
    labels = [
        "1 file dung cho (preview)",
        "2 don 2 cap, mo lai .clinq (xuat ra)",
        "3 cam ngoai thu muc an (khong dung)",
        "4 vang mat that (khong ve gi)",
    ]
    for index, (label, img) in enumerate(
            zip(labels, [before, after, decoy_frame, empty])):
        x = index * (CELL_W + GAP)
        painter.drawImage(x, LABEL_H, img)
        painter.drawText(x, 0, CELL_W, LABEL_H - 4,
                         Qt.AlignLeft | Qt.AlignVCenter, label)
    painter.end()
    if not canvas.save(OUT):
        raise RuntimeError("khong luu duoc %s" % OUT)
    if raw(before) != raw(after) or raw(empty) == raw(after):
        raise RuntimeError("so byte khong hop ly: 1!=2 hoac 4==2")

    report = {
        "png": OUT,
        "duong_dan_trong_clinq": os.path.relpath(
            data["timeline"]["tracks"][0]["clips"][0]["source_path"], folder),
        "duong_dan_sau_restore": os.path.relpath(got, folder),
        "payload_xuat_lech_byte_giua_1_va_2":
            sum(1 for x, y in zip(before_bytes, after_bytes) if x != y),
        "lecho_giua_o_3_va_o_2": sum(1 for x, y in zip(decoy_bytes, after_bytes)
                                      if x != y),
        "missing": [os.path.relpath(p, folder) for p in missing],
        "resolved": len(resolved),
    }
    with open(JSON_OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("ALL PASS " + json.dumps(report, ensure_ascii=False))
    shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
