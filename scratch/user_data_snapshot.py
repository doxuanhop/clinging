"""Chup + so sanh danh sach file du lieu nguoi dung, de chung minh mot buoc do
khong ghi de len may.

Cac probe khoi dong goi thang main._boot() va Home page tu doc recent_projects,
nen "khong co gi thay doi" phai la mot ket luan do duoc, khong phai mot loi hua.

    python scratch/user_data_snapshot.py capture scratch/_snap_x.json
    python scratch/user_data_snapshot.py diff    scratch/_snap_before.json scratch/_snap_after.json
"""
import hashlib
import json
import os
import sys


def roots():
    out = [os.path.join(os.environ.get("APPDATA", ""), "Clinging")]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in ("data", ".clinq"):
        p = os.path.join(repo, d)
        if os.path.exists(p):
            out.append(p)
    proj = os.path.join(os.path.expanduser("~"), ".clinq")
    if os.path.exists(proj):
        out.append(proj)
    # ~/.clinqing chua autosave.json + recovery/*.clinq: mot probe ghi vao day
    # ma root khong cover thi diff van in ra "0 THEM / 0 MAT / 0 DOI".
    # project_dir (mac dinh ~/Clinging_Projects) la noi file .clinq va Assets/
    # cua du an that nam, nen phai chup duoc no.
    core = core_dirs()
    out += [core["clinqing"], core["project_dir"]]
    return [r for r in out if r and os.path.isdir(r)]


def core_dirs():
    """Duong dan cua ~/.clinqing va thu muc du an, doc tu nguồn that."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    # DUUNG nhu core.project_storage.APP_DIR va core.settings.DEFAULTS — khong
    # phong nen duong dan, neu khong diff do mot cay khac.
    from core.project_storage import APP_DIR
    from core.settings import DEFAULTS
    return {"clinqing": APP_DIR, "project_dir": DEFAULTS["project_dir"]}


def fingerprint(r):
    # [mtime, size] du de phat hien app DA CHAM vao mot file, nhung KHONG du de
    # noi dung khong doi: hai noi dung khac nhau cung 79 byte (duong dan doi
    # dau, doi thu tu key) lech nhau ma mtime+size nguyen ven. Do lech mtime
    # den miligiay thi du; noi dung thi phai do bang byte.
    #
    # Cac snapshot chup truoc 2026-10-20 chi co [mtime, size]; diff duoc phat
    # hien bang cach bo qua phan hash khi MOT BEN khong co, nen ban cu van so
    # duoc ma khong bao "doi" gia.
    try:
        with open(r, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:16]
    except OSError as exc:
        return "LOI:%s" % exc
    return [round(os.path.getmtime(r), 3), os.path.getsize(r), digest]


def same(before, after):
    """So sanh hai fingerprint, triet de hash neu ben nao khong co (snapshot cu)."""
    if isinstance(before, str) or isinstance(after, str):
        return before == after
    if len(before) < 3 or len(after) < 3:
        return before[:2] == after[:2]
    return before == after


def capture():
    snap = {}
    for r in roots():
        for dirpath, _dirs, files in os.walk(r):
            for name in files:
                p = os.path.join(dirpath, name)
                try:
                    snap[p] = fingerprint(p)
                except OSError as exc:
                    snap[p] = "LOI:%s" % exc
    return snap


def diff(before_path, after_path):
    before = json.load(open(before_path, encoding="utf-8"))
    after = json.load(open(after_path, encoding="utf-8"))
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after)
                     if not same(before[k], after[k]))
    print("truoc %d file, sau %d file" % (len(before), len(after)))
    for label, group in (("THEM", added), ("MAT", removed), ("DOI", changed)):
        print("  %s: %d" % (label, len(group)))
        for k in group[:20]:
            print("      %s" % k)
    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        snap = capture()
        json.dump(snap, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
        print("chup %d file ->" % len(snap), sys.argv[2])
        print("gua:", roots())
    else:
        sys.exit(diff(sys.argv[2], sys.argv[3]))
