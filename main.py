"""
main.py
Điểm khởi chạy ứng dụng Clinqing - Professional Video Editor.

Chạy:
    pip install -r requirements.txt
    python main.py
"""

import sys
import subprocess
import time

# Mốc thời gian đầu tiên Python với tới được. Bootloader của PyInstaller chạy
# trước dòng này, nên "tổng thời gian mở app" do probe đo từ ngoài vào luôn lớn
# hơn khoảng cộng của các pha ở dưới — chính phần chênh đó là chi phí của bundle.
_T0 = time.perf_counter()

# (tên pha, giây kể từ _T0, working set KiB). Chỉ --startup-report đọc nó.
BOOT_MARKS = []


def _working_set_kib():
    """RAM thật mà tiến trình đang giữ, không qua psutil (import psutil ~10 ms
    và sẽ bị tính nhầm vào pha đang đo)."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        import ctypes.wintypes

        class counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.wintypes.DWORD),
                        ("page_fault_count", ctypes.wintypes.DWORD),
                        ("peak_working_set", ctypes.c_size_t),
                        ("working_set", ctypes.c_size_t),
                        ("quota_peak_paged", ctypes.c_size_t),
                        ("quota_paged", ctypes.c_size_t),
                        ("quota_peak_nonpaged", ctypes.c_size_t),
                        ("quota_nonpaged", ctypes.c_size_t),
                        ("pagefile_usage", ctypes.c_size_t),
                        ("peak_pagefile_usage", ctypes.c_size_t),
                        ("private_usage", ctypes.c_size_t),
                        ("peak_private_usage", ctypes.c_size_t)]

        info = counters()
        info.cb = ctypes.sizeof(counters)
        # ctypes nghi nhan so nguyen ma khong co argtypes: handle gia cua
        # GetCurrentProcess() la 0xFFFFFFFFFFFFFFFF, no vuot c_int va nang
        # OverflowError len ngoai try. Chiu thi duoc 0, truong hop nay phai
        # khai bao kieu.
        handle = ctypes.c_void_p(0xFFFFFFFFFFFFFFFF)
        get_info = None
        # kernel32 xuat ham nay voi ten K32... tren Win Vista+; psapi chi la
        # duong lui cho he the he truoc.
        for lib, name in ((ctypes.windll.kernel32, "K32GetProcessMemoryInfo"),
                          (ctypes.windll.psapi, "GetProcessMemoryInfo")):
            try:
                get_info = getattr(lib, name)
            except AttributeError:
                continue
            break
        if get_info is None:
            return 0
        get_info.restype = ctypes.wintypes.BOOL
        get_info.argtypes = [ctypes.wintypes.HANDLE,
                             ctypes.POINTER(counters),
                             ctypes.wintypes.DWORD]
        if not get_info(handle, ctypes.byref(info), info.cb):
            return 0
        return int(info.working_set // 1024)
    except Exception:
        return 0


def _mark(name):
    BOOT_MARKS.append((name, time.perf_counter() - _T0, _working_set_kib()))


def _boot():
    """Đường khởi động THẬT. --startup-report dùng đúng hàm này, không có bản
    thứ hai: một đường boot riêng để đo là một đường không bao giờ chạy."""
    from PySide6.QtWidgets import QApplication
    from theme import theme_manager
    from ui.main_controller import MainController
    from widgets.common import app_icon
    _mark("import PySide6 + ui")

    _suppress_child_console_windows()
    _set_windows_app_user_model_id()

    from core import settings
    settings.reload()
    theme_manager.set_mode(settings.get("theme"))
    _mark("settings + theme")

    app = QApplication(sys.argv)
    app.setApplicationName("Clinging")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(theme_manager.stylesheet())
    _mark("QApplication + stylesheet")

    from core.project_storage import project_arg_from_argv
    controller = MainController()
    _mark("MainController()")
    controller.show()
    _mark("show()")

    project_path = project_arg_from_argv(sys.argv)
    if project_path:
        controller.open_project_path(project_path)
    return app, controller


def _suppress_child_console_windows():
    """Windows: chặn cửa sổ console đen chớp tắt khi thư viện sinh tiến trình con.

    pydub/ffmpeg, ffprobe, OpenCV... khi chạy ở chế độ GUI (không console) sẽ
    tự cấp phát một console riêng → hiện ra rồi tắt ngay khi thêm clip video/audio
    (lúc trích xuất sóng âm/thời lượng). Vá subprocess.Popen để mọi tiến trình con
    mặc định chạy ẩn, giao diện trông chuyên nghiệp.
    """
    if sys.platform != "win32":
        return
    if getattr(subprocess.Popen, "_no_window_patched", False):
        return

    create_no_window = 0x08000000  # CREATE_NO_WINDOW
    original_init = subprocess.Popen.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | create_no_window
        startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched_init
    subprocess.Popen._no_window_patched = True


def _set_windows_app_user_model_id():
    """Windows gộp mọi cửa sổ cùng AppUserModelID vào một nút taskbar và lấy icon
    từ chính ID đó. Không đặt thì app bị gộp vào python/pythonw và hiện icon Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "QeafivelsSoftware.Clinging")
    except Exception:
        pass


