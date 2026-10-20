"""
core/anim_engine.py
Toán chuyển động theo NHỊP TIẾN ĐỘ của clip — dùng chung cho preview và export.

Khác với core.clip_effects.compute_animation_offsets (vốn nhận thời gian tường
minh), engine này chỉ nhận `p` = local_time / duration đã kẹp trong [0, 1], nên
cùng một hiệu ứng chạy trên preview lúc 12:00:03.4 và lúc render ra file cho
ra cùng một khung hình.

Mọi hàm ở đây THUẦN và không đụng tới GUI: trả về hệ số toạ độ HOÁ TRỊ
(dx theo chiều rộng, dy theo chiều cao khung) để cùng một con số dùng được cho
rect của item trên canvas lẫn canvas export ở mọi độ phân giải.

Hợp đồng trục: MotionState.dx = ±1 nghĩa là lệch trọn một khung hình theo
hướng đó; TextState.dx/dy = ±1 nghĩa là khối chữ nằm trọn NGOÀI mép khung.
"""

import math
from collections import namedtuple

# (khoá, tên hiển thị, mô tả)
MOTION_EFFECTS = (
    ("none", "None", "Keep the original clip"),
    ("zoom_in", "Ken Burns In", "Slowly push into the clip"),
    ("zoom_out", "Ken Burns Out", "Slowly pull away"),
    ("slide_left", "Slide Left", "Clip enters from the right"),
    ("slide_right", "Slide Right", "Clip enters from the left"),
    ("slide_up", "Slide Up", "Clip enters from below"),
    ("slide_down", "Slide Down", "Clip enters from above"),
    ("fade_in", "Fade In", "Fade in from black"),
    ("fade_out", "Fade Out", "Fade out to black"),
    ("pulse", "Pulse", "Rhythmic scale breathing"),
    ("spin", "Spin", "Rotate 360 degrees"),
    ("bounce", "Bounce", "Bounce up and down"),
)

TEXT_EFFECTS = (
    ("none", "Static", "Hold the text in place"),
    ("fade_in", "Fade In", "Text fades up from invisible"),
    ("fade_out", "Fade Out", "Text fades away at the end"),
    ("pop_in", "Pop In", "Scale up with a slight overshoot"),
    ("slide_in_left", "Slide From Left", "Text enters from the left edge"),
    ("slide_in_right", "Slide From Right", "Text enters from the right edge"),
    ("slide_in_up", "Slide From Below", "Text enters from the bottom edge"),
    ("slide_in_down", "Slide From Above", "Text enters from the top edge"),
    ("scroll_left", "Scroll Left", "Marquee running right to left"),
    ("scroll_right", "Scroll Right", "Marquee running left to right"),
    ("roll_up", "Credits Roll", "Text rolls upward, end credits style"),
    ("typewriter", "Typewriter", "Reveal one character at a time"),
    ("wave", "Wave", "Characters bob on a sine wave"),
    ("blur_in", "Focus In", "Rack focus from blurred to sharp"),
)

MOTION_KEYS = tuple(key for key, _, _ in MOTION_EFFECTS)
TEXT_KEYS = tuple(key for key, _, _ in TEXT_EFFECTS)
MOTION_LABELS = {key: name for key, name, _ in MOTION_EFFECTS}
TEXT_LABELS = {key: name for key, name, _ in TEXT_EFFECTS}

# dx/dy: tỉ lệ so với chiều rộng/cao khung; rotation: độ; scale: hệ số;
# opacity: 0..1. dx/dy là fraction để preview rect và canvas export cùng dùng.
MotionState = namedtuple("MotionState", ["dx", "dy", "rotation", "scale", "opacity"])
# reveal: phần trăm ký tự được hiển thị (typewriter); wave_amp theo đơn vị cỡ chữ;
# blur: bán kính blur theo đơn vị cỡ chữ (nhân với px của font khi vẽ).
TextState = namedtuple(
    "TextState", ["dx", "dy", "scale", "opacity", "reveal", "wave_amp", "wave_phase", "blur"]
)

