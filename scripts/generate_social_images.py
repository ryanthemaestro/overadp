#!/usr/bin/env python3
"""Generate Twitter/X avatar + banner PNGs for @overadp / @nar_ffmodel."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

# Brand colors (from site/index.html)
BG = (5, 8, 10)
BG3 = (15, 21, 25)
GREEN = (0, 255, 106)
GREEN_DIM = (0, 100, 40)
RED = (255, 51, 68)
FG = (238, 241, 245)
FG2 = (184, 196, 208)
FG3 = (152, 168, 184)
GRID = (0, 255, 106, 18)  # alpha ~7%

# Fonts — using what's actually on this linux box
SANS_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
SANS_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"


def draw_grid(img: Image.Image, spacing: int = 60, alpha: int = 18):
    """Draw the subtle green grid background matching the site."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    w, h = img.size
    color = (0, 255, 106, alpha)
    for x in range(0, w, spacing):
        d.line([(x, 0), (x, h)], fill=color, width=1)
    for y in range(0, h, spacing):
        d.line([(0, y), (w, y)], fill=color, width=1)
    img.paste(overlay, (0, 0), overlay)


def add_radial_glow(img: Image.Image, center, radius, color=(0, 255, 106), intensity=0.08):
    """Add a soft glow at a specific point."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = center
    steps = 30
    for i in range(steps, 0, -1):
        r = radius * i / steps
        a = int(255 * intensity * (1 - i / steps))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, a))
    img.paste(overlay, (0, 0), overlay)


def make_avatar():
    """400x400 avatar: Δ logo mark on dark grid, soft green glow."""
    size = 400
    img = Image.new("RGB", (size, size), BG)

    # Grid background
    draw_grid(img, spacing=40, alpha=14)

    # Radial glow behind the logo
    add_radial_glow(img, (size // 2, size // 2), 200, GREEN, intensity=0.12)

    # Big Δ in the center
    d = ImageDraw.Draw(img, "RGBA")
    delta_font = ImageFont.truetype(SANS_BOLD, 280)
    delta = "Δ"
    bbox = d.textbbox((0, 0), delta, font=delta_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] - 8  # slight vertical nudge
    # Glow layer first (green blurred)
    glow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    gd.text((x, y), delta, font=delta_font, fill=(*GREEN, 140))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=18))
    img.paste(glow_img, (0, 0), glow_img)
    # Main text
    d.text((x, y), delta, font=delta_font, fill=GREEN)

    # Small "OVERADP" wordmark at bottom
    wm_font = ImageFont.truetype(MONO, 22)
    wm = "OVERADP"
    wb = d.textbbox((0, 0), wm, font=wm_font)
    ww = wb[2] - wb[0]
    d.text(((size - ww) // 2, size - 46), wm, font=wm_font, fill=FG2)

    # Subtle 1px border
    d.rectangle([0, 0, size - 1, size - 1], outline=(0, 255, 106, 40), width=1)

    out_path = OUT / "twitter_avatar.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"  Avatar:  {out_path}  ({out_path.stat().st_size // 1024} KB)")


def make_banner():
    """1500x500 banner: Model R² 0.59 vs ADP R² 0.09 kill-stat."""
    w, h = 1500, 500
    img = Image.new("RGB", (w, h), BG)
    draw_grid(img, spacing=60, alpha=16)

    # Subtle gradient from top
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        a = int(50 * (1 - y / h))  # fade top to nothing
        gd.line([(0, y), (w, y)], fill=(0, 255, 106, a // 8))
    img.paste(grad, (0, 0), grad)

    # Green radial glow top-center
    add_radial_glow(img, (w // 2, 0), 700, GREEN, intensity=0.10)

    d = ImageDraw.Draw(img, "RGBA")

    # Top "section tag" style
    tag_font = ImageFont.truetype(MONO, 18)
    tag = "WALK-FORWARD VALIDATED  ·  2022-2025"
    tb = d.textbbox((0, 0), tag, font=tag_font)
    d.text(((w - (tb[2] - tb[0])) // 2, 60), tag, font=tag_font, fill=GREEN)

    # Main headline
    head_font = ImageFont.truetype(SANS_BOLD, 68)
    head = "7× MORE VARIANCE EXPLAINED THAN ADP"
    hb = d.textbbox((0, 0), head, font=head_font)
    d.text(((w - (hb[2] - hb[0])) // 2, 100), head, font=head_font, fill=FG)

    # Two stat columns
    stat_big = ImageFont.truetype(SANS_BOLD, 120)
    stat_label = ImageFont.truetype(MONO, 18)
    stat_sub = ImageFont.truetype(SANS_REG, 22)

    col_y = 210
    # Left column: OverADP Model
    left_x = w // 2 - 320

    # Badge above number
    badge = "OVERADP MODEL"
    bb = d.textbbox((0, 0), badge, font=stat_label)
    d.text((left_x - (bb[2] - bb[0]) // 2, col_y), badge, font=stat_label, fill=FG3)
    # Number
    num = "0.59"
    nb = d.textbbox((0, 0), num, font=stat_big)
    # green glow
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(g)
    gdr.text((left_x - (nb[2] - nb[0]) // 2, col_y + 30), num, font=stat_big, fill=(*GREEN, 120))
    g = g.filter(ImageFilter.GaussianBlur(12))
    img.paste(g, (0, 0), g)
    d.text((left_x - (nb[2] - nb[0]) // 2, col_y + 30), num, font=stat_big, fill=GREEN)
    # Sublabel
    sub = "R² variance explained"
    sbx = d.textbbox((0, 0), sub, font=stat_sub)
    d.text((left_x - (sbx[2] - sbx[0]) // 2, col_y + 175), sub, font=stat_sub, fill=FG2)

    # VS divider
    vs_font = ImageFont.truetype(SANS_BOLD, 60)
    vs = "VS"
    vb = d.textbbox((0, 0), vs, font=vs_font)
    d.text(((w - (vb[2] - vb[0])) // 2, col_y + 60), vs, font=vs_font, fill=FG3)
    # Divider lines
    d.line([(w // 2 - 130, col_y + 100), (w // 2 - 75, col_y + 100)], fill=(98, 108, 120, 180), width=2)
    d.line([(w // 2 + 75, col_y + 100), (w // 2 + 130, col_y + 100)], fill=(98, 108, 120, 180), width=2)

    # Right column: ADP baseline
    right_x = w // 2 + 320

    badge2 = "ADP (CONSENSUS)"
    bb2 = d.textbbox((0, 0), badge2, font=stat_label)
    d.text((right_x - (bb2[2] - bb2[0]) // 2, col_y), badge2, font=stat_label, fill=FG3)

    num2 = "0.09"
    nb2 = d.textbbox((0, 0), num2, font=stat_big)
    d.text((right_x - (nb2[2] - nb2[0]) // 2, col_y + 30), num2, font=stat_big, fill=RED)

    sub2 = "R² variance explained"
    sbx2 = d.textbbox((0, 0), sub2, font=stat_sub)
    d.text((right_x - (sbx2[2] - sbx2[0]) // 2, col_y + 175), sub2, font=stat_sub, fill=FG2)

    # Bottom tagline
    tag2_font = ImageFont.truetype(MONO, 20)
    tag2 = "MAE EDGE:   QB −34%   ·   RB −38%   ·   WR −33%   ·   TE −39%"
    tb2 = d.textbbox((0, 0), tag2, font=tag2_font)
    d.text(((w - (tb2[2] - tb2[0])) // 2, h - 80), tag2, font=tag2_font, fill=GREEN)

    url_font = ImageFont.truetype(SANS_BOLD, 26)
    url = "overadp.com"
    ub = d.textbbox((0, 0), url, font=url_font)
    d.text(((w - (ub[2] - ub[0])) // 2, h - 40), url, font=url_font, fill=FG)

    # Border glow at top
    d.line([(0, 0), (w, 0)], fill=(*GREEN, 80), width=2)

    out_path = OUT / "twitter_banner.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"  Banner:  {out_path}  ({out_path.stat().st_size // 1024} KB)")


def make_avatar_variant_face():
    """Alt avatar: the bare Δ without the wordmark (cleaner at thumbnail sizes)."""
    size = 400
    img = Image.new("RGB", (size, size), BG)
    draw_grid(img, spacing=40, alpha=14)
    add_radial_glow(img, (size // 2, size // 2), 220, GREEN, intensity=0.15)

    d = ImageDraw.Draw(img, "RGBA")
    delta_font = ImageFont.truetype(SANS_BOLD, 320)
    delta = "Δ"
    bbox = d.textbbox((0, 0), delta, font=delta_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] - 10

    glow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    gd.text((x, y), delta, font=delta_font, fill=(*GREEN, 180))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=22))
    img.paste(glow_img, (0, 0), glow_img)
    d.text((x, y), delta, font=delta_font, fill=GREEN)

    d.rectangle([0, 0, size - 1, size - 1], outline=(0, 255, 106, 60), width=1)
    out_path = OUT / "twitter_avatar_bare.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"  Avatar (bare):  {out_path}  ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    print("Generating social media images...")
    make_avatar()
    make_avatar_variant_face()
    make_banner()
    print("\n✓ Done. Upload these to Twitter/X profile settings.")
    print(f"  Directory: {OUT}")
