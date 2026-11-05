"""Draw the EM Port tool icon: two metal stubs (KLayout-style hatch) bridged by a magenta port with a source symbol.

Run in a Python with Pillow: python tools/make_icon.py
Writes python/klayout_em_export/icons/em_port.png (64 x 64). Drawn at 8x and scaled down for smooth edges.
"""
import math
import os

from PIL import Image, ImageDraw

SIZE, SCALE = 64, 8
METAL, METAL_EDGE = (255, 128, 0, 255), (176, 84, 0, 255)       # TopMetal2 orange
PORT, PORT_EDGE = (230, 0, 230, 255), (140, 0, 140, 255)         # magenta, as the tool's marker
WHITE = (255, 255, 255, 255)

N = SIZE * SCALE
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
u = N / 64.0                                     # drawing unit: 1/64 of the icon


def box(x0, y0, x1, y1):
    return [round(x0 * u), round(y0 * u), round(x1 * u), round(y1 * u)]


def hatched(x0, y0, x1, y1, fill, edge, step=10):
    """Metal stub: light fill, diagonal hatch lines and a solid edge, like KLayout's layer display."""
    d.rectangle(box(x0, y0, x1, y1), fill=fill[:3] + (90,))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rectangle(box(x0, y0, x1, y1), fill=255)
    lines = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for k in range(-64, 128, step):
        ld.line([(k * u, 64 * u), ((k + 64) * u, 0)], fill=fill, width=round(2.6 * u))
    img.paste(lines, (0, 0), Image.composite(lines, Image.new("RGBA", (N, N)), mask).split()[3])
    d.rectangle(box(x0, y0, x1, y1), outline=edge, width=round(3 * u))


# metal stubs left and right, gap in the middle
hatched(1, 15, 22, 49, METAL, METAL_EDGE)
hatched(42, 15, 63, 49, METAL, METAL_EDGE)
# port bridging the gap, a bit taller than the metal so it reads as its own shape
d.rounded_rectangle(box(18, 4, 46, 60), radius=round(4 * u), fill=PORT, outline=PORT_EDGE, width=round(2.5 * u))
# source symbol: white circle with a sine wave
cx, cy, r = 32 * u, 32 * u, 11.5 * u
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE, outline=PORT_EDGE, width=round(2 * u))
wave = [(cx + (t - 0.5) * 1.35 * r, cy - 0.5 * r * math.sin(2 * math.pi * t)) for t in [i / 60 for i in range(61)]]
d.line(wave, fill=PORT_EDGE, width=round(3.4 * u), joint="curve")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python", "klayout_em_export", "icons")
os.makedirs(out, exist_ok=True)
img.resize((SIZE, SIZE), Image.LANCZOS).save(os.path.join(out, "em_port.png"))
print("wrote", os.path.normpath(os.path.join(out, "em_port.png")))
