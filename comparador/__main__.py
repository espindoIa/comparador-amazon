"""Linha de comando: python -m comparador {init,coletar,status}."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import coletor, db


def main() -> None:
    p = argparse.ArgumentParser(prog="comparador", description=__doc__)
    p.add_argument("--db", default="data/precos.db", help="arquivo do banco (padrão: %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="cria o banco e importa eventos.csv")
    i.add_argument("--eventos", default="eventos.csv")

    c = sub.add_parser("coletar", help="coleta o preço dos livros de livros.txt")
    c.add_argument("--lista", default="livros.txt")
    c.add_argument("--sem-html", action="store_true", help="não guardar o HTML bruto")

    sub.add_parser("status", help="mostra as últimas coletas e o último preço de cada livro")

    args = p.parse_args()
    conn = db.conectar(args.db)
    db.criar_schema(conn)

    if args.cmd == "init":
        n = db.importar_eventos(conn, args.eventos) if Path(args.eventos).exists() else 0
        print(f"banco pronto em {args.db}; {n} eventos importados")
    elif args.cmd == "coletar":
        asins = coletor.ler_lista(args.lista)
        if not asins:
            raise SystemExit(f"nenhum ASIN em {args.lista}; adicione um por linha")
        coletor.coletar(conn, asins, pasta_html=None if args.sem_html else Path("data/html"))
    elif args.cmd == "status":
        for r in conn.execute("SELECT * FROM coletas ORDER BY id DESC LIMIT 5"):
            print(f"coleta {r['id']}: {r['iniciada_em']}  {r['sucesso']}/{r['tentados']} ok"
                  + (f"  ({r['observacao']})" if r["observacao"] else ""))
        print()
        for r in conn.execute(
            "SELECT l.asin, l.titulo, p.coletado_em, p.status, p.preco_centavos "
            "FROM livros l LEFT JOIN precos p ON p.id = ("
            "  SELECT id FROM precos WHERE asin = l.asin ORDER BY coletado_em DESC, id DESC LIMIT 1)"
        ):
            preco = f"R$ {r['preco_centavos'] / 100:.2f}" if r["preco_centavos"] else "-"
            print(f"{r['asin']}  {(r['titulo'] or '')[:40]:40}  {r['status'] or '-':12} {preco}")


if __name__ == "__main__":
    main()
