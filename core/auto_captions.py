"""
core/auto_captions.py
Nhận dạng giọng nói -> phụ đề có mốc thời gian, rồi đưa lên Timeline.

Engine đã vendor ở src/asr (AsrTools / bk_asr). Mọi hàm ở đây chạy được ngoài
thread GUI: không chạm widget nào, chỉ nhận callback tiến độ và trả dữ liệu thô.
"""

import os
import subprocess
import tempfile

from core import external_tools
from core.timeline_model import TrackType

# Engine nào thực sự trả lời được đo trên dịch vụ thật: Bcut nhận tiếng,
# JianYing trả task id rỗng, KuaiShou báo bị vô hiệu hoá.
#
# "Faster Whisper (local)" đã bị loại: nó kéo theo faster_whisper +
# ctranslate2 + onnxruntime + av (~193 MB) vào bundle để đổi lấy một engine
# vẫn phải tải model qua mạng lần chạy đầu, tức chẳng hề cục bộ như tên gọi.
ENGINES = ("Bcut (Bilibili)", "JianYing (CapCut)")
FORMATS = ("SRT", "ASS", "TXT", "VTT")

# Đám mây chỉ đọc được mấy dạng này; còn lại phải tách audio trước.
NATIVE_FORMATS = ("mp3", "wav", "m4a", "flac")

DEFAULT_STYLE = {
    "font_family": "Arial",
    "font_size": 56.0,
    "font_bold": True,
    "font_color": "#FFFFFF",
    "text_effect": "none",
    "text_effect_intensity": 0.6,
}


def asr_module():
    import src.asr as asr
    return asr


def ffmpeg_path():
    """Đường dẫn ffmpeg thật — bản đi kèm trong bundle thắng PATH."""
    return external_tools.find("ffmpeg")


def needs_audio_conversion(media_path):
    ext = str(media_path).rsplit(".", 1)[-1].lower() if "." in str(media_path) else ""
    return ext not in NATIVE_FORMATS


def extract_audio(media_path):
    """Trả về file mp3 16 kHz mono để upload; file gốc nếu đã là định dạng thô."""
    if not needs_audio_conversion(media_path):
        return media_path
    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError(external_tools.missing_message("ffmpeg"))
    work_dir = os.path.join(tempfile.gettempdir(), "clinging_asr")
    os.makedirs(work_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(media_path))[0][:40] or "audio"
    out_path = os.path.join(work_dir, "%s_%d.mp3" % (stem, abs(hash(media_path)) % 10 ** 8))
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    cmd = [exe, "-y", "-i", media_path, "-vn", "-ac", "1", "-ar", "16000",
           "-f", "mp3", "-q:a", "4", out_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        detail = (result.stderr or "").strip().splitlines()
        raise RuntimeError("Không tách được âm thanh: " +
                           (detail[-1] if detail else "ffmpeg thất bại"))
    return out_path


def transcribe(media_path, engine=ENGINES[0], progress=None):
    """Một file media -> [{text, start_ms, end_ms}]. progress(percent, message).

    Không có tham số ngôn ngữ: cả hai engine đám mây tự nhận tiếng trong audio,
    chọn ngôn ngữ chỉ là một control không nối vào đâu.
    """
    if progress is None:
        progress = lambda *_: None
    if not media_path or not os.path.exists(media_path):
        raise RuntimeError("Không tìm thấy tệp nguồn để nhận dạng.")

    asr = asr_module()
    audio_path = extract_audio(media_path)

    progress(12, "Đang upload âm thanh lên %s..." % engine)
    try:
        data = asr.engine_class(engine)(audio_path, use_cache=True).run()
    except Exception as exc:
        raise RuntimeError("%s không nhận dạng được tệp này: %s"
                           % (engine, exc or exc.__class__.__name__)) from exc
    progress(88, "Đang đọc bản ghi...")
    segments = asr.to_segments(data)
    if not segments:
        raise RuntimeError(
            "%s không tìm thấy tiếng nói nào. Thử engine khác hoặc kiểm tra "
            "kênh âm thanh của tệp." % engine)
    return segments


def write_subtitle(segments, out_path):
    """Đoạn thẳng -> file phụ đề, phần mở rộng quyết định định dạng."""
    asr = asr_module()
    data = asr.ASRData([asr.ASRDataSeg(s["text"], s["start_ms"], s["end_ms"])
                        for s in segments])
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".ass":
        text = data.to_ass()
    elif ext == ".txt":
        text = data.to_txt()
    elif ext == ".vtt":
        text = "WEBVTT" + chr(10) + chr(10) + data.to_srt().replace(",", ".")
    else:
        text = data.to_srt()
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return out_path


def read_subtitle(path):
    """File .srt/.ass/.vtt -> cùng dạng segment như engine trả về."""
    asr = asr_module()
    return asr.to_segments(asr.from_subtitle_file(path))


def caption_track(model):
    """Track chữ đầu tiên, tạo mới nếu dự án chưa có."""
    for track in model.tracks:
        if track.track_type == TrackType.TEXT:
            return track
    return model.add_track(TrackType.TEXT, "Phụ đề")


def style_caption_clip(clip, style=None, canvas=(1920, 1080)):
    """Áp kiểu và đặt khối chữ vào đáy khung hình (transform tính từ tâm)."""
    merged = dict(DEFAULT_STYLE)
    merged.update(style or {})
    for key, value in merged.items():
        if key in ("x", "y"):
            continue
        setattr(clip, key, value)
    canvas_w, canvas_h = canvas
    clip.transform.x = 0.0
    clip.transform.y = canvas_h / 2.0 - 140.0
    clip.transform.rotation = 0.0
    clip.transform.scale_x = 1.0
    clip.transform.scale_y = 1.0
    return clip


def _canvas_size(model):
    from core.canvas_utils import ASPECT_RATIOS
    return ASPECT_RATIOS.get(getattr(model, "project_ratio", "16:9"), (1920, 1080))


def insert_captions(model, segments, style=None):
    """Chèn trực tiếp vào model (không qua undo) — trả về list clip."""
    track = caption_track(model)
    canvas = _canvas_size(model)
    created = []
    for start, duration, text in _plan(segments):
        clip = model.add_clip(track.track_id, "", "text", start, duration, text)
        if clip is None:
            continue
        created.append(style_caption_clip(clip, style, canvas))
    return created


def caption_command(model, segments, style=None):
    """Command chèn cả loạt như một bước undo duy nhất."""
    from core.commands import InsertCaptionsCommand
    return InsertCaptionsCommand(model, _plan(segments), style, _canvas_size(model))


def _plan(segments, min_duration=0.4):
    """[(start_sec, duration_sec, text)] — dịch mốc ms của engine sang giây.

    Engine ASR trả các cửa sổ hơi chồng nhau; nếu để chồng, model sẽ tự đẻ thêm
    track va chạm và lane phụ đề hoá thành nhiều hàng lộn xộn.
    """
    ordered = sorted(segments, key=lambda s: (s["start_ms"], s["end_ms"]))
    planned = []
    cursor = 0.0
    for seg in ordered:
        start = max(cursor, seg["start_ms"] / 1000.0)
        end = max(start + min_duration, seg["end_ms"] / 1000.0)
        planned.append((start, end - start, seg["text"]))
        cursor = end
    return planned
