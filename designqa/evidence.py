"""Side by side evidence images attached to each ticket."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RED = (230, 30, 60)


def make_evidence(design: Image.Image, impl: Image.Image, bbox, out_path: Path,
                  pad: int = 48, max_w: int = 700) -> Path:
    x, y, w, h = [int(v) for v in bbox]
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(design.width, x + w + pad), min(design.height, y + h + pad)
    if right - left < 40:
        right = min(design.width, left + 40)
    if bottom - top < 40:
        bottom = min(design.height, top + 40)
    crops = []
    for img in (design, impl):
        c = img.crop((left, top, right, bottom)).copy()
        ImageDraw.Draw(c).rectangle([x - left, y - top, x - left + w, y - top + h], outline=RED, width=2)
        crops.append(c)
    s = min(1.0, max_w / crops[0].width) if crops[0].width else 1.0
    if s < 1:
        crops = [c.resize((round(c.width * s), round(c.height * s)), Image.LANCZOS) for c in crops]
    cw, ch, gap, header = crops[0].width, crops[0].height, 16, 28
    canvas = Image.new("RGB", (cw * 2 + gap * 3, ch + header + gap), (245, 246, 248))
    d = ImageDraw.Draw(canvas)
    for i, (label, c) in enumerate((("DESIGN (Figma)", crops[0]), ("IMPLEMENTATION", crops[1]))):
        ox = gap + i * (cw + gap)
        d.text((ox, 8), label, fill=(40, 40, 50))
        canvas.paste(c, (ox, header))
    canvas.save(out_path)
    return out_path
