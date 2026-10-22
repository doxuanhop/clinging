# Clinging 1.0.4

Bản cài đặt cho Windows 10/11 64-bit, chạy per-user (không cần quyền Admin, không
ghi vào `Program Files`). Ứng dụng dựng bằng PyInstaller onedir; toàn bộ runtime
gồm PySide6, OpenCV và ffmpeg nằm bên trong bundle.

## File tải về

| File | Kích thước | SHA-256 |
| --- | --- | --- |
| `ClingingSetup-1.0.4.exe` | 141.523.072 B | `4757bc88ab4de8da7e9ad56a6b2ddf422f17b853e3cdbcfac33e3a8df012cd18` |
| `ClingingSetup-1.0.4.msi` | 161.076.901 B | `cfbed23f63912c3cf622764b4f3c2dd511cbad028ecbbdf637559cf1b493dc65` |

Kiểm tra sau khi tải:

```bat
certutil -hashfile ClingingSetup-1.0.4.exe SHA256
```

Hai file là **hai cách đóng gói của cùng một ứng dụng**. Chọn một:

- `.exe` (Inno Setup) — có wizard, ghi mục Add/Remove Programs, tự xoá `_internal`
  cũ khi nâng cấp. Cài vào `%LOCALAPPDATA%\Programs\Clinging`.
- `.msi` (WiX 3.11) — triển khai hàng loạt bằng `msiexec /i ... /qn`. MSI per-user
  nên **không** tạo mục Add/Remove Programs; gỡ bằng `msiexec /x {ProductCode}`.
  `INSTALLFOLDER` mặc định của package **trùng thư mục của bản Inno**, nên muốn hai
  bản cùng tồn tại thì phải gọi rõ:
  `msiexec /i ClingingSetup-1.0.4.msi INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`.

Cả hai được dựng từ cùng một thư mục `dist\Clinging` (363 file, 514.130.264 B payload),
nên payload như nhau; bản cài sau chiếm shortcut Desktop và phần mở rộng `.clinq`.
Bảng File của MSI đọc ngược ra từ chính file `.msi` và so từng tên với `dist`
(`scratch/msi_payload_check.py`: ALL PASS, 0 fail) — chứng minh payload là bundle
1.0.4, không phải bundle cũ bị dựng lại dưới tên mới.

## Thay đổi so với 1.0.3

Bốn nhóm tính năng. Mỗi nhóm đi kèm cổng `--selftest` chạy trên đúng đường
production, một probe phản chứng chứng minh cổng đỏ vì **đúng** lý do, và ảnh dựng
từ code path sản xuất cho phần render. Selftest: **34 → 38 dòng**, `rc=0`.

### Chroma key — đục nền theo màu

Một card `Chroma key` trên mỗi clip: màu nền, ngưỡng, feather và khử loang màu
(spill). Khoá theo **góc hue** trên mặt phẳng Cb/Cr (không phải khoảng cách — màu
trắng cách nền xanh `#00B140` tới 83,7 đơn vị bão hoà, nên bộ khoá khoảng cách sẽ
đục thủng chủ thể trước khi ăn nền). Matte tính một lần trước vòng lọc, render ở
bản ≤256 px rồi phóng lên: 54 → 13,4 ms/frame. Preview và export gọi cùng một hàm.

### Tách âm thanh khỏi clip video

Menu chuột phải trên card timeline biến một clip video thành **hai** clip cùng
nguồn — phần hình tắt tiếng, phần tiếng nằm ở lane audio — và cả thao tác là một
bước undo. Không giải mã lại, không ghi file mới.

### Thẻ "Cắt" (in/out) trong bảng thuộc tính

Spin `In (s)` / `Out (s)`, nhãn thời lượng và hai nút cắt theo playhead. Toàn bộ
hình học đi qua đúng `TimelineModel.resize_clip` — hàm mà cú kéo mép clip trên
timeline gọi — nên bảng thuộc tính và timeline không thể sản ra hai số khác nhau.
Một cú kéo spin = một bước undo; cú nudge 0,01 s trên clip 4x hay thao tác trên
track bị khoá không tạo bước undo giả.

