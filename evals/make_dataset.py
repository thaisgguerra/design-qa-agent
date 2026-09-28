#!/usr/bin/env python3
"""Build an eval set with KNOWN answers.

We render the same screen twice: the untouched version plays the role of the Figma
design, and a copy with injected bugs plays the implementation. Because we injected
the bugs, we know exactly what the agent should find (ground truth), so we can
measure precision and recall instead of eyeballing demos.

The set also contains clean cases (no bugs, only a changed timestamp that the agent
is told to ignore) to measure false positives, which is what kills trust in QA tools.

Usage: python evals/make_dataset.py --n 24 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from designqa.capture import DOM_JS  # noqa: E402

# Each mutation is one realistic design-to-code slip, with the answer key.
MUTATIONS = [
    {"id": "cta_color", "category": "color", "severity": "critical", "selector": "#pay",
     "css": "#pay{background:#3B82F6!important}", "desc": "Primary CTA blue #2563EB -> #3B82F6"},
    {"id": "cta_radius", "category": "component", "severity": "minor", "selector": "#pay",
     "css": "#pay{border-radius:2px!important}", "desc": "CTA corner radius 10px -> 2px"},
    {"id": "title_size", "category": "typography", "severity": "major", "selector": "h1",
     "css": "h1{font-size:22px!important}", "desc": "Page title 28px -> 22px"},
    {"id": "title_weight", "category": "typography", "severity": "major", "selector": "h1",
     "css": "h1{font-weight:400!important}", "desc": "Page title weight 700 -> 400"},
    {"id": "desc_font", "category": "typography", "severity": "major", "selector": ".plan-desc",
     "css": ".plan-desc{font-family:'DejaVu Serif',serif!important}", "desc": "Plan description uses a serif font"},
    {"id": "card_padding", "category": "spacing", "severity": "major", "selector": "#payment",
     "css": "#payment{padding:12px!important}", "desc": "Payment card padding 24px -> 12px"},
    {"id": "field_gap", "category": "spacing", "severity": "minor", "selector": "#payment .field:nth-child(3)",
     "css": "#payment .field:nth-child(2){margin-bottom:4px!important}", "desc": "Gap between card fields 16px -> 4px"},
    {"id": "label_color", "category": "color", "severity": "minor", "selector": "#payment .field label",
     "css": "#payment .field label{color:#B0B7C3!important}", "desc": "Field labels too light (#4B5563 -> #B0B7C3)"},
    {"id": "missing_badge", "category": "missing_element", "severity": "major", "selector": ".badge",
     "css": ".badge{visibility:hidden!important}", "desc": "'MOST POPULAR' badge missing"},
    {"id": "extra_divider", "category": "extra_element", "severity": "minor", "selector": ".secure",
     "css": ".secure::before{content:'';display:block;border-top:3px dashed #9CA3AF;margin-bottom:10px}",
     "desc": "Extra dashed divider above security note"},
    {"id": "cta_copy", "category": "content", "severity": "major", "selector": "#pay",
     "js": "document.querySelector('#pay').textContent='Submit'", "desc": "CTA label 'Pay now' -> 'Submit'"},
    {"id": "total_align", "category": "layout", "severity": "major", "selector": ".total",
     "css": ".total{justify-content:flex-start!important;gap:12px}", "desc": "Total amount not right-aligned"},
    {"id": "tabs_gap", "category": "spacing", "severity": "minor", "selector": ".tabs",
     "css": ".tabs{gap:10px!important}", "desc": "Nav tab gap 24px -> 10px"},
    {"id": "logo_color", "category": "color", "severity": "major", "selector": ".logo",
     "css": ".logo{color:#7C3AED!important}", "desc": "Logo color blue -> purple"},
    {"id": "secondary_style", "category": "component", "severity": "major", "selector": ".btn-secondary",
     "css": ".btn-secondary{background:#111827!important;color:#FFFFFF!important;border-color:#111827!important}",
     "desc": "Secondary 'Back' button rendered with primary (filled) style"},
]
# Mutations that touch the same element conflict with each other.
CONFLICTS = [{"cta_color", "cta_radius", "cta_copy"}, {"title_size", "title_weight"}]
IGNORE_NOTE = "The 'Last updated' timestamp under the title is dynamic."


def conflict(a, chosen):
    return any(a in g and (g & chosen) for g in CONFLICTS)


def pick(rng, k):
    chosen: set[str] = set()
    pool = [m["id"] for m in MUTATIONS]
    rng.shuffle(pool)
    for mid in pool:
        if len(chosen) >= k:
            break
        if not conflict(mid, chosen):
            chosen.add(mid)
    return [m for m in MUTATIONS if m["id"] in chosen]


def union(a, b):
    if not a:
        return b
    if not b:
        return a
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x0, y0, x1 - x0, y1 - y0]


def box(page, selector):
    r = page.evaluate("""(s)=>{const e=document.querySelector(s); if(!e) return null;
        const b=e.getBoundingClientRect(); return [Math.round(b.left),Math.round(b.top+scrollY),Math.round(b.width),Math.round(b.height)]}""", selector)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--clean", type=int, default=4, help="cases with no bugs (false positive test)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--width", type=int, default=1100)
    ap.add_argument("--out", type=Path, default=ROOT / "cases")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    rng = random.Random(a.seed)
    html = (ROOT / "screen.html").read_text()
    a.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": a.width, "height": 800}, device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(200)
        page.screenshot(path=str(a.out / "_design.png"), full_page=True)
        design_dom = page.evaluate(DOM_JS, 250)

        for i in range(a.n):
            cid = f"case_{i + 1:02d}"
            d = a.out / cid
            d.mkdir(exist_ok=True)
            muts = [] if i < a.clean else pick(rng, rng.choice([1, 1, 2, 2, 3]))
            dynamic = i < a.clean or rng.random() < 0.3

            # design = untouched page
            page.set_content(html)
            design_boxes = {m["id"]: box(page, m["selector"]) for m in muts}
            (d / "design.png").write_bytes((a.out / "_design.png").read_bytes())

            # implementation = page with injected bugs
            page.set_content(html)
            for m in muts:
                if m.get("css"):
                    page.add_style_tag(content=m["css"])
                if m.get("js"):
                    page.evaluate(m["js"])
            if dynamic:
                page.evaluate("document.querySelector('#ts').textContent='Sep 29, 2026 at 08:15'")
            page.wait_for_timeout(100)
            page.screenshot(path=str(d / "impl.png"), full_page=True)
            dom = page.evaluate(DOM_JS, 250)
            truth = [{"id": m["id"], "category": m["category"], "severity": m["severity"], "desc": m["desc"],
                      "bbox": union(design_boxes[m["id"]], box(page, m["selector"]))} for m in muts]

            (d / "dom.json").write_text(json.dumps(dom, indent=1))
            (d / "spec.json").write_text(json.dumps(design_dom, indent=1))  # stands in for the Figma spec
            (d / "truth.json").write_text(json.dumps({"bugs": truth, "dynamic_timestamp": dynamic,
                                                      "ignore_note": IGNORE_NOTE}, indent=2))
            print(cid, [m["id"] for m in muts] or "clean", "+ts" if dynamic else "")
        browser.close()


if __name__ == "__main__":
    main()
