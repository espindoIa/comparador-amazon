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


JS = r"""
(function(){
var D=__DADOS__,W=860,H=380,ML=72,MR=20,MT=22,MB=40,BASE=H-MB,BURACO=__BURACO__;
var box=document.getElementById('graf-box'),tip=document.getElementById('tip'),ctl=document.getElementById('ctl');
var DICA='Toque ou passe o mouse no gráfico para ver o preço de cada dia.';
var opt={med:1,faixa:0,capa:0,ev:1,lac:1,pts:0};
try{var sv=JSON.parse(localStorage.getItem('opt_graf')||'null');if(sv)for(var k in opt)if(k in sv)opt[k]=sv[k]?1:0}catch(e){}
var F0=D.full[0],F1=D.full[1],v={a:D.def[0],b:D.def[1]};
function pad(n){return n<10?'0'+n:''+n}
function brl(c){return 'R$ '+(c/100).toFixed(2).replace('.',',').replace(/\B(?=(\d{3})+,)/g,'.')}
function dt(o){var d=new Date((o-719163)*864e5);return pad(d.getUTCDate())+'/'+pad(d.getUTCMonth()+1)+'/'+String(d.getUTCFullYear()).slice(2)}
function dl(o){var d=new Date((o-719163)*864e5);return pad(d.getUTCDate())+'/'+pad(d.getUTCMonth()+1)+'/'+d.getUTCFullYear()}
function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function clamp(a,b){var sp=Math.max(6,Math.min(b-a,F1-F0));a=Math.max(F0,Math.min(a,F1-sp));v.a=a;v.b=a+sp}
function X(o){return ML+(o-v.a)/(v.b-v.a)*(W-ML-MR)}
function draw(){
 ML=window.innerWidth<=600?104:72;
 var vals=[],i,r,t,e,out=[];
 D.dias.forEach(function(r){if(r[0]>=v.a&&r[0]<=v.b){vals.push(r[1]);if(opt.med)vals.push(r[3]);if(opt.faixa)vals.push(r[2],r[4])}});
 if(!vals.length)D.dias.forEach(function(r){vals.push(r[1])});
 if(opt.capa&&D.capa)vals.push(D.capa);
 var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals),f=Math.max((hi-lo)*.12,50);lo=Math.max(0,lo-f);hi+=f;
 function Y(c){return MT+(1-(c-lo)/(hi-lo))*(BASE-MT)}
 out.push('<svg id="graf" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Histórico de preço"><defs>'+
  '<clipPath id="rec"><rect x="'+ML+'" y="'+MT+'" width="'+(W-ML-MR)+'" height="'+(BASE-MT)+'"/></clipPath>'+
  '<pattern id="lac" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" class="lacl"/></pattern></defs>');
 for(i=0;i<5;i++){var c=lo+(hi-lo)*i/4;out.push('<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+Y(c).toFixed(1)+'" y2="'+Y(c).toFixed(1)+'" class="g"/><text x="'+(ML-8)+'" y="'+(Y(c)+4).toFixed(1)+'" text-anchor="end">'+brl(Math.round(c))+'</text>')}
 for(i=0;i<5;i++){var o=Math.round(v.a+(v.b-v.a)*i/4);out.push('<text x="'+X(o).toFixed(1)+'" y="'+(H-14)+'" text-anchor="'+(i==0?'start':i==4?'end':'middle')+'">'+dt(o)+'</text>')}
 out.push('<g clip-path="url(#rec)">');
 if(opt.lac)for(i=1;i<D.tr.length;i++){var a=D.tr[i-1],b=D.tr[i];if(b[0]-a[1]>BURACO)out.push('<rect x="'+X(a[1]).toFixed(1)+'" y="'+MT+'" width="'+(X(b[0])-X(a[1])).toFixed(1)+'" height="'+(BASE-MT)+'" fill="url(#lac)"><title>Sem coleta de '+dt(a[1])+' a '+dt(b[0])+'</title></rect>')}
 if(opt.ev)D.ev.forEach(function(e){var x0=X(e[1])-3,w=Math.max(X(e[2])-X(e[1]),0)+6;
  out.push('<rect x="'+x0.toFixed(1)+'" y="'+MT+'" width="'+w.toFixed(1)+'" height="'+(BASE-MT)+'" class="ev"/>');
  var dir=x0>W*.6;out.push('<text x="'+(dir?x0-4:x0+w+4).toFixed(1)+'" y="'+(MT+12)+'" class="evt" text-anchor="'+(dir?'end':'start')+'">'+esc(e[0])+'</text>')});
 if(opt.faixa&&D.dias.length>1){var top='',bot='';D.dias.forEach(function(r,j){top+=(j?'L':'M')+X(r[0]).toFixed(1)+','+Y(r[4]).toFixed(1)});
  for(i=D.dias.length-1;i>=0;i--)bot+='L'+X(D.dias[i][0]).toFixed(1)+','+Y(D.dias[i][2]).toFixed(1);
  out.push('<path d="'+top+bot+'Z" class="faixa"/>')}
 if(opt.med){var m='';D.dias.forEach(function(r,j){m+=(j?'L':'M')+X(r[0]).toFixed(1)+','+Y(r[3]).toFixed(1)});out.push('<path d="'+m+'" class="med"/>')}
 if(opt.capa&&D.capa)out.push('<line x1="'+ML+'" x2="'+(W-MR)+'" y1="'+Y(D.capa).toFixed(1)+'" y2="'+Y(D.capa).toFixed(1)+'" class="capa"/>');
 var pa='';D.tr.forEach(function(t,j){var x0=X(t[0]),x1=Math.max(X(t[1]),x0+1),y=Y(t[2]).toFixed(1),lig=j&&t[0]-D.tr[j-1][1]<=BURACO;
  pa+=(lig?'L':'M')+x0.toFixed(1)+','+y+'L'+x1.toFixed(1)+','+y});
 out.push('<path d="'+pa+'" class="preco"/>');
 if(opt.pts)D.dias.forEach(function(r){out.push('<circle cx="'+X(r[0]).toFixed(1)+'" cy="'+Y(r[1]).toFixed(1)+'" r="2" class="pt"/>')});
 else D.tr.forEach(function(t){out.push('<circle cx="'+X(t[0]).toFixed(1)+'" cy="'+Y(t[2]).toFixed(1)+'" r="3" class="pt"/>')});
 if(opt.ev)D.ev.forEach(function(e){if(e[3]==null)return;var x=X(e[4]),dir=x>W*.6;
  out.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(e[3]).toFixed(1)+'" r="5.5" class="pe"/><text x="'+(x+(dir?-9:9)).toFixed(1)+'" y="'+(Y(e[3])+4).toFixed(1)+'" class="pet" text-anchor="'+(dir?'end':'start')+'">'+brl(e[3])+'</text>')});
 out.push('</g>');
 if(opt.capa&&D.capa)out.push('<text x="'+(W-MR)+'" y="'+(Y(D.capa)-4).toFixed(1)+'" text-anchor="end">capa '+brl(D.capa)+'</text>');
 out.push('<line id="cur" x1="0" x2="0" y1="'+MT+'" y2="'+BASE+'" class="cur" visibility="hidden"/></svg>');
 box.innerHTML=out.join('');
 var s=document.getElementById('graf');s.addEventListener('pointermove',hover);
 s.addEventListener('pointerleave',function(){document.getElementById('cur').setAttribute('visibility','hidden');tip.textContent=DICA});
 painel();
}
function hover(e){var s=document.getElementById('graf'),r=s.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*W,
 o=(x-ML)/(W-ML-MR)*(v.b-v.a)+v.a,b=null,bd=1e9;
 D.dias.forEach(function(q){if(q[0]<v.a||q[0]>v.b)return;var k=Math.abs(q[0]-o);if(k<bd){bd=k;b=q}});
 if(!b)return;var c=document.getElementById('cur'),px=X(b[0]);c.setAttribute('x1',px);c.setAttribute('x2',px);c.setAttribute('visibility','visible');
 var t=dl(b[0])+': '+brl(b[1]);
 if(opt.med)t+=' · preço mais comum '+brl(b[3]);if(opt.faixa)t+=' · faixa usual '+brl(b[2])+' a '+brl(b[4]);if(opt.capa&&D.capa)t+=' · capa '+brl(D.capa);
 tip.textContent=t}
function painel(){
 ctl.querySelectorAll('[data-op]').forEach(function(b){b.setAttribute('aria-pressed',opt[b.dataset.op]?'true':'false')});
 var sp=v.b-v.a;ctl.querySelectorAll('[data-per]').forEach(function(b){var n=+b.dataset.per,al=n==0?(v.a==F0&&v.b==F1):(sp==n-1&&v.b==F1);b.setAttribute('aria-pressed',al?'true':'false')});
 var zm=ctl.querySelector('[data-z="1"]'),zo=ctl.querySelector('[data-z="-1"]');if(zm)zm.disabled=sp<=6;if(zo)zo.disabled=sp>=F1-F0}
ctl.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var sp=v.b-v.a,c=(v.a+v.b)/2;
 if(b.dataset.op){opt[b.dataset.op]=opt[b.dataset.op]?0:1;try{localStorage.setItem('opt_graf',JSON.stringify(opt))}catch(x){}}
 else if(b.dataset.per!==undefined){var n=+b.dataset.per;if(n==0){v.a=F0;v.b=F1}else clamp(F1-n+1,F1)}
 else if(b.dataset.z){var f=b.dataset.z=='1'?.5:2;clamp(c-sp*f/2,c+sp*f/2)}
 else if(b.dataset.pan){var d=Math.round(sp/3)*(+b.dataset.pan);clamp(v.a+d,v.b+d)}
 else if(b.dataset.ev!==undefined){var ev=D.ev[+b.dataset.ev];clamp(ev[1]-45,ev[2]+7)}
 draw()});
tip.textContent=DICA;draw();
})();
"""

