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
    last_payload: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    def stream(self, _method: str, _url: str, **kwargs: Any) -> _Stream:
        self.last_payload = kwargs.get("json") or {}
        _AsyncClient.last_payload = self.last_payload
        return _Stream(_Response(list(self.lines)))


def _settings() -> Settings:
    return Settings(embed_enabled=False, sidecar_enabled=False)


def _collect(
    monkeypatch: pytest.MonkeyPatch, lines: list[str], *, thinking: bool = False
) -> list[tuple[str, str]]:
    _AsyncClient.lines = lines
    monkeypatch.setattr(llm.httpx, "AsyncClient", _AsyncClient)

    async def run() -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = []
        async for kind, piece in llm.stream_chat(
            _settings(),
            model="Qwen",
            messages=[{"role": "user", "content": "ciao"}],
            max_tokens=16,
            temperature=0.0,
            top_p=0.9,
            thinking=thinking,
        ):
            chunks.append((kind, piece))
        return chunks

    return asyncio.run(run())


def test_stream_chat_yields_only_content(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data: {"choices": [{"delta": {"role": "assistant"}}]}',
        'data: {"choices": [{"delta": {"content": "La "}}]}',
        'data: {"choices": [{"delta": {"content": "Vega 64."}}]}',
        "data: [DONE]",
    ]
    assert _collect(monkeypatch, lines) == [("text", "La "), ("text", "Vega 64.")]


def test_reasoning_is_reported_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    # gpt-oss scrive il ragionamento in reasoning_content: mostrarlo come testo
    # della risposta significherebbe citare i propri pensieri
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "prima"}}]}',
        'data: {"choices": [{"delta": {"reasoning_content": " chiede"}}]}',
        'data: {"choices": [{"delta": {"content": "Sedici GB [1]."}}]}',
    ]
    assert _collect(monkeypatch, lines) == [
        ("reasoning", "prima"),
        ("reasoning", " chiede"),
        ("text", "Sedici GB [1]."),
    ]


def test_reasoning_effort_follows_the_thinking_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = ['data: {"choices": [{"delta": {"content": "ok"}}]}']
    _collect(monkeypatch, lines, thinking=False)
    kwargs = _AsyncClient.last_payload["chat_template_kwargs"]
    assert kwargs == {"enable_thinking": False, "reasoning_effort": "low"}

    _collect(monkeypatch, lines, thinking=True)
    kwargs = _AsyncClient.last_payload["chat_template_kwargs"]
    assert kwargs == {"enable_thinking": True, "reasoning_effort": "high"}


def test_stream_chat_surfaces_a_router_error(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data: {"choices": [{"delta": {"content": "parziale"}}]}',
        'data: {"error": {"message": "modello non caricato"}}',
    ]
    with pytest.raises(llm.LLMError, match="modello non caricato"):
        _collect(monkeypatch, lines)


def test_reasoning_that_eats_the_budget_is_explained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # il caso vero: gpt-oss-20b, contesto grande, 1200 token tutti nel
    # ragionamento e finish_reason "length"
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "penso a lungo"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}',
        "data: [DONE]",
    ]
    with pytest.raises(llm.LLMError, match="tutti i token"):
        _collect(monkeypatch, lines)
