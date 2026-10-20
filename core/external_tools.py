"""core/external_tools.py — một chỗ duy nhất tìm ffmpeg/ffprobe.

Lý do tồn tại: toàn bộ app gọi ``["ffmpeg", ...]`` theo tên trần, tức vay
trình từ PATH của máy người dùng. Trên máy lập trình thì luôn có, nên lỗi
im lặng: máy khác cài app vào là 15 chỗ kia ném FileNotFoundError, có chỗ
treo cả hộp thoại. Từ giờ mọi lời gọi đi qua ``find()``/``require()`` ở đây.

Thứ tự tìm (bản đi kèm THẮNG PATH):
  1. ``<exe>/_internal/tools/<ten>.exe`` — bản do installer đặt xuống.
  2. ``<repo>/tools/<ten>/<ten>.exe``  — bản cho source/gate dùng chung một
     file với bundle, để "đo trên source" và "đo trên bản đã cài" không phải
     hai sự thật khác nhau.
  3. PATH của hệ thống — cho ai đã có sẵn ffmpeg và muốn app dùng bản của họ.

Vì sao bundled-first chứ không phải PATH-first: bản đi kèm là bản được đo,
còn bản trong PATH có thể là bản cũ thiếu filter, bản full 485 MB của người
này, hoặc một ``ffmpeg.exe`` nào đó không rõ từ phần mềm khác.
"""

import os
import shutil
import sys

_TOOLS = ("ffmpeg", "ffprobe")


def _candidate_dirs():
    """Ba nơi có thể cất bản đi kèm, theo đúng thứ tự ưu tiên."""
    dirs = []
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        internal = os.path.join(base, "_internal")
        dirs.append(os.path.join(internal, "tools"))
        dirs.append(os.path.join(base, "tools"))
    else:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dirs.append(os.path.join(repo, "tools", "ffmpeg"))
    return dirs


def bundled_path(name):
    """Đường dẫn bản đi kèm, hoặc '' khi bundle không mang theo nó."""
    if name not in _TOOLS:
        return ""
    for folder in _candidate_dirs():
        path = os.path.join(folder, name + ".exe" if os.name == "nt" else name)
        if os.path.isfile(path):
            return path
    return ""


def system_path(name):
    if name not in _TOOLS:
        return ""
    return shutil.which(name) or ""


def find(name):
    """Đường dẫn thật của tool, hoặc '' — KHÔNG bao giờ raise."""
    return bundled_path(name) or system_path(name)


def source(name):
    """'bundled' | 'PATH' | '' — để báo cáo/selftest nói được bản nào đang chạy."""
    if bundled_path(name):
        return "bundled"
    return "PATH" if system_path(name) else ""


class MissingTool(RuntimeError):
    """Tool ngoài không tồn tại ở bất kỳ nguồn nào đã tìm."""


def missing_message(name):
    return ("Máy này chưa có {0}.\n\n"
            "Bản cài của Cling luôn đi kèm {0}; nếu bạn chạy từ mã nguồn, hãy "
            "đặt {0}.exe vào thư mục tools/ffmpeg/ hoặc thêm nó vào PATH rồi "
            "mở lại ứng dụng.").format(name)


def require(name):
    """Đường dẫn tool, hoặc MissingTool với câu tiếng Việt cho người dùng cuối.

    MissingTool là RuntimeError chứ không phải OSError: mọi chỗ gọi ffmpeg đã
    có nhánh ``except (OSError, SubprocessError)`` cho "không đọc được file",
    và gộp chung vào đó sẽ biến "máy này chưa có ffmpeg" thành "file này hỏng"
    — một chẩn đoán sai mà người dùng không thể tự sửa.
    """
    path = find(name)
    if path:
        return path
    raise MissingTool(missing_message(name))


def describe():
    """Tóm tắt để --selftest in ra: bản nào, ở đâu, lấy từ đâu."""
    rows = []
    for name in _TOOLS:
        path = find(name)
        rows.append("%s=%s (%s)" % (
            name, path or "MISSING", source(name) or "-" if path else "-"))
    return ", ".join(rows)
