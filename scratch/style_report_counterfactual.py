"""Phan chung cho gate UI cua ban cai: --style-report.

Moi khop cat mot process con rieng (bao cao nay mo MainWindow that, va mot
process chet giua chung kho phan biet voi loi cua probe). Parent khong sua file
nao — moi loi chi song trong bo nho cua con.

Do la bat buoc, nhung do SAI LY DO cung tinh la hong: so ca ma loi lan doan
thong bao, de "the aura khong vao model" khong an may do o mot gate khac.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_style_report_cf_child.py")

# (mode, khop bi cat, doan chung minh do dung gate)
CASES = [
    ("dyn_rect",        "boundingRect khong doi theo hieu ung", "rect_doi_theo_hieu_ung"),
    ("no_reserve",      "phai giu cho aura loang ngoai khung",   "khong_giu_cho_loang"),
    ("fat_shape",       "vung loang khong duoc bat chuot",       "vung_loang_bat_chuot"),
    ("dead_card",       "bam the phai di vao model",             "khong co aura"),
    ("same_aura",       "moi the ghi dung aura cua no",          "aura_du_8_khoa"),
    ("two_undo",        "dong hop thoai = dung 1 muc undo",      "dong_1_muc_undo"),
    ("karaoke_dead",    "duong ve dung kieu karaoke",            "karaoke_doi_khung"),
    ("flame_blob",      "tu dang hat kieu lua con la chu",       "tu_dang_hat_bi_lap_lo"),
    ("flame_no_halo",   "bo het Quang thi cung hong",            "khong_con_quang_lua"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(mode):
    proc = subprocess.run([sys.executable, "-u", CHILD, mode],
                          capture_output=True, text=True, timeout=1500,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
    lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    # Doan can so PHAI la toan bo stderr: shiboken in them "Signal source has
    # been deleted" SAU traceback luc dong cua, nen bat dong cuoi se trach
    # dung doan nhieu.
    return proc.returncode, (proc.stderr or "").strip(), (lines[-1] if lines else "")


def main():
    fails = []
    only = set(sys.argv[1:])
    for mode, gate, needle in CASES:
        if only and mode not in only:
            continue
        rc, err, tail = run(mode)
        if rc == 0:
            fails.append("%s: cat '%s' ma bao cao van xanh" % (mode, gate))
            print("XANH (SAI)   %-15s %s" % (mode, gate))
        elif needle.lower() not in err.lower():
            fails.append("%s: do sai gate (mong '%s', nhan '%s')"
                         % (mode, needle, tail[:160]))
            print("DO (SAI)     %-15s -> %s" % (mode, tail[:170]))
        else:
            print("DO (dung)    %-15s %s" % (mode, gate))

    rc, err, tail = run("clean")
    if rc != 0:
        fails.append("clean: bao cao bi do khi khong cat gi")
        print("DO (SAI)     clean           -> %s" % tail[:200])
    else:
        print("XANH (dung)  clean           -> %s" % tail[-160:])

    print("rc %d%s" % (1 if fails else 0, (" " + repr(fails)) if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
