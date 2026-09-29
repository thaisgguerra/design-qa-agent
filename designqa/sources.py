"""Inputs for the brand check: turn a link or an uploaded file into images or a PDF.

Supported links:
  * Figma          - a frame link (?node-id=...) or a file link (exports the top frames of page 1)
  * Google Drive   - file links, and Google Slides / Docs / Drawings (exported as PDF or PNG).
                     The file must be shared as "Anyone with the link can view".
  * Direct links   - any public URL that returns an image or a PDF

Everything is fetched server side, so URLs pointing to private networks are refused (SSRF guard).
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from PIL import Image

from .capture import FIGMA_API, parse_figma_url

MAX_BYTES = 30 * 1024 * 1024
MAX_ART_PAGES = 6
TIMEOUT = 60
UA = {"User-Agent": "Mozilla/5.0 (FloriBrandCheck)"}


class SourceError(Exception):
    """A problem the user can fix (bad link, sharing settings, unsupported file). Message is in PT-BR."""


@dataclass
class Source:
    name: str
    origin: str                                   # upload | figma | drive | url
    images: list[Image.Image] = field(default_factory=list)
    pdf: bytes | None = None
    pdf_pages: int = 0

    def as_images(self, max_pages: int, max_edge: int = 1568) -> list[Image.Image]:
        """Images for the model: PDFs are rasterized page by page."""
        if self.images:
            return [_fit(i, max_edge) for i in self.images[:max_pages]]
        return rasterize_pdf(self.pdf or b"", max_pages, max_edge)


# --------------------------------------------------------------------------- helpers
def _fit(img: Image.Image, max_edge: int) -> Image.Image:
    img = _flatten(img)
    if max(img.size) > max_edge:
        img = img.copy()
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return img


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def rasterize_pdf(data: bytes, max_pages: int, max_edge: int = 1568) -> list[Image.Image]:
    import pymupdf

    out = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in list(doc)[:max_pages]:
            zoom = max_edge / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


def from_bytes(data: bytes, name: str, origin: str = "upload") -> Source:
    if len(data) > MAX_BYTES:
        raise SourceError(f"O arquivo “{name}” passa de 30 MB. Exporte uma versão mais leve.")
    if data[:5] == b"%PDF-":
        import pymupdf

        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                pages = doc.page_count
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Não consegui abrir o PDF “{name}”.") from e
        return Source(name=name, origin=origin, pdf=data, pdf_pages=pages)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise SourceError(f"“{name}” não é uma imagem nem um PDF. Use PNG, JPG, WEBP ou PDF.") from e
    return Source(name=name, origin=origin, images=[img])


# --------------------------------------------------------------------------- safe download
def _check_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SourceError("O link precisa começar com http:// ou https://")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as e:
        raise SourceError(f"Não encontrei o endereço {p.hostname}. Confira o link.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SourceError("Esse link aponta para uma rede interna e não pode ser acessado.")


def _download(url: str, headers: dict | None = None) -> requests.Response:
    """GET with manual redirects so every hop passes the SSRF check."""
    for _ in range(6):
        _check_public(url)
        r = requests.get(url, headers={**UA, **(headers or {})}, timeout=TIMEOUT,
                         allow_redirects=False, stream=True)
        if r.is_redirect:
            url = urljoin(url, r.headers["Location"])
            continue
        body = r.raw.read(MAX_BYTES + 1, decode_content=True)
        if len(body) > MAX_BYTES:
            raise SourceError("O arquivo do link passa de 30 MB. Exporte uma versão mais leve.")
        r._content = body
        return r
    raise SourceError("O link redirecionou vezes demais.")


# --------------------------------------------------------------------------- Google Drive
_DRIVE_FILE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:.*&)?id=)([\w-]{10,})")
_DOCS = re.compile(r"docs\.google\.com/(presentation|document|drawings|spreadsheets)/d/([\w-]{10,})")


def _is_drive(url: str) -> bool:
    return "drive.google.com" in url or "docs.google.com" in url


def _fetch_drive(url: str) -> Source:
    if "/folders/" in url:
        raise SourceError("Esse link é de uma pasta do Drive. Abra o arquivo e copie o link dele.")
    m = _DOCS.search(url)
    if m:
        kind, fid = m.groups()
        fmt = "png" if kind == "drawings" else "pdf"
        dl = f"https://docs.google.com/{kind}/d/{fid}/export?format={fmt}"
    else:
        m = _DRIVE_FILE.search(url) or re.search(r"[?&]id=([\w-]{10,})", url)
        if not m:
            raise SourceError("Não reconheci esse link do Google Drive. Use o link do arquivo (Compartilhar > Copiar link).")
        dl = f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    r = _download(dl)
    ctype = r.headers.get("Content-Type", "")
    if r.status_code in (401, 403, 404) or "text/html" in ctype:
        raise SourceError("O Google Drive não liberou o arquivo. No Drive, clique em Compartilhar e mude "
                          "o acesso geral para “Qualquer pessoa com o link”.")
    r.raise_for_status()
    return from_bytes(r.content, _filename(r, "arquivo do Drive"), origin="drive")


def _filename(r: requests.Response, default: str) -> str:
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', r.headers.get("Content-Disposition", ""))
    return requests.utils.unquote(m.group(1)) if m else default


# --------------------------------------------------------------------------- Figma
def _fetch_figma(url: str, token: str) -> Source:
    if not token:
        raise SourceError("Links do Figma precisam de um token do Figma configurado no servidor (FIGMA_TOKEN). "
                          "Enquanto isso, exporte a arte em PNG/PDF e envie como arquivo.")
    m = re.search(r"figma\.com/(?:design|file|proto)/([A-Za-z0-9]+)", url)
    if not m:
        raise SourceError("Não reconheci esse link do Figma. Use Compartilhar > Copiar link.")
    key = m.group(1)
    hdr = {"X-Figma-Token": token}

    def api(path, params):
        r = requests.get(f"{FIGMA_API}{path}", headers=hdr, params=params, timeout=TIMEOUT)
        if r.status_code in (403, 404):
            raise SourceError("O Figma não deu acesso a esse arquivo. Confira se o token tem acesso ao arquivo.")
        r.raise_for_status()
        return r.json()

    if parse_qs(urlparse(url).query).get("node-id"):
        _, node = parse_figma_url(url)
        ids, names = [node], ["frame"]
    else:  # whole file: take the top-level frames of the first page
        doc = api(f"/files/{key}", {"depth": 2})["document"]
        frames = [n for n in doc["children"][0].get("children", [])
                  if n.get("type") in ("FRAME", "COMPONENT", "SECTION", "GROUP")][:MAX_ART_PAGES]
        if not frames:
            raise SourceError("Não encontrei frames na primeira página do arquivo. Copie o link de um frame específico.")
        ids, names = [f["id"] for f in frames], [f.get("name", "frame") for f in frames]
    data = api(f"/images/{key}", {"ids": ",".join(ids), "format": "png", "scale": 1})
    if data.get("err"):
        raise SourceError(f"O Figma não conseguiu exportar: {data['err']}")
    images = []
    for i in ids:
        img_url = (data.get("images") or {}).get(i)
        if img_url:
            images.append(Image.open(io.BytesIO(_download(img_url).content)))
    if not images:
        raise SourceError("O Figma não retornou nenhuma imagem para esse link.")
    return Source(name=names[0] if len(names) == 1 else f"{len(images)} frames do Figma",
                  origin="figma", images=images)


# --------------------------------------------------------------------------- entry point
def fetch_url(url: str, figma_token: str = "") -> Source:
    url = url.strip()
    if not url:
        raise SourceError("Cole um link.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "figma.com/" in url:
        return _fetch_figma(url, figma_token)
    if _is_drive(url):
        return _fetch_drive(url)
    r = _download(url)
    if r.status_code >= 400:
        raise SourceError(f"O link respondeu com erro {r.status_code}. Ele está público?")
    if "text/html" in r.headers.get("Content-Type", ""):
        raise SourceError("Esse link abre uma página, não um arquivo. Use um link direto para a imagem ou PDF, "
                          "ou envie o arquivo.")
    return from_bytes(r.content, _filename(r, urlparse(url).path.rsplit("/", 1)[-1] or "arquivo"), origin="url")
