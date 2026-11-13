"""Client del router llama.cpp: elenco modelli e generazione in streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import Settings

TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)


class LLMError(RuntimeError):
    """Il router non risponde o rifiuta la richiesta."""


async def models(settings: Settings) -> list[dict[str, Any]]:
    url = f"{settings.router_url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as error:
        raise LLMError(f"router non raggiungibile su {settings.router_url}: {error}") from error
    except ValueError as error:
        raise LLMError("risposta del router non valida") from error

    result: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        meta = item.get("meta") or {}
        status = item.get("status") or {}
        result.append(
            {
                "id": item.get("id", ""),
                "loaded": status.get("value") == "loaded",
                "context": meta.get("n_ctx") or item.get("context_length"),
                "params": meta.get("n_params"),
                "vision": "image" in (item.get("architecture") or {}).get("input_modalities", []),
            }
        )
    return result


async def probe(settings: Settings) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            response = await client.get(f"{settings.router_url}/health")
        return {"reachable": response.status_code < 500, "status": response.status_code}
    except httpx.HTTPError:
        return {"reachable": False, "status": 0}


async def stream_chat(
    settings: Settings,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    top_p: float,
    thinking: bool = False,
) -> AsyncIterator[str]:
    """Genera token per token; solleva LLMError con il messaggio del router."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        # Qwen3 chiede esplicitamente di disattivare il ragionamento: senza
        # questo il modello consuma i token nel blocco "thinking" e la risposta
        # resta vuota. Gli altri preset ignorano il parametro.
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    url = f"{settings.router_url}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"il router ha risposto {response.status_code}: {detail[:400]}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = httpx.Response(200, content=data).json()
                    except ValueError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield str(content)
        except httpx.HTTPError as error:
            raise LLMError(f"connessione al router interrotta: {error}") from error
