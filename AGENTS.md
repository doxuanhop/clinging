# Clinging — chỉ dẫn cho agent

File này là hợp đồng làm việc trong repo. Đọc hết trước khi sửa. Quy trình kiểm
chứng đầy đủ: `docs/verification-gates.md`. Pipeline icon: `docs/glyph-icons.md`.

## Ứng dụng là gì

- Editor video PySide6 (Qt for Python), chạy per-user trên Windows 10/11 64-bit.
  Điểm vào `main.py`, controller `ui/main_controller.py`, model trong `core/`,
  backend ASR trong `src/asr`, bộ lọc/giải mã trong `widgets/` + `core/`.
- `legacy_tk/` là bản CustomTkinter cũ, **đóng băng** — không sửa, không port ngược.
- Build: `ClingingQt.spec` (PyInstaller onedir → `dist\Clinging`) rồi
  `packaging\clinging.iss` (Inno) và `packaging\make_msi.py` (WiX 3.11, per-user).
  `heat dir dist\Clinging` lấy danh sách file từ bundle thật, nên `build/`, `dist/`,
  `*.msi` bị ignore — đừng cố commit.
- Máy này có hai bản cài song song: Inno ở `%LOCALAPPDATA%\Programs\Clinging`,
  MSI ở `%LOCALAPPDATA%\Programs\ClingingMSI`. Bản cài sau chiếm shortcut Desktop
  và phần mở rộng `.clinq`. Dữ liệu người dùng: `%APPDATA%\Roaming\Clinging`.
  **`INSTALLFOLDER` mặc định của `.msi` là `Programs\Clinging`** (trùng cây Inno):
  `msiexec /i ... /qn` không kèm thuộc tính sẽ gỡ product cũ trong `ClingingMSI`,
  xóa thư mục đó, rồi ghi payload đè lên cây Inno — vẫn báo `rc=0` và
  "MainEngineThread is returning 0". Luôn cài dạng
  `MSYS_NO_PATHCONV=1 msiexec /i <msi> INSTALLFOLDER="%LOCALAPPDATA%\Programs\ClingingMSI" /qn`
  rồi đọc lại cả hai cây + khóa HKCU Uninstall, đừng tin mỗi mã thoát (trả giá
  21/10/2026 khi ship 1.0.3).
- Repo public: `github.com/doxuanhop/clinging`, Release `v1.0.3` (hai asset
  `.exe` + `.msi`, tag gắn trên `7ee04b6`). Release `v1.0.2` là bundle liền trước,
  `v1.0.1` vẫn tồn tại nhưng là bundle còn qtawesome.
  Clone mới muốn
  build phải tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (không commit được,
  vượt 100 MB/file).

## Lệnh hay dùng

