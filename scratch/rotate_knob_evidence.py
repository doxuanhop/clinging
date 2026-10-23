"""scratch/rotate_knob_evidence.py — anh CHUP THAT cua tay nam xoay co glyph.

Tay nam xoay ve trong `CanvasClipItem.paint` duong dan cua scene preview, KHONG
phai FrameComposer — nen `--transform-report` (do pixel cua xuat) khong nhin
thay no. Dong selftest "bien doi" do bang `rotate_glyph_pixel_count` (scene.
render vao QImage). Rieng hai duong do deu la Qt tu ve; con so o day lay tu
MAN HINH VONG NGOAI: anh toan man hinh 1920x1080 chup bang PIL ImageGrab, tuc
la dung thu nguoi dung nhin thay.

An toan du lieu nguoi dung: dung het khuon cua `editor_screen_shots.py` —
fixture tu sinh bang lavfi trong %PUBLIC%\\ClingingEditorShot, `.clinq` nam
trong goc do, cache/autosave/recovery redirect ve tam, va HAI cua chieu:
recent_projects.json khong doi byte, cache nguoi dung khong them file.

Do tren anh (khong phai do trong Qt):
  dia tay nam = vung tron ban kinh ROTATE_HANDLE_R quy ra pixel thiet bi, tam
  la `mapToGlobal(mapToScene(_rotate_handle_pos()))` cua chinh item.
    white = dem pixel gan trang (min(r,g,c) > 200)   -> co dia
    dark  = dem pixel toi (max(r,g,c) < 90)          -> co glyph
  Khong chon thi item khong ve tay nam, nen `white` phai ve 0 — do la cap
  CHON/KHONG CHON phan biet, khong phai mot nguong tu choi.

Chay:
    python -u scratch/rotate_knob_evidence.py            # do + luu anh
    python -u scratch/rotate_knob_evidence.py --pixels   # phan chung tren anh
"""
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import editor_screen_shots as ess                     # noqa: E402
from PIL import Image                                 # noqa: E402

UIX = os.path.join(ROOT, "assets", "uiux")
SHOT = os.path.join(UIX, "editor-rotate-knob.png")
# Ban phong 4x la CROP THAT cua anh tren (nearest, khong ve them gi), luu sang
# assets/uiux vi o 1:1 tay nam 10 px nam giua anh 1920x1080 khong ai nhin ra.
DETAIL = os.path.join(UIX, "editor-rotate-knob-detail.png")
OFF = os.path.join(ROOT, "scratch", "rotate_knob_unselected.png")
ZOOM = os.path.join(ROOT, "scratch", "rotate_knob_zoom.png")
MEASURE = os.path.join(ROOT, "scratch", "rotate_knob_evidence.json")
fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))
    print("%-56s %s got=%r want=%r" % (label, "PASS" if ok else "FAIL", got, want))
    return ok


