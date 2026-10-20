"""scratch/captions_bar_probe.py

Gate cho thanh tien trinh cua hop thoai "Phụ đề tự động"
(ui/auto_captions_dialog.py) sau khi no thu lai thanh dai 8px khong vien —
giong het hai hop thoai cat video va trich anh thu nho.

Hai thu phai chung minh, khong phai mot:

1. Chieu day THAT tren pixel, do tren grab cua RIENG thanh bang dung thuoc o
   bar_measure.py (hai gate kia cung dung no). Counterfactual lap lai kieu cu
   (vien 1px + 18px) phai cho so DAY HON; phuc kieu thi phai tra lai DUNG con
   so ban dau. Mot phep do khong phan biet duoc hai kieu thi khong do gi ca.

2. Con so % phai khong bi mat. Thanh cu in "42%" ngay trong no; thanh 8px thi
   khong con cho chua chu, nen con so phai chay sang lbl_status. Gate kiem
   dung slot that `_on_progress` ma worker goi, khong gia lap gia tri.

Worker ASR that goi mang (Bcut), nen probe nay chi gia lap CAI POOL:
`btn_run.click()` van di qua `_on_run` that, van gan task that, chi co doan
noi `pool.start(task)` la khong cho no chay — dung nhu gate cat video goi
`_on_progress` truc tiep de bat luc do.

Chay: python -u scratch/captions_bar_probe.py
"""

import ctypes
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# Grab ra pixel thiet bi bang pixel logic de so px do duoc so thang voi QSS.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

import bar_measure

OUT = os.path.join(ROOT, "scratch")
WORK = os.path.join(OUT, "captions_bar_work")
SRC = os.path.join(WORK, "nguon.mp4")
BAR_RUN = os.path.join(OUT, "captions_bar_running.png")
BAR_OLD = os.path.join(OUT, "captions_bar_oldstyle.png")
BAR_BACK = os.path.join(OUT, "captions_bar_restored.png")
DIALOG_SHOT = os.path.join(OUT, "captions_dialog_running.png")
FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%-4s %-58s got=%r want=%r"
          % ("PASS" if ok else "FAIL", name, got, want))
    if not ok:
        FAILS.append(name)
    return ok


def above(name, got, floor):
    ok = got > floor
    print("%-4s %-58s got=%r want> %r" % ("PASS" if ok else "FAIL", name, got, floor))
    if not ok:
        FAILS.append(name)
    return ok


def true(name, condition):
    return check(name, bool(condition), True)


def pump(times=6, step=0.03):
    app = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.instance()
    for _ in range(times):
        app.processEvents()
        time.sleep(step)


def build_source():
    os.makedirs(WORK, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=blue:s=160x120:d=3:r=25,format=yuv420p",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-g", "10",
         "-c:a", "aac", SRC],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
        check=False, **FLAGS)
    true("nguon thu co that tren dia", os.path.isfile(SRC)
         and os.path.getsize(SRC) > 1000)


class _FakePool:
    """Chi ghi lai task, khong chay — de `_on_run` that van duoc di het."""

    def __init__(self):
        self.task = None

    def start(self, task):
        self.task = task


class _NoBox:
    """QMessageBox.critical/warning khong duoc mo hop thoai chan probe."""

    shown = []

    @staticmethod
    def critical(parent, title, text, *a, **k):
        _NoBox.shown.append(("critical", title, text))

    @staticmethod
    def warning(parent, title, text, *a, **k):
        _NoBox.shown.append(("warning", title, text))

    @staticmethod
    def information(parent, title, text, *a, **k):
        _NoBox.shown.append(("info", title, text))


def main():
    from PySide6.QtWidgets import QApplication
    build_source()
    app = QApplication.instance() or QApplication([])
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    print("\n== 1. Hop thoai mo tu cua so that ==")
    from ui.main_window import MainWindow
    import ui.auto_captions_dialog as mod
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(12)
    win.library_panel.add_resource("nguon.mp4", "video", SRC)
    dialog = win._open_auto_captions()
    pump(8)
    true("hop thoai mo ra that", dialog is not None)
    check("nguon la video vua them vao thu vien",
          os.path.abspath(dialog._current_source() or ""), SRC)
    check("thang tien do AN khi chua chay (khong con chrome chet)",
          dialog.progress.isVisible(), False)
    check("thanh khong in chu trong no nua",
          dialog.progress.isTextVisible(), False)
    check("thanh khai 8px", dialog.progress.height(), 8)

    print("\n== 2. Bam Chay: duong that, worker khong goi mang ==")
    fake = _FakePool()
    real_pool = mod._pool
    mod._pool = lambda: fake
    mod.QMessageBox = _NoBox
    try:
        dialog.btn_run.click()
        pump(6)
        check("bam nut di qua _on_run that (busy + task)",
              [dialog._busy, fake.task is not None], [True, True])
        check("bam Chay thi thang hien len", dialog.progress.isVisible(), True)

        print("\n== 3. Do day thanh tren pixel that ==")
        dialog._on_progress(50, "đang nhận dạng")
        pump(6)
        band = bar_measure.teal_band_height(dialog.progress, BAR_RUN)
        print("     bang teal: %d px anh thiet bi cho thanh 8px" % band)
        above("thang tien trinh co pixel that khi chay nua", band, 3)
        check("thang tien trinh mong (<= 14 px)", band <= 14, True)
        dialog.grab().save(DIALOG_SHOT)
        true("con so % khong bi mat (chuyen xuong lbl_status)",
             dialog.lbl_status.text().startswith("50%")
             and "đang nhận dạng" in dialog.lbl_status.text())
        print("     status:", dialog.lbl_status.text())

        print("\n== 4. Counterfactual: do nay phai nhay kieu cu ==")
        dialog.progress.setFixedHeight(20)
        dialog.progress.setStyleSheet(
            "QProgressBar { border: 1px solid #262831; border-radius: 6px;"
            " background-color: #14151A; }")
        pump(6)
        old_band = bar_measure.teal_band_height(dialog.progress, BAR_OLD)
        dialog.progress.setStyleSheet("")
        dialog.progress.setFixedHeight(8)
        pump(6)
        print("     kieu cu: %d px -> kieu moi: %d px" % (old_band, band))
        above("phep do phat hien kieu cu day hon kieu moi", old_band - band, 3)
        check("phuc kieu mong thi tra dung con so ban dau",
              bar_measure.teal_band_height(dialog.progress, BAR_BACK), band)

        print("\n== 5. That bai thi thanh an di ==")
        dialog._on_failed("nguon bi hong gia lap")
        pump(6)
        check("that bai: thang tien do an", dialog.progress.isVisible(), False)
        check("that bai: loi van den duoc nguoi dung (hop thoai that)",
              [row[1] for row in _NoBox.shown if row[0] == "critical"],
              ["Nhận dạng thất bại"])
    finally:
        mod._pool = real_pool
        dialog.close()
        win.close()
        pump(6)

    print("\nsummary: %s  (%d fail)"
          % ("ALL PASS" if not FAILS else "FAILURES", len(FAILS)))
    for name in FAILS:
        print("  FAIL", name)
    print("evidence:", os.path.basename(BAR_RUN), os.path.basename(BAR_OLD),
          os.path.basename(DIALOG_SHOT))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
