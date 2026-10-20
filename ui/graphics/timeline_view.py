"""
ui/graphics/timeline_view.py
QGraphicsView viewport controller — Dirty Rectangle Rendering,
Double Buffering, Ctrl+Scroll Zoom, Scroll Pan.

Tối ưu hiệu năng:
    - MinimalViewportUpdate  → chỉ repaint vùng thay đổi
    - DontSavePainterState   → giảm overhead QPainter
    - DontAdjustForAntialiasing → tránh tính toán thừa
    - CacheBackground        → cache ruler/grid
    - Antialiasing + SmoothPixmapTransform → vẽ mượt
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QTransform
from PySide6.QtWidgets import QGraphicsView

from ui.graphics.timeline_scene import TimelineScene
from core.time_mapper import TimePixelMapper


class TimelineView(QGraphicsView):
    """
    Viewport controller cho Timeline Scene.

    Features:
        - Dirty Rectangle Rendering (MinimalViewportUpdate)
        - Double Buffering (built-in QGraphicsView)
        - Ctrl + Mouse Wheel → Zoom in/out
        - Mouse Wheel (no modifier) → Cuộn ngang
        - Shift + Mouse Wheel → Cuộn dọc
        - Middle mouse drag → Pan
    """

    def __init__(self, scene: TimelineScene, mapper: TimePixelMapper,
                 parent=None):
        super().__init__(scene, parent)
        self._mapper = mapper
        self._scene = scene

        self.setObjectName("TimelineView")

        # ── Optimization Flags ──
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlags(
            QGraphicsView.DontSavePainterState |
            QGraphicsView.DontAdjustForAntialiasing
        )
        self.setRenderHints(
            QPainter.Antialiasing |
            QPainter.SmoothPixmapTransform
        )
        self.setCacheMode(QGraphicsView.CacheBackground)

        # ── Scroll bars ──
        # Invisible scrollbars keep the whole viewport available to clips.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._vertical_scroll_enabled = False

        # ── Interaction ──
        # Kéo trên vùng trống để quét chọn nhiều clip như các NLE chuyên nghiệp.
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # Zoom is represented only by TimePixelMapper on X. Keep the actual
        # QGraphicsView transform at 1:1 so row heights never scale.
        self.setTransform(QTransform())
        self._mapper.zoomChanged.connect(self._on_mapper_zoom_changed)

        # Accept drops
        self.setAcceptDrops(True)

        # ── Style ──
        self.setStyleSheet("""
            QGraphicsView {
                background-color: #0B0C10;
                border: none;
                border-top: 1px solid #1C1E27;
            }
            QScrollBar:horizontal {
                height: 10px;
                background: #0D0E14;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: #2A2C38;
                border-radius: 5px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #3A3D4E;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar:vertical {
                width: 10px;
                background: #0D0E14;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #2A2C38;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3A3D4E;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _on_mapper_zoom_changed(self, _px_per_sec: float):
        """Discard only view caches; geometry is rebuilt by TimelineScene."""
        # CacheBackground otherwise keeps ruler fragments rendered at the old
        # scale when zoom comes from the toolbar slider rather than Ctrl+wheel.
        self.resetCachedContent()
        self.viewport().update()

    # ── Wheel Event (Zoom + Scroll) ─────────────────────────────

    def set_vertical_scroll_enabled(self, enabled: bool):
        """Enable row scrolling only once the project has 3+ tracks."""
        self._vertical_scroll_enabled = bool(enabled)
        if not self._vertical_scroll_enabled:
            self.verticalScrollBar().setValue(0)

    def wheelEvent(self, event):
        """
        Ctrl + Scroll  → Zoom in/out (thay đổi px_per_sec)
        Scroll (plain) → Cuộn dọc
        Shift + Scroll → Cuộn ngang
        """
        delta = event.angleDelta().y()

        if event.modifiers() & Qt.ControlModifier:
            # Mapper thay đổi geometry thật của item (không dùng view transform),
            # vì vậy tự giữ nguyên mốc thời gian đang nằm dưới chuột.
            viewport_pos = event.position().toPoint()
            old_scene_pos = self.mapToScene(viewport_pos)
            anchor_time = self._mapper.pixel_to_time(old_scene_pos.x())
            if delta > 0:
                self._mapper.zoom_in(1.15)
            else:
                self._mapper.zoom_out(1.15)

            new_anchor_x = self._mapper.time_to_pixel(anchor_time)
            current_under_mouse = self.mapToScene(viewport_pos).x()
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() + int(new_anchor_x - current_under_mouse))

            # Reset cache khi zoom
            self.resetCachedContent()
            event.accept()

        elif event.modifiers() & Qt.ShiftModifier:
            # Cuộn ngang
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()

        else:
            # Cuộn dọc
            if self._vertical_scroll_enabled:
                bar = self.verticalScrollBar()
                bar.setValue(bar.value() - delta)
            event.accept()

    # ── Middle Mouse Drag (Pan) ─────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MiddleButton:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── Ensure viewport stays fresh ─────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resetCachedContent()

    # ── Drag & Drop Forwarding ──────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            data, kind = self._tool_payload(event.mimeData())
            if data is not None:
                self.scene().tool_preview_requested.emit(data, kind)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            data, kind = self._tool_payload(event.mimeData())
            if data is not None:
                self.scene().tool_preview_requested.emit(data, kind)
            scene_pos = self.mapToScene(event.position().toPoint())
            self.scene().show_drop_placeholder(scene_pos.x(), scene_pos.y())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.scene().hide_drop_placeholder()
        self.scene().tool_preview_clear_requested.emit()
        event.accept()

    @staticmethod
    def _tool_payload(mime):
        import json
        try:
            if mime.hasFormat("application/x-clinqing-effect"):
                return json.loads(bytes(mime.data(
                    "application/x-clinqing-effect")).decode("utf-8")), "effect"
            if mime.hasFormat("application/x-clinqing-preset"):
                data = json.loads(bytes(mime.data(
                    "application/x-clinqing-preset")).decode("utf-8"))
                raw_kind = mime.data("application/x-clinqing-kind")
                kind = bytes(raw_kind).decode("utf-8") if raw_kind else "text"
                return data, kind
        except (ValueError, UnicodeDecodeError, TypeError):
            pass
        return None, ""

    def dropEvent(self, event):
        if not event.mimeData().hasText() and not event.mimeData().hasUrls():
            event.ignore()
            return

        data, rich_kind = self._tool_payload(event.mimeData())
        name = event.mimeData().text()
        if not name and event.mimeData().hasUrls():
            name = event.mimeData().urls()[0].toLocalFile()
        kind_data = event.mimeData().data("application/x-clinqing-kind")
        kind = bytes(kind_data).decode("utf-8") if kind_data else "video"

        # Map viewport coords to scene coords
        scene_pos = self.mapToScene(event.position().toPoint())
        drop_x = scene_pos.x()
        drop_y = scene_pos.y()
        drop_time = max(0.0, self._mapper.pixel_to_time(drop_x))

        # Emit signal directly from scene
        self.scene().hide_drop_placeholder()
        if data is not None and rich_kind == "effect":
            self.scene().effect_dropped.emit(data, drop_time, drop_y)
        elif data is not None and rich_kind in ("text", "sticker"):
            self.scene().preset_dropped.emit(data, rich_kind, drop_time, drop_y)
        else:
            self.scene().resource_dropped.emit(name, kind, drop_time, drop_y)
        event.acceptProposedAction()
