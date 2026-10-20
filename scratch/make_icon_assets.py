"""Trich Font Awesome 6 Free Solid cua qtawesome ra `assets/icons/`.

Ly do phai co script nay thay vi tai tay file ve: bo thay the phai dung DUNG
byte font va DUNG charmap ma qtawesome van dung, neu khong mot ten lech code
point se ve sai hinh ma khong bao loi. Script cung ghi bang chung doi chieu
(so byte, md5, so ten) de lan sau tai tao lai van ra cai gi.

    python scratch/make_icon_assets.py

Chi lay `fa6s` vi toan bo 101 ten UI dung deu la fa6s.* (do bang
scratch/icon_name_audit.py); cac bo font khac cua qtawesome (material design,
phosphor, remix, codicon, FA5, fa6r/fa6b) la ~5 MB trong bundle khong ai dung.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "icons")
PREFIX = "fa6s"
VERSION = "6.7.2"


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])  # noqa: F841  (qtawesome nap font qua QGuiApplication)
    import qtawesome as qta
    inst = qta._instance()
    font_bytes = inst.fontdata[PREFIX]
    charmap = inst.charmap[PREFIX]
    family = inst.fontname[PREFIX]

    os.makedirs(OUT, exist_ok=True)
    ttf = os.path.join(OUT, "fontawesome6-solid-%s.ttf" % VERSION)
    with open(ttf, "wb") as handle:
        handle.write(font_bytes)
    # charmap luu ky tu don; JSON hoa ra ma codepoint de doc ma khong can Qt.
    payload = {"prefix": PREFIX, "family": family, "version": VERSION,
               "source": "qtawesome %s" % getattr(qta, "__version__", "?"),
               "license": "Font Awesome Free 6.7.2 (CC BY 4.0 / SIL OFL 1.1)",
               "glyphs": {name: "%X" % ord(ch) for name, ch in charmap.items()}}
    cmap_path = os.path.join(OUT, "fontawesome6-solid-charmap.json")
    with open(cmap_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=0)

    # Doc lai va doi chieu: file tren dia phai cho ra dung những gi qtawesome
    # tra trong bo nho, khong phai chi "viet xong".
    back = json.load(open(cmap_path, encoding="utf-8"))
    same_bytes = open(ttf, "rb").read() == font_bytes
    same_map = {k: chr(int(v, 16)) for k, v in back["glyphs"].items()} == charmap
    print("ttf   %8d bytes  md5 %s  doc-lai-khop=%s"
          % (len(font_bytes), hashlib.md5(font_bytes).hexdigest()[:12], same_bytes))
    print("charmap %6d ten  family=%r  doc-lai-khop=%s"
          % (len(charmap), family, same_map))
    print("->", os.path.relpath(ttf, ROOT))
    print("->", os.path.relpath(cmap_path, ROOT))
    if not (same_bytes and same_map):
        print("FAIL: tai nguyen tren dia khong khop voi qtawesome")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
