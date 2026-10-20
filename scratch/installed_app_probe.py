"""scratch/installed_app_probe.py

Chung minh ban cai dat THAT: chay ClingingSetup-1.0.0.exe len PC nay roi do 6
lop bang chung, khong chi "file ton tai".

Hai dieu kien tien quyet cua chinh lan chay nay: dong LICH SU moi cua Clinging
con mo truoc khi cai (mot cua so song song khoa DLL -> Inno abort + rollback
rc=5), va snap/khoi nguyen byte du an cua nguoi dung (app tu _auto_save() ghi
lai file khi mo no).

Cac lop:
  1. Installer la exe PE, > 1 MB.
  2. /VERYSILENT tra ve ma 0 (Inno: 0 = thanh cong).
  3. Thu muc cai dat co Clinging.exe + _internal/styles + _internal/src.
  4. Shortcut Desktop/Start Menu tro ve duong dan cai dat (khong phai source D:).
  5. Co entry "Clinging" trong Add/Remove Programs (HKCU Uninstall key).
  6. Exe da cai tu selftest rc=0 va bao cao trung voi bundle goc.
  7. Mo app qua shortcut Desktop: cua so that, process exe nam trong thu muc cai
     dat, va anh capture khong phai mot man den dong nhat.
  8. --thumbnail-report: hop thoai trich xuat anh mo tu MainWindow cua ban da
     cai, 6 PNG + 1 anh tong hop that nam tren dia, anh chup cua so do co that.
  9. --graph-report: do thi duong cong keyframe mo tu MainWindow cua ban da
     cai — keo chuot that doi model, keo ngoai ban kinh bam khong cham vao
     model, undo/redo tren stack cua timeline lam kim cuong chay theo, duong
     ve tren man hinh khop interpolate_keyframes do bang pixel, va anh bang
     chung do chinh exe do ra.
 10. --split-report: chuột phải vào card thật mở hộp thoại cắt của bản đã cài,
     ffmpeg ĐI KÈM trong bundle cắt ra 3 file thật trên đĩa — ffprobe đo lại từng
     file, các mối cắt không hở/chồng, và MÀU của từng đoạn khớp màu nguồn ở
     đúng giây đoạn đó tự nhận (thời lượng đạt không phát hiện được đoạn replay).
 11. --project-report + registry: .clinq trong argv mo thang vao cua dung phim
     voi dung clip/thu vien/ten/ti le cua file — ca fixture LAN du an that cua
     nguoi dung tren may nay; duong dan khong co that khong duoc mo mot
     timeline trang; khoa .clinq cua Explorer chi ve exe da cai; va mot cú
     os.startfile THAT (nhap kep cua Explorer) phai giao duong dan — ca dau
     cach — toi dong lenh cua process moi.
 12. Tính tự chủ của bundle: FFmpeg/ffprobe phải nằm trong `_internal/tools`
     và exe đã cài phải tự nhận ra bản của nó (`[bundled]`), không có dấu vết
     faster-whisper còn sót, và `--import-report` phải nạp được MỌI module của
     app ngay trong bundle — vì một tính năng chỉ chạy khi người dùng bấm nút
     thì log build không nói gì về nó.
 13. Khởi động của bản đã cài: `--startup-report` đo đúng `main._boot()` của
     bundle, nên "boot không nạp cv2", "tem RAM ra số thật" và "bìa dự án gần
     đây được vẽ" là bằng chứng của file người ta nhận, không phải của source.
 14. `--style-report`: ba tính năng chỉ hỏng khi có người bấm — 8 thẻ Aura phải
     ghi đúng khoá xuống clip và làm khung hình đổi thật, hộp thoại lớp phủ recap
     phải mở từ nút header và đóng lại chỉ để lại ĐÚNG một mục lịch sử, combo
     karaoke 9 dòng phải đổi màu preview. Vùng hình học của clip trên canvas cũng
     đo ở đây: bản đã cài từng abort giữa chừng chỉ vì bấm bốn thẻ aura khác
     nhau, và lỗi đó không log build nào nhìn thấy được.

Chay:  python scratch/installed_app_probe.py
"""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import winreg

# Bao cao selftest chep ca nhan de UI co dau ("Trang chu" that la "Trang chủ"),
# nen khi redirect ra file stdout la cp1252 va gay UnicodeEncodeError giua
# chung — do that phai duoc in ra du, khong phai lymot loi gate.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _app_version():
    """MyAppVersion trong clinging.iss la nguon duy nhat, dung nhu make_msi.py.

    Before this, INSTALLER was the literal "ClingingSetup-1.0.0.exe". Every run
    of this probe then re-installed the PREVIOUS build over whatever had just
    been shipped, and the app under test was silently the old bundle (2026-10-20:
    the qtawesome removal looked installed, then this probe put qtawesome back
    and the selftest row renamed itself to "qtawesome" again).
    """
    text = open(os.path.join(ROOT, "packaging", "clinging.iss"),
                encoding="utf-8").read()
    match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
    if not match:
        raise SystemExit("Khong doc duoc MyAppVersion trong clinging.iss")
    return match.group(1)


INSTALLER = os.path.join(ROOT, "build", "installer",
                         "ClingingSetup-%s.exe" % _app_version())
LOCAL = os.environ.get("LOCALAPPDATA", "")
DEST = os.path.join(LOCAL, "Programs", "Clinging")
DEST_EXE = os.path.join(DEST, "Clinging.exe")
DESKTOP_LNK = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "Clinging.lnk")
# {group}/{autodesktop} cua Inno nam trong APPDATA (Roaming), khong phai LOCALAPPDATA.
ROAMING = os.environ.get("APPDATA", "")
START_LNK = os.path.join(ROAMING, "Microsoft", "Windows", "Start Menu", "Programs",
                         "Clinging", "Clinging.lnk")
SHOT = os.path.join(ROOT, "scratch", "installed_app_window.png")
EVIDENCE = os.path.join(ROOT, "scratch", "installed_app_evidence.json")

FAILS = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s   got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    return ok


def note(label, value):
    print("%-58s %s" % (label, value))


def clinq_association():
    """Doc cac khoa Inno ghi duoc khi cai per-user: HKCR trung voi
    HKCU\\Software\\Classes, khong can UAC va cung khong co HKLM nao de trỏ sai."""
    out = {"progid": None, "command": None}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\.clinq") as key:
            out["progid"] = winreg.QueryValueEx(key, "")[0]
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\Clinging.Project\shell\open\command") as key:
            out["command"] = winreg.QueryValueEx(key, "")[0]
    except OSError:
        pass
    return out


def terminate_new(pids_before):
    """Dong nhung cua so vua mo — de lai thi chung ghi autosave len cung mot
    project va lan truot cuoi cung an toan."""
    import psutil
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if proc.info["pid"] not in pids_before and \
               (proc.info["name"] or "").lower() == "clinging.exe":
                proc.terminate()
        except Exception:
            pass
    time.sleep(1.0)


def lnk_fields(path):
    if not os.path.isfile(path):
        return None
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(path)
    return {"target": link.TargetPath, "workdir": link.WorkingDirectory,
            "icon": link.IconLocation}


