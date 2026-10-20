"""Phan chung: vo hieu hoa tung hook trong bo nho thi selftest phai FAIL.

Mot gate khong doi khi pha logic la gate khong do gi. Khong sua file nguon:
monkeypatch dung object ma diagnostics._settings_ok se goi.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import diagnostics
from core.time_mapper import TimePixelMapper
from core.commands import UndoStack
from core.snap_engine import SnapEngine
from theme import ThemeManager

BASE = diagnostics._settings_ok
print("khong pha gi:", BASE())

def expect_fail(label, apply, restore):
    apply()
    try:
        detail = BASE()
        print("FAIL-TO-DETECT  %s  (gate van PASS: %s)" % (label, detail))
        return False
    except Exception as exc:
        print("detected        %-28s -> %s" % (label, exc))
        return True
    finally:
        restore()

caught = 0
total = 0

orig = TimePixelMapper.set_min_zoom
total += 1; caught += expect_fail(
    "set_min_zoom tro thanh no-op",
    lambda: setattr(TimePixelMapper, "set_min_zoom", lambda self, v: self.MIN_PX_PER_SEC),
    lambda: setattr(TimePixelMapper, "set_min_zoom", orig))

orig = UndoStack.set_max_history
def _lazy(self, limit):
    self.MAX_HISTORY = max(1, int(limit)); return self.MAX_HISTORY
total += 1; caught += expect_fail(
    "set_max_history khong cat qua khru",
    lambda: setattr(UndoStack, "set_max_history", _lazy),
    lambda: setattr(UndoStack, "set_max_history", orig))

orig = SnapEngine._collect_candidates
def _no_edges(self, time, model, exclude):
    out = orig(self, time, model, exclude)
    return [c for c in out if c[1] != "clip_end" and c[1] != "clip_start"]
total += 1; caught += expect_fail(
    "mo co snap_to_clip_edges nhung van tra mep clip",
    lambda: setattr(SnapEngine, "_collect_candidates", _no_edges),
    lambda: setattr(SnapEngine, "_collect_candidates", orig))

orig = ThemeManager.set_mode
def _always(self, mode):
    self._mode = "light" if str(mode).strip().lower() == "light" else "dark"
    self.themeChanged.emit(self._mode); return True
total += 1; caught += expect_fail(
    "set_mode luc cung phat tin hieu",
    lambda: setattr(ThemeManager, "set_mode", _always),
    lambda: setattr(ThemeManager, "set_mode", orig))

orig = SnapEngine.find_snap
total += 1; caught += expect_fail(
    "find_snap tra ve None moi noi",
    lambda: setattr(SnapEngine, "find_snap", lambda self, *a, **k: None),
    lambda: setattr(SnapEngine, "find_snap", orig))

print("\n%d/%d counterfactual duoc phat hien" % (caught, total))
sys.exit(0 if caught == total else 1)
