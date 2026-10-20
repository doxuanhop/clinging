"""Doc metadata cua mot ban MSI/Inno da dung, khong tin vao ten file.

    python scratch/release_meta.py <file.msi|file.exe> [...]

Vi sao: ten file la mot chu thuat cua nguoi dung ("ClingingSetup-1.0.1.msi"),
con ProductVersion / FileVersion la dieu Windows Installer va Explorer dung de
quyet dinh nang cap, hien thi o Properties -> Details, va ghi vao ARP. Mot lan
bump ma quen mot trong ba cho thi file van tai duoc, van cai duoc, nen khong the
bi bat bang cache so sanh byte.

MSI doc bang msilib (goi thang msi.dll), khong qua WindowsInstaller.Installer:
 o may nay COM tra ve Record khong co thanh vien nao, `StringData` bao
 "Member not found", nen detector do khong chay duoc duoi dung cua its API.

exe doc bang scratch/exe_version.py (version.dll), va ke ra ma nguyen ban cua
no de Inno 6.x tu sinh do (xem do sach trong clinging.iss).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exe_version


def msi_props(path):
    import msilib
    db = msilib.OpenDatabase(os.path.abspath(path), msilib.MSIDBOPEN_READONLY)
    out = {}
    for col in ("ProductName", "ProductVersion", "ProductCode", "PackageCode",
                "ALLUSERS"):
        view = db.OpenView("SELECT `Value` FROM Property WHERE `Property` = '%s'"
                           % col)
        view.Execute(None)
        rec = view.Fetch()
        out[col] = rec.GetString(1) if rec else None
    return out


def wxs_upgrade_code():
    """UpgradeCode nam trong packaging/clinging.wxs, do build sinh ra ProductCode
    bang uuid5. Doc lai tu source hon la hardcode: doi no la hai lan cai khong
    bao gio nang cap duoc nhau, nen no phai la mot hang so co the kiem tra."""
    import re
    wxs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "packaging", "clinging.wxs")
    text = open(wxs, encoding="utf-8").read()
    match = re.search(r'UpgradeCode="\{([0-9A-Fa-f-]{36})\}"', text)
    if not match:
        raise SystemExit("Khong thay UpgradeCode trong " + wxs)
    return "{" + match.group(1).upper() + "}"


def check_msi(path, expect):
    print(path)
    props = msi_props(path)
    problems = []
    want = wxs_upgrade_code()
    for k in ("ProductName", "ProductVersion", "ProductCode"):
        print("   %-15s %s" % (k, props.get(k)))
    print("   %-15s %s (nguyen ban trong .wxs)" % ("upgrade code", want))
    if props.get("ALLUSERS") is not None:
        problems.append("ALLUSERS duoc publish = %r -> MSI yeu cau UAC va cai "
                        "vao Program Files" % props["ALLUSERS"])
    ver = props.get("ProductVersion") or ""
    if len(ver.split(".")) != 3:
        problems.append("ProductVersion %r khong co dang a.b.c (Windows Installer "
                        "chi cho phep 3 thanh phan so)" % ver)
    if expect and ver != expect:
        problems.append("ky vong %s, nhan duoc %s" % (expect, ver or "khong co"))
    for p in problems:
        print("   LECH: %s" % p)
    return 1 if problems else 0


def main(argv):
    expect = None
    if argv[:1] == ["--expect"]:
        if len(argv) < 3:
            raise SystemExit(__doc__)
        expect, argv = argv[1], argv[2:]
    if not argv:
        raise SystemExit(__doc__)
    rc = 0
    for path in argv:
        if path.lower().endswith(".msi"):
            rc = max(rc, check_msi(path, expect))
        else:
            rc = max(rc, exe_version.check(path, expect))
    if rc == 0:
        print("GATE: metadata khop" + (" = %s" % expect if expect else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