```bash
python main.py                                  # chay app binh thuong
python main.py --selftest                       # 34 dong cong, bao JSON co "failed"
python main.py --startup-report                 # boot theo tung pha + control cung land
python main.py --layout-report | --alignment-report | --graph-report
python main.py --style-report | --project-report | --thumbnail-report
python scratch/icon_name_audit.py               # ten glyph + tham so tren toan bo nguon
python scratch/gate_discrimination_probe.py     # phan chung: moi cua phai do vi dung ly do
python scratch/boot_laziness_counterfactual.py  # phan chung: boot khong duoc keo trang dung phim/psutil
python scratch/save_atomic_counterfactual.py    # phan chung: 4 phep doi byte o duong luu du an
python scratch/media_locator_counterfactual.py  # phan chung: 6 phep doi byte o chieu dinh vi media
python scratch/save_atomic_evidence.py          # anh + JSON: ban cu duoc quay, lan ghi hong khong pha file
python scratch/media_locator_evidence.py        # anh + JSON: file bi don van ra cung payload o preview va export
python scratch/undo_text_transform_counterfactual.py  # phan chung: tat push chu + mo merges_with -> cua undo do dung ly do
python scratch/undo_text_transform_evidence.py  # anh FrameComposer: doi chu/hinh hoc lech pixel, Ctrl+Z tra bang het
python scratch/clipboard_counterfactual.py      # phan chung: tat place_clip + clipboard rong + mat le + undo khong xoa -> cua clipboard do
python scratch/clipboard_evidence.py            # anh FrameComposer: ban dan giong het goc, Ctrl+Z gach ban dan ve nen
python scratch/text_styling_counterfactual.py   # phan chung: 6 phep doi byte -> cua style chu do dung ly do
python scratch/text_styling_evidence.py         # anh FrameComposer: vien/bong/bong mo/hop nen/can le ve ra that
python scratch/color_grading_ui_probe.py        # 8 cua chinh mau tren MainWindow that (nut LUT, keo, Ctrl+Z, .clinq)
python scratch/color_grading_counterfactual.py  # phan chung: 13 phep doi byte -> cua chinh mau do dung ly do
python scratch/color_grading_evidence.py        # anh FrameComposer + the panel: hue/lift/gamma/gain/LUT ve ra that
python scratch/popart_project_build.py          # du an .clinq Pop Art + xuat mp4 that, moi cua do tren FILE
python scratch/popart_project_counterfactual.py # phan chung: 6 phep doi byte, moi phep chay CA HAI gate
python scratch/popart_window_shot.py            # anh cua so THAT cua ban da cai mo du an Pop Art (PrintWindow)
python scratch/popart_window_shot.py --pixels   # phan chung tren anh: khung den do, anh that xanh, boi preview do
python scratch/boot_low_spec_probe.py           # 5 vong xuyen tat: boot/WS/private + seam icon (may phai yen)
python scratch/wall_to_window_probe.py          # do lan chuong TU BEN NGOAI (Popen -> cua so hien)
python scratch/boot_phase_profile.py            # tam chia pha MainController() bang cProfile
python scratch/user_data_snapshot.py capture scratch/_snap_before.json  # truoc khi do
python scratch/user_data_snapshot.py capture scratch/_snap_after.json   # sau khi do
python scratch/user_data_snapshot.py diff scratch/_snap_before.json scratch/_snap_after.json
python scratch/release_meta.py build/installer/ClingingSetup-<ver>.msi build/installer/ClingingSetup-<ver>.exe
python scratch/msi_payload_check.py             # payload MSI == cay dist, khong can cai
python scratch/github_release.py doxuanhop/clinging v<ver> --name "Clinging <ver>" \
    --body-file docs/release-<ver>.md build/installer/ClingingSetup-<ver>.exe \
    build/installer/ClingingSetup-<ver>.msi
```

## Ràng buộc thường trực (nguyên văn từ chủ repo)

1. **"Chỉ thay giao diện, giữ logic."** Muốn đổi hành vi thì phải nói rõ và được
   duyệt, không nhân danh "làm cho đẹp".
2. **"Loại bỏ rác."** Không để file chết, hàm không ai gọi, log thử nghiệm, thư
   mục tạm. Xóa xong phải chạy lại gate. Probe tạm (`_*_child.py`, `_audit_variant.py`)
   phải bị xóa trong `finally`.
3. **"Tối ưu cho máy có cấu hình thấp."** Mọi tính năng mới phải chịu câu hỏi: nó
   thêm bao nhiêu giây vào boot, bao nhiêu MB RAM thường trú. Import nặng thì lazify,
   thumbnail thì cache ra đĩa.
4. **"Không đụng chạm dữ liệu người dùng, có gate + ảnh chứng minh."** Không dùng
   dự án/bài hát/video của người dùng làm fixture. Trước và sau mỗi bước đo:
   snapshot → chạy → diff phải ra `0 THEM / 0 MAT / 0 DOI`.

## Hợp đồng kiểm chứng — 4 bước, thiếu một là chưa xong

1. **Gate trên đúng đường production.** Gọi chính lệnh người dùng gọi (`main.py`
   flags, exe trong `dist`, app đã cài). Test tự dựng đầu vào theo cách riêng không
   chứng minh gì.
2. **Phản chứng.** Mỗi gate phải có phép thử chứng minh nó ĐỎ vì ĐÚNG lý do: đổi
   một hằng số đầu vào, cắm một file nguồn thật chứa lỗi, xóa vật lý một file, chèn
   lại dòng vừa xóa rồi so đầu ra. Gate xanh vì đầu vào rỗng là gate giả — phải chết
   khi không tìm thấy gì để quét.
3. **Ảnh cho phần render.** Bộ dựng ảnh đi từ code path sản xuất, lưu
   `scratch/*.png`, và PHẢI mở ảnh ra xem. Log + dòng PASS không phải chứng cứ.
4. **Đọc rc của chính công cụ.** Không qua đường ống, không tin wrapper.

## Bẫy của máy này (đã trả giá)

