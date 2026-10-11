"""Confere um banco SQLite antes de publicá-lo: integridade e "não encolheu".

Uso: python scripts/verificar_banco.py NOVO [ANTERIOR] --tabela T [--tabela T2 ...]
Sai com código 1 se o banco estiver corrompido ou se alguma tabela tiver MENOS linhas
que no banco anterior (sinal de que algo apagou ou recomeçou os dados).
"""

import argparse
import sqlite3
import sys


def contar(caminho: str, tabelas: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as e:
            sys.exit(f"{caminho}: não é um banco SQLite válido ({e})")
        if ok != "ok":
            sys.exit(f"{caminho}: banco corrompido ({ok})")
        existentes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in existentes else 0
                for t in tabelas}
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("novo")
    p.add_argument("anterior", nargs="?")
    p.add_argument("--tabela", action="append", required=True)
    a = p.parse_args()
    novo = contar(a.novo, a.tabela)
    print("novo:", novo)
    if a.anterior:
        antes = contar(a.anterior, a.tabela)
        print("anterior:", antes)
        encolheu = [t for t in a.tabela if novo[t] < antes[t]]
        if encolheu:
            sys.exit(f"recusado: {', '.join(encolheu)} tem menos linhas que antes")


if __name__ == "__main__":
    main()
