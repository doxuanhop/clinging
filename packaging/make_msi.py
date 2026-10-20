"""Dong goi Clinging thanh MOT file .msi (WiX v3.11, per-user, khong UAC).

    python packaging\\make_msi.py

Ba buoc, khong buoc nao go tay danh sach file:
  1. `heat dir dist\\Clinging` sinh build\\msi\\files.wxs tu bundle that.
  2. `candle` bien clinging.wxs + files.wxs thanh .wixobj.
  3. `light` ghep cab vao trong MSI -> build\\installer\\ClingingSetup-<ver>.msi.

Ten file va thu muc dich lay theo `clinging.iss` (MyAppVersion) de hai installer
khong bao gio lech nhau. WiX tim trong %LOCALAPPDATA%\\Programs\\wix311; neu
khong co, script in ra dung URL ban `wix311-binaries.zip` (WiX v7 do WiX Toolset
bat ky OSMF EULA, nen dung han v3.11 - ban cuoi mien phi hoan toan).

Version MSI doc tu .iss, con UpgradeCode trong .wxs PHAI giu nguyen: doi no la
mo mot dong nang cap khong bao gio go duoc ban cu.
"""

import hashlib
import datetime
import os
import re
import subprocess
import sys
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(REPO, "packaging", "clinging.iss")
WXS = os.path.join(REPO, "packaging", "clinging.wxs")
BUNDLE = os.path.join(REPO, "dist", "Clinging")
MSI_DIR = os.path.join(REPO, "build", "msi")
OBJ_DIR = os.path.join(MSI_DIR, "obj")
OUT_DIR = os.path.join(REPO, "build", "installer")
WIX_HOME = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Programs", "wix311")
WIX_URL = ("https://github.com/wixtoolset/wix3/releases/download/"
           "wix3112rtm/wix311-binaries.zip")


def app_version():
    text = open(ISS, encoding="utf-8").read()
    match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
    if not match:
        raise SystemExit("Khong doc duoc MyAppVersion trong " + ISS)
    return match.group(1)


# Namespace co dinh: cung mot bundle thi lan build nao cung ra dung bo GUID.
# GUID ngau nhien moi lan build khong gay loi cho MajorUpgrade, no khiem khuyet
# o cho khong the so sanh byte-voi-byte hai lan dung.
GUID_NS = uuid.UUID("{B1A6A2E4-5F1D-4C33-9E1A-7A63F0D1B2C4}")


def stamp_guids(path):
    """heat 3.11 khong co switch sinh GUID tat dinh (`-gl` bi bo qua im lang,
    con `-gg` thi ngau nhien), nen thay `PUT-GUID-HERE` bang uuid5(component Id).
    """
    text = open(path, encoding="utf-8").read()

    def replace(match):
        head, comp_id, tail = match.group(1), match.group(2), match.group(3)
        guid = uuid.uuid5(GUID_NS, comp_id)
        return '%s%s%s Guid="{%s}"' % (head, comp_id, tail,
                                       str(guid).upper())

    stamped, n = re.subn(r'(<Component Id=")([^"]+)("[^>]*?)Guid="PUT-GUID-HERE"',
                         replace, text)
    if n == 0:
        raise SystemExit("heat khong sinh component nao de gan GUID - "
                         "danh sach file roi, dung build MSI.")
    if "PUT-GUID-HERE" in stamped:
        raise SystemExit("Con component chua co GUID sau khi stamp.")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(stamped)
    return n


def wix_tool(name):
    path = os.path.join(WIX_HOME, name)
    if not os.path.isfile(path):
        raise SystemExit(
            "Thieu WiX 3.11 (%s) trong %s\n"
            "Tai %s ve, giai ra %s roi chay lai." % (name, WIX_HOME,
                                                     WIX_URL, WIX_HOME))
    return path


def run(argv, cwd):
    print("  $ " + " ".join(argv), flush=True)
    proc = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    out = proc.stdout.decode("mbcs", errors="replace")
    sys.stdout.write(out)
    if proc.returncode != 0:
        raise SystemExit("%s loi rc=%d" % (os.path.basename(argv[0]),
                                           proc.returncode))
    return out


