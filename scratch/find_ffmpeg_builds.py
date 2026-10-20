"""Tim ban ffmpeg/ffprobe nho nhat co tren may nay de dong goi kem installer."""
import os
import sys

SKIP = {"windows", "windows.old", "program files", "program files (x86)",
        "programdata", "appdata", "system volume information",
        "$recycler.bin", "perflogs", "recovery", "temp"}
HITS = {}


def scan(base, depth, budget):
    if depth > 6 or budget[0] <= 0:
        return
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        budget[0] -= 1
        if budget[0] <= 0:
            return
        path = os.path.join(base, name)
        try:
            if name.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                if os.path.isfile(path):
                    HITS.setdefault(os.path.dirname(path), []).append(
                        (name, round(os.path.getsize(path) / 1e6, 1)))
            elif os.path.isdir(path) and name.lower() not in SKIP:
                scan(path, depth + 1, budget)
        except OSError:
            pass


for root in sys.argv[1:]:
    scan(root, 0, [60000])

for folder, rows in sorted(HITS.items()):
    print(folder, rows)
print("dirs:", len(HITS))
