"""
ui/presets_panel.py
Panel hiển thị các preset (Văn bản, Sticker) có thể kéo thả vào canvas.
Khi sidebar chọn "Văn bản" hoặc "Sticker", panel này xuất hiện thay cho Library.
"""

from PySide6.QtCore import Qt, QMimeData, Signal, QSize
from PySide6.QtGui import QDrag, QFont, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QGridLayout, QSizePolicy, QPushButton, QApplication
)

from widgets.common import (set_label_icon, icon_color, icon_pixmap,
                            font_icon)


TEXT_PRESETS = [
    {"label": "Tiêu đề lớn", "font": "Arial", "size": 60, "bold": True, "color": "#FFFFFF"},
    {"label": "Phụ đề", "font": "Arial", "size": 32, "bold": False, "color": "#FFFFFF"},
    {"label": "Caption", "font": "Segoe UI", "size": 24, "bold": False, "color": "#FFD700"},
    {"label": "Title Card", "font": "Impact", "size": 48, "bold": True, "color": "#FF4444"},
    {"label": "Nhãn nhỏ", "font": "Segoe UI", "size": 18, "bold": False, "color": "#AAAAAA"},
    {"label": "Slogan", "font": "Georgia", "size": 36, "bold": True, "color": "#00FF88"},
]

STICKER_PRESETS = [
    {"label": "Thích", "icon": "fa6s.thumbs-up", "color": "#40E0D0"},
    {"label": "Tim", "icon": "fa6s.heart", "color": "#FF5A6E"},
    {"label": "Sao", "icon": "fa6s.star", "color": "#FFD45A"},
    {"label": "Lửa", "icon": "fa6s.fire", "color": "#FF8A3D"},
    {"label": "Xác nhận", "icon": "fa6s.circle-check", "color": "#57D68D"},
    {"label": "Cảnh báo", "icon": "fa6s.triangle-exclamation", "color": "#FFC857"},
]


