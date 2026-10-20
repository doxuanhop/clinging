# Nhập Dự Án (Import Project)

## Tổng quan

Chức năng **Nhập dự án** cho phép người dùng mở file `.clinq` có sẵn từ thiết bị vào Clinging để chỉnh sửa tiếp. Khác với tạo dự án mới (tạo file rỗng), nhập dự án sẽ load toàn bộ dữ liệu timeline, clip, hiệu ứng và cài đặt từ file đã lưu.

---

## Cách sử dụng

### Từ Trang chủ

1. Mở Clinging → Trang chủ
2. Nhấn nút **"Nhập dự án"** (thẻ cuối cùng trong phần "Tạo dự án mới")
3. Hộp thoại chọn file hiện ra → duyệt đến file `.clinq` cần nhập
4. Nhấn **"Mở"**
5. Dự án được tải vào Trình dựng phim

### Từ Menu

1. Vào **Menu → Tệp tin → Nhập dự án...**
2. Chọn file `.clinq` từ thiết bị
3. Dự án mở trong editor

---

## Định dạng file `.clinq`

File `.clinq` là định dạng JSON chứa toàn bộ thông tin dự án:

```json
{
  "project_meta": {
    "project_id": "proj-a1b2c3d4e5f6",
    "project_name": "Tên dự án",
    "created_at": "2025-01-15T10:30:00",
    "resolution": { "width": 1920, "height": 1080 },
    "fps": 30,
    "aspect_ratio": "16:9",
    "version": "1.0"
  },
  "assets": {
    "asset-id-1": {
      "source_path": "/path/to/video.mp4",
      "media_type": "video",
      "duration": 12.5,
      "name": "video01.mp4"
    }
  },
  "timeline": {
    "duration": 30.0,
    "playhead": 5.2,
    "tracks": [
      {
        "track_id": "track-1",
        "track_type": "video",
        "name": "Video 1",
        "clips": [
          {
            "clip_id": "clip-1",
            "source_path": "/path/to/video.mp4",
            "media_type": "video",
            "start_time": 0.0,
            "end_time": 10.0,
            "duration": 10.0,
            "name": "video01",
            "transform": {
              "x": 960, "y": 540,
              "scale_x": 1.0, "scale_y": 1.0,
              "rotation": 0.0,
              "opacity": 1.0,
              "fit_mode": "fit"
            },
            "effects": [],
            "keyframes": {}
          }
        ]
      }
    ]
  }
}
```

---

## Luồng xử lý kỹ thuật

### 1. Chọn file (Home Page)

```
User nhấn "Nhập dự án"
    ↓
QFileDialog.getOpenFileName()
    filter: "Clinging Project (*.clinq)"
    ↓
Kiểm tra file tồn tại
    ↓
Thêm vào danh sách gần đây (recent_projects.json)
    ↓
Emit openProject(file_path)
```

### 2. Tải dự án (Main Controller)

```
_on_open_project(project_path)
    ↓
ProjectManager().project_path = project_path
    ↓
load_project_from_file(project_path)  →  dict JSON
    ↓
restore_model_from_clinq(model, project)  →  TimelineModel
    ↓
Sync canvas, cập nhật UI
```

### 3. Cấu trúc ProjectManager

| Thuộc tính | Mô tả |
|---|---|
| `project_path` | Đường dẫn file `.clinq` hiện tại |
| `project_id` | UUID duy nhất của dự án |
| `project_meta` | Dict chứa tên, FPS, resolution, aspect_ratio |

---

## Danh sách gần đây

File lưu trữ: `%APPDATA%/Clinging/recent_projects.json`

```json
[
  "C:/Users/user/Clinging_Projects/Dự án 1/Dự án 1.clinq",
  "C:/Users/user/Clinging_Projects/Dự án 2/Dự án 2.clinq"
]
```

- Tối đa **10 dự án** gần đây
- Khi nhập dự án mới, nó được đẩy lên đầu danh sách
- Dự án không tồn tại trên ổ đĩa sẽ bị lọc bỏ tự động

---

## Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| File không tồn tại | Hiện cảnh báo "File không tồn tại" |
| File không phải định dạng `.clinq` | Lỗi parse JSON → thông báo lỗi |
| File bị hỏng/malformed | `load_project_from_file` trả về `None` → không mở |
| File nằm trên ổ đĩa mạng bị mất kết nối | Fallback về autosave local |
| Permission denied | Hiện dialog lỗi |

---

## Các hàm liên quan

| Hàm | File | Vai trò |
|---|---|---|
| `_on_import_project()` | `home_page.py` | Mở file dialog, xử lý chọn file |
| `_on_open_project()` | `main_controller.py` | Nhận path, khởi tạo editor, load data |
| `load_project_from_file()` | `project_storage.py` | Đọc file `.clinq` → dict JSON |
| `restore_model_from_clinq()` | `project_storage.py` | Áp dụng dict vào TimelineModel |
| `load_recent_projects()` | `home_page.py` | Đọc danh sách gần đây |
| `save_recent_projects()` | `home_page.py` | Ghi danh sách gần đây |

---

## Ví dụ thực tế

### Nhập dự án từ USB

```
1. Copy file "MyProject.clinq" từ USB sang máy
2. Mở Clinging → Nhập dự án
3. Duyệt đến thư mục trên USB
4. Chọn file → Mở
```

### Nhập dự án backup

```
1. Trước đó đã export backup: D:\Backup\video_project.clinq
2. Mở Clinging → Nhập dự án
3. Chọn D:\Backup\video_project.clinq
4. Dự án khôi phục đầy đủ timeline + effects
```

---

## So sánh: Tạo mới vs Nhập dự án

| | Tạo dự án mới | Nhập dự án |
|---|---|---|
| **File đầu vào** | Không có | File `.clinq` có sẵn |
| **Timeline** | Trống | Có dữ liệu clip, track |
| **Assets** | Thư mục trống | Các file media đã link |
| **Project name** | Tự đặt | Đọc từ file |
| **Recent list** | Thêm mới đầu danh sách | Thêm/di chuyển lên đầu |
