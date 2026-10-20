"""
ui/split_dialog.py
Hộp thoại "Cắt thành nhiều đoạn": chọn MỘT video hoặc audio trong dự án, nhập
số đoạn, rồi ghi N file thật ra một thư mục.

Toán cắt nằm ở core/media_splitter.py — hộp thoại này không tự tính giây, không
tự đặt tên file, và không bao giờ báo một con số mà ffprobe chưa đo lại.
"""

import os
import threading

from PySide6.QtCore import Qt, QObject, QRunnable, Signal, QThreadPool, QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from core import external_tools
from core import media_splitter as splitter
from widgets.common import Toast, font_icon, open_local_file

MODE_LABELS = [
    (splitter.MODE_AUTO, "Nhanh — copy khi an toàn, mã hoá lại đoạn lệch"),
    (splitter.MODE_ENCODE, "Chính xác từng giây — mã hoá lại mọi đoạn"),
]


def _fmt(seconds):
    """1:05.30 cho người, khong phai 65.3 — doan video dai thi giay le khong doc
    duoc bang mat."""
    value = max(0.0, float(seconds or 0.0))
    minutes, rest = divmod(value, 60.0)
    if minutes >= 1:
        return "%d:%05.2f" % (int(minutes), rest)
    return "%.2fs" % value


class _SplitSignals(QObject):
    """Tín hiệu phải do QObject sống ở thread GUI sở hữu; QTimer.singleShot từ
    thread thường không bao giờ fires."""
    progress = Signal(int, int, object)
    finished = Signal(object)
    failed = Signal(str)


