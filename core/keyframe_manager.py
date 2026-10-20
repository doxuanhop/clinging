"""
core/keyframe_manager.py
Quản lý Keyframe (Khung hình chính) cho animation.

Cung cấp:
    - Keyframe: Đại diện một điểm keyframe (time, value, ease)
    - KeyframeTrack: Quản lý danh sách keyframes cho một thuộc tính
    - KeyframeManager: Quản lý tất cả keyframe tracks của một clip

Supports:
    - Thêm/xóa keyframes
    - Nội suy theo đường cong (easing) — cùng một bảng cho preview lẫn export
    - Auto-keyframe (tự thêm keyframe khi thay đổi)

Định dạng một keyframe là tuple 2 hoặc 3 phần tử:
    (time, value)                  -> ease mặc định "linear"
    (time, value, ease_name)       -> ease đặt tên theo EASINGS
Tuple 2 phần tử vẫn đọc được để project cũ mở lên không nổ, nhưng mọi chỗ GHI
đều đi qua ``make_frame`` nên không có code thứ hai tự chế định dạng.
"""

from dataclasses import dataclass
from typing import Optional


DEFAULT_EASE = "linear"


def _in_out(power):
    def curve(t):
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        if t < 0.5:
            return 0.5 * (2.0 * t) ** power
        return 1.0 - 0.5 * (2.0 - 2.0 * t) ** power
    return curve


def _powered(power, direction):
    def curve(t):
        t = min(1.0, max(0.0, t))
        if direction == "in":
            return t ** power
        if direction == "out":
            return 1.0 - (1.0 - t) ** power
        return t
    return curve


def _exponential(direction):
    def curve(t):
        t = min(1.0, max(0.0, t))
        if direction == "in":
            return (2.0 ** (10.0 * (t - 1.0))) if t > 0.0 else 0.0
        return 1.0 - (2.0 ** (-10.0 * t)) if t < 1.0 else 1.0
    return curve


# Bảng cong DUY NHẤT. Mỗi hàm nhận ratio 0..1 và trả ratio mới 0..1: f(0)=0,
# f(1)=1, đơn điệu tăng — nên giá trị nội suy không bao giờ vượt hai đầu
# keyframe (không có overshoot làm opacity > 1).
EASINGS = {
    "linear": lambda t: min(1.0, max(0.0, t)),
    "ease_in": _powered(2, "in"),
    "ease_out": _powered(2, "out"),
    "ease_in_out": _in_out(2),
    "ease_in_cubic": _powered(3, "in"),
    "ease_out_cubic": _powered(3, "out"),
    "ease_in_out_cubic": _in_out(3),
    "ease_in_expo": _exponential("in"),
    "ease_out_expo": _exponential("out"),
}

EASE_LABELS = {
    "linear": "Tuyến tính",
    "ease_in": "Chậm dần (đều)",
    "ease_out": "Nhanh dần (đều)",
    "ease_in_out": "Chậm - nhanh - chậm",
    "ease_in_cubic": "Chậm dần (mạnh)",
    "ease_out_cubic": "Nhanh dần (mạnh)",
    "ease_in_out_cubic": "Chậm - nhanh - chậm (mạnh)",
    "ease_in_expo": "Bốc dần (expo)",
    "ease_out_expo": "Hạ dần (expo)",
}


def normalize_ease(name) -> str:
    """Tên cong khong ton tai -> linear, khong bao gio KeyError giua chung render."""
    return name if name in EASINGS else DEFAULT_EASE


def apply_ease(name, ratio: float) -> float:
    return EASINGS[normalize_ease(name)](ratio)


def make_frame(time: float, value: float, ease: str = DEFAULT_EASE) -> tuple:
    """Khung hinh duy nhat duoc phep ghi vao model."""
    return (float(time), float(value), normalize_ease(ease))


def frame_time(frame) -> float:
    return float(frame[0])


def frame_value(frame) -> float:
    return float(frame[1])


def frame_ease(frame) -> str:
    return normalize_ease(frame[2]) if len(frame) > 2 else DEFAULT_EASE


