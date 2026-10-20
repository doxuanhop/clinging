"""
ui/title_bar.py
Thanh tiêu đề tùy biến (custom title bar) cho cửa sổ frameless:
- Icon + tên phần mềm + Menu dropdown
- Cho phép kéo di chuyển cửa sổ bằng chuột
- Nút thu nhỏ / phóng to / đóng
Dùng Font Awesome 6 Solid icons (prefix: fa6s).
"""

from PySide6.QtCore import Qt, QPoint, QSize, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton, QMenu

from widgets.common import set_label_icon, _qta, icon_color, IconButton


class TitleBar(QWidget):
    # Signal khi chọn "Quay về trang chủ"
    goToHome = Signal()
    undoRequested = Signal()
    redoRequested = Signal()
    splitRequested = Signal()
    deleteRequested = Signal()
    duplicateRequested = Signal()
    playRequested = Signal()
    previousFrameRequested = Signal()
    nextFrameRequested = Signal()
    autoCaptionsRequested = Signal()
    subtitleImportRequested = Signal()
    shortcutsRequested = Signal()
    aboutRequested = Signal()
    
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window.window()  # Luôn lấy top-level QMainWindow (MainController)
        self._drag_pos = None
        from widgets.common import LogoBadge, add_shadow, VSeparator
        
        self.setFixedHeight(48)
        self.setStyleSheet("background-color: #0B0C10; border-bottom: 1px solid #1C1E27;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(10)

        # ── Menu Dropdown ──
        self.menu_btn = QToolButton()
        self.menu_btn.setText("  Menu  ")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setFixedHeight(28)
        self.menu_btn.setStyleSheet("""
            QToolButton {
                background-color: #1A1B22;
                color: #CCCCCC;
                border: 1px solid #2A2C38;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QToolButton:hover {
                background-color: #252836;
                border-color: #3A3D4E;
            }
            QToolButton::menu-indicator {
                image: none;
                width: 12px;
                subcontrol-position: right center;
            }
        """)
        
        # Tạo dropdown menu
        self._create_menus()

        from PySide6.QtWidgets import QLineEdit
        self.project_name = QLineEdit("Dự án trống")
        self.project_name.setObjectName("ProjectLabel")
        self.project_name.setFrame(False)
        self.project_name.setFixedWidth(120)
        self.project_name.setReadOnly(True)
        self.project_name.setAlignment(Qt.AlignCenter)
        self.project_name.editingFinished.connect(lambda: self.project_name.setReadOnly(True))
        self.project_name.setStyleSheet("background: transparent; color: #E0E0E0; font-size: 12px;")

        edit_btn = IconButton("", "Đổi tên dự án", size=24, font_size=11,
                               icon_name="fa6s.pen")
        edit_btn.clicked.connect(self._enable_rename)

        layout.addWidget(self.menu_btn)
        layout.addStretch(1)
        layout.addStretch(1)

        # ── Tên dự án căn giữa cửa sổ ──
        # Logo đã bị gỡ bỏ nên đặt project_name + nút đổi tên vào một khung nổi
        # (overlay) là con trực tiếp của TitleBar. Khung này được tự căn chính
        # giữa theo chiều ngang cửa sổ trong resizeEvent → luôn nằm ở trung tâm
        # dù cửa sổ thay đổi kích thước, không bị lệch bởi các nút ở hai bên.
        self._center_box = QWidget(self)
        _center_layout = QHBoxLayout(self._center_box)
        _center_layout.setContentsMargins(0, 0, 0, 0)
        _center_layout.setSpacing(4)
        _center_layout.addWidget(self.project_name)
        _center_layout.addWidget(edit_btn)

        # ── Vùng bên phải: Nút Save & Export & Window Actions ──
        from PySide6.QtWidgets import QPushButton
        
        self.save_btn = QPushButton("  Lưu")
        self.save_btn.setObjectName("SaveButton")
        self.save_btn.setIcon(_qta().icon("fa6s.floppy-disk", color=icon_color()))
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setToolTip("Lưu dự án (Ctrl+S)")
        self.save_btn.setFixedHeight(28)
        self.save_btn.setStyleSheet("font-size: 11px; padding: 2px 10px; background-color: #121318; border: 1px solid #23242E; color: #D1D5DB; border-radius: 6px;")

        self.export_main = QPushButton("  Xuất video")
        self.export_main.setObjectName("ExportButton")
        self.export_main.setIcon(_qta().icon("fa6s.download", color=icon_color()))
        self.export_main.setCursor(Qt.PointingHandCursor)
        self.export_main.setToolTip("Xuất video (Ctrl+E)")
        self.export_main.setFixedHeight(28)
        self.export_main.setMinimumWidth(118)
        self.export_main.setStyleSheet("font-size: 11px; padding: 2px 14px; background-color: #2C6E64; color: #EAFFFB; border: 1px solid #40E0D0; border-radius: 8px; font-weight: 600;")
        add_shadow(self.export_main, blur=20, offset=(0, 4))

        self.export_drop = QPushButton()
        self.export_drop.setObjectName("ExportDropdown")
        self.export_drop.setIcon(_qta().icon("fa6s.caret-down", color=icon_color()))
        self.export_drop.setCursor(Qt.PointingHandCursor)
        self.export_drop.setToolTip("Tùy chọn xuất video")
        self.export_drop.setFixedSize(22, 28)
        self.export_drop.clicked.connect(self._show_export_presets)
        self.export_drop.setStyleSheet("background-color: #2C6E64; border: 1px solid #40E0D0; border-left: 1px solid rgba(255,255,255,0.18); border-radius: 0 7px 7px 0; color: #EAFFFB;")
        self.export_drop.hide()

        layout.addWidget(self.save_btn)
        layout.addSpacing(4)
        layout.addWidget(self.export_main)
        layout.addSpacing(8)
        layout.addWidget(VSeparator(height=18))
        layout.addSpacing(4)

        self.btn_min = QToolButton()
        self.btn_min.setObjectName("TitleMinBtn")
        self.btn_min.setIcon(_qta().icon("fa6s.minus", color=icon_color()))
        self.btn_min.setIconSize(QSize(12, 12))
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setToolTip("Thu nhỏ")
        self.btn_min.clicked.connect(self._safe_minimize)
        self.btn_min.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self.btn_min.setCursor(Qt.PointingHandCursor)
        self.btn_min.enterEvent = lambda e: self.btn_min.setStyleSheet(
            "background-color: #3A3C4A; border: none; color: white; border-radius: 4px;"
        )
        self.btn_min.leaveEvent = lambda e: self.btn_min.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        self.btn_max = QToolButton()
        self.btn_max.setObjectName("TitleMaxBtn")
        self.btn_max.setIcon(_qta().icon("fa6s.square", color=icon_color()))
        self.btn_max.setIconSize(QSize(10, 10))
        self.btn_max.setFixedSize(28, 28)
        self.btn_max.setToolTip("Phóng to / Khôi phục")
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_max.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self.btn_max.setCursor(Qt.PointingHandCursor)
        self.btn_max.enterEvent = lambda e: self.btn_max.setStyleSheet(
            "background-color: #3A3C4A; border: none; color: white; border-radius: 4px;"
        )
        self.btn_max.leaveEvent = lambda e: self.btn_max.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        self.btn_close = QToolButton()
        self.btn_close.setObjectName("TitleCloseBtn")
        self.btn_close.setIcon(_qta().icon("fa6s.xmark", color=icon_color()))
        self.btn_close.setIconSize(QSize(12, 12))
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip("Đóng (Quay về trang chủ)")
        self.btn_close.clicked.connect(self.goToHome.emit)
        self.btn_close.setStyleSheet("background: transparent; border: none; color: #9A9DAA;")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.enterEvent = lambda e: self.btn_close.setStyleSheet(
            "background-color: #E81123; border: none; color: white; border-radius: 4px;"
        )
        self.btn_close.leaveEvent = lambda e: self.btn_close.setStyleSheet(
            "background: transparent; border: none; color: #9A9DAA;"
        )

        for b in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(b)

    def _create_menus(self):
        """Tạo các menu dropdown cho Title Bar."""
        menu_style = """
            QMenu {
                background-color: #232323;
                color: #D8DCE0;
                border: 1px solid #3A3A3A;
                border-radius: 9px;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 30px 8px 12px;
                border-radius: 6px;
                margin: 1px 0;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(64, 224, 208, 0.16);
                color: #EAFFFB;
            }
            QMenu::separator {
                height: 1px;
                background: #3A3A3A;
                margin: 6px 4px;
            }
            QMenu::item:disabled {
                color: #62686E;
            }
            QMenu::right-arrow {
                image: url(styles/chevron-right.svg);
                width: 12px;
                height: 12px;
                margin-right: 7px;
            }
        """
        
        # Main menu
        self.main_menu = QMenu()
        self.main_menu.setStyleSheet(menu_style)
        self.main_menu.setWindowFlags(self.main_menu.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # ── File menu ──
        file_menu = QMenu("Tệp tin", self.main_menu)
        file_menu.setIcon(_qta().icon("fa6s.file", color="#40E0D0"))
        file_menu.addAction(_qta().icon("fa6s.plus", color="#CCCCCC"), "Dự án mới", self._on_new_project)
        file_menu.addAction(_qta().icon("fa6s.folder-open", color="#CCCCCC"), "Mở dự án...", self._on_open_project)
        file_menu.addSeparator()
        file_menu.addAction(_qta().icon("fa6s.floppy-disk", color="#CCCCCC"), "Lưu dự án", self._on_save)
        file_menu.addAction(_qta().icon("fa6s.download", color="#CCCCCC"), "Xuất video...", self._on_export)
        file_menu.addSeparator()
        file_menu.addAction(_qta().icon("fa6s.right-from-bracket", color="#CCCCCC"), "Quay về trang chủ", self._on_go_home)
        self.main_menu.addMenu(file_menu)
        
        # ── Edit menu ──
        edit_menu = QMenu("Chỉnh sửa", self.main_menu)
        edit_menu.setIcon(_qta().icon("fa6s.pencil", color="#40E0D0"))
        edit_menu.addAction(_qta().icon("fa6s.rotate-left", color="#CCCCCC"), "Hoàn tác (Ctrl+Z)", self.undoRequested.emit)
        edit_menu.addAction(_qta().icon("fa6s.rotate-right", color="#CCCCCC"), "Làm lại (Ctrl+Y)", self.redoRequested.emit)
        edit_menu.addSeparator()
        edit_menu.addAction(_qta().icon("fa6s.scissors", color="#CCCCCC"), "Cắt (S)", self.splitRequested.emit)
        edit_menu.addAction(_qta().icon("fa6s.trash", color="#CCCCCC"), "Xóa (Del)", self.deleteRequested.emit)
        edit_menu.addAction(_qta().icon("fa6s.clone", color="#CCCCCC"), "Nhân bản (Ctrl+D)", self.duplicateRequested.emit)
        self.main_menu.addMenu(edit_menu)
        
        # ── View menu ──
        view_menu = QMenu("Hiển thị", self.main_menu)
        view_menu.setIcon(_qta().icon("fa6s.eye", color="#40E0D0"))
        view_menu.addAction(_qta().icon("fa6s.expand", color="#CCCCCC"), "Toàn màn hình", self._toggle_max)
        view_menu.addAction(_qta().icon("fa6s.minimize", color="#CCCCCC"), "Thu nhỏ", self._safe_minimize)
        self.main_menu.addMenu(view_menu)
        
        # ── Timeline menu ──
        timeline_menu = QMenu("Timeline", self.main_menu)
        timeline_menu.setIcon(_qta().icon("fa6s.timeline", color="#40E0D0"))
        timeline_menu.addAction(_qta().icon("fa6s.play", color="#CCCCCC"), "Phát / Tạm dừng", self.playRequested.emit)
        timeline_menu.addAction(_qta().icon("fa6s.backward", color="#CCCCCC"), "Khung trước", self.previousFrameRequested.emit)
        timeline_menu.addAction(_qta().icon("fa6s.forward", color="#CCCCCC"), "Khung kế tiếp", self.nextFrameRequested.emit)
        timeline_menu.addSeparator()
        timeline_menu.addAction(_qta().icon("fa6s.scissors", color="#CCCCCC"), "Cắt tại Playhead", self.splitRequested.emit)
        self.main_menu.addMenu(timeline_menu)

        # ── Captions menu ──
        captions_menu = QMenu("Phụ đề", self.main_menu)
        captions_menu.setIcon(_qta().icon("fa6s.closed-captioning", color="#40E0D0"))
        captions_menu.addAction(_qta().icon("fa6s.microphone", color="#CCCCCC"),
                                "Nhận phụ đề tự động...",
                                self.autoCaptionsRequested.emit)
        captions_menu.addAction(_qta().icon("fa6s.file-import", color="#CCCCCC"),
                                "Nhập file phụ đề...",
                                self.subtitleImportRequested.emit)
        self.main_menu.addMenu(captions_menu)

        self.main_menu.addSeparator()
        
        # ── Help menu ──
        help_menu = QMenu("Trợ giúp", self.main_menu)
        help_menu.setIcon(_qta().icon("fa6s.circle-question", color="#40E0D0"))
        help_menu.addAction(_qta().icon("fa6s.keyboard", color="#CCCCCC"),
                                "Phím tắt", self.shortcutsRequested.emit)
        help_menu.addAction(_qta().icon("fa6s.circle-info", color="#CCCCCC"),
                            "Về Clinging", self.aboutRequested.emit)
        self.main_menu.addMenu(help_menu)
        
        # Gán menu vào nút
        self.menu_btn.setMenu(self.main_menu)

    def _on_new_project(self):
        """Tạo dự án mới."""
        self.goToHome.emit()

    def _on_open_project(self):
        """Mở dự án."""
        self.goToHome.emit()

    def _on_save(self):
        """Lưu dự án."""
        self.save_btn.click()

    def _on_export(self):
        """Xuất video."""
        self.export_main.click()

    def _show_export_presets(self):
        """Menu preset độ phân giải theo kiểu split-button của CapCut."""
        menu = QMenu(self)
        resolution_menu = menu.addMenu("Độ phân giải")
        for preset in ("480p", "720p", "1080p", "1K", "2K", "4K"):
            action = resolution_menu.addAction(preset)
            action.triggered.connect(
                lambda checked=False, value=preset: self._export_with_preset(value)
            )
        menu.addSeparator()
        menu.addAction("Tùy chỉnh xuất...", self._on_export)
        menu.exec(self.export_drop.mapToGlobal(self.export_drop.rect().bottomRight()))

    def _export_with_preset(self, preset):
        self.window().setProperty("preferredExportResolution", preset)
        self._on_export()

    def _on_go_home(self):
        """Quay về trang chủ."""
        self.goToHome.emit()

    def _enable_rename(self):
        self.project_name.setReadOnly(False)
        self.project_name.setFocus()
        self.project_name.selectAll()

    def _safe_minimize(self):
        self.window().showMinimized()

    def _toggle_max(self):
        host = self.window()
        if host.isMaximized():
            host.showNormal()
        else:
            host.showMaximized()
        self._update_max_icon()

    def _update_max_icon(self):
        if self.window().isMaximized():
            self.btn_max.setIcon(_qta().icon("fa6s.window-restore", color=icon_color()))
            self.btn_max.setToolTip("Khôi phục")
        else:
            self.btn_max.setIcon(_qta().icon("fa6s.square", color=icon_color()))
            self.btn_max.setToolTip("Phóng to / Khôi phục")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._center_project_name()

    def _center_project_name(self):
        """Căn khung tên dự án vào chính giữa TitleBar theo cả hai chiều."""
        box = getattr(self, "_center_box", None)
        if box is None:
            return
        box.adjustSize()
        w = box.sizeHint().width()
        h = box.sizeHint().height()
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        box.setGeometry(x, y, w, h)
        box.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self._toggle_max()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
