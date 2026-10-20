"""Unit evidence for src/anim.py, before it is wired into the editor.

Renders every motion effect and every text effect over a synthetic frame at five
progress values, measures whether the result actually changes over time, and
writes two labelled filmstrips so the animation can be inspected as images.

Usage: python scratch/anim_unit.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import anim

OUT = os.path.join(ROOT, "scratch")
W, H = 320, 180
# Marquee/loop effects can land on the same phase at quarter steps, so the
# verdict uses a dense sweep while the filmstrip shows an evenly spaced subset.
PS = [i / 8.0 for i in range(9)]
STRIP = [0.0, 0.25, 0.5, 0.75, 1.0]


def test_frame():
    img = Image.new("RGBA", (W, H), (18, 22, 30, 255))
    draw = ImageDraw.Draw(img)
    for i in range(0, W, 20):
        draw.line((i, 0, i + 40, H), fill=(40, 48, 62, 255), width=2)
    draw.rectangle((W // 2 - 45, H // 2 - 30, W // 2 + 45, H // 2 + 30),
                   fill=(0, 229, 255, 255), outline=(255, 255, 255, 255))
    draw.ellipse((14, 14, 54, 54), fill=(255, 92, 92, 255))
    draw.ellipse((W - 54, H - 54, W - 14, H - 14), fill=(255, 214, 90, 255))
    draw.text((W // 2, H // 2), "SRC", fill=(6, 20, 26, 255), anchor="mm")
    return img


def label_font():
    try:
        return ImageFont.truetype("arial.ttf", 13)
    except Exception:
        return ImageFont.load_default()


def filmstrip(rows, path, title):
    font = label_font()
    tile_w, tile_h = W, H
    pad, label_w = 6, 118
    cols = max(len(frames) for _, frames in rows)
    sheet = Image.new("RGB", (label_w + (tile_w + pad) * cols + pad,
                              34 + (tile_h + pad) * len(rows) + pad), (16, 16, 20))
    sheet_draw = ImageDraw.Draw(sheet)
    sheet_draw.text((8, 8), title, fill=(150, 220, 255, 255), font=font)
    y = 30
    for name, frames in rows:
        sheet_draw.text((8, y + tile_h // 2 - 8), name, fill=(230, 230, 230, 255), font=font)
        x = label_w
        for f in frames:
            bg = Image.new("RGB", (tile_w, tile_h), (10, 10, 14))
            bg.paste(f, (0, 0), f if f.mode == "RGBA" else None)
            sheet.paste(bg, (x, y))
            x += tile_w + pad
        y += tile_h + pad
    sheet.save(path)
    print("saved", path, sheet.size)


def stats(frames, reference):
    """Animation must be judged per changed pixel, not as a whole-frame mean:
    a caption covers ~0.5% of the canvas, so even a full white/black flip stays
    invisible in a mean. changed = widest single step of pixels moving >16."""
    steps = [np.abs(np.asarray(b, dtype=np.int16) - np.asarray(a, dtype=np.int16)).mean()
             for a, b in zip(frames, frames[1:])]
    moved = []
    for a, b in zip(frames, frames[1:]):
        d = np.abs(np.asarray(b, dtype=np.int16) - np.asarray(a, dtype=np.int16)).max(axis=2)
        moved.append(float((d > 16).sum()) * 100.0 / (W * H))
    peak = float(np.mean(steps)) * 100 / 255 if steps else 0.0
    end_vs_start = float(np.abs(np.asarray(frames[-1], dtype=np.int16) -
                               np.asarray(frames[0], dtype=np.int16)).mean()) * 100 / 255
    return round(peak, 2), round(max(moved) if moved else 0.0, 3), round(end_vs_start, 2)


def strip_frames(frames):
    return [frames[i] for i in (0, 2, 4, 6, 8)]


def main():
    base = test_frame()
    ref = [base] * len(PS)
    results = []

    print("== MOTION ==")
    motion_rows = []
    for key, name, _ in anim.MOTION_EFFECTS:
        frames = [anim.apply_motion(base, key, p, 5) for p in PS]
        mean, moved, end_vs = stats(frames, ref)
        verdict = "static (expected)" if key == "none" else (
            "animated" if moved > 0.05 else "NO MOTION")
        results.append(("motion:" + key, verdict))
        print("%-11s moved=%-7s%% mean=%-6s end_vs_start=%-6s %s"
              % (key, moved, mean, end_vs, verdict))
        motion_rows.append((name, strip_frames(frames)))
    filmstrip(motion_rows, os.path.join(OUT, "anim_grid_motion.png"),
              "src/anim.py motion effects - p = 0.00 / 0.25 / 0.50 / 0.75 / 1.00")

    print("== TEXT ==")
    canvas = Image.new("RGBA", (W, H), (12, 14, 18, 255))
    text_rows = []
    sample = "Chữ chạy"
    for key, name, _ in anim.TEXT_EFFECTS:
        frames = []
        for p in PS:
            layer = anim.text_layer((W, H), sample, effect=key, p=p, intensity=5,
                                    font_size=34, color="#FFFFFF", pos=(0.5, 0.5))
            frame = canvas.copy()
            frame.alpha_composite(layer)
            frames.append(frame)
        mean, moved, end_vs = stats(frames, ref)
        verdict = "static (expected)" if key == "none" else (
            "animated" if moved > 0.05 else "NO MOTION")
        results.append(("text:" + key, verdict))
        print("%-15s moved=%-7s%% mean=%-6s end_vs_start=%-6s %s"
              % (key, moved, mean, end_vs, verdict))
        text_rows.append((name, strip_frames(frames)))
    filmstrip(text_rows, os.path.join(OUT, "anim_grid_text.png"),
              "src/anim.py text effects - p = 0.00 / 0.25 / 0.50 / 0.75 / 1.00")

    # Gate: every effect must move, and "none" must not - otherwise the probe
    # itself is lying and the numbers above mean nothing.
    failures = [name for name, verdict in results
                if verdict != ("static (expected)" if name.endswith(":none") else "animated")]
    print("\nGATE: %d effects checked, %d failures" % (len(results), len(failures)))
    for name in failures:
        print("  FAIL", name, "->", dict(results)[name])
    return 1 if failures else 0


sys.exit(main())
