"""Lê os itens de uma lista de desejos PÚBLICA (ou compartilhada) da Amazon Brasil.

A lista vem paginada: a primeira página traz alguns itens e um campo escondido
`showMoreUrl` com o endereço da página seguinte. Seguimos esses endereços até o fim.
Cada item já traz o preço atual (`data-price`), o que permite acompanhar a lista
inteira com poucas requisições.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://www.amazon.com.br"

_ID_RE = re.compile(r"/(?:hz/wishlist/ls|registry/wishlist|wishlist/ls)/([A-Z0-9]{8,16})", re.I)
_ASIN_EM_PARAMS_RE = re.compile(r"ASIN:([A-Z0-9]{10})")
_ASIN_EM_LINK_RE = re.compile(r"/dp/([A-Z0-9]{10})")


class ListaIndisponivel(Exception):
    """A lista é privada, não existe ou a Amazon pediu login."""


@dataclass
class ItemLista:
    asin: str
    titulo: str | None
    autor: str | None
    preco_centavos: int | None  # None = sem oferta disponível no momento


def extrair_id(url_ou_id: str) -> str | None:
    texto = url_ou_id.strip()
    if re.fullmatch(r"[A-Z0-9]{8,16}", texto):
        return texto
    m = _ID_RE.search(texto)
    return m.group(1).upper() if m else None


def url_da_lista(lista_id: str) -> str:
    # Endereço simples, igual ao link de compartilhamento: com parâmetros extras
    # (filter/sort/viewType) a primeira página recebeu 503 nos testes.
    return f"{BASE}/hz/wishlist/ls/{lista_id}"


def _preco_attr(valor: str | None) -> int | None:
    """data-price vem como '34.99', '1234.5' ou '-Infinity' (sem oferta)."""
    if not valor:
        return None
    try:
        reais = float(valor)
    except ValueError:
        return None
    if reais != reais or reais in (float("inf"), float("-inf")) or reais <= 0:
        return None
    return round(reais * 100)


def _autor(byline: str | None) -> str | None:
    if not byline:
        return None
    # "por Fulana de Tal (Capa comum)" -> "Fulana de Tal"
    t = re.sub(r"^\s*(por|de|by)\s+", "", byline, flags=re.I)
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
    return t or None


def parse_pagina(html: str) -> tuple[list[ItemLista], str | None]:
    """Devolve (itens, url_da_próxima_página ou None)."""
    soup = BeautifulSoup(html, "html.parser")
    itens: list[ItemLista] = []
    for li in soup.select("li[data-itemid]"):
        asin = None
        params = li.get("data-reposition-action-params")
        if params:
            m = _ASIN_EM_PARAMS_RE.search(html_lib.unescape(params))
            asin = m.group(1) if m else None
            if asin is None:
                try:
                    externo = json.loads(params).get("itemExternalId", "")
                    m = _ASIN_EM_PARAMS_RE.search(externo)
                    asin = m.group(1) if m else None
                except (ValueError, AttributeError):
                    pass
        item_id = li.get("data-itemid")
        nome = soup.select_one(f"#itemName_{item_id}") if item_id else None
        if asin is None and nome is not None:
            m = _ASIN_EM_LINK_RE.search(nome.get("href") or "")
            asin = m.group(1) if m else None
        if asin is None:
            continue  # "ideias" e outros itens sem produto
        titulo = (nome.get("title") or nome.get_text(" ", strip=True)) if nome else None
        byline = soup.select_one(f"#item-byline-{item_id}") if item_id else None
        itens.append(
            ItemLista(
                asin=asin,
                titulo=" ".join(titulo.split()) if titulo else None,
                autor=_autor(byline.get_text(" ", strip=True) if byline else None),
                preco_centavos=_preco_attr(li.get("data-price")),
            )
        )

    proxima = None
    if soup.select_one("#endOfListMarker") is None:
        campo = soup.select_one("input.showMoreUrl, input[name=showMoreUrl]")
        if campo and campo.get("value"):
            proxima = urljoin(BASE, campo["value"])
    return itens, proxima


def eh_tela_de_login(html: str) -> bool:
    """Tela de login de verdade, e não o link "Faça login" que toda página tem."""
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one('#ap_email, input[name="email"], form[name="signIn"]')
        or soup.select_one('form[action*="/ap/signin"]')
    )
