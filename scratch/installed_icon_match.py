"""Trich bieu tuong thuc trong mot file .exe va so voi assets/app-icon/icon.ico.

    python scratch\\installed_icon_match.py

Vi sao phai trich PE resource chu khong tin vao ten file: shortcut Desktop cua
may dung IconLocation ",0" — Windows ve chinh nhom bieu tuong ma .exe mang,
khong phai file .ico nao duoi _internal. Neu bootloader dong goi icon cu thi
khong mot dong selftest nao phat hien duoc, ma mat nguoi dung thay ngay.

Vi sao doc .rsrc bang tay thay vi LoadLibraryEx/FindResourceExW: do thu tai
may nay, EnumResourceNamesW liet ke duoc RT_GROUP_ICON id=1 nhung
FindResourceExW cung id do tra NULL voi loi 1813 (RESOURCE_NAME_NOT_FOUND) o
moi bo tham so flag/ngon ngu. Mot detector ma chinh API Windows khong tra loi
duoc thi khong dung lam canh.

So sanh theo pixel tung anh, khong theo hash: PyInstaller va Inno nen lai PNG
trong khi dong goi, nen hai ban cung mot thiet ke van co bytes khac nhau — hash
chi dung de phat hiện khac, con muon ket luan `khop` thi phai doc het pixel.
Cua thu phan biet: notepad.exe cung duoc do va PHAI bao LECH.
"""

import hashlib
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO = os.path.join(REPO, "assets", "app-icon", "icon.ico")
BASE = os.path.join(os.environ["LOCALAPPDATA"], "Programs")


def newest(pattern):
    """Ban nao moi nhat trong build\\installer — ten file mang so version, nen
    khong duoc hardcode no vao day (mot lan bump lam gate do sai ban)."""
    import glob
    hits = sorted(glob.glob(pattern), key=os.path.getmtime)
    return hits[-1] if hits else pattern


TARGETS = {
    "Inno\\Clinging.exe": os.path.join(BASE, "Clinging", "Clinging.exe"),
    "MSI\\Clinging.exe": os.path.join(BASE, "ClingingMSI", "Clinging.exe"),
    "installer\\ClingingSetup.exe": newest(os.path.join(
        REPO, "build", "installer", "ClingingSetup-*.exe")),
    "bundle\\Clinging.exe": os.path.join(REPO, "dist", "Clinging", "Clinging.exe"),
    "_counterfactual notepad.exe": os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "System32", "notepad.exe"),
}
RT_ICON = 3
RT_GROUP_ICON = 14      # 24 la RT_MANIFEST, KHONG PHAI icon — do lan dau roi


def ico_images(blob):
    """[(w, h, sha256, n, payload)] cac anh trong mot file .ico.

    Header .ico la (reserved, type, count): count nam o offset 4, KHONG phai 2.
    Doc nham offset ay in ra "1 anh" va bo qua het khich thuoc lon.
    """
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("khong phai file .ico (reserved=%d type=%d)"
                         % (reserved, kind))
    out = []
    for i in range(count):
        off = 6 + 16 * i
        w = blob[off] or 256
        h = blob[off + 1] or 256
        size, data_off = struct.unpack_from("<II", blob, off + 8)
        image = blob[data_off:data_off + size]
        if len(image) != size:
            raise ValueError("ico cat ngat o anh %d" % i)
        out.append((w, h, hashlib.sha256(image).hexdigest(), len(image), image))
    return out


def _sections(data):
    e_lfanew = struct.unpack_from("<I", data, 0x3c)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("khong phai PE")
    nsec = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    # Data directory index 2 = resources; PE32+ tu offset 112, PE32 tu 96.
    dd = opt + (112 if magic == 0x20b else 96)
    rsrc_rva, rsrc_size = struct.unpack_from("<II", data, dd + 2 * 8)
    sec = opt + opt_size
    table = []
    for i in range(nsec):
        at = sec + i * 40
        name = data[at:at + 8].rstrip(b"\x00")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, at + 8)
        table.append((vaddr, max(vsize, rawsize), rawptr))
    if not rsrc_rva:
        raise ValueError("khong co .rsrc")
    return rsrc_rva, rsrc_size, table


def _rva_to_off(table, rva):
    for vaddr, vsize, rawptr in table:
        if vaddr <= rva < vaddr + vsize:
            return rawptr + (rva - vaddr)
    raise ValueError("RVA %d ngoai cac section" % rva)


