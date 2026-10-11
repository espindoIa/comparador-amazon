"""Linha de comando: python -m comparador {varrer,catalogo,grafico}."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from . import db, rede, varredura


def main() -> None:
    p = argparse.ArgumentParser(prog="comparador", description=__doc__)
    p.add_argument("--db", default="data/catalogo.db", help="banco do catálogo (padrão: %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("varrer", help="lê a categoria inteira (uma vez por dia) pelas páginas de busca")
    v.add_argument("--no", default=varredura.NO_HQ_MANGA,
                   help="nó da categoria (padrão: %(default)s = HQs, Mangás e Graphic Novels)")
    v.add_argument("--vendidos", action="store_true",
                   help="em vez da categoria --no, os 1.200 mais vendidos de cada gênero de Livros "
                        "e do ranking geral (~2.250 páginas por dia)")
    v.add_argument("--minutos", type=float, default=150, help="orçamento de tempo (padrão: %(default)s)")
    v.add_argument("--max-paginas", type=int, help="para depois de N requisições (para testes)")
    v.add_argument("--cliente", choices=["auto", "navegador", "curl", "requests"], default="auto")

    k = sub.add_parser("catalogo", help="progresso de hoje e dias sem varredura completa")
    k.add_argument("--no", default=varredura.NO_HQ_MANGA)
    k.add_argument("--vendidos", action="store_true", help="banco dos mais vendidos")
    k.add_argument("--exigir-ontem", action="store_true",
                   help="sai com código 1 se ontem não teve varredura completa (para alertas)")

    g = sub.add_parser("grafico", help="gráfico HTML do histórico de preço de um livro (números e gráfico, sem conclusões)")
    g.add_argument("livro", help="ASIN ou parte do título")
    g.add_argument("--eventos", default="eventos.csv")
    g.add_argument("--saida", help="arquivo HTML (padrão: data/grafico-<asin>.html)")

    args = p.parse_args()
    conn = db.conectar(args.db)
    if args.cmd in ("varrer", "catalogo"):
        varredura.criar_schema(conn)

    if args.cmd == "grafico":
        from . import relatorio
        achados = relatorio.buscar(conn, args.livro)
        if not achados:
            raise SystemExit(f"nenhum livro encontrado para {args.livro!r} em {args.db}")
        if len(achados) > 1 and args.livro.upper() != achados[0][0]:
            for a, t in achados[:15]:
                print(f"{a}  {t}")
            raise SystemExit(f"{len(achados)} resultados; repita com o ASIN exato")
        asin, titulo = achados[0]
        trechos = relatorio.serie(conn, asin)
        if not trechos:
            raise SystemExit(f"{asin} ainda não tem preço registrado")
        saida = Path(args.saida or f"data/grafico-{asin}.html")
        saida.parent.mkdir(parents=True, exist_ok=True)
        eventos = relatorio.ler_eventos(args.eventos)
        saida.write_text(relatorio.pagina(titulo or asin, asin, trechos, eventos, relatorio.aviso(conn)), encoding="utf-8")
        for e in eventos:
            print(relatorio.resumo_evento(e, relatorio.fatos_evento(trechos, e)))
        print(f"gráfico em {saida}")
    elif args.cmd == "varrer":
        sessao = rede.nova_sessao(args.cliente)
        try:
            vendidos = [varredura.NO_LIVROS, *varredura.GENEROS] if args.vendidos else None
            eid = varredura.varrer(conn, sessao, no=args.no, vendidos=vendidos, minutos=args.minutos,
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
        c = varredura.cobertura(conn, varredura.GRUPO_VENDIDOS if args.vendidos else args.no)
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


if __name__ == "__main__":
    main()
