"""
ui/compress_dialog.py
Hộp thoại "Nén / tối ưu tệp": chọn MỘT video trên đĩa, chọn kiểu đóng gói lại,
ghi ra một file mới ngay cạnh file cũ.

Toán nằm ở core/media_compress.py — hộp thoại này không tự dựng lệnh ffmpeg,
không tự đoán dung lượng, và không bao giờ báo một con số byte mà ffmpeg chưa
ghi xuống đĩa.
"""

import os
import threading

from PySide6.QtCore import Qt, QObject, QRunnable, Signal, QThreadPool, QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from core import external_tools
from core import media_compress as compress
from widgets.common import Toast, font_icon, open_local_file


def _fmt_bytes(value):
    """576340 -> '562,8 KB'; so le hang chuc trieu byte khong doc duoc."""
    size = max(0, int(value or 0))
    if size < 1024:
        return "%d B" % size
    units = ("KB", "MB", "GB")
    float_size = float(size)
    for unit in units:
        float_size /= 1024.0
        if float_size < 1024.0 or unit == units[-1]:
            return ("%.1f %s" % (float_size, unit)).replace(".", ",")
    return "%d B" % size


def _fmt_seconds(seconds):
    value = max(0.0, float(seconds or 0.0))
    minutes, rest = divmod(value, 60.0)
    text = "%d:%04.1f" % (int(minutes), rest) if minutes >= 1 else "%.1fs" % value
    # Cung mot cua van ban voi _fmt_bytes thi so phai cung mot dau thap phan:
    # "Nguồn 1,9 MB · 6.0s" la hai kieu so tron nhau.
    return text.replace(".", ",")


class _CompressSignals(QObject):
    """Tín hiệu phải do QObject sống ở thread GUI sở hữu; QTimer.singleShot từ
    thread thường không bao giờ fires."""
    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)


class _CompressTask(QRunnable):
    def __init__(self, source, output, mode, crf, preset):
        super().__init__()
        self.args = (source, output, mode, crf, preset)
        self.cancel_event = threading.Event()
        self.signals = _CompressSignals()

    def run(self):
        source, output, mode, crf, preset = self.args
        try:
            result = compress.compress_file(
                source, output, mode=mode, crf=crf, preset=preset,
                progress=lambda percent: self.signals.progress.emit(percent),
                should_cancel=self.cancel_event.is_set)
            if result["ok"] or result["cancelled"]:
                self.signals.finished.emit(result)
            else:
                # str(excp) da duoc copy trong result; vuot bien theo exception
                # goc thi thread GUI khong con gi de doc.
                self.signals.failed.emit(result["error"] or "Khong ro ly do")
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
    return _POOL


