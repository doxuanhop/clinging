"""Gate UI lớp phủ recap: mọi điều khiển PHẢI đổi được model, một bước undo trả lại hết.

Probe đi qua MainWindow thật + hộp thoại thật (không tự dựng lại widget), vì mọi
lỗi ở đây đều im lặng: nút không nối thì model đứng yên, model đứng yên thì bản
xuất ra video không có lớp phủ mà không ai báo.

Bốn thứ đo:
  0. nút trên header PHẢI mở được hộp thoại (đi hết chuỗi ba signal);
  1. từng điều khiển (5 checkbox, 3 thanh trượt, combo kiểu, 12 ô màu, nhãn, fps)
     phải ghi đúng khoá của nó vào ``model.recap_overlay``;
  2. đổi settings thì Canvas phải VẼ LẠI (đếm lần gọi drawForeground) — nếu
     không, người dùng kéo thanh trượt mà khung hình đứng yên;
  3. đóng hộp thoại = ĐÚNG MỘT mục lịch sử, undo/redo đưa model về đúng ảnh;
  4. bằng chứng là ảnh chụp thật của hộp thoại + khung hình, không phải log.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "scratch")
EVIDENCE = os.path.join(OUT, "recap_ui_evidence.png")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QLineEdit, QSlider, QSpinBox, QPushButton,
)

APP = QApplication.instance() or QApplication([])

# Autosave của MainWindow ghi vào thư mục người dùng — bật sang TEMP trước khi
# động vào bất kỳ cửa nào, kẻo báo cáo này sửa mất dự án thật.
from core import project_storage  # noqa: E402
project_storage.AUTO_SAVE_FILE = os.path.join(OUT, "recap_ui_autosave.json")

from core import recap_overlay  # noqa: E402


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def rows_of(dialog):
    return {row.key: row for row in dialog._rows()}


def main():
    from ui.main_window import MainWindow

    # Shiboken cache việc phân giải method ảo THEO INSTANCE từ lần gọi đầu, nên
    # wrapper phải được gắn lên class TRƯỚC khi MainWindow kịp vẽ lần nào — gắn
    # sau thì đếm được 0 dù canvas vẫn vẽ bình thường.
    import ui.preview_panel as upp
    calls = []
    counting = {"on": False}
    original = upp.PreviewCanvas.drawForeground

    def wrapped(self, painter, rect):
        if counting["on"]:
            calls.append(1)
        return original(self, painter, rect)

    upp.PreviewCanvas.drawForeground = wrapped
    try:
        return _drive(win_factory=MainWindow, calls=calls, counting=counting,
                      original=original)
    finally:
        upp.PreviewCanvas.drawForeground = original


def _drive(win_factory, calls, counting, original):
    win = win_factory()
    win.resize(1600, 900)
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    win.show()
    pump(app := APP, 12)

    model = win.timeline_panel.model
    stack = win.timeline_panel.undo_stack
    opening = dict(model.recap_overlay)
    if opening["enabled"]:
        raise RuntimeError("mo cua da bat san lop phu — khong the do undo")

    # --- 0. nut THAT tren header phai mo duoc hop thoai ---------------------
    # Goi thang _open_recap_overlay() thi day ba noi signal (btn -> header ->
    # panel -> cua so) khong bao gio bi do: noi hoi, video van ra, chi la
    # khong ai mo duoc bang dieu khien nua.
    btn = win.timeline_panel.header.btn_recap
    if not btn.isVisible():
        raise RuntimeError("nut lop phu recap bi cat mat tren header")
    btn.click()
    pump(app, 6)
    dialog = getattr(win, "_recap_dialog", None)
    if dialog is None or not dialog.isVisible():
        raise RuntimeError("click nut header khong mo duoc hop thoai")
    if dialog is not win._open_recap_overlay():
        raise RuntimeError("hop thoai khoi dong hai lan, moi lan mot cai")

    # Hai thứ thật sự có thể hỏng với hộp thoại này: (a) nút Đóng bị đẩy ra
    # ngoài thân, (b) thân hộp thoại CAO HƠN MÀN HÌNH. (b) là rủi ro thật trên
    # máy cấu hình thấp 1366x768: thêm hàng điều khiển mà không thêm cuộn thì
    # nửa dưới — gồm đúng cái nút Đóng — nằm ngoài tầm bấm, và Qt không hề báo.
    close_btn = [b for b in dialog.findChildren(QPushButton)
                 if b.text() == "Đóng"][0]
    bottom = close_btn.mapTo(dialog, QPoint(0, close_btn.height())).y()
    if bottom > dialog.height():
        raise RuntimeError("nut Dong tran ra ngoai hop thoai (%d > %d)"
                           % (bottom, dialog.height()))
    from PySide6.QtGui import QGuiApplication
    avail = QGuiApplication.primaryScreen().availableGeometry().height()
    if dialog.height() > avail:
        raise RuntimeError("hop thoai cao %d px, vuot man hinh %d px"
                           % (dialog.height(), avail))

    # --- 1. tung dieu khien phai ghi dung khoa ------------------------------
    touched = {}
    dialog.chk_enabled.setChecked(True);  touched["enabled"] = True
    dialog.chk_glass.setChecked(True);    touched["glass"] = True
    dialog.chk_border.setChecked(True);   touched["border"] = True
    dialog.chk_reticle.setChecked(True);  touched["reticle"] = True
    dialog.chk_rec.setChecked(True);      touched["rec"] = True
    sliders = rows_of(dialog)
    sliders["brightness"].slider.setValue(72);  touched["bg_brightness"] = 0.72
    sliders["blur"].slider.setValue(51);        touched["bg_blur"] = 51.0
    sliders["border_width"].slider.setValue(9); touched["border_width"] = 9.0
    dialog.combo_shape.setCurrentIndex(4);      touched["reticle_shape"] = "tactical"
    dialog.edit_label.setText("1080p TEST");    touched["rec_label"] = "1080p TEST"
    dialog.spin_fps.setValue(60);               touched["rec_fps"] = 60
    swatch = dialog.swatches[2][1]
    swatch.click();                             touched["border_color"] = dialog.swatches[2][0]
    pump(app)

    now = model.recap_overlay
    dead = {k: (now.get(k), v) for k, v in touched.items() if now.get(k) != v}
    if dead:
        raise RuntimeError("dieu khien khong ghi duoc model: %s" % dead)

    # --- 2. doi settings thi Canvas phai ve lai -----------------------------
    # (wrapper đã gắn ở main() trước lần vẽ đầu tiên; ở đây chỉ bật công tắc đếm)
    try:
        counting["on"] = True
        dialog.chk_reticle.setChecked(False)
        pump(app, 10)
        after_off = len(calls)
        dialog.chk_reticle.setChecked(True)
        dialog.chk_glass.setChecked(False)
        pump(app, 10)
        after_on = len(calls) - after_off
    finally:
        counting["on"] = False
    if after_off == 0 or after_on == 0:
        raise RuntimeError("Canvas khong ve lai khi doi lop phu (%d/%d lan)"
                           % (after_off, after_on))

    # --- 3. dong = DUNG MUC undo, undo/redo tra dung anh --------------------
    final = dict(model.recap_overlay)
    before_depth = len(stack._undo_stack)
    dialog._on_close()
    pump(app)
    grew = len(stack._undo_stack) - before_depth
    if grew != 1:
        raise RuntimeError("dong hop thoai tao %d muc undo, mong 1" % grew)
    stack.undo()
    pump(app)
    if model.recap_overlay != opening:
        raise RuntimeError("undo khong tra ve trang thai mo cua: %s"
                           % (model.recap_overlay,))
    stack.redo()
    pump(app)
    if model.recap_overlay != final:
        raise RuntimeError("redo khong dat lai duoc ca 13 khoa")
    stack.undo()
    pump(app)

    # --- 4. mo lai hop thoai phai doc dung trang thai hien tai --------------
    dialog2 = win._open_recap_overlay()
    pump(app, 4)
    if dialog2.chk_enabled.isChecked():
        raise RuntimeError("mo lai hop thoai thay master dang BAT sau undo")
    dialog2.chk_enabled.setChecked(True)
    dialog2.chk_border.setChecked(True)
    dialog2.chk_reticle.setChecked(True)
    dialog2.chk_rec.setChecked(True)
    dialog2.combo_shape.setCurrentIndex(2)   # scope
    pump(app)
    dialog2._on_close()
    pump(app)

    canvas = win.preview_panel.canvas
    shot = canvas.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    dlg = dialog2.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    # Cửa preview chỉ rộng ~760px cho khung 1920 nên nét 3px của tâm ngắm co lại
    # dưới 2px và màu cyan không còn đạt ngưỡng tuyệt đối. Vì vậy đo BẰNG HIỆU:
    # cùng một cửa, bật và tắt lớp phủ, rồi xem pixel nào dịch chuyển và dịch ở
    # đâu — đúng chỗ tâm ngắm và badge REC phải nằm.
    model.set_recap_overlay({"enabled": False})
    pump(app, 8)
    off = canvas.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    model.set_recap_overlay(final)
    pump(app, 8)

    import numpy as np

    def arr(img):
        row = img.bytesPerLine() // 4
        return np.frombuffer(img.constBits(), np.uint8,
                             count=row * 4 * img.height()).reshape(
            img.height(), row, 4)[:, :img.width(), :3].astype(int)

    diff = (np.abs(arr(shot) - arr(off)).max(axis=2) > 24)
    moved = int(diff.sum())
    h, w = diff.shape
    centre = diff[h // 2 - 26:h // 2 + 26, w // 2 - 26:w // 2 + 26]
    # Vùng badge REC phải quy đổi từ scene sang pixel thật của cửa: khung 1920
    # nằm gọn trong 762px nên lấy theo toạ độ scene là trượt ra ngoài canvas.
    from PySide6.QtCore import QPointF
    from core.canvas_utils import ASPECT_RATIOS
    sw, sh = ASPECT_RATIOS.get(canvas._current_ratio_key, (1920, 1080))
    # mapFromScene mới là phép chiếu scene -> pixel của viewport; transform()
    # trả về phép biến đổi world và cho ra toạ độ âm.
    tl = canvas.mapFromScene(QPointF(-sw / 2, -sh / 2))
    br = canvas.mapFromScene(QPointF(sw / 2, sh / 2))
    top, left = int(tl.y()), int(tl.x())
    chip = diff[top:top + max(1, int((br.y() - tl.y()) * 0.12)),
                left:left + max(1, int((br.x() - tl.x()) * 0.25))]
    if moved < 400:
        raise RuntimeError("lop phu khong thay doi khung that (%d px lech)" % moved)
    if int(centre.sum()) < 20:
        raise RuntimeError("tam ngam khong xuat hien o giua khung (%d px)" % int(centre.sum()))
    if int(chip.sum()) < 20:
        raise RuntimeError("badge REC khong xuat hien goc tren trai (%d px)" % int(chip.sum()))

    sheet = QImage(shot.width() + dlg.width() + 16,
                   max(shot.height(), dlg.height()) + 8,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#09090b"))
    p = QPainter(sheet)
    p.drawImage(8, 8, shot)
    p.drawImage(shot.width() + 16, 8, dlg)
    p.end()
    sheet.save(EVIDENCE)

    print(json.dumps({
        "controls_wired": len(touched),
        "repaint_calls": [after_off, after_on],
        "undo_entries_on_close": grew,
        "canvas_diff_px": [moved, int(centre.sum()), int(chip.sum())],
        "dialog_size": [dlg.width(), dlg.height()],
        "screen_h": avail,
        "evidence": EVIDENCE,
    }, ensure_ascii=False))
    win.close()
    pump(app, 4)
    print("OK: hop thoai lop phu recap noi that voi model, canvas va undo")


if __name__ == "__main__":
    sys.exit(main())
