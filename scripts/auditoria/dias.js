// Quantos livros têm diasObservados >= 14 (MIN_COMUM) e qual o maior intervalo de dias, com livro.js do repositório.
const L = require(process.argv[2] + '/comparador/web/livro.js'), fs = require('fs'), path = require('path');
const pasta = process.argv[3] + '/site/dados/h';
let n = 0, com14 = 0, maxSpan = 0, maior30 = 0;
for (const f of fs.readdirSync(pasta)) {
  const d = JSON.parse(fs.readFileSync(path.join(pasta, f)));
  for (const a in d) { const tr = d[a].h, ult = tr[tr.length - 1][1], fa = L.fatos(tr, ult); n++;
    if (fa.diasObservados >= L.MIN_COMUM) com14++;
    const G = L.dadosGrafico(tr, []), span = G.dias[G.dias.length - 1][0] - G.full[0]; maxSpan = Math.max(maxSpan, span); if (span > 30) maior30++; }
}
console.log(JSON.stringify({livros: n, com_14_dias_ou_mais: com14, maior_intervalo_dias: maxSpan, com_mais_de_30: maior30}));
