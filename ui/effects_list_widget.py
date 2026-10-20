"""
ui/effects_list_widget.py
Widget hiển thị danh sách hiệu ứng đã áp dụng lên clip.
Cho phép điều chỉnh intensity và xóa hiệu ứng.
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QFont

from widgets.common import font_icon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSlider, QScrollArea, QSizePolicy
)


class EffectItemWidget(QFrame):
    """Một hiệu ứng trong danh sách: tên + intensity slider + nút xóa."""

    intensityChanged = Signal(str, str, float)  # clip_id, effect_name, intensity
    removeClicked = Signal(str, str)  # clip_id, effect_name

    def __init__(self, clip_id, effect, parent=None):
        super().__init__(parent)
        self.clip_id = clip_id
        self.effect = effect
        self.setObjectName("EffectItemWidget")
        self.setFixedHeight(60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Icon màu theo category
        color_map = {
            "Sắc thái": "#FF6B35",
            "Chuyển tiếp": "#8B5CF6",
            "Hoạt ảnh": "#EC4899",
            "Bộ lọc": "#3B82F6",
        }
        cat_color = color_map.get(effect.category, "#8B5CF6")

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {cat_color}22;
                border: 1px solid {cat_color}66;
                border-radius: 6px;
                color: {cat_color};
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setText(effect.name[0] if effect.name else "?")
        layout.addWidget(icon_lbl)

        # Tên + intensity
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_lbl = QLabel(effect.name)
        name_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #FFFFFF;")
        name_row.addWidget(name_lbl)

        cat_lbl = QLabel(effect.category)
        cat_lbl.setStyleSheet(f"font-size: 9px; color: {cat_color};")
        name_row.addWidget(cat_lbl)
        name_row.addStretch()

        info_layout.addLayout(name_row)

        # Intensity slider
        slider_row = QHBoxLayout()
        slider_row.setSpacing(6)

        intensity_pct = int(effect.intensity * 100)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(intensity_pct)
        self.slider.setFixedWidth(140)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #2A2C38;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #8B5CF6;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: #8B5CF6;
                border-radius: 2px;
            }
        """)
        self.slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self.slider)

        self.intensity_label = QLabel(f"{intensity_pct}%")
        self.intensity_label.setFixedWidth(36)
        self.intensity_label.setStyleSheet("font-size: 10px; color: #888888;")
        slider_row.addWidget(self.intensity_label)

        info_layout.addLayout(slider_row)
        layout.addLayout(info_layout, 1)

        # Nút xóa
        remove_btn = QPushButton()
        remove_btn.setFixedSize(24, 24)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setIcon(font_icon("fa6s.xmark", "#8A8D99"))
        remove_btn.setIconSize(QSize(11, 11))
        remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: #EF444422;
                border-radius: 4px;
            }
        """)
        remove_btn.clicked.connect(lambda: self.removeClicked.emit(self.clip_id, effect.name))
        layout.addWidget(remove_btn)

    def _on_slider_changed(self, value):
        intensity = value / 100.0
        self.effect.intensity = intensity
        self.intensity_label.setText(f"{value}%")
        self.intensityChanged.emit(self.clip_id, self.effect.name, intensity)


class EffectsListWidget(QWidget):
    """Widget hiển thị danh sách hiệu ứng đã áp dụng lên clip."""

    effectRemoved = Signal(str, str)  # clip_id, effect_name
    effectIntensityChanged = Signal(str, str, float)  # clip_id, effect_name, intensity

    def __init__(self, clip_model, parent=None):
        super().__init__(parent)
        self.clip_model = clip_model

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        effects = getattr(clip_model, 'effects', [])

        if not effects:
            empty = QLabel("Chưa có hiệu ứng nào.\nChọn hiệu ứng từ panel bên trái.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("font-size: 11px; color: #6E7180; padding: 40px 0;")
            layout.addWidget(empty)
        else:
            # Header
            header = QHBoxLayout()
            title = QLabel(f"Hiệu ứng ({len(effects)})")
            title.setStyleSheet("font-size: 12px; font-weight: bold; color: #FFFFFF;")
            header.addWidget(title)
            header.addStretch()
            layout.addLayout(header)

            # Danh sách hiệu ứng
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            list_widget = QWidget()
            list_layout = QVBoxLayout(list_widget)
            list_layout.setContentsMargins(0, 4, 0, 0)
            list_layout.setSpacing(4)

            for effect in effects:
                item = EffectItemWidget(clip_model.clip_id, effect)
                item.intensityChanged.connect(self.effectIntensityChanged.emit)
                item.removeClicked.connect(self.effectRemoved.emit)
                list_layout.addWidget(item)

            list_layout.addStretch()
            scroll.setWidget(list_widget)
            layout.addWidget(scroll)
