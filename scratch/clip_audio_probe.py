"""scratch/clip_audio_probe.py

Bằng chứng ĐO ĐƯỢC cho audio per-clip (âm lượng, tốc độ, fade vào/ra của TỪNG
clip), mute của preview và cây sóng thật. Probe không tự dựng chuỗi filter: nó nạp
model bằng đúng code sản xuất (core/timeline_model.py, core/commands.py,
ui/properties_panel.py, ui/main_window.py) rồi gọi core/audio_mix.py — thứ mà
exporter dùng — và giải mã file wav đầu ra để ĐO biên độ từng tiếng bằng DFT đúng
bin (cửa sổ 100 ms, hop 25 ms). Mọi tỷ số chuẩn hoá theo biên độ đo từ chính file
nguồn, nên "1.0" nghĩa là export giữ đúng mức nguồn chứ không phải số tự thêu.

Counterfactual là phần quan trọng nhất, vì ba lý do:
  * mức 0.5 phẳng khác ramp đi qua 0.5 ở một thời điểm — đo thêm ĐỘ PHẲNG thì hai
    thứ không thể nhầm nhau;
  * tốc độ được chứng minh bằng một nguồn CÓ CỬA SỔ (im lặng 0-2 s, tiếng 2-4 s):
    clip 2 giây ở 1x không nghe thấy gì, ở 2x phải có tiếng bắt đầu đúng giữa
    clip. Một bộ atempo bị bỏ quên không thể tạo ra đường onset đó; video dùng
    cùng ý tưởng: mỗi giây một màu, đổi tốc độ là đổi MÀU ĐO ĐƯỢC;
  * cây sóng phải NHÚC NHÍCH theo cửa sổ nguồn, nên cùng một file được đo ở hai
    cửa sổ và một file im lặng phải trả về danh sách RỖNG;
  * tắt tiếng một clip là việc của RIÊNG clip đó: project hai hàng được đo ở hai
    nửa thời gian, nên một bản "tắt tiếng" nào lỡ im lặng cả project, hoặc chỉ
    ghi volume=0 (mất con số cũ), đều lộ ra ngay trên phổ của file WAV.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/clip_audio_probe.py
"""

import json
import os
import subprocess
import sys
import wave
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scratch"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import audio_mix, transitions
from core.media_extractor import extract_audio_waveform, get_media_duration
from core.timeline_model import TimelineModel, TrackType
import core.project_storage as project_storage

OUT = os.path.join(ROOT, "scratch")
TONE_WAV = os.path.join(OUT, "clip_audio_tone.wav")
GATED_WAV = os.path.join(OUT, "clip_audio_gated.wav")
SEG_MP4 = os.path.join(OUT, "clip_audio_segments.mp4")
SILENT_MP4 = os.path.join(OUT, "clip_audio_silent.mp4")
CLINQ = os.path.join(OUT, "clip_audio_project.clinq")
PANEL_PNG = os.path.join(OUT, "clip_audio_audio_card.png")
EVIDENCE = os.path.join(OUT, "clip_audio_evidence.png")

FS = 48000
TONE = 440.0
SOURCE_LEVEL = 0.4
WIN = 4800          # 100 ms -> 440 Hz rơi đúng bin số 44
HOP = 1200          # 25 ms

# Mỗi giây một màu đối lập, nung thẳng vào file probe.
SEG_COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]

FAILS = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def near(name, got, want, tol):
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        FAILS.append("%s: got %r want %r tol %r" % (name, got, want, tol))
    print("%s  %s  (got=%.4f want=%.4f tol=%.3f)"
          % ("PASS" if ok else "FAIL", name, float(got), float(want), tol))
    return ok


def in_range(name, got, low, high):
    ok = low <= float(got) <= high
    if not ok:
        FAILS.append("%s: got %r not in [%r, %r]" % (name, got, low, high))
    print("%s  %s  (got=%.4f want=[%.2f, %.2f])"
          % ("PASS" if ok else "FAIL", name, float(got), low, high))
    return ok


def run(cmd, what):
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-700:]
        raise SystemExit("%s FAILED (rc=%s):\n%s" % (what, proc.returncode, detail))


def ffmpeg(*args):
    return ["ffmpeg", "-y", "-loglevel", "error"] + list(args)


def smooth(p):
    return p * p * (3.0 - 2.0 * p)


def hsin_out(x):
    """afade t=out curve=hsin: 0.5 + 0.5*cos(pi*x)."""
    x = min(1.0, max(0.0, float(x)))
    return 0.5 + 0.5 * np.cos(np.pi * x)


def hsin_in(x):
    return 1.0 - hsin_out(x)


# ── Fixtures ───────────────────────────────────────────────────

def build_fixtures():
    # Stereo ngay từ nguồn: upmix mono->stereo của ffmpeg ăn -3 dB, nên không
    # được dựa vào nó khi chuẩn hoá biên độ.
    tone = "%g*sin(2*PI*%g*t)" % (SOURCE_LEVEL, TONE)
    run(ffmpeg("-f", "lavfi", "-i",
               "aevalsrc=exprs=%s|%s:d=4:s=%d" % (tone, tone, FS),
               "-c:a", "pcm_s16le", "-ar", str(FS), TONE_WAV), "fixture tone")
    # Nguồn CÓ CỬA SỔ: im lặng 0-2 s, có tiếng 2-4 s. Đây là thứ cho phép phân
    # biệt "atempo chạy thật" với "atempo bị bỏ qua". Viết bằng numpy vì mọi hàm
    # có tham số của aevalsrc (gte/between) đều chứa dấu phẩy, và ffmpeg cắt tuỳ
    # chọn theo dấu phẩy.
    write_gated_wav(GATED_WAV)
    run(ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x240:r=12:d=4",
               "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", SILENT_MP4), "fixture silent")
    write_segment_video(SEG_MP4, seconds=4.0, fps=12.0)


