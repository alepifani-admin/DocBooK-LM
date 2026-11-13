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
    # il titolo resta nel testo: e' contesto utile al modello e all'embedding
    assert blocks[0].text == "INTRODUZIONE"
    assert blocks[1].text == "prima riga del testo"
    assert blocks[-1].page == 2


def test_uppercase_data_lines_are_not_swallowed_as_headings() -> None:
    # in un documento di trasporto il destinatario e' scritto in maiuscolo
    page = "Cliente\nDBR_DIREZIONE REGIONALE PUGLIA\nP.ZZA A. MORO- INTERNO STAZIONE FS\n70122 BARI (BA)"
    chunks = chunks_from_pages([(1, page)])
    text = "\n".join(chunk.text for chunk in chunks)
    assert "DBR_DIREZIONE REGIONALE PUGLIA" in text
    assert "70122 BARI (BA)" in text


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


def test_small_fragments_are_merged_into_the_page_chunk() -> None:
    # modulo a colonne: le etichette sembrano titoli e spezzano il testo
    page = "\n".join(
        [
            "PRIVACY: AI SENSI DELL'ART 13 D.LGS 196/2003 I VOSTRI DATI VENGONO USATI "
            "SOLO PER FINI CONTABILI ED AMMINISTRATIVI, come previsto dalla normativa.",
            "FIRMA VETTORE",
            "Cliente Destinatario",
            "ABI/CAB",
            "Pagamento Agente",
            "P.IVA",
            "IT05403151003 MPS",
        ]
    )
    chunks = chunks_from_pages([(1, page)])
    assert len(chunks) == 1
    assert "Pagamento Agente" in chunks[0].text
    assert chunks[0].page == 1


def test_small_fragments_never_merge_across_pages() -> None:
    pages = [(1, "prima pagina con poco testo"), (2, "seconda pagina con poco testo")]
    chunks = chunks_from_pages(pages)
    assert {chunk.page for chunk in chunks} == {1, 2}
    assert chunks[0].text == "prima pagina con poco testo"
    assert chunks[1].text == "seconda pagina con poco testo"
