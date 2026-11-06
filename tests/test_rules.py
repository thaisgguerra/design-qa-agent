"""Offline tests for the rules analyzer (measured values only, no LLM)."""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from designqa.diff import compute_diff  # noqa: E402
from designqa.rules import RulesAnalyzer  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "evals" / "cases"


def el(tag, bbox, cls=None, text=None, **kw):
    base = {"tag": tag, "id": None, "cls": cls, "text": text, "font": "Inter", "size": 16, "weight": 400,
            "line_height": "normal", "color": "#111827", "bg": "transparent", "radius": "0px",
            "padding": "0px", "margin": "0px", "gap": "normal", "bbox": bbox}
    return {**base, **kw}


def run(spec, dom, regions=()):
    blank = Image.new("RGB", (800, 600), "white")
    findings, usage = RulesAnalyzer().analyze(blank, blank, list(regions), dom=dom, spec=spec)
    return findings, usage


def test_categories_from_measured_values():
    spec = [el("h1", [0, 0, 400, 30], text="Title", weight=700),
            el("button", [0, 100, 100, 40], cls="btn-primary", text="Pay", bg="#2563EB"),
            el("button", [120, 100, 80, 40], cls="btn-secondary", text="Back", bg="#FFFFFF")]
    dom = [el("h1", [0, 0, 400, 30], text="Title", weight=400),
           el("button", [0, 100, 100, 40], cls="btn-primary", text="Submit", bg="#3B82F6"),
           el("button", [120, 100, 80, 40], cls="btn-secondary", text="Back", bg="#111827", color="#FFFFFF")]
    findings, usage = run(spec, dom)
    cats = sorted(f.category for f in findings)
    assert cats == ["color", "component", "content", "typography"]
    cta = next(f for f in findings if f.category == "color")
    assert cta.severity == "critical" and "#2563EB" in cta.expected and "#3B82F6" in cta.actual
    assert usage.calls == 0 and usage.input_tokens == 0  # free: no model involved


def test_dynamic_dates_are_ignored():
    spec = [el("span", [0, 0, 200, 16], text="Sep 28, 2026 at 10:42")]
    dom = [el("span", [0, 0, 200, 16], text="Sep 29, 2026 at 08:15")]
    assert run(spec, dom)[0] == []


def test_same_change_on_many_elements_is_one_finding():
    spec = [el("label", [0, y, 200, 15], text=f"Field {y}", color="#4B5563") for y in (0, 50, 100)]
    dom = [dict(e, color="#B0B7C3") for e in spec]
    findings, _ = run(spec, dom)
    assert len(findings) == 1 and findings[0].element.startswith("3 x label")


def test_cascade_reports_only_the_root_cause():
    # Card padding shrinks: every child moves, but only the padding is reported.
    spec = [el("section", [0, 0, 400, 300], cls="card", padding="24px"),
            el("h2", [24, 24, 352, 20], text="Payment"),
            el("input", [24, 60, 352, 40])]
    dom = [el("section", [0, 0, 400, 300], cls="card", padding="12px"),
           el("h2", [12, 12, 376, 20], text="Payment"),
           el("input", [12, 48, 376, 40])]
    findings, _ = run(spec, dom)
    assert [f.category for f in findings] == ["spacing"]


def test_unexplained_shift_becomes_one_spacing_finding():
    spec = [el("section", [0, 0, 400, 300], cls="card"),
            el("label", [20, 20, 200, 15], text="A"), el("label", [20, 80, 200, 15], text="B"),
            el("label", [20, 140, 200, 15], text="C")]
    dom = [spec[0], spec[1], dict(spec[2], bbox=[20, 68, 200, 15]), dict(spec[3], bbox=[20, 128, 200, 15])]
    findings, _ = run(spec, dom)
    assert len(findings) == 1 and findings[0].category == "spacing" and '"B"' in findings[0].element


def test_missing_and_extra_elements():
    spec = [el("h2", [0, 0, 200, 20], text="Summary"), el("span", [0, 30, 100, 20], cls="badge", text="NEW"),
            el("p", [0, 60, 200, 20], text="Body")]
    dom = [el("h2", [0, 0, 200, 20], text="Summary"), el("p", [0, 60, 200, 20], text="Body"),
           el("hr", [0, 90, 200, 1], cls="divider")]
    cats = sorted(f.category for f in run(spec, dom)[0])
    assert cats == ["extra_element", "missing_element"]


def test_eval_case_end_to_end():
    """case_18: CTA color + total alignment, with a dynamic timestamp that must be ignored."""
    c = CASES / "case_18"
    design, impl = Image.open(c / "design.png").convert("RGB"), Image.open(c / "impl.png").convert("RGB")
    _, regions = compute_diff(design, impl)
    findings, _ = RulesAnalyzer().analyze(design, impl, regions, dom=json.loads((c / "dom.json").read_text()),
                                          spec=json.loads((c / "spec.json").read_text()))
    assert sorted(f.category for f in findings) == ["color", "layout"]
