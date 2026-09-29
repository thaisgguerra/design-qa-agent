"""Free brand check: no AI, no API key. Everything here is measured, so it only covers what can be
measured reliably:

  * Cores       - official colors read from the manual text (hex or RGB) vs colors measured in the art
  * Logo        - the logo image is taken from the manual and searched in the art (edge template
                  matching, color independent), then its color and its distance to the edges are checked
  * Tipografia  - fonts embedded in the manual vs fonts embedded in the art (only when the art is a PDF)

Composition, graphic elements and tone of voice need judgment, so they are marked as "needs AI".
The result has the same shape as BrandChecker.check(), so the web page renders both the same way.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .brand import CATEGORIES, SEVERITIES, _overall, _rgb, delta_e, dominant_colors, palette_check
from .sources import Source

LOGO_MIN_SCORE = 0.40           # edge correlation to consider a place as a logo candidate
LOGO_MIN_SEPARATION = 0.5       # the candidate's shape must stand out from its background (see _separation)
MIN_SHARE_FINDING = 0.05        # off-palette colors smaller than 5% of the art are not reported

_HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
_RGB = re.compile(r"R\s*[:=]?\s*(\d{1,3})\s*[,;/\n ]+\s*G\s*[:=]?\s*(\d{1,3})\s*[,;/\n ]+\s*B\s*[:=]?\s*(\d{1,3})")
_CLEAR = [(re.compile(p, re.I), v) for p, v in [
    (r"um\s+ter[çc]o|1\s*/\s*3|one\s+third", 1 / 3), (r"metade|1\s*/\s*2|half", 1 / 2),
    (r"um\s+quarto|1\s*/\s*4|one\s+quarter", 1 / 4), (r"dobro|2x", 2.0)]]
_CLEAR_CTX = re.compile(r"clear\s*space|clearspace|espa[çc]o\s+livre|[áa]rea\s+(de\s+)?prote[çc][ãa]o|[áa]rea\s+livre", re.I)
_GENERIC_FONTS = {"arial", "helvetica", "times", "timesnewroman", "courier", "symbol", "zapfdingbats", "calibri"}


@dataclass
class BrandProfile:
    name: str
    palette: list[dict] = field(default_factory=list)
    palette_source: str = ""            # "manual" (codes written in it) | "estimada" (colors measured)
    fonts: list[str] = field(default_factory=list)
    logo: Image.Image | None = None
    clearspace: float | None = None     # fraction of the logo width
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- read the manual
def _font_family(name: str) -> str:
    name = name.split("+", 1)[-1]                     # subset prefix ABCDEF+Rubik-Bold
    name = re.split(r"[-,]", name)[0]
    name = re.sub(r"(MT|PS|Std|Pro)$", "", name)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()


def _pdf_fonts(doc) -> list[str]:
    """Font families by amount of text set in them. Type3 fonts (common in Figma exports) have no name."""
    count: Counter = Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    if not span["font"].startswith("Type3"):
                        count[_font_family(span["font"])] += len(span["text"].strip())
    total = sum(count.values()) or 1
    return [f for f, n in count.most_common(4) if f and n / total > 0.05]


_HEADERS = {"cores", "cor", "paleta", "paleta de cores", "cores da marca", "colors", "colours", "color", "palette"}


def _color_name(segment: str) -> str:
    """Name of a color: the first title-like line after the previous color's specs (codes, RGB, CMYK)."""
    for line in (l.strip() for l in segment.splitlines()):
        if (3 <= len(line) <= 30 and not re.search(r"\d|#|:|%", line)
                and line.lower() not in _HEADERS and not line.endswith((".", ","))):
            return line
    return ""


def _palette_from_text(text: str) -> list[dict]:
    matches = [("#" + m.group(1).upper(), m) for m in _HEX.finditer(text)]
    if not matches:
        matches = [(f"#{int(m[1]):02X}{int(m[2]):02X}{int(m[3]):02X}", m) for m in _RGB.finditer(text)
                   if max(int(v) for v in m.groups()) <= 255]
    found: dict[str, str] = {}
    prev_end = 0
    for hex_, m in matches:
        start = max(prev_end, text.rfind("\f", 0, m.start()) + 1, m.start() - 600)
        found.setdefault(hex_, _color_name(text[start:m.start()]))
        prev_end = m.end()
    return [{"name": n or h, "hex": h} for h, n in found.items()]


