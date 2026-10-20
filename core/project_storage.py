"""
core/project_storage.py
Quản lý lưu/tải dự án Clinqing theo kiến trúc CapCut-style.

Triết lý:
  - Chỉnh sửa phi phá hủy (Non-destructive Editing)
  - Cơ sở dữ liệu dạng văn bản (Text-based JSON)
  - Asset Linking: chỉ lưu đường dẫn, không copy file gốc
  - UUID-based identification cho mọi đối tượng

Cấu trúc file .clinq:
  project_meta  → Thông tin dự án (tên, resolution, FPS, thời gian)
  assets        → Kho tài nguyên (đường dẫn file gốc, type, duration)
  timeline      → Tracks + Clips + Transform + Keyframes
"""

import os
import json
import uuid
import time
from datetime import datetime
from typing import Optional


# ── Đường dẫn lưu trữ ──────────────────────────────────────────
APP_DIR = os.path.join(os.path.expanduser("~"), ".clinqing")
AUTO_SAVE_FILE = os.path.join(APP_DIR, "autosave.json")


def _ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)


# ── Serialize / Deserialize ────────────────────────────────────

def serialize_transform(transform) -> dict:
    """Chuyển TransformData thành dict JSON-safe."""
    return {
        "x": round(transform.x, 2),
        "y": round(transform.y, 2),
        "scale_x": round(transform.scale_x, 4),
        "scale_y": round(transform.scale_y, 4),
        "rotation": round(transform.rotation, 2),
        "opacity": round(transform.opacity, 3),
        "fit_mode": getattr(transform, "fit_mode", "fit"),
        "original_w": round(getattr(transform, "original_w", 0), 1),
        "original_h": round(getattr(transform, "original_h", 0), 1),
    }


def deserialize_transform(data: dict, transform):
    """Khôi phục TransformData từ dict."""
    transform.x = data.get("x", 0.0)
    transform.y = data.get("y", 0.0)
    transform.scale_x = data.get("scale_x", 1.0)
    transform.scale_y = data.get("scale_y", 1.0)
    transform.rotation = data.get("rotation", 0.0)
    transform.opacity = data.get("opacity", 1.0)
    transform.fit_mode = data.get("fit_mode", "fit")
    transform.original_w = data.get("original_w", 0.0)
    transform.original_h = data.get("original_h", 0.0)


def serialize_keyframes(keyframes: dict) -> dict:
    """Chuyển keyframes dict thành JSON-safe dict.

    Phần tử thứ ba là tên đường cong. Project cũ không có phần tử này khi đọc
    lên, và ``deserialize_keyframes`` hiểu thiếu tức là linear.
    """
    from core.keyframe_manager import frame_ease, frame_time, frame_value
    result = {}
    for prop, frames in keyframes.items():
        result[prop] = [[round(frame_time(f), 3), round(frame_value(f), 4),
                         frame_ease(f)] for f in frames]
    return result


def deserialize_keyframes(data: dict) -> dict:
    """Khôi phục keyframes từ dict."""
    from core.keyframe_manager import make_frame
    result = {}
    for prop, frames in data.items():
        rows = []
        for frame in frames:
            t, v = frame[0], frame[1]
            ease = frame[2] if len(frame) > 2 else "linear"
            rows.append(make_frame(t, v, ease))
        rows.sort(key=lambda k: k[0])
        result[prop] = rows
    return result


def serialize_effects(effects: list) -> list:
    """Chuyển list EffectData thành JSON-safe list."""
    return [e.to_dict() for e in effects]


def deserialize_effects(data: list) -> list:
    """Khôi phục list EffectData từ list dict."""
    from core.timeline_model import EffectData
    return [EffectData.from_dict(d) for d in data]


def serialize_transition(transition) -> dict:
    """Chuyển ClipModel.transition thành JSON-safe (rỗng = không có chuyển tiếp)."""
    if not isinstance(transition, dict):
        return {}
    return {"name": transition.get("name", ""),
            "duration": round(float(transition.get("duration", 0.0) or 0.0), 3)}


