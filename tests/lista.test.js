// Testes de comparador/web/lista.js. Rodar: node tests/lista.test.js
const assert = require('node:assert/strict');
const mem = {}; globalThis.localStorage = { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
const Lista = require('../comparador/web/lista.js');

assert.deepEqual(Lista.ler(), []);
assert.equal(Lista.alternar('8535902775'), true);
assert.equal(Lista.tem('8535902775'), true);
assert.equal(Lista.alternar('8535902775'), false);
assert.deepEqual(Lista.ler(), []);

// importação: JSON, texto solto e links; ignora lixo e repetidos
let r = Lista.importar('["8535902775","B0ABCDEFGH"]');
assert.deepEqual([r.lidos, r.adicionados], [2, 2]);
r = Lista.importar('8535902775, B0ABCDEFGH\nhttps://www.amazon.com.br/dp/8501116432?ref=x lixo curto');
assert.deepEqual([r.lidos, r.adicionados], [3, 1]);
assert.deepEqual(Lista.ler(), ['8535902775', 'B0ABCDEFGH', '8501116432']);
assert.equal(Lista.importar('nada aqui').lidos, 0);
assert.deepEqual(Lista.extrair('https://www.amazon.com.br/gp/product/b0abcdefgh'), ['B0ABCDEFGH']);

// round trip e armazenamento corrompido
assert.deepEqual(Lista.extrair(Lista.exportar()), Lista.ler());
mem.lista_v1 = '{quebrado';
assert.deepEqual(Lista.ler(), []);
mem.lista_v1 = '["8535902775","<script>"]';
assert.deepEqual(Lista.ler(), ['8535902775']);
Lista.remover('8535902775');
assert.deepEqual(Lista.ler(), []);
console.log('testes de lista.js ok');
