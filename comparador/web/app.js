/* App de página única: início, busca, página do livro, minha lista e "como funciona".
 * Endereços: ./  ./?q=…  ./?livro=ASIN  ./?lista  ./?lista=ASIN,ASIN (lista compartilhada)  ./?sobre
 * Dados em dados/*.json, gerados por `python -m comparador site` (formato descrito em site.py). */
(function () {
  'use strict';
  var L = window.Livro, Lista = window.Lista, Busca = window.Busca, esc = L.esc, brl = L.brl;
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
    alerta: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/>', livro: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5V21h16"/>'
  };
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
        var fim = Math.min(i + 3000, linhas.length);
        lerObras(x, linhas, i, fim); i = fim;
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
  function matiz(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) % 360; return h; }
  function capa(o, cls, alt) {
    cls = 'cv' + (cls ? ' ' + cls : '');
    var tam = /\bg\b/.test(cls) ? 436 : /\bp\b/.test(cls) ? 218 : /\bf\b/.test(cls) ? 327 : 218;
    if (o.img) return '<div class="' + cls + '" data-t="' + esc(o.t) + '"><img src="' + CAPA + encodeURIComponent(o.img) + '._AC_UY' + tam + '_.jpg" alt="' + (alt ? esc('Capa de ' + o.t) : '') + '" loading="lazy" decoding="async"></div>';
    return placeholder(o.t, cls);
  }
  function placeholder(t, cls) { return '<div class="' + cls + ' ph" style="--h:' + matiz(t || '') + '" aria-hidden="true"><span>' + esc(t) + '</span></div>'; }
  // capa que não carrega vira a capa gerada
  document.addEventListener('error', function (e) {
    var img = e.target; if (img.tagName !== 'IMG' || !img.parentNode || !img.parentNode.classList.contains('cv')) return;
    var d = img.parentNode; d.outerHTML = placeholder(d.dataset.t || '', d.className);
  }, true);

  function etiquetaIdioma(o) { return o.idioma && o.idioma !== 'Português' ? ' <span class="tag">' + esc(o.idioma) + '</span>' : ''; }
  function subtitulo(o, extra) { return [esc(o.autor), o.ano || '', extra].filter(Boolean).join(' · ') + etiquetaIdioma(o); }
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
    return '<li><a class="row" href="./?livro=' + m.asin + '" data-r>' + capa(o) + '<div class="bd"><div class="tt">' + esc(o.t) + '</div>' +
      '<div class="sub">' + subtitulo(o) + '</div><div class="pr">' + (preco || ((eds.length > 1 ? '<span class="de">a partir de</span>' : '') + '<b>' + brl(m.preco) + '</b>' + pillComum(m.preco, m.mc) + velho)) +
      '</div><div class="eds">' + formatos + '</div></div>' + (o.eds.some(function (e) { return sv[e.asin]; }) ? SALVO : '') + '</a></li>';
  }
  function esqueleto(n) {
    var r = '<div class="sk-row"><div class="cv sk"></div><div style="flex:1"><div class="sk l" style="width:70%"></div><div class="sk l" style="width:40%"></div><div class="sk l" style="width:25%;height:16px"></div></div></div>';
    return '<div class="card">' + new Array(n + 1).join(r) + '</div>';
  }
  function erro(msg) {
    app.innerHTML = '<div class="erro"><div class="vazio"><div class="ic">' + ic('alerta') + '</div><h2>' + esc(msg) + '</h2><p>Verifique a conexão e tente de novo.</p>' +
      '<button type="button" class="btn pri" data-acao="recarregar">Tentar de novo</button></div></div>';
  }
  var tToast = null;
  function toast(msg, acao, fn) {
    var t = $('#toast');
    t.innerHTML = '<span>' + esc(msg) + '</span>' + (acao ? '<button type="button">' + esc(acao) + '</button>' : '');
    if (acao) t.querySelector('button').onclick = function () { t.classList.remove('on'); fn(); };
    t.classList.add('on'); clearTimeout(tToast); tToast = setTimeout(function () { t.classList.remove('on'); }, 5000);
  }
  function contador() { var n = Lista.ler().length; $('#cont').textContent = n ? String(n) : ''; }
  function titulo(t) { document.title = t ? t + ' · Preços de livros' : 'Preços de livros: histórico de preço de livros da Amazon'; }
  function compartilhar(url, t) {
    if (navigator.share) { navigator.share({ title: t, url: url }).catch(function () { }); return; }
    var ok = function () { toast('Link copiado'); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, function () { prompt('Copie o link:', url); });
    else prompt('Copie o link:', url);
  }

  // ---------- rotas ----------
  var rotaAtual = null, scrollAlvo = null;
  function rota() {
    var p = new URLSearchParams(location.search);
    if (p.has('livro')) return { v: 'livro', asin: (p.get('livro') || '').toUpperCase() };
    if (p.has('lista') || location.hash === '#lista') return { v: 'lista', comp: p.get('lista') || '' };
    if (p.has('sobre')) return { v: 'sobre' };
    if (['q', 'f', 'i', 'g', 'o', 'de', 'ate'].some(function (k) { return p.get(k); })) return { v: 'busca' };
    return { v: 'inicio' };
  }
  function ir(url, substituir) {
    var st = history.state || {};
    history.replaceState({ y: scrollY, n: st.n || 0 }, '');
    history[substituir ? 'replaceState' : 'pushState']({ y: 0, n: (st.n || 0) + (substituir ? 0 : 1) }, '', url);
    scrollAlvo = 0; desenhar();
  }
  function rolar() { if (scrollAlvo != null) { scrollTo(0, scrollAlvo); scrollAlvo = null; } }
  function voltar() { if ((history.state || {}).n > 0) history.back(); else ir('./'); }
  function desenhar() {
    var r = rota(); rotaAtual = r;
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
    if (!DEST) app.innerHTML = '<section class="boas sec"><div class="sk l" style="height:28px;width:60%"></div><div class="sk l" style="width:80%;margin-top:14px"></div></section>' + esqueleto(4);
    Promise.all([destaques(), META, EVENTOS]).then(function (rs) {
      if (!aindaEm(r)) return;
      var x = rs[0], m = rs[1], ev = rs[2], sv = salvos(), out = [];
      out.push('<section class="boas sec"><h1>Veja se o preço de um livro está bom antes de comprar</h1><p>Histórico de preço de ' + m.itens.toLocaleString('pt-BR') +
        ' livros mais vendidos da Amazon.com.br, atualizado todo dia. Busque um título para ver quanto ele custa agora e quanto já custou.</p>' +
        (m.aviso ? '<p class="aviso">' + esc(m.aviso) + '</p>' : '') + '</section>');
      if (Lista.ler().length) out.push('<section class="sec" id="sua-lista"></section>');
      var prox = ev.filter(function (e) { return e[1] >= x.hoje; }).sort(function (a, b) { return a[1] - b[1]; })[0];
      if (prox) {
        var d = new Date((prox[1] - 719163) * 864e5), faltam = prox[1] - x.hoje;
        out.push('<section class="sec card pad prox"><div class="dia"><b>' + d.getUTCDate() + '</b><small>' + L.dmes(prox[1]).split(' ')[1] + '</small></div><div><h3>' + esc(prox[0]) + '</h3><p class="mu sm">' +
          (faltam === 0 ? 'É hoje.' : 'Daqui a ' + L.plural(faltam, 'dia', 'dias') + '.') + ' Salve os livros que você quer comprar para comparar o preço deles no dia com o preço dos meses anteriores.</p></div></section>');
      }
      out.push('<section class="sec" id="baixa"></section>');
      app.innerHTML = out.join('');
      secaoBaixa(x, sv);
      rolar();
      if ($('#sua-lista')) indiceCompleto().then(function (ix) { if (aindaEm(r)) suaLista(ix); });
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar o catálogo'); });
  }
  function suaLista(x) {
    var el = $('#sua-lista'); if (!el) return;
    var meus = Lista.ler().slice().reverse().map(function (a) { return x.porAsin[a]; }).filter(Boolean).slice(0, 12);
    if (!meus.length) { el.remove(); return; }
    el.innerHTML = '<div class="sec-h"><h2>Sua lista</h2><a href="./?lista" data-r>Ver tudo</a></div><div class="fila">' +
      meus.map(function (e) { return '<a href="./?livro=' + e.asin + '" data-r>' + capa(e.o, 'f') + '<span class="t">' + esc(e.o.t) + '</span><b>' + brl(e.preco) + '</b></a>'; }).join('') + '</div>';
  }
  function secaoBaixa(x, sv) {
    var el = $('#baixa'); if (!el) return;
    var itens = x.baixa.map(function (b) { var e = x.porAsin[b[0]]; return e && { e: e, ant: b[1], dia: b[2] }; }).filter(Boolean);
    if (!itens.length) { el.remove(); return; }
    var tem = {}; itens.forEach(function (i) { tem[i.e.fam] = 1; });
    var vis = itens.filter(function (i) { return !filtroBaixa || i.e.fam === filtroBaixa; }), lim = baixaTudo ? vis.length : 8;
    var chips = FAMILIAS.filter(function (f) { return tem[f[0]]; });
    el.innerHTML = '<div class="sec-h"><div><h2>Baixaram de preço</h2><p class="mu sm">Ficaram mais baratos nas últimas coletas, em relação ao preço anterior.</p></div></div>' +
      (chips.length > 1 ? '<div class="chips" style="margin-bottom:12px"><button type="button" class="chip" data-baixa="" aria-pressed="' + !filtroBaixa + '">Todos</button>' +
        chips.map(function (f) { return '<button type="button" class="chip" data-baixa="' + f[0] + '" aria-pressed="' + (filtroBaixa === f[0]) + '">' + f[1] + '</button>'; }).join('') + '</div>' : '') +
      '<ul class="lst card">' + vis.slice(0, lim).map(function (i) {
        var p = Math.round((i.ant - i.e.preco) / i.ant * 100);
        return linhaObra(i.e.o, [i.e], sv, '<b>' + brl(i.e.preco) + '</b><s class="de">' + brl(i.ant) + '</s><span class="pill dn">' + ic('queda', 's') + p + '% mais barato</span>');
      }).join('') + '</ul>' + (vis.length > lim ? '<div class="mais"><button type="button" class="btn sm" data-acao="baixa-tudo">Ver todos (' + vis.length + ')</button></div>' : '');
  }

  // ---------- busca ----------
  var VAZIO = function () { return { q: '', fam: {}, i: '', g: '', o: 'rel', de: null, ate: null }; };
  var S = VAZIO(), mostrados = 30, verPreco = false, resultado = null;
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
    if (!$('#ferr')) app.innerHTML = '<div class="ferr" id="ferr"></div><div aria-live="polite" class="cont" id="cont-res"></div><div id="res" style="margin-top:10px"></div>';
    ferramentas(); resultados(); if (!parte) rolar();
  }
  function ferramentas() {
    var c = resultado.cont, chips = FAMILIAS.map(function (f) {
      return '<button type="button" class="chip" data-fam="' + f[0] + '" aria-pressed="' + !!S.fam[f[0]] + '">' + f[1] + (c.fam[f[0]] ? ' <span class="n">' + c.fam[f[0]].toLocaleString('pt-BR') + '</span>' : '') + '</button>';
    }).join('');
    var idiomas = Object.keys(c.i).sort(function (a, b) { return c.i[b] - c.i[a]; }).slice(0, 4);
    if (S.i && idiomas.indexOf(S.i) < 0) idiomas.push(S.i);
    if (idiomas.length > 1 || S.i) chips += '<span class="sep"></span>' + idiomas.map(function (i) { return '<button type="button" class="chip" data-idioma="' + esc(i) + '" aria-pressed="' + (S.i === i) + '">' + esc(i) + '</button>'; }).join('');
    var faixa = S.de != null || S.ate != null;
    chips += '<span class="sep"></span><button type="button" class="chip" data-acao="preco" aria-pressed="' + (faixa || verPreco) + '">' +
      (faixa ? (S.de != null ? brl(S.de) : 'R$ 0') + ' a ' + (S.ate != null ? brl(S.ate) : 'qualquer') : 'Preço') + ' ' + ic('baixo', 's') + '</button>';
    var ords = [['rel', 'Mais relevantes']];
    if (idx.temAv) ords.push(['avaliacoes', 'Mais avaliados']);
    ords.push(['preco', 'Menor preço'], ['preco_desc', 'Maior preço'], ['desconto', 'Maior desconto sobre a capa']);
    if (idx.temMC) ords.push(['abaixo', 'Mais abaixo do preço comum']);
    ords.push(['titulo', 'Título (A a Z)']);
    var gens = idx.gen.map(function (g, i) { return [g[0], g[1], c.g[i] || 0]; }).filter(function (g) { return g[2] || g[0] === S.g; })
      .sort(function (a, b) { return a[1].localeCompare(b[1], 'pt-BR'); });
    var selGen = gens.length ? '<label class="sel"><span class="vh">Gênero</span><select id="gen"><option value="">Todos os gêneros</option>' +
      gens.map(function (g) { return '<option value="' + g[0] + '"' + (S.g === g[0] ? ' selected' : '') + '>' + esc(g[1]) + ' (' + g[2].toLocaleString('pt-BR') + ')</option>'; }).join('') +
      '</select>' + ic('baixo', 's') + '</label>' : '';
    $('#ferr').innerHTML = '<div class="chips" role="group" aria-label="Filtros">' + chips + '</div>' +
      (verPreco || faixa ? '<div class="faixa-preco"><span class="mu sm">Preço</span><input id="de" type="number" inputmode="decimal" min="0" step="1" placeholder="de R$" aria-label="Preço mínimo em reais" value="' + (S.de != null ? S.de / 100 : '') + '">' +
        '<span class="mu sm">até</span><input id="ate" type="number" inputmode="decimal" min="0" step="1" placeholder="até R$" aria-label="Preço máximo em reais" value="' + (S.ate != null ? S.ate / 100 : '') + '"></div>' : '') +
      '<div class="l2"><span></span><div class="sels">' + selGen + '<label class="sel"><span class="vh">Ordenar por</span><select id="ord">' + ords.map(function (o) { return '<option value="' + o[0] + '"' + (S.o === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' + ic('baixo', 's') + '</label></div></div>';
  }
  function curta() { var t = S.q.trim(); return t.length === 1 && !L.asinDe(t) && !nFiltros() && S.o === 'rel'; }
  function resultados() {
    if (curta()) {
      $('#ferr .l2 > span').innerHTML = ''; $('#cont-res').textContent = '';
      $('#res').innerHTML = '<p class="nota-busca">Continue digitando…</p>';
      return;
    }
    var r = resultado.lista, el = $('#res'), n = r.length, sv = salvos(), carregando = !idx.completo;
    $('#ferr .l2 > span').innerHTML = '<span class="cont">' + (n ? n.toLocaleString('pt-BR') + (n === 1 ? ' livro' : ' livros') + (carregando ? ' até agora' : '') : '') + '</span>' +
      (nFiltros() ? ' <button type="button" class="btn gh sm" data-acao="limpar-filtros">Limpar filtros</button>' : '');
    $('#cont-res').textContent = '';
    var nota = resultado.correcao ? '<p class="nota-busca">Mostrando resultados para <b>' + esc(resultado.correcao) + '</b></p>' :
      resultado.parcial ? '<p class="nota-busca">Nenhum livro tem todas as palavras. Estes têm a maior parte delas.</p>' : '';
    var status = carregando ? '<p class="nota-busca carregando" role="status"><span class="giro" aria-hidden="true"></span>Buscando no restante do catálogo…</p>' :
      idx.falhou ? '<p class="nota-busca">Parte do catálogo não carregou. <button type="button" class="btn gh sm" data-acao="recarregar">Tentar de novo</button></p>' : '';
    if (!n) {
      // enquanto falta parte do índice, "nada encontrado" ainda não é verdade
      if (carregando) { el.innerHTML = status + esqueleto(3); return; }
      el.innerHTML = status + '<div class="vazio"><div class="ic">' + ic('busca') + '</div><h2>Nenhum livro encontrado</h2><p>' +
        (S.q.trim() ? 'Nada para "' + esc(S.q.trim()) + '"' + (nFiltros() ? ' com esses filtros' : '') + '. ' : '') +
        'O catálogo cobre os ~2.000 mais vendidos de cada categoria de livros da Amazon. Tente menos palavras' + (nFiltros() ? ' ou limpe os filtros' : '') + '.</p>' +
        (nFiltros() ? '<button type="button" class="btn" data-acao="limpar-filtros">Limpar filtros</button>' : '') + '</div>';
      return;
    }
    el.innerHTML = nota + status + '<ul class="lst card">' + r.slice(0, mostrados).map(function (x) { return linhaObra(x.o, x.eds, sv); }).join('') + '</ul>' +
      (n > mostrados ? '<div class="mais"><button type="button" class="btn sm" data-acao="mais" id="mais">Mostrar mais</button></div>' : '');
    observarMais();
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
    if (mostrados >= resultado.lista.length) { var m = $('#res .mais'); if (m) m.remove(); }
  }
  function aplicarBusca() {
    var url = urlBusca();
    if (url === './') { if (rotaAtual && rotaAtual.v === 'busca') ir('./', true); return; }
    if (rotaAtual && rotaAtual.v === 'busca') { history.replaceState(history.state, '', url); mostrados = 30; scrollTo(0, 0); busca(false); }
    else ir(url);
  }
  var tBusca = null;
  q.addEventListener('input', function () {
    $('#limpa').hidden = !q.value;
    clearTimeout(tBusca);
    tBusca = setTimeout(function () {
      if (!rotaAtual || rotaAtual.v !== 'busca') S = VAZIO();
      S.q = q.value; aplicarBusca();
    }, 150);
  });
  q.form.addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(tBusca); if (rotaAtual.v !== 'busca') S = VAZIO(); S.q = q.value; aplicarBusca(); q.blur(); });
  q.addEventListener('keydown', function (e) { if (e.key === 'Escape') { q.value = ''; q.dispatchEvent(new Event('input')); } });
  $('#limpa').addEventListener('click', function () { q.value = ''; q.focus(); q.dispatchEvent(new Event('input')); });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); q.focus(); q.select(); }
  });
  app.addEventListener('change', function (e) {
    if (e.target.id === 'ord') { S.o = e.target.value; aplicarBusca(); }
    else if (e.target.id === 'gen') { S.g = e.target.value; aplicarBusca(); }
    else if (e.target.id === 'ordl') { ordemLista = e.target.value; lista(); }
  });
  var tPreco = null;
  app.addEventListener('input', function (e) {
    if (e.target.id !== 'de' && e.target.id !== 'ate') return;
    var v = parseFloat(String(e.target.value).replace(',', '.'));
    S[e.target.id] = isFinite(v) && v >= 0 ? Math.round(v * 100) : null;
    clearTimeout(tPreco);
    tPreco = setTimeout(function () { history.replaceState(history.state, '', urlBusca()); mostrados = 30; resultado = buscar(idx); resultados(); }, 300);
  });

  // ---------- página do livro ----------
  function livro(asin) {
    var r = rotaAtual;
    titulo('Livro');
    app.innerHTML = '<button type="button" class="voltar" data-acao="voltar">' + ic('voltar', 's') + 'Voltar</button><div class="heroi"><div class="cv g sk"></div><div><div class="sk l" style="height:26px;width:80%"></div>' +
      '<div class="sk l" style="width:40%;margin-top:12px"></div><div class="sk l" style="height:40px;width:30%;margin-top:28px"></div></div></div>';
    if (!/^[A-Z0-9]{10}$/.test(asin)) return naoEncontrado();
    Promise.all([historico(asin), EVENTOS, META]).then(function (rs) {
      if (!aindaEm(r)) return;
      var l = rs[0], ev = rs[1], m = rs[2];
      if (!l) return naoEncontrado();
      var lt = L.limpar(l.t || asin), o = { t: lt.t, autor: l.autor || '', img: l.imagem || '', ano: l.publicado ? +l.publicado.slice(0, 4) : 0, idioma: l.idioma || lt.idioma };
      var tr = l.h, ult = tr[tr.length - 1][1], f = L.fatos(tr, ult), recente = m.ultima_coleta == null || ult >= m.ultima_coleta - 1;
      titulo(o.t);
      var det = [l.publicado ? 'Publicado em ' + L.dlongo(new Date(l.publicado + 'T12:00:00Z').getTime() / 864e5 + 719163 | 0) : '', o.idioma, 'ASIN ' + asin].filter(Boolean);
      app.innerHTML = '<button type="button" class="voltar" data-acao="voltar">' + ic('voltar', 's') + 'Voltar</button>' +
        (m.aviso ? '<p class="aviso">' + esc(m.aviso) + '</p>' : '') +
        '<section class="heroi sec">' + capa(o, 'g', true) + '<div><h1>' + esc(o.t) + '</h1>' + (o.autor ? '<p class="aut">' + esc(o.autor) + '</p>' : '') +
        '<p class="det">' + det.map(esc).join(' · ') + '</p><div class="fmts" id="fmts" role="group" aria-label="Formato">' +
        (l.eds || [[asin, l.f || 'Livro', f.preco]]).map(function (d) {
          return '<a class="fmt" href="./?livro=' + d[0] + '" data-r data-sub' + (d[0] === asin ? ' aria-current="true"' : '') + '><span>' + esc(d[1]) + '</span><b>' + brl(d[0] === asin ? f.preco : d[2]) + '</b></a>';
        }).join('') + '</div></div>' +
        '<div class="compra"><div class="preco-g"><b>' + brl(f.preco) + '</b><span class="mu sm">' + (recente ? 'preço em ' + L.dl(ult) : 'último preço visto, em ' + L.dl(ult)) + '</span></div>' +
        '<div class="fat">' + (recente ? '' : '<span class="pill wr">Sem coleta recente: pode ter saído de estoque ou deixado de ser vendido pela Amazon</span>') + L.comparacoes(f) + '</div>' +
        '<div class="acoes"><a class="btn pri" href="' + L.linkAmazon(asin) + '" target="_blank" rel="noopener noreferrer">Ver na Amazon ' + ic('ext', 's') + '</a>' +
        '<button type="button" class="btn salvar" data-salvar="' + asin + '"></button>' +
        '<button type="button" class="btn" data-acao="compartilhar" aria-label="Compartilhar">' + ic('share', 's') + '</button></div></div></section>' +
        '<section class="card pad sec"><div id="graf"></div>' + L.avisoDados(f) + L.estatisticas(f, tr[0][0]) + '</section>' +
        L.secaoEventos(tr, ev, m.ultima_coleta || ult) + outrasEdicoes(l.outras);
      botaoSalvar();
      L.grafico($('#graf'), L.dadosGrafico(tr, ev));
      rolar();
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar este livro'); });
  }
  function botaoSalvar() {
    var b = $('[data-salvar]'); if (!b) return;
    var na = Lista.tem(b.dataset.salvar);
    b.setAttribute('aria-pressed', String(na)); b.innerHTML = ic('salvar', 's') + (na ? 'Na sua lista' : 'Salvar na lista');
  }
  // outras edições do mesmo título e autor (calculadas em site.py): [[asin, título, capa, formato, preço], ...]
  function outrasEdicoes(outras) {
    if (!outras || !outras.length) return '';
    return '<section class="sec"><div class="sec-h"><h2>Outras edições</h2></div><ul class="lst card">' + outras.map(function (c) {
      var o = { t: L.limpar(c[1]).t, img: c[2] };
      return '<li><a class="row" href="./?livro=' + c[0] + '" data-r>' + capa(o) + '<div class="bd"><div class="tt">' + esc(o.t) + '</div>' +
        '<div class="pr"><b>' + brl(c[4]) + '</b></div><div class="eds"><span>' + esc(c[3]) + '</span></div></div></a></li>';
    }).join('') + '</ul></section>';
  }
  function naoEncontrado() {
    titulo('Livro não encontrado');
    app.innerHTML = '<div class="vazio"><div class="ic">' + ic('livro') + '</div><h2>Livro não encontrado</h2><p>Esse livro não está no catálogo. O catálogo cobre os ~2.000 mais vendidos de cada categoria de livros da Amazon.</p>' +
      '<a class="btn pri" href="./" data-r>Ir para o início</a></div>';
  }

  // ---------- minha lista ----------
  var ordemLista = 'recentes';
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
  function linhaLista(i, base, remover) {
    if (i.fora) return '<li><div class="row">' + placeholder(i.asin, 'cv p') + '<div class="bd"><div class="tt">' + i.asin + '</div><div class="sub">Fora do catálogo: não há preço registrado</div></div>' +
      (remover ? '<div class="lado"><button type="button" class="ib rm" data-remover="' + i.asin + '" aria-label="Remover da lista">' + ic('x', 's') + '</button></div>' : '') + '</div></li>';
    var antes = base && base.precos[i.asin], dif = antes && antes !== i.preco ? i.preco - antes : 0;
    var mud = dif ? '<span class="pill ' + (dif < 0 ? 'dn' : 'up') + '">' + (dif < 0 ? '▼ ' : '▲ ') + brl(Math.abs(dif)) + ' desde ' + L.dmes(base.dia) + '</span>' : '';
    return '<li><div class="row">' + capa(i.o, 'p') + '<div class="bd"><a class="tt esticar" href="./?livro=' + i.asin + '" data-r>' + esc(i.o.t) + '</a><div class="sub">' + subtitulo(i.o, esc(i.fmt)) + '</div>' +
      '<div class="pr"><b>' + brl(i.preco) + '</b>' + mud + pillComum(i.preco, i.mc) + (i.recente ? '' : '<span class="pill wr">último preço visto em ' + L.dl(i.ult) + '</span>') + '</div></div>' +
      '<div class="lado">' + (remover ? '<button type="button" class="ib rm" data-remover="' + i.asin + '" aria-label="Remover ' + esc(i.o.t) + ' da lista">' + ic('x', 's') + '</button>' : '') + spark(i.tr, i.ult) + '</div></div></li>';
  }
  function lista() {
    var r = rotaAtual, asins = Lista.ler();
    titulo('Minha lista');
    if (!asins.length) {
      app.innerHTML = '<div class="vazio"><div class="ic">' + ic('salvar') + '</div><h1 style="font-size:22px;margin-bottom:6px">Sua lista está vazia</h1>' +
        '<p>Salve os livros que você quer acompanhar: aqui você vê o preço de todos de uma vez e o que mudou desde a sua última visita. Não precisa de cadastro.</p>' +
        '<button type="button" class="btn pri" data-acao="buscar">' + ic('busca', 's') + 'Buscar livros</button></div>';
      return;
    }
    if (!$('#lst')) app.innerHTML = '<div class="lista-h"><div><h1>Minha lista</h1><p class="mu" style="margin:4px 0 0">' + L.plural(asins.length, 'livro', 'livros') + '</p></div></div>' + esqueleto(Math.min(asins.length, 5));
    carregarItens(asins).then(function (rs) {
      if (!aindaEm(r)) return;
      var m = rs[0], hoje = m.ultima_coleta, itens = rs.slice(1).map(function (it) { return itemLista(it, hoje); });
      var precos = {}; itens.forEach(function (i) { if (!i.fora) precos[i.asin] = i.preco; });
      var base = Lista.visita(hoje, precos), mais = 0, menos = 0;
      itens.forEach(function (i) { var a = base && base.precos[i.asin]; if (a && !i.fora) { if (i.preco < a) menos++; else if (i.preco > a) mais++; } });
      var ordens = [['recentes', 'Adicionados por último'], ['preco', 'Menor preço']];
      if (base) ordens.push(['queda', 'Maior queda desde a última visita']);
      if (itens.some(function (i) { return i.mc; })) ordens.push(['abaixo', 'Mais abaixo do preço comum']);
      ordens.push(['titulo', 'Título (A a Z)']);
      if (!ordens.some(function (o) { return o[0] === ordemLista; })) ordemLista = 'recentes';
      var v = itens.slice(), dif = function (i) { var a = base && base.precos[i.asin]; return a && !i.fora ? (i.preco - a) / a : 0; };
      if (ordemLista === 'recentes') v.reverse();
      else if (ordemLista === 'preco') v.sort(function (a, b) { return (a.fora ? 1e12 : a.preco) - (b.fora ? 1e12 : b.preco); });
      else if (ordemLista === 'queda') v.sort(function (a, b) { return dif(a) - dif(b); });
      else if (ordemLista === 'abaixo') v.sort(function (a, b) { return (a.mc ? (a.preco - a.mc) / a.mc : 9) - (b.mc ? (b.preco - b.mc) / b.mc : 9); });
      else v.sort(function (a, b) { var p = a.fora ? '~' : norm(a.o.t), s = b.fora ? '~' : norm(b.o.t); return p < s ? -1 : p > s ? 1 : 0; });
      app.innerHTML = '<div class="lista-h"><div><h1>Minha lista</h1><p class="mu" style="margin:4px 0 0">' + L.plural(itens.length, 'livro', 'livros') + ' · salva neste aparelho</p></div>' +
        '<div class="ctl"><label class="sel"><span class="vh">Ordenar por</span><select id="ordl">' +
        ordens.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === ordemLista ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' + ic('baixo', 's') + '</label>' +
        '<button type="button" class="btn sm" data-acao="compartilhar-lista">' + ic('share', 's') + 'Compartilhar</button></div></div>' +
        (base && (mais || menos) ? '<div class="resumo"><span class="mu">Desde sua visita de ' + L.dmes(base.dia) + ':</span>' +
          (menos ? '<span class="pill dn">▼ ' + L.plural(menos, 'ficou mais barato', 'ficaram mais baratos') + '</span>' : '') +
          (mais ? '<span class="pill up">▲ ' + L.plural(mais, 'ficou mais caro', 'ficaram mais caros') + '</span>' : '') + '</div>' : '') +
        '<ul class="lst card" id="lst">' + v.map(function (i) { return linhaLista(i, base, true); }).join('') + '</ul>' +
        '<p class="mu sm" style="margin-top:16px">A lista fica salva só neste navegador. Para levá-la a outro aparelho, toque em Compartilhar e abra o link lá.</p>';
      rolar();
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar sua lista'); });
  }
  function listaCompartilhada(texto) {
    var r = rotaAtual, asins = Lista.extrair(texto.split(',').join(' ')).slice(0, 200);
    titulo('Lista compartilhada');
    if (!asins.length) return naoEncontrado();
    app.innerHTML = esqueleto(Math.min(asins.length, 5));
    carregarItens(asins).then(function (rs) {
      if (!aindaEm(r)) return;
      var itens = rs.slice(1).map(function (it) { return itemLista(it, rs[0].ultima_coleta); }), minha = salvos();
      var novos = asins.filter(function (a) { return !minha[a]; }).length;
      app.innerHTML = '<div class="lista-h"><div><h1>Lista compartilhada</h1><p class="mu" style="margin:4px 0 0">' + L.plural(itens.length, 'livro', 'livros') + '</p></div>' +
        (novos ? '<button type="button" class="btn pri" data-acao="importar" data-asins="' + asins.join(',') + '">' + ic('salvar', 's') + 'Adicionar à minha lista' + (novos < asins.length ? ' (' + novos + ' novos)' : '') + '</button>' :
          '<a class="btn" href="./?lista" data-r>Todos já estão na sua lista</a>') + '</div>' +
        '<ul class="lst card">' + itens.map(function (i) { return linhaLista(i, null, false); }).join('') + '</ul>';
    }).catch(function () { if (aindaEm(r)) erro('Não consegui carregar a lista'); });
  }

  // ---------- como funciona ----------
  function sobre() {
    titulo('Como funciona');
    META.then(function (m) {
      if (rotaAtual.v !== 'sobre') return;
      app.innerHTML = '<article class="prosa"><h1>Como funciona</h1>' +
        '<p class="mu" style="font-size:17px;margin-top:8px">Este site guarda o histórico de preço dos livros mais vendidos da Amazon.com.br, para você saber quanto um livro costuma custar antes de comprar. Ele dá os números; a decisão é sua.</p>' +
        '<h2>De onde vêm os preços</h2><p>Todo dia, um programa lê as listas de mais vendidos de cada categoria de livros da Amazon.com.br (cerca de 2.000 por categoria, em ' +
        m.itens.toLocaleString('pt-BR') + ' livros e e-books ao todo) e anota o preço de cada formato: capa comum, capa dura, Kindle e audiolivro. Só entram ofertas vendidas pela própria Amazon.</p>' +
        '<p>A leitura é feita em várias rodadas ao longo do dia. O preço de um dia é o último visto naquele dia. O site é atualizado depois de cada rodada' +
        (m.ultima_coleta ? '; a coleta mais recente é de ' + L.dl(m.ultima_coleta) : '') + '.</p>' +
        '<h2>O que significa cada número</h2><ul>' +
        '<li><b>Preço mais comum</b>: a mediana dos preços dos últimos 90 dias, ou seja, o valor do meio quando os preços de cada dia são postos em ordem. Aparece a partir de ' + L.MIN_COMUM + ' dias de coleta.</li>' +
        '<li><b>Mais barato e mais caro</b>: o menor e o maior preço registrados nos últimos 90 dias (ou desde o início, se o livro é acompanhado há menos tempo).</li>' +
        '<li><b>Preço de capa</b>: o preço "De:" que a Amazon mostra riscado. É o preço sugerido pela editora; nem todo livro tem.</li>' +
        '<li><b>Baixaram de preço</b>: livros cujo preço caiu pelo menos 5% nas duas últimas coletas, em relação ao preço anterior.</li>' +
        '<li><b>Datas de promoção</b>: na Black Friday e em outras datas, o preço do dia é comparado com o dos 90 dias anteriores.</li></ul>' +
        '<h2>Limites</h2><ul><li>Livros fora das listas de mais vendidos não são acompanhados, e um livro que sai da lista para de ter preço novo.</li>' +
        '<li>Dias sem coleta (por falha ou porque o livro não apareceu) ficam sem preço; o gráfico mostra isso como uma interrupção na linha.</li>' +
        '<li>O preço pode mudar a qualquer momento na Amazon. Confira na loja antes de comprar.</li></ul>' +
        '<h2>Privacidade</h2><p>Não há conta nem cadastro. A sua lista fica guardada só no seu navegador; ninguém mais a vê, a não ser que você compartilhe o link dela.</p>' +
        '<p class="mu sm">Este site não tem vínculo com a Amazon.</p></article>';
      rolar();
    });
  }

  // ---------- eventos globais ----------
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-r]');
    if (a && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) { e.preventDefault(); ir(a.getAttribute('href'), a.hasAttribute('data-sub')); return; }
    var b = e.target.closest('button'); if (!b) return;
    var acao = b.dataset.acao;
    if (b.dataset.fam) { if (S.fam[b.dataset.fam]) delete S.fam[b.dataset.fam]; else S.fam[b.dataset.fam] = 1; aplicarBusca(); }
    else if (b.dataset.idioma !== undefined) { S.i = S.i === b.dataset.idioma ? '' : b.dataset.idioma; aplicarBusca(); }
    else if (b.dataset.baixa !== undefined) { filtroBaixa = b.dataset.baixa; baixaTudo = false; destaques().then(function (x) { secaoBaixa(x, salvos()); }); }
    else if (b.dataset.salvar) {
      var na = Lista.alternar(b.dataset.salvar); botaoSalvar(); contador();
      toast(na ? 'Salvo na sua lista' : 'Removido da sua lista', na ? 'Ver lista' : null, function () { ir('./?lista'); });
    } else if (b.dataset.remover) {
      var asin = b.dataset.remover, pos = Lista.ler().indexOf(asin);
      Lista.remover(asin); contador(); lista();
      toast('Removido da sua lista', 'Desfazer', function () { Lista.inserir(asin, pos); contador(); if (rotaAtual.v === 'lista') lista(); });
    }
    else if (acao === 'mais') maisResultados();
    else if (acao === 'preco') { verPreco = !verPreco; if (!verPreco) { S.de = S.ate = null; aplicarBusca(); } else { ferramentas(); resultados(); var i = $('#de'); if (i) i.focus(); } }
    else if (acao === 'limpar-filtros') { S.fam = {}; S.i = ''; S.g = ''; S.de = S.ate = null; verPreco = false; aplicarBusca(); }
    else if (acao === 'baixa-tudo') { baixaTudo = true; destaques().then(function (x) { secaoBaixa(x, salvos()); }); }
    else if (acao === 'voltar') voltar();
    else if (acao === 'buscar') { q.focus(); scrollTo(0, 0); }
    else if (acao === 'recarregar') location.reload();
    else if (acao === 'compartilhar') compartilhar(location.href, document.title);
    else if (acao === 'compartilhar-lista') compartilhar(location.origin + location.pathname + '?lista=' + Lista.ler().join(','), 'Minha lista de livros');
    else if (acao === 'importar') { var n = Lista.importar(b.dataset.asins).adicionados; contador(); ir('./?lista', true); toast(L.plural(n, 'livro adicionado', 'livros adicionados') + ' à sua lista'); }
  });
  window.addEventListener('popstate', function () { scrollAlvo = (history.state || {}).y || 0; desenhar(); });
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
