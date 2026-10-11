import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from comparador import site, varredura
from tests.test_relatorio import NODE, RAIZ, navegador


def banco(caminho, itens, aviso=None):
    c = sqlite3.connect(caminho)
    varredura.criar_schema(c)
    for asin, titulo, formato, trechos in itens:
        c.execute("INSERT INTO catalogo VALUES (?,?,?,?,?,?)", (asin, titulo, formato, "n", "2026-10-01T12:00:00+00:00",
                                                              (trechos[-1][1] if trechos else "2026-10-01") + "T12:00:00+00:00"))
        for desde, ate, preco, capa in trechos:
            c.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) VALUES (?,?,?,?,?)",
                      (asin, preco, capa, desde + "T12:00:00+00:00", ate + "T12:00:00+00:00"))
    if aviso:
        c.execute("CREATE TABLE aviso (texto TEXT)")
        c.execute("INSERT INTO aviso VALUES (?)", (aviso,))
    c.commit()
    c.close()


class TestSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_juntar_trechos(self):
        t = site.juntar_trechos([[10, 20, 5000, None], [15, 30, 5000, 8000], [31, 40, 4000, None], [60, 70, 4000, None]])
        self.assertEqual(t, [[10, 30, 5000, 8000], [31, 40, 4000, None], [60, 70, 4000, None]])   # 20 dias de buraco: não junta

    def test_construir_dois_bancos_com_livro_repetido(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Capa comum", [("2026-10-01", "2026-10-05", 5000, 8000)]),
                                ("B000000002", "Só no A", None, [("2026-10-01", "2026-10-01", 1000, None)])], aviso="SIMULADO")
        banco(self.d / "b.db", [("B000000001", "Livro Um", "Capa comum", [("2026-10-05", "2026-10-09", 5000, None)]),
                                ("B000000003", "Sem preço", None, [])])
        meta = site.construir([self.d / "a.db", self.d / "b.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        self.assertEqual(meta["itens"], 2)                       # o sem preço fica de fora
        self.assertEqual(meta["aviso"], "SIMULADO")
        for nome in site.ARQUIVOS_WEB:
            self.assertTrue((self.d / "out" / nome).exists(), nome)
        indice = json.loads((self.d / "out/dados/indice.json").read_text(encoding="utf-8"))["itens"]
        um = next(i for i in indice if i[0] == "B000000001")
        self.assertEqual(um[1:5], ["Livro Um", "Capa comum", 5000, 8000])
        h = json.loads((self.d / f"out/dados/h/{site.fragmento('B000000001')}.json").read_text(encoding="utf-8"))
        self.assertEqual(len(h["B000000001"]["h"]), 1)           # os dois históricos viraram um trecho só
        self.assertEqual(len(json.loads((self.d / "out/dados/eventos.json").read_text())), 2)

    def test_esconde_o_que_nao_foi_visto_depois_do_filtro_da_amazon(self):
        itens = [("B000000001", "Vendido pela Amazon", None, [("2026-10-01", "2026-10-20", 5000, None)]),
                 ("B000000002", "De vendedor de fora", None, [("2026-10-01", "2026-10-05", 3000, None)])]
        banco(self.d / "a.db", itens)
        c = sqlite3.connect(self.d / "a.db")
        c.execute("UPDATE catalogo SET ultimo_visto = '2026-10-05T12:00:00+00:00' WHERE asin = 'B000000002'")
        c.execute("INSERT INTO config VALUES ('so_amazon_desde', '2026-10-10T12:00:00+00:00')")
        c.commit()
        # antes de uma varredura completa com o filtro: nada é escondido
        site.construir([self.d / "a.db"], self.d / "s1")
        self.assertEqual(json.loads((self.d / "s1/dados/indice.json").read_text())["itens"].__len__(), 2)
        c.execute("INSERT INTO dias VALUES ('vendidos', '2026-10-11', '2026-10-11T20:00:00+00:00')")
        c.commit()
        c.close()
        site.construir([self.d / "a.db"], self.d / "s2")
        indice = json.loads((self.d / "s2/dados/indice.json").read_text())["itens"]
        self.assertEqual([i[0] for i in indice], ["B000000001"])
        h = json.loads((self.d / f"s2/dados/h/{site.fragmento('B000000002')}.json").read_text())
        self.assertIn("B000000002", h)                          # o histórico segue disponível (lista de desejos)

    def test_cli_site(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
        r = subprocess.run(["python", "-m", "comparador", "site", str(self.d / "a.db"), "--saida", str(self.d / "s")],
                           cwd=RAIZ, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 livros", r.stdout)

    @unittest.skipUnless(NODE, "node não instalado")
    def test_testes_da_lista_em_javascript(self):
        r = subprocess.run([NODE, os.path.join(RAIZ, "tests", "lista.test.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(navegador(), "navegador não instalado")
class TestSiteNoNavegador(unittest.TestCase):
    def _servir(self, itens, aviso=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        banco(d / "a.db", itens, aviso)
        site.construir([d / "a.db"], d / "s", Path(RAIZ) / "eventos.csv")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d / "s")))
        srv.RequestHandlerClass.log_message = lambda *a, **k: None
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_filtros_e_ordenacao_da_busca(self):
        from playwright.sync_api import sync_playwright
        h = lambda p, c=None: [("2026-10-01", "2026-10-20", p, c)]
        base = self._servir([
            ("A000000001", "Alfa", "Capa comum", h(5000, 10000)),     # 50% de desconto
            ("A000000002", "Beta", "Kindle", h(1500)),
            ("A000000003", "Gama", "Capa dura", h(9000, 9500)),       # ~5%
            ("A000000004", "Delta", "Capa comum", h(3000)),
            ("A000000005", "Epsilon", "Audiolivro", h(2000, 4000))])  # 50%
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/index.html")
            pg.evaluate("localStorage.clear()")
            pg.reload()
            pg.wait_for_selector("#q:not([disabled])")
            titulos = lambda: pg.eval_on_selector_all("#res .it .tt a", "e => e.map(x => x.textContent)")
            self.assertEqual(pg.inner_text("#res").startswith("Digite"), True)           # sem busca nem filtro: só a dica
            pg.select_option("#o-ord", "preco")                                          # ordenar sozinho já lista tudo
            pg.wait_for_selector("#res .it")
            self.assertEqual(titulos(), ["Beta", "Epsilon", "Delta", "Alfa", "Gama"])
            pg.select_option("#o-ord", "preco_desc")
            self.assertEqual(titulos(), ["Gama", "Alfa", "Delta", "Epsilon", "Beta"])
            pg.select_option("#o-ord", "desconto")
            self.assertEqual(titulos()[:2], ["Alfa", "Epsilon"])                         # 50% e 50%, empate por título
            pg.select_option("#o-ord", "titulo")
            self.assertEqual(titulos(), ["Alfa", "Beta", "Delta", "Epsilon", "Gama"])
            pg.click(".filtros summary")
            pg.click('[data-fmt="Capa comum"]')
            self.assertEqual(titulos(), ["Alfa", "Delta"])
            pg.click('[data-fl="desc"]')
            self.assertEqual(titulos(), ["Alfa"])
            self.assertIn("(2)", pg.inner_text("#n-filtros"))
            pg.click("#limpar")
            pg.fill("#pmin", "20")
            pg.fill("#pmax", "50")
            pg.wait_for_function("document.querySelectorAll('#res .it').length === 3")
            self.assertEqual(titulos(), ["Alfa", "Delta", "Epsilon"])                    # R$ 20 a R$ 50
            pg.fill("#q", "ep")
            pg.wait_for_function("document.querySelectorAll('#res .it').length === 1")
            self.assertEqual(titulos(), ["Epsilon"])
            pg.click("#res .fav")                                                        # na lista
            pg.fill("#q", "")
            pg.click('[data-fl="lista"]')
            pg.wait_for_function("document.querySelectorAll('#res .it').length === 1")
            self.assertEqual(titulos(), ["Epsilon"])
            b.close()
        self.assertEqual(erros, [])

    def test_livro_sem_coleta_recente_continua_na_lista(self):
        from playwright.sync_api import sync_playwright
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        banco(d / "a.db", [("A000000001", "Vendido pela Amazon", None, [("2026-10-01", "2026-10-20", 5000, None)]),
                           ("A000000002", "Saiu da Amazon", None, [("2026-10-01", "2026-10-05", 3000, None)])])
        c = sqlite3.connect(d / "a.db")
        c.execute("UPDATE catalogo SET ultimo_visto = '2026-10-05T12:00:00+00:00' WHERE asin = 'A000000002'")
        c.execute("INSERT INTO config VALUES ('so_amazon_desde', '2026-10-10T12:00:00+00:00')")
        c.execute("INSERT INTO dias VALUES ('vendidos', '2026-10-11', '2026-10-11T20:00:00+00:00')")
        c.commit()
        c.close()
        site.construir([d / "a.db"], d / "s")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d / "s")))
        srv.RequestHandlerClass.log_message = lambda *a, **k: None
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            pg.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
            pg.evaluate("localStorage.setItem('lista_v1', JSON.stringify(['A000000002']))")
            pg.reload()
            pg.wait_for_selector("#q:not([disabled])")
            pg.fill("#q", "saiu")
            pg.wait_for_function("document.querySelector('#res').textContent.includes('Nenhum livro')")  # sumiu da busca
            pg.click("#t-lista")
            pg.wait_for_selector("#lst .it b")
            self.assertIn("sem coleta recente", pg.inner_text("#lst"))              # mas segue na lista, com o último preço
            self.assertIn("R$ 30,00", pg.inner_text("#lst"))
            b.close()

    def test_buscar_adicionar_a_lista_e_abrir_historico(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            banco(d / "a.db", [("8535902775", "A paciente silenciosa", "Capa comum", [("2026-10-01", "2026-10-20", 3499, 6490)]),
                               ("B0ABCDEFGH", "Outro livro", "Kindle", [("2026-10-01", "2026-10-20", 1999, None)])])
            site.construir([d / "a.db"], d / "s", Path(RAIZ) / "eventos.csv")
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d / "s")))
            srv.RequestHandlerClass.log_message = lambda *a, **k: None
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.shutdown)
            base = f"http://127.0.0.1:{srv.server_port}"
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
                pg = b.new_page()
                erros = []
                pg.on("pageerror", lambda e: erros.append(str(e)))
                pg.goto(f"{base}/index.html")
                pg.wait_for_selector("#q:not([disabled])")
                pg.fill("#q", "silenciósa PACIENTE")            # sem acento e ordem trocada também acha
                pg.wait_for_selector(".it")
                self.assertIn("A paciente silenciosa", pg.inner_text("#res"))
                self.assertNotIn("Outro livro", pg.inner_text("#res"))
                pg.click(".fav")
                pg.click("#t-lista")
                pg.wait_for_selector("#lst .it b")
                self.assertIn("R$ 34,99", pg.inner_text("#lst"))
                self.assertIn("(1)", pg.inner_text("#t-lista"))
                pg.click("#lst .tt a")
                pg.wait_for_selector(".graf-box svg")
                self.assertIn("A paciente silenciosa", pg.inner_text("h1"))
                pg.goto(f"{base}/livro.html?asin=ZZZZZZZZZZ")
                pg.wait_for_selector("main p")
                self.assertIn("não está no catálogo", pg.inner_text("main"))
                b.close()
            self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main()
