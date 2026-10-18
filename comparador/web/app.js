/* App de página única: início, busca, página do livro, minha lista e "como funciona".
 * Endereços: ./  ./?q=…  ./?livro=ASIN  ./?lista  ./?lista=ASIN,ASIN (lista compartilhada)  ./?sobre
 * Dados em dados/*.json, gerados por `python -m comparador site` (formato descrito em site.py). */
(function () {
  'use strict';
  var L = window.Livro, Lista = window.Lista, Busca = window.Busca, Recomenda = window.Recomenda, esc = L.esc, brl = L.brl;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var app = $('#app'), q = $('#q');
  var CAPA = 'https://m.media-amazon.com/images/I/';
  var FAMILIAS = [['f', 'Livro físico'], ['k', 'Kindle'], ['a', 'Audiolivro']];

  // ---------- ícones ----------
  var IC = {
    voltar: '<path d="M15 18l-6-6 6-6"/>', ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    salvar: '<path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>', x: '<path d="M18 6L6 18M6 6l12 12"/>',
    share: '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13"/>', baixo: '<path d="M6 9l6 6 6-6"/>',
    busca: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>', queda: '<path d="M3 7l6 6 4-4 8 8M21 11v6h-6"/>',
    alerta: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/>', estrela: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    dir: '<path d="M9 18l6-6-6-6"/>', livro: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5V21h16"/>'
  };
  // Feather icon paths (MIT), matching the reference line icon family.
  IC.coracao = '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z"/>';
  IC.sino = '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>';
  IC.grafico = '<path d="M4 13h3v8H4zM10 8h3v13h-3zM16 3h3v18h-3z"/>';
  IC.grade = '<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>';
  IC.lista = '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>';
  function ic(n, c) { return '<svg class="i' + (c ? ' ' + c : '') + '" viewBox="0 0 24 24" aria-hidden="true">' + IC[n] + '</svg>'; }

  // ---------- dados ----------
  var norm = Busca.normalizar;
  function familia(f) { return /Kindle/.test(f || '') ? 'k' : /^(a|á)udiolivro|^audible/i.test(f || '') ? 'a' : 'f'; }
  function json(url) { return fetch(url).then(function (r) { if (!r.ok) throw new Error(url + ': ' + r.status); return r.json(); }); }
  var META = fetch('dados/meta.json', { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error('meta'); return r.json(); });
  var V = META.then(function (m) { return '?v=' + encodeURIComponent(m.gerado_em || ''); });
  var EVENTOS = V.then(function (v) { return json('dados/eventos.json' + v); }).catch(function () { return []; });
  var meta = null, IDX = null, idx = null, DEST = null;

  // Obras do índice (formato em site.py). Tabelas: fmt (formatos), gen ([nó, nome]), idi (idiomas).
  function novoIdx(d) {
    var x = { obras: [], porAsin: {}, hoje: d.hoje, fmt: d.fmt, fam: d.fmt.map(familia), gen: d.gen, idi: d.idi,
      genPorNo: {}, temMC: false, temAv: false, partes: d.partes || 1, carregadas: 0, completo: false, falhou: false };
    d.gen.forEach(function (g, i) { x.genPorNo[g[0]] = i; });
    return x;
  }
  function lerObras(x, linhas, de, ate) {
    for (var i = de || 0, fim = ate == null ? linhas.length : ate; i < fim; i++) {
      var r = linhas[i], es = r[8];
      var o = Busca.preparar({ t: r[0], autor: r[1], img: r[2], ano: r[3], idioma: r[4] ? x.idi[r[4] - 1] : '', gen: r[5], nota: r[6], av: r[7], eds: [] });
      if (o.av) x.temAv = true;
      for (var j = 0; j < es.length; j++) {
        var e = es[j], ed = { asin: e[0], fmt: x.fmt[e[1]], fam: x.fam[e[1]], preco: e[2], capa: e[3], idade: e[4], mc: e[5], menor: e[6], o: o };
        if (ed.mc) x.temMC = true;
        o.eds.push(ed); x.porAsin[ed.asin] = ed;
      }
      x.obras.push(o);
    }
  }
  // O índice vem em partes, das obras mais avaliadas para as menos: a busca começa com a primeira parte e é
  // refeita a cada parte que chega. indice() espera só a primeira; indiceCompleto(), todas.
  function carregarIndice() {
    IDX = V.then(function (v) {
      return json('dados/indice-0.json' + v).then(function (d) {
        var x = novoIdx(d);
        lerObras(x, d.o); x.carregadas = 1; x.completo = x.partes <= 1; idx = x;
        x.pronto = x.completo ? Promise.resolve(x) : proximaParte(x, v, 1, 0);
        // com tudo carregado, monta (aos poucos) o vocabulário que corrige erros de digitação
        x.pronto.then(function () { setTimeout(function () { Busca.vocabularioAosPoucos(x.obras); }, 500); });
        return x;
      });
    });
    IDX.catch(function () { IDX = null; });
    return IDX;
  }
  // lê as obras em fatias, com pausas entre elas, para a página não travar enquanto a pessoa digita
  function lerAosPoucos(x, linhas) {
    return new Promise(function (ok) {
      var i = 0;
      (function fatia() {
        var t0 = performance.now();
        while (i < linhas.length && performance.now() - t0 < 8) { var fim = Math.min(i + 200, linhas.length); lerObras(x, linhas, i, fim); i = fim; }
        if (i < linhas.length) setTimeout(fatia, 0); else ok();
      })();
    });
  }
  function proximaParte(x, v, n, tentativa) {
    return json('dados/indice-' + n + '.json' + v).then(function (d) {
      return lerAosPoucos(x, d.o).then(function () {
        x.carregadas = n + 1; x.completo = x.carregadas >= x.partes;
        chegouParte();
        return x.completo ? x : proximaParte(x, v, n + 1, 0);
      });
    }, function () {
      if (tentativa < 1) return new Promise(function (ok) { setTimeout(ok, 2000); }).then(function () { return proximaParte(x, v, n, 1); });
      x.completo = true; x.falhou = true; chegouParte(); return x;     // segue com o que chegou, e avisa na busca
    });
  }
  function indice() { return IDX || carregarIndice(); }
  function indiceCompleto() { return indice().then(function (x) { return x.pronto; }); }
  var tParte = null;
  function chegouParte() {
    clearTimeout(tParte);
    tParte = setTimeout(function () { if (rotaAtual && rotaAtual.v === 'busca' && $('#res')) busca(false, true); }, 30);
  }
  // o que a página inicial mostra, num arquivo pequeno (não espera o índice)
  function destaques() {
    if (!DEST) {
      DEST = V.then(function (v) { return json('dados/destaques.json' + v); }).then(function (d) {
        var x = novoIdx(d); lerObras(x, d.o); x.baixa = d.baixa; x.menor = d.menor; x.ngen = d.ngen; return x;
      });
      DEST.catch(function () { DEST = null; });
    }
    return DEST;
  }
  var cacheH = {};
  function fragmento(asin) { var h = 0; for (var i = 0; i < asin.length; i++) h = (h * 31 + asin.charCodeAt(i)) % 256; return (h < 16 ? '0' : '') + h.toString(16); }
  function historico(asin) {
    var k = fragmento(asin);
    if (!cacheH[k]) {
      cacheH[k] = V.then(function (v) { return fetch('dados/h/' + k + '.json' + v); }).then(function (r) { if (r.status === 404) return {}; if (!r.ok) throw new Error(r.status); return r.json(); });
      cacheH[k].catch(function () { delete cacheH[k]; });
    }
    return cacheH[k].then(function (f) { return f[asin] || null; });
  }

  // ---------- peças de interface ----------
  // cor da capa gerada: um dos tons de pano de encadernação (couro, vinho, verde, azul, ocre, ameixa), fixo por título
  var PANOS = [20, 355, 150, 212, 36, 320];
  function matiz(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) % 360; return PANOS[h % PANOS.length]; }
  function capa(o, cls, alt) {
    cls = 'cv' + (cls ? ' ' + cls : '');
    var tam = /\bg\b/.test(cls) ? 654 : /\bm\b/.test(cls) ? 436 : 218;   // altura da imagem (2x o tamanho na tela)
    if (o.img) return '<div class="' + cls + '" data-t="' + esc(o.t) + '"><img src="' + CAPA + encodeURIComponent(o.img) + '._AC_UY' + tam + '_.jpg" alt="' + (alt ? esc('Capa de ' + o.t) : '') + '" loading="lazy" decoding="async"></div>';
    return placeholder(o.t, cls);
  }
  function placeholder(t, cls) { return '<div class="' + cls + ' ph" style="--h:' + matiz(t || '') + '" data-i="' + esc((t || '?').charAt(0).toUpperCase()) + '" aria-hidden="true"><span>' + esc(t) + '</span></div>'; }
  // capa que não carrega vira a capa gerada
  document.addEventListener('error', function (e) {
    var img = e.target; if (img.tagName !== 'IMG' || !img.parentNode || !img.parentNode.classList.contains('cv')) return;
    var d = img.parentNode; d.outerHTML = placeholder(d.dataset.t || '', d.className);
  }, true);

  function etiquetaIdioma(o) { return o.idioma && o.idioma !== 'Português' ? ' <span class="tag">' + esc(o.idioma) + '</span>' : ''; }
  function subtitulo(o, extra) { return [esc(o.autor), o.ano || '', extra].filter(Boolean).join(' · ') + etiquetaIdioma(o); }
  // edição no menor preço já registrado (com 14+ dias de coleta e abaixo do preço mais comum, ou seja, o preço variou)
  function noMenor(e) { return !!(e.menor && e.preco <= e.menor && e.mc && e.preco < e.mc); }
  var MENOR = '<span class="pill dn">menor preço registrado</span>';
  function pillComum(preco, mc) {
    if (!mc) return '';
    var p = Math.round((preco - mc) / mc * 100);
    if (p === 0) return '<span class="pill">igual ao comum</span>';
    return '<span class="pill ' + (p < 0 ? 'dn' : 'up') + '">' + Math.abs(p) + '% ' + (p < 0 ? 'abaixo' : 'acima') + ' do comum</span>';
  }
  function salvos() { var s = {}; Lista.ler().forEach(function (a) { s[a] = 1; }); return s; }
  var SALVO = '<span class="salvo" title="Na sua lista">' + ic('salvar', 's') + '</span>';

  // linha de uma obra: eds = edições que passam nos filtros (a mais barata vai no preço e no link)
  function linhaObra(o, eds, sv, preco) {
    eds = eds && eds.length ? eds : o.eds;
    var m = eds.reduce(function (a, b) { return b.preco < a.preco ? b : a; });
    var formatos = o.eds.length > 1 ? o.eds.map(function (e) { return '<span' + (e === m ? ' class="on"' : '') + '>' + esc(e.fmt) + ' ' + brl(e.preco) + '</span>'; }).join('') : '<span>' + esc(m.fmt) + '</span>';
    var velho = m.idade > 1 && idx ? ' <span class="pill wr">preço de ' + L.dmes(idx.hoje - m.idade) + '</span>' : '';
    return '<li class="resultado-livro"><a class="row" href="./?livro=' + m.asin + '" data-r>' + capa(o) + '<div class="bd"><div class="tt">' + esc(o.t) + '</div><div class="sub">' + esc(o.autor) + '</div></div><span class="row-dir">' + ic('dir') + '</span><div class="pr"><span class="vh">' + (eds.length > 1 ? 'a partir de · ' : '') + esc(m.fmt) + '</span><b>' + brl(m.preco) + '</b>' + velho + '</div><span class="mini-historico" data-spark="' + m.asin + '"></span>' + (o.eds.some(function(e){return sv[e.asin];}) ? SALVO.replace('class="salvo"','class="salvo vh"') : '') + '</a><div class="row-acoes"><button type="button" class="ib hint" data-watch="' + m.asin + '" aria-label="Acompanhar preço" data-tip="Acompanhar preço">' + ic('sino') + '</button></div></li>';
  }
  function esqueleto(n) {
    var r = '<div class="sk-row"><div class="cv sk"></div><div class="sk-corpo"><div class="sk l" style="width:70%"></div><div class="sk l" style="width:40%"></div><div class="sk l" style="width:25%;height:16px"></div></div></div>';
    return '<div class="esq">' + new Array(n + 1).join(r) + '</div>';
  }
  function erro(msg) {
    app.innerHTML = '<div class="erro"><div class="vazio"><div class="ic">' + ic('alerta') + '</div><h1>' + esc(msg) + '</h1><p>Verifique a conexão.</p>' +
      '<button type="button" class="btn pri" data-acao="recarregar">Tentar de novo</button></div></div>';
    focarTela();
  }
  // cartão de capa (estantes e grades): e = edição; ant = preço anterior (riscado), se houver
  // selo: texto sobre a capa (ex.: "no seu preço"); sem preço (e.preco = 0), o cartão não mostra preço
  // por: título do livro que trouxe este para os parecidos do início ("como <título>")
  function cartao(e, ant, selo, por) {
    selo = ant ? '<span class="selo pill dn">−' + Math.round((ant - e.preco) / ant * 100) + '%</span>' : selo ? '<span class="selo pill dn">' + esc(selo) + '</span>' : '';
    return '<a class="cartao" href="./?livro=' + e.asin + '" data-r>' + capa(e.o, 'm').replace(/<\/div>$/, selo + '</div>') +
      '<span class="t">' + esc(e.o.t) + '</span>' + (e.o.autor || (!e.preco && e.fmt) ? '<span class="a">' + esc(e.o.autor || e.fmt) + '</span>' : '') +
      (por ? '<span class="por">como <cite>' + esc(por) + '</cite></span>' : '') + (e.preco ? '<span class="p"><b>' + brl(e.preco) + '</b>' + (ant ? '<s>' + brl(ant) + '</s>' : '') + (e.fmt ? '<span class="f">' + esc(e.fmt) + '</span>' : '') + '</span>' : '') + '</a>';
  }
  // No computador, a estante mostra uma fileira só (CSS). Se sobrou livro escondido, a seção ganha "Ver todos (N)",
  // que vira a estante numa grade; os cartões escondidos saem da ordem do teclado (inert). No celular ela rola.
  function arrumarEstantes() {
    document.querySelectorAll('.estante').forEach(function (e) {
      var cs = e.children, h = e.parentNode.querySelector('.sec-h'); if (!cs.length || !h) return;
      var topo = cs[0].offsetTop, fora = 0;
      for (var i = 0; i < cs.length; i++) { var x = cs[i].offsetTop > topo + 4; cs[i].inert = x; if (x) fora++; }
      var b = h.querySelector('[data-acao="abrir-estante"]'), proprio = h.querySelector('a, [data-acao="baixa-tudo"]');
      if (fora && !proprio && !b) h.insertAdjacentHTML('beforeend', '<button type="button" class="lnk" data-acao="abrir-estante">Ver todos (' + cs.length + ')</button>');
      else if (!fora && b) b.remove();
    });
  }
  var tEst = null;
  window.addEventListener('resize', function () { clearTimeout(tEst); tEst = setTimeout(arrumarEstantes, 120); });
  // aviso rápido: com ação ("Desfazer"), fica 10 s, para dar tempo de chegar ao botão pelo teclado;
  // não some enquanto o ponteiro ou o foco estão nele, e Esc fecha
  var tToast = null, msToast = 0, desfazer = null, ATALHO = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘Z' : 'Ctrl+Z';
  // fechado, o aviso só fica transparente (para a transição): o botão sai da ordem do Tab, e quem estava nele volta à tela
  function fecharToast() {
    var t = $('#toast'), bt = t.querySelector('button'), tinha = t.contains(document.activeElement);
    clearTimeout(tToast); t.classList.remove('on'); desfazer = null;
    if (bt) bt.inert = true;                       // fora do Tab e do cursor do leitor de tela; a região viva continua
    if (tinha) focarTela(true);
  }
  function contarToast() { clearTimeout(tToast); tToast = setTimeout(fecharToast, msToast); }
  function toast(msg, acao, fn) {
    var t = $('#toast');
    t.innerHTML = '<span>' + esc(msg) + '</span>' + (acao ? '<button type="button">' + esc(acao) + '</button>' : '');
    if (acao) t.querySelector('button').onclick = function () { fecharToast(); fn(); };
    desfazer = acao === 'Desfazer' ? fn : null;
    // atalho visível onde há teclado (ponteiro com hover); o leitor de tela ouve a dica junto
    if (desfazer) t.querySelector('span').insertAdjacentHTML('beforeend', matchMedia('(hover:hover)').matches ? ' <kbd class="atalho">' + ATALHO + '</kbd><span class="vh"> desfaz</span>' : '<span class="vh">. ' + ATALHO + ' desfaz.</span>');
    t.classList.add('on'); msToast = acao ? 10000 : 5000; contarToast();
  }
  (function () {
    var t = $('#toast'), pausa = function () { clearTimeout(tToast); }, segue = function () { if (t.classList.contains('on') && !t.matches(':hover') && !t.contains(document.activeElement)) contarToast(); };
    t.addEventListener('mouseenter', pausa); t.addEventListener('focusin', pausa);
    t.addEventListener('mouseleave', segue); t.addEventListener('focusout', function () { setTimeout(segue, 0); });
    document.addEventListener('keydown', function (e) {
      if (!t.classList.contains('on')) return;
      if (e.key === 'Escape') fecharToast();
      // o aviso fica no fim da página; Ctrl/⌘+Z desfaz sem precisar chegar até ele (fora de campos de texto)
      else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z' && desfazer && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); var f = desfazer; fecharToast(); f(); }
    });
  })();
  // tema: o <head> já aplicou o salvo (ou o do sistema); aqui só o botão e a cor da barra do navegador
  function aplicarTema(t) {
    document.documentElement.dataset.theme = t;
    $('#tema').setAttribute('aria-pressed', String(t !== 'light'));
    var m = $('meta[name="theme-color"]'); if (m) m.content = t === 'light' ? '#f6f3eb' : '#0b1217';
  }
  aplicarTema(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') document.documentElement.classList.add('sem-dica'); });
  ['pointermove', 'focusin'].forEach(function (t) { document.addEventListener(t, function () { document.documentElement.classList.remove('sem-dica'); }, true); });
  function contador() { var n = Lista.ler().length; $('#cont').textContent = n ? String(n) : ''; }
  function titulo(t) { document.title = t ? t + ' · Preços de livros' : 'Preços de livros: histórico de preço de livros da Amazon'; }
  function compartilhar(url, t) {
    if (navigator.share) { navigator.share({ title: t, url: url }).catch(function () { }); return; }
    var ok = function () { toast('Link copiado'); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, function () { prompt('Copie o link:', url); });
    else prompt('Copie o link:', url);
  }

  // ---------- rotas ----------
  var rotaAtual = null, scrollAlvo = null, focar = false;
  function rota() {
    var p = new URLSearchParams(location.search);
    if (p.has('livro')) return { v: 'livro', asin: (p.get('livro') || '').toUpperCase() };
    if (p.has('lista') || location.hash === '#lista') return { v: 'lista', comp: p.get('lista') || '' };
    if (p.has('sobre')) return { v: 'sobre' };
    if (p.has('inicio')) return { v: 'inicio' };
    if (['q', 'f', 'i', 'g', 'o', 'de', 'ate'].some(function (k) { return p.get(k); })) return { v: 'busca' };
    return { v: 'busca' };
  }
  // semFoco: a troca veio da digitação na busca do cabeçalho, e o foco fica no campo
  // origem: href do link ativado, guardado na entrada atual para o foco voltar a ele (popstate)
  function ir(url, substituir, semFoco, origem) {
    var st = history.state || {};
    history.replaceState({ y: scrollY, n: st.n || 0, foco: origem || null }, '');
    history[substituir ? 'replaceState' : 'pushState']({ y: 0, n: (st.n || 0) + (substituir ? 0 : 1) }, '', url);
    scrollAlvo = 0; focar = !semFoco; desenhar();
  }
  // rolagem instantânea mesmo com scroll-behavior:smooth; navegador que não conhece 'instant' recusa o objeto e cai no scrollTo simples
  function pular(y) { try { scrollTo({ top: y, behavior: 'instant' }); } catch (e) { scrollTo(0, y); } }
  function rolar() { if (scrollAlvo != null) { pular(scrollAlvo); scrollAlvo = null; } }
  // depois de uma troca de tela, o foco vai para o título da tela nova (ou para o conteúdo), para o leitor de tela
  // anunciar a troca e o Tab seguir dali. Cada tela chama ao desenhar o conteúdo final (não o esqueleto).
  // focoApos: seletor do controle que deve receber o foco quando a tela for redesenhada no lugar
  // (ex.: o botão do preço-alvo que acabou de ser salvo), já que o controle antigo some com o innerHTML
  var focoApos = null, focoVolta = null;
  function focarEl(el) { if (el) { if (!/^(A|BUTTON|INPUT|SELECT)$/.test(el.tagName)) el.tabIndex = -1; el.focus({ preventScroll: true }); } return !!el; }
  function focarTela(sempre) {
    if (focoApos) { var c = app.querySelector(focoApos); focoApos = null; if (c) { focar = false; c.focus({ preventScroll: true }); return; } sempre = true; }
    if (!focar && !sempre) return;
    focar = false;
    if (focoVolta) { var v = app.querySelector('a[href="' + focoVolta + '"]'); focoVolta = null; if (v) { v.focus({ preventScroll: true }); return; } }
    // [data-foco]: a tela indica um alvo melhor que o h1 (no livro, a região inteira, para o Tab passar pelas ações)
    var h = app.querySelector('[data-foco]') || app.querySelector('h1:not([hidden])') || app;
    if (h !== app) h.tabIndex = -1;
    h.focus({ preventScroll: true });
  }
  function voltar() { if ((history.state || {}).n > 0) history.back(); else ir('./'); }
  function desenhar() {
    var r = rota(); rotaAtual = r; document.body.dataset.tela = r.v;
    var lnk = $('.hdr-lista'); if (r.v === 'lista') lnk.setAttribute('aria-current', 'page'); else lnk.removeAttribute('aria-current');
    if (r.v !== 'busca' && document.activeElement !== q) { q.value = ''; $('#limpa').hidden = true; }
    if (r.v === 'busca') return busca(true);
    if (r.v === 'livro') return livro(r.asin);
    if (r.v === 'lista') return r.comp ? listaCompartilhada(r.comp) : lista();
    if (r.v === 'sobre') return sobre();
    return inicio();
  }
  function aindaEm(r) { return rotaAtual === r; }

  // ---------- início ----------
  var filtroBaixa = '', baixaTudo = false;
  function inicio() {
    titulo(''); var r = rotaAtual;
    if (!DEST) app.innerHTML = '<section class="boas sec"><div class="sk l" style="height:34px;width:55%"></div><div class="sk l" style="width:40%;margin-top:14px"></div></section>' + esqueleto(3);
    Promise.all([destaques(), META, EVENTOS]).then(function (rs) {
      if (!aindaEm(r)) return;
      var x = rs[0], m = rs[1], ev = rs[2], out = [];
      var lido = m.lido_ate ? leitura(m.lido_ate) : '';
      out.push('<section class="boas sec">' + (lido ? '<p class="sobre-t">Preços lidos até ' + lido + '</p>' : '') + '<h1>Histórico de preço de livros</h1><p>' + m.itens.toLocaleString('pt-BR') +
        ' livros da Amazon.com.br, com o preço lido todo dia.</p>' + (m.aviso ? '<p class="aviso">' + esc(m.aviso) + '</p>' : '') + '</section>');
      if (Lista.ler().length) out.push('<section class="sec" id="sua-lista"></section>');
      var rec = Lista.recentes();
      if (rec.length) out.push('<section class="sec"><div class="sec-h"><h2>Vistos recentemente</h2><button type="button" class="lnk" data-acao="limpar-recentes">Limpar</button></div><div class="estante">' +
        rec.map(function (v) { return cartao({ asin: v.a, preco: 0, o: { t: v.t, img: v.img } }); }).join('') + '</div></section>');
      if (Lista.ler().length || rec.length) out.push('<section class="sec" id="parecidos"></section>');
      var prox = ev.filter(function (e) { return e[1] >= x.hoje; }).sort(function (a, b) { return a[1] - b[1]; })[0];
      if (prox) {
        var d = new Date((prox[1] - 719163) * 864e5), faltam = prox[1] - x.hoje;
        out.push('<section class="sec card prox"><div class="dia"><b>' + d.getUTCDate() + '</b><small>' + L.dmes(prox[1]).split(' ')[1] + '</small></div><div><h2>' + esc(prox[0]) + '</h2><p>' +
          (faltam === 0 ? 'Hoje' : 'Daqui a ' + L.plural(faltam, 'dia', 'dias')) + '</p></div></section>');
      }
      out.push('<section class="sec" id="baixa"></section>');
      var menores = (x.menor || []).map(function (a) { return x.porAsin[a]; }).filter(Boolean);
      if (menores.length) out.push('<section class="sec"><div class="sec-h"><h2>No menor preço registrado</h2></div><div class="estante">' +
        menores.slice(0, 24).map(function (e) { return cartao(e); }).join('') + '</div></section>');
      var gens = x.gen.map(function (g, i) { return [g[0], g[1], (x.ngen || [])[i] || 0]; }).filter(function (g) { return g[2]; })
        .sort(function (a, b) { return a[1].localeCompare(b[1], 'pt-BR'); });
      if (gens.length) out.push('<section class="sec"><div class="sec-h"><h2>Gêneros</h2></div><div class="gens">' +
        gens.map(function (g) { return '<a href="./?g=' + g[0] + '" data-r>' + esc(g[1]) + '<span>' + g[2].toLocaleString('pt-BR') + '</span></a>'; }).join('') + '</div></section>');
      app.innerHTML = out.join('');
      secaoBaixa(x);
      arrumarEstantes();
      rolar(); focarTela();
      // "Sua lista" precisa do índice inteiro (os livros salvos podem estar em qualquer parte); "Parecidos", só de dados/p/
      if ($('#sua-lista')) indiceCompleto().then(function (ix) { if (aindaEm(r)) suaLista(ix); });
      parecidosInicio();
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar o catálogo'); });
  }
  function suaLista(x) {
    var el = $('#sua-lista'); if (!el) return;
    var meus = Lista.ler().slice().reverse().map(function (a) { return x.porAsin[a]; }).filter(Boolean).slice(0, 12);
    if (!meus.length) { el.remove(); return; }
    var alv = Lista.alvos();
    el.innerHTML = '<div class="sec-h"><h2>Sua lista</h2><a href="./?lista" data-r>Ver tudo</a></div><div class="estante">' +
      meus.map(function (e) { return cartao(e, 0, alv[e.asin] && e.preco <= alv[e.asin] ? 'no seu preço' : ''); }).join('') + '</div>';
    arrumarEstantes();
  }
  // ---------- livros parecidos ----------
  // As listas vêm prontas em dados/p/ (formato em site.py, conta em comparador/parecidos.py). fragmentoP é a mesma
  // conta de fragmento_p em site.py: a de fragmento, com 1024 arquivos.
  function fragmentoP(asin) { var h = 0; for (var i = 0; i < asin.length; i++) h = (h * 31 + asin.charCodeAt(i)) % 1024; return ('00' + h.toString(16)).slice(-3); }
  var cacheP = {};
  // {asin, lista: [cartão], titulo, obra, grupo, sub: [nomes de subgêneros]} do livro, ou null se ele não tem parecidos
  function parecidosDe(asin) {
    var k = fragmentoP(asin);
    if (!cacheP[k]) {
      cacheP[k] = V.then(function (v) { return fetch('dados/p/' + k + '.json' + v); }).then(function (r) { if (r.status === 404) return null; if (!r.ok) throw new Error(r.status); return r.json(); });
      cacheP[k].catch(function () { delete cacheP[k]; });
    }
    return cacheP[k].then(function (f) {
      var e = f && f.p[asin];
      return e ? { asin: asin, lista: f.l[e[0]].map(function (i) { return f.c[i]; }), titulo: e[1], obra: e[2] || asin, grupo: e[3], sub: e[4] || [] } : null;
    });
  }
  // itens: [{c: cartão, como: título do livro de partida}]; cartão: [asin, título, capa, formato, preço, autor]; sub: nomes dos
  // subgêneros do livro, na página dele (ao lado do título da estante, na régua do cabeçalho)
  function estanteParecidos(tit, itens, sub) {
    var el = $('#parecidos'); if (!el) return;
    if (!itens.length) { el.remove(); return; }
    // com um livro de partida só, "como …" seria igual em todos os cartões; com mais, vai em todos (alturas iguais)
    var motivos = {}; itens.forEach(function (x) { if (x.como) motivos[x.como] = 1; });
    var comPor = Object.keys(motivos).length > 1;
    el.innerHTML = '<div class="sec-h"><h2>' + esc(tit) + '</h2>' + (sub && sub.length ? '<span class="nota">' + esc(sub.join(' · ')) + '</span>' : '') + '</div><div class="estante">' + itens.map(function (x) {
      var c = x.c;
      return cartao({ asin: c[0], preco: c[4], fmt: c[3], o: { t: c[1], img: c[2], autor: c[5] } }, 0, '', comPor ? x.como : '');
    }).join('') + '</div>';
    arrumarEstantes();
  }
  // Livros de partida do início: a lista (peso 2, os salvos por último antes) e os vistos recentemente (peso 1, menos
  // para os mais antigos); um livro nas duas soma os pesos. Só os MAX_PARTIDA de maior peso: cada um custa um arquivo.
  var MAX_PARTIDA = 8;
  function parecidosInicio() {
    var r = rotaAtual; if (!$('#parecidos')) return;
    var salvos = Lista.ler(), peso = {}, ordem = [];
    function somar(a, w) { if (!(a in peso)) { peso[a] = 0; ordem.push(a); } peso[a] += w; }
    salvos.slice().reverse().forEach(function (a) { somar(a, 2); });
    Lista.recentes().forEach(function (v, i) { somar(v.a, Math.max(0.4, 1 - i * 0.05)); });
    var partida = ordem.map(function (a, i) { return { a: a, w: peso[a], i: i }; })
      .sort(function (x, y) { return y.w - x.w || x.i - y.i; }).slice(0, MAX_PARTIDA);
    Promise.all(partida.map(function (s) {
      return parecidosDe(s.a).then(function (e) { return e && { asin: e.asin, obra: e.obra, grupo: e.grupo, titulo: e.titulo, peso: s.w, lista: e.lista }; },
        function () { return null; });
    })).then(function (es) { if (aindaEm(r)) estanteParecidos('Parecidos com os seus livros', Recomenda.juntar(es.filter(Boolean), { fora: salvos })); });
  }

  // "Baixaram de preço": uma estante; "Ver todos" vira uma grade com tudo
  function secaoBaixa(x) {
    var el = $('#baixa'); if (!el) return;
    var itens = x.baixa.map(function (b) { var e = x.porAsin[b[0]]; return e && { e: e, ant: b[1], dia: b[2] }; }).filter(Boolean);
    if (!itens.length) { el.remove(); return; }
    var tem = {}; itens.forEach(function (i) { tem[i.e.fam] = 1; });
    var vis = itens.filter(function (i) { return !filtroBaixa || i.e.fam === filtroBaixa; }), lim = baixaTudo ? vis.length : 12;
    var chips = FAMILIAS.filter(function (f) { return tem[f[0]]; });
    el.innerHTML = '<div class="sec-h"><h2>Baixaram de preço</h2>' +
      (vis.length > lim ? '<button type="button" class="lnk" data-acao="baixa-tudo">Ver todos (' + vis.length + ')</button>' : '') + '</div>' +
      (chips.length > 1 ? '<div class="chips mb"><button type="button" class="chip" data-baixa="" aria-pressed="' + !filtroBaixa + '">Todos</button>' +
        chips.map(function (f) { return '<button type="button" class="chip" data-baixa="' + f[0] + '" aria-pressed="' + (filtroBaixa === f[0]) + '">' + f[1] + '</button>'; }).join('') + '</div>' : '') +
      '<div class="' + (baixaTudo ? 'grade' : 'estante') + '">' + vis.slice(0, lim).map(function (i) { return cartao(i.e, i.ant); }).join('') + '</div>';
    arrumarEstantes();
  }

  // ---------- busca ----------
  var VAZIO = function () { return { q: '', fam: {}, i: '', g: '', o: 'rel', de: null, ate: null }; };
  var S = VAZIO(), mostrados = 30, verPreco = false, resultado = null, filtrosAbertos = false;
  function estadoDaUrl() {
    var p = new URLSearchParams(location.search), fam = {};
    (p.get('f') || '').split(',').forEach(function (f) { if (/^[fka]$/.test(f)) fam[f] = 1; });
    var n = function (k) { var v = parseFloat(p.get(k)); return isFinite(v) && v >= 0 ? Math.round(v * 100) : null; };
    S = { q: p.get('q') || '', fam: fam, i: p.get('i') || '', g: /^\d+$/.test(p.get('g') || '') ? p.get('g') : '', o: p.get('o') || 'rel', de: n('de'), ate: n('ate') };
  }
  function urlBusca() {
    var p = new URLSearchParams();
    if (S.q.trim()) p.set('q', S.q.trim());
    var f = Object.keys(S.fam); if (f.length) p.set('f', f.join(','));
    if (S.i) p.set('i', S.i);
    if (S.g) p.set('g', S.g);
    if (S.o !== 'rel') p.set('o', S.o);
    if (S.de != null) p.set('de', S.de / 100);
    if (S.ate != null) p.set('ate', S.ate / 100);
    var s = p.toString(); return s ? './?' + s : './';
  }
  function nFiltros() { return Object.keys(S.fam).length + (S.i ? 1 : 0) + (S.g ? 1 : 0) + (S.de != null || S.ate != null ? 1 : 0); }
  function buscar(x) {
    var g = S.g && x.genPorNo[S.g] != null ? x.genPorNo[S.g] : S.g ? -2 : '';    // -2: gênero que não existe
    return Busca.buscar(x.obras, { q: S.q, fam: S.fam, i: S.i, g: g, o: S.o, de: S.de, ate: S.ate }, { porAsin: x.porAsin, asinDe: L.asinDe, parcial: !x.completo });
  }
  // inteira: a rota mudou (lê a URL e volta ao topo); parte: chegou mais uma parte do índice (refaz sem mexer no resto)
  function busca(inteira, parte) {
    if (inteira) { estadoDaUrl(); if (document.activeElement !== q) q.value = S.q; $('#limpa').hidden = !q.value; mostrados = 30; }
    titulo(S.q ? 'Busca: ' + S.q : 'Busca');
    var r = rotaAtual;
    if (!idx) { app.innerHTML = esqueleto(6); indice().then(function () { if (aindaEm(r)) busca(false); }, function () { if (aindaEm(r)) erro('Não consegui carregar o catálogo'); }); return; }
    resultado = curta() ? { lista: [], cont: { fam: {}, i: {}, g: {} } } : buscar(idx);
    if (!$('#ferr')) app.innerHTML = '<h1 class="busca-h vh" id="bh"></h1><div class="ferr" id="ferr"></div><div aria-live="polite" class="vh" id="cont-res"></div><div id="res" class="res"></div>';
    // navegando por um gênero (sem texto): o nome do gênero vira o título da página
    var gi = S.g ? idx.genPorNo[S.g] : null, bh = $('#bh');
    var porGenero = gi != null && !S.q.trim();
    bh.classList.toggle('vh', !porGenero);
    bh.textContent = porGenero ? idx.gen[gi][1] : S.q.trim() ? 'Busca: ' + S.q.trim() : 'Busca';
    if (porGenero) titulo(idx.gen[gi][1]);
    // parte nova do índice enquanto a pessoa mexe num filtro (campo de preço, lista aberta): não refaz a barra
    if (!parte || !$('#ferr').contains(document.activeElement)) ferramentas();
    resultados(); if (!parte) { rolar(); focarTela(); }
  }
  // o controle com foco na barra (chip, seletor) é recriado pelo innerHTML: devolve o foco ao controle equivalente
  function seletorDe(el) {
    if (el.id) return '#' + el.id;
    var d = el.dataset;
    return d.fam ? '[data-fam="' + d.fam + '"]' : d.idioma !== undefined ? '[data-idioma="' + d.idioma.replace(/"/g, '\\"') + '"]' : d.acao ? '[data-acao="' + d.acao + '"]' : null;
  }
  function ferramentas() {
    var fe = $('#ferr'), ativo = document.activeElement, volta = fe && fe.contains(ativo) ? seletorDe(ativo) : null;
    var c = resultado.cont, chips = FAMILIAS.map(function (f) {
      return '<button type="button" class="chip" data-fam="' + f[0] + '" aria-pressed="' + !!S.fam[f[0]] + '">' + f[1] + (c.fam[f[0]] ? ' <span class="n">' + c.fam[f[0]].toLocaleString('pt-BR') + '</span>' : '') + '</button>';
    }).join('');
    var idiomas = Object.keys(c.i).sort(function (a, b) { return c.i[b] - c.i[a]; }).slice(0, 4);
    if (S.i && idiomas.indexOf(S.i) < 0) idiomas.push(S.i);
    if (idiomas.length > 1 || S.i) chips += '<span class="sep"></span>' + idiomas.map(function (i) { return '<button type="button" class="chip" data-idioma="' + esc(i) + '" aria-pressed="' + (S.i === i) + '">' + esc(i) + '</button>'; }).join('');
    var faixa = S.de != null || S.ate != null;
    chips += '<span class="sep"></span><button type="button" class="chip" data-acao="preco" aria-pressed="' + (faixa || verPreco) + '">' +
      (faixa ? (S.de != null ? brl(S.de) : 'R$ 0') + ' a ' + (S.ate != null ? brl(S.ate) : 'qualquer') : 'Preço') + ' ' + ic('baixo', 's') + '</button>';
    var ords = [['rel', 'Relevância']];
    if (idx.temAv) ords.push(['avaliacoes', 'Mais avaliados']);
    ords.push(['preco', 'Menor preço'], ['preco_desc', 'Maior preço'], ['desconto', 'Maior desconto sobre a capa']);
    if (idx.temMC) ords.push(['abaixo', 'Mais abaixo do preço comum']);
    ords.push(['titulo', 'Título (A a Z)']);
    var gens = idx.gen.map(function (g, i) { return [g[0], g[1], c.g[i] || 0]; }).filter(function (g) { return g[2] || g[0] === S.g; })
      .sort(function (a, b) { return a[1].localeCompare(b[1], 'pt-BR'); });
    var selGen = gens.length ? '<label class="sel"><span class="vh">Gênero</span><select id="gen"><option value="">Todos os gêneros</option>' +
      gens.map(function (g) { return '<option value="' + g[0] + '"' + (S.g === g[0] ? ' selected' : '') + '>' + esc(g[1]) + ' (' + g[2].toLocaleString('pt-BR') + ')</option>'; }).join('') +
      '</select>' + ic('baixo', 's') + '</label>' : '';
    $('#ferr').innerHTML = '<details class="filtros-extra"' + (filtrosAbertos || nFiltros() || verPreco ? ' open' : '') + '><summary>Filtros</summary><div class="chips" role="group" aria-label="Filtros">' + chips + '</div>' +
      (verPreco || faixa ? '<div class="faixa-preco"><span class="mu sm">Preço</span><input id="de" type="number" inputmode="decimal" min="0" step="1" placeholder="de R$" aria-label="Preço mínimo em reais" value="' + (S.de != null ? S.de / 100 : '') + '">' +
        '<span class="mu sm">até</span><input id="ate" type="number" inputmode="decimal" min="0" step="1" placeholder="até R$" aria-label="Preço máximo em reais" value="' + (S.ate != null ? S.ate / 100 : '') + '"></div>' : '') +
      selGen + '</details><div class="l2"><span></span><div class="sels"><span class="ord-label">Ordenar por</span>' + '<label class="sel"><span class="vh">Ordenar por</span><select id="ord">' + ords.map(function (o) { return '<option value="' + o[0] + '"' + (S.o === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' + ic('baixo', 's') + '</label><div class="view-switch"><button class="ib" type="button" data-view="lista" aria-label="Exibir em lista" aria-pressed="' + (document.body.dataset.view !== 'grade') + '">' + ic('lista') + '</button><button class="ib" type="button" data-view="grade" aria-label="Exibir em grade" aria-pressed="' + (document.body.dataset.view === 'grade') + '">' + ic('grade') + '</button></div></div></div>';
    var nv = volta && ($('#ferr ' + volta) || $('#ferr .chip')); if (nv) nv.focus({ preventScroll: true });
  }
  function curta() { var t = S.q.trim(); return t.length === 1 && !L.asinDe(t) && !nFiltros() && S.o === 'rel'; }
  function resultados() {
    if (curta()) {
      $('#ferr .l2 > span').innerHTML = ''; anunciarContagem('');
      $('#res').innerHTML = '<p class="nota-busca">Continue digitando…</p>';
      return;
    }
    var r = resultado.lista, el = $('#res'), n = r.length, sv = salvos(), carregando = !idx.completo;
    $('#ferr .l2 > span').innerHTML = '<strong class="resultados-titulo">Resultados</strong><span class="cont">' + (n ? n.toLocaleString('pt-BR') + (n === 1 ? ' livro' : ' livros') + (carregando ? ' até agora' : '') : '') + '</span>' +
      (nFiltros() ? ' <button type="button" class="btn gh sm" data-acao="limpar-filtros">Limpar filtros</button>' : '');
    anunciarContagem(carregando ? '' : n ? n.toLocaleString('pt-BR') + (n === 1 ? ' livro encontrado' : ' livros encontrados') : 'Nenhum livro encontrado');
    var nota = resultado.correcao ? '<p class="nota-busca">Mostrando resultados para <b>' + esc(resultado.correcao) + '</b></p>' :
      resultado.parcial ? '<p class="nota-busca">Nenhum livro tem todas as palavras. Estes têm a maior parte delas.</p>' : '';
    var status = carregando ? '<p class="nota-busca carregando" role="status"><span class="giro" aria-hidden="true"></span>Buscando no restante do catálogo…</p>' :
      idx.falhou ? '<p class="nota-busca">Parte do catálogo não carregou. <button type="button" class="btn gh sm" data-acao="recarregar">Tentar de novo</button></p>' : '';
    if (!n) {
      // enquanto falta parte do índice, "nada encontrado" ainda não é verdade
      if (carregando) { el.innerHTML = status + esqueleto(3); return; }
      el.innerHTML = status + '<div class="vazio"><div class="ic">' + ic('busca') + '</div><h2>Nenhum livro encontrado</h2><p>' +
        (nFiltros() ? 'Tente sem os filtros.' : 'Tente outras palavras.') + '</p>' +
        (nFiltros() ? '<button type="button" class="btn" data-acao="limpar-filtros">Limpar filtros</button>' : '') + '</div>';
      return;
    }
    var explorar = !S.q.trim() && !nFiltros() ? '<p class="nota-busca"><a href="./?inicio" data-r>Explorar gêneros, livros que baixaram de preço e parecidos com os seus</a></p>' : '';
    el.innerHTML = explorar + nota + status + '<ul class="lst duas">' + r.slice(0, mostrados).map(function (x) { return linhaObra(x.o, x.eds, sv); }).join('') + '</ul>' +
      (n > mostrados ? '<div class="mais"><button type="button" class="btn sm" data-acao="mais" id="mais">Mostrar mais</button></div>' : '');
    observarMais(); carregarSparks();
  }
  var sparkObserver, sparkFila = [], sparkAtivos = 0;
  function carregarSparks() {
    if (!window.IntersectionObserver) return;
    if (!sparkObserver) sparkObserver = new IntersectionObserver(function(es) {
      es.forEach(function(e){if(e.isIntersecting){sparkObserver.unobserve(e.target);sparkFila.push(e.target);}}); processarSpark();
    }, {rootMargin:'120px'});
    document.querySelectorAll('[data-spark]:not([data-observado])').forEach(function(el){el.dataset.observado='1';sparkObserver.observe(el);});
  }
  function processarSpark() {
    while(sparkAtivos < 2 && sparkFila.length) {
      var el=sparkFila.shift(); if(!el.isConnected)continue; sparkAtivos++;
      (function(alvo){historico(alvo.dataset.spark).then(function(h){if(h && alvo.isConnected){alvo.innerHTML=spark(h.h,h.h[h.h.length-1][1]);alvo.dataset.tendencia=h.h[h.h.length-1][2]>h.h[0][2]?'alta':h.h[h.h.length-1][2]<h.h[0][2]?'baixa':'igual';}}).catch(function(){}).finally(function(){sparkAtivos--;processarSpark();});})(el);
    }
  }
  // a contagem vai para uma região viva (só para leitor de tela), com espera, para não anunciar a cada tecla
  var tCont = null;
  function anunciarContagem(txt) {
    clearTimeout(tCont);
    tCont = setTimeout(function () { var el = $('#cont-res'); if (el && el.textContent !== txt) el.textContent = txt; }, txt ? 800 : 0);
  }
  var obs = null;
  function observarMais() {
    if (!('IntersectionObserver' in window)) return;
    if (!obs) obs = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) maisResultados(); }); }, { rootMargin: '600px' });
    obs.disconnect(); var b = $('#mais'); if (b) obs.observe(b);
  }
  function maisResultados() {
    if (!resultado || !$('#res')) return;
    var antes = mostrados, sv = salvos(); mostrados += 30;
    $('#res .lst').insertAdjacentHTML('beforeend', resultado.lista.slice(antes, mostrados).map(function (x) { return linhaObra(x.o, x.eds, sv); }).join(''));
    carregarSparks();
    if (mostrados >= resultado.lista.length) {
      var m = $('#res .mais');
      if (m) { var tinha = m.contains(document.activeElement); m.remove(); if (tinha) focarEl($('#res .lst').children[antes].querySelector('a')); }
    }
  }
  // digitando: veio do campo de busca do cabeçalho; a troca de tela não tira o foco dele
  function aplicarBusca(digitando) {
    var url = urlBusca();
    if (url === './') { if (rotaAtual && rotaAtual.v === 'busca') ir('./', true, digitando); return; }
    if (rotaAtual && rotaAtual.v === 'busca') { history.replaceState(history.state, '', url); mostrados = 30; pular(0); busca(false); }
    else ir(url, false, digitando);
  }
  var tBusca = null;
  q.addEventListener('input', function () {
    $('#limpa').hidden = !q.value;
    clearTimeout(tBusca);
    tBusca = setTimeout(function () {
      if (!rotaAtual || rotaAtual.v !== 'busca') S = VAZIO();
      S.q = q.value; aplicarBusca(true);
    }, 150);
  });
  q.form.addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(tBusca); if (rotaAtual.v !== 'busca') S = VAZIO(); var antes = rotaAtual; S.q = q.value; focar = true; aplicarBusca();
    if (rotaAtual.v === 'busca') { if (idx) focarTela(); }       // sem o índice, a busca foca ao desenhar os resultados
    else if (rotaAtual === antes) focar = false;                  // campo vazio fora da busca: nada muda de tela
  });
  q.addEventListener('keydown', function (e) { if (e.key === 'Escape') { q.value = ''; q.dispatchEvent(new Event('input')); } });
  $('#limpa').addEventListener('click', function () { q.value = ''; q.focus(); q.dispatchEvent(new Event('input')); });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); q.focus(); q.select(); }
  });
  app.addEventListener('change', function (e) {
    if (e.target.id === 'ord') { S.o = e.target.value; aplicarBusca(); }
    else if (e.target.id === 'gen') { S.g = e.target.value; aplicarBusca(); }
    else if (e.target.id === 'ordl') { ordemLista = e.target.value; focoApos = '#ordl'; lista(); }
  });
  // <details> não borbulha o toggle: ouve na captura; o redesenho da barra mantém o painel como a pessoa deixou
  app.addEventListener('toggle', function (e) { if (e.target.classList && e.target.classList.contains('filtros-extra')) filtrosAbertos = e.target.open; }, true);
  var tPreco = null;
  app.addEventListener('input', function (e) {
    var fa = e.target.closest('[data-alvo-f]');
    if (fa) { var ec = fa.querySelector('.erro-campo'); if (ec) ec.remove(); e.target.removeAttribute('aria-invalid'); e.target.removeAttribute('aria-describedby'); return; }
    if (e.target.id !== 'de' && e.target.id !== 'ate') return;
    var v = parseFloat(String(e.target.value).replace(',', '.'));
    S[e.target.id] = isFinite(v) && v >= 0 ? Math.round(v * 100) : null;
    clearTimeout(tPreco);
    tPreco = setTimeout(function () { history.replaceState(history.state, '', urlBusca()); mostrados = 30; resultado = buscar(idx); resultados(); }, 300);
  });

  // ---------- página do livro ----------
  // No celular: capa ao lado do título, depois formatos, preço e botões. No computador: capa e botões numa
  // coluna à esquerda (fixa ao rolar) e o resto à direita. É a mesma marcação (ver .livro no CSS).
  function livro(asin) {
    var r = rotaAtual;
    titulo('Livro');
    app.innerHTML = '<button type="button" class="voltar" data-acao="voltar">' + ic('voltar', 's') + 'Voltar</button><div class="livro"><div class="l-lado"><div class="cv g sk"></div></div>' +
      '<div class="l-corpo"><div class="l-cab"><div class="sk l" style="height:30px;width:80%"></div><div class="sk l" style="width:40%;margin-top:14px"></div></div>' +
      '<div class="compra"><div class="sk l" style="height:40px;width:35%;margin-top:20px"></div></div></div></div>';
    if (!/^[A-Z0-9]{10}$/.test(asin)) return naoEncontrado();
    var parecidos = parecidosDe(asin).catch(function () { return null; });     // pedido junto com o histórico
    Promise.all([historico(asin), EVENTOS, META]).then(function (rs) {
      if (!aindaEm(r)) return;
      var l = rs[0], ev = rs[1], m = rs[2];
      if (!l) return naoEncontrado();
      var lt = L.limpar(l.t || asin), o = { t: lt.t, autor: l.autor || '', img: l.imagem || '', ano: l.publicado ? +l.publicado.slice(0, 4) : 0, idioma: l.idioma || lt.idioma };
      var tr = l.h, ult = tr[tr.length - 1][1], f = L.fatos(tr, ult), recente = m.ultima_coleta == null || ult >= m.ultima_coleta - 1;
      titulo(o.t);
      Lista.visto({ a: asin, t: o.t, img: o.img, p: f.preco });
      var det = [];
      if (l.nota) det.push('<span class="nota"><svg viewBox="0 0 24 24" aria-hidden="true">' + IC.estrela + '</svg>' + (l.nota / 10).toFixed(1).replace('.', ',') +
        (l.avaliacoes ? ' · ' + L.plural(l.avaliacoes, 'avaliação', 'avaliações').replace(/^\d+/, l.avaliacoes.toLocaleString('pt-BR')) : '') + '</span>');
      if (l.publicado) det.push(esc(L.dmes(new Date(l.publicado + 'T12:00:00Z').getTime() / 864e5 + 719163 | 0, true)));
      if (o.idioma) det.push(esc(o.idioma));
      det.push('ASIN ' + asin);
      var eds = l.eds || [[asin, l.f || 'Livro', f.preco]];
      app.innerHTML = '<button type="button" class="voltar" data-acao="voltar">' + ic('voltar', 's') + 'Voltar</button>' +
        (m.aviso ? '<p class="aviso">' + esc(m.aviso) + '</p>' : '') +
        '<div class="livro" role="region" aria-labelledby="l-tit" data-foco><aside class="l-lado">' + capa(o, 'g', true) +
        '<div class="acoes"><a class="btn pri" href="' + L.linkAmazon(asin) + '" target="_blank" rel="noopener noreferrer">Ver na Amazon ' + ic('ext', 's') + '</a>' +
        '<button type="button" class="btn salvar" data-salvar="' + asin + '"></button>' +
        '<button type="button" class="btn ico" data-acao="compartilhar" aria-label="Compartilhar">' + ic('share', 's') + '<span class="rot">Compartilhar</span></button></div></aside>' +
        '<div class="l-corpo"><header class="l-cab"><h1 id="l-tit">' + esc(o.t) + '</h1>' +
        (o.autor ? '<p class="aut"><a href="./?q=' + encodeURIComponent(l.autor1 || o.autor) + '" data-r>' + esc(o.autor) + '</a></p>' : '') +
        '<p class="det">' + det.map(function (d) { return '<span>' + d + '</span>'; }).join('') + '</p>' +
        (l.gen ? '<p class="l-gens">' + l.gen.map(function (g) { return '<a href="./?g=' + g[0] + '" data-r>' + esc(g[1]) + '</a>'; }).join('') + '</p>' : '') + '</header>' +
        (eds.length > 1 ? '<div class="fmts" id="fmts" role="group" aria-label="Formato">' + eds.map(function (d) {
          return '<a class="fmt" href="./?livro=' + d[0] + '" data-r data-sub' + (d[0] === asin ? ' aria-current="true"' : '') + '><span>' + esc(d[1]) + '</span><b>' + brl(d[0] === asin ? f.preco : d[2]) + '</b></a>';
        }).join('') + '</div>' : '') +
        '<div class="compra"><div class="preco-g"><b>' + brl(f.preco) + '</b><span class="mu sm">' + esc(l.f || 'Livro') + ' · ' +
        (recente ? 'em ' + L.dl(ult) : 'último preço visto, em ' + L.dl(ult)) + '</span></div>' +
        '<div class="fat">' + (recente ? '' : '<span class="pill wr">Sem coleta recente</span>') + (menorRegistrado(tr, f) ? MENOR.replace('menor', 'Menor') : '') + L.comparacoes(f) + '</div></div>' +
        '<div class="l-resto"><section class="card pad sec"><div id="graf"></div>' + L.estatisticas(f, tr[0][0]) + '</section>' +
        L.secaoEventos(tr, ev, m.ultima_coleta || ult) + estante('Outras edições', l.outras) +
        estante('Mais de ' + (l.autor1 || o.autor), l.mesmo_autor) + '<section class="sec" id="parecidos"></section></div></div></div>';
      organizarLivro(l,o,asin,f,recente,ult);
      botaoSalvar();
      arrumarEstantes();
      L.grafico($('#graf'), L.dadosGrafico(tr, ev));
      rolar(); focarTela();
      // "Parecidos" chega por último, sem segurar o resto da página; erro ou livro sem lista: a seção some
      parecidos.then(function (p) { if (aindaEm(r)) estanteParecidos('Parecidos com este livro', p ? p.lista.map(function (c) { return { c: c }; }) : [], p && p.sub); });
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar este livro'); });
  }
  function organizarLivro(l,o,asin,f,recente,ult) {
    var cab=$('.l-cab'),acoes=$('.l-lado .acoes');cab.appendChild(acoes);acoes.querySelector('.ico').remove();
    acoes.insertAdjacentHTML('beforeend','<button type="button" class="btn ico hint" data-watch="'+asin+'" aria-label="Acompanhar preço" data-tip="Acompanhar preço">'+ic('sino')+'</button>');
    $('.compra').insertAdjacentHTML('afterbegin','<div class="preco-rotulo">'+(recente?'Preço atual na Amazon':'Último preço na Amazon')+'</div>');
    var stats=$('.stats');stats.lastElementChild.remove();stats.children[1].className='st-menor';stats.children[2].className='st-maior';   // fica: mais comum, menor e maior (o preço atual já está grande acima)
    var info=[['Autor',o.autor],['Editora',l.editora],['Data de publicação',l.publicado],['ISBN / ASIN',l.isbn||asin]], resto=$('.l-resto');
    resto.children[0].insertAdjacentHTML('afterend','<section class="sec livro-info"><h2>'+ic('livro')+' Informações do livro</h2><div class="info-layout"><dl>'+info.map(function(r){return '<div><dt>'+esc(r[0])+'</dt><dd>'+esc(r[1]||'Não informado')+'</dd></div>';}).join('')+'</dl><div class="amazon-card"><a class="btn pri" href="'+L.linkAmazon(asin)+'" target="_blank" rel="noopener noreferrer">Ver na Amazon '+ic('ext','s')+'</a></div></div></section>');
  }
  function botaoSalvar() {
    var b = $('[data-salvar]'); if (!b) return;
    var na = Lista.tem(b.dataset.salvar);
    b.setAttribute('aria-pressed', String(na)); b.setAttribute('aria-label',na?'Remover da minha lista':'Salvar na minha lista'); b.title=na?'Na sua lista':'Salvar na minha lista'; b.innerHTML=ic('coracao');
  }
  // estante de livros calculada em site.py (outras edições, mais do autor): [[asin, título, capa, formato, preço], ...]
  function estante(tit, livros) {
    if (!livros || !livros.length) return '';
    return '<section class="sec"><div class="sec-h"><h2>' + esc(tit) + '</h2></div><div class="estante">' + livros.map(function (c) {
      return cartao({ asin: c[0], preco: c[4], fmt: c[3], o: { t: L.limpar(c[1]).t, img: c[2], autor: '' } });   // o formato vai junto do preço
    }).join('') + '</div></section>';
  }
  // o preço de agora é o menor já registrado? (14+ dias de coleta e o preço já foi maior)
  function menorRegistrado(tr, f) {
    if (f.diasObservados < L.MIN_COMUM) return false;
    var min = Infinity, max = 0;
    tr.forEach(function (t) { min = Math.min(min, t[2]); max = Math.max(max, t[2]); });
    return f.preco <= min && max > min;
  }
  function naoEncontrado() {
    titulo('Livro não encontrado');
    app.innerHTML = '<div class="vazio"><div class="ic">' + ic('livro') + '</div><h1>Livro não encontrado</h1><p>Ele não está entre os livros acompanhados.</p>' +
      '<a class="btn pri" href="./" data-r>Ir para o início</a></div>';
    focarTela();
  }

  // ---------- minha lista ----------
  var ordemLista = 'recentes', pendenteAlvo = null;
  // a lista usa só o histórico de cada livro (h/XX.json): não precisa esperar o índice da busca
  function carregarItens(asins) {
    return Promise.all([META].concat(asins.map(function (a) { return historico(a).then(function (h) { return { asin: a, h: h }; }); })));
  }
  function itemLista(it, hoje) {
    var h = it.h;
    if (!h) return { asin: it.asin, fora: true };
    var lt = L.limpar(h.t || it.asin), tr = h.h, ult = tr[tr.length - 1][1], f = L.fatos(tr, ult);
    var o = { t: lt.t, autor: h.autor || '', img: h.imagem || '', ano: h.publicado ? +h.publicado.slice(0, 4) : 0, idioma: h.idioma || lt.idioma };
    return { asin: it.asin, o: o, fmt: h.f || '', preco: f.preco, f: f, tr: tr, ult: ult, recente: hoje == null || ult >= hoje - 1,
      mc: f.diasObservados >= L.MIN_COMUM ? f.mediana : 0 };
  }
  function spark(tr, ult) {
    var pd = L.porDia(tr), dias = pd.dias.filter(function (d) { return d > ult - 60; });
    if (dias.length < 2) return '';
    var vs = dias.map(function (d) { return pd.preco[d]; }), lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs), a = dias[0], b = Math.max(dias[dias.length - 1], a + 1);
    var X = function (d) { return (2 + (d - a) / (b - a) * 92).toFixed(1); }, Y = function (p) { return hi === lo ? '16' : (28 - (p - lo) / (hi - lo) * 24).toFixed(1); };
    var d = dias.map(function (x, i) { return (i ? 'L' + X(x) + ',' + Y(pd.preco[dias[i - 1]]) + 'L' : 'M') + X(x) + ',' + Y(pd.preco[x]); }).join('');
    return '<svg class="spark" viewBox="0 0 96 32" aria-hidden="true"><path d="' + d + '"/></svg>';
  }
  // preço-alvo (só na sua lista): "Definir preço-alvo", ou o alvo e se o preço já chegou nele
  function alvoHtml(i, alv) {
    var a = alv && alv[i.asin];
    if (!alv) return '';
    if (!a) return '<div class="alvo"><button type="button" class="lnk" data-alvo="' + i.asin + '">Definir preço-alvo</button></div>';
    return '<div class="alvo"><span>Seu preço: ' + brl(a) + '</span>' + (i.preco <= a ? '<span class="pill dn">chegou</span>' : '<span class="mu">faltam ' + brl(i.preco - a) + '</span>') +
      '<button type="button" class="lnk" data-alvo="' + i.asin + '">Mudar</button></div>';
  }
  function linhaLista(i, base, remover, alv) {
    if (i.fora) return '<li><div class="row">' + placeholder(i.asin, 'cv p') + '<div class="bd"><div class="tt">' + i.asin + '</div><div class="sub">Sem preço registrado</div></div>' +
      (remover ? '<div class="lado"><button type="button" class="ib rm" data-remover="' + i.asin + '" aria-label="Remover da lista">' + ic('x', 's') + '</button></div>' : '') + '</div></li>';
    var antes = base && base.precos[i.asin], dif = antes && antes !== i.preco ? i.preco - antes : 0;
    var mud = dif ? '<span class="pill ' + (dif < 0 ? 'dn' : 'up') + '">' + (dif < 0 ? '▼ ' : '▲ ') + brl(Math.abs(dif)) + ' desde ' + L.dmes(base.dia) + '</span>' : '';
    return '<li><div class="row">' + capa(i.o, 'p') + '<div class="bd"><a class="tt esticar" href="./?livro=' + i.asin + '" data-r>' + esc(i.o.t) + '</a><div class="sub">' + subtitulo(i.o, esc(i.fmt)) + '</div>' +
      '<div class="pr"><b>' + brl(i.preco) + '</b>' + mud + pillComum(i.preco, i.mc) + (i.recente ? '' : '<span class="pill wr">último preço visto em ' + L.dl(i.ult) + '</span>') + '</div>' + alvoHtml(i, alv) + '</div>' +
      '<div class="lado">' + (remover ? '<button type="button" class="ib rm" data-remover="' + i.asin + '" aria-label="Remover ' + esc(i.o.t) + ' da lista">' + ic('x', 's') + '</button>' : '') + spark(i.tr, i.ult) + '</div></div></li>';
  }
  function lista() {
    var r = rotaAtual, asins = Lista.ler();
    titulo('Minha lista');
    if (!asins.length) {
      app.innerHTML = '<div class="vazio"><div class="ic">' + ic('salvar') + '</div><h1>Sua lista está vazia</h1>' +
        '<p>Salve livros para ver o preço de todos aqui e o que mudou desde a sua última visita.</p>' +
        '<button type="button" class="btn pri" data-acao="buscar">' + ic('busca', 's') + 'Buscar livros</button></div>';
      focarTela(); return;
    }
    if (!$('#lst')) app.innerHTML = '<div class="lista-h"><div><h1>Minha lista</h1><p class="mu sub">' + L.plural(asins.length, 'livro', 'livros') + '</p></div></div>' + esqueleto(Math.min(asins.length, 5));
    carregarItens(asins).then(function (rs) {
      if (!aindaEm(r)) return;
      var m = rs[0], hoje = m.ultima_coleta, itens = rs.slice(1).map(function (it) { return itemLista(it, hoje); });
      var precos = {}; itens.forEach(function (i) { if (!i.fora) precos[i.asin] = i.preco; });
      var base = Lista.visita(hoje, precos), mais = 0, menos = 0, alv = Lista.alvos();
      var noAlvo = itens.filter(function (i) { return !i.fora && alv[i.asin] && i.preco <= alv[i.asin]; }).length;
      itens.forEach(function (i) { var a = base && base.precos[i.asin]; if (a && !i.fora) { if (i.preco < a) menos++; else if (i.preco > a) mais++; } });
      var ordens = [['recentes', 'Adicionados por último'], ['preco', 'Menor preço']];
      if (base) ordens.push(['queda', 'Maior queda desde a última visita']);
      if (Object.keys(alv).length) ordens.push(['alvo', 'Mais perto do seu preço']);
      if (itens.some(function (i) { return i.mc; })) ordens.push(['abaixo', 'Mais abaixo do preço comum']);
      ordens.push(['titulo', 'Título (A a Z)']);
      if (!ordens.some(function (o) { return o[0] === ordemLista; })) ordemLista = 'recentes';
      var v = itens.slice(), dif = function (i) { var a = base && base.precos[i.asin]; return a && !i.fora ? (i.preco - a) / a : 0; };
      if (ordemLista === 'recentes') v.reverse();
      else if (ordemLista === 'preco') v.sort(function (a, b) { return (a.fora ? 1e12 : a.preco) - (b.fora ? 1e12 : b.preco); });
      else if (ordemLista === 'queda') v.sort(function (a, b) { return dif(a) - dif(b); });
      else if (ordemLista === 'alvo') v.sort(function (a, b) { var d = function (i) { return i.fora || !alv[i.asin] ? 9 : (i.preco - alv[i.asin]) / alv[i.asin]; }; return d(a) - d(b); });
      else if (ordemLista === 'abaixo') v.sort(function (a, b) { return (a.mc ? (a.preco - a.mc) / a.mc : 9) - (b.mc ? (b.preco - b.mc) / b.mc : 9); });
      else v.sort(function (a, b) { var p = a.fora ? '~' : norm(a.o.t), s = b.fora ? '~' : norm(b.o.t); return p < s ? -1 : p > s ? 1 : 0; });
      app.innerHTML = '<div class="lista-h"><div><h1>Minha lista</h1><p class="mu sub">' + L.plural(itens.length, 'livro', 'livros') + ' · salva neste aparelho</p></div>' +
        '<div class="ctl"><label class="sel"><span class="vh">Ordenar por</span><select id="ordl">' +
        ordens.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === ordemLista ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' + ic('baixo', 's') + '</label>' +
        '<button type="button" class="btn sm" data-acao="compartilhar-lista">' + ic('share', 's') + 'Compartilhar</button></div></div>' +
        (base && (mais || menos) || noAlvo ? '<div class="resumo">' + (base && (mais || menos) ? '<span class="mu">Desde sua visita de ' + L.dmes(base.dia) + ':</span>' +
          (menos ? '<span class="pill dn">▼ ' + L.plural(menos, 'ficou mais barato', 'ficaram mais baratos') + '</span>' : '') +
          (mais ? '<span class="pill up">▲ ' + L.plural(mais, 'ficou mais caro', 'ficaram mais caros') + '</span>' : '') : '') +
          (noAlvo ? '<span class="pill dn">' + L.plural(noAlvo, 'chegou no seu preço', 'chegaram no seu preço') + '</span>' : '') + '</div>' : '') +
        '<ul class="lst" id="lst">' + v.map(function (i) { return linhaLista(i, base, true, alv); }).join('') + '</ul>';
      rolar(); focarTela();
      if(pendenteAlvo){var alvo=$('[data-alvo="'+pendenteAlvo+'"]');pendenteAlvo=null;if(alvo)alvo.click();}
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar sua lista'); });
  }
  function listaCompartilhada(texto) {
    var r = rotaAtual, asins = Lista.extrair(texto.split(',').join(' ')).slice(0, 200);
    titulo('Lista compartilhada');
    if (!asins.length) {
      app.innerHTML = '<div class="vazio"><div class="ic">' + ic('salvar') + '</div><h1>Lista não encontrada</h1><p>O link não tem nenhum livro. Confira se ele foi copiado inteiro.</p>' +
        '<a class="btn pri" href="./" data-r>Ir para o início</a></div>';
      return focarTela();
    }
    app.innerHTML = esqueleto(Math.min(asins.length, 5));
    carregarItens(asins).then(function (rs) {
      if (!aindaEm(r)) return;
      var itens = rs.slice(1).map(function (it) { return itemLista(it, rs[0].ultima_coleta); }), minha = salvos();
      var novos = asins.filter(function (a) { return !minha[a]; }).length;
      app.innerHTML = '<div class="lista-h"><div><h1>Lista compartilhada</h1><p class="mu sub">' + L.plural(itens.length, 'livro', 'livros') + '</p></div>' +
        (novos ? '<button type="button" class="btn pri" data-acao="importar" data-asins="' + asins.join(',') + '">' + ic('salvar', 's') + 'Adicionar à minha lista' + (novos < asins.length ? ' (' + novos + ' novos)' : '') + '</button>' :
          '<a class="btn" href="./?lista" data-r>Todos já estão na sua lista</a>') + '</div>' +
        '<ul class="lst">' + itens.map(function (i) { return linhaLista(i, null, false); }).join('') + '</ul>';
      rolar(); focarTela();
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar a lista'); });
  }

  // ---------- como funciona ----------
  function leitura(iso) {      // "13/10 às 14:05", no horário de Brasília
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var p = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(d).reduce(function (a, x) { a[x.type] = x.value; return a; }, {});
    return p.day + '/' + p.month + ' às ' + p.hour + ':' + p.minute;
  }

  function sobre() {
    titulo('Como funciona');
    META.then(function (m) {
      if (rotaAtual.v !== 'sobre') return;
      app.innerHTML = '<article class="prosa"><h1>Como funciona</h1>' +
        '<p class="mu lead">Preços dos livros mais vendidos da Amazon.com.br, lidos todo dia' +
        (m.lido_ate ? ' (preços lidos até ' + leitura(m.lido_ate) + ')' : m.ultima_coleta ? ' (última leitura em ' + L.dl(m.ultima_coleta) + ')' : '') +
        '. O site mostra os números; a decisão é sua.</p>' +
        '<h2>Os números</h2><dl>' +
        '<dt>Preço de cada dia</dt><dd>O último preço lido no dia. Se o preço muda mais de uma vez no mesmo dia, o gráfico mostra o do fim do dia.</dd>' +
        '<dt>Preço mais comum</dt><dd>A mediana dos preços dos últimos 90 dias. Aparece com ' + L.MIN_COMUM + ' dias de coleta.</dd>' +
        '<dt>Menor e maior</dt><dd>O menor e o maior preço dos últimos 90 dias.</dd>' +
        '<dt>Preço de capa</dt><dd>O preço que a Amazon mostra riscado na lista de mais vendidos, de cada formato: no Kindle, o preço digital sugerido. Só aparece quando há desconto.</dd>' +
        '<dt>Formatos</dt><dd>Kindle e livro físico (capa comum, capa dura…) têm preço e histórico separados. Na busca, o preço é o do formato mais barato, e o nome dele vem ao lado.</dd>' +
        '<dt>Menor preço registrado</dt><dd>O menor preço desde o início da coleta, quando o livro tem ' + L.MIN_COMUM + ' dias de coleta ou mais.</dd>' +
        '<dt>Baixaram de preço</dt><dd>Queda de 5% ou mais nas duas últimas coletas.</dd>' +
        '<dt>Preço-alvo</dt><dd>O preço que você quer pagar. Fica só neste aparelho; o site não manda avisos.</dd>' +
        '<dt>Parecidos</dt><dd>Livros de outros autores com gênero e idioma em comum e, em livros de não ficção, palavras do título em comum ("python", "investimentos"). A lista de cada livro é calculada quando o site é gerado; no início, o seu navegador junta as listas dos livros da sua lista e dos que você viu ("como …" diz de qual veio). Nada sai do aparelho.</dd>' +
        '<dt>Datas de promoção</dt><dd>O preço no dia, comparado com o dos 90 dias anteriores.</dd></dl>' +
        '<h2>Limites</h2><ul><li>Só entram os ~2.000 mais vendidos de cada categoria, vendidos pela própria Amazon.</li>' +
        '<li>Dias sem coleta ficam em branco no gráfico.</li><li>O preço pode mudar a qualquer momento. Confira na loja.</li></ul>' +
        '<h2>Privacidade</h2><p>Não há conta. A sua lista fica só no seu navegador.</p>' +
        '<p class="mu sm">Este site não tem vínculo com a Amazon.</p></article>';
      rolar(); focarTela();
    });
  }

  // ---------- eventos globais ----------
  document.addEventListener('click', function (e) {
    if (e.target.closest('.pular')) { e.preventDefault(); focarTela(true); return; }
    var a = e.target.closest('a[data-r]');
    if (a && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) { e.preventDefault(); ir(a.getAttribute('href'), a.hasAttribute('data-sub'), false, app.contains(a) ? a.getAttribute('href') : null); return; }
    var b = e.target.closest('button'); if (!b) return;
    var acao = b.dataset.acao;
    // sino: salva sem sair da tela; o aviso leva à lista com o campo do preço-alvo aberto
    if (b.dataset.watch) {
      var aw = b.dataset.watch, ja = Lista.tem(aw);
      if (!ja) { Lista.alternar(aw); contador(); botaoSalvar(); }
      toast(ja ? 'Já está na sua lista' : 'Salvo na sua lista', 'Definir preço-alvo', function () { pendenteAlvo = aw; ir('./?lista'); });
    }
    else if(b.dataset.view){document.body.dataset.view=b.dataset.view;document.querySelectorAll('.view-switch [data-view]').forEach(function(v){v.setAttribute('aria-pressed',String(v===b));});}
    else if (b.id === 'tema') { var t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'; aplicarTema(t); try { localStorage.setItem('observador-tema', t); } catch (e) { } }
    else if (b.dataset.fam) { if (S.fam[b.dataset.fam]) delete S.fam[b.dataset.fam]; else S.fam[b.dataset.fam] = 1; aplicarBusca(); }
    else if (b.dataset.idioma !== undefined) { S.i = S.i === b.dataset.idioma ? '' : b.dataset.idioma; aplicarBusca(); }
    else if (b.dataset.baixa !== undefined) { filtroBaixa = b.dataset.baixa; baixaTudo = false; destaques().then(function (x) { secaoBaixa(x); focarEl($('[data-baixa="' + filtroBaixa + '"]')); }); }
    else if (b.dataset.salvar) {
      var na = Lista.alternar(b.dataset.salvar); botaoSalvar(); contador();
      toast(na ? 'Salvo na sua lista' : 'Removido da sua lista', na ? 'Ver lista' : null, function () { ir('./?lista'); });
    } else if (b.dataset.remover) {
      var asin = b.dataset.remover, pos = Lista.ler().indexOf(asin), li = b.closest('li');
      var viz = li && (li.nextElementSibling || li.previousElementSibling), vb = viz && viz.querySelector('[data-remover]');
      Lista.remover(asin); contador();
      if (vb) focoApos = '[data-remover="' + vb.dataset.remover + '"]'; else focar = true;     // sem vizinha: lista vazia, foco no título
      lista();
      toast('Removido da sua lista', 'Desfazer', function () { Lista.inserir(asin, pos); contador(); if (rotaAtual.v === 'lista') { focoApos = '[data-remover="' + asin + '"]'; lista(); } });
    }
    else if (acao === 'mais') maisResultados();
    else if (acao === 'preco') { verPreco = !verPreco; if (!verPreco) { S.de = S.ate = null; aplicarBusca(); } else { ferramentas(); resultados(); var i = $('#de'); if (i) i.focus(); } }
    else if (acao === 'limpar-filtros') { var fora = !b.closest('#ferr'); S.fam = {}; S.i = ''; S.g = ''; S.de = S.ate = null; verPreco = false; aplicarBusca(); if (fora) focarEl($('#ferr .chip')); }
    else if (acao === 'baixa-tudo') {
      // o foco vai ao 1º livro que estava escondido (no computador a estante mostra só uma fileira; no celular, os 12)
      var est0 = $('#baixa .estante'), vis = est0 ? [].filter.call(est0.children, function (c) { return !c.inert; }).length : 0;
      baixaTudo = true; destaques().then(function (x) { secaoBaixa(x); focarEl($('#baixa .grade').children[vis] || $('#baixa h2')); });
    }
    else if (acao === 'voltar') voltar();
    else if (acao === 'abrir-estante') {
      var sec = b.closest('section'), est = sec && sec.querySelector('.estante');
      var novo = est && [].filter.call(est.children, function (c) { return c.inert; })[0];
      if (est) { est.className = 'grade'; [].forEach.call(est.children, function (c) { c.inert = false; }); }
      b.remove(); focarEl(novo || (sec && sec.querySelector('h2')));
    }
    else if (acao === 'limpar-recentes') {
      Lista.limparRecentes(); var sr = b.closest('section'), par = $('#parecidos'), r = rotaAtual;
      // "Parecidos" deixa de usar os vistos: some sem lista; com lista, é refeito (e o foco pula a seção, que será redesenhada)
      if (par && !Lista.ler().length) { par.remove(); par = null; }
      else if (par) parecidosInicio();
      var prox = sr && sr.nextElementSibling;
      if (prox && prox === par) prox = par.nextElementSibling;
      if (sr) sr.remove();
      focarEl((prox && prox.querySelector('h2, a, button')) || app.querySelector('h1'));
    }
    else if (b.dataset.alvo) {
      var ali = b.closest('.alvo'), at = Lista.alvos()[b.dataset.alvo];
      ali.innerHTML = '<form class="alvo-f" data-alvo-f="' + b.dataset.alvo + '"><label class="vh" for="alvo-v-' + b.dataset.alvo + '">Preço-alvo em reais</label>' +
        '<input id="alvo-v-' + b.dataset.alvo + '" type="number" inputmode="decimal" min="0" step="0.01" placeholder="R$" value="' + (at ? (at / 100).toFixed(2) : '') + '">' +
        '<button type="submit" class="btn sm pri">Salvar</button>' + (at ? '<button type="button" class="btn sm gh" data-acao="tirar-alvo">Tirar</button>' : '') + '</form>';
      ali.querySelector('input').focus();
    }
    else if (acao === 'tirar-alvo') { var ta = b.closest('form').dataset.alvoF; Lista.definirAlvo(ta, 0); focoApos = '[data-alvo="' + ta + '"]'; lista(); }
    else if (acao === 'buscar') { q.focus(); scrollTo(0, 0); }
    else if (acao === 'recarregar') location.reload();
    else if (acao === 'compartilhar') compartilhar(location.href, document.title);
    else if (acao === 'compartilhar-lista') compartilhar(location.origin + location.pathname + '?lista=' + Lista.ler().join(','), 'Minha lista de livros');
    else if (acao === 'importar') { var n = Lista.importar(b.dataset.asins).adicionados; contador(); ir('./?lista', true); toast(L.plural(n, 'livro adicionado', 'livros adicionados') + ' à sua lista'); }
  });
  app.addEventListener('submit', function (e) {
    var f = e.target.closest('[data-alvo-f]'); if (!f) return;
    e.preventDefault();
    var inp = f.querySelector('input'), v = parseFloat(String(inp.value).replace(',', '.'));
    // valor vazio ou inválido não apaga o alvo em silêncio: avisa junto do campo (tirar o alvo é o botão "Tirar")
    if (!(isFinite(v) && v > 0)) {
      var er = f.querySelector('.erro-campo');
      var eid = 'alvo-erro-' + f.dataset.alvoF;
      if (er) er.remove();                                  // reinserido, para o alerta ser anunciado de novo
      f.insertAdjacentHTML('beforeend', '<p class="erro-campo" id="' + eid + '" role="alert">Digite um preço maior que zero.</p>');
      inp.setAttribute('aria-invalid', 'true'); inp.setAttribute('aria-describedby', eid); inp.focus();
      return;
    }
    Lista.definirAlvo(f.dataset.alvoF, Math.round(v * 100));
    focoApos = '[data-alvo="' + f.dataset.alvoF + '"]';
    lista();
  });
  window.addEventListener('popstate', function () { var st = history.state || {}; scrollAlvo = st.y || 0; focoVolta = st.foco || null; focar = true; desenhar(); });
  window.addEventListener('storage', function (e) { if (e.key === 'lista_v1') { contador(); if (rotaAtual.v === 'lista' && !rotaAtual.comp) lista(); } });

  // ---------- início ----------
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  if (location.hash === '#lista') history.replaceState({ n: 0 }, '', './?lista');
  else if (!history.state) history.replaceState({ n: 0, y: 0 }, '');
  contador();
  META.then(function (m) { meta = m; }, function () { erro('Não consegui carregar o catálogo'); });
  desenhar();
  // o índice da busca é grande: no início e na busca, começa a baixar logo, para a busca estar pronta quando a
  // pessoa digitar; na página de um livro ou na lista (links compartilhados), só quando ela for buscar
  if (rotaAtual.v === 'inicio' || rotaAtual.v === 'busca') indice().catch(function () { });
  q.addEventListener('focus', function () { indice().catch(function () { }); });
})();
