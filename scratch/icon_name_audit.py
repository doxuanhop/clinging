"""Ke danh sach ten font icon ma UI dang dung va do ten nao khong ton tai.

qtawesome bao loi khi ten nam ngoai bo Font Awesome Free, nen moi ten phai
duoc kiem tra bang chinh ham qta.icon() - khong phai doc bang ten thu cong.
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
app = QApplication([])
import qtawesome as qta

PATTERN = re.compile(r'"(fa6s|fa6r|fa6b|fa5|fa5s|fa)\.[a-z0-9\-]+"')
used = {}
for root in ("ui", "widgets", "core", "theme"):
    for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            text = open(path, encoding="utf-8").read()
            for lineno, line in enumerate(text.splitlines(), 1):
                for match in PATTERN.finditer(line):
                    icon_name = match.group(0).strip('"')
                    used.setdefault(icon_name, []).append(
                        "%s:%d" % (rel, lineno))

bad = []
blank = []
for icon_name in sorted(used):
    try:
        pm = qta.icon(icon_name, color="#FFFFFF").pixmap(16, 16)
    except Exception as exc:
        bad.append((icon_name, str(exc), used[icon_name]))
        continue
    image = pm.toImage()
    solid = sum(1 for y in range(image.height()) for x in range(image.width())
                if image.pixel(x, y) & 0xFF)
    if solid / float(16 * 16) < 0.02:
        blank.append((icon_name, used[icon_name]))

print("tong so ten icon du dung: %d" % len(used))
for icon_name, err, sites in bad:
    print("  VO HIEU %s  (%s)" % (icon_name, err))
    for s in sites:
        print("      %s" % s)
for icon_name, sites in blank:
    print("  TRONG (khong ve pixel nao): %s" % icon_name)
    for s in sites:
        print("      %s" % s)

# ── Lop 2: khong goi qta.icon() ma bo tham so mau ────────────────
# qtawesome voi mau mac dinh sinh ra pixmap 0 pixel khong trong, tuc la
# icon in trong lo. Moi lan goi phai nuong mau ro rang.
RAW = re.compile(r'(?:_qta\(\)|qta)\.icon\(')


def call_segments(text):
    """Yield (start_lineno, chuoi_than) cho moi lan goi, tinh theo ngoecon
    duoc can bang chu khong theo dong: goi _qta().icon(\n  "...", color=..)
    nam tren hai dong ma van co mau day du."""
    for match in RAW.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        yield (text.count("\n", 0, match.start()) + 1, text[match.end():index - 1])


nocolor = []
for root in ("ui", "widgets", "core", "theme"):
    for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            text = open(path, encoding="utf-8").read()
            for lineno, segment in call_segments(text):
                if "color=" not in segment:
                    nocolor.append("%s:%d %s" % (
                        rel, lineno, ("_qta().icon(" + segment).strip()[:70]))
for entry in nocolor:
    print("  KHONG MAU: %s" % entry)


def detector_proves_itself():
    """Phan bang may do: doan van xuyen dong co mau KHONG bi phan, con
    goi mot dong khong mau thi van bi phan."""
    samples = [
        ('setIcon(_qta().icon(\n    "fa6s.list", color="#40E0D0"))\n', 0),
        ('_qta().icon("fa6s.list")\n', 1),
        ('_qta().icon("fa6s.list", color="#6E7180")\n', 0),
        ('x = qta.icon(\n  "fa6s.xmark", color=_c())\n', 0),
    ]
    ok = True
    for text, want in samples:
        got = sum(1 for _, seg in call_segments(text) if "color=" not in seg)
        if got != want:
            ok = False
            print("  MAY DO SAI: %r do duoc %d, can %d" % (text, got, want))
    print("  may do phan biet multi-line co mau / goi khong mau: %s" % ok)
    return ok


if not detector_proves_itself():
    nocolor.append("may-do-selftest")

print("\nso ten vo hieu: %d, so ten trong: %d, so goi khong mau: %d"
      % (len(bad), len(blank), len(nocolor)))
sys.exit(1 if bad or blank or nocolor else 0)
