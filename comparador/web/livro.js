/* Página de histórico de preço de um livro: números e gráfico, sem conclusões.
 * Usada pelo site (livro.html) e pelo comando `grafico`. Entrada (D):
 *   {asin, titulo, formato, aviso, trechos: [[dia_ini, dia_fim, preco, capa|null]...], eventos: [[nome, dia_ini, dia_fim]...]}
 * Dias são números ordinais como os de date.toordinal() do Python (1 = 0001-01-01); preços em centavos.
 */
(function (root) {
  'use strict';
  var BURACO = 10, JANELA = 90, JANELA_PICO = 21, EPOCA = 719163;

  // ---------- cálculo (puro) ----------
  function porDia(trechos) {
    var m = {}, i, d;
    trechos.forEach(function (t) { for (d = t[0]; d <= t[1]; d++) m[d] = t[2]; });
    var dias = Object.keys(m).map(Number).sort(function (a, b) { return a - b; });
    return { dias: dias, preco: m };
  }
  function mediana(w) {
    var s = w.slice().sort(function (a, b) { return a - b; }), n = s.length, k = n >> 1;
    return Math.trunc(n % 2 ? s[k] : (s[k - 1] + s[k]) / 2);
  }
  // quartis pelo método "inclusivo" (o mesmo de statistics.quantiles(method="inclusive")); trunca para inteiro
  function quartis(w) {
    if (w.length < 2) return [w[0], w[0], w[0]];
    var s = w.slice().sort(function (a, b) { return a - b; }), m = s.length - 1;
    function q(i) { var j = Math.floor(i * m / 4), delta = (i * m) % 4; return Math.trunc((s[j] * (4 - delta) + (delta ? s[j + 1] : 0) * delta) / 4); }
    return [q(1), mediana(w), q(3)];
  }
  // para cada dia observado: [dia, q1, mediana, q3] dos últimos `janela` dias
  function janelaMovel(pd, janela) {
    janela = janela || JANELA;
    var out = [], ini = 0, i, d, w;
    for (i = 0; i < pd.dias.length; i++) {
      d = pd.dias[i];
      while (pd.dias[ini] < d - janela + 1) ini++;
      w = pd.dias.slice(ini, i + 1).map(function (x) { return pd.preco[x]; });
      out.push([d].concat(quartis(w)));
    }
    return out;
  }
  function fatos(trechos, ate, preco, janela) {
    janela = janela || JANELA;
    var pd = porDia(trechos), ini = ate - janela + 1, w = [], d, i, p;
    for (i = 0; i < pd.dias.length; i++) { d = pd.dias[i]; if (d >= ini && d <= ate) w.push(d); }
    var capa = null;
    for (i = trechos.length - 1; i >= 0; i--) if (trechos[i][3] && trechos[i][0] <= ate) { capa = trechos[i][3]; break; }
    if (preco == null) preco = pd.preco[ate] != null ? pd.preco[ate] : null;
    var f = { ate: ate, preco: preco, mediana: null, q1: null, q3: null, minimo: null, diaMinimo: null, maximo: null,
      diaMaximo: null, diasObservados: w.length, diasJanela: janela, picoRecente: null, ultimaIgualOuMenor: null, capa: capa };
    if (!w.length) return f;
    var vals = w.map(function (x) { return pd.preco[x]; }), q = quartis(vals);
    f.q1 = q[0]; f.mediana = q[1]; f.q3 = q[2];
    w.forEach(function (x) {
      p = pd.preco[x];
      if (f.minimo === null || p < f.minimo || (p === f.minimo && x > f.diaMinimo)) { f.minimo = p; f.diaMinimo = x; }
      if (f.maximo === null || p > f.maximo || (p === f.maximo && x > f.diaMaximo)) { f.maximo = p; f.diaMaximo = x; }
      if (x >= ate - JANELA_PICO && (f.picoRecente === null || p > f.picoRecente)) f.picoRecente = p;
    });
    pd.dias.forEach(function (x) { if (x < ate && preco != null && pd.preco[x] <= preco && (f.ultimaIgualOuMenor === null || x > f.ultimaIgualOuMenor)) f.ultimaIgualOuMenor = x; });
    return f;
  }
  function fatosEvento(trechos, ev) {
    var pd = porDia(trechos), menor = null;
    pd.dias.forEach(function (d) { if (d >= ev[1] && d <= ev[2] && (menor === null || pd.preco[d] < menor)) menor = pd.preco[d]; });
    return menor === null ? null : fatos(trechos, ev[1] - 1, menor);
  }

  // ---------- formatação ----------
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function brl(c) { return c == null ? '–' : 'R$ ' + (c / 100).toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+,)/g, '.'); }
  function dtObj(o) { return new Date((o - EPOCA) * 864e5); }
  function dl(o) { if (o == null) return '–'; var d = dtObj(o); return pad(d.getUTCDate()) + '/' + pad(d.getUTCMonth() + 1) + '/' + d.getUTCFullYear(); }
  function dc(o) { var d = dtObj(o); return pad(d.getUTCDate()) + '/' + pad(d.getUTCMonth() + 1) + '/' + String(d.getUTCFullYear()).slice(2); }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function pct(a, b) { var x = Math.round((a - b) / b * 100); return x === 0 ? '0%' : (x > 0 ? '+' : '') + x + '%'; }
  function comparar(v, ref) { var p = Math.round(Math.abs(v - ref) / ref * 100); return p === 0 ? 'igual a' : p + '% ' + (v > ref ? 'acima' : 'abaixo') + ' do'; }
  function linkAmazon(asin) { return 'https://www.amazon.com.br/dp/' + encodeURIComponent(asin); }
  function cartao(rot, val, nota) { return '<div class="c"><span>' + esc(rot) + '</span><b>' + esc(val) + '</b>' + (nota ? '<small>' + esc(nota) + '</small>' : '') + '</div>'; }

  function cartoesAtuais(f, recente) {
    var c = [cartao(recente === false ? 'Último preço' : 'Preço atual', brl(f.preco), dl(f.ate))];
    // com um único dia de preço, mediana, mínimo e máximo seriam o mesmo número repetido
    if (f.mediana !== null && f.diasObservados > 1) c.push(cartao('Preço mais comum', brl(f.mediana), 'mediana dos últimos ' + f.diasJanela + ' dias'),
      cartao('Mais barato', brl(f.minimo), dl(f.diaMinimo)), cartao('Mais caro', brl(f.maximo), dl(f.diaMaximo)));
    return c.join('');
  }
  function avisoDados(f) {
    if (f.diasObservados >= f.diasJanela * 0.5) return '';
    if (f.diasObservados <= 1) return '<p class="mu">Começamos a acompanhar este livro há pouco: só temos 1 dia de preço. O histórico e a comparação aparecem conforme as coletas diárias se acumulam.</p>';
    return '<p class="mu">Ainda temos poucos dados: só ' + f.diasObservados + ' dias com preço registrado nos últimos ' + f.diasJanela + '.</p>';
  }
  function resumoEvento(ev, f) {
    if (!f) return ev[0] + ': sem coleta durante o evento';
    if (f.mediana === null) return ev[0] + ': ' + brl(f.preco) + ' (sem coleta nos ' + f.diasJanela + ' dias anteriores)';
    return ev[0] + ': ' + brl(f.preco) + ', ' + comparar(f.preco, f.mediana) + ' preço mais comum dos ' + f.diasJanela + ' dias antes (' + brl(f.mediana) +
      '); mais barato antes ' + brl(f.minimo) + ', mais caro ' + brl(f.maximo) + '; ' + f.diasObservados + ' dias com coleta';
  }
  function blocoEvento(ev, f) {
    var quando = dl(ev[1]) + (ev[2] !== ev[1] ? ' a ' + dl(ev[2]) : ''), cab = '<h3>' + esc(ev[0]) + ' <small>' + quando + '</small></h3>';
    if (!f) return '<section>' + cab + '<p class="mu">Sem preço registrado durante o evento.</p></section>';
    if (f.mediana === null) return '<section>' + cab + '<p><b>' + brl(f.preco) + '</b> no evento. Não há preços registrados nos ' + f.diasJanela + ' dias anteriores para comparar.</p></section>';
    var li = ['Antes do evento, o preço mais comum era <b>' + brl(f.mediana) + '</b> (entre ' + brl(f.minimo) + ', em ' + dl(f.diaMinimo) + ', e ' + brl(f.maximo) + ', em ' + dl(f.diaMaximo) + ').'];
    if (f.picoRecente) li.push('Nas 3 semanas antes, chegou a ' + brl(f.picoRecente) + '.');
    li.push('Última vez com preço igual ou menor: ' + (f.ultimaIgualOuMenor ? dl(f.ultimaIgualOuMenor) : 'nunca, desde o início da coleta') + '.');
    var det = ['Faixa onde ficou a metade central dos dias: ' + brl(f.q1) + ' a ' + brl(f.q3) + '.', 'Dias com preço registrado na janela: ' + f.diasObservados + ' de ' + f.diasJanela + '.'];
    if (f.capa) det.splice(1, 0, 'Preço de capa informado pela Amazon: ' + brl(f.capa) + ' (evento ' + comparar(f.preco, f.capa) + ' preço de capa).');
    return '<section>' + cab + '<p class="gr"><b>' + brl(f.preco) + '</b> no evento, ' + comparar(f.preco, f.mediana) + ' preço mais comum.</p><ul>' +
      li.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul><details><summary>Mais detalhes</summary><ul>' +
      det.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></details></section>';
  }

  // dados do gráfico: dias com faixa, trechos, eventos próximos e janela inicial
  function dadosGrafico(trechos, eventos) {
    var pd = porDia(trechos), mov = janelaMovel(pd), d0 = pd.dias[0], d1 = pd.dias[pd.dias.length - 1], ev = [];
    // evento ainda distante só entra no gráfico quando já há histórico para ocupar o espaço; senão o gráfico fica quase todo vazio
    var adiante = (d1 - d0) >= 30 ? 120 : 0;
    eventos.slice().sort(function (a, b) { return a[1] - b[1]; }).forEach(function (e) {
      if (d0 - 30 <= e[2] && e[2] <= d1 + adiante) {
        var menor = null, dm = null;
        pd.dias.forEach(function (d) { if (d >= e[1] && d <= e[2] && (menor === null || pd.preco[d] < menor)) { menor = pd.preco[d]; dm = d; } });
        ev.push([e[0], e[1], e[2], menor, dm]); d0 = Math.min(d0, e[1]); d1 = Math.max(d1, e[2]);
      }
    });
    d1 = Math.max(d1, d0 + 6);
    var capa = null, i;
    for (i = trechos.length - 1; i >= 0; i--) if (trechos[i][3]) { capa = trechos[i][3]; break; }
    return { dias: mov.map(function (r) { return [r[0], pd.preco[r[0]], r[1], r[2], r[3]]; }),
      tr: trechos.map(function (t) { return [t[0], t[1], t[2]]; }), ev: ev, capa: capa,
      full: [d0, d1], def: [(d1 - d0) <= 120 ? d0 : d1 - 89, d1] };
  }

  var CSS_OPCOES = [['med', 'Preço mais comum', 'mediana dos últimos 90 dias'], ['faixa', 'Faixa usual', 'onde ficou a metade central dos dias, nos últimos 90 dias'],
    ['capa', 'Preço de capa', 'preço de capa informado pela Amazon'], ['ev', 'Promoções', 'Black Friday e outras datas'],
    ['lac', 'Dias sem coleta', 'períodos em que não há preço registrado'], ['pts', 'Cada coleta', 'um ponto por dia com preço registrado']];

  function controles(G) {
    var chips = G.ev.map(function (e, i) { return e[3] === null ? '' : '<button type="button" data-ev="' + i + '">' + esc(e[0]) + '</button>'; }).join('');
    var per = [[30, '30 dias'], [90, '90 dias'], [0, 'Tudo']].map(function (p) { return '<button type="button" data-per="' + p[0] + '">' + p[1] + '</button>'; }).join('');
    var ops = CSS_OPCOES.map(function (o) { return '<button type="button" data-op="' + o[0] + '" title="' + esc(o[2]) + '" aria-pressed="false">' + esc(o[1]) + '</button>'; }).join('');
    return '<div class="ctl"><div class="l"><span class="t">Período</span>' + per + chips + '</div><div class="l"><span class="t">Zoom</span>' +
      '<button type="button" data-z="1" aria-label="Aproximar">＋ Aproximar</button><button type="button" data-z="-1" aria-label="Afastar">－ Afastar</button>' +
      '<button type="button" data-pan="-1" aria-label="Voltar no tempo">◀</button><button type="button" data-pan="1" aria-label="Avançar no tempo">▶</button></div>' +
      '<div class="l"><span class="t">Mostrar</span>' + ops + '</div></div>';
  }

  // ---------- DOM ----------
  function montar(raiz, D) {
    var tr = D.trechos, eventos = D.eventos || [];
    var ult = tr[tr.length - 1][1], atual = fatos(tr, ult), G = dadosGrafico(tr, eventos);
    var blocos = eventos.map(function (e) { return blocoEvento(e, fatosEvento(tr, e)); }).join('');
    raiz.innerHTML = (D.aviso ? '<p><b>' + esc(D.aviso) + '</b></p>' : '') +
      '<h1>' + esc(D.titulo || D.asin) + (D.formato ? ' <small>[' + esc(D.formato) + ']</small>' : '') + '</h1>' +
      '<small>ASIN ' + esc(D.asin) + ' · ' + (tr[0][0] === ult ? 'preço de ' + dl(ult) : 'preços de ' + dl(tr[0][0]) + ' a ' + dl(ult)) + '</small>' +
      '<div class="cs" style="margin:12px 0">' + cartoesAtuais(atual, D.ultimaColeta == null ? null : ult >= D.ultimaColeta) + '</div>' + avisoDados(atual) +
      '<div class="graf-box"></div><div class="tip"></div>' + controles(G) +
      (blocos ? '<h2>Black Friday e outras promoções</h2>' + blocos : '');
    grafico(raiz, G);
  }

  function grafico(raiz, D) {
    var W = 860, H = 380, ML = 72, MR = 20, MT = 22, MB = 40, BASE = H - MB;
    var box = raiz.querySelector('.graf-box'), tip = raiz.querySelector('.tip'), ctl = raiz.querySelector('.ctl');
    var DICA = 'Toque ou passe o mouse no gráfico para ver o preço de cada dia.';
    var opt = { med: 1, faixa: 0, capa: 0, ev: 1, lac: 1, pts: 0 };
    try { var sv = JSON.parse(localStorage.getItem('opt_graf') || 'null'); if (sv) for (var k in opt) if (k in sv) opt[k] = sv[k] ? 1 : 0; } catch (e) { }
    var F0 = D.full[0], F1 = D.full[1], v = { a: D.def[0], b: D.def[1] };
    function clamp(a, b) { var sp = Math.max(6, Math.min(b - a, F1 - F0)); a = Math.max(F0, Math.min(a, F1 - sp)); v.a = a; v.b = a + sp; }
    function X(o) { return ML + (o - v.a) / (v.b - v.a) * (W - ML - MR); }
    function draw() {
      ML = (root.innerWidth || 1000) <= 600 ? 104 : 72;
      var vals = [], i, out = [];
      D.dias.forEach(function (r) { if (r[0] >= v.a && r[0] <= v.b) { vals.push(r[1]); if (opt.med) vals.push(r[3]); if (opt.faixa) vals.push(r[2], r[4]); } });
      if (!vals.length) D.dias.forEach(function (r) { vals.push(r[1]); });
      if (opt.capa && D.capa) vals.push(D.capa);
      var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), f = Math.max((hi - lo) * .12, 50); lo = Math.max(0, lo - f); hi += f;
      function Y(c) { return MT + (1 - (c - lo) / (hi - lo)) * (BASE - MT); }
      function n1(x) { return x.toFixed(1); }
      out.push('<svg class="graf" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Histórico de preço"><defs><clipPath id="rec"><rect x="' + ML + '" y="' + MT + '" width="' + (W - ML - MR) + '" height="' + (BASE - MT) + '"/></clipPath>' +
        '<pattern id="lac" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" class="lacl"/></pattern></defs>');
      for (i = 0; i < 5; i++) { var c = lo + (hi - lo) * i / 4; out.push('<line x1="' + ML + '" x2="' + (W - MR) + '" y1="' + n1(Y(c)) + '" y2="' + n1(Y(c)) + '" class="g"/><text x="' + (ML - 8) + '" y="' + n1(Y(c) + 4) + '" text-anchor="end">' + brl(Math.round(c)) + '</text>'); }
      for (i = 0; i < 5; i++) { if (v.b - v.a < 12 && i % 4) continue; var o = Math.round(v.a + (v.b - v.a) * i / 4); out.push('<text x="' + n1(X(o)) + '" y="' + (H - 14) + '" text-anchor="' + (i === 0 ? 'start' : i === 4 ? 'end' : 'middle') + '">' + dc(o) + '</text>'); }
      out.push('<g clip-path="url(#rec)">');
      if (opt.lac) for (i = 1; i < D.tr.length; i++) { var a = D.tr[i - 1], b = D.tr[i]; if (b[0] - a[1] > BURACO) out.push('<rect x="' + n1(X(a[1])) + '" y="' + MT + '" width="' + n1(X(b[0]) - X(a[1])) + '" height="' + (BASE - MT) + '" fill="url(#lac)"><title>Sem coleta de ' + dc(a[1]) + ' a ' + dc(b[0]) + '</title></rect>'); }
      if (opt.ev) D.ev.forEach(function (e) {
        var x0 = X(e[1]) - 3, w = Math.max(X(e[2]) - X(e[1]), 0) + 6, dir = x0 > W * .6;
        out.push('<rect x="' + n1(x0) + '" y="' + MT + '" width="' + n1(w) + '" height="' + (BASE - MT) + '" class="ev"/><text x="' + n1(dir ? x0 - 4 : x0 + w + 4) + '" y="' + (MT + 12) + '" class="evt" text-anchor="' + (dir ? 'end' : 'start') + '">' + esc(e[0]) + '</text>');
      });
      if (opt.faixa && D.dias.length > 1) {
        var top = '', bot = ''; D.dias.forEach(function (r, j) { top += (j ? 'L' : 'M') + n1(X(r[0])) + ',' + n1(Y(r[4])); });
        for (i = D.dias.length - 1; i >= 0; i--) bot += 'L' + n1(X(D.dias[i][0])) + ',' + n1(Y(D.dias[i][2]));
        out.push('<path d="' + top + bot + 'Z" class="faixa"/>');
      }
      if (opt.med) { var m = ''; D.dias.forEach(function (r, j) { m += (j ? 'L' : 'M') + n1(X(r[0])) + ',' + n1(Y(r[3])); }); out.push('<path d="' + m + '" class="med"/>'); }
      if (opt.capa && D.capa) out.push('<line x1="' + ML + '" x2="' + (W - MR) + '" y1="' + n1(Y(D.capa)) + '" y2="' + n1(Y(D.capa)) + '" class="capa"/>');
      var pa = ''; D.tr.forEach(function (t, j) { var x0 = X(t[0]), x1 = Math.max(X(t[1]), x0 + 1), y = n1(Y(t[2])), lig = j && t[0] - D.tr[j - 1][1] <= BURACO; pa += (lig ? 'L' : 'M') + n1(x0) + ',' + y + 'L' + n1(x1) + ',' + y; });
      out.push('<path d="' + pa + '" class="preco"/>');
      if (opt.pts) D.dias.forEach(function (r) { out.push('<circle cx="' + n1(X(r[0])) + '" cy="' + n1(Y(r[1])) + '" r="2" class="pt"/>'); });
      else D.tr.forEach(function (t) { out.push('<circle cx="' + n1(X(t[0])) + '" cy="' + n1(Y(t[2])) + '" r="3" class="pt"/>'); });
      if (opt.ev) D.ev.forEach(function (e) {
        if (e[3] == null) return; var x = X(e[4]), dir = x > W * .6;
        out.push('<circle cx="' + n1(x) + '" cy="' + n1(Y(e[3])) + '" r="5.5" class="pe"/><text x="' + n1(x + (dir ? -9 : 9)) + '" y="' + n1(Y(e[3]) + 4) + '" class="pet" text-anchor="' + (dir ? 'end' : 'start') + '">' + brl(e[3]) + '</text>');
      });
      out.push('</g>');
      if (opt.capa && D.capa) out.push('<text x="' + (W - MR) + '" y="' + n1(Y(D.capa) - 4) + '" text-anchor="end">capa ' + brl(D.capa) + '</text>');
      out.push('<line class="cur" x1="0" x2="0" y1="' + MT + '" y2="' + BASE + '" visibility="hidden"/></svg>');
      box.innerHTML = out.join('');
      var s = box.querySelector('svg');
      s.addEventListener('pointermove', hover);
      s.addEventListener('pointerleave', function () { s.querySelector('.cur').setAttribute('visibility', 'hidden'); tip.textContent = DICA; });
      painel();
    }
    function hover(e) {
      var s = box.querySelector('svg'), r = s.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W, o = (x - ML) / (W - ML - MR) * (v.b - v.a) + v.a, b = null, bd = 1e9;
      D.dias.forEach(function (q) { if (q[0] < v.a || q[0] > v.b) return; var k = Math.abs(q[0] - o); if (k < bd) { bd = k; b = q; } });
      if (!b) return;
      var c = s.querySelector('.cur'), px = X(b[0]); c.setAttribute('x1', px); c.setAttribute('x2', px); c.setAttribute('visibility', 'visible');
      var t = dl(b[0]) + ': ' + brl(b[1]);
      if (opt.med) t += ' · preço mais comum ' + brl(b[3]);
      if (opt.faixa) t += ' · faixa usual ' + brl(b[2]) + ' a ' + brl(b[4]);
      if (opt.capa && D.capa) t += ' · capa ' + brl(D.capa);
      tip.textContent = t;
    }
    function painel() {
      ctl.querySelectorAll('[data-op]').forEach(function (b) { b.setAttribute('aria-pressed', opt[b.dataset.op] ? 'true' : 'false'); });
      var sp = v.b - v.a;
      ctl.querySelectorAll('[data-per]').forEach(function (b) { var n = +b.dataset.per, al = n === 0 ? (v.a === F0 && v.b === F1) : (sp === n - 1 && v.b === F1); b.setAttribute('aria-pressed', al ? 'true' : 'false'); });
      var zm = ctl.querySelector('[data-z="1"]'), zo = ctl.querySelector('[data-z="-1"]'); if (zm) zm.disabled = sp <= 6; if (zo) zo.disabled = sp >= F1 - F0;
    }
    ctl.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return; var sp = v.b - v.a, c = (v.a + v.b) / 2;
      if (b.dataset.op) { opt[b.dataset.op] = opt[b.dataset.op] ? 0 : 1; try { localStorage.setItem('opt_graf', JSON.stringify(opt)); } catch (x) { } }
      else if (b.dataset.per !== undefined) { var n = +b.dataset.per; if (n === 0) { v.a = F0; v.b = F1; } else clamp(F1 - n + 1, F1); }
      else if (b.dataset.z) { var f = b.dataset.z === '1' ? .5 : 2; clamp(c - sp * f / 2, c + sp * f / 2); }
      else if (b.dataset.pan) { var d = Math.round(sp / 3) * (+b.dataset.pan); clamp(v.a + d, v.b + d); }
      else if (b.dataset.ev !== undefined) { var ev = D.ev[+b.dataset.ev]; clamp(ev[1] - 45, ev[2] + 7); }
      draw();
    });
    tip.textContent = DICA; draw();
  }

  var API = { porDia: porDia, quartis: quartis, janelaMovel: janelaMovel, fatos: fatos, fatosEvento: fatosEvento, resumoEvento: resumoEvento,
    dadosGrafico: dadosGrafico, avisoDados: avisoDados, cartoesAtuais: cartoesAtuais, linkAmazon: linkAmazon, montar: montar, brl: brl, dl: dl, esc: esc, pct: pct, comparar: comparar };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.Livro = API;
})(typeof window !== 'undefined' ? window : globalThis);
