"""Gate phụ đề karaoke: tám kiểu phải KHÁC NHAU, quét phải ĐIỀU KHIỂN ĐƯỢC, và
preview phải ra đúng khung hình của export.

Probe không tự dựng lại bộ vẽ chữ. Mọi khung hình đi qua hai đường thật:
  * core.text_paint.paint_animated_text  — nền tảng chung,
  * core.frame_composer.FrameComposer    — đường xuất file, có cả clip text
    thật trên TimelineModel thật.
Nếu chỉ đo hàm vẽ riêng thì một bản export không gọi seam vẫn xanh — đúng cái
bẫy "test tự dựng input" mà repo này đã trả giá.

Bốn điều đo:
  1. HÌNH HỌC: bật kiểu nào thì hộp mực của dòng chữ cũng phải y hệt chữ thường
     (đo ở sweep=0, nơi mọi từ còn pending nên chưa có halo/bóng). Lệch 1px là
     karaoke đã dịch chữ.
  2. QUÉT: khối pixel sáng phải chạy từ TRÁI sang PHẢI theo sweep — đây là định
     nghĩa duy nhất của "per-word sweep", ảnh tĩnh không chứng minh được.
  3. KHÁC NHAU: tám kiểu phải cho tám ảnh khác nhau và khác cả chữ thường; bốn
     kiểu màu (flame/neon/gradient/rainbow) phải có bão hoà màu thật, không
     phải chữ xám giả màu.
  4. PARITY + Determinism: cùng (style, sweep, t) thì export ra đúng ảnh như
     vẽ trực tiếp, và vẽ hai lần ra cùng từng byte.
"""
import json
import os
import sys

# Nen dung font THAT. Duoi offscreen, Qt tra ve 0 font ho gia dinh va moi ky tu
# (ca dau cach) in thanh mot hop "tofu" lien mach, nen trong tam muc cua tung tu
# chi do duoc loi cua chinh moi do. Probe nay chi ve ra QImage, khong mo cua so.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "scratch")
EVIDENCE = os.path.join(OUT, "karaoke_evidence.png")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])  # noqa: F841

from core import karaoke_paint  # noqa: E402
from core.text_paint import make_font, paint_animated_text  # noqa: E402

W, H = 1280, 720
FONT = make_font("Arial", 44, True)
LINE = "Xin chao buoi sang"

# Nền mà mỗi kiểu được thiết kế để ĐỌC ĐƯỢC trên đó. Vẽ trên nền khác thì kiểu
# vẫn chạy, chỉ là gate đo vào khoảng vô nghĩa.
STYLE_BG = {"outline": "#c8c8c8", "shadow": "#c8c8c8"}


def home_bg(key):
    return STYLE_BG.get(key, "#000000")


def render(style="none", sweep=0.0, t=0.0, effect="none", text=LINE, font=FONT,
           color="#FFFFFF", bg="#000000", size=(W, H)):
    """Một khung hình qua ĐÚNG hàm mà preview và export cùng gọi."""
    img = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    paint_animated_text(p, text, font, color, size[0], size[1],
                        size[0] / 2.0, size[1] / 2.0,
                        effect=effect, p=sweep, intensity=1.0,
                        style=style, t=t)
    p.end()
    return img


def rgb(img):
    row = img.bytesPerLine() // 4
    a = np.frombuffer(img.constBits(), np.uint8,
                      count=row * 4 * img.height()).reshape(
        img.height(), row, 4)[:, :img.width(), :3]
    return a[:, :, ::-1].astype(np.int16)


def ink_box(img, bg="#000000"):
    """Hộp bao của pixel KHÁC màu nền.

    Nền phải truyền vào chứ không được giả là đen: "outline" là nét TỐI màu,
    trên nền đen thì nó vô hình thật, và gate sẽ đỏ oan.
    """
    color = np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)], np.int16)
    m = (np.abs(rgb(img) - color).max(axis=2) > 24)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))


def lit_columns(img, min_lum=170):
    """Chỉ số cột có chữ SÁNG — dùng đo hướng quét của sweep."""
    a = rgb(img).max(axis=2)
    bright = a > min_lum
    cols = np.nonzero(bright.any(axis=0))[0]
    return cols


