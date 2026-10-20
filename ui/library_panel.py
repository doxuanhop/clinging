"""
ui/library_panel.py
Panel "THƯ VIỆN TÀI NGUYÊN": tab Tất cả/Video/Âm thanh/Hình ảnh/Sticker/Hiệu ứng,
ô tìm kiếm có icon kính lúp, trạng thái rỗng "Thư viện đang trống",
lưới thẻ tài nguyên (kéo được sang canvas/timeline).
Dùng Font Awesome 6 Solid icons (prefix: fa6s).
"""

import os
from PySide6.QtCore import (
    Qt, QMimeData, Signal, QEvent, QSize, QObject, QRunnable, QThreadPool
)
from PySide6.QtGui import QDrag, QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QToolButton, QPushButton, QScrollArea, QFrame, QFileDialog,
    QStackedWidget, QSizePolicy, QMenu
)

from widgets.common import AnimatedTabBar, add_shadow, set_label_icon, IconButton, _qta, icon_color, font_icon

TABS = ["Tất cả", "Video", "Âm thanh", "Hình ảnh"]

FILE_ICONS = {
    "video": "fa6s.film",
    "audio": "fa6s.music",
    "image": "fa6s.image",
}

# Loại tài nguyên suy từ phần mở rộng: tab "Tất cả" không được phép gán nhầm
# một tấm ảnh thành video.
EXT_KIND = {
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".webm": "video", ".flv": "video", ".wmv": "video", ".m4v": "video",
    ".mp3": "audio", ".wav": "audio", ".aac": "audio", ".m4a": "audio",
    ".flac": "audio", ".ogg": "audio", ".opus": "audio",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image", ".tif": "image", ".tiff": "image",
}

# Tab 0 lọc theo "Tất cả" nên không ép loại khi thêm tệp.
TAB_TO_KIND = {0: None, 1: "video", 2: "audio", 3: "image"}
TAB_TO_FILTER = {
    0: "Tất cả tệp (*.*)",
    1: "Video (*.mp4 *.mov *.avi *.mkv)",
    2: "Âm thanh (*.mp3 *.wav *.aac)",
    3: "Hình ảnh (*.png *.jpg *.jpeg)",
}
TAB_TO_PLACEHOLDER = {
    0: "Tìm kiếm tài nguyên...",
    1: "Tìm kiếm video...",
    2: "Tìm kiếm âm thanh...",
    3: "Tìm kiếm hình ảnh...",
}


def kind_for_path(path, default="video"):
    return EXT_KIND.get(os.path.splitext(path)[1].lower(), default)


def decode_thumb_image(path, kind, max_width=320):
    """Khung hình đại diện cho card thư viện. Chạy ở nền nên chỉ trả QImage
    (QPixmap bắt buộc tạo trên thread GUI), và phải .copy() để không giữ buffer
    numpy.

    Video được thu nhỏ về <= ``max_width`` ngay ở bước giải mã: card hiển thị
    116x76 nên giữ nguyên khung 1280x720 chỉ để rồi scale là lãng phí, và ảnh
    đã thu nhỏ mới là thứ đáng lưu vào cache đĩa (~414 ms một lượt giải mã trên
    HDD máy yếu — scratch/perf_baseline.json). Ảnh tĩnh KHÔNG cache: đọc PNG/JPG
    nhanh hơn cả vòng ghi/đọc cache.
    """
    from core import media_cache

    if kind == "image":
        img = QImage(path)
        return img
    if kind == "video":
        key = media_cache.image_key(path, "lib", 0.0, max_width, 0)
        if key:
            cached = media_cache.read_image(key)
            if not cached.isNull():
                return cached
        image = _decode_first_frame(path)
        if not image.isNull():
            if image.width() > max_width:
                image = image.scaledToWidth(max_width, Qt.SmoothTransformation)
            if key:
                media_cache.write_image(key, image)
        return image
    return QImage()


