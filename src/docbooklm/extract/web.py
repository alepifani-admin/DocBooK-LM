"""Fonti web: scaricamento prudente e conversione in testo utile."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from .text import html_to_text

USER_AGENT = "DocBooKLM/0.1 (locale; uso personale)"
TIMEOUT_S = 25.0
MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5


class FetchError(RuntimeError):
    """Link non scaricabile o non ammesso."""


def _is_private_host(host: str) -> bool:
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def validate(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise FetchError("sono ammessi solo link http e https")
    if not parsed.hostname:
        raise FetchError("link senza dominio")
    if not allow_private and _is_private_host(parsed.hostname):
        raise FetchError("link verso rete privata bloccato")
    return url.strip()


def download(url: str, *, allow_private: bool = False) -> tuple[bytes, str, str]:
    """Restituisce (contenuto, content-type, url finale).

    I reindirizzamenti si seguono a mano: ognuno viene rivalidato, altrimenti un
    link pubblico potrebbe rimbalzare su ``127.0.0.1`` e aggirare il blocco
    delle reti private. Il corpo si legge a pezzi, con un tetto, invece di
    tenere in memoria una pagina da centinaia di megabyte.
    """
    target = validate(url, allow_private=allow_private)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"}
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", target) as response:
                    location = response.headers.get("location")
                    if response.is_redirect and location:
                        target = validate(
                            str(response.url.join(location)), allow_private=allow_private
                        )
                        continue
                    response.raise_for_status()
                    body = _read_capped(response)
                    content_type = response.headers.get("content-type", "").lower()
                    return body, content_type, str(response.url)
            except httpx.HTTPError as error:
                raise FetchError(f"scaricamento fallito: {error}") from error
    raise FetchError("troppi reindirizzamenti")


def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise FetchError("pagina troppo grande (limite 20 MB)")
    return bytes(body)


def to_text(body: bytes, content_type: str) -> str:
    """Testo utile da una pagina: HTML ripulito, o il contenuto cosi' com'e'."""
    raw = body.decode("utf-8", errors="replace")
    looks_html = "html" in content_type or body[:200].lstrip().lower().startswith(b"<!doctype")
    if looks_html or "<html" in raw[:2000].lower():
        return html_to_text(raw)
    return raw


def title_from_html(body: bytes) -> str:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", body.decode("utf-8", errors="replace"),
                      re.IGNORECASE | re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""
