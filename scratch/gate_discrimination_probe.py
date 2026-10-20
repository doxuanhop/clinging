"""Phep phan chung cho 3 cua soi da sua 2026-10-20: moi cua phai do duoc RED
vi DUNG ly do, khong phai xanh vi dau vao rong.

    python scratch/gate_discrimination_probe.py

Cua duoc chay la CHINH script that (subprocess, dung dung lenh nguoi dung dung
ra), chi khac mot hang so dau vao. Phep thu co rang o phan 1: dat mot tep nguon
THAT chua mot ten glyph khong ton tai vung `ui/` va doi chinh audit bao do.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILS = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s%s" % (label, "PASS" if ok else "FAIL",
                          "" if ok else "  got=%r want=%r" % (got, want)))
    if not ok:
        FAILS.append(label)
    return ok


def run_py(path):
    """Chay mot lenh GIONG het lenh nguoi dung dung ra (khong them argv)."""
    run = subprocess.run([sys.executable, path], capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         timeout=900)
    return run.returncode, (run.stdout or "") + (run.stderr or "")


def run_py_with_args(path, extra):
    run = subprocess.run([sys.executable, path, ROOT] + list(extra),
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=900)
    return run.returncode, (run.stdout or "") + (run.stderr or "")


# ── 1. icon_name_audit: mot goc walk khong ton tai phai chore ────────────
# Loi cu: `theme` la FILE (theme.py), khong phai thu muc. os.walk tren mot goc
# khong ton tai sinh ra 0 file LANG LANG chu khong bao loi, nen doan audit tu
# xuong la quet sach trong khi co hai file nguon chua bao gio duoc do.
AUDIT = os.path.join(ROOT, "scratch", "icon_name_audit.py")
audit_src = open(AUDIT, encoding="utf-8").read()
DIRS = 'DIR_ROOTS = ("ui", "widgets", "core")'
FILES = 'SINGLE_FILES = ("theme.py", "main.py")'
check("danh sach goc quet khong con 'theme' gia", DIRS in audit_src, True)
check("khong con vong lap root hardcode o phan duoi",
      'for root in ("ui", "widgets", "core", "theme")' in audit_src, False)
check("danh sach file roi rac co that", FILES in audit_src, True)

rc, out = run_py(AUDIT)
check("audit nguyen ban xanh", rc, 0)
check("audit ke so file THAT cua tung goc",
      all(("goc %s" % g) in out for g in ("ui", "widgets", "core")), True)


def variant(old, new):
    """Chep audit voi MOT hang so thay doi, chay nhu lenh that, roi xoa tep."""
    path = os.path.join(ROOT, "scratch", "_audit_variant.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(audit_src.replace(old, new, 1))
    try:
        return run_py(path)
    finally:
        os.remove(path)


rc_v, out_v = variant(DIRS, DIRS[:-1] + ', "theme")')
check("them goc 'theme' khong ton tai -> RED", rc_v, 1)
check("RED vi dung ly do (goc khong co file .py nao)",
      "khong co file .py nao" in out_v, True)
check("thong diep chi ra dung goc nao vo nghia", "'theme'" in out_v, True)

missing = 'SINGLE_FILES = ("theme.py", "khong_co_file_nay.py")'
rc_v2, out_v2 = variant(FILES, missing)
check("khai bao mot file nguon khong ton tai -> RED", rc_v2, 1)
check("RED vi thieu nguon audit, khong phai loi khac",
      "thieu nguon audit" in out_v2, True)

# Phep thu co rang: mot tep nguon THAT trong ui/ chua mot ten glyph ma bo ve
# cuc bo khong co -> chinh audit nguyen ban phai bao do. Day la duong that cua
# app, khong phai do tran trong cua probe.
BAD = os.path.join(ROOT, "ui", "_gate_probe_bad_icon.py")
try:
    with open(BAD, "w", encoding="utf-8") as handle:
        handle.write('from widgets.common import _qta\n'
                     'ICON = _qta().icon("fa6s.khong-co-that-xyz", '
                     'color="#FFFFFF")\n')
    rc_b, out_b = run_py(AUDIT)
    check("ten glyph gia trong ui/ -> audit RED", rc_b, 1)
    check("audit goi ten ro fa6s.khong-co-that-xyz",
          "fa6s.khong-co-that-xyz" in out_b, True)
finally:
    os.remove(BAD)
rc_after, _o = run_py(AUDIT)
check("cat tep gia di roi audit lai xanh (khong de lai rac)", rc_after, 0)


# ── 2. msi_install_probe: so file phai so voi dist, khong phai nguong ────
import scratch.msi_install_probe as msi   # noqa: E402  lay hang so + ham that

n_dist = msi.count_files(msi.DIST)
installed_msi = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                             "Programs", "ClingingMSI")
n_msi = msi.count_files(installed_msi) if os.path.isdir(installed_msi) else -1
check("cay MSI da cai bang SO file cua dist (du lieu that)", n_msi, n_dist)

old_gate = lambda n: n >= 360                    # noqa: E731  cua CU
new_gate = lambda n, d: (n == d) and d >= 300    # noqa: E731  cua MOI
# Hai dong phan biet that su: cua cu xanh cho ca ban CO qtawesome (404 >= 360)
# va ca khi sot 1 component; cua moi do ca hai. Nguoc lai, "xanh rong" (0 == 0)
# phai bi nguong duoi chan — do la viec cua ve thu hai trong cua moi.
for n, d, why, want_old in [(404, n_dist, "ban CO qtawesome 404 file", True),
                            (n_dist - 1, n_dist, "MSI sot 1 component", True),
                            (0, 0, "ca hai cay trong, khong duoc xanh rong",
                             False)]:
    check("cua moi RED + cua cu %s cung case: %s"
          % ("XANH" if want_old else "RED", why),
          (old_gate(n), new_gate(n, d)), (want_old, False))

# Cat THAT 1 file cua mot cay that, khong dung con so tu bien.
tmp_src = os.path.join(ROOT, "scratch", "_gate_tree")
tmp_cut = tmp_src + "_cut"
shutil.rmtree(tmp_src, ignore_errors=True)
shutil.rmtree(tmp_cut, ignore_errors=True)
os.makedirs(os.path.join(tmp_src, "_internal"))
for leaf in ("a", "b", "c", "d", "e"):
    open(os.path.join(tmp_src, "_internal", leaf), "w").close()
shutil.copytree(tmp_src, tmp_cut)
os.remove(os.path.join(tmp_cut, "_internal", "c"))
a, b = msi.count_files(tmp_src), msi.count_files(tmp_cut)
# "n >= d - 2" la dang nguong ( nhu ">= 360" cua cu): no cho phep sot file.
loose = lambda n, d: n >= d - 2          # noqa: E731
check("cat 1 file thi cua moi do, cua dang nguong thi khong",
      (loose(b, a), new_gate(b, a)), (True, False))
shutil.rmtree(tmp_src, ignore_errors=True)
shutil.rmtree(tmp_cut, ignore_errors=True)
print("  %d file -> %d file (cat that '_internal/c' cua cay that)" % (a, b))


# ── 3. fontawesome.py: xoa dong import trung PHAI la thay doi vo nghia ───
from PySide6.QtWidgets import QApplication   # noqa: E402

app = QApplication.instance() or QApplication([])  # noqa: F841
import widgets.fontawesome as fa              # noqa: E402

FA_SRC = os.path.join(ROOT, "widgets", "fontawesome.py")
src = open(FA_SRC, encoding="utf-8").read()
check("dong import lap khong con trong file nguon",
      "from PySide6.QtGui import QPainter" in src, False)

pre = src.replace("    img.fill(0)\n    painter = QPainter(img)",
                  "    img.fill(0)\n    from PySide6.QtGui import QPainter\n"
                  "    painter = QPainter(img)")
check("chen lai duoc dong da xoa (co ban TRUOC de doi chieu)",
      pre != src, True)
old_mod = types.ModuleType("fontawesome_truoc_sua")
old_mod.__file__ = FA_SRC
exec(compile(pre, FA_SRC, "exec"), old_mod.__dict__)


def signature(module):
    """Hash tren BYTE RGBA that cua tung glyph, moi ten x 16/24/32 px."""
    h = hashlib.sha256()
    for name in sorted(module.names()):
        for px in (16, 24, 32):
            img = module._render("fa6s." + name, px, "#40E0D0")
            h.update(("%s@%d" % (name, px)).encode())
            h.update(bytes(img.constBits()[:img.sizeInBytes()]))
    return h.hexdigest()[:16]


now, then = signature(fa), signature(old_mod)
import json                                   # noqa: E402
charmap = os.path.join(ROOT, "assets", "icons",
                       "fontawesome6-solid-charmap.json")
payload = json.load(open(charmap, encoding="utf-8"))
check("bo ve phu toan bo ten trong charmap",
      len(fa.names()), len(payload["glyphs"]))
check("RGBA 102+ ten x 3 kich thuoc: truoc sua == sau sua", now, then)
print("  chu ky raster RGBA: %s (truoc sua) / %s (sau sua)" % (then, now))

# cai that su (tim thay boi phep thu ben tren): ten gia phai chore TRONG LAND
# cua Python luc dung icon, khong duoc cho den luc ve — vi ve xay ra trong
# callback C++ cua QIconEngine, noi exception cua Python khong the quay ve.
for bogus, why in [("fa6s.khong-co-that-xyz", "ten khong ton tai"),
                   ("fa6b.paintbrush", "prefix khong duoc ho tro")]:
    try:
        fa.icon(bogus, color="#FFFFFF")
        check("dung icon(%s) phai chore (%s)" % (bogus, why),
              "khong chore", "ValueError")
    except ValueError as exc:
        check("dung icon(%s) chore ValueError (%s)" % (bogus, why),
              bool(str(exc)), True)
good = fa.icon("fa6s.play", color="#FFFFFF")
check("ten that van dung icon() va ve duoc pixel",
      sum((good.pixmap(16, 16).toImage().pixel(x, y) >> 24) & 0xFF
          for y in range(16) for x in range(16)) > 0, True)
print("  so ten glyph trong charmap: %d" % len(payload["glyphs"]))


# ── 4. phep phan chung cua chinh phep sua: mot dong cat di = abort ───────
# "Kiem tra ten luc dung icon()" trong nom vo nghia neu khong chỉ ra duoc dieu
# gi xay ra khi KHONG co no. Doan nay cat dung mot dong `glyph_for(name)` roi
# chay trong subprocess: ban KHONG kiem tra chet bang ma process 0xC0000409
# vi loi bat len tu callback C++ cua QIconEngine; ban co kiem tra chore ValueError
# tai cho goi va tra ve ma 1 that.
CHILD = r'''
import os
import sys
import types

ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication

app = QApplication([])
import widgets.fontawesome as fa

src = open(fa.__file__, encoding="utf-8").read()
cut = src.replace("    glyph_for(name)\n", "", 1)
if "--co-cat" in sys.argv:
    assert cut != src, "khong tim thay dong glyph_for(name) de cat"
    src = cut
mod = types.ModuleType("fa_thuc_nghiem")
mod.__file__ = fa.__file__
exec(compile(src, fa.__file__, "exec"), mod.__dict__)
ic = mod.icon("fa6s.khong-co-that-xyz", color="#FFFFFF")
pm = ic.pixmap(16, 16)
sys.stdout.write("VE XONG khong chore: %s\n" % (pm.isNull(),))
'''
child_path = os.path.join(ROOT, "scratch", "_eager_validation_child.py")
try:
    with open(child_path, "w", encoding="utf-8") as handle:
        handle.write(CHILD)
    rc_ok, out_ok = run_py_with_args(child_path, [])
    check("ban CO dong kiem tra: chore ValueError, con song va co log",
          (rc_ok, "ValueError" in out_ok, "khong co glyph" in out_ok),
          (1, True, True))
    rc_cut, out_cut = run_py_with_args(child_path, ["--co-cat"])
    # rc KHONG duoc dung lam dieu kien phan biet o day: do 6 lan (3 co / 3 cat) cho thay ban
    # cat luc thi abort 0xC0000409, luc thi thoat rc=1 — Qt quyet nam bắt
    # exception qua bien C++ nam nao hay nam nao khong. Cai khong doi la DONG
    # LOG: "Error calling Python override of QIconEngine::pixmap()" chi xuat
    # hien khi loi bat len tu callback, tuc 3/3 ban cat va 0/3 ban co. Do ma
    # process van in ra, nhung gate tren no la gate mong manh.
    check("ban CAT: loi den tu callback cua QIconEngine, khong tu choi goi",
          "Error calling Python override of QIconEngine" in out_cut, True)
    check("ban CAT: process that bai o mot trong hai ma cua Qt-abort/rc-1",
          rc_cut in (1, 3221226505), True)
    check("ban CAT: khong bao gio ve xong hinh (khong co dong 'VE XONG')",
          "VE XONG" in out_cut, False)
    check("ban CO kiem tra: loi den TU CHINH choi goi icon(), khong qua Qt",
          "Error calling Python override of QIconEngine" in out_ok, False)
    check("ban CO kiem tra: traceback khong len den frame pixmap()",
          "pixmap(16, 16)" in out_ok, False)
    print("  rc co kiem tra=%r | rc khong kiem tra=%r (abort 0xc0000409 = %s)"
          % (rc_ok, rc_cut, rc_cut == 3221226505))
finally:
    os.remove(child_path)

print("\n%s  (%d fail)" % ("ALL PASS" if not FAILS else "CO FAIL", len(FAILS)))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
