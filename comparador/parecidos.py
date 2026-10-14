"""Livros parecidos, calculados na geração do site (`site.py` grava o resultado em `dados/p/`).

Para cada livro de partida (a "semente"), escolhe entre as obras da busca as mais próximas. A nota é
(G + T) × L × P:
- G, gêneros em comum: cada um pesa pela raridade no índice (log((N+1)/obras do gênero)), e a soma é dividida pela raiz
  do número de gêneros da obra (quem está em muitos gêneros não casa com tudo). Só entra quem tem G > 0;
- T, tema: as palavras do título que dizem o assunto ("python", "investimento", "constitucional"), ver `Palavras`. Só as
  3 mais raras da semente contam, e T nunca passa de G (o tema no máximo dobra o gênero, e sozinho não traz ninguém);
- L, idioma: quando os dois são conhecidos e diferentes, a obra vale OUTRO_IDIOMA;
- P, popularidade (número de avaliações, em escala de log): multiplica pouco, para desempatar.
Ficam de fora a própria obra, o mesmo livro com outro título-base ou outro autor grafado (`base`, `ct`), o mesmo autor
(a página do livro já tem "Mais de …"; autor genérico, como "Vários autores" ou uma editora, não conta como mesmo autor)
e o que a semente mandar excluir (outras edições). Na lista, cada autor aparece no máximo POR_AUTOR vezes, e cada
(autor, começo do título) uma vez só.

A conta é exata e não compara cada semente com cada obra. Sem tema, a nota de uma obra depende só da sua "classe"
(conjunto de gêneros e idioma) e da popularidade: para cada (gêneros, idioma) de semente, um `Fluxo` junta as classes
por heap e devolve as obras já na ordem final. As obras com tema (poucas: as que têm uma das 3 palavras da semente) são
pontuadas uma a uma e entram no meio do fluxo, na posição certa. `bruto()` faz a mesma conta obra por obra e serve de
referência nos testes.
"""

from __future__ import annotations

import functools
import heapq
import math
import multiprocessing
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field

OUTRO_IDIOMA = 0.3
POPULAR = 0.1
POR_AUTOR = 2
N_PARECIDOS = 10
MIN_PARALELO = 20_000     # abaixo disso, dividir entre processos custa mais do que economiza
PESO_TEMA = 0.5
PALAVRAS_SEMENTE = 3      # palavras de tema da semente que contam (as mais raras)
DF_TEMA = (3, 500)        # palavra em menos obras não liga ninguém; em mais, é genérica
NAO_FICCAO_MIN = 0.7      # palavra de assunto: nas obras que a usam, ao menos 70% do peso dos gêneros é de não ficção

# Autores que não identificam ninguém: não servem para dizer que dois livros são do mesmo autor
AUTORES_GENERICOS = frozenset({"", "nao informado", "varios autores", "diversos", "diversos autores", "autor desconhecido",
                               "desconhecido", "various", "various authors", "anonimo"})
_GENERICOS_MAIS = frozenset({"varios", "autores diversos", "vario"})
_EDITORA = re.compile(r"\b(editora|edicoes|publicacoes|publishing|press)\b")
_PARTICULAS = frozenset({"de", "da", "do", "das", "dos", "e", "del", "la", "van", "von", "di", "du", "y", "jr", "junior", "filho", "neto"})
_ARTIGOS = frozenset({"o", "a", "os", "as", "um", "uma", "the", "el", "la", "le", "les", "los"})

# Gêneros de ficção (nós de varredura.GENEROS): as palavras dos títulos deles são nomes e enredo, não assunto ("príncipe",
# "hobbit", "trilogia"). "Livros Internacionais" (7882627011) é um balde de idioma: fica fora da conta (LIVROS_INTERNACIONAIS).
GENEROS_FICCAO = frozenset({"7872687011", "7841775011", "7882388011", "7872829011", "7844001011", "7841279011", "7842710011",
                            "7843058011", "7843064011", "7843925011"})
LIVROS_INTERNACIONAIS = "7882627011"