def uninstall_entries():
    key_path = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
    rows = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            name = winreg.EnumKey(root, index)
            try:
                with winreg.OpenKey(root, name) as sub:
                    display, _ = winreg.QueryValueEx(sub, "DisplayName")
                    location, _ = winreg.QueryValueEx(sub, "InstallLocation")
            except OSError:
                continue
            rows.append({"key": name, "display": display, "location": location})
    return rows


def launch_and_capture(pid_filter):
    """Mo cua so app, capture bang PrintWindow (memory: tooling-win-window-screenshot)."""
    import ctypes
    import ctypes.wintypes
    import psutil
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.SetProcessDPIAware()

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.wintypes.DWORD),
                    ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.wintypes.WORD),
                    ("biBitCount", ctypes.wintypes.WORD),
                    ("biCompression", ctypes.wintypes.DWORD),
                    ("biSizeImage", ctypes.wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.wintypes.DWORD),
                    ("biClrImportant", ctypes.wintypes.DWORD)]

    def grab(hwnd):
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 100 or height < 100:
            return None
        dc = user32.GetWindowDC(hwnd)
        mem_dc = gdi32.CreateCompatibleDC(dc)
        bmp = gdi32.CreateCompatibleBitmap(dc, width, height)
        gdi32.SelectObject(mem_dc, bmp)
        user32.PrintWindow(hwnd, mem_dc, 2)
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(info)
        info.biWidth, info.biHeight = width, -height
        info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(width * height * 4)
        image = None
        if gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(info), 0):
            image = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, dc)
        return image

    def windows_of(pid):
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            got_pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(got_pid))
            if got_pid.value == pid:
                length = user32.GetWindowTextLengthW(hwnd)
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if buffer.value:
                    found.append((hwnd, buffer.value))
            return True

        user32.EnumWindows(enum_proc, 0)
        return found

    deadline = time.time() + 45
    hit = None
    while time.time() < deadline:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = proc.info
                if info["pid"] in pid_filter:
                    continue
                if (info["name"] or "").lower() != "clinging.exe":
                    continue
                if not str(info["exe"] or "").lower().startswith(DEST.lower()):
                    continue
                wins = windows_of(info["pid"])
                if wins:
                    hit = (info["pid"], info["exe"], wins)
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if hit:
            break
        time.sleep(0.5)
    if not hit:
        return None
    pid, exe, wins = hit
    hwnd, title = max(wins, key=lambda row: len(row[1]))
    # Cua so bi toi thieu/om sau thi PrintWindow cho khung den: phoi lai no.
    user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.5)
    # PrintWindow co the tra ve man den neu chup truoc khi Qt ve frame dau
    # tien, nen phai thu lai cho toi khi co noi dung that.
    image = None
    distinct = 0
    for _attempt in range(12):
        image = grab(hwnd)
        if image is None:
            time.sleep(1.0)
            continue
        distinct = len(set(image.convert("RGB").resize((240, 150)).getdata()))
        if distinct > 200:
            break
        time.sleep(1.0)
    if image is None:
        return {"pid": pid, "exe": exe, "title": title, "image": None}
    image.save(SHOT)
    return {"pid": pid, "exe": exe, "title": title, "size": list(image.size),
            "distinct_colors": distinct, "image": SHOT}


