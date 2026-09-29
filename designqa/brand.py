"""Brand check: how well does a piece of art follow a client's brand manual?

Same philosophy as the screen QA agent:
  * Perceive  - measure what can be measured (dominant colors of the art)
  * Reason    - Claude reads the manual (PDF) and the art, scores each brand dimension and lists
                concrete deviations through a forced tool call
  * Verify    - the palette the model read from the manual is checked against the measured colors,
                the overall score is computed here (not by the model) from weighted categories,
                and low-confidence findings go to a "to review" list instead of the main report
"""
from __future__ import annotations

import base64
import io
import re
import time

from PIL import Image

from . import config
from .analyze import Usage
from .sources import Source, rasterize_pdf

# key, label, weight. The weights are a product decision: logo and color are what clients notice first.
CATEGORIES = [
    ("logo", "Logo", 0.25),
    ("cores", "Cores", 0.25),
    ("tipografia", "Tipografia", 0.20),
    ("composicao", "Composição e respiro", 0.15),
    ("elementos", "Elementos gráficos", 0.10),
    ("linguagem", "Tom de voz", 0.05),
]
SEVERITIES = ["critico", "importante", "ajuste"]
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_BRAND_IMAGES = 40
MATCH_DELTA_E = 12.0

SYSTEM = """Você é uma diretora de arte sênior fazendo o controle de qualidade de marca de uma agência. \
Você recebe o MANUAL DE MARCA de um cliente e uma ARTE produzida pela equipe, e avalia o quanto a arte \
segue o manual.

Como avaliar:
- Use apenas o que o manual define. Se o manual não fala de um tema (ex.: não define tipografia), marque a \
categoria como não aplicável (applicable=false) em vez de inventar regras.
- Se a arte não tem o elemento (ex.: não usa logo), a categoria também é não aplicável, a menos que o manual \
exija o elemento nesse tipo de peça.
- Notas de 0 a 100 por categoria: 90-100 segue o manual; 70-89 pequenos ajustes; 50-69 desvios visíveis; \
abaixo de 50 fora da marca.
- Seja concreta e cite o manual: "O manual pede Verde primário #4BD398 no logo sobre fundo claro; a arte usa \
#2EB872" é melhor que "a cor parece diferente".
- Cores medidas na arte são fornecidas em JSON. Use esses valores em vez de estimar pelos pixels.
- Em brand_palette, liste as cores oficiais do manual com o hex exato escrito nele.
- Severidade: critico = distorce ou desrespeita o logo, cor principal errada, fonte fora da marca em destaque; \
importante = visível para o cliente; ajuste = acabamento.
- Confidence: probabilidade (0-1) de uma designer sênior concordar que é um desvio real.
- Em strengths, diga o que a arte faz bem segundo o manual (máximo 4 itens).
- Escreva tudo em português do Brasil, com linguagem direta e gentil, como feedback para uma colega."""

TOOL = {
    "name": "report_brand_check",
    "description": "Reporta a aderência da arte ao manual de marca.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_name": {"type": "string"},
            "summary": {"type": "string", "description": "Veredito em 1 ou 2 frases"},
            "brand_palette": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"name": {"type": "string"}, "hex": {"type": "string"}},
                          "required": ["name", "hex"]},
            },
            "brand_fonts": {"type": "array", "items": {"type": "string"}},
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": [c[0] for c in CATEGORIES]},
                        "applicable": {"type": "boolean"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "comment": {"type": "string", "description": "Uma frase explicando a nota"},
                    },
                    "required": ["key", "applicable", "score", "comment"],
                },
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Título curto, até 80 caracteres"},
                        "category": {"type": "string", "enum": [c[0] for c in CATEGORIES]},
                        "severity": {"type": "string", "enum": SEVERITIES},
                        "guideline": {"type": "string", "description": "O que o manual diz (com página, se souber)"},
                        "observed": {"type": "string", "description": "O que a arte faz"},
                        "suggestion": {"type": "string", "description": "Como ajustar"},
                        "art_index": {"type": "integer", "description": "Número da imagem da arte (1, 2...)"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["title", "category", "severity", "guideline", "observed",
                                 "suggestion", "art_index", "confidence"],
                },
            },
            "strengths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["brand_name", "summary", "brand_palette", "brand_fonts", "categories",
                     "findings", "strengths"],
    },
}


# --------------------------------------------------------------------------- perceive: colors
def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def dominant_colors(images: list[Image.Image], n: int = 8) -> list[dict]:
    """Most common colors across the art, with their share of the area (0-1)."""
    counts: dict[tuple, int] = {}
    for img in images:
        small = img.convert("RGB")
        small.thumbnail((240, 240))
        q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()
        for count, idx in q.getcolors() or []:
            rgb = tuple(pal[idx * 3: idx * 3 + 3])
            counts[rgb] = counts.get(rgb, 0) + count
    merged: list[list] = []  # merge near-identical colors coming from different images
    for rgb, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        for m in merged:
            if delta_e(rgb, m[0]) < 6:
                m[1] += c
                break
        else:
            merged.append([rgb, c])
    total = sum(c for _, c in merged) or 1
    # colors under 1% are edge anti-aliasing, not design decisions
    return [{"hex": _hex(rgb), "share": round(c / total, 3)} for rgb, c in merged[:n] if c / total >= 0.01]


def _lab(rgb) -> tuple[float, float, float]:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(v)) for v in rgb[:3])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a, b) -> float:
    la, lb = _lab(a), _lab(b)
    return sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5


