import sys, time, json
sys.path.insert(0, ".")
import main

media = sys.argv[1]
engine = sys.argv[2] if len(sys.argv) > 2 else "Bcut (Bilibili)"

exe = main.asr_ffmpeg_path()
print("ffmpeg:", exe)

audio, is_temp = main.asr_audio_for_upload(media)
print("upload audio:", audio, "temp:", is_temp, "bytes:", __import__("os").path.getsize(audio))

asr = main.asr_module()
print("requires_audio ->", asr.requires_audio(media), "| engine:", asr.engine_class(engine).__name__)

t0 = time.time()
data = asr.engine_class(engine)(audio, use_cache=True).run()
segs = asr.to_segments(data)
print("elapsed %.1fs | segments %d" % (time.time() - t0, len(segs)))
for s in segs[:8]:
    print("  [%7d -> %7d] %s" % (s["start_ms"], s["end_ms"], s["text"][:70]))

out = main.asr_data_to_file(data, "scratch/e2c_%s.srt" % engine.split()[0])
print("wrote", out)
with open(out, encoding="utf-8") as f:
    print("--- srt head ---")
    print(f.read()[:400])
