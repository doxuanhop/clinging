"""Phản chứng cho DÒNG --selftest karaoke: cắt một khớp thật thì row phải ĐỎ.

Row ``_karaoke_ok`` trong diagnostics.py là thứ duy nhất chứng minh tám kiểu
karaoke còn sống trong bản đóng gói — nên nó phải đỏ được, không phải xanh vì
tự tô. Mỗi mode cắt đúng một mắt xích và parent chỉ công nhận khi message đỏ
ĐÚNG câu hỏi của mắt xích đó; đỏ vì lỗi khác coi như chưa cắt.

Chạy mỗi mode trong process con riêng vì row dựng QPainter/FrameComposer thật;
một process chết giữa chừng không được kéo theo các mode còn lại. Parent không
sửa file nguồn nào — mọi lỗi chỉ sống trong bộ nhớ của con.

Cần thật: một nửa mode quay về xanh nghĩa là row chỉ là trang trí.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_selftest_karaoke_cf_child.py")

# (mode, mat xich bi cat, doan message chung minh do DUNG gate)
CASES = [
    ("registry",  "registry 8 khoa",              "khong phai 8"),
    ("normalize", "rac bi tu choi",               "rac"),
    ("seam",      "8 kieu ve 8 net khac nhau",    "duong ve bi gop"),
    ("sweep",     "p dieu khien tu sang",         "khong quet theo tu"),
    ("staircase", "moi tu den dung mot lan",      "bo qua tu"),
    ("clock",     "hue/flash chay theo t",        "khong chay theo dong ho"),
    ("counter",   "tat dinh, khong bo dem",       "khong tat dinh"),
    ("export",    "export doc text_style",        "bo qua clip.text_style"),
    ("file",      "kiem qua .clinq",              "mat khi quay qua file"),
    ("flame_blob", "tu dang hat kieu lua con la chu", "tu_dang_hat_bi_lap_lo"),
    # Bo het Quang cung lam mat luon tinh phu thuoc t, nen o row nay gate DONG
    # HO do truoc. Do o canh khac cua CUNG mot loi — van la do dung, va do la
    # ly do khop spill cua phep do nay chi do THAT trong --style-report.
    ("flame_no_halo", "bo het Quang thi cung hong", "khong chay theo dong ho"),
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
            print("XANH (SAI)   %-10s %s" % (mode, link))
        elif needle.lower() not in msg.lower():
            fails.append("%s: do sai gate (mong '%s', nhan '%s')"
                         % (mode, needle, msg[:160]))
            print("DO (SAI)     %-10s -> %s" % (mode, msg[:170]))
        else:
            print("DO (dung)    %-10s %s -> %s" % (mode, link, msg[:120]))

    rc, msg = run("clean")
    if rc != 0:
        fails.append("clean: row bi DO khi khong cat gi")
        print("DO (SAI)     clean      -> %s" % msg[:200])
    else:
        print("XANH (dung)  clean      -> %s" % msg[-170:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
