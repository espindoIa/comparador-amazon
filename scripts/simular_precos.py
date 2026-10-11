"""Simula o histórico de preços até a Black Friday, para testar o gráfico e os números dos eventos.

Usa os livros e preços REAIS de um banco do catálogo como ponto de partida e gera, num banco
NOVO (nunca altera o original), preços diários dentro de uma variação plausível. Os dados são
inventados: o banco leva a tabela `simulacao` e não deve ser misturado ao banco real.

    python scripts/simular_precos.py ORIGEM.db SAIDA.db [--livros 2000] [--semente 1]

Cenários da Black Friday (o sorteio é gravado em `simulacao.cenario` para conferência):
  real      desconto verdadeiro: preço normal, depois queda de 15 a 40% só no dia
  falso     "desconto" de fachada: o preço sobe 15 a 35% nas 3 semanas antes e "cai" de volta
  nenhum    sem promoção; só a oscilação normal
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comparador import varredura  # noqa: E402

INICIO = date(2026, 9, 28)        # 60 dias antes da Black Friday
BLACK_FRIDAY = date(2026, 11, 27)
FIM = date(2026, 11, 30)
OSCILACAO = 0.12                  # o preço normal fica dentro de ±12% do preço lido hoje
CHANCE_MUDANCA = 0.06             # chance diária de o preço normal mudar um pouco


def trechos_do_livro(rng: random.Random, base: int, capa: int | None, cenario: str):
    """Lista de (preco, desde, ate) em dias corridos."""
    teto = capa or int(base * 1.4)
    preco = base
    por_dia: dict[date, int] = {}
    d = INICIO
    while d <= FIM:
        if rng.random() < CHANCE_MUDANCA:
            alvo = base * (1 + rng.uniform(-OSCILACAO, OSCILACAO))
            preco = int(min(max(alvo, base * 0.6), teto))
        p = preco
        if cenario == "falso" and BLACK_FRIDAY - timedelta(days=21) <= d < BLACK_FRIDAY:
            p = int(min(preco * (1 + 0.25), teto))
            p = max(p, int(preco * 1.15))
        elif cenario in ("real", "falso") and d == BLACK_FRIDAY:
            p = int(preco * (1 - rng.uniform(0.15, 0.40))) if cenario == "real" else int(preco * 0.97)
        por_dia[d] = max(p, 100)
        d += timedelta(days=1)
    out: list[list] = []
    for d in sorted(por_dia):
        if out and out[-1][0] == por_dia[d]:
            out[-1][2] = d
        else:
            out.append([por_dia[d], d, d])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("origem")
    ap.add_argument("saida")
    ap.add_argument("--livros", type=int, default=2000)
    ap.add_argument("--semente", type=int, default=1)
    a = ap.parse_args()
    if Path(a.saida).exists():
        raise SystemExit(f"{a.saida} já existe; apague ou escolha outro nome")
    rng = random.Random(a.semente)

    src = sqlite3.connect(f"file:{a.origem}?mode=ro", uri=True)
    linhas = src.execute(
        "SELECT c.asin, c.titulo, c.formato, c.no, h.preco_centavos, h.preco_capa_centavos "
        "FROM catalogo c JOIN historico h ON h.id = (SELECT MAX(id) FROM historico WHERE asin = c.asin) "
        "WHERE c.formato IN ('Capa comum', 'Capa dura') AND h.preco_capa_centavos IS NOT NULL "
        "AND h.preco_centavos <= h.preco_capa_centavos").fetchall()
    rng.shuffle(linhas)
    linhas = linhas[: a.livros]

    out = sqlite3.connect(a.saida)
    out.row_factory = sqlite3.Row
    varredura.criar_schema(out)
    out.execute("CREATE TABLE simulacao (asin TEXT PRIMARY KEY, cenario TEXT NOT NULL)")
    out.execute("CREATE TABLE aviso (texto TEXT)")
    out.execute("INSERT INTO aviso VALUES ('DADOS SIMULADOS: preços inventados a partir de um banco real')")
    for asin, titulo, formato, no, preco, capa in linhas:
        cenario = rng.choices(["real", "falso", "nenhum"], [0.3, 0.3, 0.4])[0]
        out.execute("INSERT INTO catalogo VALUES (?,?,?,?,?,?)", (asin, titulo, formato, no,
                    f"{INICIO}T12:00:00+00:00", f"{FIM}T12:00:00+00:00"))
        out.execute("INSERT INTO simulacao VALUES (?,?)", (asin, cenario))
        for p, d0, d1 in trechos_do_livro(rng, preco, capa, cenario):
            out.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate, vezes) "
                        "VALUES (?,?,?,?,?,?)", (asin, p, capa, f"{d0}T12:00:00+00:00",
                                                 f"{d1}T12:00:00+00:00", (d1 - d0).days + 1))
    out.commit()
    print(f"{len(linhas)} livros simulados de {INICIO} a {FIM} em {a.saida}")


if __name__ == "__main__":
    main()
