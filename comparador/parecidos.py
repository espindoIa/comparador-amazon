"""Livros parecidos, calculados na geração do site (`site.py` grava o resultado em `dados/p/`).

Para cada livro de partida (a "semente"), escolhe entre as obras da busca as mais próximas:
- gêneros em comum, cada um pesando pela raridade no índice (log((N+1)/obras do gênero)), divididos pela raiz do
  número de gêneros da obra (quem está em muitos gêneros não casa com tudo);
- idioma: quando os dois são conhecidos e diferentes, a obra vale OUTRO_IDIOMA;
- popularidade (número de avaliações, em escala de log) multiplica pouco, para desempatar.
Só entra quem tem pelo menos um gênero em comum. Ficam de fora a própria obra, o mesmo autor (a página do livro já
tem "Mais de …") e o que a semente mandar excluir (outras edições); cada autor aparece no máximo POR_AUTOR vezes.

A conta é exata e não compara cada semente com cada obra: a nota de uma obra depende só da sua "classe" (conjunto de
gêneros e idioma) e da popularidade. Para cada (gêneros, idioma) de semente, um `Fluxo` junta as classes por heap e
devolve as obras já na ordem final; cada semente só percorre o começo do fluxo, aplicando as exclusões. `bruto()`
faz a mesma conta obra por obra e serve de referência nos testes.
"""

from __future__ import annotations

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


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if not unicodedata.combining(c)).lower()


def chave_autor(autor: str) -> str:
    """O autor principal, sem acento nem pontuação: "J.K. Rowling e Fulano" → "j k rowling"."""
    principal = re.split(r",|;| e | and | & ", autor or "", maxsplit=1)[0]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _sem_acento(principal)).split())


def popular(avaliacoes: int) -> float:
    return 1 + POPULAR * math.log(1 + (avaliacoes or 0)) / math.log(10)


@dataclass
class Obra:
    """Uma obra da busca. `gen`: posições dos gêneros em ordem crescente; `pos`: posição no índice (desempate final)."""
    pos: int
    titulo: str
    autor: str
    gen: tuple[int, ...]
    idioma: str = ""
    av: int = 0
    a: str = field(init=False)
    p: float = field(init=False)

    def __post_init__(self):
        self.a = chave_autor(self.autor)
        self.p = popular(self.av)

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


def raridade(obras: list[Obra], n_generos: int) -> list[float]:
    df = [0] * n_generos
    for o in obras:
        for g in o.gen:
            df[g] += 1
    n = len(obras)
    return [math.log((n + 1) / d) if d else 0.0 for d in df]


def _nota_genero(idf: list[float], mascara: int, gen: tuple[int, ...]) -> float:
    """Gêneros em comum somados na ordem dos gêneros da obra (a mesma nas duas contas, para os empates baterem)."""
    s = 0.0
    for g in gen:
        if mascara >> g & 1:
            s += idf[g]
    return s / math.sqrt(len(gen)) if s else 0.0


def _fator_idioma(a: str, b: str) -> float:
    return OUTRO_IDIOMA if a and b and a != b else 1.0


class Fluxo:
    """As obras com algum gênero em comum com `mascara`, na ordem final, para sementes de mesmos gêneros e idioma."""

    def __init__(self, ind: "_Indice", mascara: int, idioma: str):
        self.ind, self.feitos = ind, []
        self.heap = []
        vistas = set()
        for g in range(ind.n_generos):
            if not mascara >> g & 1:
                continue
            for k in ind.classes_do_genero[g]:
                if k in vistas:
                    continue
                vistas.add(k)
                gen, idi = k
                f = _nota_genero(ind.idf, mascara, gen) * _fator_idioma(idioma, idi)
                if f > 0:
                    o = ind.classes[k][0]
                    self.heap.append((o.ordem(f * o.p), f, 0, k))
        heapq.heapify(self.heap)

    def ate(self, n: int) -> list[tuple[float, Obra]]:
        while len(self.feitos) < n and self.heap:
            _, f, j, k = heapq.heappop(self.heap)
            membros = self.ind.classes[k]
            o = membros[j]
            self.feitos.append((f * o.p, o))
            if j + 1 < len(membros):
                prox = membros[j + 1]
                heapq.heappush(self.heap, (prox.ordem(f * prox.p), f, j + 1, k))
        return self.feitos


