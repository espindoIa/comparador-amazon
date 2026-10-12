/* Busca no catálogo: normaliza o texto, acha as obras, conta os filtros e ordena.
 * Não mexe na página: é usada por app.js no navegador e por tests/busca.test.js no Node.
 *
 * Cada obra precisa de `preparar(o)` antes (cria o.nt e o.na, o título e o autor normalizados).
 * Uma palavra da busca casa com o COMEÇO de uma palavra do título ou do autor ("pot" acha "Potter",
 * mas "otter" não). Palavras como "de", "a", "the" não precisam estar lá, mas contam na ordem
 * ("o alquimista" põe "O Alquimista" antes de "Alquimista, O Sonho"). Se nada é achado, tenta corrigir
 * erros de digitação e, por fim, mostra as obras com a maior parte das palavras. */
(function (root) {
  'use strict';
  var PARADAS = {};
  ('a o as os um uma uns umas de da do das dos e em na no nas nos ao aos para por pelo pela com ' +
    'the of and an to in on for').split(' ').forEach(function (p) { PARADAS[p] = 1; });

  function normalizar(s) {
    s = String(s || '').toLowerCase();
    return /[^\x00-\x7f]/.test(s) ? s.normalize('NFD').replace(/[\u0300-\u036f]/g, '') : s;
  }
  // palavras de um texto; "auto-ajuda", "d'água" e "J.R.R." também valem juntas ("autoajuda", "dagua", "jrr")
  var NAO_ASCII = /[^\x00-\x7f]/, SEP_ASCII = /[^a-z0-9]+/g, SEP_U = /[^\p{L}\p{N}]+/gu, LIGADA = /\S[^a-z0-9\s]+\S/;
  function separar(n) { return n.replace(NAO_ASCII.test(n) ? SEP_U : SEP_ASCII, ' ').trim(); }
  function juntas(n) {
    if (!LIGADA.test(n)) return '';
    var out = [];
    n.split(/\s+/).forEach(function (pedaco) {
      var ps = separar(pedaco);
      if (ps.indexOf(' ') > 0) out.push(ps.replace(/ /g, ''));
    });
    return out.join(' ');
  }
  function palavras(s, extras) {
    var n = normalizar(s), t = separar(n), j = extras ? juntas(n) : '';
    return (t ? t.split(' ') : []).concat(j ? j.split(' ') : []);
  }
  var ARTIGO = /^(?:(?:o|a|os|as|um|uma|the|an) )+/;
  // o.nt e o.na: " palavra palavra " (título e autor); o.tl: tamanho do título sem as formas juntas;
  // o.ini: onde o título começa sem o artigo ("O Alquimista" também começa em "alquimista")
  function preparar(o) {
    var n = normalizar(o.t), t = separar(n), j = juntas(n), a = normalizar(o.autor), ja = juntas(a), m = ARTIGO.exec(t);
    o.tl = t.length;
    o.ini = m ? m[0].length : 0;
    o.nt = ' ' + t + (j ? ' ' + j : '') + ' ';
    o.na = ' ' + separar(a) + (ja ? ' ' + ja : '') + ' ';
    return o;
  }
  // termos úteis (sem "de", "a"...; se só houver desses, ficam todos) e a frase inteira, para a ordem
  function consulta(q) {
    var todos = palavras(q), uteis = todos.filter(function (p) { return !PARADAS[p]; });
    return { todos: todos, uteis: uteis.length ? uteis : todos, frase: todos.join(' ') };
  }

  // 0: a frase é o título (com ou sem o artigo do começo); 1: o título começa com a frase, ou a frase é o
  // nome do autor ("machado de assis" acha os livros dele junto com os que têm o nome dele no título);
  // 2: todas as palavras estão no título; 3: umas no título, outras no autor
  function nivel(o, frase, emTit, n) {
    var f = ' ' + frase;
    if (o.nt.startsWith(f + ' ') && frase.length === o.tl) return 0;
    if (o.ini && o.nt.startsWith(f + ' ', o.ini) && frase.length === o.tl - o.ini) return 0;
    if (o.nt.startsWith(f) || (o.ini && o.nt.startsWith(f, o.ini)) || (n > 1 && o.na.indexOf(f + ' ') >= 0)) return 1;
    return emTit === n ? 2 : 3;
  }
  function contagens() { return { fam: {}, i: {}, g: {} }; }
  function soma(m, k) { m[k] = (m[k] || 0) + 1; }

  // c = {fam: {f: 1}, i: idioma, g: nº do gênero ou '', de, ate}; minimo = 0: todos os termos; senão, pelo menos `minimo`
  function filtrar(obras, termos, frase, c, minimo) {
    var lista = [], cont = contagens(), n = termos.length, temFam = false, f;
    for (f in c.fam || {}) temFam = true;
    var gen = c.g === '' || c.g == null ? -1 : +c.g;
    for (var i = 0; i < obras.length; i++) {
      var o = obras[i], emTit = 0, ok = 0;
      for (var j = 0; j < n; j++) {
        if (o.nt.indexOf(' ' + termos[j]) >= 0) { emTit++; ok++; }
        else if (o.na.indexOf(' ' + termos[j]) >= 0) ok++;
        else if (!minimo) break;
      }
      if (ok < (minimo || n)) continue;
      var eds = [], k, e;
      for (k = 0; k < o.eds.length; k++) {
        e = o.eds[k];
        if ((c.de == null || e.preco >= c.de) && (c.ate == null || e.preco <= c.ate)) eds.push(e);
      }
      if (!eds.length) continue;
      var okI = !c.i || o.idioma === c.i, okG = gen < 0 || o.gen.indexOf(gen) >= 0;
      if (okI && okG) {
        var vistas = {};
        for (k = 0; k < eds.length; k++) if (!vistas[eds[k].fam]) { vistas[eds[k].fam] = 1; soma(cont.fam, eds[k].fam); }
      }
      var sel = temFam ? eds.filter(function (e) { return c.fam[e.fam]; }) : eds;
      if (!sel.length) continue;
      if (okG && o.idioma) soma(cont.i, o.idioma);
      if (okI) for (k = 0; k < o.gen.length; k++) soma(cont.g, o.gen[k]);
      if (!okI || !okG) continue;
      var s = n ? nivel(o, frase, emTit, n) : 0;
      var p = sel[0].preco;
      for (k = 1; k < sel.length; k++) if (sel[k].preco < p) p = sel[k].preco;
      lista.push({ o: o, eds: sel, s: s, p: p, m: ok });
    }
    return { lista: lista, cont: cont };
  }

  // ---------- erros de digitação ----------
  // Vocabulário: cada palavra do catálogo e quantas vezes aparece. Montar leva tempo (centenas de milhares de
  // palavras), então app.js o monta aos poucos quando o índice termina de chegar (vocabularioAosPoucos).
  var VOC = null;
  function novoVoc(obras) { return { obras: obras, n: 0, f: new Map() }; }
  function somarVoc(v, ate) {
    for (; v.n < ate; v.n++) {
      var ws = (v.obras[v.n].nt + v.obras[v.n].na).split(' ');
      for (var j = 0; j < ws.length; j++) if (ws[j].length >= 3) v.f.set(ws[j], (v.f.get(ws[j]) || 0) + 1);
    }
  }
  function vocabulario(obras) {
    if (!VOC || VOC.obras !== obras || VOC.n > obras.length) VOC = novoVoc(obras);
    somarVoc(VOC, obras.length);                       // completa o que falta (índice que cresceu depois)
    return VOC;
  }
  function vocabularioAosPoucos(obras, pronto) {
    if (!VOC || VOC.obras !== obras || VOC.n > obras.length) VOC = novoVoc(obras);
    var v = VOC;
    (function fatia() {
      if (VOC !== v) return;
      somarVoc(v, Math.min(v.n + 5000, obras.length));
      if (v.n < obras.length) setTimeout(fatia, 0); else if (pronto) pronto();
    })();
  }
  function comPrefixo(v, t) {
    if (v.f.has(t)) return true;
    for (var w of v.f.keys()) if (w.length > t.length && w.startsWith(t)) return true;
    return false;
  }
  // distância de edição (troca de duas letras vizinhas conta 1); devolve k + 1 se passar de k
  function distancia(a, b, k) {
    if (Math.abs(a.length - b.length) > k) return k + 1;
    var ant2 = null, ant = [], cur, i, j;
    for (j = 0; j <= b.length; j++) ant[j] = j;
    for (i = 1; i <= a.length; i++) {
      cur = [i]; var min = i;
      for (j = 1; j <= b.length; j++) {
        var v = Math.min(ant[j] + 1, cur[j - 1] + 1, ant[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, ant2[j - 2] + 1);
        cur[j] = v; if (v < min) min = v;
      }
      if (min > k) return k + 1;
      ant2 = ant; ant = cur;
    }
    return ant[b.length];
  }
  // Troca cada termo que não começa nenhuma palavra do catálogo por uma palavra próxima. Cada termo tem até
  // CANDIDATOS opções (as mais próximas; no empate, as mais comuns) e fica a combinação que mais obras têm
  // juntas: "hary poter" vira "harry potter", não "mary poder". O termo pode estar pela metade ("pottr").
  // null se nada mudou ou se nenhuma combinação acha alguma obra.
  var CANDIDATOS = 8;
  // o próprio termo (se existe no catálogo) e as palavras próximas
  function candidatos(v, t) {
    var cs = comPrefixo(v, t) ? [{ w: t, d: 0, f: 1e9 }] : [];
    if (t.length < 4 || /^\d+$/.test(t)) return cs;
    var k = t.length >= 8 ? 2 : 1;
    for (var w of v.f.keys()) {
      if (w.length < t.length - k) continue;
      var d = distancia(t, w, k);
      if (w.length > t.length) d = Math.min(d, distancia(t, w.slice(0, t.length), k));   // palavra pela metade
      if (d > 0 && d <= k) cs.push({ w: w, d: d, f: v.f.get(w) });
    }
    return cs.sort(function (a, b) { return a.d - b.d || b.f - a.f; }).slice(0, CANDIDATOS);
  }
  function corrigir(obras, termos) {
    var v = vocabulario(obras), cs = termos.map(function (t) { return candidatos(v, t); });
    if (cs.some(function (c) { return !c.length; })) return null;
    // conta, numa passada só, quantas obras têm cada combinação de candidatos
    var conta = {}, n = termos.length;
    for (var i = 0; i < obras.length; i++) {
      var o = obras[i], tem = [];
      for (var j = 0; j < n; j++) {
        var achou = [];
        for (var k = 0; k < cs[j].length; k++) {
          var c = ' ' + cs[j][k].w;
          if (o.nt.indexOf(c) >= 0 || o.na.indexOf(c) >= 0) achou.push(k);
        }
        if (!achou.length) break;
        tem.push(achou);
      }
      if (tem.length < n) continue;
      (function somar(j, chave) {
        if (j === n) { conta[chave] = (conta[chave] || 0) + 1; return; }
        tem[j].forEach(function (k) { somar(j + 1, chave + k + ','); });
      })(0, '');
    }
    var melhor = null, mq = 0, md = 99;
    Object.keys(conta).forEach(function (chave) {
      var ks = chave.split(',').slice(0, n).map(Number), d = 0;
      ks.forEach(function (k, j) { d += cs[j][k].d; });
      if (conta[chave] > mq || (conta[chave] === mq && d < md)) { melhor = ks; mq = conta[chave]; md = d; }
    });
    var out = melhor && melhor.map(function (k, j) { return cs[j][k].w; });
    return out && out.join(' ') !== termos.join(' ') ? out : null;
  }

  // ---------- ordem ----------
  function desconto(r) { var m = 0; r.eds.forEach(function (e) { if (e.capa > e.preco) m = Math.max(m, (e.capa - e.preco) / e.capa); }); return m; }
  function abaixo(r) { var m = 9; r.eds.forEach(function (e) { if (e.mc) m = Math.min(m, (e.preco - e.mc) / e.mc); }); return m; }
  function tit(a, b) { return a.o.nt < b.o.nt ? -1 : a.o.nt > b.o.nt ? 1 : 0; }
  var ORDENS = {
    // no empate (e enquanto não há avaliações), livro com autor e com mais formatos antes
    rel: function (a, b) { return b.m - a.m || a.s - b.s || b.o.av - a.o.av || !a.o.autor - !b.o.autor || b.o.eds.length - a.o.eds.length || a.o.tl - b.o.tl || tit(a, b); },
    avaliacoes: function (a, b) { return b.o.av - a.o.av || tit(a, b); },
    preco: function (a, b) { return a.p - b.p || tit(a, b); },
    preco_desc: function (a, b) { return b.p - a.p || tit(a, b); },
    desconto: function (a, b) { return a.d - b.d || tit(a, b); },
    abaixo: function (a, b) { return a.d - b.d || tit(a, b); },
    titulo: tit
  };
  function ordenar(lista, ordem) {
    if (ordem === 'desconto') lista.forEach(function (r) { r.d = -desconto(r); });
    else if (ordem === 'abaixo') lista.forEach(function (r) { r.d = abaixo(r); });
    return lista.sort(ORDENS[ordem] || ORDENS.rel);
  }

  // c = {q, fam, i, g, o (ordem), de, ate}; x = {porAsin, asinDe (ASIN, ISBN ou link da Amazon vão direto ao livro),
  // parcial: true enquanto falta parte do índice (aí não corrige nem afrouxa: o livro pode estar na parte que falta)}.
  // Devolve {lista: [{o, eds, s, p}], cont: {fam, i, g}, correcao: texto usado no lugar do digitado, parcial: true se
  // nenhuma obra tinha todas as palavras}.
  function buscar(obras, c, x) {
    x = x || {};
    var asin = x.asinDe ? x.asinDe(c.q) : null;
    if (asin && x.porAsin && x.porAsin[asin]) {
      var e = x.porAsin[asin];
      return { lista: [{ o: e.o, eds: [e], s: 0, p: e.preco, m: 0 }], cont: contagens() };
    }
    var q = consulta(c.q), r = filtrar(obras, q.uteis, q.frase, c, 0);
    if (!r.lista.length && q.uteis.length && !x.parcial) {
      var corr = corrigir(obras, q.uteis);
      if (corr) {
        // a frase corrigida mantém as palavras como "de" e "dos", para a ordem e para mostrar
        var u = 0, frase = q.uteis === q.todos ? corr.join(' ') :
          q.todos.map(function (t) { return PARADAS[t] ? t : corr[u++]; }).join(' ');
        var rc = filtrar(obras, corr, frase, c, 0);
        if (rc.lista.length) { rc.correcao = frase; r = rc; }
      }
      var n = q.uteis.length;
      if (!r.lista.length && n >= 2) {
        var rp = filtrar(obras, q.uteis, q.frase, c, n <= 3 ? n - 1 : Math.ceil(n / 2));
        if (rp.lista.length) { rp.parcial = true; r = rp; }
      }
    }
    ordenar(r.lista, c.o);
    return r;
  }

  root.Busca = { normalizar: normalizar, palavras: palavras, preparar: preparar, consulta: consulta, buscar: buscar,
    corrigir: corrigir, distancia: distancia, ordenar: ordenar, vocabularioAosPoucos: vocabularioAosPoucos };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.Busca;
})(typeof window !== 'undefined' ? window : globalThis);
