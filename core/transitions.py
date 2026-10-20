"""
core/transitions.py
Toán chuyển tiếp DÙNG CHUNG cho Preview (CanvasClipItem) và Export (FrameComposer).

Lý do tồn tại: preview và export là hai bộ dựng hình khác nhau. Nếu công thức
fade/wipe/slide viết riêng ở từng nơi thì "xem một kiểu, xuất một kiểu" sẽ quay
lại ngay. Mọi con số của chuyển tiếp vì thế chỉ được tính ở đây; hai bộ dựng
hình chỉ việc gọi ``clip_state()`` rồi áp kết quả.

Mô hình dữ liệu (xem ClipModel.transition):
    transition = {"name": "Cross Dissolve", "duration": 0.75}
    - Name là một khoá trong TRANSITIONS.
    - Transition luôn lưu trên clip BÊN PHẢI của một cặp cắt nối tiếp.
    - "junction" = cần clip phía trước; "local" = chỉ cần chính clip đó.

Cửa sổ chuyển tiếp (window) = [B.start_time, A.end_time]. Nhờ Main Storyline
chấp nhận chồng lấn đúng bằng duration, khoảng này luôn > 0 khi chuyển tiếp hợp
lệ, và progress p = (t - start) / (end - start) chạy đều từ 0 -> 1.
"""

from collections import namedtuple

# Progress được clamp [0, 1] rồi làm mượt; fade tuyến tính trông "gắt" hơn so
# với cách hòa sáng của CapCut/Premiere.
MIN_KEEP = 0.1          # mỗi clip phải còn ít nhất chừng này giây đứng riêng
DEFAULT_DURATION = 1.0

KIND_JUNCTION = "junction"
KIND_LOCAL_IN = "local_in"
KIND_LOCAL_OUT = "local_out"

# Đúng sáu cái tên đang có trong ui/effects_panel.py nhóm "Chuyển tiếp".
TRANSITIONS = {
    "Fade In":        ("fade_in", KIND_LOCAL_IN),
    "Fade Out":       ("fade_out", KIND_LOCAL_OUT),
    "Cross Dissolve": ("cross_dissolve", KIND_JUNCTION),
    "Zoom In":        ("zoom_in", KIND_JUNCTION),
    "Slide Left":     ("slide_left", KIND_JUNCTION),
    "Wipe Right":     ("wipe_right", KIND_JUNCTION),
}

# dx, dy: pixel theo hệ canvas (dương = phải/xuống); scale: hệ số phóng;
# wipe: None hoặc (cạnh, feather) theo tỉ lệ 0..1 của bề rộng clip.
TransitionState = namedtuple(
    "TransitionState", ["opacity", "dx", "dy", "scale", "wipe"]
)

NEUTRAL = TransitionState(1.0, 0.0, 0.0, 1.0, None)


# ── Truy cập dữ liệu ────────────────────────────────────────────

def make(name: str, duration: float) -> dict:
    """Gói transition thành dict lưu được; tên lạ trả về {} (nghĩa là không có)."""
    if not name or name not in TRANSITIONS:
        return {}
    return {"name": name, "duration": round(max(0.0, float(duration)), 3)}


def name_of(clip) -> str:
    data = getattr(clip, "transition", None) or {}
    value = data.get("name", "") if isinstance(data, dict) else ""
    return value if value in TRANSITIONS else ""


def duration_of(clip) -> float:
    data = getattr(clip, "transition", None) or {}
    if not isinstance(data, dict):
        return 0.0
    return max(0.0, float(data.get("duration", 0.0) or 0.0))


def kind_of(name: str) -> str:
    return TRANSITIONS[name][1] if name in TRANSITIONS else ""


def is_junction(name: str) -> bool:
    return kind_of(name) == KIND_JUNCTION


def is_local(name: str) -> bool:
    return kind_of(name) in (KIND_LOCAL_IN, KIND_LOCAL_OUT)


# ── Lịch sự với dữ liệu thật ────────────────────────────────────

def max_duration(left, right) -> float:
    """Duration lớn nhất cặp (left, right) chịu nổi mà không nuốt clip nào."""
    if left is None or right is None:
        return 0.0
    return max(0.0, min(float(left.duration), float(right.duration)) - MIN_KEEP)


def clamp_duration(requested: float, left, right) -> float:
    room = max_duration(left, right)
    if room <= 0.0:
        return 0.0
    return min(max(float(requested), 0.0), room)


def local_room(clip) -> float:
    """Local fade trải trên tối đa toàn bộ clip; chừa MIN_KEEP để còn thấy hình."""
    if clip is None:
        return 0.0
    return max(0.0, float(clip.duration) - MIN_KEEP)


