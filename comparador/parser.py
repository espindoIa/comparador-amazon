"""Extrai preço e demais dados do HTML de uma página de produto da Amazon Brasil.

Os seletores abaixo vêm do conhecimento do layout e NÃO foram validados contra
páginas reais. Quando a Amazon mudar o layout, o coletor grava status
'erro_parse' ou 'sem_preco' e guarda o HTML bruto, que é o material para ajustar
este arquivo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

_PRECO_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")
_CAPA_RE = re.compile(r"\b(?:Preço de capa|Preço de lista|De)\s*:?\s*R\$\s*([\d.]+,\d{2})", re.I)
_VENDIDO_RE = re.compile(r"vendido por\s+(.+?)(?:\s+e\s+(?:entregue|enviado)\b|\.|$)", re.I)

_MARCAS_DE_BLOQUEIO = (
    "/errors/validateCaptcha",
    "Digite os caracteres",
    "Enter the characters you see",
)

# Só procuramos preço dentro do bloco de preço principal; um seletor global
# pegaria preços de carrosséis de "quem comprou também comprou".
_CONTAINERS_PRECO = (
    "#corePrice_feature_div",
    "#corePriceDisplay_desktop_feature_div",
    "#apex_desktop",
    "#apex_offerDisplay_desktop",
)
_SEL_PRECO_ATUAL = (
    ".priceToPay .a-offscreen",
    ".a-price:not(.a-text-price) .a-offscreen",
)
_SEL_PRECO_CAPA = (
    ".a-price.a-text-price .a-offscreen",
    ".basisPrice .a-offscreen",
)


@dataclass
class Observacao:
    status: str
    titulo: str | None = None
    autor: str | None = None
    preco_centavos: int | None = None
    preco_capa_centavos: int | None = None
    vendido_por: str | None = None
    em_estoque: bool | None = None
    condicao: str | None = None
    detalhe: str | None = None


def parse_preco(texto: str | None) -> int | None:
    """'R$ 1.234,56' -> 123456 (centavos). Devolve None se não houver preço."""
    if not texto:
        return None
    m = _PRECO_RE.search(texto.replace("\xa0", " "))
    if not m:
        return None
    return int(m.group(1).replace(".", "")) * 100 + int(m.group(2))


def _texto(el: Tag | None) -> str | None:
    if el is None:
        return None
    t = " ".join(el.get_text(" ", strip=True).split())
    return t or None


def _primeiro_preco(escopo: Tag, seletores: tuple[str, ...]) -> int | None:
    for sel in seletores:
        for el in escopo.select(sel):
            preco = parse_preco(el.get_text())
            if preco is not None:
                return preco
    return None


def _precos(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    for sel in _CONTAINERS_PRECO:
        bloco = soup.select_one(sel)
        if bloco is None:
            continue
        atual = _primeiro_preco(bloco, _SEL_PRECO_ATUAL)
        if atual is None:
            continue
        capa = _primeiro_preco(bloco, _SEL_PRECO_CAPA)
        if capa is None:
            m = _CAPA_RE.search(_texto(bloco) or "")
            capa = parse_preco(m.group(1)) if m else None
        return atual, capa
    # Layouts antigos
    el = soup.select_one("#price_inside_buybox, #priceblock_ourprice")
    atual = parse_preco(el.get_text()) if el else None
    capa = parse_preco(_texto(soup.select_one("#listPrice")))
    return atual, capa


def _vendedor(soup: BeautifulSoup) -> str | None:
    nome = None
    for el in soup.select("#tabular-buybox .tabular-buybox-text"):
        if (el.get("tabular-attribute-name") or "").strip().lower() == "vendido por":
            nome = _texto(el)
            break
    if nome is None:
        m = _VENDIDO_RE.search(_texto(soup.select_one("#merchant-info")) or "")
        nome = m.group(1).strip() if m else None
    if nome and "amazon" in nome.lower():
        return "Amazon"
    return nome


def _estoque(soup: BeautifulSoup) -> bool | None:
    if soup.select_one("#outOfStock"):
        return False
    txt = (_texto(soup.select_one("#availability")) or "").lower()
    if "indispon" in txt or "não disponível" in txt or "esgotado" in txt:
        return False
    if "em estoque" in txt or "disponível" in txt:
        return True
    return None


def parse_produto(html: str) -> Observacao:
    if any(marca in html for marca in _MARCAS_DE_BLOQUEIO):
        return Observacao("bloqueado", detalhe="página de captcha / verificação de robô")

    soup = BeautifulSoup(html, "html.parser")
    titulo = _texto(soup.select_one("#productTitle"))
    if titulo is None:
        return Observacao(
            "erro_parse",
            detalhe="#productTitle ausente: layout mudou ou não é página de produto",
        )

    autores = [_texto(a) for a in soup.select("#bylineInfo .author > a")]
    autor = ", ".join(a for a in autores if a) or None
    estoque = _estoque(soup)
    atual, capa = _precos(soup)

    base = dict(titulo=titulo, autor=autor, preco_capa_centavos=capa)
    if atual is not None:
        return Observacao(
            "ok",
            preco_centavos=atual,
            vendido_por=_vendedor(soup),
            em_estoque=False if estoque is False else True,
            condicao="novo",
            **base,
        )
    if estoque is False:
        return Observacao("indisponivel", em_estoque=False, **base)
    return Observacao(
        "sem_preco", em_estoque=estoque, detalhe="nenhum preço no bloco principal", **base
    )