CSS = """
:root{--fg:#1d2327;--bg:#fff;--mu:#667;--pr:#0b6bcb;--ca:#999;--me:#d9730d;--fx:#d9730d26;--ev:#7a5cff22;--evl:#6b4de6;--gr:#0001;--cd:#f4f6f8;--bd:#c9d1d9}
@media(prefers-color-scheme:dark){:root{--fg:#e8e8e8;--bg:#16191c;--mu:#9aa;--pr:#5aa9ff;--ca:#777;--me:#ffa94d;--fx:#ffa94d2e;--ev:#9d86ff33;--evl:#b7a6ff;--gr:#fff2;--cd:#20252a;--bd:#3a434b}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:900px;margin:0 auto;padding:16px}
h1{font-size:1.4em;margin:.2em 0}h2{font-size:1.1em;margin:1.4em 0 .4em}h3{font-size:1em;margin:1.2em 0 .4em}
svg{width:100%;height:auto;font-size:11px;fill:var(--mu);touch-action:pan-y;display:block}.g{stroke:var(--gr)}
.preco{fill:none;stroke:var(--pr);stroke-width:2}.pt{fill:var(--pr)}
.pe{fill:var(--bg);stroke:var(--pr);stroke-width:2.5}.pet{fill:var(--fg);font-size:12px;font-weight:600}
.faixa{fill:var(--fx);stroke:none}.med{fill:none;stroke:var(--me);stroke-width:2;stroke-dasharray:2 3}
.capa{stroke:var(--ca);stroke-width:1.2;stroke-dasharray:5 4}
.ev{fill:var(--ev)}.evt{fill:var(--evl);font-size:11px;font-weight:600}.cur{stroke:var(--mu);stroke-width:1}
.lacl{stroke:var(--ca);stroke-width:1;opacity:.5}
@media(max-width:600px){svg{font-size:21px}.pet,.evt{font-size:22px}}
#tip{min-height:1.5em;color:var(--fg);font-size:13px;margin:.3em 0}
#ctl{display:flex;flex-direction:column;gap:6px;margin:8px 0}
#ctl .l{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
#ctl .t{font-size:12px;color:var(--mu);min-width:62px}
#ctl button{font:inherit;font-size:13px;color:var(--fg);background:var(--bg);border:1px solid var(--bd);border-radius:999px;padding:3px 12px;cursor:pointer;min-height:32px}
#ctl button[aria-pressed=true]{background:var(--pr);border-color:var(--pr);color:#fff}
#ctl button:disabled{opacity:.4;cursor:default}
#ctl button:focus-visible{outline:2px solid var(--pr);outline-offset:2px}
.cs{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.c{background:var(--cd);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column}
.c span{font-size:12px;color:var(--mu)}.c b{font-size:1.05em}.c small{color:var(--mu);font-size:11px}
.mu,small{color:var(--mu)}
ul{margin:.3em 0;padding-left:1.2em}li{margin:.25em 0}.gr{font-size:1.05em;margin:.3em 0}
details{margin:.4em 0;color:var(--mu);font-size:14px}summary{cursor:pointer}
"""

