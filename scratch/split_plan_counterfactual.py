"""Phan chung cho ba kieu cat: deu nhau / doi dai co dinh / moc tu dat.

Dong selftest `cat file thanh N doan ra dia` noi: ca ba kieu cat deu ra file
THAT tren dia, tong do dai khong an va khong doi noi dung, cac mei cat bang 0,
va moc nguoi dung nhap duoc DUNG (khong phai bo roi chia deu). Muoi bon vet CU
chen vao `core/media_splitter.py` THAT — file ma hop thoai cat goi truc tiep —
moi vet chay `python main.py --selftest <json> --only=<dong do>` THAT va doi
DUNG dong do vi ly do cua chinh no, khong keo theo dong khac. Byte duoc khoi
phuc trong finally, roi lan chay cuoi phai XANH du 38 dong.

Vet CU + ly do mong doi (nguyen van tu chi tiet cua dong):
  1. `points_khong_bao_gio_thang` — `build_boundaries` bo nhanh `points`: nguoi
     dung dat 6 moc, app van chia deu 3 doan.
  2. `length_khong_bao_gio_thang` — bo nhanh `length`: "moi doan 2,95s" bi doi
     thanh chia deu.
  3. `moc_khong_loai_moc_sat_nhau` — hai moc cach nhau 0,1s con nguyen: doan
     0,1s ra file khong ai xem.
  4. `moc_khong_gop_du_duoi` — moc 5,95s tren nguon 6s thanh doan 0,05s.
  5. `moc_khong_chan_mep_tren` — moc 99s tren nguon 6s duoc giu: ke hoach
     khong tang dan, doan cuoi am.
  6. `moc_khong_keo_mep_cuoi` — bien cuoi khong duoc append: 1,6s duoi tran
     bi an.
  7. `doi_dai_khong_gop_du` — doan du 0,1s van thanh mot file rieng.
  8. `doi_dai_khong_keo_mep_cuoi` — bien cat dung o 5,9s, 0,1s cuoi mat.
  9. `moc_boi_deu_thanh_chia_deu` — tra dung SO doan (4) nhung sai NOI DUNG:
     chi co assertions "khong deu nhau" moi phat hien, dem doan khong the.
 10. `deu_khong_dem_dung_doan` — vong lap sinh bien cat bi ep xuống 1.
 11. `timecode_cong_phut_thay_nhan_60` — "1:02" thanh 3,0s thay vi 62s: moc
     ngoai khoang tột biến vao giua file va cat sai noi dung.
 12. `timecode_khong_doc_dau_hai_cham` — `raw.split(":")` thanh `split(".")`:
     moi moc deu doc khong ra, ke hoach con 1 doan.
 13. `moc_sai_khong_bao_ve` — `bad.append(token)` bi xoa: nguoi dung nhap "abc"
     thi app im lang, so doan tu doi ma khong hieu vi sao.
 14. `makedirs_khong_tao_thu_muc` — ffmpeg ghi vao thu muc chua ton tai.

Vet CU duoc ghi ra file that, nen mot lan bi cat giua chung de lai file nguon
dam loa: moi vet copy ban goc sang `core/media_splitter.py.cfbak` TRUOC khi
chen, va lan chay sau khoi dong bang phuc lai moi `.cfbak` con sot roi xoa chung.

```bash
python scratch/split_plan_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "cat file thanh N doan ra dia"
CORE = os.path.join(ROOT, "core", "media_splitter.py")

MUTATIONS = [
    ("points_khong_bao_gio_thang", CORE,
     b"    if points is not None:\n"
     b"        return plan_boundaries_points(total_seconds, points, start, end)\n",
     b"    if False:  # CU\n        pass\n",
     "kieu moc cat sai"),
    ("length_khong_bao_gio_thang", CORE,
     b"    if length:\n"
     b"        return plan_boundaries_length(total_seconds, length, start, end)\n",
     b"    if False:  # CU\n        pass\n",
     "kieu doi dai cat sai"),
    ("moc_khong_loai_moc_sat_nhau", CORE,
     b"        if value - kept[-1] < MIN_SEGMENT_SECONDS:\n"
     b"            continue\n",
     b"        # CU: hai moc sat nhau van du giu\n",
     "kieu moc cat sai"),
    ("moc_khong_gop_du_duoi", CORE,
     b"    if len(kept) > 1 and stop - kept[-1] < MIN_SEGMENT_SECONDS:\n"
     b"        kept.pop()\n",
     b"    # CU: du 0,05 s van thanh mot doan\n",
     "kieu moc cat sai"),
    ("moc_khong_chan_mep_tren", CORE,
     b"        if value <= begin or value >= stop:\n",
     b"        if value <= begin:  # CU: mep tren thoat\n",
     "kieu moc cat sai"),
    ("moc_khong_keo_mep_cuoi", CORE,
     b"    kept.append(round(stop, 3))\n    return kept\n",
     b"    return kept  # CU: khong keo ve met\n",
     "kieu moc cat sai"),
    ("doi_dai_khong_gop_du", CORE,
     b"    if len(points) > 2 and stop - points[-2] < MIN_SEGMENT_SECONDS:\n"
     b"        points.pop(-2)\n",
     b"    # CU: du 0,1 s van thanh mot file\n",
     "kieu doi dai cat sai"),
    ("doi_dai_khong_keo_mep_cuoi", CORE,
     b"    points = [round(begin + i * step, 3) for i in range(wanted)]\n"
     b"    points.append(round(stop, 3))\n"
     b"    if len(points) > 2 and stop - points[-2] < MIN_SEGMENT_SECONDS:\n",
     b"    points = [round(begin + i * step, 3) for i in range(wanted)]\n"
     b"    if len(points) > 2 and stop - points[-2] < MIN_SEGMENT_SECONDS:\n",
     "kieu doi dai an/doi noi dung"),
    ("moc_boi_deu_thanh_chia_deu", CORE,
     b"        return plan_boundaries_points(total_seconds, points, start, end)\n",
     b"        return plan_boundaries(total_seconds, 4, start, end)  # CU\n",
     "kieu moc cho ra chia deu"),
    ("deu_khong_dem_dung_doan", CORE,
     b"    step = (stop - begin) / wanted\n"
     b"    points = [round(begin + i * step, 3) for i in range(wanted)]\n",
     b"    step = (stop - begin) / wanted\n"
     b"    points = [round(begin + i * step, 3) for i in range(1)]  # CU\n",
     "kieu deu cat sai"),
    ("timecode_cong_phut_thay_nhan_60", CORE,
     b"    seconds = 0.0\n    for value in values:\n"
     b"        seconds = seconds * 60.0 + value\n",
     b"    seconds = 0.0\n    for value in values:\n"
     b"        seconds = seconds + value  # CU\n",
     "kieu moc cat sai"),
    ("timecode_khong_doc_dau_hai_cham", CORE,
     b'    parts = raw.split(":")\n',
     b'    parts = raw.split(".")  # CU\n',
     "kieu moc cat sai"),
    ("moc_sai_khong_bao_ve", CORE,
     b"            bad.append(token)\n",
     b"            pass  # CU: im lang bo qua token sai\n",
     "moc sai khong duoc bao ve"),
    ("makedirs_khong_tao_thu_muc", CORE,
     b"    os.makedirs(output_dir, exist_ok=True)\n",
     b"    pass  # CU: khong tao thu muc\n",
     "kieu deu cat sai"),
]


def run_selftest(report, only=None):
    """Chạy `main.py --selftest` THAT, co hoac khong loc mot dong.

    `only=ROW` cat 38 dong con 1 dong (~5,4 s/lan do 22/10/2026): 14 vet keu
    nhau thanh ~76 s thay vi ~13 phut. Van di qua dung seam production
    (QApplication, ffmpeg cua PATH, rc cua chinh `main.py`), khong phai goi
    truc tiep `_media_split_ok`.
    """
    if os.path.exists(report):
        os.remove(report)
    cmd = [sys.executable, "main.py", "--selftest", report]
    if only:
        cmd.append("--only=" + only)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if not os.path.exists(report):
        return proc.returncode, None, None
    with open(report, encoding="utf-8") as handle:
        payload = json.load(handle)
    if only:
        names = [r["name"] for r in payload["checks"]]
        if payload.get("only") != [only] or names != [ROW]:
            raise SystemExit("BUG: --only=%s khong loc dung mot dong (only=%r, "
                             "checks=%r)" % (only, payload.get("only"), names))
    row = next((r for r in payload["checks"] if r["name"] == ROW), None)
    return proc.returncode, payload, row


def restore_leftover_backups():
    restored = []
    for _, path, _, _, _ in MUTATIONS:
        bak = path + ".cfbak"
        if os.path.exists(bak):
            with open(bak, "rb") as handle:
                data = handle.read()
            with open(path, "wb") as handle:
                handle.write(data)
            os.remove(bak)
            restored.append(os.path.relpath(path, ROOT))
    return restored


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    for name in restore_leftover_backups():
        print("phuc lai %s tu .cfbak (lan chay truoc bi cat giua chung)" % name)
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    subset = MUTATIONS[args[0]:args[1]] if args else MUTATIONS
    originals = {path: open(path, "rb").read()
                 for _, path, _, _, _ in subset}
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_split_plan_cf_%d.json" % os.getpid())
    results = []
    try:
        for name, path, needle, repl, expect in subset:
            if originals[path].count(needle) != 1:
                print("BUG: vet cua %s xuat hien %d lan trong %s, can 1" %
                      (name, originals[path].count(needle),
                       os.path.relpath(path, ROOT)))
                return 2
            shutil.copyfile(path, path + ".cfbak")
            with open(path, "wb") as handle:
                handle.write(originals[path].replace(needle, repl, 1))
            try:
                rc, payload, row = run_selftest(report, only=ROW)
            finally:
                with open(path, "wb") as handle:
                    handle.write(originals[path])
                if os.path.exists(path + ".cfbak"):
                    os.remove(path + ".cfbak")
            if payload is None:
                results.append((name, False, rc, [], "khong co bao cao"))
                print("%-34s KHONG PHAN BIET  rc=%d  tu child khong ghi bao cao"
                      % (name, rc))
                continue
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            results.append((name, red, rc, others, detail))
            print("%-34s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:110]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)

    # Lan loc khong the noi "khong keo theo dong khac" vi 37 dong kia khong
    # chay. Mot vet do lai TREN TRON 38 dong de chot dieu do.
    spot_ok = True
    if subset:
        s_name, s_path, s_needle, s_repl, s_expect = subset[0]
        shutil.copyfile(s_path, s_path + ".cfbak")
        try:
            with open(s_path, "wb") as handle:
                handle.write(originals[s_path].replace(s_needle, s_repl, 1))
            s_rc, s_payload, s_row = run_selftest(report)
        finally:
            with open(s_path, "wb") as handle:
                handle.write(originals[s_path])
            if os.path.exists(s_path + ".cfbak"):
                os.remove(s_path + ".cfbak")
        s_failed = s_payload["failed"] if s_payload else ["khong co bao cao"]
        spot_ok = (s_payload is not None and s_rc == 1
                   and s_row is not None and not s_row["ok"]
                   and s_expect in s_row["detail"] and s_failed == [ROW]
                   and s_payload.get("only") is None)
        print("%-34s %s  rc=%d  rows=%d failed=%s  (vet %s, tron 38 dong)" %
              ("spot_tron_38_dong", "PASS" if spot_ok else "FAIL", s_rc,
               len(s_payload["checks"]) if s_payload else "?", s_failed, s_name))

    rc, payload, row = run_selftest(report)
    green = (rc == 0 and row is not None and row["ok"] and payload is not None
             and not payload["failed"] and payload.get("only") is None
             and len(payload["checks"]) == 38)
    if os.path.exists(report):
        os.remove(report)
    print("%-34s %s  rc=%d  rows=%s failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]) if payload else "?",
           payload["failed"] if payload else "?"))
    bad = [r[0] for r in results if not r[1]]
    if not spot_ok:
        bad.append("spot_tron_38_dong")
    print("ALL PASS" if green and spot_ok and not bad
          else "CO %d KET QUA FAIL: %s" % (len(bad), ", ".join(bad)))
    return 0 if green and spot_ok and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
