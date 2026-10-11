"""Coleta diária de preços.

Fontes, da mais barata para a mais detalhada:
1. Lista de desejos: uma requisição traz ~10 itens com o preço atual.
2. Lista de ofertas do produto: uma requisição por livro, com preço de capa,
   vendedor e condição. Por padrão ("auto") só é consultada quando necessário
   (livro novo, preço mudou na lista, ou detalhe com mais de 7 dias), para fazer
   o mínimo de requisições e reduzir bloqueios.
"""

from __future__ import annotations

import gzip
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import db
from .cliente_http import nova_sessao
from .lista_desejos import (
    ItemLista,
    ListaIndisponivel,
    eh_tela_de_login,
    extrair_id,
    parse_pagina,
    url_da_lista,
)
from .parser import Observacao, parece_bloqueio, parse_ofertas

URL_PRODUTO = "https://www.amazon.com.br/dp/{asin}"
URL_OFERTAS = "https://www.amazon.com.br/gp/product/ajax/aodAjaxMain/?asin={asin}&pc=dp"

PAUSA_PADRAO = (6.0, 14.0)  # segundos entre requisições
PAUSA_APOS_BLOQUEIO = 90.0  # espera extra depois de um bloqueio
LIMITE_BLOQUEIOS = 3  # bloqueios seguidos que interrompem a execução
DETALHE_VALIDO_POR = timedelta(days=7)
MAX_PAGINAS_LISTA = 100
TENTATIVAS_PAGINA_LISTA = 3  # a lista é a fonte principal: vale insistir um pouco

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_URL_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")


def extrair_asin(texto: str) -> str | None:
    """Aceita um ASIN/ISBN-10 puro ou um link da Amazon."""
    texto = texto.strip()
    if _ASIN_RE.match(texto.upper()):
        return texto.upper()
    m = _URL_ASIN_RE.search(texto)
    return m.group(1) if m else None


def _linhas(caminho: str | Path):
    for n, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        linha = linha.split("#", 1)[0].strip()
        if linha:
            yield n, linha


def ler_lista(caminho: str | Path) -> list[str]:
    """Lê livros.txt: um ASIN ou link por linha; '#' inicia comentário."""
    asins: list[str] = []
    for n, linha in _linhas(caminho):
        asin = extrair_asin(linha)
        if asin is None:
            print(f"aviso: linha {n} ignorada (não achei um ASIN): {linha!r}")
        elif asin not in asins:
            asins.append(asin)
    return asins


def ler_desejos(caminho: str | Path) -> list[str]:
    """Lê desejos.txt: um link de lista de desejos por linha."""
    return [linha for _, linha in _linhas(caminho)]


def _guardar_html(pasta: Path | None, nome: str, html: str | None) -> str | None:
    if not (pasta and html):
        return None
    agora = datetime.now(timezone.utc)
    destino = pasta / agora.strftime("%Y-%m-%d") / f"{nome}-{agora.strftime('%H%M%S')}.html.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(gzip.compress(html.encode("utf-8")))
    return str(destino)


def _baixar(sessao, url: str) -> tuple[int | None, str | None, Observacao | None]:
    """Devolve (status_http, html, observação de erro ou None se deu certo)."""
    try:
        resp = sessao.get(url, timeout=30)
    except requests.RequestException as e:
        return None, None, Observacao("erro_http", detalhe=f"{type(e).__name__}: {e}")
    if resp.status_code in (500, 503) or parece_bloqueio(resp.text):
        return resp.status_code, resp.text, Observacao(
            "bloqueado", detalhe=f"HTTP {resp.status_code}: captcha ou página de erro"
        )
    if resp.status_code != 200:
        return resp.status_code, resp.text, Observacao("erro_http", detalhe=f"HTTP {resp.status_code}")
    return resp.status_code, resp.text, None


def _resolver_id(sessao, url_ou_id: str) -> str:
    lista_id = extrair_id(url_ou_id)
    if lista_id is None and url_ou_id.startswith("http"):
        # Link curto (amzn.to / a.co): segue o redirecionamento.
        try:
            lista_id = extrair_id(sessao.get(url_ou_id, timeout=30).url)
        except requests.RequestException as e:
            raise ListaIndisponivel(f"não consegui abrir o link {url_ou_id}: {e}") from e
    if lista_id is None:
        raise ListaIndisponivel(f"não reconheci um link de lista de desejos em {url_ou_id!r}")
    return lista_id


