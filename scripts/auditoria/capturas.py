"""Capturas de cada tela nas larguras e nos temas, e o que sai da janela na horizontal.
Uso: python capturas.py [todas|chave]   (padrão: as telas principais em todas as larguras e o resto em 375 e 1280)
Saída (em AUDIT_SAIDA): cap/<tela>-<largura>-<tema>.png e capturas.json."""
import json
import sys

from comum import LARGURAS, SAIDA, TELAS, abrir, ir, sync_playwright

PASTA = SAIDA / "cap"
PASTA.mkdir(exist_ok=True)
PRINCIPAIS = ["busca-texto", "livro-rico", "lista"]
FORA = """() => { const W = innerWidth, r = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none') continue;
    const b = el.getBoundingClientRect(); if (!b.width || !b.height) continue;
    if (b.right > W + 1 && !el.closest('.estante,.chips,.seg,.vh,.pular,.toast')) r.push({el: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''), right: Math.round(b.right), texto: (el.innerText || '').trim().slice(0, 40)});
  }
  return {scrollWidth: document.documentElement.scrollWidth, innerWidth: W, fora: r.slice(0, 15), total: r.length}; }"""

planos = []
for tela in TELAS:
    larguras = LARGURAS if tela in PRINCIPAIS else [375, 1280]
    for w in larguras:
        for tema in ("dark", "light"):
            planos.append((tela, w, tema))
if len(sys.argv) > 1 and sys.argv[1] != "todas":
    planos = [x for x in planos if x[0] == sys.argv[1]]

out = {}
with sync_playwright() as p:
    for tela, w, tema in planos:
        b, ctx = abrir(p, largura=w, altura=900, esquema="light", tema=tema, lista=TELAS[tela][2] or tela.startswith("inicio"))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        try:
            ir(pg, tela)
        except Exception as e:  # registra e segue
            out[f"{tela}-{w}-{tema}"] = {"erro": str(e)[:200]}
            b.close()
            continue
        pg.screenshot(path=str(PASTA / f"{tela}-{w}-{tema}.png"), full_page=True)
        info = pg.evaluate(FORA)
        info["erros_js"] = erros
        out[f"{tela}-{w}-{tema}"] = info
        b.close()
        print(tela, w, tema, info["total"], "fora;", info["scrollWidth"], flush=True)
(SAIDA / "capturas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
