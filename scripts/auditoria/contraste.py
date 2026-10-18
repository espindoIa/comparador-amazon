"""Contraste medido nas cores computadas da página (não nos tokens): todo texto visível contra o fundo efetivo
(primeiro ancestral com fundo opaco, compondo o alfa), e o contorno dos campos contra o fundo em volta.
Limite: 4,5:1; 3:1 para texto grande (>= 24 px, ou >= 18,66 px em negrito) e para contorno de campo (WCAG 1.4.3, 1.4.11).
Combinações: tema escuro e claro × sistema claro e escuro (os tokens que a referencia.css não redefine seguem o sistema).
Saída (em AUDIT_SAIDA): contraste.json."""
import json

from comum import SAIDA, abrir, ir, sync_playwright

MEDIR = r"""() => {
  const rgba = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1]; };
  const lum = c => { const f = x => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; }; return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
  const razao = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  const sobre = (c, f) => [0, 1, 2].map(i => c[i] * c[3] + f[i] * (1 - c[3])).concat(1);
  function fundo(el) {
    const pilha = []; let imagem = false;
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none' && !/^url/.test(s.backgroundImage) && e !== document.body) imagem = true;
      const c = rgba(s.backgroundColor); if (c && c[3] > 0) { pilha.push(c); if (c[3] >= 1) break; }
    }
    let f = [255, 255, 255, 1];
    for (let i = pilha.length - 1; i >= 0; i--) f = sobre(pilha[i], f);
    return {f, imagem};
  }
  const nome = el => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '') + (el.parentElement ? ' < ' + el.parentElement.tagName.toLowerCase() + (typeof el.parentElement.className === 'string' && el.parentElement.className.trim() ? '.' + el.parentElement.className.trim().split(/\s+/)[0] : '') : '');
  const texto = [], vistos = {};
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const t = w.currentNode; if (!t.textContent.trim()) continue;
    const el = t.parentElement; if (!el || el.closest('.vh,script,style,noscript,[hidden],[inert]')) continue;
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'text') continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= +getComputedStyle(e).opacity;
    let c = rgba(el.tagName.toLowerCase() === 'text' ? s.fill : s.color); if (!c) continue;
    const {f, imagem} = fundo(el); c = sobre([c[0], c[1], c[2], c[3] * op], f);
    const px = parseFloat(s.fontSize), negrito = +s.fontWeight >= 700, grande = px >= 24 || (px >= 18.66 && negrito);
    const k = razao(c, f), lim = grande ? 3 : 4.5;
    const chave = nome(el) + ' ' + s.color + ' / ' + f.map(Math.round).slice(0, 3).join(',');
    if (vistos[chave]) { vistos[chave].n++; continue; }
    vistos[chave] = {el: nome(el), texto: t.textContent.trim().slice(0, 30), cor: s.color, fundo: 'rgb(' + f.map(Math.round).slice(0, 3).join(',') + ')', px, razao: +k.toFixed(2), limite: lim, passa: k >= lim, fundo_com_imagem: imagem, n: 1};
    texto.push(vistos[chave]);
  }
  // pseudo-elemento das dicas (.hint::after), que é texto visível ao passar o mouse ou focar
  const dicas = [...document.querySelectorAll('.hint')].slice(0, 1).map(el => { const s = getComputedStyle(el, '::after'); const c = rgba(s.color), f = rgba(s.backgroundColor); return {el: 'dica .hint::after', px: parseFloat(s.fontSize), razao: c && f ? +razao(c, f).toFixed(2) : null}; });
  // contorno de campos e controles (1.4.11)
  const campos = [];
  for (const el of document.querySelectorAll('input:not([type=hidden]), select, .chip, .view-switch, .seg, .leg button, .fmt, .btn:not(.pri):not(.gh)')) {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect(); if (!r.width || s.visibility === 'hidden') continue;
    const b = rgba(s.borderTopColor); if (!b || parseFloat(s.borderTopWidth) === 0) continue;
    const dentro = rgba(s.backgroundColor), {f} = fundo(el.parentElement);
    const k = razao(sobre(b, f), f);
    campos.push({el: nome(el), borda: s.borderTopColor, fundo_em_volta: 'rgb(' + f.map(Math.round).slice(0, 3).join(',') + ')', razao: +k.toFixed(2), passa: k >= 3, fundo_proprio_contrasta: dentro && dentro[3] ? +razao(sobre(dentro, f), f).toFixed(2) : null});
  }
  const unicos = {}; campos.forEach(c => { unicos[c.el + c.borda + c.fundo_em_volta] = c; });
  return {falhas_texto: texto.filter(x => !x.passa), n_pares_texto: texto.length, dicas, campos: Object.values(unicos)};
}"""

PREP = {
    "busca-texto": lambda pg: (pg.click(".filtros-extra summary"), pg.click('[data-acao="preco"]'), pg.wait_for_selector("#de")),
    "livro-rico": lambda pg: (pg.click('[data-op="med"]') if pg.locator('[data-op="med"]').count() else None),
    "livro-velho": None, "lista": None, "sobre": None, "inicio-antigo": None, "busca-vazia": None, "404": None,
}
if __name__ == "__main__":
    out = {}
    with sync_playwright() as p:
        for tela, prep in PREP.items():
            for esquema in ("light", "dark"):
                for tema in ("dark", "light"):
                    for w in ((1280, 375) if tela.startswith(("livro", "busca", "lista")) else (1280,)):
                        b, ctx = abrir(p, largura=w, esquema=esquema, tema=tema, lista=tela in ("lista", "inicio-antigo"))
                        pg = ctx.new_page()
                        ir(pg, tela)
                        if prep:
                            prep(pg)
                            pg.wait_for_timeout(300)
                        r = pg.evaluate(MEDIR)
                        chave = f"{tela}-{w}-tema={tema}-sistema={esquema}"
                        out[chave] = r
                        print(chave, len(r["falhas_texto"]), "falhas de", r["n_pares_texto"], "| campos < 3:1:", sum(not c["passa"] for c in r["campos"]), flush=True)
                        b.close()
    (SAIDA / "contraste.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