class _SplitTask(QRunnable):
    def __init__(self, file_path, out_dir, count, start, end, mode):
        super().__init__()
        self.args = (file_path, out_dir, count, start, end, mode)
        self.cancel_event = threading.Event()
        self.signals = _SplitSignals()

    def run(self):
        path, out_dir, count, start, end, mode = self.args
        try:
            result = splitter.split_media(
                path, out_dir, count=count, start=start, end=end, mode=mode,
                progress=lambda done, total, record: self.signals.progress.emit(
                    int(done), int(total), record),
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


class SplitDialog(QDialog):
    """Một hộp thoại cho mọi file; nguồn khởi đầu là card bị bấm chuột phải."""

    def __init__(self, main_window=None, initial_path="", parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.initial_path = os.path.abspath(initial_path or "")
        self._busy = False
        self._task = None
        self._duration = 0.0
        self.last_result = None
        self.output_dir = ""

        self.setWindowTitle("Cắt thành nhiều đoạn")
        self.setObjectName("SplitDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumSize(560, 470)
        self.resize(600, 520)
        self.setStyleSheet(self._style())

        self._build_ui()
        self.prepare(initial_path)

    def prepare(self, initial_path=""):
        """Nap lai nguon truoc khi hien: thu vien co the da doi ke tu lan mo
        truoc, va file vua chuot phai thi phai nam dung tam hop thoai."""
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
        body.setObjectName("SplitBody")
        layout = QVBoxLayout(body)
        # Lenh hon 6px so voi viewport cua hop thoai thi thanh cuon xuyen tat
        # xuat hien o che do AsNeeded va an mat cot ben phai form.
        layout.setContentsMargins(20, 14, 20, 10)
        layout.setSpacing(8)

        layout.addWidget(self._label("Nguồn", "FieldLabel"))
        self.combo_source = QComboBox()
        self.combo_source.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self.combo_source)

        self.combo_mode = QComboBox()
        for key, label in MODE_LABELS:
            self.combo_mode.addItem(label, key)
        self.combo_mode.currentIndexChanged.connect(self._update_summary)
        layout.addWidget(self._label("Cách cắt", "FieldLabel"))
        layout.addWidget(self.combo_mode)

        self.spin_count = self._spin(QSpinBox, 2, splitter.MAX_SEGMENTS, 3,
                                     " đoạn")
        self.spin_count.valueChanged.connect(self._update_summary)
        self.spin_start = self._spin(QDoubleSpinBox, 0.0, 0.0, 0.0, " s",
                                     decimals=2)
        self.spin_end = self._spin(QDoubleSpinBox, 0.0, 0.0, 0.0, " s",
                                   decimals=2)
        self.spin_start.valueChanged.connect(self._update_summary)
        self.spin_end.valueChanged.connect(self._update_summary)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._column("Số đoạn", self.spin_count))
        row.addWidget(self._column("Từ", self.spin_start))
        row.addWidget(self._column("Đến", self.spin_end))
        layout.addLayout(row)

        layout.addWidget(self._label("Thư mục lưu", "FieldLabel"))
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.edit_out = QLineEdit()
        self.edit_out.setObjectName("SplitOut")
        self.edit_out.setReadOnly(True)
        btn_browse = QPushButton("Chọn…")
        btn_browse.setObjectName("SplitSecondary")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._on_browse)
        out_row.addWidget(self.edit_out, 1)
        out_row.addWidget(btn_browse)
        layout.addLayout(out_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("SplitSummary")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setObjectName("SplitProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        # Con so da co lbl_status lo ("... (3/6)") nen thanh nay chi minh hoa;
        # de text cua no tren mau ngan la vo nghia vi QProgressBar chi co mot
        # mau chu cho ca track lan chunk.
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.lbl_status = QLabel("Chọn file rồi bấm Cắt.")
        self.lbl_status.setObjectName("SplitStatus")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        scroll = QScrollArea()
        scroll.setObjectName("SplitScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        bar = QFrame()
        bar.setObjectName("SplitActions")
        bar.setFixedHeight(60)
        actions = QHBoxLayout(bar)
        actions.setContentsMargins(20, 10, 20, 12)
        actions.addStretch(1)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setObjectName("SplitSecondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_run = QPushButton("Cắt")
        self.btn_run.setObjectName("SplitPrimary")
        self.btn_run.setIcon(font_icon("fa6s.scissors", "#0B0C10"))
        self.btn_run.setIconSize(QSize(14, 14))
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self._on_run)
        actions.addWidget(self.btn_cancel)
        actions.addSpacing(8)
        actions.addWidget(self.btn_run)
        root.addWidget(bar)

    def _build_title_bar(self):
        bar = QFrame()
        bar.setObjectName("SplitTitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.scissors", "#40E0D0").pixmap(QSize(16, 16)))
        title = QLabel("Cắt thành nhiều đoạn")
        title.setObjectName("SplitTitle")
        close = QPushButton()
        close.setObjectName("SplitClose")
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
        #SplitTitleBar { background-color: #1A1B26;
                  border-bottom: 1px solid #2A2D3A;
                  border-top-left-radius: 12px;
                  border-top-right-radius: 12px; }
        #SplitTitle { font-size: 16px; font-weight: 700; color: #FFFFFF;
                  background: transparent; border: none; }
        QLabel { background: transparent; border: none; }
        #SplitClose { background: transparent; border: none; border-radius: 4px; }
        #SplitClose:hover { background: #FF4D4D; }
        #SplitBody, #SplitScroll { background: transparent; border: none; }
        #FieldLabel { font-size: 11px; font-weight: 700; color: #8A8F9C;
                  letter-spacing: 0.4px; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit#SplitOut {
            background-color: #14151A; border: 1px solid #2A2D3A;
            border-radius: 6px; padding: 6px 8px; color: #E2E5EA;
            font-size: 13px; }
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #40E0D0; }
        QComboBox::drop-down { border: none; width: 22px; }
        #SplitSummary { color: #9AA0AC; font-size: 12px; }
        #SplitStatus { color: #D8DCE0; font-size: 12px; }
        QProgressBar#SplitProgress { border: none;
                  border-radius: 4px; background-color: #14151A;
                  height: 8px; }
        QProgressBar#SplitProgress::chunk { background-color: #40E0D0;
                  border-radius: 4px; }
        #SplitActions { background-color: #16171F;
                  border-top: 1px solid #2A2D3A;
                  border-bottom-left-radius: 12px;
                  border-bottom-right-radius: 12px; }
        QPushButton#SplitPrimary { background-color: #40E0D0; color: #0B0C10;
                  font-weight: 700; border: none; border-radius: 6px;
                  padding: 8px 18px; }
        QPushButton#SplitPrimary:hover { background-color: #5BEADC; }
        QPushButton#SplitPrimary:disabled { background-color: #2A2C34;
                  color: #62686E; }
        QPushButton#SplitSecondary { background-color: #252729;
                  color: #D8DCE0; border: 1px solid #3A3A3A;
                  border-radius: 6px; padding: 8px 16px; }
        QPushButton#SplitSecondary:hover { border-color: #40E0D0; }
        """

    # ── Nguồn và thông số ───────────────────────────────────────

    def _load_sources(self):
        """Video và audio trong Thư viện + trên Timeline, không trùng lặp.

        Ảnh bị loại: một tấm ảnh không có dải thời gian nào để cắt.
        """
        found = []
        seen = set()
        window = self.main_window
        library = getattr(window, "library_panel", None) if window else None
        if library is not None:
            for record in library.resource_records():
                if record.get("type") not in ("video", "audio"):
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
                if getattr(clip, "media_type", "") not in ("video", "audio"):
                    continue
                path = getattr(clip, "source_path", "") or ""
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
                "Chưa có video hoặc audio nào trong dự án.")

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
        self._duration = float(splitter.media_info(path).get("duration") or 0.0) \
            if path else 0.0
        for spin in (self.spin_start, self.spin_end):
            spin.blockSignals(True)
            spin.setRange(0.0, max(0.0, self._duration))
        self.spin_start.setValue(0.0)
        self.spin_end.setValue(self._duration)
        for spin in (self.spin_start, self.spin_end):
            spin.blockSignals(False)
        self.edit_out.setText(splitter.unique_output_dir(path) if path else "")
        self.lbl_status.setText(
            "Nguồn dài %s." % _fmt(self._duration) if self._duration > 0 else
            "Không đọc được thời lượng của nguồn này.")
        self._update_summary()

    def _planned(self):
        if self._duration <= 0:
            return []
        return splitter.plan_segments(self._duration, self.spin_count.value(),
                                      self.spin_start.value(),
                                      self.spin_end.value())

    def _update_summary(self):
        plan = self._planned()
        if not plan:
            self.lbl_summary.setText("Không có đoạn nào để cắt.")
            return
        begin, span = plan[0]
        stop = plan[-1][0] + plan[-1][1]
        text = ("%d đoạn · mỗi đoạn %s · từ %s tới %s"
                % (len(plan), _fmt(span), _fmt(begin), _fmt(stop)))
        if self.combo_mode.currentData() == splitter.MODE_AUTO:
            text += ("\nĐiểm cắt sẽ được chỉnh về đúng khung hình keyframe gần "
                     "nhất, nên các đoạn có thể lệch nhau vài phần mười giây.")
        self.lbl_summary.setText(text)

    def _on_browse(self):
        start = self.edit_out.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu đoạn",
                                                  start)
        if chosen:
            self.edit_out.setText(os.path.normpath(chosen))

    # ── Chạy ────────────────────────────────────────────────────

    def _on_run(self):
        if self._busy:
            return
        path = self._current_source()
        plan = self._planned()
        out_dir = self.edit_out.text().strip()
        if not path or not plan or not out_dir:
            self.lbl_status.setText(
                "Thiếu nguồn, khoảng thời gian hoặc thư mục lưu.")
            return
        if not external_tools.find("ffmpeg"):
            # Không phải "một đoạn nào đó lỗi": không có trình thì không đoạn
            # nào chạy, và N dòng lỗi giống nhau sẽ chôn mất câu duy nhất người
            # dùng có thể tự làm theo.
            self.lbl_status.setText(
                external_tools.missing_message("ffmpeg").splitlines()[0])
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
        self.progress.setRange(0, len(plan))
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.combo_source.setEnabled(False)
        self.lbl_status.setText("Đang cắt…")
        self.setCursor(Qt.BusyCursor)

        task = _SplitTask(path, out_dir, self.spin_count.value(),
                          self.spin_start.value(), self.spin_end.value(),
                          self.combo_mode.currentData())
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        _pool().start(task)

    def _on_progress(self, done, total, record):
        if not self._busy:
            return
        self.progress.setValue(done)
        self.lbl_status.setText(
            "Đang lưu đoạn %d/%d tại %s (%s)" %
            (done, total, _fmt(record.get("start", 0.0)),
             record.get("mode") or "?"))

    def _on_done(self, result):
        self._release()
        self.last_result = result
        segments = result.get("segments", [])
        failed = result.get("failed", [])
        folder = os.path.basename(self.output_dir.rstrip("\\/"))
        if result.get("cancelled"):
            self.lbl_status.setText(
                "Đã dừng — giữ lại %d đoạn đã lưu trong %s"
                % (len(segments), folder))
            return
        if not segments:
            self.lbl_status.setText(
                "Không cắt được đoạn nào. File có thể hỏng, hoặc nguồn không "
                "còn keyframe nào để cắt.")
            return
        encoded = sum(1 for row in segments if row.get("mode") == "encode")
        copied = len(segments) - encoded
        # "tổng" ở đây là TỔNG DO ĐƯỢC của các file trên đĩa, không phải thời
        # lượng nguồn: mỗi mei cat copy lech den ~0.1s do cach dem khung hinh
        # B-frame, nen ghi "tổng 6.19s" cho nguồn 6.00s sẽ là một câu nói lái.
        measured = sum(float(row.get("actual") or 0.0) for row in segments)
        detail = "%d đoạn (%d copy, %d mã hoá) · tổng đo được %s" % (
            len(segments), copied, encoded, _fmt(measured))
        if failed:
            detail += " · %d đoạn thất bại" % len(failed)
        self.lbl_status.setText("Đã lưu %s vào %s" % (detail, self.output_dir))
        Toast.popup(self, "Cắt xong", detail, icon_name="fa6s.circle-check",
                    action_label="Mở thư mục", action=self._open_folder,
                    dark=True, y_shift=-66)

    def _on_failed(self, message):
        self._release()
        self.progress.setVisible(False)
        self.lbl_status.setText("Lỗi khi cắt: %s" % message)

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
            self.lbl_status.setText("Đang dừng… (đoạn hiện tại sẽ ghi xong)")
            return
        self.reject()

    def _on_close(self):
        self._on_cancel()

    def reject(self):
        if self._busy:
            self._on_cancel()
            return
        super().reject()
