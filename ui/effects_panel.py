"""
ui/effects_panel.py
Panel Hiệu ứng — hiển thị các mẫu hiệu ứng chuyên nghiệp có thể áp dụng cho clip.
Mỗi hiệu ứng là một preset với tên, icon, và tham số áp dụng lên clip.
"""

from PySide6.QtCore import Qt, Signal, QMimeData, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QFont, QLinearGradient, QDrag
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QGridLayout, QStackedWidget, QPushButton, QApplication
)

from widgets.common import (AnimatedTabBar, set_label_icon, icon_color,
                            font_icon)

# Danh mục này KHÔNG áp EffectData: mỗi thẻ là một khoá trong
# core/transitions.TRANSITIONS và đi qua SetTransitionCommand (ripple edit).
# Tên hằng để main_window khỏi so sánh chuỗi thô.
TRANSITION_CATEGORY = "Chuyển tiếp"


EFFECT_CATEGORIES = {
    "Sắc thái": [
        {"name": "Warm Tone", "icon": "fa6s.sun", "color1": "#FF6B35", "color2": "#FFA07A",
         "desc": "Tông ấm, áp dụng cho cảnh hoàng hôn"},
        {"name": "Cool Blue", "icon": "fa6s.snowflake", "color1": "#4A90D9", "color2": "#87CEEB",
         "desc": "Tông lạnh, tạo cảm giác mát mẻ"},
        {"name": "Vintage", "icon": "fa6s.clock-rotate-left", "color1": "#C9A96E", "color2": "#8B7355",
         "desc": "Phong cách cổ điển, retro"},
        {"name": "B&W", "icon": "fa6s.circle-half-stroke", "color1": "#888888", "color2": "#333333",
         "desc": "Đen trắng nghệ thuật"},
        {"name": "Cinematic", "icon": "fa6s.film", "color1": "#2C3E50", "color2": "#3498DB",
         "desc": "Tông phim điện ảnh"},
        {"name": "Neon Glow", "icon": "fa6s.star", "color1": "#FF00FF", "color2": "#00FFFF",
         "desc": "Hiệu ứng neon phát sáng"},
        {"name": "Pop Art", "icon": "fa6s.circle-dot", "color1": "#FF2E63", "color2": "#FFD60A",
         "desc": "Tranh pop art: bậc màu ít, chấm bi, viền đen"},
    ],
    TRANSITION_CATEGORY: [
        {"name": "Fade In", "icon": "fa6s.arrow-right", "color1": "#000000", "color2": "#FFFFFF",
         "desc": "Phai từ đen sang rõ"},
        {"name": "Fade Out", "icon": "fa6s.arrow-left", "color1": "#FFFFFF", "color2": "#000000",
         "desc": "Phai từ rõ sang đen"},
        {"name": "Cross Dissolve", "icon": "fa6s.layer-group", "color1": "#8B5CF6", "color2": "#EC4899",
         "desc": "Hòa tan chéo giữa 2 clip"},
        {"name": "Zoom In", "icon": "fa6s.magnifying-glass-plus", "color1": "#10B981", "color2": "#059669",
         "desc": "Phóng to dần"},
        {"name": "Slide Left", "icon": "fa6s.angles-left", "color1": "#F59E0B", "color2": "#D97706",
         "desc": "Trượt sang trái"},
        {"name": "Wipe Right", "icon": "fa6s.paint-roller", "color1": "#EF4444", "color2": "#DC2626",
         "desc": "Quét từ trái sang phải"},
    ],
    "Hoạt ảnh": [
        {"name": "Bounce", "icon": "fa6s.arrow-up", "color1": "#8B5CF6", "color2": "#6D28D9",
         "desc": "Hiệu ứng nảy"},
        {"name": "Shake", "icon": "fa6s.mobile-screen", "color1": "#EF4444", "color2": "#B91C1C",
         "desc": "Rung lắc"},
        {"name": "Pulse", "icon": "fa6s.heart-pulse", "color1": "#EC4899", "color2": "#BE185D",
         "desc": "Nhấp nháy nhịp nhàng"},
        {"name": "Spin", "icon": "fa6s.rotate", "color1": "#3B82F6", "color2": "#1D4ED8",
         "desc": "Xoay vòng"},
        {"name": "Float", "icon": "fa6s.cloud", "color1": "#06B6D4", "color2": "#0891B2",
         "desc": "Bay lơ lửng"},
        {"name": "Glitch", "icon": "fa6s.bug", "color1": "#F43F5E", "color2": "#E11D48",
         "desc": "Hiệu ứng lỗi kỹ thuật số"},
        {"name": "Ken Burns Out", "icon": "fa6s.magnifying-glass-minus", "color1": "#14B8A6", "color2": "#0D9488",
         "desc": "Zoom lùi dần cả clip"},
        {"name": "Slide Right", "icon": "fa6s.angles-right", "color1": "#F59E0B", "color2": "#D97706",
         "desc": "Trượt vào từ bên phải"},
        {"name": "Slide Up", "icon": "fa6s.arrow-up-long", "color1": "#22C55E", "color2": "#15803D",
         "desc": "Trượt lên từ dưới"},
        {"name": "Slide Down", "icon": "fa6s.arrow-down-long", "color1": "#A855F7", "color2": "#7E22CE",
         "desc": "Trượt xuống từ trên"},
    ],
    "Bộ lọc": [
        {"name": "Blur", "icon": "fa6s.eye-slash", "color1": "#6366F1", "color2": "#4F46E5",
         "desc": "Làm mờ"},
        {"name": "Sharpen", "icon": "fa6s.bolt", "color1": "#F59E0B", "color2": "#D97706",
         "desc": "Làm sắc nét"},
        {"name": "Vignette", "icon": "fa6s.circle", "color1": "#1E1B4B", "color2": "#312E81",
         "desc": "Viền tối xung quanh"},
        {"name": "Grain", "icon": "fa6s.spray-can", "color1": "#78716C", "color2": "#57534E",
         "desc": "Nhiễu hạt phim"},
        {"name": "Chromatic", "icon": "fa6s.palette", "color1": "#A855F7", "color2": "#7C3AED",
         "desc": "Phân tách chromatic"},
        {"name": "Lens Flare", "icon": "fa6s.sun", "color1": "#FCD34D", "color2": "#F59E0B",
         "desc": "Loang sáng ống kính"},
    ],
    # Aura không phải lọc màu: mỗi thẻ là một hình thái vẽ theo đồng hồ clip
    # trong core/aura_paint (hạt bay, tia sét, vòng sáng, dải sóng, mưa ký tự).
    # Tên thẻ phải khớp khoá trong EFFECT_PRESETS, nếu không thẻ thành ảnh minh
    # hoạ không áp dụng được gì.
    "Aura": [
        {"name": "Hỏa Diệm", "icon": "fa6s.fire", "color1": "#FF8A28", "color2": "#FF3C1E",
         "desc": "Hạt lửa bay lên từ mép dưới"},
        {"name": "Lôi Điện", "icon": "fa6s.bolt", "color1": "#22D3EE", "color2": "#FFFFFF",
         "desc": "Viền sáng + tia sét giật quanh khung"},
        {"name": "Thánh Quang", "icon": "fa6s.sun", "color1": "#FFEE66", "color2": "#FBBF24",
         "desc": "Vòng hào quang lan ra từ tâm"},
        {"name": "Hắc Ám", "icon": "fa6s.moon", "color1": "#6600AA", "color2": "#280046",
         "desc": "Khói tím đen cuộn lên"},
        {"name": "Cực Quang", "icon": "fa6s.asterisk", "color1": "#33FF99", "color2": "#A855F7",
         "desc": "Dải sóng chảy ngang khung hình"},
        {"name": "Mã Ma Trận", "icon": "fa6s.terminal", "color1": "#22C55E", "color2": "#86EFAC",
         "desc": "Mưa ký tự xanh rơi dọc khung"},
        {"name": "Anh Đào Bay", "icon": "fa6s.spa", "color1": "#F472B6", "color2": "#FBCFE8",
         "desc": "Cánh hoa hồng trôi chéo, có xoay"},
        {"name": "Neon Hồng Tím", "icon": "fa6s.spray-can-sparkles", "color1": "#EC4899",
         "color2": "#06B6D4",
         "desc": "Hoa lửa hồng/cyan luân phiên"},
    ],
}

