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


def abrir_leitura(caminho: str | Path, papel: str = "banco") -> sqlite3.Connection:
    """Abre um banco que já existe, só para leitura. Se não abrir, encerra dizendo qual banco foi (`papel`: "novo",
    "anterior"...) e onde o procurou, em vez de um traceback do sqlite3 sem o caminho."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise SystemExit(f"{papel}: banco não encontrado: {caminho}")
    try:
        return sqlite3.connect(f"{caminho.absolute().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise SystemExit(f"{papel}: não consegui abrir {caminho}: {e}")


def dia_brasil(iso_utc: str) -> date:
    """Dia (em Brasília) de um instante ISO em UTC."""
    return datetime.fromisoformat(iso_utc).astimezone(BRASILIA).date()


def hoje_brasil() -> date:
    return datetime.now(BRASILIA).date()
