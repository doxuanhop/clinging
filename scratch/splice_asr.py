with open("main.py", encoding="utf-8", newline="") as f:
    src = f.read()
orig_lines = src.count(chr(10))

with open("scratch/asr_block.py", encoding="utf-8", newline="") as f:
    block = f.read()

START = "    def _auto_captions(self):" + chr(10)
END = "    def _add_default_text(self):" + chr(10)
assert src.count(START) == 1 and src.count(END) == 1
i, j = src.index(START), src.index(END)
src = src[:i] + block + src[j:]

DUP = r'''    # Removed duplicate _auto_captions

    def _import_subtitles(self):
        file = filedialog.askopenfilename(filetypes=[("Subtitle files", "*.srt *.ass *.ssa")])
        if file:
            messagebox.showinfo("Import Subtitles", f"Đã chọn file: {os.path.basename(file)}\n\nTính năng đang phát triển!")

'''
if DUP in src:
    src = src.replace(DUP, "")
    print("duplicate stub removed")
else:
    print("WARNING: duplicate stub not matched")

with open("main.py", "w", encoding="utf-8", newline="") as f:
    f.write(src)

print("lines", orig_lines, "->", src.count(chr(10)))
for probe in ("def _auto_captions", "def _import_subtitles", "def _asr_clips", "def _run_asr",
              "def _asr_write", "def _asr_default_media", "Tinh năng đang phát triển"):
    print(probe, "=", src.count(probe))
