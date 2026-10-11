"""Gráfico de preço de um livro (HTML com SVG embutido) e veredito de promoção."""

from __future__ import annotations

import csv
import html
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .db import dia_brasil

JANELA_BASE = 60  # dias antes do evento usados como "preço normal"
JANELA_PICO = 21  # dias antes do evento em que um aumento artificial é procurado
LIMIAR_DESCONTO = 0.05  # abaixo disso a diferença é oscilação normal, não promoção
LIMIAR_INFLADO = 0.10   # alta mínima sobre o normal para suspeitar de preço inflado


@dataclass
class Trecho:
    desde: date
    ate: date
    preco: int
    capa: int | None


@dataclass
class Evento:
    nome: str
    inicio: date
    fim: date


@dataclass
class Veredito:
    evento: Evento
    preco_evento: int | None
    normal: int | None          # mediana dos preços observados na janela anterior
    minimo_antes: int | None
    capa: int | None
    texto: str
    categoria: str = "sem_dado"  # sem_dado | real | pequeno | nao_desconto | inflado | antes_do_evento


def ler_eventos(caminho: str | Path) -> list[Evento]:
    p = Path(caminho)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return [Evento(r["nome"], date.fromisoformat(r["inicio"]), date.fromisoformat(r["fim"]))
                for r in csv.DictReader(f)]


def buscar(conn: sqlite3.Connection, termo: str) -> list[tuple[str, str]]:
    """(asin, titulo) cujo ASIN é igual ao termo ou cujo título contém o termo."""
    termo = termo.strip()
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'catalogo'").fetchone():
        q = "SELECT asin, COALESCE(titulo, '') || COALESCE(' [' || formato || ']', '') FROM catalogo"
    else:
        q = "SELECT asin, COALESCE(titulo, '') FROM livros"
    linhas = conn.execute(q + " WHERE asin = ? OR titulo LIKE ? ORDER BY 2 LIMIT 50",
                          (termo.upper(), f"%{termo}%")).fetchall()
    return [(r[0], r[1]) for r in linhas]


def serie(conn: sqlite3.Connection, asin: str) -> list[Trecho]:
    """Trechos de preço constante, em ordem. Funciona com o banco do catálogo ou o da lista."""
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'historico'").fetchone():
        linhas = conn.execute(
            "SELECT preco_centavos, preco_capa_centavos, desde, ate FROM historico "
            "WHERE asin = ? ORDER BY desde", (asin,)).fetchall()
        return [Trecho(dia_brasil(r[2]), dia_brasil(r[3]), r[0], r[1]) for r in linhas]
    linhas = conn.execute(
        "SELECT preco_centavos, preco_capa_centavos, coletado_em FROM precos "
        "WHERE asin = ? AND status = 'ok' AND preco_centavos IS NOT NULL ORDER BY coletado_em",
        (asin,)).fetchall()
    out: list[Trecho] = []
    for preco, capa, quando in linhas:
        d = dia_brasil(quando)
        if out and out[-1].preco == preco and (d - out[-1].ate).days <= 10:
            out[-1].ate = d
            out[-1].capa = out[-1].capa or capa
        else:
            out.append(Trecho(d, d, preco, capa))
    return out


JANELA_MEDIANA = 90  # dias da mediana desenhada no gráfico


def mediana_movel(trechos: list[Trecho], janela: int = JANELA_MEDIANA) -> list[tuple[date, int]]:
    """Para cada dia observado, a mediana dos preços dos últimos `janela` dias (inclusive o dia).

    Cada dia entra uma vez, com o preço do trecho em que cai; dias sem observação não entram.
    Devolve só os pontos em que o valor muda, mais o último dia.
    """
    por_dia: dict[date, int] = {}
    for t in trechos:
        d = t.desde
        while d <= t.ate:
            por_dia[d] = t.preco
            d += timedelta(days=1)
    dias = sorted(por_dia)
    out: list[tuple[date, int]] = []
    for d in dias:
        w = [por_dia[x] for x in dias if d - timedelta(days=janela - 1) <= x <= d]
        m = int(statistics.median(w))
        if not out or out[-1][1] != m:
            out.append((d, m))
    if out and out[-1][0] != dias[-1]:
        out.append((dias[-1], out[-1][1]))
    return out


def aviso(conn: sqlite3.Connection) -> str:
    """Texto da tabela `aviso`, que os bancos simulados trazem; vazio nos bancos reais."""
    if not conn.execute("SELECT name FROM sqlite_master WHERE name = 'aviso'").fetchone():
        return ""
    r = conn.execute("SELECT texto FROM aviso LIMIT 1").fetchone()
    return r[0] if r else ""


