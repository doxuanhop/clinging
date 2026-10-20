"""
scratch/button_clip_audit.py
Quét TOÀN BỘ nút trong app và tố cáo chữ bị cắt (button hẹp hơn chữ cần hiển thị).

Chạy: QT_QPA_PLATFORM=windows python -u scratch/button_clip_audit.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtWidgets import (                                      # noqa: E402
    QApplication, QPushButton, QToolButton, QComboBox, QLabel, QStyle,
    QStyleOptionButton, QStyleOptionComboBox, QStyleOptionToolButton)
from PySide6.QtGui import QFontMetrics                                  # noqa: E402

from theme import theme_manager                                          # noqa: E402


def content_rect(widget):
    """Bề rộng thật mà Qt dành cho chữ, lấy từ style đang chạy — không ước lượng
    bằng hằng số padding, nên mũi tên dropdown và khung nút đều được tính đúng."""
    if isinstance(widget, QComboBox):
        opt = QStyleOptionComboBox()
        widget.initStyleOption(opt)
        rect = widget.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt,
            QStyle.SubControl.SC_ComboBoxEditField, widget)
    elif isinstance(widget, QToolButton):
        # QStyleSheetStyle không báo padding của QSS qua subControlRect cho
        # QToolButton, nên lấy contentsRect (đây là các nút icon+chữ đã có lề).
        rect = widget.contentsRect()
    elif isinstance(widget, QPushButton):
        opt = QStyleOptionButton()
        widget.initStyleOption(opt)
        rect = widget.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, widget)
    else:
        rect = widget.contentsRect()
    return rect.width()


def audit(root, label, offenders):
    widgets = ([("button", b) for b in root.findChildren(QPushButton)] +
               [("button", b) for b in root.findChildren(QToolButton)] +
               [("combo", c) for c in root.findChildren(QComboBox)] +
               [("label", l) for l in root.findChildren(QLabel)])
    for kind, widget in widgets:
        if widget.width() <= 0 or not widget.isVisible():
            continue
        text = widget.currentText().strip() if kind == "combo" \
            else widget.text().strip()
        if not text or (kind == "label" and widget.wordWrap()):
            continue
        # Đo theo DÒNG dài nhất: nhãn 2 dòng không phải chữ bị cắt.
        text_width = max(QFontMetrics(widget.font()).horizontalAdvance(line)
                         for line in text.split("\n"))
        available = content_rect(widget)
        if available <= 0:
            continue
        if text_width > available:
            offenders.append({
                "where": label,
                "text": text,
                "object": "%s:%s" % (kind, widget.objectName() or
                                     widget.__class__.__name__),
                "width": widget.width(),
                "available": available,
                "text_width": text_width,
            })


def pump(app, times=6):
    for _ in range(times):
        app.processEvents()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme_manager.stylesheet())

    from ui.main_controller import MainController
    controller = MainController()
    controller.resize(1500, 920)
    controller.show()
    pump(app)

    offenders = []
    audit(controller.home_page, "home", offenders)

    controller._init_editor()
    controller.stack.setCurrentWidget(controller.editor_page)
    pump(app, 12)
    editor = controller.editor_page
    audit(editor, "editor", offenders)

    from ui.export_dialog import ExportDialog
    from ui.settings_dialog import SettingsDialog
    from ui.auto_captions_dialog import AutoCaptionsDialog
    # Giống hệt cách main_window mở các hộp thoại này.
    dialogs = [
        ("export", ExportDialog(editor.timeline_panel.model, parent=editor)),
        ("settings", SettingsDialog()),
        ("captions", AutoCaptionsDialog(editor)),
    ]
    for label, dialog in dialogs:
        dialog.resize(dialog.sizeHint().expandedTo(dialog.minimumSizeHint()))
        dialog.show()
        pump(app)
        audit(dialog, label, offenders)
        dialog.hide()

    print("%d clipped text widget(s)" % len(offenders))
    for item in offenders:
        print("  [%s] %-30r %s width=%d textArea=%d textWidth=%d" % (
            item["where"], item["text"][:30], item["object"],
            item["width"], item["available"], item["text_width"]))

    here = os.path.dirname(os.path.abspath(__file__))
    shot = os.path.join(here, "button_clip_toolbar.png")
    editor.timeline_panel.header.grab().save(shot)
    print("  toolbar evidence:", shot, os.path.getsize(shot), "bytes")

    # Ảnh phóng to: mắt thường phải thấy chữ có bị cắt hay không.
    from PySide6.QtCore import Qt as _Qt
    sidebar = editor.sidebar
    zoom = 3
    pixmap = sidebar.grab().scaled(sidebar.width() * zoom, sidebar.height() * zoom,
                                   _Qt.IgnoreAspectRatio, _Qt.FastTransformation)
    zoomed = os.path.join(here, "button_clip_sidebar.png")
    pixmap.save(zoomed)
    print("  sidebar evidence:", zoomed, os.path.getsize(zoomed), "bytes")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
