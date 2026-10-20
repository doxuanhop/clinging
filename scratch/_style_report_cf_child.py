"""Mot lan chay that cua --style-report, voi DUNG MOT khop bi cat trong bo nho.

Parent (style_report_counterfactual.py) moi spawn mot process nhu the nay:
cat sai khop thi gate PHAI do, va do dung vao cai khop do — do vi mot loi
khac cung tinh la khong chung minh duoc gi.
"""
import faulthandler
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
faulthandler.enable()

mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
OUT = os.path.join(os.environ.get("TEMP", ROOT), "clinging_style_cf_%s.json" % mode)

from PySide6.QtGui import QPainterPath  # noqa: E402
from ui.graphics_canvas_item import CanvasClipItem, HANDLE_SIZE  # noqa: E402

if mode == "dyn_rect":
    # Cong thuc CU: vung cua item noi theo hieu ung dang gay -> scene mat ding
    # index, va bat dong dang geometry ma gate giu cung mat.
    from core.aura_paint import aura_margin

    def old_bounding_rect(self):
        bounding = self.rect()
        m = HANDLE_SIZE + 4.0 + aura_margin(
            bounding, getattr(self.clip_model, "effects", None) or [])
        return bounding.adjusted(-m, -m, m, m)
    CanvasClipItem.boundingRect = old_bounding_rect
elif mode == "no_reserve":
    # Fix dung nhung danh het cho aura loang: gate "aura_khong_doi_geometry"
    # con phan "giu cho loang" phai do.
    def tight_bounding_rect(self):
        m = HANDLE_SIZE + 4.0
        return self.rect().adjusted(-m, -m, m, m)
    CanvasClipItem.boundingRect = tight_bounding_rect
elif mode == "fat_shape":
    # boundingRect dung nhung de vung loang quyet dinh chuot: clip dính từ rất
    # xa mép, va phep nam mép canvas cua smart-snap lech theo.
    def fat_shape(self):
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path
    CanvasClipItem.shape = fat_shape
elif mode == "dead_card":
    # The aura hinh thu van day du nhung cu bam khong chuyen vao model.
    from ui.main_window import MainWindow
    MainWindow._on_effect_applied = lambda self, data: None
elif mode == "same_aura":
    # Moi the deu ghi mot khoa aura: 8 the chi ra mot kieu. Day la loi ten
    # giua EFFECT_PRESETS va registry, khong co loi nao o khac.
    from core import aura_paint
    original_spec = aura_paint.aura_spec

    def one_kind(effects):
        spec = original_spec(effects)
        return ("fire",) + spec[1:] if spec else None
    aura_paint.aura_spec = one_kind
elif mode == "two_undo":
    # Dong hop thoai lop phu de lai HAI muc lịch sử: Ctrl+Z ke tiep an mất một
    # nửa việc của người dùng.
    from ui.recap_overlay_dialog import RecapOverlayDialog
    original_close = RecapOverlayDialog._on_close

    def double_close(self):
        original_close(self)
        from core.commands import SetRecapOverlayCommand
        self.main_window.timeline_panel.undo_stack.push(
            SetRecapOverlayCommand(self._model, dict(self._model.recap_overlay),
                                   before=dict(self._model.recap_overlay)))
    RecapOverlayDialog._on_close = double_close
elif mode == "karaoke_dead":
    # Combo van du 9 dong nhung duong ve bo qua style.
    from core import text_paint
    original = text_paint.paint_animated_text

    def ignore_style(painter, *a, **kw):
        kw["style"] = "none"
        return original(painter, *a, **kw)
    text_paint.paint_animated_text = ignore_style
elif mode == "flame_blob":
    # Cong thuc CU cua quầng lửa: 8 ban sao lech, alpha 90 -> alpha hieu dung
    # 0.95, lap kin moi lo chu. Van "doi mau that" nen khong gate nao so anh
    # bat duoc; chi phep dem lo chu moi thay.
    from core import karaoke_paint
    karaoke_paint._FLAME_HALO = (0.06, 0.09, 0.05, 90)
elif mode == "flame_no_halo":
    # Chet gian lan 2: "sua" khối đặc bằng cách BO HET quầng thì chữ trở về
    # mong nhu chu thuong, nhưng kieu lua cung mat luon ngan lua.
    from core import karaoke_paint
    karaoke_paint._FLAME_HALO = (0.0, 0.0, 0.0, 0.0)
elif mode != "clean":
    raise SystemExit("mode khong ton tai: " + mode)

import diagnostics  # noqa: E402

rc = diagnostics.run_style_report(["--style-report", OUT])
try:
    with open(OUT, encoding="utf-8") as handle:
        payload = json.load(handle)
    failed = sorted(k for k, v in payload["checks"].items() if not v)
    # Mot check co the do vi NHIEU ly do khac nhau; parent can biet dung canh
    # nao nap, neu khong thi "do" o canh sai van tinh la xanh.
    loi = payload.get("flame_loi") or []
    if loi:
        failed.append("loi=%s" % "; ".join(loi))
except Exception as exc:                                  # noqa: BLE001
    failed = ["KHONG_CO_BAO_CAO:%s" % type(exc).__name__]
print("MODE %s rc=%d failed=%s" % (mode, rc, ",".join(failed) or "-"),
      file=sys.stderr, flush=True)
sys.stdout.flush()
os._exit(1 if rc == 0 and mode != "clean" else rc)
