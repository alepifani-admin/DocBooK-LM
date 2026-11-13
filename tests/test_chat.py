from __future__ import annotations

from docbooklm.chat import build_context, build_messages, verify


def passage(n: int, text: str, page: int = 1) -> dict:
    return {
        "n": n,
        "source_id": "src_1",
        "source_title": "Documento",
        "chunk_id": 100 + n,
        "page": page,
        "section": "",
        "text": text,
    }


def test_build_context_is_numbered() -> None:
    context = build_context([passage(1, "primo testo", 3)])
    assert context.startswith("[1] (fonte: Documento, pagina 3)")
    assert "primo testo" in context


def test_build_messages_starts_with_system_and_ends_with_question() -> None:
    messages = build_messages("domanda?", [passage(1, "testo")], [{"role": "user", "text": "ciao"}])
    assert messages[0]["role"] == "system"
    assert "citazione" in messages[0]["content"].lower()
    assert messages[1] == {"role": "user", "content": "ciao"}
    assert "domanda?" in messages[-1]["content"]


def test_verify_keeps_supported_citation() -> None:
    answer = "La memoria video è di sedici gigabyte [1]."
    text, citations = verify(answer, [passage(1, "La Vega 64 ha sedici gigabyte di memoria video.")])
    assert text == answer
    assert len(citations) == 1
    assert citations[0]["n"] == 1
    assert "sedici gigabyte" in citations[0]["quote"]


def test_verify_removes_invented_citation() -> None:
    answer = "Il modello costa poco [1]."
    text, citations = verify(answer, [passage(1, "La Vega 64 ha sedici gigabyte di memoria video.")])
    assert text == "Il modello costa poco."
    assert citations == []


def test_verify_drops_out_of_range_number() -> None:
    text, citations = verify("Frase con numero inesistente [9].", [passage(1, "Frase qualsiasi.")])
    assert "[9]" not in text
    assert citations == []


def test_verify_keeps_only_valid_part_of_a_group() -> None:
    answer = "Il prefill è alto e la scheda ha sedici gigabyte [1][2]."
    passages = [
        passage(1, "Il prefill misura la velocita di lettura del contesto."),
        passage(2, "Argomento completamente diverso, senza parole in comune."),
    ]
    text, citations = verify(answer, passages)
    assert "[1]" in text
    assert "[2]" not in text
    assert [citation["n"] for citation in citations] == [1]


def test_verify_deduplicates_identical_citations() -> None:
    answer = "La Vega ha sedici gigabyte [1]. Confermo: sedici gigabyte [1]."
    text, citations = verify(answer, [passage(1, "La Vega 64 ha sedici gigabyte di memoria.")])
    assert text.count("[1]") == 2
    assert len(citations) == 1
