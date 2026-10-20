"""
core/clip_clipboard.py
Clipboard clip trong bộ nhớ cho Ctrl+C / Ctrl+V.

Vì sao không dùng QClipboard của OS: payload ở đây là ClipModel sống, mang theo
font, transform, keyframe, effects, transition — những thứ không serialize qua
text một cách vô nghĩa được và cũng không ai mong nhận clipboard clip từ ứng
dụng khác. Clipboard vì thế giới hạn trong một phiên editor, copy xong là dán
được, đúng như duplicate_clip đã làm.

Chi phí với máy cấu hình thấp: không có. Module không import nặng, không có
timer, không đụng đường per-frame. Bản sao chỉ là deepcopy của list clip đang
chọn, giữ nguyên trên RAM tới khi người dùng copy lần sau.
"""

from dataclasses import dataclass
from typing import List, Optional

# Số mục tối đa giữ lại. Một lần copy chỉ lấy các clip ĐANG CHỌN nên không thể
# phình; đây là chốt an toàn cho một kịch bản selection hàng nghìn clip.
MAX_CLIPBOARD = 512


@dataclass
class ClipboardClip:
    """Một clip đã copy, kèm vị trí tương đối để giữ bố cục khi paste nhiều clip.

    ``clip`` là deepcopy đã có clip_id của bản gốc — lệnh paste sẽ clone tiếp từ
    nó để mỗi lần dán ra id mới. ``offset`` là start_time so với clip trái nhất
    của nhóm, nhờ vậy paste nguyên nhóm giữ đúng khoảng cách giữa các clip.
    """
    clip: object
    offset: float
    source_track_id: str
    track_type: object
    media_type: str


class ClipClipboard:
    """Giả hàng đợi clipboard: copy từ selection, đọc ra snapshot để paste."""

    def __init__(self):
        self._entries: List[ClipboardClip] = []

    @property
    def is_empty(self) -> bool:
        return not self._entries

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def entries(self) -> List[ClipboardClip]:
        """Bản sao list: paste không được làm đổi hàng đợi gốc."""
        return list(self._entries)

    def clear(self):
        self._entries = []

    def copy_from(self, model, clip_ids) -> int:
        """Snapshot các clip đang chọn. Trả về số mục đã vào hàng đợi.

        Lấy min(start_time) làm mốc 0 để cả nhóm giữ bố cục tương đối khi dán.
        Clip không tồn tại (đã bị xóa khỏi model) bị bỏ qua.
        """
        collected = []
        for clip_id in clip_ids:
            clip = model.get_clip(clip_id)
            if clip is None:
                continue
            import copy
            snapshot = copy.deepcopy(clip)
            track = model.get_track(clip.track_id)
            collected.append(ClipboardClip(
                clip=snapshot,
                offset=snapshot.start_time,
                source_track_id=clip.track_id,
                track_type=getattr(track, "track_type", None),
                media_type=snapshot.media_type,
            ))
            if len(collected) >= MAX_CLIPBOARD:
                break

        if not collected:
            self._entries = []
            return 0

        base = min(entry.offset for entry in collected)
        for entry in collected:
            entry.offset = entry.offset - base
        self._entries = collected
        return len(collected)
