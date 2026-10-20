"""
ui/home_page.py
Trang chủ của Clinqing - Quản lý dự án, tạo mới, và hiển thị danh sách gần đây.
"""

import os
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import (
    Qt, Signal, QSize, QTimer, QRect, QPoint, QObject, QRunnable, QThreadPool
)
from PySide6.QtGui import QFont, QColor, QIcon, QPainter, QPainterPath, QPixmap, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QSizePolicy, QSpacerItem,
    QMenu, QGraphicsDropShadowEffect
)
from ui.custom_dialog import CustomDialog as QMessageBox, CustomInputDialog

from core import system_stats
from widgets.common import IconButton, _qta, icon_color, set_label_icon


APP_NAME = "Clinging"
RECENT_FILE = "recent_projects.json"


def get_app_data_dir() -> Path:
    """Thư mục dữ liệu app dùng chung với core.settings — định nghĩa chỉ ở một nơi."""
    from core import settings
    return settings.app_data_dir()


def get_projects_dir() -> Path:
    """Thư mục dự án do cài đặt quyết định, đọc lúc dùng chứ không đọc lúc import."""
    from core import settings
    projects_dir = Path(settings.get("project_dir"))
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir


def load_recent_projects() -> list:
    recent_path = get_app_data_dir() / RECENT_FILE
    if recent_path.exists():
        try:
            with open(recent_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_recent_projects(projects: list):
    recent_path = get_app_data_dir() / RECENT_FILE
    try:
        with open(recent_path, 'w', encoding='utf-8') as f:
            json.dump(projects, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def create_project_folder(project_name: str, save_location: str = None,
                          resolution: tuple = (1920, 1080), fps: int = None,
                          aspect_ratio: str = "16:9") -> Path:
    """
    Tạo thư mục dự án mới và file .clinq rỗng theo định dạng CapCut-style.
    Trả về đường dẫn thư mục dự án.
    """
    from core import settings
    if fps is None:
        fps = int(settings.get("default_fps"))
    if save_location is None:
        save_location = str(get_projects_dir())
    base_path = Path(save_location) / project_name
    os.makedirs(base_path / "Assets", exist_ok=True)
    os.makedirs(base_path / "Cache", exist_ok=True)
    os.makedirs(base_path / "Exports", exist_ok=True)

    project_file = base_path / f"{project_name}.clinq"

    # Tạo file .clinq rỗng — ProjectManager.save() sẽ ghi đầy đủ khi có data
    from core.project_storage import ProjectManager
    pm = ProjectManager()
    pm._project_path = str(project_file)
    pm._project_id = f"proj-{uuid.uuid4().hex[:12]}"
    pm._project_meta = {
        "project_id": pm._project_id,
        "project_name": project_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "resolution": {"width": resolution[0], "height": resolution[1]},
        "fps": fps,
        "aspect_ratio": aspect_ratio,
        "version": "1.0",
    }

    # Ghi file .clinq rỗng (chỉ có meta, chưa có timeline)
    import json
    empty_project = {
        "project_meta": pm._project_meta,
        "assets": {},
        "timeline": {
            "duration": 30.0,
            "playhead": 0.0,
            "tracks": [],
        },
    }
    with open(project_file, 'w', encoding='utf-8') as f:
        json.dump(empty_project, f, ensure_ascii=False, indent=2)

    return base_path


# ── Project Template Card ────────────────────────────────────────

class ProjectTemplateCard(QFrame):
    clicked = Signal(str, tuple)

    def __init__(self, name, icon_name, resolution, description="", parent=None):
        super().__init__(parent)
        self.template_name = name
        self.resolution = resolution
        self.setObjectName("ProjectTemplateCard")
        self.setFixedSize(155, 160)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 14)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(48, 48)
        set_label_icon(icon_label, icon_name, 26, "#40E0D0")
        layout.addWidget(icon_label, alignment=Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("TemplateName")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        if resolution[0] > 0:
            res_label = QLabel(f"{resolution[0]} x {resolution[1]} px")
            res_label.setObjectName("TemplateRes")
            res_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(res_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setObjectName("TemplateDesc")
            desc_label.setAlignment(Qt.AlignCenter)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.template_name, self.resolution)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet("""
            ProjectTemplateCard {
                border: 1.5px solid #40E0D0;
                background-color: #1E1F2E;
            }
        """)

    def leaveEvent(self, event):
        self.setStyleSheet("")


# ── System Monitor Widget ────────────────────────────────────────

class _GpuSignals(QObject):
    measured = Signal(object)


class _GpuProbeTask(QRunnable):
    """wmic / nvidia-smi mất vài trăm ms: đo ngoài GUI thread rồi đưa kết quả
    về bằng queued signal."""

    def __init__(self, signals):
        super().__init__()
        self._signals = signals

    def run(self):
        try:
            payload = system_stats.read_gpu()
        except Exception:
            payload = None
        try:
            self._signals.measured.emit(payload)
        except RuntimeError:
            # Bảng theo dõi đã bị đóng lúc phép đo còn đang chạy: kết quả
            # không còn nơi nhận, bỏ qua thay vì nổ trong thread pool.
            pass


def _temp_color(celsius):
    if celsius >= 85:
        return "#FF6B6B"
    if celsius >= 70:
        return "#FFB347"
    return "#66BB6A"


class _MonitorItem(QFrame):
    """Một dòng theo dõi: tiêu đề, số đo thật, mô tả và thanh tỉ lệ.

    Không có giá trị khởi tạo nào là số bịa — hàng đợi tới khi đo được, và
    hàng nào đo không được thì ẩn đi.
    """

    def __init__(self, title, icon_name, value_object="MonitorValue", parent=None):
        super().__init__(parent)
        self.setObjectName("MonitorItem")
        self._percent = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        icon_label = QLabel()
        set_label_icon(icon_label, icon_name, 14, "#40E0D0")
        header.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setObjectName("MonitorLabel")
        header.addWidget(title_label)
        header.addStretch(1)

        self.value_label = QLabel()
        self.value_label.setObjectName(value_object)
        self.value_label.setVisible(False)
        header.addWidget(self.value_label)
        layout.addLayout(header)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("MonitorDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            "color: #6E7180; font-size: 11px; padding-left: 20px;")
        self.detail_label.setVisible(False)
        layout.addWidget(self.detail_label)

        self.sensor_layout = QHBoxLayout()
        self.sensor_layout.setContentsMargins(20, 0, 0, 0)
        self.sensor_layout.setSpacing(8)
        self._sensor_slots = []
        self.sensor_layout.addStretch(1)
        layout.addLayout(self.sensor_layout)

        self.progress_container = QFrame()
        self.progress_container.setObjectName("MonitorProgressContainer")
        self.progress_container.setFixedHeight(4)
        progress_layout = QHBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QFrame()
        self.progress_bar.setObjectName("MonitorProgressBar")
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setFixedWidth(0)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch(1)
        self.progress_container.setVisible(False)
        layout.addWidget(self.progress_container)

    def set_state(self, percent=None, value="", detail=None, sensors=None):
        self.value_label.setText(value or "")
        self.value_label.setVisible(bool(value))

        has_detail = bool(detail)
        self.detail_label.setVisible(has_detail)
        if has_detail:
            self.detail_label.setText(detail)

        if sensors is not None:
            self._set_sensors(sensors)

        if percent is None:
            self.progress_container.setVisible(False)
        else:
            self._percent = max(0.0, min(100.0, float(percent)))
            self.progress_container.setVisible(True)
            self._sync_bar()
            # Lần đầu layout chưa chạy nên container còn rộng 0 px.
            QTimer.singleShot(0, self._sync_bar)

    def _set_sensors(self, pairs):
        while len(self._sensor_slots) < len(pairs):
            name = QLabel()
            name.setObjectName("MonitorDetail")
            value = QLabel()
            value.setObjectName("MonitorDetailValue")
            position = len(self._sensor_slots) * 2
            self.sensor_layout.insertWidget(position, name)
            self.sensor_layout.insertWidget(position + 1, value)
            self._sensor_slots.append((name, value))
        for index, (label, text) in enumerate(pairs):
            self._sensor_slots[index][0].setText(label)
            self._sensor_slots[index][0].setVisible(True)
            self._sensor_slots[index][1].setText(text)
            self._sensor_slots[index][1].setVisible(True)
        for name, value in self._sensor_slots[len(pairs):]:
            name.setVisible(False)
            value.setVisible(False)

    def clear(self):
        """Bỏ mọi chữ trên hàng: hàng ẩn không được giữ lại số cũ."""
        self.value_label.setText("")
        self.value_label.setVisible(False)
        self.detail_label.setText("")
        self.detail_label.setVisible(False)
        self._set_sensors([])
        self._percent = None
        self.progress_container.setVisible(False)

    def _sync_bar(self):
        track = self.progress_container.width()
        if track <= 0 or self._percent is None:
            return
        width = int(round(track * self._percent / 100.0))
        if width < 2 and self._percent > 0:
            width = 2
        self.progress_bar.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_bar()


class SystemMonitorWidget(QFrame):
    POLL_MS = 2000
    GPU_POLL_MS = 15000
    FIRST_POLL_MS = 250   # cpu_percent cần một cửa sổ lấy mẫu, không block GUI

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SystemMonitor")
        self.setFixedWidth(260)

        self._gpu = None
        self._gpu_busy = False
        self._gpu_supported = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 16)
        layout.setSpacing(16)

        self.cpu_widget = _MonitorItem("CPU", "fa6s.microchip")
        layout.addWidget(self.cpu_widget)

        self.ram_widget = _MonitorItem("RAM", "fa6s.memory")
        layout.addWidget(self.ram_widget)

        self.gpu_widget = _MonitorItem("GPU", "fa6s.desktop")
        layout.addWidget(self.gpu_widget)

        self.temp_widget = _MonitorItem(
            "Nhiệt độ", "fa6s.temperature-high", value_object="MonitorValueTemp")
        layout.addWidget(self.temp_widget)

        self.storage_widget = _MonitorItem("Dung lượng thiết bị", "fa6s.hard-drive")
        layout.addWidget(self.storage_widget)

        layout.addStretch(1)

        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(0, 8, 0, 0)
        info_layout.setSpacing(4)

        software_label = QLabel("Phần mềm bởi")
        software_label.setObjectName("SoftwareBy")
        info_layout.addWidget(software_label)

        brand_label = QLabel("Qeafivels Software")
        brand_label.setObjectName("BrandName")
        info_layout.addWidget(brand_label)

        email_label = QLabel("dxhop96@gmail.com")
        email_label.setObjectName("ContactEmail")
        info_layout.addWidget(email_label)

        layout.addWidget(info_frame)

        # psutil va WMI nam trong luc mo app: import psutil do duoc 0,102 s
        # cum trong `main._boot()` (cProfile, cung lane), con
        # Win32_VideoController spawn mot tien trinh. Ca hai doi den sau khi
        # cua so da ve — so lieu den muon 250 ms, khong doi noi den.
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._update_stats)

        self._gpu_signals = _GpuSignals()
        self._gpu_signals.measured.connect(self._on_gpu_measured)
        self._gpu_timer = QTimer(self)
        self._gpu_timer.setInterval(self.GPU_POLL_MS)
        self._gpu_timer.timeout.connect(self._probe_gpu)

        QTimer.singleShot(self.FIRST_POLL_MS, self._begin_measurement)

    def _begin_measurement(self):
        """Do lan dau sau khi cua so da ve; thieu psutil thi an dong do."""
        if system_stats.psutil_or_none() is None:
            for item in (self.cpu_widget, self.ram_widget, self.storage_widget):
                item.hide()
        system_stats.prime_cpu()
        self._probe_gpu()
        QTimer.singleShot(self.FIRST_POLL_MS, self._first_update)

    def _first_update(self):
        self._update_stats()
        self._timer.start(self.POLL_MS)

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start(self.POLL_MS)
        if self._gpu_supported:
            self._gpu_timer.start(self.GPU_POLL_MS)

    def hideEvent(self, event):
        self._timer.stop()
        self._gpu_timer.stop()
        super().hideEvent(event)

    def _probe_gpu(self):
        if self._gpu_busy or not self._gpu_supported:
            return
        self._gpu_busy = True
        QThreadPool.globalInstance().start(_GpuProbeTask(self._gpu_signals))

    def _on_gpu_measured(self, payload):
        self._gpu_busy = False
        if payload is None:
            # Không có nguồn đo GPU thật nào trả lời: ẩn dòng, không vẽ tên card
            # hay tỉ lệ bịa.
            self._gpu_supported = False
            self._gpu = None
            self.gpu_widget.clear()
            self.gpu_widget.hide()
            self._gpu_timer.stop()
            self._update_temperatures()
            return
        self._gpu = payload
        self.gpu_widget.show()
        value = ""
        if payload.get("percent") is not None:
            value = "%d%%" % round(payload["percent"])
        self.gpu_widget.set_state(payload.get("percent"), value,
                                  payload.get("detail"))
        self._update_temperatures()

    def _update_stats(self):
        cpu = system_stats.read_cpu()
        if cpu is None:
            self.cpu_widget.clear()
            self.cpu_widget.hide()
        else:
            self.cpu_widget.show()
            self.cpu_widget.set_state(cpu["percent"], "%d%%" % round(cpu["percent"]),
                                      cpu["detail"])

        ram = system_stats.read_memory()
        if ram is None:
            self.ram_widget.clear()
            self.ram_widget.hide()
        else:
            self.ram_widget.show()
            self.ram_widget.set_state(ram["percent"], "%d%%" % round(ram["percent"]),
                                      ram["detail"])

        disk = system_stats.read_disk()
        if disk is None:
            self.storage_widget.clear()
            self.storage_widget.hide()
        else:
            self.storage_widget.show()
            self.storage_widget.set_state(disk["percent"], "%d%%" % round(disk["percent"]),
                                          disk["detail"])

        self._update_temperatures()

    def _update_temperatures(self):
        entries = list(system_stats.read_temperatures())
        gpu_temp = (self._gpu or {}).get("temp")
        if gpu_temp:
            entries.append(("GPU", float(gpu_temp)))
        if not entries:
            # Windows không có API đo nhiệt độ chung: thà ẩn dòng còn hơn giữ
            # một con số bịa.
            self.temp_widget.clear()
            self.temp_widget.hide()
            return
        self.temp_widget.show()
        hottest = max(entries, key=lambda entry: entry[1])
        self.temp_widget.set_state(
            min(100.0, hottest[1]),
            "%.0f°C" % hottest[1],
            sensors=[(name, "%.0f°C" % value) for name, value in entries],
        )
        self.temp_widget.value_label.setStyleSheet(
            "color: %s;" % _temp_color(hottest[1]))


# ── Recent Project Card ──────────────────────────────────────────

class RecentProjectCard(QFrame):
    clicked = Signal(str)
    renameRequested = Signal(str, str)
    deleteRequested = Signal(str)
    openEditorRequested = Signal(str)

    def __init__(self, project_path, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setObjectName("RecentProjectCard")
        self.setFixedSize(200, 180)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.thumb_container = QFrame()
        self.thumb_container.setObjectName("ThumbContainer")
        self.thumb_container.setFixedHeight(120)

        thumb_layout = QVBoxLayout(self.thumb_container)
        thumb_layout.setContentsMargins(8, 8, 8, 8)
        thumb_layout.setAlignment(Qt.AlignCenter)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setObjectName("ThumbLabel")
        # Bìa do cv2 giai ma frame, ton ~0,5 s va ~134 MB RSS mot lan nap thu vien.
        # Ke hoach ve ben trong card co dinh 200x180 nen cho nem den sau khi cua so
        # da len khong lam doi bo cuc; HomePage.xep-lop-linh-nhan lo tung card mot.
        self._set_cover_placeholder()
        thumb_layout.addWidget(self.thumb_label)

        main_layout.addWidget(self.thumb_container)

        info_widget = QWidget()
        info_widget.setObjectName("CardInfo")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(12, 8, 12, 10)
        info_layout.setSpacing(4)

        name = Path(project_path).stem
        name_label = QLabel(name)
        name_label.setObjectName("ProjectName")
        name_label.setAlignment(Qt.AlignLeft)
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)

        try:
            clinq_file = Path(project_path)
            if clinq_file.exists():
                mtime = os.path.getmtime(project_path)
                from datetime import datetime
                dt = datetime.fromtimestamp(mtime)
                time_str = dt.strftime("%d/%m/%Y %H:%M")
            else:
                time_str = ""
        except Exception:
            time_str = ""

        if time_str:
            time_label = QLabel(time_str)
            time_label.setObjectName("ProjectTime")
            info_layout.addWidget(time_label)

        main_layout.addWidget(info_widget)

    def _load_project_thumbnail(self):
        from PySide6.QtGui import QPixmap
        project_dir = Path(self.project_path).parent
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
        candidates = []

        # A project links to original media, so its cover cannot rely only on an
        # optional local Assets directory.
        for name in ("thumbnail.jpg", "thumbnail.png", "cover.jpg", "cover.png"):
            candidates.append(project_dir / name)
        try:
            with Path(self.project_path).open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            for asset in (data.get("assets") or {}).values():
                if isinstance(asset, dict) and asset.get("path"):
                    candidates.append(Path(asset["path"]))
            for track in (data.get("timeline") or {}).get("tracks", []):
                for clip in track.get("clips", []):
                    if clip.get("source_path"):
                        candidates.append(Path(clip["source_path"]))
        except (OSError, ValueError, TypeError):
            pass

        assets_dir = project_dir / "Assets"
        if assets_dir.exists():
            candidates.extend(sorted(p for p in assets_dir.iterdir() if p.is_file()))

        seen = set()
        for path in candidates:
            key = str(path).lower()
            if key in seen or not path.exists() or path.suffix.lower() not in image_extensions:
                continue
            seen.add(key)
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._set_cover_pixmap(pixmap)
                return

        for path in candidates:
            key = str(path).lower()
            if key in seen or not path.exists() or path.suffix.lower() not in video_extensions:
                continue
            seen.add(key)
            pixmap = self._cover_for_video(str(path), 100)
            if pixmap is not None and not pixmap.isNull():
                self._set_cover_pixmap(pixmap)
                return

        # Compatibility fallback for older projects whose paths were not saved.
        if assets_dir.exists():
            # 1. Tìm ảnh tĩnh trước
            image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif'}
            for f in sorted(assets_dir.iterdir()):
                if f.suffix.lower() in image_extensions:
                    pixmap = QPixmap(str(f))
                    if not pixmap.isNull():
                        thumb = pixmap.scaled(180, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.thumb_label.setPixmap(thumb)
                        return

            # 2. Trích xuất frame từ video đầu tiên
            video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv'}
            for f in sorted(assets_dir.iterdir()):
                if f.suffix.lower() in video_extensions:
                    pixmap = self._cover_for_video(str(f), 100)
                    if pixmap is not None and not pixmap.isNull():
                        thumb = pixmap.scaled(180, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.thumb_label.setPixmap(thumb)
                        return

        self._set_cover_placeholder()

    def _cover_for_video(self, video_path, target_height):
        """Ảnh bìa từ một file video, ưu tiên cache đĩa hơn là giải mã lại.

        Frame đầu của video luôn ra cùng một ảnh cho tới khi file nguồn đổi, nên
        nó đáng được cache như ảnh nhỡ thư viện: lần mở app sau chỉ việc đọc PNG,
        cv2 không phải nap nữa. Khoá do media_cache tính từ đường dẫn + mtime +
        kích thước, vì vậy sửa file nguồn tự động làm khoá hỏng chứ không trả bìa
        cũ.
        """
        from core import media_cache
        from core.media_extractor import extract_video_thumbnail
        try:
            key = media_cache.image_key(video_path, "project_cover", 0.0,
                                         184, target_height)
        except (OSError, ValueError):
            key = None
        image = media_cache.read_image(key)
        if not image.isNull():
            return QPixmap.fromImage(image)
        pixmap = extract_video_thumbnail(video_path, target_height)
        if pixmap is not None and not pixmap.isNull():
            media_cache.write_image(key, pixmap.toImage())
        return pixmap

    def _set_cover_placeholder(self):
        """Chrome của ô bìa khi chưa có ảnh — cũng là trạng thái 'hết nguồn'."""
        self.thumb_label.setFixedSize(184, 104)
        self.thumb_label.setText("")
        set_label_icon(self.thumb_label, "fa6s.file-video", 36, "#40E0D0")

    def _set_cover_pixmap(self, pixmap):
        """Fill the card cover while preserving the source aspect ratio."""
        cover = pixmap.scaled(184, 104, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (cover.width() - 184) // 2)
        y = max(0, (cover.height() - 104) // 2)
        self.thumb_label.setFixedSize(184, 104)
        self.thumb_label.setPixmap(cover.copy(x, y, 184, 104))

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setObjectName("ProjectContextMenu")

        open_action = menu.addAction(_qta().icon("fa6s.play", color="#40E0D0"), "  Mở trong trình sửa video")
        open_action.triggered.connect(lambda: self.openEditorRequested.emit(self.project_path))

        menu.addSeparator()

        rename_action = menu.addAction(_qta().icon("fa6s.pen", color="#E2E4E9"), "  Đổi tên")
        rename_action.triggered.connect(self._on_rename)

        menu.addSeparator()

        delete_action = menu.addAction(_qta().icon("fa6s.trash", color="#EF4444"), "  Xóa dự án")
        delete_action.triggered.connect(self._on_delete)

        menu.exec(self.mapToGlobal(pos))

    def _on_rename(self):
        current_name = Path(self.project_path).stem
        new_name, ok = CustomInputDialog.getText(
            self, "Đổi tên dự án", "Nhập tên mới cho dự án:", text=current_name
        )
        if ok and new_name and new_name != current_name:
            self.renameRequested.emit(self.project_path, new_name)

    def _on_delete(self):
        project_name = Path(self.project_path).stem
        reply = QMessageBox.question(
            self,
            "Xóa dự án",
            f"Bạn có chắc chắn muốn xóa dự án \"{project_name}\"?\n\n"
            f"Thư mục: {Path(self.project_path).parent}\n\n"
            f"Hành động này không thể hoàn tác.",
        )
        if reply:
            self.deleteRequested.emit(self.project_path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.project_path)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet("""
            RecentProjectCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1E1F2E, stop:1 #181924);
                border: 1.5px solid #40E0D0;
                border-radius: 12px;
            }
            #ThumbContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1A1B2E, stop:1 #14151C);
                border-radius: 12px 12px 0 0;
            }
            #ProjectName {
                color: #FFFFFF;
            }
        """)

    def leaveEvent(self, event):
        self.setStyleSheet("")


# ── Home Page ────────────────────────────────────────────────────

class HomePage(QWidget):
    createProject = Signal(str, str)  # project_name, clinq_file_path
    openProject = Signal(str)
    # Mot column = danh sách; luu thu tu moi theo chieu doc.
    RECENT_COLUMNS = {"grid": 4, "list": 1}
    SORT_LABELS = {"newest": "Mới nhất", "oldest": "Cũ nhất",
                   "name": "Tên A→Z"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.system_monitor = SystemMonitorWidget()
        main_layout.addWidget(self.system_monitor)

        content_widget = QWidget()
        content_widget.setObjectName("HomeContent")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(36, 28, 36, 28)
        content_layout.setSpacing(28)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        welcome_layout = QVBoxLayout()
        welcome_layout.setSpacing(4)
        welcome_title = QLabel("Chào mừng trở lại!")
        welcome_title.setObjectName("WelcomeTitle")
        welcome_layout.addWidget(welcome_title)
        welcome_desc = QLabel("Bạn đã sẵn sàng tạo nên điều tuyệt vời với hôm nay?")
        welcome_desc.setObjectName("WelcomeDesc")
        welcome_layout.addWidget(welcome_desc)
        header_layout.addLayout(welcome_layout)
        header_layout.addStretch(1)

        new_project_frame = QFrame()
        new_project_frame.setObjectName("NewProjectBtnFrame")
        new_project_layout = QHBoxLayout(new_project_frame)
        new_project_layout.setContentsMargins(0, 0, 0, 0)
        new_project_layout.setSpacing(0)
        new_project_btn = QPushButton("  Tạo dự án mới  ")
        new_project_btn.setObjectName("NewProjectBtn")
        new_project_btn.setIcon(_qta().icon("fa6s.plus", color="white"))
        new_project_btn.setCursor(Qt.PointingHandCursor)
        new_project_btn.clicked.connect(lambda: self._on_template_clicked("Dự án trống", (1920, 1080)))
        new_project_layout.addWidget(new_project_btn)
        header_layout.addWidget(new_project_frame)

        content_layout.addLayout(header_layout)

        templates_frame = QFrame()
        templates_frame.setObjectName("SectionFrame")
        templates_layout = QVBoxLayout(templates_frame)
        templates_layout.setContentsMargins(24, 20, 24, 20)
        templates_layout.setSpacing(18)

        section_header = QHBoxLayout()
        section_title = QLabel("Tạo dự án mới")
        section_title.setObjectName("SectionTitle")
        section_header.addWidget(section_title)
        section_header.addStretch(1)

        custom_size_btn = QPushButton("  Tùy chỉnh kích thước  ")
        custom_size_btn.setObjectName("CustomSizeBtn")
        custom_size_btn.setIcon(_qta().icon("fa6s.sliders", color="#40E0D0"))
        custom_size_btn.setCursor(Qt.PointingHandCursor)
        custom_size_btn.clicked.connect(self._on_custom_size)
        section_header.addWidget(custom_size_btn)
        templates_layout.addLayout(section_header)

        templates_grid = QHBoxLayout()
        templates_grid.setSpacing(14)

        templates = [
            ("Dự án trống", "fa6s.plus", (1920, 1080), "Bắt đầu từ một dự án trống"),
            ("Video dọc (9:16)", "fa6s.mobile-screen", (1080, 1920), "1080 x 1920 px"),
            ("Video ngang (16:9)", "fa6s.play", (1920, 1080), "1920 x 1080 px"),
            ("Video vuông (1:1)", "fa6s.square", (1080, 1080), "1080 x 1080 px"),
            ("Câu chuyện (4:5)", "fa6s.image", (1080, 1350), "1080 x 1350 px"),
            ("Nhập dự án", "fa6s.folder-open", (0, 0), "Từ tệp tin .clinq hoặc\ndự án backup"),
        ]

        for name, icon, res, desc in templates:
            card = ProjectTemplateCard(name, icon, res, desc)
            card.clicked.connect(self._on_template_clicked)
            templates_grid.addWidget(card)

        templates_layout.addLayout(templates_grid)
        content_layout.addWidget(templates_frame)

        recent_frame = QFrame()
        recent_frame.setObjectName("SectionFrame")
        recent_layout = QVBoxLayout(recent_frame)
        recent_layout.setContentsMargins(24, 20, 24, 20)
        recent_layout.setSpacing(18)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Dự án gần đây")
        recent_title.setObjectName("SectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)

        self._recent_view = "grid"
        self._recent_sort = "newest"
        self.btn_view_grid = QPushButton()
        self.btn_view_grid.setObjectName("ViewToggleBtn")
        self.btn_view_grid.setIcon(_qta().icon("fa6s.table-cells", color="#40E0D0"))
        self.btn_view_grid.setCursor(Qt.PointingHandCursor)
        self.btn_view_grid.setCheckable(True)
        self.btn_view_grid.setChecked(True)
        self.btn_view_grid.setToolTip("Xem dạng lưới")
        self.btn_view_grid.clicked.connect(lambda: self._set_recent_view("grid"))
        recent_header.addWidget(self.btn_view_grid)

        self.btn_view_list = QPushButton()
        self.btn_view_list.setObjectName("ViewToggleBtn")
        self.btn_view_list.setIcon(_qta().icon("fa6s.list", color="#6E7180"))
        self.btn_view_list.setCursor(Qt.PointingHandCursor)
        self.btn_view_list.setCheckable(True)
        self.btn_view_list.setToolTip("Xem dạng danh sách")
        self.btn_view_list.clicked.connect(lambda: self._set_recent_view("list"))
        recent_header.addWidget(self.btn_view_list)

        self.btn_sort = QPushButton("Sắp xếp: " + self.SORT_LABELS["newest"])
        self.btn_sort.setObjectName("SortLabel")
        self.btn_sort.setIcon(_qta().icon("fa6s.chevron-down", color="#8a8a92"))
        self.btn_sort.setCursor(Qt.PointingHandCursor)
        sort_menu = QMenu(self)
        self._sort_actions = {}
        for sort_key, sort_caption in self.SORT_LABELS.items():
            act = sort_menu.addAction(sort_caption)
            act.setCheckable(True)
            act.setChecked(sort_key == "newest")
            act.triggered.connect(lambda checked, k=sort_key: self._set_recent_sort(k))
            self._sort_actions[sort_key] = act
        self.btn_sort.setMenu(sort_menu)
        recent_header.addWidget(self.btn_sort)

        recent_layout.addLayout(recent_header)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("RecentScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.recent_container = QWidget()
        self.recent_container.setObjectName("RecentContainer")
        self.recent_grid = QGridLayout(self.recent_container)
        self.recent_grid.setSpacing(16)
        self.recent_grid.setContentsMargins(4, 4, 4, 4)

        self.empty_state = QWidget()
        self.empty_state.setObjectName("EmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(16)

        empty_icon = QLabel()
        empty_icon.setObjectName("EmptyIcon")
        empty_icon.setFixedSize(160, 140)
        empty_icon.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(160, 140)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Clapperboard body
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2A2C38"))
        painter.drawRoundedRect(30, 40, 100, 70, 8, 8)

        # Clapperboard top
        painter.setBrush(QColor("#3A3C48"))
        painter.drawRoundedRect(30, 30, 100, 20, 8, 8)

        # Diagonal stripes on clapperboard top
        painter.setPen(QColor("#40E0D0"))
        painter.setBrush(Qt.NoBrush)
        for i in range(5):
            x = 40 + i * 18
            painter.drawLine(x, 30, x + 12, 50)

        # Play triangle
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2C6E64"))
        painter.drawPolygon([QPoint(70, 60), QPoint(70, 95), QPoint(100, 77)])

        # Sparkles
        painter.setPen(QColor("#40E0D0"))
        painter.setBrush(QColor("#2C6E64"))
        # Top-left sparkle
        painter.drawEllipse(20, 20, 4, 4)
        # Top-right sparkle
        painter.drawEllipse(135, 25, 3, 3)
        # Bottom sparkle
        painter.drawEllipse(125, 100, 4, 4)
        # Small star
        painter.drawLine(15, 55, 20, 55)
        painter.drawLine(17.5, 52.5, 17.5, 57.5)

        painter.end()
        empty_icon.setPixmap(pixmap)
        empty_layout.addWidget(empty_icon, alignment=Qt.AlignHCenter)

        empty_title = QLabel("Chưa có dự án nào tại đây")
        empty_title.setObjectName("EmptyTitle")
        empty_layout.addWidget(empty_title)

        empty_desc = QLabel("Hãy tạo dự án mới để bắt đầu hành trình sáng tạo của bạn.")
        empty_desc.setObjectName("EmptyDesc")
        empty_layout.addWidget(empty_desc)

        create_btn = QPushButton("  Tạo dự án mới  ")
        create_btn.setObjectName("NewProjectBtn")
        create_btn.setIcon(_qta().icon("fa6s.plus", color="white"))
        create_btn.setCursor(Qt.PointingHandCursor)
        create_btn.clicked.connect(lambda: self._on_template_clicked("Dự án trống", (1920, 1080)))
        empty_layout.addWidget(create_btn, alignment=Qt.AlignHCenter)

        self.recent_grid.addWidget(self.empty_state, 0, 0, 1, 3)

        scroll_area.setWidget(self.recent_container)
        recent_layout.addWidget(scroll_area)

        content_layout.addWidget(recent_frame, 1)

        main_layout.addWidget(content_widget, 1)

        self._load_recent_projects()

    def _sorted_recent(self, paths):
        if self._recent_sort == "oldest":
            return list(reversed(paths))
        if self._recent_sort == "name":
            return sorted(paths, key=lambda p: Path(p).stem.lower())
        return list(paths)

    def _set_recent_view(self, mode):
        self._recent_view = mode
        grid_on = mode == "grid"
        self.btn_view_grid.setChecked(grid_on)
        self.btn_view_list.setChecked(not grid_on)
        self.btn_view_grid.setIcon(_qta().icon(
            "fa6s.table-cells", color="#40E0D0" if grid_on else "#6E7180"))
        self.btn_view_list.setIcon(_qta().icon(
            "fa6s.list", color="#40E0D0" if not grid_on else "#6E7180"))
        self._load_recent_projects()

    def _set_recent_sort(self, mode):
        self._recent_sort = mode
        self.btn_sort.setText("Sắp xếp: " + self.SORT_LABELS[mode])
        for key, act in self._sort_actions.items():
            act.setChecked(key == mode)
        self._load_recent_projects()

    @staticmethod
    def _parse_custom_size(text):
        import re
        match = re.fullmatch(r"\s*(\d{1,5})\s*[xX*×,]\s*(\d{1,5})\s*",
                             text or "")
        if not match:
            return None
        width, height = int(match.group(1)), int(match.group(2))
        if not (2 <= width <= 8000 and 2 <= height <= 8000):
            return None
        return width, height

    def _on_custom_size(self):
        text, ok = CustomInputDialog.getText(
            self, "Kích thước tùy chỉnh",
            "Khung vẽ theo dạng Rộng x Cao, ví dụ 1080x1920", "1920x1080")
        if not ok:
            return
        size = self._parse_custom_size(text)
        if size is None:
            QMessageBox.warning(
                self, "Kích thước không hợp lệ",
                "Nhập hai số cách nhau bởi x, mỗi cạnh từ 2 đến 8000 px.")
            return
        self._on_template_clicked("Tùy chỉnh", size)
    def _on_template_clicked(self, name, resolution):
        if name == "Nhập dự án":
            self._on_import_project()
            return
        project_name = f"Dự án {len(load_recent_projects()) + 1}"

        # Xác định aspect_ratio dựa trên resolution
        w, h = resolution
        if w > 0 and h > 0:
            ratio = w / h
            if abs(ratio - (16/9)) < 0.1:
                aspect_ratio = "16:9"
            elif abs(ratio - (9/16)) < 0.1:
                aspect_ratio = "9:16"
            elif abs(ratio - 1.0) < 0.1:
                aspect_ratio = "1:1"
            elif abs(ratio - (4/5)) < 0.1:
                aspect_ratio = "4:5"
            else:
                aspect_ratio = "16:9"
        else:
            aspect_ratio = "16:9"

        project_path = create_project_folder(
            project_name, resolution=resolution, aspect_ratio=aspect_ratio
        )
        clinq_file = str(project_path / f"{project_name}.clinq")
        projects = load_recent_projects()
        projects.insert(0, clinq_file)
        save_recent_projects(projects[:10])
        self.createProject.emit(project_name, clinq_file)

    def _on_import_project(self):
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Nhập dự án Clinging", "",
            "Clinging Project (*.clinq);;Tất cả tệp tin (*)"
        )
        if not file_path:
            return
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Lỗi", "File không tồn tại.")
            return
        # Thêm vào danh sách gần đây
        projects = load_recent_projects()
        if file_path not in projects:
            projects.insert(0, file_path)
            save_recent_projects(projects[:10])
        else:
            projects.remove(file_path)
            projects.insert(0, file_path)
            save_recent_projects(projects[:10])
        self.openProject.emit(file_path)

    def _load_recent_projects(self):
        for i in range(self.recent_grid.count()):
            item = self.recent_grid.itemAt(i)
            if item and item.widget() and item.widget() != self.empty_state:
                item.widget().deleteLater()

        # Card cu da bi xoa nen khong duoc con nam trong hang doi bia: mot luot
        # xep-lap-linh-nhan chay tren card da chet se nang RuntimeError.
        self._cover_queue = []

        recent = load_recent_projects()
        valid_projects = [p for p in recent if isinstance(p, str) and os.path.exists(p)]
        # Thu tu hien thi khong duoc nguoc lai file MRU:ghi van theo valid_projects.
        shown = self._sorted_recent(valid_projects)
        columns = self.RECENT_COLUMNS[self._recent_view]

        if valid_projects:
            self.empty_state.hide()
            for i, path in enumerate(shown[:8]):
                card = RecentProjectCard(path)
                card.clicked.connect(self.openProject.emit)
                card.renameRequested.connect(self._on_rename_project)
                card.deleteRequested.connect(self._on_delete_project)
                card.openEditorRequested.connect(self.openProject.emit)
                row, col = divmod(i, columns)
                self.recent_grid.addWidget(card, row, col)
                self._cover_queue.append(card)
        else:
            self.empty_state.show()

        # Day la duong DOC: no khong duoc ghi file nguoi dung. Tu truoc, dong
        # `save_recent_projects(valid_projects)` o day moi lan mo app da ghi lai
        # MRU va tinh xoa moi du an dang khong thay duoc duong dan (o roi chua
        # cam, thu muc vua doi ten) — mot lan "chi xem" mat mai danh sach.
        # Ghi van thuoc ve nhung hanh dong that su: tao/nhap/doi ten/xoa du an.
        self._schedule_cover_load()

    def _schedule_cover_load(self):
        if not hasattr(self, "_cover_timer"):
            self._cover_timer = QTimer(self)
            self._cover_timer.setSingleShot(True)
            self._cover_timer.timeout.connect(self._load_next_cover)
        if self._cover_queue and not self._cover_timer.isActive():
            self._cover_timer.start(0)

    def _load_next_cover(self):
        """Doc bia cho DUNG MOT card moi luot, sau khi cua so da ve xong.

        Gom ca 8 card vao một luot thi app van mo nhanh nhung dong trang cho
        den het luot do; tach ra the nay nhe va khong bao gio nam trong duong
        boot.
        """
        while self._cover_queue:
            card = self._cover_queue.pop(0)
            try:
                card._load_project_thumbnail()
            except RuntimeError:
                # Card bi xoa truoc khi kip (dong project, doi tieu chi sap xep).
                continue
            break
        self._schedule_cover_load()

    def _on_rename_project(self, old_path, new_name):
        old_dir = Path(old_path).parent
        new_dir = old_dir.parent / new_name
        new_clinq = new_dir / f"{new_name}.clinq"

        if new_dir.exists():
            QMessageBox.warning(self, "Lỗi", f"Thư mục \"{new_name}\" đã tồn tại.")
            return

        try:
            old_dir.rename(new_dir)
            if old_path != str(new_clinq):
                new_clinq_path = new_dir / f"{new_name}.clinq"
                if new_clinq_path.exists():
                    os.rename(new_clinq_path, new_clinq)
                for f in old_dir.glob(f"{old_dir.stem}.clinq"):
                    new_clinq_path = new_dir / f"{new_name}.clinq"
                    if f != new_clinq_path:
                        os.rename(f, new_clinq_path)
                        break

            projects = load_recent_projects()
            updated = []
            for p in projects:
                if p == old_path:
                    updated.append(str(new_clinq))
                else:
                    updated.append(p)
            save_recent_projects(updated)

            self._load_recent_projects()
            QMessageBox.information(self, "Thành công", f"Đã đổi tên dự án thành \"{new_name}\".")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể đổi tên: {str(e)}")

    def _on_delete_project(self, project_path):
        project_dir = Path(project_path).parent
        try:
            if project_dir.exists():
                shutil.rmtree(project_dir)

            projects = load_recent_projects()
            updated = [p for p in projects if p != project_path]
            save_recent_projects(updated)

            self._load_recent_projects()
            QMessageBox.information(self, "Thành công", "Đã xóa dự án.")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể xóa dự án: {str(e)}")
