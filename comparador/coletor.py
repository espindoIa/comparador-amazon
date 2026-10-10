"""Coleta diária de preços: lê a lista de livros, visita cada página e grava no banco."""

from __future__ import annotations

import gzip
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import db
from .parser import Observacao, parse_produto

URL_PRODUTO = "https://www.amazon.com.br/dp/{asin}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}
PAUSA_PADRAO = (6.0, 14.0)  # segundos entre livros
LIMITE_BLOQUEIOS = 3  # bloqueios seguidos que interrompem a execução

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_URL_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")


def extrair_asin(texto: str) -> str | None:
    """Aceita um ASIN/ISBN-10 puro ou um link da Amazon."""
    texto = texto.strip()
    if _ASIN_RE.match(texto.upper()):
        return texto.upper()
    m = _URL_ASIN_RE.search(texto)
    return m.group(1) if m else None


def ler_lista(caminho: str | Path) -> list[str]:
    """Lê livros.txt: um ASIN ou link por linha; '#' inicia comentário."""
    asins: list[str] = []
    for n, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        asin = extrair_asin(linha)
        if asin is None:
            print(f"aviso: linha {n} ignorada (não achei um ASIN): {linha!r}")
        elif asin not in asins:
            asins.append(asin)
    return asins


def _guardar_html(pasta: Path, asin: str, html: str) -> str:
    agora = datetime.now(timezone.utc)
    destino = pasta / agora.strftime("%Y-%m-%d") / f"{asin}-{agora.strftime('%H%M%S')}.html.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(gzip.compress(html.encode("utf-8")))
    return str(destino)


def _baixar(sessao: requests.Session, asin: str) -> tuple[str | None, Observacao | None]:
    """Devolve (html, None) em caso de sucesso, ou (html|None, observação de erro)."""
    try:
        resp = sessao.get(URL_PRODUTO.format(asin=asin), headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        return None, Observacao("erro_http", detalhe=f"{type(e).__name__}: {e}")
    if resp.status_code == 503:
        return resp.text, Observacao("bloqueado", detalhe="HTTP 503")
    if resp.status_code != 200:
        return resp.text, Observacao("erro_http", detalhe=f"HTTP {resp.status_code}")
    return resp.text, None


def _registrar(conn, coleta_id, asin, obs: Observacao, html_arquivo: str | None) -> None:
    conn.execute(
        "INSERT INTO precos (asin, coleta_id, coletado_em, status, preco_centavos, "
        "preco_capa_centavos, vendido_por, em_estoque, condicao, html_arquivo, detalhe) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            asin, coleta_id, db.agora(), obs.status, obs.preco_centavos,
            obs.preco_capa_centavos, obs.vendido_por,
            None if obs.em_estoque is None else int(obs.em_estoque),
            obs.condicao, html_arquivo, obs.detalhe,
        ),
    )
    if obs.titulo:
        # Preenche título/autor na primeira vez; não sobrescreve edições manuais.
        conn.execute(
            "UPDATE livros SET titulo = COALESCE(titulo, ?), autor = COALESCE(autor, ?) "
            "WHERE asin = ?",
            (obs.titulo, obs.autor, asin),
        )


def coletar(
    conn: sqlite3.Connection,
    asins: list[str],
    *,
    sessao: requests.Session | None = None,
    pasta_html: Path | None = Path("data/html"),
    pausa: tuple[float, float] = PAUSA_PADRAO,
    dormir=time.sleep,
) -> int:
    """Roda uma coleta e devolve o id dela. Uma tentativa por livro, sem retentativas.

    Se o site bloquear LIMITE_BLOQUEIOS vezes seguidas, a execução para: insistir
    só piora o bloqueio.
    """
    sessao = sessao or requests.Session()
    coleta_id = conn.execute(
        "INSERT INTO coletas (iniciada_em) VALUES (?)", (db.agora(),)
    ).lastrowid
    conn.commit()

    tentados = sucesso = bloqueios_seguidos = 0
    observacao = None
    for i, asin in enumerate(asins):
        if bloqueios_seguidos >= LIMITE_BLOQUEIOS:
            observacao = (
                f"interrompida após {LIMITE_BLOQUEIOS} bloqueios seguidos; "
                f"{len(asins) - i} livros não tentados"
            )
            break
        if i > 0:
            dormir(random.uniform(*pausa))

        conn.execute(
            "INSERT OR IGNORE INTO livros (asin, url, criado_em) VALUES (?, ?, ?)",
            (asin, URL_PRODUTO.format(asin=asin), db.agora()),
        )
        html, erro = _baixar(sessao, asin)
        obs = erro or parse_produto(html)
        arquivo = _guardar_html(pasta_html, asin, html) if (pasta_html and html) else None
        _registrar(conn, coleta_id, asin, obs, arquivo)
        conn.commit()

        tentados += 1
        sucesso += obs.status in ("ok", "indisponivel")
        bloqueios_seguidos = bloqueios_seguidos + 1 if obs.status == "bloqueado" else 0
        print(f"[{tentados}/{len(asins)}] {asin}: {obs.status}"
              + (f" R$ {obs.preco_centavos / 100:.2f}" if obs.preco_centavos else ""))

    conn.execute(
        "UPDATE coletas SET finalizada_em = ?, tentados = ?, sucesso = ?, falhas = ?, "
        "observacao = ? WHERE id = ?",
        (db.agora(), tentados, sucesso, tentados - sucesso, observacao, coleta_id),
    )
    conn.commit()
    return coleta_id
