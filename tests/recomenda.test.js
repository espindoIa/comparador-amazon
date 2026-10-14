/* Testes de recomenda.js (rodar: node tests/recomenda.test.js). */
'use strict';
var assert = require('assert');
var R = require('../comparador/web/recomenda.js');

// cartão: [asin, título, capa, formato, preço, autor]
function c(asin, autor) { return [asin, 'Livro ' + asin, '', 'Capa comum', 1000, autor || 'Autor ' + asin]; }
function asins(r) { return r.map(function (x) { return x.c[0]; }); }

// nada de partida, nada de parecidos
assert.deepStrictEqual(R.juntar([]), []);

// um livro de partida: a lista dele, na ordem, com o motivo
var hobbit = { asin: 'H000000001', titulo: 'O Hobbit', peso: 1, lista: [c('A000000001'), c('A000000002'), c('A000000003')] };
var r = R.juntar([hobbit]);
assert.deepStrictEqual(asins(r), ['A000000001', 'A000000002', 'A000000003']);
assert.deepStrictEqual(r.map(function (x) { return x.como; }), ['O Hobbit', 'O Hobbit', 'O Hobbit']);

// parecido com dois livros sobe; o motivo é quem mais contribuiu (o de mais peso, ou o mais bem colocado)
var duna = { asin: 'D000000001', titulo: 'Duna', peso: 2, lista: [c('A000000003'), c('B000000001')] };
r = R.juntar([duna, hobbit]);
assert.strictEqual(r[0].c[0], 'A000000003');
assert.strictEqual(r[0].como, 'Duna');
assert.strictEqual(r.filter(function (x) { return x.c[0] === 'A000000001'; })[0].como, 'O Hobbit');

// empate de contribuição: fica com quem veio antes na lista de partida (mais peso, mais recente)
var a = { asin: 'X000000001', titulo: 'Primeiro', peso: 1, lista: [c('A000000009')] };
var b = { asin: 'X000000002', titulo: 'Segundo', peso: 1, lista: [c('A000000009')] };
assert.strictEqual(R.juntar([a, b])[0].como, 'Primeiro');
assert.strictEqual(R.juntar([b, a])[0].como, 'Segundo');

// fora: os livros de partida, a obra deles (Kindle salvo, cartão do físico) e os já salvos
var kindle = { asin: 'K000000001', obra: 'F000000001', titulo: 'Salvo no Kindle', peso: 2, lista: [c('A000000001')] };
var outro = { asin: 'O000000001', titulo: 'Outro', peso: 1, lista: [c('F000000001'), c('K000000001'), c('O000000001'), c('S000000001'), c('A000000002')] };
assert.deepStrictEqual(asins(R.juntar([kindle, outro], { fora: ['S000000001'] })), ['A000000001', 'A000000002']);

// cada livro uma vez (grupo: as edições do mesmo livro, calculado em site.py), e fora os grupos dos livros de partida
function cg(asin, grupo, autor) { var x = c(asin, autor); x.push(grupo); return x; }
var e1 = { asin: 'E000000001', grupo: 7, titulo: 'Um', peso: 2, lista: [cg('A000000001', 1), cg('A000000002', 2), cg('A000000003', 7)] };
var e2 = { asin: 'E000000002', grupo: 8, titulo: 'Dois', peso: 1, lista: [cg('B000000001', 1), cg('B000000002', 3)] };
assert.deepStrictEqual(asins(R.juntar([e1, e2])), ['A000000001', 'A000000002', 'B000000002']);

// no máximo 2 do mesmo autor (sem diferença de maiúsculas); sem autor não conta
var mesmo = { asin: 'M000000001', titulo: 'M', peso: 1,
  lista: [c('A000000001', 'Fulano'), c('A000000002', 'FULANO'), c('A000000003', 'fulano'), c('A000000004', ''), c('A000000005', ''), c('A000000006', '')] };
assert.deepStrictEqual(asins(R.juntar([mesmo])), ['A000000001', 'A000000002', 'A000000004', 'A000000005', 'A000000006']);

// n limita; resultado estável
assert.strictEqual(R.juntar([mesmo], { n: 2 }).length, 2);
assert.deepStrictEqual(R.juntar([duna, hobbit]), R.juntar([duna, hobbit]));

console.log('recomenda.test.js: ok');
