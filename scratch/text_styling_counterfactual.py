r"""Phan chung cho gate "style chu" (diagnostics._text_styling_ok).

Sau khi da xac nhan gate XANH, moi phep doi byte mot cho trong 4 file nguon PHAI
lam CUA STYLE CHU do vi DUNG ly do cua chinh phep do — khong phai do crash. Cac
phep chi doi duong ve (rout toi/bo composite) hoac bo cat gia tri, khong lam
text_style_of/`_paint_styled` bat exception trong paintEvent cua cua so khac: o
may nay exception qua bien C++ cua Qt giet ca process (0xC0000409), stdout mat
sach va bao cao KHONG duoc ghi — nen harness phai doc rc that va khong duoc tin
bao cao cu.

Chay:
    python scratch/text_styling_counterfactual.py

Tat ca 6 phep phai DO cho dung ly do, byte nguon tra ve nguyen ban, lan cuoi
phai XANH lai toan bang. Ghi/phuc hoi bang BYTES (write_text o may nay doi LF
thanh CRLF).

Tung vet chay `--selftest <json> --only=<dong do>` (~5 s) thay vi tron bang
(~31 s): 6 vet xuong con ~1 phut. `--only` chi cat buoc in an cua 37 dong khac,
khong cat duong do cua dong dang chay. Vet DAU TIEN do lai mot lan tren TRON
bang de giu chat "do mot minh no, khong keo theo dong khac".
"""

import glob
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TP = os.path.join(ROOT, "core", "text_paint.py")
FC = os.path.join(ROOT, "core", "frame_composer.py")
GC = os.path.join(ROOT, "ui", "graphics_canvas_item.py")
PS = os.path.join(ROOT, "core", "project_storage.py")

GATE = "style chu"
ROW = "style chu: vien/bong/hop nen/can le"
REPORT = os.path.join(tempfile.gettempdir(), "clinging_selftest.json")

# (mo ta, [(duong dan, old_bytes, new_bytes, so_lan)], ly_do_cua_expected)
MUTATIONS = [
    ("goi composite bi tat: vien/bong/hop ro ra chu thuong",
     [(TP, b"    if _styling_active(styling):",
       b"    if False and _styling_active(styling):", 1)],
     "vien ve giong chu thuong"),
    ("export khong con truyen styling cho seam",
     [(FC, b"            styling=text_style_of(clip),", b"            styling=None,", 1)],
     "export bo qua style chu hop nen"),
    ("preview bo ca import lan goi text_style_of -> seam do",
     [(GC, b"        from core.text_paint import clip_font, paint_animated_text, text_style_of",
       b"        from core.text_paint import clip_font, paint_animated_text", 1),
      (GC, b"            styling=text_style_of(clip),", b"            styling=None,", 1)],
     "seam style chu thieu"),
    ("luu du an doi khoa text_box_alpha -> khong doc lai duoc",
     # Ca `save_project_to_file` (dong 299) lan `save_project` autosave (dong 620)
     # deu ghi khoa nay; doi mot con thi cua doc tu con kia van du dung.
     [(PS, b'                "text_box_alpha": getattr(clip, "text_box_alpha", 0.0),',
       b'                "text_box_alpha_DROP": getattr(clip, "text_box_alpha", 0.0),', 2)],
     "style chu mat khi quay qua file"),
    ("text_style_of khong chuan hoa so ve float (giu nguyen int)",
     [(TP, b"        out[key] = float(value) if key in _NUMBER_STYLING else value",
       b"        out[key] = value if key in _NUMBER_STYLING else value", 1)],
     "text_style_of khong chuan hoa so ve float"),
    ("nhanh do duong ve truc tiep bi ep ve center -> can le mat nghia",
     [(TP, b"            painter.drawText(rect, _align_of(align), line)",
       b"            painter.drawText(rect, _align_of(\"center\"), line)", 1)],
     "can le khong dich vi tri chu"),
]


def snapshot(paths):
    return {p: open(p, "rb").read() for p in paths}


def restore(snap):
    for p, data in snap.items():
        with open(p, "wb") as f:
            f.write(data)


def drop_pycache(paths):
    """Xoa .pyc cua module bi doi byte: mtime do den phat giay nen phep doi byte
    trong cung giay voi lan chay truoc se dung lai bytecode cu, doan da sua bi bo
    qua va cua xanh gia. Xoa .pyc buoc dich lai tu nguon."""
    for path in paths:
        mod = os.path.splitext(os.path.basename(path))[0]
        folder = os.path.join(os.path.dirname(path), "__pycache__")
        for pyc in glob.glob(os.path.join(folder, "%s.cpython-*.pyc" % mod)):
            try:
                os.remove(pyc)
            except OSError:
                pass


