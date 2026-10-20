"""Replace a method range in main.py with a block file, matching on def lines.

Usage: python scratch/splice_range.py <start_marker> <end_marker> <block_file>
Replaces from the line starting with start_marker up to (not including) the
line starting with end_marker, preserving the blank line that ends the method.
"""
import io
import sys

start_marker, end_marker, block_file = sys.argv[1], sys.argv[2], sys.argv[3]

with io.open("main.py", encoding="utf-8", newline="") as fh:
    lines = fh.read().split("\n")

starts = [i for i, l in enumerate(lines) if l.strip().startswith(start_marker)]
ends = [i for i, l in enumerate(lines) if l.strip().startswith(end_marker)]
assert len(starts) == 1, "start marker not unique: %r -> %s" % (start_marker, starts)
assert len(ends) == 1, "end marker not unique: %r -> %s" % (end_marker, ends)
start, end = starts[0], ends[0]
assert start < end, (start, end)

# Keep the indentation-only blank line that separates methods.
tail = end
while tail - 1 > start and not lines[tail - 1].strip():
    tail -= 1

with io.open(block_file, encoding="utf-8", newline="") as fh:
    block = fh.read().rstrip("\n").split("\n")

out = lines[:start] + block + ["    "] + lines[end:]
with io.open("main.py", "w", encoding="utf-8", newline="") as fh:
    fh.write("\n".join(out))
print("replaced lines %d-%d (%d) with %d lines" % (start + 1, tail, tail - start, len(block)))
