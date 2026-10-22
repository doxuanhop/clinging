r"""Phan chung cho gate "chinh mau" (diagnostics._color_grading_ok).

Sau khi da xac nhan gate XANH, moi phep doi byte mot cho trong 4 file nguon PHAI
lam CUA CHINH MAU do vi DUNG ly do cua chinh phep do — khong phai do crash va
khong phai do mot cua khac trong same selftest. 13 phep o day tach rieng 13 xich
ma: phep xoay hue, tung banh xe lift/gamma/gain, thu tu kenh cua bo 3D, nhanh 1D,
khoa cache .cube, hai seam cua panel, hai luat gom cua lenh undo, phep boc the
trung tinh, duong tat 0 do, va tap khoa GRADING_KEYS/PIXEL_KEYS.

13 vet chay `main.py --selftest --only=chinh mau` (1 dong, ~6 s) thay vi tron 38
dong (~31 s), kem MOT vet chay lai tren TRON bang de chot "khong keo theo dong
khac"; do 22/10/2026, chay tron 13 lan la ~7 phut ngan HDD va treo ca may.

Chay:
    python scratch/color_grading_counterfactual.py

Tat ca 13 phep phai DO cho dung ly do, byte nguon tra ve nguyen ban, lan cuoi
phai XANH lai toan bang. Ghi/phuc hoi bang BYTES (write_text o may nay doi LF
thanh CRLF).
"""

import glob
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CE = os.path.join(ROOT, "core", "clip_effects.py")
LT = os.path.join(ROOT, "core", "lut.py")
CM = os.path.join(ROOT, "core", "commands.py")
PP = os.path.join(ROOT, "ui", "properties_panel.py")

GATE = "chinh mau"
REPORT = os.path.join(tempfile.gettempdir(), "clinging_selftest.json")


def L(*lines):
    """Noi cac dong bang LF that: ca 4 file nguon deu LF, khong CRLF."""
    return b"\n".join(lines)


MERGE_DEAD = L(
    b'    def merges_with(self, other: "Command") -> bool:',
    b'        if not isinstance(other, SetGradingCommand):',
    b'            return False',
    b'        if other._clip_id != self._clip_id:',
    b'            return False',
    b'        keys = set(self._requested)',
    b'        if keys != set(other._requested) or not keys:',
    b'            return False',
    b'        return other._at - self._at <= self.MERGE_WINDOW_S')

