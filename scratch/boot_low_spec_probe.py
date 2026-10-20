"""Do chi phi khoi dong cua bo ve icon Font Awesome — tren duong boot THAT.

    python scratch/boot_low_spec_probe.py

Truoc day probe nay so sanh "baseline (qtawesome)" voi "stub qtawesome" de ket
luan qtawesome dat. Sau khi `widgets/fontawesome.py` vao thay cho, so sanh do
vo nghia: qtawesome khong con trong duong boot nua. Bon hoi con lai:

  baseline         boot that, ve icon that, khong thep bam.
  instrumented     y het baseline + thep bam len tung ham cua bo ve glyph.
                   Cho so DO TRUC TIEP: bao nhieu giay trong cua so boot la do
                   code cua chung ta (nap font, ve glyph, goi engine).
  stub_renderer    `icon()` tra QIcon rong. GIU LAI DE DO BAO CUC, khong phai
                   de do thoi gian: QIcon rong mat sizeHint cua icon nen nut
                   bo chon va layout dich theo (hash bo cuc khac baseline).
                   Lech wall-clock cua no VA boot khong phai chi phi icon.
  force_qtawesome  `fa.icon` goi lai qtawesome, import dien ra TRONG boot.
                   Thep bam do truc tiep phan cua qtawesome trong cung cua so
                   boot -> phep so sanh "swap tiet kiem gi" la hai tong do bang
                   cung mot kieu dong ho, khong phai hai wall-clock cua hai
                   process.

Vi sao phai do bang dong ho ben trong, khong phai bang wall-clock: may thu
HDD 5400 rpm va lan chay dau cua mot chuoi doc ~600 file .py cham hon cac lan
sau gan hai lan (do trong mot lot chay: 2,1-3,2 s -> 1,1-1,5 s, moi che do cung
xuong duoc). Lech A-B cua hai process vi vay do ca "cache file" chu khong
rieng code. Wall-clock van in ra va van co gate nho (loai ben kiem khong duoi
0,15 s), nhung tuyen bo lon nhat nam tren so do truc tiep.

Mot boot "nhanh" vi icon TRONG thi khong duoc tinh la thanh cong: moi che do
phai ve du 10/10 icon mau (`painted`) va 2 card du an gan day (`cards`), cay
widget (`fingerprint`) giong het nhau, va bo cuc cua ba che do co icon that
(baseline / instrumented / force_qtawesome) phai TRUNG nhau mot hash.

Probe KHONG dong cham du lieu nguoi dung: moi lan chay mot sandbox tam cho
APPDATA/USERPROFILE/TEMP, seed san 2 du an con file + 1 du an mat duong dan.
"""
import json
import os
import statistics
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(REPO, "scratch", "_boot_low_spec_child.py")
OUT = os.path.join(REPO, "scratch", "boot_low_spec.json")
SHOT = os.path.join(REPO, "scratch", "boot_low_spec.png")
RUNS = 5           # vong do sau khi may da "am"
WARMUP = 3         # lan chay bo qua: doc lanh 600 file tren HDD

CHILD_SRC = r'''
import json, os, sys, time

REPO = r"__REPO__"
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
    shot = r"__SHOT__"
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
'''


def sandbox():
    """Mot thu muc du lieu NGUOI DUNG gia cho mot lan chay.

    Ly do khong phai "sach se" ma la an toan: app that co the ghi settings.json
    va thu muc autosave ~/.clinqing cua chinh nguoi dung khi mo/roi cua so.
    Seed 2 du an con file + 1 du an mat duong dan de boot di qua dung duong
    RecentProjectCard (noi tao icon that), va moi che do bat dau tu cung mot
    trang thai.
    """
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix="clinq_boot_")
    appdata = os.path.join(root, "Roaming")
    home = os.path.join(root, "home")
    data = os.path.join(appdata, "Clinging")
    os.makedirs(data)
    os.makedirs(home)
    live_a = os.path.join(root, "A.clinq")
    live_b = os.path.join(root, "B.clinq")
    gone = os.path.join(root, "Offline Drive", "Mat dien.clinq")
    for path in (live_a, live_b):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{}")
    with open(os.path.join(data, "recent_projects.json"), "w",
              encoding="utf-8") as handle:
        json.dump([live_a, gone, live_b], handle, indent=2, ensure_ascii=False)
    tmp = os.path.join(root, "tmp")
    os.makedirs(tmp)
    env = dict(os.environ, APPDATA=appdata, USERPROFILE=home, TEMP=tmp, TMP=tmp,
               PYTHONIOENCODING="utf-8")
    return root, env


