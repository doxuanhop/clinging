"""Phan chung cho cua `--split-report` (doan cat file trong bundle da cai).

Cua nay tung co `len(menu_actions) == 2`, va "Nen / toi uu tep" buoc vao menu
card video cung luc (commit b88f59f, dong 38 selftest). Ket qua: `--split-report`
chay tren may da cai do RED sau do may hom, khong phai luc viet tinh nang. Do
ay la bang chung cua hai thu can giung o day:

  1. Payload THAT do exe da cai ghi ra (`scratch/installed_split.json`, lan
     chay 22/10/2026) phai khong dieu kien nao trong
     `diagnostics.split_report_fails` bat duoc — nen phan chung chay tren
     du lieu san, khong tren fixture tu dung.
  2. Moi dieu kien phai DO vi DUNG ten cua no khi chi mot dau vao bi vet:
     21 phep vet tren 14 dieu kien — 4 cho `menu_actions` (thieu / thua / dao
     thu tu / doi ten hanh dong cat), con lai moi term mot vet rieng — va mot
     bo vet ket hop phai do DUNG 14 ten do, khong term nao lang cung.

Them kim: `VIDEO_CARD_MENU` trong diagnostics la hang so doc lap, khong phai
chuoi lay tu `ui/library_panel.py`. Neu no lech khoi thu tu ma card that sinh
ra thi cua do mot cach vo nghia, nen duoi day quet thang vao nguon
`ui/library_panel.py` ba chuoi hanh dong dung thu tu.
"""

import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAYLOAD = os.path.join(ROOT, "scratch", "installed_split.json")
PANEL = os.path.join(ROOT, "ui", "library_panel.py")

import diagnostics as doc
split_report_fails = doc.split_report_fails
VIDEO_CARD_MENU = list(doc.VIDEO_CARD_MENU)

CUT = "Cắt thành nhiều đoạn…"
THUMB = "Trích xuất ảnh thu nhỏ…"
COMPRESS = "Nén / tối ưu tệp…"

if not os.path.isfile(PAYLOAD):
    raise SystemExit("Thieu payload that: chay `dist\\Clinging\\Clinging.exe "
                     "--split-report scratch/installed_split.json` truoc.")
if VIDEO_CARD_MENU != [THUMB, CUT, COMPRESS]:
    raise SystemExit("VIDEO_CARD_MENU trong diagnostics khong con la menu "
                     "3 hanh dong ma phan chung nay biet: %r" % (VIDEO_CARD_MENU,))

results = []


def check(name, got, want):
    results.append((name, got == want, got, want))


# ── 1. Kim tren nguon: card that sinh ra dung thu tu hang so đòi ──────────
text = open(PANEL, encoding="utf-8").read()
block = re.search(r"def context_menu\(self\):.*?(?=\n    def )", text, re.S)
if block is None:
    raise SystemExit("Khong tim thay context_menu trong ui/library_panel.py")
body = block.group(0)
titles = re.findall(r'menu\.addAction\(\s*font_icon\([^)]*\),\s*\n?\s*"([^"]+)"',
                    body)
check("thu tu chuoi trong ui/library_panel.py == VIDEO_CARD_MENU", titles,
      VIDEO_CARD_MENU)

with open(PAYLOAD, encoding="utf-8") as handle:
    real = json.load(handle)

check("payload cua exe da cai khong bat duoc dieu kien nao",
      split_report_fails(real), [])
check("payload do exe da cai ghi ra mang dung menu 3 hanh dong",
      real["menu_actions"], VIDEO_CARD_MENU)

