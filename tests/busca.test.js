/* Testes de busca.js (rodar: node tests/busca.test.js). */
'use strict';
var assert = require('assert');
var B = require('../comparador/web/busca.js');

function obra(t, autor, eds, extra) {
  var o = Object.assign({ t: t, autor: autor || '', idioma: '', gen: [], av: 0, eds: [] }, extra || {});
  (eds || [['f', 1000]]).forEach(function (e, i) {
    o.eds.push({ asin: (t.replace(/\W/g, '') + 'XXXXXXXXXX').slice(0, 9).toUpperCase() + i, fam: e[0], preco: e[1], capa: e[2] || 0, mc: e[3] || 0, o: o });
  });
  return B.preparar(o);
}
var OBRAS = [
  obra('Harry Potter e a Pedra Filosofal', 'J.K. Rowling', [['f', 4000], ['k', 2500]], { av: 90000, gen: [3] }),
  obra('Harry Potter e a Câmara Secreta', 'J.K. Rowling', [['f', 4200]], { av: 50000, gen: [3] }),
  obra('Box Harry Potter', 'J.K. Rowling', [['f', 25000]], { av: 20000, gen: [3] }),
  obra('O Alquimista', 'Paulo Coelho', [['f', 3000], ['k', 1990]], { av: 30000, gen: [5] }),
  obra('Alquimista, O Sonho do', 'Fulano de Tal', [['f', 5000]], { av: 10, gen: [5] }),
  obra('Dom Casmurro', 'Machado de Assis', [['f', 1500]], { av: 8000, idioma: 'Português', gen: [5] }),
  obra('Memórias Póstumas de Brás Cubas', 'Machado de Assis', [['f', 1800]], { av: 7000, idioma: 'Português', gen: [5] }),
  obra('Autoajuda para Leigos', 'Ana Lima', [['f', 3900]], { av: 5 }),
  obra('A Mão e a Luva', 'Machado de Assis', [['k', 500]], { av: 100 }),
  obra('Pride and Prejudice (English Edition)', 'Jane Austen', [['k', 990]], { av: 400, idioma: 'Inglês', gen: [8] }),
  obra("Olhos d'Água", 'Conceição Evaristo', [['f', 3500]], { av: 3000 }),
  obra('O Senhor dos Anéis: A Sociedade do Anel', 'J.R.R. Tolkien', [['f', 6000]], { av: 40000 }),
  obra('Auto-estima em 30 dias', 'Fulano', [['f', 2000]], { av: 1 })
];
function titulos(r) { return r.lista.map(function (x) { return x.o.t; }); }
function busca(q, c) { return B.buscar(OBRAS, Object.assign({ q: q, fam: {}, i: '', g: '', o: 'rel', de: null, ate: null }, c || {})); }

// normalização: acentos, maiúsculas, pontuação
assert.strictEqual(B.normalizar('Câmara SECRETA'), 'camara secreta');
assert.deepStrictEqual(B.palavras("Olhos d'Água: auto-ajuda", true), ['olhos', 'd', 'agua', 'auto', 'ajuda', 'dagua', 'autoajuda']);

// começo de palavra, sem acento, em qualquer ordem
assert.deepStrictEqual(titulos(busca('camara harry')), ['Harry Potter e a Câmara Secreta']);
assert.deepStrictEqual(titulos(busca('pot')).length, 3);
assert.strictEqual(busca('otter').correcao, 'potter');                   // meio da palavra não casa direto: vira correção
// "de", "a", "o" não precisam estar no título, mas a frase inteira vem primeiro
assert.deepStrictEqual(titulos(busca('o alquimista')), ['O Alquimista', 'Alquimista, O Sonho do']);
assert.deepStrictEqual(titulos(busca('alquimista')), ['O Alquimista', 'Alquimista, O Sonho do']);   // sem o artigo também é o título
// título exato antes de título que começa igual; depois por avaliações
assert.deepStrictEqual(titulos(busca('harry potter')), ['Harry Potter e a Pedra Filosofal', 'Harry Potter e a Câmara Secreta', 'Box Harry Potter']);
// autor: "machado de assis" acha os três, do mais avaliado para o menos
assert.deepStrictEqual(titulos(busca('machado de assis')), ['Dom Casmurro', 'Memórias Póstumas de Brás Cubas', 'A Mão e a Luva']);
// título que tem a palavra vem antes de título em que ela só aparece no autor
assert.deepStrictEqual(titulos(busca('luva machado')), ['A Mão e a Luva']);
// apóstrofo e hífen: com e sem separação
assert.deepStrictEqual(titulos(busca('olhos dagua')), ["Olhos d'Água"]);
assert.deepStrictEqual(titulos(busca("olhos d'agua")), ["Olhos d'Água"]);
assert.deepStrictEqual(titulos(busca('autoestima')), ['Auto-estima em 30 dias']);
assert.deepStrictEqual(titulos(busca('jrr tolkien')), ['O Senhor dos Anéis: A Sociedade do Anel']);
// só palavras "vazias": vale a palavra mesmo (começo de palavra)
assert.ok(titulos(busca('a')).indexOf('A Mão e a Luva') >= 0);
// busca vazia: todos, dos mais avaliados para os menos
assert.deepStrictEqual(titulos(busca('')).slice(0, 2), ['Harry Potter e a Pedra Filosofal', 'Harry Potter e a Câmara Secreta']);