# (mo ta, [(duong dan, old_bytes, new_bytes, so_lan)], ly_do_cua_expected)
MUTATIONS = [
    ("chuoi loc mau khong con nhanh hue -> the Chinh mau ve ra khong xoay mau",
     [(CE, b'        if "hue_shift" in params:',
       b'        if False and "hue_shift" in params:', 1)],
     "chuoi loc bo qua hue_shift"),
    ("gamma bi dao nguoc mu (x**g thay vi x**(1/g))",
     [(CE, b"    x = np.power(x, 1.0 / g) * gain", b"    x = np.power(x, g) * gain", 1)],
     "gamma 1.6 khong bentre midtone"),
    ("lift tro thanh cong do sang toan anh (brightness gia trang)",
     [(CE, b"    x = x + lift * (1.0 - x)", b"    x = x + lift", 1)],
     "lift 0.25 cham ca vung sang"),
    ("0 do van chay ma tran quay: duong tat cho may cau hinh thap bi vo",
     [(CE, b"    if abs(a) < 1e-9:", b"    if abs(a) < 0:", 1)],
     "hue 0 do van chay ma tran"),
    ("khoa GRADING_KEYS bi tron vao PIXEL_KEYS -> cua the ma mat nghia che do",
     [(CE, b'GRADING_KEYS = ("hue_shift", "lift", "gamma", "gain", "lut_path")',
       b'GRADING_KEYS = ("hue_shift", "lift", "gamma", "gain", "lut_path", "brightness")', 1)],
     "GRADING_KEYS trung PIXEL_KEYS"),
    ("bo 3D doc theo thu tu kenh nguoc (loang giong do nhanh nhat)",
     [(LT, b"    ri, gi, bi = (lo[:, :, i] for i in range(3))",
       b"    gi, bi, ri = (lo[:, :, i] for i in range(3))", 1)],
     "LUT identity lech"),
    ("nhanh LUT 1D bi tra nguyen anh (con goi nhung khong ap)",
     [(LT, b"            out[:, :, ch] = _interp_1d(x[:, :, ch], table[:, ch])",
       b"            out[:, :, ch] = x[:, :, ch]", 1)],
     "LUT 1D khong duoc ap"),
    ("cache LUT chi khoa theo duong dan -> sua file tai cho khong nap lai",
     [(LT, b"        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)",
       b"        key = (os.path.abspath(path),)", 1)],
     "LUT bi thay noi dung van dung ban cu trong cache"),
    ("panel khong doc lai bo so khi doi clip / khi UndoStack doi (seam)",
     # `the Cat` (9ed6125) chen `_sync_trim_card()` vao giua hai dong nay, nen
     # mau 2 dong o day tung im lang xuat hien 0 lan — vet phai theo chuoi 3 dong.
     [(PP, L(b"        self._sync_audio_card()", b"        self._sync_trim_card()",
             b"        self._sync_grading_card()"),
       L(b"        self._sync_audio_card()", b"        self._sync_trim_card()"), 1)],
     "update_values thieu _sync_grading_card"),
    ("panel ghi vao clip bang loi khac, khong qua SetGradingCommand (seam)",
     [(PP, b"        from core.commands import SetGradingCommand",
       b"        from core.commands import SetTransitionCommand as SetGradingCommand", 1)],
     "_push_grading thieu SetGradingCommand"),
    ("lenh chinh mau ngung gom keo: 4 nac gamma = 4 buoc undo",
     [(CM, MERGE_DEAD, MERGE_DEAD.replace(
         b"        return other._at - self._at <= self.MERGE_WINDOW_S",
         b"        return False"), 1)],
     "keo 4 nac gamma thanh"),
    ("lenh chinh mau gom moi thu: quay hue bi hap vao buoc gamma",
     # Khong dung mau 4 dong thuan: doan `keys = set(...)` ay xuat hien 2 lan
     # trong commands.py sau khi SetChromaCommand ra doi — vet phai gan voi `isinstance(other, SetGradingCommand)` moi doc
     # dung lenh cua chinh mau.
     [(CM, MERGE_DEAD, MERGE_DEAD.replace(
         b"        if keys != set(other._requested) or not keys:",
         b"        if not keys:"), 1)],
     "num khac khoa bi gom chung"),
    ("the trung tinh khong bi boc: clip giu bo so khong lam doi gi dung numpy",
     [(CM, b"        if grading_is_identity(merged):",
       b"        if grading_is_identity(merged) and False:", 1)],
     "tha het ve trung tinh ma the chinh mau van con"),
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

    `only=True` them `--only=chinh mau`: 13 vet keu nhau, moi vet chay tron 38
    dong la ~31 s (karaoke/pop art/nen tep cung ma hoa that) = ~7 phut ngan HDD
    va treo ca may. Van di qua dung lenh production, van co QApplication + rc
    that. Bo loc co gate rieng: `scratch/selftest_filter_counterfactual.py`.

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
        cmd.append("--only=" + GATE)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8")
    if not os.path.exists(REPORT):
        return False, "khong co bao cao: process chet truoc khi ghi (rc=%s)" % r.returncode, None
    with open(REPORT, encoding="utf-8") as f:
        d = json.load(f)
    if only and (d.get("only") != [GATE] or len(d["checks"]) != 1):
        # Lan chay loc PHAI la lan loc, neu khong `failed=[]` mang nghia khac.
        raise AssertionError("--only=%s khong loc dung mot dong (only=%r, "
                             "checks=%d)" % (GATE, d.get("only"), len(d["checks"])))
    rows = [c for c in d["checks"] if GATE in c["name"]]
    if len(rows) != 1:
        return False, "bao cao co %d dong chua 'chinh mau' (rc=%s, checks=%d)" % (
            len(rows), r.returncode, len(d.get("checks", []))), d
    return rows[0]["ok"], rows[0].get("detail", ""), d


def main():
    paths = sorted({m for _, edits, _ in MUTATIONS for (m, _, _, _) in edits})
    original = snapshot(paths)
    failures = []
    nfull = 0
    try:
        ok, detail, d = run_gate_row(paths, only=False)
        if not ok:
            raise AssertionError("baseline phai XANH truoc khi do, ma: %s" % detail)
        nfull = len(d["checks"])
        print("baseline: XANH du %d dong, dong chinh mau: %s"
              % (nfull, detail[:80]))

        for desc, edits, expect in MUTATIONS:
            try:
                for (path, old, new, count) in edits:
                    data = open(path, "rb").read()
                    if data.count(old) != count:
                        raise AssertionError(
                            "mau byte xuat hien %d lan o %s (can dung %d): %r"
                            % (data.count(old), path, count, old[:60]))
                    open(path, "wb").write(data.replace(old, new, count))
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

        # 13/13 lan chay loc noi "do vi DUNG ly do cua no" nhung khong the noi
        # "khong keo theo dong khac", vi 37 dong kia khong chay. Vet dau tien do
        # lai tren TRON bang — mot lan, thay vi 13.
        desc, edits, expect = MUTATIONS[0]
        for (path, old, new, count) in edits:
            data = open(path, "rb").read()
            if data.count(old) != count:
                raise AssertionError("spot: mau byte lech o %s" % path)
            open(path, "wb").write(data.replace(old, new, count))
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
