# Khuôn mẫu phản chứng (copy được, đã chạy thật trong repo này)

Mọi đoạn dưới đây lấy từ probe đang sống; đường dẫn trong ngoặc là nơi tham khảo
bản gốc. Bốn khuôn covers gần hết các loại gate.

## 0. Khung check dùng chung

```python
FAILS = []

def check(label, got, want):
    ok = got == want
    print("%-58s %s%s" % (label, "PASS" if ok else "FAIL",
                          "" if ok else "  got=%r want=%r" % (got, want)))
    if not ok:
        FAILS.append(label)
    return ok

# ...cuoi file:
print("\n%s  (%d fail)" % ("ALL PASS" if not FAILS else "CO FAIL", len(FAILS)))
sys.exit(1 if FAILS else 0)
```

In ra **số đo được**, không phải tính từ: `1402 glyph`, `362 file`, `rc co
kiem tra=1 | rc khong kiem tra=3221226505`. (`scratch/gate_discrimination_probe.py`)

## 1. Đổi MỘT hằng số đầu vào của gate

Gate gốc được chép sang file tạm, `str.replace` đúng một dòng, chạy bằng lệnh y hệt
lệnh người dùng, rồi xóa. Dùng khi nghi ngờ gate xanh vì nó không nhìn thấy gì.

```python
src = open(AUDIT, encoding="utf-8").read()

def variant(old, new):
    path = os.path.join(ROOT, "scratch", "_audit_variant.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src.replace(old, new, 1))
    try:
        return run_py(path)          # subprocess, KHONG phai exec trong land nay
    finally:
        os.remove(path)

rc_v, out_v = variant('DIR_ROOTS = ("ui", "widgets", "core")',
                      'DIR_ROOTS = ("ui", "widgets", "core", "theme")')
check("them goc 'theme' khong ton tai -> RED", rc_v, 1)
check("RED vi dung ly do", "khong co file .py nao" in out_v, True)
```

Hai điều phải có: rc **và** chuỗi thông báo nói đúng lý do. rc=1 vì một lỗi khác
không chứng minh gì. Chạy bằng subprocess chứ không `exec`: `exec` hai lần trong
một land sẽ `RuntimeError: Please destroy the QApplication singleton`, và subprocess
mới là đúng lệnh sản xuất.

## 2. Cắm một file nguồn THẬT, rồi nhổ ra

Dùng khi gate quét mã nguồn. Đây là đường that của app, không phải đầu vào bịa.

```python
BAD = os.path.join(ROOT, "ui", "_gate_probe_bad_icon.py")
try:
    open(BAD, "w", encoding="utf-8").write(
        'from widgets.common import _qta\n'
        'ICON = _qta().icon("fa6s.khong-co-that-xyz", color="#FFFFFF")\n')
    rc_b, out_b = run_py(AUDIT)
    check("ten glyph gia trong ui/ -> audit RED", rc_b, 1)
    check("audit goi ten ro fa6s.khong-co-that-xyz",
          "fa6s.khong-co-that-xyz" in out_b, True)
finally:
    os.remove(BAD)
rc_after, _ = run_py(AUDIT)
check("cat tep gia di roi audit lai xanh (khong de lai rac)", rc_after, 0)
```

Bản "sau khi nhổ" là bắt buộc: nó chứng minh probe không để lại rác — tức điều
kiện "loại bỏ rác" của repo.

## 3. Xóa vật lý, không so số tự biến

Dùng cho gate đếm file / so cây thư mục.

```python
shutil.copytree(tmp_src, tmp_cut)
os.remove(os.path.join(tmp_cut, "_internal", "c"))
a, b = count_files(tmp_src), count_files(tmp_cut)
loose = lambda n, d: n >= d - 2        # dang nguong: cho phep sot file
check("cat 1 file thi cua moi do, cua dang nguong thi khong",
      (loose(b, a), (b == a and a >= 300)), (True, False))
```

Kèm bảng sự thật khi gate cũ là một ngưỡng: liệt kê case mà **cũ xanh, mới đỏ**
(bản còn qtawesome 404 file; MSI thiếu 1 component) và case **cả hai đỏ**
(`0 == 0` — "xanh rỗng"), rồi assert `(old, new)` cho từng dòng.
(`scratch/msi_install_probe.py`, `scratch/gate_discrimination_probe.py:110-149`)

