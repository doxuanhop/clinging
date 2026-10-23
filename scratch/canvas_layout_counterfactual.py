r"""Phan chung cho 36 cua cua `--canvas-layout-report` (diagnostics.py).

Cua nay sinh ra tu hai vet da ghi trong AGENTS.md, va ca hai deu co bang chung
o day:

  * "Cong tu cham cung bi dong goi": thang do nam trong payload, nen no phai
    do vi DUNG ten cua no khi mot dau vao bi vet — 36 vet tren 36 dieu kien,
    khong term nao lang cung (phan A), va mot bo vet ket hop do tron 36 ten;
  * cua "moi khoa co dieu khien ghi duoc model" chinh la cua DA BAT duoc loi
    that ngay 23/10: `touch()` thieu nhanh `header_bold`/`footer_bold`, probe
    chet o dong do va toan bo bang do im lang. Vet P1 duoi day cat dung noi
    bot signal cua hai checkbox ay va phai do lai dung mot ten do.

Hai lop chung minh khong trung nhau:

  A. OFFLINE tren payload THAT cua lan chay xanh (`scratch/canvas_layout_report.json`,
     do `python main.py --canvas-layout-report` ghi ra 23/10/2026, 36 cua 0 do):
     mot vet -> do DUNG mot ten. Lop nay khong chung duoc dieu gi ve do do
     luong — no chi chung bang cua phan biet.
  B. SONG: doi BYTES 4 cho trong `ui/canvas_layout_dialog.py` (bot signal bold,
     cat `_fit_height` + ep cua 300 px, lam gia lenh "du o", nut master tat
     khong con tom widget) roi chay LAI dung lenh production `python main.py
     --canvas-layout-report <json>` trong MOT process rieng. Phai do dung cua
     tu choi, byte nguon tra ve nguyen ban, va lan cuoi phai XANH lai toan bang.

Lan chay 23/10/2026: 50/50 PASS — P1..P4 lan luot do
`moi khoa co dieu khien ghi duoc model`, `khong dieu khien nao bi fold`,
`nut dan bao ro du o hay lap o cuoi`, `master tat an het dieu khien`, moi vet
tra ve DUNG mot ten, rc=1; lan phuc byte tra `failed=[]`.

    python scratch/canvas_layout_counterfactual.py        # ~3 phut (5 lan chay report)

Can tranh: mot lan chi chay MOT probe (hai vong song song pha ca hai), va dong
app cua nguoi dung truoc khi chay — `mo hop thoai duoi 0,6 s` la cua do thoi
gian, no co the do nham duoi contention.
"""

import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import diagnostics as doc
from core import canvas_layout

PAYLOAD = os.path.join(ROOT, "scratch", "canvas_layout_report.json")
DIALOG = os.path.join(ROOT, "ui", "canvas_layout_dialog.py")
MAIN = os.path.join(ROOT, "main.py")
SPEC = os.path.join(ROOT, "ClingingQt.spec")

GATES = [name for name, _f in doc.CANVAS_LAYOUT_REPORT_CHECKS]

# (ten cua, key trong payload, gia tri vet) — mot vet cho DUNG mot cua.
VETS = [
    ("combo bo cuc du 13 kieu", "layout_combo_count", 12),
    ("combo chat lieu du 10 phong cach", "texture_combo_count", 9),
    ("bang thu du 22 khoa", "widget_key_count", 21),
    ("moi khoa co dieu khien ghi duoc model", "unwired",
     ["footer_bold: widget muon True model con False"]),
    ("nut thanh mo duoc hop thoai", "dialog_opened", False),
    ("bam lan 2 dung mot instance", "reused", False),
    ("dem du dieu khien de do fold", "control_count", 8),
    ("khong dieu khien nao bi fold", "folded",
     ["luoi 6 o + tuan tu:btn_arrange"]),
    ("hop thoai vua man hinh", "max_dialog_h", 1200),
    ("master tat an het dieu khien", "disabled_leak", ["combo_layout"]),
    ("mo hop thoai duoi 0,6 s", "open_s", 1.9),
    ("do duoc private RAM cua chinh process", "ram_kib", 0),
    ("hop thoai chiem duoi 8 MiB private", "ram_delta_kib", 9100),
    ("keo slider model doi ngay", "slider_live", False),
    ("canvas preview ve lai theo bo cuc", "preview_px_changed", 1200),
    ("dong hop thoai dung MOT muc undo", "undo_rows", 2),
    ("Ctrl+Z tra bo cuc cu", "undo_restores", False),
    ("mo lai widget doc dung model", "refresh_widget_ok", False),
    ("dan clip ra transform dung tam o", "center_bad",
     ["tam lech ngang still0 12.5"]),
    ("clip thua khong bi lat vao o", "leftover_moved", ["still2"]),
    ("dan clip la MOT lenh undo", "arrange_rows", 2),
    ("Ctrl+Z tra nguyen vi tri cu", "arrange_reverted", False),
    ("nut dan bao ro du o hay lap o cuoi", "hint_ok", False),
    ("khong co clip thi nut dan tu choi", "empty_refused", False),
    ("bo cuc hop thoai in ra khung xuat", "bg_px", 1000),
    ("gach ngan split-4 hien ra trong xuat", "divider_px", 40),
    ("10 chat lieu la 10 buoc ve khac nhau", "texture_solids",
     ["paper: 1 mau duy nhat"]),
    ("chu dau ve trong vung cua no", "header_px", 12),
    ("nen den khong lam doi khung", "black_same", False),
    ("slot_gap thu o dung len", "gap_shrinks", False),
    ("phat tuan tu quay dung vong o", "seq_steps", [0, 1, 2, 3, 0, 1]),
    ("trao o nhay theo interval", "rotate_ok", False),
    ("bo cuc tron ven qua file .clinq", "round_trip_ok", False),
    ("file cu khong key tro ve mac dinh", "legacy_keys", 0),
    ("khong ghi vao cache nguoi dung", "user_cache_extra",
     ["cache/image/deadbeef.png"]),
    ("anh hop thoai ve co that", "shot_colors", 12),
]

