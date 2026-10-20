"""
ui/thumbnail_dialog.py
Hộp thoại "Trích xuất ảnh thu nhỏ": chọn MỘT video trong dự án, đặt cách chọn
mốc (đều N ảnh hoặc mỗi X giây), rồi ghi từng ảnh PNG + ảnh tổng hợp 5×5 ra
một thư mục.

Mọi con số đều tính bằng core/thumbnail_export.py — cùng quy tắc
frame_index_at() mà preview và Export dùng — nên ảnh ghi ra ở đây chính là
khung người ta đang nhìn thấy trên timeline, không phải khung kề bên.
"""

import os
import threading

from PySide6.QtCore import Qt, QObject, QRunnable, Signal, QThreadPool, QSize
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from core import thumbnail_export as thumbs
from widgets.common import Toast, font_icon, open_local_file

WIDTH_OPTIONS = [
    (320, "320 px  ·  nhanh, đủ xem lại"),
    (640, "640 px  ·  cân bằng"),
    (960, "960 px  ·  ảnh lớn"),
    (1280, "1280 px  ·  chậm hơn, tốn đĩa"),
]

MODE_LABELS = [
    (thumbs.MODE_COUNT, "Đều nhau — đúng N ảnh"),
    (thumbs.MODE_INTERVAL, "Theo chu kỳ — mỗi X giây"),
]

SHEET_CELLS = thumbs.SHEET_COLUMNS * thumbs.SHEET_ROWS


class _ThumbSignals(QObject):
    """Tín hiệu phải do QObject sống ở thread GUI sở hữu; QTimer.singleShot từ
    thread thường không bao giờ fires."""
    progress = Signal(int, int, float)
    finished = Signal(object)
    failed = Signal(str)


class _ExtractTask(QRunnable):
    def __init__(self, file_path, out_dir, mode, count, interval, start, end,
                 width, contact_sheet):
        super().__init__()
        self.args = (file_path, out_dir, mode, count, interval, start, end,
                     width, contact_sheet)
        self.cancel_event = threading.Event()
        self.signals = _ThumbSignals()

    def run(self):
        path, out_dir, mode, count, interval, start, end, width, sheet = self.args
        try:
            result = thumbs.export_video_thumbnails(
                path, out_dir, mode=mode, count=count, interval=interval,
                start=start, end=end, width=width, contact_sheet=sheet,
                progress=lambda done, total, seconds: self.signals.progress.emit(
                    int(done), int(total), float(seconds)),
                should_cancel=self.cancel_event.is_set)
            self.signals.finished.emit(result)
        except Exception as exc:
            # str(exc) phai duoc copy TRUOC khi vuot bien: exception da bi
            # giai phong luc signal nay duoc dispatch o thread GUI.
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
    return _POOL


