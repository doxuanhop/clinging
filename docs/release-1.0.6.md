# Clinging 1.0.6

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir; toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg nằm bên trong bundle.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.6.exe` | 143.940.720 B | `8f03b75d3102108205a3887e0ca904ad39d68bcaa47101b445b259977cb6c6c4` |
| `ClingingSetup-1.0.6.msi` | 163.537.096 B | `7addc2d02512bc11e6ec626515b13fe91a0ca3c01d5b47cc89e79da0c83df057` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.6.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục Add/Remove Programs, tự xoá `_internal`
  cũ khi nâng cấp. Cài vào `%LOCALAPPDATA%\Programs\Clinging`.
- `.msi` (WiX 3.11) — triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.
  `INSTALLFOLDER` mặc định của package **trùng thư mục của bản Inno**, nên muốn hai
  bản cùng tồn tại thì phải gọi rõ:
  `msiexec /i ClingingSetup-1.0.6.msi INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`.

## Thay đổi so với 1.0.5

Bốn nhóm. Mỗi nhóm vẫn theo hợp đồng 4 bước: cổng chạy trên đúng lệnh người dùng
gọi, phản chứng chứng minh cổng đỏ vì **đúng** lý do, ảnh cho phần render, và mã
thoát đọc từ chính công cụ. Selftest: **39 → 44 dòng**, `failed=[]`, `rc=0` — cả
trên tree nguồn lẫn trên exe đóng gói.

### Thẻ "Biến đổi": xoay tự do, lật, canh lề, khóa tỷ lệ (dòng 25)

Bảng thuộc tính của một clip giờ có đủ 12 nút trên một thẻ: ô `Tỷ lệ %` kèm nút
`Đồng nhất`, hai nút xoay `−90°` / `+90°`, hai nút lật `Ngang` / `Dọc`, sáu nút
canh mép (`Trái / Giữa / Phải` và `Trên / Dưới` đều có `Giữa`), nút `Đặt lại`,
và một **tay nắm xoay tự do** ngay trên canvas — kéo bằng chuột thật, không phải
slider.

Ba khoá mới (`flip_h`, `flip_v`, `uniform_scale`) sống trong `ClipTransform`,
tròn vẹn qua `.clinq`, **không** nằm trên đồ thị keyframe, và `SetClipTransformCommand`
undo được. File `.clinq` cũ không có khoá nào vẫn mở được và mặc định là "không lật,
khóa bật". Góc xoay luôn trong `(-180, 180]` — `QTransform` và `atan2` của
`sync_to_model` chỉ cùng một tiếng trong dải đó.

Bốn chỗ chia nhau một sự thật (`core/timeline_model.py` + `core/project_storage.py`,
`core/canvas_utils.py`, `ui/graphics_canvas_item.py`, `core/frame_composer.py`) và
cổng do **cả bốn**; `core/canvas_utils.py` xoay **trước rồi mới** canh lề.

Cổng `--transform-report`: **17 cửa**, toàn bộ số đo lấy từ **pixel mà
`FrameComposer` vẽ ra** (960×540 cho đường xuất, `QGraphicsScene.render` 1920×1080
cho preview) chứ không lấy từ model — fixture bốn góc bốn màu, lật ngang/dọc đảo
thật và không đổi tâm nội dung (`flip_center_dx = 0,0`), xoay 45° mở rộng mà vẫn
trong khung (`rot45_inside = True`), xoay 180° ≡ hai lần lật, năm phép canh lề chạm
đúng mép canvas **ở góc đã xoay** (`align_left_x0 = 0,0`, `align_right_edge = 0,0`),
ô 150 % mở rộng đúng 1,5 lần **cả hai trục** (`pct_width_ratio = 1,501`).

Phản chứng: `scratch/transform_counterfactual.py` — **18/18 PHÂN BIỆT**, `ALL PASS`,
rc=0, 133 s; SPOT đủ bảng `rc=1 rows=42 failed=['bien doi: ...']`. Ba vết đỏ bằng
điều người dùng nhìn thấy chứ không bằng cấu trúc, trong đó `hit_test_rotate_gia`:
một `_hit_test_rotate` giả vẫn qua cửa cũ vì `item.contains()` đi qua `shape()`.

Ảnh: `assets/uiux/editor-project-window.png` (chụp THẬT toàn màn hình 1920×1080).

### Bố cục & Phong cách cấp dự án (dòng 19)

Lấy từ ý tưởng trong tệp dự án 9:16 người dùng đưa: **13 khoá bố cục** (12 kiểu +
`none`: split 2, split-4, split-5, split-6, manga-grid, polaroid-retro…), **10 chất
liệu nền**, ba chế độ nền (`black` / `color` / `texture`), bốn họ font, hai vùng chữ
đầu/cuối, chạy tuần tự, manga xoay và tự vừa. Phạm vi chốt là **Cả dự án** — một dict
cấp model cạnh `recap_overlay`, sống trong `.clinq` và là **MỘT bước undo**.

`core/frame_composer.py` vẽ theo đúng thứ tự `paint_background` → clip →
`paint_foreground` → recap → scale, nên preview và xuất dùng **chung một seam**.
Vì máy cấu hình thấp: `backdrop()` cache theo khoá với trần 6 bản, và
`paint_background()` return sớm khi tắt hoặc chọn nền đen — dự án không dùng tính
năng thì không phải trả một pixel nào.

Cổng `--canvas-layout-report`: **36 cửa**, đo trên widget thật và pixel thật. Hai
cửa đáng nhớ: `22/22 khoá có điều khiển ghi được model` (bắt đúng lỗi thật ngày
23/10 — `touch()` thiếu nhánh `header_bold`/`footer_bold` làm probe chết lặng, không
in ra bảng đo lẫn một dòng FAIL) và `khong dieu khien nao bi fold` (108 điều khiển ở
bốn trạng thái, `max_dialog_h 523 < screen_h 824`). Mở hộp thoại `0,495 s`, RAM tăng
`4.940 KiB` (trần 8 MiB), kéo slider làm canvas preview đổi `272.832` px, Ctrl+Z trả
bố cục cũ.

Phản chứng: `scratch/canvas_layout_counterfactual.py` — **ALL PASS 50/50**, rc=0
(40 vết offline trên payload xanh + 4 phép đổi byte SONG trong
`ui/canvas_layout_dialog.py`), mỗi phép đỏ đúng một tên.

Ảnh commit: `assets/uiux/editor-canvas-layout-dialog.png` — ảnh **chụp THẬT cửa sổ**
1904×1072, preview đang vẽ `manga-grid` trên nền `blueprint`, vùng đối lệch 54,53 %
so với khung hình trước khi mở.

### Kho hiệu ứng âm thanh SFX (dòng 37)

Kho **14 tiếng** dựng sẵn trong app (`assets/sfx/`, 181.167 B, tổng 14,15 s) do
`tools/make_sfx.py` vẽ bằng `lavfi` rồi nén bằng `ffmpeg` — không tải audio từ mạng,
không phụ thuộc thư viện bên thứ ba. Nút trên thanh thời mở hộp thoại: ô tìm kiếm,
combobox nhóm, "Nghe thử", "Chèn vào timeline".

Cổng `--sfx-report`: **23 cửa**. Từng tiếng bị **đo lại** bằng `ffprobe`/`ffmpeg`
(thời lượng, RMS, peak, ZCR, sha256) chứ không tin `manifest.json` — manifest do
chính script dựng pack tự viết, nên một pack rỗng hay một pack toàn tiếng giống hệt
nhau vẫn "đúng manifest". Hai con số chống hai kiểu gian lận đó:
`distinct_hashes = 14` (không có hai tiếng nào là một file đổi tên) và
`zcr_spread = 0,7392` (trải đều từ tiếng chuông tới tiếng nhiễu).
Đường người dùng cũng nằm trong payload: nhóm "Chuyển cảnh" lọc còn `3/3`, tìm `"Vút"`
còn `2/2`, hai lần "Chèn" ra `clip_count 2` trên MỘT lane với `overlap 0,0`,
Ctrl+Z trả timeline trống, và "Nghe thử" rồi dừng phải **thả khoá file**
(`preview_source_cleared True`).

Phản chứng: `scratch/sfx_counterfactual.py` — **33 vết** trên payload xanh + **6 phép
đổi byte nguồn thật**, ~2,5 phút.

### Thư viện tài nguyên: hết lag trên máy cấu hình thấp (dòng 32)

Người dùng báo "vẫn lag với máy cấu hình thấp" và chỉ đích danh bảng thư viện. Đo
trên đúng đường sản xuất với fixture 66 file tự sinh (không dùng media người dùng),
sáu sửa đổi ở `ui/library_panel.py` + `core/media_cache.py`, **không đổi hành vi bán
được**. Trước / sau trên cùng máy, cùng fixture 65 thẻ:

| Chỉ số | Trước | Sau |
| --- | --- | --- |
| Lượt xây lưới cho một đợt nạp | 65 | 1 |
| GUI block khi nạp thư viện | 1132,8 ms | 197,0–214,0 ms |
| Block mỗi thẻ | 17,43 ms | 3,03–3,30 ms |
| Median một phím tìm kiếm | 17,72 ms | 1,27–2,82 ms |
| Lượt giải mã ảnh của thẻ đang ẩn | 3 | 0 |
| Thumbnail ảnh tĩnh | 1600×1200 = 7,324 MiB | 320×240 = 0,293 MiB |
| Lượt giải mã sau khi thẻ bị xóa | 20 | 3–4 |

Cổng `--library-report`: **13 cửa** (mười cửa đếm, hai cửa ms, một cửa ảnh). Phản
chứng `scratch/library_counterfactual.py`: **ALL PASS 45/45**, rc=0, 131,3 s — phần A
19 vết trét lên payload thật đang xanh, mỗi vết lấy đúng con số của bản chưa tối ưu
(bảng đã đỏ **7/13 cửa**), phần B 5 phép đổi byte trên nguồn thật và mỗi phép chạy
**cả hai** lệnh production.

### Sửa: ứng dụng chết im lặng khi đóng cửa sổ lúc dải hình còn đang giải mã (dòng 44)

Mở một dự án có video nặng rồi tắt cửa sổ: bản 1.0.6 đầu tiên chết không một dòng
thông báo, mã thoát `0xC0000409`. Lỗi này có từ trước 1.0.6 — `ClipItem` mở luồng
giải mã ngay khi được tạo và không đường nào trong app dừng nó lại lúc đóng — chỉ
là trước đây ảnh nhỡ đã nằm sẵn trong bộ nhớ đệm nên luồng xong trước khi bạn kịp
tắt. Bản này thêm `MainController.closeEvent` → `TimelineScene.shutdown_clip_workers()`,
dùng đúng `shutdown_extraction()` đã có: mỗi clip được yêu cầu nghỉ ngay sau khung
hình đang giải mã, nên cái giá lúc tắt app là một khung hình, không phải cả dải.

Đo trên fixture 4K tự sinh (3840×2160, 12 s, một keyframe duy nhất — không dùng
video của người dùng): 19,1 s cho cả lượt mở-bảng-chứng-minh-đóng ở bản sửa, so
với 16,3–17,2 s khi cố tình cắt phép dừng đó đi; hai phép cắt đều làm cổng
`--project-report` trả `3221226505` **4/4 lần**, còn mã gốc thì `rc=0`. Dòng mới
`dong cua so: dung luong giai ma clip tru khi thoat` đếm ba điều (mở ra đủ luồng,
đóng đi hết luồng, không `QThread` nào còn sống) và tự đỏ nếu ai đó xóa phép dựng.
Chi tiết phản chứng: `docs/verification-gates.md` mục "Dòng đóng cửa số",
`scratch/teardown_workers_counterfactual.py` (ALL PASS 16/16), ảnh
`scratch/teardown_workers_evidence.png` (chụp thật cửa sổ editor đang mở dự án 4K
tự sinh; ảnh không commit vì caption chứa đường dẫn cá nhân của máy đo, còn mọi số
đo thì có trong `scratch/teardown_workers_counterfactual.json`).

## Lưu ý

- **Chưa ký số.** SmartScreen có thể hiện *"Windows protected your PC"* — chọn
  *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính SHA-256 ở bảng trên.
- **Cổng chạy trên bundle thật, không phải tree nguồn.** Lần dựng này là **lần đầu**
  bốn cổng `--sfx-report`, `--canvas-layout-report`, `--library-report`,
  `--transform-report` tồn tại trong exe đóng gói; chạy từ nguồn không chứng minh
  được `hiddenimports`. `dist\Clinging\Clinging.exe`, mã thoát đọc bằng
  `subprocess.run` (không qua đường ống), máy nghỉ:

  | Lệnh trên bundle | rc | thời gian |
  | --- | --- | --- |
  | `--selftest` | 0 | 82,0 s — **44 dòng**, `failed=[]`, `only=null` |
  | `--split-report` | 0 | 9,3 s — `frozen=True`, `menu_actions` ba hành động, 3 đoạn `failed=[]` |
  | `--sfx-report` | 0 | 13,0 s — `entry_count 14`, `missing_files []`, 23 cửa `failed=[]` |
  | `--canvas-layout-report` | 0 | 18,1 s — 36 cửa, `failed=[]` |
  | `--library-report` | 0 | 12,6 s — 13 cửa `failed=[]`, `restore_block_ms 251,6`, `block_ms_per_card 3,87` |
  | `--transform-report` | 0 | 3,6 s — 17 cửa, `failed=[]` |
  | `--startup-report` | 0 | 3,5 s — `ok=True`, **11/11 cửa True**, cửa sổ hiện lúc **0,5610 s**, **69.308 KiB** lúc cửa sổ hiện |
  | `--audio-report` | 0 | 6,3 s — `frozen=True`, `card_visible=True`, 4 slider, 2 export token |
  | `python scratch/frozen_bundle_probe.py` | 0 | 404,4 s — **ALL PASS (0 fail)**, bên trong là `--selftest` **44 checks rc=0** |

- **Đã cài đè và đo trên chính bản cài.** `ClingingSetup-1.0.6.exe` cài lên
  `%LOCALAPPDATA%\Programs\Clinging` rc=0 trong 33,9 s; `scratch/installed_app_probe.py`
  đo bản cài đó: **ALL PASS (0 fail)**, rc=0, 401,7 s. `Clinging.exe` đã cài
  **7.159.482 B**, sha256[:16] `775ddfbd248b7314` **trùng từng byte** với `dist`;
  set-diff đường dẫn tương đối **385 lá vs 383 của dist — 0 thiếu**, hai phần thừa
  đúng là `unins000.exe` + `unins000.dat`; `--selftest` chạy từ thư mục cài trả
  `failed=[]` **và có dòng `dong cua so`** — phép sửa nằm trong binary người dùng
  thật sự chạy, không chỉ trong tree nguồn. `--audio-report` (từng abort
  `0xC0000409`) giờ **rc=0**. Bảng chi tiết: `docs/verification-gates.md` mục
  "Bản cài Inno 1.0.6".

- **Bốn module UI mới đều có mặt trong PYZ.** `core.sfx`, `ui.sfx_dialog`,
  `core.canvas_layout`, `ui.canvas_layout_dialog` nằm trong `hiddenimports` của
  `ClingingQt.spec` **và** mỗi dòng selftest của tính năng đó import thẳng module UI
  của nó — quy trình đã trả giá với `ui.compress_dialog` ở bản 1.0.4: module chỉ được
  import trong thân hàm thì tree nguồn luôn xanh mà bundle vẫn thiếu, người dùng chỉ
  thấy crash lúc bấm menu. `frozen_bundle_probe.py` chạy lại `--selftest` bên trong
  exe và cộng ba phản chứng (lật `_internal/styles`, ẩn `core/` rồi ẩn `ui/` của tree
  nguồn) — trả **ALL PASS, 0 fail**.
- **Không tính năng mới nào nằm trên đường boot.** `--startup-report` có thêm hai cửa
  laziness mang đúng tên module (`boot_khong_keo_sfx`, `boot_khong_keo_bocuc`);
  `scratch/boot_laziness_counterfactual.py` đo cả năm module: kéo tay hết năm lên đầu
  đường boot làm boot **chậm thêm 0,540 s** và RAM lúc có cửa sổ **thêm 13.116 KiB**,
  và đúng năm cửa đó đỏ trong khi `boot_khong_cv2` vẫn xanh — tức cổng đỏ vì module
  của chính nó, không vì môi trường.
- `scratch/release_meta.py` đọc metadata từ chính hai file (rc=0): sáu nguồn trong
  tree đều **1.0.6** (`clinging.iss MyAppVersion`, `core/settings.py APP_VERSION`,
  bốn trường trong `version_info.txt`) → `KHOP: tat ca = 1.0.6`; MSI
  `ProductVersion 1.0.6`, `ProductCode {3899A54B-5482-46B0-A291-0646D5FE1F57}` (mới),
  `UpgradeCode {322A4294-D740-42B3-9414-555BA07FDB88}` giữ nguyên như mọi bản trước;
  setup.exe `FixedFileInfo 1.0.6.0`, `FileVersion 1.0.6`, `ProductVersion 1.0.6`.
  `scratch/msi_payload_check.py`: **ALL PASS, 0 fail, rc=0** — bảng `File` của MSI
  đúng bằng **383 file / 516.682.602 B** của `dist\Clinging` (1.0.5 là 363 file /
  514.159.312 B; đối chiếu lá-file giữa hai MSI ra **đúng 20 file mới, 0 file mất**:
  15 file `assets/sfx` — 14 mp3 + `manifest.json` — và 5 ảnh `assets/uiux`, tức
  bundle cũng mang theo ảnh chứng minh). Trong payload có `Clinging.exe`,
  `ffmpeg.exe`, `ffprobe.exe`, bộ glyph fontawesome6 và **không còn** qtawesome. **Số phát hành chỉ ba thành phần**: `1.0.5.1` không cài được bằng
  Windows Installer (đo 22/10/2026: `MsiEnumRelatedProducts` trả về CẢ HAI ProductCode
  vì `MajorUpgrade` không coi số bốn thành phần là mới hơn), và
  `release_meta.source_versions()` chặn ngay từ nguồn.
- **Dữ liệu người dùng còn nguyên**: các report đều có cửa "không ghi vào cache người
  dùng" và trả `user_cache_changed False`; `%APPDATA%\Clinging\cache\image` được
  redirect về thư mục tạm cho từng lần đo (vẫn đi qua đúng đường ghi thật
  temp + `os.replace` + budget).
- Nâng cấp từ 1.0.4/1.0.5: cài đè trực tiếp được. Inno xoá `_internal` cũ trước khi
  giải nén; MSI dùng cùng `UpgradeCode` nên lần cài mới gỡ bản cũ trước khi ghi.
- Dự án `.clinq` mở được hai chiều giữa 1.0.5 và 1.0.6 vì mọi khoá mới
  (`flip_h`, `flip_v`, `uniform_scale`, `project_layout`) đều có giá trị mặc định;
  **đừng lưu lại bằng bản cũ**: bộ serialize cũ không biết các khoá mới nên chúng mất
  khi ghi.
- Máy cấu hình thấp: bản này thêm `assets/sfx/` **181.167 B** (14 tiếng) và một module
  bố cục thuần Python; không thêm binary nào. SFX và bố cục chỉ được import trong thân
  hàm điểm vào.
- Build từ mã nguồn cần tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB,
  vượt giới hạn 100 MB/file của GitHub). **Bản cài đặt đã kèm sẵn cặp này.**
- Tài liệu quy trình kiểm chứng: `docs/verification-gates.md`, `docs/glyph-icons.md`.
