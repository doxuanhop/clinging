"""
theme.py
Quản lý theme (Dark / Light) cho toàn bộ ứng dụng Clinqing.
Đọc file .qss tương ứng và cung cấp vài hằng số màu dùng trong
các chỗ cần vẽ bằng QPainter (không thể lấy từ QSS).
"""

import os
import sys
from PySide6.QtCore import QObject, Signal

# Bản dựng PyInstaller (onefile) đặt tài nguyên trong _MEIPASS, không cạnh file này.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
STYLES_DIR = os.path.join(BASE_DIR, "styles")


class Palette:
    """Hằng số màu dùng khi vẽ tay (QPainter) - phải khớp với .qss"""

    DARK = {
        "bg": "#141414",
        "panel": "#1a1a1e",
        "border": "#2a2a30",
        "accent": "#40E0D0",
        "accent_hover": "#5FF0E2",
        "text": "#e0e0e0",
        "muted": "#8a8a92",
        "ruler_line": "#2a2a30",
        "playhead": "#40E0D0",
        "cyan": "#40E0D0",
    }

    LIGHT = {
        "bg": "#f8f8f8",
        "panel": "#ffffff",
        "border": "#d8d8dc",
        "accent": "#40E0D0",
        "accent_hover": "#5FF0E2",
        "text": "#1a1a1e",
        "muted": "#6b6b72",
        "ruler_line": "#d8d8dc",
        "playhead": "#40E0D0",
        "cyan": "#40E0D0",
    }


class ThemeManager(QObject):
    """Phát tín hiệu mỗi khi theme thay đổi để các widget vẽ tay tự cập nhật."""

    themeChanged = Signal(str)  # "dark" | "light"

    def __init__(self):
        super().__init__()
        self._mode = "dark"

    @property
    def mode(self):
        return self._mode

    @property
    def colors(self):
        return Palette.DARK if self._mode == "dark" else Palette.LIGHT

    def stylesheet(self):
        path = os.path.join(STYLES_DIR, f"{self._mode}.qss")
        with open(path, "r", encoding="utf-8") as f:
            base = f.read()
        # style.qss là lớp giao diện dùng chung cho cả Home và Editor.
        # Chỉ cần sửa file này để đổi nhận diện mà không chạm code Python.
        shared_path = os.path.join(STYLES_DIR, "style.qss")
        if os.path.exists(shared_path):
            with open(shared_path, "r", encoding="utf-8") as f:
                base += "\n" + f.read()
        return base

    def toggle(self):
        self._mode = "light" if self._mode == "dark" else "dark"
        self.themeChanged.emit(self._mode)
        return self._mode

    def set_mode(self, mode: str) -> bool:
        """Đặt theme tuyệt đối (không phải lật) — chỉ phát tín hiệu khi thật sự đổi."""
        next_mode = "light" if str(mode).strip().lower() == "light" else "dark"
        if next_mode == self._mode:
            return False
        self._mode = next_mode
        self.themeChanged.emit(self._mode)
        return True


# Instance dùng chung toàn app (singleton đơn giản)
theme_manager = ThemeManager()
