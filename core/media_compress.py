"""
core/media_compress.py

Nen / toi uu MOT file video da co tren dia, khong lien quan den timeline.

Khac `core.media_splitter`: do ay cat file ra nhieu doan, con o day giu
nguyen noi dung va chi thay cach dong goi no. Hai duong chung mot triet ly cua
repo: moi con so bao cho nguoi dung (thoi luong, so byte) do ffprobe va stat
DO LAI sau khi ffmpeg da tu khen minh xong.

Bon kieu, tang dan ve thoi gian chay (do tren may nay, xem
`SECONDS_PER_SOURCE_SECOND`):

* `remux` — khong ma hoa lai, chi copy luong va day moov len dau file mp4.
  Gan nhu mien phi CPU, hop voi may cau hinh thap nhat.
* `x264` — ma hoa lai H.264, CRF nguoi dung chon.
* `x265` — HEVC, nhe hon nhung CPU nhieu lan hon.
* `vp9` — WebM, mo va khong bang sang che; codec do container chut, khong do
  nguoi dung chon.

Cong thuc lay tu compressO (github.com/codeforreal1/compressO, `ffmpeg.rs`):
thang CRF tu chat luong 0..100, quy tac "codec nao nam duoc trong container
nao" va cac cờ `-b:v 0` / `-movflags +faststart`. Ba thu nghiep duoc bao lai
bang so that thay vi port nguyen van — xem `pair_error`, `PRESETS_OF` va
`DEFAULT_PRESET`.

Vi sao phai doc stdout cua ffmpeg chu khong de hai PIPE rieng: tien trinh chi
doc mot luong thi luong con lai day bot dem va ffmpeg dung chay giua chung. O day
gop stderr vao stdout, va duong tien trinh lay tu dong `out_time_*` ma chinh
ffmpeg in ra — khong do byte, khong suy ra ti le.
"""

from __future__ import annotations

import os
import subprocess

from core import external_tools
from core.media_splitter import media_info

# ffmpeg/ffprobe khong duoc phep nhay cua so den len tren may Windows.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

MODE_REMUX = "remux"
MODE_X264 = "x264"
MODE_X265 = "x265"
MODE_VP9 = "vp9"
MODES = (MODE_REMUX, MODE_X264, MODE_X265, MODE_VP9)

MODE_LABELS = {
    MODE_REMUX: "Tối ưu không mất chất (copy luồng)",
    MODE_X264: "Nén H.264 (tương thích rộng)",
    MODE_X265: "Nén HEVC / H.265 (nhẹ hơn)",
    MODE_VP9: "Nén VP9 (WebM, mở và không bằng sáng chế)",
}

ENCODER_OF = {MODE_X264: "libx264", MODE_X265: "libx265", MODE_VP9: "libvpx-vp9"}

# Container mà cờ `+faststart` có nghĩa; ngoài danh sách này việc đặt moov ở
# đầu thuộc về muxer, ép cờ chỉ sinh lỗi "not an MP4 file".
FASTSTART_CONTAINERS = (".mp4", ".mov", ".m4v")

# Công thức của compressO (`ffmpeg.rs:209-260`): codec nào được nằm trong
# container nào do container quyết định, không do người dùng chọn. Phép đo
# 21/10/2026 định nghĩa lại lỗi này bằng thật: `-c:v libx264` ghi ra `.webm`
# thì ffmpeg bật ra rc=4294967274 (-22) sau 0,2 s và không để lại file đọc
# được. Bảng theo TOKEN vì ffprobe và ffmpeg gọi hai tên khác nhau cho cùng
# một codec (`h264`/`libx264`, `hevc`/`libx265`); `None` = mkv nhận hết.
CONTAINER_CODECS = {
    ".mp4": ("264", "265", "hevc", "av1"),
    ".mov": ("264", "265", "hevc", "av1"),
    ".m4v": ("264", "265", "hevc", "av1"),
    ".webm": ("vp8", "vp9", "av1"),
    ".mkv": None,
}

