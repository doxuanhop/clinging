"""scratch/dead_chrome_probe.py

Đếm mọi control tương tác ĐANG NHÌN THẤY trong app thật và hỏi: có slot nào
nghe tín hiệu của nó không? Không có = chrome chết: người dùng bấm và không
gì xảy ra.

Máy dò sống trong diagnostics.py (diagnostics.audit_chrome) vì chính
--selftest của exe đã cài phải chạy nó; probe này chỉ là lớp gate. Probe không
tạo bản sao thứ hai của máy dò — hai bản sao đồng ý với nhau không chứng minh
điều gì.

Counterfactual bắt buộc: probe tự tạo một nút chết và một nút sống, máy dò phải
phân biệt được hai cái — nếu không thì danh sách "chết" chỉ là lỗi của detector.
Máy dò này KHÔNG bắt được loại "nút sống nhưng hứa hão" (rail từng có một mục như
vậy), nên phần cuối có thêm ải rail: mọi mục phải có nhánh xử lý trong MainWindow
và hai mục không được dẫn về cùng một trạng thái; ải đó cũng có phản chứng riêng.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/dead_chrome_probe.py
"""

import os
import sys
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QMenu,
                               QPushButton, QToolButton, QWidget)

from diagnostics import (action_connection, audit_chrome, baseline_count,
                         collect_menus, connection_count, live_actions,
                         orphan_baseline, raw_receivers, visible_interactive)

FAILS = []
STATS = {"gates": 0}


def check(name, got, want):
    STATS["gates"] += 1
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def detector_proves_itself():
    """Detector phải nói đúng về hai nút đã biết câu trả lời."""
    live = QPushButton("sống")
    dead = QPushButton("chết")
    live.clicked.connect(lambda checked=False: None)
    check("detector nhận nút có nối", connection_count(live) > 0, True)
    check("detector nhận nút không nối", connection_count(dead), 0)

    combo_live = QComboBox()
    combo_live.addItem("a")
    combo_live.currentIndexChanged.connect(lambda *a: None)
    combo_dead = QComboBox()
    combo_dead.addItem("a")
    check("detector chạy cho QComboBox nối",
          connection_count(combo_live) > 0, True)
    check("detector chạy cho QComboBox không nối",
          connection_count(combo_dead), 0)

    # QToolButton là chỗ detector từng nói dối: Qt tự nối 2 tín hiệu của nó.
    tool_dead = QToolButton()
    check("QToolButton chưa nối bị bắt (đã trừ nền Qt)",
          (raw_receivers(tool_dead) > 0, connection_count(tool_dead)),
          (True, 0))
    tool_live = QToolButton()
    tool_live.clicked.connect(lambda checked=False: None)
    check("QToolButton có nối vẫn được tính đúng",
          connection_count(tool_live) > 0, True)

    # Nút dạng menu: Qt tự mở menu lúc bấm, nút chỉ chết khi menu rỗng slot.
    popup_menu = QMenu()
    orphan_a = popup_menu.addAction("lọc A")
    orphan_a.setCheckable(True)
    popup = QToolButton()
    popup.setMenu(popup_menu)
    check("nút menu mà mọi action đều chết vẫn bị bắt",
          connection_count(popup), 0)
    orphan_a.toggled.connect(lambda checked: None)
    check("nút menu sống khi có một action được nối",
          connection_count(popup) > 0, True)

    # Nút chỉ được nối qua QButtonGroup: trước khi group có slot phải bị coi là
    # CHẾT, sau khi có slot phải được coi là SỐNG. Hai nửa này chứng minh đường
    # QButtonGroup là có thật và không phải cái cớ để bỏ qua nút chết.
    bar = QWidget()
    group = QButtonGroup(bar)
    group.setExclusive(True)
    tab_live = QPushButton("tab", bar)
    tab_live.setCheckable(True)
    group.addButton(tab_live)
    check("nút trong group chưa nối slot vẫn bị bắt",
          connection_count(tab_live), 0)
    group.idClicked.connect(lambda idx: None)
    check("nút nối qua QButtonGroup được tính là sống",
          connection_count(tab_live) > 0, True)
    outside = QPushButton("ngoài group")
    check("nút ngoài group vẫn bị bắt", connection_count(outside), 0)

    menu = QMenu()
    wired = menu.addAction("có slot")
    wired.triggered.connect(lambda checked=False: None)
    orphan = menu.addAction("không slot")
    base = orphan_baseline(menu)
    # Chứng minh baseline cần thật: đếm tuyệt đối thì action mồ côi cũng > 0.
    check("action mồ côi có receivers do Qt tự nối (baseline phải > 0)",
          action_connection(orphan) > 0, True)
    check("menu action mồ côi bị bắt qua baseline",
          action_connection(orphan) <= base, True)
    check("menu action nối được nhận ra qua baseline",
          action_connection(wired) > base, True)
    # Bộ lọc thư viện nối toggled chứ không nối triggered — chỉ quét triggered
    # thì action sống bị báo chết.
    toggle_only = menu.addAction("chỉ nối toggled")
    toggle_only.setCheckable(True)
    toggle_only.toggled.connect(lambda checked: None)
    check("action nối toggled được tính là sống",
          toggle_only in live_actions(menu), True)
    check("action nối triggered được tính là sống",
          wired in live_actions(menu), True)
    check("action mồ côi không nằm trong live_actions",
          orphan in live_actions(menu), False)
    # Nền phải đến từ đúng lớp đang đo, không phải một con số viết tay.
    check("nền QToolButton do chính lớp đó sinh ra",
          baseline_count(QToolButton()), baseline_count(tool_dead))


