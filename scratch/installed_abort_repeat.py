"""Do TY LE LAP LAI cua abort 0xC0000409 tren BAN CAI + du an that cua may.

`scratch/installed_app_probe.py` chi chay MOT lan nen khong phan biet duoc lo
ngan nhien hay lo daan. Probe nay chay lan do `ROUNDS` lan va ghi lai stderr cua
chinh exe (dong "QThread: Destroyed while thread is still running" la dau vet
cua kha nang detach - xem `scratch/teardown_detach_heavy_probe.py`).

Du an cua nguoi dung duoc MO bang lenh that cua repo (`--project-report`), khong
phai fixture ty sinh: day la dung surface da do trong
`docs/verification-gates.md`. Byte cua file .clinq va recent_projects.json duoc
luu truoc va tra lai sau moi lan do, nen do luong khong de lai lech.
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import time

ABORT = 3221226505
EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                   "Clinging", "Clinging.exe")
WORK = os.path.join(tempfile.gettempdir(), "clinging_detach_repeat")
ROUNDS = 3


def _snapshot():
    home = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    paths = glob.glob(os.path.join(home, "Clinging_Projects", "*", "*.clinq"))
    paths.append(os.path.join(appdata, "Roaming", "Clinging", "recent_projects.json"))
    snap = {}
    for path in paths:
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                snap[path] = handle.read()
    return snap


def _restore(snap):
    touched = []
    for path, data in snap.items():
        if not os.path.isfile(path):
            touched.append(path)
            continue
        with open(path, "rb") as handle:
            if handle.read() != data:
                touched.append(path)
                with open(path, "wb") as handle:
                    handle.write(data)
    return touched


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Clinging.exe"],
                         capture_output=True, text=True).stdout
    if "Clinging.exe" in out:
        raise SystemExit("PROBE DUNG: dong Clinging.exe cua nguoi dung truoc khi do")
    projects = sorted(glob.glob(os.path.join(
        os.environ.get("USERPROFILE", ""), "Clinging_Projects", "*", "*.clinq")))
    if not projects:
        raise SystemExit("PROBE DUNG: khong co .clinq nao trong Clinging_Projects")
    project = projects[0]
    print("exe: %s\ndu an: %s" % (EXE, project))
    os.makedirs(WORK, exist_ok=True)
    rows = []
    snap = _snapshot()
    try:
        for index in range(ROUNDS):
            report = os.path.join(WORK, "repeat_%d.json" % index)
            for stale in (report, report[:-5] + ".png"):
                if os.path.isfile(stale):
                    os.remove(stale)
            started = time.time()
            proc = subprocess.run([EXE, "--project-report", report, project],
                                  capture_output=True, text=True, timeout=600)
            elapsed = time.time() - started
            payload = None
            if os.path.isfile(report):
                try:
                    with open(report, encoding="utf-8") as handle:
                        payload = json.load(handle)
                except Exception:
                    payload = None
            noise = [line.strip() for line in (proc.stderr or "").splitlines()
                     if "QThread" in line or "still running" in line
                     or "Destroying" in line]
            row = {"lan": index + 1, "rc": proc.returncode & 0xFFFFFFFF,
                   "giay": round(elapsed, 1),
                   "mo_duoc": bool(payload and payload.get("mo_duoc")),
                   "o_editor": bool(payload and payload.get("o_editor")),
                   "clips": len(payload.get("clips", {})) if payload else 0,
                   "qthread": noise[:3],
                   "stderr_end": (proc.stderr or "").strip().splitlines()[-3:]}
            rows.append(row)
            print("lan %d: rc=%-11d %5.1fs payload=%s/%s clip=%d %s"
                  % (row["lan"], row["rc"], row["giay"], row["mo_duoc"],
                     row["o_editor"], row["clips"], " | ".join(noise)[:110]))
    finally:
        touched = _restore(snap)
        print("file nguoi dung da tra lai byte: %d" % len(touched))
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "installed_abort_repeat.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"exe": EXE, "rounds": rows,
                       "abort": sum(1 for r in rows if r["rc"] == ABORT),
                       "user_touched": len(touched)}, handle,
                      ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
