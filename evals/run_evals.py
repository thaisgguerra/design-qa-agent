#!/usr/bin/env python3
"""Score the agent against the answer key.

Metrics (per analyzer / model):
  recall            share of injected bugs the agent reported (would reach a human)
  precision         share of reported findings that match a real bug (ticket quality)
  category accuracy of matched bugs, was the category right (routing / triage quality)
  clean-screen FP   findings raised on screens with no bugs (noise, the #1 trust killer)
  cost / latency    USD and seconds per screen

Usage:
  python evals/run_evals.py --analyzer baseline
  python evals/run_evals.py --analyzer claude --model claude-sonnet-5-5
  python evals/run_evals.py --analyzer claude --model claude-opus-5-5 --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from designqa.analyze import BaselineAnalyzer, ClaudeAnalyzer  # noqa: E402
from designqa.diff import overlaps  # noqa: E402
from designqa.pipeline import analyze_screen  # noqa: E402

REPORTED = ("proposed", "needs_review")  # what a human would see


def match(bug_box, finding_box):
    return overlaps(bug_box, finding_box, pad=8)


def score_case(truth, findings, statuses=REPORTED):
    fs = [f for f in findings if f["status"] in statuses]
    bugs = truth["bugs"]
    hit, cat_ok, used = 0, 0, set()
    for b in bugs:
        cands = [i for i, f in enumerate(fs) if match(b["bbox"], f["bbox"])]
        if cands:
            hit += 1
            best = next((i for i in cands if fs[i]["category"] == b["category"]), cands[0])
            cat_ok += fs[best]["category"] == b["category"]
            used.update(cands)
    tp_findings = sum(1 for i, f in enumerate(fs) if any(match(b["bbox"], f["bbox"]) for b in bugs))
    return {"bugs": len(bugs), "found": hit, "cat_ok": cat_ok, "findings": len(fs),
            "true_findings": tp_findings, "clean": not bugs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyzer", choices=["baseline", "claude"], default="baseline")
    ap.add_argument("--model", default=None)
    ap.add_argument("--cases", type=Path, default=ROOT / "cases")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-context", action="store_true", help="ablation: hide DOM + spec from the model")
    a = ap.parse_args()

    analyzer = BaselineAnalyzer() if a.analyzer == "baseline" else ClaudeAnalyzer(model=a.model)
    tag = f"{analyzer.name}-{analyzer.model}{'-nocontext' if a.no_context else ''}-{datetime.now():%Y%m%d-%H%M}"
    out_root = ROOT / "results" / tag
    cases = sorted(p for p in a.cases.iterdir() if p.is_dir())
    if a.limit:
        cases = cases[: a.limit]

    rows, cost, secs = [], 0.0, 0.0
    for c in cases:
        truth = json.loads((c / "truth.json").read_text())
        dom = None if a.no_context else json.loads((c / "dom.json").read_text())
        spec = None if a.no_context else json.loads((c / "spec.json").read_text())
        res = analyze_screen(c / "design.png", c / "impl.png", analyzer, out_root / c.name, screen=c.name,
                             dom=dom, spec=spec, dynamic_notes=truth["ignore_note"])
        s = score_case(truth, res["findings"])
        s["case"] = c.name
        s["cost"] = res["usage"]["cost_usd"]
        s["seconds"] = res["usage"]["seconds"]
        rows.append(s)
        cost += s["cost"]
        secs += s["seconds"]
        print(f"{c.name}: bugs {s['bugs']} found {s['found']} | findings {s['findings']} (true {s['true_findings']})")

    bugs = sum(r["bugs"] for r in rows)
    found = sum(r["found"] for r in rows)
    fnd = sum(r["findings"] for r in rows)
    true_f = sum(r["true_findings"] for r in rows)
    clean = [r for r in rows if r["clean"]]
    summary = {
        "analyzer": analyzer.name, "model": analyzer.model, "context": not a.no_context, "cases": len(rows),
        "recall": found / bugs if bugs else 0,
        "precision": true_f / fnd if fnd else 0,
        "category_accuracy": sum(r["cat_ok"] for r in rows) / found if found else 0,
        "findings_per_bug": fnd / bugs if bugs else 0,
        "clean_screen_false_positives": sum(r["findings"] for r in clean) / len(clean) if clean else 0,
        "cost_per_screen_usd": cost / len(rows) if rows else 0,
        "seconds_per_screen": secs / len(rows) if rows else 0,
    }
    (out_root).mkdir(parents=True, exist_ok=True)
    (out_root / "summary.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    print("\n| metric | value |\n|---|---|")
    for k, v in summary.items():
        print(f"| {k} | {v:.2f} |" if isinstance(v, float) else f"| {k} | {v} |")
    print(f"\nSaved to {out_root}")


if __name__ == "__main__":
    main()
