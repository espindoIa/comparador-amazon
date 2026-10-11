"""Banco SQLite e datas no horário de Brasília."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Horário de Brasília (sem horário de verão desde 2019). Fixo, para não depender de tzdata.
BRASILIA = timezone(timedelta(hours=-3))


def agora() -> str:
    """Instante atual em UTC, ISO 8601, sem frações de segundo."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(caminho: str | Path) -> sqlite3.Connection:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def dia_brasil(iso_utc: str) -> date:
    """Dia (em Brasília) de um instante ISO em UTC."""
    return datetime.fromisoformat(iso_utc).astimezone(BRASILIA).date()


def hoje_brasil() -> date:
    return datetime.now(BRASILIA).date()
