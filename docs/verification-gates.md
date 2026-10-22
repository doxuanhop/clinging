# Quy trình kiểm chứng của repo này

Tài liệu này định nghĩa thế nào là "xong" cho một thay đổi ở Clinging. Nó không
phải phong cách, mà là điều kiện: một sửa đổi không qua bốn bước dưới đây thì
chưa được tính là đã làm, kể khi code chạy đúng trên máy người viết.

Lý do: mọi gate trong repo này đều đã có ít nhất một lần xanh vì lý do sai
(ví dụ thật ở mục "Thất bại đã ghi").

---

## Bốn yêu cầu

### 1. Gate chạy trên ĐÚNG đường production

Gate phải gọi chính lệnh mà người dùng / installer gọi, không phải một bản mô
phỏng. Một test tự dựng đầu vào theo cách riêng của nó thì chỉ chứng minh test
đó chạy được.

- `python main.py --selftest` → `diagnostics.run_selftest()` dùng đúng
  `QApplication` mà exe tạo ra; báo cáo JSON ghi `exe`, `frozen`, `python` và
  `failed: [...]`.
- `python main.py --startup-report`, `--layout-report`, `--alignment-report`,
  `--graph-report`, `--project-report`, `--style-report`, `--import-report`,
  `--thumbnail-report`, `--split-report`, `--audio-report`, `--chrome-report`
  đều là cờ của `main.py` (xem `main.py:156-224`), tức cùng một code path với
  app thật.
- Bundle đã dựng thì đo bằng `dist\Clinging\Clinging.exe --selftest`; máy đã cài
  thì đo bằng `installed_app_probe.py` trỏ vào `%LOCALAPPDATA%\Programs\Clinging`.

**Bộ lọc dòng `--only=` (chỉ cho người phát triển).** `python main.py --selftest
<json> --only=<chuoi>` chạy đúng `run_selftest()` đó nhưng chỉ gọi những hàm có
tên chứa chuỗi lọc (lặp qua `sys.modules`, không đổi code path). Số đã đo trên
máy này 22/10/2026:

| Lệnh | Thời gian |
| --- | --- |
| `main.py --selftest` (đủ 38 dòng) | ~31,1 s |
| `main.py --selftest --only="chinh mau"` (1 dòng) | ~5,0 s (~6,2× nhanh hơn) |

Quy tắc: **một lần chạy lọc không bao giờ được báo cáo là "38 dòng xanh"**. Báo
cáo JSON có sẵn bằng chứng — khóa `"only"` là `null` khi chạy đủ bảng, là danh
sách token khi chạy lọc — nên mọi consumer phải kiểm `payload["only"] is None`
trước khi tuyên bố cả bảng. Bản thân bộ lọc có gate riêng
(`scratch/selftest_filter_counterfactual.py`, 10 cửa, trong đó cửa
`loc_khong_trach_gi_do` đòi dòng đỏ `bo loc --only khong trach duong nao` chứ
không im lặng trả bảng rỗng — đúng cái bẫy "xanh vì đầu vào rỗng"). Cờ này là
dụng cụ phát triển: không có `--only` thì `run_selftest()` chạy đúng như trước,
nên hành vi app và kết quả `--selftest` trên bản đóng gói không đổi.

### 2. Phản chứng (counterfactual): gate phải ĐỎ vì ĐÚNG lý do

Mỗi gate phải có một phép thử cho thấy nó còn khả năng chết. Xanh vì đầu vào
rỗng là xanh giả.

Nam dang phan chung dang dung trong `scratch/`:

| Dạng | Cách làm | Ví dụ đã chạy |
| --- | --- | --- |
| Đổi một hằng số đầu vào | Chép script, `str.replace` đúng một dòng, chạy bản chép như chạy bản thật | `scratch/gate_discrimination_probe.py` phần 1: thêm gốc `"theme"` (là FILE, không phải thư mục) vào `DIR_ROOTS` → audit phải rc=1 và nói "khong co file .py nao" |
| Cắm một file nguồn THẬT | Viết `ui/_gate_probe_bad_icon.py` chứa tên glyph không tồn tại, đòi chính audit gốc báo đỏ, rồi xóa và đòi xanh lại | `gate_discrimination_probe.py:94-107` — kiểm luôn rằng gate không để lại rác |
| Xóa vật lý một file | `shutil.copytree` rồi `os.remove` một lá, đo bằng hàm đếm thật | `msi_install_probe.count_files()` trên cây 5 file cắt còn 4 |
| Chèn lại dòng đã xóa | exec một module bản "trước sửa", so đầu ra với bản hiện tại | SHA-256 trên byte RGBA của 1402 glyph × 16/24/32 px phải bằng nhau khi xóa một dòng `import` thừa |

Số ngưỡng không được tự tay nhập: `check("cay MSI giai DUNG SO file cua bundle
trong dist", n == dist_n, ...)` so cây đã cài với `dist\Clinging` đang có, chứ
không so với một con số nhớ từ lần build trước. Ngưỡng dưới (`dist_n >= 300`)
chặn trường hợp "xanh rỗng" `0 == 0`.

**Dạng thứ năm — đổi byte một chỗ trong file nguồn THẬT** (mười probe trong
`scratch/*_counterfactual.py`). Khuôn đã chốt sau khi có `--only`:

1. Baseline chạy **đủ bảng** và phải xanh; `nfull = len(checks)` lấy từ chính lần
   đó, không nhập tay 38.
2. Từng phép đổi byte chạy **lọc** (`--only=<dong do>`), đòi hai điều: payload
   phải thực sự là lần chạy lọc (`only == [dong]`, `len(checks) == 1`) và `detail`
   của dòng đó chứa **đúng lý do của phép đó**. Probe nào bỏ qua điều đầu tiên sẽ
   tố cáo một bộ lọc nói dối thay vì một cổng đỏ.
3. Phép ĐẦU TIÊN chạy lại trên **đủ bảng** (SPOT, một lần thay vì N lần): đòi
   `failed == [dong do]` — giữ lại tính chất "đỏ một mình, không kéo theo dòng
   khác" mà N lần chạy lọc không thể nói.
4. Khôi phục byte, chạy đủ bảng lần cuối, phải xanh với `len(checks) == nfull`
   và `only is None`; byte nguồn phải bằng nguyên ban (so `sha256[:16]` trước/sau).

**Canary đầu mối que (`scratch/needle_canary.py`).** Probe phản chứng không chạy
được là probe **im lặng**: nó import `MUTATIONS`, đếm số lần mỗi mẫu byte xuất
hiện trong file nguồn thật, và báo `LECH` khi con số khác chính con số probe đòi.
Chạy nó TRƯỚC khi phán một cổng "xanh" — nó không đổi byte nào, 0,6 s cho 12 probe.
Hai nguyên nhân lệch đã gặp: tính năng mới chèn dòng vào giữa mẫu cũ, và **file
nguồn bị đổi sang CRLF** (mẫu nối bằng LF thành 0 lần khớp) — `git checkout -- <file>`
với `core.autocrlf=true` gây ra nguyên nhân thứ hai này mà `git status` không báo gì; chữa bằng
`data.replace(b'\r\n', b'\n')` rồi đòi byte bằng `git show HEAD:<file>`.

### 3. Render thì cần ẢNH, và ảnh phải được mở ra xem

Log và dòng PASS không chứng minh một pixel nào. Bộ dựng ảnh phải đi từ đúng code
path sản xuất (`QPixmap.grab()` của widget thật, frame xuất bằng pipeline export
thật), lưu vào `scratch/*.png`, và người kiểm phải đọc lại ảnh đó — kể cả khi nó
do chính script vừa in ra.

Ảnh đang có: `scratch/icon_parity.png` (ta vs qtawesome), `scratch/fonticon_*.png`
(9 bản UI), `scratch/desktop_icon_probe.png`, `scratch/aura_evidence_sheet.png`,
`scratch/karaoke_ui_evidence.png`, `scratch/transition_ui_evidence.png`,
`scratch/save_atomic_evidence.png`, `scratch/media_locator_evidence.png`.

Bẫy đã trả giá (xem `~/.qoder/memory`): ảnh DPR > 1 phải blit vào QRect theo device
size, không `drawPixmap(x, y, pm)` trên QImage DPR-1 (co còn 80%, ăn cả dấu trừ);
không grab sau `hide()+show()`; `QT_QPA_PLATFORM=offscreen` trên máy này không có
font nào, chữ luôn là tofu — chỉ được phán bố cục, không phán chữ.

### 4. Đọc rc CỦA CHÍNH công cụ

`rc` qua đường ống, `rc` của bash, và `rc` của wrapper đều có thể nói dối.

- Python thoát bằng fastfail (`0xC0000409` = Qt callback mang exception qua Bien
  C++, hoặc teardown để window sống) thì Git Bash báo **127** trong khi mọi gate
  trong stdout đã in `ALL PASS`.
- Đọc mã thật: `python scratch/…` rồi in `subprocess.run(...).returncode`, hoặc
  dùng `python .qoder/skills/gate-counterfactual-evidence/scripts/true_rc.py <lenh>`
  (in cả thập phân lẫn hex).
- `ISCC` và wrapper build nền trả rc=0 cả khi không ghi ra file nào; phải đọc lại
  đích (`exe_version.py`, set-diff đường dẫn tương đối so với `dist`, sha256[:16]
  của `<App>.exe`).
- **Không tự gõ lại tên dòng.** `python main.py --selftest | grep "chinh mau"`
  chỉ chạy được `grep` — pipe nuốt rc của app. Muốn đọc từng dòng thì import
  `diagnostics`, lấy đúng tuple `(tên, hàm)` từ `run_selftest`, rồi spawn
  `--selftest <json> --only=<tên lấy từ bảng>` (script một lần đã dùng cách này
  để đo 31,1 s và 5,0 s ở mục 1; đừng biến nó thành gate thường trực).

---

## Chạy toàn bộ cổng, theo thứ tự

```bash
# 0) Snapshot dữ liệu người dùng TRƯỚC khi động vào app
python scratch/user_data_snapshot.py capture scratch/_snap_before.json

# 1) Audit tên icon + tham số color= trên toàn bộ nguồn
python scratch/icon_name_audit.py

# 2) Selftest 38 dòng trên tree nguồn
python main.py --selftest

# 2b) Cùng gate nhưng chỉ một dòng (dev tool, ~5 s thay vi ~31 s). KHONG bao gio
#     duoc báo cáo là "38 dòng xanh"; payload trả về có khóa "only" để kiểm chứng.
python main.py --selftest t.json --only="chinh mau"

# 3) Đo khởi động (bao gồm control cùng lần, xem mục dưới đây)
python main.py --startup-report

# 4) Phản chứng của các cổng đã sửa gần đây (34 check)
python scratch/gate_discrimination_probe.py

# 4b) Phản chứng riêng cho ba check "cái gì KHÔNG được nạp lúc boot"
#     (trang dung phim / psutil / hop thoai nen — xem nhom I duoi day)
python scratch/boot_laziness_counterfactual.py

# 4c) Độ trễ NGƯỜI DUNG thấy (Popen -> cửa sổ hiện) + tham do UI thread
python scratch/wall_to_window_probe.py --runs 3
python scratch/wall_to_window_probe.py --selfcheck   # do luong phan biet duoc UI bi chan

# 4d) Phản chứng + ảnh cho năm cổng "luu du an", "media lac cho", "undo chu + hinh hoc",
#     "clipboard Ctrl+C/V", "style chu" (vien/bong/hop nen/can le)
#     (moi probe do byte trong nguon that, chay --selftest lai sau moi phien ban
#     CU, va KHOI PHUC byte trong finally -> lan cuoi phai ra ALL PASS rc=0)
python scratch/save_atomic_counterfactual.py
python scratch/media_locator_counterfactual.py
python scratch/undo_text_transform_counterfactual.py
python scratch/clipboard_counterfactual.py
python scratch/text_styling_counterfactual.py   # -> 6/6 do dung ly do, 120,3 s (khuon loc + SPOT)
python scratch/save_atomic_evidence.py       # -> scratch/save_atomic_evidence.png
python scratch/media_locator_evidence.py     # -> scratch/media_locator_evidence.png
python scratch/undo_text_transform_evidence.py  # -> %TEMP%\clinging_undo_evidence.png
python scratch/clipboard_evidence.py            # -> %TEMP%\clinging_clipboard_evidence.png
python scratch/text_styling_evidence.py         # -> %TEMP%\clinging_text_styling_evidence.png

# 4e) Bộ chỉnh màu (hue / lift-gamma-gain / LUT .cube): 8 cua tren MainWindow that,
#     13 phep phan chung, va anh render tu FrameComposer
python scratch/color_grading_ui_probe.py        # -> ALL PASS 8 cua, khong de lai media
python scratch/color_grading_counterfactual.py  # -> 13/13 do dung ly do, byte ve nguyen ban
                                                # -> 133,6 s (khuon loc + 1 SPOT du bang)
python scratch/color_grading_evidence.py        # -> scratch/color_grading_evidence.png
                                                # -> scratch/color_grading_card_evidence.png

# 4f) Du an Pop Art: gate do TREN FILE mp4 da xuat + 6 phep phan chung (moi phep
#     chay CA HAI gate: --selftest 36 dong va gate file)
python scratch/popart_project_build.py              # -> ALL PASS, ~5 ban render 720p
CLINGING_POPART_REUSE=1 python scratch/popart_project_build.py  # do lai khong xuat lai
python scratch/popart_project_counterfactual.py     # -> 6/6 do dung ly do, byte ve nguyen ban
                                                    # -> scratch/popart_project_counterfactual.png

# 4g) Anh chung minh cua so THAT (ban da cai mo du an Pop Art): PrintWindow ->
#     assets/uiux/pop-art-project.png, 6 cua + 3 phep phan chung tren anh
python scratch/popart_window_shot.py                # -> ALL PASS, mo anh ra XEM
python scratch/popart_window_shot.py --selfcheck    # duong dan exe sai -> rc=1
python scratch/popart_window_shot.py --pixels       # khung den DO, anh that XANH,
                                                    # boi preview DO vi mat noi dung

# 4h) Chroma key (duc nen theo goc hue + despill + matte ha do phan giai):
#     19 phep doi byte tren 4 file nguon, moi phep do DUNG mot dong cua no
python scratch/chroma_key_counterfactual.py       # -> 19/19 do, byte ve nguyen ban
                                                  # -> 147,9 s (khuon loc + 1 SPOT du bang)
python scratch/chroma_key_evidence.py             # -> 54 OK / 0 FAIL
                                                  # -> scratch/chroma_key_evidence.png
                                                  # -> scratch/chroma_key_card_evidence.png
python scratch/chroma_cost_probe.py               # -> 16 OK / 0 FAIL: chi phi/frame
                                                  # qua composer that, do xen ke 1 vong

# 4i) Tach am thanh (clip video -> clip audio cung nguon, cung noi dung, tat tieng
#     video): 10 phep doi byte tren 4 file nguon + anh TimelineScene that + wav do RMS
python scratch/detach_audio_counterfactual.py     # -> 10/10 do dung ly do, byte ve nguyen ban
                                                  # -> 87,5 s (khuon loc + 1 SPOT du bang)
python scratch/detach_audio_evidence.py           # -> 14/14 phep do PASS
                                                  # -> scratch/detach_audio_evidence.png
                                                  # -> scratch/detach_audio_evidence.json

# 4j) The Cat in/out (bang thuoc tinh ben phai): hinh hoc giao hoan toan cho
#     resize_clip, mot spin = mot buoc undo, do ca preview lan export
python scratch/trim_counterfactual.py             # -> 12/12 do dung ly do, byte ve nguyen ban
                                                  # -> 136,6 s (khuon loc + 1 SPOT du bang)
python scratch/trim_evidence.py                   # -> 23/23 phep do PASS
                                                  # -> scratch/trim_evidence.png
                                                  # -> scratch/trim_evidence.json

# 4k) Nen / toi uu tep video (cong thuc port tu compressO, chi dung ffmpeg cua
#     bundle): remux that su day moov len dau, codec khop container o CA HAI chieu
python scratch/compress_counterfactual.py         # -> 17/17 do dung ly do, byte ve nguyen ban
                                                  # -> 183,7 s (truoc khi co --only: 377,2 s)
python scratch/compress_evidence.py               # -> menu video/audio phan biet, 3 grab day pixel
                                                  # -> scratch/_compress_ev_evidence.png
python scratch/compress_cost_probe.py             # -> bang chi phi preset/codec do xen ke 1 vong

# 4l) Ban dong goi (dist/Clinging/Clinging.exe): gate chay TRONG exe, hai phan
#     chung (lat _internal/styles, an core/ cua tree nguon) + do boot
python scratch/frozen_bundle_probe.py             # -> ALL PASS (0 fail), rc=0
dist/Clinging/Clinging.exe --startup-report scratch/dist_startup.json

# 4m) Chinh bo cai loc --only va dau que cua cac probe phan chung
python scratch/selftest_filter_counterfactual.py  # -> 10/10 cua, 218,8 s; loi "xanh vi
                                                  #     dau vao rong" phai do bang dong tu
python scratch/needle_canary.py                   # -> "ALL CLEAN: n/m probe con nguyen
                                                  #     ven mau", 0,6 s, KHONG doi byte nao

# 5) Chụp lại rồi diff: phải ra 0 THEM / 0 MAT / 0 DOI
python scratch/user_data_snapshot.py capture scratch/_snap_after.json
python scratch/user_data_snapshot.py diff scratch/_snap_before.json scratch/_snap_after.json

# 6) Chỉ khi phát hành: metadata PE/MSI đọc từ chính file tải về, và payload
#    MSI đối chiếu từng tên file với dist (KHONG can cai dat)
python scratch/release_meta.py build/installer/ClingingSetup-<ver>.msi \
                               build/installer/ClingingSetup-<ver>.exe
python scratch/msi_payload_check.py
```