- **Không sandbox `APPDATA` khi chạy từ nguồn.** `site-packages` của user nằm ở
  `%APPDATA%\Python\Python311\site-packages`; trỏ `APPDATA` vào thư mục tạm làm
  `import cv2` chết lặng, selftest đỏ 4 dòng vì `ModuleNotFoundError` chứ không vì
  sản phẩm. APPDATA tạm CHỈ dùng cho exe đã cài (nó ghi đè `recent_projects.json`
  ngay lúc mở app — đã sửa và đã gate, xem `diagnostics.py` dòng `doc MRU khong ghi
  du lieu nguoi dung`).
- **Exception bật ra từ callback C++ của Qt giết cả process.** `QIconEngine.paint/
  pixmap` mà raise thì Python không unwind qua biên được: stdout buffer mất hết.
  Mã thoát của kiểu chết này **không ổn định** (đo 6 lần trên cùng một đầu vào:
  `0xC0000409` = 3221226505 hai lần, `rc=1` một lần) — gate trên chuỗi `Error
  calling Python override of ...`, chỉ in mã ra. Kiểm tên/số ở chỗ construct,
  đừng hoãn tới lúc vẽ.
- **`0xC0000409` hiện ra là rc=127 trong Git Bash** dù stdout in `ALL PASS`; window
  còn sống lúc teardown cũng gây ra mã này. Đọc mã thật bằng `subprocess.run`
  (helper: `.qoder/skills/gate-counterfactual-evidence/scripts/true_rc.py`).
- **Không tạo QWidget trước `QApplication`** — abort tức khắc, không một dòng ra.
- **Wall clock giữa hai lần chạy nói dối** trên HDD: cache drift, import bị hoist,
  layout shift khi icon rỗng đều bịa ra "tiết kiệm". Chỉ tin đồng hồ đặt trong
  `main._boot()` và control chạy cùng lần.
- **`QT_QPA_PLATFORM=offscreen` ở đây không có font nào** (`QFontDatabase` trả 0
  family): ảnh offscreen luôn là tofu, chỉ phán bố cục.
- **Inno chỉ ghi đè file nó biết**, nên bản nâng cấp giữ file lạ trong `_internal`;
  chứng minh cây bằng set-diff đường dẫn tương đối so với `dist` (chấp nhận lệch
  `unins000.*`) và sha256[:16] của `Clinging.exe`, không phán bằng size/mtime.
- **PyInstaller reuse `build\ClingingQt\Clinging.exe`**: icon mới về PE resource thì
  build với `--clean`. ISCC xóa output cũ rồi có thể abort ở lỗi 110; wrapper chạy
  nền báo rc=0.
- **Git Bash ăn argv bắt đầu bằng `/`** (`/VERYSILENT`, `/b`, `/p:`) và `ls` có thể
  in tên file khác khi tên không tồn tại: dùng `//` hoặc `MSYS_NO_PATHCONV=1`, xác
  minh sự tồn tại bằng `cmd dir /b`.
- **`write_text`/`read_text` đổi LF thành CRLF**; sửa tạm trong `scratch/` thì snapshot
  bằng byte và khôi phục bằng byte.

## Cấm

- Không commit token/mật khẩu/cookie. Token GitHub lấy bằng `git credential fill`
  và không bao giờ in ra log. Không commit `.env` hay file credential.
- Không cài/chạy công cụ phân tích bên thứ ba (`rea`, CapCut) để "so tính năng".
- Không tự dựng lại bundle/installer, không tự cài đặt đè, không tự republish asset
  Release: đó là thao tác shared-state, phải xin duyệt trước.
- Không sửa `legacy_tk/`, không đổi `UpgradeCode` trong `packaging/clinging.wxs`.
- Không đặt emoji vào UI chrome; icon đi qua `widgets/common.py:font_icon()`
  (`fa6s.*`). Ngoại lệ duy nhất: sticker legacy và tên giả trong diagnostics.

## Style

- Commit message ngắn, không dấu, ASCII (`Them note Release 1.0.1 va cach day asset`).
- Trả lời người dùng bằng tiếng Việt, câu ngắn; tài liệu repo và comment trong
  `.py` viết tiếng Việt không dấu hoặc ASCII để file giữ mã hóa đơn.
- Comment chỉ giải thích VÌ SAO, và tốt nhất là dẫn số đo thật ("0,62 s", "1402
  glyph", "362 file", "2/3 lan abort") thay vì tính từ.
