"""
core/timeline_model.py
Data model trung tâm cho Timeline Engine.

Mọi thay đổi trên timeline đều đi qua model này và phát Signal
để UI (QGraphicsScene) tự cập nhật — Event Observer Pattern.

Kiến trúc:
    TimelineModel
      └── tracks: list[TrackModel]
            └── clips: list[ClipModel]
"""

import uuid
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core import recap_overlay, transitions


# Shared vertical geometry for every Timeline surface. Header, body, drop
# routing and clip dragging must use the same values to stay row-aligned.
TIMELINE_RULER_HEIGHT = 30.0
TIMELINE_TRACK_TOP_PADDING = 24.0
TIMELINE_TRACK_GAP = 2.0
TIMELINE_SCENE_BOTTOM_PADDING = 50.0
TIMELINE_EMPTY_TRACKS_HEIGHT = 200.0


def timeline_tracks_height(tracks, top_padding: float) -> float:
    """Chiều cao vùng lane, tính từ đỉnh vùng track (dưới ruler).

    Header scene và Timeline scene phải dùng đúng công thức này. Trước đây body
    có thêm sàn max(200) còn header thì không, nên hai scene lệch nhau 24px ở
    dự án 1 track; hai thanh cuộn cùng có range khác nhau và header hết bám
    theo body khi body cuộn xuống.
    """
    if not tracks:
        return TIMELINE_EMPTY_TRACKS_HEIGHT
    return top_padding + sum(
        track.height + TIMELINE_TRACK_GAP for track in tracks)


def timeline_scene_height(tracks, top_padding: float) -> float:
    """Chiều cao scene đầy đủ (ruler + lanes + đệm đáy) cho mọi surface."""
    bottom_padding = max(TIMELINE_SCENE_BOTTOM_PADDING, top_padding)
    return (TIMELINE_RULER_HEIGHT
            + timeline_tracks_height(tracks, top_padding) + bottom_padding)



# ── Enum & Data Classes ─────────────────────────────────────────

class TrackType(Enum):
    """Loại track — quyết định icon, màu sắc, và hành vi mặc định."""
    VIDEO = auto()
    AUDIO = auto()
    IMAGE = auto()
    TEXT = auto()
    EFFECT = auto()
    OVERLAY = auto()


TRACK_MEDIA_TYPES = {
    TrackType.VIDEO: {"video"},
    TrackType.AUDIO: {"audio"},
    TrackType.IMAGE: {"image"},
    TrackType.TEXT: {"text"},
    TrackType.EFFECT: {"effect"},
    TrackType.OVERLAY: {"sticker"},
}


def track_accepts_media(track_type: TrackType, media_type: str) -> bool:
    """Typed Track validation — không cho media lọt vào sai loại track."""
    return media_type in TRACK_MEDIA_TYPES.get(track_type, set())


def track_type_for_media(media_type: str) -> TrackType:
    for track_type, media_types in TRACK_MEDIA_TYPES.items():
        if media_type in media_types:
            return track_type
    return TrackType.VIDEO


# Màu mặc định cho từng loại track
TRACK_COLORS = {
    TrackType.VIDEO:   "#4FC3F7",   # xanh dương nhạt
    TrackType.AUDIO:   "#FFB74D",   # cam
    TrackType.IMAGE:   "#81C784",   # xanh lá
    TrackType.TEXT:    "#CE93D8",   # tím nhạt
    TrackType.EFFECT:  "#81C784",   # xanh lá
    TrackType.OVERLAY: "#F06292",   # hồng
}


@dataclass
class TransformData:
    """Dữ liệu biến đổi hình học cho clip trên canvas preview."""
    x: float = 0.0
    y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0     # degrees
    opacity: float = 1.0
    fit_mode: str = "fit"     # "fit" hoặc "fill"
    # Kích thước GỐC của media (không thay đổi khi đổi ratio)
    original_w: float = 0.0
    original_h: float = 0.0
    # Kích thước media sau fit-to-canvas (dùng nội bộ)
    _media_w: float = 0.0
    _media_h: float = 0.0


@dataclass
class EffectData:
    """Một hiệu ứng đã áp dụng lên clip."""
    name: str = ""
    category: str = ""       # Sắc thái, Chuyển tiếp, Hoạt ảnh, Bộ lọc
    intensity: float = 1.0   # 0.0 – 1.0
    params: dict = field(default_factory=dict)  # tham số riêng của hiệu ứng

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "intensity": round(self.intensity, 3),
            "params": self.params,
        }

    @staticmethod
    def from_dict(d: dict) -> "EffectData":
        return EffectData(
            name=d.get("name", ""),
            category=d.get("category", ""),
            intensity=d.get("intensity", 1.0),
            params=d.get("params", {}),
        )


# ── EFFECT_PRESETS: ánh xạ tên hiệu ứng → tham số mặc định ──
EFFECT_PRESETS = {
    # Sắc thái
    "Warm Tone":    {"brightness": 0.05, "contrast": 1.05, "saturation": 1.2, "color_temp": 0.15},
    "Cool Blue":    {"brightness": 0.0, "contrast": 1.0, "saturation": 0.9, "color_temp": -0.2},
    "Vintage":      {"brightness": 0.02, "contrast": 0.9, "saturation": 0.7, "color_temp": 0.1},
    "B&W":          {"brightness": 0.0, "contrast": 1.1, "saturation": 0.0, "color_temp": 0.0},
    "Cinematic":    {"brightness": -0.03, "contrast": 1.15, "saturation": 0.85, "color_temp": -0.05},
    "Neon Glow":    {"brightness": 0.1, "contrast": 1.2, "saturation": 1.5, "color_temp": 0.0},
    # halftone/posterize/outline là ba khoá vẽ riêng, xem core/clip_effects.py.
    # Bộ số chọn bằng mắt trên 6 phương án x 2 loại khung hình thật (ảnh sáng
    # tương phản cao và cảnh màu rực rỡ — gate scratch/popart_probe.py): 3 bậc màu
    # làm bẹp chủ thể thành mảng đen, 5 bậc thì mất chất pop art; 1.3/1.8 cho
    # mảng màu đặc mà vẫn đọc được mặt người.
    "Pop Art":      {"contrast": 1.3, "saturation": 1.8, "halftone": 6.0,
                     "posterize": 4.0, "outline": 0.6},
    # Chuyển tiếp
    "Fade In":          {"fade_in": 1.0},
    "Fade Out":         {"fade_out": 1.0},
    "Cross Dissolve":   {"cross_dissolve": 1.0},
    "Zoom In":          {"zoom_in": 1.0},
    "Slide Left":       {"slide_left": 1.0},
    "Wipe Right":       {"wipe_right": 1.0},
    # Hoạt ảnh
    "Bounce":   {"bounce": 1.0},
    "Shake":    {"shake": 1.0},
    "Pulse":    {"pulse": 1.0},
    "Spin":     {"spin": 1.0},
    "Float":    {"float": 1.0},
    "Glitch":   {"glitch": 1.0},
    "Ken Burns Out": {"zoom_out": 1.0},
    "Slide Right":   {"slide_right": 1.0},
    "Slide Up":      {"slide_up": 1.0},
    "Slide Down":    {"slide_down": 1.0},
    # Bộ lọc
    "Blur":         {"blur": 4.0},
    "Sharpen":      {"sharpen": 1.0},
    "Vignette":     {"vignette": 0.6},
    "Grain":        {"grain": 0.3},
    "Chromatic":    {"chromatic": 1.0},
    "Lens Flare":   {"lens_flare": 1.0},
    # Aura: khong phai loc mau. Khoá "aura" do core/aura_paint.py vẽ theo
    # đồng hồ clip (hạt, sét, vòng sáng, dải sóng) nên nó nằm ngoài
    # PIXEL_KEYS và có gate đo độ sống riêng.
    "Hỏa Diệm":     {"aura": "fire"},
    "Lôi Điện":     {"aura": "electric"},
    "Thánh Quang":  {"aura": "divine"},
    "Hắc Ám":       {"aura": "shadow"},
    "Cực Quang":    {"aura": "aurora"},
    "Mã Ma Trận":   {"aura": "matrix"},
    "Anh Đào Bay":  {"aura": "sakura"},
    "Neon Hồng Tím": {"aura": "cyberpunk"},
}