# Palavras de título que não dizem o assunto: comuns, de edição e de capa
PARADAS = frozenset("""
para como sobre mais voce entre seus suas minha meus nossa nosso esta este essa esse isso aqui onde quando porque pelo pela
pelos pelas tudo todos todas cada outro outra outros outras agora manter criar fazer sempre nunca muito muita muitos
with from your that this what when edition book books livro livros volume volumes edicao edicoes colecao box capa dura
comum vol tomo parte partes serie completo completa nova novo novos novas luxo especial illustrated ilustrado ilustrada
anos guia manual pratico pratica introducao fundamentos teoria analise estudo estudos superposter poster pintura trilateral
capitulo extra marcador marcadores pagina paginas ilustracoes interna internas acompanha brinde brindes original traducao
traduzido atualizada atualizado ampliada ampliado revista revisada revisado premium colecionador comemorativa comemorativo
limitada exclusiva exclusivo deluxe almofadada kindle ebook english portuguese idioma portugues vários varios
about after before into over under more most best great good little first last next every never always made make makes
making easy simple proven ways step steps guide guides handbook complete edition editions revised updated lesson lessons
basic everyday word words power using used your their there they them then than will would could should have just only
also very much many some such while where which whose novel story stories volume
""".split())


_ACENTOS = re.compile("[\u0300-\u036f]")


class _Subtitulo:
    """Divide "Título: subtítulo" (também " – ", " — ", " - ") em (título, separador, subtítulo)."""
    _RE = re.compile(r"\s*[:–—―]\s|\s+-\s")

    def partition(self, t: str) -> tuple[str, str, str]:
        m = self._RE.search(t)
        return (t[:m.start()], m.group(), t[m.end():]) if m else (t, "", "")


_SUBTITULO = _Subtitulo()
# subtítulo que descreve a edição, não o assunto
_EDICAO_NO_SUBTITULO = re.compile(r"\b(edicao|traducao|original|capa|ilustrad\w*|box|volume|vol|luxo|bolso|colecionador|brinde|poster)\b")


def _sem_acento(texto: str) -> str:
    """Sem acentos (os sinais combinantes do latim) e em minúsculas."""
    texto = texto or ""
    return texto.lower() if texto.isascii() else _ACENTOS.sub("", unicodedata.normalize("NFD", texto)).lower()


def _autor_principal(autor: str) -> str:
    principal = re.split(r",|;| e | and | & ", autor or "", maxsplit=1)[0]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _sem_acento(principal)).split())


@functools.lru_cache(maxsize=None)
def chave_autor(autor: str) -> str:
    """O autor principal, sem acento, pontuação nem partículas, com as palavras em ordem: "Rowling J.K", "J. K. Rowling e
    Fulano" e "ROWLING, J.K." dão todos "j k rowling"; palavra repetida conta uma vez ("Cury Augusto Cury")."""
    return " ".join(sorted({p for p in _autor_principal(autor).split() if p not in _PARTICULAS}))


@functools.lru_cache(maxsize=None)
def autor_generico(autor: str) -> bool:
    a = _autor_principal(autor)
    return a in AUTORES_GENERICOS or a in _GENERICOS_MAIS or bool(_EDITORA.search(a))


def chave_titulo(base: str) -> str:
    """As duas primeiras palavras do título-base, sem artigo: o "mesmo livro" com subtítulos diferentes."""
    return " ".join([p for p in re.sub(r"[^a-z0-9]+", " ", _sem_acento(base)).split() if p not in _ARTIGOS][:2])


# "Mais de …": quais grafias de autor são a mesma pessoa (chaves_do_autor)
DOMINANCIA = 8            # uma ordem com 8 vezes as obras da outra (e a outra com poucas) é a "certa": a outra é o nome invertido
POUCAS = 3
_VARIANTES_AUTOR = {"junior": "jr"}
_FIM_DA_SERIE = frozenset({"vol", "volume", "livro", "parte", "tomo", "edicao"})


def palavras_autor(autor: str) -> tuple[str, ...]:
    """O autor principal em palavras, sem acento nem pontuação, na ordem em que vieram e com as partículas ("de", "von") e
    os sufixos ("Filho", "Neto"); palavra repetida conta uma vez ("Fabio Fabio Guerrini") e "Junior" vale "Jr"."""
    return tuple(dict.fromkeys(_VARIANTES_AUTOR.get(p, p) for p in _autor_principal(autor).split()))


def serie(base: str) -> str:
    """O começo do título-base que identifica a série: até duas palavras, sem artigo, antes do primeiro número ou "volume"
    ("Gokurakugai 05" → "gokurakugai", "Quero te amar até o fim 01" → "quero te"). Vazio se for curto demais."""
    out = []
    for p in re.sub(r"[^a-z0-9]+", " ", _sem_acento(base)).split():
        if p in _ARTIGOS:
            continue
        if p.isdigit() or p in _FIM_DA_SERIE:
            break
        out.append(p)
        if len(out) == 2:
            break
    s = " ".join(out)
    return s if len(s) >= 5 else ""


