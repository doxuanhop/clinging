"""
scratch/monitor_probe.py
Bằng chứng: bảng theo dõi ở trang chủ chỉ hiển thị số ĐO ĐƯỢC.

Chạy: QT_QPA_PLATFORM=windows python -u scratch/monitor_probe.py
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtWidgets import QApplication            # noqa: E402
from PySide6.QtCore import Qt                          # noqa: E402

from core import system_stats                          # noqa: E402
import ui.home_page as home_page                       # noqa: E402

FAILS = []
FAKE_LITERALS = [
    "2.1 GHz / 11.6 GHz", "6.4 GB / 15.6 GB", "128 GB / 512 GB",
    "NVIDIA GTX 1650", "4GB GDDR6", "45°C", "42°C",
    '"18%", 18', '"41%", 41', '"23%", 23', '"25%", 25',
    "cpu_percent(interval=0.1)", "disk_usage('/')",
]


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (name, got, want))
    print("%s  %s  (got=%r)" % ("PASS" if ok else "FAIL", name, got))
    return ok


def main():
    app = QApplication(sys.argv)
    try:
        from theme import theme_manager
        app.setStyleSheet(theme_manager.stylesheet())
    except Exception as exc:
        print("  stylesheet not applied: %s" % ascii(str(exc)))

    # 1) Các hàm đo trả số liệu thật, tự tính lại để đối chiếu.
    system_stats.prime_cpu()
    time.sleep(0.5)
    cpu = system_stats.read_cpu()
    check("cpu reader measured", cpu is not None and cpu["percent"] is not None, True)

    import psutil
    ram = system_stats.read_memory()
    vm = psutil.virtual_memory()
    want_used = (vm.total - vm.available) / (1024.0 ** 3)
    want_total = vm.total / (1024.0 ** 3)
    got_used, got_total = (float(x) for x in
                           re.findall(r"([\d.]+) GB", ram["detail"]))
    check("ram detail matches psutil",
          abs(got_used - want_used) < 0.15 and abs(got_total - want_total) < 0.15,
          True)

    disk = system_stats.read_disk()
    du = psutil.disk_usage(system_stats.system_disk_path())
    check("disk measured on the system drive (not '/'), same percent",
          disk["percent"], round(du.percent, 1))
    check("system drive path is windows-valid",
          system_stats.system_disk_path().rstrip("\\").endswith(":"), True)

    gpu = system_stats.read_gpu()
    print("  gpu reader:", ascii(gpu))
    check("gpu name is not the fabricated one",
          gpu is None or "GTX 1650" not in gpu["name"], True)

    # 2) Source không còn chứa một hằng số bịa nào.
    src = open(home_page.__file__, encoding="utf-8").read()
    leaked = [lit for lit in FAKE_LITERALS if lit in src]
    check("no fabricated literals left in home_page.py", leaked, [])
    check("no blocking sample window on the GUI thread",
          "interval=0.1" in src or "interval=1" in src, False)

    # 3) Widget thật: chạy 2 vòng poll rồi đọc nhãn.
    widget = home_page.SystemMonitorWidget()
    widget.resize(260, 620)
    widget.show()
    deadline = time.time() + 5.0
    while time.time() < deadline and not widget.cpu_widget.value_label.text():
        app.processEvents()
        time.sleep(0.05)
    for _ in range(3):
        app.processEvents()
        time.sleep(0.2)
    app.processEvents()

    pct = re.compile(r"^\d{1,3}%$")
    for name, item in (("CPU", widget.cpu_widget), ("RAM", widget.ram_widget),
                       ("Storage", widget.storage_widget)):
        text = item.value_label.text()
        check("%s row shows a measured percent" % name, bool(pct.match(text)), True)
        check("%s row is visible" % name, item.isVisible(), True)
        check("%s has a real detail line" % name, bool(item.detail_label.text()), True)
        check("%s detail is not fabricated" % name,
              item.detail_label.text() not in FAKE_LITERALS, True)

    # 4) Thanh tỉ lệ phải khớp % trên chiều rộng thật của track (code cũ chỉ
    #    tối đa 190/220 px nên 100% không bao giờ đầy).
    track = widget.ram_widget.progress_container.width()
    percent = float(re.sub(r"[^0-9.]", "", widget.ram_widget.value_label.text()))
    want = int(round(track * percent / 100.0))
    check("progress bar width matches the real track",
          abs(widget.ram_widget.progress_bar.width() - want) <= 2, True)
    probe = home_page._MonitorItem("Probe", "fa6s.microchip")
    probe.resize(220, 60)
    probe.show()
    app.processEvents()
    probe.set_state(100.0, "100%", "full")
    for _ in range(3):
        app.processEvents()
    check("100% fills the whole track",
          probe.progress_bar.width() == probe.progress_container.width(), True)
    probe.hide()

    # 5) Không đo được => ẩn dòng, không vẽ số.
    real_temps = system_stats.read_temperatures
    real_gpu = system_stats.read_gpu
    widget._gpu_timer.stop()
    widget._gpu = None
    system_stats.read_temperatures = lambda: []
    widget._update_temperatures()
    app.processEvents()
    check("temperature row hidden while nothing measures it",
          widget.temp_widget.isVisible(), False)

    system_stats.read_temperatures = lambda: [("CPU", 91.0)]
    widget._update_temperatures()
    app.processEvents()
    check("temperature row appears once a sensor answers",
          widget.temp_widget.isVisible(), True)
    check("temperature value comes from the sensor",
          widget.temp_widget.value_label.text(), "91°C")
    check("hot sensor is not shown as calm green",
          "FF6B6B" in widget.temp_widget.value_label.styleSheet(), True)
    system_stats.read_temperatures = lambda: [("CPU", 44.0), ("GPU", 39.0)]
    widget._update_temperatures()
    app.processEvents()
    check("coolest reading keeps the green label",
          "66BB6A" in widget.temp_widget.value_label.styleSheet(), True)
    def sensor_texts(item):
        out = []
        for index in range(item.sensor_layout.count()):
            label = item.sensor_layout.itemAt(index).widget()
            if label is not None and label.text():
                out.append(label.text())
        return out

    sensors = sensor_texts(widget.temp_widget)
    check("sensor labels list both sources", sensors, ["CPU", "44°C", "GPU", "39°C"])
    system_stats.read_temperatures = real_temps

    widget._gpu_supported = True
    system_stats.read_gpu = lambda: None
    widget._on_gpu_measured(None)
    app.processEvents()
    check("GPU row hides when no source answers", widget.gpu_widget.isVisible(), False)
    check("gpu polling stops when unsupported", widget._gpu_timer.isActive(), False)
    check("hidden GPU row keeps no stale text",
          (widget.gpu_widget.value_label.text(),
           widget.gpu_widget.detail_label.text()), ("", ""))

    # 6) Counterfactual: nguồn GPU "thật" phải in đúng tên nó đọc được.
    fake = {"name": "Test Adapter 9000", "percent": 37.0,
            "detail": "Test Adapter 9000\n1.5 GB / 4.0 GB", "temp": 63.0,
            "source": "nvidia-smi"}
    system_stats.read_gpu = lambda: fake
    widget._gpu_supported = True
    widget._probe_gpu()
    deadline = time.time() + 4.0
    while time.time() < deadline and widget._gpu_busy:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    check("GPU row shows the name its source reported",
          fake["name"] in widget.gpu_widget.detail_label.text(), True)
    check("GPU utilisation shown when the source provides it",
          widget.gpu_widget.value_label.text(), "37%")
    check("GPU temperature feeds the temperature row",
          widget.temp_widget.value_label.text(), "63°C")
    system_stats.read_gpu = real_gpu

    # 7) Poll phải chạy ngoài lúc trang bị ẩn, và không tốn thời gian trên GUI.
    started = time.perf_counter()
    widget._update_stats()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    check("one GUI-thread poll stays under 60 ms", elapsed_ms < 60.0, True)
    print("  poll cost: %.1f ms" % elapsed_ms)
    check("polling active while shown", widget._timer.isActive(), True)
    widget.hide()
    app.processEvents()
    check("polling stops when the page is hidden", widget._timer.isActive(), False)
    widget.show()
    app.processEvents()
    check("polling resumes when the page is shown", widget._timer.isActive(), True)

    # 8) Ảnh bằng chứng phải chụp từ nguồn đo THẬT, không phải payload giả ở
    #    bước counterfactual.
    system_stats.read_temperatures = real_temps
    system_stats.read_gpu = real_gpu
    widget._gpu_supported = True
    widget._probe_gpu()
    deadline = time.time() + 6.0
    while time.time() < deadline and widget._gpu_busy:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    widget._update_stats()
    app.processEvents()
    print("  screenshot state: cpu=%s ram=%s gpu=%s temp=%s storage=%s" % (
        ascii(widget.cpu_widget.value_label.text()),
        ascii(widget.ram_widget.detail_label.text()),
        ascii(widget.gpu_widget.detail_label.text()),
        ascii(widget.temp_widget.value_label.text()),
        ascii(widget.storage_widget.detail_label.text())))
    check("GPU row shows the card actually installed",
          "GTX 1650" not in widget.gpu_widget.detail_label.text(), True)
    measurable = bool(system_stats.read_temperatures()
                      or (widget._gpu or {}).get("temp"))
    check("temperature row visibility follows the sources it can read",
          widget.temp_widget.isVisible(), measurable)
    measurable_gpu = widget._gpu is not None
    check("GPU row visibility follows its source",
          widget.gpu_widget.isVisible(), measurable_gpu)

    here = os.path.dirname(os.path.abspath(__file__))
    shot = os.path.join(here, "monitor_widget.png")
    widget.grab().save(shot)
    print("  widget screenshot:", shot, os.path.getsize(shot), "bytes")

    page = home_page.HomePage()
    page.resize(1680, 900)
    page.show()
    deadline = time.time() + 4.0
    while time.time() < deadline and not page.system_monitor.cpu_widget.value_label.text():
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    page_shot = os.path.join(here, "monitor_home.png")
    page.grab().save(page_shot)
    print("  home screenshot:", page_shot, os.path.getsize(page_shot), "bytes")
    check("real HomePage renders the same data",
          bool(pct.match(page.system_monitor.cpu_widget.value_label.text())), True)

    print("\nsummary:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
    for line in FAILS:
        print(" -", line)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
