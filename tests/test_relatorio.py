import glob
import json
import os
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

from comparador import relatorio, varredura

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")


def banco(caminho=":memory:"):
    c = sqlite3.connect(caminho)
    c.row_factory = sqlite3.Row
    varredura.criar_schema(c)
    c.execute("INSERT INTO catalogo (asin, titulo, formato, no, primeiro_visto, ultimo_visto) VALUES ('B1','Livro Teste','Capa comum','n','2026-09-01','2026-12-01')")
    for preco, capa, d0, d1 in [(5000, 8000, "2026-09-01", "2026-10-20"), (6000, 8000, "2026-10-21", "2026-11-26"),
                                (4500, 8000, "2026-11-27", "2026-11-27"), (6000, 8000, "2026-11-28", "2026-12-01")]:
        c.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) VALUES ('B1',?,?,?,?)",
                  (preco, capa, d0 + "T15:00:00+00:00", d1 + "T15:00:00+00:00"))
    return c


def navegador():
    for padrao in (os.environ.get("COMPARADOR_NAVEGADOR"), *glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"),
                   shutil.which("chromium"), shutil.which("google-chrome")):
        if padrao and os.path.exists(padrao):
            return padrao
    return None


class TestDados(unittest.TestCase):
    def test_serie_e_busca(self):
        c = banco()
        self.assertEqual(relatorio.buscar(c, "teste")[0][0], "B1")
        t = relatorio.serie(c, "B1")
        self.assertEqual([x[2] for x in t], [5000, 6000, 4500, 6000])
        self.assertEqual(t[0][0], date(2026, 9, 1).toordinal())
        self.assertEqual(t[0][3], 8000)

    def test_eventos(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "e.csv")
            open(p, "w", encoding="utf-8").write("nome,inicio,fim\nBF,2026-11-27,2026-11-27\n,2026-01-01,2026-01-01\n")
            self.assertEqual(relatorio.ler_eventos(p), [["BF", date(2026, 11, 27).toordinal(), date(2026, 11, 27).toordinal()]])
        self.assertEqual(relatorio.ler_eventos("/nao/existe.csv"), [])

    def test_pagina_avulsa_e_json_seguro(self):
        h = relatorio.pagina("Livro </script><b>", "B1", relatorio.serie(banco(), "B1"), [], aviso="SIMULADO")
        self.assertIn("Livro.montar", h)
        self.assertIn("SIMULADO", h)
        self.assertEqual(h.count("</script>"), 2)           # só os do próprio documento: o título não fecha a tag
        self.assertNotIn("Livro </script>", h)

    def test_cli_grafico_e_catalogo(self):
        with tempfile.TemporaryDirectory() as d:
            banco(f"{d}/c.db").commit()
            def rodar(*a):
                return subprocess.run([sys.executable, "-m", "comparador", "--db", f"{d}/c.db", *a],
                                      cwd=RAIZ, capture_output=True, text=True, timeout=60)
            r = rodar("grafico", "teste", "--saida", f"{d}/g.html", "--eventos", f"{RAIZ}/eventos.csv")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("gráfico em", r.stdout)
            self.assertIn("Livro Teste", open(f"{d}/g.html", encoding="utf-8").read())
            self.assertNotEqual(rodar("grafico", "inexistente").returncode, 0)
            r = rodar("catalogo")                            # o workflow depende destes comandos
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("itens no catálogo", r.stdout)


@unittest.skipUnless(NODE, "node não instalado")
class TestLivroJs(unittest.TestCase):
    def test_testes_do_javascript(self):
        r = subprocess.run([NODE, os.path.join(RAIZ, "tests", "livro.test.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_quartis_batem_com_a_biblioteca_do_python(self):
        """O JavaScript reimplementa statistics.quantiles(method='inclusive'): confere em séries aleatórias."""
        rng = random.Random(7)
        casos, esperado = [], []
        for _ in range(40):
            trechos, d = [], date(2026, 1, 1).toordinal()
            for _ in range(rng.randint(1, 12)):
                n = rng.randint(1, 60)
                trechos.append([d, d + n - 1, rng.randint(500, 20000), None])
                d += n + rng.choice([0, 0, 3])
            casos.append(trechos)
            dias = {x: t[2] for t in trechos for x in range(t[0], t[1] + 1)}
            ordem = sorted(dias)
            exp = []
            for x in ordem:
                w = [dias[y] for y in ordem if x - 89 <= y <= x]
                q = statistics.quantiles(w, n=4, method="inclusive") if len(w) > 1 else [w[0]] * 3
                exp.append([x, int(q[0]), int(statistics.median(w)), int(q[2])])
            esperado.append(exp)
        js = ("const L=require(process.argv[1]);const c=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "console.log(JSON.stringify(c.map(t=>L.janelaMovel(L.porDia(t)))))")
        r = subprocess.run([NODE, "-e", js, os.path.join(RAIZ, "comparador/web/livro.js")], input=json.dumps(casos),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), esperado)


@unittest.skipUnless(navegador(), "navegador não instalado")
class TestPaginaNoNavegador(unittest.TestCase):
    def test_controles_e_texto(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as d:
            ev = [["Black Friday 2026", date(2026, 11, 27).toordinal(), date(2026, 11, 27).toordinal()]]
            open(f"{d}/p.html", "w", encoding="utf-8").write(relatorio.pagina("Livro Teste", "B1", relatorio.serie(banco(), "B1"), ev))
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
                pg = b.new_page()
                erros = []
                pg.on("pageerror", lambda e: erros.append(str(e)))
                pg.goto(f"file://{d}/p.html")
                self.assertIn("Livro Teste", pg.inner_text("h1"))
                for sel in ('[data-op="faixa"]', '[data-op="capa"]', '[data-z="1"]', '[data-pan="-1"]', '[data-ev="0"]', '[data-per="0"]'):
                    pg.click(sel)
                pg.mouse.move(500, 300)
                self.assertIn("R$", pg.inner_text(".tip"))
                texto = pg.inner_text("body")
                for palavra in ("NÃO é desconto", "desconto real", "inflado"):
                    self.assertNotIn(palavra, texto)
                self.assertIn("Preço mais comum", texto)
                self.assertIn("R$ 45,00", texto)
                b.close()
            self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main()