def _logo_from_pdf(doc) -> Image.Image | None:
    """The logo is usually the transparent image repeated across the manual's pages."""
    import pymupdf

    seen: Counter = Counter()
    info = {}
    for page in list(doc)[:12]:
        for img in page.get_images(full=True):
            xref, smask, w, h = img[0], img[1], img[2], img[3]
            if smask and w * h > 40_000:
                key = (w, h)
                seen[key] += 1
                info.setdefault(key, (xref, smask))
    if not seen:
        return None
    (w, h), _ = max(seen.items(), key=lambda kv: (kv[1], kv[0][0] * kv[0][1]))
    xref, smask = info[(w, h)]
    pix = pymupdf.Pixmap(pymupdf.Pixmap(doc, xref), pymupdf.Pixmap(doc, smask))
    img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    box = img.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    return img.crop(box) if box else None


def read_manual(src: Source) -> BrandProfile:
    prof = BrandProfile(name=re.sub(r"\.(pdf|png|jpe?g|webp)$", "", src.name, flags=re.I))
    if src.pdf:
        import pymupdf

        with pymupdf.open(stream=src.pdf, filetype="pdf") as doc:
            text = "\f".join(p.get_text() for p in doc)
            prof.palette = _palette_from_text(text)
            prof.fonts = _pdf_fonts(doc)
            prof.logo = _logo_from_pdf(doc)
        for m in _CLEAR_CTX.finditer(text):
            window = text[m.start(): m.start() + 500]
            hit = next((v for rx, v in _CLEAR if rx.search(window)), None)
            if hit:
                prof.clearspace = hit
                break
    if prof.palette:
        prof.palette_source = "manual"
    else:  # manual as image, or no codes written: estimate from the manual's own colors
        pages = src.as_images(max_pages=20, max_edge=800)
        prof.palette = [{"name": "Cor do manual", "hex": c["hex"]} for c in dominant_colors(pages, n=10)
                        if c["share"] > 0.02]
        prof.palette_source = "estimada"
        prof.notes.append("O manual não traz códigos de cor escritos; a paleta foi estimada pelas cores das páginas.")
    return prof


# --------------------------------------------------------------------------- find the logo
def _edges(img: np.ndarray):
    """Edges of every color channel, so a logo is found even when it has the same brightness as the
    background (e.g. green on pink)."""
    import cv2

    chans = [img] if img.ndim == 2 else [img[..., i] for i in range(img.shape[2])]
    e = np.max([cv2.Canny(np.ascontiguousarray(c), 60, 160) for c in chans], axis=0)
    return cv2.GaussianBlur(e.astype(np.float32), (5, 5), 0)