OPCOES = [("med", "Preço mais comum", "mediana dos últimos 90 dias"),
          ("faixa", "Faixa usual", "onde ficou a metade central dos dias, nos últimos 90 dias"),
          ("capa", "Preço de capa", "preço de capa informado pela Amazon"),
          ("ev", "Promoções", "Black Friday e outras datas"),
          ("lac", "Dias sem coleta", "períodos em que não há preço registrado"),
          ("pts", "Cada coleta", "um ponto por dia com preço registrado")]


def _controles(eventos: list[Evento], dados: dict) -> str:
    chips = "".join(f'<button type="button" data-ev="{i}">{html.escape(nome)}</button>'
                    for i, (nome, *_r) in enumerate(dados["ev"]) if dados["ev"][i][3] is not None)
    per = "".join(f'<button type="button" data-per="{n}">{t}</button>'
                  for n, t in ((30, "30 dias"), (90, "90 dias"), (0, "Tudo")))
    ops = "".join(f'<button type="button" data-op="{k}" title="{html.escape(d)}" aria-pressed="false">{html.escape(t)}</button>'
                  for k, t, d in OPCOES)
    return ('<div id="ctl">'
            f'<div class="l"><span class="t">Período</span>{per}{chips}</div>'
            '<div class="l"><span class="t">Zoom</span>'
            '<button type="button" data-z="1" aria-label="Aproximar">＋ Aproximar</button>'
            '<button type="button" data-z="-1" aria-label="Afastar">－ Afastar</button>'
            '<button type="button" data-pan="-1" aria-label="Voltar no tempo">◀</button>'
            '<button type="button" data-pan="1" aria-label="Avançar no tempo">▶</button></div>'
            f'<div class="l"><span class="t">Mostrar</span>{ops}</div></div>')


