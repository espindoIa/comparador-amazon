"""Página com o histórico de preço de um livro: gráfico e números, sem conclusões."""

from __future__ import annotations

import csv
import html
import sqlite3
import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .db import dia_brasil

JANELA = 90        # dias da mediana e da faixa usual
JANELA_PICO = 21   # dias antes de um evento em que se procura o preço mais alto
BURACO = 10        # dias sem coleta a partir dos quais o trecho é desenhado como lacuna


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


def aviso(conn: sqlite3.Connection) -> str:
    """Texto da tabela `aviso`, que os bancos simulados trazem; vazio nos bancos reais."""
    if not conn.execute("SELECT name FROM sqlite_master WHERE name = 'aviso'").fetchone():
        return ""
    r = conn.execute("SELECT texto FROM aviso LIMIT 1").fetchone()
    return r[0] if r else ""


def _brl(c: int | None) -> str:
    return "–" if c is None else f"R$ {c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def por_dia(trechos: list[Trecho]) -> dict[date, int]:
    """Preço de cada dia observado (cada dia entra uma vez; dias sem coleta não entram)."""
    out: dict[date, int] = {}
    for t in trechos:
        d = t.desde
        while d <= t.ate:
            out[d] = t.preco
            d += timedelta(days=1)
    return out


def _quartis(w: list[int]) -> tuple[int, int, int]:
    if len(w) < 2:
        return w[0], w[0], w[0]
    q = statistics.quantiles(w, n=4, method="inclusive")
    return int(q[0]), int(statistics.median(w)), int(q[2])


def janela_movel(dias: dict[date, int], janela: int = JANELA) -> list[tuple[date, int, int, int]]:
    """Para cada dia observado: (dia, 1º quartil, mediana, 3º quartil) dos últimos `janela` dias."""
    ordem = sorted(dias)
    return [(d, *_quartis([dias[x] for x in ordem if d - timedelta(days=janela - 1) <= x <= d])) for d in ordem]


@dataclass
class Fatos:
    """Números de uma janela de até 90 dias terminada num dia (inclusive), sem julgamento."""
    ate: date
    preco: int | None            # preço no próprio dia ou, para um evento, o menor durante ele
    mediana: int | None
    q1: int | None
    q3: int | None
    minimo: int | None
    dia_minimo: date | None
    maximo: int | None
    dia_maximo: date | None
    dias_observados: int
    dias_janela: int
    pico_recente: int | None     # preço mais alto nos 21 dias anteriores
    ultima_vez_igual_ou_menor: date | None  # antes de `ate`; None = nunca no período observado
    capa: int | None


def fatos(trechos: list[Trecho], ate: date, preco: int | None = None, janela: int = JANELA) -> Fatos:
    """Resume os `janela` dias até `ate` (exclusive se `preco` vier de um evento, ver `fatos_evento`)."""
    dias = por_dia(trechos)
    ini = ate - timedelta(days=janela - 1)
    w = {d: p for d, p in dias.items() if ini <= d <= ate}
    capa = next((t.capa for t in reversed(trechos) if t.capa and t.desde <= ate), None)
    if preco is None:
        preco = dias.get(ate)
    if not w:
        return Fatos(ate, preco, None, None, None, None, None, None, None, 0, janela, None, None, capa)
    q1, med, q3 = _quartis(list(w.values()))
    dmin = min(w, key=lambda d: (w[d], -d.toordinal()))
    dmax = max(w, key=lambda d: (w[d], d.toordinal()))
    recente = [p for d, p in w.items() if d >= ate - timedelta(days=JANELA_PICO)]
    igual = [d for d, p in dias.items() if d < ate and preco is not None and p <= preco]
    return Fatos(ate, preco, med, q1, q3, w[dmin], dmin, w[dmax], dmax, len(w), janela,
                 max(recente) if recente else None, max(igual) if igual else None, capa)


def fatos_evento(trechos: list[Trecho], ev: Evento) -> Fatos | None:
    """Menor preço durante o evento e a janela de 90 dias que o antecede. None sem coleta no evento."""
    dias = por_dia(trechos)
    durante = {d: p for d, p in dias.items() if ev.inicio <= d <= ev.fim}
    if not durante:
        return None
    return fatos(trechos, ev.inicio - timedelta(days=1), preco=min(durante.values()))


def _pct(a: int, b: int) -> str:
    return f"{(a - b) / b * 100:+.0f}%".replace("+0%", "0%")


def _data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "–"


def _cartao(rotulo: str, valor: str, nota: str = "") -> str:
    return (f'<div class="c"><span>{html.escape(rotulo)}</span><b>{html.escape(valor)}</b>'
            f'{f"<small>{html.escape(nota)}</small>" if nota else ""}</div>')


