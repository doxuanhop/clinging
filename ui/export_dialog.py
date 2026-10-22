"""
ui/export_dialog.py
Hộp thoại Xuất Video — giao diện modal với tùy chọn render và thanh tiến trình.
"""

import os
import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QWidget, QFrame, QDoubleSpinBox,
    QGraphicsDropShadowEffect, QApplication, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject, QSize, QUrl
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QBrush, QPen, QIcon

from core import external_tools
from core import export_range
from widgets.common import font_icon, set_label_icon, Toast, open_local_file


# ── Constants ──────────────────────────────────────────────────

ASPECT_OPTIONS = [
    ("16:9", "16:9 (Ngang)"),
    ("9:16", "9:16 (Doc)"),
    ("1:1",  "1:1 (Vuông)"),
    ("4:3",  "4:3 (TV)"),
]

RESOLUTION_MAP = {
    "16:9": [
        (854, 480,   "480p  ·  854 x 480"),
        (1280, 720,  "720p  ·  1280 x 720"),
        (1920, 1080, "1080p  ·  1920 x 1080"),
        (1024, 576,  "1K  ·  1024 x 576"),
        (2560, 1440, "2K  ·  2560 x 1440"),
        (3840, 2160, "4K  ·  3840 x 2160"),
    ],
    "9:16": [
        (480, 854,   "480p  ·  480 x 854"),
        (720, 1280,  "720p  ·  720 x 1280"),
        (1080, 1920, "1080p  ·  1080 x 1920"),
        (576, 1024,  "1K  ·  576 x 1024"),
        (1440, 2560, "2K  ·  1440 x 2560"),
        (2160, 3840, "4K  ·  2160 x 3840"),
    ],
    "1:1": [
        (480, 480, "480p  ·  480 x 480"), (720, 720, "720p  ·  720 x 720"),
        (1080, 1080, "1080p  ·  1080 x 1080"), (1024, 1024, "1K  ·  1024 x 1024"),
        (2048, 2048, "2K  ·  2048 x 2048"), (3840, 3840, "4K  ·  3840 x 3840"),
    ],
    "4:3": [
        (640, 480, "480p  ·  640 x 480"), (960, 720, "720p  ·  960 x 720"),
        (1440, 1080, "1080p  ·  1440 x 1080"), (1024, 768, "1K  ·  1024 x 768"),
        (2048, 1536, "2K  ·  2048 x 1536"), (3840, 2880, "4K  ·  3840 x 2880"),
    ],
}

FPS_OPTIONS = [
    (24, "24 (Điện ảnh)"),
    (25, "25 (PAL)"),
    (30, "30"),
    (60, "60 (Mượt hơn)"),
]


# ── Export Dialog ──────────────────────────────────────────────

