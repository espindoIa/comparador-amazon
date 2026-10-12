// Testes dos cálculos de comparador/web/livro.js. Rodar: node tests/livro.test.js
const assert = require('node:assert/strict');
const L = require('../comparador/web/livro.js');

const dia = (s) => Math.round(Date.parse(s + 'T00:00:00Z') / 864e5) + 719163;   // = date.toordinal()
const tr = (p, a, b, capa = 8000) => [dia(a), dia(b), p, capa];
const BF = ['BF', dia('2026-11-27'), dia('2026-11-27')];
const base = [tr(5000, '2026-09-01', '2026-10-20'), tr(6000, '2026-10-21', '2026-11-26'), tr(4500, '2026-11-27', '2026-11-27')];

let n = 0; const t = (nome, f) => { f(); n++; };

t('fatos do evento', () => {
  const f = L.fatosEvento(base, BF);
  assert.equal(f.preco, 4500);
  assert.equal(f.ate, dia('2026-11-26'));
  assert.deepEqual([f.minimo, f.maximo], [5000, 6000]);
  assert.equal(f.diaMinimo, dia('2026-10-20'));        // empate no mínimo: vale o dia mais recente
  assert.equal(f.mediana, 5000);                       // 50 dias a 5000 contra 37 a 6000
  assert.equal(f.picoRecente, 6000);
  assert.equal(f.ultimaIgualOuMenor, null);            // nunca esteve a R$ 45 antes
  assert.equal(f.diasObservados, 87);
  assert.equal(f.capa, 8000);
});

t('sem coleta no evento', () => {
  assert.equal(L.fatosEvento([tr(5000, '2026-09-01', '2026-11-20')], BF), null);
  assert.match(L.resumoEvento(BF, null), /sem coleta/);
});

t('última vez igual ou menor', () => {
  const s = [tr(4000, '2026-09-01', '2026-09-10'), tr(6000, '2026-09-11', '2026-11-26'), tr(4500, '2026-11-27', '2026-11-27')];
  assert.equal(L.fatosEvento(s, BF).ultimaIgualOuMenor, dia('2026-09-10'));
});

t('janela de 90 dias', () => {
  const s = [tr(5000, '2026-01-01', '2026-04-10'), tr(9000, '2026-04-11', '2026-04-20')];
  const m = L.janelaMovel(L.porDia(s));
  assert.deepEqual(m[0], [dia('2026-01-01'), 5000, 5000, 5000]);
  assert.equal(m[m.length - 1][2], 5000);              // 10 dias a 9000 não mudam a mediana
  assert.equal(L.janelaMovel(L.porDia(s), 10).at(-1)[2], 9000);
  const velho = [tr(100, '2026-01-01', '2026-03-01'), tr(300, '2026-03-02', '2026-06-30')];
  assert.equal(L.janelaMovel(L.porDia(velho)).at(-1)[2], 300);   // dias antigos saem da janela
});

t('quartis', () => {
  const s = [tr(1000, '2026-01-01', '2026-01-10'), tr(2000, '2026-01-11', '2026-01-20')];
  const [, q1, med, q3] = L.janelaMovel(L.porDia(s)).at(-1);
  assert.ok(q1 <= med && med <= q3);
  assert.deepEqual([q1, q3], [1000, 2000]);
});

t('um só dia e lacuna não quebram', () => {
  const g = L.dadosGrafico([tr(5000, '2026-01-01', '2026-01-01', null)], []);
  assert.equal(g.full[1] - g.full[0], 6);
  const h = L.dadosGrafico([tr(5000, '2026-01-01', '2026-01-05'), tr(5200, '2026-03-01', '2026-03-02')], []);
  assert.equal(h.tr.length, 2);
});

t('dados do gráfico: evento distante fica de fora; histórico longo abre em 90 dias', () => {
  const g = L.dadosGrafico(base, [BF, ['Antigo', dia('2020-01-01'), dia('2020-01-01')]]);
  assert.equal(g.ev.length, 1);
  assert.equal(g.ev[0][3], 4500);
  assert.equal(g.def[0], g.full[0]);                   // menos de 120 dias: abre mostrando tudo
  const longo = L.dadosGrafico([tr(5000, '2026-01-01', '2026-12-31')], []);
  assert.equal(longo.def[1] - longo.def[0], 89);
});