DESIGN_H = 360.0
IDENTITY = MotionState(0.0, 0.0, 0.0, 1.0, 1.0)
TEXT_IDENTITY = TextState(0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)


def label(effects, key):
    for k, name, _ in effects:
        if k == key:
            return name
    return key


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def ease_out(p, k=3.0):
    return 1.0 - (1.0 - p) ** k


def ease_smooth(p):
    return p * p * (3.0 - 2.0 * p)


def ease_back(p, overshoot=1.35):
    c = p - 1.0
    return 1.0 + (overshoot + 1.0) * c ** 3 + overshoot * c ** 2


def progress(local_time, duration):
    """Nhịp tiến độ của clip; duration<=0 (ảnh đứng yên) thì coi như ở đầu."""
    if not duration or duration <= 0:
        return 0.0
    return clamp(float(local_time) / float(duration))


def strength(intensity):
    """EffectData.intensity (0..1) -> thang 1..10 mà các công thức đã tinh chỉnh."""
    return int(clamp(float(intensity) * 9.0 + 1.0, 1.0, 10.0))


def entry_window(i):
    """Phần đầu/cuối clip mà hiệu ứng ra/vào được phép dùng."""
    return clamp(0.45 - 0.03 * i, 0.12, 0.45)


def lead_in(p, i):
    return clamp(p / entry_window(i))


def lead_out(p, i):
    frac = entry_window(i)
    return clamp((p - (1.0 - frac)) / frac)


# --- chuyển động clip ---------------------------------------------------------

def motion_state(key, p, intensity=1.0):
    """Trạng thái biến hình của clip tại nhịp `p`. Không nhận diện được khoá
    thì trả về IDENTITY để caller cũ (shake/float/glitch) không đổi hành vi."""
    handler = _MOTION.get(key or "none")
    if handler is None:
        return IDENTITY
    i = strength(intensity)
    return handler(clamp(p), i)


def _m_none(p, i):
    return IDENTITY


def _m_zoom_in(p, i):
    return MotionState(0.0, 0.0, 0.0, 1.0 + 0.02 * i * ease_smooth(p), 1.0)


def _m_zoom_out(p, i):
    return MotionState(0.0, 0.0, 0.0, 1.0 + 0.02 * i * (1.0 - ease_smooth(p)), 1.0)


def _m_slide(p, i, dx_sign, dy_sign):
    travel = 1.0 - ease_out(lead_in(p, i))
    return MotionState(dx_sign * travel, dy_sign * travel, 0.0, 1.0, 1.0)


def _m_fade_in(p, i):
    return MotionState(0.0, 0.0, 0.0, 1.0, ease_out(lead_in(p, i)))


def _m_fade_out(p, i):
    return MotionState(0.0, 0.0, 0.0, 1.0, 1.0 - ease_smooth(lead_out(p, i)))


def _m_pulse(p, i):
    cycles = 1 + i // 2
    s = 1.0 + 0.006 * i * (0.5 - 0.5 * math.cos(2 * math.pi * cycles * p))
    return MotionState(0.0, 0.0, 0.0, s, 1.0)


def _m_spin(p, i):
    shaped = p + (ease_smooth(p) - p) * ((i - 1) / 9.0)
    return MotionState(0.0, 0.0, 360.0 * shaped, 1.0, 1.0)


def _m_bounce(p, i):
    cycles = 1 + i // 2
    dy = -0.02 * i * abs(math.sin(math.pi * cycles * p)) * (1.0 - 0.6 * p)
    return MotionState(0.0, dy, 0.0, 1.0, 1.0)