Nguồn không được sandbox `APPDATA`: `site-packages` của user trên máy này nằm ở
`%APPDATA%\Python\Python311\site-packages`, nên trỏ `APPDATA` vào thư mục tạm làm
`import cv2` chết lặng — selftest đỏ 4 dòng vì `ModuleNotFoundError`, không phải
vì lỗi sản phẩm. An toàn dữ liệu đo bằng snapshot nội dung (mtime + size + sha256[:16]) quanh bước
đo, không phải bằng cách giấu `APPDATA`. Ngược lại, exe đã cài thì PHẢI
chạy với `APPDATA` chỉ vào bản copy dùng một lần, vì `ui/home_page.py`
`_load_recent_projects()` ghi đè `recent_projects.json` ngay lúc mở app.

Bảng so sánh chi phí khởi động chỉ có giá trị khi control nằm TRONG cùng một lần
chạy (`--startup-report` in `nhe_s` / `nang_s`, trong đó `nang_s` là qtawesome bị
kéo qua đúng seam đó). Wall clock giữa hai lần chạy trên HDD máy này sai do cache,
do import bị hoist, và do layout shift khi icon rỗng.

### Làn boot của trang Home

`--startup-report` có hai check về **thứ không được xuất hiện** lúc cửa sổ hiện:
`boot_khong_keo_trang_dung` (`ui.main_window`) và `boot_khong_psutil`. Lý do đo
bằng module chứ không bằng giây: số giây dao động, còn "module nào thường trú lúc
mở app" thì không.

| Bằng chứng (2026-10-20, tree nguồn) | Số |
| --- | --- |
| `python -X importtime -c "import ui.main_controller"` | `ui.main_window` cumulative **155 ms**, `core` 66 ms, `PySide6.QtMultimedia` 36 ms, `QtNetwork` 16 ms |
| `python scratch/boot_phase_profile.py` (cProfile trên `main._boot`) | `system_stats.psutil_or_none` **102 ms** cum, nằm trong `HomePage()` |
| `--startup-report` 3 lần, median `boot_to_window_s` | **1,645 → 1,204 s** sau khi lazify |
| RAM lúc cửa sổ hiện | **78,4 → 68,4 MB** (−10,0 MB) |
| `boot_laziness_counterfactual.py` | SACH rc=0 / DOC rc=1, hai check lật đúng chiều, `boot_khong_cv2` vẫn True |

Đo lại **2026-10-21** trên tree nguồn, máy không có render nào chạy cạnh tranh
(vì cả hai công cụ đều đọc wall-clock): `scratch/boot_low_spec_probe.py` rc=0, 5
vòng sau 3 lần warmup — baseline **0,658 s** median (min 0,548), working set
**70.780 KiB**, private **40.164 KiB**, 119 widget, **10/10** icon có điểm ảnh,
`qtawesome`/`qtpy`/`QtOpenGL` đều `False`. Chiều tiết kiệm xác định bằng cặp từng
vòng: `force_qtawesome` **1,090 s**, chậm hơn baseline **+0,542 s** median
`[1,013 / 1,132 / 0,384 / 0,388 / 0,542]`, private **+30.540 KiB**. Đồng hồ đặt
NGAY TRONG lần boot nói cùng một chuyện: `import qtawesome` một mình 0,414 s, cả
seam 0,564 s, còn bộ vẽ glyph cục bộ **0,028 s** (nạp font 0,008 + vẽ 0,019 cho 13
lần gọi) → không còn gì để cắt. Chế độ `stub_renderer` (seam trả icon rỗng) vẽ
**0/10** icon và làm bố cục lệch (`geo` khác) — được ghi lại để cấm dùng nó làm
gate, vì tiết kiệm của nó là tiết kiệm giả. `python main.py --startup-report` rc=0,
`ok=True`, 8/8 check: `boot_to_window` **1,038 s**, RAM lúc cửa sổ hiện **68.664
KiB**, lúc nghỉ 1,5 s sau đó **83.420 KiB**, `cv2_da_nap_luc_boot=False`, control
nặng 0,263 s (chứng minh đồng hồ phân biệt được).

Cùng lúc đó `wall_to_window_probe.py` đo từ **bên ngoài** app: trên exe 1.0.2 đã
cài, `Popen() → cửa sổ hiện` là **1,34–1,39 s** (lần đầu tiên sau reinstall 2,26 s)
trong khi đồng hồ trong app chỉ báo 0,84 s — ~0,5 s chênh là bootloader
PyInstaller + LoadLibrary, nằm ngoài mọi `--startup-report`. Probe cũng ghi
`mapped_files`/`cold_read_mb` (46 file, **67,6 MB** DLL-PYD mà một lần mở Home phải
giải phóng) vì hai lý do đã trả giá:

* **Đuổi cache bằng cách đọc file lớn KHÔNG được**: đọc 1.531,9 MB từ chính file
  installer chỉ hết 1,3 s — nó nằm trong RAM, nên phép "proxy cold boot" đó vô
  hiệu; `GetProcessIoCounters` của process cũng trả `ReadTransferCount = 0` cho
  image mapping.
* **`SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG)` là đồng hồ trung thực**: cắm
  `time.sleep(3)` vào một slot của cửa sổ thật thì probe đọc ra 2.973 ms một lần
  mẫu duy nhất >1 s — tham số phải chứng minh nó phân biệt được rồi mới được tin.

---

## Cổng "đừng làm mất việc của người dùng" (nhóm A, 2026-10-20)

Bốn dòng selftest mới giữ các lỗi từng làm mất trắng công sức của người dùng,
cộng thêm cổng cho tính năng clipboard clip (Ctrl+C / Ctrl+V).

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `luu du an: ghi hong khong pha ban cu` | `save_project_to_file` serialize ra byte TRƯỚC khi chạm file thật, ghi `.tmp` + `fsync` + `os.replace`, và quay bản cũ vào `~/.clinqing/recovery` (giữ `RECOVERY_KEEP = 5`) | `save_atomic_counterfactual.py`: 4 phép đổi byte (`open(path,"w")` cũ, bỏ rotation, handler lỗi có dấu, bỏ `or "."`) — mỗi phép phải làm ĐỎ đúng một dòng |
| `media lac cho: preview va export cung duong dan` | Một chiều duy nhất `core/media_locator.py`: chỉ đi bộ trong thư mục của chính file + thư mục chứa `.clinq`, chặn `MAX_DEPTH = 4` / `MAX_ENTRIES = 2000`, không bao giờ đụng thư mục hiện hành; định vị MỘT lần lúc mở dự án nên preview và export nhìn cùng một `source_path` | `media_locator_counterfactual.py`: 6 phép đổi byte trên 3 file (`MAX_DEPTH = 9`, `roots = [os.getcwd()]`, resolver rỗng, bỏ resolve ở `restore_model`, cắm lại `os.walk(".")` vào `TimelinePanel._get_media_duration`, bỏ báo `missing`) |
| `undo cho chu + hinh hoc clip` | Mười handler chữ của panel không còn ghi thẳng `clip_model`: mọi sửa chữ đi qua `SetClipTextCommand`, mọi sửa hình học (panel + neo Canvas) đi qua `SetClipTransformCommand` (kéo trên Canvas phải nhận `before=` từ lúc bấm chuột vì item đã ghi model trước). Gõ từng ký tự / kéo từng nấc spin gộp MỘT bước (`merges_with` + `absorb`, cửa sổ `MERGE_WINDOW_S = 0.75`), thao tác khác clip/khác khóa vẫn là một Ctrl+Z riêng. `clipUpdated` được nghe lại để Canvas vẽ lại RIÊNG item (không dựng lại scene, giữ con trỏ gõ chữ) | `undo_text_transform_counterfactual.py`: 2 phép đổi byte — tắt `push` trong `_push_text` (cửa ĐỎ vì "0 buoc, phai la 1"), nới guard khác khóa trong `merges_with` (cửa ĐỎ vì "bold khong thanh mot buoc undo rieng"); mỗi phép xong đều khôi phục byte và chạy xanh lại |
| `clipboard clip Ctrl+C/V` | `ClipClipboard.copy_from` snapshot đúng các clip đang chọn (deepcopy, giữ `offset` tương đối để dán nguyên nhóm không vỡ bố cục); `PasteClipsCommand` clone ra id MỚI, đặt qua `TimelineModel.place_clip` — CÙNG quy tắc va chạm/nhảy-layer và compaction Main Storyline như `duplicate_clip` — tại playhead, và là MỘT bước undo. Nối `Ctrl+C`/`Ctrl+V` qua `_install_editor_shortcuts` (bọc `_invoke_unless_editing`) | `clipboard_counterfactual.py`: 4 phép đổi byte — `PasteClipsCommand.execute` gọi `get_clip` thay `place_clip` (ĐỎ "seam clipboard thieu"), `copy_from` gán `self._entries = []` (ĐỎ "clipboard bao trong"), ép `offset = 0.0` (ĐỎ "le bo cuc tuong doi"), `undo` thành `pass` (ĐỎ "undo hai lan paste khong tra ve"); mỗi phép khôi phục byte rồi chạy xanh lại |

Số đo thật của lần kiểm (tree nguồn, 2026-10-20):

* 7 lần save đè liên tiếp trên cùng một file → recovery giữ đúng 5 bản gần nhất,
  đánh dấu `[m3..m7]`, 0 file `.tmp` sót; lần ghi hỏng (payload `QColor`) để file
  cũ còn nguyên từng byte.
* Ảnh chứng minh `scratch/save_atomic_evidence.png`: ba ô (file đang dùng / bản
  recovery / hiệu đổi ×8) — hai ô đầu bằng nhau khi nội dung không đổi.
* `scratch/media_locator_evidence.png`: ô 1 (file đúng chỗ) và ô 2 (file bị dời
  hai cấp, mở lại `.clinq`) cho payload xuất ra **giống nhau từng byte** (0/230.400
  byte lệch, 320×180 RGBA); ô 3 là mồi cùng tên đặt ngoài thư mục dự án (lệch
  118.992 byte, chứng hai bên phân biệt được thật); ô 4 là file vắng mặt thật —
  không vẽ gì và vẫn giữ đường dẫn cũ.
