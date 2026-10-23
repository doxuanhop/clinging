"""
ui/canvas_layout_dialog.py
Hộp thoại "Bố cục & Phong cách" — cấu hình CẢ DỰ ÁN: nền, ô bố cục, chữ đầu/cuối.

Cùng khuân với ui/recap_overlay_dialog.py vì cùng một lí do tồn tại: thẻ trong
PropertiesPanel chỉ sống khi có một clip được chọn, còn trang trí này áp lên toàn
khung hình kể cả khung trống. Mọi thay đổi áp NGAY xuống TimelineModel để Canvas
redraw bằng đúng core/canvas_layout mà bản xuất dùng.

Nút "Dàn clip vào ô" là MỘT lệnh undo riêng (ArrangeSlotsCommand): nó chỉ viết
transform, không mở nhánh composite mới, nên xem thử và xuất ra không thể lệch.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QCheckBox,
    QVBoxLayout, QWidget,
)

from core import canvas_layout
from widgets.common import font_icon

_SECTION = "font-size: 11px; font-weight: 700; color: #7FE8DC; letter-spacing: .4px;"
_FIELD = "font-size: 11px; color: #9A9DAA;"

# Cac moc thoi gian cho "Trao ô": 0 = dung nguyen bo cuc, khong doi nguon theo
# dong ho. Nhang gia tri nay trung voi thang cua `manga_rotate_interval` trong
# core/canvas_layout nen khong can bom mau rieng.
ROTATE_CHOICES = (0.0, 3.0, 5.0, 10.0, 15.0)


class CanvasLayoutDialog(QDialog):
    """Bảng chọn bố cục + phong cách; ghi thẳng vào model theo thời gian thực."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setObjectName("CanvasLayoutDialog")
        self.setWindowTitle("Bố cục & Phong cách")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumSize(700, 460)
        self.resize(760, 520)
        self.setStyleSheet(self._style())

        # Snapshot luc mo: lenh undo chi day MOT lan khi dong, ne 40 lan keo
        # thanh truot khong nhet 40 muc vao lich su.
        self._opening = dict(self._model.project_layout)
        self._loading = True
        self._build_ui()
        self._load_from(self._opening)
        self._loading = False

    # ── model ───────────────────────────────────────────────────
    @property
    def _model(self):
        return self.main_window.timeline_panel.model

    def refresh(self):
        """Đọc lại toàn bộ điều khiển từ model (undo/redo hoặc mở dự án khác)."""
        settings = dict(self._model.project_layout)
        self._opening = settings
        self._loading = True
        self._load_from(settings)
        self._loading = False

    # ── dựng UI ─────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_title_bar())

        self._scroll = QScrollArea()
        self._scroll.setObjectName("LayoutScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.horizontalScrollBar().setEnabled(False)
        body = QWidget()
        body.setObjectName("LayoutBody")
        # HAI COT, khong phai mot: mot cot cho 22 dieu khien can viewport ~790 px
        # (do lan chay 23/10: dialog 839 px trong khi man hinh nay con 824 px
        # luu duoc) tuc la no an mat nut Dong cua chinh no tren laptop 1080/768.
        columns = QHBoxLayout(body)
        columns.setContentsMargins(18, 12, 18, 12)
        columns.setSpacing(22)
        left = QVBoxLayout()
        left.setSpacing(9)
        right = QVBoxLayout()
        right.setSpacing(9)

        self.chk_enabled = QCheckBox("Bật bố cục + phong cách cho cả dự án")
        self.chk_enabled.setObjectName("LayoutMaster")
        self.chk_enabled.toggled.connect(self._apply)
        left.addWidget(self.chk_enabled)

        left.addWidget(self._section("BO CUC"))
        self.combo_layout = QComboBox()
        for key in canvas_layout.LAYOUT_ORDER:
            label, category, _fr, _chrome = canvas_layout.LAYOUT_STYLES[key]
            self.combo_layout.addItem("%s  [%s]" % (label, category), key)
        self.combo_layout.currentIndexChanged.connect(self._apply)
        left.addWidget(self.combo_layout)
        self.btn_slot_color = self._color_button("frame_color")
        self.chk_auto_fit = QCheckBox("Vừa ô (không cắt rìa)")
        self.chk_auto_fit.toggled.connect(self._apply)
        left.addLayout(self._field_row("Màu khung/o", self.btn_slot_color))
        left.addWidget(self.chk_auto_fit)
        left.addWidget(self._slider_row("Khe giữa các ô", "slot_gap", 0, 20))

        left.addWidget(self._section("PHONG CACH NEN"))
        self.combo_mode = QComboBox()
        for mode in canvas_layout.BACKGROUND_MODES:
            self.combo_mode.addItem(
                canvas_layout.BACKGROUND_MODE_LABELS[mode], mode)
        self.combo_mode.currentIndexChanged.connect(self._apply)
        left.addWidget(self.combo_mode)
        self.combo_texture = QComboBox()
        for name in canvas_layout.TEXTURE_ORDER:
            self.combo_texture.addItem(canvas_layout.TEXTURES[name][0], name)
        self.combo_texture.currentIndexChanged.connect(self._apply)
        left.addWidget(self.combo_texture)
        self.btn_bg_color = self._color_button("background_color")
        left.addLayout(self._field_row("Màu nền", self.btn_bg_color))
        left.addWidget(self._slider_row("Đậm nét chất liệu", "texture_scale",
                                         25, 400))
        left.addWidget(self._slider_row("Lớp phủ tối toàn khung",
                                         "overlay_opacity", 0, 90))

        right.addWidget(self._section("CHU DAU / CHU CUOI"))
        self.edit_header = QLineEdit()
        self.edit_header.setPlaceholderText("chữ đầu khung (để trống = không)")
        self.edit_header.textChanged.connect(self._apply)
        self.edit_footer = QLineEdit()
        self.edit_footer.setPlaceholderText("chữ cuối khung")
        self.edit_footer.textChanged.connect(self._apply)
        right.addWidget(self._field_label("Chữ đầu", _FIELD))
        right.addWidget(self.edit_header)
        right.addWidget(self._field_label("Chữ cuối", _FIELD))
        right.addWidget(self.edit_footer)
        self.combo_header_font = self._font_combo()
        self.spin_header_size = self._size_spin(10, 200)
        self.chk_header_bold = QCheckBox("Đậm")
        self.combo_footer_font = self._font_combo()
        self.spin_footer_size = self._size_spin(10, 200)
        self.chk_footer_bold = QCheckBox("Đậm")
        for spin in (self.spin_header_size, self.spin_footer_size):
            spin.valueChanged.connect(self._apply)
        for check in (self.chk_header_bold, self.chk_footer_bold):
            check.toggled.connect(self._apply)
        right.addLayout(self._style_row("Đầu", self.combo_header_font,
                                        self.spin_header_size,
                                        self.chk_header_bold))
        right.addLayout(self._style_row("Cuối", self.combo_footer_font,
                                        self.spin_footer_size,
                                        self.chk_footer_bold))
        self.btn_text_color = self._color_button("text_color")
        right.addLayout(self._field_row("Màu chữ", self.btn_text_color))

        right.addWidget(self._section("CACH CHAY"))
        self.chk_sequential = QCheckBox("Lần lượt từng ô (không ghép đồng thời)")
        self.chk_sequential.toggled.connect(self._apply)
        right.addWidget(self.chk_sequential)
        self.spin_slot_seconds = QSpinBox()
        self.spin_slot_seconds.setRange(1, 60)
        self.spin_slot_seconds.setSuffix(" s")
        self.spin_slot_seconds.valueChanged.connect(self._apply)
        self.combo_rotate = QComboBox()
        for value in ROTATE_CHOICES:
            self.combo_rotate.addItem("không đổi" if value == 0
                                      else "mỗi %gs" % value, value)
        self.combo_rotate.currentIndexChanged.connect(self._apply)
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        qrow.addWidget(self._field_label("Mỗi ô", _FIELD))
        qrow.addWidget(self.spin_slot_seconds)
        qrow.addWidget(self._field_label("Trao ô (manga)", _FIELD))
        qrow.addWidget(self.combo_rotate, 1)
        right.addLayout(qrow)

        self.btn_arrange = QPushButton("Dàn clip đang mở vào các ô")
        self.btn_arrange.setObjectName("LayoutArrange")
        self.btn_arrange.setCursor(Qt.PointingHandCursor)
        self.btn_arrange.clicked.connect(self._arrange)
        right.addWidget(self.btn_arrange)
        self.lbl_arrange = QLabel("Đếm clip trên timeline tại playhead.")
        self.lbl_arrange.setObjectName("LayoutHint")
        self.lbl_arrange.setStyleSheet(_FIELD + " background: transparent;")
        self.lbl_arrange.setWordWrap(True)
        right.addWidget(self.lbl_arrange)

        close = QPushButton("Đóng")
        close.setObjectName("LayoutClose")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self._on_close)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        left.addStretch(1)
        right.addStretch(1)
        right.addLayout(footer)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)
        self._body = body
        self._fit_height()
        self._sync_enabled_state()

    @staticmethod
    def _field_row(text, widget):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(CanvasLayoutDialog._field_label(text, _FIELD))
        row.addWidget(widget)
        row.addStretch(1)
        return row

    @staticmethod
    def _style_row(text, combo, spin, bold):
        """Mot hang cho vung chu: font + co + dam — 3 dieu khien, 1 hang."""
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(CanvasLayoutDialog._field_label(text, _FIELD))
        row.addWidget(combo, 1)
        row.addWidget(spin)
        row.addWidget(bold)
        return row

    def _build_title_bar(self):
        bar = QFrame()
        bar.setObjectName("LayoutTitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.table-cells", "#40E0D0").pixmap(QSize(16, 16)))
        title = QLabel("Bố cục & Phong cách")
        title.setObjectName("LayoutTitle")
        close = QPushButton()
        close.setObjectName("LayoutX")
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

    @staticmethod
    def _size_spin(minimum, maximum):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(" px")
        return spin

    def _font_combo(self):
        combo = QComboBox()
        combo.addItems(canvas_layout.FONT_FAMILIES)
        combo.currentIndexChanged.connect(self._apply)
        return combo

    def _color_button(self, key):
        btn = QPushButton()
        btn.setObjectName("LayoutColor_" + key)
        btn.setFixedSize(74, 24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))
        return btn

    def _slider_row(self, text, key, minimum, maximum):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._field_label(text, _FIELD))
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("LayoutSlider")
        slider.setRange(minimum, maximum)
        slider.valueChanged.connect(self._apply)
        value = QLabel()
        value.setMinimumWidth(38)
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

    @staticmethod
    def _index_of(seq, value):
        try:
            return max(0, list(seq).index(value))
        except ValueError:
            return 0

    def _load_from(self, s):
        self.chk_enabled.setChecked(bool(s["enabled"]))
        self.combo_layout.setCurrentIndex(self._index_of(
            canvas_layout.LAYOUT_ORDER, s["layout"]))
        self.combo_mode.setCurrentIndex(self._index_of(
            canvas_layout.BACKGROUND_MODES, s["background_mode"]))
        self.combo_texture.setCurrentIndex(self._index_of(
            canvas_layout.TEXTURE_ORDER, s["texture"]))
        self.chk_auto_fit.setChecked(bool(s["auto_fit"]))
        self.chk_sequential.setChecked(bool(s["play_sequentially"]))
        self.spin_slot_seconds.setValue(int(round(s["slot_seconds"])))
        self.combo_rotate.setCurrentIndex(self._index_of(
            ROTATE_CHOICES, s["manga_rotate_interval"]))
        self.edit_header.setText(s["header_text"] or "")
        self.edit_footer.setText(s["footer_text"] or "")
        self.combo_header_font.setCurrentIndex(self._index_of(
            canvas_layout.FONT_FAMILIES, s["header_font"]))
        self.combo_footer_font.setCurrentIndex(self._index_of(
            canvas_layout.FONT_FAMILIES, s["footer_font"]))
        self.spin_header_size.setValue(int(round(s["header_size"])))
        self.spin_footer_size.setValue(int(round(s["footer_size"])))
        self.chk_header_bold.setChecked(bool(s["header_bold"]))
        self.chk_footer_bold.setChecked(bool(s["footer_bold"]))
        values = {"slot_gap": int(round(s["slot_gap"] * 100)),
                  "texture_scale": int(round(s["texture_scale"] * 100)),
                  "overlay_opacity": int(round(s["overlay_opacity"] * 100))}
        for row in self._rows():
            row.slider.blockSignals(True)
            row.slider.setValue(values[row.key])
            row.slider.blockSignals(False)
            row.value_label.setText(str(values[row.key]))
        self._paint_color_buttons(s)
        self._sync_enabled_state()

    def _paint_color_buttons(self, s):
        for key, btn in (("background_color", self.btn_bg_color),
                         ("text_color", self.btn_text_color),
                         ("frame_color", self.btn_slot_color)):
            color = QColor(s[key])
            if not color.isValid():
                color = QColor("#FFFFFF")
            btn.setStyleSheet(
                "QPushButton { background-color: %s; border: 2px solid #2A2D3A;"
                " border-radius: 6px; }" % color.name())
            btn.setToolTip("%s  (%s)" % (color.name().upper(), key))

    def _collect(self) -> dict:
        values = {row.key: row.slider.value() for row in self._rows()}
        return {
            "enabled": self.chk_enabled.isChecked(),
            "layout": canvas_layout.LAYOUT_ORDER[self.combo_layout.currentIndex()],
            "background_mode": canvas_layout.BACKGROUND_MODES[
                self.combo_mode.currentIndex()],
            "background_color": self._color_of(self.btn_bg_color),
            "texture": canvas_layout.TEXTURE_ORDER[
                self.combo_texture.currentIndex()],
            "texture_scale": values["texture_scale"] / 100.0,
            "overlay_opacity": values["overlay_opacity"] / 100.0,
            "slot_gap": values["slot_gap"] / 100.0,
            "header_text": self.edit_header.text(),
            "footer_text": self.edit_footer.text(),
            "header_font": canvas_layout.FONT_FAMILIES[
                self.combo_header_font.currentIndex()],
            "footer_font": canvas_layout.FONT_FAMILIES[
                self.combo_footer_font.currentIndex()],
            "header_size": float(self.spin_header_size.value()),
            "footer_size": float(self.spin_footer_size.value()),
            "header_bold": self.chk_header_bold.isChecked(),
            "footer_bold": self.chk_footer_bold.isChecked(),
            "text_color": self._color_of(self.btn_text_color),
            "frame_color": self._color_of(self.btn_slot_color),
            "auto_fit": self.chk_auto_fit.isChecked(),
            "play_sequentially": self.chk_sequential.isChecked(),
            "slot_seconds": float(self.spin_slot_seconds.value()),
            "manga_rotate_interval": ROTATE_CHOICES[
                self.combo_rotate.currentIndex()],
        }

    @staticmethod
    def _color_of(button):
        """Màu đang chọn đọc lại từ tooltip — khong them bom truc thai rieng."""
        tip = button.toolTip() or ""
        head = tip.split("  (")[0].strip()
        return head if QColor(head).isValid() else "#FFFFFF"

    def _pick_color(self, key):
        current = QColor(self._collect()[key])
        chosen = QColorDialog.getColor(current, self, "Màu %s" % key)
        if chosen.isValid():
            settings = dict(self._model.project_layout)
            settings[key] = chosen.name().upper()
            self._loading = True
            self._paint_color_buttons(settings)
            self._loading = False
            self._apply()

    def _apply(self, *_args):
        if self._loading:
            return
        settings = self._collect()
        self._model.set_project_layout(settings)
        self._paint_color_buttons(settings)
        self._sync_enabled_state()

    def _sync_enabled_state(self):
        """Master off thì hàng dưới chỉ để xem — khỏi đoán vì sao kéo không ăn."""
        on = self.chk_enabled.isChecked()
        mode = canvas_layout.BACKGROUND_MODES[self.combo_mode.currentIndex()]
        for widget in (self.combo_layout, self.combo_mode, self.combo_texture,
                       self.btn_bg_color, self.btn_slot_color,
                       self.btn_text_color, self.chk_auto_fit,
                       self.edit_header, self.edit_footer,
                       self.combo_header_font, self.combo_footer_font,
                       self.spin_header_size, self.spin_footer_size,
                       self.chk_header_bold, self.chk_footer_bold,
                       self.chk_sequential, self.spin_slot_seconds,
                       self.combo_rotate, self.btn_arrange):
            widget.setEnabled(on)
        for row in self._rows():
            row.setEnabled(on)
        # Ô màu nền chỉ có nghĩa khi nền là MÀU; chất liệu chỉ khi nền là chat lieu.
        self.btn_bg_color.setEnabled(on and mode == "color")
        self.combo_texture.setEnabled(on and mode == "texture")
        self._rows_by_key("texture_scale").setEnabled(
            on and mode == "texture")
        self._rows_by_key("slot_gap").setEnabled(
            on and self.combo_layout.currentIndex() > 0)

    def _rows_by_key(self, key):
        for row in self._rows():
            if row.key == key:
                return row
        return QWidget()

    # ── dàn clip vào ô ──────────────────────────────────────────
    def _arrange(self):
        """Viết transform theo ô cho các clip đang hiện ở playhead — MỘT undo."""
        from core.canvas_utils import ASPECT_RATIOS
        from core.commands import ArrangeSlotsCommand
        model = self._model
        w, h = ASPECT_RATIOS.get(getattr(model, "project_ratio", "16:9"),
                                 (1920, 1080))
        settings = model.project_layout
        boxes = canvas_layout.slots(w, h, settings)
        # Thu tu = thu tu duoi-len-tren cua timeline, dao nguoc de clip dang o
        # tren cung nhan o dau tien: nguoi dung muon cai ho vua xem o vi tri 1.
        active = [clip for track in model.tracks
                  for clip in track.clips
                  if clip.start_time <= model.playhead
                  < clip.start_time + clip.duration
                  and clip.media_type in ("image", "video", "sticker", "text")]
        if not active:
            self.lbl_arrange.setText("Không có clip nào tại playhead — di "
                                     "chuot tren timeline roi bam lai.")
            return
        order = list(reversed(active))[:len(boxes)]
        placements = [(clip.clip_id, index) for index, clip in enumerate(order)]
        fill = not settings["auto_fit"]
        command = ArrangeSlotsCommand(model, placements, w, h, fill=fill)
        self.main_window.timeline_panel.undo_stack.push(command)
        self.main_window.preview_panel.canvas.viewport().update()
        self.lbl_arrange.setText(
            "Da dan %d clip vao %d o (%s). Ctrl+Z de tra ve."
            % (len(placements), len(boxes),
               "lap o cuoi" if len(active) > len(boxes) else "du o"))

    def _fit_height(self):
        """Cua phai cao du cho HET dieu khien, khong duoc de no thu thanh cuon.

        Ly do da tra gia o SplitDialog (22/10): chieu cao hang so an dong cuoi
        cua body, va probe cung khong nhin thay no. Day chi LON LEN theo
        body.sizeHint() vi thu nho gi luc keo slider la cua nhay.
        """
        body = self._body
        if not self.isVisible():
            return
        needed = (self.height() - self._scroll.viewport().height()
                  + body.sizeHint().height())
        if needed > self.height():
            self.resize(self.width(), needed)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def _on_close(self):
        """Đóng = MỘT bước undo, nếu thật sự có gì đó thay đổi."""
        now = dict(self._model.project_layout)
        self.close()
        if now == self._opening:
            return
        from core.commands import SetProjectLayoutCommand
        self.main_window.timeline_panel.undo_stack.push(
            SetProjectLayoutCommand(self._model, now, before=self._opening))

    @staticmethod
    def _style():
        return """
        QDialog { background-color: #1A1C1F; border: 1px solid #34383D;
                  border-radius: 12px; color: #D8DCE0; }
        #LayoutTitleBar { background-color: #1A1B26;
                          border-bottom: 1px solid #2A2D3A;
                          border-top-left-radius: 12px;
                          border-top-right-radius: 12px; }
        #LayoutTitle { font-size: 15px; font-weight: 700; color: #FFFFFF;
                       background: transparent; }
        #LayoutX { background: transparent; border: none; border-radius: 4px; }
        #LayoutX:hover { background: #E81123; }
        #LayoutScroll, #LayoutBody { background: transparent; }
        QCheckBox { font-size: 12px; color: #E6E8EC; background: transparent; }
        QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
                               border: 1px solid #3A3F46; background: #23262B; }
        QCheckBox::indicator:checked { background: #40E0D0; border-color: #40E0D0; }
        QCheckBox:disabled, QComboBox:disabled, QLineEdit:disabled,
        QSpinBox:disabled, QPushButton:disabled { color: #5C6068; }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #23262B; border: 1px solid #3A3F46;
            border-radius: 6px; padding: 5px 8px; color: #E6E8EC; font-size: 12px;
        }
        QComboBox::drop-down { border: none; width: 20px; }
        QSlider::groove:horizontal { height: 4px; background: #2A2D3A; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: #40E0D0; border-radius: 2px; }
        QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0;
                                     border-radius: 6px; background: #E6E8EC; }
        #LayoutArrange { background-color: #24333A; border: 1px solid #3A5560;
                         border-radius: 8px; color: #7FE8DC; font-size: 12px;
                         padding: 8px 14px; text-align: center; }
        #LayoutArrange:hover { background-color: #2C4049; }
        #LayoutClose { background-color: #2A2D3A; border: 1px solid #3A3F46;
                       border-radius: 8px; color: #E6E8EC; font-size: 12px;
                       padding: 7px 18px; }
        #LayoutClose:hover { background-color: #3A3F46; }
        """
