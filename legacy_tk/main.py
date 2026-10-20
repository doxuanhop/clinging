import os
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
import numpy as np
import threading
import time

def handle_tk_exception(*args):
    if len(args) >= 3:
        exc, val, tb = args[:3]
    else:
        return
    val_str = str(val)
    if "invalid command name" in val_str and any(x in val_str for x in ["update", "check_dpi_scaling", "_click_animation"]):
        return
    import traceback
    traceback.print_exception(exc, val, tb)

tk.Tk.report_callback_exception = handle_tk_exception

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False

PLAYSOUND_AVAILABLE = True

OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Clinging_Output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_moviepy():
    """Resolve the moviepy entry points once.

    moviepy 2.x dropped the 1.x module layout, so import the public names and
    fall back to the deep paths; callers must not assume a version.
    """
    try:
        from moviepy import VideoFileClip, ImageClip, CompositeVideoClip
        return True, {"VideoFileClip": VideoFileClip, "ImageClip": ImageClip,
                      "CompositeVideoClip": CompositeVideoClip}
    except Exception:
        pass
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        from moviepy.video.VideoClip import ImageClip
        from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
        return True, {"VideoFileClip": VideoFileClip, "ImageClip": ImageClip,
                      "CompositeVideoClip": CompositeVideoClip}
    except Exception:
        return False, None

MOVIEPY_AVAILABLE, MOVIEPY = get_moviepy()

