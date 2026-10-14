/* Livros parecidos: escolhe, entre as obras do índice, as mais próximas de um conjunto de livros (a lista de
 * desejos e os vistos recentemente, no início; o livro aberto, na página do livro). Roda só no navegador, com
 * os dados que o site já baixa: nada sai do aparelho. Não mexe na página: é usada por app.js e por
 * tests/recomenda.test.js no Node.
 *
 * Os livros de partida viram um perfil só (peso de cada gênero, autor e idioma), e o índice é percorrido uma
 * vez. A nota de cada obra:
 * - gêneros em comum, cada um pesando pela raridade no índice (Literatura e Ficção quase não conta; Direito
 *   conta muito), divididos pela raiz do número de gêneros da obra (quem está em muitos gêneros não casa com tudo);
 * - mesmo autor principal;
 * - idioma: quando o perfil tem idioma conhecido, obra em outro idioma vale bem menos;
 * - popularidade (número de avaliações, em escala de log) só desempata.
 * Campos vazios (autor ou idioma não informados) nunca contam como semelhança. Só entra quem tem pelo menos um
 * gênero ou o autor em comum, e cada autor aparece no máximo POR_AUTOR vezes. */
(function (root) {
  'use strict';
  var AUTOR = 3, OUTRO_IDIOMA = 0.3, POPULAR = 0.1, POR_AUTOR = 2;

  function normalizar(s) {
    s = String(s || '').toLowerCase();
    if (/[^\x00-\x7f]/.test(s)) s = s.normalize('NFD').replace(/[̀-ͯ]/g, '');
    return s.replace(/[^a-z0-9]+/g, ' ').trim();
  }
  // o autor principal: "Fulano, Beltrano" e "Fulano e Beltrano" contam como Fulano
  function autor(a) { return normalizar(String(a || '').split(/,|;| e | and | & /)[0]); }

  // raridade de cada gênero (posição em "gen"): log(N / obras do gênero)
  function raridade(obras) {
    var df = {}, n = obras.length;
    for (var i = 0; i < n; i++) { var g = obras[i].gen || []; for (var j = 0; j < g.length; j++) df[g[j]] = (df[g[j]] || 0) + 1; }
    var idf = {};
    for (var k in df) idf[k] = Math.log((n + 1) / df[k]);
    return idf;
  }

  // sementes: [{gen: [posições], autor, idioma, peso}] → frações do peso total em cada gênero, autor e idioma
  function perfil(sementes) {
    var p = { gen: {}, autor: {}, idioma: {}, temIdioma: false }, total = 0;
    sementes.forEach(function (s) {
      var w = s.peso > 0 ? s.peso : 1, a = autor(s.autor), id = normalizar(s.idioma);
      total += w;
      (s.gen || []).forEach(function (g) { p.gen[g] = (p.gen[g] || 0) + w; });
      if (a) p.autor[a] = (p.autor[a] || 0) + w;
      if (id) { p.idioma[id] = (p.idioma[id] || 0) + w; p.temIdioma = true; }
    });
    [p.gen, p.autor, p.idioma].forEach(function (m) { for (var k in m) m[k] /= total || 1; });
    return p;
  }

  // obras: as do índice ({t, autor, idioma, gen, av, eds}); opc: {n, excluir: [obras], semAutor: [nomes], idf}
  // Devolve as obras, da mais parecida para a menos.
  function recomendar(obras, sementes, opc) {
    opc = opc || {};
    if (!sementes.length) return [];
    var p = perfil(sementes), idf = opc.idf || raridade(obras), fora = new Set(opc.excluir || []), semAutor = {};
    (opc.semAutor || []).forEach(function (a) { a = autor(a); if (a) semAutor[a] = 1; });
    var notas = [];
    for (var i = 0; i < obras.length; i++) {
      var o = obras[i];
      if (fora.has(o) || !o.eds || !o.eds.length) continue;
      var a = autor(o.autor);
      if (a && semAutor[a]) continue;
      var g = o.gen || [], sg = 0;
      for (var j = 0; j < g.length; j++) if (p.gen[g[j]]) sg += p.gen[g[j]] * (idf[g[j]] || 0);
      if (g.length) sg /= Math.sqrt(g.length);
      var sa = a && p.autor[a] ? p.autor[a] * AUTOR : 0;
      if (sg <= 0 && sa <= 0) continue;
      var s = sg + sa, id = normalizar(o.idioma);
      if (p.temIdioma && id && !p.idioma[id]) s *= OUTRO_IDIOMA;
      s *= 1 + POPULAR * Math.log(1 + (o.av || 0)) / Math.LN10;
      notas.push({ o: o, s: s, a: a });
    }
    notas.sort(function (x, y) { return y.s - x.s || (y.o.av || 0) - (x.o.av || 0) || (x.o.t < y.o.t ? -1 : x.o.t > y.o.t ? 1 : 0); });
    var out = [], porAutor = {}, n = opc.n || 12;
    for (var k = 0; k < notas.length && out.length < n; k++) {
      var x = notas[k];
      if (x.a && (porAutor[x.a] = (porAutor[x.a] || 0) + 1) > POR_AUTOR) continue;
      out.push(x.o);
    }
    return out;
  }

  root.Recomenda = { normalizar: normalizar, autor: autor, raridade: raridade, perfil: perfil, recomendar: recomendar };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.Recomenda;
})(typeof window !== 'undefined' ? window : globalThis);
