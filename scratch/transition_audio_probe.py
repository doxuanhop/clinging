"""scratch/transition_audio_probe.py

Chứng minh #25 bằng SÓ ĐO, không bằng lời. Dựng project hai clip mang hai tiếng
khác nhau (440 Hz / 1000 Hz), chạy đúng ``core/audio_mix.py`` mà exporter dùng,
giải mã wav rồi đo biên độ TỪNG TIẾNG bằng DFT đúng bin (cửa sổ 100 ms, hop 25 ms).
Mọi tỷ số đều chuẩn hoá theo biên độ đo được từ chính file nguồn, nên "1.0" nghĩa
là export giữ đúng mức của nguồn chứ không phải một con số tự thêu.

Counterfactual là phần quan trọng nhất: giữ nguyên HÌNH HỌC chồng lấn 1 giây, chỉ
bỏ afade. Nếu hai phép đo trùng nhau thì phép đo vô nghĩa.
"""

import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio_mix                                       # noqa: E402
from core.timeline_model import TimelineModel, TrackType         # noqa: E402

OUT_DIR = os.path.join(ROOT, "scratch")
A_WAV = os.path.join(OUT_DIR, "transition_audio_tone440.wav")
B_WAV = os.path.join(OUT_DIR, "transition_audio_tone1000.wav")
A_MKV = os.path.join(OUT_DIR, "transition_audio_440.mkv")
B_MKV = os.path.join(OUT_DIR, "transition_audio_1000.mkv")
SILENT_MP4 = os.path.join(OUT_DIR, "transition_audio_silent.mp4")
CROSS_WAV = os.path.join(OUT_DIR, "transition_audio_crossfade.wav")
PLAIN_WAV = os.path.join(OUT_DIR, "transition_audio_plain.wav")
OUT_WAV = os.path.join(OUT_DIR, "transition_audio_fadeout.wav")
IN_WAV = os.path.join(OUT_DIR, "transition_audio_fadein.wav")
EVIDENCE = os.path.join(OUT_DIR, "transition_audio_evidence.png")

FS = 48000
TONE_A = 440.0
TONE_B = 1000.0
SOURCE_LEVEL = 0.4
WIN = 4800          # 100 ms -> cả 440 Hz lẫn 1000 Hz rơi đúng bin DFT
HOP = 1200          # 25 ms
FADE_T = 2.0        # cửa sổ chồng lấn sau ripple: 2.0 .. 3.0
FADE_END = 3.0

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


# ── Fixtures ───────────────────────────────────────────────────

def build_fixtures():
    # Hai biểu thức cách nhau bởi dấu |: nguồn stereo ngay. Upmix mono->stereo
    # của ffmpeg ăn -3 dB (đo được: 0.4 -> 0.283), nên không được dựa vào nó.
    for freq, wav in ((TONE_A, A_WAV), (TONE_B, B_WAV)):
        expr = "%g*sin(2*PI*%g*t)" % (SOURCE_LEVEL, freq)
        run(ffmpeg("-f", "lavfi", "-i",
                   "aevalsrc=exprs=%s|%s:d=3:s=%d" % (expr, expr, FS),
                   "-c:a", "pcm_s16le", "-ar", str(FS), wav),
            "fixture " + os.path.basename(wav))
    for wav, mkv in ((A_WAV, A_MKV), (B_WAV, B_MKV)):
        run(ffmpeg("-f", "lavfi", "-i",
                   "color=c=0x303030:s=320x240:r=12:d=3", "-i", wav,
                   "-map", "0:v", "-map", "1:a",
                   "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", mkv),
            "fixture " + os.path.basename(mkv))
    run(ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x240:r=12:d=3",
               "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", SILENT_MP4), "fixture silent mp4")