# (mo ta, [(duong dan, mau, vet thay the)], cua phai do DUNG mot ten)
MUTATIONS = [
    ("P1 bold mat signal -> cua 'moi khoa ghi duoc model' do",
     [(DIALOG, b"            check.toggled.connect(self._apply)",
       b"            pass  # (vet) khong noi signal")],
     "moi khoa co dieu khien ghi duoc model"),
    ("P2 cua 300 px + _fit_height tat -> dieu khien nam ngoai viewport",
     [(DIALOG, b"        self.resize(760, 520)", b"        self.resize(760, 300)"),
      (DIALOG, b"        if needed > self.height():",
       b"        if False and needed > self.height():")],
     "khong dieu khien nao bi fold"),
    ("P3 nut dan luon bao 'du o' -> cua loi nhap do",
     [(DIALOG, b'               "lap o cuoi" if len(active) > len(boxes)'
       b' else "du o"))',
       b'               "du o" if len(active) > len(boxes) else "du o"))')],
     "nut dan bao ro du o hay lap o cuoi"),
    ("P4 master tat khong con tom widget -> cua 'an het dieu khien' do",
     [(DIALOG, b"            widget.setEnabled(on)",
       b"            widget.setEnabled(True)")],
     "master tat an het dieu khien"),
]

# `needle_canary.py` doc bang vet theo khuon (TARGET, REQUIRED_COUNT).
TARGET = DIALOG
REQUIRED_COUNT = 1

results = []


def check(name, got, want):
    results.append((name, got == want, got, want))


def run_report(out_json):
    """Chay LENH PRODUCTION va doc `failed` tu payload no ghi ra.

    Moi vet mot process rieng: `run_canvas_layout_report` mo MainWindow va gi
    QMediaPlayer/QPainter object — go hai lan trong cung process la cong thuc
    abort 0xC0000409 (vet 23/10), va se an luon ten cua do duoc.
    """
    if os.path.isfile(out_json):
        os.remove(out_json)
    proc = subprocess.run([sys.executable, "main.py", "--canvas-layout-report",
                           out_json], cwd=ROOT, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=1200)
    if not os.path.isfile(out_json):
        raise SystemExit("PROBE DUNG: report khong ghi payload (rc=%d)\n%s\n%s"
                         % (proc.returncode, (proc.stdout or "")[-400:],
                            (proc.stderr or "")[-1200:]))
    with open(out_json, encoding="utf-8") as handle:
        data = json.load(handle)
    return proc.returncode, data


def poison(edits, on):
    """Ap (on=True) hoi goi (on=False) mot phep doi byte, doi mau DUY NHAT."""
    for path, old, new in edits:
        needle, repl = (old, new) if on else (new, old)
        data = open(path, "rb").read()
        if data.count(needle) != 1:
            raise SystemExit("VET %r xuat hien %d lan trong %s (probe doi hoi 1)"
                             % (needle[:40], data.count(needle),
                                os.path.relpath(path, ROOT)))
        open(path, "wb").write(data.replace(needle, repl, 1))


