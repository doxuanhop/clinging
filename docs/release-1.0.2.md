# Clinging 1.0.2

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir; toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg nằm bên trong bundle.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.2.exe` | 141.087.984 B | `870303b2d75c74e3d000c71eda04a7a99a5a9ffff11eb9501d9544dd6f78fbf4` |
| `ClingingSetup-1.0.2.msi` | 160.626.201 B | `21518202e0306d6d173d1f98c5920fa09650e2c102950d153cbe37beaaa4def4` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.2.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục Add/Remove Programs, tự xoá `_internal`
  cũ khi nâng cấp. Cài vào `%LOCALAPPDATA%\Programs\Clinging`.
- `.msi` (WiX 3.11) — triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.
  Cài vào `%LOCALAPPDATA%\Programs\ClingingMSI`.

Cả hai được dựng từ cùng một thư mục `dist\Clinging` (362 file), nên payload như
nhau; bản cài sau chiếm shortcut Desktop và phần mở rộng `.clinq`. Bảng File của
MSI đã đọc ngược ra từ chính file `.msi` và so từng tên với `dist`
(`scratch/msi_payload_check.py`) — chứng minh payload là bundle 1.0.2, không phải
bundle cũ bị dựng lại dưới tên mới.

## Thay đổi so với 1.0.1

- **qtawesome ra khỏi bundle.** Icon Font Awesome giờ do `widgets/fontawesome.py`
  vẽ trực tiếp từ `assets\icons\fontawesome6-solid-6.7.2.ttf` + charmap 1402 tên,
  chạy sau khi `QApplication` tồn tại. `import qtawesome` một mình tốn 0,62 s trong
  cửa sổ khởi động và kéo theo `qtpy` + `QtOpenGL`/`QtDataVisualization` (20 module
  không ai dùng); bộ vẽ mới tốn 0,044 s cho cùng 13 icon có mặt lúc boot và bớt
  ~30 MB RAM private. Boot nóng trên máy 8 GB: 0,84–0,95 s tới cửa sổ.
  Ảnh đối chiếu từng glyph: `icon_parity.png` (khác 0 pixel với bản qtawesome).
- **Mở app không còn ghi đè dữ liệu của bạn.** `recent_projects.json` trước đây bị
  viết lại ngay khi đọc, và mọi dự án đang không truy cập được (đĩa ngoài chưa gắn,
  thư mục đổi tên) bị xoá khỏi danh sách gần đây. Đường đọc giờ chỉ đọc; mục không
  giải được vẫn giữ. Cổng: `--selftest` dòng `doc MRU khong ghi du lieu nguoi dung`.
- **Tên icon sai báo rõ, không giết ứng dụng.** Trước đây một tên glyph không tồn
  tại bật lỗi bên trong callback C++ của `QIconEngine`, Python không unwind qua biên
  được nên cả process chết kiểu `0xC0000409` và mất luôn log. Giờ tên được kiểm tra
  ngay lúc dựng icon, lỗi `ValueError` chỉ ra đúng chỗ gọi.
- `Clinging.exe`, `setup.exe` và MSI khai version 1.0.2 (đọc bằng cùng API Explorer
  dùng, xem `scratch/exe_version.py --expect 1.0.2`).

## Lưu ý

- **Chưa ký số.** SmartScreen có thể hiện *"Windows protected your PC"* — chọn
  *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính SHA-256 ở bảng trên.
- Nâng cấp từ 1.0.1: cài đè trực tiếp được. Inno xoá `_internal` cũ trước khi giải
  nén, nên file của bản cũ không sót lại; nếu bạn cài cả hai đường dẫn thì hai bản
  độc lập cùng tồn tại.
- Máy cấu hình thấp: app chạy ở 8 GB RAM; xuất video giải mã tuần tự
  (~0,12 s/frame ở 720p), muốn nhanh thì cắt ngắn thời lượng hơn là hạ độ phân giải.
- Build từ mã nguồn cần tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB,
  vượt giới hạn 100 MB/file của GitHub). **Bản cài đặt đã kèm sẵn cặp này.**
- Tài liệu quy trình kiểm chứng của bản dựng: `docs/verification-gates.md`,
  `docs/glyph-icons.md`.
