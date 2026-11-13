"""Retrieval ibrido: fusione, rerank, quote per fonte e degradazione."""

from __future__ import annotations

import numpy as np
import pytest

from docbooklm import embed, retrieve, vectors
from docbooklm.config import Settings
from docbooklm.store import Store


def _notebook_source(store: Store, source_id: str, title: str, texts: list[str]) -> list[int]:
    store.add_source(
        source_id=source_id,
        notebook_id="nb_test",
        kind="text",
        title=title,
        origin=f"{source_id}.txt",
        path=None,
        sha256=source_id,
    )
    store.add_chunks(source_id, [{"text": text, "page": 1} for text in texts])
    return [int(chunk["id"]) for chunk in store.chunks(source_id)]


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        embed_enabled=True,
        sidecar_enabled=False,
        ocr_enabled=False,
    )


def test_fuse_puts_shared_hits_first() -> None:
    fused = retrieve.fuse([[10, 20, 30], [30, 40]], limit=3)
    assert fused[0] == 30  # presente in entrambe le liste
    assert set(fused[1:]) <= {10, 20, 40}


def test_fair_share_grows_with_few_sources() -> None:
    assert retrieve.fair_share(1) == retrieve.MAX_PASSAGES
    assert retrieve.fair_share(2) == 5
    assert retrieve.fair_share(10) == retrieve.MIN_PER_SOURCE


def test_dense_finds_passage_without_shared_words(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "src_dense"
    ids = _notebook_source(
        store,
        source_id,
        "Scheda",
        [
            "La Vega 64 dispone di sedici gigabyte di memoria video.",
            "La pasta si cuoce in acqua salata per dieci minuti.",
        ],
    )
    store.add_vectors(
        source_id,
        [
            (ids[0], vectors.pack([1.0, 0.0, 0.0]), 3),
            (ids[1], vectors.pack([0.0, 1.0, 0.0]), 3),
        ],
    )
    # domanda senza nessuna parola in comune con il passaggio giusto
    question = "quanta VRAM ha la scheda?"
    assert retrieve.fts_query(question)

    monkeypatch.setattr(embed, "embed_query", lambda *_: np.array([1.0, 0.0, 0.0]))
    monkeypatch.setattr(embed, "rerank", lambda *_, **__: None)

    passages = retrieve.select(store, [source_id], question, settings=settings)
    assert passages
    assert "sedici gigabyte" in passages[0]["text"]


def test_rerank_reorders_candidates(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts = [f"Il motore numero {index} usa la memoria video e il contesto del modello." for index in range(14)]
    texts[7] = "Il modello Qwen3.5-9B raggiunge 252 token al secondo in prefill."
    ids = _notebook_source(store, "src_rerank", "Manuale", texts)
    monkeypatch.setattr(embed, "embed_query", lambda *_: np.array([1.0, 0.0]))
    seen = {"documents": 0}

    def fake_rerank(_settings: Settings, _question: str, documents: list[str]) -> list[float]:
        seen["documents"] = len(documents)
        return [0.9 if "252 token" in text else 0.1 for text in documents]

    monkeypatch.setattr(embed, "rerank", fake_rerank)
    passages = retrieve.select(store, ["src_rerank"], "quale modello e' piu' veloce?", settings=settings)
    assert seen["documents"] > retrieve.MAX_PASSAGES  # il rerank ha avuto qualcosa da decidere
    assert passages[0]["chunk_id"] == ids[7]


def test_rerank_is_skipped_when_every_candidate_fits(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _notebook_source(
        store,
        "src_small",
        "Breve",
        [
            "La Vega 64 ha sedici gigabyte di memoria video.",
            "Il contesto massimo del modello e' 64k.",
        ],
    )
    monkeypatch.setattr(embed, "embed_query", lambda *_: np.array([1.0, 0.0]))

    def explode(*_args: object, **_kwargs: object) -> list[float]:
        raise AssertionError("con meno passaggi di MAX_PASSAGES il rerank non serve")

    monkeypatch.setattr(embed, "rerank", explode)
    assert retrieve.select(store, ["src_small"], "quanta memoria video?", settings=settings)


def test_without_sidecar_lexical_still_works(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "src_lex"
    _notebook_source(
        store,
        source_id,
        "Scheda",
        [
            "La Vega 64 dispone di sedici gigabyte di memoria video.",
            "La pasta si cuoce in acqua salata per dieci minuti.",
        ],
    )
    monkeypatch.setattr(embed, "embed_query", lambda *_: None)  # sidecar spento
    monkeypatch.setattr(embed, "rerank", lambda *_, **__: None)
    passages = retrieve.select(store, [source_id], "quanta memoria video ha la Vega?", settings=settings)
    assert passages
    assert "sedici gigabyte" in passages[0]["text"]


def test_select_without_settings_is_pure_lexical(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "src_pure"
    _notebook_source(
        store,
        source_id,
        "Scheda",
        ["La Vega 64 dispone di sedici gigabyte di memoria video."],
    )

    def explode(*_args, **_kwargs):  # pragma: no cover - non deve essere chiamato
        raise AssertionError("senza settings non si deve usare la rete")

    monkeypatch.setattr(embed, "embed_query", explode)
    passages = retrieve.select(store, [source_id], "quanta memoria ha la Vega?")
    assert passages
    assert passages[0]["n"] == 1


def test_quota_per_source_is_respected(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = "src_one"
    second = "src_two"
    texts = [f"Il motore numero {index} usa la memoria video e il contesto." for index in range(8)]
    _notebook_source(store, first, "Primo", texts)
    _notebook_source(store, second, "Secondo", [f"Altra fonte numero {i}." for i in range(8)])

    monkeypatch.setattr(embed, "embed_query", lambda *_: None)
    monkeypatch.setattr(embed, "rerank", lambda *_, **__: None)
    passages = retrieve.select(store, [first, second], "memoria video contesto", settings=settings)
    counts: dict[str, int] = {}
    for passage in passages:
        counts[passage["source_id"]] = counts.get(passage["source_id"], 0) + 1
    assert counts[first] <= retrieve.fair_share(2)
    assert counts[second] <= retrieve.fair_share(2)


def test_generic_question_falls_back_to_heads(    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "src_head"
    _notebook_source(store, source_id, "Libro", ["Primo paragrafo del libro.", "Secondo paragrafo."])
    monkeypatch.setattr(embed, "embed_query", lambda *_: None)
    monkeypatch.setattr(embed, "rerank", lambda *_, **__: None)
    passages = retrieve.select(store, [source_id], "riassumi", settings=settings)
    assert passages
    assert passages[0]["page"] == 1


def test_excerpt_centres_on_the_question_words() -> None:
    text = "premessa senza costrutto " * 120 + (
        "la scheda grafica dispone di sedici gigabyte di memoria video. "
    ) + "coda inutile " * 120
    cut = retrieve.excerpt(text, "quanta memoria video ha la scheda grafica?")
    assert len(cut) == retrieve.RERANK_CHARS
    assert "sedici gigabyte" in cut


def test_excerpt_keeps_a_short_passage_whole() -> None:
    assert retrieve.excerpt("testo breve", "domanda qualsiasi") == "testo breve"


def test_excerpt_without_matches_starts_from_the_top() -> None:
    text = "prologo " * 400
    assert retrieve.excerpt(text, "questione diversa").startswith("prologo")