* Năm chỗ `os.walk(".")` trong `ui/` + `core/` đã bị xoá vật lý; `get_media_dimensions`
  trên đường dẫn đã định vị trả `(8.0, 8.0)` trên ảnh 8×8.
* Ảnh chứng minh `scratch/undo_text_transform_evidence.png` (5 ô dựng bằng
  `FrameComposer`, đúng đường preview + export): ô A chữ nhỏ giữa khung → ô B
  to lên sau `SetClipTextCommand` (7.955 byte RGBA lệch) → ô C sau Ctrl+Z **bằng
  hệt A** (0 byte lệch) → ô D lệch đi sau `SetClipTransformCommand` dời + phóng
  (3.680 byte lệch) → ô E sau Ctrl+Z **bằng hệt A** (0 byte lệch). Hoàn tác không
  chỉ đổi model mà trả lại từng pixel.
* Ảnh chứng minh `scratch/clipboard_evidence.png` (4 ô `FrameComposer`, có một
  clip nền "BG" sống 0..20s để giữ duration, khỏi bị `active_visual_clips_at`
  clamp về cuối): ô A "Clinging" gốc tại t=1s → ô B tại t=10s **chưa** paste (chỉ
  còn nền, mốc trắng) → ô C tại t=10s **sau** Ctrl+V, chữ "Clinging" hiện ra và
  **giống hệt A** (0/230.400 byte lệch — bản dán giữ nguyên font/hình học) → ô D
  tại t=10s sau Ctrl+Z **trở lại đúng ô B** (0 byte so với mốc, 5.025 byte lệch so
  với ô C — undo đã gạch sạch bản dán, không để lại bóng ma).
* Ảnh chứng minh `scratch/text_styling_evidence.png` (8 ô `FrameComposer`, đúng
  đường preview + export, nền đen nên phải tint bóng màu mới thấy): ô 1 chữ trắng
  thường → ô 2 viền đỏ 6px (3.006 byte lệch) → ô 3 bóng xanh lệch 12px (2.544) →
  ô 4 bóng mờ cyan blur 8 (2.208) → ô 5 hộp nền xanh lá 60% (11.033) → ô 6 căn TRÁI
  và ô 7 căn PHẢI **dịch thật** (trai↔phai 1.506 byte lệch) → ô 8 kết hợp viền vàng
  + hộp tím + bóng (6.411). Phản chứng `text_styling_counterfactual.py`: 6 phép đổi
  byte, mỗi phép làm cổng "style chu" đỏ ĐÚNG lý do — tắt composite → "vien ve giong
  chu thuong", export mất styling → "export bo qua style chu hop nen", preview mất
  seam → "seam style chu thieu", đổi khoá lưu → "style chu mat khi quay qua file",
  mất cast float → "text_style_of khong chuan hoa so ve float", ép lề center →
  "can le khong dich vi tri chu"; sau khi khôi phục byte, bảng xanh lại 33/33 rc=0.

Mọi vòng đều khép lại bằng `user_data_snapshot.py diff` ra
`THEM: 0 / MAT: 0 / DOI: 0` trên 1612 file — gate không được quyền chạm dữ liệu thật.

---

## Cổng "chỉnh màu" (nhóm D, 2026-10-21)

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `chinh mau: hue/lift-gamma-gain/LUT .cube` | MỘT `EffectData("Chinh mau")` mỗi clip, năm khoá `{hue_shift, lift, gamma, gain, lut_path}`; `core/clip_effects.apply_color_effects` là seam màu DUY NHẤT mà cả `FrameComposer._draw_media` (export) lẫn `CanvasClipItem.paint → _apply_effects` (preview) gọi, nên hai bên bằng nhau theo cấu trúc chứ không theo lời hứa. Quay hue là xoay quanh trục xám `(1,1,1)` (xám bất biến; `hue_shift = 0` trả về ĐÚNG object cũ để máy cấu hình thấp không phải trả giá cho một phép ma trận vô ích). Lift/gamma/gain đo được TỪNG cái một: lift chỉ nhấc bóng, gamma chỉ bưng midtone, gain nhân tuyến tính từng kenh. `.cube` đọc theo trục nhanh-nhất-là-xanh (reshape `[r,g,b,ch]`), nội suy tam tuyến tính nên một bảng identity phải tái tạo đầu vào trong sai số làm tròn; LUT 1D áp theo từng kenh; cache khoá `(abspath, st_mtime_ns, st_size)`; `load_lut` không bao giờ raise. `GRADING_KEYS` cố ý rời khỏi `PIXEL_KEYS`; `SetGradingCommand` gộp thao tác trong `MERGE_WINDOW_S = 0.75` và tỉa thẻ về `GRADING_IDENTITY` thì xoá hẳn EffectData | `color_grading_counterfactual.py`: 13 phép đổi byte trên 4 file nguồn (`core/clip_effects.py`, `core/lut.py`, `core/commands.py`, `ui/properties_panel.py`) — mỗi phép phải làm ĐỎ đúng một dòng, với lý do riêng |

Số đo thật của lần kiểm (tree nguồn, 2026-10-21):

* `--selftest`: **34 dòng, `failed = []`, rc=0, 21,5 s**. Chi tiết dòng chỉnh màu:
  `xoay truc xam 0.00->26.3 do-luc, lift +61.2 toi/1.2 sang, gamma mid 37.8,
  gain 150.0, LUT identity 0.00 swap 0.00 1D 187.0, 4 nac = 3 buoc undo,
  6 seam nguyen`.
* 13 phép phản chứng đều đỏ ĐÚNG lý do, ví dụ: bỏ `hue_shift` khỏi chuỗi lọc →
  `chuoi loc bo qua hue_shift (do-luc 170.0 -> 170.0)`; đảo ngược mũ gamma →
  `gamma 1.6 khong bentre midtone (-43.4 o do 128)`; biến lift thành brightness
  toàn ảnh → `lift 0.25 cham ca vung sang (+5.0 o do 250)`; cho hue 0 vẫn chạy ma
  trận → `hue 0 do van chay ma tran (ton may cau hinh thap)`; trộn `GRADING_KEYS`
  vào `PIXEL_KEYS` → `GRADING_KEYS trung PIXEL_KEYS: cua the ma mat nghia che do`;
  hoán vị trục bảng LUT → `LUT identity lech 175.3/255`; để LUT 1D được gọi mà
  không áp → `LUT 1D khong duoc ap (do 128 ra 128.0)`; khoá cache chỉ theo đường dẫn
  → `LUT bi thay noi dung van dung ban cu trong cache (con 200.0/255, size khong
  doi = 19697 byte)`; panel ghi thẳng vào clip → `seam chinh mau:
  ClipPropertiesWidget._push_grading thieu SetGradingCommand`; tắt gom nút →
  `keo 4 nac gamma thanh 4 buoc undo (MERGE_WINDOW_S bi vo)`; gom mọi khoá →
  `num khac khoa bi gom chung vao mot buoc undo`; tắt tỉa thẻ → `tha het ve trung
  tinh ma the chinh mau van con (1 the)`. Sau 13 phép: `phuc hoi: dong chinh mau
  XANH lai`, `byte nguon da tra ve nguyen ban (4 file)`, rc=0, 340,3 s.
* **Hai lỗi sản phẩm thật bị gate này bắt được và đã sửa trong `core/lut.py`**:
  `_interp_1d` nhân `(3,1) * (3,1,1)` → `(3,3,1)` nên LUT 1D `.cube` chưa bao giờ
  áp được cho bất kỳ kích thước nào; cache LUT khoá theo `st_mtime` (độ phân giải
  giây) trong khi file `.cube` viết `%.6f` có kích thước không đổi, nên sửa file
  tại chỗ không bao giờ được nạp lại.
* Ảnh `scratch/color_grading_evidence.png` (9 ô `FrameComposer` 320×180, đúng
  đường xuất, mọi bo số đẩy qua `SetGradingCommand`): ô 7 LUT identity lệch ô 1
  **0,16/255** trung bình; ô 8 hoán vị R-B khớp kênh đối phương **0,2** và khác
  kênh cũ **43,4** trên từng pixel; ô 2 và ô 3 (hue ±90°) cách nhau **48,6** và
  mỗi bên cách gốc 38,6; ô 4 lift 0,30 nâng bóng tối **2,33 lần** trong khi vùng
  sáng chỉ **1,06 lần**; ô 5 gamma 1,60 bưng giữa **1,28 lần**, sáng **1,05 lần**;
  ô 6 gain 0,60 hạ cả ba band đúng **0,59/0,60/0,60**; ô 9 tổ hợp khác hue thuần
  **26,8**. Ảnh `scratch/color_grading_card_evidence.png`: thẻ "Chỉnh màu" grab từ
  `ClipPropertiesWidget` thật (400×268, 24.628 điểm alpha), nhãn đọc lại đúng bo số
  của clip (`+45°`, `1.30`) và tên `identity.cube`.
* `scratch/color_grading_ui_probe.py`: **8 cổng trên `MainWindow` thật** (kéo
  slider thật, bấm nút "Chọn .cube…" thật với `QFileDialog` giả trả file tạm,
  Ctrl+Z thật, lưu/mở `.clinq`, so preview `scene.render` với export
  `FrameComposer` trên cùng khung hình) — rc=0, 42,3 s, lệch preview/export
  **1,0/255**.
* Chi phí khởi động (ràng buộc "máy cấu hình thấp"): `core/lut.py` chỉ được import
  bên trong nhánh `lut_path` của `apply_color_effects`, nên cây boot không thêm
  module nào; hai check `boot_khong_keo_trang_dung` / `boot_khong_psutil` vẫn xanh
  trong chính lần chạy 34 dòng này.
* Vòng này khép bằng snapshot **1691 file** → `THEM: 0 / MAT: 0 / DOI: 0`.

