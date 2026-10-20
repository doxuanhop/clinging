"""Ask the Windows shell what icon the Desktop shortcut really renders.

Uses SHGetFileInfo on Clinging.lnk (the same call Explorer uses), converts the
returned HICON to a PNG, and compares it against the icon embedded in the file
the shortcut actually points at.

Why compare against the EXE's own resource and not against assets/app-icon:
Explorer answers from iconcache.db, and that cache is keyed by path. After an
in-place upgrade the path never changes, so a stale cache keeps handing out the
previous artwork even though the PE on disk is new — the two readers disagree
and only one of them is what the user sees. Comparing the shell's answer with
the exe's embedded 32x32 therefore tests the cache, while comparing it with the
.ico would only re-state the source and prove nothing.

Threshold is measured, not guessed: the same pixels are also scored against a
180-degree turn of the reference. A detector that cannot tell those apart is
not looking at the icon.

Usage: python scratch/desktop_icon_probe.py
"""
import ctypes.wintypes
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scratch")
LNK = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "Clinging.lnk")
sys.path.insert(0, OUT)

shell32, user32, gdi32 = ctypes.windll.shell32, ctypes.windll.user32, ctypes.windll.gdi32

from PIL import Image

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SYSICONINDEX = 0x000004000


class SHFILEINFO(ctypes.Structure):
    _fields_ = [("hIcon", ctypes.wintypes.HICON), ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_uint), ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", ctypes.wintypes.BOOL),
                ("xHotspot", ctypes.wintypes.DWORD), ("yHotspot", ctypes.wintypes.DWORD),
                ("hbmMask", ctypes.wintypes.HBITMAP), ("hbmColor", ctypes.wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", ctypes.wintypes.WORD), ("bmBitsPixel", ctypes.wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD)]


def dib_bits(hdc, hbm):
    b = BITMAP()
    gdi32.GetObjectW(hbm, ctypes.sizeof(b), ctypes.byref(b))
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = b.bmWidth, -b.bmHeight
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(b.bmWidth * b.bmHeight * 4)
    got = gdi32.GetDIBits(hdc, hbm, 0, b.bmHeight, buf, ctypes.byref(info), 0)
    if not got:
        return None
    return Image.frombuffer("RGBA", (b.bmWidth, b.bmHeight), buf, "raw", "BGRA", 0, 1)


def icon_to_pil(hicon):
    user32.GetIconInfo.argtypes = [ctypes.wintypes.HICON, ctypes.POINTER(ICONINFO)]
    gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
    gdi32.GetObjectW.argtypes = [ctypes.wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HBITMAP,
                                ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.wintypes.UINT]
    ii = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    dc = user32.GetDC(0)
    color = mask = None
    try:
        if ii.hbmColor:
            color = dib_bits(dc, ii.hbmColor)
        if ii.hbmMask:
            mask = dib_bits(dc, ii.hbmMask)
    finally:
        user32.ReleaseDC(0, dc)
        for h in (ii.hbmColor, ii.hbmMask):
            if h:
                gdi32.DeleteObject(h)
    if color is None:
        return None
    img = color.convert("RGBA")
    if mask is not None and mask.size == img.size:
        m = mask.convert("L").point(lambda v: 0 if v > 127 else 255)
        img.putalpha(m)
    return img


def main():
    import numpy as np
    if not os.path.exists(LNK):
        print("MISSING", LNK)
        return 1
    # .lnk là shell link: SHGetFileInfo cần COM được khởi tạo trong process này.
    ctypes.windll.ole32.CoInitialize(None)
    sfi = SHFILEINFO()
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    res = shell32.SHGetFileInfoW(LNK, 0, ctypes.byref(sfi), ctypes.sizeof(sfi),
                                 SHGFI_ICON | SHGFI_LARGEICON)
    if not res or not sfi.hIcon:
        print("GATE FAIL: shell returned no icon for the shortcut (res=%s err=%s)"
              % (res, ctypes.GetLastError()))
        return 1
    img = icon_to_pil(sfi.hIcon)
    user32.DestroyIcon(sfi.hIcon)
    if img is None:
        print("GATE FAIL: could not read the icon pixels")
        return 1
    path = os.path.join(OUT, "desktop_icon_probe.png")
    img.resize((256, 256), Image.Resampling.NEAREST).save(path)
    print("shell icon for Clinging.lnk:", img.size, "mode", img.mode)
    print("saved", path)

    from installed_icon_match import group_images, decode
    from msi_install_probe import lnk_target
    target = None
    try:
        target = lnk_target(LNK)
    except Exception as exc:
        print("GATE FAIL: không đọc được đích của .lnk: %s" % exc)
        return 1
    print("shortcut tro toi: %s" % target)
    _gid, images, _icons = group_images(target)
    ref = next(((w, decode(pl)) for w, _h, _s, _n, pl in images
                if w == img.width), None)
    if ref is None:
        print("GATE FAIL: exe không mang RT_ICON nào cỡ %dpx" % img.width)
        return 1
    b = np.asarray(ref[1], dtype=np.int16)

    # Explorer tô phần trong suốt bằng ảnh nền Desktop, nên chỉ những pixel mà
    # chính icon mới opaque mới so sánh được; góc dưới-trái bị badge mũi tên
    # shortcut che lên.
    a = np.asarray(img.convert("RGBA"), dtype=np.int16)
    opaque = b[:, :, 3] >= 250
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    cut = a.shape[1] * 2 // 3
    opaque &= ~((yy >= cut) & (xx < cut))
    n = int(opaque.sum())
    if n < a.shape[0] * a.shape[1] // 2:
        print("GATE FAIL: chỉ %d/%d pixel opaque, không đủ để so"
              % (n, a.shape[0] * a.shape[1]))
        return 1

    def score(other):
        d = np.abs(a[:, :, :3] - other[:, :, :3]).sum(axis=2)
        return float(d[opaque].mean()), float((d[opaque] < 60).mean())

    mean, frac = score(b)
    rot = np.rot90(b, 2)
    rmean, rfrac = score(rot)
    print("vs icon trong exe  : mean %.1f  khop %.3f cua %d px" % (mean, frac, n))
    print("vs ban quay 180 do: mean %.1f  khop %.3f" % (rmean, rfrac))
    ok = mean <= 40.0 and frac >= 0.75 and rmean > mean + 20.0
    print("GATE: desktop shortcut renders the app icon: %s" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
