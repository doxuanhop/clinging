"""scratch/frozen_bundle_probe.py

Chung minh ban dong goi (dist/Clinging/Clinging.exe) du chay THAT, khong phai
chi "file to hon 0 byte".

Phan biet voi " chay duoc la du":
  * --selftest duoc chay chinh trong exe dong goi, nen moi import/phai di qua
    boundary cua bundle (memory: tests must share the production path).
  * Counterfactual thu nhat: doi ten thu muc styles/ BEN TRONG bundle roi chay
    lai. Neu selftest van bao OK thi co nghia no tim thay resource o source tree
    D:/... (gia trang). Pate nay buoc selftest FAIL -> chung to no doc bundle.
  * Counterfactual thu hai (ve MA NGUON, khong chi resource): an `core/` cua
    tree nguon trong luc exe chay. xanh = PYZ la noi duy nhat no lay
    `core.clip_effects`; do = bundle tung nhan ngan hang cua nguon.

Chay:  python scratch/frozen_bundle_probe.py
"""

import json
import os
import shutil
import subprocess
import sys
import time

# stdout cua probe nay in CHI TIET selftest, ma chi tiet co chu co dau ("Trang
# chu 5 nut/1 menu" — dong `chrome nhin thay duoc co slot that`). Console
# cp1252 lam UnicodeEncodeError giua vong in, sau khi da in mot nua bang, nen
# hai doan counterfactual ben duoi khong chay duoc. Do 21/10/2026: rc=1,
# traceback o dong in `row["detail"]`.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

    # FFmpeg phai co TRONG bundle (spec binaries -> _internal/tools), va phai la
    # dung cap voi tools/ffmpeg tren dia. So voi ban that, khong so voi hang so:
    # check cu ("bundle khong kem ffmpeg") viet tu 1.0.1 khi app goi ban PATH,
    # nay luon FAIL vi do 21/10/2026 ca hai ben bang nhau tung byte
    # (ffmpeg 102.856.192 B, ffprobe 102.652.416 B).
    def pair_sizes(root):
        found = {}
        for _r, _d, files in os.walk(root):
            for name in files:
                if name.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                    found[name.lower()] = os.path.getsize(
                        os.path.join(_r, name))
        return found

    src_pair = pair_sizes(os.path.join(REPO, "tools", "ffmpeg"))
    bundle_pair = pair_sizes(BUNDLE)
    check("bundle kem ca hai ffmpeg + ffprobe",
          sorted(bundle_pair), ["ffmpeg.exe", "ffprobe.exe"])
    check("kich thuoc fung phin voi tools/ffmpeg (khong phai ban PATH)",
          bundle_pair, src_pair)

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

    # Dong chroma key la bang chung cv2 duoc dong goi: `chroma_key_rgb`
    # (`core/clip_effects.py:_matte_plate`) chi rut matte ve plate 256 px khi
    # import cv2 thanh cong, con cv2 = None thi no chay do day du va chinh
    # doan kiem tra danh do "branch thu nho matte khong chay o 640x360".
    # Do 21/10/2026: tree nguon bao cao dong nay xanh, nen xanh o day = bundle
    # co cv2 + co duong matte thu nho nhu nguon.
    chroma_rows = [r for r in report["checks"] if "chroma" in r["name"]]
    check("bundle co dong selftest chroma key", len(chroma_rows), 1)
    if chroma_rows:
        check("selftest dong goi: chroma OK", chroma_rows[0]["ok"], True)
        check("selftest dong goi: matte thu nho khong doi quyet dinh",
              "matte 256 px" in chroma_rows[0]["detail"], True)

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

    # Phan chung ve MA NGUON: an `core/` cua tree nguon trong luc exe chay.
    # Duong cua no trong bundle nam trong PYZ (`_internal/Clinging`), nen mot
    # bundle tu cung cap PHAI con xanh; neu tung nhan ngan hang cua nguon thi
    # moi import `core.*` se chet tai cho. Dao thuoc nay khong thay doi file
    # nao ben trong `core/` va duoc phuc hoi ngay trong finally.
    src_core = os.path.join(REPO, "core")
    src_hidden = os.path.join(REPO, "_core_probe_hidden")
    if not os.path.isdir(src_hidden):
        shutil.move(src_core, src_hidden)
        try:
            hide_report, hide_rc = run_selftest(
                os.path.join(REPO, "scratch", "frozen_bundle_hide_core.json"))
            check("counterfactual: an source/core -> exe van exit 0 (doc PYZ)",
                  hide_rc, 0)
            check("counterfactual: khong muc nao fail khi source/core bi an",
                  hide_report["failed"], [])
            check("counterfactual: dong chroma van xanh khi source/core bi an",
                  [r["ok"] for r in hide_report["checks"] if "chroma" in r["name"]],
                  [True])
            # So voi baseline tung byte: an source ma so lieu doi = exe tung lay
            # mot phan nao do tu tree nguon roi thay bang cai khac.
            hide_chroma = [r["detail"] for r in hide_report["checks"]
                           if "chroma" in r["name"]]
            check("counterfactual: chi tiet chroma giong het baseline tung byte",
                  hide_chroma, [chroma_rows[0]["detail"]] if chroma_rows else [])
        finally:
            shutil.move(src_hidden, src_core)
        check("counterfactual: source/core da duoc tra lai",
              os.path.isdir(src_core), True)
    else:
        check("khong con sot _core_probe_hidden tu lan chay truoc", False, True)

    with open(os.path.join(REPO, "scratch", "frozen_bundle_probe.json"),
              "w", encoding="utf-8") as handle:
        json.dump({"report": report, "fails": Fails}, handle, ensure_ascii=False, indent=2)

    print("\n%s  (%d fail)" % ("ALL PASS" if not Fails else "FAILED: " + "; ".join(Fails),
                               len(Fails)))
    return 0 if not Fails else 1


if __name__ == "__main__":
    sys.exit(main())