CATEGORY_TABS = list(EFFECT_CATEGORIES.keys())


class EffectCard(QFrame):
    """Nhấp để xem thử; kéo, kích đúp hoặc nhấn + để thêm."""
    previewRequested = Signal(dict)
    addRequested = Signal(dict)

    def __init__(self, effect_data, parent=None):
        super().__init__(parent)
        self.effect_data = effect_data
        self.setObjectName("EffectCard")
        self.setFixedSize(150, 130)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            f"{effect_data.get('name', '')}\n{effect_data.get('desc', '')}\n"
            "Nhấp: xem thử • Kích đúp: thêm"
        )
        self._drag_start = None
        self._did_drag = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)

        # Preview gradient
        self.preview = QLabel()
        self.preview.setFixedSize(130, 60)
        self.preview.setStyleSheet(f"""
            QLabel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {effect_data['color1']}, stop:1 {effect_data['color2']});
                border-radius: 6px;
                border: 1px solid #2A2C38;
            }}
        """)

        # Icon overlay trên preview
        icon_label = QLabel(self.preview)
        icon_label.setAlignment(Qt.AlignCenter)
        set_label_icon(icon_label, effect_data.get("icon", "fa6s.wand-magic-sparkles"), 18, "#FFFFFF")
        icon_label.setGeometry(0, 0, 130, 60)

        name = QLabel(effect_data["name"])
        name.setObjectName("EffectName")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")

        desc = QLabel(effect_data.get("desc", ""))
        desc.setObjectName("EffectDesc")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 9px; color: #888888;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(24)

        layout.addWidget(self.preview, alignment=Qt.AlignHCenter)
        layout.addWidget(name)
        layout.addWidget(desc)

        self.add_button = QPushButton(self)
        self.add_button.setObjectName("EffectAddButton")
        self.add_button.setIcon(font_icon("fa6s.plus", "#FFFFFF"))
        self.add_button.setIconSize(QSize(11, 11))
        self.add_button.setToolTip("Thêm hiệu ứng")
        self.add_button.setFixedSize(22, 22)
        self.add_button.move(self.width() - 28, 6)
        self.add_button.raise_()
        self.add_button.clicked.connect(lambda: self.addRequested.emit(dict(self.effect_data)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._did_drag = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._drag_start is None:
            return
        if ((event.position().toPoint() - self._drag_start).manhattanLength()
                < QApplication.startDragDistance()):
            return
        self._did_drag = True
        import json
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.effect_data.get("name", "Effect"))
        mime.setData("application/x-clinqing-kind", b"effect")
        mime.setData(
            "application/x-clinqing-effect",
            json.dumps(self.effect_data, ensure_ascii=False).encode("utf-8")
        )
        drag.setMimeData(mime)
        if self.preview.pixmap() and not self.preview.pixmap().isNull():
            drag.setPixmap(self.preview.pixmap().scaled(90, 44, Qt.KeepAspectRatio))
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._did_drag:
            self.previewRequested.emit(dict(self.effect_data))
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._did_drag = True
            self.addRequested.emit(dict(self.effect_data))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class EffectsPanel(QWidget):
    """Panel hiệu ứng — mở riêng biệt khi chọn 'Hiệu ứng' trên sidebar."""

    effectPreviewRequested = Signal(dict)
    effectApplied = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EffectsPanel")
        self.setFixedWidth(360)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(14)

        title = QLabel("HIỆU ỨNG")
        title.setObjectName("PanelTitle")
        outer.addWidget(title)

        hint = QLabel("Chọn hiệu ứng để áp dụng cho clip đang chọn")
        hint.setStyleSheet("font-size: 11px; color: #6E7180;")
        outer.addWidget(hint)

        # Tabs danh mục hiệu ứng
        self.tabs = AnimatedTabBar(CATEGORY_TABS, object_name="EffectTab", spacing=16)
        outer.addWidget(self.tabs)

        # Stacked widget chứa grid effects cho từng danh mục
        self.stack = QStackedWidget()

        for category in CATEGORY_TABS:
            effects = EFFECT_CATEGORIES[category]
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

            for i, effect in enumerate(effects):
                card_data = dict(effect, category=category)
                card = EffectCard(card_data)
                card.previewRequested.connect(self.effectPreviewRequested)
                card.addRequested.connect(self.effectApplied)
                r, c = divmod(i, 2)
                grid.addWidget(card, r, c)

            scroll.setWidget(grid_host)
            self.stack.addWidget(scroll)

        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)
        outer.addWidget(self.stack, 1)

        self.setStyleSheet("""
            QFrame#EffectCard {
                background-color: #1A1C24;
                border: 1px solid #2A2C38;
                border-radius: 8px;
            }
            QFrame#EffectCard:hover {
                border-color: #2C7D73;
                background-color: #1E2030;
            }
            QPushButton#EffectAddButton {
                background-color: #2C7D73;
                border: 1px solid #4AA69A;
                border-radius: 11px;
                padding: 0px;
            }
            QPushButton#EffectAddButton:hover { background-color: #36968A; }
            QPushButton#EffectAddButton:pressed { background-color: #236B63; }
            QLabel#EffectName {
                color: #FFFFFF;
                font-size: 11px;
                font-weight: bold;
            }
            QLabel#EffectDesc {
                color: #888888;
                font-size: 9px;
            }
        """)