def show(row):
    print("\n== %s ==" % row["label"])
    print("control tương tác nhìn thấy được: %d, menu: %d, action menu: %d"
          % (row["controls"], row["menus"], row["menu_actions"]))
    for name in row["dead"]:
        print("  CHẾT %s" % name)


def rail_signature(editor):
    """Trạng thái nhìn thấy được mà rail đang chọn: bảng nào hiện, tab nào đang
    bật. Chữ gợi ý tìm kiếm KHÔNG nằm trong chữ ký — đổi một dòng placeholder
    không phải là một tính năng."""
    panels = (editor.library_panel, editor.text_presets_panel,
              editor.sticker_presets_panel, editor.effects_panel)
    shown = tuple(p.isVisible() for p in panels)
    return shown, (
        editor.library_panel.tabs.group.checkedId()
        if editor.library_panel.isVisible() else -1,
        editor.effects_panel.tabs.group.checkedId()
        if editor.effects_panel.isVisible() else -1)


def rail_entries_do_something(editor, app):
    """Mỗi mục trên rail phải mở một bảng thật, và hai mục không được trùng nhau.

    Đây là ải giữ đúng loại rác mà "Brand Kit" để lại: nút rail tồn tại, có slot
    nên máy dò chrome báo SỐNG, nhưng slot chỉ bấm hộ một tab khác rồi đổi dòng
    placeholder — người dùng thấy một tính năng không có thật. Máy dò không tự
    biết một nhãn là lời hứa suông; nó chỉ chốt được hai điều: mọi key đều có
    nhánh xử lý trong MainWindow, và mọi nhánh để lại trạng thái KHÔNG trùng với
    nhánh nào khác.
    """
    import inspect
    import re

    from ui.sidebar import SIDEBAR_ITEMS

    keys = [key for key, _icon, _label in SIDEBAR_ITEMS]
    source = inspect.getsource(editor._on_sidebar_changed)
    handled = re.findall(r'key\s*==\s*"([a-z_]+)"', source)
    check("mọi mục rail đều có nhánh xử lý", sorted(keys), sorted(handled))
    check("không có nhánh xử lý nào cho mục đã bỏ khỏi rail",
          sorted(set(handled) - set(keys)), [])

    def sweep():
        sigs = {}
        for idx, key in sorted(editor.sidebar._keys.items()):
            editor.sidebar.group.button(idx).click()
            for _ in range(6):
                app.processEvents()
            sigs[key] = rail_signature(editor)
        return sigs

    sigs = sweep()
    check("mỗi mục rail bật lên đúng một bảng",
          [any(s[0]) for s in sigs.values()], [True] * len(keys))
    dupes = [k for k, s in sigs.items()
             if list(sigs.values()).count(s) > 1]
    check("hai mục rail không dẫn về cùng một trạng thái", dupes, [])

    # Phản chứng: giả một mục chỉ lặp lại việc của mục khác (kiểu Brand Kit cũ)
    # thì phép thử trùng trạng thái PHẢI đỏ. Nếu nó vẫn xanh thì ải chỉ là giấy.
    real_handler = editor._on_sidebar_changed
    editor.sidebar.currentChanged.disconnect()
    editor.sidebar.currentChanged.connect(
        lambda key: real_handler("transition" if key == "filter" else key))
    try:
        faked = sweep()
        check("mục rail trùng việc bị phát hiện",
              sorted(k for k, s in faked.items()
                     if list(faked.values()).count(s) > 1), ["filter", "transition"])
    finally:
        editor.sidebar.currentChanged.disconnect()
        editor.sidebar.currentChanged.connect(real_handler)
    back = sweep()
    check("rail trở lại bình thường sau phản chứng",
          sorted(k for k, s in back.items()
                 if list(back.values()).count(s) > 1), [])
    return sigs


