"""Phan chung cho dong selftest `luu du an: ghi hong khong pha ban cu`.

Cach do la do byte trong `core/project_storage.py`: bon phien ban CU duoc chen
nguyen vet vao file that, chay `python main.py --selftest` THAT moi lan, va doan
row do PHAI do vi dung ly do cua phien ban ay, khong do vi mot loi khac. Sau
cung byte duoc khoi phuc va mot lan selftest nua phai XANH, neu khong thi probe
da de lai nguon bi hong.

Bon phien ban CU va ly do mong doi:
  1. `open(path, "w")` + `json.dump` chen nhau: cat ngat file that truoc khi
     payload hong. Mong row do o "lan ghi hong da cham vao file that".
  2. Khong quay ban recovery. Mong do o "recovery khong quay/prune dung".
  3. Handler loi in chu co dau: tren console cp1252 cua may nay no raise
     UnicodeEncodeError thay vi tra None. Mong do vi "UnicodeEncodeError".
  4. `os.makedirs(os.path.dirname(path))` khong co `or "."`: ten tuong doi hong
     lang le. Mong do o "ten file tuong doi khong luu duoc".

```bash
python scratch/save_atomic_counterfactual.py
```
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "core", "project_storage.py")
ROW = "luu du an: ghi hong khong pha ban cu"

NEW_WRITE = (
    "    # Serialize TRUOC khi cham vao file that: loi payload thi file cu van"
    " nguyen.\n"
    "    try:\n"
    "        payload = json.dumps(project_data, ensure_ascii=False,\n"
    "                             indent=2).encode(\"utf-8\")\n"
    "    except Exception as e:\n"
    "        print(\"Loi luu du an: %s\" % e)\n"
    "        return False\n"
    "    try:\n"
    "        _rotate_recovery_copy(project_path)\n"
    "        _write_bytes_atomic(project_path, payload)\n"
    "        return True\n"
)

OLD_WRITE = (
    "    try:\n"
    "        os.makedirs(os.path.dirname(project_path), exist_ok=True)\n"
    "        with open(project_path, \"w\", encoding=\"utf-8\") as f:\n"
    "            json.dump(project_data, f, ensure_ascii=False, indent=2)\n"
    "        return True\n"
)

MUTATIONS = [
    ("ghi_truncate", NEW_WRITE.encode("utf-8"), OLD_WRITE.encode("utf-8"),
     "lan ghi hong da cham vao file that"),
    ("khong_quay_recovery",
     b"        _rotate_recovery_copy(project_path)\n",
     b"        pass  # CU: khong quay ban cu\n",
     "recovery khong quay/prune dung"),
    ("handler_loi_co_dau",
     "        print(\"Loi doc du an: %s\" % e)\n".encode("utf-8"),
     "        print(f\"L\u1ed7i \u0111\u1ecdc d\u1ef1 \u00e1n: {e}\")\n".encode("utf-8"),
     "UnicodeEncodeError"),
    ("khong_co_hoac_dau_cham",
     b"    parent = os.path.dirname(target_path) or \".\"\n",
     b"    parent = os.path.dirname(target_path)\n",
     "ten file tuong doi khong luu duoc"),
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
    original = open(TARGET, "rb").read()
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_save_cf_%d.json" % os.getpid())
    checks = []
    try:
        for name, needle, repl, expect in MUTATIONS:
            if original.count(needle) != 1:
                # Gate phai chet khi dau vao rong: chen khong duoc mot vet thi
                # khong co gi de phan biet.
                print("BUG: vet cua %s xuat hien %d lan, can 1" %
                      (name, original.count(needle)))
                return 2
            with open(TARGET, "wb") as handle:
                handle.write(original.replace(needle, repl, 1))
            rc, payload, row = run_selftest(report)
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            # Do vi DUNG ly do cua no va KHONG keo theo dong khac: neu mot phien
            # ban CU lam do ca 28 dong còn lai thi probe khong phan biet duoc gi.
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            checks.append((name, red, rc, others, detail))
            print("%-24s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:120]))
    finally:
        with open(TARGET, "wb") as handle:
            handle.write(original)
        if os.path.exists(report):
            os.remove(report)

    rc, payload, row = run_selftest(report)
    green = rc == 0 and row is not None and row["ok"]
    if os.path.exists(report):
        os.remove(report)
    print("%-24s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    print("%s" % ("ALL PASS" if green and all(c[1] for c in checks)
                  else "CO %d KET QUA FAIL" %
                       sum(0 if c[1] else 1 for c in checks)))
    return 0 if green and all(c[1] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
