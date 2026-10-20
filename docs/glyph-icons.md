# Icon: bộ vẽ glyph Font Awesome cục bộ

## Vì sao không còn qtawesome

`import qtawesome` một mình tốn **0,62 s** trong cửa sổ boot của máy cấu hình thấp
này, và cả seam icon là **0,86 s** so với **0,044 s** của bộ vẽ cục bộ — kèm
~29 MB RAM private (đo bằng đồng hồ đặt TRONG `main._boot()`, xem
`scratch/boot_low_spec_probe.py`, `scratch/qtawesome_cost_probe.py`). Phần lớn
không phải cost vẽ glyph: qtawesome kéo theo `qtpy` và
`PySide6.QtOpenGL` / `QtDataVisualization` — 20 module không ai dùng. Vẽ thật chỉ
0,043 s cho 13 icon có mặt trong boot.

Số đó chỉ có giá trị khi control nằm cùng một lần chạy. `--startup-report` in
`nhe_s` / `nang_s`, trong đó `nang_s` là qtawesome bị kéo qua đúng cùng một seam;
so wall clock giữa hai lần chạy trên HDD máy này luôn tạo ra "tiết kiệm" giả.

## Các mảnh

| Đường | Vai trò |
| --- | --- |
| `widgets/fontawesome.py` | `QIconEngine` vẽ glyph từ TTF; API `icon(name, color=...)` giống qtawesome |
| `assets/icons/fontawesome6-solid-6.7.2.ttf` | Font, byte-identical với bản qtawesome (md5 do script in ra) |
| `assets/icons/fontawesome6-solid-charmap.json` | 1402 tên → codepoint, dump từ charmap của qtawesome |
| `scratch/make_icon_assets.py` | Trích font + charmap từ qtawesome, in bảng chứng (số byte, md5, số tên) |
| `widgets/common.py:_qta()` | Seam lười: ~60 chỗ trong UI gọi `_qta().icon(...)`, đổi backend không phải chạm lại UI |
| `ClingingQt.spec` | `excludes` có `qtawesome`; `assets/icons` đi theo `datas` |

Kết quả đo sau đổi: selftest 28 dòng `failed: []` (dòng `font icon` báo
`1402 glyph, 3 font icon ve 625 pixel khong trong`), boot tới cửa sổ 1,874 s,
RAM tại cửa sổ 78.436 KiB, payload bundle 362 file.

## Ràng buộc kỹ thuật phải nhớ khi sửa

1. **Không import gì ngoài PySide6 ở đầu file.** Thứ cần cắt chính là thời gian
   import; module phải trong veo lúc `import`.
2. **Phải là `QIconEngine`, không phải `QIcon` subclass.** `QAction.icon()` trả về
   bản copy đã bị cắt mất lớp con, pixmap ra rỗng. Engine thì được QIcon giữ con
   trỏ nên copy vẫn vẽ đúng.
3. **`pixmap()` không được nhân DPR lần nữa.** Qt đã scaling kích thước theo
   device pixel ratio trước khi gọi engine (`QIcon.pixmap(16)` trên màn 1,25x đến
   engine bằng `QSize(20,20)`); nhân tiếp sẽ to hơn qtawesome và lệch từng pixel
   khi đối chiếu.
4. **Tên glyph phải kiểm tra trong `icon()`, tức trong land của Python.** Vẽ xảy
   ra trong callback C++ của `QIconEngine`; một exception bật lên từ đó không qua
   được biên C++, nên process chết mà không ai bắt được nữa (stdout đã buffer thì
   mất trắng). `widgets/fontawesome.py:191` gọi `glyph_for(name)` ngay trước khi
   dựng engine là vì vậy. `scratch/gate_discrimination_probe.py` phần 4 chứng minh
   bằng cách cắt đúng một dòng đó: bản có kiểm tra thì rc=1 + `ValueError` tại chỗ
   gọi, bản cắt thì log hiện `Error calling Python override of
   QIconEngine::pixmap()`. **Mã thoát của bản cắt không ổn định** — đo 6 lần (3/3)
   thì 2 lần abort `0xC0000409` (đọc qua `subprocess.run` là 3221226505), 1 lần
   rc=1; chỉ dòng log là bất biến, nên gate phải bắt trên chuỗi đó chứ không trên
   một mã exit.
