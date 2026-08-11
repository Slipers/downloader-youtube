"""One-off script: generates assets/icon.ico (brand gradient + download glyph)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)

S = 1024
TOP = (255, 51, 102)      # --accent
BOTTOM = (124, 92, 255)   # --accent-2

grad = Image.new("RGB", (S, S))
draw = ImageDraw.Draw(grad)
for y in range(S):
    t = y / (S - 1)
    r = round(TOP[0] + (BOTTOM[0] - TOP[0]) * t)
    g = round(TOP[1] + (BOTTOM[1] - TOP[1]) * t)
    b = round(TOP[2] + (BOTTOM[2] - TOP[2]) * t)
    draw.line([(0, y), (S, y)], fill=(r, g, b))

mask = Image.new("L", (S, S), 0)
mdraw = ImageDraw.Draw(mask)
margin = int(S * 0.04)
radius = int(S * 0.24)
mdraw.rounded_rectangle([margin, margin, S - margin, S - margin], radius=radius, fill=255)

icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(grad, (0, 0), mask)

gdraw = ImageDraw.Draw(icon)
cx = S / 2
white = (255, 255, 255, 255)

# Download glyph: vertical shaft + arrowhead + tray.
shaft_w = S * 0.09
shaft_top = S * 0.24
shaft_bottom = S * 0.52
gdraw.rounded_rectangle(
    [cx - shaft_w / 2, shaft_top, cx + shaft_w / 2, shaft_bottom],
    radius=shaft_w / 2, fill=white,
)

head_w = S * 0.30
head_y = S * 0.50
head_tip = S * 0.66
gdraw.polygon(
    [(cx - head_w / 2, head_y), (cx + head_w / 2, head_y), (cx, head_tip)],
    fill=white,
)

tray_y = S * 0.76
tray_half = S * 0.20
tray_h = S * 0.07
gdraw.rounded_rectangle(
    [cx - tray_half, tray_y, cx + tray_half, tray_y + tray_h],
    radius=tray_h / 2, fill=white,
)

icon = icon.resize((256, 256), Image.LANCZOS)
icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
icon.save(OUT / "icon.png")
print(f"Saved {OUT / 'icon.ico'}")
