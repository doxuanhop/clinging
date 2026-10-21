r"""Anh chung minh D5: bo chinh mau (hue / lift-gamma-gain / LUT .cube) ve ra
that duong xuat FrameComposer — cung ham `apply_color_effects` ma preview dung.

Gate --selftest do pixel bang numpy tai cho; hai anh o day de NGUOI MO RA XEM:
moi o la mot clip ANH (PNG ty le sinh, khong dung anh nguoi dung) dat len
TimelineModel roi render qua FrameComposer(model, W, H) nhu luc xuat video that.
Anh thu hai la the "Chinh mau" trong panel thuoc tinh, grab bang chinh widget
dung trong app.

Nen dung QApplication THAT (khong offscreen): offscreen o may nay khong co font
nen nhan tren the chinh mau chi la tofu, khong phan duoc so nao dang hien.

Chay:
    python scratch/color_grading_evidence.py
In ra bang so do tung o va EVIDENCE_IMAGE; exit 1 neu bat ky kiem tra nao hong.
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from theme import theme_manager

app.setStyleSheet(theme_manager.stylesheet())

from core import lut as lut_mod
from core.clip_effects import GRADING_EFFECT_NAME
from core.commands import SetGradingCommand, UndoStack
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType
from ui.properties_panel import ClipPropertiesWidget

OUT_SHEET = os.path.join(ROOT, "scratch", "color_grading_evidence.png")
OUT_CARD = os.path.join(ROOT, "scratch", "color_grading_card_evidence.png")
WORK = os.path.join(tempfile.gettempdir(), "clinging_grading_evidence")
TW, TH = 320, 180
SRC_W, SRC_H = 640, 360

PASS = []
FAIL = []


def truthy(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", label,
                           (" | " + extra) if extra else ""))
    return cond


def write_source_png(path):
    """Mau dinh: 6 o hue bao hoa ben trai, ramp xam + 3 o den/giua/sang ben phai.

    cv2 hieu mang la BGR nen phai dao kenh truoc khi ghi; quen dao la toan bo anh
    doi mau va kiem tra identity-LUT do khong ra gi.
    """
    import cv2
    arr = np.zeros((SRC_H, SRC_W, 3), np.uint8)
    hues = [(220, 40, 40), (220, 220, 40), (40, 220, 40),
            (40, 220, 220), (40, 40, 220), (220, 40, 220)]
    half = SRC_W // 2
    cell = SRC_H // 2
    w = half // 6
    for i, rgb in enumerate(hues):
        x = i * w
        arr[:cell, x:x + w] = rgb
        arr[cell:, x:x + w] = tuple(int(c * 0.45) for c in rgb)
    ramp = np.linspace(0, 255, SRC_W - half, dtype=np.uint8)
    arr[:, half:] = ramp[None, :, None]
    for i, level in enumerate((6, 128, 246)):
        y = 20 + i * 110
        arr[y:y + 90, half + 20:half + 110] = level
    bgr = np.ascontiguousarray(arr[:, :, ::-1])
    if not cv2.imwrite(path, bgr):
        raise RuntimeError("cv2.imwrite khong ghi duoc %s" % path)
    return arr


def write_cube(path, n, value):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("LUT_3D_SIZE %d\n" % n)
        for ri in range(n):
            for gi in range(n):
                for bi in range(n):
                    r, g, b = (ri / (n - 1.0), gi / (n - 1.0), bi / (n - 1.0))
                    handle.write("%.6f %.6f %.6f\n" % value(r, g, b))


def to_array(image):
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    row = img.bytesPerLine()
    raw = bytes(img.constBits()[: row * img.height()])
    # bytesPerLine TINH BYTE, nen so cot pixel = row // 3 (320x180 RGB888
    # trung hop row = 960 va khong co padding).
    a = np.frombuffer(raw, np.uint8).reshape(img.height(), row // 3, 3)
    return a[:, :img.width(), :].astype(np.int16)


def render(over, src_path):
    """Mot clip ANH mang bo chinh mau `over`, render qua FrameComposer that."""
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.IMAGE)
    clip = model.add_clip(track.track_id, src_path, "image", 0.0, 4.0, name="mau")
    if clip is None:
        raise RuntimeError("add_clip image tra None")
    if over:
        stack = UndoStack()
        stack.push(SetGradingCommand(model, clip.clip_id, dict(over)))
        if not [e for e in clip.effects if e.name == GRADING_EFFECT_NAME]:
            raise RuntimeError("lenh chinh mau khong gan duoc EffectData")
    composer = FrameComposer(model, TW, TH)
    try:
        # FrameComposer.render_frame tra QImage ARGB32_Premultiplied dung
        # nguyen duong export; do sang phai doc tren RGB888 lien tuc.
        return composer.render_frame(1.0).convertToFormat(
            QImage.Format.Format_RGB888), clip
    finally:
        composer.close()


def band_masks(a):
    """Vi tri ba vung do sang cua anh goc: toi (<64), giua (64..192), sang (>=192).

    Mask PHAI lay tu o goc roi dung lai cho moi o: lift 0.30 day toan bo vung toi
    vuot nguong 64 nen neu tinh theo tung o thi band toi rong, ra NaN va khong
    do duoc gi nua.
    """
    luma = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    return tuple((luma >= lo) & (luma < hi)
                 for lo, hi in ((0, 64), (64, 192), (192, 256)))


def band_levels(a, masks):
    return [float(a[m].mean()) for m in masks]


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    src = os.path.join(WORK, "mau.png")
    write_source_png(src)
    ident = os.path.join(WORK, "identity.cube")
    swap = os.path.join(WORK, "swap.cube")
    write_cube(ident, 17, lambda r, g, b: (r, g, b))
    write_cube(swap, 17, lambda r, g, b: (b, g, r))
    print("nguon mau %dx%d | LUT sha16 identity=%s swap=%s"
          % (SRC_W, SRC_H, lut_mod.lut_fingerprint(ident),
             lut_mod.lut_fingerprint(swap)))

    cases = [
        ("1. goc (khong chinh mau)", {}),
        ("2. hue +90 do", {"hue_shift": 90.0}),
        ("3. hue -90 do", {"hue_shift": -90.0}),
        ("4. lift 0.30 (nhac bong)", {"lift": 0.30}),
        ("5. gamma 1.60 (bentre giua)", {"gamma": 1.60}),
        ("6. gain 0.60 (ha sang)", {"gain": 0.60}),
        ("7. LUT identity 17^3", {"lut_path": ident}),
        ("8. LUT hoan vi R-B", {"lut_path": swap}),
        ("9. hue +45 + gamma 1.3 + LUT identity",
         {"hue_shift": 45.0, "gamma": 1.30, "lut_path": ident}),
    ]

    tiles = []
    arrays = {}
    graded_clip = None
    for label, over in cases:
        img, clip = render(over, src)
        arrays[label] = to_array(img)
        tiles.append((label, img))
        graded_clip = clip

    base = arrays[cases[0][0]]
    masks = band_masks(base)
    if not all(int(m.sum()) > 200 for m in masks):
        raise RuntimeError("ba vung do sang o goc qua mong: %s"
                           % [int(m.sum()) for m in masks])
    base_b = band_levels(base, masks)
    print("\nlech so voi o goc (mean|diff| 3 kenh, va 3 band do sang lay theo o goc):")
    stats = {}
    for label, _ in cases[1:]:
        a = arrays[label]
        b = band_levels(a, masks)
        stats[label] = (float(np.abs(a - base).mean()), b)
        print("  %-42s %5.1f  toi %6.1f  giua %6.1f  sang %6.1f"
              % (label, stats[label][0], b[0], b[1], b[2]))
    print("  (o goc: toi %.1f  giua %.1f  sang %.1f)" % tuple(base_b))

    print("\nkiem tra tren anh render:")
    ident_t = cases[6][0]
    swap_t = cases[7][0]
    plus, minus = cases[1][0], cases[2][0]
    lift_t, gam_t, gain_t = cases[3][0], cases[4][0], cases[5][0]
    comb_t = cases[8][0]
    truthy("o goc co noi dung that (std=%.1f > 10)" % float(base.std()),
           float(base.std()) > 10.0)
    truthy("LUT identity ve ra bang nguyen ban (%.2f < 1.5)" % stats[ident_t][0],
           stats[ident_t][0] < 1.5)
    a = arrays[swap_t]
    # Mean R va mean B cua anh doi xung bang nhau (117.8/117.8) nen so mean
    # kenh khong do duoc hoan vi. Phai so tung pixel: R cua o swap phai bang
    # B cua o goc va PHAI khac R cua o goc o nhung vung mau bao hoa.
    sw_ok = float(np.abs(a[:, :, 0] - base[:, :, 2]).mean())
    sw_no = float(np.abs(a[:, :, 0] - base[:, :, 0]).mean())
    truthy("LUT hoan vi R-B doi dung kenh theo tung pixel (%.1f lech, %.1f khac kenh cu)"
           % (sw_ok, sw_no), sw_ok < 3.0 and sw_no > 8.0)
    d_pm = float(np.abs(arrays[plus] - arrays[minus]).mean())
    truthy("hue +90 va -90 di nguoc chieu nhau (%.1f > 8.0)" % d_pm, d_pm > 8.0)
    truthy("moi ben hue deu lech khoi goc (%.1f / %.1f > 5.0)"
           % (stats[plus][0], stats[minus][0]),
           stats[plus][0] > 5.0 and stats[minus][0] > 5.0)
    lift_r = tuple(stats[lift_t][1][i] / base_b[i] for i in range(3))
    gam_r = tuple(stats[gam_t][1][i] / base_b[i] for i in range(3))
    # Cong thuc lift `x + lift*(1-x)` nen so khong bang nhau ma ti le phai
    # bang: bong toi 46.7 -> 108.8 (gap 2,3 lan) trong khi vung sang 213.7 chi
    # len 225.5 (1,06 lan). Do bang so tuyet doi thi khong phan biet duoc lift
    # voi brightness gia trang.
    truthy("lift nhac bong theo ti le (toi %.2f lan, sang %.2f lan)"
           % (lift_r[0], lift_r[2]),
           lift_r[0] > 1.8 and lift_r[2] < 1.10)
    truthy("gamma bun vung giua, vung sang gan nhu giu nguyen (giua %.2f lan, sang %.2f lan)"
           % (gam_r[1], gam_r[2]),
           gam_r[1] > 1.15 and gam_r[2] < 1.10)
    ratios = tuple(stats[gain_t][1][i] / base_b[i] for i in range(3))
    truthy("gain 0.60 ha ca ba band ti le (%.2f %.2f %.2f)" % ratios,
           all(0.5 < r < 0.72 for r in ratios))
    truthy("bo ket hop khong giong hue +90 don thuan (%.1f > 3.0)"
           % float(np.abs(arrays[comb_t] - arrays[plus]).mean()),
           float(np.abs(arrays[comb_t] - arrays[plus]).mean()) > 3.0)

    cols, rows = 3, (len(tiles) + 2) // 3
    label_h, pad = 22, 8
    sheet = QImage(cols * (TW + pad) + pad, rows * (TH + label_h + pad) + pad,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#0c0c10"))
    p = QPainter(sheet)
    p.setFont(QFont("Segoe UI", 10))
    for i, (label, img) in enumerate(tiles):
        x = pad + (i % cols) * (TW + pad)
        y = pad + (i // cols) * (TH + label_h + pad)
        p.drawImage(x, y, img)
        p.setPen(QColor("#e8e8ee"))
        p.drawText(x + 2, y + TH + 15, label)
    p.end()
    truthy("luu duoc sheet render", sheet.save(OUT_SHEET), OUT_SHEET)

    edit = ClipPropertiesWidget(graded_clip)
    edit.resize(320, 900)
    card = edit.card_grading
    pm = card.grab()
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    row = img.bytesPerLine()
    a = np.frombuffer(img.constBits(), np.uint8,
                      count=row * img.height()).reshape(
        img.height(), row // 4, 4)[:, :img.width(), 3]
    alpha = int((a > 8).sum())
    truthy("the Chinh mau ve ra co pixel (%dx%d, %d diem alpha)"
           % (pm.width(), pm.height(), alpha), alpha > 5000)
    truthy("the hien ten LUT da chon", "identity" in edit.lbl_lut_name.text(),
           edit.lbl_lut_name.text())
    labels = {key: value_label.text()
              for key, (slider, value_label, fmt, unit)
              in edit._grading_widgets.items()}
    truthy("nhan tren the doc lai dung bo so cua clip (hue=%s gamma=%s)"
           % (labels.get("hue_shift"), labels.get("gamma")),
           str(labels.get("hue_shift", "")).startswith("+45")
           and labels.get("gamma") == "1.30")
    truthy("luu duoc anh the dieu khien", pm.save(OUT_CARD), OUT_CARD)
    edit.deleteLater()
    app.processEvents()

    print("\nEVIDENCE_IMAGE:", OUT_SHEET)
    print("EVIDENCE_IMAGE:", OUT_CARD)
    print("KET QUA: %d OK / %d FAIL" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


try:
    sys.exit(main())
finally:
    shutil.rmtree(WORK, ignore_errors=True)
