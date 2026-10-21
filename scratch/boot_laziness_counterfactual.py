"""Phan chung cho ba cua moi cua `--startup-report`.

    python scratch/boot_laziness_counterfactual.py

Ba check `boot_khong_keo_trang_dung`, `boot_khong_psutil` va `boot_khong_keo_nen`
xanh hom nay chua co nghia gi neu chung la loai luan luon xanh. Probe nay chay
CUNG duong boot that (`main._boot` + `diagnostics.run_startup_report`) hai lan:

  * SACH     — khong lam gi them: ca ba phai True, rc 0.
  * DOC NHIEM — nap lai ba thu ma ban cu nap: `import ui.main_window` (dong
    `from ui.main_window import MainWindow` o dau ui/main_controller.py),
    `system_stats.psutil_or_none()` (psutil bi keo vong khoi dong), va
    `import ui.compress_dialog` (hop thoai Nen). Ca ba phai False, rc 1, VA
    `boot_khong_cv2` van phai True — neu do red ca cv2 thi phep thu da pha mot
    thu khac chu khong phai phan chung dieu can chung.

Vet thu ba nay sinh ra tu mot that bai do duoc 21/10/2026: hai dong dau XANH
het trong luc hop thoai nen bi keo len duong boot va boot cham them 0,428 s,
bo do phan biet cua chung.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(REPO, "scratch", "_boot_laziness_child.py")

CODE = '''\
import sys
sys.path.insert(0, __REPO__)
import main

if __POISON__:
    # Cach viet cua ban cu: trang dung phim nam trong lan boot cua trang Home,
    # va psutil duoc nap de do CPU/RAM truk khi cua so kip ve. Vet thu ba la
    # hop thoai Nen bi keo len dau file cua mot module duong boot — ke ca khi
    # `ui.main_window` van vang no van nam trong cay import.
    import ui.main_window  # noqa: F401
    import ui.compress_dialog  # noqa: F401
    from core import system_stats
    system_stats.psutil_or_none()

entry = sys.modules["__main__"]
entry._boot = main._boot
entry.BOOT_MARKS = main.BOOT_MARKS
entry._mark = main._mark

import diagnostics
rc = diagnostics.run_startup_report(["child", r"__REPORT__"])
print("RC %d" % rc)
raise SystemExit(rc)
'''


def run(poison, report):
    with open(CHILD, "w", encoding="utf-8") as handle:
        handle.write(CODE.replace("__REPO__", repr(REPO))
                     .replace("__POISON__", repr(bool(poison)))
                     .replace("__REPORT__", report))
    proc = subprocess.run([sys.executable, CHILD], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=REPO)
    if not os.path.isfile(report):
        print((proc.stdout or "")[-800:])
        print((proc.stderr or "")[-800:])
        raise SystemExit("con khong viet duoc bao cao (poison=%s)" % poison)
    return proc.returncode, json.load(open(report, encoding="utf-8"))


def main():
    clean = os.path.join(REPO, "scratch", "_laz_clean.json")
    dirty = os.path.join(REPO, "scratch", "_laz_dirty.json")
    try:
        rc_clean, d_clean = run(False, clean)
        rc_dirty, d_dirty = run(True, dirty)
    finally:
        for path in (CHILD, clean, dirty):
            if os.path.isfile(path):
                os.remove(path)
    keys = ("boot_khong_keo_trang_dung", "boot_khong_psutil",
            "boot_khong_keo_nen")
    print("SACH  rc=%d %s boot=%.3f ram=%d"
          % (rc_clean, {k: d_clean["checks"][k] for k in keys},
             d_clean["boot_to_window_s"], d_clean["ram_at_window_kib"]))
    print("DOC   rc=%d %s boot=%.3f ram=%d"
          % (rc_dirty, {k: d_dirty["checks"][k] for k in keys},
             d_dirty["boot_to_window_s"], d_dirty["ram_at_window_kib"]))
    ok = (rc_clean == 0 and d_clean["ok"] is True
          and all(d_clean["checks"][k] for k in keys)
          and rc_dirty == 1 and d_dirty["ok"] is False
          and all(d_dirty["checks"][k] is False for k in keys)
          and d_dirty["checks"]["boot_khong_cv2"] is True
          and d_dirty["checks"]["cua_so_lo"] is True)
    do = round(d_dirty["boot_to_window_s"] - d_clean["boot_to_window_s"], 3)
    ram = d_dirty["ram_at_window_kib"] - d_clean["ram_at_window_kib"]
    print("chen lai ban cu: boot %+.3f s, RAM luc cua so %+d KiB" % (do, ram))
    print(("PASS " if ok else "FAIL ")
          + "ba cua do RED vi dung ly do, khong phai RED vien")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
