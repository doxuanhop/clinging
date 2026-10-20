"""
core/snap_engine.py
Hệ thống Snapping (Magnet Effect) cho Timeline.

Khi người dùng kéo clip hoặc playhead, SnapEngine sẽ tìm điểm
"hít" gần nhất (clip edges, playhead, grid) và trả về vị trí
đã snap cùng loại snap để UI hiển thị indicator.

Thuật toán:
    1. Thu thập tất cả "snap candidates" (mép clip, playhead, grid marks)
    2. Tính khoảng cách pixel giữa vị trí hiện tại và mỗi candidate
    3. Nếu khoảng cách < threshold → snap vào candidate gần nhất
"""

from dataclasses import dataclass
from typing import Optional

from core.time_mapper import TimePixelMapper


@dataclass
class SnapResult:
    """Kết quả snap — vị trí thời gian đã snap và thông tin hiển thị."""
    snapped_time: float      # Thời gian đã snap (giây)
    snap_type: str           # "clip_start", "clip_end", "playhead", "grid"
    indicator_x: float       # Tọa độ pixel X để vẽ indicator line
    delta: float = 0.0       # Khoảng cách thời gian đã dịch chuyển


class SnapEngine:
    """
    Cơ chế snapping (Magnet Effect) cho clip và playhead.

    Sử dụng:
        engine = SnapEngine(mapper)
        result = engine.find_snap(time=3.5, exclude="clip-uuid", model=timeline)
        if result:
            clip.start_time = result.snapped_time
            show_indicator(result.indicator_x)
    """

    def __init__(self, mapper: TimePixelMapper):
        self._mapper = mapper
        self._drag_candidates = None
        self._drag_exclude = ""

        # Cấu hình snap
        self.enabled: bool = True
        self.threshold_px: int = 10           # Khoảng cách pixel để kích hoạt snap
        self.snap_to_playhead: bool = True
        self.snap_to_clip_edges: bool = True
        self.snap_to_grid: bool = False

    def begin_drag(self, model, exclude: str = ""):
        """Cache snap points once for a drag gesture instead of every pixel."""
        self._drag_exclude = exclude
        self._drag_candidates = self._collect_candidates(0.0, model, exclude)

    def end_drag(self):
        self._drag_candidates = None
        self._drag_exclude = ""

    @property
    def threshold_time(self) -> float:
        """Chuyển threshold từ pixel sang giây dựa trên zoom hiện tại."""
        return self.threshold_px / self._mapper.px_per_sec

    def find_snap(self, time: float, model, exclude: str = "",
                  check_end: bool = False) -> Optional[SnapResult]:
        """
        Tìm điểm snap gần nhất cho thời điểm `time`.

        Args:
            time:       Thời điểm cần kiểm tra snap (giây)
            model:      TimelineModel instance
            exclude:    clip_id cần loại trừ (clip đang kéo)
            check_end:  Nếu True, kiểm tra cả cuối clip (start+duration)

        Returns:
            SnapResult nếu tìm thấy snap, None nếu không.
        """
        if not self.enabled:
            return None

        if self._drag_candidates is not None and exclude == self._drag_exclude:
            candidates = self._drag_candidates
        else:
            candidates = self._collect_candidates(time, model, exclude)
        if not candidates:
            return None

        # Tìm candidate gần nhất
        best_candidate = None
        best_delta = float("inf")

        for snap_time, snap_type in candidates:
            delta = abs(time - snap_time)
            if delta < best_delta:
                best_delta = delta
                best_candidate = (snap_time, snap_type)

        if best_candidate is None or best_delta > self.threshold_time:
            return None

        snap_time, snap_type = best_candidate
        return SnapResult(
            snapped_time=snap_time,
            snap_type=snap_type,
            indicator_x=self._mapper.time_to_pixel(snap_time),
            delta=time - snap_time,
        )

    def find_snap_for_edge(self, start_time: float, end_time: float,
                           model, exclude: str = "") -> Optional[SnapResult]:
        """
        Kiểm tra snap cho cả 2 mép (đầu + cuối) của clip.
        Ưu tiên mép nào gần snap point hơn.
        """
        result_start = self.find_snap(start_time, model, exclude)
        result_end = self.find_snap(end_time, model, exclude)

        if result_start and result_end:
            # Chọn cái gần hơn
            if abs(result_start.delta) <= abs(result_end.delta):
                return result_start
            else:
                # Dịch về start dựa trên snap ở end
                duration = end_time - start_time
                result_end.snapped_time -= duration
                return result_end
        elif result_start:
            return result_start
        elif result_end:
            duration = end_time - start_time
            result_end.snapped_time -= duration
            return result_end
        return None

    def _collect_candidates(self, time: float, model,
                            exclude: str) -> list[tuple[float, str]]:
        """Thu thập tất cả snap candidates (thời gian, loại)."""
        candidates = []

        # 1. Mép clip
        if self.snap_to_clip_edges:
            for track in model.tracks:
                for clip in track.clips:
                    if clip.clip_id == exclude:
                        continue
                    candidates.append((clip.start_time, "clip_start"))
                    candidates.append((clip.end_time, "clip_end"))

        # 2. Playhead
        if self.snap_to_playhead:
            candidates.append((model.playhead, "playhead"))

        # 3. Grid marks
        if self.snap_to_grid:
            step = self._mapper.ruler_step()
            t = 0.0
            max_t = model.duration + step
            while t <= max_t:
                candidates.append((t, "grid"))
                t += step

        # 4. Luôn snap vào 0.0 (đầu timeline)
        candidates.append((0.0, "origin"))

        return candidates
