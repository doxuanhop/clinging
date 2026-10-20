"""Cai / kiem chung / go ban MSI that, bang dung duong ma nguoi dung dung.

    python scratch\\msi_install_probe.py

Vi sao phai cai that: mot file .msi build xong chua phai bang chung. Ba thu
phai do duoc tren may nay, khong phai tren mot may co quyen admin:

  * per-user that su - `IsUserAnAdmin()` phai tra 0 TRUOC khi go msiexec,
    vi Package khai bao InstallScope=perUser / InstallPrivileges=limited.
  * moi vet roi nam trong profile: thu muc dich, shortcut Desktop + Start Menu,
    HKCU\\Software\\Classes (khong phai HKCR).
  * MSI la MOT file duy nhat: khong co .cab nam canh, cab nam trong stream.

Probe cai vao `build\\msitest` de KHONG cham vao ban Inno dang chay o
%LOCALAPPDATA%\\Programs\\Clinging. Ba thu cua may bi MSI ghi de/xa khi do:
hai khoa .clinq va hai shortcut .lnk. Ca nam thu deu duoc snapshot truoc va
phuc hoi sau; do chinh la ly do probe chay duoc tren may cua nguoi dung ma
khong de lai rac.
"""

import ctypes
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import winreg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Doc version tu clinging.iss thay vi ghi chu so: installed_app_probe.py tung
# cai lai dung "ClingingSetup-1.0.0.exe" duoc hardcode va lam moi lan verify
# kiem tra ban cu, xanh van in ra ALL PASS.
_iss = open(os.path.join(REPO, "packaging", "clinging.iss"),
            encoding="utf-8").read()
_match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', _iss)
if not _match:
    raise SystemExit("Khong doc duoc MyAppVersion trong clinging.iss")
VERSION = _match.group(1)
MSI = os.path.join(REPO, "build", "installer", "ClingingSetup-%s.msi" % VERSION)
TARGET = os.path.join(REPO, "build", "msitest")
DIST = os.path.join(REPO, "dist", "Clinging")
WORK = os.path.join(REPO, "scratch")
SNAPSHOT = os.path.join(WORK, "msi_machine_state.json")
LOG = os.path.join(WORK, "msiexec.log")
DESKTOP_LNK = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop",
                           "Clinging.lnk")
MENU_LNK = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                        "Start Menu", "Programs", "Clinging", "Clinging.lnk")
CLINQ_KEYS = (
    r"Software\Classes\.clinq",
    r"Software\Classes\Clinging.Project",
    r"Software\Classes\Clinging.Project\DefaultIcon",
    r"Software\Classes\Clinging.Project\shell\open\command",
)
ARP_BASE = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

FAILS = []


def check(label, ok, detail=""):
    print("%-58s %s %s" % (label, "PASS" if ok else "FAIL",
                           "" if ok else repr(detail)))
    if not ok:
        FAILS.append(label)
    return ok


def note(label, value):
    print("  %-56s %r" % (label, value))


def reg_read(key, name=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as h:
            return winreg.QueryValueEx(h, name)[0]
    except OSError:
        return None


def reg_write(key, value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as h:
        winreg.SetValueEx(h, "", 0, winreg.REG_SZ, value)


def msiexec(args):
    """Co timeout: neu package vo tinh doi UAC thi `msiexec /qn` nam chay,
    khong in loi. Timeout bien no thanh mot ket luan doc duoc."""
    try:
        proc = subprocess.run(["msiexec.exe"] + args, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=1800)
    except subprocess.TimeoutExpired:
        return 999, "msiexec khong tra loi trong 30 phut (nghi doi UAC?)"
    return proc.returncode, proc.stdout.decode("mbcs", errors="replace")


def _shell():
    import win32com.client
    return win32com.client.Dispatch("WScript.Shell")


def lnk_target(path):
    if not os.path.isfile(path):
        return None
    return _shell().CreateShortcut(path).TargetPath


def snapshot_lnk(path):
    if not os.path.isfile(path):
        return None
    link = _shell().CreateShortcut(path)
    return {"path": path, "target": link.TargetPath,
            "workdir": link.WorkingDirectory, "icon": link.IconLocation,
            "args": link.Arguments}


def restore_lnk(snap):
    """MSI xoa .lnk ma no ghi de, nen phai dung lai dung cho cua ban Inno."""
    if not snap:
        return
    link = _shell().CreateShortcut(snap["path"])
    link.TargetPath = snap["target"]
    link.WorkingDirectory = snap["workdir"]
    link.IconLocation = snap["icon"]
    link.Arguments = snap["args"]
    link.Save()


def check_lnk_back(snap, label):
    """Shortcut phai tro lai dung cho cu, hoac dung la von khong ton tai."""
    if not snap:
        print("%-58s SKIP %s" % (label + " (von khong co)", "-"))
        return True
    return check(label, (lnk_target(snap["path"]) or "").lower() ==
                 snap["target"].lower(), lnk_target(snap["path"]))


def msi_arp_entries():
    """Moi entry ARP lien quan toi Clinging, kem duong dan cai cua no.

    Loc theo InstallLocation chu khong theo ten khoa: ban Inno cung ghi mot
    khoa `{8F0C4A6E-...}_is1` ten "Clinging", nen do theo ten thi phep thu
    "ARP het sau khi go" luong FAIL, va nguoc lai no luong PASS nho ban khac.
    InstallLocation do chinh MSI viet ra, khong the trung voi ban khac.
    """
    rows = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP_BASE) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, i)
                sub = ARP_BASE + "\\" + name
                display = reg_read(sub, "DisplayName") or ""
                if "cling" not in display.lower():
                    continue
                rows[name] = {"display": display,
                              "version": reg_read(sub, "DisplayVersion"),
                              "location": reg_read(sub, "InstallLocation")}
    except OSError:
        pass
    return rows