# Giới hạn thanh trượt tốc độ/âm lượng ở panel thuộc tính.
# atempo của ffmpeg chỉ nhận 0.5..2.0 cho một bộ lọc đơn, nên ngoài khoảng này
# core/audio_mix.py phải nối tiếp nhiều bộ atempo.
MIN_SPEED = 0.25
MAX_SPEED = 4.0
MIN_VOLUME = 0.0
MAX_VOLUME = 2.0


@dataclass
class ClipModel:
    """
    Đại diện một clip trên track.

    Attributes:
        clip_id:     UUID duy nhất
        start_time:  Vị trí bắt đầu trên timeline (giây)
        duration:    Thời lượng hiển thị (giây)
        source_path: Đường dẫn file gốc
        media_type:  Loại media (video, audio, image, ...)
        in_point:    Điểm trim bắt đầu trong file gốc (giây)
        out_point:   Điểm trim kết thúc trong file gốc (giây)
        name:        Tên hiển thị (mặc định = tên file)
        transform:   Dữ liệu biến đổi hình học
        track_id:    UUID của track chứa clip này
        transition:  Chuyển tiếp tại mép TRÁI của clip, {"name", "duration"}
                     — rỗng nghĩa là không có. Công thức ở core/transitions.py.
        volume:      Hệ số âm lượng của riêng clip (0..2, 1.0 = 100%)
        speed:       Tốc độ phát nguồn (0.25..4). duration trên timeline KHÔNG
                     đổi, nguồn bị ăn nhiều hơn khi tốc độ tăng.
        fade_in:     Giây ramp to dần ở đầu clip (cộng thêm với chuyển tiếp)
        fade_out:    Giây ramp nhỏ dần ở cuối clip
        audio_muted: Tắt tiếng riêng clip này — nguồn vẫn chạy đúng nhịp, chỉ
                     có gain bị ép về 0 (khác ``track.is_muted``, tắt cả hàng)
    """
    clip_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: float = 0.0
    duration: float = 5.0
    source_path: str = ""
    media_type: str = "video"
    in_point: float = 0.0
    out_point: float = 5.0
    # Full duration of the decoded source. Generated media (image/text/etc.)
    # intentionally ignore this limit and may be extended indefinitely.
    source_duration: float = 0.0
    name: str = ""
    transform: TransformData = field(default_factory=TransformData)
    track_id: str = ""
    effects: list = field(default_factory=list)  # list[EffectData]
    # {"name": str, "duration": float} — xem core/transitions.py
    transition: dict = field(default_factory=dict)
    # ── Audio per-clip ──
    # Bốn giá trị này là dữ liệu clip, không phải state của slider: preview lẫn
    # export phải đọc cùng một chỗ, nếu không người dùng chỉnh ô nghe thử rồi
    # xuất ra file lại mang âm lượng khác.
    volume: float = 1.0        # 0.0 .. 2.0 (1.0 = 100%)
    speed: float = 1.0         # MIN_SPEED .. MAX_SPEED, 1.0 = tốc độ gốc
    fade_in: float = 0.0       # giây, ramp to dần ở ĐẦU clip
    fade_out: float = 0.0      # giây, ramp nhỏ dần ở CUỐI clip
    # Cờ tắt tiếng của RIÊNG clip. Không phải volume=0: người dùng bật tiếng lại
    # phải lấy đúng số âm lượng cũ, còn volume=0 thì mất con số đó.
    audio_muted: bool = False
    # Style is project data, not UI-only state.  Keeping it on the clip makes
    # Timeline and Player rebuild the same preset after save/load.
    font_family: str = "Arial"
    font_size: float = 40.0
    font_bold: bool = True
    font_italic: bool = False
    font_underline: bool = False
    font_color: str = "#FFFFFF"
    # Hoạt ảnh chữ (core.anim_engine.TEXT_KEYS) — "none" là chữ đứng yên.
    text_effect: str = "none"
    text_effect_intensity: float = 0.6
    # Kiểu karaoke (core.karaoke_paint.STYLE_KEYS) — mô tả MÀU của từng từ,
    # độc lập với text_effect ở trên nên hai thứ dùng chung được.
    text_style: str = "none"
    sticker_icon: str = ""
    sticker_color: str = "#FFFFFF"
    keyframes: dict = field(default_factory=lambda: {
        'x': [],         # [(time_sec, value)]
        'y': [],
        'scale_x': [],
        'scale_y': [],
        'rotation': [],
        'opacity': []
    })

    def add_keyframe(self, property_name: str, time_sec: float, value: float,
                     ease: str = "linear"):
        """Thêm hoặc ghi đè một keyframe tại thời điểm nhất định."""
        from core.keyframe_manager import make_frame, normalize_ease, frame_ease
        if property_name not in self.keyframes:
            self.keyframes[property_name] = []
        frames = self.keyframes[property_name]

        # Tìm xem đã có keyframe nào ở thời điểm này chưa (cho phép sai số nhỏ 0.01s)
        for i, frame in enumerate(frames):
            if abs(frame[0] - time_sec) < 0.01:
                # Ghi đè giá trị. Một lời gọi không nói rõ đường cong (ease
                # "linear") không được phép âm thầm xoá cong người dùng đã chọn;
                # muốn đổi cong phải đi qua set_keyframe_ease.
                keep = normalize_ease(ease) == "linear" and frame_ease(frame) != "linear"
                frames[i] = make_frame(time_sec, value,
                                       frame_ease(frame) if keep else ease)
                return

        # Nếu chưa có, thêm mới và sắp xếp lại mảng theo thứ tự thời gian
        frames.append(make_frame(time_sec, value, ease))
        frames.sort(key=lambda k: k[0])

    def set_keyframe_ease(self, property_name: str, time_sec: float,
                          ease: str) -> bool:
        """Đặt đường cong cho keyframe đang có. True nếu sửa được."""
        from core.keyframe_manager import make_frame, frame_ease, normalize_ease
        frames = self.keyframes.get(property_name, [])
        for i, frame in enumerate(frames):
            if abs(frame[0] - time_sec) < 0.01:
                frames[i] = make_frame(frame[0], frame[1], ease)
                return True
        return False

    def get_keyframe_ease(self, property_name: str, time_sec: float) -> str:
        from core.keyframe_manager import DEFAULT_EASE, frame_ease
        for frame in self.keyframes.get(property_name, []):
            if abs(frame[0] - time_sec) < 0.01:
                return frame_ease(frame)
        return DEFAULT_EASE

    def toggle_keyframe_at(self, property_name: str, time_sec: float, value: float) -> bool:
        """Bật/tắt keyframe tại thời điểm chỉ định. Trả về True nếu thêm mới, False nếu xóa."""
        if property_name not in self.keyframes:
            self.keyframes[property_name] = []
        frames = self.keyframes[property_name]
        
        # Xem đã có keyframe nào chưa
        for i, frame in enumerate(frames):
            if abs(frame[0] - time_sec) < 0.01:
                frames.pop(i)
                return False  # Đã xóa keyframe
                
        self.add_keyframe(property_name, time_sec, value)
        return True  # Đã thêm keyframe mới

    def get_value_at_time(self, property_name: str, current_time: float, default_value: float) -> float:
        """Trả về giá trị nội suy (theo đường cong) tại thời điểm hiện tại.

        Ủy quyền cho ``interpolate_keyframes`` — nguồn nội suy duy nhất dùng
        chung cho cả preview lẫn export.
        """
        from core.keyframe_manager import interpolate_keyframes
        return interpolate_keyframes(
            self.keyframes.get(property_name, []), current_time, default_value
        )

    def get_keyframe_manager(self):
        """Lấy KeyframeManager cho clip này (compatibility wrapper)."""
        from core.keyframe_manager import KeyframeManager
        km = KeyframeManager()
        km.load_from_dict(self.keyframes)
        return km

    @property
    def end_time(self) -> float:
        """Thời điểm kết thúc = start + duration."""
        return self.start_time + self.duration

    @property
    def speed_factor(self) -> float:
        """Tốc độ phát đã kẹp vào khoảng hợp lệ — số duy nhất mọi phép ánh xạ dùng."""
        try:
            value = float(self.speed)
        except (TypeError, ValueError):
            return 1.0
        if value <= 0.0:
            return 1.0
        return max(MIN_SPEED, min(MAX_SPEED, value))

    @property
    def volume_level(self) -> float:
        try:
            value = float(self.volume)
        except (TypeError, ValueError):
            return 1.0
        return max(MIN_VOLUME, min(MAX_VOLUME, value))

    def source_at_local(self, local_time: float) -> float:
        """Giây trong file gốc tại ``local_time`` (0 = đầu clip trên timeline)."""
        return float(self.in_point) + max(0.0, float(local_time)) * self.speed_factor

    def source_time(self, timeline_time: float) -> float:
        """Giây trong file gốc tại một thời điểm của timeline.

        Điểm vào CHUNG cho preview lẫn export. Nếu mỗi bên tự cộng
        ``in_point + local`` thì clip 2x chạy đúng ở ô nghe thử nhưng xuất ra
        vẫn phát tốc độ gốc, và ngược lại.
        """
        return self.source_at_local(float(timeline_time) - float(self.start_time))

    def local_time_at(self, timeline_time: float) -> float:
        """Giây thứ bao nhiêu CỦA CLIP tại một thời điểm của timeline.

        Điểm vào CHUNG cho preview lẫn export, cùng lý do với ``source_time``:
        hai bên trước đây tự viết ``t - clip.start_time`` và kẹp về ``duration -
        1e-6`` theo hai cách khác nhau, nên khung cuối của clip đọc sang nguồn
        quá mốc mà export vẫn dựng, còn preview thì không.

        Trả về [0, duration). Ngoài hai đầu clip thì kẹp vào chính biên, KHÔNG
        phải trả số âm: ``active_visual_clips_at`` đã giữ khung cuối khi playhead
        nằm đúng ở cuối dự án, và hiệu ứng nhịp (progress, aura, karaoke) cần
        một đồng hồ luôn nằm trong clip.
        """
        t = float(timeline_time)
        end = self.end_time
        if t >= end:
            t = max(float(self.start_time), end - 0.000001)
        return max(0.0, t - float(self.start_time))

    def timeline_at_source(self, source_seconds: float) -> float:
        """Chiều ngược lại: thời điểm timeline khi biết con số trong file gốc.

        Dùng cho QMediaPlayer, vì player báo position theo đồng hồ của chính
        file nguồn — với clip 2x thì mỗi giây nguồn đi mất nửa giây timeline.
        """
        return self.start_time + max(0.0, float(source_seconds) - float(self.in_point)
                                     ) / self.speed_factor

    def consumed_source(self) -> float:
        """Đoạn nguồn clip này dùng: duration trên timeline nhân tốc độ."""
        return max(0.1, float(self.duration)) * self.speed_factor

    def clamp_speed(self, value: float) -> float:
        """Đổi tốc độ và giữ nguyên nội dung đang xem: mép đầu nguồn bất biến.

        Kẹp duration để đúng ``consumed_source()`` không vượt quá nguồn còn lại,
        vì kéo tốc độ lên 4x mà giữ nguyên 10 giây timeline sẽ cần 40 giây nguồn.
        """
        self.speed = max(MIN_SPEED, min(MAX_SPEED, float(value)))
        if self.media_type in ("video", "audio") and self.source_duration > 0.0:
            room = max(0.1, self.source_duration - float(self.in_point))
            max_duration = room / self.speed_factor
            if self.duration > max_duration:
                self.duration = max(0.1, max_duration)
        self.out_point = float(self.in_point) + self.consumed_source()
        return self.speed

    def refresh_out_point(self):
        self.out_point = float(self.in_point) + self.consumed_source()

    def set_time_range(self, start: float, duration: float):
        """Cập nhật vị trí và thời lượng, đảm bảo giá trị hợp lệ."""
        self.start_time = max(0.0, start)
        self.duration = max(0.1, duration)  # Clip tối thiểu 0.1 giây

    def clone(self) -> "ClipModel":
        """Tạo bản sao với UUID mới."""
        import copy
        new_clip = copy.deepcopy(self)
        new_clip.clip_id = str(uuid.uuid4())
        return new_clip