def run_gate_row(paths, only=True):
    """Chay --selftest tren dung duong production va tra ve (ok, detail, payload).

    `only=True` them `--only=<dong do>` (~5 s thay vi ~31 s cho tron bang). Van
    di qua dung lenh nguoi dung goi, van co QApplication + rc that. Bo loc co
    gate rieng: `scratch/selftest_filter_counterfactual.py`.

    Bao cao bi XOA truoc khi chay: mot process chet crash (0xC0000409) khong ghi
    bao cao, va neu doc file cu thi cua do bi hien thi thanh XAN gia. Thieu bao
    cao sau khi chay = crash, khong phai pass. rc lay tu chinh subprocess.run."""
    drop_pycache(paths)
    try:
        os.remove(REPORT)
    except OSError:
        pass
    cmd = [sys.executable, "main.py", "--selftest", REPORT]
    if only:
        cmd.append("--only=" + ROW)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not os.path.exists(REPORT):
        return (False, "khong co bao cao: process chet truoc khi ghi (rc=%s)"
                % r.returncode, None)
    with open(REPORT, encoding="utf-8") as f:
        d = json.load(f)
    if only and (d.get("only") != [ROW] or len(d["checks"]) != 1):
        # Lan chay loc PHAI la lan loc, neu khong `failed=[]` mang nghia khac.
        raise AssertionError("--only=%s khong loc dung mot dong (only=%r, "
                             "checks=%d)" % (ROW, d.get("only"), len(d["checks"])))
    rows = [c for c in d["checks"] if GATE in c["name"]]
    if len(rows) != 1:
        return (False, "bao cao co %d dong chua 'style chu' (rc=%s, checks=%d)"
                % (len(rows), r.returncode, len(d.get("checks", []))), d)
    return rows[0]["ok"], rows[0].get("detail", ""), d


def apply_mutation(edits):
    for (path, old, new, count) in edits:
        data = open(path, "rb").read()
        if data.count(old) != count:
            raise AssertionError(
                "mau byte xuat hien %d lan o %s (can dung %d): %r"
                % (data.count(old), path, count, old[:60]))
        open(path, "wb").write(data.replace(old, new, count))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    paths = sorted({m for _, edits, _ in MUTATIONS for (m, _, _, _) in edits})
    original = snapshot(paths)
    failures = []
    nfull = 0
    try:
        ok, detail, d = run_gate_row(paths, only=False)
        if not ok or d.get("only") is not None:
            raise AssertionError("baseline phai XANH du bang truoc khi do, ma: %s"
                                 % detail)
        nfull = len(d["checks"])
        print("baseline: XANH du %d dong, dong style chu: %s"
              % (nfull, detail[:80]))

        for desc, edits, expect in MUTATIONS:
            try:
                apply_mutation(edits)
                ok, detail, _ = run_gate_row(paths)
                if ok:
                    failures.append("%s -> gate VAN XANH (phan chung that bai)" % desc)
                elif expect not in detail:
                    failures.append("%s -> DO nhung SAI ly do: %s" % (desc, detail[:140]))
                else:
                    print("  RED dung ly do [%s]" % desc)
                    print("        %s" % detail[:110])
            finally:
                restore(original)

        # 6/6 lan chay loc noi "do vi DUNG ly do cua no" nhung khong the noi
        # "khong keo theo dong khac", vi 37 dong kia khong chay. Vet dau tien do
        # lai tren TRON bang — mot lan, thay vi 6.
        desc, edits, expect = MUTATIONS[0]
        apply_mutation(edits)
        try:
            ok, detail, d = run_gate_row(paths, only=False)
        finally:
            restore(original)
        failed = d["failed"] if d else ["khong co bao cao"]
        if (ok or expect not in detail or len(failed) != 1
                or GATE not in failed[0] or len(d["checks"]) != nfull
                or d.get("only") is not None):
            failures.append("spot_tron_bang -> ok=%s failed=%s (%s)"
                            % (ok, failed, detail[:90]))
        else:
            print("  SPOT tron %d dong: do DUNG MOT cua [%s] failed=%s"
                  % (nfull, desc, failed))

        ok, detail, d = run_gate_row(paths, only=False)
        if not ok or (d and d["failed"]) or len(d["checks"]) != nfull:
            raise AssertionError("sau phuc hoi gate van do: %s" % detail)
        print("phuc hoi: XANH lai du %d dong" % nfull)
    finally:
        restore(original)
        for path in paths:
            assert open(path, "rb").read() == original[path], "byte khong phuc hoi: %s" % path
        print("byte nguon da tra ve nguyen ban (%d file)" % len(paths))

    if failures:
        print("\nFAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nALL PASS: %d phan chung, moi cua do vi dung ly do" % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
