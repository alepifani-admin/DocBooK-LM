from __future__ import annotations

import pytest

from docbooklm import ingest
from docbooklm.extract import ExtractionError, extract_file, kind_for


def test_kind_detection() -> None:
    assert kind_for("a.PDF") == "pdf"
    assert kind_for("b.docx") == "docx"
    assert kind_for("c.png") == "image"
    assert kind_for("d.md") == "text"
    assert kind_for("e.bin") == "binary"


def test_text_source_is_indexed(store, settings, tmp_path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Titolo\n\nLa Vega 64 ha 16 GB di memoria video.", encoding="utf-8")
    source = ingest.create_from_bytes(
        store, settings, notebook_id="nb_test", filename=path.name, data=path.read_bytes()
    )
    assert source["status"] == "ready"
    assert source["kind"] == "text"
    assert source["n_tokens"] > 0
    assert store.chunks(source["id"])


def test_pdf_source_is_indexed(store, settings, pdf_path) -> None:
    source = ingest.create_from_bytes(
        store, settings, notebook_id="nb_test", filename=pdf_path.name, data=pdf_path.read_bytes()
    )
    assert source["status"] == "ready"
    assert source["kind"] == "pdf"
    assert source["pages"] == 1
    text = " ".join(item["text"] for item in store.chunks(source["id"]))
    assert "prefill" in text


def test_duplicate_is_reported(store, settings, pdf_path) -> None:
    first = ingest.create_from_bytes(
        store, settings, notebook_id="nb_test", filename=pdf_path.name, data=pdf_path.read_bytes()
    )
    second = ingest.create_from_bytes(
        store, settings, notebook_id="nb_test", filename=pdf_path.name, data=pdf_path.read_bytes()
    )
    assert first["id"] == second["id"]
    assert second.get("duplicate")


def test_too_big_is_refused(store, settings) -> None:
    settings.max_upload_mb = 0
    with pytest.raises(ingest.IngestError):
        ingest.create_from_bytes(
            store, settings, notebook_id="nb_test", filename="a.txt", data=b"x" * 10
        )


def test_empty_file_is_refused(store, settings) -> None:
    with pytest.raises(ingest.IngestError):
        ingest.create_from_bytes(
            store, settings, notebook_id="nb_test", filename="a.txt", data=b""
        )


def test_unsupported_format(store, settings, tmp_path) -> None:
    path = tmp_path / "strano.bin"
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ingest.IngestError):
        ingest.create_from_bytes(
            store, settings, notebook_id="nb_test", filename=path.name, data=path.read_bytes()
        )


def test_extract_rejects_empty_text(tmp_path) -> None:
    path = tmp_path / "vuoto.txt"
    path.write_text("   \n\n ", encoding="utf-8")
    with pytest.raises(ExtractionError):
        extract_file(path)


def test_html_is_cleaned(tmp_path) -> None:
    path = tmp_path / "pagina.html"
    path.write_text(
        "<html><head><title>T</title><style>p{color:red}</style></head>"
        "<body><nav>menu</nav><p>Testo utile</p><script>x()</script></body></html>",
        encoding="utf-8",
    )
    _, pages = extract_file(path)
    assert "Testo utile" in pages[0][1]
    assert "menu" not in pages[0][1]
    assert "color:red" not in pages[0][1]