def _brl(c: int | None) -> str:
    return "–" if c is None else f"R$ {c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def veredito(trechos: list[Trecho], ev: Evento) -> Veredito:
    antes = [t for t in trechos if t.ate < ev.inicio and t.ate >= ev.inicio - timedelta(days=JANELA_BASE)]
    durante = [t for t in trechos if t.desde <= ev.fim and t.ate >= ev.inicio]
    capa = next((t.capa for t in reversed(trechos) if t.capa), None)
    if not durante:
        return Veredito(ev, None, None, None, capa, "sem observação durante o evento", "sem_dado")
    preco = min(t.preco for t in durante)
    if not antes:
        return Veredito(ev, preco, None, None, capa,
                        f"{_brl(preco)} no evento; sem {JANELA_BASE} dias de histórico antes para comparar", "sem_dado")
    # mediana ponderada por dias de cada trecho (um preço que durou 50 dias pesa mais que um de 1 dia)
    dias: list[int] = []
    for t in antes:
        ini = max(t.desde, ev.inicio - timedelta(days=JANELA_BASE))  # só conta a parte dentro da janela
        dias += [t.preco] * ((t.ate - ini).days + 1)
    normal = int(statistics.median(dias))
    minimo = min(t.preco for t in antes)
    desc = (normal - preco) / normal
    pico = max((t.preco for t in trechos
                if t.ate >= ev.inicio - timedelta(days=JANELA_PICO) and t.desde < ev.inicio), default=normal)
    subiu = pico / normal - 1
    inflado = subiu >= LIMIAR_INFLADO
    extra = f"; {(capa - preco) / capa * 100:.0f}% abaixo da capa" if capa and capa > preco else ""
    if desc < LIMIAR_DESCONTO:
        if inflado:
            cat = "inflado"
            juiz = (f"NÃO é desconto: o preço subiu {subiu * 100:.0f}% nas semanas antes ({_brl(pico)}) "
                    "e só voltou ao normal")
        elif preco >= normal:
            cat, juiz = "nao_desconto", "NÃO é desconto: o preço normal era igual ou menor"
        else:
            cat = "pequeno"
            juiz = f"NÃO é desconto relevante: só {desc * 100:.0f}% abaixo do normal (oscilação comum)"
    elif (antes[-1].preco * (1 - LIMIAR_DESCONTO) <= preco) and not inflado:
        cat = "antes_do_evento"
        juiz = (f"o preço já era {_brl(antes[-1].preco)} logo antes do evento: a queda "
                f"({desc * 100:.0f}% abaixo do normal) não é da promoção")
    else:
        cat = "real"
        juiz = (f"{desc * 100:.0f}% abaixo do normal e é o menor preço da janela" if preco <= minimo
                else f"{desc * 100:.0f}% abaixo do normal, mas já esteve mais barato ({_brl(minimo)})")
        if inflado:
            cat = "inflado"
            juiz += f"; atenção: antes disso o preço havia subido {subiu * 100:.0f}%"
    return Veredito(ev, preco, normal, minimo, capa,
                    f"{_brl(preco)} no evento vs normal {_brl(normal)}: {juiz}{extra}", cat)


