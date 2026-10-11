/* Busca por título e lista de desejos (index.html). Dados em dados/*.json, gerados por `python -m comparador site`. */
(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var L = window.Livro, Lista = window.Lista;
  var itens = [], porAsin = {}, meta = null, mostrados = 40, ultimaBusca = [];

  function fragmento(asin) { var h = 0; for (var i = 0; i < asin.length; i++) h = (h * 31 + asin.charCodeAt(i)) % 256; return (h < 16 ? '0' : '') + h.toString(16); }
  function norm(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function dc(o) { return L.dl(o).slice(0, 5); }
  var cacheH = {};
  function historico(asin) {
    var k = fragmento(asin);
    if (!cacheH[k]) cacheH[k] = fetch('dados/h/' + k + '.json').then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).catch(function () { return {}; });
    return cacheH[k].then(function (f) { return f[asin] || null; });
  }

  // ---------- busca ----------
  function buscar(q) {
    var tokens = norm(q).split(/\s+/).filter(Boolean);
    if (!tokens.length) return [];
    var cru = q.trim().toUpperCase(), m = q.match(/\/(?:dp|gp\/product)\/([A-Za-z0-9]{10})/);
    var asin = m ? m[1].toUpperCase() : /^[A-Z0-9]{10}$/.test(cru) ? cru : null;
    if (asin && porAsin[asin]) return [porAsin[asin]];
    var frase = tokens.join(' '), achados = [];
    for (var i = 0; i < itens.length; i++) {
      var it = itens[i], ok = true;
      for (var j = 0; j < tokens.length; j++) if (it.n.indexOf(tokens[j]) < 0) { ok = false; break; }
      if (!ok) continue;
      it.s = it.n.indexOf(frase) === 0 ? 0 : (' ' + it.n).indexOf(' ' + frase) >= 0 ? 1 : 2;
      achados.push(it);
    }
    achados.sort(function (a, b) { return a.s - b.s || a.n.length - b.n.length || (a.n < b.n ? -1 : 1); });
    return achados;
  }
  function linhaPreco(it) {
    var velho = meta && meta.ultima_coleta && it.ultimo < meta.ultima_coleta;
    return '<b>' + L.brl(it.preco) + '</b>' + (velho ? '<small>visto em ' + dc(it.ultimo) + '</small>' : '') +
      (it.capa && it.capa > it.preco ? '<small>capa ' + L.brl(it.capa) + '</small>' : '');
  }
  function botaoLista(asin) {
    var na = Lista.tem(asin);
    return '<button type="button" class="fav" data-asin="' + asin + '" aria-pressed="' + na + '">' + (na ? '★ Na lista' : '☆ Adicionar') + '</button>';
  }
  function desenharResultados() {
    var q = $('#q').value, el = $('#res'), r = ultimaBusca;
    if (!q.trim()) { el.innerHTML = '<p class="mu">Digite parte do título, o nome do autor ou o ASIN/ISBN-10 para buscar entre os ' + (meta ? meta.itens.toLocaleString('pt-BR') : '') + ' livros acompanhados.</p>'; return; }
    if (!r.length) { el.innerHTML = '<p class="mu">Nenhum livro encontrado para "' + L.esc(q) + '". O catálogo cobre os ~1.000 mais vendidos de cada categoria de livros; tente menos palavras.</p>'; return; }
    el.innerHTML = '<p class="mu">' + r.length.toLocaleString('pt-BR') + ' resultado' + (r.length > 1 ? 's' : '') + '</p><ul class="lst">' +
      r.slice(0, mostrados).map(function (it) {
        return '<li class="it"><div class="tt"><a href="livro.html?asin=' + it.asin + '">' + L.esc(it.titulo) + '</a>' + (it.formato ? '<span class="tag">' + L.esc(it.formato) + '</span>' : '') +
          '</div><div class="pr">' + linhaPreco(it) + '</div>' + botaoLista(it.asin) + '</li>';
      }).join('') + '</ul>' + (r.length > mostrados ? '<p><button type="button" id="mais" class="bt">Mostrar mais</button></p>' : '');
  }
  var timer = null;
  function aoDigitar() { clearTimeout(timer); timer = setTimeout(function () { mostrados = 40; ultimaBusca = buscar($('#q').value); desenharResultados(); }, 120); }

  // ---------- lista de desejos ----------
  var ordem = 'adicao';
  function desenharLista() {
    var asins = Lista.ler(), el = $('#lst'), cont = $('#cont');
    cont.textContent = asins.length ? ' (' + asins.length + ')' : '';
    if (!asins.length) { el.innerHTML = '<p class="mu">Sua lista está vazia. Na aba Buscar, toque em "Adicionar" ao lado de um livro para acompanhar o preço dele aqui.</p>'; return; }
    el.innerHTML = '<p class="mu">Carregando preços…</p>';
    Promise.all(asins.map(function (a) { return historico(a).then(function (h) { return { asin: a, h: h }; }); })).then(function (rs) {
      var linhas = rs.map(function (r) {
        var it = porAsin[r.asin];
        if (!r.h || !it) return { asin: r.asin, fora: true, titulo: r.asin, dif: null };
        var f = L.fatos(r.h.h, r.h.h[r.h.h.length - 1][1]);
        return { asin: r.asin, it: it, titulo: it.titulo, f: f, dif: f.mediana ? (f.preco - f.mediana) / f.mediana : null };
      });
      if (ordem === 'nome') linhas.sort(function (a, b) { return norm(a.titulo) < norm(b.titulo) ? -1 : 1; });
      else if (ordem === 'preco') linhas.sort(function (a, b) { return (a.f ? a.f.preco : 1e12) - (b.f ? b.f.preco : 1e12); });
      else if (ordem === 'dif') linhas.sort(function (a, b) { return (a.dif == null ? 9 : a.dif) - (b.dif == null ? 9 : b.dif); });
      el.innerHTML = '<ul class="lst">' + linhas.map(function (l) {
        if (l.fora) return '<li class="it"><div class="tt">' + L.esc(l.asin) + ' <span class="mu">fora do catálogo (sem preços registrados)</span></div><div class="pr"></div>' + botaoLista(l.asin) + '</li>';
        var f = l.f, dif = f.mediana ? L.comparar(f.preco, f.mediana).replace(/ do$/, '') : null;
        return '<li class="it"><div class="tt"><a href="livro.html?asin=' + l.asin + '">' + L.esc(l.titulo) + '</a>' + (l.it.formato ? '<span class="tag">' + L.esc(l.it.formato) + '</span>' : '') +
          '</div><div class="pr"><b>' + L.brl(f.preco) + '</b>' + (f.mediana ? '<small>' + (dif === 'igual a' ? 'igual ao preço mais comum' : dif + ' do preço mais comum (' + L.brl(f.mediana) + ')') + '</small>' : '<small>poucos dados ainda</small>') +
          (f.minimo ? '<small>mais barato em ' + f.diasJanela + ' dias: ' + L.brl(f.minimo) + '</small>' : '') + '</div>' + botaoLista(l.asin) + '</li>';
      }).join('') + '</ul>';
    });
  }

  function aba(nome) {
    var lista = nome === 'lista';
    $('#aba-busca').hidden = lista; $('#aba-lista').hidden = !lista;
    $('#t-busca').setAttribute('aria-selected', String(!lista)); $('#t-lista').setAttribute('aria-selected', String(lista));
    if (lista) desenharLista();
    try { history.replaceState(null, '', lista ? '#lista' : location.pathname + location.search); } catch (e) { }
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    if (b.classList.contains('fav')) {
      Lista.alternar(b.dataset.asin);
      if (!$('#aba-lista').hidden) desenharLista(); else { desenharResultados(); desenharLista(); }
    } else if (b.id === 'mais') { mostrados += 40; desenharResultados(); }
    else if (b.id === 't-busca') aba('busca');
    else if (b.id === 't-lista') aba('lista');
    else if (b.id === 'copiar') {
      var t = Lista.exportar(), ok = function () { $('#msg').textContent = 'Lista copiada. Cole no outro aparelho em "Importar".'; };
      if (navigator.clipboard) navigator.clipboard.writeText(t).then(ok, function () { $('#io').value = t; $('#io').select(); $('#msg').textContent = 'Copie o texto acima.'; });
      else { $('#io').value = t; $('#io').select(); $('#msg').textContent = 'Copie o texto acima.'; }
    } else if (b.id === 'importar') {
      var r = Lista.importar($('#io').value);
      $('#msg').textContent = r.lidos ? r.adicionados + ' livro(s) adicionado(s) (' + (r.lidos - r.adicionados) + ' já estavam na lista).' : 'Não encontrei nenhum ASIN nesse texto.';
      desenharLista();
    }
  });
  window.addEventListener('storage', desenharLista);

  // ---------- início ----------
  $('#q').addEventListener('input', aoDigitar);
  $('#ord').addEventListener('change', function (e) { ordem = e.target.value; desenharLista(); });
  $('#q').disabled = true;
  Promise.all([fetch('dados/meta.json').then(function (r) { return r.json(); }), fetch('dados/indice.json').then(function (r) { return r.json(); })]).then(function (rs) {
    meta = rs[0];
    rs[1].itens.forEach(function (r) {
      var it = { asin: r[0], titulo: r[1], formato: r[2], preco: r[3], capa: r[4], ultimo: r[5], n: norm(r[1]) };
      itens.push(it); porAsin[it.asin] = it;
    });
    if (meta.aviso) { var a = $('#aviso'); a.textContent = meta.aviso; a.hidden = false; }
    $('#info').textContent = meta.itens.toLocaleString('pt-BR') + ' livros · preços de ' + (meta.ultima_coleta ? L.dl(meta.ultima_coleta) : '–');
    $('#q').disabled = false;
    var qs = new URLSearchParams(location.search).get('q'); if (qs) { $('#q').value = qs; }
    ultimaBusca = buscar($('#q').value); desenharResultados(); desenharLista();
    if (location.hash === '#lista') aba('lista'); else $('#q').focus();
  }).catch(function () { $('#res').innerHTML = '<p>Não consegui carregar o catálogo. Recarregue a página.</p>'; });
})();