def chaves_do_autor(autores: list[str], bases: list[str]) -> list[str | None]:
    """A chave de "Mais de …" de cada obra: obras com a mesma chave são do mesmo autor. `bases` são os títulos-base
    (site.titulo_base), um por obra. None (sem "Mais de …") para autor genérico, editora, sem nome ou curto demais.

    A chave é as palavras do autor principal na ordem em que vieram. Maiúsculas, acentos, pontuação, palavra repetida e
    "Jr"/"Junior" não separam ninguém. Partículas e sufixos separam: "Paula Di Carvalho" e "Paula Carvalho", "Ricardo Ramos"
    e "Ricardo Ramos Filho" são pessoas diferentes.

    As mesmas palavras em outra ordem ("Rowling J.K" e "J. K. Rowling") só se juntam com prova: um título-base em comum,
    a mesma série (o começo do título), ou uma ordem com DOMINANCIA vezes as obras da outra, que tem poucas (o nome invertido
    de quem quase sempre aparece de um jeito só). Sem prova ficam separadas: "Maya Grace" e "Grace Maya", ou "Joseph Frank" e
    "Frank Joseph" (5 obras contra 1), são pessoas diferentes."""
    exatas: list[str | None] = []
    for a in autores:
        e = "" if autor_generico(a) else " ".join(palavras_autor(a))
        exatas.append(e if len(e) >= 4 and any(c.isalpha() for c in e) else None)
    obras_de: dict[str, list[int]] = {}
    for i, e in enumerate(exatas):
        if e:
            obras_de.setdefault(e, []).append(i)
    ordens: dict[str, list[str]] = {}                     # as mesmas palavras, em ordens diferentes
    for e in obras_de:
        ordens.setdefault(" ".join(sorted(e.split())), []).append(e)
    chave = {e: e for e in obras_de}
    for grafias in ordens.values():
        if len(grafias) < 2:
            continue
        grafias.sort(key=lambda e: (-len(obras_de[e]), e))
        bases_de = {e: {bases[i] for i in obras_de[e] if len(bases[i]) >= 4} for e in grafias}
        series_de = {e: {serie(bases[i]) for i in obras_de[e]} - {""} for e in grafias}
        pai = {e: e for e in grafias}

        def raiz(e):
            while pai[e] != e:
                e = pai[e]
            return e

        for x, a in enumerate(grafias):
            for b in grafias[x + 1:]:                       # a tem mais obras que b, ou as mesmas e vem antes
                na, nb = len(obras_de[a]), len(obras_de[b])
                if bases_de[a] & bases_de[b] or series_de[a] & series_de[b] or (nb <= POUCAS and na >= DOMINANCIA * nb):
                    pai[raiz(b)] = raiz(a)
        for e in grafias:
            chave[e] = raiz(e)
    return [chave[e] if e else None for e in exatas]


def palavras(titulo: str) -> frozenset[str]:
    """As palavras do título que podem dizer o assunto: sem o que está entre parênteses, com 4 letras ou mais, sem número
    puro nem as PARADAS, no singular simples ("investimentos" → "investimento")."""
    out = set()
    for p in re.split(r"[^a-z0-9]+", re.sub(r"[(\[][^)\]]*[)\]]", " ", _sem_acento(titulo))):
        if len(p) < 4 or p.isdigit() or p in PARADAS:
            continue
        if len(p) > 4 and p.endswith("s"):
            p = p[:-1]
        out.add(p)
    return frozenset(out)


def popular(avaliacoes: int) -> float:
    return 1 + POPULAR * math.log(1 + (avaliacoes or 0)) / math.log(10)


@dataclass
class Obra:
    """Uma obra da busca. `gen`: posições dos gêneros em ordem crescente; `pos`: posição no índice (desempate final);
    `base`: o título-base (site.titulo_base), para reconhecer o mesmo livro."""
    pos: int
    titulo: str
    autor: str
    gen: tuple[int, ...]
    idioma: str = ""
    av: int = 0
    base: str = ""
    a: str = field(init=False)
    ag: bool = field(init=False)
    ct: str = field(init=False)
    p: float = field(init=False)
    tk: frozenset[str] = field(init=False)

    def __post_init__(self):
        self.a, self.ag = chave_autor(self.autor), autor_generico(self.autor)
        self.ct = chave_titulo(self.base or self.titulo)
        self.p = popular(self.av)
        self.tk = palavras(self.titulo)

    def ordem(self, nota: float) -> tuple:
        """Ordem final: nota, avaliações, título e posição."""
        return (-nota, -(self.av or 0), self.titulo, self.pos)


