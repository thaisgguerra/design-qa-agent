"""The reasoning step: turn pixel differences into specific, human-readable design findings.

Two analyzers share the same interface so they can be compared in evals:
  * ClaudeAnalyzer   - multimodal LLM that classifies, explains and prioritizes issues
  * BaselineAnalyzer - pure pixel diff, no AI (what most visual regression tools do)
"""
from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import asdict, dataclass, field

from PIL import Image

from . import config
from .diff import Region, overlaps, overlay

CATEGORIES = ["spacing", "color", "typography", "component", "layout",
              "content", "missing_element", "extra_element", "visual_diff"]
SEVERITIES = ["critical", "major", "minor"]


@dataclass
class Finding:
    title: str
    category: str
    severity: str
    element: str
    expected: str
    actual: str
    bbox: list[int]                      # [x, y, w, h] in design coordinates
    confidence: float
    rationale: str = ""
    region_ids: list[int] = field(default_factory=list)
    status: str = "proposed"             # proposed | needs_review | rejected | approved
    checks: list[str] = field(default_factory=list)
    id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0

    def cost(self, model: str) -> float:
        return config.cost_usd(model, self.input_tokens, self.output_tokens)


# --------------------------------------------------------------------------- Baseline
class BaselineAnalyzer:
    name = "pixel-diff-baseline"
    model = "none"

    def analyze(self, design, impl, regions, dom=None, spec=None):
        usage = Usage()
        findings = []
        for r in regions:
            sev = "major" if r.area > 2000 else "minor"
            findings.append(Finding(
                title=f"Visual difference in region {r.id}", category="visual_diff", severity=sev,
                element=f"region {r.id}", expected="(see design)", actual="(see implementation)",
                bbox=r.box, confidence=0.5, region_ids=[r.id],
                rationale=f"{r.area} changed pixels, mean intensity {r.intensity:.0f}"))
        return findings, usage


# --------------------------------------------------------------------------- Claude
SYSTEM = """You are a senior product designer doing Design QA: you compare the approved design \
(exported from Figma) with a screenshot of the implemented product and report every \
deviation an engineer should fix.

Rules:
- Report only real, fixable deviations: spacing/padding, color, typography (family, size, weight, \
line height), component usage or state, layout/alignment, text content, missing or extra elements.
- Ignore anti-aliasing, sub-pixel rendering, image compression and differences inside regions \
listed as dynamic content.
- When measured values are provided (Figma spec or DOM computed styles), use them for \
`expected` and `actual` instead of estimating from pixels, and say which source you used.
- Be concrete: "Button label is 14px/500, design is 16px/600" beats "font looks different".
- One finding per root cause. If a spacing change pushes everything below it down, report the \
spacing change once, not every shifted element.
- Severity: critical = breaks usability, brand or accessibility (e.g. wrong CTA color, missing \
element, unreadable text); major = clearly visible to users; minor = polish (1-4px offsets).
- Confidence: your probability (0-1) that a designer would agree this is a real deviation.
- If a numbered region is only noise, list it in `noise_region_ids` with no finding.
- Bounding boxes use the pixel coordinates of the images you receive: [x, y, width, height]."""

TOOL = {
    "name": "report_findings",
    "description": "Report the design deviations found in this screen section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short ticket title, max 80 chars"},
                        "category": {"type": "string", "enum": CATEGORIES[:-1]},
                        "severity": {"type": "string", "enum": SEVERITIES},
                        "element": {"type": "string", "description": "Which UI element, e.g. 'Primary CTA \"Pay now\"'"},
                        "expected": {"type": "string", "description": "Value in the design"},
                        "actual": {"type": "string", "description": "Value in the implementation"},
                        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                        "region_ids": {"type": "array", "items": {"type": "integer"}},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string", "description": "Evidence, and source of values (figma spec / DOM / visual)"},
                    },
                    "required": ["title", "category", "severity", "element", "expected", "actual",
                                 "bbox", "region_ids", "confidence", "rationale"],
                },
            },
            "noise_region_ids": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["findings", "noise_region_ids"],
    },
}


