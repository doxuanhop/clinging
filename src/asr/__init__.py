"""ASR engines vendored from AsrTools-v1.1.0 (bk_asr).

Cloud transcribers used by the editor's Auto Captions feature: Bcut (Bilibili),
JianYing (CapCut) and KuaiShou. Transcripts come back as ASRData segments in
milliseconds; the editor turns those into subtitle files and timeline clips.
"""

from .ASRData import ASRData, ASRDataSeg, from_subtitle_file
from .BcutASR import BcutASR
from .JianYingASR import JianYingASR
from .KuaiShouASR import KuaiShouASR

# Label -> engine class. Measured against the live services: Bcut transcribes,
# KuaiShou's endpoint replies "disabled" and JianYing returns an empty task id,
# so the editor's picker only offers Bcut plus the local fallback.
CLOUD_ENGINES = [
    ("Bcut (Bilibili)", BcutASR),
    ("KuaiShou", KuaiShouASR),
    ("JianYing (CapCut)", JianYingASR),
]

# Formats BaseASR will read straight from disk; anything else needs ffmpeg first.
NATIVE_FORMATS = ("mp3", "wav", "m4a", "flac")

__all__ = ["ASRData", "ASRDataSeg", "CLOUD_ENGINES", "NATIVE_FORMATS",
           "BcutASR", "JianYingASR", "KuaiShouASR", "from_subtitle_file",
           "engine_class", "requires_audio", "to_segments"]


def engine_class(label):
    for name, cls in CLOUD_ENGINES:
        if name == label:
            return cls
    raise ValueError("Unknown ASR engine: %s" % label)


def requires_audio(path):
    """True when the cloud engines cannot upload this file as-is."""
    ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
    return ext not in NATIVE_FORMATS


def to_segments(asr_data):
    """ASRData -> plain dicts, so callers never depend on the engine classes."""
    return [{"text": seg.text.strip(),
             "start_ms": int(seg.start_time),
             "end_ms": int(seg.end_time)}
            for seg in asr_data.segments if seg.text.strip()]
