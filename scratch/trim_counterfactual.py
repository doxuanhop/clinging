"""Phan chung cho dong selftest `the Cat in/out trong bang thuoc tinh`.

Dong nay noi: the "Cat" trong ClipPropertiesWidget doi in/out theo GIAY CUA
NGUON tren clip co toc do khac 1, giu meg ben kia khi cat, khong cho clip ve 0
giay, khong lo nguon truoc giay 0, ripple tren Main Storyline, mot lan doi so la
mot buoc undo, va an khi clip khong co cua so nguon. Muoi hai vet CU chen vao
hai file nguon THAT (ui/properties_panel.py, core/commands.py), moi vet chay
`python main.py --selftest <json>` THAT va doi dong do vi DUNG ly do cua no,
khong keo theo dong khac. Byte duoc khoi phuc trong finally, roi selftest lan
cuoi phai XANH 37 dong.

Vet CU + ly do mong doi:
  1. `in_min` bo phep nhan speed: tren clip 2x co in_point = 3,0s dat tai
     0,5s thi chan duoi sai thanh 2,5s, keo mat 0,5s nguon lech start_time.
     Mong do o "meg trai toi da tinh sai vi chia toc do".
  2. nhat In theo `from_start` bo chia speed: clip 2x cat 1 giay nguon mat 1
     giay thanh thay vi 0,5. Mong do o "cat dau khong giu meg phai".
  3. nhat Out bo chia speed: same sai so o phia mép phai. Mong do o "cat cuoi
     sai tren clip 2x".
  4. MIN_TRIM = 0.0: spin cho phep cat clip ve 0 giay. Mong do o "rong 0 giay".
  5. `_push_trim` goi thang model.resize_clip: thao tac nam ngoai UndoStack,
     Ctrl+Z mat net cat. Mong do o "(buoc 0)".
  6. chan lenh rong bi tai: mot nấc 0,01 s tren clip 4x tao buoc undo vo nghia.
     Mong do o "tao buoc undo gia".
  7. khong kiem playhead nam trong clip: bam nut khi playhead ngoai clip thi
     model kip duration ve 0,1 va an mat clip. Mong do o "ngoai clip ma van cat".
  8. `_has_source_window` cho ca clip chu: the hien tren clip khong co nguon,
     UI noi doi. Mong do o "hien cho clip chu".
  9. `_sync_trim_card` an the ngay khi clip co nguon: dong do "the Cat an khi
     clip co nguon that" — gate phai chet khi khong co gi de cat.
 10. `TrimClipCommand.execute` dat `_applied` vo dieu kien: tren track khoa lenh
     khong ap gi nhung undo van ghi nguoc hinh hoc.
 11. `TrimClipCommand._write` bo ripple: Ctrl+Z tren truc chinh de clip sau chim
     chong. Mong do o "khong tra lai ripple".
 12. `update_values` khong doc lai the: so tren spin lech model sau khi clip khac
     cat ripple. Mong do o "update_values khong doc lai the Cat".

Vet CU duoc ghi ra file that, nen mot lan bi cat giua chung (progress bo, may
tat) de lai file nguon dam loa. Moi vet copy ban goc sang `<file>.cfbak` TRUOC
khi chen, va lan chay sau khoi dong bang phuc lai moi `.cfbak` con sot roi xoa
chung — khong de lac ran trong repo.

```bash
python scratch/trim_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
Tham so cuoi dung khi lap lai tung vet (moi vet mot lan `--selftest` that); bo
trong thi chay het 12 vet.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "the Cat in/out trong bang thuoc tinh"

PANEL = os.path.join(ROOT, "ui", "properties_panel.py")
COMMANDS = os.path.join(ROOT, "core", "commands.py")

MUTATIONS = [
    ("in_min_khong_nhan_speed", PANEL,
     b"        in_min = max(0.0, float(clip.in_point)"
     b" - float(clip.start_time) * speed)\n",
     b"        in_min = max(0.0, float(clip.in_point)"
     b" - float(clip.start_time))  # CU\n",
     "meg trai toi da tinh sai vi chia toc do"),
    ("cat_dau_khong_chia_speed", PANEL,
     b"            delta = (target - float(clip.in_point)) / speed\n",
     b"            delta = target - float(clip.in_point)  # CU\n",
     "cat dau khong giu meg phai"),
    ("cat_cuoi_khong_chia_speed", PANEL,
     b"            new_duration = (target - float(clip.in_point)) / speed\n",
     b"            new_duration = target - float(clip.in_point)  # CU\n",
     "cat cuoi sai tren clip 2x"),
    ("min_trim_bang_0", PANEL,
     b"    MIN_TRIM = 0.1\n",
     b"    MIN_TRIM = 0.0  # CU\n",
     "spin cho phep clip rong 0 giay"),
    ("push_trim_bo_undo_stack", PANEL,
     b"        from core.commands import TrimClipCommand\n"
     b"        main_window.timeline_panel.undo_stack.push(\n"
     b"            TrimClipCommand(model, self.clip_id, new_duration,"
     b" from_start))\n",
     b"        model.resize_clip(self.clip_id, new_duration, from_start)"
     b"  # CU: ra ngoai UndoStack\n",
     "buoc 0"),
    ("khong_chan_lenh_rong", PANEL,
     b"        if abs(new_duration - float(clip.duration)) < 0.005:\n",
     b"        if False:  # CU: khong chan lenh rong\n",
     "tao buoc undo gia"),
    ("khong_kiem_playhead", PANEL,
     b"        if not (clip.start_time + self.MIN_TRIM < playhead\n"
     b"                < clip.end_time - self.MIN_TRIM):\n",
     b"        if False:  # CU: khong kiem playhead trong clip\n",
     "ngoai clip ma van cat"),
    ("cho_phep_clip_chu", PANEL,
     b'                    and clip.media_type in ("video", "audio")\n',
     b'                    and clip.media_type in ("video", "audio", "text")'
     b"  # CU\n",
     "hien cho clip chu"),
    ("the_bi_an_voi_clip_co_nguon", PANEL,
     b"        self.card_trim.setVisible(True)\n",
     b"        self.card_trim.setVisible(False)  # CU\n",
     "the Cat an khi clip co nguon that"),
    ("applied_vo_dieu_kien", COMMANDS,
     b"        self._applied = bool(after) and any(\n"
     b"            abs(old - new) > 0.0001 for old, new"
     b" in zip(self._before, after))\n",
     b"        self._applied = bool(after)  # CU\n",
     "bi tinh la da ap"),
    ("undo_khong_ripple", COMMANDS,
     b"        clip.out_point = out_point\n"
     b"        if track and track.is_main_track:\n",
     b"        clip.out_point = out_point\n"
     b"        if False and track and track.is_main_track:\n",
     "khong tra lai ripple"),
    ("update_values_khong_doc_the", PANEL,
     b"        self._sync_trim_card()\n"
     b"        self._sync_grading_card()\n",
     b"        self._sync_grading_card()\n",
     "update_values khong doc lai the Cat"),
]


def run_selftest(report):
    proc = subprocess.run([sys.executable, "main.py", "--selftest", report],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    with open(report, encoding="utf-8") as handle:
        payload = json.load(handle)
    row = next((r for r in payload["checks"] if r["name"] == ROW), None)
    return proc.returncode, payload, row


def restore_leftover_backups():
    """Lan chay truoc bi cat giua chung thi file nguon van dam loa. Phuc lai
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
    # `python scratch/trim_counterfactual.py 3 6` = vet thu 3..5 (moi vet mot lan
    # --selftest that, ~22 giay, nen chia bac duoc khi can).
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    subset = MUTATIONS[args[0]:args[1]] if args else MUTATIONS
    originals = {path: open(path, "rb").read()
                 for _, path, _, _, _ in subset}
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_trim_cf_%d.json" % os.getpid())
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
            detail = row["detail"] if row else "khong co row"
            others = [r["name"] for r in payload["checks"]
                      if not r["ok"] and r["name"] != ROW]
            red = (row is not None and not row["ok"] and expect in detail
                   and not others)
            results.append((name, red, rc, others, detail))
            print("%-32s %s  rc=%d  do vi: %s" %
                  (name, "PHAN BIET" if red else "KHONG PHAN BIET", rc,
                   detail[:110]))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)
        if os.path.exists(report):
            os.remove(report)

    rc, payload, row = run_selftest(report)
    green = rc == 0 and row is not None and row["ok"]
    if os.path.exists(report):
        os.remove(report)
    print("%-32s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    bad = sum(0 if r[1] else 1 for r in results)
    print("ALL PASS" if green and not bad else "CO %d KET QUA FAIL" % bad)
    return 0 if green and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