def _decode_first_frame(path):
    try:
        import cv2
        import numpy as np
        cap = cv2.VideoCapture(path)
        try:
            ret, frame = (cap.read() if cap.isOpened() else (False, None))
        finally:
            cap.release()
        if ret and frame is not None:
            rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            h, w, ch = rgb.shape
            return QImage(rgb.data, w, h, ch * w,
                          QImage.Format.Format_RGB888).copy()
    except Exception:
        return QImage()
    return QImage()


class _ThumbReady(QObject):
    image = Signal(QImage)


class _ThumbTask(QRunnable):
    """Card giữ tham chiếu tới task nên _ThumbReady luôn sống đủ lâu để emit;
    nếu card bị huỷ trước thì Qt tự ngắt kết nối slot thuộc card."""

    def __init__(self, path, kind):
        super().__init__()
        self.path = path
        self.kind = kind
        self.ready = _ThumbReady()

    def run(self):
        self.ready.image.emit(decode_thumb_image(self.path, self.kind))


_POOL = None


def thumb_pool():
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(3)
    return _POOL


class SearchField(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchBox")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        icon = QLabel()
        set_label_icon(icon, "fa6s.magnifying-glass", 14, icon_color())
        icon.setObjectName("SearchIcon")
        self.input = QLineEdit()
        self.input.setObjectName("SearchInput")
        self.input.setFrame(False)
        self.input.installEventFilter(self)
        self.setProperty("focused", False)

        layout.addWidget(icon)
        layout.addWidget(self.input, 1)

    def eventFilter(self, obj, event):
        if obj is self.input:
            if event.type() == QEvent.FocusIn:
                self._set_focused(True)
            elif event.type() == QEvent.FocusOut:
                self._set_focused(False)
        return super().eventFilter(obj, event)

    def _set_focused(self, value):
        self.setProperty("focused", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def setPlaceholderText(self, text):
        self.input.setPlaceholderText(text)


class ResourceCard(QFrame):
    thumbnailsRequested = Signal(str)
    splitRequested = Signal(str)

    def __init__(self, filename, kind="video", full_path="", parent=None):
        super().__init__(parent)
        self.filename = filename
        self.full_path = full_path
        self.kind = kind
        self.setObjectName("ResourceCard")
        self.setFixedSize(145, 145)
        self.setCursor(Qt.OpenHandCursor)
        self._drag_start = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        # Thumbnail container
        self.thumb_container = QLabel()
        self.thumb_container.setObjectName("ResourceCardIcon")
        self.thumb_container.setAlignment(Qt.AlignCenter)
        self.thumb_container.setFixedSize(120, 80)
        self.thumb_container.setStyleSheet("""
            QLabel {
                background-color: #1A1B22;
                border: 1px solid #2A2C38;
                border-radius: 6px;
            }
        """)
        
        # Tạo thumbnail ngầm
        self._load_thumbnail()

        name = QLabel(filename)
        name.setObjectName("ResourceCardLabel")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        name.setMaximumHeight(30)

        layout.addWidget(self.thumb_container, alignment=Qt.AlignHCenter)
        layout.addWidget(name)

    def _load_thumbnail(self):
        """Icon hiện ngay, khung hình thật nạp ở nền rồi thay vào sau.

        Giải mã video đồng bộ từng làm cứng toàn bộ UI khi thư viện có vài chục
        tệp — mỗi cv2.VideoCapture mất hàng trăm mili giây trên thread GUI.
        """
        set_label_icon(self.thumb_container,
                       FILE_ICONS.get(self.kind, "fa6s.file"), 32, icon_color())
        if self.kind not in ("image", "video"):
            return
        if not self.full_path or not os.path.isfile(self.full_path):
            return
        task = _ThumbTask(self.full_path, self.kind)
        self._thumb_task = task
        task.ready.image.connect(self._apply_thumb)
        thumb_pool().start(task)

    def _apply_thumb(self, image):
        if image.isNull():
            return
        thumb = QPixmap.fromImage(image).scaled(
            116, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_container.setPixmap(thumb)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._drag_start is None:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 5:
            return

        drag = QDrag(self)
        mime = QMimeData()
        path_to_send = self.full_path if self.full_path else self.filename
        mime.setText(path_to_send)
        mime.setData("application/x-clinqing-kind", self.kind.encode())

        # Tạo drag pixmap với thumbnail nhỏ
        pixmap = self.thumb_container.pixmap()
        if pixmap and not pixmap.isNull():
            drag_pixmap = pixmap.scaled(64, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            from PySide6.QtGui import QPixmap, QPainter, QColor
            drag_pixmap = QPixmap(64, 48)
            drag_pixmap.fill(QColor("#1A1B22"))
            p = QPainter(drag_pixmap)
            p.setPen(QColor("#7C5CFF"))
            p.drawText(drag_pixmap.rect(), Qt.AlignCenter, self.kind[:4].upper())
            p.end()

        drag.setMimeData(mime)
        drag.setPixmap(drag_pixmap)
        drag.setHotSpot(drag_pixmap.rect().center())
        drag.exec(Qt.CopyAction)

    def context_menu(self):
        """Menu cho card nay, hoac None khi khong ap dung duoc.

        Tam bout thanh ham rieng vi QMenu.exec() mo vong loop modal khong the
        monkeypatch trong probe — giu nguyen duong that (menu + hanh dong cua
        no) nhung van do duoc cai ma no sinh ra.
        """
        if not self.full_path or not os.path.isfile(self.full_path):
            return None
        menu = QMenu(self)
        if self.kind == "video":
            action = menu.addAction(font_icon("fa6s.images"),
                                    "Trích xuất ảnh thu nhỏ…")
            action.triggered.connect(
                lambda _checked=False:
                self.thumbnailsRequested.emit(self.full_path))
        if self.kind in ("video", "audio"):
            action = menu.addAction(font_icon("fa6s.scissors"),
                                    "Cắt thành nhiều đoạn…")
            action.triggered.connect(
                lambda _checked=False: self.splitRequested.emit(self.full_path))
        if not menu.actions():
            return None
        return menu

    def contextMenuEvent(self, event):
        """Menu chuột phải chỉ mở với video và audio.

        Moi hanh dong o day deu sinh ra HANG LOT file tu mot chuoi, nen voi anh
        tinh (da la mot anh san, khong co dai thoi gian) mot menu rong con gay
        ngo hon la khong co gi.
        """
        menu = self.context_menu()
        if menu is None:
            return super().contextMenuEvent(event)
        menu.exec(event.globalPos())


class UploadCard(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UploadCard")
        self.setFixedSize(145, 145)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel()
        set_label_icon(icon, "fa6s.plus", 22, icon_color())
        layout.addWidget(icon, alignment=Qt.AlignHCenter)

        label = QLabel("Tải lên tài nguyên")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size:11px;")
        layout.addWidget(label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class LibraryEmptyState(QWidget):
    uploadClicked = Signal()
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setObjectName("LibFolderIcon")
        icon.setAlignment(Qt.AlignCenter)
        set_label_icon(icon, "fa6s.folder-open", 48, icon_color())

        title = QLabel("Thư viện đang trống")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: 600;")

        desc = QLabel("Kéo và thả tệp vào đây\nhoặc nhấn nút bên dưới")
        desc.setObjectName("EmptyDesc")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 11px; color: #6E7180;")

        upload_btn = QPushButton("  Tải tệp lên")
        upload_btn.setObjectName("PrimaryPillButton")
        upload_btn.setIcon(_qta().icon("fa6s.upload", color=icon_color()))
        upload_btn.setCursor(Qt.PointingHandCursor)
        upload_btn.setFixedHeight(34)
        upload_btn.clicked.connect(self.uploadClicked.emit)
        add_shadow(upload_btn, blur=15, offset=(0, 3))

        layout.addWidget(icon, alignment=Qt.AlignHCenter)
        layout.addSpacing(2)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(10)
        layout.addWidget(upload_btn, alignment=Qt.AlignHCenter)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        self.uploadClicked.emit()
        event.acceptProposedAction()


class LibraryPanel(QWidget):
    resourcesChanged = Signal(list)
    thumbnailExportRequested = Signal(str)
    mediaSplitRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryPanel")
        self.setFixedWidth(360)
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(14)

        title = QLabel("THƯ VIỆN TÀI NGUYÊN")
        title.setObjectName("PanelTitle")
        outer.addWidget(title)

        self.tabs = AnimatedTabBar(TABS, spacing=13)
        outer.addWidget(self.tabs)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_box = SearchField()
        self.filter_btn = QToolButton()
        self.filter_btn.setObjectName("FilterBtn")
        self.filter_btn.setIcon(_qta().icon("fa6s.sliders", color=icon_color()))
        self.filter_btn.setIconSize(QSize(14, 14))
        self.filter_btn.setFixedSize(38, 38)
        self.filter_btn.setCursor(Qt.PointingHandCursor)
        self.filter_btn.setToolTip("Lọc tài nguyên")
        self.filter_btn.setPopupMode(QToolButton.InstantPopup)
        self.filter_btn.setMenu(self._build_filter_menu())
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(self.filter_btn)
        outer.addLayout(search_row)

        self.stack = QStackedWidget()

        self.empty_state = LibraryEmptyState()
        self.empty_state.uploadClicked.connect(self._open_file_dialog)
        self.empty_state.filesDropped.connect(self.add_files)
        self.stack.addWidget(self.empty_state)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 6, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._items = []
        self._cols = 2
        self.no_match_label = QLabel("Không có tài nguyên nào khớp bộ lọc")
        self.no_match_label.setObjectName("EmptyTitle")
        self.no_match_label.setAlignment(Qt.AlignCenter)
        self.no_match_label.setStyleSheet("font-size: 12px; color: #6E7180; padding: 18px 0;")
        self.no_match_label.hide()
        self.grid.addWidget(self.no_match_label, 0, 0, 1, self._cols)
        self.scroll.setWidget(self.grid_host)
        self.stack.addWidget(self.scroll)

        outer.addWidget(self.stack, 1)

        self._kind_filter = None
        self._hide_missing = False
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.search_box.input.textChanged.connect(self._apply_filter)
        self.search_box.setPlaceholderText(TAB_TO_PLACEHOLDER[0])
        self._apply_filter()

    def _build_filter_menu(self):
        menu = QMenu(self)
        self._kind_actions = {}
        for label, kind in (("Tất cả", None), ("Video", "video"),
                            ("Âm thanh", "audio"), ("Hình ảnh", "image")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(kind is None)
            act.triggered.connect(lambda checked, k=kind: self._set_kind_filter(k))
            self._kind_actions[kind] = act
        menu.addSeparator()
        hide_missing = menu.addAction("Ẩn tệp không còn trên đĩa")
        hide_missing.setCheckable(True)
        hide_missing.toggled.connect(self._set_hide_missing)
        self._hide_missing_action = hide_missing
        return menu

    def _set_kind_filter(self, kind):
        self._kind_filter = kind
        for value, act in self._kind_actions.items():
            act.setChecked(value == kind)
        self._apply_filter()

    def _set_hide_missing(self, checked):
        self._hide_missing = bool(checked)
        self._apply_filter()

    def _matches(self, card):
        if self._kind_filter and card.kind != self._kind_filter:
            return False
        term = self.search_box.input.text().strip().lower()
        if term and term not in card.filename.lower():
            return False
        if self._hide_missing and (not card.full_path or not os.path.exists(card.full_path)):
            return False
        return True

    def _apply_filter(self):
        """Ẩn/hiện thẻ rồi xếp lại lưới — tab, ô tìm kiếm và nút lọc cùng một đường."""
        upload_card = self._items[0] if self._items else None
        for widget in self._items:
            self.grid.removeWidget(widget)
            widget.hide()
        shown = []
        if upload_card is not None:
            shown.append(upload_card)
        shown += [c for c in self._items[1:]
                  if isinstance(c, ResourceCard) and self._matches(c)]
        for i, widget in enumerate(shown):
            r, c = divmod(i, self._cols)
            self.grid.addWidget(widget, r, c)
            widget.show()
        # Nhãn "không khớp" phải nằm dưới hàng thẻ cuối, không đè lên UploadCard
        # vì QGridLayout cho phép hai widget dùng chung một ô.
        self.grid.removeWidget(self.no_match_label)
        has_resources = any(isinstance(c, ResourceCard) for c in self._items)
        empty_result = has_resources and len(shown) <= 1
        if empty_result:
            rows = -(-len(shown) // self._cols)
            self.grid.addWidget(self.no_match_label, rows, 0, 1, self._cols)
        self.no_match_label.setVisible(empty_result)
        self.stack.setCurrentIndex(1 if has_resources else 0)

    def _open_file_dialog(self):
        idx = self.tabs.group.checkedId()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn tệp", "", TAB_TO_FILTER.get(idx, "Tất cả tệp (*.*)")
        )
        self.add_files(paths)

    def add_files(self, paths):
        """Thêm tệp từ hộp thoại hoặc kéo-thả; loại suy từ phần mở rộng."""
        added = 0
        for path in paths:
            if not path or not os.path.isfile(path):
                continue
            before = len(self._items)
            # Không ép loại theo tab đang chọn: một tấm ảnh bị gắn nhãn "video"
            # sẽ hiện sai thumbnail và hỏng ở timeline.
            self.add_resource(os.path.basename(path), kind_for_path(path), path)
            if len(self._items) > before:
                added += 1
        # isHidden() chỉ đúng cho thẻ bị chính bộ lọc ẩn, khác với isVisible()
        # (False cả khi cả panel đang bị sidebar ẩn).
        card = self._items[-1] if self._items else None
        if added and isinstance(card, ResourceCard) and card.isHidden():
            self._select_tab(0)
        return added

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([u.toLocalFile() for u in event.mimeData().urls()])
        event.acceptProposedAction()

    def add_resource(self, filename, kind="video", full_path="", emit_change=True):
        normalized = os.path.normcase(os.path.abspath(full_path)) if full_path else ""
        for item in self._items:
            if isinstance(item, ResourceCard):
                existing = os.path.normcase(os.path.abspath(item.full_path)) if item.full_path else ""
                if normalized and existing == normalized:
                    return item
        if not self._items:
            self._items.append(self._make_upload_card())
        card = ResourceCard(filename, kind, full_path)
        card.thumbnailsRequested.connect(self.thumbnailExportRequested.emit)
        card.splitRequested.connect(self.mediaSplitRequested.emit)
        self._items.append(card)
        self._apply_filter()
        if emit_change:
            self.resourcesChanged.emit(self.resource_records())
        return card

    def resource_records(self):
        return [{"name": item.filename, "path": item.full_path, "type": item.kind}
                for item in self._items if isinstance(item, ResourceCard)]

    def clear_resources(self, emit_change=True):
        for item in self._items:
            self.grid.removeWidget(item)
            item.deleteLater()
        self._items = []
        self.no_match_label.hide()
        self.stack.setCurrentIndex(0)
        if emit_change:
            self.resourcesChanged.emit([])

    def restore_resources(self, assets):
        """Re-create media cards after the project UI has been initialized."""
        self.clear_resources(emit_change=False)
        records = assets.values() if isinstance(assets, dict) else (assets or [])
        for asset in records:
            path = asset.get("path") or asset.get("source_path") or ""
            kind = asset.get("type") or asset.get("media_type") or "video"
            if path and kind in ("video", "audio", "image"):
                self.add_resource(asset.get("name") or os.path.basename(path), kind,
                                  path, emit_change=False)
        self.resourcesChanged.emit(self.resource_records())

    def _make_upload_card(self):
        card = UploadCard()
        card.clicked.connect(self._open_file_dialog)
        return card

    def _select_tab(self, idx):
        """Chọn tab từ code: setCurrentIndex không phát signal nên phải tự đồng bộ
        bộ lọc và placeholder, nếu không gạch chân và danh sách sẽ lệch nhau."""
        self.tabs.setCurrentIndex(idx)
        self._on_tab_changed(idx)

    def _on_tab_changed(self, idx):
        self.search_box.setPlaceholderText(TAB_TO_PLACEHOLDER.get(idx, "Tìm kiếm tài nguyên..."))
        # Tab là một bộ lọc: chọn "Video" phải ẩn hết ảnh và âm thanh.
        self._set_kind_filter(TAB_TO_KIND.get(idx))
