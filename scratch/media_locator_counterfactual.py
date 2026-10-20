"""Phan chung cho dong selftest `media lac cho: preview va export cung duong dan`.

Dong nay noi hai chieu: dinh vi file lac cho chi dien ra MOT lan luc mo du an,
va khong co di nao trong nam cho cua UI/`core` duoc quay lai `os.walk(".")`.
Mot phien ban CU xanh thi gate vo nghia, nen probe chen nguyen vet cu vao ba
file nguon THAT, chay `python main.py --selftest` THAT, va doi row do DO vi
dung ly do cua phien ban ay, khong keo theo dong khac. Byte duoc khoi phuc
trong `finally` roi selftest lai mot lan nua phai XANH.

Sau phien ban CU va ly do mong doi:
  1. `MAX_DEPTH = 9`: chan kinh tim kiem bi nong, pham vi mo rong ca cay.
     Mong do o "chan kinh sau bi nong".
  2. `roots = [os.getcwd()]`: thu muc hien hanh duoc tim truoc tien, nen cam
     `clip.png` do mau cua gate bi dung thay vi file cua du an.
     Mong do o "khong tim lai duoc".
  3. `resolve_model` thanh ham rong: mo .clinq lai duong dan da chet.
     Mong do o "mo du an khong dinh vi lai file lac cho".
  4. `restore_model` (ban tam autosave) khong goi resolve nua. Mong do o ten
     seam `project_storage.restore_model`.
  5. `TimelinePanel._get_media_duration` quay ve vong `os.walk(".")` cu.
     Mong do o ten seam `TimelinePanel._get_media_duration`.
  6. `resolve_model` khong ghi `missing` nua: clip vang mat bi bao im.
     Mong do o "resolve_model dem sai".

```bash
python scratch/media_locator_counterfactual.py
```
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "media lac cho: preview va export cung duong dan"

LOCATOR = os.path.join(ROOT, "core", "media_locator.py")
STORAGE = os.path.join(ROOT, "core", "project_storage.py")
PANEL = os.path.join(ROOT, "ui", "timeline_panel.py")

MUTATIONS = [
    ("chan_kinh_nong", LOCATOR,
     b"MAX_DEPTH = 4\n", b"MAX_DEPTH = 9\n",
     "chan kinh sau bi nong"),
    ("cwd_thang_truoc", LOCATOR,
     b"    roots = []\n",
     b"    roots = [os.getcwd()]  # CU: di bo thu muc hien hanh\n",
     "khong tim lai duoc"),
    ("resolver_ham_rong", LOCATOR,
     b"    resolved, missing = [], []\n",
     b"    resolved, missing = [], []\n"
     b"    return resolved, missing  # CU: khong dinh vi gi ca\n",
     "mo du an khong dinh vi lai file lac cho"),
    ("mo_ban_tam_khong_dinh_vi", STORAGE,
     b"    from core.media_locator import resolve_model\n"
     b"    resolve_model(model)\n",
     b"    pass  # CU: ban tam autosave khong dinh vi\n",
     "project_storage.restore_model"),
    ("seam_quay_lai_os_walk", PANEL,
     b"        from core.media_locator import locate\n\n"
     b"        actual_path = locate(file_path) or file_path\n",
     b"        actual_path = file_path\n"
     b"        if not os.path.exists(actual_path):\n"
     b"            basename = os.path.basename(file_path)\n"
     b'            for root, dirs, files in os.walk("."):\n'
     b"                if basename in files:\n"
     b"                    actual_path = os.path.join(root, basename)\n"
     b"                    break\n",
     "TimelinePanel._get_media_duration"),
    ("missing_bao_im_lang", LOCATOR,
     b"                missing.append(path)\n",
     b"                pass  # CU: bao im lang\n",
     "resolve_model dem sai"),
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
                          "clinging_locator_cf_%d.json" % os.getpid())
    checks = []
    try:
        for name, path, needle, repl, expect in MUTATIONS:
            if originals[path].count(needle) != 1:
                # Gate phai chet khi dau vao rong: chen khong duoc mot vet thi
                # khong co gi de phan biet.
                print("BUG: vet cua %s xuat hien %d lan trong %s, can 1" %
                      (name, originals[path].count(needle),
                       os.path.relpath(path, ROOT)))
                return 2
            with open(path, "wb") as handle:
                handle.write(originals[path].replace(needle, repl, 1))
            try:
                rc, payload, row = run_selftest(report)
            finally:
                # Ba file nguon khac nhau nen phai tra ve nguyen vet NGAY sau
                # phep do: neu khong, phien ban CU o vong lap truoc van con
                # trong file va keo theo ten cua no vao ly do do cua vong sau.
                with open(path, "wb") as handle:
                    handle.write(originals[path])
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            # Do vi DUNG ly do cua no, KHONG keo theo dong khac, va (neu la loi
            # liet ke seam) chi mot seam bi goi ten: hai seam trong mot dong
            # nghia la phien ban CU cua vong lap truoc van con sot trong nguon.
            listed = detail.split("core.media_locator: ", 1)
            solo = ("," not in listed[1]) if len(listed) == 2 else True
            red = (row is not None and not row["ok"] and expect in detail
                    and not others and solo)
            checks.append((name, red, rc, others, detail))
            print("%-26s %s  rc=%d  do vi: %s" %
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
    print("%-26s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    print("%s" % ("ALL PASS" if green and all(c[1] for c in checks)
                  else "CO %d KET QUA FAIL" %
                       sum(0 if c[1] else 1 for c in checks)))
    return 0 if green and all(c[1] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
