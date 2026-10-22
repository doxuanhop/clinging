"""Do CHI PHI that cua tung cap (x264 preset, CRF) tren may nay, de CHON bang
preset cho hop thoai Xuat — khong chon bang loi noi.

Day la duong XUAT cua app: video vao ffmpeg la rawvideo RGBA do FrameComposer
pipe ra, khong phai mp4 doc tu dia. Nen probe dung dung kieu do: dung MOT
luong frame (file .raw) roi nep no qua tung cau hinh, LEN KE nhau trong CUNG
mot vong (hai vong rieng le lech nhau 8-12 ms chi vi drift doc dia - bai hoc
nhom the pixel). So can quyet: giay ma hoa, byte ra loi, va bit/pixel (so do
nhat quan sat giua hai do phan giai).

Fixture tu lavfi, khong dong video cua nguoi dung.
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

W, H, FPS, SECONDS = 1280, 720, 30, 2.0
ROUNDS = 2
# (nhan, preset, crf). "hien tai" la cap hard-code o ui/export_dialog.py:871
# truoc khi nhom nay bat dau - moi bang khac phai so sanh duoc voi no.
CANDIDATES = (
    ("hien tai CRF18 medium", "medium", 18),
    ("CRF21 medium", "medium", 21),
    ("CRF24 medium", "medium", 24),
    ("CRF21 veryfast", "veryfast", 21),
    ("CRF23 veryfast", "veryfast", 23),
    ("CRF24 veryfast", "veryfast", 24),
    ("CRF23 ultrafast", "ultrafast", 23),
    ("CRF20 slow", "slow", 20),
)


def run(command):
    started = time.perf_counter()
    result = subprocess.run(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, check=False,
                            creationflags=0x08000000 if os.name == "nt" else 0)
    return time.perf_counter() - started, result.returncode, (
        (result.stderr or b"").decode("utf-8", "replace"))[-300:]


def main():
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        print("FAIL: khong tim thay ffmpeg")
        return 1
    folder = tempfile.mkdtemp(prefix="clinging_export_cost_")
    raw = os.path.join(folder, "stream.raw")
    frames = int(FPS * SECONDS)
    # Dung MOT luong frame that cho moi cau hinh: sinh rawvideo RGBA tu lavfi,
    # ghi ra file, roi doc lai. Neu moi cau hinh tu sinh noi dung rieng thi
    # khong con la cung mot noi dung de so byte.
    make = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=%dx%d:rate=%d:duration=%g" % (W, H, FPS, SECONDS),
            "-f", "rawvideo", "-pix_fmt", "rgba", raw]
    seconds, code, noise = run(make)
    if code != 0 or not os.path.isfile(raw):
        print("FAIL: khong dung duoc raw stream: %s" % noise)
        return 1
    expected = frames * W * H * 4
    actual = os.path.getsize(raw)
    print("raw stream %d frame %dx%d = %.0f MB (%.0f s sinh)"
          % (frames, W, H, actual / 1048576.0, seconds))
    if actual != expected:
        print("FAIL: raw stream %d B, mong %d B" % (actual, expected))
        return 1

    base_in = [ffmpeg, "-v", "error", "-y", "-f", "rawvideo",
               "-pixel_format", "rgba", "-video_size", "%dx%d" % (W, H),
               "-framerate", str(FPS), "-i", raw]
    best = {}
    for rnd in range(ROUNDS):
        for label, preset, crf in CANDIDATES:
            out = os.path.join(folder, "out_%d_%s_%d.mp4" % (rnd, preset, crf))
            cmd = base_in + ["-c:v", "libx264", "-preset", preset,
                             "-crf", str(crf), "-pix_fmt", "yuv420p",
                             "-an", out]
            dt, code, noise = run(cmd)
            if code != 0 or not os.path.isfile(out):
                print("FAIL [%s]: %s" % (label, noise))
                return 1
            size = os.path.getsize(out)
            prev = best.get(label)
            if prev is None or dt < prev["giay"]:
                best[label] = {"giay": dt, "byte": size, "preset": preset,
                               "crf": crf}
            os.remove(out)

    total_pixels = frames * W * H
    cur = best["hien tai CRF18 medium"]["giay"]
    cur_bytes = best["hien tai CRF18 medium"]["byte"]
    rows = []
    print("\n%-24s %8s %10s %10s %10s" %
          ("cau hinh", "giay", "x1,00 hien", "MB/2s", "bit/pixel"))
    for label, preset, crf in CANDIDATES:
        row = best[label]
        bpp = row["byte"] * 8.0 / total_pixels / SECONDS
        line = "%-24s %8.2f %10.2f %10.2f %10.3f" % (
            label, row["giay"], row["giay"] / cur,
            row["byte"] / 1048576.0, bpp)
        print(line)
        rows.append({"label": label, "preset": preset, "crf": crf,
                     "giay": round(row["giay"], 3),
                     "giay_so_voi_hien_tai": round(row["giay"] / cur, 3),
                     "byte": row["byte"],
                     "MB_moi_giay": round(row["byte"] / 1048576.0 / SECONDS, 3),
                     "bit_pixel": round(bpp, 4),
                     "byte_so_voi_hien_tai": round(row["byte"] / float(cur_bytes), 4)})

    dst = os.path.join(HERE, "scratch", "export_quality_cost.json")
    with open(dst, "w", encoding="utf-8") as handle:
        json.dump({"may": {"W": W, "H": H, "fps": FPS, "seconds": SECONDS,
                           "rounds": ROUNDS}, "rows": rows},
                  handle, ensure_ascii=False, indent=1)
    print("\njson:", dst)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # 221 MB raw stream nam trong %TEMP% (o C: con ~8,6 GB): probe nao sinh
        # file lon phai tu don, ke ca khi chay hong giua chung.
        import glob
        import shutil
        for leftover in glob.glob(os.path.join(
                tempfile.gettempdir(), "clinging_export_cost_*")):
            shutil.rmtree(leftover, ignore_errors=True)
