r"""Anh chung minh cong dong duc nen (chroma key): phep cat alpha ve ra that
duong xuat FrameComposer — cung ham `apply_color_effects` ma preview dung.

Khac hai bang anh cua chinh mau o cho day la MOT BO ANH HAI LOP: alpha chi nhin
thay duoc khi ben duoi co gi. Moi o la hai clip ANH tren hai track IMAGE (lop duoi
caro bon mau, lop tren la man hinh nen xanh #00B140 co tam chu the 8 mau), dat
len TimelineModel roi render qua FrameComposer(model, W, H) nhu luc xuat video
that. Cac the chroma gan qua SetChromaCommand that tren UndoStack — dung duong
nguoi dung di, khong tu gan EffectData.

Do bang cach lay mau o TAM tung patch va so voi HAI mau chieu doc cùng toa do:
man hinh goc (khi chua cat) va lop caro (khi da bi cat). patch nao gan lop caro
hon thi phep cat da an no; patch nao gan mau goc hon thi no con song.

Anh thu hai la the "Duc nen" trong panel thuoc tinh, grab bang chinh widget dung
trong app. Dung QApplication THAT (khong offscreen): offscreen o may nay khong co
font nen nhan tren the chi la tofu.

Chay:
    python scratch/chroma_key_evidence.py
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

from core.clip_effects import CHROMA_EFFECT_NAME
from core.commands import SetChromaCommand, SetGradingCommand, UndoStack
from core.frame_composer import FrameComposer
from core.timeline_model import TimelineModel, TrackType
from ui.properties_panel import ClipPropertiesWidget

OUT_SHEET = os.path.join(ROOT, "scratch", "chroma_key_evidence.png")
OUT_CARD = os.path.join(ROOT, "scratch", "chroma_key_card_evidence.png")
WORK = os.path.join(tempfile.gettempdir(), "clinging_chroma_evidence")
TW, TH = 640, 360
SRC_W, SRC_H = 640, 360

GREEN = np.array([0, 177, 64], np.int16)
# (ten, goc trai o 120x90 tren man hinh 640x360, mau chu the). Tam cua hang duoi
# dat tai y=180 de hop 20x20 nam tron trong MOT o caro (duong bien 120/240).
PATCHES = (("trang", 40, 45, (245, 245, 245)),
           ("xam", 180, 45, (130, 130, 130)),
           ("da", 320, 45, (228, 178, 150)),
           ("lacay", 480, 45, (60, 200, 60)),
           ("lan", 40, 135, (60, 190, 200)),
           ("am_xanh", 180, 135, (140, 190, 150)),
           ("do", 320, 135, (220, 40, 40)),
           ("den", 480, 135, (40, 40, 40)))
PW, PH = 120, 90
CORNER = (20, 330)            # nen xanh thuan, khong chu the nao che
STRIP_RGB = np.array([150, 205, 165], np.int16)   # dai mong doc tren man nen

PASS = []
FAIL = []


def truthy(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", label,
                           (" | " + extra) if extra else ""))
    return cond


def write_source(path, arr):
    import cv2
    # cv2 hieu mang la BGR: quen dao kenh thi toan bo bang doi mau va moi so
    # do lech kenh (spill, hoan vi) vo nghia.
    bgr = np.ascontiguousarray(arr[:, :, ::-1])
    if not cv2.imwrite(path, bgr):
        raise RuntimeError("cv2.imwrite khong ghi duoc %s" % path)


def strip_center(row):
    """Cot tam cua dai mong o dong `row` (cong thuc dung khi ve anh nen)."""
    return SRC_W - 1 - int(row * (SRC_W / float(SRC_H)))


def write_plate():
    """Man hinh nen xanh #00B140 + tam chu the 8 mau + dai mong xanh nhat."""
    arr = np.zeros((SRC_H, SRC_W, 3), np.uint8)
    arr[:] = GREEN
    for _name, x, y, rgb in PATCHES:
        arr[y:y + PH, x:x + PW] = rgb
    for i in range(SRC_H):
        c = strip_center(i)
        arr[i, max(0, c - 6):min(SRC_W, c + 6)] = STRIP_RGB
    return arr


