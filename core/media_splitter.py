"""
core/media_splitter.py

Cat MỘT file media (video hoặc audio) thành N đoạn bằng nhau, mỗi đoạn là một
file thật trên đĩa.

Đừng nhầm với `TimelineModel.split_clip()`: cắt trên timeline chỉ sửa
start/duration của clip và không đụng tới file gốc — đó là biên tập không phá
huỷ. Còn ở đây người ta muốn "cho tôi 5 clip ngắn để đăng riêng từng cái",
tức là xuất file.

Bản Tk (clinging-main) làm việc này bằng moviepy. Ứng dụng này chỉ dựa vào
ffmpeg — bản đi kèm trong ``tools/`` thắng, PATH chỉ là nguồn dự phòng (xem
``core.external_tools``) — nên toàn bộ đường cắt đi qua subprocess, và mọi con
số báo cho người dùng đều do ffprobe đo lại chứ không phải do lệnh cắt tự nhận.

Vì sao phải dò keyframe: với `-c copy`, ffmpeg không thể bắt đầu giữa một
nhóm ảnh — nó neo ngược về keyframe gần nhất. Nếu cứ giao `-ss 2.0` rồi mặc
nó, đoạn 2 sẽ replay lại một mẩu của đoạn 1, và cả lot dài HƠN file gốc. Vì
vậy điểm cắt được chỉnh về đúng keyframe đó ngay từ kế hoạch, đoạn nào không
neo được (GOP thưa hơn cả một đoạn) thì mã hoá lại riêng nó.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import re
import subprocess

from core import external_tools

MIN_SEGMENT_SECONDS = 0.2   # đoạn ngắn hơn nữa thì chỉ tổ ra file rỗng
MAX_SEGMENTS = 200          # trần an toàn: 200 file vẫn là bot dia, khong phai lot

# Điểm cắt được phép neo lùi bao nhiêu giây so với ô đều nhau. Quá chừng này
# thì thà mã hoá lại còn hơn trả một đoạn dài lệch nhìn thấy bằng mắt.
COPY_DRIFT_TOLERANCE = 0.40

# Bản thân `-t` khi copy cũng viết nốt cả gói ảnh/dải âm thanh vượt mép cắt,
# nên file THỰC có thể dài hơn kế hoạch một chút. Chấp nhận tới chừng này rồi
# mới mã hoá lại: hai đoạn chồng lên nhau hơn một phần mười giây là người xem
# thấy ngay cảnh cũ chiếu lại.
COPY_OVERSHOOT_TOLERANCE = 0.15

# Container mà libx264 + aac là lựa chọn hiển nhiên; ngoài danh sách này để
# ffmpeg tự chọn codec theo container, tránh lỗi "codec not compatible".
X264_CONTAINERS = (".mp4", ".mov", ".m4v", ".mkv")

MODE_AUTO = "auto"        # copy ở đâu an toàn, mã hoá ở đâu không neo được
MODE_ENCODE = "encode"    # chính xác từng giây, chậm nhất

MODES = (MODE_AUTO, MODE_ENCODE)

FFMPEG_TIMEOUT = 7200.0     # một đoạn 4K dài vẫn xong trong chừng này
PROBE_TIMEOUT = 15.0
KEYFRAME_TIMEOUT = 120.0


def _window_flags() -> dict:
    """ffmpeg/ffprobe khong duoc phep nhay cua so den len tren may Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": 0x08000000}


