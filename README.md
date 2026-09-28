# Design QA Agent

An AI agent that compares an approved Figma frame with the implemented screen, finds every deviation (spacing, color, typography, components, layout, content), explains it in the language engineers use, and, after a human approves, opens tickets with side by side evidence.

> Built by Thais Guerra as an AI Product Management case study. The product thinking (problem, metrics, guardrails, evals, trade-offs) is in the case study document; this repo is the working prototype behind it.

## Why

Design QA is manual, slow and inconsistent. A designer opens Figma and staging side by side, hunts for differences, takes screenshots, writes tickets. It happens late, it depends on who has time, and small inconsistencies pile up into design debt. Pixel diff tools find *that* something changed but not *what*, *why it matters*, or *how to fix it*, so teams drown in noise.

## How it works

```
 Figma frame ─┐                                  ┌─> report.html (review queue)
              ├─> 1. Perceive ─> 2. Reason ─> 3. Verify ─> 4. Human review ─> 5. Act
 Live page  ──┘    pixel diff     Claude         guardrails     approve / skip       tickets
                   + Figma spec   (vision +      (evidence,                          (ClickUp,
                   + DOM styles    measured       color check,                        Linear,
                                   context)       dedupe, conf.)                      markdown)
```

1. **Perceive (deterministic).** Export the frame from Figma, capture the page with Playwright at the same width, and run a pixel diff to find the regions that changed. Also collect *measured truth*: text styles and auto-layout spacing from the Figma file, and computed CSS from the page.
2. **Reason (LLM).** Claude receives design, implementation, a numbered diff overlay and the measured values for the changed areas only. It returns structured findings through a forced tool call: category, severity, element, expected vs actual values, location, confidence and rationale. Screens with no pixel change are never sent to the model.
3. **Verify (guardrails).** A finding survives only if there are changed pixels under it, claimed color differences are visible in the sampled pixels, and it is not a duplicate. Low confidence findings go to a review queue instead of becoming tickets.
4. **Human in the loop.** The designer or PM approves findings in the terminal or report. Nothing is written to the tracker without approval (an optional auto-approve threshold exists for mature teams).
5. **Act.** Tickets are created with a consistent template and a side by side evidence image.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # add ANTHROPIC_API_KEY (and FIGMA_TOKEN if you use --figma)
```

Compare a Figma frame with a live page:

```bash
python cli.py --figma "https://www.figma.com/design/<KEY>/<name>?node-id=12-345" \
              --url https://staging.example.com/checkout --screen "Checkout"
```

Compare two images you already have (Figma export at 1x + a screenshot at the same width):

```bash
python cli.py --design checkout-figma.png --impl checkout-build.png --screen "Checkout"
```

Useful flags:

| Flag | What it does |
|---|---|
| `--baseline` | Pixel diff only, no LLM (free, used as the comparison baseline) |
| `--model claude-opus-5-5` | Use the higher accuracy model |
| `--mask ".timestamp" ".avatar"` | Hide dynamic elements on the live page before capture |
| `--ignore "the chart data is live"` | Plain language note on what the model should ignore |
| `--tracker clickup` / `linear` | Where tickets go (default: markdown files in `runs/<screen>/tickets`) |
| `--approve interactive/confident/all/none` | Which findings become tickets |

Output lives in `runs/<screen>/`: `report.html`, `findings.json`, `evidence/*.png`, `tickets/`.

## Evals

The eval set has a known answer key. The same screen is rendered twice: the clean version plays the Figma design and a copy with injected bugs plays the implementation. Clean cases (only a dynamic timestamp changed) measure false positives.

```bash
python evals/make_dataset.py --n 24          # build cases (4 clean + 20 with 1 to 3 bugs)
python evals/run_evals.py --analyzer baseline
python evals/run_evals.py --analyzer claude --model claude-sonnet-5-5
python evals/run_evals.py --analyzer claude --model claude-opus-5-5
python evals/run_evals.py --analyzer claude --no-context    # ablation: images only
```

Metrics: recall, precision, category accuracy, findings per bug (noise), false positives on clean screens, cost and latency per screen.

Baseline result (pixel diff, no AI) on the 24 cases:

| Metric | Pixel diff baseline |
|---|---|
| Recall | 100% |
| Precision | 66% |
| Category accuracy | 0% (it cannot say what changed) |
| Findings per real bug | 2.3 |
| False positives per clean screen | 1.0 |
| Cost per screen | $0 |

The baseline catches everything but produces 2.3 tickets per real bug, flags dynamic content, and never explains the problem. The agent's job is to keep recall high while fixing the other rows.

## Tests

```bash
python -m pytest -q tests      # offline, the Claude client is mocked
```

## Project layout

```
designqa/capture.py    Figma export + spec, Playwright capture + computed styles
designqa/diff.py       alignment, pixel diff, changed regions, overlay
designqa/analyze.py    Claude analyzer (prompt, tool schema, tiling) and pixel baseline
designqa/verify.py     guardrails: evidence, color check, dedupe, confidence gate
designqa/evidence.py   side by side evidence images
designqa/trackers.py   ClickUp, Linear, markdown tickets
designqa/report.py     HTML review report
evals/                 dataset generator, answer key, scoring
```

## Known limitations and next steps

- Layout shifts cascade: one spacing bug moves everything below it. The model is told to report the root cause once, but the diff regions still multiply. Next step: element-level alignment (match Figma layers to DOM nodes) before diffing.
- Needs the design exported at the same width as the viewport. Responsive breakpoints mean one run per frame.
- States (hover, error, empty, loading) require one capture per state.
- Design tokens: comparing against token names (not only hex values) would make tickets more actionable.
