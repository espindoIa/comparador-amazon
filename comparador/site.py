"""Gera o site estático (busca por título, histórico de cada livro e lista de desejos).

Entrada: um ou mais bancos do catálogo. Saída: uma pasta com HTML, CSS, JavaScript e dados em JSON,
que pode ser servida por qualquer hospedagem estática (GitHub Pages). Não há servidor: a busca e a
lista de desejos rodam no navegador (a lista fica guardada só no navegador de quem a cria).

Dados gerados em `dados/`:
- `indice.json`  uma linha por livro visível, para a busca (some o que não foi visto depois do filtro
                 "vendido pela Amazon"; o histórico dele continua nos `h/`): [asin, título, formato, preço atual, preço de capa, último dia visto,
                 autor, código da capa, publicado (AAAA-MM-DD), idioma, obra (ASIN que agrupa os formatos)]
- `h/XX.json`    (com autor, imagem, publicado, idioma e obra quando conhecidos) histórico de ~1/256 dos livros (XX = hash de 1 byte do ASIN, em hexadecimal), carregado sob demanda
- `meta.json`    data da última coleta, totais e aviso (bancos simulados)
- `eventos.json` promoções (de eventos.csv)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .db import dia_brasil
from .relatorio import BURACO, WEB, aviso, ler_eventos

DETALHES = ("autor", "imagem", "publicado", "idioma", "obra")
ARQUIVOS_WEB = ("index.html", "livro.html", "app.js", "lista.js", "livro.js", "estilo.css")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def fragmento(asin: str) -> str:
    """Arquivo de histórico do livro. Mesma conta em app.js (`fragmento`): hash simples, 256 arquivos."""
    h = 0
    for c in asin:
        h = (h * 31 + ord(c)) % 256
    return f"{h:02x}"


def juntar_trechos(trechos: list[list]) -> list[list]:
    """Junta históricos do mesmo livro vindos de bancos diferentes: trechos com o mesmo preço que se
    tocam (ou ficam a até BURACO dias um do outro) viram um só."""
    out: list[list] = []
    for t in sorted(trechos, key=lambda t: (t[0], t[1])):
        if out and out[-1][2] == t[2] and t[0] <= out[-1][1] + BURACO:
            out[-1][1] = max(out[-1][1], t[1])
            out[-1][3] = out[-1][3] or t[3]
        else:
            out.append(list(t))
    return out


def corte_amazon(conn: sqlite3.Connection) -> int | None:
    """Dia (ordinal) a partir do qual só vale o que foi visto: é o início do filtro "vendido pela Amazon",
    mas só depois que uma varredura completa com o filtro terminou (antes, o catálogo ainda está sendo
    refeito e esconder o que falta esvaziaria a busca). None = não esconder nada."""
    try:
        desde = conn.execute("SELECT valor FROM config WHERE chave = 'so_amazon_desde'").fetchone()
        if not desde:
            return None
        ok = conn.execute("SELECT 1 FROM dias WHERE completo_em >= ? LIMIT 1", (desde[0],)).fetchone()
    except sqlite3.OperationalError:       # banco sem essas tabelas (anterior ao filtro)
        return None
    return dia_brasil(desde[0]).toordinal() if ok else None


def ler_banco(caminho: Path, livros: dict[str, dict]) -> str:
    """Soma os livros de um banco em `livros`. Devolve o aviso do banco (vazio se não houver)."""
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        corte = corte_amazon(conn)
        colunas = {c[1] for c in conn.execute("PRAGMA table_info(catalogo)")}
        detalhes = ", ".join(c if c in colunas else f"NULL AS {c}" for c in DETALHES)   # bancos antigos não têm
        for r in conn.execute(f"SELECT asin, titulo, formato, ultimo_visto, {detalhes} FROM catalogo"):
            l = livros.setdefault(r["asin"], {"t": None, "f": None, "u": 0, "h": [], "v": False})
            l["t"] = l["t"] or r["titulo"]
            l["f"] = l["f"] or r["formato"]
            for c in DETALHES:
                l[c] = l.get(c) or r[c]
            u = dia_brasil(r["ultimo_visto"]).toordinal()
            l["u"] = max(l["u"], u)
            l["v"] = l["v"] or corte is None or u >= corte     # visível na busca
        for r in conn.execute("SELECT asin, desde, ate, preco_centavos, preco_capa_centavos FROM historico"):
            if r["asin"] in livros:
                livros[r["asin"]]["h"].append([dia_brasil(r["desde"]).toordinal(), dia_brasil(r["ate"]).toordinal(),
                                               r["preco_centavos"], r["preco_capa_centavos"]])
        return aviso(conn)
    finally:
        conn.close()


def construir(bancos: list[Path], saida: Path, eventos: Path | None = None) -> dict:
    livros: dict[str, dict] = {}
    avisos = [a for a in (ler_banco(Path(b), livros) for b in bancos) if a]
    livros = {a: l for a, l in livros.items() if l["h"]}          # sem preço registrado não há o que mostrar
    for l in livros.values():
        l["h"] = juntar_trechos(l["h"])

    if saida.exists():
        shutil.rmtree(saida)
    (saida / "dados" / "h").mkdir(parents=True)
    for nome in ARQUIVOS_WEB:
        shutil.copy(WEB / nome, saida / nome)

    indice = []
    fragmentos: dict[str, dict] = {}
    for asin in sorted(livros):
        l = livros[asin]
        ultimo = l["h"][-1]
        capa = next((t[3] for t in reversed(l["h"]) if t[3]), None)
        if l["v"]:
            indice.append([asin, l["t"] or asin, l["f"], ultimo[2], capa, l["u"], *(l.get(c) for c in DETALHES)])
        fragmentos.setdefault(fragmento(asin), {})[asin] = {"t": l["t"], "f": l["f"], "h": l["h"],
                                                           **{c: l[c] for c in DETALHES if l.get(c)}}
    (saida / "dados" / "indice.json").write_text(_json({"v": 1, "itens": indice}), encoding="utf-8")
    for chave, conteudo in fragmentos.items():
        (saida / "dados" / "h" / f"{chave}.json").write_text(_json(conteudo), encoding="utf-8")

    meta = {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "itens": len(indice),
            "ultima_coleta": max((i[5] for i in indice), default=None), "aviso": " / ".join(dict.fromkeys(avisos))}
    (saida / "dados" / "meta.json").write_text(_json(meta), encoding="utf-8")
    (saida / "dados" / "eventos.json").write_text(_json(ler_eventos(eventos) if eventos else []), encoding="utf-8")
    return meta
