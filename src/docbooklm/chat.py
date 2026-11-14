"""Costruzione del prompt e verifica delle citazioni.

La regola e' semplice: una citazione resta solo se la frase che la porta
condivide almeno una parola di contenuto con il passaggio citato. Le citazioni
inventate vengono rimosse dal testo invece di essere mostrate come se fossero
supportate.
"""

from __future__ import annotations

import re
from typing import Any

from .retrieve import STOPWORDS, strip_accents

SYSTEM_PROMPT = """Sei DocBooK LM, un assistente che risponde esclusivamente sulla base dei \
passaggi numerati forniti dall'utente.

Regole:
1. Rispondi in italiano, in modo diretto e concreto.
2. Ogni affermazione che viene dai passaggi termina con il numero del passaggio tra parentesi \
quadre, per esempio [2]. Puoi citare piu' passaggi insieme: [1][4].
3. Usa solo i numeri presenti nell'elenco. Non inventare numeri e non citare passaggi che non \
esistono.
4. Se i passaggi non bastano a rispondere, dillo in una frase e indica cosa manca.
5. Non scrivere "secondo il documento" o "in base alle fonti": metti soltanto la citazione.
6. Non ripetere l'elenco dei passaggi e non riportare i numeri in una nota finale.
7. Quando servono tabelle, elenchi, sezioni o un ordine preciso, usa markdown semplice: tabelle con | e la riga di separazione, elenchi con - o 1., titoli con #. La stessa impaginazione viene riprodotta nel PDF esportato."""

_CITE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_WORD = re.compile(r"[0-9]+|[^\W\d_]{4,}", re.UNICODE)
_LIMIT_QUOTE = 260


def build_context(passages: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for passage in passages:
        where = f"fonte: {passage['source_title']}"
        if passage.get("page"):
            where += f", pagina {passage['page']}"
        if passage.get("section"):
            where += f", sezione: {passage['section']}"
        blocks.append(f"[{passage['n']}] ({where})\n{passage['text'].strip()}")
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    passages: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        messages.append({"role": turn["role"], "content": turn["text"]})
    context = build_context(passages)
    messages.append(
        {
            "role": "user",
            "content": f"Passaggi disponibili:\n\n{context}\n\nDomanda: {question}",
        }
    )
    return messages


def _content_words(text: str) -> set[str]:
    words = {match.group(0) for match in _WORD.finditer(strip_accents(text.casefold()))}
    return {word for word in words if word not in STOPWORDS}


def _sentence_around(text: str, position: int) -> str:
    """La frase che contiene ``position``.

    Dopo un a capo il testo riprende dal carattere successivo, non due: con
    ``+2`` la prima parola perdeva una lettera e, se era l'unica in comune con
    il passaggio, la citazione veniva scartata come se fosse inventata.
    """
    start = 0
    dot = text.rfind(". ", 0, position)
    if dot >= 0:
        start = max(start, dot + 2)
    newline = text.rfind("\n", 0, position)
    if newline >= 0:
        start = max(start, newline + 1)
    ends = [index for index in (text.find(". ", position), text.find("\n", position)) if index > 0]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end]


def _best_quote(chunk_text: str, sentence: str) -> str:
    wanted = _content_words(sentence)
    best = ""
    best_score = 0
    for candidate in _SENTENCE.finditer(chunk_text):
        piece = candidate.group(0).strip()
        if len(piece) < 12:
            continue
        score = len(wanted & _content_words(piece))
        if score > best_score:
            best, best_score = piece, score
    if not best:
        best = chunk_text.strip()
    return best[: _LIMIT_QUOTE + 1].strip()


def verify(answer: str, passages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Rimuove le citazioni non supportate e restituisce quelle verificate."""
    by_number = {int(passage["n"]): passage for passage in passages}
    citations: list[dict[str, Any]] = []
    out: list[str] = []
    last = 0

    for match in _CITE.finditer(answer):
        out.append(answer[last : match.start()])
        last = match.end()
        numbers = [int(part) for part in re.split(r"[,;]", match.group(1)) if part.strip()]
        sentence = _sentence_around(answer, match.start())
        sentence_words = _content_words(sentence)
        kept: list[int] = []
        for number in numbers:
            passage = by_number.get(number)
            if passage is None:
                continue
            if not sentence_words & _content_words(str(passage["text"])):
                continue
            kept.append(number)
            quote = _best_quote(str(passage["text"]), sentence)
            entry = {
                "n": number,
                "source_id": passage["source_id"],
                "source_title": passage["source_title"],
                "chunk_id": passage["chunk_id"],
                "page": passage["page"],
                "quote": quote,
            }
            if not any(
                item["chunk_id"] == entry["chunk_id"] and item["quote"] == entry["quote"]
                for item in citations
            ):
                citations.append(entry)
        if kept:
            out.append("".join(f"[{number}]" for number in kept))

    out.append(answer[last:])
    text = "".join(out)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)

    for citation in citations:
        passage = by_number[citation["n"]]
        if not citation["page"]:
            citation["page"] = int(passage.get("page") or 0)
    citations.sort(key=lambda item: item["n"])
    return text.strip(), citations