@dataclass
class TrackModel:
    """
    Đại diện một track trên timeline.

    Attributes:
        track_id:    UUID duy nhất
        track_type:  Loại track (VIDEO, AUDIO, TEXT, ...)
        name:        Tên hiển thị
        clips:       Danh sách clip trên track
        z_index:     Thứ tự layer (cao hơn = hiển thị trên)
        is_locked:   Khóa chỉnh sửa
        is_visible:  Hiển thị trên canvas
        is_muted:    Tắt tiếng (cho audio track)
        color:       Màu hiển thị track
        height:      Chiều cao track (pixel) trên timeline
    """
    track_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    track_type: TrackType = TrackType.VIDEO
    name: str = ""
    clips: list = field(default_factory=list)
    z_index: int = 0
    is_locked: bool = False
    is_visible: bool = True
    is_muted: bool = False
    color: str = ""
    height: float = 60.0
    is_main_track: bool = False

    def __post_init__(self):
        if not self.color:
            self.color = TRACK_COLORS.get(self.track_type, "#4FC3F7")
        if not self.name:
            self.name = f"{self.track_type.name.capitalize()} Track"

    @property
    def is_magnetic(self) -> bool:
        """Only Main Storyline owns gapless/ripple placement semantics."""
        return self.track_type == TrackType.VIDEO and self.is_main_track

    def get_end_time(self) -> float:
        """Thời điểm kết thúc của clip cuối cùng trên track."""
        if not self.clips:
            return 0.0
        return max(c.end_time for c in self.clips)

    def find_clip_at(self, time: float) -> Optional[ClipModel]:
        """Tìm clip tại vị trí thời gian."""
        for clip in self.clips:
            if clip.start_time <= time < clip.end_time:
                return clip
        return None

    def has_overlap(self, start: float, duration: float,
                    exclude_id: str = "") -> bool:
        """Kiểm tra xem khoảng thời gian có chồng lấn clip nào không."""
        end = start + duration
        for clip in self.clips:
            if clip.clip_id == exclude_id:
                continue
            if clip.start_time < end and clip.end_time > start:
                return True
        return False


