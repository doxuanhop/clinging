"""
core/clip_effects.py
Pipeline hiệu ứng DÙNG CHUNG cho cả Preview (CanvasClipItem) lẫn Export
(RenderWorker/FrameComposer).

Tách ra khỏi ui/graphics_canvas_item.py để "xuất video giống hệt xem trước":
    - apply_color_effects(image, effects): lọc màu theo pixel (brightness,
      contrast, saturation, color_temp, blur, vignette, grain, sharpen,
      posterize, halftone, outline, chromatic, lens_flare).
    - compute_animation_offsets(effects, t): tính dịch chuyển/scale/opacity của
      các hiệu ứng chuyển động theo thời gian t (giây).

Cả hai đều là hàm THUẦN: không phụ thuộc QGraphicsItem/scene, nhận effect list
tường minh nên preview và export luôn cho cùng kết quả.
"""

import math
from collections import namedtuple

from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

from core import anim_engine

try:
    import numpy as np
except ImportError:  # numpy có trong requirements; nếu thiếu -> bỏ qua lọc màu
    np = None

try:
    import cv2
except ImportError:
    cv2 = None


# dx, dy: dịch chuyển (px canvas); rotation: độ; scale: hệ số; opacity: 0..1
AnimationOffsets = namedtuple(
    "AnimationOffsets", ["dx", "dy", "rotation", "scale", "opacity"]
)

# Danh sách ĐẦY ĐỦ mọi khoá `effect.params` mà apply_color_effects đọc.
# Đây là chỗ dựa duy nhất để phân biệt "thẻ thật" với "thẻ ma": một key không
# có trong bảng này thì không nhánh nào trong chuỗi chạm tới, nghĩa là thẻ đó
# trong panel chỉ là ảnh minh hoạ. Thêm key mới bắt buộc thêm nhánh ở đây, nếu
# không gate scratch/effect_liveness_probe.py và dòng selftest sẽ báo ngay.
PIXEL_KEYS = (
    "brightness", "contrast", "saturation", "color_temp", "blur", "vignette",
    "grain", "sharpen", "halftone", "posterize", "outline",
    "chromatic", "lens_flare",
)

# Khoá của BO CHỈNH MÀU (nhóm D). Tách khỏi PIXEL_KEYS có chủ đích: cổng
# _effect_liveness_ok khoá PIXEL_KEYS đúng bằng tập khoá của các thẻ "Sắc thái"/
# "Bộ lọc", còn chỉnh màu KHÔNG phải thẻ một-nhấp — nó là một EffectData
# (category "Chinh mau") do panel thuộc tính quản lý. Thêm khoá chỉnh màu vào
# đây thì không phải sửa gate thẻ ma, và chuỗi lọc vẫn đọc được qua GRADING_KEYS.
GRADING_KEYS = ("hue_shift", "lift", "gamma", "gain", "lut_path")

# Bo chinh mau dung khi DUOC bat duoc trong danh sach hieu ung cua clip; ten
# nay la khoa nhat quan giua panel thuoc tinh, lenh undo va gate, vi khong co
# the mot-nhap nao trong EFFECT_CATEGORIES mang ten trung.
GRADING_EFFECT_NAME = "Chinh mau"

# Phan tu trung tinh cua tung phep: hue 0 do, lift 0, gamma 1, gain 1, khong LUT.
# Mot bo dung het cac gia tri nay thi apply_color_effects ve bang nguyen ban,
# nen SetClipGradingCommand boc ca EffectData khi nguoi dung tha het ve mac
# dinh - giu no lai chi dem them vong numpy moi frame tren may cau hinh thap.
GRADING_IDENTITY = {"hue_shift": 0.0, "lift": 0.0, "gamma": 1.0,
                    "gain": 1.0, "lut_path": ""}


def grading_is_identity(params) -> bool:
    """True khi bo tham so chinh mau khong con lam thay doi khung hinh nao."""
    values = params or {}
    for key, neutral in GRADING_IDENTITY.items():
        value = values.get(key, neutral)
        try:
            if isinstance(neutral, str):
                if str(value or ""):
                    return False
            else:
                parts = value if isinstance(value, (list, tuple)) else [value]
                if any(abs(float(v) - neutral) > 1e-6 for v in parts):
                    return False
        except (TypeError, ValueError):
            return False   # gia tri sai kieu tu file .clinq cu: giu EffectData, khong boc
    return True


