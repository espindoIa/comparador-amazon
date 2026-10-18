"""Gera o site estático (busca por título, histórico de cada livro e lista de desejos).

Entrada: um ou mais bancos do catálogo. Saída: uma pasta com HTML, CSS, JavaScript e dados em JSON,
que pode ser servida por qualquer hospedagem estática (GitHub Pages). Não há servidor: a busca e a
lista de desejos rodam no navegador (a lista fica guardada só no navegador de quem a cria).

Dados gerados em `dados/` (textos vazios "" e números 0 = não informado; dias = número ordinal da data):
- `indice-N.json` a busca, em partes: os livros visíveis agrupados por obra (os formatos do mesmo livro
                 juntos). Ficam de fora o que não é livro, o que não foi visto depois do filtro "vendido
                 pela Amazon" e o que não aparece há SUMIR_DIAS dias (o histórico continua nos `h/`).
                 As obras vão das mais avaliadas para as menos: a parte 0 tem as PARTE_INICIAL primeiras e
                 chega rápido; as outras vêm depois, com PARTE obras cada.
                   {"v": 3, "o": [[título, autor, código da capa, ano, idioma (posição em "idi", +1),
                                   [gêneros (posição em "gen")], nota (décimos), nº de avaliações,
                                   [[asin, nº do formato, preço, preço de capa, dias desde a última vez visto,
                                     preço mais comum, menor preço registrado], ...]], ...]}
                 a parte 0 também traz "hoje" (dia da última coleta), "partes" (quantas são) e as tabelas
                 "fmt" (formatos), "gen" ([nó, nome] dos gêneros) e "idi" (idiomas).
- `destaques.json` o que a página inicial mostra, sem precisar do índice: as tabelas acima, as obras
                 citadas ("o", mesmo formato), "baixa" ([asin, preço anterior, dia da mudança]: baixaram de
                 preço agora há pouco), "menor" (asins no menor preço registrado) e "ngen" (obras por gênero).
- `h/XX.json`    histórico de ~1/256 dos livros (XX = hash de 1 byte do ASIN, em hexadecimal), carregado sob
                 demanda, com autor, imagem, publicado, idioma, nota, avaliações e gêneros quando conhecidos,
                 os outros formatos da obra ("eds": [[asin, formato, preço]]), outras edições do mesmo
                 título e autor ("outras": [[asin, título, capa, formato, preço]]) e as obras mais avaliadas
                 do mesmo autor principal ("autor1" e "mesmo_autor", no formato de "outras"; quem é o mesmo autor
                 vem de parecidos.chaves_do_autor, e editoras e "Vários autores" não têm).
- `p/XXX.json`   livros parecidos (ver parecidos.py) de ~1/1024 dos livros (XXX = `fragmento_p` do ASIN, mesma conta em
                 app.js), carregados sob demanda pela página do livro e pelo início. Os livros da busca e os que saíram
                 dela têm lista; os parecidos são sempre livros da busca. Cartões e listas repetidos aparecem uma vez:
                   {"c": [[asin, título, capa, formato, preço, autor, grupo], ...],  (edição: a primeira da obra, como em "outras")
                    "l": [[posição em "c", ...], ...],                           (até MAX_PARECIDOS, do mais parecido ao menos)
                    "p": {asin: [posição em "l", título curto, ASIN da obra, grupo, [subgêneros]]}}
                 O título curto, a obra ("" quando é o próprio ASIN) e o grupo servem ao início: o motivo "como <título>" e
                 para não repetir um livro. O grupo é um número, o mesmo em todos os arquivos, para as edições do mesmo livro
                 (mesmo autor e mesmo começo de título, ver parecidos.chave_titulo): o início junta listas de livros diferentes
                 e mostra cada grupo uma vez, fora os grupos dos livros de partida. O 5º item, só quando há snapshot de
                 subgêneros (`--subgeneros`) e o livro está em algum, traz até MAX_SUBGENEROS nomes deles (os que mais itens da
                 lista dividem com ele),
                 que a página do livro mostra ao lado do título da estante.
- `meta.json`    data da última coleta, totais e aviso (bancos simulados); com o snapshot dos subgêneros (`--subgeneros`, ver
                 subgeneros.py), também "subgeneros": {gerado_em, folhas, k}
- `eventos.json` promoções (de eventos.csv)
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import re
import shutil
import statistics
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import parecidos
from .db import abrir_leitura, dia_brasil
from .relatorio import BURACO, WEB, aviso, ler_eventos
from .subgeneros import ler_snapshot
from .varredura import GENEROS

DETALHES = ("autor", "imagem", "publicado", "idioma", "obra", "nota", "avaliacoes")
ARQUIVOS_WEB = ("referencia.css", "index.html", "livro.html", "404.html", "app.js", "busca.js", "lista.js", "recomenda.js", "livro.js", "estilo.css", "icone.svg",
                "icone-180.png", "icone-192.png", "icone-512.png", "icone-maskable-512.png", "manifest.json",
                "cormorant-600.woff2", "crimson-400.woff2", "crimson-400i.woff2", "crimson-600.woff2", "OFL.txt")
JANELA = 90            # dias do "preço mais comum" (mesma janela de livro.js)
MIN_DIAS_COMUM = 14    # com menos dias de coleta na janela, o preço mais comum não é mostrado
QUEDA_MIN = 0.05       # "baixaram de preço": queda de pelo menos 5%...
QUEDA_DIAS = 2         # ...que começou na última coleta ou na anterior
JANELA_QUEDA = 30      # dias para trás que a comparação de queda olha
MAX_BAIXA = 60         # por família (físico, Kindle, audiolivro): sem isso, as ofertas do dia do Kindle tomam tudo
MAX_MENOR = 60
SUMIR_DIAS = 14        # sem aparecer há tantos dias: sai da busca (continua na lista de quem salvou)
PARTE_INICIAL = 15_000  # obras na primeira parte do índice (as mais avaliadas): a busca começa com elas
PARTE = 40_000         # obras em cada uma das outras partes
MAX_TITULO = 140       # caracteres do título no índice (o título inteiro fica no histórico)
MAX_OUTRAS = 8
MAX_AUTOR = 8          # "mais deste autor" na página do livro
MAX_TITULO_MINI = 80   # título nas estantes da página do livro (o cartão mostra 2 linhas)
MAX_AUTOR_MINI = 40    # autor no cartão dos parecidos (uma linha)
MAX_TITULO_CURTO = 40  # título do livro de partida no motivo "como <título>" do início
MAX_PARECIDOS = 10
MAX_SUBGENEROS = 3     # subgêneros do livro de partida mostrados na página do livro (os que a lista dele mais divide com ele)
FRAG_P = 1024          # arquivos de parecidos (com 256, cada um passaria de 300 KB compactado)

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


def por_dia(trechos: list[list], desde: int | None = None) -> dict[int, int]:
    """Preço de cada dia com coleta (o mesmo que porDia em livro.js): o último lido no dia, se o preço mudou mais de
    uma vez nele. `desde`: só os dias a partir deste."""
    m: dict[int, int] = {}
    for t in trechos:
        for d in range(t[0] if desde is None else max(t[0], desde), t[1] + 1):
            m[d] = t[2]
    return m


def _trechos_do_dia(trechos: list[list], desde: int) -> list[list]:
    """Os trechos como o site os mostra: um preço por dia, com os dias seguidos de mesmo preço juntos."""
    dias = por_dia(trechos, desde)
    out: list[list] = []
    for d in sorted(dias):
        if out and out[-1][2] == dias[d] and d - out[-1][1] <= BURACO:
            out[-1][1] = d
        else:
            out.append([d, d, dias[d]])
    return out


def mais_comum(trechos: list[list], ate: int) -> int | None:
    """Mediana dos preços dos últimos JANELA dias até `ate`, truncada como em livro.js; None com poucos dias."""
    w = [p for d, p in por_dia(trechos).items() if ate - JANELA < d <= ate]
    return int(statistics.median(w)) if len(w) >= MIN_DIAS_COMUM else None


def queda(trechos: list[list], hoje: int) -> tuple[int, int] | None:
    """(preço anterior, dia da mudança) se o preço de hoje é uma queda recente em relação ao dia anterior; senão None.
    Compara preços por dia (o último lido em cada um): com várias leituras por dia, uma oscilação dentro do mesmo dia
    (R$ 40 → R$ 50 → R$ 40) não é queda."""
    trechos = _trechos_do_dia(trechos, hoje - JANELA_QUEDA)
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


def _versionar(saida: Path) -> str:
    v = _versao(saida)
    for nome in ("index.html", "livro.html", "404.html"):
        html = (saida / nome).read_text(encoding="utf-8")
        html = re.sub(r'(src|href)="([\w-]+\.(?:js|css|svg|json|png))"', lambda m: f'{m[1]}="{m[2]}?v={v}"', html)
        (saida / nome).write_text(html, encoding="utf-8")
    return v


def _previa(saida: Path, url: str, v: str) -> None:
    """Imagem de prévia dos links compartilhados (Open Graph): os apps de mensagem só aceitam endereço completo,
    e o endereço público só a publicação conhece (--url). O ?v= renova a prévia em cache quando o ícone muda."""
    if not re.match(r"https?://", url):
        raise ValueError(f"--url precisa começar com http:// ou https:// (veio {url!r})")
    url = url.rstrip("/")
    marca = '<meta property="og:locale" content="pt_BR">\n'
    html = (saida / "index.html").read_text(encoding="utf-8")
    if marca not in html:
        raise ValueError("index.html sem a meta og:locale, onde entra a prévia")
    # sem og:url: as telas do app são o mesmo index.html com ?livro=…/?lista=…, e um endereço canônico único
    # faria o link compartilhado de um livro ou de uma lista abrir na página inicial
    tags = (f'<meta property="og:image" content="{url}/icone-512.png?v={v}">\n'
            '<meta property="og:image:width" content="512">\n<meta property="og:image:height" content="512">\n'
            '<meta property="og:image:alt" content="Ícone do Preços de livros">\n')
    (saida / "index.html").write_text(html.replace(marca, marca + tags), encoding="utf-8")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def fragmento(asin: str) -> str:
    """Arquivo de histórico do livro. Mesma conta em app.js (`fragmento`): hash simples, 256 arquivos."""
    h = 0
    for c in asin:
        h = (h * 31 + ord(c)) % 256
    return f"{h:02x}"


def fragmento_p(asin: str) -> str:
    """Arquivo de parecidos do livro. Mesma conta em app.js (`fragmentoP`): a de `fragmento`, com FRAG_P arquivos."""
    h = 0
    for c in asin:
        h = (h * 31 + ord(c)) % FRAG_P
    return f"{h:03x}"


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


def nome_proprio(nome: str) -> str:
    """Autor escrito todo em maiúsculas ("ELIO D'ANNA") vira "Elio D'Anna"; os outros ficam como vieram."""
    if not nome or nome != nome.upper() or not any(c.isalpha() for c in nome):
        return nome
    palavras = nome.lower().split(" ")
    return " ".join(p if i and p in _MINUSCULAS else re.sub(r"(^|[-'’.])(\w)", lambda m: m[1] + m[2].upper(), p)
                    for i, p in enumerate(palavras))


_MINUSCULAS = frozenset({"de", "da", "do", "das", "dos", "e", "del", "la", "van", "von", "di", "du", "y"})
_EDICOES = {"english": "Inglês", "portuguese": "", "spanish": "Espanhol", "french": "Francês", "italian": "Italiano",
            "german": "Alemão", "japanese": "Japonês"}
_EDICAO_RE = re.compile(r"\s*[(\[](\w+) Edition[)\]]\s*$", re.I)


def limpar_titulo(titulo: str | None) -> tuple[str, str]:
    """("Título", idioma): "(English Edition)" e afins saem do título e viram idioma (o mesmo que limpar em livro.js)."""
    t = (titulo or "").strip()
    m = _EDICAO_RE.search(t)
    if m and m[1].lower() in _EDICOES:
        return t[:m.start()] or t, _EDICOES[m[1].lower()]
    return t, ""


def normalizar(texto: str) -> str:
    """Sem acentos e em minúsculas (para comparar títulos e autores)."""
    if texto and texto.isascii():
        return texto.lower()
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if not unicodedata.combining(c)).lower()


def titulo_curto(titulo: str) -> str:
    """O título sem o subtítulo, para caber numa linha ("Sapiens (Nova edição): Uma breve história…" → "Sapiens (Nova edição)")."""
    t = re.split(r"\s*[:–—―]\s|\s+-\s", titulo or "", maxsplit=1)[0].strip()
    return t[:MAX_TITULO_CURTO].rstrip()


def titulo_base(titulo: str) -> str:
    """Título sem subtítulo nem observações entre parênteses, para achar outras edições do mesmo livro.
    Subtítulo ou parênteses com número ficam ("Metro: Level 3", "(Volume 2)"): são outro volume."""
    t = re.sub(r"\s*[(\[][^)\]]*[)\]]", lambda m: m[0] if re.search(r"\d", m[0]) else "", normalizar(titulo))
    m = re.search(r"\s*[:–—]\s|\s+-\s", t)
    if m and not re.search(r"\d", t[m.end():]):
        t = t[:m.start()]
    return " ".join(t.split())


# Autores que não identificam ninguém: não servem para dizer que dois livros são o mesmo
AUTORES_GENERICOS = parecidos.AUTORES_GENERICOS


def ultima_leitura(caminho: Path) -> str | None:
    """Instante (ISO) da leitura mais recente do banco. O site mostra a mais antiga entre os bancos: todos os grupos
    de gêneros foram lidos pelo menos até ali."""
    conn = abrir_leitura(caminho, "catálogo")
    try:
        return conn.execute("SELECT MAX(ultimo_visto) FROM catalogo").fetchone()[0]
    finally:
        conn.close()


def ler_banco(caminho: Path, livros: dict[str, dict]) -> str:
    """Soma os livros de um banco em `livros`. Devolve o aviso do banco (vazio se não houver)."""
    conn = abrir_leitura(caminho, "catálogo")
    conn.row_factory = sqlite3.Row
    try:
        corte = corte_amazon(conn)
        colunas = {c[1] for c in conn.execute("PRAGMA table_info(catalogo)")}
        detalhes = ", ".join(c if c in colunas else f"NULL AS {c}" for c in DETALHES)   # bancos antigos não têm
        for r in conn.execute(f"SELECT asin, titulo, formato, no, ultimo_visto, {detalhes} FROM catalogo"):
            l = livros.setdefault(r["asin"], {"t": None, "f": None, "u": 0, "h": [], "v": False, "g": set()})
            u = dia_brasil(r["ultimo_visto"]).toordinal()
            # O mesmo livro pode estar em mais de um banco (uma sequência de coleta passou a lê-lo, ou ele está em gêneros de
            # duas): a linha vista por último manda, e a mais velha só preenche o que falta. Assim, o banco que deixou de
            # ler o livro não sobrepõe a nota, a capa ou o título que o outro atualiza todo dia.
            valor = (lambda novo, antigo: novo or antigo) if u > l["u"] else (lambda novo, antigo: antigo or novo)  # noqa: E731
            l["t"] = valor(r["titulo"], l["t"])
            l["f"] = valor(r["formato"], l["f"])
            for c in DETALHES:
                l[c] = valor(r[c], l.get(c))
            l["u"] = max(l["u"], u)
            l["v"] = l["v"] or corte is None or u >= corte     # visível na busca
            if r["no"] in GENEROS:
                l["g"].add(r["no"])
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'generos'").fetchone():
            for r in conn.execute("SELECT asin, no FROM generos"):
                if r["asin"] in livros and r["no"] in GENEROS:
                    livros[r["asin"]]["g"].add(r["no"])
        for r in conn.execute("SELECT asin, desde, ate, preco_centavos, preco_capa_centavos FROM historico"):
            if r["asin"] in livros:
                livros[r["asin"]]["h"].append([dia_brasil(r["desde"]).toordinal(), dia_brasil(r["ate"]).toordinal(),
                                               r["preco_centavos"], r["preco_capa_centavos"]])
        return aviso(conn)
    finally:
        conn.close()


def menor_registrado(trechos: list[list]) -> int | None:
    """Menor preço já registrado (o do fim de cada dia, como no gráfico), se o livro tem pelo menos MIN_DIAS_COMUM dias
    de coleta; senão None."""
    dias = por_dia(trechos)
    if len(dias) < MIN_DIAS_COMUM:
        return None
    return min(dias.values())


class Tabela:
    """Nomes repetidos (formatos, idiomas, gêneros) viram números no índice."""

    def __init__(self):
        self.pos: dict = {}

    def __call__(self, nome) -> int:
        return self.pos.setdefault(nome, len(self.pos))

    def lista(self) -> list:
        return list(self.pos)


def _preparar(livros: dict[str, dict]) -> None:
    """Título limpo, idioma, autor com maiúsculas normais e popularidade de cada livro."""
    for l in livros.values():
        l["t"], idioma = limpar_titulo(l["t"])
        l["idioma"] = l.get("idioma") or idioma
        l["autor"] = nome_proprio(l.get("autor") or "")


def _obra(asins: list[str], livros: dict[str, dict], t: dict[str, Tabela], hoje: int) -> dict:
    """Uma obra: dados do livro (da edição principal, quando há) e cada formato, do físico mais barato ao Kindle."""
    ordem = {"f": 0, "k": 1, "a": 2}
    eds = sorted(asins, key=lambda a: (ordem[familia(livros[a]["f"])], livros[a]["h"][-1][2], a))
    principal = next((a for a in eds if livros[a].get("obra") == a), eds[0])
    fontes = [livros[principal]] + [livros[a] for a in eds if a != principal]
    det = {c: next((l[c] for l in fontes if l.get(c)), None) for c in DETALHES}
    generos = sorted(set().union(*(livros[a]["g"] for a in eds)), key=lambda g: list(GENEROS).index(g))
    linhas = []
    for a in eds:
        l = livros[a]
        capa = next((x[3] for x in reversed(l["h"]) if x[3]), None)
        linhas.append([a, t["fmt"](l["f"] or "Livro"), l["h"][-1][2], capa or 0, max(0, hoje - l["u"]),
                       mais_comum(l["h"], l["h"][-1][1]) or 0, menor_registrado(l["h"]) or 0])
    titulo = livros[principal]["t"] or principal
    linha = [titulo[:MAX_TITULO].rstrip(), det["autor"] or "", det["imagem"] or "",
             int(det["publicado"][:4]) if det["publicado"] else 0,
             t["idi"](det["idioma"]) + 1 if det["idioma"] else 0, [t["gen"](g) for g in generos],
             det["nota"] or 0, max((livros[a].get("avaliacoes") or 0 for a in eds), default=0), linhas]
    return {"linha": linha, "eds": eds, "titulo": titulo, "autor": det["autor"] or "", "pop": linha[7], "idioma": det["idioma"] or "",
            "base": titulo_base(titulo)}


def _mini(obras: list[dict], livros: dict[str, dict], j: int) -> list:
    """Cartão de uma obra nas estantes da página do livro: [asin, título, capa, formato, preço] da primeira edição."""
    o = obras[j]
    return [o["eds"][0], o["titulo"][:MAX_TITULO_MINI].rstrip(), o["linha"][2], livros[o["eds"][0]]["f"] or "Livro", o["linha"][8][0][2]]


def _genes_de_subgenero(sub: dict | None, obra_de: dict[str, int], n_obras: int, n_base: int):
    """Os subgêneros do snapshot como genes extras, a partir de `n_base`: ({posição da obra: {gene: quão no alto da lista}},
    {asin: {gene: o mesmo}}, {gene: peso}, {gene: nome}). "Quão no alto" é a posição do ASIN na lista da folha (a ordem de
    mais vendidos) dividida pelo total de resultados dela: 0 é o primeiro, e serve para escolher que subgêneros mostrar. O peso é o da raridade do nó entre as obras, log((N+1)/total): o total de resultados da Amazon
    ("mais de N" é um piso) e não a contagem das rotuladas, que só vê as primeiras páginas. Folhas que não casam com
    nenhuma obra da busca não viram gene."""
    por_obra: dict[int, dict[int, float]] = {}
    por_asin: dict[str, dict[int, float]] = {}
    pesos: dict[int, float] = {}
    nomes: dict[int, str] = {}
    for f in (sub or {}).get("folhas", []):
        membros = {obra_de[a] for a in f["asins"] if a in obra_de}
        if not membros:
            continue
        gene = n_base + len(pesos)
        total = max(f["total"] or 0, len(membros), len(f["asins"]))
        pesos[gene] = math.log((n_obras + 1) / max(f["total"] or 0, len(membros)))
        nomes[gene] = f["nome"]
        for pos, a in enumerate(f["asins"]):
            por_asin.setdefault(a, {})[gene] = pos / total
            if a in obra_de:
                por_obra.setdefault(obra_de[a], {}).setdefault(gene, pos / total)       # a primeira vez que a obra aparece
    return por_obra, por_asin, pesos, nomes


def _parecidos(obras: list[dict], livros: dict[str, dict], obra_de: dict[str, int], outras: dict[int, list[int]],
               autor: dict[int, list[int]], t: dict[str, Tabela], sub: dict | None = None) -> dict[str, dict]:
    """Os arquivos `p/` (formato no começo deste arquivo): as obras da busca e os livros que saíram dela, com gênero.
    `sub`: o snapshot dos subgêneros (subgeneros.ler_snapshot), que entram na conta como genes extras."""
    bases = [o["base"] for o in obras]
    n_base = len(t["gen"].lista())
    por_obra, por_asin, pesos, nomes = _genes_de_subgenero(sub, obra_de, len(obras), n_base)

    def subs(altura: dict[int, float], lista: list[int]) -> list[str]:
        """Até MAX_SUBGENEROS dos subgêneros do livro de partida: os que mais itens da lista dele dividem com ele (é por eles
        que a lista é o que é), e, no empate, aquele em que ele está mais alto na lista do subgênero e, depois, o mais raro."""
        com = collections.Counter(g for j in lista for g in por_obra.get(j, ()) if g in altura)
        return [nomes[g] for g in sorted(altura, key=lambda g: (-com[g], altura[g], -pesos[g], g))[:MAX_SUBGENEROS]]
    genes = lambda i, base: tuple(sorted({*base, *por_obra.get(i, ())}))        # noqa: E731
    pobras = [parecidos.Obra(i, o["titulo"], o["autor"], genes(i, o["linha"][5]), o["idioma"], o["pop"], bases[i]) for i, o in enumerate(obras)]
    sementes = [parecidos.Semente(genes(i, o["linha"][5]), o["idioma"], o["autor"], i, frozenset(outras.get(i, []) + autor.get(i, [])),
                                  o["titulo"], bases[i]) for i, o in enumerate(obras)]
    fora = sorted(a for a, l in livros.items() if a not in obra_de and l["g"])
    # fora da busca, a obra (coluna `obra`) pode ter outra edição na busca: ela não é parecida, é o mesmo livro
    sementes += [parecidos.Semente(tuple(sorted({*(t["gen"](g) for g in livros[a]["g"]), *por_asin.get(a, ())})), livros[a].get("idioma") or "",
                                   livros[a].get("autor") or "", obra_de.get(livros[a].get("obra") or a), frozenset(), livros[a]["t"] or "",
                                   titulo_base(livros[a]["t"] or ""))
                 for a in fora]
    pos = {no: t["gen"](no) for no in GENEROS}
    listas = parecidos.calcular(pobras, n_base + len(pesos), sementes, MAX_PARECIDOS,
                                ficcao=frozenset(pos[no] for no in parecidos.GENEROS_FICCAO) | frozenset(pesos),
                                balde=frozenset({pos[parecidos.LIVROS_INTERNACIONAIS]}),
                                n_base=n_base if pesos else None, idf_extra=pesos or None)

    arquivos: dict[str, dict] = {}
    cartoes: dict[int, list] = {}                     # o cartão de cada obra, montado uma vez para todos os arquivos
    grupos: dict[tuple, int] = {}

    def grupo(autor: str, titulo: str, base: str) -> int:
        k = (parecidos.chave_autor(autor), parecidos.chave_titulo(base or titulo))
        return grupos.setdefault(k, len(grupos))

    def gravar(asin: str, lista: list[int], titulo: str, obra: str, g: int, sub_nomes: list[str] = ()):     # titulo: já curto; g: o grupo da semente
        arq = arquivos.get(fragmento_p(asin))
        if arq is None:
            arq = arquivos[fragmento_p(asin)] = {"c": [], "l": [], "p": {}, "_c": {}, "_l": {}}
        pos_c, c = arq["_c"], arq["c"]
        idx = []
        for j in lista:
            i = pos_c.get(j)
            if i is None:
                if j not in cartoes:
                    cartoes[j] = _mini(obras, livros, j) + [obras[j]["autor"][:MAX_AUTOR_MINI].rstrip(),
                                                            grupo(obras[j]["autor"], obras[j]["titulo"], bases[j])]
                i = pos_c[j] = len(c)
                c.append(cartoes[j])
            idx.append(i)
        chave = tuple(idx)
        li = arq["_l"].get(chave)
        if li is None:
            li = arq["_l"][chave] = len(arq["l"])
            arq["l"].append(idx)
        arq["p"][asin] = [li, titulo, obra if obra != asin else "", g] + ([list(sub_nomes)] if sub_nomes else [])

    for i, o in enumerate(obras):
        if listas[i]:
            curto, g = titulo_curto(o["titulo"]), grupo(o["autor"], o["titulo"], bases[i])
            for a in o["eds"]:
                gravar(a, listas[i], curto, o["eds"][0], g, subs(por_obra.get(i, {}), listas[i]))
    for a, lista in zip(fora, listas[len(obras):]):
        if lista:
            t_a = livros[a]["t"] or a
            gravar(a, lista, titulo_curto(t_a), a, grupo(livros[a].get("autor") or "", t_a, titulo_base(t_a)), subs(por_asin.get(a, {}), lista))
    return {k: {"c": v["c"], "l": v["l"], "p": v["p"]} for k, v in arquivos.items()}


def autor_principal(autor: str) -> str:
    """O primeiro autor, como veio ("Machado de Assis, Fulano e outros." → "Machado de Assis")."""
    return re.split(r",|;| e | & ", autor or "", maxsplit=1)[0].strip(" .")


def _mesmo_autor(obras: list[dict], outras: dict[int, list[int]]) -> dict[int, list[int]]:
    """Para cada obra, as mais avaliadas do mesmo autor principal (sem ela, sem as outras edições dela e sem outros livros
    com o mesmo título-base). Quem é o mesmo autor: `parecidos.chaves_do_autor` (editoras e "Vários autores" ficam sem)."""
    chaves = parecidos.chaves_do_autor([o["autor"] for o in obras], [o["base"] for o in obras])
    grupos: dict[str, list[int]] = {}
    for i, chave in enumerate(chaves):                # obras já vêm das mais avaliadas para as menos
        if chave:
            grupos.setdefault(chave, []).append(i)
    out: dict[int, list[int]] = {}
    for membros in grupos.values():
        if len(membros) < 2:
            continue
        for i in membros:
            fora, base = {i, *outras.get(i, [])}, obras[i]["base"]
            lista = []
            for j in membros:
                if j in fora or (len(base) >= 4 and obras[j]["base"] == base):
                    continue
                lista.append(j)
                if len(lista) == MAX_AUTOR:
                    break
            out[i] = lista
    return out


def _outras(obras: list[dict]) -> dict[int, list[int]]:
    """Para cada obra, outras com o mesmo título-base e o mesmo autor (outras edições do mesmo livro)."""
    grupos: dict[tuple, list[int]] = {}
    for i, o in enumerate(obras):
        base, autor = o["base"], normalizar(o["autor"]).strip(" .")
        if len(base) >= 4 and autor not in AUTORES_GENERICOS:
            grupos.setdefault((base, autor), []).append(i)
    out: dict[int, list[int]] = {}
    for membros in grupos.values():
        if len(membros) > 1:
            membros.sort(key=lambda i: -obras[i]["pop"])
            for i in membros:
                out[i] = [j for j in membros if j != i][:MAX_OUTRAS]
    return out


def construir(bancos: list[Path], saida: Path, eventos: Path | None = None, url: str | None = None,
              subgeneros: Path | None = None) -> dict:
    livros: dict[str, dict] = {}
    avisos = [a for a in (ler_banco(Path(b), livros) for b in bancos) if a]
    livros = {a: l for a, l in livros.items() if l["h"]}          # sem preço registrado não há o que mostrar
    for l in livros.values():
        l["h"] = juntar_trechos(l["h"])
    _preparar(livros)

    if saida.exists():
        shutil.rmtree(saida)
    (saida / "dados" / "h").mkdir(parents=True)
    for nome in ARQUIVOS_WEB:
        shutil.copy(WEB / nome, saida / nome)
    v = _versionar(saida)
    if url:
        _previa(saida, url, v)

    # na busca: só o que é livro, continua à venda pela Amazon e apareceu nos últimos SUMIR_DIAS dias
    hoje = max((l["u"] for l in livros.values() if l["v"]), default=None)
    visiveis = {a: l for a, l in livros.items() if l["v"] and familia(l["f"]) and l["u"] > (hoje or 0) - SUMIR_DIAS}
    t = {"fmt": Tabela(), "idi": Tabela(), "gen": Tabela()}
    for g in GENEROS:                                          # gêneros sempre na mesma ordem
        t["gen"](g)
    obras = sorted((_obra(g, visiveis, t, hoje) for g in agrupar(visiveis)),
                   key=lambda o: (-o["pop"], o["titulo"].casefold(), o["eds"][0]))
    outras = _outras(obras)
    autor = _mesmo_autor(obras, outras)
    obra_de = {a: i for i, o in enumerate(obras) for a in o["eds"]}

    # histórico de cada livro, com os outros formatos da obra e outras edições
    fragmentos: dict[str, dict] = {}
    nomes_gen = dict(GENEROS)
    for asin in sorted(livros):
        l = livros[asin]
        h = {"t": l["t"], "f": l["f"], "h": l["h"],
             **{c: l[c] for c in DETALHES if l.get(c)}}
        if l["g"]:
            h["gen"] = [[g, nomes_gen[g]] for g in GENEROS if g in l["g"]]
        i = obra_de.get(asin)
        if i is not None:
            o = obras[i]
            if len(o["eds"]) > 1:
                h["eds"] = [[a, livros[a]["f"] or "Livro", livros[a]["h"][-1][2]] for a in o["eds"]]
            if i in outras:
                h["outras"] = [_mini(obras, livros, j) for j in outras[i]]
            if autor.get(i):
                h["mesmo_autor"] = [_mini(obras, livros, j) for j in autor[i]]
                h["autor1"] = autor_principal(o["autor"])
        fragmentos.setdefault(fragmento(asin), {})[asin] = h
    for chave, conteudo in fragmentos.items():
        (saida / "dados" / "h" / f"{chave}.json").write_text(_json(conteudo), encoding="utf-8")

    # livros parecidos de cada livro (com os subgêneros, se houver um snapshot bom: sem ele o site sai como sempre)
    sub = None
    if subgeneros:
        try:
            sub = ler_snapshot(subgeneros)
        except ValueError as e:
            print(f"aviso: site sem subgêneros ({e})", file=sys.stderr)
    inicio_p = time.monotonic()
    (saida / "dados" / "p").mkdir()
    for chave, conteudo in _parecidos(obras, livros, obra_de, outras, autor, t, sub).items():
        (saida / "dados" / "p" / f"{chave}.json").write_text(_json(conteudo), encoding="utf-8")
    tempo_p = time.monotonic() - inicio_p

    # índice da busca, em partes
    tabelas = {"fmt": t["fmt"].lista(), "gen": [[g, nomes_gen[g]] for g in t["gen"].lista()], "idi": t["idi"].lista()}
    cortes = [0, PARTE_INICIAL] + list(range(PARTE_INICIAL + PARTE, len(obras), PARTE))
    cortes = [c for c in cortes if c < len(obras)] or [0]
    for n, inicio in enumerate(cortes):
        fim = cortes[n + 1] if n + 1 < len(cortes) else len(obras)
        parte = {"v": 3, "o": [o["linha"] for o in obras[inicio:fim]]}
        if n == 0:
            parte = {"v": 3, "hoje": hoje, "partes": len(cortes), **tabelas, "o": parte["o"]}
        (saida / "dados" / f"indice-{n}.json").write_text(_json(parte), encoding="utf-8")

    # destaques da página inicial: baixaram de preço (até MAX_BAIXA por família) e no menor preço registrado
    baixa: dict[str, list] = {}
    for a, l in visiveis.items():
        q = queda(l["h"], hoje)
        if q:
            baixa.setdefault(familia(l["f"]), []).append([a, q[0], q[1]])
    baixa_lista = []
    for fam in ("f", "k", "a"):
        b = sorted(baixa.get(fam, []), key=lambda b: (livros[b[0]]["h"][-1][2] / b[1], b[0]))
        baixa_lista += b[:MAX_BAIXA]
    menor = []
    for o in obras:                                            # já vêm das mais avaliadas para as menos
        for e in o["linha"][8]:
            if e[4] == 0 and e[6] and e[2] <= e[6] and e[5] and e[2] < e[5]:
                menor.append(e[0])
                break
        if len(menor) >= MAX_MENOR:
            break
    citadas = sorted({obra_de[a] for a in [b[0] for b in baixa_lista] + menor})
    ngen = [0] * len(tabelas["gen"])
    for o in obras:
        for g in o["linha"][5]:
            ngen[g] += 1
    destaques = {"v": 3, "hoje": hoje, **tabelas, "o": [obras[i]["linha"] for i in citadas],
                 "baixa": baixa_lista, "menor": menor, "ngen": ngen}
    (saida / "dados" / "destaques.json").write_text(_json(destaques), encoding="utf-8")

    meta = {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "itens": sum(len(o["eds"]) for o in obras), "obras": len(obras), "ultima_coleta": hoje,
            "lido_ate": min((u for u in (ultima_leitura(Path(b)) for b in bancos) if u), default=None),
            "aviso": " / ".join(dict.fromkeys(avisos))}
    if sub:
        meta["subgeneros"] = {"gerado_em": sub.get("gerado_em"), "folhas": len(sub["folhas"]), "k": sub.get("k")}
    (saida / "dados" / "meta.json").write_text(_json(meta), encoding="utf-8")
    (saida / "dados" / "eventos.json").write_text(_json(ler_eventos(eventos) if eventos else []), encoding="utf-8")
    return {**meta, "tempo_parecidos": round(tempo_p, 1)}
