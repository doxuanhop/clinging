"""Kế hoạch âm thanh của exporter: gom clip, ghép ``filter_complex``, render wav.

Tách khỏi ``RenderWorker`` để probe chạy ĐÚNG chuỗi filter mà app xuất ra. Nếu
dựng một bản sao riêng cho test thì test chỉ chứng minh bản sao đúng, chứ không
chứng minh file video mà người dùng nhận.
"""

from __future__ import annotations

import os
import subprocess

from core import external_tools

SAMPLE_RATE = 48000
MIN_CLIP_DURATION = 0.1

# hsin = nửa hình sin (0.5 - 0.5*cos(pi*x)); lệch <=1.5% biên độ so với
# smoothstep x*x*(3-2*x) mà preview dùng, nên tiếng export nghe giống ô nghe thử.
FADE_CURVE = "hsin"


def has_audio_stream(source_path: str, cache: dict | None = None) -> bool:
    """Probe một lần để video im lặng không tạo ``[i:a]`` hỏng."""
    if cache is not None and source_path in cache:
        return cache[source_path]
    ffprobe = external_tools.find("ffprobe")
    present = False
    if ffprobe:
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_type",
                 "-of", "default=nw=1:nk=1", source_path],
                capture_output=True, timeout=15,
            )
            present = probe.returncode == 0 and bool(probe.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            present = False
    if cache is not None:
        cache[source_path] = present
    return present


def collect_audio_clips(model, cache: dict | None = None) -> list:
    """Clip có tiếng thật, theo đúng thứ tự mà exporter đánh số ``[i:a]``.

    Clip tắt tiếng bị loại ngay đây chứ không chờ ``volume=0``: một luồng im
    lặng vẫn được giải mã, vẫn chiếm một ``[i:a]`` và vẫn làm lệch thứ tự mà
    các hàm khác đang đánh số.
    """
    clips = []
    for track in model.tracks:
        if track.is_muted:
            continue
        for clip in track.clips:
            if getattr(clip, "audio_muted", False):
                continue
            if (clip.media_type in ("audio", "video") and
                    os.path.exists(clip.source_path) and
                    has_audio_stream(clip.source_path, cache)):
                clips.append(clip)
    return clips


def fade_segment(fades) -> str:
    """Chuỗi ``afade`` đặt TRƯỚC ``adelay`` vì toạ độ ramp tính theo dòng chảy
    của chính clip, còn ``adelay`` mới là thứ đẩy nó xuống đúng chỗ trên timeline.
    """
    parts = []
    for kind, start, dur in fades:
        if dur <= 0.0:
            continue
        parts.append(f"afade=t={kind}:st={start:.6f}:d={dur:.6f}"
                     f":curve={FADE_CURVE}")
    return (",".join(parts) + ",") if parts else ""


def input_args(clips) -> list:
    args = []
    for clip in clips:
        args.extend([
            "-fflags", "+genpts+discardcorrupt",
            "-err_detect", "ignore_err",
            "-i", clip.source_path,
        ])
    return args


def atempo_chain(speed: float) -> str:
    """Chuỗi ``atempo`` đúng, mỗi bộ lọc chỉ được xử lý 0.5..2.0.

    ffmpeg từ chối atempo nằm ngoài khoảng đó, nên 4x phải thành hai bộ 2.0 nối
    nhau còn 0.25x thành hai bộ 0.5. Trả về "" khi tốc độ gốc để không nhét bộ
    lọc thừa vào filter_complex.
    """
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return ""
    if value <= 0.0:
        return ""
    factors = []
    remaining = value
    while remaining > 2.0 + 1e-9:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        factors.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        factors.append(remaining)
    if not factors or (len(factors) == 1 and abs(factors[0] - 1.0) <= 1e-6):
        return ""
    return "".join("atempo=%.6f," % f for f in factors)


def build_filter_complex(model, clips, duration: float) -> str:
    """Decode từng nguồn lên PCM liền mạch rồi trộn thành một luồng duy nhất.

    ``normalize=0`` là cố ý và đã được đo: amix mặc định CHIA biên độ cho số
    input đang hoạt động, còn ``adelay`` thì khiến input bật dữ liệu từ giây 0.
    Kết quả là phần đầu project bị giảm âm lượng rồi nhảy lên đúng lúc clip trước
    kết thúc — cú nhảy rơi trúng cửa sổ cross-fade, tiếng bị "thủng" một cái bụp.
    Cộng thuần (normalize=0) cho ra đúng điều preview đang làm: mỗi clip mang
    gain của riêng nó rồi hai luồng tự cộng trong thẻ.

    Thứ tự trong một luồng: ``atrim`` lấy đúng đoạn nguồn (dài theo tốc độ) ->
    ``atempo`` co/giãn về đúng ``clip.duration`` -> fade và volume của chính clip
    -> ``adelay`` mới đẩy xuống vị trí timeline. Đảo lại thì toạ độ ramp trong
    ``model.transition_fades()`` (tính theo giây của clip trên timeline) sẽ lệch.
    """
    from core.transitions import clip_volume
    parts = []
    for i, clip in enumerate(clips):
        delay_ms = int(clip.start_time * 1000)
        source_start = max(0.0, float(clip.in_point))
        speed = getattr(clip, "speed_factor", 1.0) or 1.0
        clip_duration = max(MIN_CLIP_DURATION, float(clip.duration))
        consumed = max(MIN_CLIP_DURATION, clip_duration * float(speed))
        gain = clip_volume(clip)
        parts.append(
            f"[{i}:a]atrim=start={source_start:.6f}:"
            f"duration={consumed:.6f},asetpts=PTS-STARTPTS,"
            f"{atempo_chain(speed)}"
            f"aresample={SAMPLE_RATE}:async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:"
            f"channel_layouts=stereo,"
            f"{fade_segment(model.transition_fades(clip))}"
            + (f"volume={gain:.6f}," if abs(gain - 1.0) > 1e-6 else "")
            + f"adelay={delay_ms}:all=1[a{i}]"
        )
    if not parts:
        return ""
    mix_inputs = "".join(f"[a{i}]" for i in range(len(clips)))
    parts.append(
        f"{mix_inputs}amix=inputs={len(clips)}:"
        "duration=longest:dropout_transition=0:normalize=0,"
        f"aresample={SAMPLE_RATE}:async=1:first_pts=0,"
        f"atrim=duration={duration:.6f},"
        "asetpts=PTS-STARTPTS[aout]"
    )
    return ";".join(parts)


def render_audio(model, clips, duration: float, out_path: str) -> str:
    """Chạy ffmpeg dựng ``out_path`` (PCM 16-bit/48 kHz stereo). Trả về đường dẫn.

    PCM là cố ý: không encode AAC hỏng sang AAC rồi giải mã lại khi mux.
    """
    filter_complex = build_filter_complex(model, clips, duration)
    if not filter_complex:
        raise RuntimeError("Không có luồng âm thanh nào để trộn")
    cmd = ([external_tools.require("ffmpeg"), "-y", "-loglevel", "error"]
           + input_args(clips) + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "2",
        out_path,
    ])
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if (result.returncode != 0 or not os.path.exists(out_path) or
            os.path.getsize(out_path) <= 44):
        details = result.stderr.decode("utf-8", errors="replace")[-600:]
        raise RuntimeError("Không thể chuẩn hóa luồng âm thanh. " + details)
    return out_path
