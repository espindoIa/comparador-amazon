"""Conferências finais: voltar do navegador (rolagem e foco), pílulas de subiu/caiu renderizadas na lista (sistema claro,
tema escuro), anel de foco do cartão da lista (R1) e aviso de preload sem uso. Saída (em AUDIT_SAIDA): conferencias.json."""
import json

from comum import BASE, LISTA, RICO, FORMATOS, VELHO, SAIDA, NAV, sync_playwright
from contraste import MEDIR  # noqa: E402  (reaproveita a medição; importar roda o contraste se for __main__ só)

out = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=NAV, args=["--no-sandbox"])
    # 1. voltar do navegador
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.goto(BASE + "/?q=harry%20potter"); pg.wait_for_selector("#res .row")
    pg.wait_for_function("!document.querySelector('#res .carregando')", timeout=60000)
    pg.evaluate("scrollTo(0, 1500)"); pg.wait_for_timeout(300)
    alvo = pg.evaluate("(() => { const r = [...document.querySelectorAll('#res a.row')].find(a => a.getBoundingClientRect().top > 100); return r.getAttribute('href'); })()")
    pg.click(f'#res a.row[href="{alvo}"]'); pg.wait_for_selector("#graf svg")
    pg.go_back(); pg.wait_for_selector("#res .row"); pg.wait_for_timeout(600)
    out["voltar do navegador (busca)"] = pg.evaluate("({y: scrollY, ativo: document.activeElement.id || document.activeElement.className, url: location.search})")
    pg.click("#res [data-watch]"); pg.wait_for_selector(".alvo-f input"); pg.go_back(); pg.wait_for_selector("#res .row"); pg.wait_for_timeout(600)
    out["voltar depois do sino"] = pg.evaluate("({y: scrollY, url: location.search})")
    ctx.close()
    # 3. pílulas de mudança e de alvo na lista, sistema claro + tema escuro (o padrão de quem usa o sistema claro)
    for esquema in ("light", "dark"):
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme=esquema)
        st = {"lista_v1": json.dumps(LISTA), "alvos_v1": json.dumps({RICO: 999999}),
              "vistos_v1": json.dumps({"a": {"d": 1, "p": {RICO: 1, FORMATOS: 999999, VELHO: 1}}})}
        ctx.add_init_script("try{localStorage.clear();" + "".join(f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in st.items()) + "}catch(e){}")
        pg = ctx.new_page()
        pg.goto(BASE + "/?lista"); pg.wait_for_selector("#lst .row"); pg.wait_for_timeout(500)
        r = pg.evaluate(MEDIR)
        out[f"lista com pílulas, sistema={esquema}, tema escuro"] = {"pilulas": pg.evaluate("[...document.querySelectorAll('.pill')].map(e => e.className + ': ' + e.innerText)"),
            "falhas": [f for f in r["falhas_texto"] if "pill" in f["el"]]}
        if esquema == "light":
            pg.screenshot(path=str(SAIDA / "conferencia-lista-pilulas-sistema-claro.png"))
            # 5. anel do cartão da lista ao chegar pelo Tab
            pg.evaluate("document.activeElement.blur()")
            for _ in range(30):
                pg.keyboard.press("Tab")
                if pg.evaluate("document.activeElement.classList.contains('esticar')"):
                    break
            out["R1: cartão da lista com foco pelo Tab"] = pg.evaluate("(() => { const a = document.activeElement, row = a.closest('.row'); return {link: a.className, anel_da_linha: getComputedStyle(row).outlineStyle + ' ' + getComputedStyle(row).outlineWidth, anel_do_link: getComputedStyle(a).outlineStyle}; })()")
            pg.screenshot(path=str(SAIDA / "conferencia-R1-foco-lista.png"))
        ctx.close()
    # 6. preload sem uso
    ctx = b.new_context()
    pg = ctx.new_page()
    msgs = []
    pg.on("console", lambda m: msgs.append(m.type + ": " + m.text))
    pg.goto(BASE + "/"); pg.wait_for_selector("#res .row"); pg.wait_for_timeout(4000)
    out["console"] = [m for m in msgs if "preload" in m.lower()]
    out["fontes baixadas"] = pg.evaluate("performance.getEntriesByType('resource').filter(e => /woff2/.test(e.name)).map(e => e.name.split('/').pop() + ' ' + e.transferSize + 'B')")
    out["fontes usadas"] = pg.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight)")
    b.close()
(SAIDA / "conferencias.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
