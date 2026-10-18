"""Movimento: inventário das transições e animações (estilo computado e document.getAnimations() durante a interação),
custo com a CPU 4× mais lenta (CDP Emulation.setCPUThrottlingRate): long animation frames, layout shift e latência
de interação (Event Timing API), e o que muda com prefers-reduced-motion: reduce. Saída (em AUDIT_SAIDA): motion.json."""
import json

from comum import BASE, RICO, SAIDA, abrir, ir, sync_playwright

INVENTARIO = r"""() => { const m = {};
  for (const el of document.querySelectorAll('*')) {
    for (const pseudo of [null, '::after']) {
      const s = getComputedStyle(el, pseudo);
      const t = s.transitionProperty, d = s.transitionDuration, a = s.animationName;
      const nome = el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '') + (pseudo || '');
      if (d.split(',').some(x => parseFloat(x) > 0)) m['T ' + nome] = {prop: t, dur: d, easing: s.transitionTimingFunction};
      if (a !== 'none') m['A ' + nome] = {anim: a, dur: s.animationDuration, easing: s.animationTimingFunction, iter: s.animationIterationCount};
    }
  } return m; }"""
ANIMS = "() => document.getAnimations().map(a => ({tipo: a.constructor.name, nome: a.animationName || a.transitionProperty, alvo: (a.effect && a.effect.target) ? a.effect.target.tagName.toLowerCase() + '.' + a.effect.target.className : '', dur: a.effect && a.effect.getTiming().duration, easing: a.effect && a.effect.getTiming().easing, estado: a.playState}))"
OBS = r"""() => { window.__m = {loaf: [], cls: [], ev: []};
  try { new PerformanceObserver(l => l.getEntries().forEach(e => __m.loaf.push({dur: Math.round(e.duration), bloqueio: Math.round(e.blockingDuration), t: Math.round(e.startTime), scripts: (e.scripts || []).slice(0, 2).map(s => (s.sourceFunctionName || '') + '@' + (s.sourceURL || '').split('/').pop() + ':' + Math.round(s.duration))}))).observe({type: 'long-animation-frame', buffered: true}); } catch (e) { __m.loaf = 'sem suporte'; }
  new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) __m.cls.push({v: +e.value.toFixed(4), t: Math.round(e.startTime), fontes: (e.sources || []).slice(0, 3).map(s => s.node ? (s.node.className || s.node.nodeName) : '?')}); })).observe({type: 'layout-shift', buffered: true});
  new PerformanceObserver(l => l.getEntries().forEach(e => { if (e.interactionId) __m.ev.push({tipo: e.name, dur: Math.round(e.duration), entrada: Math.round(e.processingStart - e.startTime), processo: Math.round(e.processingEnd - e.processingStart), alvo: e.target ? (e.target.id || e.target.className || e.target.tagName) : ''}); })).observe({type: 'event', durationThreshold: 16, buffered: true}); }"""

