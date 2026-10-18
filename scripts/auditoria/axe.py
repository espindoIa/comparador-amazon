"""axe-core 4.10.2 (arquivo em AUDIT_AXE, padrão data/auditoria/axe.min.js; fora do git) em cada tela e estado.
Regras: wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa e best-practice. Temas escuro (padrão) e claro; sistema claro.
Saída (em AUDIT_SAIDA): axe.json (por tela) e axe-resumo.json (por regra)."""
import json
import os
from pathlib import Path

from comum import BASE, SAIDA, TELAS, abrir, ir, sync_playwright

# baixe uma vez: curl -o data/auditoria/axe.min.js https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js
AXE = Path(os.environ.get("AUDIT_AXE", SAIDA / "axe.min.js")).read_text()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
RODAR = "async t => { const r = await axe.run(document, {runOnly: {type: 'tag', values: t}, resultTypes: ['violations','incomplete']});" \
        " const f = v => v.map(x => ({id: x.id, impact: x.impact, help: x.help, n: x.nodes.length, alvos: x.nodes.slice(0, 6).map(n => n.target.join(' ')), resumo: (x.nodes[0] || {}).failureSummary}));" \
        " return {violations: f(r.violations), incomplete: f(r.incomplete)}; }"


def estados(pg, nome):
    """Estados que não são uma tela com endereço próprio."""
    if nome == "carregando":
        pg.route("**/dados/indice-0.json*", lambda r: None)                      # nunca responde: fica o esqueleto
        pg.goto(BASE + "/?q=amor")
        pg.wait_for_selector(".esq .sk-row")
    elif nome == "erro":
        pg.route("**/dados/meta.json*", lambda r: r.fulfill(status=500, body="x"))
        pg.goto(BASE + "/")
        pg.wait_for_selector(".erro h1")
    elif nome == "toast":
        ir(pg, "livro-rico")
        pg.click("[data-salvar]")
        pg.wait_for_selector(".toast.on")
    elif nome == "filtros-abertos":
        ir(pg, "busca-texto")
        pg.click(".filtros-extra summary")
        pg.click('[data-acao="preco"]')
        pg.wait_for_selector("#de")
    elif nome == "alvo-erro":
        ir(pg, "lista")
        pg.click('[data-alvo]')
        pg.fill('.alvo-f input', '')
        pg.click('.alvo-f button[type=submit]')
        pg.wait_for_selector(".erro-campo")
    pg.wait_for_timeout(400)


EXTRA = ["carregando", "erro", "toast", "filtros-abertos", "alvo-erro"]
out, resumo = {}, {}
with sync_playwright() as p:
    for nome in list(TELAS) + EXTRA:
        for w in (1280, 375):
            for tema in ("dark", "light"):
                lista = nome in ("lista", "inicio-antigo", "alvo-erro")
                b, ctx = abrir(p, largura=w, esquema="light", tema=tema, lista=lista)
                pg = ctx.new_page()
                try:
                    if nome in TELAS:
                        ir(pg, nome)
                    else:
                        estados(pg, nome)
                    pg.add_script_tag(content=AXE)
                    r = pg.evaluate(RODAR, TAGS)
                except Exception as e:
                    r = {"erro": str(e)[:300]}
                chave = f"{nome}-{w}-{tema}"
                out[chave] = r
                for v in r.get("violations", []):
                    s = resumo.setdefault(v["id"], {"impact": v["impact"], "help": v["help"], "telas": {}, "exemplo": v["alvos"][:3], "resumo": v["resumo"]})
                    s["telas"][chave] = v["n"]
                print(chave, [(v["id"], v["n"]) for v in r.get("violations", [])] or r.get("erro"), flush=True)
                b.close()
(SAIDA / "axe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
(SAIDA / "axe-resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1))