class _Indice:
    def __init__(self, obras: list[Obra], n_generos: int):
        self.obras, self.n_generos = obras, n_generos
        self.idf = raridade(obras, n_generos)
        self.classes: dict[tuple, list[Obra]] = {}
        for o in obras:
            if o.gen:
                self.classes.setdefault((o.gen, o.idioma), []).append(o)
        for membros in self.classes.values():
            membros.sort(key=lambda o: o.ordem(o.p))      # dentro da classe a nota só varia com a popularidade
        self.classes_do_genero: list[list[tuple]] = [[] for _ in range(n_generos)]
        for k in self.classes:
            for g in k[0]:
                self.classes_do_genero[g].append(k)
        self.fluxos: dict[tuple, Fluxo] = {}

    def fluxo(self, s: Semente) -> Fluxo:
        mascara = sum(1 << g for g in s.gen)
        k = (mascara, s.idioma)
        if k not in self.fluxos:
            self.fluxos[k] = Fluxo(self, mascara, s.idioma)
        return self.fluxos[k]


def _escolher(candidatos, s: Semente, n: int) -> list[int]:
    """Percorre os candidatos (já na ordem final) aplicando as exclusões e o limite por autor."""
    autor, out, por_autor = chave_autor(s.autor), [], {}
    for _, o in candidatos:
        if o.pos == s.obra or o.pos in s.excluir or (autor and o.a == autor):
            continue
        if o.a:
            por_autor[o.a] = por_autor.get(o.a, 0) + 1
            if por_autor[o.a] > POR_AUTOR:
                continue
        out.append(o.pos)
        if len(out) >= n:
            break
    return out


def _lista(ind: _Indice, s: Semente, n: int) -> list[int]:
    if not s.gen:
        return []
    fl = ind.fluxo(s)
    pedido = 4 * n
    while True:
        feitos = fl.ate(pedido)
        out = _escolher(feitos, s, n)
        if len(out) >= n or len(feitos) < pedido:
            return out
        pedido *= 2


def bruto(obras: list[Obra], n_generos: int, s: Semente, n: int = N_PARECIDOS) -> list[int]:
    """Referência: a mesma conta, obra por obra."""
    idf = raridade(obras, n_generos)
    mascara = sum(1 << g for g in s.gen)
    notas = []
    for o in obras:
        if not o.gen:
            continue
        f = _nota_genero(idf, mascara, o.gen) * _fator_idioma(s.idioma, o.idioma)
        if f > 0:
            notas.append((f * o.p, o))
    notas.sort(key=lambda x: x[1].ordem(x[0]))
    return _escolher(notas, s, n)


_ESTADO: tuple | None = None    # o que os processos filhos herdam pelo fork


def _trabalho(faixa: range) -> list[list[int]]:
    ind, sementes, n = _ESTADO
    return [_lista(ind, sementes[i], n) for i in faixa]


def calcular(obras: list[Obra], n_generos: int, sementes: list[Semente], n: int = N_PARECIDOS,
             processos: int | None = None) -> list[list[int]]:
    """Os parecidos de cada semente (posições em `obras`, na ordem). O mesmo resultado com qualquer número de processos."""
    global _ESTADO
    ind = _Indice(obras, n_generos)
    if processos is None:
        processos = os.cpu_count() or 1
        if (len(sementes) < MIN_PARALELO or threading.active_count() > 1
                or "fork" not in multiprocessing.get_all_start_methods()):
            processos = 1
    if processos <= 1:
        return [_lista(ind, s, n) for s in sementes]
    _ESTADO = (ind, sementes, n)
    try:
        tam = -(-len(sementes) // processos)
        faixas = [range(i, min(i + tam, len(sementes))) for i in range(0, len(sementes), tam)]
        with multiprocessing.get_context("fork").Pool(processos) as pool:
            partes = pool.map(_trabalho, faixas)
    finally:
        _ESTADO = None
    return [lista for parte in partes for lista in parte]
