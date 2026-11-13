from __future__ import annotations

import numpy as np

from docbooklm import vectors
from docbooklm.store import Store


def _source(store: Store, source_id: str = "src_v") -> str:
    store.add_source(
        source_id=source_id,
        notebook_id="nb_test",
        kind="text",
        title="Vettori",
        origin="v.txt",
        path=None,
        sha256=source_id,
    )
    return source_id


def test_pack_unpack_roundtrip() -> None:
    vector = np.array([0.5, -1.25, 3.0], dtype=np.float32)
    assert np.allclose(vectors.unpack(vectors.pack(vector)), vector)
    assert len(vectors.pack(vector)) == 3 * 4


def test_normalize_unit_norm() -> None:
    matrix = vectors.normalize(np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32))
    assert np.allclose(np.linalg.norm(matrix[0]), 1.0)
    assert np.allclose(matrix[1], [0.0, 0.0])  # vettore nullo: non divide per zero


def test_search_orders_by_similarity(store: Store) -> None:
    source_id = _source(store)
    store.add_chunks(
        source_id,
        [
            {"text": "memoria video della scheda", "page": 1},
            {"text": "velocita di generazione", "page": 1},
            {"text": "contesto massimo del modello", "page": 1},
        ],
    )
    chunks = store.chunks(source_id)
    store.add_vectors(
        source_id,
        [
            (chunks[0]["id"], vectors.pack([1.0, 0.0]), 2),
            (chunks[1]["id"], vectors.pack([0.0, 1.0]), 2),
            (chunks[2]["id"], vectors.pack([0.7, 0.7]), 2),
        ],
    )
    index = vectors.VectorIndex(store)
    hits = index.search([source_id], [1.0, 0.0], limit=3)
    assert [hit["chunk_id"] for hit in hits] == [chunks[0]["id"], chunks[2]["id"], chunks[1]["id"]]
    assert hits[0]["score"] > hits[1]["score"] > hits[2]["score"]


def test_search_ignores_other_sources(store: Store) -> None:
    first = _source(store, "src_a")
    second = _source(store, "src_b")
    store.add_chunks(first, [{"text": "primo", "page": 1}])
    store.add_chunks(second, [{"text": "secondo", "page": 1}])
    store.add_vectors(
        first, [(store.chunks(first)[0]["id"], vectors.pack([1.0, 0.0]), 2)]
    )
    store.add_vectors(
        second, [(store.chunks(second)[0]["id"], vectors.pack([1.0, 0.0]), 2)]
    )
    hits = vectors.VectorIndex(store).search([second], [1.0, 0.0])
    assert [hit["chunk_id"] for hit in hits] == [store.chunks(second)[0]["id"]]


def test_search_skips_vectors_of_another_model(store: Store) -> None:
    source_id = _source(store)
    store.add_chunks(source_id, [{"text": "testo", "page": 1}])
    store.add_vectors(source_id, [(store.chunks(source_id)[0]["id"], vectors.pack([1.0, 0.0, 0.0]), 3)])
    index = vectors.VectorIndex(store)
    # domanda a 2 dimensioni contro vettori a 3: non si confrontano
    assert index.search([source_id], [1.0, 0.0]) == []


def test_cache_follows_new_vectors_and_needs_invalidation_to_replace(store: Store) -> None:
    source_id = _source(store)
    store.add_chunks(source_id, [{"text": "primo", "page": 1}])
    first = int(store.chunks(source_id)[0]["id"])
    store.add_vectors(source_id, [(first, vectors.pack([1.0, 0.0]), 2)])
    index = vectors.VectorIndex(store)
    assert len(index.search([source_id], [1.0, 0.0])) == 1

    # un vettore in piu' cambia il conteggio: la matrice si ricostruisce da sola
    store.add_chunks(source_id, [{"text": "secondo", "page": 1}])
    second = int(store.chunks(source_id)[1]["id"])
    store.add_vectors(source_id, [(second, vectors.pack([0.0, 1.0]), 2)])
    assert len(index.search([source_id], [1.0, 0.0])) == 2

    # stessa quantita', contenuto diverso: serve invalidare esplicitamente
    store.add_vectors(source_id, [(first, vectors.pack([-1.0, 0.0]), 2)])
    assert index.search([source_id], [1.0, 0.0])[0]["chunk_id"] == first
    index.invalidate(source_id)
    assert index.search([source_id], [1.0, 0.0])[0]["chunk_id"] == second


def test_index_for_is_shared(store: Store) -> None:
    assert vectors.index_for(store) is vectors.index_for(store)
