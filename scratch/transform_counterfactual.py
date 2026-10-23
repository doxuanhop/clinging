"""Phan chung cho nhom "Bien doi" (xoay tu do + lat + canh le + khoa ty le).

Hai oracle, mot cho moi vet:
  * `python main.py --selftest <json> --only=<dong bien doi>` — xich ma noi:
    co nam trong model/.clinq/undo, goc dung dai, 12 nut nam trong the, keo tay
    nam ra dung mot buoc.
  * `python main.py --transform-report <json>` — do TREN ANH: lat co dao mau
    khong, xoay 90 co dao truc khong, canh mep co cham 0, xem truoc co cung mat
    voi xuat.

Ly do phai co ca hai: vet `export_bo_xoay` (FrameComposer khong con xoay) lam
DO bang report ma dong selftest van XANH — no chi doc so trong model, khong nhin
pixel. Chieu nguoc lai, vet `canh_khong_theo_hop_xoay` chi dong selftest do
duoc (report canh luc dang 0 do nen khong phat hien). Mot trong hai oracle bo
sot la co that.

 1. export_bo_lat               (report) "lat ngang dao hai nua mau"
 2. preview_bo_lat              (report) "xem truoc cung mat voi xuat sau lat"
 3. export_bo_xoay              (report) "xoay 90 dao rong cao"  — selftest XANH
 4. canh_khong_theo_hop_xoay    (selftest) "canh trai khi xoay 90 ra x="
 5. align_start_tra_0           (selftest) "canh mep sai"
 6. rotated_box_khong_dao_truc  (selftest) "xoay 90 khong dao truc"
 7. normalize_khong_goi         (selftest) "_normalize_angle tra goc ngoai"
 8. bounding_an_room            (selftest) "boundingRect thieu ROTATE_ROOM"
    (cua "vung xoay tron ngoai boundingRect" XANH vi tren khung 320x180 cua
     dong do, margin = HANDLE_SIZE+4+aura_reserve = 12+216 px > 34 px ma tay
     nam can — no le thuoc kich thuoc khung, nen ngoi seam moi phan biet duoc)
 9. hit_test_rotate_gia         (selftest) "keo tay nam +45 do ra goc"
    (`item.contains()` cua Qt di qua shape(), khong qua `_hit_test_rotate`:
     phep thu hit-test van xanh, chi cu keo that moi lo ra)
10. luu_mat_co                  (selftest) "luu mo lech"
11. doc_legacy_gan_co           (selftest) "file cu bi gan co la"
12. pct_chi_ghi_mot_truc        (selftest) "hai truc phai bang nhau"
13. khoa_dong_van_nhap_duoc     (selftest) "khoa dong ma van cho nhap tung truc"
14. reset_giu_goc               (selftest) "Dat lai con sot"
15. nut_lat_khong_push          (selftest) "khong ghi co len model"
16. thang_do_dem_sau_nut        (selftest) "thang do ghi 11" — vet do LAI
    THANG DO, khong do san pham: chung minh con so 12 la mot cua, khong phai
    mot chuoi ghi chu (bai hoc hang so menu cu trong bundle 1.0.4).
17. fixture_trang_don           (report) "fixture lech mau bon goc" — vet do
    FIXTURE: nen dong nhat thi moi phep lat deu "dung" va cua do xanh vi khong
    co gi de dao.
18. align_end_tra_0             (report) "canh phai cham mep phai" — cung mot
    phep doi byte o `align_center` nhu vet 5, nhung do bang ANH: do la duong
    ma dong selftest khong nhin thay (no so voi con so -480/+480).
19. glyph_tay_nam_an_het        (selftest) "tay nam xoay khong co glyph" —
    tay nam trong (khong mũi tên) thi dong van xanh vi cac phep do xich ma deu
    dat: `rotate_glyph_pixel_count` dem pixel toi trong đĩa duong kinh 11 don vi
    va do SAN PHAM VE, khong do code.

Vet CU duoc ghi ra file that, nen mot lan bi cat giua chung de lai file nguon
dam loa: moi vet copy ban goc sang `<file>.cfbak` TRUOC khi chen, va lan chay
sau khoi dong bang phuc lai moi `.cfbak` con sot roi xoa chung.

```bash
python scratch/transform_counterfactual.py [so_phep_thu_dau] [so_thu_nhat]
```
Toan bo 19 vet ~2 phut (mot vet selftest ~2 s, mot vet report ~4 s, hai lan
chay tron bang ~40 s). KHONG chay hai ban sao cua probe nay song song: chung
ghi de byte len cung file nguon.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = "bien doi: xoay tu do + lat + canh le + khoa ty le"

FC = os.path.join(ROOT, "core", "frame_composer.py")
GCI = os.path.join(ROOT, "ui", "graphics_canvas_item.py")
PP = os.path.join(ROOT, "ui", "properties_panel.py")
CU = os.path.join(ROOT, "core", "canvas_utils.py")
PS = os.path.join(ROOT, "core", "project_storage.py")
DIAG = os.path.join(ROOT, "diagnostics.py")
# Tran cho MOI lan goi production. Tron bang `--selftest` do 63,2-71,3 s (may
# nghi, 23/10/2026), mot vet ~2 s, `--transform-report` ~4 s. 420 s bang ~6 lan
# do dai lon nhat da do: bai hoc cua `frozen_bundle_probe.py` la mot lan chay
# keo 404 s chi vi may khong nghi, nen tran vua phai dung cho HDD tranh chan,
# vua phai NGAT duoc (xem `_child`).
CHILD_TIMEOUT = 420

# (ten, oracle, file, needle, repl, mong_doi_nao_do)
MUTATIONS = [
    ("export_bo_lat", "report", FC,
     b'        fx = -1.0 if getattr(clip.transform, "flip_h", False) else 1.0\n',
     b"        fx = 1.0  # CU: xuat bo qua lat ngang\n",
     "lat ngang dao hai nua mau"),
    ("preview_bo_lat", "report", GCI,
     b'            fx = -1.0 if getattr(self.clip_model.transform, "flip_h", '
     b'False) else 1.0\n',
     b"            fx = 1.0  # CU: preview bo qua lat ngang\n",
     "xem truoc cung mat voi xuat sau lat"),
    ("export_bo_xoay", "report", FC,
     b"        painter.rotate(rot + anim.rotation)\n",
     b"        painter.rotate(0.0)  # CU: xuat khong xoay\n",
     "xoay 90 dao rong cao"),
    ("canh_khong_theo_hop_xoay", "selftest", PP,
     b"        box_w, box_h = rotated_box_size(base_w * transform.scale_x,\n"
     b"                                        base_h * transform.scale_y,\n"
     b"                                        transform.rotation)\n",
     b"        box_w, box_h = rotated_box_size(base_w * transform.scale_x,\n"
     b"                                        base_h * transform.scale_y,\n"
     b"                                        0.0)  # CU: canh theo rect chua xoay\n",
     "canh trai khi xoay 90 ra x="),
    ("align_start_tra_0", "selftest", CU,
     b"        return -half + box_size / 2.0\n",
     b"        return 0.0  # CU\n",
     "canh mep sai"),
    ("rotated_box_khong_dao_truc", "selftest", CU,
     b"    return box_w * c + box_h * s, box_w * s + box_h * c\n",
     b"    return box_w, box_h  # CU\n",
     "xoay 90 khong dao truc"),
    ("normalize_khong_goi", "selftest", GCI,
     b"    return a - 360.0 if a > 180.0 else a\n",
     b"    return a  # CU: de goc 270 song nguyen\n",
     "_normalize_angle tra goc ngoai"),
    ("bounding_an_room", "selftest", GCI,
     b"        return bounding.adjusted(-margin, -margin - ROTATE_ROOM, margin,"
     b" margin)\n",
     b"        return bounding.adjusted(-margin, -margin, margin, margin)  # CU\n",
     "boundingRect thieu ROTATE_ROOM"),
    ("hit_test_rotate_gia", "selftest", GCI,
     b"        pt = self._rotate_handle_pos()\n"
     b"        return QRectF(pt.x() - ROTATE_HIT, pt.y() - ROTATE_HIT,\n"
     b"                      ROTATE_HIT * 2, ROTATE_HIT * 2).contains(pos)\n",
     b"        return False  # CU: tay nam khong bao gio bam duoc\n",
     "keo tay nam +45 do ra goc"),
    ("luu_mat_co", "selftest", PS,
     b'        "flip_h": bool(getattr(transform, "flip_h", False)),\n',
     b'        "flip_h": False,  # CU: khong ghi co\n',
     "luu mo lech"),
    ("doc_legacy_gan_co", "selftest", PS,
     b'    transform.flip_h = bool(data.get("flip_h", False))\n',
     b'    transform.flip_h = bool(data.get("flip_h", True))  # CU\n',
     "file cu bi gan co la"),
    ("pct_chi_ghi_mot_truc", "selftest", PP,
     b"        self.spin_scale_y.setValue(factor)\n",
     b"        pass  # CU: khong ghi truc Y\n",
     "hai truc phai bang nhau"),
    ("khoa_dong_van_nhap_duoc", "selftest", PP,
     b"        self.spin_scale_x.setEnabled(not locked)\n"
     b"        self.spin_scale_y.setEnabled(not locked)\n",
     b"        self.spin_scale_x.setEnabled(True)  # CU\n"
     b"        self.spin_scale_y.setEnabled(True)  # CU\n",
     "khoa dong ma van cho nhap tung truc"),
    ("reset_giu_goc", "selftest", PP,
     b'                  "rotation": 0.0, "flip_h": False, "flip_v": False,\n',
     b'                  "flip_h": False, "flip_v": False,\n',
     "Dat lai con sot"),
    ("nut_lat_khong_push", "selftest", PP,
     b"        requested = {key: bool(value) for key, value in changes.items()\n"
     b"                     if bool(getattr(transform, key, False)) != bool(value)}\n"
     b"        if not requested:\n",
     b"        requested = {key: bool(value) for key, value in changes.items()\n"
     b"                     if bool(getattr(transform, key, False)) != bool(value)}\n"
     b"        if True:  # CU: khong bao gio push\n",
     "khong ghi co len model"),
    ("thang_do_dem_sau_nut", "selftest", DIAG,
     b"TRANSFORM_BUTTON_COUNT = 12   # dat lai + dong nhat + 2 xoay + 2 lat +"
     b" 6 canh\n",
     b"TRANSFORM_BUTTON_COUNT = 11   # CU: thang do dem thieu mot nut\n",
     "thang do ghi 11"),
    ("fixture_trang_don", "report", DIAG,
     b"            quad.fillRect(0, 0, 160, 90, QColor(230, 30, 40))"
     b"      # trai tren\n",
     b"            quad.fillRect(0, 0, 160, 90, QColor(235, 235, 235))  # CU\n",
     "fixture lech mau bon goc"),
    ("align_end_tra_0", "report", CU,
     b"        return half - box_size / 2.0\n",
     b"        return 0.0  # CU\n",
     "canh phai cham mep phai"),
    # 19. Tay nam xoay phai DOC RA la nut xoay: goi pixmap ve trong `paint` la
    # callback C++ cua Qt nen vet nay khong duoc phep lam no NOD (Exception
    # trong paint = ca process chet, do 23/10/2026). Do bang CAY SO:
    # `rotate_glyph_pixel_count` dem pixel toi trong duong kinh 11 don vi —
    # disc tran ~0, co glyph ~2000. Vet nay tra glyph ve pixmap rong.
    ("glyph_tay_nam_an_het", "selftest", GCI,
     b"            glyph = rotate_glyph_pixmap()\n",
     b"            glyph = QPixmap()  # CU: tay nam trang tron, khong con glyph\n",
     "tay nam xoay khong co glyph"),
]


def _read(report):
    with open(report, encoding="utf-8") as handle:
        return json.load(handle)


def _child(command, label):
    """Chay mot lenh production THAT, co tran.

    Tran o day KHONG phai de phong nghia ly. Lan chay 23/10/2026 (muc 4s duoi
    `docs/verification-gates.md`): lan SPOT chay tron bang `--selftest` voi vet
    `canh_khong_theo_hop_xoay` nam tren nguon khong tu ket thuc — tien trinh
    song hon 13 phut, CPU phang 8,20 s qua hai lan mau cach nhau 100 s, cua so
    'Clinging - Video Editor' van hien, payload khong ton tai. Khong co tran thi
    cha dung yen o do mai mai va lan chay khong bao gio in ra loi bao. Do lai
    lan 240 s sau do: control tron bang rc=0 71,3 s, vet nhu vay rc=1 63,2 s
    (KHONG tai hien) -> loi la `subprocess.run` thieu tran, khong phai doan ma
    vet thay.
    """
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SystemExit("PROBE DUNG: %s khong tu ket thuc trong %d s. Do la "
                         "dead-lock (CPU phang), khong phai do San pham; nguon "
                         "da duoc phuc lai byte trong finally."
                         % (label, CHILD_TIMEOUT))


def run_selftest(report, only=None):
    """Chạy `main.py --selftest` THAT, có hoặc không lọc lại đúng một dòng."""
    if os.path.exists(report):
        os.remove(report)
    cmd = [sys.executable, "main.py", "--selftest", report]
    label = "main.py --selftest " + (("--only=" + only) if only else "TRON BANG")
    if only:
        cmd.append("--only=" + only)
    proc = _child(cmd, label)
    payload = _read(report)
    if only:
        names = [r["name"] for r in payload["checks"]]
        if payload.get("only") != [only] or names != [ROW]:
            raise SystemExit("BUG: --only=%s khong loc dung mot dong (only=%r, "
                             "checks=%r)" % (only, payload.get("only"), names))
    row = next((r for r in payload["checks"] if r["name"] == ROW), None)
    return proc.returncode, payload, row


def run_report(report):
    """Chạy `main.py --transform-report` THAT va tra ve ten tung cua do."""
    if os.path.exists(report):
        os.remove(report)
    proc = _child([sys.executable, "main.py", "--transform-report", report],
                  "main.py --transform-report")
    payload = _read(report)
    return proc.returncode, payload


def restore_leftover_backups():
    restored = []
    for _, _, path, _, _, _ in MUTATIONS:
        bak = path + ".cfbak"
        if os.path.exists(bak):
            with open(bak, "rb") as handle:
                data = handle.read()
            with open(path, "wb") as handle:
                handle.write(data)
            os.remove(bak)
            restored.append(os.path.relpath(path, ROOT))
    return restored


def judge(oracle, report, expect):
    """(do_dung_cua, mo_ta) — do la ten cua trong payload, khong phai noi suy."""
    if oracle == "selftest":
        rc, payload, row = run_selftest(report, only=ROW)
        detail = row["detail"] if row else "khong co row"
        others = [r["name"] for r in payload["checks"]
                  if not r["ok"] and r["name"] != ROW]
        return (row is not None and not row["ok"] and expect in detail
                and not others), rc, detail[:140]
    rc, payload = run_report(report)
    failed = payload.get("failed", [])
    return expect in failed, rc, ", ".join(failed)[:140]


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    for name in restore_leftover_backups():
        print("phuc lai %s tu .cfbak (lan chay truoc bi cat giua chung)" % name)
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    subset = MUTATIONS[args[0]:args[1]] if args else MUTATIONS
    originals = {}
    for _, _, path, _, _, _ in subset:
        originals.setdefault(path, open(path, "rb").read())
    report = os.path.join(tempfile.gettempdir(),
                          "clinging_transform_cf_%d.json" % os.getpid())
    results = []
    try:
        for name, oracle, path, needle, repl, expect in subset:
            if originals[path].count(needle) != 1:
                print("BUG: vet cua %s xuat hien %d lan trong %s, can 1" %
                      (name, originals[path].count(needle),
                       os.path.relpath(path, ROOT)))
                return 2
            shutil.copyfile(path, path + ".cfbak")
            with open(path, "wb") as handle:
                handle.write(originals[path].replace(needle, repl, 1))
            try:
                ok, rc, detail = judge(oracle, report, expect)
            finally:
                with open(path, "wb") as handle:
                    handle.write(originals[path])
                if os.path.exists(path + ".cfbak"):
                    os.remove(path + ".cfbak")
            results.append((name, ok))
            print("%-26s %-8s %s  rc=%d  do: %s" %
                  (name, oracle, "PHAN BIET" if ok else "KHONG PHAN BIET",
                   rc, detail))
    finally:
        for path, data in originals.items():
            with open(path, "wb") as handle:
                handle.write(data)

    # Mot vet do tren TRON bang selftest de chot rang no khong keo theo dong
    # khac (lan chay 14/10 cua nhom khac: vet dung mot dong lam do hai dong).
    spot_ok, nfull = False, 0
    spot = next(((n, o, p, nd, rp, ex) for n, o, p, nd, rp, ex in subset
                 if o == "selftest"), None)
    if spot:
        s_name, _s_oracle, s_path, s_needle, s_repl, s_expect = spot
        shutil.copyfile(s_path, s_path + ".cfbak")
        try:
            with open(s_path, "wb") as handle:
                handle.write(originals[s_path].replace(s_needle, s_repl, 1))
            s_rc, s_payload, s_row = run_selftest(report)
        finally:
            with open(s_path, "wb") as handle:
                handle.write(originals[s_path])
            if os.path.exists(s_path + ".cfbak"):
                os.remove(s_path + ".cfbak")
        nfull = len(s_payload["checks"]) if s_payload else 0
        s_failed = s_payload["failed"] if s_payload else []
        spot_ok = (s_rc == 1 and s_row is not None and not s_row["ok"]
                   and s_expect in s_row["detail"] and s_failed == [ROW]
                   and s_payload.get("only") is None)
        print("%-26s %-8s %s  rc=%d  rows=%d failed=%s  (vet %s, tron bang)" %
              ("spot_tron_bang", "selftest", "PASS" if spot_ok else "FAIL",
               s_rc, nfull, s_failed, s_name))

    rc, payload, row = run_selftest(report)
    green = (rc == 0 and row is not None and row["ok"] and payload
             and not payload["failed"] and payload.get("only") is None
             and nfull in (0, len(payload["checks"])))
    r_rc, r_payload = run_report(report)
    green_report = (r_rc == 0 and not r_payload.get("failed")
                    and r_payload.get("ok"))
    if os.path.exists(report):
        os.remove(report)
    print("%-26s %-8s %s  rc=%d  rows=%d failed=%s" %
          ("khoi_phuc_xanh", "selftest", "PASS" if green else "FAIL", rc,
           len(payload["checks"]), payload["failed"]))
    print("%-26s %-8s %s  rc=%d  failed=%s" %
          ("khoi_phuc_xanh", "report", "PASS" if green_report else "FAIL", r_rc,
           r_payload.get("failed")))
    bad = [n for n, ok in results if not ok]
    if not spot_ok:
        bad.append("spot_tron_bang")
    if not green or not green_report:
        bad.append("khoi_phuc")
    print("ALL PASS" if not bad else "CO %d KET QUA FAIL: %s"
          % (len(bad), ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
