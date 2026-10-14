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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import busca, parecidos, rede, ritmo, varredura

POR_PAGINA = 16
MAX_PAGINAS = 400             # teto do experimento, contando as páginas que já estão em disco
PAUSA = 4.0                   # segundos entre dois pedidos à Amazon (o mínimo aceito na linha de comando)
ERROS_SEGUIDOS = 3            # falhas de rede ou de HTTP seguidas que encerram a execução (o bloqueio encerra na primeira)
PASSADA_DO_COLETOR = 13_000   # páginas de uma passada completa do coletor (~13 mil, ver `varrer --help`), para comparar o custo
KS = (5, 10, 20, 75)          # páginas por folha que o resumo compara (75 é o que a Amazon mostra)
K_PADRAO = 10                 # páginas por folha na coleta recorrente (a cobertura do piloto: 38,5% das obras do gênero)
INTERVALO_DIAS = 14           # entre o fim de um ciclo e o começo do seguinte (provisório: a estabilidade dos rótulos não foi medida)
EXECUCOES_ATE_ACEITAR = 3     # um ciclo com páginas que não vêm termina assim mesmo depois de tantas execuções
PAUSA_BLOQUEIO_H = 24         # pausa depois do primeiro bloqueio; dobra a cada um seguido
PAUSA_MAXIMA_DIAS = 7
MIN_FOLHAS_NOVAS = 0.5        # um snapshot com menos que isto das folhas do anterior não é publicado (layout novo, erro de leitura)
_ARQUIVO_RE = re.compile(r"^no-(\d+)-p1\.html\.gz$")


class Cache:
    """O HTML de cada página lida, em <pasta>/paginas/no-<nó>-p<N>.html.gz. É o armazém do experimento: guarda tudo, e a
    árvore e os rótulos se refazem dele. (`Compacto` guarda só o que a conta usa.)"""

    def __init__(self, pasta: Path | str):
        self.pasta = Path(pasta) / "paginas"
        self.problemas = Path(pasta) / "problemas"          # onde vai o HTML das páginas que a Amazon bloqueou

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

    def info(self, no: str) -> dict | None:
        """`ler_no` da página 1 do nó, ou None se ela não está em disco."""
        html = self.ler(no, 1)
        return None if html is None else ler_no(html, no)

    def cards(self, no: str, pagina: int) -> list[list[str]] | None:
        """`cards_da_pagina` da página, ou None se ela não está em disco."""
        html = self.ler(no, pagina)
        if html is None:
            return None
        try:
            return cards_da_pagina(html)
        except busca.LayoutDesconhecido:
            return []


class Compacto:
    """O que a conta usa de cada página lida, e nada mais (uns 400 bytes por página, em vez de ~100 KB de HTML): da página 1,
    o que `ler_no` diz do nó; de todas, os cards. É o armazém da coleta recorrente, cujo estado precisa caber numa release
    e continuar entre execuções. `paginas` é um dicionário {"nó/página": {"i": info ou None, "c": cards}} (o do estado)."""

    def __init__(self, paginas: dict | None = None, problemas: Path | None = None):
        self.paginas = paginas if paginas is not None else {}
        self.problemas = problemas

    def existe(self, no: str, pagina: int) -> bool:
        return f"{no}/{pagina}" in self.paginas

    def gravar(self, no: str, pagina: int, html: str) -> None:
        try:
            cards = cards_da_pagina(html)
        except busca.LayoutDesconhecido:
            cards = []
        self.paginas[f"{no}/{pagina}"] = {"i": ler_no(html, no) if pagina == 1 else None, "c": cards}

    def info(self, no: str) -> dict | None:
        p = self.paginas.get(f"{no}/1")
        return p and p["i"]

    def cards(self, no: str, pagina: int) -> list[list[str]] | None:
        p = self.paginas.get(f"{no}/{pagina}")
        return p and p["c"]

    def nos(self) -> list[str]:
        return sorted(k[:-2] for k in self.paginas if k.endswith("/1"))

    def __len__(self) -> int:
        return len(self.paginas)