def write_backdrop():
    """Caro 4 mau le: vi tri o caro duoc lay mau bang toa do pixel tren anh nen."""
    cols = [(200, 40, 200), (40, 200, 200), (240, 240, 60), (70, 70, 220)]
    arr = np.zeros((SRC_H, SRC_W, 3), np.uint8)
    cw, ch = SRC_W // 4, SRC_H // 3
    for r in range(3):
        for c in range(4):
            arr[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = cols[(r + c) % 4]
    return arr


def to_array(image):
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    row = img.bytesPerLine()
    raw = bytes(img.constBits()[: row * img.height()])
    # bytesPerLine TINH BYTE nen so cot pixel = row // 3.
    a = np.frombuffer(raw, np.uint8).reshape(img.height(), row // 3, 3)
    return a[:, :img.width(), :].astype(np.int16)


PLATE = BACKDROP = None


def build(over=None, grade=None, drop_foreground=False):
    """Hai lop: caro duoi, man nen xanh tren. The chroma/chinh mau gan qua LENH
    that tren UndoStack — panel va duong dung cua nguoi dung cung mot loi goi."""
    model = TimelineModel()
    model.project_ratio = "16:9"
    # add_track dao nguoc z_index (track THEM SAU roi z_index = 0 = nen), nen
    # lop phai cat phai duoc them TRUOC. Dao lai thu tu la caro lap day nen.
    top = model.add_track(TrackType.IMAGE)
    bottom = model.add_track(TrackType.IMAGE)
    if [t.z_index for t in (top, bottom)] != sorted([t.z_index for t in (top, bottom)],
                                                    reverse=True):
        raise RuntimeError("gia dinh z_index dao nguoc da doi: top=%s bottom=%s"
                           % (top.z_index, bottom.z_index))
    if model.add_clip(bottom.track_id, BACKDROP, "image", 0.0, 4.0,
                      name="caro") is None:
        raise RuntimeError("add_clip caro tra None")
    fg = model.add_clip(top.track_id, PLATE, "image", 0.0, 4.0, name="nen-xanh")
    if fg is None:
        raise RuntimeError("add clip nen-xanh tra None")
    stack = UndoStack()
    if grade:
        stack.push(SetGradingCommand(model, fg.clip_id, dict(grade)))
    if over:
        stack.push(SetChromaCommand(model, fg.clip_id, dict(over)))
        if not [e for e in fg.effects if e.name == CHROMA_EFFECT_NAME]:
            raise RuntimeError("lenh chroma khong gan duoc EffectData")
    if drop_foreground:
        model.remove_clip(fg.clip_id)
    return model, fg, stack


def render(model):
    composer = FrameComposer(model, TW, TH)
    try:
        # FrameComposer.render_frame tra dung duong export; do lech phai doc
        # tren RGB888 lien tuc, khong phai tren kenh alpha cua ARGB32.
        return to_array(composer.render_frame(1.0).convertToFormat(
            QImage.Format.Format_RGB888))
    finally:
        composer.close()


def mean_box(a, cx, cy, half=10):
    return a[cy - half:cy + half, cx - half:cx + half].reshape(-1, 3).mean(axis=0)


def patch(a, name):
    """Mean 20x20 o TAM patch tren BAT KY anh nao: cung toa do thi so duoc."""
    _x, _y = next((p[1], p[2]) for p in PATCHES if p[0] == name)
    return mean_box(a, _x + PW // 2, _y + PH // 2)


def strip_mean(a):
    """Doc doc dai mong: moi dong lay 5 pixel quanh tam cua chinh no."""
    return np.mean([mean_box(a, strip_center(i), i, 2) for i in range(300, 312)],
                   axis=0).astype(np.int16)


def src_of(name):
    return np.array(next(p[3] for p in PATCHES if p[0] == name), np.int16)


def corner(a):
    return mean_box(a, *CORNER)


def dist(got, ref):
    return float(np.abs(got - ref).max())


def main():
    global PLATE, BACKDROP
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    plate = write_plate()
    backdrop = write_backdrop()
    PLATE = os.path.join(WORK, "nen-xanh.png")
    BACKDROP = os.path.join(WORK, "caro.png")
    write_source(PLATE, plate)
    write_source(BACKDROP, backdrop)

    # Chi con lop caro (da bo clip tren) -> day la mau phai thoat ra khi phep cat
    # an het: moi do lech sau nay chieu ve toa do nay, khong chieu ve hang ma.
    bare = render(build(drop_foreground=True)[0])
    plain = render(build()[0])
    print("lop duoi (%d,%d,%d) o goc | nen xanh khi chua cat (%d,%d,%d) o goc"
          % (*corner(bare).astype(int), *corner(plain).astype(int)))
    if dist(corner(bare), corner(plain)) < 60:
        raise RuntimeError("hai lop khong chong du nhau: track sau khong nam tren "
                           "track truoc, khong do duoc phep cat")

    cases = [
        ("0. khong co the chroma", {}, None),
        ("1. dung sai 0.05", {"tolerance": 0.05}, None),
        ("2. dung sai 0.30", {"tolerance": 0.30}, None),
        ("3. dung sai 0.60 + vien mong 0.60",
         {"tolerance": 0.60, "feather": 0.60}, None),
        ("4. 0.05 + vien mong 0.60 (goc do chong am)",
         {"tolerance": 0.05, "feather": 0.60}, None),
        ("5. nhu 4 + chong am 0.80",
         {"tolerance": 0.05, "feather": 0.60, "spill": 0.80}, None),
        ("6. mau khoa DO #FF0000, dung sai 0.35",
         {"key_color": "#FF0000", "tolerance": 0.35}, None),
        ("7. dung sai 0.30 + chinh mau hue +90",
         {"tolerance": 0.30}, {"hue_shift": 90.0}),
    ]
    tiles = []
    arrays = {}
    graded_clip = chroma_clip = None
    for label, over, grade in cases:
        model, clip, _ = build(over, grade)
        arrays[label] = render(model)
        tiles.append((label, arrays[label]))
        if label.startswith("2."):
            chroma_clip = clip
        graded_clip = clip
        del model

    print("\nphan loai tam cua tung mau (GOC = con song, DUOI = da bi cat):")
    print("%-40s %s" % ("o", " ".join("%7s" % p[0] for p in PATCHES)))
    for label, _o, _g in cases:
        a = arrays[label]
        row = []
        for name, _x, _y, _rgb in PATCHES:
            got = patch(a, name)
            row.append("GOC" if dist(got, src_of(name)) <= dist(got, patch(bare, name))
                       else "DUOI")
        print("%-40s %s" % (label, " ".join("%7s" % r for r in row)))

    print("\nkiem tra tren anh render:")
    t = [c[0] for c in cases]
    (t_none, t_005, t_030, t_060, t_sp0, t_sp8, t_red, t_grade) = t

    def kept(label, name, why):
        got = patch(arrays[label], name)
        return truthy("%s: %s con song (%s)" % (label, name, why),
                      dist(got, src_of(name)) < 6.0, str(got.astype(int)))

    def cut(label, name, why):
        got = patch(arrays[label], name)
        return truthy("%s: %s da bi cat (%s)" % (label, name, why),
                      dist(got, patch(bare, name)) < 6.0, str(got.astype(int)))

    truthy("o 0: chua bat thi nen xanh lap day (%d,%d,%d)"
           % tuple(corner(arrays[t_none]).astype(int)),
           dist(corner(arrays[t_none]), GREEN) < 6.0)
    for name in ("trang", "xam", "da", "lacay", "lan", "am_xanh", "do", "den"):
        kept(t_none, name, "chua co the")

    for label in (t_005, t_030, t_060, t_sp0, t_sp8):
        c = corner(arrays[label])
        truthy("%s: nen xanh bi cat, lop duoi thoat ra (%d,%d,%d)"
               % (label, *c.astype(int)), dist(c, corner(bare)) < 5.0)

    for name in ("trang", "xam", "da", "den", "lacay", "lan"):
        kept(t_005, name, "dung sai 0.05 chua toi 19.8 do")
    for name in ("trang", "xam", "da", "den"):
        kept(t_030, name, "trung tinh, mag duoi nguong")
        kept(t_060, name, "trung tinh o dung sai toi da")
    cut(t_030, "lacay", "19.8 do da nam trong vong 0.30")
    kept(t_030, "lan", "40.8 do ngoai vong 0.30")
    cut(t_060, "lacay", "19.8 do")
    cut(t_060, "lan", "40.8 do trong vong 49.6 do")

    # Dai mong (150,205,165) cung hue voi nen nhung bao hoa 26.5: no bi an DAN
    # theo nguong bao hoa, nen o dung sai nho nhat no gan lop duoi hon gan chinh
    # no. Do bang ti le: 0 < frac < 0.5 nghia la da mat phan lon.
    vis = strip_mean(arrays[t_005])
    bd = strip_mean(bare)
    span = dist(bd, STRIP_RGB)
    frac = dist(vis, bd) / max(1.0, span)
    truthy("dai mong xanh nhat bi an dan o dung sai 0.05 (frac %.2f < 0.5, lech goc %.1f > 8)"
           % (frac, dist(vis, STRIP_RGB)), 0.0 <= frac < 0.5
           and dist(vis, STRIP_RGB) > 8.0)

    ga0, ga8 = patch(arrays[t_sp0], "lacay"), patch(arrays[t_sp8], "lacay")
    truthy("chong am 0.8 keo kenh xanh cua vuong bi am (%d -> %d, lech %.1f > 20)"
           % (int(ga0[1]), int(ga8[1]), abs(ga0[1] - ga8[1])), abs(ga0[1] - ga8[1]) > 20.0)
    truthy("chong am khong dong kenh do/luc (%.1f / %.1f)"
           % (abs(float(ga0[0] - ga8[0])), abs(float(ga0[2] - ga8[2]))),
           abs(float(ga0[0] - ga8[0])) < 6.0 and abs(float(ga0[2] - ga8[2])) < 6.0)
    truthy("chong am khong lam doi matte (goc lech %.1f < 4)"
           % dist(corner(arrays[t_sp8]), corner(arrays[t_sp0])),
           dist(corner(arrays[t_sp8]), corner(arrays[t_sp0])) < 4.0)

    cut(t_red, "do", "mau khoa DO cat do 142.8 do lech nen")
    cut(t_red, "da", "mau khoa DO cat ca mau da")
    truthy("mau khoa DO: nen van LAP DAY xanh (%d,%d,%d)"
           % tuple(corner(arrays[t_red]).astype(int)),
           dist(corner(arrays[t_red]), GREEN) < 6.0)
    for name in ("lacay", "lan", "trang", "den"):
        kept(t_red, name, "hue khong gan DO")

    truthy("o 7: the chroma dat cung the chinh mau hue +90 van cat het nen (%d,%d,%d)"
           % tuple(corner(arrays[t_grade]).astype(int)),
           dist(corner(arrays[t_grade]), corner(bare)) < 6.0)
    gt = patch(arrays[t_grade], "trang")
    truthy("o 7: chu the trung tinh van song sau khi xoay hue (%d,%d,%d)"
           % tuple(gt.astype(int)), dist(gt, src_of("trang")) < 12.0)
    gsrc = patch(arrays[t_none], "do")
    gtint = patch(arrays[t_grade], "do")
    truthy("o 7: hue +90 DO THAT mau do (%d,%d,%d -> %d,%d,%d, lech %.0f > 25)"
           % (*gsrc.astype(int), *gtint.astype(int), dist(gsrc, gtint)),
           dist(gsrc, gtint) > 25.0)

    cols, rows = 2, (len(tiles) + 1) // 2
    label_h, pad = 22, 8
    sheet = QImage(cols * (TW + pad) + pad, rows * (TH + label_h + pad) + pad,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#0c0c10"))
    p = QPainter(sheet)
    p.setFont(QFont("Segoe UI", 10))
    for i, (label, a) in enumerate(tiles):
        rgb = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
        img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.shape[1] * 3,
                     QImage.Format.Format_RGB888).copy()
        x = pad + (i % cols) * (TW + pad)
        y = pad + (i // cols) * (TH + label_h + pad)
        p.drawImage(x, y, img)
        p.setPen(QColor("#e8e8ee"))
        p.drawText(x + 2, y + TH + 15, label)
    p.end()
    truthy("luu duoc sheet render", sheet.save(OUT_SHEET), OUT_SHEET)

    edit = ClipPropertiesWidget(chroma_clip)
    edit.resize(320, 1000)
    card = edit.card_chroma
    pm = card.grab()
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    row = img.bytesPerLine()
    a = np.frombuffer(img.constBits(), np.uint8,
                      count=row * img.height()).reshape(
        img.height(), row // 4, 4)[:, :img.width(), 3]
    alpha = int((a > 8).sum())
    truthy("the Duc nen ve ra co pixel (%dx%d, %d diem alpha)"
           % (pm.width(), pm.height(), alpha), alpha > 5000)
    labels = {key: value_label.text()
              for key, (slider, value_label, fmt, unit)
              in edit._chroma_widgets.items()}
    truthy("nhan tren the doc lai dung bo so cua clip (%s)" % labels,
           labels.get("tolerance") == "0.30" and labels.get("feather") == "0.25")
    truthy("o mau hien hex va RGB cua mau khoa (%s)" % edit.lbl_key_name.text(),
           "#00B140" in edit.lbl_key_name.text()
           and "(0,177,64)" in edit.lbl_key_name.text())
    truthy("the Duc nen khong bi an khi clip la anh", not card.isHidden(),
           str(card.isHidden()))
    truthy("luu duoc anh the dieu khien", pm.save(OUT_CARD), OUT_CARD)
    edit.deleteLater()
    app.processEvents()

    from PIL import Image
    for path in (OUT_SHEET, OUT_CARD):
        with Image.open(path) as im:
            im.load()
            colours = len(im.convert("RGB").getcolors(100000) or [])
            truthy("mo lai %s: %dx%d, %d mau" % (os.path.basename(path),
                                                 im.width, im.height, colours),
                   im.width > 100 and im.height > 100 and colours > 40)

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
