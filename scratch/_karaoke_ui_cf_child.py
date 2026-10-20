"""Con: chạy karaoke_ui_probe dưới ĐÚNG MỘT lỗi phát lại trong bộ nhớ. Không sửa file nào.

Mỗi mode cắt một khớp của chuỗi "nhãn -> model -> vẽ lại -> pixel":

  registry      combo thiếu một kiểu (danh sách dựng widget và danh sách khoá lệch nhau)
  labels        hai dòng cùng nhãn -> người dùng không phân biệt được kiểu nào
  dead_write    tín hiệu nối nhưng handler rỗng -> model đứng yên
  no_refresh    model đổi nhưng chẳng ai bảo item vẽ lại -> màn hình đứng yên
  no_style      item vẽ lại nhưng bỏ qua text_style -> preview vẫn là chữ trắng
  undo_push     mỗi cú nhấp thêm một mục undo (sai quy ước tab Chữ)
  dupe_key      một dòng ghi nhầm khoá của dòng khác
  no_readback   mở lại properties không đọc kiểu trong model
  flame_dead    riêng kiểu flame thành chữ thường -> hai ô ảnh chứng minh giống nhau
  clean         không mutation nào, phải XANH

Parent (scratch/karaoke_ui_probe_counterfactual.py) kiểm tra lỗi đó làm đỏ ĐÚNG gate
nào — đỏ sai chỗ cũng tính là probe giả.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scratch"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def patch(mode):
    from core import karaoke_paint, text_paint
    from ui.graphics_canvas_item import TextClipItem
    from ui.properties_panel import ClipPropertiesWidget

    if mode == "clean":
        return
    if mode == "registry":
        # Danh sách nhãn của panel ngắn hơn STYLE_KEYS: một kiểu biến mất khỏi
        # combo trong khi model vẫn nhận khoá của nó.
        karaoke_paint.KARAOKE_STYLES = list(karaoke_paint.KARAOKE_STYLES)[:-1]
        return
    if mode == "labels":
        # Khoá vẫn đủ 8 nhưng hai dòng trùng nhãn — người dùng bấm nhầm kiểu.
        items = list(karaoke_paint.KARAOKE_STYLES)
        items[1] = (items[1][0], items[2][1])
        karaoke_paint.KARAOKE_STYLES = items
        return
    if mode == "dead_write":
        ClipPropertiesWidget._on_text_style_changed = lambda self, index: None
        return
    if mode == "no_refresh":
        ClipPropertiesWidget._refresh_canvas = lambda self: None
        return
    if mode == "no_style":
        # Item vẫn update() (theo đường khác) nhưng không bao giờ dựng lại vẽ
        # theo text_style — đúng lỗi "combo đủ, model đúng, màn hình sai".
        TextClipItem.refresh_style = lambda self: None
        return
    if mode == "undo_push":
        original = ClipPropertiesWidget._on_text_style_changed

        class _Noop:
            # UndoStack.push() gọi command.execute() — một QUndoCommand của Qt
            # không có hàm đó, lỗi ném bên trong slot sẽ bị nuốt và stack vẫn
            # đứng yên: phép phản chứng sẽ "xanh" vì lý do sai.
            def execute(self): pass
            def undo(self): pass
            def description(self): return "noop"

        def with_undo(self, index):
            original(self, index)
            mw = self._find_main_window()
            if mw is not None:
                mw.timeline_panel.undo_stack.push(_Noop())
        ClipPropertiesWidget._on_text_style_changed = with_undo
        return
    if mode == "dupe_key":
        # Dòng thứ 5 ghi khoá của dòng 1: gate "mọi dòng phải in lại tên nó".
        def shifted(self, index):
            if index == 5:
                index = 1
            self.clip_model.text_style = self.combo_text_style.itemData(index) or "none"
            self._refresh_canvas()
        ClipPropertiesWidget._on_text_style_changed = shifted
        return
    if mode == "no_readback":
        # Cả đường dựng mới lẫn đường dùng lại editor đều đi qua
        # update_values() (properties_panel:1079 và :1103), nên đây là khớp
        # duy nhất cắt được "mở lại không đọc model".
        original = ClipPropertiesWidget.update_values

        def forget_style(self, clip_model):
            original(self, clip_model)
            c = self.combo_text_style
            c.blockSignals(True)
            c.setCurrentIndex(0)          # "quên" không đọc clip.text_style
            c.blockSignals(False)
        ClipPropertiesWidget.update_values = forget_style
        return
    if mode == "flame_dead":
        # Chỉ flame hỏng: preview glow/neon vẫn đổi nên gate pixel còn xanh,
        # nhưng hai ô của ảnh chứng minh thành giống hệt nhau.
        original = karaoke_paint.normalize_style
        karaoke_paint.normalize_style = lambda s: (
            "none" if str(s).strip().lower() == "flame" else original(s))
        return
    if mode == "style_ignored":
        # Đường vẽ dùng chung cho cả preview lẫn export bỏ qua style.
        original = text_paint.paint_animated_text

        def plain(*args, **kwargs):
            kwargs["style"] = "none"
            return original(*args, **kwargs)
        text_paint.paint_animated_text = plain
        return
    raise SystemExit("mode khong biet: %r" % mode)


def main():
    patch(sys.argv[1])
    import karaoke_ui_probe as P
    return P.main()


if __name__ == "__main__":
    sys.exit(main())