def test_fixtures():
    print("\n== 0. fixtures ==")
    ta, va = envelope(A_WAV, TONE_A)
    tb, vb = envelope(B_WAV, TONE_B)
    _t_leak, leak = envelope(B_WAV, TONE_A)
    near("440 Hz source really is 0.4", solo_level(ta, va, (0.3, 2.7)),
         SOURCE_LEVEL, 0.01)
    near("1000 Hz source really is 0.4", solo_level(tb, vb, (0.3, 2.7)),
         SOURCE_LEVEL, 0.01)
    # Thước đo phải mù với tiếng kia: bin 440 không được nhìn thấy 1000 Hz.
    near("440 Hz bin is blind to the 1000 Hz tone",
         solo_level(_t_leak, leak, (0.3, 2.7)), 0.0, 0.002)
    check("fixture is stereo pcm", read_stereo(A_WAV)[0].shape[1], 2)
    return solo_level(ta, va, (0.3, 2.7)), solo_level(tb, vb, (0.3, 2.7))


def story_clips():
    """Main Storyline: A 0-3 (440 Hz), B 3-6 (1000 Hz)."""
    model = TimelineModel()
    track = model.add_track(TrackType.VIDEO)
    a = model.add_clip(track.track_id, A_MKV, "video", 0.0, 3.0, "a")
    b = model.add_clip(track.track_id, B_MKV, "video", 0.0, 3.0, "b")
    return model, track, a, b


def positions(model):
    return {c.name: (round(c.start_time, 3), round(c.end_time, 3))
            for track in model.tracks for c in track.clips}


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


def envelope(path, freq):
    """(times, amplitude): DFT đúng bin nên hai tiếng đo độc lập, không rò rỉ."""
    stereo, _ = read_stereo(path)
    bin_index = int(round(freq * WIN / FS))
    if abs(bin_index * FS / WIN - freq) > 1e-9:
        raise SystemExit("tone %g does not sit on a DFT bin" % freq)
    reference = np.exp(-2j * np.pi * bin_index * np.arange(WIN) / WIN)
    times, frames = _windows(stereo.mean(axis=1))
    return times, 2.0 * np.abs(frames @ reference) / WIN


def total_rms(path):
    stereo, _ = read_stereo(path)
    times, frames = _windows(stereo.mean(axis=1))
    return times, np.sqrt((frames ** 2).mean(axis=1))


def value_at(times, values, t):
    return float(values[int(np.argmin(np.abs(times - t)))])


def solo_level(times, values, span):
    keep = (times >= span[0]) & (times <= span[1])
    inside = values[keep]
    return float(np.median(inside)) if inside.size else 0.0


def slice_values(times, values, low, high):
    keep = (times >= low) & (times <= high)
    return values[keep]


def max_hop_change(times, values, low, high):
    selected = slice_values(times, values, low, high)
    if selected.size < 2:
        return 0.0
    return float(np.max(np.abs(np.diff(selected))))


def hsin_out(x):
    """afade t=out curve=hsin: 0.5 + 0.5*cos(pi*x)."""
    x = min(1.0, max(0.0, float(x)))
    return 0.5 + 0.5 * np.cos(np.pi * x)


def hsin_in(x):
    return 1.0 - hsin_out(x)


def mix(model, out_path):
    audio_mix.render_audio(model, audio_mix.collect_audio_clips(model, {}),
                           model.duration, out_path)
    return out_path


# ── 1. Chuỗi filter ────────────────────────────────────────────

