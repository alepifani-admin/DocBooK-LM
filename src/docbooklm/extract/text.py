"""Testo semplice: markdown, codice, csv, html ripulito, rtf senza marcatori."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("docbooklm")

_TAG = re.compile(r"<[^>]+>")
_RTF_WORD = re.compile(r"\\[a-zA-Z]+-?\d* ?")
_NOISE = re.compile(
    r"<(script|style|nav|header|footer|aside|form|noscript|svg)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_BLOCK = re.compile(r"</(p|div|li|tr|h[1-6]|section|article)>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    text = _NOISE.sub(" ", html)
    text = _BR.sub("\n", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def rtf_to_text(raw: str) -> str:
    text = re.sub(r"\{[^{}]*\\\*[^{}]*\}", "", raw)
    text = _RTF_WORD.sub(" ", text)
    text = text.replace("{", "").replace("}", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract(path: Path) -> list[tuple[int, str]]:
    raw = _decode(path.read_bytes())
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm", ".xml"}:
        raw = html_to_text(raw)
    elif suffix == ".rtf":
        raw = rtf_to_text(raw)
    return [(1, raw)]
