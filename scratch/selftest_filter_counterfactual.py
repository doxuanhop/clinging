"""Phan chung cho bo loc `--only=` cua `main.py --selftest` (diagnostics.py).

Bo loc nay sinh ra vi mot ly do do duoc: `compress_counterfactual.py` keu 17 lan
`--selftest` TRON 38 dong = ~20 phut ngan HDD va treo ca may. Cat con 1 dong thi
5,0 s/lan. Nhung no cung mo ra ba kieu gate gia ma chinh hop dong cua repo da
cam, nen ba vet CU duoc chen vao `diagnostics.py` THAT (file ma lenh production
doc), moi vet chay `python main.py --selftest <json> --only=...` THAT:

  1. `chi_de_dau_rong` — `_selftest_only` tra [] mon: `--only=` bi lang qua,
     bao cao van xanh nhung la 38 dong, khong phai 1 dong nhu probe tuong da
     chay. Do lan nay bang `compress_counterfactual.run_selftest` that: no PHAI
     noi "BUG: --only=... khong loc dung mot dong" chu khong duoc im lang.
  2. `xanh_vi_dau_vao_rong` — xoa canh `col.check("bo loc --only khong trach
     duong nao")`: bo loc khong trach duong nao thi `checks = []`, `failed = []`
     va rc = 0 — dung cai gate-xanh-vi-dau-vao-rong ma `agents.md` cam.
  3. `keu_loc_ma_chay_het` — bo `rows = selected`: payload van ghi
     `only=["..."]` (nên ben doc tuong la 1 dong) trong khi 38 dong that van
     chay. Day la vet nguy hiem nhat vi ca hai phia deu "dung".

Vet CU ghi byte that nen moi lan copy ban goc sang `diagnostics.py.cfbak` va
phuc lai bang byte trong finally; lan chay cuoi phai XANH du 38 dong va
`sha256[:16]` cua diagnostics.py khong doi.

```bash
python scratch/selftest_filter_counterfactual.py
```
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "diagnostics.py")
ORIGINAL = open(DIAG, "rb").read()
# Do tu payload lan dau, khong phai hang so tri nho: neu them/bot dong selftest
# thi probe nay do ra lech tu, khong im lang theo. Gan so that o main().
NFULL = 0

TOKEN_NEN = "nen toi uu tep"
ROW_NEN = "nen toi uu tep video: moov + codec-hop-container"
TOKEN_CAT = "the Cat"
ROW_CAT = "the Cat in/out trong bang thuoc tinh"
BOGUS = "khong_trach_duoc_dong_nao_dau"

MUTATIONS = {
    "chi_de_dau_rong": (
        b'    flag = "--only="\n'
        b'    return [a[len(flag):] for a in argv[1:] if a.startswith(flag)]\n',
        b'    return []  # CU: bo loc bi lang qua\n',
    ),
    "xanh_vi_dau_vao_rong": (
        b'            col.check("bo loc --only khong trach duong nao", '
        b'_nothing_selected)\n',
        b'            pass  # CU: loc rong thi im lang\n',
    ),
    "keu_loc_ma_chay_het": (
        b"        rows = selected\n",
        b"        pass  # CU: tinh selected ma khong dung\n",
    ),
}


def run_selftest(tokens=()):
    """Chay `main.py --selftest <json> [--only=...]` THAT, tra (rc, payload)."""
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_filter_cf_%d.json" % os.getpid())
    if os.path.exists(report):
        os.remove(report)
    cmd = [sys.executable, "main.py", "--selftest", report]
    cmd += ["--only=" + t for t in tokens]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if not os.path.exists(report):
        return proc.returncode, None
    with open(report, encoding="utf-8") as handle:
        payload = json.load(handle)
    os.remove(report)
    return proc.returncode, payload


def names(payload):
    return [r["name"] for r in (payload or {}).get("checks", [])]


def consumer_guard(token):
    """Gọi hàm giữ cửa THẬT của probe tiêu thụ: `compress_counterfactual.run_selftest`.

 Trả về chuỗi lý do nó từ chối chạy (hoặc "" nếu nó im lặng accepted) — vet
 `chi_de_dau_rong` va `keu_loc_ma_chay_het` chi an toàn nếu hàm này lên tiếng.
 """
    path = os.path.join(ROOT, "scratch", "compress_counterfactual.py")
    spec = importlib.util.spec_from_file_location("cf_probe_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_filter_cf_guard_%d.json" % os.getpid())
    try:
        mod.run_selftest(report, only=token)
    except SystemExit as exc:
        return str(exc)
    return ""


def mutate(name):
    needle, repl = MUTATIONS[name]
    if ORIGINAL.count(needle) != 1:
        raise SystemExit("BUG: vet %s xuat hien %d lan trong diagnostics.py, "
                         "can 1" % (name, ORIGINAL.count(needle)))
    shutil.copyfile(DIAG, DIAG + ".cfbak")
    with open(DIAG, "wb") as handle:
        handle.write(ORIGINAL.replace(needle, repl, 1))


def restore():
    with open(DIAG, "wb") as handle:
        handle.write(ORIGINAL)
    if os.path.exists(DIAG + ".cfbak"):
        os.remove(DIAG + ".cfbak")


class Table:
    def __init__(self):
        self.rows = []

    def add(self, label, ok, detail):
        self.rows.append((label, bool(ok)))
        print("%-30s %s  %s" % (label, "PHAN BIET" if ok else "KHONG PHAN BIET",
                                str(detail)[:150]))

    @property
    def bad(self):
        return [r[0] for r in self.rows if not r[1]]


def main():
    global NFULL
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sha = hashlib.sha256(ORIGINAL).hexdigest()[:16]
    t = Table()

    # ---- baseline: bo loc phai chay dung hop dong tren tree sạch ----------
    rc, full = run_selftest()
    NFULL = len(full["checks"]) if full else 0
    t.add("tron_khong_keu_only",
          rc == 0 and full and full["only"] is None
          and NFULL and not full["failed"],
          "rc=%d only=%r rows=%d failed=%s" % (rc, full and full["only"],
                                               NFULL, full and full["failed"]))

    rc, one = run_selftest([TOKEN_NEN])
    t.add("loc_dung_mot_dong",
          rc == 0 and one and one["only"] == [TOKEN_NEN]
          and names(one) == [ROW_NEN] and one["checks"][0]["ok"],
          "rc=%d only=%r rows=%s" % (rc, one and one["only"], names(one or {})))

    rc, two = run_selftest([TOKEN_NEN, TOKEN_CAT])
    t.add("loc_hai_token_or",
          rc == 0 and two and sorted(two["only"]) == sorted([TOKEN_NEN, TOKEN_CAT])
          and sorted(names(two)) == sorted([ROW_NEN, ROW_CAT]),
          "rc=%d only=%r rows=%d" % (rc, two and two["only"],
                                     len(two["checks"]) if two else -1))

    rc, dead = run_selftest([BOGUS])
    GUARD = "bo loc --only khong trach duong nao"
    t.add("loc_khong_trach_gi_do",
          rc == 1 and dead and dead["failed"] == [GUARD]
          and BOGUS in dead["checks"][0]["detail"]
          and ("%d dong tu" % NFULL) in dead["checks"][0]["detail"],
          "rc=%d failed=%s detail=%s" % (rc, dead and dead["failed"],
                                         dead and dead["checks"][0]["detail"]))

    # ---- vet 1: `--only` bi lang qua -> ben tieu thu PHAI noi "BUG" -------
    try:
        mutate("chi_de_dau_rong")
        rc, ignored = run_selftest([TOKEN_NEN])
        t.add("vet1_lang_bo-loc",
              rc == 0 and ignored and ignored["only"] is None
              and len(ignored["checks"]) == NFULL,
              "rc=%d only=%r rows=%d (token bi lang qua, khong co nao doi)"
              % (rc, ignored and ignored["only"],
                 len(ignored["checks"]) if ignored else -1))
        why = consumer_guard(TOKEN_NEN)
        t.add("vet1_bao_ve_bug", why.startswith("BUG: --only="),
              "compress_counterfactual.run_selftest tu choi: %s" % (why or "IM LANG"))
    finally:
        restore()

    # ---- vet 2: xoa canh -> loc rong van xanh -----------------------------
    try:
        mutate("xanh_vi_dau_vao_rong")
        rc, empty = run_selftest([BOGUS])
        t.add("vet2_xanh_dau_rong",
              rc == 0 and empty is not None and empty["checks"] == []
              and empty["failed"] == [],
              "rc=%d rows=%d failed=%s — day la gate gia ma hop dong cam"
              % (rc, len(empty["checks"]) if empty else -1,
                 empty and empty["failed"]))
    finally:
        restore()

    # ---- vet 3: bao "only" ma chay het 38 dong ---------------------------
    try:
        mutate("keu_loc_ma_chay_het")
        rc, lying = run_selftest([TOKEN_NEN])
        t.add("vet3_keu_loc_chay_het",
              rc == 0 and lying and lying["only"] == [TOKEN_NEN]
              and len(lying["checks"]) == NFULL,
              "rc=%d only=%r rows=%d (keu la loc, thuc te chay tron)"
              % (rc, lying and lying["only"],
                 len(lying["checks"]) if lying else -1))
        why = consumer_guard(TOKEN_NEN)
        t.add("vet3_bao_ve_bug", why.startswith("BUG: --only="),
              "compress_counterfactual.run_selftest tu choi: %s" % (why or "IM LANG"))
    finally:
        restore()

    # ---- khoi phuc: 38 dong xanh, byte nguyen ven ------------------------
    rc, back = run_selftest()
    green = (rc == 0 and back and not back["failed"] and back["only"] is None
             and len(back["checks"]) == NFULL)
    same = hashlib.sha256(open(DIAG, "rb").read()).hexdigest()[:16] == sha
    t.add("khoi_phuc_xanh", green and same,
          "rc=%d rows=%d failed=%s sha16=%s (can %s)"
          % (rc, len(back["checks"]) if back else -1, back and back["failed"],
             hashlib.sha256(open(DIAG, "rb").read()).hexdigest()[:16], sha))

    bad = t.bad
    print("ALL PASS" if not bad else "CO %d FAIL: %s" % (len(bad), ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
