"""Subgêneros da Amazon.com.br: experimento da Fase C (docs/roadmap.md), sem coleta recorrente. Descobre a árvore de
subcategorias de cada gênero e mede o que custaria rotular os livros com ela.

A Amazon divide cada um dos 29 gêneros que o coletor lê em subcategorias ("Fantasia, Horror e Ficção Científica" →
"Fantasia" → "Épica"), cada uma com a sua lista de mais vendidos. Três passos, todos retomáveis:

  descobrir  uma página por nó (a primeira dos mais vendidos, com o filtro "vendido pela Amazon" do coletor): a navegação
             "Departamento" dá os filhos do nó e o total de resultados dele;
  rotular    as K primeiras páginas dos mais vendidos de cada folha, uma rodada por página (a 1 de todas as folhas, depois
             a 2, e assim por diante): quais livros são de cada subgênero;
  custo      o resumo da árvore e quanto custaria rotular toda semana (só lê o disco).

O HTML de cada página lida fica em <pasta>/paginas/ (gz) e é a fonte de tudo: a árvore (arvore.json) e os rótulos
(rotulos.json) se refazem dele, e consertar o parser não custa nenhuma página (rode `descobrir` de novo: o que está em disco
não é pedido outra vez). Cortesia com a Amazon: uma página por vez, pausa de pelo menos PAUSA s, parada na primeira página
bloqueada (sem tentar de novo) e um teto de páginas que conta as que já estão em disco.
"""

from __future__ import annotations

import collections
import gzip
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import busca, rede, ritmo, varredura

POR_PAGINA = 16
MAX_PAGINAS = 400             # teto do experimento, contando as páginas que já estão em disco
PAUSA = 4.0                   # segundos entre dois pedidos à Amazon (o mínimo aceito na linha de comando)
ERROS_SEGUIDOS = 3            # falhas de rede ou de HTTP seguidas que encerram a execução (o bloqueio encerra na primeira)
PASSADA_DO_COLETOR = 13_000   # páginas de uma passada completa do coletor (~13 mil, ver `varrer --help`), para comparar o custo
KS = (5, 10, 20, 75)          # páginas por folha que o resumo compara (75 é o que a Amazon mostra)
_ARQUIVO_RE = re.compile(r"^no-(\d+)-p1\.html\.gz$")


class Cache:
    """O HTML de cada página lida, em <pasta>/paginas/no-<nó>-p<N>.html.gz."""

    def __init__(self, pasta: Path | str):
        self.pasta = Path(pasta) / "paginas"

    def _arquivo(self, no: str, pagina: int) -> Path:
        return self.pasta / f"no-{no}-p{pagina}.html.gz"

    def existe(self, no: str, pagina: int) -> bool:
        return self._arquivo(no, pagina).exists()

    def ler(self, no: str, pagina: int) -> str | None:
        try:
            return gzip.decompress(self._arquivo(no, pagina).read_bytes()).decode("utf-8")
        except (OSError, EOFError):          # não existe, ou ficou pela metade
            return None

    def gravar(self, no: str, pagina: int, html: str) -> None:
        arquivo = self._arquivo(no, pagina)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = arquivo.with_name(arquivo.name + ".tmp")        # o arquivo só aparece inteiro
        provisorio.write_bytes(gzip.compress(html.encode("utf-8"), 6))
        provisorio.replace(arquivo)

    def nos(self) -> list[str]:
        """Os nós que têm a página 1 em disco."""
        if not self.pasta.is_dir():
            return []
        return sorted(m.group(1) for f in self.pasta.iterdir() if (m := _ARQUIVO_RE.match(f.name)))

    def __len__(self) -> int:
        return sum(1 for _ in self.pasta.glob("no-*-p*.html.gz")) if self.pasta.is_dir() else 0


