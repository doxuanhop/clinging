"""scratch/console_window_probe.py — do cua so console CON THOAT vo patch.

Vi sao ton tai: ``main._suppress_child_console_windows()`` (main.py:115) vá
``subprocess.Popen`` thêm CREATE_NO_WINDOW, và exe phát hành là PE subsystem=2
(GUI) — đo 23/10/2026 trên cả ``dist\\Clinging`` lẫn bản cài Inno. Người dùng
vẫn báo "console đen chớp tắt", nên còn đúng hai câu hỏi chưa có số:

  (A) duong production (them clip, doc metadata, cat, nen, xuat frame) con
      spawn nao thieu CREATE_NO_WINDOW khong;
  (B) patch duoc dat o main.py:89 TUC LA SAU bon dong import dau cua ``_boot``
      — spawn nao nho vao khe ho do se cap console that, vi luc do cha no chua
      duoc vá.

Vi sao phai chay duoi pythonw.exe:
    ``python.exe`` trong Git Bash có sẵn console, mọi tiến trình con THỪA console
    đó nên không bao giờ mở cửa sổ riêng — probe sẽ xanh mà không chứng minh gì.
    ``pythonw.exe`` không có console, giống hệt bản đóng gói: tiến trình con nào
    thiếu CREATE_NO_WINDOW thì Windows PHẢI cấp phát console mới, và nó hiện lên.

Lệnh:
    pythonw scratch/console_window_probe.py                 # do (rc=0 = sạch)
    pythonw scratch/console_window_probe.py --phan-chung    # cổng phải ĐỎ đúng lý
    pythonw scratch/console_window_probe.py --boot-window   # che do con: do pha (B)

Báo cáo: scratch/console_window_probe.json (bang cua) +
scratch/console_boot_window.json (số đo pha trước patch).
"""
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
# Mode do that va mode phan chung PHAI ghi hai file RIENG: lan chay 23/10/2026
# `--phan-chung` chay ke sau do la bang cua mode do that bi xoa khoong loi bao,
# chi con lai 8 cua cua chinh no trong cung mot duong dan.
REPORT = os.path.join(
    HERE, "console_window_probe_cf.json" if "--phan-chung" in sys.argv
    else "console_window_probe.json")
BOOT_REPORT = os.path.join(HERE, "console_boot_window.json")
NO_WINDOW = 0x08000000
CONSOLE_MARKERS = ("consolewindowclass", "pseudoconsole", "cascadia", "vttrans",
                   "window console")
# Bon dong import DAU TIEN cua main._boot() (main.py:83-92) — cac module duoc
# nap TRUOC khi _suppress_child_console_windows() chay. Ten ghi theo module that
# nap: ``from theme import theme_manager`` nap module ``theme`` (theme.py là một
# module, không phải package). Them dong vao _boot ma khong them vao day thi
# pha (B) do mot duong khong ai chay.
BOOT_IMPORTS = ("theme", "ui.main_controller", "widgets.common", "core.settings")

