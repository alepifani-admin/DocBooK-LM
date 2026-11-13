"""Immagini e scansioni: OCR diretto sull'immagine."""

from __future__ import annotations

from pathlib import Path

from . import ocr


def extract(path: Path) -> list[tuple[int, str]]:
    from . import ExtractionError  # import locale: il pacchetto importa questo modulo

    if not ocr.available():
        raise ExtractionError("OCR non disponibile su questo sistema: serve macOS con Vision")
    return [(1, ocr.recognize(path))]