def collect(sink, data, base, offset, table):
    """Cap TEN cua cay resource: moi ten co mot dir ngon ngu, lay payload dau.

    Cay la type -> name -> language -> data. Goi nay PHAI dung o cap name: o
    cap language thi `ident` la 1033 chu khong phai so thu tu anh, nen neu de
    no ghi chung vao sink thi min(groups) ra 1033 va ta doc nhom khong hop le.
    """
    at = base + offset
    named, ids = struct.unpack_from("<HH", data, at + 12)
    for i in range(named + ids):
        entry = at + 16 + i * 8
        ident, ref = struct.unpack_from("<II", data, entry)
        if ref & 0x80000000:
            # Dir ngon ngu: lay data entry dau tien (ngoi sao san pham le).
            lang_at = base + (ref & 0x7fffffff)
            lang_named, lang_ids = struct.unpack_from("<HH", data, lang_at + 12)
            for j in range(lang_named + lang_ids):
                lentry = lang_at + 16 + j * 8
                _lang, lref = struct.unpack_from("<II", data, lentry)
                if lref & 0x80000000:
                    continue
                sink[ident] = _data_entry(data, base, lref, table)
                break
        else:
            sink[ident] = _data_entry(data, base, ref, table)


def _data_entry(data, base, ref, table):
    rva, size = struct.unpack_from("<II", data, base + ref)
    start = _rva_to_off(table, rva)
    return data[start:start + size]


def resources(path):
    """{type: {id: bytes}} cho RT_ICON va RT_GROUP_ICON cua mot PE."""
    data = open(path, "rb").read()
    rsrc_rva, _rsrc_size, table = _sections(data)
    base = _rva_to_off(table, rsrc_rva)
    out = {RT_ICON: {}, RT_GROUP_ICON: {}}
    named, ids = struct.unpack_from("<HH", data, base + 12)
    for t in range(named + ids):
        entry = base + 16 + t * 8
        ident, ref = struct.unpack_from("<II", data, entry)
        if (ref & 0x80000000) and ident in (RT_ICON, RT_GROUP_ICON):
            collect(out[ident], data, base, ref & 0x7fffffff, table)
    return out, table, data


def group_images(path):
    """(group_id, [(w, h, sha256, n)] theo thu tu nhom, {id: payload})."""
    res, _table, _data = resources(path)
    groups = res[RT_GROUP_ICON]
    icons = res[RT_ICON]
    if not groups:
        raise ValueError("exe khong co RT_GROUP_ICON: " + path)
    group_id = min(groups)
    blob = groups[group_id]
    _reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    if kind != 1 or not (0 < count <= 32):
        raise ValueError("nhom icon %d khong hop le" % group_id)
    images = []
    for i in range(count):
        e = struct.unpack_from("<BBBBHHIH", blob, 6 + 14 * i)
        payload = icons.get(e[7])
        if payload is None:
            raise ValueError("thieu RT_ICON id=%d" % e[7])
        images.append((e[0] or 256, e[1] or 256,
                       hashlib.sha256(payload).hexdigest(), len(payload),
                       payload))
    return group_id, sorted(images, key=lambda r: r[1]), icons


def decode(payload):
    """Doc mot anh (PNG trong .ico hoac DIB trong resource) -> RGBA numpy HxWx4."""
    import io
    import numpy as np
    from PIL import Image
    blob = bytes(payload)
    try:
        img = Image.open(io.BytesIO(blob))
    except Exception:
        # RT_ICON cua nhieu exe la DIB khong co BITMAPFILEHEADER -> them 14 byte.
        header = b"BM" + struct.pack("<IHHI", 14 + len(blob), 0, 0, 14)
        img = Image.open(io.BytesIO(header + blob))
        img.load()
        # DIB cua icon co biHeight = 2*height (anh + AND mask), ep lai.
        if img.height == 2 * img.width:
            img = img.crop((0, 0, img.width, img.width))
    img = img.convert("RGBA")
    return np.asarray(img, dtype=np.int16)


def pixel_stats(a, b):
    """(mean abs diff tren RGB, so pixel peak lech > 16, tong pixel)."""
    import numpy as np
    if a.shape != b.shape:
        raise ValueError("hai anh khong cung kich thuoc: %s vs %s"
                         % (a.shape, b.shape))
    diff = np.abs(a[:, :, :3] - b[:, :, :3])
    peak = diff.max(axis=2)
    return (float(diff.mean()), int((peak > 16).sum()),
            int(peak.size), int(peak.max()))


