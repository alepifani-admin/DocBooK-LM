"""Persistenza su SQLite: notebook, fonti, chunk, note, messaggi.

Una connessione per operazione: SQLite e' economico e cosi' il codice e' sicuro
anche quando FastAPI serve richieste sincrone dal threadpool.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebook (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS source (
    id          TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebook(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT '',
    path        TEXT,
    sha256      TEXT NOT NULL DEFAULT '',
    pages       INTEGER NOT NULL DEFAULT 0,
    n_tokens    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'ready',
    error       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS source_notebook_idx ON source(notebook_id);

CREATE TABLE IF NOT EXISTS chunk (
    id        INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    ord       INTEGER NOT NULL,
    page      INTEGER NOT NULL DEFAULT 0,
    section   TEXT NOT NULL DEFAULT '',
    text      TEXT NOT NULL,
    n_tokens  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chunk_source_idx ON chunk(source_id, ord);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    text,
    content='chunk',
    content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS note (
    id          TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebook(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    markdown    TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS note_notebook_idx ON note(notebook_id, created_at);

CREATE TABLE IF NOT EXISTS message (
    id         TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebook(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    citations  TEXT NOT NULL DEFAULT '[]',
    model      TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS message_notebook_idx ON message(notebook_id, created_at);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> float:
    return time.time()


class Store:
    """Accesso al database. Nessuno stato condiviso: ogni chiamata apre e chiude."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ notebook

    def notebooks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT n.*, (SELECT COUNT(*) FROM source s WHERE s.notebook_id = n.id) AS n_sources"
                " FROM notebook n ORDER BY n.created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def notebook(self, notebook_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notebook WHERE id = ?", (notebook_id,)).fetchone()
        return dict(row) if row else None

    def create_notebook(self, notebook_id: str, name: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO notebook (id, name, created_at) VALUES (?, ?, ?)",
                (notebook_id, name, _now()),
            )
        return {"id": notebook_id, "name": name, "n_sources": 0, "created_at": _now()}

    def rename_notebook(self, notebook_id: str, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE notebook SET name = ? WHERE id = ?", (name, notebook_id))
        return cur.rowcount > 0

    def delete_notebook(self, notebook_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook WHERE id = ?", (notebook_id,))
        return cur.rowcount > 0

    def ensure_notebook(self, notebook_id: str) -> dict[str, Any]:
        found = self.notebook(notebook_id)
        if found is None:
            return self.create_notebook(notebook_id, "Quaderno senza titolo")
        return found

    # -------------------------------------------------------------------- source

    def sources(self, notebook_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source WHERE notebook_id = ? ORDER BY created_at",
                (notebook_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def source(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM source WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None

    def add_source(
        self,
        *,
        source_id: str,
        notebook_id: str,
        kind: str,
        title: str,
        origin: str,
        path: str | None,
        sha256: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO source (id, notebook_id, kind, title, origin, path, sha256,"
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', ?)",
                (source_id, notebook_id, kind, title, origin, path, sha256, _now()),
            )
        result = self.source(source_id)
        assert result is not None
        return result

    def set_source_kind(self, source_id: str, kind: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE source SET kind = ? WHERE id = ?", (kind, source_id))

    def finish_source(
        self, source_id: str, *, pages: int, n_tokens: int, error: str = ""
    ) -> None:
        status = "error" if error else "ready"
        with self._connect() as conn:
            conn.execute(
                "UPDATE source SET status = ?, error = ?, pages = ?, n_tokens = ? WHERE id = ?",
                (status, error, pages, n_tokens, source_id),
            )

    def delete_source(self, source_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM source WHERE id = ?", (source_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------------- chunk

    def add_chunks(self, source_id: str, chunks: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO chunk (source_id, ord, page, section, text, n_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        source_id,
                        index,
                        chunk.get("page", 0),
                        chunk.get("section", ""),
                        chunk["text"],
                        chunk.get("n_tokens", 0),
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )

    def chunks(self, source_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk WHERE source_id = ? ORDER BY ord", (source_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def chunk(self, chunk_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT c.*, s.title AS source_title FROM chunk c"
                " JOIN source s ON s.id = c.source_id WHERE c.id = ?",
                (chunk_id,),
            ).fetchone()
        return dict(row) if row else None

    # -------------------------------------------------------------------- search

    def search(self, source_ids: list[str], query: str, limit: int = 30) -> list[dict[str, Any]]:
        """BM25 su FTS5, ristretto alle fonti indicate."""
        if not source_ids or not query.strip():
            return []
        placeholders = ",".join("?" for _ in source_ids)
        sql = (
            "SELECT c.*, s.title AS source_title, bm25(chunk_fts) AS score"
            " FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
            " JOIN source s ON s.id = c.source_id"
            f" WHERE chunk_fts MATCH ? AND c.source_id IN ({placeholders})"
            " ORDER BY score LIMIT ?"
        )
        params: list[Any] = [query, *source_ids, limit]
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]

    def head_chunks(self, source_id: str, limit: int = 2) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.*, s.title AS source_title FROM chunk c"
                " JOIN source s ON s.id = c.source_id"
                " WHERE c.source_id = ? ORDER BY c.ord LIMIT ?",
                (source_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def page_of_chunk(self, chunk_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT page FROM chunk WHERE id = ?", (chunk_id,)).fetchone()
        return int(row["page"]) if row else 0

    # --------------------------------------------------------------------- note

    def notes(self, notebook_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM note WHERE notebook_id = ? ORDER BY created_at DESC",
                (notebook_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_note(
        self, notebook_id: str, note_id: str, title: str, markdown: str
    ) -> dict[str, Any]:
        created = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO note (id, notebook_id, title, markdown, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (note_id, notebook_id, title, markdown, created),
            )
        return {
            "id": note_id,
            "notebook_id": notebook_id,
            "title": title,
            "markdown": markdown,
            "created_at": created,
        }

    def delete_note(self, note_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM note WHERE id = ?", (note_id,))
        return cur.rowcount > 0

    def note(self, note_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM note WHERE id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    def update_note(self, note_id: str, *, title: str, markdown: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE note SET title = ?, markdown = ? WHERE id = ?",
                (title, markdown, note_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM note WHERE id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ message

    def add_message(
        self,
        *,
        message_id: str,
        notebook_id: str,
        role: str,
        text: str,
        citations: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> dict[str, Any]:
        created = _now()
        payload = json.dumps(citations or [], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO message (id, notebook_id, role, text, citations, model, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, notebook_id, role, text, payload, model, created),
            )
        return {
            "id": message_id,
            "notebook_id": notebook_id,
            "role": role,
            "text": text,
            "citations": citations or [],
            "model": model,
            "created_at": created,
        }

    def messages(self, notebook_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM message WHERE notebook_id = ? ORDER BY created_at DESC LIMIT ?",
                (notebook_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["citations"] = json.loads(item["citations"])
            result.append(item)
        return result

    # ----------------------------------------------------------------------- kv

    def get_kv(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_kv(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