# Đuôi chuẩn cho từng kiểu: chọn VP9 mà vẫn giữ đuôi nguồn thì tổ hợp trên
# chắc chắn lỗi, nên gợi ý file phải đổi đuôi luôn.
MODE_EXTENSION = {MODE_VP9: ".webm"}

# CRF 20/22 là ngưỡng "nhìn không ra khác" mà `media_splitter` đã dùng từ
# bản 1.0.3; đặt thấp hơn nữa thì người dùng phải tự chịu thời gian.
# compressO dùng thang 24..36 (chât luong 0..100) — khong bao gio dat CRF 20,
# nen giu thang cua repo va bao cao lech trong docs/verification-gates.md.
CRF_MIN = 16
CRF_MAX = 35
DEFAULT_CRF = {MODE_X264: 20, MODE_X265: 22, MODE_VP9: 33}

# Preset la tham so cua libx26x; libvpx-vp9 KHONG nhan `-preset` (ffmpeg bao
# "Invalid preset") ma nhan `-cpu-used` — nen moi kieu phai co thang rieng.
# Do tren may nay 21/10/2026 (8 CPU logich, ffmpeg dong goi, fixture lavfi
# 6 s 1280x720 nguon x264 CRF 23 1.951.137 B, CRF 28): ultrafast 1,45 s nhung
# file ra 3.115.218 B = NANG HON nguon 59,7%; veryfast 2,59 s / 819.239 B;
# fast 4,67 s / 926.532 B; medium 4,66 s / 895.248 B; slow 7,02 s / 905.301 B.
# Nen `slow` (preset "ironclad" cua compressO) dat them 2,35 s chi de doi lech
# 21 KB khong dang — va `veryfast` trung voi `media_splitter` da ban 1.0.3.
PRESETS = ("ultrafast", "veryfast", "faster", "fast", "medium", "slow")
VP9_CPU_USED = ("1", "2", "4", "5", "8")
PRESETS_OF = {MODE_X264: PRESETS, MODE_X265: PRESETS, MODE_VP9: VP9_CPU_USED}
DEFAULT_PRESET = {MODE_X264: "veryfast", MODE_X265: "veryfast", MODE_VP9: "5"}

# vp9 bắt buộc có `-b:v 0` khi chạy CRF: thiếu nó thì muxer áp trần bitrate
# và file ra lớn hơn nhiều lần so với CRF đã chọn.
VP9_FLAGS = ("-b:v", "0", "-row-mt", "1")

# GIÂY THẬT / GIÂY VIDEO do tren dung may nay (cung fixture nhu block tren, moi
# cau hinh chay LEN KE nhau trong mot vong): x264 veryfast 2,59 s, x265 veryfast
# 12,29 s, vp9 cpu-used 5 26,45 s cho 6 s 720p. Day la thang do de nguoi dung
# may cau hinh thap biet truoc minh se choi gi — khong phai so tham khao tai lieu.
SECONDS_PER_SOURCE_SECOND = {MODE_X264: 0.43, MODE_X265: 2.05, MODE_VP9: 4.41}

AUDIO_KBIT = "160k"
PROBE_TIMEOUT = 15.0
TERMINATE_GRACE = 5.0
NOISE_KEPT = 40

# Những khóa ffmpeg in ra lúc chạy — không phải lỗi, không đưa vào nhật ký.
_PROGRESS_KEYS = ("out_time_us=", "out_time_ms=", "out_time=", "frame=",
                  "fps=", "bitrate=", "speed=", "progress=", "stream_")

_ENCODER_CACHE = {}


def _extension(path: str) -> str:
    return (os.path.splitext(path or "")[1] or "").lower()


def fits_container(name: str, extension: str) -> bool:
    """Codec/encoder `name` có được phép nằm trong container `extension` không.

    So bằng TOKEN vì ffprobe trả `h264`/`hevc`/`vp9` còn ffmpeg lại nhận
    `libx264`/`libx265`/`libvpx-vp9` — một bảng tên đầy đủ sẽ sai ở đúng chỗ
    mà compressO cũng sai (bản gốc của họ chỉ dò "264"/"265" nên quên `hevc`).
    """
    allowed = CONTAINER_CODECS.get(extension)
    if allowed is None or not name:
        return True
    return any(token in name for token in allowed)


