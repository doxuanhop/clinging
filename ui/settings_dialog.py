"""
ui/settings_dialog.py
Hộp thoại Cài đặt — mở từ nút Settings trên Trang chủ.

Mỗi control ở đây tương ứng một khóa trong core.settings.DEFAULTS và một chỗ
thật trong app đọc khóa đó. Thêm control không có hook chỉ tạo ra một nút nói
dối, nên các control trang trí của bản dựng mẫu đã bị bỏ hẳn.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QWidget, QTabWidget, QComboBox, QLineEdit, QScrollArea,
    QFileDialog, QCheckBox, QApplication
)

from core import settings
from theme import theme_manager
from widgets.common import _qta


# ── Reusable widgets ──────────────────────────────────────────

_COMBO_STYLE = """
    QComboBox {
        background-color: #1A1B22;
        border: 1px solid #2A2C38;
        border-radius: 6px;
        padding: 5px 10px;
        color: #E0E0E0;
        font-size: 12px;
        min-width: 80px;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid #6E7180;
        margin-right: 8px;
    }
    QComboBox QAbstractItemView {
        background-color: #1A1B22;
        color: #E0E0E0;
        border: 1px solid #2A2C38;
        selection-background-color: #8B5CF6;
    }
"""

_TOGGLE_ON = ("QPushButton { background-color: #8B5CF6; border: none;"
              " border-radius: 12px; }")
_TOGGLE_OFF = ("QPushButton { background-color: #3A3B50; border: none;"
               " border-radius: 12px; }")


def _make_combo(items, current=None, width=None):
    c = QComboBox()
    c.addItems(items)
    if current:
        # Một giá trị tay sửa trong settings.json có thể ngoài danh sách chọn.
        # Nếu chỉ setCurrentText thì combo âm thầm hiện item đầu và người dùng
        # lưu lùi về giá trị khác cái app đang thật sự chạy.
        if current not in [c.itemText(i) for i in range(c.count())]:
            try:
                position = len([item for item in items if float(item) < float(current)])
            except ValueError:
                position = c.count()
            c.insertItem(position, current)
        c.setCurrentText(current)
    c.setStyleSheet(_COMBO_STYLE)
    if width:
        c.setFixedWidth(width)
    return c


def _style_toggle(btn):
    btn.setStyleSheet(_TOGGLE_ON if btn.isChecked() else _TOGGLE_OFF)


def _make_toggle(checked=False):
    btn = QPushButton()
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setFixedSize(44, 24)
    btn.setCursor(Qt.PointingHandCursor)
    _style_toggle(btn)
    btn.clicked.connect(lambda: _style_toggle(btn))
    return btn


def _make_checkbox(text, checked=True):
    cb = QCheckBox(text)
    cb.setChecked(checked)
    cb.setStyleSheet("QCheckBox { color: #E0E0E0; font-size: 12px; spacing: 8px; }"
                     "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #3A3B50; background: #1A1B22; }"
                     "QCheckBox::indicator:checked { background-color: #8B5CF6; border-color: #8B5CF6; }")
    return cb


def _section_card(title):
    card = QFrame()
    card.setStyleSheet("QFrame { background-color: #14151D; border: 1px solid #1E1F2E; border-radius: 10px; }")
    vl = QVBoxLayout(card)
    vl.setContentsMargins(20, 16, 20, 16)
    vl.setSpacing(10)
    lbl = QLabel(title)
    lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #E0E0E0;")
    vl.addWidget(lbl)
    return card, vl


def _setting_row(label, desc, widget):
    row = QHBoxLayout()
    row.setSpacing(16)
    text = QVBoxLayout()
    text.setSpacing(2)
    lbl = QLabel(label)
    lbl.setStyleSheet("font-size: 12px; font-weight: 500; color: #E0E0E0;")
    text.addWidget(lbl)
    if desc:
        d = QLabel(desc)
        d.setStyleSheet("font-size: 11px; color: #6E7180;")
        d.setWordWrap(True)
        text.addWidget(d)
    row.addLayout(text, 1)
    row.addWidget(widget)
    return row


def _dir_row(label, desc, path_value):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    edit = QLineEdit(path_value)
    edit.setReadOnly(True)
    edit.setStyleSheet("""
        QLineEdit {
            background-color: #1A1B22;
            border: 1px solid #2A2C38;
            border-radius: 6px;
            padding: 5px 10px;
            color: #E0E0E0;
            font-size: 12px;
        }
    """)
    layout.addWidget(edit, 1)
    browse = QPushButton()
    browse.setIcon(_qta().icon("fa6s.folder-open", color="#8B5CF6"))
    browse.setFixedSize(30, 30)
    browse.setCursor(Qt.PointingHandCursor)
    browse.setStyleSheet("QPushButton { background: transparent; border: 1px solid #2A2C38; border-radius: 6px; }"
                         "QPushButton:hover { background-color: #1A1B22; border-color: #8B5CF6; }")
    layout.addWidget(browse)
    return _setting_row(label, desc, widget), edit, browse


def _scroll_body(tab_layout):
    """Gắn một QScrollArea vào tab, trả về layout chứa nội dung bên trong."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    content = QWidget()
    content.setStyleSheet("background: transparent;")
    body = QVBoxLayout(content)
    body.setContentsMargins(32, 20, 32, 20)
    body.setSpacing(16)
    scroll.setWidget(content)
    tab_layout.addWidget(scroll)
    return body