def _rgb(hex_: str):
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette_check(art_colors: list[dict], brand_palette: list[dict]) -> dict:
    """Match each measured art color to the nearest official color. Deterministic, no LLM."""
    valid = [dict(name=p.get("name", ""), hex=p["hex"].upper()) for p in brand_palette
             if re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(p.get("hex", "")).strip())]
    for p in valid:
        p["hex"] = "#" + p["hex"].lstrip("#")
    if not valid:
        return {"brand": [], "art": art_colors, "adherence": None}
    art, matched = [], 0.0
    for c in art_colors:
        near = min(valid, key=lambda p: delta_e(_rgb(c["hex"]), _rgb(p["hex"])))
        de = delta_e(_rgb(c["hex"]), _rgb(near["hex"]))
        ok = de <= MATCH_DELTA_E
        matched += c["share"] if ok else 0
        art.append({**c, "nearest": near["name"], "nearest_hex": near["hex"],
                    "delta_e": round(de, 1), "match": ok})
    return {"brand": valid, "art": art, "adherence": round(100 * matched)}


# --------------------------------------------------------------------------- reason
def _img_block(img: Image.Image, fmt: str = "PNG") -> dict:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"quality": 85} if fmt == "JPEG" else {"optimize": True}))
    media = "image/jpeg" if fmt == "JPEG" else "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def _brand_blocks(brand: Source) -> list[dict]:
    """The manual goes in as a native PDF when it fits the API limits, else as page images."""
    if brand.pdf and len(brand.pdf) <= MAX_PDF_BYTES and brand.pdf_pages <= MAX_PDF_PAGES:
        return [{"type": "document", "title": brand.name,
                 "source": {"type": "base64", "media_type": "application/pdf",
                            "data": base64.b64encode(brand.pdf).decode()},
                 "cache_control": {"type": "ephemeral"}}]  # same manual is reused across many arts
    pages = (rasterize_pdf(brand.pdf, MAX_BRAND_IMAGES, 1100) if brand.pdf
             else brand.as_images(MAX_BRAND_IMAGES, 1400))
    return [_img_block(p, "JPEG") for p in pages]


def _overall(categories: list[dict]) -> int | None:
    weights = {k: w for k, _, w in CATEGORIES}
    used = [c for c in categories if c["applicable"]]
    total = sum(weights[c["key"]] for c in used)
    if not total:
        return None
    return round(sum(weights[c["key"]] * c["score"] for c in used) / total)


class BrandChecker:
    def __init__(self, model: str | None = None, client=None):
        self.model = model or config.MODEL
        if client is None:
            import anthropic
            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError("Configure a ANTHROPIC_API_KEY no arquivo .env do servidor.")
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.client = client

    def check(self, art: Source, brand: Source, notes: str = "") -> dict:
        art_imgs = art.as_images(max_pages=6)
        if not art_imgs:
            raise ValueError("A arte não tem nenhuma página.")
        colors = dominant_colors(art_imgs)

        content: list[dict] = [{"type": "text", "text": "MANUAL DE MARCA DO CLIENTE:"}]
        content += _brand_blocks(brand)
        for i, img in enumerate(art_imgs, 1):
            content += [{"type": "text", "text": f"ARTE — imagem {i} de {len(art_imgs)}:"}, _img_block(img)]
        content.append({"type": "text", "text": (
            "Cores medidas na arte (hex e fração da área): "
            + ", ".join(f"{c['hex']} {c['share']:.0%}" for c in colors) + "\n"
            + (f"Contexto da peça: {notes}\n" if notes.strip() else "")
            + "Avalie a arte contra o manual e responda com report_brand_check. "
              "Inclua todas as 6 categorias.")})

        usage = Usage()
        t0 = time.time()
        resp = self.client.messages.create(
            model=self.model, max_tokens=8000, system=SYSTEM, tools=[TOOL],
            tool_choice={"type": "tool", "name": "report_brand_check"},
            messages=[{"role": "user", "content": content}])
        usage.seconds = time.time() - t0
        usage.calls = 1
        usage.input_tokens = resp.usage.input_tokens
        usage.output_tokens = resp.usage.output_tokens
        raw = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        if not raw:
            raise RuntimeError("O modelo não retornou uma avaliação. Tente de novo.")
        return self._build(raw, colors, usage, len(art_imgs))

    def _build(self, raw: dict, colors: list[dict], usage: Usage, n_art: int) -> dict:
        by_key = {c.get("key"): c for c in raw.get("categories", [])}
        categories = []
        for key, label, weight in CATEGORIES:
            c = by_key.get(key) or {"applicable": False, "score": 0, "comment": "Não avaliado."}
            categories.append({"key": key, "label": label, "weight": weight,
                               "applicable": bool(c.get("applicable")),
                               "score": max(0, min(100, int(c.get("score", 0)))),
                               "comment": c.get("comment", "")})

        # Guardrail: low-confidence findings are shown as "to review", never as confirmed issues.
        order = {s: i for i, s in enumerate(SEVERITIES)}
        findings, review = [], []
        for f in raw.get("findings", []):
            f = {**f, "confidence": float(f.get("confidence", 0.5)),
                 "art_index": max(1, min(n_art, int(f.get("art_index", 1) or 1)))}
            (findings if f["confidence"] >= config.MIN_CONFIDENCE else review).append(f)
        findings.sort(key=lambda f: (order.get(f.get("severity"), 9), -f["confidence"]))

        return {
            "brand_name": raw.get("brand_name", ""),
            "summary": raw.get("summary", ""),
            "score": _overall(categories),
            "categories": categories,
            "findings": findings,
            "to_review": review,
            "strengths": raw.get("strengths", [])[:4],
            "brand_fonts": raw.get("brand_fonts", []),
            "palette": palette_check(colors, raw.get("brand_palette", [])),
            "model": self.model,
            "cost_usd": round(usage.cost(self.model), 4),
            "seconds": round(usage.seconds, 1),
        }
