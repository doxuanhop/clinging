"""Chung minh hai thu muc cai dat = dung bundle vua build, khong pha tron.

    python scratch\\installed_dirs_match.py

Dem theo duong doi tuong-voi-tree-goc, khong theo timestamp: [InstallDelete]
cua .iss xoa {app}\\_internal tru khi giai, nen sau lan nang cap thu muc phai
trai ra KHONG con mot file nao ma bundle hom nay khong co. File le (nhun cua
lan cai cu, hay video do mot probe nao do xuat ra) phai lo ra o day.
"""

import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(REPO, "dist", "Clinging")
BASE = os.path.join(os.environ["LOCALAPPDATA"], "Programs")
COPIES = {"Inno (Clinging)": os.path.join(BASE, "Clinging"),
          "MSI (ClingingMSI)": os.path.join(BASE, "ClingingMSI")}


def rel_set(root):
    out = set()
    for base, _sub, names in os.walk(root):
        for name in names:
            out.add(os.path.relpath(os.path.join(base, name), root))
    return out


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def main():
    bundle = rel_set(BUNDLE)
    print("bundle          %d file" % len(bundle))
    bundle_exe = sha(os.path.join(BUNDLE, "Clinging.exe"))
    ok = True
    for label, root in COPIES.items():
        if not os.path.isdir(root):
            print("%-20s THU MUC KHONG TON TAI" % label)
            ok = False
            continue
        got = rel_set(root)
        extra = sorted(got - bundle)
        missing = sorted(bundle - got)
        exe_same = sha(os.path.join(root, "Clinging.exe")) == bundle_exe
        # _internal la phan build thay doi theo tung lan; so song voi bundle
        # bang ten duong dan, khong so bang mtime.
        print("%-20s %4d file  exe khop bundle: %s" % (label, len(got), exe_same))
        print("    lac ra ngoài bundle : %s" % (extra if extra else "khong co"))
        print("    bundle thieu trong cay cai: %s"
              % (missing if missing else "khong co"))
        if missing or not exe_same:
            ok = False
    print("\n%s" % ("KHOI NOI DUNG KHOP BUNDLE" if ok
                    else "LECH - xem dong in o tren"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
