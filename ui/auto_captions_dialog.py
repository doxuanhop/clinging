"""
ui/auto_captions_dialog.py
Hộp thoại "Phụ đề tự động": chọn nguồn, chạy ASR ngoài thread, rồi đưa kết quả
lên Timeline (một bước undo) hoặc ghi ra file phụ đề.
"""

import os

from PySide6.QtCore import (
    Qt, QObject, QRunnable, Signal, QThreadPool,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from core import auto_captions


class _AsrSignals(QObject):
    """Tín hiệu phải do một QObject sống ở thread GUI sở hữu; QTimer.singleShot
    từ thread thường không bao giờ fires."""
    progress = Signal(int, str)
    finished = Signal(list)
    failed = Signal(str)


class _AsrTask(QRunnable):
    def __init__(self, media_path, engine):
        super().__init__()
        self.media_path = media_path
        self.engine = engine
        self.signals = _AsrSignals()

    def run(self):
        try:
            segments = auto_captions.transcribe(
                self.media_path, self.engine,
                lambda percent, message: self.signals.progress.emit(
                    int(percent), str(message)))
            self.signals.finished.emit(segments)
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
    return _POOL


def _fmt_ms(ms):
    s = ms / 1000.0
    return "%02d:%02d.%03d" % (int(s // 60), int(s % 60), int(ms % 1000))


class AutoCaptionsDialog(QDialog):
    """Một hộp thoại dùng cho cả nhận dạng và nhập file phụ đề có sẵn."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self._segments = []
        self._busy = False

        self.setWindowTitle("Phụ đề tự động")
        self.setObjectName("AutoCaptionsDialog")
        self.setMinimumSize(680, 520)
        self.resize(720, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Phụ đề tự động")
        title.setObjectName("DialogTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)
        self.combo_source = QComboBox()
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(list(auto_captions.ENGINES))
        self.combo_format = QComboBox()
        self.combo_format.addItems(list(auto_captions.FORMATS))
        form.addRow("Nguồn âm thanh:", self.combo_source)
        form.addRow("Engine:", self.combo_engine)
        root.addLayout(form)

        self.check_timeline = QCheckBox("Đưa phụ đề vào Timeline")
        self.check_timeline.setChecked(True)
        self.check_file = QCheckBox("Ghi ra file phụ đề:")
        row_opts = QHBoxLayout()
        row_opts.setSpacing(8)
        row_opts.addWidget(self.check_timeline)
        row_opts.addWidget(self.check_file)
        row_opts.addWidget(self.combo_format)
        row_opts.addStretch(1)
        root.addLayout(row_opts)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_run = QPushButton("Chạy nhận dạng")
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_import = QPushButton("Nhập file phụ đề...")
        self.btn_import.clicked.connect(self._on_import)
        self.btn_close = QPushButton("Đóng")
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_import)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setObjectName("AsrProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        # QProgressBar chi co MOT mau chu: den thi mat nan tra luc 0%, trang
        # thi mo tren mau ngan teal. Con so % xuong lbl_status, o day da co
        # san tin nhan cua engine, thanh chi con minh hoa.
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        # Thanh 0% nam chet giua form truoc khi chay cung la chrome chet.
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("Chọn nguồn rồi chạy nhận dạng.")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Thời gian", "Nội dung"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 205)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        # Bảng mặc định của Qt nền trắng — lệch hẳn chủ đề tối của app.
        self.setStyleSheet("""
            QTableWidget {
                background-color: #14151A;
                alternate-background-color: #181A20;
                color: #D8DCE0;
                border: 1px solid #262831;
                border-radius: 8px;
                gridline-color: #22242C;
            }
            QTableWidget::item { padding: 6px 8px; }
            QHeaderView::section {
                background-color: #1C1E27;
                color: #9A9DAA;
                border: none;
                padding: 6px 8px;
                font-weight: 600;
            }
            QPushButton#PrimaryBtn {
                background-color: #40E0D0;
                color: #0B0C10;
                font-weight: 700;
                border: none;
                border-radius: 6px;
                padding: 7px 14px;
            }
            QPushButton#PrimaryBtn:disabled {
                background-color: #2A2C34;
                color: #62686E;
            }
            QProgressBar#AsrProgress {
                border: none;
                border-radius: 4px;
                background-color: #14151A;
                height: 8px;
            }
            QProgressBar#AsrProgress::chunk {
                background-color: #40E0D0;
                border-radius: 4px;
            }
        """)

        self.refresh_sources()

    # ── Nguồn ───────────────────────────────────────────────────

    def refresh_sources(self):
        """Ưu tiên file có âm thanh: clip trên Timeline trước, rồi tới Thư viện."""
        found = []
        seen = set()
        model = self.main_window.timeline_panel.model
        for track in model.tracks:
            for clip in track.clips:
                path = clip.source_path or ""
                if clip.media_type in ("video", "audio") and path not in seen \
                        and os.path.exists(path):
                    seen.add(path)
                    found.append((path, clip.name or os.path.basename(path)))
        library = getattr(self.main_window, "library_panel", None)
        if library is not None:
            for record in library.resource_records():
                path = record.get("path", "")
                if record.get("type") in ("video", "audio") and path not in seen \
                        and os.path.exists(path):
                    seen.add(path)
                    found.append((path, record.get("name") or os.path.basename(path)))

        self.combo_source.clear()
        for path, label in found:
            self.combo_source.addItem(label, path)
        if not found:
            self.lbl_status.setText(
                "Chưa có nguồn âm thanh. Kéo một video hoặc file audio vào "
                "Timeline/Thư viện trước.")
            self.btn_run.setEnabled(False)
        else:
            self.btn_run.setEnabled(True)

    def _current_source(self):
        return self.combo_source.currentData() or ""

    # ── Chạy ────────────────────────────────────────────────────

    def _on_run(self):
        if self._busy:
            return
        media = self._current_source()
        if not media:
            QMessageBox.warning(self, "Phụ đề tự động", "Chưa chọn nguồn âm thanh.")
            return

        self._busy = True
        self.btn_run.setEnabled(False)
        self.btn_import.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(2)
        self.lbl_status.setText("2% · Đang chuẩn bị âm thanh...")
        self.setCursor(Qt.BusyCursor)

        task = _AsrTask(media, self.combo_engine.currentText())
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        _pool().start(task)

    def _on_progress(self, percent, message):
        percent = max(0, min(100, percent))
        self.progress.setValue(percent)
        # Thanh 8px khong con cho dua chu vao trong no, nen con so % phai
        # di tren dong nhan: xoa no la nguoi dung mat thong tin duy nhat
        # tang len duoc trong luc chay.
        self.lbl_status.setText("%d%% · %s" % (percent, message))

    def _on_done(self, segments):
        self._release(segments, "Nhận dạng xong %d dòng." % len(segments))

    def _on_import(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Nhập file phụ đề", "",
            "Phụ đề (*.srt *.ass *.ssa *.vtt *.txt)")
        if not path:
            return
        try:
            segments = auto_captions.read_subtitle(path)
        except Exception as exc:
            QMessageBox.critical(self, "Nhập phụ đề",
                                 "Không đọc được tệp này:\n%s" % exc)
            return
        if not segments:
            QMessageBox.information(self, "Nhập phụ đề",
                                    "Không tìm thấy dòng phụ đề nào trong tệp.")
            return
        self._segments = segments
        self._fill_table(segments)
        self.progress.setValue(100)
        self.lbl_status.setText("Đã đọc %d dòng từ %s."
                                % (len(segments), os.path.basename(path)))
        self._apply(segments)

    def _release(self, segments, message):
        self._busy = False
        self.btn_run.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.unsetCursor()
        self.progress.setValue(100)
        self._segments = segments
        self._fill_table(segments)
        self.lbl_status.setText(message)
        self._apply(segments)

    def _on_failed(self, message):
        self._busy = False
        self.btn_run.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.unsetCursor()
        self.progress.setValue(0)
        # Lot that bai thi khong con tien do de minh hoa; de lai thanh 0%
        # nam giua form chi la chrome chet luc dang bao loi.
        self.progress.setVisible(False)
        self.lbl_status.setText("Thất bại.")
        QMessageBox.critical(self, "Nhận dạng thất bại", message)

    # ── Kết quả ─────────────────────────────────────────────────

    def _fill_table(self, segments):
        self.table.setRowCount(len(segments))
        for row, seg in enumerate(segments):
            self.table.setItem(row, 0, QTableWidgetItem(
                "%s → %s" % (_fmt_ms(seg["start_ms"]), _fmt_ms(seg["end_ms"]))))
            self.table.setItem(row, 1, QTableWidgetItem(seg["text"]))

    def _apply(self, segments):
        model = self.main_window.timeline_panel.model
        if self.check_timeline.isChecked() and segments:
            cmd = auto_captions.caption_command(model, segments)
            self.main_window.timeline_panel.undo_stack.push(cmd)
            self.main_window._sync_canvas()
        if self.check_file.isChecked() and segments:
            media = self._current_source()
            out = self._write_file(segments, media)
            if out:
                self.lbl_status.setText(
                    "%d dòng đã chèn vào Timeline · file: %s"
                    % (len(segments), out))

    def _write_file(self, segments, media):
        out_dir = os.path.dirname(media) if media else ""
        stem = os.path.splitext(os.path.basename(media))[0] if media else "captions"
        out = os.path.join(out_dir, "%s.%s" % (stem, self.combo_format.currentText().lower()))
        try:
            return auto_captions.write_subtitle(segments, out)
        except OSError:
            fallback = os.path.join(os.path.expanduser("~"), "Clinging_exports",
                                    "%s.%s" % (stem, self.combo_format.currentText().lower()))
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            return auto_captions.write_subtitle(segments, fallback)
