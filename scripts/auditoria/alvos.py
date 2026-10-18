"""Tamanho dos alvos de toque. WCAG 2.5.8 (AA): 24×24 px, ou um círculo de 24 px centrado no alvo que não encosta no
de outro alvo (exceção de espaçamento); links dentro de texto ficam de fora. Também compara com a regra do MASTER.md
(>= 40 px em tela de toque; 44 px em campos e botões de ícone) e com os 44 pt das Apple HIG.
Emula toque (has_touch + is_mobile => pointer:coarse) em 375 px. Saída (em AUDIT_SAIDA): alvos.json."""
import json

from comum import SAIDA, abrir, ir, sync_playwright

MEDIR = r"""() => {
  const sel = 'a[href], button, input:not([type=hidden]), select, summary, [tabindex="0"]';
  const els = [...document.querySelectorAll(sel)].filter(e => { const s = getComputedStyle(e), r = e.getBoundingClientRect(); return r.width && r.height && s.visibility !== 'hidden' && !e.closest('[inert],.vh,.pular'); });
  const caixas = els.map(e => { const r = e.getBoundingClientRect(); return {e, x: r.left + r.width / 2 + scrollX, y: r.top + r.height / 2 + scrollY, w: r.width, h: r.height}; });
  const nome = e => (e.getAttribute('aria-label') || e.innerText || e.getAttribute('placeholder') || e.tagName).trim().replace(/\s+/g, ' ').slice(0, 40);
  const emTexto = e => e.tagName === 'A' && getComputedStyle(e).display === 'inline' && /^(P|LI|DD|SPAN)$/.test(e.parentElement.tagName);
  const out = [];
  caixas.forEach((c, i) => {
    if (emTexto(c.e)) return;
    const pequeno = c.w < 24 || c.h < 24;
    let espacado = true;
    // círculo de 24 px no centro: não pode encostar no retângulo de outro alvo nem no círculo de outro alvo pequeno
    if (pequeno) caixas.forEach((d, j) => {
      if (i === j || c.e.contains(d.e) || d.e.contains(c.e)) return;
      const dx = Math.max(Math.abs(c.x - d.x) - d.w / 2, 0), dy = Math.max(Math.abs(c.y - d.y) - d.h / 2, 0);
      const dPequeno = d.w < 24 || d.h < 24;
      if (Math.hypot(dx, dy) < 12 || (dPequeno && Math.hypot(c.x - d.x, c.y - d.y) < 24)) espacado = false;
    });
    out.push({nome: nome(c.e), el: c.e.tagName.toLowerCase() + (typeof c.e.className === 'string' && c.e.className ? '.' + c.e.className.trim().split(/\s+/).join('.') : ''), w: Math.round(c.w), h: Math.round(c.h),
      falha_2_5_8: pequeno && !espacado, abaixo_de_40: Math.min(c.w, c.h) < 40, abaixo_de_44: Math.min(c.w, c.h) < 44});
  });
  return {coarse: matchMedia('(pointer: coarse)').matches, alvos: out};
}"""
out = {}
with sync_playwright() as p:
    for tela in ("busca-texto", "livro-rico", "lista", "sobre", "inicio-antigo"):
        for toque, w in ((True, 375), (False, 1280)):
            b, ctx = abrir(p, largura=w, toque=toque, lista=tela in ("lista", "inicio-antigo"))
            pg = ctx.new_page()
            ir(pg, tela)
            if tela == "busca-texto":
                pg.click(".filtros-extra summary")
                pg.wait_for_timeout(200)
            r = pg.evaluate(MEDIR)
            uniq = {}
            for a in r["alvos"]:
                uniq.setdefault((a["el"], a["w"], a["h"]), dict(a, n=0))["n"] += 1
            r["alvos"] = sorted(uniq.values(), key=lambda a: min(a["w"], a["h"]))
            out[f"{tela}-{w}{'-toque' if toque else ''}"] = r
            print(tela, w, "coarse" if r["coarse"] else "", "2.5.8:", sum(a["falha_2_5_8"] for a in r["alvos"]), "<40:", sum(a["abaixo_de_40"] for a in r["alvos"]), flush=True)
            b.close()
(SAIDA / "alvos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
