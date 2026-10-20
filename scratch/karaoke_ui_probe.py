"""Gate UI cho bộ chọn kiểu karaoke: một dòng trong combo PHẢI đổi được khung hình.

Lỗi ở đây là lỗi im lặng: combo đầy đủ 8 nhãn, model nhận đúng khoá, nhưng item
trên Canvas không vẽ lại — người dùng chọn "Lửa" thì màn hình vẫn là chữ trắng,
và bản xuất ra vẫn đúng, nên không ai biết cho tới khi so hai bên. Vì vậy probe
này đo cả bốn khúc: nhãn -> model -> vẽ lại -> pixel thay đổi thật.

Đi qua MainWindow thật + Properties panel thật (không tự dựng widget): nút/signal
không nối thì model đứng yên, và model đứng yên thì không có gì dưới này đo được.

Chay: QT_QPA_PLATFORM=windows python -u scratch/karaoke_ui_probe.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
# Font THAT: duoi offscreen Qt tra ve 0 ho, moi ky tu in ra mot hinh chu nhat,
# nen "chu doi mau" van xanh gia ca khi duong ve bi cat.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
OUT = os.path.join(HERE, "scratch")
EVIDENCE = os.path.join(OUT, "karaoke_ui_evidence.png")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402
import numpy as np  # noqa: E402

APP = QApplication.instance() or QApplication([])  # noqa: F841

from core import karaoke_paint, project_storage  # noqa: E402
from core.timeline_model import TrackType  # noqa: E402

# Autosave của MainWindow ghi vào thư mục người dùng — bật sang TEMP trước khi
# động vào bất kỳ cửa nào, kẻo báo cáo này sửa mất dự án thật.
project_storage.AUTO_SAVE_FILE = os.path.join(OUT, "karaoke_ui_autosave.json")

FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def arr(img):
    row = img.bytesPerLine() // 4
    return np.frombuffer(img.constBits(), np.uint8,
                         count=row * 4 * img.height()).reshape(
        img.height(), row, 4)[:, :img.width(), :3].astype(int)


def main():
    from ui.main_window import MainWindow

    # Đếm lần Canvas thực sự vẽ lại. Wrapper phải gắn lên class TRƯỚC khi cửa sổ
    # kịp vẽ lần nào, vì shiboken cache việc phân giải method theo instance.
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
        return _drive(MainWindow, calls, counting, original)
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
    panel = win.properties_panel

    # --- 1. clip chu THAT qua chinh duong cua app ---------------------------
    # Tab "Chữ" dựng lại toàn bộ widget mỗi lần show_clip_properties, nên combo
    # phải được lấy lại qua panel sau mỗi lần mở — giữ một tham chiếu cũ là đo
    # trên cái widget đã bị thay.
    win._add_text_to_timeline()
    pump(app, 8)
    track = [t for t in model.tracks if t.track_type == TrackType.TEXT][0]
    clip = track.clips[0]
    clip.name = "Xin chao buoi sang"
    panel.show_clip_properties(clip)
    pump(app, 8)

    def combo():
        # Widget thuoc ve ClipPropertiesWidget cua clip dang chon (panel dung
        # lai no khi mo lai cung mot clip), khong phai attribute cua panel.
        editor = getattr(panel, "current_editor", None)
        c = getattr(editor, "combo_text_style", None) if editor else None
        if not isinstance(c, QComboBox):
            raise RuntimeError("properties panel khong co combo kieu karaoke")
        return c

    # --- 2. combo phai co 9 mong: "none" + tam kieu, nhan khong trung --------
    c = combo()
    keys = [c.itemData(i) for i in range(c.count())]
    labels = [c.itemText(i) for i in range(c.count())]
    if keys[0] != "none" or tuple(keys[1:]) != karaoke_paint.STYLE_KEYS:
        raise RuntimeError("combo khong dung 8 khoa (duoc %s)" % (keys,))
    if len(set(labels)) != len(labels) or any(not l.strip() for l in labels[1:]):
        raise RuntimeError("nhan kieu trung nhau hoac rong: %s" % labels)
    if c.currentData() != "none":
        raise RuntimeError("mo clip moi ma combo dang o %s" % c.currentData())

    # --- 3. chon kieu phai ghi model, ve lai, va KHONG tao muc undo ---------
    depth = len(stack._undo_stack)
    try:
        counting["on"] = True
        combo().setCurrentIndex(1)        # glow — di qua signal that
        pump(app, 10)
        repaint_first = len(calls)
    finally:
        counting["on"] = False
    if clip.text_style != "glow":
        raise RuntimeError("combo doi nhung clip.text_style van %s" % clip.text_style)
    if repaint_first == 0:
        raise RuntimeError("Canvas khong ve lai khi doi kieu karaoke")
    if len(stack._undo_stack) != depth:
        raise RuntimeError("doi kieu karaoke tao %d muc undo (quy uoc cua tab "
                           "chu la khong tao)" % (len(stack._undo_stack) - depth))

    # Moi trong 8 kieu phai in het ten cua no len model — mot mong bi noi trinh
    # voi mong khac la loi ma chi do tung cai moi thay.
    written = {}
    c = combo()
    for i in range(1, c.count()):
        c.setCurrentIndex(i)
        pump(app, 2)
        written[c.itemData(i)] = clip.text_style
    bad = {k: v for k, v in written.items() if k != v}
    if bad:
        raise RuntimeError("mong nao do ghi sai khoa: %s" % bad)

    # --- 4. doc lai: mo lai properties KHONG duoc ghi de model --------------
    clip.text_style = "neon"
    panel.show_clip_properties(clip)
    pump(app, 4)
    if combo().currentData() != "neon":
        raise RuntimeError("mo lai properties khong doc dung kieu trong model (%s)"
                           % combo().currentData())
    if clip.text_style != "neon":
        raise RuntimeError("show_clip_properties dung combo de ghi nguoc lai model")

    # --- 5. pixel: hai kieu khac nhau phai cho hai khung hinh ---------------
    canvas = win.preview_panel.canvas
    model.playhead = clip.start_time + clip.duration * 0.5
    canvas.update()
    pump(app, 12)

    def shoot(style):
        """Đổi kiểu ĐÚNG theo đường người dùng: một cú chọn ở combo.

        Probe không được gọi item.refresh_style() hộ nữa — tự vẽ hộ thì lỗi
        "model đúng nhưng item không bao giờ vẽ lại" sẽ chẳng bao giờ hiện ra.
        """
        c = combo()
        idx = c.findData(style)
        if idx < 0:
            raise RuntimeError("combo khong co kieu %s de chon" % style)
        c.setCurrentIndex(idx)
        pump(app, 12)
        if clip.text_style != style:
            raise RuntimeError("chon %s o combo nhung model la %s" % (style, clip.text_style))
        if canvas._clip_items.get(clip.clip_id) is None:
            raise RuntimeError("Canvas khong co item cho clip chu (%s)" % clip.clip_id)
        return canvas.grab().toImage().convertToFormat(FORMAT)

    shots = {style: shoot(style) for style in ("none", "glow", "neon")}

    base = arr(shots["none"])
    moved = {}
    for style in ("glow", "neon"):
        d = (np.abs(arr(shots[style]) - base).max(axis=2) > 24)
        moved[style] = int(d.sum())
        if moved[style] < 120:
            raise RuntimeError("kieu %s khong doi khung preview (%d px lech so voi chu thuong)"
                               % (style, moved[style]))

    # --- 6. anh chung minh: chu thuong | kieu | combo, khong phai log --------
    # Ba ô vì hai lỗi khác nhau cần nhìn thấy: ô giữa phải KHÁC ô trái (đường
    # vẽ nối tới Canvas) và ô phải phải CHO THẤY combo 9 dòng (không phải ảnh
    # chụp một cái bảng đã cuộn qua mặt điều khiển).
    plain_shot = shots["none"]
    style_shot = shoot("flame")
    # Cho đúng cái combo đang chọn kiểu vừa chụp — bảng điều khiển và khung hình
    # phải kể cùng một câu chuyện trong ảnh.
    pump(app, 4)

    from PySide6.QtWidgets import QAbstractScrollArea
    areas = panel.findChildren(QAbstractScrollArea)
    if areas:
        bar = areas[0].verticalScrollBar()
        y = combo().mapTo(areas[0].viewport(), QPoint(0, 0)).y()
        bar.setValue(max(0, min(bar.maximum(), bar.value() + y - 40)))
        pump(app, 6)
    strip = panel.grab().toImage().convertToFormat(FORMAT)

    # Ba ô, hai hàng: hàng trên là cùng một playhead với hai kiểu khác nhau,
    # hàng dưới là đúng cái combo. Bề ngang sheet phải tính cho CẢ HAI ô canvas
    # — đặt ô thứ hai ngoài chiều ngang là ảnh vẫn lưu được, chỉ là nó cụt.
    row_y = 22
    strip_y = row_y + plain_shot.height() + 26
    sheet = QImage(max(plain_shot.width() * 2 + 24, strip.width() + 16),
                   strip_y + strip.height() + 8, FORMAT)
    sheet.fill(QColor("#09090b"))
    p = QPainter(sheet)
    p.drawImage(8, row_y, plain_shot)
    p.drawImage(plain_shot.width() + 16, row_y, style_shot)
    p.drawImage(8, strip_y, strip)
    p.setPen(QColor("#e4e4e7"))
    p.drawText(8, 15, "trai: chu thuong | phai: kieu flame (cung playhead)")
    p.drawText(8, strip_y - 8, "properties: combo kieu karaoke")
    p.end()
    sheet.save(EVIDENCE)
    if not os.path.exists(EVIDENCE) or os.path.getsize(EVIDENCE) < 20000:
        raise RuntimeError("anh chung minh khong co noi dung (%d byte)"
                           % (os.path.getsize(EVIDENCE) if os.path.exists(EVIDENCE) else 0))
    # Ảnh phải thật sự khác nhau: hai ô giống hệt nhau nghĩa là "flame" chỉ là
    # một dòng chữ thường, và sheet này sẽ trông vẫn ổn nếu không đo.
    changed = int((np.abs(arr(style_shot) - arr(plain_shot)).max(axis=2) > 24).sum())
    if changed < 120:
        raise RuntimeError("bang chung minh co hai o giong het nhau (%d px lech)" % changed)

    win.close()
    pump(app, 4)
    print(json.dumps({
        "combo_entries": combo().count(),
        "keys_ok": list(written),
        "repaint_calls_on_change": repaint_first,
        "undo_entries_added": 0,
        "readback_index": "neon",
        "preview_diff_px": moved,
        "evidence_diff_px": changed,
        "evidence": EVIDENCE,
    }, ensure_ascii=False))
    print("OK: bo chon karaoke noi that voi model, canvas va pixel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