def find_logo(art: Image.Image, logo: Image.Image) -> dict | None:
    """Multi-scale template matching on edges, so the logo is found in any color."""
    import cv2

    work = art.convert("RGB")
    f = 1000 / max(work.size)  # same working size for every art: big ones shrink, small ones grow
    if f != 1:
        work = work.resize((round(work.width * f), round(work.height * f)), Image.LANCZOS)
    art_e = _edges(np.asarray(work))
    mask = np.asarray(logo.getchannel("A"))
    best = None
    W, H = work.size
    for frac in np.geomspace(0.06, 0.8, 26):
        tw = int(W * frac)
        th = int(tw * logo.height / logo.width)
        if tw < 24 or th < 16 or tw >= W or th >= H:
            continue
        tpl = _edges(cv2.resize(mask, (tw, th), interpolation=cv2.INTER_AREA))
        if tpl.std() < 1e-3:
            continue
        res = cv2.matchTemplate(art_e, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if best is None or score > best["score"]:
            best = {"score": float(score), "box": [x, y, tw, th]}
    if not best or best["score"] < LOGO_MIN_SCORE:
        return None
    x, y, w, h = (round(v / f) for v in best["box"])
    # verify on a fixed-size crop of the original: enough pixels for tiny logos, fast for big ones
    size = (240, max(20, round(240 * h / max(1, w))))
    crop = np.asarray(art.convert("RGB").crop((x, y, x + w, y + h)).resize(size, Image.LANCZOS), dtype=np.float32)
    inside, outside = _masks(logo, *size)
    sep = _separation(crop, inside, outside)
    if sep < LOGO_MIN_SEPARATION:  # edges lined up by chance (text, circles): not a logo
        return None
    r, g, b = (int(v) for v in np.median(crop[inside], axis=0))
    return {"score": round(best["score"], 2), "separation": round(sep, 2), "box": [x, y, w, h],
            "color": f"#{r:02X}{g:02X}{b:02X}"}


def _masks(logo: Image.Image, w: int, h: int):
    """Inside of the logo shape and its surroundings, away from anti-aliased borders."""
    import cv2

    m = (np.asarray(logo.getchannel("A").resize((w, h))) > 128).astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    return cv2.erode(m, k, iterations=2).astype(bool), ~cv2.dilate(m, k, iterations=3).astype(bool)


def _separation(crop: np.ndarray, inside: np.ndarray, outside: np.ndarray) -> float:
    """How much the logo shape stands out: |mean inside - mean outside| / (spread inside + outside),
    on the channel where it stands out most. A real logo is one color on a background (high);
    a chance match mixes colors (near 0)."""
    i, o = crop[inside], crop[outside]
    if len(i) < 20 or len(o) < 20:
        return 0.0
    return float(max(abs(i[:, c].mean() - o[:, c].mean()) / (i[:, c].std() + o[:, c].std() + 1)
                     for c in range(3)))


# --------------------------------------------------------------------------- the check
def _finding(title, category, severity, guideline, observed, suggestion, art_index=1, confidence=0.9):
    return dict(title=title, category=category, severity=severity, guideline=guideline, observed=observed,
                suggestion=suggestion, art_index=art_index, confidence=confidence)


class FreeBrandChecker:
    model = "gratuito"

    def check(self, art: Source, brand: Source, notes: str = "") -> dict:
        t0 = time.time()
        art_imgs = art.as_images(max_pages=6)
        if not art_imgs:
            raise ValueError("A arte não tem nenhuma página.")
        prof = read_manual(brand)
        cats = {k: {"applicable": False, "score": 0, "comment": ""} for k, _, _ in CATEGORIES}
        findings, review, strengths = [], [], []

        # ---- colors
        colors = dominant_colors(art_imgs)
        pal = palette_check(colors, prof.palette)
        if pal["adherence"] is not None:
            cats["cores"] = {"applicable": True, "score": pal["adherence"], "comment":
                             f"{pal['adherence']}% da área da arte usa cores da paleta"
                             + (" (paleta estimada)." if prof.palette_source == "estimada" else " oficial.")}
            off = [c for c in pal["art"] if not c["match"] and c["share"] >= MIN_SHARE_FINDING]
            if off:  # one finding for all of them: in photos every shade would otherwise be its own ticket
                total = sum(c["share"] for c in off)
                findings.append(_finding(
                    f"{len(off)} cor(es) fora da paleta ({total:.0%} da arte)", "cores",
                    "importante" if total >= 0.2 else "ajuste",
                    "Paleta oficial: " + ", ".join(f"{p['name']} {p['hex']}" for p in pal["brand"]) + ".",
                    "; ".join(f"{c['hex']} ({c['share']:.0%}, mais perto de {c['nearest']})" for c in off) + ".",
                    "Troque essas cores pela cor oficial mais próxima. Se forem sombras de foto ou render, "
                    "pode ignorar.",
                    confidence=0.9 if prof.palette_source == "manual" else 0.5))
            if pal["adherence"] >= 85:
                strengths.append("As cores da arte estão dentro da paleta da marca.")
            used: dict[str, float] = {}  # every official color the art uses, with its share of the area
            for c in pal["art"]:
                if c["match"]:
                    key = f"{c['nearest']} {c['nearest_hex']}"
                    used[key] = used.get(key, 0) + c["share"]
            strengths += [f"Usa a cor oficial {k} ({v:.0%} da arte)." for k, v in
                          sorted(used.items(), key=lambda kv: -kv[1])]

        # ---- logo
        if prof.logo is not None:
            hits = [(i, find_logo(img, prof.logo)) for i, img in enumerate(art_imgs, 1)]
            hits = [(i, h) for i, h in hits if h]
            if not hits:
                review.append(_finding(
                    "Não encontrei o logo na arte", "logo", "ajuste",
                    "O logo do manual foi procurado em todas as imagens da arte.",
                    "Nenhuma área parecida com o logo.",
                    "Se a peça deveria ter logo, confira se ele está lá e sem distorção. "
                    "Logos muito pequenos, inclinados ou em versão diferente podem não ser reconhecidos.",
                    confidence=0.4))
            else:
                score, comments, matched = 100, [], []
                n = len(hits)
                matched.append("Logo da marca presente na arte" + (f" ({n} imagens)." if n > 1 else "."))
                for i, h in hits:
                    img = art_imgs[i - 1]
                    x, y, w, hh = h["box"]
                    # clearspace against the edges of the piece
                    if prof.clearspace:
                        need = prof.clearspace * w
                        gap = min(x, y, img.width - (x + w), img.height - (y + hh))
                        if gap < need * 0.9:
                            score -= 30
                            findings.append(_finding(
                                "Logo sem a área de proteção", "logo", "critico",
                                f"O manual pede um respiro de {_frac(prof.clearspace)} da largura do logo em volta dele.",
                                f"O logo está a {max(0, gap)}px da borda; o mínimo seria {round(need)}px.",
                                "Afaste o logo da borda ou diminua o tamanho dele.", art_index=i))
                        else:
                            comments.append("respeita a área de proteção")
                            matched.append(f"Logo com a área de proteção de {_frac(prof.clearspace)} respeitada.")
                    # color of the logo
                    col = h["color"]
                    if col and prof.palette:
                        near = min(prof.palette, key=lambda p: delta_e(_rgb(col), _rgb(p["hex"])))
                        de = delta_e(_rgb(col), _rgb(near["hex"]))
                        if de > 15:
                            # photos and 3D renders shade the logo, so a medium difference is only "to review"
                            sure = de > 30
                            score -= 25 if sure else 0
                            (findings if sure else review).append(_finding(
                                "Logo numa cor fora da paleta", "logo", "importante" if sure else "ajuste",
                                "O logo deve usar uma das cores oficiais da marca.",
                                f"O logo aparece em {col}; a cor oficial mais próxima é {near['name']} {near['hex']}.",
                                f"Aplique o logo em {near['hex']} ou em outra versão prevista no manual. "
                                "Se a arte for foto ou render, a luz pode explicar a diferença.",
                                art_index=i, confidence=0.8 if sure else 0.45))
                        else:
                            comments.append(f"na cor {near['name']}")
                            matched.append(f"Logo na cor oficial {near['name']} {near['hex']}.")
                cats["logo"] = {"applicable": True, "score": max(0, score), "comment":
                                ("Logo encontrado" + (f" em {n} imagens" if n > 1 else "")
                                 + (f", {', '.join(dict.fromkeys(comments))}." if comments else "."))}
                strengths[:0] = list(dict.fromkeys(matched))  # logo first: it is what clients notice first

        # ---- typography (only PDFs carry font names)
        if prof.fonts and art.pdf:
            import pymupdf

            with pymupdf.open(stream=art.pdf, filetype="pdf") as doc:
                art_fonts = _pdf_fonts(doc)
            brand_keys = {f.lower().replace(" ", "") for f in prof.fonts}
            ok = [f for f in art_fonts if f.lower().replace(" ", "") in brand_keys]
            off = [f for f in art_fonts if f not in ok and f.lower().replace(" ", "") not in _GENERIC_FONTS]
            if art_fonts:
                score = round(100 * len(ok) / max(1, len(ok) + len(off)))
                cats["tipografia"] = {"applicable": True, "score": score,
                                      "comment": f"Fontes da arte: {', '.join(art_fonts)}."}
                for f in off:
                    findings.append(_finding(
                        f"Fonte fora da marca: {f}", "tipografia", "importante",
                        f"O manual usa {', '.join(prof.fonts)}.", f"A arte usa {f}.",
                        f"Troque {f} por {prof.fonts[0]}."))
                strengths += [f"Usa a fonte da marca {f}." for f in ok]
        if not cats["tipografia"]["applicable"]:
            cats["tipografia"]["comment"] = ("Só dá para conferir fontes quando a arte e o manual são PDFs "
                                             "com fontes identificáveis.")
        for k in ("composicao", "elementos", "linguagem"):
            cats[k]["comment"] = "Precisa de análise com IA."
        if cats["logo"]["comment"] == "":
            cats["logo"]["comment"] = ("Não encontrei o logo na arte." if prof.logo is not None
                                       else "Não consegui extrair o logo do manual.")

        categories = [{"key": k, "label": label, "weight": w, **cats[k]} for k, label, w in CATEGORIES]
        order = {s: i for i, s in enumerate(SEVERITIES)}
        findings.sort(key=lambda f: order[f["severity"]])
        score = _overall(categories)
        summary = _summary(score, findings, categories)
        return {
            "mode": "free",
            "brand_name": prof.name,
            "summary": summary + (" " + " ".join(prof.notes) if prof.notes else ""),
            "score": score,
            "categories": categories,
            "findings": findings,
            "to_review": review,
            "strengths": strengths[:8],
            "brand_fonts": prof.fonts,
            "palette": pal,
            "model": self.model,
            "cost_usd": 0.0,
            "seconds": round(time.time() - t0, 1),
        }


def _frac(v: float) -> str:
    return {1 / 3: "1/3", 1 / 2: "1/2", 1 / 4: "1/4", 2.0: "2x"}.get(v, f"{v:.2f}")


def _summary(score, findings, categories) -> str:
    if score is None:
        return "Não consegui medir nada nessa arte com o modo gratuito."
    measured = [c["label"].lower() for c in categories if c["applicable"]]
    crit = sum(f["severity"] == "critico" for f in findings)
    base = f"Medi {', '.join(measured)}. "
    if not findings:
        return base + "Nada fora do manual nesses critérios."
    return base + (f"{len(findings)} ponto(s) para ajustar" + (f", {crit} crítico(s)." if crit else "."))
