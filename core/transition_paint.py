"""
core/transition_paint.py
Wipe mask DÙNG CHUNG cho Preview (CanvasClipItem) lẫn Export (FrameComposer).

core/transitions.py chỉ ra con số (cạnh quét ở tỉ lệ nào, feather bao nhiêu);
file này là bước vẽ duy nhất tiêu thụ con số đó. Để riêng một chỗ vì wipe cần
thao tác alpha của ảnh — nếu mỗi bộ dựng hình tự cắt thì "xem một kiểu, xuất
một kiểu" sẽ quay lại ngay ở đúng hiệu ứng khó thấy lỗi nhất.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QBrush


def apply_wipe(image: QImage, edge: float, feather: float = 0.06) -> QImage:
    """Giữ phần ảnh bên TRÁI mép quét ngang, xóa dần phần bên phải.

    edge/feather là tỉ lệ 0..1 theo bề rộng ảnh: edge=0.5 là quét giữa ảnh.
    feather = 0 cho một đường cắt sắc; giá trị dương hòa dần để mép wipe không
    răng cưa khi scale xuống độ phân giải xuất.
    """
    if image is None or image.isNull():
        return QImage()

    w, h = image.width(), image.height()
    if w <= 0 or h <= 0:
        return image

    lo = max(0.0, min(1.0, float(edge) - max(0.0, float(feather)) / 2.0))
    hi = max(0.0, min(1.0, float(edge) + max(0.0, float(feather)) / 2.0))

    if hi <= 0.0:
        # Chưa kịp lộ gì: trả ảnh trong suốt để hai bên vẽ giống nhau (không skip
        # drawItem, tránh preview giữ lại khung hình cũ).
        blank = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        blank.fill(Qt.transparent)
        return blank
    if lo >= 1.0:
        return image

    source = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    mask = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.transparent)

    painter = QPainter(mask)
    opaque = QColor(255, 255, 255, 255)
    clear = QColor(255, 255, 255, 0)
    if hi - lo < 1e-4:
        # Cắt cứng: fill hình chữ nhật để không phải nhồi hai stop trùng nhau.
        painter.fillRect(0, 0, int(round(w * hi)), h, opaque)
    else:
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, opaque if lo > 0.0 else clear)
        grad.setColorAt(lo, opaque)
        grad.setColorAt(hi, clear)
        grad.setColorAt(1.0, clear)
        painter.fillRect(mask.rect(), QBrush(grad))
    # SourceIn: giữ màu của ảnh nhưng lấy alpha của mask vừa vẽ.
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.drawImage(0, 0, source)
    painter.end()
    return mask
