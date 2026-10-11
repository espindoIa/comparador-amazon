"""Lê as páginas de busca da Amazon (resultados de uma categoria, ~16 livros por página).

Armadilhas reais tratadas aqui (todas vistas em out/2026):
- Um card pode ter vários formatos (Capa comum, Kindle, Capa dura), cada um com seu
  ASIN e seu preço. O card pode até ser "do Kindle", com o livro físico como secundário.
  Por isso o preço é lido de dentro do link /dp/ASIN que o contém: cada formato
  fica com o próprio ASIN e o próprio "De:".
- Fora desse link há outros valores que NÃO são o preço: parcelas ("em até 2x de
  R$ 21,73") e a linha de outras ofertas ("Mais opções de compra R$ 13,00").
- Kindle Unlimited aparece como "R$ 0,00": não é preço de venda, é descartado.
- Formato sem preço ("Ver opções") é ignorado.
- Fatia vazia vem com a marca `s-no-results` ("Nenhum resultado"): é fim normal.
- Sem o parâmetro de ordenação (`s=`), a Amazon devolve uma vitrine da categoria, sem
  resultados. Isso é reconhecido como layout desconhecido, não como "fim da lista".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from bs4 import BeautifulSoup

from .parser import parse_preco

URL_BUSCA = "https://www.amazon.com.br/s?i=stripbooks&rh={rh}&s={ordem}&page={pagina}"
ORDENS = {"preco": "price-asc-rank", "vendidos": "exact-aware-popularity-rank"}
_ASIN_LINK_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_TOTAL_RE = re.compile(r"de\s+(mais de\s+)?([\d.]+)\s+resultados")
_FORMATOS = {
    "capa comum": "Capa comum", "capa dura": "Capa dura", "kindle": "Kindle",
    "ebook kindle": "Kindle", "livro de bolso": "Livro de bolso", "box": "Box",
    "edição padrão": "Capa comum", "brochura": "Capa comum", "espiral": "Espiral",
}


class LayoutDesconhecido(Exception):
    """A página não tem a estrutura de resultados esperada (mudança de layout, vitrine etc.)."""


@dataclass
class ItemBusca:
    asin: str
    formato: str | None
    titulo: str | None
    preco_centavos: int
    preco_capa_centavos: int | None = None


@dataclass
class PaginaBusca:
    itens: list[ItemBusca] = field(default_factory=list)
    cards: int = 0                  # cards de resultado (sem patrocinados)
    total: int | None = None        # "710 resultados" ou "mais de 2.000"
    total_exato: bool = False
    ultima_pagina: int | None = None


def url_busca(no: str, preco_min: int, preco_max: int, pagina: int, ordem: str = "preco") -> str:
    """URL de uma fatia.

    ordem "preco": categoria `no`, preços em centavos (inclusive), do menor para o maior.
    ordem "vendidos": categoria `no` inteira, dos mais vendidos para os menos (sem filtro de
    preço; a Amazon só mostra as 75 primeiras páginas nessa ordem).
    """
    rh = f"n:{no}" if ordem == "vendidos" else f"n:{no},p_36:{preco_min}-{preco_max}"
    return URL_BUSCA.format(rh=quote(rh, safe=""), ordem=ORDENS[ordem], pagina=pagina)


_NAO_E_FORMATO = re.compile(r"\d|^(ver|mais|outr|menor preço|oferta|promo)", re.I)


def _formato(texto: str, titulo: str | None = None) -> str | None:
    """Rótulo de formato do card ("Capa Comum", "Kindle", "Canoa, Grampeado ou Costurado"...).

    Os conhecidos são padronizados; um rótulo novo é mantido como veio, em vez de perdido.
    Descarta o que não é formato: título, avaliações "(463)", "Ver opções" etc.
    """
    t = " ".join(texto.split())
    if not t or len(t) > 40 or t == titulo or _NAO_E_FORMATO.search(t):
        return None
    return _FORMATOS.get(t.lower(), t)


def _patrocinado(card) -> bool:
    if "AdHolder" in (card.get("class") or []):
        return True
    rotulo = card.select_one(".puis-sponsored-label-text, .s-sponsored-label-text")
    return bool(rotulo) or card.find(string=re.compile(r"^\s*Patrocinado\s*$")) is not None


def _itens_do_card(card) -> list[ItemBusca]:
    h2 = card.select_one("h2")
    titulo = h2.get_text(" ", strip=True) if h2 else None
    formatos: dict[str, str] = {}
    precos: dict[str, tuple[int, int | None]] = {}
    for a in card.select('a[href*="/dp/"]'):
        m = _ASIN_LINK_RE.search(a.get("href", ""))
        if not m:
            continue
        asin = m.group(1)
        preco_el = a.select_one('.a-price[data-a-color="base"] > .a-offscreen')
        if preco_el is None:
            fmt = _formato(a.get_text(" ", strip=True), titulo)
            if fmt and asin not in formatos:
                formatos[asin] = fmt
            continue
        preco = parse_preco(preco_el.get_text())
        if not preco:  # R$ 0,00 = Kindle Unlimited / grátis: não é preço de venda
            continue
        capa = None
        for s in a.select(".a-offscreen"):
            t = s.get_text(" ", strip=True)
            if t.startswith("De:"):
                capa = parse_preco(t)
                break
        precos.setdefault(asin, (preco, capa))
    return [
        ItemBusca(asin, formatos.get(asin), titulo, preco, capa)
        for asin, (preco, capa) in precos.items()
    ]


def parse_busca(html: str) -> PaginaBusca:
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one('[data-component-type="s-result-info-bar"]')
    cards = soup.select('div[data-component-type="s-search-result"][data-asin]')
    sem_resultados = soup.select_one(".s-no-results, [class*='s-no-results']") is not None
    if info is None and not cards and not sem_resultados:
        raise LayoutDesconhecido("página sem barra de resultados nem cards")

    pagina = PaginaBusca()
    if info is not None:
        m = _TOTAL_RE.search(info.get_text(" ", strip=True).replace("\xa0", " "))
        if m:
            pagina.total = int(m.group(2).replace(".", ""))
            pagina.total_exato = not m.group(1)
    numeros = [
        int(t) for t in (x.get_text(strip=True) for x in soup.select(".s-pagination-strip .s-pagination-item"))
        if t.isdigit()
    ]
    pagina.ultima_pagina = max(numeros) if numeros else None

    vistos = set()
    for card in cards:
        if not card.get("data-asin") or _patrocinado(card):
            continue
        pagina.cards += 1
        for item in _itens_do_card(card):
            if item.asin not in vistos:
                vistos.add(item.asin)
                pagina.itens.append(item)
    return pagina