def run(mode):
    import shutil
    root, env = sandbox()
    try:
        with open(CHILD, "w", encoding="utf-8") as handle:
            handle.write(CHILD_SRC.replace("__REPO__", REPO).replace("__SHOT__", SHOT))
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, CHILD, mode], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              cwd=REPO, timeout=300, env=env)
        line = next((l for l in proc.stdout.splitlines()
                     if l.startswith("RESULT ")), None)
        if line is None:
            return {"mode": mode, "error": (proc.stderr or "")[-600:]}
        row = json.loads(line[len("RESULT "):])
        row["wall_s"] = round(time.perf_counter() - started, 3)
        return row
    finally:
        shutil.rmtree(root, ignore_errors=True)


def med(rows, key):
    vals = [r[key] for r in rows if key in r]
    return round(statistics.median(vals), 3) if vals else None


def seam(rows):
    vals = [(r.get("attribution") or {}).get("seam_total_s") for r in rows]
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 4) if vals else None


def brief(row):
    att = row.get("attribution") or {}
    return ("boot %5.3f s  seam %6s s  cards %s  geo %s  painted %s/%s  "
            "qta=%s qtpy=%s gl=%s"
            % (row.get("boot_s", -1), att.get("seam_total_s"), row.get("cards"),
               row.get("geo_hash"), row.get("painted"), row.get("sampled"),
               row.get("qtawesome_loaded"), row.get("qtpy_loaded"),
               row.get("qtopenGL_loaded")))