@dataclass
class Semente:
    """Livro de partida. `obra`: a posição da própria obra na busca (None se ela não está na busca);
    `excluir`: outras posições que não podem aparecer (outras edições, mais do autor)."""
    gen: tuple[int, ...]
    idioma: str = ""
    autor: str = ""
    obra: int | None = None
    excluir: frozenset[int] = frozenset()
    titulo: str = ""
    base: str = ""


def raridade(obras: list[Obra], n_generos: int) -> list[float]:
    df = [0] * n_generos
    for o in obras:
        for g in o.gen:
            df[g] += 1
    n = len(obras)
    return [math.log((n + 1) / d) if d else 0.0 for d in df]


class Palavras:
    """Quais palavras de título contam como tema, e quanto. Uma palavra conta se aparece em DF_TEMA obras e se, nessas
    obras, o peso dos gêneros de não ficção (pela raridade) passa de NAO_FICCAO_MIN em média; obras só em `balde`
    (Livros Internacionais) não entram na média."""

    def __init__(self, obras: list[Obra], idf_gen: list[float], ficcao: frozenset[int], balde: frozenset[int]):
        df, soma_nf, n_nf = {}, {}, {}
        for o in obras:
            gens = [g for g in o.gen if g not in balde]
            total = sum(idf_gen[g] for g in gens)
            nf = sum(idf_gen[g] for g in gens if g not in ficcao) / total if total else None
            for p in o.tk:
                df[p] = df.get(p, 0) + 1
                if nf is not None:
                    soma_nf[p] = soma_nf.get(p, 0.0) + nf
                    n_nf[p] = n_nf.get(p, 0) + 1
        n = len(obras)
        self.idf = {p: math.log((n + 1) / d) for p, d in df.items()
                    if DF_TEMA[0] <= d <= DF_TEMA[1] and n_nf.get(p) and soma_nf[p] / n_nf[p] >= NAO_FICCAO_MIN}

    def da_semente(self, titulo: str) -> tuple[str, ...]:
        """Até PALAVRAS_SEMENTE palavras: primeiro as do título principal (antes do subtítulo, onde fica o assunto:
        "Hábitos Atômicos: um método fácil e comprovado…"), depois as do subtítulo; em cada parte, das mais raras para
        as menos, e no empate pela palavra (nunca pela ordem de um set, que muda a cada execução)."""
        principal, _, resto = _SUBTITULO.partition(titulo or "")
        if _EDICAO_NO_SUBTITULO.search(_sem_acento(resto)):     # "Tradução original com aquarelas do autor": é a edição
            resto = ""
        out = []
        for parte in (principal, resto):
            for p in sorted((p for p in palavras(parte) if p in self.idf and p not in out), key=lambda p: (-self.idf[p], p)):
                out.append(p)
        return tuple(out[:PALAVRAS_SEMENTE])

    def tema(self, sem: tuple[str, ...], o: Obra) -> float:
        s = sum(self.idf[p] for p in sem if p in o.tk)
        return PESO_TEMA * s / math.sqrt(max(1, len(o.tk))) if s else 0.0


def _nota_genero(idf: list[float], mascara: int, gen: tuple[int, ...]) -> float:
    """Gêneros em comum somados na ordem dos gêneros da obra (a mesma nas duas contas, para os empates baterem)."""
    s = 0.0
    for g in gen:
        if mascara >> g & 1:
            s += idf[g]
    return s / math.sqrt(len(gen)) if s else 0.0


def _fator_idioma(a: str, b: str) -> float:
    return OUTRO_IDIOMA if a and b and a != b else 1.0


def _nota(g0: float, t: float, fator: float, p: float) -> float:
    return (g0 + min(t, g0)) * fator * p


