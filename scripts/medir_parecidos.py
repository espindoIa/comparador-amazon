"""Mede os parecidos (comparador/parecidos.py) sobre um índice de verdade: tempo, tamanho dos arquivos `p/`, diversidade
e as listas de livros-sonda, para revisão a olho. Só lê: o índice vem de uma pasta `dados/` gerada pelo comando `site`
ou do site publicado.

    python scripts/medir_parecidos.py https://espindoia.github.io/comparador-amazon/dados
    python scripts/medir_parecidos.py site/dados --sonda "O Hobbit" --sonda "Python"

As listas saem iguais às do site, exceto pelas exclusões de "Outras edições" e "Mais de …", que o índice não traz.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comparador import site  # noqa: E402

SONDAS = ["O Hobbit", "Pai rico, pai pobre", "Python Fluente", "É assim que acaba", "Sapiens", "Direito Constitucional Esquematizado",
          "A biblioteca da meia-noite", "Hábitos Atômicos", "O Pequeno Príncipe", "1984", "Torto arado", "Box Harry Potter",
          "Investimentos inteligentes", "Mindset", "A revolução dos bichos", "Código limpo", "Ansiedade", "O poder do agora",
          "Atomic Habits", "Dom Casmurro", "One Piece", "Bíblia", "Turma da Mônica", "Verity", "Diário de um banana"]


def ler_json(origem: str, nome: str):
    if origem.startswith(("http://", "https://")):
        with urllib.request.urlopen(f"{origem.rstrip('/')}/{nome}", timeout=120) as r:
            return json.load(r)
    return json.loads((Path(origem) / nome).read_text(encoding="utf-8"))


def montar(origem: str):
    """As obras do índice no formato que `site._parecidos` usa (sem o histórico, que o índice não traz)."""
    p0 = ler_json(origem, "indice-0.json")
    linhas = list(p0["o"])
    for n in range(1, p0.get("partes", 1)):
        linhas += ler_json(origem, f"indice-{n}.json")["o"]
    obras, livros = [], {}
    for linha in linhas:
        eds = [e[0] for e in linha[8]]
        for e in linha[8]:
            livros[e[0]] = {"f": p0["fmt"][e[1]], "g": set(), "t": linha[0]}
        obras.append({"linha": linha, "eds": eds, "titulo": linha[0], "autor": linha[1], "pop": linha[7],
                      "idioma": p0["idi"][linha[4] - 1] if linha[4] else "", "base": site.titulo_base(linha[0])})
    t = {"gen": site.Tabela()}
    for g in p0["gen"]:
        t["gen"](g[0])
    return p0, obras, livros, t


def medir(origem: str, sondas: list[str]) -> str:
    out = []
    t0 = time.monotonic()
    p0, obras, livros, t = montar(origem)
    out.append(f"obras: {len(obras)} (lidas em {time.monotonic() - t0:.1f} s)")
    t0 = time.monotonic()
    obra_de = {a: i for i, o in enumerate(obras) for a in o["eds"]}
    arquivos = site._parecidos(obras, livros, obra_de, {}, {}, t)
    out.append(f"parecidos e arquivos p/: {time.monotonic() - t0:.1f} s")
    crus = [site._json(c).encode() for c in arquivos.values()]
    gz = sorted(len(gzip.compress(c, 6)) for c in crus)
    out.append(f"p/: {len(crus)} arquivos; total {sum(len(c) for c in crus) / 2**20:.0f} MB cru, {sum(gz) / 2**20:.1f} MB gzip; "
               f"gzip por arquivo: mediana {statistics.median(gz) / 1024:.0f} KB, p90 {gz[int(len(gz) * .9)] / 1024:.0f} KB, "
               f"máx {gz[-1] / 1024:.0f} KB")
    listas = {}
    for arq in arquivos.values():
        for asin, e in arq["p"].items():
            listas[asin] = [arq["c"][i] for i in arq["l"][e[0]]]
    por_obra = {o["eds"][0]: tuple(c[0] for c in listas.get(o["eds"][0], [])) for o in obras}
    cont = collections.Counter(a for lista in por_obra.values() for a in lista)
    titulo = {o["eds"][0]: o["titulo"] for o in obras}
    out.append(f"diversidade: {len(set(por_obra.values()))} listas distintas para {len(por_obra)} obras; "
               f"{sum(1 for v in por_obra.values() if v)} com lista; {len(cont)} obras aparecem em alguma")
    out.append("mais exibidos: " + "; ".join(f"{titulo[a][:40]} ({n})" for a, n in cont.most_common(20)))
    norm = lambda s: site.normalizar(s).strip()  # noqa: E731
    for q in sondas:
        o = next((o for o in obras if norm(o["titulo"]).startswith(norm(q))), None)
        if not o:
            out.append(f"\n## {q}: não está no índice")
            continue
        gens = ", ".join(p0["gen"][g][1] for g in o["linha"][5])
        out.append(f"\n## {o['titulo'][:70]} — {o['autor'] or '?'} [{gens}] {o['idioma']}")
        for c in listas.get(o["eds"][0], []):
            out.append(f"   - {c[1][:60]} — {c[5] or '?'}")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("origem", help="pasta dados/ do site gerado, ou o endereço da pasta dados/ do site publicado")
    p.add_argument("--sonda", action="append", help="título (começo) de um livro para mostrar a lista; repetível (padrão: as sondas fixas)")
    a = p.parse_args(argv)
    print(medir(a.origem, a.sonda or SONDAS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
