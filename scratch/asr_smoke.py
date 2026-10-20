import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.asr import (ASRData, ASRDataSeg, CLOUD_ENGINES, NATIVE_FORMATS, engine_class,
                     requires_audio, to_segments, from_subtitle_file)

print("engines:", [n for n, _ in CLOUD_ENGINES])
print("classes:", [c.__name__ for _, c in CLOUD_ENGINES])
print("engine_class('JianYing (CapCut)') ->", engine_class("JianYing (CapCut)").__name__)
print("requires_audio('a.mp4')", requires_audio("a.mp4"), "| 'a.wav'", requires_audio("a.wav"),
      "| 'a.m4a'", requires_audio("a.m4a"), "| 'noext'", requires_audio("noext"))

data = ASRData([ASRDataSeg("xin chao", 0, 1400),
               ASRDataSeg("the next line\ntranslated", 1400, 3250)])
print("srt:\n" + data.to_srt())
print("ass head:", data.to_ass().splitlines()[10:12])
print("json:", data.to_json())
segs = to_segments(data)
print("to_segments:", segs)
print("empty-text filter:", to_segments(ASRData([ASRDataSeg("   ", 0, 10)])))

srt = "1\n00:00:00,000 --> 00:00:01,400\nhello there\n\n2\n00:00:01,400 --> 00:00:03,250\ncaption two\n"
back = from_subtitle_file.__globals__["from_srt"](srt)
print("roundtrip srt ->", to_segments(back))

ass = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
       "Dialogue: 0,0:00:01.20,0:00:02.75,Default,,0,0,0,,one two three\n")
print("ass ->", to_segments(from_subtitle_file.__globals__["from_ass"](ass)))

# BaseASR format assertion + binary path support
from src.asr.BaseASR import BaseASR
print("supported:", BaseASR.SUPPORTED_SOUND_FORMAT, "| cache:", os.path.basename(BaseASR.CACHE_FILE))
b = BaseASR(b"fake-bytes")
print("crc32 from bytes:", b.crc32_hex, "len:", len(b.file_binary))

import requests
print("requests ok:", requests.__version__)
