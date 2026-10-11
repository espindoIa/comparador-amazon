"""Acesso ao banco SQLite."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


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


def criar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def importar_eventos(conn: sqlite3.Connection, csv_path: str | Path) -> int:
    """Carrega eventos.csv (colunas: nome,inicio,fim). Reexecutar atualiza o `fim`."""
    n = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if not (linha.get("nome") or "").strip():
                continue
            conn.execute(
                "INSERT INTO eventos (nome, inicio, fim) VALUES (?, ?, ?) "
                "ON CONFLICT (nome, inicio) DO UPDATE SET fim = excluded.fim",
                (linha["nome"].strip(), linha["inicio"].strip(), linha["fim"].strip()),
            )
            n += 1
    conn.commit()
    return n
