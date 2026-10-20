"""
ui/sidebar.py
Dải icon dọc bên trái: Thư viện, Âm thanh, Văn bản, Sticker, Hiệu ứng,
Chuyển cảnh, Bộ lọc. Mỗi mục chỉ đổi PANEL bên trái đang hiện, không có mục nào
mở một tính năng riêng — thêm một nút ở đây nghĩa là thêm một nhánh trong
MainWindow._on_sidebar_changed dẫn tới một bảng điều khiển có thật.
Dùng Font Awesome 6 Solid icons (prefix: fa6s).
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QButtonGroup, QSizePolicy,
    QScrollArea, QFrame
)

from widgets.common import IconButton, icon_color, _qta


SIDEBAR_WIDTH = 76   # đủ chỗ cho nhãn dài nhất ("Chuyển cảnh") thở


# (key, fa_icon, label)
SIDEBAR_ITEMS = [
    ("library", "fa6s.photo-film", "Thư viện"),
    ("audio", "fa6s.music", "Âm thanh"),
    ("text", "fa6s.font", "Văn bản"),
    ("sticker", "fa6s.face-smile", "Sticker"),
    ("effects", "fa6s.wand-magic-sparkles", "Hiệu ứng"),
    ("transition", "fa6s.arrows-left-right", "Chuyển cảnh"),
    ("filter", "fa6s.filter", "Bộ lọc"),
]


class SidebarButton(QToolButton):
    def __init__(self, icon_name, label, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self.setToolTip(label)
        self.setIcon(IconButton._qta_icon(icon_name, icon_color()))
        self.setIconSize(QSize(14, 14))
        self.setFixedSize(68, 48)
        f = self.font()
        f.setPointSize(8)
        self.setFont(f)


class Sidebar(QWidget):
    currentChanged = Signal(str)
    toggleTimelineRequested = Signal(bool) # Báo ẩn/hiện timeline

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── QScrollArea bọc ngoài và Ẩn Thanh Cuộn (Invisible scrollbar) ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # Không bao giờ hiển thị thanh cuộn
        scroll.setStyleSheet("background: transparent;")

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(4, 10, 4, 10)
        scroll_layout.setSpacing(6)
        scroll_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        # Nút Ẩn/Hiện Timeline (Đặt lên đầu cuộn) — kiểu giống SidebarButton
        self.btn_toggle_timeline = QToolButton()
        self.btn_toggle_timeline.setCheckable(True)
        self.btn_toggle_timeline.setChecked(True)
        self.btn_toggle_timeline.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_timeline.setObjectName("SidebarButton")
        self.btn_toggle_timeline.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.btn_toggle_timeline.setIcon(_qta().icon("fa6s.eye", color=icon_color()))
        self.btn_toggle_timeline.setIconSize(QSize(14, 14))
        self.btn_toggle_timeline.setText("Timeline")
        self.btn_toggle_timeline.setToolTip("Ẩn / Hiện Timeline")
        self.btn_toggle_timeline.setFixedSize(68, 48)
        f_tl = self.btn_toggle_timeline.font()
        f_tl.setPointSize(8)
        self.btn_toggle_timeline.setFont(f_tl)
        self.btn_toggle_timeline.clicked.connect(self._on_toggle_timeline)

        # Nút Thu gọn / Mở rộng Sidebar — kiểu giống SidebarButton
        scroll_layout.addWidget(self.btn_toggle_timeline)
        scroll_layout.addSpacing(10)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._keys = {}

        for i, (key, icon_name, label) in enumerate(SIDEBAR_ITEMS):
            btn = SidebarButton(icon_name, label)
            self.group.addButton(btn, i)
            self._keys[i] = key
            scroll_layout.addWidget(btn)
            if i == 0:
                btn.setChecked(True)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)

        self.group.idClicked.connect(self._emit_changed)

    def _emit_changed(self, idx):
        self.currentChanged.emit(self._keys[idx])

    def _on_toggle_timeline(self, checked):
        # Đổi icon
        icon_name = "fa6s.eye" if checked else "fa6s.eye-slash"
        self.btn_toggle_timeline.setIcon(_qta().icon(icon_name, color=icon_color()))
        self.toggleTimelineRequested.emit(checked)
