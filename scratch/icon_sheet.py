import sys, os
sys.path.insert(0, os.path.abspath("."))
import tkinter as tk
import customtkinter as ctk
root = ctk.CTk(); root.withdraw()
from main import _glyph, UI_ACCENT, UI_MUTED
from PIL import Image, ImageDraw

names = [n for n in sys.argv[1:]] or ["media","audio","text","transitions","effects","elements","filters","overlays","adjustment","ai","plus","plus_circle","search","sort","chevron_down","undo","redo","cut","trash","copy","paste","lock","unlock","eye","eye_off","speaker","speaker_off","mic","zoom_in","zoom_out","magnet","split","play","pause","skip_start","skip_end","step_prev","step_next","settings","camera","reset","diamond","flip_h","flip_v","rotate","frame","frame_fill","crop","fit_width","link","export","help","image","folder","cloud","menu","panel_right","panel_left","close","minimize","maximize","marker","keyframe","waveform","track_video","track_text"]
px, gap = 40, 6
cols = 10
rows = (len(names)+cols-1)//cols
sheet = Image.new("RGB", (cols*(px+gap)+gap, rows*(px+22)+gap), (18,18,22))
d = ImageDraw.Draw(sheet)
for i,n in enumerate(names):
    r,c = divmod(i, cols)
    x = gap + c*(px+gap); y = gap + r*(px+22)
    tile = Image.new("RGBA",(px,px),(21,21,26,255))
    _glyph(n, ImageDraw.Draw(tile), px/24.0, max(1,int(round(px/24.0*1.5))), (234,234,238) if i%2 else (0,229,255))
    sheet.paste(tile,(x,y),tile)
    d.text((x, y+px+2), n, fill=(150,150,160))
sheet.save("scratch/icon_sheet.png")
print("OK", len(names))
