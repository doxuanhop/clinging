"""Do "mo app lau bao nhieu lau va ngot bao nhieu RAM" tren may nay, ca hai dau:

  * ben NGOAI: bat Clinging.exe nhu nguoi dung bam shortcut, do tu luc spawn
    den khi cua so "Clinging - Video Editor" that su hien len, dong thoi lay
    mau RSS doc duoc. So nay tinh ca bootloader cua PyInstaller — phan ma
    `main._T0` khong the thay.
  * ben TRONG: Clinging.exe --startup-report, do tung pha cua duong boot that.

Mode:
    python scratch/startup_ram_probe.py external [ten-json]
        chi do ben ngoai dung exe da cai (dung duoc ca khi exe chua co flag).
    python scratch/startup_ram_probe.py all
        hai lan chay exe that: mot lan ep kho bia (cold), mot lan doc lai
        (warm), roi so voi duong ma ban cu doi ly.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import time

REPO = r"D:\Programming\clinging"
EXE = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\doxuanhop\AppData\Local"),
                   "Programs", "Clinging", "Clinging.exe")
TITLE = "Clinging - Video Editor"
PYTHON = sys.executable

user32 = ctypes.windll.user32
FindWindowW = user32.FindWindowW
IsWindowVisible = user32.IsWindowVisible
PostMessageW = user32.PostMessageW
WM_CLOSE = 0x0010


def cover_cache_dir():
    out = subprocess.run(
        [PYTHON, "-c", "import sys; sys.path.insert(0, %r); "
                       "from core import media_cache; print(media_cache.cache_root())" % REPO],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    return out.stdout.strip().splitlines()[-1]


def measure_external(run_ms=9000, label=""):
    """Spawn -> cua so dau tien lo ra, va peak RSS cua ca qua trinh do."""
    assert not FindWindowW(None, TITLE), "da co cua so Clinging mo san, dong no truoc khi do"
    started = time.perf_counter()
    proc = subprocess.Popen([EXE], cwd=os.path.dirname(EXE))
    window_at = None
    peak_rss_kib = 0
    try:
        import psutil
        ps = psutil.Process(proc.pid)
        has_ps = True
    except Exception:
        ps, has_ps = None, False
    deadline = started + run_ms / 1000.0
    while time.perf_counter() < deadline:
        if window_at is None and FindWindowW(None, TITLE) and IsWindowVisible(
                FindWindowW(None, TITLE)):
            window_at = time.perf_counter() - started
        if has_ps:
            try:
                peak_rss_kib = max(peak_rss_kib, ps.memory_info().rss // 1024)
            except Exception:
                pass
        if window_at is not None and time.perf_counter() - started > window_at + 1.5:
            break
        time.sleep(0.005)
    # Dong cua so that, khong de progress abort 0xC0000409 luc thoat.
    hwnd = FindWindowW(None, TITLE)
    if hwnd:
        PostMessageW(hwnd, WM_CLOSE, 0, 0)
    closed_at = time.perf_counter()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return {"label": label, "exe": EXE,
            "window_exposed": window_at is not None,
            "spawn_to_window_s": round(window_at, 4) if window_at else None,
            "peak_rss_kib": peak_rss_kib if has_ps else None,
            "exit_code": proc.returncode,
            "close_s": round(time.perf_counter() - closed_at, 3)}


def run_report(report_path, extra_env=None):
    env = dict(os.environ)
    env.update(extra_env or {})
    started = time.perf_counter()
    proc = subprocess.run([EXE, "--startup-report", report_path],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=os.path.dirname(EXE))
    wall = time.perf_counter() - started
    payload = None
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        os.remove(report_path)
    return proc.returncode, wall, payload, (proc.stderr or "")[-400:]


FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


def force_cold_covers():
    """Doi ten thu muc cache anh: chac chan khong con b nao, khong xoa du lieu
    nguoi dung (thu muc duoc tra lai nguyen ven khi probe xong)."""
    image = os.path.join(cover_cache_dir(), "image")
    hidden = image + ".probe_hidden"
    if os.path.isdir(hidden):
        raise RuntimeError("con sot lan chay truoc: " + hidden)
    existed = os.path.isdir(image)
    names = os.listdir(image) if existed else []
    if existed:
        os.rename(image, hidden)
    return {"image": image, "hidden": hidden, "existed": existed,
            "files_before": len(names)}


def restore_covers(state):
    if os.path.isdir(state["image"]):
        for name in os.listdir(state["image"]):
            try:
                os.remove(os.path.join(state["image"], name))
            except OSError:
                pass
        os.rmdir(state["image"])
    if state["existed"]:
        os.rename(state["hidden"], state["image"])


def full_run():
    print("== before/after tren dung ban da cai ==")
    state = force_cold_covers()
    cold = warm = None
    try:
        rc, wall, cold, err = run_report(
            os.path.join(REPO, "scratch", "startup_cold.json"))
        print("cold rc=%d wall=%.3f err=%s" % (rc, wall, err[:120]))
        rc2, wall2, warm, err2 = run_report(
            os.path.join(REPO, "scratch", "startup_warm.json"))
        print("warm rc=%d wall=%.3f" % (rc2, wall2))
    finally:
        restore_covers(state)

    for tag, row in (("cold", cold), ("warm", warm)):
        if row is None:
            check("startup-report %d vi %s" % (rc if tag == "cold" else rc2, tag),
                  False, "khong co payload")
            continue
        check("checks xanh %s" % tag, row.get("ok") is True, row.get("checks"))
        check("tem ram do duoc %s" % tag, row["ram_at_window_kib"] > 10000,
              "%d KiB luc cua so lo" % row["ram_at_window_kib"])
        check("boot khong cv2 %s" % tag, not row["control"]["cv2_da_nap_luc_boot"])
        check("bia duoc ve %s" % tag,
              row["recent_cards"] > 0 and row["recent_covers"] == row["recent_cards"],
              "%d/%d card" % (row["recent_covers"], row["recent_cards"]))
        check("anh chung minh %s" % tag, os.path.isfile(row["evidence_shot"]),
              row["evidence_shot"])

    if cold and warm:
        # Day la phan biet that cua cache: lan dau giai ma frame nen cv2 van
        # nap sau khi cua so lo ra; lan sau khong con cv2 trong tien trinh.
        check("cold nap cv2 luc ngam", cold["control"]["cv2_luc_ngam"] is True,
              cold["control"])
        check("warm khong cv2 luc ngam", warm["control"]["cv2_luc_ngam"] is False,
              warm["control"])
        check("warm nhanh hon cold",
              warm["phases"][-1]["dt_s"] < cold["phases"][-1]["dt_s"],
              "sat le %0.3f s < %0.3f s" % (warm["phases"][-1]["dt_s"],
                                            cold["phases"][-1]["dt_s"]))
        check("boot < 2.8 s (ban cu do 3.5-3.8 s)",
              warm["boot_to_window_s"] < 2.8,
              "%.3f s" % warm["boot_to_window_s"])
        check("ram luc mo < 125 MiB (ban cu 137 MiB)",
              warm["ram_at_window_kib"] < 125 * 1024,
              "%d KiB" % warm["ram_at_window_kib"])
        with open(os.path.join(REPO, "scratch", "startup_after.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"cold": cold, "warm": warm}, handle, ensure_ascii=False, indent=2)

    ext = measure_external(label="sau toi uu")
    with open(os.path.join(REPO, "scratch", "startup_external_after.json"), "w",
              encoding="utf-8") as handle:
        json.dump(ext, handle, ensure_ascii=False, indent=2)
    check("cua so lo ra khi mo binh thuong", ext["window_exposed"], ext)
    check("spawn->cua so < 6 s", (ext["spawn_to_window_s"] or 99) < 6.0,
          ext["spawn_to_window_s"])
    check("peak RSS < 320 MiB", (ext["peak_rss_kib"] or 10 ** 9) < 320 * 1024,
          ext["peak_rss_kib"])
    check("dong sach, khong abort", ext["exit_code"] == 0, ext["exit_code"])

    print("\n%d FAIL" % len(FAILS))
    for name in FAILS:
        print("  - " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "external":
        label = sys.argv[2] if len(sys.argv) > 2 else "lan"
        out = measure_external(label=label)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        target = os.path.join(REPO, "scratch",
                              "startup_external_%s.json" % re.sub(
                                  r"[^A-Za-z0-9.-]+", "_", label))
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(out, handle, ensure_ascii=False, indent=2)
        sys.exit(0 if out["window_exposed"] else 1)
    sys.exit(full_run())
