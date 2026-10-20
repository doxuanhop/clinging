"""Chup lai vet may truoc/sau khi cai CA HAI installer, va in ra lech giua hai lan.

    python scratch\\install_both_state.py before
    python scratch\\install_both_state.py after
    python scratch\\install_both_state.py diff

VI SAO PHAI CO: lan nay cai that len may, khong phai vao thu muc test. Ba thu
bi ghi de co the lam hop le lan cai: hai khoa `.lnk` (Desktop + Start Menu),
khoa lien hop `.clinq` trong HKCU\\Software\\Classes, va danh sach ARP. Du lieu
project cua nguoi dung (HKCU\\Software\\QeafivelsSoftware\\Clinging) thi KHONG
duoc phep doi - no la thứ duy nhất trong bo nay ma khong tai tao duoc.
"""

import json
import os
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from msi_install_probe import (ARP_BASE, CLINQ_KEYS, DESKTOP_LNK, MENU_LNK,
                               lnk_target, msi_arp_entries, reg_read)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_SETTINGS = r"Software\QeafivelsSoftware\Clinging"
DIRS = [os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Clinging"),
        os.path.join(os.environ["LOCALAPPDATA"], "Programs", "ClingingMSI")]


def settings_values():
    out = {}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_SETTINGS)
    except OSError as exc:
        return {"error": str(exc)}
    for i in range(winreg.QueryInfoKey(key)[1]):
        name, value, _t = winreg.EnumValue(key, i)
        out[name] = str(value)
    winreg.CloseKey(key)
    return out


def dir_state(root):
    exe = os.path.join(root, "Clinging.exe")
    if not os.path.isfile(exe):
        return {"exists": False}
    n = sum(len(names) for _d, _s, names in os.walk(root))
    return {"exists": True, "files": n,
            "exe_mtime": os.path.getmtime(exe),
            "exe_size": os.path.getsize(exe)}


def tree_state(root):
    """Duu an toan cua du lieu nguoi dung: dem file + mtime moi nhat.

    Installer khong duoc cham vao hai thu muc nay. Neu mot file nao bi ghi lai
    thi max_mtime doi, va phep diff in ra duoc no la file nao.
    """
    if not os.path.isdir(root):
        return {"exists": False}
    files, newest, newest_path, total = 0, 0.0, None, 0
    for base, _sub, names in os.walk(root):
        for name in names:
            p = os.path.join(base, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files += 1
            total += st.st_size
            if st.st_mtime > newest:
                newest, newest_path = st.st_mtime, p
    return {"exists": True, "files": files, "bytes": total,
            "newest": newest_path}


def capture():
    userdata = {
        os.path.expanduser("~/.clinqing"): tree_state(
            os.path.expanduser("~/.clinqing")),
        core_settings_dir(): tree_state(core_settings_dir()),
    }
    return {
        "clinq": {k: reg_read(k) for k in CLINQ_KEYS},
        "lnk": {"desktop": lnk_target(DESKTOP_LNK), "menu": lnk_target(MENU_LNK)},
        "arp_clinging": msi_arp_entries(),
        "arp_scanned": sorted(k for k in _uninstall_keys()
                              if "cling" in (k or "").lower()),
        "settings": settings_values(),
        "userdata": userdata,
        "dirs": {d: dir_state(d) for d in DIRS},
    }


def core_settings_dir():
    """Thu muc settings cua dung core/settings.app_data_dir() — khong tu phat minh."""
    import sys as _sys
    _sys.path.insert(0, REPO)
    from core.settings import app_data_dir
    return str(app_data_dir())


def _uninstall_keys():
    names = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP_BASE)
    except OSError:
        return names
    for i in range(winreg.QueryInfoKey(root)[0]):
        sub = winreg.EnumKey(root, i)
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP_BASE + "\\" + sub)
            display = winreg.QueryValueEx(k, "DisplayName")[0]
            winreg.CloseKey(k)
        except OSError:
            continue
        if "cling" in str(display).lower():
            names.append(str(display) + " @ " + sub)
    winreg.CloseKey(root)
    return names


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "before").lower()
    path = os.path.join(REPO, "scratch", "install_state_%s.json" % mode)
    if mode == "diff":
        before = json.load(open(path.replace("_diff", "_before"),
                                encoding="utf-8"))
        after = json.load(open(path.replace("_diff", "_after"), encoding="utf-8"))
        for section in ("clinq", "lnk", "settings", "dirs", "arp_scanned"):
            if before[section] != after[section]:
                print("LECH %s" % section)
                print("   truoc: %s" % json.dumps(before[section], indent=1))
                print("   sau : %s" % json.dumps(after[section], indent=1))
        if before["userdata"] != after["userdata"]:
            print("CANH BAO: du lieu nguoi dung da doi")
            print("   truoc: %s" % json.dumps(before["userdata"], indent=1))
            print("   sau : %s" % json.dumps(after["userdata"], indent=1))
        else:
            print("OK: du lieu nguoi dung (~/.clinqing + settings) khong doi")
        if before["settings"] != after["settings"]:
            print("CANH BAO: khoa registry du lieu project da doi")
        else:
            print("OK: %d khoa registry du lieu project giu nguyen"
                  % len(after["settings"]))
        return 0
    state = capture()
    json.dump(state, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(json.dumps(state, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