class CompressDialog(QDialog):
    """Một hộp thoại cho mọi file; nguồn khởi đầu là card bị bấm chuột phải."""

    def __init__(self, main_window=None, initial_path="", parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.initial_path = os.path.abspath(initial_path or "")
        self._busy = False
        self._task = None
        self._facts = {}
        self.last_result = None
        self.output_path = ""

        self.setWindowTitle("Nén / tối ưu tệp")
        self.setObjectName("CompressDialog")
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
        body.setObjectName("CompressBody")
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
        for mode in compress.MODES:
            self.combo_mode.addItem(compress.MODE_LABELS[mode], mode)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self._label("Cách xử lý", "FieldLabel"))
        layout.addWidget(self.combo_mode)

        self.spin_crf = QSpinBox()
        self.spin_crf.setRange(compress.CRF_MIN, compress.CRF_MAX)
        self.spin_crf.setValue(compress.DEFAULT_CRF[compress.MODE_X264])
        self.spin_crf.valueChanged.connect(self._update_summary)
        self.combo_preset = QComboBox()
        self._refill_presets(compress.MODE_X264)
        self.combo_preset.currentIndexChanged.connect(self._update_summary)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._column("Chất lượng (CRF)", self.spin_crf))
        row.addWidget(self._column("Tốc độ mã hoá", self.combo_preset))
        layout.addLayout(row)

        layout.addWidget(self._label("File lưu", "FieldLabel"))
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.edit_out = QLineEdit()
        self.edit_out.setObjectName("CompressOut")
        self.edit_out.setReadOnly(True)
        btn_browse = QPushButton("Chọn…")
        btn_browse.setObjectName("CompressSecondary")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._on_browse)
        out_row.addWidget(self.edit_out, 1)
        out_row.addWidget(btn_browse)
        layout.addLayout(out_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("CompressSummary")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setObjectName("CompressProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        # Con so da co lbl_status lo; de text cua no tren mau ngan la vo nghia
        # vi QProgressBar chi co mot mau chu cho ca track lan chunk.
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.lbl_status = QLabel("Chọn file rồi bấm Nén.")
        self.lbl_status.setObjectName("CompressStatus")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        scroll = QScrollArea()
        scroll.setObjectName("CompressScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        bar = QFrame()
        bar.setObjectName("CompressActions")
        bar.setFixedHeight(60)
        actions = QHBoxLayout(bar)
        actions.setContentsMargins(20, 10, 20, 12)
        actions.addStretch(1)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setObjectName("CompressSecondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_run = QPushButton("Nén")
        self.btn_run.setObjectName("CompressPrimary")
        self.btn_run.setIcon(font_icon("fa6s.compress", "#0B0C10"))
        self.btn_run.setIconSize(QSize(14, 14))
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self._on_run)
        actions.addWidget(self.btn_cancel)
        actions.addSpacing(8)
        actions.addWidget(self.btn_run)
        root.addWidget(bar)

    def _build_title_bar(self):
        bar = QFrame()
        bar.setObjectName("CompressTitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.compress", "#40E0D0").pixmap(QSize(16, 16)))
        title = QLabel("Nén / tối ưu tệp")
        title.setObjectName("CompressTitle")
        close = QPushButton()
        close.setObjectName("CompressClose")
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
    def _style():
        return """
        QDialog { background-color: #1A1C1F; border: 1px solid #34383D;
                  border-radius: 12px; color: #D8DCE0; }
        #CompressTitleBar { background-color: #1A1B26;
                  border-bottom: 1px solid #2A2D3A;
                  border-top-left-radius: 12px;
                  border-top-right-radius: 12px; }
        #CompressTitle { font-size: 16px; font-weight: 700; color: #FFFFFF;
                  background: transparent; border: none; }
        QLabel { background: transparent; border: none; }
        #CompressClose { background: transparent; border: none;
                  border-radius: 4px; }
        #CompressClose:hover { background: #FF4D4D; }
        #CompressBody, #CompressScroll { background: transparent; border: none; }
        #FieldLabel { font-size: 11px; font-weight: 700; color: #8A8F9C;
                  letter-spacing: 0.4px; }
        QComboBox, QSpinBox, QLineEdit#CompressOut {
            background-color: #14151A; border: 1px solid #2A2D3A;
            border-radius: 6px; padding: 6px 8px; color: #E2E5EA;
            font-size: 13px; }
        QComboBox:focus, QSpinBox:focus { border-color: #40E0D0; }
        QComboBox::drop-down { border: none; width: 22px; }
        QComboBox:disabled, QSpinBox:disabled { color: #62686E;
                  border-color: #23262C; }
        #CompressSummary { color: #9AA0AC; font-size: 12px; }
        #CompressStatus { color: #D8DCE0; font-size: 12px; }
        QProgressBar#CompressProgress { border: none; border-radius: 4px;
                  background-color: #14151A; height: 8px; }
        QProgressBar#CompressProgress::chunk { background-color: #40E0D0;
                  border-radius: 4px; }
        #CompressActions { background-color: #16171F;
                  border-top: 1px solid #2A2D3A;
                  border-bottom-left-radius: 12px;
                  border-bottom-right-radius: 12px; }
        QPushButton#CompressPrimary { background-color: #40E0D0; color: #0B0C10;
                  font-weight: 700; border: none; border-radius: 6px;
                  padding: 8px 18px; }
        QPushButton#CompressPrimary:hover { background-color: #5BEADC; }
        QPushButton#CompressPrimary:disabled { background-color: #2A2C34;
                  color: #62686E; }
        QPushButton#CompressSecondary { background-color: #252729;
                  color: #D8DCE0; border: 1px solid #3A3A3A;
                  border-radius: 6px; padding: 8px 16px; }
        QPushButton#CompressSecondary:hover { border-color: #40E0D0; }
        """

    # ── Nguồn và thông số ───────────────────────────────────────

    def _load_sources(self):
        """Video trong Thư viện + trên Timeline, không trùng lặp.

        Ảnh và audio bị loại: một tấm ảnh không có gì để nén lại, còn audio thì
        container của nó không có moov để dời — người dùng sẽ tưởng đã tiết kiệm.
        """
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
                if getattr(clip, "media_type", "") != "video":
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
            self.lbl_status.setText("Chưa có video nào trong dự án.")

    def _select_source(self, path):
        for index in range(self.combo_source.count()):
            if os.path.abspath(self.combo_source.itemData(index) or "") == path:
                self.combo_source.setCurrentIndex(index)
                return True
        return False

    def _current_source(self):
        return self.combo_source.currentData() or ""

    def _current_mode(self):
        return self.combo_mode.currentData() or compress.MODE_REMUX

    def _on_source_changed(self):
        path = self._current_source()
        self._facts = compress.source_facts(path) if path else {}
        self._sync_output_field()
        self._on_mode_changed()

    def _on_mode_changed(self):
        mode = self._current_mode()
        encode = mode != compress.MODE_REMUX
        self.spin_crf.setEnabled(encode)
        self.combo_preset.setEnabled(encode)
        self._refill_presets(mode)
        if encode:
            # Doi sang HEVC/VP9 ma giu CRF 20 cua H.264 thi file ra nang hon
            # nguoi dung tuong da chon — mac dinh phai theo tung codec.
            self.spin_crf.setValue(compress.DEFAULT_CRF[mode])
        self._sync_output_field()
        self._update_summary()

    def _refill_presets(self, mode):
        """Thang toc do lai khac nhau tung codec: libx26x co `fast`/`slow`,
        vp9 thi khong — ep `-preset` vao vp9 la ffmpeg bao "Invalid preset"."""
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        for value in compress.PRESETS_OF.get(mode, ()):
            label = value if mode != compress.MODE_VP9 else "cpu-used %s" % value
            self.combo_preset.addItem(label, value)
        index = self.combo_preset.findData(compress.DEFAULT_PRESET.get(mode))
        self.combo_preset.setCurrentIndex(max(0, index))
        self.combo_preset.blockSignals(False)

    def _speed_label(self):
        if self._current_mode() == compress.MODE_VP9:
            return "cpu-used %s" % (self.combo_preset.currentData() or "?")
        return self.combo_preset.currentData() or "?"

    def _pair_blocked(self, output):
        """Lời chặn của core, tính thêm codec của NGUỒN cho trường hợp remux."""
        return compress.pair_error(output, self._current_mode(),
                                   self._facts.get("video_codec", ""))

    def _sync_output_field(self):
        path = self._current_source()
        self.edit_out.setText(
            compress.suggest_output(path, self._current_mode()) if path else "")

    def _update_summary(self):
        facts = self._facts
        mode = self._current_mode()
        if not facts.get("exists"):
            self.lbl_summary.setText("Không có file nguồn nào để nén.")
            return
        head = ("Nguồn %s · %s · %s" % (_fmt_bytes(facts.get("bytes")),
                                        _fmt_seconds(facts.get("duration")),
                                        facts.get("extension") or "?"))
        if mode == compress.MODE_REMUX:
            detail = ("Không mã hoá lại: giữ nguyên từng bit hình ảnh, chỉ đổi "
                      "cách đóng gói" + (" và dời bảng mô tả lên đầu file."
                      if facts.get("extension") in compress.FASTSTART_CONTAINERS
                      else "."))
        else:
            label = compress.MODE_LABELS[mode]
            estimate = compress.estimate_seconds(mode, facts.get("duration")
                                                 or 0.0)
            detail = ("%s · CRF %d · %s — file này ước tính %s trên máy này "
                      "(đo ở 720p), file cũ vẫn giữ nguyên." %
                      (label, self.spin_crf.value(), self._speed_label(),
                       _fmt_seconds(estimate) if estimate > 0 else "vài giây"))
            blocked = self._pair_blocked(self.edit_out.text())
            if blocked:
                detail += "\n" + blocked
        self.lbl_summary.setText(head + "\n" + detail)

    def _extensions_for_mode(self, mode):
        """Đuôi mà KIỂU đang chọn ghi được — đọc ngược chính bảng mà core
        dùng để chặn lệnh, nên thêm codec sau này không phải sửa hộp thoại."""
        return compress.container_choices(mode)

    def _on_browse(self):
        current = self.edit_out.text()
        start = os.path.dirname(current) if current else os.path.expanduser("~")
        suggested = os.path.basename(current)
        chosen = QFileDialog.getSaveFileName(
            self, "Chọn file kết quả", os.path.join(start, suggested),
            "Video (%s)" % " ".join("*" + ext for ext in
                                    self._extensions_for_mode(
                                        self._current_mode())))
        if chosen:
            self.edit_out.setText(os.path.normpath(chosen[0] if isinstance(
                chosen, tuple) else chosen))
            self._update_summary()

    # ── Chạy ────────────────────────────────────────────────────

    def _on_run(self):
        if self._busy:
            return
        source = self._current_source()
        output = os.path.abspath(self.edit_out.text().strip() or "")
        mode = self._current_mode()
        if not source or not output:
            self.lbl_status.setText("Thiếu nguồn hoặc file kết quả.")
            return
        if not external_tools.find("ffmpeg"):
            # Không phải "một file nào đó lỗi": không có trình thì không file
            # nào chạy, và một dòng lỗi duy nhất mới là thứ người dùng làm được.
            self.lbl_status.setText(
                external_tools.missing_message("ffmpeg").splitlines()[0])
            return
        if os.path.normcase(output) == os.path.normcase(source):
            self.lbl_status.setText("File kết quả trùng file nguồn.")
            return
        blocked = self._pair_blocked(output)
        if blocked:
            self.lbl_status.setText(blocked)
            return
        encoder = compress.ENCODER_OF.get(mode)
        if encoder and not compress.encoder_present(encoder):
            self.lbl_status.setText(
                "Bản ffmpeg đang dùng không có %s — thử kiểu khác." % encoder)
            return

        self._busy = True
        self.last_result = None
        self.output_path = output
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.combo_source.setEnabled(False)
        self.lbl_status.setText("Đang nén…")
        self.setCursor(Qt.BusyCursor)

        task = _CompressTask(source, output, mode, self.spin_crf.value(),
                             self.combo_preset.currentData())
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        _pool().start(task)

    def _on_progress(self, percent):
        if not self._busy:
            return
        self.progress.setValue(int(percent))
        self.lbl_status.setText("Đang nén (%d%%)…" % int(percent))

    def _on_done(self, result):
        self._release()
        self.last_result = result
        if result.get("cancelled"):
            self.progress.setVisible(False)
            self.lbl_status.setText("Đã dừng — file dở đã bị xóa, nguồn còn nguyên.")
            return
        saved = int(result.get("saved_bytes") or 0)
        out_bytes = int(result.get("output_bytes") or 0)
        in_bytes = int(result.get("input_bytes") or 0)
        folder = os.path.dirname(self.output_path)
        if saved > 0:
            detail = ("%s → %s (bớt %s, còn %.0f%%)" % (
                _fmt_bytes(in_bytes), _fmt_bytes(out_bytes),
                _fmt_bytes(saved), out_bytes / float(in_bytes or 1) * 100.0))
        else:
            # File nguon da nen sat thi remux khong the nhe hon duoc nua —
            # phai noi thang dieu do, dung de nguoi dung tu doan rang loi.
            detail = ("%s → %s: khong nhe hon duoc nua, chi toi uu cach dong "
                      "goi" % (_fmt_bytes(in_bytes), _fmt_bytes(out_bytes)))
        if compress.is_faststart(self.output_path):
            detail += " · moov nam dau file"
        self.lbl_status.setText("Đã lưu vào %s" % folder)
        Toast.popup(self, "Nén xong", detail, icon_name="fa6s.circle-check",
                    action_label="Mở thư mục", action=self._open_folder,
                    dark=True, y_shift=-66)

    def _on_failed(self, message):
        self._release()
        self.progress.setVisible(False)
        self.lbl_status.setText("Lỗi khi nén: %s" % message)

    def _open_folder(self):
        if not open_local_file(os.path.dirname(self.output_path)):
            self.lbl_status.setText("Không mở được thư mục (đã bị xoá?)")

    def _release(self):
        self._busy = False
        self._task = None
        self.unsetCursor()
        self.btn_run.setEnabled(bool(self._current_source()))
        self.combo_source.setEnabled(True)

    def _on_cancel(self):
        """Đóng giữa lúc chạy thì phải dừng worker trước: để thread ghi tiếp
        vào một file người ta đã đóng thì không còn cách báo cáo kết quả."""
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