def find_ffmpeg():
    import shutil
    import os
    import subprocess
    
    paths_to_check = []
    
    path_env = os.environ.get("PATH", "")
    paths_to_check.extend(path_env.split(os.pathsep))
    
    common_paths = [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin"),
        os.path.expanduser(r"~\ffmpeg\bin"),
    ]
    paths_to_check.extend(common_paths)
    
    for search_path in paths_to_check:
        ffmpeg_exe = os.path.join(search_path, "ffmpeg.exe")
        if os.path.exists(ffmpeg_exe):
            return ffmpeg_exe
    
    result = subprocess.run(["where", "ffmpeg"], capture_output=True, text=True, shell=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split('\n')[0]
    
    return None

def cut_audio_with_ffmpeg(input_path, output_path, start_sec, end_sec):
    import subprocess
    import shutil
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        return False
    cmd = [
        ffmpeg_path, "-y",
        "-i", input_path,
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def get_audio_duration_ffmpeg(file_path):
    import subprocess
    import shutil
    import re
    ffmpeg_path = find_ffmpeg()
    cmd = [ffmpeg_path, "-i", file_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stderr
        match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', output)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except:
        pass
    return 0

# --- ASR core (AsrTools-v1.1.0 / bk_asr) -------------------------------------
# src/asr holds the vendored engines; the editor drives them directly instead of
# shipping a second GUI, so a transcript can become timeline clips.
ASR_ENGINES = ["Bcut (Bilibili)", "Faster Whisper (local)", "JianYing (CapCut)"]
ASR_FORMATS = ["SRT", "ASS", "TXT", "VTT"]
ASR_LANGS = ["Auto", "Vietnamese", "English", "Chinese", "Japanese", "Korean"]
ASR_LANG_CODES = {"Auto": None, "Vietnamese": "vi", "English": "en",
                  "Chinese": "zh", "Japanese": "ja", "Korean": "ko"}

def asr_module():
    import sys
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import src.asr as asr
    return asr

def asr_ffmpeg_path():
    import sys
    exe = find_ffmpeg()
    if exe:
        return exe
    # AsrTools ships its own ffmpeg; use it when nothing is installed system-wide.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(base, "AsrTools-v1.1.0", "ffmpeg.exe")
    return bundled if os.path.exists(bundled) else None

def asr_audio_for_upload(media_path):
    """Return (upload path, is_temporary); cloud engines only read mp3/wav/m4a/flac."""
    asr = asr_module()
    if not asr.requires_audio(media_path):
        return media_path, False
    import subprocess
    import tempfile
    exe = asr_ffmpeg_path()
    if not exe:
        raise RuntimeError("ffmpeg is required to send this media to a cloud ASR engine. "
                           "Install ffmpeg, or keep the AsrTools-v1.1.0 folder next to Clinging.")
    work_dir = os.path.join(tempfile.gettempdir(), "clinging_asr")
    os.makedirs(work_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(media_path))[0][:40] or "audio"
    out_path = os.path.join(work_dir, "%s_%d.mp3" % (stem, abs(hash(media_path)) % 10 ** 8))
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        cmd = [exe, "-y", "-i", media_path, "-vn", "-ac", "1", "-ar", "16000",
               "-f", "mp3", "-q:a", "4", out_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(out_path):
            detail = (result.stderr or "").strip().splitlines()
            raise RuntimeError("Could not extract audio: " + (detail[-1] if detail else "ffmpeg failed"))
    return out_path, True

def asr_local_segments(audio_path, language, progress):
    """Offline engine; returns timed segments like the cloud engines do."""
    from faster_whisper import WhisperModel
    progress(15, "Loading Faster Whisper model...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    progress(30, "Transcribing locally...")
    segments, info = model.transcribe(audio_path, language=language or None,
                                      beam_size=5, vad_filter=True)
    total = max(1.0, float(getattr(info, "duration", 0.0) or 0.0))
    result = []
    for seg in segments:
        if seg.text.strip():
            result.append({"text": seg.text.strip(),
                           "start_ms": int(round(seg.start * 1000)),
                           "end_ms": int(round(seg.end * 1000))})
        progress(30 + min(65, int(65 * seg.end / total)), "%d lines so far" % len(result))
    return result

def asr_data_to_file(asr_data, out_path):
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".ass":
        text = asr_data.to_ass()
    elif ext == ".txt":
        text = asr_data.to_txt()
    elif ext == ".vtt":
        text = "WEBVTT" + chr(10) + chr(10) + asr_data.to_srt().replace(",", ".")
    else:
        text = asr_data.to_srt()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path

# --- animation core -----------------------------------------------------------
# src/anim holds the frame-space effects. The player and the exporter both go
# through it, so an effect that reads correctly in preview is what gets rendered.
def anim_module():
    import sys
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import src.anim
    return src.anim

ANIM = anim_module()

# --------------------------------------------------------------------------- #
# UI theme tokens (shared by the top bar, tool rail, panels and timeline)
# --------------------------------------------------------------------------- #
UI_FONT = "Segoe UI"
UI_BG = "#0A0A0C"          # window background / sash gaps
UI_RAIL = "#101014"        # top bar + left tool rail
UI_PANEL = "#15151A"       # panel cards
UI_HEADER = "#1D1D24"      # section headers inside a panel
UI_FIELD = "#0F0F13"       # inputs, dropdowns, canvas wells
UI_HOVER = "#23232B"
UI_BORDER = "#2A2A33"
UI_TEXT = "#EAEAEE"
UI_MUTED = "#8C8C97"
UI_DIM = "#5E5E68"
UI_ACCENT = "#00E5FF"
UI_ACCENT_SOFT = "#00A8BD"
UI_ACCENT_BG = "#0C2A31"


def _glyph(name, d, k, w, col):
    """Draw a line icon on a 24x24 design grid scaled by ``k`` (pixels per unit)."""
    def P(*v):
        return [(x * k, y * k) for x, y in zip(v[::2], v[1::2])]

    def line(*v):
        d.line(P(*v), fill=col, width=w, joint="curve")

    def ell(*v):
        d.ellipse([v[0] * k, v[1] * k, v[2] * k, v[3] * k], outline=col, width=w)

    def ellf(*v):
        d.ellipse([v[0] * k, v[1] * k, v[2] * k, v[3] * k], fill=col)

    def rect(*v, radius=2):
        d.rounded_rectangle([v[0] * k, v[1] * k, v[2] * k, v[3] * k],
                            radius=radius * k, outline=col, width=w)

    def rectf(*v):
        d.rectangle([v[0] * k, v[1] * k, v[2] * k, v[3] * k], fill=col)

    def poly(*v, fill=None):
        d.polygon(P(*v), outline=col, width=w, fill=fill or col)

    def opoly(*v):
        d.polygon(P(*v), outline=col, width=w)

    def arc(x0, y0, x1, y1, a0, a1):
        d.arc([x0 * k, y0 * k, x1 * k, y1 * k], a0, a1, fill=col, width=w)

    def star(cx, cy, r, ir):
        pts = []
        for i in range(8):
            ang = -1.5708 + i * 0.7854
            rad = r if i % 2 == 0 else ir
            pts.append(((cx + rad * math.cos(ang)) * k,
                        (cy + rad * math.sin(ang)) * k))
        d.polygon(pts, fill=col)

    if name in ("media", "video"):
        rect(3, 5, 21, 19)
        line(3, 9, 21, 9)
        line(7, 5, 7, 9)
        line(13, 5, 13, 9)
        line(19, 5, 19, 9)
    elif name == "audio":
        ell(4.5, 14.5, 9.5, 19.5)
        ell(14.5, 12.5, 19.5, 17.5)
        line(9, 17, 9, 6)
        line(19, 15, 19, 4)
        line(9, 6, 19, 4)
    elif name == "text":
        line(6, 5, 18, 5)
        line(12, 5, 12, 19)
        line(9, 19, 15, 19)
    elif name == "transitions":
        opoly(4, 5, 13, 12, 4, 19)
        opoly(20, 5, 11, 12, 20, 19)
    elif name == "effects":
        star(10, 10, 6.5, 2.2)
        star(18, 17, 3.6, 1.2)
    elif name == "elements":
        ell(3.5, 3.5, 12.5, 12.5)
        rect(12, 12, 21, 21)
    elif name == "filters":
        opoly(3.5, 5, 20.5, 5, 13.5, 12.5, 13.5, 19.5, 10.5, 17.5, 10.5, 12.5)
    elif name == "overlays":
        rect(3.5, 3.5, 15.5, 15.5)
        rect(8.5, 8.5, 20.5, 20.5)
    elif name == "adjustment":
        line(4, 8, 20, 8)
        line(4, 16, 20, 16)
        ell(8, 5.5, 11.5, 10.5)
        ell(14, 13.5, 17.5, 18.5)
    elif name == "ai":
        ell(3, 3, 21, 21)
        star(12, 12, 6.5, 2.2)
    elif name == "plus":
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif name == "plus_circle":
        ell(3, 3, 21, 21)
        line(12, 7.5, 12, 16.5)
        line(7.5, 12, 16.5, 12)
    elif name == "minus":
        line(5, 12, 19, 12)
    elif name == "search":
        ell(4.5, 4.5, 15, 15)
        line(14, 14, 20, 20)
    elif name == "sort":
        line(4, 7, 14, 7)
        line(4, 12, 11, 12)
        line(4, 17, 8, 17)
        line(18, 6, 18, 18)
        poly(*[15, 15, 21, 15, 18, 19])
    elif name == "chevron_down":
        line(7, 10, 12, 15)
        line(12, 15, 17, 10)
    elif name == "chevron_up":
        line(7, 14, 12, 9)
        line(12, 9, 17, 14)
    elif name == "chevron_left":
        line(14, 7, 9, 12)
        line(9, 12, 14, 17)
    elif name == "chevron_right":
        line(10, 7, 15, 12)
        line(15, 12, 10, 17)
    elif name == "undo":
        arc(5, 6, 19, 20, 180, 330)
        poly(2.5, 13, 8, 9.5, 8, 16.5)
    elif name == "redo":
        arc(5, 6, 19, 20, 210, 360)
        poly(16, 9.5, 21.5, 13, 16, 16.5)
    elif name == "cut":
        ell(4, 13.5, 8, 17.5)
        ell(4, 6.5, 8, 10.5)
        line(7.6, 14.6, 20, 7)
        line(7.6, 9.4, 20, 17)
    elif name == "trash":
        rect(6, 8, 18, 20, radius=1)
        line(4, 8, 20, 8)
        line(9.5, 8, 9.5, 4.5)
        line(14.5, 8, 14.5, 4.5)
        line(9.5, 4.5, 14.5, 4.5)
        line(10, 11.5, 10, 17)
        line(14, 11.5, 14, 17)
    elif name == "copy":
        rect(4, 4, 15, 15, radius=1)
        rect(9, 9, 20, 20, radius=1)
    elif name == "paste":
        rect(5.5, 5, 18.5, 20, radius=2)
        rect(9, 2.5, 15, 6.5, radius=1)
    elif name == "lock":
        rect(5.5, 10.5, 18.5, 20, radius=2)
        arc(8, 4, 16, 12, 180, 360)
        line(8, 8, 8, 10.5)
        line(16, 8, 16, 10.5)
    elif name == "unlock":
        rect(5.5, 10.5, 18.5, 20, radius=2)
        arc(8, 4, 16, 12, 180, 335)
        line(8, 8, 8, 10.5)
    elif name == "eye":
        ell(3.5, 8.5, 20.5, 15.5)
        ellf(10.2, 10.6, 13.8, 13.4)
    elif name == "eye_off":
        ell(3.5, 8.5, 20.5, 15.5)
        line(4, 20, 20, 4)
    elif name == "speaker":
        poly(*[4, 10, 8, 10, 12.5, 6, 12.5, 18, 8, 14, 4, 14])
        arc(13, 8, 19, 16, 300, 60)
    elif name == "speaker_off":
        poly(*[4, 10, 8, 10, 12.5, 6, 12.5, 18, 8, 14, 4, 14])
        line(15, 9.5, 20.5, 15)
        line(20.5, 9.5, 15, 15)
    elif name == "mic":
        rect(9.5, 3, 14.5, 13, radius=2.5)
        arc(6.5, 8.5, 17.5, 16.5, 0, 180)
        line(12, 16.5, 12, 20)
        line(9, 20, 15, 20)
    elif name == "zoom_in":
        ell(4.5, 4.5, 15, 15)
        line(14, 14, 20, 20)
        line(7.5, 9.8, 12, 9.8)
        line(9.8, 7.5, 9.8, 12)
    elif name == "zoom_out":
        ell(4.5, 4.5, 15, 15)
        line(14, 14, 20, 20)
        line(7.5, 9.8, 12, 9.8)
    elif name == "magnet":
        arc(5.5, 5.5, 18.5, 18.5, 180, 360)
        line(5.5, 12, 5.5, 18)
        line(18.5, 12, 18.5, 18)
        line(3.5, 18, 7.5, 18)
        line(16.5, 18, 20.5, 18)
    elif name == "split":
        line(12, 3, 12, 21)
        poly(*[4, 9, 9, 12, 4, 15])
        poly(*[20, 9, 15, 12, 20, 15])
    elif name == "play":
        poly(*[8, 5, 19, 12, 8, 19])
    elif name == "pause":
        rectf(7, 5, 10.5, 19)
        rectf(13.5, 5, 17, 19)
    elif name == "skip_start":
        line(6, 5, 6, 19)
        poly(*[19, 5, 19, 19, 9, 12])
    elif name == "skip_end":
        line(18, 5, 18, 19)
        poly(*[5, 5, 5, 19, 15, 12])
    elif name == "step_prev":
        line(7, 6, 7, 18)
        poly(*[17, 6, 17, 18, 10, 12])
    elif name == "step_next":
        line(17, 6, 17, 18)
        poly(*[7, 6, 7, 18, 14, 12])
    elif name == "settings":
        ell(7, 7, 17, 17)
        for i in range(8):
            a = i * 0.7854
            line(12 + 5 * math.cos(a), 12 + 5 * math.sin(a),
                 12 + 8.2 * math.cos(a), 12 + 8.2 * math.sin(a))
    elif name == "camera":
        rect(3, 8, 21, 19, radius=2)
        line(9, 8, 10.5, 5)
        line(10.5, 5, 13.5, 5)
        line(13.5, 5, 15, 8)
        ell(8.5, 11, 15.5, 17)
    elif name == "reset":
        arc(5, 5, 19, 19, 300, 210)
        line(17.5, 3.5, 18.6, 8.4)
        line(18.6, 8.4, 13.7, 7.4)
    elif name == "diamond":
        opoly(12, 4.5, 19.5, 12, 12, 19.5, 4.5, 12)
    elif name == "flip_h":
        line(12, 3, 12, 21)
        poly(*[9, 7, 3, 12, 9, 17])
        poly(*[15, 7, 21, 12, 15, 17])
    elif name == "flip_v":
        line(3, 12, 21, 12)
        poly(*[7, 9, 12, 3, 17, 9])
        poly(*[7, 15, 12, 21, 17, 15])
    elif name == "rotate":
        arc(4.5, 4.5, 19.5, 19.5, 320, 230)
        poly(*[19.5, 4, 20.5, 9.5, 15.5, 7.5])
    elif name == "frame":
        rect(4, 6, 20, 18, radius=1)
    elif name == "frame_fill":
        rect(4, 4, 20, 20, radius=1)
        line(9, 9, 15, 15)
        line(15, 9, 9, 15)
    elif name == "crop":
        rect(6, 3, 18, 21, radius=1)
        line(3, 9, 21, 9)
    elif name == "fit_width":
        rect(3, 8, 21, 16, radius=1)
        line(7, 5, 7, 19)
        line(17, 5, 17, 19)
    elif name == "link":
        rect(3, 8, 13, 16, radius=4)
        rect(11, 8, 21, 16, radius=4)
    elif name == "export":
        line(4, 15, 4, 20)
        line(4, 20, 20, 20)
        line(20, 20, 20, 15)
        line(12, 14, 12, 4)
        poly(*[8, 8, 12, 3.5, 16, 8])
    elif name == "help":
        ell(3.5, 3.5, 20.5, 20.5)
        arc(9, 7.5, 15, 13, 200, 20)
        line(12, 12, 12, 15)
        ellf(11, 17, 13, 19)
    elif name == "image":
        rect(3.5, 5, 20.5, 19, radius=2)
        ell(7.5, 8.5, 11, 12)
        poly(*[6, 17, 11, 12, 14, 15, 17, 13, 20, 16])
    elif name == "folder":
        poly(*[3.5, 7, 9.5, 7, 11.5, 9.5, 20.5, 9.5, 20.5, 19, 3.5, 19])
    elif name == "cloud":
        arc(6, 6, 15, 15, 150, 390)
        arc(11, 8, 19, 15, 250, 360)
        line(6, 15, 18, 15)
    elif name == "menu":
        line(4, 7, 20, 7)
        line(4, 12, 20, 12)
        line(4, 17, 20, 17)
    elif name == "panel_right":
        rect(3.5, 5, 20.5, 19, radius=2)
        line(14, 5, 14, 19)
    elif name == "panel_left":
        rect(3.5, 5, 20.5, 19, radius=2)
        line(10, 5, 10, 19)
    elif name == "close":
        line(6, 6, 18, 18)
        line(18, 6, 6, 18)
    elif name == "minimize":
        line(5, 17, 19, 17)
    elif name == "maximize":
        rect(5, 5, 19, 19, radius=1)
    elif name == "marker":
        poly(*[6, 3, 18, 3, 18, 14, 12, 18, 6, 14])
    elif name == "keyframe":
        poly(*[12, 4, 19, 12, 12, 20, 5, 12], fill=col)
    elif name == "waveform":
        for i, h in enumerate((4, 8, 3, 11, 6, 9, 4, 7, 10, 5)):
            line(4 + i * 1.8, 12 - h / 2, 4 + i * 1.8, 12 + h / 2)
    elif name == "track_video":
        rect(3.5, 6, 20.5, 18, radius=2)
        poly(*[10, 9, 16, 12, 10, 15])
    elif name == "track_text":
        rect(3.5, 5, 20.5, 19, radius=2)
        line(8, 9, 16, 9)
        line(12, 9, 12, 16)
    elif name == "dial":
        ell(4, 4, 20, 20)
        line(12, 12, 16.5, 7.5)
        ellf(15.2, 6.2, 17.8, 8.8)
    elif name == "spinner":
        opoly(12.5, 8, 16, 4.5, 19.5, 8)
        opoly(12.5, 16, 16, 19.5, 19.5, 16)
    elif name == "brand":
        d.arc([4 * k, 3.5 * k, 20 * k, 20.5 * k], 50, 310, fill=col, width=int(w * 2.4))
    else:
        ell(5, 5, 19, 19)


_UI_IMAGE_CACHE = {}
_UI_PHOTO_CACHE = {}


def _glyph_bitmap(name, px, color, bg=None, pad=0, ss=4):
    side = (px + 2 * pad) * ss
    img = Image.new("RGBA", (side, side), bg if bg is not None else (0, 0, 0, 0))
    canvas = Image.new("RGBA", (px * ss, px * ss), (0, 0, 0, 0))
    k = px * ss / 24.0
    _glyph(name, ImageDraw.Draw(canvas), k, max(1, int(round(k * 1.5))), color)
    img.alpha_composite(canvas, (pad * ss, pad * ss))
    return img.resize((px + 2 * pad, px + 2 * pad), Image.LANCZOS)


def ui_icon(name, px, color=UI_TEXT):
    """A crisp line icon drawn at runtime, cached as a CTkImage."""
    key = (name, px, color)
    cached = _UI_IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    img = _glyph_bitmap(name, px, color)
    out = ctk.CTkImage(light_image=img, dark_image=img, size=(px, px))
    _UI_IMAGE_CACHE[key] = out
    return out


def ui_badge(name, px, color=UI_TEXT, bg=UI_FIELD, pad=3):
    """The same glyph on a solid chip, for overlaying on thumbnails."""
    key = (name, px, color, bg, pad)
    cached = _UI_PHOTO_CACHE.get(key)
    if cached is not None:
        return cached
    img = _glyph_bitmap(name, px, color, bg=bg, pad=pad)
    out = ImageTk.PhotoImage(img)
    _UI_PHOTO_CACHE[key] = out
    return out


MEDIA_TYPE_GLYPHS = {"video": "track_video", "audio": "audio",
                     "image": "image", "text": "text"}


def format_timecode(seconds, fps=30):
    total = float(seconds or 0)
    whole = int(total)
    frames = int(round((total - whole) * fps)) % fps
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d:%02d" % (h, m, s, frames)


def format_duration(seconds):
    total = int(round(seconds or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


class TimelineClip:
    def __init__(self, file_path, start_time=0, duration=5, clip_type='video', track_idx=0):
        self.file_path = file_path
        self.start_time = start_time
        self.duration = duration
        self.clip_type = clip_type
        self.track_idx = track_idx
        self.mv_clip = None
        self.is_pinned = False
        self.group_id = None
        self.x_pos = 0.5
        self.y_pos = 0.85
        self.text_content = ""
        self.font = "Arial"
        self.font_size = 32
        self.text_color = "#FFFFFF"
        self.bg_color = "#000000"
        self.motion_effect = "none"
        self.motion_intensity = 5
        self.text_effect = "none"
        self.text_intensity = 5

class ClingingApp:
    # Layout tokens: top bar, left tool rail and the video properties panel
    TOPBAR_H = 46
    SIDEBAR_W = 112
    SIDEBAR_ICON_PX = 26
    SIDEBAR_LABEL_PX = 11
    SIDEBAR_ITEM_H = 62
    SIDEBAR_PAD_Y = 2
    PANEL_PAD = 12
    THUMB_SIZE = (128, 72)
    ASSETS_W = 392
    PROPS_W = 360

    PROPS_PAD = 14
    PROPS_LABEL_W = 84
    PROPS_VALUE_W = 64
    PROPS_ROW_H = 28
    PROPS_FONT = (UI_FONT, 12)
    PROPS_SECTION_FONT = (UI_FONT, 13, "bold")

    def __init__(self, project_data=None):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("Clinging - Video Editor")
        self.root.geometry("1400x900")
        
        self.media_files = []
        self.media_types = []
        self.thumbnails = {}
        self.current_file = None
        self.preview_clip = None
        self.timeline_clips = []
        self._audio_thread = None
        self._stop_audio = False
        self.video_path = None # File path for the main video (if any)
        
        from datetime import datetime
        
        if project_data:
            self.project_id = project_data.get("id")
            self.project_name = project_data.get("name", datetime.now().strftime("%y%m%d-%H%M"))
            
            # Load timeline clips
            for c_data in project_data.get("clips", []):
                clip = TimelineClip(
                    c_data.get("file_path"),
                    c_data.get("start_time", 0),
                    c_data.get("duration", 5),
                    c_data.get("clip_type", "video"),
                    c_data.get("track_idx", 0)
                )
                clip.is_pinned = c_data.get("is_pinned", False)
                clip.group_id = c_data.get("group_id")
                clip.x_pos = c_data.get("x_pos", 320)
                clip.y_pos = c_data.get("y_pos", 180)
                clip.motion_effect = c_data.get("motion_effect", "none")
                clip.motion_intensity = c_data.get("motion_intensity", 5)
                clip.text_effect = c_data.get("text_effect", "none")
                clip.text_intensity = c_data.get("text_intensity", 5)
                if c_data.get("clip_type") == "text":
                    clip.text_content = c_data.get("text_content", "Text")
                    clip.font_size = c_data.get("font_size", 36)
                    clip.text_color = c_data.get("text_color", "white")
                    clip.bg_color = c_data.get("bg_color", "transparent")
                self.timeline_clips.append(clip)
                
                # Add to media files - kiểm tra file tồn tại
                f = c_data.get("file_path")
                mtype = c_data.get("clip_type", "video")
                if f:
                    if f not in self.media_files:
                        self.media_files.append(f)
                        self.media_types.append(mtype)
                    # Generate thumbnail
                    if os.path.exists(f):
                        self.generate_thumbnail(f)
            
            # Load thumbnail
            thumb_path = project_data.get("thumb_path", "")
            if thumb_path and os.path.exists(thumb_path):
                try:
                    self.project_thumb = thumb_path
                except:
                    pass
        else:
            self.project_id = None
            self.project_name = datetime.now().strftime("%y%m%d-%H%M")
            
        self.is_playing = False
        self.zoom_level = 1.0
        self.active_tab = "All"
        self.playhead_x = 100
        self.pixels_per_second = 30.0
        self.selected_clips = []
        self.timeline_photos = []
        self.selected_media_indices = []
        
        # Panel visibility states
        self.assets_collapsed = False
        self.props_collapsed = False

        
        # Setup drag & drop (optional - requires tkinterdnd2)
        try:
            self.root.drop_target_register('DND_Files')
            self.root.dnd_bind('<<Drop>>', self.on_file_drop)
        except:
            pass  # tkinterdnd2 not available
        
        # Create UI first
        self.create_ui()
        
        # If loading from project, rebuild timeline and thumbnails after UI is ready
        if project_data and self.timeline_clips:
            self.root.after(100, self._load_project_complete)
    
    def _load_project_complete(self):
        """Hoàn tất việc load project sau khi UI ready"""
        self.draw_timeline_clips()
        self.refresh_thumbnails()
        
    def create_ui(self):
        self.root.configure(fg_color=UI_BG)
        # Layout: [top bar spanning both columns] / [rail | work area]
        self.root.grid_columnconfigure(0, weight=0) # Sidebar
        self.root.grid_columnconfigure(1, weight=1) # Main area
        self.root.grid_rowconfigure(0, weight=0, minsize=self.TOPBAR_H) # Top Bar
        self.root.grid_rowconfigure(1, weight=1) # Vertical center

        self.create_top_bar()

        # Sidebar Frame (Main Tools) - scrollable so larger icons still fit
        self.sidebar_frame = ctk.CTkFrame(self.root, fg_color=UI_RAIL, width=self.SIDEBAR_W, corner_radius=0)
        self.sidebar_frame.grid(row=1, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        ctk.CTkFrame(self.sidebar_frame, width=1, fg_color=UI_BORDER).grid(
            row=0, column=1, sticky="ns")
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(0, weight=1)
        self.sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, fg_color="transparent",
                                                     scrollbar_button_color=UI_RAIL,
                                                     scrollbar_button_hover_color=UI_HOVER)
        self.sidebar_scroll.grid(row=0, column=0, sticky="nsew", padx=2, pady=4)

        # Main Vertical PanedWindow (Middle Panels vs Timeline)
        self.main_paned = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg=UI_BG, bd=0, sashwidth=5,
                                         sashrelief=tk.FLAT)
        self.main_paned.grid(row=1, column=1, sticky="nsew")
        
        # Horizontal PanedWindow for Middle Panels
        self.middle_paned = tk.PanedWindow(self.main_paned, orient=tk.HORIZONTAL, bg=UI_BG, bd=0, sashwidth=5,
                                           sashrelief=tk.FLAT)
        self.main_paned.add(self.middle_paned, stretch="always", minsize=200)
        
        # Panels containers
        self.assets_container = ctk.CTkFrame(self.middle_paned, fg_color=UI_BG, corner_radius=0)
        self.preview_container = ctk.CTkFrame(self.middle_paned, fg_color=UI_BG, corner_radius=0)
        self.properties_container = ctk.CTkFrame(self.middle_paned, fg_color=UI_BG, corner_radius=0)
        
        self.middle_paned.add(self.assets_container, minsize=200)
        self.middle_paned.add(self.preview_container, stretch="always", minsize=300)
        self.middle_paned.add(self.properties_container, minsize=200)
        
        # Create actual panels
        self.create_sidebar_content(self.sidebar_scroll)
        self.create_assets_panel(self.assets_container)
        self.create_preview_panel(self.preview_container)
        self.create_properties_panel(self.properties_container)
        
        # Bottom - Timeline Container
        self.timeline_container = ctk.CTkFrame(self.main_paned, fg_color=UI_BG, corner_radius=0)
        self.main_paned.add(self.timeline_container, minsize=150)
        
        self.create_timeline_panel(self.timeline_container)
        
        def set_sashes():
            self.root.update_idletasks()
            w = self.middle_paned.winfo_width()
            if w > 700:
                self.middle_paned.sash_place(0, self.ASSETS_W, 0)
                self.middle_paned.sash_place(1, w - self.PROPS_W, 0)
        self.root.after(200, set_sashes)

    # ---- top bar ---------------------------------------------------------- #
    def create_top_bar(self):
        self.top_menu_btns = {}
        bar = ctk.CTkFrame(self.root, fg_color=UI_RAIL, height=self.TOPBAR_H, corner_radius=0)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(left, text="", image=ui_icon("brand", 26, UI_ACCENT)).pack(side=tk.LEFT, padx=(16, 5))
        ctk.CTkLabel(left, text="Clinging", font=(UI_FONT, 15, "bold"),
                     text_color=UI_TEXT).pack(side=tk.LEFT, padx=(0, 16))
        for label in ("File", "Edit", "Tools", "View", "Help"):
            btn = ctk.CTkButton(left, text=label, width=52, height=26, corner_radius=6,
                                fg_color="transparent", hover_color=UI_HOVER, text_color=UI_TEXT,
                                font=(UI_FONT, 12), anchor="w")
            btn.configure(command=lambda b=btn, l=label: self._open_top_menu(l, b))
            btn.pack(side=tk.LEFT, padx=1)
            self.top_menu_btns[label] = btn

        mid = ctk.CTkFrame(bar, fg_color="transparent")
        mid.grid(row=0, column=1, sticky="")
        self.top_title_lbl = ctk.CTkLabel(mid, text=self.project_name or "Untitled Project",
                                          font=(UI_FONT, 13, "bold"), text_color=UI_TEXT)
        self.top_title_lbl.pack(side=tk.LEFT)
        ctk.CTkFrame(mid, width=1, height=16, fg_color=UI_BORDER).pack(side=tk.LEFT, padx=12, pady=8)
        self.top_status_lbl = ctk.CTkLabel(mid, text="Draft - not saved yet",
                                           font=(UI_FONT, 11), text_color=UI_MUTED)
        self.top_status_lbl.pack(side=tk.LEFT)

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(0, 10))
        for glyph, cmd in (("link", lambda: self._toast("Connections are not configured in this build.")),
                           ("export", self.export_video),
                           ("help", self._show_about)):
            self._icon_btn(right, glyph, cmd).pack(side=tk.LEFT, padx=2)
        ctk.CTkFrame(bar, height=1, fg_color=UI_BORDER).grid(row=1, column=0, columnspan=3, sticky="ew")

    def _icon_btn(self, parent, glyph, command, px=18, size=30, color=None, tip=""):
        btn = ctk.CTkButton(parent, text="", width=size, height=size, corner_radius=7,
                            fg_color="transparent", hover_color=UI_HOVER,
                            image=ui_icon(glyph, px, color or UI_MUTED), command=command)
        if tip:
            btn.bind("<Enter>", lambda e, t=tip: self._show_tip(btn, t), add="+")
            btn.bind("<Leave>", lambda e: self._hide_tip(), add="+")
        return btn

    @staticmethod
    def _menu_defs():
        return {
            "File": [("Import Media", "import_media"), ("Save Project", "save_project"),
                     ("Export Video", "export_video"), None,
                     ("Import Subtitles", "_import_subtitles")],
            "Edit": [("Cut Clip at Playhead", "cut_clip_at_playhead"),
                     ("Delete Selected", "delete_clips"), None,
                     ("Deselect All", "_deselect_all")],
            "Tools": [("Auto Captions", "_auto_captions"), ("Remove Logo", "_show_remove_logo_dialog"),
                      ("Motion Effects", "_goto_motion_tab")],
            "View": [("Toggle Media Panel", "toggle_assets_panel"),
                     ("Toggle Properties Panel", "toggle_properties_panel"), None,
                     ("Zoom Timeline In", "zoom_in"), ("Zoom Timeline Out", "zoom_out")],
            "Help": [("About Clinging", "_show_about")],
        }

    def _open_top_menu(self, label, btn=None):
        entries = self._menu_defs().get(label, [])
        menu = ctk.CTkMenu(self.root, tearoff=0, corner_radius=8, border_width=1,
                           border_color=UI_BORDER, fg_color=UI_HEADER,
                           text_color=UI_TEXT, font=(UI_FONT, 12),
                           hover_color=UI_HOVER)
        for item in entries:
            if item is None:
                menu.add_separator()
                continue
            text, attr = item
            menu.add_command(label=text, command=lambda a=attr: self._run_action(a))
        if btn is not None:
            x, y = btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height() + 2
        else:
            x, y = self.root.winfo_pointer_x(), self.root.winfo_pointer_y()
        menu.tk_popup(x, y)

    def _run_action(self, attr):
        fn = getattr(self, attr, None)
        if callable(fn):
            fn()

    def _goto_motion_tab(self):
        self.on_video_tab_click("Motion")

    def _deselect_all(self):
        self.selected_clips = []
        self._selected_clip = None
        try:
            self.draw_timeline_clips()
        except Exception:
            pass

    def _show_about(self):
        messagebox.showinfo("Clinging", "Clinging Video Editor\n\n"
                            "Non-linear editor with auto-caption, cut-out and "
                            "logo-removal tooling.")

    def _toast(self, text):
        if hasattr(self, "top_status_lbl"):
            self.top_status_lbl.configure(text=text, text_color=UI_MUTED)

    def set_status(self, text):
        if hasattr(self, "top_status_lbl"):
            self.top_status_lbl.configure(text=text, text_color=UI_MUTED)

    def _show_tip(self, widget, text):
        tip = getattr(self, "_tip", None)
        if tip is None:
            tip = self._tip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            lbl = ctk.CTkLabel(tip, text=text, fg_color=UI_HEADER, text_color=UI_TEXT,
                               font=(UI_FONT, 11), corner_radius=6, padx=8, pady=4)
            lbl.pack()
        tip.wm_geometry("+%d+%d" % (widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 4))
        tip.deiconify()
        tip.lift()

    def _hide_tip(self):
        tip = getattr(self, "_tip", None)
        if tip is not None:
            tip.withdraw()

    def create_assets_panel(self, parent):
        left_panel = ctk.CTkFrame(parent, fg_color=UI_PANEL, width=320, corner_radius=8)
        left_panel.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # Panel header: title follows the active rail tab
        assets_header = ctk.CTkFrame(left_panel, fg_color="transparent", height=36)
        assets_header.pack(fill=tk.X, padx=self.PANEL_PAD, pady=(8, 0))
        assets_header.pack_propagate(False)

        self.toggle_left_btn = self._icon_btn(assets_header, "panel_left",
                                              self.toggle_assets_panel, px=17, size=28)
        self.toggle_left_btn.pack(side=tk.RIGHT)
        self.assets_title_lbl = ctk.CTkLabel(assets_header,
                                             text=getattr(self, "_active_asset_tab", "Media"),
                                             font=(UI_FONT, 14, "bold"), text_color=UI_TEXT)
        self.assets_title_lbl.pack(side=tk.LEFT)

        # Divider
        ctk.CTkFrame(left_panel, height=1, fg_color=UI_BORDER).pack(fill=tk.X)
        
        # Dynamic Content Area for Tabs
        self.assets_dynamic_area = ctk.CTkFrame(left_panel, fg_color="transparent")
        self.assets_dynamic_area.pack(fill=tk.BOTH, expand=True)
        
        # Initial render
        self._render_media_tab()

    MEDIA_SUBTABS = ("Project", "Import", "Cloud", "Stock")
    MEDIA_FILTERS = ("All", "Video", "Audio", "Image")
    MEDIA_SORTS = ("Date Added", "Name", "Duration")
        
    RAIL_TABS = (
        ("Media", "media", "_render_media_tab"),
        ("Audio", "audio", "_render_audio_tab"),
        ("Text", "text", "_render_text_tab"),
        ("Transitions", "transitions", "_render_transitions_tab"),
        ("Effects", "effects", "_render_effects_tab"),
        ("Elements", "elements", "_render_stickers_tab"),
        ("Filters", "filters", "_render_filters_tab"),
        ("Overlays", "overlays", "_render_stub_tab"),
        ("Adjustment", "adjustment", "_render_stub_tab"),
        ("AI Tools", "ai", "_render_stub_tab"),
    )

    def create_sidebar_content(self, parent):
        px = self.SIDEBAR_ICON_PX
        self.tab_icons = {}
        for name, glyph, _fn in self.RAIL_TABS:
            self.tab_icons[name] = {
                "active": ui_icon(glyph, px, UI_ACCENT),
                "idle": ui_icon(glyph, px, UI_MUTED),
            }

        self._active_asset_tab = self.RAIL_TABS[0][0]
        self.asset_tab_btns = {}
        for name, _glyph, _fn in self.RAIL_TABS:
            active = name == self._active_asset_tab
            btn = ctk.CTkButton(parent, text=name,
                                image=self.tab_icons[name]["active" if active else "idle"],
                                compound="top",
                                fg_color=UI_ACCENT_BG if active else "transparent",
                                text_color=UI_ACCENT if active else UI_MUTED,
                                hover_color=UI_HOVER, height=self.SIDEBAR_ITEM_H,
                                width=self.SIDEBAR_W - 14,
                                font=(UI_FONT, self.SIDEBAR_LABEL_PX, "bold" if active else "normal"),
                                command=lambda n=name: self._switch_asset_tab(n), corner_radius=8)
            btn.pack(fill=tk.X, padx=5, pady=self.SIDEBAR_PAD_Y)
            self.asset_tab_btns[name] = btn

        footer = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self._icon_btn(footer, "plus_circle", self.import_media, px=22, size=34,
                       color=UI_MUTED).pack(anchor="center")

    def toggle_assets_panel(self):
        """Ẩn/hiện panel bên trái"""
        if self.assets_collapsed:
            self.middle_paned.add(self.assets_container, before=self.preview_container)
            self.assets_collapsed = False
            if hasattr(self, 'expand_left_btn'): self.expand_left_btn.place_forget()
        else:
            self.middle_paned.forget(self.assets_container)
            self.assets_collapsed = True
            self.show_expand_left_button()

    def show_expand_left_button(self):
        if not hasattr(self, 'expand_left_btn'):
            self.expand_left_btn = ctk.CTkButton(self.preview_container, text="»", width=30, height=30, 
                                                fg_color="#1E1E1E", text_color="#00E5FF", hover_color="#333333",
                                                corner_radius=4, command=self.toggle_assets_panel)
        self.expand_left_btn.place(x=5, y=5)

    def toggle_properties_panel(self):
        """Ẩn/hiện panel bên phải"""
        if self.props_collapsed:
            self.middle_paned.add(self.properties_container)
            self.props_collapsed = False
            if hasattr(self, 'expand_right_btn'): self.expand_right_btn.place_forget()
        else:
            self.middle_paned.forget(self.properties_container)
            self.props_collapsed = True
            self.show_expand_right_button()

    def show_expand_right_button(self):
        if not hasattr(self, 'expand_right_btn'):
            self.expand_right_btn = ctk.CTkButton(self.preview_container, text="«", width=30, height=30, 
                                                 fg_color="#1E1E1E", text_color="#00E5FF", hover_color="#333333",
                                                 corner_radius=4, command=self.toggle_properties_panel)
        self.root.update_idletasks()
        self.expand_right_btn.place(relx=1.0, x=-35, y=5)

    def _switch_asset_tab(self, tab_name):
        self._active_asset_tab = tab_name
        if hasattr(self, 'assets_title_lbl'):
            self.assets_title_lbl.configure(text=tab_name)
        
        # Clear dynamic area
        if hasattr(self, 'assets_dynamic_area'):
            for w in self.assets_dynamic_area.winfo_children():
                w.destroy()

        # Update button colors
        if hasattr(self, 'asset_tab_btns'):
            for name, btn in self.asset_tab_btns.items():
                active = name == tab_name
                btn.configure(image=self.tab_icons[name]["active" if active else "idle"],
                              text_color=UI_ACCENT if active else UI_MUTED,
                              fg_color=UI_ACCENT_BG if active else "transparent",
                              font=(UI_FONT, self.SIDEBAR_LABEL_PX, "bold" if active else "normal"))

        target = {n: fn for n, _g, fn in self.RAIL_TABS}.get(tab_name)
        if target:
            getattr(self, target)()

    def _render_stub_tab(self):
        ctk.CTkLabel(self.assets_dynamic_area,
                     text="%s\n\nThis panel is not wired up yet." % self._active_asset_tab,
                     text_color=UI_MUTED, font=(UI_FONT, 12), justify=tk.CENTER).pack(expand=True)

    
    def _render_text_tab(self):
        # Create a container with sidebar and content area
        text_container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        text_container.pack(fill=tk.BOTH, expand=True)
        
        # Left Sidebar for Text Categories
        text_sidebar = ctk.CTkFrame(text_container, fg_color="#262626", width=120)
        text_sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 2))
        text_sidebar.pack_propagate(False)
        
        # Right Content Area
        self.text_content_area = ctk.CTkScrollableFrame(text_container, fg_color="transparent")
        self.text_content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        categories = [
            ("Thêm văn bản", self._show_text_default),
            ("Tài sản của tôi", None),
            ("Hiệu ứng văn bản", None),
            ("Mẫu văn bản", self._show_text_templates),
            ("Auto Captions", self._auto_captions),
            ("Import Subtitles", self._import_subtitles),
        ]
        
        for name, cmd in categories:
            # Add ▾ to items that usually have dropdowns or to match the image
            display_name = name
            if name in ["Tài sản của tôi", "Hiệu ứng văn bản", "Mẫu văn bản"]:
                display_name = name + " ▾"
                
            btn = ctk.CTkButton(text_sidebar, text=display_name, fg_color="transparent", text_color="#AAAAAA", 
                               hover_color="#333", anchor="w", height=35, font=("Segoe UI", 11),
                               command=cmd if cmd else lambda: None)
            btn.pack(fill=tk.X, pady=1)
            if name == "Thêm văn bản":
                btn.configure(fg_color="#333", text_color="#00E5FF") # Highlight active
                
        # Show default category
        self._show_text_default()

    def _show_text_default(self):
        for w in self.text_content_area.winfo_children(): w.destroy()
        
        # Header
        ctk.CTkLabel(self.text_content_area, text="Văn bản mặc định", text_color="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=10)
        
        # Default text card (like CapCut)
        card = ctk.CTkFrame(self.text_content_area, fg_color="#2B2B2B", width=120, height=120, corner_radius=8)
        card.pack(side=tk.LEFT, padx=10, pady=5)
        card.pack_propagate(False)
        
        # Inner frame for the "TI" look
        inner_card = ctk.CTkFrame(card, fg_color="#1E1E1E", corner_radius=4)
        inner_card.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(inner_card, text="Văn bản\nmặc định", text_color="#AAAAAA", font=("Segoe UI", 11)).pack(expand=True)
        
        # Plus icon button at the bottom right
        plus_btn = ctk.CTkButton(card, text="+", width=24, height=24, corner_radius=12,
                                fg_color="#00E5FF", text_color="black", font=("Segoe UI", 14, "bold"),
                                command=self._add_default_text)
        plus_btn.place(relx=1.0, rely=1.0, x=-2, y=-2, anchor="se")
        
        # Hover effect
        card.bind("<Enter>", lambda e: card.configure(fg_color="#333333"))
        card.bind("<Leave>", lambda e: card.configure(fg_color="#2B2B2B"))

    def _show_text_templates(self):
        for w in self.text_content_area.winfo_children(): w.destroy()
        ctk.CTkLabel(self.text_content_area, text="Mẫu văn bản", text_color="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=10)
        
        templates = [
            ("Vlog Title", "#FF6B6B", "white", 24),
            ("News Headline", "#4ECDC4", "white", 18),
            ("TikTok Style", "#FFE66D", "black", 16),
            ("YouTube", "#FF0000", "white", 14),
        ]
        
        for template_name, bg_color, text_color, font_size in templates:
            t_frame = ctk.CTkFrame(self.text_content_area, fg_color="#2B2B2B", corner_radius=6, height=60)
            t_frame.pack(fill=tk.X, padx=10, pady=5)
            t_frame.pack_propagate(False)
            
            lbl = tk.Label(t_frame, text=template_name, bg=bg_color, fg=text_color, font=("Arial", font_size, "bold"), cursor="hand2")
            lbl.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            lbl.bind("<Button-1>", lambda e, name=template_name, bg=bg_color, fg=text_color, fs=font_size*2: self._add_text_template(name, bg, fg, fs))
    
    # ---- Auto captions (AsrTools / bk_asr) -----------------------------------
    ASR_TRACK = 1
    ASR_CAPTION_Y = 318
    ASR_CAPTION_SIZE = 28

    def _asr_default_media(self):
        clip = getattr(self, "_selected_clip", None)
        candidates = []
        if clip is not None and clip.clip_type in ("video", "audio") and clip.file_path:
            candidates.append(clip.file_path)
        candidates.append(getattr(self, "video_path", None))
        if self.media_files:
            candidates.append(self.media_files[0])
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _auto_captions(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Auto Captions")
        dialog.geometry("470x600")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ctk.CTkFrame(dialog, fg_color=UI_PANEL, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True)

        head = ctk.CTkFrame(body, fg_color=UI_HEADER, height=44, corner_radius=0)
        head.pack(fill=tk.X)
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="Auto Captions", text_color=UI_TEXT,
                     font=(UI_FONT, 14, "bold")).pack(side=tk.LEFT, padx=14)
        ctk.CTkLabel(head, text="powered by AsrTools", text_color=UI_DIM,
                     font=(UI_FONT, 11)).pack(side=tk.RIGHT, padx=14)

        scroll = ctk.CTkScrollableFrame(body, fg_color="transparent",
                                        scrollbar_button_color=UI_BORDER,
                                        scrollbar_button_hover_color=UI_HOVER)
        scroll.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        state = {"media": self._asr_default_media(), "busy": False}

        def field(parent, label):
            frame = ctk.CTkFrame(parent, fg_color=UI_HEADER, height=34, corner_radius=0)
            frame.pack(fill=tk.X, pady=(0, 4))
            frame.pack_propagate(False)
            ctk.CTkLabel(frame, text=label, width=96, anchor="w", text_color=UI_MUTED,
                         font=(UI_FONT, 12)).pack(side=tk.LEFT, padx=(10, 4), fill=tk.Y)
            return frame

        media_row = field(scroll, "Media")
        media_lbl = ctk.CTkLabel(media_row, text="", anchor="w", text_color=UI_TEXT,
                                 font=(UI_FONT, 12))
        media_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def refresh_media_lbl():
            path = state["media"]
            if not path:
                media_lbl.configure(text="No file selected", text_color=UI_DIM)
            elif not os.path.exists(path):
                media_lbl.configure(text="Missing: " + os.path.basename(path), text_color="#FF8A8A")
            else:
                media_lbl.configure(text=os.path.basename(path), text_color=UI_TEXT)

        def choose():
            path = filedialog.askopenfilename(parent=dialog, title="Choose media",
                                              filetypes=[("Media", "*.mp3 *.wav *.aac *.m4a *.flac *.ogg "
                                                          "*.mp4 *.avi *.mov *.mkv *.ts *.webm")])
            if path:
                state["media"] = path
                refresh_media_lbl()

        ctk.CTkButton(media_row, text="Browse", width=68, height=24, corner_radius=6,
                      fg_color=UI_FIELD, hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER,
                      text_color=UI_TEXT, font=(UI_FONT, 11), command=choose).pack(side=tk.RIGHT, padx=8)
        refresh_media_lbl()

        def option_field(label, values, default):
            menu = ctk.CTkOptionMenu(field(scroll, label), values=values, width=250, height=28,
                                     corner_radius=6, fg_color=UI_FIELD, button_color=UI_HOVER,
                                     button_hover_color=UI_ACCENT_SOFT, text_color=UI_TEXT,
                                     dropdown_fg_color=UI_HEADER, dropdown_hover_color=UI_HOVER,
                                     dropdown_text_color=UI_TEXT)
            menu.pack(side=tk.RIGHT, padx=8, pady=3)
            menu.set(default)
            return menu

        engine_menu = option_field("Engine", ASR_ENGINES, "Bcut (Bilibili)")
        lang_menu = option_field("Language", ASR_LANGS, "Auto")
        format_menu = option_field("Subtitle file", ASR_FORMATS, "SRT")

        timeline_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(scroll, text="Place captions on the timeline", variable=timeline_var,
                        checkbox_width=18, checkbox_height=18, corner_radius=5, border_width=2,
                        fg_color=UI_ACCENT, hover_color=UI_ACCENT_SOFT, border_color=UI_BORDER,
                        text_color=UI_TEXT, font=(UI_FONT, 12)).pack(anchor="w", pady=(10, 6))

        note = ctk.CTkLabel(scroll, text="", anchor="w", justify=tk.LEFT, wraplength=380,
                            text_color=UI_DIM, font=(UI_FONT, 11))
        note.pack(fill=tk.X, pady=(2, 8))

        def show_note(*_a):
            engine = engine_menu.get()
            if engine == "Faster Whisper (local)":
                note.configure(text="Runs offline on CPU and is the best choice for Vietnamese "
                                    "and English. Needs the faster-whisper package.")
            elif engine == "JianYing (CapCut)":
                note.configure(text="CapCut cloud engine. Upload reaches the API but the task "
                                    "id often comes back empty, so expect a failure - use Bcut.")
            else:
                note.configure(text="Bilibili cloud engine: the audio track is uploaded for "
                                    "transcription. Strongest on Chinese; identical audio is cached, "
                                    "so retries are instant.")

        engine_menu.configure(command=show_note)
        show_note()

        progress = ctk.CTkProgressBar(body, height=6, corner_radius=3, fg_color=UI_BORDER,
                                      progress_color=UI_ACCENT, mode="determinate")
        progress.pack(fill=tk.X, padx=14, pady=(0, 4))
        progress.set(0)

        status = ctk.CTkLabel(body, text="Ready", anchor="w", text_color=UI_MUTED, font=(UI_FONT, 11))
        status.pack(fill=tk.X, padx=14, pady=(0, 8))

        def set_state(pct, text):
            try:
                progress.set(max(0.0, min(1.0, pct / 100.0)))
                status.configure(text=text)
            except tk.TclError:
                pass

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill=tk.X, padx=14, pady=(0, 14))

        def start():
            if state["busy"]:
                return
            media = state["media"]
            if not media or not os.path.exists(media):
                messagebox.showwarning("No media", "Choose a video or audio file first.", parent=dialog)
                return
            engine = engine_menu.get()
            lang = lang_menu.get()
            out_format = format_menu.get()
            to_timeline = bool(timeline_var.get())

            state["busy"] = True
            run_btn.configure(state="disabled", text="Transcribing...")
            set_state(2, "Preparing audio...")

            def report(pct, text):
                # Worker threads must not touch Tk widgets; hop back via after().
                try:
                    dialog.after(0, lambda p=pct, t=str(text): set_state(p, t))
                except tk.TclError:
                    pass

            def work():
                try:
                    segments = self._run_asr(media, engine, lang, report)
                    saved = self._asr_write(segments, media, out_format)
                    report(100, "%d caption lines written" % len(segments))
                    dialog.after(0, lambda: finish(True, segments, saved, to_timeline))
                except BaseException as exc:
                    dialog.after(0, lambda e=exc: finish(False, None, None, to_timeline, e))

            def finish(ok, segments, saved, to_timeline, error=None):
                state["busy"] = False
                try:
                    run_btn.configure(state="normal", text="Transcribe")
                except tk.TclError:
                    return
                if ok:
                    created = self._asr_clips(segments) if to_timeline else []
                    detail = "Captions: %d lines\nSaved: %s" % (len(segments), saved or "-")
                    if created:
                        detail += "\nAdded to the timeline text lane."
                    messagebox.showinfo("Auto Captions", detail, parent=dialog)
                    self.set_status("Auto captions: %d lines from %s" % (len(segments),
                                                                        os.path.basename(media)))
                else:
                    message = str(error) if error is not None else "Unknown error"
                    if error is not None and not message:
                        message = error.__class__.__name__
                    set_state(0, "Failed")
                    messagebox.showerror("Auto Captions failed", message, parent=dialog)

            import threading
            threading.Thread(target=work, daemon=True).start()

        run_btn = ctk.CTkButton(buttons, text="Transcribe", height=38, corner_radius=8,
                                fg_color=UI_ACCENT, hover_color=UI_ACCENT_SOFT, text_color="#06212A",
                                font=(UI_FONT, 13, "bold"), command=start)
        run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ctk.CTkButton(buttons, text="Close", width=88, height=38, corner_radius=8, fg_color=UI_FIELD,
                      hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER, text_color=UI_TEXT,
                      font=(UI_FONT, 12), command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

    def _run_asr(self, media_path, engine, lang_name, report):
        """Transcribe one file -> list of {text, start_ms, end_ms} dicts."""
        asr = asr_module()
        language = ASR_LANG_CODES.get(lang_name)
        try:
            audio_path, _tmp = asr_audio_for_upload(media_path)
        except RuntimeError:
            if engine != "Faster Whisper (local)":
                raise
            # faster-whisper decodes containers itself, so ffmpeg is optional here
            audio_path = media_path
        if engine == "Faster Whisper (local)":
            try:
                return asr_local_segments(audio_path, language, report)
            except ImportError:
                raise RuntimeError("The local engine needs the faster-whisper package:"
                                   "\n\npip install faster-whisper")
        cls = asr.engine_class(engine)
        report(12, "Uploading audio to %s..." % engine)
        try:
            data = cls(audio_path, use_cache=True).run()
        except Exception as exc:
            raise RuntimeError("%s could not transcribe this file: %s"
                               "\n\nTry Bcut (Bilibili) or the local engine."
                               % (engine, exc or exc.__class__.__name__)) from exc
        report(88, "Reading transcript...")
        segments = asr.to_segments(data)
        if not segments:
            raise RuntimeError("%s returned no speech. Try another engine or check the audio track."
                               % engine)
        return segments

    def _asr_write(self, segments, media_path, out_format):
        if not segments:
            raise RuntimeError("No speech was recognised in this file.")
        asr = asr_module()
        data = asr.ASRData([asr.ASRDataSeg(s["text"], s["start_ms"], s["end_ms"]) for s in segments])
        stem = os.path.splitext(media_path)[0]
        out_path = stem + "." + out_format.lower()
        try:
            asr_data_to_file(data, out_path)
        except OSError:
            out_path = os.path.join(OUTPUT_DIR, os.path.basename(stem) + "." + out_format.lower())
            asr_data_to_file(data, out_path)
        return out_path

    def _asr_clips(self, segments):
        """Put each transcript line on the timeline text lane as an editable clip."""
        created = []
        for seg in segments:
            start = max(0.0, seg["start_ms"] / 1000.0)
            duration = max(0.4, (seg["end_ms"] - seg["start_ms"]) / 1000.0)
            clip = TimelineClip("", start, duration, "text", self.ASR_TRACK)
            clip.text_content = seg["text"]
            clip.font = "Arial"
            clip.font_size = self.ASR_CAPTION_SIZE
            clip.text_color = "#FFFFFF"
            clip.bg_color = "#000000"
            clip.x_pos = 320
            clip.y_pos = self.ASR_CAPTION_Y
            self.timeline_clips.append(clip)
            created.append(clip)
        try:
            self.draw_timeline_clips()
        except Exception as exc:
            print("Timeline redraw after captions failed: %s" % exc)
        if created and hasattr(self, "draw_preview_frame"):
            try:
                self.draw_preview_frame(int(created[0].start_time * 30))
            except Exception:
                pass
        self.set_status("%d caption clips on the text lane" % len(created))
        return created

    def _import_subtitles(self):
        path = filedialog.askopenfilename(
            title="Import subtitles",
            filetypes=[("Subtitles", "*.srt *.ass *.ssa *.vtt *.json")])
        if not path:
            return
        try:
            asr = asr_module()
            data = asr.from_subtitle_file(path)
            segments = asr.to_segments(data)
        except Exception as exc:
            messagebox.showerror("Import Subtitles", "Could not read this subtitle file:\n%s" % exc)
            return
        if not segments:
            messagebox.showwarning("Import Subtitles", "No caption lines found in\n" + path)
            return
        self._asr_clips(segments)
        messagebox.showinfo("Import Subtitles",
                            "%d lines from %s\n\nThey are on the timeline text lane, ready to edit."
                            % (len(segments), os.path.basename(path)))

    def _add_default_text(self):
        # Determine start time (at playhead or end of track)
        playhead_time = getattr(self, 'current_frame', 0) / 30.0 if hasattr(self, 'current_frame') else 0
        
        text_clip = TimelineClip(
            "",
            playhead_time,
            5,
            "text",
            1 # Track 1 for text
        )
        text_clip.text_content = "Văn bản mặc định"
        text_clip.font = "Arial"
        text_clip.font_size = 60
        text_clip.text_color = "white"
        text_clip.bg_color = "transparent"
        text_clip.x_pos = 320
        text_clip.y_pos = 180
        
        self.timeline_clips.append(text_clip)
        self.selected_clips = [text_clip]
        self._selected_clip = text_clip # For properties
        
        self.draw_timeline_clips()
        self.update_properties_panel()
        
        # Trigger immediate preview
        if hasattr(self, 'draw_preview_frame'):
            self.draw_preview_frame(int(playhead_time * 30))
        
        print(f"Added text clip at {playhead_time}s")
    
    def _add_text_template(self, name, bg_color, text_color, font_size):
        playhead_time = getattr(self, 'current_frame', 0) / 30.0 if hasattr(self, 'current_frame') else 0
        
        text_clip = TimelineClip(
            "",
            playhead_time,
            5,
            "text",
            1
        )
        text_clip.text_content = name
        text_clip.font = "Arial"
        text_clip.font_size = font_size
        text_clip.text_color = text_color
        text_clip.bg_color = bg_color
        text_clip.x_pos = 320
        text_clip.y_pos = 180
        
        self.timeline_clips.append(text_clip)
        self.selected_clips = [text_clip]
        self._selected_clip = text_clip
        
        self.draw_timeline_clips()
        self.update_properties_panel()
        
        if hasattr(self, 'draw_preview_frame'):
            self.draw_preview_frame(int(playhead_time * 30))
    
    def _show_tts_dialog(self):
        dialog = ctk.CTkToplevel()
        dialog.title("Text to Speech")
        dialog.geometry("400x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=380, height=380, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        ctk.CTkLabel(content, text="Text to Speech", font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Nhập văn bản:", text_color="white").pack(pady=5, anchor="w")
        text_entry = ctk.CTkTextbox(content, height=80, fg_color="#2B2B2B", border_width=0)
        text_entry.pack(fill=tk.X, pady=5)
        text_entry.insert("1.0", "Nhập văn bản cần chuyển thành giọng nói...")
        
        ctk.CTkLabel(content, text="Chọn giọng:", text_color="white").pack(pady=(15, 5), anchor="w")
        
        voice_var = ctk.StringVar(value="vi")
        voices = [
            ("vi", "Tiếng Việt"),
            ("en", "English"),
            ("zh-CN", "中文"),
            ("ja", "日本語"),
            ("ko", "한국어"),
        ]
        for val, name in voices:
            ctk.CTkRadioButton(content, text=name, variable=voice_var, value=val).pack(anchor="w", pady=2)
        
        ctk.CTkLabel(content, text="Tốc độ:", text_color="white").pack(pady=(15, 5), anchor="w")
        speed_var = ctk.StringVar(value="1.0")
        for speed in ["0.5", "0.75", "1.0", "1.25", "1.5"]:
            ctk.CTkRadioButton(content, text=f"{speed}x", variable=speed_var, value=speed).pack(side=tk.LEFT, padx=5)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_tts():
            text = text_entry.get("1.0", tk.END).strip()
            if not text or text == "Nhập văn bản cần chuyển thành giọng nói...":
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập văn bản")
                return
            
            try:
                from gtts import gTTS
                import tempfile
                import platform
                
                lang_code = voice_var.get()
                speed_val = float(speed_var.get())
                
                status_lbl = ctk.CTkLabel(content, text="Đang tạo âm thanh...", text_color="#00E5FF")
                status_lbl.pack(pady=10)
                dialog.update()
                
                tts = gTTS(text=text, lang=lang_code, slow=(speed_val < 0.8))
                
                temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                temp_file.close()
                tts.save(temp_file.name)
                
                try:
                    import playsound
                    playsound.playsound(temp_file.name)
                    messagebox.showinfo("Thành công", "Đã phát âm thanh!")
                except Exception as e:
                    messagebox.showwarning("Phát thất bại", f"Không thể phát âm thanh:\n{str(e)}\n\nĐã lưu tại:\n{temp_file.name}")
                
            except ImportError:
                messagebox.showwarning("Thiếu thư viện", "Cần cài đặt gTTS:\n\npip install gTTS")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể tạo âm thanh:\n{str(e)}")
            
            try:
                os.unlink(temp_file.name)
            except:
                pass
        
        ctk.CTkButton(btn_frame, text="Tạo âm thanh", fg_color="#9C27B0", text_color="white", width=120, command=do_tts).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#666", text_color="white", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _render_media_tab(self):
        root = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        root.pack(fill=tk.BOTH, expand=True, padx=self.PANEL_PAD, pady=(4, 6))

        # --- source sub-tabs -----------------------------------------------
        sub = ctk.CTkFrame(root, fg_color="transparent")
        sub.pack(fill=tk.X, pady=(6, 0))
        self._media_subtab = getattr(self, "_media_subtab", "Import")
        for name in self.MEDIA_SUBTABS:
            active = name == self._media_subtab
            cell = tk.Frame(sub, bg=UI_PANEL)
            cell.pack(side=tk.LEFT, padx=(0, 18))
            lbl = tk.Label(cell, text=name, bg=UI_PANEL, cursor="hand2", pady=6,
                           font=(UI_FONT, 12, "bold" if active else "normal"),
                           fg=UI_ACCENT if active else UI_MUTED)
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, n=name: self._set_media_subtab(n))
            tk.Frame(cell, height=2, bg=UI_ACCENT if active else UI_PANEL).pack(fill=tk.X)

        # --- drop / import zone --------------------------------------------
        zone = ctk.CTkFrame(root, fg_color=UI_FIELD, border_width=1,
                            border_color=UI_BORDER, corner_radius=10, height=156)
        zone.pack(fill=tk.X, pady=(10, 10))
        zone.pack_propagate(False)
        ctk.CTkLabel(zone, text="", image=ui_icon("image", 28, UI_DIM)).pack(pady=(18, 2))
        drop_lbl = ctk.CTkLabel(zone, text="Drag & drop media here",
                                text_color=UI_TEXT, font=(UI_FONT, 12))
        drop_lbl.pack()
        ctk.CTkLabel(zone, text="or", text_color=UI_MUTED, font=(UI_FONT, 11)).pack()
        split = ctk.CTkFrame(zone, fg_color=UI_ACCENT, corner_radius=8)
        split.pack(pady=(6, 14))
        ctk.CTkButton(split, text="Import Media", width=116, height=30, corner_radius=8,
                      fg_color="transparent", hover_color=UI_ACCENT_SOFT,
                      text_color="#04222A", font=(UI_FONT, 12, "bold"),
                      command=self.import_media).pack(side=tk.LEFT)
        ctk.CTkButton(split, text="", width=28, height=30, corner_radius=8,
                      fg_color="transparent", hover_color=UI_ACCENT_SOFT,
                      image=ui_icon("chevron_down", 13, "#04222A"),
                      command=self.import_media).pack(side=tk.LEFT)
        for widget in (zone, drop_lbl):
            widget.bind("<Button-1>", lambda e: self.import_media())

        # --- filter chips, sort and search ---------------------------------
        bar = ctk.CTkFrame(root, fg_color="transparent")
        bar.pack(fill=tk.X, pady=(0, 6))
        self._media_chip_btns = {}
        for name in self.MEDIA_FILTERS:
            chip = ctk.CTkButton(bar, text=name, height=24, width=46, corner_radius=12,
                                 font=(UI_FONT, 11),
                                 fg_color=UI_HEADER if name == self.active_tab else "transparent",
                                 text_color=UI_TEXT if name == self.active_tab else UI_MUTED,
                                 hover_color=UI_HOVER,
                                 command=lambda n=name: self.switch_tab(n))
            chip.pack(side=tk.LEFT, padx=(0, 3))
            self._media_chip_btns[name] = chip

        self._media_search = getattr(self, "_media_search", "")
        entry = ctk.CTkEntry(bar, width=96, height=24, corner_radius=12, fg_color=UI_FIELD,
                             border_width=0, text_color=UI_TEXT, placeholder_text="Search",
                             font=(UI_FONT, 11))
        entry.pack(side=tk.RIGHT)
        entry.insert(0, self._media_search)
        entry.bind("<KeyRelease>", self._on_media_search)
        self._icon_btn(bar, "search", lambda: entry.focus_set(), px=14, size=22).pack(
            side=tk.RIGHT, padx=4)

        sort_row = ctk.CTkFrame(bar, fg_color="transparent")
        sort_row.pack(side=tk.RIGHT, padx=6)
        ctk.CTkLabel(sort_row, text="Sort", text_color=UI_DIM, font=(UI_FONT, 11)).pack(side=tk.LEFT)
        ctk.CTkOptionMenu(sort_row, values=list(self.MEDIA_SORTS), width=86, height=22,
                          corner_radius=11, fg_color=UI_FIELD, button_color=UI_HEADER,
                          button_hover_color=UI_HOVER, dropdown_fg_color=UI_HEADER,
                          text_color=UI_TEXT, font=(UI_FONT, 11),
                          command=self._set_media_sort).pack(side=tk.LEFT, padx=(4, 0))

        # --- thumbnail grid -------------------------------------------------
        self.thumb_grid_container = ctk.CTkScrollableFrame(
            root, fg_color="transparent", scrollbar_button_color=UI_HOVER,
            scrollbar_button_hover_color=UI_BORDER)
        self.thumb_grid_container.pack(fill=tk.BOTH, expand=True)
        self.thumb_grid = ctk.CTkFrame(self.thumb_grid_container, fg_color="transparent")
        self.thumb_grid.pack(fill=tk.BOTH, expand=True)
        self._media_durations = getattr(self, "_media_durations", {})
        self.refresh_thumbnails()
        if not getattr(self, "_probing", False):
            self.root.after(150, self._probe_media_durations)

    def _on_media_search(self, event=None):
        self._media_search = event.widget.get().strip().lower()
        self.refresh_thumbnails()

    def _set_media_subtab(self, name):
        if name == getattr(self, "_media_subtab", None):
            return
        self._media_subtab = name
        self._render_media_tab()

    def _set_media_sort(self, value):
        self._media_sort = value
        self.refresh_thumbnails()

    def _media_display_order(self):
        files = self.media_files
        mode = getattr(self, "_media_sort", "Date Added")
        if mode == "Name":
            order = sorted(range(len(files)), key=lambda i: os.path.basename(files[i]).lower())
        elif mode == "Duration":
            dur = getattr(self, "_media_durations", {})
            order = sorted(range(len(files)), key=lambda i: -dur.get(files[i], 0.0))
        else:
            order = list(range(len(files)))[::-1]
        query = getattr(self, "_media_search", "")
        if query:
            order = [i for i in order if query in os.path.basename(files[i]).lower()]
        return order

    def _probe_media_durations(self):
        # Fill the duration badges one file per idle tick; probing the whole
        # library up front would freeze the window on first paint.
        cache = getattr(self, "_media_durations", {})
        pending = [(f, t) for f, t in zip(self.media_files, self.media_types) if f not in cache]
        if not pending:
            self._probing = False
            return
        self._probing = True
        path, mtype = pending[0]
        try:
            cache[path] = float(self.get_media_duration(path, mtype) or 0.0)
        except Exception:
            cache[path] = 0.0
        if getattr(self, "_active_asset_tab", "") == "Media":
            self.refresh_thumbnails()
        self.root.after(60, self._probe_media_durations)
    
    def _render_audio_tab(self):
        container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        ctk.CTkLabel(container, text="🎵 Audio Library", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    def _render_transitions_tab(self):
        container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        ctk.CTkLabel(container, text="🔀 Transitions", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    def _render_effects_tab(self):
        container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        ctk.CTkLabel(container, text="✨ Effects", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    def _render_stickers_tab(self):
        container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        ctk.CTkLabel(container, text="😎 Stickers", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    def _render_filters_tab(self):
        container = ctk.CTkFrame(self.assets_dynamic_area, fg_color="transparent")
        container.pack(fill=tk.BOTH, expand=True)
        ctk.CTkLabel(container, text="🎬 Filters", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
        
        
    def create_preview_panel(self, parent):
        center_panel = ctk.CTkFrame(parent, fg_color=UI_PANEL, corner_radius=8)
        center_panel.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # --- header --------------------------------------------------------
        header = ctk.CTkFrame(center_panel, fg_color="transparent", height=36)
        header.pack(fill=tk.X, padx=self.PANEL_PAD, pady=(6, 0))
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="Player", font=(UI_FONT, 14, "bold"),
                     text_color=UI_TEXT).pack(side=tk.LEFT)

        self.aspect_ratio = "Fit"
        ctk.CTkOptionMenu(header, values=["Fit", "16:9", "3:2", "4:3", "1:1", "9:16", "21:9"],
                          width=74, height=26, corner_radius=6, fg_color=UI_FIELD,
                          button_color=UI_HEADER, button_hover_color=UI_HOVER,
                          dropdown_fg_color=UI_HEADER, text_color=UI_MUTED,
                          font=(UI_FONT, 11), command=self.change_aspect_ratio).pack(
            side=tk.LEFT, padx=(12, 0))

        tail = ctk.CTkFrame(header, fg_color="transparent")
        tail.pack(side=tk.RIGHT)
        self._icon_btn(tail, "camera", self._snapshot_frame, px=16, size=28,
                       tip="Save the current frame as PNG").pack(side=tk.RIGHT, padx=1)
        self._icon_btn(tail, "settings",
                       lambda: self._toast("Player settings are not wired up yet."),
                       px=16, size=28).pack(side=tk.RIGHT, padx=1)
        ctk.CTkOptionMenu(tail, values=["Full Quality", "Draft 720p", "Draft 480p"],
                          width=104, height=26, corner_radius=6, fg_color=UI_FIELD,
                          button_color=UI_HEADER, button_hover_color=UI_HOVER,
                          dropdown_fg_color=UI_HEADER, text_color=UI_MUTED,
                          font=(UI_FONT, 11)).pack(side=tk.RIGHT, padx=(0, 8))

        # --- canvas --------------------------------------------------------
        self.canvas_container = ctk.CTkFrame(center_panel, fg_color="#000000", corner_radius=0)
        self.canvas_container.pack(fill=tk.BOTH, expand=True, padx=self.PANEL_PAD, pady=6)

        self.preview_canvas = tk.Canvas(self.canvas_container, bg="#000000", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.create_text(320, 180, text="No media loaded", fill="#555",
                                        font=(UI_FONT, 16))

        self._drag_state = {"active": False, "clip": None, "item_id": None}
        self._drag_handle_ids = []

        self.preview_canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        self._canvas_click_handler = None

        def on_canvas_click(event):
            x, y = event.x, event.y
            for clip in self.timeline_clips:
                if clip.clip_type == 'text':
                    cx, cy = getattr(clip, 'x_pos', 320), getattr(clip, 'y_pos', 180)
                    if abs(x - cx) < 100 and abs(y - cy) < 30:
                        self._select_clip_for_edit(clip)
                        return
            self._selected_clip = None
            self._update_props_for_clip()

        self.preview_canvas.bind("<Double-Button-1>", on_canvas_click)

        # --- seek bar ------------------------------------------------------
        self.timeline_slider = ctk.CTkSlider(center_panel, from_=0, to=100, height=10,
                                             fg_color=UI_FIELD, progress_color=UI_ACCENT,
                                             button_color=UI_ACCENT, button_hover_color=UI_ACCENT_SOFT,
                                             command=self.on_slider_move)
        self.timeline_slider.pack(fill=tk.X, side=tk.BOTTOM, padx=self.PANEL_PAD, pady=(0, 2))

        # --- transport -----------------------------------------------------
        controls = ctk.CTkFrame(center_panel, fg_color="transparent", height=42)
        controls.pack(fill=tk.X, side=tk.BOTTOM, pady=(0, 6))

        self.time_label = ctk.CTkLabel(controls, text="00:00:00:00 / 00:00:00:00",
                                       text_color=UI_MUTED, font=(UI_FONT, 11))
        self.time_label.pack(side=tk.LEFT, padx=(2, 0))

        right_ctrls = ctk.CTkFrame(controls, fg_color="transparent")
        right_ctrls.pack(side=tk.RIGHT)
        for glyph, tip in (("fit_width", "Fit to width"), ("frame_fill", "Fill frame"),
                           ("crop", "Crop"), ("frame", "Original size")):
            self._icon_btn(right_ctrls, glyph,
                           lambda g=glyph: self._toast("%s preview is not wired up yet." % tip),
                           px=15, size=26, tip=tip).pack(side=tk.LEFT, padx=1)

        btn_frame = ctk.CTkFrame(controls, fg_color="transparent")
        btn_frame.pack(side=tk.LEFT, expand=True)
        self._icon_btn(btn_frame, "skip_start", self._jump_start, px=15, size=30).pack(side=tk.LEFT, padx=1)
        self._icon_btn(btn_frame, "step_prev", self.prev_frame, px=15, size=30).pack(side=tk.LEFT, padx=1)
        self.play_btn = self._icon_btn(btn_frame, "play", self.play_video, px=18, size=34,
                                       color=UI_TEXT)
        self.play_btn.pack(side=tk.LEFT, padx=4)
        self._icon_btn(btn_frame, "step_next", self.next_frame, px=15, size=30).pack(side=tk.LEFT, padx=1)
        self._icon_btn(btn_frame, "skip_end", self._jump_end, px=15, size=30).pack(side=tk.LEFT, padx=1)

    def _jump_start(self):
        self.timeline_slider.set(0)
        self.on_slider_move(0)

    def _jump_end(self):
        val = int(self.timeline_slider.cget("to"))
        self.timeline_slider.set(val)
        self.on_slider_move(val)

    def _set_play_icon(self, playing):
        btn = getattr(self, "play_btn", None)
        if btn is not None:
            btn.configure(image=ui_icon("pause" if playing else "play", 18, UI_TEXT))

    def _snapshot_frame(self):
        frame = getattr(self, "_last_preview_pil", None)
        if frame is None:
            self._toast("Nothing to snapshot yet - load a clip first.")
            return
        from datetime import datetime
        out = os.path.join(OUTPUT_DIR, "frame_%s.png" % datetime.now().strftime("%y%m%d-%H%M%S"))
        try:
            frame.save(out)
            self._toast("Snapshot saved: %s" % os.path.basename(out))
        except Exception as exc:
            self._toast("Snapshot failed: %s" % exc)

        
    def create_properties_panel(self, parent):
        self.right_panel = ctk.CTkFrame(parent, fg_color=UI_PANEL, width=self.PROPS_W, corner_radius=0)
        self.right_panel.pack(fill=tk.BOTH, expand=True)

        head = ctk.CTkFrame(self.right_panel, fg_color="transparent", height=40)
        head.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(2, 0))
        head.pack_propagate(False)

        self.toggle_right_btn = self._icon_btn(head, "panel_right", self.toggle_properties_panel,
                                               px=17, size=28, tip="Collapse panel")
        self.toggle_right_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.props_tabs_frame = ctk.CTkFrame(head, fg_color="transparent")
        self.props_tabs_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Frame(self.right_panel, height=1, bg=UI_BORDER).pack(fill=tk.X, padx=self.PROPS_PAD)

        self.props_sub_tabs = ctk.CTkFrame(self.right_panel, fg_color=UI_FIELD, corner_radius=8, height=36)
        self.props_sub_tabs.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(10, 4))

        # Scrollable frame for properties content
        self.props_scrollable = ctk.CTkScrollableFrame(self.right_panel, fg_color="transparent",
                                                      scrollbar_button_color=UI_BORDER,
                                                      scrollbar_button_hover_color=UI_HOVER)
        self.props_scrollable.pack(fill=tk.BOTH, expand=True, padx=(0, 2))

        self.props_content = self.props_scrollable
        self.update_properties_panel()


    def _sync_sub_tabs_slot(self):
        # Keep the chip row's slot but collapse it when a panel has no sub-tabs;
        # re-packing the container would move it below the scrollable body.
        empty = not self.props_sub_tabs.winfo_children()
        self.props_sub_tabs.configure(fg_color="transparent" if empty else UI_FIELD,
                                      height=1 if empty else 36)

    def update_properties_panel(self):
        try:
            self._render_properties_panel()
        finally:
            self._sync_sub_tabs_slot()

    def _render_properties_panel(self):
        for w in self.props_tabs_frame.winfo_children():
            if w != getattr(self, "toggle_right_btn", None): w.destroy()
        for w in self.props_sub_tabs.winfo_children(): w.destroy()
        for w in self.props_content.winfo_children(): w.destroy()
        
        clip = getattr(self, '_selected_clip', None)
        if clip and clip.clip_type == 'text':
            self.render_text_properties(clip)
            return
        
        if not hasattr(self, 'selected_clips') or not self.selected_clips:
            ctk.CTkLabel(self.props_content, text="No selection", text_color=UI_DIM,
                         font=self.PROPS_FONT).pack(pady=24)
            return
            
        ctype = self.selected_clips[0].clip_type
        
        if ctype in ['video', 'image']:
            self.current_video_tab = "Video"
            self._render_video_tab_strip()
            self.render_video_tab_content()
            return
        
        if ctype == 'audio':
            self.current_audio_tab = "Basic"
            self._render_props_tabs(self.AUDIO_TABS, self.current_audio_tab,
                                    self.on_audio_tab_click)
            self.render_audio_basic_tab()
            return

        if ctype == 'text':
            self.current_text_tab = "Text"
            self._render_props_tabs(self.TEXT_TABS, self.current_text_tab,
                                    self.on_text_tab_click)
            self.render_text_tab()
            return

    VIDEO_TABS = ["Video", "Animation", "Tracking", "Adjust",
                  "Cut", "Motion", "Logo Removal", "AI Tools"]
    AUDIO_TABS = ["Basic", "Cut", "Speed"]
    TEXT_TABS = ["Text", "Animation", "Tracking", "TTS"]

    def _props_tabs_into(self, holder, tabs, active, handler):
        """Flat text tabs; the active one carries a 2px accent underline."""
        for column, tab in enumerate(tabs):
            is_active = tab == active
            cell = tk.Frame(holder, bg=UI_PANEL, cursor="hand2")
            cell.grid(row=0, column=column, sticky="n")
            label = tk.Label(cell, text=tab, bg=UI_PANEL, anchor="center",
                             fg=UI_ACCENT if is_active else UI_MUTED,
                             font=(UI_FONT, 11, "bold" if is_active else "normal"),
                             padx=7, pady=9)
            label.pack()
            tk.Frame(cell, height=2, bg=UI_ACCENT if is_active else UI_PANEL).pack(fill=tk.X)
            for widget in (cell, label):
                widget.bind("<Button-1>", lambda e, t=tab: handler(t))

    def _render_props_tabs(self, tabs, active, handler, scroll=False):
        for w in self.props_tabs_frame.winfo_children():
            w.destroy()

        if not scroll:
            holder = tk.Frame(self.props_tabs_frame, bg=UI_PANEL)
            holder.pack(side=tk.LEFT, fill=tk.X)
            self._props_tabs_into(holder, tabs, active, handler)
            return

        # Eight tabs never fit a ~360px panel, so the strip keeps natural label
        # widths and scrolls instead of dropping the overflow off the edge.
        canvas = tk.Canvas(self.props_tabs_frame, height=34, bg=UI_PANEL, highlightthickness=0)
        canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        holder = tk.Frame(canvas, bg=UI_PANEL)
        window = canvas.create_window((0, 0), window=holder, anchor="nw")
        def sync_region(*_):
            if not canvas.winfo_exists():
                return
            width = max(holder.winfo_reqwidth(), canvas.winfo_width())
            canvas.configure(scrollregion=(0, 0, width, 34))
            canvas.itemconfigure(window, width=width)
        canvas.bind("<Configure>", sync_region)
        holder.bind("<Configure>", sync_region)

        canvas.configure(xscrollincrement=30)
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
                    lambda ev: canvas.xview_scroll(int(-ev.delta / 120), "units")), add="+")
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"), add="+")

        # grid, not pack: pack unmaps the overflow tabs, which makes the strip
        # report a width that fits and silently swallow the rest.
        self._props_tabs_into(holder, tabs, active, handler)

        def reveal_active(attempts=0):
            if not canvas.winfo_exists() or active is None or attempts > 10:
                return
            total = max(1, holder.winfo_reqwidth())
            if total <= 1 or canvas.winfo_width() <= 1:
                canvas.after(80, lambda: reveal_active(attempts + 1))
                return
            sync_region()
            index = tabs.index(active) if active in tabs else 0
            # Requested widths, not winfo_x: the strip may not be laid out yet.
            # Back off slightly so the active tab never starts mid-glyph.
            offset = max(0, sum(b.winfo_reqwidth() for b in holder.winfo_children()[:index]) - 14)
            canvas.xview_moveto(max(0, min(offset, total - canvas.winfo_width())) / total)
        canvas.after(120, lambda: reveal_active(0))

    def _render_video_tab_strip(self):
        self._render_props_tabs(self.VIDEO_TABS, getattr(self, "current_video_tab", "Video"),
                                self.on_video_tab_click, scroll=True)

    def _render_video_placeholder(self, tab):
        box = ctk.CTkFrame(self.props_content, fg_color=UI_HEADER, corner_radius=8)
        box.pack(fill=tk.X, padx=self.PROPS_PAD, pady=16)
        ctk.CTkLabel(box, image=ui_icon("marker", 26, UI_DIM), text="").pack(pady=(18, 4))
        ctk.CTkLabel(box, text=tab, text_color=UI_TEXT,
                     font=self.PROPS_SECTION_FONT).pack()
        ctk.CTkLabel(box, text="No controls for this tab yet", text_color=UI_MUTED,
                     font=("Segoe UI", 11), wraplength=self._props_wrap()).pack(pady=(2, 18))

    def render_video_tab_content(self):
        for w in self.props_sub_tabs.winfo_children(): w.destroy()
        for w in self.props_content.winfo_children(): w.destroy()
        
        if not hasattr(self, 'selected_clips') or not self.selected_clips:
            return
            
        ctype = self.selected_clips[0].clip_type
        tab = getattr(self, 'current_video_tab', "Video")
        
        if ctype in ['video', 'image']:
            if tab == "Video":
                self.render_video_basic_tab()
            elif tab == "Cut":
                self.render_video_cut_tab()
            elif tab == "Logo Removal":
                self.render_remove_logo_tab()
            elif tab == "Motion":
                self.render_motion_graphics_tab()
            else:
                self._render_video_placeholder(tab)
        elif ctype == 'audio':
            self.render_audio_tab()
        elif ctype == 'text':
            self.render_text_tab()
        
        self._sync_sub_tabs_slot()
        
    def on_video_tab_click(self, tab_name):
        self.current_video_tab = tab_name
        self._render_video_tab_strip()
        self.render_video_tab_content()
    
    def on_audio_tab_click(self, tab_name):
        self.current_audio_tab = tab_name
        self._render_props_tabs(self.AUDIO_TABS, tab_name, self.on_audio_tab_click)
        for w in self.props_sub_tabs.winfo_children(): w.destroy()
        for w in self.props_content.winfo_children(): w.destroy()
        
        if self.current_audio_tab == "Basic":
            self.render_audio_basic_tab()
        elif self.current_audio_tab == "Cut":
            self.render_audio_cut_tab()
        elif self.current_audio_tab == "Speed":
            self.render_audio_speed_tab()
    
    def on_text_tab_click(self, tab_name):
        self.current_text_tab = tab_name
        self.update_properties_panel()
    
    def _props_audio_levels(self):
        for label, lo, hi, val, text in (("Volume", -60, 20, 0, "0.0 dB"),
                                         ("Fade in", 0, 10, 0, "0.0 s"),
                                         ("Fade out", 0, 10, 0, "0.0 s"),
                                         ("Balance", -100, 100, 0, "L+R")):
            row = self._props_row(label, pady=2)
            self._props_slider(row, lo, hi, val)
            self._props_value(row, text, stepper=False)

    def render_audio_basic_tab(self):
        self._props_section("Basic")
        self._props_audio_levels()
    
    def _props_section(self, title, reset=True):
        header = ctk.CTkFrame(self.props_content, fg_color=UI_HEADER, corner_radius=6, height=34)
        header.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(14, 2))
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=title, text_color=UI_TEXT,
                     font=self.PROPS_SECTION_FONT).pack(side=tk.LEFT, padx=(10, 0))
        if reset:
            ctk.CTkLabel(header, image=ui_icon("reset", 15, UI_DIM), text="").pack(side=tk.RIGHT, padx=(0, 9))
        return header

    def _props_wrap(self):
        # The sash sizes the properties column in device pixels while CTk scales
        # wraplength, so a constant tuned at 100% DPI clips mid-word when scaled.
        try:
            scaling = max(0.5, self.right_panel._apply_widget_scaling(100) / 100.0)
            device = self.right_panel.winfo_width() - 96
            return max(120, int(device / scaling)) if device >= 100 else 200
        except Exception:
            return 200

    def _props_group(self, text, dim=False):
        ctk.CTkLabel(self.props_content, text=text, anchor="w",
                     text_color=UI_DIM if dim else UI_MUTED,
                     font=(UI_FONT, 11)).pack(fill=tk.X, padx=self.PROPS_PAD + 2, pady=(9, 0))

    def _props_row(self, label=None, pady=4, label_w=None):
        row = ctk.CTkFrame(self.props_content, fg_color="transparent")
        row.pack(fill=tk.X, padx=self.PROPS_PAD, pady=pady)
        row.columnconfigure(1, weight=1)
        if label is not None:
            ctk.CTkLabel(row, text=label, text_color=UI_MUTED,
                         width=self.PROPS_LABEL_W if label_w is None else label_w, anchor="w",
                         font=self.PROPS_FONT).grid(row=0, column=0, sticky="w")
        return row

    def _props_box(self, parent, text, width=None, spinner=True):
        """Value read-out with a spinbox affordance."""
        box = ctk.CTkFrame(parent, fg_color=UI_FIELD, border_width=1, border_color=UI_BORDER,
                           corner_radius=5, width=self.PROPS_VALUE_W if width is None else width,
                           height=self.PROPS_ROW_H)
        box.pack_propagate(False)
        ctk.CTkLabel(box, text=text, text_color=UI_TEXT,
                     font=self.PROPS_FONT).pack(side=tk.LEFT, padx=(8, 0))
        if spinner:
            ctk.CTkLabel(box, image=ui_icon("spinner", 11, UI_DIM), text="").pack(side=tk.RIGHT, padx=(0, 5))
        return box

    def _props_value(self, row, text, stepper=True, column=2, sticky="e"):
        self._props_box(row, text, spinner=stepper).grid(
            row=0, column=column, sticky=sticky, padx=(8, 0) if sticky == "e" else (4, 8))

    def _props_keyframe(self, row):
        ctk.CTkLabel(row, image=ui_icon("keyframe", 13, UI_DIM), text=""
                     ).grid(row=0, column=3, sticky="e", padx=(7, 0))

    def _props_slider(self, row, from_, to, value):
        slider = ctk.CTkSlider(row, from_=from_, to=to, height=16, fg_color=UI_BORDER,
                               progress_color=UI_TEXT, button_color="#FFFFFF",
                               button_hover_color=UI_ACCENT)
        slider.set(value)
        slider.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        return slider

    def _props_field(self, parent, placeholder, width=54):
        return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, height=self.PROPS_ROW_H,
                            fg_color=UI_FIELD, border_width=1, border_color=UI_BORDER,
                            text_color=UI_TEXT, placeholder_text_color=UI_DIM, font=self.PROPS_FONT)

    def _props_dropdown(self, parent, text, values=None):
        menu = ctk.CTkOptionMenu(parent, values=values or [text], width=120, height=self.PROPS_ROW_H,
                                 corner_radius=5, fg_color=UI_FIELD, button_color=UI_HOVER,
                                 dropdown_fg_color=UI_HEADER, dropdown_hover_color=UI_HOVER,
                                 dropdown_text_color=UI_TEXT, text_color=UI_TEXT,
                                 font=self.PROPS_FONT, dynamic_resizing=False)
        menu.set(text)
        return menu

    def _props_toggle_row(self, label, on=False, strong=False):
        row = self._props_row()
        ctk.CTkLabel(row, text=label, text_color=UI_TEXT if strong else UI_MUTED, anchor="w",
                     font=self.PROPS_SECTION_FONT if strong else self.PROPS_FONT
                     ).grid(row=0, column=0, columnspan=3, sticky="w")
        switch = ctk.CTkSwitch(row, text="", width=42, height=22, button_color="#FFFFFF",
                               progress_color=UI_ACCENT_SOFT, fg_color=UI_BORDER)
        switch.grid(row=0, column=3, sticky="e")
        if on:
            switch.select()
        return row, switch

    def _props_sub_tabs(self, labels, active_index=0):
        self.props_sub_tabs.configure(fg_color=UI_FIELD, height=36)
        for index, text in enumerate(labels):
            is_active = index == active_index
            # Explicit width: CTkButton clips its own label when width=1 and pack
            # stretches the widget afterwards.
            ctk.CTkButton(self.props_sub_tabs, text=text, width=16 + 7 * len(text),
                          height=26, corner_radius=13,
                          fg_color=UI_ACCENT_BG if is_active else "transparent",
                          border_width=1 if is_active else 0, border_color=UI_ACCENT,
                          hover_color=UI_HOVER, text_color=UI_ACCENT if is_active else UI_MUTED,
                          font=("Segoe UI", 11, "bold" if is_active else "normal")
                          ).pack(side=tk.LEFT, padx=2, pady=5)

    def render_video_basic_tab(self):
        self._props_sub_tabs(["Basic", "Color", "Mask", "AI Tools"])

        self._props_section("Transform")

        self._props_group("Scale")
        for axis in ("X", "Y"):
            row = self._props_row(axis, label_w=16, pady=2)
            self._props_slider(row, 0, 200, 100)
            self._props_value(row, "100%")
            self._props_keyframe(row)
        self._props_toggle_row("Uniform scale", on=True)

        self._props_group("Position")
        pos_row = self._props_row(pady=2)
        for index, axis in enumerate(("X", "Y")):
            pos_row.grid_columnconfigure(index * 2 + 1, weight=1)
            ctk.CTkLabel(pos_row, text=axis, text_color=UI_MUTED, width=14, anchor="w",
                         font=self.PROPS_FONT).grid(row=0, column=index * 2, sticky="w")
            self._props_box(pos_row, "0.00").grid(row=0, column=index * 2 + 1, sticky="ew",
                                                  padx=(4, 8) if index == 0 else (4, 0))

        self._props_group("Rotate")
        rot_row = self._props_row(pady=2)
        rot_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(rot_row, image=ui_icon("dial", 22, UI_TEXT), text=""
                     ).grid(row=0, column=0, sticky="w", padx=(2, 8))
        self._props_box(rot_row, "0.00°").grid(row=0, column=1, columnspan=3, sticky="ew")

        self._props_group("Flip", dim=True)
        flip_row = self._props_row(pady=2)
        flip_row.grid_columnconfigure(0, weight=1)
        flip_bar = ctk.CTkFrame(flip_row, fg_color=UI_FIELD, corner_radius=6, height=32)
        flip_bar.grid(row=0, column=0, columnspan=4, sticky="ew", ipady=2)
        for glyph in ("flip_h", "flip_v", "rotate", "frame", "frame_fill"):
            self._icon_btn(flip_bar, glyph,
                           lambda: self._toast("Transform helpers are preview-only in this build"),
                           px=16, size=26, color=UI_MUTED).pack(side=tk.LEFT, expand=True)

        self._props_section("Compositing")

        self._props_group("Blend Mode")
        mode_row = self._props_row(pady=2)
        mode_row.grid_columnconfigure(0, weight=1)
        self._props_dropdown(mode_row, "Normal",
                             ["Normal", "Multiply", "Screen", "Overlay",
                              "Soft Light", "Hard Light", "Difference"]
                             ).grid(row=0, column=0, sticky="ew")

        self._props_group("Opacity")
        opacity_row = self._props_row(pady=2)
        self._props_slider(opacity_row, 0, 100, 100)
        self._props_value(opacity_row, "100%", stepper=False)
        self._props_keyframe(opacity_row)

        self._props_section("Background")

        self._props_group("Type")
        bg_row = self._props_row(pady=2)
        bg_row.grid_columnconfigure(0, weight=1)
        self._props_dropdown(bg_row, "Default", ["Default", "Solid", "Blur", "Mirror"]
                             ).grid(row=0, column=0, sticky="ew")
    
    def render_video_cut_tab(self):
        self._props_section("Split video into short clips", reset=False)
        
        clip = self.selected_clips[0]
        video_path = clip.file_path
        
        duration_sec = self.get_media_duration(video_path, clip.clip_type)
        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        
        info_frame = ctk.CTkFrame(self.props_content, fg_color=UI_HEADER, corner_radius=8)
        info_frame.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(6, 10))
        ctk.CTkLabel(info_frame, text=f"Duration: {mins}:{secs:02d}", text_color=UI_ACCENT,
                     font=self.PROPS_FONT).pack(pady=10)
        
        input_row = self._props_row("Segments")
        self.cut_segments_entry = self._props_field(input_row, "3", width=70)
        self.cut_segments_entry.grid(row=0, column=1, columnspan=2, sticky="w", padx=(4, 8))
        self.cut_segments_entry.insert("0", "3")
        
        ctk.CTkLabel(self.props_content, text="A 10 minute clip split into 3 gives three ~3 minute parts.",
                     text_color=UI_DIM, font=("Segoe UI", 10), justify=tk.LEFT, anchor="w",
                     wraplength=self._props_wrap()
                     ).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(0, 8))
        
        self.cut_status_label = ctk.CTkLabel(self.props_content, text="", text_color=UI_MUTED, font=("Segoe UI", 10))
        self.cut_status_label.pack(fill=tk.X, padx=self.PROPS_PAD, pady=2)
        
        self.cut_progress = ctk.CTkProgressBar(self.props_content, orientation="horizontal", mode="determinate",
                                               progress_color=UI_ACCENT, fg_color=UI_BORDER)
        self.cut_progress.set(0)
        self.cut_progress.pack(fill=tk.X, padx=self.PROPS_PAD, pady=6)
        
        btn_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        btn_frame.pack(fill=tk.X, padx=self.PROPS_PAD, pady=8)
        
        self.cut_start_btn = ctk.CTkButton(btn_frame, text="Split", fg_color=UI_ACCENT_SOFT, text_color="#04252A", height=34, corner_radius=8, font=("Segoe UI", 12, "bold"), command=self.start_video_cut)
        self.cut_start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        self.cut_cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", fg_color="#7A2430", text_color=UI_TEXT, height=34, corner_radius=8, font=("Segoe UI", 12, "bold"), command=self.cancel_video_cut, state="disabled")
        self.cut_cancel_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        
        self.cutting = False
        self.cancel_cut = False
    
    def render_motion_graphics_tab(self):
        self._props_section("Motion", reset=False)
        
        clips = self._motion_targets()
        current = clips[0].motion_effect if clips else "none"
        intensity = int(clips[0].motion_intensity) if clips else 5
        
        ctk.CTkLabel(self.props_content, text="Animate the selected clip; the player and the "
                     "export use the same frames",
                     text_color=UI_DIM, font=("Segoe UI", 10), justify=tk.LEFT, anchor="w",
                     wraplength=self._props_wrap()
                     ).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(0, 6))
        
        self._motion_effect_type = ctk.StringVar(value=current)
        
        effects_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        effects_frame.pack(fill=tk.X, pady=6, padx=(4, self.PROPS_PAD))
        
        for effect_key, effect_name, effect_desc in ANIM.MOTION_EFFECTS:
            item_frame = ctk.CTkFrame(effects_frame, fg_color=UI_HEADER, corner_radius=8)
            item_frame.pack(fill=tk.X, pady=3, padx=4)
            ctk.CTkRadioButton(item_frame, text=effect_name, variable=self._motion_effect_type,
                               value=effect_key, font=("Segoe UI", 11, "bold"),
                               text_color=UI_TEXT, fg_color=UI_ACCENT, border_color=UI_DIM,
                               hover_color=UI_ACCENT_SOFT, command=self._on_motion_choice
                               ).pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(item_frame, text=effect_desc, text_color=UI_MUTED,
                         font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(0, 8))
        
        intensity_row = self._props_row("Intensity")
        self._motion_intensity = ctk.CTkSlider(intensity_row, from_=1, to=10, height=16,
                                               fg_color=UI_BORDER, progress_color=UI_TEXT,
                                               button_color="#FFFFFF",
                                               button_hover_color=UI_ACCENT,
                                               command=self._on_motion_intensity)
        self._motion_intensity.set(intensity)
        self._motion_intensity.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self._motion_intensity_label = ctk.CTkLabel(intensity_row, text=str(intensity),
                                                    text_color=UI_TEXT,
                                                    width=self.PROPS_VALUE_W, anchor="e",
                                                    font=self.PROPS_FONT)
        self._motion_intensity_label.grid(row=0, column=2, sticky="e")
        
        action_row = ctk.CTkFrame(self.props_content, fg_color="transparent")
        action_row.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(8, 16))
        
        ctk.CTkButton(action_row, text="Preview", fg_color=UI_FIELD, hover_color=UI_HOVER,
                      border_width=1, border_color=UI_BORDER, text_color=UI_TEXT,
                      height=34, corner_radius=8, font=("Segoe UI", 11, "bold"),
                      command=self._preview_motion_effect
                      ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        ctk.CTkButton(action_row, text="Apply", fg_color=UI_ACCENT_SOFT, text_color="#04252A",
                      height=34, corner_radius=8, font=("Segoe UI", 11, "bold"),
                      command=self._apply_motion_effect
                      ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        ctk.CTkButton(action_row, text="Render file", fg_color=UI_FIELD, hover_color=UI_HOVER,
                      border_width=1, border_color=UI_BORDER, text_color=UI_TEXT,
                      height=34, corner_radius=8, font=("Segoe UI", 11, "bold"),
                      command=self._render_motion_file
                      ).pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    def _motion_targets(self):
        clips = getattr(self, "selected_clips", None) or []
        return [c for c in clips if c.clip_type in ("video", "image")]
    
    def _seek_to_frame(self, frame_num):
        frame_num = max(0, int(frame_num))
        self.timeline_slider.set(frame_num)
        self.current_frame = frame_num
        self.playhead_x = 100 + frame_num
        self.draw_playhead()
        self.draw_preview_frame(frame_num)
    
    def _on_motion_choice(self):
        targets = self._motion_targets()
        if not targets:
            self.set_status("Select a clip on the timeline to animate")
            return
        effect = self._motion_effect_type.get()
        intensity = int(self._motion_intensity.get())
        for clip in targets:
            clip.motion_effect = effect
            clip.motion_intensity = intensity
        self._seek_to_frame(int(targets[0].start_time * 30))
        self.set_status("Motion: %s (%d) on %d clip(s)"
                        % (ANIM.label(ANIM.MOTION_EFFECTS, effect), intensity, len(targets)))
    
    def _on_motion_intensity(self, value):
        intensity = int(value)
        if hasattr(self, "_motion_intensity_label"):
            self._motion_intensity_label.configure(text=str(intensity))
        for clip in self._motion_targets():
            clip.motion_intensity = intensity
        self.draw_preview_frame(int(self.current_frame))
    
    def _preview_motion_effect(self):
        targets = self._motion_targets()
        if not targets:
            messagebox.showwarning("Motion", "Select a clip on the timeline first")
            return
        self._on_motion_choice()
        clip = targets[0]
        if self.is_playing:
            self.play_video()
        self._seek_to_frame(int(clip.start_time * 30))
        self.play_video()
        self.root.after(max(400, int(clip.duration * 1000)), self._stop_motion_preview)
    
    def _stop_motion_preview(self):
        if getattr(self, "is_playing", False):
            self.play_video()
    
    def _apply_motion_effect(self):
        targets = self._motion_targets()
        if not targets:
            messagebox.showwarning("Motion", "Select a clip on the timeline first")
            return
        effect = self._motion_effect_type.get()
        intensity = int(self._motion_intensity.get())
        for clip in targets:
            clip.motion_effect = effect
            clip.motion_intensity = intensity
        self.draw_preview_frame(int(self.current_frame))
        name = ANIM.label(ANIM.MOTION_EFFECTS, effect)
        self.set_status("Motion %s (%d) kept on %d clip(s) - rendered on export"
                        % (name, intensity, len(targets)))
        self._toast("%s applied to %d clip(s)" % (name, len(targets)))
    
    def _render_motion_file(self):
        targets = self._motion_targets()
        if not targets:
            messagebox.showwarning("Motion", "Select a clip on the timeline first")
            return
        clip = targets[0]
        if clip.motion_effect == "none":
            messagebox.showinfo("Motion", "Pick an effect before rendering a file")
            return
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(clip.file_path))[0]
        out_path = os.path.join(out_dir, "%s_motion_%s.mp4" % (stem, clip.motion_effect))
        self._render_clips_to_file([clip], out_path)
    
    def render_remove_logo_tab(self):
        self._props_section("Logo / watermark removal", reset=False)
        
        clip = self.selected_clips[0]
        video_path = clip.file_path
        
        info_text = ("Pick the area holding the logo on the player:\n"
                     "1. Start select   2. Drag a box on the player\\n"
                     "3. Choose a method   4. Apply")
        ctk.CTkLabel(self.props_content, text=info_text, text_color=UI_DIM, font=("Segoe UI", 10),
                     justify=tk.LEFT, anchor="w", wraplength=self._props_wrap()
                     ).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(0, 8))
        
        self._roi_selection_mode = False
        self._roi_start = None
        self._roi_end = None
        self._roi_rect_id = None
        
        btn_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        btn_frame.pack(pady=6, fill=tk.X, padx=self.PROPS_PAD)
        
        self._select_roi_btn = ctk.CTkButton(btn_frame, text="Start select", fg_color=UI_ACCENT_SOFT, text_color="#04252A", height=34, corner_radius=8, font=("Segoe UI", 11, "bold"), command=self._toggle_roi_selection)
        self._select_roi_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        self._clear_roi_btn = ctk.CTkButton(btn_frame, text="Clear area", fg_color=UI_FIELD, hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER, text_color=UI_TEXT, height=34, corner_radius=8, font=("Segoe UI", 11, "bold"), command=self._clear_roi_selection, state="disabled")
        self._clear_roi_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        
        ctk.CTkLabel(self.props_content, text="Selected area", text_color=UI_MUTED, anchor="w",
                     font=self.PROPS_FONT).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(8, 2))
        
        self._roi_info_frame = ctk.CTkFrame(self.props_content, fg_color=UI_HEADER, corner_radius=8)
        self._roi_info_frame.pack(fill=tk.X, padx=self.PROPS_PAD, pady=4)
        
        self._roi_coords_label = ctk.CTkLabel(self._roi_info_frame, text="No area selected", text_color=UI_DIM, font=("Segoe UI", 10))
        self._roi_coords_label.pack(pady=10)
        
        self._props_section("Removal method", reset=False)
        
        self._remove_method_var = ctk.StringVar(value="blur")
        
        methods_info = [
            ("blur", "1. Blur / Mosaic", "Fast, leaves a soft smudge"),
            ("ai", "2. AI Smart Inpaint", "Rebuilds the content, slow"),
            ("crop", "3. Crop frame", "Thorough, loses the video edge"),
            ("overlay", "4. Overlay", "Cover the logo with image/text")
        ]
        
        for method_key, method_name, method_desc in methods_info:
            m_frame = ctk.CTkFrame(self.props_content, fg_color=UI_HEADER, corner_radius=8)
            m_frame.pack(fill=tk.X, pady=4, padx=self.PROPS_PAD)
            
            ctk.CTkRadioButton(m_frame, text=method_name, variable=self._remove_method_var, value=method_key,
                               font=("Segoe UI", 11, "bold"), text_color=UI_TEXT,
                               fg_color=UI_ACCENT, border_color=UI_DIM, hover_color=UI_ACCENT_SOFT,
                               command=self._update_method_options).pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(m_frame, text=method_desc, text_color=UI_MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(0, 8))
        
        self._method_options_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        self._method_options_frame.pack(pady=6, fill=tk.X, padx=self.PROPS_PAD)
        self._update_method_options()
        
        apply_btn_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        apply_btn_frame.pack(pady=12, fill=tk.X, padx=self.PROPS_PAD)
        
        self._apply_remove_logo_btn = ctk.CTkButton(apply_btn_frame, text="Apply", fg_color=UI_ACCENT_SOFT, text_color="#04252A", height=34, corner_radius=8, font=("Segoe UI", 11, "bold"), command=self._apply_remove_logo_from_panel, state="disabled")
        self._apply_remove_logo_btn.pack(fill=tk.X)
    
    def _update_method_options(self):
        for w in self._method_options_frame.winfo_children():
            w.destroy()
        
        method = self._remove_method_var.get()
        
        if method == "blur":
            ctk.CTkLabel(self._method_options_frame, text="Blur strength:", text_color=UI_TEXT, font=("Segoe UI", 10)).pack(pady=(5, 2), anchor="w")
            blur_frame = ctk.CTkFrame(self._method_options_frame, fg_color="transparent")
            blur_frame.pack(pady=5)
            self._blur_radius_slider = ctk.CTkSlider(blur_frame, from_=5, to=50, width=200, fg_color=UI_BORDER, progress_color=UI_ACCENT, button_color="#FFFFFF")
            self._blur_radius_slider.set(25)
            self._blur_radius_slider.pack(pady=5)
            self._blur_value_label = ctk.CTkLabel(blur_frame, text="25", text_color=UI_ACCENT, font=("Segoe UI", 10), width=30)
            self._blur_value_label.pack(side=tk.LEFT, padx=5)
            
            def update_blur_label(value):
                self._blur_value_label.configure(text=str(int(value)))
            self._blur_radius_slider.configure(command=update_blur_label)
            
            pixel_frame = ctk.CTkFrame(self._method_options_frame, fg_color="transparent")
            pixel_frame.pack(pady=5)
            self._pixel_blur = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(pixel_frame, text="Pixelate (Mosaic)", variable=self._pixel_blur,
                            text_color=UI_MUTED, fg_color=UI_BORDER, hover_color=UI_HOVER,
                            checkmark_color=UI_ACCENT).pack(side=tk.LEFT, padx=5)
        
        elif method == "overlay":
            ctk.CTkLabel(self._method_options_frame, text="Overlay file:", text_color=UI_TEXT, font=("Segoe UI", 10)).pack(pady=(5, 2), anchor="w")
            overlay_frame = ctk.CTkFrame(self._method_options_frame, fg_color="transparent")
            overlay_frame.pack(pady=5)
            self._overlay_entry = ctk.CTkEntry(overlay_frame, width=200, height=32, fg_color=UI_FIELD,
                                               border_width=1, border_color=UI_BORDER,
                                               text_color=UI_TEXT, placeholder_text="PNG / JPG path")
            self._overlay_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
            ctk.CTkButton(overlay_frame, text="...", width=30, height=32, fg_color=UI_FIELD,
                          hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER,
                          text_color=UI_TEXT, command=self._browse_overlay_for_panel).pack(side=tk.LEFT, padx=2)
        
        elif method == "crop":
            ctk.CTkLabel(self._method_options_frame, text="Crop removes the selected area from the video\nThe frame size will change!", text_color="#FFAA00", font=("Segoe UI", 9), justify=tk.LEFT).pack(pady=10, anchor="w")
    
    def _browse_overlay_for_panel(self):
        file = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.gif")])
        if file:
            self._overlay_entry.delete(0, tk.END)
            self._overlay_entry.insert(0, file)
    
    def _apply_remove_logo_from_panel(self):
        if not self._roi_start or not self._roi_end:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn vùng cần xóa")
            return
        
        x1, y1 = self._roi_start
        x2, y2 = self._roi_end
        
        w = x2 - x1
        h = y2 - y1
        
        if w <= 0 or h <= 0:
            messagebox.showwarning("Cảnh báo", "Vùng chọn không hợp l���")
            return
        
        clip = self.selected_clips[0]
        video_path = clip.file_path
        
        self._logo_filepath = video_path
        self._logo_x = x1
        self._logo_y = y1
        self._logo_w = w
        self._logo_h = h
        self._logo_mode = self._remove_method_var.get()
        
        if self._logo_mode == "blur":
            if hasattr(self, '_blur_radius_slider'):
                self._logo_blur_radius = int(self._blur_radius_slider.get())
            if hasattr(self, '_pixel_blur'):
                self._logo_pixel_blur = self._pixel_blur.get()
        
        if self._logo_mode == "overlay":
            overlay_file = self._overlay_entry.get()
            if not overlay_file or not os.path.exists(overlay_file):
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn file đè lên")
                return
            self._overlay_file_for_panel = overlay_file
        
        self._clear_roi_selection()
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        
        if self._logo_mode == "blur":
            self._do_blur_logo(output_dir, base_name, None)
        elif self._logo_mode == "ai":
            self._do_ai_remove_logo(output_dir, base_name, None)
        elif self._logo_mode == "crop":
            self._do_crop_logo(output_dir, base_name, None)
        elif self._logo_mode == "overlay":
            self._overlay_for_panel = overlay_file
            self._do_overlay_logo(output_dir, base_name, None)
    
    def _toggle_roi_selection(self):
        self._roi_selection_mode = not self._roi_selection_mode
        
        if self._roi_selection_mode:
            self._select_roi_btn.configure(fg_color=UI_ACCENT_SOFT, text="Stop select")
            self.preview_canvas.configure(cursor="cross")
            
            self._roi_bind_id1 = self.preview_canvas.bind("<ButtonPress-1>", self._on_roi_start)
            self._roi_bind_id2 = self.preview_canvas.bind("<B1-Motion>", self._on_roi_drag)
            self._roi_bind_id3 = self.preview_canvas.bind("<ButtonRelease-1>", self._on_roi_end)
        else:
            self._select_roi_btn.configure(fg_color=UI_HOVER, text="Start select")
            self.preview_canvas.configure(cursor="")
            
            if self._roi_bind_id1:
                self.preview_canvas.unbind("<ButtonPress-1>", self._roi_bind_id1)
            if self._roi_bind_id2:
                self.preview_canvas.unbind("<B1-Motion>", self._roi_bind_id2)
            if self._roi_bind_id3:
                self.preview_canvas.unbind("<ButtonRelease-1>", self._roi_bind_id3)
    
    def _on_roi_start(self, event):
        self._roi_start = (event.x, event.y)
        self._roi_end = (event.x, event.y)
    
    def _on_roi_drag(self, event):
        if self._roi_start:
            self._roi_end = (event.x, event.y)
            
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
            
            x1, y1 = self._roi_start
            x2, y2 = self._roi_end
            self._roi_rect_id = self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline="#FF0000", width=2, dash=(5, 3))
    
    def _on_roi_end(self, event):
        if self._roi_start and self._roi_end:
            x1, y1 = self._roi_start
            x2, y2 = self._roi_end
            
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            
            self._roi_start = (x1, y1)
            self._roi_end = (x2, y2)
            
            self._update_roi_display()
            
            self._select_roi_btn.configure(fg_color=UI_HOVER, text="Start select")
            self.preview_canvas.configure(cursor="")
            
            if self._roi_bind_id1:
                self.preview_canvas.unbind("<ButtonPress-1>", self._roi_bind_id1)
            if self._roi_bind_id2:
                self.preview_canvas.unbind("<B1-Motion>", self._roi_bind_id2)
            if self._roi_bind_id3:
                self.preview_canvas.unbind("<ButtonRelease-1>", self._roi_bind_id3)
            
            self._roi_selection_mode = False
    
    def _update_roi_display(self):
        if self._roi_start and self._roi_end:
            x1, y1 = self._roi_start
            x2, y2 = self._roi_end
            w = x2 - x1
            h = y2 - y1
            
            self._roi_coords_label.configure(text=f"X: {x1}, Y: {y1}\nW: {w}, H: {h}")
            self._clear_roi_btn.configure(state="normal")
            self._apply_remove_logo_btn.configure(state="normal")
            
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
                self._roi_rect_id = None
            self._roi_rect_id = self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline="#00FF00", width=3)
    
    def _clear_roi_selection(self):
        self._roi_start = None
        self._roi_end = None
        
        if self._roi_rect_id:
            self.preview_canvas.delete(self._roi_rect_id)
            self._roi_rect_id = None
        
        self._roi_coords_label.configure(text="No area selected")
        self._clear_roi_btn.configure(state="disabled")
        self._apply_remove_logo_btn.configure(state="disabled")
    
    def _apply_remove_logo(self):
        if not self._roi_start or not self._roi_end:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn vùng cần xóa")
            return
        
        x1, y1 = self._roi_start
        x2, y2 = self._roi_end
        
        w = x2 - x1
        h = y2 - y1
        
        if w <= 0 or h <= 0:
            messagebox.showwarning("Cảnh báo", "Vùng chọn không hợp lệ")
            return
        
        clip = self.selected_clips[0]
        video_path = clip.file_path
        
        self._logo_filepath = video_path
        self._logo_x = x1
        self._logo_y = y1
        self._logo_w = w
        self._logo_h = h
        self._logo_mode = self._remove_method_var.get()
        
        if self._logo_mode == "blur" and hasattr(self, '_blur_radius_slider'):
            self._logo_blur_radius = int(self._blur_radius_slider.get())
        
        self._clear_roi_selection()
        
        self._do_remove_logo(None)
    
    def render_audio_tab(self):
        self._props_section("Basic")
        self._props_audio_levels()

        for text in ["Loudness normalization", "Voice enhancement", "Noise reduction"]:
            cb_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
            cb_frame.pack(fill=tk.X, pady=4)
            ctk.CTkCheckBox(cb_frame, text=text, text_color=UI_MUTED, fg_color=UI_BORDER,
                            hover_color=UI_HOVER, checkmark_color=UI_ACCENT,
                            font=self.PROPS_FONT).pack(side=tk.LEFT, padx=self.PROPS_PAD + 2)

    def render_text_animation_tab(self, clip):
        self._props_section("Text animation", reset=False)
        self._text_anim_clip = clip
        
        ctk.CTkLabel(self.props_content, text="Scrolling and intro moves for this text clip. "
                     "The player and the export share the same frames.",
                     text_color=UI_DIM, font=("Segoe UI", 10), justify=tk.LEFT, anchor="w",
                     wraplength=self._props_wrap()
                     ).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(0, 6))
        
        self._text_effect_type = ctk.StringVar(value=getattr(clip, 'text_effect', 'none'))
        
        effects_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        effects_frame.pack(fill=tk.X, pady=6, padx=(4, self.PROPS_PAD))
        
        for effect_key, effect_name, effect_desc in ANIM.TEXT_EFFECTS:
            item_frame = ctk.CTkFrame(effects_frame, fg_color=UI_HEADER, corner_radius=8)
            item_frame.pack(fill=tk.X, pady=3, padx=4)
            ctk.CTkRadioButton(item_frame, text=effect_name, variable=self._text_effect_type,
                               value=effect_key, font=("Segoe UI", 11, "bold"),
                               text_color=UI_TEXT, fg_color=UI_ACCENT, border_color=UI_DIM,
                               hover_color=UI_ACCENT_SOFT, command=self._on_text_choice
                               ).pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(item_frame, text=effect_desc, text_color=UI_MUTED,
                         font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(0, 8))
        
        intensity_row = self._props_row("Speed")
        self._text_intensity = ctk.CTkSlider(intensity_row, from_=1, to=10, height=16,
                                             fg_color=UI_BORDER, progress_color=UI_TEXT,
                                             button_color="#FFFFFF",
                                             button_hover_color=UI_ACCENT,
                                             command=self._on_text_intensity)
        self._text_intensity.set(int(getattr(clip, 'text_intensity', 5)))
        self._text_intensity.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self._text_intensity_label = ctk.CTkLabel(intensity_row,
                                                  text=str(int(getattr(clip, 'text_intensity', 5))),
                                                  text_color=UI_TEXT, width=self.PROPS_VALUE_W,
                                                  anchor="e", font=self.PROPS_FONT)
        self._text_intensity_label.grid(row=0, column=2, sticky="e")
        
        ctk.CTkButton(self.props_content, text="Play preview", fg_color=UI_ACCENT_SOFT,
                      text_color="#04252A", height=34, corner_radius=8,
                      font=("Segoe UI", 11, "bold"), command=self._preview_text_animation
                      ).pack(fill=tk.X, padx=self.PROPS_PAD, pady=(8, 16))
    
    def _on_text_choice(self):
        clip = getattr(self, "_text_anim_clip", None)
        if clip is None:
            return
        clip.text_effect = self._text_effect_type.get()
        clip.text_intensity = int(self._text_intensity.get())
        self._seek_to_frame(int(clip.start_time * 30))
        self.set_status("Text animation: %s (%d)"
                        % (ANIM.label(ANIM.TEXT_EFFECTS, clip.text_effect),
                           clip.text_intensity))
    
    def _on_text_intensity(self, value):
        intensity = int(value)
        if hasattr(self, "_text_intensity_label"):
            self._text_intensity_label.configure(text=str(intensity))
        clip = getattr(self, "_text_anim_clip", None)
        if clip is not None:
            clip.text_intensity = intensity
        self.draw_preview_frame(int(self.current_frame))
    
    def _preview_text_animation(self):
        clip = getattr(self, "_text_anim_clip", None)
        if clip is None:
            return
        if self.is_playing:
            self.play_video()
        self._seek_to_frame(int(clip.start_time * 30))
        self.play_video()
        self.root.after(max(400, int(clip.duration * 1000)), self._stop_motion_preview)
    
    def render_text_tab(self):
        self._props_sub_tabs(["Basic", "Bubble", "Effect"])

        self._props_section("Text")

        text_box = ctk.CTkTextbox(self.props_content, height=80, fg_color=UI_FIELD,
                                  text_color=UI_TEXT, border_width=1, border_color=UI_BORDER,
                                  corner_radius=6, font=self.PROPS_FONT)
        text_box.pack(fill=tk.X, padx=self.PROPS_PAD, pady=6)
        text_box.insert("0.0", "Default text")

        font_row = self._props_row("Font", pady=2)
        font_row.grid_columnconfigure(1, weight=1)
        self._props_dropdown(font_row, "System",
                             ["System", "Segoe UI", "Arial", "Roboto", "Montserrat"]
                             ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0))

        size_row = self._props_row("Size", pady=2)
        self._props_slider(size_row, 0, 100, 15)
        self._props_value(size_row, "15", stepper=False)

        style_row = self._props_row("Style", pady=2)
        style_bar = ctk.CTkFrame(style_row, fg_color=UI_FIELD, corner_radius=6, height=30)
        style_bar.grid(row=0, column=1, columnspan=3, sticky="ew", ipady=1)
        for glyph, tip in (("B", "Bold"), ("U", "Underline"), ("I", "Italic"), ("S", "Strike")):
            ctk.CTkButton(style_bar, text=glyph, width=34, height=24, corner_radius=5,
                          fg_color="transparent", hover_color=UI_HOVER, text_color=UI_MUTED,
                          font=(UI_FONT, 12, "bold"),
                          command=lambda: self._toast("Text styling is preview-only in this build")
                          ).pack(side=tk.LEFT, padx=2)

        case_row = self._props_row("Case", pady=2)
        case_bar = ctk.CTkFrame(case_row, fg_color=UI_FIELD, corner_radius=6, height=30)
        case_bar.grid(row=0, column=1, columnspan=3, sticky="ew", ipady=1)
        for label in ("TT", "tt", "Tt"):
            ctk.CTkButton(case_bar, text=label, width=34, height=24, corner_radius=5,
                          fg_color="transparent", hover_color=UI_HOVER, text_color=UI_MUTED,
                          font=self.PROPS_FONT,
                          command=lambda: self._toast("Text styling is preview-only in this build")
                          ).pack(side=tk.LEFT, padx=2)

        color_row = self._props_row("Color", pady=2)
        swatch = ctk.CTkFrame(color_row, fg_color="#FFFFFF", border_width=1,
                              border_color=UI_BORDER, corner_radius=5, width=44,
                              height=self.PROPS_ROW_H)
        swatch.pack_propagate(False)
        swatch.grid(row=0, column=1, sticky="w", padx=(4, 8))
        self._props_value(color_row, "#FFFFFF")
    
    def render_text_properties(self, clip):
        tab = getattr(self, "current_text_tab", "Text")
        self._render_props_tabs(self.TEXT_TABS, tab, self.on_text_tab_click)
        if tab == "Animation":
            self.render_text_animation_tab(clip)
            return
        if tab != "Text":
            self._render_video_placeholder(tab)
            return
        
        self._text_clip = clip
        
        text_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        text_frame.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(text_frame, text="Content", text_color=UI_MUTED, anchor="w",
                     font=self.PROPS_FONT).pack(anchor="w")
        
        self._text_content_box = ctk.CTkTextbox(self.props_content, height=80, fg_color=UI_FIELD,
                                                text_color=UI_TEXT, border_width=1,
                                                border_color=UI_BORDER, corner_radius=6,
                                                font=self.PROPS_FONT)
        self._text_content_box.pack(fill=tk.X, padx=self.PROPS_PAD, pady=5)
        self._text_content_box.insert("0.0", getattr(clip, 'text_content', ''))
        self._text_content_box.bind("<<Modified>>", lambda e: self._on_text_content_change(clip))
        self._text_content_box.bind("<KeyRelease>", lambda e: self._on_text_content_change(clip))
        
        self._props_section("Style", reset=False)

        size_row = self._props_row("Size", pady=2)
        self._font_size_slider = ctk.CTkSlider(size_row, from_=8, to=120, height=16,
                                               fg_color=UI_BORDER, progress_color=UI_TEXT,
                                               button_color="#FFFFFF", button_hover_color=UI_ACCENT,
                                               number_of_steps=112)
        self._font_size_slider.set(getattr(clip, 'font_size', 36))
        self._font_size_slider.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self._font_size_label = ctk.CTkLabel(size_row, text=str(int(getattr(clip, 'font_size', 36))),
                                             text_color=UI_TEXT, width=self.PROPS_VALUE_W,
                                             anchor="e", font=self.PROPS_FONT)
        self._font_size_label.grid(row=0, column=2, sticky="e")
        self._font_size_slider.configure(command=lambda v: self._on_font_size_change(clip, v))

        self._props_group("Position")
        pos_row = self._props_row(pady=2)
        for index, (axis, attr, default) in enumerate((("X", "x_pos", 320), ("Y", "y_pos", 180))):
            pos_row.grid_columnconfigure(index * 2 + 1, weight=1)
            ctk.CTkLabel(pos_row, text=axis, text_color=UI_MUTED, width=14, anchor="w",
                         font=self.PROPS_FONT).grid(row=0, column=index * 2, sticky="w",
                                                    padx=(0, 4) if index == 0 else (8, 4))
            entry = ctk.CTkEntry(pos_row, width=40, height=self.PROPS_ROW_H, fg_color=UI_FIELD,
                                 border_width=1, border_color=UI_BORDER, text_color=UI_TEXT,
                                 font=self.PROPS_FONT)
            entry.grid(row=0, column=index * 2 + 1, sticky="ew")
            entry.insert(0, str(int(getattr(clip, attr, default))))
            entry.bind("<KeyRelease>", lambda e, key=axis.lower(): self._on_pos_change(clip, key))
            setattr(self, "_%s_pos_entry" % axis.lower(), entry)

        def color_row(title, colors, handler):
            ctk.CTkLabel(self.props_content, text=title, text_color=UI_MUTED, anchor="w",
                         font=self.PROPS_FONT).pack(fill=tk.X, padx=self.PROPS_PAD + 2, pady=(10, 2))
            grid = ctk.CTkFrame(self.props_content, fg_color=UI_FIELD, corner_radius=6)
            grid.pack(fill=tk.X, padx=self.PROPS_PAD, pady=(0, 4))
            for color_val, color_hex in colors:
                ctk.CTkButton(grid, text="", fg_color=color_hex, border_width=1,
                              border_color=UI_BORDER, width=24, height=22, corner_radius=4,
                              command=lambda c=color_val, h=color_hex: handler(c, h)
                              ).pack(side=tk.LEFT, padx=2, pady=5)

        color_row("Text color", [("white", "#FFFFFF"), ("black", "#000000"),
                                 ("yellow", "#FFFF00"), ("red", "#FF0000"),
                                 ("green", "#00FF00"), ("blue", "#0000FF"),
                                 ("orange", "#FFA500"), ("pink", "#FF69B4")],
                  lambda c, h: self._on_text_color_change(clip, c, h))
        color_row("Background color", [("transparent", UI_FIELD), ("red", "#FF0000"),
                                        ("blue", "#0000FF"), ("green", "#00FF00"),
                                        ("yellow", "#FFFF00"), ("black", "#000000")],
                  lambda c, h: self._on_bg_color_change(clip, c))
    
    def _on_text_content_change(self, clip):
        if hasattr(self._text_content_box, 'edit_modified'):
            self._text_content_box.edit_modified(False)
        text = self._text_content_box.get("0.0", tk.END).strip()
        clip.text_content = text
        self.draw_preview_frame(int(self.current_frame))
    
    def _on_font_size_change(self, clip, value):
        value = int(value)
        clip.font_size = value
        self._font_size_label.configure(text=str(value))
        self.draw_preview_frame(int(self.current_frame))
    
    def _on_pos_change(self, clip, axis):
        try:
            val = int(self._x_pos_entry.get() if axis == 'x' else self._y_pos_entry.get())
            if axis == 'x':
                clip.x_pos = max(50, min(590, val))
            else:
                clip.y_pos = max(30, min(330, val))
            self.draw_preview_frame(int(self.current_frame))
        except:
            pass
    
    def _on_text_color_change(self, clip, color_val, color_hex):
        clip.text_color = color_val
        self.draw_preview_frame(int(self.current_frame))
    
    def _on_bg_color_change(self, clip, color_val):
        clip.bg_color = color_val
        self.draw_preview_frame(int(self.current_frame))
    
    def create_timeline_panel(self, parent):
        tl_frame = ctk.CTkFrame(parent, fg_color=UI_PANEL, corner_radius=0)
        tl_frame.pack(fill=tk.BOTH, expand=True)

        # Timeline Toolbar
        toolbar = ctk.CTkFrame(tl_frame, fg_color=UI_RAIL, height=40, corner_radius=0)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)

        # Left tools
        left_tools = ctk.CTkFrame(toolbar, fg_color="transparent")
        left_tools.pack(side=tk.LEFT, padx=8)
        self._cut_mode = False
        self.cut_btn = self._icon_btn(left_tools, "cut", self.toggle_cut_mode, px=15, size=28,
                                      tip="Toggle cut mode")
        self.cut_btn.pack(side=tk.LEFT, padx=1)
        for glyph, cmd, tip in (
                ("split", self.cut_clip_at_playhead, "Split clip at playhead"),
                ("trash", self.delete_clips, "Delete selected clips"),
                ("close", self._deselect_all, "Deselect all"),
                ("zoom_out", self.zoom_out, "Zoom out"),
                ("zoom_in", self.zoom_in, "Zoom in"),
                ("fit_width", self._reset_timeline_zoom, "Reset zoom")):
            self._icon_btn(left_tools, glyph, cmd, px=15, size=28, tip=tip).pack(side=tk.LEFT, padx=1)

        # Right tools (zoom)
        right_tools = ctk.CTkFrame(toolbar, fg_color="transparent")
        right_tools.pack(side=tk.RIGHT, padx=10)
        self._icon_btn(right_tools, "plus_circle", self.zoom_in, px=14, size=24).pack(
            side=tk.RIGHT, padx=(6, 0))
        self.tl_zoom_slider = ctk.CTkSlider(right_tools, from_=5, to=200, width=110,
                                            fg_color=UI_FIELD, progress_color=UI_ACCENT,
                                            button_color=UI_TEXT, button_hover_color=UI_ACCENT_SOFT,
                                            command=self.on_zoom_slider_move)
        self.tl_zoom_slider.set(30)
        self.tl_zoom_slider.pack(side=tk.RIGHT, padx=(0, 6))

        # Tracks Container
        tracks_container = ctk.CTkFrame(tl_frame, fg_color=UI_BG)
        tracks_container.pack(fill=tk.BOTH, expand=True)

        # Time Ruler
        self.ruler_canvas = tk.Canvas(tracks_container, bg=UI_RAIL, highlightthickness=0, height=30)
        self.ruler_canvas.pack(fill=tk.X)
        self.ruler_canvas.bind("<ButtonPress-1>", self.on_ruler_click)
        self.ruler_canvas.bind("<B1-Motion>", self.on_ruler_drag)
        self.draw_ruler()

        # Timeline Tracks Canvas
        self.tl_canvas = tk.Canvas(tracks_container, bg=UI_BG, highlightthickness=0)
        self.tl_canvas.pack(fill=tk.BOTH, expand=True)
        self.tl_canvas.bind("<ButtonPress-1>", self.on_tl_click)
        self.tl_canvas.bind("<B1-Motion>", self.on_tl_drag)
        self.tl_canvas.bind("<Button-3>", self.on_tl_right_click)

        self.draw_playhead()

        try:
            self.tl_canvas.drop_target_register('DND_Files')
            self.tl_canvas.dnd_bind('<<Drop>>', self.on_timeline_drop)
        except:
            pass

    def _reset_timeline_zoom(self):
        self.tl_zoom_slider.set(30)
        self.on_zoom_slider_move(30)

    def toggle_cut_mode(self):
        self._cut_mode = not self._cut_mode
        if self._cut_mode:
            self.cut_btn.configure(fg_color=UI_ACCENT_BG, border_width=1,
                                   border_color=UI_ACCENT,
                                   image=ui_icon("cut", 15, UI_ACCENT))
            self.tl_canvas.configure(cursor="cross")
        else:
            self.cut_btn.configure(fg_color="transparent", border_width=0,
                                   image=ui_icon("cut", 15, UI_MUTED))
            self.tl_canvas.configure(cursor="")
    
    def on_timeline_drop(self, event):
        pass
    
    def on_file_drop(self, event):
        # Get dropped files from event data
        try:
            # Try to parse file paths from the drop event
            data = event.data
            if data:
                # Parse Windows file paths
                files = data.split()
                for f in files:
                    f = f.strip('{}')  # Remove curly braces if present
                    if os.path.isfile(f):
                        self.add_to_timeline(f)
        except Exception as e:
            print(f"Drop error: {e}")
    
    def add_to_timeline(self, path):
        if not os.path.isfile(path):
            return
            
        ext = os.path.splitext(path)[1].lower()
        supported = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', 
                    '.jpg', '.jpeg', '.png', '.gif']
        
        if ext not in supported:
            return
        
        mtype = 'video' if ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm'] else \
                'audio' if ext in ['.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'] else 'image'
        
        # Add to media files
        if path not in self.media_files:
            self.media_files.append(path)
            self.media_types.append(mtype)
            self.generate_thumbnail(path)
        
        # Add to timeline clips
        dur = self.get_media_duration(path, mtype)
        track_idx = 0 if mtype in ['video', 'image'] else 1 if mtype == 'text' else 2
        
        track_clips = [c for c in self.timeline_clips if c.track_idx == track_idx]
        start_time = max([c.start_time + c.duration for c in track_clips], default=0.0)
        
        clip = TimelineClip(path, start_time, dur, mtype, track_idx)
        self.timeline_clips.append(clip)
        
        # Draw on timeline
        self.draw_timeline_clips()
        
        self.refresh_thumbnails()
        
    def get_media_duration(self, path, mtype):
        if not MOVIEPY_AVAILABLE: return 5.0
        try:
            if mtype == 'video':
                with MOVIEPY['VideoFileClip'](path) as clip:
                    return float(clip.duration)
            elif mtype == 'audio':
                import subprocess
                import os
                
                ffmpeg_exec = find_ffmpeg()
                
                ffprobe_exec = None
                if ffmpeg_exec and os.path.exists(ffmpeg_exec):
                    ffprobe_exec = ffmpeg_exec.replace("ffmpeg", "ffprobe")
                
                if not ffmpeg_exec:
                    return 5.0
                
                try:
                    if ffprobe_exec and os.path.exists(ffprobe_exec):
                        cmd = [ffprobe_exec, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                        if result.returncode == 0 and result.stdout.strip():
                            try:
                                return float(result.stdout.strip())
                            except ValueError:
                                pass
                except Exception as e:
                    print(f"FFprobe error: {e}")
                
                return 5.0
        except Exception as e:
            print("Error getting duration:", e)
        return 5.0
    
    def draw_timeline_clips(self):
        # Clear canvas entirely
        self.tl_canvas.delete("all")
        self.timeline_photos = []  # reset photos reference

        used = sorted({c.track_idx for c in self.timeline_clips})
        rows = max(2, (used[-1] + 1) if used else 2)

        for idx in range(rows):
            y = 20 + idx * 60
            kinds = {c.clip_type for c in self.timeline_clips if c.track_idx == idx}
            if kinds and kinds <= {"audio"}:
                name, glyph, icons = "Audio 1", "audio", ("lock", "speaker_off")
            elif "text" in kinds:
                name, glyph, icons = "Text 1", "track_text", ("lock", "eye")
            elif kinds & {"video", "image"}:
                name, glyph, icons = "Video 1", "track_video", ("lock", "eye", "speaker")
            else:
                name, glyph, icons = "Track %d" % (idx + 1), "frame", ("lock",)
            self._draw_track_header(y, name, glyph, icons)
            self.tl_canvas.create_line(0, y + 50, 3000, y + 50, fill="#17171D")

        self.tl_canvas.create_line(100, 0, 100, max(500, 20 + rows * 60 + 30), fill=UI_BORDER)

        for clip in self.timeline_clips:
            track_y = 20 + clip.track_idx * 60

            x1 = 100 + clip.start_time * self.pixels_per_second
            x2 = x1 + clip.duration * self.pixels_per_second
            y1 = track_y
            y2 = y1 + 40

            clip.bbox = (x1, y1, x2, y2)

            is_selected = (clip in getattr(self, 'selected_clips', []))
            if clip.clip_type == "audio":
                body, edge = "#12302A", "#2C6E56"
            elif clip.clip_type == "text":
                body, edge = "#5B3BA8", "#8A6BF0"
            else:
                body, edge = "#22222A", "#3A3A46"
            self.tl_canvas.create_rectangle(
                x1, y1, x2, y2, fill=body,
                outline=UI_ACCENT if is_selected else edge,
                width=2 if is_selected else 1)

            # Rich Visuals inside
            if clip.clip_type in ["video", "image"]:
                thumb = self.thumbnails.get(clip.file_path)
                if thumb:
                    img_h = 36
                    aspect = thumb.width / thumb.height if thumb.height > 0 else 1
                    img_w = int(img_h * aspect)
                    if img_w > 0:
                        resized = thumb.resize((img_w, img_h), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(resized)
                        self.timeline_photos.append(photo)

                        curr_x = int(x1) + 2
                        max_x = int(x2) - 2
                        while curr_x < max_x:
                            draw_w = min(img_w, max_x - curr_x)
                            if draw_w < img_w:
                                crop_p = ImageTk.PhotoImage(resized.crop((0, 0, draw_w, img_h)))
                                self.timeline_photos.append(crop_p)
                                self.tl_canvas.create_image(curr_x, int(y1) + 2, image=crop_p, anchor=tk.NW)
                            else:
                                self.tl_canvas.create_image(curr_x, int(y1) + 2, image=photo, anchor=tk.NW)
                            curr_x += img_w
            elif clip.clip_type == "audio":
                import random
                random.seed(clip.file_path)
                mid_y = (y1 + y2) / 2
                for cx in range(int(x1) + 3, int(x2) - 3, 4):
                    amp = random.randint(3, 15)
                    self.tl_canvas.create_line(cx, mid_y - amp, cx, mid_y + amp, fill="#3DDC84")
            elif clip.clip_type == "text":
                label = (getattr(clip, "text_content", "") or "Text").strip()[:24]
                self.tl_canvas.create_text(x1 + 8, y1 + 20, text=label, fill="white",
                                           anchor=tk.W, font=(UI_FONT, 10, "bold"))

            if clip.clip_type != "text":
                name = os.path.basename(clip.file_path)[:15]
                self.tl_canvas.create_text(x1 + 6, y1 + 11, text=name, fill="black",
                                           anchor=tk.W, font=(UI_FONT, 9))
                self.tl_canvas.create_text(x1 + 5, y1 + 10, text=name, fill="white",
                                           anchor=tk.W, font=(UI_FONT, 9))

            if clip.duration and x2 - x1 > 70:
                dur_txt = format_duration(clip.duration)
                w = len(dur_txt) * 6 + 8
                self.tl_canvas.create_rectangle(x2 - w - 4, y2 - 15, x2 - 4, y2 - 3,
                                                fill="#000000", outline="")
                self.tl_canvas.create_text(x2 - 4 - w / 2, y2 - 9, text=dur_txt,
                                           fill="#FFFFFF", font=(UI_FONT, 8, "bold"))

            if clip.is_pinned:
                self.tl_canvas.create_text(x1 + 5, y1 - 8, text="Pinned",
                                           fill=UI_ACCENT, anchor=tk.W, font=(UI_FONT, 8, "bold"))

        self.draw_playhead()

        total_dur = self.get_total_duration()
        self.timeline_slider.configure(to=int(total_dur * 30))

    def _draw_track_header(self, y, name, glyph, icons):
        c = self.tl_canvas
        c.create_rectangle(0, y, 100, y + 50, fill=UI_RAIL, outline="#17171D")
        badge = ui_badge(glyph, 12, UI_MUTED, UI_HEADER, pad=3)
        self.timeline_photos.append(badge)
        c.create_image(8, y + 7, image=badge, anchor=tk.NW)
        c.create_text(32, y + 12, text=name, fill=UI_TEXT, font=(UI_FONT, 9), anchor=tk.W)
        x = 10
        for icon in icons:
            chip = ui_badge(icon, 11, UI_MUTED, UI_RAIL, pad=3)
            self.timeline_photos.append(chip)
            c.create_image(x, y + 30, image=chip, anchor=tk.NW)
            x += 24

    def draw_ruler(self):
        self.ruler_canvas.delete("all")
        self.ruler_canvas.create_line(0, 29, 3000, 29, fill=UI_BORDER)
        pps = self.pixels_per_second
        for sec in np.arange(0, 3000 / pps, 1):
            x = 100 + sec * pps
            if x > 3000:
                break
            if sec % 5 == 0:
                self.ruler_canvas.create_line(x, 18, x, 29, fill="#4E4E5A")
                self.ruler_canvas.create_text(x, 9, text="00:%02d" % int(sec),
                                              fill=UI_MUTED, font=(UI_FONT, 8))
            else:
                self.ruler_canvas.create_line(x, 24, x, 29, fill="#33333D")
                
    def on_zoom_slider_move(self, value):
        self.pixels_per_second = value
        self.draw_ruler()
        self.draw_timeline_clips()
        
    def zoom_in(self):
        val = min(200, self.pixels_per_second + 10)
        self.tl_zoom_slider.set(val)
        self.on_zoom_slider_move(val)
        
    def zoom_out(self):
        val = max(5, self.pixels_per_second - 10)
        self.tl_zoom_slider.set(val)
        self.on_zoom_slider_move(val)
    
    def cut_clip_at_playhead(self):
        if not hasattr(self, 'timeline_slider'):
            return
        current = self.timeline_slider.get() / 30.0
        self.cut_clip_at_time(current)
    
    def cut_clip_at_time(self, cut_time):
        modified = False
        for clip in self.timeline_clips:
            if clip.start_time < cut_time < (clip.start_time + clip.duration):
                if clip.clip_type == 'video':
                    self._split_video_clip(clip, cut_time)
                    modified = True
                else:
                    clip2 = TimelineClip(
                        clip.file_path,
                        cut_time,
                        clip.start_time + clip.duration - cut_time,
                        clip.clip_type,
                        clip.track_idx
                    )
                    clip.duration = cut_time - clip.start_time
                    self.timeline_clips.append(clip2)
                    modified = True
                break
        if modified:
            self.draw_timeline_clips()
    
    def _split_video_clip(self, clip, cut_time):
        if not MOVIEPY_AVAILABLE:
            messagebox.showerror("Lỗi", "Cần moviepy để cắt video")
            return
        try:
            import time as time_module
            local_cut = cut_time - clip.start_time
            
            dialog = ctk.CTkToplevel()
            dialog.title("Cắt Video")
            dialog.geometry("450x250")
            dialog.transient(self.root)
            dialog.grab_set()
            
            scroll = ctk.CTkScrollableFrame(dialog, width=430, height=230, fg_color="#1A1A1A")
            scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            content = scroll
            
            ctk.CTkLabel(content, text="Cắt video chạy nền", text_color="#00E5FF", font=("Segoe UI", 14, "bold")).pack(pady=10)
            ctk.CTkLabel(content, text=f"⏱ Thời điểm cắt: {local_cut:.2f}s", text_color="#888").pack(pady=5)
            ctk.CTkLabel(content, text="⚠️ Video sẽ được tách tại thời điểm cắt\nTác vụ sẽ chạy nền ngay cả khi đóng cửa sổ", text_color="#FFAA00").pack(pady=10)
            
            btn_frame = ctk.CTkFrame(content, fg_color="transparent")
            btn_frame.pack(pady=20)
            
            def do_split():
                dialog.destroy()
                
                output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
                os.makedirs(output_dir, exist_ok=True)
                
                base_name = os.path.splitext(os.path.basename(clip.file_path))[0]
                
                part1_path = os.path.join(output_dir, f"{base_name}_p1.mp4")
                part2_path = os.path.join(output_dir, f"{base_name}_p2.mp4")
                
                progress_win = ctk.CTkToplevel()
                progress_win.title("Đang cắt video")
                progress_win.geometry("400x150")
                progress_win.transient(self.root)
                progress_win.grab_set()
                
                lbl = ctk.CTkLabel(progress_win, text="⏳ Đang cắt video...", text_color="white", font=("Segoe UI", 14))
                lbl.pack(pady=20)
                progress_bar = ctk.CTkProgressBar(progress_win, width=300)
                progress_bar.pack(pady=10)
                progress_bar.set(0)
                
                status_lbl = ctk.CTkLabel(progress_win, text="Đang khởi tạo...", text_color="#888")
                status_lbl.pack(pady=5)
                
                btn_frame2 = ctk.CTkFrame(progress_win, fg_color="transparent")
                btn_frame2.pack(pady=10)
                
                paused = [False]
                cancelled = [False]
                
                def toggle_pause():
                    paused[0] = not paused[0]
                    pause_btn.configure(text="▶ Tiếp từ" if paused[0] else "⏸ Tạm dừng")
                
                def cancel_cut():
                    cancelled[0] = True
                    progress_win.destroy()
                    messagebox.showinfo("Huỷ", "Đã huỷ tác vụ cắt video")
                
                pause_btn = ctk.CTkButton(btn_frame2, text="⏸ Tạm dừng", fg_color="#FF9800", text_color="white", width=120, command=toggle_pause)
                pause_btn.pack(side=tk.LEFT, padx=10)
                ctk.CTkButton(btn_frame2, text="⏹ Huỷ", fg_color="#F44336", text_color="white", width=80, command=cancel_cut).pack(side=tk.LEFT, padx=10)
                ctk.CTkButton(btn_frame2, text="📥 Chạy nền", fg_color="#333", text_color="white", width=100, command=progress_win.destroy).pack(side=tk.LEFT, padx=10)
                
                progress_win.update()
                
                def run_in_background():
                    try:
                        video_clip = MOVIEPY['VideoFileClip'](clip.file_path)
                        
                        status_lbl.configure(text="Đang xuất phần 1...")
                        progress_win.update()
                        
                        while paused[0] and not cancelled[0]:
                            time_module.sleep(0.2)
                        
                        if cancelled[0]:
                            video_clip.close()
                            return
                        
                        part1 = video_clip.subclipped(0, local_cut)
                        progress_bar.set(0.2)
                        progress_win.update()
                        
                        part1.write_videofile(part1_path, codec='libx264', audio_codec='aac', logger=None, preset='ultrafast')
                        progress_bar.set(0.5)
                        progress_win.update()
                        
                        while paused[0]:
                            time_module.sleep(0.2)
                        
                        status_lbl.configure(text="Đang xuất phần 2...")
                        
                        if cancelled[0]:
                            video_clip.close()
                            part1.close()
                            return
                        
                        part2 = video_clip.subclipped(local_cut, video_clip.duration)
                        part2.write_videofile(part2_path, codec='libx264', audio_codec='aac', logger=None, preset='ultrafast')
                        
                        video_clip.close()
                        part1.close()
                        part2.close()
                        
                        progress_bar.set(1.0)
                        status_lbl.configure(text="✅ Hoàn tất!")
                        progress_win.update()
                        time_module.sleep(1)
                        
                        clip.file_path = part1_path
                        clip.duration = local_cut
                        
                        clip2 = TimelineClip(
                            part2_path,
                            cut_time,
                            self.get_total_duration() - cut_time,
                            clip.clip_type,
                            clip.track_idx
                        )
                        self.timeline_clips.append(clip2)
                        
                        self.media_files.append(part1_path)
                        self.media_files.append(part2_path)
                        self.media_types.append("video")
                        self.media_types.append("video")
                        self.generate_thumbnail(part1_path)
                        self.generate_thumbnail(part2_path)
                        
                        self.draw_timeline_clips()
                        self.refresh_thumbnails()
                        
                        if progress_win.winfo_exists():
                            progress_win.destroy()
                        
                        messagebox.showinfo("Thành công", f"Đã cắt video!\n\nPhần 1: {part1_path}\nPhần 2: {part2_path}")
                        
                    except Exception as e:
                        if progress_win.winfo_exists():
                            progress_win.destroy()
                        messagebox.showerror("Lỗi", f"Không thể cắt video:\n{str(e)}")
                
                import threading
                threading.Thread(target=run_in_background, daemon=True).start()
            
            ctk.CTkButton(btn_frame, text="Cắt", fg_color="#00AA55", width=80, command=do_split).pack(side=tk.LEFT, padx=10)
            ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể cắt video:\n{str(e)}")
        
    def get_clip_part_at(self, x, y):
        for clip in reversed(self.timeline_clips):
            if hasattr(clip, 'bbox'):
                x1, y1, x2, y2 = clip.bbox
                if x1 <= x <= x2 and y1 <= y <= y2:
                    if x - x1 < 8:
                        return clip, 'left_edge'
                    elif x2 - x < 8:
                        return clip, 'right_edge'
                    else:
                        return clip, 'center'
        return None, None

    def on_tl_click(self, event):
        if getattr(self, '_cut_mode', False):
            time_sec = (event.x - 100) / self.pixels_per_second if event.x > 100 else 0
            self.cut_clip_at_time(time_sec)
            return
        
        clip, part = self.get_clip_part_at(event.x, event.y)
        
        if clip:
            if hasattr(clip, 'group_id') and clip.group_id:
                group_clips = [c for c in self.timeline_clips if getattr(c, 'group_id', None) == clip.group_id]
                self.selected_clips = group_clips
            else:
                if event.state & 0x0001 or event.state & 0x0004:
                    if clip in self.selected_clips:
                        self.selected_clips.remove(clip)
                    else:
                        self.selected_clips.append(clip)
                else:
                    if clip not in self.selected_clips:
                        self.selected_clips = [clip]
            
            self.is_dragging_clip = True
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            self.drag_start_states = {c: {'start_time': c.start_time, 'duration': c.duration, 'track_idx': c.track_idx} for c in self.selected_clips}
            self.drag_part = part
            self.draw_timeline_clips()
            self.update_properties_panel()
        else:
            self.selected_clips = []
            self.is_dragging_clip = False
            self.drag_part = None
            self.update_playhead_position(event.x)
            self.draw_timeline_clips()
            self.update_properties_panel()

    def on_tl_drag(self, event):
        if hasattr(self, 'is_dragging_clip') and self.is_dragging_clip and self.selected_clips:
            delta_x = event.x - self.drag_start_x
            delta_time = delta_x / self.pixels_per_second
            track_shift = int((event.y - self.drag_start_y) / 60) if hasattr(self, 'drag_start_y') else 0
            
            for c in self.selected_clips:
                initial = self.drag_start_states.get(c)
                if not initial: continue
                
                if self.drag_part == 'center':
                    c.start_time = max(0, initial['start_time'] + delta_time)
                    c.track_idx = max(0, initial['track_idx'] + track_shift)
                elif self.drag_part == 'right_edge':
                    c.duration = max(0.5, initial['duration'] + delta_time)
                elif self.drag_part == 'left_edge':
                    c.start_time = max(0, initial['start_time'] + delta_time)
                    c.duration = max(0.5, initial['duration'] - delta_time)
                
            self.draw_timeline_clips()
        else:
            self.update_playhead_position(event.x)
            
    def get_total_duration(self):
        pinned = next((c for c in self.timeline_clips if c.is_pinned), None)
        if pinned:
            return pinned.start_time + pinned.duration
        elif self.timeline_clips:
            return max(c.start_time + c.duration for c in self.timeline_clips)
        return 1.0
            
    def on_tl_right_click(self, event):
        clip, part = self.get_clip_part_at(event.x, event.y)
        if clip:
            if clip not in getattr(self, 'selected_clips', []):
                self.selected_clips = [clip]
            self.draw_timeline_clips()
            
            menu = tk.Menu(self.root, tearoff=0, bg="#2B2B2B", fg="white")
            pin_text = "Bỏ ghim (Unpin)" if clip.is_pinned else "Ghim làm Layout chính (Pin)"
            menu.add_command(label=pin_text, command=lambda: self.toggle_pin(clip))
            
            if len(self.selected_clips) > 1:
                menu.add_command(label="Nhóm (Group)", command=self.group_clips)
            else:
                menu.add_command(label="Nhóm (Group)", state="disabled")
            
            if clip.clip_type == 'audio':
                cut_audio_menu = tk.Menu(menu, tearoff=0, bg="#2B2B2B", fg="white")
                cut_audio_menu.add_command(label="Cắt tại vị trí con trỏ", command=lambda: self._cut_audio_at_click_pos(clip, event.x))
                cut_audio_menu.add_command(label="Cắt tại playhead", command=lambda: self._cut_audio_at_playhead(clip))
                cut_audio_menu.add_separator()
                cut_audio_menu.add_command(label="Tách file gốc", command=lambda: self._split_audio_file(clip))
                menu.add_cascade(label="Cắt Audio", menu=cut_audio_menu)
            elif clip.clip_type in ['video', 'image']:
                cut_video_menu = tk.Menu(menu, tearoff=0, bg="#2B2B2B", fg="white")
                cut_video_menu.add_command(label="Cắt tại vị trí con trỏ", command=lambda: self._cut_video_at_click_pos(clip, event.x))
                cut_video_menu.add_command(label="Cắt tại playhead", command=lambda: self._cut_video_at_playhead(clip))
                menu.add_cascade(label="Cắt Video", menu=cut_video_menu)
            
            menu.add_command(label="Lên trên (Bring Forward)", command=self.move_layer_up)
            menu.add_command(label="Xuống dưới (Send Backward)", command=self.move_layer_down)
            menu.add_separator()
            menu.add_command(label="Xoá (Delete)", command=self.delete_clips)
            
            menu.post(event.x_root, event.y_root)
    
    def _cut_audio_at_click_pos(self, clip, x):
        time_sec = (x - 100) / self.pixels_per_second if x > 100 else 0
        if clip.start_time <= time_sec <= clip.start_time + clip.duration:
            self._cut_audio_clip(clip, time_sec)
    
    def _cut_audio_at_playhead(self, clip):
        time_sec = self.current_frame / 30.0
        if clip.start_time <= time_sec <= clip.start_time + clip.duration:
            self._cut_audio_clip(clip, time_sec)
    
    def _cut_audio_clip(self, clip, cut_time):
        import os
        if not clip.file_path or not os.path.exists(clip.file_path):
            messagebox.showerror("Lỗi", "File audio không tồn tại")
            return
        
        import shutil
        ffmpeg_path = find_ffmpeg()
        
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                ffmpeg_path = path
                break
        
        if not ffmpeg_path or not shutil.which("ffmpeg"):
            messagebox.showerror("Lỗi", "Cần ffmpeg để cắt audio.\nVui lòng cài đặt ffmpeg.")
            return
        
        import time as time_module
        local_cut = cut_time - clip.start_time
        
        dialog = ctk.CTkToplevel()
        dialog.title("Cắt Audio")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=430, height=230, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        ctk.CTkLabel(content, text="Cắt audio bằng FFmpeg", text_color="#00E5FF", font=("Segoe UI", 14, "bold")).pack(pady=10)
        ctk.CTkLabel(content, text=f"Thời điểm cắt: {local_cut:.2f}s", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text="Audio sẽ được tách tại thời điểm cắt", text_color="#FFAA00").pack(pady=10)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_split():
            dialog.destroy()
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audio")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(clip.file_path))[0]
            ext = os.path.splitext(clip.file_path)[1] or ".mp3"
            
            part1_path = os.path.join(output_dir, f"{base_name}_p1{ext}")
            part2_path = os.path.join(output_dir, f"{base_name}_p2{ext}")
            
            progress_win = ctk.CTkToplevel()
            progress_win.title("Đang cắt audio")
            progress_win.geometry("400x150")
            progress_win.transient(self.root)
            progress_win.grab_set()
            
            lbl = ctk.CTkLabel(progress_win, text="Đang cắt audio...", text_color="white", font=("Segoe UI", 14))
            lbl.pack(pady=20)
            
            def run_in_background():
                import subprocess
                try:
                    lbl.configure(text="Đang xuất phần 1...")
                    progress_win.update()
                    
                    cmd1 = [ffmpeg_path, "-y", "-i", clip.file_path, "-ss", "0", "-to", str(local_cut), "-c", "copy", part1_path]
                    result1 = subprocess.run(cmd1, capture_output=True, text=True)
                    
                    lbl.configure(text="Đang xuất phần 2...")
                    progress_win.update()
                    
                    cmd2 = [ffmpeg_path, "-y", "-i", clip.file_path, "-ss", str(local_cut), "-c", "copy", part2_path]
                    result2 = subprocess.run(cmd2, capture_output=True, text=True)
                    
                    lbl.configure(text="Hoàn tất!")
                    progress_win.update()
                    time_module.sleep(1)
                    
                    clip.file_path = part1_path
                    clip.duration = local_cut
                    
                    clip2 = TimelineClip(
                        part2_path,
                        cut_time,
                        self.get_total_duration() - cut_time,
                        clip.clip_type,
                        clip.track_idx
                    )
                    self.timeline_clips.append(clip2)
                    
                    self.media_files.append(part1_path)
                    self.media_files.append(part2_path)
                    self.media_types.append("audio")
                    self.media_types.append("audio")
                    
                    self.draw_timeline_clips()
                    
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    
                    messagebox.showinfo("Thành công", f"Đã cắt audio!\n\nPhần 1: {part1_path}\nPhần 2: {part2_path}")
                    
                except Exception as e:
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    messagebox.showerror("Lỗi", f"Không thể cắt audio: {str(e)}")
            
            import threading
            threading.Thread(target=run_in_background, daemon=True).start()
        
        ctk.CTkButton(btn_frame, text="Cắt", fg_color="#00AA55", width=80, command=do_split).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _split_audio_file(self, clip):
        messagebox.showinfo("Cắt Audio", "Tính năng tách file audio gốc đang được phát triển...")

    def group_clips(self):
        import uuid
        gid = str(uuid.uuid4())
        for c in getattr(self, 'selected_clips', []):
            c.group_id = gid

    def toggle_pin(self, clip):
        is_p = clip.is_pinned
        for c in self.timeline_clips:
            c.is_pinned = False
        clip.is_pinned = not is_p
        self.draw_timeline_clips()
        
    def move_layer_up(self):
        for c in getattr(self, 'selected_clips', []):
            c.track_idx += 1
        self.draw_timeline_clips()
        
    def move_layer_down(self):
        for c in getattr(self, 'selected_clips', []):
            if c.track_idx > 0:
                c.track_idx -= 1
        self.draw_timeline_clips()
        
    def delete_clips(self):
        for c in getattr(self, 'selected_clips', []):
            if c in self.timeline_clips:
                self.timeline_clips.remove(c)
        self.selected_clips = []
        self.draw_timeline_clips()

    def draw_playhead(self):
        self.ruler_canvas.delete("playhead")
        self.tl_canvas.delete("playhead")
        
        # Draw handle on ruler
        self.ruler_canvas.create_polygon(
            self.playhead_x - 5, 10,
            self.playhead_x + 5, 10,
            self.playhead_x + 5, 20,
            self.playhead_x, 30,
            self.playhead_x - 5, 20,
            fill="white", outline="white", tags="playhead"
        )
        
        # Draw vertical line across timeline
        self.tl_canvas.create_line(self.playhead_x, 0, self.playhead_x, 2000,
                                   fill=UI_ACCENT, tags="playhead")

    def on_ruler_click(self, event):
        self.update_playhead_position(event.x)
        
    def on_ruler_drag(self, event):
        self.update_playhead_position(event.x)
        
    def update_playhead_position(self, x):
        self.playhead_x = max(100, x)
        self.draw_playhead()
        
        time_sec = (self.playhead_x - 100) / 30.0
        frame_idx = int(time_sec * 30)
        
        max_val = self.timeline_slider.cget("to")
        if frame_idx <= max_val:
            self.timeline_slider.set(frame_idx)
            self.draw_preview_frame(frame_idx)
            
    def on_slider_move(self, value):
        frame_idx = int(value)
        self.draw_preview_frame(frame_idx)
        self.playhead_x = 100 + frame_idx
        self.draw_playhead()
        
    def switch_tab(self, tab):
        self.active_tab = tab
        for name, chip in getattr(self, "_media_chip_btns", {}).items():
            active = name == tab
            chip.configure(fg_color=UI_HEADER if active else "transparent",
                           text_color=UI_TEXT if active else UI_MUTED)
        self.refresh_thumbnails()
    
    def import_media(self):
        files = filedialog.askopenfilenames(filetypes=[
            ("All", "*.mp4 *.avi *.mov *.mkv *.webm *.mp3 *.wav *.aac *.m4a *.flac *.ogg *.jpg *.jpeg *.png"),
            ("Video", "*.mp4 *.avi *.mov *.mkv *.webm"),
            ("Audio", "*.mp3 *.wav *.aac *.m4a *.flac *.ogg"),
            ("Image", "*.jpg *.jpeg *.png *.gif")
        ])
        
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            mtype = 'video' if ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm'] else \
                    'audio' if ext in ['.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'] else 'image'
            
            self.media_files.append(f)
            self.media_types.append(mtype)
            self.generate_thumbnail(f)
        
        self.refresh_thumbnails()
        
    def generate_thumbnail(self, path):
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                img = Image.open(path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.thumbnail(self.THUMB_SIZE)
                self.thumbnails[path] = img
            elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm'] and MOVIEPY_AVAILABLE:
                clip = MOVIEPY['VideoFileClip'](path)
                frame = clip.get_frame(0)
                clip.close()
                if isinstance(frame, np.ndarray):
                    frame = Image.fromarray(frame)
                frame.thumbnail(self.THUMB_SIZE)
                self.thumbnails[path] = frame
            elif ext in ['.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg']:
                from PIL import ImageDraw
                import random
                img = Image.new('RGB', self.THUMB_SIZE, color='#232329')
                draw = ImageDraw.Draw(img)
                random.seed(path)
                mid_y = self.THUMB_SIZE[1] // 2
                for x in range(3, self.THUMB_SIZE[0] - 3, 3):
                    amp = random.randint(3, mid_y - 3)
                    draw.line([(x, mid_y - amp), (x, mid_y + amp)], fill='#4FA8C7', width=2)
                self.thumbnails[path] = img
        except Exception as e:
            print(f"Thumb error: {e}")
            
        if path not in self.thumbnails:
            from PIL import ImageDraw
            img = Image.new('RGB', (80, 45), color='#444444')
            try:
                draw = ImageDraw.Draw(img)
                draw.text((10, 15), "Media", fill="white")
            except:
                pass
            self.thumbnails[path] = img
    def refresh_thumbnails(self):
        # Clear existing
        for widget in self.thumb_grid.winfo_children():
            widget.destroy()

        if getattr(self, "_media_subtab", "Import") in ("Cloud", "Stock"):
            ctk.CTkLabel(self.thumb_grid,
                         text="Cloud and Stock libraries need a Clinging account.",
                         text_color=UI_MUTED, font=(UI_FONT, 11), justify=tk.CENTER).pack(pady=40)
            return

        if not self.media_files:
            ctk.CTkLabel(self.thumb_grid,
                         text="No media imported yet.\nUse Import Media to add files.",
                         text_color=UI_MUTED, font=(UI_FONT, 11), justify=tk.CENTER).pack(pady=40)
            return

        avail = self.thumb_grid.winfo_width()
        cols = max(2, avail // (self.THUMB_SIZE[0] + 26)) if avail > 60 else 2
        row, col = 0, 0

        for i in self._media_display_order():
            f = self.media_files[i]
            mtype = self.media_types[i]
            if self.active_tab != "All" and mtype != self.active_tab.lower():
                continue

            thumb = self.thumbnails.get(f)
            is_sel = i in getattr(self, 'selected_media_indices', [])
            frame = ctk.CTkFrame(self.thumb_grid, fg_color=UI_HEADER, corner_radius=8,
                                 border_width=1,
                                 border_color=UI_ACCENT if is_sel else UI_HEADER)
            frame.grid(row=row, column=col, padx=5, pady=5, sticky="nw")

            card = ctk.CTkFrame(frame, fg_color="transparent")
            card.pack(padx=4, pady=(4, 0))
            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                lbl = tk.Label(card, image=photo, bg=UI_HEADER, cursor="hand2")
                lbl.image = photo
                lbl.pack()
                dur = getattr(self, "_media_durations", {}).get(f, 0.0)
                if dur:
                    tk.Label(card, text=format_duration(dur), bg="#000000", fg="#FFFFFF",
                             font=(UI_FONT, 9, "bold"), padx=4, pady=1).place(
                        relx=0, rely=1.0, anchor="sw", x=4, y=-4)
                glyph = MEDIA_TYPE_GLYPHS.get(mtype, "image")
                tk.Label(card, image=ui_badge(glyph, 11, "#FFFFFF", "#000000", pad=3),
                         bg=UI_HEADER).place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)

            name = os.path.basename(f)
            if len(name) > 18:
                name = name[:15] + "..."
            ctk.CTkLabel(frame, text=name, text_color=UI_MUTED,
                         font=(UI_FONT, 10)).pack(padx=6, pady=(2, 5))

            # Bind drag & drop and menu events to the frame and all its children
            targets = [frame, card] + frame.winfo_children() + card.winfo_children()
            for target in targets:
                target.bind("<ButtonPress-1>", lambda e, idx=i: self.start_drag(e, idx))
                target.bind("<B1-Motion>", self.do_drag)
                target.bind("<ButtonRelease-1>", self.end_drag)
                target.bind("<Button-3>", lambda e, idx=i: self.show_media_menu(e, idx))

            col += 1
            if col >= cols:
                col = 0
                row += 1
    
    def start_drag(self, event, idx):
        if event.state & 0x0001 or event.state & 0x0004:
            if idx in self.selected_media_indices:
                self.selected_media_indices.remove(idx)
            else:
                self.selected_media_indices.append(idx)
        else:
            if idx not in self.selected_media_indices:
                self.selected_media_indices = [idx]
            self.select_media(idx)
            
        self.refresh_thumbnails()
        self.drag_data = {"x": event.x_root, "y": event.y_root, "indices": self.selected_media_indices}
        
        self.drag_window = tk.Toplevel(self.root)
        self.drag_window.wm_overrideredirect(True)
        self.drag_window.wm_attributes("-alpha", 0.7)
        
        for i, drag_idx in enumerate(self.selected_media_indices[:3]):
            thumb = self.thumbnails.get(self.media_files[drag_idx])
            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                lbl = tk.Label(self.drag_window, image=photo, bg="#2B2B2B")
                lbl.image = photo
                lbl.pack(side=tk.LEFT)
                
        if len(self.selected_media_indices) > 3:
            tk.Label(self.drag_window, text=f"+{len(self.selected_media_indices)-3}", bg="#2B2B2B", fg="white").pack(side=tk.LEFT)
            
        self.drag_window.geometry(f"+{event.x_root+10}+{event.y_root+10}")
        
    def do_drag(self, event):
        if hasattr(self, 'drag_window') and self.drag_window:
            self.drag_window.geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
    def end_drag(self, event):
        if hasattr(self, 'drag_window') and self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None
            
        x, y = self.root.winfo_pointerxy()
        widget = self.root.winfo_containing(x, y)
        
        if widget == self.tl_canvas:
            rel_x = x - self.tl_canvas.winfo_rootx()
            if rel_x >= 100:
                time_sec = max(0, (rel_x - 100) / self.pixels_per_second)
                rel_y = y - self.tl_canvas.winfo_rooty()
                track_idx = max(0, int((rel_y - 20) / 60))
                
                curr_time = time_sec
                for idx in self.drag_data.get("indices", []):
                    filepath = self.media_files[idx]
                    mtype = self.media_types[idx]
                    clip = TimelineClip(filepath, curr_time, 5, mtype, track_idx)
                    self.timeline_clips.append(clip)
                    curr_time += 5
                    
                self.draw_timeline_clips()
                
    def show_media_menu(self, event, idx):
        filepath = self.media_files[idx]
        mtype = self.media_types[idx]
        
        menu = tk.Menu(self.root, tearoff=0, bg="#2B2B2B", fg="white", font=("Segoe UI", 10))
        
        # Add to timeline
        menu.add_command(label="Add to Timeline", command=lambda: self.add_to_timeline_by_idx(idx))
        
        if mtype == "video":
            menu.add_separator()
            
            audio_menu = tk.Menu(menu, tearoff=0, bg="#2B2B2B", fg="white", font=("Segoe UI", 10))
            audio_menu.add_command(label="Xoá nhạc nền (giữ giọng nói)", command=lambda: self.remove_video_audio(idx, filepath, "isolate"))
            audio_menu.add_command(label="Xoá toàn bộ audio", command=lambda: self.remove_video_audio(idx, filepath, "remove"))
            audio_menu.add_command(label="Thay thế nhạc nền", command=lambda: self.replace_video_audio(idx, filepath))
            
            menu.add_cascade(label="🎵 Remove Audio", menu=audio_menu)
            
            logo_menu = tk.Menu(menu, tearoff=0, bg="#2B2B2B", fg="white", font=("Segoe UI", 10))
            logo_menu.add_command(label="Tự động phát hiện logo", command=lambda: self.auto_detect_and_remove_logo(idx, filepath))
            logo_menu.add_separator()
            logo_menu.add_command(label="Cắt khung hình (Crop)", command=lambda: self.remove_logo(idx, filepath, "crop"))
            logo_menu.add_command(label="Làm mờ vùng chọn (Blur)", command=lambda: self.remove_logo(idx, filepath, "blur"))
            logo_menu.add_command(label="Chèn đè vật thể (Overlay)", command=lambda: self.remove_logo(idx, filepath, "overlay"))
            logo_menu.add_command(label="AI Xóa watermark (Smart)", command=lambda: self.remove_logo(idx, filepath, "ai"))
            
            menu.add_cascade(label="🖼️ Remove Logo/Watermark", menu=logo_menu)
            menu.add_command(label="Extract Thumbnails...", command=lambda: self.extract_thumbnails(idx, filepath))
            menu.add_command(label="Extract Audio", command=lambda: self.extract_audio(idx, filepath))
        
        menu.add_separator()
        menu.add_command(label="Rename", command=lambda: self.rename_media(idx))
        menu.add_command(label="Duplicate", command=lambda: self.duplicate_media(idx))
        menu.add_separator()
        menu.add_command(label="Open File Location", command=lambda: self.open_file_location(filepath))
        menu.add_command(label="Properties", command=lambda: self.show_properties(idx))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self.delete_media(idx))
        
        menu.post(event.x_root, event.y_root)
    
    def add_to_timeline_by_idx(self, idx):
        filepath = self.media_files[idx]
        mtype = self.media_types[idx]
        
        dur = self.get_media_duration(filepath, mtype)
        track_idx = 0 if mtype in ['video', 'image'] else 1 if mtype == 'text' else 2
        
        track_clips = [c for c in self.timeline_clips if c.track_idx == track_idx]
        start_time = max([c.start_time + c.duration for c in track_clips], default=0.0)
        
        clip = TimelineClip(filepath, start_time, dur, mtype, track_idx)
        self.timeline_clips.append(clip)
        self.draw_timeline_clips()
    
    def extract_thumbnails(self, idx, filepath):
        self._extract_idx = idx
        self._extract_filepath = filepath
        self._show_extract_dialog()
    
    def _show_extract_dialog(self):
        if not MOVIEPY_AVAILABLE:
            messagebox.showerror("Lỗi", "Cần moviepy để trích xuất thumbnails")
            return
        
        dialog = ctk.CTkToplevel()
        dialog.title("Trích xuất Thumbnails")
        dialog.geometry("450x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=430, height=530, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        content = scroll
        
        ctk.CTkLabel(content, text="Số lượng ảnh:", font=("Segoe UI", 14)).pack(pady=10)
        
        count_entry = ctk.CTkEntry(content, width=200, height=35, font=("Segoe UI", 14))
        count_entry.pack(pady=5)
        count_entry.insert(0, "10")
        
        ctk.CTkLabel(content, text="Chế độ:", font=("Segoe UI", 12)).pack(pady=5)
        mode_var = ctk.StringVar(value="even")
        ctk.CTkRadioButton(content, text="Đều đặn", variable=mode_var, value="even").pack(pady=2)
        ctk.CTkRadioButton(content, text="Ngẫu nhiên", variable=mode_var, value="random").pack(pady=2)
        
        ctk.CTkLabel(content, text="Chất lượng ảnh:", font=("Segoe UI", 12)).pack(pady=10)
        
        quality_var = ctk.StringVar(value="720p")
        quality_frame = ctk.CTkFrame(content, fg_color="transparent")
        quality_frame.pack(pady=5)
        
        high_quality_frame = ctk.CTkFrame(quality_frame, fg_color="transparent")
        high_quality_frame.pack(pady=2)
        ctk.CTkLabel(high_quality_frame, text="Cao:", text_color="#00AA55", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        ctk.CTkRadioButton(high_quality_frame, text="8K", variable=quality_var, value="8k", text_color="#00AA55").pack(side=tk.LEFT, padx=5)
        ctk.CTkRadioButton(high_quality_frame, text="4K", variable=quality_var, value="4k", text_color="#00AA55").pack(side=tk.LEFT, padx=5)
        ctk.CTkRadioButton(high_quality_frame, text="2K", variable=quality_var, value="2k", text_color="#00AA55").pack(side=tk.LEFT, padx=5)
        
        low_quality_frame = ctk.CTkFrame(quality_frame, fg_color="transparent")
        low_quality_frame.pack(pady=2)
        ctk.CTkLabel(low_quality_frame, text="Thấp:", text_color="#FFAA00", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        ctk.CTkRadioButton(low_quality_frame, text="1080p", variable=quality_var, value="1080p").pack(side=tk.LEFT, padx=5)
        ctk.CTkRadioButton(low_quality_frame, text="720p", variable=quality_var, value="720p").pack(side=tk.LEFT, padx=5)
        ctk.CTkRadioButton(low_quality_frame, text="480p", variable=quality_var, value="480p").pack(side=tk.LEFT, padx=5)
        
        pixel_frame = ctk.CTkFrame(quality_frame, fg_color="transparent")
        pixel_frame.pack(pady=2)
        ctk.CTkLabel(pixel_frame, text="Pixel:", text_color="#AA55FF", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        ctk.CTkRadioButton(pixel_frame, text="Pixel Art", variable=quality_var, value="pixel_art").pack(side=tk.LEFT, padx=5)
        ctk.CTkRadioButton(pixel_frame, text="Low-Res", variable=quality_var, value="low_res").pack(side=tk.LEFT, padx=5)
        
        ctk.CTkLabel(content, text="Thư mục lưu:", font=("Segoe UI", 12)).pack(pady=10)
        
        self._extract_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "thumbs")
        os.makedirs(self._extract_folder, exist_ok=True)
        
        folder_frame = ctk.CTkFrame(content, fg_color="transparent")
        folder_frame.pack(pady=5, fill=tk.X)
        folder_entry = ctk.CTkEntry(folder_frame, width=280)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        folder_entry.insert(0, self._extract_folder)
        ctk.CTkButton(folder_frame, text="...", width=30, command=lambda: self._browse_extract_folder(folder_entry)).pack(side=tk.LEFT, padx=5)
        
        self._progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._progress_label.pack(pady=5)
        
        self._progress_bar = ctk.CTkProgressBar(content, width=300, height=20, progress_color="#00AA55")
        self._progress_bar.pack(pady=10)
        self._progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_extract():
            try:
                count = int(count_entry.get())
                if count <= 0:
                    raise ValueError
            except:
                messagebox.showerror("Lỗi", "Số lượng phải là số nguyên dương")
                return
            
            self._extract_folder = folder_entry.get()
            os.makedirs(self._extract_folder, exist_ok=True)
            
            mode = mode_var.get()
            quality = quality_var.get()
            self._do_extract_thumbnails(self._extract_idx, self._extract_filepath, count, mode, quality, dialog)
        
        ctk.CTkButton(btn_frame, text="Tách", fg_color="#00AA55", width=80, command=do_extract).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _browse_extract_folder(self, entry):
        folder = filedialog.askdirectory(initialdir=self._extract_folder)
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
    
    def _do_extract_thumbnails(self, idx, filepath, count, mode, quality, dialog):
        quality_sizes = {
            "8k": (3840, 2160),
            "4k": (2560, 1440),
            "2k": (1920, 1080),
            "1080p": (1920, 1080),
            "720p": (1280, 720),
            "480p": (854, 480),
            "pixel_art": (64, 64),
            "low_res": (160, 90),
        }
        
        target_size = quality_sizes.get(quality, (1280, 720))
        
        try:
            clip = MOVIEPY['VideoFileClip'](filepath)
            duration = clip.duration
            
            if mode == "random":
                import random
                times = sorted(random.sample([i * duration / count for i in range(count)], count))
            else:
                times = [i * duration / count for i in range(count)]
            
            os.makedirs(self._extract_folder, exist_ok=True)
            
            for i, t in enumerate(times):
                self._progress_bar.set((i + 1) / count)
                self._progress_label.configure(text=f"Đang xử lý... {i+1}/{count}")
                self._progress_label.update_idletasks()
                
                frame = clip.get_frame(t)
                if isinstance(frame, np.ndarray):
                    frame = Image.fromarray(frame)
                
                if quality == "pixel_art":
                    frame = frame.resize((16, 16), Image.NEAREST)
                    frame = frame.resize(target_size, Image.NEAREST)
                elif quality == "low_res":
                    small = frame.resize((80, 45), Image.NEAREST)
                    frame = small.resize(target_size, Image.NEAREST)
                else:
                    frame.thumbnail(target_size)
                
                safe_name = os.path.splitext(os.path.basename(filepath))[0]
                out_path = os.path.join(self._extract_folder, f"{safe_name}_t{i+1:03d}.jpg")
                frame_rgb = frame.convert("RGB")
                frame_rgb.save(out_path, "JPEG", quality=95 if quality in ["8k", "4k", "2k", "1080p"] else 85)
            
            clip.close()
            
            self._extracted_thumbnails_dir = self._extract_folder
            self._show_extracted_thumbnails(self._extract_folder)
            
            self._progress_label.configure(text="Hoàn tất!")
            messagebox.showinfo("Thành công", f"Đã tách {count} thumbnails!\nChất lượng: {quality}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tách thumbnails:\n{str(e)}")
    
    def _show_extracted_thumbnails(self, folder):
        thumbs_win = ctk.CTkToplevel()
        thumbs_win.title("Thumbnails đã tách")
        thumbs_win.geometry("700x500")
        
        header = ctk.CTkFrame(thumbs_win, height=40)
        header.pack(fill=tk.X, padx=10, pady=5)
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="Thumbnails", font=("Segoe UI", 14)).pack(side=tk.LEFT)
        ctk.CTkButton(header, text="Tải xuống", fg_color="#00AA55", width=80, command=self._download_thumbnails).pack(side=tk.RIGHT, padx=5)
        ctk.CTkButton(header, text="Mở thư mục", fg_color="#2B2B2B", width=80, command=lambda: os.startfile(folder)).pack(side=tk.RIGHT)
        
        scroll = ctk.CTkScrollableFrame(thumbs_win, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        files = [f for f in os.listdir(folder) if f.endswith('.jpg') or f.endswith('.png')]
        files.sort()
        
        row, col = 0, 0
        for fname in files:
            fpath = os.path.join(folder, fname)
            try:
                img = Image.open(fpath)
                img.thumbnail((100, 60))
                photo = ImageTk.PhotoImage(img)
                
                frame = ctk.CTkFrame(scroll, fg_color="#2B2B2B", width=110, height=80, corner_radius=4)
                frame.grid(row=row, column=col, padx=5, pady=5)
                frame.grid_propagate(False)
                
                lbl = tk.Label(frame, image=photo, bg="#2B2B2B", cursor="hand2")
                lbl.image = photo
                lbl.pack(padx=2, pady=2)
                lbl.bind("<Button-3>", lambda e, fp=fpath: self._show_thumb_menu(e, fp))
                
                ctk.CTkLabel(frame, text=fname[:12], text_color="#888", font=("Segoe UI", 7)).pack(pady=2)
            except:
                pass
            
            col += 1
            if col >= 6:
                col = 0
                row += 1
    
    def _show_thumb_menu(self, event, filepath):
        menu = tk.Menu(self.root, tearoff=0, bg="#2B2B2B", fg="white")
        menu.add_command(label="Tải xuống", command=lambda: self._save_thumbnail(filepath))
        menu.add_command(label="Mở thư mục chứa", command=lambda: os.startfile(os.path.dirname(filepath)))
        menu.post(event.x_root, event.y_root)
    
    def _save_thumbnail(self, filepath):
        save_path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            initialfile=os.path.basename(filepath),
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")]
        )
        if save_path:
            import shutil
            shutil.copy(filepath, save_path)
            messagebox.showinfo("Đã lưu", f"Đã lưu vào:\n{save_path}")
    
    def _download_thumbnails(self):
        folder = getattr(self, '_extracted_thumbnails_dir', '')
        if folder and os.path.exists(folder):
            files = [f for f in os.listdir(folder) if f.endswith('.jpg') or f.endswith('.png')]
            if files:
                os.startfile(folder)
    
    def extract_audio(self, idx, filepath):
        self._audio_idx = idx
        self._audio_filepath = filepath
        self._show_extract_audio_dialog()
    
    def _show_extract_audio_dialog(self):
        if not MOVIEPY_AVAILABLE:
            messagebox.showerror("Lỗi", "Cần moviepy để trích xuất audio")
            return
        
        dialog = ctk.CTkToplevel()
        dialog.title("Trích xuất Audio")
        dialog.geometry("450x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=430, height=380, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        content = scroll
        
        ctk.CTkLabel(content, text="Trích xuất Audio từ Video", font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Tệp gốc:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._audio_filepath), text_color="white", font=("Segoe UI", 11)).pack(pady=2)
        
        ctk.CTkLabel(content, text="Định dạng:", font=("Segoe UI", 12)).pack(pady=10)
        
        format_var = ctk.StringVar(value="mp3")
        format_frame = ctk.CTkFrame(content, fg_color="transparent")
        format_frame.pack(pady=5)
        ctk.CTkRadioButton(format_frame, text="MP3", variable=format_var, value="mp3").pack(side=tk.LEFT, padx=10)
        ctk.CTkRadioButton(format_frame, text="WAV", variable=format_var, value="wav").pack(side=tk.LEFT, padx=10)
        ctk.CTkRadioButton(format_frame, text="AAC", variable=format_var, value="aac").pack(side=tk.LEFT, padx=10)
        
        ctk.CTkLabel(content, text="Chất lượng:", font=("Segoe UI", 12)).pack(pady=10)
        
        quality_var = ctk.StringVar(value="320")
        quality_frame = ctk.CTkFrame(content, fg_color="transparent")
        quality_frame.pack(pady=5)
        ctk.CTkLabel(quality_frame, text="MP3:", text_color="#00AA55").pack(side=tk.LEFT)
        for q in ["320", "192", "128", "96"]:
            ctk.CTkRadioButton(quality_frame, text=f"{q}kbps", variable=quality_var, value=q).pack(side=tk.LEFT, padx=3)
        
        ctk.CTkLabel(content, text="Thư mục lưu:", font=("Segoe UI", 12)).pack(pady=10)
        
        self._audio_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audio")
        os.makedirs(self._audio_folder, exist_ok=True)
        
        folder_frame = ctk.CTkFrame(content, fg_color="transparent")
        folder_frame.pack(pady=5, fill=tk.X)
        folder_entry = ctk.CTkEntry(folder_frame, width=280)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        folder_entry.insert(0, self._audio_folder)
        ctk.CTkButton(folder_frame, text="...", width=30, command=lambda: self._browse_audio_folder(folder_entry)).pack(side=tk.LEFT, padx=5)
        
        self._audio_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._audio_progress_label.pack(pady=5)
        
        self._audio_progress_bar = ctk.CTkProgressBar(content, width=300, height=20, progress_color="#00AA55")
        self._audio_progress_bar.pack(pady=10)
        self._audio_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_extract():
            self._audio_folder = folder_entry.get()
            os.makedirs(self._audio_folder, exist_ok=True)
            format_val = format_var.get()
            quality_val = quality_var.get()
            self._do_extract_audio(self._audio_idx, self._audio_filepath, format_val, quality_val, dialog)
        
        ctk.CTkButton(btn_frame, text="Trích xuất", fg_color="#00AA55", width=100, command=do_extract).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _browse_audio_folder(self, entry):
        folder = filedialog.askdirectory(initialdir=self._audio_folder)
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
    
    def _do_extract_audio(self, idx, filepath, format_val, quality_val, dialog):
        try:
            self._audio_progress_label.configure(text="Đang xử lý...")
            self._audio_progress_bar.set(0.1)
            self._audio_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](filepath)
            
            self._audio_progress_bar.set(0.3)
            self._audio_progress_label.configure(text="Đang trích âm thanh...")
            self._audio_progress_label.update_idletasks()
            
            if clip.audio is None:
                messagebox.showerror("Lỗi", "Video không có audio!")
                clip.close()
                return
            
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            
            if format_val == "wav":
                ext = "wav"
                out_path = os.path.join(self._audio_folder, f"{base_name}_audio.{ext}")
                clip.audio.write_audiofile(out_path, codec='pcm_s16le')
            elif format_val == "aac":
                ext = "m4a"
                out_path = os.path.join(self._audio_folder, f"{base_name}_audio.{ext}")
                clip.audio.write_audiofile(out_path, codec='aac', audio_fps=44100)
            else:
                ext = "mp3"
                out_path = os.path.join(self._audio_folder, f"{base_name}_audio.{ext}")
                clip.audio.write_audiofile(out_path, codec='mp3', bitrate=f'{quality_val}k')
            
            self._audio_progress_bar.set(0.9)
            self._audio_progress_label.configure(text="Hoàn tất!")
            self._audio_progress_label.update_idletasks()
            
            clip.close()
            
            self._audio_progress_bar.set(1.0)
            messagebox.showinfo("Thành công", f"Đã trích xuất audio!\nLưu tại:\n{out_path}")
            dialog.destroy()
            
            os.startfile(self._audio_folder)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể trích xuất audio:\n{str(e)}")
    
    def rename_media(self, idx):
        current_name = os.path.basename(self.media_files[idx])
        # Simple rename - just show message for now
        messagebox.showinfo("Rename", f"Rename: {current_name}")
    
    def duplicate_media(self, idx):
        filepath = self.media_files[idx]
        mtype = self.media_types[idx]
        
        self.media_files.append(filepath)
        self.media_types.append(mtype)
        self.generate_thumbnail(filepath)
        self.refresh_thumbnails()
        messagebox.showinfo("Duplicated", "Media duplicated")
    
    def remove_video_audio(self, idx, filepath, mode):
        self._remove_idx = idx
        self._remove_filepath = filepath
        self._remove_mode = mode
        self._show_remove_audio_dialog()
    
    def _show_remove_audio_dialog(self):
        dialog = ctk.CTkToplevel()
        dialog.title("Xoá Audio khỏi Video")
        dialog.geometry("450x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=430, height=380, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        mode_text = "Xoá nhạc nền (giữ lại giọng nói)" if self._remove_mode == "isolate" else "Xoá toàn bộ audio"
        ctk.CTkLabel(content, text=mode_text, font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Tệp gốc:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._remove_filepath), text_color="white", font=("Segoe UI", 11)).pack(pady=2)
        
        if self._remove_mode == "isolate":
            ctk.CTkLabel(content, text="Các thành phần audio có thể tách:", text_color="#00AA55", font=("Segoe UI", 12)).pack(pady=10)
            
            components_frame = ctk.CTkFrame(content, fg_color="transparent")
            components_frame.pack(pady=5)
            
            self._isolate_drums = ctk.CTkCheckBox(components_frame, text="🎸 Trống (Drums)", checkbox_width=20, checkbox_height=20).pack(pady=2)
            self._isolate_drums.select()
            self._isolate_bass = ctk.CTkCheckBox(components_frame, text="🎸 Bass", checkbox_width=20, checkbox_height=20).pack(pady=2)
            self._isolate_bass.select()
            self._isolate_other = ctk.CTkCheckBox(components_frame, text="🎵 Nhạc nền (Other)", checkbox_width=20, checkbox_height=20).pack(pady=2)
            self._isolate_other.select()
            self._isolate_vocals = ctk.CTkCheckBox(components_frame, text="🎤 Giọng nói (Vocals)", checkbox_width=20, checkbox_height=20).pack(pady=2)
            self._isolate_vocals.select()
            
            ctk.CTkLabel(content, text="Model AI:", font=("Segoe UI", 12)).pack(pady=10)
            
            self._ai_model = ctk.StringVar(value="htdemucs")
            model_frame = ctk.CTkFrame(content, fg_color="transparent")
            model_frame.pack(pady=5)
            ctk.CTkRadioButton(model_frame, text="Demucs (UVR)", variable=self._ai_model, value="htdemucs").pack(side=tk.LEFT, padx=5)
            ctk.CTkRadioButton(model_frame, text="MDX", variable=self._ai_model, value="mdx").pack(side=tk.LEFT, padx=5)
            
            ctk.CTkLabel(content, text="⚠️ Yêu cầu cài đặt: pip install demucs", text_color="#FFAA00", font=("Segoe UI", 10)).pack(pady=5)
        else:
            ctk.CTkLabel(content, text="⚠️ Video mới sẽ xoá toàn bộ audio", text_color="#FFAA00", font=("Segoe UI", 10)).pack(pady=10)
        
        output_frame = ctk.CTkFrame(content, fg_color="transparent")
        output_frame.pack(pady=10, fill=tk.X)
        ctk.CTkLabel(output_frame, text="Thư mục lưu:", font=("Segoe UI", 11)).pack(side=tk.LEFT)
        
        self._remove_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._remove_progress_label.pack(pady=10)
        
        self._remove_progress_bar = ctk.CTkProgressBar(content, width=300, height=20, progress_color="#00AA55")
        self._remove_progress_bar.pack(pady=10)
        self._remove_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_remove():
            self._do_remove_video_audio(dialog)
        
        ctk.CTkButton(btn_frame, text="Xử lý", fg_color="#00AA55", width=100, command=do_remove).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _do_remove_video_audio(self, dialog):
        try:
            self._remove_progress_label.configure(text="Đang chuẩn bị...")
            self._remove_progress_label.update_idletasks()
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(self._remove_filepath))[0]
            
            if self._remove_mode == "isolate":
                self._do_ai_audio_separation(dialog, base_name, output_dir)
            else:
                self._do_simple_audio_removal(dialog, base_name, output_dir)
                
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xoá audio:\n{str(e)}")
    
    def _do_simple_audio_removal(self, dialog, base_name, output_dir):
        try:
            self._remove_progress_label.configure(text="Đang xử lý...")
            self._remove_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._remove_filepath)
            self._remove_progress_bar.set(0.3)
            self._remove_progress_label.configure(text="Đang xuất video...")
            self._remove_progress_label.update_idletasks()
            
            out_path = os.path.join(output_dir, f"{base_name}_no_audio.mp4")
            new_clip = clip.without_audio()
            new_clip.write_videofile(out_path, codec='libx264', audio=False, logger=None)
            
            self._remove_progress_bar.set(0.9)
            self._remove_progress_label.configure(text="Hoàn tất!")
            self._remove_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._remove_progress_bar.set(1.0)
            self._add_processed_video(out_path)
            messagebox.showinfo("Thành công", f"Đã xoá audio!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xoá audio:\n{str(e)}")
    
    def _do_ai_audio_separation(self, dialog, base_name, output_dir):
        import subprocess
        import shutil
        
        ffmpeg_path = find_ffmpeg()
        
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                ffmpeg_path = path
                break
        
        if not ffmpeg_path:
            messagebox.showerror("Lỗi", "Cần ffmpeg để xử lý audio.\nVui lòng cài đặt ffmpeg.")
            return
        
        try:
            self._remove_progress_label.configure(text="Đang trích audio từ video...")
            self._remove_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._remove_filepath)
            
            if clip.audio is None:
                messagebox.showerror("Lỗi", "Video không có audio để tách!")
                clip.close()
                return
            
            self._remove_progress_bar.set(0.1)
            self._remove_progress_label.configure(text="Đang xuất audio...")
            self._remove_progress_label.update_idletasks()
            
            temp_audio = os.path.join(output_dir, f"{base_name}_temp_audio.wav")
            clip.audio.write_audiofile(temp_audio, codec='pcm_s16le')
            
            self._remove_progress_bar.set(0.2)
            self._remove_progress_label.configure(text="Đang khởi tạo mô hình Demucs...")
            self._remove_progress_label.update_idletasks()
            
            try:
                from demucs.separate import separate
                from demucs.hdemucs import HDemucsModel
                import torch
                
                model_name = self._ai_model.get()
                
                self._remove_progress_label.configure(text=f"Đang tải model {model_name}...")
                self._remove_progress_label.update_idletasks()
                
                separator = separate.Separator(model=model_name, device='cuda' if torch.cuda.is_available() else 'cpu')
                
                self._remove_progress_bar.set(0.3)
                self._remove_progress_label.configure(text="Đang tách audio bằng AI...")
                self._remove_progress_label.update_idletasks()
                
                separated = separator.separate_audio_file(temp_audio)
                
                self._remove_progress_bar.set(0.7)
                self._remove_progress_label.configure(text="Đang ghép video với audio đã x�� lý...")
                self._remove_progress_label.update_idletasks()
                
                keep_drums = not bool(self._isolate_drums.get())
                keep_bass = not bool(self._isolate_bass.get())
                keep_other = not bool(self._isolate_other.get())
                keep_vocals = bool(self._isolate_vocals.get())
                
                stems_dir = os.path.join(output_dir, "separated", base_name)
                
                final_audio_path = self._mix_separated_stems(stems_dir, keep_drums, keep_bass, keep_other, keep_vocals, output_dir)
                
                import subprocess
                import shutil
                ffmpeg_path = find_ffmpeg()
                
                video_clip = clip.without_video()
                
                temp_output = os.path.join(output_dir, f"{base_name}_temp.mp4")
                video_clip.write_videofile(temp_output, codec='libx264', logger=None, preset='ultrafast')
                video_clip.close()
                
                out_path = os.path.join(output_dir, f"{base_name}_isolated.mp4")
                cmd = [ffmpeg_path, "-y", "-i", temp_output, "-i", final_audio_path, "-c", "v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", out_path]
                subprocess.run(cmd, capture_output=True)
                os.remove(temp_output)
                
                os.remove(final_audio_path)
                
                self._remove_progress_bar.set(0.9)
                self._remove_progress_label.configure(text="Hoàn tất!")
                self._remove_progress_label.update_idletasks()
                
                self._remove_progress_bar.set(1.0)
                self._add_processed_video(out_path)
                messagebox.showinfo("Thành công", f"Đã tách audio!\nLưu tại:\n{out_path}")
                dialog.destroy()
                
            except ImportError:
                messagebox.showinfo("Thông báo", "Demucs chưa được cài đặt.\nSử dụng lệnh: pip install demucs\n\nSẽ xoá toàn bộ audio thay thế.")
                clip.close()
                out_path = os.path.join(output_dir, f"{base_name}_no_audio.mp4")
                video_clip = MOVIEPY['VideoFileClip'](self._remove_filepath)
                new_clip = video_clip.without_audio()
                new_clip.write_videofile(out_path, codec='libx264', audio=False, logger=None)
                video_clip.close()
                new_clip.close()
                self._remove_progress_bar.set(1.0)
                self._add_processed_video(out_path)
                messagebox.showinfo("Thành công", f"Đã xoá audio!\nLưu tại:\n{out_path}")
                dialog.destroy()
                
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tách audio:\n{str(e)}")
    
    def _mix_separated_stems(self, stems_dir, keep_drums, keep_bass, keep_other, keep_vocals, output_dir):
        import numpy as np
        
        drums_path = os.path.join(stems_dir, "drums.wav")
        bass_path = os.path.join(stems_dir, "bass.wav")
        other_path = os.path.join(stems_dir, "other.wav")
        vocals_path = os.path.join(stems_dir, "vocals.wav")
        
        max_len = 0
        components = []
        
        if not keep_drums and os.path.exists(drums_path):
            import soundfile as sf
            drums_data, sr = sf.read(drums_path)
            max_len = max(max_len, len(drums_data))
            components.append(drums_data)
        
        if not keep_bass and os.path.exists(bass_path):
            import soundfile as sf
            bass_data, sr = sf.read(bass_path)
            max_len = max(max_len, len(bass_data))
            components.append(bass_data)
        
        if not keep_other and os.path.exists(other_path):
            import soundfile as sf
            other_data, sr = sf.read(other_path)
            max_len = max(max_len, len(other_data))
            components.append(other_data)
        
        if keep_vocals and os.path.exists(vocals_path):
            import soundfile as sf
            vocals_data, sr = sf.read(vocals_path)
            max_len = max(max_len, len(vocals_data))
            components.append(vocals_data)
        
        if not components:
            messagebox.showwarning("Cảnh báo", "Không có thành phần nào được giữ lại!")
            return None
        
        result = np.zeros(max_len)
        for comp in components:
            if len(comp) < max_len:
                comp = np.pad(comp, (0, max_len - len(comp)))
            result += comp
        
        result = result / len(components) if len(components) > 1 else result
        
        out_path = os.path.join(output_dir, "final_mix.wav")
        import soundfile as sf
        sf.write(out_path, result, sr)
        
        return out_path
    
    def _add_processed_video(self, video_path):
        if os.path.exists(video_path):
            self.media_files.append(video_path)
            self.media_types.append("video")
            self.generate_thumbnail(video_path)
            self.refresh_thumbnails()
    
    def _do_remove_video_audio(self, dialog):
        try:
            self._remove_progress_label.configure(text="Đang xử lý...")
            self._remove_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._remove_filepath)
            
            self._remove_progress_bar.set(0.3)
            self._remove_progress_label.configure(text="Đang xoá audio...")
            self._remove_progress_label.update_idletasks()
            
            if self._remove_mode == "isolate":
                messagebox.showinfo("Thông báo", "Chế độ 'Xoá nhạc nền, giữ giọng nói' yêu cầu mô hình AI.\nVui lòng sử dụng mô hình Demucs để xử lý.\nHiện tại sẽ xoá toàn bộ audio.")
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(self._remove_filepath))[0]
            out_path = os.path.join(output_dir, f"{base_name}_no_audio.mp4")
            
            self._remove_progress_bar.set(0.6)
            self._remove_progress_label.configure(text="Đang xuất video...")
            self._remove_progress_label.update_idletasks()
            
            new_clip = clip.without_audio()
            new_clip.write_videofile(out_path, codec='libx264', audio=False, logger=None)
            
            self._remove_progress_bar.set(0.9)
            self._remove_progress_label.configure(text="Hoàn tất!")
            self._remove_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._remove_progress_bar.set(1.0)
            
            self.media_files.append(out_path)
            self.media_types.append("video")
            self.generate_thumbnail(out_path)
            self.refresh_thumbnails()
            
            messagebox.showinfo("Thành công", f"Đã xoá audio!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xoá audio:\n{str(e)}")
    
    def replace_video_audio(self, idx, filepath):
        audio_file = filedialog.askopenfilename(
            title="Chọn file audio thay thế",
            filetypes=[("Audio", "*.mp3 *.wav *.aac *.m4a *.flac *.ogg")]
        )
        if audio_file:
            self._replace_idx = idx
            self._replace_filepath = filepath
            self._replace_audio_file = audio_file
            self._show_replace_audio_dialog()
    
    def _show_replace_audio_dialog(self):
        dialog = ctk.CTkToplevel()
        dialog.title("Thay thế Audio")
        dialog.geometry("450x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=430, height=280, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        ctk.CTkLabel(content, text="Thay thế Audio", font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Video gốc:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._replace_filepath), text_color="white", font=("Segoe UI", 11)).pack(pady=2)
        
        ctk.CTkLabel(content, text="Audio mới:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._replace_audio_file), text_color="#00AA55", font=("Segoe UI", 11)).pack(pady=2)
        
        ctk.CTkLabel(content, text="Chú ý: Cắt audio theo độ dài video", text_color="#FFAA00", font=("Segoe UI", 10)).pack(pady=10)
        
        self._replace_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._replace_progress_label.pack(pady=10)
        
        self._replace_progress_bar = ctk.CTkProgressBar(content, width=300, height=20, progress_color="#00AA55")
        self._replace_progress_bar.pack(pady=10)
        self._replace_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_replace():
            self._do_replace_video_audio(dialog)
        
        ctk.CTkButton(btn_frame, text="Xử lý", fg_color="#00AA55", width=100, command=do_replace).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _do_replace_video_audio(self, dialog):
        import subprocess
        import shutil
        import os
        import re
        
        ffmpeg_path = find_ffmpeg()
        
        if not ffmpeg_path:
            common_paths = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"),
            ]
            for path in common_paths:
                if os.path.exists(path):
                    ffmpeg_path = path
                    break
        
        if not ffmpeg_path or not shutil.which("ffmpeg"):
            messagebox.showerror("Lỗi", "Cần ffmpeg để thay audio.\nVui lòng cài đặt ffmpeg và thêm vào PATH.")
            return
        
        try:
            self._replace_progress_label.configure(text="Đang xử lý...")
            self._replace_progress_label.update_idletasks()
            
            video_path = self._replace_filepath
            audio_path = self._replace_audio_file
            
            self._replace_progress_bar.set(0.3)
            self._replace_progress_label.configure(text="Đang ghép audio...")
            self._replace_progress_label.update_idletasks()
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            out_path = os.path.join(output_dir, f"{base_name}_new_audio.mp4")
            
            self._replace_progress_bar.set(0.6)
            self._replace_progress_label.configure(text="Đang xuất video...")
            self._replace_progress_label.update_idletasks()
            
            cmd = [ffmpeg_path, "-y", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", out_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                messagebox.showerror("Lỗi", f"Không thể thay audio:\n{error_msg[:500]}")
                return
            
            self._replace_progress_bar.set(0.9)
            self._replace_progress_label.configure(text="Hoàn tất!")
            self._replace_progress_label.update_idletasks()
            
            self._replace_progress_bar.set(1.0)
            
            self.media_files.append(out_path)
            self.media_types.append("video")
            self.generate_thumbnail(out_path)
            self.refresh_thumbnails()
            
            messagebox.showinfo("Thành công", f"Đã thay thế audio!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể thay thế audio:\n{str(e)}")
    
    def remove_logo(self, idx, filepath, mode):
        self._logo_idx = idx
        self._logo_filepath = filepath
        self._logo_mode = mode
        self._show_remove_logo_dialog()
    
    def auto_detect_and_remove_logo(self, idx, filepath):
        """Tự động phát hiện và xóa logo/watermark"""
        self._logo_idx = idx
        self._logo_filepath = filepath
        
        dialog = ctk.CTkToplevel()
        dialog.title("Tự động phát hiện Logo")
        dialog.geometry("500x450")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=480, height=430, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        ctk.CTkLabel(content, text="Tự động phát hiện Logo", font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Đang phân tích video...", text_color="#00AA55", font=("Segoe UI", 12)).pack(pady=10)
        
        self._auto_progress_bar = ctk.CTkProgressBar(content, width=350, height=20, progress_color="#00AA55")
        self._auto_progress_bar.pack(pady=10)
        self._auto_progress_bar.set(0)
        
        self._auto_status = ctk.CTkLabel(content, text="", text_color="#888")
        self._auto_status.pack(pady=5)
        
        def do_detect():
            try:
                self._auto_progress_bar.set(0.1)
                self._auto_status.configure(text="Đang đọc video...")
                self._auto_status.update_idletasks()
                
                result = self.detect_watermark_auto(filepath)
                
                if result:
                    x1, y1, x2, y2 = result
                    self._logo_x = x1
                    self._logo_y = y1
                    self._logo_w = x2 - x1
                    self._logo_h = y2 - y1
                    
                    self._auto_progress_bar.set(0.5)
                    self._auto_status.configure(text=f"Phát hiện: X={x1}, Y={y1}, W={self._logo_w}, H={self._logo_h}")
                    self._auto_status.update_idletasks()
                    
                    self._show_auto_confirm_dialog(dialog, result)
                else:
                    messagebox.showinfo("Thông báo", "Không tìm thấy logo tự động.\nVui lòng chọn vùng thủ công.")
                    dialog.destroy()
                    self.remove_logo(idx, filepath, "ai")
                    
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể phát hiện:\n{str(e)}")
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_split():
            import threading
            import subprocess
            import shutil
            
            dialog.destroy()
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audio")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(clip.file_path))[0]
            ext = os.path.splitext(clip.file_path)[1] or ".mp3"
            
            part1_path = os.path.join(output_dir, f"{base_name}_p1{ext}")
            part2_path = os.path.join(output_dir, f"{base_name}_p2{ext}")
            
            progress_win = ctk.CTkToplevel()
            progress_win.title("Đang cắt audio")
            progress_win.geometry("400x150")
            progress_win.transient(self.root)
            progress_win.grab_set()
            
            lbl = ctk.CTkLabel(progress_win, text="Đang cắt audio...", text_color="white", font=("Segoe UI", 14))
            lbl.pack(pady=20)
            progress_bar = ctk.CTkProgressBar(progress_win, width=300)
            progress_bar.pack(pady=10)
            progress_bar.set(0)
            status_lbl = ctk.CTkLabel(progress_win, text="Đang khởi tạo...", text_color="#888")
            status_lbl.pack(pady=5)
            btn_frame2 = ctk.CTkFrame(progress_win, fg_color="transparent")
            btn_frame2.pack(pady=10)
            paused = [False]
            cancelled = [False]
            
            def toggle_pause():
                paused[0] = not paused[0]
                pause_btn.configure(text="▶ Tiếp tục" if paused[0] else "⏸ Tạm dừng")
            
            def cancel_cut():
                cancelled[0] = True
                progress_win.destroy()
                messagebox.showinfo("Huỷ", "Đã huỷ tác vụ cắt audio")
            
            ffmpeg_path = find_ffmpeg()
            
            pause_btn = ctk.CTkButton(btn_frame2, text="⏸ Tạm dừng", fg_color="#FF9800", text_color="white", width=120, command=toggle_pause)
            pause_btn.pack(side=tk.LEFT, padx=10)
            ctk.CTkButton(btn_frame2, text="⏹ Huỷ", fg_color="#F44336", text_color="white", width=80, command=cancel_cut).pack(side=tk.LEFT, padx=10)
            ctk.CTkButton(btn_frame2, text="📥 Chạy nền", fg_color="#333", text_color="white", width=100, command=progress_win.destroy).pack(side=tk.LEFT, padx=10)
            
            progress_win.update()
            
            def run_in_background():
                import time as time_module
                try:
                    status_lbl.configure(text="Đang xuất phần 1...")
                    progress_win.update()
                    
                    while paused[0] and not cancelled[0]:
                        time_module.sleep(0.2)
                    
                    if cancelled[0]:
                        return
                    
                    cmd1 = [ffmpeg_path, "-y", "-i", clip.file_path, "-ss", "0", "-to", str(local_cut), "-c", "copy", part1_path]
                    subprocess.run(cmd1, capture_output=True)
                    progress_bar.set(0.2)
                    progress_win.update()
                    
                    while paused[0]:
                        time_module.sleep(0.2)
                    
                    status_lbl.configure(text="Đang xuất phần 2...")
                    
                    if cancelled[0]:
                        return
                    
                    total_dur = clip.duration
                    cmd2 = [ffmpeg_path, "-y", "-i", clip.file_path, "-ss", str(local_cut), "-to", str(total_dur), "-c", "copy", part2_path]
                    subprocess.run(cmd2, capture_output=True)
                    
                    progress_bar.set(1.0)
                    status_lbl.configure(text="Hoàn tất!")
                    progress_win.update()
                    time_module.sleep(1)
                    
                    clip.file_path = part1_path
                    clip.duration = local_cut
                    
                    clip2 = TimelineClip(
                        part2_path,
                        cut_time,
                        self.get_total_duration() - cut_time,
                        clip.clip_type,
                        clip.track_idx
                    )
                    self.timeline_clips.append(clip2)
                    
                    self.media_files.append(part1_path)
                    self.media_files.append(part2_path)
                    self.media_types.append("audio")
                    self.media_types.append("audio")
                    
                    self.draw_timeline_clips()
                    
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    
                    messagebox.showinfo("Thành công", f"Đã cắt audio!\n\nPhần 1: {part1_path}\nPhần 2: {part2_path}")
                    
                except Exception as e:
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    messagebox.showerror("Lỗi", f"Không thể cắt audio: {str(e)}")
            
            threading.Thread(target=run_in_background, daemon=True).start()
        
        ctk.CTkButton(btn_frame, text="Cắt", fg_color="#00AA55", width=80, command=do_split).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _show_auto_confirm_dialog(self, parent_dialog, logo_region):
        x1, y1, x2, y2 = logo_region
        
        confirm = ctk.CTkToplevel()
        confirm.title("Xác nhận vùng Logo")
        confirm.geometry("500x500")
        confirm.transient(self.root)
        confirm.grab_set()
        
        scroll = ctk.CTkScrollableFrame(confirm, width=480, height=480, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        ctk.CTkLabel(content, text="Đã phát hiện vùng logo:", font=("Segoe UI", 14, "bold"), text_color="#00AA55").pack(pady=10)
        
        info_frame = ctk.CTkFrame(content, fg_color="transparent")
        info_frame.pack(pady=10)
        ctk.CTkLabel(info_frame, text=f"X: {x1}").pack(pady=2)
        ctk.CTkLabel(info_frame, text=f"Y: {y1}").pack(pady=2)
        ctk.CTkLabel(info_frame, text=f"Rộng: {x2-x1}").pack(pady=2)
        ctk.CTkLabel(info_frame, text=f"Cao: {y2-y1}").pack(pady=2)
        
        try:
            clip = MOVIEPY['VideoFileClip'](self._logo_filepath)
            preview_frame = clip.get_frame(0)
            clip.close()
            
            if isinstance(preview_frame, np.ndarray):
                img = Image.fromarray(preview_frame)
            else:
                img = preview_frame
            
            img_h = 200
            aspect = img.width / img.height if img.height > 0 else 1
            img_w = int(img_h * aspect)
            img.thumbnail((img_w, img_h))
            
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
            
            preview_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img_w, img_h))
            ctk.CTkLabel(content, image=preview_photo, text="").pack(pady=10)
        except Exception as e:
            print(f"Preview error: {e}")
        
        ctk.CTkLabel(content, text="Chọn phương pháp xóa:", font=("Segoe UI", 12)).pack(pady=10)
        
        method_frame = ctk.CTkFrame(content, fg_color="transparent")
        method_frame.pack(pady=10)
        self._remove_method = ctk.StringVar(value="ai")
        ctk.CTkRadioButton(method_frame, text="AI Smart Inpaint", variable=self._remove_method, value="ai").pack(pady=2)
        ctk.CTkRadioButton(method_frame, text="Làm mờ (Blur)", variable=self._remove_method, value="blur").pack(pady=2)
        ctk.CTkRadioButton(method_frame, text="Cắt bỏ (Crop)", variable=self._remove_method, value="crop").pack(pady=2)
        
        self._logo_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._logo_progress_label.pack(pady=5)
        
        self._logo_progress_bar = ctk.CTkProgressBar(content, width=350, height=20, progress_color="#00AA55")
        self._logo_progress_bar.pack(pady=10)
        self._logo_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_process():
            self._logo_mode = self._remove_method.get()
            self._logo_x = x1
            self._logo_y = y1
            self._logo_w = x2 - x1
            self._logo_h = y2 - y1
            
            confirm.destroy()
            parent_dialog.destroy()
            self._do_remove_logo(None)
    
    def render_audio_cut_tab(self):
        ctk.CTkLabel(self.props_content, text="Cắt audio thành các đoạn ngắn", text_color="white", font=("Segoe UI", 12, "bold")).pack(pady=(10, 5))
        
        clip = self.selected_clips[0] if self.selected_clips else None
        if not clip or clip.clip_type != 'audio':
            ctk.CTkLabel(self.props_content, text="⚠️ Vui lòng chọn clip audio trong Timeline", text_color="#FFAA00").pack(pady=20)
            return
        
        audio_path = clip.file_path
        
        try:
            duration_sec = self.get_media_duration(audio_path, 'audio')
            mins = int(duration_sec // 60)
            secs = int(duration_sec % 60)
        except:
            duration_sec = clip.duration
            mins = int(duration_sec // 60)
            secs = int(duration_sec % 60)
        
        info_frame = ctk.CTkFrame(self.props_content, fg_color="#2B2B2B", corner_radius=6)
        info_frame.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(info_frame, text=f"⏱ Thời lượng audio: {mins}:{secs:02d}", text_color="#00E5FF", font=("Segoe UI", 11)).pack(pady=10)
        
        input_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        input_frame.pack(fill=tk.X, pady=10)
        ctk.CTkLabel(input_frame, text="Số đoạn cắt:", text_color="#AAAAAA", width=80, anchor="w").pack(side=tk.LEFT)
        
        self.cut_audio_segments_entry = ctk.CTkEntry(input_frame, placeholder_text="3", width=100, height=32, fg_color="#2B2B2B", border_width=0)
        self.cut_audio_segments_entry.pack(side=tk.LEFT, padx=10)
        self.cut_audio_segments_entry.insert("0", "3")
        
        ctk.CTkLabel(self.props_content, text=" Ví dụ: Audio 6 phút, nhập 3 → Cắt thành 3 đoạn ~2 phút mỗi đoạn", text_color="#666", font=("Segoe UI", 10)).pack(pady=(0, 10))
        
        self.cut_audio_status_label = ctk.CTkLabel(self.props_content, text="", text_color="#AAAAAA", font=("Segoe UI", 10))
        self.cut_audio_status_label.pack(pady=5)
        
        self.cut_audio_progress = ctk.CTkProgressBar(self.props_content, orientation="horizontal", mode="determinate")
        self.cut_audio_progress.set(0)
        self.cut_audio_progress.pack(fill=tk.X, pady=5)
        
        btn_frame = ctk.CTkFrame(self.props_content, fg_color="transparent")
        btn_frame.pack(fill=tk.X, pady=10)
        
        self.cut_audio_start_btn = ctk.CTkButton(btn_frame, text="Cắt audio", fg_color="#9C27B0", text_color="white", height=36, font=("Segoe UI", 11, "bold"), command=self.start_audio_cut)
        self.cut_audio_start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        self.cut_audio_cancel_btn = ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#F44336", text_color="white", height=36, font=("Segoe UI", 11, "bold"), command=self.cancel_audio_cut, state="disabled")
        self.cut_audio_cancel_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        self.cutting_audio = False
        self.cancel_audio_cut = False
    
    def start_audio_cut(self):
        try:
            num_segments = int(self.cut_audio_segments_entry.get())
            if num_segments <= 0:
                messagebox.showwarning("Lỗi", "Số đoạn cắt phải lớn hơn 0")
                return
        except ValueError:
            messagebox.showwarning("Lỗi", "Vui lòng nhập số đoạn hợp lệ")
            return
        
        import shutil
        ffmpeg_path = find_ffmpeg()
        
        if not shutil.which("ffmpeg"):
            messagebox.showerror("Lỗi", "Cần ffmpeg để cắt audio. Vui lòng cài đặt ffmpeg.")
            return
        
        from tkinter import filedialog
        save_dir = filedialog.askdirectory(title="Chọn thư mục lưu audio đã cắt")
        if not save_dir:
            return
        
        project_name = getattr(self, 'project_name', "Project") or "Project"
        
        clip = self.selected_clips[0]
        audio_path = clip.file_path
        
        self.cutting_audio = True
        self.cancel_audio_cut = False
        self.cut_audio_start_btn.configure(state="disabled")
        self.cut_audio_cancel_btn.configure(state="normal")
        self.cut_audio_status_label.configure(text="Đang cắt...")
        
        def run_cut():
            import time as time_module
            import subprocess
            
            try:
                total_duration = clip.duration
                segment_duration = total_duration / num_segments
                
                for i in range(num_segments):
                    if self.cancel_audio_cut:
                        break
                    
                    while getattr(self, '_audio_paused', False):
                        time_module.sleep(0.2)
                        if self.cancel_audio_cut:
                            break
                    
                    if self.cancel_audio_cut:
                        break
                    
                    start_time = i * segment_duration
                    end_time = min((i + 1) * segment_duration, total_duration)
                    
                    base_name = os.path.splitext(os.path.basename(audio_path))[0]
                    ext = os.path.splitext(audio_path)[1] or ".mp3"
                    output_name = f"{i+1}.{project_name}_{base_name}{ext}"
                    output_path = os.path.join(save_dir, output_name)
                    
                    status_text = f"Đang xuất đoạn {i+1}/{num_segments}..."
                    self.root.after(0, lambda t=status_text: self.cut_audio_status_label.configure(text=t))
                    self.root.after(0, lambda p=(i+1)/num_segments: self.cut_audio_progress.set(p))
                    
                    cmd = [
                        ffmpeg_path, "-y",
                        "-i", audio_path,
                        "-ss", str(start_time),
                        "-to", str(end_time),
                        "-c", "copy",
                        output_path
                    ]
                    subprocess.run(cmd, capture_output=True)
                    
                    mins_part = int(segment_duration // 60)
                    secs_part = int(segment_duration % 60)
                    output_size = os.path.getsize(output_path) / (1024 * 1024)
                    
                    status_text = f"Đoạn {i+1}/{num_segments} | {mins_part}:{secs_part:02d} | {output_size:.1f}MB"
                    self.root.after(0, lambda t=status_text: self.cut_audio_status_label.configure(text=t))
                
                if self.cancel_audio_cut:
                    self.root.after(0, lambda: self.cut_audio_status_label.configure(text="Đã huỷ"))
                else:
                    self.root.after(0, lambda: self.cut_audio_status_label.configure(text="Hoàn tất!"))
                    self.root.after(0, lambda: messagebox.showinfo("Hoàn tất", f"Đã cắt {num_segments} đoạn audio!\n\nLưu tại: {save_dir}"))
                    try:
                        os.startfile(save_dir)
                    except:
                        pass
                    
            except Exception as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Lỗi", err))
            
            self.root.after(0, self._finish_audio_cut)
        
        import threading
        threading.Thread(target=run_cut, daemon=True).start()
    
    def cancel_audio_cut(self):
        self.cancel_audio_cut = True
        self.cut_audio_status_label.configure(text="Đang huỷ...")
    
    def _finish_audio_cut(self):
        self.cutting_audio = False
        self.cut_audio_start_btn.configure(state="normal")
        self.cut_audio_cancel_btn.configure(state="disabled")
        self.cut_audio_progress.set(0)
    
    def render_audio_speed_tab(self):
        ctk.CTkLabel(self.props_content, text="Điều chỉnh tốc độ audio", text_color="white", font=("Segoe UI", 12, "bold")).pack(pady=(10, 5))
        ctk.CTkLabel(self.props_content, text="Tính năng đang phát triển", text_color="#666").pack(pady=20)
    
    def _show_remove_remove_logo_dialog(self):
        dialog = ctk.CTkToplevel()
        dialog.title("Xóa Logo/Watermark")
        dialog.geometry("500x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=480, height=530, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        mode_texts = {
            "crop": "Cắt khung hình (Crop)",
            "blur": "Làm mờ vùng chọn (Blur)",
            "overlay": "Chèn đè vật thể (Overlay)",
            "ai": "AI Xóa watermark"
        }
        ctk.CTkLabel(content, text=mode_texts.get(self._logo_mode, "Xóa Logo"), font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Tệp gốc:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._logo_filepath), text_color="white", font=("Segoe UI", 11)).pack(pady=2)
        
        ctk.CTkLabel(content, text="Chọn vùng chứa logo/watermark:", font=("Segoe UI", 12)).pack(pady=10)
        
        pos_frame = ctk.CTkFrame(content, fg_color="transparent")
        pos_frame.pack(pady=5, fill=tk.X)
        
        ctk.CTkLabel(pos_frame, text="X (pixel):", width=80).pack(side=tk.LEFT)
        self._logo_x_entry = ctk.CTkEntry(pos_frame, width=100)
        self._logo_x_entry.pack(side=tk.LEFT, padx=5)
        self._logo_x_entry.insert(0, "50")
        
        ctk.CTkLabel(pos_frame, text="Y (pixel):", width=80).pack(side=tk.LEFT)
        self._logo_y_entry = ctk.CTkEntry(pos_frame, width=100)
        self._logo_y_entry.pack(side=tk.LEFT, padx=5)
        self._logo_y_entry.insert(0, "50")
        
        size_frame = ctk.CTkFrame(content, fg_color="transparent")
        size_frame.pack(pady=5, fill=tk.X)
        
        ctk.CTkLabel(size_frame, text="Chiều rộng:", width=80).pack(side=tk.LEFT)
        self._logo_w_entry = ctk.CTkEntry(size_frame, width=100)
        self._logo_w_entry.pack(side=tk.LEFT, padx=5)
        self._logo_w_entry.insert(0, "100")
        
        ctk.CTkLabel(size_frame, text="Chiều cao:", width=80).pack(side=tk.LEFT)
        self._logo_h_entry = ctk.CTkEntry(size_frame, width=100)
        self._logo_h_entry.pack(side=tk.LEFT, padx=5)
        self._logo_h_entry.insert(0, "50")
        
        if self._logo_mode == "blur":
            ctk.CTkLabel(content, text="Mức độ mờ (Blur radius):", font=("Segoe UI", 12)).pack(pady=10)
            blur_frame = ctk.CTkFrame(content, fg_color="transparent")
            blur_frame.pack(pady=5)
            self._blur_radius = ctk.CTkSlider(blur_frame, from_=5, to=50, width=200, fg_color="#333", progress_color="#00AA55", button_color="white")
            self._blur_radius.set(25)
            self._blur_radius.pack(pady=5)
            ctk.CTkLabel(content, text="Giá trị: 25", text_color="#00AA55", font=("Segoe UI", 10)).pack(pady=5)
        
        elif self._logo_mode == "overlay":
            ctk.CTkLabel(content, text="Chọn file đè lên (ảnh/video):", font=("Segoe UI", 12)).pack(pady=10)
            overlay_frame = ctk.CTkFrame(content, fg_color="transparent")
            overlay_frame.pack(pady=5, fill=tk.X)
            self._overlay_entry = ctk.CTkEntry(overlay_frame, width=300)
            self._overlay_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ctk.CTkButton(overlay_frame, text="...", width=30, command=lambda: self._browse_overlay_file()).pack(side=tk.LEFT, padx=5)
        
        elif self._logo_mode == "crop":
            ctk.CTkLabel(content, text="Cắt bỏ vùng chọn:", font=("Segoe UI", 12, "bold"), text_color="#FFAA00").pack(pady=10)
            ctk.CTkLabel(content, text="⚠️ Crop sẽ cắt bỏ vùng chọn khỏi video\n⚠️ Kích thước video sẽ thay đổi", text_color="#FF5555", font=("Segoe UI", 10)).pack(pady=5)
            
            ctk.CTkLabel(content, text="Vị trí logo trên video:", font=("Segoe UI", 12)).pack(pady=10)
            corner_frame = ctk.CTkFrame(content, fg_color="transparent")
            corner_frame.pack(pady=5)
            corners = [("Góc trên trái", "top_left"), ("Góc trên phải", "top_right"), ("Góc dưới trái", "bottom_left"), ("Góc dưới phải", "bottom_right")]
            self._crop_corner = ctk.StringVar(value="top_right")
            for text, val in corners:
                ctk.CTkRadioButton(corner_frame, text=text, variable=self._crop_corner, value=val).pack(side=tk.LEFT, padx=5)
        
        elif self._logo_mode == "ai":
            ctk.CTkLabel(content, text="⚠️ Chế độ AI đang thử nghiệm", text_color="#FFAA00", font=("Segoe UI", 12, "bold")).pack(pady=10)
            ctk.CTkLabel(content, text="Cần cài đặt: pip install rembg", text_color="#888", font=("Segoe UI", 10)).pack(pady=5)
        
        output_frame = ctk.CTkFrame(content, fg_color="transparent")
        output_frame.pack(pady=10, fill=tk.X)
        ctk.CTkLabel(output_frame, text="Thư mục lưu:", font=("Segoe UI", 11)).pack(side=tk.LEFT)
        
        self._logo_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._logo_progress_label.pack(pady=10)
        
        self._logo_progress_bar = ctk.CTkProgressBar(content, width=350, height=20, progress_color="#00AA55")
        self._logo_progress_bar.pack(pady=10)
        self._logo_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_remove():
            try:
                self._logo_x = int(self._logo_x_entry.get())
                self._logo_y = int(self._logo_y_entry.get())
                self._logo_w = int(self._logo_w_entry.get())
                self._logo_h = int(self._logo_h_entry.get())
            except:
                messagebox.showerror("Lỗi", "Vui lòng nhập số hợp lệ")
                return
            
            self._do_remove_logo(dialog)
        
        ctk.CTkButton(btn_frame, text="Xử lý", fg_color="#00AA55", width=100, command=do_remove).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _browse_overlay_file(self):
        file = filedialog.askopenfilename(filetypes=[("Media", "*.png *.jpg *.mp4 *.avi *.mov")])
        if file:
            self._overlay_entry.delete(0, tk.END)
            self._overlay_entry.insert(0, file)
    
    def _show_remove_logo_dialog(self):
        dialog = ctk.CTkToplevel()
        dialog.title("Xóa Logo/Watermark")
        dialog.geometry("500x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        scroll = ctk.CTkScrollableFrame(dialog, width=480, height=530, fg_color="#1A1A1A")
        scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = scroll
        
        mode_texts = {
            "crop": "Cắt khung hình (Crop)",
            "blur": "Làm mờ vùng chọn (Blur)",
            "overlay": "Chèn đè vật thể (Overlay)",
            "ai": "AI Xóa watermark"
        }
        ctk.CTkLabel(content, text=mode_texts.get(self._logo_mode, "Xóa Logo"), font=("Segoe UI", 16, "bold")).pack(pady=15)
        
        ctk.CTkLabel(content, text="Tệp gốc:", text_color="#888").pack(pady=5)
        ctk.CTkLabel(content, text=os.path.basename(self._logo_filepath), text_color="white", font=("Segoe UI", 11)).pack(pady=2)
        
        ctk.CTkLabel(content, text="Chọn vùng chứa logo/watermark:", font=("Segoe UI", 12)).pack(pady=10)
        
        pos_frame = ctk.CTkFrame(content, fg_color="transparent")
        pos_frame.pack(pady=5, fill=tk.X)
        ctk.CTkLabel(pos_frame, text="X (pixel):", width=80).pack(side=tk.LEFT)
        self._logo_x_entry = ctk.CTkEntry(pos_frame, width=100)
        self._logo_x_entry.pack(side=tk.LEFT, padx=5)
        self._logo_x_entry.insert(0, "50")
        
        ctk.CTkLabel(pos_frame, text="Y (pixel):", width=80).pack(side=tk.LEFT)
        self._logo_y_entry = ctk.CTkEntry(pos_frame, width=100)
        self._logo_y_entry.pack(side=tk.LEFT, padx=5)
        self._logo_y_entry.insert(0, "50")
        
        size_frame = ctk.CTkFrame(content, fg_color="transparent")
        size_frame.pack(pady=5, fill=tk.X)
        ctk.CTkLabel(size_frame, text="Chiều rộng:", width=80).pack(side=tk.LEFT)
        self._logo_w_entry = ctk.CTkEntry(size_frame, width=100)
        self._logo_w_entry.pack(side=tk.LEFT, padx=5)
        self._logo_w_entry.insert(0, "100")
        
        ctk.CTkLabel(size_frame, text="Chiều cao:", width=80).pack(side=tk.LEFT)
        self._logo_h_entry = ctk.CTkEntry(size_frame, width=100)
        self._logo_h_entry.pack(side=tk.LEFT, padx=5)
        self._logo_h_entry.insert(0, "50")
        
        if self._logo_mode == "blur":
            ctk.CTkLabel(content, text="Mức độ mờ (Blur radius):", font=("Segoe UI", 12)).pack(pady=10)
            blur_frame = ctk.CTkFrame(content, fg_color="transparent")
            blur_frame.pack(pady=5)
            self._blur_radius = ctk.CTkSlider(blur_frame, from_=5, to=50, width=200, fg_color="#333", progress_color="#00AA55", button_color="white")
            self._blur_radius.set(25)
            self._blur_radius.pack(pady=5)
        
        elif self._logo_mode == "overlay":
            ctk.CTkLabel(content, text="Chọn file đè lên (ảnh):", font=("Segoe UI", 12)).pack(pady=10)
            overlay_frame = ctk.CTkFrame(content, fg_color="transparent")
            overlay_frame.pack(pady=5, fill=tk.X)
            self._overlay_entry = ctk.CTkEntry(overlay_frame, width=300)
            self._overlay_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ctk.CTkButton(overlay_frame, text="...", width=30, command=lambda: self._browse_overlay_file()).pack(side=tk.LEFT, padx=5)
        
        elif self._logo_mode == "crop":
            ctk.CTkLabel(content, text="⚠️ Crop sẽ cắt bỏ vùng chọn khỏi video", text_color="#FFAA00", font=("Segoe UI", 10)).pack(pady=10)
        
        self._logo_progress_label = ctk.CTkLabel(content, text="", text_color="#00AA55")
        self._logo_progress_label.pack(pady=10)
        
        self._logo_progress_bar = ctk.CTkProgressBar(content, width=350, height=20, progress_color="#00AA55")
        self._logo_progress_bar.pack(pady=10)
        self._logo_progress_bar.set(0)
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        def do_remove():
            try:
                self._logo_x = int(self._logo_x_entry.get())
                self._logo_y = int(self._logo_y_entry.get())
                self._logo_w = int(self._logo_w_entry.get())
                self._logo_h = int(self._logo_h_entry.get())
            except:
                messagebox.showerror("Lỗi", "Vui lòng nhập số hợp lệ")
                return
            
            self._do_remove_logo(dialog)
        
        ctk.CTkButton(btn_frame, text="Xử lý", fg_color="#00AA55", width=100, command=do_remove).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="Huỷ", fg_color="#AA0000", width=80, command=dialog.destroy).pack(side=tk.LEFT, padx=10)
    
    def _do_remove_logo(self, dialog):
        try:
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "video")
            os.makedirs(output_dir, exist_ok=True)
            
            base_name = os.path.splitext(os.path.basename(self._logo_filepath))[0]
            
            if self._logo_mode == "blur":
                self._do_blur_logo(output_dir, base_name, dialog)
            elif self._logo_mode == "overlay":
                self._do_overlay_logo(output_dir, base_name, dialog)
            elif self._logo_mode == "crop":
                self._do_crop_logo(output_dir, base_name, dialog)
            elif self._logo_mode == "ai":
                self._do_ai_remove_logo(output_dir, base_name, dialog)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xóa logo:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def _do_blur_logo(self, output_dir, base_name, dialog):
        try:
            self._logo_progress_label.configure(text="Đang xử lý...")
            self._logo_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._logo_filepath)
            fps = clip.fps
            duration = clip.duration
            w, h = clip.size
            
            self._logo_progress_bar.set(0.1)
            self._logo_progress_label.configure(text="Đang làm mờ...")
            self._logo_progress_label.update_idletasks()
            
            blur_radius = int(getattr(self, '_logo_blur_radius', 25) if hasattr(self, '_logo_blur_radius') else 25)
            
            def make_blurred_frame(t):
                frame = clip.get_frame(t)
                if isinstance(frame, np.ndarray):
                    img = Image.fromarray(frame)
                else:
                    img = frame
                
                x1 = max(0, self._logo_x)
                y1 = max(0, self._logo_y)
                x2 = min(w, x1 + self._logo_w)
                y2 = min(h, y1 + self._logo_h)
                
                if x2 > x1 and y2 > y1:
                    region = img.crop((x1, y1, x2, y2))
                    blurred = region.filter(ImageFilter.GaussianBlur(radius=blur_radius))
                    img.paste(blurred, (x1, y1))
                
                return np.array(img)
            
            from moviepy.video.fx.all import iteratelambda
            from moviepy.video.VideoClip import VideoClip as VC
            
            def blur_effect(get_frame, t):
                frame = make_blurred_frame(t)
                return frame
            
            new_clip = VC(lambda t: make_blurred_frame(t), duration=duration).with_fps(fps)
            new_clip = new_clip.set_size((w, h))
            
            out_path = os.path.join(output_dir, f"{base_name}_blur.mp4")
            self._logo_progress_bar.set(0.5)
            self._logo_progress_label.configure(text="Đang xuất video...")
            self._logo_progress_label.update_idletasks()
            
            new_clip.write_videofile(out_path, codec='libx264', logger=None)
            
            self._logo_progress_bar.set(0.9)
            self._logo_progress_label.configure(text="Hoàn tất!")
            self._logo_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._logo_progress_bar.set(1.0)
            self._add_processed_video(out_path)
            messagebox.showinfo("Thành công", f"Đã làm mờ logo!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể làm mờ:\n{str(e)}")
    
    def _do_overlay_logo(self, output_dir, base_name, dialog):
        try:
            overlay_file = getattr(self, '_overlay_entry', None)
            if overlay_file:
                overlay_file = overlay_file.get() if hasattr(overlay_file, 'get') else str(overlay_file)
            
            if not overlay_file or not os.path.exists(overlay_file):
                messagebox.showerror("Lỗi", "Vui lòng chọn file đè lên")
                return
            
            self._logo_progress_label.configure(text="Đang xử lý...")
            self._logo_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._logo_filepath)
            w, h = clip.size
            
            self._logo_progress_bar.set(0.2)
            self._logo_progress_label.configure(text="Đang tạo overlay...")
            self._logo_progress_label.update_idletasks()
            
            overlay_ext = os.path.splitext(overlay_file)[1].lower()
            if overlay_ext in ['.jpg', '.jpeg', '.png']:
                overlay_img = Image.open(overlay_file).convert("RGBA")
                overlay_img.thumbnail((self._logo_w, self._logo_h))
                overlay_frame = np.array(overlay_img)
            else:
                overlay_clip = MOVIEPY['VideoFileClip'](overlay_file)
                overlay_frame = overlay_clip.get_frame(0)
                overlay_clip.close()
                if isinstance(overlay_frame, np.ndarray):
                    overlay_img = Image.fromarray(overlay_frame).convert("RGBA")
                    overlay_img.thumbnail((self._logo_w, self._logo_h))
                    overlay_frame = np.array(overlay_img)
            
            def make_overlay_frame(t):
                frame = clip.get_frame(t)
                if isinstance(frame, np.ndarray):
                    img = Image.fromarray(frame).convert("RGBA")
                else:
                    img = frame.convert("RGBA")
                
                x1 = max(0, self._logo_x)
                y1 = max(0, self._logo_y)
                x2 = min(w, x1 + overlay_frame.shape[1])
                y2 = min(h, y1 + overlay_frame.shape[0])
                
                overlay_resized = Image.fromarray(overlay_frame).resize((x2 - x1, y2 - y1))
                img.paste(overlay_resized, (x1, y1), overlay_resized)
                
                return np.array(img.convert("RGB"))
            
            from moviepy.video.VideoClip import VideoClip as VC
            
            new_clip = VC(lambda t: make_overlay_frame(t), duration=clip.duration).with_fps(clip.fps)
            new_clip = new_clip.set_size((w, h))
            
            out_path = os.path.join(output_dir, f"{base_name}_overlay.mp4")
            self._logo_progress_bar.set(0.5)
            self._logo_progress_label.configure(text="Đang xuất video...")
            self._logo_progress_label.update_idletasks()
            
            new_clip.write_videofile(out_path, codec='libx264', logger=None)
            
            self._logo_progress_bar.set(0.9)
            self._logo_progress_label.configure(text="Hoàn tất!")
            self._logo_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._logo_progress_bar.set(1.0)
            self._add_processed_video(out_path)
            messagebox.showinfo("Thành công", f"Đã đè overlay!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể đè overlay:\n{str(e)}")
    
    def _do_crop_logo(self, output_dir, base_name, dialog):
        try:
            self._logo_progress_label.configure(text="Đang xử lý...")
            self._logo_progress_label.update_idletasks()
            
            clip = MOVIEPY['VideoFileClip'](self._logo_filepath)
            w, h = clip.size
            
            self._logo_progress_bar.set(0.2)
            self._logo_progress_label.configure(text="Đang crop video...")
            self._logo_progress_label.update_idletasks()
            
            crop_pos = getattr(self, '_crop_corner', 'top_right') if hasattr(self, '_crop_corner') else 'top_right'
            
            x1 = max(0, self._logo_x)
            y1 = max(0, self._logo_y)
            x2 = min(w, x1 + self._logo_w)
            y2 = min(h, y1 + self._logo_h)
            
            crop_box = (x1, y1, x2, y2)
            
            out_path = os.path.join(output_dir, f"{base_name}_crop.mp4")
            self._logo_progress_bar.set(0.5)
            self._logo_progress_label.configure(text="Đang xuất video...")
            self._logo_progress_label.update_idletasks()
            
            new_clip = clip.crop(*crop_box)
            new_clip.write_videofile(out_path, codec='libx264', logger=None)
            
            self._logo_progress_bar.set(0.9)
            self._logo_progress_label.configure(text="Hoàn tất!")
            self._logo_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._logo_progress_bar.set(1.0)
            self._add_processed_video(out_path)
            messagebox.showinfo("Thành công", f"Đã crop video!\nLưu tại:\n{out_path}")
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể crop:\n{str(e)}")
    
    def _do_ai_remove_logo(self, output_dir, base_name, dialog):
        if dialog and dialog.winfo_exists():
            try:
                import cv2
                self._logo_progress_label.configure(text="Đang phân tích video bằng AI...")
                self._logo_progress_label.update_idletasks()
            except:
                pass
        else:
            dialog = None
        
        try:
            import cv2
            
            clip = MOVIEPY['VideoFileClip'](self._logo_filepath)
            fps = clip.fps
            duration = clip.duration
            w, h = clip.size
            
            if dialog and dialog.winfo_exists():
                self._logo_progress_bar.set(0.05)
                self._logo_progress_label.configure(text="Đang phát hiện vùng watermark...")
                self._logo_progress_label.update_idletasks()
            
            x1 = max(0, self._logo_x)
            y1 = max(0, self._logo_y)
            x2 = min(w, x1 + self._logo_w)
            y2 = min(h, y1 + self._logo_h)
            
            logo_region = (x1, y1, x2, y2)
            
            prev_gray = None
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[y1:y2, x1:x2] = 255
            
            feature_params = dict(maxCorners=100, qualityLevel=0.3, minDistance=7, blockSize=7)
            win_size = 21
            
            def SmartInpaintAI(frame, mask_frame, prev_gray, logo_region):
                x1, y1, x2, y2 = logo_region
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY) if len(frame.shape) == 3 else frame
                
                mask_crop = mask_frame[y1:y2, x1:x2].copy()
                
                mask_crop_dilated = cv2.dilate(mask_crop, np.ones((5, 5), np.uint8), iterations=2)
                mask_crop_blur = cv2.GaussianBlur(mask_crop_dilated, (21, 21), 0)
                
                dilated_full = cv2.dilate(mask_frame, np.ones((10, 10), np.uint8), iterations=3)
                dilated_blur = cv2.GaussianBlur(dilated_full, (15, 15), 0)
                
                result = frame.copy()
                
                if prev_gray is not None:
                    prev_good = cv2.goodFeaturesToTrack(gray, **feature_params)
                    curr_good = cv2.goodFeaturesToTrack(prev_gray, **feature_params)
                    
                    if prev_good is not None and curr_good is not None:
                        curr_good, status, err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, curr_good, None, winSize=win_size)
                        
                        src_pts = curr_good[status == 1]
                        dst_pts = prev_good[status == 1]
                        
                        if len(src_pts) > 4:
                            M, mask_inliers = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
                            if M is not None:
                                warped = cv2.warpPerspective(result, M, (w, h))
                                mask_warped = cv2.warpPerspective(mask_frame, M, (w, h))
                                
                                valid_mask = (mask_warped > 0) & (dilated_blur > 127)
                                result[valid_mask] = warped[valid_mask]
                
                bg_region = frame.copy()
                
                for offset_y in range(-20, 21, 5):
                    for offset_x in range(-20, 21, 5):
                        sx = max(0, x1 + offset_x)
                        sy = max(0, y1 + offset_y)
                        ex = min(w, x2 + offset_x)
                        ey = min(h, y2 + offset_y)
                        
                        if sx < ex and sy < ey:
                            sample = frame[sy:ey, sx:ex]
                            if sample.size > 0:
                                mean_color = np.mean(sample, axis=(0, 1))
                                result[y1:y2, x1:x2] = (result[y1:y2, x1:x2] * (mask_crop > 127)[:, :, np.newaxis] + 
                                                      mean_color * (mask_crop <= 127)[:, :, np.newaxis]).astype(np.uint8)
                
                edge_mask = cv2.GaussianBlur(mask_crop, (11, 11), 0)
                edge_mask = edge_mask.astype(float) / 255.0
                
                blended = result[y1:y2, x1:x2].astype(float)
                original = frame[y1:y2, x1:x2].astype(float)
                
                for c in range(3):
                    blended[:, :, c] = original[:, :, c] * (1 - edge_mask) + blended[:, :, c] * edge_mask
                
                result[y1:y2, x1:x2] = blended.astype(np.uint8)
                
                result = cv2.bilateralFilter(result, 9, 75, 75)
                
                return result, gray, result
            
            def process_frame_ai(t, clip_obj, logo_region, mask_arr):
                frame = clip_obj.get_frame(t)
                if isinstance(frame, np.ndarray):
                    if frame.max() <= 1.0:
                        frame = (frame * 255).astype(np.uint8)
                    if len(frame.shape) == 2:
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                    elif frame.shape[2] == 4:
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                
                result, _, _ = SmartInpaintAI(frame, mask_arr, None, logo_region)
                return result
            
            from moviepy.video.VideoClip import VideoClip as VC
            
            total_frames = int(duration * fps)
            
            def render_frame(t):
                progress = t / duration
                return process_frame_ai(t, clip, logo_region, mask)
            
            new_clip = VC(lambda t: render_frame(t), duration=duration)
            new_clip = new_clip.with_fps(fps)
            new_clip = new_clip.set_size((w, h))
            
            out_path = os.path.join(output_dir, f"{base_name}_ai_smart.mp4")
            
            if dialog and dialog.winfo_exists():
                self._logo_progress_bar.set(0.8)
            
            new_clip.write_videofile(out_path, codec='libx264', logger=None)
            
            if dialog and dialog.winfo_exists():
                self._logo_progress_bar.set(0.95)
                self._logo_progress_label.configure(text="Hoàn tất!")
                self._logo_progress_label.update_idletasks()
            
            clip.close()
            new_clip.close()
            
            self._logo_progress_bar.set(1.0)
            self._add_processed_video(out_path)
            messagebox.showinfo("Thành công", f"Đã xóa logo bằng AI thông minh!\nLưu tại:\n{out_path}")
            
            if dialog and dialog.winfo_exists():
                dialog.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xóa logo AI:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def SmartInpaint_with_optical_flow(self, frame, prev_frame, mask, logo_region):
        """Smart Inpaint sử dụng Optical Flow và Contextual Attention"""
        x1, y1, x2, y2 = logo_region
        
        if prev_frame is None:
            return frame, frame
        
        try:
            import cv2
            
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_RGB2GRAY)
            
            prev_pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=50, qualityLevel=0.01, minDistance=10)
            
            if prev_pts is not None:
                curr_pts, status, err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_pts, None, winSize=15)
                
                good_prev = prev_pts[status == 1]
                good_curr = curr_pts[status == 1]
                
                if len(good_prev) >= 4:
                    H, mask_homography = cv2.findHomography(good_prev, good_curr, cv2.RANSAC, 4.0)
                    
                    if H is not None:
                        result = frame.copy()
                        
                        mask_inpaint = cv2.warpPerspective(mask, H, (frame.shape[1], frame.shape[0]))
                        
                        warped = cv2.warpPerspective(prev_frame, H, (frame.shape[1], frame.shape[0]))
                        
                        inpaint_region = (mask > 0)
                        
                        valid_pts = mask_homography.flatten() == 1
                        
                        for c in range(min(3, frame.shape[2])):
                            result[:, :, c][inpaint_region] = warped[:, :, c][inpaint_region]
                        
                        kernel = np.ones((5, 5), np.uint8)
                        mask_dilated = cv2.dilate(mask, kernel, iterations=3)
                        mask_blur = cv2.GaussianBlur(mask_dilated.astype(float), (15, 15), 0)
                        mask_blur = mask_blur / mask_blur.max() if mask_blur.max() > 0 else mask_blur
                        
                        for c in range(min(3, frame.shape[2])):
                            orig_channel = frame[:, :, c].astype(float)
                            inpaint_channel = result[:, :, c].astype(float)
                            
                            result[:, :, c] = (orig_channel * (1 - mask_blur) + inpaint_channel * mask_blur).astype(np.uint8)
                        
                        result = cv2.bilateralFilter(result, 9, 75, 75)
                        
                        return result, gray
            
            return frame, gray
            
        except Exception as e:
            print(f"SmartInpaint error: {e}")
            return frame, gray
    
    def detect_watermark_auto(self, video_path):
        """Tự động phát hiện vùng watermark trong video"""
        try:
            import cv2
            
            clip = MOVIEPY['VideoFileClip'](video_path)
            h, w = clip.size[1], clip.size[0]
            
            first_frames = [clip.get_frame(i / 30.0) for i in range(5)]
            last_frames = [clip.get_frame(clip.duration - i / 30.0) for i in range(5, 0, -1)]
            
            clip.close()
            
            all_diffs = np.zeros((h, w), dtype=float)
            
            for i, (f1, f2) in enumerate(zip(first_frames, last_frames)):
                diff = np.abs(f1.astype(float) - f2.astype(float))
                diff_sum = np.mean(diff, axis=2) if len(diff.shape) == 3 else diff
                all_diffs += diff_sum
            
            all_diffs /= 5
            
            threshold = np.percentile(all_diffs, 90)
            
            binary_diff = (all_diffs > threshold).astype(np.uint8) * 255
            
            kernel = np.ones((15, 15), np.uint8)
            dilated = cv2.dilate(binary_diff, kernel, iterations=3)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                largest = max(contours, key=cv2.contourArea)
                x, y, ww, hh = cv2.boundingRect(largest)
                
                return (max(0, x), max(0, y), min(w, x + ww), min(h, y + hh))
            
            return (w - 150, h - 100, w - 50, h - 50)
            
        except Exception as e:
            print(f"Auto detect error: {e}")
            return None
    
    def open_file_location(self, filepath):
        folder = os.path.dirname(filepath)
        import subprocess
        subprocess.Popen(f'explorer /select,"{filepath}"')
    
    def show_properties(self, idx):
        filepath = self.media_files[idx]
        info = f"Path: {filepath}\n"
        info += f"Size: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB"
        messagebox.showinfo("Properties", info)
    
    def delete_media(self, idx):
        if messagebox.askyesno("Delete", "Delete this media?"):
            del self.media_files[idx]
            del self.media_types[idx]
            self.refresh_thumbnails()
    
    def select_media(self, idx):
        self.current_file = self.media_files[idx]
        
        # Show in preview
        try:
            ext = os.path.splitext(self.current_file)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                img = Image.open(self.current_file)
                img.thumbnail((640, 360))
                self.preview_image = ImageTk.PhotoImage(img)
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(320, 180, image=self.preview_image)
            elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm'] and MOVIEPY_AVAILABLE:
                self.preview_clip = MOVIEPY['VideoFileClip'](self.current_file)
                self.timeline_slider.configure(to=int(self.preview_clip.duration * 30))
                self.draw_preview_frame(0)
                
                # Extract audio for playback
                if self.preview_clip.audio:
                    temp_audio = os.path.join(OUTPUT_DIR, "preview_audio.mp3")
                    if not hasattr(self, 'current_audio_path') or self.current_audio_path != self.current_file:
                        try:
                            # Run async or block? Blocking for now but suppressing logger
                            self.preview_clip.audio.write_audiofile(temp_audio, logger=None)
                            self.current_audio_file = temp_audio
                            self.current_audio_path = self.current_file
                        except Exception as e:
                            print(f"Audio extract error: {e}")
        except Exception as e:
            print(f"Preview error: {e}")
    
    def _source_frame(self, clip, local_time):
        """Raw frame for a video/image clip, or None when it cannot be read."""
        try:
            if clip.clip_type == 'video':
                if not MOVIEPY_AVAILABLE or not clip.file_path:
                    return None
                if clip.mv_clip is None:
                    clip.mv_clip = MOVIEPY['VideoFileClip'](clip.file_path)
                return Image.fromarray(np.asarray(clip.mv_clip.get_frame(local_time)))
            if clip.clip_type == 'image':
                if clip.mv_clip is None:
                    clip.mv_clip = Image.open(clip.file_path).convert("RGBA")
                return clip.mv_clip
        except Exception as exc:
            print("Frame source error: %s" % exc)
        return None

    def _clip_layer(self, clip, local_time, w, h):
        """One clip rendered into a canvas-sized RGBA layer, effects included."""
        p = ANIM.motion_progress(local_time, clip.duration)
        if clip.clip_type in ('video', 'image'):
            frame = self._source_frame(clip, local_time)
            if frame is None:
                return None
            frame = frame.convert("RGBA")
            # thumbnail() only shrinks, which left a smaller-than-canvas clip
            # floating in black; scale-to-fit so 16:9 media fills a 16:9 frame.
            scale = min(w / frame.width, h / frame.height)
            size = (max(1, int(round(frame.width * scale))),
                    max(1, int(round(frame.height * scale))))
            frame = frame.resize(size, Image.Resampling.LANCZOS)
            layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            layer.paste(frame, ((w - frame.width) // 2, (h - frame.height) // 2))
            return ANIM.apply_motion(layer, getattr(clip, 'motion_effect', 'none'), p,
                                     getattr(clip, 'motion_intensity', 5))
        if clip.clip_type == 'text':
            return ANIM.text_layer(
                (w, h), getattr(clip, 'text_content', ''),
                effect=getattr(clip, 'text_effect', 'none'), p=p,
                intensity=getattr(clip, 'text_intensity', 5),
                font_size=getattr(clip, 'font_size', 36),
                color=getattr(clip, 'text_color', '#FFFFFF'),
                bg=getattr(clip, 'bg_color', 'transparent'),
                pos=(getattr(clip, 'x_pos', 320) / 640.0,
                     getattr(clip, 'y_pos', 180) / 360.0),
                font=getattr(clip, 'font', 'Arial'))
        return None

    def _compose_clips(self, clips, time_sec, w, h):
        """Stack the given clips that are live at `time_sec` into one RGBA frame."""
        base = Image.new('RGBA', (w, h), (0, 0, 0, 255))
        active = [c for c in clips
                  if c.start_time <= time_sec < (c.start_time + c.duration)]
        # Highest track last, so captions and overlays sit above the video frame.
        active.sort(key=lambda c: c.track_idx)
        for clip in active:
            layer = self._clip_layer(clip, time_sec - clip.start_time, w, h)
            if layer is not None:
                base = Image.alpha_composite(base, layer)
        return base, active

    def _compose_frame(self, time_sec, w, h):
        """The player and the exporter share this, so a clip can never look
        different in preview from how it lands in the rendered file."""
        return self._compose_clips(self.timeline_clips, time_sec, w, h)

    def draw_preview_frame(self, frame_num):
        import threading
        if hasattr(self, '_frame_lock'):
            if self._frame_lock.locked():
                return
        
        self._frame_lock = threading.Lock()
        self._frame_lock.acquire()
        
        try:
            time_sec = frame_num / 30.0
            base, active_clips = self._compose_frame(time_sec, 640, 360)
            
            self._last_preview_pil = base
            self.preview_image = ImageTk.PhotoImage(base)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(320, 180, image=self.preview_image)
            
            for clip in active_clips:
                if clip.clip_type == 'text':
                    cx = getattr(clip, 'x_pos', 320)
                    cy = getattr(clip, 'y_pos', 180)
                    is_sel = (hasattr(self, '_selected_clip') and self._selected_clip == clip)
                    self.preview_canvas.create_rectangle(cx - 100, cy - 25, cx + 100, cy + 25, outline="#00E5FF" if is_sel else "#444444", width=2)
            
            total_dur = self.get_total_duration()
            if hasattr(self, 'time_label'):
                self.time_label.configure(text="%s / %s" % (format_timecode(time_sec),
                                                            format_timecode(total_dur)))
        finally:
            if hasattr(self, '_frame_lock'):
                try:
                    self._frame_lock.release()
                except:
                    pass
    
    def _on_canvas_press(self, event):
        if self._drag_state.get("locked"):
            return
        x, y = event.x, event.y
        for clip in self.timeline_clips:
            if clip.clip_type == 'text':
                cx, cy = getattr(clip, 'x_pos', 320), getattr(clip, 'y_pos', 180)
                if abs(x - cx) < 100 and abs(y - cy) < 30:
                    self._drag_state = {"active": True, "clip": clip, "start_x": x, "start_y": y, "orig_x": cx, "orig_y": cy}
                    self._selected_clip = clip
                    self._update_props_for_clip()
                    return
    
    def _on_canvas_drag(self, event):
        state = self._drag_state
        if not state.get("active"):
            return
        clip = state.get("clip")
        if not clip:
            return
        dx = event.x - state["start_x"]
        dy = event.y - state["start_y"]
        clip.x_pos = max(50, min(590, state["orig_x"] + dx))
        clip.y_pos = max(30, min(330, state["orig_y"] + dy))
        self.draw_preview_frame(int(self.current_frame))
    
    def _on_canvas_release(self, event):
        if self._drag_state.get("active"):
            self._drag_state = {"active": False, "clip": None}
    
    def _select_clip_for_edit(self, clip):
        self._selected_clip = clip
        self._update_props_for_clip()
        self.draw_preview_frame(int(self.current_frame))
    
    def _update_props_for_clip(self):
        pass
    
    def play_video(self):
        self.is_playing = not self.is_playing
        if self.is_playing:
            self._set_play_icon(True)
            self._stop_audio = False
            
            if WINSOUND_AVAILABLE and hasattr(self, 'current_audio_file') and os.path.exists(self.current_audio_file):
                def play_audio_async():
                    try:
                        winsound.PlaySound(self.current_audio_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    except Exception as e:
                        print(f"Audio play error: {e}")
                
                import threading
                if self._audio_thread and self._audio_thread.is_alive():
                    self._audio_thread.join(timeout=0.1)
                self._audio_thread = threading.Thread(target=play_audio_async, daemon=True)
                self._audio_thread.start()
            elif PLAYSOUND_AVAILABLE and hasattr(self, 'current_audio_file') and os.path.exists(self.current_audio_file):
                try:
                    from playsound import playsound
                    import threading
                    if self._audio_thread and self._audio_thread.is_alive():
                        self._audio_thread.join(timeout=0.1)
                    self._audio_thread = threading.Thread(target=lambda: playsound(self.current_audio_file), daemon=True)
                    self._audio_thread.start()
                except Exception as e:
                    print(f"Audio play error: {e}")
            
            self.play_loop()
        else:
            self._set_play_icon(False)
            self._stop_audio = True
            if WINSOUND_AVAILABLE:
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except:
                    pass
    
    def change_aspect_ratio(self, ratio):
        self.aspect_ratio = ratio
        self._apply_aspect_ratio()
    
    def _apply_aspect_ratio(self):
        if not hasattr(self, 'preview_image') or self.preview_image is None:
            return
        w, h = self.preview_image.width(), self.preview_image.height()
        if w == 0 or h == 0:
            return
        ratio_map = {
            "16:9": (16, 9), "3:2": (3, 2), "4:3": (4, 3),
            "1:1": (1, 1), "9:16": (9, 16), "21:9": (21, 9)
        }
        if self.aspect_ratio in ratio_map:
            rw, rh = ratio_map[self.aspect_ratio]
            target_ratio = rw / rh
            current_ratio = w / h
            if abs(target_ratio - current_ratio) > 0.01:
                new_w = int(h * target_ratio)
                new_h = int(w / target_ratio)
                if new_w <= w:
                    new_h = h
                    new_w = int(h * target_ratio)
                else:
                    new_w = w
                    new_h = int(w / target_ratio)
                self.preview_canvas.configure(width=new_w, height=new_h)
    
    def play_loop(self):
        if self.is_playing:
            current = self.timeline_slider.get()
            max_val = self.timeline_slider.cget("to")
            actual_max = int(self.get_total_duration() * 30)
            
            if current < min(max_val, actual_max):
                self.timeline_slider.set(current + 1)
                self.playhead_x = 100 + (current + 1)
                self.draw_playhead()
                self.draw_preview_frame(current + 1)
                self.root.after(33, self.play_loop)
            else:
                self._set_play_icon(False)
                self.is_playing = False
                self._stop_audio = True
                if WINSOUND_AVAILABLE:
                    try:
                        winsound.PlaySound(None, winsound.SND_PURGE)
                    except:
                        pass
    
    def prev_frame(self):
        val = max(0, self.timeline_slider.get() - 1)
        self.timeline_slider.set(val)
        self.on_slider_move(val)
    
    def next_frame(self):
        max_val = self.timeline_slider.cget("to")
        val = min(max_val, self.timeline_slider.get() + 1)
        self.timeline_slider.set(val)
        self.on_slider_move(val)
    
    def edit_project_name(self, event):
        self.proj_name_label.pack_forget()
        self.proj_name_entry = ctk.CTkEntry(self.proj_name_frame, width=120, height=24, fg_color="#2B2B2B", text_color="white", border_width=0)
        self.proj_name_entry.insert(0, self.project_name)
        self.proj_name_entry.pack(side=tk.LEFT)
        self.proj_name_entry.focus()
        self.proj_name_entry.bind("<Return>", self.save_project_name)
        self.proj_name_entry.bind("<FocusOut>", self.save_project_name)
        
    def save_project_name(self, event):
        new_name = self.proj_name_entry.get().strip()
        if new_name:
            self.project_name = new_name
            self.project_name_var.set(self.project_name)
        self.proj_name_entry.destroy()
        self.proj_name_label.pack(side=tk.LEFT)
        self.save_project()

    def export_video(self):
        export_win = ctk.CTkToplevel(self.root)
        export_win.title("Xuất")
        export_win.geometry("800x600")
        export_win.configure(fg_color="#181818")
        export_win.grab_set()
        export_win.focus_force()
        
        main_content = ctk.CTkFrame(export_win, fg_color="transparent")
        main_content.pack(fill=tk.BOTH, expand=True)
        
        left_frame = ctk.CTkFrame(main_content, width=280, fg_color="#181818")
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(20, 10), pady=20)
        left_frame.pack_propagate(False)
        
        thumb_box = ctk.CTkFrame(left_frame, fg_color="#000000", corner_radius=0)
        thumb_box.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        ctk.CTkLabel(thumb_box, text="Thumbnail", text_color="#FF4444", font=("Brush Script MT", 36)).place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkButton(left_frame, text="✎ Sửa ảnh bìa", fg_color="#2B2B2B", text_color="#AAAAAA", hover_color="#333", width=120).pack(pady=10)
        
        right_frame = ctk.CTkFrame(main_content, fg_color="#181818")
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 20), pady=20)
        
        ctk.CTkLabel(right_frame, text="Tên", text_color="#AAAAAA").pack(anchor="w", pady=(0, 5))
        name_entry = ctk.CTkEntry(right_frame, fg_color="#2B2B2B", border_width=0, text_color="white", height=35)
        name_entry.pack(fill=tk.X, pady=(0, 15))
        name_entry.insert(0, getattr(self, "project_name", "Video_Export"))
        
        ctk.CTkLabel(right_frame, text="Xuất sang", text_color="#AAAAAA").pack(anchor="w", pady=(0, 5))
        path_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        path_frame.pack(fill=tk.X, pady=(0, 20))
        path_entry = ctk.CTkEntry(path_frame, fg_color="#2B2B2B", border_width=0, text_color="white", height=35)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        import os
        default_path = os.path.join(os.path.expanduser("~"), "Clinging_Output")
        path_entry.insert(0, default_path)
        
        vid_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        vid_frame.pack(fill=tk.X, pady=5)
        
        vid_check = ctk.CTkCheckBox(vid_frame, text="Video", text_color="white", font=("Segoe UI", 12, "bold"), fg_color="#333", checkmark_color="#00E5FF", hover_color="#444")
        vid_check.select()
        vid_check.pack(anchor="w", pady=(0, 15))
        
        settings_grid = ctk.CTkFrame(vid_frame, fg_color="transparent")
        settings_grid.pack(fill=tk.X, padx=(30, 0))
        
        labels = ["Độ phân giải", "Tốc độ bit", "Bộ mã hóa", "Định dạng", "Tỷ lệ khung hình"]
        values = [["1080P", "4K", "720P"], ["Được đề xuất", "Cao", "Thấp"], ["H.264", "HEVC"], ["mp4", "mov"], ["30fps", "60fps", "24fps"]]
        menus = {}
        
        for i, (lbl, vals) in enumerate(zip(labels, values)):
            ctk.CTkLabel(settings_grid, text=lbl, text_color="#AAAAAA", width=120, anchor="w").grid(row=i, column=0, pady=8, sticky="w")
            om = ctk.CTkOptionMenu(settings_grid, values=vals, fg_color="#333", button_color="#444", button_hover_color="#555", text_color="white", dropdown_fg_color="#2B2B2B", dropdown_hover_color="#444", dropdown_text_color="white")
            om.grid(row=i, column=1, pady=8, sticky="ew")
            om.set(vals[0])
            menus[lbl] = om
            
        settings_grid.grid_columnconfigure(1, weight=1)
        
        audio_check = ctk.CTkCheckBox(right_frame, text="Âm thanh", text_color="white", font=("Segoe UI", 12, "bold"), fg_color="#333", checkmark_color="#00E5FF", hover_color="#444")
        audio_check.select()
        audio_check.pack(anchor="w", pady=15)
        
        ctk.CTkCheckBox(right_frame, text="Xuất GIF", text_color="white", font=("Segoe UI", 12, "bold"), fg_color="#333", checkmark_color="#00E5FF", hover_color="#444").pack(anchor="w", pady=5)
        
        bottom_frame = ctk.CTkFrame(export_win, fg_color="#181818", height=60, corner_radius=0)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        dur = int(self.get_total_duration())
        ctk.CTkLabel(bottom_frame, text=f"⏳ Khoảng thời gian: {dur} giây | 💾 Kích thước: khoảng 161 MB", text_color="#888", font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=20)
        
        ctk.CTkButton(bottom_frame, text="Hủy", fg_color="#333", text_color="white", hover_color="#444", width=100, height=36, corner_radius=6, command=export_win.destroy).pack(side=tk.RIGHT, padx=20, pady=15)
        
        def do_export():
            out_name = name_entry.get().strip() or "Video_Export"
            out_dir = path_entry.get().strip() or default_path
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{out_name}.mp4")
            
            size_map = {"720P": (1280, 720), "1080P": (1920, 1080), "4K": (3840, 2160)}
            size = size_map.get(menus["Độ phân giải"].get(), None)
            try:
                fps = int(menus["Tỷ lệ khung hình"].get().replace("fps", ""))
            except ValueError:
                fps = 30
            
            export_win.destroy()
            self._do_export_video(out_path, size=size, fps=fps,
                                  with_audio=bool(audio_check.get()))
        
        def browse_output():
            chosen = filedialog.askdirectory(title="Chọn thư mục lưu video",
                                             initialdir=default_path)
            if chosen:
                path_entry.delete(0, tk.END)
                path_entry.insert(0, chosen)
        
        ctk.CTkButton(path_frame, text="📁", width=40, height=35, fg_color="#333",
                      text_color="white", hover_color="#444",
                      command=browse_output).pack(side=tk.LEFT, padx=(5, 0))
        ctk.CTkButton(bottom_frame, text="Xuất", fg_color="#00E5FF", text_color="black", hover_color="#00C4DD", font=("Segoe UI", 13, "bold"), width=120, height=36, corner_radius=6, command=do_export).pack(side=tk.RIGHT)
    
    def _do_export_video(self, output_path, size=None, fps=None, with_audio=True):
        if not self.timeline_clips:
            messagebox.showwarning("Export", "The timeline has no clips.")
            return
        self._render_clips_to_file(self.timeline_clips, output_path, size=size, fps=fps,
                                   with_audio=with_audio)

    def _render_clips_to_file(self, clips, out_path, size=None, fps=None, with_audio=True):
        """Render clips through the player's own compositor.

        Frames are piped to ffmpeg as raw RGB and audio is mixed onto the
        timeline first, so the file cannot drift from what preview showed.
        """
        w, h = size or self._export_size()
        staged = self._stage_clips(clips)
        duration = max([c.start_time + c.duration for c in staged] or [0])
        if duration <= 0:
            messagebox.showwarning("Render", "Nothing to render.")
            return
        fps = fps or 30

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Rendering")
        dlg.geometry("420x170")
        dlg.transient(self.root)
        dlg.grab_set()
        bar = ctk.CTkProgressBar(dlg, width=320)
        bar.pack(pady=(22, 8))
        bar.set(0)
        status = ctk.CTkLabel(dlg, text="Starting...", text_color=UI_MUTED, font=self.PROPS_FONT)
        status.pack()
        state = {"cancel": False, "done": False}
        ctk.CTkButton(dlg, text="Cancel", width=100, height=30, fg_color=UI_FIELD,
                      hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER,
                      text_color=UI_TEXT, command=lambda: state.update(cancel=True)
                      ).pack(pady=10)
        dlg.protocol("WM_DELETE_WINDOW", lambda: state.update(cancel=True))

        def report(index, total):
            if state["done"]:
                return
            bar.set(index / max(1, total))
            status.configure(text="Frame %d / %d  (%.0f%%)"
                             % (index, total, 100.0 * index / max(1, total)))

        def finish():
            state["done"] = True
            dlg.grab_release()
            dlg.destroy()

        def show_result(ok, detail):
            finish()
            if ok:
                self.media_files.append(out_path)
                self.media_types.append("video")
                self.generate_thumbnail(out_path)
                self.refresh_thumbnails()
                self.set_status("Rendered %s" % os.path.basename(out_path))
                messagebox.showinfo("Render complete", "%s\n\n%s" % (out_path, detail))
            elif detail == "cancelled":
                self.set_status("Render cancelled")
            else:
                messagebox.showerror("Render failed", detail)

        def work():
            error = None
            try:
                self._ffmpeg_render(staged, out_path, w, h, fps, duration, report, state,
                                    with_audio)
            except Exception as exc:
                error = exc
            finally:
                self._close_staged(staged)
            if error is None:
                self.root.after(0, lambda: show_result(True, "%dx%d @ %dfps%s"
                                                       % (w, h, fps,
                                                          "" if with_audio else ", silent")))
            elif str(error) == "cancelled":
                self.root.after(0, lambda: show_result(False, "cancelled"))
            else:
                self.root.after(0, lambda: show_result(
                    False, "%s: %s" % (type(error).__name__, error)))

        self.root.after(60, lambda: threading.Thread(target=work, daemon=True).start())

    def _export_size(self):
        ratio_map = {
            "16:9": (1920, 1080), "3:2": (1920, 1280), "4:3": (1600, 1200),
            "1:1": (1080, 1080), "9:16": (1080, 1920), "21:9": (2560, 1080),
        }
        return ratio_map.get(getattr(self, "aspect_ratio", "16:9"), (1920, 1080))

    def _ffmpeg_render(self, clips, out_path, w, h, fps, duration, report, state,
                       with_audio=True):
        import subprocess
        exe = asr_ffmpeg_path()
        if not exe:
            raise RuntimeError("ffmpeg not found. Install it, or keep the "
                               "AsrTools-v1.1.0 folder next to Clinging.")
        total = max(1, int(round(duration * fps)))
        wav = self._mix_audio_wav(clips, duration) if with_audio else None

        def spawn(with_audio):
            cmd = [exe, "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                   "-s", "%dx%d" % (w, h), "-r", str(fps), "-i", "-"]
            if with_audio and wav:
                cmd += ["-i", wav, "-c:a", "aac", "-b:a", "192k", "-shortest"]
            else:
                cmd += ["-an"]
            cmd += ["-map", "0:v:0", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

        proc = spawn(True)
        try:
            for index in range(total):
                if state.get("cancel"):
                    raise RuntimeError("cancelled")
                frame, _ = self._compose_clips(clips, index / float(fps), w, h)
                proc.stdin.write(frame.convert("RGB").tobytes())
                if index % 5 == 0 or index == total - 1:
                    self.root.after(0, lambda i=index: report(i + 1, total))
            proc.stdin.close()
        except Exception:
            proc.kill()
            proc.wait()
            self._discard_partial(out_path)
            raise
        err = proc.stderr.read().decode("utf-8", "replace")
        rc = proc.wait()
        if rc != 0 and wav:
            # The audio encoder is the only optional piece here; retry video-only.
            self._discard_partial(out_path)
            proc = spawn(False)
            err = proc.stderr.read().decode("utf-8", "replace")
            rc = proc.wait()
        if rc != 0:
            self._discard_partial(out_path)
            raise RuntimeError(err.strip()[-400:] or "ffmpeg exited with %d" % rc)
        if wav:
            try:
                os.remove(wav)
            except OSError:
                pass

    def _discard_partial(self, out_path):
        try:
            if os.path.exists(out_path) and os.path.getsize(out_path) < 1024:
                os.remove(out_path)
        except OSError:
            pass

    def _mix_audio_wav(self, clips, duration):
        """Lay every clip's audio on the timeline and return a stereo wav path."""
        import subprocess
        import tempfile
        import wave
        rate, channels = 44100, 2
        samples = int(round(duration * rate)) * channels
        master = np.zeros(samples, dtype=np.float32)
        exe = asr_ffmpeg_path()
        if not exe:
            return None
        work_dir = os.path.join(tempfile.gettempdir(), "clinging_render")
        os.makedirs(work_dir, exist_ok=True)
        found = False
        for clip in clips:
            if clip.clip_type not in ("video", "audio") or not clip.file_path:
                continue
            if not os.path.exists(clip.file_path):
                continue
            slot = abs(hash((clip.file_path, clip.start_time))) % 10 ** 9
            raw = os.path.join(work_dir, "seg_%d.f32" % slot)
            cmd = [exe, "-loglevel", "error", "-y", "-t", str(max(0.01, clip.duration)),
                   "-i", clip.file_path, "-vn", "-ac", str(channels), "-ar", str(rate),
                   "-f", "f32le", raw]
            try:
                if subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode != 0:
                    continue
                data = np.fromfile(raw, dtype=np.float32)
            except Exception:
                continue
            finally:
                try:
                    os.remove(raw)
                except OSError:
                    pass
            start = int(round(clip.start_time * rate)) * channels
            end = min(len(master), start + len(data))
            if end > start:
                master[start:end] += data[:end - start]
                found = True
        if not found or not np.any(master):
            return None
        pcm = (np.clip(master, -1.0, 1.0) * 32767.0).astype("<i2")
        out_path = os.path.join(work_dir, "mix_%d_%d.wav" % (os.getpid(), int(time.time() * 1000)))
        with wave.open(out_path, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(pcm.tobytes())
        return out_path

    def _stage_clips(self, clips):
        """Copy clips onto a timeline that starts at zero, keeping every visual
        setting; the originals stay untouched. mv_clip is deliberately not shared:
        the render thread must not read through the player's decoder."""
        offset = min(c.start_time for c in clips)
        staged = []
        for c in clips:
            twin = TimelineClip(c.file_path, c.start_time - offset, c.duration,
                                c.clip_type, c.track_idx)
            twin.text_content = getattr(c, 'text_content', '')
            twin.font = getattr(c, 'font', 'Arial')
            twin.font_size = getattr(c, 'font_size', 32)
            twin.text_color = getattr(c, 'text_color', '#FFFFFF')
            twin.bg_color = getattr(c, 'bg_color', '#000000')
            twin.x_pos = getattr(c, 'x_pos', 320)
            twin.y_pos = getattr(c, 'y_pos', 180)
            twin.motion_effect = getattr(c, 'motion_effect', 'none')
            twin.motion_intensity = getattr(c, 'motion_intensity', 5)
            twin.text_effect = getattr(c, 'text_effect', 'none')
            twin.text_intensity = getattr(c, 'text_intensity', 5)
            staged.append(twin)
        return staged

    def _close_staged(self, staged):
        """The render thread opens its own decoders; release them when it ends."""
        for twin in staged:
            if twin.clip_type == 'video' and twin.mv_clip is not None:
                try:
                    twin.mv_clip.close()
                except Exception:
                    pass
                twin.mv_clip = None
    
    def split_video(self):
        messagebox.showinfo("Split", "Split feature coming soon!")
    
    def start_video_cut(self):
        try:
            num_segments = int(self.cut_segments_entry.get())
            if num_segments <= 0:
                messagebox.showwarning("Lỗi", "Số đoạn cắt phải lớn hơn 0")
                return
        except ValueError:
            messagebox.showwarning("Lỗi", "Vui lòng nhập số đoạn hợp lệ")
            return
        
        if not MOVIEPY_AVAILABLE:
            messagebox.showerror("Lỗi", "MoviePy không khả dụng")
            return
        
        from tkinter import filedialog
        save_dir = filedialog.askdirectory(title="Chọn thư mục lưu video đã cắt")
        if not save_dir:
            return
        
        project_name = getattr(self, 'project_name', "Project")
        if not project_name:
            project_name = "Project"
        
        clip = self.selected_clips[0]
        video_path = clip.file_path
        
        self.cutting = True
        self.cancel_cut = False
        self.cut_start_btn.configure(state="disabled")
        self.cut_cancel_btn.configure(state="normal")
        self.cut_status_label.configure(text="Đang cắt...")
        
        def run_cut():
            from src.logic import cut_video_logic
            import time
            
            def progress_callback(current, total, info=None):
                if info:
                    percent = int((info['segment'] / info['total']) * 100)
                    output_size = info.get('output_size', 0)
                    duration_str = info.get('duration_str', '00:00')
                    project_n = info.get('project_name', '')
                    
                    status_text = f"Đoạn {info['segment']}/{info['total']} | {duration_str} | {output_size:.1f}MB | {percent}%"
                else:
                    percent = int(current / total * 100)
                    status_text = f"Đang cắt {current}/{total}... {percent}%"
                
                self.root.after(0, lambda: self.cut_progress.set(percent / 100))
                self.root.after(0, lambda: self.cut_status_label.configure(text=status_text))
            
            def cancel_callback():
                return self.cancel_cut
            
            try:
                cut_video_logic(self, MOVIEPY, video_path, num_segments, save_dir, project_name, progress_callback, cancel_callback)
            except Exception as e:
                # Python giải phóng `e` khi khối except kết thúc, nên lambda phải
                # giữ sẵn chuỗi lỗi, không tham chiếu `e` muộn.
                error_text = str(e)
                self.root.after(0, lambda: messagebox.showerror("Lỗi", error_text))
            
            self.root.after(0, self._finish_cut)
        
        import threading
        t = threading.Thread(target=run_cut, daemon=True)
        t.start()
    
    def _finish_cut(self):
        self.cutting = False
        self.cut_start_btn.configure(state="normal")
        self.cut_cancel_btn.configure(state="disabled")
        
        if self.cancel_cut:
            self.cut_status_label.configure(text="Đã huỷ")
        else:
            self.cut_status_label.configure(text="Hoàn thành!")
        self.cut_progress.set(0)
    
    def cancel_video_cut(self):
        if self.cutting:
            self.cancel_cut = True
            self.cut_status_label.configure(text="Đang huỷ...")
    
    def merge_videos(self):
        messagebox.showinfo("Merge", "Merge feature coming soon!")
    
    def crop_video(self):
        messagebox.showinfo("Crop", "Crop feature coming soon!")
    
    def trim_video(self):
        messagebox.showinfo("Trim", "Trim feature coming soon!")
    
    def save_project(self):
        import json
        import os
        import random
        from datetime import datetime
        
        clips_data = []
        for c in self.timeline_clips:
            clip_info = {
                "file_path": c.file_path,
                "start_time": c.start_time,
                "duration": c.duration,
                "clip_type": c.clip_type,
                "track_idx": c.track_idx,
                "is_pinned": c.is_pinned,
                "group_id": c.group_id,
                "x_pos": getattr(c, 'x_pos', 320),
                "y_pos": getattr(c, 'y_pos', 180),
                "motion_effect": getattr(c, "motion_effect", "none"),
                "motion_intensity": getattr(c, "motion_intensity", 5),
                "text_effect": getattr(c, "text_effect", "none"),
                "text_intensity": getattr(c, "text_intensity", 5)
            }
            if c.clip_type == "text":
                clip_info["text_content"] = getattr(c, "text_content", "Text")
                clip_info["font_size"] = getattr(c, "font_size", 36)
                clip_info["text_color"] = getattr(c, "text_color", "white")
                clip_info["bg_color"] = getattr(c, "bg_color", "transparent")
            clips_data.append(clip_info)
            
        thumb_path = getattr(self, "project_thumb", "")
        if not thumb_path:
            for c in self.timeline_clips:
                if c.clip_type in ['video', 'image'] and c.file_path in self.thumbnails:
                    img = self.thumbnails[c.file_path]
                    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
                    thumbs_dir = os.path.join(data_dir, "thumbs")
                    os.makedirs(thumbs_dir, exist_ok=True)
                    pid = getattr(self, "project_id", None) or os.urandom(4).hex()
                    self.project_id = pid
                    thumb_file = os.path.join(thumbs_dir, f"{pid}.jpg")
                    try:
                        img_rgb = img.convert("RGB")
                        img_rgb.save(thumb_file, "JPEG")
                        thumb_path = thumb_file
                        self.project_thumb = thumb_path
                    except Exception as e:
                        print("Error saving thumb:", e)
                    break

        dur_sec = self.get_total_duration()
        m = int(dur_sec // 60)
        s = int(dur_sec % 60)
        
        proj_id = getattr(self, "project_id", None) or os.urandom(4).hex()
        proj_data = {
            "id": proj_id,
            "name": getattr(self, "project_name", f"Dự án {datetime.now().strftime('%m%d')}"),
            "clips": clips_data,
            "duration": f"{m:02d}:{s:02d}",
            "size": f"{len(clips_data) * 5 + random.randint(1, 10)}MB",
            "time_str": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "thumb_path": thumb_path,
            "project_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "projects", proj_id)
        }
        self.project_id = proj_data["id"]
        
        projects_file = "projects.json"
        projects = []
        if os.path.exists(projects_file):
            try:
                with open(projects_file, 'r', encoding='utf-8') as f:
                    projects = json.load(f)
            except:
                pass
                
        found = False
        for i, p in enumerate(projects):
            if p.get("id") == proj_data["id"]:
                projects[i] = proj_data
                found = True
                break
        if not found:
            projects.insert(0, proj_data)
            
        with open(projects_file, 'w', encoding='utf-8') as f:
            json.dump(projects, f, ensure_ascii=False, indent=4)
            
        messagebox.showinfo("Lưu dự án", "Đã lưu dự án thành công!")
    
    def run(self):
        self.root.mainloop()

class HomeWindow:
    def __init__(self):
        import json
        import os
        self.projects_file = "projects.json"
        self.projects = []
        self.home_images = []
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        self.projects_dir = os.path.join(self.data_dir, "projects")
        self.thumbs_dir = os.path.join(self.data_dir, "thumbs")
        self.outputs_dir = os.path.join(self.data_dir, "outputs")
        
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.thumbs_dir, exist_ok=True)
        os.makedirs(self.outputs_dir, exist_ok=True)
        
        if os.path.exists(self.projects_file):
            try:
                with open(self.projects_file, 'r', encoding='utf-8') as f:
                    self.projects = json.load(f)
            except:
                pass
                
        for proj in self.projects:
            if "project_dir" not in proj:
                proj["project_dir"] = os.path.join(self.projects_dir, proj.get("id", ""))
                os.makedirs(proj["project_dir"], exist_ok=True)
                
        ctk.set_appearance_mode("Dark")
        self.root = ctk.CTk()
        self.root.title("Clinging - Trang chủ")
        self.root.geometry("1100x750")
        self.root.configure(fg_color="#181818")
        
        self.create_ui()
        
    def create_ui(self):
        # Left Sidebar
        sidebar = ctk.CTkFrame(self.root, width=220, fg_color="#181818", corner_radius=0)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        
        # Profile section
        profile_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        profile_frame.pack(pady=20, padx=15, fill=tk.X)
        ctk.CTkLabel(profile_frame, text="Clinging Editor\nPhiên bản Cá Nhân", text_color="white", font=("Segoe UI", 16, "bold")).pack()
        
        # Menu items
        ctk.CTkButton(sidebar, text="🏠 Trang chủ", fg_color="#2B2B2B", text_color="white", anchor="w", corner_radius=8).pack(fill=tk.X, padx=15, pady=5)
        
        # Bottom left promos
        promo_frame = ctk.CTkFrame(sidebar, fg_color="#2B2B2B", corner_radius=10)
        promo_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=20)
        ctk.CTkLabel(promo_frame, text="💡 Được đề xuất\nPhụ đề tự động", text_color="white", anchor="w", justify=tk.LEFT).pack(padx=10, pady=10)
        
        # Main Content Area
        main_content = ctk.CTkFrame(self.root, fg_color="#0A0A0A", corner_radius=0)
        main_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Top banner / Create Project
        banner = ctk.CTkFrame(main_content, height=140, fg_color="#1E3A8A", corner_radius=15)
        banner.pack(fill=tk.X, padx=30, pady=(30, 20))
        banner.pack_propagate(False)
        
        create_btn = ctk.CTkButton(banner, text="➕ Tạo dự án", font=("Segoe UI", 18, "bold"), fg_color="white", text_color="black", hover_color="#E0E0E0", height=45, corner_radius=8, command=self.open_editor)
        create_btn.place(relx=0.5, rely=0.5, anchor="center")
        
        # Quick tools
        tools_frame = ctk.CTkFrame(main_content, fg_color="transparent")
        tools_frame.pack(fill=tk.X, padx=30, pady=(0, 20))
        
        tools = [("🎥", "Ghi màn hình"), ("👤", "Tự động cắt ảnh"), ("✨", "Cải thiện chất lượng")]
        for icon, text in tools:
            btn_frame = ctk.CTkFrame(tools_frame, fg_color="#2B2B2B", corner_radius=8, height=60)
            btn_frame.pack(side=tk.LEFT, expand=True, padx=5, fill=tk.X)
            btn_frame.pack_propagate(False)
            ctk.CTkLabel(btn_frame, text=f"{icon}  {text}", text_color="white", font=("Segoe UI", 13, "bold")).place(relx=0.5, rely=0.5, anchor="center")
            
        # Projects Section
        projects_header = ctk.CTkFrame(main_content, fg_color="transparent")
        projects_header.pack(fill=tk.X, padx=30, pady=10)
        ctk.CTkLabel(projects_header, text=f"Dự án ({len(self.projects)})", font=("Segoe UI", 16, "bold"), text_color="white").pack(side=tk.LEFT)
        
        search_frame = ctk.CTkFrame(projects_header, fg_color="transparent")
        search_frame.pack(side=tk.RIGHT)
        ctk.CTkButton(search_frame, text="🗑 Xoá tất cả", fg_color="#8B0000", text_color="white", width=100, hover_color="#B22222", command=self.delete_all_projects).pack(side=tk.LEFT, padx=5)
        
        # Project Grid
        projects_grid = ctk.CTkScrollableFrame(main_content, fg_color="transparent")
        projects_grid.pack(fill=tk.BOTH, expand=True, padx=20)
        
        if not self.projects:
            empty_lbl = ctk.CTkLabel(projects_grid, text="Danh sách dự án trống.\nHãy tạo dự án mới!", text_color="#555", font=("Segoe UI", 14))
            empty_lbl.pack(pady=50)
        else:
            row, col = 0, 0
            for i, proj in enumerate(self.projects):
                p_frame = ctk.CTkFrame(projects_grid, fg_color="transparent", width=140, height=180)
                p_frame.grid(row=row, column=col, padx=10, pady=10)
                p_frame.grid_propagate(False)
                
                thumb = ctk.CTkFrame(p_frame, fg_color="#1E1E1E", width=140, height=100, corner_radius=10, cursor="hand2")
                thumb.pack(fill=tk.X)
                
                thumb.bind("<Button-1>", lambda e, p=proj: self.open_editor(p))
                thumb.bind("<Button-3>", lambda e, p=proj: self.show_project_menu(e, p))
                
                drawn = False
                thumb_path = proj.get("thumb_path", "")
                if thumb_path and os.path.exists(thumb_path):
                    try:
                        img = Image.open(thumb_path)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(136, 96))
                        self.home_images.append(ctk_img)
                        lbl = ctk.CTkLabel(thumb, image=ctk_img, text="")
                        lbl.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
                        lbl.bind("<Button-1>", lambda e, p=proj: self.open_editor(p))
                        drawn = True
                    except:
                        pass
                
                if not drawn:
                    colors = ["#2B1B4A", "#4A1B2E", "#1B4A3A", "#1B364A"]
                    color = colors[i % len(colors)]
                    inner = ctk.CTkFrame(thumb, fg_color=color, corner_radius=8)
                    inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
                    inner.bind("<Button-1>", lambda e, p=proj: self.open_editor(p))
                    inner.bind("<Button-3>", lambda e, p=proj: self.show_project_menu(e, p))
                else:
                    lbl.bind("<Button-3>", lambda e, p=proj: self.show_project_menu(e, p))
                
                ctk.CTkLabel(p_frame, text=proj.get("name", f"Dự án {i+1}"), text_color="white", font=("Segoe UI", 12, "bold"), anchor="w").pack(fill=tk.X, pady=(8, 2))
                ctk.CTkLabel(p_frame, text=proj.get("size", "0MB") + " | " + proj.get("duration", "00:00"), text_color="#888", font=("Segoe UI", 11), anchor="w").pack(fill=tk.X)
                
                col += 1
                if col >= 5:
                    col = 0
                    row += 1
                
    def open_editor(self, project_data=None):
        self.root.destroy()
        app = ClingingApp(project_data)
        app.run()
    
    def show_project_menu(self, event, project):
        menu = tk.Menu(self.root, tearoff=0, bg="#2B2B2B", fg="white")
        menu.add_command(label="📂 Mở trong trình chỉnh sửa", command=lambda: self.open_editor(project))
        menu.add_separator()
        menu.add_command(label="📁 Mở đường dẫn tệp", command=lambda: self.open_project_folder(project))
        menu.add_command(label="🗑 Xoá dự án", command=lambda: self.delete_project(project))
        
        menu.tk_popup(event.x_root, event.y_root)
    
    def open_project_folder(self, project):
        project_dir = project.get("project_dir", "")
        if project_dir and os.path.exists(project_dir):
            os.startfile(project_dir)
        else:
            project_path = os.path.join(self.projects_dir, project.get("id", ""))
            if os.path.exists(project_path):
                os.startfile(project_path)
            else:
                os.startfile(self.data_dir)
    
    def delete_project(self, project):
        proj_id = project.get("id", "")
        if not proj_id:
            return
            
        proj_name = project.get("name", "dự án")
        if messagebox.askyesno("Xoá dự án", f"Bạn có muốn xoá dự án '{proj_name}' này không?"):
            self.projects = [p for p in self.projects if p.get("id") != proj_id]
            with open(self.projects_file, 'w', encoding='utf-8') as f:
                json.dump(self.projects, f, ensure_ascii=False, indent=4)
            self.root.destroy()
            HomeWindow().run()
    
    def delete_all_projects(self):
        if not self.projects:
            return
        if messagebox.askyesno("Xoá tất cả", "Bạn có muốn xoá tất cả dự án không?"):
            self.projects = []
            with open(self.projects_file, 'w', encoding='utf-8') as f:
                json.dump(self.projects, f, ensure_ascii=False, indent=4)
            self.root.destroy()
            HomeWindow().run()
        
    def run(self):
        self.root.mainloop()

def main():
    app = HomeWindow()
    app.run()

if __name__ == "__main__":
    main()