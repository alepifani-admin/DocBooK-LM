from __future__ import annotations

from docbooklm.chunk import (
    blocks_from_pages,
    chunks_from_pages,
    estimate_tokens,
    looks_like_heading,
)


def test_heading_uppercase() -> None:
    assert looks_like_heading("INTRODUZIONE AL SISTEMA")
    assert looks_like_heading("1.2 Metodo")
    assert looks_like_heading("Capitolo terzo")


def test_table_row_is_not_a_heading() -> None:
    # una riga di tabella ha le iniziali maiuscole ma non e' un titolo
    assert not looks_like_heading("Coding qualita Qwen3-Coder 30B")
    assert not looks_like_heading("Il modello risponde bene a questa domanda.")


def test_blocks_keep_section_and_page() -> None:
    pages = [(1, "INTRODUZIONE\nprima riga del testo\nseconda riga"), (2, "altra pagina")]
    blocks = blocks_from_pages(pages)
    assert blocks[0].section == "INTRODUZIONE"
    assert blocks[0].page == 1
    assert blocks[0].text == "prima riga del testo"
    assert blocks[-1].page == 2


def test_chunks_do_not_cross_pages() -> None:
    pages = [(1, "a" * 100), (2, "b" * 100)]
    chunks = chunks_from_pages(pages)
    assert {chunk.page for chunk in chunks} == {1, 2}


def test_chunk_size_respects_target() -> None:
    line = "parola " * 120  # ~840 caratteri
    pages = [(1, "\n".join([line] * 20))]
    chunks = chunks_from_pages(pages)
    assert len(chunks) > 1
    assert all(len(chunk.text) < 4800 for chunk in chunks)


def test_overlap_between_chunks() -> None:
    line = "contenuto ripetuto " * 30
    pages = [(1, "\n".join([line] * 40))]
    chunks = chunks_from_pages(pages)
    assert len(chunks) >= 2
    # la coda del primo passaggio ricompare all'inizio del secondo
    assert chunks[0].text.splitlines()[-1] in chunks[1].text


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 100