def ler_lista_desejos(
    sessao, url_ou_id: str, *, pasta_html=None, pausa=PAUSA_PADRAO, dormir=time.sleep
) -> tuple[list[ItemLista], str | None]:
    """Devolve (itens, aviso). Se uma página do meio falhar de vez, devolve os itens
    já lidos com um aviso de lista incompleta, em vez de perder tudo."""
    lista_id = _resolver_id(sessao, url_ou_id)
    url: str | None = url_da_lista(lista_id)
    vistos: set[str] = set()
    itens: dict[str, ItemLista] = {}
    pagina = 0
    while url and url not in vistos and pagina < MAX_PAGINAS_LISTA:
        vistos.add(url)
        if pagina:
            dormir(random.uniform(*pausa))
        pagina += 1
        # O 503 da Amazon é intermitente: tenta de novo com espera crescente.
        for tentativa in range(TENTATIVAS_PAGINA_LISTA):
            if tentativa:
                dormir(PAUSA_APOS_BLOQUEIO * tentativa)
            status, html, erro = _baixar(sessao, url)
            _guardar_html(pasta_html, f"lista-{lista_id}-p{pagina}", html)
            if erro is None or erro.status != "bloqueado":
                break
        if status == 404:
            raise ListaIndisponivel("lista não encontrada (404): confira o link")
        if erro:
            msg = f"página {pagina} da lista: {erro.detalhe} (após {TENTATIVAS_PAGINA_LISTA} tentativas)"
            if not itens:
                raise ListaIndisponivel(msg)
            return list(itens.values()), f"lista incompleta ({len(itens)} itens lidos); {msg}"
        novos, url = parse_pagina(html)
        if pagina == 1 and not novos:
            if eh_tela_de_login(html):
                raise ListaIndisponivel(
                    "a Amazon pediu login: a lista é privada. Em 'Suas listas' > 'Gerenciar lista', "
                    "mude a privacidade para 'Pública' ou 'Compartilhada'"
                )
            if url is None and "endOfListMarker" not in html:
                raise ListaIndisponivel(
                    "nenhum item na primeira página: a lista está vazia ou o layout mudou "
                    "(o HTML ficou salvo em data/html/)"
                )
        for item in novos:
            itens.setdefault(item.asin, item)
    return list(itens.values()), None


def _registrar(conn, coleta_id, asin, obs: Observacao, fonte: str, html_arquivo=None) -> None:
    conn.execute(
        "INSERT INTO precos (asin, coleta_id, coletado_em, fonte, status, preco_centavos, "
        "preco_capa_centavos, vendido_por, em_estoque, condicao, html_arquivo, detalhe) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            asin, coleta_id, db.agora(), fonte, obs.status, obs.preco_centavos,
            obs.preco_capa_centavos, obs.vendido_por,
            None if obs.em_estoque is None else int(obs.em_estoque),
            obs.condicao, html_arquivo, obs.detalhe,
        ),
    )
    # Preenche título/autor na primeira vez; não sobrescreve edições manuais.
    conn.execute(
        "UPDATE livros SET titulo = COALESCE(titulo, ?), autor = COALESCE(autor, ?) WHERE asin = ?",
        (obs.titulo, obs.autor, asin),
    )


def _garantir_livro(conn, asin: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO livros (asin, url, criado_em) VALUES (?, ?, ?)",
        (asin, URL_PRODUTO.format(asin=asin), db.agora()),
    )


def _ultimo(conn, asin: str, fonte: str, *, so_ok: bool = True):
    return conn.execute(
        "SELECT preco_centavos, coletado_em FROM precos WHERE asin = ? AND fonte = ? "
        + ("AND status = 'ok' " if so_ok else "")
        + "ORDER BY coletado_em DESC, id DESC LIMIT 1",
        (asin, fonte),
    ).fetchone()


