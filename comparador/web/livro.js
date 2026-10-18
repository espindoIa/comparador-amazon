/* Histórico de preço de um livro: cálculos, números e gráfico, sem conclusões.
 * Usado pelo app (app.js) e pela página avulsa do comando `grafico` (montar). Entrada de montar (D):
 *   {asin, titulo, formato, aviso, trechos: [[dia_ini, dia_fim, preco, capa|null]...], eventos: [[nome, dia_ini, dia_fim]...]}
 * Dias são números ordinais como os de date.toordinal() do Python (1 = 0001-01-01); preços em centavos.
 */
(function (root) {
  'use strict';
  var BURACO = 10, JANELA = 90, JANELA_PICO = 21, EPOCA = 719163, MIN_COMUM = 14;   // MIN_COMUM: o mesmo de site.py

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
  var MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var MESES_L = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function brl(c) { return c == null ? '–' : 'R$ ' + (c / 100).toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+,)/g, '.'); }
  function brlCurto(c) { return c % 100 ? brl(c) : brl(c).slice(0, -3); }
  function dtObj(o) { return new Date((o - EPOCA) * 864e5); }
  function dl(o) { if (o == null) return '–'; var d = dtObj(o); return pad(d.getUTCDate()) + '/' + pad(d.getUTCMonth() + 1) + '/' + d.getUTCFullYear(); }
  function dc(o) { var d = dtObj(o); return pad(d.getUTCDate()) + '/' + pad(d.getUTCMonth() + 1) + '/' + String(d.getUTCFullYear()).slice(2); }
  function dmes(o, ano) { var d = dtObj(o); return d.getUTCDate() + ' ' + MESES[d.getUTCMonth()] + (ano ? ' ' + d.getUTCFullYear() : ''); }
  function dlongo(o) { var d = dtObj(o); return d.getUTCDate() + ' de ' + MESES_L[d.getUTCMonth()] + ' de ' + d.getUTCFullYear(); }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function pct(a, b) { var x = Math.round((a - b) / b * 100); return x === 0 ? '0%' : (x > 0 ? '+' : '') + x + '%'; }
  function comparar(v, ref) { var p = Math.round(Math.abs(v - ref) / ref * 100); return p === 0 ? 'igual a' : p + '% ' + (v > ref ? 'acima' : 'abaixo') + ' do'; }
  function linkAmazon(asin) { return 'https://www.amazon.com.br/dp/' + encodeURIComponent(asin); }
  function plural(n, um, varios) { return n + ' ' + (n === 1 ? um : varios); }

  // "(English Edition)" e afins saem do título e viram etiqueta de idioma
  var EDICOES = { english: 'Inglês', portuguese: '', spanish: 'Espanhol', french: 'Francês', italian: 'Italiano', german: 'Alemão', japanese: 'Japonês' };
  function limpar(titulo) {
    var t = String(titulo || '').trim(), idioma = '';
    t = t.replace(/\s*[(\[](\w+) Edition[)\]]\s*$/i, function (m, l) { var k = l.toLowerCase(); if (!(k in EDICOES)) return m; idioma = EDICOES[k]; return ''; });
    return { t: t || String(titulo || ''), idioma: idioma };
  }
  // ASIN a partir de um link da Amazon, de um ASIN/ISBN-10 ou de um ISBN-13 (978...); null se não for nada disso
  function asinDe(texto) {
    var s = String(texto || '').trim(), m = s.match(/\/(?:dp|gp\/product)\/([A-Za-z0-9]{10})/);
    if (m) return m[1].toUpperCase();
    var c = s.replace(/[\s-]/g, '').toUpperCase();
    if (/^97[89]\d{10}$/.test(c)) {
      if (c.slice(0, 3) !== '978') return null;
      var b = c.slice(3, 12), soma = 0;
      for (var i = 0; i < 9; i++) soma += (10 - i) * +b[i];
      var dv = (11 - soma % 11) % 11;
      return b + (dv === 10 ? 'X' : dv);
    }
    return /^(?=.*\d)[A-Z0-9]{10}$/.test(c) ? c : null;
  }

  // ---------- blocos de texto ----------
  function celula(rot, val, nota) { return '<div><span>' + esc(rot) + '</span><b>' + val + '</b>' + (nota ? '<small>' + esc(nota) + '</small>' : '') + '</div>'; }
  // grade de números do livro (f = fatos até o último dia; inicio = primeiro dia com preço)
  function estatisticas(f, inicio) {
    var varios = f.diasObservados > 1, curto = f.ate - inicio + 1 < f.diasJanela, desde = curto ? 'desde ' + dmes(inicio) : 'em ' + f.diasJanela + ' dias';
    return '<div class="stats">' +
      celula('Preço mais comum', f.diasObservados >= MIN_COMUM ? brl(f.mediana) : '–', f.diasObservados >= MIN_COMUM ? 'mediana ' + desde : 'a partir de ' + MIN_COMUM + ' dias') +
      celula('Menor preço', varios ? brl(f.minimo) : '–', varios ? dl(f.diaMinimo) : 'a partir de 2 dias') +
      celula('Maior preço', varios ? brl(f.maximo) : '–', varios ? dl(f.diaMaximo) : 'a partir de 2 dias') +
      celula('Acompanhado desde', dl(inicio), plural(f.diasObservados, 'dia com preço', 'dias com preço') + (curto ? '' : ' em 90')) + '</div>';
  }
  function avisoDados(f) {
    if (f.diasObservados >= MIN_COMUM) return '';
    return '<div class="poucos"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg><p>' +
      (f.diasObservados <= 1 ? 'Começamos a acompanhar este livro há pouco: só há 1 dia de preço. ' : 'Ainda há poucos dados: ' + f.diasObservados + ' dias com preço registrado. ') +
      'O preço mais comum aparece a partir de ' + MIN_COMUM + ' dias de coleta.</p></div>';
  }
  // comparação do preço atual (etiquetas abaixo do preço grande)
  function comparacoes(f) {
    var out = [];
    if (f.diasObservados >= MIN_COMUM && f.mediana) {
      var c = comparar(f.preco, f.mediana), cls = f.preco < f.mediana ? 'dn' : f.preco > f.mediana ? 'up' : '';
      out.push('<span class="pill ' + cls + '">' + (c === 'igual a' ? 'Igual ao preço mais comum' : c[0].toUpperCase() + c.slice(1) + ' preço mais comum') + '</span>');
    }
    if (f.capa && f.capa > f.preco) out.push('<span class="sm">Preço de capa <s>' + brl(f.capa) + '</s> (' + Math.round((f.capa - f.preco) / f.capa * 100) + '% abaixo)</span>');
    return out.join('');
  }
  function resumoEvento(ev, f) {
    if (!f) return ev[0] + ': sem coleta durante o evento';
    if (f.mediana === null) return ev[0] + ': ' + brl(f.preco) + ' (sem coleta nos ' + f.diasJanela + ' dias anteriores)';
    return ev[0] + ': ' + brl(f.preco) + ', ' + comparar(f.preco, f.mediana) + ' preço mais comum dos ' + f.diasJanela + ' dias antes (' + brl(f.mediana) +
      '); mais barato antes ' + brl(f.minimo) + ', mais caro ' + brl(f.maximo) + '; ' + f.diasObservados + ' dias com coleta';
  }
  function blocoEvento(ev, f) {
    var quando = dl(ev[1]) + (ev[2] !== ev[1] ? ' a ' + dl(ev[2]) : ''), cab = '<h3>' + esc(ev[0]) + ' <small>' + quando + '</small></h3>';
    if (f.mediana === null) return '<div class="ev-b">' + cab + '<p class="gr"><b>' + brl(f.preco) + '</b> no evento.</p><p class="mu sm">Não há preços registrados nos ' + f.diasJanela + ' dias anteriores para comparar.</p></div>';
    var li = ['Antes do evento, o preço mais comum era <b>' + brl(f.mediana) + '</b>, entre ' + brl(f.minimo) + ' (' + dl(f.diaMinimo) + ') e ' + brl(f.maximo) + ' (' + dl(f.diaMaximo) + ').'];
    if (f.picoRecente) li.push('Nas 3 semanas antes, chegou a ' + brl(f.picoRecente) + '.');
    li.push('Última vez com preço igual ou menor: ' + (f.ultimaIgualOuMenor ? dl(f.ultimaIgualOuMenor) : 'nunca, desde o início da coleta') + '.');
    var det = ['Metade dos dias ficou entre ' + brl(f.q1) + ' e ' + brl(f.q3) + '.', 'Dias com preço registrado na janela: ' + f.diasObservados + ' de ' + f.diasJanela + '.'];
    if (f.capa) det.splice(1, 0, 'Preço de capa informado pela Amazon: ' + brl(f.capa) + ' (evento ' + comparar(f.preco, f.capa) + ' preço de capa).');
    return '<div class="ev-b">' + cab + '<p class="gr"><b>' + brl(f.preco) + '</b> no evento, ' + comparar(f.preco, f.mediana) + ' preço mais comum.</p><ul>' +
      li.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul><details><summary>Mais detalhes</summary><ul>' +
      det.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></details></div>';
  }
  // seção de promoções: as que têm preço registrado e a próxima (com contagem regressiva); '' se nada a mostrar
  function secaoEventos(trechos, eventos, hoje) {
    var blocos = [], prox = null;
    eventos.forEach(function (e) {
      var f = fatosEvento(trechos, e);
      if (f) blocos.push(blocoEvento(e, f));
      else if (e[1] > hoje && (!prox || e[1] < prox[1])) prox = e;
    });
    if (prox) blocos.push('<div class="ev-b ev-prox"><h3>' + esc(prox[0]) + '</h3><span>' + dl(prox[1]) + ' · daqui a ' + plural(prox[1] - hoje, 'dia', 'dias') + '</span></div>');
    return blocos.length ? '<section class="card pad sec"><h2 class="t2">Datas de promoção</h2>' + blocos.join('') + '</section>' : '';
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
    d0 = Math.min(d0, d1 - 6);                     // pouco histórico: mostra pelo menos uma semana, terminando no último dia
    var capa = null, i;
    for (i = trechos.length - 1; i >= 0; i--) if (trechos[i][3]) { capa = trechos[i][3]; break; }
    return { dias: mov.map(function (r) { return [r[0], pd.preco[r[0]], r[1], r[2], r[3]]; }),
      tr: trechos.map(function (t) { return [t[0], t[1], t[2]]; }), ev: ev, capa: capa,
      full: [d0, d1], def: [(d1 - d0) <= 120 ? d0 : d1 - 89, d1] };
  }

  // marcas "redondas" do eixo de preço, dentro de [lo, hi]: 3 a 5 linhas com passo 1, 2 ou 5 × 10^n centavos
  function marcas(lo, hi) {
    var bruto = Math.max((hi - lo) / 4, 1), p = Math.pow(10, Math.floor(Math.log10(bruto))), passo = [1, 2, 5, 10].map(function (k) { return k * p; }).filter(function (x) { return x >= bruto; })[0];
    var a = Math.ceil(lo / passo) * passo, out = [];
    for (var v = a; v <= hi; v += passo) out.push(Math.round(v));
    return out;
  }

  // ---------- gráfico (DOM) ----------
  // el recebe o cabeçalho com os períodos, o gráfico e a legenda. G = dadosGrafico(...)
  function grafico(el, G, titulo) {
    var NS = 'opt_graf2', opt = { med: 0, capa: 0 };
    try { var sv = JSON.parse(localStorage.getItem(NS) || 'null'); if (sv) for (var k in opt) if (k in sv) opt[k] = sv[k] ? 1 : 0; } catch (e) { }
    var temMed = G.dias.length >= MIN_COMUM, F0 = G.full[0], F1 = G.full[1], UL = G.dias[G.dias.length - 1][0], v = { a: G.def[0], b: G.def[1] };
    var span = UL - F0, pers = [[30, '30 dias'], [90, '90 dias'], [365, '1 ano']].filter(function (p) { return span > p[0]; });
    var evs = G.ev.map(function (e, i) { return e[3] === null ? '' : '<button type="button" data-ev="' + i + '">' + esc(e[0]) + '</button>'; }).join('');
    var seg = pers.length || evs ? '<div class="seg" role="group" aria-label="Período">' + pers.map(function (p) { return '<button type="button" data-per="' + p[0] + '">' + p[1] + '</button>'; }).join('') +
      '<button type="button" data-per="0">Tudo</button>' + evs + '</div>' : '';
    el.innerHTML = '<div class="graf-h"><h2>' + esc(titulo || 'Histórico de preço') + '</h2>' + seg + '</div>' +
      '<div class="graf" tabindex="0" role="group" aria-label="' + esc(titulo || 'Histórico de preço') + '. Use as setas para ver o preço de cada dia."><div class="tip" hidden></div></div>' +
      '<p class="vh" aria-live="polite"></p><div class="leg"><span class="fixo"><i></i>Preço</span>' +
      (temMed ? '<button type="button" class="lmed" data-op="med">Preço mais comum</button>' : '') +
      (G.capa ? '<button type="button" class="lcapa" data-op="capa">Preço de capa</button>' : '') + '</div>';
    var box = el.querySelector('.graf'), tip = box.querySelector('.tip'), voz = el.querySelector('[aria-live]'), ki = -1, W = 0, H = 0, ML = 0, MR = 12, MT = 22, MB = 26, X, Y;

    function n1(x) { return Math.round(x * 10) / 10; }
    function draw() {
      W = box.clientWidth || 640; H = W < 520 ? 220 : 280;
      var vals = [], i, out = [], BASE = H - MB;
      G.dias.forEach(function (r, j) { if (r[0] >= v.a && r[0] <= v.b) { vals.push(r[1]); if (opt.med && temMed && j >= MIN_COMUM - 1) vals.push(r[3]); } });
      if (!vals.length) G.dias.forEach(function (r) { vals.push(r[1]); });
      if (opt.capa && G.capa) vals.push(G.capa);
      var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), f = Math.max((hi - lo) * .15, 100); lo = Math.max(0, lo - f); hi += f;
      var ms = marcas(lo, hi);
      ML = Math.max.apply(null, ms.map(function (m) { return brlCurto(m).length; })) * 6.6 + 10;
      X = function (o) { return ML + (o - v.a) / Math.max(1, v.b - v.a) * (W - ML - MR); };
      Y = function (c) { return MT + (1 - (c - lo) / (hi - lo)) * (BASE - MT); };
      out.push('<svg width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(resumo()) + '"><defs><linearGradient id="gArea" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0" stop-color="var(--ac)" stop-opacity=".22"/><stop offset="1" stop-color="var(--ac)" stop-opacity="0"/></linearGradient>' +
        '<clipPath id="gRec"><rect x="' + ML + '" y="0" width="' + (W - ML - MR + 1) + '" height="' + H + '"/></clipPath></defs>');
      ms.forEach(function (m) { if (m < lo || m > hi) return; var y = n1(Y(m)); out.push('<line x1="' + ML + '" x2="' + (W - MR) + '" y1="' + y + '" y2="' + y + '" class="g"/><text x="' + (ML - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + brlCurto(m) + '</text>'); });
      // datas do eixo: passo inteiro de dias, para ficarem igualmente espaçadas; a última encosta no fim
      var nx = W < 520 ? 3 : 5, ano = v.b - v.a > 300, passo = Math.max(1, Math.ceil((v.b - v.a) / (nx - 1)));
      for (var o = v.b; o >= v.a; o -= passo) {
        var xo = X(o), ponta = o === v.b ? 'end' : xo - ML < 24 ? 'start' : 'middle';
        out.push('<text x="' + n1(xo) + '" y="' + (H - 6) + '" text-anchor="' + ponta + '">' + (ano ? MESES[dtObj(o).getUTCMonth()] + ' ' + String(dtObj(o).getUTCFullYear()).slice(2) : dmes(o)) + '</text>');
      }
      out.push('<g clip-path="url(#gRec)">');
      G.ev.forEach(function (e) {
        var x0 = X(e[1] - .5), w = Math.max(X(e[2] + .5) - x0, 4), dir = x0 > W * .6;
        out.push('<rect x="' + n1(x0) + '" y="' + MT + '" width="' + n1(w) + '" height="' + (BASE - MT) + '" class="ev" rx="3"/><text x="' + n1(dir ? x0 - 5 : x0 + w + 5) + '" y="' + (MT + 12) + '" class="evt" text-anchor="' + (dir ? 'end' : 'start') + '">' + esc(e[0]) + '</text>');
      });
      if (opt.capa && G.capa) out.push('<line x1="' + ML + '" x2="' + (W - MR) + '" y1="' + n1(Y(G.capa)) + '" y2="' + n1(Y(G.capa)) + '" class="capa"/>');
      if (opt.med && temMed) { var m = ''; G.dias.forEach(function (r, j) { if (j >= MIN_COMUM - 1) m += (m ? 'L' : 'M') + n1(X(r[0])) + ',' + n1(Y(r[3])); }); out.push('<path d="' + m + '" class="med"/>'); }
      // preço em degraus: vale até mudar; mais de BURACO dias sem coleta interrompem a linha
      var linha = '', area = '', run = '', ini = null, fimX = null;
      function fecha() { if (run) { area += run + 'L' + fimX + ',' + BASE + 'L' + ini + ',' + BASE + 'Z'; linha += run; } run = ''; }
      G.tr.forEach(function (t, j) {
        var prox = G.tr[j + 1], liga = prox && prox[0] - t[1] <= BURACO, x0 = n1(X(t[0])), x1 = n1(X(liga ? prox[0] : t[1])), y = n1(Y(t[2]));
        if (!run) { run = 'M' + x0 + ',' + y; ini = x0; } else run += 'L' + x0 + ',' + y;
        run += 'L' + x1 + ',' + y; fimX = x1;
        if (!liga) fecha();
      });
      fecha();
      out.push('<path d="' + area + '" class="area"/><path d="' + linha + '" class="preco"/>');
      var ul = G.tr[G.tr.length - 1];
      out.push('<circle cx="' + n1(X(ul[1])) + '" cy="' + n1(Y(ul[2])) + '" r="4.5" class="fim"/>');
      G.ev.forEach(function (e) { if (e[3] != null) out.push('<circle cx="' + n1(X(e[4])) + '" cy="' + n1(Y(e[3])) + '" r="5" class="pe"/>'); });
      out.push('</g>');
      if (opt.capa && G.capa) out.push('<text x="' + (W - MR) + '" y="' + n1(Y(G.capa) - 5) + '" text-anchor="end">capa ' + brl(G.capa) + '</text>');
      out.push('<line class="cur" y1="' + MT + '" y2="' + BASE + '" visibility="hidden"/><circle class="curp" r="5" visibility="hidden"/></svg>');
      var velho = box.querySelector('svg'); if (velho) velho.remove();
      box.insertAdjacentHTML('beforeend', out.join(''));
      painel();
      if (ki >= 0 && document.activeElement === box) mostraDia(ki);
    }
    // índices (em G.dias) dos dias dentro do período mostrado
    function visiveis() { var r = []; G.dias.forEach(function (q, j) { if (q[0] >= v.a && q[0] <= v.b) r.push(j); }); return r; }
    // resumo em texto do período mostrado, para o leitor de tela
    function resumo() {
      var js = visiveis(); if (!js.length) return 'Gráfico do histórico de preço';
      var ps = js.map(function (j) { return G.dias[j][1]; }), d0 = G.dias[js[0]][0], d1 = G.dias[js[js.length - 1]][0];
      return 'Gráfico do histórico de preço de ' + dmes(d0, true) + ' a ' + dmes(d1, true) + ': menor ' + brl(Math.min.apply(null, ps)) +
        ', maior ' + brl(Math.max.apply(null, ps)) + ', último ' + brl(ps[ps.length - 1]);
    }
    function mostra(e) {
      var s = box.querySelector('svg'), r = s.getBoundingClientRect(), x = e.clientX - r.left, o = (x - ML) / (W - ML - MR) * (v.b - v.a) + v.a, bd = 1e9, bj = -1;
      G.dias.forEach(function (q, j) { if (q[0] < v.a || q[0] > v.b) return; var k = Math.abs(q[0] - o); if (k < bd) { bd = k; bj = j; } });
      if (bj >= 0) mostraDia(bj);
    }
    function mostraDia(bj) {
      var s = box.querySelector('svg'), b = G.dias[bj]; ki = bj;
      var px = X(b[0]), py = Y(b[1]), c = s.querySelector('.cur'), p = s.querySelector('.curp');
      c.setAttribute('x1', px); c.setAttribute('x2', px); c.setAttribute('visibility', 'visible');
      p.setAttribute('cx', px); p.setAttribute('cy', py); p.setAttribute('visibility', 'visible');
      tip.innerHTML = '<b>' + brl(b[1]) + '</b><br>' + dmes(b[0], true) + (opt.med && temMed && bj >= MIN_COMUM - 1 ? '<br>mais comum ' + brl(b[3]) : '');
      tip.hidden = false;
      var tw = tip.offsetWidth; tip.style.left = Math.max(tw / 2, Math.min(W - tw / 2, px)) + 'px';
      tip.style.top = Math.max(0, py - tip.offsetHeight - 14) + 'px';
      return b;
    }
    // teclado: setas andam de um dia observado para o outro, Home e End vão às pontas; o valor é anunciado
    function tecla(e) {
      var js = visiveis(), i = js.indexOf(ki), n;
      if (!js.length) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') n = i < 0 ? js.length - 1 : Math.max(0, i - 1);
      else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') n = i < 0 ? js.length - 1 : Math.min(js.length - 1, i + 1);
      else if (e.key === 'Home') n = 0;
      else if (e.key === 'End') n = js.length - 1;
      else if (e.key === 'Escape') { esconde(); return; }
      else return;
      e.preventDefault();
      var b = mostraDia(js[n]);
      voz.textContent = brl(b[1]) + ' em ' + dmes(b[0], true);
    }
    function esconde() { ki = -1; var s = box.querySelector('svg'); if (!s) return; s.querySelector('.cur').setAttribute('visibility', 'hidden'); s.querySelector('.curp').setAttribute('visibility', 'hidden'); tip.hidden = true; }
    function painel() {
      el.querySelectorAll('[data-op]').forEach(function (b) { b.setAttribute('aria-pressed', opt[b.dataset.op] ? 'true' : 'false'); });
      el.querySelectorAll('[data-per]').forEach(function (b) { var n = +b.dataset.per, al = n === 0 ? (v.a === F0 && v.b === F1) : (v.a === Math.max(F0, UL - n + 1) && v.b === UL); b.setAttribute('aria-pressed', al ? 'true' : 'false'); });
      el.querySelectorAll('[data-ev]').forEach(function (b) { var e = G.ev[+b.dataset.ev]; b.setAttribute('aria-pressed', v.a === Math.max(F0, e[1] - 45) && v.b === Math.min(F1, e[2] + 7) ? 'true' : 'false'); });
    }
    box.addEventListener('pointermove', mostra);
    box.addEventListener('pointerdown', mostra);
    box.addEventListener('pointerleave', function () { if (!box.matches(':focus-visible')) esconde(); });
    box.addEventListener('keydown', tecla);
    box.addEventListener('focus', function () { var js = visiveis(); if (js.length && box.matches(':focus-visible')) mostraDia(js[js.length - 1]); });
    box.addEventListener('blur', esconde);
    el.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.op) { opt[b.dataset.op] = opt[b.dataset.op] ? 0 : 1; try { localStorage.setItem(NS, JSON.stringify(opt)); } catch (x) { } }
      else if (b.dataset.per !== undefined) { var n = +b.dataset.per; v.a = n === 0 ? F0 : Math.max(F0, UL - n + 1); v.b = n === 0 ? F1 : UL; }
      else if (b.dataset.ev !== undefined) { var ev = G.ev[+b.dataset.ev]; v.a = Math.max(F0, ev[1] - 45); v.b = Math.min(F1, ev[2] + 7); }
      else return;
      esconde(); draw();
    });
    var tm = null, larg = 0;
    function aoRedimensionar() { clearTimeout(tm); tm = setTimeout(function () { if (box.isConnected && box.clientWidth !== larg) { larg = box.clientWidth; draw(); } }, 80); }
    if (root.ResizeObserver) new ResizeObserver(aoRedimensionar).observe(box); else root.addEventListener('resize', aoRedimensionar);
    draw(); larg = box.clientWidth;
  }

  // ---------- página avulsa (comando `grafico`) ----------
  function montar(raiz, D) {
    var tr = D.trechos, eventos = D.eventos || [], ult = tr[tr.length - 1][1], atual = fatos(tr, ult), G = dadosGrafico(tr, eventos), L = limpar(D.titulo || D.asin);
    if (root.document && root.document.body) root.document.body.classList.add('avulsa');
    raiz.innerHTML = (D.aviso ? '<p class="aviso">' + esc(D.aviso) + '</p>' : '') +
      '<section class="sec"><h1>' + esc(L.t) + '</h1><p class="mu">' + [D.formato, L.idioma, 'ASIN ' + D.asin].filter(Boolean).map(esc).join(' · ') + '</p>' +
      '<div class="compra"><div class="preco-g"><b>' + brl(atual.preco) + '</b><span class="mu sm">em ' + dl(ult) + '</span></div><div class="fat">' + comparacoes(atual) + '</div></div></section>' +
      '<section class="card pad sec"><div class="g-box"></div>' + avisoDados(atual) + estatisticas(atual, tr[0][0]) + '</section>' +
      secaoEventos(tr, eventos, ult);
    grafico(raiz.querySelector('.g-box'), G);
  }

  var API = { porDia: porDia, quartis: quartis, janelaMovel: janelaMovel, fatos: fatos, fatosEvento: fatosEvento, resumoEvento: resumoEvento,
    dadosGrafico: dadosGrafico, marcas: marcas, avisoDados: avisoDados, estatisticas: estatisticas, comparacoes: comparacoes, secaoEventos: secaoEventos,
    grafico: grafico, montar: montar, linkAmazon: linkAmazon, limpar: limpar, asinDe: asinDe, MIN_COMUM: MIN_COMUM,
    brl: brl, dl: dl, dc: dc, dmes: dmes, dlongo: dlongo, esc: esc, pct: pct, comparar: comparar, plural: plural };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.Livro = API;
})(typeof window !== 'undefined' ? window : globalThis);