class Leitor:
    """Garante que uma página está no armazém: já está, ou vem da Amazon, uma por vez e com pausa. Para de pedir ao chegar no
    teto, no fim do prazo, na primeira página bloqueada ou depois de ERROS_SEGUIDOS falhas seguidas (`parou` diz qual); a
    partir daí só reconhece o que já está no armazém. Quem lê o resultado separa "parou" (acabou a execução) de "esta página
    falhou" (`erro`). `prazo`: instante (no `relogio`) a partir do qual não se pede mais nada."""

    def __init__(self, sessao, cache: Cache | Compacto, *, max_paginas: int = MAX_PAGINAS, pausa: float = PAUSA,
                 dormir=time.sleep, relogio=time.monotonic, aviso=lambda texto: None, prazo: float | None = None):
        self.sessao, self.cache, self.prazo = sessao, cache, prazo
        self.max_paginas, self.pausa, self.dormir, self.relogio, self.aviso = max_paginas, pausa, dormir, relogio, aviso
        self.usadas = len(cache)         # páginas em disco mais os pedidos desta execução: o que conta para o teto
        self.pedidas = 0                 # pedidos à Amazon desta execução (as falhas também contam)
        self.parou: str | None = None
        self.erro: str | None = None     # por que a última página pedida não veio
        self._ultimo: float | None = None
        self._falhas = 0

    def pagina(self, no: str, pagina: int) -> bool:
        """A página `pagina` dos mais vendidos de `no` está no armazém? Não estando, tenta pedi-la (ver `parou` e `erro`)."""
        self.erro = None
        if self.cache.existe(no, pagina):
            return True
        if self.parou:
            return False
        if self.prazo is not None and self.relogio() >= self.prazo:
            self.parou = "tempo"
            return False
        if self.usadas >= self.max_paginas:
            self.parou = f"teto de {self.max_paginas} páginas"
            return False
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
            return True
        rede.guardar_html(self.cache.problemas, f"no-{no}-p{pagina}", html)
        self.erro = f"{erro.status}: {erro.detalhe}"
        if erro.status == "bloqueado":
            self.parou = "bloqueio"
        else:
            self._falhas += 1
            if self._falhas >= ERROS_SEGUIDOS:
                self.parou = f"{ERROS_SEGUIDOS} erros seguidos"
        return False


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


def arvore_do_cache(cache: Cache | Compacto) -> dict:
    """Os nós que têm a página 1 no armazém, lidos dele (o `arvore.json` é só uma cópia disso)."""
    return {no: cache.info(no) or no_com_erro("página ilegível") for no in cache.nos()}


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
            if not leitor.pagina(no, 1):
                if leitor.parou:
                    fila.appendleft((no, nivel))
                    break
                falhas[no] = no_com_erro(leitor.erro)
                aviso(f"{no}: não veio ({leitor.erro})")
                continue
            nos[no] = leitor.cache.info(no)
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


def k_pelo_orcamento(arvore: dict, cache: Cache | Compacto, de: str | None = None, max_paginas: int = MAX_PAGINAS) -> int:
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
            if p <= info["paginas"] and not leitor.pagina(no, p) and leitor.parou:
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


def rotulos(cache: Cache | Compacto, arvore: dict, k: int, de: str | None = None) -> dict:
    """{folha: {nome, total, exato, paginas: [página 1, página 2, ...]}} lido do cache (ver `cards_da_pagina`): só as
    páginas que estão em disco, de 1 até `k`, sem buracos."""
    saida = {}
    for no, info in folhas_de(arvore, de).items():
        paginas = []
        for p in range(1, min(k, info["paginas"]) + 1):
            cards = cache.cards(no, p)
            if cards is None:
                break
            paginas.append(cards)
        saida[no] = {"nome": info["nome"], "total": info["total"], "exato": info["exato"], "paginas": paginas}
    return saida


SNAPSHOT_VERSAO = 1