def container_choices(mode: str) -> list:
    """Những đuôi mà kiểu `mode` ghi được — cùng một bảng mà `pair_error` đọc."""
    name = ENCODER_OF.get(mode, "")
    return sorted(ext for ext, tokens in CONTAINER_CODECS.items()
                  if not tokens or fits_container(name, ext))


def encoder_present(name: str, ffmpeg: str = "") -> bool:
    """Bản ffmpeg đang dùng có mã hóa được codec này không — hỏi chính nó.

    Cache theo đường dẫn: `external_tools` có thể trả bản bundle hoặc một bản
    PATH khác nhau, và hai bản không chắc có cùng codec.
    """
    ffmpeg = ffmpeg or external_tools.find("ffmpeg") or ""
    if not ffmpeg:
        return False
    key = (os.path.normcase(ffmpeg), name)
    cached = _ENCODER_CACHE.get(key)
    if cached is not None:
        return cached
    found = False
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT, check=False, creationflags=NO_WINDOW)
        for line in (result.stdout or b"").decode("utf-8", "replace").splitlines():
            # Dong du dang ` V....D libx264   <mo ta>`: cot 0 la bit mask cua
            # loai, cot 1 la TEN codec. Dong "V..... = Video" cua gia thieu le
            # cung bat dau bang V, nen phai so sinh dung ten moi du.
            fields = line.split()
            if len(fields) >= 2 and fields[1] == name:
                found = True
                break
    except (OSError, subprocess.SubprocessError):
        found = False
    _ENCODER_CACHE[key] = found
    return found


def source_video_codec(file_path: str) -> str:
    """Tên codec của DẢI VIDEO đầu tiên — `h264`, `hevc`, `vp9`, hoặc "".

    `remux` copy từng bit nên container kết quả phải chứa được codec của
    NGUỒN; không có con số này thì `pair_error` chỉ kiểm được chiều ngược lại
    (encoder do người dùng chọn).
    """
    ffprobe = external_tools.find("ffprobe")
    if not ffprobe or not os.path.isfile(file_path):
        return ""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT, check=False, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    lines = (result.stdout or b"").decode("utf-8", "replace").splitlines()
    return lines[0].strip().lower() if lines else ""


def source_facts(file_path: str) -> dict:
    """Kích thước + thời lượng do ffprobe đo; tồn tại thật trên đĩa."""
    path = os.path.abspath(file_path or "")
    facts = {"path": path, "exists": os.path.isfile(path), "bytes": 0,
             "duration": 0.0, "has_video": False, "has_audio": False,
             "video_codec": "", "extension": _extension(path)}
    if not facts["exists"]:
        return facts
    info = media_info(path)
    facts["duration"] = float(info.get("duration") or 0.0)
    facts["has_video"] = bool(info.get("has_video"))
    facts["has_audio"] = bool(info.get("has_audio"))
    facts["video_codec"] = source_video_codec(path)
    try:
        facts["bytes"] = os.path.getsize(path)
    except OSError:
        pass
    return facts


def suggest_output(file_path: str, mode: str) -> str:
    """File kết quả ngay cạnh file nguồn, ĐỔI đuôi nếu container nguồn không
    nhận codec của kiểu đã chọn.

    Không ghi đè nguồn: hỏng giữa lúc chạy thì nguồn còn nguyên vẹn.
    """
    source = os.path.abspath(file_path or "")
    stem = os.path.splitext(source)[0]
    extension = MODE_EXTENSION.get(mode) or _extension(source) or ".mp4"
    candidate = "%s_%s%s" % (stem, mode, extension)
    index = 2
    while os.path.exists(candidate):
        candidate = "%s_%s_%d%s" % (stem, mode, index, extension)
        index += 1
    return candidate


