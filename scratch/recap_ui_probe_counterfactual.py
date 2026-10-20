"""Phản chứng cho gate UI: cắt một khớp thật thì ĐỎ đúng gate tương ứng.

Chạy recap_ui_probe trong process con riêng (mỗi lỗi một process) vì probe dựng
MainWindow thật; nhiều cửa trong một process dễ chết lúc thoát hơn là báo lỗi
giả. Parent không sửa file nào — mọi lỗi chỉ sống trong bộ nhớ của con.

Mỗi case phải đỏ VÌ ĐÚNG CÂU HỎI của nó (soạn văn bản lỗi), đỏ vì một lỗi khác
coi như không tính.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_recap_ui_cf_child.py")

# (mode, gate phải đỏ, đoạn thông báo chứng minh đúng gate)
CASES = [
    ("button",   "nut header mo hop thoai",   "khong mo duoc hop thoai"),
    ("apply",    "dieu khien ghi model",      "dieu khien khong ghi"),
    ("repaint",  "Canvas ve lai",             "khong ve lai"),
    ("undopush", "dong = 1 muc undo",         "muc undo"),
    ("before",   "undo tra trang thai cu",    "undo khong tra ve"),
    ("refresh",  "mo lai doc dung model",     "mo lai hop thoai"),
    ("drawfg",   "lop phu thay doi khung",    "khong thay doi khung"),
    ("bind",     "canvas biet model (KL)",    "khong thay doi khung"),
    ("chrome",   "hop thoai khong vuot man hinh", "vuot man hinh"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(mode):
    proc = subprocess.run([sys.executable, "-u", CHILD, mode],
                          capture_output=True, text=True, timeout=600,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
    lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    return proc.returncode, lines[-1] if lines else (proc.stdout or "").strip()[-120:]


def main():
    fails = []
    only = set(sys.argv[1:])
    for mode, gate, needle in CASES:
        if only and mode not in only:
            continue
        rc, msg = run(mode)
        if rc == 0:
            fails.append("%s: cat mat noi '%s' ma probe van xanh" % (mode, gate))
            print("XANH (SAI)   %-9s %s" % (mode, gate))
        elif needle.lower() not in msg.lower():
            fails.append("%s: do sai gate (mong '%s', nhan '%s')" % (mode, needle, msg[:120]))
            print("DO (SAI)     %-9s -> %s" % (mode, msg[:140]))
        else:
            print("DO (dung)    %-9s %s -> %s" % (mode, gate, msg[:110]))

    # Sau cuoi: khong cat gi phai xanh, VA anh chung minh phai sinh ra tu lan sach nay.
    rc, msg = run("clean")
    if rc != 0:
        fails.append("clean: probe bi do khi khong cat gi")
        print("DO (SAI)     clean     -> %s" % msg[:160])
    else:
        print("XANH (dung)  clean     -> %s" % msg.replace("\\\\", "\\")[-160:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
