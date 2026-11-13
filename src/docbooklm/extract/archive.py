"""Archivi ZIP: una fonte sola con i documenti che contengono.

Capita spesso di scaricare un lotto di PDF (bolle, fatture, scansioni) e di
ritrovarsi con un archivio. Aprirlo a mano e ricaricare i file uno per uno
rompe il flusso: qui l'archivio diventa una fonte unica, con le pagine in
sequenza e il nome di ogni documento come sezione dei suoi passaggi.

I singoli file illeggibili vengono saltati (una scansione rotta non deve
buttare via le altre); se non se ne salva nessuno, l'errore e' esplicito.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger("docbooklm")

MAX_MEMBERS = 200
MAX_UNPACKED_BYTES = 400 * 1024 * 1024
_JUNK = (".DS_Store", "Thumbs.db")


def looks_like_zip(data: bytes) -> bool:
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06")


def _usable(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    if info.is_dir() or name.startswith("__MACOSX/"):
        return False
    base = name.rsplit("/", 1)[-1]
    return bool(base) and not base.startswith(".") and base not in _JUNK


def _kind_of(kinds: set[str]) -> str:
    """Tipo della fonte: quello dei documenti, se sono tutti uguali."""
    kinds.discard("binary")
    if len(kinds) == 1:
        return kinds.pop()
    return "text"


def extract(path: Path, *, ocr_enabled: bool = True) -> tuple[str, list[tuple[int, str]]]:
    """Restituisce (tipo, pagine) dell'archivio. Solleva ExtractionError."""
    from . import ExtractionError, extract_file, suffix_for  # import locale

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise ExtractionError("archivio non leggibile") from error

    pages: list[tuple[int, str]] = []
    kinds: set[str] = set()
    failure: Exception | None = None
    unpacked = 0

    with archive, tempfile.TemporaryDirectory(dir=path.parent) as work:
        infos = sorted(
            (info for info in archive.infolist() if _usable(info)),
            key=lambda item: item.filename,
        )[:MAX_MEMBERS]
        if not infos:
            raise ExtractionError("archivio vuoto: nessun documento leggibile")
        for index, info in enumerate(infos):
            member = Path(info.filename).name
            data = archive.read(info)
            unpacked += len(data)
            if unpacked > MAX_UNPACKED_BYTES:
                raise ExtractionError("archivio troppo grande una volta aperto")
            suffix = suffix_for(member, data)
            if not suffix:
                logger.warning("archivio: formato non riconosciuto per %s", member)
                failure = failure or ExtractionError(f"formato non supportato: {member}")
                continue
            target = Path(work) / f"{index:03d}{suffix}"
            target.write_bytes(data)
            try:
                inner_kind, inner = extract_file(target, ocr_enabled=ocr_enabled)
            except ExtractionError as error:
                logger.warning("archivio: salto %s (%s)", member, error)
                failure = failure or error
                continue
            if not inner:
                continue
            kinds.add(inner_kind)
            # Il nome del documento apre la sua prima pagina, chiuso da un punto:
            # cosi' resta **testo** (la riga senza punteggiatura verrebbe presa per
            # un titolo e sparirebbe dal passaggio) e il modello puo' citare la
            # bolla o la fattura per nome.
            offset = pages[-1][0] if pages else 0
            _, first_text = inner[0]
            stem = Path(member).stem.strip()
            opening = f"{stem}.\n{first_text}" if stem else first_text
            pages.append((offset + 1, opening))
            for number, text in inner[1:]:
                pages.append((offset + number, text))

    if not pages:
        raise ExtractionError(str(failure) if failure else "nessun testo negli allegati")
    return _kind_of(kinds), pages