def montar_snapshot(arvore: dict, rotulos_lidos: dict, k: int, generos: list[str], gerado_em: str | None = None) -> dict:
    """O que o site usa dos rótulos (`rotulos()`): por folha, o nó, o nome, o total de resultados (que dá o peso do
    subgênero) e os ASINs dos livros que a Amazon pôs nas primeiras páginas dela, sem repetir."""
    folhas = []
    for no, r in rotulos_lidos.items():
        asins = list(dict.fromkeys(a for pagina in r["paginas"] for card in pagina for a in card))
        if asins:
            folhas.append({"no": no, "nome": r["nome"], "total": r["total"], "exato": r["exato"], "asins": asins})
    return {"v": SNAPSHOT_VERSAO, "gerado_em": gerado_em or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "k": k, "generos": list(generos), "folhas": folhas}


def ler_snapshot(caminho: Path | str) -> dict:
    """O snapshot em `caminho` (JSON, ou .gz), conferido. ValueError diz o que está errado: quem usa (o site) segue sem
    subgêneros em vez de falhar. Folhas mal formadas ou sem ASIN são descartadas; sem nenhuma folha, é erro."""
    caminho = Path(caminho)
    try:
        bruto = caminho.read_bytes()
        dados = json.loads((gzip.decompress(bruto) if caminho.suffix == ".gz" else bruto).decode("utf-8"))
    except (OSError, EOFError, ValueError) as e:
        raise ValueError(f"não consegui ler {caminho}: {e}") from e
    if not isinstance(dados, dict) or dados.get("v") != SNAPSHOT_VERSAO:
        raise ValueError(f"versão desconhecida do snapshot ({dados.get('v') if isinstance(dados, dict) else type(dados).__name__})")
    folhas = [f for f in dados.get("folhas") or []
              if isinstance(f, dict) and isinstance(f.get("no"), str) and isinstance(f.get("nome"), str)
              and (f.get("total") is None or isinstance(f["total"], int))
              and isinstance(f.get("asins"), list) and f["asins"] and all(isinstance(a, str) for a in f["asins"])]
    if not folhas:
        raise ValueError("snapshot sem nenhuma folha com livros")
    return {**dados, "folhas": folhas}


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
    linhas.append(f"uma passada do coletor tem ~{PASSADA_DO_COLETOR} páginas; em 14/10/2026 ele fazia uma por dia (ciclo de "
                  f"{ritmo.CICLOS[-1]} h, ~{7 * 24 // ritmo.CICLOS[-1]} por semana). O ciclo de {ritmo.CICLOS[0]} h é a meta e nunca foi sustentado")
    for c in cobertura_por_totais(arvore):
        if c["total"]:
            linhas.append(f"  {c['nome']}: {c['total']}{'' if c['exato'] else '+'} resultados; os {c['filhos']} filhos somam "
                          f"{c['soma_filhos']}{'' if c['filhos_exatos'] else '+'} ({c['soma_filhos'] / c['total']:.0%})")
    return "\n".join(linhas)


class Estado:
    """O que a coleta recorrente guarda entre uma execução e outra (asset da release, `estado.json.gz`): o ciclo em andamento
    (as páginas já lidas, em `Compacto`), a pausa depois de bloqueio e o fim do último ciclo. Um arquivo que existe mas não
    se lê é erro (ValueError): recomeçar do zero apagaria a pausa e leria de novo o que já foi lido."""

    VERSAO = 1

    def __init__(self, dados: dict | None = None):
        d = dados or {}
        self.ciclo: dict | None = d.get("ciclo")                  # {"inicio", "k", "nos", "execucoes", "paginas": {...}}
        self.pausa_ate: str | None = d.get("pausa_ate")
        self.bloqueios: int = d.get("bloqueios", 0)               # bloqueios seguidos (zera quando um ciclo termina)
        self.ultimo_snapshot: str | None = d.get("ultimo_snapshot")

    def dados(self) -> dict:
        return {"v": self.VERSAO, "ciclo": self.ciclo, "pausa_ate": self.pausa_ate, "bloqueios": self.bloqueios,
                "ultimo_snapshot": self.ultimo_snapshot}

    @classmethod
    def ler(cls, arquivo: Path) -> "Estado":
        if not arquivo.exists():
            return cls()
        try:
            dados = json.loads(gzip.decompress(arquivo.read_bytes()).decode("utf-8"))
        except (OSError, EOFError, ValueError) as e:
            raise ValueError(f"estado ilegível em {arquivo}: {e}") from e
        if not isinstance(dados, dict) or dados.get("v") != cls.VERSAO:
            raise ValueError(f"estado de outra versão em {arquivo}")
        return cls(dados)

    def gravar(self, arquivo: Path) -> None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = arquivo.with_name(arquivo.name + ".tmp")
        provisorio.write_bytes(gzip.compress(json.dumps(self.dados(), ensure_ascii=False).encode("utf-8"), 6))
        provisorio.replace(arquivo)


