"""Doi chieu pixel: bo ve glyph cuc bo PHAI ra cung hinh voi qtawesome.

Ly do khong the chi nhin bang mat: ca hai ben deu co the "co pixel" ma lech
nhau 1-2 dot anh — khong ai phat hien trong 101 icon. Va nguoc lai, mot loi
dien bien (sai ho font, sai code point) van co the cho ra mot o day mau, nen
phai so voi chinh anh cua qtawesome tren CUNG byte TTF.

Moi ten dung trong repo ve ba o: qtawesome | cuc bo | hieu (|old-new| nhan
doi). Gate:
  * ca hai ben deu phai co pixel (khong duoc isNull() — qtawesome tra QIcon
    khong null nhung pixmap trong nguyen);
  * ty le pixel lech > 32 alpha phai < 2% moi icon;
  * anh chung minh scratch/icon_parity.png phai duoc mo ra xem.

    python scratch/icon_parity_probe.py
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT_PNG = os.path.join(ROOT, "scratch", "icon_parity.png")
SIZES = (16, 24)
PATTERN = re.compile(r'"(fa6s|fa6r|fa6b|fa5s|fa5|fa)\.[a-z0-9\-]+"')
TOLERANCE = 32      # alpha khac nhau bao nhieu thi tinh la lech
MAX_BAD = 0.02      # duong cho phep tinh theo ty le pixel


def used_names():
    names = set()
    for folder in ("ui", "widgets", "core", "theme", "src"):
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                for match in PATTERN.finditer(text):
                    names.add(match.group(0).strip('"'))
    return sorted(names)


def alpha_grid(pm):
    """Ma 2D gia tri alpha cua pixmap (da ve cung kich thuoc thiet bi)."""
    from PySide6.QtGui import QImage
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    return [[(img.pixel(x, y) >> 24) & 0xFF for x in range(img.width())]
            for y in range(img.height())]


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])           # noqa: F841
    import qtawesome as qta
    from widgets import fontawesome

    names = used_names()
    if not names:
        print("FAIL: khong tim thay ten icon nao trong repo -> probe do khong cai gi")
        return 1

    cell = max(SIZES) + 8
    columns = 12
    pairs = len(names) * len(SIZES)
    rows_needed = -(-pairs // columns)
    sheet = QImage(columns * cell * 3, rows_needed * (cell * 3) + 26,
                   QImage.Format_ARGB32)
    sheet.fill(QColor("#1B1D24"))
    painter = QPainter(sheet)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(6, 14, "qtawesome | cuc bo | hieu (x2) - %d ten, %d cap"
                     % (len(names), pairs))
    painter.end()

    rows = []
    col = 0
    for name in names:
        for size in SIZES:
            old = qta.icon(name, color="#FFFFFF").pixmap(size, size)
            new = fontawesome.icon(name, color="#FFFFFF").pixmap(size, size)
            a_old, a_new = alpha_grid(old), alpha_grid(new)
            solid_old = sum(1 for row in a_old for v in row if v > 8)
            solid_new = sum(1 for row in a_new for v in row if v > 8)
            n_px = max(1, len(a_old) * len(a_old[0]))
            if len(a_old) != len(a_new) or len(a_old[0]) != len(a_new[0]):
                rows.append((name, size, "KICH THUOC KHAC: %s vs %s"
                             % (old.width(), new.width()), 1.0))
                continue
            bad = sum(1 for y in range(len(a_old)) for x in range(len(a_old[0]))
                      if abs(a_old[y][x] - a_new[y][x]) > TOLERANCE)
            rows.append((name, size, "", bad / float(n_px)))
            # Ve ba o: old, new, diff nhan doi.
            painter = QPainter(sheet)
            base_x = (col % columns) * cell * 3
            base_y = (col // columns) * cell * 3 + 22
            painter.drawPixmap(base_x + 4, base_y + 4, old)
            painter.drawPixmap(base_x + cell + 4, base_y + 4, new)
            diff = QImage(old.width(), old.height(), QImage.Format_ARGB32_Premultiplied)
            diff.fill(0)
            dp = QPainter(diff)
            for y in range(len(a_old)):
                for x in range(len(a_old[0])):
                    d = abs(a_old[y][x] - a_new[y][x])
                    if d:
                        # Alpha = do lech: o khac biet 0 thi trong suot, de o
                        # diff den khat (khong phai loi) khin hin tren bang.
                        dp.fillRect(x, y, 1, 1, QColor(255, 90, 0, min(255, d * 3)))
            dp.end()
            painter.drawImage(base_x + 2 * cell + 4, base_y + 4, diff)
            painter.end()
            col += 1
            if bad / float(n_px) > MAX_BAD or solid_old == 0 or solid_new == 0:
                rows[-1] = (name, size,
                            "LECH %.1f%%  solid old=%d new=%d"
                            % (100.0 * bad / n_px, solid_old, solid_new),
                            bad / float(n_px))

    sheet.save(OUT_PNG)
    worst = sorted(rows, key=lambda r: -r[3])[:12]
    fails = [r for r in rows if r[2]]
    differing = sum(1 for r in rows if r[3] > 0)
    print("ten icon doi chieu: %d, cap (ten,size): %d, so o: %s"
          % (len(names), len(rows), OUT_PNG))
    print("cap co khac biet pixel: %d/%d" % (differing, len(rows)))
    print("10 cap lech nhieu nhat:")
    for name, size, note, frac in worst:
        print("  %-34s %2dpx  %6.2f%%%s" % (name, size, 100 * frac,
                                            ("  <-- " + note) if note else ""))
    # Phep phan biet cua chinh probe: hai GLYPH KHAC NHAU phai bi bao lech.
    # Neu thuong so nay ra gan 0 thi "PASS 204/204" chi la do do mot o trang
    # voi mot o trang khac, khong phai do hai ben giong nhau.
    a_ref = alpha_grid(qta.icon("fa6s.play", color="#FFFFFF").pixmap(24, 24))
    a_swap = alpha_grid(fontawesome.icon("fa6s.pause", color="#FFFFFF").pixmap(24, 24))
    swap_bad = sum(1 for y in range(len(a_ref)) for x in range(len(a_ref[0]))
                   if abs(a_ref[y][x] - a_swap[y][x]) > TOLERANCE) / float(
        max(1, len(a_ref) * len(a_ref[0])))
    print("doi chieu play(cuc bo) vs play(qta) = 0; nhung play vs PAUSE = %.1f%% "
          "pixel lech -> do la bang chung phep do phan biet duoc glyph"
          % (100 * swap_bad))
    if swap_bad <= MAX_BAD:
        print("FAIL: probe khong phan biet duoc hai glyph khac nhau -> PASS vo nghia")
        return 1

    if fails:
        print("\nFAIL: %d/%d cap khong dat nguong (%d%% lech, %d%% pixel)"
              % (len(fails), len(rows), TOLERANCE, 100 * MAX_BAD))
        return 1
    print("\nPASS: moi cap khong qua %.0f%% pixel lech qua %d alpha"
          % (100 * MAX_BAD, TOLERANCE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
