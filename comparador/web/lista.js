/* Lista de desejos do app: fica só no navegador (localStorage), sem conta e sem servidor. */
(function (root) {
  'use strict';
  var CHAVE = 'lista_v1', ASIN = /^[A-Z0-9]{10}$/;
  function ler() {
    try { var v = JSON.parse(localStorage.getItem(CHAVE) || '[]'); return Array.isArray(v) ? v.filter(function (a) { return ASIN.test(a); }) : []; } catch (e) { return []; }
  }
  function gravar(l) { try { localStorage.setItem(CHAVE, JSON.stringify(l)); return true; } catch (e) { return false; } }
  function tem(asin) { return ler().indexOf(asin) >= 0; }
  function alternar(asin) {
    var l = ler(), i = l.indexOf(asin);
    if (i >= 0) l.splice(i, 1); else l.push(asin);
    gravar(l); return i < 0;
  }
  function remover(asin) { gravar(ler().filter(function (a) { return a !== asin; })); }
  // aceita um JSON com a lista, ASINs separados por espaço, vírgula ou linha, ou links da Amazon (.../dp/ASIN)
  function extrair(texto) {
    var achados = [], t = String(texto || '').trim(), v;
    try { v = JSON.parse(t); if (Array.isArray(v)) t = v.join(' '); } catch (e) { }
    (t.match(/\/(?:dp|gp\/product)\/([A-Za-z0-9]{10})/g) || []).forEach(function (m) { achados.push(m.split('/').pop().toUpperCase()); });
    t.replace(/https?:\/\/\S+/g, ' ').split(/[\s,;]+/).forEach(function (x) { if (ASIN.test(x)) achados.push(x); });
    return achados.filter(function (a, i) { return achados.indexOf(a) === i; });
  }
  function importar(texto) {
    var novos = extrair(texto), l = ler(), n = 0;
    novos.forEach(function (a) { if (l.indexOf(a) < 0) { l.push(a); n++; } });
    gravar(l); return { lidos: novos.length, adicionados: n };
  }
  function exportar() { return JSON.stringify(ler()); }
  function inserir(asin, pos) { var l = ler().filter(function (a) { return a !== asin; }); l.splice(Math.min(pos, l.length), 0, asin); gravar(l); }

  // Preços "desde a sua última visita": guarda os preços vistos em cada dia de coleta. A comparação é com
  // a visita feita num dia de coleta anterior, então recarregar a página no mesmo dia não apaga as mudanças.
  // hoje = dia da coleta mais recente; precos = {asin: centavos}. Devolve {dia, precos} da visita anterior, ou null.
  var VISTOS = 'vistos_v1';
  function visita(hoje, precos) {
    var s; try { s = JSON.parse(localStorage.getItem(VISTOS) || 'null'); } catch (e) { s = null; }
    if (!s || typeof s !== 'object') s = {};
    if (!s.a || s.a.d !== hoje) { if (s.a && s.a.d < hoje) s.b = s.a; s.a = { d: hoje, p: {} }; }
    for (var k in precos) s.a.p[k] = precos[k];
    try { localStorage.setItem(VISTOS, JSON.stringify(s)); } catch (e) { }
    return s.b ? { dia: s.b.d, precos: s.b.p } : null;
  }
  root.Lista = { ler: ler, tem: tem, alternar: alternar, remover: remover, inserir: inserir, extrair: extrair, importar: importar, exportar: exportar, visita: visita };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.Lista;
})(typeof window !== 'undefined' ? window : globalThis);
