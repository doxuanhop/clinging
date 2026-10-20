"""Con chạy cho phản chứng của DÒNG --selftest karaoke (_karaoke_ok).

Mỗi process cắt ĐÚNG MỘT mắt xích ngay trước khi gọi hàm row, rồi gọi nó.
Parent không sửa file nào — mọi lỗi chỉ sống trong bộ nhớ của con.

Row này không được xanh chỉ vì nó tự vẽ. Nó phải đỏ khi registry thiếu khoá,
khi đường vẽ bỏ qua kiểu, khi sweep bị nối cứng hoặc nhảy qua từ, khi đồng hồ
clip bị bỏ qua, khi có bộ đếm làm đường vẽ không tất định, khi đường xuất
không đọc ``text_style``, và khi file làm mất khoá.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Row chạy trong app THAT (windows platform). Headless ở máy này = 0 font: Qt
# vẽ mọi ký tự ra hình chữ nhật và mọi so sánh nét chữ thành vô nghĩa.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])  # noqa: F841

from core import karaoke_paint, project_storage  # noqa: E402
from core.frame_composer import FrameComposer  # noqa: E402
import diagnostics  # noqa: E402


def apply(mode):
    if mode == "registry":
        karaoke_paint.STYLE_KEYS = tuple(karaoke_paint.STYLE_KEYS[:7])
        return
    if mode == "normalize":
        karaoke_paint.normalize_style = lambda v: str(v or "none").strip().lower()
        return
    if mode == "seam":
        # text_paint gọi karaoke_paint.paint_word — cho nó vẽ "hào quang" thành
        # MỘT nét thường thì tám kiểu còn gì? Đây là cái row phải bắt được.
        def plain(painter, rect, word, style, state, base_color, font_px,
                  t, index, line_rect):
            karaoke_paint._solid(painter, rect, word, base_color)
        karaoke_paint.paint_word = plain
        return
    if mode == "sweep":
        karaoke_paint.lit_count = lambda total, sweep: max(0, int(total))
        return
    if mode == "staircase":
        karaoke_paint.lit_count = lambda total, sweep: total if sweep >= 0.5 else 0
        return
    if mode == "clock":
        # Bo qua t: lua khong con chop, cau vồng khong con xoay — nhưng 8 kieu
        # van khac nhau va van quet theo tu, nen chi gate dong ho moi đỏ.
        real = karaoke_paint.paint_word

        def frozen(painter, rect, word, style, state, base_color, font_px,
                   t, index, line_rect):
            return real(painter, rect, word, style, state, base_color, font_px,
                        0.0, index, line_rect)

        karaoke_paint.paint_word = frozen
        return
    if mode == "counter":
        # Thêm BỘ ĐẾM giữ giữa hai lần vẽ: cùng (p, t) ra hai ảnh khác nhau,
        # tức scrub lùi không còn trở về đúng khung hình cũ.
        real = karaoke_paint.paint_word
        state = [0]

        def drifting(painter, rect, word, style, state_, base_color, font_px,
                     t, index, line_rect):
            state[0] += 1
            return real(painter, rect, word, style, state_, base_color, font_px,
                        t + state[0] * 0.37, index, line_rect)

        karaoke_paint.paint_word = drifting
        return
    if mode == "export":
        real = FrameComposer._draw_text

        def forced(self, painter, clip, *a, **kw):
            clip.text_style = "none"
            return real(self, painter, clip, *a, **kw)

        FrameComposer._draw_text = forced
        return
    if mode == "file":
        real = project_storage.load_project_from_file

        def strip(path):
            data = real(path)
            for track in (data or {}).get("timeline", {}).get("tracks", []):
                for clip in track.get("clips", []):
                    clip.pop("text_style", None)
            return data

        project_storage.load_project_from_file = strip
        return
    if mode == "flame_blob":
        # Cong thuc CU cua quầng lửa (8 ban sao, alpha 90): 8 lan chong nhau
        # cho alpha hieu dung 0.95, lap kin lo chu. Van "doi pixel" nen gate
        # so anh khong thay; chi dem lo chu moi đỏ.
        karaoke_paint._FLAME_HALO = (0.06, 0.09, 0.05, 90)
        return
    if mode == "flame_no_halo":
        # Duong tranh lan: "sua" khoi dac bang cach bo het quầng thi tu mong
        # lai nhu chu thuong, va kieu lua mat luon ngan lua.
        karaoke_paint._FLAME_HALO = (0.0, 0.0, 0.0, 0.0)
        return
    if mode != "clean":
        raise SystemExit("mode khong ton tai: " + mode)
    # "clean": khong cat gi — row phai xanh va in ra so do that.


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    apply(mode)
    try:
        detail = diagnostics._karaoke_ok()
    except Exception as exc:
        print("%s RED %s: %s" % (mode, type(exc).__name__, exc))
        return 1
    print("%s GREEN %s" % (mode, detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
