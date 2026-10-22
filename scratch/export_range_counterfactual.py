"""Phan chung cho dong selftest `vung xuat in/out + preset chat luong`.

Dong nay noi: `core/export_range.py` la TOAN quyet dinh cua so xuat (giay nao,
bao nhieu frame, bao nhieu byte), `RenderWorker` phai di qua no (co_names +
co_consts, khong grep), xuat toan bo phai GIU du doan cuoi khong tieng (bai hoc
`-shortest`), file vung phai la CAT cua file toan bo theo CHI SO frame, preset
CRF 24 phai nho hon CRF 18 cung noi dung, hai cua so co tieng (0->0,6 am,
0,6->1,2 tam) phai ra dung do dai va dung tieng, va ExportDialog phai cung mot
cua so voi worker + khong mo hop thoai luu file khi vung sai.

Muoi tam vet CU chen vao BA file nguon THAT. Moi vet chay that
`python main.py --selftest <json> --only=<dong do>` va doi dong do vi DUNG ly do
cua no; vet dau tien chay lai TREN TRON bang de chot rang no khong keo theo
dong khac. Byte duoc khoi phuc trong finally, roi selftest lan cuoi phai XANH
du so dong cua bang (so do tu lan chay tron, khong phai hang so nho).

 1. min_frames_bang_0            -> "vung 0,05 s phai bi tu che"
 2. span_tu_hai_so_nhap          -> "span khong sinh tu so khung hinh"
 3. kep_ve_khong_chan_duoi       -> "kep ve dau duoi" (khong phai "ngoai pham
    vi": nhanh RANGE_FULL reset start nen `clamped` khong nhin thay chan duoi)
 4. kep_ve_khong_chan_tren       -> "kep ve dau tren"
 5. che_do_toan_bo_tat           -> "vung toan bo bi nhan dien sai"
 6. frame_time_khong_dich        -> "khong phai frame cua toan bo"
 7. preset_la_de_thu_tu_cuoi     -> "preset la khong roi mac dinh CRF 18"
 8. audio_khong_con_ss           -> "vung khong cat audio bang -ss"
 9. worker_bo_audio_seek         -> "audio cua vung_cat khong duoc -ss cat theo"
    (`co_names` nhin thay `audio_input_args` qua duong mp3 sidecar NEN phep thu
    duy nhat la RMS: bo -ss o duong video thi doan tam tra ve tieng am)
10. worker_preset_co_dinh        -> "CRF 24 khong nho hon CRF 18"
11. worker_bo_do_dai             -> "vung dai 2.4" (audio duoi day keo file ra
    toi 2,4 s — dung cai cach `-shortest` tung an doan cuoi)
12. worker_shortest_quay_lai     -> "mang hang so '-shortest'"
13. hop_thoai_khong_qua_seam     -> "_current_window khong goi resolve_window"
14. hop_thoai_tu_tinh_span       -> "hop thoai do do dai bang hieu so nhap tay"
    (van goi seam nhung ghi de span: do la loi ma co_names khong bao gio thay)
15. do_dai_vung_in_mm_ss         -> "phai la con so giay + khung hinh"
    (vung 0,6 s la hop le ma nhan in ra "00:00" — loi nguoi dung nhin thay,
    khong phai loi toan; co_names khong nhin thay chuoi format)
16. bam_nut_khong_chan_vung_sai  -> "van mo hop thoai luu file"
17. fixture_hai_nua_giong_nhau   -> "hai nua nguon khong khac nhau"
18. fixture_khong_con_ramp       -> "audio cua vung_cat khong duoc -ss cat theo"
    (vet DO FIXTURE, khong do san pham: tat ramp 1,0 -> 0,02 thi hai cua so co
    tieng giong het nhau va phep thu RMS o vet 9 khong con phan biet duoc gi.
   vet 9 va 18 cung mot dong bao loi la CO Y: mot cua, hai duong.)
   Hai vet 17/18 nam trong `diagnostics.py` — do la cach duy nhat chung minh
   gate khong xanh vi le: xoa doi luong am cua fixture thi hai cua so tieng
   giong het nhau va phep thu RMS khong con noi duoc dieu gi ve san pham nua.

Vet CU duoc ghi ra file that, nen mot lan bi cat giua chung de lai file nguon
dam loa: moi vet copy ban goc sang `<file>.cfbak` TRUOC khi chen, va lan chay
sau khoi dong bang phuc lai moi `.cfbak` con sot roi xoa chung.

```bash
python scratch/export_range_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
Moi vet mot lan `--selftest` that (~12 s), nen chia bac duoc khi lap lai.
KHONG chay hai ban sao cua probe nay song song: chung ghi de byte len cung
ba file nguon.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "vung xuat in/out + preset chat luong"

RANGE = os.path.join(ROOT, "core", "export_range.py")
DLG = os.path.join(ROOT, "ui", "export_dialog.py")
DIAG = os.path.join(ROOT, "diagnostics.py")

MUTATIONS = [
    ("min_frames_bang_0", RANGE,
     b"MIN_WINDOW_FRAMES = 2\n",
     b"MIN_WINDOW_FRAMES = 0  # CU\n",
     "vung 0,05 s phai bi tu che"),
    ("span_tu_hai_so_nhap", RANGE,
     b"    span = frames / fps\n",
     b"    span = end - start  # CU: do bang so user nhap\n",
     "span khong sinh tu so khung hinh"),
    ("kep_ve_khong_chan_duoi", RANGE,
     b"    start = min(max(start, 0.0), duration)\n",
     b"    start = min(start, duration)  # CU: khong chan duoi 0\n",
     "kep ve dau duoi sinh ra"),
    ("kep_ve_khong_chan_tren", RANGE,
     b"    end = min(max(end, 0.0), duration)\n",
     b"    end = max(end, 0.0)  # CU: khong chan tren duration\n",
     "kep ve dau tren sinh ra"),
    ("che_do_toan_bo_tat", RANGE,
     b"    if start <= 0.0 and span >= duration - (1.0 / fps):\n",
     b"    if False:  # CU: khong nhan che do toan bo\n",
     "vung toan bo bi nhan dien sai"),
    ("frame_time_khong_dich", RANGE,
     b"    return float(start) + index / float(fps)\n",
     b"    return index / float(fps)  # CU: khong cong start\n",
     "khong phai frame cua toan bo"),
    ("preset_la_de_thu_tu_cuoi", RANGE,
     b"    return QUALITY_PRESETS[0]\n",
     b"    return QUALITY_PRESETS[-1]  # CU\n",
     "preset la khong roi mac dinh CRF 18"),
    ("audio_khong_con_ss", RANGE,
     b'        args += ["-ss", "%.6f" % window["start"]]\n',
     b'        args += ["-t", "%.6f" % window["start"]]  # CU\n',
     "vung khong cat audio bang -ss"),
    ("worker_bo_audio_seek", DLG,
     b"            cmd.extend(export_range.audio_input_args(window))\n",
     b"            cmd.extend([])  # CU: khong -ss cho audio\n",
     "audio cua vung_cat khong duoc -ss cat theo"),
    ("worker_preset_co_dinh", DLG,
     b"            cmd.extend(export_range.encode_args(self.quality))\n",
     b'            cmd.extend(export_range.encode_args("cao"))  # CU\n',
     "CRF 24 khong nho hon CRF 18"),
    ("worker_bo_do_dai", DLG,
     b"            cmd.extend(export_range.output_args(window))\n",
     b"            cmd.extend([])  # CU: khong -t\n",
     "do dai file ra khong phai do chinh export quyet"),
    ("worker_shortest_quay_lai", DLG,
     b"            cmd.extend(export_range.output_args(window))\n",
     b'            cmd.extend(export_range.output_args(window)'
     b' + ["-shortest"])  # CU\n',
     "mang hang so '-shortest'"),
    ("hop_thoai_khong_qua_seam", DLG,
     b"        if self._range_mode() == export_range.RANGE_WINDOW:\n"
     b"            return export_range.resolve_window(\n"
     b"                self.spin_from.value(), self.spin_to.value(), duration,\n"
     b"                self._current_fps())\n"
     b"        return export_range.resolve_window(0.0, duration, duration,\n"
     b"                                           self._current_fps())\n",
     b'        if self._range_mode() == export_range.RANGE_WINDOW:\n'
     b'            return {"ok": True,  # CU: ban phuc bac trong hop thoai\n'
     b'                    "mode": export_range.RANGE_WINDOW,\n'
     b'                    "start": self.spin_from.value(),\n'
     b'                    "span": self.spin_to.value()'
     b' - self.spin_from.value(),\n'
     b'                    "frames": 0}\n'
     b'        return {"ok": True, "mode": export_range.RANGE_FULL,\n'
     b'                "start": 0.0, "span": duration, "frames": 0}\n',
     "_current_window khong goi"),
    ("hop_thoai_tu_tinh_span", DLG,
     b"            return export_range.resolve_window(\n"
     b"                self.spin_from.value(), self.spin_to.value(), duration,\n"
     b"                self._current_fps())\n",
     b"            window = export_range.resolve_window(\n"
     b"                self.spin_from.value(), self.spin_to.value(), duration,\n"
     b"                self._current_fps())\n"
     b"            window[\"span\"] = (self.spin_to.value()\n"
     b"                                - self.spin_from.value())  # CU\n"
     b"            return window\n",
     "hop thoai do do dai bang hieu so nhap tay"),
    ("do_dai_vung_in_mm_ss", DLG,
     b'            do_dai = "%.2f s, %d frame" % (shown, window["frames"])\n',
     b"            do_dai = self._fmt_time(shown)  # CU: mm:ss an vung duoi 1s\n",
     "phai la con so"),
    ("bam_nut_khong_chan_vung_sai", DLG,
     b'        window = self._current_window()\n'
     b'        if not window.get("ok"):\n',
     b'        window = self._current_window()\n'
     b'        if False:  # CU: mo hop thoai luu du vung sai\n',
     "van mo hop thoai luu file"),
    ("fixture_hai_nua_giong_nhau", DIAG,
     b'"testsrc2=size=160x120:rate=25:duration=%g,hue=h=72+t*60"',
     b'"testsrc2=size=160x120:rate=25:duration=%g,hue=h=t*60"',
     "hai nua nguon khong khac nhau"),
    ("fixture_khong_con_ramp", DIAG,
     b"volume=volume='if(lt(t,%g),1.0,0.02)':eval=frame",
     b"volume=volume='if(lt(t,%g),1.0,1.0)':eval=frame",
     "audio cua vung_cat khong duoc -ss cat theo"),
]


def run_selftest(report, only=None):
    """Chạy `main.py --selftest` THAT, có hoặc không lọc lại đúng một dòng.

    `only=ROW` cắt 39 dòng xuống 1: 18 phép đổi byte mà mỗi phép chạy trọn bảng
    (~42 s, các dòng chroma/pop art/nén đều mã hoá thiệt) là hơn 9 phút ngán
    HDD. Vẫn đi qua đúng seam production — QApplication, boundary của bundle, rc
    của chính `main.py` — chứ không gọi thẳng hàm `_export_range_ok`.
    """
    if os.path.exists(report):
        os.remove(report)
    cmd = [sys.executable, "main.py", "--selftest", report]
    if only:
        cmd.append("--only=" + only)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
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
                          "clinging_export_range_cf_%d.json" % os.getpid())
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
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            results.append((name, red, rc, others, detail))
            print("%-30s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:120]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)
        if os.path.exists(report):
            os.remove(report)

    # Lan loc 14/14 noi duoc "do vi DUNG ly do cua no" nhung khong the noi
    # "khong keo theo dong khac". Mot vet do lai tren TRON bang de chot dieu do.
    spot_ok, nfull = False, 0
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
        nfull = len(s_payload["checks"]) if s_payload else 0
        s_failed = s_payload["failed"] if s_payload else []
        spot_ok = (s_rc == 1 and s_row is not None and not s_row["ok"]
                   and s_expect in s_row["detail"] and s_failed == [ROW]
                   and s_payload.get("only") is None)
        print("%-30s %s  rc=%d  rows=%d failed=%s  (vet %s, tron bang)" %
              ("spot_tron_bang", "PASS" if spot_ok else "FAIL", s_rc, nfull,
               s_failed, s_name))

    rc, payload, row = run_selftest(report)
    green = (rc == 0 and row is not None and row["ok"] and payload
             and not payload["failed"] and payload.get("only") is None
             and nfull and len(payload["checks"]) == nfull)
    if os.path.exists(report):
        os.remove(report)
    print("%-30s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    bad = [r[0] for r in results if not r[1]]
    if not spot_ok:
        bad.append("spot_tron_bang")
    print("ALL PASS" if green and not bad
          else "CO %d KET QUA FAIL: %s" % (len(bad), ", ".join(bad)))
    return 0 if green and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
