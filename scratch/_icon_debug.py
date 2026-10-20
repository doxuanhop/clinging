import ctypes, struct, sys
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
DATAFILE, IMAGE = 0x1, 0x20
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]

ProcT = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                           ctypes.c_void_p, wintypes.LPARAM)
k32.EnumResourceTypesW.argtypes = [wintypes.HMODULE, ProcT, wintypes.LPARAM]
k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, wintypes.LPCWSTR, ProcT,
                                   wintypes.LPARAM]

def make(i):
    return ctypes.cast(i, wintypes.LPCWSTR)

def dump(path, flags):
    m = k32.LoadLibraryExW(path, None, flags)
    if not m:
        print("  LoadLibraryExW fail rc=%d" % ctypes.get_last_error()); return
    types = []
    def tcb(_m, _n, name, _p):
        v = ctypes.cast(name, ctypes.c_void_p).value
        types.append(int(v) if (v or 0) < 0x10000 else str(ctypes.wstring_at(name)))
        return True
    r1 = k32.EnumResourceTypesW(m, ProcT(tcb), 0)
    print("  flags=0x%x enumTypes=%d types=%s" % (flags, r1, sorted(set(types))))
    for t in (3, 14, 24):
        ids = []
        def ncb(_m, _ty, name, _p):
            v = ctypes.cast(name, ctypes.c_void_p).value
            ids.append(int(v) if (v or 0) < 0x10000 else str(ctypes.wstring_at(name)))
            return True
        r = k32.EnumResourceNamesW(m, make(t), ProcT(ncb), 0)
        print("    type %d enum=%d ids=%s" % (t, r, sorted(ids, key=str)[:12]))
    k32.FreeLibrary(m)

for p in sys.argv[1:]:
    print(p)
    for f in (DATAFILE, DATAFILE | IMAGE):
        dump(p, f)
