# Clinging 1.0.1

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir, toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg được đóng gói bên trong.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.1.exe` | 144.450.049 B | `3841780a86024641a5c238e8f62474106d3bbb95fd1f61bcb200b7fa0e6174e2` |
| `ClingingSetup-1.0.1.msi` | 165.002.912 B | `205ffbb39f94d7cb5ac5f7541f955007c43b8b63ca44885963def824167ac8dd` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.1.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**, không phải hai phiên bản
khác nhau. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục trong Add/Remove Programs, tự xoá
  `_internal` cũ khi nâng cấp.
- `.msi` (WiX 3.11) — để triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên nó **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.

Cài theo đường dẫn mặc định `%LOCALAPPDATA%\Programs\Clinging`. Nếu cài cả hai,
bản cài sau chiếm shortcut Desktop và phần mở rộng `.clinq`.

## Thay đổi so với 1.0.0

- **Biểu tượng ứng dụng đã cập nhật.** Bản 1.0.0 mang icon cũ vì PyInstaller dùng
  lại `build\ClingingQt\Clinging.exe` (PE resource nằm trong file EXE đã build
  trước đó), nên icon mới trong `assets\app-icon\icon.ico` không được nhúng lại.
  Bản này build với `--clean`; icon đã xác minh bằng cách đọc thẳng resource `.rsrc`
  của exe đã cài và so từng pixel với `icon.ico` (5 kích thước 16→256, sai lệch 0),
  đồng thời hỏi Explorer vẽ icon thật của shortcut rồi so tiếp (`SHGetFileInfoW`).
- `setup.exe` tự khai `FileVersion`/`ProductVersion` = 1.0.1, kèm Company và
  Copyright. Trước đó Inno để trống `VersionInfoVersion`, nên mở Properties của
  file tải về chỉ thấy `0.0.0.0`.

## Lưu ý

- **Chưa ký số.** Windows SmartScreen có thể hiện cảnh báo *"Windows protected
  your PC"* — chọn *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính
  SHA-256 ở bảng trên và thấy khớp.
- Máy cấu hình thấp: ứng dụng chạy được ở 8 GB RAM; xuất video giải mã tuần tự
  (~0,12 s/frame ở 720p), nên muốn nhanh thì cắt ngắn thời lượng hơn là hạ độ phân giải.
- Dự án không kèm `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB, vượt giới hạn
  100 MB/file của GitHub). Bản **cài đặt** ở trên đã có sẵn cặp ffmpeg này; chỉ khi
  build từ mã nguồn bạn mới cần tự đặt hai file đó vào `tools\ffmpeg\`.
