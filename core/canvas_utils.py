"""
core/canvas_utils.py
Utility functions cho Player Canvas — tính toán vị trí và tỉ lệ media.
"""

import math
import os
from PySide6.QtCore import QRectF


# Kích thước Canvas mặc định theo tỉ lệ khung hình
ASPECT_RATIOS = {
    "16:9": (1920, 1080),
    "19:6": (1900, 600),
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
    "4:3":  (1440, 1080),
}

DEFAULT_CANVAS_W = 1920
DEFAULT_CANVAS_H = 1080


def calculate_fit_and_center(media_w: float, media_h: float,
                             canvas_w: float = DEFAULT_CANVAS_W,
                             canvas_h: float = DEFAULT_CANVAS_H) -> dict:
    """
    Tính toán tọa độ và tỉ lệ để media vừa vặn và nằm giữa Canvas.

    Công thức:
        scale = min(canvas_w / media_w, canvas_h / media_h)
        x = (canvas_w - media_w * scale) / 2
        y = (canvas_h - media_h * scale) / 2

    Returns:
        dict với keys: x, y, scale, new_w, new_h
    """
    if media_w <= 0 or media_h <= 0:
        return {
            'x': 0.0, 'y': 0.0,
            'scale': 1.0,
            'new_w': canvas_w, 'new_h': canvas_h
        }

    scale_x = canvas_w / media_w
    scale_y = canvas_h / media_h
    scale = min(scale_x, scale_y)

    new_w = media_w * scale
    new_h = media_h * scale

    # PreviewCanvas dùng hệ tọa độ tâm: sceneRect = (-w/2, -h/2, w, h).
    # Vì rect của item cũng được vẽ quanh tâm, vị trí căn giữa luôn là (0, 0).
    center_x = 0.0
    center_y = 0.0

    return {
        'x': center_x,
        'y': center_y,
        'scale': scale,
        'new_w': new_w,
        'new_h': new_h
    }


ALIGN_EDGES = ("start", "center", "end")


def rotated_box_size(box_w: float, box_h: float, rotation: float) -> tuple:
    """Hộp BAO của một rect xoay quanh tâm — (rộng, cao) luôn dương.

    Canh mép phải dùng hộp bao, không dùng rect chưa xoay: clip xoay 90° thì bề
    rộng TA nhìn thấy chính là chiều cao của rect, lấy số chưa xoay thì mép
    chạm lệch một khoảng bằng hiệu hai trục (1920x1080 là 840 px).
    """
    a = math.radians(rotation)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return box_w * c + box_h * s, box_w * s + box_h * c


def align_center(canvas_size: float, box_size: float, edge: str) -> float:
    """Tọa độ TAM (hệ tâm canvas) đặt hộp `box_size` chạm `edge` của canvas.

    Canvas và FrameComposer cùng dùng hệ tọa độ tâm (sceneRect = -w/2..w/2) và
    `transform.x` là ĐỘ LỆCH khỏi tâm, nên "canh trái" là -canvas/2 + box/2 chứ
    không phải 0. Mọi chuỗi lạ trả 0.0 để nút không ghi một số vô nghĩa.
    """
    half = canvas_size / 2.0
    if edge == "start":
        return -half + box_size / 2.0
    if edge == "end":
        return half - box_size / 2.0
    return 0.0


def base_display_size(clip, canvas_w: float, canvas_h: float) -> tuple:
    """Kích thước nền (đã fit/fill) TRƯỚC khi nhân scale — một nguồn cho ba bên.

    FrameComposer lẫn bảng thuộc tính cùng đọc ở đây: nút canh mép cần đúng hộp
    mà máy vẽ đang DISPLAY, tự tính lại bằng công thức riêng là canh theo một hệ
    quy chiếu khác hệ đang vẽ ra file.
    """
    tw = getattr(clip.transform, "_media_w", 0.0)
    th = getattr(clip.transform, "_media_h", 0.0)
    if tw > 0 and th > 0:
        return float(tw), float(th)

    if clip.media_type == "sticker":
        return 220.0, 220.0

    media_w = getattr(clip.transform, "original_w", 0) or 0
    media_h = getattr(clip.transform, "original_h", 0) or 0
    if media_w <= 0 or media_h <= 0:
        media_w, media_h = get_media_dimensions(clip.source_path, clip.media_type)
    if media_w <= 0 or media_h <= 0:
        media_w, media_h = 400.0, 300.0

    layout = calculate_fit_and_center(media_w, media_h, canvas_w, canvas_h)
    return layout["new_w"], layout["new_h"]