_THEME_LABELS = {"dark": "Tối", "light": "Sáng"}
_THEME_KEYS = {label: key for key, label in _THEME_LABELS.items()}


# ── Tab: Chung ────────────────────────────────────────────────

class _GeneralTab(QWidget):
    KEYS = ("theme", "project_dir", "default_fps",
            "auto_save", "auto_save_interval")

    def __init__(self, values):
        super().__init__()
        self.dir_edits = {}
        self.dir_browse = {}
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        body = _scroll_body(tab_layout)

        card, cvl = _section_card("Giao diện")
        self.theme_combo = _make_combo(
            [_THEME_LABELS[k] for k in settings.CHOICES["theme"]],
            _THEME_LABELS.get(values["theme"], "Tối"), 120)
        cvl.addLayout(_setting_row(
            "Chủ đề", "Đổi màu toàn bộ ứng dụng, có hiệu lực ngay khi lưu.",
            self.theme_combo))
        body.addWidget(card)

        card, cvl = _section_card("Dự án")
        row, edit, browse = _dir_row(
            "Thư mục dự án mặc định",
            "Nơi tạo thư mục cho mỗi dự án mới.", values["project_dir"])
        browse.clicked.connect(
            lambda checked=False, k="project_dir": self._browse(k))
        cvl.addLayout(row)
        self.dir_edits["project_dir"] = edit
        self.dir_browse["project_dir"] = browse
        self.default_fps = _make_combo(
            ["24", "25", "30", "50", "60"], str(values["default_fps"]), 80)
        cvl.addLayout(_setting_row(
            "FPS mặc định cho dự án mới",
            "Ghi vào metadata dự án, và là FPS dùng để tính bước frame khi chưa mở dự án nào.",
            self.default_fps))
        body.addWidget(card)

        card, cvl = _section_card("Tự động lưu")
        self.auto_save = _make_toggle(values["auto_save"])
        cvl.addLayout(_setting_row(
            "Tự động lưu dự án",
            "Ghi định kỳ trạng thái timeline ra file dự án.", self.auto_save))
        self.save_interval = _make_combo(
            ["1", "3", "5", "10", "15", "30"], str(values["auto_save_interval"]), 80)
        cvl.addLayout(_setting_row(
            "Khoảng thời gian tự động lưu (phút)",
            "Chỉ có ý nghĩa khi tự động lưu đang bật.", self.save_interval))
        body.addWidget(card)

        body.addStretch(1)

    def _browse(self, key):
        edit = self.dir_edits[key]
        chosen = QFileDialog.getExistingDirectory(self, "Chọn thư mục", edit.text())
        if chosen:
            edit.setText(chosen)

    def get_settings(self):
        return {
            "theme": _THEME_KEYS.get(self.theme_combo.currentText(), "dark"),
            "default_fps": int(self.default_fps.currentText()),
            "auto_save": self.auto_save.isChecked(),
            "auto_save_interval": int(self.save_interval.currentText()),
            "project_dir": self.dir_edits["project_dir"].text(),
        }


# ── Tab: Timeline ─────────────────────────────────────────────