def _svg(trechos: list[Trecho], eventos: list[Evento], largura=860, altura=360) -> str:
    ml, mr, mt, mb = 70, 20, 20, 40
    d0 = min(t.desde for t in trechos)
    d1 = max(t.ate for t in trechos)
    for e in eventos:  # mostra eventos próximos do período observado
        if d0 - timedelta(days=30) <= e.fim <= d1 + timedelta(days=120):
            d0, d1 = min(d0, e.inicio), max(d1, e.fim)
    d1 = max(d1, d0 + timedelta(days=6))
    med = mediana_movel(trechos)
    valores = [t.preco for t in trechos] + [t.capa for t in trechos if t.capa] + [m for _, m in med]
    lo, hi = min(valores), max(valores)
    folga = max((hi - lo) * 0.1, 50)
    lo, hi = max(0, lo - folga), hi + folga
    X = lambda d: ml + (d - d0).days / (d1 - d0).days * (largura - ml - mr)
    Y = lambda v: mt + (1 - (v - lo) / (hi - lo)) * (altura - mt - mb)
    p: list[str] = [f'<svg viewBox="0 0 {largura} {altura}" role="img" aria-label="Histórico de preço">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        p.append(f'<line x1="{ml}" x2="{largura - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="g"/>'
                 f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{html.escape(_brl(int(v)))}</text>')
    for e in eventos:
        if e.fim < d0 or e.inicio > d1:
            continue
        x0, x1 = X(e.inicio), max(X(e.fim), X(e.inicio) + 3)
        p.append(f'<rect x="{x0:.1f}" y="{mt}" width="{x1 - x0:.1f}" height="{altura - mt - mb}" class="ev"/>'
                 f'<text x="{x0 - 3 if x0 > largura * 0.6 else x0 + 3:.1f}" y="{mt + 12}" class="evt" '
                 f'text-anchor="{"end" if x0 > largura * 0.6 else "start"}">{html.escape(e.nome)}</text>')
    n = 5
    for i in range(n):
        d = d0 + (d1 - d0) * i // (n - 1)
        ancora = "start" if i == 0 else "end" if i == n - 1 else "middle"
        p.append(f'<text x="{X(d):.1f}" y="{altura - 14}" text-anchor="{ancora}">{d.strftime("%d/%m/%y")}</text>')
    capas = [t for t in trechos if t.capa]
    if capas:
        pts = " ".join(f"{X(t.desde):.1f},{Y(t.capa):.1f} {X(t.ate):.1f},{Y(t.capa):.1f}" for t in capas)
        p.append(f'<polyline points="{pts}" class="capa"/>')
    mp = ""
    for i, (d, m) in enumerate(med):
        if i:
            mp += f"L{X(d):.1f},{Y(med[i - 1][1]):.1f}"  # degrau
        mp += f"{'M' if not i else 'L'}{X(d):.1f},{Y(m):.1f}"
    p.append(f'<path d="{mp}" class="med"><title>Mediana dos últimos {JANELA_MEDIANA} dias</title></path>')
    path = ""
    for i, t in enumerate(trechos):
        x0, x1, y = X(t.desde), X(t.ate), Y(t.preco)
        if i and (t.desde - trechos[i - 1].ate).days <= 10:
            path += f"L{x0:.1f},{y:.1f}"  # degrau: o preço mudou entre duas visitas
        else:
            path += f"M{x0:.1f},{y:.1f}"
        path += f"L{max(x1, x0 + 1):.1f},{y:.1f}"
    p.append(f'<path d="{path}" class="preco"/>')
    for t in trechos:
        p.append(f'<circle cx="{X(t.desde):.1f}" cy="{Y(t.preco):.1f}" r="3" class="pt">'
                 f'<title>{t.desde:%d/%m/%Y}: {html.escape(_brl(t.preco))}</title></circle>')
    p.append("</svg>")
    return "".join(p)


CSS = """
:root{--fg:#1d2327;--bg:#fff;--mu:#667;--pr:#0b6bcb;--ca:#999;--me:#d9730d;--ev:#f5a62333;--gr:#0001}
@media(prefers-color-scheme:dark){:root{--fg:#e8e8e8;--bg:#16191c;--mu:#9aa;--pr:#5aa9ff;--ca:#777;--me:#ffa94d;--ev:#f5a62344;--gr:#fff2}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:900px;margin:0 auto;padding:16px}
svg{width:100%;height:auto;font-size:11px;fill:var(--mu)}.g{stroke:var(--gr)}
.preco{fill:none;stroke:var(--pr);stroke-width:2}.pt{fill:var(--pr)}
.med{fill:none;stroke:var(--me);stroke-width:2;stroke-dasharray:2 3}
.capa{fill:none;stroke:var(--ca);stroke-width:1.5;stroke-dasharray:5 4}
.ev{fill:var(--ev)}.evt{fill:var(--fg);font-size:11px}
li{margin:.3em 0}small{color:var(--mu)}
"""


def pagina(titulo: str, asin: str, trechos: list[Trecho], eventos: list[Evento], aviso: str = "") -> str:
    ultimo = trechos[-1]
    precos = [t.preco for t in trechos]
    resumo = (f"Atual {_brl(ultimo.preco)} · mínimo {_brl(min(precos))} · máximo {_brl(max(precos))}"
              f" · mediana {JANELA_MEDIANA} dias {_brl(mediana_movel(trechos)[-1][1])}"
              f" · capa {_brl(next((t.capa for t in reversed(trechos) if t.capa), None))}"
              f" · observado de {trechos[0].desde:%d/%m/%Y} a {ultimo.ate:%d/%m/%Y}")
    vs = "".join(f"<li><b>{html.escape(v.evento.nome)}</b> ({v.evento.inicio:%d/%m/%Y}): {html.escape(v.texto)}</li>"
                 for v in (veredito(trechos, e) for e in eventos))
    return (f'<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(titulo)}</title><style>{CSS}</style><body>"
            f'{f"<p><b>{html.escape(aviso)}</b></p>" if aviso else ""}'
            f"<h1>{html.escape(titulo)}</h1><small>ASIN {html.escape(asin)} · linha contínua: preço; "
            f"tracejada cinza: preço de capa; pontilhada laranja: mediana dos últimos 90 dias; faixa: promoção</small>{_svg(trechos, eventos)}"
            f"<p>{html.escape(resumo)}</p><h2>Promoções</h2><ul>{vs or '<li>nenhum evento em eventos.csv</li>'}</ul>"
            f"</body></html>")