_MOTION = {
    "none": _m_none,
    "zoom_in": _m_zoom_in,
    "zoom_out": _m_zoom_out,
    "slide_left": lambda p, i: _m_slide(p, i, 1.0, 0.0),
    "slide_right": lambda p, i: _m_slide(p, i, -1.0, 0.0),
    "slide_up": lambda p, i: _m_slide(p, i, 0.0, 1.0),
    "slide_down": lambda p, i: _m_slide(p, i, 0.0, -1.0),
    "fade_in": _m_fade_in,
    "fade_out": _m_fade_out,
    "pulse": _m_pulse,
    "spin": _m_spin,
    "bounce": _m_bounce,
}


# --- chuyển động chữ ----------------------------------------------------------

def text_state(key, p, intensity=1.0):
    handler = _TEXT.get(key or "none")
    if handler is None:
        return TEXT_IDENTITY
    i = strength(intensity)
    return handler(clamp(p), i)


def _t_none(p, i):
    return TEXT_IDENTITY


def _t_fade_in(p, i):
    return TEXT_IDENTITY._replace(opacity=ease_out(lead_in(p, i)))


def _t_fade_out(p, i):
    return TEXT_IDENTITY._replace(opacity=1.0 - ease_smooth(lead_out(p, i)))


def _t_pop_in(p, i):
    e = ease_back(lead_in(p, i))
    return TEXT_IDENTITY._replace(
        scale=0.55 + 0.45 * e,
        opacity=ease_out(clamp(lead_in(p, i) * 2.5)),
    )


def _t_blur_in(p, i):
    radius = max(0.0, (1.0 - ease_out(lead_in(p, i))) * 0.18)
    return TEXT_IDENTITY._replace(blur=radius)


def _t_slide_in(effect, p, i):
    """dx/dy theo hợp đồng: ±1 = chữ nằm trọn ngoài mép khung ở trục đó."""
    travel = 1.0 - ease_out(lead_in(p, i))
    if effect == "slide_in_left":
        return TEXT_IDENTITY._replace(dx=-travel)
    if effect == "slide_in_right":
        return TEXT_IDENTITY._replace(dx=travel)
    if effect == "slide_in_up":
        return TEXT_IDENTITY._replace(dy=travel)
    return TEXT_IDENTITY._replace(dy=-travel)


def _t_scroll_left(p, i):
    loops = 1 + (i - 1) // 4
    span = clamp(p * loops) if loops == 1 else (p * loops) % 1.0
    # dx tính từ tâm: -1 = nằm ngoài mép trái, +1 = ngoài mép phải.
    return TEXT_IDENTITY._replace(dx=(1.0 - 2.0 * span))


def _t_scroll_right(p, i):
    loops = 1 + (i - 1) // 4
    span = clamp(p * loops) if loops == 1 else (p * loops) % 1.0
    return TEXT_IDENTITY._replace(dx=(2.0 * span - 1.0))


def _t_roll_up(p, i):
    # Từ dưới lên trên trọn khung hình, không phải dừng ở giữa.
    return TEXT_IDENTITY._replace(dy=1.0 - 2.0 * clamp(p))


def _t_typewriter(p, i):
    return TEXT_IDENTITY._replace(reveal=lead_in(p, i))


def _t_wave(p, i):
    cycles = 1 + i // 2
    return TEXT_IDENTITY._replace(wave_amp=0.10 + 0.03 * i,
                                  wave_phase=2 * math.pi * cycles * p)


_TEXT = {
    "none": _t_none,
    "fade_in": _t_fade_in,
    "fade_out": _t_fade_out,
    "pop_in": _t_pop_in,
    "blur_in": _t_blur_in,
    "slide_in_left": lambda p, i: _t_slide_in("slide_in_left", p, i),
    "slide_in_right": lambda p, i: _t_slide_in("slide_in_right", p, i),
    "slide_in_up": lambda p, i: _t_slide_in("slide_in_up", p, i),
    "slide_in_down": lambda p, i: _t_slide_in("slide_in_down", p, i),
    "scroll_left": _t_scroll_left,
    "scroll_right": _t_scroll_right,
    "roll_up": _t_roll_up,
    "typewriter": _t_typewriter,
    "wave": _t_wave,
}
