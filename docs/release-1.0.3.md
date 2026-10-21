# Clinging 1.0.3

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir; toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg nằm bên trong bundle.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.3.exe` | 141.157.203 B | `f6af436c6de57babf4ec8d68a90c62998b9ed0caa0438f1303d8de64f7143ae4` |
| `ClingingSetup-1.0.3.msi` | 160.704.025 B | `6659172fe5027daa53cfee3adf024891e72043e397c5c4e0526cd3413309a8d9` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.3.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục Add/Remove Programs, tự xoá `_internal`
  cũ khi nâng cấp. Cài vào `%LOCALAPPDATA%\Programs\Clinging`.
- `.msi` (WiX 3.11) — triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.
  `INSTALLFOLDER` mặc định của package là `%LOCALAPPDATA%\Programs\Clinging\`, tức
  **trùng thư mục của bản Inno**. Muốn hai bản cùng tồn tại như máy phát triển thì
  gọi rõ thư mục: `msiexec /i ClingingSetup-1.0.3.msi INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`.

Cả hai được dựng từ cùng một thư mục `dist\Clinging` (362 file), nên payload như
nhau; bản cài sau chiếm shortcut Desktop và phần mở rộng `.clinq`. Bảng File của
MSI đã đọc ngược ra từ chính file `.msi` và so từng tên với `dist`
(`scratch/msi_payload_check.py`) — chứng minh payload là bundle 1.0.3, không phải
bundle cũ bị dựng lại dưới tên mới.

## Thay đổi so với 1.0.2

Bốn nhóm tính năng, mỗi nhóm đi kèm cổng `--selftest` chạy trên đúng đường production,
phản chứng chứng minh cổng đỏ vì đúng lý do, và ảnh dựng từ `FrameComposer` cho phần
render. Selftest bản này: 34 dòng, `rc=0`.

### Nhóm A — sửa cho đúng, không thêm bề mặt mới

- **File media bị dời vẫn mở được.** Bộ giải đường dẫn mới (`core/media_locator.py`)
  dò lại vị trí thực của asset khi file đổi chỗ, dùng **chung cho cả preview lẫn
  export** nên hai bên ra cùng payload.
- **Lưu dự án nguyên tử.** Ghi ra file tạm rồi mới đổi tên, giữ 5 bản recovery gần
  nhất; một lần ghi hỏng (payload không serialize được) để file `.clinq` thật còn
  nguyên từng byte — trước đây autosave đè trực tiếp lên dự án đang mở.
- **Hoàn tác cho thao tác chữ và hình học.** `SetClipTextCommand` và
  `SetClipTransformCommand` nằm trong stack undo; các thao tác số liên tiếp trong
  0,75 s gộp thành một bước. `Ctrl+Z` trả lại từng pixel giống khung gốc.

### Nhóm B — clipboard clip (Ctrl+C / Ctrl+V)

Nhân bản clip qua đúng seam `place_clip` của dự án, nên bản dán giữ nguyên font,
hình học và tham chiếu media, và chịu cùng luật đụng độ/góp layer như `duplicate_clip`;
có undo để gạch sạch bản dán. Clipboard chỉ sống trong bộ nhớ phiên làm việc.

### Nhóm C — style chữ

Mười một trường style trên mỗi clip chữ: màu + bề rộng viền, màu + lệch dx/dy + độ
mờ bóng, màu + độ đậm + bán kính + đệm của hộp nền, và căn lề trái/giữa/phải. Một
seam duy nhất (`core/text_paint.py:text_style_of`) cho cả `TextClipItem.paint` lẫn
`FrameComposer._draw_text`, nên thứ thấy trên canvas đúng bằng thứ xuất ra file.
Chỉ bật căn lề vẫn đi đường vẽ trực tiếp (không dựng lớp ảnh) để máy yếu không bị
đánh thuế. Điều khiển ở thẻ "Style chữ" trong panel thuộc tính, có undo.

### Nhóm D — chỉnh màu

- **Năm núm trên mỗi clip:** xoay trục xám (hue, ±180°), lift, gamma, gain và LUT
  `.cube`. Card "Chinh mau" là một `EffectData` riêng, không lẫn với các filter màu
  có sẵn.
- **Preview == export.** Cả hai gọi cùng `core/clip_effects.apply_color_effects`;
  khung render từ `FrameComposer` lệch ảnh preview 0,16/255 mức trung bình mỗi kênh.
  Ảnh chứng minh đo được lift nhấc vùng tối ×2,33 trong khi vùng sáng chỉ ×1,06,
  gamma nén vùng giữa ×1,28 còn vùng sáng giữ nguyên, và LUT hoán vị kênh R↔B khớp
  từng pixel (lệch 0,2 so với kênh đúng, 43,4 so với kênh cũ).
- **Bộ đọc LUT** (`core/lut.py`) hỗ trợ cả bảng 3D `.cube` (trục xanh nhanh nhất,
  nội suy tam tuyến) lẫn bảng 1D theo kênh, cache theo `(đường dẫn, mtime_ns, kích
  thước)` tối đa 4 bảng, và không bao giờ ném lỗi ra UI khi file hỏng. Hai lỗi thật
  của module này — phân kênh 1D và khoá cache va nhau — do chính cổng mới tìm ra.
- **Không đánh thuế máy yếu / bộ nhớ thường trú.** `core/lut.py` chỉ được import
  trong nhánh có chọn LUT, nên cửa sổ khởi động không nạp nó.

## Sửa lỗi đi kèm

- Probe dựng lại phải gọi `stop()` + `setSource(QUrl())` cho `QMediaPlayer` trước khi
  xoá fixture: backend WMF giữ file media đang mở ngay cả sau `close()`, nên lần chạy
  20/10 để sót `scratch/color_grading_ui_A.mp4` với `WinError 32` dù 8 cổng đều xanh.
  App thật không bị ảnh hưởng (process thoát là handle về hệ điều hành), nhưng một
  probe không giải phóng nguồn thì không có quyền báo PASS.
- Ảnh chứng minh dựng từ `FrameComposer.render_frame` (trả `QImage` ARGB32_Premultiplied),
  đọc pixel theo `bytesPerLine()` tính bằng byte — hai chỗ trước đó đọc sai kiểu.

## Lưu ý

- **Chưa ký số.** SmartScreen có thể hiện *"Windows protected your PC"* — chọn
  *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính SHA-256 ở bảng trên.
- Nâng cấp từ 1.0.2: cài đè trực tiếp được. Inno xoá `_internal` cũ trước khi giải
  nén; MSI dùng cùng `UpgradeCode` nên lần cài mới gỡ bản cũ trước khi ghi.
- Dự án `.clinq` hai chiều: bản 1.0.2 mở được file của 1.0.3 vì mọi field mới đều có
  giá trị mặc định, và thẻ `EffectData("Chinh mau")` chỉ là no-op ở đó — `apply_color_effects`
  của 1.0.2 trả nguyên ảnh khi không khoá nào thuộc `PIXEL_KEYS` (đã đọc lại mã bản
  `2b22966`). Nhưng **đừng lưu lại bằng bản 1.0.2**: bộ serialize cũ không biết 11 trường
  style chữ nên chúng mất khi ghi. Mở dự án cũ bằng 1.0.3 thì giữ nguyên.
- **Khởi động của chính bản cài, đo bằng `--startup-report` của exe đã cài** (không
  phải từ tree nguồn): 1,02 s tới cửa sổ, working set 68,5 MB ngay lúc cửa sổ hiện,
  `cv2` không xuất hiện trong đường boot (`cv2_da_nap_luc_boot=False`, và vẫn `False`
  lúc ngầm định). Bản dựng này đi qua `scratch/installed_app_probe.py`: 216 dòng do,
  **0 FAIL**, `rc=0`, gồm cả 34 dòng `--selftest` chạy trong bundle.
- Máy cấu hình thấp: app chạy ở 8 GB RAM; xuất video giải mã tuần tự
  (~0,12 s/frame ở 720p), muốn nhanh thì cắt ngắn thời lượng hơn là hạ độ phân giải.
- Build từ mã nguồn cần tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB,
  vượt giới hạn 100 MB/file của GitHub). **Bản cài đặt đã kèm sẵn cặp này.**
- Tài liệu quy trình kiểm chứng của bản dựng: `docs/verification-gates.md`,
  `docs/glyph-icons.md`.
