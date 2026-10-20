"""
ui/main_controller.py
MainController - Tổng quản chuyển đổi giữa Trang chủ và Trang dựng phim.
Sử dụng QStackedWidget để chuyển trang mượt mà.
"""

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize, QPoint, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QToolButton, QLabel
)

from ui.home_page import HomePage
from ui.main_window import MainWindow


def _make_app_icon():
    from widgets.common import app_icon
    return app_icon()


def _icon(name, color="#9A9DAA"):
    """Helper tạo icon qua qta."""
    import qtawesome as qta
    return qta.icon(name, color=color)


class ControllerTitleBar(QWidget):
    """Thanh tiêu đề tùy chỉnh cho MainController (trang chủ)."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window  # window IS MainController (top-level)
        self._drag_pos = None

        self.setFixedHeight(56)
        self.setStyleSheet("background-color: #0D0E15; border-bottom: 1px solid #1C1E27;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(12)

        # ── Logo + Tên app ──
        from widgets.common import LogoBadge
        logo = LogoBadge(size=30)
        layout.addWidget(logo)

        name = QLabel("Clinging")
        name.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF; letter-spacing: 1px;")
        layout.addWidget(name)

        # Project search was decorative only, so the Home title bar keeps a
        # single flexible gap between branding and utility controls.
        layout.addStretch(1)

        # ── Utility icons ──
        icon_style = """
            QToolButton {
                background: transparent;
                border: none;
                color: #9A9DAA;
                border-radius: 14px;
            }
            QToolButton:hover {
                background-color: #1A1B22;
                color: #FFFFFF;
            }
        """

        self._btn_help = QToolButton()
        self._btn_help.setIcon(_icon("fa6s.circle-question"))
        self._btn_help.setIconSize(QSize(16, 16))
        self._btn_help.setFixedSize(32, 32)
        self._btn_help.setStyleSheet(icon_style)
        self._btn_help.setCursor(Qt.PointingHandCursor)
        self._btn_help.setToolTip("Trợ giúp")

        self._btn_notify = QToolButton()
        self._btn_notify.setIcon(_icon("fa6s.bell"))
        self._btn_notify.setIconSize(QSize(16, 16))
        self._btn_notify.setFixedSize(32, 32)
        self._btn_notify.setStyleSheet(icon_style)
        self._btn_notify.setCursor(Qt.PointingHandCursor)
        self._btn_notify.setToolTip("Thông báo")

        self._btn_settings = QToolButton()
        self._btn_settings.setIcon(_icon("fa6s.gear"))
        self._btn_settings.setIconSize(QSize(16, 16))
        self._btn_settings.setFixedSize(32, 32)
        self._btn_settings.setStyleSheet(icon_style)
        self._btn_settings.setCursor(Qt.PointingHandCursor)
        self._btn_settings.setToolTip("Cài đặt")

        for b in (self._btn_help, self._btn_notify, self._btn_settings):
            layout.addWidget(b)

        layout.addSpacing(8)

        # ── Nút cửa sổ ──
        self._btn_min = QToolButton()
        self._btn_min.setIcon(_icon("fa6s.minus"))
        self._btn_min.setIconSize(QSize(12, 12))
        self._btn_min.setFixedSize(28, 28)
        self._btn_min.setToolTip("Thu nhỏ")
        self._btn_min.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self._btn_min.setCursor(Qt.PointingHandCursor)
        self._btn_min.clicked.connect(self._safe_minimize)
        self._btn_min.enterEvent = lambda e: self._btn_min.setStyleSheet(
            "background-color: #3A3C4A; border: none; color: white; border-radius: 4px;"
        )
        self._btn_min.leaveEvent = lambda e: self._btn_min.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        self._btn_max = QToolButton()
        self._btn_max.setIcon(_icon("fa6s.square"))
        self._btn_max.setIconSize(QSize(10, 10))
        self._btn_max.setFixedSize(28, 28)
        self._btn_max.setToolTip("Phóng to / Khôi phục")
        self._btn_max.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self._btn_max.setCursor(Qt.PointingHandCursor)
        self._btn_max.clicked.connect(self._toggle_max)
        self._btn_max.enterEvent = lambda e: self._btn_max.setStyleSheet(
            "background-color: #3A3C4A; border: none; color: white; border-radius: 4px;"
        )
        self._btn_max.leaveEvent = lambda e: self._btn_max.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        self._btn_close = QToolButton()
        self._btn_close.setIcon(_icon("fa6s.xmark"))
        self._btn_close.setIconSize(QSize(12, 12))
        self._btn_close.setFixedSize(28, 28)
        self._btn_close.setToolTip("Đóng ứng dụng")
        self._btn_close.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self._btn_close.setCursor(Qt.PointingHandCursor)
        self._btn_close.clicked.connect(self._window.close)
        self._btn_close.enterEvent = lambda e: self._btn_close.setStyleSheet(
            "background-color: #E81123; border: none; color: white; border-radius: 4px;"
        )
        self._btn_close.leaveEvent = lambda e: self._btn_close.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        for b in (self._btn_min, self._btn_max, self._btn_close):
            layout.addWidget(b)

        self._update_max_icon()

    def _safe_minimize(self):
        self._window.showMinimized()

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _update_max_icon(self):
        if self._window.isMaximized():
            self._btn_max.setIcon(_icon("fa6s.window-restore"))
            self._btn_max.setToolTip("Khôi phục")
        else:
            self._btn_max.setIcon(_icon("fa6s.square"))
            self._btn_max.setToolTip("Phóng to")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self._toggle_max()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class MainController(QMainWindow):
    """
    Tổng quản điều khiển việc chuyển đổi giữa:
    - Trang chủ (HomePage): Quản lý dự án
    - Trang dựng phim (MainWindow): Timeline + Canvas + Properties
    """

    _resize_margin = 8
    _resize_edge = None
    _resize_start_pos = None
    _resize_start_geo = None

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clinging - Video Editor")
        self.setWindowIcon(_make_app_icon())
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        root = QWidget()
        root.setObjectName("RootWindow")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = ControllerTitleBar(self)
        root_layout.addWidget(self.title_bar)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.home_page = HomePage()
        self.editor_page = None

        self.stack.addWidget(self.home_page)

        self.home_page.createProject.connect(self._on_create_project)
        self.home_page.openProject.connect(self._on_open_project)

        self.title_bar._btn_settings.clicked.connect(self._on_open_settings)
        self.title_bar._btn_help.clicked.connect(self._on_open_help)
        self.title_bar._btn_notify.clicked.connect(self._on_open_notifications)

        self._apply_stylesheet()
    
    def _on_create_project(self, project_name, clinq_file_path):
        """Tạo dự án mới và chuyển sang trang dựng phim."""
        from core.project_storage import ProjectManager
        pm = ProjectManager()
        pm.project_path = clinq_file_path

        self._init_editor()
        self.stack.setCurrentWidget(self.editor_page)
        self.title_bar.hide()

        # Cập nhật tên project trên title bar editor
        self.editor_page.title_bar.project_name.setText(project_name)

    def open_project_path(self, project_path):
        """Mở dự án được giao từ NGOÀI app: dòng lệnh hoặc một cú nhấp đúp
        file .clinq của Explorer.

        Mọi đường đều phải đi qua ``_on_open_project`` — đúng hàm thẻ ở Home
        gọi — vì một lối load thứ hai luôn đúng với source mà sai với bản đã
        cài: đó là chỗ dự án mở ra với timeline trống hoặc thiếu thư viện.
        Trả False khi đường dẫn không phải file .clinq thật, để caller về Home
        thay vì mở một cửa sổ dựng phim rỗng.
        """
        import os
        path = os.path.abspath(str(project_path or ""))
        if not path.lower().endswith(".clinq") or not os.path.isfile(path):
            return False
        self._on_open_project(path)
        return True

    def _on_open_project(self, project_path):
        """Mở dự án có sẵn và chuyển sang trang dựng phim."""
        from core.project_storage import ProjectManager
        pm = ProjectManager()
        pm.project_path = project_path

        self._init_editor()
        self.stack.setCurrentWidget(self.editor_page)
        self.title_bar.hide()

        # Load dự án vào editor
        from core.project_storage import load_project_from_file, restore_model_from_clinq
        project = load_project_from_file(project_path)
        if project:
            restore_model_from_clinq(self.editor_page.timeline_panel.model, project)
            self.editor_page.restore_library_from_project(project)
            self.editor_page._sync_canvas()

            meta = project.get("project_meta", {})
            project_name = meta.get("project_name", "")
            if project_name:
                self.editor_page.title_bar.project_name.setText(project_name)

            aspect_ratio = meta.get("aspect_ratio", "16:9")
            ratio_display = {
                "16:9": "16:9 - Ngang chuẩn",
                "19:6": "19:6 - Siêu rộng",
                "9:16": "9:16 - Đứng Shorts/Tiktok",
                "1:1": "1:1 - Vuông",
                "4:3": "4:3 - Cổ điển",
            }.get(aspect_ratio, "16:9 - Ngang chuẩn")
            self.editor_page.timeline_panel.header.combo_aspect_ratio.setCurrentText(ratio_display)

    def _init_editor(self):
        """Lazy init trang editor."""
        if self.editor_page is None:
            self.editor_page = MainWindow()
            self.stack.addWidget(self.editor_page)
            self.editor_page.title_bar.goToHome.connect(self.show_home)

    def show_home(self):
        """Quay về trang chủ — tự động lưu trước khi rời đi."""
        if self.editor_page:
            self.editor_page._auto_save()
        self.stack.setCurrentWidget(self.home_page)
        self.title_bar.show()
        # Refresh danh sách gần đây
        if hasattr(self.home_page, '_load_recent_projects'):
            self.home_page._load_recent_projects()

    def _on_window_state_changed(self):
        """Cập nhật icon maximize/restore trên cả 2 title bar khi trạng thái cửa sổ thay đổi."""
        self.title_bar._update_max_icon()
        if self.editor_page and self.editor_page.title_bar:
            self.editor_page.title_bar._update_max_icon()

    def _on_open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.settingsApplied.connect(self._on_settings_applied)
        dialog.exec()

    def _on_settings_applied(self, values):
        """Cửa sổ nào đang sống phải đọc cài đặt mới ngay, không chờ dựng lại."""
        if self.editor_page is not None:
            self.editor_page._apply_settings()
        if hasattr(self.home_page, "refresh_settings"):
            self.home_page.refresh_settings()

    def _on_open_help(self):
        from ui.custom_dialog import CustomDialog
        dialog = CustomDialog(
            "Trợ giúp",
            "Nếu bạn cần hỗ trợ, hãy gửi email tới:\n\n"
            "dxhop96@gmail.com",
            self,
            icon_type="question",
            buttons=[("Gửi email", "accept"), ("Đóng", "reject")],
            default_button=0,
        )
        dialog.exec()
        if dialog.result() == 0:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl("mailto:dxhop96@gmail.com"))

    def _on_open_notifications(self):
        from ui.custom_dialog import CustomDialog
        CustomDialog.information(
            self, "Thông báo",
            "Các tính năng và thông báo mới sẽ được cập nhật "
            "trong bản cập nhật tiếp theo.",
        )

    # ── Window Resize (8 cạnh) ─────────────────────────────────

    def _get_resize_edge(self, pos):
        rect = self.rect()
        x, y = pos.x(), pos.y()
        m = self._resize_margin
        on_left = x < m
        on_right = x > rect.width() - m
        on_top = y < m
        on_bottom = y > rect.height() - m
        if on_top and on_left:
            return Qt.TopLeftEdge
        if on_top and on_right:
            return Qt.TopRightEdge
        if on_bottom and on_left:
            return Qt.BottomLeftEdge
        if on_bottom and on_right:
            return Qt.BottomRightEdge
        if on_top:
            return Qt.TopEdge
        if on_bottom:
            return Qt.BottomEdge
        if on_left:
            return Qt.LeftEdge
        if on_right:
            return Qt.RightEdge
        return None

    def _get_resize_cursor(self, edge):
        cursors = {
            Qt.TopLeftEdge: Qt.SizeFDiagCursor,
            Qt.TopRightEdge: Qt.SizeBDiagCursor,
            Qt.BottomLeftEdge: Qt.SizeBDiagCursor,
            Qt.BottomRightEdge: Qt.SizeFDiagCursor,
            Qt.TopEdge: Qt.SizeVerCursor,
            Qt.BottomEdge: Qt.SizeVerCursor,
            Qt.LeftEdge: Qt.SizeHorCursor,
            Qt.RightEdge: Qt.SizeHorCursor,
        }
        return cursors.get(edge, Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._get_resize_edge(event.pos())
            if edge:
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edge:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geo = self._resize_start_geo
            min_size = self.minimumSize()
            new_geo = geo.adjusted(0, 0, 0, 0)
            if self._resize_edge & Qt.LeftEdge:
                if geo.width() - delta.x() >= min_size.width():
                    new_geo.setLeft(geo.left() + delta.x())
            if self._resize_edge & Qt.RightEdge:
                if geo.width() + delta.x() >= min_size.width():
                    new_geo.setRight(geo.right() + delta.x())
            if self._resize_edge & Qt.TopEdge:
                if geo.height() - delta.y() >= min_size.height():
                    new_geo.setTop(geo.top() + delta.y())
            if self._resize_edge & Qt.BottomEdge:
                if geo.height() + delta.y() >= min_size.height():
                    new_geo.setBottom(geo.bottom() + delta.y())
            self.setGeometry(new_geo)
            event.accept()
        else:
            if not self.isMaximized():
                edge = self._get_resize_edge(event.pos())
                if edge:
                    self.setCursor(self._get_resize_cursor(edge))
                else:
                    self.setCursor(Qt.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_edge = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.stack.updateGeometry()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            self._on_window_state_changed()
        super().changeEvent(event)
    
    def _apply_stylesheet(self):
        """Áp dụng stylesheet cho MainController."""
        self.setStyleSheet("""
            #RootWindow {
                background-color: #0D0E15;
            }
            QMainWindow {
                background-color: #0D0E15;
            }
            QStackedWidget {
                background-color: #0D0E15;
            }
            #HomePage {
                background-color: #0D0E15;
            }
            #WelcomeTitle {
                font-size: 28px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #WelcomeDesc {
                font-size: 14px;
                color: #888888;
            }
            #SearchBar {
                background-color: #1A1B22;
                border: 1px solid #2A2C38;
                border-radius: 8px;
            }
            #NewProjectBtn {
                background-color: #2C6E64;
                color: #EAFFFB;
                border: 1px solid #40E0D0;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            #NewProjectBtn:hover {
                background-color: #348175;
            }
            #NewProjectDropdown {
                background-color: #2C6E64;
                color: #EAFFFB;
                border: 1px solid #40E0D0;
                border-left: 1px solid rgba(234,255,251,0.22);
                border-radius: 0 8px 8px 0;
                min-width: 38px; max-width: 38px;
                padding: 10px 0;
                font-weight: bold;
            }
            #NewProjectDropdown:hover { background-color: #348175; }
            #SectionFrame {
                background-color: #14151D;
                border: 1px solid #1E1F2E;
                border-radius: 12px;
            }
            #SectionTitle {
                font-size: 18px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #ProjectTemplateCard {
                background-color: #1A1B22;
                border: 1px solid #2A2C38;
                border-radius: 10px;
            }
            #ProjectTemplateCard:hover {
                border: 2px solid #40E0D0;
                background-color: #1E1F2E;
            }
            #TemplateName {
                font-size: 12px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #TemplateRes {
                font-size: 10px;
                color: #888888;
            }
            #TemplateDesc {
                font-size: 9px;
                color: #666666;
            }
            #CustomSizeBtn {
                background-color: transparent;
                color: #40E0D0;
                border: 1px solid #40E0D0;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            #CustomSizeBtn:hover {
                background-color: rgba(64, 224, 208, 0.12);
            }
            #RecentProjectCard {
                background-color: #1A1B22;
                border: 1px solid #2A2C38;
                border-radius: 10px;
            }
            #RecentProjectCard:hover {
                border: 2px solid #40E0D0;
            }
            #ProjectName {
                font-size: 12px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #EmptyTitle {
                font-size: 18px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #EmptyDesc {
                font-size: 13px;
                color: #888888;
            }
            #SystemMonitor {
                background-color: #14151D;
                border-right: 1px solid #1E1F2E;
            }
            #MonitorTitle {
                font-size: 14px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #MonitorItem {
                background-color: transparent;
            }
            #MonitorLabel {
                font-size: 12px;
                color: #CCCCCC;
            }
            #MonitorValue {
                font-size: 12px;
                font-weight: bold;
                color: #40E0D0;
            }
            #MonitorProgress, #MonitorProgressContainer {
                background-color: #1E1F2E;
                border-radius: 2px;
            }
            #ProgressBar, #MonitorProgressBar {
                background-color: #40E0D0;
                border-radius: 2px;
            }
            #SoftwareBy {
                font-size: 10px;
                color: #666666;
            }
            #BrandName {
                font-size: 12px;
                font-weight: bold;
                color: #40E0D0;
            }
            #ContactEmail {
                font-size: 10px;
                color: #888888;
            }
        """)
