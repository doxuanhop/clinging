---
name: gate-counterfactual-evidence
description: Verify a change in the Clinging repo the way this project requires — a gate that runs the real production command (main.py --selftest / --*-report, dist exe, installed exe), a counterfactual that proves the gate goes RED for exactly the right reason, an evidence PNG for anything that renders, and the tool's own exit code read from subprocess (not bash's 127). Use when fixing or extending Clinging code, when asked "co gate + anh chung minh", "phan chung", "chay lai selftest", "verify with evidence", or before claiming a bug is fixed / a build is shippable.
argument-hint: <duong danh module da sua hoac lenh gate>
---

# Gate → phản chứng → ảnh → rc thật

## Overview

Bốn bước bắt buộc cho mọi thay đổi ở Clinging. Thiếu một bước thì báo cáo là
"chưa xong", dù code chạy đúng trên máy người viết. Chi tiết đầy đủ:
`docs/verification-gates.md`; hợp đồng repo: `AGENTS.md`.

## Khi nào dùng

- Sau khi sửa `ui/`, `widgets/`, `core/`, `diagnostics.py`, `main.py`, `theme.py`.
- Trước khi nói "đã sửa xong lỗi X".
- Trước khi dựng bundle / installer / đẩy asset Release.
- Khi bị hỏi "gate của cái này là gì?" cho một thay đổi đã tồn tại.

## Bước 1 — Gate trên đúng đường production

Gọi **chính lệnh người dùng gọi**. Không tự dựng đầu vào, không viết bộ mô phỏng.

```bash
python main.py --selftest                 # 38 dong, JSON co "failed": [...]
python main.py --selftest out.json --only="chinh mau"   # mot dong (~5 s vs ~31 s); payload["only"] != null => KHONG duoc bao cao la du bang
python main.py --startup-report           # boot tung pha + control cung land
python scratch/icon_name_audit.py         # ten glyph + tham so tren toan bo nguon
dist/Clinging/Clinging.exe --selftest     # bundle that
python scratch/installed_app_probe.py     # app da cai
```

Gate tốt in ra **số đo được** (`1402 glyph`, `362 file`, `625 pixel khong trong`),
không in "OK". Gate mới viết thì thêm một dòng `check()` vào probe hiện có, không
sáng tạo framework thứ hai.

## Bước 2 — Phản chứng: gate phải ĐỎ vì ĐÚNG lý do

Với mỗi gate vừa dựa vào, chọn một khuôn trong `references/recipes.md`:

1. Đổi **một** hằng số đầu vào của gate, chạy bản chép, đòi rc≠0 **và** chuỗi thông
   báo nói đúng lý do.
2. Cắm một **file nguồn thật** chứa lỗi (`ui/_*_probe_bad_*.py`), đòi chính gate gốc
   báo đỏ, nhổ ra, đòi xanh lại.
3. Xóa **vật lý** một file / cắt một component, đòi gate đếm được.
4. Chèn lại dòng vừa xóa và so đầu ra (hash byte RGBA, pixel, văn bản) — chứng minh
   thay đổi vô nghĩa, hoặc chứng minh dòng vừa thêm là dòng sống.

Cấm kết luận bằng prose. "Gate này chắc vẫn bắt được" không phải chứng cứ.
Chạy gộp tất cả: `python scratch/gate_discrimination_probe.py`.

## Bước 3 — Ảnh cho thứ gì đó render

```python
widget.grab().save("scratch/<ten>_evidence.png")   # tu code path SAN XUAT
```

Rồi **mở ảnh lên xem** (Read tool) trước khi báo cáo. Đếm alpha
(`(pixel >> 24) & 0xFF`), đừng gate bằng `isNull()` — icon không `color=` từng
non-null mà zero pixel. Bẫy DPR/offscreen/opacity/grab-sau-hide:
`references/recipes.md` mục 5.

## Bước 4 — Đọc rc của chính công cụ

```bash
python .qoder/skills/gate-counterfactual-evidence/scripts/true_rc.py python main.py --selftest
```

`true_rc.py` in `rc=<dec> (0x<hex>)` kèm dịch nghĩa và độ dài stdout/stderr. Nó tồn
tại vì: Qt callback trở exception → process chết, Git Bash báo **127** trong khi
stdout cuối vẫn đọc `ALL PASS`; stdout đã buffer thì **mất trắng** (`stdout=0 B`).
Chiều ngược lại cũng phải nhớ: **đừng lấy mã exit làm điều kiện phân biệt** nếu nó là mã abort —
`0xC0000409` và `rc=1` xen kẽ nhau trên cùng một đầu vào (đo 6 lần: 2 abort / 1 rc=1).
Bất biến để assert là nội dung log; mã exit chỉ in ra để đọc.

## Bước 5 — Không đụng dữ liệu người dùng

```bash
python scratch/user_data_snapshot.py capture scratch/_snap_before.json   # TRUOC khi do
# ...do dac (selftest / probe / exe da cai)...
python scratch/user_data_snapshot.py capture scratch/_snap_after.json
python scratch/user_data_snapshot.py diff scratch/_snap_before.json scratch/_snap_after.json
```

Chạy từ nguồn với **APPDATA THẬT** (site-packages của user nằm trong `%APPDATA%\Python`;
sandbox APPDATA làm `import cv2` chết và selftest đỏ oan). APPDATA tạm chỉ dùng khi đo
exe đã cài — app ghi đè `recent_projects.json` ngay lúc mở. Size bằng nhau mà mtime
đổi = MỘT LẦN GHI.

## Kết thúc phải trình

1. Lệnh gate xanh + rc thật (dòng `rc=...`).
2. Phản chứng đỏ + chuỗi lý do + case đã nhổ/sạch rác.
3. Đường dẫn ảnh đã mở xem, và nói rõ ảnh cho thấy gì.
4. `user_data_snapshot.py diff` = 0/0/0.
5. Chênh lệch còn lại giữa `src` ↔ `dist\Clinging` ↔ installer ↔ Release asset, nếu có.

## Dấu hiệu "run không hợp lệ" (không được tính là PASS)

- rc lấy qua đường ống, hoặc wrapper chạy nền báo 0.
- rc=127 trên probe in `ALL PASS` → probe để window sống, hoặc là fastfail thật.
- Probe không in ra con số nào: xanh trên mẫu rỗng.
- Gate so với hằng số tự nhập thay vì với artifact đang có trên đĩa.
- Đầu vào không tồn tại mà gate vẫn "quet sach".
- Ảnh cũ dựng từ lần chạy trước được đem ra làm bằng chứng cho lần chạy này.

## Resources

- `scripts/true_rc.py` — chạy một lệnh, in mã thoát thật + dịch nghĩa + cảnh báo log trống.
- `references/recipes.md` — 7 khuôn code copy-được (check harness, variant, cắm file
  thật, xóa vật lý, chèn lại dòng, ảnh, snapshot user data, checklist xanh giả).
- Trong repo: `scratch/gate_discrimination_probe.py` (31 check, bản mẫu hoàn chỉnh),
  `diagnostics.py` (`run_selftest`, `_font_icon_ok`, `_recent_readonly_ok`),
  `docs/verification-gates.md`, `docs/glyph-icons.md`, `AGENTS.md`.
