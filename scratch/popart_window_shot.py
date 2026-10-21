"""Chup cua so app DA CAI (Inno 1.0.3) luc mo du an Pop Art, luu vao assets/uiux.

Duong THAT: Clinging.exe <duong dan .clinq> -> cua so that -> bat anh.
Khong dung ban ve lai nao (grabWidget/self-render): anh nay phai la dieu
nguoi dung nhin thay tren man hinh.

Cua:
  1. tim duoc cua so cua DUNG pid da khoi dong (khong phai cua cua cai don)
  2. anh bat duoc khong den (mean luma > 8) - in ra duong bat da dung
  3. vung preview co noi dung (> 400 mau khac nhau trong 320x180 o giua)
  4. hai lan chup cach nhau 0,8 s gan nhu giong het (<= 1%, khong bat mid-paint)
  5. cua so nam tron trong man hinh (khong bi cat khi grab theo bbox)
  6. file PNG ghi ra duoc, mo lai doc duoc dung kich thuoc

Chay:
    python scratch/popart_window_shot.py
    python scratch/popart_window_shot.py --selfcheck   # phan chung: duong dan exe sai
    python scratch/popart_window_shot.py --pixels      # phan chung: cua anh do vi dung ly do
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PNG = os.path.join(ROOT, "assets", "uiux", "pop-art-project.png")
EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Clinging", "Clinging.exe")
CLINQ = os.path.join(os.environ.get("USERPROFILE", ""), "Clinging_Projects",
                     "Pop Art Demo", "Pop Art Demo.clinq")

WM_CLOSE = 0x0010
SW_RESTORE = 9
HWND_TOPMOST = wt.HWND(-1)
HWND_NOTOPMOST = wt.HWND(-2)
SWP_SHOWWINDOW, SWP_FRAMECHANGED = 0x0040, 0x0020
SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0004
DWMWA_EXTENDED_FRAME_BOUNDS = 9
WANT_W, WANT_H = 1500, 900          # du cho 1920x1080 ma van fit tren laptop 1366x768

ctypes.windll.user32.SetProcessDPIAware()
user32, gdi32, dwmapi = (ctypes.windll.user32, ctypes.windll.gdi32,
                         ctypes.windll.dwmapi)

from PIL import Image, ImageChops, ImageGrab, ImageStat


def plain(s):
    """Bo dau: tieu de co dau, so sanh bang ASCII cho chac."""
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def frame_bounds(hwnd):
    """Phan cua so THINH duoc (khong tinh vien do cua GetWindowRect)."""
    r = wt.RECT()
    ok = dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                      ctypes.byref(r), ctypes.sizeof(r))
    if ok != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def place_top(hwnd, w, h):
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(wt.HWND(hwnd), HWND_TOPMOST, 0, 0, w, h,
                        SWP_SHOWWINDOW | SWP_FRAMECHANGED)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)


def grab_screen(r):
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom),
                          all_screens=True).convert("RGB")


def print_window(hwnd):
    """PrintWindow(PW_RENDERFULLCONTENT). Tra (anh, ma loi, alpha lon nhat).

    Win10 19045 + cua FramelessWindowHint: do rc va alpha de biet no that bai
    o buoc ve hay o buoc doc mau (alpha=0 thi mau bi DWM an).
    """
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < 64 or h < 64:
        return None, "cua %dx%d - khong phai cua chinh" % (w, h), 0
    dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(dc)
    bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    rc = user32.PrintWindow(wt.HWND(hwnd), mem_dc, 2)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, dc)
    rgba = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    amax = rgba.getchannel("A").getextrema()[1]
    if not got:
        return None, "GetDIBits tra %d" % got, amax
    return rgba.convert("RGB"), "rc=%d getdibits=%d" % (rc, got), amax


def capture(hwnd):
    """Thu PrintWindow truoc (khong phu thuoc vao oc lap), roi moi grab man hinh."""
    img, why, amax = print_window(hwnd)
    if img is not None and ImageStat.Stat(img.convert("L")).mean[0] > 8.0:
        return img, "PrintWindow (%s)" % why
    g = grab_screen(frame_bounds(hwnd))
    return g, "man hinh (%s; PrintWindow cho luma %.1f, alpha_max %d)" % (
        why, ImageStat.Stat(img.convert("L")).mean[0] if img else -1.0, amax)


def mean_luma(img):
    return ImageStat.Stat(img.convert("L")).mean[0]


def preview_box(img):
    cx, cy = img.width // 2, img.height // 2
    return img.crop((max(0, cx - 160), max(0, cy - 90),
                     min(img.width, cx + 160), min(img.height, cy + 90)))


def n_colors(img, step=37):
    return len(set(list(img.getdata())[::step]))


def pct_moved(a, b):
    """% dieu lech thay doi ro (>8 luma) giua hai lan chup."""
    if a.size != b.size:
        return 100.0
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 8 else 0)
    return ImageStat.Stat(d).mean[0] / 255.0 * 100.0


def gate_frame(a, b):
    """Cua 2+3+4 tren hai anh. Tra (so fail, so do) - dung ca cho phan chung."""
    p_luma, p_colors = mean_luma(preview_box(a)), n_colors(preview_box(a))
    moved = pct_moved(a, b)
    fails = []
    if mean_luma(a) <= 8.0:
        fails.append("khung den (luma %.1f)" % mean_luma(a))
    if p_colors < 400:
        fails.append("preview khong co noi dung (%d mau)" % p_colors)
    if moved > 1.0:
        fails.append("hai lan chup lech %.2f%% - dang giua ve" % moved)
    return fails, dict(luma=mean_luma(a), p_luma=p_luma, p_colors=p_colors,
                       moved=moved, size=a.size)


def find_window(pid, deadline_s):
    """Cho toi khi cua so cua DUNG pid nay lo ra."""
    Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    box = {}

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        got = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(got))
        if got.value != pid:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        if "clinging" in plain(title.value):
            box.update(hwnd=hwnd, title=title.value)
            return False
        return True

    end = time.time() + deadline_s
    while time.time() < end and not box:
        user32.EnumWindows(Proc(cb), 0)
        if not box:
            time.sleep(0.25)
    return box.get("hwnd"), box.get("title")


def run(exe, clinq, out_png):
    for label, path in (("exe", exe), ("du an", clinq)):
        if not os.path.exists(path):
            print("GATE FAIL: %s khong ton tai: %s" % (label, path))
            return 1
    sw, sh = screen_size()
    print("man hinh: %dx%d" % (sw, sh))
    proc = subprocess.Popen([exe, clinq], cwd=os.path.dirname(exe))
    hwnd = None
    fails = []
    try:
        hwnd, title = find_window(proc.pid, 30.0)
        if not hwnd:
            print("GATE FAIL: khong thay cua so Clinging cua pid %d trong 30 s" % proc.pid)
            return 1
        print("cua so: pid=%d title=%r" % (proc.pid, title))
        place_top(hwnd, min(WANT_W, sw), min(WANT_H, sh))
        # Cho Qt nap du an + ve xong frame dau; chi chap nhan anh khi no sang.
        a = how = None
        end = time.time() + 25.0
        while time.time() < end:
            time.sleep(1.5)
            cand, method = capture(hwnd)
            if mean_luma(cand) > 8.0:
                a, how = cand, method
                break
        if a is None:
            print("GATE FAIL: 25 s van khong co frame sang (%s)" % how)
            return 1
        r = frame_bounds(hwnd)
        time.sleep(0.8)
        b, _ = capture(hwnd)
        fails, m = gate_frame(a, b)
        inside = (r.left >= 0 and r.top >= 0 and r.right <= sw and r.bottom <= sh)
        print("bat anh: %s" % how)
        print("bbox cua so: %d,%d-%d,%d  tron_man_hinh=%s" % (
            r.left, r.top, r.right, r.bottom, inside))
        print("kich thuoc %dx%d  luma %.1f  preview %d mau  lech hai lan %.2f%%"
              % (m["size"][0], m["size"][1], m["luma"], m["p_colors"], m["moved"]))
        if not inside:
            fails.append("cua so %d,%d-%d,%d tron ra ngoai man hinh %dx%d"
                         % (r.left, r.top, r.right, r.bottom, sw, sh))
        if not fails:
            os.makedirs(os.path.dirname(out_png), exist_ok=True)
            a.save(out_png, optimize=True)
            back = Image.open(out_png)
            if back.size != a.size:
                fails.append("PNG mo lai %s != %s" % (back.size, a.size))
            else:
                print("anh: %s (%d bytes, %dx%d)"
                      % (out_png, os.path.getsize(out_png), a.width, a.height))
    finally:
        if hwnd:
            user32.SetWindowPos(wt.HWND(hwnd), HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE)
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    for f in fails:
        print("GATE FAIL:", f)
    print("ALL PASS" if not fails else "CO FAIL: %d" % len(fails))
    return 0 if not fails else 1


def pixels_selfcheck(png):
    """Phan chung cho cua 2+3+4: khung den phai DO, anh that phai XANH,
    va boi den len preview phai DO vi dung ly do (mat noi dung).
    """
    fails = []
    black = Image.new("RGB", (WANT_W, WANT_H), (5, 5, 8))
    red, m = gate_frame(black, black)
    print("[A] khung den    -> %d fail: %s" % (len(red), red))
    if not red:
        fails.append("cua khong phat hien duoc khung den - cua gia")
    if not os.path.exists(png):
        print("[B] chua co anh -> bo qua")
        return 1 if fails else 0
    real = Image.open(png).convert("RGB")
    red2, m2 = gate_frame(real, real.copy())
    print("[B] anh that     -> %d fail  (%dx%d luma %.1f preview %d mau)"
          % (len(red2), m2["size"][0], m2["size"][1], m2["luma"], m2["p_colors"]))
    if red2:
        fails.append("anh dang luu khong qua cua cua chinh: %s" % red2)
    tampered = real.copy()
    tampered.paste((6, 6, 6), (tampered.width // 2 - 160, tampered.height // 2 - 90,
                               tampered.width // 2 + 160, tampered.height // 2 + 90))
    red3, m3 = gate_frame(tampered, tampered.copy())
    print("[C] boi preview  -> %d fail: %s (%d mau)" % (len(red3), red3, m3["p_colors"]))
    if not any("preview" in f for f in red3):
        fails.append("cua preview khong do khi bi xoa noi dung")
    for f in fails:
        print("GATE FAIL:", f)
    print("ALL PASS (phan chung anh)" if not fails else "CO FAIL: %d" % len(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        # Phan chung: gate phai CHET khi duong dan vao khong ton tai, khong in ALL PASS
        sys.exit(run(os.path.join(ROOT, "khong-co-exe-nay.exe"), CLINQ, OUT_PNG))
    if "--pixels" in sys.argv:
        sys.exit(pixels_selfcheck(OUT_PNG))
    sys.exit(run(EXE, CLINQ, OUT_PNG))
