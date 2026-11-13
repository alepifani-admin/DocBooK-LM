"""API e interfaccia di DocBooK LM su 127.0.0.1:8078.

Un solo processo: FastAPI serve l'interfaccia statica e parla con il router
llama.cpp gia' attivo su :8080. Nessun modello viene caricato da qui.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.types import Scope

from . import __version__, indexer, llm, sidecar, vectors
from . import chat as chat_mod
from . import ingest as ingest_mod
from .config import Settings, get_settings
from .extract import pdf as pdf_ext
from .extract import pdf_boxes
from .retrieve import select as select_passages
from .store import Store

logger = logging.getLogger("docbooklm")

STATIC_DIR = Path(__file__).parent / "static"


# --------------------------------------------------------------------- modelli


class NotebookIn(BaseModel):
    name: str


class UrlIn(BaseModel):
    notebook: str
    url: str


class NoteIn(BaseModel):
    notebook: str
    title: str = ""
    markdown: str


class NotePatch(BaseModel):
    title: str | None = None
    markdown: str | None = None


class ModelIn(BaseModel):
    model: str


class ChatIn(BaseModel):
    notebook: str
    question: str
    sources: list[str] = []
    model: str | None = None
    history: bool = True


class ClientErrorIn(BaseModel):
    message: str = ""
    detail: str = ""
    agent: str = ""


# ------------------------------------------------------------------ applicazione


def _store(app: FastAPI) -> Store:  # pragma: no cover - accesso tipizzato
    return app.state.store  # type: ignore[no-any-return]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    settings.ensure_dirs()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store = Store(settings.db_path)
    app.state.settings = settings
    app.state.store = store
    if not store.notebooks():
        store.create_notebook(f"nb_{uuid.uuid4().hex[:10]}", "Il mio quaderno")

    # I sidecar si avviano dopo il servizio: se non partono, l'interfaccia
    # risponde lo stesso e il retrieval resta lessicale.
    status = await run_in_threadpool(sidecar.start, settings)
    app.state.sidecars = status
    if status.get("embed"):
        await run_in_threadpool(indexer.backfill, store, settings)

    logger.info(
        "DocBooK LM su http://%s:%s (embedding %s, rerank %s)",
        settings.api_host,
        settings.api_port,
        "attivo" if status.get("embed") else "spento",
        "attivo" if status.get("rerank") else "spento",
    )
    try:
        yield
    finally:
        indexer.shutdown()
        sidecar.stop()


app = FastAPI(title="DocBooK LM", version=__version__, lifespan=lifespan)
class _StaticFiles(StaticFiles):
    """Asset locali, mai riusati dalla cache: dopo un aggiornamento il browser
    non deve restare su un vecchio modulo JS (era successo: l'interfaccia
    chiamava `api.clearSources`, che nel file vecchio non esisteva). I file sono
    pochi e piccoli, scaricarli a ogni caricamento non costa nulla."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/static", _StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    # la pagina cambia quando cambia l'interfaccia: niente copia vecchia in cache
    return FileResponse(
        STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"}
    )


# --------------------------------------------------------------------- notebook


@app.get("/api/notebooks")
def list_notebooks() -> dict[str, Any]:
    return {"notebooks": _store(app).notebooks()}


@app.post("/api/notebooks", status_code=201)
def create_notebook(body: NotebookIn) -> dict[str, Any]:
    name = body.name.strip() or "Quaderno senza titolo"
    return _store(app).create_notebook(f"nb_{uuid.uuid4().hex[:10]}", name)


@app.patch("/api/notebooks/{notebook_id}")
def rename_notebook(notebook_id: str, body: NotebookIn) -> dict[str, Any]:
    store = _store(app)
    if not store.rename_notebook(notebook_id, body.name.strip() or "Quaderno senza titolo"):
        raise HTTPException(404, "quaderno inesistente")
    return {"ok": True}


@app.delete("/api/notebooks/{notebook_id}")
def delete_notebook(notebook_id: str) -> dict[str, Any]:
    store = _store(app)
    sources = store.sources(notebook_id)
    if sources:
        raise HTTPException(409, "il quaderno contiene fonti")
    if not store.delete_notebook(notebook_id):
        raise HTTPException(404, "quaderno inesistente")
    return {"ok": True}


# ----------------------------------------------------------------------- fonti


def _decorate(store: Store, source: dict[str, Any]) -> dict[str, Any]:
    """Aggiunge all'avanzamento dell'indicizzazione semantica al record fonte."""
    done, total = store.embedding_progress(str(source["id"]))
    return {**source, "embedded": done, "n_chunks": total}


def _index(store: Store, settings: Settings, source: dict[str, Any]) -> None:
    """Mette in coda i vettori mancanti: l'upload non aspetta la GPU."""
    if source.get("status") == "ready":
        indexer.submit(store, settings, str(source["id"]))


@app.get("/api/sources")
def list_sources(notebook: str = Query(...)) -> dict[str, Any]:
    store = _store(app)
    return {"sources": [_decorate(store, item) for item in store.sources(notebook)]}


