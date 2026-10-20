#!/usr/bin/env python
"""Chay MOT lenh va in ra ma thoat THAT cua no, khong phai ma cua shell.

Ly do ton tai: Git Bash doi `0xC0000409` (Qt callback mang exception qua bien
C++, hoac teardown de window con song) thanh `rc=127`, va duong ong (`| tee`)
tra rc cua tien trinh cuoi. Probe trong repo nay in `ALL PASS` o cuoi stdout
trong khi process that da chet - nen rc phai doc tu chinh subprocess cua lenh ay.

    python .qoder/skills/gate-counterfactual-evidence/scripts/true_rc.py \
        python scratch/icon_name_audit.py
    python .qoder/skills/gate-counterfactual-evidence/scripts/true_rc.py \
        --tail 30 python main.py --selftest

Dong dau: rc thap phan + hex, y nghia neu ma da biet, va do dai stdout/stderr de
phat hien log bi an.
"""
import sys
import subprocess
import time

# Ma that bi hide sau khi Windows/Python convert thanh signed 32-bit.
KNOWN = {
    -1073740791: "0xC0000409 STATUS_STACK_BUFFER_OVERRUN (fastfail): loi bat qua "
                 "bien callback C++ cua Qt, hoac window con song luc teardown. "
                 "Git Bash bao 127.",
    -1073741819: "0xC0000005 access violation: thuong la QWidget/QPixmap touched "
                 "sau khi C++ object da bi huy.",
    127: "127 trong bash = da phong toan ma thoat that; doc lai dong nay bang "
         "subprocess.run truoc khi ket luan probe xanh.",
    2: "2 = thieu file/arg hoac SystemExit(2) tu chinh lenh.",
}


def main(argv):
    tail = 25
    if argv and argv[0] == "--tail":
        tail = int(argv[1])
        argv = argv[2:]
    if not argv:
        print("dung: true_rc.py [--tail N] <lenh> [arg...]")
        return 64
    started = time.time()
    try:
        run = subprocess.run(argv, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=1800)
    except FileNotFoundError:
        print("rc=NE KHONG TIM THAY: %r" % (argv[0],))
        return 127
    except subprocess.TimeoutExpired:
        print("rc=TIMEOUT sau 1800 s (probe treo? windowed build + exception "
              "khong bat = hop thu mo lien)")
        return 124
    secs = time.time() - started
    out, err = run.stdout or "", run.stderr or ""
    rc = run.returncode
    note = KNOWN.get(rc) or KNOWN.get(rc - 2 ** 32) or ""
    print("rc=%d (0x%08x)  elapsed=%.1fs  stdout=%d B  stderr=%d B"
          % (rc, rc & 0xFFFFFFFF, secs, len(out.encode()), len(err.encode())))
    if note:
        print("dich nghia: %s" % note)
    if not out.strip() and not err.strip():
        print("canh bao: khong mot dong ra nao.")
        print("  Neu lenh ghi bao ca ra file (main.py --selftest --report X.json) thi doc")
        print("  file ay de lay 'failed'. Nhung noi dung rong tu mot probe in-ra-man-hinh")
        print("  la mau do rong, khong phai PASS: gate phai in ra so do duoc.")
    body = (out + ("\n[stderr]\n" + err if err.strip() else "")).splitlines()
    if len(body) > tail:
        print("--- (%d dong, chi in %d dong cuoi) ---" % (len(body), tail))
        body = body[-tail:]
    else:
        print("--- output ---")
    for line in body:
        print("  " + line)
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