def comparar_snapshots(antigo: dict, novo: dict) -> str:
    """Quanto o snapshot mudou: folhas que entraram e saíram e, nas folhas que ficaram, a parte dos ASINs que trocou. É a
    medida da estabilidade dos rótulos, que decide o intervalo entre ciclos."""
    a = {f["no"]: set(f["asins"]) for f in antigo["folhas"]}
    n = {f["no"]: set(f["asins"]) for f in novo["folhas"]}
    comuns = a.keys() & n.keys()
    base = sum(len(a[x]) for x in comuns)
    trocaram = sum(len(a[x] ^ n[x]) for x in comuns)
    return (f"folhas: {len(n)} (antes {len(a)}; entraram {len(n.keys() - a.keys())}, saíram {len(a.keys() - n.keys())}); "
            f"nas {len(comuns)} que ficaram, {trocaram} ASINs entraram ou saíram de {base} ({trocaram / base:.1%})"
            if base else f"folhas: {len(n)} (antes {len(a)}; nenhuma em comum)")


def _iso(quando: datetime) -> str:
    return quando.astimezone(timezone.utc).isoformat(timespec="seconds")


def atualizar(abrir_sessao, pasta: Path, *, generos: list[str], k: int = K_PADRAO, minutos: float = 300, intervalo_dias: float = INTERVALO_DIAS,
              max_paginas: int = 3000, pausa: float = PAUSA, novo_ciclo: bool = False, anterior: dict | None = None,
              agora=lambda: datetime.now(timezone.utc), dormir=time.sleep, relogio=time.monotonic, aviso=print) -> int:
    """Uma execução da coleta recorrente (`abrir_sessao()` devolve a sessão, e só é chamada se houver o que ler): continua (ou começa) o ciclo que lê as árvores dos `generos` e as `k` primeiras páginas
    de cada folha, até `minutos` ou `max_paginas` pedidas, e guarda o estado em `pasta/estado.json.gz`. Quando o ciclo termina,
    escreve `pasta/snapshot-novo.json` (e diz o que mudou em relação a `anterior`, se dado). Devolve o código de saída:
    0 (terminou, continua depois ou não havia o que fazer) ou 1 (bloqueio ou falhas seguidas, que gravam a pausa; estado
    ilegível; snapshot recusado)."""
    arquivo_estado = pasta / "estado.json.gz"
    try:
        estado = Estado.ler(arquivo_estado)
    except ValueError as e:
        aviso(f"{e}; não vou começar do zero")
        return 1
    agora_ = agora()
    if estado.pausa_ate and agora_ < datetime.fromisoformat(estado.pausa_ate):
        aviso(f"em pausa até {estado.pausa_ate} (bloqueio ou snapshot recusado); nada a fazer")
        return 0
    if novo_ciclo:
        estado.ciclo = None
    if estado.ciclo is None:
        if not novo_ciclo and estado.ultimo_snapshot and agora_ - datetime.fromisoformat(estado.ultimo_snapshot) < timedelta(days=intervalo_dias):
            aviso(f"nada a fazer: o último snapshot é de {estado.ultimo_snapshot} e o intervalo é de {intervalo_dias:g} dias")
            return 0
        estado.ciclo = {"inicio": _iso(agora_), "k": k, "nos": list(generos), "execucoes": 0, "paginas": {}}
    ciclo = estado.ciclo
    ciclo["execucoes"] += 1
    armazem = Compacto(ciclo["paginas"], pasta / "problemas")
    lidas = [0]

    def avisar(texto: str) -> None:                       # a cada 50 páginas o estado vai para o disco (um corte do job não perde tudo)
        aviso(texto)
        lidas[0] += 1
        if lidas[0] % 50 == 0:
            estado.gravar(arquivo_estado)

    sessao = abrir_sessao()
    leitor = Leitor(sessao, armazem, max_paginas=len(armazem) + max_paginas, pausa=pausa, dormir=dormir, relogio=relogio,
                    aviso=avisar, prazo=relogio() + minutos * 60)
    codigo = 0
    try:
        arvore = descobrir(leitor, ciclo["nos"], None)
        if arvore["completa"]:
            rotular(leitor, arvore, ciclo["k"])
        folhas = folhas_de(arvore)
        faltam = sum(1 for no, i in folhas.items() for p in range(1, min(i["paginas"], ciclo["k"]) + 1) if not armazem.existe(no, p))
        aviso(f"{leitor.pedidas} páginas pedidas nesta execução; {len(armazem)} no ciclo; {len(folhas)} folhas; "
              f"{faltam} páginas de folha ainda por ler" + (f"; parou: {leitor.parou}" if leitor.parou else ""))
        if leitor.parou and leitor.parou not in ("tempo",) and not leitor.parou.startswith("teto"):
            estado.bloqueios += 1
            horas = min(PAUSA_BLOQUEIO_H * 2 ** (estado.bloqueios - 1), PAUSA_MAXIMA_DIAS * 24)
            estado.pausa_ate = _iso(agora() + timedelta(hours=horas))
            aviso(f"{leitor.parou}: pausa de {horas:g} h, até {estado.pausa_ate}")
            codigo = 1
        elif arvore["completa"] and not leitor.parou and (not faltam or ciclo["execucoes"] >= EXECUCOES_ATE_ACEITAR):
            snap = montar_snapshot(arvore, rotulos(armazem, arvore, ciclo["k"]), ciclo["k"], ciclo["nos"], _iso(agora()))
            if anterior and len(snap["folhas"]) < MIN_FOLHAS_NOVAS * len(anterior["folhas"]):
                aviso(f"snapshot recusado: {len(snap['folhas'])} folhas contra {len(anterior['folhas'])} no anterior (menos de "
                      f"{MIN_FOLHAS_NOVAS:.0%}); a Amazon mudou o layout ou a leitura falhou. Próximo ciclo só depois do intervalo")
                estado.pausa_ate = _iso(agora() + timedelta(days=intervalo_dias))
                codigo = 1
            else:
                gravar_json(pasta / "snapshot-novo.json", snap)
                aviso(f"ciclo completo: {len(snap['folhas'])} folhas, {sum(len(x['asins']) for x in snap['folhas'])} ASINs"
                      + (f"; troca em relação ao anterior: {comparar_snapshots(anterior, snap)}" if anterior else ""))
                estado.ultimo_snapshot, estado.bloqueios, estado.pausa_ate = snap["gerado_em"], 0, None
            estado.ciclo = None
    finally:
        estado.gravar(arquivo_estado)
        if hasattr(sessao, "fechar"):
            sessao.fechar()
    return codigo


def gravar_json(arquivo: Path, dados) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    provisorio = arquivo.with_name(arquivo.name + ".tmp")
    provisorio.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    provisorio.replace(arquivo)


def executar(args) -> None:
    """O comando `subgeneros` (os argumentos vêm de __main__.py). Nunca abre banco."""
    pasta = Path(args.pasta)
    arquivo_arvore = pasta / "arvore.json"
    if args.passo == "atualizar":
        nos = [n.strip() for n in args.nos.split(",") if n.strip()] if args.nos else sorted(parecidos.GENEROS_FICCAO)
        desconhecidos = [n for n in nos if n not in varredura.GENEROS]
        if desconhecidos:
            raise SystemExit(f"gênero desconhecido: {', '.join(desconhecidos)}")
        anterior = ler_snapshot(args.anterior) if args.anterior and Path(args.anterior).exists() else None
        codigo = atualizar(lambda: rede.nova_sessao(args.cliente), pasta, generos=nos, k=args.k, minutos=args.minutos,
                           intervalo_dias=args.intervalo_dias, max_paginas=args.max_paginas, pausa=args.pausa,
                           novo_ciclo=args.novo_ciclo, anterior=anterior)
        if codigo:
            raise SystemExit(codigo)
        return
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
