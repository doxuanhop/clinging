"""bar_measure.py — một thước duy nhất cho chiều dày thanh tiến trình.

Cả gate cắt video (scratch/media_split_probe.py) và gate trích xuất thumbnail
(scratch/thumbnail_probe.py) đều phải chứng minh "thanh đã nhỏ lại". Nếu mỗi
nơi tự viết bộ đo thì một lần sửa sai ở chỗ này sẽ khiến chỗ kia báo số đẹp
mà không đo gì. Nên bộ đo nằm ở đây, hai gate dùng chung.

Vì sao đo trên grab của RIÊNG thanh chứ không phải grab cả hộp thoại:
QProgressBar màu #40E0D0 và nut primary của hai hộp thoại cũng màu #40E0D0,
cao hơn thanh rất nhiều. Đo cả cửa sổ (nghiêng trục tìm run dài nhất rồi đếm
số hàng liên tiếp) sẽ lấy chiều cao của cái nut — con số 33 px từng lọt qua
ngưỡng w//8 của phép đo cũ, tức phép đo đó không phân biệt được gì.

Ngưỡng chiều dài theo tỷ lệ chính cái thanh (>= 1/4 bề rộng) nên một thanh
mỏng dính vẫn hợp lệ, còn một vệt teal lấm tấm thì không.
"""

import os

from PIL import Image


def teal_band_height(bar, path):
    """Số hàng pixel LIÊN TIẾP mang màu ngắn teal trong grab của `bar`.

    Ảnh lưu ở `path` là pixel thiết bị của chính widget, nên con số này so
    được thẳng với chiều cao khai trong QSS/setFixedHeight của thanh.
    """
    bar.grab().save(path, "PNG")
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    best = run = 0
    for y in range(h):
        longest = cur = 0
        for x in range(w):
            r, g, b = px[x, y]
            if r < 130 and g > 170 and b > 160:
                cur += 1
                if cur > longest:
                    longest = cur
            else:
                cur = 0
        run = run + 1 if longest >= max(8, w // 4) else 0
        best = max(best, run)
    return best
