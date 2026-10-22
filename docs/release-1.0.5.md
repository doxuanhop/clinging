# Clinging 1.0.5

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir; toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg nằm bên trong bundle.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.5.exe` | 141.574.633 B | `2abf1a981e5279a08e5e47a161b74ea756ce19c50bd2872a473837d60b825902` |
| `ClingingSetup-1.0.5.msi` | 161.113.765 B | `0edaef1b3c8ee9b31fdd62b73f6c50d1348b0865cd8cfd5a564642057122986c` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.5.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục Add/Remove Programs, tự xoá `_internal`
  cũ khi nâng cấp. Cài vào `%LOCALAPPDATA%\Programs\Clinging`.
- `.msi` (WiX 3.11) — triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.
  `INSTALLFOLDER` mặc định của package **trùng thư mục của bản Inno**, nên muốn hai
  bản cùng tồn tại thì phải gọi rõ:
  `msiexec /i ClingingSetup-1.0.5.msi INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`.

## Thay đổi so với 1.0.4

Bốn nhóm. Mỗi nhóm vẫn theo hợp đồng 4 bước: cổng chạy trên đúng lệnh người dùng
gọi, phản chứng chứng minh cổng đỏ vì **đúng** lý do, ảnh cho phần render, và mã
thoát đọc từ chính công cụ. Selftest: **38 → 39 dòng**, `failed=[]`, `rc=0`.

### Cắt thành nhiều đoạn: ba kiểu trên một hộp thoại

Trước bản này, "Cắt thành nhiều đoạn…" chỉ chia **đều** theo số đoạn. Nay chọn
kiểu ngay trong hộp thoại:

| Kiểu | Nhập | Việc nó làm |
| --- | --- | --- |
| **Chia đều** | số đoạn | như cũ |
| **Độ dài cố định** | giây mỗi đoạn | cắt hết nguồn thành đoạn bằng nhau, phần dư ghép vào đoạn cuối |
| **Mốc tự đặt** | chuỗi `0:01.5, 0:03.25, 5.95, …` | cắt đúng tại các mốc; mốc ngoài khoảng Từ→Đến hoặc hai mốc sát nhau dưới 0,20 s bị **báo** chứ không âm thầm bỏ |

Ba cột nhập đổi theo kiểu; `_plan_args()` trả đúng một từ khoá cho kiểu đang chọn;
kiểu mốc không còn mốc hợp lệ nào thì hộp thoại **từ chối chạy** thay vì lặng lẽ
cắt đều. Toàn bộ số học nằm trong `core/media_splitter.py:build_boundaries()`.

Cổng đo trên **file thật**, không đọc lời khai của hàm lập mốc: `span` từng đoạn,
`ffprobe` mở lại từng file, tổng `span` khớp thời lượng nguồn (±0,05 s), mỗi mối
nối khít (`start[i] == start[i-1] + span[i-1]`, ±1e-6). Dòng selftest cắt cả ba
kế hoạch ra đĩa → `3 kieu cat (deu/doi dai/moc) ra 8 doan that, tong span = nguon,
ffprobe doc lai duoc` (8 = 2 + 2 + 4, trong đó chuỗi nhập 8 token còn 4 mốc hợp lệ).

Phản chứng: `scratch/split_plan_counterfactual.py` — 14 phép đổi byte trên
`core/media_splitter.py`, **14/14 PHÂN BIỆT**, `ALL PASS`, rc=0, ~2,2 phút.
Probe hiện trường: `scratch/media_split_probe.py` — **167 cửa, ALL PASS (0 fail)**,
rc=0, 78,6 s. Ảnh `scratch/media_split_evidence.png` (ba kiểu, mỗi kiểu hàng đoạn +
file trên đĩa) và `scratch/media_split_dialog_points.png` (600×602, hộp thoại "Mốc
tự đặt" với cả ba dòng giải thích).

Đi kèm là một sửa giao diện: thân hộp thoại kiểu mốc cần 492 px trong khi
`resize(600, 520)` chỉ cho viewport 410 px, nên dòng "1 mốc bị bỏ vì…" — dòng
**duy nhất** nói người dùng nhập sai ở đâu — nằm gấp dưới fold và `grab()` của
probe không nhìn thấy. `SplitDialog._fit_height()` giờ chỉ LỚN LEN theo
`sizeHint()` thật, và cổng đo `verticalScrollBar().maximum() == 0` ở bốn trạng thái
(deu / độ dài / mốc / kết quả).

### Xuất theo vùng in/out + bốn preset chất lượng

Hộp thoại Xuất thêm cửa sổ `Từ → Đến` (kèm chế độ toàn bộ) và bốn preset lấy từ
số đo chứ không từ cảm tính (`scratch/export_quality_cost_probe.py` →
`scratch/export_quality_cost.json`, 1280×720@30, 2,0 s, 2 vòng, 8 cấu hình):

| Preset | Đo trên máy này | Ghi chú |
| --- | --- | --- |
| CRF 18 `medium` | 1,938 s / 1.151.616 B | chuẩn chất lượng |
| CRF 21 `medium` | 1,865 s / **0,777×** byte | mặc định mới |
| CRF 24 `medium` | 2,134 s / **0,563×** byte | nhẹ hơn nữa |
| CRF 23 `veryfast` | **0,541×** thời gian / 0,558× byte | khi cần nhanh |

`ultrafast` **bị loại dù nhanh nhất** (0,712 s) vì nó phình tệp lên **1,542×**.

Cổng (dòng 39) có bảy khúc, trong đó năm khúc chạm `export_range` trên giấy:
`MIN_WINDOW_FRAMES = 2`, `span` sinh từ `frames / fps` chứ không từ hiệu hai số
nhập tay, **hai đầu đều bị kẹp** (`-5 → 0` và `1,0 → 999 → 1,4 s`); `RenderWorker`
phải đi qua seam; năm lần **xuất thật** đo lại bằng `ffprobe -count_frames` +
`os.path.getsize`; vùng phải là **cắt** của toàn bộ (giải mã cả file theo chỉ số
khung hình và so hue từng khung: mọi `cat` ≤ 15°, mọi `dau` > 20°); preset đổi thật
số byte trên cùng nội dung. Chi tiết đo được: `24 frame/2.40s toan bo ... vung
1.20s = 12 frame cat cua no (lech mau [2.5, 1.5, 6.6, ...] do <=15), tieng 6 f RMS
0.0880 vs tam 6 f RMS 0.0067 (13.2x), CRF24 18191 B < CRF18 30525 B cung frame`.

Phản chứng: `scratch/export_range_counterfactual.py` — 18 phép đổi byte trên **ba**
file nguồn thật (`core/export_range.py`, `ui/export_dialog.py`, `diagnostics.py`),
**18/18 PHÂN BIỆT**, `ALL PASS`, rc=0, 178,0 s; SPOT đủ bảng
`rc=1 rows=39 failed=['vung xuat in/out + preset chat luong']`, khôi phục
`rc=0 rows=39 failed=[]`. Hai vết đỏ bằng lời của chính người dùng: nhãn in ra
`'Thời lượng: 00:00 / 00:02'` (nên phải in con số giây + khung hình), và
`tieng: 6 frame/1.2 s thay vi 6/0.6 s` (nên `-ss` phải đi vào lệnh xuất video).
Ảnh `scratch/export_range_evidence.png` (1560×1380): `ExportDialog` THẬT ở
1120×520 cho cả hai chế độ, 24 + 12 khung giải mã thật kèm hiệu số hue, bảng
`ffprobe -count_frames` của năm tệp, RMS hai cửa sổ.

### Sửa lỗi đi kèm

- **`-shortest` ăn mất đoạn cuối.** Đường mux audio/video kết thúc bằng
  `-shortest`, nên một vùng xuất có ảnh dài hơn tiếng bị **cắt cụt** mà không một
  cổng nào nhìn thấy. Bây giờ độ dài do `export_range` quyết (`-t`), `-shortest`
  ra khỏi lệnh.
- **`--split-report` của bản đóng gói tự trả 0.** Bản 1.0.4 dựng từ cùng tree
  nguồn vẫn giữ hằng số cũ `len(menu_actions) == 2` trong bundle — thang đo bị
  đóng gói cùng sản phẩm — nên exe 1.0.4 đã cài khi đó đỏ rc=1 trên một app cắt
  **đúng** (3 đoạn, mối nối 0,0, lệch màu 0,0). Lần dựng này đưa thang đo mới vào
  payload: `dist\Clinging\Clinging.exe --split-report` → **rc=0**, `failed=[]`,
  `menu_actions` ba hành động theo đúng thứ tự — và bản 1.0.5 đang cài trên máy
  phát triển cũng trả **rc=0** (xem mục Lưu ý).
- **Số phát hành bốn thành phần bị chặn ngay từ nguồn.** `1.0.4.1` nghe như một
  bản vá hợp lệ, nhưng `ProductVersion` của Windows Installer chỉ định nghĩa
  `a.b.c`: đo 22/10/2026, hai package probe cùng UpgradeCode (1.0.4 rồi 1.0.4.1)
  khiến `MsiEnumRelatedProducts` trả về **CẢ HAI** ProductCode — `MajorUpgrade`
  không coi số bốn thành phần là mới hơn nên không bao giờ gỡ bản cũ. WiX 3.11 thì
  `candle`/`light` vẫn ngon lành và ghi nguyên văn `1.0.4.1` vào bảng Property, tức
  lỗi chỉ lộ ra lúc cài. `scratch/release_meta.py:source_versions()` giờ chết tại
  chỗ: `filevers`/`prodvers` có thành phần thứ 4 khác 0 là `SystemExit`. Phản chứng
  bằng một vết byte duy nhất (`filevers=(1, 0, 5, 1)`) → rc=1 đúng dòng đó, khôi
  phục → rc=0. Vì vậy bản vá này mang số **1.0.5**.

## Lưu ý

- **Chưa ký số.** SmartScreen có thể hiện *"Windows protected your PC"* — chọn
  *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính SHA-256 ở bảng trên.
- **Cổng chạy trên bundle thật, không phải tree nguồn.**
  `dist\Clinging\Clinging.exe --selftest`: **39 dòng, `failed=[]`, `only=null`,
  rc=0**. `--startup-report` của cùng exe đó: `ok=True`, **cả chín cửa `True`**
  (`boot_khong_cv2`, `boot_khong_keo_trang_dung`, `boot_khong_psutil`,
  `boot_khong_keo_nen`, `bia_duoc_ve`…), working set **68.992 KiB** ngay lúc cửa sổ
  hiện, cửa sổ hiện lúc **0,7454 s**; lần chạy ĐẦU tiên sau khi dựng lại (đọc đĩa
  nguội) là **2,5996 s** — hai số của cùng một bundle, nên con giây chỉ là mẫu có
  dao động trên HDD máy này, còn `sys.modules` và working set mới là bất biến đáng
  tin (xem `AGENTS.md`, mục "Wall clock giữa hai lần chạy nói dối").
  `scratch/frozen_bundle_probe.py`: **ALL PASS, 0 fail, rc=0**, gồm bốn phép phản
  chứng — lật `_internal/styles` (đỏ đúng lý do thiếu styles), ẩn `core/` rồi ẩn
  `ui/` của tree nguồn (phải vẫn xanh và chi tiết giống từng byte, tức mã đọc từ
  PYZ), và hai dòng mới trong bundle: `vung xuat in/out + preset chat luong` cùng
  `nen toi uu tep video` đều xanh.
- `scratch/release_meta.py` đọc metadata từ chính hai file: `ProductVersion` 1.0.5,
  `FixedFileInfo 1.0.5.0`, `ProductCode {83F5569F-5490-427E-9E6A-B28CE97BFF99}` mới,
  `UpgradeCode {322A4294-D740-42B3-9414-555BA07FDB88}` giữ nguyên như mọi bản trước.
  `scratch/msi_payload_check.py`: **ALL PASS, 0 fail, rc=0** — bảng `File` của MSI
  đúng bằng **363 file / 514.159.312 B** của `dist\Clinging`, có `Clinging.exe`,
  `ffmpeg.exe`, `ffprobe.exe`, bộ glyph fontawesome6 và **không còn** qtawesome.
- **Đã cài lên máy phát triển theo đường Inno, 22/10/2026.**
  `python scratch/installed_app_probe.py`: **ALL PASS, 0 fail**, `TRUE_RC=0`
  (14 tầng bằng chứng). Số đo lại được từ chính bản cài:
  `Clinging.exe` **6.997.295 B**, sha256[:16] `33cbadb850d55464` — **trùng từng
  byte** với `dist\Clinging\Clinging.exe`; `--selftest` từ thư mục cài **rc=0,
  `failed=[]`**; `--split-report` **rc=0** với thẻ video ba hành động
  (Trích xuất ảnh thu nhỏ / Cắt thành nhiều đoạn / Nén tối ưu tệp) và cắt thật
  3 đoạn `mei [0.0, 0.0]`; `_internal` **495,5 MB**, sweep **75 module nạp, 0 lỗi**;
  boot **0,642 s** tới cửa sổ, **68.880 KiB** lúc cửa sổ hiện, **82.524 KiB** lúc
  nghỉ, **cả chín cửa khởi động `True`**; style/layout/alignment/audio/chrome/
  thumbnail/graph/project report đều rc=0.
- **Thư mục cài không thiếu file nào.** Set-diff đường dẫn tương đối giữa
  `%LOCALAPPDATA%\Programs\Clinging` và `dist\Clinging`: **363 lá (dist) so với
  365 (bản cài)** — `0 thiếu`, hai phần thừa đúng là `unins000.exe` +
  `unins000.dat` của Inno.
- **Dữ liệu người dùng còn nguyên.** `user_data_snapshot` 1.927 → 1.968 mục,
  **`THEM: 47 / MAT: 6 / DOI: 0`** (mã thoát của lệnh diff là 1 vì có thêm/mất —
  con số phải đọc là `DOI`). Toàn bộ mục thay đổi nằm trong `~/.clinqing/recovery`
  của fixture selftest (thêm 6, mất 6 do vòng quay keep-5) và `cache\image` của
  ứng dụng (41 mục dựng lại được); **không** đường nào thuộc `Clinging_Projects\`.
  Dự án THẬT của người dùng
  (`Clinging_Projects\Dự án 2\Dự án 2.clinq`) mở qua bản cài và **vẫn nguyên byte**
  so với lúc trước khi probe chạy.
- **Cây MSI vẫn là 1.0.4.** Dịch vụ Windows Installer trên máy này còn kẹt từ
  22/10 (bốn lệnh `msiexec` bị `timeout` cắt giữa giao dịch → `msiserver`
  deadlock; `sc stop` báo Access denied vì cần Admin; chỉ reboot mới sạch), nên
  mọi `/i` `/x` đều treo. Muốn cài `ClingingSetup-1.0.5.msi` vào
  `%LOCALAPPDATA%\Programs\ClingingMSI`: reboot, gỡ hai product probe
  `{B3C15772-…}` / `{706DC2C6-…}`, rồi cài có `INSTALLFOLDER=` rõ ràng như mọi lần.
- Nâng cấp từ 1.0.4: cài đè trực tiếp được. Inno xoá `_internal` cũ trước khi giải
  nén; MSI dùng cùng `UpgradeCode` nên lần cài mới gỡ bản cũ trước khi ghi.
- Dự án `.clinq` mở được hai chiều giữa 1.0.4 và 1.0.5 vì mọi khoá mới đều có giá
  trị mặc định; **đừng lưu lại bằng bản cũ**: bộ serialize cũ không biết các khoá
  mới nên chúng mất khi ghi.
- Máy cấu hình thấp: bản này không thêm binary nào so với 1.0.4; `core/export_range.py`
  nằm trên đường xuất chứ không trên đường boot, và cửa sổ vẫn hiện mà `cv2`,
  `psutil`, `ui.main_window`, `ui.compress_dialog` đều chưa được nạp.
- Build từ mã nguồn cần tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB,
  vượt giới hạn 100 MB/file của GitHub). **Bản cài đặt đã kèm sẵn cặp này.**
- Tài liệu quy trình kiểm chứng: `docs/verification-gates.md`, `docs/glyph-icons.md`.
