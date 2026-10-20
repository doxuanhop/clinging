"""Con chay cho phan chung cua DÒNG --selftest "xem trước = xuất".

Row ``_local_time_ok`` chứng minh preview lẫn export lấy mốc thời gian cục bộ
của clip từ MỘT hàm. Mỗi mode cắt ĐÚNG MỘT mắt xích rồi gọi hàm row:

  boundary       — xoá biên kẹp, trả về đúng phép trừ thô mà export từng dùng
  preview_split  — cho MainWindow viết lại phép tính bằng tay (đúng công thức cũ)
  no_seam        — điểm vào chung biến mất hẳn

Parent không sửa file nguồn nào; mọi lỗi chỉ sống trong bộ nhớ của con.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])  # noqa: F841

from core.timeline_model import ClipModel  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
import diagnostics  # noqa: E402


def apply(mode):
    if mode == "boundary":
        # Cach export viet truoc day: khong kep bien, playhead qua mat clip la
        # doc nguon vuot cua so clip.
        ClipModel.local_time_at = lambda self, t: max(
            0.0, float(t) - float(self.start_time))
        return
    if mode == "preview_split":
        # Preview tu viet lai phep tinh cua no. Chi can mot lan nhu the nay la
        # hai ben lai co hai bien khac nhau, va row phai do.
        def hand_rolled(self, current_time):
            local = 0.0
            for clip in ():
                local = max(0.0, min(float(current_time),
                                     clip.end_time - 0.000001) - clip.start_time)
            return local
        MainWindow._sync_canvas_frames_at_time = hand_rolled
        return
    if mode == "no_seam":
        del ClipModel.local_time_at
        return
    if mode != "clean":
        raise SystemExit("mode khong ton tai: " + mode)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    apply(mode)
    try:
        detail = diagnostics._local_time_ok()
    except Exception as exc:  # noqa: BLE001
        print("%s RED %s: %s" % (mode, type(exc).__name__, exc))
        return 1
    print("%s GREEN %s" % (mode, detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
