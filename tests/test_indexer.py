from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from docbooklm import embed, indexer
from docbooklm.config import Settings
from docbooklm.store import Store


def _source_with_chunks(store: Store, count: int = 3) -> str:
    store.add_source(
        source_id="src_idx",
        notebook_id="nb_test",
        kind="text",
        title="Indicizzata",
        origin="i.txt",
        path=None,
        sha256="idx",
    )
    store.add_chunks(
        "src_idx", [{"text": f"passaggio numero {index}", "page": 1} for index in range(count)]
    )
    return "src_idx"


def test_embed_source_writes_one_vector_per_chunk(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = _source_with_chunks(store, 5)

    def fake(_settings: Settings, texts: list[str]) -> np.ndarray:
        return np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (len(texts), 1))

    monkeypatch.setattr(indexer.embed, "embed_texts", fake)
    written = indexer.embed_source(store, settings, source_id)
    assert written == 5
    assert store.vector_count([source_id]) == 5
    assert store.chunks_without_vectors(source_id) == []


def test_embed_source_retries_a_failing_batch(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = _source_with_chunks(store, 1)
    calls = {"n": 0}

    def flaky(_settings: Settings, texts: list[str]) -> np.ndarray:
        calls["n"] += 1
        if calls["n"] == 1:
            raise embed.EmbedError("sidecar non pronto")
        return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))

    monkeypatch.setattr(indexer.embed, "embed_texts", flaky)
    monkeypatch.setattr(indexer.time, "sleep", lambda _seconds: None)

    assert indexer.embed_source(store, settings, source_id) == 1
    assert calls["n"] == 2


def test_embed_source_gives_up_without_raising(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = _source_with_chunks(store, 2)

    def broken(_settings: Settings, _texts: list[str]) -> np.ndarray:
        raise embed.EmbedError("giu'")

    monkeypatch.setattr(indexer.embed, "embed_texts", broken)
    monkeypatch.setattr(indexer.time, "sleep", lambda _seconds: None)

    assert indexer.embed_source(store, settings, source_id) == 0
    assert store.vector_count([source_id]) == 0


def test_embed_source_is_incremental(store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    source_id = _source_with_chunks(store, 2)
    monkeypatch.setattr(
        indexer.embed,
        "embed_texts",
        lambda _s, texts: np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1)),
    )
    assert indexer.embed_source(store, settings, source_id) == 2
    # chiamata successiva: non resta niente da fare
    assert indexer.embed_source(store, settings, source_id) == 0


def test_submit_respects_disabled_embedding(store: Store, settings: Settings) -> None:
    assert settings.embed_enabled is False  # dalla fixture
    assert indexer.submit(store, settings, "src_idx") is False


# ---------------------------------------------------------------- lotti e troncamento


def test_batches_respect_the_character_budget() -> None:
    items = [{"id": index, "text": "x" * 2000} for index in range(6)]
    batches = list(indexer._batches(items, size=8, budget=5000))
    assert [len(batch) for batch in batches] == [2, 2, 2]
    for batch in batches:
        assert sum(len(str(item["text"])) for item in batch) <= 5000


def test_batches_respect_the_item_limit() -> None:
    items = [{"id": index, "text": "corto"} for index in range(10)]
    assert [len(batch) for batch in indexer._batches(items, size=4)] == [4, 4, 2]


def test_batches_keep_an_oversized_passage_alone() -> None:
    items = [{"id": 0, "text": "x" * 9000}, {"id": 1, "text": "corto"}]
    assert [len(batch) for batch in indexer._batches(items)] == [1, 1]


def test_embed_texts_truncates_a_long_passage(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, list[str]] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": [{"index": 0, "embedding": [3.0, 4.0]}]}

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def post(self, _url: str, json: dict[str, Any]) -> FakeResponse:
            seen["input"] = list(json["input"])
            return FakeResponse()

    monkeypatch.setattr(embed.httpx, "Client", FakeClient)
    matrix = embed.embed_texts(settings, ["parola " * 5000])
    # un passaggio troppo lungo supera l'ubatch del sidecar: si manda troncato
    assert len(seen["input"][0]) == embed.MAX_ITEM_CHARS
    assert np.allclose(np.linalg.norm(matrix[0]), 1.0)