class PresetDragCard(QFrame):
    """Thẻ preset có thể kéo thả vào canvas."""

    previewRequested = Signal(dict, str)
    addRequested = Signal(dict, str)

    def __init__(self, preset_data, preset_type="text", parent=None):
        super().__init__(parent)
        self.preset_data = preset_data
        self.preset_type = preset_type
        self.setObjectName("PresetCard")
        self.setFixedSize(140, 100)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"{preset_data.get('label', '')}\nNhấp: xem thử • Kích đúp: thêm")
        self._drag_start = None
        self._did_drag = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # Preview area
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedSize(124, 50)
        self.preview.setStyleSheet("""
            QLabel {
                background-color: #1A1B22;
                border: 1px solid #2A2C38;
                border-radius: 6px;
            }
        """)

        if preset_type == "text":
            self._render_text_preview()
        else:
            self._render_sticker_preview()

        name = QLabel(preset_data.get("label", ""))
        name.setObjectName("PresetLabel")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("font-size: 10px; color: #9A9DAA;")
        name.setWordWrap(True)

        layout.addWidget(self.preview, alignment=Qt.AlignHCenter)
        layout.addWidget(name)

        self.add_button = QPushButton(self)
        self.add_button.setObjectName("PresetAddButton")
        self.add_button.setIcon(font_icon("fa6s.plus", "#FFFFFF"))
        self.add_button.setIconSize(QSize(11, 11))
        self.add_button.setToolTip("Thêm vào video")
        self.add_button.setFixedSize(22, 22)
        self.add_button.move(self.width() - 28, 6)
        self.add_button.raise_()
        self.add_button.clicked.connect(
            lambda: self.addRequested.emit(dict(self.preset_data), self.preset_type)
        )

    def _render_text_preview(self):
        pixmap = QPixmap(124, 50)
        pixmap.fill(QColor("#1A1B22"))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)

        font_name = self.preset_data.get("font", "Arial")
        font_size = max(8, min(16, self.preset_data.get("size", 24) // 4))
        font = QFont(font_name, font_size)
        if self.preset_data.get("bold"):
            font.setBold(True)
        p.setFont(font)

        color = QColor(self.preset_data.get("color", "#FFFFFF"))
        p.setPen(color)
        p.drawText(pixmap.rect(), Qt.AlignCenter, self.preset_data.get("label", "Text"))
        p.end()

        self.preview.setPixmap(pixmap)

    def _render_sticker_preview(self):
        icon_name = self.preset_data.get("icon", "fa6s.face-smile")
        set_label_icon(
            self.preview, icon_name, 28,
            self.preset_data.get("color", icon_color())
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._did_drag = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._drag_start is None:
            return
        if ((event.position().toPoint() - self._drag_start).manhattanLength()
                < QApplication.startDragDistance()):
            return

        self._did_drag = True

        drag = QDrag(self)
        mime = QMimeData()

        if self.preset_type == "text":
            mime.setText(self.preset_data.get("label", "Text"))
            mime.setData("application/x-clinqing-kind", b"text")
            # Store preset metadata
            import json
            meta = json.dumps(self.preset_data).encode()
            mime.setData("application/x-clinqing-preset", meta)
        else:
            mime.setText(self.preset_data.get("label", "Sticker"))
            mime.setData("application/x-clinqing-kind", b"sticker")
            import json
            meta = json.dumps(self.preset_data).encode()
            mime.setData("application/x-clinqing-preset", meta)

        drag.setMimeData(mime)

        pixmap = self._drag_pixmap()
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.CopyAction)

    def _drag_pixmap(self):
        """Anh đại diện lúc kéo — tách ra để gate soi được artwork thật."""
        pixmap = QPixmap(64, 48)
        pixmap.fill(QColor("#1A1B22"))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        if self.preset_type == "text":
            p.setPen(QColor(self.preset_data.get("color", "#FFFFFF")))
            font = QFont(self.preset_data.get("font", "Arial"), 10)
            if self.preset_data.get("bold"):
                font.setBold(True)
            p.setFont(font)
            p.drawText(pixmap.rect(), Qt.AlignCenter, self.preset_data.get("label", "T")[:6])
        else:
            # Kéo thả thì preview phải dùng đúng font icon mà thẻ đang hiển thị,
            # không phải hai ký tự đầu của nhãn - nhãn sticker giờ là tiếng Việt.
            icon_pm = icon_pixmap(
                self.preset_data.get("icon", "fa6s.face-smile"), 24,
                self.preset_data.get("color", icon_color()))
            p.drawPixmap((64 - icon_pm.width()) // 2,
                         (48 - icon_pm.height()) // 2, icon_pm)
        p.end()
        return pixmap

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._did_drag:
            self.previewRequested.emit(dict(self.preset_data), self.preset_type)
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._did_drag = True
            self.addRequested.emit(dict(self.preset_data), self.preset_type)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PresetsPanel(QWidget):
    """Panel hiển thị danh sách preset có thể kéo thả."""

    previewRequested = Signal(dict, str)
    addRequested = Signal(dict, str)

    def __init__(self, preset_type="text", parent=None):
        super().__init__(parent)
        self.setObjectName("PresetsPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(14)

        if preset_type == "text":
            title = QLabel("THƯ VIỆN VĂN BẢN")
            presets = TEXT_PRESETS
        else:
            title = QLabel("STICKER")
            presets = STICKER_PRESETS

        title.setObjectName("PanelTitle")
        outer.addWidget(title)

        hint = QLabel("Kéo và thả vào canvas để thêm")
        hint.setStyleSheet("font-size: 11px; color: #6E7180;")
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setSpacing(12)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        for i, preset in enumerate(presets):
            card = PresetDragCard(preset, preset_type)
            card.previewRequested.connect(self.previewRequested)
            card.addRequested.connect(self.addRequested)
            r, c = divmod(i, 2)
            grid.addWidget(card, r, c)

        scroll.setWidget(grid_host)
        outer.addWidget(scroll, 1)

        self.setStyleSheet("""
            QFrame#PresetCard {
                background-color: #1A1C24;
                border: 1px solid #2A2C38;
                border-radius: 8px;
            }
            QFrame#PresetCard:hover {
                border-color: #2C7D73;
                background-color: #1E2030;
            }
            QPushButton#PresetAddButton {
                background-color: #2C7D73;
                border: 1px solid #4AA69A;
                border-radius: 11px;
                padding: 0px;
            }
            QPushButton#PresetAddButton:hover { background-color: #36968A; }
            QPushButton#PresetAddButton:pressed { background-color: #236B63; }
            QLabel#PresetLabel {
                color: #9A9DAA;
                font-size: 10px;
            }
        """)
