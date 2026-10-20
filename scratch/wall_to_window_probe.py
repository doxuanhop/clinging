"""Do lan chuong cua nguoi dung: nhan đúp -> cua so hien -> UI thread tra loi.

    python scratch/wall_to_window_probe.py              # 3 lan tren exe da cai
    python scratch/wall_to_window_probe.py --runs 1
    python scratch/wall_to_window_probe.py --selfcheck   # phan chung cua tham do

Vi sao probe nay ton tai: `--startup-report` dat dong ho trong `main._boot()`,
tuc la no bat dau tinh TU LUC main.py chay dong lenh dau tien. Cac buc do
0,71-0,84 s den cua so chi la phan SAU cua lan chuong. Phan TRUOC — bootloader
PyInstaller, nap DLL cua PySide6, init CPython — khong mot dong report nao cham
toi, va tren may cau hinh thap do la phan nguoi dung goi la "lag".

Probe nay do ba thu, khong dung den JSON report:

 1. `wall_to_window_s`: Popen() -> cua so dau tien cua app co IsWindowVisible()
    = True. Day la khoang cach nguoi dung cam thay.
 2. `ui_rt_*`: vong lap `SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG)` dat vao
    chinh cua so do. UI thread rang thi Windows giu tin nhan trong hang doi nen
    phan hoi cham; do la tham do "cua so hien ra nhung khong bam duoc", dat ben
    ngoai app nen khong the bi dong ho cua app noi gian.
 3. `cold_read_mb`: tong dung luong file DLL/PYD duoc map tu thu muc cai dat.
    Day la LUONG DOC TOI DA khi het bom trang — uoc luong chu khong phai phep
    do: probe "doc file khac de duoi cache" that bai vi ly do nay (doc 1,5 GB tu
    cung file chi het 1,3 s, nghia la van nam trong RAM).

Ma thoat: 0 khi do duoc; 1 neu khong tim thay cua so hoac selfcheck cho thay
tham do khong phan biet duoc UI bi chan.
"""
import argparse
import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
from ctypes import wintypes

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002

_enum_cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_enum_cb_t, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPVOID, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                       wintypes.WPARAM, wintypes.LPARAM,
                                       ctypes.c_uint, ctypes.c_uint,
                                       ctypes.POINTER(wintypes.LPARAM)]
user32.SendMessageTimeoutW.restype = ctypes.c_long
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
                                wintypes.LPARAM]

WM_CLOSE = 0x0010


def visible_windows():
    """[(hwnd, pid, title)] cua moi cua so dinh cap dang hien tren may nay."""
    out = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value:
            out.append((hwnd, pid.value, buf.value))
        return True

    user32.EnumWindows(_enum_cb_t(cb), 0)
    return out


def ui_roundtrip_ms(hwnd, timeout_ms=5000):
    """Thoi gian UI thread cua hwnd phan hoi mot tin nhan rong.

    UI thread dang ban (ve, doc dia, giai ma anh) thi Windows giu tin nhan trong
    hang doi va ham nay tro ve cham; hung nang thi no tra ve 0 kem
    ERROR_TIMEOUT/ABORTIFHUNG. Day la tham do ben ngoai: khong can sua app,
    khong the bi dong ho cua app noi gian.
    """
    result = wintypes.LPARAM()
    started = time.perf_counter()
    ok = user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG,
                                    timeout_ms, ctypes.byref(result))
    elapsed = (time.perf_counter() - started) * 1000.0
    return elapsed, bool(ok)


def descendants(pid):
    """Pid cua app + moi con chau (PyInstaller onedir co the chi mot proc)."""
    found = {pid}
    try:
        import psutil
        for child in psutil.Process(pid).children(recursive=True):
            found.add(child.pid)
    except Exception:
        pass
    return found


def mapped_bytes(pids, install_dir):
    """Danh sach file anh xa (DLL/PYD/EXE) nam trong thu muc cai dat.

    Tra ve (so file, tong byte, [(MB, ten file)] sap xem giam dan) — ten file
    can luu vao JSON vi thu tu nap DLL cho biet phan nao cua bo PySide6 that
    su can cho trang Home, phan nao chi ke theo vi editor bi import som.
    """
    try:
        import psutil
    except ImportError:
        return 0, 0, []
    paths = set()
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            for group in proc.memory_maps(grouped=True):
                p = getattr(group, "path", None) or group[0]
                if p and p.lower().startswith(install_dir.lower()):
                    paths.add(os.path.normcase(p))
        except Exception:
            continue
    sized = []
    for p in paths:
        try:
            sized.append((os.path.getsize(p), p))
        except OSError:
            pass
    sized.sort(reverse=True)
    return len(paths), sum(s for s, _ in sized), [
        (round(s / 2**20, 2), os.path.relpath(p, install_dir)) for s, p in sized]


