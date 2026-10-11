"""Extrai preço e demais dados da lista de ofertas ("todas as ofertas") de um produto.

Usamos o endpoint de ofertas, e não a página do produto, porque em visitas
automatizadas a página do produto costuma esconder o preço ("adicione ao carrinho
para ver o preço"), enquanto a lista de ofertas traz a oferta principal completa:
preço, preço de capa, condição e vendedor. Também é ~25x menor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

_PRECO_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")

# Página de captcha / página de erro "cachorros da Amazon".
_MARCAS_DE_BLOQUEIO = (
    "/errors/validateCaptcha",
    "Digite os caracteres",
    "Enter the characters you see",
    "amazon.com.br/error/500",
    "Algo deu errado",
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


def parece_bloqueio(html: str) -> bool:
    return any(marca in html for marca in _MARCAS_DE_BLOQUEIO)


def _texto(el: Tag | None) -> str | None:
    if el is None:
        return None
    t = " ".join(el.get_text(" ", strip=True).split())
    return t or None


def _preco_da_oferta(oferta: Tag) -> int | None:
    for sel in (
        ".apex-pricetopay-value .a-offscreen",
        ".apex-pricetopay-accessibility-label",
    ):
        for el in oferta.select(sel):
            preco = parse_preco(el.get_text())
            if preco is not None:
                return preco
    # Último recurso: partes visíveis "34," + "99"
    inteiro = oferta.select_one(".apex-pricetopay-value .a-price-whole")
    fracao = oferta.select_one(".apex-pricetopay-value .a-price-fraction")
    if inteiro and fracao:
        return parse_preco(inteiro.get_text(strip=True).rstrip(",") + "," + fracao.get_text(strip=True))
    return None


def _capa_da_oferta(oferta: Tag) -> int | None:
    for sel in (".apex-basisprice-value .a-offscreen", ".apex-basisprice-offscreen-label"):
        for el in oferta.select(sel):
            preco = parse_preco(el.get_text())
            if preco is not None:
                return preco
    return None


def _condicao(oferta: Tag) -> str | None:
    t = (_texto(oferta.select_one("#aod-offer-heading")) or "").lower()
    if t.startswith("novo"):
        return "novo"
    if t.startswith("usado"):
        return "usado"
    return t or None


def _vendedor(oferta: Tag) -> str | None:
    bloco = oferta.select_one("#aod-offer-soldBy .a-col-right")
    if bloco is None:
        return None
    for el in bloco.select("a, span.a-color-base"):
        nome = _texto(el)
        if nome and "devolução" not in nome.lower():
            return "Amazon" if "amazon" in nome.lower() else nome
    return None


def parse_ofertas(html: str) -> Observacao:
    if parece_bloqueio(html):
        return Observacao("bloqueado", detalhe="captcha ou página de erro da Amazon")

    soup = BeautifulSoup(html, "html.parser")
    titulo = _texto(soup.select_one("#aod-asin-title-text"))
    principal = soup.select_one("#aod-pinned-offer")
    if titulo is None and principal is None:
        return Observacao("erro_parse", detalhe="resposta não parece a lista de ofertas")

    preco = _preco_da_oferta(principal) if principal else None
    detalhe = None
    oferta = principal
    if preco is None:
        # Sem oferta principal: usamos a primeira oferta nova da lista, se houver.
        for o in soup.select("#aod-offer-list #aod-offer"):
            if _condicao(o) == "novo" and _preco_da_oferta(o) is not None:
                oferta, preco = o, _preco_da_oferta(o)
                detalhe = "sem oferta principal; usada a primeira oferta nova"
                break

    if preco is None:
        total = soup.select_one("#aod-total-offer-count")
        sem_ofertas = total is not None and (total.get("value") or "0").strip() == "0"
        return Observacao(
            "indisponivel" if sem_ofertas else "sem_preco",
            titulo=titulo,
            em_estoque=False if sem_ofertas else None,
            detalhe=None if sem_ofertas else "ofertas presentes, mas sem preço legível",
        )

    return Observacao(
        "ok",
        titulo=titulo,
        preco_centavos=preco,
        preco_capa_centavos=_capa_da_oferta(oferta),
        vendido_por=_vendedor(oferta),
        em_estoque=True,
        condicao=_condicao(oferta),
        detalhe=detalhe,
    )
