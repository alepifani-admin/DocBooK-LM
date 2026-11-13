"""Ingestione di una fonte: salvataggio, estrazione, chunk e indice."""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from . import chunk as chunk_mod
from .config import Settings
from .extract import ExtractionError, extract_file, suffix_for
from .extract import web as web_ext
from .store import Store

logger = logging.getLogger("docbooklm")


class IngestError(RuntimeError):
    """Fonte rifiutata: formato, dimensione o contenuto non utilizzabile."""


def _title_from_name(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
    return stem or name


def _save(settings: Settings, source_id: str, suffix: str, data: bytes) -> Path:
    settings.files_dir.mkdir(parents=True, exist_ok=True)
    target = settings.files_dir / f"{source_id}{suffix}"
    target.write_bytes(data)
    return target


def _index(
    store: Store,
    source_id: str,
    pages: list[tuple[int, str]],
) -> int:
    chunks = chunk_mod.chunks_from_pages(pages)
    if not chunks:
        raise IngestError("il testo estratto e' troppo breve per essere indicizzato")
    store.add_chunks(source_id, chunk_mod.as_dicts(chunks))
    return sum(item.n_tokens for item in chunks)


def create_from_bytes(
    store: Store,
    settings: Settings,
    *,
    notebook_id: str,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise IngestError(f"file troppo grande: limite {settings.max_upload_mb} MB")
    if not data:
        raise IngestError("file vuoto")

    digest = hashlib.sha256(data).hexdigest()
    for existing in store.sources(notebook_id):
        if existing["sha256"] == digest and existing["status"] == "ready":
            return {**existing, "duplicate": True}

    source_id = f"src_{uuid.uuid4().hex[:12]}"
    # il contenuto dice piu' del nome: un PDF scaricato senza estensione resta
    # un PDF, un archivio resta un archivio
    suffix = suffix_for(filename, data)
    stored = _save(settings, source_id, suffix, data)
    store.add_source(
        source_id=source_id,
        notebook_id=notebook_id,
        kind="pending",
        title=_title_from_name(filename),
        origin=filename,
        path=str(stored),
        sha256=digest,
    )

    try:
        kind, pages = extract_file(stored, ocr_enabled=settings.ocr_enabled)
        total = _index(store, source_id, pages)
    except (ExtractionError, IngestError) as error:
        store.finish_source(source_id, pages=0, n_tokens=0, error=str(error))
        raise IngestError(str(error)) from error

    store.finish_source(source_id, pages=len(pages), n_tokens=total)
    store.set_source_kind(source_id, kind)
    result = store.source(source_id)
    assert result is not None
    return result


def create_from_url(
    store: Store,
    settings: Settings,
    *,
    notebook_id: str,
    url: str,
) -> dict[str, Any]:
    try:
        body, content_type, final_url = web_ext.download(
            url, allow_private=settings.allow_private_urls
        )
    except web_ext.FetchError as error:
        raise IngestError(str(error)) from error

    is_pdf = "application/pdf" in content_type or final_url.lower().endswith(".pdf")
    suffix = ".pdf" if is_pdf else ".html"
    title = ""
    if is_pdf:
        title = Path(final_url.split("?")[0]).stem
    else:
        title = web_ext.title_from_html(body) or Path(final_url.split("?")[0]).name
        body = web_ext.to_text(body, content_type).encode("utf-8")
        suffix = ".txt"

    return create_from_bytes(
        store,
        settings,
        notebook_id=notebook_id,
        filename=f"{title or 'pagina'}{suffix}",
        data=body,
    )