def interpolate_keyframes(frames, current_time: float,
                          default_value: float = 0.0) -> float:
    """Nguồn nội suy DUY NHẤT cho toàn bộ hệ keyframe — preview lẫn export.

    Args:
        frames: danh sách keyframe (time, value[, ease]) ĐÃ sắp xếp theo thời
            gian; dạng 2 phần tử được hiểu là linear.
        current_time: thời điểm cần lấy giá trị.
        default_value: giá trị khi chưa có keyframe nào.

    Công thức:
        ratio = (current_time - time_a) / (time_b - time_a)
        ratio = EASINGS[ease_cua_keyframe_A](ratio)
        value = value_a + (value_b - value_a) * ratio

    Ease lưu trên keyframe A áp cho đoạn A→B (chiều đi ra). Keyframe cuối
    không có đoạn phía sau nên ease của nó không có tác dụng — đó là lý do
    UI ghi rõ "áp dụng tới keyframe kế tiếp".
    """
    if not frames:
        return default_value

    # Chỉ 1 keyframe, hoặc trước keyframe đầu tiên -> giữ giá trị đầu.
    if len(frames) == 1 or current_time <= frame_time(frames[0]):
        return frame_value(frames[0])

    # Sau keyframe cuối cùng -> giữ giá trị cuối.
    if current_time >= frame_time(frames[-1]):
        return frame_value(frames[-1])

    # Tìm 2 keyframe bao bọc (A, B) rồi nội suy theo cong cua A.
    for i in range(len(frames) - 1):
        time_a, val_a = frame_time(frames[i]), frame_value(frames[i])
        time_b, val_b = frame_time(frames[i + 1]), frame_value(frames[i + 1])
        if time_a <= current_time <= time_b:
            if abs(time_b - time_a) < 0.001:
                return val_a
            ratio = (current_time - time_a) / (time_b - time_a)
            ratio = apply_ease(frame_ease(frames[i]), ratio)
            return val_a + (val_b - val_a) * ratio

    return default_value


@dataclass
class Keyframe:
    """Đại diện một điểm keyframe tại thời điểm nhất định."""
    time: float      # Thời điểm (giây)
    value: float     # Giá trị tại thời điểm đó
    ease: str = DEFAULT_EASE   # Đường cong áp cho đoạn đi tới keyframe kế tiếp

    def as_frame(self) -> tuple:
        return make_frame(self.time, self.value, self.ease)

    def __repr__(self):
        return f"Keyframe(t={self.time:.2f}, v={self.value:.2f}, {self.ease})"


class KeyframeTrack:
    """
    Quản lý danh sách keyframes cho một thuộc tính (x, y, scale, opacity...).
    Hỗ trợ nội suy theo đường cong giữa các keyframe.
    """

    def __init__(self):
        self.keyframes: list[Keyframe] = []
        self._auto_keyframe: bool = False  # Bật/tắt auto-keyframe

    @property
    def auto_keyframe(self) -> bool:
        return self._auto_keyframe
    
    @auto_keyframe.setter
    def auto_keyframe(self, value: bool):
        self._auto_keyframe = value

    def add_keyframe(self, time: float, value: float,
                     ease: str = DEFAULT_EASE) -> Keyframe:
        """
        Thêm keyframe mới tại thời điểm chỉ định.
        Nếu đã có keyframe tại thời điểm này, sẽ ghi đè giá trị nhưng GIỮ ease
        đã chọn — đổi số không được phép âm thầm đặt lại đường cong.
        """
        # Kiểm tra xem đã có keyframe tại thời điểm này chưa
        for i, kf in enumerate(self.keyframes):
            if abs(kf.time - time) < 0.01:
                self.keyframes[i].value = value
                if ease != DEFAULT_EASE or kf.ease == DEFAULT_EASE:
                    self.keyframes[i].ease = normalize_ease(ease)
                return self.keyframes[i]

        # Thêm mới
        kf = Keyframe(time=time, value=value, ease=normalize_ease(ease))
        self.keyframes.append(kf)
        self._sort_keyframes()
        return kf

    def set_ease(self, time: float, ease: str) -> bool:
        """Đặt đường cong cho keyframe tại thời điểm. Trả về True nếu có sửa."""
        kf = self.get_keyframe_at(time)
        if kf is None:
            return False
        kf.ease = normalize_ease(ease)
        return True

    def remove_keyframe(self, time: float) -> bool:
        """Xóa keyframe tại thời điểm chỉ định. Trả về True nếu tìm và xóa được."""
        for i, kf in enumerate(self.keyframes):
            if abs(kf.time - time) < 0.01:
                self.keyframes.pop(i)
                return True
        return False

    def toggle_keyframe(self, time: float, value: float) -> bool:
        """
        Bật/tắt keyframe tại thời điểm.
        Trả về True nếu thêm mới, False nếu xóa.
        """
        # Tìm keyframe hiện có
        for i, kf in enumerate(self.keyframes):
            if abs(kf.time - time) < 0.01:
                # Đã có → xóa
                self.keyframes.pop(i)
                return False
        
        # Chưa có → thêm mới
        self.add_keyframe(time, value)
        return True

    def get_value_at_time(self, current_time: float, default_value: float = 0.0) -> float:
        """Trả về giá trị nội suy tại thời điểm hiện tại.

        Ủy quyền cho ``interpolate_keyframes`` để toàn bộ hệ keyframe dùng
        chung một thuật toán duy nhất — cùng bảng cong cho preview lẫn export.
        """
        return interpolate_keyframes(
            [kf.as_frame() for kf in self.keyframes],
            current_time, default_value
        )

    def has_keyframe_at(self, time: float) -> bool:
        """Kiểm tra có keyframe tại thời điểm không."""
        for kf in self.keyframes:
            if abs(kf.time - time) < 0.01:
                return True
        return False

    def get_keyframe_at(self, time: float) -> Optional[Keyframe]:
        """Lấy keyframe tại thời điểm (nếu có)."""
        for kf in self.keyframes:
            if abs(kf.time - time) < 0.01:
                return kf
        return None

    def get_all_keyframes(self) -> list[Keyframe]:
        """Lấy danh sách tất cả keyframes."""
        return self.keyframes.copy()

    def clear(self):
        """Xóa tất cả keyframes."""
        self.keyframes.clear()

    def _sort_keyframes(self):
        """Sắp xếp keyframes theo thời gian."""
        self.keyframes.sort(key=lambda kf: kf.time)

    def __len__(self):
        return len(self.keyframes)
    
    def __bool__(self):
        return len(self.keyframes) > 0


