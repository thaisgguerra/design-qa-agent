"""Offline tests for the brand check: inputs, measured palette, scoring and guardrails (mocked client)."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from designqa.brand import BrandChecker, dominant_colors, palette_check  # noqa: E402
from designqa.sources import SourceError, _check_public, from_bytes  # noqa: E402


def png_bytes(color="#4BD398", accent="#FB7082"):
    img = Image.new("RGB", (400, 300), color)
    ImageDraw.Draw(img).rectangle([0, 0, 100, 300], fill=accent)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Verde primario #4BD398")
    return doc.tobytes()


class FakeClient:
    def __init__(self, payload):
        self.payload, self.calls, self.messages = payload, [], self

    def create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="tool_use", name="report_brand_check", input=self.payload)
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=5000, output_tokens=800))


PAYLOAD = {
    "brand_name": "Flori Tech", "summary": "Boa aderência.",
    "brand_palette": [{"name": "Verde primário", "hex": "#4BD398"}, {"name": "Rosa-Flori", "hex": "FB7082"},
                      {"name": "inválida", "hex": "verde"}],
    "brand_fonts": ["Rubik"],
    "categories": [
        {"key": "logo", "applicable": True, "score": 80, "comment": "ok"},
        {"key": "cores", "applicable": True, "score": 100, "comment": "ok"},
        {"key": "tipografia", "applicable": False, "score": 0, "comment": "sem texto"},
    ],
    "findings": [
        {"title": "Logo sem respiro", "category": "logo", "severity": "importante", "guideline": "X = 1/3",
         "observed": "encostado", "suggestion": "afastar", "art_index": 9, "confidence": 0.9},
        {"title": "Talvez a fonte", "category": "tipografia", "severity": "ajuste", "guideline": "Rubik",
         "observed": "?", "suggestion": "?", "art_index": 1, "confidence": 0.2},
    ],
    "strengths": ["Paleta correta"],
}


def test_from_bytes_detects_types():
    assert from_bytes(png_bytes(), "a.png").images
    src = from_bytes(pdf_bytes(), "manual.pdf")
    assert src.pdf and src.pdf_pages == 1 and len(src.as_images(3)) == 1
    with pytest.raises(SourceError):
        from_bytes(b"hello", "notes.txt")


def test_private_urls_are_blocked():
    for url in ("http://127.0.0.1/x.png", "http://localhost/x", "http://169.254.169.254/latest", "ftp://x.com/a"):
        with pytest.raises(SourceError):
            _check_public(url)


def test_palette_is_measured_not_guessed():
    colors = dominant_colors([Image.open(io.BytesIO(png_bytes()))])
    assert colors[0]["hex"] == "#4BD398" and abs(colors[0]["share"] - 0.75) < 0.02
    check = palette_check(colors, PAYLOAD["brand_palette"])
    assert [b["hex"] for b in check["brand"]] == ["#4BD398", "#FB7082"]   # invalid hex dropped
    assert check["adherence"] == 100 and all(c["match"] for c in check["art"])
    off = palette_check([{"hex": "#1E40AF", "share": 1.0}], PAYLOAD["brand_palette"])
    assert off["adherence"] == 0


def test_brand_check_contract_and_scoring():
    client = FakeClient(PAYLOAD)
    art = from_bytes(png_bytes(), "post.png")
    brand = from_bytes(pdf_bytes(), "manual.pdf")
    res = BrandChecker(model="claude-sonnet-5-5", client=client).check(art, brand, notes="post Instagram")

    kw = client.calls[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "report_brand_check"}
    content = kw["messages"][0]["content"]
    assert content[1]["type"] == "document" and content[1]["source"]["media_type"] == "application/pdf"
    assert any(b["type"] == "image" for b in content)
    assert "#4BD398" in content[-1]["text"] and "post Instagram" in content[-1]["text"]

    # overall = weighted mean of applicable categories only: (0.25*80 + 0.25*100) / 0.5
    assert res["score"] == 90
    assert len(res["categories"]) == 6 and not res["categories"][2]["applicable"]
    # guardrails: low confidence goes to review, art_index is clamped to the images we sent
    assert [f["title"] for f in res["findings"]] == ["Logo sem respiro"]
    assert res["findings"][0]["art_index"] == 1
    assert [f["title"] for f in res["to_review"]] == ["Talvez a fonte"]
    assert res["palette"]["adherence"] == 100 and res["cost_usd"] > 0


# --------------------------------------------------------------------------- free mode (no AI)
def manual_pdf(logo):
    """A tiny brand manual: color codes as text + the logo as a transparent image on two pages."""
    import pymupdf
    doc = pymupdf.open()
    buf = io.BytesIO()
    logo.save(buf, format="PNG")
    for text in ("Cores\nVerde primário\nUso geral\n#4BD398\nR: 75\nRosa-Flori\nBotões\n#FB7082",
                 "Espaço livre: X = um terço da largura do logotipo"):
        page = doc.new_page()
        page.insert_text((72, 72), text)
        page.insert_image(pymupdf.Rect(300, 300, 500, 460), stream=buf.getvalue())
    return doc.tobytes()


def make_logo():
    logo = Image.new("RGBA", (400, 320), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    d.ellipse([20, 20, 180, 180], outline="white", width=26)
    d.rectangle([230, 20, 262, 300], fill="white")
    d.polygon([(40, 300), (200, 220), (200, 300)], fill="white")
    return logo


def art_with_logo(logo, color, x, y, w, bg="#FB7082"):
    art = Image.new("RGB", (1000, 1000), bg)
    lg = logo.resize((w, round(w * logo.height / logo.width)))
    solid = Image.new("RGBA", lg.size, color)
    solid.putalpha(lg.getchannel("A"))
    art.paste(solid, (x, y), solid)
    return art


def test_free_mode_reads_manual():
    from designqa.brand_free import read_manual
    prof = read_manual(from_bytes(manual_pdf(make_logo()), "Manual.pdf"))
    assert [(p["name"], p["hex"]) for p in prof.palette] == [("Verde primário", "#4BD398"), ("Rosa-Flori", "#FB7082")]
    assert prof.logo is not None and abs(prof.clearspace - 1 / 3) < 1e-6


def test_free_mode_logo_and_clearspace():
    from designqa.brand_free import FreeBrandChecker
    from designqa.sources import Source
    logo = make_logo()
    brand = from_bytes(manual_pdf(logo), "Manual.pdf")
    good = FreeBrandChecker().check(Source("ok", "upload", images=[art_with_logo(logo, "#4BD398", 350, 350, 300)]), brand)
    assert good["categories"][0]["score"] == 100 and good["score"] >= 90 and not good["findings"]

    bad = FreeBrandChecker().check(Source("bad", "upload", images=[art_with_logo(logo, "#1E40AF", 8, 8, 300)]), brand)
    titles = [f["title"] for f in bad["findings"]]
    assert "Logo sem a área de proteção" in titles and "Logo numa cor fora da paleta" in titles
    assert bad["cost_usd"] == 0 and bad["mode"] == "free"

    none = FreeBrandChecker().check(Source("empty", "upload", images=[Image.new("RGB", (800, 800), "#F8F695")]), brand)
    assert not none["categories"][0]["applicable"] and none["to_review"]
