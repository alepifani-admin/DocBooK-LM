"""Estrazione del testo per tipo di fonte.

Ogni estrattore restituisce una lista di coppie (numero di pagina, testo); per i
formati senza pagine la pagina e' sempre 1.
"""

from __future__ import annotations

from pathlib import Path

from . import docx as docx_ext
from . import image as image_ext
from . import pdf as pdf_ext
from . import text as text_ext
from . import web as web_ext

TEXT_SUFFIXES = {
    ".md", ".txt", ".rst", ".html", ".htm", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".tex", ".rtf", ".py", ".csv", ".json", ".log", ".sql", ".sh",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


class ExtractionError(RuntimeError):
    """Il file non e' leggibile come fonte."""


def kind_for(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "binary"


def extract_file(path: Path, *, ocr_enabled: bool = True) -> tuple[str, list[tuple[int, str]]]:
    """Restituisce (tipo, pagine). Solleva ExtractionError se non c'e' testo."""
    kind = kind_for(path.name)
    if kind == "pdf":
        pages = pdf_ext.extract(path, ocr_enabled=ocr_enabled)
    elif kind == "docx":
        pages = docx_ext.extract(path)
    elif kind == "image":
        if not ocr_enabled:
            raise ExtractionError("OCR disattivato: impossibile leggere un'immagine")
        pages = image_ext.extract(path)
    elif kind == "text":
        pages = text_ext.extract(path)
    else:
        raise ExtractionError(f"formato non supportato: {path.suffix or 'senza estensione'}")

    if not any(page_text.strip() for _, page_text in pages):
        raise ExtractionError("nessun testo estraibile dal file")
    return kind, pages


__all__ = ["ExtractionError", "extract_file", "kind_for", "pdf_ext", "web_ext"]
