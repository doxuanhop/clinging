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
        """Thực thi command và đẩy vào undo stack."""
        command.execute()
        self._undo_stack.append(command)
        self._redo_stack.clear()        # Xóa redo khi có action mới

        # Giới hạn lịch sử
        if len(self._undo_stack) > self.MAX_HISTORY:
            self._undo_stack.pop(0)

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
