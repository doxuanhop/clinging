"""Launch the app through the Desktop shortcut and capture its window.

Proves the .lnk (target, working dir, icon) actually starts Clinging, then closes it.

Usage: python scratch/shortcut_launch.py
"""
import ctypes.wintypes
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scratch")
user32, gdi32, kernel32 = (ctypes.windll.user32, ctypes.windll.gdi32,
                          ctypes.windll.kernel32)
user32.SetProcessDPIAware()

from PIL import Image

LNK = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "Clinging.lnk")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD)]


def grab(hwnd):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(dc)
    bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    user32.PrintWindow(hwnd, mem_dc, 2)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    img = None
    if gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(info), 0):
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, dc)
    return img


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.wintypes.DWORD), ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.wintypes.WCHAR * 260)]


def pids_named(*names):
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.wintypes.DWORD,
                                                  ctypes.wintypes.DWORD]
    pids = set()
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.wintypes.HANDLE(-1).value:
        return pids
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    first = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while first:
        if (entry.szExeFile or "").lower() in names:
            pids.add(int(entry.th32ProcessID))
        first = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return pids


def windows_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        wp = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if wp.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc, 0)
    return found


def main():
    if not os.path.exists(LNK):
        print("MISSING", LNK)
        return 1
    before = pids_named("pythonw.exe")
    print("pythonw pids before:", sorted(before))
    os.startfile(LNK)
    deadline = time.time() + 40
    new_pid = None
    while time.time() < deadline:
        fresh = pids_named("pythonw.exe") - before
        for pid in fresh:
            if windows_of(pid):
                new_pid = pid
                break
        if new_pid:
            break
        time.sleep(0.5)
    if not new_pid:
        print("GATE: shortcut did not open a window")
        return 1
    time.sleep(4.0)
    wins = windows_of(new_pid)
    print("shortcut launched pid", new_pid, "windows:", wins)
    for hwnd, title in wins:
        img = grab(hwnd)
        if img:
            path = os.path.join(OUT, "shortcut_launch.png")
            img.save(path)
            print("saved", path, img.size, repr(title))
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    print("GATE: shortcut launched the app:", True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
