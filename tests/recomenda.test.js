/* Testes de recomenda.js (rodar: node tests/recomenda.test.js). */
'use strict';
var assert = require('assert');
var R = require('../comparador/web/recomenda.js');

// gêneros (posições): 0 Literatura e Ficção (comum), 1 Fantasia, 2 Direito, 3 Romance
function obra(t, autor, gen, extra) {
  var o = Object.assign({ t: t, autor: autor, idioma: '', gen: gen, av: 0, eds: [] }, extra || {});
  o.eds.push({ asin: (t.replace(/\W/g, '') + 'XXXXXXXXXX').slice(0, 10).toUpperCase(), preco: 1000, o: o });
  return o;
}
var HP1 = obra('Harry Potter 1', 'J.K. Rowling', [0, 1], { av: 90000 });
var HP2 = obra('Harry Potter 2', 'J.K. Rowling', [0, 1], { av: 50000 });
var HP3 = obra('Harry Potter 3', 'J.K. Rowling', [0, 1], { av: 40000 });
var HP4 = obra('Harry Potter 4', 'J. K. Rowling', [0, 1], { av: 30000 });
var SDA = obra('O Senhor dos Anéis', 'J.R.R. Tolkien', [0, 1], { av: 40000 });
var NARNIA = obra('Nárnia', 'C.S. Lewis', [1], { av: 20000, idioma: 'Português' });
var NARNIA_EN = obra('Narnia (English Edition)', 'C.S. Lewis, Pauline Baynes', [1], { av: 20000, idioma: 'Inglês' });
var DOM = obra('Dom Casmurro', 'Machado de Assis', [0], { av: 80000 });
var CODIGO = obra('Código Civil', 'Fulano', [2], { av: 100000 });
var SEM = obra('Sem dados', '', [], { av: 999999 });
var OUTRO = obra('Outro Rowling', 'J.K. Rowling e Fulano', [3], { av: 10 });
var VAZIA = obra('Sem edição', 'Ciclano', [1], { av: 5 }); VAZIA.eds = [];
var FICCAO = ['A', 'B', 'C', 'D'].map(function (x) { return obra('Ficção ' + x, 'Autor ' + x, [0]); });
var OBRAS = [HP1, HP2, HP3, HP4, SDA, NARNIA, NARNIA_EN, DOM, CODIGO, SEM, OUTRO, VAZIA].concat(FICCAO);
function t(l) { return l.map(function (o) { return o.t; }); }
function rec(sementes, opc) { return t(R.recomendar(OBRAS, sementes, opc)); }

// autor principal, sem acento nem pontuação
assert.strictEqual(R.autor('J.K. Rowling e Fulano'), 'j k rowling');
assert.strictEqual(R.autor('C.S. Lewis, Pauline Baynes'), 'c s lewis');
assert.strictEqual(R.autor(''), '');

// gênero raro pesa mais que o comum
var idf = R.raridade(OBRAS);
assert.ok(idf[2] > idf[1] && idf[1] > idf[0]);

// sem livros de partida, nada
assert.deepStrictEqual(rec([]), []);

// a partir de Harry Potter: mesmo autor primeiro (no máximo 2 por autor), depois o gênero; os livros de partida ficam
// de fora pela obra; sem gênero nem autor em comum (Direito, obra sem dados) não entra; obra sem edição não entra
var r = rec([{ gen: [0, 1], autor: 'J.K. Rowling', peso: 1 }], { excluir: [HP1] });
assert.deepStrictEqual(r.slice(0, 2), ['Harry Potter 2', 'Harry Potter 3']);
assert.ok(r.indexOf('Harry Potter 4') < 0, 'no máximo 2 do mesmo autor');
assert.ok(r.indexOf('Harry Potter 1') < 0 && r.indexOf('Código Civil') < 0 && r.indexOf('Sem dados') < 0 && r.indexOf('Sem edição') < 0);
assert.ok(r.indexOf('O Senhor dos Anéis') >= 0 && r.indexOf('Nárnia') >= 0);
// Fantasia (raro) vence Literatura e Ficção (comum), mesmo com menos avaliações
assert.ok(r.indexOf('Nárnia') < r.indexOf('Dom Casmurro'));

// autor vazio no perfil não casa com obras sem autor
assert.deepStrictEqual(rec([{ gen: [], autor: '', peso: 1 }]), []);

// idioma conhecido: o mesmo livro em outro idioma cai para depois
r = rec([{ gen: [1], autor: 'Outra Pessoa', idioma: 'Português', peso: 1 }]);
assert.ok(r.indexOf('Nárnia') < r.indexOf('Narnia (English Edition)'));

// semAutor tira o autor inteiro (a página do livro já tem "Mais de …"), com coautor e grafia diferentes
r = rec([{ gen: [0, 1], autor: 'J.K. Rowling', peso: 1 }], { semAutor: ['J. K. Rowling'] });
assert.ok(!r.some(function (x) { return /Rowling|Harry/.test(x); }));
assert.strictEqual(r[0], 'O Senhor dos Anéis');

// o peso de cada livro de partida conta: Direito com peso maior passa na frente
r = rec([{ gen: [1], peso: 1 }, { gen: [2], peso: 3 }]);
assert.strictEqual(r[0], 'Código Civil');

// n limita o tamanho; o resultado é estável (desempate por avaliações e título)
assert.strictEqual(rec([{ gen: [0, 1], peso: 1 }], { n: 3 }).length, 3);
assert.deepStrictEqual(rec([{ gen: [0, 1], peso: 1 }]), rec([{ gen: [0, 1], peso: 1 }]));

console.log('recomenda.test.js: ok');
