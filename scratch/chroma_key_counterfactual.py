r"""Phan chung cho gate "duc nen chroma key" (diagnostics._chroma_key_ok).

Sau khi da xac nhan gate XANH, moi phep doi byte mot cho trong 4 file nguon PHAI
lam CUA CHROMA do vi DUNG ly do cua chinh phep do — khong phai do crash, khong
phai do mot cua khac trong same selftest, va khong phai do cua "chinh mau" (hai
num nay di tren cung mot chuoi loc nen phep doi byte hom nay co the va cham ca
hai; bao cao doi HOI dung MOT dong chua tu "chroma").

19 phep tach rieng 19 xich ma: nguong bao hoa, do rong cua num dung sai, do
mong cua num vien mem (hai chieu: span=0 va span am), ba luat cua despill,
matte dao nguoc, pre-pass bi tat, duong tat cho may cau hinh thap, mau sac rac
trong file .clinq, tap khoa CHROMA_KEYS, hai luat gom cua lenh undo, phep boc
the trung tinh, hai seam cua panel, mot preset dan khoa chroma vao bo loc, va
HAI chieu cua canh thu nho matte ( tat canh = thieu chi phi 54 ms/frame; plate
qua ran = an chu the).

Chay:
    python scratch/chroma_key_counterfactual.py

Tat ca 17 phep phai DO cho dung ly do, byte nguon tra ve nguyen ban, lan cuoi
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
CM = os.path.join(ROOT, "core", "commands.py")
PP = os.path.join(ROOT, "ui", "properties_panel.py")
TM = os.path.join(ROOT, "core", "timeline_model.py")

GATE = "chroma"
REPORT = os.path.join(tempfile.gettempdir(), "clinging_selftest.json")


def L(*lines):
    """Noi cac dong bang LF that: ca 4 file nguon deu LF, khong CRLF."""
    return b"\n".join(lines)


CHROMA_MERGE = L(
    b'    def merges_with(self, other: "Command") -> bool:',
    b'        if not isinstance(other, SetChromaCommand):',
    b'            return False',
    b'        if other._clip_id != self._clip_id:',
    b'            return False',
    b'        keys = set(self._requested)',
    b'        if keys != set(other._requested) or not keys:',
    b'            return False',
    b'        return other._at - self._at <= self.MERGE_WINDOW_S')
CHROMA_MERGE_NO_KEY = L(
    b'    def merges_with(self, other: "Command") -> bool:',
    b'        if not isinstance(other, SetChromaCommand):',
    b'            return False',
    b'        if other._clip_id != self._clip_id:',
    b'            return False',
    b'        keys = set(self._requested)',
    b'        if not keys:',
    b'            return False',
    b'        return other._at - self._at <= self.MERGE_WINDOW_S')

# (mo ta, [(duong dan, old_bytes, new_bytes, so_lan)], ly_do_cua_expected)
MUTATIONS = [
    ("nguong bao hoa bi ve 0 -> khoang cach hue an luon trang/xam/den",
     [(CE, b"CHROMA_MAG_FLOOR = 20.0", b"CHROMA_MAG_FLOOR = 0.0", 1)],
     "duc ca mau trung tinh"),
    ("num dung sai khong mo rong vong hue (span = 0 do)",
     [(CE, b"CHROMA_TOL_SPAN_DEG = 76.0", b"CHROMA_TOL_SPAN_DEG = 0.0", 1)],
     "0.15 khong mo vong toi la cay"),
    ("num vien mem bi noi dung (span = 0): bien luon mong bang goc",
     [(CE, b"CHROMA_SOFT_SPAN_DEG = 40.0", b"CHROMA_SOFT_SPAN_DEG = 0.0", 1)],
     "vien mem khong lam mong bien"),
    ("vien mem dao nguoc: keo num lam bien AM, nen khong bao gio bi cat",
     [(CE, b"                            * CHROMA_SOFT_SPAN_DEG",
       b"                            * -CHROMA_SOFT_SPAN_DEG", 1)],
     "mau cua chinh bo khoa van con"),
    ("nut chong ám tat: duyet spill thanh do",
     [(CE, b"    if spill > 1e-6:", b"    if False and spill > 1e-6:", 1)],
     "spill 0.8 khong keo kenh"),
    ("despill dong ca ba kenh thay vi chi kenh nong",
     [(CE, b"    dst += delta",
       L(b"    dst += delta",
         b"    for _ch in (0, 1, 2):",
         b"        if _ch != hot:",
         b"            out[:, :, _ch] += delta"), 1)],
     "spill dong luon kenh khac"),
    ("pre-pass chroma bi tat: khong he cat nen",
     [(CE, b'        if "tolerance" in params:',
       b'        if False and "tolerance" in params:', 1)],
     "nen con alpha"),
    ("matte dao nguoc: cat chu the, giu nen",
     [(CE, b"            alpha = alpha * matte[:, :, None]",
       b"            alpha = alpha * (1.0 - matte[:, :, None])", 1)],
     "bi duc o QImage that"),
    ("duong tat may cau hinh thap bi vo: the trung tinh van mo numpy",
     [(CE, b"    if not any(_opens_pixels(e) for e in effects):",
       L(b"    if not any(k in PIXEL_KEYS or k in GRADING_KEYS or k in CHROMA_KEYS",
         b'               for e in effects for k in (getattr(e, "params", None) or {})):'),
       1)],
     "the chroma trung tinh van chay chuoi loc"),
    ("mau sac doc khong duoc trong .clinq khong con duoc giu",
     [(CE, b"    if not color.isValid():", b"    if False:", 1)],
     "mau doc khong duoc"),
    ("khoa CHROMA_KEYS lan vao PIXEL_KEYS: mot the doi chuc nang",
     [(CE, b'CHROMA_KEYS = ("key_color", "tolerance", "feather", "spill")',
       b'CHROMA_KEYS = ("key_color", "tolerance", "feather", "spill", "brightness")', 1)],
     "CHROMA_KEYS trung khoa khac"),
    ("lenh chroma ngung gom keo: 4 nac dung sai = 4 buoc undo",
     [(CM, CHROMA_MERGE,
       CHROMA_MERGE.replace(b"        return other._at - self._at <= self.MERGE_WINDOW_S",
                            b"        return False"), 1)],
     "keo 4 nac dung sai thanh"),
    ("lenh chroma gom moi thu: doi mau nen bi hap vao buoc dung sai",
     [(CM, CHROMA_MERGE, CHROMA_MERGE_NO_KEY, 1)],
     "num khac khoa bi gom"),
    ("the trung tinh khong bi boc: clip giu the chroma rong, mo numpy moi frame",
     [(CM, b"        if chroma_is_identity(merged):",
       b"        if chroma_is_identity(merged) and False:", 1)],
     "tha het ve trung tinh ma the chroma van con"),
    ("panel khong doc lai bo so chroma khi doi clip (seam)",
     [(PP, L(b"        self._sync_grading_card()",
             b"        self._sync_chroma_card()"),
       b"        self._sync_grading_card()", 1)],
     "update_values thieu _sync_chroma_card"),
    ("panel ghi the chroma bang SetGradingCommand, khong qua lenh cua no (seam)",
     [(PP, b"        from core.commands import SetChromaCommand",
       b"        from core.commands import SetGradingCommand", 1),
      (PP, b"            SetChromaCommand(model, self.clip_id, requested))",
       b"            SetGradingCommand(model, self.clip_id, requested))", 1)],
     "_push_chroma thieu SetChromaCommand"),
    ("mot preset Bo loc dung khoa chroma: loc mau se duc nen luong bat",
     [(TM, b'    "Fade In":          {"fade_in": 1.0},',
       L(b'    "Chroma Test":      {"tolerance": 0.5},',
         b'    "Fade In":          {"fade_in": 1.0},'), 1)],
     "dung khoa chroma"),
    ("thu nho matte bi tat: do luong 54 ms/frame quay lai, may thap mat 30 fps",
     [(CE, b"    if long_side <= CHROMA_MATTE_MAX:",
       b"    if True:", 1)],
     "branch thu nho matte khong chay"),
    ("plate matte bi thu qua ran (10x6 thay vi 256): chu the bi tron vao nen",
     [(CE, b"    size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))",
       b"    size = (max(1, w // 64), max(1, h // 64))", 1)],
     "thu nho matte"),
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
    """Chay --selftest tren dung duong production va tra ve dong chroma.

    Bao cao bi XOA truoc khi chay: mot process chet crash (0xC0000409) khong ghi
    bao cao, va neu doc file cu thi cua do bi hien thi thanh XANH gia. Thieu bao
    cao sau khi chay = crash, khong phai pass. rc lay tu chinh subprocess.run.
    """
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
        return False, "bao cao co %d dong chua 'chroma' (rc=%s, checks=%d)" % (
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
        print("baseline: dong chroma XANH (%s)" % detail[:90])

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
                    failures.append("%s -> DO nhung SAI ly do: %s" % (desc, detail[:150]))
                else:
                    print("  RED dung ly do [%s]" % desc)
                    print("        %s" % detail[:110])
            finally:
                restore(original)

        ok, detail = run_gate_row(paths)
        if not ok:
            raise AssertionError("sau phuc hoi gate van do: %s" % detail)
        print("phuc hoi: dong chroma XANH lai")
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
