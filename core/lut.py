"""core/lut.py — đọc và áp file LUT .cube cho pipeline lọc màu dùng chung.

LUT là đầu vào TỪ ĐĨA (người dùng chọn file .cube), nên đây là ranh giới hệ
thống: phải chịu được file hỏng/cụt/kích thước lẻ mà KHÔNG bật exception xuyên
qua callback C++ của Qt (lỗi đó giết cả process, xem AGENTS.md). Mọi hàm ở đây
trả về None khi không dùng được, để apply_color_effects bỏ qua bước LUT thay vì
làm hỏng khung hình.

Cache theo (đường dẫn tuyệt đối, mtime ns, size): một dự án chỉ dùng vài LUT nhưng
mỗi frame preview lẫn từng frame export đều gọi lại, đọc đĩa + parse mỗi lần là
không chấp nhận được trên máy cấu hình thấp. mtime phải lấy theo ns: file .cube
viết bởi máy định dạng `%.6f` có số byte y hệt nhau dù nội dung đổi, nên khoá
theo giây sẽ giữ bảng cũ mãi mãi khi người dùng sửa LUT tại chỗ.
"""

import hashlib
import os
from collections import OrderedDict

try:
    import numpy as np
except ImportError:
    np = None

_MAX_CACHED = 4
_CACHE = OrderedDict()   # key -> (size:int, table:ndarray (N,N,N,3) float32) | None


def _metadata_int(line, token):
    if line.upper().startswith(token):
        parts = line.split()
        if len(parts) >= 2:
            try:
                return int(float(parts[1]))
            except ValueError:
                return None
    return None


def _parse_cube(text):
    """Trả (size, table (N,N,N,3) float32) cho 3D LUT, hoặc (N, table (N,3)) cho 1D.

    Thứ tự trong .cube NGƯỢC với cách hay tưởng tượng: kênh LAM đổi nhanh
    nhất, rồi lục, rồi đỏ, nên reshape(n,n,n,3) tự nó thành chỉ số [r, g, b, ch].
    Hiểu ngược là table bị hoán vị r<->b: LUT identity trả ảnh lệch tới ~250/255
    thay vì bằng nguyên bản — gate scratch/color_grading_counterfactual.py do đó
    đo thẳng "LUT identity == ảnh vào".
    """
    size3d = size1d = None
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        up = line.upper()
        if up.startswith("TITLE"):
            continue
        v = _metadata_int(line, "LUT_3D_SIZE")
        if v is not None:
            size3d = v
            continue
        v = _metadata_int(line, "LUT_1D_SIZE")
        if v is not None:
            size1d = v
            continue
        if up.startswith("DOMAIN_"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            r, g, b = (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            continue
        rows.append((r, g, b))
    arr = np.asarray(rows, np.float32)
    if size3d and size3d >= 2:
        n = size3d
        if arr.shape[0] != n * n * n:
            return None
        table = arr.reshape(n, n, n, 3)   # [r, g, b, ch]
        return n, table
    if size1d and size1d >= 2:
        n = size1d
        if arr.shape[0] != n:
            return None
        return n, arr.reshape(n, 3)
    return None


def load_lut(path):
    """(size, table) hoặc None. Không bao giờ raise: file lỗi -> None."""
    if np is None or not path:
        return None
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            parsed = _parse_cube(f.read())
    except OSError:
        parsed = None
    _CACHE[key] = parsed
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX_CACHED:
        _CACHE.popitem(last=False)
    return parsed


def _interp_1d(x, table):
    """x (H,W) 0..1 + table (N,) -> (H,W). Khong them truc cuoi: goi theo tung
    kenh nen table da 1-D; `[..., None]` tung bien (3,1) * (3,1,1) thanh (3,3,1)
    va 1D LUT that khong ap duoc cho bat ky kich thuoc nao."""
    n = table.shape[0]
    pos = np.clip(x, 0.0, 1.0) * (n - 1)
    lo = np.floor(pos).astype(np.int32)
    hi = np.minimum(lo + 1, n - 1)
    frac = pos - lo
    return table[lo] * (1.0 - frac) + table[hi] * frac


def apply_lut(rgb, path):
    """rgb float32 (H,W,3) 0..255 -> ảnh đã qua LUT, hoặc trả nguyên nếu LUT vô dụng.

    3D dùng nội suy tam tuyến (trilinear) trên 8 đỉnh ô lưới; 1D áp từng kênh độc
    lập. Cả hai đều vector hoá toàn ảnh, không vòng lặp theo pixel.
    """
    lut = load_lut(path)
    if not lut:
        return rgb
    n, table = lut
    x = np.clip(rgb, 0.0, 255.0) / 255.0
    if table.ndim == 2:                       # 1D LUT
        out = np.empty_like(x)
        for ch in range(3):
            out[:, :, ch] = _interp_1d(x[:, :, ch], table[:, ch])
        return out * 255.0
    pos = x * (n - 1)
    lo = np.clip(np.floor(pos).astype(np.int32), 0, n - 2)
    frac = pos - lo
    # Ten bien PHAI theo đúng thứ tự kênh của table: chỉ số 0 = đỏ. Lần đầu
    # viết nhầm thành (gi, bi, ri), thành thử LUT identity hoán vị ba kênh và
    # ảnh lệch trung bình 85/255 — gate do đó đo identity, không đo "có khác 0".
    ri, gi, bi = (lo[:, :, i] for i in range(3))
    fr, fg, fb = (frac[:, :, i] for i in range(3))

    def corner(dr, dg, db):
        return table[ri + dr, gi + dg, bi + db]

    c000, c100 = corner(0, 0, 0), corner(1, 0, 0)
    c010, c110 = corner(0, 1, 0), corner(1, 1, 0)
    c001, c101 = corner(0, 0, 1), corner(1, 0, 1)
    c011, c111 = corner(0, 1, 1), corner(1, 1, 1)
    w = fr[..., None]
    top0 = c000 * (1 - w) + c100 * w
    top1 = c010 * (1 - w) + c110 * w
    bot0 = c001 * (1 - w) + c101 * w
    bot1 = c011 * (1 - w) + c111 * w
    g = fg[..., None]
    front = top0 * (1 - g) + top1 * g
    back = bot0 * (1 - g) + bot1 * g
    b = fb[..., None]
    out = front * (1 - b) + back * b
    return (np.clip(out, 0.0, 1.0) * 255.0).astype(np.float32)


def lut_fingerprint(path):
    """16 hex đầu của sha256 nội dung — để gate đối chiếu đúng file, không tin tên."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ""
