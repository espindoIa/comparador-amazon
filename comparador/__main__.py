"""Linha de comando: python -m comparador {init,coletar,status,lacunas}."""

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

    c = sub.add_parser("coletar", help="coleta os preços da lista de desejos e de livros.txt")
    c.add_argument("--lista", default="livros.txt", help="arquivo com ASINs avulsos")
    c.add_argument("--desejos-arquivo", default="desejos.txt", help="arquivo com links de listas")
    c.add_argument("--desejos", action="append", default=[], metavar="LINK",
                   help="link de uma lista de desejos (pode repetir)")
    c.add_argument("--detalhar", choices=["auto", "todos", "nenhum"], default="auto",
                   help="quando consultar a lista de ofertas de cada livro (padrão: %(default)s)")
    c.add_argument("--cliente", choices=["auto", "navegador", "curl", "requests"], default="auto",
                   help="cliente HTTP; auto = navegador se o Playwright estiver instalado, "
                        "senão curl, senão requests (padrão: %(default)s)")
    c.add_argument("--sem-html", action="store_true", help="não guardar o HTML bruto")
    c.add_argument("--uma-por-dia", action="store_true",
                   help="não faz nada se já houver coleta completa hoje (horário de Brasília); "
                        "feito para ser agendado várias vezes ao dia")

    l = sub.add_parser("lacunas", help="lista os dias sem coleta completa")
    l.add_argument("--ultimos", type=int, metavar="N",
                   help="só os últimos N dias; sai com código 1 se faltar algum (para alertas)")

    sub.add_parser("status", help="mostra as últimas coletas e o último preço de cada livro")

    args = p.parse_args()
    conn = db.conectar(args.db)
    db.criar_schema(conn)

    if args.cmd == "init":
        n = db.importar_eventos(conn, args.eventos) if Path(args.eventos).exists() else 0
        print(f"banco pronto em {args.db}; {n} eventos importados")
    elif args.cmd == "coletar":
        if args.uma_por_dia and db.hoje_brasil() in db.dias_cobertos(conn):
            print(f"{db.hoje_brasil()}: já existe coleta completa hoje; nada a fazer")
            return
        asins = coletor.ler_lista(args.lista) if Path(args.lista).exists() else []
        listas = list(args.desejos)
        if Path(args.desejos_arquivo).exists():
            listas += coletor.ler_desejos(args.desejos_arquivo)
        if not asins and not listas:
            raise SystemExit(
                f"nada para coletar: coloque o link da sua lista de desejos em {args.desejos_arquivo} "
                f"ou ASINs em {args.lista}"
            )
        cid = coletor.coletar(
            conn, asins, listas_desejos=list(dict.fromkeys(listas)), detalhar=args.detalhar,
            cliente=args.cliente,
            pasta_html=None if args.sem_html else Path("data/html"),
        )
        obs = conn.execute("SELECT observacao FROM coletas WHERE id = ?", (cid,)).fetchone()[0]
        if obs:
            print(f"atenção: {obs}")
        if not conn.execute("SELECT completa FROM coletas WHERE id = ?", (cid,)).fetchone()[0]:
            raise SystemExit("coleta incompleta: o dia ainda não está coberto")
    elif args.cmd == "lacunas":
        faltam = db.lacunas(conn)
        if args.ultimos:
            faltam = [d for d in faltam if (db.hoje_brasil() - d).days <= args.ultimos]
        if not db.dias_cobertos(conn):
            raise SystemExit("nenhuma coleta completa registrada ainda")
        for d in faltam:
            print(f"sem coleta completa em {d}")
        print(f"{len(faltam)} dia(s) sem coleta" if faltam else "nenhuma lacuna")
        if args.ultimos and faltam:
            raise SystemExit(1)
    elif args.cmd == "status":
        for r in conn.execute("SELECT * FROM coletas ORDER BY id DESC LIMIT 5"):
            print(f"coleta {r['id']}: {r['iniciada_em']}  {r['sucesso']}/{r['tentados']} ok"
                  + (f"  ({r['observacao']})" if r["observacao"] else ""))
        print()
        for r in conn.execute(
            "SELECT l.asin, l.titulo, p.coletado_em, p.fonte, p.status, p.preco_centavos, "
            "p.preco_capa_centavos FROM livros l LEFT JOIN precos p ON p.id = ("
            "  SELECT id FROM precos WHERE asin = l.asin AND status = 'ok' "
            "  ORDER BY coletado_em DESC, id DESC LIMIT 1) ORDER BY l.titulo"
        ):
            preco = f"R$ {r['preco_centavos'] / 100:7.2f}" if r["preco_centavos"] else "         -"
            capa = f"capa R$ {r['preco_capa_centavos'] / 100:.2f}" if r["preco_capa_centavos"] else ""
            print(f"{r['asin']}  {(r['titulo'] or '')[:40]:40}  {preco}  {capa}")


if __name__ == "__main__":
    main()