def _precisa_detalhar(conn, asin: str, preco_mudou: bool | None) -> bool:
    """preco_mudou: None se o livro não está em nenhuma lista de desejos."""
    if preco_mudou is None or preco_mudou:
        return True
    ultimo = _ultimo(conn, asin, "ofertas")
    if ultimo is None:
        return True
    limite = (datetime.now(timezone.utc) - DETALHE_VALIDO_POR).isoformat(timespec="seconds")
    return ultimo["coletado_em"] < limite


def coletar(
    conn: sqlite3.Connection,
    asins: list[str],
    *,
    listas_desejos: list[str] = (),
    detalhar: str = "auto",  # "auto", "todos" ou "nenhum"
    sessao=None,
    cliente: str = "auto",
    pasta_html: Path | None = Path("data/html"),
    pausa: tuple[float, float] = PAUSA_PADRAO,
    dormir=time.sleep,
) -> int:
    """Roda uma coleta e devolve o id dela."""
    sessao = sessao or nova_sessao(cliente)
    coleta_id = conn.execute("INSERT INTO coletas (iniciada_em) VALUES (?)", (db.agora(),)).lastrowid
    conn.commit()
    tentados = sucesso = 0
    avisos: list[str] = []
    requisicoes = 0

    # 1. Listas de desejos
    mudou: dict[str, bool] = {}
    for url in listas_desejos:
        if requisicoes:
            dormir(random.uniform(*pausa))
        try:
            itens, aviso = ler_lista_desejos(sessao, url, pasta_html=pasta_html, pausa=pausa, dormir=dormir)
        except ListaIndisponivel as e:
            avisos.append(f"lista {url}: {e}")
            print(f"aviso: lista de desejos {url}: {e}")
            continue
        finally:
            requisicoes += 1
        if aviso:
            avisos.append(f"lista {url}: {aviso}")
            print(f"aviso: {aviso}")
        print(f"lista de desejos: {len(itens)} itens")
        for item in itens:
            _garantir_livro(conn, item.asin)
            anterior = _ultimo(conn, item.asin, "lista_desejos", so_ok=False)
            mudou[item.asin] = mudou.get(item.asin, False) or (
                anterior is None or anterior["preco_centavos"] != item.preco_centavos
            )
            obs = Observacao(
                "ok" if item.preco_centavos else "indisponivel",
                titulo=item.titulo,
                autor=item.autor,
                preco_centavos=item.preco_centavos,
                em_estoque=bool(item.preco_centavos),
            )
            _registrar(conn, coleta_id, item.asin, obs, "lista_desejos")
            tentados += 1
            sucesso += 1
        conn.commit()

    # 2. Lista de ofertas de cada livro
    alvos = list(dict.fromkeys([*asins, *mudou]))
    bloqueios_seguidos = 0
    for i, asin in enumerate(alvos):
        if detalhar == "nenhum":
            break
        if detalhar == "auto" and not _precisa_detalhar(conn, asin, mudou.get(asin)):
            continue
        if bloqueios_seguidos >= LIMITE_BLOQUEIOS:
            avisos.append(
                f"interrompida após {LIMITE_BLOQUEIOS} bloqueios seguidos; "
                f"{len(alvos) - i} livros não consultados"
            )
            break
        if requisicoes:
            dormir(random.uniform(*pausa) + (PAUSA_APOS_BLOQUEIO if bloqueios_seguidos else 0))
        requisicoes += 1

        _garantir_livro(conn, asin)
        _, html, erro = _baixar(sessao, URL_OFERTAS.format(asin=asin))
        obs = erro or parse_ofertas(html)
        _registrar(conn, coleta_id, asin, obs, "ofertas", _guardar_html(pasta_html, asin, html))
        conn.commit()

        tentados += 1
        sucesso += obs.status in ("ok", "indisponivel")
        bloqueios_seguidos = bloqueios_seguidos + 1 if obs.status == "bloqueado" else 0
        preco = f" R$ {obs.preco_centavos / 100:.2f}" if obs.preco_centavos else ""
        print(f"[ofertas] {asin}: {obs.status}{preco}")

    conn.execute(
        "UPDATE coletas SET finalizada_em = ?, tentados = ?, sucesso = ?, falhas = ?, "
        "observacao = ? WHERE id = ?",
        (db.agora(), tentados, sucesso, tentados - sucesso, "; ".join(avisos) or None, coleta_id),
    )
    conn.commit()
    return coleta_id
