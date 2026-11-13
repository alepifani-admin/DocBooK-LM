"""Client dei due sidecar: embedding (bge-m3) e rerank (bge-reranker-v2-m3).

I sidecar sono processi llama-server separati dal router di chat: uno risponde
su /v1/embeddings, l'altro su /rerank. Se non ci sono, il retrieval resta
lessicale invece di rompersi: questo modulo non solleva mai verso l'interfaccia,
restituisce None e il chiamante decide.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import httpx
import numpy as np

from .config import Settings

logger = logging.getLogger("docbooklm")

EMBED_BATCH = 8
# Il sidecar ha ubatch fisico 2048: ~4000 caratteri italiani sono ~1100 token.
# Oltre, un singolo passaggio supera il batch fisico e llama-server risponde 500.
MAX_ITEM_CHARS = 4000
PROBE_TTL = 5.0
_ok_until: dict[str, float] = {}


class EmbedError(RuntimeError):
    """Il sidecar non risponde o rifiuta la richiesta."""


def _probe(url: str, path: str = "/health") -> bool:
    now = time.monotonic()
    if _ok_until.get(url, 0.0) > now:
        return True
    try:
        response = httpx.get(f"{url}{path}", timeout=httpx.Timeout(1.5))
        # 503 = llama-server sta ancora caricando il modello: non e' pronto
        healthy = response.status_code == 200
    except httpx.HTTPError:
        healthy = False
    if healthy:
        _ok_until[url] = now + PROBE_TTL
    else:
        _ok_until.pop(url, None)
    return healthy


def embeddings_ready(settings: Settings) -> bool:
    return settings.embed_enabled and _probe(settings.embed_url)


def rerank_ready(settings: Settings) -> bool:
    return settings.embed_enabled and _probe(settings.rerank_url, "/health")


def embed_texts(settings: Settings, texts: list[str], *, timeout: float = 180.0) -> np.ndarray:
    """Vettori normalizzati, una riga per testo. Solleva EmbedError."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    payload = {"input": [text[:MAX_ITEM_CHARS] for text in texts], "model": "bge-m3"}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response = client.post(f"{settings.embed_url}/v1/embeddings", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as error:
        _ok_until.pop(settings.embed_url, None)
        raise EmbedError(f"embedding non disponibile: {error}") from error
    except ValueError as error:
        raise EmbedError("risposta di embedding non valida") from error

    items = body.get("data") or []
    if len(items) != len(texts):
        raise EmbedError(f"attesi {len(texts)} vettori, ricevuti {len(items)}")
    ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
    matrix = np.asarray([item["embedding"] for item in ordered], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return cast(np.ndarray, matrix / norms)


def embed_query(settings: Settings, question: str) -> np.ndarray | None:
    """Vettore della domanda, o None se il sidecar non c'e'."""
    if not embeddings_ready(settings):
        return None
    try:
        vector = embed_texts(settings, [question])[0]
    except EmbedError as error:
        logger.warning("retrieval denso disattivato per questa domanda: %s", error)
        return None
    return cast(np.ndarray, vector)


def rerank(
    settings: Settings, question: str, documents: list[str], *, timeout: float = 45.0
) -> list[float] | None:
    """Punteggi di pertinenza nell'ordine dei documenti, o None senza sidecar."""
    if not documents or not rerank_ready(settings):
        return None
    payload = {"query": question, "documents": [doc[:2400] for doc in documents]}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response = client.post(f"{settings.rerank_url}/rerank", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as error:
        _ok_until.pop(settings.rerank_url, None)
        logger.warning("rerank non disponibile: %s", error)
        return None
    except ValueError:
        return None

    results: list[dict[str, Any]] = body.get("results") or []
    if len(results) != len(documents):
        return None
    scores = [0.0] * len(documents)
    for item in results:
        try:
            scores[int(item["index"])] = float(item["relevance_score"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    return scores