class Fluxo:
    """As obras com algum gênero em comum com `mascara`, na ordem da nota sem tema, para sementes de mesmos gêneros e
    idioma. As classes ficam em ordem do teto (a nota da mais popular de cada uma) e só entram no heap quando o teto
    alcança a próxima nota a sair: assim o heap tem poucas classes, e a ordem continua exata."""

    def __init__(self, ind: "_Indice", mascara: int, idioma: str):
        self.ind, self.feitos, self.heap = ind, [], []
        tetos = []
        for gen, membros_por_idioma in ind.relevantes(mascara):
            g0 = _nota_genero(ind.idf, mascara, gen)
            for k in membros_por_idioma:
                f = g0 * _fator_idioma(idioma, k[1])
                tetos.append((f * ind.classes[k][0].p, f, k))
        tetos.sort(key=lambda x: -x[0])
        self.tetos, self.prox = tetos, 0

    def item(self, j: int) -> tuple[float, Obra] | None:
        """O j-ésimo do fluxo (None no fim)."""
        classes, tetos, heap = self.ind.classes, self.tetos, self.heap
        while len(self.feitos) <= j:
            # entra toda classe cujo teto alcança a melhor nota do heap (com empate, entra: o desempate é no heap)
            while self.prox < len(tetos) and (not heap or tetos[self.prox][0] >= -heap[0][0][0]):
                _, f, k = tetos[self.prox]
                o = classes[k][0]
                heapq.heappush(heap, (o.ordem(f * o.p), f, 0, k))
                self.prox += 1
            if not heap:
                break
            _, f, i, k = heapq.heappop(heap)
            membros = classes[k]
            o = membros[i]
            self.feitos.append((f * o.p, o))
            if i + 1 < len(membros):
                prox = membros[i + 1]
                heapq.heappush(heap, (prox.ordem(f * prox.p), f, i + 1, k))
        return self.feitos[j] if j < len(self.feitos) else None


class _Indice:
    def __init__(self, obras: list[Obra], n_generos: int, ficcao: frozenset[int], balde: frozenset[int]):
        self.obras, self.n_generos = obras, n_generos
        self.idf = raridade(obras, n_generos)
        self.palavras = Palavras(obras, self.idf, ficcao, balde)
        self.classes: dict[tuple, list[Obra]] = {}
        self.com_palavra: dict[str, list[Obra]] = {}
        for o in obras:
            if o.gen:
                self.classes.setdefault((o.gen, o.idioma), []).append(o)
                for p in o.tk:
                    if p in self.palavras.idf:
                        self.com_palavra.setdefault(p, []).append(o)
        for membros in self.classes.values():
            membros.sort(key=lambda o: o.ordem(o.p))      # dentro da classe, sem tema, a nota só varia com a popularidade
        self.classes_por_genero: dict[tuple, list[tuple]] = {}       # conjunto de gêneros → as classes (uma por idioma)
        for k in self.classes:
            self.classes_por_genero.setdefault(k[0], []).append(k)
        self.gens_do_genero: list[list[tuple]] = [[] for _ in range(n_generos)]
        for gen in self.classes_por_genero:
            for g in gen:
                self.gens_do_genero[g].append(gen)
        self.fluxos: dict[tuple, Fluxo] = {}

    def relevantes(self, mascara: int):
        """Os conjuntos de gêneros com algum gênero da máscara, cada um com as suas classes (uma por idioma)."""
        vistos = set()
        for g in range(self.n_generos):
            if mascara >> g & 1:
                for gen in self.gens_do_genero[g]:
                    if gen not in vistos:
                        vistos.add(gen)
                        yield gen, self.classes_por_genero[gen]

    def fluxo(self, mascara: int, idioma: str) -> Fluxo:
        k = (mascara, idioma)
        if k not in self.fluxos:
            self.fluxos[k] = Fluxo(self, mascara, idioma)
        return self.fluxos[k]


def _escolher(candidatos, s: Semente, n: int) -> list[int]:
    """Percorre os candidatos (já na ordem final) aplicando as exclusões, o limite por autor e o mesmo livro uma vez só."""
    autor = chave_autor(s.autor) if not autor_generico(s.autor) else ""
    base, ct, a_s = s.base, chave_titulo(s.base or s.titulo), chave_autor(s.autor)
    out, por_autor, vistos = [], {}, set()
    for _, o in candidatos:
        if o.pos == s.obra or o.pos in s.excluir or (autor and o.a == autor):
            continue
        if base and o.base == base:                                          # o mesmo livro, de outro autor ou sem autor
            continue
        if ct and o.ct == ct and (o.a == a_s or not o.a or not a_s):
            continue
        if (o.a, o.ct) in vistos:                                            # duas edições do mesmo livro na lista
            continue
        if o.a:
            por_autor[o.a] = por_autor.get(o.a, 0) + 1
            if por_autor[o.a] > POR_AUTOR:
                continue
        vistos.add((o.a, o.ct))
        out.append(o.pos)
        if len(out) >= n:
            break
    return out


