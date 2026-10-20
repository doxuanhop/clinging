"""Doi chieu cay `dist` voi payload ben trong MSI, khong can cai dat.

    python scratch/msi_payload_check.py [<duong dan .msi>]

File table cua MSI phai chua DUNG mot tap hop file nhu dist; mot component bi
sot khi `heat` chay se cho ra MSI cai duoc, chay duoc, thieu duoc mot thu.
Version lay tu `packaging/clinging.iss` — cung mot nguon ma `make_msi.py` dung,
nen gate khong the tro thanh gia khi sau khi bump version ma quen chay lai.
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import msilib  # noqa: E402  DeprecationWarning chap nhan duoc o day

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iss_version():
    iss = os.path.join(REPO, "packaging", "clinging.iss")
    text = open(iss, encoding="utf-8").read()
    match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
    if not match:
        raise SystemExit("Khong thay MyAppVersion trong " + iss)
    return match.group(1)


VERSION = iss_version()
MSI = (sys.argv[1] if len(sys.argv) > 1 else
       os.path.join(REPO, "build", "installer",
                    "ClingingSetup-%s.msi" % VERSION))
print("MSI: %s" % MSI)

db = msilib.OpenDatabase(os.path.abspath(MSI), msilib.MSIDBOPEN_READONLY)


def rows(sql, ncols):
    view = db.OpenView(sql)
    view.Execute(None)
    out = []
    rec = view.Fetch()
    while rec is not None:
        out.append(tuple(rec.GetString(i) for i in range(1, ncols + 1)))
        rec = view.Fetch()
    return out


names = [r[1].split("|")[-1] for r in
         rows("SELECT `File`, `FileName`, `FileSize` FROM File", 3)]
total = sum(int(r[2] or 0) for r in
            rows("SELECT `File`, `Component_`, `FileSize` FROM File", 3))


def walk_dist(root):
    base = os.path.join(root, "Clinging")
    found = []
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            found.append(os.path.relpath(os.path.join(dirpath, f), base))
    return found


dist = walk_dist(os.path.join(REPO, "dist"))
fails = []


def check(label, got, want):
    ok = got == want
    print("%-52s %s%s" % (label, "PASS" if ok else "FAIL",
                          "" if ok else "  got=%r want=%r" % (got, want)))
    if not ok:
        fails.append(label)


check("MSI File rows == so file trong dist", len(names), len(dist))
ids = [r[0] for r in rows("SELECT `File`, `FileName` FROM File", 2)]
check(" khoa chinh `File` khong trung lap", len(ids), len(set(ids)))
print("  leaf name lap lai o nhieu thu muc (hop le, dist cung vay): %d"
      % (len(names) - len(set(names))))
from collections import Counter  # noqa: E402

msi_leafs = Counter(os.path.basename(n) for n in names)
dist_leafs = Counter(os.path.basename(p) for p in dist)
only_dist = sorted((dist_leafs - msi_leafs).elements())
only_msi = sorted((msi_leafs - dist_leafs).elements())
check("bo leaf name MSI == bo leaf name dist",
      (only_msi, only_dist), ([], []))
if only_msi or only_dist:
    # In TRENCH LECH chu khong in ca hai danh sach 362 phan tu: mot doan
    # 15 KB chen vao log gate se choi mat dong FAIL ma nguoi doc can thuong.
    print("    chi co trong MSI: %s" % (only_msi[:12],))
    print("    chi co trong dist: %s" % (only_dist[:12],))
for probe in ("Clinging.exe", "ffmpeg.exe", "ffprobe.exe",
              "fontawesome6-solid-6.7.2.ttf", "fontawesome6-solid-charmap.json"):
    check("payload co %s" % probe, probe in msi_leafs, True)
check("payload KHONG con qtawesome",
      any("qtawesome" in n.lower() for n in names), False)
print("  payload bytes tong = %d (%.1f MB), dist files = %d"
      % (total, total / 2**20, len(dist)))
print("\n%s  (%d fail)" % ("ALL PASS" if not fails else "CO FAIL", len(fails)))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
