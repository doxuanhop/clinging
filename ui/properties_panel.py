"""
ui/properties_panel.py
Bảng thuộc tính bên phải: tab THUỘC TÍNH / HIỆU ỨNG.
Cập nhật 2 chiều (Bi-directional) thông số kỹ thuật của Clip đang chọn.
Hỗ trợ đặt Keyframe (Hình thoi viên kim cương) và Auto-Keyframe chuẩn chỉnh.
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QLineEdit, QDoubleSpinBox, QSlider, QFormLayout, QFrame, QScrollArea, QPushButton,
    QComboBox
)

from widgets.common import AnimatedTabBar, FadeStack, set_label_icon, font_icon
from core import keyframe_graph, transitions


# Nút keyframe vẽ bằng font icon, nên màu phải đổi tay theo trạng thái:
# QIcon không ăn theo `color` trong QSS.
KF_ICON = "fa6s.diamond"
KF_IDLE_COLOR = "#555566"
KF_ACTIVE_COLOR = "#40E0D0"


def set_keyframe_button_state(btn, active: bool):
    btn.setProperty("active", "true" if active else "false")
    btn.setIcon(font_icon(KF_ICON,
                          KF_ACTIVE_COLOR if active else KF_IDLE_COLOR))
    btn.setIconSize(QSize(11, 11))
    btn.style().unpolish(btn)
    btn.style().polish(btn)


class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(14)

        icon = QLabel()
        icon.setObjectName("EmptyIconCircle")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(80, 80)
        set_label_icon(icon, "fa6s.gear", 28)

        title = QLabel("Chưa chọn đối tượng")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignCenter)

        desc = QLabel("Chọn một đối tượng trên canvas\nhoặc timeline để tùy chỉnh thông số")
        desc.setObjectName("EmptyDesc")
        desc.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon, alignment=Qt.AlignHCenter)
        layout.addWidget(title)
        layout.addWidget(desc)


class ClipPropertiesWidget(QWidget):
    """
    Widget hiển thị biểu mẫu thuộc tính cho một Clip dưới dạng card bo góc hiện đại.
    Hỗ trợ chèn Keyframe (nút kim cương Font Awesome) và tự động đặt
    Keyframe (Auto-Keyframe).
    """
    # Phát ra khi thuộc tính thay đổi: (clip_id, name, scale_x, scale_y, rotation, opacity, x, y)
    propertyChanged = Signal(str, str, float, float, float, float, float, float)
    keyframeStateChanged = Signal()  # Báo Timeline vẽ lại kim cương

    def __init__(self, clip_model, parent=None):
        super().__init__(parent)
        self.clip_model = clip_model
        self.clip_id = clip_model.clip_id
        # Đặt sớm để các setValue/setCurrentFont lúc dựng form không bị coi là
        # người dùng sửa và không đọc phải thuộc tính chưa tồn tại.
        self._block_signals = True

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sử dụng QScrollArea để cuộn nội dung mượt mà
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("PropertiesScroll")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(14)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # --- Card 1: Thông tin chung ---
        card_info = QFrame()
        card_info.setObjectName("PropertyCard")
        layout_info = QFormLayout(card_info)
        layout_info.setSpacing(8)
        layout_info.setContentsMargins(12, 12, 12, 12)
        
        lbl_info_title = QLabel("Thông tin chung")
        lbl_info_title.setObjectName("CardTitle")
        layout_info.addRow(lbl_info_title)

        self.input_name = QLineEdit(clip_model.name)
        self.input_name.textChanged.connect(self._on_values_changed)
        layout_info.addRow("Tên đối tượng:", self.input_name)

        # --- Card 2: Căn chỉnh & Tọa độ + Nút Keyframe ⬦ ---
        card_transform = QFrame()
        card_transform.setObjectName("PropertyCard")
        layout_transform = QFormLayout(card_transform)
        layout_transform.setSpacing(8)
        layout_transform.setContentsMargins(12, 12, 12, 12)

        lbl_transform_title = QLabel("Vị trí & Biến đổi (Transform)")
        lbl_transform_title.setObjectName("CardTitle")
        # Nut do thi nam cung hang tieu de vi no la hanh dong cua CA the
        # chuyen dong, khong thuoc ve rieng thong so nao ben duoi.
        transform_header = QWidget()
        header_layout = QHBoxLayout(transform_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(lbl_transform_title)
        header_layout.addStretch(1)
        self.btn_graph = QPushButton("Đồ thị")
        self.btn_graph.setObjectName("GraphEntryBtn")
        self.btn_graph.setIcon(font_icon("fa6s.bezier-curve", "#40E0D0"))
        self.btn_graph.setIconSize(QSize(12, 12))
        self.btn_graph.setFixedHeight(22)
        self.btn_graph.setCursor(Qt.PointingHandCursor)
        self.btn_graph.setToolTip("Xem và sửa đường cong chuyển động theo thời gian")
        self.btn_graph.clicked.connect(self._open_keyframe_graph)
        header_layout.addWidget(self.btn_graph)
        layout_transform.addRow(transform_header)

        # ── Fit / Fill Mode Toggle ──
        is_video_image = clip_model.media_type in ("video", "image")
        if is_video_image:
            mode_widget = QWidget()
            mode_layout = QHBoxLayout(mode_widget)
            mode_layout.setContentsMargins(0, 0, 0, 0)
            mode_layout.setSpacing(6)

            self.btn_fit = QPushButton("Fit")
            self.btn_fit.setCheckable(True)
            self.btn_fit.setFixedHeight(26)
            self.btn_fit.setCursor(Qt.PointingHandCursor)
            self.btn_fit.setObjectName("FitFillBtn")

            self.btn_fill = QPushButton("Fill")
            self.btn_fill.setCheckable(True)
            self.btn_fill.setFixedHeight(26)
            self.btn_fill.setCursor(Qt.PointingHandCursor)
            self.btn_fill.setObjectName("FitFillBtn")

            fit_mode = getattr(clip_model.transform, 'fit_mode', 'fit')
            self.btn_fit.setChecked(fit_mode == "fit")
            self.btn_fill.setChecked(fit_mode == "fill")

            self.btn_fit.clicked.connect(lambda: self._on_fit_mode_changed("fit"))
            self.btn_fill.clicked.connect(lambda: self._on_fit_mode_changed("fill"))

            mode_layout.addWidget(self.btn_fit)
            mode_layout.addWidget(self.btn_fill)
            layout_transform.addRow("Hiển thị:", mode_widget)

        # Danh sách lưu các nút bấm kim cương để cập nhật trạng thái hoạt động (active)
        self._kf_buttons = {}

        # Vị trí X
        self.spin_x = self.create_property_row(layout_transform, "Vị trí X (px):", clip_model.transform.x, -2000.0, 2000.0, "x")
        # Vị trí Y
        self.spin_y = self.create_property_row(layout_transform, "Vị trí Y (px):", clip_model.transform.y, -2000.0, 2000.0, "y")
        # Co giãn X
        self.spin_scale_x = self.create_property_row(layout_transform, "Co giãn X:", clip_model.transform.scale_x, 0.1, 10.0, "scale_x", step=0.1)
        # Co giãn Y
        self.spin_scale_y = self.create_property_row(layout_transform, "Co giãn Y:", clip_model.transform.scale_y, 0.1, 10.0, "scale_y", step=0.1)
        # Góc xoay
        self.spin_rotation = self.create_property_row(layout_transform, "Góc xoay (°):", clip_model.transform.rotation, 0.0, 360.0, "rotation")

        # Độ mờ (Opacity) Slider
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(8)
        
        self.btn_kf_opacity = QPushButton()
        self.btn_kf_opacity.setFixedSize(22, 22)
        self.btn_kf_opacity.setCursor(Qt.PointingHandCursor)
        self.btn_kf_opacity.setObjectName("KeyframeBtn")
        set_keyframe_button_state(self.btn_kf_opacity, False)
        self.btn_kf_opacity.clicked.connect(lambda: self.toggle_keyframe("opacity", self.btn_kf_opacity, self.slider_opacity.value() / 100.0))
        self._kf_buttons["opacity"] = self.btn_kf_opacity
        
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(int(clip_model.transform.opacity * 100))
        self.slider_opacity.valueChanged.connect(self._on_opacity_slider_changed)
        
        self.lbl_opacity_val = QLabel(f"{self.slider_opacity.value()}%")
        self.lbl_opacity_val.setFixedWidth(36)
        self.lbl_opacity_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_opacity_val.setStyleSheet("color: #A0A0A0; font-size: 11px;")
        
        opacity_layout.addWidget(self.btn_kf_opacity)
        opacity_layout.addWidget(self.slider_opacity)
        opacity_layout.addWidget(self.lbl_opacity_val)
        layout_transform.addRow("Độ mờ (%):", opacity_widget)

        # Thêm các Cards vào scroll area
        scroll_layout.addWidget(card_info)
        scroll_layout.addWidget(card_transform)

        # Card: Chuyển tiếp — cùng nguồn dữ liệu mà preview lẫn export cùng đọc.
        self.card_transition = QFrame()
        self.card_transition.setObjectName("PropertyCard")
        layout_transition = QFormLayout(self.card_transition)
        layout_transition.setSpacing(8)
        layout_transition.setContentsMargins(12, 12, 12, 12)

        lbl_transition_title = QLabel("Chuyển tiếp")
        lbl_transition_title.setObjectName("CardTitle")
        layout_transition.addRow(lbl_transition_title)

        self.combo_transition = QComboBox()
        self.combo_transition.addItem("(Không có)", "")
        for transition_name in transitions.TRANSITIONS:
            self.combo_transition.addItem(transition_name, transition_name)
        self.combo_transition.currentIndexChanged.connect(self._on_transition_changed)
        layout_transition.addRow("Kiểu:", self.combo_transition)

        duration_widget = QWidget()
        duration_layout = QHBoxLayout(duration_widget)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.setSpacing(8)
        self.slider_transition = QSlider(Qt.Horizontal)
        self.slider_transition.setRange(10, 100)
        self.slider_transition.valueChanged.connect(self._on_transition_duration_moving)
        # Chỉ commit khi thả chuột: mỗi lần set_transition là một ripple edit,
        # push theo từng pixel kéo sẽ ngập undo stack.
        self.slider_transition.sliderReleased.connect(self._on_transition_duration_released)
        self.lbl_transition_val = QLabel("1.00s")
        self.lbl_transition_val.setFixedWidth(44)
        self.lbl_transition_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_transition_val.setStyleSheet("color: #A0A0A0; font-size: 11px;")
        duration_layout.addWidget(self.slider_transition)
        duration_layout.addWidget(self.lbl_transition_val)
        layout_transition.addRow("Độ dài:", duration_widget)

        self.btn_transition_clear = QPushButton("Bỏ chuyển tiếp")
        self.btn_transition_clear.setObjectName("TransitionClearBtn")
        self.btn_transition_clear.setFixedHeight(26)
        self.btn_transition_clear.setCursor(Qt.PointingHandCursor)
        self.btn_transition_clear.clicked.connect(
            lambda: self._apply_transition("", None))
        layout_transition.addRow(self.btn_transition_clear)

        scroll_layout.addWidget(self.card_transition)
        self._sync_transition_card()

        # Card: Âm thanh — volume, tốc độ và fade của RIÊNG clip.
        self.card_audio = QFrame()
        self.card_audio.setObjectName("PropertyCard")
        layout_audio = QFormLayout(self.card_audio)
        layout_audio.setSpacing(8)
        layout_audio.setContentsMargins(12, 12, 12, 12)

        lbl_audio_title = QLabel("Âm thanh")
        lbl_audio_title.setObjectName("CardTitle")
        layout_audio.addRow(lbl_audio_title)

        (self.row_volume, self.slider_volume,
         self.lbl_volume_val) = self._create_audio_slider(
            0, 200, int(round(float(getattr(clip_model, "volume", 1.0)) * 100)))
        self.slider_volume.valueChanged.connect(self._on_volume_moving)
        self.slider_volume.sliderReleased.connect(self._on_volume_released)
        layout_audio.addRow("Âm lượng (%):", self.row_volume)

        # Cờ tắt tiếng của RIÊNG clip này, đứng ngay dưới Âm lượng vì hai thứ
        # cùng trả lời một câu hỏi. Không phải slider về 0: volume=0 mất con số
        # cũ, còn đây thì bật lại là đúng mức âm lượng đã chọn.
        self.btn_audio_mute = QPushButton("Tắt tiếng clip")
        self.btn_audio_mute.setObjectName("TransitionClearBtn")
        self.btn_audio_mute.setCheckable(True)
        self.btn_audio_mute.setFixedHeight(26)
        self.btn_audio_mute.setCursor(Qt.PointingHandCursor)
        self.btn_audio_mute.toggled.connect(self._on_mute_toggled)
        layout_audio.addRow(self.btn_audio_mute)

        (self.row_speed, self.slider_speed,
         self.lbl_speed_val) = self._create_audio_slider(
            25, 400, int(round(float(getattr(clip_model, "speed", 1.0)) * 100)))
        self.slider_speed.valueChanged.connect(self._on_speed_moving)
        self.slider_speed.sliderReleased.connect(self._on_speed_released)
        layout_audio.addRow("Tốc độ:", self.row_speed)

        (self.row_fade_in, self.slider_fade_in,
         self.lbl_fade_in_val) = self._create_audio_slider(
            0, 300, int(round(float(getattr(clip_model, "fade_in", 0.0)) * 100)))
        self.slider_fade_in.valueChanged.connect(self._on_fade_in_moving)
        self.slider_fade_in.sliderReleased.connect(self._on_fade_in_released)
        layout_audio.addRow("Fade vào (s):", self.row_fade_in)

        (self.row_fade_out, self.slider_fade_out,
         self.lbl_fade_out_val) = self._create_audio_slider(
            0, 300, int(round(float(getattr(clip_model, "fade_out", 0.0)) * 100)))
        self.slider_fade_out.valueChanged.connect(self._on_fade_out_moving)
        self.slider_fade_out.sliderReleased.connect(self._on_fade_out_released)
        layout_audio.addRow("Fade ra (s):", self.row_fade_out)

        self.btn_audio_reset = QPushButton("Về mặc định")
        self.btn_audio_reset.setObjectName("TransitionClearBtn")
        self.btn_audio_reset.setFixedHeight(26)
        self.btn_audio_reset.setCursor(Qt.PointingHandCursor)
        self.btn_audio_reset.clicked.connect(
            lambda: self._apply_clip_audio(
                volume=1.0, speed=1.0, fade_in=0.0, fade_out=0.0,
                audio_muted=False))
        layout_audio.addRow(self.btn_audio_reset)

        # Chỉ clip mang tiếng thật mới có thẻ này: text/sticker không có luồng
        # âm thanh, hiện thanh trượt cho chúng là UI nói dối.
        self.card_audio.setVisible(
            clip_model.media_type in ("video", "audio"))
        scroll_layout.addWidget(self.card_audio)
        self._sync_audio_card()
        
        # Card 3: Nhóm chuyên biệt cho Văn bản (ẩn mặc định)
        self.card_text = QFrame()
        self.card_text.setObjectName("PropertyCard")
        layout_text = QFormLayout(self.card_text)
        layout_text.setSpacing(8)
        layout_text.setContentsMargins(12, 12, 12, 12)
        
        lbl_text_title = QLabel("Thuộc tính Văn bản")
        lbl_text_title.setObjectName("CardTitle")
        layout_text.addRow(lbl_text_title)
        
        # Font chữ
        from PySide6.QtWidgets import QFontComboBox
        self.combo_font = QFontComboBox()
        self.combo_font.setCurrentFont(QFont(clip_model.font_family))
        self.combo_font.currentFontChanged.connect(self._on_font_changed)
        layout_text.addRow("Phông chữ:", self.combo_font)

        # Cỡ chữ
        self.spin_font_size = QDoubleSpinBox()
        self.spin_font_size.setRange(8.0, 200.0)
        self.spin_font_size.setValue(float(clip_model.font_size))
        self.spin_font_size.setSingleStep(2.0)
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        layout_text.addRow("Cỡ chữ:", self.spin_font_size)

        # Định dạng chữ: Bold, Italic, Underline
        format_widget = QWidget()
        format_layout = QHBoxLayout(format_widget)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(4)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedSize(32, 26)
        self.btn_bold.setCursor(Qt.PointingHandCursor)
        self.btn_bold.setObjectName("TextFormatBtn")
        font_bold = QFont()
        font_bold.setBold(True)
        self.btn_bold.setFont(font_bold)
        self.btn_bold.clicked.connect(self._on_bold_toggled)

        self.btn_italic = QPushButton("I")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedSize(32, 26)
        self.btn_italic.setCursor(Qt.PointingHandCursor)
        self.btn_italic.setObjectName("TextFormatBtn")
        font_italic = QFont()
        font_italic.setItalic(True)
        self.btn_italic.setFont(font_italic)
        self.btn_italic.clicked.connect(self._on_italic_toggled)

        self.btn_underline = QPushButton("U")
        self.btn_underline.setCheckable(True)
        self.btn_underline.setFixedSize(32, 26)
        self.btn_underline.setCursor(Qt.PointingHandCursor)
        self.btn_underline.setObjectName("TextFormatBtn")
        font_underline = QFont()
        font_underline.setUnderline(True)
        self.btn_underline.setFont(font_underline)
        self.btn_underline.clicked.connect(self._on_underline_toggled)

        self.btn_bold.setChecked(bool(clip_model.font_bold))
        self.btn_italic.setChecked(bool(clip_model.font_italic))
        self.btn_underline.setChecked(bool(clip_model.font_underline))

        format_layout.addWidget(self.btn_bold)
        format_layout.addWidget(self.btn_italic)
        format_layout.addWidget(self.btn_underline)
        format_layout.addStretch(1)
        layout_text.addRow("Định dạng:", format_widget)

        # Màu chữ
        self.btn_text_color = QPushButton("Chọn màu")
        self.btn_text_color.setFixedSize(80, 28)
        self._set_color_swatch(clip_model.font_color)
        self.btn_text_color.clicked.connect(self._on_text_color_clicked)
        layout_text.addRow("Màu chữ:", self.btn_text_color)

        # Kiểu karaoke = màu của TỪNG TỪ theo tiến độ clip. Đứng riêng khỏi
        # "Kiểu chạy" bên dưới vì hai thứ nhân lên nhau, không loại trừ nhau:
        # chữ vẫn chạy wave mà vẫn quét sáng từng từ được.
        from core import karaoke_paint
        self.combo_text_style = QComboBox()
        self.combo_text_style.addItem("Không (một màu)", "none")
        for style_key, style_label in karaoke_paint.KARAOKE_STYLES:
            self.combo_text_style.addItem(style_label, style_key)
        style_idx = self.combo_text_style.findData(clip_model.text_style or "none")
        self.combo_text_style.setCurrentIndex(max(0, style_idx))
        self.combo_text_style.currentIndexChanged.connect(self._on_text_style_changed)
        layout_text.addRow("Kiểu karaoke:", self.combo_text_style)
        
        # Nội dung text
        from PySide6.QtWidgets import QTextEdit
        self.text_edit = QTextEdit()
        self.text_edit.setMaximumHeight(80)
        self.text_edit.setPlainText(clip_model.name)
        self.text_edit.textChanged.connect(self._on_text_content_changed)
        layout_text.addRow("Nội dung:", self.text_edit)
        
        # Card 4: Hiệu ứng chữ chạy — model là nguồn sự thật cho cả preview lẫn export
        self.card_motion = QFrame()
        self.card_motion.setObjectName("PropertyCard")
        layout_motion = QFormLayout(self.card_motion)
        layout_motion.setSpacing(8)
        layout_motion.setContentsMargins(12, 12, 12, 12)

        lbl_motion_title = QLabel("Chữ chạy")
        lbl_motion_title.setObjectName("CardTitle")
        layout_motion.addRow(lbl_motion_title)

        from core import anim_engine
        self.combo_text_effect = QComboBox()
        self.combo_text_effect.addItem("Không (đứng yên)", "none")
        for key, label, _desc in anim_engine.TEXT_EFFECTS:
            if key != "none":
                self.combo_text_effect.addItem(label, key)
        idx = self.combo_text_effect.findData(clip_model.text_effect or "none")
        self.combo_text_effect.setCurrentIndex(max(0, idx))
        self.combo_text_effect.currentIndexChanged.connect(self._on_text_effect_changed)
        layout_motion.addRow("Kiểu chạy:", self.combo_text_effect)

        intensity_widget = QWidget()
        intensity_layout = QHBoxLayout(intensity_widget)
        intensity_layout.setContentsMargins(0, 0, 0, 0)
        intensity_layout.setSpacing(8)
        self.slider_text_intensity = QSlider(Qt.Horizontal)
        self.slider_text_intensity.setRange(0, 100)
        self.slider_text_intensity.setValue(int(round(float(clip_model.text_effect_intensity) * 100)))
        self.slider_text_intensity.valueChanged.connect(self._on_text_intensity_changed)
        self.lbl_text_intensity = QLabel(f"{self.slider_text_intensity.value()}%")
        self.lbl_text_intensity.setFixedWidth(36)
        self.lbl_text_intensity.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_text_intensity.setStyleSheet("color: #A0A0A0; font-size: 11px;")
        intensity_layout.addWidget(self.slider_text_intensity)
        intensity_layout.addWidget(self.lbl_text_intensity)
        layout_motion.addRow("Cường độ:", intensity_widget)

        # Ẩn/hiện dựa trên media_type
        is_text = clip_model.media_type == "text"
        self.card_text.setVisible(is_text)
        self.card_motion.setVisible(is_text)
        
        scroll_layout.addWidget(self.card_text)
        scroll_layout.addWidget(self.card_motion)
        scroll_layout.addStretch(1)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        self._block_signals = False
        
        # Đồng bộ màu kim cương ban đầu
        self.update_keyframe_buttons_ui()

    def create_property_row(self, layout, label_text, default_val, min_val, max_val, property_key, step=1.0):
        """Tạo hàng thuộc tính có nút kim cương và ô nhập SpinBox."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        lbl = QLabel(label_text)
        
        # Nút keyframe hình kim cương (Font Awesome)
        btn_kf = QPushButton()
        btn_kf.setFixedSize(22, 22)
        btn_kf.setCursor(Qt.PointingHandCursor)
        btn_kf.setObjectName("KeyframeBtn")
        set_keyframe_button_state(btn_kf, False)
        self._kf_buttons[property_key] = btn_kf

        # Ô SpinBox
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setDecimals(2)
        spin.setSingleStep(step)
        spin.setValue(default_val)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        
        # Kết nối tín hiệu
        btn_kf.clicked.connect(lambda: self.toggle_keyframe(property_key, btn_kf, spin.value()))
        spin.valueChanged.connect(lambda val: self._on_spin_changed(property_key, val, btn_kf))

        row_layout.addWidget(lbl)
        row_layout.addStretch(1)
        row_layout.addWidget(btn_kf)
        row_layout.addWidget(spin)
        
        layout.addRow(row_widget)
        return spin

    def toggle_keyframe(self, property_key, btn_widget, current_value):
        """Bật hoặc tắt keyframe tại Playhead hiện tại."""
        main_window = self._find_main_window()
        if not main_window:
            return
            
        playhead_time = main_window.timeline_panel.model.playhead
        local_time = playhead_time - self.clip_model.start_time
        
        if local_time < 0:
            return
        
        from core.commands import ToggleKeyframeCommand
        cmd = ToggleKeyframeCommand(
            main_window.timeline_panel.model,
            self.clip_model.clip_id,
            property_key,
            local_time,
            current_value,
        )
        main_window.timeline_panel.undo_stack.push(cmd)
        
        is_added = cmd._was_added
        set_keyframe_button_state(btn_widget, is_added)
        
        self.keyframeStateChanged.emit()

    def _on_spin_changed(self, property_key, new_value, btn_widget):
        if self._block_signals:
            return
            
        frames = self.clip_model.keyframes.get(property_key, [])
        main_window = self._find_main_window()
        if main_window and len(frames) > 0:
            playhead_time = main_window.timeline_panel.model.playhead
            local_time = playhead_time - self.clip_model.start_time
            if local_time >= 0:
                old_value = self.clip_model.get_value_at_time(
                    property_key, local_time, new_value
                )
                from core.commands import AutoKeyframeCommand
                cmd = AutoKeyframeCommand(
                    main_window.timeline_panel.model,
                    self.clip_model.clip_id,
                    property_key,
                    local_time,
                    old_value,
                    new_value,
                )
                main_window.timeline_panel.undo_stack.push(cmd)
                
                set_keyframe_button_state(btn_widget, True)
                
                self.keyframeStateChanged.emit()

        self._on_values_changed()

    def _on_opacity_slider_changed(self, value):
        self.lbl_opacity_val.setText(f"{value}%")
        
        if self._block_signals:
            return
        
        btn_widget = self._kf_buttons.get("opacity")
        frames = self.clip_model.keyframes.get("opacity", [])
        main_window = self._find_main_window()
        if main_window and len(frames) > 0:
            playhead_time = main_window.timeline_panel.model.playhead
            local_time = playhead_time - self.clip_model.start_time
            if local_time >= 0:
                old_value = self.clip_model.get_value_at_time(
                    "opacity", local_time, value / 100.0
                )
                from core.commands import AutoKeyframeCommand
                cmd = AutoKeyframeCommand(
                    main_window.timeline_panel.model,
                    self.clip_model.clip_id,
                    "opacity",
                    local_time,
                    old_value,
                    value / 100.0,
                )
                main_window.timeline_panel.undo_stack.push(cmd)
                if btn_widget:
                    set_keyframe_button_state(btn_widget, True)
                self.keyframeStateChanged.emit()
            
        self._on_values_changed()

    def update_keyframe_buttons_ui(self):
        """Cập nhật màu nút kim cương (đã chốt / chưa chốt) tại vị trí playhead hiện tại."""
        # Cung mot quy tac voi menu chuot phai cua clip: do thi chi co noi dung
        # khi clip that su co moc. Xong truoc vi doan duoi day can main_window
        # va co the nghi som khi widget chua nam trong panel.
        self.btn_graph.setVisible(
            bool(keyframe_graph.animated_properties(self.clip_model)))

        main_window = self._find_main_window()
        if not main_window:
            return
            
        playhead_time = main_window.timeline_panel.model.playhead
        local_time = playhead_time - self.clip_model.start_time
        
        for prop_key, btn in self._kf_buttons.items():
            frames = self.clip_model.keyframes.get(prop_key, [])
            is_active = any(abs(frame[0] - local_time) < 0.05 for frame in frames)
            set_keyframe_button_state(btn, is_active)

    def _open_keyframe_graph(self):
        main_window = self._find_main_window()
        if main_window is None:
            return None
        return main_window._open_keyframe_graph(self.clip_model.clip_id)

    def _find_main_window(self) -> QWidget:
        # Helper tìm MainWindow
        p = self.parent()
        while p:
            if p.objectName() == "MainWindow" or hasattr(p, "timeline_panel"):
                return p
            p = p.parent()
        return None

    # ── Text-specific methods ───────────────────────────────────

    def _canvas_item(self):
        """Item đang vẽ clip này trên Canvas Player (nếu có)."""
        main_window = self._find_main_window()
        if main_window is None:
            return None
        return main_window.preview_panel.canvas._clip_items.get(self.clip_id)

    def _refresh_canvas(self):
        item = self._canvas_item()
        if item is not None and hasattr(item, "refresh_style"):
            item.refresh_style()
        elif item is not None:
            item.update()
        self._on_values_changed()

    def _set_color_swatch(self, color):
        self.btn_text_color.setStyleSheet(
            f"background-color: {color}; border: 1px solid #333;")

    def _on_font_changed(self, font):
        """Cập nhật font chữ khi thay đổi."""
        if self._block_signals:
            return
        self.clip_model.font_family = font.family()
        self._refresh_canvas()

    def _on_font_size_changed(self, value):
        """Cập nhật cỡ chữ."""
        if self._block_signals:
            return
        self.clip_model.font_size = float(value)
        self._refresh_canvas()

    def _on_bold_toggled(self):
        """Bật/tắt chữ đậm."""
        if self._block_signals:
            return
        self.clip_model.font_bold = self.btn_bold.isChecked()
        self._refresh_canvas()

    def _on_italic_toggled(self):
        """Bật/tắt chữ nghiêng."""
        if self._block_signals:
            return
        self.clip_model.font_italic = self.btn_italic.isChecked()
        self._refresh_canvas()

    def _on_underline_toggled(self):
        """Bật/tắt gạch chân."""
        if self._block_signals:
            return
        self.clip_model.font_underline = self.btn_underline.isChecked()
        self._refresh_canvas()

    def _on_text_color_clicked(self):
        """Chọn màu chữ."""
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            self._set_color_swatch(color.name())
            self.clip_model.font_color = color.name()
            self._refresh_canvas()

    def _on_text_content_changed(self):
        """Cập nhật nội dung văn bản."""
        if self._block_signals:
            return
        text = self.text_edit.toPlainText()
        self.clip_model.name = text
        self.input_name.setText(text)
        self._refresh_canvas()

    def _on_text_effect_changed(self, index):
        """Chọn kiểu chữ chạy."""
        if self._block_signals:
            return
        self.clip_model.text_effect = self.combo_text_effect.itemData(index) or "none"
        self._refresh_canvas()

    def _on_text_style_changed(self, index):
        """Chọn kiểu karaoke — chỉ đổi MÀU theo từ, không đổi hình học khối chữ."""
        if self._block_signals:
            return
        self.clip_model.text_style = self.combo_text_style.itemData(index) or "none"
        self._refresh_canvas()

    def _on_text_intensity_changed(self, value):
        """Cường độ chữ chạy, lưu theo thang 0..1 của EffectData."""
        self.lbl_text_intensity.setText(f"{value}%")
        if self._block_signals:
            return
        self.clip_model.text_effect_intensity = value / 100.0
        self._refresh_canvas()

    def _on_fit_mode_changed(self, mode):
        """Chuyển đổi giữa Fit và Fill mode."""
        if self._block_signals:
            return

        self.clip_model.transform.fit_mode = mode
        self.btn_fit.setChecked(mode == "fit")
        self.btn_fill.setChecked(mode == "fill")

        main_window = self._find_main_window()
        if main_window:
            from core.canvas_utils import apply_auto_fit, ASPECT_RATIOS
            ratio_key = main_window.timeline_panel.header.combo_aspect_ratio.currentText()
            ratio_key = ratio_key.split(" - ")[0] if " - " in ratio_key else "16:9"
            canvas_w, canvas_h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))
            apply_auto_fit(self.clip_model, canvas_w, canvas_h)

            canvas_item = main_window.preview_panel.canvas._clip_items.get(self.clip_id)
            if canvas_item:
                canvas_item.sync_from_model()
                canvas_item.update()

            self._on_values_changed()

    # ── Transition card ─────────────────────────────────────────

    def _model(self):
        main_window = self._find_main_window()
        return main_window.timeline_panel.model if main_window else None

    def _sync_transition_card(self):
        """Đọc chuyển tiếp từ model và tắt những kiểu timeline này chưa chỗ chứa.

        Room tính lại mỗi lần sync vì trim một clip có thể làm chuyển tiếp hợp lệ
        thành không hợp lệ; để chọn được rồi im lặng không áp thì người dùng chỉ
        thấy UI nói dối.
        """
        model = self._model()
        clip = model.get_clip(self.clip_id) if model else self.clip_model
        if clip is None:
            self.card_transition.setVisible(False)
            return

        blocked = self._block_signals
        self._block_signals = True
        current = transitions.name_of(clip)
        for i in range(self.combo_transition.count()):
            name = self.combo_transition.itemData(i) or ""
            room = (model.max_transition_duration(self.clip_id, name)
                    if model is not None and name else 1.0)
            self.combo_transition.model().item(i).setEnabled(room > 0.0)
        self.combo_transition.setCurrentIndex(
            max(0, self.combo_transition.findData(current)))

        room = 0.0
        if model is not None and current:
            room = model.max_transition_duration(self.clip_id, current)
        top = max(1, int(round(room * 100)))
        self.slider_transition.setEnabled(bool(current) and room > 0.0)
        self.slider_transition.setMinimum(min(10, top))
        self.slider_transition.setMaximum(top)
        # Không có chuyển tiếp thì con trỏ đứng ở độ dài mặc định, không phải
        # 0.00s — người dùng thấy số đó rồi kéo xuống một kiểu mới.
        shown = transitions.duration_of(clip) if current else transitions.DEFAULT_DURATION
        self.slider_transition.setValue(int(round(
            max(0.01, min(shown, room if (current and room > 0.0) else 999.0)) * 100)))
        self.lbl_transition_val.setText(
            "%.2fs" % (self.slider_transition.value() / 100.0))
        self.btn_transition_clear.setEnabled(bool(current))
        self._block_signals = blocked

    def _on_transition_changed(self, index):
        if self._block_signals:
            return
        name = self.combo_transition.itemData(index) or ""
        if name == transitions.name_of(self.clip_model):
            return
        self._apply_transition(name, None)

    def _on_transition_duration_moving(self, value):
        self.lbl_transition_val.setText("%.2fs" % (value / 100.0))

    def _on_transition_duration_released(self):
        if self._block_signals:
            return
        name = transitions.name_of(self.clip_model)
        if not name:
            return
        requested = self.slider_transition.value() / 100.0
        if abs(requested - transitions.duration_of(self.clip_model)) < 0.005:
            return
        self._apply_transition(name, requested)

    def _apply_transition(self, name, duration):
        model = self._model()
        main_window = self._find_main_window()
        if model is None or main_window is None:
            return
        from core.commands import SetTransitionCommand
        main_window.timeline_panel.undo_stack.push(
            SetTransitionCommand(model, self.clip_id, name, duration))
        # Ripple có thể đã co duration vừa kéo; đọc lại model thay vì tin con số
        # trên slider.
        self._sync_transition_card()
        main_window._sync_canvas()

    # ── Audio card ──────────────────────────────────────────────

    def _create_audio_slider(self, minimum: int, maximum: int, value: int):
        """Hàng slider + nhãn — cùng kiểu trình bày với thẻ Chuyển tiếp."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        label = QLabel("")
        label.setFixedWidth(44)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet("color: #A0A0A0; font-size: 11px;")
        row_layout.addWidget(slider)
        row_layout.addWidget(label)
        return row, slider, label

    def _clip(self):
        model = self._model()
        if model is not None:
            found = model.get_clip(self.clip_id)
            if found is not None:
                return found
        return self.clip_model

    def _paint_audio_labels(self):
        self.lbl_volume_val.setText("%d%%" % self.slider_volume.value())
        self.lbl_speed_val.setText("%.2fx" % (self.slider_speed.value() / 100.0))
        self.lbl_fade_in_val.setText("%.2fs" % (self.slider_fade_in.value() / 100.0))
        self.lbl_fade_out_val.setText("%.2fs" % (self.slider_fade_out.value() / 100.0))
        self._paint_audio_mute(bool(self.btn_audio_mute.isChecked()))

    def _paint_audio_mute(self, muted: bool):
        """Nhãn và icon phải mô tả ĐIỀU SẮP XẢY RA khi bấm, không phải trạng thái
        của chính cái nút — người dùng không nhìn vào checkbox, họ nhìn vào chỗ
        tiếng đáng lẽ ra."""
        self.btn_audio_mute.setText("Bật tiếng clip" if muted else "Tắt tiếng clip")
        self.btn_audio_mute.setIcon(font_icon(
            "fa6s.volume-high" if muted else "fa6s.volume-xmark",
            "#8a8a92" if muted else "#40E0D0"))

    def _sync_audio_card(self):
        """Đọc lại bốn giá trị từ model — model clamp, slider không được quyền tin số của mình."""
        clip = self._clip()
        if clip is None or clip.media_type not in ("video", "audio"):
            self.card_audio.setVisible(False)
            return
        self.card_audio.setVisible(True)

        blocked = self._block_signals
        self._block_signals = True
        # Trần của hai ramp là độ dài clip: để slider kéo tới 3s trên clip 1s thì
        # người dùng thả tay thấy số 3.00s trong khi model đã kẹp về 0.x.
        fade_room = max(1, int(round(float(clip.duration) * 100)))
        for slider in (self.slider_fade_in, self.slider_fade_out):
            slider.setMinimum(0)
            slider.setMaximum(fade_room)
        self.slider_volume.setValue(int(round(clip.volume_level * 100)))
        self.slider_speed.setValue(int(round(clip.speed_factor * 100)))
        self.slider_fade_in.setValue(int(round(float(clip.fade_in) * 100)))
        self.slider_fade_out.setValue(int(round(float(clip.fade_out) * 100)))
        self.btn_audio_mute.setChecked(bool(getattr(clip, "audio_muted", False)))
        self._paint_audio_labels()
        self._block_signals = blocked

    def _on_volume_moving(self, value):
        self.lbl_volume_val.setText("%d%%" % value)

    def _on_speed_moving(self, value):
        self.lbl_speed_val.setText("%.2fx" % (value / 100.0))

    def _on_fade_in_moving(self, value):
        self.lbl_fade_in_val.setText("%.2fs" % (value / 100.0))

    def _on_fade_out_moving(self, value):
        self.lbl_fade_out_val.setText("%.2fs" % (value / 100.0))

    def _on_volume_released(self):
        self._commit_audio(volume=self.slider_volume.value() / 100.0)

    def _on_mute_toggled(self, checked):
        """Một cú bấm = một lệnh undo được, kể cả khi Qt tự đổi checked lúc sync."""
        if self._block_signals:
            return
        clip = self._clip()
        if clip is None or bool(clip.audio_muted) == bool(checked):
            return
        self._apply_clip_audio(audio_muted=bool(checked))

    def _on_speed_released(self):
        self._commit_audio(speed=self.slider_speed.value() / 100.0)

    def _on_fade_in_released(self):
        self._commit_audio(fade_in=self.slider_fade_in.value() / 100.0)

    def _on_fade_out_released(self):
        self._commit_audio(fade_out=self.slider_fade_out.value() / 100.0)

    def _commit_audio(self, **changes):
        if self._block_signals:
            return
        clip = self._clip()
        if clip is None:
            return
        current = {"volume": clip.volume_level, "speed": clip.speed_factor,
                   "fade_in": float(clip.fade_in), "fade_out": float(clip.fade_out)}
        # Kéo trả về đúng số cũ là lệnh rỗng: mỗi lệnh rỗng thêm một lần Ctrl+Z
        # không hoàn tác được gì.
        if all(abs(current[key] - float(value)) < 0.005
               for key, value in changes.items()):
            return
        self._apply_clip_audio(**changes)

    def _apply_clip_audio(self, **changes):
        model = self._model()
        main_window = self._find_main_window()
        if model is None or main_window is None:
            return
        from core.commands import SetClipAudioCommand
        main_window.timeline_panel.undo_stack.push(
            SetClipAudioCommand(model, self.clip_id, **changes))
        self._sync_audio_card()

        item = main_window.timeline_panel.scene._clip_items.get(self.clip_id)
        if item is not None:
            # Đổi tốc độ/trim đổi CỬA SỔ nguồn nên phải trích xuất lại; hàm đó tự
            # nhận ra cửa sổ không đổi, nên kéo âm lượng không tốn một lần giải mã.
            item.refresh_media_extraction()
            item.update()
        main_window._sync_canvas()

    def update_values(self, clip_model):
        """Cập nhật các ô nhập liệu từ Model (khi tương tác kéo trên Canvas)."""
        self._block_signals = True
        self.input_name.setText(clip_model.name)
        self.spin_x.setValue(clip_model.transform.x)
        self.spin_y.setValue(clip_model.transform.y)
        self.spin_scale_x.setValue(clip_model.transform.scale_x)
        self.spin_scale_y.setValue(clip_model.transform.scale_y)
        self.spin_rotation.setValue(clip_model.transform.rotation)
        opacity_percent = int(clip_model.transform.opacity * 100)
        self.slider_opacity.setValue(opacity_percent)
        self.lbl_opacity_val.setText(f"{opacity_percent}%")
        if clip_model.media_type == "text":
            self.combo_font.setCurrentFont(QFont(clip_model.font_family))
            self.spin_font_size.setValue(float(clip_model.font_size))
            self.btn_bold.setChecked(bool(clip_model.font_bold))
            self.btn_italic.setChecked(bool(clip_model.font_italic))
            self.btn_underline.setChecked(bool(clip_model.font_underline))
            self._set_color_swatch(clip_model.font_color)
            if self.text_edit.toPlainText() != clip_model.name:
                self.text_edit.setPlainText(clip_model.name)
            idx = self.combo_text_effect.findData(clip_model.text_effect or "none")
            self.combo_text_effect.setCurrentIndex(max(0, idx))
            style_idx = self.combo_text_style.findData(clip_model.text_style or "none")
            self.combo_text_style.setCurrentIndex(max(0, style_idx))
            intensity_percent = int(round(float(clip_model.text_effect_intensity) * 100))
            self.slider_text_intensity.setValue(intensity_percent)
            self.lbl_text_intensity.setText(f"{intensity_percent}%")
        self._block_signals = False
        # Chuyển tiếp đổi theo ripple của những lệnh khác (xóa/trim clip), nên
        # phải đọc lại từ model mỗi lần panel cập nhật.
        self._sync_transition_card()
        self._sync_audio_card()
        
        # Cập nhật màu các nút kim cương
        self.update_keyframe_buttons_ui()

    def _on_values_changed(self, *args):
        if self._block_signals:
            return
        
        self.propertyChanged.emit(
            self.clip_id,
            self.input_name.text(),
            self.spin_scale_x.value(),
            self.spin_scale_y.value(),
            self.spin_rotation.value(),
            self.slider_opacity.value() / 100.0,
            self.spin_x.value(),
            self.spin_y.value()
        )


class PropertiesPanel(QWidget):
    clipPropertiesChanged = Signal(str, str, float, float, float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PropertiesPanel")
        self.setFixedWidth(330)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 18, 16, 16)
        outer.setSpacing(14)

        title = QLabel("Bảng Thuộc tính - Properties")
        title.setObjectName("PropTitle")
        outer.addWidget(title)

        self.tabs = AnimatedTabBar(["THUỘC TÍNH", "HIỆU ỨNG"], object_name="PropTab", spacing=24)
        outer.addWidget(self.tabs)

        self.stack = QStackedWidget()
        self.stack.addWidget(EmptyState())
        self.stack.addWidget(EmptyState())
        self.fade_stack = FadeStack(self.stack)
        outer.addWidget(self.fade_stack, 1)

        self.tabs.currentChanged.connect(self.fade_stack.set_index)
        self.current_editor = None

        # Áp dụng bộ QSS tùy biến hiện đại card-based màu tím
        self.apply_properties_stylesheet()

    def show_empty(self):
        """Khôi phục trạng thái trống."""
        if self.current_editor:
            self.current_editor.deleteLater()
            self.current_editor = None
        self.stack.removeWidget(self.stack.widget(0))
        self.stack.insertWidget(0, EmptyState())
        self.stack.setCurrentIndex(0)

    def show_clip_properties(self, clip_model):
        """Hiển thị trình cấu hình thông số của clip được chọn."""
        if self.current_editor and self.current_editor.clip_id == clip_model.clip_id:
            self.current_editor.update_values(clip_model)
            return

        if self.current_editor:
            self.current_editor.deleteLater()
            self.current_editor = None
            
        self.current_editor = ClipPropertiesWidget(clip_model)
        self.current_editor.propertyChanged.connect(self.clipPropertiesChanged.emit)
        
        main_window = self._find_main_window()
        if main_window:
            clip_item = main_window.timeline_panel.scene._clip_items.get(clip_model.clip_id)
            if clip_item:
                self.current_editor.keyframeStateChanged.connect(clip_item.sync_keyframe_nodes_from_model)
            self.current_editor.keyframeStateChanged.connect(main_window.timeline_panel.scene.update)
        
        self.stack.removeWidget(self.stack.widget(0))
        self.stack.insertWidget(0, self.current_editor)
        self.stack.setCurrentIndex(0)
        # ClipPropertiesWidget.__init__ đồng bộ thẻ chuyển tiếp lúc nó CHƯA có
        # cha, nên _find_main_window() trả None và mọi kiểu đều được mở. Phải sync
        # lại sau khi widget đã nằm trong panel thì danh sách "không đủ chỗ" mới
        # đúng — nếu không, clip đầu hàng vẫn bấm được junction rồi im lặng.
        self.current_editor.update_values(clip_model)
        # Cập nhật tab hiệu ứng
        self.update_effects_tab(clip_model)

    def update_editor_values(self, clip_model):
        """Đồng bộ hóa giá trị khi người dùng kéo dãn trên canvas."""
        if self.current_editor and self.current_editor.clip_id == clip_model.clip_id:
            self.current_editor.update_values(clip_model)

    def update_effects_tab(self, clip_model):
        """Cập nhật tab HIỆU ỨNG với danh sách hiệu ứng đã áp dụng lên clip."""
        from ui.effects_list_widget import EffectsListWidget
        old = self.stack.widget(1)
        if old:
            old.deleteLater()
        widget = EffectsListWidget(clip_model)
        widget.effectRemoved.connect(self._on_effect_removed_from_clip)
        widget.effectIntensityChanged.connect(self._on_effect_intensity_changed)
        self.stack.insertWidget(1, widget)
        self._current_effects_clip = clip_model

    def _on_effect_removed_from_clip(self, clip_id, effect_name):
        """Xóa hiệu ứng khỏi clip."""
        main_window = self._find_main_window()
        if main_window:
            from core.commands import RemoveEffectCommand
            cmd = RemoveEffectCommand(main_window.timeline_panel.model, clip_id, effect_name)
            main_window.timeline_panel.undo_stack.push(cmd)
            clip = main_window.timeline_panel.model.get_clip(clip_id)
            if clip:
                self.update_effects_tab(clip)
            main_window._sync_canvas()

    def _on_effect_intensity_changed(self, clip_id, effect_name, intensity):
        """Thay đổi cường độ hiệu ứng."""
        main_window = self._find_main_window()
        if main_window:
            clip = main_window.timeline_panel.model.get_clip(clip_id)
            if clip:
                for e in clip.effects:
                    if e.name == effect_name:
                        e.intensity = intensity
                        break
                main_window._sync_canvas()

    def update_panel_for_item(self, selected_item):
        """
        Hàm điều khiển chính — cập nhật Properties Panel dựa trên loại đối tượng.
        Hỗ trợ: CanvasClipItem (Video/Image), TextClipItem (Text), hoặc None.
        """
        if selected_item is None:
            self.show_empty()
            return

        # Lấy clip_model từ item
        clip_model = None
        if hasattr(selected_item, 'clip_model'):
            clip_model = selected_item.clip_model
        
        if clip_model is None:
            self.show_empty()
            return

        # Hiển thị properties cho clip
        self.show_clip_properties(clip_model)

    def _find_main_window(self) -> QWidget:
        p = self.parent()
        while p:
            if p.objectName() == "MainWindow" or hasattr(p, "timeline_panel"):
                return p
            p = p.parent()
        return None

    def apply_properties_stylesheet(self):
        self.setStyleSheet("""
            /* Tổng thể Tab Widget */
            QTabWidget::pane {
                border: none;
                background-color: #0D0E15;
            }
            QTabBar::tab {
                background: transparent;
                color: #888888;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #FFFFFF;
                border-bottom: 2px solid #40E0D0;
            }
            
            /* Khu vực chứa nội dung cuộn */
            QScrollArea#PropertiesScroll {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }

            /* Các thẻ (Card) thay thế cho QGroupBox */
            QFrame#PropertyCard {
                background-color: #1A1C24;
                border-radius: 8px;
                padding: 8px;
                border: none;
            }
            QLabel#CardTitle {
                color: #40E0D0;
                font-size: 12px;
                font-weight: bold;
                margin-bottom: 6px;
            }

            /* Nhãn chung */
            QLabel {
                color: #CCCCCC;
                font-size: 13px;
            }

            /* Ô nhập liệu và SpinBox phẳng */
            QLineEdit, QDoubleSpinBox {
                background-color: #252836;
                color: #FFFFFF;
                border: 1px solid #333340;
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
            }
            QLineEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #40E0D0;
            }

            /* Nút bấm Keyframe hình kim cương */
            QPushButton#KeyframeBtn {
                color: #555566;
                background: transparent;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton#KeyframeBtn:hover {
                color: #FFFFFF;
            }
            QPushButton#KeyframeBtn[active="true"] {
                color: #40E0D0;
            }

            /* Nút Fit/Fill Mode */
            QPushButton#FitFillBtn {
                background-color: #252836;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#FitFillBtn:hover {
                background-color: #3A3D4E;
                color: #FFFFFF;
            }
            QPushButton#FitFillBtn:checked {
                background-color: #2C7D73;
                color: #FFFFFF;
                border-color: #40E0D0;
            }

            /* Nut mo do thi duong cong o goc the Transform */
            QPushButton#GraphEntryBtn {
                background-color: transparent;
                color: #40E0D0;
                border: 1px solid #2C7D73;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
            }
            QPushButton#GraphEntryBtn:hover {
                background-color: rgba(64, 224, 208, 0.14);
                border-color: #40E0D0;
                color: #EAFFFB;
            }

            /* Nút Bỏ chuyển tiếp */
            QPushButton#TransitionClearBtn {
                background-color: #252836;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#TransitionClearBtn:hover {
                background-color: #3A3D4E;
                color: #FFFFFF;
            }
            QPushButton#TransitionClearBtn:disabled {
                color: #555566;
                background-color: #1A1C24;
            }

            /* Nút định dạng chữ Bold/Italic/Underline */
            QPushButton#TextFormatBtn {
                background-color: #252836;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton#TextFormatBtn:hover {
                background-color: #3A3D4E;
                color: #FFFFFF;
            }
            QPushButton#TextFormatBtn:checked {
                background-color: #2C7D73;
                color: #FFFFFF;
                border-color: #40E0D0;
            }

            /* Tùy biến Slider phẳng màu tím */
            QSlider::groove:horizontal {
                border-radius: 2px;
                height: 4px;
                background: #333340;
            }
            QSlider::sub-page:horizontal {
                background: #40E0D0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 1px solid #40E0D0;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
