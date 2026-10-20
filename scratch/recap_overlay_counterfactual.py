"""Phản chứng: gate recap phải ĐỎ khi từng mắt xích bị cắt — nếu còn xanh là probe giả.

Bốn phép thử, mỗi phép cắt đúng một mối nối thật:
  a) PreviewCanvas.drawForeground -> no-op   (mối nối mới nối trong lượt này)
  b) recap_overlay.paint_overlay  -> no-op   (seam vector dùng chung hai đường)
  c) recap_overlay.paint_backdrop -> no-op   (nền kính mờ)
  d) PreviewCanvas._grab_scene_content -> None (ảnh chụp scene của preview)
"""
import io
import os
import runpy
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scratch"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import recap_overlay_probe as P  # noqa: E402


def run():
    try:
        P.main()
    except SystemExit:
        return "probe thoat som (khong phai loi)"
    except BaseException as exc:
        return "%s: %s" % (type(exc).__name__, str(exc).splitlines()[0])
    return None


CASES = [
    ("a preview drawForeground", "ui.preview_panel", "PreviewCanvas.drawForeground",
     lambda self, painter, rect: None),
    ("b paint_overlay", "core.recap_overlay", "paint_overlay",
     lambda *a, **k: None),
    ("c paint_backdrop", "core.recap_overlay", "paint_backdrop",
     lambda *a, **k: None),
    ("d grab_scene_content", "ui.preview_panel", "PreviewCanvas._grab_scene_content",
     lambda self, w, h: None),
]

failed = []
for label, _mod, target, stub in CASES:
    if "." in target:
        cls_name, attr = target.split(".")
        owner = getattr(P, cls_name) if hasattr(P, cls_name) else None
        if owner is None:
            import ui.preview_panel as upp
            owner = getattr(upp, cls_name)
        holder, key = owner, attr
    else:
        import core.recap_overlay as cro
        holder, key = cro, target
    original = getattr(holder, key)
    setattr(holder, key, stub)
    try:
        msg = run()
    finally:
        setattr(holder, key, original)
    if msg is None:
        failed.append(label)
        print("XANH (SAI)  %s: cat mat moi ma probe van pass" % label)
    else:
        print("DO (dung)    %s -> %s" % (label, msg[:120]))

# Va phai xanh khi khong cat gi ca.
clean = run()
if clean is not None:
    failed.append("clean")
    print("XANH? clean run bi do: %s" % clean)
else:
    print("XANH (dung)  clean run khong cat gi")

# --- Dong --selftest cung phai do khi cat mat noi that ---------------------
import diagnostics  # noqa: E402


def run_row():
    try:
        return None, diagnostics._recap_overlay_ok()
    except BaseException as exc:
        return "%s: %s" % (type(exc).__name__, str(exc).splitlines()[0]), ""


import core.project_storage as cps  # noqa: E402

_save = cps.save_project_to_file


def drop_key(model, path, project_meta=None):
    """Ghi file NHƯNG xoá khoá recap_overlay — mô phỏng bản trước khi có tính năng."""
    _save(model, path, project_meta)
    import json
    with io.open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.get("timeline", {}).pop("recap_overlay", None)
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


import core.recap_overlay as cro  # noqa: E402

for label, holder, key, stub in (
        ("e selftest row: paint_overlay", cro, "paint_overlay", lambda *a, **k: None),
        ("f selftest row: mat khoa trong file", cps, "save_project_to_file", drop_key)):
    original = getattr(holder, key)
    setattr(holder, key, stub)
    try:
        err, note = run_row()
    finally:
        setattr(holder, key, original)
    if err is None:
        failed.append(label)
        print("XANH (SAI)  %s: cat mat moi ma dong selftest van pass" % label)
    else:
        print("DO (dung)    %s -> %s" % (label, err[:120]))

err, note = run_row()
if err is not None:
    failed.append("selftest clean")
    print("XANH? dong selftest clean bi do: %s" % err)
else:
    print("XANH (dung)  dong selftest: %s" % note)

print("rc", 1 if failed else 0, failed)
sys.exit(1 if failed else 0)