if sys.stdout is None:
    # pythonw KHONG co console, print() khi do im lang (builtin print bo qua
    # khi sys.stdout la None): bang cua phai di qua mot file neu muon doc duoc
    # sau lan chay. JSON van la thu mua, file nay de phan tan cua nao FAIL.
    # Che do con phai ghi file RIENG: no la tien trinh con cua mode cha, dung
    # chung mot duong dan la no xoa mat bang cua cha (da tro thanh
    # FileNotFoundError khi lan dau chay do dung lieu nay).
    _suffix = ("_boot_window" if "--boot-window" in sys.argv else
               ("_frozen" if "--frozen" in sys.argv else ""))
    sys.stdout = open(os.path.join(
        HERE, "console_window_probe%s.log" % _suffix), "w",
        encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _console_windows():
    """(class, pid) của mọi cửa sổ top-level ĐANG hiện có tên lớp giống console."""
    user32 = ctypes.windll.user32
    found = []
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND,
                                   ctypes.wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        cls = (buf.value or "").lower()
        if any(marker in cls for marker in CONSOLE_MARKERS):
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((cls, int(pid.value)))
        return True

    user32.EnumWindows(proc_type(cb), 0)
    return found


def _watch(seconds, fn):
    """Chạy ``fn`` trong lúc một tóc giả quay EnumWindows; trả về cửa sổ console
    MỚI sinh (console sẵn có của máy dựng thử không được tính)."""
    hits = []
    before = set(_console_windows())
    stop_at = time.perf_counter() + seconds
    lock = threading.Lock()

    def loop():
        while time.perf_counter() < stop_at:
            for hit in _console_windows():
                with lock:
                    if hit not in before and hit not in hits:
                        hits.append(hit)
            time.sleep(0.005)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        fn()
    finally:
        stop_at = time.perf_counter()
        thread.join(timeout=3.0)
    with lock:
        return list(hits)


def _spy(real_init, sink):
    """Installs a recorder UNDER whatever patch is live; returns the spy."""

    def spy(self, *a, **kw):
        real_init(self, *a, **kw)
        argv = a[0] if a else kw.get("args")
        if isinstance(argv, (list, tuple)):
            name = os.path.basename(str(argv[0])) if argv else ""
        else:
            name = os.path.basename(str(argv))
        sink.append((name, int(kw.get("creationflags") or 0)))

    subprocess.Popen.__init__ = spy
    return spy


# ----------------------------------------------------------------- che do con
def boot_window_mode():
    """Do pha (B): spy duy nhat, CHUA co patch cua main, trong luc nap bon
    module dau cua ``_boot``. Co spawn nao o day la co console that."""
    canary = "--canary" in sys.argv
    recorded = []
    real_init = subprocess.Popen.__init__
    _spy(real_init, recorded)
    started = time.perf_counter()

    def do_imports():
        import importlib
        for name in BOOT_IMPORTS:
            importlib.import_module(name)
        if canary:
            # Mot spawn co y THIEU co, ngay trong pha do — phep thu chung
            # detector chay co THAT, khong phai no im lang vi khong co gi.
            from core import external_tools
            ffmpeg = external_tools.find("ffmpeg")
            subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=60)

    hits = _watch(45.0, do_imports)
    subprocess.Popen.__init__ = real_init
    naked = [name for name, flags in recorded if not (flags & NO_WINDOW)]
    payload = {"canary": canary, "seconds": round(time.perf_counter() - started, 1),
               "imports": list(BOOT_IMPORTS), "spawns": recorded,
               "naked": naked, "consoles": hits,
               "console_of_self": bool(ctypes.windll.kernel32.GetConsoleWindow())}
    with open(BOOT_REPORT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print("boot-window canary=%s spawns=%d naked=%d consoles=%d %s s"
          % (canary, len(recorded), len(naked), len(hits), payload["seconds"]))
    if canary:
        ok = bool(naked) and bool(hits)
    else:
        ok = not naked and not hits and not payload["console_of_self"]
    print("ALL PASS" if ok else "FAIL")
    sys.stdout.flush()
    sys.exit(0 if ok else 1)


if "--boot-window" in sys.argv:
    boot_window_mode()


# ------------------------------------------------- che do con: do tren EXE THAT
INSTALLED_EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                             "Clinging", "Clinging.exe")
BUNDLE_EXE = os.path.join(REPO, "dist", "Clinging", "Clinging.exe")
MEDIA_TOOLS = ("ffmpeg.exe", "ffprobe.exe")
# Truong hop RONG cua vet 4 phai ghi ra file KHAC: no cung chay `--frozen`,
# neu trung tro thi no ghi de payload cua lan do that — so 16,3 s /
# children=['ffmpeg.exe'] mat khong loi bao (do 23/10/2026).
def frozen_report_path(argv):
    """Duong dan file ma MOT tien trinh `--frozen` voi argv nay se ghi ra."""
    return os.path.join(HERE, "console_frozen_empty.json"
                        if "--empty" in argv else "console_frozen.json")


FROZEN_REPORT = frozen_report_path(sys.argv)


def frozen_exe_path():
    for index, arg in enumerate(sys.argv):
        if arg == "--exe" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return INSTALLED_EXE if os.path.isfile(INSTALLED_EXE) else BUNDLE_EXE


def _process_rows():
    """(pid, ppid, ten.exe) cua moi tien trinh dang song, qua Toolhelp snapshot."""
    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if handle in (0, -1):
        return []
    rows = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID),
                         (entry.szExeFile or "").lower()))
            ok = kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(handle)
    return rows


def _visible_windows(pid):
    user32 = ctypes.windll.user32
    found = []
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND,
                                   ctypes.wintypes.LPARAM)

    def cb(hwnd, _lparam):
        box = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(box))
        if int(box.value) == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(proc_type(cb), 0)
    return found