def msi_arp_for(target):
    return {k: v for k, v in msi_arp_entries().items()
            if (v["location"] or "").lower().rstrip("\\") == target.lower()}


def count_files(root):
    return sum(len(names) for _d, _s, names in os.walk(root))


def snapshot_state():
    state = {"clinq": {k: reg_read(k) for k in CLINQ_KEYS},
             "lnk": [snapshot_lnk(DESKTOP_LNK), snapshot_lnk(MENU_LNK)]}
    json.dump(state, open(SNAPSHOT, "w", encoding="utf-8"), indent=1)
    return state


def restore_state(state):
    for key, value in state["clinq"].items():
        if value is None:
            continue
        try:
            reg_write(key, value)
        except OSError as exc:
            print("  khong phuc hoi duoc %s: %s" % (key, exc))
    for snap in state["lnk"]:
        restore_lnk(snap)


def main():
    print("== 0. dieu kien tien quyet ==")
    check("probe chay KHONG can admin (per-user MSI moi dung)",
          not bool(ctypes.windll.shell32.IsUserAnAdmin()),
          "IsUserAnAdmin()=%d" % ctypes.windll.shell32.IsUserAnAdmin())
    if not check("MSI ton tai", os.path.isfile(MSI), MSI):
        return 2
    size = os.path.getsize(MSI)
    check("MSI la mot file duy nhat > 100 MB", size > 100 * 2**20, size)
    note("kich thuoc MSI MB", round(size / 2**20, 1))
    cabs = [p for p in glob.glob(os.path.join(REPO, "build", "installer", "*"))
            if p.lower().endswith(".cab")]
    check("khong co .cab nam canh MSI (cab nam trong stream)", not cabs, cabs)

    state = snapshot_state()
    note("clinq TRUOC khi test", state["clinq"][r"Software\Classes\.clinq"])
    note("lnk Desktop TRUOC khi test",
         state["lnk"][0] and state["lnk"][0]["target"])

    # Neu `INSTALLFOLDER=` khong winp, MSI se giai nen vao thu muc ban Inno dang
    # chay. Do bang chung phan biet truoc/sau de khong bao "PASS" nho ran.
    real_dir = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Clinging")
    real_exe = os.path.join(real_dir, "Clinging.exe")
    before = (count_files(real_dir),
              os.path.getmtime(real_exe) if os.path.isfile(real_exe) else None)
    note("ban Inno TRUOC khi test (file, mtime exe)",
         (before[0], before[1] and datetime.datetime.fromtimestamp(
             before[1]).strftime("%H:%M:%S")))

    if os.path.isdir(TARGET):
        print("  don thu muc test cu: %s" % TARGET)
        shutil.rmtree(TARGET, ignore_errors=True)

    print("\n== 1. msiexec /i INSTALLFOLDER=%s /qn ==" % TARGET)
    rc, out = msiexec(["/i", MSI, "INSTALLFOLDER=%s" % TARGET, "/qn",
                       "/l*v", LOG])
    if not check("cai silent tra ve 0", rc == 0, "rc=%d %s" % (rc, out[-500:])):
        restore_state(state)
        return 1

    after = (count_files(real_dir),
             os.path.getmtime(real_exe) if os.path.isfile(real_exe) else None)
    check("INSTALLFOLDER= winp: thu muc ban Inno khong bi cham",
          after == before, "%r != %r" % (after, before))

    exe = os.path.join(TARGET, "Clinging.exe")
    check("Clinging.exe nam trong thu muc test", os.path.isfile(exe), exe)
    n = count_files(TARGET) if os.path.isdir(TARGET) else 0
    # Moc so sanh lay tu chinh `dist\Clinging` ma `heat dir()` dong goi, KHONG
    # ghi chu so trong probe. Rang buoc cu "n >= 360" (sau khi qtawesome bi cat,
    # bundle 404 -> 362 file) la mot gate vo nghia: ban CO qtawesome 404 file
    # cung xanh, nen no khong the phat hien rac quay lai. Bang so do = doan
    # "MSI giai het tung component"; cai "khong con qtawesome" la cua gate
    # nguoc ben duoi, khong phai cua con so nay.
    dist_n = count_files(DIST) if os.path.isdir(DIST) else 0
    check("cay MSI giai DUNG SO file cua bundle trong dist",
          n == dist_n, "msi=%d dist=%d" % (n, dist_n))
    # Gate so sanh co the xanh rong: dist mat thi 0 == 0. Nhay du 300 ngan
    # cach do, gia tri that van in ra khi FAIL.
    check("dist dung lam moc so sanh co payload that",
          dist_n >= 300, "%d file" % dist_n)
    check("ban MSI cung KHONG co qtawesome",
          not os.path.isdir(os.path.join(TARGET, "_internal", "qtawesome")),
          os.path.join(TARGET, "_internal", "qtawesome"))
    check("ban MSI co font + charmap FA6 local",
          os.path.isfile(os.path.join(
              TARGET, "_internal", "assets", "icons",
              "fontawesome6-solid-6.7.2.ttf")), True)
    check("ffmpeg + ffprobe di kem", all(os.path.isfile(p) for p in (
        os.path.join(TARGET, "_internal", "tools", "ffmpeg.exe"),
        os.path.join(TARGET, "_internal", "tools", "ffprobe.exe"))),
        sorted(os.listdir(os.path.join(TARGET, "_internal", "tools")))
        if os.path.isdir(os.path.join(TARGET, "_internal", "tools")) else "")
    check("khong co unins000.exe cua Inno trong thu muc test",
          not os.path.isfile(os.path.join(TARGET, "unins000.exe")))

    print("\n== 2. vet trong profile (khong phai toan cuc) ==")
    check(r"HKCU\Software\Classes\.clinq -> Clinging.Project",
          reg_read(r"Software\Classes\.clinq") == "Clinging.Project",
          reg_read(r"Software\Classes\.clinq"))
    cmd = reg_read(r"Software\Classes\Clinging.Project\shell\open\command") or ""
    check('lenh mo tro toi exe test, co "%1" trong ngoac kep',
          TARGET.lower() in cmd.lower() and '"%1"' in cmd, cmd)
    check("ProgId co ten hien thi",
          reg_read(r"Software\Classes\Clinging.Project") == "Clinging Project",
          reg_read(r"Software\Classes\Clinging.Project"))
    check("shortcut Desktop tro toi exe test",
          (lnk_target(DESKTOP_LNK) or "").lower() == exe.lower(),
          lnk_target(DESKTOP_LNK))
    check("shortcut Start Menu tro toi exe test",
          (lnk_target(MENU_LNK) or "").lower() == exe.lower(),
          lnk_target(MENU_LNK))
    check("khong con .lnk nao tro toi thu muc Inno cua ban cu",
          all((lnk_target(p) or "").lower() !=
              os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Clinging",
                           "Clinging.exe").lower()
              for p in (DESKTOP_LNK, MENU_LNK)))
    arp_all = msi_arp_entries()
    arp = msi_arp_for(TARGET)
    note("moi key ARP lien quan Cling", arp_all)
    check("co dung MOT entry Add/Remove Programs tro vao thu muc test",
          len(arp) == 1, arp)
    if len(arp) == 1:
        key = next(iter(arp))
        note("ARP key", key)
        note("ARP DisplayName / version",
             (arp[key]["display"], arp[key]["version"]))
        check("ARP DisplayVersion la " + VERSION, arp[key]["version"] == VERSION,
              arp[key]["version"])
        est = reg_read(ARP_BASE + "\\" + key, "EstimatedSize")
        check("ARP EstimatedSize khop payload (>400 MB)",
              isinstance(est, int) and est > 400 * 1024, est)
        check("ARP co duong go im lang",
              bool(reg_read(ARP_BASE + "\\" + key, "QuietUninstallString")),
              reg_read(ARP_BASE + "\\" + key, "QuietUninstallString"))

    print("\n== 3. ung dung chay tu thu muc MSI ==")
    selftest = os.path.join(WORK, "msi_selftest.json")
    proc = subprocess.run([exe, "--selftest", selftest],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          cwd=TARGET)
    text = proc.stdout.decode("utf-8", errors="replace")
    check("--selftest rc 0 tu ban MSI", proc.returncode == 0,
          "rc=%d %s" % (proc.returncode, text[-300:]))
    rows = json.load(open(selftest, encoding="utf-8"))["checks"]
    bad = [c["name"] for c in rows if not c["ok"]]
    check("selftest: moi %d dong deu ok" % len(rows), not bad, bad)
    note("selftest tu", json.load(open(selftest, encoding="utf-8"))["exe"])

    report = os.path.join(WORK, "msi_startup.json")
    proc = subprocess.run([exe, "--startup-report", report],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          cwd=TARGET)
    text = proc.stdout.decode("utf-8", errors="replace")
    check("--startup-report rc 0 tu ban MSI", proc.returncode == 0,
          "rc=%d %s" % (proc.returncode, text[-300:]))
    if os.path.isfile(report):
        payload = json.load(open(report, encoding="utf-8"))
        check("startup-report: frozen + moi check xanh",
              payload.get("frozen") and all(payload["checks"].values()),
              payload.get("checks"))
        check("startup-report: boot khong nap cv2",
              payload["control"]["cv2_da_nap_luc_boot"] is False)
        check("startup-report: do duoc RAM that",
              payload["ram_at_window_kib"] > 10000,
              payload["ram_at_window_kib"])
        note("boot s / RAM KiB", (payload["boot_to_window_s"],
                                  payload["ram_at_window_kib"]))
        check("anh chung minh cua ban MSI",
              os.path.isfile(os.path.join(WORK, "msi_startup.png")))
    else:
        check("startup-report viet duoc JSON", False, report)

    print("\n== 4. go sach ==")
    # Go bang dung cai duong Settings dung: QuietUninstallString trong ARP. Neu
    # no ma chay duoc thi entry ARP do co that, khong chi co ten.
    quiet = ""
    if len(arp) == 1:
        key = next(iter(arp))
        quiet = reg_read(ARP_BASE + "\\" + key, "QuietUninstallString") or ""
    # msiexec() TU them ten exe o dong lenh, nen phai bo token dau cua
    # QuietUninstallString. Lan truoc de token do tron vao, msiexec doc
    # "msiexec.exe" la duong dan package, mo hop "Windows Installer" choi ma
    # khong bao gio chay, va subprocess cho den het timeout 30 phut.
    args = (quiet.split()[1:] if quiet else ["/x", MSI]) + [
        "/norestart", "/l*v", LOG + ".un"]
    note("lenh go", "msiexec.exe " + " ".join(args))
    rc, out = msiexec(args)
    check("go silent tra ve 0", rc == 0, "rc=%d %s" % (rc, out[-500:]))
    check("thu muc test da bi xoa het", not os.path.isdir(TARGET),
          "%d file con lai" % count_files(TARGET))
    check("MSI da bi go khoi may", not msi_arp_for(TARGET), msi_arp_for(TARGET))
    check(r"HKCU .clinq da bi go", reg_read(r"Software\Classes\.clinq") is None,
          reg_read(r"Software\Classes\.clinq"))

    restore_state(state)
    check(".clinq cua may da ve dung gia tri cu",
          reg_read(r"Software\Classes\.clinq") ==
          state["clinq"][r"Software\Classes\.clinq"],
          reg_read(r"Software\Classes\.clinq"))
    check('lenh mo .clinq da ve dung duong dan ban Inno',
          (reg_read(r"Software\Classes\Clinging.Project\shell\open\command") or
           "").lower() ==
          (state["clinq"][r"Software\Classes\Clinging.Project"
                          r"\shell\open\command"] or "").lower(),
          reg_read(r"Software\Classes\Clinging.Project\shell\open\command"))
    check_lnk_back(state["lnk"][0], "shortcut Desktop da ve dung cho cu")
    check_lnk_back(state["lnk"][1], "shortcut Start Menu da ve dung cho cu")

    print("\nsummary: %s  (%d fail)" %
          ("ALL PASS" if not FAILS else "FAIL: " + ", ".join(FAILS),
           len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
