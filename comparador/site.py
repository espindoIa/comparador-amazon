"""Gera o site estático (busca por título, histórico de cada livro e lista de desejos).

Entrada: um ou mais bancos do catálogo. Saída: uma pasta com HTML, CSS, JavaScript e dados em JSON,
que pode ser servida por qualquer hospedagem estática (GitHub Pages). Não há servidor: a busca e a
lista de desejos rodam no navegador (a lista fica guardada só no navegador de quem a cria).

Dados gerados em `dados/`:
- `indice.json`  para a busca, os livros visíveis agrupados por obra (os formatos do mesmo livro juntos;
                 some o que não foi visto depois do filtro "vendido pela Amazon" e o que não é livro, mas
                 o histórico continua nos `h/`):
                   {"v": 2, "hoje": dia da última coleta, "fmt": [nomes dos formatos],
                    "o": [[título, autor, código da capa, ano, idioma,
                           [[asin, nº do formato, preço, preço de capa, dias desde a última vez visto,
                             preço mais comum (0 = poucos dados)], ...]], ...],
                    "baixa": [[asin, preço anterior, dia da mudança], ...]}   (baixaram de preço agora há pouco)
                 textos vazios ("") e números 0 = não informado
- `h/XX.json`    histórico de ~1/256 dos livros (XX = hash de 1 byte do ASIN, em hexadecimal), carregado sob
                 demanda, com autor, imagem, publicado, idioma e obra quando conhecidos
- `meta.json`    data da última coleta, totais e aviso (bancos simulados)
- `eventos.json` promoções (de eventos.csv)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .db import dia_brasil
from .relatorio import BURACO, WEB, aviso, ler_eventos

DETALHES = ("autor", "imagem", "publicado", "idioma", "obra")
ARQUIVOS_WEB = ("index.html", "livro.html", "app.js", "lista.js", "livro.js", "estilo.css", "icone.svg", "manifest.json")
JANELA = 90            # dias do "preço mais comum" (mesma janela de livro.js)
MIN_DIAS_COMUM = 14    # com menos dias de coleta na janela, o preço mais comum não é mostrado
QUEDA_MIN = 0.05       # "baixaram de preço": queda de pelo menos 5%...
QUEDA_DIAS = 2         # ...que começou na última coleta ou na anterior
MAX_BAIXA = 120

# formatos que aparecem nas listas de livros da Amazon mas não são livros: ficam fora da busca
NAO_LIVRO = frozenset({
    "Brinquedo", "Material de escritório", "Acessório", "Agenda ou Calendário", "Diário", "Mapa", "Cartas",
    "CD de áudio", "CD multimídia", "Produtos de escritório", "Porta-cartões", "Pôster", "Agenda de contatos",
    "Diversos", "Cozinha", "Ferramentas e reformas", "Gráfico de parede", "Slide", "Papelaria", "DVD-ROM",
    "Marcador de página", "Blu-ray", "Áudio, Cassete", "Caixa"})


def familia(formato: str | None) -> str | None:
    """'k' (Kindle), 'a' (audiolivro), 'f' (livro físico) ou None (não é livro)."""
    if not formato:
        return "f"
    if formato in NAO_LIVRO:
        return None
    if "Kindle" in formato:
        return "k"
    if formato.lower().replace("á", "a").startswith("audiolivro") or formato == "Audible":
        return "a"
    return "f"


def por_dia(trechos: list[list]) -> dict[int, int]:
    """Preço de cada dia com coleta (o mesmo que porDia em livro.js)."""
    m: dict[int, int] = {}
    for t in trechos:
        for d in range(t[0], t[1] + 1):
            m[d] = t[2]
    return m


def mais_comum(trechos: list[list], ate: int) -> int | None:
    """Mediana dos preços dos últimos JANELA dias até `ate`, truncada como em livro.js; None com poucos dias."""
    w = [p for d, p in por_dia(trechos).items() if ate - JANELA < d <= ate]
    return int(statistics.median(w)) if len(w) >= MIN_DIAS_COMUM else None


def queda(trechos: list[list], hoje: int) -> tuple[int, int] | None:
    """(preço anterior, dia da mudança) se o preço atual é uma queda recente; senão None."""
    if len(trechos) < 2:
        return None
    ant, atual = trechos[-2], trechos[-1]
    if atual[1] < hoje or atual[0] < hoje - QUEDA_DIAS + 1 or atual[0] - ant[1] > BURACO:
        return None
    if ant[2] - atual[2] < max(100, ant[2] * QUEDA_MIN):
        return None
    return ant[2], atual[0]


def agrupar(livros: dict[str, dict]) -> list[list[str]]:
    """Junta em obras os ASINs ligados pela coluna `obra` (os formatos do mesmo card da Amazon)."""
    pai: dict[str, str] = {}

    def raiz(x: str) -> str:
        while pai.setdefault(x, x) != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for asin, l in livros.items():
        a = raiz(asin)
        if l.get("obra"):
            b = raiz(l["obra"])
            if a != b:
                pai[max(a, b)] = min(a, b)
    grupos: dict[str, list[str]] = {}
    for asin in livros:
        grupos.setdefault(raiz(asin), []).append(asin)
    return list(grupos.values())


def _versao(saida: Path) -> str:
    """Hash dos arquivos do app, para o navegador não usar JS/CSS velhos depois de uma publicação."""
    h = hashlib.sha1()
    for nome in ARQUIVOS_WEB:
        h.update((saida / nome).read_bytes())
    return h.hexdigest()[:10]


def _versionar(saida: Path) -> None:
    v = _versao(saida)
    for nome in ("index.html", "livro.html"):
        html = (saida / nome).read_text(encoding="utf-8")
        html = re.sub(r'(src|href)="(\w+\.(?:js|css|svg|json))"', lambda m: f'{m[1]}="{m[2]}?v={v}"', html)
        (saida / nome).write_text(html, encoding="utf-8")


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


def _obra(asins: list[str], livros: dict[str, dict], fmt: dict[str, int], hoje: int) -> list:
    """Linha do índice para uma obra: dados do livro (da edição principal, quando há) e cada formato."""
    ordem = {"f": 0, "k": 1, "a": 2}
    eds = sorted(asins, key=lambda a: (ordem[familia(livros[a]["f"])], livros[a]["h"][-1][2], a))
    principal = next((a for a in eds if livros[a].get("obra") == a), eds[0])
    fontes = [livros[principal]] + [livros[a] for a in eds if a != principal]
    det = {c: next((l[c] for l in fontes if l.get(c)), "") for c in DETALHES}
    linhas = []
    for a in eds:
        l = livros[a]
        capa = next((t[3] for t in reversed(l["h"]) if t[3]), None)
        f = l["f"] or "Livro"
        linhas.append([a, fmt.setdefault(f, len(fmt)), l["h"][-1][2], capa or 0, max(0, hoje - l["u"]),
                       mais_comum(l["h"], l["h"][-1][1]) or 0])
    titulo = livros[principal]["t"] or principal
    return [titulo, det["autor"], det["imagem"], int(det["publicado"][:4]) if det["publicado"] else 0, det["idioma"], linhas]


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
    _versionar(saida)

    fragmentos: dict[str, dict] = {}
    for asin in sorted(livros):
        l = livros[asin]
        fragmentos.setdefault(fragmento(asin), {})[asin] = {"t": l["t"], "f": l["f"], "h": l["h"],
                                                           **{c: l[c] for c in DETALHES if l.get(c)}}
    for chave, conteudo in fragmentos.items():
        (saida / "dados" / "h" / f"{chave}.json").write_text(_json(conteudo), encoding="utf-8")

    # na busca: só o que é livro e continua à venda pela Amazon
    visiveis = {a: l for a, l in livros.items() if l["v"] and familia(l["f"])}
    hoje = max((l["u"] for l in visiveis.values()), default=None)
    fmt: dict[str, int] = {}
    obras = sorted((_obra(g, visiveis, fmt, hoje) for g in agrupar(visiveis)), key=lambda o: (o[0].casefold(), o[5][0][0]))
    baixa = []
    for a, l in visiveis.items():
        q = queda(l["h"], hoje)
        if q:
            baixa.append([a, q[0], q[1]])
    baixa.sort(key=lambda b: (livros[b[0]]["h"][-1][2] / b[1], b[0]))
    indice = {"v": 2, "hoje": hoje, "fmt": list(fmt), "o": obras, "baixa": baixa[:MAX_BAIXA]}
    (saida / "dados" / "indice.json").write_text(_json(indice), encoding="utf-8")

    meta = {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "itens": len(visiveis),
            "obras": len(obras), "ultima_coleta": hoje, "aviso": " / ".join(dict.fromkeys(avisos))}
    (saida / "dados" / "meta.json").write_text(_json(meta), encoding="utf-8")
    (saida / "dados" / "eventos.json").write_text(_json(ler_eventos(eventos) if eventos else []), encoding="utf-8")
    return meta
