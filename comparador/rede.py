"""Acesso à Amazon: download com detecção de bloqueio, preço em centavos e HTML bruto de depuração."""

from __future__ import annotations

import gzip
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .cliente_http import nova_sessao  # noqa: F401  (reexportado para o CLI)

PAUSA_APOS_BLOQUEIO = 90.0  # espera extra depois de um bloqueio

_PRECO_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")

# Página de captcha / página de erro "cachorros da Amazon". O erro é reconhecido pelo
# <title>, e não por uma frase solta, que também aparece escondida em páginas normais.
_MARCAS_DE_BLOQUEIO = (
    "/errors/validateCaptcha",
    "Digite os caracteres",
    "Enter the characters you see",
    "amazon.com.br/error/500",
)
_TITULO_ERRO_RE = re.compile(r"<title>[^<]*Algo deu errado", re.I)

@dataclass
class Erro:
    status: str  # 'bloqueado' ou 'erro_http'
    detalhe: str

def parse_preco(texto: str | None) -> int | None:
    """'R$ 1.234,56' -> 123456 (centavos). Devolve None se não houver preço."""
    if not texto:
        return None
    m = _PRECO_RE.search(texto.replace("\xa0", " "))
    if not m:
        return None
    return int(m.group(1).replace(".", "")) * 100 + int(m.group(2))

def parece_bloqueio(html: str) -> bool:
    return any(marca in html for marca in _MARCAS_DE_BLOQUEIO) or bool(_TITULO_ERRO_RE.search(html))

def guardar_html(pasta: Path | None, nome: str, html: str | None) -> str | None:
    if not (pasta and html):
        return None
    agora = datetime.now(timezone.utc)
    destino = pasta / agora.strftime("%Y-%m-%d") / f"{nome}-{agora.strftime('%H%M%S')}.html.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(gzip.compress(html.encode("utf-8")))
    return str(destino)

def classificar(resp) -> tuple[int | None, str | None, Erro | None]:
    """Resposta -> (status_http, html, erro ou None). Status 0 = a requisição nem chegou (rede, tempo)."""
    if resp.status_code == 0:
        return None, None, Erro("erro_http", f"falha de rede: {resp.text[:120]}")
    if resp.status_code in (500, 503) or parece_bloqueio(resp.text):
        return resp.status_code, resp.text, Erro("bloqueado", f"HTTP {resp.status_code}: captcha ou página de erro")
    if resp.status_code != 200:
        return resp.status_code, resp.text, Erro("erro_http", f"HTTP {resp.status_code}")
    return resp.status_code, resp.text, None


def baixar(sessao, url: str) -> tuple[int | None, str | None, Erro | None]:
    """Devolve (status_http, html, erro ou None se deu certo)."""
    try:
        resp = sessao.get(url, timeout=30)
    except requests.RequestException as e:
        return None, None, Erro("erro_http", f"{type(e).__name__}: {e}")
    return classificar(resp)


def baixar_lote(sessao, urls: list[str], atrasos: list[float], dormir=time.sleep, relogio=time.monotonic):
    """Baixa várias páginas, a i-ésima `atrasos[i]` segundos depois do início do lote.

    Com o navegador, as requisições do lote ficam em andamento ao mesmo tempo (o escalonamento é feito
    dentro da página). Nos outros clientes, e com uma página só, é uma de cada vez, nos mesmos instantes.
    Devolve uma lista de (status, html, erro), na ordem de `urls`.
    """
    if len(urls) > 1 and hasattr(sessao, "get_lote"):
        try:
            return [classificar(r) for r in sessao.get_lote(urls, atrasos, timeout=30)]
        except requests.RequestException as e:
            return [(None, None, Erro("erro_http", f"{type(e).__name__}: {e}")) for _ in urls]
    inicio = relogio()
    saida = []
    for url, atraso in zip(urls, atrasos):
        falta = atraso - (relogio() - inicio)
        if falta > 0:
            dormir(falta)
        saida.append(baixar(sessao, url))
    return saida
