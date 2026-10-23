"""
ui/preview_panel.py
Khu vực xem trước video (canvas): QGraphicsView + QGraphicsScene, zoom, kéo thả
tài nguyên, toolbar Fit/Fill nổi. Điều khiển phát nằm ở TimelineHeader.
"""

import time

from PySide6.QtCore import Qt, Signal, QSize, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QPen, QFont, QBrush, QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QFrame, QSizePolicy,
    QGraphicsScene, QGraphicsView, QGraphicsTextItem, QGraphicsPixmapItem
)

ASPECT_SIZES = {
    "16:9": (640, 360),
    "19:6": (760, 240),
    "9:16": (360, 640),
    "1:1":  (500, 500),
    "4:3":  (500, 375),
}



from ui.graphics_canvas_item import CanvasClipItem
from core.timeline_model import ClipModel
from core import canvas_layout, recap_overlay


class PreviewCanvas(QGraphicsView):
    """
    Canvas Trình phát — QGraphicsView kết hợp QGraphicsScene.
    Hỗ trợ: zoom (Ctrl+Scroll), drag items, selection, floating toolbar Fit/Fill.
    """
    resourceDropped = Signal(str, str, float, float)  # name, kind, scene_x, scene_y
    presetDropped = Signal(object, str, float, float)
    effectDropped = Signal(object, float, float)
    previewRequested = Signal(object, str)
    previewClearRequested = Signal()
    itemSelected = Signal(object)

    def __init__(self, parent=None):
        self.scene_obj = QGraphicsScene()
        super().__init__(self.scene_obj, parent)
        self.setObjectName("PreviewCanvas")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        # fitInView preserves the project ratio; a tall minimum only steals
        # space from the Timeline on common laptop screens.
        self.setMinimumSize(260, 240)

        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setStyleSheet(
            "background-color: #0D0E15; border: 1px solid #2A2C38; border-radius: 12px;"
        )

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)

        self._zoom_factor = 1.0
        self._current_ratio_key = "16:9"

        self._setup_scene("16:9")

        self._clip_items = {}
        self._model = None
        self._glass_cache = None
        self._glass_key = None
        self._glass_at = 0.0
        self._syncing = False
        self._selecting_from_timeline = False
        # Selection that the timeline last ASKED the canvas to show. Qt batches
        # selectionChanged into a zero-timer, so the report is delivered long
        # after any guard flag is back to False — this is what lets
        # main_window tell "the user clicked empty space" apart from "the
        # selected clip was merely hidden because it is off-playhead".
        self._expected_selection = []
        self._preview_item = None
        self._preview_transition = None
        self._drag_preview_key = None
        self._tool_preview_timer = QTimer(self)
        self._tool_preview_timer.setInterval(33)
        self._tool_preview_timer.timeout.connect(self._refresh_tool_preview)

        self.scene_obj.selectionChanged.connect(self._on_selection_changed)

    def _setup_scene(self, ratio_key):
        """Thiết lập scene rect + border cho tỷ lệ chỉ định."""
        from core.canvas_utils import ASPECT_RATIOS
        w, h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))
        self._current_ratio_key = ratio_key

        self.setSceneRect(-w / 2, -h / 2, w, h)

        if hasattr(self, "_border_rect") and self._border_rect in self.scene_obj.items():
            self.scene_obj.removeItem(self._border_rect)
        self._border_rect = self.scene_obj.addRect(
            -w / 2, -h / 2, w, h, QPen(QColor("#555555"), 2)
        )
        self._border_rect.setZValue(-100)

        if hasattr(self, "hint_item"):
            self.hint_item.setPos(-100, -20)

        self._zoom_factor = 1.0
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def update_aspect_ratio(self, ratio_string):
        """Gọi khi người dùng đổi tỉ lệ khung hình."""
        if "19:6" in ratio_string:
            key = "19:6"
        elif "16:9" in ratio_string:
            key = "16:9"
        elif "9:16" in ratio_string:
            key = "9:16"
        elif "1:1" in ratio_string:
            key = "1:1"
        else:
            key = "4:3"

        self._setup_scene(key)

    @staticmethod
    def _mime_payload(mime):
        """Return rich card metadata without reducing a preset to plain text."""
        import json
        try:
            if mime.hasFormat("application/x-clinqing-effect"):
                data = json.loads(bytes(mime.data(
                    "application/x-clinqing-effect")).decode("utf-8"))
                return data, "effect"
            if mime.hasFormat("application/x-clinqing-preset"):
                data = json.loads(bytes(mime.data(
                    "application/x-clinqing-preset")).decode("utf-8"))
                kind_data = mime.data("application/x-clinqing-kind")
                kind = bytes(kind_data).decode("utf-8") if kind_data else "text"
                return data, kind
        except (ValueError, UnicodeDecodeError, TypeError):
            pass
        return None, ""

    def _request_drag_preview(self, mime):
        data, kind = self._mime_payload(mime)
        if data is None:
            return
        key = (kind, data.get("name") or data.get("label"))
        if key != self._drag_preview_key:
            self._drag_preview_key = key
            self.previewRequested.emit(data, kind)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasText() and (mime.hasFormat("application/x-clinqing-kind") or
                               mime.hasFormat("application/x-clinqing-preset") or
                               mime.hasFormat("application/x-clinqing-effect")):
            self._request_drag_preview(mime)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self._request_drag_preview(event.mimeData())
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drag_preview_key = None
        self.previewClearRequested.emit()
        event.accept()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasText():
            event.ignore()
            return
        data, rich_kind = self._mime_payload(mime)
        scene_pos = self.mapToScene(event.position().toPoint())
        if data is not None and rich_kind == "effect":
            self.effectDropped.emit(data, scene_pos.x(), scene_pos.y())
            self._drag_preview_key = None
            event.acceptProposedAction()
            return
        if data is not None and rich_kind in ("text", "sticker"):
            self.presetDropped.emit(data, rich_kind, scene_pos.x(), scene_pos.y())
            self._drag_preview_key = None
            event.acceptProposedAction()
            return
        kind_data = mime.data("application/x-clinqing-kind")
        kind = bytes(kind_data).decode("utf-8") if kind_data else "video"
        name = mime.text()
        self.resourceDropped.emit(name, kind, scene_pos.x(), scene_pos.y())
        self._drag_preview_key = None
        event.acceptProposedAction()

    def clear_tool_preview(self):
        """Remove only temporary preview state; project clips remain untouched."""
        if self._preview_item is not None:
            if self._preview_item.scene() is self.scene_obj:
                self.scene_obj.removeItem(self._preview_item)
            self._preview_item = None
        if self._preview_transition is not None:
            # Nhả state xem thử để lần sync kế vẽ lại đúng chuyển tiếp đã áp.
            self._preview_transition[0].set_transition_state(None)
            self._preview_transition = None
        for item in self._clip_items.values():
            if hasattr(item, "_preview_effect"):
                item._preview_effect = None
                item.update()
        self._tool_preview_timer.stop()

    def _refresh_tool_preview(self):
        """Quét hết nhịp tiến độ khi đang xem thử hiệu ứng.

        Animation giờ tính theo p = local_time / duration, nên nếu giữ nguyên
        playhead thì người dùng chỉ thấy một khung tĩnh.
        """
        self._preview_sweep = (getattr(self, "_preview_sweep", 0.0) + 1.0 / 30.0) % 1.0
        if self._preview_transition is not None:
            self._preview_transition[0].set_transition_state(
                self._transition_preview_state(self._preview_sweep))
        for item in self._clip_items.values():
            if getattr(item, "_preview_effect", None) is None:
                continue
            item.set_local_time(self._preview_sweep * max(0.001, item.clip_model.duration))
            item.update()

    def _transition_preview_state(self, progress):
        """State xem thử tại một tiến độ — cùng hàm mà preview/export sẽ vẽ."""
        from core import transitions
        _, name, canvas_w, canvas_h = self._preview_transition
        if transitions.is_local(name):
            # Đang xem thử nên clip chưa mang duration nào; tiến độ của dải phai
            # lấy thẳng từ thanh quét, qua đúng hàm mà preview/export vẫn dùng.
            return transitions.local_state_at(name, progress)
        return transitions.incoming_state(name, progress, canvas_w, canvas_h)

    def preview_transition(self, clip_id, name, canvas_w, canvas_h, progress=0.5):
        """Xem thử chuyển tiếp trên một clip; không sửa ClipModel, không ripple.

        Cửa sổ thật của kiểu nối chỉ tồn tại sau khi áp (cần clip liền trước chồng
        lên), nên ở đây vẽ một mình clip bên vào tại tiến độ đang quét — đủ để
        người dùng phân biệt wipe với slide.
        """
        self.clear_tool_preview()
        item = self._clip_items.get(clip_id)
        if item is None or not hasattr(item, "set_transition_state"):
            return False
        from core import transitions
        if name not in transitions.TRANSITIONS:
            return False
        self._preview_transition = (item, name, canvas_w, canvas_h)
        item.set_transition_state(self._transition_preview_state(progress))
        self._tool_preview_timer.start()
        return True

    def preview_component(self, preset, kind):
        """Show a lightweight, non-persistent text/sticker preview at centre."""
        self.clear_tool_preview()
        label = preset.get("label", "Text" if kind == "text" else "Sticker")
        if kind == "text":
            item = QGraphicsTextItem(label)
            font = QFont(preset.get("font", "Arial"), int(preset.get("size", 40)))
            font.setBold(bool(preset.get("bold", False)))
            item.setDefaultTextColor(QColor(preset.get("color", "#FFFFFF")))
            item.setFont(font)
        else:
            from widgets.common import icon_pixmap
            pixmap = icon_pixmap(
                preset.get("icon", "fa6s.face-smile"), 180,
                preset.get("color", "#FFFFFF")
            )
            item = QGraphicsPixmapItem(pixmap)
        item.setOpacity(0.88)
        item.setZValue(10000)
        item.setAcceptedMouseButtons(Qt.NoButton)
        self.scene_obj.addItem(item)
        item.setPos(-item.boundingRect().width() / 2, -item.boundingRect().height() / 2)
        self._preview_item = item

    def preview_effect(self, clip_id, effect):
        """Attach an in-memory effect to one canvas item; never mutate ClipModel."""
        self.clear_tool_preview()
        item = self._clip_items.get(clip_id)
        if item is not None and hasattr(item, "_apply_effects"):
            item._preview_effect = effect
            item.update()
            from core import anim_engine
            from core.aura_paint import AURA_KEYS
            animated_keys = set(anim_engine.MOTION_KEYS) | set(AURA_KEYS) | {
                "shake", "float", "glitch", "cross_dissolve", "wipe_right",
            }
            if animated_keys.intersection(effect.params):
                self._tool_preview_timer.start()
            return True
        return False

    def bind_model(self, model):
        """Dán model vào canvas NGAY lúc nối dây, không chờ lần sync đầu.

        Dự án trống thì chẳng có clip nào để sync, mà lớp phủ recap là cấu
        hình dự án: nó phải hiện cả trên khung hình trống.
        """
        self._model = model
        self.viewport().update()

    def drawBackground(self, painter, rect):
        """Nen cua bo cuc cap du an — cung ham ma FrameComposer goi luc xuat.

        Scene khong co item nen: lop nen cua du an phai nam DUOI moi clip, nen
        no song o day chu khong the ve trong drawForeground nhu lop recap.
        """
        super().drawBackground(painter, rect)
        model = self._model
        if model is None:
            return
        settings = model.project_layout
        if not canvas_layout.layout_active(settings):
            return
        w, h = self._frame_size()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(-w / 2.0, -h / 2.0)
        canvas_layout.paint_background(painter, w, h, settings)
        painter.restore()

    def _frame_size(self) -> tuple:
        from core.canvas_utils import ASPECT_RATIOS
        return ASPECT_RATIOS.get(self._current_ratio_key, (1920, 1080))

    def drawForeground(self, painter, rect):
        """Vẽ khung/o/chữ của bố cục rồi tới lớp phủ recap, bằng đúng các hàm
        mà bản xuất gọi — thứ tự lop phai giong FrameComposer: clip -> bo cuc
        -> recap."""
        model = self._model
        if model is None:
            return
        w, h = self._frame_size()
        layout = model.project_layout
        if canvas_layout.layout_active(layout):
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            # Painter vào đây đã ở tọa độ scene (gốc giữa khung); canvas_layout
            # vẽ theo hệ góc trên trái w×h, nên tịnh tiến một lần là đủ đúng vị
            # trí khi zoom/fit đổi tỉ lệ.
            painter.translate(-w / 2.0, -h / 2.0)
            canvas_layout.paint_foreground(painter, w, h, layout,
                                           float(model.playhead))
            painter.restore()
        settings = model.recap_overlay
        if not recap_overlay.overlay_active(settings):
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Recap ve sau bo cuc vi no la chrome cua ban ghi hinh, khong phai
        # mot phan cua khung thiet ke.
        painter.translate(-w / 2.0, -h / 2.0)
        # Painter vào đây đã ở tọa độ scene (gốc giữa khung); recap_overlay vẽ
        # theo hệ góc trên trái w×h, nên tịnh tiến một lần là đủ đúng vị trí
        # khi zoom/fit đổi tỉ lệ.
        painter.translate(-w / 2.0, -h / 2.0)
        if settings["glass"]:
            content = self._grab_scene_content(w, h)
            if content is not None:
                recap_overlay.paint_backdrop(painter, w, h, content, settings)
                painter.drawImage(recap_overlay.content_rect(w, h, settings), content)
        recap_overlay.paint_overlay(
            painter, w, h, settings, float(model.playhead),
            recap_overlay.resolution_label(w, h, settings))
        painter.restore()

    def _grab_scene_content(self, w, h):
        """Chụp scene để làm nguồn nền kính mờ; cache 0.1s theo (playhead, số item)."""
        key = (round(float(self._model.playhead), 3), len(self._clip_items))
        now = time.monotonic()
        if self._glass_cache is not None and self._glass_key == key and now - self._glass_at < 0.1:
            return self._glass_cache
        target_w = min(768, int(w))
        target_h = max(1, int(round(target_w * float(h) / max(1.0, float(w)))))
        image = QImage(target_w, target_h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#000000"))
        # Border xám + hint "kéo thả" là chrome riêng của Canvas; chúng lọt vào
        # ảnh chụp thì nền kính mờ sẽ loang cả viền ra toàn khung.
        chrome = []
        for name in ("_border_rect", "hint_item"):
            item = getattr(self, name, None)
            if item is not None and item.isVisible():
                item.setVisible(False)
                chrome.append(item)
        painter = QPainter(image)
        try:
            self.scene_obj.render(
                painter, QRectF(0, 0, target_w, target_h),
                QRectF(-w / 2.0, -h / 2.0, w, h))
        finally:
            painter.end()
            for item in chrome:
                item.setVisible(True)
        self._glass_cache = image
        self._glass_key = key
        self._glass_at = now
        return image

    def wheelEvent(self, event: QWheelEvent):
        """Zoom bằng Ctrl + Scroll."""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.1 if delta > 0 else 0.9
            new_zoom = self._zoom_factor * factor
            new_zoom = max(0.2, min(new_zoom, 5.0))
            scale_factor = new_zoom / self._zoom_factor
            self.scale(scale_factor, scale_factor)
            self._zoom_factor = new_zoom
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._zoom_factor == 1.0:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def _on_selection_changed(self):
        if self._syncing or self._selecting_from_timeline:
            return
        selected_items = self.scene_obj.selectedItems()
        if selected_items:
            item = selected_items[0]
            self.itemSelected.emit(item)
        else:
            self.itemSelected.emit(None)

    def sync_scene_from_model(self, model, on_transform_callback,
                              on_edit_commit=None):
        """Đồng bộ toàn bộ clip từ TimelineModel lên Canvas."""
        self._model = model
        self._syncing = True
        try:
            for item in list(self._clip_items.values()):
                self.scene_obj.removeItem(item)
            self._clip_items.clear()

            for track in model.tracks:
                z_value = track.z_index

                for clip in track.clips:
                    if clip.media_type == "audio":
                        continue

                    if clip.media_type == "text":
                        from ui.graphics_canvas_item import TextClipItem
                        canvas_item = TextClipItem(
                            clip, on_transform_callback, on_edit_commit)
                    else:
                        from ui.graphics_canvas_item import CanvasClipItem
                        canvas_item = CanvasClipItem(
                            clip, on_transform_callback, on_edit_commit)

                    canvas_item.setZValue(z_value)
                    self.scene_obj.addItem(canvas_item)
                    self._clip_items[clip.clip_id] = canvas_item

            if hasattr(self, "hint_item"):
                self.hint_item.setVisible(len(self._clip_items) == 0)

            # Rebuild replaces every item, and QGraphicsScene delivers
            # selectionChanged on a zero-timer — i.e. AFTER this method
            # returns. Without re-asserting the selection here, that stale
            # event finds nothing selected and deselect_all() blanks the
            # properties panel one beat after every clip click.
            for clip_id in model.selected_clip_ids:
                item = self._clip_items.get(clip_id)
                if item is not None:
                    item.setSelected(True)
        finally:
            self._syncing = False

    def update_rendering_order(self, model):
        """Map hàng Timeline sang zValue mà không tạo lại Canvas item.

        Track UI index 0 luôn là lớp ngoài cùng. Hàm này được
        gọi sau Add/Delete/Swap track và sau khi clip đổi track.
        """
        total = len(model.tracks)
        for track_index, track in enumerate(model.tracks):
            z_value = float(total - track_index)
            track.z_index = int(z_value)
            for clip in track.clips:
                canvas_item = self._clip_items.get(clip.clip_id)
                if canvas_item is not None:
                    canvas_item.setZValue(z_value)
        self.scene_obj.update()


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreviewPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(0)

        self.canvas = PreviewCanvas()
        outer.addWidget(self.canvas, 1)
