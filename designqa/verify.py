"""Guardrails between the LLM and the ticket tracker.

Nothing the model says becomes a ticket unless it survives these checks:
  1. Evidence check   - the finding must overlap a region where pixels actually changed
  2. Color check      - claimed color differences must be visible in the sampled pixels
  3. De-duplication   - overlapping findings with the same category are merged (tiles overlap)
  4. Confidence gate  - low confidence findings go to a human review queue, never straight to tickets
"""
from __future__ import annotations

import re

import numpy as np
from PIL import Image

from . import config
from .analyze import Finding
from .diff import Region, iou, overlaps

HEX = re.compile(r"#([0-9A-Fa-f]{6})")


def _median_color(img: Image.Image, box) -> np.ndarray:
    x, y, w, h = [max(0, int(v)) for v in box]
    crop = np.asarray(img.crop((x, y, x + max(1, w), y + max(1, h))), dtype=np.int16).reshape(-1, 3)
    return np.median(crop, axis=0) if len(crop) else np.zeros(3)


def _changed_share(design, impl, box, threshold: int = 24) -> float:
    x, y, w, h = [max(0, int(v)) for v in box]
    crop = (x, y, x + max(1, w), y + max(1, h))
    a = np.asarray(design.crop(crop), dtype=np.int16)
    b = np.asarray(impl.crop(crop), dtype=np.int16)
    return float((np.abs(a - b).max(axis=-1) >= threshold).mean()) if a.size else 0.0


def _check_color(f: Finding, design, impl) -> str | None:
    exp, act = HEX.search(f.expected or ""), HEX.search(f.actual or "")
    if not (exp and act):
        return None
    if exp.group(1).lower() == act.group(1).lower():
        return "contradicted: expected and actual colors are identical"
    diff = np.abs(_median_color(design, f.bbox) - _median_color(impl, f.bbox)).max()
    # Thin text or several small elements barely move the median of a large box, so also accept
    # the change when at least 1% of the pixels in the box clearly changed color.
    share = _changed_share(design, impl, f.bbox)
    ok = diff >= 6 or share >= 0.01
    return "color difference confirmed in pixels" if ok else "weak: pixel colors look the same in this box"


def verify(findings: list[Finding], regions: list[Region], design, impl,
           min_conf: float | None = None) -> list[Finding]:
    min_conf = config.MIN_CONFIDENCE if min_conf is None else min_conf
    by_id = {r.id: r for r in regions}

    for f in findings:
        linked = [by_id[i] for i in f.region_ids if i in by_id]
        touching = linked or [r for r in regions if overlaps(f.bbox, r.box, pad=16)]
        if touching:
            f.checks.append(f"pixel evidence: regions {[r.id for r in touching]}")
        else:
            f.checks.append("no pixel evidence under this box")
            f.confidence = min(f.confidence, 0.3)

        if f.category == "color":
            c = _check_color(f, design, impl)
            if c:
                f.checks.append(c)
                if c.startswith("contradicted"):
                    f.status = "rejected"
                elif c.startswith("weak"):
                    f.confidence = min(f.confidence, 0.45)

    # De-duplicate (same category, strongly overlapping). Keep the most confident one.
    kept: list[Finding] = []
    for f in sorted(findings, key=lambda x: -x.confidence):
        dup = next((k for k in kept if k.category == f.category and iou(k.bbox, f.bbox) > 0.4), None)
        if dup:
            dup.checks.append(f"merged duplicate: {f.title}")
            continue
        kept.append(f)

    for f in kept:
        if f.status == "rejected":
            continue
        f.status = "proposed" if f.confidence >= min_conf else "needs_review"

    order = {"critical": 0, "major": 1, "minor": 2}
    kept.sort(key=lambda x: (x.status == "rejected", order.get(x.severity, 3), x.bbox[1]))
    for i, f in enumerate(kept, start=1):
        f.id = f"DQA-{i:03d}"
    return kept
