"""Frame-space animation used by both the player and the exporter.

Preview and export call apply_motion() / text_layer() with the clip's local
progress, so what the user watches is what gets rendered. Pure PIL: no Tk and no
moviepy, which lets the exporter reuse it through a raw ffmpeg pipe.
"""
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MOTION_EFFECTS = (
    ("none", "None", "Keep the original clip"),
    ("zoom_in", "Ken Burns In", "Slowly push into the clip"),
    ("zoom_out", "Ken Burns Out", "Slowly pull away"),
    ("slide_left", "Slide Left", "Clip enters from the right"),
    ("slide_right", "Slide Right", "Clip enters from the left"),
    ("slide_up", "Slide Up", "Clip enters from below"),
    ("slide_down", "Slide Down", "Clip enters from above"),
    ("fade_in", "Fade In", "Fade in from black"),
    ("fade_out", "Fade Out", "Fade out to black"),
    ("pulse", "Pulse", "Rhythmic scale breathing"),
    ("spin", "Spin", "Rotate 360 degrees"),
    ("bounce", "Bounce", "Bounce up and down"),
)

TEXT_EFFECTS = (
    ("none", "Static", "Hold the text in place"),
    ("fade_in", "Fade In", "Text fades up from invisible"),
    ("fade_out", "Fade Out", "Text fades away at the end"),
    ("pop_in", "Pop In", "Scale up with a slight overshoot"),
    ("slide_in_left", "Slide From Left", "Text enters from the left edge"),
    ("slide_in_right", "Slide From Right", "Text enters from the right edge"),
    ("slide_in_up", "Slide From Below", "Text enters from the bottom edge"),
    ("slide_in_down", "Slide From Above", "Text enters from the top edge"),
    ("scroll_left", "Scroll Left", "Marquee running right to left"),
    ("scroll_right", "Scroll Right", "Marquee running left to right"),
    ("roll_up", "Credits Roll", "Text rolls upward, end credits style"),
    ("typewriter", "Typewriter", "Reveal one character at a time"),
    ("wave", "Wave", "Characters bob on a sine wave"),
    ("blur_in", "Focus In", "Rack focus from blurred to sharp"),
)

MOTION_KEYS = tuple(key for key, _, _ in MOTION_EFFECTS)
TEXT_KEYS = tuple(key for key, _, _ in TEXT_EFFECTS)

DESIGN_H = 360.0
_FONT_CACHE = {}


def label(effects, key):
    for k, name, _ in effects:
        if k == key:
            return name
    return key


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def ease_out(p, k=3.0):
    return 1.0 - (1.0 - p) ** k


def ease_smooth(p):
    return p * p * (3.0 - 2.0 * p)


def ease_back(p, overshoot=1.35):
    c = p - 1.0
    return 1.0 + (overshoot + 1.0) * c ** 3 + overshoot * c ** 2


def get_font(name, px):
    key = (name, int(px))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    tried = [name, "arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"]
    for candidate in tried:
        if not candidate:
            continue
        try:
            font = ImageFont.truetype(candidate, max(6, int(px)))
        except Exception:
            continue
        _FONT_CACHE[key] = font
        return font
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _entry(intensity):
    """How much of the clip the intro animation is allowed to use."""
    return clamp(0.45 - 0.03 * intensity, 0.12, 0.45)


def _lead_in(p, intensity):
    return clamp(p / _entry(intensity))


def _lead_out(p, intensity):
    frac = _entry(intensity)
    return clamp((p - (1.0 - frac)) / frac)


# --- clip (motion) effects ----------------------------------------------------

def _zoom(img, s):
    w, h = img.size
    if abs(s - 1.0) < 1e-3:
        return img
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    big = img.resize((nw, nh), Image.Resampling.BILINEAR)
    x, y = (nw - w) // 2, (nh - h) // 2
    return big.crop((x, y, x + w, y + h))


def _offset(img, dx, dy):
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return img
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (int(round(dx)), int(round(dy))))
    return out