def _qimage_to_rgba(image: QImage):
    """QImage -> ndarray float32 (H, W, 4) theo thứ tự R,G,B,A."""
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = img.constBits()
    try:
        raw = buf.tobytes()
    except AttributeError:
        raw = bytes(buf)
    arr = np.frombuffer(raw, np.uint8).reshape((h, w, 4)).astype(np.float32)
    return arr, w, h


def _rgba_to_qimage(arr) -> QImage:
    """ndarray (H, W, 4) -> QImage (bản copy sở hữu bộ nhớ riêng)."""
    h, w = arr.shape[:2]
    out = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = QImage(out.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()


def _moving_average(a, k, axis):
    """Trung bình trượt cửa sổ k dọc theo trục (dùng cumulative sum)."""
    r = k // 2
    pad_width = [(r, r) if i == axis else (0, 0) for i in range(a.ndim)]
    padded = np.pad(a, pad_width, mode="edge")
    csum = np.cumsum(padded, axis=axis, dtype=np.float32)
    zero_shape = list(csum.shape)
    zero_shape[axis] = 1
    csum = np.concatenate([np.zeros(zero_shape, csum.dtype), csum], axis=axis)
    hi = [slice(None)] * csum.ndim
    lo = [slice(None)] * csum.ndim
    hi[axis] = slice(k, None)
    lo[axis] = slice(0, -k)
    return (csum[tuple(hi)] - csum[tuple(lo)]) / float(k)


def _box_blur_rgb(rgb, radius: int):
    """Box blur nhanh trên mảng RGB float32 (H, W, 3)."""
    k = max(1, int(radius)) * 2 + 1
    if cv2 is not None:
        return cv2.blur(rgb, (k, k))
    return _moving_average(_moving_average(rgb, k, 0), k, 1)


def _blend(a, b, k):
    """Nội suy tuyến tính a -> b; k đã kẹp trong [0,1]."""
    k = max(0.0, min(1.0, float(k)))
    return a + (b - a) * k


def _luma(rgb):
    return (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2])


def contrast_rgb(rgb, contrast, intensity):
    """Kéo giãn màu quanh trục giữa 128; intensity=0 trả nguyên vẹn.

    Công thức "259*(c+255)/(255*(259-c))" hay gặp chỉ đúng khi c là ĐỘ LỆCH
    trong [-255, 255]. Các preset ở đây ghi 1.05/1.1/1.2 theo nghĩa HỆ SỐ
    NHÂN, đưa vào công thức đó là mẫu số âm và ảnh bị đảo màu hoàn toàn —
    nên ở đây nhân thẳng quanh trục giữa.
    """
    c_val = float(contrast) * intensity + (1.0 - intensity)
    if abs(c_val - 1.0) < 1e-9:
        return rgb
    return (rgb - 128.0) * c_val + 128.0


def posterize_rgb(rgb, levels):
    """Nén mỗi kênh về đúng `levels` bậc màu — nền tảng của tranh pop art."""
    lv = max(2.0, float(levels))
    q = np.clip(rgb, 0.0, 255.0) / 255.0 * (lv - 1.0)
    return np.round(q) / (lv - 1.0) * 255.0


