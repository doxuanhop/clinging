"""scratch/_project_cf_child.py

Chay --project-report (hoac --selftest, mode "selftest") duoi mot loi da phat
lai TRONG BO NHO cua process nay; khong file nao bi sua.
Xem scratch/project_launch_counterfactual.py.
"""

import ctypes
import os
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


def patch(mode):
    from core import project_storage as ps
    if mode == "parse":
        # Loi DA SHIP o duoi khac: chi doc --project, yen lang bo qua dong ma
        # Explorer thuc su gui ("Clinging.exe <duong-dan.clinq>").
        ps.project_arg_from_argv = lambda argv: (
            argv[argv.index("--project") + 1] if "--project" in argv
            and argv.index("--project") + 1 < len(argv) else None)
        return
    if mode == "restore":
        # Loi DA SHIP o duoi khac: editor du mo ra nhung model khong duoc nap,
        # nguoi dung thay mot timeline trang.
        ps.restore_model_from_clinq = lambda model, project: None
        return
    if mode == "library":
        # Du an mo dung nhung thu vien trong trang: asset bi an, keo khong ra.
        from ui.main_window import MainWindow
        MainWindow.restore_library_from_project = lambda self, project: None
        return
    if mode == "order":
        # Thu vien co DU nhung SAI THU TU. Phep so sanh sap xep hai ben thi
        # khong bao gio phat hien; do la ly do khoa nay so theo thu tu file.
        from ui.library_panel import LibraryPanel
        original = LibraryPanel.restore_resources

        def reversed_restore(self, assets):
            records = (list(assets.values()) if isinstance(assets, dict)
                       else list(assets or []))
            return original(self, list(reversed(records)))

        LibraryPanel.restore_resources = reversed_restore
        return
    raise SystemExit("mode khong biet: %r" % mode)


def main():
    mode = sys.argv[1]
    report = sys.argv[2]
    if mode == "selftest":
        # Khoa nam trong selftest phai BIT: doi parser thanh kieu chi doc
        # --project roi chay chinh selftest cua process nay.
        from core import project_storage as ps
        ps.project_arg_from_argv = lambda argv: (
            argv[argv.index("--project") + 1] if "--project" in argv
            and argv.index("--project") + 1 < len(argv) else None)
        from diagnostics import run_selftest
        return run_selftest([sys.argv[0], report])
    from diagnostics import _project_fixture
    fixture, _ = _project_fixture()
    patch(mode)
    from diagnostics import run_project_report
    # Duong dan di qua argv THAT, giong het chuoi Explorer sinh ra.
    return run_project_report([sys.argv[0], report, fixture])


if __name__ == "__main__":
    sys.exit(main())
