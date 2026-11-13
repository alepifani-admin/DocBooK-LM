"""Estrazione del testo per tipo di fonte.

Ogni estrattore restituisce una lista di coppie (numero di pagina, testo); per i
formati senza pagine la pagina e' sempre 1.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from . import archive as archive_ext
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
ARCHIVE_SUFFIXES = {".zip"}


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
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    return "binary"


def _docx_or_zip(data: bytes) -> str:
    """Un .docx e' uno zip: si guarda dentro per distinguerlo da un archivio."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as probe:
            names = set(probe.namelist())
    except (zipfile.BadZipFile, OSError):
        return ".zip"
    return ".docx" if "word/document.xml" in names else ".zip"


def suffix_for(name: str, data: bytes) -> str:
    """Estensione del file: quella del nome, o dedotta dai primi byte.

    Serve ai file che arrivano senza estensione (download, archivi aperti a
    mano): il contenuto dice piu' del nome.
    """
    suffix = Path(name).suffix.lower()
    if kind_for(name) != "binary":
        return suffix
    if data[:5] == b"%PDF-":
        return ".pdf"
    if archive_ext.looks_like_zip(data):
        return _docx_or_zip(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:9] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:5] == b"{\\rtf":
        return ".rtf"
    return ""


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
    elif kind == "archive":
        return archive_ext.extract(path, ocr_enabled=ocr_enabled)
    else:
        raise ExtractionError(f"formato non supportato: {path.suffix or 'senza estensione'}")

    if not any(page_text.strip() for _, page_text in pages):
        raise ExtractionError("nessun testo estraibile dal file")
    return kind, pages


__all__ = [
    "ExtractionError",
    "extract_file",
    "kind_for",
    "pdf_ext",
    "suffix_for",
    "web_ext",
]
