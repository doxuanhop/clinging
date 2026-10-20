"""Evidence: the text-animation card renders in the real editor panel.

Usage: QT_QPA_PLATFORM=windows python scratch/text_ui_probe.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "scratch")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from theme import theme_manager
from ui.graphics_canvas_item import TextClipItem
from ui.main_window import MainWindow
from core.timeline_model import TrackType

TEXT = "XIN CHAO\nBAN THE NAO"


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())

    win = MainWindow()
    win.resize(1680, 940)

    model = win.timeline_panel.model
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.TEXT, "Captions")
    clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, TEXT)
    clip.font_family = "Arial"
    clip.font_size = 96.0
    clip.font_bold = True
    clip.text_effect = "slide_in_left"
    clip.text_effect_intensity = 0.6

    win.properties_panel.show_clip_properties(clip)
    win.preview_panel.canvas.sync_scene_from_model(model, lambda c: None)
    app.processEvents()

    panel = win.properties_panel.grab()
    panel.save(os.path.join(OUT, "text_props_panel.png"))
    print("saved text_props_panel.png", panel.width(), "x", panel.height())

    # Card chữ chạy nằm cuối danh sách cuộn — kéo thanh cuộn xuống mới thấy thật
    from PySide6.QtWidgets import QScrollArea
    editor = win.properties_panel.current_editor
    scroll = editor.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents()
    lower = editor.grab()
    lower.save(os.path.join(OUT, "text_props_lower.png"))
    print("saved text_props_lower.png", lower.width(), "x", lower.height())

    editor = win.grab()
    editor.save(os.path.join(OUT, "text_editor_shot.png"))
    print("saved text_editor_shot.png", editor.width(), "x", editor.height())

    # Canvas Player với cùng khối chữ, tại hai nhịp tiến độ khác nhau
    CW, CH = 1920, 1080
    item = win.preview_panel.canvas._clip_items.get(clip.clip_id)
    print("canvas item:", type(item).__name__)
    tiles = []
    for t in (0.05, 0.55):
        item.set_local_time(t * 4.0)
        img = QImage(CW, CH, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.black)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        win.preview_panel.canvas.scene_obj.render(
            p, QRectF(0, 0, CW, CH), win.preview_panel.canvas.scene_obj.sceneRect())
        p.end()
        tiles.append(img)
    strip = QImage(CW, CH * 2 + 8, QImage.Format.Format_ARGB32_Premultiplied)
    strip.fill(Qt.GlobalColor.black)
    p = QPainter(strip)
    for i, img in enumerate(tiles):
        p.drawImage(0, i * (CH + 8), img)
    p.end()
    strip.scaled(760, int(strip.height() * 760 / CW), Qt.IgnoreAspectRatio,
                 Qt.SmoothTransformation).save(os.path.join(OUT, "text_canvas_strip.png"))
    print("saved text_canvas_strip.png")

    # Đổi kiểu chạy trong panel rồi kiểm tra model + item cùng theo
    editor_widget = win.properties_panel.current_editor
    combo = editor_widget.combo_text_effect
    combo.setCurrentIndex(max(0, combo.findData("typewriter")))
    app.processEvents()
    print("model effect after combo:", clip.text_effect)
    print("item plain text:", repr(item.toPlainText()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
