"""Word (.docx): paragrafi, titoli, elenchi e tabelle riga per riga."""

from __future__ import annotations

from pathlib import Path

import docx


def _table_rows(table: docx.table.Table) -> list[str]:
    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def extract(path: Path) -> list[tuple[int, str]]:
    document = docx.Document(str(path))
    lines: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name if paragraph.style is not None else "").lower()
        if "heading" in style or "titolo" in style:
            lines.append(text)
            lines.append("")
        else:
            lines.append(text)

    for table in document.tables:
        lines.append("")
        lines.extend(_table_rows(table))

    return [(1, "\n".join(lines))]
