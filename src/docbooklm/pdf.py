"""Esportazione in PDF di risposte e note.

Il PDF deve somigliare a quello che si vede nella chat: titoli, elenchi,
grassetto, citazioni e **tabelle vere**, non righe appiattite. Nessun font da
installare: i base-14 (Helvetica, Courier) sono dentro ogni lettore PDF e la
codifica cp1252 copre l'italiano. Quello che cp1252 non ha (emoji, frecce) viene
sostituito o tolto, altrimenti fpdf si ferma a meta' documento.
"""

from __future__ import annotations

import contextlib
import re
import time
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import TableBordersLayout
from fpdf.fonts import FontFace

PAGE_WIDTH = 210.0
MARGIN_X = 20.0
MARGIN_TOP = 18.0
MARGIN_BOTTOM = 22.0

BODY_SIZE = 10.5
LEADING = 5.4
TABLE_SIZE = 9.0
TABLE_LEADING = 4.8

TEXT = (58, 58, 55)
MUTED = (106, 106, 101)
RULE = (200, 200, 194)
CODE_FILL = (244, 244, 242)

MAX_EXPORTS = 200
MAX_AGE_S = 7 * 24 * 3600

# simboli frequenti che cp1252 non contiene
_SWAPS = {
    "\u2192": "->",
    "\u2190": "<-",
    "\u2191": "^",
    "\u2193": "v",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u2248": "~",
    "\u00d7": "x",
    "\u00a0": " ",
    "\u200b": "",
    "\t": "    ",
}

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_NUMBERED = re.compile(r"^(\d{1,3})[.)]\s+(.*)$")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
# riga di separazione di una tabella: solo |, -, : e spazi, con almeno un -
_TABLE_SEP = re.compile(r"^[\s|:-]+$")
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# i modelli a volte scrivono HTML dentro il markdown (tipico: <br> nelle celle)
_HTML_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_BOLD = re.compile(r"</?(?:b|strong)>", re.IGNORECASE)
_HTML_ITALIC = re.compile(r"</?(?:i|em)>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def clean(text: str) -> str:
    """Testo scrivibile con cp1252: il resto viene sostituito o scartato."""
    out: list[str] = []
    for char in text:
        replacement = _SWAPS.get(char)
        if replacement is not None:
            out.append(replacement)
            continue
        try:
            char.encode("cp1252")
        except UnicodeEncodeError:
            continue
        out.append(char)
    return "".join(out)


def _inline(text: str) -> str:
    """Markdown in linea come lo legge fpdf: ``*x*`` diventa corsivo, i link
    mostrano anche l'indirizzo (in un PDF non si clicca) e i tag HTML che i
    modelli infilano nel markdown diventano testo o a capo."""
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_BOLD.sub("**", text)
    text = _HTML_ITALIC.sub("__", text)
    text = _HTML_TAG.sub("", text)
    text = _LINK.sub(r"\1 (\2)", text)
    text = _ITALIC.sub(r"__\1__", text)
    return text.replace("`", "")


@dataclass
class Block:
    """Un pezzo di documento, gia' classificato."""

    kind: str
    text: str = ""
    level: int = 0
    rows: list[list[str]] = field(default_factory=list)
    aligns: list[str] = field(default_factory=list)
    header: bool = False


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and "-" in stripped and bool(_TABLE_SEP.match(stripped))


def _alignments(separator: str, columns: int) -> list[str]:
    cells = _split_row(separator)
    aligns: list[str] = []
    for index in range(columns):
        cell = cells[index] if index < len(cells) else "---"
        if cell.startswith(":") and cell.endswith(":"):
            aligns.append("CENTER")
        elif cell.endswith(":"):
            aligns.append("RIGHT")
        else:
            aligns.append("LEFT")
    return aligns


def _blocks(markdown: str) -> list[Block]:
    """Blocchi del markdown: titoli, elenchi, citazioni, codice, tabelle."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []
    code: list[str] | None = None

    def flush() -> None:
        if not paragraph:
            return
        text = " ".join(part.strip() for part in paragraph).strip()
        paragraph.clear()
        if text:
            blocks.append(Block("p", text))

    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.rstrip()
        stripped = line.strip()

        if code is not None:
            if stripped.startswith("```"):
                blocks.append(Block("code", "\n".join(code)))
                code = None
            else:
                code.append(raw)
            index += 1
            continue

        if stripped.startswith("```"):
            flush()
            code = []
            index += 1
            continue
        if not stripped:
            flush()
            index += 1
            continue
        if _RULE.match(stripped):
            flush()
            blocks.append(Block("rule"))
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush()
            blocks.append(Block("h", heading.group(2).strip(), len(heading.group(1))))
            index += 1
            continue

        # tabella: serve la riga di separazione, come nel markdown della chat
        if (
            "|" in stripped
            and index + 1 < len(lines)
            and _is_separator(lines[index + 1])
        ):
            flush()
            separator = lines[index + 1]
            raw_rows = [_split_row(stripped)]
            index += 2
            while index < len(lines) and "|" in lines[index]:
                if _is_separator(lines[index]):
                    index += 1
                    continue
                raw_rows.append(_split_row(lines[index]))
                index += 1
            columns = max(len(row) for row in raw_rows)
            rows = [(row + [""] * columns)[:columns] for row in raw_rows]
            blocks.append(
                Block("table", rows=rows, aligns=_alignments(separator, columns), header=True)
            )
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            flush()
            indent = len(line) - len(line.lstrip())
            body = bullet.group(1).strip()
            task = _TASK.match(body)
            if task:
                # come nella chat: pallino e poi "[x]" nel testo
                tick = "x" if task.group(1).lower() == "x" else " "
                body = f"[{tick}] {task.group(2).strip()}"
            blocks.append(Block("bullet", body, indent // 2))
            index += 1
            continue

        numbered = _NUMBERED.match(stripped)
        if numbered:
            flush()
            indent = len(line) - len(line.lstrip())
            blocks.append(
                Block("number", numbered.group(2).strip(), indent // 2, aligns=[numbered.group(1)])
            )
            index += 1
            continue

        if stripped.startswith(">"):
            flush()
            blocks.append(Block("quote", stripped.lstrip(">").strip()))
            index += 1
            continue

        paragraph.append(stripped)
        index += 1

    if code is not None:
        blocks.append(Block("code", "\n".join(code)))
    flush()
    return blocks


class _Sheet(FPDF):
    def __init__(self, footer: str) -> None:
        super().__init__(format="A4", unit="mm")
        # i base-14 accettano solo cp1252: con latin-1 "—" e "…" farebbero errore
        self.core_fonts_encoding = "cp1252"
        self.footer_text = footer
        self.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
        self.set_auto_page_break(True, margin=MARGIN_BOTTOM)
        self.set_text_color(*TEXT)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        width = (PAGE_WIDTH - 2 * MARGIN_X) / 2
        self.cell(width, 5, self.footer_text, align="L")
        self.cell(width, 5, f"{self.page_no()} / {{nb}}", align="R")
        self.set_text_color(*TEXT)


def _title_block(doc: _Sheet, title: str, subtitle: str) -> None:
    doc.set_font("Helvetica", "B", 18)
    doc.multi_cell(0, 8, clean(title), new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        doc.ln(1)
        doc.set_font("Helvetica", "", 9)
        doc.set_text_color(*MUTED)
        doc.multi_cell(0, 5, clean(subtitle), new_x="LMARGIN", new_y="NEXT")
        doc.set_text_color(*TEXT)
    doc.ln(3)
    doc.set_draw_color(*RULE)
    doc.set_line_width(0.3)
    y = doc.get_y()
    doc.line(MARGIN_X, y, PAGE_WIDTH - MARGIN_X, y)
    doc.ln(6)


def _heading(doc: _Sheet, text: str, level: int) -> None:
    size = {1: 15.0, 2: 13.0, 3: 11.5, 4: 10.5}.get(level, 10.5)
    doc.ln(3 if level <= 2 else 2)
    doc.set_font("Helvetica", "B", size)
    doc.multi_cell(0, size * 0.55, _inline(clean(text)), markdown=True, new_x="LMARGIN", new_y="NEXT")
    doc.ln(1.2)


def _table(doc: _Sheet, block: Block) -> None:
    """Tabella vera: colonne, intestazione in grassetto, bordi leggeri.

    Con ``repeat_headings`` l'intestazione ricompare a ogni pagina: una tabella
    di dieci righe spezzata a meta' resta leggibile.
    """
    if not block.rows:
        return
    columns = len(block.rows[0])
    aligns = tuple(block.aligns or ["LEFT"] * columns)
    # con molte colonne il testo va stretto: un punto in meno evita di spezzare
    # le parole a meta' e tiene la tabella dentro il foglio
    size = 8.0 if columns >= 6 else TABLE_SIZE
    leading = 4.4 if columns >= 6 else TABLE_LEADING
    padding = (1.4, 1.2) if columns >= 6 else (1.8, 1.6)
    doc.ln(1.5)
    doc.set_font("Helvetica", "", size)
    doc.set_draw_color(*RULE)
    doc.set_line_width(0.2)
    with doc.table(
        width=PAGE_WIDTH - 2 * MARGIN_X,
        text_align=aligns,
        v_align="MIDDLE",
        first_row_as_headings=block.header,
        borders_layout=TableBordersLayout.ALL,
        headings_style=FontFace(emphasis="BOLD"),
        line_height=leading,
        padding=padding,
        markdown=True,
        repeat_headings=1 if block.header else 0,
    ) as table:
        for values in block.rows:
            row = table.row()
            for value in values:
                row.cell(_inline(clean(value)))
    doc.ln(3)


def _list_item(doc: _Sheet, block: Block) -> None:
    """Elenco con rientro: le righe a capo restano allineate al testo, non al
    pallino (prima ripartivano dal margine e sembravano un altro paragrafo)."""
    if block.kind == "bullet":
        marker = "•"
    else:
        number = block.aligns[0] if block.aligns else "1"
        marker = f"{number}."

    indent = 6.0 * (block.level + 1)
    doc.set_x(MARGIN_X + indent)
    doc.set_font("Helvetica", "", BODY_SIZE)
    label_width = doc.get_string_width(marker) + 2.6
    doc.cell(label_width, LEADING, marker)
    doc.multi_cell(
        0,
        LEADING,
        _inline(clean(block.text)),
        markdown=True,
        new_x="LMARGIN",
        new_y="NEXT",
    )
    doc.ln(0.6)


def _body_block(doc: _Sheet, block: Block) -> None:
    if block.kind == "h":
        _heading(doc, block.text, block.level)
        return

    if block.kind == "rule":
        doc.ln(2)
        doc.set_draw_color(*RULE)
        y = doc.get_y()
        doc.line(MARGIN_X, y, PAGE_WIDTH - MARGIN_X, y)
        doc.ln(4)
        return

    if block.kind == "code":
        doc.set_font("Courier", "", 8.5)
        doc.set_fill_color(*CODE_FILL)
        doc.set_x(MARGIN_X + 2)
        doc.multi_cell(
            PAGE_WIDTH - 2 * MARGIN_X - 4,
            4.6,
            clean(block.text) or " ",
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        doc.ln(2.5)
        return

    if block.kind == "quote":
        doc.set_x(MARGIN_X + 6)
        doc.set_font("Helvetica", "I", 10)
        doc.set_text_color(*MUTED)
        doc.multi_cell(
            PAGE_WIDTH - 2 * MARGIN_X - 6,
            LEADING,
            clean(_inline(block.text)),
            markdown=False,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        doc.set_text_color(*TEXT)
        doc.ln(1.5)
        return

    if block.kind == "table":
        _table(doc, block)
        return

    if block.kind in {"bullet", "number"}:
        _list_item(doc, block)
        return

    doc.set_font("Helvetica", "", BODY_SIZE)
    doc.multi_cell(
        0, LEADING, _inline(clean(block.text)), markdown=True, new_x="LMARGIN", new_y="NEXT"
    )
    doc.ln(2.2)


def _citations(doc: _Sheet, citations: Iterable[dict[str, Any]]) -> None:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for citation in citations:
        key = (
            str(citation.get("source_title") or ""),
            int(citation.get("page") or 0),
            str(citation.get("quote") or "")[:60],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
    if not unique:
        return

    doc.ln(6)
    doc.set_font("Helvetica", "B", 12)
    doc.multi_cell(0, 6, "Fonti citate", new_x="LMARGIN", new_y="NEXT")
    doc.ln(1)
    for citation in unique:
        label = str(citation.get("source_title") or "fonte")
        page = citation.get("page")
        if page:
            label = f"{label}, pagina {page}"
        doc.set_font("Helvetica", "B", 9.5)
        doc.multi_cell(0, 5, clean(label), new_x="LMARGIN", new_y="NEXT")
        quote = str(citation.get("quote") or "").strip()
        if quote:
            doc.set_font("Helvetica", "I", 9)
            doc.set_text_color(*MUTED)
            doc.multi_cell(
                0, 4.8, clean(quote[:300]), markdown=False, new_x="LMARGIN", new_y="NEXT"
            )
            doc.set_text_color(*TEXT)
        doc.ln(2)


def render(
    title: str,
    markdown: str,
    *,
    subtitle: str = "",
    footer: str = "DocBooK LM",
    citations: Iterable[dict[str, Any]] | None = None,
) -> bytes:
    """Il PDF come bytes, senza toccare il disco: usato anche dai test."""
    doc = _Sheet(clean(footer))
    doc.set_title(clean(title))
    doc.set_author("DocBooK LM")
    doc.set_creator("DocBooK LM")
    doc.alias_nb_pages()
    doc.add_page()

    _title_block(doc, title, subtitle)
    for block in _blocks(markdown):
        _body_block(doc, block)
    if citations:
        _citations(doc, citations)
    return bytes(doc.output())


def slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return value[:48] or "documento"


def prune(directory: Path) -> None:
    """Tiene la cartella leggibile: 200 file al massimo, una settimana di vita."""
    try:
        files = sorted(
            directory.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True
        )
    except OSError:
        return
    now = time.time()
    for index, path in enumerate(files):
        try:
            expired = now - path.stat().st_mtime > MAX_AGE_S
        except OSError:
            continue
        if index < MAX_EXPORTS and not expired:
            continue
        with contextlib.suppress(OSError):
            path.unlink()


def write(
    directory: Path,
    *,
    title: str,
    markdown: str,
    subtitle: str = "",
    citations: Iterable[dict[str, Any]] | None = None,
) -> Path:
    """Crea il file nella cartella delle esportazioni e ne restituisce il percorso."""
    directory.mkdir(parents=True, exist_ok=True)
    prune(directory)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{slug(title)}-{stamp}-{uuid.uuid4().hex[:4]}.pdf"
    target = directory / name
    target.write_bytes(render(title, markdown, subtitle=subtitle, citations=citations))
    return target
