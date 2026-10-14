/* Parecidos no início: junta as listas prontas (dados/p/, calculadas por comparador/parecidos.py) dos livros de partida
 * (a lista de desejos e os vistos recentemente). Não mexe na página: é usada por app.js e por tests/recomenda.test.js.
 *
 * Cada livro de partida traz o peso (salvo pesa mais que visto) e a sua lista, do mais parecido ao menos. Um cartão
 * soma peso / (DESLOCA + posição) de cada lista em que aparece: quem é parecido com vários livros sobe, e a escala das
 * notas de cada lista não importa. O motivo ("como <título>") é o livro de partida que mais contribuiu. Ficam de fora
 * os livros de partida, os já salvos (pela obra: um Kindle salvo não volta como o cartão do livro físico), as outras
 * edições deles e de cada cartão (o grupo, calculado em site.py: cada livro aparece uma vez) e o terceiro cartão em
 * diante do mesmo autor. */
(function (root) {
  'use strict';
  var DESLOCA = 3, POR_AUTOR = 2;

  // entradas: [{asin, obra, grupo, titulo, peso, lista: [cartão]}] (cartão: [asin, título, capa, formato, preço, autor,
  // grupo]), na ordem de preferência para desempate; opc: {fora: [asins], n}. Devolve [{c: cartão, como: título}], do
  // mais parecido ao menos.
  function juntar(entradas, opc) {
    opc = opc || {};
    var fora = {}, foraG = {}, soma = {}, melhor = {}, cartoes = {}, primeiro = {}, ordem = [];
    (opc.fora || []).forEach(function (a) { fora[a] = 1; });
    entradas.forEach(function (e) { fora[e.asin] = 1; if (e.obra) fora[e.obra] = 1; if (e.grupo != null) foraG[e.grupo] = 1; });
    entradas.forEach(function (e, i) {
      (e.lista || []).forEach(function (c, pos) {
        var a = c[0];
        if (fora[a] || (c[6] != null && foraG[c[6]])) return;
        var v = e.peso / (DESLOCA + pos);
        if (!(a in soma)) { soma[a] = 0; cartoes[a] = c; primeiro[a] = ordem.length; ordem.push(a); }
        soma[a] += v;
        // o motivo: quem mais contribuiu; empate fica com quem veio antes (mais peso, mais recente)
        if (!melhor[a] || v > melhor[a].v) melhor[a] = { v: v, i: i };
      });
    });
    ordem.sort(function (x, y) { return soma[y] - soma[x] || primeiro[x] - primeiro[y]; });
    var out = [], porAutor = {}, grupos = {}, n = opc.n || 12;
    for (var k = 0; k < ordem.length && out.length < n; k++) {
      var a = ordem[k], g = cartoes[a][6], au = String(cartoes[a][5] || '').toLowerCase();
      if (g != null && grupos[g]) continue;                 // outra edição de um livro que já entrou
      if (au && (porAutor[au] = (porAutor[au] || 0) + 1) > POR_AUTOR) continue;
      if (g != null) grupos[g] = 1;
      out.push({ c: cartoes[a], como: entradas[melhor[a].i].titulo });
    }
    return out;
  }

  root.Recomenda = { juntar: juntar };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.Recomenda;
})(typeof window !== 'undefined' ? window : globalThis);