class Leitor:
    """Entrega o HTML de uma página: do cache ou da Amazon, uma por vez e com pausa. Para de pedir ao chegar no teto, na
    primeira página bloqueada ou depois de ERROS_SEGUIDOS falhas seguidas (`parou` diz qual); a partir daí só entrega o que
    está no cache. Quem lê o resultado separa "parou" (acabou a execução) de "esta página falhou" (`erro`)."""

    def __init__(self, sessao, cache: Cache, *, max_paginas: int = MAX_PAGINAS, pausa: float = PAUSA,
                 dormir=time.sleep, relogio=time.monotonic, aviso=lambda texto: None):
        self.sessao, self.cache = sessao, cache
        self.max_paginas, self.pausa, self.dormir, self.relogio, self.aviso = max_paginas, pausa, dormir, relogio, aviso
        self.usadas = len(cache)         # páginas em disco mais os pedidos desta execução: o que conta para o teto
        self.pedidas = 0                 # pedidos à Amazon desta execução (as falhas também contam)
        self.parou: str | None = None
        self.erro: str | None = None     # por que a última página pedida não veio
        self._ultimo: float | None = None
        self._falhas = 0

    def pagina(self, no: str, pagina: int) -> str | None:
        """O HTML da página `pagina` dos mais vendidos de `no`, ou None (ver `parou` e `erro`)."""
        self.erro = None
        html = self.cache.ler(no, pagina)
        if html is not None:
            return html
        if self.parou:
            return None
        if self.usadas >= self.max_paginas:
            self.parou = f"teto de {self.max_paginas} páginas"
            return None
        if self._ultimo is not None and (falta := self.pausa - (self.relogio() - self._ultimo)) > 0:
            self.dormir(falta)
        _, html, erro = rede.baixar(self.sessao, busca.url_busca(no, 0, busca.SEM_TETO, pagina, "vendidos"))
        self._ultimo = self.relogio()
        self.usadas += 1
        self.pedidas += 1
        if erro is None:
            self._falhas = 0
            self.cache.gravar(no, pagina, html)
            self.aviso(f"página {self.usadas}/{self.max_paginas}: nó {no} p{pagina}")
            return html
        rede.guardar_html(self.cache.pasta.parent / "problemas", f"no-{no}-p{pagina}", html)
        self.erro = f"{erro.status}: {erro.detalhe}"
        if erro.status == "bloqueado":
            self.parou = "bloqueio"
        else:
            self._falhas += 1
            if self._falhas >= ERROS_SEGUIDOS:
                self.parou = f"{ERROS_SEGUIDOS} erros seguidos"
        return None


def no_com_erro(detalhe: str | None) -> dict:
    return {"status": "erro", "detalhe": detalhe, "nome": None, "pais": [], "filhos": [], "total": None, "exato": False, "paginas": 0}


def ler_no(html: str, no: str) -> dict:
    """O que a página 1 dos mais vendidos de `no` diz sobre ele. `status`:
      folha     sem subcategorias: é o que se rotula;
      interno   com subcategorias (`filhos`);
      vazio     nenhum resultado com o filtro "vendido pela Amazon": sem livros, e não é folha;
      outro_no  a Amazon mostrou a página de outro nó (redirecionamento): `detalhe` diz qual;
      erro      layout desconhecido: `detalhe` diz o que faltou.
    `total` são os resultados do nó ("mais de 3.000" é só um piso: `exato` falso) e `paginas`, quantas páginas de mais
    vendidos ele tem (a Amazon só mostra 75). `pais`, do mais alto ao mais próximo, dão a posição do nó na árvore."""
    try:
        dep, pagina = busca.parse_subnos(html), busca.parse_busca(html)
    except busca.LayoutDesconhecido as e:
        return no_com_erro(str(e))
    total, exato = pagina.total, pagina.total_exato
    if total is None and (pagina.ultima_pagina or 1) == 1:
        total, exato = pagina.cards, True              # uma página só: o total é a contagem dela ("12 resultados" não traz o "de")
    info = {"status": "", "nome": dep.atual.nome if dep.atual else None,
            "pais": [[p.no, p.nome] for p in dep.pais], "filhos": [[f.no, f.nome] for f in dep.filhos],
            "total": total, "exato": exato,
            "paginas": min(varredura.LIMITE_PAGINAS_VENDIDOS, pagina.ultima_pagina or (1 if pagina.cards else 0))}
    if dep.atual is not None and dep.atual.no != no:
        info.update(status="outro_no", detalhe=f"a página é do nó {dep.atual.no} ({dep.atual.nome})")
    elif not pagina.cards:
        info["status"] = "vazio"
    elif dep.atual is None:
        info.update(status="erro", detalhe="navegação sem o nó atual")
    else:
        info["status"] = "interno" if dep.filhos else "folha"
    return info