**Khâu phát hành 1.0.3 (cùng ngày).** Bundle `dist\Clinging` 362 file, `Clinging.exe`
6.890.990 B khai `ProductVersion 1.0.3`; `release_meta.py` xác nhận cả `.exe` (Inno)
lẫn `.msi` đều 1.0.3 → `GATE: metadata khop`; `msi_payload_check.py` 10/10 PASS nên
payload MSI đúng là cây `dist` (không còn qtawesome, có ffmpeg/ffprobe + cặp font
FA6). Bản đã cài chạy `scratch/installed_app_probe.py`: **216 dòng đo, 0 FAIL, rc=0** —
trong đó `--selftest` 34 dòng chạy trong bundle, `--style-report`, `--graph-report`,
`--project-report` (cả fixture lẫn dự án thật của người dùng, so byte với bản chụp
TRƯỚC khi probe mở), `.clinq` association và shortcut Desktop. Boot của exe đã cài đo
bằng `--startup-report` của chính nó: **1,02 s** tới cửa sổ, working set **68,5 MB**
lúc cửa sổ hiện, `cv2_da_nap_luc_boot=False`. Snapshot sau toàn bộ khâu cài + do:
`MAT: 0 / DOI: 0`, `THEM: 41` và CẢ 41 đều nằm dưới `cache\image\` (bộ nhớ đệm thumbnail
ra đĩa, sinh ra vì app vừa mở dự án), không có file dữ liệu nào khác thay đổi.

---

## Cổng "dự án Pop Art" (nhóm E, 2026-10-21)

Sản phẩm giao: `C:\Users\doxuanhop\Clinging_Projects\Pop Art Demo\Exports\pop_art_demo.mp4`
— 11,50 s, h264 1280×720@24 + AAC stereo 48 kHz, 8.962.919 B, ffprobe đọc trực tiếp
trên file. Dự án `Pop Art Demo.clinq` (9.728 B) và hai fixture `Assets\fixture_gradient.mp4`
/ `fixture_pattern.mp4` do chính `scratch/popart_project_build.py` sinh: không có
video, bài hát hay dự án nào của người dùng làm nguyên liệu (`Dự án 2` untouched).

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `du an pop art: lap bang lenh cua app` | Model dựng bằng đúng sáu lệnh người dùng gọi — `AddClipCommand`, `ApplyEffectCommand`, `SetGradingCommand`, `SetClipAudioCommand`, `SetClipTextCommand`, `SetTransitionCommand` — trên `UndoStack`, không có bản vẽ phái sinh; lưu bằng `project_storage.save_project_to_file`, mở lại bằng `restore_model_from_clinq(media_roots=[...])`; round-trip phải giữ thời lượng, bộ thẻ hiệu ứng, 12 khoá mỗi clip (volume/speed/fade_in/fade_out + 8 khoá chữ/font), chuyển tiếp, đúng HAI thẻ "Chinh mau" (5 khoá), và `clip_id` không đổi | `popart_project_counterfactual.py`: 6 phép đổi byte trên `core/clip_effects.py`, `core/commands.py`, `core/project_storage.py`, mỗi phép chạy CẢ HAI gate (selftest 34 dòng + gate file) |
| `san pham mp4 do tren FILE` | Render bằng đúng `ui.export_dialog.RenderWorker` mà người dùng bấm, mọi ngưỡng tính trên mp4 đã giải mã (ffprobe + ffmpeg xuất frame + PCM), không tính trên frame trong bộ nhớ | 7 cua build PHAI xanh o ca 6 phep thu: thoi luong dung, RMS, 2 kenh, am thanh khong ngan hon file, khong loi xuat, phoi `finished_ok` |
| `the Pop Art doi anh sau khi encode` | So `chuan` với `khong_popart` (ĐÃ có chữ + hoạt ảnh + chuyển tiếp + chỉnh màu, chỉ thiếu thẻ Pop Art) — so với `goc` thì lệch trọn cả ba lớp và vẫn xanh khi thẻ Pop Art bị gỡ | 35,39 / 20,88 / 26,94 ở ba mốc (ngưỡng 10,0) |
| `luoi 6 px` | Nâng luma trung bình trên ô 6 px ĐO Ở NGOÀI dải chữ, lấy max over 36 pha ô: Ben-Day chấm MUC/GIAY (`rgb*0.30+8` / `rgb*1.06+26`) chỉ hiện ra ở đây | 44,01 (ngưỡng 25,0): ban Pop Art 131,1/48,9/71,7 vs ban bo the 0,5/4,9/5,6 |
| `bo chinh mau (gain 1.10) lam sang file` | Median độ chênh luma ba mốc của `chuan` so với `khong_grade`, đo SAU encode | 2,479 (ngưỡng 1,0) |
| `chu ve ra file` | % điểm ảnh trong dải chữ đổi >30 giữa `chuan` và `khong_chu` — không dùng tổng ink vì con chữ in đậm làm pixel tối đi, tổng ink TĂNG khi bỏ chữ | 8,61 / 15,45 / 15,68 % (ngưỡng 3,0) |
| `chi phi xuat` | Ngưỡng lấy TỪ SỐ ĐO chứ không phải đoán: trần 1,20 s/frame chỉ bật ở chế độ đầy đủ (ban ngan 0,626 s/frame vì bộ giải mã + pipe ffmpeg chưa kip amortize) | 0,285 s/frame, peak working set 217.356 KiB (< 400 MiB) |

Số đo thật của lần kiểm (2026-10-21):

* `python scratch/popart_project_build.py` (đủ dự án, 5 bản render): **ALL PASS,
  rc=0**. `python scratch/popart_project_counterfactual.py`: baseline `rc=(0,0)`
  (cả hai gate xanh trước), **6/6 phép đổi byte đỏ ĐÚNG cửa, 0 cửa đỏ oan**, sau
  khi khôi phục byte hai gate xanh lại, `rc=0`.
* F1 `halftone` trả thẳng ảnh (không vẽ chấm) → đỏ `selftest: phong cach pop art`,
  `the Pop Art doi anh`, `luoi 6 px`, `bo chinh mau (gain 1.10)`. Cửa cuối là phát
  hiện thật: bỏ lưới chấm thì posterize 4 bậc nuốt luôn mức sáng +10 % của gain
  (luma đo được tụt 2,479 → 0,33), tức hai lớp màu ĐÀ nhau trên file.
* F2 `x**1/g * gain` → `* 1.0` → đỏ `selftest: chinh mau: ...` + `bo chinh mau`.
* F3 `ApplyEffectCommand` lấy `params=dict(preset)` → `params={}` → đỏ HAI cửa build
  (`the Pop Art doi anh` và `luoi 6 px` cùng nhận **0,0**), selftest 34 dòng **vẫn
  xanh**: dòng `phong cach pop art` kiểm tên khoá của preset và gọi hàm trực tiếp, nó
  không đọc đường preset → command. Ghi lại để lần sau không tưởng selftest đã chạm
  giá trị preset.
* F4 serialiser bỏ `text_style` → đỏ `selftest: 8 kieu karaoke` + `mo lai:
  POP ART!.text_style`; dòng `style chu: vien/bong/hop nen/can le` vẫn xanh vì nó
  đo trường khác.
* F5 `serialize_effects` lọc bỏ thẻ "Chinh mau" → đỏ 6 cửa: 1 selftest
  (`chinh mau: hue/lift-gamma-gain/LUT .cube`) + 5 round-trip (`mo lai: dung HAI the
  Chinh mau`, `bo chinh mau con nguyen 5 khoa`, `gain van la 1.1`,
  `fixture A/B dung hieu ung`).
* F6 `posterize lv = 255` (không nén bậc) → đỏ DUY NHẤT `selftest: phong cach pop
  art`, cả gate file xanh. Đây là phép thử NGUOC co y: ảnh `.png` chưa encode phân
  biệt được số bậc, nhưng sau h264 + lưới Ben-Day + bộ resampler của `FrameComposer`
  thì không. Posterize/halftone/outline/contrast vì vậy do unit gate giữ
  (`diagnostics.py:_popart_ok`: đúng số bậc 2/4/8, vùng tối >0,30 và lệch vùng sáng
  >0,25, viền trên vùng phẳng, spread >1,05), gate file giữ đường phối hợp + persistence.
* Snapshot dữ liệu người dùng quanh vòng này (`_snap_before_pop.json` 09:32 →
  `_snap_after_pop.json` 11:20, 1.744 → 1.758 file): `THEM: 24 / MAT: 10 / DOI: 1`.
  Giải trình hết 35 dòng: 4 file là dự án thật vừa tạo (`Pop Art Demo.clinq`, hai
  fixture trong `Assets\`, `Exports\pop_art_demo.mp4`), 1 là `recent_projects.json`
  (đăng ký MRU chủ đích), 1 là thumbnail cache ra đĩa, và 19 mới + 10 cũ bị xoá đều
  nằm trong `~\.clinqing\recovery\` của bốn stem: `Pop Art Demo` (4 mới),
  `Pop Art CF` (5 mới, bản của probe SHORT), `Kiem karaoke` (5 mới/5 cũ),
  `Kiem recap` (5 mới/5 cũ). Hai stem cuối KHÔNG phải dự án của người dùng — đó là
  fixture mà `--selftest` tự dựng trong `%TEMP%\clinging_*_report\`. Cơ chế đúng là
  cơ chế đã gate ở nhóm A2: `core/project_storage.py:207 _rotate_recovery_copy` copy
  bản đang có vào `recovery/` TRƯỚC khi ghi đè lên một `.clinq` đã tồn tại, rồi
  `_prune_recovery` giữ 5 bản — nên mỗi lần app mở rồi lưu lại fixture tạm là hàng
  cũ của chính fixture đó bị đẩy ra. Nội dung bị đẩy là bản chụp fixture tạm, không
  phải công sức người dùng: `Clinging_Projects\Dự án 2` không có dòng nào trong diff.
* Defect THẬT mà cổng này bắt được (mới ghi, chưa sửa vì RULE "chi thay giao dien,
  giu logic"): buoc ghep trong `ui/export_dialog.py:877` dung `-shortest`, nên khi
  clip chữ chạy sau clip audio cuối, mp4 bị **cắt đuôi im lặng** — model báo
  `duration` 1,9 s mà file ra 1,6 s, `--selftest` không biết. Probe buộc fixture
  kết chữ trong phạm vi audio; sản phẩm thật (11,5 s) không bị ảnh hưởng.

* Ảnh: `scratch/popart_project_evidence.png` (1316×638, 5 cột `goc` / `bo the Pop
  Art` / `bo chinh mau` / `bo clip chu` / `SAN PHAM` × 3 mốc thời gian, footer ghi
  đủ số đo) và `scratch/popart_project_counterfactual.png` (624×1608, 8 hàng: frame
  `chuan` của vòng baseline cạnh frame của vòng đã đổi byte). Hàng `baseline` lệch
  **0,0**/màu vì hai ô là cùng một ảnh; các hàng F1–F6 lệch 6,3–45,8 và F1/F3 mất
  hẳn lưới chấm Ben-Day nhìn thấy được. Hàng `final` (byte đã khôi phục, render
  lại từ đầu) vẫn lệch baseline **7,5**/màu: hai lần xuất CÙNG một model không cho
  hai file bằng nhau trên máy này, nên mọi ngưỡng file ở trên đều so hai bản render
  trong CÙNG một vòng, không so xuyên vòng.

### Ảnh cửa sổ thật của bản đã cài (`scratch/popart_window_shot.py`)

Bức `assets/uiux/pop-art-project.png` (1500×1000) là cửa sổ của **bản Inno đã cài**
mở đúng dự án Pop Art (`Clinging.exe <duong dan .clinq>`), không phải ảnh
`grabWidget()` hay frame tự dựng. Sáu cửa: tìm thấy cửa sổ của **đúng pid vừa
khởi động**; ảnh không đen (luma > 8); vùng preview 320×180 có > 400 màu; hai lần
chup lệch ≤ 1 %; cửa sổ nằm trọn trong màn hình; PNG ghi xong mở lại đúng kích
thước.

* Số đo lần chạy 21/10/2026: `man hinh: 1920x1080`, `bat anh: PrintWindow
  (rc=1 getdibits=1000)`, `kich thuoc 1500x1000 luma 34.7 preview 571 mau lech hai
  lan 0.00%`, **ALL PASS rc=0** (12,3 s).
* Bài học về thứ tự: lần đầu gọi `PrintWindow` ngay sau 2,5 s chờ trả về **toàn
  đen** (`luma 0.0`, 1 màu) dù `rc=1`. Probe vì vậy chỉ nhận ảnh khi đã sáng, poll
  mỗi 1,5 s trong 25 s — ảnh chụp "lúc app còn đang boot" không phải bằng chứng.
* `--selfcheck` (đường dẫn exe bịa) → `rc=1`, đỏ vì "exe khong ton tai".
  `--pixels` ba phép lật trên CHÍNH hàm cổng ảnh: khung đen 1500×1000 đỏ 2 cửa
  (`khung den`, `preview khong co noi dung`), ảnh đã lưu xanh 0 cửa, ảnh bị bôi đen
  đúng vùng preview đỏ ĐÚNG cửa preview (571 → 1 màu).
* Snapshot dữ liệu người dùng quanh phép chụp: 1.758 → 1.774 file,
  **THEM 16 / MAT 0 / DOI 0**. Cả 16 dòng là `cache\image\` (14) và `cache\wave\`
  (2) — thumbnail + waveform của hai fixture Pop Art vừa được tính lại. Không có
  dòng nào ở `recent_projects.json`, `.clinq`, hay `~\.clinqing\recovery\`: đóng
  app mà model không bẩn thì không có gì được lưu.

---

## Cổng "dục nền chroma key" (nhóm F, 2026-10-21)

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `duc nen chroma key: goc hue + alpha qua chuoi loc` | Một `EffectData("Chroma key")` mỗi clip, bốn khoá `{key_color, tolerance, feather, spill}` nằm NGOÀI `PIXEL_KEYS`/`GRADING_KEYS` nên cổng "thẻ ma" không đổi. Matte đo bằng **GÓC hue trên mặt phẳng Cb/Cr (BT.601)**, tuyệt đối không dùng khoảng cách: trắng cách nền `#00B140` tới 83,7 đơn vị bão hoà nên bản "distance" khoét chủ thể trước khi khoét nền. Ngưỡng bão hoà `CHROMA_MAG_FLOOR = 20,0` **cố định** (sàn không được phình theo núm, nếu không núm rộng lại ăn màu nhạt). `tolerance = 0` → `apply_color_effects` trả về ĐÚNG object QImage. Matte tính **MỘT lần trước** vòng lọc màu nên thứ tự thẻ không đổi được kết quả; despill chỉ động kênh nóng nhất của màu khoá và không được chạm alpha. `SetChromaCommand` gom trong `MERGE_WINDOW_S = 0.75`, khác khoá thì không gom, về `CHROMA_IDENTITY` thì tỉa hẳn thẻ | `chroma_key_counterfactual.py`: 19 phép đổi byte trên `core/clip_effects.py`, `core/commands.py`, `ui/properties_panel.py`, `core/timeline_model.py` |
| (cùng dòng) `matte 256 px` | `CHROMA_MATTE_MAX = 256`: mặt phẳng matte tính trên plate thu nhỏ (`cv2.INTER_AREA` xuống, `INTER_LINEAR` lên) rồi nhân vào alpha; despill vẫn chấm RGB ở độ phân giải làm việc. Phải đo được CẢ HAI chiều: cạnh thu nhỏ **thật sự chạy** ở 640×360 (không thì cổng xanh vì nhánh bị vô hiệu hoá), và **không đổi quyết định** trong vùng đồng nhất — chỉ được làm lệch đường biên | hai phép cuối của `chroma_key_counterfactual.py`: `if long_side <= CHROMA_MATTE_MAX:` → `if True:` (tắt cạnh) phải đỏ vì `branch thu nho matte khong chay`, và `size = (round(w*scale), round(h*scale))` → `(w//64, h//64)` (plate quá ran) phải đỏ vì `thu nho matte an chu the` |

Số đo thật của lần kiểm (tree nguồn, 2026-10-21):

* `--selftest`: **35 dòng, `failed = []`, rc=0, 19,2 s**. Chi tiết dòng chroma:
  `nen 0.000 moi dung sai, la-cay 19.8 do alpha 1.000->0.303->0.000 theo num
  0.05/0.15/0.30, lan 40.8 do cat tu 0.50, 4 mau trung tinh con 1.000 o tolerance
  1.0 (ke ca 0.0 do mag 16.7), bien mong la-cay tai tolerance 0.02, feather 0->1
  lam mong 1.000->0.030, spill 177->61 khong doi matte, matte 256 px (lech 0.0000
  so voi do day du tai 640x360), 4 nac = 1 buoc undo, 6 seam, round-trip 1 the`.
* 19 phép phản chứng đều đỏ ĐÚNG lý do, rc=0, **437,3 s**, ví dụ: sàn bão hoà về 0
  → `tolerance 1.0 duc ca mau trung tinh (trang alpha nan)`; span núm dung sai về 0
  → `tolerance 0.15 khong mo vong toi la cay (alpha 1.000)`; span viền mềm về 0 →
  `vien mem khong lam mong bien`; đảo dấu span → `mau cua chinh bo khoa van con
  o alpha 0.998`; despill tắt → `spill 0.8 khong keo kenh xanh cua nen (177 -> 177)`;
  despill cả ba kênh → `spill dong luon kenh khac cua nen`; pre-pass tắt →
  `nen con alpha 255 trong QImage`; matte đảo → `trang bi duc o QImage that (alpha 0)`;
  thẻ trung tính vẫn mở numpy → `the chroma trung tinh van chay chuoi loc`; màu đọc
  không được → `mau doc khong duoc ('') khong tra ve nen mac dinh`; khoá lẫn
  `PIXEL_KEYS` → `CHROMA_KEYS trung khoa khac`; hai luật gom undo →
  `keo 4 nac dung sai thanh 4 buoc undo` / `num khac khoa bi gom chung`; tắt tỉa thẻ
  → `tha het ve trung tinh ma the chroma van con (1 the)`; hai seam panel →
  `update_values thieu _sync_chroma_card` / `_push_chroma thieu SetChromaCommand`;
  presetBo loc dùng khoá chroma → `Bo loc se duc nen luong bat`.