// erros de digitação: só quando nada é achado, e fica a combinação que mais obras têm juntas
// ("mary" e "poder" são palavras mais comuns que "harry" e "potter", mas não acham Harry Potter)
OBRAS.push(obra('Mulheres e Poder', 'Mary Beard', [['f', 3000]]), obra('O Poder do Hábito', 'Charles Duhigg', [['f', 3000]]),
  obra('Poder e Glória', 'Mary Renault', [['f', 3000]]), obra('Mary Poppins', 'P. L. Travers', [['f', 3000]]));
var r = busca('hary poter');
assert.strictEqual(r.correcao, 'harry potter');
assert.strictEqual(r.lista[0].o.t, 'Harry Potter e a Pedra Filosofal');
assert.strictEqual(B.buscar(OBRAS, { q: 'hary poter', fam: {}, o: 'rel' }, { parcial: true }).lista.length, 0);   // índice incompleto: espera
r = busca('casmuro');
assert.deepStrictEqual([r.correcao, titulos(r)], ['casmurro', ['Dom Casmurro']]);
assert.strictEqual(busca('o senhr dos aneis').correcao, 'o senhor dos aneis');   // mostra com as palavras curtas
r = busca('memorias postmas');                                             // pela metade e com erro
assert.deepStrictEqual(titulos(r), ['Memórias Póstumas de Brás Cubas']);
assert.strictEqual(B.corrigir(OBRAS, ['xyzw']), null);                    // nada perto: não inventa correção
r = busca('alquimist');                                                    // achou: não corrige
assert.strictEqual(r.correcao, undefined);
assert.strictEqual(B.distancia('potter', 'poter', 2), 1);
assert.strictEqual(B.distancia('ab', 'ba', 1), 1);                         // troca de vizinhas = 1
assert.strictEqual(B.distancia('casa', 'xxxxxxx', 2), 3);
// nenhuma obra com todas as palavras: as que têm a maior parte
r = busca('harry potter pedra filosofal edicao especial capa dura');
assert.ok(r.parcial);
assert.strictEqual(r.lista[0].o.t, 'Harry Potter e a Pedra Filosofal');

// filtros e contagens: família, idioma, gênero, preço
r = busca('', { fam: { k: 1 } });
assert.deepStrictEqual(titulos(r).sort(), ['A Mão e a Luva', 'Harry Potter e a Pedra Filosofal', 'O Alquimista', 'Pride and Prejudice (English Edition)']);
assert.strictEqual(r.cont.fam.f, 15);                                      // a contagem de um filtro ignora o próprio filtro
assert.strictEqual(r.lista[0].eds.length, 1);                              // só a edição Kindle
r = busca('', { g: 5 });
assert.deepStrictEqual(titulos(r), ['O Alquimista', 'Dom Casmurro', 'Memórias Póstumas de Brás Cubas', 'Alquimista, O Sonho do']);
assert.strictEqual(r.cont.g[3], 3);
r = busca('', { i: 'Inglês' });
assert.deepStrictEqual(titulos(r), ['Pride and Prejudice (English Edition)']);
r = busca('', { de: 1000, ate: 2000, o: 'preco' });
assert.deepStrictEqual(r.lista.map(function (x) { return x.p; }), [1500, 1800, 1990, 2000]);
r = busca('', { o: 'avaliacoes' });
assert.strictEqual(r.lista[0].o.av, 90000);

// ASIN, ISBN ou link vão direto ao livro
var porAsin = {}; OBRAS.forEach(function (o) { o.eds.forEach(function (e) { porAsin[e.asin] = e; }); });
var alvo = OBRAS[5].eds[0];
r = B.buscar(OBRAS, { q: 'https://www.amazon.com.br/x/dp/' + alvo.asin + '/ref=x', fam: {}, o: 'rel' },
  { porAsin: porAsin, asinDe: function (s) { var m = /\/dp\/(\w{10})/.exec(s); return m && m[1]; } });
assert.deepStrictEqual(titulos(r), ['Dom Casmurro']);

console.log('testes de busca.js ok');
