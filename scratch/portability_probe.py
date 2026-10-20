"""scratch/portability_probe.py

Do xem ban CAI DAT co tu song tren MAY KHAC khong co FFmpeg trong PATH khong.

May nay co ffmpeg 8.1.2 (winget), nen moi thu deu xanh. May khac thi 17 cho
goi ["ffmpeg", ...] / ["ffprobe", ...] trong core/ + ui/ se khong tim thay
trinh. Cach duy nhat de biet that bai ra sao: chay dung exe da cai nhung
CAT bot thu muc ffmpeg khoi PATH cua con, roi doc ket qua va loi no.

Day la GATE, khong phai bang in: moi dong PASS o duoi la mot dieu kien that
bai duoc. Lan chay truoc khi bundle chep ffmpeg da do chung minh dieu do —
--split-report treo 10 phut vi thieu trinh.

Khong dung file du an cua nguoi dung: moi report deu ghi vao temp rieng.

Chay:  python scratch/portability_probe.py
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEST = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Clinging",
                    "Clinging.exe")
OUT = os.path.join(ROOT, "scratch")
FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}

FAILS = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s   got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    return ok


def stripped_path():
    """PATH khong con thu muc nao chua ffmpeg.exe/ffprobe.exe."""
    keep = []
    dropped = []
    for part in os.environ["PATH"].split(os.pathsep):
        if os.path.isfile(os.path.join(part, "ffmpeg.exe")) \
                or os.path.isfile(os.path.join(part, "ffprobe.exe")):
            dropped.append(part)
        else:
            keep.append(part)
    return os.pathsep.join(keep), dropped


def run(args, report, timeout=600):
    if os.path.isfile(report):
        os.remove(report)
    proc = subprocess.run([DEST] + args + [report], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout,
                          env=ENV, **FLAGS)
    payload = None
    if os.path.isfile(report):
        with open(report, encoding="utf-8") as handle:
            payload = json.load(handle)
    return proc.returncode, payload


def hide_bundle_tools():
    """Lay ffmpeg/ffprobe DI KEM ra khoi bundle, chay --split-report, roi tra
    ve dung cho. Day la phan phan bon cua probe: neu khong the lam doan nay
    do, "ALL PASS" chi la do ffmpeg cua may nay phuc vu an sau luong.

    Ban truoc khi bundle chep ffmpeg da treo dung 10 phut o doan nay (hop
    thoai traceback console=False khong ai bam OK), nen that bai PHAI ra JSON
    va ra lenh trong vong vai chuc giay.
    """
    tools = os.path.join(os.path.dirname(DEST), "_internal", "tools")
    moved = [os.path.join(tools, name) for name in ("ffmpeg.exe", "ffprobe.exe")
             if os.path.isfile(os.path.join(tools, name))]
    report = os.path.join(OUT, "port_split_noffmpeg.json")
    started = time.time()
    try:
        for path in moved:
            os.rename(path, path + ".hidden")
        try:
            rc, payload = run(["--split-report"], report, timeout=240)
        except subprocess.TimeoutExpired:
            return None, None, round(time.time() - started, 1), moved
    finally:
        for path in moved:
            os.replace(path + ".hidden", path)
    return rc, payload, round(time.time() - started, 1), moved


def main():
    if not os.path.isfile(DEST):
        print("khong tim thay exe da cai:", DEST)
        return 1
    path, dropped = stripped_path()
    env = dict(os.environ)
    env["PATH"] = path
    env["PYTHONIOENCODING"] = "utf-8"
    globals()["ENV"] = env
    print("exe                ", DEST)
    print("bo thu muc khoi PATH", dropped)

    # Dieu kien tien quyet cua ca lan do: con cua exe da cai THAT su khong con
    # ffmpeg nao trong PATH. Khong co dong nay thi moi thu xanh chi vi may nay
    # van con ffmpeg 8.1.2, va probe khong do duoc gi ve may khac.
    probe = subprocess.run([sys.executable, "-c",
                            "import shutil;print(shutil.which('ffmpeg'))"],
                           capture_output=True, text=True, env=env)
    which = probe.stdout.strip()
    print("ffmpeg trong PATH cua con:", which or "None")
    check("PATH cua con khong con ffmpeg/ffprobe nao",
          [which, subprocess.run(
              [sys.executable, "-c",
               "import shutil;print(shutil.which('ffprobe'))"],
              capture_output=True, text=True, env=env).stdout.strip()],
          ["None", "None"])

    rc, selftest = run(["--selftest"],
                       os.path.join(OUT, "port_selftest.json"))
    print("\n== --selftest rc=%s ==" % rc)
    if selftest:
        for row in selftest["checks"]:
            if any(k in row["name"] for k in ("ffmpeg", "cat file",
                                              "trich xuat", "bundle")):
                print("  %-42s %s | %s" % (row["name"][:42],
                                           "OK " if row["ok"] else "FAIL",
                                           row["detail"][:110]))
        print("  failed rows:", selftest["failed"])
    check("selftest rc=0 tren may khong co ffmpeg trong PATH", rc, 0)
    check("selftest khong dong nao fail",
          [r["name"] for r in (selftest or {}).get("failed", [])], [])
    ff_row = next((r for r in (selftest or {}).get("checks", [])
                   if r["name"] == "ffmpeg + ffprobe tim thay"), None)
    check("selftest tim thay ban di kem, khong phai PATH",
          bool(ff_row) and "[bundled]" in str(ff_row["detail"]), True)

    rc, split = run(["--split-report"],
                    os.path.join(OUT, "port_split.json"))
    print("\n== --split-report rc=%s ==" % rc)
    if split:
        print("  nguon:", split.get("ffmpeg_source"),
              "| doan:", split.get("on_disk"),
              "| error:", str(split.get("error"))[:200])
    check("split-report rc=0 khong treo khong loi", rc, 0)
    check("split-report cat ra 3 file that tren dia",
          len((split or {}).get("on_disk", [])), 3)
    check("ffprobe doc lai duoc ca 3 doan, khong lo",
          [round(r["probe"], 1) > 0.5
           for r in (split or {}).get("segments", [])], [True, True, True])
    check("3 doan do ban ffmpeg TRONG bundle cat ra",
          [(split or {}).get("ffmpeg_source"),
           os.path.normpath(str((split or {}).get("ffmpeg_path", ""))).lower()
           .startswith(os.path.dirname(DEST).lower() + os.sep)],
          ["bundled", True])

    rc, thumb = run(["--thumbnail-report"],
                    os.path.join(OUT, "port_thumbnail.json"))
    print("\n== --thumbnail-report rc=%s ==" % rc)
    if thumb:
        print("  written:", len(thumb.get("on_disk", [])),
              "missing:", thumb.get("missing"),
              "| error:", str(thumb.get("error"))[:200])
    check("thumbnail-report rc=0 tren may khong co ffmpeg", rc, 0)
    check("thumbnail-report ve du 6 PNG, khong thieu file nao",
          [len((thumb or {}).get("on_disk", [])), (thumb or {}).get("missing")],
          [6, []])

    rc, layout = run(["--layout-report"],
                     os.path.join(OUT, "port_layout.json"), timeout=300)
    print("\n== --layout-report (mo cua so that) rc=%s ==" % rc)
    if layout:
        print("  window_height:", layout.get("window_height"),
              "timeline_pct:", layout.get("timeline_pct"))
    check("layout-report rc=0 (cong cua so that van mo)", rc, 0)
    check("cua so that cao tren 400px",
          (layout or {}).get("window_height", 0) > 400, True)

    print("\n== phan phan bon: bundle khong con ffmpeg ==")
    rc, payload, elapsed, moved = hide_bundle_tools()
    print("  rc=%s elapsed=%ss ok=%s error=%s"
          % (rc, elapsed, (payload or {}).get("ok"),
             str((payload or {}).get("error"))[:90]))
    check("thieu ffmpeg thi ve ngay, khong treo hop thoai", rc, 1)
    check("bao cao noi ro thieu ffmpeg",
          bool(payload) and payload.get("ok") is False
          and "ffmpeg" in str(payload.get("error", "")), True)
    check("khong co doan gia nao duoc ghi nhan la cat xong",
          (payload or {}).get("segments"), [])
    check("bundle duoc khoi nguyen day du",
          [os.path.isfile(p) and os.path.getsize(p) > 1048576 for p in moved],
          [True, True])

    print("\nsummary: %s  (%d fail)"
          % ("ALL PASS" if not FAILS else "FAILED", len(FAILS)))
    for line in FAILS:
        print("  -", line)
    return 1 if FAILS else 0


ENV = {}

if __name__ == "__main__":
    sys.exit(main())
