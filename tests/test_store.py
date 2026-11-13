from __future__ import annotations

from docbooklm.store import Store


def test_notebooks_crud(store: Store) -> None:
    created = store.create_notebook("nb_2", "Secondo")
    assert created["name"] == "Secondo"
    assert store.rename_notebook("nb_2", "Rinominato")
    assert store.notebook("nb_2")["name"] == "Rinominato"  # type: ignore[index]
    assert store.delete_notebook("nb_2")
    assert store.notebook("nb_2") is None


def test_ensure_notebook_creates_once(store: Store) -> None:
    store.ensure_notebook("nb_x")
    store.ensure_notebook("nb_x")
    assert [item["id"] for item in store.notebooks()].count("nb_x") == 1


def test_source_lifecycle_and_cascade(store: Store) -> None:
    store.add_source(
        source_id="src_a",
        notebook_id="nb_test",
        kind="text",
        title="Documento",
        origin="doc.txt",
        path=None,
        sha256="abc",
    )
    store.add_chunks("src_a", [{"text": "la scheda ha sedici gigabyte", "page": 1}])
    store.finish_source("src_a", pages=1, n_tokens=8)

    assert store.source("src_a")["status"] == "ready"  # type: ignore[index]
    assert len(store.chunks("src_a")) == 1
    assert store.search(["src_a"], '"sedici"*')
    assert store.search(["src_other"], '"sedici"*') == []

    assert store.delete_source("src_a")
    assert store.chunks("src_a") == []
    assert store.search(["src_a"], '"sedici"*') == []


def test_fts_ignores_accents_and_matches_prefix(store: Store) -> None:
    store.add_source(
        source_id="src_b",
        notebook_id="nb_test",
        kind="text",
        title="Doc",
        origin="doc.txt",
        path=None,
        sha256="def",
    )
    store.add_chunks("src_b", [{"text": "La velocità del prefill è alta", "page": 1}])
    assert store.search(["src_b"], '"velocita"*')
    assert store.search(["src_b"], '"prefi"*')


def test_search_tolerates_broken_query(store: Store) -> None:
    assert store.search(["src_b"], '"') == []


def test_notes(store: Store) -> None:
    note = store.add_note("nb_test", "note_1", "Titolo", "testo")
    assert note["title"] == "Titolo"
    assert store.notes("nb_test")[0]["id"] == "note_1"
    updated = store.update_note("note_1", title="Nuovo", markdown="altro")
    assert updated["markdown"] == "altro"  # type: ignore[index]
    assert store.note("note_1")["title"] == "Nuovo"  # type: ignore[index]
    assert store.delete_note("note_1")
    assert store.note("note_1") is None


def test_kv(store: Store) -> None:
    assert store.get_kv("model", "default") == "default"
    store.set_kv("model", "Qwen3.5")
    store.set_kv("model", "Qwen3.5-9B")
    assert store.get_kv("model") == "Qwen3.5-9B"


def test_messages_roundtrip(store: Store) -> None:
    store.add_message(
        message_id="msg_1",
        notebook_id="nb_test",
        role="assistant",
        text="risposta",
        citations=[{"n": 1}],
        model="m",
    )
    messages = store.messages("nb_test")
    assert messages[0]["role"] == "assistant"
    assert messages[0]["citations"] == [{"n": 1}]