def halftone_rgb(rgb, cell):
    """Chấm bi Ben-Day: mỗi ô lưới thành một chấm, ô càng tối chấm càng to.

    Bán kính r = 0.92 * (cell/2) * sqrt(1 - độ sáng): hệ số 0.92 giữ cho hai
    chấm kề nhau luôn còn hở, nếu chấm đặc kín ô thì lưới thông thành một mảng
    đen và mất hết sắc độ.

    Vì diện tích chấm là πr² nên tỉ lệ mực in đo được trên ảnh thật chỉ vào
    khoảng 0.68 * (1 - độ sáng) — lưới chấm làm trung cảnh SÁNG HƠN ảnh gốc
    chừng một phần ba, đó là chất "in lưới" của tranh pop art chứ không phải
    bug. Ở các ô sáng trên ~240, chấm nhỏ hơn một pixel nên in ra giấy trắng
    hoàn toàn.

    Mọi thứ tính theo KHÔNG GIAN Ô (hc x wc) rồi mới nở ra từng pixel: khoảng
    cách tới tâm ô chỉ phải căn bậc hai trên đúng c*c ô con, không phải trên
    toàn ảnh — bản 640px tốn 8ms thay vì 64ms.
    """
    h, w = rgb.shape[:2]
    c = max(3, int(round(cell)))
    lum = np.clip(_luma(rgb), 0.0, 255.0) / 255.0
    hc, wc = (h + c - 1) // c, (w + c - 1) // c
    padded = np.pad(lum, ((0, hc * c - h), (0, wc * c - w)), mode="edge")
    cell_lum = padded.reshape(hc, c, wc, c).mean(axis=(1, 3))
    # 0.92 de hai cham ke nhau bao gio cung con hen giua: cham dac kin o thi
    # luu thong thanh mot mau den, mat het sac do cua anh.
    radius = 0.92 * np.sqrt(np.clip(1.0 - cell_lum, 0.0, 1.0))
    step = (np.arange(c, dtype=np.float32) + 0.5) / (c / 2.0) - 1.0
    dist = np.sqrt(step[:, None] ** 2 + step[None, :] ** 2)
    dot = (dist[None, None, :, :] <= radius[:, :, None, None])
    dot = dot.transpose(0, 2, 1, 3).reshape(hc * c, wc * c)[:h, :w][:, :, None]
    # Muc va chi la chinh mau cua anh, ke sang toi — not tranh pop art giu
    # mau cua canh, nen khong duoc ep no ve den/trang nhu lang in báo.
    paper = np.minimum(255.0, rgb * 1.06 + 26.0)
    ink = rgb * 0.30 + 8.0
    return np.where(dot, ink, paper)


def outline_rgb(rgb, sensitivity):
    """Viền đen comic: chỉ những pixel có gradient độ sáng vượt ngưỡng.

    Ngưỡng giảm theo `sensitivity` (0..1) nên tăng tay này là kéo thêm nét
    từ mảng phẳng lên chi tiết mịn; mảng phẳng luôn nguyên vẹn vì gradient
    của nó xấp xỉ 0.
    """
    lum = _luma(rgb)
    dx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1]))
    dy = np.abs(np.diff(lum, axis=0, prepend=lum[:1, :]))
    grad = dx + dy
    threshold = max(6.0, 90.0 - 74.0 * max(0.0, min(1.0, float(sensitivity))))
    edge = np.clip((grad - threshold) / threshold, 0.0, 1.0)[:, :, None]
    return rgb * (1.0 - 0.94 * edge)


def lens_flare_rgb(rgb, strength):
    """Loang sáng kiểu ống kính (bloom): tán phần ảnh vượt ngưỡng rồi cộng screen.

    Ngưỡng 185/255 và hệ số 1.30 chọn bằng mắt trên HAI loại khung hình thật
    (gate scratch/effect_liveness_probe.py): với 170/1.45, khung đã sáng sẵn
    (luma 198) bị đẩy lên 220 và cháy chi tiết; 185/1.30 chỉ còn +14 trên khung
    đó mà vẫn +20 trên khung màu đậm — loang rõ mà không đục.

    Blur hai lần xấp xỉ nhân chập tam giác — một lần box thì quầng sáng lộ rõ
    cạnh vuông. Bán kính theo CẠNH NGẮN để ảnh proxy 640px và ảnh full-HD loang
    cùng một mức; vuông cham thực của cặp blur là 2*radius.
    """
    base = np.clip(rgb, 0.0, 255.0)
    s = max(0.0, min(1.0, float(strength)))
    if s <= 1e-6:
        return base
    h, w = base.shape[:2]
    lum = _luma(base)
    weight = np.clip((lum - 185.0) / 70.0, 0.0, 1.0)[:, :, None]
    radius = max(4, int(round(min(h, w) * 0.045)))
    bright = base * weight
    halo = np.clip(_box_blur_rgb(_box_blur_rgb(bright, radius), radius) * (1.30 * s),
                   0.0, 255.0)
    return 255.0 - (255.0 - base) * (255.0 - halo) / 255.0


