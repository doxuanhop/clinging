"""core/sfx.py — ĐỌC KHO HIỆU ỨNG ÂM THANH dựng sẵn trong app (`assets/sfx/`).

Ba việc, không cham Qt, không cham ffmpeg, không cham mang:
  * ``pack_dir()`` — thư mục pack theo thứ tự bundle-thắng, giống
    ``core/external_tools.py`` (bản đi kèm là bản đã được đo).
  * ``entries()`` — đọc ``manifest.json`` MỘT lần rồi nhớ, dán thêm đường dẫn
    tuyệt đối cho từng tiếng.
  * ``groups()`` / ``by_key()`` — cho hộp thoại ``ui/sfx_dialog.py`` vẽ danh sách.

Vì sao tách module: 14 tiếng nằm gọn trong 181.167 B (do `tools/make_sfx.py` in
ra, 22/10/2026) và độ dài ĐÃ BIẾT, ghi trong manifest ngay lúc dựng. Nếu để UI
tự đoán, mỗi lần chèn là một lời gọi ffprobe (~0,1-0,3 s trên HDD 5400 rpm) chỉ
để lấy lại một con số đã nằm trên đĩa.

Vì sao không tin manifest một chiều: manifest do `tools/make_sfx.py` tự viết,
nó là loại "tự chấm điểm" mà AGENTS.md đã gọi tên. Cổng ``--sfx-report`` đo lại
từng file bằng ffprobe + RMS và bắt lệch; ở đây chỉ đọc.
"""

import json
import os
import sys

PACK_SUBDIR = ("assets", "sfx")
MANIFEST_NAME = "manifest.json"

_cache = None          # list entries, gan duong dan tuyet doi
_cache_dir = ""        # thu muc da doc — doi thu muc thi doc lai


def pack_dir():
    """Đường dẫn tuyệt đối tới `assets/sfx`, hoặc '' nếu bundle không mang theo."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, *PACK_SUBDIR))
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(base, "_internal", *PACK_SUBDIR))
        candidates.append(os.path.join(base, *PACK_SUBDIR))
    else:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(repo, *PACK_SUBDIR))
    for folder in candidates:
        if os.path.isfile(os.path.join(folder, MANIFEST_NAME)):
            return folder
    # Manifest vang nhung file van co the con (lan build bi cat nua): tra ve cho
    # gateway do va bao "thieu manifest" chu khong bao "khong co tieng nao".
    return candidates[0] if candidates else ""


def entries(force=False):
    """Danh sách ``{key,label,group,path,seconds,bytes}``, rỗng nếu pack hỏng."""
    global _cache, _cache_dir
    folder = pack_dir()
    if not force and _cache is not None and _cache_dir == folder:
        return _cache
    out = []
    try:
        with open(os.path.join(folder, MANIFEST_NAME), encoding="utf-8") as h:
            doc = json.load(h)
    except (OSError, ValueError):
        _cache, _cache_dir = out, folder
        return out
    for row in doc.get("entries") or []:
        name = row.get("file") or ""
        if not name:
            continue
        item = dict(row)
        item["path"] = os.path.normpath(os.path.join(folder, name))
        out.append(item)
    _cache, _cache_dir = out, folder
    return out


def by_key(key):
    for row in entries():
        if row.get("key") == key:
            return row
    return None


def groups():
    """Tên nhóm theo đúng thứ tự dựng pack (khong thu nhat alphabet)."""
    seen = []
    for row in entries():
        name = row.get("group") or "Khác"
        if name not in seen:
            seen.append(name)
    return seen


def missing_files():
    """Entries mà file trên đĩa không tồn tại hoặc dài 0 byte."""
    return [row["key"] for row in entries()
            if not os.path.isfile(row["path"]) or os.path.getsize(row["path"]) == 0]
