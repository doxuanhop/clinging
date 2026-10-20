"""Replace the Motion-tab block in main.py with the live-effect implementation."""
import io

MAIN = "main.py"
BLOCK = "scratch/motion_block.txt"
START, END = 2311, 2497  # 1-based, inclusive

with io.open(MAIN, encoding="utf-8", newline="") as fh:
    lines = fh.read().split("\n")

assert lines[START - 1].strip().startswith("def render_motion_graphics_tab"), lines[START - 1]
assert lines[END - 1].strip().startswith("messagebox.showinfo(\"Bounce"), lines[END - 1]

with io.open(BLOCK, encoding="utf-8", newline="") as fh:
    block = fh.read().rstrip("\n").split("\n")

out = lines[:START - 1] + block + lines[END:]
with io.open(MAIN, "w", encoding="utf-8", newline="") as fh:
    fh.write("\n".join(out))

print("replaced %d lines with %d; file now %d lines" % (END - START + 1, len(block), len(out)))
