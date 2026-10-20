"""Phản chứng cho gate bộ chọn karaoke: cắt một khớp thật thì ĐỎ đúng gate đó.

Mỗi lỗi chạy trong process con riêng vì probe dựng MainWindow thật; hai cửa trong
một process chết lúc thoát nhanh hơn là báo lỗi giả. Parent không sửa file nào —
mọi lỗi chỉ sống trong bộ nhớ của con.

Đỏ là bắt buộc, nhưng đỏ VÌ SAI LÝ DO cũng tính là hỏng: mỗi case so cả mã lỗi
và đoạn thông báo, để "style bị bỏ qua" không ăn may đỏ ở gate nhãn trùng.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_karaoke_ui_cf_child.py")

# (mode, khớp bị cắt, đoạn thông báo chứng minh đỏ đúng gate đó)
CASES = [
    ("registry",     "combo phai co 8 khoa",        "khong dung 8 khoa"),
    ("labels",       "8 nhan khong trung",          "nhan kieu trung nhau"),
    ("dead_write",   "chon kieu ghi vao model",     "clip.text_style van"),
    ("no_refresh",   "doi kieu thi canvas ve lai",  "khong ve lai"),
    ("undo_push",    "tab chu khong tao muc undo",  "muc undo"),
    ("dupe_key",     "moi dong ghi dung khoa",      "ghi sai khoa"),
    ("no_readback",  "mo lai doc kieu tu model",    "khong doc dung kieu"),
    ("style_ignored","duong ve dung style",         "khong doi khung preview"),
    ("flame_dead",   "anh chung minh phai khac nhau", "giong het nhau"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(mode):
    proc = subprocess.run([sys.executable, "-u", CHILD, mode],
                          capture_output=True, text=True, timeout=900,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
    lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    return proc.returncode, (lines[-1] if lines else (proc.stdout or "").strip()[-160:])


def main():
    fails = []
    only = set(sys.argv[1:])
    for mode, gate, needle in CASES:
        if only and mode not in only:
            continue
        rc, msg = run(mode)
        if rc == 0:
            fails.append("%s: cat mat noi '%s' ma probe van xanh" % (mode, gate))
            print("XANH (SAI)   %-13s %s" % (mode, gate))
        elif needle.lower() not in msg.lower():
            fails.append("%s: do sai gate (mong '%s', nhan '%s')" % (mode, needle, msg[:140]))
            print("DO (SAI)     %-13s -> %s" % (mode, msg[:150]))
        else:
            print("DO (dung)    %-13s %s" % (mode, gate))

    rc, msg = run("clean")
    if rc != 0:
        fails.append("clean: probe bi do khi khong cat gi")
        print("DO (SAI)     clean         -> %s" % msg[:200])
    else:
        print("XANH (dung)  clean         -> %s" % msg.replace("\\\\", "\\")[-200:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
