"""Đo "khối đặc" của từ karaoke và chọn hằng số quầng lửa BẰNG SỐ ĐO.

Cơ chế được kiểm chứng ở đây: quầng flame là 8 bản sao lệch của nét chữ chồng
nhau, nên alpha hiệu dụng giữa thân chữ là 1-(1-a/255)^8. Với alpha 90 con số đó
0.95 — mọi lỗ chữ (a, o, u) lập tức bị lấp, từ ĐANG HÁT thành một khối cam.

Probe đi qua ĐÚNG đường production (core.text_paint.paint_animated_text ->
core.karaoke_paint.paint_word) và chỉ đổi bộ hằng số ``_FLAME_HALO`` trên module,
mặc định là bản đang ship — không có bản sao thứ hai của thuật toán vẽ.

Ba con số báo cáo cho mỗi (ứng viên, khổ chữ):
  * fill  = pixel mực / diện tích hộp khít của mực. Chữ thường ~0.47-0.65,
            khối đặc ~0.75.
  * holes = số vùng nền bị bao kín bên trong mực (đếm bằng connected components).
            Từ còn đọc được thì còn lỗ; khối đặc có 0 lỗ.
  * glow  = số pixel mực nhiều hơn chữ thường cùng từ — dưới 0 nghĩa là quầng
            đã bị xoá sạch chứ không phải đã làm mỏng.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

import core.karaoke_paint as kp
from core.text_paint import paint_animated_text

WORD = "chao"          # hai chữ a/o có lỗ: thước đo lỗ chữ
SWEEP = 0.2            # 1 từ + sweep này -> từ ở trạng thái ACTIVE
# pulse = 0.5+0.5*sin(t*2.4): ba thời điểm dưới đây phủ cả chu kỳ nhấp nháy
# (đáy, giữa, đỉnh). Bán kính quầng lớn nhất ở ĐỈNH, nhưng số lỗ chữ KHÔNG đơn
# điệu theo bán kính — mode 'counter' của phản chứng đã đo ra 1 lỗ ở 28px tại
# một pha trung gian — nên phải lấy giá trị tệ nhất trên cả chu kỳ.
T_CYCLE = (0.0, (math.pi * 1.5) / 2.4, (math.pi / 2) / 2.4)
SIZES = (40, 28, 20, 16, 12)

# Ứng viên: (bán kính lúc đã hát, gốc lúc đang hát, biên độ nhấp nháy, alpha)
CANDIDATES = [
    (0.06, 0.09, 0.05, 90),   # bản đang ship — khối đặc
    (0.04, 0.06, 0.03, 70),
    (0.03, 0.045, 0.02, 60),
    (0.025, 0.035, 0.015, 50),
    (0.02, 0.03, 0.012, 40),
]

W, H = 420, 160


def render(style, px_size, t=None):
    t = T_CYCLE[-1] if t is None else t
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    font = QFont("Arial")
    font.setPixelSize(px_size)
    font.setBold(True)
    paint_animated_text(p, WORD, font, "#FFFFFF", W, H, W / 2.0, H / 2.0,
                        effect="none", p=SWEEP, intensity=1.0, style=style, t=t)
    p.end()
    row = img.bytesPerLine() // 4
    a = np.frombuffer(img.constBits(), np.uint8,
                      count=row * 4 * H).reshape(H, row, 4)[:, :W, :3]
    return a[:, :, ::-1].copy()


def metrics(arr):
    ink = arr.max(axis=2) > 40
    if not ink.any():
        return 0, 0.0, 0
    ys, xs = np.nonzero(ink)
    box = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    import cv2
    bg = (~box).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bg, 8)
    h, w = box.shape
    holes = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (x == 0 or y == 0 or x + bw >= w or y + bh >= h) and area >= 2:
            holes += 1
    return int(ink.sum()), round(100.0 * box.sum() / box.size, 1), holes


def sheet(path, cells):
    """Dải ảnh chứng minh: mỗi ô một (nhãn, ảnh), ghi đúng số đo lên đầu ô."""
    import cv2
    tiles = []
    for label, arr, note in cells:
        bgr = cv2.cvtColor(np.clip(arr, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        bgr = cv2.resize(bgr, (int(W * 0.55), int(H * 0.55)),
                         interpolation=cv2.INTER_NEAREST)
        bgr = np.vstack([np.full((18, bgr.shape[1], 3), 12, np.uint8), bgr])
        cv2.putText(bgr, label, (4, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                    (0, 255, 128), 1, cv2.LINE_AA)
        cv2.putText(bgr, note, (bgr.shape[1] - 118, 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.30, (230, 230, 0), 1, cv2.LINE_AA)
        tiles.append(bgr)
    gap = np.full((tiles[0].shape[0], 6, 3), 30, np.uint8)
    line = tiles[0]
    for t in tiles[1:]:
        line = np.hstack([line, gap, t])
    cv2.imwrite(path, line)


def main():
    app = QApplication.instance() or QApplication([])  # noqa: F841
    mode = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    default = kp._FLAME_HALO

    if mode == "sweep":
        print("hang so dang ship: %s" % (default,))
        print("so do = TE NHAT tren ca chu ky nhap nhay (muc/fill/lo, +spill)")
        print("%-28s %s" % ("ung vien (lit,hot,swing,alpha)",
                            "  ".join("%-18s" % ("%dpx muc/fill/lo" % s)
                                      for s in SIZES)))
        for cand in CANDIDATES:
            kp._FLAME_HALO = cand
            cells = []
            for px_size in SIZES:
                rows = []
                for t in T_CYCLE:
                    plain = metrics(render("none", px_size))
                    hot = metrics(render("flame", px_size, t))
                    rows.append((hot[0], hot[1], hot[2], hot[0] - plain[0]))
                worst = (max(r[0] for r in rows), max(r[1] for r in rows),
                         min(r[2] for r in rows), min(r[3] for r in rows))
                cells.append("%d/%s/%d(+%d)" % worst)
            print("%-28s %s" % (str(cand),
                                "  ".join("%-18s" % c for c in cells)))
        kp._FLAME_HALO = default
        return 0

    # evidence: chu thuong | quang CU (khoi dac) | quang MOI, o ba khổ chữ
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "karaoke_flame_density.png")
    old = CANDIDATES[0]
    cells = []
    for px_size in (40, 20, 12):
        for label, halo in (("chu thuong %d" % px_size, None),
                            ("cu %d" % px_size, old),
                            ("moi %d" % px_size, default)):
            kp._FLAME_HALO = halo or default
            arr = render("none" if halo is None else "flame", px_size)
            m = metrics(arr)
            cells.append((label, arr, "muc %d fill %s lo %d" % m))
    kp._FLAME_HALO = default
    sheet(out, cells)
    print("anh: %s (%d o)" % (out, len(cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