class CircularProgress(QWidget):
    """Vòng tiến trình render kiểu CapCut, hiển thị % ở tâm."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self.setFixedSize(104, 104)

    def setValue(self, value):
        value = max(0, min(100, int(value)))
        if value != self._value:
            self._value = value
            self.update()

    def value(self):
        return self._value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(9, 9, -9, -9)
        painter.setPen(QPen(QColor("#303438"), 8, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(QColor("#40E0D0"), 8, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._value / 100))
        painter.setPen(QColor("#EAFFFB"))
        font = QFont("Segoe UI", 16, QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self._value}%")


class ExportDialog(QDialog):
    """
    Hộp thoại Xuất Video.
    Hiển thị modal, chặn tương tác với cửa sổ chính.
    """

    exportCancelled = Signal()
    exportFinished = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._rendering = False
        self._cancelled = False
        self._render_worker = None
        self._render_thread = None
        # Duong dan file vua xuat + co mo no ra chua. Chu tich nay quyet dinh
        # cua so chinh co hien lai toast "mo file" hay khong.
        self.exported_path = ""
        self.file_opened = False

        self.setWindowTitle("Xuất video")
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        self.setMinimumWidth(980)
        self.setMinimumHeight(min(520, max(420, screen_h - 120)))
        self.setMaximumHeight(max(520, int(screen_h * 0.88)))
        self.resize(1120, min(720, int(screen_h * 0.84)))
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #1A1C1F;
                border: 1px solid #34383D;
                border-radius: 14px;
                color: #D8DCE0;
            }
            QLabel { color: #E0E0E0; }
            QComboBox {
                background-color: #252636;
                border: 1px solid #3A3B50;
                border-radius: 6px;
                padding: 8px 12px;
                color: #E0E0E0;
                min-height: 20px;
            }
            QComboBox:hover { border-color: #40E0D0; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 30px;
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #A0A0A0;
                margin-right: 10px;
            }
            QComboBox QAbstractItemView {
                background-color: #252636;
                border: 1px solid #3A3B50;
                color: #E0E0E0;
                selection-background-color: #2C6E64;
                padding: 4px;
            }
            QDoubleSpinBox {
                background-color: #252636;
                border: 1px solid #3A3B50;
                border-radius: 6px;
                padding: 5px 8px;
                color: #E0E0E0;
                min-height: 20px;
            }
            QDoubleSpinBox:hover { border-color: #40E0D0; }
            QDoubleSpinBox:disabled { color: #5A5D6E; background-color: #1E1F2B; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background-color: #2E3040;
                border: none;
                width: 16px;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }
        """)

        self._build_ui()
        ratio_key = getattr(model, "project_ratio", "16:9") if model else "16:9"
        aspect_index = self.combo_aspect.findData(ratio_key)
        if aspect_index >= 0:
            self.combo_aspect.setCurrentIndex(aspect_index)
        # Combo độ phân giải tạo sau khi signal aspect ban đầu đã
        # phát, nên luôn populate tường minh để submenu không rỗng.
        self._update_resolution_options(ratio_key)
        # O in/out can do dai du an truoc lan ve dau tien; nean gia tri bang 0
        # se khiem khat "tu 0 den 0 s" ngay khi mo hop thoai.
        self._sync_range_spins()
        self._on_range_mode_changed()
        self._update_preview()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title Bar ──
        title_bar = self._build_title_bar()
        root.addWidget(title_bar)

        # ── Content ──
        content_host = QWidget()
        content = QHBoxLayout(content_host)
        content.setContentsMargins(24, 16, 24, 20)
        content.setSpacing(20)

        # Left: Settings
        progress_section = self._build_progress_section()
        progress_section.setMinimumWidth(285)
        progress_section.setMaximumWidth(320)
        content.addWidget(progress_section, 0)

        left_panel = self._build_settings_panel()
        content.addWidget(left_panel, 1)

        # Right: Preview
        right_panel = self._build_preview_panel()
        content.addWidget(right_panel, 1)

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # AlwaysOff o day tung an nut "Xuat rieng am thanh" hoan toan vo hinh:
        # cua so cao 520 px (minimumHeight cua man 768) chi con viewport 408 px
        # trong khi hai cot can 555 px, va grab() khong bao gio cuoc. AsNeeded
        # de nut "Chat luong" voi o in/out den duoc bang cuon o man thap.
        content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content_scroll.setWidget(content_host)
        self.content_scroll = content_scroll
        root.addWidget(content_scroll, 1)

        # Move the action row out of the progress card and anchor it to the
        # modal's bottom-right, matching the reference export workflow.
        progress_layout = progress_section.layout()
        action_item = progress_layout.takeAt(progress_layout.count() - 1)
        action_layout = action_item.layout() if action_item else None
        if action_layout is not None:
            action_host = QFrame()
            action_host.setFixedHeight(62)
            action_host.setStyleSheet(
                "QFrame { background: #16171F; border-top: 1px solid #2A2D3A; }"
            )
            action_layout.setContentsMargins(24, 12, 24, 12)
            action_host.setLayout(action_layout)
            root.addWidget(action_host)

        # ── Progress Section ──

    def _build_title_bar(self):
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet("""
            QFrame {
                background-color: #1A1B26;
                border-bottom: 1px solid #2A2D3A;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 16, 0)

        title = QLabel("Xuất video")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF; background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        btn_close = QPushButton()
        btn_close.setFixedSize(30, 30)
        btn_close.setIcon(font_icon("fa6s.xmark", "#C8CBD4"))
        btn_close.setIconSize(QSize(15, 15))
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #FF4D4D; }
        """)
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)

        return bar

    def _build_settings_panel(self):
        panel = QFrame()
        panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QLabel("CÀI ĐẶT XUẤT")
        header.setStyleSheet("font-size: 11px; font-weight: bold; color: #888; letter-spacing: 1px; background: transparent; border: none;")
        layout.addWidget(header)

        # Aspect ratio
        lbl_ar = QLabel("Tỉ lệ khung hình")
        lbl_ar.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        layout.addWidget(lbl_ar)

        self.combo_aspect = QComboBox()
        for key, label in ASPECT_OPTIONS:
            self.combo_aspect.addItem(label, key)
        self.combo_aspect.currentIndexChanged.connect(self._on_aspect_changed)
        layout.addWidget(self.combo_aspect)

        # Hint
        self.lbl_ar_hint = QLabel("")
        self.lbl_ar_hint.setStyleSheet("font-size: 11px; color: #888; background: transparent; border: none;")
        layout.addWidget(self.lbl_ar_hint)

        # Resolution
        lbl_res = QLabel("Độ phân giải")
        lbl_res.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        layout.addWidget(lbl_res)

        self.combo_resolution = QComboBox()
        self.combo_resolution.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_resolution)

        self.lbl_res_hint = QLabel("")
        self.lbl_res_hint.setStyleSheet("font-size: 11px; color: #888; background: transparent; border: none;")
        layout.addWidget(self.lbl_res_hint)

        # FPS
        lbl_fps = QLabel("FPS (Số khung hình/giây)")
        lbl_fps.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        layout.addWidget(lbl_fps)

        self.combo_fps = QComboBox()
        for val, label in FPS_OPTIONS:
            self.combo_fps.addItem(label, val)
        self.combo_fps.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_fps)

        fps_hint = QLabel("Cao hơn = mượt hơn, dung lượng lớn hơn")
        fps_hint.setStyleSheet("font-size: 11px; color: #888; background: transparent; border: none;")
        layout.addWidget(fps_hint)

        layout.addSpacing(8)

        # Export audio toggle
        audio_row = QHBoxLayout()
        audio_label_col = QVBoxLayout()
        audio_lbl = QLabel("Xuất riêng âm thanh")
        audio_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        audio_label_col.addWidget(audio_lbl)
        audio_sub = QLabel("Xuất file âm thanh MP3 riêng biệt")
        audio_sub.setStyleSheet("font-size: 11px; color: #888; background: transparent; border: none;")
        audio_label_col.addWidget(audio_sub)
        audio_row.addLayout(audio_label_col, 1)

        self.toggle_audio = QPushButton()
        self.toggle_audio.setFixedSize(44, 24)
        self.toggle_audio.setCheckable(True)
        self.toggle_audio.setChecked(False)
        self.toggle_audio.setStyleSheet("""
            QPushButton {
                background-color: #3A3B50;
                border: none;
                border-radius: 12px;
            }
            QPushButton:checked {
                background-color: #40E0D0;
            }
        """)
        self.toggle_audio.clicked.connect(self._update_preview)
        audio_row.addWidget(self.toggle_audio)

        layout.addLayout(audio_row)
        layout.addStretch()

        return panel

    def _build_preview_panel(self):
        panel = QFrame()
        panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QLabel("XEM TRƯỚC XUẤT")
        header.setStyleSheet("font-size: 11px; font-weight: bold; color: #888; letter-spacing: 1px; background: transparent; border: none;")
        layout.addWidget(header)

        # Preview canvas
        self.preview_frame = QFrame()
        self.preview_frame.setMinimumHeight(260)
        self.preview_frame.setStyleSheet("""
            QFrame {
                background-color: #0D0E14;
                border: 1px solid #2A2D3A;
                border-radius: 8px;
            }
        """)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setAlignment(Qt.AlignCenter)

        self.preview_label = QLabel("Không có nội dung")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("color: #555; font-size: 13px; background: transparent; border: none;")
        preview_layout.addWidget(self.preview_label)

        self.preview_pixmap_label = QLabel()
        self.preview_pixmap_label.setAlignment(Qt.AlignCenter)
        self.preview_pixmap_label.setStyleSheet("background: transparent; border: none;")
        preview_layout.addWidget(self.preview_pixmap_label)

        layout.addWidget(self.preview_frame, 1)

        # Info row
        info_frame = QFrame()
        info_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        info_layout = QHBoxLayout(info_frame)
        info_layout.setContentsMargins(4, 0, 4, 0)

        self.lbl_format = QLabel("Định dạng: MP4 (H.264)")
        self.lbl_format.setStyleSheet("font-size: 12px; color: #888; background: transparent; border: none;")
        info_layout.addWidget(self.lbl_format)

        info_layout.addStretch()

        self.lbl_duration = QLabel("Thời lượng: 00:00")
        self.lbl_duration.setStyleSheet("font-size: 12px; color: #888; background: transparent; border: none;")
        info_layout.addWidget(self.lbl_duration)

        layout.addWidget(info_frame)

        # ── Vung xuat (in/out) + chat luong ──
        # Dat o COT PHAI, khong phai cot cai dat: cot trai dang day dan va hop
        # thoai dung QScrollArea co hai thanh luon AlwaysOff, nen cong them 226
        # px vao cot trai lam "Xuat rieng am thanh" nam ngoai viewport hoan
        # toan vo hinh (do 22/10/2026: sizeHint 705 > viewport 580). Cot phai
        # con gia: preview_frame chi can 260 px nen them 122 px van duoi
        # sizeHint 479 px cua cot trai.
        lbl_range = QLabel("Vùng xuất")
        lbl_range.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        layout.addWidget(lbl_range)

        self.combo_range = QComboBox()
        self.combo_range.addItem("Toàn bộ dự án", export_range.RANGE_FULL)
        self.combo_range.addItem("Vùng chỉ định (từ → đến)", export_range.RANGE_WINDOW)
        self.combo_range.currentIndexChanged.connect(self._on_range_mode_changed)
        layout.addWidget(self.combo_range)

        self.range_row = QHBoxLayout()
        self.range_row.setSpacing(8)
        self.spin_from = QDoubleSpinBox()
        self.spin_to = QDoubleSpinBox()
        for spin, name in ((self.spin_from, "Từ"), (self.spin_to, "Đến")):
            caption = QLabel(name)
            caption.setStyleSheet("font-size: 12px; color: #888; background: transparent; border: none;")
            self.range_row.addWidget(caption)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setSuffix(" s")
            spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin.valueChanged.connect(self._update_preview)
            self.range_row.addWidget(spin)
        layout.addLayout(self.range_row)

        lbl_quality = QLabel("Chất lượng")
        lbl_quality.setStyleSheet("font-size: 13px; font-weight: bold; color: #E0E0E0; background: transparent; border: none;")
        layout.addWidget(lbl_quality)

        self.combo_quality = QComboBox()
        for key, label, _preset, _crf in export_range.QUALITY_PRESETS:
            self.combo_quality.addItem(label, key)
        self.combo_quality.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_quality)

        return panel

    def _build_progress_section(self):
        section = QFrame()
        section.setStyleSheet("""
            QFrame {
                background-color: #16171F;
                border: 1px solid #2A2D3A;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Header row
        header_row = QHBoxLayout()
        lbl_prog = QLabel("TIẾN TRÌNH XUẤT")
        lbl_prog.setStyleSheet("font-size: 11px; font-weight: bold; color: #888; letter-spacing: 1px; background: transparent; border: none;")
        header_row.addWidget(lbl_prog)
        header_row.addStretch()

        self.lbl_time_elapsed = QLabel("00:00:00 / 00:00:00")
        self.lbl_time_elapsed.setStyleSheet("font-size: 12px; color: #888; background: transparent; border: none;")
        header_row.addWidget(self.lbl_time_elapsed)
        layout.addLayout(header_row)

        # Status text
        self.lbl_status = QLabel("Sẵn sàng xuất video")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #A0A0A0; background: transparent; border: none;")

        progress_body = QHBoxLayout()
        progress_body.setSpacing(22)
        self.progress_bar = CircularProgress()
        progress_body.addWidget(self.progress_bar, 0, Qt.AlignLeft | Qt.AlignVCenter)

        progress_details = QVBoxLayout()
        progress_details.setSpacing(8)
        progress_details.addWidget(self.lbl_status)

        # Giữ alias để code lifecycle cũ tương thích; % đã hiện
        # ngay chính giữa vòng tròn.
        self.lbl_percent = QLabel("0%")
        self.lbl_percent.hide()

        # Steps list
        self.steps_container = QVBoxLayout()
        self.steps_container.setSpacing(6)
        self.steps_container.setContentsMargins(0, 4, 0, 4)
        self._step_labels = []
        steps = [
            "Khởi tạo xuất video...",
            "Đang xử lý video...",
            "Đang xử lý âm thanh...",
            "Đang ghép file...",
            "Hoàn tất",
        ]
        for i, text in enumerate(steps):
            row = QHBoxLayout()
            row.setSpacing(8)

            dot = QLabel()
            dot.setFixedSize(14, 14)
            dot.setStyleSheet("background: transparent; border: none;")
            set_label_icon(dot, "fa6s.circle", 8, "#444444")
            row.addWidget(dot)

            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 12px; color: #555; background: transparent; border: none;")
            row.addWidget(lbl)
            row.addStretch()

            self.steps_container.addLayout(row)
            self._step_labels.append((dot, lbl))

        progress_details.addLayout(self.steps_container)
        progress_body.addLayout(progress_details, 1)
        layout.addLayout(progress_body)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Hủy xuất")
        self.btn_cancel.setFixedSize(120, 36)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #252636;
                color: #E0E0E0;
                border: 1px solid #3A3B50;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #303234; border-color: #40E0D0; }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("Xuất video")
        self.btn_export.setFixedSize(130, 36)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #2C6E64;
                color: #EAFFFB;
                border: 1px solid #40E0D0;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #348175; }
            QPushButton:disabled { background-color: #3A3B50; color: #666; }
        """)
        self.btn_export.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self.btn_export)

        layout.addLayout(btn_row)

        return section

    # ── Logic ──────────────────────────────────────────────────

    def _on_aspect_changed(self, index):
        ratio_key = self.combo_aspect.currentData()
        hint_map = {
            "16:9": "Khuyên nghị cho YouTube, video truyền thống",
            "9:16": "Khuyên nghị cho mạng xã hội (TikTok, Reels, Shorts)",
            "1:1":  "Phù hợp cho Instagram, Facebook",
            "4:3":  "Tỉ lệ cổ điển",
        }
        self.lbl_ar_hint.setText(hint_map.get(ratio_key, ""))
        self._update_resolution_options(ratio_key)
        self._update_preview()

    def _update_resolution_options(self, ratio_key):
        self.combo_resolution.blockSignals(True)
        self.combo_resolution.clear()
        res_list = RESOLUTION_MAP.get(ratio_key, RESOLUTION_MAP["16:9"])
        for w, h, label in res_list:
            self.combo_resolution.addItem(label, (w, h))
        if res_list:
            self.combo_resolution.setCurrentIndex(0)
        self.combo_resolution.blockSignals(False)

        if ratio_key == "9:16":
            self.lbl_res_hint.setText("Khuyên nghị cho mạng xã hội (TikTok, Reels, Shorts)")
        else:
            self.lbl_res_hint.setText("")

    def select_resolution_preset(self, preset: str):
        """Chọn preset từ submenu nút Xuất video."""
        key = preset.lower()
        for index in range(self.combo_resolution.count()):
            if self.combo_resolution.itemText(index).lower().startswith(key):
                self.combo_resolution.setCurrentIndex(index)
                return True
        return False

    def _project_duration(self):
        return float(self.model.duration) if self.model is not None else 0.0

    def _current_fps(self):
        return int(self.combo_fps.currentData() or 30)

    def _range_mode(self):
        return self.combo_range.currentData() or export_range.RANGE_FULL

    def _sync_range_spins(self):
        """Nean hai o in/out theo do dai du an THAT, khong phai theo do dai
        cua lan mo hop thoai truoc do (dung model co the doi sau undo)."""
        duration = self._project_duration()
        for spin, target in ((self.spin_from, 0.0), (self.spin_to, duration)):
            spin.blockSignals(True)
            spin.setMaximum(duration)
            spin.setValue(target)
            spin.blockSignals(False)

    def _current_window(self):
        """Cua so RenderWorker se dung. Goi thang vao export_range.resolve_window
        nhu worker — khong co ban phuc bac thu hai o day."""
        duration = self._project_duration()
        if self._range_mode() == export_range.RANGE_WINDOW:
            return export_range.resolve_window(
                self.spin_from.value(), self.spin_to.value(), duration,
                self._current_fps())
        return export_range.resolve_window(0.0, duration, duration,
                                           self._current_fps())

    def _on_range_mode_changed(self):
        windowed = self._range_mode() == export_range.RANGE_WINDOW
        self.spin_from.setEnabled(windowed)
        self.spin_to.setEnabled(windowed)
        self._update_preview()

    def _update_preview(self):
        ratio_key = self.combo_aspect.currentData() or "16:9"
        res_data = self.combo_resolution.currentData()
        if res_data:
            w, h = res_data
        else:
            w, h = 1920, 1080

        fps = self._current_fps()
        duration = self._project_duration()
        has_audio = self.toggle_audio.isChecked()

        window = self._current_window()
        row = export_range.preset_of(self.combo_quality.currentData())
        shown = window["span"] if window.get("ok") else 0.0
        # Vung duoi mot giay la HOP LE (toi thieu 2 frame), nen do dai cua no
        # phai in ra CON SO. `mm:ss` cua toan bo bai video lam vung 0,6 s in
        # thanh "00:00" ngay canh nut Xuat — do lan chay 22/10/2026 khi do bang
        # cua so 1,2 s (no in "00:01", mat mat 0,2 s).
        if window.get("mode") == export_range.RANGE_WINDOW and window.get("ok"):
            do_dai = "%.2f s, %d frame" % (shown, window["frames"])
        else:
            do_dai = self._fmt_time(shown)
        self.lbl_duration.setText(
            "Thời lượng: %s / %s" % (do_dai, self._fmt_time(duration)))
        # preset/CRF in ra la dung chuoi ffmpeg di vao lenh, khong phai mot
        # nhan marketing. Khi vung in/out sai, loi nguoi dung doc duoc dat
        # canh con so 00:00 de khong co "xuat duoc 0 giay" im lang.
        self.lbl_format.setText(
            "Định dạng: MP4 · x264 %s · CRF %d%s"
            % (row[2], row[3],
               "" if window.get("ok") else " · " + window["error"]))

        # Draw preview
        max_preview_h = 240
        max_preview_w = 300
        scale = min(max_preview_w / max(w, 1), max_preview_h / max(h, 1))
        pw = max(int(w * scale), 1)
        ph = max(int(h * scale), 1)

        pixmap = QPixmap(pw, ph)
        pixmap.fill(QColor("#0D0E14"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Border
        painter.setPen(QPen(QColor("#40E0D0"), 2))
        painter.setBrush(QBrush(QColor("#1A1B26")))
        painter.drawRoundedRect(1, 1, pw - 2, ph - 2, 4, 4)

        # Resolution text
        painter.setPen(QColor("#555"))
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, f"{w}x{h}")

        painter.end()

        self.preview_pixmap_label.setPixmap(pixmap)
        self.preview_label.hide()

    def _on_export_clicked(self):
        if self._rendering:
            return

        res_data = self.combo_resolution.currentData()
        if not res_data:
            return

        w, h = res_data
        fps = self._current_fps()
        ratio_key = self.combo_aspect.currentData() or "16:9"
        export_audio = self.toggle_audio.isChecked()
        quality = self.combo_quality.currentData()

        window = self._current_window()
        if not window.get("ok"):
            # Bao loi TRUOC khi mo hop thoai chon cho luu: nguoi dung dung
            # 15 giay de tim thu muc roi moi biet range sai thi toi te.
            self.lbl_status.setText("Lỗi: " + window["error"])
            return

        # Ask output path
        default_name = "export.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "Chọn nơi lưu video", default_name,
            "Video (*.mp4);;Tất cả (*)"
        )
        if not path:
            return

        if not path.lower().endswith(".mp4"):
            path += ".mp4"

        self._start_render(path, w, h, fps, ratio_key, export_audio,
                           window=window, quality=quality)

    def _start_render(self, output_path, width, height, fps, ratio_key,
                      export_audio, window=None, quality=None):
        self._rendering = True
        self._cancelled = False
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.lbl_percent.setText("0%")
        self.lbl_status.setText("Đang chuẩn bị xuất video...")
        self.lbl_time_elapsed.setText("00:00:00 / 00:00:00")
        self._reset_steps()

        # Start render worker
        self._render_thread = QThread()
        self._render_worker = RenderWorker(
            self.model, output_path, width, height, fps, ratio_key, export_audio,
            window=window, quality=quality
        )
        self._render_worker.moveToThread(self._render_thread)

        self._render_worker.progressChanged.connect(self._on_progress)
        self._render_worker.statusChanged.connect(self._on_status)
        self._render_worker.stepChanged.connect(self._on_step)
        self._render_worker.timeUpdate.connect(self._on_time_update)
        self._render_worker.finished_ok.connect(self._on_render_done)
        self._render_worker.errorOccurred.connect(self._on_render_error)
        self._render_worker.cancelled.connect(self._on_render_cancelled)

        self._render_thread.started.connect(self._render_worker.run)
        self._render_worker.finished_ok.connect(self._render_thread.quit)
        self._render_worker.errorOccurred.connect(self._render_thread.quit)
        self._render_worker.cancelled.connect(self._render_thread.quit)
        self._render_worker.finished_ok.connect(self._render_worker.deleteLater)
        self._render_worker.errorOccurred.connect(self._render_worker.deleteLater)
        self._render_worker.cancelled.connect(self._render_worker.deleteLater)
        self._render_thread.finished.connect(self._render_thread.deleteLater)

        self._render_thread.start()

    def _on_progress(self, value):
        self.progress_bar.setValue(value)
        self.lbl_percent.setText(f"{value}%")

    def _on_status(self, text):
        self.lbl_status.setText(text)

    def _on_step(self, step_index):
        for i, (dot, lbl) in enumerate(self._step_labels):
            if i < step_index:
                set_label_icon(dot, "fa6s.circle", 8, "#4CAF50")
                lbl.setStyleSheet("font-size: 12px; color: #4CAF50; background: transparent; border: none;")
            elif i == step_index:
                set_label_icon(dot, "fa6s.circle", 8, "#40E0D0")
                lbl.setStyleSheet("font-size: 12px; color: #E0E0E0; background: transparent; border: none;")
            else:
                set_label_icon(dot, "fa6s.circle", 8, "#444444")
                lbl.setStyleSheet("font-size: 12px; color: #555; background: transparent; border: none;")

    def _on_time_update(self, elapsed, total):
        self.lbl_time_elapsed.setText(f"{elapsed} / {total}")

    def _on_render_done(self, output_path):
        self._rendering = False
        self._on_step(4)
        self.progress_bar.setValue(100)
        self.lbl_percent.setText("100%")
        self.lbl_status.setText(f"Xuất thành công: {os.path.basename(output_path)}")
        self.btn_export.setText("Xuất lại")
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        self.exported_path = output_path
        self.file_opened = False
        # Toast dat TREN hop thoai nay vi no modal: toast cua cua so chinh
        # luc nay hien duoc nhung khong bam duoc. dark=True: hop thoai xuat
        # luon toi theo stylesheet cung co, bat ke chu de sang cua app.
        # y_shift=-56: thanh nut 50px duoi day co nut "Xuất lại" o dung goc
        # duoi-phai, de toast moc len thi nguoi dung mat luon nut chinh.
        Toast.popup(self, "Xuất video xong", os.path.basename(output_path),
                    icon_name="fa6s.circle-check", action_label="Mở file",
                    action=self._open_exported_file, dark=True, y_shift=-56)
        self.exportFinished.emit(output_path)

    def _open_exported_file(self):
        """Mo file vua bang dung ung dung mac dinh cua he dieu hanh."""
        self.file_opened = open_local_file(self.exported_path)
        if not self.file_opened:
            self.lbl_status.setText("Không mở được file (file đã bị xoá?)")

    def _on_render_error(self, error_msg):
        self._rendering = False
        self.lbl_status.setText(f"Lỗi: {error_msg}")
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _on_render_cancelled(self):
        self._rendering = False
        self._render_worker = None
        self.lbl_status.setText("Đã hủy xuất video")
        self.exportCancelled.emit()
        super().reject()

    def _on_cancel(self):
        if not self._rendering:
            super().reject()
        elif self._render_worker:
            self._cancelled = True
            self._render_worker.request_cancel()
            self.lbl_status.setText("Đang hủy...")
            self.btn_cancel.setEnabled(False)

    def reject(self):
        if self._rendering:
            self._on_cancel()
            return
        super().reject()

    def _reset_steps(self):
        for i, (dot, lbl) in enumerate(self._step_labels):
            set_label_icon(dot, "fa6s.circle", 8, "#444444")
            lbl.setStyleSheet("font-size: 12px; color: #555; background: transparent; border: none;")

    @staticmethod
    def _fmt_time(seconds):
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m:02d}:{s:02d}"


