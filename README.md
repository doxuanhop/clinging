# Clinqing — Professional Video Editor (UI Skeleton)

Giao diện desktop được dựng lại theo đúng bố cục trong ảnh chụp màn hình
bạn cung cấp, viết bằng **PySide6** (Qt for Python).

## 0. Tài liệu hiện hành

Các mục 3–6 bên dưới mô tả thời kỳ dựng skeleton UI và **đã cũ**: ứng dụng hiện
chạy engine video thật (giải mã tuần tự, xuất MP4 qua ffmpeg, ASR, chuyển cảnh,
layer âm thanh từng clip). Tài liệu đang đúng:

- `AGENTS.md` — hợp đồng làm việc trong repo: ràng buộc, lệnh, bẫy của máy build.
- `docs/verification-gates.md` — thế nào là "xong": gate trên đường production,
  phản chứng, ảnh chứng minh, đọc rc thật.
- `docs/glyph-icons.md` — bộ vẽ icon Font Awesome cục bộ (đã thay qtawesome) và
  các cổng đi kèm.
- `docs/release-1.0.2.md` — bản cài đặt đang phát hành: SHA-256, thay đổi so với 1.0.1.
- `docs/release-1.0.1.md` — bản 1.0.1 (bundle còn qtawesome) và bài học "cùng tên,
  khác payload".
- `docs/import_project.md` — định dạng file dự án `.clinq` và đường nhập dự án.

Chạy thử:

```bash
python main.py                                  # mo app
python main.py --selftest --report st.json      # 28 dong cong, xem key "failed"
python scratch/icon_name_audit.py               # ten glyph dung trong UI
```

Cần `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (không commit được vì vượt 100 MB/file
của GitHub); bản cài đặt đã kèm sẵn.

## 1. Cài đặt & chạy

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Yêu cầu Python 3.9+.

## 2. Cấu trúc project

```
clinqing_app/
├── main.py                  # Điểm khởi chạy
├── theme.py                 # Quản lý Dark/Light theme, bảng màu dùng khi vẽ tay
├── requirements.txt
├── styles/
│   ├── dark.qss              # Toàn bộ style Dark mode (giống ảnh mẫu)
│   └── light.qss             # Style Light mode tương ứng
├── widgets/
│   └── common.py             # IconButton, AnimatedTabBar, FadeStack, add_shadow()...
└── ui/
    ├── title_bar.py           # Thanh tiêu đề tùy biến (frameless, kéo di chuyển)
    ├── top_toolbar.py          # Logo, tên dự án, Undo/Redo, Lưu, Xuất video
    ├── sidebar.py              # Dải icon dọc: Thư viện, Tải lên, Âm thanh...
    ├── library_panel.py        # THƯ VIỆN TÀI NGUYÊN: tab + tìm kiếm + lưới thẻ
    ├── preview_panel.py        # Khung xem trước 9:16 + điều khiển phát
    ├── properties_panel.py     # Bảng Thuộc tính / Hiệu ứng (trạng thái rỗng)
    └── timeline_panel.py       # DYNAMIC TIMELINE: header, ruler vẽ tay, track
```

## 3. Những gì đã hoạt động thật (không phải chỉ là hình tĩnh)

- **Kéo–thả**: kéo một thẻ tài nguyên từ "Thư viện" thả vào khung xem trước
  hoặc vào Timeline → nội dung khung xem trước / track cập nhật theo thời gian thực.
- **Tải tệp thật**: bấm thẻ "+ Tải lên tài nguyên" hoặc icon "Tải lên" ở sidebar
  sẽ mở hộp thoại chọn file (`QFileDialog`) và thêm vào lưới.
- **Tab trượt mượt**: tab Video/Âm thanh/Hình ảnh/Sticker và tab
  Thuộc tính/Hiệu ứng có gạch chân trượt bằng `QPropertyAnimation`.
- **Chuyển trang mượt (fade)**: đổi tab ở bảng Thuộc tính có hiệu ứng mờ dần.
- **Timeline có thật**: thước thời gian được vẽ bằng `QPainter` (không phải
  ảnh tĩnh), có thanh playhead đỏ kéo/click để tua, và slider zoom timeline
  hoạt động thật (kéo giãn khoảng cách vạch giây).
- **Sáng / Tối (Light/Dark)**: nút hình tròn trên toolbar chuyển đổi toàn bộ
  theme của app tức thì bằng cách đổi `QSS` + màu vẽ tay trong `theme.py`.
- **Cửa sổ tùy biến**: title bar riêng (không viền OS mặc định), kéo để di
  chuyển cửa sổ, nút thu nhỏ/phóng to/đóng hoạt động thật.
- **Đổ bóng (shadow)**: nút "Xuất video" và các card có
  `QGraphicsDropShadowEffect` mềm mại giống enterprise app thật.

## 4. Những gì CHƯA làm (do đây là bước dựng giao diện — UI shell)

Phần **xử lý video thật** (decode/encode, render timeline thành file MP4,
áp hiệu ứng, ghép audio...) **chưa được cài đặt** — đây là một hệ thống
backend riêng biệt, thường dùng:

- `ffmpeg` / `ffmpeg-python` hoặc `moviepy` để decode/encode & xuất video.
- `PySide6.QtMultimedia` (`QMediaPlayer` + `QVideoWidget`) để phát preview
  thật trong khung canvas thay vì placeholder.
- Một `TimelineModel` (danh sách clip, track, thời lượng, hiệu ứng) làm
  nguồn dữ liệu chung cho cả Timeline UI và bộ máy render.

Mình đã chừa sẵn các "điểm nối" (signal `resourceDropped`, `exportRequested`,
class `TimelinePanel`/`PreviewCanvas`...) để cắm engine xử lý video vào mà
không phải viết lại giao diện.

## 5. Về Qt Designer (thiết kế kéo-thả)

Bạn hoàn toàn có thể mở **Qt Designer** (`pip install pyside6-tools` rồi chạy
lệnh `pyside6-designer`) để chỉnh sửa trực quan các panel, xuất ra file
`.ui`, sau đó nạp bằng `QUiLoader` hoặc biên dịch bằng `pyside6-uic` thành
Python. Cấu trúc hiện tại được viết code trực tiếp (không qua `.ui`) để dễ
đọc, dễ chỉnh và dễ AI hỗ trợ tiếp — nhưng hoàn toàn tương thích nếu bạn muốn
chuyển một phần sang Designer sau này.

## 6. Ghi chú môi trường build

Do môi trường tạo mã nguồn này không có kết nối internet để `pip install
PySide6` và chạy thử trực tiếp, mình đã kiểm tra cú pháp toàn bộ file bằng
`python -m py_compile` (không lỗi). Khi chạy trên máy bạn (có PySide6), nếu
gặp lỗi nhỏ về căn chỉnh pixel, hãy báo lại — rất dễ tinh chỉnh thêm.
