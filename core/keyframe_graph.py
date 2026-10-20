"""
core/keyframe_graph.py
Phần toán của "đồ thị đường cong keyframe": quy chiếu (thời gian, giá trị)
↔ pixel và lấy mẫu đường cong để vẽ.

Tách riêng khỏi widget vì hai lý do:
  * Đường cong hiển thị PHẢI sinh ra từ ``interpolate_keyframes`` — nguồn nội
    suy duy nhất mà preview và export đang dùng. Một biểu đồ tự tính lại bằng
    lerp riêng sẽ vẽ cho người ta thấy một chuyển động không tồn tại.
  * Mỗi phép chiếu ở đây đều đo được bằng probe mà không cần mở cửa sổ: kéo
    node tới pixel nào thì model phải nhận đúng giá trị của pixel đó, nên
    chiều ngược lại phải là nghịch đảo chính xác của chiều đi.

Mỗi property có đơn vị riêng (px, %, độ, hệ số co giãn) nên đồ thị KHÔNG dùng
chung một trục tung: mỗi property một dải, tự co theo khoảng giá trị của chính
nó.
"""

from __future__ import annotations

from core.keyframe_manager import (frame_ease, frame_time, frame_value,
                                   interpolate_keyframes)

# Thứ tự hiển thị trên đồ thị. Ba property hình ảnh đứng trước vì người ta
# chỉnh chúng nhiều nhất; opacity cuối vì dải giá trị của nó cố định.
PROPERTY_ORDER = ("x", "y", "scale_x", "scale_y", "rotation", "opacity")

PROPERTY_LABELS = {
    "x": "Vị trí X",
    "y": "Vị trí Y",
    "scale_x": "Co giãn X",
    "scale_y": "Co giãn Y",
    "rotation": "Góc xoay",
    "opacity": "Độ mờ",
}

# Nhãn đơn vị chỉ để hiện thị; giá trị trong model luôn là số thô.
PROPERTY_UNITS = {
    "x": "px",
    "y": "px",
    "scale_x": "×",
    "scale_y": "×",
    "rotation": "°",
    "opacity": "%",
}

# opacity/scale lưu thô 0..1 / 1.0 nhưng người dùng đọc theo %.
PROPERTY_SCALES = {"opacity": 100.0}

# Một đường thẳng nằm ngang (mọi keyframe cùng giá trị) vẫn phải có chiều cao
# để kéo được node lên xuống, nên mỗi property có dải tối thiểu riêng — tính
# theo ĐƠN VỊ HIỂN THỊ, vì 1.0 của opacity (%) và 1.0 của scale (×) không cùng
# một ý nghĩa.
MIN_VALUE_SPANS = {
    "x": 20.0,
    "y": 20.0,
    "scale_x": 0.1,
    "scale_y": 0.1,
    "rotation": 10.0,
    "opacity": 10.0,
}
VALUE_PADDING = 0.12


def display_value(prop: str, value: float) -> float:
    """Giá trị thô -> số in trên trục tung (opacity 0..1 thành 0..100)."""
    return float(value) * PROPERTY_SCALES.get(prop, 1.0)


def raw_value(prop: str, shown: float) -> float:
    """Ngược lại của display_value: trục tung -> model."""
    return float(shown) / PROPERTY_SCALES.get(prop, 1.0)


def format_value(prop: str, value: float) -> str:
    """Chuoi ngan in canh truc tung, dung mot dang cho moi cot so."""
    shown = display_value(prop, value)
    unit = PROPERTY_UNITS.get(prop, "")
    if abs(shown) >= 100 or unit in ("px", "%", "°"):
        text = "%.0f" % shown
    else:
        text = "%.2f" % shown
    # "-0px" la mot so khong ton tai: duoi 0,4 cua truc luon lon hon 0,4 phia
    # tren no, nen cot so phai in ra "0px" thang.
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]
    return text + unit


def frames_of(clip, prop) -> list:
    """Keyframe của một property, đã sắp theo thời gian."""
    frames = list((getattr(clip, "keyframes", None) or {}).get(prop, []))
    frames.sort(key=frame_time)
    return frames


def animated_properties(clip) -> tuple:
    """Property CO keyframe that, theo thu tu do thi; property la ben ngoai
    PROPERTY_ORDER van duoc giu (project mo tu ban khac co the mang theo)."""
    keyframes = getattr(clip, "keyframes", None) or {}
    known = [prop for prop in PROPERTY_ORDER if keyframes.get(prop)]
    extra = sorted(prop for prop in keyframes
                   if prop not in PROPERTY_ORDER and keyframes[prop])
    return tuple(known + extra)


def default_value(clip, prop) -> float:
    """Gia tri dung khi doan chua co keyframe bao phu — lay dung gia tri
    transform hien tai de duong cong noi vao dung diem khop cua clip."""
    transform = getattr(clip, "transform", None)
    return float(getattr(transform, prop, 0.0) or 0.0)


