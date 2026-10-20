"""
core/thumbnail_export.py

Trich xuat HANG LOAT anh nho tu MOT video: moi anh mot file PNG dat ten theo
moc thoi gian, them contact sheet 5x5 de xem lai ca lot trong mot lan mo.

Vi sao dung SequentialVideoReader chu khong goi extract_frame_image() cho tung
moc: do tren may cau hinh thap (scratch/perf_baseline.json), mo container +
seek + doc + dong = 492 ms/anh, trong khi doc tiep tren capture da mo chi 28
ms. Lot 24 moc theo kieu cu ton ~12 giay; theo duong nay ~1 giay va chi tang
theo so frame phai vuot, khong tang theo so moc.

Moc thoi gian quy ra chi so frame bang frame_index_at() — cua duy nhat cho ca
app — nen "frame_0002.5s.png" chinh la khung ma preview bao tai cung moc tren
timeline.
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from core.media_frame import (SequentialVideoReader, extract_frame_image,
                              qimage_from_bgr)

MODE_COUNT = "count"        # N anh cach deu nhau trong khoang
MODE_INTERVAL = "interval"  # mot anh moi X giay

MAX_FRAMES = 2000          # tran an toan: 2000 anh van la bot dia, khong phai lot
SHEET_COLUMNS = 5
SHEET_ROWS = 5             # 5x5 = 25 o mot sheet, vuot thi sang sheet moi
CELL_GAP = 8
SHEET_MARGIN = 10
LABEL_HEIGHT = 24
SHEET_BACKGROUND = QColor(20, 20, 26)
SHEET_TEXT = QColor(201, 201, 209)


def video_info(file_path: str) -> dict:
    """{width, height, fps, duration} cua nguon; {} khi khong doc duoc."""
    from core.media_extractor import get_video_metadata
    return get_video_metadata(file_path) or {}


def plan_times(total_seconds, mode=MODE_COUNT, count=12, interval=2.0,
               start=0.0, end=None):
    """Danh sach moc giay tang dan, luon nam trong [start, end].

    MODE_COUNT lay theo DIEM GIUA cua N o bang nhau (start + (i+0.5)*step) chu
    khong chia deu tu dau den cuoi: moc dung `end` nam sat EOF, va voi mot so
    container OpenCV tra khong duoc frame cuoi — minh mat khung cuoi tran chi
    vi chon mot moc bien. Diem giua thia nua buoc o hai dau van du N khung phu
    het khoang.

    MODE_INTERVAL bat dau tu dung `start`: nguoi dung nhap "moi 2 giay" thi
    mong thay 0.0, 2.0, 4.0 chu khong phai 1.0, 3.0.
    """
    total = max(0.0, float(total_seconds or 0.0))
    if total <= 0:
        return []
    begin = min(max(0.0, float(start)), total)
    stop = total if end is None else min(max(begin, float(end)), total)
    span = stop - begin
    if span <= 0:
        return [round(begin, 3)]
    if mode == MODE_INTERVAL:
        step = max(0.001, float(interval))
        n = min(MAX_FRAMES, int(math.floor(span / step)) + 1)
        return [round(begin + i * step, 3) for i in range(n)]
    n = max(1, min(int(count), MAX_FRAMES))
    step = span / n
    return [round(begin + (i + 0.5) * step, 3) for i in range(n)]


def frame_name(seconds, digits=1) -> str:
    """frame_0002.5s.png: ten tu noi moc nguon, va vi phan nguyen zero-pad 4
    chu so nen thu theo ten cung la thu theo thoi gian."""
    fmt = "frame_%0" + str(5 + int(digits)) + "." + str(int(digits)) + "fs.png"
    return fmt % max(0.0, float(seconds))


def time_label(seconds, digits=1) -> str:
    """Chu duoi moi o cua sheet — CUNG do chinh xac voi ten file cua no."""
    return ("%%.%dfs" % int(digits)) % max(0.0, float(seconds))


def _naming_digits(times):
    """So le thap phan can thiet de ten file khong va cham nhau.

    Mot so sau dau phay la ten ma nguoi doc duoc, nhung lot moc day hon 0.1
    giay (interval 0.05s) se cho hai moc cung mot ten — va ghi de la MAT FILE
    IM LANG, khong bao gio ho. Cac moc ay quy ve cung mot frame nguon nen lot
    3 so le van giu duoc ca hai, chi khi that bai moi dung den no.
    """
    for digits in (1, 3):
        if len({frame_name(t, digits) for t in times}) == len(times):
            return digits
    return 3


def _unique_plan(times, digits):
    """[(moc giay, ten file)] tang dan, moi ten xuat hien dung mot lan.

    Hai moc con trung ten sau khi da nang len 3 so le la hai moc cach nhau
    < 0.0005 giay, tuc cung mot frame nguon: giu moc dau con hon de hai lan
    ghi trung mot duong dan.
    """
    plan = []
    seen = set()
    for seconds in sorted({max(0.0, float(t)) for t in (times or [])}):
        name = frame_name(seconds, digits)
        if name in seen:
            continue
        seen.add(name)
        plan.append((seconds, name))
    return plan


def default_output_dir(file_path: str) -> str:
    """<ten video>_thumbnails ngay canh file nguon."""
    return os.path.splitext(os.path.abspath(file_path))[0] + "_thumbnails"


def unique_output_dir(file_path: str) -> str:
    """Mac dinh cua default_output_dir nhung khong de hai lot tron vao nhau:
    lot sau dang sau _2, _3 — tron anh thi khong the phat hien bang mat."""
    folder = default_output_dir(file_path)
    if not os.path.isdir(folder):
        return folder
    index = 2
    while os.path.isdir("%s_%d" % (folder, index)):
        index += 1
    return "%s_%d" % (folder, index)


def cell_size(file_path: str, width: int):
    """(rong, cao) cua mot anh trong lot. Lay ti le tu metadata nguon de sheet
    khong bi keo lech, va de hop thoai hien kich thuoc that truoc khi xuat."""
    info = video_info(file_path)
    out_w = max(16, int(width))
    src_w = int(info.get("width") or 0)
    src_h = int(info.get("height") or 0)
    if src_w <= 0 or src_h <= 0:
        return out_w, max(1, int(round(out_w * 9.0 / 16.0)))
    return out_w, max(1, int(round(out_w * float(src_h) / float(src_w))))


def _image_at(reader, file_path, seconds):
    """(QImage, chi so frame that) tai mot moc; QImage trong = khong lay duoc.

    Duong cham ffmpeg chi chay khi OpenCV that bai het (codec OpenCV khong doc
    hoac moc vuot EOF): no la lu chon, khong phai duong chinh.
    """
    frame = reader.read_bgr(seconds)
    if frame is not None:
        return qimage_from_bgr(frame), reader.last_index
    image = extract_frame_image(file_path, seconds)
    if image.isNull():
        return QImage(), None
    return image, None


def _write_sheet(cells, output_dir, index, cell_w, cell_h, digits):
    """cells = [(seconds, QImage da vung trong o), ...], toi da 25 o.

    Anh ve giua theo chieu doc cua phan anh: KeepAspectRatio co the tra be nho
    hon cell_h (nguon doc), ne sat day thi sheet nom ga gu.
    """
    rows = max(1, int(math.ceil(len(cells) / float(SHEET_COLUMNS))))
    block_h = cell_h + LABEL_HEIGHT
    canvas_w = (SHEET_MARGIN * 2 + SHEET_COLUMNS * cell_w
                + (SHEET_COLUMNS - 1) * CELL_GAP)
    canvas_h = SHEET_MARGIN * 2 + rows * block_h + (rows - 1) * CELL_GAP
    sheet = QImage(canvas_w, canvas_h, QImage.Format_RGB32)
    sheet.fill(SHEET_BACKGROUND)
    painter = QPainter(sheet)
    painter.setPen(SHEET_TEXT)
    font = QFont()
    font.setPixelSize(max(11, int(LABEL_HEIGHT * 0.58)))
    painter.setFont(font)
    try:
        for position, (seconds, image) in enumerate(cells):
            column = position % SHEET_COLUMNS
            row = position // SHEET_COLUMNS
            x = SHEET_MARGIN + column * (cell_w + CELL_GAP)
            y = SHEET_MARGIN + row * (block_h + CELL_GAP)
            painter.drawImage(x + (cell_w - image.width()) // 2,
                              y + (cell_h - image.height()) // 2, image)
            # Cung do chinh xac voi ten file: o ghi "0.1s" trong khi ben canh
            # no la frame_0000.050s.png thi sheet thanh ra khoi loi doc.
            painter.drawText(x, y + cell_h + LABEL_HEIGHT - 7,
                             time_label(seconds, digits))
    finally:
        painter.end()
    path = os.path.join(output_dir, "contact_sheet_%02d.png" % index)
    return path if sheet.save(path, "PNG") else None


def _flush_sheet(pending, result, output_dir, index, cell_w, cell_h, digits):
    path = _write_sheet(pending, output_dir, index, cell_w, cell_h, digits)
    if path:
        result["sheets"].append(path)
    del pending[:]


def export_thumbnails(file_path, times, output_dir, width=640,
                      contact_sheet=True, progress=None, should_cancel=None,
                      on_frame=None):
    """Ghi PNG cho tung moc + contact sheet, tra ket qua cho caller bao cao.

    {written, sheets, missing, cancelled, fps, cell}: `missing` la moc khong
    lay duoc anh (EOF/codec), `cancelled` nghia la dung giua lot — sheet chua
    du 25 o van ghi vi do la thanh qua dung duoc.

    `times` sap lai tang dan va khong trung trong ham: decoder chi chay toi, nen
    mot lot khong theo thu tu se keo day seek nguoc ve dau video; hai moc cung
    mot ten file thi mot trong hai bi ghi de.

    `on_frame(seconds, index, path)` cho caller biet CHI SO FRAME THAT cua tung
    anh. Ten file do moc giay dat ra, con "thuc te la frame so may" phai do
    chinh decoder bao — so sanh bang mat canh tranh khong phat hien duoc lech
    mot khung.

    Dieu kien: contact_sheet=True ve bang QPainter nen can mot QGuiApplication
    dang song. Duong cua app luon dap ung; script chay ngoai GUI thi truyen
    contact_sheet=False, neu khong Qt abort giua luc dang xuat lot.
    """
    digits = _naming_digits(sorted({max(0.0, float(t)) for t in (times or [])}))
    plan = _unique_plan(times, digits)
    total = len(plan)
    os.makedirs(output_dir, exist_ok=True)
    cell_w, cell_h = cell_size(file_path, width)
    result = {"written": [], "sheets": [], "missing": [], "cancelled": False,
              "fps": 0.0, "cell": (cell_w, cell_h)}
    if total == 0:
        return result

    reader = SequentialVideoReader(file_path)
    pending = []
    sheet_index = 1
    try:
        for done, (seconds, name) in enumerate(plan, start=1):
            if should_cancel is not None and should_cancel():
                result["cancelled"] = True
                break
            image, index = _image_at(reader, file_path, seconds)
            result["fps"] = reader.fps or result["fps"]
            saved = None
            if not image.isNull():
                image = image.scaled(cell_w, cell_h, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                candidate = os.path.join(output_dir, name)
                if image.save(candidate, "PNG"):
                    result["written"].append(candidate)
                    pending.append((seconds, image))
                    saved = candidate
            if saved is None:
                result["missing"].append(seconds)
            elif on_frame is not None:
                on_frame(seconds, index, saved)
            if contact_sheet and len(pending) >= SHEET_COLUMNS * SHEET_ROWS:
                _flush_sheet(pending, result, output_dir, sheet_index, cell_w,
                             cell_h, digits)
                sheet_index += 1
            if progress is not None:
                progress(done, total, seconds)
        if contact_sheet and pending:
            _flush_sheet(pending, result, output_dir, sheet_index, cell_w,
                         cell_h, digits)
    finally:
        reader.close()
    return result


def export_video_thumbnails(file_path, output_dir, mode=MODE_COUNT, count=12,
                            interval=2.0, start=0.0, end=None, width=640,
                            contact_sheet=True, progress=None,
                            should_cancel=None, on_frame=None):
    """plan_times() + export_thumbnails() trong mot goi — duong hop thoai dung."""
    times = plan_times(video_info(file_path).get("duration", 0.0), mode, count,
                       interval, start, end)
    return export_thumbnails(file_path, times, output_dir, width,
                             contact_sheet, progress, should_cancel, on_frame)
