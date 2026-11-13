"""Archivi ZIP e file senza estensione."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from docbooklm import ingest
from docbooklm.extract import ExtractionError, extract_file, suffix_for

from .pdf_fixture import build_pdf


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_suffix_from_content_when_the_name_has_none() -> None:
    assert suffix_for("POSTE NOVEMBRE", b"%PDF-1.7\nresto") == ".pdf"
    assert suffix_for("bolle", _zip({"a.txt": b"ciao"})) == ".zip"
    assert suffix_for("lettera", _zip({"word/document.xml": b"<document/>"})) == ".docx"
    assert suffix_for("foto", b"\x89PNG\r\n\x1a\nresto") == ".png"
    assert suffix_for("mistero", b"\x00\x01\x02\x03") == ""


def test_name_wins_when_it_is_already_known() -> None:
    assert suffix_for("nota.md", b"%PDF-1.7") == ".md"


def test_archive_pages_follow_the_document_order(tmp_path: Path) -> None:
    path = tmp_path / "lotto.zip"
    path.write_bytes(
        _zip(
            {
                "b-secondo.txt": b"testo del secondo documento del lotto",
                "a-primo.txt": b"testo del primo documento del lotto",
            }
        )
    )
    kind, pages = extract_file(path, ocr_enabled=False)
    assert kind == "text"
    assert [number for number, _ in pages] == [1, 2]
    # l'ordine e' per nome, non per come sono stati inseriti nell'archivio
    assert pages[0][1].startswith("a-primo.")
    assert "primo documento" in pages[0][1]
    assert "secondo documento" in pages[1][1]


def test_archive_reads_pdfs_without_extension(tmp_path: Path) -> None:
    pdf = build_pdf(tmp_path / "servizio.pdf", ["Il prefill misura la lettura del contesto"])
    path = tmp_path / "POSTE NOVEMBRE.zip"
    path.write_bytes(_zip({"POSTE NOVEMBRE/BC_005000_13_11_2026": pdf.read_bytes()}))
    kind, pages = extract_file(path, ocr_enabled=False)
    assert kind == "pdf"
    assert len(pages) == 1
    assert pages[0][1].startswith("BC_005000_13_11_2026.")
    assert "prefill" in pages[0][1]


def test_archive_skips_what_it_cannot_read(tmp_path: Path) -> None:
    path = tmp_path / "misto.zip"
    path.write_bytes(
        _zip(
            {
                "buono.txt": b"testo leggibile senza problemi",
                "rotto.bin": b"\x00\x01\x02\x03",
                "__MACOSX/._buono.txt": b"spazzatura",
            }
        )
    )
    kind, pages = extract_file(path, ocr_enabled=False)
    assert kind == "text"
    assert len(pages) == 1
    assert "leggibile" in pages[0][1]


def test_empty_archive_is_an_explicit_error(tmp_path: Path) -> None:
    path = tmp_path / "vuoto.zip"
    path.write_bytes(_zip({".DS_Store": b"x"}))
    with pytest.raises(ExtractionError, match="vuoto"):
        extract_file(path, ocr_enabled=False)


def test_broken_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "finto.zip"
    path.write_bytes(b"non sono uno zip")
    with pytest.raises(ExtractionError):
        extract_file(path, ocr_enabled=False)


def test_extensionless_archive_upload_becomes_one_source(store, settings, tmp_path) -> None:
    pdf = build_pdf(tmp_path / "uno.pdf", ["La Vega 64 ha sedici gigabyte di memoria video"])
    data = _zip(
        {
            "BC_004992.pdf": pdf.read_bytes(),
            "BC_005000.pdf": pdf.read_bytes(),
        }
    )
    source = ingest.create_from_bytes(
        store, settings, notebook_id="nb_test", filename="POSTE NOVEMBRE", data=data
    )
    assert source["status"] == "ready"
    assert source["kind"] == "pdf"
    assert source["pages"] == 2
    texts = " ".join(chunk["text"] for chunk in store.chunks(source["id"]))
    assert "memoria video" in texts
    # il nome del documento resta nel testo, cosi' il modello puo' citarlo
    assert "BC_004992" in texts
    assert "BC_005000" in texts
