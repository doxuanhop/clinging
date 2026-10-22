"""
core/settings.py

Nơi duy nhất định nghĩa cài đặt của ứng dụng.

Nguyên tắc: một khóa chỉ được tồn tại khi có chỗ thật trong app đọc nó.
Thêm khóa "trang trí" chỉ tạo ra một control nói dối trong hộp thoại Cài
đặt, nên các khóa không có hook đã bị bỏ hẳn thay vì giữ lại cho đẹp.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "Clinging"
# Cùng số với packaging/version_info.txt và ClingingSetup-<ver>.exe. Từ 1.0.1
# tới 1.0.3 dòng này bị QUÊN (vẫn "1.0.0") nên hộp "Về" nói sai bản đang chạy,
# và gate cũ `settings.APP_VERSION in about` luôn đúng vì nó tự so với chính nó.
# Giờ release_meta.py so ba nguồn (.iss / version_info.txt / đây) và chết nếu lệch.
APP_VERSION = "1.0.5"

# Cho phép probe/diagnostics trỏ tới một file settings tạm.
ENV_PATH = "CLINGING_SETTINGS_PATH"

DEFAULTS = {
    # Giao diện
    "theme": "dark",                     # theme_manager.set_mode + stylesheet
    # Dự án
    "project_dir": str(Path.home() / "Clinging_Projects"),
    "default_fps": 30,                   # meta fps của dự án mới
    "playhead_step": 1,                  # số frame mỗi lần nhấn Left/Right
    # Timeline
    "snapping_enabled": True,
    "snap_playhead": True,
    "snap_clip_edges": True,
    "snap_threshold": 10,                # pixel
    "min_zoom_px_per_sec": 5,            # mức thu nhỏ tối đa
    "show_waveform": True,
    "show_thumbnails": True,
    "undo_steps": 100,
    # Tự động lưu
    "auto_save": True,
    "auto_save_interval": 5,             # phút
}

BOOL_KEYS = frozenset({
    "snapping_enabled", "snap_playhead", "snap_clip_edges",
    "show_waveform", "show_thumbnails", "auto_save",
})

CHOICES = {"theme": ("dark", "light")}

# (min, max) — giá trị ngoài khoảng bị kẹp, không bị loại.
INT_RANGES = {
    "default_fps": (1, 240),
    "playhead_step": (1, 10),
    "snap_threshold": (1, 50),
    "min_zoom_px_per_sec": (1, 100),
    "undo_steps": (10, 1000),
    "auto_save_interval": (1, 60),
}

DIR_KEYS = frozenset({"project_dir"})


def app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    app_dir = base / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def settings_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return app_data_dir() / "settings.json"


def _coerce(key, value):
    """Trả về giá trị hợp lệ cho `key`, hoặc None nếu không dùng được."""
    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return None
    if key in CHOICES:
        text = str(value).strip().lower()
        return text if text in CHOICES[key] else None
    if key in INT_RANGES:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        low, high = INT_RANGES[key]
        return max(low, min(high, number))
    if key in DIR_KEYS:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    return None


def sanitize(mapping) -> dict:
    """Chỉ giữ khóa đã biết; mọi giá trị hỏng rơi về DEFAULTS."""
    result = dict(DEFAULTS)
    if not isinstance(mapping, dict):
        return result
    for key in DEFAULTS:
        coerced = _coerce(key, mapping.get(key))
        if coerced is not None:
            result[key] = coerced
    return result


_cache = dict(DEFAULTS)


def load(path=None) -> dict:
    """Đọc file, kẹp theo DEFAULTS; file thiếu/hỏng không được ném lỗi."""
    target = Path(path) if path else settings_path()
    saved = {}
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict):
                saved = raw
        except (OSError, ValueError):
            saved = {}
    return sanitize(saved)


def use(mapping) -> dict:
    """Nạp vào bộ nhớ đệm đang chạy mà không ghi đĩa."""
    global _cache
    _cache = sanitize(mapping)
    return dict(_cache)


def reload(path=None) -> dict:
    return use(load(path))


def save(mapping=None, path=None) -> dict:
    """Validate, ghi đĩa rồi cập nhật cache — app đọc ngay giá trị mới."""
    clean = sanitize(mapping if mapping is not None else _cache)
    target = Path(path) if path else settings_path()
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(clean, handle, indent=2, ensure_ascii=False)
    use(clean)
    return clean


def reset(path=None) -> dict:
    return save(DEFAULTS, path)


def get(key):
    return _cache.get(key, DEFAULTS.get(key))


def values() -> dict:
    return dict(_cache)


def unknown_keys(mapping) -> list:
    """Khóa bị loại khỏi file — diagnostics dùng để chứng minh không có khóa ma."""
    if not isinstance(mapping, dict):
        return []
    return sorted(str(key) for key in mapping if key not in DEFAULTS)