t('poucos dados: estatísticas e aviso dizem o que falta', () => {
  const um = L.fatos([tr(6165, '2026-10-11', '2026-10-11')], dia('2026-10-11'));
  const e1 = L.estatisticas(um, dia('2026-10-11'));
  assert.match(e1, /a partir de 2 dias/);
  assert.match(e1, /1 dia com preço/);
  assert.doesNotMatch(e1, /R\$ 61,65/);                // sem repetir o preço atual como mínimo e máximo
  assert.match(L.avisoDados(um), /1 dia de preço/);
  const dois = L.fatos([tr(6000, '2026-10-10', '2026-10-11')], dia('2026-10-11'));
  assert.match(L.estatisticas(dois, dia('2026-10-10')), /Menor preço<\/span><b>R\$ 60,00/);
  assert.match(L.avisoDados(dois), /2 dias com preço/);
  assert.doesNotMatch(L.comparacoes(dois), /preço mais comum/);   // sem preço mais comum, sem comparação
  const muitos = L.fatos([tr(6000, '2026-09-01', '2026-10-10'), tr(4500, '2026-10-11', '2026-10-11')], dia('2026-10-11'));
  assert.equal(L.avisoDados(muitos), '');
  assert.match(L.comparacoes(muitos), /25% abaixo do preço mais comum/);
});

t('título sem "(English Edition)"', () => {
  assert.deepEqual(L.limpar('Atomic Habits (English Edition)'), { t: 'Atomic Habits', idioma: 'Inglês' });
  assert.deepEqual(L.limpar('Livro (Portuguese Edition)'), { t: 'Livro', idioma: '' });
  assert.deepEqual(L.limpar('Box (Edição 2)'), { t: 'Box (Edição 2)', idioma: '' });
});

t('ASIN a partir de link ou ISBN', () => {
  assert.equal(L.asinDe('https://www.amazon.com.br/Habitos-Atomicos/dp/8550807567/ref=sr_1_1'), '8550807567');
  assert.equal(L.asinDe('978-85-5080-756-6'), '8550807567');
  assert.equal(L.asinDe('b08xyz1234'), 'B08XYZ1234');
  assert.equal(L.asinDe('harry potter'), null);
  assert.equal(L.asinDe('9791234567896'), null);
});

t('marcas do eixo ficam dentro dos dados', () => {
  assert.deepEqual(L.marcas(4210, 6130), [4500, 5000, 5500, 6000]);
  assert.deepEqual(L.marcas(5000, 5000), [5000]);
  for (const m of L.marcas(1234, 98765)) assert.ok(m >= 1234 && m <= 98765);
});

t('gráfico curto não se estica até eventos distantes', () => {
  const curto = L.dadosGrafico([tr(5000, '2026-10-11', '2026-10-11')], [BF]);
  assert.equal(curto.ev.length, 0);
  assert.equal(curto.full[1] - curto.full[0], 6);
  const longo = L.dadosGrafico([tr(5000, '2026-09-01', '2026-10-11')], [BF]);
  assert.equal(longo.ev.length, 1);
});

t('link da Amazon', () => {
  assert.equal(L.linkAmazon('8556510841'), 'https://www.amazon.com.br/dp/8556510841');
});

t('formatação', () => {
  assert.equal(L.brl(123456), 'R$ 1.234,56');
  assert.equal(L.brl(3990), 'R$ 39,90');
  assert.equal(L.brl(null), '–');
  assert.equal(L.dl(dia('2026-11-27')), '27/11/2026');
  assert.equal(L.comparar(4500, 6000), '25% abaixo do');
  assert.equal(L.esc('<b>"x"</b>'), '&lt;b&gt;&quot;x&quot;&lt;/b&gt;');
});

console.log(`${n} testes de livro.js ok`);
