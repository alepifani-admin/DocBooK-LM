"""PDF: testo per pagina con pdfium, OCR di ripiego per le pagine scansionate.

pdfium e' lo stesso motore che usa Chrome: estrae il testo nell'ordine di
lettura e, per le pagine immagine, permette di rasterizzare a 200 DPI per l'OCR.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pypdfium2 as pdfium

from . import ocr

logger = logging.getLogger("docbooklm")

RENDER_DPI = 200
MIN_TEXT_CHARS = 40


def _page_text(page: pdfium.PdfPage) -> str:
    textpage = page.get_textpage()
    try:
        return str(textpage.get_text_range())
    finally:
        textpage.close()


def _render_png(page: pdfium.PdfPage, path: Path) -> Path:
    bitmap = page.render(scale=RENDER_DPI / 72)
    image = bitmap.to_pil()
    image.save(path, format="PNG")
    return path


def extract(path: Path, *, ocr_enabled: bool = True) -> list[tuple[int, str]]:
    document = pdfium.PdfDocument(str(path))
    pages: list[tuple[int, str]] = []
    tmp_dir = path.parent
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                text = _page_text(page)
                if len(text.strip()) < MIN_TEXT_CHARS and ocr_enabled and ocr.available():
                    target = tmp_dir / f".ocr-{path.stem}-{index + 1}.png"
                    try:
                        _render_png(page, target)
                        text = ocr.recognize(target)
                    finally:
                        target.unlink(missing_ok=True)
                pages.append((index + 1, text))
            finally:
                page.close()
    finally:
        document.close()
    return pages


def page_image(path: Path, page_number: int, *, dpi: int = 150) -> bytes:
    """PNG della pagina 1-based, usato dal visualizzatore delle citazioni."""
    document = pdfium.PdfDocument(str(path))
    try:
        index = max(0, min(page_number - 1, len(document) - 1))
        page = document[index]
        try:
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_pil()
            buffer = _png_bytes(image)
            return buffer
        finally:
            page.close()
    finally:
        document.close()


def _png_bytes(image: object) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")  # type: ignore[attr-defined]
    return buffer.getvalue()


def page_count(path: Path) -> int:
    document = pdfium.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()