def pair_error(output_path: str, mode: str, source_codec: str = "") -> str:
    """Kiểm tra kiểu nén có ghi được vào container của `output_path` không.

    Trả về lời nói để hiển thị, hoặc "" khi hợp lệ. Đây là bản Python của
    `is_codec_compatible` trong compressO — giữ lại vì nó chặn LỆNH chứ không
    chặn codec: cùng một kiểu x264 hợp lệ với `.mp4` nhưng vô nghĩa với
    `.webm`, và lỗi thật thì ffmpeg chỉ báo một mã số không đọc được.
    `remux` không chọn encoder nên phải dò codec của NGUỒN (`source_codec`);
    thiếu con số đó thì hàm trả "" — kiểm được một chiều vẫn hơn giả vờ kiểm
    được hai chiều.
    """
    extension = _extension(output_path)
    if CONTAINER_CODECS.get(extension) is None:
        return ""
    if mode == MODE_REMUX:
        if not source_codec or fits_container(source_codec, extension):
            return ""
        return ("Bản gốc là %s, không nằm trong file %s — chọn kiểu nén lại "
                "hoặc giữ đuôi cũ." % (source_codec, extension))
    encoder = ENCODER_OF.get(mode, "")
    if fits_container(encoder, extension):
        return ""
    return ("Kiểu %s không ghi được vào file %s — chỉ %s." %
            (MODE_LABELS.get(mode, mode), extension or "?",
             ", ".join(container_choices(mode))))


def estimate_seconds(mode: str, duration: float) -> float:
    """Uoc luong giay that cho `duration` giay video — nhan he so DO may nay.

    `remux` tra 0,0 vi copy luong chi tra phi doc/ghi. khong ma hoa.
    """
    if mode == MODE_REMUX:
        return 0.0
    factor = SECONDS_PER_SOURCE_SECOND.get(mode)
    if factor is None or float(duration or 0.0) <= 0:
        return 0.0
    return float(duration) * factor


def build_command(ffmpeg, source, output, mode, crf=None, preset=None,
                  has_audio=True, keep_metadata=True) -> list:
    """Lệnh ffmpeg đầy đủ cho một kiểu nén — hàm thuần, không chạy gì.

    Tùy chọn phải đứng TRƯỚC tên file xuất: đặt sau, ffmpeg hiểu nhầm đó là
    tùy chọn của một đầu vào tiếp theo và lặng lẽ bỏ qua.
    """
    if mode not in MODES:
        raise ValueError("Kiểu nén không hợp lệ: %s" % mode)
    incompatible = pair_error(output, mode)
    if incompatible:
        raise ValueError(incompatible)
    command = [ffmpeg, "-v", "error", "-hide_banner", "-nostdin", "-y",
               "-i", source]
    extension = _extension(output)
    if mode == MODE_REMUX:
        command += ["-map", "0", "-c", "copy"]
        if keep_metadata:
            command += ["-map_metadata", "0", "-map_chapters", "0"]
            if extension in FASTSTART_CONTAINERS:
                command += ["-movflags", "+faststart"]
        else:
            command += ["-map_metadata", "-1", "-map_chapters", "-1"]
    else:
        choices = PRESETS_OF[mode]
        chosen_crf = int(DEFAULT_CRF[mode] if crf is None else crf)
        chosen_preset = preset if preset in choices else DEFAULT_PRESET[mode]
        command += ["-map", "0:v:0?", "-map", "0:a:0?"]
        if extension == ".mkv":
            # Phụ đề văn bản chỉ sống được trong mkv; ép mov_text vào mkv thì
            # ffmpeg báo lỗi codec khó hiểu ngay ở dòng cuối log.
            command += ["-map", "0:s?", "-c:s", "copy"]
        command += ["-c:v", ENCODER_OF[mode]]
        if mode == MODE_VP9:
            # `-preset` la cua libx26x; vp9 khong hieu nen ep no vao thi
            # ffmpeg bao "Invalid preset" — do luong + row-mt thay the.
            command += ["-cpu-used", chosen_preset] + list(VP9_FLAGS)
        else:
            command += ["-preset", chosen_preset]
        command += ["-crf", str(min(CRF_MAX, max(CRF_MIN, chosen_crf))),
                    "-pix_fmt", "yuv420p"]
        if extension == ".webm":
            # AAC bị webm muxer từ chối; Opus là codec duy nhất trong chuẩn
            # này mà bản ffmpeg đóng gói của repo cũng có sẵn.
            command += (["-c:a", "libopus", "-b:a", AUDIO_KBIT] if has_audio
                        else ["-an"])
        else:
            command += (["-c:a", "aac", "-b:a", AUDIO_KBIT] if has_audio
                        else ["-an"])
        if extension == ".mp4" and mode == MODE_X265:
            # Tag `hvc1` (không phải `hev1`) là thứ QuickTime và trình phát
            # Windows chịu mở; thiếu nó thì file nén xong vẫn không phát được.
            command += ["-tag:v", "hvc1"]
        command += (["-map_metadata", "0"] if keep_metadata
                    else ["-map_metadata", "-1"])
        if extension in FASTSTART_CONTAINERS:
            command += ["-movflags", "+faststart"]
    command += ["-progress", "pipe:1", "-nostats", output]
    return command


