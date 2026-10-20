"""scratch/_graph_cf_child.py

Chay --graph-report duoi mot loi cu da duoc phat lai trong bo nho (xem
scratch/graph_report_counterfactual.py). Khong sua file nao ca.
"""

import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


def patch(mode):
    if mode == "clean":
        return
    if mode == "curve":
        # Loi DA SHIP: diem mau cuoi ghi nham t0 -> duong noi gay keo nguoc ve
        # trai qua ca lane, nhin thay duoc bang mat thuong.
        from core import keyframe_graph as kg
        original = kg.sample_curve

        def broken(frames, prop, default, t0, t1, samples=120):
            out = list(original(frames, prop, default, t0, t1,
                                samples=samples))
            if out:
                out[-1] = out[0]
            return out
        kg.sample_curve = broken
        return
    if mode == "nodes":
        # Loi DA SHIP: update_from_model chi dinh vi lai moc cu, khong dung lai
        # bo moc khi model doi -> vien kim cuong o lai sau khi hoan tac.
        from ui.graphics.clip_item import ClipItem
        ClipItem._node_signature = lambda self: self._model_signature()
        return
    if mode == "blit":
        # Loi DA SHIP trong chinh ANH BANG CHUNG: paint len canvas DPR 1 bang
        # drawPixmap(x, y, pm) co pm DPR 1.25 -> Qt hieu kich thuoc pixmap la
        # LOGIC va ep no xuong 80%. Nét mong (dau tru cua "-372px") bi xoa.
        # Tai day: giu nguyen loi cua Qt bang cach ve vao rect 80% do.
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter
        original = QPainter.drawPixmap

        def drawPixmap(self, *args, **kwargs):
            if (len(args) == 2 and isinstance(args[0], QRect)
                    and hasattr(args[1], "devicePixelRatio")):
                pm, rect = args[1], args[0]
                dpr = pm.devicePixelRatio() or 1.0
                if (rect.width() == pm.width() and rect.height() == pm.height()
                        and dpr > 1.0):
                    return original(self, QRect(rect.x(), rect.y(),
                                                int(rect.width() / dpr),
                                                int(rect.height() / dpr)), pm)
            return original(self, *args, **kwargs)
        QPainter.drawPixmap = drawPixmap
        return
    raise SystemExit("mode khong biet: %r" % mode)


def main():
    mode = sys.argv[1]
    report = sys.argv[2]
    patch(mode)
    from diagnostics import run_graph_report
    return run_graph_report([sys.argv[0], report])


if __name__ == "__main__":
    sys.exit(main())
