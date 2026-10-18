"""Tema: a emulação de prefers-color-scheme funciona? Qual tema abre? Os tokens se misturam? O tema salvo pisca?
Saída (em AUDIT_SAIDA): tema.json e capturas tema-*.png."""
import json

from comum import BASE, SAIDA, abrir, sync_playwright

TOKENS = ["--bg", "--sf", "--fg", "--mu", "--ac", "--dn", "--dns", "--up", "--ups", "--wr", "--wrs", "--evl", "--ev", "--capa", "--med", "--pri", "--prif"]
LER = "t => { const s = getComputedStyle(document.documentElement); return Object.fromEntries(t.map(k => [k, s.getPropertyValue(k).trim()])); }"
out = {}
with sync_playwright() as p:
    for esquema in ("light", "dark"):
        for tema in (None, "light", "dark"):
            b, ctx = abrir(p, esquema=esquema, tema=tema)
            pg = ctx.new_page()
            pg.goto(BASE + "/")
            pg.wait_for_selector("#res .row")
            chave = f"sistema={esquema} tema_salvo={tema}"
            out[chave] = {
                "prefers-color-scheme: dark casa": pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches"),
                "data-theme": pg.evaluate("document.documentElement.dataset.theme"),
                "color-scheme computado": pg.evaluate("getComputedStyle(document.documentElement).colorScheme"),
                "tokens": pg.evaluate(LER, TOKENS),
                "meta theme-color ativo": pg.evaluate("[...document.querySelectorAll('meta[name=theme-color]')].filter(m => matchMedia(m.media).matches).map(m => m.content)"),
            }
            b.close()
    # botão #tema: estado e nome acessível antes e depois do clique
    b, ctx = abrir(p, esquema="light")
    pg = ctx.new_page()
    pg.goto(BASE + "/")
    pg.wait_for_selector("#res .row")
    attrs = "() => { const b = document.querySelector('#tema'); return {label: b.getAttribute('aria-label'), pressed: b.getAttribute('aria-pressed'), tema: document.documentElement.dataset.theme, img: b.querySelector('img').getAttribute('src')}; }"
    antes = pg.evaluate(attrs)
    pg.click("#tema")
    depois = pg.evaluate(attrs)
    out["botao #tema"] = {"antes": antes, "depois_do_clique": depois, "aria_snapshot": pg.locator("header").aria_snapshot()}
    b.close()
    # piscada: tema claro salvo, app.js atrasado 1,5 s (rede lenta); o que aparece antes de o script rodar?
    b, ctx = abrir(p, esquema="light", tema="light")
    pg = ctx.new_page()

    def atrasar(route):
        import time
        time.sleep(1.5)
        route.continue_()
    pg.route("**/app.js*", atrasar)
    pg.goto(BASE + "/", wait_until="commit")
    pg.wait_for_selector(".hdr", state="attached")
    pg.wait_for_timeout(500)
    out["piscada"] = {"data-theme antes do app.js": pg.evaluate("document.documentElement.dataset.theme || null"),
                      "fundo antes do app.js": pg.evaluate("getComputedStyle(document.body).backgroundColor")}
    pg.screenshot(path=str(SAIDA / "tema-piscada-antes-do-app.png"))
    pg.wait_for_selector("#res .row", timeout=60000)
    out["piscada"]["data-theme depois"] = pg.evaluate("document.documentElement.dataset.theme")
    out["piscada"]["fundo depois"] = pg.evaluate("getComputedStyle(document.body).backgroundColor")
    pg.screenshot(path=str(SAIDA / "tema-piscada-depois-do-app.png"))
    b.close()
(SAIDA / "tema.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