def arvore_do_cache(cache: Cache) -> dict:
    """Os nós que têm a página 1 em disco, lidos do HTML (o `arvore.json` é só uma cópia disso)."""
    return {no: ler_no(cache.ler(no, 1) or "", no) for no in cache.nos()}


def descobrir(leitor: Leitor, raizes: list[str], profundidade: int | None = None, salvar=None, aviso=lambda texto: None) -> dict:
    """Busca em largura a partir de `raizes`, `profundidade` níveis abaixo delas (None: até as folhas). Um nó é uma página
    e nunca é lida duas vezes: os que já estão em disco saem de lá, relidos do HTML. Para quando o leitor para. Devolve a
    árvore com todos os nós que estão em disco (não só os desta busca) e `salvar(árvore)` é chamado a cada nó novo."""
    nos = arvore_do_cache(leitor.cache)
    falhas: dict[str, dict] = {}
    fila = collections.deque((no, 0) for no in dict.fromkeys(raizes))
    vistos = {no for no, _ in fila}

    def arvore() -> dict:
        return {"gerada_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "raizes": list(raizes),
                "profundidade": profundidade, "parou": leitor.parou, "completa": not fila and not leitor.parou,
                "paginas_em_disco": len(leitor.cache), "nos": {**nos, **falhas}}

    while fila:
        no, nivel = fila.popleft()
        novo = no not in nos
        if novo:
            html = leitor.pagina(no, 1)
            if html is None:
                if leitor.parou:
                    fila.appendleft((no, nivel))
                    break
                falhas[no] = no_com_erro(leitor.erro)
                aviso(f"{no}: não veio ({leitor.erro})")
                continue
            nos[no] = ler_no(html, no)
        info = nos[no]
        if info["status"] == "interno" and (profundidade is None or nivel < profundidade):
            for filho, _ in info["filhos"]:
                if filho not in vistos:
                    vistos.add(filho)
                    fila.append((filho, nivel + 1))
        if novo:
            aviso(f"{no} {info['nome'] or '?'}: {info['status']}, {info['total']} resultados, {len(info['filhos'])} filhos")
            if salvar:
                salvar(arvore())
    resultado = arvore()
    if salvar:
        salvar(resultado)
    return resultado


def abaixo_de(arvore: dict, de: str) -> set[str]:
    """`de` e tudo que as listas de filhos alcançam a partir dele. Não dá para usar o caminho (`pais`) que a página mostra:
    a árvore da Amazon é um grafo (Horror está em "Fantasia, Horror e Ficção Científica" e em "Literatura e Ficção", e a
    página só mostra um dos caminhos)."""
    achados, fila = {de}, [de]
    while fila:
        for filho, _ in arvore["nos"].get(fila.pop(), {}).get("filhos", []):
            if filho not in achados:
                achados.add(filho)
                fila.append(filho)
    return achados


def folhas_de(arvore: dict, de: str | None = None) -> dict[str, dict]:
    """Os nós `folha`, em ordem de código (a mesma em qualquer execução; se uma rodada parar no meio, as folhas que já têm a
    página são um pedaço sem relação com o assunto); com `de`, só os que estão abaixo desse nó (ou ele mesmo)."""
    dentro = abaixo_de(arvore, de) if de else None
    return {no: i for no, i in sorted(arvore["nos"].items(), key=lambda par: int(par[0]))
            if i["status"] == "folha" and (dentro is None or no in dentro)}


def nao_lidos(arvore: dict) -> set[str]:
    """Subcategorias que alguma página listou e que ainda não têm página lida."""
    return {f[0] for i in arvore["nos"].values() for f in i["filhos"]} - set(arvore["nos"])


def custo(arvore: dict, k: int, de: str | None = None) -> int:
    """Páginas para ler as `k` primeiras de cada folha conhecida (uma folha com menos páginas custa as que tem)."""
    return sum(min(i["paginas"], k) for i in folhas_de(arvore, de).values())


def k_pelo_orcamento(arvore: dict, cache: Cache, de: str | None = None, max_paginas: int = MAX_PAGINAS) -> int:
    """O maior K tal que ler as K primeiras páginas de cada folha cabe no que falta do teto (o que já está em disco não custa)."""
    folhas, livres, melhor = folhas_de(arvore, de), max_paginas - len(cache), 0
    for k in range(1, max((i["paginas"] for i in folhas.values()), default=0) + 1):
        faltam = sum(1 for no, i in folhas.items() for p in range(1, min(i["paginas"], k) + 1) if not cache.existe(no, p))
        if faltam > livres:
            break
        melhor = k
    return melhor