# ── 2. Phan chung: mot vet -> mot ten ─────────────────────────────────────
segs = real["segments"]
MUTATIONS = [
    # (ten vet, key, gia tri moi, nhung dieu kien phai do)
    ("menu thieu hanh dong nen (kieu cu == 2)", "menu_actions",
     [THUMB, CUT], ["menu card video"]),
    ("menu thua mot hanh dong", "menu_actions",
     VIDEO_CARD_MENU + ["Xoa khoi thu vien"], ["menu card video"]),
    ("menu dao thu tu cat / nen", "menu_actions",
     [THUMB, COMPRESS, CUT], ["menu card video"]),
    ("hanh dong cat doi ten", "menu_actions",
     [THUMB, "Chia nho thanh nhieu doan…", COMPRESS], ["menu card video"]),
    ("khong phai ban dong goi", "frozen", False, ["frozen"]),
    ("mo sai nguon", "selected_source", "", ["dung nguon vua bam"]),
    ("danh sach ham khop danh sach dia", "on_disk",
     [segs[0]["name"]], ["3 doan nam tren dia",
                         "danh sach ham = danh sach dia"]),
    ("co doan that bai", "failed", ["part02.mp4"],
     ["khong doan nao that bai"]),
    ("nguoi dung bam Huy", "cancelled", True, ["khong doan nao that bai"]),
    ("ffprobe khong doc lai duoc doan", "segments",
     [dict(segs[0], probe=0.0)] + segs[1:], ["ffprobe doc lai tung doan"]),
    ("mei cat cho nhau", "joints", [0.04, 0.0],
     ["mei cat khong ho khong choong"]),
    ("mei cat ho nhau", "joints", [-0.02, 0.0],
     ["mei cat khong ho khong choong"]),
    ("mau doan lech mau nguon", "hue_gaps", [45.0, 0.0, 0.0],
     ["mau tung doan la mau trong nguon"]),
    ("thieu phep do mau", "hue_gaps", [0.0, 0.0],
     ["mau tung doan la mau trong nguon"]),
    ("khong do mau duoc", "hue_gaps", [0.0, None, 0.0],
     ["mau tung doan la mau trong nguon"]),
    ("status khong ke so doan", "status", "Xong.", ["status ke so doan"]),
    ("thang tien do an sau khi chay", "progress_visible_after", False,
     ["thang tien do dang hien"]),
    ("thang tien do khong do duoc day", "progress_band_px", 0,
     ["do day thang tien do hop ly"]),
    ("thang tien do day gianh nut bam", "progress_band_px", 400,
     ["do day thang tien do hop ly"]),
    ("man den (khong phai cua so that)", "distinct_colors", 1,
     ["cua so ve co that"]),
    ("anh bang chung bi an", "screenshot",
     os.path.join(ROOT, "scratch", "khong_ton_tai_split.png"),
     ["anh bang chung nam tren dia"]),
]

for name, key, value, expected in MUTATIONS:
    mutant = copy.deepcopy(real)
    mutant[key] = value
    check("do vi dung ly do: %s" % name,
          sorted(split_report_fails(mutant)), sorted(expected))

# ── 3. Bo ket hop: tat ca vet cung luc -> moi dieu kien deu phai len ten ───
combo = copy.deepcopy(real)
for _n, key, value, _e in MUTATIONS:
    combo[key] = value
combo_fails = set(split_report_fails(combo))
covered = {exp for _m in MUTATIONS for exp in _m[3]}
check("bo vet ket hop do tron bo dieu kien", combo_fails, covered)
check("moi term trong SPLIT_REPORT_CHECKS deu co vet cua no",
      sorted(covered), sorted(n for n, _f in doc.SPLIT_REPORT_CHECKS))

print("== phan chung cua `--split-report` (%d phep vet) ==" % len(MUTATIONS))
bad = [row for row in results if not row[1]]
for name, ok, got, want in results:
    print("  %-58s %s" % (name[:58], "PASS" if ok else "FAIL"))
    if not ok:
        print("      got  %r" % (got,))
        print("      want %r" % (want,))
print("\n%s  (%d/%d)" % ("ALL PASS" if not bad else "FAILED (%d)" % len(bad),
                        len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