def media_info(file_path: str) -> dict:
    """{duration, has_video, has_audio} do ffprobe đo; {} khi không đọc được."""
    if not file_path or not os.path.isfile(file_path):
        return {}
    ffprobe = external_tools.find("ffprobe")
    if not ffprobe:
        return {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT, check=False, **_window_flags())
        if result.returncode != 0:
            return {}
        data = json.loads((result.stdout or b"").decode("utf-8", "replace")
                          or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    kinds = {stream.get("codec_type")
             for stream in data.get("streams", []) if stream.get("codec_type")}
    duration = float(data.get("format", {}).get("duration") or 0.0)
    if duration <= 0:
        for stream in data.get("streams", []):
            try:
                duration = max(duration, float(stream.get("duration") or 0.0))
            except (TypeError, ValueError):
                continue
    return {"duration": duration, "has_video": "video" in kinds,
            "has_audio": "audio" in kinds}


def probe_duration(file_path: str) -> float:
    """Giây THỰC của một file trên đĩa — con số duy nhất được phép báo cho
    người dùng, vì nó là thứ ffprobe đo sau khi ffmpeg đã tự khen mình xong."""
    return float(media_info(file_path).get("duration") or 0.0)


def keyframe_times(file_path: str, limit: int = 100000) -> list:
    """Giây trình diễn của mọi keyframe video, tang dan, khong trung.

    Doc mang packet thuan tuy (ffprobe khong giai ma) nen re, va chi la du
    phong: danh sach rong nghia la khong do duoc (audio thuan, container la,
    hoac ffprobe bi chan) va caller phai xu nhu khong rang buoc keyframe.
    """
    try:
        ffprobe = external_tools.find("ffprobe")
        if not ffprobe:
            return []
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0",
             file_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=KEYFRAME_TIMEOUT, check=False, **_window_flags())
        if result.returncode != 0:
            return []
        text = (result.stdout or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    found = set()
    for line in text.splitlines():
        fields = line.strip().split(",")
        if len(fields) < 2 or not fields[1].startswith("K"):
            continue
        try:
            seconds = float(fields[0])
        except ValueError:
            continue
        if seconds >= 0.0:
            found.add(round(seconds, 3))
        if len(found) >= limit:
            break
    return sorted(found)


def default_output_dir(file_path: str) -> str:
    """<ten video>_parts ngay canh file nguon."""
    return os.path.splitext(os.path.abspath(file_path))[0] + "_parts"


def unique_output_dir(file_path: str) -> str:
    """Lot sau không đè lot trước: doan trung ten thi file bi ghi de im lang."""
    folder = default_output_dir(file_path)
    if not os.path.isdir(folder):
        return folder
    index = 2
    while os.path.isdir("%s_%d" % (folder, index)):
        index += 1
    return "%s_%d" % (folder, index)


TIMECODE_SEPARATOR = re.compile(r"[;,\n\r]+")


def parse_timecode(text):
    """'12.5' / '0:45' / '1:02:03.5' -> giay; None neu khong doc duoc.

    Phut va gio phai la so nguyen: '1,5:30' khong ai nhap the, va neu cho
    thi no bi doc thanh mot con so khac han y nguoi dung.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) > 3:
        return None
    for lead in parts[:-1]:
        if not re.fullmatch(r"\d+", lead.strip()):
            return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    if any(value < 0 for value in values):
        return None
    seconds = 0.0
    for value in values:
        seconds = seconds * 60.0 + value
    return round(seconds, 3)


def parse_cut_points(text):
    """(moc tang dan khong trung, token doc khong ra) tu '0:05, 0:12; 1:00'.

    Tra ve ca danh sach loi de hop thoai in duoc ten tung token — im lang
    bo qua 'abc' thi nguoi dung tu hien tai sao so doan khong doi.
    """
    marks, bad = [], []
    for token in TIMECODE_SEPARATOR.split(str(text or "")):
        token = token.strip()
        if not token:
            continue
        seconds = parse_timecode(token)
        if seconds is None:
            bad.append(token)
        else:
            marks.append(seconds)
    return sorted(set(marks)), bad


def plan_boundaries(total_seconds, count=3, start=0.0, end=None):
    """N+1 bien cat cach deu nhau trong [start, end], tang dan chat che."""
    window = _window(total_seconds, start, end)
    if window is None:
        return []
    begin, stop = window
    wanted = max(1, min(int(count), MAX_SEGMENTS))
    while wanted > 1 and (stop - begin) / wanted < MIN_SEGMENT_SECONDS:
        wanted -= 1
    step = (stop - begin) / wanted
    points = [round(begin + i * step, 3) for i in range(wanted)]
    points.append(round(stop, 3))
    return points


def plan_boundaries_length(total_seconds, length_seconds, start=0.0, end=None):
    """Bien cat cach nhau dung `length_seconds`, doan cuoi mang phan du.

    Phan du khong bao gio bi vet: no ghep vao doan ke truoc, vi mot doan
    0,1 s la mot file khong ai xem ma van phai tra thoi gian cat. Khi so doan
    cham tran `MAX_SEGMENTS` thi buoc nhay bi keo dai ra, that bai theo huong
    doan dai hon yeu cau con hon la mat noi dung.
    """
    window = _window(total_seconds, start, end)
    if window is None:
        return []
    begin, stop = window
    span = stop - begin
    step = float(length_seconds or 0.0)
    if step < MIN_SEGMENT_SECONDS:
        return []
    step = max(step, span / MAX_SEGMENTS)
    wanted = int(math.ceil(span / step - 1e-6))
    if wanted < 1:
        return []
    points = [round(begin + i * step, 3) for i in range(wanted)]
    points.append(round(stop, 3))
    if len(points) > 2 and stop - points[-2] < MIN_SEGMENT_SECONDS:
        points.pop(-2)
    return points


def plan_boundaries_points(total_seconds, points, start=0.0, end=None):
    """Bien cat theo moc nguoi dung dat: [begin] + moc giu + [stop].

    Moc ngoai khoang, moc trung nhau hoac moc tao ra doan ngan hon
    `MIN_SEGMENT_SECONDS` bi loai im lang — ke hoach tra ve luon bat dau o
    `start` va ket thuc o `end`, nen mot con so nhap sai khong an hay doi
    duoc noi dung.
    """
    window = _window(total_seconds, start, end)
    if window is None:
        return []
    begin, stop = window
    kept = [round(begin, 3)]
    for value in sorted(float(point) for point in (points or [])):
        if value <= begin or value >= stop:
            continue
        if value - kept[-1] < MIN_SEGMENT_SECONDS:
            continue
        kept.append(round(value, 3))
    if len(kept) > 1 and stop - kept[-1] < MIN_SEGMENT_SECONDS:
        kept.pop()
    kept.append(round(stop, 3))
    return kept


def build_boundaries(total_seconds, count=3, length=None, points=None,
                     start=0.0, end=None):
    """Ba kieu cat quy ve MOT danh sach bien: deu nhau / doi dai co dinh / moc tu dat.

    `points` thang la kieu manh nhat (no dinh so doan), den `length`, cuoi
    cung moi den `count` — moi lan goi chi nen dung mot trong ba.
    """
    if points is not None:
        return plan_boundaries_points(total_seconds, points, start, end)
    if length:
        return plan_boundaries_length(total_seconds, length, start, end)
    return plan_boundaries(total_seconds, count, start, end)


def _window(total_seconds, start, end):
    """(begin, stop) da guoc ve [0, total] va con rong; None neu khong cat duoc."""
    total = max(0.0, float(total_seconds or 0.0))
    if total <= 0:
        return None
    begin = min(max(0.0, float(start)), total)
    stop = total if end is None else min(max(begin, float(end)), total)
    if stop - begin <= 0:
        return None
    return begin, stop


def plan_segments(total_seconds, count=3, start=0.0, end=None, length=None,
                  points=None):
    """[(bat_dau, do_dai)] — phan TOAN hoc thuan cua ke hoach, chua co rang
    buoc keyframe. `split_media()` moi la noi alignment xay ra."""
    marks = build_boundaries(total_seconds, count, length, points, start, end)
    return [(marks[i], round(marks[i + 1] - marks[i], 3))
            for i in range(len(marks) - 1)]


def align_boundaries(points, keyframes, tolerance=COPY_DRIFT_TOLERANCE):
    """Ke hoach cat KHONG CHONG LAP va KHONG MAT NOI DUNG tu cac bien deu nhau.

    Moi bien duoc keo ve keyframe cuoi cung nam TRUOC no: doan truoc do ket
    thuc dung tai do (cat o duoi ket luon an toan, cat o dau moi giua chung
    moi hong), nen hai doan khong con replay cung mot noi dung. Bien khong neo
    duoc — lech hon `tolerance`, hoac khong co keyframe nao phia ben trai — thi
    danh cờ `encode` cho doan BAT DAU tai do va giu nguyen vi tri chinh xac.

    Bien CUOI khong bao gio keo lui: keo no ve keyframe la cat bo phan duoi
    tran cua file, mat noi dung con hon la lech doi ti so.

    `keyframes` rong = khong rang buoc (audio thuan, hoac do khong ra
    keyframe): moi bien gi nguyen, copy ca.

    Hai bien keo ve cung mot keyframe thi doan giua rong bang 0 — bien sau bi
    loai, tuc la khong the co nhieu doan copy hon so keyframe an toan.
    """
    if len(points) < 2:
        return []
    marks = [float(value) for value in points]
    encode_start = [False] * len(marks)
    last = len(marks) - 1
    if keyframes:
        for index, value in enumerate(marks):
            if index == last:
                break
            position = bisect.bisect_right(keyframes, value + 1e-6) - 1
            snapped = float(keyframes[position]) if position >= 0 else None
            if snapped is None or value - snapped > float(tolerance):
                encode_start[index] = True
            else:
                marks[index] = snapped
    kept = []
    kept_encode = []
    for index, value in enumerate(marks):
        if kept and value <= kept[-1] + 1e-6:
            continue
        kept.append(value)
        kept_encode.append(encode_start[index])
    if len(kept) < 2:
        return []
    return [{"start": round(kept[index], 3),
             "span": round(kept[index + 1] - kept[index], 3),
             "encode": bool(kept_encode[index])}
            for index in range(len(kept) - 1)]


def segment_name(source_path: str, index: int, total: int) -> str:
    """part của chính file nguồn, giữ nguyên đuôi để -c copy còn xài được."""
    stem = os.path.splitext(os.path.basename(source_path))[0]
    digits = max(2, len(str(max(1, int(total)))))
    return "%s_part%0*d%s" % (stem, digits, int(index),
                              os.path.splitext(source_path)[1] or ".mp4")


def _run(args, timeout=FFMPEG_TIMEOUT):
    """(rc, thong_bao_loi). Khong bao gio noi: loi cua ffmpeg phai tra ve
    duoc cho hop thoai in ra, neu khong nguoi dung chi thay 'that bai'."""
    try:
        result = subprocess.run(args, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=timeout,
                                check=False, **_window_flags())
        return result.returncode, (result.stderr or b"").decode(
            "utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


def _encode_args(output_path: str, info: dict) -> list:
    """Co dinh codec cho container pho bien de may cau hinh thap chay duoc
    preset veryfast; container khac de ffmpeg tu theo le cua no."""
    if not info.get("has_video"):
        return []
    if os.path.splitext(output_path)[1].lower() not in X264_CONTAINERS:
        return []
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]


def cut_segment(source_path, output_path, start, span, info, encode=False):
    """Cat mot doan; tra {"mode", "duration", "error"}.

    `mode` la "copy" hay "encode" THE THAT, khong phai che do duoc yeu cau:
    copy xong ma ffprobe do dai lech qua `tolerance` thi doan ay duoc ma hoa
    lai ngay tai cho, va ke hoach duoc bao ve la "copy" chi khi so do kiem
    chung duoc.
    """
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        # Loi nay phai den duoc nguoi dung nhu MOT dong "thieu ffmpeg", khong
        # phai vo so doan that bai vi ly do khong ai doc duoc.
        return {"mode": None, "duration": 0.0,
                "error": external_tools.missing_message("ffmpeg")}
    base = [ffmpeg, "-v", "error", "-y", "-ss", "%.3f" % max(0.0, float(start)),
            "-i", source_path, "-t", "%.3f" % max(0.001, float(span))]
    error = ""
    if not encode:
        rc, error = _run(base + ["-c", "copy", "-avoid_negative_ts",
                                 "make_zero", output_path])
        actual = probe_duration(output_path) if rc == 0 else 0.0
        if rc == 0 and abs(actual - float(span)) <= COPY_OVERSHOOT_TOLERANCE:
            return {"mode": "copy", "duration": actual, "error": ""}
        if rc != 0:
            error = error or "ffmpeg -c copy that bai"
    rc, encode_error = _run(base + _encode_args(output_path, info)
                            + ["-movflags", "+faststart", output_path])
    actual = probe_duration(output_path) if rc == 0 else 0.0
    if rc == 0 and actual > 0:
        return {"mode": "encode", "duration": actual, "error": ""}
    return {"mode": None, "duration": actual,
            "error": encode_error or error or "ffmpeg khong tra ve file nao"}


def split_media(file_path, output_dir, count=3, start=0.0, end=None,
                mode=MODE_AUTO, progress=None, should_cancel=None,
                length=None, points=None):
    """Cat toan bo (hoac mot khoang) file ra N doan.

    `count`, `length`, `points` la ba cach NOI CUNG MOT DIEU — bien cat deu
    nhau, doan dai co dinh, moc tu dat (xem `build_boundaries`); `points` thang
    quyet khi duoc dua vao.

    Tra ve {"segments", "failed", "cancelled", "planned", "duration", "mode"}:
    `segments` chi chua file THAT su ton tai tren dia va ffprobe doc duoc, moi
    phan tu co {"path","start","span","actual","mode"} — `actual` la giay do
    ffprobe đo lai, khong phai giay ffmpeg tu bao.

    Huy giua chung co hieu luc GIUA HAI DOAN: ffmpeg dang chay thi de no xong
    doan ay, vi giua lieu dung thu tuc cat giua chung se de lai file doi.
    """
    info = media_info(file_path)
    total = float(info.get("duration") or 0.0)
    result = {"segments": [], "failed": [], "cancelled": False,
              "planned": [], "duration": total, "source": file_path,
              "mode": mode}
    if total <= 0 or not (info.get("has_video") or info.get("has_audio")):
        return result
    plan_points = build_boundaries(total, count, length, points, start, end)
    frames = keyframe_times(file_path) if info.get("has_video") else []
    if mode == MODE_ENCODE:
        plan = [{"start": round(point, 3),
                 "span": round(plan_points[index + 1] - point, 3),
                 "encode": True}
                for index, point in enumerate(plan_points[:-1])
                if plan_points[index + 1] - point > 0]
    else:
        plan = align_boundaries(plan_points, frames)
    result["planned"] = plan
    if not plan:
        return result
    os.makedirs(output_dir, exist_ok=True)
    for position, row in enumerate(plan, start=1):
        if should_cancel is not None and should_cancel():
            result["cancelled"] = True
            break
        output_path = os.path.join(output_dir,
                                   segment_name(file_path, position, len(plan)))
        outcome = cut_segment(file_path, output_path, row["start"], row["span"],
                              info, encode=row["encode"])
        record = {"path": output_path, "start": row["start"],
                  "span": row["span"], "actual": outcome["duration"],
                  "mode": outcome["mode"]}
        if outcome["mode"] is None or not os.path.isfile(output_path):
            result["failed"].append(record)
        else:
            result["segments"].append(record)
        if progress is not None:
            progress(position, len(plan), record)
    return result