def chromatic_rgb(rgb, strength):
    """Tách màu tán sắc: đỏ bị PHÓNG TO ra xa tâm, xanh dương thu VÀO gần tâm.

    Dời theo bán kính chứ không theo một trục cố định, vì đó là cách tròng kính
    thật lỗi — biên lệch nhiều, giữa ảnh gần như nguyên.

    Chiều lấy mẫu NGƯỢC chiều dời ảnh: out(x) = in(cx + (x-cx)*factor), nên
    factor NHỎ HƠN 1 mới là phóng to. Vì vậy kênh đỏ dùng 1 - s, kênh xanh
    dương dùng 1 + s. Đảo hai hệ số này vẫn ra "viền tím" nhưng viền nằm sai
    phía của mọi biên vật thể — gate scratch/effect_liveness_probe.py do hướng
    dời trên cả biên trái lẫn biên phải nên bắt được.

    Mẫu lấy theo pixel gần nhất trên ảnh vào (proxy đã giới hạn 640px) nên
    viền tím hiện đúng ở biên vật thể, nơi gradient màu dốc nhất.

    0.040 là biên độ ở cường độ tối đa, chọn bằng mắt trên khung hình thật:
    0.022 gần như không thấy gì khi ảnh đã về proxy 640px, còn 0.070 thì viền
    tím vỡ thành lỗi file ảnh chứ không còn là ống kính.
    """
    s = max(0.0, min(1.0, float(strength))) * 0.040
    if s <= 1e-6:
        return rgb
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    out = rgb.copy()
    for channel, factor in ((0, 1.0 - s), (2, 1.0 + s)):
        sx = np.clip(cx + (xx - cx) * factor, 0, w - 1).astype(np.int32)
        sy = np.clip(cy + (yy - cy) * factor, 0, h - 1).astype(np.int32)
        out[:, :, channel] = rgb[:, :, channel][sy, sx]
    return out


def _per_channel(value, default):
    """Trả mảng (3,) float32: value là scalar (lặp 3 kênh) hoặc đúng 3 số.

    Scalar và list độ dài khác 3 đều phân phối về `default` cho từng kênh, để
    một giá trị lỗi từ file .clinq cũ không làm hỏng cả khung hình.
    """
    try:
        if isinstance(value, (list, tuple)):
            if len(value) == 3:
                return np.asarray(value, np.float32)
        else:
            v = float(value)
            return np.array([v, v, v], np.float32)
    except (TypeError, ValueError):
        pass
    return np.asarray([default, default, default], np.float32)


def hue_shift_rgb(rgb, degrees):
    """Xoay hue toàn ảnh bằng ma trận quay quanh trục xám (giữ nguyên độ sáng).

    Đây là phép quay trong không gian RGB quanh vector (1,1,1), nên ảnh xám
    thuần (R=G=B) đứng yên tuyệt đối — đó là tính chất gate đo: một bản xoay
    sai (dịch cả ba kênh như brightness) sẽ làm xám đổi màu và bị bắt.
    """
    a = math.radians(float(degrees))
    if abs(a) < 1e-9:
        return rgb
    c, s = math.cos(a), math.sin(a)
    one = 1.0 / 3.0
    sqrt3 = math.sqrt(1.0 / 3.0)
    m = np.array([
        [c + one * (1 - c),        one * (1 - c) - sqrt3 * s, one * (1 - c) + sqrt3 * s],
        [one * (1 - c) + sqrt3 * s, c + one * (1 - c),        one * (1 - c) - sqrt3 * s],
        [one * (1 - c) - sqrt3 * s, one * (1 - c) + sqrt3 * s, c + one * (1 - c)],
    ], np.float32)
    return rgb @ m.T


def lift_gamma_gain_rgb(rgb, lift, gamma, gain):
    """Ba bánh xe màu chuẩn (SGO): gain nhân, gamma bẻ midtone, lift nhấc bóng.

    Chuẩn hoá về 0..1 rồi: x = x** (1/gamma) * gain + lift*(1-x). Mặc định
    lift=0, gamma=1, gain=1 trả nguyên ảnh (identity), nên gate đo được từng
    cái một: gamma>1 sáng midtone mà không cháy đen, lift>0 nhấc vùng tối mà
    không đụng vùng sáng, gain nhân đều.
    """
    lift = _per_channel(lift, 0.0)
    gamma = _per_channel(gamma, 1.0)
    gain = _per_channel(gain, 1.0)
    if (np.allclose(lift, 0.0) and np.allclose(gamma, 1.0)
            and np.allclose(gain, 1.0)):
        return rgb
    x = np.clip(rgb, 0.0, 255.0) / 255.0
    g = np.clip(gamma, 0.05, 4.0)
    x = np.power(x, 1.0 / g) * gain
    x = x + lift * (1.0 - x)
    return np.clip(x, 0.0, 1.0) * 255.0


