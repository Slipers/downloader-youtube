"""One-off script: derives the extension icons from assets/icon.png."""
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
OUT = Path(__file__).resolve().parent / "icons"
OUT.mkdir(exist_ok=True)

source = Image.open(SRC).convert("RGBA")
for size in (16, 32, 48, 128):
    source.resize((size, size), Image.LANCZOS).save(OUT / f"icon{size}.png")

print(f"Saved icons to {OUT}")