def clamp_local(requested: float, clip) -> float:
    room = local_room(clip)
    if room <= 0.0:
        return 0.0
    return min(max(float(requested), 0.0), room)


def overlap_for(clip, previous) -> float:
    """Số giây chồng lấn mà chuyển tiếp của ``clip`` cần tại mép trái nó.

    Trả về 0 khi không có transition hoặc transition là kiểu local (không cần
    cặp). Chính Main Storyline dùng hàm này khi compact, nên "adjacency" ở đây
    là do caller đảm bảo (hai clip liền nhau trong sequence), không đo toạ độ
    cũ — toạ độ đang được viết lại chính lúc đó.
    """
    name = name_of(clip)
    if not name or not is_junction(name) or previous is None:
        return 0.0
    return clamp_duration(duration_of(clip), previous, clip)


def window(left, right):
    """(start, end) của cửa sổ chuyển tiếp, hoặc None nếu cặp không hợp lệ."""
    if left is None or right is None:
        return None
    if not is_junction(name_of(right)):
        return None
    start = float(right.start_time)
    end = float(left.end_time)
    if end - start <= 0.0001:
        return None
    return start, end


def progress_in_window(t: float, start: float, end: float) -> float:
    span = end - start
    if span <= 0.0:
        return 1.0
    return min(1.0, max(0.0, (float(t) - start) / span))


def _smooth(x: float) -> float:
    return x * x * (3.0 - 2.0 * x)


def _ratio(value: float, span: float) -> float:
    if span <= 0.0:
        return 1.0
    return min(1.0, max(0.0, float(value) / span))


# ── Công thức vẽ từng kiểu ──────────────────────────────────────

def incoming_state(name: str, p: float, canvas_w: float, canvas_h: float):
    """Trạng thái clip BÊN VÀO (clip mang transition) tại tiến độ p."""
    g = _smooth(min(1.0, max(0.0, p)))
    key = TRANSITIONS[name][0]
    if key == "cross_dissolve":
        return TransitionState(g, 0.0, 0.0, 1.0, None)
    if key == "zoom_in":
        return TransitionState(g, 0.0, 0.0, 0.55 + 0.45 * g, None)
    if key == "slide_left":
        return TransitionState(1.0, canvas_w * (1.0 - g), 0.0, 1.0, None)
    if key == "wipe_right":
        # feather 6% bề rộng: mép quét mềm nhưng vẫn đọc rõ là wipe.
        return TransitionState(1.0, 0.0, 0.0, 1.0, (g, 0.06))
    return NEUTRAL


def outgoing_state(name: str, p: float, canvas_w: float, canvas_h: float):
    """Trạng thái clip BÊN RA (clip phía trước) tại cùng tiến độ p."""
    g = _smooth(min(1.0, max(0.0, p)))
    key = TRANSITIONS[name][0]
    if key == "slide_left":
        return TransitionState(1.0, -canvas_w * g, 0.0, 1.0, None)
    # Dissolve/zoom/wipe: clip bên ra đứng yên underneath, clip bên vào tự tiết
    # lộ dần — nên chỉ một phía cần biến đổi.
    return NEUTRAL


def fade_span(clip) -> float:
    """Độ dài ramp của local fade trên chính clip đó.

    Public vì UI timeline cần cùng số này để vẽ dải đánh dấu Fade In/Out — nếu
    mỗi nơi tự tính ``min(duration, clip.duration)`` thì dải trên timeline sẽ
    lệch so với vùng thực sự phai trên canvas.
    """
    return max(0.05, min(duration_of(clip), float(clip.duration)))


def local_state_at(name: str, p: float) -> TransitionState:
    """State của local fade tại tiến độ p của CHÍNH dải phai (0..1).

    Tách riêng khỏi ``local_fade_state`` vì UI xem thử có mỗi một thanh quét, chưa
    có duration đã lưu để suy ra thời gian cục bộ — mà nếu tự viết công thức fade
    ở UI thì lại là "xem một kiểu, xuất một kiểu".
    """
    g = _smooth(min(1.0, max(0.0, p)))
    key = TRANSITIONS[name][0]
    if key == "fade_in":
        return TransitionState(g, 0.0, 0.0, 1.0, None)
    if key == "fade_out":
        return TransitionState(_smooth(1.0 - min(1.0, max(0.0, p))), 0.0, 0.0, 1.0, None)
    return NEUTRAL


