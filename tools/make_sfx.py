"""Dung kho hieu ung am thanh (SFX) di san trong app — `assets/sfx/`.

Moi tep la mot bieu thuc lavfi thuan: khong tai ve tu dau, khong co moi thu
nghiem ben ngoai, va `tools/ffmpeg/*.exe` la thu duy nhat sinh ra am thanh.
Day la NGUON duy nhat cua pack: chay `python tools/make_sfx.py` de tai tao
toan bo `assets/sfx/*.mp3` + `manifest.json`.

Vi sao gate van phai do lai tung tep chu khong tin manifest: manifest do chinh
script nay viet ra, nen no la loai "tu cham diem" ma AGENTS.md da ghi ten
("cong tu cham cung bi dong goi"). `--sfx-report` doc file bang ffprobe + RMS
va bat lech voi manifest.

So do in ra luc build (bytes / duration / RMS / zero-crossing rate) la so THAT
cua lan chay do; ngan sach pack cung chot theo do, khong chot theo cam tinh.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core import external_tools  # noqa: E402  (bundled-first resolver)

OUT_DIR = os.path.join(ROOT, "assets", "sfx")
SAMPLE_RATE = 44100
# 96k mono la muc thap nhat ma mot tieng chuong 1,8 s van giu duoi 25 kB tren
# may cau hinh thap; 128k khong thay doi RMS do duoc (duoi 1e-4) ma ton them
# ~30% byte, nen khong dung.
BITRATE = "96k"
# Muc am luong chung cua ca pack. Khong phai thoi thien: lan build dau tien
# (khong chuan hoa) do ra RMS lech nhau 33 lan — `sparkle` 0,0106 gan nhu
# khong nghe thay, `riser` 0,3553 lot tanh cac tieng khac — nen moi tep phai
# do lai va keo ve day, kem chan dung `peak` de khong hoa mai vung clip.
TARGET_RMS = 0.18
# 0,95 chu khong phai 1,0: lan build dau `wind` do peak 1,1918 tren chinh file da
# ma hoa (nghe rach) — tran gate phai la so do duoc tu file, khong phai mac dinh
# "am ly thuyet". (Nguyen nhan cua lan do la seed, xem NOISE_SEED duoi day.)
PEAK_CEIL = 0.95
# Muc script huong toi, THAP HON tran gate de du ho cho lech giua hai lan ma
# hoa cung mot gain (mp3 doi phan bo bit theo bien do, ~3,6 %).
PEAK_AIM = 0.88
MAX_GAIN_ITERS = 6
GAIN_EPS = 0.01
# `anoisesrc` mac dinh seed=0 = ngau nhien. Ba cong thuc nhieu cua pack vi the
# khong phai la mot bieu thuc thuan: lan build dau vong lap hoi gain duoi khong
# hoi tu, do lech peak/gain nhay 0,27..0,43 giua hai lan ma hoa lien tiep
# (trace 22/10 tren `whoosh_low`, cung file cung gain). Co dinh seed thi vong lap
# dong trong 2 vong va hai lan ma hoa tra (RMS, ZCR, peak) giong het tung chu so.
NOISE_SEED = 42

# key, label, nhom, so giay, bieu thuc lavfi (mono)
# `gte(t,X)` = cua so bat dong ho: mot bieu thuc duy nhat tao duoc nhieu tieng
# lech nhau ma khong can -filter_complex (giu lenh ffmpeg gan giong nhau).
RECIPES = [
    ("whoosh_low", "Vút thấp", "Chuyển cảnh", 0.70,
     "anoisesrc=color=pink:amplitude=0.75:duration=0.70:sample_rate=%d:seed=%d,"
     "lowpass=f=900,afade=t=in:st=0:d=0.18,"
     "afade=t=out:st=0.30:d=0.40" % (SAMPLE_RATE, NOISE_SEED)),
    ("whoosh_high", "Vút cao", "Chuyển cảnh", 0.45,
     "anoisesrc=color=white:amplitude=0.55:duration=0.45:sample_rate=%d:seed=%d,"
     "highpass=f=1800,lowpass=f=9000,afade=t=in:st=0:d=0.06,"
     "afade=t=out:st=0.18:d=0.27" % (SAMPLE_RATE, NOISE_SEED + 1)),
    ("riser", "Dâng dần", "Chuyển cảnh", 2.00,
     "aevalsrc='(0.10+0.45*t)*sin(2*PI*(150*t+300*t*t))':s=%d:d=2.0,"
     "afade=t=out:st=1.7:d=0.3" % SAMPLE_RATE),
    ("impact", "Trống ngực", "Nhấn mạnh", 0.80,
     "aevalsrc='0.95*sin(2*PI*58*t)*exp(-7*t)"
     "+0.35*sin(2*PI*190*t)*exp(-30*t)':s=%d:d=0.8" % SAMPLE_RATE),
    ("pop", "Bốp", "Nhấn mạnh", 0.30,
     "aevalsrc='0.9*sin(2*PI*320*t)*exp(-16*t)':s=%d:d=0.3" % SAMPLE_RATE),
    ("click", "Tách", "Nhấn mạnh", 0.10,
     "aevalsrc='sin(2*PI*1600*t)*exp(-140*t)':s=%d:d=0.1" % SAMPLE_RATE),
    ("ding", "Keng", "Thông báo", 1.80,
     "aevalsrc='sin(2*PI*880*t)*exp(-3.2*t)"
     "+0.45*sin(2*PI*1760*t)*exp(-4.5*t)"
     "+0.20*sin(2*PI*2640*t)*exp(-6*t)':s=%d:d=1.8" % SAMPLE_RATE),
    ("chime", "Chuông ba tiếng", "Thông báo", 2.20,
     "aevalsrc='sin(2*PI*660*t)*exp(-3*t)"
     "+sin(2*PI*880*(t-0.16))*exp(-3*(t-0.16))*gte(t,0.16)"
     "+sin(2*PI*1100*(t-0.32))*exp(-3*(t-0.32))*gte(t,0.32)':s=%d:d=2.2"
     % SAMPLE_RATE),
    ("tick", "Tích tắc", "Thông báo", 0.70,
     "aevalsrc='sin(2*PI*2400*t)*exp(-190*t)"
     "+sin(2*PI*2400*(t-0.5))*exp(-190*(t-0.5))*gte(t,0.5)':s=%d:d=0.7"
     % SAMPLE_RATE),
    ("error_buzz", "Sai", "Thông báo", 0.90,
     "aevalsrc='0.5*(sin(2*PI*220*t)+sin(2*PI*233*t))*exp(-1.6*t)'"
     ":s=%d:d=0.9" % SAMPLE_RATE),
    ("glitch", "Nhiễu", "Môi trường", 0.35,
     "anoisesrc=color=white:amplitude=0.6:duration=0.35:sample_rate=%d:seed=%d,"
     "highpass=f=1200,tremolo=f=27:d=0.9" % (SAMPLE_RATE, NOISE_SEED + 2)),
    ("sparkle", "Lấp lánh", "Môi trường", 1.40,
     "anoisesrc=color=white:amplitude=0.4:duration=1.4:sample_rate=%d:seed=%d,"
     "highpass=f=5200,tremolo=f=13:d=0.95,afade=t=out:st=0.9:d=0.5"
     % (SAMPLE_RATE, NOISE_SEED + 3)),
    ("wind", "Gió", "Môi trường", 2.20,
     "anoisesrc=color=brown:amplitude=0.85:duration=2.2:sample_rate=%d:seed=%d,"
     "lowpass=f=600,tremolo=f=0.6:d=0.6,afade=t=in:st=0:d=0.4,"
     "afade=t=out:st=1.4:d=0.8" % (SAMPLE_RATE, NOISE_SEED + 4)),
    ("shutter", "Chụp ảnh", "Môi trường", 0.25,
     "aevalsrc='sin(2*PI*2600*t)*exp(-160*t)"
     "+sin(2*PI*2100*(t-0.075))*exp(-160*(t-0.075))*gte(t,0.075)'"
     ":s=%d:d=0.25" % SAMPLE_RATE),
]


def run(argv):
    proc = subprocess.run(argv, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit("ffmpeg that bai: %s\n%s"
                         % (" ".join(argv[:6]),
                            proc.stderr.decode("utf-8", "replace")[-400:]))
    return proc


def probe_seconds(ffprobe, path):
    out = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path]).stdout
    return float(out.decode().strip())


def measure(ffmpeg, path):
    """(rms, zcr, peak) cua TIENG trong file — doc raw f32le qua ffmpeg.

    ZCR (ty le phan bat dau mot nhip, dem qua 8 kHz) la con so de chung minh hai
    SFX khong giong het nhau: `click` va `ding` co the trung RMS nhung khong the
    trung ZC. numpy chi dung luc do, khong phai luc chay app.
    """
    import numpy as np
    raw = run([ffmpeg, "-v", "error", "-i", path, "-vn", "-ac", "1",
               "-ar", "8000", "-f", "f32le", "-"]).stdout
    data = np.frombuffer(raw, np.float32).astype(np.float64)
    if data.size < 8:
        raise SystemExit("file khong co tieng: %s" % path)
    rms = float(np.sqrt(np.mean(data ** 2)))
    peak = float(np.max(np.abs(data)))
    sign = np.signbit(data[1:]) != np.signbit(data[:-1])
    return rms, float(np.mean(sign)), peak


def encode(ffmpeg, graph, seconds, path, gain=None):
    if gain is not None:
        graph = graph + ",volume=%.5f" % gain
    run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", graph,
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "libmp3lame",
         "-b:a", BITRATE, "-t", "%.2f" % seconds, path])


def tune(ffmpeg, graph, seconds, path):
    """Do -> sua gain -> do lai, cho den khi peak tren FILE that nam duoi tran.

    Khong dung mot phep tinh gain moi: so do o buoc ma hoa 1 (tin hieu chua
    khuoch dai) luon du doan thap hon peak cua file da ma hoa o buoc 2, vi 96k
    CBR cat tau cao khac nhau theo bien do. Van dung vong lap cho den khi chinh
    no thoa man, va tra ve lan do gan nhat voi muc tieu.
    """
    gain, rms, zcr, peak = 1.0, 0.0, 0.0, 0.0
    for _ in range(MAX_GAIN_ITERS):
        encode(ffmpeg, graph, seconds, path, gain)
        rms, zcr, peak = measure(ffmpeg, path)
        if peak > PEAK_AIM:
            step = PEAK_AIM / peak
        elif rms < TARGET_RMS:
            step = min(TARGET_RMS / max(rms, 1e-6), PEAK_AIM / max(peak, 1e-6))
        elif rms > TARGET_RMS:
            # Nhin vung nay moi thay: lan hoi tu dau chi keo len, nen `riser`
            # (gain 1,0, RMS 0,3553) lot tanh cac tieng con lai trong khi van
            # duoc peak 0,8208. Tieng lien tuc phai ve dung muc chung.
            step = TARGET_RMS / rms
        else:
            step = 1.0
        if abs(step - 1.0) < GAIN_EPS:
            return gain, rms, zcr, peak, peak <= PEAK_CEIL
        gain *= step
    return gain, rms, zcr, peak, peak <= PEAK_CEIL


def main():
    ffmpeg = external_tools.find("ffmpeg")
    ffprobe = external_tools.find("ffprobe")
    os.makedirs(OUT_DIR, exist_ok=True)
    # Xoa tep cu truoc khi dung: mot entry bi doi ten thi `assets/sfx` phai con
    # DUNG so tep ma manifest ke, neu khong gate "so tep == so entry" xanh vi
    # rac cua lan build truoc.
    for stale in sorted(os.listdir(OUT_DIR)):
        if stale.endswith(".mp3"):
            os.remove(os.path.join(OUT_DIR, stale))
    entries = []
    print("%-13s %-16s %7s %9s %8s %7s %7s %8s" %
          ("key", "nhom", "giay", "bytes", "RMS", "peak", "ZCR", "gain"))
    for key, label, group, seconds, graph in RECIPES:
        name = key + ".mp3"
        path = os.path.join(OUT_DIR, name)
        gain, rms, zcr, peak, converged = tune(ffmpeg, graph, seconds, path)
        if not converged:
            raise SystemExit("%s khong hoi tu: peak %.4f RMS %.4f (tran %.2f)"
                             % (key, peak, rms, PEAK_CEIL))
        entries.append({"key": key, "label": label, "group": group,
                        "file": name,
                        "seconds": round(probe_seconds(ffprobe, path), 4),
                        "want_seconds": seconds, "gain": round(gain, 5),
                        "bytes": os.path.getsize(path),
                        "rms": round(rms, 5), "peak": round(peak, 5),
                        "zcr": round(zcr, 5)})
        print("%-13s %-16s %7.3f %9d %8.4f %7.4f %7.4f %8.3f" %
              (key, group, entries[-1]["seconds"], entries[-1]["bytes"],
               rms, peak, zcr, gain))
    total = sum(e["bytes"] for e in entries)
    print("TONG CONG: %d tep, %s bytes (%.2f MiB)"
          % (len(entries), format(total, ","), total / 1048576.0))
    manifest = {"pack_version": 1, "sample_rate": SAMPLE_RATE,
                "bitrate": BITRATE, "target_rms": TARGET_RMS,
                "peak_ceiling": PEAK_CEIL, "entries": entries}
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as h:
        json.dump(manifest, h, ensure_ascii=False, indent=2, sort_keys=True)
        h.write("\n")
    print("manifest ->", os.path.relpath(os.path.join(OUT_DIR, "manifest.json"), ROOT))


if __name__ == "__main__":
    main()