def deserialize_transition(data) -> dict:
    """Đọc transition từ file cũ: thiếu/sai kiểu đều coi như không có."""
    from core import transitions
    if not isinstance(data, dict):
        return {}
    name = data.get("name", "")
    if name not in transitions.TRANSITIONS:
        return {}
    return transitions.make(name, data.get("duration", 0.0))


# ── Asset Management ───────────────────────────────────────────

def _build_asset_id(asset_dict: dict, source_path: str, media_type: str,
                    clip=None) -> str:
    """
    Tạo hoặc lấy lại asset_id cho file gốc.
    Mỗi file chỉ xuất hiện 1 lần trong block 'assets'.
    """
    if source_path in asset_dict:
        # The library is serialized before timeline clips.  At that point its
        # entry may not know the decoded source duration yet, so enrich the
        # existing asset when the corresponding clip is visited.
        asset = asset_dict[source_path]
        if clip:
            source_duration = float(
                getattr(clip, "source_duration", 0.0) or
                (clip.in_point + clip.duration)
            )
            if source_duration > float(asset.get("original_duration", 0.0)):
                asset["original_duration"] = round(source_duration, 3)
        return asset["_id"]

    asset_id = f"asset-{uuid.uuid4().hex[:12]}"
    original_duration = 0.0
    if clip:
        original_duration = (clip.source_duration or
                             clip.in_point + clip.duration)
    elif media_type == "image":
        original_duration = 0.0

    asset_dict[source_path] = {
        "_id": asset_id,
        "type": media_type,
        "path": source_path,
        "original_duration": round(original_duration, 3),
    }
    return asset_id


# ── Save Project (.clinq format) ──────────────────────────────