def test_graph():
    print("\n== 1. filter graph ==")
    model, track, a, b = story_clips()
    check("clips laid end-to-end", positions(model),
          {"a": (0.0, 3.0), "b": (3.0, 6.0)})
    check("junction applied",
          model.set_transition(b.clip_id, "Cross Dissolve", 1.0), True)
    check("ripple created the overlap", positions(model),
          {"a": (0.0, 3.0), "b": (2.0, 5.0)})
    check("model duration shrank", round(model.duration, 3), 5.0)

    clips = audio_mix.collect_audio_clips(model, {})
    check("both clips carry audio", [c.name for c in clips], ["a", "b"])
    check("incoming fade plan", model.transition_fades(b), [("in", 0.0, 1.0)])
    check("outgoing fade plan", model.transition_fades(a), [("out", 2.0, 1.0)])

    graph = audio_mix.build_filter_complex(model, clips, model.duration)
    check("afade count matches plan", graph.count("afade="), 2)
    check("incoming afade string",
          "afade=t=in:st=0.000000:d=1.000000:curve=hsin" in graph, True)
    check("outgoing afade string",
          "afade=t=out:st=2.000000:d=1.000000:curve=hsin" in graph, True)
    chains = graph.split(";")
    for index in range(2):
        # afade đứng TRƯỚC adelay: st/d tính theo dòng chảy của clip, adelay
        # mới là thứ đẩy dòng chảy đó xuống đúng chỗ trên timeline.
        check("afade precedes adelay in chain %d" % index,
              0 < chains[index].find("afade") < chains[index].find("adelay"),
              True)
    check("amix sums instead of averaging", "amix=inputs=2" in graph
          and "normalize=0" in graph, True)

    quiet = TimelineModel()
    qtrack = quiet.add_track(TrackType.VIDEO)
    quiet.add_clip(qtrack.track_id, SILENT_MP4, "video", 0.0, 3.0, "silent")
    check("silent video contributes no stream",
          audio_mix.collect_audio_clips(quiet, {}), [])
    check("no stream -> no graph",
          audio_mix.build_filter_complex(quiet, [], quiet.duration), "")

    muted_model, muted_track, _ma, _mb = story_clips()
    muted_track.is_muted = True
    check("muted track contributes nothing",
          audio_mix.collect_audio_clips(muted_model, {}), [])

    # Clip vừa mang chuyển tiếp vào vừa bị clip sau nối chồng: HAI ramp.
    both = TimelineModel()
    btrack = both.add_track(TrackType.VIDEO)
    x = both.add_clip(btrack.track_id, A_MKV, "video", 0.0, 3.0, "x")
    y = both.add_clip(btrack.track_id, B_MKV, "video", 0.0, 3.0, "y")
    z = both.add_clip(btrack.track_id, A_MKV, "video", 0.0, 3.0, "z")
    check("first junction", both.set_transition(y.clip_id, "Wipe Right", 0.5),
          True)
    check("second junction", both.set_transition(z.clip_id, "Slide Left", 0.5),
          True)
    check("middle clip gets both ramps",
          [(kind, round(st, 3), round(dur, 3))
           for kind, st, dur in both.transition_fades(y)],
          [("in", 0.0, 0.5), ("out", 2.5, 0.5)])
    middle = audio_mix.build_filter_complex(
        both, audio_mix.collect_audio_clips(both, {}),
        both.duration).split(";")[1]
    check("double ramp -> two afades in one chain", middle.count("afade="), 2)
    return model


# ── 2. Đo thật: cross-fade ─────────────────────────────────────

