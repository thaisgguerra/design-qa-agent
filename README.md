https://github.com/user-attachments/assets/c7b16191-d8f8-4f40-b03e-2cb96339163d

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
| `--rules` | Measured values only (Figma spec vs computed CSS), no LLM, free |
| `--spec` / `--dom` | Load saved Figma spec and computed styles JSON (to use `--rules` with `--design` / `--impl`) |
| `--model claude-opus-5-5` | Use the higher accuracy model |
| `--mask ".timestamp" ".avatar"` | Hide dynamic elements on the live page before capture |
| `--ignore "the chart data is live"` | Plain language note on what the model should ignore |
| `--tracker clickup` / `linear` | Where tickets go (default: markdown files in `runs/<screen>/tickets`) |
| `--approve interactive/confident/all/none` | Which findings become tickets |

Output lives in `runs/<screen>/`: `report.html`, `findings.json`, `evidence/*.png`, `tickets/`.

## Demo (no API key, $0)

`demo/checkout/` is one checkout screen with three injected bugs (CTA color, card padding, logo color) and a timestamp that changes on every load.

```bash
python cli.py --design demo/checkout/design.png --impl demo/checkout/impl.png \
              --spec demo/checkout/spec.json --dom demo/checkout/dom.json \
              --rules --screen "Checkout" --out demo/run-rules --approve confident
python cli.py --design demo/checkout/design.png --impl demo/checkout/impl.png \
              --baseline --screen "Checkout" --out demo/run-baseline --approve none
```

| | Pixel diff | Rules |
|---|---|---|
| Changed regions | 8 | 8 |
| Findings | 8, all "visual difference" | 3: CTA color (critical), card padding, logo for review |
| Timestamp | flagged | ignored as dynamic |
| Card padding cascade | 5 separate alerts | 1 root cause, 24px vs 12px |
| Tickets | none (nothing to say) | 2, with expected vs actual and evidence |

Results are already in `demo/run-rules/` and `demo/run-baseline/` (open `report.html`). Rebuild the screen with `python evals/make_dataset.py --bugs cta_color,card_padding,logo_color --out demo` and move `demo/demo` to `demo/checkout`.

## Brand Check (web app)

A simple web page for the design team: paste a link (Figma, Google Drive, or a direct image/PDF URL) or upload the **art**, do the same for the **client's brand manual**, and get an on-brand score as a percentage, with a score per criterion (logo, color, typography, composition, graphic elements, tone of voice), the official palette against the colors measured in the art, and a list of what to fix. The interface is in Portuguese and follows the Flori Tech visual identity.

```bash
pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY (FIGMA_TOKEN only if you want Figma links)
uvicorn web.app:app --port 8000
```

Open http://localhost:8000.

How it scores, in the same perceive / reason / verify shape as the screen agent:

- **Perceive.** Dominant colors of the art are measured with PIL (no AI).
- **Reason.** Claude reads the brand manual as a native PDF (cached, since the same manual is reused across many pieces) plus the art images, and returns a per-criterion score and findings through a forced tool call. Criteria the manual does not cover are marked as not applicable, so they don't count.
- **Verify.** The overall score is computed in code as a weighted mean of the applicable criteria (logo 25%, color 25%, typography 20%, composition 15%, graphic elements 10%, tone 5%), not by the model. The palette the model read from the manual is checked against the measured colors (CIE ΔE). Low-confidence findings go to a "to review" list.

**Free mode (no API key).** Without `ANTHROPIC_API_KEY` the page still works and costs nothing: it only reports what can be measured. Colors: the official palette is read from the codes written in the manual (hex or RGB) and compared with the art's measured colors. Logo: the transparent logo image is taken from the manual, searched in the art with color-independent edge matching, confirmed by checking that the shape stands out from its background, and then its color and its distance to the edges are checked against the clearspace rule written in the manual (e.g. "um terço da largura"). Fonts: compared only when both files are PDFs with named fonts. Composition, graphic elements and tone of voice need the AI mode.

**GitHub Pages (no server).** The same page is published to GitHub Pages by `.github/workflows/pages.yml`. When there is no `/api` it runs the free mode in the browser (`web/static/engine.js`, a port of `brand_free.py` using pdf.js and OpenCV.js), so files never leave the user's computer. Only uploads work there, since browsers can't download Drive or Figma files from another site.

