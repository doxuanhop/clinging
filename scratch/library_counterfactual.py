"""Phan chung cho cua `--library-report` va dong selftest "thu vien tai nguyen".

Nguoi dung bao "van lag voi may cau hinh thap" (22/10/2026). Tra loi bang cach
dat them sau lop toi uu len `ui/library_panel.py` thi phai co hai thu:

  1. Thang do PHAI do vi dung ly do. `--library-report` in ra 13 cua co ten
     (`diagnostics.LIBRARY_REPORT_CHECKS`); phan A duoi day vet tung dau vao
     tren payload THAT do chinh lenh chay ra (`scratch/_lib_report.json`) va
     doi DUNG ten cua no nup len, khong term nao lang cung. 19 phep vet tren
     13 dieu kien, cong mot bo vet ket hop phai do du 13 ten.
  2. Thang do do duoc loi THAT trong product, khong chi do khi ta sua payload.
     Phan B doi byte nguon `ui/library_panel.py` (tat tung lop toi uu), chay
     LAI hai lenh ma nguoi dung/dev chay (`main.py --library-report` va
     `main.py --selftest --only="thu vien tai nguyen"`) roi yeu cau do dung
     cua da dinh + dong selftest do dung cu. Nam vet doi byte, ~2,5 phut
     tren may yen; may dang mo ung dung khac thi no khong do gate, no chi
     keo dai (do 22/10: mot vet >900 s vi contention HDD).

Nhung phep do cua phan B mat ~16 s/moi lan vi no phai dung fixture video tren
%TEMP% va mo that MainWindow — do la gia cua cong production, khong cat ngan.

Toan bo viec doi byte nam trong `main()` duoi canh `__main__`, con lai chi la
hang so: `scratch/needle_canary.py` import file nay de dem mau byte, ma import
mot probe doi byte la pha nguon nguoi dung (hop dong cua canary: KHONG doi byte
nao).

Chay:  python -u scratch/library_counterfactual.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PANEL = os.path.join(ROOT, "ui", "library_panel.py")
PAYLOAD = os.path.join(ROOT, "scratch", "_lib_report.json")
ROW_ONLY = "thu vien tai nguyen"

import diagnostics as doc
library_report_fails = doc.library_report_fails

results = []


def check(name, got, want):
    results.append((name, got == want, got, want))


# ── A. Vet tung dau vao tren payload that ─────────────────────────────────
# (ten vet, {key: gia tri vet}, nhung cua PHAI do)
VETS = [
    ("thieu the khi nap", {"cards_loaded": 64}, ["luoi da nap du the"]),
    ("moi the mot luot doi luoi (O(n^2))", {"filter_passes_restore": 65},
     ["luoi xay dung 1 lan moi luot"]),
    ("an nhat 17,43 ms/the (so cu truoc toi uu)",
     {"block_ms_per_card": 17.43}, ["an nhat moi the duoi 8 ms"]),
    ("an nhat bang 0 (luoi khong chay)", {"block_ms_per_card": 0.0},
     ["an nhat moi the duoi 8 ms"]),
    ("the bi an van giai ma", {"hidden_image_decodes": 3},
     ["the bi an khong giai ma"]),
    ("the bi an van giao anh", {"hidden_image_delivered": 3},
     ["the bi an khong giai ma"]),
    ("tab Anh chi ve 2/3 anh", {"images_delivered": 2},
     ["the hien van giao anh du"]),
    ("video tab dau tien ve thieu", {"videos_delivered_p1": 61},
     ["the hien van giao anh du"]),
    ("anh tinh giu nguyen 1600 px", {"image_thumb_width": 1600},
     ["anh nho anh tinh duoi 320 px"]),
    ("anh tinh khong ghi duoc cache", {"image_key_after_first": False},
     ["anh nho anh tinh co cache dia"]),
    ("lan doc hai khong doc tu cache", {"image_second_cached": False},
     ["anh nho anh tinh co cache dia"]),
    ("mot phim 9,94 ms (con sot ban o luoi)",
     {"keystroke_median_ms": 9.94}, ["go tim kiem median duoi 8 ms"]),
    ("20/20 task cua dot da xoa van chay", {"decodes_for_cleared": 20},
     ["the da xoa khong giai ma them"]),
    ("batch huy do dai khong dung fixture", {"tasks_requested": 19},
     ["the da xoa khong giai ma them"]),
    ("3 lan emit qua bien C++", {"emit_errors": 3},
     ["khong loi emit qua bien C++"]),
    ("redirect khong ghi lan nao", {"redirect_image_files": 0},
     ["fixture ghi THAT o redirect"]),
    ("probe sang ghi cache nguoi dung", {"user_cache_changed": True},
     ["khong ghi vao cache nguoi dung"]),
    ("manh thu vien chi mot mau", {"distinct_colors": 1},
     ["anh thu vien ve co that"]),
    ("anh chung minh khong ton tai",
     {"screenshot": os.path.join(ROOT, "scratch", "khong_ton_tai_lib.png")},
     ["anh thu vien ve co that"]),
]

# ── B. Vet tren nguon that, qua hai lenh production ───────────────────────
# (ten vet, mau cu the thay, thay bang gi, cua CAU TRUC phai do, doan loi selftest)
# HOP DONG: vet chi duoc do bang nhung cua DEM (so lan, kich thuoc, co flag) —
# khong do bang cua ms. Ly do do ngay tren may nay: CUNG mot vet "cat guard dot
# nap", `block_ms_per_card` la 17,43 ms lan chay thu nhat va 6,1 ms lan chay thu
# hai, vi HDD 5400 rpm chia voi ung dung khac; con `filter_passes_restore` thi
# 66 ca hai lan. Hai cua ms ("an nhat moi the duoi 8 ms", "go tim kiem median
# duoi 8 ms") van duoc in ra bang so de doc, khong nam trong doi mong cua vet.
#
# So do duoc giung lai tu lan chay may yen 22/10/2026:
#   baseline  : passes=1, block/the=3,09-3,87 ms, median phim 1,4 ms,
#               decodes_for_cleared=3..7, anh tinh 320 px
#   V1        : passes=66, decodes_for_cleared=19  (moi the mot luot xay luoi,
#               nen dot 20 the kip giai ma xong truoc khi `clear` dat `cancelled`)
#   V2        : image_thumb_width=1600
#   V3        : decodes_for_cleared=20
#   V4        : hidden_image_decodes=3, decodes_for_cleared=20 va
#               images_delivered=0 vi the da co task tu luc __init__ nen
#               `request_thumbnail()` o lan mo tab Anh la khong (no tung chay
#               mot lan) — ba cua cung mot co che "xin giai ma som".
#   V5        : khong do cua cau truc nao; median phim 8,64-9,94 ms vuot nguong
#               8 ms la du, va chung cu dem duoc la dong selftest
#               "N lan ban lai o cu khi bo loc khong doi".
MUTATIONS = [
    ("cat guard dot nap: moi the lai xay lai luoi",
     b"        if not self._batch_depth:\n",
     b"        if True:\n",
     ["luoi xay dung 1 lan moi luot", "the da xoa khong giai ma them"],
     ["luot doi luoi"]),
    ("tat thu nho anh tinh luc doc",
     b"    if size.width() > max_width:\n",
     b"    if False and size.width() > max_width:\n",
     ["anh nho anh tinh duoi 320 px"], [">320 px"]),
    ("tat cau dao huy task cua the da xoa",
     b"            self._thumb_task.cancelled = True\n",
     b"            self._thumb_task.cancelled = False\n",
     ["the da xoa khong giai ma them"], ["khong bi cat dien"]),
    ("the bi an van xin giai ma (hoi ban cu)",
     b"        set_label_icon(self.thumb_container,\n",
     b"        self.request_thumbnail()\n"
     b"        set_label_icon(self.thumb_container,\n",
     ["the bi an khong giai ma", "the da xoa khong giai ma them",
      "the hien van giao anh du"],
     ["the anh bi an van co task"]),
    ("ban lai moi o luoi bat ke o cu",
     b'            if getattr(widget, "_grid_cell", None) != (r, c):\n',
     b"            if True:\n",
     [], ["lan ban lai o cu"]),
]

TIMING_CHECKS = {"an nhat moi the duoi 8 ms", "go tim kiem median duoi 8 ms"}

# `--library-report` sinh `.png` ngay canh `.json` (`diagnostics.py`:
# `shot = report[:-5] + ".png"`), nen hai duong dan tam phai nam trong MOT thu
# muc tam — de trong scratch/ thi moi lan vet de lai `_lib_vet.png` ric, dung
# rang buoc "loai bo rac" cua repo.
WORKDIR = tempfile.mkdtemp(prefix="clinging_libcf_")
VET_JSON = os.path.join(WORKDIR, "_lib_vet.json")
ROW_JSON = os.path.join(WORKDIR, "_lib_vet_row.json")
METRICS = ("filter_passes_restore", "block_ms_per_card", "keystroke_median_ms",
           "decodes_for_cleared", "hidden_image_decodes", "image_thumb_width")

# Cho `scratch/needle_canary.py`: vet 5 phan tu (ten, old, new, cua, tu) va mau
# luon xuat hien DUNG MOT lan trong TARGET.
TARGET = PANEL
REQUIRED_COUNT = 1


def run(cmd, report_path):
    try:
        proc = subprocess.run([sys.executable, "-u"] + cmd, cwd=ROOT,
                              capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        # Lan chay 22/10/2026: vet thu nam keo dai >900 s khi `Clinging.exe`
        # cua nguoi dung dang mo (528 MB, media tren cung HDD) — cung vet do chay
        # tren may yen tra ket qua trong 13 s. Day la contention, khong phai cong
        # do, nen bao ro may yen chu khong bao "gate do".
        raise SystemExit("PROBE DUNG: %s khong tra ve trong 300 s — may dang "
                         "chay don cong viec khac (ung dung/multi-probe). "
                         "Dong het roi chay lai." % (" ".join(cmd),))
    payload = {}
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    return proc.returncode, payload, proc.stderr.decode("utf-8", "replace")


def vet_run(tag):
    """Chay ca hai lenh production va lay do/loi cua tung lenh."""
    rc_rep, rep, _err = run(["main.py", "--library-report", VET_JSON], VET_JSON)
    rc_row, row_payload, _ = run(["main.py", "--selftest", ROW_JSON,
                                  "--only=%s" % ROW_ONLY], ROW_JSON)
    fails = sorted(rep.get("failed", []))
    row_msg = "; ".join(r.get("detail", "") for r in row_payload.get("checks", [])
                        if not r.get("ok")) or str(row_payload.get("failed", ""))
    numbers = ", ".join("%s=%s" % (m, rep.get(m)) for m in METRICS)
    print("  [%s] rc=%d do=%d | %s" % (tag[:40], rc_rep, len(fails), numbers))
    sys.stdout.flush()
    return rc_rep, fails, rc_row, row_msg, tag


def restore(original):
    with open(PANEL, "wb") as handle:
        handle.write(original)
    return open(PANEL, "rb").read() == original


def main():
    if not os.path.isfile(PAYLOAD):
        raise SystemExit("Thieu payload that: chay `python -u main.py "
                         "--library-report scratch/_lib_report.json` truoc.")
    with open(PAYLOAD, encoding="utf-8") as handle:
        real = json.load(handle)
    if real.get("failed"):
        raise SystemExit("Payload baseline dang DO: %r — sua xong roi moi "
                         "phan chung." % (real["failed"],))

    for name, patch, expected in VETS:
        mutant = dict(real)
        mutant.update(patch)
        check("vet payload: %s" % name, sorted(library_report_fails(mutant)),
              sorted(expected))

    all_patch = {}
    for _n, patch, _e in VETS:
        all_patch.update(patch)
    combo = dict(real)
    combo.update(all_patch)
    covered = {exp for _n, _p, exps in VETS for exp in exps}
    check("bo vet ket hop do tron bo 13 cua",
          sorted(set(library_report_fails(combo))),
          sorted(n for n, _f in doc.LIBRARY_REPORT_CHECKS))
    check("moi cua co vet cua no",
          sorted(covered), sorted(n for n, _f in doc.LIBRARY_REPORT_CHECKS))
    check("baseline payload khong do dieu kien nao",
          library_report_fails(real), [])

    original = open(PANEL, "rb").read()
    if b"\r\n" in original:
        raise SystemExit("ui/library_panel.py dang CRLF — phan chung noi mau "
                         "LF, phai doi ve LF truoc khi vet.")

    try:
        rc_rep, fails, rc_row, row_msg, _ = vet_run("baseline")
        check("baseline: --library-report rc=0", rc_rep, 0)
        check("baseline: --library-report khong cua nao do", fails, [])
        check("baseline: dong selftest rc=0", rc_row, 0)
        if rc_row != 0:
            print("      baseline row loi: %r" % (row_msg,))

        for name, old, new, want_checks, want_words in MUTATIONS:
            if original.count(old) != REQUIRED_COUNT:
                raise SystemExit("Mau vet khong du %d lan: %r"
                                 % (REQUIRED_COUNT, old,))
            with open(PANEL, "wb") as handle:
                handle.write(original.replace(old, new, REQUIRED_COUNT))
            try:
                rc_rep, fails, rc_row, row_msg, _ = vet_run(name)
                structural = sorted(f for f in fails if f not in TIMING_CHECKS)
                timing = sorted(f for f in fails if f in TIMING_CHECKS)
                check("vet nguon do dung cua cau truc: %s" % name, structural,
                      sorted(want_checks))
                if want_checks:
                    check("vet nguon rc=1: %s" % name, rc_rep, 1)
                check("dong selftest do vi vet nay: %s" % name, rc_row, 1)
                hit = [w for w in want_words if w in str(row_msg)]
                check("selftest do dung cu: %s" % name,
                      len(hit) == len(want_words), True)
                if len(hit) != len(want_words):
                    print("      row noi: %r" % (str(row_msg)[:300],))
                if timing:
                    print("      (cua ms cung do: %s — khong tinh, xem hop "
                          "dong do dem)" % ", ".join(timing))
            finally:
                if not restore(original):
                    raise SystemExit("Khong phuc hoi duoc ui/library_panel.py!")
    finally:
        restore(original)
        shutil.rmtree(WORKDIR, ignore_errors=True)
        # `ignore_errors=True` tung "thanh cong" gia tren may nay (bẫy rmtree
        # trong docs/verification-gates.md): phai DO que tam con tren dia hay
        # khong, khong duoc in mot roi bo qua.
        check("thu muc tam cua probe bi xoa het", os.path.exists(WORKDIR), False)

    print("== phan chung cua --library-report + dong selftest thu vien ==")
    bad = [row for row in results if not row[1]]
    for name, ok, got, want in results:
        print("  %-62s %s" % (name[:62], "PASS" if ok else "FAIL"))
        if not ok:
            print("      got  %r" % (got,))
            print("      want %r" % (want,))
    print("\n%s  (%d/%d)" % ("ALL PASS" if not bad else "FAILED (%d)" % len(bad),
                             len(results) - len(bad), len(results)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
