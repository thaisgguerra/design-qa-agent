#!/usr/bin/env python3
"""Design QA agent: compare a Figma frame with the implemented screen and open tickets.

Examples
  # Figma frame vs live page, tickets as local markdown files
  python cli.py --figma "https://www.figma.com/design/KEY/App?node-id=12-345" --url https://staging.app.com/checkout

  # Two screenshots you already have (no API tokens for Figma needed)
  python cli.py --design design.png --impl build.png --screen "Checkout"

  # No AI at all (baseline for comparison / offline demo)
  python cli.py --design design.png --impl build.png --baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from designqa import config
from designqa.analyze import BaselineAnalyzer, ClaudeAnalyzer, Finding
from designqa.capture import capture_url, export_figma_frame, fetch_figma_spec
from designqa.pipeline import analyze_screen, save
from designqa.trackers import get_tracker


def review(findings: list[dict], mode: str) -> list[dict]:
    """Human in the loop: decide which findings become tickets."""
    candidates = [f for f in findings if f["status"] in ("proposed", "needs_review")]
    if mode == "none":
        return []
    if mode == "all":
        return [f for f in candidates if f["status"] == "proposed"]
    if mode == "confident":
        return [f for f in candidates if f["status"] == "proposed" and f["confidence"] >= config.AUTO_APPROVE_CONFIDENCE]
    approved = []
    print(f"\n{len(candidates)} findings to review. [y] open ticket  [n] skip  [q] stop\n")
    for f in candidates:
        flag = "  (low confidence)" if f["status"] == "needs_review" else ""
        print(f"{f['id']} [{f['severity']}/{f['category']}] {f['title']}{flag}\n"
              f"   expected: {f['expected']}\n   actual:   {f['actual']}\n   evidence: {f['evidence']}")
        ans = input("   open ticket? [y/n/q] ").strip().lower()
        if ans == "q":
            break
        if ans == "y":
            approved.append(f)
    return approved


def main() -> int:
    p = argparse.ArgumentParser(description="Design QA agent")
    src = p.add_argument_group("design source (one of)")
    src.add_argument("--figma", help="Figma frame link (needs FIGMA_TOKEN)")
    src.add_argument("--design", type=Path, help="Design PNG exported from Figma")
    impl = p.add_argument_group("implementation source (one of)")
    impl.add_argument("--url", help="URL of the implemented screen (captured with Playwright)")
    impl.add_argument("--impl", type=Path, help="Screenshot PNG of the implementation")
    p.add_argument("--screen", default=None, help="Screen name used in tickets")
    p.add_argument("--out", type=Path, default=None, help="Output folder (default runs/<screen>)")
    p.add_argument("--baseline", action="store_true", help="Pixel diff only, no LLM")
    p.add_argument("--model", default=None, help=f"Claude model (default {config.MODEL})")
    p.add_argument("--mask", nargs="*", default=[], help="CSS selectors with dynamic content to hide")
    p.add_argument("--ignore", default="", help="Plain-language note on dynamic content the model should ignore")
    p.add_argument("--tracker", choices=["markdown", "clickup", "linear"], default="markdown")
    p.add_argument("--approve", choices=["interactive", "confident", "all", "none"], default=None,
                   help="Which findings become tickets (default: interactive in a terminal, else none)")
    a = p.parse_args()

    if not (a.figma or a.design) or not (a.url or a.impl):
        p.error("Provide a design (--figma or --design) and an implementation (--url or --impl).")

    screen = a.screen or (a.url or (a.impl.stem if a.impl else "screen"))
    slug = "".join(c if c.isalnum() else "-" for c in (a.screen or "screen").lower()).strip("-")
    out = a.out or Path("runs") / slug
    out.mkdir(parents=True, exist_ok=True)

    spec = None
    design_path = a.design
    if a.figma:
        if not config.FIGMA_TOKEN:
            p.error("Set FIGMA_TOKEN in .env to read from Figma (or export the frame as PNG and use --design).")
        design_path = export_figma_frame(a.figma, config.FIGMA_TOKEN, out / "design.png")
        spec = fetch_figma_spec(a.figma, config.FIGMA_TOKEN)
        (out / "figma_spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        print(f"Figma frame exported ({len(spec)} spec items)")

    dom = None
    impl_path = a.impl
    if a.url:
        width = Image.open(design_path).width
        impl_path = out / "implementation.png"
        dom = capture_url(a.url, impl_path, width=width, mask_selectors=a.mask)
        (out / "dom.json").write_text(json.dumps(dom, indent=2, ensure_ascii=False))
        print(f"Page captured at {width}px ({len(dom)} elements measured)")

    analyzer = BaselineAnalyzer() if a.baseline else ClaudeAnalyzer(model=a.model)
    result = analyze_screen(design_path, impl_path, analyzer, out, screen=screen, dom=dom, spec=spec,
                            dynamic_notes=a.ignore)
    fs = result["findings"]
    print(f"\n{len(result['regions'])} changed regions -> {len(fs)} findings "
          f"({sum(f['status']=='proposed' for f in fs)} proposed, "
          f"{sum(f['status']=='needs_review' for f in fs)} need review, "
          f"{sum(f['status']=='rejected' for f in fs)} rejected) · ${result['usage']['cost_usd']:.3f}")

    mode = a.approve or ("interactive" if sys.stdin.isatty() else "none")
    approved = review(fs, mode)
    if approved:
        tracker = get_tracker(a.tracker, out)
        for f in approved:
            f["ticket"] = tracker.create(Finding(**{k: f[k] for k in Finding.__dataclass_fields__}),
                                         Path(f["evidence"]), screen)
            f["status"] = "approved"
            print(f"  ticket: {f['ticket']}")
        save(result, out)
    print(f"\nReport: {out / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
