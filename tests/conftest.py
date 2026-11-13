"""Fixture condivise: store, impostazioni e PDF di prova."""

from __future__ import annotations

from pathlib import Path

import pytest

from docbooklm.config import Settings
from docbooklm.store import Store

from .pdf_fixture import build_pdf


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    # niente sidecar nei test: la GPU e la rete restano fuori
    config = Settings(
        data_dir=tmp_path / "data",
        ocr_enabled=False,
        embed_enabled=False,
        sidecar_enabled=False,
    )
    config.ensure_dirs()
    return config


@pytest.fixture()
def store(settings: Settings) -> Store:
    store = Store(settings.db_path)
    store.create_notebook("nb_test", "Quaderno di prova")
    return store


@pytest.fixture()
def pdf_path(tmp_path: Path) -> Path:
    return build_pdf(
        tmp_path / "prova.pdf",
        [
            "DocBooK LM documento di prova",
            "Il prefill misura la velocita di lettura del contesto.",
            "La Vega 64 ha sedici gigabyte di memoria video.",
        ],
    )