def local_fade_state(name: str, clip, local_time: float) -> TransitionState:
    """Fade In/Out ramp trên ``duration`` giây đầu hoặc cuối của chính clip."""
    span = fade_span(clip)
    key = TRANSITIONS[name][0]
    if key == "fade_in":
        return local_state_at(name, _ratio(local_time, span))
    if key == "fade_out":
        remaining = float(clip.duration) - float(local_time)
        return local_state_at(name, 1.0 - _ratio(remaining, span))
    return NEUTRAL


def combine(a: TransitionState, b: TransitionState) -> TransitionState:
    """Gộp hai trạng thái: nhân opacity/phóng, cộng dịch chuyển."""
    wipe = b.wipe if b.wipe is not None else a.wipe
    return TransitionState(a.opacity * b.opacity, a.dx + b.dx, a.dy + b.dy,
                           a.scale * b.scale, wipe)


# ── Điểm vào duy nhất cho hai bộ dựng hình ──────────────────────

def clip_state(clip, previous, following, t: float,
               canvas_w: float, canvas_h: float) -> TransitionState:
    """Trạng thái vẽ của ``clip`` tại thời điểm tuyệt đối t trên timeline.

    ``previous``/``following`` là clip kề trái/kề phải trên cùng track (None nếu
    không có). Hàm chỉ đọc thuộc tính tường minh nên chạy được trong thread xuất
    hình, không cần model hay Qt.
    """
    if clip is None:
        return NEUTRAL

    own = name_of(clip)
    if own and is_junction(own):
        pair = window(previous, clip)
        if pair is None:
            return NEUTRAL
        p = progress_in_window(t, pair[0], pair[1])
        if p >= 1.0:
            return NEUTRAL
        return incoming_state(own, p, canvas_w, canvas_h)

    if own:
        return local_fade_state(own, clip, float(t) - float(clip.start_time))

    following_name = name_of(following) if following is not None else ""
    if following_name and is_junction(following_name):
        pair = window(clip, following)
        if pair is not None:
            p = progress_in_window(t, pair[0], pair[1])
            if p < 1.0:
                return outgoing_state(following_name, p, canvas_w, canvas_h)
    return NEUTRAL


def clip_audio_gain(clip, previous, following, t: float) -> float:
    """Hệ số âm lượng 0..1(+) của ``clip`` tại thời điểm t (dùng cho preview).

    Bao gồm CẢ volume per-clip lẫn ramp fade_in/fade_out của chính clip, vì
    preview chỉ có một cái loa: nếu ô nghe thử chỉ nhân chuyển tiếp thì người
    dùng kéo thanh Âm lượng xuống 20% mà tiếng vẫn 100%, rồi mở file export ra
    mới thấy khác.
    """
    if clip is None:
        return 1.0
    return transition_only_gain(clip, previous, following, t) * local_gain(clip, t)


def transition_only_gain(clip, previous, following, t: float) -> float:
    """Chỉ phần chuyển tiếp: junction và local fade của transition.
    """
    if clip is None:
        return 1.0
    own = name_of(clip)
    if own and is_junction(own):
        pair = window(previous, clip)
        if pair is None:
            return 1.0
        return _smooth(progress_in_window(t, pair[0], pair[1]))
    if own:
        key = TRANSITIONS[own][0]
        span = fade_span(clip)
        local_time = float(t) - float(clip.start_time)
        if key == "fade_in":
            return _smooth(_ratio(local_time, span))
        if key == "fade_out":
            return _smooth(_ratio(float(clip.duration) - local_time, span))
        return 1.0
    following_name = name_of(following) if following is not None else ""
    if following_name and is_junction(following_name):
        pair = window(clip, following)
        if pair is not None:
            return 1.0 - _smooth(progress_in_window(t, pair[0], pair[1]))
    return 1.0


# ── Audio của riêng clip (không phụ thuộc chuyển tiếp) ──────────

def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def clip_volume(clip, ignore_mute: bool = False) -> float:
    """Hệ số âm lượng per-clip, 0.0 (im lặng) tới 2.0 (+6 dB).

    ``None`` mới là "chưa chỉnh"; 0.0 phải đi qua nguyên value, vì clip tắt
    tiếng là một trạng thái người dùng chọn, không phải thiếu dữ liệu.

    ``audio_muted`` cũng về 0.0 nhưng KHÔNG ghi đè lên ``volume``: đây là chỗ
    duy nhất mà preview (qua ``local_gain``) và exporter (qua
    ``audio_mix.build_filter_complex``) cùng đọc, nên một cú tắt tiếng đổi cả ô
    nghe thử lẫn file xuất ra, còn con số âm lượng thì giữ nguyên để bật lại.

    ``ignore_mute`` dành riêng cho cây sóng: tắt tiếng phải đổi MÀU của sóng
    chứ không được xóa hình dạng của nó.
    """
    if clip is None:
        return 1.0
    if not ignore_mute and getattr(clip, "audio_muted", False):
        return 0.0
    raw = getattr(clip, "volume", None)
    if raw is None:
        return 1.0
    return min(2.0, max(0.0, _num(raw, 1.0)))


