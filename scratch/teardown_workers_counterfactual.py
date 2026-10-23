"""Phan chung cho phep dung luong giai ma clip luc dong cua so (1.0.6).

Cac phai do: `MainController.closeEvent` goi `shutdown_clip_workers()`, va vong
lap do goi `shutdown_extraction()` cua tung ClipItem. Bo MỘT trong hai dong do
thi app chet o 0xC0000409 (3221226505) luc interpreter thoat, khong lai mot dong
traceback nao — do la loi ban 1.0.6 mac phai khi `installed_app_probe.py` mo du
an 4K that cua nguoi dung (3/3 lan abort, payload van ghi xong).

Probe chay HAI thang do tren cung mot vet:
  * `main.py --selftest --only="dong cua so"` — do CAU TRUC (con thread nao sau
    close khong), xanh/do ngay lap tuc, chay duoc moi may;
  * `main.py --project-report <json> <du an 4K>` — do CHET THAT: ma thoat cua
    chinh lenh nguoi dung goi khi mo mot project nang.

Du an 4K do probe TU SINH bang bo ffmpeg dong goi (`testsrc2` 3840x2160, 12 s,
`-g 360 -sc_threshold 0` → ffprobe dem duoc DUNG MOT keyframe). Khong video nao
cua nguoi dung duoc dung: metadata `keyframe == 1` la cua phan chung — neu
fixture co nhieu keyframe thi moi luc seek la mot lan doc nho nhe, worker xong
trước khi cửa sổ đóng, và phép thử sẽ xanh mà không đo gì cả.

```bash
python scratch/teardown_workers_counterfactual.py
```
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg", "ffmpeg.exe")
FFPROBE = os.path.join(ROOT, "tools", "ffmpeg", "ffprobe.exe")
ABORT = 3221226505                      # 0xC0000409, fastfail khi Qt bi cut giua
ROW = "dong cua so: dung luong giai ma clip tru khi thoat"
ROW_ONLY = "dong cua so"
DETAIL = "van con luong"                # phan ket luan cua _clip_teardown_ok

WORK = os.path.join(tempfile.gettempdir(), "clinging_teardown_cf")
FIXTURE = os.path.join(WORK, "nguon-4k.mp4")
PROJECT = os.path.join(WORK, "Teardown 4K.clinq")
EVIDENCE_JSON = os.path.join(ROOT, "scratch", "teardown_workers_evidence.json")
EVIDENCE_PNG = EVIDENCE_JSON[:-5] + ".png"
RESULT = os.path.join(ROOT, "scratch", "teardown_workers_counterfactual.json")

MUTATIONS = [
    ("closeEvent_khong_goi_gi",
     os.path.join(ROOT, "ui", "main_controller.py"),
     b"            self.editor_page.timeline_panel.scene.shutdown_clip_workers()\n",
     b"            pass  # CU: closeEvent khong dung luong\n", DETAIL),
    ("vong_lap_khong_dung_ai",
     os.path.join(ROOT, "ui", "graphics", "timeline_scene.py"),
     b"        for item in list(self._clip_items.values()):\n"
     b"            item.shutdown_extraction()\n",
     b"        for item in list(self._clip_items.values()):\n"
     b"            pass  # CU: shutdown_clip_workers khong dung ai ca\n", DETAIL),
]


def _true_rc(returncode):
    """Ma that cua process, khong phai ma Git Bash in ra (no hien 127)."""
    return returncode & 0xFFFFFFFF


def _user_data_paths():
    home = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    paths = list(glob.glob(os.path.join(home, "Clinging_Projects", "*", "*.clinq")))
    paths.append(os.path.join(appdata, "Roaming", "Clinging", "recent_projects.json"))
    return [p for p in paths if os.path.isfile(p)]


def _user_data_snapshot():
    snap = {}
    for path in _user_data_paths():
        with open(path, "rb") as handle:
            snap[path] = handle.read()
    return snap


def _user_data_restore(snap):
    """Tra lai byte nguyen cho file bi chinh trong lan do. Tra so luong lech."""
    touched = []
    for path, data in snap.items():
        if not os.path.isfile(path):
            touched.append(path)
            continue
        with open(path, "rb") as handle:
            if handle.read() != data:
                touched.append(path)
                with open(path, "wb") as handle:
                    handle.write(data)
    return touched


def _guard_no_app_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Clinging.exe"],
                         capture_output=True, text=True).stdout
    if "Clinging.exe" in out:
        raise SystemExit("PROBE DUNG: dong Clinging.exe cua nguoi dung truoc khi do "
                         "(nhat la lan abort duoc lap lai)")


def _fixture():
    """Sinh video 4K MOT keyframe va du an .clinq tro vao no (khong dung cua nguoi dung)."""
    import shutil
    for tool in (FFMPEG, FFPROBE):
        if not os.path.isfile(tool):
            raise SystemExit("PROBE DUNG: thieu %s (repo moi phai tu dat bo ffmpeg)"
                             % tool)
    os.makedirs(WORK, exist_ok=True)
    rebuild = True
    if os.path.isfile(FIXTURE) and os.path.getsize(FIXTURE) > 1_000_000:
        rebuild = False
    else:
        shutil.rmtree(WORK, ignore_errors=True)
        os.makedirs(WORK, exist_ok=True)
    if rebuild:
        build = subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=s=3840x2160:r=30:d=12", "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "40", "-g", "360",
             "-keyint_min", "360", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
             FIXTURE], capture_output=True, text=True)
        if build.returncode != 0:
            raise SystemExit("ffmpeg khong sinh duoc fixture: %s"
                             % build.stderr.strip()[:200])
    frames = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=key_frame", "-of", "csv=p=0", FIXTURE],
        capture_output=True, text=True).stdout
    key = len([line for line in frames.splitlines() if line.strip() == "1,"])
    total = len([line for line in frames.splitlines() if line.strip()])
    if key != 1:
        raise SystemExit("PROBE DUNG: fixture co %d keyframe/%d khung hinh, moi "
                         "luc seek se re va khong con ai beat luc dong cua so"
                         % (key, total))
    data = {
        "project_meta": {
            "project_id": "teardown-4k", "project_name": "Teardown 4K",
            "created_at": "2026-10-23T00:00:00",
            "last_modified": "2026-10-23T00:00:00",
            "resolution": {"width": 3840, "height": 2160}, "fps": 30,
            "aspect_ratio": "16:9", "version": "1.0",
        },
        "assets": {"a-4k": {"type": "video", "path": FIXTURE,
                            "original_duration": 12.0}},
        "timeline": {
            "duration": 12.0, "playhead": 0.0,
            "tracks": [{
                "track_id": "t-main", "track_type": "VIDEO", "name": "Main",
                "z_index": 1, "is_main_track": True, "is_locked": False,
                "is_visible": True, "is_muted": False, "color": "#4FC3F7",
                "clips": [{
                    "clip_id": "c-4k", "timeline_in": 0.0, "timeline_out": 12.0,
                    "duration": 12.0, "source_duration": 12.0,
                    "asset_id": "a-4k", "source_path": FIXTURE,
                    "media_type": "video", "name": "nguon-4k.mp4",
                    "trim_in": 0.0, "trim_out": 12.0}],
            }],
        },
    }
    with open(PROJECT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return key, total


def _payload_of(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _run_row(report):
    """`main.py --selftest --only="dong cua so"` THAT; tra (rc, dong do)."""
    if os.path.exists(report):
        os.remove(report)
    proc = subprocess.run([sys.executable, "main.py", "--selftest", report,
                           "--only=" + ROW_ONLY], cwd=ROOT,
                          capture_output=True, text=True)
    payload = _payload_of(report) or {}
    if payload.get("only") != [ROW_ONLY] or len(payload.get("checks", [])) != 1:
        raise SystemExit("BUG: --only=%s khong loc dung mot dong (payload=%r)"
                         % (ROW_ONLY, {k: payload.get(k) for k in
                                       ("only", "failed")}))
    row = payload["checks"][0] if payload.get("checks") else None
    if os.path.exists(report):
        os.remove(report)
    return _true_rc(proc.returncode), row


def _run_report(out_json):
    """`main.py --project-report <json> <du an 4K>` THAT; tra (rc, payload, giay)."""
    for path in (out_json, out_json[:-5] + ".png"):
        if os.path.exists(path):
            os.remove(path)
    start = time.time()
    proc = subprocess.run([sys.executable, "-X", "utf8", "main.py",
                           "--project-report", out_json, PROJECT],
                          cwd=ROOT, capture_output=True, text=True, timeout=420)
    return _true_rc(proc.returncode), _payload_of(out_json), time.time() - start


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _guard_no_app_running()
    key, total = _fixture()
    print("fixture: %s (%d B, %d/%d khung hinh co keyframe)"
          % (os.path.basename(FIXTURE), os.path.getsize(FIXTURE), key, total))

    checks = []
    snap = _user_data_snapshot()
    originals = {}
    report = os.path.join(tempfile.gettempdir(), "clinging_teardown_row.json")

    def note(name, ok, detail):
        checks.append((name, ok))
        print("%-34s %s  %s" % (name, "PASS" if ok else "FAIL", detail))

    try:
        for path in (MUTATIONS[0][1], MUTATIONS[1][1]):
            with open(path, "rb") as handle:
                originals[path] = handle.read()

        # 1) baseline: hai thang do PHAI xanh tru khi vet, neu khong thi probe
        #    do mot loi da co tu truoc, khong do phep dung nay.
        rc, row = _run_row(report)
        note("baseline_selftest_row", rc == 0 and row and row["ok"],
             "rc=%d row=%s" % (rc, (row or {}).get("detail", "khong co row")))
        rc, payload, secs = _run_report(EVIDENCE_JSON)
        alive = payload or {}
        note("baseline_project_report",
             rc == 0 and alive.get("mo_duoc") is True
             and alive.get("o_editor") is True,
             "rc=%d %.1fs mo_duoc=%s o_editor=%s cache_extra=%s"
             % (rc, secs, alive.get("mo_duoc"), alive.get("o_editor"),
               alive.get("user_cache_extra")))

        # 2) tung vet: chay HAI lan de lo phien ban may tinh co luc rong.
        for index, (name, target, needle, repl, expect) in enumerate(MUTATIONS):
            original = originals[target]
            if original.count(needle) != 1:
                note(name + "_vet", False,
                     "vet xuat hien %d lan, can 1" % original.count(needle))
                continue
            for attempt in (1, 2):
                with open(target, "wb") as handle:
                    handle.write(original.replace(needle, repl, 1))
                rc, row = _run_row(report)
                detail = (row or {}).get("detail", "khong co row")
                red_row = (row is not None and not row["ok"]
                           and expect in str(detail))
                note("%s_selftest_vet%d" % (name, attempt), red_row,
                     "rc=%d do vi: %s" % (rc, str(detail)[:120]))
                prod = EVIDENCE_JSON[:-5] + "_vet%d.json" % attempt
                rc, payload, secs = _run_report(prod)
                body = payload or {}
                # Abort o exit ma payload van day du: chung toi chet vi Qt bi
                # cat, khong phai vi khong mo duoc du an.
                red_exit = (rc == ABORT and body.get("mo_duoc") is True
                            and body.get("o_editor") is True)
                note("%s_project_rc_vet%d" % (name, attempt), red_exit,
                     "rc=%d (muon %d) %.1fs mo_duoc=%s o_editor=%s"
                     % (rc, ABORT, secs, body.get("mo_duoc"),
                        body.get("o_editor")))
                for path in (prod, prod[:-5] + ".png"):
                    if os.path.exists(path):
                        os.remove(path)
                with open(target, "wb") as handle:
                    handle.write(original)
                if index == 0 and attempt == 1:
                    # Spot check xen ke: byte nguyen thi lai phai xanh.
                    rc, row = _run_row(report)
                    note("spot_sau_vet1", rc == 0 and row and row["ok"],
                         "rc=%d row=%s" % (rc, (row or {}).get("detail", "")))

        # 3) khoi phuc: bang tron 44 dong phai xanh, neu khong probe de lai nguon hong.
        proc = subprocess.run([sys.executable, "-X", "utf8", "main.py",
                               "--selftest", report], cwd=ROOT,
                              capture_output=True, text=True, timeout=420)
        payload = _payload_of(report) or {}
        green_all = (_true_rc(proc.returncode) == 0
                     and payload.get("only") in (None, [])
                     and payload.get("failed") == []
                     and len(payload.get("checks", [])) >= 44)
        note("bang_tron_xanh_sau_khoi_phuc", green_all,
             "rc=%d rows=%s failed=%s only=%r"
             % (_true_rc(proc.returncode), len(payload.get("checks", [])),
                payload.get("failed"), payload.get("only")))
        for path in (MUTATIONS[0][1], MUTATIONS[1][1]):
            with open(path, "rb") as handle:
                note("byte_nguyen_%s" % os.path.basename(path),
                     handle.read() == originals[path], "so byte voi ban goc")
    finally:
        if os.path.exists(report):
            os.remove(report)
        touched = _user_data_restore(snap)
        note("du_lieu_nguoi_dung_khong_doi", not touched,
             "%d file lech byte" % len(touched))
        note("anh_chung_minh_ton_tai",
             os.path.isfile(EVIDENCE_JSON) and os.path.isfile(EVIDENCE_PNG),
             EVIDENCE_PNG)
        with open(RESULT, "w", encoding="utf-8") as handle:
            json.dump({"fixture": {"path": FIXTURE, "keyframes": key,
                                   "frames": total},
                       "abort_code": ABORT,
                       "checks": [{"name": n, "ok": bool(o)} for n, o in checks],
                       "evidence_png": EVIDENCE_PNG},
                      handle, ensure_ascii=False, indent=2)

    failed = [n for n, ok in checks if not ok]
    print("%s" % ("ALL PASS %d/%d" % (len(checks), len(checks)) if not failed
                  else "CO %d KET QUA FAIL: %s" % (len(failed), ", ".join(failed))))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