class KeyframeManager:
    """
    Quản lý tất cả keyframe tracks của một clip.
    Mỗi thuộc tính (x, y, scale_x, scale_y, rotation, opacity) có một KeyframeTrack.
    """

    # Các thuộc tính được hỗ trợ
    SUPPORTED_PROPERTIES = ['x', 'y', 'scale_x', 'scale_y', 'rotation', 'opacity']

    def __init__(self):
        self._tracks: dict[str, KeyframeTrack] = {}
        
        # Khởi tạo tracks cho các thuộc tính mặc định
        for prop in self.SUPPORTED_PROPERTIES:
            self._tracks[prop] = KeyframeTrack()

    def get_track(self, property_name: str) -> KeyframeTrack:
        """Lấy hoặc tạo KeyframeTrack cho thuộc tính."""
        if property_name not in self._tracks:
            self._tracks[property_name] = KeyframeTrack()
        return self._tracks[property_name]

    def add_keyframe(self, property_name: str, time: float, value: float,
                     ease: str = DEFAULT_EASE) -> Keyframe:
        """Thêm keyframe cho thuộc tính."""
        return self.get_track(property_name).add_keyframe(time, value, ease)

    def set_ease(self, property_name: str, time: float, ease: str) -> bool:
        """Đặt đường cong cho một keyframe đang có."""
        return self.get_track(property_name).set_ease(time, ease)

    def get_ease(self, property_name: str, time: float) -> str:
        track = self.get_track(property_name)
        kf = track.get_keyframe_at(time)
        return kf.ease if kf is not None else DEFAULT_EASE

    def remove_keyframe(self, property_name: str, time: float) -> bool:
        """Xóa keyframe khỏi thuộc tính."""
        return self.get_track(property_name).remove_keyframe(time)

    def toggle_keyframe(self, property_name: str, time: float, value: float) -> bool:
        """Bật/tắt keyframe tại thời điểm."""
        return self.get_track(property_name).toggle_keyframe(time, value)

    def get_value_at_time(self, property_name: str, current_time: float,
                          default_value: float = 0.0) -> float:
        """Lấy giá trị nội suy tại thời điểm."""
        return self.get_track(property_name).get_value_at_time(current_time, default_value)

    def get_all_values_at_time(self, current_time: float, defaults: dict = None) -> dict:
        """Lấy tất cả giá trị tại thời điểm."""
        if defaults is None:
            defaults = {}
        
        result = {}
        for prop in self.SUPPORTED_PROPERTIES:
            default = defaults.get(prop, 0.0)
            result[prop] = self.get_value_at_time(prop, current_time, default)
        return result

    def has_any_keyframes(self) -> bool:
        """Kiểm tra có keyframe nào không."""
        return any(track for track in self._tracks.values() if track)

    def clear_all(self):
        """Xóa tất cả keyframes."""
        for track in self._tracks.values():
            track.clear()

    def get_tracks_dict(self) -> dict:
        """Lấy dict chứa tất cả tracks (để lưu vào model)."""
        return self._tracks.copy()

    def load_from_dict(self, data: dict):
        """Tải keyframes từ dict (để khôi phục từ model).

        Chấp nhận cả frame 2 phần tử của project cũ: thiếu ease tức là linear.
        """
        for prop, frames in data.items():
            track = self.get_track(prop)
            track.clear()
            if isinstance(frames, list):
                for item in frames:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        track.add_keyframe(item[0], item[1], frame_ease(item))
