"""Phan loai abort 0xC0000409 tren du an NANG sau khi them tran detach.

Ban cai 1.0.7 do `scratch/installed_app_probe.py` tra MOT FAIL:
`project THAT exit 0: got 3221226505 want 0` tren du an hai clip 4K 110 s,
trong khi cung cong do tren ban cai 1.0.6 (van `wait(5000)` roi `wait()` tran)
la XANH. Hai ban chi lech nhau o duong `EXTRACTION_SHUTDOWN_MS` +
`detach_running_thread()`, nen cau hoi duy nhat can tra loi:

    Co phai MOT THREAD BI DETACH CON SONG luc interpreter finalize gay ra?

Probe nay khong dung du an cua nguoi dung lam fixture. No tu sinh video 4K
dai (nhieu GOP, moi lan seek phai giai ma lai tu keyframe gan nhat) va lap
project HAI clip giong hinh dan cua du an that, roi do HAI CHIEU cua tran:

  * tran RAT LON (240000 ms): khong ai bi detach -> khong ai duoc cat som;
  * tran = 1 ms: moi thread deu bi detach lien tuc -> KY VONG ABORT tren ca
    project nhe (ma moi bang do khong bao gio vuot 8000 ms).

Ket luan probe rut ra tu so do: `nhe-1` abort trong khi `nhe-8000` va ca ba
lan do tren project 4K hai clip tu sinh deu rc=0 thi do dich thoi la MOT
THREAD BI DETACH VAN CON SONG luc interpreter finalize, con project nao bi
danh la "du nang" (don vi giai ma > 8000 ms) phai do tren du an cua nguoi dung
bang `scratch/installed_abort_repeat.py`.
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
CLIP_ITEM = os.path.join(ROOT, "ui", "graphics", "clip_item.py")
ABORT = 3221226505
CAP_NEEDLE = b"EXTRACTION_SHUTDOWN_MS = 8000\n"

WORK = os.path.join(tempfile.gettempdir(), "clinging_detach_cf")
HEAVY = os.path.join(WORK, "nguon-4k-dai.mp4")
LIGHT = os.path.join(WORK, "nguon-4k-ngan.mp4")
HEAVY_PROJECT = os.path.join(WORK, "Detach Heavy.clinq")
LIGHT_PROJECT = os.path.join(WORK, "Detach Light.clinq")
RESULT = os.path.join(ROOT, "scratch", "teardown_detach_heavy_probe.json")

HEAVY_SECONDS = 48.0
LIGHT_SECONDS = 6.0
CHILD_TIMEOUT = 600


def _true_rc(returncode):
    return returncode & 0xFFFFFFFF


def _guard_no_app_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Clinging.exe"],
                         capture_output=True, text=True).stdout
    if "Clinging.exe" in out:
        raise SystemExit("PROBE DUNG: dong Clinging.exe cua nguoi dung truoc khi do")


def _user_data_snapshot():
    home = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    paths = glob.glob(os.path.join(home, "Clinging_Projects", "*", "*.clinq"))
    paths.append(os.path.join(appdata, "Roaming", "Clinging", "recent_projects.json"))
    snap = {}
    for path in paths:
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                snap[path] = handle.read()
    return snap


def _user_data_restore(snap):
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


def _build(path, seconds):
    """Sinh video 4K nhieu GOP: -g 360 nen moi seek giai ma toi 360 khung hinh."""
    if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
        return
    os.makedirs(WORK, exist_ok=True)
    build = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=s=3840x2160:r=30:d=%g" % seconds, "-c:v", "libx264",
         "-preset", "ultrafast", "-crf", "40", "-g", "360", "-keyint_min", "360",
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True, timeout=1800)
    if build.returncode != 0 or not os.path.isfile(path):
        raise SystemExit("PROBE DUNG: ffmpeg khong sinh duoc %s: %s"
                         % (os.path.basename(path), build.stderr.strip()[:200]))


def _keyframes(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "frame=key_frame", "-of", "csv=p=0",
                          path], capture_output=True, text=True).stdout
    lines = [line.strip().rstrip(",") for line in out.splitlines() if line.strip()]
    return sum(1 for line in lines if line == "1"), len(lines)


def _project(path, source, seconds, clip_count):
    """Du an tro source TU SINH; clip_count = 2 tai phan nua timeline (dan clip)."""
    each = seconds / clip_count
    clips = []
    for index in range(clip_count):
        clips.append({
            "clip_id": "c-%d" % index,
            "timeline_in": round(index * each, 3),
            "timeline_out": round((index + 1) * each, 3),
            "duration": round(each, 3), "source_duration": round(each, 3),
            "asset_id": "a-4k", "source_path": source, "media_type": "video",
            "name": os.path.basename(source),
            "trim_in": round(index * each, 3),
            "trim_out": round((index + 1) * each, 3),
        })
    data = {
        "project_meta": {
            "project_id": "detach-%s" % os.path.basename(path)[:4].lower(),
            "project_name": os.path.splitext(os.path.basename(path))[0],
            "created_at": "2026-10-23T00:00:00",
            "last_modified": "2026-10-23T00:00:00",
            "resolution": {"width": 3840, "height": 2160}, "fps": 30,
            "aspect_ratio": "16:9", "version": "1.0",
        },
        "assets": {"a-4k": {"type": "video", "path": source,
                            "original_duration": seconds}},
        "timeline": {"duration": seconds, "playhead": 0.0, "tracks": [{
            "track_id": "t-main", "track_type": "VIDEO", "name": "Main",
            "z_index": 1, "is_main_track": True, "is_locked": False,
            "is_visible": True, "is_muted": False, "color": "#4FC3F7",
            "clips": clips}]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _set_cap(value, original):
    """Ghi tran moi len BAN GOC, khong len file dang mang tran cua phep truoc.

    Neu thay chuoi `= 8000` thi sau lan do tran 240000 khong con tim thay no nua,
    va phep do tiep theo chet giua chang.
    """
    with open(CLIP_ITEM, "wb") as handle:
        handle.write(original.replace(CAP_NEEDLE,
                                      b"EXTRACTION_SHUTDOWN_MS = %d\n" % value))


def _restore_cap(original):
    with open(CLIP_ITEM, "wb") as handle:
        handle.write(original)
    with open(CLIP_ITEM, "rb") as handle:
        return handle.read() == original


def _run_report(project, out_json, exe=None):
    """`<exe> --project-report <json> <du an>` THAT; do ca stderr.

    `exe=None` nghia la tree nguon (`python main.py`). Ban cai khong doc vet
    `EXTRACTION_SHUTDOWN_MS` cua tree nguon - no chay tran 8000 ms da dong goi,
    nen no la mau chung cho duong nguoi dung that.
    """
    for stale in (out_json, out_json[:-5] + ".png"):
        if os.path.isfile(stale):
            os.remove(stale)
    command = ([exe] if exe else [sys.executable, "-X", "utf8", "main.py"])
    command += ["--project-report", out_json, project]
    start = time.time()
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              timeout=CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, time.time() - start, ""
    elapsed = time.time() - start
    payload = None
    if os.path.isfile(out_json):
        try:
            with open(out_json, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            payload = None
    return _true_rc(proc.returncode), payload, elapsed, proc.stderr or ""


def _qthread_noise(stderr):
    """Dong Qt tu to khi thread bi huy luc van dang chay (khong phai loi Python)."""
    hits = [line.strip() for line in stderr.splitlines()
            if "QThread" in line or "Destroying" in line
            or "still running" in line]
    return hits[:4]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _guard_no_app_running()
    for tool in (FFMPEG, FFPROBE):
        if not os.path.isfile(tool):
            raise SystemExit("PROBE DUNG: thieu %s" % tool)

    _build(HEAVY, HEAVY_SECONDS)
    _build(LIGHT, LIGHT_SECONDS)
    heavy_key, heavy_frames = _keyframes(HEAVY)
    if heavy_key < 2:
        raise SystemExit("PROBE DUNG: fixture nang co %d keyframe/%d khung hinh, "
                         "seek se khong phai giai ma dai" % (heavy_key, heavy_frames))
    _project(HEAVY_PROJECT, HEAVY, HEAVY_SECONDS, 2)
    _project(LIGHT_PROJECT, LIGHT, LIGHT_SECONDS, 1)
    print("fixture nang: %d B, %d keyframe/%d khung hinh, 2 clip %.0f s"
          % (os.path.getsize(HEAVY), heavy_key, heavy_frames, HEAVY_SECONDS / 2))
    print("fixture nhe: %d B, 1 clip %.0f s"
          % (os.path.getsize(LIGHT), LIGHT_SECONDS))

    with open(CLIP_ITEM, "rb") as handle:
        cap_original = handle.read()
    if CAP_NEEDLE not in cap_original:
        raise SystemExit("PROBE DUNG: clip_item.py khong con day %r (ma nguon da doi, "
                         "probe phai doi theo)" % CAP_NEEDLE)

    snap = _user_data_snapshot()
    rows = []
    fails = []

    def record(name, project, cap, expect, exe=None):
        if exe is None:
            _set_cap(cap, cap_original)
        out_json = os.path.join(WORK, "report_%s.json" % name.replace(" ", "_"))
        rc, payload, elapsed, stderr = _run_report(project, out_json, exe)
        opened = bool(payload and payload.get("mo_duoc") and payload.get("o_editor"))
        noise = _qthread_noise(stderr)
        ok = (rc == (ABORT if expect == "abort" else 0))
        if not ok:
            fails.append(name)
        rows.append({"ten": name, "cap_ms": cap, "exe": exe or "tree nguon",
                    "ky_vong": expect, "rc": rc, "giay": round(elapsed, 1),
                    "mo_duoc": opened, "qthread": noise, "ok": ok})
        print("%-26s cap=%-7d rc=%-11d %5.1fs payload=%s %s  %s"
              % (name, cap, rc if rc is not None else -1, elapsed,
                 "du" if opened else "thieu",
                 "PASS" if ok else "FAIL", " | ".join(noise)[:120]))
        return rc

    try:
        # Ban cai 1.0.7 (tran 8000 ms da dong goi) tren du an nang - mau that
        # cua FAIL trong installed_app_probe, chay TRUOC moi vet de khong bi
        # nhiu cac lan do sau no.
        installed = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                                 "Clinging", "Clinging.exe")
        if os.path.isfile(installed):
            record("exe-cai-nang", HEAVY_PROJECT, 8000, "ok", exe=installed)
        # Chieu 1: tran san xuat tren du an nang tu sinh.
        record("nang-8000", HEAVY_PROJECT, 8000, "ok")
        # Chieu 2: tran khong dung ai - khong ai bi detach.
        record("nang-240000", HEAVY_PROJECT, 240000, "ok")
        # Chieu 3+4: cung project nhe, chi khac tran. Tran 1 ms ep MOI thread
        # bi detach ngay tuc thi - so do 23/10/2026 ra rc=0, nghia la MOT MINH
        # thread bi detach khong gay fastfail; abort tren may can mot dieu kien
        # nua chi co o du an nang cua nguoi dung (do lan do 1/4 o
        # `scratch/installed_abort_repeat.py`).
        record("nhe-8000", LIGHT_PROJECT, 8000, "ok")
        record("nhe-1", LIGHT_PROJECT, 1, "ok")
    finally:
        restored = _restore_cap(cap_original)
        touched = _user_data_restore(snap)
        print("khoi phuc clip_item.py nguyen byte: %s" % restored)
        print("du lieu nguoi dung bi cham: %d" % len(touched))

    with open(RESULT, "w", encoding="utf-8") as handle:
        json.dump({"fixture_nang": {"file": HEAVY, "keyframe": heavy_key,
                                    "frames": heavy_frames,
                                    "byte": os.path.getsize(HEAVY)},
                   "fixture_nhe": {"file": LIGHT,
                                   "byte": os.path.getsize(LIGHT)},
                   "rows": rows, "failed": fails,
                   "restored": restored, "user_touched": len(touched)},
                  handle, ensure_ascii=False, indent=2)

    if not restored or fails:
        print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
        return 1
    nang = {row["ten"]: row for row in rows}
    if nang["nhe-1"]["rc"] == ABORT:
        print("KET LUAN DOI HUONG: tran 1 ms (moi thread deu bi detach).da no rc=%d - "
              "bay gio detach DA du gay abort, khac voi so do 23/10/2026 (rc=0). "
              "Phai xem lai doan detach trong clip_item.py." % nang["nhe-1"]["rc"])
        return 1
    print("KET LUAN: detach mot minh KHONG gay abort (nhe-1 rc=%d cung cap voi "
          "nhe-8000 rc=%d); project 4K hai clip TU SINH khong vuot tran 8000 ms "
          "(nang-8000 rc=%d sau %.1fs, nang-240000 rc=%d sau %.1fs, exe cai rc=%d "
          "sau %.1fs)" % (nang["nhe-1"]["rc"], nang["nhe-8000"]["rc"],
                          nang["nang-8000"]["rc"], nang["nang-8000"]["giay"],
                          nang["nang-240000"]["rc"], nang["nang-240000"]["giay"],
                          nang["exe-cai-nang"]["rc"], nang["exe-cai-nang"]["giay"]))
    print("ALL PASS %d/%d" % (len(rows), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
