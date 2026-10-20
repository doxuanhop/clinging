
import json, os, sys, time

REPO = r"D:\Programming\clinging"
mode = sys.argv[1]
sys.path.insert(0, REPO)


def ws_kib():
    import ctypes, ctypes.wintypes as wt
    class C(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD),
                    ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]
    # WinDLL rieng: main._working_set_kib da gan argtypes cho
    # K32GetProcessMemoryInfo tren instance toan cuc bang cau truc cua no.
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(C), wt.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wt.BOOL
    c = C(); c.cb = ctypes.sizeof(c)
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(),
                                       ctypes.byref(c), c.cb):
        raise SystemExit("K32GetProcessMemoryInfo tra ve 0 (tem RAM hong)")
    return int(c.WorkingSetSize // 1024), int(c.PrivateUsage // 1024)


import main

# PRE-AMB GIONG HET NHAU MOI CHE DO. Do rieng: `import widgets.fontawesome` la
# thu nhap `PySide6.QtGui` DAU TIEN tien vao process, no keo theo
# `PySide6.support.signature.*` + `shibokensupport` = 0,537 s (do bang
# scratch/_qtgui_import_cost.py). De no o TRONG hay NGOAI cua so boot thi
# wall-clock cua hai mode lech nhau hang 0,5 s ma khong he do icon — chinh
# probe nay tung bao "instrumented nhanh hon baseline 0,74 s" vi ly do do.
# Trong app that no nam trong boot; o day moi mode deu tra truoc de cua so boot
# cua ba ben so sanh duoc voi nhau. So do tuyen bo chinh cua probe la dong ho
# seam ben duoi, khong bi cai nay anh huong.
import widgets.fontawesome as fa

attribution = {}

if mode == "instrumented":
    # _render/_load nam BEN TRONG pixmap/paint nen chung khong duoc cong vao
    # tong; do chung rieng de biet tien nao la nap font, nao la ve glyph.
    acc = {}
    hits = {}

    def wrap(holder, attr, key):
        original = getattr(holder, attr)

        def timed(*a, **k):
            t = time.perf_counter()
            try:
                return original(*a, **k)
            finally:
                acc[key] = acc.get(key, 0.0) + (time.perf_counter() - t)
                hits[key] = hits.get(key, 0) + 1
        setattr(holder, attr, timed)

    wrap(fa, "icon", "icon")
    wrap(fa, "_render", "render")
    wrap(fa, "_load", "load")
    eng = fa._GlyphEngine
    for meth in ("pixmap", "paint", "iconSize", "clone"):
        wrap(eng, meth, "engine." + meth)

    def snapshot_attribution():
        top = {k: v for k, v in acc.items() if not k.startswith(("render", "load"))}
        return {"seam_total_s": round(sum(top.values()), 4),
                "seam_import_s": 0.0,
                "render_s": round(acc.get("render", 0.0), 4),
                "load_s": round(acc.get("load", 0.0), 4),
                "counts": dict(hits)}

elif mode == "stub_renderer":
    # Que module ve glyph: moi icon tra ve QIcon rong. `from widgets import
    # fontawesome` lay thuoc tinh cua package, nen phai gan ca hai noi.
    import types
    import widgets
    from PySide6.QtGui import QIcon
    fake = types.ModuleType("widgets.fontawesome")
    fake.icon = lambda name, *a, **k: QIcon()
    fake.asset_root = lambda: ""
    sys.modules["widgets.fontawesome"] = fake
    widgets.fontawesome = fake
elif mode == "force_qtawesome":
    # Chay lai duong CU qua DUNG mot seam. KHONG duoc `import qtawesome` o day:
    # gia that lon nhat cua no nam trong luc import, ma import lai dien ra TRONG
    # boot that. De nam duoc no trong cua so boot, ham gia phai import ngay lan
    # goi dau tien va tu do dong ho cua chinh no.
    qta_acc = {"import_s": 0.0, "icon_s": 0.0, "icon_calls": 0}

    def old_icon(name, color="#FFFFFF", *a, **k):
        if "qtawesome" not in sys.modules:
            t = time.perf_counter()
            import qtawesome
            qta_acc["import_s"] += time.perf_counter() - t
        else:
            import qtawesome
        t = time.perf_counter()
        try:
            return qtawesome.icon(name, color=color)
        finally:
            qta_acc["icon_s"] += time.perf_counter() - t
            qta_acc["icon_calls"] += 1

    fa.icon = old_icon

    def snapshot_attribution():
        return {"seam_total_s": round(qta_acc["import_s"] + qta_acc["icon_s"], 4),
                "seam_import_s": round(qta_acc["import_s"], 4),
                "qta_icon_s": round(qta_acc["icon_s"], 4),
                "counts": {"qtawesome.icon": qta_acc["icon_calls"]}}

t0 = time.perf_counter()
app, controller = main._boot()
boot = time.perf_counter() - t0
# Lay so do NGAY sau luc _boot tro ve, TRUOC vong processEvents duoi day — neu
# khong tong seam tinh ca nhung lan ve icon sau khi cua so da hien.
if mode in ("instrumented", "force_qtawesome"):
    attribution = snapshot_attribution()
until = time.time() + 1.2
while time.time() < until and not controller.isVisible():
    app.processEvents()
    time.sleep(0.02)

from PySide6.QtWidgets import QWidget
from widgets.common import icon_pixmap

fp = {}
for w in controller.findChildren(QWidget):
    fp[type(w).__name__] = fp.get(type(w).__name__, 0) + 1

grid = getattr(controller.home_page, "recent_grid", None)
cards = 0
for i in range(grid.count() if grid else 0):
    item = grid.itemAt(i)
    if type(item.widget()).__name__ == "RecentProjectCard":
        cards += 1

# Hash bo cuc: stub che icon thanh QIcon rong nen nut mat sizeHint va layout
# dich theo. Do de khong ai doc lech wall-clock cua stub nhu "chi phi icon con lai".
import hashlib
cells = sorted("%s:%d,%d,%dx%d" % (type(w).__name__, w.x(), w.y(),
                                   w.width(), w.height())
               for w in controller.findChildren(QWidget))
geo_hash = hashlib.sha1("\n".join(cells).encode("utf-8")).hexdigest()[:12]

SAMPLE = ["fa6s.play", "fa6s.plus", "fa6s.download", "fa6s.trash", "fa6s.pen",
          "fa6s.xmark", "fa6s.minus", "fa6s.square", "fa6s.sliders",
          "fa6s.folder-open"]
painted = 0
for nm in SAMPLE:
    pm = icon_pixmap(nm, 16)
    img = pm.toImage()
    solid = sum(1 for y in range(img.height()) for x in range(img.width())
                if (img.pixel(x, y) >> 24) & 0xFF)
    if solid / float(max(1, img.width() * img.height())) > 0.02:
        painted += 1

shot = None
if mode == "baseline":
    shot = r"D:\Programming\clinging\scratch\boot_low_spec.png"
    controller.grab().save(shot)

ws, priv = ws_kib()
out = {"mode": mode, "boot_s": round(boot, 3),
       "window_exposed": bool(controller.isVisible()),
       "ws_kib": ws, "private_kib": priv,
       "ws_prod_kib": main._working_set_kib(),
       "qtawesome_loaded": "qtawesome" in sys.modules,
       "qtpy_loaded": "qtpy" in sys.modules,
       "qtopenGL_loaded": "PySide6.QtOpenGL" in sys.modules,
       "fontawesome_loaded": "widgets.fontawesome" in sys.modules,
       "painted": painted, "sampled": len(SAMPLE),
       "cards": cards,
       "geo_hash": geo_hash, "attribution": attribution,
       "widgets": sum(fp.values()), "fingerprint": fp, "shot": shot}
app.processEvents()
controller.close()
app.quit()
print("RESULT " + json.dumps(out, ensure_ascii=False))
