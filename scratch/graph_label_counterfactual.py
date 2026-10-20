"""scratch/graph_label_counterfactual.py

Chung minh gate "cot so khong de len nhau" trong keyframe_graph_probe CO THAT
bat duoc loi.

Phat lai cach cu — lane nao cung in ca 5 dong nhan (ma lane 48 px chua duoi
16 px x 5): gate phai NO va probe phai tra rc != 0. Chay xong thi khong de
lai patch nao (moi thu nam trong process con nay).

Chay: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/graph_label_counterfactual.py
"""

import ctypes
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import ui.keyframe_graph_dialog as dlg

# Cach CU: khong bao gio gian cach nhan, bat ke lane cao bao nhieu.
dlg.label_divisions = lambda height, label_h: 4

code = 0
try:
    runpy.run_path(os.path.join(ROOT, "scratch",
                                "keyframe_graph_probe.py"),
                   run_name="__main__")
except SystemExit as exit_request:
    code = exit_request.code or 0

print("\nprobe duoi cach cu: rc=%d (%s)"
      % (code, "FAIL nhu mong doi" if code else "PASS — gate vo nghia!"))
if code == 0:
    print("GATE KHONG PHAT Hien loi: cot so de len nhau ma van PASS")
sys.exit(0 if code else 1)
