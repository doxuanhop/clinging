"""
core/system_stats.py
Số liệu hệ thống THẬT cho bảng theo dõi ở trang chủ.

Quy tắc: không đo được thì trả None / [] để UI ẩn dòng đi. Module này cố ý
không import Qt để chạy được trong test và trong worker thread.
"""

from __future__ import annotations

import os
import shutil
import subprocess

GIB = 1024.0 ** 3
MIB = 1024.0 ** 2
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Win32_VideoController chỉ gọi một lần: tên card không đổi, spawn process mỗi
# 2 giây là phí. nvidia-smi thì phải hỏi lại vì có utilisation.
_WMI_GPU_CACHE: list = []

_SENSOR_LABELS = {
    "k10temp": "CPU",
    "coretemp": "CPU",
    "cpu_thermal": "CPU",
    "acpitz": "Hệ thống",
    "nvidia": "GPU",
    "radeon": "GPU",
    "nvme": "SSD",
    "iwlwifi": "WiFi",
    "BAT": "Pin",
}


def psutil_or_none():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _clamp(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


# ── CPU / RAM / ổ đĩa ────────────────────────────────────────────

def prime_cpu():
    """cpu_percent(interval=None) cần một lần gọi mồi; lần gọi sau mới có số."""
    ps = psutil_or_none()
    if ps is None:
        return False
    ps.cpu_percent(interval=None)
    return True


def read_cpu():
    ps = psutil_or_none()
    if ps is None:
        return None
    percent = _clamp(ps.cpu_percent(interval=None))
    detail = None
    freq = None
    try:
        freq = ps.cpu_freq()
    except Exception:
        freq = None
    if freq:
        current = (freq.current or 0.0) / 1000.0
        peak = (freq.max or 0.0) / 1000.0
        if current > 0 and peak > current:
            detail = "%.2f / %.2f GHz" % (current, peak)
        elif current > 0:
            detail = "%.2f GHz" % current
        elif peak > 0:
            detail = "%.2f GHz đỉnh" % peak
    if detail is None:
        threads = ps.cpu_count(logical=True)
        if threads:
            detail = "%d luồng" % threads
    if percent is None and detail is None:
        return None
    return {"percent": percent, "detail": detail}


def read_memory():
    ps = psutil_or_none()
    if ps is None:
        return None
    try:
        vm = ps.virtual_memory()
    except Exception:
        return None
    used = vm.total - getattr(vm, "available", vm.used)
    return {
        "percent": _clamp(vm.percent),
        "detail": "%.1f GB / %.1f GB" % (used / GIB, vm.total / GIB),
    }


def system_disk_path():
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:")
        drive = (drive[:1] if len(drive) > 1 else drive) + ":"
        return drive + os.sep
    return "/"


def read_disk():
    ps = psutil_or_none()
    if ps is None:
        return None
    path = system_disk_path()
    try:
        usage = ps.disk_usage(path)
    except Exception:
        return None
    label = os.path.splitdrive(path)[0] or path
    return {
        "percent": _clamp(usage.percent),
        "detail": "%s  %.0f GB / %.0f GB" % (label, usage.used / GIB, usage.total / GIB),
    }


# ── GPU ──────────────────────────────────────────────────────────

def _run_quiet(cmd, timeout=6):
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=_NO_WINDOW)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or b"").decode("utf-8", "replace")


def _nvidia_smi_path():
    found = shutil.which("nvidia-smi")
    if found:
        return found
    root = os.environ.get("SystemRoot", r"C:\Windows")
    for sub in ("System32", "Sysnative", "SysWOW64"):
        candidate = os.path.join(root, sub, "nvidia-smi.exe")
        if os.path.exists(candidate):
            return candidate
    return None


def _read_nvidia():
    binary = _nvidia_smi_path()
    if binary is None:
        return None
    out = _run_quiet([
        binary,
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return None
    line = out.strip().splitlines()[0]
    fields = [f.strip() for f in line.split(",")]
    if len(fields) < 2 or not fields[0]:
        return None

    def number(index):
        try:
            return float(fields[index])
        except (IndexError, ValueError):
            return None

    used, total = number(2), number(3)
    detail = fields[0]
    if used is not None and total:
        detail += "\n%.1f GB / %.1f GB" % (used / MIB, total / MIB)
    return {
        "name": fields[0],
        "percent": _clamp(number(1)),
        "detail": detail,
        "temp": number(4),
        "source": "nvidia-smi",
    }


def _read_wmi():
    if _WMI_GPU_CACHE:
        return _WMI_GPU_CACHE[0]
    out = _run_quiet([
        "wmic", "path", "Win32_VideoController",
        "get", "Name,AdapterRAM", "/format:list",
    ])
    if not out:
        return None
    adapters, name, ram = [], None, None
    for raw in out.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "name":
            if name:
                adapters.append((name, ram))
                ram = None
            name = value
        elif key == "adapterram":
            try:
                ram = float(value)
            except ValueError:
                ram = None
    if name:
        adapters.append((name, ram))
    if not adapters:
        return None
    dedicated = [a for a in adapters if any(
        marker in (a[0] or "").lower()
        for marker in ("nvidia", "geforce", "quadro", "rtx", "gtx",
                       "radeon", "arc"))]
    chosen = (dedicated or adapters)[0]
    detail = chosen[0]
    # AdapterRAM là trường 32-bit: từ 4 GB trở lên là con số bịa, không hiển thị.
    if chosen[1] is not None and 0 < chosen[1] < 4 * GIB:
        detail += "\n%.0f GB" % (chosen[1] / GIB)
    gpu = {"name": chosen[0], "percent": None, "detail": detail,
           "temp": None, "source": "wmi"}
    _WMI_GPU_CACHE.append(gpu)
    return gpu


def read_gpu():
    return _read_nvidia() or _read_wmi()


# ── Nhiệt độ ─────────────────────────────────────────────────────

def read_temperatures():
    ps = psutil_or_none()
    reader = getattr(ps, "sensors_temperatures", None) if ps else None
    if reader is None:
        return []
    try:
        table = reader() or {}
    except Exception:
        return []
    entries, seen = [], set()
    for key, rows in table.items():
        label = _SENSOR_LABELS.get(key.lower(), key)
        for row in rows:
            current = getattr(row, "current", None)
            if current is None or not (5.0 <= current <= 150.0):
                continue
            if label in seen:
                continue
            seen.add(label)
            entries.append((label, float(current)))
            break
    entries.sort(key=lambda item: item[1], reverse=True)
    return entries[:4]