## 4. Chèn lại dòng vừa xóa và so đầu ra

Dùng để chứng minh một thay đổi **vô nghĩa về hành vi** (xóa import trùng, refactor),
hoặc ngược lại chứng minh một dòng vừa thêm là dòng sống.

```python
pre = src.replace("    img.fill(0)\n    painter = QPainter(img)",
                  "    img.fill(0)\n    from PySide6.QtGui import QPainter\n"
                  "    painter = QPainter(img)")
mod = types.ModuleType("phien_ban_truoc_sua"); mod.__file__ = FA_SRC
exec(compile(pre, FA_SRC, "exec"), mod.__dict__)

def signature(module):                      # hash tren BYTE RGBA that
    h = hashlib.sha256()
    for name in sorted(module.names()):
        for px in (16, 24, 32):
            img = module._render("fa6s." + name, px, "#40E0D0")
            h.update(("%s@%d" % (name, px)).encode())
            h.update(bytes(img.constBits()[:img.sizeInBytes()]))
    return h.hexdigest()[:16]
check("RGBA 1402 ten x 3 kich thuoc: truoc sua == sau sua",
      signature(fa), signature(mod))
```

Đảo ngược khuôn này chính là cách tìm ra lỗi thật 2026-10-20: cắt một dòng
`glyph_for(name)` khỏi `widgets/fontawesome.py:191` trong một child script rồi chạy
→ có dòng thì rc=1 + `ValueError` tại chỗ gọi; cắt dòng thì log hiện `Error calling
Python override of QIconEngine::pixmap()`. **Không gate trên mã exit của bản cắt**:
đo 6 lần thì 2/3 abort `0xC0000409` (3221226505), 1/3 rc=1 — Qt quyết định lần nào
kịp ném exception qua biên. Chuỗi log mới là bất biến (3/3 bản cắt, 0/3 bản gốc);
in cả hai mã ra để làm số đo, nhưng assert trên chuỗi. Không có phép thử đó thì
"thêm kiểm tra cho chắc" chỉ là prose.

## 5. Ảnh chứng minh cho render

Ảnh phải do code path sản xuất dựng, và phải được mở ra xem.

```python
pm = widget.grab()                       # hoac scene -> QImage -> QPixmap
pm.save(os.path.join(ROOT, "scratch", "ten_evidence.png"))
```

Ràng buộc đã trả giá: ảnh DPR>1 phải blit vào `QRect` theo device size, đừng
`drawPixmap(x, y, pm)` trên QImage DPR-1 (co còn 80%, ăn cả dấu trừ); grab widget
cha khi có hiệu ứng opacity, chỉ grab **sau khi** fade kết thúc và **không** grab
sau `hide()+show()`; đo một dải (strip) trên chính ảnh của nó chứ không trên ảnh của
cả dialog; `QT_QPA_PLATFORM=offscreen` trên máy này cho 0 font family nên chữ luôn
là tofu — chỉ phán bố cục. Gate ảnh thì đếm pixel alpha, không đếm `isNull()`.

## 6. Không đụng dữ liệu người dùng

```bash
python scratch/user_data_snapshot.py capture scratch/_snap_before.json
<lenh do>
python scratch/user_data_snapshot.py capture scratch/_snap_after.json
python scratch/user_data_snapshot.py diff scratch/_snap_before.json scratch/_snap_after.json
```

Fingerprint mỗi file = `[mtime_ms, size, sha256[:16]]`. **Size bằng nhau mà mtime
đổi là MỘT LẦN GHI**, không phải nhiễu. APPDATA của run-from-source phải là
APPDATA THẬT (site-packages của user nằm trong `%APPDATA%\Python\...`); APPDATA tạm
chỉ dùng cho exe đã cài, vì app ghi đè `recent_projects.json` ngay khi mở.

## 7. Checklist "xanh giả"

- Đầu vào của gate có tồn tại không? (`os.walk` gốc sai trả 0 file im lặng)
- Con số trong check có lấy từ artifact thật không, hay là hằng số nhớ từ lần build trước?
- rc có đọc từ subprocess của chính lệnh đó không?
- Ảnh có được mở ra xem chưa, và nó có phải dựng từ code path vừa sửa không?
- Probe có để lại file / cửa sổ sống không?
- Run có bị coi là xanh khi thực ra là `rc=127` sau in `ALL PASS` không?
