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

### Từ dòng lệnh hoặc nháy đúp trong Explorer

```bash
Clinging.exe "D:\Du an\Kiem chung.clinq"      # duong dan co dau cach van mo duoc
```

Đường này đi qua `main.py` → `MainController`, không qua Trang chủ: exe nhận tham số,
nếu giải được `.clinq` thì vào thẳng cửa dung phim với đúng clip/thư viện/tên/tỉ lệ của
file; đường dẫn không có thật thì **giữ nguyên cửa sổ đang mở**, không hiện timeline
trắng. `HKEY_CURRENT_USER\Software\Classes\.clinq → Clinging.Project` là do installer
per-user ghi, nên không cần quyền Admin. Cổng: `python main.py --project-report` và
`scratch/installed_app_probe.py` (lớp 11, gồm cả một cú `os.startfile` thật).

---

## Định dạng file `.clinq`

File `.clinq` là định dạng JSON chứa toàn bộ thông tin dự án. Block `assets`
mỗi file gốc chỉ xuất hiện một lần (chúc thu duong dan → id), clip chỉ tham
chiếu `asset_id` — không copy media vào thư mục dự án.

```json
{
  "project_meta": {
    "project_id": "proj-a1b2c3d4e5f6",
    "project_name": "Tên dự án",
    "created_at": "2025-01-15T10:30:00",
    "last_modified": "2026-10-21T09:12:44",
    "resolution": { "width": 1920, "height": 1080 },
    "fps": 30,
    "aspect_ratio": "16:9",
    "version": "1.0"
  },
  "assets": {
    "asset-4f9c21be07a1": {
      "type": "video",
      "path": "D:/Media/video01.mp4",
      "original_duration": 12.5
    }
  },
  "timeline": {
    "duration": 30.0,
    "playhead": 5.2,
    "recap_overlay": { "enabled": false, "...": "mot so khoa cua core/recap_overlay.py" },
    "tracks": [
      {
        "track_id": "track-1",
        "track_type": "VIDEO",
        "name": "Video 1",
        "z_index": 0,
        "is_main_track": true,
        "is_locked": false,
        "is_visible": true,
        "is_muted": false,
        "color": "#4FC3F7",
        "clips": [
          {
            "clip_id": "clip-1",
            "timeline_in": 0.0,
            "timeline_out": 10.0,
            "duration": 10.0,
            "source_duration": 12.5,
            "transform": {
              "x": 960.0, "y": 540.0,
              "scale_x": 1.0, "scale_y": 1.0,
              "rotation": 0.0, "opacity": 1.0,
              "fit_mode": "fit",
              "original_w": 1920.0, "original_h": 1080.0
            },
            "keyframes": {
              "scale_x": [[0.0, 1.0, "linear"], [2.5, 1.2, "ease_in_out"]]
            },
            "effects": [
              {
                "name": "Chinh mau",
                "category": "Chinh mau",
                "intensity": 1.0,
                "params": {
                  "hue_shift": 0.0, "lift": 0.0, "gamma": 1.0,
                  "gain": 1.05, "lut_path": "D:/LUTs/teal.cube"
                }
              }
            ],
            "transition": { "name": "Fade In", "duration": 0.5 },
            "font_family": "Arial", "font_size": 40.0,
            "font_bold": true, "font_italic": false, "font_underline": false,
            "font_color": "#FFFFFF",
            "text_effect": "none", "text_effect_intensity": 0.6,
            "text_style": "none",
            "text_outline_color": "#000000", "text_outline_width": 0.0,
            "text_shadow_color": "#000000",
            "text_shadow_dx": 0.0, "text_shadow_dy": 0.0, "text_shadow_blur": 0.0,
            "text_box_color": "#000000", "text_box_alpha": 0.0,
            "text_box_radius": 8.0, "text_box_padding": 12.0,
            "text_align": "center",
            "sticker_icon": "", "sticker_color": "#FFFFFF",
            "volume": 1.0, "speed": 1.0, "fade_in": 0.0, "fade_out": 0.0,
            "audio_muted": false,
            "asset_id": "asset-4f9c21be07a1",
            "trim_in": 1.2, "trim_out": 11.2,
            "source_path": "D:/Media/video01.mp4",
            "media_type": "video",
            "name": "video01"
          }
        ]
      }
    ]
  }
}
```

