"""
core/media_cache.py

Bộ nhớ đệm GIỮA CÁC LẦN MỞ PROJECT cho ảnh nhỡ và dạng sóng.

Vì sao cần: mỗi lần mở một dự án, app giải mã lại 6..24 ảnh nhỡ cho từng clip
và lại chạy ffmpeg dựng dạng sóng. Trên máy cấu hình thấp đo được 414 ms cho
MỘT ảnh nhỡ nguồn từ HDD (scratch/perf_baseline.json), tức một clip dài tốn
~5 giây IO chỉ để vẽ lại thứ đã hiển thị y hệt lần trước. Ảnh nhỡ của thư viện
cũng giải mã lại mỗi lần dựng card.

Khoá cache = đường dẫn tuyệt đối + mtime + kích thước file gốc + loại + tham
số sinh ảnh, nên sửa/quy đổi file nguồn tự động làm hỏng khoá chứ không trả
ảnh cũ. Ghi bằng temp + os.replace: nhiều thread cùng ghi một khoá là an toàn.

Chỉ ba nơi gọi module này — ảnh nhỡ timeline, ảnh nhỡ thư viện, dạng sóng.
Đường xuất video KHÔNG BAO GIỜ đi qua đây: frame xuất phụ thuộc hiệu ứng và
độ phân giải, và cache hàng nghìn frame chỉ tổ chiếm đĩa.
"""

from __future__ import annotations

import hashlib
import json
import os

from PySide6.QtGui import QImage

# 256 MB: đủ cho vài nghìn ảnh nhỡ 160px. Thu muc nam tren o C: (SSD) trong khi
# media nam tren o D: (HDD 5400 rpm), nen doc cache tranh han chuong dia cua
# nguon; o C: con ~8,6 GB trong nen nguong nay chiem ~3% dung luong con lai.
BUDGET_BYTES = 256 * 1024 * 1024

_EVICTED = False


def cache_root() -> str:
    from core.settings import app_data_dir
    root = os.path.join(str(app_data_dir()), "cache")
    os.makedirs(root, exist_ok=True)
    return root


def _key_path(kind: str, parts) -> str:
    """Đường dẫn file cache cho một khoá; phần tử None làm khoá vô hiệu."""
    if any(part is None for part in parts):
        raise ValueError("thieu tham so khoa cache")
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode(
        "utf-8")).hexdigest()[:24]
    folder = os.path.join(cache_root(), kind)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, digest)


def _source_stamp(file_path: str):
    """(mtime_ns, size) của nguồn — đổi nội dung là khoá đổi theo."""
    try:
        stat = os.stat(file_path)
    except OSError:
        return None, None
    return stat.st_mtime_ns, stat.st_size


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path: str, payload) -> None:
    _put_bytes(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _put_bytes(path: str, data: bytes) -> None:
    tmp = path + ".%d.tmp" % os.getpid()
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── API cho hai loại dữ liệu ────────────────────────────────────

def image_key(file_path: str, kind: str, seconds, width, height):
    stamp = _source_stamp(file_path)
    if stamp[0] is None:
        return None
    return _key_path("image", (os.path.abspath(file_path), stamp[0], stamp[1],
                               kind, round(float(seconds), 4), int(width),
                               int(height)))


def read_image(path: str) -> QImage:
    if not path:
        return QImage()
    image = QImage()
    if image.load(path):
        return image
    return QImage()


def write_image(path: str, image: QImage) -> bool:
    if not path or image is None or image.isNull():
        return False
    _enforce_budget()
    tmp = path + ".%d.tmp.png" % os.getpid()
    ok = image.save(tmp, "PNG")
    if ok:
        try:
            os.replace(tmp, path)
        except OSError:
            ok = False
    if not ok:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return bool(ok)


def waveform_key(file_path: str, num_samples, start, duration):
    stamp = _source_stamp(file_path)
    if stamp[0] is None:
        return None
    # duration=None la "dung cua so mac dinh", khong phai thieu tham so: luu
    # bang sentinel de _key_path kh nham no voi loi goi ham.
    return _key_path("wave", (os.path.abspath(file_path), stamp[0], stamp[1],
                              int(num_samples), round(float(start), 4),
                              "auto" if duration is None
                              else round(float(duration), 4)))


def read_waveform(path: str):
    """Danh sách biên độ đã cache, hoặc None nếu không có mục hợp lệ.

    Danh sách RỖNG là kết quả HỢP LỆ và phải được cache: file không có luồng
    âm thanh khiến extract_audio_waveform trả về [], và nếu chỉ cache kết quả
    có dữ liệu thì mỗi lần mở project app lại chạy ffmpeg vô ích trên đúng
    những file im lặng đó.
    """
    if not path:
        return None
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    amps = data.get("amps")
    if isinstance(amps, list) and all(isinstance(v, (int, float)) for v in amps):
        return [float(v) for v in amps]
    return None


def write_waveform(path: str, amplitudes) -> bool:
    if not path or amplitudes is None:
        return False
    _enforce_budget()
    # JSON viet so phu thuc dang day du de doc lai ra DUNG nguyen tam
    # (repr round-trip). Lam tron o day thi cay song khong doi hinh, nhung
    # cau hoi "cache tra ve cai gi" se khong con tra loi duoc nhu cu.
    _write_json(path, {"amps": [float(v) for v in amplitudes]})
    return os.path.exists(path)


def clear() -> int:
    """Xoá toàn bộ cache, trả về số file đã xoá — probe dùng để đo counterfactual."""
    root = cache_root()
    removed = 0
    for kind in ("image", "wave"):
        folder = os.path.join(root, kind)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, name))
                removed += 1
            except OSError:
                pass
    return removed


def stats():
    """(số file, tổng byte) — gate cần số thật, không cần mô tả."""
    root = cache_root()
    files = total = 0
    for kind in ("image", "wave"):
        folder = os.path.join(root, kind)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            try:
                total += os.path.getsize(os.path.join(folder, name))
                files += 1
            except OSError:
                pass
    return files, total


# ── ngân sách đĩa ───────────────────────────────────────────────

def _enforce_budget() -> None:
    """Gọi một lần mỗi tiến trình khi ghi: dọn file cũ nhất cho tới khi lọt
    ngân sách. Chạy lúc ghi chứ không lúc đọc để một project mở nhanh không
    bao giờ bị chặn bởi một lượt quét đĩa."""
    global _EVICTED
    if _EVICTED:
        return
    _EVICTED = True
    root = cache_root()
    entries = []
    for kind in ("image", "wave"):
        folder = os.path.join(root, kind)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            try:
                info = os.stat(full)
            except OSError:
                continue
            entries.append((info.st_mtime, info.st_size, full))
    total = sum(item[1] for item in entries)
    if total <= BUDGET_BYTES:
        return
    for mtime, size, full in sorted(entries):
        if total <= BUDGET_BYTES:
            break
        try:
            os.remove(full)
            total -= size
        except OSError:
            pass


def remove_path(path: str) -> None:
    """Gỡ một mục cache hỏng — dùng khi đọc ra file vỡ."""
    try:
        os.remove(path)
    except OSError:
        pass
