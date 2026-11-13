"""Immagini e scansioni: OCR diretto sull'immagine."""

from __future__ import annotations

from pathlib import Path

from . import ocr


def extract(path: Path) -> list[tuple[int, str]]:
    return [(1, ocr.recognize(path))]
