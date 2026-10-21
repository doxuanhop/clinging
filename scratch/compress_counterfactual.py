"""Phan chung cho dong selftest `nen toi uu tep video: moov + codec-hop-container`.

Dong nay noi: `remux` that su day moov len dau file, moi loi phai tra ve mot cau
TRUOC khi kip lay lenh ffmpeg chua chay, codec phai hop voi container o CA HAI
chieu (encoder do nguoi dung chon va codec cua nguon khi copy luong), thang tien
trinh doc duoc ca ba cach ffmpeg in moc thoi gian, va that bai / Huy khong de lai
file do. Muoi bay vet CU chen vao `core/media_compress.py` THAT — file ma hop
thoai nen goi truc tiep — moi vet chay `python main.py --selftest <json>` THAT
va doi DUNG dong do vi ly do cua chinh no, khong keo theo dong khac. Byte duoc
khoi phuc trong finally, roi lan chay cuoi phai XANH 38 dong.

Vet CU + ly do mong doi (nguyen van tu chi tiet cua dong):
  1. `remux_khong_movflags` — bo cờ +faststart trong lenh remux: moov van nam
     cuoi, nguoi dung tuong da toi uu.
  2. `encoder_present_luon_false` — doi chieu codec bat thanh `found = False`.
  3. `video_codec_khong_luu_vao_facts` — nguon khong con duoc do codec.
  4. `remux_khong_chan_container` — chan duoi `if True` o chieu codec cua NGUON.
  5. `is_faststart_dao_nguoc` — detector bao moov-dau cho mot file moov-cuoi,
     nen canary cua fixture nat truoc.
  6. `vp9_di_nhanh_preset` — `if mode == MODE_VP9` thanh `if False`: vp9 nhan
     `-preset`, ffmpeg bao "Invalid preset".
  7. `vp9_thieu_bv0` — bo `-b:v 0` khoi VP9_FLAGS.
  8. `webm_van_aac` — nhanh audio bo duoi `.webm`, sinh aac trong webm.
  9. `suggest_giu_duoi_nguon` — goi y file khong doi sang `.webm` cho vp9.
 10. `container_choices_tu_bang` — liet ke ca 5 duoi cho moi kieu.
 11. `build_command_khong_raise` — bo chan pair_error trong ham dung lenh.
 12. `crf_khong_chan` — bo min/max, CRF 99 thoat ra lenh that.
 13. `hevc_khong_tag_hvc1` — mp4 + x265 ma khong tag thi trinh phat khong mo.
 14. `progress_bo_out_time_ms` — ban ffmpeg cu in `out_time_ms` bi bo sot.
 15. `progress_bo_dinh_dang_hms` — ban cu nua in `out_time=HH:MM:SS.ms`.
 16. `khoi_xoa_file_do` — `_drop` tro thanh noi dung rong. Do o vet NAY la chan
     "Huy" (dòng `dung giua chung van con file do`), KHONG phai chan nguon rac:
     do 21/10/2026, ffmpeg fail truoc khi kip tao file cho mot doan van ban
     mang duoi .mp4, nen vet _drop khong the do o chan do.
 17. `remux_bao_ton_gio_ma_hoa` — uoc luong thoi gian tinh ca remux.

Vet CU duoc ghi ra file that, nen mot lan bi cat giua chung de lai file nguon
dam loa: moi vet copy ban goc sang `core/media_compress.py.cfbak` TRUOC khi chen,
va lan chay sau khoi dong bang phuc lai moi `.cfbak` con sot roi xoa chung.

```bash
python scratch/compress_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "nen toi uu tep video: moov + codec-hop-container"
CORE = os.path.join(ROOT, "core", "media_compress.py")

MUTATIONS = [
    ("remux_khong_movflags", CORE,
     b'            command += ["-map_metadata", "0", "-map_chapters", "0"]\n'
     b'            if extension in FASTSTART_CONTAINERS:\n'
     b'                command += ["-movflags", "+faststart"]\n',
     b'            command += ["-map_metadata", "0", "-map_chapters", "0"]\n',
     "remux xong ma moov van nam cuoi file"),
    ("encoder_present_luon_false", CORE,
     b"            if len(fields) >= 2 and fields[1] == name:\n"
     b"                found = True\n",
     b"            if len(fields) >= 2 and fields[1] == name:\n"
     b"                found = False  # CU\n",
     "ffmpeg cua bundle nay khong co libx264"),
    ("video_codec_khong_luu_vao_facts", CORE,
     b'    facts["video_codec"] = source_video_codec(path)\n',
     b"    pass  # CU: khong do codec nguon\n",
     "fixture khong phai h264"),
    ("remux_khong_chan_container", CORE,
     b"        if not source_codec or fits_container(source_codec, extension):\n",
     b"        if True:  # CU: chieu codec cua nguon khong bi chan\n",
     "remux video h264 ra webm khong bi chan"),
    ("is_faststart_dao_nguoc", CORE,
     b'    return positions["moov"] < positions["mdat"]\n',
     b'    return positions["moov"] > positions["mdat"]  # CU\n',
     "fixture da faststart san"),
    ("vp9_di_nhanh_preset", CORE,
     b"        if mode == MODE_VP9:\n",
     b"        if False:  # CU\n",
     "vp9 nhan -preset"),
    ("vp9_thieu_bv0", CORE,
     b'VP9_FLAGS = ("-b:v", "0", "-row-mt", "1")\n',
     b'VP9_FLAGS = ("-row-mt", "1")  # CU\n',
     "vp9 thieu -cpu-used hoac -b:v 0"),
    ("webm_van_aac", CORE,
     b'        if extension == ".webm":\n',
     b'        if False:  # CU: nhanh aac dung cho moi duoi\n',
     "webm ma mang aac"),
    ("suggest_giu_duoi_nguon", CORE,
     b'    extension = MODE_EXTENSION.get(mode) or _extension(source) or ".mp4"\n',
     b'    extension = _extension(source) or ".mp4"  # CU\n',
     "goi y file cho vp9 khong doi duoi .webm"),
    ("container_choices_tu_bang", CORE,
     b"    return sorted(ext for ext, tokens in CONTAINER_CODECS.items()\n"
     b"                  if not tokens or fits_container(name, ext))\n",
     b"    return sorted(CONTAINER_CODECS)  # CU: khong doi chieu codec\n",
     "bang container cua vp9 bi lech"),
    ("build_command_khong_raise", CORE,
     b"    incompatible = pair_error(output, mode)\n"
     b"    if incompatible:\n"
     b"        raise ValueError(incompatible)\n",
     b"    # CU: khong chan to hop codec/container\n",
     "build_command khong chan x264 trong webm"),
    ("crf_khong_chan", CORE,
     b'        command += ["-crf", str(min(CRF_MAX, max(CRF_MIN, chosen_crf))),\n',
     b'        command += ["-crf", str(chosen_crf),  # CU: khong chan\n',
     "CRF 99 khong bi chan ve CRF_MAX"),
    ("hevc_khong_tag_hvc1", CORE,
     b'            command += ["-tag:v", "hvc1"]\n',
     b'            pass  # CU: khong tag\n',
     "hevc trong mp4 thieu tag hvc1"),
    ("progress_bo_out_time_ms", CORE,
     b'    if line.startswith(("out_time_us=", "out_time_ms=")):\n',
     b'    if line.startswith("out_time_us="):  # CU\n',
     "khong doc duoc out_time_ms (ban cu)"),
    ("progress_bo_dinh_dang_hms", CORE,
     b'    if line.startswith("out_time="):\n',
     b'    if False:  # CU\n',
     "khong doc duoc out_time=HH:MM:SS"),
    ("khoi_xoa_file_do", CORE,
     b"def _drop(path):\n    try:\n        if os.path.isfile(path):\n"
     b"            os.unlink(path)\n    except OSError:\n        pass\n",
     b"def _drop(path):\n    return  # CU: giu lai file do\n",
     "dung giua chung van con file do"),
    ("remux_bao_ton_gio_ma_hoa", CORE,
     b"    if mode == MODE_REMUX:\n        return 0.0\n",
     b"    if mode == MODE_REMUX:\n        return float(duration or 0.0)\n",
     "remux duoc bao la ton thoi gian ma hoa"),
]


def run_selftest(report):
    if os.path.exists(report):
        os.remove(report)
    proc = subprocess.run([sys.executable, "main.py", "--selftest", report],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if not os.path.exists(report):
        return proc.returncode, None, None
    with open(report, encoding="utf-8") as handle:
        payload = json.load(handle)
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
                          "clinging_compress_cf_%d.json" % os.getpid())
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
                rc, payload, row = run_selftest(report)
            finally:
                with open(path, "wb") as handle:
                    handle.write(originals[path])
                if os.path.exists(path + ".cfbak"):
                    os.remove(path + ".cfbak")
            if payload is None:
                results.append((name, False, rc, [], "khong co bao cao"))
                print("%-32s KHONG PHAN BIET  rc=%d  tu child khong ghi bao cao"
                      % (name, rc))
                continue
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            results.append((name, red, rc, others, detail))
            print("%-32s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:120]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)

    rc, payload, row = run_selftest(report)
    green = (rc == 0 and row is not None and row["ok"] and payload is not None
             and not payload["failed"])
    if os.path.exists(report):
        os.remove(report)
    print("%-32s %s  rc=%d  rows=%s failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]) if payload else "?",
           payload["failed"] if payload else "?"))
    bad = [r[0] for r in results if not r[1]]
    print("ALL PASS" if green and not bad
          else "CO %d KET QUA FAIL: %s" % (len(bad), ", ".join(bad)))
    return 0 if green and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
