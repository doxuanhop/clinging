"""Con: chạy recap_ui_probe dưới một lỗi đã phát lại trong bộ nhớ. Không sửa file nào.

Mỗi mode cắt đúng MỘT mắt xích của chuỗi UI lớp phủ recap. Parent
(scratch/recap_ui_probe_counterfactual.py) kiểm tra lỗi đó làm gate nào đỏ — đỏ
sai chỗ cũng tính là probe giả.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scratch"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def patch(mode):
    if mode == "clean":
        return
    if mode == "button":
        # Chuỗi ba signal (nút header -> panel -> cửa sổ) đứt ở khớp cuối.
        from ui.main_window import MainWindow
        original = MainWindow.__init__

        def __init__(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.timeline_panel.recapOverlayRequested.disconnect(
                self._open_recap_overlay)
        MainWindow.__init__ = __init__
        return
    if mode == "apply":
        # Điều khiển vẫn sáng nhưng không bao giờ chạm tới model.
        from ui.recap_overlay_dialog import RecapOverlayDialog
        RecapOverlayDialog._apply = lambda self, *_a: None
        return
    if mode == "repaint":
        # Model đổi mà không ai bảo Canvas vẽ lại: kéo thanh trượt, khung đứng yên.
        from ui.main_window import MainWindow
        MainWindow._on_recap_overlay_changed = lambda self, _s: None
        return
    if mode == "undopush":
        # Đóng hộp thoại mà không ghi lịch sử -> mất cả thay đổi khi undo lần sau.
        from ui.recap_overlay_dialog import RecapOverlayDialog
        RecapOverlayDialog._on_close = lambda self: self.close()
        return
    if mode == "before":
        # Lệnh undo tự snapshot lúc tạo TRONG KHI model đã ở trạng thái "sau":
        # undo trở thành phép thế chỗ cho chính nó.
        from core.commands import SetRecapOverlayCommand
        original = SetRecapOverlayCommand.__init__

        def __init__(self, model, settings, before=None):
            original(self, model, settings, None)
        SetRecapOverlayCommand.__init__ = __init__
        return
    if mode == "refresh":
        # Hộp thoại dùng lại, mở lên mà không đọc model -> hiện đúng trạng thái
        # của lần trước (sau undo là master đã tắt nhưng hộp vẫn bật).
        from ui.recap_overlay_dialog import RecapOverlayDialog
        RecapOverlayDialog.refresh = lambda self: None
        return
    if mode == "drawfg":
        from ui.preview_panel import PreviewCanvas
        PreviewCanvas.drawForeground = lambda self, painter, rect: None
        return
    if mode == "bind":
        # Dự án trống không có clip nào -> sync_scene_from_model không chạy ->
        # canvas không biết model là ai, lớp phủ biến mất khỏi khung.
        from ui.preview_panel import PreviewCanvas
        PreviewCanvas.bind_model = lambda self, model: None
        return
    if mode == "chrome":
        # Thêm điều khiển mà không thêm cuộn: thân hộp thoại cao hơn màn hình,
        # nửa dưới (có nút Đóng) nằm ngoài tầm bấm.
        from ui.recap_overlay_dialog import RecapOverlayDialog
        original = RecapOverlayDialog.__init__

        def __init__(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.setMinimumHeight(3000)
        RecapOverlayDialog.__init__ = __init__
        return
    raise SystemExit("mode khong biet: %r" % mode)


def main():
    patch(sys.argv[1])
    import recap_ui_probe as P
    return P.main()


if __name__ == "__main__":
    sys.exit(main())
