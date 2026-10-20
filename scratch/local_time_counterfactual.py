"""Phan chung cho DÒNG --selftest "xem trước = xuất: mốc thời gian cục bộ".

Row ``_local_time_ok`` là thứ duy nhất chứng minh preview và export không còn
tự viết hai phép tính khác nhau cho cùng một mốc thời gian. Mỗi mode cắt đúng
một mắt xích; parent chỉ công nhận khi message đỏ ĐÚNG câu hỏi của mắt xích đó.

Cần thật: một mode quay về xanh nghĩa là row chỉ trang trí.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_local_time_cf_child.py")

# (mode, mat xich bi cat, doan message chung minh do DUNG gate)
CASES = [
    ("boundary",       "bien [0,duration) luc cuoi clip", "bien local_time_at sai"),
    ("preview_split",  "preview dung diem vao chung",     "tu tinh moc thoi gian"),
    ("no_seam",        "diem vao chung ton tai",          "local_time_at"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(mode):
    proc = subprocess.run([sys.executable, "-u", CHILD, mode],
                          capture_output=True, text=True, timeout=900,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT,
                                         "PYTHONIOENCODING": "utf-8"})
    out = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return proc.returncode, (out[-1] if out else "")


def main():
    fails = []
    only = set(sys.argv[1:])
    for mode, link, needle in CASES:
        if only and mode not in only:
            continue
        rc, msg = run(mode)
        if rc == 0:
            fails.append("%s: cat '%s' ma row van XANH" % (mode, link))
            print("XANH (SAI)   %-15s %s" % (mode, link))
        elif needle.lower() not in msg.lower():
            fails.append("%s: do sai gate (mong '%s', nhan '%s')"
                         % (mode, needle, msg[:180]))
            print("DO (SAI)     %-15s -> %s" % (mode, msg[:190]))
        else:
            print("DO (dung)    %-15s %s -> %s" % (mode, link, msg[:130]))

    rc, msg = run("clean")
    if rc != 0:
        fails.append("clean: row bi DO khi khong cat gi")
        print("DO (SAI)     clean           -> %s" % msg[:200])
    else:
        print("XANH (dung)  clean           -> %s" % msg[-150:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
