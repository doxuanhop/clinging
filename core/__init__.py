"""
core/__init__.py
Package cốt lõi chứa toàn bộ logic nghiệp vụ của Timeline Engine.
Tách biệt hoàn toàn khỏi UI để dễ test và bảo trì.
"""

from core.timeline_model import TimelineModel, TrackModel, ClipModel, TrackType
from core.time_mapper import TimePixelMapper
from core.snap_engine import SnapEngine, SnapResult
from core.commands import UndoStack

__all__ = [
    "TimelineModel", "TrackModel", "ClipModel", "TrackType",
    "TimePixelMapper",
    "SnapEngine", "SnapResult",
    "UndoStack",
]