def exe_icon_groups(path):
    """Dem RT_GROUP_ICON trong file exe: day la thu Explorer/taskbar dung den."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    # lpszType/lpszName la MAKEINTRESOURCE khi gia tri < 0x10000, nen ep kieu
    # c_void_p roi tu giai ma — doc thanh string dia chi 14 se crash process.
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMODULE,
                                   ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_ssize_t)

    def resource_text(value):
        if value is None:
            return ""
        number = value if isinstance(value, int) else ctypes.cast(
            value, ctypes.c_void_p).value or 0
        if number < 0x10000:
            return "#%d" % number
        return ctypes.wstring_at(number)

    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE,
                                        wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                            enum_proc, ctypes.c_ssize_t]
    # LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE: doc resource
    # cua exe ma khong nap code cua no.
    module = kernel32.LoadLibraryExW(path, 0, 0x2 | 0x20)
    if not module:
        return None
    found = []

    def collect(_module, _type, name, _lparam):
        found.append(resource_text(name))
        return True

    kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel32.EnumResourceNamesW(module, 14, enum_proc(collect), 0)
    kernel32.FreeLibrary(module)
    return found


def snapshot_user_projects():
    """Doc NGUYEN BYTE moi .clinq cua nguoi dung truoc khi probe mo bat cu
    cua so nao — selftest, thumbnail, graph, split va project-report deu tai
    autosave cua ho len timeline khi khoi dong, va _auto_save() ghi thang lai
    file do."""
    out = {}
    for path in glob.glob(os.path.join(os.environ.get("USERPROFILE", ""),
                                       "Clinging_Projects", "*", "*.clinq")):
        try:
            with open(path, "rb") as handle:
                out[path] = handle.read()
        except OSError:
            pass
    return out


def restore_user_projects(snapshots):
    """Tra lai byte goc, tra ve danh sach file da bi viet de trong lan do."""
    touched = []
    for path, data in snapshots.items():
        try:
            with open(path, "rb") as handle:
                now = handle.read()
            if now != data:
                touched.append((os.path.basename(path), len(now), len(data)))
                with open(path, "wb") as handle:
                    handle.write(data)
                with open(path, "rb") as handle:
                    if handle.read() != data:
                        FAILS.append("khong khoi nguyen duoc %s" % path)
        except OSError:
            pass
    return touched


def close_stray_instances(timeout=30.0):
    """Đóng LỊCH SƯ mọi cửa sổ Clinging còn mở trước khi chạy installer.

    Hai tai nan do chinh lan chay 19/10 bat duoc, ca hai deu la mot cua so song
    song voi probe:
      * Inno khong thay duoc DLL dang bi khoa — log ghi "DeleteFile failed;
        code 5. Access is denied" tren _internal\\libffi-8.dll, roi abort,
        ROLLBACK toan bo lan cai va tra rc=5.
      * Mot instance khong thuoc probe van chay _auto_save() cua no, nen file
        .clinq cua nguoi dung bi viet lai giua luc probe do.
    WM_CLOSE duoc gui truoc de app tu luu du lieu dang soan; chi khi no cai
    cach moi terminate, va ket qua duoc bao ra check chu khong an di.
    """
    import ctypes
    from ctypes import wintypes
    import psutil
    user32 = ctypes.windll.user32

    def pids():
        return {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                if (p.info["name"] or "").lower() == "clinging.exe"}

    alive = pids()
    if not alive:
        return [], []
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in alive and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            found.append((hwnd, pid.value, buf.value))
        return True

    user32.EnumWindows(collect, 0)
    for hwnd, _pid, _title in found:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pids():
            return found, []
        time.sleep(0.5)
    remaining = sorted(pids())
    for pid in remaining:
        try:
            psutil.Process(pid).terminate()
        except Exception:
            pass
    time.sleep(1.0)
    return found, remaining


def main():
    before_lnk = lnk_fields(DESKTOP_LNK)
    note("lnk Desktop TRUOC khi cai", (before_lnk or {}).get("target"))

    # Snap TRUOC khi dong cua: dong mot cua so dang mo cung lam app chay
    # _auto_save() (lan do 19/10 do no danh so lai asset_id cua "Du an 2"),
    # nen byte goc phai duoc lay truoc cai do, khong phai sau.
    user_snapshots = snapshot_user_projects()

    strays, stubborn = close_stray_instances()
    if strays:
        note("cua app dang mo truoc khi cai (da dong lich su)",
             [(pid, title) for _h, pid, title in strays])
    check("khong con cua Clinging nao khoa file khi cai", stubborn, [])

    check("installer la file PE", open(INSTALLER, "rb").read(2)
          if os.path.isfile(INSTALLER) else None, b"MZ")
    installer_mb = round(os.path.getsize(INSTALLER) / 1048576.0, 1)
    note("installer", "%s (%.1f MB)" % (INSTALLER, installer_mb))
    check("installer > 1 MB", installer_mb > 1.0, True)

    log = os.path.join(ROOT, "scratch", "installer_run.log")
    proc = subprocess.run([INSTALLER, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                           "/NORESTART", "/LOG=" + log])
    check("trinh cai dat tra ve ma 0", proc.returncode, 0)
    if os.path.isdir(DEST):
        note("noi dung thu muc cai dat", sorted(os.listdir(DEST)))

    check("Clinging.exe da cai", os.path.isfile(DEST_EXE), True)
    check("styles cua app da cai", os.path.isfile(
        os.path.join(DEST, "_internal", "styles", "dark.qss")), True)
    check("src.asr cua app da cai", os.path.isfile(
        os.path.join(DEST, "_internal", "src", "asr", "BcutASR.py")), True)

    after_lnk = lnk_fields(DESKTOP_LNK)
    check("lnk Desktop tro toi exe da cai",
          (after_lnk or {}).get("target", "").lower(), DEST_EXE.lower())
    check("lnk Desktop KHONG con tro source tree",
          "pythonw.exe" in (after_lnk or {}).get("target", "").lower(), False)
    note("lnk Desktop icon sau khi cai", (after_lnk or {}).get("icon"))
    check("co shortcut Start Menu", os.path.isfile(START_LNK), True)
    note("shortcut Start Menu", START_LNK)
    check("exe cai dat co icon RT_GROUP_ICON",
          len(exe_icon_groups(DEST_EXE) or []) >= 1, True)

    entries = [row for row in uninstall_entries()
               if (row["display"] or "").strip().lower() == "clinging"]
    check("co entry Add/Remove Programs", len(entries) >= 1, True)
    # May nay CAI HAI thu muc cung ten "Clinging" (Inno o Programs\Clinging va
    # MSI o Programs\ClingingMSI), nen entries[0] theo thu tu registry khong
    # phai ban Inno. Phai chon dung entry tro ve DEST; neu Inno mat entry thi
    # do la FAIL that, khong phai do thu tu duong dan.
    dest_norm = os.path.normpath(DEST).lower()
    own = [row for row in entries
           if os.path.normpath(row["location"] or "").lower() == dest_norm]
    check("co entry ARP tro dung vao thu muc Inno", len(own), 1)
    if own:
        note("registry uninstall (entry Inno)", own[0])
    for row in entries:
        note("entry ARP cung ten", "%s -> %s" % (row["key"], row["location"]))

    # Duong dan trung khong chung minh noi dung trung: lan cai 2026-10-20 13:15
    # de lai Clinging.exe cua ban cu (6.880.111 byte, _internal qtawesome) ben
    # trong khi _internal cua ban moi nam o cho khac. Set-diff theo ten duong
    # dan khong phat hien ra dieu do; sha256 thi co.
    dist_exe = os.path.join(ROOT, "dist", "Clinging", "Clinging.exe")

    def sha256_16(path):
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16]

    check("exe da cai TRUNG VOI exe trong dist theo byte",
          sha256_16(DEST_EXE), sha256_16(dist_exe))

    report_path = os.path.join(ROOT, "scratch", "installed_selftest.json")
    run = subprocess.run([DEST_EXE, "--selftest", report_path], timeout=300)
    with open(report_path, encoding="utf-8") as handle:
        report = json.load(handle)
    check("exe da cai selftest exit 0", run.returncode, 0)
    check("exe da cai selftest khong fail", report["failed"], [])
    check("selftest chay tu thu muc cai dat",
          report["exe"].lower(), DEST_EXE.lower())
    for row in report["checks"]:
        note("  " + row["name"], row["detail"][:100])

    # Font icon cua bundle da cai: "isNull False" khong chung minh duoc no
    # hien len, nen doc dung dong "font icon" trong bao cao cua chinh exe.
    qt_rows = [r for r in report["checks"] if r["name"] == "font icon"]
    check("bundle da cai co dong selftest 'font icon'", len(qt_rows), 1)
    if not qt_rows:
        names = [r["name"] for r in report["checks"]]
        note("ten cac dong selftest", names)
        return 1
    qt_row = qt_rows[0]
    check("exe da cai: font icon ve duoc pixel that",
          bool(qt_row["ok"]) and "pixel" in str(qt_row["detail"]), True)
    font_dir = os.path.join(os.path.dirname(DEST_EXE), "_internal",
                            "assets", "icons")
    fa6 = [f for f in os.listdir(font_dir)
           if f.startswith("fontawesome6-solid")] if os.path.isdir(font_dir) else []
    check("bundle da cai chon font + charmap FA6 solid",
          any(f.endswith(".ttf") for f in fa6)
          and any(f.endswith(".json") for f in fa6), True)
    check("bundle da cai kem ghi chu phep Font Awesome",
          os.path.isfile(os.path.join(font_dir, "LICENSE.txt")), True)
    # qtawesome phai that su rung khoi bundle, neu khong thi 0,6 s boot va
    # ~29 MB private quay lai ma khong ai nhin thay.
    qta_dir = os.path.join(os.path.dirname(DEST_EXE), "_internal", "qtawesome")
    check("bundle da cai KHONG con qtawesome", os.path.isdir(qta_dir), False)

    # Bang cong easing phai chay trong chinh bundle da cai — dong selftest do
    # noi suy that, nen no that bai neu PyInstaller khong kep theo module moi.
    ease_row = next(r for r in report["checks"]
                    if r["name"] == "duong cong easing cua keyframe")
    check("exe da cai: 9 duong cong easing + funnel noi suy chay that",
          bool(ease_row["ok"]) and "9 duong cong" in str(ease_row["detail"]),
          True)

    # Bon chang ve pop art phai chay trong chinh bundle da cai: dong selftest
    # do so bac mau, dien tich muc va do toi bien that, nen no no neu
    # PyInstaller khong kep theo ban clip_effects moi.
    art_row = next(r for r in report["checks"]
                   if r["name"] == "phong cach pop art")
    check("exe da cai: posterize + halftone + outline + contrast chay that",
          bool(art_row["ok"]) and "halftone" in str(art_row["detail"]), True)

    # Decoder tuan tu + cache dia la hai module MOI cua lan toi uu nay. Neu
    # PyInstaller khong kep chung thi dong selftest nay no, nen "selftest pass"
    # cua exe da cai van co nghia voi duong chay nong nhat.
    dec_row = next(r for r in report["checks"]
                   if r["name"] == "giai ma tuan tu + cache dia")
    check("exe da cai: frame_index_at + cache anh/song + nguon mat chay that",
          bool(dec_row["ok"]) and "round(t*fps)" in str(dec_row["detail"]),
          True)

    # Portability cua ban cai: FFmpeg PHAI nam trong bundle va duong chay that
    # cua exe da cai PHAI tro ve ban do, khong phai ban trong PATH cua may nay.
    # Mot may khong co FFmpeg thi chi khac ban nay o mot thu: thu muc tools.
    tools = os.path.join(os.path.dirname(DEST_EXE), "_internal", "tools")
    check("bundle da cai chep ffmpeg.exe vao _internal/tools",
          os.path.isfile(os.path.join(tools, "ffmpeg.exe")), True)
    check("bundle da cai chep ffprobe.exe vao _internal/tools",
          os.path.isfile(os.path.join(tools, "ffprobe.exe")), True)
    ff_row = next(r for r in report["checks"]
                  if r["name"] == "ffmpeg + ffprobe tim thay")
    check("exe da cai tu do duong dan ffmpeg cua no",
          bool(ff_row["ok"]) and "[bundled]" in str(ff_row["detail"]), True)
    note("ffmpeg/ffprobe cua bundle da cai", str(ff_row["detail"])[:160])

    # Faster Whisper (local) bi bo vi no keo 193 MB vao bundle trong khi khong
    # engine nao trong so do chay duoc o day. Neu PyInstaller con phan tich
    # duoc no thi cac thu muc nay van con trong _internal.
    leftovers = [name for name in ("faster_whisper", "ctranslate2",
                                   "onnxruntime", "av.libs")
                 if os.path.isdir(os.path.join(os.path.dirname(DEST_EXE),
                                               "_internal", name))]
    check("bundle da cai khong con faster-whisper/ctranslate2/onnxruntime/av",
          leftovers, [])
    note("dung luong _internal cua ban da cai (MB)",
         round(sum(os.path.getsize(os.path.join(r, f))
                   for r, _d, fs in os.walk(os.path.dirname(DEST_EXE))
                   for f in fs) / 1048576, 1))

    # Quet TOAN BO module cua bundle. --selftest chi do duoc nhung module ma
    # dong cua no goi ten; nut bam cua nguoi dung lai goi nhung module khac,
    # va neu PyInstaller khong kep chung thi loi chi no ra sau khi installer
    # bao "thanh cong". Phep phan biet nam trong chinh doan nay: tkinter bi
    # exclude, nen no PHAI that bai — neu no nay thi "0 loi" chi la do sweep
    # khong chay that trong bundle.
    imports_path = os.path.join(ROOT, "scratch", "installed_imports.json")
    imports_run = subprocess.run([DEST_EXE, "--import-report", imports_path],
                                 timeout=300)
    with open(imports_path, encoding="utf-8") as handle:
        imports = json.load(handle)
    note("module sweep do duoc trong bundle",
         "%d nap, %d loi" % (len(imports["loaded"]), len(imports["failures"])))
    check("import-report cua exe da cai tra ve ma 0", imports_run.returncode, 0)
    check("sweep chay trong bundle dong goi (khong phai source)",
          imports["frozen"], True)
    check("sweep do duoc hon 50 module (khong phai danh sach rong)",
          imports["attempted"] >= 50, True)
    check("moi module cua bundle da cai nap duoc", imports["failures"], [])
    check("phep phan biet: tkinter KHONG nap duoc trong bundle",
          imports["tkinter_present"], False)
    for name in ("core.external_tools", "core.media_splitter",
                 "core.auto_captions", "ui.split_dialog",
                 "ui.thumbnail_dialog", "ui.keyframe_graph_dialog",
                 "src.asr.BcutASR"):
        check("bundle da cai co " + name, name in imports["loaded"], True)

    # Khoi dong cua DUNG ban da cai: do bang chinh duong boot cua no
    # (main._boot), khong phai do tu source — source luon nhanh hon vi no
    # khong phai bootloader giai nan bundle.
    startup_path = os.path.join(ROOT, "scratch", "installed_startup.json")
    for stale in (startup_path, startup_path[:-5] + ".png"):
        if os.path.isfile(stale):
            os.remove(stale)
    startup_run = subprocess.run([DEST_EXE, "--startup-report", startup_path],
                                 timeout=300)
    with open(startup_path, encoding="utf-8") as handle:
        startup = json.load(handle)
    note("boot do tu exe da cai (s / KiB)",
         {"boot_to_window_s": round(startup["boot_to_window_s"], 3),
          "ram_at_window_kib": startup["ram_at_window_kib"],
          "ram_idle_kib": startup["ram_idle_kib"],
          "card_bia": [startup["recent_covers"], startup["recent_cards"]],
          "control": startup["control"]})
    check("startup-report cua exe da cai tra ve ma 0", startup_run.returncode, 0)
    check("startup do trong bundle dong goi (frozen)", startup["frozen"], True)
    check("moi check khoi dong deu xanh", startup["checks"],
          {k: True for k in startup["checks"]})
    # Phep phan biet cua ban toi uu: cv2 (134 MiB RSS, ~0,5 s nap) khong duoc
    # con nam trong duong boot nua. Ban cu do tren may nay: cv2 co, 3.5-3.8 s,
    # 137 MiB luc cua so lo ra.
    check("exe da cai: boot khong nap cv2",
          startup["control"]["cv2_da_nap_luc_boot"], False)
    check("exe da cai: tem RAM do duoc (khong phai so 0 gia tạo)",
          startup["ram_at_window_kib"] > 10000, True)
    check("exe da cai: dong ho phan biet nhe/nang",
          startup["control"]["nang_s"] >= 0.05, True)
    check("exe da cai: bia du an gan day duoc ve",
          [startup["recent_cards"] >= 1, startup["recent_covers"]],
          [True, startup["recent_cards"]])
    check("exe da cai: anh chung minh khoi dong nam tren dia",
          os.path.isfile(startup["evidence_shot"]), True)

    # Ba tinh nang chi hong khi co nguoi bam. --selftest cua bundle do duong ve
    # (aura_paint/recap_overlay/karaoke_paint) nhung chua tung cham vao mot cai
    # the nao, nen mot chu giu lien ket nhat trong panel cung khong ai biet.
    style_path = os.path.join(ROOT, "scratch", "installed_style.json")
    for stale in (style_path, style_path[:-5] + ".png"):
        if os.path.isfile(stale):
            os.remove(stale)
    style_run = subprocess.run([DEST_EXE, "--style-report", style_path],
                               timeout=900)
    check("style-report cua exe da cai tra ve ma 0", style_run.returncode, 0)
    with open(style_path, encoding="utf-8") as handle:
        style = json.load(handle)
    note("style report do tu exe da cai", {
        "the aura": style["the_aura"],
        "aura_lech_nhat_px": style["aura_lech_nhat_px"],
        "boundingRect_khong/co_aura": style["boundingRect_px"],
        "aura_loang_px": style["aura_loang_px"],
        "vung_chuot_px": style["vung_chuot_px"],
        "lop_phu_px": style["lop_phu_px"],
        "muc_undo_khi_dong": style["muc_undo_khi_dong"],
        "karaoke_lech_px": style["karaoke_lech_px"],
        "mau_trong_anh": style["mau_trong_anh"]})
    check("style do trong bundle dong goi (frozen)", style["frozen"], True)
    check("moi check cua style report deu xanh", style["checks"],
          {k: True for k in style["checks"]})
    check("exe da cai: nhom Aura co du 8 the", len(style["the_aura"]), 8)
    check("exe da cai: 8 the ghi 8 khoa aura khac nhau",
          len({v[0] for v in style["aura_applied"].values()}), 8)
    check("exe da cai: bam the aura lam khung hinh doi that",
          [v[1] >= 200 for v in style["aura_applied"].values()],
          [True] * len(style["aura_applied"]))
    # Bat dong dang hinh hoc: truoc day bam 4 the aura khac nhau trong mot phien
    # la process chet giua app.processEvents() — boundingRect cua clip noi theo
    # clip.effects, scene mat ding index cua no.
    check("exe da cai: boundingRect khong doi khi gan/go aura",
          [style["boundingRect_px"][0] == style["boundingRect_px"][1],
           style["boundingRect_px"][2] == style["boundingRect_px"][3]],
          [True, True])
    check("exe da cai: van con cho cho aura loang ra ngoai khung",
          style["aura_loang_px"] >= 0.19 * min(style["khung_clip_px"]), True)
    check("exe da cai: vung bat chuot khong an theo vung loang",
          style["vung_chuot_px"] <= style["khung_clip_px"][0] + 24.5, True)
    check("exe da cai: dong hop thoai lop phu chi de lai 1 muc undo",
          style["muc_undo_khi_dong"], 1)
    check("exe da cai: chon kieu karaoke la preview doi that",
          all(v >= 120 for v in style["karaoke_lech_px"].values()), True)
    style_shot = os.path.join(ROOT, "scratch", "installed_style_evidence.png")
    if os.path.isfile(style["screenshot"]):
        shutil.copyfile(style["screenshot"], style_shot)
        check("exe da cai: anh bang chung aura/lop phu/karaoke nam trong scratch",
              os.path.getsize(style_shot) > 2048, True)
    else:
        check("exe da cai: anh bang chung aura/lop phu/karaoke nam tren dia",
              False, True)

    # Do ti le bo cuc cua DUNG exe da cai (khong phai do tu source).
    layout_path = os.path.join(ROOT, "scratch", "installed_layout.json")
    layout_run = subprocess.run([DEST_EXE, "--layout-report", layout_path],
                                timeout=300)
    check("layout report exit 0", layout_run.returncode, 0)
    with open(layout_path, encoding="utf-8") as handle:
        layout = json.load(handle)
    note("bo cuc do duoc tu exe da cai", layout)
    check("timeline cua exe da cai nam trong 28-34% cua so",
          28.0 <= layout["timeline_pct"] <= 34.0, True)
    check("exe da cai dung bundle dong goi (frozen)", layout["frozen"], True)

    # Do lech hang track cua DUNG exe da cai: header trai vs lane phai.
    align_path = os.path.join(ROOT, "scratch", "installed_alignment.json")
    align_run = subprocess.run([DEST_EXE, "--alignment-report", align_path],
                               timeout=300)
    check("alignment report exit 0", align_run.returncode, 0)
    with open(align_path, encoding="utf-8") as handle:
        align = json.load(handle)
    note("lech hang lon nhat do tu exe da cai (px)", align["worst_diff_px"])
    check("exe da cai: header va lane thang hang (<=1px)", align["aligned"], True)
    geo = [scene["geometry"] for scene in align["scenarios"].values()]
    check("exe da cai: hai scene cao bang nhau",
          all(g["body_scene_h"] == g["header_scene_h"] for g in geo), True)
    check("exe da cai: hai viewport cao bang nhau",
          all(g["body_viewport_h"] == g["header_viewport_h"] for g in geo), True)
    check("exe da cai: hai range cuộn bang nhau",
          all(g["body_scroll"] == g["header_scroll"] for g in geo), True)
    check("co anh alignment tu exe da cai",
          os.path.isfile(align["screenshot"]), True)

    # The Audio card is UI, so the shipped bundle must hand over its own pixels,
    # not a screenshot taken from the source tree.
    audio_path = os.path.join(ROOT, "scratch", "installed_audio.json")
    audio_shot = os.path.join(ROOT, "scratch", "installed_audio_card.png")
    audio_run = subprocess.run([DEST_EXE, "--audio-report", audio_path],
                               timeout=300)
    check("audio report exit 0", audio_run.returncode, 0)
    with open(audio_path, encoding="utf-8") as handle:
        audio = json.load(handle)
    note("the card do duoc tu exe da cai",
         {key: audio[key] for key in ("card_visible", "sliders",
                                      "distinct_colors", "export_tokens")})
    check("exe da cai: the card opens on an audio clip", audio["card_visible"], True)
    check("exe da cai: slider reads the model, not its own memory",
          audio["sliders"], [45, 100, 50, 0])
    check("exe da cai: card is drawn, not a blank box",
          audio["distinct_colors"] > 20, True)
    check("exe da cai: plan carries volume + fade",
          audio["export_tokens"], ["volume=0.450000,", "afade=t=in:"])
    check("exe da cai: card PNG written by the installed bundle",
          os.path.isfile(audio["screenshot"]), True)
    if os.path.isfile(audio["screenshot"]):
        shutil.copyfile(audio["screenshot"], audio_shot)
        check("anh card cua ban da cai nam trong scratch",
              os.path.getsize(audio_shot) > 2048, True)

    import psutil
    # Dead chrome khong crash va khong de lai dau vet trong log, nen ban da cai
    # phai tu do ket noi that cua no. Counterfactual da do tren duong nay: chen
    # mot nut chet vao HomePage thi --chrome-report tra ve rc=1 va neu ten nut.
    chrome_path = os.path.join(ROOT, "scratch", "installed_chrome.json")
    chrome_run = subprocess.run([DEST_EXE, "--chrome-report", chrome_path],
                                timeout=600)
    check("chrome report exit 0", chrome_run.returncode, 0)
    with open(chrome_path, encoding="utf-8") as handle:
        chrome = json.load(handle)
    note("audit tu exe da cai",
         [(row["label"], row["controls"], row["menus"], row["menu_actions"])
          for row in chrome["audit"]])
    check("exe da cai: 0 control nhin thay duoc ma khong co slot",
          chrome["dead"], [])
    check("exe da cai: bundle dong goi that (frozen)", chrome["frozen"], True)
    check("exe da cai: audit vuon qua 20 control Editor va 8 menu",
          [chrome["audit"][1]["controls"] >= 20,
           chrome["audit"][1]["menus"] >= 8], [True, True])
    focus = chrome["focus"]
    check("exe da cai: nut toan man hinh lam timeline cao len that",
          [focus["timeline_grows"], focus["preview_shrinks"]], [True, True])
    check("exe da cai: icon nut doi raster pixel, khong chi doi ten",
          focus["icon_changed"], True)
    check("exe da cai: bam lan hai tra dung bo cuc cu",
          focus["restore_exact"], True)
    note("bo cuc do duoc khi focus",
         {"truoc": focus["before"], "focus": focus["focused"],
          "restore": focus["restored"]})
    check("exe da cai: anh bang chung focus nam tren dia",
          os.path.isfile(chrome["screenshot"]), True)

    # --selftest cua exe da cai phai chua chinh dong kiem nay, neu khong thi
    # "selftest pass" van vo nghia voi chrome chet.
    check("exe da cai: selftest co dong kiem chrome",
          any(row["name"].startswith("chrome") for row in report["checks"]),
          True)
    check("exe da cai: selftest co dong kiem thumbnail",
          any(row["name"].startswith("trich xuat anh")
              for row in report["checks"]), True)
    check("exe da cai: selftest co dong kiem do thi duong cong",
          any(row["name"].startswith("do thi duong cong")
              for row in report["checks"]), True)

    # Ba thanh tien trinh (split / thumbnail / Auto Captions) phai cung mot do
    # day trong chinh bundle. Hai dong tren do duoc chung bang report rieng;
    # rieng Auto Captions khong co report cua nguoi dung (no goi mang), nen
    # bang chung duy nhat cho ban da cai la dong selftest nay — no dung dung
    # thuoc bar_measure va tu phep phan biet kieu cu, nen "pass" khong the la
    # mot phep do te li.
    asr_row = next((r for r in report["checks"]
                    if r["name"].startswith("thanh tien do Auto Captions")),
                   None)
    check("exe da cai: selftest co dong kiem thanh Auto Captions",
          asr_row is not None, True)
    if asr_row is not None:
        note("thanh Auto Captions ban da cai", asr_row["detail"][:120])
        check("exe da cai: thang Auto Captions MON va co pixel that",
              [bool(asr_row["ok"]), "vs kieu cu" in str(asr_row["detail"])],
              [True, True])

    # Trich xuat anh: cua so that mo tu MainWindow cua ban DA CAI, worker that,
    # va PNG that nam lai tren dia. Do bang source thi khong noi duoc dieu gi
    # ve bundle nguoi dung nhan.
    thumb_path = os.path.join(ROOT, "scratch", "installed_thumbnail.json")
    thumb_out = os.path.join(tempfile.gettempdir(),
                             "clinging_thumbnail_report_out")
    if os.path.isdir(thumb_out):
        shutil.rmtree(thumb_out)
    thumb_run = subprocess.run([DEST_EXE, "--thumbnail-report", thumb_path],
                               timeout=600)
    check("thumbnail report exit 0", thumb_run.returncode, 0)
    with open(thumb_path, encoding="utf-8") as handle:
        thumb = json.load(handle)
    note("hop thoai cua ban da cai",
         {"tieu de": thumb["dialog_title"], "chrome": thumb["chrome"],
          "anh tren dia": len(thumb["on_disk"]), "sheet": thumb["sheets"],
          "mau trong anh": thumb["distinct_colors"]})
    check("exe da cai: bundle dong goi that (frozen)", thumb["frozen"], True)
    check("exe da cai: hop thoai mo tu duong dan chuot phai",
          thumb["selected_source"], os.path.abspath(thumb["source"]))
    check("exe da cai: 6 PNG nam tren dia, khong moc nao thieu",
          [len(thumb["on_disk"]), thumb["missing"]], [6, []])
    check("exe da cai: PNG doc lai duoc dung kich thuoc form hen",
          thumb["decoded_sizes"], [thumb["decoded_sizes"][0]] * 6)
    check("exe da cai: co anh tong hop", len(thumb["sheets"]), 1)
    check("exe da cai: form 600px khong co thanh cuon xuyen tat",
          [thumb["chrome"]["visible"], thumb["chrome"]["maximum"]],
          [False, 0])
    check("exe da cai: thang tien do chi hien khi lot chay",
          [thumb["chrome"]["progress_visible_before"],
           thumb["progress_visible_after"]], [False, True])
    note("do day thanh tien trinh ban da cai (px thiet bi, DPR)",
         [thumb["progress_band_px"], thumb["progress_dpr"]])
    check("exe da cai: thang tien do MON (8px CSS, do tren pixel cua bundle)",
          [thumb["progress_band_px"] > 3,
           thumb["progress_band_px"] <= thumb["progress_dpr"] * 8 + 3],
          [True, True])
    check("exe da cai: cua so ve co that (khong phai hop den)",
          thumb["distinct_colors"] > 40, True)
    check("exe da cai: anh hop thoai thumbnail nam tren dia",
          os.path.isfile(thumb["screenshot"]), True)

    # Do thi duong cong: ba thu chi co o ban da cai moi noi len — duong ve co
    # phai duong interpolate_keyframes tra ra (do bang pixel tren anh grab cua
    # chinh exe), mot cu keo chuot that co thay model hay khong, va undo/redo
    # tren stack cua timeline co lam vien kim cuong chay theo hay khong.
    graph_path = os.path.join(ROOT, "scratch", "installed_graph.json")
    graph_shot = os.path.join(ROOT, "scratch", "installed_graph.png")
    graph_run = subprocess.run([DEST_EXE, "--graph-report", graph_path],
                               timeout=600)
    check("graph report exit 0", graph_run.returncode, 0)
    with open(graph_path, encoding="utf-8") as handle:
        graph = json.load(handle)
    note("do thi cua ban da cai",
         {"tieu de": graph["clip_title"], "lane": graph["lanes"],
          "keo ngoai ban kinh": graph["keo_ngoai_ban_kinh"]["undo_delta"],
          "keo dung tam": graph["keo_dung_tam"]["model"][-1],
          "doan net moi cot": graph["duong_ve"]["doan_net"],
          "lech duong ve (px)": graph["duong_ve"]["max_lech_px"],
          "cot so 6 lane": graph["cot_so"],
          "mau trong anh": graph["distinct_colors"]})
    check("exe da cai: do thi mo tu MainWindow cua bundle (frozen)",
          graph["frozen"], True)
    check("exe da cai: hop thoai do thi dung lai, khong chan bang hinh",
          [graph["hop_thoai_dung_lai"], graph["modal"]], [True, False])
    check("exe da cai: keo ngoai ban kinh bam khong cham vao model",
          [graph["keo_ngoai_ban_kinh"]["model"],
           graph["keo_ngoai_ban_kinh"]["undo_delta"],
           graph["keo_ngoai_ban_kinh"]["selected"]],
          [graph["truoc_khi_keo"], 0, None])
    check("exe da cai: keo dung tam dat dung (thoi gian, gia tri) cua pixel",
          [graph["keo_dung_tam"]["model"][-1],
           graph["keo_dung_tam"]["undo_delta"]],
          [[1.5, 250.0, "ease_out_expo"], 1])
    check("exe da cai: undo tu stack timeline tra moc ve dung cho cu",
          [graph["undo"]["model"][-1], graph["undo"]["diamonds_x"]],
          [[2.0, -100.0, "ease_out_expo"], [0.0, 1.0, 2.0]])
    check("exe da cai: redo dat lai moc va kim cuong di theo",
          [graph["redo"]["model"][-1], graph["redo"]["diamonds_x"]],
          [[1.5, 250.0, "ease_out_expo"], [0.0, 1.0, 1.5]])
    check("exe da cai: duong tren do thi la duong cua model (<=2.5px)",
          graph["duong_ve"]["max_lech_px"] is not None
          and graph["duong_ve"]["max_lech_px"] <= 2.5, True)
    check("exe da cai: moi cot chi co MOT doan net (khong co loi keo nguoc)",
          graph["duong_ve"]["doan_net"], [1] * len(graph["duong_ve"]["doan_net"]))
    check("exe da cai: duong ve co do duoc it nhat 4 cot",
          graph["duong_ve"]["cot_do"] >= 4, True)
    check("exe da cai: 6 property ra 6 lane dung thu tu", graph["lanes"],
         ["x", "y", "scale_x", "scale_y", "rotation", "opacity"])
    gutter = graph["cot_so"]
    check("exe da cai: cot so 6 lane khong de len nhau (moi lane >=2 dong)",
          [gutter["dong"] >= 2 * len(graph["lanes"]),
           gutter["cao_nhat_px"] <= gutter["cao_chu_px"] + 3,
           gutter["le_hep_nhat_px"] >= 2], [True, True, True])
    # ANH BANG CHUNG PHAI NOI DUNG CHUINH NO: lane co day so am thi "-372px"
    # phai con nguyen dau tru tren PNG, khong phai chi dung trong model.
    check("exe da cai: dau tru cua so am con nguyen ven tren anh",
          [gutter["dau_tru_muon"], gutter["dau_tru"],
           gutter["dau_tru"] == gutter["dau_tru_muon"]], [3, 3, True])
    check("exe da cai: cua so ve co that (khong phai hop den)",
          graph["distinct_colors"] > 40, True)
    if os.path.isfile(graph["screenshot"]):
        # Banner do thi da ty viet vao scratch/installed_graph.png (duong dan no
        # sinh ra tu chinh report path), nen chep khi trung la chep vo nghia va
        # shutil bao SameFileError.
        if not os.path.samefile(graph["screenshot"], graph_shot):
            shutil.copyfile(graph["screenshot"], graph_shot)
        check("exe da cai: anh do thi nam trong scratch",
              os.path.getsize(graph_shot) > 2048, True)
    else:
        check("exe da cai: anh do thi nam tren dia", False, True)

    # ── 10. Cắt file thành N đoạn: chuột phải thật -> file thật trên đĩa ──
    # Bundle phai cat duoc bang ffmpeg cua NGUOI DUNG, va moi file phai mang
    # DUNG noi dung (mau) cua no — thoi luong dat khong chung minh duoc dieu
    # do, vi mot doan replay doan khac van co thoi luong dep.
    split_path = os.path.join(ROOT, "scratch", "installed_split.json")
    split_shot = os.path.join(ROOT, "scratch", "installed_split.png")
    split_out = os.path.join(tempfile.gettempdir(), "clinging_split_report_out")
    for stale in (split_path, split_path[:-5] + ".png"):
        if os.path.isfile(stale):
            os.remove(stale)
    shutil.rmtree(split_out, ignore_errors=True)
    split_run = subprocess.run([DEST_EXE, "--split-report", split_path],
                               timeout=900)
    check("split report exit 0", split_run.returncode, 0)
    with open(split_path, encoding="utf-8") as handle:
        split = json.load(handle)
    note("cat file cua ban da cai",
         {"menu": split["menu_actions"], "tieu de": split["dialog_title"],
          "doan tren dia": split["on_disk"], "mei cat": split["joints"],
          "lech mau": split["hue_gaps"], "status": split["status"],
          "mau trong anh": split["distinct_colors"]})
    check("exe da cai: bundle doc duoc module cat file (frozen)",
          split["frozen"], True)
    check("exe da cai: card video co 2 hanh dong, hanh dong 2 la cat file",
          [len(split["menu_actions"]), "Cắt" in split["menu_actions"][-1]],
          [2, True])
    check("exe da cai: chuot phai mo hop thoai dung nguon vua bam",
          split["selected_source"], os.path.abspath(split["source"]))
    check("exe da cai: 3 file nam tren dia, khong doan nao that bai",
          [len(split["on_disk"]), split["failed"], split["cancelled"]],
          [3, [], False])
    check("exe da cai: danh sach ham bao khop danh sach tren dia",
          split["on_disk"], sorted(r["name"] for r in split["segments"]))
    check("exe da cai: ffprobe doc lai duoc tung doan",
          [r["probe"] > 0.5 for r in split["segments"]], [True] * 3)
    check("exe da cai: cac mei cat khong ho khong choong", split["joints"],
          [0.0, 0.0])
    check("exe da cai: mau cua tung doan la mau cua no trong nguon",
          [g is not None and g < 22.0 for g in split["hue_gaps"]],
          [True, True, True])
    check("exe da cai: status ke ro so doan va cach cat",
          "3 đoạn" in split["status"], True)
    note("do day thanh tien trinh hop thoai cat (px thiet bi, DPR)",
         [split["progress_band_px"], split["progress_dpr"]])
    check("exe da cai: thang tien do cat MON (8px CSS, do tren pixel bundle)",
          [split["progress_band_px"] > 3,
           split["progress_band_px"] <= split["progress_dpr"] * 8 + 3],
          [True, True])
    check("exe da cai: cua so ve co that (khong phai hop den)",
          split["distinct_colors"] > 40, True)
    if os.path.isfile(split["screenshot"]):
        if not os.path.samefile(split["screenshot"], split_shot):
            shutil.copyfile(split["screenshot"], split_shot)
        check("exe da cai: anh hop thoai cat file nam trong scratch",
              os.path.getsize(split_shot) > 2048, True)
    else:
        check("exe da cai: anh hop thoai cat file nam tren dia", False, True)

    # ── 11. Mo .clinq tu dong lenh va tu nhap kep cua Explorer ──
    project_json = os.path.join(ROOT, "scratch", "installed_project.json")
    for stale in (project_json, project_json[:-5] + ".png"):
        if os.path.isfile(stale):
            os.remove(stale)
    # Duong dan co dau cach: do chinh la chuoi Explorer sinh ra khi mo file,
    # nen phai giu nguyen ca khoang trang trong doan "Kiem chung.clinq".
    fixture = os.path.join(tempfile.gettempdir(), "clinging_project_report",
                           "Kiem chung.clinq")
    project_run = subprocess.run([DEST_EXE, "--project-report", project_json,
                                  fixture], timeout=600)
    check("project report exit 0", project_run.returncode, 0)
    with open(project_json, encoding="utf-8") as handle:
        project = json.load(handle)
    note("mo project cua ban da cai",
         {"argv": project["argv_duoc"], "ten": project["ten_du_an"],
          "ti le": project["ti_le"], "clip": project["clips"],
          "thu vien": project["thu_vien"],
          "mau trong anh": project["distinct_colors"]})
    check("exe da cai: mo .clinq tu argv vao thang cua dung phim",
          [project["frozen"], project["mo_duoc"], project["o_editor"],
           project["khoi_dong_tu_home"]], [True, True, True, True])
    check("exe da cai: du an mo ra DUNG clip cua file (start/duration/kieu)",
          project["clips"], project["clips_muon"])
    check("exe da cai: thu vien nap DUNG tai nguyen cua file",
          project["thu_vien"], project["thu_vien_muon"])
    check("exe da cai: ten du an va ti le khung hinh theo file",
          [project["ten_du_an"], project["ti_le"].startswith("9:16"),
           os.path.samefile(project["project_path"], fixture)],
          ["Kiem chung mo tu file", True, True])
    check("exe da cai: duong .clinq khong co that khong mo duoc va giu cua cu",
          [project["duong_gia"]["tra_ve"], project["duong_gia"]["nguyen_hien_tai"]],
          [False, True])
    check("exe da cai: anh bang chung mo project nam tren dia",
          os.path.isfile(project["screenshot"]), True)

    # Du an THAT cua nguoi dung tren may nay — fixture tu sinh chi chung minh
    # duong di, no khong the noi "bai hat 3 phut 41 giay mo ra van con nguyen".
    user_projects = glob.glob(os.path.join(
        os.environ.get("USERPROFILE", ""), "Clinging_Projects", "*", "*.clinq"))
    real_report = {}
    if user_projects:
        real = sorted(user_projects)[0]
        real_json = os.path.join(ROOT, "scratch", "installed_project_user.json")
        for stale in (real_json, real_json[:-5] + ".png"):
            if os.path.isfile(stale):
                os.remove(stale)
        # Ky vong lay tu BYTE goc cua file TRUOC khi probe mo (user_snapshots),
        # khong phai ban ma _auto_save() cua lan mo vua roi ghi de: muon do
        # phai co truoc khi mo, neu khong moi sai lech deu tu an mot.
        pre = json.loads(user_snapshots[real].decode("utf-8"))
        real_run = subprocess.run([DEST_EXE, "--project-report", real_json,
                                   real], timeout=600)
        check("project THAT exit 0", real_run.returncode, 0)
        with open(real_json, encoding="utf-8") as handle:
            real_report = json.load(handle)
        real_meta = pre["project_meta"]
        note("mo du an that cua ban da cai",
             {"file": real, "ten": real_report["ten_du_an"],
              "ti le": real_report["ti_le"],
              "clip": len(real_report["clips"]),
              "thu vien": len(real_report["thu_vien"]),
              "mau trong anh": real_report["distinct_colors"]})
        check("exe da cai: du an that mo vao thang cua dung phim",
              [real_report["frozen"], real_report["mo_duoc"],
               real_report["o_editor"], real_report["khoi_dong_tu_home"]],
              [True, True, True, True])
        check("exe da cai: du an that gi nguyen clip va thu vien cua no",
              [real_report["clips"] == real_report["clips_muon"],
               real_report["thu_vien"] == real_report["thu_vien_muon"],
               len(real_report["clips"]) > 0], [True, True, True])
        # So voi BYTE cua file luc probe BAT DAU, khong phai ban ma chinh
        # _auto_save() cua lan mo vua roi ghi de.
        check("exe da cai: clip mo ra khop byte file TRUOC khi probe mo",
              {k: (v[0], v[1]) for k, v in real_report["clips"].items()},
              {c["clip_id"]: (c["timeline_in"], c["duration"])
               for t in pre["timeline"]["tracks"] for c in t["clips"]})
        check("exe da cai: ten va ti le cua du an that theo chinh file",
              [real_report["ten_du_an"],
               real_report["ti_le"].startswith(real_meta["aspect_ratio"]),
               os.path.samefile(real_report["project_path"], real)],
              [real_meta["project_name"], True, True])
        real_shot = os.path.join(ROOT, "scratch", "installed_project_user.png")
        if os.path.isfile(real_report["screenshot"]):
            if not os.path.samefile(real_report["screenshot"], real_shot):
                shutil.copyfile(real_report["screenshot"], real_shot)
            check("exe da cai: anh du an that nam trong scratch",
                  os.path.getsize(real_shot) > 2048, True)
        else:
            check("exe da cai: anh du an that nam tren dia", False, True)
    else:
        note("du an that", "khong co file .clinq nao trong Clinging_Projects")

    assoc = clinq_association()
    note("lien ket .clinq", assoc)
    check("Explorer: .clinq tro toi Clinging.Project", assoc["progid"],
          "Clinging.Project")
    check("Explorer: lenh mo la exe da cai, co %1 trong ngoac kep",
          assoc["command"], '"%s" "%%1"' % DEST_EXE)

    pids_before = {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                   if (p.info["name"] or "").lower() == "clinging.exe"}
    os.startfile(fixture)
    shell = launch_and_capture(pids_before)
    check("nhap kep .clinq mo duoc cua so that", shell is not None, True)
    if shell:
        launch_shot = os.path.join(ROOT, "scratch", "installed_project_launch.png")
        if shell.get("image") and os.path.isfile(shell["image"]):
            shutil.copyfile(shell["image"], launch_shot)
        import psutil
        try:
            cmdline = " ".join(psutil.Process(shell["pid"]).cmdline())
        except Exception:
            cmdline = ""
        note("dong lenh cua exe do Explorer sinh ra", cmdline)
        check("nhap kep .clinq: duong dan (ca dau cach) toi tay exe",
              fixture.lower() in cmdline.lower(), True)
        terminate_new(pids_before)

    pids_before = {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                   if (p.info["name"] or "").lower() == "clinging.exe"}
    os.startfile(DESKTOP_LNK)
    captured = launch_and_capture(pids_before)
    check("mo app qua shortcut Desktop", captured is not None, True)
    if captured:
        note("cua so app", captured["title"])
        check("process app chay tu thu muc cai dat",
              captured["exe"].lower().startswith(DEST.lower()), True)
        check("anh capture co nhieu mau (khong phai man den)",
              (captured.get("distinct_colors") or 0) > 200, True)
        time.sleep(1.0)
        terminate_new(pids_before)
        note("evidence image", captured.get("image"))

    # Lan cuoi cung: moi cua so probe da dong, nen bat cu _auto_save() nao
    # chay trong 11 lop do deu co the da cham vao du an cua nguoi dung. Tra
    # lai byte goc va do lai — probe do app, khong do ho.
    touched = restore_user_projects(user_snapshots)
    if touched:
        note("du an nguoi dung bi app viet lai trong lan do", touched)
    # Do byte day du nhung in ra log mot bo: log probe khong phai cho de
    # nguyen van ban du an cua nguoi dung trong do.
    check("du an cua nguoi dung van NGUYEN byte sau ca lan do",
          snapshot_user_projects() == user_snapshots, True)

    with open(EVIDENCE, "w", encoding="utf-8") as handle:
        json.dump({"lnk_before": before_lnk, "lnk_after": after_lnk,
                   "installer_mb": installer_mb, "selftest": report,
                   "uninstall_entries": entries, "window": captured,
                   "split": split, "style": style,
                   "user_project_touched": touched,
                   "project": project, "real_project": real_report,
                   "clinq_assoc": assoc,
                   "fails": FAILS}, handle, ensure_ascii=False, indent=2)

    print("\n%s  (%d fail)" % ("ALL PASS" if not FAILS else "FAILED", len(FAILS)))
    for line in FAILS:
        print("  " + line)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