Chu ý ve schema:

- Ten mốc thời gian của clip là `timeline_in` / `timeline_out`, KHÔNG phải
  `start_time` / `end_time`.
- Clip chữ (`media_type: "text"`) có `asset_id: null`, `source_path: ""` và
  nội dung nằm trong `text_content` (trùng giá trị với `name`).
- Mười mốt trường style chữ (`text_style`, `text_outline_*`, `text_shadow_*`,
  `text_box_*`, `text_align`) và bốn trường âm thanh + `audio_muted` luôn được
  ghi ra, kể cả khi mặc định — bộ đọc dùng `.get(key, default)` nên file cũ
  thiếu chúng vẫn mở được.
- Bo chỉnh màu là MỘT `EffectData` tên `Chinh mau` nằm trong `effects`, không
  phải trường riêng của clip. `core/clip_effects.py:GRADING_IDENTITY` là giá
  trị trung tính; khi cả năm núm về trung tính thì lệnh undo bỏ hẳn card, nên
  file không chứa rác.

**Tương thích một chiều.** Bộ đọc dùng `.get(key, default)` cho mọi trường mới,
nên 1.0.3 mở thoải mái file do 1.0.0–1.0.2 lưu ra. Ngược lại thì không: bản 1.0.2
không biết 11 trường style chữ và card `Chinh mau`, nên **đừng lấy 1.0.2 lưu đè**
lên dự án đã chỉnh bằng 1.0.3 — một lần Ctrl+S là mất style và màu.

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
ProjectManager.project_path = project_path
    ↓
load_project_from_file(project_path)  →  dict JSON   (lỗi → None, không mở)
    ↓
restore_model_from_clinq(model, project, media_roots)  →  TimelineModel
    ↓  (bên trong: resolve_model() dinh vi media lac cho, MOT lan)
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

- Tối đa **10 dự án** gần đây (`projects[:10]` lúc ghi)
- Khi nhập hoặc tạo dự án, nó được đẩy lên đầu danh sách; mục đã có thì chuyển lên chứ không nhân bản
- Đường **đọc** (`_load_recent_projects()`) chỉ lọc dự án mất đường dẫn khỏi MÀN HÌNH
  hiển thị, **không ghi lại file**. Trước 1.0.2 nó ghi `valid_projects` ngay lúc mở app,
  nên một lần "chỉ xem" trên ổ rời chưa cắm / thư mục vừa đổi tên là mất mục vĩnh viễn.
  Gate: selftest dòng `doc MRU khong ghi du lieu nguoi dung` +
  `scratch/recent_projects_safety_probe.py`.

---

## Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| File không tồn tại | Hiện cảnh báo "File không tồn tại"; đường argv thì **giữ nguyên cửa sổ đang mở** |
| File không phải JSON | `load_project_from_file()` trả `None` → không mở, in `Loi doc du an` |
| File bị hỏng/malformed | Như trên. Vì ghi là atomic, file dich không bao giờ ở trạng thái nửa vời — lỗi đọc chỉ đến từ file thật sự hỏng |
| Ghi thất bại giữa chừng (đĩa đầy, process bị giết) | File `.clinq` cũ **còn nguyên**; bản sao trước lần ghi nằm trong `~/.clinqing/recovery/` |
| Media lac cho (doi/duy chuyen file goc) | `core/media_locator.py` dinh vi lai MOT lan luc mo du an, ca preview lan export cung nhin mot duong dan |
| Permission denied | Hiện dialog lỗi; lưu thất bại trả `False`, không xóa recovery copy |

