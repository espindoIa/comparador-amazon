"""Escolhe as cópias do banco que podem ser apagadas da release "catalogo".

Fica com as RECENTES cópias mais novas (as 4 execuções de cada dia) e, além delas, com a última
cópia de cada um dos DIAS dias anteriores, para dar para voltar a um dia bom se um erro passar
despercebido por mais de três dias. O resto sai, assim como as cópias de testes antigos, sem a
categoria no nome.

Uso: lista de nomes na entrada, um por linha; escreve na saída os que podem ser apagados.
    gh release view catalogo --json assets --jq '.assets[].name' \\
        | python scripts/podar_copias.py --alvo vendidos
"""

import argparse
import re
import sys
from datetime import date, timedelta

RECENTES = 14
DIAS = 30
_ANTIGAS = re.compile(r"^catalogo-\d{4}-[\d-]+\.db\.gz$")


def podar(nomes: list[str], alvo: str, hoje: date, recentes: int = RECENTES, dias: int = DIAS) -> list[str]:
    padrao = re.compile(rf"^catalogo-{re.escape(alvo)}-(\d{{4}}-\d{{2}}-\d{{2}})[\d-]*\.db\.gz$")
    copias = sorted(n for n in nomes if padrao.match(n))     # o nome tem data e hora: ordem = idade
    manter = set(copias[-recentes:]) if recentes else set()
    limite = (hoje - timedelta(days=dias)).isoformat()
    ultima_do_dia: dict[str, str] = {}
    for n in copias:
        ultima_do_dia[padrao.match(n).group(1)] = n
    manter |= {n for dia, n in ultima_do_dia.items() if dia >= limite}
    return [n for n in copias if n not in manter] + sorted(n for n in nomes if _ANTIGAS.match(n))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alvo", required=True)
    p.add_argument("--recentes", type=int, default=RECENTES)
    p.add_argument("--dias", type=int, default=DIAS)
    p.add_argument("--hoje", type=date.fromisoformat, default=date.today())
    a = p.parse_args()
    nomes = [linha.strip() for linha in sys.stdin if linha.strip()]
    for n in podar(nomes, a.alvo, a.hoje, a.recentes, a.dias):
        print(n)


if __name__ == "__main__":
    main()