def test_crossfade(model, ref_a, ref_b):
    print("\n== 2. measured cross-fade ==")
    path = mix(model, CROSS_WAV)
    _stereo, seconds = read_stereo(path)
    near("mix duration follows project", round(seconds, 3), 5.0, 0.06)

    ta, va = envelope(path, TONE_A)
    tb, vb = envelope(path, TONE_B)
    ea, eb = va / ref_a, vb / ref_b

    # Mức tuyệt đối: clip đứng riêng phải ra đúng mức nguồn. Đây là gate mà
    # amix normalize=1 đánh FAIL (nó chia 2 suốt phần đầu project).
    near("first clip exports at source level", solo_level(ta, ea, (0.3, 1.5)),
         1.0, 0.04)
    near("last clip exports at source level", solo_level(tb, eb, (3.5, 4.7)),
         1.0, 0.04)

    near("A full just before the window", value_at(ta, ea, FADE_T - 0.2), 1.0,
         0.05)
    near("A silent just after the window", value_at(ta, ea, FADE_END + 0.2),
         0.0, 0.05)
    near("B silent just before the window", value_at(tb, eb, FADE_T - 0.2),
         0.0, 0.05)
    near("B full just after the window", value_at(tb, eb, FADE_END + 0.2), 1.0,
         0.05)

    # Giữa cửa sổ: cả hai phải đang ở giữa — một cú cắt cứng không thể cho ra.
    a_quarter = value_at(ta, ea, FADE_T + 0.25)
    b_quarter = value_at(tb, eb, FADE_T + 0.25)
    in_range("A has started falling at p=0.25", a_quarter, 0.55, 0.95)
    in_range("B has started rising at p=0.25", b_quarter, 0.05, 0.45)
    near("A follows hsin at p=0.25", a_quarter, hsin_out(0.25), 0.06)
    near("B follows hsin at p=0.25", b_quarter, hsin_in(0.25), 0.06)
    near("A follows hsin mid-window", value_at(ta, ea, 2.5), hsin_out(0.5), 0.06)
    near("B follows hsin mid-window", value_at(tb, eb, 2.5), hsin_in(0.5), 0.06)
    near("A follows hsin at p=0.75", value_at(ta, ea, 2.75), hsin_out(0.75),
         0.06)
    near("B follows hsin at p=0.75", value_at(tb, eb, 2.75), hsin_in(0.75), 0.06)

    win_a = slice_values(ta, ea, FADE_T, FADE_END)
    win_b = slice_values(tb, eb, FADE_T, FADE_END)
    check("A ramps down monotonically",
          bool(np.all(win_a[:-1] >= win_a[1:] - 0.02)), True)
    check("B ramps up monotonically",
          bool(np.all(win_b[:-1] <= win_b[1:] + 0.02)), True)

    # Bù trừ biên độ: trong cửa sổ, A + B luôn bằng một clip đứng riêng.
    grid = np.arange(FADE_T, FADE_END + 1e-9, HOP / FS)
    summed = np.interp(grid, ta, ea) + np.interp(grid, tb, eb)
    in_range("cross-fade stays amplitude-complementary",
             float(np.max(np.abs(summed - 1.0))), 0.0, 0.05)

    # Không được có cú nhảy mức nào quanh mép cửa sổ: đây chính là cái "bụp"
    # mà amix normalize=1 gây ra khi số input đang hoạt động đổi.
    tr, rms = total_rms(path)
    solo = solo_level(tr, rms, (0.3, 1.5))
    erms = rms / solo
    in_range("no level jump across the junction",
             max_hop_change(tr, erms, 1.85, 3.15), 0.0, 0.12)
    near("total level dips ~3 dB mid-window", value_at(tr, erms, 2.5),
         np.sqrt(0.5), 0.07)
    stereo, _ = read_stereo(path)
    in_range("mix never clips", float(np.max(np.abs(stereo))), 0.2, 0.999)
    return (ta, ea), (tb, eb), (tr, erms)


# ── 3. Counterfactual: cùng chồng lấn, không afade ─────────────

