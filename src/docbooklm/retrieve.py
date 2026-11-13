"""Selezione dei passaggi da passare al modello.

Oggi: BM25 su FTS5 con prefisso sulle parole italiane, quota per fonte e
riempimento con l'inizio di ogni fonte (le domande generiche come "riassumi"
non hanno parole chiave e senza questo riempimento resterebbero senza contesto).
Il retrieval denso e il rerank si innestano qui, in F2.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .store import Store

MAX_PASSAGES = 10
PER_SOURCE = 3

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


def _key(store_question: str) -> str:  # pragma: no cover - solo chiarezza
    return store_question


def select(store: Store, source_ids: list[str], question: str) -> list[dict[str, Any]]:
    """Passaggi numerati pronti per il prompt."""
    if not source_ids:
        return []

    selected: list[dict[str, Any]] = []
    used: set[int] = set()
    per_source: dict[str, int] = {source_id: 0 for source_id in source_ids}

    query = fts_query(question)
    if query and not is_generic(question):
        for hit in store.search(source_ids, query, limit=MAX_PASSAGES * 4):
            if len(selected) >= MAX_PASSAGES:
                break
            source_id = str(hit["source_id"])
            if per_source.get(source_id, 0) >= PER_SOURCE:
                continue
            if int(hit["id"]) in used:
                continue
            used.add(int(hit["id"]))
            per_source[source_id] = per_source.get(source_id, 0) + 1
            selected.append(hit)

    # Ogni fonte selezionata contribuisce almeno con il suo inizio: e' il
    # contesto che rende sensata una domanda generica o una citazione isolata.
    for source_id in source_ids:
        if len(selected) >= MAX_PASSAGES:
            break
        if per_source.get(source_id, 0) > 0:
            continue
        for head in store.head_chunks(source_id, limit=2):
            if int(head["id"]) in used:
                continue
            used.add(int(head["id"]))
            per_source[source_id] = per_source.get(source_id, 0) + 1
            selected.append(head)
            break

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