def main():
    # QApplication phải có TRƯỚC khi tạo widget nào: Qt6 abort ngay tại chỗ
    # nếu không, và abort kiểu này không để lại traceback Python (rc 127,
    # không một dòng output).
    app = QApplication.instance() or QApplication(sys.argv)

    detector_proves_itself()

    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())
    from ui.main_controller import MainController
    controller = MainController()
    controller.show()
    for _ in range(25):
        app.processEvents()
    home = audit_chrome("Trang chủ", controller.home_page)
    show(home)

    from ui.main_window import MainWindow
    editor = MainWindow()
    editor.resize(1500, 900)
    editor.show()
    for _ in range(25):
        app.processEvents()
    editor_rows = audit_chrome("Editor", editor)
    show(editor_rows)

    # Coverage: collector phải với tới menu KHÔNG parented của nút "Menu".
    # findChildren(QMenu) chỉ thấy 1 menu, nên thiếu đường này là audit im
    # lặng báo "sạch" ngay trên cả menu Trợ giúp.
    menus = collect_menus(editor)
    titles = {m.title() for m in menus}
    help_menu = [m for m in menus if m.title() == "Trợ giúp"]
    help_texts = {a.text() for m in help_menu for a in m.actions()}
    check("audit thấy menu của nút Menu (không cha, chỉ qua setMenu)",
          "Trợ giúp" in titles, True)
    check("audit thấy cả 2 action menu Trợ giúp",
          len(help_texts & {"Phím tắt", "Về Clinging"}), 2)
    check("audit thấy nhiều menu hơn findChildren(QMenu) đơn thuần",
          len(menus) > len(editor.findChildren(QMenu)), True)
    # Máy dò phải thấy đúng số nút nhìn thấy được, không đếm cả những thứ ẩn.
    check("audit editor thấy ít nhất 20 control nhìn thấy được",
          editor_rows["controls"] >= 20, True)
    check("control ẩn không bị đếm nhầm",
          len(visible_interactive(editor)), editor_rows["controls"])

    total = home["dead"] + editor_rows["dead"]
    check("không còn chrome chết nào nhìn thấy được", total, [])

    rail = rail_entries_do_something(editor, app)
    print("  rail: %s" % ", ".join("%s->tab%s" % (k, s[1]) for k, s in rail.items()))

    editor.close()
    controller.close()
    for _ in range(8):
        app.processEvents()

    print("\n%d gates, %d FAIL" % (STATS["gates"], len(FAILS)))
    for line in FAILS:
        print("FAIL ", line)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