# ── Render Worker ──────────────────────────────────────────────

class RenderWorker(QObject):
    """
    Worker chạy ngầm trong QThread.
    Dựng từng frame timeline bằng FrameComposer (giống hệt Canvas preview)
    rồi PIPE rawvideo thẳng vào ffmpeg để encode + mux — không ghi PNG.
    """

    progressChanged = Signal(int)
    statusChanged = Signal(str)
    stepChanged = Signal(int)
    timeUpdate = Signal(str, str)
    finished_ok = Signal(str)
    errorOccurred = Signal(str)
    cancelled = Signal()

    def __init__(self, model, output_path, width, height, fps, ratio_key,
                 export_audio, window=None, quality=None):
        super().__init__()
        self.model = model
        self.output_path = output_path
        self.width = width
        self.height = height
        self.fps = fps
        self.ratio_key = ratio_key
        self.export_audio = export_audio
        # `window`/`quality` de trong = hanh vi cu: ca du an, CRF 18 medium.
        self.window = window
        self.quality = quality
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        import subprocess
        import tempfile
        import shutil

        try:
            # Step 0: Init
            self.stepChanged.emit(0)
            self.statusChanged.emit("Khởi tạo xuất video...")
            self.progressChanged.emit(0)

            duration = self.model.duration
            if duration <= 0:
                self.errorOccurred.emit("Thời lượng dự án bằng 0")
                return

            window = self.window or export_range.resolve_window(
                0.0, duration, duration, self.fps)
            if not window.get("ok"):
                self.errorOccurred.emit(window["error"])
                return
            total_frames = window["frames"]
            start = window["start"]
            tmp_dir = tempfile.mkdtemp(prefix="clinqing_render_")

            # Check ffmpeg — ban di kem trong _internal/tools thang, PATH chi la
            # nguong du phong. Goi ten tran se bao "thêm vào PATH" cho mot lan
            # cai dang le khong yeu cau nguoi dung lam gi ca.
            ffmpeg = external_tools.find("ffmpeg")
            if not ffmpeg:
                self.errorOccurred.emit(external_tools.missing_message("ffmpeg"))
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return

            # ── Step 2: Xử lý âm thanh TRƯỚC (là input file cho ffmpeg pipe) ──
            self.stepChanged.emit(2)
            self.statusChanged.emit("Đang xử lý âm thanh...")
            self.progressChanged.emit(3)

            from core import audio_mix

            audio_clips = audio_mix.collect_audio_clips(self.model, {})
            audio_file = None
            if audio_clips:
                # Decode every source onto a fresh, continuous PCM timeline.
                # AAC sources can contain skipped/corrupt samples; rebuilding
                # PTS before mixing prevents them from reaching the final AAC
                # encoder as non-monotonic timestamps. afade cho vùng chuyển
                # tiếp được gắn trong chính chuỗi filter này (core/audio_mix).
                #
                # Audio van duoc dung cho CA DU AN roi moi cat cua so bang -ss
                #/-t o input: fade in/out va transition tinh theo truc thoi
                # gian tuyet doi cua timeline, nen doan 2,0->4,0 cua ban xuat
                # vung PHAI la dung doan do cua ban xuat toan bo. Cat ngay
                # trong render_audio la mot duong thong ke thu hai, va hai
                # duong thong ke tung tra so khac nhau o day (bai hoc the Cat).
                audio_file = os.path.join(tmp_dir, "audio.wav")
                audio_mix.render_audio(
                    self.model, audio_clips, duration, audio_file)

            # ── Step 1: Render + encode video qua PIPE rawvideo -> ffmpeg ──
            self.stepChanged.emit(1)
            self.statusChanged.emit("Đang xử lý video...")
            self.progressChanged.emit(15)

            from core.frame_composer import FrameComposer
            composer = FrameComposer(self.model, self.width, self.height)

            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW

            cmd = [
                ffmpeg, "-y", "-loglevel", "error",
                "-f", "rawvideo",
                "-pixel_format", "rgba",
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", str(self.fps),
                "-i", "-",
            ]
            if audio_file and os.path.exists(audio_file):
                cmd.extend(export_range.audio_input_args(window))
                cmd.extend(["-i", audio_file])
            cmd.extend(export_range.encode_args(self.quality))
            if audio_file and os.path.exists(audio_file):
                cmd.extend([
                    "-af", "aresample=48000:async=1:first_pts=0",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                ])
            else:
                cmd.extend(["-an"])
            # `-t` cua ung dung thay cho `-shortest`: do dai file ra la con so
            # do chinh export quyet (frames/fps), khong phai "cai nao ngan hon
            # thi cat cai kia". Cũ: model 1,9 s ra file 1,6 s vi doan cuoi
            # khong co tieng — clip chu bien mat lang lang.
            cmd.extend(export_range.output_args(window))
            cmd.append(self.output_path)

            # stderr -> file: tránh deadlock khi buffer pipe stderr đầy lúc render dài.
            err_path = os.path.join(tmp_dir, "ffmpeg_stderr.log")
            err_file = open(err_path, "wb")
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=err_file, startupinfo=startupinfo,
                creationflags=creationflags,
            )

            try:
                for frame_idx in range(total_frames):
                    if self._cancel_requested:
                        try:
                            if proc.stdin:
                                proc.stdin.close()
                        except OSError:
                            pass
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        composer.close()
                        err_file.close()
                        self.statusChanged.emit("Đã hủy xuất video")
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        self.cancelled.emit()
                        return

                    current_time = export_range.frame_time(
                        start, frame_idx, self.fps)
                    frame_bytes = composer.render_frame_bytes(current_time)
                    try:
                        proc.stdin.write(frame_bytes)
                    except (BrokenPipeError, OSError):
                        # ffmpeg đã thoát (thường do lỗi) -> dừng, đọc log bên dưới.
                        break

                    progress = 15 + int((frame_idx + 1) / total_frames * 80)
                    self.progressChanged.emit(progress)
                    self.statusChanged.emit(f"Đang xử lý video ({progress}%)...")
                    # Dong ho tien te tinh TU CUA SO, khong tinh theo truc
                    # timeline: xuat doan 2,0->4,0 phai chay 00:00 -> 00:02
                    # thi nguoi dung moi doc duoc "con bao lau".
                    self.timeUpdate.emit(
                        self._fmt(current_time - start),
                        self._fmt(window["span"]),
                    )
            finally:
                composer.close()
                if proc.stdin and not proc.stdin.closed:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            # ── Step 3: Ghép file (ffmpeg tự kết thúc khi đọc hết pipe) ──
            self.stepChanged.emit(3)
            self.statusChanged.emit("Đang ghép file...")
            self.progressChanged.emit(97)

            returncode = proc.wait()
            err_file.close()
            if returncode != 0:
                try:
                    with open(err_path, "rb") as f:
                        error_text = f.read().decode("utf-8", errors="replace")[-500:]
                except OSError:
                    error_text = "(không đọc được log)"
                self.errorOccurred.emit(f"FFmpeg lỗi: {error_text}")
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return

            self.progressChanged.emit(100)

            # Step 4: Done
            self.stepChanged.emit(4)
            self.statusChanged.emit("Hoàn tất")

            # Export separate audio if requested
            if self.export_audio and audio_clips:
                mp3_path = self.output_path.rsplit(".", 1)[0] + "_audio.mp3"
                cmd_audio = [
                    ffmpeg, "-y", "-loglevel", "error",
                ]
                if audio_file and os.path.exists(audio_file):
                    cmd_audio.extend(export_range.audio_input_args(window))
                    cmd_audio.extend(["-i", audio_file])
                    cmd_audio.extend([
                        "-vn", "-af", "aresample=48000:async=1:first_pts=0",
                        "-c:a", "libmp3lame", "-b:a", "192k",
                    ])
                    cmd_audio.extend(export_range.output_args(window))
                else:
                    cmd_audio.extend(["-vn"])
                cmd_audio.append(mp3_path)
                subprocess.run(cmd_audio, capture_output=True, timeout=300)

            shutil.rmtree(tmp_dir, ignore_errors=True)
            self.finished_ok.emit(self.output_path)

        except Exception as e:
            self.errorOccurred.emit(str(e))

    @staticmethod
    def _fmt(seconds):
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
