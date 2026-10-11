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
  root.Lista = { ler: ler, tem: tem, alternar: alternar, remover: remover, extrair: extrair, importar: importar, exportar: exportar };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.Lista;
})(typeof window !== 'undefined' ? window : globalThis);
