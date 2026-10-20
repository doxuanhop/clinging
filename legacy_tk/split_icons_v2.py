from PIL import Image
import os

img_path = r'C:\Users\doxuanhop\.gemini\antigravity\brain\94f5f29c-27c0-4c8c-b8f6-a3d2e2fc69ed\editor_icons_grid_2_1776824835229.png'
out_dir = r'd:\tool\clinging\icons'
os.makedirs(out_dir, exist_ok=True)

img = Image.open(img_path)
w, h = img.size
cell_w = w // 4
cell_h = h // 4

icons = [
    "menu", "undo", "redo", "freeze",
    "reverse", "mirror", "rotate_cw", "aspect_ratio",
    "search", "folder", "cloud", "settings"
]

for i, name in enumerate(icons):
    r = i // 4
    c = i % 4
    left = c * cell_w
    top = r * cell_h
    right = left + cell_w
    bottom = top + cell_h
    
    icon = img.crop((left, top, right, bottom))
    icon.save(os.path.join(out_dir, f"{name}.png"))

print("Icons Set 2 split successfully.")
