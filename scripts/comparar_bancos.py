"""Compara dois bancos do catálogo: quantos livros o novo leu, quantos já estavam no anterior, quantos são novos.

Uso: python scripts/comparar_bancos.py NOVO ANTERIOR
Só lê os dois bancos. Serve para medir o ganho de volume de uma mudança na coleta.
"""

import sqlite3
import sys


def asins(caminho: str) -> dict[str, str | None]:
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return dict(conn.execute("SELECT asin, no FROM catalogo"))
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    novo, antigo = asins(sys.argv[1]), asins(sys.argv[2])
    comuns = novo.keys() & antigo.keys()
    so_novo = novo.keys() - antigo.keys()
    print(f"novo: {len(novo)} livros; anterior: {len(antigo)}")
    print(f"em comum: {len(comuns)} ({len(comuns) / max(len(novo), 1):.0%} do novo); "
          f"só no novo: {len(so_novo)} ({len(so_novo) / max(len(antigo), 1):+.0%} sobre o anterior); "
          f"só no anterior: {len(antigo.keys() - novo.keys())}")
    por = {}
    for a in novo:
        d = por.setdefault(novo[a], [0, 0])
        d[0] += 1
        d[1] += a in antigo
    conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    try:
        paginas, minutos = conn.execute(
            "SELECT SUM(paginas), SUM((julianday(finalizada_em) - julianday(iniciada_em)) * 1440) FROM execucoes").fetchone()
    except sqlite3.DatabaseError:
        paginas = minutos = None
    finally:
        conn.close()
    if paginas:
        print(f"{paginas} páginas em {minutos:.0f} min ({paginas / max(minutos, 1e-9):.0f} páginas/min reais); "
              f"{len(novo) / paginas:.1f} livros por página; {len(so_novo) / paginas:.1f} livros novos (fora do anterior) por página")
    print("por categoria (nó): lidos / já conhecidos")
    for no, (n, k) in sorted(por.items(), key=lambda x: -x[1][0]):
        print(f"  {no}: {n} / {k}")


if __name__ == "__main__":
    main()
