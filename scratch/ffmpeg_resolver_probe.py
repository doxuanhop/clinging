"""scratch/ffmpeg_resolver_probe.py

Gate cho core/external_tools.py: thứ tự tìm ffmpeg/ffprobe và các nhánh "máy
không có trình" phải báo sạch, không treo, không crash.

Lý do tồn tại: máy lập trình lúc nào cũng có ffmpeg trong PATH, nên mọi lỗi về
thứ tự tìm kiếm đều im lặng ở đây và chỉ nổ trên MÁY KHÁC. Probe này cắt PATH
ngay trong tiến trình để mô phỏng một máy sạch.

Bốn điều phải chứng minh:

1. bundled THẮNG PATH. Máy này có ffmpeg 8.1.2 trong PATH, bundle mang 9.0.1.
   Nếu find() trả về 8.1.2 thì nó vẫn đi vay của host.
2. Máy sạch vẫn chạy: cắt PATH thì find() vẫn phải trỏ vào tools/ffmpeg.
3. Máy không có gì cả: mọi chỗ PROBE về giá trị rỗng như cũ ({}, [], False,
   QImage rỗng) chứ không ném exception; mọi chỗ HÀNH ĐỘNG trả về MỘT câu
   tiếng Việt làm theo được, không phải FileNotFoundError trần.
4. Phục hồi: sau khi bỏ giả lập, số đo phải trở lại đúng như ban đầu — một
   phép đo không hoàn nguyên được thì không đo cái gì cả.

Chạy: python -u scratch/ffmpeg_resolver_probe.py
"""

import os
import subprocess
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

BUNDLED_DIR = os.path.join(ROOT, "tools", "ffmpeg")
SAMPLE = os.path.join(tempfile.gettempdir(), "resolver_probe.mp4")
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%-4s %-54s got=%r want=%r"
          % ("PASS" if ok else "FAIL", name, got, want))
    if not ok:
        FAILS.append(name)
    return ok


def true(name, condition):
    return check(name, bool(condition), True)


def pump(times=6, step=0.03):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    for _ in range(times):
        app.processEvents()
        time.sleep(step)


def build_sample():
    """Video mẫu dựng bằng ĐÚNG bản ffmpeg sẽ được đối chiếu đến."""
    subprocess.run(
        [os.path.join(BUNDLED_DIR, "ffmpeg.exe"), "-v", "error", "-y",
         "-f", "lavfi", "-i",
         "color=c=teal:s=160x120:d=2:r=25,format=yuv420p",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest",
         "-c:v", "libx264", "-preset", "veryfast", "-g", "10", "-c:a", "aac",
         SAMPLE],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
        check=False, creationflags=0x08000000)
    return SAMPLE


class _NoTool:
    """Ngữ cảnh: giả lập máy không có bundled copy VÀ không có PATH."""

    def __init__(self, external_tools):
        self.mod = external_tools
        self.saved_dirs = None
        self.saved_path = None

    def __enter__(self):
        self.saved_dirs = self.mod._candidate_dirs
        self.saved_path = os.environ["PATH"]
        self.mod._candidate_dirs = lambda: []
        os.environ["PATH"] = ""
        return self

    def __exit__(self, *exc):
        self.mod._candidate_dirs = self.saved_dirs
        os.environ["PATH"] = self.saved_path
        return False