def contact_sheet(cases, path):
    """Anh chung minh: moi hang = mot kich thuoc, cot = nguon | trong exe | lech x8."""
    from PIL import Image
    tile = 256
    pad = 6
    sheet = Image.new("RGBA", (pad + 3 * (tile + pad),
                               pad + len(cases) * (tile + pad)), (30, 30, 38, 255))
    for row, (size, src_png, exe_png, diff_png) in enumerate(cases):
        for col, png in enumerate((src_png, exe_png, diff_png)):
            img = Image.open(png).convert("RGBA")
            img.thumbnail((tile, tile), Image.NEAREST)
            canvas = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
            canvas.paste(img, ((tile - img.width) // 2,
                               (tile - img.height) // 2), img)
            sheet.paste(canvas, (pad + col * (tile + pad), pad + row * (tile + pad)),
                        canvas)
    sheet.save(path, "PNG")
    return path


def main():
    import numpy as np
    from PIL import Image
    src = {(w, h): payload for w, h, _s, _n, payload in
           ico_images(open(ICO, "rb").read())}
    print("nguon assets/app-icon/icon.ico: %d kich thuoc %s"
          % (len(src), sorted(src)))
    verdicts = {}
    sheet_cases = []
    for label, path in TARGETS.items():
        if not os.path.isfile(path):
            print("\n%-32s KHONG CO FILE" % label)
            continue
        try:
            group_id, images, all_icons = group_images(path)
        except ValueError as exc:
            # Khong co RT_GROUP_ICON la mot LECH that (notepad cua may nay la
            # stub), khong phai loi cua detector: dung bien thanh ban do, im
            # lang crash se xoa mat ca anh chung minh.
            print("\n%-32s LECH - %s" % (label, exc))
            verdicts[label] = False
            continue
        print("\n%-32s nhom #%d, %d RT_ICON" % (label, group_id, len(all_icons)))
        rows = []
        for size, _h, _sha, n, payload in images:
            key = (size, size)
            if key not in src:
                print("   %3dx%d %7d B  KHONG CO ANH NGUON CUNG KICH THUOC"
                      % (size, size, n))
                verdicts[label] = False
                continue
            a, b = decode(src[key]), decode(payload)
            mean, bad, total, peak = pixel_stats(a, b)
            frac = 100.0 * bad / total
            verdict = mean <= 1.0 and frac <= 0.2
            print("   %3dx%d  exe %7d B / nguon %7d B  mean %.3f  peak %3d  "
                  "lech>16: %.3f%%  %s"
                  % (size, size, n, len(src[key]), mean, peak, frac,
                     "khop" if verdict else "LECH"))
            rows.append((size, verdict, a, b))
        ok = bool(rows) and all(r[1] for r in rows)
        verdicts[label] = ok and len(rows) == len(src)
        if sheet_cases is not None and label.startswith("Inno"):
            out_dir = os.path.join(REPO, "scratch")
            for size, _v, a, b in rows:
                src_png = os.path.join(out_dir, "icon_src_%d.png" % size)
                exe_png = os.path.join(out_dir, "icon_exe_%d.png" % size)
                dif_png = os.path.join(out_dir, "icon_diff8x_%d.png" % size)
                Image.fromarray(a.astype(np.uint8), "RGBA").save(src_png)
                Image.fromarray(b.astype(np.uint8), "RGBA").save(exe_png)
                d = np.clip(np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2) * 8,
                            0, 255).astype(np.uint8)
                alpha = np.clip(a[:, :, 3], 0, 255).astype(np.uint8)
                Image.fromarray(np.dstack([d, d, d, alpha]), "RGBA").save(dif_png)
                sheet_cases.append((size, src_png, exe_png, dif_png))
    cf = verdicts.get("_counterfactual notepad.exe")
    print("\ncounterfactual: notepad bi bao LECH = %s" % (cf is False))
    shipped = [v for k, v in verdicts.items() if "notepad" not in k]
    ok = bool(shipped) and all(shipped) and cf is False
    if sheet_cases:
        print("anh chung minh: %s" % contact_sheet(
            sheet_cases, os.path.join(REPO, "scratch", "icon_compare.png")))
    print("%s" % ("EXE DA CAI MANG DUNG BIEU TUONG MOI" if ok
                  else "KHONG DAT - xem dong LECH o tren"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
