"""
scratch/export_toast_probe.py

Gate cho toast "Xuất video xong" + nut mo file.

Chay:
    QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python scratch/export_toast_probe.py

Vi sao phai xuat THAT: dieu can chung minh la chuoi noi giữan — RenderWorker
phai xong that thi toast moi xuat hien, va no phai mo DUNG file vua sinh ra.
Mot probe tu goi Toast.popup() se khong bao gio phat hien _on_render_done
khong goi toast, hoac goi voi duong dan khac.

 Moi assert ve hinh deu do pixel that cua widget (khong phai "isNull"),
 va moi assert co the fail deu duoc doi chung bang counterfactual o cuoi.
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = os.path.join(ROOT, "scratch", "toast_tmp")
VIDEO = os.path.join(ROOT, "data", "video", "jimeng-2026-01-30-2619_new_audio.mp4")
EVID_DIALOG = os.path.join(ROOT, "scratch", "clinging_toast_dialog.png")
EVID_NEG = os.path.join(TMP, "control_no_toast.png")
EVID_EDITOR = os.path.join(ROOT, "scratch", "clinging_toast_editor.png")
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%-4s %-56s got=%r want=%r"
          % ("PASS" if ok else "FAIL", name, got, want))
    if not ok:
        FAILS.append(name)
    return ok


def above(name, got, limit):
    ok = got > limit
    print("%-4s %-56s got=%r > %r" % ("PASS" if ok else "FAIL", name, got, limit))
    if not ok:
        FAILS.append(name)
    return ok


def note(name, value):
    print("     %-56s %r" % (name, value))


def pump(seconds):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def same_path(a, b):
    """QUrl.toLocalFile() tra ve dau '/' tren Windows, nen khong duoc so
    sanh chuoi nguyen van. Chi doi dau phan tach: hoa/thuong va Unicode
    bi gao thi hai chuoi van khac nhau."""
    return a.replace("\\", "/") == b.replace("\\", "/")


def region_samples(host, toast, step=2):
    """Mau pixel trong vung toast tren anh capture cua HOST.

    grab() tren chinh toast cho ra toan bo mau trong suot vi widget dang
    gan QGraphicsOpacityEffect: chi anh cua cha moi te hop quyet cua
    effect do. grab() cua cha o pixel goc nen toa do logical cua toast
    phai nhan ty le scale DPI."""
    img = host.grab().toImage()
    sx = img.width() / float(max(1, host.width()))
    sy = img.height() / float(max(1, host.height()))
    x0 = int(toast.x() * sx)
    y0 = int(toast.y() * sy)
    x1 = min(img.width(), int((toast.x() + toast.width()) * sx))
    y1 = min(img.height(), int((toast.y() + toast.height()) * sy))
    return [img.pixelColor(x, y).rgba()
            for y in range(y0, y1, step) for x in range(x0, x1, step)]


def toast_coverage(host, toast):
    """% pixel trong vung toast DOI mau khi toast hien len so voi khi an.

    Do truc tiep tren anh cua host nen khong phu thuoc nen duong sau no:
    widget tran, hop thoai xuat toi hay editor deu phai ra cung con so."""
    shown = region_samples(host, toast)
    toast.hide()
    pump(0.12)
    hidden = region_samples(host, toast)
    toast.show()
    toast.raise_()
    pump(0.12)
    diff = sum(1 for a, b in zip(shown, hidden) if a != b)
    return 100.0 * diff / max(1, len(shown))


def file_card_pixels(path, host, rect):
    """Dem pixel dung mot mau nen card trong vung toast cua file PNG DA GHI.

    Do tren file chu khong do tren widget: lan capture dau tien cua gate
    nay cho ra anh khong co toast trong khi coverage van PASS, nen file
    chung minh phai duoc kiem tra bang chinh no. Dem ca hai bang mau vi
    toast theo chu de dang dung con hop thoai xuat thi ep bang toi."""
    from PySide6.QtGui import QColor, QImage
    from theme import Palette
    img = QImage(path).convertToFormat(QImage.Format_RGB32)
    sx = img.width() / float(max(1, host.width()))
    sy = img.height() / float(max(1, host.height()))
    want = {QColor(Palette.DARK["panel"]).rgb(),
            QColor(Palette.LIGHT["panel"]).rgb()}
    x0, y0 = int(rect.left() * sx), int(rect.top() * sy)
    x1 = min(img.width(), int(rect.right() * sx))
    y1 = min(img.height(), int(rect.bottom() * sy))
    hits = [0, 0]
    for key, colour in enumerate(sorted(want)):
        hits[key] = sum(1 for y in range(y0, y1) for x in range(x0, x1)
                        if img.pixelColor(x, y).rgb() == colour)
    return max(hits)


def shot(widget, path):
    pix = widget.grab()
    pix.save(path)
    note("evidence: " + os.path.basename(path),
         "%dx%d %d bytes" % (pix.width(), pix.height(),
                             os.path.getsize(path) if os.path.exists(path) else -1))


def build_model(dur=2.0):
    from core.timeline_model import TimelineModel, TrackType
    model = TimelineModel()
    model.project_ratio = "16:9"
    track = model.add_track(TrackType.VIDEO, "main")
    model.add_clip(track.track_id, VIDEO, "video", 0.0, dur, "clip")
    return model


# ── 1. widget ───────────────────────────────────────────────────

def section_widget(app):
    from shiboken6 import isValid
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget
    from widgets.common import Toast

    host = QWidget()
    host.resize(900, 600)
    host.show()
    pump(0.3)

    hits = []
    toast = Toast.popup(host, "Tieu de thu", "message.mp4",
                        action_label="Mở file", action=lambda: hits.append(1),
                        ms=9000)
    pump(0.5)

    check("toast la con cua host", toast.parentWidget() is host, True)
    check("toast dang hien len", toast.isVisible(), True)
    check("moi host mot toast", len(Toast._LIVE), 1)
    check("toast nam trong bounds host", host.rect().contains(toast.geometry()), True)
    check("toast o goc duoi-phai",
          (toast.x() > host.width() // 2 and toast.y() > host.height() // 2), True)
    above("toast ve len that: >80% vung cua no doi mau",
          toast_coverage(host, toast), 80.0)
    # Doi chieu cho do luong tren: cung mot widget cung kich thuoc/vi tri
    # nhung khong ve gi thi phai ra 0%. Neu metric chi do toa do thi no
    # khong phat hien duoc dieu nay.
    plain = QWidget()
    plain.resize(900, 600)
    plain.show()
    pump(0.2)
    blank = QWidget(plain)
    blank.setGeometry(400, 480, 260, 88)
    blank.raise_()
    blank.show()
    pump(0.2)
    check("doi chieu: widget trong cung vi tri -> 0% doi mau",
          toast_coverage(plain, blank), 0.0)
    blank.close()
    plain.close()
    pump(0.2)

    check("tieu de dung", toast.findChild(QLabel, "ToastTitle").text(), "Tieu de thu")
    check("ten file hien du",
          toast.findChild(QLabel, "ToastMsg").text(), "message.mp4")

    toast.findChild(QPushButton, "ToastAction").click()
    pump(0.5)
    check("bam nut chay hanh dong dung 1 lan", hits, [1])
    check("toast tat sau khi bam", len(Toast._LIVE), 0)

    Toast.popup(host, "Tu tat", "x", ms=1500)
    pump(0.4)
    check("con song truoc han", len(Toast._LIVE), 1)
    pump(2.4)
    check("tu tat sau ms da dat", len(Toast._LIVE), 0)

    first = Toast.popup(host, "A", "a", ms=9000)
    second = Toast.popup(host, "B", "b", ms=9000)
    pump(0.3)
    check("toast moi thay cho toast cu",
          (len(Toast._LIVE), Toast._LIVE.get(id(host)) is second,
           first.isVisible(), second.isVisible()),
          (1, True, False, True))

    # _LIVE co the con gi toast ma C++ object da bi huy (host dong bat ngo).
    # popup() lap lai phai tu nan, khong crash va chi de 1 toast song.
    from shiboken6 import delete as sip_delete
    stale = Toast.popup(host, "S", "s", ms=9000)
    sip_delete(stale)
    check("_LIVE dang gi widget da chet", Toast._LIVE.get(id(host)) is stale, True)
    revived = Toast.popup(host, "Phuc hoi", "van mo duoc", ms=9000)
    pump(0.3)
    check("popup khong crash khi _LIVE con con tro chet",
          (len(Toast._LIVE), isValid(revived), revived.isVisible()),
          (1, True, True))

    # Host dong khi toast con song: toast la con cua host nen phai an theo,
    # khong de lai cua roi chet tren man hinh.
    host.close()
    pump(0.3)
    check("dong host thi toast an theo", revived.isVisible(), False)
    Toast._LIVE.clear()


# ── 2. XUAT THAT QUA ExportDialog ───────────────────────────────

def section_export(app):
    import ui.export_dialog as ed
    from PySide6.QtWidgets import QLabel, QPushButton
    from ui.export_dialog import ExportDialog
    from widgets.common import Toast

    out = os.path.join(TMP, "toast_export.mp4")
    if os.path.exists(out):
        os.remove(out)

    dialog = ExportDialog(build_model())
    dialog.show()
    pump(0.4)

    opened = []
    real_open = ed.open_local_file
    ed.open_local_file = lambda p: (opened.append(p), True)[1]
    done = []
    dialog.exportFinished.connect(done.append)
    try:
        t0 = time.time()
        dialog._start_render(out, 320, 180, 12, "16:9", False)
        deadline = time.time() + 420
        while time.time() < deadline and not done:
            pump(0.2)
        note("xuat %d frame 320x180@12" % int(2.0 * 12), "%.1f s" % (time.time() - t0))

        check("xuat khong loi (co exportFinished)", len(done), 1)
        check("exportFinished mang dung duong dan", done, [out])
        check("file xuat co that tren dia", os.path.isfile(out), True)
        above("file xuat co kich thuoc", os.path.getsize(out) / 1024.0, 10.0)
        check("dialog luu duong dan", dialog.exported_path, out)

        toast = Toast._LIVE.get(id(dialog))
        check("toast xuat hien TREN hop thoai xuat (modal)",
              toast is not None and toast.parentWidget() is dialog, True)
        check("tieu de toast", toast.findChild(QLabel, "ToastTitle").text(),
              "Xuất video xong")
        check("toast chi dung ten file vua xuat",
              toast.findChild(QLabel, "ToastMsg").text(), os.path.basename(out))
        check("toast co nut Mo file",
              toast.findChild(QPushButton, "ToastAction") is not None, True)
        # Toast la lop de len: no khong duoc choang cho nut cua chinh hop
        # thoai, neu khong "Mo file" se danh mat nguoi dung nut "Xuat lai".
        from PySide6.QtCore import QPoint
        btn_top = dialog.btn_export.mapTo(dialog, QPoint(0, 0)).y()
        note("top nut Xuat lai / day toast",
             "%d / %d" % (btn_top, toast.geometry().bottom()))
        check("toast khong de len nut Xuat lai",
              toast.geometry().bottom() < btn_top, True)
        # Capture TRUOC khi do coverage: coverage phai an toast de lay nen
        # so sanh, va Qt khong ve lai mot widget gan QGraphicsOpacityEffect
        # sau cap hide()/show() (da do: grab sau show ra dung anh nen). An
        # toast roi moi capture thi anh chung minh se mat toast.
        # Fade vao 170ms: capture ngay sau khi toast sinh ra thi card con
        # trong suot mot phan (lan dau tien nut "Xuat lai" lo xuyen qua
        # than card trong anh chung minh). Chay het vong animation roi moi do.
        pump(0.4)
        rect = toast.geometry()
        shot(dialog, EVID_DIALOG)
        above("file chung minh co than toast tren hop thoai",
              file_card_pixels(EVID_DIALOG, dialog, rect), 3000)
        above("toast ve du pixel tren hop thoai",
              toast_coverage(dialog, toast), 80.0)

        toast.findChild(QPushButton, "ToastAction").click()
        pump(0.5)
        check("hanh dong mo DUNG file vua xuat", opened, [out])
        check("dialog danh dau da mo file", dialog.file_opened, True)
        check("toast tat sau khi mo", Toast._LIVE.get(id(dialog)) is None, True)
        # Doi chieu cho do luong tren file: cung hop thoai, cung vung do,
        # luc toast da tat thi file phai ra 0 pixel nen card.
        shot(dialog, EVID_NEG)
        check("doi chieu: file khong toast -> 0 pixel nen card",
              file_card_pixels(EVID_NEG, dialog, rect), 0)
    finally:
        ed.open_local_file = real_open
        dialog.close()
        pump(0.3)
    return out


# ── 3. TOAST ROI TREN CUA SO EDITOR ─────────────────────────────

def section_editor(app, out):
    from PySide6.QtWidgets import QLabel, QPushButton
    import widgets.common as wc
    from ui.export_dialog import ExportDialog
    from ui.main_window import MainWindow
    from widgets.common import Toast

    win = MainWindow()
    win.resize(1400, 820)
    win.show()
    pump(1.2)

    dialog = ExportDialog(build_model())
    dialog.exported_path = out
    try:
        # (a) Da mo file o hop thoai thi khong lap lai nua.
        dialog.file_opened = True
        win._toast_export_result(dialog)
        pump(0.3)
        check("da mo file -> khong toast trung", Toast._LIVE.get(id(win)) is None, True)

        # (b) Dong hop thoai khi chua mo -> toast roi tren editor.
        calls = []
        real_open = wc.open_local_file
        wc.open_local_file = lambda p: (calls.append(p), True)[1]
        try:
            dialog.file_opened = False
            win._toast_export_result(dialog)
            pump(0.5)
            toast = Toast._LIVE.get(id(win))
            check("chua mo -> co toast tren editor",
                  toast is not None and toast.parentWidget() is win, True)
            check("toast editor dung ten file vua xuat",
                  toast.findChild(QLabel, "ToastMsg").text(), os.path.basename(out))
            rect = toast.geometry()
            shot(win, EVID_EDITOR)
            above("file chung minh co than toast tren editor",
                  file_card_pixels(EVID_EDITOR, win, rect), 3000)
            above("toast ve du pixel tren editor",
                  toast_coverage(win, toast), 80.0)
            toast.findChild(QPushButton, "ToastAction").click()
            pump(0.4)
            check("toast editor mo dung file", calls, [out])
            check("toast tat sau khi bam", Toast._LIVE.get(id(win)) is None, True)
        finally:
            wc.open_local_file = real_open

        # (c) Khong co duong dan thi khong co toast (duong bi/huy).
        empty = ExportDialog(build_model())
        win._toast_export_result(empty)
        pump(0.3)
        check("khong xuat xong -> khong toast", Toast._LIVE.get(id(win)) is None, True)
    finally:
        dialog.close()
        win.close()
        pump(0.4)


# ── 4. DUONG MO FILE CUA HE DIEU HANH ───────────────────────────

def section_open_path(app, out):
    import widgets.common as wc
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    check("duong dan rong -> False", wc.open_local_file(""), False)
    check("file khong ton tai -> False",
          wc.open_local_file(os.path.join(TMP, "khong_co_file.mp4")), False)

    captured = []
    real = QDesktopServices.openUrl
    QDesktopServices.openUrl = staticmethod(lambda url: (captured.append(url), True)[1])
    try:
        ok = wc.open_local_file(out)
    finally:
        QDesktopServices.openUrl = real
    check("file that -> True", ok, True)
    check("Qt nhan DUNG mot URL file local", len(captured), 1)
    url = captured[0]
    check("URL tro toi file vua xuat",
          same_path(url.toLocalFile(), os.path.abspath(out)), True)
    note("URL tho (chi khac dau phan tach)", url.toLocalFile())
    check("URL la scheme file", url.scheme(), "file")

    # Duong dan co dau va dau cach phai di qua QUrl.fromLocalFile chu khong
    # qua chuoi tay — dung mot file that o thu muc ten tieng Viet de kiem.
    weird = os.path.join(TMP, "dự án của tôi", "kết quả final.mp4")
    os.makedirs(os.path.dirname(weird), exist_ok=True)
    with open(weird, "wb") as handle:
        handle.write(b"x")
    got = []
    QDesktopServices.openUrl = staticmethod(lambda u: (got.append(u), True)[1])
    try:
        wc.open_local_file(weird)
    finally:
        QDesktopServices.openUrl = real
    check("duong dan dau cach + Unicode khong bi gao",
          same_path(got[0].toLocalFile(), os.path.abspath(weird)), True)
    note("URL tho (Unicode)", got[0].toLocalFile())


# ── 5. COUNTERFACTUAL: cac khoa tren CO THE FAIL ────────────────

def section_counterfactual(app):
    import ui.export_dialog as ed
    import widgets.common as wc
    from ui.export_dialog import ExportDialog
    from ui.main_window import MainWindow
    from widgets.common import Toast

    # (a) Neu _on_render_done KHONG goi toast thi khoa o muc 2 phai no.
    #     Gia lap Toast.popup = do luong xem no duoc goi may lan, roi goi
    #     dung callback cua worker.
    dialog = ExportDialog(build_model())
    pops = []
    real_popup = Toast.popup

    def spy_popup(host, title, message="", **kw):
        pops.append((title, message))
        return None

    Toast.popup = staticmethod(spy_popup)
    try:
        dialog._on_render_done(os.path.join(TMP, "dao_gia.mp4"))
    finally:
        Toast.popup = real_popup
    check("_on_render_done tu goi Toast.popup (khong do probe goi)",
          pops, [("Xuất video xong", "dao_gia.mp4")])
    check("_on_render_done dat duong dan de editor dung lai",
          os.path.basename(dialog.exported_path), "dao_gia.mp4")

    # (b) Neu chu tich "da mo" bi bo qua thi khoa (a) o muc 3 phai no:
    #     mo Toast.popup de dem, goi _toast_export_result voi file_opened=True.
    win = MainWindow()
    win.resize(1200, 700)
    win.show()
    pump(1.0)
    count = []
    Toast.popup = staticmethod(lambda *a, **k: count.append(1))
    try:
        dialog.file_opened = True
        win._toast_export_result(dialog)
        check("file_opened=True van toast -> khoa (a) muc 3 DAO CHIEU",
              len(count), 0)
        dialog.file_opened = False
        win._toast_export_result(dialog)
        check("nhung file_opened=False thi phai co toast", len(count), 1)
    finally:
        Toast.popup = real_popup
        win.close()
        dialog.close()
        pump(0.3)

    # (c) Hanh dong phai mo file DA BI XOÁ mà không crash: goi _open_exported_file
    #     voi duong dan khong con tren dia (open_local_file THAT, khong spy).
    gone = os.path.join(TMP, "vua_bi_xoa.mp4")
    dialog.exported_path = gone
    dialog.file_opened = False
    dialog._open_exported_file()
    check("file bi xoa -> khong mo, khong crash", dialog.file_opened, False)

    # (d) Khoa (c) muc 3 phai phan biet: mot dialog khong xuat gi ca
    #     thi khong duoc toast. Da kiem o muc 3; o day kiem nguoc:
    #     duong dan rong + file_opened=False thi van im lang.
    empty = ExportDialog(build_model())
    empty.exported_path = ""
    empty.file_opened = False
    win2 = MainWindow()
    win2.show()
    pump(0.8)
    hits = []
    Toast.popup = staticmethod(lambda *a, **k: hits.append(a))
    try:
        win2._toast_export_result(empty)
    finally:
        Toast.popup = real_popup
        win2.close()
        pump(0.3)
    check("khong co duong dan -> khong toast", hits, [])

    # (e) Khoa "toast khong de len nut" o muc 2 phai phan biet duoc: cung
    #     hop thoai, y_shift=0 thi the card moc len nut "Xuat lai".
    from PySide6.QtCore import QPoint
    d2 = ExportDialog(build_model())
    d2.show()
    pump(0.5)
    plain_toast = Toast.popup(d2, "A", "b", ms=9000, dark=True)
    plain_bottom = plain_toast.geometry().bottom()
    lifted = Toast.popup(d2, "A", "b", ms=9000, dark=True, y_shift=-56)
    btn_top = d2.btn_export.mapTo(d2, QPoint(0, 0)).y()
    note("top nut / day toast y_shift=0 / day toast y_shift=-56",
         "%d / %d / %d" % (btn_top, plain_bottom, lifted.geometry().bottom()))
    check("DAO CHIEU: y_shift=0 thi de len nut that",
          plain_bottom >= btn_top, True)
    check("y_shift=-56 thi tron nut", lifted.geometry().bottom() < btn_top, True)
    d2.close()
    pump(0.3)


def main():
    os.makedirs(TMP, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    print("== 1. widget ==")
    section_widget(app)
    print("== 2. xuat that qua ExportDialog ==")
    out = section_export(app)
    print("== 3. toast roi tren editor ==")
    section_editor(app, out)
    print("== 4. duong mo file cua he dieu hanh ==")
    section_open_path(app, out)
    print("== 5. counterfactual ==")
    section_counterfactual(app)

    print("\n%s  (%d fail)" % ("summary: ALL PASS" if not FAILS else "summary: FAIL",
                               len(FAILS)))
    for line in FAILS:
        print("  FAIL " + line)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