# ── Timeline Model (QObject — phát Signal) ──────────────────────

class TimelineModel(QObject):
    """
    Model trung tâm quản lý toàn bộ dữ liệu timeline.

    Tất cả thay đổi phải đi qua các method của class này
    để đảm bảo Signal được phát chính xác cho UI.

    Signals:
        trackAdded(TrackModel)     — track mới được thêm
        trackRemoved(str)          — track bị xóa (track_id)
        clipAdded(ClipModel)       — clip mới được thêm
        clipRemoved(str)           — clip bị xóa (clip_id)
        clipMoved(str, float)      — clip di chuyển (clip_id, new_start)
        clipResized(str, float)    — clip resize (clip_id, new_duration)
        playheadChanged(float)     — playhead di chuyển (time)
        durationChanged(float)     — tổng thời lượng thay đổi
        selectionChanged(list)     — danh sách clip_id được chọn thay đổi
    """

    trackAdded = Signal(object)
    trackRemoved = Signal(str)
    tracksReordered = Signal()
    clipAdded = Signal(object)
    clipRemoved = Signal(str)
    clipMoved = Signal(str, float)
    clipResized = Signal(str, float)
    clipUpdated = Signal(str)          # clip_id cập nhật thuộc tính (transform/name)
    playheadChanged = Signal(float)
    durationChanged = Signal(float)
    selectionChanged = Signal(list)
    recapOverlayChanged = Signal(dict)   # lớp phủ recap cấp dự án

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[TrackModel] = []
        self._playhead: float = 0.0
        self._duration: float = 30.0       # mặc định 30 giây
        self._selected_ids: list[str] = []
        self._track_counter = {t: 0 for t in TrackType}
        self._project_ratio: str = "16:9"  # Tỉ lệ khung hình hiện tại
        self._recap_overlay: dict = dict(recap_overlay.OVERLAY_DEFAULTS)

    # ── Properties ──────────────────────────────────────────────

    @property
    def tracks(self) -> list[TrackModel]:
        return self._tracks

    @property
    def playhead(self) -> float:
        return self._playhead

    @playhead.setter
    def playhead(self, value: float):
        value = max(0.0, min(value, self._duration))
        if value != self._playhead:
            self._playhead = value
            self.playheadChanged.emit(value)

    @property
    def duration(self) -> float:
        return self._duration

    @duration.setter
    def duration(self, value: float):
        value = max(1.0, value)
        if value != self._duration:
            self._duration = value
            self.durationChanged.emit(value)

    @property
    def selected_clip_ids(self) -> list[str]:
        return self._selected_ids

    @property
    def project_ratio(self) -> str:
        return self._project_ratio

    @project_ratio.setter
    def project_ratio(self, value: str):
        self._project_ratio = value

    @property
    def recap_overlay(self) -> dict:
        """Cấu hình lớp phủ recap của CẢ dự án (viền, nền kính, tâm ngắm, REC).

        Trả về dict đã điền đủ khoá nên nơi gọi không cần kiểm tra None; đây là
        thứ mà FrameComposer và PreviewCanvas cùng đọc để hai bên không lệch.
        """
        return recap_overlay.normalize(self._recap_overlay)

    def set_recap_overlay(self, settings, emit: bool = True):
        self._recap_overlay = recap_overlay.normalize(settings)
        if emit:
            self.recapOverlayChanged.emit(dict(self._recap_overlay))

    # ── Track Management ────────────────────────────────────────

    def add_track(self, track_type: TrackType = TrackType.VIDEO,
                  name: str = "", z_index: int = -1,
                  track_id: str = "", is_main_track: bool = False,
                  restore_mode: bool = False) -> TrackModel:
        """Thêm typed track theo trật tự NLE: overlay > main video > audio."""
        self._track_counter[track_type] += 1
        count = self._track_counter[track_type]

        if not name:
            name = f"{track_type.name.capitalize()} {count}"

        existing_main = next(
            (t for t in self._tracks
             if t.track_type == TrackType.VIDEO and t.is_main_track), None)
        if track_type != TrackType.VIDEO:
            is_main_track = False
        elif not restore_mode:
            # Singleton invariant: the first video row is the only magnetic
            # Main Storyline. Every later video row is an OverlayTrack.
            is_main_track = existing_main is None

        track = TrackModel(
            track_id=track_id or str(uuid.uuid4()),
            track_type=track_type,
            name=name,
            z_index=z_index,
            is_main_track=is_main_track,
            color=TRACK_COLORS.get(track_type, "#4FC3F7"),
            height=(58.0 if is_main_track else
                    46.0 if track_type in (TrackType.VIDEO, TrackType.IMAGE) else
                    40.0),
        )
        if track_type == TrackType.AUDIO:
            self._tracks.append(track)
        elif is_main_track:
            # Main Storyline là hàng visual cuối cùng, ngay trên audio.
            audio_index = next((i for i, t in enumerate(self._tracks)
                                if t.track_type == TrackType.AUDIO), len(self._tracks))
            self._tracks.insert(audio_index, track)
        else:
            # Overlay/text/image/effect nằm trên Main Storyline.
            main_index = next((i for i, t in enumerate(self._tracks)
                               if t.is_main_track),
                              next((i for i, t in enumerate(self._tracks)
                                    if t.track_type == TrackType.AUDIO), len(self._tracks)))
            self._tracks.insert(main_index, track)
        self._normalize_track_layers(enforce_main=not restore_mode)
        self.trackAdded.emit(track)
        self.tracksReordered.emit()
        return track

    def _normalize_track_layers(self, enforce_main: bool = True):
        """UI xếp trên→dưới; canvas render visual dưới→trên."""
        if enforce_main:
            self._enforce_single_main_storyline()
        visual = [t for t in self._tracks if t.track_type != TrackType.AUDIO]
        for layer, track in enumerate(reversed(visual)):
            track.z_index = layer
        self._normalize_track_names()

    def _enforce_single_main_storyline(self):
        """Repair invalid/legacy projects and keep one magnetic video row."""
        video_tracks = [t for t in self._tracks
                        if t.track_type == TrackType.VIDEO]
        if not video_tracks:
            return
        marked = [t for t in video_tracks if t.is_main_track]
        # UI order is top-to-bottom, so the bottom-most marked video is the
        # safest Main Storyline for legacy projects containing duplicates.
        keeper = marked[-1] if marked else video_tracks[-1]
        for track in video_tracks:
            track.is_main_track = track is keeper
            track.height = 58.0 if track is keeper else 46.0

    def _normalize_track_names(self):
        """Derive generated track labels from live rows, not add history."""
        counters = {track_type: 0 for track_type in TrackType}
        labels = {
            TrackType.VIDEO: "Video",
            TrackType.AUDIO: "Audio",
            TrackType.IMAGE: "Image",
            TrackType.TEXT: "Text",
            TrackType.EFFECT: "Effect",
            TrackType.OVERLAY: "Sticker",
        }
        for track in self._tracks:
            if track.is_main_track:
                track.name = "Main Storyline"
                continue
            counters[track.track_type] += 1
            track.name = f"{labels[track.track_type]} {counters[track.track_type]}"
        self._track_counter = counters

    def move_track(self, track_id: str, new_index: int) -> bool:
        """Sắp xếp track qua model; Header và Body cùng nghe một signal."""
        track = self.get_track(track_id)
        if track is None:
            return False
        old_index = self._tracks.index(track)
        new_index = max(0, min(new_index, len(self._tracks) - 1))

        # Audio luôn thuộc nửa dưới. Main video không thể rời khỏi
        # vị trí visual cuối cùng; overlay không thể chui xuống dưới main.
        audio_start = next((i for i, t in enumerate(self._tracks)
                            if t.track_type == TrackType.AUDIO), len(self._tracks))
        main_index = next((i for i, t in enumerate(self._tracks)
                           if t.is_main_track), audio_start)
        if track.track_type == TrackType.AUDIO:
            new_index = max(audio_start, new_index)
        elif track.is_main_track:
            new_index = max(0, audio_start - 1)
        else:
            new_index = min(new_index, max(0, main_index - 1))
        if new_index == old_index:
            return False
        self._tracks.pop(old_index)
        self._tracks.insert(new_index, track)
        self._normalize_track_layers()
        self.tracksReordered.emit()
        return True

    def remove_track(self, track_id: str):
        """Xóa track và tất cả clip trên nó."""
        self._remove_track_by_id(track_id, remove_clips=True)

    def _remove_track_by_id(self, track_id: str, remove_clips: bool = True):
        """Xóa track theo ID. remove_clips=True sẽ xóa cả clip con."""
        for i, track in enumerate(self._tracks):
            if track.track_id == track_id:
                if remove_clips:
                    for clip in list(track.clips):
                        self._remove_clip_from_track(clip.clip_id, track)
                self._tracks.pop(i)
                self._normalize_track_layers(enforce_main=True)
                self.trackRemoved.emit(track_id)
                self.tracksReordered.emit()
                return

    def _remove_clip_from_track(self, clip_id: str, track: TrackModel):
        """Xóa clip khỏi track cụ thể (không trigger auto-remove)."""
        for i, clip in enumerate(track.clips):
            if clip.clip_id == clip_id:
                track.clips.pop(i)
                if clip_id in self._selected_ids:
                    self._selected_ids.remove(clip_id)
                self.clipRemoved.emit(clip_id)
                return

    def get_track(self, track_id: str) -> Optional[TrackModel]:
        """Tìm track theo ID."""
        for track in self._tracks:
            if track.track_id == track_id:
                return track
        return None

    def is_track_empty(self, track_id: str) -> bool:
        """Kiểm tra track có trống không."""
        track = self.get_track(track_id)
        return track is not None and len(track.clips) == 0

    def get_empty_tracks(self) -> list[TrackModel]:
        """Lấy danh sách tracks trống."""
        return [t for t in self._tracks if len(t.clips) == 0]

    def get_tracks_with_content(self) -> list[TrackModel]:
        """Lấy danh sách tracks có nội dung."""
        return [t for t in self._tracks if len(t.clips) > 0]

    def find_or_create_track(self, track_type: TrackType) -> TrackModel:
        """Tìm track trống cùng loại hoặc tạo track mới."""
        # Ưu tiên tìm track trống cùng loại (reuse)
        for track in self._tracks:
            if track.track_type == track_type and len(track.clips) == 0:
                return track
        # Nếu không có track trống, tìm track bất kỳ cùng loại
        for track in self._tracks:
            if track.track_type == track_type:
                return track
        return self.add_track(track_type)

    def track_index_at_y(
            self, scene_y: float,
            ruler_height: float = TIMELINE_RULER_HEIGHT,
            track_top_padding: float = TIMELINE_TRACK_TOP_PADDING) -> int:
        """Nguồn quy đổi Y→track duy nhất cho drop và drag."""
        if not self._tracks:
            return -1
        y = scene_y - ruler_height - track_top_padding
        if y < 0.0:
            return -1
        top = 0.0
        for index, track in enumerate(self._tracks):
            if y < top + track.height + TIMELINE_TRACK_GAP:
                return index
            top += track.height + TIMELINE_TRACK_GAP
        return len(self._tracks) - 1

    # ── Clip Management ─────────────────────────────────────────

    def recalculate_main_storyline(self, track: TrackModel, ordered=None):
        """Single authority for Main Storyline ordering, time anchors and duration.

        Gapless means "kế nhau", không có nghĩa là "không chồng": một clip mang
        chuyển tiếpjunction bắt buộc chồng lên clip trước đúng bằng duration của
        nó. Vì compact là nguồn sự thật duy nhất cho thứ tự timeline, mọi thao
        tác (thêm/xóa/kéo/cắt/trim) đều tự giữ nguyên các cửa sổ chuyển tiếp.
        """
        if track is None or not track.is_main_track:
            return
        clips = list(ordered) if ordered is not None else sorted(
            track.clips, key=lambda c: c.start_time)
        cursor = 0.0
        previous = None
        for item in clips:
            start = max(0.0, cursor - transitions.overlap_for(item, previous))
            if abs(item.start_time - start) > 0.0001:
                item.start_time = start
                self.clipMoved.emit(item.clip_id, start)
            cursor = item.end_time
            previous = item
        track.clips[:] = clips
        self.recalculate_project_duration()

    def _compact_main_track(self, track: TrackModel, ordered=None):
        """Backward-compatible internal name."""
        self.recalculate_main_storyline(track, ordered)

    def recalculate_project_duration(self):
        """Recompute duration after both growth and shrink operations."""
        end_time = max((clip.end_time for track in self._tracks
                        for clip in track.clips), default=1.0)
        self.duration = max(1.0, end_time)
        if self._playhead > self._duration:
            self.playhead = self._duration

    @staticmethod
    def _track_interval_is_free(track: TrackModel, start: float, duration: float,
                                exclude_id: str = "") -> bool:
        end = start + duration
        return not any(c.clip_id != exclude_id and c.start_time < end
                       and c.end_time > start for c in track.clips)

    def _create_collision_track(self, source_track: TrackModel) -> TrackModel:
        """Bounce a colliding overlay into a new compatible layer above Main."""
        source_index = self._tracks.index(source_track)
        created = self.add_track(source_track.track_type)
        self._tracks.remove(created)
        self._tracks.insert(source_index, created)
        self._normalize_track_layers()
        self.tracksReordered.emit()
        return created

    def add_clip(self, track_id: str, source_path: str,
                 media_type: str = "video", start_time: float = 0.0,
                 duration: float = 5.0, name: str = "") -> Optional[ClipModel]:
        """Thêm clip vào track. Tự tìm vị trí không chồng lấn nếu cần."""
        track = self.get_track(track_id)
        if (track is None or track.is_locked or
                not track_accepts_media(track.track_type, media_type)):
            return None

        if not track.is_magnetic:
            start_time = max(0.0, start_time)
            if not self._track_interval_is_free(track, start_time, duration):
                track = self._create_collision_track(track)
                track_id = track.track_id
            clip = ClipModel(
                start_time=start_time, duration=duration,
                source_path=source_path, media_type=media_type,
                name=name or source_path.split("/")[-1].split("\\")[-1],
                in_point=0.0, out_point=duration,
                source_duration=duration, track_id=track_id,
            )
            track.clips.append(clip)
            track.clips.sort(key=lambda c: c.start_time)
            self.recalculate_project_duration()
            self.clipAdded.emit(clip)
            return clip

        # Magnetic drop ignores the pointer's X coordinate. Existing clips are
        # first repaired into one gapless sequence, then the new media is
        # appended at the exact end. Reordering an existing clip remains a
        # separate ripple operation handled by place_clip_ripple().
        self.recalculate_main_storyline(track)
        start_time = track.get_end_time()

        clip = ClipModel(
            start_time=start_time,
            duration=duration,
            source_path=source_path,
            media_type=media_type,
            name=name or source_path.split("/")[-1].split("\\")[-1],
            in_point=0.0,
            out_point=duration,
            source_duration=duration,
            track_id=track_id,
        )
        track.clips.append(clip)
        self._compact_main_track(track)
        self._auto_extend_duration(max((c.end_time for c in track.clips), default=clip.end_time))
        self.clipAdded.emit(clip)
        return clip

    def remove_clip(self, clip_id: str):
        """Xóa clip khỏi track. Tự động xóa track nếu trống."""
        for track in self._tracks:
            for i, clip in enumerate(track.clips):
                if clip.clip_id == clip_id:
                    removed_start = clip.start_time
                    removed_end = clip.end_time
                    removed_duration = clip.duration
                    track.clips.pop(i)
                    if clip_id in self._selected_ids:
                        self._selected_ids.remove(clip_id)
                    self.clipRemoved.emit(clip_id)

                    # Magnetic Main Storyline: đóng khoảng trống khi xóa.
                    if track.is_main_track:
                        self.recalculate_main_storyline(track)
                    else:
                        self.recalculate_project_duration()

                    # Track động: xóa ngay khi clip cuối cùng bị xóa.
                    if len(track.clips) == 0:
                        self._remove_track_by_id(track.track_id)
                    return

    def move_clip(self, clip_id: str, new_start: float,
                  new_track_id: str = ""):
        """Di chuyển clip đến vị trí mới (và có thể sang track khác)."""
        clip, old_track = self._find_clip(clip_id)
        if clip is None or old_track.is_locked:
            return

        new_start = max(0.0, new_start)
        source_track_became_empty = False

        # Chuyển track nếu cần
        if new_track_id and new_track_id != old_track.track_id:
            new_track = self.get_track(new_track_id)
            if new_track and not new_track.is_locked:
                old_track.clips.remove(clip)
                clip.track_id = new_track_id
                new_track.clips.append(clip)
                # Kiểm tra track nguồn có trống không
                if len(old_track.clips) == 0:
                    source_track_became_empty = True

        clip.start_time = new_start
        self.recalculate_project_duration()
        self.clipMoved.emit(clip_id, new_start)

        # Dynamic Track Management: Xóa track nguồn nếu trống
        if source_track_became_empty:
            self._remove_track_by_id(old_track.track_id)

    def place_clip_ripple(self, clip_id: str, desired_start: float):
        """Đặt clip vào track mà không chồng lấn, ripple các clip kế cận."""
        clip, track = self._find_clip(clip_id)
        if clip is None or track is None or track.is_locked:
            return
        desired_start = max(0.0, desired_start)
        others = sorted((c for c in track.clips if c.clip_id != clip_id),
                        key=lambda c: c.start_time)
        if track.is_main_track:
            insert_index = len(others)
            for index, other in enumerate(others):
                if desired_start < other.start_time + other.duration / 2.0:
                    insert_index = index
                    break
            ordered = others[:insert_index] + [clip] + others[insert_index:]
            self._compact_main_track(track, ordered)
            self._auto_extend_duration(max((c.end_time for c in ordered), default=0.0))
            return

        clip.start_time = desired_start
        if not self._track_interval_is_free(
                track, desired_start, clip.duration, exclude_id=clip.clip_id):
            new_track = self._create_collision_track(track)
            if clip in track.clips:
                track.clips.remove(clip)
            clip.track_id = new_track.track_id
            new_track.clips.append(clip)
            track = new_track
        track.clips.sort(key=lambda c: c.start_time)
        self.recalculate_project_duration()
        self.clipMoved.emit(clip_id, clip.start_time)
        for empty in list(self.get_empty_tracks()):
            if not empty.is_main_track:
                self._remove_track_by_id(empty.track_id)
        return
        collision = next((c for c in others
                          if c.start_time < desired_start + clip.duration and
                          c.end_time > desired_start), None)
        if collision:
            before = desired_start < collision.start_time + collision.duration / 2.0
            insert_time = collision.start_time if before else collision.end_time
            for existing in reversed(others):
                if existing.start_time >= insert_time or (before and existing is collision):
                    existing.start_time += clip.duration
                    self.clipMoved.emit(existing.clip_id, existing.start_time)
            desired_start = insert_time
        clip.start_time = desired_start
        self._auto_extend_duration(max((c.end_time for c in track.clips), default=clip.end_time))
        self.clipMoved.emit(clip_id, desired_start)

    def resize_clip(self, clip_id: str, new_duration: float,
                    from_start: bool = False):
        """Thay đổi thời lượng clip (trim từ đầu hoặc cuối)."""
        clip, track = self._find_clip(clip_id)
        if clip is None or track.is_locked:
            return

        new_duration = max(0.1, new_duration)

        if (clip.media_type in ("video", "audio") and
                clip.source_duration > 0.0):
            # Nguồn bị ăn theo tốc độ: clip 10 giây ở 2x cần 20 giây nguồn, nên
            # trần duration là phần nguồn còn lại CHIA cho speed.
            available = max(0.1, clip.source_duration - clip.in_point)
            new_duration = min(new_duration, available / clip.speed_factor)

        if from_start:
            delta = clip.duration - new_duration
            clip.start_time = max(0.0, clip.start_time + delta)
            clip.in_point += delta * clip.speed_factor

        clip.duration = new_duration
        clip.refresh_out_point()
        if track.is_main_track:
            self.recalculate_main_storyline(track)
        else:
            self.recalculate_project_duration()
        self.clipResized.emit(clip_id, new_duration)

    def split_clip(self, clip_id: str, split_time: float) -> Optional[ClipModel]:
        """Cắt clip thành 2 tại thời điểm chỉ định."""
        clip, track = self._find_clip(clip_id)
        if clip is None or track.is_locked:
            return None

        if split_time <= clip.start_time or split_time >= clip.end_time:
            return None

        # Phần 2: từ split_time đến end
        right_duration = clip.end_time - split_time
        right_clip = clip.clone()
        right_clip.start_time = split_time
        right_clip.duration = right_duration
        # Mép cắt là thời điểm TIMELINE; giây trong nguồn phải qua ánh xạ speed
        # thì hai nửa mới nối đúng một mạch nội dung ở 2x hay 0.5x.
        right_clip.in_point = clip.source_time(split_time)
        right_clip.refresh_out_point()
        right_clip.name = clip.name + " (2)"
        right_clip.track_id = track.track_id

        # Phần 1: rút ngắn clip gốc
        clip.duration = split_time - clip.start_time
        clip.refresh_out_point()
        self.clipResized.emit(clip.clip_id, clip.duration)

        right_clip.transition = {}
        # Ramp fade_in/fade_out gắn với mép của clip. Sau khi cắt, mép cũ của nửa
        # phải và mép mới của nửa trái nằm giữa cùng một nguồn, nên mỗi nửa chỉ
        # giữ cái ramp thuộc phía mình — nếu không tiếng sẽ fade hai lần ở chỗ cắt.
        clip.fade_in = min(clip.fade_in, clip.duration)
        clip.fade_out = 0.0
        right_clip.fade_in = 0.0
        right_clip.fade_out = min(right_clip.fade_out, right_duration)
        # Transition mô tả cú CẮT ở mép trái clip. Sau khi cắt đôi, cú cắt cũ
        # vẫn thuộc nửa trái; nửa phải đứng giữa nội dung của cùng một nguồn nên
        # không được mang theo chuyển tiếp (nếu không compact sẽ chồng hai nửa
        # lên nhau và "nuốt" mất một đoạn hình).
        track.clips.append(right_clip)
        if track.is_main_track:
            self.recalculate_main_storyline(track)
        else:
            self.recalculate_project_duration()
        self.clipAdded.emit(right_clip)
        return right_clip

    def duplicate_clip(self, clip_id: str) -> Optional[ClipModel]:
        """Nhân bản clip, đặt ngay sau clip gốc."""
        clip, track = self._find_clip(clip_id)
        if clip is None:
            return None

        new_clip = clip.clone()
        new_clip.start_time = clip.end_time
        new_clip.track_id = track.track_id
        new_clip.name = clip.name + " (copy)"
        track.clips.append(new_clip)
        if track.is_main_track:
            ordered = sorted((c for c in track.clips if c is not new_clip),
                             key=lambda c: c.start_time)
            source_index = ordered.index(clip)
            ordered.insert(source_index + 1, new_clip)
            self.recalculate_main_storyline(track, ordered)
        else:
            if not self._track_interval_is_free(
                    track, new_clip.start_time, new_clip.duration,
                    exclude_id=new_clip.clip_id):
                new_track = self._create_collision_track(track)
                track.clips.remove(new_clip)
                new_clip.track_id = new_track.track_id
                new_track.clips.append(new_clip)
            self.recalculate_project_duration()
        self.clipAdded.emit(new_clip)
        return new_clip

    # ── Transitions ─────────────────────────────────────────────

    def _track_neighbors(self, clip: ClipModel):
        """Clip kề trái/kề phải của ``clip`` trên cùng track, theo thứ tự time."""
        track = self.get_track(clip.track_id)
        if track is None:
            return None, None
        ordered = sorted(track.clips, key=lambda c: (c.start_time, c.end_time))
        index = next((i for i, item in enumerate(ordered) if item is clip), -1)
        if index < 0:
            return None, None
        previous = ordered[index - 1] if index > 0 else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        return previous, following

    def previous_clip(self, clip: ClipModel) -> Optional[ClipModel]:
        return self._track_neighbors(clip)[0]

    def next_clip(self, clip: ClipModel) -> Optional[ClipModel]:
        return self._track_neighbors(clip)[1]

    def max_transition_duration(self, clip_id: str, name: str) -> float:
        """Duration tối nhất UI cho phép với clip này; 0 = không dùng được."""
        clip, track = self._find_clip(clip_id)
        if clip is None or track is None or track.is_locked:
            return 0.0
        if transitions.is_local(name):
            return transitions.local_room(clip)
        if not transitions.is_junction(name):
            return 0.0
        # Junction chỉ sống trên Main Storyline: đó là track duy nhất có quy
        # tắc compact tường minh, nên chồng lấn được tạo lại sau mọi thao tác.
        # Overlay track dùng logic "va chạm là nhảy layer", sẽ phá chồng lấn.
        if not track.is_main_track:
            return 0.0
        return transitions.max_duration(self.previous_clip(clip), clip)

    def set_transition(self, clip_id: str, name: str,
                       duration: float = None) -> bool:
        """Gắn (hoặc xóa với name rỗng) chuyển tiếp tại mép trái clip.

        Gắn transition là một ripple edit: clip này và mọi clip sau nó trên Main
        Storyline trượt trái đúng ``duration`` giây để tạo chồng lấn thật. Xóa thì
        trượt trả lại chỗ cũ.
        """
        clip, track = self._find_clip(clip_id)
        if clip is None or track is None or track.is_locked:
            return False

        if not name:
            if clip.transition:
                clip.transition = {}
            if track.is_main_track:
                self.recalculate_main_storyline(track)
            else:
                self.recalculate_project_duration()
            self.clipUpdated.emit(clip_id)
            return True

        requested = transitions.DEFAULT_DURATION if duration is None else duration
        room = self.max_transition_duration(clip_id, name)
        if room <= 0.0:
            return False
        applied = (transitions.clamp_duration(requested, self.previous_clip(clip), clip)
                   if transitions.is_junction(name)
                   else transitions.clamp_local(requested, clip))
        if applied <= 0.0:
            return False

        clip.transition = transitions.make(name, applied)
        if track.is_main_track:
            self.recalculate_main_storyline(track)
        else:
            self.recalculate_project_duration()
        self.clipUpdated.emit(clip_id)
        return True

    def set_clip_audio(self, clip_id: str, volume=None, speed=None,
                       fade_in=None, fade_out=None, audio_muted=None) -> dict:
        """Đổi audio của một clip, trả về ĐÚNG giá trị đã áp.

        Panel không được tin con số trên slider: hai ramp fade phải kẹp vào nhau
        và tăng tốc độ có thể cắt ngắn duration khi nguồn không đủ dài. Model là
        nguồn sự thật, nên chính nó phải báo lại những gì đã áp dụng.
        """
        clip, track = self._find_clip(clip_id)
        if clip is None or track is None or track.is_locked:
            return {}

        before_duration = float(clip.duration)
        applied = {}

        if volume is not None:
            clip.volume = max(MIN_VOLUME, min(MAX_VOLUME, float(volume)))
        applied["volume"] = clip.volume

        if audio_muted is not None:
            clip.audio_muted = bool(audio_muted)
        applied["audio_muted"] = clip.audio_muted

        if fade_in is not None:
            clip.fade_in = max(0.0, float(fade_in))
        if fade_out is not None:
            clip.fade_out = max(0.0, float(fade_out))
        # transitions.clip_fade_spans là chỗ duy nhất biết cách kẹp hai ramp
        # (cả vào duration lẫn vào nhau); đọc lại từ đó thay vì tự min/max.
        clip.fade_in, clip.fade_out = transitions.clip_fade_spans(clip)
        applied["fade_in"] = clip.fade_in
        applied["fade_out"] = clip.fade_out

        if speed is not None:
            applied["speed"] = clip.clamp_speed(speed)

        if abs(float(clip.duration) - before_duration) > 0.0001:
            if track.is_main_track:
                self.recalculate_main_storyline(track)
            else:
                self.recalculate_project_duration()
            self.clipResized.emit(clip_id, clip.duration)

        self.clipUpdated.emit(clip_id)
        return applied

    def transition_state(self, clip: ClipModel, t: float,
                         canvas_w: float, canvas_h: float):
        """State vẽ của clip tại thời điểm t — điểm vào chung cho preview/export."""
        previous, following = self._track_neighbors(clip)
        return transitions.clip_state(clip, previous, following, t,
                                      canvas_w, canvas_h)

    def transition_gain(self, clip: ClipModel, t: float) -> float:
        previous, following = self._track_neighbors(clip)
        return transitions.clip_audio_gain(clip, previous, following, t)

    def transition_band(self, clip: ClipModel):
        """(kind, start, end) của vùng chuyển tiếp trên timeline, hoặc None.

        kind là "overlap" (chồng lấn của kiểu junction) hay "in"/"out" (dải local
        fade). Timeline chỉ tô theo con số này — đo từ cửa sổ thật thay vì
        duration đã lưu, vì trim clip bên trái co chồng lấn lại mà transition vẫn
        còn tên.
        """
        name = transitions.name_of(clip)
        if not name:
            return None
        if transitions.is_junction(name):
            pair = transitions.window(self._track_neighbors(clip)[0], clip)
            return None if pair is None else ("overlap", pair[0], pair[1])
        span = transitions.fade_span(clip)
        if transitions.kind_of(name) == transitions.KIND_LOCAL_IN:
            return ("in", clip.start_time, clip.start_time + span)
        return ("out", clip.end_time - span, clip.end_time)

    def transition_fades(self, clip: ClipModel):
        """Chuỗi ``afade`` ffmpeg cho riêng clip này, theo giây của chính nó.

        Điểm vào chung cho exporter: exporter không được tự suy ra cửa sổ
        chồng lấn, vì nó cần cả clip liền sau (chiều nhỏ dần) — thứ mà chuỗi
        filter không tự biết được.
        """
        previous, following = self._track_neighbors(clip)
        return transitions.audio_fades(clip, previous, following)

    # ── Selection ────────────────────────────────────────────────

    def select_clip(self, clip_id: str, add_to: bool = False):
        """Chọn clip. add_to=True để multi-select."""
        if not add_to:
            self._selected_ids.clear()
        if clip_id not in self._selected_ids:
            self._selected_ids.append(clip_id)
        self.selectionChanged.emit(self._selected_ids[:])

    def select_clips(self, clip_ids: list[str]):
        """Chọn nhiều clip trong một lần cập nhật state."""
        valid = [clip_id for clip_id in clip_ids if self.get_clip(clip_id)]
        if valid != self._selected_ids:
            self._selected_ids = valid
            self.selectionChanged.emit(self._selected_ids[:])

    def deselect_all(self):
        """Bỏ chọn tất cả."""
        self._selected_ids.clear()
        self.selectionChanged.emit([])

    def get_clip(self, clip_id: str) -> Optional[ClipModel]:
        """Tìm clip theo ID."""
        clip, _ = self._find_clip(clip_id)
        return clip

    def active_visual_clips_at(self, time_seconds: float) -> list[ClipModel]:
        """Single playhead query, ordered background -> foreground for Canvas."""
        query_time = max(0.0, float(time_seconds))
        # Preserve the final frame when playback stops exactly at project end,
        # while all normal edit boundaries remain half-open [start, end).
        if self._duration > 0.0 and query_time >= self._duration:
            query_time = max(0.0, self._duration - 0.000001)
        visual_tracks = sorted(
            (t for t in self._tracks
             if t.track_type != TrackType.AUDIO and t.is_visible),
            key=lambda t: t.z_index,
        )
        return [clip for track in visual_tracks for clip in track.clips
                if clip.media_type != "audio"
                and clip.start_time <= query_time < clip.end_time]

    def update_clip_properties(self, clip_id: str, name: Optional[str] = None,
                               scale_x: Optional[float] = None, scale_y: Optional[float] = None,
                               rotation: Optional[float] = None, opacity: Optional[float] = None,
                               x: Optional[float] = None, y: Optional[float] = None):
        """Cập nhật các thuộc tính kỹ thuật của clip từ Properties Panel và phát signal."""
        clip, _ = self._find_clip(clip_id)
        if not clip:
            return
        if name is not None:
            clip.name = name
        if scale_x is not None:
            clip.transform.scale_x = scale_x
        if scale_y is not None:
            clip.transform.scale_y = scale_y
        if rotation is not None:
            clip.transform.rotation = rotation
        if opacity is not None:
            clip.transform.opacity = opacity
        if x is not None:
            clip.transform.x = x
        if y is not None:
            clip.transform.y = y
        self.clipUpdated.emit(clip_id)

    # ── Internal Helpers ────────────────────────────────────────

    def _find_clip(self, clip_id: str):
        """Tìm clip và track chứa nó. Trả về (clip, track) hoặc (None, None)."""
        for track in self._tracks:
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return clip, track
        return None, None

    def _auto_extend_duration(self, needed: float):
        """Tự kéo dài duration nếu clip vượt quá."""
        if needed > self._duration:
            self.duration = needed + 5.0  # Thêm 5s buffer

    def get_all_clip_edges(self, exclude_id: str = "") -> list[float]:
        """Thu thập tất cả mép clip (đầu + cuối) — dùng cho snapping."""
        edges = []
        for track in self._tracks:
            for clip in track.clips:
                if clip.clip_id == exclude_id:
                    continue
                edges.append(clip.start_time)
                edges.append(clip.end_time)
        return sorted(set(edges))