def _candidatos(ind: _Indice, s: Semente):
    """Todas as obras com gênero em comum, na ordem final: o fluxo sem tema, com as obras de tema intercaladas."""
    mascara = sum(1 << g for g in s.gen)
    sem = ind.palavras.da_semente(s.titulo)
    com_tema = {}
    for p in sem:
        for o in ind.com_palavra.get(p, ()):
            if o.pos in com_tema:
                continue
            g0 = _nota_genero(ind.idf, mascara, o.gen)
            if g0 > 0:
                com_tema[o.pos] = (_nota(g0, ind.palavras.tema(sem, o), _fator_idioma(s.idioma, o.idioma), o.p), o)
    lista_tema = sorted(com_tema.values(), key=lambda x: x[1].ordem(x[0]))
    fl, j, t = ind.fluxo(mascara, s.idioma), 0, 0
    while True:
        b = fl.item(j)
        while b and b[1].pos in com_tema:                                    # essas já estão na lista de tema
            j += 1
            b = fl.item(j)
        if t < len(lista_tema) and (b is None or lista_tema[t][1].ordem(lista_tema[t][0]) < b[1].ordem(b[0])):
            yield lista_tema[t]
            t += 1
        elif b:
            yield b
            j += 1
        else:
            return


def _lista(ind: _Indice, s: Semente, n: int) -> list[int]:
    return _escolher(_candidatos(ind, s), s, n) if s.gen else []


def bruto(obras: list[Obra], n_generos: int, s: Semente, n: int = N_PARECIDOS,
          ficcao: frozenset[int] = frozenset(), balde: frozenset[int] = frozenset()) -> list[int]:
    """Referência: a mesma conta, obra por obra."""
    idf = raridade(obras, n_generos)
    pal = Palavras(obras, idf, ficcao, balde)
    sem = pal.da_semente(s.titulo)
    mascara = sum(1 << g for g in s.gen)
    notas = []
    for o in obras:
        if not o.gen:
            continue
        g0 = _nota_genero(idf, mascara, o.gen)
        if g0 > 0:
            notas.append((_nota(g0, pal.tema(sem, o), _fator_idioma(s.idioma, o.idioma), o.p), o))
    notas.sort(key=lambda x: x[1].ordem(x[0]))
    return _escolher(notas, s, n)


_ESTADO: tuple | None = None    # o que os processos filhos herdam pelo fork


def _trabalho(faixa: list[int]) -> list[list[int]]:
    ind, sementes, n = _ESTADO
    return [_lista(ind, sementes[i], n) for i in faixa]


def calcular(obras: list[Obra], n_generos: int, sementes: list[Semente], n: int = N_PARECIDOS, processos: int | None = None,
             ficcao: frozenset[int] = frozenset(), balde: frozenset[int] = frozenset()) -> list[list[int]]:
    """Os parecidos de cada semente (posições em `obras`, na ordem). `ficcao` e `balde`: posições dos gêneros de ficção e
    de Livros Internacionais (ver `Palavras`). O mesmo resultado com qualquer número de processos."""
    global _ESTADO
    ind = _Indice(obras, n_generos, ficcao, balde)
    if processos is None:
        processos = os.cpu_count() or 1
        if (len(sementes) < MIN_PARALELO or threading.active_count() > 1
                or "fork" not in multiprocessing.get_all_start_methods()):
            processos = 1
    if processos <= 1:
        return [_lista(ind, s, n) for s in sementes]
    # sementes de mesmos gêneros e idioma no mesmo processo: cada um monta só os seus fluxos
    ordem = sorted(range(len(sementes)), key=lambda i: (sementes[i].gen, sementes[i].idioma, i))
    tam = -(-len(ordem) // processos)
    faixas = [ordem[i:i + tam] for i in range(0, len(ordem), tam)]
    _ESTADO = (ind, sementes, n)
    try:
        with multiprocessing.get_context("fork").Pool(processos) as pool:
            partes = pool.map(_trabalho, faixas)
    finally:
        _ESTADO = None
    out: list[list[int]] = [[] for _ in sementes]
    for faixa, parte in zip(faixas, partes):
        for i, lista in zip(faixa, parte):
            out[i] = lista
    return out