def test_counterfactual(cross_curve, ref_a, ref_b):
    print("\n== 3. counterfactual: same overlap, no afade ==")
    model, _track, a, b = story_clips()
    check("build the same overlap",
          model.set_transition(b.clip_id, "Cross Dissolve", 1.0), True)
    check("then drop the transition",
          model.set_transition(b.clip_id, "", 0.0), True)
    # B đặt lại bằng tay vào 2.0: hình học giống hệt phép đo ở mục 2, chỉ khác
    # là không còn afade. Hai phép đo trùng nhau => phép đo vô nghĩa.
    b.start_time = 2.0
    check("overlap geometry restored", positions(model),
          {"a": (0.0, 3.0), "b": (2.0, 5.0)})
    check("no fade planned without a transition", model.transition_fades(a), [])
    graph = audio_mix.build_filter_complex(
        model, audio_mix.collect_audio_clips(model, {}), model.duration)
    check("graph has no afade", graph.count("afade="), 0)

    path = mix(model, PLAIN_WAV)
    ta, va = envelope(path, TONE_A)
    tb, vb = envelope(path, TONE_B)
    # Chuẩn hoá theo biên độ file NGUỒN, không theo mức đo trong chính file này:
    # lấy file làm mốc thì mọi mức tự thành 1.0 và gate lùi về 0 vô nghĩa.
    plain_a, plain_b = va / ref_a, vb / ref_b
    near("hard overlap keeps A at source level",
         solo_level(ta, plain_a, (2.1, 2.9)), 1.0, 0.05)
    near("hard overlap keeps B at source level",
         solo_level(tb, plain_b, (2.1, 2.9)), 1.0, 0.05)

    # Phép đo PHÂN BIỆT được: bước nhảy lớn nhất ngay tại mép cắt cứng, đo trên
    # cùng một khoảng thời gian cho cả hai lần chạy.
    plain_jump = max_hop_change(ta, plain_a, 2.9, 3.15)
    fade_jump = max_hop_change(cross_curve[0], cross_curve[1], 2.9, 3.15)
    in_range("cross-fade hop across the boundary stays small", fade_jump,
             0.0, 0.08)
    in_range("hard cut hops hard", plain_jump, 0.24, 1.0)
    check("hard cut changes level far more than the cross-fade",
          plain_jump > 3.0 * fade_jump, True)
    print("   biggest hop at the junction edge: plain=%.4f crossfade=%.4f"
          % (plain_jump, fade_jump))
    near("hard cut drops A to silence", value_at(ta, plain_a, 3.2), 0.0, 0.05)
    return (ta, plain_a), (tb, plain_b)


# ── 4. Local fade trên track AUDIO ─────────────────────────────

def test_local_fades(ref_a):
    print("\n== 4. local fades on an audio track ==")
    model = TimelineModel()
    track = model.add_track(TrackType.AUDIO)
    clip = model.add_clip(track.track_id, A_WAV, "audio", 0.0, 3.0, "tone")
    check("fade out accepted",
          model.set_transition(clip.clip_id, "Fade Out", 1.0), True)
    check("local fade does not ripple", positions(model), {"tone": (0.0, 3.0)})
    check("fade out plan", model.transition_fades(clip), [("out", 2.0, 1.0)])

    ta, va = envelope(mix(model, OUT_WAV), TONE_A)
    ea = va / ref_a
    near("fade out holds source level mid-clip", value_at(ta, ea, 1.5), 1.0, 0.03)
    near("fade out at p=0.5", value_at(ta, ea, 2.5), hsin_out(0.5), 0.06)
    in_range("fade out ends silent", value_at(ta, ea, 2.9), 0.0, 0.06)

    check("swap to fade in",
          model.set_transition(clip.clip_id, "Fade In", 1.0), True)
    check("fade in plan", model.transition_fades(clip), [("in", 0.0, 1.0)])
    ta, va = envelope(mix(model, IN_WAV), TONE_A)
    ea = va / ref_a
    in_range("fade in starts silent", value_at(ta, ea, 0.05), 0.0, 0.06)
    near("fade in at p=0.5", value_at(ta, ea, 0.5), hsin_in(0.5), 0.06)
    near("fade in reaches source level", value_at(ta, ea, 1.4), 1.0, 0.03)


# ── 5. Ảnh bằng chứng ──────────────────────────────────────────

