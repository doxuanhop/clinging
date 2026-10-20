"""Tam: thu hep nguyen nhan abort — chi them clip video vao timeline, khong lam gi them."""
import faulthandler
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
faulthandler.enable()

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from core import project_storage  # noqa: E402
project_storage.AUTO_SAVE_FILE = os.path.join(ROOT, "scratch", "dbg_style_autosave.json")

import diagnostics  # noqa: E402
from core.timeline_model import track_type_for_media  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

src = diagnostics._report_video(seconds=3.0, fps=25.0, size=(320, 180))
win = MainWindow()
win.resize(1500, 900)
win.show()
for _ in range(20):
    app.processEvents()
timer = getattr(win, "_autosave_timer", None)
if timer is not None:
    timer.stop()

model = win.timeline_panel.model
track = model.add_track(track_type_for_media("video"), "Dbg")
clip = model.add_clip(track.track_id, src, "video", 0.0, 3.0, "nen")
model.playhead = 1.0
win._sync_canvas()
for i in range(8):
    for _ in range(10):
        app.processEvents()
    print("pump %d ok, items=%s" % (i, list(win.preview_panel.canvas._clip_items)))
    sys.stdout.flush()
print("SURVIVED")
win.close()
sys.stdout.flush()
os._exit(0)
