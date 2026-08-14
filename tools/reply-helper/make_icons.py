#!/usr/bin/env python3
"""Generate simple Δ icons for the extension."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(__file__).resolve().parent / "icons"
OUT.mkdir(exist_ok=True)

BG = (5, 8, 10)
GREEN = (0, 255, 106)
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

for size in (16, 48, 128):
    img = Image.new("RGBA", (size, size), BG + (255,))
    d = ImageDraw.Draw(img)
    # border
    d.rectangle([0, 0, size - 1, size - 1], outline=(0, 255, 106, 80), width=max(1, size // 32))
    # Δ
    fs = int(size * 0.78)
    f = ImageFont.truetype(FONT, fs)
    ch = "Δ"
    b = d.textbbox((0, 0), ch, font=f)
    tw = b[2] - b[0]
    th = b[3] - b[1]
    x = (size - tw) // 2 - b[0]
    y = (size - th) // 2 - b[1] - max(1, size // 32)
    d.text((x, y), ch, font=f, fill=GREEN)
    img.save(OUT / f"icon{size}.png")
    print(f"  icon{size}.png")
print("Done.")
