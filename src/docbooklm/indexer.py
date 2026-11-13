"""Indicizzazione semantica in background.

L'upload non aspetta l'embedding: un libro da trecento pagine sono migliaia di
passaggi e qualche minuto di GPU. Il testo e' utilizzabile subito con BM25, il
denso si aggiunge strada facendo e la fonte espone l'avanzamento.

Un solo worker: cosi' due upload non si contendono la stessa GPU e il progresso
resta leggibile (una fonte alla volta).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from . import embed, vectors
from .config import Settings
from .store import Store

logger = logging.getLogger("docbooklm")

BATCH = 8  # passaggi per richiesta: ~2k token, sotto il contesto dei sidecar
CHAR_BUDGET = 6000  # caratteri per richiesta: limita i token e la latenza
FETCH = 64  # passaggi letti per giro: oltre non serve, si ripete

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_lock = threading.Lock()
_pending: set[str] = set()


def _pool() -> ThreadPoolExecutor:
    """Executor creato alla prima richiesta e ricreato dopo uno shutdown."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docbook-embed")
        return _executor


def _batches(
    items: list[dict[str, Any]], size: int = BATCH, budget: int = CHAR_BUDGET
) -> Iterable[list[dict[str, Any]]]:
    """Raggruppa per numero di passaggi E per caratteri.

    Il conteggio da solo non basta: otto passaggi lunghi superano il batch fisico
    del sidecar (``ub``) e llama-server risponde 500. Il budget di caratteri tiene
    ogni richiesta sotto quella soglia; un passaggio singolo piu' grande resta da
    solo, perche' il client lo tronca comunque.
    """
    batch: list[dict[str, Any]] = []
    used = 0
    for item in items:
        length = len(str(item.get("text") or ""))
        if batch and (len(batch) >= size or used + length > budget):
            yield batch
            batch = []
            used = 0
        batch.append(item)
        used += length
    if batch:
        yield batch


def _embed_batch(settings: Settings, texts: list[str], attempts: int = 3) -> np.ndarray:
    """Batch con qualche ritentativo: i primi secondi dopo l'avvio sono fragili."""
    failure: embed.EmbedError | None = None
    for attempt in range(attempts):
        try:
            return embed.embed_texts(settings, texts)
        except embed.EmbedError as error:
            failure = error
            if attempt < attempts - 1:
                time.sleep(1.0 + attempt)
    if failure is not None:
        raise failure
    raise embed.EmbedError("embedding non disponibile")


def embed_source(store: Store, settings: Settings, source_id: str) -> int:
    """Calcola i vettori mancanti di una fonte. Restituisce quanti ne ha scritti."""
    written = 0
    while True:
        # la fonte puo' essere stata eliminata mentre la GPU lavorava
        if store.source(source_id) is None:
            break
        pending = store.chunks_without_vectors(source_id, limit=FETCH)
        if not pending:
            break
        for batch in _batches(pending):
            texts = [str(item["text"]) for item in batch]
            try:
                matrix = _embed_batch(settings, texts)
            except embed.EmbedError as error:
                logger.warning("indicizzazione di %s interrotta: %s", source_id, error)
                return written
            items = [
                (int(item["id"]), vectors.pack(matrix[index]), int(matrix.shape[1]))
                for index, item in enumerate(batch)
            ]
            store.add_vectors(source_id, items)
            written += len(items)
    if written:
        vectors.index_for(store).invalidate(source_id)
        logger.info("fonte %s: %s passaggi indicizzati", source_id, written)
    return written


def _job(store: Store, settings: Settings, source_id: str) -> None:
    try:
        embed_source(store, settings, source_id)
    except Exception:  # pragma: no cover - il job non deve morire in silenzio
        logger.exception("indicizzazione di %s fallita", source_id)
    finally:
        with _lock:
            _pending.discard(source_id)


def submit(store: Store, settings: Settings, source_id: str) -> bool:
    """Mette in coda una fonte; False se il retrieval denso e' spento."""
    if not settings.embed_enabled:
        return False
    with _lock:
        if source_id in _pending:
            return True
        _pending.add(source_id)
    _pool().submit(_job, store, settings, source_id)
    return True


def is_pending(source_id: str) -> bool:
    with _lock:
        return source_id in _pending


def backfill(store: Store, settings: Settings, limit: int = 50) -> int:
    """Indicizza le fonti rimaste senza vettori (avvio o vecchi database)."""
    if not settings.embed_enabled or not embed.embeddings_ready(settings):
        return 0
    queued = 0
    for source_id in store.sources_without_vectors(limit=limit):
        if submit(store, settings, source_id):
            queued += 1
    if queued:
        logger.info("indicizzazione in coda per %s fonti", queued)
    return queued


def shutdown() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
    with _lock:
        _pending.clear()
