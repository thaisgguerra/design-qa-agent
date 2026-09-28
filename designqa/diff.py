"""Deterministic visual diff: aligns the two images and finds regions that changed.

This step is cheap, fast and never hallucinates. It tells the LLM *where* to look,
and it is used later to check that every LLM finding has pixel evidence behind it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage


@dataclass
class Region:
    id: int
    x: int
    y: int
    w: int
    h: int
    area: int
    intensity: float  # mean channel difference inside the region (0-255)

    @property
    def box(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    def to_dict(self) -> dict:
        return asdict(self)


def load_pair(design_path, impl_path) -> tuple[Image.Image, Image.Image, float]:
    """Load both images, scale the implementation to the design width, pad to equal height.

    Returns (design, impl, impl_scale). impl_scale converts implementation (DOM)
    coordinates into design coordinates.
    """
    design = Image.open(design_path).convert("RGB")
    impl = Image.open(impl_path).convert("RGB")
    scale = design.width / impl.width
    if abs(scale - 1) > 1e-3:
        impl = impl.resize((design.width, round(impl.height * scale)), Image.LANCZOS)
    h = max(design.height, impl.height)

    def pad(img):
        if img.height == h:
            return img
        canvas = Image.new("RGB", (img.width, h), (255, 255, 255))
        canvas.paste(img, (0, 0))
        return canvas

    return pad(design), pad(impl), scale


def compute_diff(design: Image.Image, impl: Image.Image, threshold: int = 24,
                 min_area: int = 40, dilate: int = 6, max_regions: int = 40) -> tuple[np.ndarray, list[Region]]:
    # A light blur removes anti-aliasing and sub-pixel font rendering noise.
    a = np.asarray(design.filter(ImageFilter.GaussianBlur(1)), dtype=np.int16)
    b = np.asarray(impl.filter(ImageFilter.GaussianBlur(1)), dtype=np.int16)
    delta = np.abs(a - b).max(axis=2)
    mask = delta > threshold
    grown = ndimage.binary_dilation(mask, iterations=dilate) if dilate else mask
    labels, n = ndimage.label(grown)
    regions: list[Region] = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        ys, xs = sl
        raw = mask[ys, xs] & (labels[ys, xs] == i)
        area = int(raw.sum())
        if area < min_area:
            continue
        regions.append(Region(0, xs.start, ys.start, xs.stop - xs.start, ys.stop - ys.start, area,
                              float(delta[ys, xs][raw].mean())))
    regions.sort(key=lambda r: r.area, reverse=True)
    regions = regions[:max_regions]
    regions.sort(key=lambda r: (r.y, r.x))
    for idx, r in enumerate(regions, start=1):
        r.id = idx
    return mask, regions


def diff_ratio(mask: np.ndarray) -> float:
    return float(mask.mean())


def overlay(impl: Image.Image, regions: list[Region]) -> Image.Image:
    """Implementation screenshot with numbered red boxes on every changed region."""
    img = impl.copy()
    d = ImageDraw.Draw(img)
    for r in regions:
        d.rectangle([r.x, r.y, r.x + r.w, r.y + r.h], outline=(230, 30, 60), width=3)
        label = str(r.id)
        tx, ty = r.x, max(0, r.y - 16)
        d.rectangle([tx, ty, tx + 8 * len(label) + 8, ty + 16], fill=(230, 30, 60))
        d.text((tx + 4, ty + 2), label, fill=(255, 255, 255))
    return img


def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def overlaps(a: list[float], b: list[float], pad: int = 0) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad < bx or bx + bw + pad < ax or ay + ah + pad < by or by + bh + pad < ay)
