r"""Phan chung cho gate "chinh mau" (diagnostics._color_grading_ok).

Sau khi da xac nhan gate XANH, moi phep doi byte mot cho trong 4 file nguon PHAI
lam CUA CHINH MAU do vi DUNG ly do cua chinh phep do — khong phai do crash va
khong phai do mot cua khac trong same selftest. 13 phep o day tach rieng 13 xich
ma: phep xoay hue, tung banh xe lift/gamma/gain, thu tu kenh cua bo 3D, nhanh 1D,
khoa cache .cube, hai seam cua panel, hai luat gom cua lenh undo, phep boc the
trung tinh, duong tat 0 do, va tap khoa GRADING_KEYS/PIXEL_KEYS.

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


MERGE_BLOCK = L(
    b'        keys = set(self._requested)',
    b'        if keys != set(other._requested) or not keys:',
    b'            return False',
    b'        return other._at - self._at <= self.MERGE_WINDOW_S')
MERGE_BLOCK_FALSE = L(
    b'        keys = set(self._requested)',
    b'        if not keys:',
    b'            return False',
    b'        return other._at - self._at <= self.MERGE_WINDOW_S')
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
     [(PP, L(b"        self._sync_audio_card()", b"        self._sync_grading_card()"),
       b"        self._sync_audio_card()", 1)],
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
     [(CM, MERGE_BLOCK, MERGE_BLOCK_FALSE, 1)],
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


def run_gate_row(paths):
    """Chay --selftest tren dung duong production va tra ve dong chinh mau.

    Bao cao bi XOA truoc khi chay: mot process chet crash (0xC0000409) khong ghi
    bao cao, va neu doc file cu thi cua do bi hien thi thanh XAN gia. Thieu bao
    cao sau khi chay = crash, khong phai pass. rc lay tu chinh subprocess.run."""
    drop_pycache(paths)
    try:
        os.remove(REPORT)
    except OSError:
        pass
    r = subprocess.run([sys.executable, "main.py", "--selftest"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if not os.path.exists(REPORT):
        return False, "khong co bao cao: process chet truoc khi ghi (rc=%s)" % r.returncode
    with open(REPORT, encoding="utf-8") as f:
        d = json.load(f)
    rows = [c for c in d["checks"] if GATE in c["name"]]
    if len(rows) != 1:
        return False, "bao cao co %d dong chua 'chinh mau' (rc=%s, checks=%d)" % (
            len(rows), r.returncode, len(d.get("checks", [])))
    return rows[0]["ok"], rows[0].get("detail", "")


def main():
    paths = sorted({m for _, edits, _ in MUTATIONS for (m, _, _, _) in edits})
    original = snapshot(paths)
    failures = []
    try:
        ok, detail = run_gate_row(paths)
        if not ok:
            raise AssertionError("baseline phai XANH truoc khi do, ma: %s" % detail)
        print("baseline: dong chinh mau XANH")

        for desc, edits, expect in MUTATIONS:
            try:
                for (path, old, new, count) in edits:
                    data = open(path, "rb").read()
                    if data.count(old) != count:
                        raise AssertionError(
                            "mau byte xuat hien %d lan o %s (can dung %d): %r"
                            % (data.count(old), path, count, old[:60]))
                    open(path, "wb").write(data.replace(old, new, count))
                ok, detail = run_gate_row(paths)
                if ok:
                    failures.append("%s -> gate VAN XANH (phan chung that bai)" % desc)
                elif expect not in detail:
                    failures.append("%s -> DO nhung SAI ly do: %s" % (desc, detail[:140]))
                else:
                    print("  RED dung ly do [%s]" % desc)
                    print("        %s" % detail[:110])
            finally:
                restore(original)

        ok, detail = run_gate_row(paths)
        if not ok:
            raise AssertionError("sau phuc hoi gate van do: %s" % detail)
        print("phuc hoi: dong chinh mau XANH lai")
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
