"""Phan chung cho dong selftest `tach tieng video thanh clip audio rieng`.

Dong nay noi: tach tieng mot clip video ra clip AUDIO trung nguon, trung noi dung
(start/in/duration/speed/volume/fade), xuong hang audio co tieng, khong con bị
export doc hai lan, va Ctrl+Z tra lai DUNG mot buoc cho ca hai nua dong thoi gi
lại hàng audio trống người dùng đã tạo. Mot phien ban CU xanh thi gate vo nghia,
nen probe chen 10 vet CU vao 4 file nguon THAT (core/timeline_model.py,
core/commands.py, ui/graphics/clip_item.py, ui/timeline_panel.py), chay
`python main.py --selftest <json> --only=<dong do>` THAT, va doi row tach tieng
do vi DUNG ly do cua phien ban ay; vet dau tien chay lai TREN TRON bang de chot
rang no khong keo theo dong khac. Byte duoc khoi phuc trong finally, roi
selftest lan cuoi phai XANH du so dong cua bang (so lay tu lan chay tron).

Sau phien ban CU va ly do mong doi:
  1. `place_clip(..., clip.start_time + 0.5)`: tieng tach ro lech nua giay so voi
     hinh. Mong do o "lech start_time".
  2. bo `clip.audio_muted = True`: video van con tieng sau khi tach, export doc
     hai lan cung mot nguon. Mong do o "hai nua cua thao tac khong doi trang thai".
  3. `if clip.audio_muted and False`: tach duoc tieng cua clip dang tat tieng, tao
     them mot hang rang. Mong do o "tach duoc tieng cua clip dang tat tieng".
  4. `audio.media_type = "video"`: `place_clip` tu choi dat clip khong phai audio
     len hang audio, nen detach_tra ve None — khong co clip audio nao ra doi.
     Mong do o "khong co dung 1 clip audio".
  5. `audio.source_path = ""`: clip tach ro tro ve khong, export se mo file rong.
     Mong do o "clip tach sai loai hoac sai nguon".
  6. `_detachable_audio_clip` tra `True` mon: muc menu moc ca khi clip da im
     lang, bam vao khong co gi xay ra. Mong do o "menu hien khi".
  7. `undo()` khong ghi lai `audio_muted`: Ctrl+Z chi xoa clip audio, video van
     im lang. Mong do o "Ctrl+Z chi tra lai mot nua thao tac".
  8. `_restore_track` tom tat `state = None`: remove_clip tu xoa hang vua trong,
     nguoi dung mat hang audio trong cua minh. Mong do o "lam mat hang audio".
  9. panel goi thang `model.detach_audio`: thao tac ra ngoai UndoStack nen khong
     con buoc hoàn tác. Mong do o "panel khong push DetachAudioCommand".
  10. xoa khoa "detach_audio" khoi bang phan phoi menu: muc menu hien len nhưng
     khong noi vao signal nao. Mong do o "khong goi audio_detach_requested".

Vet CU duoc ghi ra file that, nen mot lan bi cut giua chung (progress bo, may
tat) de lai file nguon dam loa. Vi vay moi vet copy ban goc sang `<file>.cfbak`
TRUOC khi chen, va lan chay sau khoi dong bang cach phuc lai moi `.cfbak` con sot
roi xoa chung — khong de lac ran trong repo.

```bash
python scratch/detach_audio_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
Tham so cuoi dung khi lap lai tung vet (moi vet mot lan `--selftest` that, chay
ca 10 vet mat ~35 phut); bo trong thi chay het.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "tach tieng video thanh clip audio rieng"

MODEL = os.path.join(ROOT, "core", "timeline_model.py")
COMMANDS = os.path.join(ROOT, "core", "commands.py")
CLIP_ITEM = os.path.join(ROOT, "ui", "graphics", "clip_item.py")
PANEL = os.path.join(ROOT, "ui", "timeline_panel.py")

MUTATIONS = [
    ("tieng_lech_hinh_nua_giay", MODEL,
     b"placed = self.place_clip(audio, target.track_id, clip.start_time)\n",
     b"placed = self.place_clip(audio, target.track_id,\n"
     b"                             clip.start_time + 0.5)  # CU\n",
     "lech start_time"),
    ("video_van_con_tieng_sau_khi_tach", MODEL,
     b"        clip.audio_muted = True\n"
     b"        self.clipUpdated.emit(clip.clip_id)\n",
     b"        self.clipUpdated.emit(clip.clip_id)\n",
     "hai nua cua thao tac khong doi trang thai"),
    ("tach_ca_clip_dang_tat_tieng", MODEL,
     b"        if clip.audio_muted:\n            return None\n",
     b"        if clip.audio_muted and False:\n            return None\n",
     "tach duoc tieng cua clip dang tat tieng"),
    ("clip_tach_khong_phai_audio", MODEL,
     b'        audio.media_type = "audio"\n',
     b'        audio.media_type = "video"  # CU\n',
     "khong co dung 1 clip audio"),
    ("clip_tach_khong_con_nguon", MODEL,
     b'        audio.media_type = "audio"\n',
     b'        audio.media_type = "audio"\n        audio.source_path = ""  # CU\n',
     "clip tach sai loai hoac sai nguon"),
    ("menu_moc_len_voi_moi_clip", CLIP_ITEM,
     b'        return bool(clip.media_type == "video" and clip.source_path\n'
     b"                    and not clip.audio_muted\n"
     b"                    and os.path.exists(clip.source_path))\n",
     b"        return True  # CU: muc menu moc len voi moi clip\n",
     "menu hien khi"),
    ("undo_khong_bat_lai_tieng", COMMANDS,
     b"            clip.audio_muted = self._was_muted\n"
     b"            self._model.clipUpdated.emit(self._source_id)\n",
     b"            pass  # CU: undo khong bat lai tieng\n",
     "Ctrl+Z chi tra lai mot nua thao tac"),
    ("undo_mat_hang_audio_trong", COMMANDS,
     b"        state = self._track_state\n",
     b"        state = None  # CU: khong dung lai hang da bi xoa\n",
     "lam mat hang audio"),
    ("panel_khong_push_lenh_undo", PANEL,
     b"        self.undo_stack.push(DetachAudioCommand(self.model, clip_id))\n",
     b"        self.model.detach_audio(clip_id)  # CU: ra ngoai UndoStack\n",
     "panel khong push DetachAudioCommand"),
    ("menu_khong_noi_vao_signal", CLIP_ITEM,
     b'            "detach_audio": "audio_detach_requested",\n',
     b"",
     "khong goi audio_detach_requested"),
]


def run_selftest(report, only=None):
    """Chạy `main.py --selftest` THAT, có hoặc không lọc lại đúng một dòng.

    `only=ROW` cắt trọn bảng xuống 1 dòng: do 22/10/2026, 10 phép đổi byte mà mỗi
    phép chạy trọn bảng (31 s, mấy dòng karaoke/pop art/chroma/nén đều mã hoá
    thiệt) là ~5 phút ngán HDD. Vẫn đi qua đúng seam production — QApplication,
    boundary của bundle, rc của chính `main.py` — chứ không gọi thẳng hàm `_ok`.
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
        # Lan chay loc PHAI la lan loc: dung mot dong va dung dong dang do. Neu
        # `--only` bi lang qua thi `failed=[]` mang nghia khac hon nghia probe
        # nay dung den. Bo loc co gate rieng (selftest_filter_counterfactual.py).
        names = [r["name"] for r in payload["checks"]]
        if payload.get("only") != [only] or names != [ROW]:
            raise SystemExit("BUG: --only=%s khong loc dung mot dong (only=%r, "
                             "checks=%r)" % (only, payload.get("only"), names))
    row = next((r for r in payload["checks"] if r["name"] == ROW), None)
    return proc.returncode, payload, row