def above(label, got, limit):
    ok = got > limit
    if not ok:
        fails.append("%s: got %r not above %r" % (label, got, limit))
    print("%-56s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def below(label, got, limit):
    ok = got < limit
    if not ok:
        fails.append("%s: got %r not below %r" % (label, got, limit))
    print("%-56s %s value=%r limit=%r" % (label, "PASS" if ok else "FAIL", got, limit))
    return ok


def counts(img, cx, cy, radius):
    """(white, dark) trong vung tron tam (cx, cy) ban kinh radius, toa do anh.

    Tam co the nam sat mép anh (view cat tay nam), nen clip cua crop phai doi
    chieu duoc bao — `crop` noi khong biet chiu toa do dao nguoc.
    """
    x0, x1 = int(cx - radius), int(cx + radius + 1)
    y0, y1 = int(cy - radius), int(cy + radius + 1)
    left, top = max(x0, 0), max(y0, 0)
    right, bottom = min(x1, img.width), min(y1, img.height)
    if right <= left or bottom <= top:
        return 0, 0, 0
    crop = img.crop((left, top, right, bottom))
    px = list(crop.getdata())
    white = dark = total = 0
    for index, (r, g, b) in enumerate(px):
        col, row = index % crop.width, index // crop.width
        dx = left + col - cx
        dy = top + row - cy
        if dx * dx + dy * dy > radius * radius:
            continue
        total += 1
        if min(r, g, b) > 200:
            white += 1
        elif max(r, g, b) < 90:
            dark += 1
    return white, dark, total


def measure(img, cx, cy, radius):
    white, dark, total = counts(img, cx, cy, radius)
    return {"white": white, "dark": dark, "total": total,
            "white_frac": round(white / float(total or 1), 3),
            "dark_frac": round(dark / float(total or 1), 3)}


def knob_geometry(canvas, item):
    """(cx, cy, radius) cua dia tay nam quy ra TOA DO MAN HINH that + tam trong viewport.

    Tam lay tu chinh pixel ma View canvas nhin ra, khong phai tu phep nhan
    tay: `mapFromScene` roi `mapToGlobal` cua DICH item, ban kinh la hieu hai
    viewport point cua hai moc cach nhau ROTATE_HANDLE_R don vi local.
    """
    from PySide6.QtCore import QPointF
    from ui.graphics_canvas_item import ROTATE_HANDLE_R

    stem = item._rotate_handle_pos()
    center_scene = item.mapToScene(stem)
    edge_scene = item.mapToScene(stem + QPointF(ROTATE_HANDLE_R, 0.0))
    view_center = canvas.mapFromScene(center_scene)
    view_edge = canvas.mapFromScene(edge_scene)
    radius = abs(view_edge.x() - view_center.x())
    global_point = canvas.mapToGlobal(view_center)
    return (float(global_point.x()), float(global_point.y()), radius,
            float(view_center.x()), float(view_center.y()))


def place_knob(canvas, item, vx, vy):
    """Dich item so cho tam tay nam nam dung pixel (vx, vy) CUA VIEW.

    Tam phai nam duoi mép tren viewport: `fitInView(sceneRect)` cat bol đi mọi
    thu ngoai scene rect, ma tay nam lai ở CAO hon mép tren clip
    (ROTATE_OFFSET = 24 don vi local). Clip full-frame vi the co tay nam
    ngot khoi anh — dat no bang toa do nguoc la buoc duy nhat de phep do
    duoi do dung vao glyph chu khong vao nen canvas.
    """
    from PySide6.QtCore import QPoint
    from ui.graphics_canvas_item import ROTATE_OFFSET

    target_scene = canvas.mapToScene(QPoint(int(vx), int(vy)))
    rect = item.rect()
    scale = item.scale()
    item.setPos(target_scene.x() - scale * rect.center().x(),
                target_scene.y() - scale * (rect.top() - ROTATE_OFFSET))
    item.setRotation(0.0)


def run_capture():
    from core import media_cache, project_storage
    from core.project_storage import save_project_to_file

    real_cache_root = media_cache.cache_root
    user_cache_before = ess.count_files(real_cache_root())
    mru_before = ess.mru_bytes()

    shutil.rmtree(ess.WORK, ignore_errors=True)
    media_cache.cache_root = lambda: os.path.join(ess.WORK, "_cache")
    project_storage.AUTO_SAVE_FILE = os.path.join(ess.WORK, "_autosave.json")
    project_storage.RECOVERY_DIR = os.path.join(ess.WORK, "_recovery")

    app = ctrl = None
    try:
        print("== 1. fixture ==")
        proj, (src_a, _src_b) = ess.make_media()
        clinq = str(proj / ("%s.clinq" % ess.PROJECT))
        check("luu .clinq qua duong production",
              save_project_to_file(ess.build_model(src_a, _src_b), clinq, {
                  "project_name": ess.PROJECT,
                  "resolution": {"width": ess.W, "height": ess.H},
                  "fps": ess.FPS, "aspect_ratio": "16:9"}), True)

        print("\n== 2. cua so that ==")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        def pump(times=8, pause=0.03):
            for _ in range(times):
                app.processEvents()
                time.sleep(pause)

        from ui.main_controller import MainController
        from ui.graphics_canvas_item import CanvasClipItem
        from core.project_storage import ProjectManager
        ctrl = MainController()
        ctrl.show()
        pump(10)
        check("mo du an fixture", ctrl.open_project_path(clinq), True)
        pump(30)
        sw, sh = ess.shot.screen_size()
        main_hwnd, main_pid = ess.own_hwnd(ctrl)
        check("handle cua chinh thuoc ve pid nay", main_pid, os.getpid())
        ess.place(main_hwnd, 0, 0, sw, sh)
        pump(6)
        check("du an dang mo la fixture",
              os.path.abspath(ProjectManager().project_path or "").startswith(
                  os.path.abspath(ess.WORK)), True)

        canvas = ctrl.editor_page.preview_panel.canvas
        items = [it for it in canvas._clip_items.values()
                 if isinstance(it, CanvasClipItem)]
        check("canvas co item video hinh", len(items) > 0, True)
        item = items[0]

        # Khong thu nho item: so o day phai la kich co THAT cua tay nam trong
        # cua so max 1920x1080, tuc la thu nguoi dung nhin thay.
        view_scale = float(canvas.transform().m11())
        vp = canvas.viewport().size()
        print("   canvas viewport=%dx%d view_scale=%.3f item_scale=%.3f "
              "media_rect=%dx%d" % (vp.width(), vp.height(), view_scale,
                                    item.scale(), int(item.rect().width()),
                                    int(item.rect().height())))
        place_knob(canvas, item, vp.width() * 0.5, vp.height() * 0.12)
        pump(20)

        cx, cy, radius, vx, vy = knob_geometry(canvas, item)
        above("ban kinh dia tay nam quy ra pixel", radius, 2.5)
        check("tam tay nam nam TRONG viewport",
              0 <= vx < vp.width() and 0 <= vy < vp.height(), True)
        print("   knob: man hinh=(%.0f, %.0f) viewport=(%.0f, %.0f) "
              "ban kinh=%.2f px (duong kinh %.1f px)"
              % (cx, cy, vx, vy, radius, radius * 2))

        print("\n== 3. do KHONG CHON ==")
        canvas.scene_obj.clearSelection()
        pump(12)
        bbox = ess.shot.frame_bounds(main_hwnd)
        img_off = ess.shot.grab_screen(bbox)
        off = measure(img_off, cx - bbox.left, cy - bbox.top, radius)
        print("   khong chon: %s" % off)

        print("\n== 4. do CHON ==")
        item.setSelected(True)
        pump(12)
        img_on = ess.shot.grab_screen(bbox)
        on = measure(img_on, cx - bbox.left, cy - bbox.top, radius)
        print("   co chon: %s" % on)

        check("hai lan chup cung mot bbox", [img_off.width, img_off.height],
              [img_on.width, img_on.height])
        check("anh la toan man hinh that",
              [img_on.width, img_on.height], [sw, sh])
        above("A: dia trang xuat hien khi chon clip", on["white"], 8)
        below("B: bo chon thi het dia trang", off["white"], 4)
        above("C: glyph toi nam trong dia", on["dark"], 4)
        # Glyph chi la MOT MUI TEN: no chiem phan trong dia, khong duoc lap
        # day — neu dem duoc 100% max thi do vao nen toi, khong do vao glyph.
        below("D: glyph chi mot phan cua dia", on["dark_frac"], 0.6)
        above("E: sau khi chon, vung do sang hon luc bo chon",
              on["white"] - off["white"], 6)

        print("\n== 5. luu anh ==")
        img_on.save(SHOT)
        img_off.save(OFF)
        zoom = img_on.crop((int(cx - bbox.left - 90), int(cy - bbox.top - 90),
                            int(cx - bbox.left + 90), int(cy - bbox.top + 90)))
        zoom = zoom.resize((zoom.width * 4, zoom.height * 4), Image.NEAREST)
        zoom.save(ZOOM)
        zoom.save(DETAIL)
        check("anh toan man hinh da luu", os.path.isfile(SHOT), True)
        check("anh luc bo chon da luu", os.path.isfile(OFF), True)
        check("anh phong to 4x da luu", os.path.isfile(ZOOM), True)
        check("crop phong to da luu sang assets/uiux",
              os.path.isfile(DETAIL), True)
        above("E: anh PNG co du noi dung (> 20000 B)", os.path.getsize(SHOT),
              20000)

        payload = {"shot": SHOT, "zoom": ZOOM, "detail": DETAIL,
                   "unselected": OFF,
                   "bbox": [bbox.left, bbox.top, bbox.right, bbox.bottom],
                   "center_in_shot": [cx - bbox.left, cy - bbox.top],
                   "radius": radius, "selected": on, "unselected_meas": off,
                   "screen": [sw, sh],
                   "view_scale": view_scale, "viewport": [vp.width(), vp.height()],
                   "item_scale": item.scale()}
        with open(MEASURE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
    finally:
        if ctrl is not None:
            ctrl.close()
            for _ in range(30):
                app.processEvents()
                time.sleep(0.03)
        user_cache_after = ess.count_files(real_cache_root())
        check("khong them file vao cache nguoi dung",
              user_cache_after, user_cache_before)
        check("recent_projects.json khong doi byte", ess.mru_bytes(), mru_before)
        shutil.rmtree(ess.WORK, ignore_errors=True)

    if fails:
        print("CO FAIL: " + " | ".join(fails))
        return 1
    print("ALL PASS")
    return 0


def pixels_selfcheck():
    """Phan chung tren ANH DA LUU: cua do PHAI do vi dung vung pixel cua no.

    Vet 1 do den vung tron bang XAM TRUNG TINH (128,128,128) — mau nay khong
    phai trang (min 128 < 200) cung khong phai toi (max 128 > 90), nen ca hai
    con so phai ve 0: chung no lay tu dung region chu khong phai tu mot gia
    tri toan cuc nao do. Doi bang nen toi (18,19,23) thi `dark` van 81 vi
    chinh mau do la mau toi — do la luan vi vong, do 23/10/2026.
    Vet 2 do LAI tam do tren anh CHUP LUC BO CHON — cung toa do, cung ban kinh
    ma pixel khac nhau: chung region khong tu dem ra dia.
    Vet 3 lech tam 40 px vuot ra tren dia — so du lech toa do co nghia.
    """
    with open(MEASURE, encoding="utf-8") as handle:
        data = json.load(handle)
    img = Image.open(data["shot"]).convert("RGB")
    cx, cy = data["center_in_shot"]
    radius = data["radius"]
    print("== phan chung tren %s ==" % os.path.basename(data["shot"]))
    base = measure(img, cx, cy, radius)
    check("baseline khop voi so da do",
          [base["white"], base["dark"]],
          [data["selected"]["white"], data["selected"]["dark"]])

    blanked = img.copy()
    from PIL import ImageDraw
    ImageDraw.Draw(blanked).ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(128, 128, 128))
    wiped = measure(blanked, cx, cy, radius)
    below("vet 1: xoa region thi het pixel trang", wiped["white"], 4)
    below("vet 1: xoa region thi het glyph toi", wiped["dark"], 4)

    off_img = Image.open(data["unselected"]).convert("RGB")
    off_meas = measure(off_img, cx, cy, radius)
    below("vet 2: cung region tren anh bo chon thi het dia trang",
          off_meas["white"], 4)
    check("vet 2: anh bo chon cung kich thuoc anh chup",
          [off_img.width, off_img.height], [img.width, img.height])

    shifted = measure(img, cx, cy - (radius + 40.0), radius)
    below("vet 3: lech tam 40 px vuot ra tren dia thi het pixel trang",
          shifted["white"], 4)

    if fails:
        print("CO FAIL: " + " | ".join(fails))
        return 1
    print("ALL PASS (phan chung)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(pixels_selfcheck() if "--pixels" in sys.argv else run_capture())
