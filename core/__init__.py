"""
core/__init__.py
Package cốt lõi chứa toàn bộ logic nghiệp vụ của Timeline Engine.
Tách biệt hoàn toàn khỏi UI để dễ test và bảo trì.

Tên model ở dưới resolve lúc được lấy (PEP 562), không import ở đầu file:
mỗi `from core import settings` cũng chạy file này, và bản eager kéo
timeline_model -> dataclasses + recap_overlay + transitions + copy vào làn boot
của trang Home (66 ms cumulative do bang `-X importtime`).
"""

_LAZY_ATTRS = {
    "TimelineModel": "core.timeline_model",
    "TrackModel": "core.timeline_model",
    "ClipModel": "core.timeline_model",
    "TrackType": "core.timeline_model",
    "TimePixelMapper": "core.time_mapper",
    "SnapEngine": "core.snap_engine",
    "SnapResult": "core.snap_engine",
    "UndoStack": "core.commands",
}

__all__ = [
    "TimelineModel", "TrackModel", "ClipModel", "TrackType",
    "TimePixelMapper",
    "SnapEngine", "SnapResult",
    "UndoStack",
]


def __getattr__(name):
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError("module 'core' has no attribute %r" % name)
    from importlib import import_module
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