5. **Chỉ nhận `color=`.** Tham số lạ (`rotation=`, `options=`)raise, thà chết rõ
   còn hơn im lặng vẽ hình không xoay.
6. **Font nạp qua `QFontDatabase`, cần `QGuiApplication` đã tồn tại.** Gọi
   `icon()` trước `QApplication()` là abort im lặng (một dạng rc=127 khác trên
   máy này).

## Chính sách icon của UI

- Không emoji trong chrome UI. Emoji phụ thuộc font hệ thống: cùng một bản dựng
  hiện khác nhau trên mỗi máy và không đổi màu theo theme. Mọi nút/menu đi qua
  `widgets/common.py:font_icon()` / `icon_pixmap()`.
- Toàn bộ tên đang dùng trong repo là `fa6s.*` (kiểm bằng
  `scratch/icon_name_audit.py`), nên bộ vẽ chỉ cần Solid. Muốn thêm `fa6r.*` hoặc
  `fa6b.*` thì mở rộng `PREFIX`/charmap trong `scratch/make_icon_assets.py`, không
  viết thêm bộ vẽ thứ hai.
  Ngoại lệ duy nhất: `diagnostics.py` cố tình dùng `fa6b.paintbrush` làm tên giả để
  test đường báo lỗi.
- Sticker legacy (hình dán trong dự án) là emoji thật, được phép.

## Cổng kiểm chứng

```bash
python scratch/icon_name_audit.py            # ten + tham so, tren dung danh sach goc nguon
python main.py --selftest                    # dong "font icon": ve pixel va do alpha
python scratch/gate_discrimination_probe.py  # phan chung cua audit + cua raster
python scratch/icon_parity_probe.py          # anh doi chieu ta vs qtawesome
```

`icon_name_audit.py` quét `DIR_ROOTS = ("ui", "widgets", "core")` và
`SINGLE_FILES = ("theme.py", "main.py")`, và **chết nếu một gốc không có file
.py nào**. Bài học: `theme` là FILE, `os.walk()` trên một gốc không tồn tại trả về
0 file im lặng, khiến audit tự xưng "quet sach" trong khi hai file nguồn chưa bao
giờ được đo.

Dòng `font icon` trong selftest không chỉ đếm tên: nó vẽ và gate trên **alpha**
(`(pixel >> 24) & 0xFF`), vì một icon không có `color=` từng trả về QIcon non-null
nhưng không một pixel nào. Đừng bao giờ gate bằng `isNull()`.

Ảnh chứng minh: `scratch/icon_parity.png` (ta vs qtawesome, cùng tên cùng cỡ),
`scratch/icon_sheet.png`, `scratch/fonticon_{home,editor,toolbar,dialog,menu,...}.png`.

## Trạng thái artifact (2026-10-20, chốt cho 1.0.2)

`dist\Clinging` và hai installer 1.0.2 **đã mang đúng nguồn hiện tại**: không còn
qtawesome trong payload (bảng File của MSI đọc ngược ra từ file `.msi`, đối từng
tên với `dist` — `scratch/msi_payload_check.py`), icon do `widgets/fontawesome.py`
vẽ từ TTF, và đường báo lỗi tên glyph sớm cũng nằm trong bundle. Hai sửa đổi nguồn
làm sau bản 1.0.1 local (xóa một dòng `import QPainter` thừa — vo nghia, đã chứng
minh bằng SHA-256 trên byte RGBA của 1402 tên × 16/24/32 px, cùng dấu
`dd4ab2c944327ae2` hai bên; và thêm dòng kiểm tên sớm) nay đã được dựng thật.
Release v1.0.1 trên GitHub vẫn là bundle chứa qtawesome; bản không-có-qtawesome đầu
tiên phát hành là v1.0.2.

## Liên quan

- `docs/verification-gates.md` — quy tắc gate / phản chứng / ảnh / rc.
- `docs/release-1.0.1.md` — đường dựng và cách xác minh artifact đã cài.
