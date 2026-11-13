"""Selezione dei passaggi da passare al modello.

Tre stadi, ognuno utilizza il precedente:

1. **lessicale** — BM25 su FTS5, prefisso e accenti rimossi: trova i termini
   esatti, i nomi propri, i numeri;
2. **denso** — bge-m3 su sidecar: trova il senso, anche con parole diverse
   ("quanta memoria video" contro "sedici gigabyte di VRAM");
3. **fusione e rerank** — Reciprocal Rank Fusion delle due liste, poi il
   cross-encoder riordina i migliori candidati guardando domanda e passaggio
   insieme.

Se i sidecar non rispondono lo stadio denso non esiste e restano BM25 piu' il
riempimento con l'inizio di ogni fonte: la chat continua a funzionare.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from . import embed, vectors
from .config import Settings
from .store import Store

MAX_PASSAGES = 16  # tetto assoluto: oltre, il prefill diventa inaccettabile
# Il vero limite e' il contesto, non il numero: 32.000 caratteri sono ~8.000
# token, cioe' una trentina di secondi di prefill sulla Vega. Con passaggi
# corti (bolle, fatture) entrano tutti; con i capitoli di un libro ne bastano
# otto o nove, come prima.
CONTEXT_CHARS = 32000
LEXICAL_LIMIT = 60
DENSE_LIMIT = 60
RERANK_CANDIDATES = 14
RERANK_CHARS = 700  # estratto per candidato: ~175 token, ~0,8 s sul reranker
MIN_PER_SOURCE = 3
RRF_K = 60

_TOKEN = re.compile(r"[0-9]+|[^\W\d_]{3,}", re.UNICODE)

STOPWORDS = {
    "che", "chi", "cui", "del", "della", "delle", "dei", "degli", "dello", "con", "per",
    "tra", "fra", "gli", "lui", "lei", "loro", "come", "cosa", "quale", "quali", "quando",
    "dove", "perche", "sono", "essere", "avere", "hanno", "viene", "vengono", "questo",
    "questa", "questi", "queste", "quello", "quella", "anche", "piu", "meno", "molto",
    "tutto", "tutti", "tutte", "sulla", "sulle", "sullo", "sugli", "dalla", "dalle",
    "dallo", "dagli", "nelle", "nella", "nello", "negli", "alla", "alle", "allo", "agli",
    "una", "uno", "qual", "nel", "nell", "sul", "dall", "dell", "sull",
    "the", "and", "for", "what", "does", "with", "from", "this", "that", "these", "those",
    "are", "was", "were", "how", "why", "when", "which", "you",
}

GENERIC = {
    "riassumi", "riassunto", "sintetizza", "sintesi", "spiega", "descrivi", "elenco",
    "parlami", "contiene", "contenuto", "fonti", "documento", "documenti", "testo",
    "generale", "overview", "panoramica", "summary", "riassumere", "principali",
}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def terms(text: str) -> list[str]:
    """Parole utili alla ricerca, senza duplicati e senza parole vuote."""
    seen: set[str] = set()
    result: list[str] = []
    for match in _TOKEN.finditer(strip_accents(text.casefold())):
        word = match.group(0)
        if word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        result.append(word)
    return result


def fts_query(text: str, limit: int = 12) -> str:
    words = terms(text)[:limit]
    if not words:
        return ""
    return " OR ".join(f'"{word}"*' for word in words)


def is_generic(question: str) -> bool:
    words = terms(question)
    if not words:
        return True
    return all(word in GENERIC for word in words)


def fair_share(source_count: int) -> int:
    """Quanti passaggi meriterebbe ogni fonte: con una sola fonte si prende tutto."""
    if source_count <= 0:
        return MIN_PER_SOURCE
    return max(MIN_PER_SOURCE, math.ceil(MAX_PASSAGES / source_count))


def fuse(ranked: list[list[int]], limit: int) -> list[int]:
    """Reciprocal Rank Fusion: ogni lista contribuisce con 1/(k + posizione)."""
    scores: dict[int, float] = {}
    for ranking in ranked:
        for position, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position + 1)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [chunk_id for chunk_id, _ in ordered[:limit]]


def _dense_ids(store: Store, settings: Settings | None, source_ids: list[str], question: str) -> list[int]:
    if settings is None:
        return []
    query = embed.embed_query(settings, question)
    if query is None:
        return []
    hits = vectors.index_for(store).search(source_ids, query, limit=DENSE_LIMIT)
    return [int(hit["chunk_id"]) for hit in hits]


def excerpt(text: str, question: str, size: int = RERANK_CHARS) -> str:
    """La parte del passaggio che parla della domanda.

    Il cross-encoder costa in proporzione ai token: su passaggi da ~850 token
    ripassarli interi costerebbe secondi. Si manda la finestra che contiene piu'
    parole della domanda (o l'inizio, se nessuna compare, come per una parafrasi
    pura).
    """
    if len(text) <= size:
        return text
    words = terms(question)[:10]
    if not words:
        return text[:size]
    lowered = text.casefold()
    step = max(1, size // 4)
    best_start, best_hits = 0, 0
    for start in range(0, len(text) - size + 1, step):
        window = lowered[start : start + size]
        hits = sum(1 for word in words if word in window)
        if hits > best_hits:
            best_start, best_hits = start, hits
    return text[best_start : best_start + size]


def _heads(store: Store, source_ids: list[str], selected: list[dict[str, Any]]) -> None:
    """Riempimento con l'inizio di ogni fonte ancora assente.

    Serve alle domande generiche ("riassumi"), che non hanno parole chiave: senza
    questo il contesto resterebbe vuoto.
    """
    seen = {int(item["id"]) for item in selected}
    for source_id in source_ids:
        if len(selected) >= MAX_PASSAGES:
            break
        if any(str(item["source_id"]) == source_id for item in selected):
            continue
        for head in store.head_chunks(source_id, limit=2):
            if int(head["id"]) in seen:
                continue
            seen.add(int(head["id"]))
            selected.append(head)
            break


def select(
    store: Store,
    source_ids: list[str],
    question: str,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Passaggi numerati pronti per il prompt."""
    if not source_ids:
        return []

    lexical = []
    if not is_generic(question):
        query = fts_query(question)
        if query:
            lexical = [
                int(hit["id"])
                for hit in store.search(source_ids, query, limit=LEXICAL_LIMIT)
            ]

    dense = _dense_ids(store, settings, source_ids, question)

    candidates = fuse([lexical, dense], RERANK_CANDIDATES) if (lexical or dense) else []
    rows = {int(row["id"]): row for row in store.chunks_by_ids(candidates)}

    ordered = [rows[chunk_id] for chunk_id in candidates if chunk_id in rows]
    # Il rerank serve a scegliere *quali* passaggi entrano: se entrano tutti nel
    # contesto, e' solo latenza in piu'.
    if settings is not None and sum(len(str(row["text"])) for row in ordered) > CONTEXT_CHARS:
        scores = embed.rerank(
            settings, question, [excerpt(str(row["text"]), question) for row in ordered]
        )
        if scores is not None:
            ordered = [
                row
                for _, row in sorted(
                    zip(scores, ordered, strict=True), key=lambda pair: -pair[0]
                )
            ]

    share = fair_share(len(source_ids))
    # Ogni fonte ha la sua fetta di contesto: cosi' una non mangia l'altra e il
    # prompt resta sotto CONTEXT_CHARS complessivi.
    budget = max(CONTEXT_CHARS // max(1, len(source_ids)), CONTEXT_CHARS // 4)
    per_source: dict[str, int] = {}
    chars: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for row in ordered:
        if len(selected) >= MAX_PASSAGES:
            break
        source_id = str(row["source_id"])
        count = per_source.get(source_id, 0)
        if count >= share:
            continue
        length = len(str(row["text"]))
        # i primi passaggi di ogni fonte entrano sempre: il contesto non deve
        # restare vuoto solo perche' i suoi passaggi sono lunghi
        if count >= MIN_PER_SOURCE and chars.get(source_id, 0) + length > budget:
            continue
        per_source[source_id] = count + 1
        chars[source_id] = chars.get(source_id, 0) + length
        selected.append(row)

    if len(selected) < MAX_PASSAGES:
        _heads(store, source_ids, selected)

    numbered: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        numbered.append(
            {
                "n": index,
                "source_id": str(item["source_id"]),
                "source_title": str(item.get("source_title") or ""),
                "chunk_id": int(item["id"]),
                "page": int(item.get("page") or 0),
                "section": str(item.get("section") or ""),
                "text": str(item["text"]),
            }
        )
    return numbered
