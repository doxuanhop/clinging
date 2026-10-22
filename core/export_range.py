"""
core/export_range.py

Toan QUYET DINH VUNG XUAT cho ``ui/export_dialog.py:RenderWorker``: xuat tu
giay nao, dai bao nhieu, sinh bao nhieu khung hinh, va ffmpeg phai cat audio
o dau.

Vi sao tach module: RenderWorker khong co ham thuan khiu nao de probe cham —
muon do "vung 2,0 -> 4,0 ra dung 60 frame @30fps" thi phai chay ca ffmpeg
(mot lan xuat ~10 s). Toan o day khong cham file, khong cham Qt, va
RenderWorker goi CHINH NO: probe va app khong the tra hai so khac nhau. Do la
bai hoc the Cat (``9ed6125``): hinh hoc di qua ``TimelineModel.resize_clip``
de the dieu khien va con chuot tren timeline khong bao gio bat dong.

Hai bat buoc ma ham ``resolve_window`` giu, vi ca hai tung gay im lang:
* ``span`` TRA VE tinh bang SO KHUNG HINH (``frames / fps``), khong phai hieu
  hai so user nhap. Duong video sinh dung ``frames`` frame tai ``fps``, nen
  neu audio window dung con so nhap tay thi hai ben lech toi da 1/fps giay
  va lan lap moi lan xuat.
* Khong co ``-shortest`` o dau het. ``ui/export_dialog.py:877`` dung no cho
  toi 21/10/2026: model 1,9 s ma file ra 1,6 s, vi clip cuoi khong co tieng
  thi muxer cat luon ca hinh (do trong scratch/popart_project_build.py).
  ``output_args`` noi do dai bang ``-t`` cua chinh no.
"""

RANGE_FULL = "full"
RANGE_WINDOW = "window"

# Mot frame thi khong goi la "doan": khong co gi de xem va hau het player
# hien thi to. Hai frame la ngan nhat co nghia.
MIN_WINDOW_FRAMES = 2

# (key, nhan, x264 preset, CRF). So lieu CHON TU DO, khong phai doan:
# scratch/export_quality_cost.json — 8 cap, cung mot luong 60 frame
# 1280x720@30 rawvideo RGBA (dung y duong RenderWorker), hai vong len ke nhau
# lay vong nhanh hon, tren may nay 22/10/2026:
#   CRF18 medium 1,94 s 1,10 MB   CRF21 medium 1,86 s 0,85 MB
#   CRF24 medium 2,13 s 0,62 MB   CRF21 veryfast 1,11 s 0,75 MB
#   CRF23 veryfast 1,05 s 0,61 MB CRF24 veryfast 1,08 s 0,54 MB
#   CRF20 slow 3,46 s 0,90 MB     CRF23 ultrafast 0,71 s 1,69 MB
# HAI ket qua AM co ghi o day de khong ai them lai: `slow` thua CRF21 medium
# ca hai chieu (cham hon 1,9 lan, to hon 6 %), va `ultrafast` ra file TO HON
# CRF18 medium 54 % — nhanh nhat la dat nhat ve byte. Khong preset nao trong
# hai cai do duoc ship.
QUALITY_PRESETS = (
    ("cao", "Chất lượng cao · CRF 18 (mặc định)", "medium", 18),
    ("can_bang", "Cân bằng · CRF 21 · nhẹ hơn 23 %", "medium", 21),
    ("nhe", "Tệp nhẹ · CRF 24 · nhẹ hơn 44 %", "medium", 24),
    ("nhanh", "Nhanh cho máy cấu hình thấp · CRF 23 · 0,54× thời gian",
     "veryfast", 23),
)


def preset_keys():
    return tuple(row[0] for row in QUALITY_PRESETS)


def preset_of(key):
    """Cau hinh cho mot key; key la -> cai dau tien (mac dinh cua app)."""
    for row in QUALITY_PRESETS:
        if row[0] == key:
            return row
    return QUALITY_PRESETS[0]


def encode_args(key):
    """Doan lenh ffmpeg ma RenderWorker that dung — khong phai ban phuc bac."""
    row = preset_of(key)
    return ["-c:v", "libx264", "-preset", row[2], "-crf", str(row[3]),
            "-pix_fmt", "yuv420p"]


def resolve_window(start, end, duration, fps):
    """Quy hai so nguoi dung nhap thanh mot cua so khung hinh hop le.

    Tra ve dict: ``ok`` False thi trong ``error`` la cau NGUOI DUNG doc duoc,
    khong phai ten ham. Khi ``ok``: ``start``/``span`` (giay), ``frames``
    (so khung hinh that se render) va ``mode`` (RANGE_FULL / RANGE_WINDOW).
    """
    out = {"ok": False, "error": "", "mode": RANGE_FULL, "start": 0.0,
           "span": 0.0, "frames": 0}
    try:
        duration = float(duration)
        fps = float(fps)
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        out["error"] = "Thoi diem xuat khong phai con so"
        return out
    if duration <= 0:
        out["error"] = "Dự án trống, không có gì để xuất"
        return out
    if fps <= 0:
        out["error"] = "FPS phải lớn hơn 0"
        return out
    # Kep ve trong pham vi thay vi bao loi: o "Den" de trong hoac nhap qua
    # cuoi du an la chuyen thuong gap, va y cua nguoi dung ro rang la "den
    # het".
    start = min(max(start, 0.0), duration)
    end = min(max(end, 0.0), duration)
    if end <= start:
        out["error"] = ("Điểm kết thúc phải nằm sau điểm bắt đầu "
                        "(từ %s đến %s)" % (_fmt(start), _fmt(end)))
        return out
    frames = int(round((end - start) * fps))
    if frames < MIN_WINDOW_FRAMES:
        out["error"] = ("Vùng xuất chỉ được %d khung hình ở %s fps — tối thiểu "
                        "%d khung hình" % (frames, _g(fps), MIN_WINDOW_FRAMES))
        return out
    span = frames / fps
    out.update({"ok": True, "frames": frames, "span": span, "start": start,
                "mode": RANGE_WINDOW})
    # "Toan bo" khong phai mot kieu rieng: no la cua so bat dau bang 0 va ket
    # thuc bang het du an. Phan biet de RenderWorker khong -ss vo nghia.
    if start <= 0.0 and span >= duration - (1.0 / fps):
        out["mode"] = RANGE_FULL
        out["start"] = 0.0
        out["span"] = min(span, duration)
        out["frames"] = int(round(out["span"] * fps))
    return out


def frame_time(start, index, fps):
    """Giay cua khung hinh thu `index` trong vung — diem neo cua preview."""
    return float(start) + index / float(fps)


def audio_input_args(window):
    """`-ss` dat TRUOC `-i` file wav: PCM seek la chinh xac tung mau, khong
    phai keyframe. Khong them gi ca khi xuat toan bo."""
    args = []
    if window.get("mode") == RANGE_WINDOW and window.get("start", 0.0) > 0.0:
        args += ["-ss", "%.6f" % window["start"]]
    return args


def output_args(window):
    """Do dai NOI DUNG cua file ra, tinh bang khung hinh — thang do `-shortest`
    thay bang con so cua chinh chung ta."""
    return ["-t", "%.6f" % window["span"]] if window.get("ok") else []


def _fmt(seconds):
    seconds = max(0.0, float(seconds))
    return "%.2fs" % seconds


def _g(value):
    return ("%g" % float(value))
