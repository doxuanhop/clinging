"""Counterfactual cho --thumbnail-report: gate PHAI doi mau khi ship hong.

Moi lan mo phong mot kieu hong that (roi anh, thanh cuon xuyen tat) va doi
ma rc thanh 1. Gate luon tra 0 la gate chet, khong phai gate.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import diagnostics as dg  # noqa: E402
from core import thumbnail_export as thumbs  # noqa: E402

OUT_DIR = os.path.join(tempfile.gettempdir(), "clinging_thumbnail_report_out")
REPORT = os.path.join(ROOT, "scratch", "thumb_report_cf.json")
FAILS = []


def run(label):
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    argv = ["x", "--thumbnail-report", REPORT]
    rc = dg.run_thumbnail_report(argv)
    print("%-42s rc=%d" % (label, rc))
    return rc


def check(label, ok):
    print("%-42s %s" % (label, "PASS" if ok else "FAIL"))
    if not ok:
        FAILS.append(label)


real_export = thumbs.export_thumbnails


def lossy(*args, **kwargs):
    """Mo phong 'ghi sot anh': giu lai 3/6 file va bao cao dung so do."""
    result = real_export(*args, **kwargs)
    for path in result["written"][3:]:
        os.remove(path)
    result["written"] = result["written"][:3]
    return result


print("== 1. Chay binh thuong: gate phai = 0 ==")
check("ship lanh -> rc 0", run("lanh") == 0)

print("\n== 2. Gia lap ghi sot anh (3/6) ==")
thumbs.export_thumbnails = lossy
try:
    thumbs.export_video_thumbnails.__globals__["export_thumbnails"] = lossy
    check("roi anh -> rc khac 0", run("roi anh") == 1)
finally:
    thumbs.export_thumbnails = real_export
    thumbs.export_video_thumbnails.__globals__["export_thumbnails"] = real_export

print("\n== 3. Gia lap thang tien do hien xuyen tat ==")
from PySide6.QtWidgets import QProgressBar  # noqa: E402
real_set_visible = QProgressBar.setVisible
QProgressBar.setVisible = lambda self, v=True: real_set_visible(self, True)
try:
    rc = run("bar hien som")
    payload = json.load(open(REPORT, encoding="utf-8"))
    check("bar hien luc chua chay -> rc khac 0", rc == 1)
    check("gate do dung thuoc cua no",
          payload["chrome"]["progress_visible_before"] is True)
finally:
    QProgressBar.setVisible = real_set_visible

print("\n== 4. Ship lanh lai sau hai lan pha ==")
check("lanh -> rc 0", run("lanh lan 2") == 0)

print("\n%s" % ("ALL PASS (0 fail)" if not FAILS else "FAILS: %s" % FAILS))
sys.exit(0 if not FAILS else 1)
