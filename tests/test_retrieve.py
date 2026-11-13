from __future__ import annotations

from docbooklm import ingest
from docbooklm.retrieve import fts_query, is_generic, select, strip_accents, terms


def test_strip_accents() -> None:
    assert strip_accents("perché è così") == "perche e cosi"


def test_terms_drop_stopwords_and_duplicates() -> None:
    assert terms("Qual è il modello più veloce nel prefill?") == ["modello", "veloce", "prefill"]


def test_fts_query_uses_prefix() -> None:
    assert fts_query("modelli veloci") == '"modelli"* OR "veloci"*'


def test_fts_query_empty() -> None:
    assert fts_query("che cosa è") == ""


def test_generic_questions() -> None:
    assert is_generic("riassumi")
    assert is_generic("che cosa contiene?")
    assert not is_generic("quale modello ha il prefill più alto")


def test_select_gives_context_to_generic_question(store, settings, pdf_path) -> None:
    source = ingest.create_from_bytes(
        store,
        settings,
        notebook_id="nb_test",
        filename=pdf_path.name,
        data=pdf_path.read_bytes(),
    )
    passages = select(store, [source["id"]], "riassumi")
    assert passages
    assert passages[0]["n"] == 1
    assert passages[0]["page"] == 1
    assert "prefill" in passages[0]["text"]


def test_select_orders_by_relevance(store, settings, pdf_path) -> None:
    source = ingest.create_from_bytes(
        store,
        settings,
        notebook_id="nb_test",
        filename=pdf_path.name,
        data=pdf_path.read_bytes(),
    )
    passages = select(store, [source["id"]], "quanta memoria video ha la Vega?")
    assert passages
    assert passages[0]["n"] == 1


def test_select_skips_unknown_sources(store) -> None:
    assert select(store, [], "domanda") == []
