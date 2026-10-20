"""
scratch/thumbnail_probe.py

Gate cho tinh nang trich xuat thumbnails hang loat (core/thumbnail_export.py +
ui/thumbnail_dialog.py + menu chuot phai tren card thu vien).

Chay:
    QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python scratch/thumbnail_probe.py

Nguon dung la video TY SINH 640x360/30fps/120 frame, moi frame ve 8 thanh den
trang = nhi phan cua CHI SO FRAME. Do la bang chung tuyet doi: mot PNG doc ra
tai moc giay nao thi phai co dung so frame do, lech mot khung duy nhat cung
dao ngoc thanh ra so khac. So sanh mat canh tranh khong lam duoc dieu nay vi
nhieu cua hai khung lien ke trong video nang giong het nhau.

Probe di QUA CHINH DUONG SAN XUAT (export_video_thumbnails, plan_times,
SequentialVideoReader) chu khong tai tao dau vao — mot probe tu ghep anh se
khong bao gio phat hien duoc loi quy doi giay -> chi so frame.

Phai co QApplication truoc khi ve contact sheet: QPainter do QImage abort ngot
(0xC0000409, khong traceback, rc=127) khi khong co QGuiApplication dang song.
"""

from __future__ import annotations

import os
import shutil
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Gate nay in ca nhan de UI co dau ("Trích xuất ảnh thu nhỏ…"). Redirect ra
# file thi stdout la cp1252 va crash giua chung — do that phai in duoc ra log
# moi do duoc, nen ep UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core import thumbnail_export as te  # noqa: E402  ROOT vua vao sys.path
from core.media_frame import frame_index_at

import bar_measure

TMP = os.path.join(ROOT, "scratch", "thumb_tmp")
SOURCE = os.path.join(TMP, "thumb_src.mp4")
BROKEN = os.path.join(TMP, "broken_src.mp4")
EVID_SHEET = os.path.join(ROOT, "scratch", "clinging_thumbnail_sheet.png")
EVID_FORM = os.path.join(ROOT, "scratch", "clinging_thumbnail_dialog.png")
EVID_DONE = os.path.join(ROOT, "scratch", "clinging_thumbnail_done.png")
# Grab cua RIENG thanh tien trinh, khong phai grab ca hop thoai: nut primary
# cung mau teal #40E0D0 va cao hon thanh rat nen, do ca cua so thi dinh dem
# chieu cao cai nut (lan do cu da nhu the va khong phat hien duoc gi).
EVID_BAR_RUN = os.path.join(ROOT, "scratch", "clinging_thumb_bar_running.png")
EVID_BAR_OLD = os.path.join(ROOT, "scratch", "clinging_thumb_bar_oldstyle.png")
EVID_BAR_BACK = os.path.join(ROOT, "scratch", "clinging_thumb_bar_restored.png")
WIDTH = 640
HEIGHT = 360
FPS = 30.0
FRAMES = 120          # 4.0 giay nguon
BAR_BAND = 20         # do mau o giua thanh, bo 20px hai ben lech bien doi
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%-4s %-58s got=%r want=%r"
          % ("PASS" if ok else "FAIL", name, got, want))
    if not ok:
        FAILS.append(name)
    return ok


def above(name, got, limit):
    ok = got > limit
    print("%-4s %-58s got=%r > %r" % ("PASS" if ok else "FAIL", name, got, limit))
    if not ok:
        FAILS.append(name)
    return ok


def true(name, condition):
    return check(name, bool(condition), True)


def note(name, value):
    print("     %-58s %r" % (name, value))


def pump(seconds):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def shot(widget, path):
    pix = widget.grab()
    pix.save(path)
    note("evidence: " + os.path.basename(path),
         "%dx%d %d bytes" % (pix.width(), pix.height(),
                             os.path.getsize(path) if os.path.exists(path) else -1))


def painted(pixmap):
    """So pixel CO MAU (alpha > 0) cua mot pixmap — icon khong mau van
    isNull()=False nen chi dem alpha moi phat hien icon trong."""
    from PySide6.QtGui import QImage
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    return sum(1 for y in range(image.height())
               for x in range(image.width())
               if image.pixelColor(x, y).alpha() > 0)


