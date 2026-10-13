"""Confere os preços do banco novo contra os do anterior antes de publicar: um erro de leitura de preço
(preço em reais lido como centavos, formato novo de preço na página) mudaria quase todos os preços de uma vez.

Uso: python scripts/verificar_precos.py NOVO ANTERIOR [--forcar]
Só livros físicos (o Kindle tem ofertas do dia que mudam muita coisa à meia-noite, e isso é normal).
Compara o último preço de cada livro presente nos dois bancos. Recusa (código 1) se, com pelo menos
MIN_COMPARAVEIS livros: mais de MAX_MUDARAM dos preços mudaram, ou mais de MAX_EXTREMOS mudaram para menos
de um quinto ou mais de cinco vezes o anterior (a troca de reais por centavos dá 100%), ou há preços fora de R$ 0,50 a R$ 50 mil.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comparador.site import familia  # noqa: E402

MIN_COMPARAVEIS = 1000
MAX_MUDARAM = 0.60        # fração dos livros comparáveis (na Black Friday muita coisa muda, mas não tudo)
MAX_EXTREMOS = 0.02
MAX_FORA_DA_FAIXA = 0.005
PRECO_MIN, PRECO_MAX = 50, 5_000_000    # centavos


def _ultimos(conn: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    """{asin: (último preço, formato)}"""
    return {a: (p, f) for a, p, f in conn.execute(
        "SELECT h.asin, h.preco_centavos, k.formato FROM historico h JOIN catalogo k USING (asin) "
        "WHERE h.id IN (SELECT MAX(id) FROM historico GROUP BY asin)")}


def medir(novo: Path, anterior: Path) -> dict:
    a = sqlite3.connect(f"file:{anterior}?mode=ro", uri=True)
    n = sqlite3.connect(f"file:{novo}?mode=ro", uri=True)
    try:
        antes, agora = _ultimos(a), _ultimos(n)
    finally:
        a.close()
        n.close()
    fisico = lambda f: familia(f) == "f"      # noqa: E731
    comparaveis = [(antes[k][0], p) for k, (p, f) in agora.items() if k in antes and fisico(f)]
    mudaram = [(x, y) for x, y in comparaveis if x != y]
    extremos = [1 for x, y in mudaram if y < x / 5 or y > x * 5]
    novos_fisicos = [p for k, (p, f) in agora.items() if fisico(f)]
    fora = [1 for p in novos_fisicos if not PRECO_MIN <= p <= PRECO_MAX]
    c = max(len(comparaveis), 1)
    return {"comparaveis": len(comparaveis), "mudaram": len(mudaram) / c, "extremos": len(extremos) / c,
            "fora_da_faixa": len(fora) / max(len(novos_fisicos), 1)}


def problema(m: dict) -> str | None:
    if m["fora_da_faixa"] > MAX_FORA_DA_FAIXA:
        return f"{m['fora_da_faixa']:.1%} dos preços estão fora de R$ 0,50 a R$ 50 mil"
    if m["comparaveis"] < MIN_COMPARAVEIS:
        return None
    if m["mudaram"] > MAX_MUDARAM:
        return f"{m['mudaram']:.0%} dos preços dos livros físicos mudaram de uma vez (limite {MAX_MUDARAM:.0%})"
    if m["extremos"] > MAX_EXTREMOS:
        return f"{m['extremos']:.1%} dos preços mudaram para menos de 1/5 ou mais de 5x (limite {MAX_EXTREMOS:.0%})"
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("novo", type=Path)
    p.add_argument("anterior", type=Path, nargs="?")
    p.add_argument("--forcar", action="store_true", help="só avisa, não recusa")
    a = p.parse_args()
    if not a.anterior:
        print("sem banco anterior; nada a comparar")
        return
    m = medir(a.novo, a.anterior)
    print(f"preços: {m['comparaveis']} livros físicos comparáveis; {m['mudaram']:.1%} mudaram, "
          f"{m['extremos']:.2%} em mais de 5x, {m['fora_da_faixa']:.2%} fora da faixa")
    motivo = problema(m)
    if motivo:
        print(f"{'aviso' if a.forcar else 'recusado'}: {motivo}")
        if not a.forcar:
            sys.exit(1)


if __name__ == "__main__":
    main()