def get_media_dimensions(file_path: str, media_type: str) -> tuple[float, float]:
    """
    Lấy kích thước (width, height) của file media.
    Trả về (0, 0) nếu không đọc được.
    """
    from core.media_locator import locate

    # Duong dan da duoc `restore_model_from_clinq` dinh vi luc mo du an; o day
    # chi con mot kha nang lac cho la file bi doi ten sau khi mo. Khong di bo
    # thu muc hien hanh: `os.walk(".")` cung mot lenh go cua nguoi dung co the
    # tro toi `C:\Windows\System32` khi app mo tu Explorer.
    actual_path = locate(file_path) or file_path

    if not os.path.exists(actual_path):
        return 0.0, 0.0

    try:
        if media_type == "image":
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(actual_path)
            if not pixmap.isNull():
                return float(pixmap.width()), float(pixmap.height())

        elif media_type == "video":
            import cv2
            # Suppress OpenCV error messages for unsupported codecs
            old_stderr = os.dup(2)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 2)
            try:
                cap = cv2.VideoCapture(actual_path)
            finally:
                os.dup2(old_stderr, 2)
                os.close(old_stderr)
                os.close(devnull)
            if cap.isOpened():
                w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                cap.release()
                return float(w), float(h)
            cap.release()

    except Exception as e:
        print(f"Lỗi đọc kích thước media: {e}")

    return 0.0, 0.0


def apply_fit_to_canvas(clip, canvas_w: float = DEFAULT_CANVAS_W,
                        canvas_h: float = DEFAULT_CANVAS_H):
    """
    Áp dụng Fit-to-Canvas transform cho ClipModel.
    Tự động đọc kích thước file và tính toán vị trí/căn giữa.
    """
    if clip.media_type == "audio":
        return

    # Dung kich thuoc GOC da luu (khong doc lai file)
    media_w = getattr(clip.transform, 'original_w', 0) or 0
    media_h = getattr(clip.transform, 'original_h', 0) or 0

    # Neu chua co, doc tu file
    if media_w <= 0 or media_h <= 0:
        media_w, media_h = get_media_dimensions(clip.source_path, clip.media_type)
        if media_w > 0 and media_h > 0:
            clip.transform.original_w = media_w
            clip.transform.original_h = media_h

    if media_w <= 0 or media_h <= 0:
        media_w, media_h = canvas_w, canvas_h

    layout = calculate_fit_and_center(media_w, media_h, canvas_w, canvas_h)

    clip.transform.x = layout['x']
    clip.transform.y = layout['y']
    clip.transform.scale_x = 1.0
    clip.transform.scale_y = 1.0
    clip.transform._media_w = layout['new_w']
    clip.transform._media_h = layout['new_h']


def calculate_fill_and_crop(media_w: float, media_h: float,
                             canvas_w: float = DEFAULT_CANVAS_W,
                             canvas_h: float = DEFAULT_CANVAS_H) -> dict:
    """
    Tính toán tọa độ và tỉ lệ để media Lấp đầy Canvas (Fill) — không để khoảng trống.
    Media sẽ bị crop (cắt bớt rìa) để bao phủ toàn bộ canvas.

    Công thức:
        scale = max(canvas_w / media_w, canvas_h / media_h)

    Returns:
        dict với keys: x, y, scale, new_w, new_h
    """
    if media_w <= 0 or media_h <= 0:
        return {
            'x': 0.0, 'y': 0.0,
            'scale': 1.0,
            'new_w': canvas_w, 'new_h': canvas_h
        }

    scale_x = canvas_w / media_w
    scale_y = canvas_h / media_h
    scale = max(scale_x, scale_y)

    new_w = media_w * scale
    new_h = media_h * scale

    # Căn giữa phần media bị crop
    center_x = 0.0
    center_y = 0.0

    return {
        'x': center_x,
        'y': center_y,
        'scale': scale,
        'new_w': new_w,
        'new_h': new_h
    }