def draw_evidence(cross, plain):
    print("\n== 5. evidence image ==")
    (ta, ea), (tb, eb), rms_curve = cross
    (qa, qa_n), (qb, qb_n) = plain

    w, h = 1040, 660
    img = Image.new("RGB", (w, h), "#101014")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(16)
        big = ImageFont.load_default(22)
    except TypeError:
        font = big = ImageFont.load_default()

    left, top, pw, ph = 74, 74, w - 130, h - 290
    t_max, v_max = 5.0, 1.2

    def X(t):
        return int(left + pw * (t / t_max))

    def Y(v):
        return int(top + ph * (1.0 - min(max(float(v), 0.0), v_max) / v_max))

    draw.rectangle([X(FADE_T), top, X(FADE_END), top + ph], fill="#20202C")
    draw.text((X(FADE_T) + 6, top + 6), "overlap window 2.0-3.0 s",
              fill="#8B8BA0", font=font)
    for i in range(11):
        x = int(left + pw * i / 10.0)
        draw.line([x, top, x, top + ph], fill="#26262E")
        draw.text((x - 12, top + ph + 8), "%.1f" % (t_max * i / 10.0),
                  fill="#9A9AA8", font=font)
    for value in (0.0, 0.5, 1.0):
        y = int(top + ph * (1.0 - value / v_max))
        draw.line([left, y, left + pw, y], fill="#26262E")
        draw.text((8, y - 8), "%.1f" % value, fill="#9A9AA8", font=font)
    title = ("core/audio_mix.py rendered wav - per-tone amplitude, exact DFT bin")
    check("chart title fits the image",
          draw.textlength(title, font=big) <= w - left - 12, True)
    draw.text((left, 22), title, fill="#E4E4EC", font=big)
    subtitle = ("measured over a 100 ms window, hop 25 ms; "
                "x = timeline seconds   y = amplitude / source amplitude (0.4)")
    check("chart subtitle fits the image",
          draw.textlength(subtitle, font=font) <= w - left - 12, True)
    draw.text((left, top + ph + 34), subtitle, fill="#9A9AA8", font=font)

    def plot(times, values, color, width=2):
        points = [(X(t), Y(v)) for t, v in zip(times, values)]
        if len(points) > 1:
            draw.line(points, fill=color, width=width)

    plot(qa, qa_n, "#EF6666")
    plot(qb, qb_n, "#5C8DF0")
    plot(ta, ea, "#22C55E", 3)
    plot(tb, eb, "#8B5CF6", 3)
    plot(rms_curve[0], rms_curve[1], "#F59E0B")

    legend = [("#22C55E", "440 Hz with afade cross-fade"),
              ("#8B5CF6", "1000 Hz with afade cross-fade"),
              ("#EF6666", "440 Hz, same 1 s overlap, NO afade (hard cut)"),
              ("#5C8DF0", "1000 Hz, same 1 s overlap, NO afade"),
              ("#F59E0B", "total RMS / solo RMS (amplitude fade: -3 dB mid)")]
    for index, (color, label) in enumerate(legend):
        y = top + ph + 62 + index * 22
        draw.line([left, y + 7, left + 26, y + 7], fill=color, width=3)
        draw.text((left + 34, y - 1), label, fill="#C8C8D4", font=font)

    img.save(EVIDENCE)
    check("evidence image exists", os.path.exists(EVIDENCE), True)
    size = os.path.getsize(EVIDENCE) if os.path.exists(EVIDENCE) else 0
    in_range("evidence image not trivial", size, 12000, 1 << 30)
    reopened = Image.open(EVIDENCE)
    check("evidence image reopens at full size", reopened.size, (w, h))
    pixels = np.asarray(reopened.convert("L"))
    check("evidence image has drawn content", bool((pixels > 60).sum() > 5000),
          True)
    print("   image: %s (%d bytes)" % (EVIDENCE, size))


def main():
    version = subprocess.run(["ffmpeg", "-version"], capture_output=True
                             ).stdout.decode("utf-8", "replace")
    print(version.splitlines()[0])
    build_fixtures()
    # Biên độ quy chiếu đo từ CHÍNH file nguồn, bằng cùng thước đo với mix.
    ref_a, ref_b = test_fixtures()
    cross = test_crossfade(test_graph(), ref_a, ref_b)
    plain = test_counterfactual(cross[0], ref_a, ref_b)
    test_local_fades(ref_a)
    draw_evidence(cross, plain)
    print("\n" + "=" * 62)
    if FAILS:
        print("%d FAIL:" % len(FAILS))
        for line in FAILS:
            print("  - " + line)
        return 1
    print("summary: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
