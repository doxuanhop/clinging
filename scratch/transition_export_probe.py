"""scratch/transition_export_probe.py

Mạch cuối của #25: chạy đúng ``RenderWorker`` của hộp thoại Xuất (kẻ thật người
dùng bấm), rồi đo âm thanh trong FILE MP4 ĐẦU RA — không phải file trung gian.

Chuỗi đo lại toàn bộ qua helper của transition_audio_probe.py, nên file này chỉ
trả lời một câu hỏi: cross-fade có sống sót qua AAC 192k và bước mux hay không.
"""

import os
import subprocess
import sys

import numpy as np

SCRATCH = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRATCH)
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRATCH)

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtWidgets import QApplication                        # noqa: E402

from core.timeline_model import TimelineModel, TrackType          # noqa: E402
from ui.export_dialog import RenderWorker                         # noqa: E402
import transition_audio_probe as measure                          # noqa: E402

OUT_MP4 = os.path.join(SCRATCH, "transition_export_e2e.mp4")
OUT_WAV = os.path.join(SCRATCH, "transition_export_e2e.wav")
PLAIN_MP4 = os.path.join(SCRATCH, "transition_export_plain.mp4")
PLAIN_WAV = os.path.join(SCRATCH, "transition_export_plain.wav")

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


def story(with_transition=True):
    model = TimelineModel()
    model.project_ratio = "4:3"
    track = model.add_track(TrackType.VIDEO)
    a = model.add_clip(track.track_id, measure.A_MKV, "video", 0.0, 3.0, "a")
    b = model.add_clip(track.track_id, measure.B_MKV, "video", 0.0, 3.0, "b")
    if with_transition:
        assert model.set_transition(b.clip_id, "Cross Dissolve", 1.0)
    else:
        # Cùng hình học chồng lấn, chỉ khác là không có afade.
        b.start_time = 2.0
    return model


def export(model, out_path):
    for path in (out_path, out_path + "_audio.mp3"):
        try:
            os.remove(path)
        except OSError:
            pass
    worker = RenderWorker(model, out_path, 320, 240, 12, "4:3", False)
    errors, done = [], []
    worker.errorOccurred.connect(errors.append)
    worker.finished_ok.connect(done.append)
    worker.run()
    return errors, done


def decode_audio(mp4_path, wav_path):
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp4_path, "-vn",
         "-c:a", "pcm_s16le", "-ar", str(measure.FS), "-ac", "2", wav_path],
        capture_output=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit("decode failed: " +
                         proc.stderr.decode("utf-8", errors="replace")[-500:])
    return wav_path


def streams(mp4_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type:format=duration", "-of",
         "default=nw=1:nk=1", mp4_path],
        capture_output=True, timeout=60)
    lines = [l.strip() for l in
             probe.stdout.decode("utf-8", errors="replace").splitlines()
             if l.strip()]
    kinds = [l for l in lines if l in ("video", "audio")]
    duration = next((float(l) for l in lines if ":" not in l and
                     l.replace(".", "", 1).isdigit()), 0.0)
    return kinds, duration


def main():
    app = QApplication(sys.argv)
    measure.build_fixtures()
    ref_a, ref_b = measure.test_fixtures()

    print("\n== 1. real export through RenderWorker ==")
    model = story(True)
    errors, done = export(model, OUT_MP4)
    check("exporter reported no error", errors, [])
    check("exporter emitted finished_ok", done, [OUT_MP4])
    check("output file exists", os.path.exists(OUT_MP4), True)
    in_range("output file is not trivial",
             os.path.getsize(OUT_MP4), 5000, 1 << 30)
    kinds, duration = streams(OUT_MP4)
    check("output carries video and audio", kinds, ["video", "audio"])
    near("output duration follows the rippled timeline", duration, 5.0, 0.12)

    print("\n== 2. cross-fade survived AAC + mux ==")
    wav = decode_audio(OUT_MP4, OUT_WAV)
    ta, va = measure.envelope(wav, measure.TONE_A)
    tb, vb = measure.envelope(wav, measure.TONE_B)
    ea, eb = va / ref_a, vb / ref_b
    near("first clip still at source level",
         measure.solo_level(ta, ea, (0.3, 1.5)), 1.0, 0.06)
    near("last clip still at source level",
         measure.solo_level(tb, eb, (3.6, 4.7)), 1.0, 0.06)
    near("A fades at p=0.25 in the finished file",
         measure.value_at(ta, ea, 2.25), measure.hsin_out(0.25), 0.09)
    near("B rises at p=0.25 in the finished file",
         measure.value_at(tb, eb, 2.25), measure.hsin_in(0.25), 0.09)
    near("A fades at mid-window in the finished file",
         measure.value_at(ta, ea, 2.5), 0.5, 0.09)
    near("B rises at mid-window in the finished file",
         measure.value_at(tb, eb, 2.5), 0.5, 0.09)
    near("A is silent after the window",
         measure.value_at(ta, ea, 3.3), 0.0, 0.06)
    grid = np.arange(measure.FADE_T, measure.FADE_END + 1e-9,
                     measure.HOP / measure.FS)
    summed = (np.interp(grid, ta, ea) + np.interp(grid, tb, eb))
    in_range("finished file stays amplitude-complementary",
             float(np.max(np.abs(summed - 1.0))), 0.0, 0.09)

    print("\n== 3. counterfactual on the same path ==")
    plain_model = story(False)
    perrors, pdone = export(plain_model, PLAIN_MP4)
    check("plain export reported no error", perrors, [])
    check("plain export finished", pdone, [PLAIN_MP4])
    pwav = decode_audio(PLAIN_MP4, PLAIN_WAV)
    qa, qva = measure.envelope(pwav, measure.TONE_A)
    qb, qvb = measure.envelope(pwav, measure.TONE_B)
    near("plain overlap keeps A at full",
         measure.solo_level(qa, qva / ref_a, (2.1, 2.9)), 1.0, 0.06)
    near("plain overlap keeps B at full",
         measure.solo_level(qb, qvb / ref_b, (2.1, 2.9)), 1.0, 0.06)
    plain_jump = measure.max_hop_change(qa, qva / ref_a, 2.9, 3.2)
    fade_jump = measure.max_hop_change(ta, ea, 2.9, 3.2)
    print("   biggest hop at the cut: plain=%.4f crossfade=%.4f"
          % (plain_jump, fade_jump))
    check("the finished file shows a harder cut without afade",
          plain_jump > 3.0 * fade_jump, True)
    in_range("plain hard cut jumps hard", plain_jump, 0.2, 1.0)

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
