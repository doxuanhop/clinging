"""Tách chi phí của từng phần trong pha MainController() bằng cách tat mot phep
thu that, roi do lai bang dung duong boot cua app (main._boot).

Moi lan chay mot process moi va tat dung mot thu. Mot dong "no_cover" chay nhanh
hon baseline moi la bang chung cho phep do; so khong tu chung minh duoc gi.
"""

import json
import os
import subprocess
import sys
import time

REPO = r"D:\Programming\clinging"
PYTHON = sys.executable
CHILD_PATH = os.path.join(REPO, "scratch", "_boot_child.py")

CHILD = '''\
import json, sys, time
sys.path.insert(0, REPO)
mode = sys.argv[1]
import main
if mode == "no_cover":
    import ui.home_page as hp
    hp.RecentProjectCard._load_project_thumbnail = lambda self: None
elif mode == "no_cards":
    import ui.home_page as hp
    hp.HomePage._load_recent_projects = lambda self: None
elif mode == "baseline":
    pass
else:
    raise SystemExit("che do khong ton tai: " + mode)
t0 = time.perf_counter()
app, controller = main._boot()
boot = time.perf_counter() - t0
out = {"mode": mode,
       "boot_s": round(boot, 4),
       "marks": [{"name": n, "t_s": round(t, 4), "ram_kib": r}
                 for n, t, r in main.BOOT_MARKS],
       "cv2_loaded": "cv2" in sys.modules,
       "ram_kib": main._working_set_kib()}
print("RESULT " + json.dumps(out))
'''


def run(mode):
    with open(CHILD_PATH, "w", encoding="utf-8") as handle:
        handle.write(CHILD.replace("REPO", repr(REPO)))
    started = time.perf_counter()
    proc = subprocess.run([PYTHON, CHILD_PATH, mode], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=REPO)
    wall = time.perf_counter() - started
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        return {"mode": mode, "wall_s": round(wall, 3),
                "error": (proc.stderr or "")[-400:]}
    row = json.loads(line[len("RESULT "):])
    row["wall_s"] = round(wall, 3)
    return row


def main():
    rows = [run(m) for m in ("baseline", "no_cover", "no_cards", "baseline")]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    with open(os.path.join(REPO, "scratch", "boot_cost_rows.json"), "w",
              encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