### Nén / tối ưu tệp

Menu chuột phải trên card **video** trong thư viện → hộp thoại "Nén / tối ưu tệp"
với bốn kiểu, chỉ dùng ffmpeg đã kèm trong bundle:

| Kiểu | Việc nó làm | Khi nào dùng |
| --- | --- | --- |
| **Tối ưu không mất chất** (remux) | Copy từng bit stream, chỉ đổi cách đóng gói để `moov` lên đầu file | Muốn mở/tải nhanh mà không chấp nhận giảm chất lượng. Không mã hoá lại |
| **H.264** (CRF 16–35) | Nén lại, tương thích rộng nhất | Mặc định an toàn cho mọi máy phát và trình duyệt |
| **H.265/HEVC** | Nén mạnh hơn, `hvc1` tag cho QuickTime | Khi cần nhẹ và máy phát có bản quyền giải mã HEVC |
| **VP9 / WebM** | Nén mở, không bằng sáng chế, `-cpu-used` thay cho `-preset` | Khi bắt buộc WebM |

Hộp thoại **chặn trước khi chạy** những cặp vô nghĩa: H.264 không ghi được vào
`.webm`, remux một nguồn h264 ra `.webm` cũng không (nguồn không tự đổi codec),
`.webm` buộc `libopus`, HEVC trong `.mp4` buộc tag `hvc1`. Có thanh tiến độ và nút
Huy; một lần chạy dở **không để lại file rác** trên đĩa.

Số đo trên máy phát triển (fixture 6 s 1280×720, 1.951.137 B, 8 CPU logich):

- remux: **bằng byte**, đổi đúng thứ tự atom `ftyp>free>mdat>moov` → `ftyp>moov>free>mdat`, 0,74 s.
- H.264 CRF 28 `veryfast`: **−53,8 %**, 4,16 s.
- H.265 CRF 30 `veryfast`: −53,2 %, 12,29 s.
- VP9 CRF 33 `cpu-used 5`: **+2,4 %**, 31,80 s trên clip ngắn này — VP9 **không**
  thắng về dung lượng cho clip ngắn, nó chỉ thắng ở chỗ WebM mở và không bằng sáng
  chế. Chọn nó vì định dạng, đừng chọn vì mong file nhỏ hơn.
- `ultrafast` **không phải tuỳ chọn tiết kiệm**: ra file **nặng hơn nguồn 59,7 %**.

## Sửa lỗi đi kèm

- **Hộp "Về" nói đúng phiên bản.** `core/settings.py:APP_VERSION` vẫn ghi `1.0.0`
  từ bản 1.0.1 tới 1.0.3 trong khi hai file cài đặt đã chạy 1.0.3. Cổng cũ
  (`settings.APP_VERSION in about`) xanh suốt vì nó so một chuỗi với chính nó;
  `scratch/release_meta.py` giờ đọc ba nguồn trong tree (`.iss`,
  `version_info.txt`, `settings.py`) và chết nếu lệch.
- `--startup-report` thêm cửa `boot_khong_keo_nen`: kéo tay hộp thoại nén lên
  đường boot làm chậm **0,428 s** mà hai cửa laziness cũ vẫn xanh, vì chúng chỉ
  nhìn đúng tên module của chúng.
- Sửa gate bundle: stdout UTF-8 (probe in bảng có dấu chết giữa bảng trên console
  cp1252, hai đoạn phía sau không chạy mà vẫn tưởng đã xong), đối chiếu ffmpeg
  thật, thêm phản chứng cho `_internal`.
