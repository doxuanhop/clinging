"""Phản chứng cho karaoke_probe: cắt một khớp thật thì ĐỎ đúng gate tương ứng.

Probe xanh một mình không chứng minh được gì — có thể nó đo một thứ luôn luôn
đúng. Mỗi mode dưới đây vá MỘT khớp trong bộ nhớ của process con (xem
_karaoke_cf_child.py) và phải làm đỏ ĐÚNG gate được nêu tên. Đỏ vì lỗi khác,
hoặc vẫn xanh, đều tính là phản chứng thất bại.

Mode "export" và "sweep" là hai lỗi nguy hiểm nhất: cả hai để preview đẹp nguyên
vẹn trong khi file xuất ra sai.

Ghi chú trung thực về "layout" và "sweep": hai lỗi này bị gate HÌNH HỌC (mục 1)
chặn trước khi tới gate riêng của chúng — mọi thứ làm sai vị trí hoặc làm sai
trạng thái pending đều làm lệch trọng tâm mực. Đó là lớp phòng thủ đầu tiên chứ
không phải gate nhầm, nên tên gate ghi dưới đây là tên lớp đã đỏ. Hai gate chuẩn
quét (median 0.05↔0.95 và hướng q1↔q3) là canh chừng trùng lặp: mọi lỗi thứ tự
quét đều bị chặn sớm hơn, chúng tôi không dựng thêm một phản chứng giả cho chúng.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_karaoke_cf_child.py")

# (mode, gate phải đỏ, đoạn thông báo chứng minh đúng gate)
CASES = [
    ("normalize", "rac bi tu choi",                "nhan gia tri rac"),
    ("pending",   "pending la net chung",          "net pending rieng"),
    ("geometry",  "karaoke khong dich chu",        "dich"),
    ("layout",    "hop tu phai theo Qt (gate 1)",  "dich"),
    ("sweep",     "sweep dieu khien tu (gate 1)",  "dich"),
    ("staircase", "moi tu den luong dung mot lan", "bo qua mot tu"),
    ("fill",      "gradient to net chu",           "khoi dac"),
    ("ring",      "quang la pixel that",           "mo rong hop muc"),
    ("shadow",    "bong chay xuong-phai",          "khong chay xuong-phai"),
    ("export",    "export dung kieu karaoke",      "export lech"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(mode):
    proc = subprocess.run([sys.executable, "-u", CHILD, mode],
                          capture_output=True, text=True, timeout=900,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
    lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    return proc.returncode, (lines[-1] if lines else
                             (proc.stdout or "").strip()[-160:])


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
            fails.append("%s: do sai gate (mong '%s', nhan '%s')" % (mode, needle, msg[:140]))
            print("DO (SAI)     %-9s -> %s" % (mode, msg[:150]))
        else:
            print("DO (dung)    %-9s %s -> %s" % (mode, gate, msg[:110]))

    # Lan cuoi khong cat gi: phai xanh, VA anh chung minh phai sinh ra tu chinh
    # lan sach nay (khong phai con sot cua lan bi benh o tren).
    rc, msg = run("clean")
    if rc != 0:
        fails.append("clean: probe bi do khi khong cat gi")
        print("DO (SAI)     clean     -> %s" % msg[:200])
    else:
        print("XANH (dung)  clean     -> %s" % msg.replace("\\\\", "\\")[-200:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
