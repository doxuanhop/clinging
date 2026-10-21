"""
core/commands.py
Hệ thống Undo/Redo sử dụng Command Pattern.

Mỗi thao tác chỉnh sửa trên timeline được gói thành một Command object
có thể thực thi (execute) và hoàn tác (undo). UndoStack quản lý lịch sử
và phát Signal để UI cập nhật trạng thái nút Undo/Redo.

Pattern:
    stack = UndoStack()
    stack.push(MoveClipCommand(model, clip_id, old_pos, new_pos))
    stack.undo()   # → quay lại old_pos
    stack.redo()   # → đến new_pos lại
"""

from abc import ABC, abstractmethod
import time
from typing import Optional
from PySide6.QtCore import QObject, Signal


# ── Abstract Command ────────────────────────────────────────────

class Command(ABC):
    """Base class cho mọi command. Subclass phải implement execute() và undo()."""

    @abstractmethod
    def execute(self):
        """Thực thi hành động."""

    @abstractmethod
    def undo(self):
        """Hoàn tác hành động."""

    def description(self) -> str:
        """Mô tả ngắn hiển thị trong tooltip Undo/Redo."""
        return self.__class__.__name__

    def merges_with(self, other: "Command") -> bool:
        """Lệnh mới có phải là bước tiếp theo của lệnh đang nằm trên đỉnh?

        Mặc định KHÔNG: mọi lệnh khác nhau (khác clip, khác thao tác) phải còn
        là một bước Ctrl+Z riêng.
        """
        return False

    def absorb(self, other: "Command"):
        """Nạp kết quả của lệnh kế tiếp vào lệnh này, giữ nguyên điểm khởi đầu."""
        return None


# ── Undo Stack ──────────────────────────────────────────────────