---

## Lưu atomic và bản cứu (từ 1.0.3)

Đường ghi duy nhất là `save_project_to_file()` (`core/project_storage.py:229`):

1. `json.dumps` **trước** khi chạm vào file thật — payload hỏng thì file cũ còn nguyên.
2. `_rotate_recovery_copy()` chép bản đang có vào `~/.clinqing/recovery/<stem>__<timestamp>.clinq`,
   giữ tối đa `RECOVERY_KEEP = 5` bản mới nhất (`_prune_recovery`).
3. `_write_bytes_atomic()` ghi `target.tmp` cùng thư mục + `fsync` rồi `os.replace` —
   đổi tên là atomic trên Windows, nên file dich luôn là một bản trọn vẹn.

Autosave (`~/.clinqing/autosave.json`) đi qua **cùng** hai hàm đó nhưng **không**
rotate recovery: thư mục dự án của người dùng không tự nhiên mọc thêm file, và bản
cứu chỉ tính cho file `.clinq` họ đã đặt tên.

Gate: selftest dòng `luu du an: ghi hong khong pha ban cu`,
`scratch/save_atomic_counterfactual.py` (4 phép đổi byte trên đường lưu) và
`scratch/save_atomic_evidence.py` (ảnh + JSON: bản cũ được quay lại, lần ghi hỏng không phá file).

---

## Định vị lại media lac cho

`core/media_locator.py` trả về đường dẫn mới cho file media không còn ở đường đã lưu.
Mac định:

- Kinh tim kiem: `MAX_DEPTH = 4`, `MAX_ENTRIES = 2000 muc` (do: thuc muc du an
  2.000 muc het duoi 40 ms, con `os.walk(".")` tu cwd cua exe da cai mo toi hang
  chuc ngan muc).
- Bo qua `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `$RECYCLE.BIN`,
  `System Volume Information` va bat ky thu muc bat dau dau bang `.`.
- Chieu duy nhat: `restore_model_from_clinq(..., media_roots=...)` goi
  `resolve_model()` MOT lan sau khi model lap day, tuc la chi doc dia luc mo du an,
  khong bao gio trong vong lap ve frame. Preview va export cung doc `clip.source_path`
  da duoc dinh vi, nen khong the lech.

Gate: selftest dòng `media lac cho: preview va export cung duong dan`,
`scratch/media_locator_counterfactual.py` (6 phép đổi byte) và
`scratch/media_locator_evidence.py` (ảnh: file bị đơn vẫn ra cùng payload ở preview lẫn export).

---

## Các hàm liên quan

| Hàm | File | Vai trò |
|---|---|---|
| `_on_import_project()` | `ui/home_page.py` | Mở file dialog, kiểm tra tồn tại, đẩy vào MRU |
| `_on_open_project()` | `ui/main_controller.py` | Nhận path, khởi tạo editor, load data |
| `project_arg_from_argv()` | `core/project_storage.py` | Đọc `.clinq` từ dòng lệnh / Explorer |
| `load_project_from_file()` | `core/project_storage.py` | Đọc file `.clinq` → dict JSON (lỗi → `None`) |
| `save_project_to_file()` | `core/project_storage.py` | Serialize + recovery + ghi atomic |
| `restore_model_from_clinq()` | `core/project_storage.py` | Áp dict vào `TimelineModel`, gọi `resolve_model()` |
| `resolve_model()` / `locate()` | `core/media_locator.py` | Định vị lại media lac cho, mot chieu chung |
| `ProjectManager` | `core/project_storage.py` | Nắm `project_path` / `project_id` / `project_meta` |
| `load_recent_projects()` | `ui/home_page.py` | Đọc MRU — **chỉ đọc, không ghi lại** |
| `save_recent_projects()` | `ui/home_page.py` | Ghi MRU, cắt `[:10]` |

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