@app.post("/api/sources", status_code=201)
async def upload_source(
    notebook: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    if store.notebook(notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    data = await file.read()
    try:
        source = await run_in_threadpool(
            ingest_mod.create_from_bytes,
            store,
            settings,
            notebook_id=notebook,
            filename=file.filename or "fonte",
            data=data,
        )
    except ingest_mod.IngestError as error:
        raise HTTPException(400, str(error)) from error
    _index(store, settings, source)
    return _decorate(store, source)


@app.post("/api/sources/url", status_code=201)
async def upload_url(body: UrlIn) -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    if store.notebook(body.notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    try:
        source = await run_in_threadpool(
            ingest_mod.create_from_url,
            store,
            settings,
            notebook_id=body.notebook,
            url=body.url,
        )
    except ingest_mod.IngestError as error:
        raise HTTPException(400, str(error)) from error
    _index(store, settings, source)
    return _decorate(store, source)


@app.post("/api/sources/text", status_code=201)
async def upload_text(
    notebook: str = Form(...),
    title: str = Form("Testo incollato"),
    text: str = Form(...),
) -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    if store.notebook(notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    if not text.strip():
        raise HTTPException(400, "testo vuoto")
    safe = (title.strip() or "Testo incollato").replace("/", "-")[:80]
    try:
        source = await run_in_threadpool(
            ingest_mod.create_from_bytes,
            store,
            settings,
            notebook_id=notebook,
            filename=f"{safe}.txt",
            data=text.encode("utf-8"),
        )
    except ingest_mod.IngestError as error:
        raise HTTPException(400, str(error)) from error
    _index(store, settings, source)
    return _decorate(store, source)


@app.get("/api/sources/{source_id}")
def get_source(source_id: str) -> dict[str, Any]:
    store = _store(app)
    source = store.source(source_id)
    if source is None:
        raise HTTPException(404, "fonte inesistente")
    return {"source": _decorate(store, source), "passages": store.chunks(source_id)}


def _purge(store: Store, settings: Settings, source: dict[str, Any]) -> None:
    """Rimuove una fonte: file caricato, pagine in cache, righe e vettori."""
    source_id = str(source["id"])
    if source["path"]:
        Path(source["path"]).unlink(missing_ok=True)
    for cached in settings.pages_dir.glob(f"{source_id}-*.png"):
        cached.unlink(missing_ok=True)
    store.delete_source(source_id)
    vectors.index_for(store).invalidate(source_id)


@app.delete("/api/sources")
def delete_sources(notebook: str = Query(...)) -> dict[str, Any]:
    """Svuota il quaderno delle sue fonti, in una sola chiamata."""
    settings: Settings = get_settings()
    store = _store(app)
    if store.notebook(notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    sources = store.sources(notebook)
    for source in sources:
        _purge(store, settings, source)
    return {"ok": True, "deleted": len(sources)}


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str) -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    source = store.source(source_id)
    if source is None:
        raise HTTPException(404, "fonte inesistente")
    _purge(store, settings, source)
    return {"ok": True}


@app.get("/api/sources/{source_id}/page/{page}.png")
def source_page(source_id: str, page: int, dpi: int = Query(150, ge=72, le=300)) -> FileResponse:
    settings: Settings = get_settings()
    store = _store(app)
    source = store.source(source_id)
    if source is None or not source["path"]:
        raise HTTPException(404, "fonte inesistente")
    if source["kind"] != "pdf":
        raise HTTPException(400, "la fonte non e' un PDF")
    cache = settings.pages_dir / f"{source_id}-{page}-{dpi}.png"
    if not cache.exists():
        try:
            cache.write_bytes(pdf_ext.page_image(Path(source["path"]), page, dpi=dpi))
        except Exception as error:  # pragma: no cover - dipende dal file
            raise HTTPException(500, f"pagina non renderizzabile: {error}") from error
    return FileResponse(cache, media_type="image/png")


@app.get("/api/sources/{source_id}/locate")
def locate_quote(source_id: str, quote: str, page: int = 0) -> dict[str, Any]:
    store = _store(app)
    source = store.source(source_id)
    if source is None or not source["path"] or source["kind"] != "pdf":
        return {"found": False, "boxes": []}
    return pdf_boxes.locate(Path(source["path"]), page, quote)


# ------------------------------------------------------------------------ note


@app.get("/api/notes")
def list_notes(notebook: str = Query(...)) -> dict[str, Any]:
    return {"notes": _store(app).notes(notebook)}


@app.post("/api/notes", status_code=201)
def create_note(body: NoteIn) -> dict[str, Any]:
    store = _store(app)
    if store.notebook(body.notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    title = body.title.strip() or "Nota"
    return store.add_note(body.notebook, f"note_{uuid.uuid4().hex[:10]}", title, body.markdown)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str) -> dict[str, Any]:
    if not _store(app).delete_note(note_id):
        raise HTTPException(404, "nota inesistente")
    return {"ok": True}


@app.patch("/api/notes/{note_id}")
def patch_note(note_id: str, body: NotePatch) -> dict[str, Any]:
    store = _store(app)
    current = store.note(note_id)
    if current is None:
        raise HTTPException(404, "nota inesistente")
    updated = store.update_note(
        note_id,
        title=(body.title if body.title is not None else current["title"]).strip() or "Nota",
        markdown=body.markdown if body.markdown is not None else current["markdown"],
    )
    if updated is None:
        raise HTTPException(404, "nota inesistente")
    return updated


# ---------------------------------------------------------------------- modelli


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    current = store.get_kv("model", settings.default_model)
    try:
        available = await llm.models(settings)
        error = ""
    except llm.LLMError as failure:
        available, error = [], str(failure)
    if current not in {item["id"] for item in available} and available:
        current = available[0]["id"]
    return {
        "models": available,
        "current": current,
        "router": settings.router_url,
        "error": error,
    }


@app.post("/api/models/select")
def select_model(body: ModelIn) -> dict[str, Any]:
    _store(app).set_kv("model", body.model)
    return {"ok": True, "current": body.model}


# ----------------------------------------------------------------------- chat


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatIn) -> StreamingResponse:
    settings: Settings = get_settings()
    store = _store(app)
    if store.notebook(body.notebook) is None:
        raise HTTPException(404, "quaderno inesistente")
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "domanda vuota")
    source_ids = [item for item in body.sources if store.source(item) is not None]
    if not source_ids:
        raise HTTPException(400, "seleziona almeno una fonte")

    model = body.model or store.get_kv("model", settings.default_model)
    history: list[dict[str, str]] = []
    if body.history:
        for message in store.messages(body.notebook, limit=settings.history_turns * 2):
            history.append({"role": message["role"], "text": message["text"]})

    passages = select_passages(store, source_ids, question, settings=settings)
    store.add_message(
        message_id=f"msg_{uuid.uuid4().hex[:10]}",
        notebook_id=body.notebook,
        role="user",
        text=question,
        model=model,
    )
    messages = chat_mod.build_messages(question, passages, history)

    async def stream() -> AsyncIterator[str]:
        yield _sse(
            "meta",
            {
                "model": model,
                "passages": [
                    {
                        "n": passage["n"],
                        "source_id": passage["source_id"],
                        "source_title": passage["source_title"],
                        "page": passage["page"],
                    }
                    for passage in passages
                ],
            },
        )
        collected: list[str] = []
        try:
            async for delta in llm.stream_chat(
                settings,
                model=model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature,
                top_p=settings.top_p,
                thinking=settings.thinking,
            ):
                collected.append(delta)
                yield _sse("delta", {"text": delta})
        except llm.LLMError as error:
            logger.warning("generazione interrotta: %s", error)
            yield _sse("error", {"message": str(error)})
            return

        answer = "".join(collected).strip()
        if not answer:
            yield _sse("error", {"message": "il modello non ha prodotto testo"})
            return
        text, citations = chat_mod.verify(answer, passages)
        store.add_message(
            message_id=f"msg_{uuid.uuid4().hex[:10]}",
            notebook_id=body.notebook,
            role="assistant",
            text=text,
            citations=citations,
            model=model,
        )
        yield _sse("done", {"text": text, "citations": citations, "model": model})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/state")
async def state(notebook: str = Query("")) -> dict[str, Any]:
    """Tutto cio' che serve all'interfaccia per disegnarsi in un colpo solo."""
    settings: Settings = get_settings()
    store = _store(app)
    if not notebook:
        existing = store.notebooks()
        notebook = existing[0]["id"] if existing else f"nb_{uuid.uuid4().hex[:10]}"
    store.ensure_notebook(notebook)
    model_payload = await list_models()
    return {
        "notebooks": store.notebooks(),
        "notebook": store.notebook(notebook),
        "sources": [_decorate(store, item) for item in store.sources(notebook)],
        "notes": store.notes(notebook),
        "messages": store.messages(notebook, limit=settings.history_turns * 2),
        "models": model_payload["models"],
        "model": model_payload["current"],
        "router": settings.router_url,
        "router_error": model_payload["error"],
    }


@app.post("/api/client-error")
def client_error(body: ClientErrorIn) -> dict[str, Any]:
    """Un errore dell'interfaccia finisce nel log del servizio.

    Il messaggio che compare in un avviso sparisce dopo pochi secondi: senza
    questa riga, un guasto del browser resta invisibile dal lato del server.
    """
    logger.warning(
        "errore nell'interfaccia: %s | %s | %s",
        body.message[:500],
        body.detail[:2000],
        body.agent[:200],
    )
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    settings: Settings = get_settings()
    store = _store(app)
    probe = await llm.probe(settings)
    return {
        "service": "docbooklm",
        "version": __version__,
        "router": {"url": settings.router_url, **probe},
        "notebooks": len(store.notebooks()),
    }


@app.exception_handler(HTTPException)
async def http_error(_: Any, error: HTTPException) -> Response:
    return Response(
        content=json.dumps({"error": error.detail}, ensure_ascii=False),
        status_code=error.status_code,
        media_type="application/json",
    )


def main() -> None:  # pragma: no cover - avvio da riga di comando
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "docbooklm.api:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
