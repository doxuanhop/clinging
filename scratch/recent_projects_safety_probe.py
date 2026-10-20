"""Gate: mo app KHONG duoc ghi de len danh sach du an gan day cua nguoi dung.

Loi cu: `HomePage._load_recent_projects()` ket thuc bang `save_recent_projects(
valid_projects)`, tuc la duong DOC ghi file; kem theo no tinh xoa moi du an ma
`os.path.exists()` tra False ngay luc do — cam o roi ra, doi ten thu muc, hay mo
app "chi de xem" la mat mai muc trong MRU.

Probe chay `main._boot()` THAT (duong nguoi dung di) trong mot subprocess co
`APPDATA` tro ra thu muc tam, nen no khong bao gio dong va vao du lieu that.
Ba bat buoc:

  1. `recent_projects.json` sau khi boot phai NGUYEN VEN tung byte so voi luc
     trc (khong phai "noi dung tuong duong" — do bang md5).
  2. Du an dang khong thay duoc duong dan van con trong file. Day la cai ma
     loi cu lam mat.
  3. Phep phan chung: chay lai cung kich ban voi hanh vi CU duoc dung lai
     (goi `save_recent_projects` cuoi ham doc). Neu ca hai lan ra so giong nhau
     thi probe do khong phan biet duoc gi, va "PASS" chi la do tro.

    python scratch/recent_projects_safety_probe.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(REPO, "scratch", "_recent_projects_child.py")

CHILD_SRC = r'''
import os, sys, time
sys.path.insert(0, r"__REPO__")

mode = sys.argv[1]
import main
if mode == "old":
    # Dung lai hanh vi CU: duong doc van ghi file. Khong phai mot cai cach khac
    # de "kiem tra ham save" — no phai chay dung cay widget cua app that.
    import ui.home_page as hp
    real = hp.HomePage._load_recent_projects
    def patched(self):
        real(self)
        recent = hp.load_recent_projects()
        hp.save_recent_projects(
            [p for p in recent if os.path.exists(p)][:10])
    hp.HomePage._load_recent_projects = patched

app, controller = main._boot()
deadline = time.time() + 12.0
while time.time() < deadline and not controller.isVisible():
    app.processEvents()
    time.sleep(0.02)
visible = bool(controller.isVisible())
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
cards = 0
grid = getattr(controller.home_page, "recent_grid", None)
for i in range(grid.count() if grid else 0):
    item = grid.itemAt(i)
    w = item.widget() if item else None
    if type(w).__name__ == "RecentProjectCard":
        cards += 1
controller.close()
app.quit()
print("BOOTED visible=%s cards=%d" % (visible, cards))
'''

FIXED = "fixed"
OLD = "old"


def md5(path):
    if not os.path.exists(path):
        return None
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def run(mode):
    root = tempfile.mkdtemp(prefix="clinq_rp_")
    try:
        appdata = os.path.join(root, "Roaming")
        data = os.path.join(appdata, "Clinging")
        os.makedirs(data)
        live_a = os.path.join(root, "A.clinq")
        live_b = os.path.join(root, "B.clinq")
        gone = os.path.join(root, "Offline Drive", "Mất điện.clinq")
        for p in (live_a, live_b):
            open(p, "w", encoding="utf-8").write("{}")
        seed = [live_a, gone, live_b]
        recent = os.path.join(data, "recent_projects.json")
        with open(recent, "w", encoding="utf-8") as handle:
            json.dump(seed, handle, indent=2, ensure_ascii=False)
        before = md5(recent)

        with open(CHILD, "w", encoding="utf-8") as handle:
            handle.write(CHILD_SRC.replace("__REPO__", REPO))
        env = dict(os.environ, APPDATA=appdata)
        proc = subprocess.run([sys.executable, CHILD, mode], cwd=REPO, env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        after = md5(recent)
        saved = json.load(open(recent, encoding="utf-8"))
        line = next((l for l in proc.stdout.splitlines() if l.startswith("BOOTED")),
                    "")
        return {"mode": mode, "rc": proc.returncode,
                "booted": line, "cards": int(line.rsplit("=", 1)[1]) if line else -1,
                "unchanged": before == after,
                "gone_survived": gone in saved,
                "entries": len(saved),
                "stderr": (proc.stderr or "")[-400:]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    fixed = run(FIXED)
    old = run(OLD)
    for row in (fixed, old):
        print(json.dumps(row, ensure_ascii=False))

    fails = []
    if fixed["rc"] != 0 or "visible=True" not in fixed["booted"]:
        fails.append("lan boot that khong mo duoc cua so -> probe khong do cai gi")
    if fixed["cards"] != 2:
        fails.append("phai hien dung 2 card (2 du an con file), ra %d" % fixed["cards"])
    if not fixed["unchanged"]:
        fails.append("VAN GHI DE recent_projects.json khi doc")
    if not fixed["gone_survived"]:
        fails.append("du an khong thay duoc duong dan da bi xoa khoi MRU")
    if old["unchanged"]:
        fails.append("PHAN CHUNG hong: hanh vi CU cung khong lam doi file "
                     "-> probe khong phan biet duoc cu va moi")
    if old["gone_survived"]:
        fails.append("PHAN CHUNG hong: hanh vi CU van giu du an mat duong dan "
                     "-> kich ban thieu truong hop gay loi")
    print("\n=== KET LUAN ===")
    if fails:
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("  PASS: boot khong ghi file, giu du an mat duong dan; hanh vi cu bi bat")
    print("  (moi: nguyen ven md5, %d card; cu: file doi + mat muc -> gate do duoc)"
          % fixed["cards"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