def measure_launch(exe, title_prefix, settle_s=10.0, poll_s=45.0, args=None):
    """Mot lan chuong that: mo app nhu nguoi dung roi do phan hoi cua UI thread."""
    install_dir = os.path.dirname(os.path.abspath(exe))
    proc = subprocess.Popen([exe] + list(args or []),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    started = time.perf_counter()
    deadline = started + poll_s
    hwnd = None
    window_title = ""
    tree = {proc.pid}
    while time.perf_counter() < deadline and hwnd is None:
        tree = descendants(proc.pid)
        for cand, pid, title in visible_windows():
            if pid in tree and title.lower().startswith(title_prefix.lower()):
                hwnd, window_title = cand, title
                break
        if hwnd is None:
            time.sleep(0.005)
    if hwnd is None:
        proc.kill()
        proc.wait(timeout=10)
        raise RuntimeError("Khong thay cua so '%s' trong %.0f s"
                           % (title_prefix, poll_s))
    wall_to_window = time.perf_counter() - started

    samples = []
    rss_at_window = 0
    map_count = map_bytes = 0
    end = time.perf_counter() + settle_s
    first = True
    while time.perf_counter() < end:
        elapsed, replied = ui_roundtrip_ms(hwnd)
        samples.append({"dt_s": round(time.perf_counter() - started, 3),
                        "rt_ms": round(elapsed, 1), "replied": replied})
        if first:
            first = False
            try:
                import psutil
                rss_at_window = psutil.Process(proc.pid).memory_info().rss // 1024
            except Exception:
                rss_at_window = 0
            map_count, map_bytes, mapped = mapped_bytes(tree, install_dir)
        time.sleep(0.05)

    # Dong cua that, khong kill: kill bo lai bootloader treo va lam hoen cac
    # lan do sau.
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        rc = proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait(timeout=10)
    rts = [s["rt_ms"] for s in samples]
    return {
        "wall_to_window_s": round(wall_to_window, 3),
        "window_title": window_title,
        "rss_at_window_kib": rss_at_window,
        "mapped_files": map_count,
        "cold_read_mb": round(map_bytes / 2**20, 1),
        "mapped_list": mapped,
        "ui_rt_first_ms": samples[0]["rt_ms"],
        "ui_rt_p50_ms": round(statistics.median(rts), 1),
        "ui_rt_max_ms": round(max(rts), 1),
        "ui_rt_over_250ms": sum(1 for v in rts if v > 250),
        "ui_rt_no_reply": sum(1 for v in samples if not v["replied"]),
        "close_rc": rc,
        "samples": samples,
    }


def selfcheck():
    """Chung minh tham do phan biet: cua so song >3 s khong tra loi.

    Mot cua so that (PySide6, source tree) show() roi ngam time.sleep(3) trong
    mot slot — UI thread bi chan 3 s. Neu `ui_rt_max_ms` khong vuot 2500 thi
    tham do vo nghia va moi ket luan 'lag' rut ra tu no la gia.
    """
    child = os.path.join(REPO, "scratch", "_wall_to_window_blocker.py")
    code = (
        "import sys, time\n"
        "from PySide6.QtCore import QTimer\n"
        "from PySide6.QtWidgets import QApplication, QWidget\n"
        "app = QApplication(sys.argv)\n"
        "w = QWidget()\n"
        "w.setWindowTitle('ClingingBlockerProbe')\n"
        "w.resize(320, 200)\n"
        "w.show()\n"
        "QTimer.singleShot(1200, lambda: time.sleep(3.0))\n"
        "QTimer.singleShot(7000, app.quit)\n"
        "sys.exit(app.exec())\n"
    )
    with open(child, "w", encoding="utf-8") as handle:
        handle.write(code)
    try:
        data = measure_launch(sys.executable, "ClingingBlockerProbe",
                              settle_s=6.0, args=[child])
    finally:
        os.remove(child)
    blocked = [s["rt_ms"] for s in data["samples"] if s["rt_ms"] > 1000]
    print("selfcheck rt_max=%.1f ms  mau >1s: %d"
          % (data["ui_rt_max_ms"], len(blocked)))
    ok = data["ui_rt_max_ms"] > 2500
    print("tham do PHAN BIET duoc UI bi chan: " + ("CO" if ok else "KHONG"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--exe", default=os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "Clinging",
        "Clinging.exe"))
    ap.add_argument("--title", default="Clinging")
    ap.add_argument("--poll-sec", type=float, default=45.0)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--out", default=os.path.join(
        REPO, "scratch", "_wall_to_window_report.json"))
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()
    if not os.path.isfile(args.exe):
        print("FAIL khong thay exe: " + args.exe)
        return 1
    runs = []
    for i in range(args.runs):
        try:
            data = measure_launch(args.exe, args.title, poll_s=args.poll_sec)
        except RuntimeError as exc:
            print("FAIL " + str(exc))
            return 1
        runs.append(data)
        print("lan %d: toi_cua_so=%.3f s  RSS_cua_so=%d KiB  "
              "map=%d file / %.1f MB  phan_hoi_dau=%.1f ms  "
              "p50=%.1f max=%.1f ms  mau>250ms=%d  khong_phan_hoi=%d  rc=%d"
              % (i + 1, data["wall_to_window_s"], data["rss_at_window_kib"],
                 data["mapped_files"], data["cold_read_mb"],
                 data["ui_rt_first_ms"], data["ui_rt_p50_ms"],
                 data["ui_rt_max_ms"], data["ui_rt_over_250ms"],
                 data["ui_rt_no_reply"], data["close_rc"]))
        time.sleep(2)
    walls = [r["wall_to_window_s"] for r in runs]
    print("KET LUAN wall_to_window: min=%.3f median=%.3f max=%.3f"
          % (min(walls), statistics.median(walls), max(walls)))
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"exe": args.exe, "runs": runs}, handle,
                  ensure_ascii=False, indent=2)
    print("json: " + args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
