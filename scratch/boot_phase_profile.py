"""Tam chia pha `MainController()` bang cProfile tren dung `main._boot()`.

    python scratch/boot_phase_profile.py

Dong lenh nay KHONG thay vao --startup-report: report do tung pha, con o day can
biết BÊN TRONG pha do ham nao nam. Van goi `main._boot()` that, khong dung ban
phat rieng, vi duong thu hai la loi chung minh thu hai.
"""
import cProfile
import io
import os
import pstats
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import main  # noqa: E402

profile = cProfile.Profile()
profile.enable()
try:
    app, controller = main._boot()
finally:
    profile.disable()

stats = io.StringIO()
pstats.Stats(profile, stream=stats).sort_stats("cumulative").print_stats(400)
lines = stats.getvalue().splitlines()
want = ("main_controller.py", "home_page.py", "widgets\\common", "theme.py",
        "fontawesome.py", "custom_dialog.py", "system_stats.py")
print("== 24 dong CUMULATIVE dau tien trong cay cua app ==")
shown = 0
for line in lines:
    if any(w in line.lower() for w in want) and "site-packages" not in line:
        print(line[:150])
        shown += 1
        if shown >= 24:
            break
print("== 12 dong tot theo SELF time (bat ky) ==")
pstats.Stats(profile, stream=sys.stdout).sort_stats("tottime").print_stats(12)
sys.stdout.flush()
os._exit(0)