def value_domain(frames, prop, fallback: float = 0.0):
    """(lo, hi) cua truc tung cho mot property, da cong bien.

    Ba case phai song duoc: khong co moc nao (chi con gia tri mac dinh), mot
    moc, va moi moc bang nhau — ca ba deu ra duoi nam ngang o giua thay vi
    chia cho 0.
    """
    shown = [display_value(prop, frame_value(f)) for f in frames]
    if not shown:
        shown = [display_value(prop, fallback)]
    lo, hi = min(shown), max(shown)
    span = hi - lo
    minimum = MIN_VALUE_SPANS.get(prop, 1.0)
    if span < minimum:
        # Can giua duoi quanh gia tri chung, khong lech ve mot phia.
        pad = minimum / 2.0
        lo, hi = lo - pad, hi + pad
    else:
        pad = span * VALUE_PADDING
        lo, hi = lo - pad, hi + pad
    return lo, hi


def sample_curve(frames, prop, default: float, t0: float, t1: float,
                 samples: int = 120) -> list:
    """((thoi_gian, gia tri tho), ...) mau duong cong THAT cua model.

    Goi tung diem qua interpolate_keyframes — khong noi suy lai o day. Neuan
    mot ban ve nao dung cach thay ham nay bang 'tinh nhanh' thi do that cua
    preview/export va duong tren man hinh se lech nhau.
    """
    count = max(2, int(samples))
    t0, t1 = min(float(t0), float(t1)), max(float(t0), float(t1))
    if t1 <= t0:
        return [(t0, interpolate_keyframes(frames, t0, default))]
    step = (t1 - t0) / (count - 1)
    out = []
    for index in range(count):
        # Diem CUOI phai la t1: neu con ghi nham thanh t0 thi mau cuoi trung
        # diem dau, va duong noi gay se keo mot net nguoc ve trai qua het lane.
        time = t1 if index == count - 1 else t0 + index * step
        out.append((time, interpolate_keyframes(frames, time, default)))
    return out


def interpolate_at(frames, prop, default: float, time: float) -> float:
    """Gia tri duong cong THAT tai mot thoi diem — moc moi do thi chen vao
    phai roi dung cho duong cong dang di qua, khong phai gia tuy y.

    Van la interpolate_keyframes: do thi khong co loi noi suy rieng.
    """
    return interpolate_keyframes(frames, time, default)


# ── Phép chiếu pixel ↔ dữ liệu ────────────────────────────────
def time_to_x(time: float, t0: float, t1: float, x0: float, x1: float) -> float:
    span = float(t1) - float(t0)
    if span <= 0:
        return float(x0)
    ratio = (float(time) - float(t0)) / span
    return float(x0) + ratio * (float(x1) - float(x0))


def x_to_time(x: float, t0: float, t1: float, x0: float, x1: float) -> float:
    width = float(x1) - float(x0)
    if width <= 0:
        return float(t0)
    span = float(t1) - float(t0)
    ratio = (float(x) - float(x0)) / width
    return float(t0) + ratio * span


def value_to_y(value: float, lo: float, hi: float, y0: float, y1: float) -> float:
    """Truc tung: gia tri lon o TREN (y0 la dinh lane, y1 la day lane)."""
    span = float(hi) - float(lo)
    if span <= 0:
        return (float(y0) + float(y1)) / 2.0
    ratio = (float(value) - float(lo)) / span
    return float(y1) - ratio * (float(y1) - float(y0))


def y_to_value(y: float, lo: float, hi: float, y0: float, y1: float) -> float:
    height = float(y1) - float(y0)
    if height <= 0:
        return float(lo)
    span = float(hi) - float(lo)
    ratio = (float(y1) - float(y)) / height
    return float(lo) + ratio * span


def clamp(value: float, lo: float, hi: float) -> float:
    return min(max(float(value), float(lo)), float(hi))


def frame_at(frames, time: float, tolerance: float = 0.05):
    """Keyframe gan moc thoi gian nhat trong nguong, hoac None.

    Model so sanh moc theo nguong 0.01–0.05 s, nen do vi phai dung cung mot
    nguong; dung `==` thi keo node toi gan moc cu se tao moc moi chong chat.
    """
    best, best_gap = None, None
    for frame in frames:
        gap = abs(frame_time(frame) - float(time))
        if gap <= tolerance and (best_gap is None or gap < best_gap):
            best, best_gap = frame, gap
    return best


def hit_test(frames, x: float, y: float, prop: str, t0: float, t1: float,
             lo: float, hi: float, x0: float, x1: float, y0: float, y1: float,
             radius: float = 9.0):
    """Node nao nam duoi diem (x, y)? Tra (chi_so, frame) hoac None.

    Do bang pixel (khong phai nguong thoi gian) vi hai moc cach nhau 0.02 s la
    chuyen binh thuong khi keo; nguoi dung phai bam duoc vao cai ma ho nhin
    thay.
    """
    found, best_gap = None, None
    for index, frame in enumerate(frames):
        fx = time_to_x(frame_time(frame), t0, t1, x0, x1)
        fy = value_to_y(display_value(prop, frame_value(frame)), lo, hi, y0, y1)
        gap = max(abs(fx - float(x)), abs(fy - float(y)))
        if gap <= float(radius) and (best_gap is None or gap < best_gap):
            found, best_gap = (index, frame), gap
    return found


def ease_of(frame) -> str:
    return frame_ease(frame)


def time_of(frame) -> float:
    return frame_time(frame)


def value_of(frame) -> float:
    return frame_value(frame)
