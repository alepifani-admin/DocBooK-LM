"""Scaricamento dei link: rete privata, reindirizzamenti e dimensione."""

from __future__ import annotations

import httpx
import pytest

from docbooklm.extract import web


class _Stream:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, *_args: object) -> bool:
        return False


class _Client:
    """Sostituisce httpx.Client: consuma le risposte preparate, in ordine."""

    def __init__(self, responses: list[httpx.Response], **kwargs: object) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def stream(self, _method: str, url: str, **_kwargs: object) -> _Stream:
        self.calls.append(url)
        return _Stream(self._responses.pop(0))


def _public_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # niente DNS nei test: "pubblico.test" e' pubblico, 127.0.0.1 no
    monkeypatch.setattr(
        web, "_is_private_host", lambda host: host in {"127.0.0.1", "localhost"}
    )


def test_redirect_to_a_private_host_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_only(monkeypatch)
    redirect = httpx.Response(
        302,
        headers={"location": "http://127.0.0.1/segreto"},
        request=httpx.Request("GET", "http://pubblico.test/pagina"),
    )
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: _Client([redirect], **kwargs))

    with pytest.raises(web.FetchError, match="rete privata"):
        web.download("http://pubblico.test/pagina")


def test_redirect_on_a_public_host_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_only(monkeypatch)
    redirect = httpx.Response(
        301,
        headers={"location": "http://pubblico.test/altra"},
        request=httpx.Request("GET", "http://pubblico.test/pagina"),
    )
    page = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<html><body>contenuto</body></html>",
        request=httpx.Request("GET", "http://pubblico.test/altra"),
    )
    client = _Client([redirect, page])
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)

    body, content_type, url = web.download("http://pubblico.test/pagina")
    assert b"contenuto" in body
    assert content_type.startswith("text/html")
    assert url.endswith("/altra")
    assert client.calls == ["http://pubblico.test/pagina", "http://pubblico.test/altra"]


def test_page_larger_than_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_only(monkeypatch)
    monkeypatch.setattr(web, "MAX_BYTES", 10)
    page = httpx.Response(
        200,
        content=b"x" * 64,
        request=httpx.Request("GET", "http://pubblico.test/pagina"),
    )
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: _Client([page], **kwargs))

    with pytest.raises(web.FetchError, match="troppo grande"):
        web.download("http://pubblico.test/pagina")


def test_html_without_a_content_type_is_still_cleaned() -> None:
    text = web.to_text(b"<!doctype html><p>Ciao <b>mondo</b></p>", "text/plain")
    assert "Ciao mondo" in text
    assert "<b>" not in text


def test_plain_text_is_left_alone() -> None:
    assert web.to_text(b"riga uno\nriga due", "text/plain") == "riga uno\nriga due"
