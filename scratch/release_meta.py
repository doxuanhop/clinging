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


def source_versions():
    """Doc ba nguon phai TRUNG NHAU truoc khi dung bat cu thu gi.

    Vi sao lai can: tu 1.0.1 den 1.0.3 `core/settings.py:APP_VERSION` van ghi
    "1.0.0" trong khi hai file dong goi da chay 1.0.3 — hop "Về" cua ban ship
    noi sai ban dang chay. Gate cu (`settings.APP_VERSION in about`) XANH SUOT
    vi no so chuoi cua chinh no, nen lech khong the ty lo. Doi thanh so ba
    nguon doc lap trong nguon.
    """
    import re
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def read(*parts):
        with open(os.path.join(repo, *parts), encoding="utf-8") as handle:
            return handle.read()

    iss = read("packaging", "clinging.iss")
    vi = read("packaging", "version_info.txt")
    st = read("core", "settings.py")

    def grab(text, pattern, label):
        match = re.search(pattern, text)
        if not match:
            raise SystemExit("khong doc duoc %s" % label)
        return match.group(1)

    out = {}
    out["clinging.iss MyAppVersion"] = grab(
        iss, r'#define\s+MyAppVersion\s+"([^"]+)"', "MyAppVersion trong .iss")
    out["version_info.txt FileVersion"] = grab(
        vi, r"StringStruct\('FileVersion', '([^']+)'\)", "FileVersion")
    out["version_info.txt ProductVersion"] = grab(
        vi, r"StringStruct\('ProductVersion', '([^']+)'\)", "ProductVersion")
    ff = re.search(r"filevers=\((\d+), (\d+), (\d+), (\d+)\)", vi)
    pv = re.search(r"prodvers=\((\d+), (\d+), (\d+), (\d+)\)", vi)
    if not ff or not pv:
        raise SystemExit("khong doc duoc filevers/prodvers")
    out["version_info.txt filevers"] = ".".join(ff.groups()[:3])
    out["version_info.txt prodvers"] = ".".join(pv.groups()[:3])
    out["core/settings.py APP_VERSION"] = grab(
        st, r'(?m)^APP_VERSION\s*=\s*"([^"]+)"', "APP_VERSION")
    return out


def check_sources():
    values = source_versions()
    print("Nguon so phai khop (doc truc tiep trong tree):")
    for name, value in sorted(values.items()):
        print("   %-32s %s" % (name, value))
    distinct = set(values.values())
    if len(distinct) != 1:
        print("   LECH: %d so khac nhau %r" % (len(distinct), sorted(distinct)))
        return 1, ""
    version = next(iter(values.values()))
    print("   KHOP: tat ca = %s" % version)
    return 0, version


def main(argv):
    expect = None
    if argv[:1] == ["--expect"]:
        if len(argv) < 3:
            raise SystemExit(__doc__)
        expect, argv = argv[1], argv[2:]
    if not argv:
        raise SystemExit(__doc__)
    rc = 0
    src_rc, src_version = check_sources()
    rc = max(rc, src_rc)
    if expect is None:
        # Mac dinh lay so tu .iss: ten asset, ProductVersion MSI va FileVersion
        # exe PHAI theo no. truoc day `--expect` la chu thuat do nguoi dung go
        # tay, nen quen not la khong bat duoc lech.
        expect = src_version
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
