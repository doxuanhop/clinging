"""scratch/media_split_probe.py

Bằng chứng ĐO ĐƯỢC cho cơ chế "cắt một file thành N đoạn ra đĩa"
(core/media_splitter.py, ui/split_dialog.py) — tính năng port từ bản Tk
clinging-main, nhưng bỏ moviepy: mọi đường cắt đi qua ffmpeg của hệ thống, và
mọi con số báo cho người dùng đều do ffprobe ĐO LẠI chứ không phải do ffmpeg
tự nhận.

Vì sao phải có chứng cứ về NỘI DUNG, không chỉ về thời lượng: một bộ cắt bỏ
quên `-ss` vẫn trả về N file có đúng thời lượng được hứa, và ffprobe cũng gật
đầu — chỉ có điều cả N file đều chiếu lại cùng một đoạn đầu. Nên nguồn thử là
video có MÀU QUAY THEO THỜI GIAN (hue ~60 độ/giây): mỗi đoạn phải mang đúng
màu của nguồn ở đúng giây nó tự nhận, đo bằng chính reader frame mà preview
dùng. Đây là cách "frame tự khai số của mình" mà so ảnh tổng thể không làm được.

Counterfactual (mục 9) là phần quan trọng nhất: cùng bộ đo ấy chạy trên một
bản cắt CỐ TÌNH SAI — bỏ `-ss`, và bỏ cả việc neo keyframe — và gate buộc phải
ĐỎ. Một gate không đỏ khi code sai thì không phải là gate.

Chạy: python -u scratch/media_split_probe.py
"""

import math
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
import colorsys
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSize

from core import media_splitter as splitter
from core.media_frame import extract_frame_image

import bar_measure

OUT = os.path.join(ROOT, "scratch")
# Tat high-DPI scaling de grab ra pixel thiet bi bang pixel logic: so dong
# teal dem duoc tren anh so thang duoc voi chieu cao khai trong QSS (8px).
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
WORK = os.path.join(OUT, "split_probe_work")
DENSE = os.path.join(WORK, "dense.mp4")        # keyframe mỗi 0.48 s
SPARSE = os.path.join(WORK, "sparse.mp4")      # keyframe chỉ mỗi 4 s (GOP 100)
GATED = os.path.join(WORK, "gated.wav")        # im lặng 0-2 s, tiếng 2-4 s
EVIDENCE = os.path.join(OUT, "media_split_evidence.png")
DIALOG_SHOT = os.path.join(OUT, "media_split_dialog.png")
DIALOG_POINTS_SHOT = os.path.join(OUT, "media_split_dialog_points.png")
DIALOG_RUN_SHOT = os.path.join(OUT, "media_split_dialog_running.png")
DIALOG_OLD_SHOT = os.path.join(OUT, "media_split_dialog_oldstyle.png")
DIALOG_BACK_SHOT = os.path.join(OUT, "media_split_dialog_restyled.png")

FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}
TONE_HZ = 440.0
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


def true(name, value):
    return check(name, bool(value), True)


def above(name, got, floor):
    ok = float(got) > float(floor)
    if not ok:
        FAILS.append("%s: got %r not above %r" % (name, got, floor))
    print("%s  %s  (got=%r want> %r)" % ("PASS" if ok else "FAIL",
                                         name, got, floor))
    return ok


def run(cmd, timeout=300):
    return subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout,
                          check=False, **FLAGS)


# ── Nguồn thử ──────────────────────────────────────────────────

def build_video(path, gop, seconds=6.0):
    """Màu thuần quay theo thời gian: hue xấp xỉ 60 độ mỗi giây.

    `t` trong biểu thức của filter hue là timestamp của frame, nên màu ĐO được
    là một chiếc đồng hồ — không cần OCR, và phân giải dưới một giây.
    """
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i",
           "color=c=red:s=320x240:d=%s:r=25,format=yuv420p,hue=h='t*60'"
           % seconds,
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=%s" % seconds,
           "-shortest", "-c:v", "libx264", "-preset", "veryfast",
           "-g", str(gop), "-pix_fmt", "yuv420p", "-c:a", "aac", path]
    result = run(cmd)
    if result.returncode != 0:
        raise SystemExit("không dựng được video thử: "
                         + result.stderr.decode("utf-8", "replace")[:400])


def build_gated_wav(path, fs=48000, seconds=4.0, level=0.4):
    """Im lặng nửa đầu, sóng sin nửa sau — đoạn nào lấy nhầm chỗ của đoạn khác
    lộ ra ngay trên RMS, không cần phải nghe."""
    frames = int(fs * seconds)
    ramp = np.arange(frames) / float(fs)
    signal = level * math.sqrt(2.0) * np.sin(2 * np.pi * TONE_HZ * ramp)
    channel = np.where(ramp >= seconds / 2.0, signal, 0.0)
    packed = (np.clip(np.column_stack([channel, channel]), -1.0, 1.0)
              * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        handle.writeframes(packed.tobytes())


def rms_at(path, seconds, win_seconds=0.1):
    """Biên độ DFT tại đúng bin của TONE_HZ trong một cửa sổ 100 ms."""
    with wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        raw = np.frombuffer(handle.readframes(handle.getnframes()),
                            dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        raw = raw.reshape(-1, channels).mean(axis=1)
    win = int(rate * win_seconds)
    window = raw[int(seconds * rate):int(seconds * rate) + win]
    if window.size < win:
        window = np.pad(window, (0, win - window.size))
    bins = np.fft.rfft(window * np.hanning(win))
    index = int(round(TONE_HZ * win / rate))
    return float(abs(bins[index]) * 2.0 / win)


def gate_rms(name, path, seconds, want_loud):
    value = rms_at(path, seconds)
    ok = (value > 0.05) if want_loud else (value < 0.01)
    if not ok:
        FAILS.append("%s: rms %.4f at %.1fs, want loud=%s"
                     % (name, value, seconds, want_loud))
    print("%s  %s  (rms=%.4f tai %.1fs muon_co_tieng=%s)"
          % ("PASS" if ok else "FAIL", name, value, seconds, want_loud))
    return value


def hue_at(path, seconds):
    """Góc màu trung bình (độ) của khung hình tại một giây, đọc bằng ĐÚNG
    decoder mà preview dùng."""
    image = extract_frame_image(path, seconds)
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_RGB32)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine() // 4
    arr = np.frombuffer(image.constBits(), np.uint8)
    arr = arr.reshape(height, stride, 4)[:, :width, :].astype(float)
    blue, green, red = arr[..., 0], arr[..., 1], arr[..., 2]
    high = np.maximum(np.maximum(red, green), blue)
    low = np.minimum(np.minimum(red, green), blue)
    chroma = high - low
    hue = np.zeros_like(red)
    mask = (chroma > 0) & (high == red)
    hue[mask] = (((green[mask] - blue[mask]) / chroma[mask]) % 6.0)
    mask = (chroma > 0) & (high == green)
    hue[mask] = ((blue[mask] - red[mask]) / chroma[mask]) + 2.0
    mask = (chroma > 0) & (high == blue)
    hue[mask] = ((red[mask] - green[mask]) / chroma[mask]) + 4.0
    angle = np.deg2rad(hue * 60.0)[chroma > 0]
    if angle.size == 0:
        return None
    return math.degrees(math.atan2(float(np.sin(angle).mean()),
                                   float(np.cos(angle).mean()))) % 360.0


def hue_gap(a, b):
    return min(abs(a - b), 360.0 - abs(a - b))


def alpha_count(pixmap):
    """Số pixel có màu thật — icon null thì đã rõ, nhưng icon trong suốt mà
    'không null' mới là cái bẫy, nên phải đếm alpha."""
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    stride = image.bytesPerLine() // 4
    arr = np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), stride, 4)
    return int((arr[..., 3] > 10).sum())