def main():
    fails = doc.canvas_layout_report_fails

    # ── 0. Kim tren nguon: thang do van nam tren dung be mat san pham ──────
    main_src = open(MAIN, encoding="utf-8").read()
    check("main.py noi co --canvas-layout-report vao ham do",
          ('if "--canvas-layout-report" in sys.argv:' in main_src
           and "run_canvas_layout_report" in main_src), True)
    check("bundle van chuyen ui.canvas_layout_dialog (hiddenimports)",
          "'ui.canvas_layout_dialog'" in open(SPEC, encoding="utf-8").read(),
          True)
    dialog_src = open(DIALOG, encoding="utf-8").read()
    check("19 ten widget cua cua 'master tat' van ton tai trong hop thoai",
          [attr for attr in doc.CANVAS_LAYOUT_CHILD_WIDGETS
           if "self.%s =" % attr not in dialog_src], [])
    check("bang gia tri thu dung 22 khoa cua LAYOUT_DEFAULTS",
          sorted(doc.CANVAS_LAYOUT_TEST_VALUES)
          == sorted(canvas_layout.LAYOUT_DEFAULTS), True)

    if not os.path.isfile(PAYLOAD):
        raise SystemExit(
            "Thieu payload that: chay `python main.py --canvas-layout-report %s` "
            "truoc (phan chung chay tren du lieu do cua do, khong tren fixture "
            "tu dung)." % PAYLOAD)
    with open(PAYLOAD, encoding="utf-8") as handle:
        real = json.load(handle)
    check("payload lan chay xanh khong bat duoc dieu kien nao", fails(real), [])
    check("payload do dung lenh production ghi ra (khong phai fixture)",
          real.get("report"), os.path.abspath(PAYLOAD))

    # ── A. Mot vet -> mot ten ──────────────────────────────────────────────
    check("moi cua co dung MOT vet cua chinh no (khong trung, khong thieu)",
          sorted(name for name, _k, _v in VETS), sorted(GATES))
    for name, key, value in VETS:
        mutant = copy.deepcopy(real)
        mutant[key] = value
        check("do vi dung ly do: %s" % name, sorted(fails(mutant)), [name])

    # ── B. Bo vet ket hop + gate gia do ────────────────────────────────────
    combo = copy.deepcopy(real)
    for _name, key, value in VETS:
        combo[key] = value
    check("bo vet ket hop do tron 36 cua", sorted(fails(combo)), sorted(GATES))
    try:
        fails({})
        check("payload rong bi tu choi", "khong raise", "KeyError")
    except KeyError:
        check("payload rong bi tu choi", True, True)

    # ── C. Phan chung SONG: 4 phep doi byte tren nguon that ────────────────
    originals = {path: open(path, "rb").read() for path, _o, _n in MUTATIONS[0][1]}
    scratch_dir = os.path.join(ROOT, "scratch")
    poison_json = os.path.join(scratch_dir, "_cl_poison_counterfactual.json")
    restored_json = os.path.join(scratch_dir, "_cl_restored_counterfactual.json")
    try:
        for label, edits, expected in MUTATIONS:
            poison(edits, True)
            try:
                rc, report = run_report(poison_json)
            finally:
                poison(edits, False)
                for path, blob in originals.items():
                    if open(path, "rb").read() != blob:
                        raise SystemExit("KHONG PHUC HOI duoc byte goc cua %s"
                                         % path)
            got = sorted(report.get("failed", ["<khong co failed>"]))
            check("%s -> do DUNG mot cua" % label, got, [expected])
            print("  %-56s rc=%d failed=%s" % (label[:56], rc, got))

        rc, report = run_report(restored_json)
        check("lan cuoi sau khi phuc byte: XANH lai toan bang",
              sorted(report.get("failed", ["<khong co failed>"])), [])
        print("  lan phuc byte: rc=%d failed=%s" % (rc, report.get("failed")))
    finally:
        for path, blob in originals.items():
            open(path, "wb").write(blob)
        for out in (poison_json, restored_json):
            for name in (out, out[:-5] + ".png"):
                if os.path.isfile(name):
                    os.remove(name)

    print("== phan chung cua `--canvas-layout-report` (%d vet offline + %d vet song) =="
          % (len(VETS) + 4, len(MUTATIONS) + 1))
    bad = [row for row in results if not row[1]]
    for name, ok, got, want in results:
        print("  %-64s %s" % (name[:64], "PASS" if ok else "FAIL"))
        if not ok:
            print("      got  %r" % (got,))
            print("      want %r" % (want,))
    print("\n%s  (%d/%d)" % ("ALL PASS" if not bad else "FAILED (%d)" % len(bad),
                             len(results) - len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
