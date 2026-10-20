"""Doc ban version cua mot .exe qua version.dll — dung API Explorer dung.

    python scratch/exe_version.py [--expect 1.0.1] <duong-dan-exe> [...]

Vi sao phai hoi version.dll: `--version` khong ton tai trong app nay, va doc
thang VS_VERSIONINFO trong .rsrc thi phai tu doi endian va padding. API nay tra
ve dung cai nguoi dung se thay o Properties -> Details, nen no la chung cu that
cho mot lan bump version.

Vi sao phai liet ke VarFileInfo\Translation thay vi hardcode 040904b0: Inno Setup
ghi ban string cua setup.exe duoi khoa 000004b0, nen khoa cu tra ve NULL cho moi
truong. Gate cu in ra "None" het va van tra rc = 0 (None != None la False) — mot
gate luon xanh thi khong dung lam canh. Nay thi thong tin version thieu la do
rieng, va --expect bien mot lan bump thanh mot su that do duoc.
"""

import ctypes
import ctypes.wintypes
import struct
import sys

WANT = ("FileVersion", "ProductVersion", "ProductName", "FileDescription",
        "LegalCopyright")


def _api():
    v = ctypes.windll.version
    v.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p,
                                          ctypes.POINTER(ctypes.wintypes.DWORD)]
    v.GetFileVersionInfoSizeW.restype = ctypes.wintypes.DWORD
    v.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.wintypes.DWORD,
                                      ctypes.wintypes.DWORD, ctypes.c_void_p]
    v.GetFileVersionInfoW.restype = ctypes.wintypes.BOOL
    v.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                 ctypes.POINTER(ctypes.c_void_p),
                                 ctypes.POINTER(ctypes.wintypes.UINT)]
    v.VerQueryValueW.restype = ctypes.wintypes.BOOL
    return v


def read(path):
    """Return {'fixed': 'a.b.c.d', 'strings': {...}, 'keys': [lang keys used]}."""
    v = _api()
    unk = ctypes.wintypes.DWORD()
    n = v.GetFileVersionInfoSizeW(path, ctypes.byref(unk))
    if not n:
        raise SystemExit("GetFileVersionInfoSizeW = 0 (%s)" % path)
    buf = ctypes.create_string_buffer(n)
    if not v.GetFileVersionInfoW(path, 0, n, buf):
        raise SystemExit("GetFileVersionInfoW that bai (%s)" % path)

    def query(sub):
        p = ctypes.c_void_p()
        l = ctypes.wintypes.UINT()
        if not v.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(l)):
            return None, 0
        return p, l.value

    fixed = None
    p, size = query("\\")
    if p is not None and size >= 16:
        raw = ctypes.string_at(p.value, size)
        # VS_FIXEDFILEINFO: MS=(minor, major), LS=(revision, build) theo WORD.
        minor, major, revision, build = struct.unpack("<4H", raw[8:16])
        fixed = "%d.%d.%d.%d" % (major, minor, build, revision)

    translations = []
    p, size = query("\\VarFileInfo\\Translation")
    if p is not None:
        words = struct.unpack("<%dH" % (size // 2), ctypes.string_at(p.value, size))
        translations = list(zip(words[0::2], words[1::2]))

    # Khong tu di qua VS_VERSIONINFO: block StringFileInfo con ca block Var
    # (Van_Flags) xen giua, nen di bo qua sai kieu la cam block ke tiep va moi
    # truong in ra rong. VerQueryValueW theo ten tung String la du.
    out, keys = {}, []
    for lang, cp in translations:
        key = "\\StringFileInfo\\%04x%04x\\" % (lang, cp)
        found = {}
        for name in WANT:
            p = ctypes.c_void_p()
            l = ctypes.wintypes.UINT()
            if v.VerQueryValueW(buf, key + name, ctypes.byref(p), ctypes.byref(l)):
                # Inso pad moi String den chieu dai toi da cua bang (FileVersion
                # cua setup.exe la 20 ky tu trang hoan toan), nen phai rstrip
                # truoc khi so sanh - neu khong thi "--expect" luon do sai.
                val = ctypes.wstring_at(p.value).rstrip()
                if val:
                    found[name] = val
        if found:
            keys.append("%04x%04x" % (lang, cp))
            for name, val in found.items():
                out.setdefault(name, val)
    return {"fixed": fixed, "strings": out, "keys": keys,
            "n_translations": len(translations)}


def check(path, expect=None):
    info = read(path)
    problems = []
    print(path)
    print("   lang keys       %s (%d translation)"
          % (",".join(info["keys"]) or "-", info["n_translations"]))
    print("   %-15s %s" % ("FixedFileInfo", info["fixed"]))
    for k in WANT:
        print("   %-15s %s" % (k, info["strings"].get(k)))
    filev = info["strings"].get("FileVersion")
    prodv = info["strings"].get("ProductVersion")
    if not filev or not prodv:
        problems.append("thong tin version trong .rsrc rong hoac thieu")
    else:
        if filev != prodv:
            problems.append("FileVersion != ProductVersion")
        if info["fixed"] and not info["fixed"].startswith(filev):
            problems.append("FixedFileInfo %s khong khop FileVersion %s"
                            % (info["fixed"], filev))
    if expect:
        got = filev or info["fixed"] or ""
        if not got.startswith(expect):
            problems.append("ky vong %s, nhan duoc %s" % (expect, got or "khong co gi"))
    for p in problems:
        print("   LECH: %s" % p)
    return 1 if problems else 0


def main(argv):
    expect = None
    if argv[:1] == ["--expect"]:
        if len(argv) < 3:
            raise SystemExit(__doc__)
        expect, argv = argv[1], argv[2:]
    if not argv:
        raise SystemExit(__doc__)
    rc = 0
    for path in argv:
        rc = max(rc, check(path, expect))
    if rc == 0:
        print("GATE: moi file co version" + (" = %s" % expect if expect else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