def make_fixture(tmp):
    """Video 2 giây có tiếng — fixture TỰ SINH, không đụng media người dùng."""
    ffmpeg = external_tools_find()
    if not ffmpeg:
        raise SystemExit("PROBE DUNG: khong tim thay ffmpeg")
    path = os.path.join(tmp, "fixture.mp4")
    subprocess.run([ffmpeg, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", path], check=True, timeout=240)
    if os.path.getsize(path) < 10000:
        raise SystemExit("PROBE DUNG: fixture qua nho (%d B)" % os.path.getsize(path))
    return path


def external_tools_find():
    from core import external_tools
    return external_tools.find("ffmpeg")


def build_project(tmp, with_clip):
    """Du an .clinq do chinh `project_storage` viet — khong phai mot file gia.

    AUTO_SAVE_FILE/RECOVERY_DIR redirect ve tam: `save_project_to_file` xoay ca
    ban phuc hoi trong %APPDATA%\\Clinging, chay tren may nguoi dung ma khong
    redirect la ghi de du lieu cua ho.
    """
    from core import project_storage
    from core.timeline_model import TimelineModel, TrackType

    project_storage.AUTO_SAVE_FILE = os.path.join(tmp, "_autosave.json")
    project_storage.RECOVERY_DIR = os.path.join(tmp, "_recovery")
    os.makedirs(project_storage.RECOVERY_DIR, exist_ok=True)
    media_dir = os.path.join(tmp, "media")
    os.makedirs(media_dir, exist_ok=True)
    project_dir = os.path.join(tmp, "Du an console")
    os.makedirs(project_dir, exist_ok=True)
    clinq = os.path.join(project_dir, "du_an.clinq")

    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.VIDEO)
    if with_clip:
        clip_path = make_fixture(media_dir)
        if model.add_clip(track.track_id, clip_path, "video", 0.0, 2.0,
                          name="fixture") is None:
            raise SystemExit("PROBE DUNG: add_clip tra None")
    if not project_storage.save_project_to_file(
            model, clinq, {"project_name": "Du an console"}):
        raise SystemExit("PROBE DUNG: khong luu duoc .clinq")
    return clinq


def frozen_mode():
    """Mở bản exe THẬT bằng một dự án có clip video, đếm cửa sổ console sinh ra.

    Day la buoc do duy nhat cham vao dung thu nguoi dung bao: patch nam trong
    ``main._boot`` va exe la GUI subsystem, nen mot console nhay len o day la
    loi nguyen ven cua ban phat hanh. APPDATA/LOCALAPPDATA cua con tro duoc
    redirect ve tam — ban cai khong duoc phep cham vao du an that cua ho.
    """
    exe = frozen_exe_path()
    if not os.path.isfile(exe):
        raise SystemExit("PROBE DUNG: khong thay exe %s" % exe)
    if any(name == "clinging.exe" for _p, _pp, name in _process_rows()):
        raise SystemExit("PROBE DUNG: may dang con Clinging.exe chay — dong app "
                         "truoc khi do (HDD 5400 rpm va DLL khoa lam lan do sai).")
    empty = "--empty" in sys.argv
    tmp = tempfile.mkdtemp(prefix="clinging_frozen_console_")
    clinq = build_project(tmp, not empty)
    roaming = os.path.join(tmp, "roaming")
    local = os.path.join(tmp, "local")
    os.makedirs(roaming)
    os.makedirs(local)
    env = dict(os.environ, APPDATA=roaming, LOCALAPPDATA=local)

    before = set(_console_windows())
    started = time.perf_counter()
    proc = subprocess.Popen([exe, clinq], env=env)
    consoles, tools, hwnds, appeared = [], [], None, 0.0
    # Lan do ket thuc SOM HON deadline khi cua so da hien va 15 s xem video da
    # qua. `hwnds` khong duoc phep tr thanh [] roi dung o do: lan chay dau
    # tien cua probe nay bao window=False/90,3 s chi vi poll TRUOC luc app kip
    # mo cua so, roi roi straight vao `proc.wait(90)` (do 23/10/2026).
    window_deadline = started + 45.0
    while time.perf_counter() - started < 90.0:
        for hit in _console_windows():
            if hit not in before and hit not in consoles:
                consoles.append(hit)
        for pid, ppid, name in _process_rows():
            if ppid == proc.pid and name in MEDIA_TOOLS and (pid, name) not in tools:
                tools.append((pid, name))
        if not hwnds:
            if time.perf_counter() < window_deadline and proc.poll() is None:
                hwnds = _visible_windows(proc.pid)
                if hwnds:
                    appeared = time.perf_counter()
        elif time.perf_counter() - appeared > 15.0:
            break
        time.sleep(0.02)
    for hwnd in (hwnds or []):
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    try:
        proc.wait(timeout=60)
        closed = True
    except subprocess.TimeoutExpired:
        proc.kill()
        closed = False
    shutil.rmtree(tmp, ignore_errors=True)

    payload = {"exe": exe, "empty": empty, "clinq_was": clinq,
               "seconds": round(time.perf_counter() - started, 1),
               "window": bool(hwnds), "closed_cleanly": closed,
               "media_children": sorted({n for _p, n in tools}),
               "consoles": consoles}
    with open(FROZEN_REPORT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print("frozen exe=%s empty=%s window=%s %s s children=%s consoles=%s"
          % (os.path.basename(exe), empty, payload["window"], payload["seconds"],
             payload["media_children"], consoles))
    ok = (payload["window"] and closed and not consoles
          and (bool(tools) if not empty else True))
    print("ALL PASS" if ok else "FAIL")
    sys.stdout.flush()
    sys.exit(0 if ok else 1)


if "--frozen" in sys.argv:
    frozen_mode()

# --------------------------------------------------------------------- mode cha
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import main as clinging_main  # noqa: E402
from core import external_tools, media_cache  # noqa: E402

RESULTS = []
SPAWNS = []
LAYERS = {}


def check(name, got, want):
    ok = got == want
    RESULTS.append({"name": name, "got": got, "want": want, "ok": ok})
    print("%-58s %-24s %s" % (name, str(got)[:24], "OK" if ok else "FAIL"))
    return ok


def install_layers():
    """Ba lớp, theo đúng thứ tự mà production xếp:

        caller -> patched (gop CREATE_NO_WINDOW) -> spy (ghi co THAT) -> goc

    spy NAM DUOI patched mới đọc được cờ sau khi đã gộp: ``patched_init`` sửa
    ngay dict ``kwargs`` của caller rồi gọi ``original(self, *args, **kwargs)``,
    nên dict spy nhận là một object đã mang cờ. Đặt spy TRÊN patched thì spy chỉ
    thấy cờ TRƯỚC khi vá — tức cổng "mọi spawn mang cờ" xanh vì đọc sai chỗ.
    """
    LAYERS["real"] = subprocess.Popen.__init__
    LAYERS["spy"] = _spy(LAYERS["real"], SPAWNS)
    clinging_main._suppress_child_console_windows()
    LAYERS["patched"] = subprocess.Popen.__init__
    assert LAYERS["patched"] is not LAYERS["spy"], "patch cua main khong nam tren spy"


def use_layer(name):
    """'patched' = duong that; 'spy' = cat hoan toan patch cua main."""
    subprocess.Popen.__init__ = LAYERS[name]


def production_sweeps(fixture):
    """Goi tung ham that sinh tien trinh con tren duong nguoi dung.

    Ham nao tra ve gia tri rong thi lan do KHONG sinh tien trinh nao, nen moi
    ham phai tra mot con so duoc — khong co vay thi "0 cua so console" xanh vi
    dau vao rong.
    """
    from core import (audio_mix, media_compress, media_extractor, media_frame,
                      media_splitter, system_stats)

    out = []
    meta = media_extractor.get_video_metadata(fixture)
    out.append(("media_extractor.get_video_metadata",
                float(meta.get("duration") or 0.0) > 0.0))
    out.append(("media_extractor.extract_audio_waveform",
                len(media_extractor.extract_audio_waveform(fixture, 60))))
    out.append(("media_extractor.get_media_duration",
                float(media_extractor.get_media_duration(fixture, "video")) > 0.0))
    out.append(("audio_mix.has_audio_stream",
                bool(audio_mix.has_audio_stream(fixture))))
    out.append(("media_splitter.media_info",
                len(media_splitter.media_info(fixture)) > 0))
    out.append(("media_splitter.keyframe_times",
                len(media_splitter.keyframe_times(fixture)) > 0))
    out.append(("media_compress.source_video_codec",
                media_compress.source_video_codec(fixture) == "h264"))
    out.append(("media_frame.extract_frame_image",
                int(media_frame.extract_frame_image(fixture, 0.5).width()) > 0))
    out.append(("system_stats.read_gpu",
                isinstance(system_stats.read_gpu(), dict)))
    return out


def run_frozen_child(extra):
    """Lan che do `--frozen` cua chinh file nay va doc so no ghi ra.

    Tam goi qua con tro rieng vi pha do PHAI chay trong mot process khong co
    console va khong co Qt cua mode cha — mot cua so console sinh ra trong luc
    cha dang gi QApplication van la cua do, nhung so do duoc doc lai tu file
    de khong ai phai do bang cach nhin man hinh.
    """
    child_argv = ["--frozen"] + list(extra)
    child = subprocess.run([sys.executable, os.path.abspath(__file__)]
                           + child_argv,
                           capture_output=True, timeout=400)
    # Doc theo duong dan CUA CON, khong phai cua cha: cha khong co `--empty`
    # trong argv nen neu dung FROZEN_REPORT cua minh thi no doc lai so cua lan
    # do that vua roi — vet 4 xanh vi tien trinh khac bao cao.
    with open(frozen_report_path(child_argv), encoding="utf-8") as handle:
        data = json.load(handle)
    data["rc"] = child.returncode
    data["stderr"] = (child.stderr or b"").decode("utf-8", "replace")[-400:]
    return data


def main_mode(fixture):
    check("probe chay duoi pythonw (khong co console cua me)",
          bool(ctypes.windll.kernel32.GetConsoleWindow()), False)
    check("patch cua main da nam tren Popen",
          getattr(subprocess.Popen, "_no_window_patched", False), True)
    for name, value in production_sweeps(fixture):
        check("goi that: " + name, bool(value), True)
    use_layer("patched")
    del SPAWNS[:]
    fresh = _watch(8.0, lambda: production_sweeps(fixture))
    check("khong cua so console MOI nao trong duong production", len(fresh), 0)
    if fresh:
        print("   THANG: " + ", ".join("%s pid=%s" % h for h in fresh))
    # 5 lan spawn la so DO DUOC (23/10/2026): nam ham gọi ffprobe, bon ham kia
    # đi OpenCV/pydub nên không spawn qua Popen. San 5 la beat that — nếu một
    # lần chạy nào tụt xuống 4 thì có nghĩa một hàm đã thôi spawn (đầu vào rỗng)
    # và mọi "0 cửa sổ" phía sau trở nên vô nghĩa.
    check("do duoc it nhat 5 lan sinh tien trinh con", len(SPAWNS) >= 5, True)
    check("trong do co ffprobe.exe (duong do THAT, khong phai vong lap rong)",
          any(name == "ffprobe.exe" for name, _ in SPAWNS), True)
    naked = sorted(name for name, flags in SPAWNS if not (flags & NO_WINDOW))
    check("moi lan sinh deu mang CREATE_NO_WINDOW", len(naked), 0)
    if naked:
        print("   THIEU CO: " + ", ".join(naked))
    print("   da sinh: " + ", ".join(sorted({a for a, _f in SPAWNS})))

    # Pha (B): patch dat sau 4 dong import dau cua _boot — do bang che do con,
    # mot pythonw rieng voi spy ma KHONG co patch.
    child = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--boot-window"], capture_output=True, timeout=300)
    boot = json.load(open(BOOT_REPORT, encoding="utf-8"))
    check("pha truoc patch: khong spawn nao trong 4 module dau _boot",
          len(boot["spawns"]), 0)
    check("pha truoc patch: khong cua so console nao", len(boot["consoles"]), 0)
    check("pha truoc patch: rc cua che do con", child.returncode, 0)
    print("   boot-window: %s s, spawns=%s, consoles=%s"
          % (boot["seconds"], boot["spawns"], boot["consoles"]))

    # (C) do tren BAN THAT: exe da cai mo du an co clip video — dung luc ma
    # nguoi dung bao console nhay len (them mo media, lam thumbnail/song hai).
    frozen = run_frozen_child([])
    check("exe phat hanh: cua so app mo that (lan do co nghia)", frozen["window"], True)
    check("exe phat hanh: app co sinh tien trinh media (ffprobe/ffmpeg)",
          bool(frozen["media_children"]), True)
    check("exe phat hanh: KHONG cua so console nao trong lan mo du an",
          len(frozen["consoles"]), 0)
    check("exe phat hanh: che do con rc", frozen["rc"], 0)
    print("   frozen: %s %s s children=%s consoles=%s"
          % (os.path.basename(frozen["exe"]), frozen["seconds"],
             frozen["media_children"], frozen["consoles"]))
    if frozen["consoles"]:
        print("   " + frozen["stderr"])


def counterfactual_mode(fixture):
    """Cac cong tren phai DO vi dung ly do — khong phai xanh vi detector chay hoai."""
    ffmpeg = external_tools.find("ffmpeg")

    # Vet 1: cat hoan toan patch cua main roi spawn mot console app. Windows
    # PHAI cấp phát console mới; nếu watcher không thấy thì mọi "0 cửa sổ" ở
    # main_mode đều vô nghĩa.
    use_layer("spy")
    fresh = _watch(6.0, lambda: subprocess.run([ffmpeg, "-version"],
                                               capture_output=True, timeout=60))
    check("phan chung 1: spawn khong co co MO duoc cua so console",
          len(fresh) >= 1, True)
    print("   thay: " + ", ".join("%s pid=%s" % h for h in fresh))

    # Vet 2: cung duong do, bo patch thi cua "moi lan sinh deu mang co" phai do
    # LECH — chung no do vi dung ten, khong do vi khong tim thay spawn nao.
    del SPAWNS[:]
    from core import audio_mix
    audio_mix.has_audio_stream(ffmpeg)
    naked = [a for a, f in SPAWNS if not (f & NO_WINDOW)]
    check("phan chung 2: bo patch thi cua CREATE_NO_WINDOW do lech",
          len(naked) >= 1, True)
    use_layer("patched")

    # Vet 3: cua "pha truoc patch" do vi dung ly do — che do con chay with
    # --canary (them mot spawn co y thieu co ngay trong pha do) PHAI bat duoc
    # ca naked lan console. Neu khong thi cua do chi xanh vi boot im lang hon.
    child = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--boot-window", "--canary"],
                           capture_output=True, timeout=300)
    boot = json.load(open(BOOT_REPORT, encoding="utf-8"))
    check("phan chung 3: canary boot-window mo duoc cua so console",
          len(boot["consoles"]) >= 1, True)
    check("phan chung 3: canary boot-window ghi duoc spawn thieu co",
          len(boot["naked"]) >= 1, True)
    check("phan chung 3: rc cua che do con khi canary", child.returncode, 0)

    # Vet 4: cua "exe phat hanh co sinh tien trinh media" do vi NOI DUNG, khong
    # do mot vong lap luc nao cung thay ffprobe. Cung exe do, mo mot du an KHONG
    # clip nao thi dem duoc 0 — hai lan chay ke nhau cham dung mot cai bat.
    frozen_empty = run_frozen_child(["--empty"])
    check("phan chung 4: du an khong clip thi dem duoc 0 tien trinh media",
          frozen_empty["media_children"], [])
    check("phan chung 4: du an khong clip van mo duoc cua so (lan do chay)",
          frozen_empty["window"], True)
    check("phan chung 4: che do con rc khi du an rong", frozen_empty["rc"], 0)


if __name__ == "__main__":
    counterfactual = "--phan-chung" in sys.argv
    started = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix="clinging_console_")
    media_cache.cache_root = lambda: tmp
    install_layers()
    try:
        fixture = make_fixture(tmp)
        if counterfactual:
            counterfactual_mode(fixture)
        else:
            main_mode(fixture)
    finally:
        use_layer("real")
    fails = [r["name"] for r in RESULTS if not r["ok"]]
    payload = {"mode": "counterfactual" if counterfactual else "main",
               "seconds": round(time.perf_counter() - started, 1),
               "spawns": len(SPAWNS), "failed": fails, "checks": RESULTS}
    with open(REPORT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print("ALL PASS" if not fails else "FAIL: " + ", ".join(fails))
    print("  %d cua, %s s, %d lan spawn -> %s"
          % (len(RESULTS), payload["seconds"], payload["spawns"],
             os.path.basename(REPORT)))
    rc = 0 if not fails else 1
    sys.stdout.flush()
    sys.exit(rc)