def grab_png(widget, path):
    widget.grab().save(path, "PNG")
    return path


def out_dir(case):
    folder = os.path.join(WORK, case)
    shutil.rmtree(folder, ignore_errors=True)
    return folder


def listing(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(name for name in os.listdir(folder)
                  if os.path.isfile(os.path.join(folder, name)))


def joints(rows):
    """Độ hở/chồng giữa hai đoạn kế nhau tính từ KẾ HOẠCH: phải toàn 0."""
    return [round(rows[i]["start"] - (rows[i - 1]["start"]
                                      + rows[i - 1]["span"]), 4)
            for i in range(1, len(rows))]


def hue_of_parts(rows, source):
    """[(thứ tự, giây giữa đoạn, màu nguồn tại giây đó, màu của file)] — màu
    của file đo ở đúng giữa đoạn của NÓ, vì file đã là một dải thời gian mới."""
    out = []
    for index, row in enumerate(rows, start=1):
        middle = row["start"] + row["span"] / 2.0
        out.append((index, middle, hue_at(source, middle),
                    hue_at(row["path"], row["span"] / 2.0)))
    return out


def measure_bench():
    """Do chi phi that cua hai duong cat tren cung mot nguon 1080p — so lieu
    cho panel F, lay do chinh gate nay đo chứ không phải con so chep tay."""
    src = os.path.join(WORK, "bench_1080p.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=1920x1080:rate=30:duration=20", "-c:v", "libx264",
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-g", "60", src],
        timeout=600)
    out = {}
    for key, extra in (("copy", ["-c", "copy", "-avoid_negative_ts", "make_zero"]),
                       ("encode", ["-c:v", "libx264", "-preset", "ultrafast",
                                   "-threads", "1", "-an"])):
        target = os.path.join(WORK, "bench_%s.mp4" % key)
        started = time.perf_counter()
        run(["ffmpeg", "-v", "error", "-y", "-ss", "5.0", "-i", src,
             "-t", "5.0"] + extra + [target], timeout=600)
        out[key] = time.perf_counter() - started
    out["ratio"] = out["encode"] / max(0.001, out["copy"])
    for name in ("bench_1080p.mp4", "bench_copy.mp4", "bench_encode.mp4"):
        os.remove(os.path.join(WORK, name))
    return out


# ── Probe ──────────────────────────────────────────────────────

def main():
    app = QApplication.instance() or QApplication(sys.argv)

    def pump(times=8, step=0.05):
        for _ in range(times):
            app.processEvents()
            threading.Event().wait(step)

    os.makedirs(WORK, exist_ok=True)
    build_video(DENSE, 12)
    build_video(SPARSE, 100)
    build_gated_wav(GATED)

    print("\n== 1. Nguon thu: thoi luong va keyframe do duoc ==")
    dense_total = splitter.probe_duration(DENSE)
    sparse_total = splitter.probe_duration(SPARSE)
    near("video keyday dai dung 6s", dense_total, 6.0, 0.15)
    near("video thua dai dung 6s", sparse_total, 6.0, 0.15)
    dense_keys = splitter.keyframe_times(DENSE)
    sparse_keys = splitter.keyframe_times(SPARSE)
    above("video keyday co nhieu keyframe", len(dense_keys), 8)
    check("video thua chi co 2 keyframe", len(sparse_keys), 2)
    check("keyframe tang dan va khong trung",
          dense_keys == sorted(set(dense_keys)), True)
    near("keyframe dau tien nam tai 0", dense_keys[0], 0.0, 0.001)
    check("audio thuan khong co keyframe",
          len(splitter.keyframe_times(GATED)), 0)

    print("\n== 2. Toan thuan: ke hoach cat khong duoc mat noi dung ==")
    check("N doan can N+1 bien", len(splitter.plan_boundaries(6.0, 3)), 4)
    check("bien dau va cuoi khop nguon",
          [splitter.plan_boundaries(6.0, 3)[0],
           splitter.plan_boundaries(6.0, 3)[-1]], [0.0, 6.0])
    check("ba o bang nhau",
          [round(row[1], 3) for row in splitter.plan_segments(6.0, 3)],
          [2.0, 2.0, 2.0])
    check("ke hoach phu dung khoang cat",
          round(sum(row[1] for row in splitter.plan_segments(6.0, 3)), 3), 6.0)
    check("so doan bi chan tren MAX_SEGMENTS",
          len(splitter.plan_boundaries(600.0, 100000)) - 1,
          splitter.MAX_SEGMENTS)
    check("doan ngan hon nguong thi bo bo doan",
          len(splitter.plan_segments(1.0, 50)), 5)
    check("nguon khong co thoi luong thi khong co ke hoach",
          splitter.plan_segments(0.0, 3), [])
    check("khoang cat rong thi khong co ke hoach",
          splitter.plan_segments(6.0, 3, 2.0, 2.0), [])

    # Neo keyframe la cho de sai nhat nen phai do bang danh sach keyframe gia:
    # khong can ffmpeg, va that bai theo cach doc duoc ngay ca khi lech nho.
    rows = splitter.align_boundaries([0.0, 2.0, 4.0, 6.0],
                                     [0.0, 1.92, 3.84, 5.76])
    check("bien duoc keo ve keyframe phia truoc",
          [row["start"] for row in rows], [0.0, 1.92, 3.84])
    check("bien CUOI khong bao gio keo lui",
          round(rows[-1]["start"] + rows[-1]["span"], 3), 6.0)
    check("tong do dai van dung khoang cat",
          round(sum(row["span"] for row in rows), 3), 6.0)
    check("doan cat dung tai keyframe thi khong phai ma hoa",
          [row["encode"] for row in rows], [False, False, False])
    check("khong doan nao ho hay choong", [j for j in joints(rows) if j], [])
    far = splitter.align_boundaries([0.0, 2.0, 4.0, 6.0], [0.0, 6.0])
    check("GOP thua thi bien gi nguyen va doan phai ma hoa",
          [(row["start"], row["encode"]) for row in far],
          [(0.0, False), (2.0, True), (4.0, True)])
    dup = splitter.align_boundaries([0.0, 2.0, 2.1, 6.0],
                                    [0.0, 1.92, 3.84, 5.76])
    check("hai bien neo ve cung mot keyframe thi bi gop",
          [(row["start"], row["span"]) for row in dup],
          [(0.0, 1.92), (1.92, 4.08)])
    collapse = splitter.align_boundaries([0.0, 0.1, 0.2, 6.0], [0.0, 3.0, 6.0])
    check("moi bien ghep ve mot keyframe thi con mot doan bang ca nguon",
          [(row["start"], row["span"]) for row in collapse], [(0.0, 6.0)])
    check("khong con doan rong bang 0",
          [row for row in collapse if row["span"] <= 0], [])
    check("khong do duoc keyframe thi gi nguyen moi bien",
          [(row["start"], row["encode"]) for row in
           splitter.align_boundaries([0.0, 2.0, 4.0, 6.0], [])],
          [(0.0, False), (2.0, False), (4.0, False)])

    print("\n== 2b. Ba kieu cat: doi dai co dinh va moc tu dat (toan thuan) ==")
    check("doi dai co dinh: 65s buoc 30s ra doan cuoi mang du",
          splitter.plan_boundaries_length(65.0, 30.0), [0.0, 30.0, 60.0, 65.0])
    check("doi dai chan van: 60s buoc 30s khong them doan rong",
          splitter.plan_boundaries_length(60.0, 30.0), [0.0, 30.0, 60.0])
    check("du < nguong thi ghep vao doan ke truoc, khong vet",
          splitter.plan_boundaries_length(60.0, 29.95), [0.0, 29.95, 60.0])
    check("buoc du ngan thi khong co ke hoach",
          splitter.plan_boundaries_length(60.0, 0.1), [])
    capped = splitter.plan_boundaries_length(100000.0, 1.0)
    check("cham tran MAX_SEGMENTS thi keo dai buoc thay vi mat noi dung",
          [len(capped) - 1, round(capped[1] - capped[0], 3), capped[-1]],
          [splitter.MAX_SEGMENTS, 500.0, 100000.0])
    check("moc tu dat: loai moc ngoai khoang, moc trung, moc sat nhau",
          splitter.plan_boundaries_points(
              60.0, [5.0, 12.5, 12.5, 0.0, 60.0, 200.0, 59.99]),
          [0.0, 5.0, 12.5, 60.0])
    check("moc tu dat khong co gi thi con mot doan bang ca nguon",
          splitter.plan_boundaries_points(60.0, []), [0.0, 60.0])
    check("moc duoc sap xep lai, khong phu thuoc thu tu nguoi dung go",
          splitter.plan_boundaries_points(60.0, [40.0, 10.0, 25.0]),
          [0.0, 10.0, 25.0, 40.0, 60.0])
    check("kieu moc thang kieu doi dai khi goi build_boundaries",
          splitter.build_boundaries(60.0, 3, 20.0, [7.0]), [0.0, 7.0, 60.0])
    check("doc moc: giay le, phut:giay, gio:phut:giay",
          [splitter.parse_timecode("12.5"), splitter.parse_timecode("0:45"),
           splitter.parse_timecode("1:02:03.5")], [12.5, 45.0, 3723.5])
    check("chuoi khong phai thoi gian thi tra None chu khong phai 0",
          [splitter.parse_timecode(x) for x in
           ("abc", "1,5:30", "1:", "", "1:2:3:4")],
          [None, None, None, None, None])
    check("tach chuoi moc: giu nguyen token doc khong ra de hop thoai in ten",
          splitter.parse_cut_points("0:05, 0:12; 20\nabc, 1:00"),
          ([5.0, 12.0, 20.0, 60.0], ["abc"]))
    for label, kwargs in (("doi dai", {"length": 2.5}), ("moc", {"points": [1.5, 3.5]})):
        rows_style = splitter.plan_segments(6.0, 3, 0.0, 6.0, **kwargs)
        check("ke hoach %s: tong do dai bang khoang cat" % label,
              round(sum(row[1] for row in rows_style), 3), 6.0)
        check("ke hoach %s: bien sau = bien truoc + do dai" % label,
              [round(rows_style[i][0], 3) for i in range(1, len(rows_style))],
              [round(rows_style[i - 1][0] + rows_style[i - 1][1], 3)
               for i in range(1, len(rows_style))])

    print("\n== 3. Cat that: video keyday, che do tu dong ==")
    folder = out_dir("dense_auto")
    dense = splitter.split_media(DENSE, folder, count=3)
    dense_rows = dense["segments"]
    check("ra dung 3 file", listing(folder),
          ["dense_part01.mp4", "dense_part02.mp4", "dense_part03.mp4"])
    check("khong doan nao that bai", len(dense["failed"]), 0)
    check("khong bi huy", dense["cancelled"], False)
    check("cac mei cat khong ho va khong choong", joints(dense_rows),
          [0.0, 0.0])
    near("tong ke hoach bang thoi luong nguon",
         sum(row["span"] for row in dense_rows), dense_total, 0.02)
    for index, row in enumerate(dense_rows, start=1):
        near("doan %d: ffprobe do duoc nhu ke hoach" % index,
             splitter.probe_duration(row["path"]), row["span"],
             splitter.COPY_OVERSHOOT_TOLERANCE + 0.05)
        above("doan %d: file khong rong" % index,
              os.path.getsize(row["path"]), 2000)
    above("co it nhat mot doan copy that",
          sum(1 for row in dense_rows if row["mode"] == "copy"), 0)

    print("\n== 4. NOI DUNG tung doan dung la cua no (mau do duoc) ==")
    hue_rows = hue_of_parts(dense_rows, DENSE)
    check("moi doan do duoc mau",
          [1 if h is not None else 0 for _, _, c, a in hue_rows for h in (c, a)],
          [1] * (2 * len(hue_rows)))
    for index, middle, claimed, actual in hue_rows:
        near("doan %d: mau khop giu doan no tu nhan" % index,
             hue_gap(claimed, actual), 0.0, 22.0)
    parts = [actual for _, _, _, actual in hue_rows]
    above("ba doan mang ba mau KHAC nhau",
          min(hue_gap(a, b) for i, a in enumerate(parts) for b in parts[i + 1:]),
          30.0)
    above("mau nguon quay theo thoi gian that",
          hue_gap(hue_rows[0][2], hue_rows[-1][2]), 60.0)

    print("\n== 5. Video GOP thua: neo keyframe va tu ma hoa lai ==")
    folder = out_dir("sparse_auto")
    sparse = splitter.split_media(SPARSE, folder, count=3)
    sparse_rows = sparse["segments"]
    check("ra du 3 file tren dia", len(sparse_rows), 3)
    check("mei van khong ho khong choong", joints(sparse_rows), [0.0, 0.0])
    near("tong ke hoach van bang nguon",
         sum(row["span"] for row in sparse_rows), sparse_total, 0.02)
    above("GOP thua buoc it nhat mot doan phai ma hoa",
          sum(1 for row in sparse_rows if row["mode"] == "encode"), 0)
    check("doan copy bat dau dung tai keyframe cua nguon",
          [round(row["start"], 2) for row in sparse_rows
           if row["mode"] == "copy"], [0.0, 4.0])
    check("doan khong neo duoc thi bao ma hoa",
          [round(row["start"], 2) for row in sparse_rows
           if row["mode"] == "encode"], [2.0])
    near("noi dung doan cua ban cat GOP thua cung dung",
         max(hue_gap(c, a) for _, _, c, a in hue_of_parts(sparse_rows, SPARSE)),
         0.0, 22.0)
    folder = out_dir("sparse_encode")
    forced = splitter.split_media(SPARSE, folder, count=3,
                                  mode=splitter.MODE_ENCODE)
    check("che do ma hoa: moi doan deu encode",
          sorted({row["mode"] for row in forced["segments"]}), ["encode"])
    near("che do ma hoa: tung doan dung 2.000s",
         forced["segments"][0]["actual"], sparse_total / 3.0, 0.06)
    check("che do ma hoa: bien cat nguyen si",
          [row["start"] for row in forced["segments"]], [0.0, 2.0, 4.0])

    print("\n== 5b. Cat THAT theo ba kieu tren video 6s (do tren FILE) ==")
    style_cases = []
    for label, expected, kwargs in (
            ("deu", 3, {"count": 3}),
            ("doi dai", 3, {"length": 2.5}),
            ("moc", 3, {"points": [1.0, 4.5]})):
        folder = out_dir("style_" + label.replace(" ", "_"))
        case = splitter.split_media(DENSE, folder, **kwargs)
        rows_style = case["segments"]
        check("kieu %s: ra dung %d file tren dia" % (label, expected),
              len(rows_style), expected)
        check("kieu %s: khong doan nao that bai, khong bi huy" % label,
              [len(case["failed"]), case["cancelled"]], [0, False])
        check("kieu %s: mei cat khong ho khong choong" % label,
              joints(rows_style), [0.0] * (expected - 1))
        near("kieu %s: tong ke hoach bang thoi luong nguon" % label,
             sum(row["span"] for row in rows_style), dense_total, 0.02)
        worst_gap = max(hue_gap(claimed, actual)
                        for _, _, claimed, actual in hue_of_parts(rows_style,
                                                                  DENSE))
        check("kieu %s: NOI DUNG tung doan dung cua no (lech mau < 22 do)"
              % label, worst_gap < 22.0, True)
        for index, row in enumerate(rows_style, start=1):
            near("kieu %s: doan %d ffprobe doc duoc nhu ke hoach"
                 % (label, index), row["actual"], row["span"],
                 splitter.COPY_OVERSHOOT_TOLERANCE + 0.05)
        style_cases.append((label, case))
    # Loi ich duy nhat cua kieu moc: cat theo NOI DUNG, khong theo phep chia.
    # Keyframe thua hop copy lech toi 0,4s, nen "dung" la trong tam do lech ay.
    marks = [row["start"] for row in style_cases[2][1]["segments"]][1:]
    check("kieu moc: cat THAT gan hai moc 1,0s va 4,5s da nhap",
          [round(abs(m - r), 3) <= splitter.COPY_DRIFT_TOLERANCE
           for m, r in zip([1.0, 4.5], marks)], [True, True])
    check("kieu moc: doan giua KHONG bang 1/3 nguon (khong phai chia deu)",
          abs(style_cases[2][1]["segments"][1]["span"] - dense_total / 3.0)
          > 0.15, True)
    lengths = [row["span"] for row in style_cases[1][1]["segments"]]
    check("kieu doi dai: moi doan gan 2,5s trich doan cuoi mang du",
          [round(value, 1) for value in lengths[:2]], [2.4, 2.4])
    above("kieu doi dai: doan cuoi la phan du, ngan hon cac doan truoc",
          lengths[0] - lengths[-1], 0.5)

    print("\n== 6. Cat AUDIO: RMS chung doan nao ra vung nay ==")
    folder = out_dir("wav")
    audio = splitter.split_media(GATED, folder, count=4)
    check("ra 4 file wav", listing(folder),
          ["gated_part01.wav", "gated_part02.wav",
           "gated_part03.wav", "gated_part04.wav"])
    near("audio: tong do dai bang nguon",
         sum(row["span"] for row in audio["segments"]),
         splitter.probe_duration(GATED), 0.02)
    check("audio: khong doan nao phai ma hoa",
          sorted({row["mode"] for row in audio["segments"]}), ["copy"])
    gate_rms("doan 1 (0-1s) CAM", audio["segments"][0]["path"], 0.5, False)
    gate_rms("doan 3 (2-3s) CO TIENG 440Hz",
             audio["segments"][2]["path"], 0.5, True)
    gate_rms("doan 3 con tieng den 0.8s cua no",
             audio["segments"][2]["path"], 0.8, True)
    gate_rms("doan 2 (1-2s) VAN CAM", audio["segments"][1]["path"], 0.9, False)

    print("\n== 7. Huy giua chung chi de lai doan da xong ==")
    folder = out_dir("cancel")
    stop_flag = {"on": False}
    seen = []

    def note_progress(done, total, record):
        seen.append(os.path.basename(record["path"]))
        stop_flag["on"] = done >= 2

    cancelled = splitter.split_media(DENSE, folder, count=4,
                                     progress=note_progress,
                                     should_cancel=lambda: stop_flag["on"])
    check("co ghi nhan bi huy", cancelled["cancelled"], True)
    check("dung dung sau doan 2", len(seen), 2)
    check("tren dia chi co 2 file", len(listing(folder)), 2)
    check("do con lai la hai doan dau", seen,
          ["dense_part01.mp4", "dense_part02.mp4"])

    print("\n== 8. Nguon hong, nguon khong ton tai, cach dat ten ==")
    broken = os.path.join(WORK, "broken.mp4")
    with open(broken, "wb") as handle:
        handle.write(b"day khong phai video")
    check("file hong: media_info tra trong", splitter.media_info(broken), {})
    check("file hong: khong cat duoc doan nao",
          len(splitter.split_media(broken, out_dir("broken"),
                                   count=3)["segments"]), 0)
    check("file khong ton tai: duration 0",
          splitter.probe_duration(os.path.join(WORK, "khong_co.mp4")), 0.0)
    check("ten doan giu nguyen duoi cua nguon",
          splitter.segment_name("a.mp4", 3, 12), "a_part03.mp4")
    check("so doan hon 9 thi so rong them cho",
          splitter.segment_name("a.mp4", 12, 12), "a_part12.mp4")
    check("thu muc cu khong bi de len",
          os.path.basename(splitter.unique_output_dir(DENSE)).startswith(
              "dense_parts"), True)

    print("\n== 9. Counterfactual: gate PHAI do khi code sai ==")
    real_run = splitter._run

    def drop_seek(args, timeout=splitter.FFMPEG_TIMEOUT):
        """Ban cat bo quen `-ss`: moi doan deu bat dau tu 0s."""
        trimmed, skip = [], False
        for item in args:
            if skip:
                skip = False
                continue
            if item == "-ss":
                skip = True
                continue
            trimmed.append(item)
        return real_run(trimmed, timeout)

    splitter._run = drop_seek
    folder = out_dir("cf_noseek")
    lying = splitter.split_media(DENSE, folder, count=3,
                                 mode=splitter.MODE_ENCODE)
    splitter._run = real_run
    check("(a) bo -ss van ra 3 file co thoi luong dat",
          [len(lying["segments"])]
          + [abs(row["actual"] - row["span"]) <= 0.2 for row in
             lying["segments"]], [3, True, True, True])
    lying_hue = hue_of_parts(lying["segments"], DENSE)
    worst = max(hue_gap(claimed, actual) for _, _, claimed, actual in lying_hue)
    above("(a) gate MAU PHAI DO: ba doan trung mot noi dung", worst - 22.0, 0.0)
    check("(a) doan dau tien van dung, chi doan sau gian",
          hue_gap(lying_hue[0][2], lying_hue[0][3]) < 22.0, True)

    real_align = splitter.align_boundaries
    real_tol = splitter.COPY_OVERSHOOT_TOLERANCE
    splitter.align_boundaries = lambda points, frames, **kw: [
        {"start": points[i], "span": points[i + 1] - points[i], "encode": False}
        for i in range(len(points) - 1)]
    splitter.COPY_OVERSHOOT_TOLERANCE = 999.0
    folder = out_dir("cf_nosnap")
    naive = splitter.split_media(SPARSE, folder, count=3)
    splitter.align_boundaries = real_align
    splitter.COPY_OVERSHOOT_TOLERANCE = real_tol
    naive_total = sum(row["actual"] for row in naive["segments"])
    above("(b) gate TONG THOI LUONG PHAI DO: copy khong neo thi replay",
          (naive_total - sparse_total) - real_tol * len(naive["segments"]), 0.0)
    check("(b) gate NOI DUNG PHAI DO: doan replay cua doan truoc",
          [row["actual"] - row["span"] > real_tol
           for row in naive["segments"]], [False, True, False])
    naive_worst = max(hue_gap(c, a) for _, _, c, a in
                      hue_of_parts(naive["segments"], SPARSE))
    above("(b) gate MAU PHAI DO: mau doan replay khong phai cua no",
          naive_worst - 22.0, 0.0)
    check("(b) ban that replay toi da 0.15s moi mei cat",
          [row["actual"] - row["span"] > real_tol
           for row in sparse_rows], [False, False, False])
    check("(b) ban that vuot tong thoi luong trong muc cong don theo doan",
          sum(row["actual"] for row in sparse_rows) - sparse_total
          <= real_tol * len(sparse_rows), True)

    print("\n== 10. Cua so that: chuot phai card -> hop thoai -> cat ==")
    # `cache_root()` tro thang vao %APPDATA%\Clinging\cache. Duong dan fixture
    # %TEMP% cua probe doi MOI LAN chay, nen moi lan chay de lai mot file cache
    # vo nghia trong tho cua nguoi dung (do 22/10/2026: diff 1925 -> 1926 file,
    # THEM cache/image/7c67e845abbb9240931e0c98). Van di qua DUNG duong ghi
    # that (khoa = duong dan + mtime + size, temp + os.replace, budget), chi
    # doi GOC de khong lai rac.
    from core import media_cache
    real_cache_root = media_cache.cache_root

    def cache_tree():
        return sum(len(f) for _r, _d, f in os.walk(real_cache_root()))

    user_cache_before = cache_tree()
    redirect = os.path.join(WORK, "cache_redirect")
    os.makedirs(redirect, exist_ok=True)
    media_cache.cache_root = lambda: redirect

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(8)
    card = win.library_panel.add_resource("dense.mp4", "video", DENSE)
    menu = card.context_menu()
    # Lay danh sach ban dung cua gate `--split-report`, khong luu mot con so:
    # "Nen / toi uu tep" vao menu cung luc probe nay van bao "2 hanh dong" xanh.
    from diagnostics import VIDEO_CARD_MENU
    check("card video co dung menu ban dang dong goi",
          [a.text() for a in menu.actions()], VIDEO_CARD_MENU)
    check("hanh dong thu hai la cat file", menu.actions()[1].text(),
          "Cắt thành nhiều đoạn…")
    above("icon keo cua hanh dong net that",
          alpha_count(menu.actions()[1].icon().pixmap(QSize(16, 16))), 20)
    audio_card = win.library_panel.add_resource("gated.wav", "audio", GATED)
    check("card audio chi co mot hanh dong",
          [a.text() for a in audio_card.context_menu().actions()],
          ["Cắt thành nhiều đoạn…"])
    image_card = win.library_panel.add_resource(
        "evid.png", "image", os.path.join(OUT, "clip_audio_evidence.png"))
    check("card anh tinh khong co menu", image_card.context_menu(), None)

    menu.actions()[1].trigger()
    pump(6)
    dialog = getattr(win, "_split_dialog", None)
    check("cua so chinh da mo hop thoai", dialog is not None, True)
    check("hop thoai mo dung nguon vua bam",
          os.path.abspath(dialog._current_source()), DENSE)
    near("hop thoai doc dung thoi luong nguon", dialog._duration,
         dense_total, 0.05)
    check("tom tat ke hoach trung so doan da nhap",
          "%d đoạn" % dialog.spin_count.value() in dialog.lbl_summary.text(),
          True)
    above("hop thoai ve ra co noi dung", alpha_count(dialog.grab()), 40000)
    grab_png(dialog, DIALOG_SHOT)

    style_keys = [dialog.combo_style.itemData(i)
                  for i in range(dialog.combo_style.count())]

    def fits(tag):
        """Khong duoc PHAI CUON moi thay chu thich. Do 22/10/2026 o kieu moc:
        viewport 410 px trong khi than hop thoai can 492 px, nen dong "1 moc
        bi bo..." — dong DUY NHAT noi nguoi dung nhap sai o dau — nam duoc
        fold, va `grab()` chung minh cung khong nhin thay no."""
        sa = dialog._scroll
        check("hop thoai %s khong phai cuon moi thay het chu" % tag,
              [sa.verticalScrollBar().maximum(),
               sa.widget().sizeHint().height() <= sa.viewport().height()],
              [0, True])

    fits("kieu deu")
    dialog.combo_style.setCurrentIndex(style_keys.index("length"))
    pump(2)
    check("chuyen kieu doi dai thi chi con o do dai",
          [dialog.col_count.isHidden(), dialog.col_length.isHidden(),
           dialog.col_points.isHidden()], [True, False, True])
    check("kieu doi dai truyen length, khong truyen count/moc",
          dialog._plan_args()[0], {"length": dialog.spin_length.value()})
    fits("kieu doi dai")

    # KIEU MOC TU DAT tren widget that: ke hoach hien ra PHAI la ke hoach se
    # chay, neu hai ben tinh khac nhau thi nguoi dung thay mot con so trong
    # khi file ra mot con so khac.
    dialog.combo_style.setCurrentIndex(style_keys.index("points"))
    pump(2)
    check("chuyen kieu thi chi con o nhap moc",
          [dialog.col_count.isHidden(), dialog.col_length.isHidden(),
           dialog.col_points.isHidden()], [True, True, False])
    dialog.edit_points.setText("1.2, 0:04.5, sai")
    pump(2)
    check("token doc khong ra duoc in thang ten ra",
          "sai" in dialog.lbl_summary.text(), True)
    fits("token sai")
    dialog.edit_points.setText("1.2, 0:04.5, 99:00")
    pump(2)
    check("moc ngoai khoang bi bo va hop thoai noi ro bao nhieu bi bo",
          [len(dialog._planned()), "bị bỏ" in dialog.lbl_summary.text()],
          [3, True])
    fits("moc tu dat")
    above("kieu moc: cua PHAI rong ra so voi kieu deu",
          dialog.height() - 520, 40)
    grab_png(dialog, DIALOG_POINTS_SHOT)
    dialog.combo_style.setCurrentIndex(style_keys.index("count"))
    pump(2)
    check("quay lai kieu deu thi het chuyen lo moc",
          [dialog.col_count.isHidden(), "bị bỏ" in dialog.lbl_summary.text()],
          [False, False])

    folder = out_dir("dialog")
    dialog.edit_out.setText(folder)
    dialog.spin_count.setValue(2)
    dialog.combo_mode.setCurrentIndex(0)
    dialog.edit_points.setText("1.0, 4.5")
    pump(2)
    dialog._on_run()
    for _ in range(200):
        pump(1, 0.05)
        if dialog.last_result is not None and not dialog._busy:
            break
    check("hop thoai bao xong", dialog._busy, False)
    check("hop thoai cat ra 2 doan", len(dialog.last_result["segments"]), 2)
    check("hop thoai khong bao loi", len(dialog.last_result["failed"]), 0)
    check("so file trong thu muc khop bao cao",
          len([n for n in listing(folder) if n.endswith(".mp4")]), 2)
    status = dialog.lbl_status.text()
    true("status ke ro so doan va thu muc",
         "2 đoạn" in status and os.path.basename(folder) in status)
    fits("status ket qua (2 doan)")
    print("     status:", status)

    # Lan chay THU HAI cua cung hop thoai, lan nay theo MOC: noi duong tu o
    # nhap den FILE tren dia, khong dung o danh sach doan tinh trong dau.
    folder = out_dir("dialog_points")
    dialog.edit_out.setText(folder)
    dialog.combo_style.setCurrentIndex(style_keys.index("points"))
    pump(2)
    dialog._on_run()
    for _ in range(200):
        pump(1, 0.05)
        if dialog.last_result is not None and not dialog._busy:
            break
    rows_p = dialog.last_result["segments"]
    check("hop thoai theo moc: 3 doan trong widget = 3 file tren dia",
          [len(rows_p), len([n for n in listing(folder)
                             if n.endswith(".mp4")])], [3, 3])
    near("hop thoai theo moc: tong do dai van bang nguon",
         sum(row["span"] for row in rows_p), dense_total, 0.02)
    check("hop thoai theo moc: ba doan ba do dai khac nhau (khong phai chia deu)",
          len({round(row["span"], 1) for row in rows_p}), 3)
    fits("status ket qua cat theo moc")
    print("     status moc:", dialog.lbl_status.text())

    # NGUON GOP THUA: 4/6 doan buoc phai ma hoa lai -> ca lan chay keu hon mot
    # giay, de thanh tien trinh con dang o giua khi do.
    dialog2 = win._open_media_split(SPARSE)
    check("hop thoai cat duoc DUNG LAI chu khong mo lan hai", dialog2 is dialog,
          True)
    # Cung MOT hop thoai duoc dung lai (main_window giu _split_dialog), nen
    # kieu van dang o "moc" cua lan chay thu hai phia tren — phai dat lai kieu
    # truoc khi do thang tien trinh, neu khong doan 6 thanh doan 3.
    dialog2.combo_style.setCurrentIndex(style_keys.index("count"))
    dialog2.edit_out.setText(out_dir("dialog_cancel"))
    dialog2.spin_count.setValue(6)
    dialog2._on_run()
    task = dialog2._task
    true("worker da duoc gan truoc khi huy", task is not None)
    check("thang tien trinh hien len khi worker bat dau",
          [dialog2._busy, dialog2.progress.isVisible(),
           dialog2.progress.maximum()], [True, True, 6])
    # Goi DUNG slot ma signal cua worker goi (khong phai gia lap gia tri):
    # do la duong ve that cua thanh. Do tren grab cua RIENG thanh — grab ca
    # hop thoai lay chieu cao nut "Cắt" (cung mau teal, 33 px) chu khong lay
    # thanh, nen no chang chung minh duoc dieu gate noi.
    dialog2._on_progress(3, 6, {"start": 2.0, "mode": "encode"})
    pump(2)
    band = bar_measure.teal_band_height(dialog2.progress, DIALOG_RUN_SHOT)
    print("     bang teal: %d px anh thiet bi cho thanh 8px CSS" % band)
    above("thang tien trinh co pixel that khi chay", band, 3)
    check("thang tien trinh mong (<= 14 px anh, khong con 18px + vien)",
          band <= 14, True)
    # Counterfactual: cung widget do, lap lai kieu cu (18px + vien 1px) thuoc
    # do phai nhay ra day hon. Neu khong nhay, no khong do gi ca.
    dialog2.progress.setFixedHeight(20)
    dialog2.progress.setStyleSheet("QProgressBar { border: 1px solid #262831;"
                                   " border-radius: 6px;"
                                   " background-color: #14151A; }")
    pump(2)
    old_band = bar_measure.teal_band_height(dialog2.progress, DIALOG_OLD_SHOT)
    dialog2.progress.setStyleSheet("")
    dialog2.progress.setFixedHeight(8)
    pump(2)
    print("     kieu cu: %d px -> kieu moi: %d px" % (old_band, band))
    above("do nay phat hien kieu cu day hon kieu moi", old_band - band, 3)
    check("phuc kieu mong thi tra dung con so ban dau",
          bar_measure.teal_band_height(dialog2.progress, DIALOG_BACK_SHOT), band)
    dialog2._on_cancel()
    true("nut Huy dung worker, khong dong cua ngay",
         task.cancel_event.is_set() and dialog2.isVisible())
    for _ in range(120):
        pump(1, 0.05)
        if dialog2.last_result is not None and not dialog2._busy:
            break
    files = len(listing(dialog2.output_dir))
    true("ket qua huy duoc bao cao thang (toi da 6 file)", files <= 6)
    print("     huy luc sau: %d file, status: %s"
          % (files, dialog2.lbl_status.text()))

    # Phan chung cua chinh cua do: neu redirect khong co file nao thi "khong
    # them file vao tho nguoi dung" xanh vi khong ghi lan nao, khong phai vi
    # do dung GOC.
    above("anh nho fixture ghi THAT (qua redirect, khong phai do rong)",
          len(listing(os.path.join(redirect, "image"))), 0)
    check("probe khong de lai file trong cache anh cua nguoi dung",
          cache_tree(), user_cache_before)

    print("\n== 11. Anh chung minh ==")
    bench = measure_bench()
    print("     1080p 5s: copy %.2fs vs ma hoa lai %.2fs (%.1fx)"
          % (bench["copy"], bench["encode"], bench["ratio"]))
    above("copy that su nhanh hon duong ma hoa lai cua ban Tk",
          bench["ratio"], 3.0)
    sheet = make_evidence(dense_total, dense, sparse, forced, audio, naive,
                          lying, hue_rows, lying_hue, bench, style_cases)
    sheet.save(EVIDENCE, "PNG")
    true("anh chung minh nam tren dia", os.path.isfile(EVIDENCE))
    colours = len(sheet.convert("RGB").getcolors(400000) or [])
    above("anh chung minh co nhieu mau (khong phai man trang)", colours, 60)
    print("evidence image", EVIDENCE)

    for widget in (dialog2, dialog, card, audio_card, image_card, win):
        widget.close()
        widget.deleteLater()
    pump(4)
    print("\nsummary: %s  (%d fail)"
          % ("ALL PASS" if not FAILS else "FAILURES", len(FAILS)))
    for line in FAILS:
        print("  FAIL", line)
    print("rc=%d" % (1 if FAILS else 0))
    return 1 if FAILS else 0


def swatch(degrees):
    red, green, blue = colorsys.hsv_to_rgb((degrees % 360.0) / 360.0, 0.95, 0.95)
    return int(red * 255), int(green * 255), int(blue * 255)


def make_evidence(total, dense, sparse, forced, audio, naive, lying, hue_rows,
                  lying_hue, bench, style_cases):
    """Pan A so do cua tung doan, B mau noi dung, C counterfactual, D+E so lieu
    that va chang trai cua hop thoai, G ba kieu cat tren cung mot nguon."""
    width, height = 1560, 1780
    sheet = Image.new("RGB", (width, height), (18, 19, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 17)
        big = ImageFont.truetype("arial.ttf", 21)
    except OSError:
        font = ImageFont.load_default()
        big = font
    teal, white, dim = (64, 224, 208), (232, 234, 240), (150, 154, 166)
    good, bad = (120, 240, 160), (255, 96, 96)
    palette = [(64, 224, 208), (255, 170, 60), (120, 200, 255), (220, 120, 255)]

    def panel(x, y, w, h, name):
        draw.rectangle([x, y, x + w, y + h], outline=(60, 62, 72))
        draw.text((x + 12, y + 8), name, fill=teal, font=big)

    def text(x, y, line, fill=white):
        draw.text((x, y), line, fill=fill, font=font)

    draw.text((24, 14), "Cắt file thành N đoạn — moi con so do ffprobe va "
                        "decoder do lai", fill=teal, font=big)

    rows = dense["segments"]
    panel(24, 52, 720, 320, "A. tung doan: ke hoach vs thuc do")
    scale = 620.0 / max(1.0, total)
    cursor = 0.0
    for index, row in enumerate(rows):
        x0 = 60 + cursor * scale
        x1 = 60 + (cursor + row["span"]) * scale
        colour = palette[index % len(palette)]
        draw.rectangle([x0, 150, x1, 196], fill=colour)
        text(x0 + 4, 206, "doan %d %s" % (index + 1, row["mode"]), fill=colour)
        text(x0 + 4, 228, "ke hoach %.2fs" % row["span"])
        drift = abs(row["actual"] - row["span"])
        text(x0 + 4, 250, "thuc %.3fs" % row["actual"],
             fill=good if drift <= splitter.COPY_OVERSHOOT_TOLERANCE else bad)
        cursor += row["span"]
    text(36, 286, "tong ke hoach %.3fs   nguon %.3fs   mei cat: %s"
         % (sum(r["span"] for r in rows), total,
            ", ".join("%+.3f" % j for j in joints(rows)) or "-"))
    text(36, 314, "ma hoa lai %d/%d doan   copy %d doan"
         % (sum(1 for r in rows if r["mode"] == "encode"), len(rows),
            sum(1 for r in rows if r["mode"] == "copy")), fill=dim)

    panel(768, 52, 768, 320, "B. mau cua doan = mau nguon o giu doan ay")
    for index, (number, middle, claimed, actual) in enumerate(hue_rows):
        y = 100 + index * 84
        draw.rectangle([792, y, 902, y + 60], fill=swatch(claimed))
        draw.rectangle([922, y, 1032, y + 60], fill=swatch(actual))
        gap = hue_gap(claimed, actual)
        text(1052, y + 6, "doan %d  tu %.2f den %.2fs"
             % (number, middle - rows[index]["span"] / 2.0,
                middle + rows[index]["span"] / 2.0))
        text(1052, y + 30, "nguon %.0f do | doan %.0f do | lech %.0f"
             % (claimed, actual, gap), fill=good if gap < 22 else bad)
    text(792, 340, "trai = nguon tai giay doan tu nhan   |   phai = file that",
         fill=dim)

    panel(24, 396, 720, 320, "C. counterfactual — gate phai DO")
    for index in range(len(lying["segments"])):
        y = 444 + index * 46
        claimed = lying_hue[index][2]
        actual = lying_hue[index][3]
        draw.rectangle([48, y, 148, y + 34], fill=swatch(claimed))
        draw.rectangle([162, y, 262, y + 34], fill=swatch(actual))
        gap = hue_gap(claimed, actual)
        text(280, y + 6, "(a) bo -ss: doan %d lech %.0f do" % (index + 1, gap),
             fill=bad if gap > 22 else good)
    naive_total = sum(r["actual"] for r in naive["segments"])
    text(48, 600, "(a) ca 3 file van DUNG thoi luong — chi mau lot ta chung "
                   "mot noi dung", fill=dim)
    replaying = [(index, row) for index, row in enumerate(naive["segments"], 1)
                 if row["actual"] - row["span"]
                 > splitter.COPY_OVERSHOOT_TOLERANCE]
    text(48, 628, "(b) bo neo keyframe: tong do that %.3fs vs nguon %.3fs"
         % (naive_total, naive["duration"]), fill=bad)
    text(48, 656, "     ban that: tong %.3fs, moi doan lech <= %.2fs so voi ke hoach"
         % (sum(r["actual"] for r in sparse["segments"]),
            splitter.COPY_OVERSHOOT_TOLERANCE), fill=good)
    text(48, 684, "(b) replay lo ra o doan %s: %s"
         % (", ".join(str(i) for i, _ in replaying) or "-",
            ", ".join("doan %d ke hoach %.2fs do duoc %.3fs"
                      % (i, r["span"], r["actual"]) for i, r in replaying)),
         fill=bad)

    panel(768, 396, 768, 320, "D. GOP thua va audio")
    # 13 dong trong 320px: de lang 26px thi 4 dong audio tran ra ngoai khung
    # va de len tieu de panel F — do la loi bo cuc, khong phai loi so lieu.
    y = 430
    for row in sparse["segments"]:
        text(792, y, "%-20s start %.2f  ke hoach %.2f  thuc %.3f  %s"
             % (os.path.basename(row["path"]), row["start"], row["span"],
                row["actual"], row["mode"]))
        y += 20
    text(792, y, "che do ma hoa lai:", fill=dim)
    y += 26
    for row in forced["segments"]:
        text(792, y, "%-20s start %.2f  ke hoach %.2f  thuc %.3f  %s"
             % (os.path.basename(row["path"]), row["start"], row["span"],
                row["actual"], row["mode"]), fill=(255, 170, 60))
        y += 20
    text(792, y, "audio 4 doan (im lang 0-2s, tieng 2-4s):", fill=dim)
    y += 26
    for index, row in enumerate(audio["segments"], start=1):
        value = rms_at(row["path"], 0.5)
        text(792, y, "   doan %d  thuc %.3fs  RMS 440Hz tai 0.5s = %.4f"
             % (index, row["actual"], value),
             fill=good if (value > 0.05) == (index >= 3) else bad)
        y += 20

    panel(24, 740, 720, 640, "E. hop thoai that (widget, khong phai mo phong)")
    if os.path.isfile(DIALOG_SHOT):
        shot = Image.open(DIALOG_SHOT).convert("RGB")
        ratio = min(690.0 / shot.width, 590.0 / shot.height)
        size = (max(1, int(shot.width * ratio)), max(1, int(shot.height * ratio)))
        sheet.paste(shot.resize(size, Image.NEAREST), (34, 786))
        draw.rectangle([34, 786, 34 + size[0], 786 + size[1]],
                       outline=(60, 62, 72))
    panel(768, 740, 768, 640, "F. vi sao khong dung moviepy nhu ban Tk")
    lines = [
        (teal, "Ban clinging-main (Tk + moviepy)"),
        (white, "- mo VideoFileClip cho TUNG doan roi write_videofile()"),
        (white, "  preset ultrafast: giai ma + ma hoa LAI toan bo doan,"),
        (white, "  khong bao gio copy, nen chat luong giam mot the he."),
        (white, "- do may nay (cat doan 5s tu file 1080p30 20s):"),
        (white, "  copy %.2fs   vs   ma hoa lai %.2fs  = %.0f lan cham hon"
              % (bench["copy"], bench["encode"], bench["ratio"])),
        (white, "- bao 'thanh cong' ma khong do lai file da ghi."),
        (dim, ""),
        (teal, "O day:"),
        (white, "- ffprobe liet keyframe MOT LAN; diem cat duoc NEO ve"),
        (white, "  keyframe phia truoc (tolerance %.2fs) nen doan copy"
              % splitter.COPY_DRIFT_TOLERANCE),
        (white, "  khong replay ca GOP; neo khong noi thi ma hoa rieng no."),
        (white, "- moi file sinh ra duoc ffprobe DO LAI va so voi ke hoach,"),
        (white, "  lech qua %.2fs thi ma hoa lai tai cho."
              % splitter.COPY_OVERSHOOT_TOLERANCE),
        (white, "- gia phai tra: tong thoi luong tren dia co the hon nguon"),
        (white, "  toi da %.2fs moi mei cat copy (do dem khung hinh B-frame"
              % splitter.COPY_OVERSHOOT_TOLERANCE),
        (white, "  reorder), khong phai mat noi dung — cot mau o panel B"),
        (white, "  chung moi doan dung mang dung noi dung cua no."),
    ]
    y = 792
    for fill, line in lines:
        text(792, y, line, fill=fill)
        y += 30

    panel(24, 1400, 1512, 340,
          "G. ba kieu cat tren CUNG mot nguon 6s: deu / doi dai co dinh / "
          "moc tu dat")
    y = 1446
    for label, case in style_cases:
        rows_g = case["segments"]
        scale_g = 700.0 / max(1.0, total)
        x = 210
        for index, row in enumerate(rows_g):
            width = max(2.0, row["span"] * scale_g)
            draw.rectangle([x, y, x + width, y + 26],
                           fill=palette[index % len(palette)])
            text(x + 3, y + 30, "%.2fs" % row["actual"], fill=dim)
            x += width
        text(48, y + 4, "kieu %s" % label, fill=teal)
        gaps = joints(rows_g)
        text(960, y + 4, "%d doan   mei %s   tong %.3f/%.3fs"
             % (len(rows_g), ", ".join("%+.3f" % j for j in gaps) or "-",
                sum(row["span"] for row in rows_g), total), fill=good)
        text(960, y + 28, "start: %s"
             % ", ".join("%.2f" % row["start"] for row in rows_g), fill=dim)
        y += 78
    text(48, y, "ca ba kieu deu cat tren FILE: khong doan nao ho/choong, "
                "tong span = nguon, mau tung doan khop mau nguon", fill=dim)
    return sheet


if __name__ == "__main__":
    sys.exit(main())