def apply_fill_to_canvas(clip, canvas_w: float = DEFAULT_CANVAS_W,
                          canvas_h: float = DEFAULT_CANVAS_H):
    """
    Áp dụng Fill-to-Canvas transform cho ClipModel.
    """
    if clip.media_type == "audio":
        return

    # Dung kich thuoc GOC da luu
    media_w = getattr(clip.transform, 'original_w', 0) or 0
    media_h = getattr(clip.transform, 'original_h', 0) or 0

    if media_w <= 0 or media_h <= 0:
        media_w, media_h = get_media_dimensions(clip.source_path, clip.media_type)
        if media_w > 0 and media_h > 0:
            clip.transform.original_w = media_w
            clip.transform.original_h = media_h

    if media_w <= 0 or media_h <= 0:
        media_w, media_h = canvas_w, canvas_h

    layout = calculate_fill_and_crop(media_w, media_h, canvas_w, canvas_h)

    clip.transform.x = layout['x']
    clip.transform.y = layout['y']
    clip.transform.scale_x = 1.0
    clip.transform.scale_y = 1.0
    clip.transform._media_w = layout['new_w']
    clip.transform._media_h = layout['new_h']


def apply_auto_fit(clip, canvas_w: float = DEFAULT_CANVAS_W,
                    canvas_h: float = DEFAULT_CANVAS_H):
    """
    Áp dụng Fit hoặc Fill dựa trên fit_mode của clip.
    Nếu tỷ lệ video khác project > 30% → Fill tự động, ngược lại → Fit.
    """
    fit_mode = getattr(clip.transform, 'fit_mode', 'fit')

    if fit_mode == "fill":
        apply_fill_to_canvas(clip, canvas_w, canvas_h)
    else:
        apply_fit_to_canvas(clip, canvas_w, canvas_h)


def detect_optimal_fit_mode(media_w: float, media_h: float,
                             canvas_w: float = DEFAULT_CANVAS_W,
                             canvas_h: float = DEFAULT_CANVAS_H) -> str:
    """
    Phát hiện chế độ hiển thị tối ưu dựa trên tỷ lệ media và canvas.
    Nếu tỷ lệ khác biệt quá lớn (>30%) → nên dùng Fill để chuyên nghiệp hơn.
    """
    if media_w <= 0 or media_h <= 0:
        return "fit"

    media_ratio = media_w / media_h
    canvas_ratio = canvas_w / canvas_h
    diff = abs(media_ratio - canvas_ratio) / canvas_ratio

    return "fill" if diff > 0.3 else "fit"


def fit_to_project_ratio(clip, project_ratio: str = "16:9"):
    """
    Tính toán lại transform cho clip dựa trên tỉ lệ khung hình mới của project.
    Tôn trọng fit_mode (fit/fill) đã lưu trên clip.
    
    Args:
        clip: ClipModel cần cập nhật
        project_ratio: Tỉ lệ mới ("16:9", "9:16", "1:1", "4:3")
    """
    if clip.media_type == "audio":
        return
    
    if project_ratio not in ASPECT_RATIOS:
        project_ratio = "16:9"
    
    canvas_w, canvas_h = ASPECT_RATIOS[project_ratio]
    
    # Dùng kích thước GỐC đã lưu (không cần đọc lại file)
    media_w = getattr(clip.transform, 'original_w', 0) or clip.transform._media_w
    media_h = getattr(clip.transform, 'original_h', 0) or clip.transform._media_h
    
    # Nếu chưa có kích thước gốc, thử đọc từ file
    if media_w <= 0 or media_h <= 0:
        media_w, media_h = get_media_dimensions(clip.source_path, clip.media_type)
        if media_w > 0 and media_h > 0:
            clip.transform.original_w = media_w
            clip.transform.original_h = media_h
    
    if media_w <= 0 or media_h <= 0:
        return
    
    # Phát hiện fit_mode nếu chưa có
    if not hasattr(clip.transform, 'fit_mode') or not clip.transform.fit_mode:
        clip.transform.fit_mode = detect_optimal_fit_mode(media_w, media_h, canvas_w, canvas_h)
    
    # Áp dụng theo fit_mode hiện tại
    apply_auto_fit(clip, canvas_w, canvas_h)
