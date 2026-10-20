"""scratch/project_launch_counterfactual.py

Chung minh --project-report CO THE FAIL.

Ba loi duoi day la ba cach that ma doan "mo project tu file" co the hong, duoc
phat lai TRONG BO NHO cua process con (khong file nao bi sua), roi chay lai
chinh report:

  parse   : chi doc --project, bo qua dong ma Explorer thuc su gui
            ("Clinging.exe <duong-dan.clinq>") -> khong mo gi ca.
  restore : editor du mo nhung model khong duoc nap -> timeline trang.
  library : du an mo dung nhung thu vien trong trang -> keo khong ra tai nguyen.
  order   : thu vien du so luong nhung dao thu tu -> khoa nay so theo thu tu
            file, nen no phai do; mot phep so sanh sap xep thi khong bao gio.

  selftest: chang loi "parse" lenh truong nhung chay --selftest, de khoa moi
            trong selftest PHAI bit va chi bit dung dong cua no.

Case sach (khong patch) phai rc=0 — neu ca bon deu rc=0 thi report vo nghia.

Chay: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/project_launch_counterfactual.py
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_project_cf_child.py")
TEMP = os.environ.get("TEMP", ROOT)
# Report tu viet file nay luc bat dau, nen harness chi can biet duong dan.
FIXTURE = os.path.join(TEMP, "clinging_project_report", "Kiem chung.clinq")


def run(mode):
    out = os.path.join(TEMP, "project_cf_%s.json" % mode)
    if os.path.isfile(out):
        os.remove(out)
    if mode == "clean":
        cmd = [sys.executable, "-u", os.path.join(ROOT, "main.py"),
               "--project-report", out, FIXTURE]
    else:
        cmd = [sys.executable, "-u", CHILD, mode, out]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    payload = {}
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as handle:
            payload = json.load(handle)
    return proc.returncode, payload


def brief(mode, payload):
    if mode == "selftest":
        return "failed=%r" % (payload.get("failed"),)
    return ("mo=%s editor=%s clip=%d/%d thu_vien=%d duong_gia=%s"
            % (payload.get("mo_duoc"), payload.get("o_editor"),
               len(payload.get("clips", {})),
               len(payload.get("clips_muon", {})),
               len(payload.get("thu_vien", [])),
               payload.get("duong_gia", {}).get("tra_ve")))


def main():
    fails = []
    for mode, want_rc in (("clean", 0), ("parse", 1), ("restore", 1),
                          ("library", 1), ("order", 1), ("selftest", 1)):
        rc, payload = run(mode)
        print("%-8s rc=%d  %s" % (mode, rc, brief(mode, payload)))
        if rc != want_rc:
            fails.append("%s: muon rc=%d, thay rc=%d" % (mode, want_rc, rc))
        if mode == "order" and payload.get("thu_vien") != \
                list(reversed(payload.get("thu_vien_muon", []))):
            fails.append("order: thu vien khong bi dao thu tu nen khoa nay "
                         "khong do duoc gi (%r)" % (payload.get("thu_vien"),))
        if mode == "selftest" and payload.get("failed") != \
                ["mo du an tu file .clinq"]:
            # rc=1 do dong KHAC fail thi khoa moi chua noi len dieu gi.
            fails.append("selftest: fail khong thu ve dong .clinq: %r"
                         % (payload.get("failed"),))

    print("\n%s  (%d fail)" % ("ALL PASS" if not fails else "FAILED",
                               len(fails)))
    for line in fails:
        print("  " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