def main():
    if "--selftest" in sys.argv:
        # Bản đóng gói phải tự chứng minh được nó đủ mảnh lúc chạy.
        from diagnostics import run_selftest
        sys.exit(run_selftest())

    if "--layout-report" in sys.argv:
        # Đo tỉ lệ bố cục mặc định của đúng file exe này, không phải của source.
        from diagnostics import run_layout_report
        sys.exit(run_layout_report())

    if "--alignment-report" in sys.argv:
        from diagnostics import run_alignment_report
        sys.exit(run_alignment_report())

    if "--audio-report" in sys.argv:
        # Anh the Am thanh va chuoi filter xuat phai do tu chinh ban chay nay.
        from diagnostics import run_audio_report
        sys.exit(run_audio_report())

    if "--chrome-report" in sys.argv:
        # Nút bấm không ra gì không crash và không để lại dấu vết trong log,
        # nên phải do kết nối thật của chính bản đang chạy.
        from diagnostics import run_chrome_report
        sys.exit(run_chrome_report())

    if "--thumbnail-report" in sys.argv:
        # Ảnh PNG và cửa sổ trích xuất phải do bản đã cài tự tạo ra; đo từ
        # source thì không nói gì về bundle người ta nhận.
        from diagnostics import run_thumbnail_report
        sys.exit(run_thumbnail_report())

    if "--split-report" in sys.argv:
        # Chuột phải thật → hộp thoại thật → N file thật trên đĩa, do ffprobe và
        # màu của chính bundle đã cài đo lại.
        from diagnostics import run_split_report
        sys.exit(run_split_report())

    if "--graph-report" in sys.argv:
        # Đồ thị đường cong: cú kéo chuột thật phải làm model đổi, và ảnh chụp
        # chứng minh phải do chính bản đã cài vẽ ra.
        from diagnostics import run_graph_report
        sys.exit(run_graph_report())

    if "--project-report" in sys.argv:
        # Nhấp đúp .clinq mà mở nhầm trang là lỗi im lặng: app vẫn lên, chỉ là
        # không có dự án nào được mở. Phải do chính chuỗi argv của bản đã cài
        # đo, vì source luôn đúng.
        from diagnostics import run_project_report
        sys.exit(run_project_report())

    if "--style-report" in sys.argv:
        # Thẻ aura, hộp thoại lớp phủ và combo karaoke là những thứ chỉ hỏng khi
        # có người bấm: selftest đo đường vẽ trong bundle nhưng chưa từng chạm
        # vào một cái thẻ nào.
        from diagnostics import run_style_report
        sys.exit(run_style_report())

    if "--import-report" in sys.argv:
        # Module chi duoc dung khi nguoi dung mo hop thoai cua no thi khong co
        # gi chung minh no van con trong ban cai. Sweep nay nap het moi module
        # cua bundle va ra ma loi that.
        from diagnostics import run_import_report
        sys.exit(run_import_report())

    if "--startup-report" in sys.argv:
        # "Mở app chậm" không sửa được bằng cảm giác: phải do từng pha trên
        # chính bản đã cài, và RAM mà nó giữ lúc ngồi im.
        from diagnostics import run_startup_report
        sys.exit(run_startup_report())

    if "--library-report" in sys.argv:
        # "Thu vien lag" la mot loi phan nan, khong phai loi crash: no chi hien
        # khi luoi co hang chuc the va media nam tren HDD. Phai do tren dung
        # duong mo project cua ban nay, voi fixture that tren dia.
        from diagnostics import run_library_report
        sys.exit(run_library_report())

    if "--sfx-report" in sys.argv:
        # Pack SFX sống trong bundle (assets/sfx) va trong _internal cua ban cai,
        # khong phai trong tree nguon: chen ra clip ma khong co tieng nao tren dia
        # thi chi nguoi dung moi biet. Do tren duong cua nguoi dung — bam nut tren
        # thanh thoi, hop thoai that, chen that, roi do lai tung tieng.
        from diagnostics import run_sfx_report
        sys.exit(run_sfx_report())

    if "--transform-report" in sys.argv:
        # The "Bien doi" card (xoay tu do, lat, canh le, khoa ty le) co the xanh
        # tren so ma sai tren mat: mot ben dung co flip, ben kia im lang bo qua
        # (preview lat, export khong lat), hoac canh mep theo so CHUA xoay. Cac
        # con so duoi day do tu pixel ma FrameComposer ve ra, khong do tu model.
        from diagnostics import run_transform_report
        sys.exit(run_transform_report())

    if "--canvas-layout-report" in sys.argv:
        # Bo cuc + phong cách nam o NAM be mat ma --selftest khong nhin thay:
        # nut tren header, 22 khoa widget->model, doan gập cua body, pixel ma
        # FrameComposer ve tu chinh model do, va lenh "Dan clip vao o". Do tren
        # MainWindow that, khong tren fixture tu dung.
        from diagnostics import run_canvas_layout_report
        sys.exit(run_canvas_layout_report())

    # PySide6 tự động xử lý High DPI - không cần thiết lập thủ công
    app, controller = _boot()  # noqa: F841 (controller phải sống tới khi exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
