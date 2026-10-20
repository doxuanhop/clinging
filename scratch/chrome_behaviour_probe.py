"""scratch/chrome_behaviour_probe.py

dead_chrome_probe chỉ chứng minh một control CÓ slot. Probe này bấm thật từng
control vừa được nối trong #39 và đo hậu quả thật: thư mục dự án trên đĩa, số
cột mà layout tạo ra, thứ tự file MRU, chiều cao splitter, và nội dung hộp
thoại so với registry phím tắt.

Mọi fixture đi qua đường thật: APPDATA và CLINGING_SETTINGS_PATH trỏ vào thư mục
tạm, nên load_recent_projects / create_project_folder / settings là code sản
phẩm chạy nguyên ven — không có bản sao logic thứ hai để tự chiều.

Seam duy nhất bị thay là exec(): probe tự gõ vào ô nhập rồi bấm OK thật
(_on_accept là code sản phẩm). Không thay parse, không thay layout, không thay
hộp thoại.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/chrome_behaviour_probe.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

TMP = Path(tempfile.mkdtemp(prefix="clinging_chrome_"))
APPDATA = TMP / "appdata"
PROJECTS = TMP / "projects"
SCRATCH = ROOT / "scratch"
APPDATA.mkdir(parents=True)
PROJECTS.mkdir(parents=True)
os.environ["APPDATA"] = str(APPDATA)
os.environ["CLINGING_SETTINGS_PATH"] = str(APPDATA / "Clinging" / "settings.json")

import numpy as np
from PySide6.QtCore import QSize, qVersion
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core import settings

settings.use({"project_dir": str(PROJECTS)})

FAILS = []
STATS = {"gates": 0}
MRU_NAMES = ["Beta", "Mid", "Alpha", "Delta", "Zeta clip"]


def check(name, got, want):
    STATS["gates"] += 1
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def pump(app, times=12):
    for _ in range(times):
        app.processEvents()

def settle(app, ms=60):
    """Chạy một vòng loop thật — processEvents() KHÔNG flush deleteLater, nên
    đo ngay sau đó sẽ thấy cả card cũ lẫn card mới và gate nói dối về bố cục.
    Loop thật của app có flush, probe phải tương đương."""
    from PySide6.QtCore import QEventLoop, QTimer
    pump(app)
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    pump(app)


def shot(widget, tag):
    path = SCRATCH / ("chrome_%s.png" % tag)
    widget.grab().save(str(path))
    return path


def build_fixture():
    from ui.home_page import create_project_folder
    paths = []
    for name in MRU_NAMES:
        folder = create_project_folder(name, resolution=(640, 480))
        paths.append(str(folder / ("%s.clinq" % name)))
    return paths


def visible_cards(home):
    out = []
    for index in range(home.recent_grid.count()):
        item = home.recent_grid.itemAt(index)
        widget = item.widget() if item else None
        if widget is None or widget is home.empty_state:
            continue
        if not widget.isVisible():
            continue
        out.append(widget)
    return out


def card_stems(home):
    return [Path(widget.project_path).stem for widget in visible_cards(home)]


def card_columns(home):
    return len({widget.geometry().x() for widget in visible_cards(home)})


def find_button(root, object_name):
    for widget in root.findChildren(QPushButton):
        if widget.objectName() == object_name:
            return widget
    return None


def icon_raster(button):
    """Raster 24x24 của icon — đo pixel thật, không hỏi isNull()."""
    pixmap = button.icon().pixmap(QSize(24, 24))
    if pixmap.isNull():
        return np.zeros((24, 24), dtype=np.uint8)
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    buf = image.constBits()
    raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
    data = np.frombuffer(raw, np.uint8).reshape(image.height(), image.width(), 4)
    return data[:, :, 3].astype(np.int16)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    from PySide6.QtWidgets import QDialog
    from ui import custom_dialog

    PENDING = {"text": ""}
    dialogs = []

    def fake_input_exec(self):
        self.show()
        pump(app)
        self.input.setText(PENDING["text"])
        shot(self, "input")
        self._on_accept()          # nút OK thật: kể cả .strip() của sản phẩm
        return int(QDialog.Accepted)

    def fake_dialog_exec(self):
        self.show()
        pump(app)
        texts = [label.text() for label in self.findChildren(QLabel) if label.text()]
        longest = max(texts, key=len) if texts else ""
        png = shot(self, "dialog%d" % len(dialogs))
        dialogs.append({"title": self.windowTitle(), "text": longest, "png": png})
        self.hide()
        return 1

    custom_dialog.CustomInputDialog.exec = fake_input_exec
    custom_dialog.CustomDialog.exec = fake_dialog_exec

    # ── Fixture đọc/ghi đúng đường sản phẩm ──
    fixture = build_fixture()
    from ui import home_page as hp
    hp.save_recent_projects(fixture)
    check("fixture ghi đọc qua đúng đường sản phẩm", hp.load_recent_projects(), fixture)

    home = hp.HomePage()
    home.resize(1400, 900)
    home.show()
    pump(app)

    check("trang chủ nạp đủ 5 dự án thật", len(visible_cards(home)), 5)
    check("mặc định là lưới 4 cột", card_columns(home), 4)

    # ── View toggle: đo SỐ CỘT layout thật, không đo nhãn ──
    home.btn_view_list.click()
    settle(app)
    check("bấm nút danh sách còn 1 cột", card_columns(home), 1)
    check("danh sách vẫn đủ 5 card", len(visible_cards(home)), 5)
    check("trạng thái hai nút lật đúng",
          (home.btn_view_grid.isChecked(), home.btn_view_list.isChecked()),
          (False, True))
    home.btn_view_grid.click()
    settle(app)
    check("bấm lại nút lưới trả về 4 cột", card_columns(home), 4)

    # ── Sort: đo THỨ TỰ card ──
    check("sắp 'Mới nhất' giữ đúng thứ tự MRU trên đĩa", card_stems(home), MRU_NAMES)
    home._sort_actions["name"].trigger()
    settle(app)
    check("sắp 'Tên A→Z' đổi thứ tự card thật",
          card_stems(home), sorted(MRU_NAMES, key=str.lower))
    home._sort_actions["oldest"].trigger()
    settle(app)
    check("sắp 'Cũ nhất' là đảo ngược", card_stems(home), list(reversed(MRU_NAMES)))
    check("nhãn nút đổi theo chế độ đã chọn", home.btn_sort.text(),
          "Sắp xếp: Cũ nhất")
    check("thứ tự hiển thị KHÔNG bị ghi ngược vào file MRU",
          [Path(p).stem for p in hp.load_recent_projects()], MRU_NAMES)
    home._sort_actions["newest"].trigger()
    settle(app)

    # ── Custom size: bấm thật, đo thư mục + meta trên đĩa ──
    created = []
    home.createProject.connect(lambda name, path: created.append((name, path)))
    size_btn = find_button(home, "CustomSizeBtn")
    check("tìm thấy nút tùy chỉnh kích thước", size_btn is not None, True)

    before_dirs = len(list(PROJECTS.iterdir()))
    PENDING["text"] = "1234x567"
    size_btn.click()
    pump(app)
    check("nút tạo đúng một dự án", len(created), 1)
    check("thư mục dự án tăng đúng 1", len(list(PROJECTS.iterdir())) - before_dirs, 1)
    if created:
        meta = json.loads(Path(created[0][1]).read_text(encoding="utf-8"))["project_meta"]
        check("meta lưu đúng kích thước người dùng nhập",
              (meta["resolution"]["width"], meta["resolution"]["height"]),
              (1234, 567))
        check("dự án mới được đẩy lên đầu MRU",
              Path(hp.load_recent_projects()[0]).stem, "Dự án 6")
    shot(home, "home_after_create")

    # Counterfactual: input rác thì không được tạo gì cả
    before_dirs = len(list(PROJECTS.iterdir()))
    dialogs_before = len(dialogs)
    PENDING["text"] = "abc"
    size_btn.click()
    pump(app)
    check("input rác không tạo thêm thư mục dự án",
          len(list(PROJECTS.iterdir())), before_dirs)
    check("input rác phải bật hộp cảnh báo", len(dialogs) - dialogs_before, 1)
    if len(dialogs) > dialogs_before:
        check("cảnh báo nói đúng thứ sai", "không hợp lệ" in dialogs[-1]["title"], True)

    check("bảng parse chặn hết input rác",
          [hp.HomePage._parse_custom_size(text) for text in
           ("1920x1080", " 1080 X 1920 ", "640*360", "abc", "", "1x1080",
            "8001x600", "1920x8001")],
          [(1920, 1080), (1080, 1920), (640, 360), None, None, None, None, None])

    # ── Editor: nút toàn màn hình timeline ──
    from ui.main_window import MainWindow
    editor = MainWindow()
    editor.resize(1500, 900)
    editor.show()
    pump(app, 30)

    header = editor.timeline_panel.header
    sizes0 = list(editor.work_splitter.sizes())
    ink0 = icon_raster(header.btn_focus)
    header.btn_focus.click()
    pump(app)
    sizes1 = list(editor.work_splitter.sizes())
    ink1 = icon_raster(header.btn_focus)
    check("bấm toàn màn hình: timeline cao lên thật", sizes1[1] > sizes0[1], True)
    check("bấm toàn màn hình: vùng xem bị thu thật", sizes1[0] < sizes0[0], True)
    check("icon nút đổi hình thật (khác raster, không phải khác tên)",
          (bool((ink0 > 0).any()), bool((ink1 > 0).any()),
           bool((ink0 != ink1).any())), (True, True, True))
    shot(editor, "editor_focus_on")
    header.btn_focus.click()
    pump(app)
    check("bấm lần hai trả lại đúng tỷ lệ đã lưu trước đó",
          list(editor.work_splitter.sizes()), sizes0)

    # ── Hộp "Phím tắt" phải là chính registry ──
    editor._show_shortcuts()
    shortcuts = dialogs[-1]
    keys = sorted(editor._editor_bindings)
    check("hộp phím tắt có nội dung", bool(shortcuts["text"]), True)
    check("mọi phím đã cài đều xuất hiện",
          [key for key in keys if key not in shortcuts["text"]], [])
    check("hộp phím tắt không có dòng nào ngoài registry",
          len([line for line in shortcuts["text"].split(chr(10)) if line.strip()]),
          len(keys))
    shortcuts_png = Path(shortcuts["png"])

    editor._editor_bindings["Ctrl+K"] = ("Dòng mồi cho counterfactual",
                                         lambda: None)
    editor._show_shortcuts()
    check("thêm 1 phím vào registry thì hộp dài ra đúng 1 dòng",
          len([line for line in dialogs[-1]["text"].split(chr(10)) if line.strip()]),
          len(keys) + 1)
    del editor._editor_bindings["Ctrl+K"]

    editor._show_about()
    about = dialogs[-1]["text"]
    ffmpeg = shutil.which("ffmpeg")
    check("hộp 'Về' nói đúng phiên bản app", settings.APP_VERSION in about, True)
    check("hộp 'Về' nói đúng Qt đang chạy", qVersion() in about, True)
    check("hộp 'Về' nói đúng đường dẫn ffmpeg thật",
          (bool(ffmpeg), ffmpeg in about if ffmpeg else False), (True, True))
    check("hộp 'Về' nói đúng file cài đặt đang dùng",
          str(settings.settings_path()) in about, True)

    draw_evidence(shortcuts_png, Path(dialogs[-1]["png"]))

    print("\n%d gates, %d FAIL" % (STATS["gates"], len(FAILS)))
    for line in FAILS:
        print("FAIL ", line)
    return 0 if not FAILS else 1


def draw_evidence(shortcuts_png, about_png):
    """Ghép ảnh đã chụp và tự kiểm tra bố cục của chính tấm bằng chứng."""
    from PIL import Image, ImageDraw

    cells = [
        ("home_after_create", "Trang chủ: dự án tùy chỉnh vừa tạo"),
        ("editor_focus_on", "Timeline toàn màn hình (vùng xem bị thu)"),
        ("input", "Hộp nhập kích thước thật"),
        ("dialog0", "Cảnh báo input rác"),
    ]
    named = [(tag, title, SCRATCH / ("chrome_%s.png" % tag))
             for tag, title in cells
             if (SCRATCH / ("chrome_%s.png" % tag)).exists()]
    named += [("shortcuts", "Phím tắt — in từ registry", shortcuts_png),
              ("about", "Về Clinging — sự thật đọc lúc chạy", about_png)]
    check("bằng chứng: đủ 6 ảnh cho từng control đã bấm", len(named), 6)

    slot_w, slot_h, pad, caption = 640, 420, 24, 22
    cols = 2
    rows = (len(named) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * (slot_w + pad) + pad,
                               rows * (slot_h + pad + caption) + pad),
                       (16, 17, 23))
    draw = ImageDraw.Draw(canvas)
    rects = {}
    for index, (tag, title, path) in enumerate(named):
        row, col = divmod(index, cols)
        x = pad + col * (slot_w + pad)
        y = pad + row * (slot_h + pad + caption)
        img = Image.open(path).convert("RGB")
        scale = min(slot_w / img.width, slot_h / img.height, 1.0)
        size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        canvas.paste(img.resize(size), (x, y + caption))
        draw.text((x + 2, y + 4), title, fill=(224, 224, 230))
        rects[tag] = (x, y + caption, x + size[0], y + size[1] + caption)

    def overlaps(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

    keys = list(rects)
    check("bằng chứng: không ô nào tràn ra ngoài ảnh",
          [tag for tag, box in rects.items()
           if box[0] < 0 or box[1] < 0 or box[2] > canvas.width
           or box[3] > canvas.height], [])
    check("bằng chứng: hai ô bất kỳ không chồng lên nhau",
          ["%s+%s" % (a, b) for i, a in enumerate(keys) for b in keys[i + 1:]
           if overlaps(rects[a], rects[b])], [])
    arr = np.asarray(canvas.convert("RGB"), dtype=np.int16)
    check("bằng chứng: mọi ô đều có nội dung thật",
          [tag for tag, box in rects.items()
           if int(arr[box[1]:box[3], box[0]:box[2]].max()) < 40], [])

    out = SCRATCH / "chrome_evidence.png"
    canvas.save(str(out))
    print("bằng chứng: %s (%dx%d)" % (out, canvas.width, canvas.height))


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # Fixture nam trong TMP (APPDATA + project_dir tai dinh huong), xoa het
        # de lan chay sau khong phat san thep bua truoc.
        shutil.rmtree(str(TMP), ignore_errors=True)