def _b64(img: Image.Image) -> dict:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def _scale_box(box, f, dy=0):
    x, y, w, h = box
    return [round(x * f), round((y - dy) * f), round(w * f), round(h * f)]


class ClaudeAnalyzer:
    name = "claude"

    def __init__(self, model: str | None = None, client=None, max_edge: int = 1568,
                 tile_height: int = 1400, overlap: int = 120):
        self.model = model or config.MODEL
        self.max_edge = max_edge
        self.tile_height = tile_height
        self.overlap = overlap
        if client is None:
            import anthropic
            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError("Set ANTHROPIC_API_KEY (or use --baseline).")
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.client = client

    def _tiles(self, height: int):
        if height <= self.tile_height + self.overlap:
            return [(0, height)]
        tiles, y = [], 0
        while y < height:
            tiles.append((y, min(height, y + self.tile_height)))
            if y + self.tile_height >= height:
                break
            y += self.tile_height - self.overlap
        return tiles

    def analyze(self, design, impl, regions: list[Region], dom=None, spec=None,
                dynamic_notes: str = ""):
        usage = Usage()
        findings: list[Finding] = []
        for top, bottom in self._tiles(design.height):
            tile_regions = [r for r in regions if r.y < bottom and r.y + r.h > top]
            if not tile_regions:
                continue  # no pixel change in this slice -> no LLM call (cost guardrail)
            f = min(1.0, self.max_edge / max(design.width, bottom - top))
            crop = (0, top, design.width, bottom)
            size = (round(design.width * f), round((bottom - top) * f))
            d_img = design.crop(crop).resize(size, Image.LANCZOS)
            i_img = impl.crop(crop).resize(size, Image.LANCZOS)
            o_img = overlay(impl, regions).crop(crop).resize(size, Image.LANCZOS)

            near = lambda b: any(overlaps(b, r.box, pad=24) for r in tile_regions)
            ctx = {
                "changed_regions": [{"id": r.id, "bbox": _scale_box(r.box, f, top),
                                     "changed_pixels": r.area} for r in tile_regions],
                "figma_spec": [dict(s, bbox=_scale_box(s["bbox"], f, top))
                               for s in (spec or []) if s.get("bbox") and near(s["bbox"])][:60],
                "dom_computed_styles": [dict(e, bbox=_scale_box(e["bbox"], f, top))
                                        for e in (dom or []) if e.get("bbox") and near(e["bbox"])][:80],
            }
            text = ("Image 1 is the DESIGN (source of truth). Image 2 is the IMPLEMENTATION. "
                    "Image 3 is the implementation with numbered red boxes on regions where pixels changed.\n"
                    f"Image size: {size[0]}x{size[1]} px.\n"
                    + (f"Dynamic content to ignore: {dynamic_notes}\n" if dynamic_notes else "")
                    + "Measured context (JSON):\n" + json.dumps(ctx, ensure_ascii=False)
                    + "\n\nReview every numbered region and report findings with report_findings.")
            t0 = time.time()
            resp = self.client.messages.create(
                model=self.model, max_tokens=4096, system=SYSTEM, tools=[TOOL],
                tool_choice={"type": "tool", "name": "report_findings"},
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Image 1 (design):"}, _b64(d_img),
                    {"type": "text", "text": "Image 2 (implementation):"}, _b64(i_img),
                    {"type": "text", "text": "Image 3 (diff overlay):"}, _b64(o_img),
                    {"type": "text", "text": text},
                ]}],
            )
            usage.seconds += time.time() - t0
            usage.calls += 1
            usage.input_tokens += resp.usage.input_tokens
            usage.output_tokens += resp.usage.output_tokens
            payload = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), {})
            for raw in payload.get("findings", []):
                x, y, w, h = raw["bbox"]
                findings.append(Finding(
                    title=raw["title"][:120], category=raw["category"], severity=raw["severity"],
                    element=raw["element"], expected=raw["expected"], actual=raw["actual"],
                    bbox=[round(x / f), round(y / f + top), round(w / f), round(h / f)],
                    confidence=float(raw.get("confidence", 0.5)), rationale=raw.get("rationale", ""),
                    region_ids=[int(i) for i in raw.get("region_ids", [])]))
        return findings, usage