def main():
    if not os.path.isdir(BUNDLE):
        raise SystemExit("Chua co bundle " + BUNDLE +
                         "\nBuild PyInstaller truoc (ClingingQt.spec).")
    version = app_version()
    exe = os.path.join(BUNDLE, "Clinging.exe")
    print("bundle   : %s" % BUNDLE)
    print("  Clinging.exe mtime %s" %
          datetime.datetime.fromtimestamp(
              os.path.getmtime(exe)).strftime("%Y-%m-%d %H:%M:%S"))
    print("version  : %s (tu clinging.iss)" % version)

    for d in (MSI_DIR, OBJ_DIR, OUT_DIR):
        os.makedirs(d, exist_ok=True)
    stale = os.path.join(MSI_DIR, "files.wxs")
    if os.path.isfile(stale):
        os.remove(stale)

    heat = wix_tool("heat.exe")
    candle = wix_tool("candle.exe")
    light = wix_tool("light.exe")

    print("\n== 1. heat: lay danh sach file that cua bundle ==")
    run([heat, "dir", BUNDLE,
         "-cg", "ClingingFiles", "-dr", "INSTALLFOLDER",
         "-srd", "-sreg", "-var", "var.SourceDir",
         "-out", stale], cwd=REPO)
    guids = stamp_guids(stale)
    rows = open(stale, encoding="utf-8").read()
    files = len(re.findall(r"<File ", rows))
    components = len(re.findall(r"<Component ", rows))
    print("  %d component duoc gan GUID tat dinh" % guids)
    print("  %d file / %d component" % (files, components))
    if files < 100:
        raise SystemExit("heat sinh qua it file - bundle doi thay hoac sai tham "
                         "s? Dung build MSI.")

    print("\n== 2. candle ==")
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(BUNDLE) for f in fs)
    print("  payload %.1f MB -> EstimatedSize %d KB trong Add/Remove Programs"
          % (total / 2**20, total // 1024))
    run([candle, "-arch", "x64",
         "-dSourceDir=" + BUNDLE,
         "-dAppVersion=" + version,
         "-dEstimatedSizeKb=" + str(total // 1024),
         "-dIconPath=" + os.path.join(REPO, "assets", "app-icon", "icon.ico"),
         "-dLicenseRtf=" + os.path.join(REPO, "packaging", "license.rtf"),
         "-out", OBJ_DIR + os.sep,
         WXS, stale], cwd=REPO)

    print("\n== 3. light: nen + nhung cab vao trong MSI ==")
    out_msi = os.path.join(OUT_DIR, "ClingingSetup-%s.msi" % version)
    if os.path.isfile(out_msi):
        os.remove(out_msi)
    # Ba ICE phai tat CO LY DO, tat ca deu do package per-user payload-file:
    #   ICE38: moi component trong profile phai lay KeyPath la khoa HKCU. Chua
    #          theo sach is nao thi 404 file -> 404 khoa rac trong registry cua
    #          nguoi dung. Ban nay chi cai cho mot user nen khong co nguy co
    #          "user khac dung do".
    #   ICE64: moi thu muc trong profile phai co RemoveFile. RemoveFile cua MSI
    #          voi FileName TRONG se XOA DE QUY thu muc do, ma ICE64 goi ca
    #          %LOCALAPPDATA%\Programs - noi VS Code va app khac cung nam.
    #          Khong danh doi an toan cua nguoi khac lay mot thong bao.
    #          phep thu "thu muc test bi xoa het" trong msi_install_probe do
    #          lai viec MSI tu don (no xoa thu muc no tao ra khi chung rong).
    #   ICE91: thu muc dich khong doi theo ALLUSERS - dung y tinh cua ban nay:
    #          Package khong khai bao `both` nen khong the cai per-machine.
    run([light, "-ext", "WixUIExtension", "-cultures:en-us",
         "-sice:ICE38", "-sice:ICE64", "-sice:ICE91",
         "-pdbout", os.path.join(OBJ_DIR, "clinging.wixpdb"),
         "-out", out_msi,
         os.path.join(OBJ_DIR, "clinging.wixobj"),
         os.path.join(OBJ_DIR, "files.wixobj")], cwd=REPO)

    if not os.path.isfile(out_msi):
        raise SystemExit("light bao thanh cong nhung khong co file MSI.")
    blob = open(out_msi, "rb").read()
    print("\nmsi      : %s" % out_msi)
    print("  %.1f MB  sha256 %s" % (len(blob) / 2**20,
                                    hashlib.sha256(blob).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
