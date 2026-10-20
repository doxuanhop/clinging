"""Custom cover picker for a Main Storyline video clip."""

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from core.media_frame import extract_frame
from ui.custom_dialog import CustomDialog
from widgets.common import font_icon


class CoverDialog(QDialog):
    def __init__(self, clip, output_path, initial_source_time=0.0, parent=None):
        super().__init__(parent)
        self.clip = clip
        self.output_path = str(output_path)
        self.source_start = max(0.0, float(clip.in_point))
        self.source_duration = max(0.1, float(clip.duration))
        self.selected_source_time = min(self.source_start + self.source_duration,
            max(self.source_start, float(initial_source_time)))
        self.cover_path = ""
        self.setWindowTitle("Tạo ảnh bìa")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumWidth(760)
        self.setMaximumWidth(900)
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.82))
        self.setStyleSheet(self._style())
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._update_preview)
        self._build_ui()
        self._build_thumbnails()
        self._update_preview()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        title = QFrame(); title.setObjectName("CoverTitleBar"); title.setFixedHeight(48)
        row = QHBoxLayout(title); row.setContentsMargins(20, 0, 12, 0)
        heading = QLabel("Tạo ảnh bìa"); heading.setObjectName("CoverHeading")
        close = QPushButton(); close.setObjectName("CoverClose")
        close.setIcon(font_icon("fa6s.xmark", "#9CA3AF"))
        close.setIconSize(QSize(13, 13)); close.setFixedSize(28, 28)
        close.clicked.connect(self.reject)
        row.addWidget(heading); row.addStretch(); row.addWidget(close); root.addWidget(title)
        scroll = QScrollArea(); scroll.setObjectName("CoverScroll"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(); layout = QVBoxLayout(body); layout.setContentsMargins(24, 20, 24, 14); layout.setSpacing(14)
        hint = QLabel("Chọn khoảnh khắc đẹp từ video gốc"); hint.setObjectName("CoverHint"); layout.addWidget(hint)
        self.preview = QLabel("Đang đọc khung hình…"); self.preview.setObjectName("CoverPreview")
        self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(640, 340)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)
        time_row = QHBoxLayout(); self.time_label = QLabel("00:00.000"); self.time_label.setObjectName("CoverTime")
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, max(1, int(self.source_duration * 1000)))
        self.slider.setValue(int((self.selected_source_time - self.source_start) * 1000))
        self.slider.valueChanged.connect(self._on_slider_changed)
        time_row.addWidget(self.time_label); time_row.addWidget(self.slider, 1); layout.addLayout(time_row)
        strip_scroll = QScrollArea(); strip_scroll.setObjectName("CoverStripScroll"); strip_scroll.setFixedHeight(82)
        strip_scroll.setFrameShape(QFrame.NoFrame); strip_scroll.setWidgetResizable(True)
        strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        strip = QWidget(); self.strip_layout = QHBoxLayout(strip); self.strip_layout.setContentsMargins(0, 2, 0, 2); self.strip_layout.setSpacing(7)
        strip_scroll.setWidget(strip); layout.addWidget(strip_scroll); scroll.setWidget(body); root.addWidget(scroll, 1)
        footer = QFrame(); footer.setObjectName("CoverFooter"); buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 12, 24, 16); buttons.addStretch()
        cancel = QPushButton("Hủy"); cancel.setObjectName("CoverSecondary"); cancel.clicked.connect(self.reject)
        create = QPushButton("Tạo ảnh bìa"); create.setObjectName("CoverPrimary"); create.clicked.connect(self._create_cover)
        buttons.addWidget(cancel); buttons.addWidget(create); root.addWidget(footer)

    def _build_thumbnails(self):
        for index in range(7):
            relative = self.source_duration * index / 6
            pixmap = extract_frame(self.clip.source_path, self.source_start + relative, QSize(104, 62))
            button = QPushButton(); button.setObjectName("CoverThumb"); button.setFixedSize(104, 64)
            if not pixmap.isNull():
                button.setIcon(QIcon(pixmap)); button.setIconSize(QSize(100, 58))
            button.clicked.connect(lambda _checked=False, t=relative: self.slider.setValue(int(t * 1000)))
            self.strip_layout.addWidget(button)
        self.strip_layout.addStretch()

    def _on_slider_changed(self, value):
        self.selected_source_time = self.source_start + value / 1000.0
        minutes, seconds = divmod(self.selected_source_time, 60.0)
        self.time_label.setText(f"{int(minutes):02d}:{seconds:06.3f}")
        self._preview_timer.start()

    def _update_preview(self):
        pixmap = extract_frame(self.clip.source_path, self.selected_source_time, QSize(700, 390))
        if pixmap.isNull():
            self.preview.setPixmap(QPixmap()); self.preview.setText("Không thể đọc hình ảnh tại thời điểm này")
        else:
            self.preview.setText(""); self.preview.setPixmap(pixmap)

    def _create_cover(self):
        pixmap = extract_frame(self.clip.source_path, self.selected_source_time)
        if pixmap.isNull():
            CustomDialog.warning(self, "Không thể tạo ảnh bìa", "Không đọc được khung hình đã chọn. Hãy chọn một thời điểm khác.")
            return
        output = Path(self.output_path); output.parent.mkdir(parents=True, exist_ok=True)
        if not pixmap.save(str(output), "PNG"):
            CustomDialog.warning(self, "Không thể tạo ảnh bìa", "Không thể lưu ảnh bìa vào thư mục dự án.")
            return
        self.cover_path = str(output); self.accept()

    @staticmethod
    def _style():
        return """
        QDialog { background:#1A1C1F; border:1px solid #34383D; border-radius:14px; color:#E5E7EB; }
        #CoverTitleBar,#CoverFooter { background:#1A1C1F; border-bottom:1px solid #2A2E34; }
        #CoverHeading { color:white; font-size:15px; font-weight:700; }
        #CoverClose { background:transparent; border:none; border-radius:6px; }
        #CoverClose:hover { background:#E81123; }
        #CoverScroll,#CoverStripScroll { background:transparent; border:none; }
        #CoverHint { color:#D8DCE0; font-size:13px; font-weight:600; }
        #CoverPreview { background:#08090C; border:1px solid #34383D; border-radius:10px; color:#818791; }
        #CoverTime { color:#40E0D0; font-family:Consolas; min-width:72px; }
        #CoverThumb { background:#111318; border:1px solid #34383D; border-radius:7px; padding:1px; }
        #CoverThumb:hover,#CoverThumb:focus { border:2px solid #40E0D0; }
        #CoverPrimary { background:#2C6E64; color:#EAFFFB; border:1px solid #40E0D0; border-radius:8px; padding:8px 22px; font-weight:700; }
        #CoverPrimary:hover { background:#348175; }
        #CoverSecondary { background:#252729; color:#D8DCE0; border:1px solid #3A3A3A; border-radius:8px; padding:8px 22px; }
        #CoverSecondary:hover { border-color:#40E0D0; }
        QSlider::groove:horizontal { height:4px; background:#34383D; border-radius:2px; }
        QSlider::sub-page:horizontal { background:#2C6E64; border-radius:2px; }
        QSlider::handle:horizontal { width:14px; margin:-5px 0; background:#40E0D0; border-radius:7px; }
        """
