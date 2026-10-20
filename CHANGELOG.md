# CHANGELOG

Các thay đổi đáng chú ý của Clinging. Bản chi tiết cho người dùng cuối (kèm bảng
file tải về và SHA-256) nằm trong `docs/release-<ver>.md`; tài liệu quy trình kiểm
chứng nằm trong `docs/verification-gates.md`.

Mọi mục dưới đây đều đi kèm cổng `--selftest` chạy trên đúng đường production,
phản chứng chứng minh cổng đỏ vì đúng lý do, và ảnh `FrameComposer` cho phần render.

## [Unreleased]

Chưa đóng bundle/installer, chưa đẩy lên GitHub Releases — mới chỉ nằm trong tree
nguồn (commit `b894d2a`). Selftest: 33/33, `rc=0`.

### Thêm — định vị media & lưu dự án (nhóm A)

- **File media bị dời vẫn mở được.** Bộ giải đường dẫn mới
  (`core/media_locator.py`) dò lại vị trí thực của asset khi file đổi chỗ, dùng
  **chung cho cả preview lẫn export** nên hai bên ra cùng payload. Phản chứng
  `media_locator_counterfactual.py` (6 phép đổi byte), ảnh
  `media_locator_evidence.py`.
- **Lưu dự án nguyên tử, không để lệch `.clinq` thật.** Ghi ra file tạm rồi mới
  đổi tên; giữ 5 bản recovery gần nhất; một lần ghi hỏng (payload không serialize
  được) để file cũ còn nguyên từng byte. Phản chứng
  `save_atomic_counterfactual.py`, ảnh `save_atomic_evidence.py`.
- **Hoàn tác cho thao tác chữ và hình học.** `SetClipTextCommand` và
  `SetClipTransformCommand` nằm trong stack undo; các thao tác số liên tiếp trong
  0,75 s gộp thành một bước. Ảnh `undo_text_transform_evidence.py` chứng minh
  Ctrl+Z trả lại **từng pixel** giống khung gốc.

### Thêm — clipboard clip (nhóm B)

- **Nhân bản clip bằng Ctrl+C / Ctrl+V**, đặt qua đúng seam `place_clip` của dự án
  nên bản dán giữ nguyên font, hình học và media tham chiếu; có undo để gạch sạch
  bản dán. Phản chứng `clipboard_counterfactual.py`, ảnh `clipboard_evidence.py`.

### Thêm — style chữ (nhóm C)

- **Mười một trường style trên mỗi clip chữ:** màu + bề rộng viền, màu + lệch
  dx/dy + độ mờ bóng, màu + độ đậm + bán kính + đệm của hộp nền, và căn lề
  trái/giữa/phải.
- **Một seam duy nhất cho preview và export.** `core/text_paint.py:text_style_of`
  dựng dict style mà cả `TextClipItem.paint` lẫn `FrameComposer._draw_text` cùng
  đọc, nên thứ bạn thấy trên canvas đúng bằng thứ xuất ra file.
- **Máy yếu không bị đánh thuế.** Chỉ bật căn lề vẫn đi đường vẽ trực tiếp (không
  dựng lớp ảnh); cổng `--selftest` dựng sẵn để đỏ nếu căn lề bị kéo vào composite.
- **Điều khiển trong panel thuộc tính** (thẻ "Style chữ") và **có undo**.
- Phản chứng `text_styling_counterfactual.py` (6 phép đổi byte, mỗi phép làm cổng
  đỏ đúng một lý do), ảnh `text_styling_evidence.py` (8 ô: viền / bóng / bóng mờ /
  hộp nền / căn trái / căn phải / kết hợp).

## [1.0.2] - 2026-10

- Đưa `qtawesome` ra khỏi bundle: icon Font Awesome vẽ trực tiếp từ TTF, cắt ~0,62 s
  khởi động và ~30 MB RAM; boot nóng 0,84–0,95 s.
- Mở app không còn ghi đè `recent_projects.json`; mục không truy cập được vẫn giữ.
- Tên icon sai báo `ValueError` rõ chỗ gọi, không còn giết process kiểu `0xC0000409`.
- Chi tiết: `docs/release-1.0.2.md`.

## [1.0.1] - 2026-10

- Bản đóng gói đầu tiên có kèm cặp `ffmpeg`/`ffprobe`. Bundle vẫn chứa `qtawesome`.
- Chi tiết: `docs/release-1.0.1.md`.
