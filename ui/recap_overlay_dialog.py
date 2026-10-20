"""
ui/recap_overlay_dialog.py
Hộp thoại "Lớp phủ recap" — cấu hình CẢ DỰ ÁN: viền màu, nền kính mờ, tâm ngắm, badge REC.

Vì sao là hộp thoại riêng chứ không phải thẻ trong PropertiesPanel: thẻ clip chỉ
sống khi có một clip được chọn, còn lớp phủ này áp lên toàn khung hình (kể cả
khung trống). Đóng/mở hộp thoại không làm mất cấu hình.

Mọi thay đổi áp NGAY xuống TimelineModel để Canvas redraw bằng đúng
core/recap_overlay mà bản xuất dùng — người thấy gì trên canvas là thứ sẽ vào
video. Một lần mở hộp thoại = MỘT bước undo: lệnh chỉ được đẩy khi đóng, nên kéo
thanh trượt 40 lần không nhét 40 mục vào lịch sử.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QSpinBox, QCheckBox, QVBoxLayout, QWidget,
)

from core import recap_overlay
from widgets.common import font_icon

_SECTION = "font-size: 11px; font-weight: 700; color: #7FE8DC; letter-spacing: .4px;"
_FIELD = "font-size: 11px; color: #9A9DAA;"


class RecapOverlayDialog(QDialog):
    """Bảng bật/tắt và chỉnh từng lớp phủ; ghi thẳng vào model theo thời gian thực."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setObjectName("RecapOverlayDialog")
        self.setWindowTitle("Lớp phủ recap")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumSize(520, 520)
        self.resize(560, 560)
        self.setStyleSheet(self._style())

        # Snapshot lúc mở: lệnh undo chỉ đẩy MỘT lần khi đóng, và nếu người dùng
        # bấm Đóng mà không đổi gì thì lịch sử phải nguyên vẹn (không có mục ma).
        self._opening = dict(self._model.recap_overlay)
        self._border_color = self._opening["border_color"]
        self._reticle_color = self._opening["reticle_color"]
        self._loading = True
        self._build_ui()
        self._load_from(self._opening)
        self._loading = False

    # ── model ───────────────────────────────────────────────────
    @property
    def _model(self):
        return self.main_window.timeline_panel.model

    def refresh(self):
        """Đọc lại toàn bộ điều khiển từ model — hộp thoại được dùng lại, còn
        model thì undo/redo và mở dự án khác có thể đã đổi trong lúc nó ẩn."""
        settings = dict(self._model.recap_overlay)
        self._opening = settings
        self._border_color = settings["border_color"]
        self._reticle_color = settings["reticle_color"]
        self._loading = True
        self._load_from(settings)
        self._loading = False

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_title_bar())

        body = QWidget()
        body.setObjectName("RecapBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(10)

        self.chk_enabled = QCheckBox("Bật lớp phủ recap")
        self.chk_enabled.setObjectName("RecapMaster")
        self.chk_enabled.toggled.connect(self._apply)
        layout.addWidget(self.chk_enabled)

        layout.addWidget(self._section("NỀN KÍNH MỜ"))
        self.chk_glass = QCheckBox("Làm mờ nội dung phía sau")
        self.chk_glass.toggled.connect(self._apply)
        layout.addWidget(self.chk_glass)
        layout.addWidget(self._slider_row(
            "Độ sáng nền", "brightness", 0, 100))
        layout.addWidget(self._slider_row(
            "Độ mờ", "blur", 0, 80))

        layout.addWidget(self._section("VIỀN"))
        self.chk_border = QCheckBox("Viền màu bo góc")
        self.chk_border.toggled.connect(self._apply)
        layout.addWidget(self.chk_border)
        self.swatches = []
        strip = QHBoxLayout()
        strip.setSpacing(6)
        for hexcode in recap_overlay.BORDER_SWATCHES:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(hexcode)
            btn.setStyleSheet(
                "QPushButton { background-color: %s; border: 2px solid #2A2D3A;"
                " border-radius: 6px; }"
                "QPushButton:checked { border: 2px solid #FFFFFF; }" % hexcode)
            btn.clicked.connect(lambda _=False, c=hexcode: self._pick_border_color(c))
            strip.addWidget(btn)
            self.swatches.append((hexcode, btn))
        strip.addStretch(1)
        layout.addLayout(strip)
        layout.addWidget(self._slider_row("Độ dày viền", "border_width", 1, 12))

        layout.addWidget(self._section("TÂM NGẮM"))
        self.chk_reticle = QCheckBox("Hiện tâm ngắm giữa khung")
        self.chk_reticle.toggled.connect(self._apply)
        layout.addWidget(self.chk_reticle)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo_shape = QComboBox()
        self.combo_shape.addItems([recap_overlay.RETICLE_LABELS[s]
                                   for s in recap_overlay.RETICLE_SHAPES])
        self.combo_shape.currentIndexChanged.connect(self._apply)
        row.addWidget(self._field_label("Kiểu", _FIELD))
        row.addWidget(self.combo_shape, 1)
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(60, 26)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.setText("")
        self.btn_color.clicked.connect(self._pick_reticle_color)
        row.addWidget(self._field_label("Màu", _FIELD))
        row.addWidget(self.btn_color)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addWidget(self._section("BADGE REC"))
        self.chk_rec = QCheckBox("Chấm REC + đồng hồ + nhãn độ phân giải")
        self.chk_rec.toggled.connect(self._apply)
        layout.addWidget(self.chk_rec)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.edit_label = QLineEdit()
        self.edit_label.setPlaceholderText("để trống = tự theo kích thước dự án")
        self.edit_label.textChanged.connect(self._apply)
        row2.addWidget(self._field_label("Nhãn", _FIELD))
        row2.addWidget(self.edit_label, 1)
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(0, 240)
        self.spin_fps.setSuffix(" fps")
        self.spin_fps.valueChanged.connect(self._apply)
        row2.addWidget(self._field_label("Tốc độ", _FIELD))
        row2.addWidget(self.spin_fps)
        layout.addLayout(row2)

        layout.addStretch(1)
        close = QPushButton("Đóng")
        close.setObjectName("RecapClose")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self._on_close)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)

        root.addWidget(body, 1)
        self._sync_enabled_state()

    def _build_title_bar(self):
        bar = QFrame()
        bar.setObjectName("RecapTitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.crosshairs", "#40E0D0").pixmap(QSize(16, 16)))
        title = QLabel("Lớp phủ recap")
        title.setObjectName("RecapTitle")
        close = QPushButton()
        close.setObjectName("RecapX")
        close.setIcon(font_icon("fa6s.xmark", "#C8CBD4"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(28, 28)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self._on_close)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(close)
        return bar

    @staticmethod
    def _section(text):
        label = QLabel(text)
        label.setStyleSheet(_SECTION + " background: transparent;")
        return label

    @staticmethod
    def _field_label(text, style):
        label = QLabel(text)
        label.setStyleSheet(style + " background: transparent;")
        return label

    def _slider_row(self, text, key, minimum, maximum):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._field_label(text, _FIELD))
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("RecapSlider")
        slider.setRange(minimum, maximum)
        slider.valueChanged.connect(self._apply)
        value = QLabel()
        value.setMinimumWidth(34)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setStyleSheet(_FIELD + " background: transparent;")
        slider.valueChanged.connect(lambda v, l=value: l.setText(str(v)))
        row.addWidget(slider, 1)
        row.addWidget(value)
        host.slider = slider
        host.key = key
        host.value_label = value
        return host

    # ── đọc/ghi settings ────────────────────────────────────────
    def _rows(self):
        return [child for child in self.findChildren(QWidget)
                if hasattr(child, "slider") and hasattr(child, "key")]

    def _load_from(self, s):
        self.chk_enabled.setChecked(bool(s["enabled"]))
        self.chk_glass.setChecked(bool(s["glass"]))
        self.chk_border.setChecked(bool(s["border"]))
        self.chk_reticle.setChecked(bool(s["reticle"]))
        self.chk_rec.setChecked(bool(s["rec"]))
        self.edit_label.setText(s["rec_label"] or "")
        self.spin_fps.setValue(int(s["rec_fps"] or 0))
        self.combo_shape.setCurrentIndex(
            max(0, recap_overlay.RETICLE_SHAPES.index(s["reticle_shape"])))
        values = {"brightness": int(round(s["bg_brightness"] * 100)),
                  "blur": int(round(s["bg_blur"])),
                  "border_width": int(round(s["border_width"]))}
        for row in self._rows():
            row.slider.blockSignals(True)
            row.slider.setValue(values[row.key])
            row.slider.blockSignals(False)
            row.value_label.setText(str(values[row.key]))
        self._paint_color_buttons(s)
        self._sync_enabled_state()

    def _paint_color_buttons(self, s):
        for hexcode, btn in self.swatches:
            btn.setChecked(hexcode.upper() == str(s["border_color"]).upper())
        color = QColor(s["reticle_color"])
        self.btn_color.setStyleSheet(
            "QPushButton { background-color: %s; border: 2px solid #2A2D3A;"
            " border-radius: 6px; }" % (color.name()))

    def _collect(self) -> dict:
        values = {row.key: row.slider.value() for row in self._rows()}
        return {
            "enabled": self.chk_enabled.isChecked(),
            "glass": self.chk_glass.isChecked(),
            "bg_brightness": values["brightness"] / 100.0,
            "bg_blur": float(values["blur"]),
            "border": self.chk_border.isChecked(),
            "border_color": self._border_color,
            "border_width": float(values["border_width"]),
            "reticle": self.chk_reticle.isChecked(),
            "reticle_shape": recap_overlay.RETICLE_SHAPES[self.combo_shape.currentIndex()],
            "reticle_color": self._reticle_color,
            "rec": self.chk_rec.isChecked(),
            "rec_label": self.edit_label.text().strip(),
            "rec_fps": int(self.spin_fps.value()),
        }

    def _pick_border_color(self, hexcode):
        self._border_color = hexcode
        self._apply()

    def _pick_reticle_color(self):
        chosen = QColorDialog.getColor(QColor(self._reticle_color), self,
                                       "Màu tâm ngắm")
        if chosen.isValid():
            self._reticle_color = chosen.name()
            self._apply()

    def _apply(self, *_args):
        if self._loading:
            return
        settings = self._collect()
        self._border_color = settings["border_color"]
        self._reticle_color = settings["reticle_color"]
        self._model.set_recap_overlay(settings)
        self._paint_color_buttons(settings)
        self._sync_enabled_state()

    def _sync_enabled_state(self):
        """Master off thì mọi hàng dưới chỉ để xem — khỏi đoán vì sao kéo không ăn."""
        on = self.chk_enabled.isChecked()
        for widget in (self.chk_glass, self.chk_border, self.chk_reticle,
                       self.chk_rec, self.combo_shape, self.btn_color,
                       self.edit_label, self.spin_fps):
            widget.setEnabled(on)
        for row in self._rows():
            row.setEnabled(on)
        for _hex, btn in self.swatches:
            btn.setEnabled(on)

    def _on_close(self):
        """Đóng = MỘT bước undo, nếu thật sự có gì đó thay đổi."""
        now = dict(self._model.recap_overlay)
        self.close()
        if now == self._opening:
            return
        from core.commands import SetRecapOverlayCommand
        self.main_window.timeline_panel.undo_stack.push(
            SetRecapOverlayCommand(self._model, now, before=self._opening))

    @staticmethod
    def _style():
        return """
        QDialog { background-color: #1A1C1F; border: 1px solid #34383D;
                  border-radius: 12px; color: #D8DCE0; }
        #RecapTitleBar { background-color: #1A1B26;
                         border-bottom: 1px solid #2A2D3A;
                         border-top-left-radius: 12px;
                         border-top-right-radius: 12px; }
        #RecapTitle { font-size: 15px; font-weight: 700; color: #FFFFFF;
                      background: transparent; }
        #RecapX { background: transparent; border: none; border-radius: 4px; }
        #RecapX:hover { background: #E81123; }
        #RecapBody { background: transparent; }
        QCheckBox { font-size: 12px; color: #E6E8EC; background: transparent; }
        QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
                               border: 1px solid #3A3F46; background: #23262B; }
        QCheckBox::indicator:checked { background: #40E0D0; border-color: #40E0D0; }
        QCheckBox:disabled { color: #5C6068; }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #23262B; border: 1px solid #3A3F46;
            border-radius: 6px; padding: 5px 8px; color: #E6E8EC; font-size: 12px;
        }
        QComboBox::drop-down { border: none; width: 20px; }
        QSlider::groove:horizontal { height: 4px; background: #2A2D3A; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: #40E0D0; border-radius: 2px; }
        QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0;
                                     border-radius: 6px; background: #E6E8EC; }
        #RecapClose { background-color: #2A2D3A; border: 1px solid #3A3F46;
                      border-radius: 8px; color: #E6E8EC; font-size: 12px;
                      padding: 7px 18px; }
        #RecapClose:hover { background-color: #3A3F46; }
        """
