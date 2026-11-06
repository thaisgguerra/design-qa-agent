"""Rules analyzer: explain pixel changes with measured values only, no LLM and no cost.

It compares the Figma spec (design) with the computed styles of the page (implementation),
element by element, and turns each measured difference into a categorized finding:

  text changed                       -> content
  font family / size / weight / lh   -> typography
  padding / margin / gap             -> spacing
  radius, or 2+ paint props at once  -> component   (e.g. secondary button styled as primary)
  color or background only           -> color
  element only in the design         -> missing_element
  element only in the build          -> extra_element
  moved with no property change      -> spacing (vertical) or layout (horizontal), root cause only
  leaf resized with no prop change   -> layout

Cascades: an element that moved or resized is not reported when an earlier change explains it
(an ancestor changed, or something above it in the same column changed). The first unexplained
shift becomes the root cause and explains what follows.

Pixel regions that no element explains (icons, SVG, borders, pseudo elements) are kept as
"unexplained visual change" findings with low confidence, so recall does not drop: they go to
the human review queue. In a hybrid setup these are the only regions worth sending to an LLM.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .analyze import Finding, Usage
from .diff import Region, overlaps

TYPO = ("font", "size", "weight", "line_height")
SPACING = ("padding", "margin", "gap")
PAINT = ("color", "bg")
DATE = re.compile(r"\b(\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2})",
                  re.I)
MOVE_TOL = 2   # px of movement ignored (sub-pixel rounding)


def _key(e):
    return (e.get("tag"), e.get("cls"))


def _name(e):
    label = f"{e.get('tag')}{'.' + e['cls'] if e.get('cls') else ''}"
    txt = (e.get("text") or "").strip()
    return f'{label} "{txt[:40]}"' if txt else label


def _contains(a, b, pad=1):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax - pad <= bx and ay - pad <= by and bx + bw <= ax + aw + pad and by + bh <= ay + ah + pad


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _is_dynamic(a, b):
    """Text that looks like a date or time on both sides is treated as dynamic content."""
    return bool(a and b and DATE.search(a) and DATE.search(b))


def _px(v):
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


class RulesAnalyzer:
    name = "rules"
    model = "none"

    def analyze(self, design, impl, regions: list[Region], dom=None, spec=None):
        usage = Usage()
        if not dom or not spec:
            return [], usage  # nothing measured: the pipeline falls back to pixel regions below
        pairs, missing, extra = self._align(spec, dom)
        findings: list[Finding] = []
        causes: list[list[int]] = []        # spec boxes of elements that changed on their own
        explained: list[list[int]] = []     # every box (design and build) accounted for
        groups: dict[tuple, list] = {}
        own: dict[int, list[str]] = {}       # element -> its own changed properties

        # 1. Property changes on matched elements.
        for s, d in pairs:
            text_s, text_d = (s.get("text") or "").strip(), (d.get("text") or "").strip()
            if text_s != text_d and _is_dynamic(text_s, text_d):
                explained += [s["bbox"], d["bbox"]]
                continue
            changed = [k for k in TYPO + SPACING + PAINT + ("radius",) if s.get(k) != d.get(k)]
            if text_s != text_d:
                changed.append("text")
            if not changed:
                continue
            causes.append(s["bbox"])
            own[id(s)] = changed
            explained += [s["bbox"], d["bbox"]]
            for cat, props in self._categorize(changed):
                sig = (cat, s.get("tag"), tuple((p, s.get(p), d.get(p)) for p in props))
                groups.setdefault(sig, []).append((s, d, props))

        for (cat, _tag, _), items in groups.items():
            findings.append(self._prop_finding(cat, items))

        # 2. Elements present on one side only.
        for s in missing:
            causes.append(s["bbox"])
            explained.append(s["bbox"])
            findings.append(Finding(
                title=f"Missing element: {_name(s)}", category="missing_element", severity="critical",
                element=_name(s), expected="present in the Figma frame", actual="not found in the page",
                bbox=list(s["bbox"]), confidence=0.85,
                rationale="Element exists in the Figma spec and has no match in the DOM (rules)."))
        for d in extra:
            causes.append(d["bbox"])
            explained.append(d["bbox"])
            findings.append(Finding(
                title=f"Extra element: {_name(d)}", category="extra_element", severity="major",
                element=_name(d), expected="not in the Figma frame", actual="present in the page",
                bbox=list(d["bbox"]), confidence=0.8,
                rationale="Element exists in the DOM and has no match in the Figma spec (rules)."))

        # 3. Movement and resizing without a property change: report root causes only.
        #    Movement is measured relative to the element's container, so children that simply
        #    travel with their card are never reported. A relative move is explained by a cause in
        #    an ancestor, or by a cause above it (or before it in the row) inside the same container.
        dom_of = {id(s): d for s, d in pairs}
        specs = [s for s, _ in pairs]

        def parent(s):
            boxes = [o for o in specs if o is not s and _contains(o["bbox"], s["bbox"])
                     and o["bbox"] != s["bbox"]]
            return min(boxes, key=lambda o: o["bbox"][2] * o["bbox"][3]) if boxes else None

        def in_scope(c, par):
            return par is None or _contains(par["bbox"], c)

        for s, d in pairs:
            sb, db = s["bbox"], d["bbox"]
            dx, dy = db[0] - sb[0], db[1] - sb[1]
            dw, dh = db[2] - sb[2], db[3] - sb[3]
            if max(abs(dx), abs(dy), abs(dw), abs(dh)) <= MOVE_TOL:
                continue
            explained += [sb, db]
            mine = own.get(id(s), [])
            if "margin" in mine:
                continue  # its own margin change already explains the move
            if mine and max(abs(dw), abs(dh)) > MOVE_TOL:
                continue  # its own style change resized it; a centered or wrapped element moves too
            par = parent(s)
            if par is not None:
                pd = dom_of[id(par)]["bbox"]
                dx, dy = dx - (pd[0] - par["bbox"][0]), dy - (pd[1] - par["bbox"][1])
            has_children = any(o is not s and _contains(sb, o["bbox"]) for o in specs)
            by_ancestor = any(c is not sb and _contains(c, sb) for c in causes)
            above = any(in_scope(c, par) and c[1] + c[3] <= sb[1] + MOVE_TOL
                        and c[0] < sb[0] + sb[2] and sb[0] < c[0] + c[2] for c in causes)
            same_row = any(in_scope(c, par) and c[1] < sb[1] + sb[3] and sb[1] < c[1] + c[3]
                           and c[0] + c[2] <= sb[0] + MOVE_TOL for c in causes)
            v_unexplained = abs(dy) > MOVE_TOL and not (by_ancestor or above)
            h_unexplained = abs(dx) > MOVE_TOL and not (by_ancestor or same_row)
            size_unexplained = max(abs(dw), abs(dh)) > MOVE_TOL and not has_children and not by_ancestor
            if h_unexplained:
                findings.append(Finding(
                    title=f"Horizontal alignment off: {_name(s)}", category="layout",
                    severity="major" if abs(dx) > 8 else "minor", element=_name(s),
                    expected=f"x = {sb[0]}px", actual=f"x = {db[0]}px ({dx:+d}px inside its container)",
                    bbox=_union([sb, db]), confidence=0.7,
                    rationale="Element moved sideways inside its container with no style change on it "
                              "or on anything before it in the row (rules)."))
                causes.append(sb)
            elif v_unexplained:
                findings.append(Finding(
                    title=f"Vertical spacing off above {_name(s)}", category="spacing",
                    severity="major" if abs(dy) > 4 else "minor", element=_name(s),
                    expected=f"y = {sb[1]}px", actual=f"y = {db[1]}px ({dy:+d}px inside its container)",
                    bbox=_union([sb, db]), confidence=0.6,
                    rationale="First element in its container to move with no measured cause; "
                              "likely a margin or gap on a wrapper (rules)."))
                causes.append(sb)
            elif size_unexplained:
                findings.append(Finding(
                    title=f"Size changed: {_name(s)}", category="layout", severity="minor", element=_name(s),
                    expected=f"{sb[2]}x{sb[3]}px", actual=f"{db[2]}x{db[3]}px", bbox=_union([sb, db]),
                    confidence=0.5, rationale="Leaf element resized with no style change; something inside "
                                              "or next to it may have been added (rules)."))
                causes.append(sb)

        # 4. Pixel regions nothing above explains -> low confidence, human review.
        for r in regions:
            if any(overlaps(r.box, b, pad=4) for b in explained + [f.bbox for f in findings]):
                continue
            findings.append(Finding(
                title=f"Unexplained visual change in region {r.id}", category="visual_diff",
                severity="major" if r.area > 2000 else "minor", element=f"region {r.id}",
                expected="(see design)", actual="(see implementation)", bbox=r.box, confidence=0.4,
                region_ids=[r.id], rationale=f"{r.area} changed pixels with no measured style difference "
                                             "(icon, image, border or pseudo element). Needs a human or an LLM."))
        return findings, usage

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _align(spec, dom):
        sm = SequenceMatcher(a=[_key(e) for e in spec], b=[_key(e) for e in dom], autojunk=False)
        pairs, missing, extra = [], [], []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
                pairs += list(zip(spec[i1:i2], dom[j1:j2]))
            else:
                missing += spec[i1:i2]
                extra += dom[j1:j2]
        return pairs, missing, extra

    @staticmethod
    def _categorize(changed):
        out = []
        if "text" in changed:
            out.append(("content", ["text"]))
        typo = [p for p in TYPO if p in changed]
        if typo:
            out.append(("typography", typo))
        sp = [p for p in SPACING if p in changed]
        if sp:
            out.append(("spacing", sp))
        paint = [p for p in PAINT if p in changed]
        if "radius" in changed or len(paint) >= 2:
            out.append(("component", paint + (["radius"] if "radius" in changed else [])))
        elif paint:
            out.append(("color", paint))
        return out

    @staticmethod
    def _prop_finding(cat, items):
        s, d, props = items[0]
        n = len(items)
        label = {"color": "text color", "bg": "background", "size": "font size", "weight": "font weight",
                 "font": "font family", "line_height": "line height", "text": "text", "radius": "corner radius"}
        expected = ", ".join(f"{label.get(p, p)} {s.get(p)}" for p in props)
        actual = ", ".join(f"{label.get(p, p)} {d.get(p)}" for p in props)
        element = _name(s) if n == 1 else f"{n} x {s.get('tag')} ({_name(s)}, ...)"
        cta = (s.get("cls") or "").startswith("btn-primary")
        sev = "critical" if cta and cat in ("color", "component", "content") else "major"
        if cat == "spacing":
            delta = max((abs((_px(s.get(p)) or 0) - (_px(d.get(p)) or 0)) for p in props), default=0)
            sev = "minor" if delta <= 4 else "major"
        what = {"content": "Text differs", "typography": "Typography differs", "spacing": "Spacing differs",
                "component": "Component style differs", "color": "Color differs"}[cat]
        return Finding(
            title=f"{what}: {element}"[:120], category=cat, severity=sev, element=element,
            expected=expected, actual=actual, bbox=_union([b for x in items for b in (x[0]["bbox"], x[1]["bbox"])]),
            confidence=0.9, rationale=("Measured: Figma spec vs computed CSS (rules)."
                                       + (f" Same change on {n} elements, likely one token or style." if n > 1 else "")))
