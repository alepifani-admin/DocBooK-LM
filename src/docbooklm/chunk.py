"""Chunking strutturato: blocchi -> passaggi con pagina, sezione e stima dei token.

Un passaggio non attraversa mai il confine di pagina o di sezione: e' quello che
permette alla citazione di indicare "pagina 4" con precisione e al prompt di
conservare il titolo sotto cui il testo compare.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

TARGET_CHARS = 3400  # ~850 token a 4 caratteri per token
MIN_CHARS = 240
OVERLAP_CHARS = 420

_HEADING_MAX_WORDS = 12
_HEADING_MAX_CHARS = 78
_END_PUNCT = (".", ",", ";", ":", "!", "?", "…")
_NUMBERED = re.compile(r"^(\d+(\.\d+)*|[IVXLC]+\.)\s+\S")
_KEYWORDS = (
    "capitolo", "parte", "sezione", "sommario", "indice", "introduzione",
    "conclusione", "appendice", "allegato", "premessa", "prefazione", "glossario",
    "chapter", "section", "summary", "introduction", "conclusion", "appendix",
)


@dataclass
class Block:
    """Paragrafo o riga significativa, con la sua provenienza."""

    page: int
    section: str
    text: str


@dataclass
class Chunk:
    """Passaggio pronto per l'indice."""

    text: str
    page: int
    section: str
    n_tokens: int = 0
    parts: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def looks_like_heading(line: str) -> bool:
    """Euristica prudente: meglio perdere un titolo che spezzare una tabella.

    In italiano una riga di tabella ("Coding qualita Qwen3-Coder") ha le iniziali
    maiuscole esattamente come un titolo, quindi il maiuscolo da solo non basta:
    servono tutte maiuscole, una numerazione o una parola chiave di struttura.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _HEADING_MAX_CHARS:
        return False
    if stripped.endswith(_END_PUNCT):
        return False
    words = stripped.split()
    if len(words) > _HEADING_MAX_WORDS:
        return False
    if _NUMBERED.match(stripped):
        return True
    letters = [char for char in stripped if char.isalpha()]
    if letters and sum(1 for char in letters if char.isupper()) / len(letters) > 0.85:
        return len(words) <= 10
    first = words[0].casefold().strip(".,;:")
    return first in _KEYWORDS


def blocks_from_pages(pages: Iterable[tuple[int, str]]) -> list[Block]:
    blocks: list[Block] = []
    current_section = ""
    for page_number, page_text in pages:
        for raw in page_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if looks_like_heading(line):
                current_section = line
            # La riga resta nel testo anche quando apre una sezione: nei moduli e
            # nelle tabelle una riga in maiuscolo e' un dato ("DBR_DIREZIONE
            # REGIONALE PUGLIA"), e scartarla faceva sparire proprio cio' che
            # l'utente cerca. Il titolo nel passaggio aiuta anche l'embedding.
            blocks.append(Block(page=page_number, section=current_section, text=line))
    return blocks


def _flush(group: list[Block], section: str, page: int, chunks: list[Chunk]) -> list[Block]:
    """Chiude il gruppo corrente e restituisce la coda da riusare come overlap."""
    text = "\n".join(block.text for block in group).strip()
    if text:
        chunks.append(
            Chunk(
                text=text,
                page=page,
                section=section,
                n_tokens=estimate_tokens(text),
                parts=[block.text for block in group],
            )
        )
    tail: list[Block] = []
    budget = 0
    for block in reversed(group):
        budget += len(block.text) + 1
        if budget > OVERLAP_CHARS:
            break
        tail.insert(0, block)
    return tail


def _absorb(target: Chunk, extra: Chunk) -> None:
    """Fonde `extra` in `target`, saltando la coda di overlap gia' presente."""
    parts = list(target.parts)
    overlap = 0
    for size in range(min(len(parts), len(extra.parts)), 0, -1):
        if parts[-size:] == extra.parts[:size]:
            overlap = size
            break
    parts.extend(extra.parts[overlap:])
    target.parts = parts
    target.text = "\n".join(parts).strip()
    target.n_tokens = estimate_tokens(target.text)


def _merge_small(chunks: list[Chunk], min_chars: int = MIN_CHARS) -> list[Chunk]:
    """Unisce i frammenti minuscoli prodotti da moduli, tabelle ed etichette.

    Un PDF a colonne o un modulo produce righe che sembrano titoli ("P.IVA",
    "ABI/CAB") e spezzano il testo in passaggi da due parole: inutili sia per
    BM25 sia per l'embedding. Si fondono con il passaggio vicino della stessa
    pagina, mai attraverso una pagina (la citazione deve restare esatta).
    """
    merged: list[Chunk] = []
    for chunk in chunks:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.page == chunk.page
            and (len(previous.text) < min_chars or len(chunk.text) < min_chars)
            and len(previous.text) + len(chunk.text) <= TARGET_CHARS
        ):
            _absorb(previous, chunk)
        else:
            merged.append(chunk)
    return merged


def chunks_from_pages(pages: Iterable[tuple[int, str]]) -> list[Chunk]:
    """Costruisce i passaggi rispettando sezioni, pagine e dimensione target."""
    chunks: list[Chunk] = []
    group: list[Block] = []
    section = ""
    page = 0
    size = 0

    for block in blocks_from_pages(pages):
        if group and (block.section != section or block.page != page):
            _flush(group, section, page, chunks)
            group, size = [], 0
        elif group and size + len(block.text) > TARGET_CHARS:
            group = _flush(group, section, page, chunks)
            size = sum(len(item.text) + 1 for item in group)
        if not group:
            section, page = block.section, block.page
        group.append(block)
        size += len(block.text) + 1

    if group:
        _flush(group, section, page, chunks)
    return _merge_small(chunks)


def as_dicts(chunks: list[Chunk]) -> list[dict[str, Any]]:
    return [
        {"text": chunk.text, "page": chunk.page, "section": chunk.section,
         "n_tokens": chunk.n_tokens}
        for chunk in chunks
    ]
