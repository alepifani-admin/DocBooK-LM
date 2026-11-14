"""Il PDF generato si apre davvero: pagine, testo, accenti, citazioni."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pypdfium2 as pdfium

from docbooklm import pdf


def text_of(data: bytes, tmp_path: Path, page: int = 0) -> str:
    path = tmp_path / "prova.pdf"
    path.write_bytes(data)
    document = pdfium.PdfDocument(str(path))
    try:
        return document[page].get_textpage().get_text_range()
    finally:
        document.close()


def pages_of(data: bytes, tmp_path: Path) -> int:
    path = tmp_path / "prova.pdf"
    path.write_bytes(data)
    document = pdfium.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


def test_title_and_italian_text_survive(tmp_path: Path) -> None:
    data = pdf.render("Risposta · Il mio quaderno", "La memoria è di sedici gigabyte.")
    assert data.startswith(b"%PDF")
    text = text_of(data, tmp_path)
    assert "Risposta · Il mio quaderno" in text
    assert "La memoria è di sedici gigabyte." in text


def test_markdown_becomes_readable_text(tmp_path: Path) -> None:
    markdown = """# Sintesi

Un paragrafo con **grassetto** e *corsivo* e `codice`.

## Punti

- primo punto
- secondo punto
  - dettaglio annidato
1. primo numerato

> una citazione
"""
    text = text_of(pdf.render("Titolo", markdown), tmp_path)
    assert "Sintesi" in text
    assert "Punti" in text
    # i marcatori non restano nel PDF
    assert "**" not in text and "`" not in text and "*corsivo*" not in text
    assert "grassetto" in text and "corsivo" in text
    assert "• primo punto" in text
    assert "dettaglio annidato" in text
    assert "1. primo numerato" in text
    assert "una citazione" in text


def test_long_documents_get_more_pages_and_page_numbers(tmp_path: Path) -> None:
    markdown = "\n\n".join(
        f"Articolo {index}. " + ("Testo che deve andare a capo. " * 12)
        for index in range(1, 90)
    )
    data = pdf.render("Contratto", markdown)
    total = pages_of(data, tmp_path)
    assert total > 1
    first = text_of(data, tmp_path, 0)
    last = text_of(data, tmp_path, total - 1)
    assert re.search(rf"\b1 / {total}\b", first)
    assert re.search(rf"\b{total} / {total}\b", last)


def test_characters_outside_the_font_do_not_break_the_file(tmp_path: Path) -> None:
    # emoji e frecce non esistono in cp1252: spariscono o diventano testo semplice
    text = text_of(pdf.render("Prova", "Freccia → e emoji 😀 e trattino — e puntini …"), tmp_path)
    assert "->" in text
    assert "—" in text
    assert "…" in text


def test_citations_are_listed_once(tmp_path: Path) -> None:
    citations = [
        {"source_title": "Bolla 1", "page": 2, "quote": "Sedici gigabyte."},
        {"source_title": "Bolla 1", "page": 2, "quote": "Sedici gigabyte."},
        {"source_title": "Bolla 2", "page": 1, "quote": "Altra frase."},
    ]
    text = text_of(pdf.render("Risposta", "Testo [1][2].", citations=citations), tmp_path)
    assert text.count("Fonti citate") == 1
    assert "Bolla 1, pagina 2" in text
    assert "Bolla 2, pagina 1" in text
    assert text.count("Sedici gigabyte.") == 1


def test_write_uses_a_downloadable_name_and_prunes_old_files(tmp_path: Path) -> None:
    directory = tmp_path / "exports"
    directory.mkdir()
    old = time.time() - pdf.MAX_AGE_S - 60
    for index in range(pdf.MAX_EXPORTS + 5):
        path = directory / f"vecchio-{index:03d}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        os.utime(path, (old, old))

    created = pdf.write(
        directory,
        title="Il mio quaderno",
        markdown="Testo",
    )
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*\.pdf", created.name)
    assert created.is_file()
    assert created.read_bytes().startswith(b"%PDF")
    assert len(list(directory.glob("*.pdf"))) <= pdf.MAX_EXPORTS


def test_malformed_markdown_is_still_a_pdf() -> None:
    # il modello a volte lascia un ** aperto o un blocco di codice senza fine:
    # l'esportazione non deve fallire proprio sul testo che serve
    data = pdf.render("Prova", "un **grassetto non chiuso e 2 * 3\n\n```\ncodice senza fine")
    assert data.startswith(b"%PDF")
    assert len(data) > 1000
