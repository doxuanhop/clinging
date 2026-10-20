"""
core/media_extractor.py
Công cụ backend trích xuất dữ liệu đa phương tiện sử dụng OpenCV, NumPy và FFmpeg.
Hỗ trợ:
  - Trích xuất frame đầu tiên của video làm ảnh đại diện (Thumbnail) với tốc độ cao.
  - Phân tích biên độ và giảm mẫu (Downsampling) sóng âm thanh (Waveform) cho tệp audio/video.
"""

import os
import json
import subprocess
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt

from core import external_tools

# Video metadata cache: file_path -> {width, height, fps, duration}
_metadata_cache = {}

# cv2 + numpy được nạp ở lần giải mã thật sự, không phải ở lần import module.
# Do trên máy này: hai thư viện này chiếm 134 MiB RSS và ~0,5 s, trong khi trang
# Home mở app chưa chắc đã cần giải mã frame nào (ảnh bìa đã nằm trong cache đĩa).
_cv2 = None
_np = None


def _numpy():
    global _np
    if _np is None:
        import numpy as np
        _np = np
    return _np


def _opencv():
    global _cv2
    if _cv2 is None:
        import cv2
        _cv2 = cv2
        _numpy()
    return _cv2


def _probe_with_ffprobe(file_path: str) -> dict:
    """Read reliable container metadata, especially for WMV and VFR media."""
    ffprobe = external_tools.find("ffprobe")
    if not ffprobe:
        return {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=8, creationflags=0x08000000
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        format_duration = float(data.get("format", {}).get("duration") or 0)
        stream_duration = float(video.get("duration") or 0)
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        numerator, denominator = (rate.split("/", 1) + ["1"])[:2]
        fps = float(numerator) / float(denominator) if float(denominator) else 0.0
        return {"width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0), "fps": fps,
                "duration": max(format_duration, stream_duration)}
    except (OSError, ValueError, TypeError, json.JSONDecodeError,
            subprocess.SubprocessError):
        return {}


def get_video_metadata(file_path: str) -> dict:
    """
    Đọc metadata của video: width, height, fps, duration.
    Trả về dict hoặc {} nếu lỗi.
    Dùng cache để tránh đọc lại nhiều lần.
    """
    if file_path in _metadata_cache:
        return _metadata_cache[file_path]

    if not os.path.exists(file_path):
        return {}

    try:
        cv2 = _opencv()
        probed = _probe_with_ffprobe(file_path)
        old_stderr = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        try:
            cap = cv2.VideoCapture(file_path)
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
            os.close(devnull)
        if not cap.isOpened():
            return {}

        width = int(probed.get("width") or cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(probed.get("height") or cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(probed.get("fps") or cap.get(cv2.CAP_PROP_FPS))
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()

        if fps <= 0:
            fps = 30.0
        duration = float(probed.get("duration") or 0.0)
        if duration <= 0 and frame_count > 0:
            duration = frame_count / fps

        meta = {
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "aspect_ratio": f"{width}:{height}" if height > 0 else "16:9",
            "ratio_value": width / height if height > 0 else 16 / 9,
        }
        _metadata_cache[file_path] = meta
        return meta

    except Exception as e:
        print(f"Lỗi đọc metadata video: {e}")
        return {}


def get_media_duration(file_path: str, media_type: str) -> float:
    """Return actual source duration without decoding the complete file."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    if media_type == "image":
        return 5.0
    if media_type == "video":
        probed_duration = float(_probe_with_ffprobe(file_path).get("duration") or 0.0)
        if probed_duration > 0:
            return probed_duration
        return float(get_video_metadata(file_path).get("duration") or 0.0)
    if media_type == "audio":
        return float(_probe_with_ffprobe(file_path).get("duration") or 0.0)
    return 0.0

def extract_video_thumbnail(file_path, target_height):
    """
    Trích xuất frame đầu tiên của video bằng OpenCV và chuyển đổi thành QPixmap.
    """
    if not os.path.exists(file_path):
        return None
        
    try:
        cv2 = _opencv()
        # Khởi tạo đối tượng đọc video
        old_stderr = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        try:
            cap = cv2.VideoCapture(file_path)
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
            os.close(devnull)
        if not cap.isOpened():
            return None
        
        # Đọc frame đầu tiên
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            return None

        # OpenCV mặc định dùng hệ màu BGR, PyQt/PySide cần hệ màu RGB
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channel = rgb_image.shape
        bytes_per_line = channel * width
        
        # Chuyển đổi ma trận pixel thành QImage, sau đó sang QPixmap
        q_img = QImage(rgb_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        
        # Scale ảnh theo chiều cao của track
        return pixmap.scaledToHeight(int(target_height), Qt.SmoothTransformation)
        
    except Exception as e:
        print(f"Lỗi trích xuất frame video: {e}")
        return None

WAVEFORM_SAMPLE_RATE = 8000
# File dài vô hạn sẽ làm worker treo cả giây; cửa sổ mặc định chỉ để dựng hình.
WAVEFORM_MAX_WINDOW = 30.0


def extract_audio_waveform(file_path, num_samples=150, start=0.0, duration=None):
    """Biên độ từng cột sóng trên MỘT CỬA SỔ nguồn được chọn.

    Bọc `_compute_waveform` bằng cache đĩa: mỗi ffmpeg này tốn ~0,4 s và trước
    đây nó chạy lại y hệt mỗi lần mở project (scratch/perf_baseline.json).
    Hai lý do hàm dưới gọi ffmpeg thay vì tải cả file bằng pydub:

    * Clip đã trim hoặc chạy 2x chỉ hiển thị một đoạn nguồn. Đọc cả file rồi
      căng ra trên clip means waveform chỉ đúng cho clip chưa cắt — người dùng
      kéo mép trim mà sóng không nhúc nhích thì cây sóng là đồ trang trí.
    * ``-ss``/``-t`` cắt ngay khi giải mã, nên video dài vẫn vẽ sóng nhanh.

    Trả về danh sách RỖNG khi file không có luồng âm thanh. Đường phẳng đầy số
    0 cũng "vẽ được", và clip im lặng sẽ hiện dải sóng như thể đã phân tích xong.
    """
    from core import media_cache

    key = media_cache.waveform_key(file_path, num_samples, start, duration)
    cached = media_cache.read_waveform(key) if key else None
    if cached is not None and len(cached) == int(num_samples):
        return cached
    amps = _compute_waveform(file_path, num_samples, start, duration)
    if key:
        media_cache.write_waveform(key, amps)
    return amps


def _compute_waveform(file_path, num_samples=150, start=0.0, duration=None):
    if not os.path.exists(file_path) or num_samples <= 0:
        return []

    window = WAVEFORM_MAX_WINDOW if duration is None else max(
        0.05, float(duration))
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        return []
    cmd = [ffmpeg, "-v", "error", "-ss", "%.3f" % max(0.0, float(start))]
    if window > 0.0:
        cmd.extend(["-t", "%.3f" % window])
    cmd.extend([
        "-i", file_path,
        "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(WAVEFORM_SAMPLE_RATE),
        "-f", "s16le", "-",
    ])
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=30, creationflags=0x08000000
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0 or not result.stdout:
        return []

    np = _numpy()
    try:
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float64)
    except ValueError:
        return []
    if samples.size == 0:
        return []

    per_column = max(1, samples.size // num_samples)
    usable = min(num_samples * per_column, samples.size)
    columns = np.abs(samples[:usable].reshape(-1, per_column)).max(axis=1)
    if columns.size < num_samples:
        # File ngắn hơn số cột yêu cầu: lặp mẫu cuối để cây sóng vẫn phủ hết clip.
        columns = np.pad(columns, (0, num_samples - columns.size), mode="edge")

    peak = float(columns.max())
    if peak <= 0.0:
        # Nguồn có luồng tiếng nhưng toàn số 0: vẫn là "có sóng", chỉ là phẳng.
        return [0.0] * num_samples
    return [float(column) / peak for column in columns[:num_samples]]