def main():
    modes = ("baseline", "instrumented", "stub_renderer", "force_qtawesome")
    data = {"runs": RUNS, "warmup": WARMUP, "python": sys.version.split()[0],
            "modes": {m: [] for m in modes}}

    # WARMUP: tren HDD nay, vi tri cua mot lan chay trong lot quyet dinh hon ca
    # ma nguon. Bo qua WARMUP lan boot dau tien de lop doc .py/.ttf da vao cache
    # truoc khi so nao duoc dung so sanh. Cac so do warmup van in ra de nhin
    # thay do troi, khong giu lai trong JSON.
    warm = []
    for i in range(WARMUP):
        row = run("baseline")
        warm.append(row)
        print("[warmup %d][baseline    ] %s" % (i, brief(row)))
    data["warmup_boot_s"] = [r.get("boot_s") for r in warm]
    if any(r.get("error") for r in warm):
        print("GATE FAIL: warmup boot loi:\n%s" % [r.get("error") for r in warm
                                                   if r.get("error")])
        return 1

    # XOAY VONG THU TU: neu chot mot che do chay truoc moi che do khac thi lech
    # A-B do ca "lan chay dau cua vong" chu khong phai do code. Dao nguoc o le.
    for i in range(RUNS):
        order = modes if i % 2 == 0 else modes[::-1]
        for mode in order:
            row = run(mode)
            data["modes"][mode].append(row)
            print("[round %d][%-15s] %s" % (i, mode, brief(row)))

    broken = [(m, r["error"]) for m, rows in data["modes"].items()
              for r in rows if r.get("error")]
    if broken:
        for m, err in broken:
            print("GATE FAIL: che do %s chay loi:\n%s" % (m, err))
        return 1

    base, inst = data["modes"]["baseline"], data["modes"]["instrumented"]
    stub, old = data["modes"]["stub_renderer"], data["modes"]["force_qtawesome"]
    b_priv, o_priv = med(base, "private_kib"), med(old, "private_kib")

    paired_old = [o.get("boot_s", 0) - b.get("boot_s", 0) for b, o in zip(base, old)]
    paired_inst = [n.get("boot_s", 0) - b.get("boot_s", 0) for b, n in zip(base, inst)]
    saved_wall = round(statistics.median(paired_old), 3)
    inst_noise = round(statistics.median(paired_inst), 3)
    local_s = seam(inst)
    qtaw_s = seam(old)
    saved_seam = None if (local_s is None or qtaw_s is None) else round(qtaw_s - local_s, 4)

    same_fp = all(r.get("fingerprint") == base[0].get("fingerprint")
                  for rows in data["modes"].values() for r in rows)
    geo = {m: sorted({r.get("geo_hash") for r in rows}) for m, rows in
           data["modes"].items()}
    real_geo = {m: geo[m] for m in ("baseline", "instrumented", "force_qtawesome")}

    print("\n=== boot (%d vong sau %d lan warmup) ===" % (RUNS, WARMUP))
    for label, rows, note in (("baseline        ", base, ""),
                              ("instrumented    ", inst,
                               "lech ghep median %+.3f s" % inst_noise),
                              ("stub_renderer   ", stub,
                               "BO CUC LECH (geo khac) - khong dung lam gate"),
                              ("force_qtawesome ", old,
                                "lech ghep median %+.3f s" % saved_wall)):
        r = rows[0]
        print("  %s %5.3f s (min %5.3f max %5.3f)  WS %6s KiB  private %6s KiB  "
              "seam %6s s  widgets %s  painted %s/%s  qtawesome=%s qtpy=%s "
              "QtOpenGL=%s  %s"
              % (label, med(rows, "boot_s"), min(x.get("boot_s", 9e9) for x in rows),
                 max(x.get("boot_s", 0) for x in rows),
                 med(rows, "ws_kib"), med(rows, "private_kib"), seam(rows),
                 med(rows, "widgets"), r.get("painted"), r.get("sampled"),
                 r.get("qtawesome_loaded"), r.get("qtpy_loaded"),
                 r.get("qtopenGL_loaded"), note))
    print("  warmup boot: %s" % data["warmup_boot_s"])
    print("  lech force-baseline tung vong: %s" % [round(x, 3) for x in paired_old])
    print("  do truc tiep trong cua so boot:")
    print("    bo ve glyph   %.3f s  (nap font %.3f s + ve glyph %.3f s)  %s"
          % (local_s or -1,
             med([r["attribution"] for r in inst], "load_s") or -1,
             med([r["attribution"] for r in inst], "render_s") or -1,
             inst[0]["attribution"].get("counts")))
    print("    qtawesome     %.3f s  (rieng import %.3f s + icon %.3f s)  %s"
          % (qtaw_s or -1,
             med([r["attribution"] for r in old], "seam_import_s") or -1,
             med([r["attribution"] for r in old], "qta_icon_s") or -1,
             old[0]["attribution"].get("counts")))
    print("  cay widget giong nhau moi che do: %s" % same_fp)
    print("  bo cuc theo che do: %s" % json.dumps(geo))
    print("  anh chung minh baseline: %s" % SHOT)

    fails = []
    if any(r.get("cards") != 2 for rows in data["modes"].values() for r in rows):
        fails.append("so card MRU != 2 -> boot khong di qua duong RecentProjectCard "
                     "(duyet %s)" % [r.get("cards") for rows in data["modes"].values()
                                      for r in rows])
    if not same_fp:
        fails.append("cay widget khac nhau -> cac che do khong phai cung mot app")
    if any(not r.get("window_exposed") for r in base + inst):
        fails.append("baseline/instrumented khong mo duoc cua so")
    if any(r.get("painted", 0) < r.get("sampled", 99) for r in base + inst):
        fails.append("baseline/instrumented ve icon khong du pixel -> 'nhanh' la do TRONG")
    if any(r.get("painted", 0) < r.get("sampled", 99) for r in old):
        fails.append("force_qtawesome ve icon khong du pixel -> do trong voi trong")
    for rows, name in ((base, "baseline"), (inst, "instrumented")):
        if any(r.get("qtawesome_loaded") or r.get("qtpy_loaded") for r in rows):
            fails.append("%s: qtawesome/qtpy VAN con trong duong boot that" % name)
        if any(r.get("qtopenGL_loaded") for r in rows):
            fails.append("%s: PySide6.QtOpenGL con bi nap (dau de cua qtpy)" % name)
    if any(len(v) != 1 for v in real_geo.values()) or \
       len({v[0] for v in real_geo.values()}) != 1:
        fails.append("bo cuc khac nhau giua baseline/instrumented/force -> so sanh "
                     "wall-clock khong con la cung mot cua so")
    if abs(inst_noise) > 0.30:
        fails.append("instrumented lech baseline %.3f s -> thep bam da lam thay doi "
                     "boot, so do seam khong dang tin" % inst_noise)
    if local_s is None or local_s > 0.10:
        fails.append("bo ve glyph chiem %.3f s trong cua so boot (>0,10 s) -> van con "
                     "chi phi icon cuc bo can x ly" % (local_s or -1))
    if saved_seam is None or saved_seam < 0.30:
        fails.append("do truc tiep: seam cu (qtawesome) chi hon seam moi %.3f s "
                     "(<0,30 s) -> khong co bang chung swap cat duoc chi phi"
                     % (saved_seam if saved_seam is not None else -1))
    if qtaw_s is not None and (med([r["attribution"] for r in old],
                                   "seam_import_s") or 0) < 0.20:
        fails.append("import qtawesome chiem %.3f s trong boot -> phep force "
                     "khong chay duong cu that (import bi day ra ngoai cua so)"
                     % (med([r["attribution"] for r in old], "seam_import_s") or 0))
    if saved_wall < 0.15:
        fails.append("wall-clock ghep vong chi tang %.3f s khi dung lai qtawesome "
                     "(<0,15 s) -> khong khop voi so do seam, phai kiem lai phep do"
                     % saved_wall)

    print("\n=== Ket luan ===")
    if fails:
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("  Trong cua so boot, seam ve icon chiem: qtawesome %.3f s -> bo ve glyph "
          "%.3f s (tiet kiem %.3f s), do bang dong ho o DUNG cung mot noi."
          % (qtaw_s, local_s, saved_seam))
    print("  Rieng `import qtawesome` = %.3f s; san ve glyph = %.3f s cho %d lan goi."
          % (med([r["attribution"] for r in old], "seam_import_s") or -1,
             med([r["attribution"] for r in inst], "render_s") or -1,
             inst[0]["attribution"].get("counts", {}).get("render", -1)))
    print("  Wall-clock ghep vong xac nhan chieu: force cham hon baseline %.3f s; "
          "RAM private tiet kiem %d KiB."
          % (saved_wall, (o_priv or 0) - (b_priv or 0)))
    print("  Icon cuc bo con lai trong boot (%.3f s) gan 0 -> khong con gi de cat; "
          "lech wall-clock cua stub la do bo cuc, khong phai do ve glyph."
          % local_s)
    data["verdict"] = {"seam_local_s": local_s, "seam_qtawesome_s": qtaw_s,
                       "saved_seam_s": saved_seam,
                       "saved_wall_s": saved_wall, "paired_wall": [round(x, 3) for x in paired_old],
                       "instrumented_noise_s": inst_noise,
                       "saved_private_kib": (o_priv or 0) - (b_priv or 0),
                       "font_load_s": med([r["attribution"] for r in inst], "load_s"),
                       "render_s": med([r["attribution"] for r in inst], "render_s"),
                       "qtawesome_import_s": med([r["attribution"] for r in old],
                                                  "seam_import_s"),
                       "geo_by_mode": geo}
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("JSON:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