class ThumbnailDialog(QDialog):
    """Một hộp thoại cho mọi video; nguồn khởi đầu là video bị bấm chuột phải."""

    def __init__(self, main_window=None, initial_path="", parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.initial_path = os.path.abspath(initial_path or "")
        self._busy = False
        self._task = None
        self._duration = 0.0
        self.last_result = None
        self.output_dir = ""

        self.setWindowTitle("Trích xuất ảnh thu nhỏ")
        self.setObjectName("ThumbnailDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumSize(560, 540)
        self.resize(600, 600)
        self.setStyleSheet(self._style())

        self._build_ui()
        self.prepare(initial_path)

    def prepare(self, initial_path=""):
        """Nap lai nguon truoc khi hien: thu vien co the da doi ke tu lan mo
        truoc, va video vua chuot phai thi phai nam dung tam hop thoai."""
        path = os.path.abspath(initial_path or "") or self.initial_path
        self.initial_path = path
        self._load_sources()
        if path:
            self._select_source(path)
        self._on_source_changed()

    # ── Giao diện ───────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_title_bar())

        body = QWidget()
        body.setObjectName("ThumbBody")
        layout = QVBoxLayout(body)
        # Lenh hon 6px so voi viewport cua hop thoai 600px thi thanh cuon xuyen
        # tat xuat hien o che do AsNeeded, va no an mat cot ben phai form.
        layout.setContentsMargins(20, 14, 20, 10)
        layout.setSpacing(8)

        layout.addWidget(self._label("Nguồn video", "FieldLabel"))
        self.combo_source = QComboBox()
        self.combo_source.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self.combo_source)

        layout.addWidget(self._label("Cách chọn khung hình", "FieldLabel"))
        self.combo_mode = QComboBox()
        for key, label in MODE_LABELS:
            self.combo_mode.addItem(label, key)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.combo_mode)

        self.spin_count = self._spin(QSpinBox, 1, thumbs.MAX_FRAMES, 12,
                                     " ảnh")
        self.spin_interval = self._spin(QDoubleSpinBox, 0.1, 600.0, 2.0,
                                        " giây", decimals=2)
        self.spin_count.valueChanged.connect(self._update_summary)
        self.spin_interval.valueChanged.connect(self._update_summary)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._column("Số ảnh", self.spin_count))
        row.addWidget(self._column("Cách nhau", self.spin_interval))
        layout.addLayout(row)

        self.spin_start = self._spin(QDoubleSpinBox, 0.0, 0.0, 0.0, " s",
                                     decimals=2)
        self.spin_end = self._spin(QDoubleSpinBox, 0.0, 0.0, 0.0, " s",
                                   decimals=2)
        self.spin_start.valueChanged.connect(self._update_summary)
        self.spin_end.valueChanged.connect(self._update_summary)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._column("Từ", self.spin_start))
        row2.addWidget(self._column("Đến", self.spin_end))
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self.combo_width = QComboBox()
        for value, label in WIDTH_OPTIONS:
            self.combo_width.addItem(label, value)
        self.combo_width.setCurrentIndex(1)
        self.combo_width.currentIndexChanged.connect(self._update_summary)
        self.check_sheet = QCheckBox("Ảnh tổng hợp 5×5")
        self.check_sheet.setChecked(True)
        self.check_sheet.toggled.connect(self._update_summary)
        row3.addWidget(self._column("Kích thước ảnh", self.combo_width), 1)
        row3.addWidget(self.check_sheet, 0, Qt.AlignBottom)
        layout.addLayout(row3)

        layout.addWidget(self._label("Thư mục lưu", "FieldLabel"))
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.edit_out = QLineEdit()
        self.edit_out.setObjectName("ThumbOut")
        self.edit_out.setReadOnly(True)
        btn_browse = QPushButton("Chọn…")
        btn_browse.setObjectName("ThumbSecondary")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._on_browse)
        out_row.addWidget(self.edit_out, 1)
        out_row.addWidget(btn_browse)
        layout.addLayout(out_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("ThumbSummary")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setObjectName("ThumbProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        # Chu cua QProgressBar chi co mot mau: den tren nan tra #14151A luc
        # 0% thi khong doc duoc, ma trang tren mau ngan teal thi cung mo.
        # Con so da co lbl_status lo ("... (3/6)") nen thanh nay chi minh hoa.
        self.progress.setTextVisible(False)
        # Thanh 0% trong nguyen khi chua chay la chrome chet: form luc dang
        # tay chi can mot duong ke sach. No xuat hien khi bam Trich xuat.
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.lbl_status = QLabel("Chọn video rồi bấm Trích xuất.")
        self.lbl_status.setObjectName("ThumbStatus")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        scroll = QScrollArea()
        scroll.setObjectName("ThumbScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        bar = QFrame()
        bar.setObjectName("ThumbActions")
        bar.setFixedHeight(60)
        actions = QHBoxLayout(bar)
        actions.setContentsMargins(20, 10, 20, 12)
        actions.addStretch(1)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setObjectName("ThumbSecondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_run = QPushButton("Trích xuất")
        self.btn_run.setObjectName("ThumbPrimary")
        self.btn_run.setIcon(font_icon("fa6s.images", "#0B0C10"))
        self.btn_run.setIconSize(QSize(14, 14))
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self._on_run)
        actions.addWidget(self.btn_cancel)
        actions.addSpacing(8)
        actions.addWidget(self.btn_run)
        root.addWidget(bar)

    def _build_title_bar(self):
        bar = QFrame()
        bar.setObjectName("ThumbTitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.images", "#40E0D0").pixmap(QSize(16, 16)))
        title = QLabel("Trích xuất ảnh thu nhỏ")
        title.setObjectName("ThumbTitle")
        close = QPushButton()
        close.setObjectName("ThumbClose")
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
    def _label(text, object_name):
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    @classmethod
    def _column(cls, text, widget):
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(cls._label(text, "FieldLabel"))
        box.addWidget(widget)
        return host

    @staticmethod
    def _spin(kind, minimum, maximum, value, suffix="", decimals=None):
        spin = kind()
        spin.setRange(minimum, maximum)
        if decimals is not None:
            spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _style():
        return """
        QDialog { background-color: #1A1C1F; border: 1px solid #34383D;
                  border-radius: 12px; color: #D8DCE0; }
        #ThumbTitleBar { background-color: #1A1B26;
                  border-bottom: 1px solid #2A2D3A;
                  border-top-left-radius: 12px;
                  border-top-right-radius: 12px; }
        #ThumbTitle { font-size: 16px; font-weight: 700; color: #FFFFFF;
                  background: transparent; border: none; }
        QLabel { background: transparent; border: none; }
        #ThumbClose { background: transparent; border: none; border-radius: 4px; }
        #ThumbClose:hover { background: #FF4D4D; }
        #ThumbBody, #ThumbScroll { background: transparent; border: none; }
        #FieldLabel { font-size: 11px; font-weight: 700; color: #8A8F9C;
                  letter-spacing: 0.4px; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit#ThumbOut {
            background-color: #14151A; border: 1px solid #2A2D3A;
            border-radius: 6px; padding: 6px 8px; color: #E2E5EA;
            font-size: 13px; }
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #40E0D0; }
        QComboBox::drop-down { border: none; width: 22px; }
        QCheckBox { color: #D8DCE0; font-size: 13px; spacing: 8px;
                  background: transparent; border: none; }
        #ThumbSummary { color: #9AA0AC; font-size: 12px; }
        #ThumbStatus { color: #D8DCE0; font-size: 12px; }
        QProgressBar#ThumbProgress { border: none;
                  border-radius: 4px; background-color: #14151A;
                  height: 8px; }
        QProgressBar#ThumbProgress::chunk { background-color: #40E0D0;
                  border-radius: 4px; }
        #ThumbActions { background-color: #16171F;
                  border-top: 1px solid #2A2D3A;
                  border-bottom-left-radius: 12px;
                  border-bottom-right-radius: 12px; }
        QPushButton#ThumbPrimary { background-color: #40E0D0; color: #0B0C10;
                  font-weight: 700; border: none; border-radius: 6px;
                  padding: 8px 18px; }
        QPushButton#ThumbPrimary:hover { background-color: #5BEADC; }
        QPushButton#ThumbPrimary:disabled { background-color: #2A2C34;
                  color: #62686E; }
        QPushButton#ThumbSecondary { background-color: #252729;
                  color: #D8DCE0; border: 1px solid #3A3A3A;
                  border-radius: 6px; padding: 8px 16px; }
        QPushButton#ThumbSecondary:hover { border-color: #40E0D0; }
        """

    # ── Nguồn và thông số ───────────────────────────────────────

    def _load_sources(self):
        """Video trong Thư viện + clip video trên Timeline, không trùng lặp."""
        found = []
        seen = set()
        window = self.main_window
        library = getattr(window, "library_panel", None) if window else None
        if library is not None:
            for record in library.resource_records():
                if record.get("type") != "video":
                    continue
                path = record.get("path", "")
                if path and path not in seen and os.path.exists(path):
                    seen.add(path)
                    found.append((path, record.get("name")
                                  or os.path.basename(path)))
        panel = getattr(window, "timeline_panel", None) if window else None
        model = getattr(panel, "model", None) if panel else None
        for track in getattr(model, "tracks", []) if model else []:
            for clip in getattr(track, "clips", []):
                path = getattr(clip, "source_path", "") or ""
                if getattr(clip, "media_type", "") != "video":
                    continue
                if path and path not in seen and os.path.exists(path):
                    seen.add(path)
                    found.append((path, getattr(clip, "name", "")
                                  or os.path.basename(path)))
        if self.initial_path and self.initial_path not in seen \
                and os.path.exists(self.initial_path):
            found.insert(0, (self.initial_path,
                             os.path.basename(self.initial_path)))
        self.combo_source.blockSignals(True)
        self.combo_source.clear()
        for path, label in found:
            self.combo_source.addItem(label, path)
        self.combo_source.blockSignals(False)
        if not found:
            self.btn_run.setEnabled(False)
            self.lbl_status.setText(
                "Chưa có video nào trong dự án. Thêm video vào Thư viện trước.")

    def _select_source(self, path):
        for index in range(self.combo_source.count()):
            if os.path.abspath(self.combo_source.itemData(index) or "") == path:
                self.combo_source.setCurrentIndex(index)
                return True
        return False

    def _current_source(self):
        return self.combo_source.currentData() or ""

    def _on_source_changed(self):
        path = self._current_source()
        self._duration = float(thumbs.video_info(path).get("duration") or 0.0) \
            if path else 0.0
        for spin in (self.spin_start, self.spin_end):
            spin.blockSignals(True)
            spin.setRange(0.0, max(0.0, self._duration))
        self.spin_start.setValue(0.0)
        self.spin_end.setValue(self._duration)
        for spin in (self.spin_start, self.spin_end):
            spin.blockSignals(False)
        self.edit_out.setText(thumbs.unique_output_dir(path) if path else "")
        self.lbl_status.setText(
            "Nguồn dài %.2f s." % self._duration if self._duration > 0 else
            "Không đọc được thời lượng của nguồn này.")
        self._on_mode_changed()

    def _on_mode_changed(self):
        interval = self.combo_mode.currentData() == thumbs.MODE_INTERVAL
        self.spin_count.setEnabled(not interval)
        self.spin_interval.setEnabled(interval)
        self._update_summary()

    def _planned_times(self):
        if self._duration <= 0:
            return []
        return thumbs.plan_times(
            self._duration, self.combo_mode.currentData(),
            self.spin_count.value(), self.spin_interval.value(),
            self.spin_start.value(), self.spin_end.value())

    def _update_summary(self):
        times = self._planned_times()
        if not times:
            self.lbl_summary.setText("Không có khung hình nào để trích xuất.")
            return
        width = int(self.combo_width.currentData() or 640)
        cell = thumbs.cell_size(self._current_source(), width)
        step = ("cách đều %.2f s" % (times[1] - times[0])) if len(times) > 1 \
            else "một mốc"
        text = ("%d ảnh · %d×%d px · %s · tới %.2f s"
                % (len(times), cell[0], cell[1], step, times[-1]))
        if self.check_sheet.isChecked():
            text += " · %d ảnh tổng hợp" % -(-len(times) // SHEET_CELLS)
        self.lbl_summary.setText(text)

    def _on_browse(self):
        start = self.edit_out.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu ảnh",
                                                  start)
        if chosen:
            self.edit_out.setText(os.path.normpath(chosen))

    # ── Chạy ────────────────────────────────────────────────────

    def _on_run(self):
        if self._busy:
            return
        path = self._current_source()
        times = self._planned_times()
        out_dir = self.edit_out.text().strip()
        if not path or not times or not out_dir:
            self.lbl_status.setText(
                "Thiếu nguồn, khoảng thời gian hoặc thư mục lưu.")
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.lbl_status.setText("Không tạo được thư mục: %s" % exc)
            return

        self._busy = True
        self.last_result = None
        self.output_dir = out_dir
        self.progress.setVisible(True)
        self.progress.setRange(0, len(times))
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.combo_source.setEnabled(False)
        self.lbl_status.setText("Đang giải mã video…")
        self.setCursor(Qt.BusyCursor)

        task = _ExtractTask(path, out_dir, self.combo_mode.currentData(),
                            self.spin_count.value(),
                            self.spin_interval.value(), self.spin_start.value(),
                            self.spin_end.value(),
                            int(self.combo_width.currentData() or 640),
                            self.check_sheet.isChecked())
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        _pool().start(task)

    def _on_progress(self, done, total, seconds):
        if not self._busy:
            return
        self.progress.setValue(done)
        self.lbl_status.setText("Đang lưu ảnh tại %.2f s  (%d/%d)"
                                % (seconds, done, total))

    def _on_done(self, result):
        self._release()
        self.last_result = result
        written = len(result.get("written", []))
        sheets = len(result.get("sheets", []))
        missing = len(result.get("missing", []))
        folder = os.path.basename(self.output_dir.rstrip("\\/"))
        if result.get("cancelled"):
            self.lbl_status.setText(
                "Đã dừng — giữ lại %d ảnh đã lưu trong %s" % (written, folder))
            return
        if written == 0:
            self.lbl_status.setText(
                "Không trích xuất được ảnh nào. Video có thể hỏng, hoặc toàn bộ"
                " mốc nằm ngoài thời lượng.")
            return
        detail = "%d ảnh" % written
        if sheets:
            detail += " + %d ảnh tổng hợp" % sheets
        if missing:
            detail += " · bỏ %d mốc không đọc được" % missing
        self.lbl_status.setText("Đã lưu %s vào %s" % (detail, self.output_dir))
        Toast.popup(self, "Trích xuất ảnh xong", detail,
                    icon_name="fa6s.circle-check", action_label="Mở thư mục",
                    action=self._open_folder, dark=True, y_shift=-66)

    def _on_failed(self, message):
        self._release()
        # Lot that bai khong co tien do de minh hoa; giu lai thanh lang o giua
        # form con hon de nguoi ta do loi vao no.
        self.progress.setVisible(False)
        self.lbl_status.setText("Lỗi khi trích xuất: %s" % message)

    def _open_folder(self):
        if not open_local_file(self.output_dir):
            self.lbl_status.setText("Không mở được thư mục (đã bị xoá?)")

    def _release(self):
        self._busy = False
        self._task = None
        self.unsetCursor()
        self.btn_run.setEnabled(bool(self._current_source()))
        self.combo_source.setEnabled(True)

    def _on_cancel(self):
        """Đóng giữa lúc chạy thì phải dừng worker trước: để thread ghi tiếp
        vào thư mục người ta đã đóng thì không còn cách báo cáo kết quả."""
        if self._busy and self._task is not None:
            self._task.cancel_event.set()
            self.lbl_status.setText("Đang dừng…")
            return
        self.reject()

    def _on_close(self):
        self._on_cancel()

    def reject(self):
        if self._busy:
            self._on_cancel()
            return
        super().reject()
