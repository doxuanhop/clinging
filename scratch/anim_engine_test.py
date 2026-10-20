"""Unit gates for core/anim_engine.py (pure math, no GUI).

Usage: python scratch/anim_engine_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import anim_engine as A

fails = []
total = [0]


def ok(cond, msg):
    total[0] += 1
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ── progress ──────────────────────────────────────────────────
ok(close(A.progress(0.0, 5.0), 0.0), "progress(0,5) == 0")
ok(close(A.progress(2.5, 5.0), 0.5), "progress(2.5,5) == 0.5")
ok(close(A.progress(9.9, 5.0), 1.0), "progress clamps at 1")
ok(close(A.progress(1.0, 0.0), 0.0), "progress with no duration == 0")
ok(close(A.progress(-3.0, 5.0), 0.0), "negative local time clamps to 0")

# ── easing shapes ──────────────────────────────────────────────
ok(close(A.ease_out(0.0), 0.0) and close(A.ease_out(1.0), 1.0), "ease_out endpoints")
ok(A.ease_out(0.5) > 0.5, "ease_out leads linear in the first half")
ok(close(A.ease_smooth(0.0), 0.0) and close(A.ease_smooth(1.0), 1.0), "ease_smooth endpoints")
ok(close(A.ease_back(1.0), 1.0, 1e-9), "ease_back lands exactly on 1")
ok(max(A.ease_back(x) for x in [i / 100.0 for i in range(101)]) > 1.05,
   "ease_back overshoots (pop needs the bounce)")

# ── strength maps 0..1 UI slider onto the tuned 1..10 scale ────
ok(A.strength(0.0) == 1 and A.strength(1.0) == 10 and A.strength(0.5) in (5, 6),
   "strength(0..1) -> 1..10")

# ── motion: every key resolves, unknown keys are inert ─────────
for key in A.MOTION_KEYS:
    st = A.motion_state(key, 0.5, 1.0)
    ok(all(v == v for v in st), "motion %s returns finite numbers at p=0.5" % key)
ok(A.motion_state("shake", 0.5, 1.0) == A.IDENTITY,
   "unknown key is inert so legacy shake/float/glitch keep working")
ok(A.motion_state(None, 0.5, 1.0) == A.IDENTITY, "None key is inert")

# ── motion gates, checked at the endpoints that matter ─────────
ok(close(A.motion_state("zoom_in", 0.0, 1.0).scale, 1.0)
   and close(A.motion_state("zoom_in", 1.0, 1.0).scale, 1.2),
   "zoom_in: 1.0 -> 1.18 at full strength")
ok(close(A.motion_state("zoom_out", 0.0, 1.0).scale, 1.2)
   and close(A.motion_state("zoom_out", 1.0, 1.0).scale, 1.0),
   "zoom_out mirrors zoom_in")

ok(close(A.motion_state("slide_left", 0.0, 1.0).dx, 1.0)
   and close(A.motion_state("slide_left", 1.0, 1.0).dx, 0.0),
   "slide_left starts a full frame off the right edge and lands centred")
ok(close(A.motion_state("slide_right", 0.0, 1.0).dx, -1.0),
   "slide_right is the mirror, not a duplicate")
ok(close(A.motion_state("slide_up", 0.0, 1.0).dy, 1.0)
   and close(A.motion_state("slide_up", 0.0, 1.0).dx, 0.0),
   "slide_up moves on the vertical axis only")
ok(close(A.motion_state("slide_down", 0.0, 1.0).dy, -1.0),
   "slide_down enters from the top")
ok(A.motion_state("slide_left", 0.1, 1.0).dx > 0.0,
   "slide_left is still off-centre early in the clip (entry window is not the whole clip)")

ok(close(A.motion_state("fade_in", 0.0, 1.0).opacity, 0.0)
   and close(A.motion_state("fade_in", 1.0, 1.0).opacity, 1.0),
   "fade_in 0 -> 1")
ok(close(A.motion_state("fade_out", 0.0, 1.0).opacity, 1.0)
   and close(A.motion_state("fade_out", 1.0, 1.0).opacity, 0.0),
   "fade_out 1 -> 0")
ok(A.motion_state("fade_in", 0.05, 1.0).opacity > 0.0,
   "fade_in is already visible a frame after the cut (no black flash)")

spins = [A.motion_state("spin", i / 10.0, 1.0).rotation for i in range(11)]
ok(close(spins[0], 0.0) and close(spins[-1], 360.0), "spin sweeps 0 -> 360")
ok(all(b >= a for a, b in zip(spins, spins[1:])), "spin never rewinds")

pulses = [A.motion_state("pulse", i / 50.0, 1.0).scale for i in range(51)]
ok(min(pulses) >= 0.999 and max(pulses) <= 1.06, "pulse stays inside a breathing band")
ok(len({round(v, 4) for v in pulses}) > 8, "pulse actually oscillates")

bounces = [A.motion_state("bounce", i / 50.0, 1.0).dy for i in range(51)]
ok(max(bounces) == 0.0 and min(bounces) < -0.05, "bounce only moves upward from baseline")
ok(close(bounces[-1], 0.0), "bounce settles at the end")

# intensity must actually change the motion, not just its name
ok(A.motion_state("zoom_in", 1.0, 0.1).scale < A.motion_state("zoom_in", 1.0, 1.0).scale,
   "stronger intensity zooms deeper")
ok(A.motion_state("slide_left", 0.3, 1.0).dx < A.motion_state("slide_left", 0.3, 0.1).dx,
   "stronger intensity finishes the slide sooner")

# ── text gates ─────────────────────────────────────────────────
for key in A.TEXT_KEYS:
    st = A.text_state(key, 0.5, 1.0)
    ok(all(v == v for v in st), "text %s returns finite numbers at p=0.5" % key)
ok(A.text_state("nonsense", 0.5, 1.0) == A.TEXT_IDENTITY, "unknown text key is inert")

ok(close(A.text_state("typewriter", 0.0, 1.0).reveal, 0.0)
   and close(A.text_state("typewriter", 1.0, 1.0).reveal, 1.0),
   "typewriter reveals 0% -> 100%")
ok(0.0 < A.text_state("typewriter", 0.02, 1.0).reveal < 1.0,
   "typewriter shows at least one glyph immediately")

ok(close(A.text_state("scroll_left", 0.0, 0.0).dx, 1.0)
   and close(A.text_state("scroll_left", 1.0, 0.0).dx, -1.0),
   "scroll_left crosses the whole frame right -> left")
ok(close(A.text_state("scroll_right", 0.0, 0.0).dx, -1.0), "scroll_right mirrors it")
ok(close(A.text_state("scroll_left", 1.0 / 3.0, 1.0).dx, 1.0, 1e-6)
   and close(A.text_state("scroll_left", 1.0, 1.0).dx, 1.0, 1e-6),
   "a strong marquee loops three times instead of stopping")
ok(close(A.text_state("roll_up", 0.0, 1.0).dy, 1.0)
   and close(A.text_state("roll_up", 1.0, 1.0).dy, -1.0),
   "roll_up travels off-top, not to the middle")

ok(A.text_state("slide_in_left", 0.0, 1.0).dx < -0.99
   and close(A.text_state("slide_in_left", 1.0, 1.0).dx, 0.0),
   "slide_in_left enters from off the left edge")
ok(A.text_state("slide_in_up", 0.0, 1.0).dy > 0.99, "slide_in_up enters from below")

pop = [A.text_state("pop_in", i / 50.0, 1.0).scale for i in range(51)]
ok(pop[0] < 0.6 and close(pop[-1], 1.0, 1e-6), "pop_in grows from 0.55 to exactly 1.0")
ok(max(pop) > 1.0, "pop_in overshoots before settling")
ok(A.text_state("pop_in", 0.0, 1.0).opacity == 0.0, "pop_in starts invisible")

ok(A.text_state("blur_in", 0.0, 1.0).blur > 0.1
   and close(A.text_state("blur_in", 1.0, 1.0).blur, 0.0),
   "blur_in racks focus to sharp")
ok(A.text_state("fade_in", 0.0, 1.0).opacity == 0.0
   and close(A.text_state("fade_in", 1.0, 1.0).opacity, 1.0), "text fade_in 0 -> 1")
ok(close(A.text_state("fade_out", 1.0, 1.0).opacity, 0.0), "text fade_out ends invisible")

wave = A.text_state("wave", 0.0, 1.0)
ok(wave.wave_amp > 0.1 and close(wave.wave_phase, 0.0), "wave carries an amplitude")
ok(A.text_state("wave", 0.5, 1.0).wave_phase > A.text_state("wave", 0.25, 1.0).wave_phase,
   "wave phase advances with the clip")

# determinism: the exporter calls this per frame, twice over
ok(A.motion_state("spin", 0.37, 0.44) == A.motion_state("spin", 0.37, 0.44)
   and A.text_state("pop_in", 0.37, 0.44) == A.text_state("pop_in", 0.37, 0.44),
   "identical inputs give identical outputs")

print("\n%d checks, %d failed" % (total[0], len(fails)))
print("summary:", "ALL PASS" if not fails else "FAILURES\n  " + "\n  ".join(fails))
sys.exit(1 if fails else 0)
