"""Avvio e arresto dei due sidecar di retrieval.

Sono processi llama-server dedicati: bge-m3 per gli embedding su ``embed_url`` e
il reranker su ``rerank_url``. Restano fuori dal router di chat, che continua a
gestire i suoi preset senza ``--models-max`` piu' alti e senza cambi di flag.
Se un modello o il binario mancano, il sidecar non parte e il retrieval resta
lessicale: e' una degradazione, non un errore.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import IO
from urllib.parse import urlparse

import httpx

from .config import Settings

logger = logging.getLogger("docbooklm")

START_TIMEOUT = 120.0
_running: dict[str, subprocess.Popen[bytes]] = {}


def _port(url: str) -> int:
    parsed = urlparse(url)
    return parsed.port or 80


def _healthy(url: str) -> bool:
    try:
        # solo 200: con 503 il modello sta caricando e le richieste fallirebbero
        return httpx.get(f"{url}/health", timeout=httpx.Timeout(1.0)).status_code == 200
    except httpx.HTTPError:
        return False


def _log_path(settings: Settings, name: str) -> Path:
    return settings.data_dir / f"sidecar-{name}.log"


MAX_LOG_BYTES = 8 * 1024 * 1024


def _open_log(path: Path) -> IO[bytes]:
    """Log del sidecar in append, azzerato se e' diventato enorme.

    Ogni avvio e ogni tanto il file cresce: senza un tetto, in qualche mese
    sono centinaia di megabyte che nessuno legge.
    """
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_bytes(b"")
    except OSError:
        pass
    return path.open("ab")


def _command(settings: Settings, name: str) -> list[str] | None:
    """Riga di comando del sidecar, o None se manca qualcosa sul disco."""
    binary = settings.llama_server
    if name == "embed":
        model = settings.model_path(settings.embed_model)
        flags = ["--embeddings", "--pooling", "cls"]
        url = settings.embed_url
    else:
        model = settings.model_path(settings.rerank_model)
        flags = ["--reranking", "--pooling", "rank"]
        url = settings.rerank_url

    if not binary.exists():
        logger.warning("sidecar %s non avviato: manca %s", name, binary)
        return None
    if not model.exists():
        logger.warning("sidecar %s non avviato: manca il modello %s", name, model)
        return None
    return [
        str(binary),
        *flags,
        "-m",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(_port(url)),
        # -ngl 99: bge-m3 e il reranker stanno in ~1,3 GB, la chat ne riserva ~10
        "-ngl",
        "99",
        "-c",
        "4096",
        "-b",
        "4096",
        # ubatch fisico: un passaggio da 1200 token non deve andare in errore
        "-ub",
        "2048",
        "--no-webui",
        "--log-colors",
        "off",
    ]


def _start(settings: Settings, name: str) -> bool:
    url = settings.embed_url if name == "embed" else settings.rerank_url
    if _healthy(url):
        logger.info("sidecar %s gia' attivo su %s", name, url)
        return True

    command = _command(settings, name)
    if command is None:
        return False

    log = _open_log(_log_path(settings, name))
    log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} avvio {name}\n".encode())
    log.flush()
    try:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        logger.warning("sidecar %s non avviato: %s", name, error)
        log.close()
        return False
    _running[name] = process

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            logger.warning(
                "sidecar %s terminato durante l'avvio (codice %s); vedi %s",
                name,
                process.returncode,
                _log_path(settings, name),
            )
            _running.pop(name, None)
            log.close()
            return False
        if _healthy(url):
            logger.info("sidecar %s pronto su %s", name, url)
            return True
        time.sleep(0.5)

    logger.warning("sidecar %s non pronto entro %.0f s", name, START_TIMEOUT)
    return False


def start(settings: Settings) -> dict[str, bool]:
    """Avvia i sidecar abilitati; restituisce lo stato di ciascuno."""
    if not settings.embed_enabled:
        return {"embed": False, "rerank": False}
    if not settings.sidecar_enabled:
        # sidecar avviati altrove: si usa quello che c'e'
        return {"embed": _healthy(settings.embed_url), "rerank": _healthy(settings.rerank_url)}
    return {
        "embed": _start(settings, "embed"),
        "rerank": _start(settings, "rerank"),
    }


def stop() -> None:
    """Ferma solo i processi avviati da questo processo."""
    for name, process in list(_running.items()):
        _running.pop(name, None)
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
        logger.info("sidecar %s fermato", name)
