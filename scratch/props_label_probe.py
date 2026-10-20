"""Measure why the Motion / Text-animation help labels clip.

Usage: python scratch/props_label_probe.py
"""
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ctypes
ctypes.windll.user32.SetProcessDPIAware()

import customtkinter as ctk
import main as appmod

SRC = os.path.join(ROOT, "scratch", "motion_still.mp4")


def walk(w, depth=0):
    for c in w.winfo_children():
        yield c, depth
        yield from walk(c, depth + 1)


def run(app):
    try:
        video = app.timeline_clips[0]
        app.selected_clips = [video]
        app.current_video_tab = "Motion"
        app.render_video_tab_content()
        app.root.update()
        app.root.update_idletasks()

        print("props_content px:", app.props_content.winfo_width(),
              "req:", app.props_content.winfo_reqwidth(),
              "PROPS_W:", appmod.ClingingApp.PROPS_W, "PAD:", appmod.ClingingApp.PROPS_PAD)

        for w, d in walk(app.props_content):
            if not isinstance(w, ctk.CTkLabel):
                continue
            txt = str(w.cget("text"))
            if "player and the" not in txt:
                continue
            inner = getattr(w, "_label", None)
            print("---", repr(txt[:44]))
            print("   outer winfo:", w.winfo_width(), "req:", w.winfo_reqwidth(),
                  "cget wrap:", w.cget("wraplength"))
            if inner is not None:
                print("   inner wrap:", inner.cget("wraplength"),
                      "winfo:", inner.winfo_width(), "req:", inner.winfo_reqwidth())
    except Exception as exc:
        print("PROBE ERROR:", type(exc).__name__, exc)
    finally:
        app.root.destroy()


app = appmod.ClingingApp({"id": "propsprobe", "name": "propsprobe", "clips": [
    {"file_path": SRC, "start_time": 0, "duration": 2, "clip_type": "video", "track_idx": 0},
]})
app.root.after(900, lambda: run(app))
app.root.mainloop()