def restore_leftover_backups():
    """Lan chay truoc bi cut giua chung thi file nguon van dam loa. Phuc lai
    bang `*.cfbak` con sot va bao ra stdout de khong ai tuong probe xanh."""
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
    # `python scratch/detach_audio_counterfactual.py 3 6` = vet thu 3..5 (moi
    # vet chi chay lai DONG dang do qua `--only`, nen chia bac van re (5 s).
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    subset = MUTATIONS[args[0]:args[1]] if args else MUTATIONS
    originals = {path: open(path, "rb").read()
                 for _, path, _, _, _ in subset}
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_detach_cf_%d.json" % os.getpid())
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
            print("%-34s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:110]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)
        if os.path.exists(report):
            os.remove(report)

    # Lan loc 10/10 noi duoc "do vi DUNG ly do cua no" nhung KHONG the noi
    # "khong keo theo dong khac", vi 37 dong kia khong chay. Vet dau tien do lai
    # tren TRON bang de chot dieu do — mot lan chay tron, thay vi 10 lan.
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
        print("%-34s %s  rc=%d  rows=%d failed=%s  (vet %s, tron bang)" %
              ("spot_tron_bang", "PASS" if spot_ok else "FAIL", s_rc, nfull,
               s_failed, s_name))

    rc, payload, row = run_selftest(report)
    green = (rc == 0 and row is not None and row["ok"] and payload
             and not payload["failed"] and payload.get("only") is None
             and nfull and len(payload["checks"]) == nfull)
    if os.path.exists(report):
        os.remove(report)
    print("%-34s %s  rc=%d  rows=%d failed=%s" %
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
