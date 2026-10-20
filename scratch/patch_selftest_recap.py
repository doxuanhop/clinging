"""Thêm dòng --selftest 'lop phu recap' vào diagnostics.py (neo: sau _aura_ok)."""
import io

PATH = r"D:\Programming\clinging\diagnostics.py"
s = io.open(PATH, "r", encoding="utf-8", newline="").read()
assert "\r\n" not in s, "diagnostics.py phai LF"

ROW = '    col.check("8 aura to sang va chay theo dong ho clip", _aura_ok)\n'
assert s.count(ROW) == 1
s = s.replace(ROW, ROW + '    col.check("lop phu recap: vien/REC/kinh mo + luu vao file", _recap_overlay_ok)\n', 1)

FUNC = '''

def _recap_overlay_ok():
    """Một dòng --selftest: lớp phủ recap sống ở model, trong file dự án và ở cả hai đường vẽ.

    Không giống aura, đây là cấu hình CẢ DỰ ÁN nên bốn mắt xích phải khớp: mặc
    định tắt (file cũ không có khoá), clamp khi đọc, tròn-trip qua
    ``save_project_to_file``/``restore_model_from_clinq``, và FrameComposer phải
    đổi pixel thật. Đo trên nền trắng xoá ở 640x360 (k=0.5) để nét vẫn còn dày
    hơn một pixel mà không phải dựng cả cửa sổ.
    """
    import numpy as np
    import tempfile
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from core import project_storage, recap_overlay
    from core.frame_composer import FrameComposer
    from core.timeline_model import TimelineModel, TrackType

    if recap_overlay.overlay_active({}):
        raise RuntimeError("mac dinh phai TAT nhung overlay_active({}) = True")
    clamped = recap_overlay.normalize({"bg_brightness": 9, "border_width": 0,
                                       "reticle_shape": "khong_co"})
    if clamped["bg_brightness"] != 1.0 or clamped["border_width"] < 1.0 \\
            or clamped["reticle_shape"] != "cross":
        raise RuntimeError("normalize khong clamp: %s" % clamped)

    W, H = 640, 360
    folder = os.path.join(tempfile.gettempdir(), "clinging_recap_report")
    os.makedirs(folder, exist_ok=True)
    png = os.path.join(folder, "nen_trang.png")
    if not os.path.exists(png):
        seed = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        seed.fill(Qt.GlobalColor.white)
        seed.save(png)

    settings = {"enabled": True, "border": True, "border_color": "#3673FE",
                "reticle": True, "reticle_shape": "scope",
                "reticle_color": "#00FFFF", "rec": True, "rec_fps": 30}

    def build(overlay):
        model = TimelineModel()
        model.project_ratio = "16:9"
        track = model.add_track(TrackType.IMAGE)
        clip = model.add_clip(track.track_id, png, "image", 0.0, 2.0, name="recap")
        if clip is None:
            raise RuntimeError("add_clip tra None (track/media khong khop)")
        model.set_recap_overlay(overlay)
        return model

    def frame(model):
        composer = FrameComposer(model, W, H)
        try:
            img = composer.render_frame(0.5).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied)
        finally:
            composer.close()
        buf = img.constBits()
        raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
        row = img.bytesPerLine() // 4
        return np.frombuffer(raw, np.uint8).reshape((H, row, 4))[:, :W, :3].astype(np.int16)

    def count(px, hexcolor, tol):
        c = QColor(hexcolor)
        d = np.abs(px - np.array([c.red(), c.green(), c.blue()], np.int16))
        return int((d.max(axis=2) <= tol).sum())

    on = frame(build(settings))
    off = frame(build({"enabled": False}))
    border = count(on, "#3673FE", 60)
    reticle = count(on, "#00FFFF", 60)
    #Vien 4*k=2px quanh 640x360 ~ 4000px, tam ngam scope ~ 200px; bat ky lop nao
    #bang 0 la mat nui ve, con khac biet on/off = 0 la master off khong tat.
    if border < 1500 or reticle < 60:
        raise RuntimeError("lop phu khong hien khi bat (vien %d, tam ngam %d px)"
                           % (border, reticle))
    if np.array_equal(on, off):
        raise RuntimeError("bat full overlay ma khung khong doi pixel")
    if count(off, "#00FFFF", 60) or count(off, "#3673FE", 60):
        raise RuntimeError("master off van con ve lop phu")

    path = os.path.join(folder, "Kiem recap.clinq")
    project_storage.save_project_to_file(build(settings), path)
    reloaded = TimelineModel()
    data = project_storage.load_project_from_file(path)
    if not data:
        raise RuntimeError("load_project_from_file tra rong")
    project_storage.restore_model_from_clinq(reloaded, data)
    if reloaded.recap_overlay != recap_overlay.normalize(settings):
        raise RuntimeError("recap_overlay khong tron ven qua file: %s"
                           % (reloaded.recap_overlay,))
    return ("vien %d px, tam ngam %d px, master off sach %d/%d, file giu nguyen %d khoa"
            % (border, reticle, int((np.abs(on - off).max(axis=2) > 6).sum()),
               W * H, len(reloaded.recap_overlay)))

'''

ANCHOR = "\n\ndef _project_fixture():"
assert s.count(ANCHOR) == 1
s = s.replace(ANCHOR, FUNC + "\ndef _project_fixture():", 1)

io.open(PATH, "w", encoding="utf-8", newline="").write(s)
import ast
ast.parse(io.open(PATH, encoding="utf-8", newline="").read())
print("OK diagnostics.py co dong selftest recap")
