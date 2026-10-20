"""Chung minh gate `boot_khong_cv2` PHAT DUOC do: chay dung duong boot that
(main._boot + diagnostics.run_startup_report) nhung lap lai cach viet CUA BAN
CU — card tu giai ma bìa ngay trong ham khoi dong, khong qua cache dia.

Neu cai bien nay khong lam do red thi `boot_khong_cv2` xanh chi la do luon luon
xanh, khong phai do app khoi dong sach.
"""

import json
import os
import subprocess
import sys

REPO = r"D:\Programming\clinging"
CHILD = os.path.join(REPO, "scratch", "_startup_counterfactual_child.py")

CODE = '''\
import sys
sys.path.insert(0, __REPO__)
import main
import ui.home_page as hp
from core.media_extractor import extract_video_thumbnail

# Cach viet cua ban cu: bìa duoc giai ma trong luc card dang duoc dung.
old_init = hp.RecentProjectCard.__init__


def sync_init(self, project_path, parent=None):
    old_init(self, project_path, parent)
    self._load_project_thumbnail()


hp.RecentProjectCard.__init__ = sync_init
# ... va chua co cache bia: goi thang vao bo giai ma.
hp.RecentProjectCard._cover_for_video = lambda self, path, h: extract_video_thumbnail(path, h)

entry = sys.modules["__main__"]
entry._boot = main._boot
entry.BOOT_MARKS = main.BOOT_MARKS
entry._mark = main._mark

import diagnostics
rc = diagnostics.run_startup_report(
    ["child", r"__REPORT__"])
print("RC %d" % rc)
raise SystemExit(rc)
'''


def main():
    report = os.path.join(REPO, "scratch", "startup_counterfactual.json")
    with open(CHILD, "w", encoding="utf-8") as handle:
        handle.write(CODE.replace("__REPO__", repr(REPO))
                     .replace("__REPORT__", report))
    proc = subprocess.run([sys.executable, CHILD], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=REPO)
    if not os.path.isfile(report):
        print(proc.stdout[-800:])
        print(proc.stderr[-800:])
        raise SystemExit("con khong viet duoc bao cao")
    row = json.load(open(report, encoding="utf-8"))
    print("rc", proc.returncode, (proc.stdout or "").strip().splitlines()[-1:])
    print("checks", row["checks"])
    print("control", row["control"])
    print("boot_to_window", round(row["boot_to_window_s"], 3),
          "ram_at_window", row["ram_at_window_kib"])
    ok = (proc.returncode == 1 and row["ok"] is False
          and row["checks"]["boot_khong_cv2"] is False
          and row["control"]["cv2_da_nap_luc_boot"] is True)
    print(("PASS " if ok else "FAIL ") +
          "phat do red khi lap lai cach viet cu")
    if proc.stderr.strip():
        print("stderr:", proc.stderr[-400:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
