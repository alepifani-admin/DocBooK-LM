"""Geometria di una citazione: dove si trova la frase dentro la pagina PDF.

Il visualizzatore disegna i rettangoli restituiti qui sopra l'immagine della
pagina, quindi le coordinate sono normalizzate (0-1, origine in alto a sinistra).
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def _normalize(text: str) -> tuple[str, list[int]]:
    """Testo senza spazi doppi, ripiegato in minuscolo, con mappa sugli indici."""
    chars: list[str] = []
    mapping: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if previous_space:
                continue
            chars.append(" ")
            mapping.append(index)
            previous_space = True
            continue
        chars.append(char.lower())
        mapping.append(index)
        previous_space = False
    return "".join(chars), mapping


def locate(path: Path, page_number: int, quote: str) -> dict[str, object]:
    """Rettangoli della citazione nella pagina, o lista vuota se non la trova."""
    quote = (quote or "").strip()
    needle = _normalize(quote)[0]
    if not quote or not needle:
        return {"found": False, "boxes": []}

    document = pdfium.PdfDocument(str(path))
    try:
        index = max(0, min(page_number - 1, len(document) - 1))
        page = document[index]
        try:
            textpage = page.get_textpage()
            width, height = page.get_size()
            text = textpage.get_text_range()
            normalized, mapping = _normalize(text)
            position = normalized.find(needle)
            if position < 0 or width <= 0 or height <= 0:
                return {"found": False, "boxes": []}
            start = mapping[position]
            end = mapping[min(position + len(needle) - 1, len(mapping) - 1)]

            char_boxes: list[tuple[float, float, float, float]] = []
            for char_index in range(start, end + 1):
                left, bottom, right, top = textpage.get_charbox(char_index)
                if right - left <= 0 or top - bottom <= 0:
                    continue
                char_boxes.append((left, bottom, right, top))
        finally:
            page.close()
    finally:
        document.close()

    boxes = _merge_lines(char_boxes, width, height)
    return {"found": bool(boxes), "boxes": boxes}


def _merge_lines(
    boxes: list[tuple[float, float, float, float]], width: float, height: float
) -> list[list[float]]:
    """Unisce i caratteri in una riga sola per riga di testo."""
    if not boxes:
        return []
    boxes.sort(key=lambda box: (-box[3], box[0]))
    lines: list[list[float]] = []
    for left, bottom, right, top in boxes:
        target = None
        for line in lines:
            line_top, line_bottom = line[1] + line[3], line[1]
            if min(top, line_top) - max(bottom, line_bottom) > 0.5 * min(
                top - bottom, line_top - line_bottom
            ):
                target = line
                break
        if target is None:
            lines.append([left, bottom, right - left, top - bottom])
            continue
        target[0] = min(target[0], left)
        target[2] = max(target[0] + target[2], right) - target[0]
        new_bottom = min(target[1], bottom)
        target[3] = max(target[1] + target[3], top) - new_bottom
        target[1] = new_bottom

    result: list[list[float]] = []
    for left, bottom, box_width, box_height in lines:
        result.append(
            [
                round(left / width, 5),
                round(1 - (bottom + box_height) / height, 5),
                round(box_width / width, 5),
                round(box_height / height, 5),
            ]
        )
    return result
