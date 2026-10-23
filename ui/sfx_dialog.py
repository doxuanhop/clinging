"""
ui/sfx_dialog.py

Hộp thoại "Hiệu ứng âm thanh": nghe thử một tiếng trong pack dựng sẵn
(`assets/sfx/`) rồi chèn nó xuống timeline.

Toàn bộ việc đọc pack nằm ở core/sfx.py — hộp thoại không tự do độ dài, không
tự tìm ffmpeg/ffprobe, và chèn qua ĐÚNG ngăn nạp mà kéo-thả từ thư viện vẫn đi
(`TimelinePanel._on_resource_dropped`), nên undo của người dùng là undo thật và
project lưu đúng một clip audio như mọi media khác.
"""

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from core import sfx as sfx_core
from widgets.common import font_icon

ALL_GROUPS = "Tất cả nhóm"


class SfxDialog(QDialog):
    """Một instance duy nhất do MainWindow giữ — mở/đóng không dựng lại worker."""

    insertRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SfxDialog")
        self.setWindowTitle("Hiệu ứng âm thanh")
        self.setModal(False)
        self.resize(460, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm tiếng…")
        self.search.setClearButtonEnabled(True)
        self.group_combo = QComboBox()
        self.group_combo.addItem(ALL_GROUPS)
        head.addWidget(self.search, 3)
        head.addWidget(self.group_combo, 2)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        root.addWidget(self.list, 1)

        info = QHBoxLayout()
        self.icon_play = QPushButton("  Nghe thử")
        self.icon_play.setIcon(font_icon("fa6s.play", color="#FFFFFF"))
        self.icon_play.setObjectName("SfxPreviewBtn")
        self.icon_play.setMinimumWidth(120)
        self.icon_insert = QPushButton("  Chèn vào timeline")
        self.icon_insert.setIcon(font_icon("fa6s.plus", color="#FFFFFF"))
        self.icon_insert.setObjectName("PrimaryPillButton")
        self.icon_insert.setMinimumWidth(180)
        info.addWidget(self.icon_play)
        info.addStretch(1)
        info.addWidget(self.icon_insert)
        root.addLayout(info)

        self.status = QLabel("")
        self.status.setObjectName("SfxStatus")
        root.addWidget(self.status)

        # Mot QMediaPlayer cua rieng: dung player cua editor thi tieng SFX chen
        # vao giua luc nguoi dang xem lai bi cat doan, va nguoc lai.
        self._audio_out = QAudioOutput(self)
        self._audio_out.setVolume(0.8)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)

        self.search.textChanged.connect(self._refill)
        self.group_combo.currentIndexChanged.connect(self._refill)
        self.icon_play.clicked.connect(self._toggle_preview)
        self.icon_insert.clicked.connect(self._insert)
        self.list.itemDoubleClicked.connect(lambda *_: self._insert())

        self._refill()

    # ---------------------------------------------------------------
    # Danh sách

    def refresh(self):
        """Đọc lại pack (gói mới dựng trên đĩa không cần mở lại app)."""
        sfx_core.entries(force=True)
        self._refill()
        return self

    def _groups(self):
        names = sfx_core.groups()
        current = self.group_combo.currentText()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem(ALL_GROUPS)
        for name in names:
            self.group_combo.addItem(name)
        index = self.group_combo.findText(current)
        self.group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.group_combo.blockSignals(False)

    def _refill(self):
        self._groups()
        needle = self.search.text().strip().casefold()
        group = self.group_combo.currentText()
        want = "" if group == ALL_GROUPS else group
        self.list.blockSignals(True)
        self.list.clear()
        for row in sfx_core.entries():
            if want and row.get("group") != want:
                continue
            label = row.get("label") or row.get("key") or ""
            if needle and needle not in ("%s %s %s" % (
                    label, row.get("key"), row.get("group"))).casefold():
                continue
            item = QListWidgetItem("%s   ·   %.2f s   ·   %.0f KB" % (
                label, float(row.get("seconds") or 0.0),
                max(0, int(row.get("bytes") or 0)) / 1024.0))
            item.setData(Qt.UserRole, row)
            self.list.addItem(item)
        self.list.blockSignals(False)
        missing = sfx_core.missing_files()
        if missing:
            self.status.setText("Thiếu %d tệp trong pack — chạy "
                                "python tools/make_sfx.py" % len(missing))
        elif self.list.count() == 0:
            self.status.setText("Không có tiếng nào khớp bộ lọc.")
        else:
            self.status.setText("%d tiếng trong pack." % self.list.count())

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    # ---------------------------------------------------------------
    # Nghe thử

    def _toggle_preview(self):
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.stop_preview()
            return
        row = self._selected()
        if not row:
            self.status.setText("Chọn một tiếng trước đã.")
            return
        if not os.path.isfile(row["path"]):
            self.status.setText("Thiếu tệp %s" % os.path.basename(row["path"]))
            return
        self._player.setSource(QUrl.fromLocalFile(row["path"]))
        self._player.play()

    def stop_preview(self):
        self._player.stop()
        # QMediaPlayer giu file MO cho toi khi source bi thay — chen xong mà
        # keep nguồn thì probe không xóa được fixture (WinError 32).
        self._player.setSource(QUrl())

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.icon_play.setText("  Dừng" if playing else "  Nghe thử")
        self.icon_play.setIcon(font_icon("fa6s.stop" if playing else "fa6s.play",
                                         color="#FFFFFF"))

    def _on_error(self, _error, message):
        self.status.setText("Nghe thử lỗi: %s" % (message or "không rõ"))

    # ---------------------------------------------------------------
    # Chèn

    def _insert(self):
        row = self._selected()
        if not row:
            self.status.setText("Chọn một tiếng trước đã.")
            return None
        self.insertRequested.emit(row)
        return row

    def closeEvent(self, event):
        self.stop_preview()
        super().closeEvent(event)


def insert_to_timeline(window, entry):
    """Chen mot tieng SFX xuong timeline qua ngan nap that, tai vi tri playhead.

    Playhead nhích về CUỐI clip vừa chèn để tiếng kế tiếp nối liền. Nếu không
    nhích thi `TimelineModel.add_clip` khong cho hai clip chong nhau va mo lan
    thu hai (`_create_collision_track`) — do 22/10 qua phan chung: vet "chen
    xong khong tien playhead" ra HAI lane audio chu khong phai mot lane de len
    nhau.

    Khong goi `_auto_save` o day: ngan nap tha tu thu vien cung khong luu, ma de
    dong ho autosave (30 s) cua `MainWindow`. Them mot lan ghi rieng la them mot
    phep doi voi du lieu nguoi dung ma khong tinh nang nao doi.
    """
    panel = window.timeline_panel
    start = float(panel.model.playhead)
    clip = panel._on_resource_dropped(entry["path"], "audio", start, -1.0)
    if clip is None:
        return None
    panel.model.playhead = start + float(clip.duration)
    panel.model.select_clip(clip.clip_id)
    return clip