def _percent(seconds: float, duration: float) -> int:
    if duration <= 0:
        return -1
    return max(0, min(99, int(seconds / duration * 100.0)))


def read_progress(line: str, duration: float) -> int:
    """Phần trăm từ một dòng ffmpeg; -1 nếu dòng đó không phải mốc thời gian.

    ffmpeg 9 in `out_time_us`, bản cũ hơn in `out_time_ms` (cùng đơn vị micro
    giây, chỉ tên đổi), bản cũ nữa in `out_time=` dạng `H:M:S.ms`. Bỏ sót một
    dạng là mất thanh tiến trình trên đúng bản ffmpeg người dùng đang cài.
    """
    if line.startswith(("out_time_us=", "out_time_ms=")):
        try:
            return _percent(int(line.split("=", 1)[1]) / 1_000_000.0, duration)
        except ValueError:
            return -1
    if line.startswith("out_time="):
        fields = line.split("=", 1)[1].split(":")
        if len(fields) != 3:
            return -1
        try:
            return _percent(int(fields[0]) * 3600 + int(fields[1]) * 60
                            + float(fields[2]), duration)
        except ValueError:
            return -1
    return -1


def top_level_atoms(path: str) -> list:
    """[(ten, bo_cuc_dau)] cua cac atom goc trong mot file fMP4/MP4.

    Day la thu duy nhat chung minh `+faststart` that co tac dung: mot file van
    mo binh thuong du cho du moov nam cuoi. Doc header 8 byte la du — khong
    can mo hinh, khong can thu vien nao.
    """
    found = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            offset = 0
            while offset + 8 <= size:
                handle.seek(offset)
                header = handle.read(8)
                if len(header) < 8:
                    break
                length = int.from_bytes(header[:4], "big")
                name = header[4:8].decode("latin-1")
                if length == 1:
                    extended = handle.read(8)
                    if len(extended) < 8:
                        break
                    length = int.from_bytes(extended, "big")
                elif length == 0:
                    length = size - offset
                if length < 8:
                    break
                found.append((name, offset))
                offset += length
    except OSError:
        return []
    return found


def is_faststart(path: str) -> bool:
    """moov nam TRUOC mdat — dieu kien de trinh duyet phat duoc khi moi tai."""
    positions = {}
    for name, offset in top_level_atoms(path):
        positions.setdefault(name, offset)
    if "moov" not in positions or "mdat" not in positions:
        return False
    return positions["moov"] < positions["mdat"]


def _stop(process):
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass


