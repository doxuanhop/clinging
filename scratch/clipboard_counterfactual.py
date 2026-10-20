"""Phan chung cho dong selftest `clipboard clip Ctrl+C/V`.

Dong nay noi: Ctrl+C snapshot dung clip dang chon, Ctrl+V dan ra id moi giu
nguyen font/hinh hoc + le bo cuc tuong doi, va moi lan dan la MOT buoc undo.
Mot phien ban CU xanh thi gate vo nghia, nen probe chen vet cu vao HAI file
nguon THAT (core/commands.py, core/clip_clipboard.py), chay
`python main.py --selftest` THAT, va doi row clipboard do vi dung ly do cua
phien ban ay, khong keo theo dong khac. Byte duoc khoi phuc trong finally roi
selftest lai mot lan nua phai XANH.

Sau phien ban CU va ly do mong doi:
  1. `PasteClipsCommand.execute` goi `get_clip` thay `place_clip`: lenh dan khong
     con di qua seam model. Mong do o "seam clipboard thieu".
  2. `copy_from` gan `self._entries = []`: clipboard bao rong sau copy.
     Mong do o "clipboard bao trong sau khi copy".
  3. `entry.offset = entry.offset - base` thanh `= 0.0`: nhieu clip dan chong len
     nhau mat bo cuc. Mong do o "le bo cuc tuong doi".
  4. `undo` thanh `pass`: buoc dan khong hoan tac duoc.
     Mong do o "undo hai lan paste khong tra ve".

```bash
python scratch/clipboard_counterfactual.py
```
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "clipboard clip Ctrl+C/V"

COMMANDS = os.path.join(ROOT, "core", "commands.py")
CLIPBOARD = os.path.join(ROOT, "core", "clip_clipboard.py")

MUTATIONS = [
    ("dan_khong_qua_place_clip", COMMANDS,
     b"            placed = self._model.place_clip(\n",
     b"            placed = self._model.get_clip(  # CU: khong dat clip\n",
     "seam clipboard thieu"),
    ("clipboard_bao_rong", CLIPBOARD,
     b"        self._entries = collected\n",
     b"        self._entries = []  # CU: copy xong van rong\n",
     "clipboard bao trong sau khi copy"),
    ("mat_le_bo_cuc", CLIPBOARD,
     b"            entry.offset = entry.offset - base\n",
     b"            entry.offset = 0.0  # CU: khong gi le tuong doi\n",
     "le bo cuc tuong doi"),
    ("undo_khong_xoa", COMMANDS,
     b"        for clip_id in reversed(self._pasted_ids):\n"
     b"            self._model.remove_clip(clip_id)\n"
     b"        self._pasted_ids = []\n",
     b"        pass  # CU: undo khong xoa ban dan\n",
     "undo hai lan paste khong tra ve"),
]


def run_selftest(report):
    proc = subprocess.run([sys.executable, "main.py", "--selftest", report],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    with open(report, encoding="utf-8") as handle:
        payload = json.load(handle)
    row = next((r for r in payload["checks"] if r["name"] == ROW), None)
    return proc.returncode, payload, row


def main():
    originals = {path: open(path, "rb").read()
                 for _, path, _, _, _ in MUTATIONS}
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_clipboard_cf_%d.json" % os.getpid())
    checks = []
    try:
        for name, path, needle, repl, expect in MUTATIONS:
            if originals[path].count(needle) != 1:
                print("BUG: vet cua %s xuat hien %d lan trong %s, can 1" %
                      (name, originals[path].count(needle),
                       os.path.relpath(path, ROOT)))
                return 2
            with open(path, "wb") as handle:
                handle.write(originals[path].replace(needle, repl, 1))
            try:
                rc, payload, row = run_selftest(report)
            finally:
                with open(path, "wb") as handle:
                    handle.write(originals[path])
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            checks.append((name, red, rc, others, detail))
            print("%-28s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:120]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)
        if os.path.exists(report):
            os.remove(report)

    rc, payload, row = run_selftest(report)
    green = rc == 0 and row is not None and row["ok"]
    if os.path.exists(report):
        os.remove(report)
    print("%-28s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    print("%s" % ("ALL PASS" if green and all(c[1] for c in checks)
                  else "CO %d KET QUA FAIL" %
                       sum(0 if c[1] else 1 for c in checks)))
    return 0 if green and all(c[1] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
