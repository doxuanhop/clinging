"""
core/time_mapper.py
Hàm chuyển đổi tập trung Time ↔ Pixel (Time-to-Pixel Mapping).

Đây là trung tâm đồng bộ giữa mọi thành phần trên trục thời gian:
  - TimelineScene (vẽ ruler, grid)
  - ClipItem (vị trí + chiều rộng)
  - PlayheadItem (vị trí X)
  - SnapEngine (tính khoảng cách)

Công thức cốt lõi:
    pixel = time × px_per_sec + left_margin − scroll_offset
    time  = (pixel − left_margin + scroll_offset) / px_per_sec
"""

import math

from PySide6.QtCore import QObject, Signal


class TimePixelMapper(QObject):
    """
    Chuyển đổi 2 chiều giữa thời gian (giây) và tọa độ pixel (X).

    Signals:
        zoomChanged(float)  — px_per_sec mới sau khi zoom
    """

    zoomChanged = Signal(float)

    # Giới hạn zoom
    MIN_PX_PER_SEC = 5.0       # zoom xa nhất
    MAX_PX_PER_SEC = 500.0     # zoom gần nhất
    DEFAULT_PX_PER_SEC = 48.0

    # Track Header lives in its own fixed view.  The scrollable Track Body
    # therefore starts exactly at timeline time 0.
    LEFT_MARGIN = 0.0

    def __init__(self, px_per_sec: float = DEFAULT_PX_PER_SEC,
                 parent=None):
        super().__init__(parent)
        self._px_per_sec = px_per_sec
        self._offset = 0.0       # scroll offset (pixel)

    # ── Properties ──────────────────────────────────────────────

    @property
    def px_per_sec(self) -> float:
        return self._px_per_sec

    @property
    def offset(self) -> float:
        return self._offset

    @offset.setter
    def offset(self, value: float):
        self._offset = max(0.0, value)

    # ── Core Conversion ─────────────────────────────────────────

    def time_to_pixel(self, t: float) -> float:
        """Chuyển thời gian (giây) → tọa độ pixel X trên scene."""
        return t * self._px_per_sec + self.LEFT_MARGIN

    def pixel_to_time(self, px: float) -> float:
        """Chuyển tọa độ pixel X → thời gian (giây). Clamp >= 0."""
        t = (px - self.LEFT_MARGIN) / self._px_per_sec
        return max(0.0, t)

    def duration_to_width(self, d: float) -> float:
        """Chuyển thời lượng (giây) → chiều rộng pixel."""
        return d * self._px_per_sec

    def width_to_duration(self, w: float) -> float:
        """Chuyển chiều rộng pixel → thời lượng (giây)."""
        # Keep the sign: drag deltas to the left are negative.  Callers that
        # represent absolute durations clamp their own domain explicitly.
        return w / self._px_per_sec

    # ── Zoom Control ────────────────────────────────────────────

    def set_zoom(self, px_per_sec: float):
        """Đặt mức zoom. Clamp trong khoảng [MIN, MAX]."""
        px_per_sec = max(self.MIN_PX_PER_SEC,
                         min(px_per_sec, self.MAX_PX_PER_SEC))
        if px_per_sec != self._px_per_sec:
            self._px_per_sec = px_per_sec
            self.zoomChanged.emit(px_per_sec)

    def set_min_zoom(self, px_per_sec: float):
        """Cài 'thu nhỏ tối đa' cho riêng mapper này (không đụng lớp khác).

        Mức zoom hiện tại bị kẹp lại ngay, nên slider và scene không bao giờ
        mâu thuẫn với nhau sau khi đổi cài đặt.
        """
        low = max(0.1, float(px_per_sec))
        self.MIN_PX_PER_SEC = min(low, float(self.MAX_PX_PER_SEC))
        self.set_zoom(self._px_per_sec)
        return self.MIN_PX_PER_SEC

    def zoom_in(self, factor: float = 1.2):
        """Phóng to (tăng px_per_sec)."""
        self.set_zoom(self._px_per_sec * factor)

    def zoom_out(self, factor: float = 1.2):
        """Thu nhỏ (giảm px_per_sec)."""
        self.set_zoom(self._px_per_sec / factor)

    def zoom_to_fit(self, duration: float, viewport_width: float):
        """Zoom vừa khít toàn bộ timeline trong viewport."""
        available = viewport_width - self.LEFT_MARGIN - 20  # margin phải
        if duration > 0 and available > 0:
            self.set_zoom(available / duration)

    # ── Scene Geometry Helpers ──────────────────────────────────

    def scene_width(self, duration: float) -> float:
        """Tổng chiều rộng scene cần thiết cho timeline duration."""
        return self.time_to_pixel(duration) + 100  # buffer bên phải

    def ruler_step(self) -> float:
        """Minor interval selected from a stable 1/2/5 time sequence."""
        return self.ruler_intervals()[0]

    def ruler_major_step(self) -> float:
        """Khoảng cách giữa các vạch chính (có label text)."""
        return self.ruler_intervals()[1]

    def ruler_intervals(self, min_minor_px: float = 18.0,
                        min_label_px: float = 88.0) -> tuple[float, float, int]:
        """Return minor/major time intervals derived only from px_per_sec.

        Using nice decimal intervals prevents the ruler from stretching a
        cached bitmap or accumulating floating-point drift while zooming.
        """
        raw_minor = max(1e-6, min_minor_px / self._px_per_sec)
        exponent = 10.0 ** math.floor(math.log10(raw_minor))
        normalized = raw_minor / exponent
        nice = next((value for value in (1.0, 2.0, 5.0, 10.0)
                     if value >= normalized), 10.0)
        minor = nice * exponent

        raw_multiple = max(1.0, min_label_px /
                           max(1e-6, minor * self._px_per_sec))
        major_multiple = next((value for value in (1, 2, 5, 10, 20, 50)
                               if value >= raw_multiple), 50)
        return minor, minor * major_multiple, major_multiple
