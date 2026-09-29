"""Flori Brand Check: web interface for the brand check agent.

Run locally:
    uvicorn web.app:app --reload
and open http://localhost:8000
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from designqa import config  # noqa: E402
from designqa.brand import BrandChecker  # noqa: E402
from designqa.sources import MAX_BYTES, Source, SourceError, fetch_url, from_bytes  # noqa: E402

app = FastAPI(title="Flori Brand Check")


def _load(url: str, upload: UploadFile | None, what: str) -> Source:
    if upload is not None and upload.filename:
        data = upload.file.read(MAX_BYTES + 1)
        return from_bytes(data, upload.filename)
    if url.strip():
        return fetch_url(url, config.FIGMA_TOKEN)
    raise SourceError(f"Envie {what}: cole um link ou escolha um arquivo.")


def _preview(src: Source, limit: int = 6) -> list[str]:
    out = []
    for img in src.as_images(max_pages=limit, max_edge=720):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


@app.get("/api/config")
def get_config():
    return {"ready": bool(config.ANTHROPIC_API_KEY), "figma": bool(config.FIGMA_TOKEN), "model": config.MODEL}


@app.post("/api/analyze")
def analyze(art_url: str = Form(""), brand_url: str = Form(""), notes: str = Form(""),
            art_file: UploadFile | None = File(None), brand_file: UploadFile | None = File(None)):
    # sync def: FastAPI runs it in a worker thread, so slow downloads and the model call don't block
    try:
        for url, upload, what in ((art_url, art_file, "a arte"), (brand_url, brand_file, "o manual de marca")):
            if not url.strip() and not (upload and upload.filename):
                raise SourceError(f"Envie {what}: cole um link ou escolha um arquivo.")
        art = _load(art_url, art_file, "a arte")
        brand = _load(brand_url, brand_file, "o manual de marca")
        result = BrandChecker().check(art, brand, notes=notes[:1000])
    except SourceError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "credit balance" in msg or "authentication" in msg.lower():
            msg = "A chave da API do Claude foi recusada. Confira a ANTHROPIC_API_KEY e os créditos da conta."
        return JSONResponse({"error": f"Algo deu errado na análise. {msg}"}, status_code=500)
    result["art"] = {"name": art.name, "origin": art.origin, "previews": _preview(art)}
    result["brand"] = {"name": brand.name, "origin": brand.origin}
    return result


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
