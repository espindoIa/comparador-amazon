"""Preços de livros da Amazon.com.br: coleta (varrer), acompanhamento (catalogo), gráfico de um livro (grafico) e site (site)."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import cliente_http, db, rede, ritmo, varredura

DB_PADRAO = "data/vendidos.db"
EVENTOS_PADRAO = Path(__file__).resolve().parent.parent / "eventos.csv"     # sem ele (instalado fora do repositório): sem datas de promoção


def _numero_positivo(texto: str) -> float:
    try:
        v = float(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{texto!r} não é um número") from None
    if not (math.isfinite(v) and v > 0):
        raise argparse.ArgumentTypeError(f"deve ser maior que 0 (veio {texto})")
    return v


def _inteiro_positivo(texto: str) -> int:
    try:
        v = int(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{texto!r} não é um número inteiro") from None
    if v < 1:
        raise argparse.ArgumentTypeError(f"deve ser pelo menos 1 (veio {texto})")
    return v


def _mais_vendidos(args, parser) -> bool:
    """O modo de coleta: os mais vendidos dos gêneros de Livros (padrão) ou, com --no, uma categoria só."""
    if args.no is not None and args.vendidos:
        parser.error("--vendidos e --no se excluem: --vendidos já é o padrão, e --no lê só a categoria dada")
    return args.no is None


def _opcoes_de_coleta(args) -> tuple[list[str] | None, list[tuple[int, int]] | None]:
    """Os nós (--generos, --particao) e as faixas de preço (--faixas) pedidos; encerra se não valem."""
    try:
        vendidos = varredura.nos_vendidos(args.generos, args.particao) if args.mais_vendidos else None
        faixas = varredura.faixas_de_precos(args.faixas.split(",")) if args.faixas else None
    except ValueError as e:
        raise SystemExit(f"opção inválida: {e}")
    return vendidos, faixas


def _eventos(args) -> Path:
    """O eventos.csv: o do repositório se não se pediu outro; um pedido que não existe é erro, não "sem promoções"."""
    if args.eventos is None:
        return EVENTOS_PADRAO
    caminho = Path(args.eventos)
    if not caminho.exists():
        raise SystemExit(f"arquivo de eventos não encontrado: {caminho} (colunas nome,inicio,fim)")
    return caminho


def _exigir_banco(args) -> None:
    """catalogo e grafico só leem: um banco que não existe é erro (o arquivo vazio que o sqlite criaria pareceria um catálogo vazio)."""
    if Path(args.db).exists():
        return
    dica = ""
    if args.db == DB_PADRAO and Path("data/catalogo.db").exists():
        dica = " (o padrão era data/catalogo.db; para ele, use --db data/catalogo.db)"
    raise SystemExit(f"banco não encontrado: {args.db}{dica}. Só o varrer cria o banco; use --db para apontar o arquivo certo")


def _plano(args, vendidos, faixas) -> None:
    """--dry-run: o que o `varrer` faria com estas opções. Não abre o navegador, não pede nada à Amazon e não grava:
    o banco só é lido, e só se já existir."""
    existe = Path(args.db).exists()
    config: dict = {}
    if existe:
        conn = db.abrir_leitura(args.db, "catálogo")
        try:
            config = varredura.ler_config(conn)
        except sqlite3.OperationalError:       # banco sem a tabela config: o varrer nunca rodou nele
            pass
        finally:
            conn.close()
    r = varredura.ritmo_da_execucao(config, ritmo_inicial=args.ritmo, ritmo_max=args.ritmo_max,
                                    teto_auto_max=args.teto_auto_max, subir_a_cada=args.subir_a_cada)
    print("dry-run: nada foi lido da Amazon nem gravado")
    print(f"banco: {args.db}" + (" (aberto só para leitura)" if existe else " (ainda não existe; o varrer o criaria)"))
    print(varredura.descrever_ritmo(r, args.ritmo_max is None, args.ciclo_horas or ritmo.ciclo_guardado(config),
                                    args.ciclo_horas is None))
    pausa = ritmo.pausa_ate(config)
    if not pausa or pausa <= datetime.fromisoformat(db.agora()):
        print("pausa: nenhuma")
    elif args.ciclo_horas is None and not args.ignorar_pausa:
        print(f"pausa: até {pausa.isoformat(timespec='minutes')} (bloqueio recente); o varrer não leria nada. "
              "Para ler assim mesmo: --ignorar-pausa")
    else:
        print(f"pausa: até {pausa.isoformat(timespec='minutes')}, ignorada por {'--ignorar-pausa' if args.ignorar_pausa else '--ciclo-horas'}")
    if vendidos is None:
        print(f"fatias: categoria {args.no}")
    else:
        n = len(faixas or varredura.FAIXAS_VENDIDOS)
        print(f"fatias: {len(vendidos)} gêneros × {n} faixas de preço = {len(vendidos) * n}")
    print(f"orçamento: {args.minutos:g} min" + (f"; para depois de {args.max_paginas} requisições" if args.max_paginas else "")
          + ("; para na primeira falha" if args.parar_na_falha else ""))
    problema = cliente_http.problema_do_cliente(args.cliente)
    print(f"cliente: {args.cliente}"
          + (" (o módulo playwright está instalado; o Chrome ou Edge só é procurado na execução)"
             if not problema and args.cliente in ("auto", "navegador") else ""))
    if problema:
        raise SystemExit(f"a execução pararia aqui: {problema}")


def main() -> None:
    exemplos = """exemplos:
  comparador varrer --dry-run                       confere as opções e mostra o plano, sem pedir nada à Amazon
  comparador varrer --minutos 20                    lê por 20 minutos os mais vendidos de cada gênero
  comparador catalogo                               progresso de hoje e frescor do catálogo
  comparador grafico "título ou ASIN"               página avulsa com o histórico de preço de um livro
  comparador site data/vendidos.db --saida site     gera o site"""
    fmt = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(prog="comparador", description=__doc__, epilog=exemplos, formatter_class=fmt)
    p.add_argument("--db", default=DB_PADRAO, help="banco do catálogo (padrão: %(default)s); vale antes ou depois do comando")
    db_opcao = argparse.ArgumentParser(add_help=False)            # o mesmo --db, depois do comando; sem valor próprio,
    db_opcao.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)   # para não apagar o de antes dele
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{varrer,catalogo,grafico,site}")

    v = sub.add_parser("varrer", parents=[db_opcao], formatter_class=fmt, epilog=exemplos,
                       help="lê os preços pelas páginas de busca da Amazon (por padrão, os mais vendidos de cada gênero)",
                       description="Lê os preços pelas páginas de busca da Amazon e guarda no banco. Sem opções, lê os ~2.000 "
                                   "livros mais vendidos (com preço) de cada um dos 29 gêneros de Livros, em 9 faixas de preço "
                                   "(~13 mil páginas por passada completa), só pelo navegador.")
    comum = v.add_argument_group("uso comum")
    comum.add_argument("--minutos", type=_numero_positivo, default=150, help="orçamento de tempo (padrão: %(default)s)")
    comum.add_argument("--dry-run", action="store_true",
                       help="confere as opções e mostra o que a execução faria (ritmo, ciclo, pausa, fatias, cliente), sem "
                            "abrir o navegador, sem pedir nada à Amazon e sem gravar no banco")
    comum.add_argument("--cliente", choices=["auto", "navegador", "curl", "requests"], default="auto",
                       help="como ler as páginas (padrão: %(default)s = só o navegador; se ele não abrir, para e diz por quê). "
                            "curl e requests só quando pedidos: a Amazon costuma bloqueá-los, e um bloqueio grava no banco "
                            "uma pausa de horas")
    comum.add_argument("--particao", choices=list(varredura.PARTICOES_VENDIDOS),
                       help="só os gêneros desta sequência de coleta (uma por servidor em varredura.yml)")
    comum.add_argument("--generos", help="só estes nós, separados por vírgula (padrão: os 29 gêneros; "
                                         "o ranking geral de Livros, 6740748011, só se for pedido aqui)")
    comum.add_argument("--faixas", help="bordas das faixas de preço em reais, ex.: 0,20,30,40,50,60,80,120,200 "
                                        "(padrão: " + ",".join(f"{a / 100:g}" for a, _ in varredura.FAIXAS_VENDIDOS) + ")")
    comum.add_argument("--no", default=None,
                       help="em vez dos mais vendidos, lê só esta categoria (nó da Amazon), fatiada por preço; "
                            f"{varredura.NO_HQ_MANGA} = HQs, Mangás e Graphic Novels")
    comum.add_argument("--vendidos", action="store_true", help="os mais vendidos dos gêneros (já é o padrão; existe por compatibilidade)")
    cal = v.add_argument_group("ritmo e ciclo (calibragem; os padrões aprendem com o banco)")
    cal.add_argument("--ritmo", type=_numero_positivo, default=None,
                     help="páginas por minuto no começo (padrão: 80%% do último ritmo limpo guardado no banco, "
                          f"ou {ritmo.PPM_BASE:g}, o ritmo medido sem bloqueios)")
    cal.add_argument("--ritmo-max", type=_numero_positivo, default=None,
                     help="teto de páginas por minuto programadas (o real fica ~10-20%% abaixo): o ritmo sobe aos "
                          "poucos até ele enquanto não há falha e recua nas falhas. Sem esta opção, o teto é o que "
                          f"está guardado no banco (começa em {ritmo.PPM_TETO_PADRAO:g}) e sobe 25%% por dia "
                          f"limpo até {ritmo.PPM_TETO_AUTO_MAX:g} (ou até --teto-auto-max); com ela, o valor é fixo e nada é aprendido")
    cal.add_argument("--teto-auto-max", type=_numero_positivo, default=ritmo.PPM_TETO_AUTO_MAX,
                     help="até onde o teto guardado no banco pode subir sozinho (padrão: %(default)g). Vale também sobre um "
                          "teto já guardado acima dele. Com várias sequências em paralelo, é o limite de cada uma; "
                          "só vale sem --ritmo-max")
    cal.add_argument("--ciclo-horas", type=int, choices=ritmo.CICLOS, default=None,
                     help="horas entre passadas completas do catálogo (padrão: o degrau guardado no banco, que começa em "
                          f"{ritmo.CICLO_INICIAL} h e desce um degrau por dia limpo até {ritmo.CICLOS[0]} h). Com esta opção, o "
                          "ciclo fica fixo e nada é aprendido")
    cal.add_argument("--ignorar-pausa", action="store_true",
                     help="lê mesmo durante a pausa que segue um bloqueio (horas, de propósito: cada execução cai num IP novo)")
    cal.add_argument("--subir-a-cada", type=_inteiro_positivo, default=ritmo.A_CADA,
                     help="páginas boas seguidas para cada subida de 25%% do ritmo (padrão: %(default)s)")
    dep = v.add_argument_group("depuração")
    dep.add_argument("--max-paginas", type=_inteiro_positivo, help="para depois de N requisições (para testes)")
    dep.add_argument("--parar-na-falha", action="store_true",
                     help="termina na primeira falha (bloqueio, erro ou página curta), sem insistir; para medir "
                          "até que ritmo a coleta passa limpa")
    dep.add_argument("--pasta-html", help="onde guardar o HTML bruto das páginas com problema (padrão: html/ ao lado do banco)")

    k = sub.add_parser("catalogo", parents=[db_opcao], help="progresso de hoje e dias sem varredura completa",
                       description="Mostra o progresso da coleta, o frescor do catálogo e as últimas execuções. Só lê o banco.")
    k.add_argument("--no", default=None, help="em vez dos mais vendidos, esta categoria (nó da Amazon)")
    k.add_argument("--vendidos", action="store_true", help="os mais vendidos dos gêneros (já é o padrão; existe por compatibilidade)")
    k.add_argument("--json", action="store_true", help="escreve um objeto JSON em vez do texto (os --exigir-* continuam valendo)")
    k.add_argument("--exigir-ontem", action="store_true",
                   help="sai com código 1 se ontem não teve varredura completa (para alertas)")
    k.add_argument("--exigir-frescor", action="store_true",
                   help="sai com código 1 se alguma fatia está sem passada completa há mais de 2 ciclos e 2 h (a coleta parou "
                        "ou não dá conta do ciclo; para alertas)")
    k.add_argument("--exigir-detalhes", action="store_true",
                   help="sai com código 1 se a última execução avisou que os cards vieram sem capa ou autor (para alertas)")

    g = sub.add_parser("grafico", parents=[db_opcao],
                       help="gráfico HTML do histórico de preço de um livro (números e gráfico, sem conclusões)")
    g.add_argument("livro", help="ASIN ou parte do título")
    g.add_argument("--eventos", default=None, help="datas de promoção, em CSV nome,inicio,fim (padrão: o eventos.csv do repositório)")
    g.add_argument("--saida", help="arquivo HTML (padrão: data/grafico-<asin>.html)")

    w = sub.add_parser("site", help="gera o site estático (busca por título, histórico e lista de desejos)")
    w.add_argument("bancos", nargs="+", help="um ou mais bancos do catálogo")
    w.add_argument("--saida", default="site", help="pasta de saída (padrão: %(default)s)")
    w.add_argument("--eventos", default=None, help="datas de promoção, em CSV nome,inicio,fim (padrão: o eventos.csv do repositório)")
    w.add_argument("--url", default=None, help="endereço público do site, para a imagem de prévia dos links compartilhados; "
                                               "sem ele, os links aparecem sem imagem")

    args = p.parse_args()
    if args.cmd == "site":
        from . import site
        meta = site.construir([Path(b) for b in args.bancos], Path(args.saida), _eventos(args), args.url)
        print(f"site em {args.saida}: {meta['itens']} livros")
        return
    if args.cmd in ("varrer", "catalogo"):
        args.mais_vendidos = _mais_vendidos(args, v if args.cmd == "varrer" else k)
    if args.cmd == "varrer":
        if args.ritmo is not None and args.ritmo_max is not None and args.ritmo > args.ritmo_max:
            v.error(f"--ritmo ({args.ritmo:g}) passa de --ritmo-max ({args.ritmo_max:g}), que deveria ser o teto fixo")
        if not args.mais_vendidos:
            for opcao in ("generos", "faixas", "particao"):
                if getattr(args, opcao):
                    v.error(f"--{opcao} vale só para os mais vendidos, e --no escolhe uma categoria")
        vendidos, faixas = _opcoes_de_coleta(args)
        if args.dry_run:
            _plano(args, vendidos, faixas)
            return
    else:
        _exigir_banco(args)
    conn = db.conectar(args.db)
    if args.cmd in ("varrer", "catalogo"):
        varredura.criar_schema(conn)

    try:
        if args.cmd == "grafico":
            from . import relatorio
            eventos = _eventos(args)
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
            saida.write_text(relatorio.pagina(titulo or asin, asin, trechos, relatorio.ler_eventos(eventos), relatorio.aviso(conn)),
                             encoding="utf-8")
            print(f"gráfico em {saida}")
        elif args.cmd == "varrer":
            if args.ciclo_horas is None and not args.ignorar_pausa and (pausa := varredura.pausa_vigente(conn)):
                print(f"em pausa até {pausa.isoformat(timespec='minutes')} (bloqueio recente); nada a fazer. "
                      "Para ler assim mesmo: --ignorar-pausa")
                return
            sessao = rede.nova_sessao(args.cliente)
            try:
                res = varredura.executar(
                    conn, sessao, no=args.no or varredura.NO_HQ_MANGA, vendidos=vendidos, minutos=args.minutos,
                    max_paginas=args.max_paginas,
                    faixas=faixas, ritmo_inicial=args.ritmo, ritmo_max=args.ritmo_max, teto_auto_max=args.teto_auto_max,
                    subir_a_cada=args.subir_a_cada, ciclo_horas=args.ciclo_horas, ignorar_pausa=args.ignorar_pausa,
                    parar_na_falha=args.parar_na_falha,
                    pasta_html=Path(args.pasta_html) if args.pasta_html else Path(args.db).parent / "html")
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
            c = varredura.cobertura(conn, varredura.GRUPO_VENDIDOS if args.mais_vendidos else args.no)
            pausa = varredura.pausa_vigente(conn)
            n, fracoes = varredura.preenchimento(conn, varredura.inicio_do_dia())
            execucoes = [dict(r) for r in conn.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 5")]
            if args.json:
                print(json.dumps({
                    "itens": c.itens, "vistos_hoje": c.vistos_hoje, "fatias": c.fatias, "fatias_hoje": c.fatias_hoje,
                    "dia_completo": c.dia_completo, "dias_sem_varredura_completa": [str(d) for d in c.lacunas],
                    "ciclo_horas": c.ciclo_horas, "passada_mais_velha_h": c.mais_antiga_h,
                    "limite_atraso_h": varredura.limite_atraso(c.ciclo_horas), "fatias_atrasadas": c.atrasadas,
                    "fatias_nunca_lidas": c.nunca_lidas, "pausa_ate": pausa.isoformat(timespec="minutes") if pausa else None,
                    "itens_lidos_hoje": n, "preenchimento_hoje": {nome: fracoes[col] for col, nome in varredura.CAMPOS_PREENCHIMENTO.items()} if n else {},
                    "ultimas_execucoes": execucoes}, ensure_ascii=False, indent=1))
            else:
                print(f"{c.itens} itens no catálogo; {c.vistos_hoje} com preço lido hoje")
                print(f"hoje: {c.fatias_hoje} de {c.fatias} fatias lidas" + (" (dia completo)" if c.dia_completo else ""))
                print("dias sem varredura completa: " + (", ".join(map(str, c.lacunas)) if c.lacunas else "nenhum"))
                if c.mais_antiga_h is not None:
                    print(f"frescor: ciclo de {c.ciclo_horas} h; a passada completa mais velha tem {c.mais_antiga_h:.1f} h"
                          f" (limite {varredura.limite_atraso(c.ciclo_horas):g} h); {c.atrasadas} fatias atrasadas"
                          + (f", {c.nunca_lidas} nunca lidas" if c.nunca_lidas else ""))
                if pausa:
                    print(f"pausa depois de bloqueio até {pausa.isoformat(timespec='minutes')}")
                if n:
                    print(f"detalhes dos {n} itens lidos hoje: " + ", ".join(
                        f"{nome} {fracoes[col]:.0%}" for col, nome in varredura.CAMPOS_PREENCHIMENTO.items()))
                for r in execucoes:
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

    finally:
        conn.close()

if __name__ == "__main__":
    main()