out = {"inventario": {}, "durante": {}, "custo_cpu4x": {}, "reduzido": {}}
with sync_playwright() as p:
    # inventário estático por tela
    for tela in ("busca-texto", "livro-rico", "lista", "inicio-antigo"):
        b, ctx = abrir(p, lista=tela in ("lista", "inicio-antigo"))
        pg = ctx.new_page(); ir(pg, tela)
        out["inventario"][tela] = pg.evaluate(INVENTARIO)
        b.close()
    # animações em curso durante interações
    b, ctx = abrir(p)
    pg = ctx.new_page()
    pg.goto(BASE + "/?q=amor"); pg.wait_for_selector(".giro", timeout=30000)
    out["durante"]["buscando (giro)"] = pg.evaluate(ANIMS)
    ir(pg, "livro-rico")
    pg.hover(".l-cab .acoes .btn.pri"); pg.mouse.down(); out["durante"]["botão pressionado"] = pg.evaluate(ANIMS); pg.mouse.up()
    pg.click("[data-salvar]"); pg.wait_for_timeout(30); out["durante"]["aviso aparecendo"] = pg.evaluate(ANIMS)
    pg.click('[data-per="0"]') if pg.locator('[data-per="0"]').count() else None
    pg.wait_for_timeout(30); out["durante"]["troca de período do gráfico"] = pg.evaluate(ANIMS)
    pg.click("#tema"); pg.wait_for_timeout(30); out["durante"]["troca de tema"] = pg.evaluate(ANIMS)
    pg.click('[data-acao="voltar"]'); pg.wait_for_timeout(30); out["durante"]["troca de tela (voltar)"] = pg.evaluate(ANIMS)
    b.close()
    # custo com a CPU 4× mais lenta: carga da busca e interações principais
    for largura in (375, 1280):
        b, ctx = abrir(p, largura=largura, lista=True)
        pg = ctx.new_page()
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        pg.add_init_script(OBS.replace("() => {", "(() => {", 1) + ")()")
        pg.goto(BASE + "/?q=amor")
        pg.wait_for_selector("#res .row", timeout=120000)
        primeiro = pg.evaluate("performance.now()")
        pg.wait_for_function("!document.querySelector('#res .carregando')", timeout=180000)
        completo = pg.evaluate("performance.now()")
        # digitar na busca enquanto o vocabulário é montado
        pg.click("#q"); pg.keyboard.press("End"); pg.keyboard.type(" de verao", delay=120); pg.wait_for_timeout(1500)
        pg.click(".filtros-extra summary"); pg.click('[data-fam="k"]'); pg.wait_for_timeout(800)
        pg.select_option("#ord", "preco"); pg.wait_for_timeout(800)
        pg.click('[data-view="grade"]'); pg.wait_for_timeout(500)
        pg.click("#res .row"); pg.wait_for_selector("#graf svg", timeout=60000); pg.wait_for_timeout(800)
        if pg.locator('[data-per="0"]').count():
            pg.click('[data-per="0"]'); pg.wait_for_timeout(400)
        pg.click("#tema"); pg.wait_for_timeout(500)
        pg.click("[data-salvar]"); pg.wait_for_timeout(500)
        m = pg.evaluate("window.__m")
        evs = sorted(m["ev"], key=lambda e: -e["dur"])
        out["custo_cpu4x"][str(largura)] = {"primeiros_resultados_ms": round(primeiro), "indice_completo_ms": round(completo),
            "loaf_n": len(m["loaf"]) if isinstance(m["loaf"], list) else m["loaf"], "loaf_maiores": sorted(m["loaf"], key=lambda e: -e["dur"])[:8] if isinstance(m["loaf"], list) else [],
            "cls_total": round(sum(x["v"] for x in m["cls"]), 4), "cls": m["cls"][:10], "interacoes_mais_lentas": evs[:10]}
        b.close()
    # movimento reduzido
    b, ctx = abrir(p, movimento="reduce")
    pg = ctx.new_page()
    pg.route("**/dados/indice-1.json*", lambda r: None)
    pg.goto(BASE + "/?q=amor"); pg.wait_for_selector(".giro", timeout=30000)
    out["reduzido"]["animações com reduce (buscando)"] = pg.evaluate(ANIMS)
    out["reduzido"]["scroll-behavior"] = pg.evaluate("getComputedStyle(document.documentElement).scrollBehavior")
    out["reduzido"]["transição de .toast"] = pg.evaluate("getComputedStyle(document.querySelector('.toast')).transitionDuration")
    out["reduzido"]["transição de .resultado-livro"] = pg.evaluate("getComputedStyle(document.querySelector('.resultado-livro') || document.body).transitionDuration")
    b.close()
    b, ctx = abrir(p, movimento="reduce")
    pg = ctx.new_page(); pg.route("**/dados/indice-0.json*", lambda r: None)
    pg.goto(BASE + "/?q=amor"); pg.wait_for_selector(".sk-row")
    out["reduzido"]["esqueleto com reduce"] = pg.evaluate(ANIMS)
    b.close()
(SAIDA / "motion.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps({k: out[k] for k in ("durante", "custo_cpu4x", "reduzido")}, ensure_ascii=False, indent=1)[:9000])
