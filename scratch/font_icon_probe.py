"""Gate "khong con emoji - icon tool/menu phai la font icon".

Hai lop bang chung:
  1. Quet tinh: khong con ky tu emoji trong chuoi hien thi cua ui/widgets.
  2. Do that tren widget: moi font icon phai sinh ra pixmap co pixel khong
     trong, va cac be mat da sua phai render duoc ma khong loi.
Kem anh capture tung be mat de mat nhin, khong chi tin vao dong PASS.
"""
import ast
import ctypes
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Console mac dinh cua may nay la cp1252: mot dong in ra chua ky tu non-ASCII
# (o day la danh sach emoji con lai) lam probe chet giua chung va rc=1 vi
# UnicodeEncodeError chu khong vi san pham.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

FAILS = []
OUT = os.path.join(ROOT, "scratch")

EMOJI_RANGES = [(0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                (0xFE00, 0xFE0F), (0x25A0, 0x25FF)]
# Du lieu cu: sticker cua du an cu luu "emoji + ten" trong name, canvas ve lại
# dung theo noi dung nguoi dung chon day, khong phai icon giao dien. Danh bau
# bang NOI DUNG dong lenh, khong bang so dong: so dong cua no da tr 468 -> 488
# vi mot lan sua file khac, va phep danh bau theo so dong bien that thanh FAIL
# gia (probe do rc=1 vi dong nguoi dung khong the sua).
ALLOWED = {os.path.join("ui", "graphics_canvas_item.py"): {'or "\u25cf"'}}


def is_emoji(ch):
    code = ord(ch)
    return any(a <= code <= b for a, b in EMOJI_RANGES)


def _docstring_lines(tree):
    """Dong thuoc chu thich/docstring - do thi co the ve sơ ho (▼, ←)
    ma khong bao gio hien len UI, nen khong tinh là emoji giao dien."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            first = node.body[0]
            for offset in range(doc.count("\n") + 1):
                lines.add(first.lineno + offset)
    return lines


def _is_glyph_only(value):
    """Chuoi ngan chi gom ky tu dung mot minh - dau hieu "ky tu thay icon".

    Ky tu unicode luon phu thuoc font cua may dung, nen no khong doi mau
    theo chu de va co the in ra o trong. Nut cong cu phai dung font icon.
    """
    stripped = value.strip()
    return 0 < len(stripped) <= 2 and not any(ch.isalnum() for ch in stripped)


def scan_glyph_buttons():
    """Tim nut QPushButton/QToolButton dung ky tu lam bieu tuong.

    Chi tinh nut: nhan " / " hay "•" giua hai chuoi la van ban that, con nut
    ma chi co mot ky tu thi do la icon muon - phai qua font_icon().
    """
    hits = []
    for root in ("ui", "widgets"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, ROOT)
                source = open(path, encoding="utf-8").read()
                tree = ast.parse(source, filename=path)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or not node.args:
                        continue
                    callee = getattr(node.func, "attr", None) or \
                        getattr(node.func, "id", None)
                    if callee not in ("QPushButton", "QToolButton", "setText"):
                        continue
                    first = node.args[0]
                    if (isinstance(first, ast.Constant)
                            and isinstance(first.value, str)
                            and _is_glyph_only(first.value)):
                        hits.append("%s:%d %s(%r)" % (
                            rel, node.lineno, callee, first.value))
    return hits


def scan_sources():
    """Chi kiem tra hang chu (string constant) that, khong doc comment."""
    hits = []
    for root in ("ui", "widgets", "core"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, root)):
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, ROOT)
                allowed = ALLOWED.get(rel, set())
                text = open(path, encoding="utf-8").read()
                tree = ast.parse(text, filename=path)
                doc_lines = _docstring_lines(tree)
                physical = text.splitlines()
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant) or not isinstance(
                            node.value, str):
                        continue
                    if node.lineno in doc_lines:
                        continue
                    found = [c for c in node.value if is_emoji(c)]
                    if found and not any(
                            marker in physical[node.lineno - 1]
                            for marker in allowed):
                        hits.append((rel, node.lineno,
                                     "".join(sorted(set(found))),
                                     physical[node.lineno - 1].strip()[:80]))
    return hits


def check(label, got, want):
    ok = got == want
    print("%-58s %s  got=%r" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append(label)
    return ok


def pump(app, times=10):
    for _ in range(times):
        app.processEvents()


def grab(widget, name):
    path = os.path.join(OUT, name)
    widget.grab().save(path)
    print("  saved %s" % name)
    return path


def opaque_fraction(painted):
    """Ty le pixel khong trong suat - chung minh font icon thuc su ve."""
    image = painted.toImage() if hasattr(painted, "toImage") else painted
    total = image.width() * image.height()
    if not total:
        return 0.0
    solid = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixel(x, y) & 0xFF:
                solid += 1
    return solid / float(total)


def _button_types():
    from PySide6.QtWidgets import QPushButton, QToolButton
    # IconButton cua app la QToolButton, khong phai QPushButton, nen phai quét cả hai.
    return (QPushButton, QToolButton)


def surface_pixmaps(widget):
    """Moi icon that dang render tren be mat, kem nhan dien dang thu."""
    from PySide6.QtWidgets import QLabel
    out = []
    for cls in _button_types():
        for w in widget.findChildren(cls):
            ic = w.icon()
            if ic is not None and not ic.isNull():
                out.append(("nut[%s]" % (w.text() or w.objectName()),
                            ic.pixmap(16, 16)))
    for w in widget.findChildren(QLabel):
        pm = w.pixmap()
        if pm is not None and not pm.isNull():
            out.append(("nhan[%s]" % (w.objectName() or "?"), pm))
    return out


def sweep(widget, tag):
    """Toan bo be mat: khong con emoji trong nhan va khong con icon trang.

    kiem "duoc" ma khong ve thi nguoi dung thay cho trong, nen ca hai lop
    phai do tren widget that chu khong doc chuoi trong ma nguon.
    """
    from PySide6.QtWidgets import QLabel
    labels = widget.findChildren(QLabel)
    buttons = []
    for cls in _button_types():
        buttons = buttons + widget.findChildren(cls)
    bad_text = [w.text() for w in labels + buttons if w.text()
                and any(is_emoji(c) for c in w.text())]
    check("%s: nhan khong con emoji" % tag, bad_text, [])
    glyph = [w.text() for w in buttons if _is_glyph_only(w.text())]
    check("%s: khong nut nao dung ky tu lam bieu tuong" % tag, glyph, [])
    pms = surface_pixmaps(widget)
    blank = [name for name, pm in pms if opaque_fraction(pm) <= 0.02]
    check("%s: %d font icon deu ve co pixel" % (tag, len(pms)), blank, [])
    return len(pms)


def main():
    ctypes.windll.user32.SetProcessDPIAware()

    # ── Lop 1: quet tinh ────────────────────────────────────────
    hits = scan_sources()
    for rel, lineno, chars, snippet in hits:
        print("  emoji con lai: %s:%d %s | %s" % (rel, lineno, chars, snippet))
    check("khong con emoji trong chuoi UI", len(hits), 0)

    glyph_hits = scan_glyph_buttons()
    for entry in glyph_hits:
        print("  ky tu thay icon: %s" % entry)
    check("khong con nut dung ky tu lam bieu tuong", len(glyph_hits), 0)

    # ── Lop 1b: moi ten font icon trong UI phai ton tai trong FA6 Free ──
    # Mot ten sai khong chi in ra o trống mà còn lam crash panel luc mo.
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    rc = subprocess.call([sys.executable, "-u",
                          os.path.join(OUT, "icon_name_audit.py")],
                         cwd=ROOT, env=env)
    check("moi ten font icon giai quyet va ve duoc", rc, 0)

    app = QApplication(sys.argv)
    from theme import theme_manager
    app.setStyleSheet(theme_manager.stylesheet())

    # ── Lop 2: font icon phai ve duoc ───────────────────────────
    from widgets.common import font_icon, icon_pixmap, set_label_icon
    from PySide6.QtWidgets import QLabel
    for name in ("fa6s.xmark", "fa6s.diamond", "fa6s.chevron-down",
                 "fa6s.scissors", "fa6s.clone", "fa6s.trash",
                 "fa6s.wand-magic-sparkles", "fa6s.circle",
                 "fa6s.thumbs-up", "fa6s.triangle-exclamation"):
        label = QLabel()
        set_label_icon(label, name, 16, "#FFFFFF")
        check("%s sinh pixmap khong trong" % name,
              opaque_fraction(label.pixmap()) > 0.02, True)

    # ── Home page: loi chao va nut Sap xep ──────────────────────
    from ui.home_page import HomePage
    home = HomePage()
    home.resize(1500, 900)
    home.show()
    pump(app)
    sweep(home, "trang chu")
    grab(home, "fonticon_home.png")

    # ── Panel Sticker: nhan preset khong con emoji ──────────────
    from ui.presets_panel import PresetsPanel, STICKER_PRESETS
    stickers = PresetsPanel("sticker")
    stickers.resize(320, 700)
    stickers.show()
    pump(app)
    check("preset sticker khong con emoji trong nhan",
          any(is_emoji(c) for p in STICKER_PRESETS for c in p["label"]), False)
    sweep(stickers, "panel sticker")
    grab(stickers, "fonticon_stickers.png")

    # ── Anh keo tha sticker: phai la font icon, khong phai chu cat ngan ──
    from ui.presets_panel import PresetDragCard
    card = PresetDragCard(STICKER_PRESETS[0], "sticker")
    drag_pm = card._drag_pixmap()
    drag_img = drag_pm.toImage()
    target = int(STICKER_PRESETS[0]["color"].lstrip("#"), 16)
    near = 0
    for y in range(drag_img.height()):
        for x in range(drag_img.width()):
            px = drag_img.pixel(x, y)
            if all(abs(((px >> sh) & 0xFF) - ((target >> sh) & 0xFF)) <= 24
                   for sh in (16, 8, 0)):
                near += 1
    drag_path = os.path.join(OUT, "fonticon_drag.png")
    drag_pm.save(drag_path)
    print("  saved fonticon_drag.png")
    check("anh keo tha ve net font icon mau cua sticker", near >= 20, True)

    # ── Panel Hieu ung: icon overlay ────────────────────────────
    from ui.effects_panel import EffectsPanel
    effects = EffectsPanel()
    effects.resize(320, 700)
    effects.show()
    pump(app)
    sweep(effects, "panel hieu ung")
    grab(effects, "fonticon_effects.png")

    # ── Huy hieu ung tren clip (badge) ──────────────────────────
    from core.timeline_model import ClipModel
    from ui.graphics.clip_item import ClipItem
    from core.time_mapper import TimePixelMapper
    clip = ClipModel(clip_id="c1", name="clip.mp4", source_path="clip.mp4",
                     media_type="video", start_time=0.0, duration=4.0)
    # Hieu ung phai la EffectData THAT: `deserialize_effects` la duong duy nhat
    # mot file .clinq day vao model, va the thuoc tinh doc `effect.name`. Ban dict
    # la hinh cua du an tk cu — khong co duong nao trong app nay cho no vao model,
    # nen de nguyen thi probe chet o ClipPropertiesWidget chu khong do san pham.
    from core.project_storage import deserialize_effects
    clip.effects = deserialize_effects([
        {"name": "Warm Tone", "category": "Sắc thái", "intensity": 1.0},
        {"name": "Pop Art", "category": "Sắc thái", "intensity": 1.0},
    ])
    item = ClipItem(clip, TimePixelMapper())
    from PySide6.QtWidgets import QGraphicsScene
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    scene = QGraphicsScene()
    scene.addItem(item)
    source = item.boundingRect().adjusted(-2, -2, 20, 20)
    shot = QImage(int(source.width()), int(source.height()),
                  QImage.Format_ARGB32_Premultiplied)
    shot.fill(Qt.transparent)
    painter = QPainter(shot)
    scene.render(painter, QRectF(shot.rect()), source)
    painter.end()
    path = os.path.join(OUT, "fonticon_badge.png")
    shot.save(path)
    print("  saved fonticon_badge.png")
    check("badge hieu dung ve co net", opaque_fraction(shot) > 0.5, True)
    check("badge co net font icon (khong phai chu)",
          icon_pixmap("fa6s.wand-magic-sparkles", 10, "#FFFFFF").isNull(), False)

    # ── Menu chu clip: moi muc phai co QIcon font ───────────────
    menu, actions = item._build_context_menu()
    check("menu clip co dung so muc theo loai",
          [a.text() for a in actions],
          ["Cắt tại Playhead", "Nhân bản clip", "Tách âm thanh", "Xóa clip"]
          if item._detachable_audio_clip()
          else ["Cắt tại Playhead", "Nhân bản clip", "Xóa clip"])
    check("moi muc menu co font icon",
          all(not a.icon().isNull() for a in actions), True)
    check("moi muc font icon ve duoc pixel",
          all(opaque_fraction(a.icon().pixmap(16, 16)) > 0.02 for a in actions),
          True)
    check("nhan menu khong con emoji",
          any(is_emoji(c) for a in actions for c in a.text()), False)
    print("  menu: " + " | ".join("%s" % a.text() for a in actions))
    menu.show()
    pump(app)
    grab(menu, "fonticon_clip_menu.png")
    menu.hide()

    # ── Form thuoc tinh clip: nut keyframe phai doi mau theo trang thai ──
    # QIcon khong theo QSS `color`, nen trang thai danh/dau phai nuong lai
    # pixmap; neu khong thi nguoi dung khong biet nut nao dang bat.
    from PySide6.QtCore import QSize
    from ui.properties_panel import ClipPropertiesWidget, set_keyframe_button_state
    form = ClipPropertiesWidget(clip)
    form.resize(330, 900)
    form.show()
    pump(app)
    sweep(form, "form thuoc tinh clip")
    grab(form, "fonticon_props.png")
    btns = list(getattr(form, "_kf_buttons", {}).values())
    check("form co nut keyframe", len(btns) > 0, True)
    if btns:
        btn = btns[0]
        set_keyframe_button_state(btn, False)
        idle = btn.icon().pixmap(QSize(11, 11)).toImage()
        set_keyframe_button_state(btn, True)
        active = btn.icon().pixmap(QSize(11, 11)).toImage()
        check("nut keyframe ve duoc o ca hai trang thai",
              [opaque_fraction(idle) > 0.02, opaque_fraction(active) > 0.02],
              [True, True])
        check("nut keyframe doi mau khi bat",
              idle.pixel(idle.width() // 2, idle.height() // 2)
              != active.pixel(active.width() // 2, active.height() // 2), True)
    form.close()

    # ── Hop thoai Custom: nut dong xmark ────────────────────────
    from ui.custom_dialog import CustomDialog
    dialog = CustomDialog(title="Xac nhan", message="Mot thong bao tuy chinh")
    dialog.show()
    pump(app)
    sweep(dialog, "hop thoai tuy chinh")
    grab(dialog, "fonticon_dialog.png")
    dialog.close()

    # ── Export dialog: nut dong + cham buoc ─────────────────────
    from ui.export_dialog import ExportDialog
    from core.timeline_model import TimelineModel
    export = ExportDialog(TimelineModel())
    export.show()
    pump(app)
    sweep(export, "hop thoai xuat")
    grab(export, "fonticon_export.png")
    export.close()

    # ── Toan bo cua so bien tap ─────────────────────────────────
    # Toolbar, sidebar, title bar, properties panel: day la cho emoji
    # tung xuat hien nhieu nhat, nen quet het widget trong mot lan.
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1920, 1035)
    win.show()
    pump(app, 20)
    sweep(win, "cua so bien tap")
    grab(win, "fonticon_window.png")
    win.close()

    print("\n%s (%d fail)" % ("ALL PASS" if not FAILS else
                              "FAILED: " + "; ".join(FAILS), len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