def _dados_js(trechos: list[Trecho], eventos: list[Evento]) -> dict:
    dias = por_dia(trechos)
    mov = janela_movel(dias)
    d0, d1 = min(dias), max(dias)
    evs = []
    for e in sorted(eventos, key=lambda e: e.inicio):
        if d0 - timedelta(days=30) <= e.fim <= d1 + timedelta(days=120):  # só eventos próximos do período
            evs.append(e)
            d0, d1 = min(d0, e.inicio), max(d1, e.fim)
    d1 = max(d1, d0 + timedelta(days=6))
    ev = []
    for e in evs:
        dur = {d: v for d, v in dias.items() if e.inicio <= d <= e.fim}
        dm = min(dur, key=dur.get) if dur else None
        ev.append([e.nome, e.inicio.toordinal(), e.fim.toordinal(),
                   dur[dm] if dm else None, dm.toordinal() if dm else None])
    ini = d0.toordinal() if (d1 - d0).days <= 120 else d1.toordinal() - 89
    return {"dias": [[d.toordinal(), dias[d], q1, m, q3] for d, q1, m, q3 in mov],
            "tr": [[t.desde.toordinal(), t.ate.toordinal(), t.preco] for t in trechos],
            "ev": ev, "capa": next((t.capa for t in reversed(trechos) if t.capa), None),
            "full": [d0.toordinal(), d1.toordinal()], "def": [ini, d1.toordinal()]}


def pagina(titulo: str, asin: str, trechos: list[Trecho], eventos: list[Evento], aviso: str = "") -> str:
    dados = _dados_js(trechos, eventos)
    atual = fatos(trechos, trechos[-1].ate)
    blocos = "".join(_bloco_evento(e, fatos_evento(trechos, e)) for e in eventos)
    js = JS.replace("__DADOS__", json.dumps(dados).replace("</", "<\\/")).replace("__BURACO__", str(BURACO))
    return (f'<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(titulo)}</title><style>{CSS}</style><body>"
            f'{f"<p><b>{html.escape(aviso)}</b></p>" if aviso else ""}'
            f"<h1>{html.escape(titulo)}</h1><small>ASIN {html.escape(asin)} · preços de "
            f"{_data(trechos[0].desde)} a {_data(trechos[-1].ate)}</small>"
            f'<div class="cs" style="margin:12px 0">{_cartoes_atuais(atual)}</div>{_aviso_dados(atual)}'
            f'<div id="graf-box"><noscript>O gráfico precisa de JavaScript; '
            f"os números abaixo funcionam sem ele.</noscript></div>"
            f'<div id="tip"></div>{_controles(eventos, dados)}'
            f"{f'<h2>Black Friday e outras promoções</h2>{blocos}' if blocos else ''}"
            f"<script>{js}</script></body></html>")
