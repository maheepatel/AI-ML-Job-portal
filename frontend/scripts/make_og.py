"""Render public/og.png (1200x630) for link previews. Re-run after changing the tagline:
    python frontend/scripts/make_og.py   (needs Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "og.png"
MINT_BG, MINT, INK = (236, 255, 224), (0, 240, 160), (0, 0, 0)


def font(names: list[str], size: int):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


bold = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"]
regular = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]

img = Image.new("RGB", (1200, 630), MINT_BG)
d = ImageDraw.Draw(img)

# Logo mark: black rounded square with the mint "gradient" line.
d.rounded_rectangle((80, 72, 144, 136), radius=18, fill=INK)
d.line([(94, 122), (110, 100), (122, 112), (132, 86)], fill=MINT, width=7, joint="curve")
d.text((164, 78), "gradient", font=font(bold, 46), fill=INK)

headline = font(bold, 76)
d.text((80, 200), "Every AI/ML opening", font=headline, fill=INK)
y2 = 290
d.rectangle((80, y2 + 52, 80 + d.textlength("on the internet.", font=headline), y2 + 84), fill=MINT)
d.text((80, y2), "on the internet.", font=headline, fill=INK)

d.text((80, 410), "Freshers to 4 years · refreshed every 4 hours · scam-checked",
       font=font(regular, 32), fill=(40, 40, 40))

# Pill
d.rounded_rectangle((80, 492, 470, 562), radius=35, fill=INK)
d.text((112, 507), "Find AI/ML jobs →", font=font(bold, 32), fill=(255, 255, 255))

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, optimize=True)
print(OUT, OUT.stat().st_size, "bytes")