def build_synthetic(path):
    """Video 120 frame, frame i ve nhi phan cua i thanh 8 thanh dang dung."""
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS,
                             (WIDTH, HEIGHT))
    true("tao duoc nguon tong hop", writer.isOpened())
    for index in range(FRAMES):
        image = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        for bit in range(8):
            x0 = bit * (WIDTH // 8)
            image[:, x0:x0 + (WIDTH // 8)] = (
                255 if (index >> (7 - bit)) & 1 else 0)
        writer.write(image)
    writer.release()
    return path


def read_bits(image):
    """(chi so frame, 8 gia tri thanh) tu mot anh BGR/gray 640px rong."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) \
        if image.ndim == 3 and image.shape[2] == 3 else image
    scale = gray.shape[1] / float(WIDTH)
    values = []
    for bit in range(8):
        left = int(round(bit * (WIDTH // 8) * scale + BAR_BAND * scale))
        right = int(round(left + (WIDTH // 8 - 2 * BAR_BAND) * scale))
        band = gray[:, left:max(right, left + 1)]
        values.append(float(band.mean()) if band.size else 0.0)
    index = 0
    for value in values:
        index = (index << 1) | (1 if value > 128.0 else 0)
    return index, values


def certified_index(path):
    """Chi so frame MA CHINH ANH DANG KEE — doc lai PNG da ghi ra dia."""
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        return None, None
    return read_bits(image)


def cell_index(cell):
    """Chi so frame cua mot vung da cat ra tu contact sheet."""
    return read_bits(cell)[0]


def sheet_cell(sheet, position, cell_w, cell_h, top=0, height=None):
    """Cat mot vung trong o thu `position` cua contact sheet ra ndarray BGR."""
    block_h = cell_h + te.LABEL_HEIGHT
    column = position % te.SHEET_COLUMNS
    row = position // te.SHEET_COLUMNS
    x = te.SHEET_MARGIN + column * (cell_w + te.CELL_GAP)
    y = te.SHEET_MARGIN + row * (block_h + te.CELL_GAP) + top
    bottom = (y + cell_h) if height is None else (y + height)
    return sheet[y:bottom, x:x + cell_w]


def main():
    from PySide6.QtWidgets import QApplication
    # Phai song TRUOC khi ve sheet — xem docstring dau file.
    app = QApplication.instance() or QApplication(sys.argv)

    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    build_synthetic(SOURCE)
    with open(BROKEN, "wb") as handle:
        handle.write(b"day khong phai video\n" * 40)

    print("\n== 1. plan_times: toan moc thoi gian ==")
    check("duration 0 -> khong co moc", te.plan_times(0.0), [])
    check("duration am -> khong co moc", te.plan_times(-5.0), [])
    even = te.plan_times(4.0, te.MODE_COUNT, count=12)
    check("mode count tra du N moc", len(even), 12)
    check("moc tang dan", even, sorted(even))
    check("khong moc nao trung nhau", len(set(even)), len(even))
    check("buoc deu cua 12 moc tren 4s", round(even[1] - even[0], 3),
          round(4.0 / 12, 3))
    check("moc dau la DIEM GIUA o dau tien (khong phai 0.0)", even[0],
          round(4.0 / 12 / 2, 3))
    check("moc cuoi khong nam sat EOF", even[-1], round(4.0 - 4.0 / 24, 3))
    step_times = te.plan_times(4.0, te.MODE_INTERVAL, interval=2.0)
    check("mode interval: bat dau tu 0.0", step_times, [0.0, 2.0, 4.0])
    check("interval cua 0.5giay tren 4s co 9 moc",
          len(te.plan_times(4.0, te.MODE_INTERVAL, interval=0.5)), 9)
    check("interval bat dau tu 1.0 -> moc dau dung 1.0",
          te.plan_times(4.0, te.MODE_INTERVAL, interval=1.0, start=1.0)[:2],
          [1.0, 2.0])
    check("count=0 bi ken lai thanh 1", len(te.plan_times(4.0, count=0)), 1)
    check("count vuot tran bi ken",
          len(te.plan_times(4.0, count=te.MAX_FRAMES + 500)), te.MAX_FRAMES)
    check("interval=0 bi ken lai (khong vong lap vo han)",
          len(te.plan_times(1.0, te.MODE_INTERVAL, interval=0.0)),
          min(te.MAX_FRAMES, int(1.0 / 0.001) + 1))
    check("start vuot duration bi keo ve cuoi",
          te.plan_times(4.0, te.MODE_INTERVAL, interval=1.0, start=99.0),
          [4.0])
    check("end vuot duration bi ken theo duration",
          te.plan_times(4.0, te.MODE_INTERVAL, interval=1.0, end=99.0),
          [0.0, 1.0, 2.0, 3.0, 4.0])
    check("start==end -> dung mot moc",
          te.plan_times(4.0, te.MODE_COUNT, count=12, start=2.0, end=2.0),
          [2.0])
    check("start>end bi keo ve khoang hop le",
          te.plan_times(4.0, te.MODE_INTERVAL, interval=1.0, start=3.0,
                        end=1.0)[:1], [3.0])
    note("so moc thuc te cua 12 anh tren 4s", len(even))

    print("\n== 2. Export that: anh + chi so frame ty ke ==")
    out = os.path.join(TMP, "count12")
    certified = {}
    started = time.time()
    result = te.export_video_thumbnails(SOURCE, out, te.MODE_COUNT, count=12,
                                        width=320,
                                        on_frame=lambda s, i, p: certified.__setitem__(
                                            round(s, 3), (i, p)))
    elapsed = time.time() - started
    note("thoi gian xuat 12 anh 320px (giay)", round(elapsed, 2))
    check("ket qua tra ve duong dan file", len(result["written"]), 12)
    check("khong moc nao thieu", result["missing"], [])
    check("khong bi huy", result["cancelled"], False)
    check("fps do tu decoder", round(result["fps"], 3), FPS)
    check("kich thuoc o = ti le nguon", result["cell"], (320, 180))
    check("ten file theo moc giay", [os.path.basename(p) for p in
                                     sorted(result["written"])],
          [te.frame_name(t) for t in sorted(even)])
    check("du 1 contact sheet cho 12 anh", len(result["sheets"]), 1)
    expect = {round(t, 3): frame_index_at(t, FPS) for t in even}
    check("decoder bao dung chi so ma frame_index_at tinh",
          {t: v[0] for t, v in sorted(certified.items())}, expect)
    wrong = []
    for seconds, (index, path) in sorted(certified.items()):
        got, values = certified_index(path)
        if got != index or got != expect[seconds]:
            wrong.append((seconds, index, got, values))
    check("moi PNG tren dia ve dung nhi phan cua frame no", wrong, [])
    true("PNG dau tien co ca thanh den lan trang",
         len(set(certified_index(result["written"][0])[1])) >= 2)
    sample = cv2.imread(result["written"][0], cv2.IMREAD_COLOR)
    check("PNG co dung kich thuoc 320x180", None if sample is None
          else sample.shape[:2], (180, 320))

    print("\n== 3. Contact sheet: bo cuc va dung thu tu o ==")
    sheet_path = result["sheets"][0]
    shutil.copyfile(sheet_path, EVID_SHEET)
    sheet = cv2.imread(sheet_path, cv2.IMREAD_COLOR)
    true("doc lai duoc sheet", sheet is not None)
    cw, ch = result["cell"]
    want_w = te.SHEET_MARGIN * 2 + te.SHEET_COLUMNS * cw + (
        te.SHEET_COLUMNS - 1) * te.CELL_GAP
    want_h = te.SHEET_MARGIN * 2 + 3 * (ch + te.LABEL_HEIGHT) + 2 * te.CELL_GAP
    check("sheet 12 anh = 3 hang x 5 cot", sheet.shape[:2], (want_h, want_w))
    first = sheet_cell(sheet, 0, cw, ch)
    check("o 0 chua dung frame dau tien", cell_index(first), expect[even[0]])
    last_cell = sheet_cell(sheet, 11, cw, ch)
    check("o 11 chua dung frame cuoi cung", cell_index(last_cell),
          expect[even[-1]])
    empty = sheet_cell(sheet, 12, cw, ch)
    check("o 12 (trong) nguyen mau nen sheet",
          tuple(int(v) for v in empty[cw // 2, ch // 2]),
          (te.SHEET_BACKGROUND.blue(), te.SHEET_BACKGROUND.green(),
           te.SHEET_BACKGROUND.red()))
    above("co chu danh thoi gian duoi o 0",
          int(np.count_nonzero(
              cv2.cvtColor(sheet_cell(sheet, 0, cw, ch,
                                      top=ch, height=te.LABEL_HEIGHT),
                           cv2.COLOR_BGR2GRAY) > 128)), 40)

    print("\n== 4. Mode interval + khoang thoi gian con han ==")
    out2 = os.path.join(TMP, "interval")
    got2 = te.export_video_thumbnails(SOURCE, out2, te.MODE_INTERVAL,
                                      interval=0.5, start=1.0, end=2.0,
                                      width=160, contact_sheet=False)
    check("3 moc 1.0/1.5/2.0 -> 3 file", [os.path.basename(p) for p in
                                          sorted(got2["written"])],
          ["frame_0001.0s.png", "frame_0001.5s.png", "frame_0002.0s.png"])
    check("khong sheet khi tat", got2["sheets"], [])
    check("thieu hut trong khoang da chon", got2["missing"], [])
    pair = sorted((certified_index(p)[0], p) for p in got2["written"])
    check("chi so frame cua 1.0/1.5/2.0 giay la 30/45/60",
          [x[0] for x in pair],
          [frame_index_at(t, FPS) for t in (1.0, 1.5, 2.0)])

    print("\n== 5. Phan trang sheet va anh vuot EOF ==")
    check("kich thuoc o 120px van dung ti le nguon",
          te.cell_size(SOURCE, 120), (120, 68))
    out3 = os.path.join(TMP, "many")
    many = te.export_thumbnails(SOURCE, [i * 0.1 for i in range(40)], out3,
                                width=120)
    check("40 moc trong 4s -> 40 anh", len(many["written"]), 40)
    check("40 anh = 2 sheet 5x5 (25 + 15)", len(many["sheets"]), 2)
    check("ten sheet phan trang", [os.path.basename(p) for p in many["sheets"]],
          ["contact_sheet_01.png", "contact_sheet_02.png"])
    second = cv2.imread(many["sheets"][1], cv2.IMREAD_COLOR)
    check("sheet 2 chi 3 hang", second.shape[0],
          te.SHEET_MARGIN * 2 + 3 * (many["cell"][1] + te.LABEL_HEIGHT)
          + 2 * te.CELL_GAP)
    check("sheet 2 van day 5 cot", second.shape[1],
          te.SHEET_MARGIN * 2 + te.SHEET_COLUMNS * many["cell"][0]
          + (te.SHEET_COLUMNS - 1) * te.CELL_GAP)
    out4 = os.path.join(TMP, "eof")
    eof = te.export_thumbnails(SOURCE, [3.9, 5.0, 7.0], out4, width=160)
    check("moc trong nguon van ghi duoc", len(eof["written"]), 1)
    check("moc vuot EOF bi xep vao thieu hut", eof["missing"], [5.0, 7.0])
    check("sheet chi co 1 o duoc dien", len(eof["sheets"]), 1)

    print("\n== 6. Huy gitua lot giu thanh qua da ghi ==")
    counter = {"n": 0}

    def cancel_after_three():
        counter["n"] += 1
        return counter["n"] > 3

    out5 = os.path.join(TMP, "cancel")
    stopped = te.export_thumbnails(SOURCE, [i * 0.2 for i in range(20)], out5,
                                   width=120, should_cancel=cancel_after_three)
    check("dung sau 3 moc", len(stopped["written"]), 3)
    check("co co huy", stopped["cancelled"], True)
    check("sheet cua phan con lai van ghi", len(stopped["sheets"]), 1)
    check("chi ghi 3 file ra dia", len([n for n in os.listdir(out5)
                                        if n.startswith("frame_")]), 3)

    print("\n== 7. Thu muc mac dinh va xung dot ==")
    check("thu muc mac dinh ben canh nguon", te.default_output_dir(SOURCE),
          os.path.join(TMP, "thumb_src_thumbnails"))
    check("chua ton tai thi giu nguyen ten",
          te.unique_output_dir(SOURCE), os.path.join(TMP,
                                                    "thumb_src_thumbnails"))
    os.makedirs(te.default_output_dir(SOURCE), exist_ok=True)
    check("lot 2 them duoi _2", te.unique_output_dir(SOURCE),
          os.path.join(TMP, "thumb_src_thumbnails_2"))
    os.makedirs(os.path.join(TMP, "thumb_src_thumbnails_2"), exist_ok=True)
    check("lot 3 them duoi _3", te.unique_output_dir(SOURCE),
          os.path.join(TMP, "thumb_src_thumbnails_3"))

    print("\n== 8. Nguon mo khong duoc: van ket thuc sach ==")
    check("ffprobe khong ra metadata cho file gia", te.video_info(BROKEN), {})
    out6 = os.path.join(TMP, "broken")
    broken = te.export_thumbnails(BROKEN, [0.5, 1.0, 1.5, 2.0], out6,
                                  width=120)
    check("khong ghi duoc anh nao", broken["written"], [])
    check("moi moc deu la thieu hut", broken["missing"], [0.5, 1.0, 1.5, 2.0])
    check("khong co sheet rong", broken["sheets"], [])
    check("khong bi huy", broken["cancelled"], False)

    print("\n== 9. Khong de lai lot rong khi khong co moc ==")
    out7 = os.path.join(TMP, "empty_plan")
    empty_plan = te.export_thumbnails(SOURCE, [], out7, width=120)
    check("khong co moc thi khong co gi de ghi", empty_plan["written"], [])
    check("khong co sheet khi khong co anh", empty_plan["sheets"], [])
    check("khong moc nao bi goi la thieu hut", empty_plan["missing"], [])

    print("\n== 10. Counterfactual: chung minh cac gate doc duoc lech ==")
    # Nech "giay -> frame" = round, khong phai floor. Hai quy tac nay khac nhau
    # o moi moc le, va lech mot khung la loi he thong lon nhat cua tinh nang
    # nay (preview bao mot khung, PNG ghi ra mot khung khac). Mot gate chi
    # dung duoc neu co it nhat mot moc ma no co the phat hien su khac biet.
    discriminating = [t for t in even if frame_index_at(t, FPS) != int(t * FPS)]
    above("co moc ma round khac floor", len(discriminating), 0)
    probe_time = round(discriminating[0], 3)
    got_index, _ = certified_index(certified[probe_time][1])
    note("moc dung de phan biet hai quy tac", probe_time)
    check("PNG mang chi so ROUND chu khong phai FLOOR",
          (got_index, int(discriminating[0] * FPS)),
          (frame_index_at(probe_time, FPS), int(probe_time * FPS)))
    out8 = os.path.join(TMP, "unsorted")
    shuffled = te.export_thumbnails(SOURCE, list(reversed(even)), out8,
                                    width=320, contact_sheet=False)
    check("moc xap lung van ra du 12 anh", len(shuffled["written"]), 12)
    check("moc xap lung khong lech frame nao",
          [certified_index(p)[0] for p in sorted(shuffled["written"])],
          [frame_index_at(t, FPS) for t in even])
    check("du 12 file nam tren dia", len([n for n in os.listdir(out8)
                                          if n.startswith("frame_")]), 12)
    # O cua sheet khong the danh lia nhau: gate "o 0 = frame dau" chi co gia tri
    # neu frame cua o 1 THUC SU khac va nam o dung cho cua no.
    cell_one = sheet_cell(sheet, 1, cw, ch)
    check("o 1 chua dung frame thu hai", cell_index(cell_one), expect[even[1]])
    true("o 0 va o 1 khong the trao cho nhau",
         cell_index(first) != expect[even[1]])
    check("du 12 file PNG cua lot chinh tren dia",
          len([n for n in os.listdir(out) if n.startswith("frame_")]), 12)

    # Lot moc day hon 0.1 giay: hai moc co the cung tron ve mot ten 1 so le
    # (0.05 va 0.15 deu ra "0.1"). Ghi de la mat file im lang, nen lot day phai
    # tu dong nang len 3 so le va giu du 20 anh tren dia.
    out9 = os.path.join(TMP, "dense")
    dense = te.export_thumbnails(SOURCE, [i * 0.05 for i in range(20)], out9,
                                 width=120, contact_sheet=False)
    check("lot 0.05s giu du 20 moc", len(dense["written"]), 20)
    check("20 ten file khong trung nhau", len({os.path.basename(p) for p in
                                               dense["written"]}), 20)
    check("20 file that nam tren dia", len([n for n in os.listdir(out9)
                                            if n.startswith("frame_")]), 20)
    check("lot day chuyen sang ten 3 so le",
          os.path.basename(dense["written"][1]), "frame_0000.050s.png")
    check("ten lot rua van 1 so le", os.path.basename(result["written"][1]),
          "frame_0000.5s.png")
    check("chu duoi o cung do chinh xac voi ten file",
          (te.time_label(0.5, 1), te.time_label(0.05, 3)),
          ("0.5s", "0.050s"))

    print("\n== 11. Hop thoai: nguon, mac dinh, bat/tat theo che do ==")
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import QPushButton, QWidget
    from ui.thumbnail_dialog import ThumbnailDialog
    from widgets.common import Toast

    class StubLibrary(QWidget):
        def __init__(self, records):
            super().__init__()
            self._records = records

        def resource_records(self):
            return list(self._records)

    class StubWindow(QWidget):
        def __init__(self, records):
            super().__init__()
            self.library_panel = StubLibrary(records)
            self.timeline_panel = None

    records = [{"name": "src.mp4", "path": SOURCE, "type": "video"},
               {"name": "a.png", "path": result["written"][0], "type": "image"},
               {"name": "mat.mp4", "path": os.path.join(TMP, "no.mp4"),
                "type": "video"}]
    stub = StubWindow(records)
    dialog = ThumbnailDialog(stub, SOURCE)
    check("hop thoai chi liet ke video con tren dia",
          dialog.combo_source.count(), 1)
    check("chon dung video vua chuot phai",
          os.path.abspath(dialog._current_source()), SOURCE)
    check("gioi han tu/den theo thoi luong nguon",
          (dialog.spin_start.maximum(), dialog.spin_end.maximum()),
          (4.0, 4.0))
    check("thu muc mac dinh ngay canh nguon", dialog.edit_out.text(),
          te.unique_output_dir(SOURCE))
    check("thu muc mac dinh CHUA duoc tao",
          os.path.isdir(dialog.edit_out.text()), False)
    true("tom tat noi ro 12 anh", "12 ảnh" in dialog.lbl_summary.text())
    dialog.combo_mode.setCurrentIndex(1)
    check("che do chu ky: mo o giay, dong o so anh",
          (dialog.spin_count.isEnabled(), dialog.spin_interval.isEnabled()),
          (False, True))
    dialog.spin_interval.setValue(1.0)
    true("tom tat doi theo che do (5 moc moi 1s)",
         "5 ảnh" in dialog.lbl_summary.text())
    dialog.combo_mode.setCurrentIndex(0)
    check("che do deu: mo lai o so anh",
          (dialog.spin_count.isEnabled(), dialog.spin_interval.isEnabled()),
          (True, False))
    dialog.spin_count.setValue(6)
    dialog.combo_width.setCurrentIndex(0)
    true("tom tat hien kich thuoc 320px", "320×180" in dialog.lbl_summary.text())
    dialog.edit_out.setText(os.path.join(TMP, "dialog"))
    dialog.show()
    pump(0.25)
    from PySide6.QtWidgets import QScrollArea
    scroll = dialog.findChild(QScrollArea)
    bar = scroll.verticalScrollBar()
    check("kich thuoc mac dinh khong can thanh cuon", bar.isVisible(), False)
    check("kich thuoc mac dinh khong du thieu", bar.maximum(), 0)
    # Counterfactual: chinh thanh cuon PHAI xuat hien khi form bi nen, neu
    # khong thi hai check tren chi la do luon tra ve False.
    dialog.resize(600, 420)
    pump(0.2)
    above("form bi nen thi thanh cuon xuat hien that", bar.maximum(), 0)
    check("thanh cuon an duoc du lieu (khong chan cot phai)",
          scroll.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
    dialog.resize(600, 600)
    pump(0.2)
    check("tra lai kich thuoc cu thi het thanh cuon", bar.isVisible(), False)
    check("thang tien do an khi chua chay (form khong co chrome chet)",
          dialog.progress.isVisible(), False)
    shot(dialog, EVID_FORM)

    print("\n== 12. Chay that qua worker cua hop thoai ==")
    out_dir = dialog.edit_out.text()
    dialog._on_run()
    deadline = time.time() + 60
    while dialog._busy and time.time() < deadline:
        pump(0.05)
    check("worker da tra lai hop thoai", dialog._busy, False)
    check("thang tien do hien ra khi lot chay", dialog.progress.isVisible(), True)
    check("lot xong thi thang tien do day",
          (dialog.progress.value(), dialog.progress.maximum()),
          (dialog.progress.maximum(), dialog.progress.maximum()))
    # Chen do day that cua thanh vao giua luc no dang hien. Do tren grab cua
    # rieng no, cung thuoc do voi gate cat video (bar_measure.py):
    # hai hop thoai khac noi dung nhung phai cung mot chieu day va cung mot
    # phep do, neu khong mot cai nho cai to van im lang duoc.
    bar_now = bar_measure.teal_band_height(dialog.progress, EVID_BAR_RUN)
    above("thang tien trinh co pixel that khi day", bar_now, 3)
    check("thang tien trinh mong (<= 14 px anh, khong con 18px + vien)",
          bar_now <= 14, True)
    # Counterfactual: lap lai kieu cu (18px + vien 1px) tren cung widget ay.
    # Phep do khong nhay ra day hon thi no khong do gi ca.
    dialog.progress.setFixedHeight(20)
    dialog.progress.setStyleSheet("QProgressBar { border: 1px solid #262831;"
                                  " border-radius: 6px;"
                                  " background-color: #14151A; }")
    pump(0.05)
    bar_old = bar_measure.teal_band_height(dialog.progress, EVID_BAR_OLD)
    dialog.progress.setStyleSheet("")
    dialog.progress.setFixedHeight(8)
    pump(0.05)
    note("do day kieu cu -> kieu moi", "%d px -> %d px" % (bar_old, bar_now))
    above("phep do phat hien kieu cu day hon kieu moi", bar_old - bar_now, 3)
    # va phai tra ve dung con so cu, chung to grab khong doi mau theo lan do:
    check("phuc kieu mong thi tra dung con so ban dau",
          bar_measure.teal_band_height(dialog.progress, EVID_BAR_BACK), bar_now)
    res = dialog.last_result or {}
    check("6 anh duoc ghi", len(res.get("written", [])), 6)
    check("khong moc nao thieu", res.get("missing"), [])
    check("mot anh tong hop duoc ghi", len(res.get("sheets", [])), 1)
    check("6 file nam tren dia", len([n for n in os.listdir(out_dir)
                                      if n.startswith("frame_")]), 6)
    check("chi so frame cua lot hop thoai dung quy tac chung",
          [certified_index(p)[0] for p in sorted(res["written"])],
          [frame_index_at(t, FPS) for t in
           te.plan_times(4.0, te.MODE_COUNT, count=6)])
    true("trang thai bao da luu",
         dialog.lbl_status.text().startswith("Đã lưu"))
    toast = Toast._LIVE.get(id(dialog))
    true("co toast bao xong", toast is not None)
    labels = [b.text() for b in toast.findChildren(QPushButton)] if toast else []
    true("toast co nut mo thu muc", "Mở thư mục" in labels)
    check("toast dat tren chinh hop thoai (no non-modal nen khong chan)",
          toast.parent() is dialog if toast else False, True)
    pump(0.35)
    shot(dialog, EVID_DONE)
    if toast:
        toast.destroy_now()
    pump(0.05)
    dialog._on_failed("nguon bi hong gia lap")
    check("lot that bai thi thang tien do an di", dialog.progress.isVisible(),
          False)

    print("\n== 13. Nut Huy cua hop thoai dung worker giua lot ==")
    dialog2 = ThumbnailDialog(stub, SOURCE)
    dialog2.combo_mode.setCurrentIndex(0)
    dialog2.spin_count.setValue(40)
    dialog2.edit_out.setText(os.path.join(TMP, "dialog_cancel"))
    dialog2.show()
    pump(0.1)
    dialog2._on_run()
    task = dialog2._task
    true("task da duoc giao vao pool", task is not None)

    def stop_at_three(done, total, seconds):
        if done >= 3:
            task.cancel_event.set()

    task.signals.progress.connect(stop_at_three)
    deadline = time.time() + 60
    while dialog2._busy and time.time() < deadline:
        pump(0.05)
    res2 = dialog2.last_result or {}
    written2 = len(res2.get("written", []))
    above("lot bi dung van giu duoc anh da ghi", written2, 2)
    true("dung som hon toan lot 40 anh", written2 < 40)
    check("ket qua danh dau bi huy", res2.get("cancelled"), True)
    true("trang thai bao da dung",
         dialog2.lbl_status.text().startswith("Đã dừng"))
    check("lot bi dung khong toast 'xong'", Toast._LIVE.get(id(dialog2)), None)
    check("so file tren dia khop ket qua", len([n for n in
                                                os.listdir(dialog2.output_dir)
                                                if n.startswith("frame_")]),
          written2)
    dialog2.close()
    dialog.close()
    pump(0.1)

    print("\n== 14. Chuot phai card thu vien mo dung hop thoai ==")
    from ui.library_panel import ResourceCard
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(0.4)
    card = win.library_panel.add_resource(os.path.basename(SOURCE), "video",
                                          SOURCE)
    menu = card.context_menu()
    true("card video co menu", menu is not None)
    check("menu video co dung hai hanh dong", len(menu.actions()), 2)
    check("ten hanh dong dung chu de", menu.actions()[0].text(),
          "Trích xuất ảnh thu nhỏ…")
    above("icon cua hanh dong to that",
          painted(menu.actions()[0].icon().pixmap(QSize(16, 16))), 20)
    fired = []
    win.library_panel.thumbnailExportRequested.connect(fired.append)
    menu.actions()[0].trigger()
    check("hanh dong noi dung duong dan video",
          [os.path.abspath(p) for p in fired], [SOURCE])
    win_dialog = getattr(win, "_thumbnail_dialog", None)
    true("cua so chinh da mo hop thoai", win_dialog is not None)
    check("hop thoai chon dung nguon vua bam",
          os.path.abspath(win_dialog._current_source()), SOURCE)
    png_card = win.library_panel.add_resource("evid.png", "image",
                                              result["written"][0])
    check("card anh tinh khong co menu", png_card.context_menu(), None)
    ghost = ResourceCard("mat.mp4", "video", os.path.join(TMP, "nope.mp4"))
    check("card video da bi xoa khoi dia khong co menu",
          ghost.context_menu(), None)
    # Dong het cua so truoc khi thoat: cua song khi tien trinh ket thuc thi Qt
    # abort 0xC0000409 va probe doc ra rc=127 du moi gate da PASS.
    for widget in (win_dialog, card, png_card, ghost, win):
        widget.close()
        widget.deleteLater()
    pump(0.4)

    print("\n" + ("ALL PASS (0 fail)" if not FAILS else
                  "FAILURES: %d -> %s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