class UndoStack(QObject):
    """
    Quản lý lịch sử Undo/Redo.

    Signals:
        stateChanged()     — undo/redo availability thay đổi
        undoTextChanged(str) — mô tả hành động undo tiếp theo
        redoTextChanged(str) — mô tả hành động redo tiếp theo
    """

    stateChanged = Signal()
    undoTextChanged = Signal(str)
    redoTextChanged = Signal(str)

    MAX_HISTORY = 100   # Giới hạn lịch sử

    def __init__(self, parent=None):
        super().__init__(parent)
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_text(self) -> str:
        if self._undo_stack:
            return f"Hoàn tác: {self._undo_stack[-1].description()}"
        return ""

    @property
    def redo_text(self) -> str:
        if self._redo_stack:
            return f"Làm lại: {self._redo_stack[-1].description()}"
        return ""

    def set_max_history(self, limit: int) -> int:
        """Cài số bước hoàn tác tối đa cho riêng stack này (không đổi cả lớp)."""
        self.MAX_HISTORY = max(1, int(limit))
        overflow = len(self._undo_stack) - self.MAX_HISTORY
        if overflow > 0:
            del self._undo_stack[:overflow]
        self._emit_state()
        return self.MAX_HISTORY

    @property
    def max_history(self) -> int:
        return self.MAX_HISTORY

    @property
    def undo_count(self) -> int:
        return len(self._undo_stack)

    def push(self, command: Command):
        """Thực thi command và đẩy vào undo stack.

        Hai lệnh kế tiếp nhau mà merges_with() cho là cùng một thao tác (gõ
        từng ký tự, kéo từng nấc spin) thì LỆNH trên đỉnh nhận kết quả của lệnh
        mới thay vì thành một bước thứ hai: MAX_HISTORY = 100 sẽ bị điền sạch
        chỉ bởi một đoạn chữ, và Ctrl+Z phải xoá cả đoạn chứ không từng ký tự.
        """
        command.execute()
        top = self._undo_stack[-1] if self._undo_stack else None
        if top is not None and top.merges_with(command):
            top.absorb(command)
        else:
            self._undo_stack.append(command)
            # Giới hạn lịch sử
            if len(self._undo_stack) > self.MAX_HISTORY:
                self._undo_stack.pop(0)
        self._redo_stack.clear()        # Xóa redo khi có action mới

        self._emit_state()

    def undo(self):
        """Hoàn tác hành động cuối cùng."""
        if not self.can_undo:
            return
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        self._emit_state()

    def redo(self):
        """Làm lại hành động vừa hoàn tác."""
        if not self.can_redo:
            return
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        self._emit_state()

    def clear(self):
        """Xóa toàn bộ lịch sử."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._emit_state()

    def _emit_state(self):
        self.stateChanged.emit()
        self.undoTextChanged.emit(self.undo_text)
        self.redoTextChanged.emit(self.redo_text)


# ── Concrete Commands ───────────────────────────────────────────

class MoveClipCommand(Command):
    """Di chuyển clip từ vị trí cũ sang vị trí mới."""

    def __init__(self, model, clip_id: str,
                 old_start: float, new_start: float,
                 old_track_id: str = "", new_track_id: str = ""):
        self._model = model
        self._clip_id = clip_id
        self._old_start = old_start
        self._new_start = new_start
        self._old_track_id = old_track_id
        self._new_track_id = new_track_id or old_track_id
        self._before_positions: dict[str, float] = {}
        self._before_track_id = ""
        self._before_clips = None

    def execute(self):
        import copy
        clip = self._model.get_clip(self._clip_id)
        track = self._model.get_track(clip.track_id) if clip else None
        if track:
            self._before_track_id = track.track_id
            self._before_clips = copy.deepcopy(track.clips)
        self._before_positions = {
            clip.clip_id: clip.start_time
            for track in self._model.tracks for clip in track.clips
        }
        self._model.place_clip_ripple(self._clip_id, self._new_start)

    def undo(self):
        if self._before_clips is not None:
            import copy
            track = self._model.get_track(self._before_track_id)
            if track:
                restored_ids = {clip.clip_id for clip in self._before_clips}
                for other_track in list(self._model.tracks):
                    if other_track is track:
                        continue
                    for current in list(other_track.clips):
                        if current.clip_id in restored_ids:
                            other_track.clips.remove(current)
                            self._model.clipRemoved.emit(current.clip_id)
                for current in list(track.clips):
                    self._model.clipRemoved.emit(current.clip_id)
                track.clips = copy.deepcopy(self._before_clips)
                for restored in track.clips:
                    self._model.clipAdded.emit(restored)
                for empty in list(self._model.get_empty_tracks()):
                    if not empty.is_main_track:
                        self._model.remove_track(empty.track_id)
                self._model.recalculate_project_duration()
                return
        for clip_id, start_time in self._before_positions.items():
            clip = self._model.get_clip(clip_id)
            if clip:
                clip.start_time = start_time
                self._model.clipMoved.emit(clip_id, start_time)

    def description(self) -> str:
        return "Di chuyển clip"


class ResizeClipCommand(Command):
    """Thay đổi thời lượng clip."""

    def __init__(self, model, clip_id: str,
                 old_duration: float, new_duration: float,
                 old_start: float = 0.0, new_start: float = 0.0,
                 from_start: bool = False,
                 old_in: float = 0.0, new_in: float = 0.0):
        self._model = model
        self._clip_id = clip_id
        self._old_duration = old_duration
        self._new_duration = new_duration
        self._old_start = old_start
        self._new_start = new_start
        self._from_start = from_start
        self._old_in = old_in
        self._new_in = new_in

    def _apply(self, start, duration, in_point):
        clip, track = self._model._find_clip(self._clip_id)
        if not clip:
            return
        clip.start_time = max(0.0, start)
        clip.duration = max(0.1, duration)
        clip.in_point = max(0.0, in_point)
        clip.out_point = clip.in_point + clip.duration
        if track and track.is_main_track:
            # Trimming the spine is a ripple edit: all following clips remain
            # gapless and move with the changed edge.
            self._model.recalculate_main_storyline(track)
        else:
            self._model.recalculate_project_duration()
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def execute(self):
        self._apply(self._new_start, self._new_duration, self._new_in)

    def undo(self):
        self._apply(self._old_start, self._old_duration, self._old_in)

    def description(self) -> str:
        return "Thay đổi kích thước clip"


class AddClipCommand(Command):
    """Thêm clip mới vào timeline."""

    def __init__(self, model, track_id: str, source_path: str,
                 media_type: str = "video", start_time: float = 0.0,
                 duration: float = 5.0, name: str = ""):
        self._model = model
        self._track_id = track_id
        self._source_path = source_path
        self._media_type = media_type
        self._start_time = start_time
        self._duration = duration
        self._name = name
        self._clip_id: Optional[str] = None
        self._before_positions: dict[str, float] = {}

    def execute(self):
        self._before_positions = {
            clip.clip_id: clip.start_time
            for track in self._model.tracks for clip in track.clips
        }
        clip = self._model.add_clip(
            self._track_id, self._source_path, self._media_type,
            self._start_time, self._duration, self._name
        )
        if clip and clip.media_type in ("video", "image"):
            self._clip_id = clip.clip_id
            from core.canvas_utils import get_media_dimensions, ASPECT_RATIOS, apply_auto_fit
            media_w, media_h = get_media_dimensions(
                clip.source_path, clip.media_type
            )
            ratio_key = getattr(self._model, 'project_ratio', '16:9')
            canvas_w, canvas_h = ASPECT_RATIOS.get(ratio_key, (1920, 1080))
            # Media mới luôn Fit an toàn trong project frame; người dùng có
            # thể chủ động chọn Fill nếu muốn crop.
            clip.transform.fit_mode = "fit"
            apply_auto_fit(clip, canvas_w, canvas_h)
        elif clip:
            self._clip_id = clip.clip_id

    def undo(self):
        if self._clip_id:
            self._model.remove_clip(self._clip_id)
        for clip_id, start_time in self._before_positions.items():
            clip = self._model.get_clip(clip_id)
            if clip and clip.start_time != start_time:
                clip.start_time = start_time
                self._model.clipMoved.emit(clip_id, start_time)

    def description(self) -> str:
        return f"Thêm clip: {self._name or self._source_path}"


class RemoveClipCommand(Command):
    """Xóa clip khỏi timeline (lưu trạng thái để undo)."""

    def __init__(self, model, clip_id: str):
        self._model = model
        self._clip_id = clip_id
        # Lưu snapshot để undo
        self._saved_clip = None
        self._saved_track_id = ""
        self._saved_track = None
        self._saved_positions = {}

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            import copy
            self._saved_clip = copy.deepcopy(clip)
            self._saved_track_id = clip.track_id
            track = self._model.get_track(clip.track_id)
            self._saved_track = copy.deepcopy(track) if track else None
            self._saved_positions = {
                c.clip_id: c.start_time
                for t in self._model.tracks for c in t.clips
            }
            self._model.remove_clip(self._clip_id)

    def undo(self):
        if self._saved_clip and self._saved_track_id:
            track = self._model.get_track(self._saved_track_id)
            # Nếu track đã bị auto-remove, tạo lại track
            if track is None:
                from core.timeline_model import TrackType
                track_type = self._saved_clip.track_type if hasattr(self._saved_clip, 'track_type') else TrackType.VIDEO
                # Xác định track_type từ media_type
                media_type = self._saved_clip.media_type if hasattr(self._saved_clip, 'media_type') else "video"
                from ui.timeline_panel import MEDIA_TO_TRACK
                track_type = MEDIA_TO_TRACK.get(media_type, TrackType.VIDEO)
                track = self._model.add_track(track_type, z_index=0)
                if self._saved_track:
                    track.name = self._saved_track.name
                    track.is_main_track = self._saved_track.is_main_track
                # Cập nhật track_id trong saved clip
                self._saved_clip.track_id = track.track_id
            track.clips.append(self._saved_clip)
            self._model.clipAdded.emit(self._saved_clip)
            for clip_id, start_time in self._saved_positions.items():
                restored = self._model.get_clip(clip_id)
                if restored and restored.start_time != start_time:
                    restored.start_time = start_time
                    self._model.clipMoved.emit(clip_id, start_time)
            self._model._normalize_track_layers()
            self._model.tracksReordered.emit()

    def description(self) -> str:
        name = self._saved_clip.name if self._saved_clip else self._clip_id
        return f"Xóa clip: {name}"


class DuplicateClipCommand(Command):
    """Nhân bản clip và cho phép hoàn tác/làm lại đầy đủ."""

    def __init__(self, model, clip_id: str):
        self._model = model
        self._source_id = clip_id
        self._duplicate_id: Optional[str] = None

    def execute(self):
        duplicate = self._model.duplicate_clip(self._source_id)
        if duplicate:
            self._duplicate_id = duplicate.clip_id

    def undo(self):
        if self._duplicate_id:
            self._model.remove_clip(self._duplicate_id)

    def description(self) -> str:
        return "Nhân bản clip"


class DetachAudioCommand(Command):
    """Tách tiếng một clip video thành clip audio — MỘT bước Ctrl+Z cho cả hai nửa.

    Thao tác này sửa hai nơi cùng lúc (thêm clip audio xuống hàng tiếng, tắt tiếng
    clip video), nên undo phải trả cả hai. Trả một nửa thì hàng video im lặng vẫn
    nằm đó và người dùng chỉ phát hiện lúc bật export.

    Clip audio là clip cuối cùng trên một hàng vừa trống sẽ bị ``remove_clip`` xóa
    luôn hàng đó. Nếu hàng ấy người dùng tạo sẵn mà đang rỗng thì Ctrl+Z làm mất
    hàng của họ, nên lệnh nhớ nguyên trạng (tên, mute, lock, vị trí) để dựng lại
    đúng id — redo rồi undo phải về đúng mô hình ban đầu.
    """

    def __init__(self, model, clip_id: str):
        self._model = model
        self._source_id = clip_id
        self._audio_id: Optional[str] = None
        self._was_muted = False
        self._existed_audio_ids: set[str] = set()
        self._track_state: Optional[dict] = None

    def execute(self):
        clip = self._model.get_clip(self._source_id)
        if clip is None:
            return
        self._was_muted = bool(clip.audio_muted)
        from core.timeline_model import TrackType
        self._existed_audio_ids = {
            t.track_id for t in self._model.tracks
            if t.track_type == TrackType.AUDIO}
        audio = self._model.detach_audio(self._source_id)
        if audio is None:
            return
        self._audio_id = audio.clip_id
        if audio.track_id in self._existed_audio_ids:
            track = self._model.get_track(audio.track_id)
            if track is not None:
                self._track_state = {
                    "track_id": track.track_id,
                    "name": track.name,
                    "is_muted": bool(track.is_muted),
                    "is_locked": bool(track.is_locked),
                    "index": self._model.tracks.index(track),
                }

    def undo(self):
        if self._audio_id is None:
            return
        self._model.remove_clip(self._audio_id)
        self._restore_track()
        clip = self._model.get_clip(self._source_id)
        if clip is not None:
            clip.audio_muted = self._was_muted
            self._model.clipUpdated.emit(self._source_id)

    def _restore_track(self):
        state = self._track_state
        if state is None or self._model.get_track(state["track_id"]) is not None:
            return
        from core.timeline_model import TrackType
        track = self._model.add_track(TrackType.AUDIO, name=state["name"],
                                      track_id=state["track_id"])
        track.is_muted = state["is_muted"]
        track.is_locked = state["is_locked"]
        self._model.tracks.remove(track)
        self._model.tracks.insert(
            min(state["index"], len(self._model.tracks)), track)
        self._model.tracksReordered.emit()

    def description(self) -> str:
        return "Tách âm thanh khỏi clip"


class PasteClipsCommand(Command):
    """Dán cả nhóm clip từ clipboard tại playhead — MỘT bước undo.

    Bản dán clone từ snapshot nên id mới, giữ nguyên font/transform/keyframe/
    effect như bản gốc. Offset tương đối giữ bố cục nhiều clip khi dán cùng lúc.
    """

    def __init__(self, model, entries, anchor_time: float):
        self._model = model
        self._entries = list(entries)
        self._anchor = float(anchor_time)
        self._pasted_ids: list[str] = []

    def execute(self):
        import copy
        import uuid
        self._pasted_ids = []
        for entry in self._entries:
            pasted = copy.deepcopy(entry.clip)
            pasted.clip_id = str(uuid.uuid4())
            placed = self._model.place_clip(
                pasted, entry.source_track_id, self._anchor + entry.offset)
            if placed is not None:
                self._pasted_ids.append(placed.clip_id)
        if self._pasted_ids:
            self._model.select_clips(self._pasted_ids)

    def undo(self):
        for clip_id in reversed(self._pasted_ids):
            self._model.remove_clip(clip_id)
        self._pasted_ids = []

    def description(self) -> str:
        return "Dán %d clip" % len(self._pasted_ids)


class AddTrackCommand(Command):
    """Thêm track mới."""

    def __init__(self, model, track_type, name: str = ""):
        from core.timeline_model import TrackType
        self._model = model
        self._track_type = track_type
        self._name = name
        self._track_id: Optional[str] = None

    def execute(self):
        track = self._model.add_track(self._track_type, self._name)
        self._track_id = track.track_id

    def undo(self):
        if self._track_id:
            self._model.remove_track(self._track_id)

    def description(self) -> str:
        return f"Thêm track: {self._name}"


class RemoveTrackCommand(Command):
    """Xóa track."""

    def __init__(self, model, track_id: str):
        self._model = model
        self._track_id = track_id
        self._saved_track = None

    def execute(self):
        track = self._model.get_track(self._track_id)
        if track:
            import copy
            self._saved_track = copy.deepcopy(track)
            self._model.remove_track(self._track_id)

    def undo(self):
        if self._saved_track:
            self._model._tracks.append(self._saved_track)
            self._model.trackAdded.emit(self._saved_track)

    def description(self) -> str:
        name = self._saved_track.name if self._saved_track else self._track_id
        return f"Xóa track: {name}"


class SplitClipCommand(Command):
    """Cắt clip thành 2 phần tại thời điểm chỉ định."""

    def __init__(self, model, clip_id: str, split_time: float):
        self._model = model
        self._clip_id = clip_id
        self._split_time = split_time
        self._original_duration: float = 0.0
        self._new_clip_id: Optional[str] = None

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            self._original_duration = clip.duration
            new_clip = self._model.split_clip(self._clip_id, self._split_time)
            if new_clip:
                self._new_clip_id = new_clip.clip_id

    def undo(self):
        # Restore the original segment before removing the right half.  Doing
        # this in the opposite order compacts Main Storyline too early and can
        # leave the following clip overlapping the restored segment.
        clip = self._model.get_clip(self._clip_id)
        if clip:
            clip.duration = self._original_duration
            clip.out_point = clip.in_point + self._original_duration
            self._model.clipResized.emit(self._clip_id, self._original_duration)
        if self._new_clip_id:
            self._model.remove_clip(self._new_clip_id)
        if clip:
            track = self._model.get_track(clip.track_id)
            if track and track.is_main_track:
                self._model.recalculate_main_storyline(track)
            else:
                self._model.recalculate_project_duration()

    def description(self) -> str:
        return "Cắt clip"


class TrimClipCommand(Command):
    """Cắt mép trái (from_start=True) hoặc mép phải clip — một bước undo.

    Hình học giao hoàn toàn cho `model.resize_clip`: chính hàm đó kẹp trần nguồn
    theo tốc độ (core/timeline_model.py:1054) và tính lại ripple cho Main
    Storyline, nên thẻ thuộc tính và handle kéo trên timeline ra cùng một con số.
    Lệnh này không tự viết lại phép kẹp đó.
    """

    def __init__(self, model, clip_id: str, new_duration: float,
                 from_start: bool = False):
        self._model = model
        self._clip_id = clip_id
        self._new_duration = new_duration
        self._from_start = from_start
        self._before: tuple = ()
        self._applied = False

    def _geometry(self) -> tuple:
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return ()
        return (float(clip.start_time), float(clip.duration),
                float(clip.in_point), float(clip.out_point))

    def _write(self, geometry: tuple):
        clip, track = self._model._find_clip(self._clip_id)
        if clip is None:
            return
        start_time, duration, in_point, out_point = geometry
        clip.start_time = max(0.0, start_time)
        clip.duration = max(0.1, duration)
        clip.in_point = max(0.0, in_point)
        clip.out_point = out_point
        if track and track.is_main_track:
            self._model.recalculate_main_storyline(track)
        else:
            self._model.recalculate_project_duration()
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def execute(self):
        self._before = self._geometry()
        if not self._before:
            return
        self._model.resize_clip(self._clip_id, self._new_duration,
                                self._from_start)
        after = self._geometry()
        # resize_clip im lặng bỏ qua khi track bị khoá; ghi ngược một hình học
        # chưa từng được áp là lệnh undo giả.
        self._applied = bool(after) and any(
            abs(old - new) > 0.0001 for old, new in zip(self._before, after))

    def undo(self):
        if self._applied and self._before:
            self._write(self._before)

    def description(self) -> str:
        return "Cắt đầu clip" if self._from_start else "Cắt cuối clip"


class ApplyEffectCommand(Command):
    """Áp dụng hiệu ứng lên clip."""

    def __init__(self, model, clip_id: str, effect_data: dict):
        """
        effect_data: dict từ EFFECT_CATEGORIES, chứa name, category, icon, ...
        """
        self._model = model
        self._clip_id = clip_id
        self._effect_data = effect_data
        self._effect_name = effect_data.get("name", "")
        self._category = effect_data.get("category", "")
        self._added_index: int = -1

    def execute(self):
        from core.timeline_model import EffectData, EFFECT_PRESETS
        clip = self._model.get_clip(self._clip_id)
        if not clip:
            return
        # Nếu hiệu ứng cùng tên đã tồn tại → bỏ qua
        for e in clip.effects:
            if e.name == self._effect_name:
                return
        preset = EFFECT_PRESETS.get(self._effect_name, {})
        effect = EffectData(
            name=self._effect_name,
            category=self._category,
            intensity=1.0,
            params=dict(preset),
        )
        clip.effects.append(effect)
        self._added_index = len(clip.effects) - 1
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if clip and 0 <= self._added_index < len(clip.effects):
            clip.effects.pop(self._added_index)
            self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        return f"Áp dụng hiệu ứng: {self._effect_name}"


class RemoveEffectCommand(Command):
    """Xóa hiệu ứng khỏi clip."""

    def __init__(self, model, clip_id: str, effect_name: str):
        self._model = model
        self._clip_id = clip_id
        self._effect_name = effect_name
        self._removed_effect = None
        self._removed_index: int = -1

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if not clip:
            return
        for i, e in enumerate(clip.effects):
            if e.name == self._effect_name:
                self._removed_effect = e
                self._removed_index = i
                clip.effects.pop(i)
                self._model.clipResized.emit(self._clip_id, clip.duration)
                return

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if clip and self._removed_effect is not None:
            clip.effects.insert(self._removed_index, self._removed_effect)
            self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        return f"Xóa hiệu ứng: {self._effect_name}"


class SetGradingCommand(Command):
    """Đổi một nút của bo chỉnh màu: hue / lift / gamma / gain / LUT.

    Một clip chỉ có DUY NHẤT một EffectData tên "Chinh mau". Bảy lần gõ từ bảy
    slider mà mỗi lần thêm một hiệu ứng thì chuỗi lọc chạy bảy lượt và file
    .clinq đầy rác — nên lệnh này HỢP NHẤT vào params của thẻ đã có.

    Ngược lại, khi người dùng thả hết về trung tính thì thẻ bị XOÁ: giữ lại một
    bo số không làm đổi lấy một pixel là bắt máy cấu hình thấp mở numpy mỗi
    frame vô ích (đường tắt trong apply_color_effects chỉ bật khi có khoá thật).

    Bảy slider kéo liên tục trong MERGE_WINDOW_S được gom thành MỘT bước undo:
    kéo tông màu tới đáy rồi Ctrl+Z phải trả về đúng lúc chưa kéo, không phải
    lùi từng nấc.
    """

    MERGE_WINDOW_S = 0.75
    LABELS = {"hue_shift": "tông màu", "lift": "lift", "gamma": "gamma",
              "gain": "gain", "lut_path": "LUT"}

    def __init__(self, model, clip_id: str, params: dict):
        from core.clip_effects import GRADING_KEYS
        self._model = model
        self._clip_id = clip_id
        self._requested = {key: value for key, value in (params or {}).items()
                           if key in GRADING_KEYS and value is not None}
        self._before = None          # (index, EffectData|None, params|None)
        self._at = time.monotonic()

    @staticmethod
    def _index(clip, name) -> int:
        for i, effect in enumerate(clip.effects):
            if effect.name == name:
                return i
        return -1

    def execute(self):
        from core.clip_effects import (GRADING_EFFECT_NAME, GRADING_IDENTITY,
                                       grading_is_identity)
        from core.timeline_model import EffectData
        clip = self._model.get_clip(self._clip_id)
        if clip is None or not self._requested:
            return
        index = self._index(clip, GRADING_EFFECT_NAME)
        old = clip.effects[index] if index >= 0 else None
        self._before = (index, old, dict(old.params) if old else None)
        merged = dict(GRADING_IDENTITY)
        merged.update(old.params if old is not None else {})
        merged.update(self._requested)
        if grading_is_identity(merged):
            if index >= 0:
                clip.effects.pop(index)
        elif old is not None:
            old.params = merged
        else:
            clip.effects.append(EffectData(
                name=GRADING_EFFECT_NAME, category=GRADING_EFFECT_NAME,
                intensity=1.0, params=merged))
        self._model.clipUpdated.emit(self._clip_id)

    def undo(self):
        from core.clip_effects import GRADING_EFFECT_NAME
        clip = self._model.get_clip(self._clip_id)
        if clip is None or self._before is None:
            return
        index, old, old_params = self._before
        current = self._index(clip, GRADING_EFFECT_NAME)
        if current >= 0:
            clip.effects.pop(current)
        if old is not None:
            old.params = old_params
            clip.effects.insert(min(index, len(clip.effects)), old)
        self._model.clipUpdated.emit(self._clip_id)

    def merges_with(self, other: "Command") -> bool:
        if not isinstance(other, SetGradingCommand):
            return False
        if other._clip_id != self._clip_id:
            return False
        keys = set(self._requested)
        if keys != set(other._requested) or not keys:
            return False
        return other._at - self._at <= self.MERGE_WINDOW_S

    def absorb(self, other: "SetGradingCommand"):
        self._requested = dict(other._requested)
        self._at = other._at

    def description(self) -> str:
        parts = [self.LABELS.get(key, key) for key in sorted(self._requested)]
        return ("Chỉnh màu: " + ", ".join(parts)) if parts else "Chỉnh màu"


class SetChromaCommand(Command):
    """Đổi một núm của bộ dục nền: màu khoá / tolerance / feather / spill.

    Anh em sinh đôi với SetGradingCommand nhưng KHÔNG kế thừa chung: bản đó đã
    được ba probe đổi-byte bám vào từng dòng (color_grading_counterfactual.py),
    nên gộp thành một base sẽ làm chúng khập khiễng vì lý do kỹ thuật chứ không
    phải vì lỗi thật. Hợp đồng giữ nguyên: một clip đúng một EffectData
    "Chroma key", kéo trượt trong MERGE_WINDOW_S gom thành một bước undo, và
    thả về trung tính thì boc thẻ — tolerance 0 mà để thẻ lại thì
    apply_color_effects mở numpy tính matte vô ích mỗi frame.
    """

    MERGE_WINDOW_S = 0.75
    LABELS = {"key_color": "màu nền", "tolerance": "dung sai",
              "feather": "viền mềm", "spill": "chống ám màu"}

    def __init__(self, model, clip_id: str, params: dict):
        from core.clip_effects import CHROMA_KEYS
        self._model = model
        self._clip_id = clip_id
        self._requested = {key: value for key, value in (params or {}).items()
                           if key in CHROMA_KEYS and value is not None}
        self._before = None          # (index, EffectData|None, params|None)
        self._at = time.monotonic()

    @staticmethod
    def _index(clip, name) -> int:
        for i, effect in enumerate(clip.effects):
            if effect.name == name:
                return i
        return -1

    def execute(self):
        from core.clip_effects import (CHROMA_EFFECT_NAME, CHROMA_IDENTITY,
                                       chroma_is_identity)
        from core.timeline_model import EffectData
        clip = self._model.get_clip(self._clip_id)
        if clip is None or not self._requested:
            return
        index = self._index(clip, CHROMA_EFFECT_NAME)
        old = clip.effects[index] if index >= 0 else None
        self._before = (index, old, dict(old.params) if old else None)
        merged = dict(CHROMA_IDENTITY)
        merged.update(old.params if old is not None else {})
        merged.update(self._requested)
        if chroma_is_identity(merged):
            if index >= 0:
                clip.effects.pop(index)
        elif old is not None:
            old.params = merged
        else:
            clip.effects.append(EffectData(
                name=CHROMA_EFFECT_NAME, category=CHROMA_EFFECT_NAME,
                intensity=1.0, params=merged))
        self._model.clipUpdated.emit(self._clip_id)

    def undo(self):
        from core.clip_effects import CHROMA_EFFECT_NAME
        clip = self._model.get_clip(self._clip_id)
        if clip is None or self._before is None:
            return
        index, old, old_params = self._before
        current = self._index(clip, CHROMA_EFFECT_NAME)
        if current >= 0:
            clip.effects.pop(current)
        if old is not None:
            old.params = old_params
            clip.effects.insert(min(index, len(clip.effects)), old)
        self._model.clipUpdated.emit(self._clip_id)

    def merges_with(self, other: "Command") -> bool:
        if not isinstance(other, SetChromaCommand):
            return False
        if other._clip_id != self._clip_id:
            return False
        keys = set(self._requested)
        if keys != set(other._requested) or not keys:
            return False
        return other._at - self._at <= self.MERGE_WINDOW_S

    def absorb(self, other: "SetChromaCommand"):
        self._requested = dict(other._requested)
        self._at = other._at

    def description(self) -> str:
        parts = [self.LABELS.get(key, key) for key in sorted(self._requested)]
        return ("Dục nền: " + ", ".join(parts)) if parts else "Dục nền"


class SetTransitionCommand(Command):
    """Gắn/xóa chuyển tiếp ở mép trái clip.

    Transition là ripple edit (các clip sau trượt trái để tạo chồng lấn), nên
    hoàn tác phải trả lại cả vị trí lẫn transition — chỉ xóa dict là còn lại
    timeline bị lệch một đoạn ``duration``.
    """

    def __init__(self, model, clip_id: str, name: str, duration: float = None):
        self._model = model
        self._clip_id = clip_id
        self._name = name
        self._duration = duration
        self._before_positions: dict[str, float] = {}
        self._before_transition: dict = {}
        self._applied = ""

    def _snapshot(self):
        self._before_positions = {
            clip.clip_id: clip.start_time
            for track in self._model.tracks for clip in track.clips
        }
        clip = self._model.get_clip(self._clip_id)
        self._before_transition = dict(getattr(clip, "transition", {}) or {})

    def _restore(self, transition: dict):
        clip = self._model.get_clip(self._clip_id)
        if clip is not None:
            clip.transition = dict(transition or {})
        for clip_id, start_time in self._before_positions.items():
            moved = self._model.get_clip(clip_id)
            if moved is not None and abs(moved.start_time - start_time) > 0.0001:
                moved.start_time = start_time
                self._model.clipMoved.emit(clip_id, start_time)
        self._model.recalculate_project_duration()
        self._model.clipUpdated.emit(self._clip_id)

    def execute(self):
        self._snapshot()
        applied = self._model.set_transition(
            self._clip_id, self._name, self._duration)
        self._applied = self._name if applied else ""
        if not applied:
            self._restore(self._before_transition)

    def undo(self):
        self._restore(self._before_transition)

    def description(self) -> str:
        if self._name:
            return "Đặt chuyển tiếp: %s" % self._name
        return "Bỏ chuyển tiếp"


class SetClipAudioCommand(Command):
    """Đổi âm lượng / tốc độ / fade in-out / cờ tắt tiếng của một clip.

    Tốc độ KHÔNG chỉ là một con số âm thanh: nó đổi cả duration (khi nguồn cạn)
    lẫn cửa sổ nguồn mà dải hình và cây sóng đang vẽ, nên snapshot phải lưu nguyên
    phần hình học. Một lệnh undo chỉ trả volume mà để clip bị co thì người dùng
    mất đoạn clip mà không biết vì sao.
    """

    FIELDS = ("volume", "speed", "fade_in", "fade_out", "audio_muted")

    def __init__(self, model, clip_id: str, volume=None, speed=None,
                 fade_in=None, fade_out=None, audio_muted=None):
        self._model = model
        self._clip_id = clip_id
        self._requested = {"volume": volume, "speed": speed,
                           "fade_in": fade_in, "fade_out": fade_out,
                           "audio_muted": audio_muted}
        self._before: dict = {}
        self._before_geometry: tuple = ()
        self._applied: dict = {}

    def _snapshot(self):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        self._before = {
            key: (bool(getattr(clip, key)) if key in ("audio_muted",)
                  else float(getattr(clip, key)))
            for key in self.FIELDS}
        self._before_geometry = (
            float(clip.start_time), float(clip.duration),
            float(clip.in_point), float(clip.out_point),
        )

    def _write(self, values: dict, geometry: tuple, speed: float):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        clip.volume = values["volume"]
        clip.fade_in = values["fade_in"]
        clip.fade_out = values["fade_out"]
        clip.audio_muted = bool(values["audio_muted"])
        clip.speed = speed
        (start_time, duration, in_point, out_point) = geometry
        clip.start_time = start_time
        clip.duration = duration
        clip.in_point = in_point
        clip.out_point = out_point
        self._model.recalculate_project_duration()
        self._model.clipResized.emit(self._clip_id, duration)
        self._model.clipUpdated.emit(self._clip_id)

    def execute(self):
        self._snapshot()
        if not self._before:
            return
        applied = self._model.set_clip_audio(self._clip_id, **self._requested)
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        # set_clip_audio đã clamp; đổi tốc độ có thể co duration, nên chiều hoàn
        # tác phải biết cả hình học sau lệnh này (undo() trả về _before_geometry).
        applied["speed"] = float(clip.speed)
        # Clip bị khóa hoặc đã mất giữa đường: set_clip_audio trả {} nên không
        # được giữ _before, nếu không undo() ghi ngược một dict thiếu khoá.
        asked = {key for key, value in self._requested.items()
                 if value is not None}
        if not asked.issubset(set(applied)):
            self._before = {}
            return
        self._applied = applied

    def undo(self):
        if not self._before:
            return
        self._write(self._before, self._before_geometry, self._before["speed"])

    def description(self) -> str:
        parts = []
        if self._requested["volume"] is not None:
            parts.append("âm lượng")
        if self._requested["speed"] is not None:
            parts.append("tốc độ")
        if (self._requested["fade_in"] is not None or
                self._requested["fade_out"] is not None):
            parts.append("fade")
        if self._requested["audio_muted"] is not None:
            parts.append("tắt tiếng")
        return ("Đổi " + " + ".join(parts)) if parts else "Đổi audio clip"


def transform_snapshot(clip) -> dict:
    """Ảnh 6 số hình học của clip — định dạng mà SetClipTransformCommand hiểu."""
    t = clip.transform
    return {key: float(getattr(t, key))
            for key in ("x", "y", "scale_x", "scale_y", "rotation", "opacity")}


class SetClipTextCommand(Command):
    """Đổi chữ của một clip: nội dung, font, cỡ, đậm/nghiên/gạch, màu, kiểu chạy.

    Panel gõ chữ không còn ghi thẳng vào ``clip_model`` nữa: một lệnh chữ nằm
    ngoài UndoStack nghĩa là Ctrl+Z của người dùng bỏ qua luôn thao tác mà họ
    vừa làm nhiều nhất. Mười trường đi chung MỘT lệnh vì undo từng phần sẽ
    khiến khối chữ nhảy kiểu giữa hai lần hoàn tác.
    """

    FIELDS = ("name", "font_family", "font_size", "font_bold", "font_italic",
              "font_underline", "font_color", "text_effect",
              "text_effect_intensity", "text_style",
              "text_outline_color", "text_outline_width",
              "text_shadow_color", "text_shadow_dx", "text_shadow_dy",
              "text_shadow_blur", "text_box_color", "text_box_alpha",
              "text_box_radius", "text_box_padding", "text_align")
    BOOLS = ("font_bold", "font_italic", "font_underline")
    NUMBERS = ("font_size", "text_effect_intensity",
               "text_outline_width", "text_shadow_dx", "text_shadow_dy",
               "text_shadow_blur", "text_box_alpha", "text_box_radius",
               "text_box_padding")
    # Ba trường này đổi liên tục từng nấc (gõ chữ, kéo spin) -> gộp một bước.
    MERGES_WITH = ("name", "font_size", "text_effect_intensity",
                   "text_outline_width", "text_shadow_dx", "text_shadow_dy",
                   "text_shadow_blur", "text_box_alpha", "text_box_radius",
                   "text_box_padding")
    # Hai lần spin cách nhau lâu hơn mức này là hai thao tác riêng biệt.
    MERGE_WINDOW_S = 0.75

    def __init__(self, model, clip_id: str, **values):
        self._model = model
        self._clip_id = clip_id
        self._requested = {key: self._cast(key, values[key])
                           for key in self.FIELDS
                           if values.get(key) is not None}
        self._before: dict = {}
        self._applied: dict = {}
        self._at = time.monotonic()

    @classmethod
    def _cast(cls, key: str, value):
        if key in cls.BOOLS:
            return bool(value)
        if key in cls.NUMBERS:
            return float(value)
        return str(value)

    def _read(self) -> dict:
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return {}
        return {key: self._cast(key, getattr(clip, key)) for key in self.FIELDS}

    def _write(self, values: dict):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        for key, value in values.items():
            setattr(clip, key, value)
        self._model.clipUpdated.emit(self._clip_id)

    def execute(self):
        self._before = self._read()
        if not self._before:
            return
        applied = dict(self._before)
        applied.update(self._requested)
        self._write(applied)
        self._applied = {key: applied[key] for key in self._requested}

    def undo(self):
        if not self._before:
            return
        self._write(self._before)

    def merges_with(self, other: "Command") -> bool:
        if not isinstance(other, SetClipTextCommand):
            return False
        if other._clip_id != self._clip_id:
            return False
        keys = set(self._requested)
        if keys != set(other._requested) or not keys:
            return False
        if not all(key in self.MERGES_WITH for key in keys):
            return False
        return other._at - self._at <= self.MERGE_WINDOW_S

    def absorb(self, other: "Command"):
        self._requested = dict(other._requested)
        self._applied = dict(other._applied)
        self._at = other._at

    def description(self) -> str:
        parts = []
        if "name" in self._requested:
            parts.append("nội dung")
        if {"font_family", "font_size", "font_color"}.intersection(self._requested):
            parts.append("font")
        if any(key in self._requested for key in self.BOOLS):
            parts.append("kiểu chữ")
        if {"text_effect", "text_effect_intensity", "text_style"}.intersection(
                self._requested):
            parts.append("chữ chạy")
        return ("Đổi chữ: " + ", ".join(parts)) if parts else "Đổi chữ clip"


class SetClipTransformCommand(Command):
    """Đổi hình học clip (vị trí, tỷ lệ, xoay, opacity) và tên hiển thị.

    Viết qua ``model.update_clip_properties`` chứ không tự ghi ``clip.transform``:
    đó là đường duy nhất phát ``clipUpdated`` cho scene vẽ lại nhãn.

    Kéo trên Canvas KHÔNG tự snapshot lúc execute() được, vì item đã ghi kết quả
    vào model trước khi lệnh chạy — lệnh phải nhận ``before=`` từ chỗ bắt đầu
    gesture, nếu không Ctrl+Z trả lại đúng giá trị vừa kéo và người dùng tưởng
    nút undo hỏng.
    """

    FIELDS = ("x", "y", "scale_x", "scale_y", "rotation", "opacity")
    MERGES_WITH = FIELDS
    MERGE_WINDOW_S = 0.75

    def __init__(self, model, clip_id: str, name=None, before=None, **values):
        self._model = model
        self._clip_id = clip_id
        requested = {}
        for key in self.FIELDS:
            if values.get(key) is not None:
                requested[key] = float(values[key])
        if name is not None:
            requested["name"] = str(name)
        self._requested = requested
        self._gesture_before = dict(before) if before else None
        self._before: dict = {}
        self._before_name = ""
        self._at = time.monotonic()

    def _write(self, values: dict):
        self._model.update_clip_properties(
            self._clip_id,
            name=values.get("name"),
            scale_x=values.get("scale_x"), scale_y=values.get("scale_y"),
            rotation=values.get("rotation"), opacity=values.get("opacity"),
            x=values.get("x"), y=values.get("y"),
        )

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        live = transform_snapshot(clip)
        self._before_name = str(clip.name)
        self._before = dict(self._gesture_before) if self._gesture_before else live
        self._write(self._requested)

    def undo(self):
        if not self._before:
            return
        values = dict(self._before)
        values["name"] = self._before_name
        self._write(values)

    def merges_with(self, other: "Command") -> bool:
        if not isinstance(other, SetClipTransformCommand):
            return False
        if other._clip_id != self._clip_id:
            return False
        # Gesture trên Canvas luôn là một bước riêng, không hòa vào lệnh trước.
        if self._gesture_before is not None or other._gesture_before is not None:
            return False
        if set(self._requested) != set(other._requested):
            return False
        return other._at - self._at <= self.MERGE_WINDOW_S

    def absorb(self, other: "Command"):
        self._requested = dict(other._requested)
        self._at = other._at

    def description(self) -> str:
        labels = {"x": "vị trí X", "y": "vị trí Y", "scale_x": "rộng",
                  "scale_y": "cao", "rotation": "xoay", "opacity": "mờ",
                  "name": "tên"}
        parts = [labels[key] for key in self.FIELDS + ("name",)
                 if key in self._requested]
        return ("Đổi " + " + ".join(parts)) if parts else "Đổi hình học clip"


# ── Keyframe Commands ──────────────────────────────────────────

class ToggleKeyframeCommand(Command):
    """Thêm/xóa keyframe tại thời điểm chỉ định (nút diamond ⬦)."""

    def __init__(self, model, clip_id: str, property_key: str,
                 time_sec: float, value: float):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._time_sec = time_sec
        self._value = value
        self._was_added: bool = False

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            self._was_added = clip.toggle_keyframe_at(
                self._property_key, self._time_sec, self._value
            )
            self._model.clipResized.emit(self._clip_id, clip.duration)

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            frames = clip.keyframes.get(self._property_key, [])
            for i, frame in enumerate(frames):
                if abs(frame[0] - self._time_sec) < 0.01:
                    frames.pop(i)
                    break
            self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        action = "Thêm" if self._was_added else "Xóa"
        return f"{action} keyframe {self._property_key}"


class DragKeyframeCommand(Command):
    """Kéo thả keyframe node trên timeline sang vị trí mới."""

    def __init__(self, model, clip_id: str, property_key: str,
                 old_time: float, new_time: float, value: float):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._old_time = old_time
        self._new_time = new_time
        self._value = value

    def _move(self, clip, from_time, to_time):
        from core.keyframe_manager import frame_ease, make_frame
        frames = clip.keyframes.get(self._property_key, [])
        for i, frame in enumerate(frames):
            if abs(frame[0] - from_time) < 0.05:
                # Kéo thả chỉ đổi THỜI GIAN: đường cong của keyframe phải đi
                # theo, nếu không mỗi lần chỉnh vị trí là một lần mất easing.
                frames[i] = make_frame(to_time, self._value, frame_ease(frame))
                break
        frames.sort(key=lambda k: k[0])
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            self._move(clip, self._old_time, self._new_time)

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if clip:
            self._move(clip, self._new_time, self._old_time)

    def description(self) -> str:
        return f"Di chuyển keyframe {self._property_key}"


class AddKeyframeCommand(Command):
    """Chen MOT moc moi. Khong dung ToggleKeyframeCommand o day: toggle xoa
    khi da co moc, ma nguong thoi gian (0.05 s) rong hon nguong bam cua do
    thi, nen bam them o gan moc cu se xoa bom moc khong nhin thay."""

    TOLERANCE = 0.05

    def __init__(self, model, clip_id: str, property_key: str,
                 time_sec: float, value: float, ease: str = None):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._time_sec = float(time_sec)
        self._value = float(value)
        self._ease = ease
        self._replaced = None

    def execute(self):
        from core.keyframe_manager import frame_ease, make_frame
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        frames = clip.keyframes.setdefault(self._property_key, [])
        for i, frame in enumerate(frames):
            if abs(frame[0] - self._time_sec) <= self.TOLERANCE:
                self._replaced = tuple(frame)
                # Khong noi ro duong cong thi GIU cua moc cu — dung qua tac
                # ma model.add_keyframe da bao ve: doi so khong duoc xoa bom
                # duong cong nguoi ta da chon.
                keep = self._ease if self._ease is not None else frame_ease(frame)
                frames[i] = make_frame(self._time_sec, self._value, keep)
                break
        else:
            frames.append(make_frame(self._time_sec, self._value,
                                     self._ease or "linear"))
            frames.sort(key=lambda k: k[0])
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        frames = clip.keyframes.get(self._property_key, [])
        for i, frame in enumerate(frames):
            if abs(frame[0] - self._time_sec) <= self.TOLERANCE:
                if self._replaced is not None:
                    frames[i] = self._replaced
                else:
                    frames.pop(i)
                break
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        return f"Thêm keyframe {self._property_key}"


class EditKeyframeCommand(Command):
    """Kéo một moc tren do thi: doi THOI GIAN va/hoi GIA TRI, giu duong cong.

    DragKeyframeCommand (timeline) chi keo doc truc X, nen khong dung duoc o
    day. Lenh luu frame cu NGUYEN VEN (khi ca hai chieu) va tim lai theo
    duong moi khi hoan tac, neu khong thi hoan tac mot lan keo doi goc se
    tra node ve sai moc.
    """

    TOLERANCE = 0.05

    def __init__(self, model, clip_id: str, property_key: str,
                 old_time: float, new_time: float, new_value: float):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._old_time = float(old_time)
        self._new_time = float(new_time)
        self._new_value = float(new_value)
        self._old_frame = None
        self._applied = False

    def _frames(self, clip):
        return clip.keyframes.setdefault(self._property_key, [])

    def _find(self, frames, at_time):
        best, best_gap = None, None
        for frame in frames:
            gap = abs(frame[0] - at_time)
            if gap <= self.TOLERANCE and (best_gap is None or gap < best_gap):
                best, best_gap = frame, gap
        return best

    def _replace(self, clip, match_time, frame):
        frames = self._frames(clip)
        target = self._find(frames, match_time)
        if target is None:
            return False
        frames[frames.index(target)] = frame
        frames.sort(key=lambda k: k[0])
        self._model.clipResized.emit(self._clip_id, clip.duration)
        return True

    def execute(self):
        from core.keyframe_manager import frame_ease, make_frame
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        current = self._find(self._frames(clip), self._old_time)
        if current is None:
            return
        self._old_frame = tuple(current)
        self._applied = self._replace(
            clip, self._old_time,
            make_frame(self._new_time, self._new_value, frame_ease(current)))

    def undo(self):
        if not self._applied or self._old_frame is None:
            return
        clip = self._model.get_clip(self._clip_id)
        if clip is not None:
            self._replace(clip, self._new_time, tuple(self._old_frame))

    def description(self) -> str:
        return f"Sửa keyframe {self._property_key}"


class RemoveKeyframeCommand(Command):
    """Xoa MOT moc cu the (khong phai toggle): undo phai tra lai dung frame,
    dung ca duong cong nguoi ta da chon."""

    TOLERANCE = 0.05

    def __init__(self, model, clip_id: str, property_key: str, time_sec: float):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._time_sec = float(time_sec)
        self._removed = None

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        frames = clip.keyframes.get(self._property_key, [])
        best, best_gap = None, None
        for frame in frames:
            gap = abs(frame[0] - self._time_sec)
            if gap <= self.TOLERANCE and (best_gap is None or gap < best_gap):
                best, best_gap = frame, gap
        if best is None:
            return
        self._removed = tuple(best)
        frames.remove(best)
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def undo(self):
        if self._removed is None:
            return
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        frames = clip.keyframes.setdefault(self._property_key, [])
        frames.append(self._removed)
        frames.sort(key=lambda k: k[0])
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        return f"Xóa keyframe {self._property_key}"


class SetKeyframeEaseCommand(Command):
    """Chọn đường cong nội suy cho MỘT keyframe — undo được, như mọi sửa model khác."""

    def __init__(self, model, clip_id: str, property_key: str,
                 time_sec: float, new_ease: str):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._time_sec = time_sec
        self._new_ease = new_ease
        self._old_ease = None

    def _apply(self, ease):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return False
        changed = clip.set_keyframe_ease(self._property_key, self._time_sec,
                                         ease)
        if changed:
            self._model.clipResized.emit(self._clip_id, clip.duration)
        return changed

    def execute(self):
        clip = self._model.get_clip(self._clip_id)
        if clip is None:
            return
        self._old_ease = clip.get_keyframe_ease(self._property_key,
                                                self._time_sec)
        self._apply(self._new_ease)

    def undo(self):
        if self._old_ease is not None:
            self._apply(self._old_ease)

    def description(self) -> str:
        return f"Đổi đường cong keyframe {self._property_key}"


class AutoKeyframeCommand(Command):
    """Tự động thêm/ghi đè keyframe khi thay đổi giá trị spin (auto-keyframe)."""

    def __init__(self, model, clip_id: str, property_key: str,
                 time_sec: float, old_value: float, new_value: float):
        self._model = model
        self._clip_id = clip_id
        self._property_key = property_key
        self._time_sec = time_sec
        self._old_value = old_value
        self._new_value = new_value
        self._had_existing: bool = False
        self._old_frame = None

    def execute(self):
        from core.keyframe_manager import frame_ease, make_frame
        clip = self._model.get_clip(self._clip_id)
        if not clip:
            return
        frames = clip.keyframes.get(self._property_key, [])
        for i, frame in enumerate(frames):
            if abs(frame[0] - self._time_sec) < 0.01:
                self._had_existing = True
                self._old_frame = tuple(frame)   # giữ nguyên cả đường cong
                frames[i] = make_frame(frame[0], self._new_value,
                                       frame_ease(frame))
                self._model.clipResized.emit(self._clip_id, clip.duration)
                return
        clip.add_keyframe(self._property_key, self._time_sec, self._new_value)
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def undo(self):
        clip = self._model.get_clip(self._clip_id)
        if not clip:
            return
        frames = clip.keyframes.get(self._property_key, [])
        if self._had_existing and self._old_frame:
            for i, frame in enumerate(frames):
                if abs(frame[0] - self._time_sec) < 0.01:
                    frames[i] = self._old_frame
                    break
        else:
            for i, frame in enumerate(frames):
                if abs(frame[0] - self._time_sec) < 0.01:
                    frames.pop(i)
                    break
        self._model.clipResized.emit(self._clip_id, clip.duration)

    def description(self) -> str:
        return f"Auto-keyframe {self._property_key}"


class SetRecapOverlayCommand(Command):
    """Đổi lớp phủ recap của CẢ dự án — một bước undo cho cả hộp thoại.

    Settings đã qua core.recap_overlay.normalize nên đủ 13 khoá; snapshot lúc
    tạo để hoàn tác trả lại nguyên trạng, kể cả với file cũ mở lên chưa từng có
    khoá nào (lúc đó "before" chính là mặc định tắt).
    """

    def __init__(self, model, settings, before=None):
        """``before`` bắt buộc phải truyền khi hộp thoại đã áp dụng thay đổi
        THỜI GIAN THỰC: nếu để lệnh tự snapshot lúc tạo thì nó chụp đúng trạng
        thái "sau", và undo trở thành phép thế chỗ cho chính nó."""
        self._model = model
        self._after = dict(settings)
        self._before = dict(before if before is not None else model.recap_overlay)

    def execute(self):
        self._model.set_recap_overlay(self._after)

    def undo(self):
        self._model.set_recap_overlay(self._before)

    def description(self) -> str:
        on = bool(self._after.get("enabled"))
        return "Lớp phủ recap: %s" % ("bật" if on else "tắt")


class InsertCaptionsCommand(Command):
    """Chèn cả loạt phụ đề như MỘT bước undo — hoàn tác một lần là sạch cả lane."""

    def __init__(self, model, planned, style=None, canvas=(1920, 1080)):
        self._model = model
        self._planned = list(planned)
        self._style = dict(style or {})
        self._canvas = canvas
        self._clip_ids: list[str] = []

    def execute(self):
        from core.auto_captions import caption_track, style_caption_clip
        # undo() xoá clip cuối cùng thì model cũng xoá luôn track trống, nên
        # redo phải xin track chữ mới chứ không thể giữ id cũ.
        track = caption_track(self._model)
        self._clip_ids = []
        for start, duration, text in self._planned:
            clip = self._model.add_clip(track.track_id, "", "text",
                                        start, duration, text)
            if clip is None:
                continue
            style_caption_clip(clip, self._style, self._canvas)
            self._clip_ids.append(clip.clip_id)

    def undo(self):
        for clip_id in reversed(self._clip_ids):
            self._model.remove_clip(clip_id)
        self._clip_ids = []

    def description(self) -> str:
        return "Thêm phụ đề (%d dòng)" % len(self._clip_ids)