def main():
    report = {}

    # --- 0. normalize khong duoc im lang nhan gia tri rac -------------------
    if karaoke_paint.normalize_style("Khong-Biet") != "none":
        raise RuntimeError("normalize_style nhan gia tri rac")
    for key, _label in karaoke_paint.KARAOKE_STYLES:
        if karaoke_paint.normalize_style(key.upper() + " ") != key:
            raise RuntimeError("normalize_style bo lac kieu hop le %s" % key)
    report["styles"] = list(karaoke_paint.STYLE_KEYS)

    # Bố cục từ phải đo TRƯỚC cả gate hình học: gate 1 cần biết từng từ nằm đâu
    # để so chữ karaoke với đúng chỗ Qt đã xếp chữ thường.
    probe = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    pp = QPainter(probe)
    pp.setFont(FONT)
    fm = pp.fontMetrics()
    pp.end()
    boxes = karaoke_paint.word_boxes(fm, LINE)
    if len(boxes) < 3:
        raise RuntimeError("word_boxes gop het dong thanh %d tu" % len(boxes))
    line_w = fm.horizontalAdvance(LINE)
    line_left = W / 2.0 - line_w / 2.0

    # --- 1. hinh hoc: karaoke khong duoc dich dong chu ----------------------
    # So theo TRỌNG TÂM MỰC của từng từ pending, không so hộp mực cả dòng: mực
    # của chữ "n" chảy sang cả ô dấu cách bên cạnh, nên hộp chung luôn lệch nhau
    # vài chục px dù hai dòng chữ nằm đúng chỗ như nhau.
    plain0 = rgb(render("none", 0.0)).max(axis=2) > 24

    def centroid(mask, lo, hi):
        sub = mask[:, lo:hi]
        cols = np.nonzero(sub.any(axis=0))[0]
        if not len(cols):
            return None
        weights = sub[:, cols].sum(axis=0).astype(float)
        return float((cols * weights).sum() / weights.sum()) + lo

    def vspan(mask, lo, hi):
        sub = mask[:, lo:hi]
        rows = np.nonzero(sub.any(axis=1))[0]
        return (int(rows.min()), int(rows.max())) if len(rows) else None

    plain_box = vspan(plain0, 0, W)
    if plain_box is None or not (0 < plain_box[0] < plain_box[1] < H):
        raise RuntimeError("anh nen khong co chu: %s" % (plain_box,))
    geometry = {}
    for key in karaoke_paint.STYLE_KEYS:
        styled = rgb(render(key, 0.0)).max(axis=2) > 24
        worst = 0.0
        for word, wx, ww in boxes[1:]:          # tu 0 dang hat -> co quầng
            # Vat hai dau hop tu bang nhau tren ca hai anh: muc tran qua dau
            # "n" bi doi xung nen trong tam van so duoc cung mot vung.
            pad = 2
            lo = max(0, int(line_left + wx) - pad)
            hi = min(W, int(line_left + wx + ww) + pad)
            ca, cb = centroid(plain0, lo, hi), centroid(styled, lo, hi)
            if ca is None or cb is None:
                raise RuntimeError("kieu %s lam mat tu %r (%d..%d)" % (key, word, lo, hi))
            va, vb = vspan(plain0, lo, hi), vspan(styled, lo, hi)
            drift = abs(ca - cb) + abs(va[0] - vb[0]) + abs(va[1] - vb[1])
            worst = max(worst, drift)
            if drift > 3.0:
                raise RuntimeError("kieu %s lam tu %r dich %.1fpx (cx %.1f->%.1f, "
                                   "doc %s->%s)" % (key, word, drift, ca, cb, va, vb))
        geometry[key] = round(worst, 2)
    report["geometry_max_px"] = max(geometry.values())

    # --- 2. sweep phai chay trai -> phai -----------------------------------
    # Từ phải ĐÚNG chỗ Qt đã xếp: mỗi hộp từ tiên đoán phải có mực của ảnh chữ
    # thường rơi vào trong nó. Đây là gate giữ word_boxes bám theo shaping thật
    # (cộng dồn advance dấu cách từng làm lệch tới 40px).
    plain_mask = rgb(render("none", 0.0)).max(axis=2) > 24
    prev_end = -1.0
    for word, wx, ww in boxes:
        if wx <= prev_end - 1:
            raise RuntimeError("tu %r de len tu truoc do (%.1f)" % (word, wx))
        prev_end = wx + ww
        lo = int(round(line_left + wx)) - 2
        hi = int(round(line_left + wx + ww)) + 2
        if hi - lo < 4 or plain_mask[:, max(0, lo):hi].sum() < 8:
            raise RuntimeError("khong co muc nao roi vao hop tu %r (%d..%d)"
                               % (word, lo, hi))
    if boxes[-1][1] + boxes[-1][2] > line_w + 2:
        raise RuntimeError("tu cuoi tran ra ngoai dong (%.1f > %.1f)"
                           % (boxes[-1][1] + boxes[-1][2], line_w))
    counts = [karaoke_paint.lit_count(len(boxes), s / 100.0)
              for s in range(101)]
    if counts[0] != 0:
        raise RuntimeError("sweep=0.0 da co %d tu sang" % counts[0])
    if counts[-1] != len(boxes):
        raise RuntimeError("sweep=1.0 khong bao qua toan bo %d tu" % len(boxes))
    if any(b < a for a, b in zip(counts, counts[1:])):
        raise RuntimeError("sweep tang thi so tu sang khong duoc giam")
    if len(set(counts)) != len(boxes) + 1:
        raise RuntimeError("sweep bo qua mot tu nao do (%d/%d trang thai)"
                           % (len(set(counts)), len(boxes) + 1))

    # Doi tu pending -> lit phai lam khoi cot SANG tinh dich sang phai. Lay kieu
    # glow (lit = trang tuyet doi tren nen den) de do khong bi mau cua kieu khac
    # che lop.
    left_early = lit_columns(render("glow", 0.05))
    left_late = lit_columns(render("glow", 0.95))
    if len(left_early) == 0 or len(left_late) == 0:
        raise RuntimeError("do duoc cot sang: %d / %d" % (len(left_early), len(left_late)))
    move = float(np.median(left_late) - np.median(left_early))
    if move < line_w * 0.15:
        raise RuntimeError("sweep khong chay qua dong chu (median dich %.1f/%.1f px)"
                           % (move, line_w))
    # ... va dich theo HUONG: qt 25% phai nam ben trai 75%.
    q1 = lit_columns(render("glow", 0.25))
    q3 = lit_columns(render("glow", 0.75))
    if not float(np.median(q3)) > float(np.median(q1)):
        raise RuntimeError("sweep chay nguoc huong")
    report["sweep_median_shift_px"] = round(move, 1)
    report["words"] = len(boxes)

    # --- 2b. từ CHƯA TỚI LƯỢT phải là một nét chung cho cả tám kiểu ----------
    # "Chưa tới lượt" phải trông như nhau bất kể kiểu nào: đó là nhánh duy nhất
    # vẽ chữ thường thuần, và là tiền đề của gate hình học ở mục 1. Khi "outline"
    # được cho pending sáng gần bằng lúc hát, người dùng nền tối không còn thấy
    # nhịp quét nữa — lỗi đó chỉ đỏ được ở đây, không đỏ được bằng mắt trên log.
    last_x, last_w = boxes[-1][1], boxes[-1][2]
    l_lo = int(line_left + last_x) - 2
    l_hi = int(line_left + last_x + last_w) + 2
    l_band = slice(plain_box[0], plain_box[1] + 1)
    shared = None
    for key in karaoke_paint.STYLE_KEYS:
        crop = rgb(render(key, 0.0))[l_band, l_lo:l_hi]
        if shared is None:
            shared = crop
            continue
        if not np.array_equal(crop, shared):
            raise RuntimeError("kieu %s co net pending rieng (%d px lech)"
                               % (key, int((np.abs(crop - shared).max(axis=2) > 0).sum())))
    # ... và tới lượt thì phải KHÁC hẳn: ít nhất 30% mực của từ phải đổi.
    changed = {}
    for key in karaoke_paint.STYLE_KEYS:
        bg = home_bg(key)
        a = rgb(render(key, 0.0, bg=bg))[l_band, l_lo:l_hi]
        b = rgb(render(key, 1.0, t=0.37, bg=bg))[l_band, l_lo:l_hi]
        ink = int((np.abs(a - np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)],
                                       np.int16)).max(axis=2) > 24).sum())
        d = int((np.abs(a - b).max(axis=2) > 24).sum())
        if ink == 0 or d < 0.3 * ink:
            raise RuntimeError("kieu %s: tu cuoi doi khong dang ke khi sweep 0->1 "
                               "(%d/%d px)" % (key, d, ink))
        changed[key] = round(d / max(1, ink), 2)
    report["last_word_change"] = changed

    # --- 3. tam kieu phai khac nhau, co mau that, va co HOQUANG THAT ---------
    # "outline" và "shadow" là pigment TỐI màu: trên nền đen chúng vô hình thật,
    # nên so với chữ thường phải so trên nền SÁNG — cũng đúng là chỗ người dùng
    # cần đến chúng (chữ đè lên khung hình sáng).
    plain_full = rgb(render("none", 1.0))
    fingerprints = {}
    for key in karaoke_paint.STYLE_KEYS:
        bg = home_bg(key)
        arr = rgb(render(key, 1.0, t=0.37, bg=bg))
        ref = plain_full if bg == "#000000" else rgb(render("none", 1.0, bg=bg))
        delta = float(np.abs(arr - ref).max(axis=2).astype(bool).mean())
        if delta < 0.0004:
            raise RuntimeError("kieu %s ve giong het chu thuong tren %s (%.5f)"
                               % (key, bg, delta))
        fingerprints[key] = rgb(render(key, 1.0, t=0.37))
    keys = list(karaoke_paint.STYLE_KEYS)

    # Quầng sáng phải là PIXEL THẬT. Đây là gate chống đúng cái bẫy đã rơi:
    # QPainter.drawText BỎ QUA bề rộng bút, nên "viền nét đậm" chỉ là chữ thường
    # -> nếu quay lại dùng pen width thì mọi kiểu glow/neon/outline đỏ tại đây.
    # Đo: hộp mực lúc mọi từ đã hát phải RỘNG hơn hộp mực chữ thường CÙNG NỀN,
    # tức phần chìa ra hai đầu dòng chỉ có thể là quầng, không phải chữ. Nền lấy
    # theo home_bg() — nét tối màu của "outline" vô hình trên nền đen.
    # Gate này phải chạy TRƯỚC bảng so đôi một: khi quầng biến mất vì nét bút,
    # glow/shadow/outline thành ba bản giống hệt nhau và bảng đó đỏ trước, báo
    # sai nguyên nhân.
    halos = {}
    for key in ("glow", "neon", "soft", "rainbow", "flame", "outline"):
        bg = home_bg(key)
        plain = ink_box(render("none", 1.0, bg=bg), bg)
        wide = ink_box(render(key, 1.0, t=0.37, bg=bg), bg)
        if plain is None or wide is None:
            raise RuntimeError("kieu %s nen %s khong ve gi" % (key, bg))
        grow = min(plain[0] - wide[0], wide[1] - plain[1])
        if grow < 1:
            raise RuntimeError("kieu %s khong mo rong hop muc (%d px) — quay "
                               "sang khong phai pixel that" % (key, grow))
        halos[key] = grow
    report["halo_grow_px"] = halos

    # "shadow" là nét chữ DỊCH XUỐNG-PHẢI, không phải quầng đối xứng. Gate định
    # hướng này đỏ nếu ai đó thay bóng bằng một vòng ring: hộp mực phải chìa ra
    # mép phải và đáy, tuyệt đối không chìa sang trái, và phần mực thêm vào phải
    # TỐI hơn nền (đúng nghĩa "bóng").
    sh_bg = home_bg("shadow")
    sh_plain_img = rgb(render("none", 1.0, bg=sh_bg))
    sh_img = rgb(render("shadow", 1.0, t=0.37, bg=sh_bg))
    sh_bgv = np.array([int(sh_bg[i:i + 2], 16) for i in (1, 3, 5)], np.int16)
    sh_plain = ink_box(render("none", 1.0, bg=sh_bg), sh_bg)
    sh_wide = ink_box(render("shadow", 1.0, t=0.37, bg=sh_bg), sh_bg)
    if sh_wide[1] - sh_plain[1] < 1 or sh_wide[3] - sh_plain[3] < 1:
        raise RuntimeError("bong khong chay xuong-phai (%s -> %s)"
                           % (sh_plain, sh_wide))
    if sh_plain[0] - sh_wide[0] > 1:
        raise RuntimeError("bong choi sang ca ben trai — day la quầng, khong "
                           "phai bong (%s -> %s)" % (sh_plain, sh_wide))
    extra = (np.abs(sh_img - sh_bgv).max(axis=2) > 24) & \
            (np.abs(sh_plain_img - sh_bgv).max(axis=2) <= 24)
    if int(extra.sum()) < 200:
        raise RuntimeError("khong co vung bong moi (%d px)" % int(extra.sum()))
    darker = float(sh_img[extra].mean())
    if darker > int(sh_bgv.max()) - 20:
        raise RuntimeError("vung bong khong toi hon nen (mean %.1f vs nen %d)"
                           % (darker, int(sh_bgv.max())))
    report["shadow_extra_mean_lum"] = round(darker, 1)
    report["shadow_grow_px"] = [sh_wide[1] - sh_plain[1], sh_wide[3] - sh_plain[3]]
    report["shadow_extra_px"] = int(extra.sum())

    # Gradient phải tô đúng HÌNH CHỮ, không phải một khối đặc. Đây là gate bắt
    # đúng cái lỗi đã xảy ra: tô gradient rồi DestinationIn bằng nét chữ là vòng
    # lặp rỗng (Qt bỏ qua composition mode khi vẽ chữ), kết quả là một hình chữ
    # nhật màu. Đo trên LÕI SÁNG (bỏ qua quầng) của từ đang hát: một hàng ngang
    # đi qua khối đặc thì kín 100%, qua chữ thì còn nhiều khe nền.
    shapes = {}
    for key in ("flame", "gradient"):
        arr = rgb(render(key, 1.0, t=0.37))
        core = arr.max(axis=2) > 170
        word, wx, ww = boxes[0]
        lo = int(line_left + wx)
        hi = int(line_left + wx + ww) + 1
        band = core[plain_box[0]:plain_box[1] + 1, lo:hi]
        fill = float(band.sum(axis=1).max()) / band.shape[1]
        if fill > 0.9:
            raise RuntimeError("kieu %s to mot khoi dac (%.2f hang ngang kin muc) "
                               "chu khong phai net chu" % (key, fill))
        shapes[key] = round(fill, 3)
    report["gradient_core_max_row_fill"] = shapes

    # Bốn kiểu màu phải có bão hoà thật (không phải chữ xám giả màu).
    for key in ("flame", "neon", "gradient", "rainbow"):
        arr = fingerprints[key]
        mx = arr.max(axis=2).astype(np.int32)
        mn = arr.min(axis=2).astype(np.int32)
        sat = float(((mx - mn) > 60)[mx > 90].mean())
        if sat < 1e-5:
            raise RuntimeError("kieu %s khong co pixel mau nao (sat=%.6f)" % (key, sat))

    clash = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = fingerprints[keys[i]], fingerprints[keys[j]]
            same = float((np.abs(a - b).max(axis=2) <= 8).mean())
            if same > 0.995:
                clash.append("%s~%s(%.4f)" % (keys[i], keys[j], same))
    if clash:
        raise RuntimeError("co kieu giong het nhau: %s" % clash[:4])
    report["distinct_pairs_ok"] = len(keys) * (len(keys) - 1) // 2

    # --- 4. parity preview/export + determinism -----------------------------
    from core.canvas_utils import ASPECT_RATIOS
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType

    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.TEXT)
    clip = model.add_clip(track.track_id, "", "text", 0.0, 4.0, name=LINE)
    if clip is None:
        raise RuntimeError("add_clip text tra None")
    clip.font_size = 44.0
    clip.font_bold = True
    clip.text_style = "neon"
    # So ở ĐÚNG khổ composer dựng, không phải khổ xuất: FrameComposer vẽ mọi clip
    # lên canvas theo project_ratio rồi mới co về out_width/out_height. So ở
    # 1280x720 là so một ảnh đã bị thu 2/3 + SmoothTransformation, lệch cả dòng
    # chữ mà tỉ lệ pixel sai vẫn nằm dưới ngưỡng.
    CW, CH = ASPECT_RATIOS["16:9"]
    composer = FrameComposer(model, CW, CH)
    local = 1.0
    sweep = min(1.0, max(0.0, local / max(1e-6, clip.duration)))
    fa = rgb(composer.render_frame(local).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied))
    direct = render("neon", sweep, t=local, size=(CW, CH))
    da = rgb(direct)
    if fa.shape != da.shape:
        raise RuntimeError("export %s ≠ direct %s" % (fa.shape, da.shape))
    diff = float((np.abs(fa - da).max(axis=2) > 24).mean())
    if diff > 0.0002:
        raise RuntimeError("export lech duong ve truc tiep %.5f anh" % diff)
    report["export_vs_direct_px"] = round(diff, 6)
    report["export_canvas"] = [CW, CH]

    again = render("neon", sweep, t=local, size=(CW, CH))
    if not np.array_equal(rgb(again), da):
        raise RuntimeError("cung (style, sweep, t) ma hai lan ve khac nhau")
    # Khong duoc giu trang thai: ve xen ke mot kieu khac roi ve lai phai giong het.
    render("rainbow", 0.5, t=9.0)
    third = render("neon", sweep, t=local, size=(CW, CH))
    if not np.array_equal(rgb(third), da):
        raise RuntimeError("co trang thai giua hai lan ve (state leak)")

    # --- 5. anh chung minh: 8 kieu x 4 sweep x 2 nen ------------------------
    # Nen SANG la bat buoc de phan dinh "outline" va "shadow": net toi mau cua
    # chung vo hinh tren nen den, nen anh chung minh chi co nen den se khong
    # chung minh duoc gi.
    sweeps = (0.0, 0.34, 0.67, 1.0)
    bgs = ("#000000", "#c8c8c8")
    cols = [(bg, sw) for bg in bgs for sw in sweeps]
    cell_w, cell_h = 340, 130
    rows = ("none",) + tuple(keys)
    sheet = QImage(cell_w * len(cols), cell_h * (len(rows) + 1),
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#141418"))
    sp = QPainter(sheet)
    small = make_font("Arial", 22, True)
    for col, (bg, sw) in enumerate(cols):
        tile = render("none", sw, font=small, size=(cell_w - 8, cell_h - 8),
                      bg=bg)
        sp.drawImage(col * cell_w + 4, cell_h + 4, tile)
    for row, key in enumerate(rows[1:], start=2):
        for col, (bg, sw) in enumerate(cols):
            tile = render(key, sw, t=0.37, font=small,
                          size=(cell_w - 8, cell_h - 8), bg=bg)
            sp.drawImage(col * cell_w + 4, row * cell_h + 4, tile)
    sp.setFont(make_font("Arial", 20, False))
    sp.setPen(QColor("#d4d4e0"))
    for col, (bg, sw) in enumerate(cols):
        sp.drawText(col * cell_w + 6, 24, "%s  sweep %.2f" % (bg, sw))
    for row, key in enumerate(rows):
        sp.drawText(6, (row + 1) * cell_h + 24, key)
    sp.end()
    sheet.save(EVIDENCE)
    report["evidence"] = EVIDENCE
    report["evidence_size"] = [sheet.width(), sheet.height()]

    print(json.dumps(report, ensure_ascii=False))
    print("OK: 8 kieu karaoke khac nhau,quet chay trai->phai,xuat giong preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