def apply_color_effects(image: QImage, effects) -> QImage:
    """Áp dụng toàn bộ hiệu ứng lọc màu lên QImage và trả về QImage mới.

    Vector hoá bằng NumPy (nhanh hơn per-pixel Python hàng trăm lần) nên preview
    và export áp effect theo thời gian thực. Vẫn xử lý trên proxy tối đa 640px
    rồi scale lại như bản gốc.
    """
    if not effects:
        return image
    if np is None:
        return image

    # Thẻ không có khoá pixel nào (Aura, Hoạt ảnh, Chuyển tiếp) phải trả lại ảnh
    # nguyên bản: round-trip numpy + proxy 640px dưới đây tự nó làm đổi vài
    #/channel, nên chỉ cần một hiệu ứng phi-pixel cũng đủ làm clip xỉn màu.
    # Đây cũng là đường tắt cho máy cấu hình thấp — khỏi mở numpy khi không vẽ gì.
    if not any(k in PIXEL_KEYS or k in GRADING_KEYS
               for e in effects for k in (getattr(e, "params", None) or {})):
        return image

    output_size = image.size()
    work = image
    if max(image.width(), image.height()) > 640:
        work = image.scaled(640, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    arr, w, h = _qimage_to_rgba(work)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4]

    for effect in effects:
        intensity = effect.intensity
        params = effect.params

        # ── Brightness ──
        if "brightness" in params:
            rgb = rgb + params["brightness"] * intensity * 255.0

        # ── Contrast ──
        if "contrast" in params:
            rgb = contrast_rgb(rgb, params["contrast"], intensity)

        # ── Saturation ──
        if "saturation" in params:
            s_val = params["saturation"] * intensity + (1.0 - intensity)
            gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1]
                    + 0.114 * rgb[:, :, 2])[:, :, None]
            rgb = gray + s_val * (rgb - gray)

        # ── Color Temperature ──
        if "color_temp" in params:
            ct = params["color_temp"] * intensity
            rgb = rgb.copy()
            rgb[:, :, 0] += ct * 30.0   # ct > 0 = ấm (tăng đỏ)
            rgb[:, :, 2] -= ct * 30.0   # giảm xanh

        # ── Bo chinh mau (nhom D): hue -> lift/gamma/gain -> LUT ──
        # Gia tri tuyet doi theo slider, khong nhan intensity: panel thuoc tinh
        # la nguon thuat toan, con intensity cua EffectData mac dinh 1.0. Thu tu
        # nay de LUT nam cuoi (LUT da duoc thi cong theo khong gian mau cua no).
        if "hue_shift" in params:
            rgb = hue_shift_rgb(rgb, params["hue_shift"])
        if any(k in params for k in ("lift", "gamma", "gain")):
            rgb = lift_gamma_gain_rgb(rgb, params.get("lift", 0.0),
                                      params.get("gamma", 1.0),
                                      params.get("gain", 1.0))
        if params.get("lut_path"):
            from core import lut as _lut
            rgb = _lut.apply_lut(rgb, params["lut_path"])

        # ── Blur ──
        # Khong co `max(1, ...)`: ban cu bao gio cung mo 3x3, ngay khi tay keo
        # ve 0, nen Blur la the duy nhat ma cuong do 0 khong tra lai anh goc.
        if "blur" in params:
            radius = int(round(params["blur"] * intensity))
            if radius >= 1:
                rgb = _box_blur_rgb(np.clip(rgb, 0, 255).astype(np.float32), radius)

        # ── Vignette ──
        if "vignette" in params:
            vig = params["vignette"] * intensity
            yy, xx = np.mgrid[0:h, 0:w]
            cx, cy = w / 2.0, h / 2.0
            max_dist = math.sqrt(cx * cx + cy * cy)
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_dist
            factor = (1.0 - vig * dist * dist)[:, :, None]
            rgb = rgb * factor

        # ── Grain (noise) ──
        if "grain" in params:
            grain_amount = params["grain"] * intensity * 50
            noise = np.random.normal(0, grain_amount, (h, w, 1))
            rgb = rgb + noise

        # ── Sharpen (unsharp mask) ──
        if "sharpen" in params:
            sharp = params["sharpen"] * intensity
            base = np.clip(rgb, 0, 255).astype(np.float32)
            blurred = _box_blur_rgb(base, 2)
            rgb = base + sharp * (base - blurred)

        # ── Tán sắc và loang sáng: hai hiệu ứng "Bộ lọc" từng là thẻ ma ──
        # Dat TRUOC cac ben pop art: chung toang mau va sang, ma luoi cham +
        # nen thang thi sau khi do se khong con doc duoc net tach mau o bien.
        if "chromatic" in params:
            rgb = _blend(rgb, chromatic_rgb(rgb, params["chromatic"]), intensity)
        if "lens_flare" in params:
            rgb = _blend(rgb, lens_flare_rgb(rgb, params["lens_flare"]), intensity)

        # ── Pop art: lưới chấm -> bậc màu -> viền, theo đúng thứ tự này ──
        # Posterize sau halftone de hai cham/nen giay bi nen thang thanh mau
        # phang, khong con doc gradient; vien ve cuoi de net den khong bi hai
        # thao tac tren loang mat.
        if "halftone" in params:
            rgb = _blend(rgb, halftone_rgb(rgb, params["halftone"]), intensity)
        if "posterize" in params:
            rgb = _blend(rgb, posterize_rgb(rgb, params["posterize"]), intensity)
        if "outline" in params:
            rgb = _blend(rgb, outline_rgb(rgb, params["outline"]), intensity)

    result = np.concatenate([np.clip(rgb, 0, 255), alpha], axis=2)
    out = _rgba_to_qimage(result)
    if out.size() != output_size:
        # IgnoreAspectRatio: chiều về là co lại đúng kích thước đã đi ra, nên
        # không được phép "giữ tỉ lệ" — với khung 576x1268, KeepAspectRatio trả
        # về 576x1266 (lệch 2px do làm tròn), và mọi caller tin vào kích thước
        # ảnh ra sẽ thấy một khác biệt ma. Xuôi thì vẫn KeepAspectRatio để proxy
        # không bị méo (vignette trên dự án 9:16 phải tròn, không elip).
        out = out.scaled(output_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return out


def compute_animation_offsets(effects, t: float, rect_width: float = 0.0,
                             rect_height: float = 0.0,
                             duration: float = 0.0) -> AnimationOffsets:
    """Tính offset chuyển động của các hiệu ứng animation tại thời điểm t (giây).

    `t` phải là thời gian CỤC BỘ của clip (local_time = playhead - clip.start)
    ở cả hai đường vẽ: preview từng truyền time.monotonic() nên khung hình xem
    trước và khung xuất ra không bao giờ khớp nhau.

    Các hiệu ứng có trong core.anim_engine tính theo nhịp tiến độ
    (p = t / duration) nên kết quả chỉ phụ thuộc vị trí trong clip. Mấy hiệu
    ứng tuần hoàn còn lại (shake/float/glitch/cross_dissolve/wipe_right) giữ
    công thức cũ, chạy theo t.
    """
    dx = dy = rotation = 0.0
    scale = 1.0
    opacity = 1.0
    # Không có độ dài thì không có "nhịp tiến độ": thà đứng yên còn hơn đóng
    # khung ở p=0 (fade_in sẽ che đen cả clip).
    has_span = bool(duration and duration > 0)
    prog = anim_engine.progress(t, duration) if has_span else 0.0
    for effect in effects:
        params = effect.params
        strength = effect.intensity

        # Nhịp tiến độ: mọi khoá mà engine biết đều đi qua đây.
        for key in params:
            if not has_span or key == "none" or key not in anim_engine.MOTION_KEYS:
                continue
            st = anim_engine.motion_state(key, prog, strength)
            dx += st.dx * rect_width
            dy += st.dy * rect_height
            rotation += st.rotation
            scale *= st.scale
            opacity *= st.opacity

        # Tuần hoàn theo đồng hồ clip: chưa có khái niệm tiến độ.
        if "shake" in params:
            dx += math.sin(t * 22.0) * 12.0 * strength
            dy += math.cos(t * 17.0) * 7.0 * strength
        if "float" in params:
            dy += math.sin(t * 2.4) * 18.0 * strength
        if "glitch" in params:
            dx += math.sin(t * 43.0) * 9.0 * strength
        if "cross_dissolve" in params:
            opacity *= 0.45 + 0.55 * abs(math.sin(t * 2.2))
        if "wipe_right" in params:
            scale *= 0.75 + 0.25 * ((t % 1.5) / 1.5)
    return AnimationOffsets(dx, dy, rotation, scale, max(0.0, min(1.0, opacity)))
