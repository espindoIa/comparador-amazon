"""Dados de um livro para a página de histórico (comparador/web/livro.js) e a página avulsa do `grafico`.

Os cálculos (mediana, faixa, números por promoção) e o gráfico ficam todos em livro.js, para o site
e o comando `grafico` mostrarem exatamente a mesma coisa. Aqui só se lê o banco e se monta o JSON.
Os dias viajam como ordinais (date.toordinal()); os preços, em centavos.
"""

from __future__ import annotations

import csv
import html
import json
import sqlite3
from datetime import date
from pathlib import Path

from .db import dia_brasil

WEB = Path(__file__).with_name("web")
BURACO = 10  # dias sem coleta a partir dos quais dois trechos deixam de ser ligados


def ler_eventos(caminho: str | Path) -> list[list]:
    """[[nome, dia_ini, dia_fim], ...] a partir do eventos.csv (colunas nome,inicio,fim)."""
    p = Path(caminho)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return [[r["nome"], date.fromisoformat(r["inicio"]).toordinal(), date.fromisoformat(r["fim"]).toordinal()]
                for r in csv.DictReader(f) if (r.get("nome") or "").strip()]


def buscar(conn: sqlite3.Connection, termo: str) -> list[tuple[str, str]]:
    """(asin, titulo [formato]) cujo ASIN é igual ao termo ou cujo título contém o termo."""
    termo = termo.strip()
    linhas = conn.execute(
        "SELECT asin, COALESCE(titulo, '') || COALESCE(' [' || formato || ']', '') FROM catalogo "
        "WHERE asin = ? OR titulo LIKE ? ORDER BY 2 LIMIT 50", (termo.upper(), f"%{termo}%")).fetchall()
    return [(r[0], r[1]) for r in linhas]


def serie(conn: sqlite3.Connection, asin: str) -> list[list]:
    """Trechos de preço constante, em ordem: [[dia_ini, dia_fim, preco, capa ou None], ...]."""
    linhas = conn.execute(
        "SELECT desde, ate, preco_centavos, preco_capa_centavos FROM historico WHERE asin = ? ORDER BY desde, id",
        (asin,)).fetchall()
    return [[dia_brasil(r[0]).toordinal(), dia_brasil(r[1]).toordinal(), r[2], r[3]] for r in linhas]


def aviso(conn: sqlite3.Connection) -> str:
    """Texto da tabela `aviso`, que os bancos simulados trazem; vazio nos bancos reais."""
    if not conn.execute("SELECT name FROM sqlite_master WHERE name = 'aviso'").fetchone():
        return ""
    r = conn.execute("SELECT texto FROM aviso LIMIT 1").fetchone()
    return r[0] if r else ""


def json_seguro(obj) -> str:
    """JSON que pode ir dentro de <script> (sem fechar a tag nem quebrar em separadores de linha)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") \
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def pagina(titulo: str, asin: str, trechos: list[list], eventos: list[list], aviso: str = "", formato: str | None = None) -> str:
    """Página avulsa (um único arquivo HTML, sem depender de servidor) com o histórico de um livro."""
    dados = {"asin": asin, "titulo": titulo, "formato": formato, "aviso": aviso, "trechos": trechos, "eventos": eventos}
    css = (WEB / "estilo.css").read_text(encoding="utf-8")
    js = (WEB / "livro.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    return (f'<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(titulo)}</title><style>{css}</style><body>"
            f'<main id="livro"><noscript>Esta página precisa de JavaScript para mostrar o histórico.</noscript></main>'
            f"<script>{js}</script><script>Livro.montar(document.getElementById('livro'),{json_seguro(dados)});</script>"
            f"</body></html>")
