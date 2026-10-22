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
- Repo public: `github.com/doxuanhop/clinging`, Release `v1.0.4` (hai asset
  `.exe` + `.msi`, tag gắn trên `155cef5`; `msi_payload_check.py` đọc bảng File của
  MSI và so từng tên với `dist\Clinging` — 363 file, 514.130.264 B). `v1.0.3` là
  bundle liền trước (đã có chroma key + chỉnh màu nhưng CHƯA có tách tiếng, thẻ
  Cắt, nén tệp), `v1.0.1` vẫn tồn tại nhưng là bundle còn qtawesome.
  **1.0.4 đã cài lên máy này cả hai cây (22/10/2026)**: `Clinging.exe`
  6.967.178 B, sha256[:16] `6785b32b92e8d0b3` giống hệt `dist\Clinging`,
  `installed_app_probe.py` ALL PASS rc=0 — nhưng bundle vẫn mang
  `--split-report` với hằng số menu cũ (xem bẫy "cổng đóng gói trong bundle").
  Clone mới muốn
  build phải tự đặt `tools\ffmpeg\ffmpeg.exe` + `ffprobe.exe` (không commit được,
  vượt 100 MB/file).

## Lệnh hay dùng

```bash
python main.py                                  # chay app binh thuong
python main.py --selftest                       # 39 dong cong, bao JSON co "failed"
python main.py --selftest out.json --only="chinh mau"   # mot dong thoi (~5-12 s vs ~49 s); khong bao gio duoc bao cao la "39 dong xanh", doc payload["only"] truoc khi tin
python main.py --startup-report                 # boot theo tung pha + control cung land
python main.py --layout-report | --alignment-report | --graph-report
python main.py --style-report | --project-report | --thumbnail-report
python main.py --split-report [out.json]        # cua cat file, thang do la diagnostics.split_report_fails
python scratch/split_gate_counterfactual.py     # phan chung: 21 vet tren 14 dieu kien cua --split-report (~0,5 s)
python scratch/split_plan_counterfactual.py     # phan chung: 14 vet tren toan cat 3 kieu (deu/doi dai/moc), ~2,2 phut, co 1 lan SPOT tron du bang
python scratch/media_split_probe.py             # 79 s: cat THAT tren dia + anh chung minh 3 kieu (panel G), 167 cua
python scratch/export_range_counterfactual.py   # phan chung: 18 vet tren vung xuat in/out + preset (178 s, 1 lan SPOT du 39 dong)
python scratch/export_range_evidence.py         # anh: 2 che do ExportDialog + 24/12 khung hue + ffprobe -count_frames + RMS, 16 cua
python scratch/export_quality_cost_probe.py     # do 8 cau hinh preset/CRF, xen ke 2 vong -> scratch/export_quality_cost.json
python scratch/icon_name_audit.py               # ten glyph + tham so tren toan bo nguon
python scratch/gate_discrimination_probe.py     # phan chung: moi cua phai do vi dung ly do
python scratch/needle_canary.py                 # 0,6 s: dem mau byte cua 14 probe, probe khong chay duoc = probe im lang
python scratch/selftest_filter_counterfactual.py # phan chung: bo loc --only, 10 cua (~3,7 phut)
python scratch/boot_laziness_counterfactual.py  # phan chung: boot khong duoc keo trang dung phim/psutil/hop thoai nen
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
python scratch/chroma_key_counterfactual.py     # phan chung: 19 phep doi byte -> cua duc nen do dung ly do
python scratch/chroma_key_evidence.py           # anh FrameComposer: cat nen xanh, giu chu the, vien mong + chong am
python scratch/chroma_cost_probe.py             # low-spec: duong tat 0 ms; thue chroma < the Pop Art da ban
python scratch/detach_audio_counterfactual.py   # phan chung: 10 phep doi byte -> cua tach tieng do dung ly do
python scratch/detach_audio_evidence.py         # anh + JSON: TimelineScene that, RMS wav do tu render_audio
python scratch/trim_counterfactual.py           # phan chung: 12 phep doi byte -> the Cat in/out do dung ly do
python scratch/trim_evidence.py                 # anh + JSON: FrameComposer 4 trang thai, wav do first_loud + RMS
python scratch/compress_counterfactual.py       # phan chung: 17 phep doi byte -> cua nen tep do dung ly do
python scratch/compress_evidence.py             # anh: menu card video -> hop thoai that, byte/atom do lan chay nay
python scratch/compress_cost_probe.py           # do chi phi 10 cau hinh preset/codec tren ffmpeg dong goi
python scratch/boot_low_spec_probe.py           # 5 vong xuyen tat: boot/WS/private + seam icon (may phai yen)
python scratch/wall_to_window_probe.py          # do lan chuong TU BEN NGOAI (Popen -> cua so hien)
python scratch/boot_phase_profile.py            # tam chia pha MainController() bang cProfile
python scratch/frozen_bundle_probe.py           # gate TRONG exe dong goi: 38 dong + 3 phan chung
                                                #   (bundle 1.0.4 CHUA co dong 39 "vung xuat": tree
                                                #   nguon da 39, dung lai bundle phai cho xin phep)
                                                # (lat _internal/styles, an core/ roi an ui/ cua tree nguon)
dist/Clinging/Clinging.exe --startup-report scratch/dist_startup.json  # boot cua ban dong goi
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
- **Một cửa laziness chỉ chứng điều đúng tên nó nhìn.** `boot_khong_keo_trang_dung`
  xanh KHÔNG nghĩa là boot sạch: đo 21/10/2026, kéo tay
  `import ui.compress_dialog` lên đầu một module đường boot thì `ui.main_window`
  vẫn vắng, hai cửa cũ vẫn xanh, mà boot chậm thêm **0,428 s** và RAM lúc cửa sổ
  thêm 1 MiB. Tính năng mới có module riêng phải thêm cửa đo `sys.modules` trên
  đúng tên module đó (`boot_khong_keo_nen`) rồi bắt nó đỏ bằng
  `boot_laziness_counterfactual.py`.
- **Cửa laziness không cứu được bundle.** Module UI chỉ được `import` bên trong
  thân hàm (`ui.compress_dialog` nằm trong `MainWindow._open_media_compress`) thì
  tree nguồn luôn xanh mà bản đóng gói vẫn có thể thiếu nó — người dùng chỉ thấy
  crash lúc bấm menu. Hai chỗ phải sửa cùng nhau: `hiddenimports` trong
  `ClingingQt.spec` VÀ một lệnh `import` thẳng trong row selftest của tính năng đó
  (đúng kiểu `ui.split_dialog`); phản chứng bằng cách **đổi tên vật lý**
  `ui/compress_dialog.py` (đỏ đúng một dòng, `ModuleNotFoundError`) và bằng cửa
  "an `ui/` cua tree nguon" trong `frozen_bundle_probe.py`.
- **Cổng tự chấm cũng bị đóng gói.** `run_split_report` kết luận bằng
  `len(menu_actions) == 2`, và `b88f59f` thêm hành động "Nen / toi uu tep…" vào
  card video mà không chạy lại `--split-report` — nên hằng số cũ vào luôn bundle,
  và bản 1.0.4 đã cài trả rc=1 trên một app cắt đúng (3 đoạn, mei 0,0, lech mau
  0,0 — đo 22/10/2026). Hệ quả quy trình: đổi một **bề mặt sản phẩm** (menu, nút,
  thẻ) thì phải chạy lại mọi `--*-report` có chạm bề mặt đó, vì lỗi không nằm ở
  nguồn mà nằm ở chính thang đo ship ra. Từ lần này thang đo đặt tên từng cửa
  (`diagnostics.SPLIT_REPORT_CHECKS`) và so với `VIDEO_CARD_MENU`, phản chứng
  `scratch/split_gate_counterfactual.py` (21 vet / 14 cua, 0,5 s, rc=0).
- **Hằng số chiều cao trong hộp thoại là một cửa đo, không phải một sở thích.**
  Them kieu cat "diem cat tu dat" lam than `SplitDialog` can 492 px trong khi
  `resize(600, 520)` chi cho viewport 410 px: dong "1 moc bi bo..." — dong
  DUY NHAT noi nguoi dung nhap sai o dau — nam duoc fold, va `grab()` cua probe
  cung khong nhin thay no nen khong bao gio do. Chua: `SplitDialog._fit_height()`
  (chi LON LEN theo `body.sizeHint()`, nghe QEvent.Resize cua hai nhan cuoi)
  + cua do `verticalScrollBar().maximum() == 0` o BON trang thai (deu / doi dai
  / moc / status ket qua) trong `scratch/media_split_probe.py`. Do cua nay tren
  `QT_QPA_PLATFORM=offscreen` cho 423 < 480 ("an toan" gia) vi platform do
  khong co font nao, sizeHint thap hon that: chieu cao phai do platform that.
- **Probe mo `MainWindow` de lai rac trong tho nguoi dung.**
  `library_panel.add_resource()` cua `media_split_probe.py` giai anh nho cho
  fixture va ghi thang vao `%APPDATA%\Clinging\cache\image`; khoa cache gom
  duong dan + mtime + size nen moi lan chay them MOT muc moi (do 22/10/2026:
  diff 1925 -> 1926 file, `THEM: 1`). Chua: probe redirect
  `core.media_cache.cache_root` ve goc tam — van di qua dung duong ghi that
  (temp + `os.replace` + budget) — kem cua phan chung "anh nho fixture ghi
  THAT o redirect" de cua "khong them file vao cache nguoi dung" khong xanh vi
  khong ghi lan nao.
- **Mọi thẻ pixel đều trả phí round-trip, không chỉ phí bộ lọc.** Chuỗi chung
  `apply_color_effects` (QImage→numpy→proxy 640 px→QImage) tự nó ngốn 65–85
  ms/frame ở 720p/1080p — đo 21/10/2026 qua `FrameComposer`: không thẻ 30 ms,
  `grading hue 45` 76–84, chroma 88–98, Pop Art 195–230. Nên ràng buộc
  "≤ 22 ms/frame cho 30 fps" trên đường xuất là **không thẻ nào đạt được**, kể
  cả thẻ đã bán: phải so với thẻ đã ban, và đo RIÊNG hàm tính
  (`chroma_key_rgb` tại 640×360: 54 ms khi tính đầy đủ, 13 ms khi matte rút về
  256 px — vì `atan2` một mình là 11,8 ms/230k phần tử trên CPU chỉ có X86_V2).
  Hai cấu hình muốn so phải đo **xen kẽ trong cùng một vòng**: hai vòng riêng
  lẻ lệch nhau 8–12 ms chỉ vì drift đọc đĩa.
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
- **`git checkout -- <file>` cũng đổi LF thành CRLF** (repo này `core.autocrlf=true`
  + `.gitattributes text=auto`, nên `git status` KHÔNG báo gì sau khi checkout).
  Hệ quả đo 22/10/2026: sau một lệnh checkout để sửa hậu quả chạy trùng probe,
  `core/clip_effects.py` thành 714 dòng CRLF, `needle_canary.py` lập tức báo
  `popart_project_counterfactual ... LECH, mau tim thay 0 lan` — probe nối mẫu
  bằng LF (`L(*lines)`) không còn áp được byte nào, nghĩa là cả sáu phép phản
  chứng pop art chết. Chữa: `data.replace(b'\r\n', b'\n')` rồi đòi
  `open(f,'rb').read() == git show HEAD:f` (bốn file nguồn bị dính: clip_effects,
  frame_composer, export_dialog, src/asr/*). Probe dùng mẫu một dòng thì không
  chết, nên triệu chứng chỉ hiện ở những probe có mẫu nhiều dòng.
- **Hai bản sao cùng chạy một probe là hỏng cả hai.** Probe phan chung doi byte
  file nguon va ghi `%TEMP%\clinging_selftest.json`; chay song song (mot lan
  background cu + mot lan moi) thi mot ban doc `original` sau khi ban kia da
  vet, va `finally` cua no phuc lai... doan vet. Lan chay 22/10/2026 bo lai
  `if False and "hue_shift" in params` trong `core/clip_effects.py`; phat hien
  bang `git status`, phuc bang `git checkout -- <file>` (file do khong nam trong
  dam thay doi co y). KHONG bai dung hai vong probe song song.
- **`--only` cat nua bang do luu do.** Lan chay loc co `failed=[]` khong nghia la
  39 dong xanh; doc `payload["only"]` (phai la `null`) truoc khi bao cao. Probe
  phan chung da theo khuon: baseline du bang -> vet chay `--only` -> MOT lan SPOT
  du bang -> khoi phuc du bang. Gia do: tron bang 48,8 s (39 dong; 38 dong la
  31,1 s), mot dong 5,0-12,4 s; nen tep 17 vet 377,2 s -> 183,7 s, chroma 19 vet
  = 147,9 s, chinh mau 13 vet = 133,6 s, vung xuat 18 vet = 178,0 s.
- **`co_names` khong nhin duoc hai dieu.** (a) HAI loi cung mot ham trong cung
  mot than: `audio_input_args` duoi go o duong video LAN LUOT duong mp3 sidecar,
  nen xoa `-ss` o duong video thi cua van xanh (do 22/10/2026 — vet
  `worker_bo_audio_seek`). (b) MOT CHUOI FORMAT: doi `lbl_duration` tu `mm:ss`
  sang con so khong doi ten cung khong doi hang nao. Chua cho ca hai: do bang
  CON SO tren san pham that — RMS hai cua so tieng (bo `-ss` thi hai con so
  giong het nhau), va chinh chu nguoi dung doc (`00:00`).
- **Mac dinh cua widget co the lam phep thu thanh tron.** `combo_fps` mo ra o
  24 fps, va cua so 1,25 s tron ven 30 khung hinh nen `span` tinh bang hieu hai
  so nhap tay trung khit `frames / fps` — vet `hop_thoai_tu_tinh_span` XANH nhu
  khong. Dong do phai ghim 30 fps (1,25 s -> 37,5 frame, khong phep nguyen hoa
  nao sinh ra duoc con so do) roi moi so.
- **Nhan `mm:ss` an mat noi dung duoi mot giay.** Cua so 2 khung hinh la HOP LE
  (`MIN_WINDOW_FRAMES = 2`) nhung `_fmt_time` in "00:00" ngay canh nut Xuat —
  cung kieu im lang nhu `-shortest` an doan cuoi. Do dai cua vung in phai in
  bang con so giay + khung hinh; che do toan bo gi dong ho.
- **Anh chung minh toa do cung co "dong duoi fold".** Panel A cua
  `export_range_evidence.py` cao 372 px trong khi anh 700 px (325 px) + hai dong
  chu thich can 401 px: chu A de duong len tieu de B, va probe van PASS vi no
  khong do toa do cua sheet. Nong panel len 420 px va di B/C/D xuong 48 px —
  mo anh ra xem la buoc duy nhat bat duoc loi nay.

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
