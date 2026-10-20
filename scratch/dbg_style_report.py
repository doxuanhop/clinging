"""Tam: lay traceback THAT cua run_style_report (exe abort khong in gi ra)."""
import faulthandler
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
faulthandler.enable()

import diagnostics  # noqa: E402

out = os.path.join(os.environ.get("TEMP", ROOT), "clinging_style_dbg.json")
try:
    rc = diagnostics.run_style_report(["x", out])
except SystemExit as exc:
    rc = exc.code
except BaseException:
    traceback.print_exc()
    rc = 1
print("STYLE rc=%s" % rc)
sys.stdout.flush()
os._exit(0 if rc == 0 else 1)
