"""Espaçamento de texto (WCAG 1.4.12), cores forçadas (forced-colors: active), zoom de 200% (página de 640 px com
escala 2) e tamanho de fonte do navegador (o site usa px). Saída (em AUDIT_SAIDA): extras.json e extra-*.png."""
import json

from comum import SAIDA, abrir, ir, sync_playwright

ESPACO = "*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}p{margin-bottom:2em!important}"
CORTADO = r"""() => { const r = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden' || el.closest('.vh')) continue;
    if (!/(hidden|clip)/.test(s.overflow + s.overflowX + s.overflowY)) continue;
    if (s.webkitLineClamp !== 'none' || s.textOverflow === 'ellipsis') continue;           // corte de propósito
    if (!(el.innerText || '').trim()) continue;
    if (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2) r.push(el.tagName.toLowerCase() + '.' + el.className + ' "' + el.innerText.trim().slice(0, 30) + '"');
  }
  // sobreposição: texto que passa da altura fixa do controle
  for (const el of document.querySelectorAll('.btn,.chip,.pill,.fmt,.seg button,.leg button,.badge,select')) {
    const b = el.getBoundingClientRect(); if (!b.height) continue;
    if (el.scrollHeight > el.clientHeight + 2) r.push('estoura ' + el.tagName.toLowerCase() + '.' + el.className + ' "' + (el.innerText || '').trim().slice(0, 25) + '"');
  }
  return [...new Set(r)]; }"""
out = {}
with sync_playwright() as p:
    for tela in ("busca-texto", "livro-rico", "lista"):
        for w in (375, 1280):
            b, ctx = abrir(p, largura=w, lista=tela == "lista")
            pg = ctx.new_page(); ir(pg, tela)
            antes = pg.evaluate(CORTADO)
            pg.add_style_tag(content=ESPACO); pg.wait_for_timeout(300)
            depois = pg.evaluate(CORTADO)
            out[f"1.4.12 {tela} {w}"] = {"novos_cortes": [x for x in depois if x not in antes]}
            pg.screenshot(path=str(SAIDA / f"extra-espaco-{tela}-{w}.png"), full_page=False)
            b.close()
    for tela in ("busca-texto", "livro-rico", "lista"):
        b, ctx = abrir(p, largura=1280, cores_forcadas="active", lista=tela == "lista")
        pg = ctx.new_page(); ir(pg, tela)
        if tela == "busca-texto":
            pg.click(".filtros-extra summary"); pg.click('[data-fam="k"]'); pg.wait_for_timeout(300)
        pg.screenshot(path=str(SAIDA / f"extra-forced-{tela}.png"))
        out[f"forced {tela}"] = pg.evaluate("""() => ({
          view_ligado: (() => { const e = document.querySelector('.view-switch [aria-pressed=true]'); return e ? getComputedStyle(e).outlineStyle + ' ' + getComputedStyle(e).backgroundColor : null; })(),
          chip_ligado: (() => { const e = document.querySelector('.chip[aria-pressed=true]'); return e ? getComputedStyle(e).outlineStyle : null; })(),
          imgs_icone: [...document.querySelectorAll('.header-tools img, .enviar img, .busca-dica img')].map(i => i.getAttribute('src').split('?')[0])})""")
        b.close()
    b, ctx = abrir(p, largura=640, altura=450)
    pg = ctx.new_page(); ir(pg, "livro-rico")
    pg.screenshot(path=str(SAIDA / "extra-zoom200-livro.png"))
    out["zoom 200% (640px)"] = pg.evaluate("({scrollW: document.documentElement.scrollWidth, hdr: document.querySelector('.hdr').getBoundingClientRect().height, janela: innerHeight})")
    # tamanho de fonte do navegador: raiz em 32px (como 'muito grande'); o texto acompanha?
    pg.add_style_tag(content="html{font-size:32px!important}")
    out["fonte do navegador 2x"] = pg.evaluate("getComputedStyle(document.querySelector('.l-cab h1')).fontSize + ' / corpo ' + getComputedStyle(document.body).fontSize")
    b.close()
(SAIDA / "extras.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
