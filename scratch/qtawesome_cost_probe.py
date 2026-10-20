"""Phan rai 1,4 s cua qtawesome thanh nhung thu that su thay the duoc duoc.

    python scratch/qtawesome_cost_probe.py

boot_low_spec_probe do duoc: stub qtawesome tiet kiem 1,419 s boot va 37 MB
working set, cay widget giong het baseline. Con so do la TOI DA cua mot lan
swap, vi stub khong ve bat ky icon nao. Muon biet bao nhieu la that thi phai tam
no ra thanh:

  import qtawesome         -- thu that su loai bo duoc
  nap font + charmap       -- thu phai lam lai, nhung cua ta tu lam duoc
  sinh 208 QIcon + pixmap  -- KHONG the bo; phai do cua phe thay the de so san

Phep so san be duoi: doc thang charmap cua qtawesome, nap file .ttf no bang
QFontDatabase.addApplicationFont, roi ve cung glyph do bang QPainter. Neu cach
nay van mat ~0,9 s thi swap chi con gia tri 0,5 s, va Ke hoach "bo qtawesome"
phai viet lai.

Vi sao khong dung QT_QPA_PLATFORM=offscreen: may nay offscreen tra ve 0 ho font,
moi glyph in ra trong = phep do khong do duoc gi. Chay windows platform that.
Dem alpha pixel chu khong tin isNull(): icon co the non-null ma ve 0 pixel.
"""

import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch", "qtawesome_cost.json")
PATTERN = re.compile(r'"(fa6s|fa6r|fa6b|fa5|fa5s|fa)\.[a-z0-9\-]+"')
SIZE = 16


def used_names():
    names = {}
    for root in ("ui", "widgets", "core", "theme"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                for match in PATTERN.finditer(open(path, encoding="utf-8").read()):
                    names.setdefault(match.group(0).strip('"'), True)
    return sorted(names)


def ws_kib():
    import ctypes
    import ctypes.wintypes as wt

    class C(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [
            (n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(C), wt.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wt.BOOL
    c = C()
    c.cb = ctypes.sizeof(c)
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise SystemExit("K32GetProcessMemoryInfo = 0 (tem RAM hong)")
    return int(c.WorkingSetSize // 1024), int(c.PrivateUsage // 1024)


def painted(pm):
    """Ty le pixel co alpha, tren pixmap that cua Qt (DPR co the >1)."""
    img = pm.toImage()
    solid = sum(1 for y in range(img.height()) for x in range(img.width())
                if (img.pixel(x, y) >> 24) & 0xFF)
    return solid / float(img.width() * img.height())


def main():
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPixmap)
    from PySide6.QtWidgets import QApplication

    names = used_names()
    app = QApplication(sys.argv[:1])
    base_ws, base_priv = ws_kib()
    report = {"names": len(names), "size_px": SIZE,
              "platform": app.platformName(), "dpr": app.devicePixelRatio()}

    t0 = time.perf_counter()
    import qtawesome as qta
    report["import_s"] = round(time.perf_counter() - t0, 3)
    ws, priv = ws_kib()
    report["import_ws_kib"] = ws - base_ws
    report["import_private_kib"] = priv - base_priv

    t0 = time.perf_counter()
    first = qta.icon(names[0], color="#FFFFFF").pixmap(SIZE, SIZE)
    report["first_icon_s"] = round(time.perf_counter() - t0, 3)
    ws1, priv1 = ws_kib()
    report["first_icon_ws_kib"] = ws1 - ws
    report["first_icon_private_kib"] = priv1 - priv
    report["first_icon_painted"] = round(painted(first), 3)

    t0 = time.perf_counter()
    icons = [qta.icon(n, color="#FFFFFF") for n in names]
    report["build_icons_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    pixmaps = [ic.pixmap(SIZE, SIZE) for ic in icons]
    report["render_pixmaps_s"] = round(time.perf_counter() - t0, 3)
    ws2, priv2 = ws_kib()
    report["all_icons_ws_kib"] = ws2 - base_ws
    report["all_icons_private_kib"] = priv2 - base_priv
    blanks = [n for n, pm in zip(names, pixmaps) if painted(pm) < 0.02]
    report["blank_count"] = len(blanks)
    report["blank_names"] = blanks[:20]

    # Be duoi cho phep thay the: cung charmap, cung glyph, ve bang QPainter
    # truc tiep tren QImage, khong qua QIcon/qtawesome.
    family = qta._instance().fontname["fa6s"]
    font_bytes = qta._instance().fontdata["fa6s"]
    codepoints = qta._instance().charmap["fa6s"]
    fa6s = [n for n in names if n.startswith("fa6s.")]
    report["names_fa6s"] = len(fa6s)
    missing = [n for n in fa6s if n.split(".", 1)[1] not in codepoints]
    report["charmap_missing"] = missing[:20]
    img = QImage(SIZE * len(fa6s), SIZE * 2, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    font = QFont(family)
    font.setPixelSize(SIZE)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    t0 = time.perf_counter()
    drawn = 0
    for i, name in enumerate(fa6s):
        short = name.split(".", 1)[1]
        cp = codepoints.get(short)
        if cp is None:
            continue
        # charmap cua qtawesome luu ma unicode dang CHU KY tu ('\\uf100'), khong
        # phai chu hex — thu ca hai cach de bo thay the sau nay khong dinh vien
        # vao mot kieu.
        glyph = cp if isinstance(cp, str) and len(cp) == 1 else \
            chr(int(cp, 16) if isinstance(cp, str) else int(cp))
        x = i * SIZE * 2
        painter.drawText(QRect(x, 0, SIZE * 2, SIZE * 2),
                         Qt.AlignCenter, glyph)
        drawn += 1
    painter.end()
    report["qpainter_all_s"] = round(time.perf_counter() - t0, 3)
    report["qpainter_drawn"] = drawn
    report["qpainter_family"] = family
    # qtawesome giu font trong dang BYTES, khong phai file tren dia: mot bo thay
    # the phai co file .ttf cua no (cat ra day la buoc bat buoc khi lap dat).
    report["fa6s_font_bytes"] = len(font_bytes)
    report["fa6s_font_md5"] = __import__("hashlib").md5(font_bytes).hexdigest()
    strip = sum(1 for y in range(img.height()) for x in range(img.width())
                if (img.pixel(x, y) >> 24) & 0xFF)
    report["qpainter_painted_fraction"] = round(
        strip / float(img.width() * img.height()), 4)

    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(report, indent=1, ensure_ascii=False))

    qta_total = (report["import_s"] + report["first_icon_s"]
                 + report["build_icons_s"] + report["render_pixmaps_s"])
    print("\nqtawesome cong quy %s %s ten: %.3f s (import %.3f + font/icon dau %.3f "
          "+ build %.3f + render %.3f)"
          % ("fa6s/fa6r" , report["names"], qta_total, report["import_s"],
             report["first_icon_s"], report["build_icons_s"],
             report["render_pixmaps_s"]))
    print("cach ve glyph truc tiep (be duoi cua mot bo thay the): %.3f s cho %d glyph"
          % (report["qpainter_all_s"], report["qpainter_drawn"]))
    print("=> mot swap thuc te tiet kiem nhieu nhat %.3f s, it nhat %.3f s"
          % (qta_total, max(0.0, qta_total - report["qpainter_all_s"])))
    if report["blank_count"]:
        print("CANH BAO: %d ten khong ve pixel nao qua qtawesome"
              % report["blank_count"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
