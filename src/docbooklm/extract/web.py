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
    """Restituisce (contenuto, content-type, url finale)."""
    target = validate(url, allow_private=allow_private)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"}
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True,
                      max_redirects=MAX_REDIRECTS, headers=headers) as client:
        try:
            response = client.get(target)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise FetchError(f"scaricamento fallito: {error}") from error
    body = response.content
    if len(body) > MAX_BYTES:
        raise FetchError("pagina troppo grande (limite 20 MB)")
    content_type = response.headers.get("content-type", "").lower()
    return body, content_type, str(response.url)


def to_text(body: bytes, content_type: str) -> str:
    if "html" not in content_type and not body[:200].lstrip().lower().startswith(b"<!doctype"):
        text = body.decode("utf-8", errors="replace")
        return text if "html" not in content_type else html_to_text(text)
    return html_to_text(body.decode("utf-8", errors="replace"))


def title_from_html(body: bytes) -> str:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", body.decode("utf-8", errors="replace"),
                      re.IGNORECASE | re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""