def clip_fade_spans(clip):
    """(fade_in, fade_out) giây, đã kẹp để hai ramp không chồng lên nhau.

    Hai ramp cộng thêm với chuyển tiếp là cố ý: ffmpeg nối tiếp afade nên ở
    vùng trùng nhau biên độ NHÂN hai đường cong, tức nhỏ đi chứ không phình.
    """
    if clip is None:
        return 0.0, 0.0
    duration = max(0.0, _num(clip.duration))
    fade_in = min(max(0.0, _num(getattr(clip, "fade_in", 0.0))), duration)
    fade_out = min(max(0.0, _num(getattr(clip, "fade_out", 0.0))), duration)
    total = fade_in + fade_out
    if total > duration and total > 0.0:
        scale = duration / total
        fade_in *= scale
        fade_out *= scale
    return round(fade_in, 3), round(fade_out, 3)


def local_gain(clip, t: float, ignore_mute: bool = False) -> float:
    """Volume nhân với ramp fade_in/fade_out của riêng clip tại thời điểm t."""
    if clip is None:
        return 1.0
    gain = clip_volume(clip, ignore_mute=ignore_mute)
    fade_in, fade_out = clip_fade_spans(clip)
    local_time = _num(t) - _num(clip.start_time)
    if fade_in > 0.0:
        gain *= _smooth(_ratio(local_time, fade_in))
    if fade_out > 0.0:
        gain *= _smooth(_ratio(_num(clip.duration) - local_time, fade_out))
    return gain



def audio_fades(clip, previous, following):
    """Danh sách ``afade`` cho exporter: [(("in"|"out"), st_sec, dur_sec), ...].

    Toạ độ tính theo DÒNG CHẢY CỦA CHÍNH CLIP (0 = đầu đoạn audio sau khi
    exporter ``atrim`` theo in_point và ``asetpts=PTS-STARTPTS``), nên exporter
    chỉ việc ghép chuỗi filter, không phải quy chiếu lại nguồn.

    Một clip có thể mang HAI fade: nó nhỏ dần vì clip kế tiếp nối chồng lên nó,
    và đồng thời to dần vì chính nó mang chuyển tiếp. Preview chỉ cần
    ``clip_audio_gain`` tại từng giây, nhưng ffmpeg cần đúng hai ramp này thì
    tiếng mới hòa chứ không đổi tiếng cái "cạch" tại mép nối.
    """
    fades = []
    name = name_of(clip)
    if name and is_junction(name):
        pair = window(previous, clip)
        if pair is not None:
            offset = min(max(0.0, pair[0] - float(clip.start_time)),
                         float(clip.duration))
            fades.append(("in", round(offset, 3), round(pair[1] - pair[0], 3)))
    elif name == "Fade In":
        fades.append(("in", 0.0, round(fade_span(clip), 3)))
    elif name == "Fade Out":
        span = fade_span(clip)
        fades.append(("out",
                      round(max(0.0, float(clip.duration) - span), 3),
                      round(span, 3)))

    # Chiều ra: clip sau mang junction thì clip này phải nhường tiếng trong
    # đúng cửa sổ đó — nếu chỉ fade một bên thì vùng chồng lấn bị hụt âm,
    # người dùng nghe như ai đó vặn nhỏ loa rồi trả lại.
    next_name = name_of(following) if following is not None else ""
    if next_name and is_junction(next_name):
        pair = window(clip, following)
        if pair is not None:
            span = pair[1] - pair[0]
            fades.append(("out",
                          round(max(0.0, float(clip.duration) - span), 3),
                          round(span, 3)))

    # Ramp do người dùng chỉnh ở thẻ Audio. Toạ độ vẫn tính theo dòng chảy của
    # clip SAU khi atempo đổi độ dài, nên exporter phải đặt chuỗi afade này sau
    # bộ lọc tốc độ — xem core/audio_mix.py.
    explicit_in, explicit_out = clip_fade_spans(clip)
    if explicit_in > 0.0:
        fades.append(("in", 0.0, explicit_in))
    if explicit_out > 0.0:
        fades.append(("out",
                      round(max(0.0, float(clip.duration) - explicit_out), 3),
                      explicit_out))
    return fades