class _TimelineTab(QWidget):
    KEYS = ("snapping_enabled", "snap_playhead", "snap_clip_edges",
            "snap_threshold", "min_zoom_px_per_sec", "show_waveform",
            "show_thumbnails", "playhead_step", "undo_steps")

    def __init__(self, values):
        super().__init__()
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        body = _scroll_body(tab_layout)

        card, cvl = _section_card("Bắt dính (Snapping)")
        self.snap_enabled = _make_toggle(values["snapping_enabled"])
        cvl.addLayout(_setting_row(
            "Bật snapping",
            "Tắt thì clip dừng đúng chỗ chuột thả, không bị hút vào đâu.",
            self.snap_enabled))
        self.snap_playhead = _make_checkbox("Snap vào playhead",
                                            values["snap_playhead"])
        cvl.addWidget(self.snap_playhead)
        self.snap_edges = _make_checkbox("Snap vào đầu/cuối clip",
                                         values["snap_clip_edges"])
        cvl.addWidget(self.snap_edges)
        self.snap_threshold = _make_combo(
            ["2", "5", "8", "10", "15", "20", "30"],
            str(values["snap_threshold"]), 80)
        cvl.addLayout(_setting_row(
            "Ngưỡng bắt dính (pixel)",
            "Mép cách điểm snap bao xa thì vẫn bị hút vào.", self.snap_threshold))
        body.addWidget(card)

        card, cvl = _section_card("Thu phóng và hiển thị")
        self.min_zoom = _make_combo(
            ["1", "2", "5", "10", "20", "40"],
            str(values["min_zoom_px_per_sec"]), 90)
        cvl.addLayout(_setting_row(
            "Thu nhỏ tối đa (pixel mỗi giây)",
            "Slider zoom không cho kéo xuống dưới mức này.", self.min_zoom))
        self.show_waveform = _make_toggle(values["show_waveform"])
        cvl.addLayout(_setting_row(
            "Hiển thị dạng sóng âm thanh",
            "Tắt thì clip audio chỉ còn nền màu.", self.show_waveform))
        self.show_thumbs = _make_toggle(values["show_thumbnails"])
        cvl.addLayout(_setting_row(
            "Hiển thị thumbnail của clip",
            "Tắt thì clip video/Image dùng nền màu đặc thay vì dải ảnh.",
            self.show_thumbs))
        body.addWidget(card)

        card, cvl = _section_card("Điều hướng và lịch sử")
        self.playhead_step = _make_combo(
            ["1", "2", "5", "10"], str(values["playhead_step"]), 80)
        cvl.addLayout(_setting_row(
            "Bước playhead (frame)",
            "Số frame đi qua mỗi lần nhấn mũi tên trái/phải.", self.playhead_step))
        self.undo_steps = _make_combo(
            ["10", "50", "100", "200", "500"], str(values["undo_steps"]), 90)
        cvl.addLayout(_setting_row(
            "Số bước hoàn tác tối đa",
            "Hạ xuống thì lịch sử đã dài hơn sẽ bị cắt ngay.", self.undo_steps))
        body.addWidget(card)

        body.addStretch(1)

    def get_settings(self):
        return {
            "snapping_enabled": self.snap_enabled.isChecked(),
            "snap_playhead": self.snap_playhead.isChecked(),
            "snap_clip_edges": self.snap_edges.isChecked(),
            "snap_threshold": int(self.snap_threshold.currentText()),
            "min_zoom_px_per_sec": int(self.min_zoom.currentText()),
            "show_waveform": self.show_waveform.isChecked(),
            "show_thumbnails": self.show_thumbs.isChecked(),
            "playhead_step": int(self.playhead_step.currentText()),
            "undo_steps": int(self.undo_steps.currentText()),
        }


# ── Settings Dialog ───────────────────────────────────────────