def rotular(leitor: Leitor, arvore: dict, k: int, de: str | None = None) -> None:
    """Lê as `k` primeiras páginas de cada folha, uma rodada por página: a 1 de todas as folhas, depois a 2, e assim por
    diante. Se a execução parar no meio (bloqueio, teto), todas as folhas têm o mesmo número de páginas, ou uma a mais."""
    folhas = folhas_de(arvore, de)
    for p in range(1, k + 1):
        for no, info in folhas.items():
            if p <= info["paginas"] and leitor.pagina(no, p) is None and leitor.parou:
                return


def cards_da_pagina(html: str) -> list[list[str]]:
    """Os cards com preço da página, do mais vendido ao menos; cada card é a lista dos ASINs dos seus formatos (o do card primeiro)."""
    cards: dict[str, list[str]] = {}
    for item in busca.parse_busca(html).itens:
        obra = item.obra or item.asin
        lista = cards.setdefault(obra, [obra])
        if item.asin not in lista:
            lista.append(item.asin)
    return list(cards.values())


def rotulos(cache: Cache, arvore: dict, k: int, de: str | None = None) -> dict:
    """{folha: {nome, total, exato, paginas: [página 1, página 2, ...]}} lido do cache (ver `cards_da_pagina`): só as
    páginas que estão em disco, de 1 até `k`, sem buracos."""
    saida = {}
    for no, info in folhas_de(arvore, de).items():
        paginas = []
        for p in range(1, min(k, info["paginas"]) + 1):
            html = cache.ler(no, p)
            if html is None:
                break
            paginas.append(cards_da_pagina(html))
        saida[no] = {"nome": info["nome"], "total": info["total"], "exato": info["exato"], "paginas": paginas}
    return saida


def cobertura_por_totais(arvore: dict) -> list[dict]:
    """Para cada nó interno com todos os filhos lidos: o total dele, a soma dos totais dos filhos e quantos são. Um livro
    pode estar em mais de um filho (a soma passa do total) e em nenhum (falta): é uma ordem de grandeza, e totais "mais de N"
    são pisos (`exato` diz se o do pai é exato)."""
    linhas = []
    for no, i in arvore["nos"].items():
        filhos = [arvore["nos"].get(f[0]) for f in i["filhos"]]
        if i["status"] != "interno" or any(f is None or f["total"] is None for f in filhos):
            continue
        linhas.append({"no": no, "nome": i["nome"], "total": i["total"], "exato": i["exato"],
                       "soma_filhos": sum(f["total"] for f in filhos), "filhos": len(filhos),
                       "filhos_exatos": all(f["exato"] for f in filhos)})
    return linhas


def texto_resumo(arvore: dict, ks=KS) -> str:
    """O resumo da árvore e do custo de rotular, em texto."""
    nos = arvore["nos"]
    contagem = collections.Counter(i["status"] for i in nos.values())
    nomes = {"folha": "folhas", "interno": "internos", "vazio": "vazios", "outro_no": "de outro nó", "erro": "com erro"}
    linhas = [f"{len(nos)} nós lidos (" + ", ".join(f"{contagem[s]} {nomes[s]}" for s in nomes if contagem[s]) + ")"
              + f"; {len(nao_lidos(arvore))} subcategorias listadas e ainda não lidas"
              + ("" if arvore.get("completa", True) else f"; a busca parou: {arvore.get('parou') or 'fila não vazia'}")]
    folhas = folhas_de(arvore)
    niveis = collections.Counter(len(i["pais"]) - 1 for i in nos.values() if i["pais"])
    linhas.append("nós por nível (0 = gênero): " + ", ".join(f"{n}: {c}" for n, c in sorted(niveis.items())))
    generos = [(no, i) for no, i in nos.items() if len(i["pais"]) == 1]
    for no, i in generos:
        dentro = abaixo_de(arvore, no)
        abaixo = [j for n, j in nos.items() if n in dentro and n != no]
        linhas.append(f"  {i['nome'] or no}: {len(i['filhos'])} subcategorias diretas"
                      + (f"; abaixo dele {sum(j['status'] == 'folha' for j in abaixo)} folhas e "
                         f"{sum(j['status'] == 'interno' for j in abaixo)} internos lidos" if abaixo else ""))
    if folhas:
        linhas.append(f"{len(folhas)} folhas, com {sum(i['total'] or 0 for i in folhas.values())} resultados somados (pisos incluídos)")
    for k in ks:
        n, ainda = custo(arvore, k), len(nao_lidos(arvore))
        linhas.append(f"rotular as {k} primeiras páginas de cada folha: {n} páginas ({n / PASSADA_DO_COLETOR:.1%} de uma passada do coletor)"
                      + (f"; mais até {ainda * k} se as {ainda} ainda não lidas forem folhas" if ainda else ""))
    linhas.append(f"uma passada do coletor tem ~{PASSADA_DO_COLETOR} páginas, e ele faz de {7 * 24 // ritmo.CICLO_INICIAL} "
                  f"(ciclo de {ritmo.CICLO_INICIAL} h) a {7 * 24 // ritmo.CICLOS[0]} (ciclo de {ritmo.CICLOS[0]} h) passadas por semana")
    for c in cobertura_por_totais(arvore):
        if c["total"]:
            linhas.append(f"  {c['nome']}: {c['total']}{'' if c['exato'] else '+'} resultados; os {c['filhos']} filhos somam "
                          f"{c['soma_filhos']}{'' if c['filhos_exatos'] else '+'} ({c['soma_filhos'] / c['total']:.0%})")
    return "\n".join(linhas)


