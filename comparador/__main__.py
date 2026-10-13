"""Linha de comando: python -m comparador {varrer,catalogo,grafico,site}."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from . import db, rede, ritmo, varredura


def main() -> None:
    p = argparse.ArgumentParser(prog="comparador", description=__doc__)
    p.add_argument("--db", default="data/catalogo.db", help="banco do catálogo (padrão: %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("varrer", help="lê a categoria inteira (uma vez por dia) pelas páginas de busca")
    v.add_argument("--no", default=varredura.NO_HQ_MANGA,
                   help="nó da categoria (padrão: %(default)s = HQs, Mangás e Graphic Novels)")
    v.add_argument("--vendidos", action="store_true",
                   help="em vez da categoria --no, os ~2.000 livros mais vendidos (com preço) de cada "
                        "um dos 29 gêneros de Livros, em 9 faixas de preço (~13 mil páginas por passada)")
    v.add_argument("--minutos", type=float, default=150, help="orçamento de tempo (padrão: %(default)s)")
    v.add_argument("--max-paginas", type=int, help="para depois de N requisições (para testes)")
    v.add_argument("--cliente", choices=["auto", "navegador", "curl", "requests"], default="auto",
                   help="como ler as páginas (padrão: %(default)s = só o navegador; se ele não abrir, para e diz por quê). "
                        "curl e requests só quando pedidos: a Amazon costuma bloqueá-los, e um bloqueio grava no banco "
                        "uma pausa de horas")
    v.add_argument("--ritmo", type=float, default=None,
                   help="páginas por minuto no começo (padrão: 80%% do último ritmo limpo guardado no banco, "
                        f"ou {ritmo.PPM_BASE:g}, o ritmo medido sem bloqueios)")
    v.add_argument("--ritmo-max", type=float, default=None,
                   help="teto de páginas por minuto programadas (o real fica ~10-20%% abaixo): o ritmo sobe aos "
                        "poucos até ele enquanto não há falha e recua nas falhas. Sem esta opção, o teto é o que "
                        f"está guardado no banco (começa em {ritmo.PPM_TETO_PADRAO:g}) e sobe 25%% por dia "
                        f"limpo até {ritmo.PPM_TETO_AUTO_MAX:g} (ou até --teto-auto-max); com ela, o valor é fixo e nada é aprendido")
    v.add_argument("--teto-auto-max", type=float, default=ritmo.PPM_TETO_AUTO_MAX,
                   help="até onde o teto guardado no banco pode subir sozinho (padrão: %(default)g). Vale também sobre um "
                        "teto já guardado acima dele. Com várias sequências em paralelo, é o limite de cada uma; "
                        "só vale sem --ritmo-max")
    v.add_argument("--faixas", help="com --vendidos: bordas das faixas de preço em reais, ex.: 0,20,30,40,50,60,80,120,200 "
                                    "(padrão: " + ",".join(f"{a / 100:g}" for a, _ in varredura.FAIXAS_VENDIDOS) + ")")
    v.add_argument("--generos", help="com --vendidos: só estes nós, separados por vírgula (padrão: os 29 gêneros; "
                                     "o ranking geral de Livros, 6740748011, só se for pedido aqui)")
    v.add_argument("--particao", choices=list(varredura.PARTICOES_VENDIDOS),
                   help="com --vendidos: só os gêneros desta sequência de coleta (uma por servidor em varredura.yml; "
                        "ver PARTICOES_VENDIDOS)")
    v.add_argument("--ciclo-horas", type=int, choices=ritmo.CICLOS, default=None,
                   help="horas entre passadas completas do catálogo (padrão: o degrau guardado no banco, que começa em "
                        f"{ritmo.CICLO_INICIAL} h e desce um degrau por dia limpo até {ritmo.CICLOS[0]} h). Com esta opção, o "
                        "ciclo fica fixo e nada é aprendido")
    v.add_argument("--ignorar-pausa", action="store_true",
                   help="lê mesmo durante a pausa que segue um bloqueio (horas, de propósito: cada execução cai num IP novo)")
    v.add_argument("--subir-a-cada", type=int, default=ritmo.A_CADA,
                   help="páginas boas seguidas para cada subida de 25%% do ritmo (padrão: %(default)s)")
    v.add_argument("--parar-na-falha", action="store_true",
                   help="termina na primeira falha (bloqueio, erro ou página curta), sem insistir; para medir "
                        "até que ritmo a coleta passa limpa")

    k = sub.add_parser("catalogo", help="progresso de hoje e dias sem varredura completa")
    k.add_argument("--no", default=varredura.NO_HQ_MANGA)
    k.add_argument("--vendidos", action="store_true", help="banco dos mais vendidos")
    k.add_argument("--exigir-ontem", action="store_true",
                   help="sai com código 1 se ontem não teve varredura completa (para alertas)")
    k.add_argument("--exigir-frescor", action="store_true",
                   help="sai com código 1 se alguma fatia está sem passada completa há mais de 2 ciclos e 2 h (a coleta parou "
                        "ou não dá conta do ciclo; para alertas)")
    k.add_argument("--exigir-detalhes", action="store_true",
                   help="sai com código 1 se a última execução avisou que os cards vieram sem capa ou autor (para alertas)")

    g = sub.add_parser("grafico", help="gráfico HTML do histórico de preço de um livro (números e gráfico, sem conclusões)")
    g.add_argument("livro", help="ASIN ou parte do título")
    g.add_argument("--eventos", default="eventos.csv")
    g.add_argument("--saida", help="arquivo HTML (padrão: data/grafico-<asin>.html)")

    w = sub.add_parser("site", help="gera o site estático (busca por título, histórico e lista de desejos)")
    w.add_argument("bancos", nargs="+", help="um ou mais bancos do catálogo")
    w.add_argument("--saida", default="site", help="pasta de saída (padrão: %(default)s)")
    w.add_argument("--eventos", default="eventos.csv")

    args = p.parse_args()
    if args.cmd == "site":
        from . import site
        meta = site.construir([Path(b) for b in args.bancos], Path(args.saida), Path(args.eventos))
        print(f"site em {args.saida}: {meta['itens']} livros")
        return
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
        print(f"gráfico em {saida}")
    elif args.cmd == "varrer":
        try:
            vendidos = varredura.nos_vendidos(args.generos, args.particao) if args.vendidos else None
            faixas = varredura.faixas_de_precos(args.faixas.split(",")) if args.faixas else None
        except ValueError as e:
            raise SystemExit(f"opção inválida: {e}")
        if args.ciclo_horas is None and not args.ignorar_pausa and (pausa := varredura.pausa_vigente(conn)):
            print(f"em pausa até {pausa.isoformat(timespec='minutes')} (bloqueio recente); nada a fazer. "
                  "Para ler assim mesmo: --ignorar-pausa")
            return
        sessao = rede.nova_sessao(args.cliente)
        try:
            res = varredura.executar(
                conn, sessao, no=args.no, vendidos=vendidos, minutos=args.minutos, max_paginas=args.max_paginas,
                faixas=faixas, ritmo_inicial=args.ritmo, ritmo_max=args.ritmo_max, teto_auto_max=args.teto_auto_max,
                subir_a_cada=args.subir_a_cada, ciclo_horas=args.ciclo_horas, ignorar_pausa=args.ignorar_pausa,
                parar_na_falha=args.parar_na_falha, pasta_html=Path("data/html"))
        finally:
            if hasattr(sessao, "fechar"):
                sessao.fechar()
        if res.exec_id is None:
            print(f"{db.hoje_brasil()}: ciclo de {res.ciclo_horas} h já está completo; nada a fazer")
            return
        e = conn.execute("SELECT * FROM execucoes WHERE id = ?", (res.exec_id,)).fetchone()
        if "ritmo_teto" in res.config_ritmo:
            print(f"ritmo: teto guardado no banco passa de {res.teto:.0f} para {float(res.config_ritmo['ritmo_teto']):.0f}")
        if "ciclo_horas" in res.config_ciclo and res.config_ciclo["ciclo_horas"] != str(res.ciclo_horas):
            print(f"ciclo: passa de {res.ciclo_horas} h para {res.config_ciclo['ciclo_horas']} h")
        if "ritmo_pausa_ate" in res.config_ciclo:
            print(f"pausa: sem leitura até {res.config_ciclo['ritmo_pausa_ate']}")
        print(f"execução {res.exec_id}: {e['paginas']} páginas, {e['itens']} preços, {e['bloqueios']} bloqueios, "
              f"{e['erros']} erros, {e['curtas']} páginas curtas, {e['ppm']} páginas/min; "
              + ("ciclo completo" if res.completou else "ciclo incompleto"))
        if e["observacao"]:
            print(f"atenção: {e['observacao']}")
        if e["paginas"] == 0 and (e["bloqueios"] or e["erros"]):
            raise SystemExit("nenhuma página lida")
    elif args.cmd == "catalogo":
        c = varredura.cobertura(conn, varredura.GRUPO_VENDIDOS if args.vendidos else args.no)
        print(f"{c.itens} itens no catálogo; {c.vistos_hoje} com preço lido hoje")
        print(f"hoje: {c.fatias_hoje} de {c.fatias} fatias lidas" + (" (dia completo)" if c.dia_completo else ""))
        print("dias sem varredura completa: " + (", ".join(map(str, c.lacunas)) if c.lacunas else "nenhum"))
        if c.mais_antiga_h is not None:
            print(f"frescor: ciclo de {c.ciclo_horas} h; a passada completa mais velha tem {c.mais_antiga_h:.1f} h"
                  f" (limite {varredura.limite_atraso(c.ciclo_horas):g} h); {c.atrasadas} fatias atrasadas"
                  + (f", {c.nunca_lidas} nunca lidas" if c.nunca_lidas else ""))
        pausa = varredura.pausa_vigente(conn)
        if pausa:
            print(f"pausa depois de bloqueio até {pausa.isoformat(timespec='minutes')}")
        n, fracoes = varredura.preenchimento(conn, varredura.inicio_do_dia())
        if n:
            print(f"detalhes dos {n} itens lidos hoje: " + ", ".join(
                f"{nome} {fracoes[c]:.0%}" for c, nome in varredura.CAMPOS_PREENCHIMENTO.items()))
        for r in conn.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 5"):
            print(f"execução {r['id']}: {r['iniciada_em']}  {r['paginas']} páginas, {r['itens']} preços, "
                  f"{r['bloqueios']} bloqueios, {r['erros']} erros, {r['curtas']} curtas, {r['ppm'] or '?'} pág/min"
                  + (f"  ({r['observacao']})" if r["observacao"] else ""))
        ontem = db.hoje_brasil() - timedelta(days=1)
        if args.exigir_ontem and ontem in c.lacunas:
            raise SystemExit(f"{ontem} ficou sem varredura completa")
        if args.exigir_frescor and c.atrasadas:
            raise SystemExit(f"{c.atrasadas} fatias sem passada completa há mais de {varredura.limite_atraso(c.ciclo_horas):g} h")
        ultima = conn.execute("SELECT observacao FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()
        if args.exigir_detalhes and ultima and varredura.AVISO_LAYOUT in (ultima[0] or ""):
            raise SystemExit(f"a última execução avisou: {ultima[0]}")


if __name__ == "__main__":
    main()
