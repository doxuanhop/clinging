"""Do chi phi doc module cua `import PySide6.QtGui` — ly do moi che do trong
scratch/boot_low_spec_probe.py phai tra dung chi phi nay TRUOC cua so boot.

    python scratch/_qtgui_import_cost.py

Ket qua (may nay, cache da am): ~0,54 s, va gan toan bo nam trong
`PySide6.support.signature.*` + `shibokensupport` — bo phan giai chu ky cua
PySide6, khong phai DLL Qt. App that cung phai tra khoan nay; neu no nam BEN
TRONG cua so boot o mot che do ma NGOAI cua so o mot che do khac thi wall-clock
hai ben lech nhau 0,5 s ma khong he gi do icon.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIMER = ("import time; "
         "t=time.perf_counter(); import PySide6.QtGui; "
         "print('%.3f' % (time.perf_counter()-t))")

rows = []
for _ in range(3):
    out = subprocess.run([sys.executable, "-c", TIMER], capture_output=True,
                         text=True, cwd=REPO)
    rows.append(out.stdout.strip() or out.stderr[-200:])
print("import PySide6.QtGui (3 lan, process moi):", rows)

# Bao cao importtime: module nao nang nhat tren duong den QtGui.
out = subprocess.run([sys.executable, "-X", "importtime", "-c", TIMER],
                     capture_output=True, text=True, cwd=REPO)
entries = []
for line in out.stderr.splitlines():
    parts = line.split("|")
    if len(parts) >= 3:
        try:
            # Dinh dang `-X importtime`: self [us] | cumulative | ten module.
            entries.append((int(parts[1].strip()), parts[-1].strip()))
        except ValueError:
            pass
entries.sort(reverse=True)
print("5 module co self-time lon nhat tren duong import PySide6.QtGui:")
for us, name in entries[:5]:
    print("  %7.3f s  %s" % (us / 1e6, name))
