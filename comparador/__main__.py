"""Linha de comando: python -m comparador {init,coletar,status,lacunas,varrer,catalogo}."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from . import coletor, db, varredura


def main() -> None:
    p = argparse.ArgumentParser(prog="comparador", description=__doc__)
    p.add_argument("--db", help="arquivo do banco (padrão: data/precos.db; data/catalogo.db "
                                "para varrer e catalogo)")
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

    v = sub.add_parser("varrer", help="lê a categoria inteira (uma vez por dia) pelas páginas de busca")
    v.add_argument("--no", default=varredura.NO_HQ_MANGA,
                   help="nó da categoria (padrão: %(default)s = HQs, Mangás e Graphic Novels)")
    v.add_argument("--minutos", type=float, default=150, help="orçamento de tempo (padrão: %(default)s)")
    v.add_argument("--max-paginas", type=int, help="para depois de N requisições (para testes)")
    v.add_argument("--cliente", choices=["auto", "navegador", "curl", "requests"], default="auto")

    k = sub.add_parser("catalogo", help="progresso de hoje e dias sem varredura completa")
    k.add_argument("--no", default=varredura.NO_HQ_MANGA)
    k.add_argument("--exigir-ontem", action="store_true",
                   help="sai com código 1 se ontem não teve varredura completa (para alertas)")

    args = p.parse_args()
    catalogo = args.cmd in ("varrer", "catalogo")
    args.db = args.db or ("data/catalogo.db" if catalogo else "data/precos.db")
    conn = db.conectar(args.db)
    if catalogo:
        varredura.criar_schema(conn)
    else:
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
    elif args.cmd == "varrer":
        sessao = coletor.nova_sessao(args.cliente)
        try:
            eid = varredura.varrer(conn, sessao, no=args.no, minutos=args.minutos,
                                   max_paginas=args.max_paginas, pasta_html=Path("data/html"))
        finally:
            if hasattr(sessao, "fechar"):
                sessao.fechar()
        if eid is None:
            print(f"{db.hoje_brasil()}: varredura do dia já está completa; nada a fazer")
            return
        e = conn.execute("SELECT * FROM execucoes WHERE id = ?", (eid,)).fetchone()
        print(f"execução {eid}: {e['paginas']} páginas, {e['itens']} preços, "
              f"{e['bloqueios']} bloqueios, {e['erros']} erros")
        if e["observacao"]:
            print(f"atenção: {e['observacao']}")
        if e["paginas"] == 0 and (e["bloqueios"] or e["erros"]):
            raise SystemExit("nenhuma página lida")
    elif args.cmd == "catalogo":
        c = varredura.cobertura(conn, args.no)
        print(f"{c.itens} itens no catálogo; {c.vistos_hoje} com preço lido hoje")
        print(f"hoje: {c.fatias_hoje} de {c.fatias} fatias lidas" + (" (dia completo)" if c.dia_completo else ""))
        print("dias sem varredura completa: " + (", ".join(map(str, c.lacunas)) if c.lacunas else "nenhum"))
        for r in conn.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 5"):
            print(f"execução {r['id']}: {r['iniciada_em']}  {r['paginas']} páginas, {r['itens']} preços, "
                  f"{r['bloqueios']} bloqueios, {r['erros']} erros"
                  + (f"  ({r['observacao']})" if r["observacao"] else ""))
        ontem = db.hoje_brasil() - timedelta(days=1)
        if args.exigir_ontem and ontem in c.lacunas:
            raise SystemExit(f"{ontem} ficou sem varredura completa")
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