Google Drive files must be shared as "Anyone with the link". Links are fetched server side, so URLs that resolve to private networks are refused.

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

### Rules analyzer (measured values, no LLM, $0)

```bash
python evals/run_evals.py --analyzer rules
python evals/make_dataset.py --n 40 --clean 6 --seed 2026 --out evals/holdout   # fresh cases, not used to write the rules
python evals/run_evals.py --analyzer rules --cases evals/holdout
python evals/run_evals.py --analyzer rules --cases evals/holdout --perturb 3      # stress test
```

`designqa/rules.py` compares the Figma spec with the computed CSS element by element and turns each measured difference into a categorized finding with exact values (text -> content, font -> typography, padding/margin/gap -> spacing, radius or several paint props -> component, color/background -> color, unmatched elements -> missing/extra). Movement is measured relative to the element's container, so a cascade is reported once at its root. Dates and times that changed on both sides are treated as dynamic. Pixel regions no element explains (icons, SVG, borders) become low-confidence "unexplained" findings for human review.

| Metric | Baseline (24 cases) | Rules (24 cases) | Baseline (holdout, 40) | Rules (holdout, 40) |
|---|---|---|---|---|
| Recall | 100% | 100% | 100% | 100% |
| Precision | 66% | 100% | 38% | 100% |
| Category accuracy | 0% | 90% | 0% | 88% |
| Findings per real bug | 2.3 | 1.0 | 4.0 | 1.0 |
| False positives per clean screen | 1.0 | 0 | 1.0 | 0 |
| Cost per screen | $0 | $0 | $0 | $0 |

The miss in category is always the same kind of bug: changes that leave no trace in the measured styles (an SVG logo recolored, a pseudo-element divider). They are still found, but as "unexplained" or "size changed". Those are exactly the regions worth sending to the LLM.

**Read this before trusting the 100%.** In this synthetic set the spec and the DOM come from the same HTML, so elements match 1:1 and positions are exact. Real Figma layers do not map 1:1 to DOM nodes and rendering differs by a few pixels. `--perturb PX` mimics that by dropping CSS class names and jittering every DOM box by up to PX pixels:

| DOM noise | Precision | Findings per bug | False positives per clean screen |
|---|---|---|---|
| 0 px | 100% | 1.0 | 0 |
| 1 px | 98% | 1.1 | 0 |
| 2 px | 62% | 1.9 | 0 |
| 3 px | 14% | 11.3 | 19.5 |

Rules are precise when matching is clean and collapse when it is not. The product conclusion: measured rules are the cheap first layer, and the LLM earns its cost on judgment (is this shift a bug or rendering noise, what is this unexplained region), not on reading values the spec already has.

## Tests

```bash
python -m pytest -q tests      # offline, the Claude client is mocked
```

## Project layout

```
designqa/capture.py    Figma export + spec, Playwright capture + computed styles
designqa/diff.py       alignment, pixel diff, changed regions, overlay
designqa/analyze.py    Claude analyzer (prompt, tool schema, tiling) and pixel baseline
designqa/rules.py      rules analyzer: spec vs computed CSS, cascades, no LLM
designqa/verify.py     guardrails: evidence, color check, dedupe, confidence gate
designqa/evidence.py   side by side evidence images
designqa/trackers.py   ClickUp, Linear, markdown tickets
designqa/report.py     HTML review report
designqa/sources.py    brand check inputs: Figma, Google Drive, URLs, uploads
designqa/brand.py      brand check: palette measurement, Claude scoring, guardrails
web/                   Brand Check web app (FastAPI + static page)
evals/                 dataset generator, answer key, scoring
```

## Known limitations and next steps

- Layout shifts cascade: one spacing bug moves everything below it. The model is told to report the root cause once, but the diff regions still multiply. Next step: element-level alignment (match Figma layers to DOM nodes) before diffing.
- Needs the design exported at the same width as the viewport. Responsive breakpoints mean one run per frame.
- States (hover, error, empty, loading) require one capture per state.
- Design tokens: comparing against token names (not only hex values) would make tickets more actionable.
- Rules are brittle to imperfect element matching (see the stress test). Next step: a hybrid analyzer that runs the rules first and sends only unexplained or ambiguous regions to Claude, plus a tolerance learned from clean screens.
