"""scratch/graph_report_counterfactual.py

Chung minh --graph-report CO THE FAIL.

Mot khoa khong the sai khong duoc tinh la khoa. O day phat lai hai loi DA TUNG
nam trong ban ship (khong phai sua file, chi patch trong bo nho cua process do)
roi chay lai chinh report:

  curve  : sample_curve ghi nham diem CUOI thanh t0 -> duong keo mot net nguoc
           qua ca lane -> cot anh co >1 doan net / lech gia tri.
  nodes  : ClipItem.update_from_model chi dinh vi lai moc cu (khong dung lai bo
           moc khi model doi) -> undo tu stack khong lam kim cuong chay theo.
  blit   : anh bang chung dan lane DPR 1.25 len canvas DPR 1 theo kieu cu
           drawPixmap(x, y, pm) -> bi ep 80%, dau tru cua "-372px" mat net.

Case sach (khong patch) phai rc=0 — neu ca ba deu rc=0 thi report vo nghia.

Chay: QT_QPA_PLATFORM=windows PYTHONIOENCODING=utf-8 python -u scratch/graph_report_counterfactual.py
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "scratch", "_graph_cf_child.py")


def run(mode):
    out = os.path.join(os.environ.get("TEMP", ROOT),
                       "graph_cf_%s.json" % mode)
    if os.path.isfile(out):
        os.remove(out)
    proc = subprocess.run([sys.executable, "-u", CHILD, mode, out],
                          capture_output=True, text=True, timeout=300)
    payload = {}
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as handle:
            payload = json.load(handle)
    return proc.returncode, payload, proc.stdout.strip().splitlines()[-3:]


def main():
    fails = []
    clean, clean_payload, _ = run("clean")
    print("clean            rc=%d  doan_net=%r  kim cuong undo=%r"
          % (clean, clean_payload.get("duong_ve", {}).get("doan_net"),
             clean_payload.get("undo", {}).get("diamonds_x")))
    fails += [] if clean == 0 else ["clean phai rc=0, thu rc=%d" % clean]

    curve, curve_payload, _ = run("curve")
    runs = curve_payload.get("duong_ve", {}).get("doan_net")
    print("curve  (loi cu)  rc=%d  doan_net=%r  lech=%r"
          % (curve, runs, curve_payload.get("duong_ve", {}).get("max_lech_px")))
    fails += ([] if curve == 1 else
              ["patch loi sample_curve khong lam do thi no: rc=%d" % curve])

    nodes, nodes_payload, _ = run("nodes")
    diamonds = nodes_payload.get("undo", {}).get("diamonds_x")
    print("nodes  (loi cu)  rc=%d  kim cuong undo=%r  model undo=%r"
          % (nodes, diamonds,
             nodes_payload.get("undo", {}).get("model")))
    fails += ([] if nodes == 1 else
              ["patch loi kim cuong cu khong lam do thi no: rc=%d" % nodes])

    blit, blit_payload, _ = run("blit")
    gutter = blit_payload.get("cot_so", {})
    print("blit   (loi cu)  rc=%d  cot_so=%r" % (blit, gutter))
    # Phai la KHOA DAU TRU bat loi, khong phai mot dieu kien khong lien quan
    # (le hep / so dong) vo tinh no theo.
    fails += ([] if blit == 1 else
              ["patch dan anh 80% khong lam do thi no: rc=%d" % blit])
    if gutter.get("dau_tru") == gutter.get("dau_tru_muon"):
        fails.append("blit: dau_tru van bang dau_tru_muon nen khoa moi vo nghia "
                     "(%r)" % gutter)

    print("\n%s  (%d fail)" % ("ALL PASS" if not fails else "FAILED",
                               len(fails)))
    for line in fails:
        print("  " + line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
