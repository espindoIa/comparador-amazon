"""Teclado e foco: ordem do Tab, anel visível, foco encoberto (2.4.11), destino do foco depois de cada redesenho,
dicas (.hint) e Esc (1.4.13). Saída (em AUDIT_SAIDA): foco.json e capturas foco-*.png."""
import json

from comum import BASE, RICO, SAIDA, abrir, ir, sync_playwright

ATIVO = r"""() => { const e = document.activeElement; if (!e || e === document.body) return {el: 'body'};
  const s = getComputedStyle(e), r = e.getBoundingClientRect();
  const anel = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
  // encoberto: o centro e os cantos do controle mostram outro elemento por cima (2.4.11 pede que não fique todo escondido)
  const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 2, r.top + 2], [r.right - 2, r.bottom - 2]];
  const cob = pts.filter(([x, y]) => { const t = document.elementFromPoint(x, y); return t && !e.contains(t) && !t.contains(e); }).length;
  const quem = (() => { const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return t && !e.contains(t) ? (t.closest('.toast') ? 'toast' : t.tagName.toLowerCase() + '.' + t.className) : null; })();
  return {el: e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '') + (e.id ? '#' + e.id : ''),
    nome: (e.getAttribute('aria-label') || e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 50), anel, cantos_cobertos: cob, por: quem,
    dentro_da_janela: r.bottom > 0 && r.top < innerHeight}; }"""
out = {}


def tabs(pg, n):
    seq = []
    for _ in range(n):
        pg.keyboard.press("Tab")
        seq.append(pg.evaluate(ATIVO))
    return seq


with sync_playwright() as p:
    b, ctx = abrir(p, largura=1280)
    pg = ctx.new_page()
    ir(pg, "busca-texto")
    pg.wait_for_function("!document.querySelector('#res .carregando')", timeout=60000)
    pg.evaluate("document.activeElement.blur(); scrollTo(0,0)")
    seq = tabs(pg, 22)
    out["busca: primeiros 22 Tabs"] = seq
    out["busca: paradas por resultado"] = pg.evaluate("[...document.querySelector('#res .lst li').querySelectorAll('a,button')].map(e => e.tagName + ' ' + (e.getAttribute('aria-label') || e.innerText.trim().slice(0, 30)))")
    out["busca: sem anel"] = [s for s in seq if not s.get("anel") and s["el"] != "body"]
    # pular para o conteúdo
    pg.goto(BASE + "/?q=harry%20potter"); pg.wait_for_selector("#res .row")
    pg.keyboard.press("Tab")
    out["pular: 1º Tab"] = pg.evaluate(ATIVO)
    pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
    out["pular: depois do Enter"] = pg.evaluate(ATIVO)
    # dica: foca a #tema, Esc, a dica continua visível?
    pg.focus("#tema"); pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Tab"); pg.wait_for_timeout(200)
    vis = "() => getComputedStyle(document.querySelector('#tema'), '::after').opacity"
    out["dica: opacidade com foco"] = pg.evaluate(vis)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    out["dica: opacidade depois do Esc"] = pg.evaluate(vis)
    # filtros: abre o details, liga e desliga um chip; para onde vai o foco? o details continua aberto?
    pg.click(".filtros-extra summary")
    pg.focus('[data-fam="k"]'); pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
    out["filtros: depois de ligar Kindle"] = {"ativo": pg.evaluate(ATIVO), "aberto": pg.evaluate("document.querySelector('.filtros-extra').open")}
    pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
    out["filtros: depois de desligar Kindle"] = {"ativo": pg.evaluate(ATIVO), "aberto": pg.evaluate("document.querySelector('.filtros-extra').open")}
    # filtros abertos e a pessoa digita mais uma letra na busca
    pg.click(".filtros-extra summary") if not pg.evaluate("document.querySelector('.filtros-extra').open") else None
    pg.click("#q"); pg.keyboard.type(" e"); pg.wait_for_timeout(800)
    out["filtros: abertos e digitar na busca"] = {"aberto_depois": pg.evaluate("document.querySelector('.filtros-extra').open")}
    # troca de tela: resultado -> livro -> voltar
    pg.goto(BASE + "/?q=harry%20potter"); pg.wait_for_selector("#res .row")
    pg.wait_for_function("!document.querySelector('#res .carregando')", timeout=60000)
    pg.focus("#res .row"); pg.keyboard.press("Enter"); pg.wait_for_selector("#graf svg"); pg.wait_for_timeout(300)
    out["livro: foco ao abrir"] = pg.evaluate(ATIVO)
    out["livro: Tabs"] = tabs(pg, 14)
    pg.click('[data-acao="voltar"]'); pg.wait_for_selector("#res .row"); pg.wait_for_timeout(400)
    out["voltar: foco"] = pg.evaluate(ATIVO)
    # sino no resultado: muda de tela?
    pg.click("#res [data-watch]"); pg.wait_for_timeout(1500)
    out["sino na busca: endereço e foco"] = {"url": pg.url.replace(BASE, ""), "ativo": pg.evaluate(ATIVO)}
    b.close()

    # toast cobrindo o foco (375 px)
    b, ctx = abrir(p, largura=375, altura=700)
    pg = ctx.new_page()
    ir(pg, "livro-rico")
    pg.click("[data-salvar]"); pg.wait_for_selector(".toast.on")
    cobertos = []
    for _ in range(40):
        pg.keyboard.press("Tab")
        a = pg.evaluate(ATIVO)
        if a.get("por") == "toast":
            cobertos.append(a)
            pg.screenshot(path=str(SAIDA / "foco-coberto-pelo-toast.png"))
            break
    out["toast: controle com foco coberto pelo aviso"] = cobertos
    out["toast: aria"] = pg.evaluate("(() => { const t = document.querySelector('#toast'); return {role: t.getAttribute('role'), live: t.getAttribute('aria-live'), texto: t.innerText}; })()")
    b.close()

    # lista: remover e desfazer
    b, ctx = abrir(p, largura=1280, lista=True)
    pg = ctx.new_page()
    ir(pg, "lista")
    pg.click("[data-remover]"); pg.wait_for_timeout(600)
    out["lista: foco depois de remover"] = pg.evaluate(ATIVO)
    pg.keyboard.press("Control+z"); pg.wait_for_timeout(600)
    out["lista: foco depois de Ctrl+Z"] = pg.evaluate(ATIVO)
    out["lista: aria_snapshot"] = pg.locator("#app").aria_snapshot()[:2500]
    b.close()

    b, ctx = abrir(p, largura=1280)
    pg = ctx.new_page()
    ir(pg, "livro-rico")
    out["livro: aria_snapshot"] = pg.locator("#app").aria_snapshot()[:4000]
    pg.focus(".graf"); pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(200)
    out["gráfico: região viva depois de ←"] = pg.evaluate("document.querySelector('#graf [aria-live]').textContent")
    b.close()
(SAIDA / "foco.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
for k, v in out.items():
    if "aria_snapshot" in k or "Tabs" in k:
        continue
    print(k, "=>", json.dumps(v, ensure_ascii=False)[:600])
