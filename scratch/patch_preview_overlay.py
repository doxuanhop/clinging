"""Nối lớp phủ recap vào đường preview (ui/preview_panel.py). Neo đơn nhất, LF."""
import io

PATH = r"D:\Programming\clinging\ui\preview_panel.py"
s = io.open(PATH, "r", encoding="utf-8", newline="").read()
assert "\r\n" not in s, "file phai LF"


def sub(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new, 1)


sub("from PySide6.QtCore import Qt, Signal, QSize, QPointF, QTimer\n"
    "from PySide6.QtGui import QColor, QPen, QFont, QBrush, QPainter, QWheelEvent\n",
    "import time\n\n"
    "from PySide6.QtCore import Qt, Signal, QSize, QPointF, QRectF, QTimer\n"
    "from PySide6.QtGui import QColor, QPen, QFont, QBrush, QImage, QPainter, QWheelEvent\n")

sub("from ui.graphics_canvas_item import CanvasClipItem\n"
    "from core.timeline_model import ClipModel\n",
    "from ui.graphics_canvas_item import CanvasClipItem\n"
    "from core.timeline_model import ClipModel\n"
    "from core import recap_overlay\n")

sub("        self._clip_items = {}\n        self._syncing = False\n",
    "        self._clip_items = {}\n"
    "        self._model = None\n"
    "        self._glass_cache = None\n"
    "        self._glass_key = None\n"
    "        self._glass_at = 0.0\n"
    "        self._syncing = False\n")

sub('    def sync_scene_from_model(self, model, on_transform_callback):\n'
    '        """Đồng bộ toàn bộ clip từ TimelineModel lên Canvas."""\n'
    "        self._syncing = True\n",
    '    def sync_scene_from_model(self, model, on_transform_callback):\n'
    '        """Đồng bộ toàn bộ clip từ TimelineModel lên Canvas."""\n'
    "        self._model = model\n"
    "        self._syncing = True\n")

FG = '''    def drawForeground(self, painter, rect):
        """Vẽ lớp phủ recap lên Canvas bằng đúng core/recap_overlay mà bản xuất dùng."""
        model = self._model
        if model is None:
            return
        settings = model.recap_overlay
        if not recap_overlay.overlay_active(settings):
            return
        from core.canvas_utils import ASPECT_RATIOS
        w, h = ASPECT_RATIOS.get(self._current_ratio_key, (1920, 1080))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
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

'''

anchor = "    def wheelEvent(self, event: QWheelEvent):\n"
assert s.count(anchor) == 1
s = s.replace(anchor, FG + anchor, 1)

io.open(PATH, "w", encoding="utf-8", newline="").write(s)
print("patched, bare LF ok:", s.count("\n") - s.count("\r\n") == len(s.splitlines()))