class SettingsDialog(QDialog):
    """Phát settingsApplied sau khi ghi file để cửa sổ đang chạy áp theo."""

    settingsApplied = Signal(dict)

    TAB_CLASSES = ((_GeneralTab, "Chung"), (_TimelineTab, "Timeline"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt — Clinging")
        screen = QApplication.primaryScreen()
        max_h = int(screen.availableGeometry().height() * 0.88) if screen else 720
        self.setMinimumSize(900, min(520, max_h))
        self.setMaximumHeight(max_h)
        self.resize(980, min(680, max_h))
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet("QDialog { background-color: #0D0E15; border: 1px solid #1C1E27; border-radius: 12px; color: #E0E0E0; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = QFrame()
        title_bar.setFixedHeight(48)
        title_bar.setStyleSheet("background-color: #0D0E15; border-bottom: 1px solid #1C1E27; border-top-left-radius: 12px; border-top-right-radius: 12px;")
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(20, 0, 12, 0)
        title_lbl = QLabel("Cài đặt")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        tb.addWidget(title_lbl)
        tb.addStretch(1)
        close_btn = QPushButton()
        close_btn.setIcon(_qta().icon("fa6s.xmark", color="#9A9DAA"))
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("background: transparent; border: none; border-radius: 4px;")
        close_btn.clicked.connect(self.reject)
        tb.addWidget(close_btn)
        root.addWidget(title_bar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab {
                background: transparent; color: #6E7180; border: none;
                border-bottom: 2px solid transparent; padding: 10px 24px;
                font-size: 13px; font-weight: 500;
            }
            QTabBar::tab:selected { color: #EAFFFB; border-bottom: 2px solid #40E0D0; }
            QTabBar::tab:hover { color: #CCCCCC; }
        """)
        content_layout.addWidget(self.tabs, 1)

        bottom = QFrame()
        bottom.setFixedHeight(60)
        bottom.setStyleSheet("background-color: #0D0E15; border-top: 1px solid #1C1E27;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(32, 0, 32, 0)

        reset_all = QPushButton("  Đặt lại tất cả cài đặt  ")
        reset_all.setIcon(_qta().icon("fa6s.rotate-right", color="#E0E0E0"))
        reset_all.setCursor(Qt.PointingHandCursor)
        reset_all.setStyleSheet("QPushButton { background: transparent; color: #E0E0E0; border: 1px solid #2A2C38; border-radius: 8px; padding: 10px 16px; font-size: 12px; }"
                                "QPushButton:hover { background-color: #1A1B22; border-color: #3A3D4E; }")
        reset_all.clicked.connect(self._on_reset)
        bl.addWidget(reset_all)
        bl.addStretch(1)

        save_btn = QPushButton("  Lưu  ")
        save_btn.setStyleSheet("QPushButton { background-color: #2C6E64; color: #EAFFFB; border: 1px solid #40E0D0; border-radius: 8px; padding: 10px 40px; font-size: 13px; font-weight: bold; }"
                               "QPushButton:hover { background-color: #348175; }")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        bl.addWidget(save_btn)

        cancel_btn = QPushButton("  Hủy  ")
        cancel_btn.setStyleSheet("QPushButton { background-color: #1A1B22; color: #E0E0E0; border: 1px solid #2A2C38; border-radius: 8px; padding: 10px 40px; font-size: 13px; }"
                                 "QPushButton:hover { background-color: #252836; border-color: #3A3D4E; }")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        bl.addWidget(cancel_btn)

        content_layout.addWidget(bottom)
        root.addWidget(content, 1)

        self._drag_pos = None
        title_bar.mousePressEvent = self._title_press
        title_bar.mouseMoveEvent = self._title_move
        title_bar.mouseReleaseEvent = self._title_release

        self.populate(settings.values())

    # ── Nạp control từ giá trị thật ──

    def populate(self, values):
        """Dựng lại tab từ đúng bộ giá trị đang có — control không giữ trạng thái riêng."""
        while self.tabs.count():
            self.tabs.removeTab(0)
        for tab_class, name in self.TAB_CLASSES:
            self.tabs.addTab(tab_class(values), name)
        self.tabs_data = [self.tabs.widget(i) for i in range(self.tabs.count())]

    def merged_settings(self):
        """Mỗi tab chỉ đóng góp khóa của chính nó.

        Gộp nguyên dict thì tab dựng sau ghi đè khóa của tab dựng trước: đổi
        theme ở tab Chung từng bị tab Timeline 'nuốt' mất ngay trước khi ghi đĩa.
        """
        merged = {}
        for tab in self.tabs_data:
            values = tab.get_settings()
            merged.update({key: values[key] for key in tab.KEYS})
        return merged

    # ── Nút ──

    def _on_save(self):
        self._write(self.merged_settings(), close=True)

    def _on_reset(self):
        """Đặt lại thật: ghi DEFAULTS ra đĩa, áp dụng, rồi dựng lại control."""
        self._write(settings.reset(), close=False)
        self.populate(settings.values())

    def _write(self, values, close):
        try:
            saved = settings.save(values)
        except OSError as exc:
            from ui.custom_dialog import CustomDialog
            CustomDialog.warning(self, "Không lưu được cài đặt", str(exc))
            return
        theme_manager.set_mode(saved["theme"])
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme_manager.stylesheet())
        self.settingsApplied.emit(saved)
        if close:
            self.accept()

    # ── Drag ──

    def _title_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_move(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _title_release(self, event):
        self._drag_pos = None
