"""End-to-end agent loop: perceive (diff) -> reason (LLM) -> verify (guardrails) -> act (tickets)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .analyze import Usage
from .diff import compute_diff, diff_ratio, load_pair, overlay
from .evidence import make_evidence
from .report import write_report
from .verify import verify


def _scale_dom(dom, s):
    if not dom or abs(s - 1) < 1e-3:
        return dom
    return [dict(e, bbox=[round(v * s) for v in e["bbox"]], size=(e.get("size") or 0) * s) for e in dom]


def analyze_screen(design_path: Path, impl_path: Path, analyzer, out_dir: Path, screen: str = "screen",
                   dom=None, spec=None, dynamic_notes: str = "", threshold: int = 24) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ev_dir = out_dir / "evidence"
    ev_dir.mkdir(exist_ok=True)

    design, impl, s = load_pair(design_path, impl_path)
    mask, regions = compute_diff(design, impl, threshold=threshold)
    overlay(impl, regions).save(out_dir / "overlay.png")

    if regions:
        kwargs = {"dynamic_notes": dynamic_notes} if analyzer.name == "claude" else {}
        findings, usage = analyzer.analyze(design, impl, regions, dom=_scale_dom(dom, s), spec=spec, **kwargs)
    else:
        findings, usage = [], Usage()
    findings = verify(findings, regions, design, impl)

    for f in findings:
        f_ev = make_evidence(design, impl, f.bbox, ev_dir / f"{f.id}.png")
        f.__dict__["evidence"] = str(f_ev)

    result = {
        "screen": screen,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "analyzer": analyzer.name,
        "model": analyzer.model,
        "diff_ratio": diff_ratio(mask),
        "regions": [r.to_dict() for r in regions],
        "findings": [dict(f.to_dict(), evidence=f.__dict__.get("evidence")) for f in findings],
        "usage": {**usage.__dict__, "cost_usd": usage.cost(analyzer.model)},
        "artifacts": {"overlay": str(out_dir / "overlay.png"), "design": str(design_path), "impl": str(impl_path)},
    }
    save(result, out_dir)
    return result


def save(result: dict, out_dir: Path) -> None:
    (out_dir / "findings.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    write_report(result, out_dir / "report.html")
