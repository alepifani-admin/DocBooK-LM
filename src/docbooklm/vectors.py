"""Ricerca densa: vettori float32 nel database, confronto a matrice con numpy.

Con qualche migliaio di passaggi il prodotto matrice-vettore costa pochi
millisecondi, quindi non serve un indice approssimato: si tiene in memoria la
matrice di ogni fonte selezionata e si ricostruisce solo quando i vettori
cambiano. La cache e' per processo e viene invalidata dall'indicizzatore.
"""

from __future__ import annotations

import threading
from typing import Any, cast

import numpy as np

from .store import Store


def pack(vector: np.ndarray | list[float]) -> bytes:
    """Vettore -> byte contigui float32 (l'ordine degli assi resta quello)."""
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    return array.tobytes()


def unpack(blob: bytes) -> np.ndarray:
    return cast(np.ndarray, np.frombuffer(blob, dtype=np.float32))


def normalize(matrix: np.ndarray) -> np.ndarray:
    """Righe a norma 1: coseno = prodotto scalare, senza divisioni per riga."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return cast(np.ndarray, matrix / norms)


class VectorIndex:
    """Matrici dei vettori per fonte, con cache invalidabile."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[int, np.ndarray, np.ndarray]] = {}

    def invalidate(self, source_id: str | None = None) -> None:
        with self._lock:
            if source_id is None:
                self._cache.clear()
            else:
                self._cache.pop(source_id, None)

    def _source_matrix(self, source_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        # Un COUNT e' un indice, leggere i blob no: si ricostruisce solo se il
        # numero di vettori cambia. La sostituzione a parita' di numero (modello
        # di embedding diverso) richiede invalidate().
        count = self._store.vector_count([source_id])
        if count == 0:
            self._cache.pop(source_id, None)
            return None
        cached = self._cache.get(source_id)
        if cached and cached[0] == count:
            return cached[1], cached[2]

        rows = self._store.vectors([source_id])
        dim = int(rows[0]["dim"])
        ids = np.fromiter((int(row["chunk_id"]) for row in rows), dtype=np.int64, count=count)
        matrix = np.frombuffer(b"".join(row["vec"] for row in rows), dtype=np.float32)
        if matrix.size != count * dim:  # vettori di dimensioni diverse: dati incoerenti
            return None
        matrix = normalize(matrix.reshape(count, dim))
        self._cache[source_id] = (count, ids, matrix)
        return ids, matrix

    def search(
        self, source_ids: list[str], query: np.ndarray | list[float], limit: int = 40
    ) -> list[dict[str, Any]]:
        """I passaggi piu' vicini alla domanda, dal piu' simile al meno simile."""
        if not source_ids or limit <= 0:
            return []
        query_vector = normalize(np.asarray(query, dtype=np.float32).reshape(1, -1))[0]

        chunks: list[np.ndarray] = []
        scores: list[np.ndarray] = []
        with self._lock:
            for source_id in source_ids:
                entry = self._source_matrix(source_id)
                if entry is None:
                    continue
                ids, matrix = entry
                if matrix.shape[1] != query_vector.shape[0]:
                    continue  # modello di embedding diverso: vettore non confrontabile
                chunks.append(ids)
                scores.append(matrix @ query_vector)

        if not chunks:
            return []
        all_ids = np.concatenate(chunks)
        all_scores = np.concatenate(scores)
        take = min(limit, all_ids.size)
        # argpartition: basta l'ordine dei primi `take`, senza ordinare tutto
        top = np.argpartition(-all_scores, take - 1)[:take]
        top = top[np.argsort(-all_scores[top])]
        return [
            {"chunk_id": int(all_ids[index]), "score": float(all_scores[index])}
            for index in top
        ]


_INDEXES: dict[str, VectorIndex] = {}
_REGISTRY_LOCK = threading.Lock()


def index_for(store: Store) -> VectorIndex:
    """Un solo indice per database, condiviso da API e indicizzatore."""
    key = str(store.path)
    with _REGISTRY_LOCK:
        index = _INDEXES.get(key)
        if index is None:
            index = VectorIndex(store)
            _INDEXES[key] = index
        return index
