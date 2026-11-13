from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest

from docbooklm import llm
from docbooklm.config import Settings


class _Response:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _Stream:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> _Response:
        return self._response

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _AsyncClient:
    lines: ClassVar[list[str]] = []

    def __init__(self, **_kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    def stream(self, _method: str, _url: str, **_kwargs: Any) -> _Stream:
        return _Stream(_Response(list(self.lines)))


def _settings() -> Settings:
    return Settings(embed_enabled=False, sidecar_enabled=False)


def _collect(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> list[str]:
    _AsyncClient.lines = lines
    monkeypatch.setattr(llm.httpx, "AsyncClient", _AsyncClient)

    async def run() -> list[str]:
        chunks: list[str] = []
        async for piece in llm.stream_chat(
            _settings(),
            model="Qwen",
            messages=[{"role": "user", "content": "ciao"}],
            max_tokens=16,
            temperature=0.0,
            top_p=0.9,
        ):
            chunks.append(piece)
        return chunks

    return asyncio.run(run())


def test_stream_chat_yields_only_content(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data: {"choices": [{"delta": {"role": "assistant"}}]}',
        'data: {"choices": [{"delta": {"content": "La "}}]}',
        'data: {"choices": [{"delta": {"content": "Vega 64."}}]}',
        "data: [DONE]",
    ]
    assert _collect(monkeypatch, lines) == ["La ", "Vega 64."]


def test_stream_chat_surfaces_a_router_error(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data: {"choices": [{"delta": {"content": "parziale"}}]}',
        'data: {"error": {"message": "modello non caricato"}}',
    ]
    with pytest.raises(llm.LLMError, match="modello non caricato"):
        _collect(monkeypatch, lines)