- **Hộp thoại nén phải có mặt trong bundle, không chỉ trong tree nguồn.**
  `ui.compress_dialog` chỉ được nạp bằng một lệnh import bên trong
  `MainWindow._open_media_compress`, nên bản đóng gói thiếu nó thì menu
  "Nén / tối ưu tệp" crash đúng lúc người dùng bấm, trong khi `--selftest` chạy
  từ tree nguồn vẫn xanh đủ 38 dòng. `ClingingQt.spec` nay khai cặp
  `core.media_compress` + `ui.compress_dialog` trong `hiddenimports` ( cùng kiểu
  thumbnail/split/keyframe) và dòng selftest của nó import thẳng module đó; phản
  chứng bằng cách đổi tên vật lý file cho ra đúng một dòng đỏ
  `ModuleNotFoundError: No module named 'ui.compress_dialog'`, `rc=1`.

## Lưu ý

- **Chưa ký số.** SmartScreen có thể hiện *"Windows protected your PC"* — chọn
  *More info → Run anyway*. Bỏ qua được nếu bạn vừa tự tính SHA-256 ở bảng trên.
- **Cổng chạy trên bundle thật, không phải tree nguồn.**
  `dist\Clinging\Clinging.exe --selftest`: **38 dòng, `failed=[]`, rc=0**.
  `--startup-report` của cùng exe đó: `ok=True`, cửa sổ hiện lúc **0,977 s**,
  working set **68.872 KiB** ngay lúc cửa sổ hiện, và cả bốn cửa laziness đều
  `True` (`cv2`, `psutil`, `ui.main_window`, `ui.compress_dialog` chưa được nạp).
  Bản dựng 1.0.4 liền trước cùng tree nguồn (lúc 06:21, trước khi dựng lại
  `--clean` lúc 08:28) đo `boot_to_window_s` **0,718 s** — hai số của cùng mã nguồn
  lệch nhau 36 %, vì vậy con giây ở đây là một mẫu có dao động trên HDD máy này, còn
  bốn cửa `sys.modules` (đều `True`) mới là bất biến đáng tin (xem `AGENTS.md`, mục
  "Wall clock giữa hai lần chạy nói dối").
  `scratch/frozen_bundle_probe.py`: **ALL PASS, 0 fail, rc=0**, gồm ba phép phản
  chứng — lật `_internal/styles` (phải đỏ), ẩn `core/` rồi ẩn `ui/` của tree nguồn
  (phải vẫn xanh và chi tiết giống từng byte, tức mã đọc từ PYZ).
- `scratch/release_meta.py` đọc metadata từ chính hai file: `ProductVersion` 1.0.4,
  `FixedFileInfo 1.0.4.0`, `ProductCode {510B10E9-AE65-4B47-A3AC-4FB608873CA2}` mới,
  `UpgradeCode {322A4294-D740-42B3-9414-555BA07FDB88}` giữ nguyên như mọi bản trước.
- **Đã cài lên máy phát triển (22/10/2026), cả hai cây.** MSI bằng
  `msiexec /i ClingingSetup-1.0.4.msi INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`
  (rc=0, 39,7 s); Inno bằng `ClingingSetup-1.0.4.exe /VERYSILENT` chạy trong
  `scratch/installed_app_probe.py`. Hai cây đọc lại bằng nội dung, không bằng rc:
  `Clinging.exe` **6.967.178 B, sha256[:16] `6785b32b92e8d0b3`** — khớp `dist\Clinging`
  từng byte; cây Inno 365 leaf = 363 payload + `unins000.*`, set-diff đường dẫn
  tương đối với `dist` ra **0 thiếu / 0 thừa** ngoài cặp unins. Bản Inno cài sau nên
  giữ `.clinq` + shortcut Desktop (`Clinging.Project` → `...\Programs\Clinging\Clinging.exe "%1"`).
  `scratch/installed_app_probe.py`: **ALL PASS, 0 fail, rc=0**, 284,6 s, 221 dòng —
  gồm selftest của exe đã cài khớp bundle (38 dòng), cửa sổ thật capture,
  `.clinq` double-click, dự án THẬT của người dùng (`Dự án 2`) mở đúng thang cua
  dung phim và **còn nguyên byte** sau cả lần đo.