def write_gated_wav(path):
    """4 s: im lặng 0-2 s, tiếng 440 Hz 2-4 s, cắt đúng ranh giới mẫu.

    Cửa sổ 100 ms của phép đo rơi trọn vẹn vào một bên, nên onset đo được là
    2.000 s chứ không phải 2.05 s hay 1.95 s.
    """
    total = int(4.0 * FS)
    gate = int(2.0 * FS)
    index = np.arange(total, dtype=np.float64)
    tone = SOURCE_LEVEL * np.sin(2.0 * np.pi * TONE * index / FS)
    tone[:gate] = 0.0
    stereo = np.stack([tone, tone], axis=1)
    pcm = np.clip(stereo, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(FS)
        handle.writeframes(pcm.tobytes())


def write_segment_video(path, seconds, fps):
    import cv2
    W, H = 320, 240
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for index in range(int(seconds * fps)):
        rgb = SEG_COLORS[min(int(index / fps), len(SEG_COLORS) - 1)]
        frame = np.zeros((H, W, 3), np.uint8)
        frame[:, :] = (rgb[2], rgb[1], rgb[0])
        writer.write(frame)
    writer.release()
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        raise SystemExit("cannot write probe media: " + path)


# ── Measurement ────────────────────────────────────────────────

def read_stereo(path):
    with wave.open(path, "rb") as handle:
        channels, rate, width = (handle.getnchannels(), handle.getframerate(),
                                 handle.getsampwidth())
        raw = handle.readframes(handle.getnframes())
    if (channels, rate, width) != (2, FS, 2):
        raise SystemExit("%s is not 48k/16bit/stereo: %r"
                         % (os.path.basename(path), (channels, rate, width)))
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return samples.reshape(-1, channels), len(raw) / float(FS * channels * width)


def _windows(mono):
    count = max(0, (len(mono) - WIN) // HOP + 1)
    times = np.arange(count) * HOP / FS + (WIN / 2.0) / FS
    frames = np.lib.stride_tricks.sliding_window_view(mono, WIN)[
        np.arange(count) * HOP]
    return times, frames


def envelope(path, freq=TONE):
    """(times, amplitude): DFT đúng bin nên các tiếng đo độc lập, không rò rỉ."""
    stereo, _ = read_stereo(path)
    bin_index = int(round(freq * WIN / FS))
    if abs(bin_index * FS / WIN - freq) > 1e-9:
        raise SystemExit("tone %g does not sit on a DFT bin" % freq)
    reference = np.exp(-2j * np.pi * bin_index * np.arange(WIN) / WIN)
    times, frames = _windows(stereo.mean(axis=1))
    return times, 2.0 * np.abs(frames @ reference) / WIN


def value_at(times, values, t):
    return float(values[int(np.argmin(np.abs(times - t)))])


def solo_level(times, values, span):
    keep = (times >= span[0]) & (times <= span[1])
    inside = values[keep]
    return float(np.median(inside)) if inside.size else 0.0


def slice_values(times, values, low, high):
    keep = (times >= low) & (times <= high)
    return values[keep]


def spread(times, values, low, high):
    """(min, max) trên khoảng — dùng để chứng minh một đường BẰNG PHẲNG."""
    selected = slice_values(times, values, low, high)
    if selected.size == 0:
        return 0.0, 0.0
    return float(selected.min()), float(selected.max())


def max_abs_diff(times_a, a, times_b, b):
    grid = np.arange(min(times_a[0], times_b[0]),
                     min(times_a[-1], times_b[-1]) + 1e-9, HOP / FS)
    return float(np.max(np.abs(np.interp(grid, times_a, a)
                               - np.interp(grid, times_b, b))))


def mix(model, out_path):
    audio_mix.render_audio(model, audio_mix.collect_audio_clips(model, {}),
                           model.duration, out_path)
    return out_path


def tone_model(path=TONE_WAV, kind="audio", duration=None):
    """Clip đơn trên đúng loại track mà app sẽ tạo cho media type đó."""
    model = TimelineModel()
    track = model.add_track(TrackType.AUDIO if kind == "audio"
                           else TrackType.VIDEO)
    full = get_media_duration(path, kind)
    clip = model.add_clip(track.track_id, path, kind, 0.0,
                          duration or full or 4.0, os.path.basename(path))
    return model, track, clip


# ── 1. Model là nguồn sự thật ──────────────────────────────────

def test_model():
    print("\n== 1. model clamps and geometry ==")
    model, track, clip = tone_model()
    check("drop uses the real source duration", round(clip.duration, 3), 4.0)
    check("a fresh clip starts neutral",
          [clip.volume, clip.speed, clip.fade_in, clip.fade_out,
           clip.audio_muted],
          [1.0, 1.0, 0.0, 0.0, False])

    applied = model.set_clip_audio(clip.clip_id, volume=5.0)
    check("volume above the ceiling is clamped", applied["volume"], 2.0)
    applied = model.set_clip_audio(clip.clip_id, volume=-3.0)
    check("volume below the floor is clamped", applied["volume"], 0.0)
    # 0.0 là một TRẠNG THÁI người dùng chọn, không phải thiếu dữ liệu.
    check("mute-by-volume is not read as unset", clip.volume_level, 0.0)
    near("gain of a silent clip is silence",
         transitions.local_gain(clip, clip.start_time + 2.0), 0.0, 1e-9)

    model.set_clip_audio(clip.clip_id, volume=1.0)
    applied = model.set_clip_audio(clip.clip_id, fade_in=3.0, fade_out=3.0)
    check("two ramps that overflow are scaled together",
          [applied["fade_in"], applied["fade_out"]], [2.0, 2.0])

    model.set_clip_audio(clip.clip_id, fade_in=0.0, fade_out=0.0)
    applied = model.set_clip_audio(clip.clip_id, speed=10.0)
    check("speed above the ceiling is clamped", applied["speed"], 4.0)
    # 4x trên nguồn 4 s chỉ chứa nổi 1 giây timeline.
    check("raising speed trims to the source that fits",
          round(clip.duration, 3), 1.0)
    check("out_point follows speed", round(clip.out_point, 3), 4.0)

    model.set_clip_audio(clip.clip_id, speed=1.0)
    check("returning to 1x does not re-inflate the clip",
          round(clip.duration, 3), 1.0)
    model.resize_clip(clip.clip_id, 2.0)
    check("trim back to 2 s", round(clip.duration, 3), 2.0)

    # Ánh xạ nguồn <-> timeline phải khớp ngược chiều nhau: cùng một công thức
    # dùng cho preview, export, thumbnail và trim.
    for local in (0.0, 0.7, 2.0):
        near("1x source_at_local(%.1f)" % local, clip.source_at_local(local),
             local, 1e-9)
    model.set_clip_audio(clip.clip_id, speed=2.0)
    check("2x keeps 2 timeline seconds on a 4 s source",
          round(clip.duration, 3), 2.0)
    near("2x consumes 4 source seconds", clip.consumed_source(), 4.0, 1e-9)
    near("source at local 1.0 is 2.0", clip.source_time(1.0), 2.0, 1e-9)
    near("round trip back to timeline", clip.timeline_at_source(2.0), 1.0, 1e-9)
    check("out_point after 2x", round(clip.out_point, 3), 4.0)


# ── 2. Chuỗi filter export ─────────────────────────────────────

def test_graph():
    print("\n== 2. export filter graph ==")
    check("atempo of 1x adds nothing", audio_mix.atempo_chain(1.0), "")
    check("2x is one legal atempo", audio_mix.atempo_chain(2.0),
          "atempo=2.000000,")
    # ffmpeg từ chối atempo ngoài 0.5..2.0, nên 4x và 0.25x PHẢI thành hai bộ.
    check("4x chains two atempo", audio_mix.atempo_chain(4.0),
          "atempo=2.000000,atempo=2.000000,")
    check("0.25x chains two half-speed", audio_mix.atempo_chain(0.25),
          "atempo=0.500000,atempo=0.500000,")
    chain = [float(p.split("=")[1]) for p in audio_mix.atempo_chain(3.0).split(",")
             if p]
    check("3x chain multiplies back to 3", round(np.prod(chain), 6), 3.0)
    check("3x chain stays inside ffmpeg limits",
          all(0.5 - 1e-9 <= factor <= 2.0 + 1e-9 for factor in chain), True)

    model, track, clip = tone_model()
    model.set_clip_audio(clip.clip_id, volume=0.5, fade_in=1.0, fade_out=1.0,
                         speed=2.0)
    graph = audio_mix.build_filter_complex(
        model, audio_mix.collect_audio_clips(model, {}), model.duration)
    check("atrim eats duration x speed", "duration=4.000000" in graph, True)
    check("atempo sits in the chain", "atempo=2.000000," in graph, True)
    check("user fade in is an afade",
          "afade=t=in:st=0.000000:d=1.000000" in graph, True)
    check("user fade out lands at the clip end",
          "afade=t=out:st=1.000000:d=1.000000" in graph, True)
    check("volume is its own filter", "volume=0.500000," in graph, True)
    check("two user ramps -> two afade", graph.count("afade="), 2)

    chain0 = graph.split(";")[0]
    order = [chain0.find(needle) for needle in
             ("atrim=", "atempo=", "afade=", "volume=", "adelay=")]
    check("every filter is present", all(i >= 0 for i in order), True)
    # Thứ tự là logic: ramp và volume tính theo dòng chảy của clip SAU atempo,
    # còn adelay mới là thứ đẩy cả dòng chảy xuống vị trí timeline.
    check("order is atrim -> atempo -> afade -> volume -> adelay",
          order == sorted(order), True)

    quiet, _qtrack, _qclip = tone_model(SILENT_MP4, "video")
    check("a silent source contributes nothing",
          audio_mix.collect_audio_clips(quiet, {}), [])
    check("so there is no graph",
          audio_mix.build_filter_complex(quiet, [], quiet.duration), "")

    muted, mtrack, _mclip = tone_model()
    mtrack.is_muted = True
    check("export skips a muted track", audio_mix.collect_audio_clips(muted, {}),
          [])

    flat, _ftrack, fclip = tone_model()
    flat.set_clip_audio(fclip.clip_id, volume=1.0)
    plain_graph = audio_mix.build_filter_complex(
        flat, audio_mix.collect_audio_clips(flat, {}), flat.duration)
    check("an untouched clip gets no volume filter", "volume=" in plain_graph,
          False)
    check("and no afade", plain_graph.count("afade="), 0)
    check("and no atempo", "atempo=" in plain_graph, False)


# ── 3. Đo âm lượng ─────────────────────────────────────────────

def test_volume(ref):
    print("\n== 3. measured per-clip volume ==")
    curves = {}
    for level in (0.0, 0.2, 0.5, 1.0, 2.0):
        model, track, clip = tone_model()
        model.set_clip_audio(clip.clip_id, volume=level)
        times, values = envelope(mix(model, os.path.join(
            OUT, "clip_audio_volume_%d.wav" % int(level * 100))), TONE)
        normalised = values / ref
        curves[level] = (times, normalised)
        near("volume %d%% exports at %d%% of source" % (level * 100, level * 100),
             solo_level(times, normalised, (0.4, 3.6)), level, 0.02)
        low, high = spread(times, normalised, 0.4, 3.6)
        # Counterfactual: ramp đi qua 0.5 tại một thời điểm trông giống hệt mức
        # 0.5. Một đường PHẲNG 0.5 thì không ramp nào tạo ra được.
        in_range("the %d%% curve is flat, not a ramp" % int(level * 100),
                 high - low, 0.0, 0.03)
    in_range("volume 0% really is silence",
             solo_level(*curves[0.0], (0.4, 3.6)), 0.0, 0.01)
    in_range("volume 200% doubles the source",
             solo_level(*curves[2.0], (0.4, 3.6)), 1.97, 2.03)
    check("200% still fits in the 16-bit container",
          float(np.max(np.abs(read_stereo(os.path.join(
              OUT, "clip_audio_volume_200.wav"))[0]))) < 0.999, True)
    in_range("50% and 20% are measurably different curves",
             max_abs_diff(curves[0.5][0], curves[0.5][1],
                          curves[0.2][0], curves[0.2][1]), 0.15, 1.0)
    return curves


# ── 4. Đo fade của riêng clip ──────────────────────────────────

def test_fades(ref):
    print("\n== 4. measured explicit fade_in / fade_out ==")
    model, track, clip = tone_model()
    check("1 s ramps on a 4 s clip",
          model.set_clip_audio(clip.clip_id, fade_in=1.0, fade_out=1.0, speed=1.0),
          {"volume": 1.0, "fade_in": 1.0, "fade_out": 1.0, "speed": 1.0,
           "audio_muted": False})
    plan = model.transition_fades(clip)
    check("both ramps reach the exporter",
          [(kind, round(st, 3), round(dur, 3)) for kind, st, dur in plan],
          [("in", 0.0, 1.0), ("out", 3.0, 1.0)])

    times, values = envelope(mix(model, os.path.join(OUT, "clip_audio_fades.wav")),
                             TONE)
    curve = values / ref
    for t in (0.15, 0.3, 0.5, 0.7, 0.85):
        near("fade in follows hsin at t=%.2f" % t, value_at(times, curve, t),
             hsin_in(t), 0.06)
    for t in (3.15, 3.3, 3.5, 3.7, 3.85):
        near("fade out follows hsin at t=%.2f" % t, value_at(times, curve, t),
             hsin_out(t - 3.0), 0.06)
    near("middle of the clip stays at source level",
         solo_level(times, curve, (1.4, 2.6)), 1.0, 0.03)
    in_range("fade starts silent", value_at(times, curve, 0.03), 0.0, 0.08)
    in_range("fade ends silent", value_at(times, curve, 3.97), 0.0, 0.08)
    ramp_in = slice_values(times, curve, 0.0, 1.0)
    ramp_out = slice_values(times, curve, 3.0, 4.0)
    check("fade in is monotonic up",
          bool(np.all(ramp_in[:-1] <= ramp_in[1:] + 0.02)), True)
    check("fade out is monotonic down",
          bool(np.all(ramp_out[:-1] >= ramp_out[1:] - 0.02)), True)

    # Counterfactual: cùng nguồn, bỏ hai ramp — nếu đường đo KHÔNG đổi thì phép
    # đo đang nhìn thấy thứ gì khác chứ không phải fade.
    control, _ctr, _cclip = tone_model()
    control_times, control_values = envelope(
        mix(control, os.path.join(OUT, "clip_audio_nofade.wav")), TONE)
    control_curve = control_values / ref
    near("control clip is flat at source level",
         solo_level(control_times, control_curve, (0.4, 3.6)), 1.0, 0.02)
    in_range("removing the ramps changes the measurement a lot",
             max_abs_diff(times, curve, control_times, control_curve), 0.5, 2.0)
    return (times, curve), (control_times, control_curve)


# ── 5. Đo tốc độ: counterfactual có cửa sổ ─────────────────────

def test_speed(ref):
    print("\n== 5. measured speed with an onset inside the source ==")
    # Nguồn im lặng 0-2 s, có tiếng 2-4 s. Clip 2 giây timeline:
    #   1x -> atrim 0..2 -> không nghe thấy gì
    #   2x -> atrim 0..4 + atempo 2 -> onset đúng giữa clip
    results = {}
    for speed, name in ((1.0, "1x"), (2.0, "2x")):
        model, track, clip = tone_model(GATED_WAV)
        model.resize_clip(clip.clip_id, 2.0)
        check("clip is 2 timeline seconds at %s" % name,
              round(clip.duration, 3), 2.0)
        if speed != 1.0:
            applied = model.set_clip_audio(clip.clip_id, speed=speed)
            check("speed %s applied" % name, applied["speed"], speed)
            check("speed %s keeps the timeline duration" % name,
                  round(clip.duration, 3), 2.0)
        graph = audio_mix.build_filter_complex(
            model, audio_mix.collect_audio_clips(model, {}), model.duration)
        check("atrim window at %s" % name,
              "duration=%.6f" % (2.0 * speed) in graph, True)
        check("atempo at %s" % name,
              (("atempo=%.6f," % speed) in graph) if speed != 1.0
              else ("atempo=" not in graph), True)

        path = os.path.join(OUT, "clip_audio_speed_%s.wav" % name)
        _stereo, seconds = read_stereo(mix(model, path))
        near("export length follows the timeline clip at %s" % name,
             round(seconds, 2), 2.0, 0.06)
        times, values = envelope(path, TONE)
        results[name] = (times, values / ref)

    t1, c1 = results["1x"]
    t2, c2 = results["2x"]
    low1, high1 = spread(t1, c1, 0.1, 1.9)
    in_range("1x hears nothing (its window is the silent half)", high1, 0.0, 0.03)
    in_range("2x is still silent at t=0.5", value_at(t2, c2, 0.5), 0.0, 0.06)
    near("2x reaches source level at t=1.6", value_at(t2, c2, 1.6), 1.0, 0.05)
    above = np.where(c2 > 0.5)[0]
    onset = float(t2[above[0]]) if above.size else 99.0
    in_range("2x onset lands at the middle of the clip", onset, 0.94, 1.06)
    in_range("the 1x and 2x runs are genuinely different",
             max_abs_diff(t1, c1, t2, c2), 0.7, 2.0)

    # 0.5x trên cùng nguồn: 2 giây timeline chỉ ăn 1 giây nguồn -> vẫn im lặng.
    model, track, clip = tone_model(GATED_WAV)
    model.resize_clip(clip.clip_id, 2.0)
    model.set_clip_audio(clip.clip_id, speed=0.5)
    check("0.5x on a 4 s source keeps 2 s", round(clip.duration, 3), 2.0)
    near("0.5x consumes 1 source second", clip.consumed_source(), 1.0, 1e-9)
    times, values = envelope(
        mix(model, os.path.join(OUT, "clip_audio_speed_half.wav")), TONE)
    low, high = spread(times, values / ref, 0.1, 1.9)
    in_range("0.5x hears the silent first second", high, 0.0, 0.03)
    return results


# ── 6. Tốc độ phải đổi cả HÌNH ─────────────────────────────────

def test_video_speed():
    print("\n== 6. speed moves the picture, not only the sound ==")
    from PySide6.QtGui import QImage
    from core.frame_composer import FrameComposer

    def to_array(image: QImage) -> np.ndarray:
        img = image.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        return np.frombuffer(raw, np.uint8).reshape(
            (img.height(), img.width(), 4)).astype(np.int16)

    def color_at(model, t):
        composer = FrameComposer(model, 320, 240)
        try:
            arr = to_array(composer.render_frame(t))
        finally:
            composer.close()
        return arr[:, :, :3].mean(axis=(0, 1))

    def name_for(rgb):
        best, best_gap = None, 1e18
        for index, want in enumerate(SEG_COLORS):
            gap = sum((float(rgb[k]) - want[k]) ** 2 for k in range(3))
            if gap < best_gap:
                best, best_gap = index, gap
        return best

    plain, _pt, pclip = tone_model(SEG_MP4, "video", duration=4.0)
    check("source_duration is the decoded file length",
          round(pclip.source_duration, 2), 4.0)
    for local, want in ((0.4, 0), (1.4, 1), (2.4, 2)):
        check("1x at t=%.1f shows source second %d" % (local, want),
              name_for(color_at(plain, local)), want)

    fast, _ft, fclip = tone_model(SEG_MP4, "video", duration=4.0)
    fast.set_clip_audio(fclip.clip_id, speed=2.0)
    # 4s nguồn ở 2x chỉ chứa nổi 2s timeline — chính là clamp của model.
    check("2x on a 4 s source becomes 2 timeline seconds",
          round(fclip.duration, 3), 2.0)
    for local, want in ((0.2, 0), (0.7, 1), (1.2, 2), (1.7, 3)):
        check("2x at local %.1f shows source second %d" % (local, want),
              name_for(color_at(fast, local)), want)

    gap = float(np.abs(color_at(plain, 0.7) - color_at(fast, 0.7)).mean())
    in_range("1x and 2x frames differ at the same timeline second", gap,
             40.0, 255.0)


# ── 7. Lưu / nạp ───────────────────────────────────────────────

def test_persistence():
    print("\n== 7. persistence ==")
    model, track, clip = tone_model()
    model.set_clip_audio(clip.clip_id, volume=0.35, speed=1.5,
                         fade_in=0.4, fade_out=0.8, audio_muted=True)
    check("1.5x on a 4 s source shortens the clip", round(clip.duration, 3), 2.667)
    if os.path.exists(CLINQ):
        os.remove(CLINQ)
    project_storage.save_project_to_file(
        model, CLINQ, {"project_name": "audio-probe"})
    project = project_storage.load_project_from_file(CLINQ)
    check("project file written", bool(project), True)

    stored = [c for t in project["timeline"]["tracks"] for c in t["clips"]][0]
    check("five audio keys are on disk",
          sorted(k for k in ("volume", "speed", "fade_in", "fade_out",
                             "audio_muted") if k in stored),
          ["audio_muted", "fade_in", "fade_out", "speed", "volume"])
    check("and the mute is stored as a flag, not as a number",
          [stored["audio_muted"], type(stored["audio_muted"]).__name__],
          [True, "bool"])

    reloaded = TimelineModel()
    project_storage.restore_model_from_clinq(reloaded, project)
    back = reloaded.get_clip(clip.clip_id)
    check("round trip keeps every knob",
          [round(back.volume, 3), round(back.speed, 3),
           round(back.fade_in, 3), round(back.fade_out, 3), back.audio_muted],
          [0.35, 1.5, 0.4, 0.8, True])
    check("a project reopened from disk is still silent",
          audio_mix.collect_audio_clips(reloaded, {}), [])
    check("round trip keeps the geometry speed left behind",
          [round(back.duration, 3), round(back.out_point, 3)], [2.667, 4.0])
    near("and the reloaded clip measures the same source span",
         back.consumed_source(), 4.0, 0.002)

    # Project cũ (trước tính năng này) KHÔNG có bốn key: phải về mặc định trung
    # tính, nếu không mọi file cũ sẽ im lặng 0% hoặc chạy 0.25x.
    legacy = json.loads(json.dumps(project))
    legacy_clip = legacy["timeline"]["tracks"][0]["clips"][0]
    for key in ("volume", "speed", "fade_in", "fade_out", "audio_muted"):
        legacy_clip.pop(key, None)
    old = TimelineModel()
    project_storage.restore_model_from_clinq(old, legacy)
    restored = list(old.tracks[0].clips)[0]
    check("legacy project restores neutral audio",
          [restored.volume, restored.speed, restored.fade_in, restored.fade_out,
           restored.audio_muted],
          [1.0, 1.0, 0.0, 0.0, False])
    check("legacy project keeps its own duration", round(restored.duration, 3), 2.667)
    graph = audio_mix.build_filter_complex(
        old, audio_mix.collect_audio_clips(old, {}), old.duration)
    check("so the old export graph is byte-for-byte unchanged",
          "volume=" in graph or "atempo=" in graph or "afade=" in graph, False)
    os.remove(CLINQ)


# ── 8. Undo ────────────────────────────────────────────────────

def test_undo():
    print("\n== 8. one undo gives everything back ==")
    from core.commands import SetClipAudioCommand
    model, track, clip = tone_model()
    before = [clip.volume, clip.speed, clip.fade_in, clip.fade_out,
              clip.start_time, clip.duration, clip.in_point, clip.out_point]
    command = SetClipAudioCommand(model, clip.clip_id, volume=0.3, speed=2.0,
                                  fade_in=0.5, fade_out=0.25)
    command.execute()
    check("command applied audio",
          [round(clip.volume, 3), round(clip.speed, 3), clip.fade_in, clip.fade_out],
          [0.3, 2.0, 0.5, 0.25])
    check("and moved geometry", [round(clip.duration, 3), clip.out_point],
          [2.0, 4.0])
    check("description names the knobs", command.description(),
          "Đổi âm lượng + tốc độ + fade")
    command.undo()
    after = [clip.volume, clip.speed, clip.fade_in, clip.fade_out,
             clip.start_time, clip.duration, clip.in_point, clip.out_point]
    check("undo restores audio AND geometry (speed had shortened the clip)",
          [round(v, 6) for v in after], [round(v, 6) for v in before])
    check("so the export plan is back too", model.transition_fades(clip), [])

    redo = SetClipAudioCommand(model, clip.clip_id, speed=4.0)
    redo.execute()
    check("4x shortens to what the source holds", round(clip.duration, 3), 1.0)
    redo.undo()
    check("undo of a pure speed change gives the length back",
          round(clip.duration, 3), 4.0)

    # Một cú tắt tiếng là một lệnh undo được, và không được nhân bản sang các
    # knob khác (volume vẫn 1.0 ở đây).
    mute = SetClipAudioCommand(model, clip.clip_id, audio_muted=True)
    mute.execute()
    check("the mute command writes only the mute flag",
          [clip.audio_muted, clip.volume, round(clip.duration, 3)],
          [True, 1.0, 4.0])
    check("and names itself", mute.description(), "Đổi tắt tiếng")
    mute.undo()
    check("undo brings the sound back", clip.audio_muted, False)
    mute.execute()
    check("redo mutes again", clip.audio_muted, True)

    # Track khoá: set_clip_audio trả {} — lệnh phải tự coi như không xảy ra, nếu
    # không undo() ghi ngược một dict thiếu khoá và làm clip nổ giữa chừng.
    locked = SetClipAudioCommand(model, clip.clip_id, volume=0.1,
                                 audio_muted=False)
    track.is_locked = True
    locked.execute()
    locked.undo()
    track.is_locked = False
    check("a command on a locked track changes nothing",
          [clip.audio_muted, clip.volume], [True, 1.0])
    model.set_clip_audio(clip.clip_id, audio_muted=False)

    # Split: ramp phải chia theo nửa, không nhân đôi và không rơi giữa clip.
    model.set_clip_audio(clip.clip_id, fade_in=1.0, fade_out=1.0)
    right = model.split_clip(clip.clip_id, 2.0)
    left = model.get_clip(clip.clip_id)
    check("left half keeps the fade in", [left.fade_in, left.fade_out], [1.0, 0.0])
    check("right half keeps the fade out", [right.fade_in, right.fade_out],
          [0.0, 1.0])
    check("halves stay inside their own duration",
          [left.fade_in <= left.duration, right.fade_out <= right.duration],
          [True, True])
    plan = [(c.name, [(k, round(st, 3), round(d, 3))
                      for k, st, d in model.transition_fades(c)])
            for c in (left, right)]
    check("each half hands its ramp to the exporter", plan,
          [("clip_audio_tone.wav", [("in", 0.0, 1.0)]),
           ("clip_audio_tone.wav (2)", [("out", 1.0, 1.0)])])


# ── 9. Preview đi qua MainWindow thật ──────────────────────────

def test_preview(app):
    print("\n== 9. preview through the real MainWindow ==")
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QMediaPlayer
    from transition_apply_probe import FakePlayer
    from ui.main_window import MainWindow

    project_storage.AUTO_SAVE_FILE = os.path.join(OUT, "clip_audio_autosave.json")
    win = MainWindow()
    win.resize(1680, 940)
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    player = FakePlayer()
    win._audio_player = player
    # Timer PHẢI dừng để _pre_buffer_active_audio chạy thật (nó tự bảo vệ khi
    # đang phát) — đây chính là hàm có bug mute trước đây.
    win._play_timer.stop()

    def clear():
        model = win.timeline_panel.model
        for track in list(model.tracks):
            model.remove_track(track.track_id)
        model.project_ratio = "16:9"
        model.playhead = 0.0
        player.calls.clear()
        player.setSource(QUrl())
        player.position_ms = 0
        player.rate = 1.0
        player.state = QMediaPlayer.PlayingState
        return model

    # -- volume + fades phải tới được cái loa duy nhất của preview
    model = clear()
    track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(track.track_id, TONE_WAV, "audio", 0.0, 4.0, "tone")
    model.set_clip_audio(clip.clip_id, volume=0.4)
    owner, gain = win._preview_audio_owner(2.0)
    check("owner is the clip under the playhead", owner.clip_id == clip.clip_id,
          True)
    near("preview gain carries the per-clip volume", gain, 0.4, 1e-6)
    win._apply_preview_audio(2.0)
    near("QAudioOutput volume follows it", win._audio_output.volume(), 0.4, 0.01)

    model.set_clip_audio(clip.clip_id, volume=1.0, fade_in=1.0)
    near("preview gain follows the fade at t=0.5",
         win._preview_audio_owner(0.5)[1], smooth(0.5), 1e-6)
    win._apply_preview_audio(0.5)
    near("speaker is half open mid fade", win._audio_output.volume(), smooth(0.5),
         0.01)
    near("and full after the ramp", win._preview_audio_owner(2.0)[1], 1.0, 1e-6)
    # QAudioOutput chỉ 0..1: volume 200% phải được kẹp, không được méo.
    model.set_clip_audio(clip.clip_id, fade_in=0.0, volume=2.0)
    win._apply_preview_audio(2.0)
    in_range("preview clamps the speaker instead of clipping",
             win._audio_output.volume(), 0.999, 1.0)

    # -- speed: đồng hồ phải chạy theo tốc độ của CLIP
    model.set_clip_audio(clip.clip_id, volume=1.0, speed=2.0)
    check("2x clip now spans 2 timeline seconds", round(clip.duration, 3), 2.0)
    player.calls.clear()
    win._apply_preview_audio(0.5)
    check("preview asks the backend for 2x",
          [c for c in player.calls if c[0] == "setPlaybackRate"],
          [("setPlaybackRate", 2.0)])
    near("clock divides by the applied rate", win._timeline_at_source(clip, 2.0),
         1.0, 1e-9)
    near("clock rate read back from the player", win._clock_rate(), 2.0, 1e-9)

    # Backend từ chối rate: playhead phải chạy theo thứ THỰC SỰ phát.
    real_supported = player.isPlaybackRateSupported
    player.isPlaybackRateSupported = lambda rate: False
    win._apply_preview_audio(0.5)
    check("a rejected rate falls back to 1x in the player", win._clock_rate(), 1.0)
    near("and the clock mapping then uses 1x", win._timeline_at_source(clip, 2.0),
         2.0, 1e-9)
    player.isPlaybackRateSupported = real_supported

    # -- mute: track tắt tiếng không được làm master clock, không được phát
    model = clear()
    track = model.add_track(TrackType.AUDIO, "Silent row")
    clip = model.add_clip(track.track_id, TONE_WAV, "audio", 0.0, 4.0, "tone")
    track.is_muted = True
    check("no clock owner on a muted row", win._playback_owner_at(2.0) is None,
          True)
    check("muted row has no preview owner",
          win._preview_audio_owner(2.0)[0] is None, True)
    win._pre_buffer_active_audio()
    check("preload does not load a muted source",
          win._same_media(player.source().toLocalFile(), TONE_WAV), False)
    win._apply_preview_audio(2.0)
    near("and no owner means the speaker is restored",
         win._audio_output.volume(), 1.0, 1e-6)
    check("export also drops the muted row",
          audio_mix.collect_audio_clips(model, {}), [])
    track.is_muted = False
    win._pre_buffer_active_audio()
    check("unmuting loads it again",
          win._same_media(player.source().toLocalFile(), TONE_WAV), True)
    check("clock owner returns",
          win._playback_owner_at(2.0).clip_id == clip.clip_id, True)

    # Nút loa trên transport phải tắt được thiết bị phát thật.
    check("a mute button exists on the transport",
          hasattr(win.timeline_panel.header, "btn_mute"), True)
    win.timeline_panel.header.btn_mute.click()
    check("clicking it mutes the audio output", win._audio_output.isMuted(), True)
    was_checked = win.timeline_panel.header.btn_mute.isChecked()
    win.timeline_panel.header.btn_mute.click()
    check("clicking again unmutes", win._audio_output.isMuted(), False)
    check("and the button drove the icon state",
          [was_checked, win.timeline_panel.header.btn_mute.isChecked()],
          [True, False])

    # -- một bước play thường PHẢI tự áp volume của clip
    model = clear()
    track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(track.track_id, TONE_WAV, "audio", 0.0, 4.0, "tone")
    model.set_clip_audio(clip.clip_id, volume=0.5)
    player.setSource(QUrl.fromLocalFile(TONE_WAV))
    # _pre_buffer_active_audio bên trên kết thúc bằng play()+pause: fake phải
    # đang ở PlayingState thì bước tick mới đi đúng nhánh đồng hồ audio.
    player.state = QMediaPlayer.PlayingState
    win._audio_output.setMuted(False)
    model.playhead = 1.0
    player.position_ms = 2000
    win._play_timer.start()
    win._on_play_step()
    near("a normal tick applies the clip volume", win._audio_output.volume(), 0.5,
         0.01)
    in_range("and advances the playhead from the source clock", model.playhead,
             1.95, 2.05)

    # Đổi nguồn/đổi nhịp cũng là một lần seek: position có thể còn 0 khi file mới
    # nạp, đồng hồ không được vì thế kéo playhead nhảy ngược.
    win._play_timer.stop()
    player.position_ms = 0
    model.playhead = 2.5
    win._on_play_step()
    check("playhead never rewinds when position resets", model.playhead > 2.5, True)

    model.playhead = 3.0
    player.position_ms = 0
    win._play_timer.start()
    win._on_audio_position_changed(0)
    check("a zero position does not rewind the playhead", model.playhead, 3.0)
    win._play_timer.stop()
    return win


# ── 10. Cây sóng ───────────────────────────────────────────────

def test_waveform(win):
    print("\n== 10. waveform ==")
    from PySide6.QtCore import QUrl

    quiet = extract_audio_waveform(GATED_WAV, 60, start=0.0, duration=2.0)
    loud = extract_audio_waveform(GATED_WAV, 60, start=2.0, duration=2.0)
    check("window length matches the request", [len(quiet), len(loud)], [60, 60])
    in_range("silent half of the source draws nothing", max(quiet), 0.0, 0.001)
    in_range("loud half draws a full-height wave", min(loud), 0.5, 1.0)
    check("the wave MOVES with the window (trim is not decoration)",
          max(abs(a - b) for a, b in zip(quiet, loud)) > 0.5, True)

    whole = extract_audio_waveform(GATED_WAV, 60, start=0.0, duration=4.0)
    in_range("whole-clip wave is quiet then loud", max(whole[:29]), 0.0, 0.05)
    in_range("and its back half is full", min(whole[31:]), 0.5, 1.0)

    check("a file with no audio stream returns NO wave",
          extract_audio_waveform(SILENT_MP4, 60), [])
    check("a missing file is not a fake flat wave either",
          extract_audio_waveform(os.path.join(OUT, "nope_absent.wav"), 60), [])

    # Gain của chính cây sóng trên item thật của timeline.
    model = win.timeline_panel.model
    for track in list(model.tracks):
        model.remove_track(track.track_id)
    track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(track.track_id, TONE_WAV, "audio", 0.0, 4.0, "tone")
    win._audio_player.setSource(QUrl())
    model.set_clip_audio(clip.clip_id, volume=0.5)
    item = win.timeline_panel.scene._clip_items.get(clip.clip_id)
    check("the timeline item exists", item is not None, True)
    near("waveform is drawn at the clip volume", item._waveform_gain(0.5), 0.5,
         1e-9)
    check("and the export plan agrees with the picture",
          audio_mix.build_filter_complex(
              model, audio_mix.collect_audio_clips(model, {}),
              model.duration).count("volume=0.500000,"), 1)
    model.set_clip_audio(clip.clip_id, volume=1.0, fade_in=1.0)
    near("waveform ramps with the fade", item._waveform_gain(0.125), smooth(0.5),
         1e-9)
    near("waveform is full after the ramp", item._waveform_gain(0.9), 1.0, 1e-9)

    # Đổi cửa sổ nguồn (tốc độ) phải khién item trích xuất lại; kéo âm lượng thì
    # không — nếu không mỗi cú kéo trượt sẽ spawn một lần giải mã.
    signature_before = item._extraction_signature()
    model.set_clip_audio(clip.clip_id, fade_in=0.0, speed=2.0)
    check("speed changes the extraction window",
          item._extraction_signature() != signature_before, True)
    volume_signature = item._extraction_signature()
    model.set_clip_audio(clip.clip_id, volume=0.7)
    check("volume alone does NOT re-decode the file",
          item._extraction_signature() == volume_signature, True)
    stale = getattr(item, "_extraction_key", None)
    check("the item KNOWS its window went stale",
          stale != item._extraction_signature(), True)
    item.refresh_media_extraction()
    caught_up = getattr(item, "_extraction_key", None)
    check("refresh re-decodes exactly the new window",
          caught_up == item._extraction_signature(), True)
    model.set_clip_audio(clip.clip_id, volume=0.9)
    item.refresh_media_extraction()
    check("a volume-only change does NOT re-decode",
          getattr(item, "_extraction_key", None), caught_up)
    model.resize_clip(clip.clip_id, 1.5)
    item.refresh_media_extraction()
    check("a changed window DOES re-decode",
          getattr(item, "_extraction_key", None) != caught_up, True)
    item.shutdown_extraction()
    return quiet, loud, whole


# ── 11. Thẻ Âm thanh thật trong panel ──────────────────────────

def capture_audio_card(win):
    """Ảnh THẬT của thẻ Âm thanh: đây là UI, không có ảnh thì chưa xong."""
    print("\n== 11. the Audio card in the properties panel ==")
    from PySide6.QtWidgets import QApplication

    model = win.timeline_panel.model
    clip = list(model.tracks[0].clips)[0]
    # Slider phải khớp model; model đang đặt ở mức khác trung tính nên khớp ở đây
    # mới có nghĩa. Nếu thẻ tự nhớ số của nó thì nó hiện 100/100.
    asked = [round(clip.volume * 100), round(clip.speed * 100)]
    undo = win.timeline_panel.undo_stack
    start_count = len(undo._undo_stack)
    win.properties_panel.show_clip_properties(clip)
    win.show()
    for _ in range(20):
        QApplication.processEvents()
    editor = win.properties_panel.current_editor
    card = editor.card_audio
    check("audio card is visible for an audio clip", card.isVisible(), True)
    check("the card reads the model, not its own memory",
          [editor.slider_volume.value(), editor.slider_speed.value()], asked)
    check("and the knob really is off-neutral, so that match means something",
          asked != [100, 100], True)

    before = [clip.volume, clip.speed, clip.fade_in, clip.start_time,
              clip.duration, clip.in_point, clip.out_point]

    # Kéo slider THẬT rồi thả: đây là đường đi của người dùng, không phải mô tả.
    editor.slider_volume.setValue(20)
    editor.slider_volume.sliderReleased.emit()
    near("dragging the volume slider commits to the model", clip.volume, 0.2, 1e-9)
    editor.slider_speed.setValue(150)
    editor.slider_speed.sliderReleased.emit()
    near("dragging the speed slider commits", clip.speed, 1.5, 1e-9)
    editor.slider_fade_in.setValue(50)
    editor.slider_fade_in.sliderReleased.emit()
    near("fade in commits", clip.fade_in, 0.5, 1e-9)
    check("labels read percent / x / seconds",
          [editor.lbl_volume_val.text(), editor.lbl_speed_val.text(),
           editor.lbl_fade_in_val.text()], ["20%", "1.50x", "0.50s"])
    check("three drags pushed three undo steps",
          len(undo._undo_stack) - start_count, 3)
    for _ in range(3):
        undo.undo()
        for _ in range(3):
            QApplication.processEvents()
    after = [clip.volume, clip.speed, clip.fade_in, clip.start_time,
             clip.duration, clip.in_point, clip.out_point]
    check("Ctrl+Z returns audio AND geometry", [round(v, 6) for v in after],
          [round(v, 6) for v in before])

    # Thả slider tại đúng số cũ phải KHÔNG tạo lệnh rỗng. Panel phải tự đọc lại
    # model trước đã (undo ở trên đổi model, slider thì vẫn giữ số cũ).
    win.properties_panel.show_clip_properties(clip)
    for _ in range(4):
        QApplication.processEvents()
    count_before = len(undo._undo_stack)
    editor.slider_volume.setValue(editor.slider_volume.value())
    editor.slider_volume.sliderReleased.emit()
    check("a no-op drag adds no undo noise", len(undo._undo_stack), count_before)

    # Kéo vọt trần: slider 200% nhưng model tự kẹp — panel phải hiển thị lại con
    # số của model, không được tin số của mình.
    editor.slider_volume.setValue(200)
    editor.slider_volume.sliderReleased.emit()
    editor.slider_speed.setValue(400)
    editor.slider_speed.sliderReleased.emit()
    for _ in range(3):
        QApplication.processEvents()
    check("model ceiling wins over the slider number", clip.volume, 2.0)
    near("and the card re-reads the clamped speed", clip.speed, 4.0, 1e-9)

    editor.btn_audio_reset.click()
    for _ in range(3):
        QApplication.processEvents()
    check("reset returns every knob",
          [clip.volume, clip.speed, clip.fade_in, clip.fade_out],
          [1.0, 1.0, 0.0, 0.0])

    # Text/Sticker không có luồng tiếng: hiện slider cho chúng là UI nói dối.
    text_track = model.add_track(TrackType.TEXT)
    text_clip = model.add_clip(text_track.track_id, "", "text", 0.0, 2.0, "title")
    win.properties_panel.show_clip_properties(text_clip)
    for _ in range(6):
        QApplication.processEvents()
    check("a text clip gets no audio card",
          win.properties_panel.current_editor.card_audio.isVisible(), False)

    win.properties_panel.show_clip_properties(clip)
    for _ in range(6):
        QApplication.processEvents()
    card = win.properties_panel.current_editor.card_audio
    win.properties_panel.current_editor.slider_volume.setValue(45)
    win.properties_panel.current_editor.slider_volume.sliderReleased.emit()
    for _ in range(6):
        QApplication.processEvents()
    card.grab().save(PANEL_PNG)
    check("audio card screenshot written", os.path.exists(PANEL_PNG), True)
    if os.path.exists(PANEL_PNG):
        with Image.open(PANEL_PNG) as shot:
            grey = np.asarray(shot.convert("L"), dtype=np.float64)
            check("screenshot has real pixels",
                  [shot.width > 120, shot.height > 80], [True, True])
            # Thẻ phải CÓ NỘI DUNG: một hình chữ nhật tô đặc có std ~ 0.
            check("card content is measurable", float(grey.std()) > 12.0, True)
            in_range("and the brightest pixels are text/handle, not noise",
                     float(np.percentile(grey, 99.5)), 90.0, 255.0)
    return clip


# ── 12. Tắt tiếng RIÊNG một clip ───────────────────────────────

def _two_row_model():
    """Hai clip nối nhau (0-2 s và 2-4 s) trên HAI hàng — tắt một clip thì nửa
    kia của file vẫn phải có tiếng, nên phép đo này không thể ăn gian bằng cách
    im lặng cả project."""
    model = TimelineModel()
    clips = []
    for index, start in enumerate((0.0, 2.0)):
        track = model.add_track(TrackType.AUDIO, "row %d" % index)
        clips.append(model.add_clip(track.track_id, TONE_WAV, "audio",
                                    start, 2.0, "tone %d" % index))
    return model, clips


def test_clip_mute(app, win, ref):
    print("\n== 12. per-clip mute reaches the file ==")
    import time

    def halves(model, path):
        """(mức đo 0-2 s, mức đo 2-4 s) của chính file mà exporter dựng ra."""
        times, values = envelope(mix(model, path), TONE)
        norm = values / ref
        return (solo_level(times, norm, (0.3, 1.8)),
                solo_level(times, norm, (2.3, 3.8)))

    # ── 12a. Export: tắt một clip không được tắt cả project ──
    model, (a, b) = _two_row_model()
    model.set_clip_audio(b.clip_id, volume=0.5)
    front0, back0 = halves(
        model, os.path.join(OUT, "clip_audio_mute_both.wav"))
    in_range("front clip exports at source level", front0, 0.97, 1.03)
    in_range("back clip exports at its own 50%", back0, 0.48, 0.52)

    model.set_clip_audio(b.clip_id, audio_muted=True)
    front1, back1 = halves(
        model, os.path.join(OUT, "clip_audio_mute_back.wav"))
    near("muting the back clip leaves the front EXACTLY as loud",
         front1, front0, 0.02)
    in_range("while the back half of the FILE is silence", back1, 0.0, 0.01)
    check("the muted clip is not even handed to ffmpeg",
          [c.clip_id for c in audio_mix.collect_audio_clips(model, {})],
          [a.clip_id])
    check("mute covers the number, it does not rewrite it", b.volume, 0.5)
    check("and the graph says volume=0 for it",
          "volume=0.000000," in audio_mix.build_filter_complex(
              model, [b], model.duration), True)

    model.set_clip_audio(b.clip_id, audio_muted=False)
    times, values = envelope(mix(
        model, os.path.join(OUT, "clip_audio_mute_off.wav")), TONE)
    norm = values / ref
    in_range("unmuting restores the 50% that was set BEFORE the mute",
             solo_level(times, norm, (2.3, 3.8)), 0.48, 0.52)
    near("front half never moved across the whole mute cycle",
         solo_level(times, norm, (0.3, 1.8)), front0, 0.02)

    # ── 12b. Preview qua MainWindow thật: một cái loa, hai clip chồng nhau ──
    pmodel = win.timeline_panel.model
    for track in list(pmodel.tracks):
        pmodel.remove_track(track.track_id)
    pmodel.playhead = 0.0
    row1 = pmodel.add_track(TrackType.AUDIO, "row A")
    cm = pmodel.add_clip(row1.track_id, TONE_WAV, "audio", 0.0, 4.0, "clip A")
    row2 = pmodel.add_track(TrackType.AUDIO, "row B")
    cl = pmodel.add_clip(row2.track_id, TONE_WAV, "audio", 0.0, 4.0, "clip B")
    pmodel.set_clip_audio(cm.clip_id, audio_muted=True)
    owner, gain = win._preview_audio_owner(2.0)
    check("a muted clip never wins the single speaker",
          owner.clip_id == cl.clip_id, True)
    near("its unmuted neighbour keeps full gain", gain, 1.0, 1e-6)
    pmodel.set_clip_audio(cl.clip_id, audio_muted=True)
    owner, gain = win._preview_audio_owner(2.0)
    check("with both muted a clip still owns the clock", owner is not None, True)
    near("but its gain is silence", gain, 0.0, 1e-9)
    win._apply_preview_audio(2.0)
    near("so the speaker is shut", win._audio_output.volume(), 0.0, 1e-6)
    check("muting does not move the playhead's timebase",
          win._playback_owner_at(2.0).clip_id == owner.clip_id, True)
    pmodel.set_clip_audio(cm.clip_id, audio_muted=False)
    near("one click of gain comes back through the same path",
         win._preview_audio_owner(2.0)[1], 1.0, 1e-6)

    # ── 12c. Nút thật trên thẻ Âm thanh: một cú bấm = một lệnh undo ──
    from PySide6.QtWidgets import QApplication
    undo = win.timeline_panel.undo_stack
    win.properties_panel.show_clip_properties(cm)
    win.show()
    for _ in range(12):
        QApplication.processEvents()
    editor = win.properties_panel.current_editor
    check("the card opens unmuted", editor.btn_audio_mute.isChecked(), False)
    check("and offers the mute action", editor.btn_audio_mute.text(),
          "Tắt tiếng clip")
    steps = len(undo._undo_stack)
    editor.btn_audio_mute.click()
    for _ in range(4):
        QApplication.processEvents()
    check("one click writes the model flag", cm.audio_muted, True)
    check("the button now offers the way back", editor.btn_audio_mute.text(),
          "Bật tiếng clip")
    check("the click pushed exactly one undo step", len(undo._undo_stack) - steps,
          1)
    check("and the step says what it did", undo.undo_text,
          "Hoàn tác: Đổi tắt tiếng")
    undo.undo()
    for _ in range(4):
        QApplication.processEvents()
    check("Ctrl+Z brings the sound back", cm.audio_muted, False)
    undo.redo()
    for _ in range(4):
        QApplication.processEvents()
    check("redo mutes again", cm.audio_muted, True)
    win.properties_panel.show_clip_properties(cm)
    for _ in range(4):
        QApplication.processEvents()
    check("the re-shown card reads the model, not its own memory",
          editor.btn_audio_mute.isChecked(), True)
    editor.btn_audio_reset.click()
    for _ in range(4):
        QApplication.processEvents()
    check("reset clears the mute along with the knobs",
          [cm.audio_muted, cm.volume], [False, 1.0])

    shot_off = os.path.join(OUT, "clip_audio_mute_card_off.png")
    shot_on = os.path.join(OUT, "clip_audio_mute_card_on.png")
    editor.btn_audio_mute.grab().save(shot_off)
    editor.btn_audio_mute.click()
    for _ in range(4):
        QApplication.processEvents()
    editor.btn_audio_mute.grab().save(shot_on)

    # ── 12d. Cây sóng trên timeline phải nói đúng điều người dùng nghe ──
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionGraphicsItem
    from core import settings

    pmodel.set_clip_audio(cm.clip_id, audio_muted=False)
    item = win.timeline_panel.scene._clip_items.get(cm.clip_id)
    check("the timeline has a real item for the clip", item is not None, True)
    deadline = time.time() + 20.0
    while time.time() < deadline and not item.audio_amplitudes:
        QApplication.processEvents()
    check("its waveform really decoded", bool(item.audio_amplitudes), True)
    check("and the timeline shows waveforms at all",
          bool(settings.get("show_waveform")), True)

    def wave_paint(clip_item, tag):
        """Vẽ clip bằng đúng paint() của nó lên QImage rồi trả về (mảng pixel, ảnh).

        rect() của ClipItem tính theo toạ độ cục bộ của item nên hàng đầu tiên
        bắt đầu ở y = 64.5 chứ không phải 0: painter phải tịnh tiến về góc trên-
        trái của rect, còn exposedRect phải đúng bằng rect đó — Qt giao hệ toạ độ
        của item, và paint() cắt nó với rect() để chọn cột sóng vẽ ra. Truyền
        QRectF(0, 0, w, h) thì phần giao rỗng, chỉ vài cột đầu được vẽ.
        """
        rect = clip_item.rect()
        width, height = max(1, int(rect.width())), max(1, int(rect.height()))
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        painter.translate(-rect.left(), -rect.top())
        option = QStyleOptionGraphicsItem()
        option.rect = QRect(0, 0, width, height)
        option.exposedRect = rect
        clip_item.paint(painter, option, None)
        painter.end()
        arr = np.frombuffer(image.constBits(), dtype=np.uint8,
                            count=image.sizeInBytes()).reshape(
            height, image.bytesPerLine() // 4, 4)[:, :width, :3].astype(int)
        image.save(os.path.join(OUT, "clip_audio_wave_%s.png" % tag))
        return arr, (width, height)

    def wave_inks(arr):
        """Đếm pixel "sóng còn tiếng" và "sóng đã tắt" do CHÍNH paint() vẽ.

        Sóng vẽ bằng QPen 1.2px với Antialiasing BẬT nên mỗi cột chỉ phủ ~60% ô:
        60% của #00FFCC cộng nền #1C1D24 là (11,165,136), nên so màu tuyệt đối
        hoặc ngưỡng "xanh+lam>150" sẽ đếm được gần 0 dù sóng vẫn vẽ đầy đủ.
        Vì vậy phân loại theo HƯỚNG màu: cyan kéo lục lên cao hơn đỏ rất nhiều
        và lam thấp hơn lục, còn xám #8a8a92 thì đỏ ≈ lục và cả ba kênh cùng
        sáng lên so với nền. Viền accent #40E0D0 (cùng họ cyan) nằm sát mép nên
        vùng đếm lùi vào trong 6px; chữ trắng và viền phụ chồng chữ (ClearType
        loang màu thành #CCFFE4/#97CDFF) rớt ra ngoài nhờ trần đỏ 150 và khối
        phủ khi chọn/hover thì tối hơn ngưỡng sáng của cả hai họ.
        """
        blue, green, red = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        height, width = red.shape
        inner = np.zeros((height, width), dtype=bool)
        margin = min(6, max(1, width // 2), max(1, height // 2))
        inner[margin:height - margin, margin:width - margin] = True
        cyan = int((inner & (green - red > 40) & (green > 90) &
                    (blue < green) & (red < 150)).sum())
        grey = int((inner & (np.abs(red - green) <= 12) & (blue - red >= 4) &
                    (blue - red <= 24) & (red >= 70) & (red <= 200)).sum())
        return cyan, grey

    def wave_state(clip_item, arr, size, tag):
        """Dòng chẩn đoán + bảng màu thật: ải màu nào FAIL cũng để lại ảnh đo."""
        amp = list(clip_item.audio_amplitudes or [])
        top = {}
        for row in arr[::max(1, size[1] // 40)]:
            for blue, green, red in row[::max(1, size[0] // 60)][:, :]:
                top[(int(red), int(green), int(blue))] = top.get(
                    (int(red), int(green), int(blue)), 0) + 1
        five = sorted(top.items(), key=lambda kv: -kv[1])[:5]
        print("   [%s] %dx%d type=%s silent=%s amps=%d max=%.3f sel=%s hov=%s "
              "wave=%s" % (
                  tag, size[0], size[1], clip_item.clip_model.media_type,
                  clip_item._audio_silent(), len(amp),
                  max(amp) if amp else -1.0, clip_item.isSelected(),
                  clip_item._hover, settings.get("show_waveform")))
        print("        %s" % ", ".join("#%02X%02X%02X x%d" % (c[0], c[1], c[2], n)
                                       for c, n in five))

    item_arr, item_size = wave_paint(item, "audible")
    wave_state(item, item_arr, item_size, "audible")
    cyan_on, grey_on = wave_inks(item_arr)
    columns = max(1, int(item.rect().width() // 2))
    print("   wave pixels: audible cyan=%d grey=%d" % (cyan_on, grey_on))
    in_range("an audible clip paints a cyan wave", cyan_on, 40.0, 1e9)
    in_range("and it covers most of the clip", cyan_on / columns, 0.3, 1e9)
    near("and no grey wave", grey_on, 0, 40)
    pmodel.set_clip_audio(cm.clip_id, audio_muted=True)
    item.update()
    muted_arr, muted_size = wave_paint(item, "muted")
    wave_state(item, muted_arr, muted_size, "muted")
    cyan_m, grey_m = wave_inks(muted_arr)
    print("   wave pixels: muted    cyan=%d grey=%d" % (cyan_m, grey_m))
    check("a muted clip paints ZERO cyan pixels", cyan_m, 0)
    in_range("while the grey wave takes its place", grey_m, 40.0, 1e9)
    in_range("and keeps the SHAPE it had while audible",
             grey_m / max(1, cyan_on), 0.6, 1.6)
    pmodel.set_clip_audio(cm.clip_id, audio_muted=False)
    row1.is_muted = True
    cyan_t, grey_t = wave_inks(wave_paint(item, "row_muted")[0])
    check("muting the whole row greys the wave too", [cyan_t > 0, grey_t > 40],
          [False, True])
    row1.is_muted = False

    # ── 12e. Phản chứng: mọi phép đo trên phải FAIL nếu cờ không còn tác dụng ──
    # Cờ mute chặn tiếng ở HAI tầng: collect_audio_clips không giao clip cho
    # ffmpeg, và clip_volume ép gain về 0 cho preview + chuỗi volume. Neutralise
    # một tầng thôi thì tầng còn lại vẫn im lặng, phép đo "LOUD" sẽ FAIL và ải
    # này thành giấy — phải tắt cả hai cùng lúc.
    real_clip_volume = transitions.clip_volume
    real_collect = audio_mix.collect_audio_clips

    def collect_no_mute(model, cache=None):
        clips = []
        for track in model.tracks:
            if track.is_muted:
                continue
            for clip in track.clips:
                if (clip.media_type in ("audio", "video") and
                        os.path.exists(clip.source_path) and
                        audio_mix.has_audio_stream(clip.source_path, cache)):
                    clips.append(clip)
        return clips

    def no_mute_volume(clip, ignore_mute=False):
        # build_filter_complex `from core.transitions import clip_volume` ngay
        # trong thân hàm, nên ghi đè ở đây tới được tận chuỗi filter của exporter.
        return 1.0 if getattr(clip, "audio_muted", False) else \
            real_clip_volume(clip, ignore_mute=ignore_mute)

    transitions.clip_volume = no_mute_volume
    audio_mix.collect_audio_clips = collect_no_mute
    try:
        model.set_clip_audio(b.clip_id, audio_muted=True)
        times, values = envelope(mix(
            model, os.path.join(OUT, "clip_audio_mute_cf.wav")), TONE)
        cf = solo_level(times, values / ref, (2.3, 3.8))
        in_range("a mute that does nothing leaves the back half LOUD", cf, 0.4,
                 1.0)
    finally:
        transitions.clip_volume = real_clip_volume
        audio_mix.collect_audio_clips = real_collect
    times, values = envelope(mix(
        model, os.path.join(OUT, "clip_audio_mute_restored.wav")), TONE)
    in_range("with the real functions back, it is silent again",
             solo_level(times, values / ref, (2.3, 3.8)), 0.0, 0.01)

    # Cờ bản địa trên ClipItem từng được ghi mỗi ngày mà không có chỗ nào đọc.
    # Quét cả cây ui/ để chiêu "dời cờ sang file khác" không lách được ải này.
    # Chỉ bắt dòng GHI (gán hoặc khai báo field), vì các comment dưới ui/ vẫn
    # nêu tên hai cờ để giải thích vì sao chúng bị bỏ.
    import re
    dead_flag = re.compile(
        r"\b(is_audio_muted|is_video_hidden)\s*(?::\s*bool)?\s*=(?!=)")
    offenders = []
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "ui")):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(folder, fname)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for match in dead_flag.finditer(text):
                offenders.append("%s:%s" % (
                    os.path.relpath(path, ROOT).replace("\\", "/"),
                    match.group(1)))
    check("no write-only track flag survives in ui/", offenders, [])

    return {
        "front": front0, "back_unmuted": back0, "back_muted": back1,
        "front_while_muted": front1,
        "card_off": shot_off, "card_on": shot_on,
        "cyan": [cyan_on, cyan_m], "grey": [grey_on, grey_m],
        "wave_audible": os.path.join(OUT, "clip_audio_wave_audible.png"),
        "wave_muted": os.path.join(OUT, "clip_audio_wave_muted.png"),
    }


# ── 13. Ảnh bằng chứng ─────────────────────────────────────────

def draw_evidence(volume_curves, fades, speed, waves, panel_path, mute=None):
    print("\n== 13. evidence image ==")
    w, h = 1560, 1160
    img = Image.new("RGB", (w, h), "#101014")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(15)
        big = ImageFont.load_default(19)
    except TypeError:
        font = big = ImageFont.load_default()

    def panel(x, y, pw, ph, title, t_max, t_ticks, v_ticks, series):
        left, top = x + 42, y + 32
        plot_w, plot_h = pw - 62, ph - 74
        v_max = max(v_ticks)
        draw.rectangle([x, y, x + pw, y + ph], outline="#33333F")
        draw.text((x + 10, y + 8), title, fill="#E4E4EC", font=big)
        for i in range(t_ticks + 1):
            gx = int(left + plot_w * i / t_ticks)
            draw.line([gx, top, gx, top + plot_h], fill="#22222C")
            draw.text((gx - 9, top + plot_h + 4), "%.1f" % (t_max * i / t_ticks),
                      fill="#8B8BA0", font=font)
        for value in v_ticks:
            gy = int(top + plot_h * (1.0 - value / v_max))
            draw.line([left, gy, left + plot_w, gy], fill="#22222C")
            draw.text((6, gy - 7), "%g" % value, fill="#8B8BA0", font=font)
        colors = ["#4ADE80", "#F59E0B", "#60A5FA", "#F472B6", "#A78BFA", "#E4E4EC"]
        used = []
        for index, (label, times, values) in enumerate(series):
            color = colors[index % len(colors)]
            points = [(int(left + plot_w * min(1.0, t / t_max)),
                       int(top + plot_h * (1.0 - min(v_max, max(0.0, v)) / v_max)))
                      for t, v in zip(times, values)]
            if len(points) > 1:
                draw.line(points, fill=color, width=2)
            spot = left + 8 + index * 118
            draw.text((spot, y + ph - 18), label, fill=color, font=font)
            used.append(label)
        return used

    pw, ph = 740, 340
    panel(20, 20, pw, ph, "A. per-clip volume: measured amplitude / source", 4.0,
          8, [0.0, 1.0, 2.0],
          [("%d%%" % int(level * 100), times, values)
           for level, (times, values) in sorted(volume_curves.items())])
    panel(800, 20, pw, ph, "B. user fade in + fade out, 1 s each", 4.0, 8,
          [0.0, 0.5, 1.0], [("fades 1+1", *fades[0]), ("no fade", *fades[1])])
    panel(20, 380, pw, ph,
          "C. speed vs a gated source (silent 0-2 s): 1x hears nothing", 2.0, 4,
          [0.0, 0.5, 1.0], [("1x", *speed["1x"]), ("2x", *speed["2x"])])

    x, y, pw2, ph2 = 800, 380, 740, 340
    draw.rectangle([x, y, x + pw2, y + ph2], outline="#33333F")
    draw.text((x + 10, y + 8),
              "D. waveform per source window (core/media_extractor.py)",
              fill="#E4E4EC", font=big)
    rows = (("gated 0-2 s  (silent half)", waves[0], "#EF6666"),
            ("gated 2-4 s  (tone half)", waves[1], "#4ADE80"),
            ("gated 0-4 s  (whole clip)", waves[2], "#60A5FA"))
    for r, (label, data, color) in enumerate(rows):
        base = y + 48 + r * 96
        draw.text((x + 12, base - 22), label, fill="#9A9AA8", font=font)
        bar = (pw2 - 40) / max(1, len(data))
        for i, value in enumerate(data):
            bh = max(1.0, float(value) * 66.0)
            draw.rectangle([x + 20 + i * bar, base + 66 - bh,
                            x + 20 + (i + 1) * bar - 1, base + 66], fill=color)

    if os.path.exists(panel_path):
        with Image.open(panel_path) as shot:
            scale = min(1.0, 700.0 / shot.width, 250.0 / shot.height)
            sized = shot.convert("RGB").resize(
                (max(1, int(shot.width * scale)), max(1, int(shot.height * scale))))
            img.paste(sized, (20, 772))
            draw = ImageDraw.Draw(img)
            draw.text((20, 730),
                      "E. real Audio card rendered by ui/properties_panel.py "
                      "(volume 45%%, card %dx%d px)"
                      % (sized.width, sized.height), fill="#E4E4EC", font=big)

    # F + G: tắt tiếng RIÊNG clip. Vẽ dưới dòng chú thích 730 để khe 721-729 vẫn
    # trống như hai ải bên dưới đòi hỏi.
    if mute:
        draw.text((800, 730),
                  "F. per-clip mute: level measured off the exported WAV",
                  fill="#E4E4EC", font=big)
        rows = (("front 0-2 s", mute["front_while_muted"], "#60A5FA"),
                ("back, unmuted", mute["back_unmuted"], "#F472B6"),
                ("back, MUTED", mute["back_muted"], "#EF6666"))
        for r, (label, value, color) in enumerate(rows):
            base = 778 + r * 62
            draw.text((800, base), label, fill="#9A9AA8", font=font)
            bar_w = int(max(0.0, min(1.0, float(value))) * 200)
            draw.rectangle([960, base + 2, 1160, base + 16], outline="#33333F")
            draw.rectangle([960, base + 2, 960 + bar_w, base + 16], fill=color)
            draw.text((1166, base), "%.3f" % float(value), fill=color, font=font)
        draw.text((800, 968), "cyan wave %d px -> %d px, grey %d px -> %d px"
                  % (mute["cyan"][0], mute["cyan"][1],
                     mute["grey"][0], mute["grey"][1]),
                  fill="#9A9AA8", font=font)

        # Hai dải sóng VẼ THẬT (ảnh dump từ chính ClipItem.paint()), phóng to
        # bằng NEAREST để giữ nguyên từng pixel màu. Người duyệt ảnh phải nhìn
        # thấy cây sóng vẫn còn hình dạng mà chỉ đổi màu, chứ không phải tin
        # vào con số ở dòng trên.
        for r, (path, label) in enumerate((
                (mute["wave_audible"], "clip_item.paint() while audible"),
                (mute["wave_muted"], "clip_item.paint() while MUTED"))):
            if not os.path.exists(path):
                continue
            with Image.open(path) as shot:
                scaled = shot.convert("RGB").resize(
                    (int(shot.width * 1.6), int(shot.height * 1.6)),
                    Image.NEAREST)
                top = 990 + r * 82
                img.paste(scaled, (1010, top))
                draw = ImageDraw.Draw(img)
                draw.text((800, top + 18), label, fill="#9A9AA8", font=font)
                strip = np.asarray(scaled).astype(int)
                red, green, blue = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
                cyan_px = int(((green - red > 40) & (green > 90) &
                               (blue < green) & (red < 150)).sum())
                grey_px = int(((np.abs(red - green) <= 12) &
                               (blue - red >= 4) & (blue - red <= 24) &
                               (red >= 70) & (red <= 200)).sum())
                if r == 0:
                    in_range("the audible strip in the evidence is cyan",
                             cyan_px, 200.0, 1e9)
                    check("and carries no grey wave", grey_px < 40, True)
                else:
                    in_range("the muted strip is grey instead",
                             grey_px, 200.0, 1e9)
                    check("and has no cyan left", cyan_px, 0)

        for r, (path, label) in enumerate((
                (mute["card_off"], "button before the click"),
                (mute["card_on"], "button after the click"))):
            if not os.path.exists(path):
                continue
            with Image.open(path) as shot:
                scale = min(1.0, 330.0 / shot.width)
                sized = shot.convert("RGB").resize(
                    (max(1, int(shot.width * scale)),
                     max(1, int(shot.height * scale))))
                img.paste(sized, (1230, 778 + r * 60))
                draw = ImageDraw.Draw(img)
                draw.text((1230, 760 + r * 60), label, fill="#9A9AA8", font=font)

    # Chữ vẽ ra ngoài hộp panel là lỗi có thật ở lần vẽ đầu: hai nhãn "1x"/"2x"
    # của biểu đồ C rơi đúng vào dòng chú thích E. Khe giữa hai hàng panel phải
    # trống, và dòng E không được lẫn màu chữ của chú thích biểu đồ.
    arr = np.asarray(img.convert("RGB")).astype(int)
    for r0, r1 in ((361, 379), (721, 729)):
        ink = int(np.max(np.abs(arr[r0:r1 + 1] - np.array([16, 16, 20])).sum(axis=2)))
        check("rows %d-%d stay an empty gutter" % (r0, r1), ink <= 6, True)
    band = arr[721:772]
    legend_ink = (((band[:, :, 0] < 120) & (band[:, :, 1] > 140) & (band[:, :, 2] > 100)) |
                  ((band[:, :, 0] > 200) & (band[:, :, 1] > 120) &
                   (band[:, :, 1] < 200) & (band[:, :, 2] < 80)))
    check("the caption line carries no chart legend", int(legend_ink.sum()), 0)

    img.save(EVIDENCE)
    print("  saved", EVIDENCE, "%dx%d" % (w, h))
    print("  saved", panel_path)


# ── Runner ─────────────────────────────────────────────────────

def main():
    from PySide6.QtWidgets import QApplication
    # QApplication trước hết: FrameComposer và ClipItem cần nó, và probe đi qua
    # đúng các lớp đó chứ không dựng bản sao không-Qt.
    app = QApplication(sys.argv)
    try:
        from theme import theme_manager
        app.setStyleSheet(theme_manager.stylesheet())
    except Exception as exc:
        print("  (theme skipped: %s)" % exc)

    build_fixtures()

    print("\n== 0. fixtures ==")
    t0, v0 = envelope(TONE_WAV, TONE)
    ref = solo_level(t0, v0, (0.4, 3.6))
    near("tone fixture really is 0.4", ref, SOURCE_LEVEL, 0.01)
    tg, vg = envelope(GATED_WAV, TONE)
    gate = vg / ref
    _gs, high_s = spread(tg, gate, 0.2, 1.8)
    in_range("gated fixture is silent in the first half", high_s, 0.0, 0.02)
    in_range("gated fixture has tone in the second half",
             solo_level(tg, gate, (2.4, 3.8)), 0.97, 1.03)
    other_t, other_v = envelope(TONE_WAV, 1000.0)
    in_range("the 440 Hz bin is blind to other content",
             solo_level(other_t, other_v, (0.4, 3.6)), 0.0, 0.002)

    test_model()
    test_graph()
    volume_curves = test_volume(ref)
    fade_pair = test_fades(ref)
    speed_curves = test_speed(ref)
    test_video_speed()
    test_persistence()
    test_undo()

    win = test_preview(app)
    waves = test_waveform(win)
    capture_audio_card(win)
    mute = test_clip_mute(app, win, ref)
    draw_evidence(volume_curves, fade_pair, speed_curves, waves, PANEL_PNG, mute)

    for reader in getattr(win, "_video_readers", {}).values():
        reader.close()
    for path in (CLINQ, project_storage.AUTO_SAVE_FILE):
        if os.path.exists(path):
            os.remove(path)

    print("\nsummary:", "ALL PASS" if not FAILS else "FAILURES\n  " +
          "\n  ".join(FAILS))

    # Giải phóng có chủ đích: để Python tự giải phong thi QApplication co the bi
    # huy truoc cua so, va C++ fast-fail luc thoat se che mat ket qua probe.
    win.close()
    app.processEvents()
    win = None
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
