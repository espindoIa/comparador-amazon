"""Acesso ao banco SQLite."""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


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


def criar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    # Migração de bancos criados antes da coluna `fonte` existir.
    colunas = {r["name"] for r in conn.execute("PRAGMA table_info(precos)")}
    if "completa" not in {r["name"] for r in conn.execute("PRAGMA table_info(coletas)")}:
        conn.execute("ALTER TABLE coletas ADD COLUMN completa INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "fonte" not in colunas:
        conn.execute(
            "ALTER TABLE precos ADD COLUMN fonte TEXT NOT NULL DEFAULT 'ofertas' "
            "CHECK (fonte IN ('ofertas', 'lista_desejos'))"
        )
        conn.commit()


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


def dia_brasil(iso_utc: str) -> date:
    """Dia (em Brasília) de um instante ISO em UTC."""
    return datetime.fromisoformat(iso_utc).astimezone(BRASILIA).date()


def hoje_brasil() -> date:
    return datetime.now(BRASILIA).date()


def dias_cobertos(conn: sqlite3.Connection) -> set[date]:
    """Dias (em Brasília) com pelo menos uma coleta completa."""
    return {dia_brasil(r[0]) for r in conn.execute("SELECT iniciada_em FROM coletas WHERE completa = 1")}


def lacunas(conn: sqlite3.Connection, hoje: date | None = None) -> list[date]:
    """Dias sem coleta completa, do primeiro dia coberto até ontem (hoje ainda pode ser coletado)."""
    cobertos = dias_cobertos(conn)
    if not cobertos:
        return []
    hoje = hoje or hoje_brasil()
    dia, fim, faltam = min(cobertos), hoje - timedelta(days=1), []
    while dia <= fim:
        if dia not in cobertos:
            faltam.append(dia)
        dia += timedelta(days=1)
    return faltam
