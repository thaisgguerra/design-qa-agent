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
