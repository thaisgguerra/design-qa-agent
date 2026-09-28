"""Inputs: export the design from Figma and capture the implementation from a URL.

Two sources of "measured truth" make the agent more reliable than vision alone:
  * Figma spec  -> exact fonts, sizes, colors and auto-layout spacing from the design file
  * DOM styles  -> exact computed CSS values from the implemented page
The LLM compares images, but it is told to prefer these measured values over
estimating from pixels. That is the main hallucination guardrail.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

FIGMA_API = "https://api.figma.com/v1"


# --------------------------------------------------------------------------- Figma
def parse_figma_url(url: str) -> tuple[str, str]:
    """Return (file_key, node_id) from a Figma frame link."""
    m = re.search(r"figma\.com/(?:design|file|proto)/([A-Za-z0-9]+)", url)
    if not m:
        raise ValueError(f"Not a Figma design URL: {url}")
    file_key = m.group(1)
    node = parse_qs(urlparse(url).query).get("node-id", [None])[0]
    if not node:
        raise ValueError("The Figma link must point to a frame (it needs ?node-id=...). "
                         "In Figma: select the frame > right click > Copy link to selection.")
    return file_key, node.replace("-", ":")


def _figma_get(path: str, token: str, params: dict) -> dict:
    r = requests.get(f"{FIGMA_API}{path}", headers={"X-Figma-Token": token}, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def export_figma_frame(url: str, token: str, out_path: Path, scale: float = 1.0) -> Path:
    file_key, node_id = parse_figma_url(url)
    data = _figma_get(f"/images/{file_key}", token, {"ids": node_id, "format": "png", "scale": scale})
    if data.get("err"):
        raise RuntimeError(f"Figma export error: {data['err']}")
    img_url = data["images"].get(node_id)
    if not img_url:
        raise RuntimeError("Figma returned no image for this node.")
    out_path.write_bytes(requests.get(img_url, timeout=120).content)
    return out_path


def _rgba_to_hex(c: dict, opacity: float = 1.0) -> str:
    r, g, b = (round(c[k] * 255) for k in ("r", "g", "b"))
    a = c.get("a", 1.0) * opacity
    return f"#{r:02X}{g:02X}{b:02X}" + ("" if a >= 0.999 else f" (alpha {a:.2f})")


def _solid_fill(node: dict) -> str | None:
    for f in node.get("fills", []) or []:
        if f.get("type") == "SOLID" and f.get("visible", True):
            return _rgba_to_hex(f["color"], f.get("opacity", 1.0))
    return None


def fetch_figma_spec(url: str, token: str, scale: float = 1.0, limit: int = 200) -> list[dict]:
    """Flatten the frame into a compact spec: text styles and auto-layout spacing."""
    file_key, node_id = parse_figma_url(url)
    data = _figma_get(f"/files/{file_key}/nodes", token, {"ids": node_id})
    root = data["nodes"][node_id]["document"]
    origin = root.get("absoluteBoundingBox") or {"x": 0, "y": 0}
    items: list[dict] = []

    def bbox(n):
        b = n.get("absoluteBoundingBox")
        if not b:
            return None
        return [round((b["x"] - origin["x"]) * scale), round((b["y"] - origin["y"]) * scale),
                round(b["width"] * scale), round(b["height"] * scale)]

    def walk(n):
        if len(items) >= limit or n.get("visible", True) is False:
            return
        t = n.get("type")
        if t == "TEXT":
            s = n.get("style", {})
            items.append({
                "kind": "text", "name": n.get("name"), "text": (n.get("characters") or "")[:80],
                "font": s.get("fontFamily"), "size": s.get("fontSize"), "weight": s.get("fontWeight"),
                "line_height": s.get("lineHeightPx"), "letter_spacing": s.get("letterSpacing"),
                "color": _solid_fill(n), "bbox": bbox(n),
            })
        elif t in ("FRAME", "INSTANCE", "COMPONENT", "RECTANGLE"):
            entry = {"kind": "instance" if t == "INSTANCE" else "box", "name": n.get("name"),
                     "fill": _solid_fill(n), "radius": n.get("cornerRadius"), "bbox": bbox(n)}
            if n.get("layoutMode") and n.get("layoutMode") != "NONE":
                entry.update({
                    "layout": n["layoutMode"].lower(), "gap": n.get("itemSpacing"),
                    "padding": [n.get("paddingTop", 0), n.get("paddingRight", 0),
                                n.get("paddingBottom", 0), n.get("paddingLeft", 0)],
                })
            if entry["fill"] or entry.get("layout") or t == "INSTANCE":
                items.append({k: v for k, v in entry.items() if v is not None})
        for child in n.get("children", []) or []:
            walk(child)

    walk(root)
    return items


# --------------------------------------------------------------------------- Browser
DOM_JS = r"""
(limit) => {
  const hex = (c) => {
    const m = c && c.match(/rgba?\(([^)]+)\)/);
    if (!m) return c;
    const p = m[1].split(',').map(s => parseFloat(s));
    if (p.length === 4 && p[3] === 0) return 'transparent';
    const h = '#' + p.slice(0,3).map(v => Math.round(v).toString(16).padStart(2,'0')).join('').toUpperCase();
    return p.length === 4 && p[3] < 1 ? `${h} (alpha ${p[3]})` : h;
  };
  const out = [];
  const sel = 'h1,h2,h3,h4,h5,h6,p,span,a,button,label,input,select,textarea,img,svg,li,nav,header,footer,section,[role=button],[class*=card],[class*=btn]';
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= limit) break;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
    const ownText = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      cls: (el.className && typeof el.className === 'string') ? el.className.split(/\s+/).slice(0,3).join('.') : undefined,
      text: ownText.slice(0, 80) || undefined,
      font: cs.fontFamily.split(',')[0].replace(/["']/g,''),
      size: parseFloat(cs.fontSize), weight: +cs.fontWeight || cs.fontWeight,
      line_height: cs.lineHeight, color: hex(cs.color), bg: hex(cs.backgroundColor),
      radius: cs.borderRadius, padding: cs.padding, margin: cs.margin, gap: cs.gap,
      bbox: [Math.round(r.left + scrollX), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)],
    });
  }
  return out;
}
"""


def capture_url(url: str, out_path: Path, width: int, height: int = 900, full_page: bool = True,
                wait_ms: int = 800, mask_selectors: list[str] | None = None,
                dom_limit: int = 250) -> list[dict]:
    """Screenshot a page at the design's width and return computed styles of visible elements.

    mask_selectors: elements with dynamic content (dates, avatars, ads) that should be
    hidden so they don't create false positives.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(url, wait_until="networkidle")
        page.add_style_tag(content="*{animation:none!important;transition:none!important;caret-color:transparent!important}")
        for s in mask_selectors or []:
            page.add_style_tag(content=f"{s}{{visibility:hidden!important}}")
        page.wait_for_timeout(wait_ms)
        dom = page.evaluate(DOM_JS, dom_limit)
        page.screenshot(path=str(out_path), full_page=full_page)
        browser.close()
    return dom