def _to_black(img, k):
    if k <= 0:
        return img
    return Image.blend(img, Image.new("RGBA", img.size, (0, 0, 0, 255)), clamp(k))


def _motion_zoom_in(img, p, i, w, h):
    return _zoom(img, 1.0 + 0.02 * i * ease_smooth(p))


def _motion_zoom_out(img, p, i, w, h):
    return _zoom(img, 1.0 + 0.02 * i * (1.0 - ease_smooth(p)))


def _motion_slide(img, p, i, w, h, dx_sign, dy_sign):
    travel = 1.0 - ease_out(_lead_in(p, i))
    return _offset(img, dx_sign * travel * w, dy_sign * travel * h)


def _motion_fade_in(img, p, i, w, h):
    return _to_black(img, 1.0 - ease_out(_lead_in(p, i)))


def _motion_fade_out(img, p, i, w, h):
    return _to_black(img, ease_smooth(_lead_out(p, i)))


def _motion_pulse(img, p, i, w, h):
    cycles = 1 + i // 2
    s = 1.0 + 0.006 * i * (0.5 - 0.5 * math.cos(2 * math.pi * cycles * p))
    return _zoom(img, s)


def _motion_spin(img, p, i, w, h):
    shaped = p + (ease_smooth(p) - p) * ((i - 1) / 9.0)
    return img.rotate(360.0 * shaped, resample=Image.Resampling.BICUBIC,
                      expand=False, fillcolor=(0, 0, 0, 0))


def _motion_bounce(img, p, i, w, h):
    cycles = 1 + i // 2
    amp = h * 0.02 * i
    dy = -amp * abs(math.sin(math.pi * cycles * p)) * (1.0 - 0.6 * p)
    return _offset(img, 0, dy)


def _motion_none(img, p, i, w, h):
    return img


_MOTION = {
    "none": _motion_none,
    "zoom_in": _motion_zoom_in,
    "zoom_out": _motion_zoom_out,
    "slide_left": lambda im, p, i, w, h: _motion_slide(im, p, i, w, h, 1, 0),
    "slide_right": lambda im, p, i, w, h: _motion_slide(im, p, i, w, h, -1, 0),
    "slide_up": lambda im, p, i, w, h: _motion_slide(im, p, i, w, h, 0, 1),
    "slide_down": lambda im, p, i, w, h: _motion_slide(im, p, i, w, h, 0, -1),
    "fade_in": _motion_fade_in,
    "fade_out": _motion_fade_out,
    "pulse": _motion_pulse,
    "spin": _motion_spin,
    "bounce": _motion_bounce,
}


def apply_motion(img, effect, p, intensity=5):
    """Transform one canvas-sized frame; `p` is progress through the clip (0..1)."""
    handler = _MOTION.get(effect or "none")
    if handler is None or handler is _motion_none:
        return img
    mode = img.mode
    src = img if mode == "RGBA" else img.convert("RGBA")
    w, h = src.size
    out = handler(src, clamp(p), int(clamp(intensity, 1, 10)), w, h)
    return out if mode == "RGBA" else out.convert(mode)


def motion_progress(local_time, duration):
    if not duration or duration <= 0:
        return 0.0
    return clamp(local_time / duration)


# --- text effects -------------------------------------------------------------

def _tint_alpha(bmp, alpha):
    if alpha >= 0.999:
        return bmp
    out = bmp.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * clamp(alpha))))
    return out


def _text_bitmap(text, font, color, bg, pad):
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
    box = probe.multiline_textbbox((0, 0), text, font=font, spacing=6, align="center")
    w, h = int(box[2] - box[0]) + pad * 2, int(box[3] - box[1]) + pad * 2
    if w <= pad * 2 or h <= pad * 2:
        return None
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if bg and bg != "transparent":
        draw.rectangle((0, 0, w - 1, h - 1), fill=bg)
    draw.multiline_text((pad - box[0], pad - box[1]), text, font=font, fill=color,
                        spacing=6, align="center")
    return img