def _comparar(valor: int, ref: int) -> str:
    pct = round(abs(valor - ref) / ref * 100)
    return "igual a" if pct == 0 else f"{pct}% {'acima' if valor > ref else 'abaixo'} do"


def _cartoes_atuais(f: Fatos) -> str:
    c = [_cartao("Hoje", _brl(f.preco), _data(f.ate))]
    if f.mediana is not None:
        c += [_cartao("Preço mais comum", _brl(f.mediana), f"mediana dos últimos {f.dias_janela} dias"),
              _cartao("Mais barato", _brl(f.minimo), _data(f.dia_minimo)),
              _cartao("Mais caro", _brl(f.maximo), _data(f.dia_maximo))]
    return "".join(c)


def _aviso_dados(f: Fatos) -> str:
    if f.dias_observados >= f.dias_janela * 0.5:
        return ""
    return (f'<p class="mu">Ainda temos poucos dados: só {f.dias_observados} dias com preço registrado '
            f'nos últimos {f.dias_janela}.</p>')


def resumo_evento(ev: Evento, f: Fatos | None) -> str:
    """Uma linha com os números do evento, para o terminal."""
    if f is None:
        return f"{ev.nome}: sem coleta durante o evento"
    if f.mediana is None:
        return f"{ev.nome}: {_brl(f.preco)} (sem coleta nos {f.dias_janela} dias anteriores)"
    return (f"{ev.nome}: {_brl(f.preco)}, {_comparar(f.preco, f.mediana)} preço mais comum dos "
            f"{f.dias_janela} dias antes ({_brl(f.mediana)}); mais barato antes {_brl(f.minimo)}, "
            f"mais caro {_brl(f.maximo)}; {f.dias_observados} dias com coleta")


def _bloco_evento(ev: Evento, f: Fatos | None) -> str:
    quando = _data(ev.inicio) + (f" a {_data(ev.fim)}" if ev.fim != ev.inicio else "")
    cab = f"<h3>{html.escape(ev.nome)} <small>{quando}</small></h3>"
    if f is None:
        return f'<section>{cab}<p class="mu">Sem preço registrado durante o evento.</p></section>'
    if f.mediana is None:
        return (f'<section>{cab}<p><b>{_brl(f.preco)}</b> no evento. Não há preços registrados nos '
                f'{f.dias_janela} dias anteriores para comparar.</p></section>')
    li = [f"Antes do evento, o preço mais comum era <b>{_brl(f.mediana)}</b> "
          f"(entre {_brl(f.minimo)}, em {_data(f.dia_minimo)}, e {_brl(f.maximo)}, em {_data(f.dia_maximo)}).",
          ]
    if f.pico_recente:
        li.append(f"Nas 3 semanas antes, chegou a {_brl(f.pico_recente)}.")
    li.append("Última vez com preço igual ou menor: " + (_data(f.ultima_vez_igual_ou_menor)
              if f.ultima_vez_igual_ou_menor else "nunca, desde o início da coleta") + ".")
    det = [f"Faixa onde ficou a metade central dos dias: {_brl(f.q1)} a {_brl(f.q3)}.",
           f"Dias com preço registrado na janela: {f.dias_observados} de {f.dias_janela}."]
    if f.capa:
        det.insert(1, f"Preço de capa informado pela Amazon: {_brl(f.capa)} "
                      f"(evento {_comparar(f.preco, f.capa)} preço de capa).")
    return (f"<section>{cab}<p class=\"gr\"><b>{_brl(f.preco)}</b> no evento, "
            f"{_comparar(f.preco, f.mediana)} preço mais comum.</p>"
            f"<ul>{''.join(f'<li>{x}</li>' for x in li)}</ul>"
            f"<details><summary>Mais detalhes</summary><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in det)}</ul>"
            f"</details></section>")


