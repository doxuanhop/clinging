"""Don mot ban MSI test con sot sau khi probe bi treo, roi phuc hoi may.

Chay mot lan: python -u scratch\\msi_cleanup.py
"""

import json
import os
import subprocess
import sys
import winreg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO, "build", "msitest")
SNAPSHOT = os.path.join(REPO, "scratch", "msi_machine_state.json")
ARP_BASE = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
CLINQ_KEYS = (
    r"Software\Classes\.clinq",
    r"Software\Classes\Clinging.Project",
    r"Software\Classes\Clinging.Project\DefaultIcon",
    r"Software\Classes\Clinging.Project\shell\open\command",
)


def reg_read(key, name=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as h:
            return winreg.QueryValueEx(h, name)[0]
    except OSError:
        return None


def arp_for(target):
    rows = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ARP_BASE) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, i)
                loc = reg_read(ARP_BASE + "\\" + name, "InstallLocation") or ""
                if loc.lower().rstrip("\\") == target.lower():
                    rows.append(name)
    except OSError:
        pass
    return rows


def main():
    keys = arp_for(TARGET)
    print("ARP tro vao thu muc test:", keys)
    for key in keys:
        argv = ["msiexec.exe", "/x", key, "/qn", "/norestart",
                "/l*v", os.path.join(REPO, "scratch", "msiexec.log.un")]
        print("lenh:", " ".join(argv))
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=1800)
        print("rc=%d" % proc.returncode)

    print("con thu muc test:", os.path.isdir(TARGET),
          os.path.isdir(TARGET) and
          sum(len(n) for _d, _s, n in os.walk(TARGET)))
    print("ARP con lai:", arp_for(TARGET))
    print("clinq sau khi go:", {k: reg_read(k) for k in CLINQ_KEYS})

    state = json.load(open(SNAPSHOT, encoding="utf-8"))
    import msi_install_probe as probe
    probe.restore_state(state)
    print("clinq da phuc hoi:", {k: reg_read(k) for k in CLINQ_KEYS})
    for snap in state["lnk"]:
        print("lnk", snap["path"], "->", probe.lnk_target(snap["path"]))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