def gravar_json(arquivo: Path, dados) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    provisorio = arquivo.with_name(arquivo.name + ".tmp")
    provisorio.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    provisorio.replace(arquivo)


def executar(args) -> None:
    """O comando `subgeneros` (os argumentos vêm de __main__.py). Nunca abre banco."""
    pasta = Path(args.pasta)
    arquivo_arvore = pasta / "arvore.json"
    if args.passo == "custo":
        if not arquivo_arvore.exists():
            raise SystemExit(f"{arquivo_arvore} não existe: rode `subgeneros descobrir --pasta {pasta}` antes")
        print(texto_resumo(json.loads(arquivo_arvore.read_text(encoding="utf-8")), args.ks))
        return
    cache = Cache(pasta)
    if args.passo == "rotular":
        if not arquivo_arvore.exists():
            raise SystemExit(f"{arquivo_arvore} não existe: rode `subgeneros descobrir --pasta {pasta}` antes")
        arvore = json.loads(arquivo_arvore.read_text(encoding="utf-8"))
        if not folhas_de(arvore, args.de):
            raise SystemExit("nenhuma folha lida" + (f" abaixo de {args.de}" if args.de else "") + ": rode `descobrir` até as folhas")
        k = args.k or k_pelo_orcamento(arvore, cache, args.de, args.max_paginas)
        print(f"{len(folhas_de(arvore, args.de))} folhas; K = {k} páginas por folha" + ("" if args.k else " (o que cabe no teto)"))
        if not args.k and k < 3:
            raise SystemExit("K abaixo de 3 pelo teto: um gênero pela metade enviesa a cobertura. Aumente --max-paginas, escolha "
                             "um gênero menor ou peça -k explícito")
    sessao = rede.nova_sessao(args.cliente)
    try:
        leitor = Leitor(sessao, cache, max_paginas=args.max_paginas, pausa=args.pausa, aviso=print)
        if args.passo == "descobrir":
            nos = [n.strip() for n in args.nos.split(",") if n.strip()] if args.nos else list(varredura.GENEROS)
            descobrir(leitor, nos, args.profundidade, salvar=lambda a: gravar_json(arquivo_arvore, a), aviso=print)
            print(texto_resumo(json.loads(arquivo_arvore.read_text(encoding="utf-8")), args.ks))
        else:
            rotular(leitor, arvore, k, args.de)
            gravar_json(pasta / "rotulos.json", {"k": k, "de": args.de, "folhas": rotulos(cache, arvore, k, args.de)})
            print(f"rótulos em {pasta / 'rotulos.json'} ({custo(arvore, k, args.de)} páginas para K = {k}; "
                  f"{len(cache)} em disco)")
    finally:
        if hasattr(sessao, "fechar"):
            sessao.fechar()
    print(f"{leitor.pedidas} páginas pedidas à Amazon nesta execução; {len(cache)} em disco")
    if leitor.parou:
        raise SystemExit(f"parou: {leitor.parou}")
