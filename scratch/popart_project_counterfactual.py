r"""Phan chung cho gate "du an pop art" (scratch/popart_project_build.py).

Moi phep doi byte duoc do bang HAI gate, vi hai lop bang chung khac nhau:
  * `main.py --selftest <json>` — do TUNG HAM o don vi (posterize dung so bac,
    halftone nap muc theo do toi, outline khong cham mang phang, chinh mau
    hue/lift-gamma-gain/LUT, kieu chu luu vao file).
  * build che do ngan (CLINGING_POPART_SHORT=1) — do tren FILE mp4 da giai ma
    va round-trip .clinq, van la DUNG doan code cua lan chay hang that: lap
    clip bang core.commands, luu/mo lai bang core.project_storage, xuat bang
    ui.export_dialog.RenderWorker.

So lieu duoc dien duoi day khong phai doan truoc — chung do lan do tham khao
21/10/2026 (scratch/_popart_cf_discover.py, da xoa):

  F1 halftone_rgb tra thang anh  selftest: "phong cach pop art" do;  build: do
     "the Pop Art doi anh" (2,91 < 10), "luoi 6 px" (2,68 < 25) VA "bo chinh
     mau (gain 1,10)" (0,33 < 1,0). Cua chinh mau do luon theo F1 la CO THAT:
     bo cham Ben-Day thi posterize 4 bac nuot het muc tang 10%, nen khong con
     lech de do. Do la ly do F2 (mat gain trong bo chinh mau) can ton tai: no
     lat DUNG mot cua chinh mau.
  F2 x * 1/g * 1.0               selftest: "chinh mau: ..." do; build: chi do
     cua chinh mau.
  F3 the Pop Art khong lay thong so tu preset (params={})  build: do "the Pop
     Art doi anh" + "luoi 6 px"; selftest VAN XANH, vi dong "phong cach pop
     art" goi thang halftone_rgb/posterize_rgb voi so lieu cua no nen khong
     nhin thay duong noi preset -> EffectData. Do la ly do can ca hai cap gate.
     Ban dau o day la "preset ve trung tinh" (halftone 0.0, posterize 255.0,
     outline 0.0) va do XANH toan bang — bo, vi chuoi loc theo SU CO MAT cua
     khoa (core/clip_effects.py:450 `if "halftone" in params:`) chu khong theo
     gia tri: halftone 0.0 van in cham, o 3 px do `c = max(3, ...)`.
  F4 khieu luu text_style        selftest: "8 kieu karaoke: ..." do (dong do
     cung luu/mo text_style); build: do "mo lai: POP ART!.text_style".
     Dong "style chu: vien/bong/hop nen/can le" VAN XANH (no do truong khac).
  F5 serialize_effects loc bo the Chinh mau -> build do 5 cua round-trip chinh
     mau, selftest do "chinh mau: ...".
  F6 posterize lv = 255          selftest DO ("phong cach pop art"), build VAN
     XANH toan bang. Do la phep thu NGUOC: file sau encode khong phan biet
     duoc posterize, vi luoi cham Ben-Day ve MUC/GIAY tu mau goc va bo
     resampler cua FrameComposer mo lai cac bac da nen.

Chay:
    python scratch/popart_project_counterfactual.py

Ghi/phuc hoi byte nguyen ban (write_text o may nay doi LF thanh CRLF); lan cuoi
cung phai XANH lai ca hai gate. Anh bang chung:
scratch/popart_project_counterfactual.png
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "scratch", "popart_project_build.py")
TMP = os.path.join(ROOT, "scratch", "popart_cf_tmp")
# Frame phai nam NGOAI TMP: popart_project_build.py:492 xoa trắng TMP moi vong
# (SHORT), nen copy vao TMP thi vong ke tiep an mat anh cua cac vong truoc.
FRAMES = os.path.join(ROOT, "scratch", "popart_cf_frames")
GATE_JSON = os.path.join(ROOT, "scratch", "popart_cf_evidence.json")
SELF_JSON = os.path.join(ROOT, "scratch", "_popart_cf_selftest.json")
FRAME_T = 0.9                     # moc do o giua ban ngan, co clip chu ben trong
EVIDENCE = os.path.join(ROOT, "scratch", "popart_project_counterfactual.png")

CE = os.path.join(ROOT, "core", "clip_effects.py")
PS = os.path.join(ROOT, "core", "project_storage.py")
CM = os.path.join(ROOT, "core", "commands.py")


def L(*lines):
    """Noi cac dong bang LF that: ca 3 file nguon deu LF."""
    return b"\n".join(lines)


HALF_HEAD = L(b'    h, w = rgb.shape[:2]', b'    c = max(3, int(round(cell)))')
HALF_NOOP = L(b'    return rgb', b'    h, w = rgb.shape[:2]',
              b'    c = max(3, int(round(cell)))')

# Nhung cua build PHAI xanh o moi phep thu: do la cac lop khong bi no cham.
BUILD_ALWAYS_GREEN = [
    "chuan: thoi luong file = thoi luong du an",
    "am thanh trong file", "file co 2 kenh am thanh",
    "chu ve ra file", "khong loi xuat", "phoi finished_ok",
]

# (ten, [(file, old, new, so_lan)], cua_phai_do, cua_phai_xanh)
MUTATIONS = [
    ("F1 halftone_rgb tra thang anh (khong ve cham Ben-Day)",
     [(CE, HALF_HEAD, HALF_NOOP, 1)],
     ["selftest: phong cach pop art",
      "the Pop Art doi anh", "luoi 6 px", "bo chinh mau (gain 1.10)"],
     BUILD_ALWAYS_GREEN + ["mo lai:"]),
    ("F2 gain bi bo trong bo chinh mau (x**1/g * 1.0)",
     [(CE, b"    x = np.power(x, 1.0 / g) * gain",
       b"    x = np.power(x, 1.0 / g) * 1.0", 1)],
     ["selftest: chinh mau: hue/lift-gamma-gain/LUT .cube",
      "bo chinh mau (gain 1.10)"],
     BUILD_ALWAYS_GREEN + ["the Pop Art doi anh", "luoi 6 px", "mo lai:"]),
    ("F3 the Pop Art khong lay thong so tu preset (params={})",
     [(CM, b"            params=dict(preset),", b"            params={},", 1)],
     ["the Pop Art doi anh", "luoi 6 px"],
     BUILD_ALWAYS_GREEN + ["selftest: phong cach pop art",
                           "bo chinh mau (gain 1.10)", "mo lai:"]),
    ("F4 kieu luu bo truong text_style -> .clinq mat kieu chu",
     [(PS, b'                "text_style": getattr(clip, "text_style", "none"),',
       b'                "text_style": "none",', 2)],
     ["selftest: 8 kieu karaoke", "mo lai: POP ART!.text_style"],
     BUILD_ALWAYS_GREEN + ["selftest: style chu: vien/bong/hop nen/can le",
                           "the Pop Art doi anh", "luoi 6 px",
                           "bo chinh mau (gain 1.10)"]),
    ("F5 serialize_effects loc bo the Chinh mau",
     [(PS, b"    return [e.to_dict() for e in effects]",
       b'    return [e.to_dict() for e in effects if e.name != "Chinh mau"]', 1)],
     ["selftest: chinh mau: hue/lift-gamma-gain/LUT .cube",
      "mo lai: dung HAI the Chinh mau", "bo chinh mau con nguyen 5 khoa",
      "gain van la 1.1", "fixture A dung hieu ung", "fixture B dung hieu ung"],
     BUILD_ALWAYS_GREEN + ["the Pop Art doi anh", "luoi 6 px"]),
    ("F6 posterize khong nen (lv = 255) - phep thu NGUOC o cap file",
     [(CE, b"    lv = max(2.0, float(levels))", b"    lv = 255.0", 1)],
     ["selftest: phong cach pop art"],
     BUILD_ALWAYS_GREEN + ["the Pop Art doi anh", "luoi 6 px",
                           "bo chinh mau (gain 1.10)", "mo lai:"]),
]


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def apply(edits):
    for path, old, new, count in edits:
        data = open(path, "rb").read()
        if data.count(old) != count:
            raise SystemExit("neo byte khong khop o %s: thay %d lan, mong %d"
                             % (path, data.count(old), count))
        open(path, "wb").write(data.replace(old, new, count))


def restore_all(targets, before, after):
    """Ghi lai nguyen block byte da doc luc bat dau, roi KIEM TRA bang hash.

    Khong dung `git checkout`: trong lan do, repo co the dang co thay doi khac
    chen vao, va neu phep phuc hoi hong thi moi lan do sau la gia.
    """
    for path in targets:
        open(path, "wb").write(before[path])
    bad = [p for p in targets if digest(p) != after[p]]
    if bad:
        raise SystemExit("byte khong ve nguyen ban: %s" % bad)


def _child(argv, env, timeout):
    return subprocess.run(argv, cwd=ROOT, env=dict(os.environ, **env),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _bail(tag, where, proc):
    out = (proc.stdout or "")[-600:]
    err = (proc.stderr or "")[-800:]
    raise SystemExit("%s: %s chay loi (khong phai FAIL that):\n%s\n%s"
                     % (tag, where, out, err))


def run_build(tag):
    """Gate do tren file: ban ngan, cung doan code voi lan chay hang that."""
    if os.path.exists(GATE_JSON):
        os.remove(GATE_JSON)
    proc = _child([sys.executable, "-u", BUILD],
                  {"CLINGING_POPART_SHORT": "1", "PYTHONIOENCODING": "utf-8",
                   "QT_QPA_PLATFORM": "windows"}, 3600)
    if "Traceback" in (proc.stdout or "") or "Traceback" in (proc.stderr or ""):
        _bail(tag, "build", proc)
    if not os.path.exists(GATE_JSON):
        raise SystemExit("%s: build khong ghi ra %s" % (tag, GATE_JSON))
    return {"rc": proc.returncode,
            "fails": json.load(open(GATE_JSON, encoding="utf-8")).get("fails", [])}


def run_selftest(tag):
    """Gate don vi: 34 dong cua chinh app, ten cua gan prefix de khong lan."""
    if os.path.exists(SELF_JSON):
        os.remove(SELF_JSON)
    proc = _child([sys.executable, "-u", "main.py", "--selftest", SELF_JSON],
                  {"PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "windows"},
                  1800)
    if "Traceback" in (proc.stdout or "") or "Traceback" in (proc.stderr or ""):
        _bail(tag, "selftest", proc)
    if not os.path.exists(SELF_JSON):
        raise SystemExit("%s: selftest khong ghi ra %s" % (tag, SELF_JSON))
    failed = json.load(open(SELF_JSON, encoding="utf-8")).get("failed", [])
    return {"rc": proc.returncode, "fails": ["selftest: " + n for n in failed]}


def run_both(tag):
    b, s = run_build(tag), run_selftest(tag)
    return {"rc": (b["rc"], s["rc"]), "fails": b["fails"] + s["fails"],
            "build": b, "self": s}


def frame_of(tag):
    """Copy frame `chuan` moc giua cua lan chay vung tam, phuc dung anh bang chung."""
    src = os.path.join(TMP, "chuan_%.1f.png" % FRAME_T)
    dst = os.path.join(FRAMES, "chuan_%s.png" % tag)
    shutil.copyfile(src, dst)
    return dst


def verdict(res, expect_red, expect_green):
    got = res["fails"]
    red = [lab for lab in expect_red if any(lab in f for f in got)]
    extra = [f for f in got if not any(k in f for k in expect_red)]
    green = [lab for lab in expect_green if not any(lab in f for f in got)]
    want_rc = 1 if expect_red else 0
    ok = (want_rc in res["rc"]
          and len(red) == len(expect_red) and not extra
          and len(green) == len(expect_green))
    return ok, red, extra, [l for l in expect_green if l not in green]


def main():
    targets = sorted({p for _t, edits, _r, _g in MUTATIONS for (p, *_x) in edits})
    before = {p: open(p, "rb").read() for p in targets}
    after = {p: digest(p) for p in targets}
    os.makedirs(FRAMES, exist_ok=True)
    rows = []
    try:
        base = run_both("baseline")
        ok, _r, extra, lost = verdict(base, [], [])
        print("baseline rc=%s fails=%s" % (base["rc"], base["fails"] or "khong co"))
        if base["fails"]:
            print("GATE FAIL: mot trong hai gate dang DO truoc khi phan chung -> "
                  "so cua con lai vo nghia")
            return 1
        frames = {"baseline": frame_of("baseline")}
        for name, edits, expect_red, expect_green in MUTATIONS:
            apply(edits)
            try:
                res = run_both(name[:2])
            finally:
                restore_all(targets, before, after)
            ok, red, extra, lost = verdict(res, expect_red, expect_green)
            print("\n%-58s %s rc=%s" % (name, "OK" if ok else "SAI", res["rc"]))
            print("   do dung cua      : %s" % (red or "(khong doi cua nao)"))
            print("   do oan cua khac  : %s" % ([f[:78] for f in extra] or "khong co"))
            print("   xanh giu duoc    : %d/%d"
                  % (len(expect_green) - len(lost), len(expect_green)))
            if lost:
                print("   bi mat xanh o    : %s" % lost)
            rows.append({"mutation": name, "expected_red": expect_red,
                         "expected_green": expect_green, "fails": res["fails"],
                         "rc": list(res["rc"]), "ok": ok})
            frames[name[:2]] = frame_of(name[:2])
            if not ok:
                json.dump(rows, open(os.path.join(
                    ROOT, "scratch", "popart_project_counterfactual.json"),
                    "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print("GATE FAIL: %s" % name)
                return 1
        final = run_both("final")
        if final["fails"]:
            print("GATE FAIL: sau khi phuc hoi byte ma van con do:\n  %s"
                  % "\n  ".join(final["fails"]))
            return 1
        print("\ncuoi cung (byte nguyen ban): rc=%s, ca hai gate XANH"
              % (final["rc"],))
        frames["final"] = frame_of("final")
        write_evidence(frames)
        json.dump(rows, open(os.path.join(
            ROOT, "scratch", "popart_project_counterfactual.json"),
            "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("ALL PASS")
        return 0
    finally:
        for p in targets:
            open(p, "wb").write(before[p])
        for p in targets:
            if digest(p) != after[p]:
                print("CANH BAO: byte %s khong ve nguyen ban" % p)
        shutil.rmtree(FRAMES, ignore_errors=True)


def write_evidence(frames):
    import cv2
    import numpy as np
    keys = [k for k in ("baseline", "F1", "F2", "F3", "F4", "F5", "F6", "final")
            if frames.get(k)]
    ref = cv2.imread(frames["baseline"], cv2.IMREAD_COLOR)
    if ref is None:
        raise SystemExit("khong doc duoc frame baseline de dung anh chung minh")
    tile_w, tile_h = 300, 169
    gap, head = 6, 40
    sheet = np.full((head + len(keys) * (tile_h + 22) + 40,
                     gap * 2 + 2 * (tile_w + gap), 3), 18, np.uint8)
    for c, text in enumerate(("frame `chuan` cua lan baseline",
                              "frame `chuan` cua lan da doi byte")):
        cv2.putText(sheet, text, (gap + c * (tile_w + gap) + 4, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (238, 238, 238), 1, cv2.LINE_AA)
    for r, key in enumerate(keys):
        y0 = head + r * (tile_h + 22)
        img = cv2.imread(frames[key], cv2.IMREAD_COLOR)
        d = -1.0
        if img is not None and img.shape == ref.shape:
            d = float(np.abs(img.astype(np.float64)
                             - ref.astype(np.float64)).mean())
        cv2.putText(sheet, "%s  lech %.1f mau/pixel" % (key, d),
                    (gap, y0 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (200, 200, 120), 1, cv2.LINE_AA)
        for c, src in enumerate((ref, img)):
            if src is None:
                continue
            tile = cv2.resize(src, (tile_w, tile_h))
            sheet[y0 + 20:y0 + 20 + tile_h,
                  gap + c * (tile_w + gap):gap + c * (tile_w + gap) + tile_w] = tile
    cv2.putText(sheet, "F4/F5/F6 khong doi hinh: mat truong trong .clinq hoac lop ma file khong nhin thay",
                (gap, sheet.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.40,
                (205, 205, 205), 1, cv2.LINE_AA)
    if not cv2.imwrite(EVIDENCE, sheet):
        raise SystemExit("khong ghi duoc anh bang chung")
    print("anh chung minh: %s (%d bytes, %dx%d)"
          % (EVIDENCE, os.path.getsize(EVIDENCE), sheet.shape[1], sheet.shape[0]))


if __name__ == "__main__":
    sys.exit(main())
