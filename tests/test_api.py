"""Test dell'API: upload, stato, note e streaming della chat con motore finto."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docbooklm import api as api_module
from docbooklm import llm


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DOCBOOKLM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCBOOKLM_OCR_ENABLED", "false")
    # i test non devono avviare processi llama-server ne' aspettare la GPU
    monkeypatch.setenv("DOCBOOKLM_EMBED_ENABLED", "false")
    monkeypatch.setenv("DOCBOOKLM_SIDECAR_ENABLED", "false")
    api_module.get_settings.cache_clear()
    with TestClient(api_module.app) as test_client:
        yield test_client
    api_module.get_settings.cache_clear()


def notebook_id(client: TestClient) -> str:
    payload = client.get("/api/state").json()
    return str(payload["notebook"]["id"])


def add_text_source(client: TestClient, text: str = "La Vega 64 ha sedici gigabyte di memoria video.") -> dict:
    response = client.post(
        "/api/sources/text",
        data={"notebook": notebook_id(client), "title": "Prova", "text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    payload = client.get("/health").json()
    assert payload["service"] == "docbooklm"
    assert "router" in payload


def test_state_has_default_notebook(client: TestClient) -> None:
    payload = client.get("/api/state").json()
    assert payload["notebook"]["name"] == "Il mio quaderno"
    assert payload["sources"] == []
    assert payload["notes"] == []
    assert "models" in payload


def test_index_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "DocBooK LM" in response.text


def test_static_assets_exist(client: TestClient) -> None:
    for asset in ("/static/app.js", "/static/style.css", "/static/icons.svg", "/static/api.js"):
        assert client.get(asset).status_code == 200, asset


def test_notebook_crud(client: TestClient) -> None:
    created = client.post("/api/notebooks", json={"name": "Nuovo"}).json()
    assert created["name"] == "Nuovo"
    assert client.patch(f"/api/notebooks/{created['id']}", json={"name": "Rinominato"}).status_code == 200
    assert client.delete(f"/api/notebooks/{created['id']}").status_code == 200
    assert client.delete("/api/notebooks/inesistente").status_code == 404


def test_upload_and_delete_source(client: TestClient) -> None:
    source = add_text_source(client)
    assert source["status"] == "ready"
    listing = client.get(f"/api/sources?notebook={notebook_id(client)}").json()["sources"]
    assert [item["id"] for item in listing] == [source["id"]]
    detail = client.get(f"/api/sources/{source['id']}").json()
    assert detail["passages"]
    assert client.delete(f"/api/sources/{source['id']}").status_code == 200
    assert client.get(f"/api/sources/{source['id']}").status_code == 404


def test_upload_unknown_notebook(client: TestClient) -> None:
    response = client.post("/api/sources/text", data={"notebook": "nope", "text": "ciao"})
    assert response.status_code == 404


def test_empty_text_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/sources/text", data={"notebook": notebook_id(client), "text": "   "}
    )
    assert response.status_code == 400


def test_notes_crud(client: TestClient) -> None:
    created = client.post(
        "/api/notes", json={"notebook": notebook_id(client), "title": "N", "markdown": "testo"}
    ).json()
    assert created["title"] == "N"
    patched = client.patch(f"/api/notes/{created['id']}", json={"markdown": "altro"}).json()
    assert patched["markdown"] == "altro"
    assert client.delete(f"/api/notes/{created['id']}").status_code == 200
    assert client.patch("/api/notes/nope", json={"markdown": "x"}).status_code == 404


def test_chat_requires_sources(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"notebook": notebook_id(client), "question": "ciao", "sources": []}
    )
    assert response.status_code == 400


def test_chat_streams_and_verifies_citations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = add_text_source(client)

    async def fake_stream(*_args, **_kwargs) -> AsyncIterator[str]:
        yield "La scheda ha sedici gigabyte "
        yield "di memoria video [1]. Il resto è inventato [7]."

    monkeypatch.setattr(llm, "stream_chat", fake_stream)

    events: list[tuple[str, str]] = []
    with client.stream(
        "POST",
        "/api/chat",
        json={
            "notebook": notebook_id(client),
            "question": "quanta memoria ha la scheda?",
            "sources": [source["id"]],
        },
    ) as response:
        assert response.status_code == 200
        event = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                events.append((event, line[5:].strip()))

    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "delta" in names
    assert names[-1] == "done"

    import json

    done = json.loads(events[-1][1])
    assert "[1]" in done["text"]
    assert "[7]" not in done["text"]
    assert len(done["citations"]) == 1
    assert done["citations"][0]["n"] == 1

    messages = client.get("/api/state").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["citations"][0]["chunk_id"]


def test_chat_reports_engine_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    source = add_text_source(client)

    async def broken(*_args, **_kwargs) -> AsyncIterator[str]:
        raise llm.LLMError("router giù")
        yield ""  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", broken)
    with client.stream(
        "POST",
        "/api/chat",
        json={
            "notebook": notebook_id(client),
            "question": "domanda",
            "sources": [source["id"]],
        },
    ) as response:
        body = "".join(response.iter_text())
    assert "error" in body
    assert "router giù" in body


def test_models_endpoint_handles_dead_router(client: TestClient) -> None:
    payload = client.get("/api/models").json()
    assert "models" in payload
    assert payload["current"]


def test_select_model(client: TestClient) -> None:
    available = client.get("/api/models").json()["models"]
    target = available[0]["id"] if available else "Qwen3.5-9B"
    payload = client.post("/api/models/select", json={"model": target}).json()
    assert payload["current"] == target
    assert client.get("/api/models").json()["current"] == target
