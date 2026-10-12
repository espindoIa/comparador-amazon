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

// desfazer a remoção devolve o livro à mesma posição
['A000000001', 'A000000002', 'A000000003'].forEach((a) => Lista.alternar(a));
Lista.remover('A000000002');
Lista.inserir('A000000002', 1);
assert.deepEqual(Lista.ler(), ['A000000001', 'A000000002', 'A000000003']);

// "desde sua última visita": compara com a visita de um dia de coleta anterior
assert.equal(Lista.visita(100, { A000000001: 5000 }), null);                 // primeira visita
assert.equal(Lista.visita(100, { A000000001: 5000 }), null);                 // mesmo dia de novo
let v = Lista.visita(101, { A000000001: 4000, A000000002: 3000 });
assert.deepEqual(v, { dia: 100, precos: { A000000001: 5000 } });
v = Lista.visita(101, { A000000001: 4000 });                                   // recarregar não apaga a comparação
assert.equal(v.precos.A000000001, 5000);
assert.deepEqual(Lista.visita(102, {}).precos, { A000000001: 4000, A000000002: 3000 });
mem.vistos_v1 = 'lixo';
assert.equal(Lista.visita(103, {}), null);
// vistos recentemente: o mais novo primeiro, sem repetir, no máximo 12; lixo é ignorado
for (let i = 0; i < 14; i++) Lista.visto({ a: 'R0000000' + String(i).padStart(2, '0'), t: 'Livro ' + i, img: 'x', p: 1000 + i });
Lista.visto({ a: 'R000000005', t: 'Livro 5', img: 'x', p: 999 });
let rec = Lista.recentes();
assert.equal(rec.length, 12);
assert.deepEqual(rec[0], { a: 'R000000005', t: 'Livro 5', img: 'x', p: 999 });
assert.equal(rec.filter((x) => x.a === 'R000000005').length, 1);
Lista.visto({ a: '<script>', t: 'x' });
assert.equal(Lista.recentes()[0].a, 'R000000005');
mem.recentes_v1 = '{"a":1}';
assert.deepEqual(Lista.recentes(), []);
Lista.visto({ a: 'R000000001', t: 'Um' });
Lista.limparRecentes();
assert.deepEqual(Lista.recentes(), []);

// preço-alvo: define, troca, apaga com 0; ignora lixo
Lista.definirAlvo('A000000001', 3990);
Lista.definirAlvo('A000000002', 1500.4);
Lista.definirAlvo('A000000001', 2990);
Lista.definirAlvo('ruim', 100);
assert.deepEqual(Lista.alvos(), { A000000001: 2990, A000000002: 1500 });
Lista.definirAlvo('A000000002', 0);
assert.deepEqual(Lista.alvos(), { A000000001: 2990 });
mem.alvos_v1 = '[1,2]';
assert.deepEqual(Lista.alvos(), {});
console.log('testes de lista.js ok');
