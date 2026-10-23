"""Do CHI PHI that cua "Thu vien tai nguyen" tren may cau hinh thap nay.

May nay that (khong mo phong): i7-2720QM 4C/8T nam 2011, 12 GB RAM, media nam
tren HDD 5400 rpm. Moi so do doc tu machine nay, ghi ra
scratch/library_perf.json de lan sau so sinh.

Tat ca phep do di qua DUNG duong production:
  `LibraryPanel.restore_resources()`    (ui/main_window.py:214 goi khi mo project)
  `LibraryPanel.add_resource()`         (goi khi tha/kenh them tep)
  `LibraryPanel._apply_filter()`        (mo khi go tim / doi tab / bat an tep mat)
  `ResourceCard._apply_thumb()`         (slot tren thread GUI luc anh ve xong)
  `ui.library_panel.decode_thumb_image` (thread nen)
  `_ThumbTask.run()`                    (QRunnable that cua pool)
Khong co ham phong, khong co widget tu dung. Cac bong dong ho goi NGUYEN ham
san xuat va chi them dong ho + dem, nen so do la cua duong that.

LY DO CO P0/P0b: lan chay dau tien cua probe nay bao "luoi ve xong 0,030 s" va
"P4 = 0 lan". Ca hai deu gia — `ResourceCard._load_thumbnail()` dat ICON cho
bang `set_label_icon()`, ma icon cung la QPixmap, nen dem `pixmap() is None`
luon tra "xong". P0 do dung cai do va cong bo no; moi phep cho sau nay dua tren
dem SO LAN GIAO THAT (decode + _apply_thumb), khong dua tren pixmap.

Cac phep do:
  P0  P0a pixmap placeholder co bi tinh la "ve xong" khong (phan chung cua phep
      do cu); P0b so lan giao that khi dung 18 card
  P1  GUI thread bi BLOCK khi dung lai toan bo card (cold vs warm cache dia)
  P2  thoi gian den khi worker giai xong CA LUOI + so lan GUI thuc su ve
  P3  mot lan go mot ky tu tim kiem / mot lan doi tab (khi luoi da day card)
  P4  tong thoi gian thread GUI ot trong _apply_thumb, tach theo rong anh
  P5  kich thuoc QImage ma duong "image" giai ma ra (full-size hay da thu nho)
  P6  working set (KiB, tu ham cua production main._working_set_kib)
  P7  so luot giai ma LANG PHI cho card dang bi bo loc an
  P8  phan thoi gian GUI block nam trong _apply_filter (lan COLD va WARM)
  P9  scaling: GUI block theo so card — du do O(n^2) cua doi luoi
  P10 so luot giai ma van chay sau khi card da bi xoa + so lan emit that bai
      qua bien callback C++ cua Qt

Chay:  python -u scratch/library_perf_probe.py
Khong doi nguong nao cua --selftest: day la probe do, khong phai gate.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

WORK = os.path.join(tempfile.gettempdir(), "clinging_libperf")
CACHE = os.path.join(WORK, "cache")
MEDIA = os.path.join(WORK, "media")
N_VIDEO, N_IMAGE, N_SMALL = 12, 6, 48
IMG_W, IMG_H = 2000, 2800
JSON_OUT = os.path.join(ROOT, "scratch", "library_perf.json")
PUMP = 0.005          # ~50 vong processEvents/giay — du cho slot queued

RESULTS = {}


def row(metric, value, unit="", note=""):
    RESULTS[metric] = {"value": value, "unit": unit, "note": note}
    print("%-46s %10s %-5s %s" % (
        metric, ("%.3f" % value) if isinstance(value, float) else value, unit, note))


def ffmpeg(args, timeout=180):
    from core import external_tools
    cmd = [external_tools.require("ffmpeg"), "-hide_banner", "-loglevel", "error",
           "-y"] + args
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit("ffmpeg fail: %s"
                         % proc.stderr.decode("utf-8", "replace")[-600:])


def working_set_kib():
    """DUNG ham cua production (main._working_set_kib), khong ban sao.

    Ban sao o day tung go `ctypes.windll.psapi.K32GetProcessMemoryInfo` va
    AttributeError — ham nam tren kernel32 tu Win Vista+. main.py da xu ly dung
    va duoc gate rieng trong --startup-report, nen do bang no la do bang thu
    nguo dung thay."""
    from main import _working_set_kib
    return _working_set_kib()


def pump(app, seconds=0.05):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(PUMP)


# ── fixture ────────────────────────────────────────────────────

def make_fixture():
    """Video 720p ngan + anh lon 2000x2800 (jpg va png) — nhu mot project anh
    dien thoai. Nhom tep nho (320x240) chi de do SCALING cua doi luoi: chung
    that nam tren dia, di qua dung ResourceCard that.

    Khong lay media cua nguoi dung (rang buoc "khong dung cham du lieu nguoi
    dung"): moi tep do ffmpeg cua bundle sinh ra trong %TEMP%."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(MEDIA, exist_ok=True)
    paths = []
    for i in range(N_VIDEO):
        p = os.path.join(MEDIA, "clip_%02d.mp4" % i)
        ffmpeg(["-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=24:duration=2",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", p])
        paths.append({"name": os.path.basename(p), "type": "video", "path": p})
    for i in range(N_IMAGE):
        ext = "jpg" if i % 2 else "png"
        p = os.path.join(MEDIA, "photo_%02d.%s" % (i, ext))
        ffmpeg(["-f", "lavfi", "-i", "gradients=size=%dx%d" % (IMG_W, IMG_H),
                "-frames:v", "1", p])
        paths.append({"name": os.path.basename(p), "type": "image", "path": p})
    for i in range(N_SMALL):
        p = os.path.join(MEDIA, "tiny_%02d.mp4" % i)
        ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p])
        paths.append({"name": os.path.basename(p), "type": "video", "path": p})
    for rec in paths:
        if not os.path.isfile(rec["path"]) or os.path.getsize(rec["path"]) < 2000:
            raise SystemExit("fixture hong: %r" % rec["path"])
    return paths


# ── bong do (goi NGUYEN ham production, chi them dong ho) ───────

class Hooks:
    """Dem va do. Moi ham boc luu lai de restore, va `uninstall()` phai chay
    trong `finally` — probe do roi de lang bang trong source tree la rac.

    Giao dich duoc phan biet theo `card.full_path` (chu khong phai bucket tren
    card) vi khong muon cham vao `ResourceCard.__init__`: ghi sai o do la
    exception bat qua bien callback C++ cua Qt, lop loi repo da ghi co the
    abort 0xC0000409."""

    def __init__(self):
        self.applying = []        # (giay, w, h, full_path) moi lan _apply_thumb (GUI)
        self.decodes = []         # (kind, w, h, path) moi lan decode THAT (worker)
        self.filters = []         # giay moi lan _apply_filter (GUI)
        self.task_runs = []       # (basename, ten loi) moi lan QRunnable chay
        self.emit_errors = 0
        self.emit_errors_total = 0    # KHONG bi reset: reset thi P10 bao 0 trong
                                      # khi stderr van in ra 3 lan
        self._saved = []

    def install(self):
        import ui.library_panel as lp

        original_thumb = lp.ResourceCard._apply_thumb
        applying = self.applying

        def timed_thumb(self, image):
            t0 = time.perf_counter()
            original_thumb(self, image)
            applying.append((time.perf_counter() - t0, image.width(),
                             image.height(), self.full_path))
        lp.ResourceCard._apply_thumb = timed_thumb
        self._saved.append((lp.ResourceCard, "_apply_thumb", original_thumb))

        original_decode = lp.decode_thumb_image
        decodes = self.decodes

        def counted_decode(path, kind, max_width=320):
            image = original_decode(path, kind, max_width)
            decodes.append((kind, image.width(), image.height(), path))
            return image
        lp.decode_thumb_image = counted_decode
        self._saved.append((lp, "decode_thumb_image", original_decode))

        original_run = lp._ThumbTask.run
        runs = self.task_runs
        counters = self        # `self` ben trong counted_run la TASK, khong phai Hooks

        def counted_run(self):
            error = ""
            try:
                original_run(self)
            except RuntimeError as exc:
                # Nem lai: day van phai la duong production, probe chi dem.
                counters.emit_errors += 1
                counters.emit_errors_total += 1
                error = type(exc).__name__
                raise
            finally:
                runs.append((os.path.basename(self.path), error))
        lp._ThumbTask.run = counted_run
        self._saved.append((lp._ThumbTask, "run", original_run))

        original_filter = lp.LibraryPanel._apply_filter
        filters = self.filters

        def counted_filter(self):
            t0 = time.perf_counter()
            original_filter(self)
            filters.append(time.perf_counter() - t0)
        lp.LibraryPanel._apply_filter = counted_filter
        self._saved.append((lp.LibraryPanel, "_apply_filter", original_filter))

    def uninstall(self):
        for holder, name, value in reversed(self._saved):
            setattr(holder, name, value)
        self._saved = []

    def wait_workers(self, app, want, timeout=180.0):
        """Cho den khi worker chay xong `want` luot giai ma — KHONG dua tren
        pixmap, vi icon placeholder cung la QPixmap."""
        t0 = time.perf_counter()
        deadline = t0 + timeout
        while time.perf_counter() < deadline and len(self.decodes) < want:
            app.processEvents()
            time.sleep(PUMP)
        return time.perf_counter() - t0

    def delivered(self, paths):
        """So card trong `paths` thuc su nhan anh tren thread GUI."""
        wanted = set(paths)
        return sum(1 for _dt, _w, _h, p in self.applying if p in wanted)

    def dt_for(self, paths, wide_only=None):
        wanted = set(paths)
        out = []
        for dt, w, _h, p in self.applying:
            if p in wanted and (wide_only is None or (w > 400) == wide_only):
                out.append(dt)
        return out


def main():
    from core import media_cache
    media_cache.cache_root = lambda: CACHE   # do cold/warm khong cham cache nguoi dung

    print("== fixture ==")
    records = make_fixture()
    print("   %d video 720p + %d anh %dx%d + %d tep nho = %d file"
          % (N_VIDEO, N_IMAGE, IMG_W, IMG_H, N_SMALL, len(records)))

    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    import ui.library_panel as lp
    from ui.library_panel import LibraryPanel, ResourceCard

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
    panel = LibraryPanel()
    host.layout().addWidget(panel)
    host.resize(360, 900)
    host.show()
    pump(app)

    hooks = Hooks()
    hooks.install()
    original_decode = lp.decode_thumb_image  # BAN THAT, sau khi boc gia tai

    real = [r for r in records if r["name"].startswith(("clip_", "photo_"))]
    real_paths = [r["path"] for r in real]
    n_real = len(real)

    try:
        # ── P0a: pixmap placeholder bi tinh la "ve xong" — phan chung ──
        panel.clear_resources()
        pump(app)
        hooks.decodes.clear()
        panel.add_resource(real[0]["name"], "video", real[0]["path"], emit_change=False)
        card0 = panel._items[-1]
        placeholder = card0.thumb_container.pixmap()
        row("P0a pixmap cua card VUA tao (chua giai ma)",
            "co (%dx%d)" % (placeholder.width(), placeholder.height())
            if placeholder and not placeholder.isNull() else "khong", "",
            "dem pixmap() la cach do GIA: lan chay dau bao 'luoi ve xong 0,030 s, "
            "pending=0' khi so luot giai ma thuc te moi bang %d" % len(hooks.decodes))

        # ── P0b: so lan GIAO THAT khi dung het nhom 18 card ────────
        hooks.applying.clear()
        hooks.decodes.clear()
        hooks.task_runs.clear()
        t0 = time.perf_counter()
        panel.restore_resources(real)
        blocked_first = time.perf_counter() - t0
        wait0 = hooks.wait_workers(app, n_real)
        pump(app, 0.8)
        delivered = hooks.delivered(real_paths)
        row("P0b lan GIAO THAT _apply_thumb (%d card)" % n_real, delivered, "lan",
            "worker xong sau %.3f s; GUI block %.3f s" % (wait0, blocked_first))

        # ── P5: mot anh bi giai ma full-size hay da thu nho ────────
        for label, name in (("jpg", "photo_01.jpg"), ("png", "photo_00.png")):
            rec = next(r for r in records if r["name"] == name)
            img = original_decode(rec["path"], "image")
            row("P5 anh %s: QImage tra ve" % label,
                "%dx%d" % (img.width(), img.height()), "",
                "~%.1f MiB RGB tam thoi, card chi can 116x76"
                % (img.width() * img.height() * 3 / 1048576.0))

        # ── P1/P2/P4/P6/P8: cold vs warm, do THAT ──────────────────
        for warm in (False, True):
            if not warm:
                shutil.rmtree(CACHE, ignore_errors=True)
            hooks.decodes.clear()
            hooks.applying.clear()
            hooks.filters.clear()
            hooks.task_runs.clear()
            ws_before = working_set_kib()
            t0 = time.perf_counter()
            panel.restore_resources(real)
            blocked = time.perf_counter() - t0
            fl = sum(hooks.filters) * 1000.0
            t1 = time.perf_counter()
            wait = hooks.wait_workers(app, n_real)
            pump(app, 0.8)
            delivered = hooks.delivered(real_paths)
            ws_after = working_set_kib()
            tag = "WARM" if warm else "COLD"
            row("P1 restore_resources %d card %s (GUI block)" % (n_real, tag),
                blocked, "s", "cache dia %s"
                % ("da co anh nhỡ video" if warm else "trong"))
            row("P2 worker giai xong ca luoi %s" % tag, wait, "s",
                "GUI ve duoc %d/%d card; %d luot decode"
                % (delivered, n_real, len(hooks.decodes)))
            row("P8 _apply_filter %s" % tag, fl, "ms",
                "%d lan chay trong %.0f ms block => %.0f%% thoi gian GUI la doi luoi"
                % (len(hooks.filters), blocked * 1000.0,
                   100.0 * fl / max(blocked * 1000.0, 1e-9)))
            row("P6 working set delta %s" % tag, ws_after - ws_before, "KiB",
                "%d -> %d" % (ws_before, ws_after))
            if warm:
                all_dt = hooks.dt_for(real_paths)
                big = hooks.dt_for(real_paths, wide_only=True)
                small = hooks.dt_for(real_paths, wide_only=False)
                row("P4 _apply_thumb tong (thread GUI, WARM)",
                    sum(all_dt) * 1000.0, "ms",
                    "%d lan; anh >400px rong (jpg/png): %d lan tot %.1f ms; "
                    "video <=320px: %d lan tot %.1f ms"
                    % (len(all_dt), len(big), sum(big) * 1000.0,
                       len(small), sum(small) * 1000.0))

        # ── P3: go tim kiem va doi tab, luc luoi DA day card ────────
        ks, ks_filter = [], []
        for term in ("", "c", "cl", "cli", "clip", "clip_", "x", ""):
            hooks.filters.clear()
            t0 = time.perf_counter()
            panel.search_box.input.setText(term)
            app.processEvents()
            ks.append(time.perf_counter() - t0)
            ks_filter.append(sum(hooks.filters) * 1000.0)
        row("P3 mot lan go tim kiem (median)",
            sorted(ks)[len(ks) // 2] * 1000.0, "ms",
            "max %.1f ms; median _apply_filter %.1f ms tren %d card"
            % (max(ks) * 1000.0, sorted(ks_filter)[len(ks_filter) // 2], n_real))

        tabs, tabs_filter = [], []
        for idx in (1, 2, 3, 0):
            hooks.filters.clear()
            t0 = time.perf_counter()
            panel.tabs._buttons[idx].click()
            app.processEvents()
            tabs.append(time.perf_counter() - t0)
            tabs_filter.append(sum(hooks.filters) * 1000.0)
        row("P3 mot lan doi tab (median)", sorted(tabs)[len(tabs) // 2] * 1000.0, "ms",
            "max %.1f ms; _apply_filter: %s"
            % (max(tabs) * 1000.0, ["%.1f" % v for v in tabs_filter]))

        # ── P7: the bi AN thi KHONG giai ma; mo tab ra thi van phai co ──
        panel.clear_resources()
        pump(app)
        hooks.decodes.clear()
        hooks.applying.clear()
        panel.tabs._buttons[1].click()          # tab Video -> anh bi an
        images = [r for r in records if r["type"] == "image"]
        image_paths = [r["path"] for r in images]
        panel.restore_resources(images)
        pump(app, 1.5)                           # du cho 6 luot giai ma chay xong
        hidden_runs = sum(1 for kind, _w, _h, _p in hooks.decodes if kind == "image")
        visible = sum(1 for c in panel._items
                      if isinstance(c, ResourceCard) and not c.isHidden())
        row("P7 luot giai ma khi tab Video mo (%d anh)" % len(images),
            hidden_runs, "lan",
            "the an khong duoc giai ma: %d/%d; card THING hien: %d"
            % (hidden_runs, len(images), visible))

        # Parity cua do tre: mo tab Hinh anh thi 6 the ay PHAI tai duoc anh,
        # neu khong "toi uu" chi la cach khac cua "thumbnail khong bao gio hien".
        hooks.decodes.clear()
        hooks.applying.clear()
        panel.tabs._buttons[3].click()           # tab Hình ảnh
        wait7 = hooks.wait_workers(app, len(images), timeout=60.0)
        pump(app, 0.8)
        got = hooks.delivered(image_paths)
        widths = [w for _dt, w, _h, p in hooks.applying if p in set(image_paths)]
        row("P7b mo tab Hinh anh thi 6 the tai duoc", got, "lan",
            "sau %.3f s; rong anh giao ve: %s (max_width=320)"
            % (wait7, sorted(set(widths))))

        # ── P9: scaling — GUI block theo so card ────────────────────
        panel.tabs._buttons[0].click()
        pump(app)
        for n in (n_real, 30, n_real + N_SMALL):
            sub = (records[:n] if n != 30
                   else [r for r in records if r["name"].startswith(("clip_", "photo_"))][:12]
                   + [r for r in records if r["name"].startswith("tiny_")][:18])
            hooks.filters.clear()
            t0 = time.perf_counter()
            panel.restore_resources(sub)
            blocked = time.perf_counter() - t0
            fl = sum(hooks.filters) * 1000.0
            row("P9 restore_resources %d card (GUI block)" % len(sub), blocked, "s",
                "_apply_filter chay %d lan, %.0f ms (%.0f%%); block/card %.1f ms"
                % (len(hooks.filters), fl, 100.0 * fl / max(blocked * 1000.0, 1e-9),
                   blocked * 1000.0 / len(sub)))
            # Buoc PHAI la 1: dot nap gop do luoi thanh mot lan. >1 nghia la
            # quay lai O(n^2); 0 nghia la luoi khong duoc do lai sau dot nap.
            row("P9 CHECK so lan _apply_filter = 1", len(hooks.filters), "lan",
                "KHONG DAT" if len(hooks.filters) != 1 else "dat")

        # ── P10: giai ma van chay sau khi card bi xoa ───────────────
        # Phai doi pool KIET TRUOC: neu khong, con sot luot giai cua P9 (66
        # card) len vao trong bang P10 va bao "43 lan lang phi" cho 20 task.
        lp.thumb_pool().waitForDone(60000)
        pump(app, 0.3)
        hooks.decodes.clear()
        hooks.task_runs.clear()
        hooks.emit_errors = 0
        panel.restore_resources(records[:20])   # 20 task bay vao pool (max 3 thread)
        panel.clear_resources()                 # xoa card KHI task dang chay
        hooks.wait_workers(app, 20, timeout=60.0)
        pump(app, 0.5)
        row("P10 decode chay SAU khi clear (20 card)", len(hooks.decodes), "lan",
            "toan bo la lang phi: khong con card nao de gan anh vao; emit that "
            "bai trong phep do nay: %d" % hooks.emit_errors)
        row("P10 so lan 'Signal source has been deleted' (ca lan chay)",
            hooks.emit_errors_total, "lan",
            "exception bat ra tu callback C++ cua QRunnable — lop loi repo da "
            "ghi lop loi nay co the abort 0xC0000409 khong on dinh")

        host.close()
        pump(app)

        RESULTS["fixture"] = {"video": N_VIDEO, "image": N_IMAGE, "small": N_SMALL,
                              "img_wh": [IMG_W, IMG_H], "cards_real": n_real}
        payload = json.dumps(RESULTS, ensure_ascii=False, indent=1)
        tmp = JSON_OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(tmp, JSON_OUT)
        print("\nghi %s" % JSON_OUT)
        return 0
    finally:
        hooks.uninstall()
        # cv2 VideoCapture phia worker co the van giu mo luc rmtree lan dau, va
        # rmtree(ignore_errors=True) AN that bai — nen thu lai co dem so lan.
        for _ in range(25):
            shutil.rmtree(WORK, ignore_errors=True)
            if not os.path.exists(WORK):
                break
            time.sleep(0.2)
        if os.path.exists(WORK):
            print("CANH BAO: goc fixture con sot %s" % WORK)


if __name__ == "__main__":
    sys.exit(main())
