"""Launch the extracted Qt reference app and capture its windows.

Runs reference/main.py as a child process, waits for its top-level windows,
captures each with PrintWindow, then shuts the child down.

Usage: python scratch/qt_ref_shot.py [page]
"""
import ctypes.wintypes
import ctypes
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = ROOT
OUT = os.path.join(ROOT, "scratch")
PY = sys.executable

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.SetProcessDPIAware()

from PIL import Image


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD)]


def print_window(hwnd):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < 40 or h < 40:
        return None
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
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(info), 0)
    img = None
    if got:
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, dc)
    return img


def windows_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        wp = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if wp.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc, 0)
    return found


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "home"
    proc = subprocess.Popen([PY, "main.py"], cwd=REF,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        deadline = time.time() + 25
        wins = []
        while time.time() < deadline:
            wins = windows_of(proc.pid)
            if wins:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        if proc.poll() is not None:
            print("CHILD EXITED rc=%s" % proc.returncode)
            print(proc.stdout.read().decode("utf-8", "replace")[-4000:])
            return 1
        time.sleep(3.0)
        wins = windows_of(proc.pid)
        print("windows:", [(h, t) for h, t in wins])
        for hwnd, title in wins:
            img = print_window(hwnd)
            if img is None:
                print("no pixels for", hwnd, title)
                continue
            path = os.path.join(OUT, "qt_ref_%s_%d.png" % (tag, hwnd))
            img.save(path)
            print("saved", path, img.size, repr(title))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
