"""Ke danh sach ten font icon ma UI dang dung va do ten nao khong ton tai.

Moi ten phai duoc kiem tra bang CHINH seam cua UI (`widgets.common._qta()`, tuc
la `widgets/fontawesome.py` sau khi bo qtawesome) — khong phai doc bang ten thu
cong, cung khong phai goi mot thu vien khac roi noi "ok". qtawesome van duoc
nap o day nhung chi voi mot vai tro: `charmap` cua no la oracle de phat hien
 Asset dump cua chung ta thieu ten ma Font Awesome Free that su co.
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
app = QApplication([])
from widgets.common import _qta

try:
    import qtawesome as _oracle
    _oracle_names = {("fa6s." + n) for n in _oracle._instance().charmap["fa6s"]}
except Exception as exc:  # khong co qtawesome thi van audit duoc
    _oracle_names = set()
    print("  (bo qua oracle qtawesome: %s)" % type(exc).__name__)

PATTERN = re.compile(r'"(fa6s|fa6r|fa6b|fa5|fa5s|fa)\.[a-z0-9\-]+"')
DIR_ROOTS = ("ui", "widgets", "core")
SINGLE_FILES = ("theme.py", "main.py")

used = {}
per_root = {}
sources = []
for root in DIR_ROOTS:
    found = []
    for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
        found += [os.path.join(dirpath, name) for name in files
                  if name.endswith(".py")]
    per_root[root] = found
    sources += found
for rel in SINGLE_FILES:
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        raise SystemExit("thieu nguon audit: %s" % rel)
    sources.append(path)

# Mot goc walk khong ton tai sinh ra 0 file LANG LANG chu khong bao loi: goc
# "theme" tung bi nhu vay (theme la FILE theme.py, khong phai thu muc), nen
# tung ten icon o do chua lan nao bi do. Tieng la "quet duoc" phai la hien
# thuc, khong phai mac dinh.
for root, found in sorted(per_root.items()):
    if not found:
        raise SystemExit("goc audit %r khong co file .py nao -> gate vo nghia"
                         % root)
    print("  goc %-10s : %d file .py" % (root, len(found)))
print("  file roi rac  : %s" % ", ".join(SINGLE_FILES))

for path in sorted(sources):
    rel = os.path.relpath(path, ROOT)
    text = open(path, encoding="utf-8").read()
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in PATTERN.finditer(line):
            icon_name = match.group(0).strip('"')
            used.setdefault(icon_name, []).append(
                "%s:%d" % (rel, lineno))

bad = []
blank = []
missing_from_dump = []
for icon_name in sorted(used):
    try:
        # Goi qua seam cua UI: neu bo ve cuc bo thieu ten thi no phai chore
        # o day, dung ra loi that cua app — khong phai loi cua oracle.
        pm = _qta().icon(icon_name, color="#FFFFFF").pixmap(16, 16)
    except Exception as exc:
        bad.append((icon_name, str(exc), used[icon_name]))
        continue
    image = pm.toImage()
    # Dem ALPHA, khong dem mau: o trong cua pixmap ARGB co the co gia tri mau
    # khac 0, va dem mau tung lam "ve duoc" mot hinh in ra o trang.
    solid = sum(1 for y in range(image.height()) for x in range(image.width())
                if (image.pixel(x, y) >> 24) & 0xFF)
    if solid / float(max(1, image.width() * image.height())) < 0.02:
        blank.append((icon_name, used[icon_name]))
    # Oracle: ten Font Awesome Free co that nhung asset dump cua ta khong co
    # nghia la scratch/make_icon_assets.py chay thieu, khong phai UI sai.
    if icon_name.startswith("fa6s.") and _oracle_names and \
            icon_name not in _oracle_names:
        missing_from_dump.append((icon_name, used[icon_name]))

print("tong so ten icon du dung: %d" % len(used))
for icon_name, err, sites in bad:
    print("  VO HIEU %s  (%s)" % (icon_name, err))
    for s in sites:
        print("      %s" % s)
for icon_name, sites in blank:
    print("  TRONG (khong ve pixel nao): %s" % icon_name)
    for s in sites:
        print("      %s" % s)

# ── Lop 2: khong goi _qta().icon() ma bo tham so mau ─────────────
# Mot QIcon khong nuong mau van co the in ra o trang. Moi lan goi phai nuong
# mau ro rang (widget common dung icon_color() mac dinh, nen goi cua no cung
# phai co color= hien ro).
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
for path in sorted(sources):          # cung danh sach nguon voi lop 1 o tren
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

print("\nso ten vo hieu: %d, so ten trong: %d, so goi khong mau: %d, "
      "so ten FA6s thieu trong asset dump: %d"
      % (len(bad), len(blank), len(nocolor), len(missing_from_dump)))
for icon_name, sites in missing_from_dump:
    print("  THIEU TRONG DUMP %s" % icon_name)
    for s in sites:
        print("      %s" % s)
sys.exit(1 if bad or blank or nocolor or missing_from_dump else 0)