* Ảnh `scratch/chroma_key_evidence.png` (8 ô `FrameComposer` 640×360, đúng đường
  xuất, mọi bo số đẩy qua `SetChromaCommand`/`SetGradingCommand` trên `UndoStack`
  thật): ô 0 nguyên nền xanh; ô 1-2 cắt hết caro, giữ 8 ô màu; ô 3-4 viền mềm làm
  mong biên; ô 5 chống ám kéo kênh xanh của ô nhiễm ám 127 → 99 mà không đụng
  đỏ/lục (lệch 0,0); ô 6 khoá màu ĐỎ cắt đúng đỏ-da-cam và để nguyên nền xanh;
  ô 7 chroma + chỉnh màu hue +90 vẫn cắt nền (239,239,60) và xoay đỏ đi 163.
  Ảnh `scratch/chroma_key_card_evidence.png`: thẻ "Dục nền (Chroma key)" grab từ
  `ClipPropertiesWidget` thật (400×235, 22.138 điểm alpha), nhãn đọc lại đúng
  `0.30 / 0.25 / 0.00` và hex `#00B140 (0,177,64)`. Probe: **54 OK / 0 FAIL, rc=0,
  4,3 s**, hai ảnh được `PIL.Image.open` mở lại và đếm màu (7.747 và 210 màu).
* `scratch/chroma_cost_probe.py` (ràng buộc "máy cấu hình thấp") — **16 OK / 0 FAIL,
  rc=0, 41,5 s**:
  * Đường tắt: không thẻ và thẻ `tolerance 0` trả về **đúng object QImage**
    (`0,015 ms/frame`), nên clip không dục nền không phải trả giá numpy.
  * Thuê qua `FrameComposer` (20 frame median): 720p — không thẻ 30,1 ms, chroma
    98,4, `grading hue 45` 76,0, Pop Art 195,0; 1080p — 31,7 / 87,7 / 62,2 / 190,6.
    **Phần cứng nói dối nếu đo hai vòng riêng**: cùng một cấu hình, hai vòng liền
    lệch 8-12 ms vì drift đọc đĩa, nên cặp núm dung sai/viền mềm phải đo **xen kẽ
    trong cùng một vòng** — kết quả 117,5 vs 120,0 ms (720p) và 102,6 vs 103,6 ms
    (1080p), tức núm không nhân chi phí vì matte chỉ tính một lần.
  * RIêng hàm `chroma_key_rgb` tại 640×360: **13,4 ms** khi matte rút về 256 px,
    20,2 ms kèm despill, so với **54,0 ms** khi tính đầy đủ — `atan2` một mình hết
    11,8 ms/230k phần tử trên CPU chỉ có X86_V2. Despill viết lại theo lerp một
    kênh: 8,8 → 6,4 ms, kết quả bằng nhau tới 0,0/255.
  * RAM: 20 frame 1080p làm working set 72,6 → 73,4 MB (**+0,8 MB**), không thêm
    module nặng nào vào import đầu (numpy/cv2 đã nạp sẵn cho các thẻ khác).