def _drop(path):
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def compress_file(source_path, output_path, mode=MODE_REMUX, crf=None,
                  preset=None, progress=None, should_cancel=None):
    """Nén một file; trả về số đo THẬT, không phải lời ffmpeg tự nhận.

    {"ok", "cancelled", "output", "mode", "input_bytes", "output_bytes",
     "saved_bytes", "ratio", "duration_in", "duration_out", "error"}

    `ok` chỉ True khi file kết quả tồn tại trên đĩa, ffprobe đọc lại được và
    có ít nhất một dải video hoặc audio. Thất bại thì file dở bị xóa: để lại
    nó là để lại một rác mang đuôi `.mp4` mà không phần mềm nào mở được.
    """
    result = {"ok": False, "cancelled": False, "output": output_path,
              "mode": mode, "input_bytes": 0, "output_bytes": 0,
              "saved_bytes": 0, "ratio": 0.0, "duration_in": 0.0,
              "duration_out": 0.0, "error": ""}
    facts = source_facts(source_path)
    result["input_bytes"] = facts["bytes"]
    result["duration_in"] = facts["duration"]
    if not facts["exists"]:
        result["error"] = "Không tìm thấy file nguồn."
        return result
    if mode not in MODES:
        result["error"] = "Kiểu nén không hợp lệ: %s" % mode
        return result
    if os.path.abspath(output_path) == facts["path"]:
        result["error"] = "File kết quả trùng file nguồn."
        return result
    incompatible = pair_error(output_path, mode, facts.get("video_codec", ""))
    if incompatible:
        # Chặn ở đây để `build_command` không bao giờ raise giữa lúc chạy, và
        # để người dùng đọc được câu thay vì mã lỗi -22 của ffmpeg.
        result["error"] = incompatible
        return result
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        result["error"] = external_tools.missing_message("ffmpeg").splitlines()[0]
        return result
    encoder = ENCODER_OF.get(mode)
    if encoder and not encoder_present(encoder, ffmpeg):
        result["error"] = "Bản ffmpeg đang dùng không có %s." % encoder
        return result

    command = build_command(ffmpeg, facts["path"], output_path, mode,
                            crf=crf, preset=preset,
                            has_audio=facts["has_audio"])
    result["command"] = command
    process = None
    noise = []
    try:
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        except OSError as exc:
            result["error"] = "Không tạo được thư mục: %s" % exc
            return result
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=NO_WINDOW)
        for raw in iter(process.stdout.readline, ""):
            line = raw.strip()
            if not line:
                continue
            if should_cancel is not None and should_cancel():
                _stop(process)
                _drop(output_path)
                result["cancelled"] = True
                result["error"] = "Đã hủy."
                return result
            percent = read_progress(line, facts["duration"])
            if percent >= 0:
                if progress is not None:
                    progress(percent)
            elif not line.startswith(_PROGRESS_KEYS):
                noise.append(line)
                del noise[:-NOISE_KEPT]
        process.stdout.close()
        code = process.wait()
        if should_cancel is not None and should_cancel():
            _drop(output_path)
            result["cancelled"] = True
            result["error"] = "Đã hủy."
            return result
        if code != 0:
            _drop(output_path)
            result["error"] = ("\n".join(noise[-6:]).strip()
                               or "ffmpeg kết thúc với mã lỗi %d" % code)
            return result
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if process is not None:
            _stop(process)
        _drop(output_path)
        result["error"] = str(exc) or exc.__class__.__name__
        return result
    finally:
        if process is not None and process.poll() is None:
            _stop(process)

    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        _drop(output_path)
        result["error"] = "ffmpeg xong nhưng không để lại file nào."
        return result
    info = media_info(output_path)
    if not (info.get("has_video") or info.get("has_audio")):
        _drop(output_path)
        result["error"] = "File kết quả không có dải nào đọc được."
        return result
    result["output_bytes"] = os.path.getsize(output_path)
    result["duration_out"] = float(info.get("duration") or 0.0)
    result["saved_bytes"] = result["input_bytes"] - result["output_bytes"]
    result["ratio"] = (result["output_bytes"] / float(result["input_bytes"])
                       if result["input_bytes"] else 0.0)
    result["ok"] = True
    if progress is not None:
        progress(100)
    return result
