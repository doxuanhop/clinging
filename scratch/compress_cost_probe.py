"""Do CHI PHI that cua tung preset/codec tren may nay, bang dung ffmpeg cua app.

Cai nen cua compressO (github.com/codeforreal1/compressO) co hai preset:
  ironclad   -> them `-preset slow` (+ yuv420p, +faststart, -b:v 0)
  thunderbolt-> khong them block do
"Chon preset nao cho Clinging" khong the quyet bang loi noi. Must đo trên máy
có cấu hình thấp: con số dưới đây là thứ quyết định UI, không phải tài liệu.

Moi cau hinh chay LEN KE nhau trong CUNG MOT vong (hai vong rieng le lech nhau
chi vi drift doc dia). Fixture tu lavfi, khong dong video cua nguoi dung.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import external_tools  # noqa: E402

SOURCE_SECONDS = 6.0
# Dung sai PHAI theo container. Lan chay 21/10/2026 da dinh nghia loi bang
# cach khac: nep `-c:v libx264` ra `out.mp4.webm` thi ffmpeg bat ngay
# rc=4294967274 (0xFFFFFFEA, -22) trong 0,2s — container le, codec phai theo.
CONFIGS = (
    ("x264 ultrafast", "mp4", ["-c:v", "libx264", "-preset", "ultrafast",
                               "-crf", "28"]),
    ("x264 veryfast", "mp4", ["-c:v", "libx264", "-preset", "veryfast",
                              "-crf", "28"]),
    ("x264 fast", "mp4", ["-c:v", "libx264", "-preset", "fast", "-crf", "28"]),
    ("x264 medium", "mp4", ["-c:v", "libx264", "-preset", "medium",
                            "-crf", "28"]),
    ("x264 slow", "mp4", ["-c:v", "libx264", "-preset", "slow", "-crf", "28"]),
    ("x265 veryfast", "mp4", ["-c:v", "libx265", "-preset", "veryfast",
                              "-crf", "30", "-tag:v", "hvc1"]),
    ("x265 fast", "mp4", ["-c:v", "libx265", "-preset", "fast", "-crf", "30",
                          "-tag:v", "hvc1"]),
    # vp9 khong nhan `-preset` (do la cua libx26x); no nhan `-cpu-used`, va
    # Bat BUOC phai co `-b:v 0` khi dung crf — thieu no thi bitrate bi chan.
    ("vp9 cpu8", "webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33",
                          "-cpu-used", "8", "-row-mt", "1"]),
    ("vp9 cpu5", "webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33",
                          "-cpu-used", "5", "-row-mt", "1"]),
    ("vp9 good", "webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33",
                          "-row-mt", "1"]),
)


def run(command):
    started = time.perf_counter()
    result = subprocess.run(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, check=False,
                            creationflags=0x08000000 if os.name == "nt" else 0)
    return time.perf_counter() - started, result.returncode, (
        result.stderr or b"").decode("utf-8", "replace")[-300:]


def main():
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        print("FAIL: khong tim thay ffmpeg")
        return 1
    folder = tempfile.mkdtemp(prefix="clinging_compress_cost_")
    source = os.path.join(folder, "src.mp4")
    base = [ffmpeg, "-v", "error", "-hide_banner", "-y"]
    make = base + ["-f", "lavfi", "-i",
                   "testsrc2=size=1280x720:rate=25:duration=%g" % SOURCE_SECONDS,
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=%g"
                   % SOURCE_SECONDS, "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                   source]
    seconds, code, noise = run(make)
    if code != 0 or not os.path.isfile(source):
        print("FAIL: khong dung duoc fixture: %s" % noise)
        return 1
    src_bytes = os.path.getsize(source)
    print("fixture 1280x720 %gs: %d B  (dung %0.1fs de tao, %s)"
          % (SOURCE_SECONDS, src_bytes, seconds, ffmpeg))
    print("CPU logical: %s" % (os.cpu_count(),))

    rows = []
    for name, extension, flags in CONFIGS:
        out = os.path.join(folder, "out_%s.%s" % (name.replace(" ", "_"),
                                                 extension))
        command = (base + ["-i", source, "-map", "0:v:0", "-an"] + flags
                   + [out])
        elapsed, code, noise = run(command)
        size = os.path.getsize(out) if os.path.isfile(out) else 0
        rows.append({"name": name, "ext": extension, "rc": code,
                     "s": round(elapsed, 2),
                     "bytes": size, "ratio": round(size / float(src_bytes), 4)
                     if src_bytes else 0.0, "noise": noise.strip()[:120]})
        print("%-16s rc=%d  %6.2fs  %9d B  gap %5.1f%%  %s"
              % (name, code, elapsed, size,
                 (1.0 - (size / float(src_bytes))) * 100.0 if src_bytes else 0.0,
                 noise.strip().replace("\n", " ")[:60]))
        if os.path.isfile(out):
            os.unlink(out)
    failed = [r["name"] for r in rows if r["rc"] != 0 or r["bytes"] <= 0]
    print("\nTHAT BAI (codec khong co trong ban nay): %s" % (failed or "khong co"))
    with open(os.path.join(HERE, "scratch", "_compress_cost.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"ffmpeg": ffmpeg, "cpu": os.cpu_count(),
                   "source_bytes": src_bytes, "rows": rows}, handle, indent=1)
    for entry in os.listdir(folder):
        try:
            os.unlink(os.path.join(folder, entry))
        except OSError:
            pass
    os.rmdir(folder)
    print("ALL DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