* Snapshot dữ liệu người dùng quanh `--selftest`: **1774 → 1774 file,
  `THEM: 6 / MAT: 6 / DOI: 0`**. Sáu dòng thêm và sáu dòng mất cùng nằm trong
  `~\.clinqing\recovery\` và trùng đúng hai stem fixture của selftest
  (`Kiem karaoke` 5, `Kiem recap` 1) — vòng quay keep-5 của ảnh phục hồi, không
  phải mất dữ liệu: `DOI: 0` và tổng số file không đổi.

**Xác minh bản đóng gói (bundle `dist\Clinging`, dựng lại từ đúng tree chroma).**
`Clinging.exe` 6.911.780 B (bản 1.0.3 là 6.890.990 B), dựng bằng
`python -m PyInstaller ClingingQt.spec --noconfirm`, log `scratch/pyinstaller_chroma.log`,
`Build complete` sau 204 s.

* `scratch/frozen_bundle_probe.py`: **ALL PASS, 0 fail, rc=0, 40,2 s** — trong đó
  selftest chạy **bên trong exe đóng gói** là 35 dòng, `failed = []`, `frozen = True`,
  `_MEIPASS` trỏ vào `dist\Clinging\_internal` (85 entry), và dòng chroma OK với
  `matte 256 px (lech 0.0000 so voi do day du tai 640x360)` — tức cv2 5.0.0 có mặt
  trong PYZ và cạnh thu nhỏ matte chạy thật trong bundle, không chỉ ở tree nguồn.
* Hai phản chứng của bundle: (1) lật `_internal\styles` → selftest `rc=1` và đúng
  mục fail `styles/*.qss + theme`; (2) **đổi tên `core/` của tree nguồn** trong lúc
  exe chạy → selftest vẫn `rc=0`, `failed = []`, dòng chroma vẫn OK và **chi tiết
  giống baseline từng byte**. Đó là bằng chứng code đến từ PYZ chứ không vay từ
  `D:\Programming\clinging\core`; thư mục được trả lại trong `finally` và
  `git status` sạch sau phép thử.
* Boot của bundle (hai lần, `--startup-report`): **0,58 s** và **0,55 s** tới lúc
  cửa sổ lộ, working set 61,8–62,0 MB lúc `MainController()` xong, 68,8 MB lúc cửa
  sổ hiện, 82,3–82,6 MB lúc ngắm; tám check của báo cáo đều `true`
  (`cua_so_lo`, `tem_ram_con_song`, `dong_ho_phan_biet`, `boot_khong_cv2`,
  `boot_khong_keo_trang_dung`, `boot_khong_psutil`, `bia_duoc_ve`, `anh_chung_minh`).
  Không so được với `scratch/dist_startup_final.json` (1,42 s / 102 MB) vì baseline
  đó dựng trước khi bỏ qtawesome — chỉ kết luận được là chroma không thêm gì vào
  đường boot: không import mới, và `control.cv2_da_nap_luc_boot = false`.
  Ảnh `scratch/dist_startup_chroma2.png` đã mở ra xem: Home đủ chữ, icon Font
  Awesome không tofu, hai bìa dự án gần đây được vẽ, monitor CPU/RAM/GPU sống.
* Snapshot quanh ba lần selftest trong bundle + hai lần boot: **1774 → 1774 file,
  `THEM: 10 / MAT: 10 / DOI: 0`** — mười thêm và mười mất đều là ảnh phục hồi
  keep-5 của đúng hai fixture selftest (`Kiem karaoke`, `Kiem recap`).
* **Chưa** dựng lại installer, **chưa** cài đè, **chưa** đụng Release: chroma key
  mới tồn tại ở tree nguồn + bundle local, chờ duyệt phát hành.

---

## Cổng "tách âm thanh" (nhóm G, 2026-10-21)

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `tach tieng video thanh clip audio rieng` | `TimelineModel.detach_audio` clone clip video thành clip AUDIO **cùng** `source_path`/`in_point`/`out_point`/`duration`/`speed_factor`/`volume_level`/`fade_in`/`fade_out` và **cùng** `start_time`, rồi đặt `audio_muted = True` lên clip nguồn. Exporter không phải sửa một dòng: `collect_audio_clips` chỉ còn thấy clip audio, `build_filter_complex` tự sinh `atrim` + `adelay=<start*1000>`. Preview cũng không: `_preview_audio_owner` đổi chủ theo `clip_volume` nên video đã tắt tiếng tự nhường. **Đúng MỘT** clip được thêm — video còn tiếng thì cùng một nguồn bị đọc hai lần trong bản trộn. Từ chối khi: không phải video, `source_path` rỗng, hàng đang khóa, tiếng đã tắt (chẳng còn gì để tách). Hàng đích ưu tiên hàng audio không khóa và **còn phát được tiếng**; đổ xuống hàng `is_muted` là tiếng tách ra câm luôn mà người dùng không có manh mối. `remove_clip` tự xóa hàng trống nên `undo()` phải dựng lại hàng audio trống của người dùng **cùng id, tên, mute/lock và vị trí trong danh sách** — không thì một cú Ctrl+Z ăn mất hàng họ tạo. Hai nửa nằm trong MỘT `DetachAudioCommand` vì undo rời rạc để lại hàng tiếng câm. Persistence dùng nguyên `ClipModel.to_dict/from_dict`, không khoá mới. Cửa ngõ UI gate bằng **hành vi thật** (`ClipItem._detachable_audio_clip` gọi qua `SimpleNamespace(clip_model=...)` cho 4 trạng thái) chứ không bằng tên hàm | `detach_audio_counterfactual.py`: 10 phép đổi byte trên `core/timeline_model.py`, `core/commands.py`, `ui/graphics/clip_item.py`, `ui/timeline_panel.py` |

Số đo thật của lần kiểm (tree nguồn, 2026-10-21):

* `--selftest`: **36 dòng, `failed = []`**. Chi tiết dòng tách tiếng:
  `1 clip audio trung nguon/trung noi dung, export thay [0:a] adelay=1500,
  Ctrl+Z tra lai ca hai nua + giu hang audio trong`. Fixture là file lavfi
  `testsrc2` + `sine=440` 4 s dựng trong `%TEMP%`, không dùng video của người dùng.
* 10 phép phản chứng — mỗi phép chạy lại `python main.py --selftest <json>` THẬT,
  **rc đọc từ chính probe = 0 (`0x00000000`), 244,8 s** cho 11 lần selftest —
  tất cả đỏ ĐÚNG lý do và **không kéo theo dòng nào khác**:
  `place_clip(..., clip.start_time + 0.5)` → `lech start_time: 2.0000 vs 1.5000`;
  bỏ `clip.audio_muted = True` → `hai nua cua thao tac khong doi trang thai`;
  `if clip.audio_muted and False` → `tach duoc tieng cua clip dang tat tieng`;
  `audio.media_type = "video"` → `khong co dung 1 clip audio sau khi tach: []`
  (chính `place_clip`/`track_accepts_media` từ chối, tức loại media là khóa thật
  chứ không phải nhãn trang trí); `audio.source_path = ""` →
  `clip tach sai loai hoac sai nguon`; `_detachable_audio_clip` trả `True` mòn →
  `menu hien khi da tach va tat tieng, menu hien khi la clip audio, ...`;
  `undo` không ghi lại mute → `Ctrl+Z chi tra lai mot nua thao tac`;
  `_restore_track` thành `state = None` → `Ctrl+Z lam mat hang audio trong cua
  nguoi dung`; panel gọi thẳng `model.detach_audio` →
  `panel khong push DetachAudioCommand`; xóa khóa `"detach_audio"` khỏi bảng phân
  phối menu → `menu clip khong goi audio_detach_requested`. Khôi phục byte xong:
  `khoi_phuc_xanh PASS rc=0 rows=36 failed=[]`, `ALL PASS`. Probe copy bản gốc
  sang `<file>.cfbak` TRƯỚC khi chèn và ở lần chạy sau tự khôi phục mọi `.cfbak`
  còn sót: một lần chạy nền bị cắt giữa chừng đã để lại đúng một dòng `# CU`
  trong `ui/timeline_panel.py` trong khi wrapper báo `exit 0`.
* Ảnh `scratch/detach_audio_evidence.png` (1282×578, bốn ô `TimelineScene` dựng
  từ model thật qua đúng tín hiệu model — `TimePixelMapper().set_zoom(90.0)`,
  `SnapEngine` thật, mỗi ô grab sau 4,0 s settle để worker thumbnail/waveform kịp
  việc): ô 1 clip gốc 0..4 s; ô 2 block audio teal 0..4 s **và sóng trên clip video
  biến mất** (`ClipItem._audio_silent()` đọc thẳng model, nên nút loa trên hàng và
  cây sóng không thể bất đồng); ô 3 kéo block sang 1..5 s; ô 4 lane audio trống +
  sóng video trở lại sau Ctrl+Z. wav do `core.audio_mix.render_audio` sản xuất
  (PCM s16le/48k/stereo), giải bằng `wave`+`struct` của stdlib, định vị điểm đổi
  tone 440→880 Hz bằng mật độ cắt-zero trong cửa trượt 25 ms:
  **trước 2,00 s | sau tách 2,00 s | dịch +1,0 s 3,00 s | Ctrl+Z 2,00 s**, RMS cả
  file `0,0628 / 0,0628 / 0,0562 / 0,0628` — tách không làm đổi tiếng, con số
  thứ ba thấp hơn đúng bằng phần đầu bị cắt. Probe: **14/14 phép đo PASS**,
  `failed = []`.
* Máy cấu hình thấp: không module mới, không import mới trên đường boot, không
  hộp thoại — `detach_audio` chỉ chạy khi người dùng bấm menu, nên giá boot là
  0 s / 0 MB; việc mới duy nhất nằm trong row selftest.
* Snapshot dữ liệu người dùng quanh vòng gate (`_snap_before.json` 18:09 →
  `_snap_after.json` 18:15, **1790 → 1790 file**): `THEM: 6 / MAT: 6 / DOI: 0`.
  Sáu thêm và sáu mất nằm trọn trong `~\.clinqing\recovery\` và trùng đúng hai
  stem fixture của `--selftest` (`Kiem karaoke` 5, `Kiem recap` 1) — vòng quay
  keep-5 đã giải trình ở các nhóm trước. Không có dòng nào ở `recent_projects.json`,
  `.clinq`, hay `Clinging_Projects\`; `DOI: 0`.
* Hai probe cũ đụng tới menu clip phải chạy lại sau khi thêm mục "Tách âm thanh":
  `scratch/font_icon_probe.py` **rc=0, ALL PASS (0 fail)** và
  `scratch/keyframe_graph_probe.py` **rc=0, ALL PASS**. Lần chạy đầu của
  `font_icon_probe.py` ĐỎ vì ba khiếm khuyết có sẵn từ trước, không phải do
  nhóm này: (a) `clip.effects` trong fixture là `dict` trong khi
  `ClipPropertiesWidget._grading_params` đọc `effect.name` — model không bao giờ
  chứa dict (`deserialize_effects` luôn trả `EffectData`), nên fixture được sửa
  đi đúng đường sản xuất; (b) bảng cho-phép emoji danh theo **số dòng** (468) mà
  dòng đó đã trôi tới 488, nên cổng "không còn emoji trong UI" báo đỏ giả — niu
  nay danh theo nội dung dòng, và chứng minh nó không rỗng: tắt bảng cho-phép
  thì đúng một hit `ui/graphics_canvas_item.py:488` quay lại; (c) probe in danh
  sách emoji ra console cp1252 nên chết giữa bảng bằng `UnicodeEncodeError` —
  nay `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` như các probe
  khác.
* **Chưa** dựng lại bundle cho nhóm này: `dist\Clinging` hiện tại dựng từ tree
  chroma nên vẫn chạy 35 dòng — tách tiếng mới tồn tại ở tree nguồn, chờ duyệt
  phát hành.

---

## Cổng "thẻ Cắt in/out" (nhóm H, 2026-10-21)

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `the Cat in/out trong bang thuoc tinh` | Bảng thuộc tính có thẻ **Cắt**: spin `In (s)`, spin `Out (s)`, nhãn thời lượng và hai nút cắt theo playhead ở đầu/cuối clip. **Toàn bộ hình học giao cho `TimelineModel.resize_clip`** — chính hàm mà cú kéo mép clip trên timeline gọi — nên thẻ và timeline không thể sản ra hai số khác nhau, và pipeline render không đổi một dòng nào. Đơn vị là hợp đồng: In/Out là **giây của nguồn** (`in_point`/`out_point`), thời lượng là **giây timeline**, nối nhau qua `consumed_source() = duration * speed_factor`; vì vậy mọi khoảng cách trong `_trim_bounds` phải qua `* speed` (mép trái tối đa `in_point - start_time*speed` — clip bị chắn ở giây 0 của **nguồn** thì kéo hết cỡ vẫn còn `In = 2,0` chứ không về 0). Kéo một spin = **MỘT** bước `TrimClipCommand`: `_applied` chỉ đặt khi hình học THỰC đổi (`> 0,0001`), nên một cú nudge 0,01 s trên clip 4x hay một cú cắt trên hàng khóa không tạo bước undo giả — Ctrl+Z của người dùng không được xóa nhầm bước bên cạnh. Cắt đầu phải **giữ mép phải** (`start_time` và `in_point` cùng dịch, có nhân speed). Playhead ngoài đoạn clip thì từ chối. Clip chữ/hình không có cửa sổ nguồn thì thẻ ẩn. Export không có code mới: gate assert `atrim=start=2.000000:duration=1.000000` và `adelay=2500:all=1` trong filter graph thật, và `update_values()` phải đọc lại thẻ (undo KHÔNG tự làm mới panel) | `trim_counterfactual.py`: 12 phép đổi byte trên `ui/properties_panel.py` + `core/commands.py` |

Số đo thật của lần kiểm (tree nguồn, 2026-10-21):

* `--selftest`: **37 dòng, `failed = []`**. Chi tiết dòng thẻ Cắt:
  `cat tren clip 2x: in=2.0 dur=0.5@2.5s, export thay atrim=start=2.0 duration=1.0
  + adelay=2500, ripple keo clip sau ve 2.0, Ctrl+Z 4/4`. Fixture là mp4 lavfi
  `testsrc2=160x120:rate=25:duration=6` + `sine=440:duration=6` dựng trong
  `%TEMP%`, không dùng video của người dùng.
* `scratch/trim_evidence.png` (900×1318, `scratch/trim_evidence.json`): nguồn 6 s
  ghép từ sáu block rắn 1 s **đỏ / lục / lam / vàng / cyan / magenta** + tone
  440 Hz 0..3 s và 880 Hz 3..6 s, nên "đang phát giây nguồn nào" đọc bằng MÀU,
  không phải bằng pixel-diff. Bốn trạng thái, mỗi trạng thái một ô `TimelineScene`
  grab từ model thật (`TimePixelMapper().set_zoom(120.0)`), bốn khung ra do
  `FrameComposer(320x180).render_frame()` tại t = 0,5 / 1,5 / 2,5 / 3,5 s (mẫu
  pixel giữa 160,90) và tiếng do `core.audio_mix.render_audio` sản xuất
  (PCM s16le/48k/stereo) rồi đo bằng `wave`+`struct` stdlib:

  | Trạng thái | `start, dur, in, out` | spin In/Out | filmstrip (do-luc-lam-vang) | `first_loud` | đổi tone | RMS 0,3–1,7 s / 2,3–3,7 s |
  | --- | --- | --- | --- | --- | --- | --- |
  | A gốc | 0,0 4,0 0,0 4,0 | 0,0 / 4,0 | do luc lam vang | 0,00 s | 3,00 s | 0,0625 / 0,06245 |
  | B cắt đầu 2 s | 2,0 2,0 2,0 4,0 | 2,0 / 4,0 | **den den** lam vang | **2,00 s** | 3,00 s | **0,0** / 0,06245 |
  | C cắt cuối 2 s | 0,0 2,0 0,0 2,0 | 0,0 / 2,0 | do luc **den den** | 0,00 s | **không có** | 0,0625 / **0,0** |
  | D Ctrl+Z từ B | 0,0 4,0 0,0 4,0 | 0,0 / 4,0 | do luc lam vang | 0,00 s | 3,00 s | 0,0625 / 0,06245 |

  `first_loud` dịch đúng 2,00 s khi cắt đầu nhưng **không đổi** khi cắt cuối — tức
  `start_time` được giữ, chỉ `out_point` bị chặn. Hai ô đen ở đầu filmstrip B là
  khung hình timeline trống (clip đã dời sang 2,0 s), còn `source_time()` tại
  2,5 / 3,5 s vẫn 2,5 / 3,5 vì mép phải bất động. `switch = None` ở C là bằng
  chứng đoạn 880 Hz đã ra khỏi cửa sổ nguồn.
  Kết quả probe: **23/23 phép đo PASS**, `failed = []`, `TRUE_RC = 0`.
* Bẫy phải ghi lại: `active_visual_clips_at` (core/timeline_model.py:1452) clamp
  mọi truy vấn tại/sau đuôi dự án về `duration - 1e-6` để **giữ khung cuối**, và
  `resize_clip` gọi `recalculate_project_duration` khi cắt cuối nên `model.duration`
  co còn 2,1 s — nếu không chốt dự án ở một độ dài cố định thì 4 ô đo ở 2,5 s và
  3,5 s vẫn "có hình" và trạng thái C trông như không cắt gì. `measure()` vì vậy
  đặt `model.duration = PROJECT_SPAN` (6,0 s) trước khi dựng `FrameComposer`.
* Bẫy thứ hai: undo KHÔNG đọc lại bảng thuộc tính, nên sau `stack.undo()` spin vẫn
  mang range của trạng thái cũ (`out_min = in_point + MIN_TRIM*speed = 2,1`) và
  `setValue(2,0)` bị clamp thành 2,1. Probe phải gọi đúng đường sản xuất
  `editor.update_values(clip)` (qua `PropertiesPanel.show_clip_properties`) sau
  mỗi cú Ctrl+Z — đó cũng là lý do `update_values` nằm trong nhóm gate.
* 12 phép phản chứng, **tất cả chạy lại `python main.py --selftest <json>` THẬT**
  trên tree nguồn và mỗi phép chỉ làm đỏ ĐÚNG một dòng `the Cat in/out trong bang
  thuoc tinh` (không dòng nào khác đỏ). Probe kết thúc `ALL PASS`, **rc đọc từ
  chính probe = 0 (`0x00000000`)**, lần chạy cuối `khoi_phuc_xanh PASS rc=0
  rows=37 failed=[]`:

  | Phép đổi byte | Lý do gate đỏ (nguyên văn từ selftest) |
  | --- | --- |
  | `in_min_khong_nhan_speed` — bỏ `* speed` ở mép trái | `meg trai toi da tinh sai vi chia toc do: (2.5, 4.8, 3.2, 6.0)` |
  | `cat_dau_khong_chia_speed` — cắt đầu không dịch theo speed | `cat dau khong giu meg phai: (2.9, 0.1, 2.8, 3.0) (buoc 2)` |
  | `cat_cuoi_khong_chia_speed` — chặn nguồn theo timeline thay vì nguồn | `cat cuoi sai tren clip 2x: (2.0, 2.0, 1.0, 5.0) (buoc 0)` |
  | `min_trim_bang_0` — `MIN_TRIM = 0.0` | `spin cho phep clip rong 0 giay` |
  | `push_trim_bo_undo_stack` — ghi hình học thẳng, không qua `UndoStack` | `cat cuoi sai tren clip 2x: (2.0, 1.0, 1.0, 3.0) (buoc 0)` |
  | `khong_chan_lenh_rong` — bỏ guard `abs(...) < 0.005` | `mot nac 0,01s tren clip 4x tao buoc undo gia` |
  | `khong_kiem_playhead` — bỏ guard playhead ngoài clip | `playhead ngoai clip ma van cat` |
  | `cho_phep_clip_chu` — `_has_source_window` trả `True` mòn | `the Cat hien cho clip chu khong co nguon` |
  | `the_bi_an_voi_clip_co_nguon` — thẻ ẩn với clip có nguồn | `the Cat an khi clip co nguon that` |
  | `applied_vo_dieu_kien` — `_applied = True` vô điều kiện | `lenh cat tren track khoa bi tinh la da ap` |
  | `undo_khong_ripple` — undo không gọi `recalculate_main_storyline` | `Ctrl+Z khong tra lai ripple tren truc chinh` |
  | `update_values_khong_doc_the` — bỏ `_sync_trim_card()` khỏi `update_values` | `diem vao the cat bi thieu: update_values khong doc lai the Cat` |

  Phép thứ nhất ban đầu **không đỏ**: fixture duy nhất có `in_point` nhỏ hơn
  `start_time*speed`, nên `in_min` bị `max(0.0, ...)` clamp TRƯỚC khi số hạng bị
  đổi kịp ảnh hưởng tới kết quả — gate xanh vì đầu vào bị cắt cụt cũng là gate giả.
  Thêm fixture mà số hạng đó quyết định kết quả (`start 0,5 / in 3,0 / speed 2,0`:
  mép trái tối đa là 2,0 chứ không phải 0,0) thì phép thử phân biệt được ngay.
* Máy cấu hình thấp: thẻ Cắt sống trong `ui/properties_panel.py` — file nằm NGOÀI
  chuỗi boot của trang Home (đã lazify từ 1.0.3), `TrimClipCommand` đi nhờ
  `core.commands` đang được nạp sẵn. Không module mới, không import mới trên đường
  boot, không hộp thoại, nên giá là 0 s / 0 MB. Đo lại `--startup-report` trên
  chính tree nguồn có thẻ Cắt: cửa sổ hiện lúc **1,064 s**, RAM **67,2 MB** lúc
  cửa sổ / 81,6 MB lúc ngấm, `cv2_da_nap_luc_boot = false`, control cùng lần chạy
  `nhe_s = 0,0` / `nang_s = 0,237`. Toàn bộ việc mới nằm trong row selftest
  (28,0 s cho 37 dòng, `rc=0`).
* Snapshot dữ liệu người dùng quanh vòng gate cuối (`_snap_trim_a.json` →
  `_snap_trim_b.json`, **1833 → 1833 file**): `THEM: 6 / MAT: 6 / DOI: 0`. Sáu thêm
  và sáu mất nằm trọn trong `~\.clinqing\recovery\`, trùng đúng hai stem fixture của
  `--selftest` (`Kiem karaoke` 5, `Kiem recap` 1) — vòng quay keep-5 đã giải trình
  ở nhóm G. Không có dòng nào ở `recent_projects.json`, `.clinq`, hay
  `Clinging_Projects\`; `DOI: 0`.
* **Chưa** dựng lại bundle cho nhóm này: `dist\Clinging` vẫn dựng từ tree chroma nên
  chạy 35 dòng — thẻ Cắt (cũng như tách tiếng và chroma key) mới tồn tại ở tree
  nguồn, chờ duyệt phát hành.

## Cổng "nén / tối ưu tệp" (nhóm I, 2026-10-21)

Nguồn ý tưởng: `github.com/codeforreal1/compressO` (repo người dùng đưa ra,
`doxuanhop/compressO` không tồn tại). **Không** lấy code và **không** lấy binary
của nó: chỉ port công thức ffmpeg vào `core/media_compress.py`, chạy bằng đúng
`tools\ffmpeg\ffmpeg.exe` mà app đã có. Không thêm file thực thi nào, không thêm
MB nào vào bundle.

| Dòng | Hợp đồng | Phản chứng |
| --- | --- | --- |
| `nen toi uu tep video: moov + codec-hop-container` | Bốn kiểu (`remux`, `x264`, `x265`, `vp9`) và mọi lời chặn phải là **số đo được**, không phải lời hứa. `remux` `-c copy -movflags +faststart`: bằng chứng duy nhất là tự đi đọc lại 8-byte header của file ra và so **thứ tự atom** (`top_level_atoms` / `is_faststart`) — nếu không có hai hàm đó thì `-movflags` là một dòng chữ vô nghĩa. `encoder_present()` hỏi **chính ffmpeg của bundle** (`-encoders`), không hard-code: bundle này không có AV1/VP8 nên hai codec đó không được hiện trong menu. `pair_error()` chặn **CẢ HAI chiều**: kiểu nén không ghi được vào container không chứa nó, và `remux` một nguồn `h264` ra `.webm` cũng bị chặn (nguồn không tự đổi codec). `.webm` buộc `libopus` (aac trong webm là file hỏng), `.mp4` + hevc buộc `-tag:v hvc1` (không thì QuickTime/Apple không đọc), vp9 buộc `-cpu-used` + `-b:v 0` và **cấm** `-preset` (libvpx không nhận). `estimate_seconds(remux) == 0.0` vì copy stream không mã hoá lại. `compress_file()` phải **xóa file dở** khi lỗi hoặc khi người dùng bấm Huy — ffmpeg đã kịp tạo file thì một nửa file vẫn nằm trên đĩa người dùng. Ba cách đọc tiến độ (`out_time_ms`, `out_time_us`, `out_time=HH:MM:SS`) vì ffmpeg đổi cách viết giữa các bản | `compress_counterfactual.py`: 17 phép đổi byte trên `core/media_compress.py`, mỗi phép chỉ làm đỏ đúng dòng 38 |

Số đo thật của lần kiểm (tree nguồn, 2026-10-21):

* `--selftest`: **38 dòng, `failed = []`**, `rc=0 (0x00000000)`, 32,3 s cho cả
  38 dòng (chạy trên đúng tree commit). Chi tiết dòng 38:
  `nguon 51122 B moov-cuoi -> remux 51122 B moov-dau (ftyp>moov>free>mdat), x264
  76982 B; 5 loi hop-le + nguon rac/lenh Huy khong de lai file do; vp9
  -cpu-used/-b:v 0/libopus; 3 cach doc tien do`. Fixture 51.122 B là mp4 cố ý
  **không** faststart (canary `ftyp>free>mdat>moov`), dựng bằng ffmpeg của bundle
  trong `%TEMP%`, không đụng video người dùng.
* 17 phép phản chứng, **mỗi phép chạy lại `python main.py --selftest <json>`
  THẬT**; kết quả `17/17 PHAN BIET` + `khoi_phuc_xanh PASS rc=0 rows=38
  failed=[]`, `ALL PASS`, **rc đọc từ chính probe = 0**, `elapsed=377,2 s` (lần
  chạy trước cùng probe đó là 551,5 s — hai con số chỉ khác nhau vì đọc đĩa,
  không phải vì code). `sha256[:16]` của `core/media_compress.py`
  (`6ae2023120eb0167`) giống hệt trước, giữa và sau hai vòng: probe phục hồi
  byte thật, không để lại vệt.

  | Phép đổi byte | Lý do gate đỏ (nguyên văn từ selftest) |
  | --- | --- |
  | `remux_khong_movflags` — bỏ `-movflags +faststart` | `remux xong ma moov van nam cuoi file` |
  | `encoder_present_luon_false` — hàm trả `False` mòn | `ffmpeg cua bundle nay khong co libx264 (x264)` |
  | `video_codec_khong_luu_vao_facts` — `source_facts` không ghi `video_codec` | `fixture khong phai h264: ''` |
  | `remux_khong_chan_container` — `remux` không xét codec của nguồn | `remux video h264 ra webm khong bi chan` |
  | `is_faststart_dao_nguoc` — hàm đảo kết quả | `fixture da faststart san — dong nay khong phan biet duoc gi` |
  | `vp9_di_nhanh_preset` — vp9 dùng `-preset` như x264 | `vp9 nhan -preset: ffmpeg bao 'Invalid preset'` |
  | `vp9_thieu_bv0` — bỏ `-cpu-used`/`-b:v 0` | `vp9 thieu -cpu-used hoac -b:v 0: <lenh>` |
  | `webm_van_aac` — `.webm` vẫn gắn `aac` | `webm ma mang aac: <lenh>` |
  | `suggest_giu_duoi_nguon` — gợi ý tên file giữ đuôi nguồn | `goi y file cho vp9 khong doi duoi .webm` |
  | `container_choices_tu_bang` — `container_choices` trả mọi đuôi | `bang container cua vp9 bi lech: ['.m4v', '.mkv', '.mov', '.mp4', '.webm']` |
  | `build_command_khong_raise` — dựng lệnh mà không chặn cặp hợp lệ | `build_command khong chan x264 trong webm` |
  | `crf_khong_chan` — bỏ clamp CRF | `CRF 99 khong bi chan ve CRF_MAX` |
  | `hevc_khong_tag_hvc1` — bỏ `-tag:v hvc1` | `hevc trong mp4 thieu tag hvc1/faststart` |
  | `progress_bo_out_time_ms` — chỉ đọc cách viết mới | `khong doc duoc out_time_ms (ban cu)` |
  | `progress_bo_dinh_dang_hms` — chỉ đọc số nguyên µs | `khong doc duoc out_time=HH:MM:SS` |
  | `khoi_xoa_file_do` — bỏ `_drop()` file dở | `dung giua chung van con file do <duong dan>` |
  | `remux_bao_ton_gio_ma_hoa` — `estimate_seconds(remux)` tính như mã hoá | `remux duoc bao la ton thoi gian ma hoa` |

* `scratch/compress_evidence.py` → `scratch/_compress_ev_evidence.png`
  (1560×1290, 266,7 KB): **34/34 chân PASS**, `rc=0`, 50,8 s. Ảnh có năm bảng và
  đã được mở ra xem: (A) ba `CompressDialog` **thật** grab từ cửa sổ thật —
  remux mặc định, vp9 (thang tốc độ đổi nhãn thành `cpu-used 5`, gợi ý file
  `.webm`), và cặp bị chặn in nguyên văn lời chặn; (B) stat + ffprobe trước/sau
  của ba lần chạy thiệt; (C) năm lệnh do `build_command` sinh nguyên văn; (D) menu
  chuột của **card video có hành "Nén / tối ưu tệp…", card audio thì không**;
  (E) ba grab đều 487.500 pixel có nội dung. Bảng B:

  | Lần chạy thật | Kích thước | Δ | atom / faststart | wall |
  | --- | --- | --- | --- | --- |
  | nguồn (x264 CRF 23) | 1,9 MB | — | `ftyp>free>mdat>moov`, faststart=False | — |
  | `remux` copy | 1,9 MB | **+0,0 %** | `ftyp>moov>free>mdat`, faststart=**True** | 0,74 s |
  | `x264` CRF 28 veryfast | 879,6 KB | **−53,8 %** | faststart=True, 6,000→6,000 s | 4,16 s |
  | `vp9` CRF 33 cpu-used 5 | 1,9 MB | **+2,4 %** | `n/a (webm khong co moov)` | 31,80 s |

  `remux` copy từng bit nên byte không đổi; **chỉ khác thứ tự atom** — đó là toàn
  bộ lợi ích của nó, và cũng là lý do cột cuối là wall clock đo trên máy này
  trong vòng chạy, không lấy từ bảng chi phí.
* Bảng chi phí (`scratch/compress_cost_probe.py` → `_compress_cost.json`, fixture
  6 s 1280×720 `testsrc2` = 1.951.137 B, 8 CPU logich, **đo xen kẽ một vòng**):
  x264 CRF 28: `ultrafast` 1,45 s / **3.115.218 B (+59,7 %)** · `veryfast` 2,59 s /
  819.239 B · `fast` 4,67 s / 926.532 B · `medium` 4,66 s / 895.248 B · `slow`
  7,02 s / 905.301 B. x265 CRF 30: `veryfast` 12,29 s / 914.070 B · `fast` 12,64 s /
  934.980 B. vp9 CRF 33: `cpu-used 8` 29,68 s / 1.861.055 B · `cpu-used 5` 26,45 s /
  **cùng 1.861.055 B** · mặc định ("good") 51,15 s / 1.804.780 B.
  Ba kết luận rút ra từ số, không từ lời khen: (1) **`ultrafast` không phải để
  tiết kiệm** — nó ra file NẶNG HƠN nguồn 59,7 %; (2) `-preset slow` mà compressO
  gọi là "ironclad" tốn thêm 4,43 s chỉ để đổi 86 KB so với `veryfast` → máy cấu
  hình thấp không có quyền trả, ship `veryfast` (trùng preset `media_splitter` đã
  bán); (3) **`-cpu-used 8` vừa chậm hơn vừa ra đúng số byte như `5`** — libvpx
  kẹp tham số tốc độ, nên mặc định là `5` và hộp thoại không được gợi ý `8`.
* Kết quả **âm, phải nói thẳng**: trên fixture 6 s này `vp9 CRF 33` ra file
  **+2,4 % so với nguồn** (và 31,8 s), trong khi `x264 CRF 28` ra **−53,8 %**
  (4,16 s). VP9 không phải thắng về dung lượng cho clip ngắn; fixture lại là
  `testsrc2` tổng hợp — nhiễu nhân tạo là thứ VP9 ăn tốt nhất, nên số thật trên
  video quay còn tệ hơn. Hộp thoại vẫn để vp9 vì nó bán được thứ x264 không có:
  WebM mở và không bằng sáng chế.
* Lệch có chủ ý so với compressO: giữ dải CRF của repo (16–35) thay vì thang
  36→24 của nó — thang đó không với tới các CRF 20/22 app đã dùng ở đường xuất;
  không lấy slider "quality" một chiều vì bốn kiểu có bốn thang khác nhau; không
  lấy AV1/VP8 vì ffmpeg của bundle không có encoder (`encoder_present` trả
  `False`, và dòng đó được chặn hiện trong menu).
* Máy cấu hình thấp — **có gate mới**: `--startup-report` thêm
  `boot_khong_keo_nen` (đo `ui.compress_dialog` + `core.media_compress` có nằm
  trong `sys.modules` đúng lúc cửa sổ hiện). Lý do thêm dòng: `ui.library_panel`
  (nơi menu "Nén" sống) chỉ được nạp qua `ui/main_window.py:20` nên tưởng là
  `boot_khong_keo_trang_dung` đã bao phong, nhưng phép thử cho thấy **không**:
  kéo tay `import ui.compress_dialog` lên đầu một module đường boot thì
  `ui.main_window` vẫn vắng, hai dòng cũ vẫn xanh, mà boot chậm thêm
  **0,428 s** và RAM lúc cửa sổ thêm **1 MiB** — tức 40 % của 1,083 s mà bản
  1.0.3 đang chạy. Sau khi thêm dòng, `boot_laziness_counterfactual.py` chạy
  SACH/DOC NHIEM trên ba module: `SACH rc=0 {trang_dung: True, psutil: True,
  nen: True} boot=1,249 ram=68648` / `DOC rc=1 {False, False, False} boot=1,661
  ram=80552` → `chen lai ban cu: boot +0,412 s, RAM +11904 KiB`, `PASS ba cua do
  RED vi dung ly do`. Cây sạch hiện tại: `boot_khong_keo_nen = True`,
  `boot_khong_cv2 = True`, `ok = True`, cửa sổ hiện lúc 1,083–1,741 s / 66–67 MiB
  (lệch giữa hai lần chạy chỉ vì đọc đĩa). Giá thật của tính năng khi mở hộp
  thoại: một import lazy, 0 s boot, 0 MB thường trú.
* Snapshot dữ liệu người dùng quanh toàn bộ vòng gate
  (`_snap_before.json` → `_snap_after.json`, **1835 → 1835 file**):
  `THEM: 7 / MAT: 7 / DOI: 0`. Bảy thêm và bảy mất nằm trọn trong
  `~\.clinqing\recovery\` và chỉ mang hai stem fixture của `--selftest`
  (`Kiem karaoke` 5, `Kiem recap` 2) — vòng quay keep-5 đã giải trình ở nhóm G
  và H. `recent_projects.json`, các `.clinq` thật và `Clinging_Projects\`:
  **`DOI: 0`**, không có thêm/mất nào khác.
* Ảnh chứng minh **có thật** và đã mở ra xem hai lần: lần xem đầu bắt ra ba lỗi
  hiển thị (`.webm` bị đọc header MP4 in ra tên atom rác → đổi thành
  `n/a (webm khong co moov)`; một câu trộn hai dấu phân cách `1,9 MB · 6.0s` →
  `_fmt_seconds` đổi sang dấu phẩy; chân vp9 dùng con số đã đo tệ hơn → chuyển về
  mặc định `5`). Ảnh hiện tại là lần chạy SAU ba sửa đổi đó.
* **Lỗ hổng chỉ thấy khi bước sang đường đóng gói** (2026-10-22, trước khi dựng
  bundle 1.0.4): `ui.compress_dialog` chỉ được nạp bằng một lệnh `import` bên
  trong `MainWindow._open_media_compress`, và không cổng nào đọc tên module đó từ
  PYZ của exe. Nếu bản dựng thiếu nó thì menu "Nen / toi uu tep" crash ngay lúc
  người dùng bấm, trong khi `--selftest` chạy từ source tree vẫn 38 dòng xanh —
  đúng bài học `--selftest` cũ của `ui.split_dialog`, module mà row của nó
  `import` thẳng để bundle phải tự chứng minh. Đã sửa hai chỗ: `ClingingQt.spec`
  thêm cặp `core.media_compress` + `ui.compress_dialog` vào `hiddenimports` (cùng
  kiểu ba cặp thumbnail/split/keyframe đã có), và `diagnostics._media_compress_ok`
  thêm `from ui.compress_dialog import CompressDialog`.
* **Phản chứng cho điều vừa thêm** — đổi tên vật lý một file, không đổi hằng số:
  `mv ui/compress_dialog.py ui/_compress_dialog_hidden.py` rồi chạy
  `python main.py --selftest scratch/selftest_cf_dialog.json` →
  `TRUE_RC 1`, `failed = ['nen toi uu tep video: moov + codec-hop-container']`,
  chi tiết dòng đỏ là nguyên văn `ModuleNotFoundError: No module named
  'ui.compress_dialog'`; **đúng một dòng** trong 38 đổi màu. Đổi tên lại →
  sha256[:16] `43d279f85ac417df` khớp từng byte, `--selftest` chạy lại
  `TRUE_RC 0`, 38 dòng, `failed = []`.
* Vòng gate nguồn của bản 1.0.4 (`scratch/selftest_104.json`): 38 dòng,
  `failed = []`, rc = 0. Snapshot dữ liệu người dùng quanh hai lần chạy đó:
  **1835 → 1835 file**, `THEM: 7 / MAT: 7 / DOI: 0`, và 7+7 nằm trọn trong
  `~\.clinqing\recovery\` với hai stem fixture (`Kiem karaoke` 5, `Kiem recap` 2).

## Thất bại đã ghi (để không lặp)

| Hiện tượng | Nguyên nhân thật | Hệ quả thành quy tắc |
| --- | --- | --- |
| `python -m` audit in "quet sach" | `os.walk()` trên một gốc không tồn tại trả 0 file mà không báo lỗi | Gate phải chết nếu đầu vào của nó rỗng (`gate_discrimination_probe.py:79-89`) |
| `msi_install_probe` xanh cho cả bản còn qtawesome | Ngưỡng `n >= 360` trong khi bản mới có 362 file | So với bundle thật, không so với hằng số |
| `dist\Clinging\Clinging.exe --split-report` (và bản đã cài 1.0.4) trả **rc=1 trên một app cắt đúng**, phát hiện ngày 22/10/2026 khi cài 1.0.4 | `run_split_report` tự chấm bằng `len(menu_actions) == 2`; commit `b88f59f` thêm hành động "Nén / tối ưu tệp…" vào card video nhưng không chạy lại `--split-report`, nên hằng số cũ bị ĐÓNG GÓI vào bundle và chỉ đỏ khi có người cài bản mới | Cổng tự chấm phải so với **bề mặt sản phẩm đang ship** (`diagnostics.VIDEO_CARD_MENU`, ba chuỗi đúng thứ tự) chứ không với một con số; mỗi điều kiện đặt tên một cửa (`SPLIT_REPORT_CHECKS`) để phản chứng chỉ ra được cửa nào đỏ vì lý do của nó (`scratch/split_gate_counterfactual.py`, 21 vet / 14 cua, rc=0). Hệ quả còn lại: `dist`, hai file cài và Release 1.0.4 vẫn mang hằng số cũ — app không sao, nhưng `--split-report` của chúng chỉ xanh sau một lần dựng lại |
| `msiexec /i ClingingSetup-1.0.3.msi /qn` báo `rc=0`, log "MainEngineThread is returning 0", nhưng `Programs\ClingingMSI` biến mất và cây Inno bị payload MSI đè | `INSTALLFOLDER` mặc định trong `packaging\clinging.wxs` trỏ `Programs\Clinging`; major upgrade gỡ product cũ trước khi ghi product mới | Cài MSI luôn kèm `INSTALLFOLDER=...ClingingMSI`, và sau khi cài phải đọc lại CẢ HAI cây + khóa HKCU Uninstall (hai entry cùng trỏ một thư mục là hỏng), không tin mỗi mã thoát |
| Process abort `0xC0000409`, mất hết stdout | `ValueError` bật lên trong `QIconEngine.pixmap()` — callback C++ | Kiểm tên ngay trong `widgets/fontawesome.py:icon()`, trước khi qua biên |
| 4 dòng selftest đỏ `cv2` | Sandbox `APPDATA` của chính người viết | Chạy nguồn với APPDATA thật + gate snapshot |
| Probe để lại `scratch/*.mp4`, `os.remove` báo `WinError 32` cả sau 2 s retry | `QMediaPlayer` (backend WMF) giữ source đang mở cho tới khi được `setSource(QUrl())`, không phải `close()` của `SequentialVideoReader` | Dọn fixture phải buông cả player: `stop()` + `setSource(QUrl())` rồi mới xoá; và việc xoá thất bại phải tính là FAIL, không được in một dòng rồi bỏ qua |
| selftest xanh, exe crash khi mở | Probe để window sống tới lúc teardown | Probe phải đóng theo thứ tự rồi pump event |
| `--report` treo khi build `console=False` | Exception không bắt biến thành hộp thoại modal | Chế độ headless phải ghi error payload và return khác 0 |
| Phản chứng đỏ **mà source không đổi gì** | Gate assert `rc == 3221226505`, trong khi Qt-abort lần ra 0xC0000409 lần ra rc=1 (đo 6 lần: 2 abort / 1 rc=1 cho cùng một đầu vào) | Bất biến phải là nội dung log (`Error calling Python override of ...`), mã exit chỉ in ra để đọc — assert trên TẬP {1, 0xC0000409} |
| `chroma_cost_probe` FAIL `thue bo sung <= 22.0 ms/frame` dù code đã nhanh hết mức | Ngưỡng bịa từ chi phí bộ lọc thuần, quên rằng MỌI thẻ pixel phải trả round-trip QImage→numpy→QImage (65-85 ms/frame lúc 720p) trước khi phép lọc chạy | So thẻ mới với thẻ ĐÃ SHIP chạy qua cùng composer (ngưỡng tương đối) và đặt ngưỡng tuyệt đối chỉ trên hàm toán thuần |
| Hai phép phản chứng đầu tiên của chroma đỏ vì đúng lý do nhưng SAI dòng | Cạnh 640×360 mới thêm đặt TRƯỚC các assertion QImage cũ nên nó nuốt lỗi của phép thử khác | Mỗi phép đổi byte phải chỉ làm đỏ CỬA CỦA NÓ — đặt assertion mới SAU các assertion đã tồn tại trong cùng giai đoạn, rồi chạy lại 19/19 |
| `frozen_bundle_probe.py` chết giữa bảng, `UnicodeEncodeError: 'charmap' codec` ở dòng in `row["detail"]` | Probe in chi tiết selftest có dấu ("Trang chủ 5 nut/1 menu…") ra console cp1252, và bảng dừng ở dòng 12/35 — hai đoạn counterfactual phía sau KHÔNG chạy mà vẫn có người tưởng probe đã xong | Probe nào in bảng cũng phải `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` ở đầu file; rc của probe phải đọc bằng `subprocess.run`, không đọc bằng mắt |
| Cửa `bundle khong kem ffmpeg/ffprobe` FAIL trên một bundle đúng | Check viết từ 1.0.1 khi app gọi ffmpeg bản PATH; `ClingingQt.spec` nay đóng cả cặp vào `_internal/tools` nên "không kèm" là sai hợp đồng | Cửa "có/không tài nguyên" phải lấy spec + `dist` làm chuẩn và so **từng file với bản trên đĩa** (102.856.192 B / 102.652.416 B), không so với hằng số hay với trí nhớ |
| `--selftest` xanh nhưng stdout in `Loi luu du an: Object of type QColor is not JSON serializable` | Đó là fixture cố ý của dòng `luu du an atomic` (`diagnostics.py:523` đưa payload không serialize được để chứng minh file thật không bị chạm; `:535` ghi JSON cắt đôi cho đường đọc) | Trước khi gọi một dòng stdout "trông như lỗi" là regression, quy nó về ĐÚNG dòng: chạy từng hàm `_ok` trong subprocess riêng rồi xem dòng nào in ra |
| Phản chứng `in_min_khong_nhan_speed` của thẻ Cắt KHÔNG đỏ dù đã bỏ `* speed` | Fixture duy nhất có `in_point < start_time*speed`, nên `max(0.0, ...)` clamp kết quả về 0,0 trước khi số hạng bị đổi kịp lộ ra — đầu vào bị cắt cụt, không phải code đúng | Một mutation chỉ được coi là đã gate khi có fixture mà số hạng đó **quyết định đầu ra**; thêm fixture `start 0,5 / in 3,0 / speed 2,0` rồi chạy lại đủ 12/12 |
| `compress_counterfactual.py` báo `SyntaxError: bytes can only contain ASCII literal characters` và **không chạy nổi một phép nào** | Needle của mutation `webm_van_aac` chép nguyên dòng có dấu tiếng Việt vào `b'...'` | Needle byte trong probe phản chứng phải ASCII-only (dòng nguồn thật có dấu thì chép phần không dấu quanh nó); một probe không chạy được là probe im lặng, không phải probe đỏ |
| `--selftest` 38 dòng xanh từ source tree, nhưng menu "Nen / toi uu tep" của bản đóng gói chỉ chờ ngày crash | `ui.compress_dialog` chỉ được `import` bên trong thân hàm `MainWindow._open_media_compress`, và không cổng nào đọc PYZ của exe theo tên module đó — `hiddenimports` của spec cũng chưa có nó | Tính năng có module UI riêng phải (a) có cặp trong `hiddenimports` của `ClingingQt.spec` và (b) được `import` thẳng trong row selftest của chính nó, rồi phản chứng bằng **đổi tên vật lý file** (đã làm với thumbnail/split/keyframe; compress bổ sung 22/10/2026: đỏ đúng một dòng với `ModuleNotFoundError`, đổi tên lại thì sha256[:16] khớp từng byte) |
| Mutation `khoi_xoa_file_do` không đỏ trên chân "nguồn rác" | Với đầu vào là một đoạn văn bản mang đuôi `.mp4`, ffmpeg fail TRƯỚC khi kịp tạo file ra, nên bỏ `_drop()` cũng chẳng còn file mà kiểm — do 21/10/2026 | Mỗi mutation phải có một đầu vào mà file dở THỰC SỰ tồn tại; ở đây là chân bấm Huy giữa chừng, và lý do gate đỏ được viết lại thành `dung giua chung van con file do` |
| Ảnh bằng chứng in ra `atom \x1a\x43\x42...` cho dòng `.webm` | `top_level_atoms` đi theo header 8 byte kiểu MP4; áp nó lên EBML thì đọc thẻ ra toàn tên rác — mà ảnh vẫn "có chữ" nên nhìn qua không thấy sai | Hàm giải mã theo container phải tự khai nó chỉ đúng với container nào (`FASTSTART_CONTAINERS`), và ảnh phải MỞ RA XEM chứ không đếm pixel không |
| Probe dựng fixture chết ở dòng `fixture video loi rc=0` dù ffmpeg đã báo lỗi từ trước | Guard viết `fmt_bytes(size).endswith("B")` — luôn đúng, vì "1.9 MB" cũng kết thúc bằng "B" | Kiểm đầu vào bằng ngưỡng số (`getsize >= 100_000`), không kiểm bằng hình thức chuỗi; một guard luôn đúng còn tệ hơn không có guard |
| Hai cửa `boot_khong_keo_trang_dung` và `boot_khong_psutil` **xanh** trong khi hộp thoại nén bị kéo lên đường boot, boot chậm thêm 0,428 s | Hai cửa đó chỉ nhìn `ui.main_window` và `psutil`; `ui.compress_dialog` đi vào bằng một module đường boot khác thì không ai thấy | Cửa laziness chỉ chứng điều đúng tên nó nhìn: module mới phải có cửa đo `sys.modules` trên chính tên nó (`boot_khong_keo_nen`) |
| Bảng chi phí đo `cpu-used 8` rồi chân vp9 của ảnh bằng chứng cũng dùng `8` | Probe lấy con số đang thử thay vì mặc định bản ra; trên máy này `8` ra ĐÚNG số byte của `5` nhưng lâu hơn 3,2 s | Ảnh/dòng kiểm phải chạy đúng cấu hình ship ra (`preset=None` để `build_command` tự lấy `DEFAULT_PRESET`), không phải cấu hình đang dò |
| `color_grading_counterfactual.py` chết ngay dòng đầu: `AssertionError: mau byte xuat hien 0 lan o ui\properties_panel.py`, 13 phép phản chứng KHÔNG chạy một phép nào | Tính năng sau (thẻ Cắt, 9ed6125) chèn `self._sync_trim_card()` vào GIỮA hai dòng mà mẫu 2 dòng đã chép; cùng kiểu hỏng ở `commands.py` khi `SetChromaCommand` sao lại đoạn `keys = set(self._requested)` nên mẫu 4 dong khớp 2 lan trong khi probe đòi 1 | Mẫu byte phải neo vào một đoạn ĐỘC QUYỀN (thêm dòng `isinstance(other, SetGradingCommand)`), guard là `count != so_lan` (không phải `<`), và trước khi phán một cổng "xanh" thì chạy `scratch/needle_canary.py` (~0,6 s, không đổi byte) để tìm probe đã chết im lặng |
| Một loạt phản chứng chạy nhanh hơn 6 lần nhưng báo "38 dòng xanh" dù chỉ 1 dòng được gọi | `--only=` cắt bớt bảng, `failed=[]` của lần chạy lọc mang nghĩa KHÁC `failed=[]` của lần chạy đủ | Consumer phải đọc `payload["only"]` (phải là `null`) và `len(checks)` so với `nfull` đo từ baseline; bản thân bộ lọc có gate đỏ riêng khi nó không trạch dòng nào (`selftest_filter_counterfactual.py`), và giữ tính chất "đỏ một mình" bằng một lần SPOT đủ bảng |

| Sau khi chữa chạy trùng probe bằng `git checkout -- core/clip_effects.py`, canary báo `popart_project_counterfactual ... mau tim thay 0 lan` | Repo có `core.autocrlf=true` + `.gitattributes text=auto`, nên checkout ghi lại file bằng CRLF mà `git status` vẫn báo sạch; mọi mẫu nối bằng `L(*lines)` (LF) trên file đó thành 0 lần khớp — bốn file nguồn bị dính (clip_effects, frame_composer, export_dialog, `src/asr/*`) | Khôi phục bằng `data.replace(b"\r\n", b"\n")` rồi đòi `open(f,"rb").read() == git show HEAD:<file>`; mẫu nhiều dòng chỉ an toàn khi file nguồn còn LF, nên canary phải chạy sau MỌI lệnh checkout |

## Liên quan

- `docs/glyph-icons.md` — pipeline icon cục bộ và các gate đi kèm.
- `docs/release-1.0.1.md` — đường dựng bundle và cách xác minh artifact.
- `AGENTS.md` — hợp đồng làm việc, trong đó có bốn yêu cầu ở trên.
- Skill `.qoder/skills/gate-counterfactual-evidence/` — bản rút gọn để agent theo
  từng bước khi sửa code.
