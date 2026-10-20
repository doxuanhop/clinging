# Clinging - Video Editor

**Clinging** là phần mềm biên tập video mã nguồn mở với giao diện đồ họa, hỗ trợ nhiều tính năng biên tập video, audio, thêm text, hiệu ứng và xuất video.

## Mục lục

1. [Cài đặt](#cài-đặt)
2. [Giao diện chính](#giao-diện-chính)
3. [Import Media](#import-media)
4. [Thuộc tính Video](#thuộc-tính-video)
5. [Cắt Video & Audio](#cắt-video--audio)
6. [Thuộc tính Text](#thuộc-tính-text)
7. [Hiệu ứng Động (Motion)](#hiệu-ứng-động-motion)
8. [Xóa Logo/Watermark](#xóa-logowatermark)
9. [Thay thế Audio](#thay-thế-audio)
10. [Xuất Video](#xuất-video)
11. [Text to Speech & Auto Captions](#text-to-speech--auto-captions)
12. [Phím tắt](#phím-tắt)

---

## Cài đặt

### Yêu cầu hệ thống
- Python 3.8+
- Windows 10/11

### Cài đặt thư viện
```bash
pip install -r requirements.txt
```

### Chạy phần mềm
```bash
python main.py
```

### Thư viện cần thiết
- `moviepy` - Xử lý video
- `customtkinter` - Giao diện người dùng
- `PIL` - Xử lý hình ảnh
- `opencv-python` - Xử lý video nâng cao
- `faster-whisper` - Nhận dạng giọng nói (Auto Captions)
- `gTTS` - Chuyển text thành giọng nói (TTS)
- `playsound` - Phát âm thanh

---

## Giao diện chính

Giao diện Clinging gồm các phần chính:

```
┌─────────────────────────────────────────────────────────────┐
│  Menu   │  💾 Lưu   │  Export  │                    [─][□][×] │
├─────────────────────────────────────────────────────────────┤
│                    │                                             │
│   Assets Panel     │              Player Preview                  │
│   (Bên trái)      │            (Giữa màn hình)                  │
│                   │                                             │
├───────────────────┴─────────────────────────────────────────┤
│                  Timeline Editor                               │
│            (Thanh thời gian bên dưới)                      │
├─────────────────────────────────────────────────────────────┤
│                  Properties Panel                            │
│            (Panel thuộc tính bên phải)                     │
└─────────────────────────────────────────────────────────────┘
```

### Assets Panel (Panel tài sản)
- **Media**: Import video, audio, hình ảnh
- **Text**: Thêm text, template, Auto Captions, TTS
- **Transitions**: Hiệu ứng chuyển cảnh
- **Effects**: Hiệu ứng video
- **Elements**: Element đặc biệt
- **Stickers**: Sticker dán

---

## Import Media

### Cách import
1. Nhấn nút **Import ▾** trên toolbar hoặc nút **+ Import Media**
2. Chọn file video/audio/hình ảnh
3. File được thêm vào Assets và Timeline

### Định dạng hỗ trợ
- **Video**: MP4, AVI, MOV, MKV, WebM
- **Audio**: MP3, WAV, M4A, FLAC, OGG
- **Hình ảnh**: PNG, JPG, JPEG, BMP, GIF

### Thumbnails
- Tự động tạo thumbnail cho các file media
- Hiển thị trong panel Assets

---

## Thuộc tính Video

### Tab Cơ bản
- **Độ sáng** (Brightness): -100 đến +100
- **Độ tương phản** (Contrast): -100 đến +100  
- **Độ bão hòa** (Saturation): -100 đến +100
- **Hue** (Tint): 0 đến 360
- **Làm mờ** (Blur): 0 đến 50
- **Khử nhiễu** (Denoise): Bật/Tắt

### Tab Crop
- **Cắt xén**: Điều chỉnh vùng hiển thị
- **Left/Right/Top/Bottom**: Điều chỉnh từng cạnh

### Tab Rotate
- **Xoay**: Xoay video theo độ (0-360)
- **Lật ngang**: Lật theo trục X
- **Lật dọc**: Lật theo trục Y

### Tab Color
- **Màu overlay**: Chọn màu phủ lên video
- **Độ mờ**: Điều chỉnh độ trong suốt

### Tab Rotate (Video)
- **Xoay**: 90°, 180°, 270°, 360°
- **Lật**: Ngang, Dọc

---

## Cắt Video & Audio

### Cắt Video

**Cách 1: Sử dụng nút cắt**
1. Chọn clip trên timeline
2. Nhấn nút **✂** trên thanh công cụ
3. Chọn thời điểm cắt trên timeline điểm cần cắt
4. Nhấn **Cắt** để chia video thành 2 phần

**Cách 2: Right-click menu**
1. Chuột phải vào clip trên timeline
2. Chọn **Cắt Video** → **Tại vị trí con trỏ** hoặc **Tại vị trí playhead**

### Cắt Audio

**Tương tự như cắt video:**
1. Chọn clip audio trên timeline
2. Right-click → **Cắt Audio** → **Tại vị trí con trỏ**
3. Audio được chia thành 2 phần

### Thuộc tính cắt thủ công (Properties Panel)

Tab **Cắt audio** trong Properties Panel cho phép:
- **Số đoạn cắt**: 1-5 đoạn
- **Thời điểm bắt đầu/Thời lượng**: Nhập thủ công
- **Định dạng xuất**: MP3, WAV, M4A, OGG

---

## Thuộc tính Text

### Thêm Text mới
1. Vào tab **Text** trong Assets Panel
2. Nhấn **+ Thêm Text**
3. Text được thêm vào timeline với thời lượng mặc định 5 giây

### Thuộc tính text (Properties Panel)

Tab **Văn bản** hiển thị:

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nội dung** | Text hiển thị |
| **Font** | Phông chữ (Arial, Times,...) |
| **Cỡ chữ** | Kích thước font (8-200) |
| **Màu chữ** | Màu văn bản |
| **Màu nền** | Màu nền text |
| **Vị trí X** | Vị trí ngang (0.0-1.0) |
| **Vị trí Y** | Vị trí dọc (0.0-1.0) |

**Vị trí**: 
- `0.5, 0.5` = Giữa màn hình
- `0.5, 0.9` = Dưới cùng (phụ đề)
- `0.5, 0.1` = Trên cùng

### Template Text
Tab **Text Templates** cung cấp các template có sẵn:
- Background colored
- Outlined text
- Shadowed text
- Subtitle style

### Chỉnh sửa trực tiếp trên Player
- **Click và kéo**: Di chuyển text
- **Nhập nội dung**: Click vào text trên preview

---

## Hiệu ứng Động (Motion)

### Motion Effects Tab
1. Vào tab **Hiệu ứng động** trong Properties Panel
2. Chọn hiệu ứng từ danh sách

### Các hiệu ứng có sẵn

| Hiệu ứng | Mô tả |
|----------|-------|
| **Fade In** | Mờ dần vào |
| **Fade Out** | Mờ dần ra |
| **Zoom In** | Phóng to vào |
| **Zoom Out** | Thu nhỏ ra |
| **Slide Left** | Trượt sang trái |
| **Slide Right** | Trượt sang phải |
| **Slide Up** | Trượt lên |
| **Slide Down** | Trượt xuống |
| **Rotate** | Xoay quanh tâm |
| **Pulse** | Đập nhịp |
| **Blink** | Nhấp nháy |
| **Wave** | Sóng |

### Áp dụng hiệu ứng
1. Chọn clip trên timeline
2. Chọn hiệu ứng trong danh sách
3. Nhấn **Xem trước** để xem thử
4. Nhấn **✓ Áp dụng Motion** để lưu

---

## Xóa Logo/Watermark

### Tab Xóa Logo trong Properties Panel

**Các phương pháp:**

| Phương pháp | Mô tả |
|------------|-------|
| **Inpaint** | Dùng AI thông minh (cần OpenCV) |
| **Blur** | Làm mờ vùng logo |
| **Cover** | Phủ đè hình ảnh khác |

### Cách sử dụng

1. Chọn clip video
2. Vào tab **Xóa Logo** trong Properties Panel
3. Nhấn **🎯 Bắt đầu chọn vùng**
4. Vẽ hình chữ nhật quanh logo trên preview
5. Chọn phương pháp xử lý
6. Nhấn **✓ Áp dụng**

---

## Thay thế Audio

### Tab Thay Audio

1. Chọn clip video trên timeline
2. Vào tab **Thay Audio** trong Properties Panel
3. Chọn file audio mới hoặc nhập URL
4. Nhấn **Xử lý** để thay thế

### Tách Audio từ Video

1. Vào menu **Công cụ** → **Tách Audio**
2. Chọn file video nguồn
3. Chọn thư mục lưu
4. Nhấn **Tách**

---

## Xuất Video

### Xuất (Export)

1. Nhấn nút **Export** trên toolbar
2. Chọn thư mục lưu file xuất
3. Đặt tên file

### Tùy chọn xuất

| Tùy chọn | Mô tả |
|----------|-------|
| **Format** | MP4, AVI, MOV, MKV |
| **Codec** | H.264, H.265, VP9 |
| **Quality** | Cao, Trung bình, Thấp |
| **Resolution** | 1080p, 720p, 480p |
| **FPS** | 24, 30, 60 |

### Tỷ lệ khung hình (Aspect Ratio)

| Tỷ lệ | Kích thước |
|-------|------------|
| **16:9** | 1920x1080 |
| **9:16** | 1080x1920 |
| **1:1** | 1080x1080 |
| **4:3** | 1440x1080 |

---

## Text to Speech & Auto Captions

### Auto Captions (Tạo phụ đề tự động)

1. Import video vào timeline
2. Vào tab **Text** trong Assets Panel
3. Nhấn **Tạo phụ đề tự động (AI)**
4. Chọn ngôn ngữ (Auto, Vietnamese, English,...)
5. Đợi xử lý hoàn tất
6. Text clips được thêm vào timeline

**Yêu cầu:** `faster-whisper`

### Text to Speech (Chuyển text thành giọng nói)

1. Vào tab **Text** trong Assets Panel
2. Nhấn **Chuyển Text thành giọng nói**
3. Nhập văn bản cần chuyển
4. Chọn ngôn ngữ và tốc độ
5. Nhấn **Tạo âm thanh** để nghe thử

**Ngôn ngữ hỗ trợ:** Vietnamese, English, Chinese, Japanese, Korean

**Tốc độ:** 0.5x, 0.75x, 1.0x, 1.25x, 1.5x

**Yêu cầu:** `gTTS`, `playsound`

---

## Speech to Text (Chuyển giọng nói thành văn bản)

### Tách âm thanh từ video

1. **Speech to Text** trong tab **Media** của Assets
2. Chọn file video/audio nguồn
3. Chọn ngôn ngữ
4. Chọn định dạng xuất (TXT hoặc SRT)
5. Nhấn **▶ Bắt đầu chuyển đổi**

### Kết quả

- File text được lưu cùng thư mục với video gốc
- Định dạng SRT hỗ trợ hiển thị subtitle trong video player

---

## Phím tắt

| Phím | Chức năng |
|------|-----------|
| **Space** | Phát/Tạm dừng video |
| **← / →** | Frame trước/sau |
| **Home** | Đầu video |
| **End** | Cuối video |
| **Delete** | Xóa clip đang chọn |
| **Ctrl+S** | Lưu dự án |
| **Ctrl+E** | Mở Export |
| **Ctrl+I** | Import media |
| **+/-** | Zoom timeline |

---

## Lưu ý

1. **FFmpeg**: Cần cài đặt FFmpeg để sử dụng một số tính năng:
   - Tách audio từ video
   - Thay thế audio
   - Một số hiệu ứng
   
2. **Thư mục output**: Mặc định lưu tại `~/Clinging_Output`

3. **Tỷ lệAspect**:
   - 16:9: Video ngang phổ biến
   - 9:16: Video dọc (TikTok, Reels)
   - 1:1: Video vuông (Instagram)

4. **Xử lý nền**: Các tác vụ nặng (Export, xử lý video) chạy trong thread nền để không block giao diện

---

## Giải quyết sự cố

### Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách khắc phục |
|-----|------------|---------------|
| **FFmpeg not found** | Chưa cài FFmpeg | Cài đặt FFmpeg và thêm vào PATH |
| **Import Error** | Thiếu thư viện | pip install -r requirements.txt |
| **AudioFileClip not available** | Moviepy version | Dùng FFmpeg thay thế |
| **Invalid command name** | Lỗi Tkinter | Đóng cửa sổ và thử lại |

### Cài đặt FFmpeg

```bash
# Tải từ https://ffmpeg.org/
# Giải nén và thêm vào PATH Windows
```

Hoặc sử dụng Chocolatey:
```bash
choco install ffmpeg
```

---

## Thông tin

- **Phiên bản**: 1.0
- **Giấy phép**: MIT
- **Ngôn ngữ giao diện**: Tiếng Việt
- **Nền tảng**: Windows

---

*Tài liệu được tạo cho Clinging Video Editor*