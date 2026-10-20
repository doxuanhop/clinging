"""Ve icon Font Awesome tu TTF trong `assets/icons`, khong đi qua qtawesome.

Vi sao phai co module nay: do tren chinh may cau hinh thap nay
(`scratch/boot_low_spec_probe.py`, do bang dong ho dat trong long `main._boot()`),
`import qtawesome` mot minh ngot 0,62 s trong cua so boot, va ca seam qtawesome
la 0,86 s so voi 0,044 s cua bo ve nay — kem theo ~29 MB RAM private. Phan lon
khong phai ve glyph: `import qtawesome` keo theo `qtpy` va `PySide6.QtOpenGL` /
`QtDataVisualization` — 20 module, khong mot ai dung toi. San ve glyph that chi
0,043 s cho 13 hinh trong boot that.

Giong het qtawesome ve hieu qua: cung mot file TTF (md5 kiem chung bang
`scratch/make_icon_assets.py`), cung ten ho font, cung cong thuc
`drawText(rect, AlignCenter, char)` voi cỡ chữ = round(0.875 * chieu cao o),
cung `QIconEngine` (khong phai `QIcon` subclass — thu roi: `QAction.icon()` tra
ve ban copy da bi cat mat lop con, pixmap ra rong).

Khong import gi o dau file ngoai PySide6: module phai trong veo luc `import`,
vi chinh thoi gian import la cai can cat.
"""
import json
import os
import sys

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QIcon, QIconEngine, QImage,
                           QFont, QFontDatabase, QPainter, QPixmap)

_TTF = "fontawesome6-solid-6.7.2.ttf"
_CHARMAP = "fontawesome6-solid-charmap.json"
PREFIX = "fa6s"

_state = None
_pixmap_cache = {}


def asset_root():
    """Thu muc `assets` — trong bundle PyInstaller nam o _MEIPASS."""
    root = getattr(sys, "_MEIPASS", None)
    if root:
        return os.path.join(root, "assets")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "assets")


def _load():
    """Nap font + charmap MOT LAN, sau khi QGuiApplication da ton tai."""
    global _state
    if _state is not None:
        return _state
    if QGuiApplication.instance() is None:
        raise RuntimeError(
            "fontawesome.icon() can QGuiApplication; goi sau QApplication()")
    base = os.path.join(asset_root(), "icons")
    ttf_path = os.path.join(base, _TTF)
    map_path = os.path.join(base, _CHARMAP)
    for path in (ttf_path, map_path):
        if not os.path.isfile(path):
            raise RuntimeError(
                "thieu tai nguyen icon %s — chay scratch/make_icon_assets.py"
                % os.path.basename(path))
    with open(ttf_path, "rb") as handle:
        font_bytes = handle.read()
    with open(map_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    fid = QFontDatabase.addApplicationFontFromData(font_bytes)
    families = QFontDatabase.applicationFontFamilies(fid)
    if not families:
        raise RuntimeError("Qt khong nap duoc %s" % ttf_path)
    _state = {"family": families[0],
              "glyphs": {name: chr(int(code, 16))
                         for name, code in payload["glyphs"].items()}}
    return _state


def names():
    """Toan bo ten (khong tien to) ma bo ve nay dung duoc."""
    return set(_load()["glyphs"])


def glyph_for(name):
    """Tra ve ky tu glyph cua "fa6s.play"; ten la thi bao roi, khong ve trong.

    Kieu bao loi nay la thu nghia cua gate `scratch/icon_name_audit.py`: mot
    ten ngoai bo Font Awesome Free phai chore, khong duoc im lang in ra o trang.
    """
    state = _load()
    prefix, _, short = name.partition(".")
    if prefix != PREFIX:
        raise ValueError(
            "bo ve nay chi co %s.* (muon them %s.* thi mo rong "
            "scratch/make_icon_assets.py): %r" % (PREFIX, prefix, name))
    try:
        return state["glyphs"][short]
    except KeyError:
        raise ValueError("khong co glyph %r trong %s" % (short, _CHARMAP))


def _screen_dpr():
    try:
        return float(QGuiApplication.primaryScreen().devicePixelRatio()) or 1.0
    except Exception:
        return 1.0


def _render(name, px, color):
    """QImage px x px dung o thiet bi (device pixel), khong phai o logic."""
    state = _load()
    key = (name, color, px)
    img = _pixmap_cache.get(key)
    if img is not None:
        return img
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    font = QFont(state["family"])
    font.setPixelSize(max(6, int(round(0.875 * px))))
    font.setStyleName("Solid")
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(img.rect(), int(Qt.AlignCenter | Qt.AlignVCenter),
                     glyph_for(name))
    painter.end()
    _pixmap_cache[key] = img
    return img


class _GlyphEngine(QIconEngine):
    """Engine, khong phai QIcon: QIcon giu con tro toi engine nen mot QAction
    copy icon van ve dung hinh (QIcon subclass thi bi cat thanh QIcon thuong).
    """

    def __init__(self, name, color):
        super().__init__()
        self._name = name
        self._color = color

    def _dpr_for(self, painter):
        device = painter.device() if painter else None
        try:
            return float(device.devicePixelRatio()) or 1.0
        except Exception:
            return _screen_dpr()

    def paint(self, painter, rect, mode=QIcon.Normal, state=QIcon.Off):
        dpr = self._dpr_for(painter)
        px = max(1, int(round(rect.height() * dpr)))
        pm = QPixmap.fromImage(_render(self._name, px, self._color))
        pm.setDevicePixelRatio(dpr)
        painter.drawPixmap(QPoint(rect.x(), rect.y()), pm)

    def pixmap(self, size, mode=QIcon.Normal, state=QIcon.Off):
        # Qt da nhan kich thuoc theo device pixel ratio TRUOC khi goi engine
        # (QIcon.pixmap(16) tren man 1,25x den day bang QSize(20,20)), nen o
        # day phai ve DUNG size va khong duoc nhan DPR lan nua — lam thi anh
        # to hon cua qtawesome va lech tung pixel khi doi chieu.
        img = _render(self._name, max(1, int(size.width())), self._color)
        return QPixmap.fromImage(img)

    def iconSize(self, mode=QIcon.Normal, state=QIcon.Off):
        return QSize(16, 16)

    def clone(self):
        return _GlyphEngine(self._name, self._color)

    def name(self):
        return ""


def icon(name, color="#FFFFFF", *args, **kwargs):
    """Dung ng thay cho `qtawesome.icon(name, color=...)`.

    Tham so thua bi bo: ca repo chi dung `color=` (kiem tra bang
    `scratch/icon_name_audit.py`), va neu mot ngay nao co nguoi truyen
    `rotation=`/`options=` thi that ro hon la im lang ve hinh khong xoay.

    Ten duoc kiem tra NGAY DAY, luc con dung trong land cua Python. De no
    chore lan dau tien luc ve (trong `glyph_for` goi tu `QIconEngine.pixmap`,
    mot callback ma C++ goi lai) thi loi khong con la traceback nua: Qt khong
    the mang exception cua Python nguoc qua bien, nen ca process that bai
    kieu 0xC0000409 va khong de lai mot dong log. Do la cai ma
    `scratch/gate_discrimination_probe.py` da bat duoc 2026-10-20, khi mot ten
    glyph gia trong `ui/` lam dung do cua chinh no chay an.
    """
    used = [k for k in kwargs if k != "color"]
    if used or args:
        raise ValueError(
            "bo ve glyph cuc bo chi ho tro color=; tham so khong biet: %s %s"
            % (used, args))
    glyph_for(name)
    return QIcon(_GlyphEngine(name, color))
