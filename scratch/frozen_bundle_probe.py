"""scratch/frozen_bundle_probe.py

Chung minh ban dong goi (dist/Clinging/Clinging.exe) du chay THAT, khong phai
chi "file to hon 0 byte".

Phan biet voi " chay duoc la du":
  * --selftest duoc chay chinh trong exe dong goi, nen moi import/phai di qua
    boundary cua bundle (memory: tests must share the production path).
  * Counterfactual: doi ten thu muc styles/ BEN TRONG bundle roi chay lai. Neu
    selftest van bao OK thi co nghia no tim thay resource o source tree D:/...
    (gia trang). Pate nay buoc selftest FAIL -> chung to no doc bundle.

Chay:  python scratch/frozen_bundle_probe.py
"""

import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(REPO, "dist", "Clinging")
EXE = os.path.join(BUNDLE, "Clinging.exe")
INTERNAL = os.path.join(BUNDLE, "_internal")
OUT = os.path.join(REPO, "scratch", "frozen_bundle_report.json")

Fails = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s   got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        Fails.append("%s: got %r want %r" % (label, got, want))
    return ok


def run_selftest(report_path, timeout=240):
    """Exe la GUI-subsystem nen stdout bac; ma thoat + file bao cao la chung cu."""
    if os.path.exists(report_path):
        os.remove(report_path)
    started = time.time()
    proc = subprocess.run([EXE, "--selftest", report_path], timeout=timeout)
    if not os.path.exists(report_path):
        raise RuntimeError("exe khong ghi bao cao (rc=%d, %.1fs)"
                           % (proc.returncode, time.time() - started))
    with open(report_path, encoding="utf-8") as handle:
        return json.load(handle), proc.returncode


def main():
    check("bundle co exe", os.path.isfile(EXE), True)
    if not os.path.isfile(EXE):
        print("\nFAILED: chua co bundle, hay chay ClingingQt.spec truoc")
        return 1

    with open(EXE, "rb") as handle:
        check("exe co header PE/MZ", handle.read(2), b"MZ")
    check("exe lon hon 1 MB", os.path.getsize(EXE) > 1024 * 1024, True)

    # FFmpeg co tinh la dung loi: app Goi ban trong PATH, khong mang theo 728 MB.
    bundled_ffmpeg = [os.path.join(root, name)
                      for root, _dirs, files in os.walk(BUNDLE)
                      for name in files if name.lower() in ("ffmpeg.exe", "ffprobe.exe")]
    check("bundle khong kem ffmpeg/ffprobe (dung ban PATH)", bundled_ffmpeg, [])

    report, rc = run_selftest(OUT)
    names = [row["name"] for row in report["checks"]]
    print("\n-- selftest trong bundle (rc=%d, %d checks) --" % (rc, len(names)))
    for row in report["checks"]:
        print("  %-32s %s  %s" % (row["name"], "OK " if row["ok"] else "BAD",
                                  row["detail"][:110]))

    check("selftest exit 0", rc, 0)
    check("selftest khong con muc nao fail", report["failed"], [])
    check("bao cao tu nha exe dong goi", report["exe"], EXE)
    check("frozen = True", report["frozen"], True)

    bundle_row = next(r for r in report["checks"] if r["name"] == "bundle dong goi")
    meipass = bundle_row["detail"].split(",")[0].strip().replace("\\", "/").lower()
    check("_MEIPASS nam trong bundle, khong phai source tree",
          meipass.startswith(BUNDLE.replace("\\", "/").lower()), True)

    # Counterfactual: lat resource cua bundle -> selftest PHAI fail.
    styles = os.path.join(INTERNAL, "styles")
    hidden = os.path.join(INTERNAL, "styles__probe_hidden")
    if os.path.isdir(styles):
        shutil.move(styles, hidden)
        try:
            cf_report, cf_rc = run_selftest(
                os.path.join(REPO, "scratch", "frozen_bundle_counterfactual.json"))
            check("counterfactual: lat styles -> selftest fail", cf_rc, 1)
            check("counterfactual: do dung la fail thieu styles",
                  "styles/*.qss + theme" in cf_report["failed"], True)
        finally:
            if os.path.isdir(hidden):
                shutil.move(hidden, styles)
        check("counterfactual: styles da duoc tra lai", os.path.isdir(styles), True)
    else:
        check("bundle co _internal/styles de doi chieu", os.path.isdir(styles), True)

    with open(os.path.join(REPO, "scratch", "frozen_bundle_probe.json"),
              "w", encoding="utf-8") as handle:
        json.dump({"report": report, "fails": Fails}, handle, ensure_ascii=False, indent=2)

    print("\n%s  (%d fail)" % ("ALL PASS" if not Fails else "FAILED: " + "; ".join(Fails),
                               len(Fails)))
    return 0 if not Fails else 1


if __name__ == "__main__":
    sys.exit(main())
