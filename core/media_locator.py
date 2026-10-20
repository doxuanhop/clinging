"""core/media_locator.py
Dinh vi lai file media lac cho: MOT chieu duy nhat cho preview va export.

Vi sao co module nay: `os.walk(".")` tung nam o nam cho khac nhau trong `ui/`
va `core/`, tim file theo ten o bat ky dau duoi THU MUC HIEN HANH. Cwd cua exe
da cai khi mo tu Explorer la `C:\\Windows\\System32`, nen mot clip thieu file
lam app di bo ca o; nguoc lai export (core/frame_composer.py, core/audio_mix.py)
khong tim gi ca, nen cung mot bai co the sang tren timeline ma xuat ra lai trang
lang. Nam chung mot chieu va gioi han tam tim kiem thi hai ben khong the lech.

Nguyen tac cho may cau hinh thap: tim kiem CHI luc mo du an (mot lan doc dia),
khong bao gio trong vong lap ve frame.
"""

import os

# Chan kinh tim kiem. Do tren may nay: thu muc du an 2.000 muc het duoi 40 ms,
# trong khi `os.walk(".")` tu cwd cua exe da cai mo toi hang chuc ngan muc.
MAX_DEPTH = 4
MAX_ENTRIES = 2000
MEDIA_TYPES = ("video", "image", "audio")
# Thu muc khong bao gio chua tai nguyen cua du an ma lai nam trong cay thu muc
# du an (repo clone, venv, recycler).
SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__",
                       "$RECYCLE.BIN", "System Volume Information"})


def _walk_limited(root):
    """Sinh (dirpath, filenames) toi MAX_DEPTH layers va MAX_ENTRIES muc."""
    base = root.rstrip("\\/")
    base_depth = base.count(os.sep)
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath != base and dirpath.count(os.sep) - base_depth >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        yield dirpath, filenames
        seen += len(filenames) + 1
        if seen >= MAX_ENTRIES:
            return


def locate(source_path, extra_roots=()):
    """Tra ve duong dan cung ten file dang con ton tai, hoac None.

    Chi di bo trong thu muc cua chinh file do va cac thu muc o `extra_roots`
    (thuong la thu muc chua file .clinq). Thu muc hien hanh KHONG bao gio duoc
    dung toi, nen ket qua khong doi khi app duoc mo tu choi khac.
    """
    if not source_path:
        return None
    if os.path.exists(source_path):
        return source_path
    name = os.path.basename(source_path)
    if not name:
        return None
    target = name.casefold()
    roots = []
    for root in [os.path.dirname(source_path)] + list(extra_roots):
        if root and os.path.isdir(root) and root not in roots:
            roots.append(root)
    for root in roots:
        for dirpath, filenames in _walk_limited(root):
            for candidate in filenames:
                if candidate.casefold() == target:
                    return os.path.join(dirpath, candidate)
    return None


def resolve_model(model, extra_roots=()):
    """Ghi thang duong dan tim duoc vao tung clip; tra (resolved, missing).

    Goi MOT LAN luc mo du an. `missing` la nhung clip ma ca preview lan export
    cung khong the hien duoc noi dung that, de caller bao cho nguoi dung thay
    vi im lang ve man trang.
    """
    resolved, missing = [], []
    for track in getattr(model, "tracks", []):
        for clip in getattr(track, "clips", []):
            if getattr(clip, "media_type", "") not in MEDIA_TYPES:
                continue
            path = getattr(clip, "source_path", "")
            if not path or os.path.exists(path):
                continue
            found = locate(path, extra_roots)
            if found:
                resolved.append((path, found))
                clip.source_path = found
            else:
                missing.append(path)
    return resolved, missing