def main():
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    from core import external_tools
    from core import media_splitter as splitter
    from core import audio_mix
    from core import media_extractor as mx

    true("video mau co tren dia", os.path.isfile(build_sample())
         and os.path.getsize(SAMPLE) > 1000)

    print("\n== 1. Ban di kem thang PATH ==")
    print("     PATH    :", external_tools.system_path("ffmpeg") or "-")
    print("     bundle  :", external_tools.bundled_path("ffmpeg") or "-")
    check("find() tra ve dung file trong tools/ffmpeg",
          os.path.dirname(external_tools.find("ffmpeg")), BUNDLED_DIR)
    check("nguon duoc ghi nhan la bundled",
          external_tools.source("ffmpeg"), "bundled")
    sys_ff = external_tools.system_path("ffmpeg")
    true("PATH co mot ban KHAC de doan thu khong trung hop",
         bool(sys_ff) and os.path.abspath(sys_ff)
         != os.path.abspath(os.path.join(BUNDLED_DIR, "ffmpeg.exe")))

    print("\n== 2. May sach (cat PATH) van phai thay ban di kem ==")
    saved_path = os.environ["PATH"]
    os.environ["PATH"] = ""
    try:
        check("khong con gi trong PATH", external_tools.system_path("ffmpeg"), "")
        true("cat PATH xong find() van ra bundle",
             os.path.dirname(external_tools.find("ffmpeg")) == BUNDLED_DIR)
        true("ffprobe di kem van do duoc file",
             float(splitter.media_info(SAMPLE).get("duration") or 0) > 1.5)
    finally:
        os.environ["PATH"] = saved_path

    print("\n== 3. May khong co gi ca: nhanh loi phai sach ==")
    with _NoTool(external_tools):
        check("find() = '' khi khong con nguon nao",
              external_tools.find("ffmpeg"), "")
        try:
            external_tools.require("ffmpeg")
            check("require() phai nem MissingTool", "khong nem", "MissingTool")
        except external_tools.MissingTool as exc:
            true("require() bao bang cau lam theo duoc",
                 "Máy này chưa có ffmpeg" in str(exc)
                 and "tools/ffmpeg" in str(exc))

        check("media_info khi thieu ffprobe", splitter.media_info(SAMPLE), {})
        check("keyframe_times khi thieu ffprobe",
              splitter.keyframe_times(SAMPLE), [])
        check("probe_duration khi thieu ffprobe",
              splitter.probe_duration(SAMPLE), 0.0)
        check("has_audio_stream khi thieu ffprobe",
              audio_mix.has_audio_stream(SAMPLE), False)
        check("_probe_with_ffprobe khi thieu ffprobe",
              mx._probe_with_ffprobe(SAMPLE), {})
        check("waveform khi thieu ffmpeg", mx._compute_waveform(SAMPLE), [])
        from core.media_frame import _extract_image_with_ffmpeg
        true("frame fallback ve QImage rong, khong crash",
             _extract_image_with_ffmpeg(SAMPLE, 0.5).isNull())

        cut = splitter.cut_segment(
            SAMPLE, os.path.join(tempfile.gettempdir(), "resolver_cut.mp4"),
            0.0, 1.0, {"has_video": True})
        true("cut_segment bao ro thieu ffmpeg, khong noi 'that bai'",
             "Máy này chưa có ffmpeg" in cut["error"] and cut["mode"] is None)

    print("\n== 4. Hop thoai cat: khong mo worker, khong treo ==")
    parent = QWidget()
    from ui.split_dialog import SplitDialog
    dialog = SplitDialog(main_window=types.SimpleNamespace(),
                         initial_path=SAMPLE, parent=parent)
    dialog.edit_out.setText(os.path.join(tempfile.gettempdir(),
                                         "resolver_out"))
    dialog.spin_count.setValue(2)
    pump(6)
    try:
        with _NoTool(external_tools):
            dialog.btn_run.click()
            pump(6)
            check("bam Chay ma thieu ffmpeg thi khong busy",
                  dialog._busy, False)
            true("status noi ro thieu ffmpeg",
                 "Máy này chưa có ffmpeg" in dialog.lbl_status.text())
            print("     status:", dialog.lbl_status.text()[:64])
    finally:
        dialog.close()
        pump(6)

    print("\n== 5. Phuc hoi: so do quay lai dung nhu ban dau ==")
    check("find() lai tra ve bundle",
          os.path.dirname(external_tools.find("ffmpeg")), BUNDLED_DIR)
    true("media_info do lai duoc",
         float(splitter.media_info(SAMPLE).get("duration") or 0) > 1.5)

    print("\nsummary: %s  (%d fail)"
          % ("ALL PASS" if not FAILS else "FAILURES", len(FAILS)))
    for name in FAILS:
        print("  FAIL", name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
