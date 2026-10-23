"""Phan chung cho cua `--sfx-report` va dong selftest "kho hieu ung am thanh sfx".

Tinh nang: kho 14 tieng SFX dung san trong app (`tools/make_sfx.py` →
`assets/sfx/`), hop thoai chen xuong timeline qua nut tren thanh thoi. Nam 23
dieu kien cua no (`diagnostics.SFX_REPORT_CHECKS`) nam trong bundle va trong ban
cai, nen chung phai co bang chung do DUOC vet, khong phai do ten. Hai lop nhu
`scratch/library_counterfactual.py`:

  A. Vet tung dau vao tren payload THAT do chinh lenh chay ra
     (`scratch/_sfx_report.json`, lan chay 22/10/2026 rc=0): 33 phep vet tren 23
     dieu kien, moi vet phai nop dung ten cua no, khong term nao lang cung, va
     mot bo vet ket hop phai do tron 23 ten.
  B. Doi byte nguon that (hop thoai, panel, thang do, manifest cua pack) roi
     chay LAI hai lenh ma nguoi dung/dev chay: `main.py --sfx-report` va
     `main.py --selftest --only=sfx`. Nam vet nay chung minh thang do bat DUOC
     loi san pham chu khong chi bat duoc payload sua tay.

Toan bo doi byte nam trong `main()` duoi canh `__main__`; phan tren chi la hang
so de `scratch/needle_canary.py` import dem mau byte (hop dong: canary KHONG
duoc phep doi byte nao).

Chay:  python -u scratch/sfx_counterfactual.py        (~2,5 phut, may phai yen)
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DIALOG = os.path.join(ROOT, "ui", "sfx_dialog.py")
PANEL = os.path.join(ROOT, "ui", "timeline_panel.py")
DIAG = os.path.join(ROOT, "diagnostics.py")
MANIFEST = os.path.join(ROOT, "assets", "sfx", "manifest.json")
PAYLOAD = os.path.join(ROOT, "scratch", "_sfx_report.json")
ROW_ONLY = "sfx"

import diagnostics as doc
sfx_report_fails = doc.sfx_report_fails

results = []


def check(name, got, want):
    results.append((name, got == want, got, want))


# ── A. Vet tung dau vao tren payload that ─────────────────────────────────
# (ten vet, {key: gia tri vet}, nhung cua PHAI do)
VETS = [
    # Cong gia: pack vang thi moi cua sau xanh vi khong co gi de do. `entry_count`
    # la mau so chung cua nam phep so sanh, nen no phai len ten ca nam.
    ("pack khong doc duoc manifest", {"entry_count": 0},
     ["doc duoc manifest", "pack du 14 tieng", "ffprobe do lai tung tieng",
      "14 tieng 14 hash", "hop thoai liet du pack", "loc nhom rut dung nhom",
      "tim kiem loc theo nhan"]),
    ("manifest khai thieu thiem mot tieng", {"entry_count": 13},
     ["pack du 14 tieng", "ffprobe do lai tung tieng", "14 tieng 14 hash",
      "hop thoai liet du pack"]),
    ("mot tieng bi mat tren dia", {"missing_files": ["wind"]},
     ["doc duoc manifest"]),
    ("byte tren dia lech manifest", {"byte_mismatches": ["pop"]},
     ["byte tren dia khop manifest"]),
    ("pack vuot ngan sach byte", {"pack_bytes": 250000},
     ["pack duoi ngan sach byte"]),
    ("pack am thanh vuot 20 s", {"pack_seconds": 25.0},
     ["tong thoi luong duoi ngan sach"]),
    ("manifest dung tran khac thang do", {"manifest_peak_ceiling": 0.98},
     ["manifest dung mot tran voi thang do"]),
    ("ffprobe khong do duoc tieng nao", {"probed_count": 0},
     ["ffprobe do lai tung tieng"]),
    ("ffprobe tra ve toan 0 s", {"min_probe_seconds": 0.0},
     ["ffprobe do lai tung tieng"]),
    ("do dai thuc lech manifest 0,5 s", {"duration_worst_dev": 0.5},
     ["ffprobe do lai tung tieng"]),
    ("khong tieng nao ra tieng (RMS 0)", {"rms_max": 0.0},
     ["RMS do lai khop manifest"]),
    ("RMS do lai lech manifest 0,05", {"rms_worst_dev": 0.05},
     ["RMS do lai khop manifest"]),
    ("mot tieng hoa mai vuot tran", {"peak_max": 0.97},
     ["peak duoi tran chong hoa mai"]),
    ("hai tieng trung het noi dung", {"distinct_hashes": 13},
     ["14 tieng 14 hash"]),
    ("14 tieng nghe giong het nhau", {"zcr_spread": 0.1},
     ["tieng khong giong het nhau"]),
    ("nut bi an khoi thanh thoi", {"button_visible": False},
     ["nut thanh mo duoc hop thoai"]),
    ("bam nut khong mo duoc hop thoai", {"dialog_opened": False},
     ["nut thanh mo duoc hop thoai"]),
    ("hop thoai liet thieu mot dong", {"dialog_rows": 13},
     ["hop thoai liet du pack"]),
    ("loc nhom rut sai so dong", {"group_rows": 5},
     ["loc nhom rut dung nhom"]),
    ("loc nhom khong cat gi", {"group_rows": 14},
     ["loc nhom rut dung nhom"]),
    ("tim kiem khong trach duong nao", {"search_rows": 0},
     ["tim kiem loc theo nhan"]),
    ("tim kiem dem sai so ket qua", {"search_rows": 4},
     ["tim kiem loc theo nhan"]),
    ("dung nghe thu van giu file mo", {"preview_source_cleared": False},
     ["nghe thu tha khoa file khi dung"]),
    # Vet nay sinh ra tu lan chay dau (22/10): `stop_preview()` tren mot player
    # CHUA tung phat thi `source()` rong san, nen phep thu "da tha khoa" xanh ma
    # khong do gi. Payload phai ghi ca hai ben: da MOI va da DONG.
    ("chua tung mo nguon khi nghe thu", {"preview_source_was_loaded": False},
     ["nghe thu tha khoa file khi dung"]),
    ("chen xong khong co clip", {"clip_count": 0},
     ["chen ra clip audio tren timeline"]),
    ("clip chen vao bi khai la video", {"clip_kinds": ["audio", "video"]},
     ["chen ra clip audio tren timeline"]),
    ("clip chen ra do dai 0", {"clip_durations_audible": False},
     ["chen ra clip audio tren timeline"]),
    ("hai tieng de chong nhau", {"overlap": 0.3},
     ["hai tieng noi lien khong chong"]),
    ("moi lan chen mot lane audio", {"audio_tracks": 2},
     ["chen tao mot lane audio"]),
    ("playhead dung yen sau khi chen", {"playhead_after": 0.0},
     ["playhead chay toi cuoi clip"]),
    ("Ctrl+Z khong xoa duoc clip", {"clips_after_undo": 2},
     ["Ctrl+Z tra ve timeline trong"]),
    ("probe ghi vao cache nguoi dung", {"user_cache_changed": True},
     ["khong ghi vao cache nguoi dung"]),
    ("man den thay vi cua so that", {"distinct_colors": 3},
     ["anh hop thoai ve co that"]),
    ("anh chung minh bi an",
     {"screenshot": os.path.join(ROOT, "scratch", "khong_ton_tai_sfx.png")},
     ["anh hop thoai ve co that"]),
]

# ── B. Vet tren nguon that, qua hai lenh production ───────────────────────
# (ten vet, duong dan file, mau cu, mau moi, nhung cua phai do)
# Khuon nam buoc de `needle_canary.py` dem duoc mau: item[1] la duong dan.
# Moi vet phai do dung ten cua no va KHONG do term nao khac — do la ly do
# `row` cung duoc ghi lai: vet nao khong lam do dong selftest thi phai noi ro
# vi sao (dong do khong cham toi cai nut).

# Ten cua duoc `SFX_REPORT_CHECKS` sinh ra tu chinh hang so bi vet
# (`"pack du %d tieng" % SFX_PACK_ENTRIES`), nên doi 14 -> 13 thì cửa đổi tên
# thành "pack du 13 tieng". Ghi ten bang chu la thi vet do dung ly do nhung
# probe doi ten la chim; tinh ten tu hang so goc thi ca hai chieu deu theo.
SCALE_RED_NAME = "pack du %d tieng" % (doc.SFX_PACK_ENTRIES - 1)

MUTATIONS = [
    ("hop thoai liet ke thieu tieng cuoi", DIALOG,
     "        for row in sfx_core.entries():\n",
     "        for row in sfx_core.entries()[:-1]:\n",
     ["hop thoai liet du pack"]),
    # Do 22/10 lan dau: vet nay khong chi tien `playhead` ma con doi lai CA HAI
    # cua — `TimelineModel.add_clip` (core/timeline_model.py:891) tu choi chen
    # deo lên clip đã có trên track audio không magnetic rồi gọi
    # `_create_collision_track()`, nên tiếng thứ hai sang lane kế bên.
    ("chen xong khong tien playhead", DIALOG,
     "    panel.model.playhead = start + float(clip.duration)\n",
     "",
     ["chen tao mot lane audio", "hai tieng noi lien khong chong",
      "playhead chay toi cuoi clip"]),
    ("dung nghe thu van giu nguon mo", DIALOG,
     "        self._player.setSource(QUrl())\n",
     "        pass  # vet: khong tha nguon\n",
     ["nghe thu tha khoa file khi dung"]),
    ("nut SFX khong duoc gan len thanh thoi", PANEL,
     "        layout.addWidget(self.btn_sfx)\n",
     "",
     ["nut thanh mo duoc hop thoai"]),
    ("thang do khai mot tieng it hon pack", DIAG,
     "SFX_PACK_ENTRIES = 14\n", "SFX_PACK_ENTRIES = 13\n",
     [SCALE_RED_NAME]),
    ("manifest khai sai byte cua mot tieng", MANIFEST,
     b'"bytes": 4432,', b'"bytes": 4433,',
     ["byte tren dia khop manifest"]),
]

# Vet thu tu (nut SFX khong nam tren thanh thoi) KHONG lam do dong selftest:
# dong do do hop thoai va ngan chen, khong cham cai nut — do la ly do no nam
# ngoai danh sach nay, chu khong phai do probe chay thieu.
ROW_RED = {name for name, _p, _o, _n, _e in MUTATIONS
           if not name.startswith("nut SFX")}

# Cho `scratch/needle_canary.py`: nam vet theo khuon (ten, duong dan, mau cu,
# mau moi, cua) va moi mau phai xuat hien DUNG MOT lan trong chinh file no tro.
#
# `--sfx-report` sinh `.png` ngay canh `.json`, nen hai duong dan tam nam trong
# MOT thu muc tam — de trong scratch/ thi moi vet de lai ric, dung rang buoc
# "loai bo rac" cua repo.
WORKDIR = tempfile.mkdtemp(prefix="clinging_sfxcf_")
VET_JSON = os.path.join(WORKDIR, "_sfx_vet.json")
ROW_JSON = os.path.join(WORKDIR, "_sfx_vet_row.json")
METRICS = ("entry_count", "dialog_rows", "clip_count", "overlap",
           "audio_tracks", "playhead_after", "clips_after_undo",
           "duration_worst_dev", "rms_worst_dev", "peak_max",
           "distinct_hashes", "pack_bytes")


def run(cmd, report_path):
    try:
        proc = subprocess.run([sys.executable, "-u"] + cmd, cwd=ROOT,
                              capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise SystemExit("PROBE DUNG: %s khong tra ve trong 300 s — may dang "
                         "chay don cong viec khac (ung dung/multi-probe). "
                         "Dong het roi chay lai." % (" ".join(cmd),))
    payload = {}
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    return proc.returncode, payload


def vet_run(tag):
    """Chay ca hai lenh production va lay do/loi cua tung lenh."""
    rc_rep, rep = run(["main.py", "--sfx-report", VET_JSON], VET_JSON)
    rc_row, row_payload = run(["main.py", "--selftest", ROW_JSON,
                               "--only=%s" % ROW_ONLY], ROW_JSON)
    fails = sorted(rep.get("failed", []))
    row_msgs = [r.get("detail", "") for r in row_payload.get("checks", [])
                if not r.get("ok")]
    numbers = ", ".join("%s=%s" % (m, rep.get(m)) for m in METRICS)
    print("  [%s] rc=%d do=%d | %s" % (tag[:44], rc_rep, len(fails), numbers))
    sys.stdout.flush()
    return rc_rep, fails, rc_row, "; ".join(row_msgs), rep.get("error", "")


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def main():
    if not os.path.isfile(PAYLOAD):
        raise SystemExit("Thieu payload that: chay `python main.py --sfx-report "
                         "scratch/_sfx_report.json` truoc.")
    with open(PAYLOAD, encoding="utf-8") as handle:
        real = json.load(handle)
    if real.get("failed"):
        raise SystemExit("Payload do LA lan chay DO (%r) — can ban xanh lam goc."
                         % real["failed"])

    check("payload cua lan chay xanh khong bat duoc dieu kien nao",
          sfx_report_fails(real), [])

    for name, patch, expected in VETS:
        mutant = copy.deepcopy(real)
        mutant.update(patch)
        check("do vi dung ly do: %s" % name,
              sorted(sfx_report_fails(mutant)), sorted(expected))

    covered = {term for _n, _p, expected in VETS for term in expected}
    combo = copy.deepcopy(real)
    for _name, patch, _expected in VETS:
        combo.update(patch)
    # Sau khi ap het vet theo thu tu, bon khoa so sanh da bi vet sau ghi de vet
    # truoc va ba cua lai xanh lai (do 22/10): `entry_count` 0 -> 13 nen
    # `distinct_hashes` 14 == 13 khong con do, `dialog_rows` 13 == 13 mat do,
    # `manifest_peak_ceiling` 0,98 la `peak_max` 0,97 chui duoi tran. Do la
    # truong hop that cua cong thuc "moi vet do dung mot cua", khong phai loi
    # cua thang do, nen bo ket hop phai dinh ca hai ben phep so sanh.
    combo.update({"entry_count": 13, "distinct_hashes": 14, "dialog_rows": 14,
                  "manifest_peak_ceiling": 0.98, "peak_max": 0.99})
    check("bo vet ket hop do tron bo dieu kien",
          set(sfx_report_fails(combo)), covered)
    check("moi term trong SFX_REPORT_CHECKS deu co vet cua no",
          sorted(covered), sorted(n for n, _f in doc.SFX_REPORT_CHECKS))

    # ── B. doi byte nguon that ───────────────────────────────────────────
    originals = {}
    try:
        rc, fails, rc_row, row_msg, err = vet_run("SACH (baseline)")
        check("baseline: --sfx-report rc=0 khong do nao", (rc, fails), (0, []))
        check("baseline: dong selftest sfx xanh", (rc_row, row_msg), (0, ""))
        for name, path, old, new, expected in MUTATIONS:
            if path not in originals:
                originals[path] = read_bytes(path)
            data = originals[path]
            needle = old.encode("utf-8") if isinstance(old, str) else old
            repl = new.encode("utf-8") if isinstance(new, str) else new
            if data.count(needle) != 1:
                raise SystemExit("Mau vet %r xuat hien %d lan trong %s — vet "
                                 "nay khong con doi byte duoc nua."
                                 % (needle[:40], data.count(needle), path))
            write_bytes(path, data.replace(needle, repl, 1))
            try:
                rc, fails, rc_row, row_msg, err = vet_run(name)
            finally:
                write_bytes(path, originals[path])
                assert read_bytes(path) == originals[path]
            if err:
                # Mot exception giua probe in ra "probe chay khong xong" chu
                # khong ra ten cua; do van la RED nhung khong phai RED vi DUNG
                # ly do, nen phan chung nay khong cho no luot qua.
                print("      error=%s" % err)
            check("vet %s: do dung cua" % name[:34], fails, sorted(expected))
            check("vet %s: rc=1" % name[:34], rc, 1)
            check("vet %s: dong selftest %s"
                  % (name[:34], "do" if name in ROW_RED else "xanh"),
                  rc_row != 0, name in ROW_RED)
        rc, fails, rc_row, row_msg, _err = vet_run("SPOT sau khi khoi phuc")
        check("khoi phuc xong thi --sfx-report xanh lai", (rc, fails), (0, []))
        check("khoi phuc xong thi dong selftest xanh lai", (rc_row, row_msg),
              (0, ""))
    finally:
        for path, data in originals.items():
            write_bytes(path, data)
        shutil.rmtree(WORKDIR, ignore_errors=True)

    print("== phan chung cua `--sfx-report` (%d vet payload + %d vet nguon) =="
          % (len(VETS), len(MUTATIONS)))
    bad = [row for row in results if not row[1]]
    for name, ok, got, want in results:
        print("  %-62s %s" % (name[:62], "PASS" if ok else "FAIL"))
        if not ok:
            print("      got  %r" % (got,))
            print("      want %r" % (want,))
    print("\n%s  (%d/%d)" % ("ALL PASS" if not bad else "FAILED (%d)" % len(bad),
                             len(results) - len(bad), len(results)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