def _wave_layer(size, text, font, color, cx, cy, amp, phase):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    widths = [font.getlength(ch) for ch in text]
    total = sum(widths)
    x = cx - total / 2.0
    for index, ch in enumerate(text):
        if ch != " ":
            y = cy + amp * math.sin(phase + index * 0.55)
            draw.text((x, y), ch, font=font, fill=color, anchor="lm")
        x += widths[index]
    return layer


def text_layer(size, text, effect="none", p=0.0, intensity=5, font_size=28,
               color="#FFFFFF", bg="transparent", pos=(0.5, 0.5), font="Arial"):
    """Render an animated text layer the size of `size` (RGBA, transparent bg)."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    text = (text or "").strip()
    if not text:
        return layer
    w, h = size
    i = int(clamp(intensity, 1, 10))
    p = clamp(p)
    px = max(6, int(round(font_size * (h / DESIGN_H))))
    fnt = get_font(font, px)
    cx, cy = pos[0] * w, pos[1] * h
    pad = max(4, int(px * 0.35))

    if effect == "wave":
        cycles = 1 + i // 2
        return _wave_layer(size, text, fnt, color, cx, cy,
                           px * (0.10 + 0.03 * i), 2 * math.pi * cycles * p)

    bmp = _text_bitmap(text, fnt, color, bg, pad)
    if bmp is None:
        return layer

    dx = cx - bmp.width / 2.0
    dy = cy - bmp.height / 2.0

    if effect == "fade_in":
        bmp = _tint_alpha(bmp, ease_out(_lead_in(p, i)))
    elif effect == "fade_out":
        bmp = _tint_alpha(bmp, 1.0 - ease_smooth(_lead_out(p, i)))
    elif effect == "pop_in":
        e = ease_back(_lead_in(p, i))
        scale = 0.55 + 0.45 * e
        bmp = bmp.resize((max(1, int(bmp.width * scale)), max(1, int(bmp.height * scale))),
                         Image.Resampling.BILINEAR)
        dx, dy = cx - bmp.width / 2.0, cy - bmp.height / 2.0
        bmp = _tint_alpha(bmp, ease_out(clamp(_lead_in(p, i) * 2.5)))
    elif effect == "blur_in":
        radius = max(0.0, (1.0 - ease_out(_lead_in(p, i))) * px * 0.18)
        if radius > 0.4:
            bmp = bmp.filter(ImageFilter.GaussianBlur(radius))
    elif effect in ("slide_in_left", "slide_in_right", "slide_in_up", "slide_in_down"):
        travel = 1.0 - ease_out(_lead_in(p, i))
        if effect == "slide_in_left":
            dx -= (cx + bmp.width / 2.0) * travel
        elif effect == "slide_in_right":
            dx += (w - cx + bmp.width / 2.0) * travel
        elif effect == "slide_in_up":
            dy += (h - cy + bmp.height / 2.0) * travel
        else:
            dy -= (cy + bmp.height / 2.0) * travel
    elif effect in ("scroll_left", "scroll_right", "roll_up"):
        loops = 1 + (i - 1) // 4 if effect != "roll_up" else 1
        span = clamp(p * loops) if loops == 1 else (p * loops) % 1.0
        if effect == "scroll_left":
            dx = w - (w + bmp.width) * span
        elif effect == "scroll_right":
            dx = -bmp.width + (w + bmp.width) * span
        else:
            dy = h - (h + bmp.height) * clamp(p)
    elif effect == "typewriter":
        shown = int(round(len(text) * _lead_in(p, i)))
        typed = text[:max(1, shown)]
        typed_bmp = _text_bitmap(typed, fnt, color, bg, pad)
        if typed_bmp is not None:
            # Keep the left edge fixed so the line does not jitter while typing.
            dx = cx - bmp.width / 2.0
            bmp = typed_bmp

    layer.paste(bmp, (int(round(dx)), int(round(dy))), bmp)
    return layer