def _svg(trechos: list[Trecho], eventos: list[Evento], largura=860, altura=380) -> tuple[str, list]:
    ml, mr, mt, mb = 72, 20, 22, 40
    dias = por_dia(trechos)
    mov = janela_movel(dias)
    d0, d1 = min(dias), max(dias)
    for e in eventos:  # só estende o eixo até eventos próximos do período observado
        if d0 - timedelta(days=30) <= e.fim <= d1 + timedelta(days=120):
            d0, d1 = min(d0, e.inicio), max(d1, e.fim)
    d1 = max(d1, d0 + timedelta(days=6))
    precos = [t.preco for t in trechos]
    valores = precos + [m for _, _, m, _ in mov]
    lo, hi = min(valores), max(valores)
    folga = max((hi - lo) * 0.12, 50)
    lo, hi = max(0, lo - folga), hi + folga
    X = lambda d: ml + (d - d0).days / (d1 - d0).days * (largura - ml - mr)
    Y = lambda v: mt + (1 - (v - lo) / (hi - lo)) * (altura - mt - mb)
    base = altura - mb
    p = [f'<svg id="graf" viewBox="0 0 {largura} {altura}" role="img" aria-label="Histórico de preço">'
         f'<defs><pattern id="lac" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         f'<line x1="0" y1="0" x2="0" y2="6" class="lacl"/></pattern></defs>']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        p.append(f'<line x1="{ml}" x2="{largura - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="g"/>'
                 f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{html.escape(_brl(int(v)))}</text>')
    for i in range(5):
        d = d0 + (d1 - d0) * i // 4
        a = "start" if i == 0 else "end" if i == 4 else "middle"
        p.append(f'<text x="{X(d):.1f}" y="{altura - 14}" text-anchor="{a}">{d:%d/%m/%y}</text>')
    for a, b in zip(trechos, trechos[1:]):  # lacunas de coleta
        if (b.desde - a.ate).days > BURACO:
            p.append(f'<rect x="{X(a.ate):.1f}" y="{mt}" width="{X(b.desde) - X(a.ate):.1f}" height="{base - mt}" '
                     f'fill="url(#lac)"><title>Sem coleta de {_data(a.ate)} a {_data(b.desde)}</title></rect>')
    for e in eventos:
        if e.fim < d0 or e.inicio > d1:
            continue
        x0 = X(e.inicio) - 3
        w = max(X(e.fim) - X(e.inicio), 0) + 6
        right = x0 > largura * 0.6
        p.append(f'<rect x="{x0:.1f}" y="{mt}" width="{w:.1f}" height="{base - mt}" class="ev"/>'
                 f'<text x="{x0 - 4 if right else x0 + w + 4:.1f}" y="{mt + 12}" class="evt" '
                 f'text-anchor="{"end" if right else "start"}">{html.escape(e.nome)}</text>')
    mp = ""
    for i, (d, _, m, _) in enumerate(mov):
        mp += f"{'M' if i == 0 else 'L'}{X(d):.1f},{Y(m):.1f}"
    p.append(f'<path d="{mp}" class="med"/>')
    path = ""
    for i, t in enumerate(trechos):
        x0, x1, y = X(t.desde), X(t.ate), Y(t.preco)
        ligado = i and (t.desde - trechos[i - 1].ate).days <= BURACO
        path += f"{'L' if ligado else 'M'}{x0:.1f},{y:.1f}L{max(x1, x0 + 1):.1f},{y:.1f}"
    p.append(f'<path d="{path}" class="preco"/>')
    for t in trechos:
        p.append(f'<circle cx="{X(t.desde):.1f}" cy="{Y(t.preco):.1f}" r="3" class="pt"/>')
    for e in eventos:
        dur = {d: v for d, v in dias.items() if e.inicio <= d <= e.fim}
        if dur:
            d = min(dur, key=dur.get)
            p.append(f'<circle cx="{X(d):.1f}" cy="{Y(dur[d]):.1f}" r="5.5" class="pe"/>'
                     f'<text x="{X(d) + (-9 if X(d) > largura * 0.6 else 9):.1f}" y="{Y(dur[d]) + 4:.1f}" class="pet" '
                     f'text-anchor="{"end" if X(d) > largura * 0.6 else "start"}">{html.escape(_brl(dur[d]))}</text>')
    p.append(f'<line id="cur" x1="0" x2="0" y1="{mt}" y2="{base}" class="cur" visibility="hidden"/></svg>')
    medd = {d: (a, m, b) for d, a, m, b in mov}
    dados = [[d.isoformat(), dias[d], *medd[d]] for d in sorted(dias)]
    geo = {"d0": d0.toordinal(), "d1": d1.toordinal(), "ml": ml, "mr": mr, "w": largura}
    return "".join(p), [dados, geo]


JS = """
(function(){var D=%s,G=D[1];D=D[0];var s=document.getElementById('graf'),c=document.getElementById('cur'),
t=document.getElementById('tip');if(!s)return;
function brl(v){return 'R$ '+(v/100).toFixed(2).replace('.',',').replace(/\\B(?=(\\d{3})+,)/g,'.')}
function mover(e){var r=s.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*G.w;
var o=(x-G.ml)/(G.w-G.ml-G.mr)*(G.d1-G.d0)+G.d0,b=null,bd=1e9;
D.forEach(function(r){var n=Date.parse(r[0])/864e5+719163,k=Math.abs(n-o);if(k<bd){bd=k;b=r}});
if(!b)return;var n=Date.parse(b[0])/864e5+719163,px=G.ml+(n-G.d0)/(G.d1-G.d0)*(G.w-G.ml-G.mr);
c.setAttribute('x1',px);c.setAttribute('x2',px);c.setAttribute('visibility','visible');
var p=b[0].split('-');t.textContent=p[2]+'/'+p[1]+'/'+p[0]+': '+brl(b[1])+' (preço mais comum: '+brl(b[3])+')'}
s.addEventListener('pointermove',mover);s.addEventListener('pointerleave',function(){c.setAttribute('visibility','hidden');
t.textContent='Toque ou passe o mouse no gráfico para ver o preço de cada dia.'})})();
"""

CSS = """
:root{--fg:#1d2327;--bg:#fff;--mu:#667;--pr:#0b6bcb;--ca:#999;--me:#d9730d;--fx:#d9730d1f;--ev:#7a5cff22;--evl:#6b4de6;--gr:#0001;--cd:#f4f6f8}
@media(prefers-color-scheme:dark){:root{--fg:#e8e8e8;--bg:#16191c;--mu:#9aa;--pr:#5aa9ff;--ca:#777;--me:#ffa94d;--fx:#ffa94d26;--ev:#9d86ff33;--evl:#b7a6ff;--gr:#fff2;--cd:#20252a}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:900px;margin:0 auto;padding:16px}
h1{font-size:1.4em;margin:.2em 0}h2{font-size:1.1em;margin:1.4em 0 .4em}h3{font-size:1em;margin:1.2em 0 .4em}
svg{width:100%;height:auto;font-size:11px;fill:var(--mu);touch-action:pan-y}.g{stroke:var(--gr)}
.preco{fill:none;stroke:var(--pr);stroke-width:2}.pt{fill:var(--pr)}
.pe{fill:var(--bg);stroke:var(--pr);stroke-width:2.5}.pet{fill:var(--fg);font-size:12px;font-weight:600}
.med{fill:none;stroke:var(--me);stroke-width:2;stroke-dasharray:2 3}
.capa{stroke:var(--ca);stroke-width:1.2;stroke-dasharray:5 4}
.ev{fill:var(--ev)}.evt{fill:var(--evl);font-size:11px;font-weight:600}.cur{stroke:var(--mu);stroke-width:1}
.lacl{stroke:var(--ca);stroke-width:1;opacity:.5}
@media(max-width:600px){svg{font-size:21px}.pet,.evt{font-size:22px}}
#tip{min-height:1.5em;color:var(--fg);font-size:13px;margin:.3em 0}
.leg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--mu);margin:.3em 0 .6em}
.leg i{display:inline-block;width:22px;height:0;border-top:2px solid;vertical-align:middle;margin-right:5px}
.leg .b{height:10px;border:0;background:var(--fx);border-top:0}
.cs{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.c{background:var(--cd);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column}
.c span{font-size:12px;color:var(--mu)}.c b{font-size:1.05em}.c small{color:var(--mu);font-size:11px}
.mu,small{color:var(--mu)}
ul{margin:.3em 0;padding-left:1.2em}li{margin:.25em 0}.gr{font-size:1.05em;margin:.3em 0}
details{margin:.4em 0;color:var(--mu);font-size:14px}summary{cursor:pointer}
"""


def pagina(titulo: str, asin: str, trechos: list[Trecho], eventos: list[Evento], aviso: str = "") -> str:
    svg, dados = _svg(trechos, eventos)
    atual = fatos(trechos, trechos[-1].ate)
    blocos = "".join(_bloco_evento(e, fatos_evento(trechos, e)) for e in eventos)
    legenda = ('<div class="leg"><span><i style="border-color:var(--pr)"></i>preço</span>'
               '<span><i style="border-color:var(--me);border-top-style:dotted"></i>preço mais comum (últimos 90 dias)</span>'
               '<span style="color:var(--evl)">▮ evento</span></div>')
    return (f'<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(titulo)}</title><style>{CSS}</style><body>"
            f'{f"<p><b>{html.escape(aviso)}</b></p>" if aviso else ""}'
            f"<h1>{html.escape(titulo)}</h1><small>ASIN {html.escape(asin)} · preços de "
            f"{_data(trechos[0].desde)} a {_data(trechos[-1].ate)}</small>"
            f'<div class="cs" style="margin:12px 0">{_cartoes_atuais(atual)}</div>{_aviso_dados(atual)}'
            f'{legenda}{svg}<div id="tip">Toque ou passe o mouse no gráfico para ver o preço de cada dia.</div>'
            f"{f'<h2>Black Friday e outras promoções</h2>{blocos}' if blocos else ''}"
            f"<script>{JS % json.dumps(dados)}</script></body></html>")