- **Một cổng trong bundle 1.0.4 báo đỏ trên một app lành**: `--split-report` của
  chính exe đã cài vẫn giữ `len(menu_actions) == 2`, mà menu card video từ bản này
  có ba hành động (thêm "Nén / tối ưu tệp…"). Số đo thật trong payload của nó đều
  đạt: 3 đoạn trên đĩa, mei cat `[0.0, 0.0]`, lệch màu `[0.0, 0.0, 0.0]`, thanh tiến
  trình 10 px @ DPR 1,25, 383 màu trong ảnh. Sửa nằm ở nguồn
  (`diagnostics.VIDEO_CARD_MENU` + `split_report_fails`, phản chứng
  `scratch/split_gate_counterfactual.py` **26/26, rc=0**), nên `installed_app_probe`
  chấm payload do exe đã cài bằng thang nguồn và ghi rc của exe thành một dòng
  chú. **Chỉ một lần dựng lại bundle mới làm exe tự trả 0.**
- Nâng cấp từ 1.0.3: cài đè trực tiếp được. Inno xoá `_internal` cũ trước khi giải
  nén; MSI dùng cùng `UpgradeCode` nên lần cài mới gỡ bản cũ trước khi ghi.
- Dự án `.clinq` hai chiều: 1.0.3 mở được file của 1.0.4 vì mọi khoá mới
  (`Chroma key`, in/out, audio detach) đều có giá trị mặc định và là no-op ở bản
  cũ; nhưng **đừng lưu lại bằng 1.0.3**: bộ serialize cũ không biết các khoá mới
  nên chúng mất khi ghi.
- Máy cấu hình thấp: bản này không thêm binary nào so với 1.0.3, và toàn bộ module
  mới (chroma, nén, cắt) nằm ngoài chuỗi boot — cửa sổ vẫn hiện mà `cv2`,
  `psutil`, `ui.main_window`, `ui.compress_dialog` đều chưa được nạp.
- **Nén tệp là thao tác ghi file mới, không sửa file nguồn**: đầu ra mặc định đặt
  cạnh nguồn với hậu tố `_toi_uu` / `_remux` / `_vp9`, file cũ giữ nguyên.
- Build từ mã nguồn cần tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (~205 MB,
  vượt giới hạn 100 MB/file của GitHub). **Bản cài đặt đã kèm sẵn cặp này.**
- Tài liệu quy trình kiểm chứng của bản dựng: `docs/verification-gates.md`,
  `docs/glyph-icons.md`.
- **Thay đổi chỉ phục vụ người phát triển, không đổi hành vi app.** `--selftest`
  nhận thêm cờ lọc dòng `--only=<chuoi>` (~5 s cho một dòng thay vì ~31 s cho đủ
  38 dòng), và sáu probe phản chứng nặng nhất đổi sang khuôn "baseline đủ bảng →
  từng phép đổi byte chạy lọc → một phép chạy lại đủ bảng → khôi phục đủ bảng".
  Nhờ vậy chuỗi gate nặng nhất giảm rõ: probe nén tệp 377,2 s → 183,7 s (17 phép),
  chroma 19 phép = 147,9 s, chỉnh màu 13 phép = 133,6 s, thẻ Cắt 12 phép = 136,6 s,
  tách âm thanh 10 phép = 87,5 s, style chữ 6 phép = 120,3 s. Các probe nhẹ hơn
  (lưu dự án, media locus, clipboard, undo, pop art) vẫn chạy đủ bảng ở mỗi phép.
  Thêm
  `scratch/needle_canary.py` (0,6 s) phát hiện probe có mẫu byte đã chết im lặng —
  nó tìm ra hai probe hỏng do tính năng mới chèn dòng vào giữa mẫu cũ. Không có
  `--only` thì `run_selftest()` chạy y như bản 1.0.3.