def save_project_to_file(model, project_path: str, project_meta: dict = None):
    """
    Lưu toàn bộ trạng thái Timeline ra file .clinq theo định dạng CapCut-style.

    Args:
        model: TimelineModel hiện tại
        project_path: Đường dẫn file .clinq (vd: ~/Clinging_Projects/MyProj/MyProj.clinq)
        project_meta: Dict metadata bổ sung (resolution, fps, aspect_ratio...)
    """
    if not project_meta:
        project_meta = {}

    now = datetime.now().isoformat(timespec="seconds")

    # ── 1. project_meta ──
    meta = {
        "project_id": project_meta.get("project_id", f"proj-{uuid.uuid4().hex[:12]}"),
        "project_name": project_meta.get("project_name", os.path.splitext(os.path.basename(project_path))[0]),
        "created_at": project_meta.get("created_at", now),
        "last_modified": now,
        "resolution": project_meta.get("resolution", {"width": 1920, "height": 1080}),
        "fps": project_meta.get("fps", 30),
        "aspect_ratio": project_meta.get("aspect_ratio", "16:9"),
        "version": "1.0",
    }

    # ── 2. assets (Kho tài nguyên) ──
    assets_dict = {}  # source_path → asset data
    assets_out = {}
    for asset in getattr(model, "library_assets", []):
        source_path = asset.get("path", "")
        media_type = asset.get("type", "video")
        if source_path and media_type in ("video", "audio", "image"):
            _build_asset_id(assets_dict, source_path, media_type)

    # ── 3. timeline > tracks > clips ──
    tracks_out = []

    for track in model.tracks:
        clips_out = []

        for clip in track.clips:
            clip_data = {
                "clip_id": clip.clip_id,
                "timeline_in": round(clip.start_time, 3),
                "timeline_out": round(clip.start_time + clip.duration, 3),
                "duration": round(clip.duration, 3),
                "source_duration": round(
                    getattr(clip, "source_duration", 0.0), 3),
                "transform": serialize_transform(clip.transform),
                "keyframes": serialize_keyframes(clip.keyframes),
                "effects": serialize_effects(getattr(clip, 'effects', [])),
                "transition": serialize_transition(
                    getattr(clip, "transition", {})),
                "font_family": getattr(clip, "font_family", "Arial"),
                "font_size": getattr(clip, "font_size", 40.0),
                "font_bold": getattr(clip, "font_bold", True),
                "font_italic": getattr(clip, "font_italic", False),
                "font_underline": getattr(clip, "font_underline", False),
                "font_color": getattr(clip, "font_color", "#FFFFFF"),
                "text_effect": getattr(clip, "text_effect", "none"),
                "text_effect_intensity": getattr(clip, "text_effect_intensity", 0.6),
                "text_style": getattr(clip, "text_style", "none"),
                "sticker_icon": getattr(clip, "sticker_icon", ""),
                "sticker_color": getattr(clip, "sticker_color", "#FFFFFF"),
                **_audio_fields(clip),
            }

            media_type = clip.media_type

            if media_type in ("video", "image", "audio"):
                # Asset linking: chỉ lưu đường dẫn, không copy file
                asset_id = _build_asset_id(
                    assets_dict, clip.source_path, media_type, clip
                )
                clip_data["asset_id"] = asset_id
                clip_data["trim_in"] = round(clip.in_point, 3)
                clip_data["trim_out"] = round(clip.out_point, 3)
                clip_data["source_path"] = clip.source_path
                clip_data["media_type"] = media_type
                clip_data["name"] = clip.name

            elif media_type == "text":
                clip_data["asset_id"] = None
                clip_data["text_content"] = clip.name
                clip_data["source_path"] = ""
                clip_data["media_type"] = "text"
                clip_data["name"] = clip.name

            else:
                clip_data["asset_id"] = None
                clip_data["source_path"] = clip.source_path
                clip_data["media_type"] = media_type
                clip_data["name"] = clip.name

            clips_out.append(clip_data)

        track_data = {
            "track_id": track.track_id,
            "track_type": track.track_type.name,
            "name": track.name,
            "z_index": track.z_index,
            "is_main_track": track.is_main_track,
            "is_locked": track.is_locked,
            "is_visible": track.is_visible,
            "is_muted": track.is_muted,
            "color": track.color,
            "clips": clips_out,
        }
        tracks_out.append(track_data)

    # Chuyển assets_dict → assets_out (bỏ field _id tạm)
    for source_path, info in assets_dict.items():
        asset_id = info.pop("_id")
        assets_out[asset_id] = info

    # ── 4. Assembly ──
    project_data = {
        "project_meta": meta,
        "assets": assets_out,
        "timeline": {
            "duration": round(model.duration, 3),
            "playhead": round(model.playhead, 3),
            "tracks": tracks_out,
            # Lớp phủ recap là cấu hình dự án, không gắn clip nào, nên nằm ở
            # đây chứ không trong clip_data.
            "recap_overlay": dict(getattr(model, "recap_overlay", {})),
        },
    }

    # ── 5. Write to disk ──
    try:
        os.makedirs(os.path.dirname(project_path), exist_ok=True)
        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(project_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Lỗi lưu dự án: {e}")
        return False


# ── Load Project (.clinq format) ──────────────────────────────

def project_arg_from_argv(argv) -> Optional[str]:
    """Đường dẫn ``.clinq`` mà Explorer đặt vào argv khi nhấp đúp file, hoặc
    đứng sau ``--project`` khi gõ tay. Trả ``None`` khi không có gì để mở.

    Nằm ở đây chứ không nằm trong ``main.py``: bản đóng gói giữ ``main.py`` làm
    ``__main__`` nên không import lại được, còn báo cáo kiểm chứng thì phải đọc
    bằng ĐÚNG hàm mà app thật dùng để parse chuỗi lệnh của nó.
    """
    if "--project" in argv:
        index = argv.index("--project")
        if index + 1 < len(argv):
            return argv[index + 1]
    for arg in argv[1:]:
        if arg.lower().endswith(".clinq") and os.path.isfile(arg):
            return arg
    return None


def load_project_from_file(project_path: str) -> Optional[dict]:
    """Đọc file .clinq và trả về dict."""
    if not os.path.exists(project_path):
        return None
    try:
        with open(project_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Lỗi đọc dự án: {e}")
        return None


def restore_model_from_clinq(model, project: dict):
    """
    Khôi phục TimelineModel từ dữ liệu .clinq.
    Xóa toàn bộ track/clip hiện có trước khi restore.
    """
    from core.timeline_model import (TrackType, ClipModel, TransformData,
                                     track_accepts_media, track_type_for_media)

    # Xóa sạch track cũ
    for track in list(model.tracks):
        model.remove_track(track.track_id)

    meta = project.get("project_meta", {})
    timeline = project.get("timeline", {})
    assets = project.get("assets", {})

    model._project_ratio = meta.get("aspect_ratio", "16:9")
    model._duration = timeline.get("duration", 30.0)

    # File cũ không có khoá này -> set_recap_overlay tự điền mặc định.
    model.set_recap_overlay(timeline.get("recap_overlay"), emit=False)

    for track_data in timeline.get("tracks", []):
        track_type_name = track_data.get("track_type", "VIDEO")
        try:
            track_type = TrackType[track_type_name]
        except KeyError:
            track_type = TrackType.VIDEO

        track = model.add_track(
            track_type, track_data.get("name", ""),
            track_id=track_data.get("track_id", ""),
            is_main_track=track_data.get("is_main_track", False),
            restore_mode=True,
        )
        track.z_index = track_data.get("z_index", 0)
        track.is_locked = track_data.get("is_locked", False)
        track.is_visible = track_data.get("is_visible", True)
        track.is_muted = track_data.get("is_muted", False)

        for clip_data in track_data.get("clips", []):
            transform = TransformData()
            if "transform" in clip_data:
                deserialize_transform(clip_data["transform"], transform)

            keyframes = {}
            if "keyframes" in clip_data:
                keyframes = deserialize_keyframes(clip_data["keyframes"])

            source_path = clip_data.get("source_path", "")
            media_type = clip_data.get("media_type", "video")

            # Kiểm tra file còn tồn tại không
            if media_type in ("video", "image", "audio") and source_path:
                if not os.path.exists(source_path):
                    # Tìm lại file theo tên trong cùng thư mục
                    basename = os.path.basename(source_path)
                    parent_dir = os.path.dirname(source_path)
                    if os.path.exists(parent_dir):
                        for f in os.listdir(parent_dir):
                            if f == basename:
                                source_path = os.path.join(parent_dir, f)
                                break

            target_track = track
            if not track_accepts_media(track.track_type, media_type):
                target_track = model.find_or_create_track(track_type_for_media(media_type))
            clip = ClipModel(
                clip_id=clip_data.get("clip_id", str(uuid.uuid4())),
                start_time=clip_data.get("timeline_in", 0.0),
                duration=clip_data.get("duration", 5.0),
                source_path=source_path,
                media_type=media_type,
                in_point=clip_data.get("trim_in", 0.0),
                out_point=clip_data.get("trim_out", 5.0),
                source_duration=clip_data.get(
                    "source_duration",
                    assets.get(clip_data.get("asset_id", ""), {}).get(
                        "original_duration",
                        max(clip_data.get("trim_out", 0.0),
                            clip_data.get("duration", 5.0)))),
                name=clip_data.get("name", ""),
                transform=transform,
                track_id=target_track.track_id,
                keyframes=keyframes,
                effects=deserialize_effects(clip_data.get("effects", [])),
                transition=deserialize_transition(clip_data.get("transition")),
                font_family=clip_data.get("font_family", "Arial"),
                font_size=clip_data.get("font_size", 40.0),
                font_bold=clip_data.get("font_bold", True),
                font_italic=clip_data.get("font_italic", False),
                font_underline=clip_data.get("font_underline", False),
                font_color=clip_data.get("font_color", "#FFFFFF"),
                text_effect=clip_data.get("text_effect", "none"),
                text_effect_intensity=clip_data.get("text_effect_intensity", 0.6),
                text_style=clip_data.get("text_style", "none"),
                sticker_icon=clip_data.get("sticker_icon", ""),
                sticker_color=clip_data.get("sticker_color", "#FFFFFF"),
                **_audio_values(clip_data),
            )
            target_track.clips.append(clip)
            model.clipAdded.emit(clip)

    for empty_track in list(model.get_empty_tracks()):
        model.remove_track(empty_track.track_id)
    for restored_track in model.tracks:
        if restored_track.is_main_track:
            model.recalculate_main_storyline(restored_track)
    model.recalculate_project_duration()
    model._normalize_track_layers(enforce_main=True)
    model.tracksReordered.emit()
    model.playhead = timeline.get("playhead", 0.0)


# ── Audio per-clip ─────────────────────────────────────────────
# Bốn khoá số này đi qua MỘT chỗ duy nhất cho cả .clinq lẫn autosave legacy. Dự án
# cũ không có chúng thì nhận giá trị mặc định, tức speed=1.0 và giữ nguyên hành
# vi đã lưu.
#
# audio_muted đứng riêng vì nó là bool: vòng float() bên dưới sẽ ghi 0.0/1.0 vào
# file và trả về float khi nạp, tức một cờ bật/tắt bị lưu như một con số.

_AUDIO_DEFAULTS = {"volume": 1.0, "speed": 1.0,
                   "fade_in": 0.0, "fade_out": 0.0}
_AUDIO_FLAGS = {"audio_muted": False}


def _audio_fields(clip) -> dict:
    out = {}
    for key, default in _AUDIO_DEFAULTS.items():
        try:
            out[key] = round(float(getattr(clip, key, default)), 3)
        except (TypeError, ValueError):
            out[key] = default
    for key, default in _AUDIO_FLAGS.items():
        out[key] = bool(getattr(clip, key, default))
    return out


def _audio_values(clip_data) -> dict:
    out = {}
    for key, default in _AUDIO_DEFAULTS.items():
        try:
            out[key] = float(clip_data.get(key, default))
        except (TypeError, ValueError):
            out[key] = default
    for key, default in _AUDIO_FLAGS.items():
        out[key] = bool(clip_data.get(key, default))
    return out


# ── Legacy Autosave (backward compat) ─────────────────────────

def save_project(model, aspect_ratio: str = "16:9", playhead: float = 0.0):
    """Lưu autosave (backward compat với code cũ)."""
    _ensure_dir()

    tracks_data = []
    for track in model.tracks:
        clips_data = []
        for clip in track.clips:
            clip_data = {
                "clip_id": clip.clip_id,
                "start_time": clip.start_time,
                "duration": clip.duration,
                "source_duration": getattr(
                    clip, "source_duration", 0.0),
                "source_path": clip.source_path,
                "media_type": clip.media_type,
                "in_point": clip.in_point,
                "out_point": clip.out_point,
                "name": clip.name,
                "track_id": clip.track_id,
                "transform": serialize_transform(clip.transform),
                "keyframes": serialize_keyframes(clip.keyframes),
                "effects": serialize_effects(getattr(clip, 'effects', [])),
                "transition": serialize_transition(
                    getattr(clip, "transition", {})),
                "font_family": getattr(clip, "font_family", "Arial"),
                "font_size": getattr(clip, "font_size", 40.0),
                "font_bold": getattr(clip, "font_bold", True),
                "font_italic": getattr(clip, "font_italic", False),
                "font_underline": getattr(clip, "font_underline", False),
                "font_color": getattr(clip, "font_color", "#FFFFFF"),
                "text_effect": getattr(clip, "text_effect", "none"),
                "text_effect_intensity": getattr(clip, "text_effect_intensity", 0.6),
                "text_style": getattr(clip, "text_style", "none"),
                "sticker_icon": getattr(clip, "sticker_icon", ""),
                "sticker_color": getattr(clip, "sticker_color", "#FFFFFF"),
                **_audio_fields(clip),
            }
            clips_data.append(clip_data)

        track_data = {
            "track_id": track.track_id,
            "track_type": track.track_type.name,
            "name": track.name,
            "z_index": track.z_index,
            "is_main_track": track.is_main_track,
            "is_locked": track.is_locked,
            "is_visible": track.is_visible,
            "is_muted": track.is_muted,
            "clips": clips_data,
        }
        tracks_data.append(track_data)

    project = {
        "version": "1.0",
        "saved_at": time.time(),
        "aspect_ratio": aspect_ratio,
        "playhead": playhead,
        "duration": model.duration,
        "tracks": tracks_data,
        "library_assets": list(getattr(model, "library_assets", [])),
    }

    try:
        with open(AUTO_SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Lỗi auto-save: {e}")
        return False


def load_project() -> Optional[dict]:
    """Tải autosave (backward compat)."""
    if not os.path.exists(AUTO_SAVE_FILE):
        return None
    try:
        with open(AUTO_SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Lỗi load autosave: {e}")
        return None


def restore_model(model, project: dict):
    """Khôi phục model từ autosave (backward compat)."""
    from core.timeline_model import (TrackType, ClipModel, TransformData,
                                     track_accepts_media, track_type_for_media)

    model._duration = project.get("duration", 30.0)

    for track_data in project.get("tracks", []):
        track_type_name = track_data.get("track_type", "VIDEO")
        try:
            track_type = TrackType[track_type_name]
        except KeyError:
            track_type = TrackType.VIDEO

        track = model.add_track(
            track_type, track_data.get("name", ""),
            track_id=track_data.get("track_id", ""),
            is_main_track=track_data.get("is_main_track", False),
            restore_mode=True,
        )
        track.z_index = track_data.get("z_index", 0)
        track.is_locked = track_data.get("is_locked", False)
        track.is_visible = track_data.get("is_visible", True)
        track.is_muted = track_data.get("is_muted", False)

        for clip_data in track_data.get("clips", []):
            transform = TransformData()
            if "transform" in clip_data:
                deserialize_transform(clip_data["transform"], transform)

            keyframes = {}
            if "keyframes" in clip_data:
                keyframes = deserialize_keyframes(clip_data["keyframes"])

            media_type = clip_data.get("media_type", "video")
            target_track = track
            if not track_accepts_media(track.track_type, media_type):
                target_track = model.find_or_create_track(track_type_for_media(media_type))
            clip = ClipModel(
                clip_id=clip_data.get("clip_id", ""),
                start_time=clip_data.get("start_time", 0.0),
                duration=clip_data.get("duration", 5.0),
                source_path=clip_data.get("source_path", ""),
                media_type=media_type,
                in_point=clip_data.get("in_point", 0.0),
                out_point=clip_data.get("out_point", 5.0),
                source_duration=clip_data.get(
                    "source_duration",
                    max(clip_data.get("out_point", 0.0),
                        clip_data.get("duration", 5.0))),
                name=clip_data.get("name", ""),
                transform=transform,
                track_id=target_track.track_id,
                keyframes=keyframes,
                effects=deserialize_effects(clip_data.get("effects", [])),
                transition=deserialize_transition(clip_data.get("transition")),
                font_family=clip_data.get("font_family", "Arial"),
                font_size=clip_data.get("font_size", 40.0),
                font_bold=clip_data.get("font_bold", True),
                font_italic=clip_data.get("font_italic", False),
                font_underline=clip_data.get("font_underline", False),
                font_color=clip_data.get("font_color", "#FFFFFF"),
                text_effect=clip_data.get("text_effect", "none"),
                text_effect_intensity=clip_data.get("text_effect_intensity", 0.6),
                text_style=clip_data.get("text_style", "none"),
                sticker_icon=clip_data.get("sticker_icon", ""),
                sticker_color=clip_data.get("sticker_color", "#FFFFFF"),
                **_audio_values(clip_data),
            )
            target_track.clips.append(clip)
            model.clipAdded.emit(clip)

    for empty_track in list(model.get_empty_tracks()):
        model.remove_track(empty_track.track_id)
    for restored_track in model.tracks:
        if restored_track.is_main_track:
            model.recalculate_main_storyline(restored_track)
    model.recalculate_project_duration()
    model._normalize_track_layers(enforce_main=True)
    model.tracksReordered.emit()
    model.playhead = project.get("playhead", 0.0)


def has_autosave() -> bool:
    return os.path.exists(AUTO_SAVE_FILE)


def delete_autosave():
    if os.path.exists(AUTO_SAVE_FILE):
        os.remove(AUTO_SAVE_FILE)


# ── Project Manager (Singleton) ───────────────────────────────

class ProjectManager:
    """
    Quản lý trạng thái dự án hiện tại.
    Theo dõi đường dẫn file .clinq, metadata, và trạng thái lưu.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._project_path: Optional[str] = None
        self._project_meta: dict = {}
        self._is_modified: bool = False
        self._project_id: str = f"proj-{uuid.uuid4().hex[:12]}"

    @property
    def project_path(self) -> Optional[str]:
        return self._project_path

    @project_path.setter
    def project_path(self, value: str):
        self._project_path = value
        if value:
            # Đọc meta từ file nếu đã tồn tại
            existing = load_project_from_file(value)
            if existing and "project_meta" in existing:
                self._project_meta = existing["project_meta"]
                self._project_id = self._project_meta.get("project_id", self._project_id)

    @property
    def project_name(self) -> str:
        if self._project_path:
            return os.path.splitext(os.path.basename(self._project_path))[0]
        return "Dự án mới"

    @property
    def project_meta(self) -> dict:
        return self._project_meta

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    def mark_modified(self):
        self._is_modified = True

    def mark_saved(self):
        self._is_modified = False

    def save(self, model, resolution=None, fps=30, aspect_ratio="16:9"):
        """Lưu dự án vào file .clinq hiện tại."""
        if not self._project_path:
            return False

        if resolution is None:
            resolution = {"width": 1920, "height": 1080}

        self._project_meta.update({
            "project_id": self._project_id,
            "project_name": self.project_name,
            "resolution": resolution,
            "fps": fps,
            "aspect_ratio": aspect_ratio,
        })

        success = save_project_to_file(
            model, self._project_path, self._project_meta
        )
        if success:
            self.mark_saved()
        return success

    def load(self, model, project_path: str = None) -> bool:
        """Tải dự án từ file .clinq."""
        path = project_path or self._project_path
        if not path:
            return False

        project = load_project_from_file(path)
        if not project:
            return False

        self._project_path = path
        self._project_meta = project.get("project_meta", {})
        self._project_id = self._project_meta.get("project_id", self._project_id)

        restore_model_from_clinq(model, project)
        self.mark_saved()
        return True

    def new_project(self, model, project_path: str, resolution=None, fps=30,
                    aspect_ratio="16:9"):
        """Tạo dự án mới và lưu lần đầu."""
        self._project_path = project_path
        self._project_id = f"proj-{uuid.uuid4().hex[:12]}"
        self._project_meta = {
            "project_id": self._project_id,
            "project_name": os.path.splitext(os.path.basename(project_path))[0],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "resolution": resolution or {"width": 1920, "height": 1080},
            "fps": fps,
            "aspect_ratio": aspect_ratio,
        }
        return self.save(model, resolution, fps, aspect_ratio)

    def close(self):
        """Đóng dự án hiện tại."""
        self._project_path = None
        self._project_meta = {}
        self._is_modified = False
        self._project_id = f"proj-{uuid.uuid4().hex[:12]}"
