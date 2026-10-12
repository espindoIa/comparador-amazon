import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from comparador import site, varredura
from tests.test_relatorio import NODE, RAIZ, navegador


def banco(caminho, itens, aviso=None):
    c = sqlite3.connect(caminho)
    varredura.criar_schema(c)
    for asin, titulo, formato, trechos in itens:
        c.execute("INSERT INTO catalogo (asin, titulo, formato, no, primeiro_visto, ultimo_visto) VALUES (?,?,?,?,?,?)", (asin, titulo, formato, "n", "2026-10-01T12:00:00+00:00",
                                                              (trechos[-1][1] if trechos else "2026-10-01") + "T12:00:00+00:00"))
        for desde, ate, preco, capa in trechos:
            c.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) VALUES (?,?,?,?,?)",
                      (asin, preco, capa, desde + "T12:00:00+00:00", ate + "T12:00:00+00:00"))
    if aviso:
        c.execute("CREATE TABLE aviso (texto TEXT)")
        c.execute("INSERT INTO aviso VALUES (?)", (aviso,))
    c.commit()
    c.close()


def indice(saida):
    """(parte 0 do índice v3, todas as obras de todas as partes)."""
    dados = Path(saida) / "dados"
    p0 = json.loads((dados / "indice-0.json").read_text(encoding="utf-8"))
    obras = []
    for n in range(p0["partes"]):
        obras += json.loads((dados / f"indice-{n}.json").read_text(encoding="utf-8"))["o"]
    return p0, obras


def edicoes(saida):
    """{asin: (obra, edição)} do índice v3."""
    return {e[0]: (o, e) for o in indice(saida)[1] for e in o[8]}


def historico(saida, asin):
    return json.loads((Path(saida) / f"dados/h/{site.fragmento(asin)}.json").read_text(encoding="utf-8"))[asin]


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
        ind = indice(self.d / "out")[0]
        o, e = edicoes(self.d / "out")["B000000001"]
        self.assertEqual(o[0], "Livro Um")
        self.assertEqual([ind["fmt"][e[1]], e[2], e[3]], ["Capa comum", 5000, 8000])
        self.assertEqual(ind["hoje"], meta["ultima_coleta"])
        self.assertEqual(e[4], 0)                                # visto na última coleta
        h = json.loads((self.d / f"out/dados/h/{site.fragmento('B000000001')}.json").read_text(encoding="utf-8"))
        self.assertEqual(len(h["B000000001"]["h"]), 1)           # os dois históricos viraram um trecho só
        self.assertEqual(len(json.loads((self.d / "out/dados/eventos.json").read_text())), 2)

    def test_detalhes_do_livro_vao_para_o_indice_e_o_historico(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Capa dura", [("2026-10-01", "2026-10-05", 5000, None)]),
                                ("B000000002", "Livro Dois", "Kindle", [("2026-10-01", "2026-10-05", 900, None)])])
        c = sqlite3.connect(self.d / "a.db")
        c.execute("UPDATE catalogo SET autor='Ana', imagem='img1', publicado='2024-08-05', idioma='Português', "
                  "obra='B000000001' WHERE asin='B000000001'")
        c.commit()
        c.close()
        site.construir([self.d / "a.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        ed = edicoes(self.d / "out")
        idi = indice(self.d / "out")[0]["idi"]
        self.assertEqual(ed["B000000001"][0][:5], ["Livro Um", "Ana", "img1", 2024, idi.index("Português") + 1])
        self.assertEqual(ed["B000000002"][0][:5], ["Livro Dois", "", "", 0, 0])           # livro ainda sem detalhes
        h = json.loads((self.d / f"out/dados/h/{site.fragmento('B000000001')}.json").read_text(encoding="utf-8"))
        self.assertEqual(h["B000000001"]["autor"], "Ana")

    def test_banco_antigo_sem_colunas_de_detalhe_ainda_vira_site(self):
        c = sqlite3.connect(self.d / "velho.db")
        c.executescript(
            "CREATE TABLE catalogo (asin TEXT PRIMARY KEY, titulo TEXT, formato TEXT, no TEXT, "
            "primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL);"
            "CREATE TABLE historico (id INTEGER PRIMARY KEY, asin TEXT, preco_centavos INTEGER, preco_capa_centavos INTEGER, "
            "desde TEXT, ate TEXT, vezes INTEGER DEFAULT 1);"
            "INSERT INTO catalogo VALUES ('B000000001','Velho','Capa comum','n','2026-10-01T12:00:00+00:00','2026-10-02T12:00:00+00:00');"
            "INSERT INTO historico (asin, preco_centavos, desde, ate) VALUES ('B000000001', 100, '2026-10-01T12:00:00+00:00', '2026-10-02T12:00:00+00:00');")
        c.commit()
        c.close()
        self.assertEqual(site.construir([self.d / "velho.db"], self.d / "out", Path(RAIZ) / "eventos.csv")["itens"], 1)

    def test_esconde_o_que_nao_foi_visto_depois_do_filtro_da_amazon(self):
        itens = [("B000000001", "Vendido pela Amazon", None, [("2026-10-01", "2026-10-20", 5000, None)]),
                 ("B000000002", "De vendedor de fora", None, [("2026-10-01", "2026-10-08", 3000, None)])]
        banco(self.d / "a.db", itens)
        c = sqlite3.connect(self.d / "a.db")
        c.execute("UPDATE catalogo SET ultimo_visto = '2026-10-08T12:00:00+00:00' WHERE asin = 'B000000002'")
        c.execute("INSERT INTO config VALUES ('so_amazon_desde', '2026-10-10T12:00:00+00:00')")
        c.commit()
        # antes de uma varredura completa com o filtro: nada é escondido
        site.construir([self.d / "a.db"], self.d / "s1")
        self.assertEqual(len(edicoes(self.d / "s1")), 2)
        c.execute("INSERT INTO dias VALUES ('vendidos', '2026-10-11', '2026-10-11T20:00:00+00:00')")
        c.commit()
        c.close()
        site.construir([self.d / "a.db"], self.d / "s2")
        self.assertEqual(list(edicoes(self.d / "s2")), ["B000000001"])
        h = json.loads((self.d / f"s2/dados/h/{site.fragmento('B000000002')}.json").read_text())
        self.assertIn("B000000002", h)                          # o histórico segue disponível (lista de desejos)

    def test_formatos_da_mesma_obra_viram_um_item(self):
        h = lambda p: [("2026-10-01", "2026-10-05", p, None)]
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Kindle", h(1900)), ("B000000002", "Livro Um", "Capa comum", h(4000)),
                                ("B000000003", "Livro Um", "Capa dura", h(9000)), ("B000000004", "Outro", "Capa comum", h(3000)),
                                ("B000000005", "Agenda 2027", "Agenda ou Calendário", h(2000))])
        c = sqlite3.connect(self.d / "a.db")
        # a capa dura apareceu no card da capa comum, que apareceu no card do Kindle: tudo uma obra só
        c.execute("UPDATE catalogo SET obra='B000000001', autor='Ana' WHERE asin IN ('B000000001','B000000002')")
        c.execute("UPDATE catalogo SET obra='B000000002' WHERE asin='B000000003'")
        c.commit()
        c.close()
        meta = site.construir([self.d / "a.db"], self.d / "out")
        obras = indice(self.d / "out")[1]
        self.assertEqual((meta["itens"], meta["obras"]), (4, 2))       # a agenda não é livro
        um = next(o for o in obras if o[0] == "Livro Um")
        self.assertEqual([e[0] for e in um[8]], ["B000000002", "B000000003", "B000000001"])   # físicos primeiro, do mais barato
        self.assertEqual(um[1], "Ana")
        self.assertIn("B000000005", json.loads((self.d / f"out/dados/h/{site.fragmento('B000000005')}.json").read_text()))

    def test_preco_mais_comum_so_com_dias_suficientes(self):
        d = date(2026, 10, 1).toordinal()
        self.assertIsNone(site.mais_comum([[d, d + 12, 5000, None]], d + 12))          # 13 dias
        self.assertEqual(site.mais_comum([[d, d + 9, 5000, None], [d + 10, d + 13, 3000, None]], d + 13), 5000)
        velho = [[d, d + 99, 1000, None], [d + 100, d + 119, 2000, None]]
        self.assertEqual(site.mais_comum(velho, d + 119), 1000)                  # 70 dias a 1000 e 20 a 2000 na janela
        self.assertEqual(site.mais_comum(velho, d + 200), None)                  # nada nos últimos 90 dias

    def test_baixaram_de_preco(self):
        h = {"B000000001": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 4000, None)],   # -20%: entra
             "B000000002": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 4900, None)],   # -2%: não
             "B000000003": [("2026-10-01", "2026-10-03", 5000, None), ("2026-10-04", "2026-10-09", 3000, None)],   # caiu há dias
             "B000000004": [("2026-10-01", "2026-10-08", 3000, None), ("2026-10-09", "2026-10-09", 5000, None)],   # subiu
             "B000000005": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 2500, None)]}   # -50%
        banco(self.d / "a.db", [(a, a, "Capa comum", t) for a, t in h.items()])
        site.construir([self.d / "a.db"], self.d / "out")
        baixa = json.loads((self.d / "out/dados/destaques.json").read_text())["baixa"]
        self.assertEqual(baixa, [["B000000005", 5000, date(2026, 10, 9).toordinal()], ["B000000001", 5000, date(2026, 10, 9).toordinal()]])

    def _detalhar(self, nome, sql, *args):
        c = sqlite3.connect(self.d / nome)
        c.execute(sql, args)
        c.commit()
        c.close()

    def test_partes_do_indice_vao_das_mais_avaliadas_para_as_menos(self):
        h = [("2026-10-01", "2026-10-05", 1000, None)]
        banco(self.d / "a.db", [(f"B00000000{i}", f"Livro {i}", "Capa comum", h) for i in range(1, 6)])
        for i, av in ((1, 10), (2, 5000), (3, None), (4, 300), (5, 90)):
            self._detalhar("a.db", "UPDATE catalogo SET avaliacoes = ?, nota = 45 WHERE asin = ?", av, f"B00000000{i}")
        with mock.patch.object(site, "PARTE_INICIAL", 2), mock.patch.object(site, "PARTE", 2):
            meta = site.construir([self.d / "a.db"], self.d / "out")
        p0, obras = indice(self.d / "out")
        self.assertEqual(p0["partes"], 3)
        self.assertEqual([o[0] for o in p0["o"]], ["Livro 2", "Livro 4"])
        self.assertEqual([o[0] for o in obras], ["Livro 2", "Livro 4", "Livro 5", "Livro 1", "Livro 3"])  # sem avaliações no fim
        self.assertEqual([o[6:8] for o in obras[:2]], [[45, 5000], [45, 300]])
        self.assertEqual(meta["itens"], 5)                       # conta todas as partes (a trava do site compara isto)
        self.assertNotIn("fmt", json.loads((self.d / "out/dados/indice-1.json").read_text()))   # tabelas só na parte 0

    def test_generos_vem_da_tabela_e_do_primeiro_no(self):
        h = [("2026-10-01", "2026-10-05", 1000, None)]
        banco(self.d / "a.db", [("B000000001", "Romance e fantasia", "Capa comum", h), ("B000000002", "Só no ranking", "Kindle", h)])
        self._detalhar("a.db", "UPDATE catalogo SET no = '7882388011' WHERE asin = 'B000000001'")
        self._detalhar("a.db", "UPDATE catalogo SET no = ? WHERE asin = 'B000000002'", varredura.NO_LIVROS)
        self._detalhar("a.db", "INSERT INTO generos VALUES ('B000000001', '7841775011')")
        site.construir([self.d / "a.db"], self.d / "out")
        p0, _ = indice(self.d / "out")
        ed = edicoes(self.d / "out")
        self.assertEqual(sorted(p0["gen"][g][1] for g in ed["B000000001"][0][5]), ["Fantasia, Horror e Ficção Científica", "Romance"])
        self.assertEqual(ed["B000000002"][0][5], [])
        self.assertEqual(historico(self.d / "out", "B000000001")["gen"],
                         [["7841775011", "Fantasia, Horror e Ficção Científica"], ["7882388011", "Romance"]])
        ngen = json.loads((self.d / "out/dados/destaques.json").read_text())["ngen"]
        self.assertEqual(ngen[[g[0] for g in p0["gen"]].index("7882388011")], 1)

    def test_some_da_busca_quem_nao_aparece_ha_duas_semanas(self):
        banco(self.d / "a.db", [("B000000001", "Atual", None, [("2026-10-01", "2026-10-20", 1000, None)]),
                                ("B000000002", "Sumiu", None, [("2026-10-01", "2026-10-06", 1000, None)]),
                                ("B000000003", "Quase", None, [("2026-10-01", "2026-10-07", 1000, None)])])
        site.construir([self.d / "a.db"], self.d / "out")
        self.assertEqual(sorted(edicoes(self.d / "out")), ["B000000001", "B000000003"])
        self.assertEqual(historico(self.d / "out", "B000000002")["h"][0][2], 1000)    # o histórico continua lá

    def test_formatos_e_outras_edicoes_vao_para_o_historico(self):
        h = lambda p: [("2026-10-01", "2026-10-05", p, None)]
        banco(self.d / "a.db", [("B000000001", "Dom Casmurro", "Capa comum", h(2000)), ("B000000002", "Dom Casmurro", "Kindle", h(500)),
                                ("B000000003", "Dom Casmurro: Edição comentada", "Capa dura", h(6000)),
                                ("B000000004", "Dom Casmurro (Volume 2)", "Capa comum", h(3000)),
                                ("B000000005", "Dom Casmurro", "Capa comum", h(1000))])
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'MACHADO DE ASSIS', obra = 'B000000001' WHERE asin IN ('B000000001', 'B000000002')")
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'Machado de Assis' WHERE asin IN ('B000000003', 'B000000004')")
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'Não informado' WHERE asin = 'B000000005'")
        site.construir([self.d / "a.db"], self.d / "out")
        um = historico(self.d / "out", "B000000002")
        self.assertEqual(um["autor"], "Machado de Assis")                          # estava todo em maiúsculas
        self.assertEqual(um["eds"], [["B000000001", "Capa comum", 2000], ["B000000002", "Kindle", 500]])
        self.assertEqual(um["outras"], [["B000000003", "Dom Casmurro: Edição comentada", "", "Capa dura", 6000]])  # volume 2 e autor genérico, não
        self.assertNotIn("eds", historico(self.d / "out", "B000000003"))
        self.assertEqual(historico(self.d / "out", "B000000003")["outras"][0][0], "B000000001")

    def test_baixaram_de_preco_por_familia_e_menor_preco_registrado(self):
        h = lambda a, b: [("2026-09-20", "2026-10-08", a, None), ("2026-10-09", "2026-10-09", b, None)]
        banco(self.d / "a.db", [("B000000001", "Físico 1", "Capa comum", h(5000, 2500)), ("B000000002", "Físico 2", "Capa comum", h(5000, 4000)),
                                ("B000000003", "Kindle 1", "Kindle", h(5000, 500)), ("B000000004", "Kindle 2", "Kindle", h(5000, 1000)),
                                ("B000000005", "Parado", "Capa comum", [("2026-09-20", "2026-10-09", 3000, None)])])
        with mock.patch.object(site, "MAX_BAIXA", 1):
            site.construir([self.d / "a.db"], self.d / "out")
        d = json.loads((self.d / "out/dados/destaques.json").read_text())
        self.assertEqual([b[0] for b in d["baixa"]], ["B000000001", "B000000003"])          # a maior queda de cada família
        self.assertEqual(sorted(d["menor"]), ["B000000001", "B000000002", "B000000003", "B000000004"])   # o parado não
        self.assertEqual(sorted(e[0] for o in d["o"] for e in o[8]), ["B000000001", "B000000002", "B000000003", "B000000004"])
        self.assertEqual(edicoes(self.d / "out")["B000000001"][1][6], 2500)                  # menor preço registrado

    def test_nomes_e_titulos(self):
        self.assertEqual(site.nome_proprio("ELIO D'ANNA"), "Elio D'Anna")
        self.assertEqual(site.nome_proprio("FERNANDO J. DE LUCCA"), "Fernando J. de Lucca")
        self.assertEqual(site.nome_proprio("J.R.R. TOLKIEN"), "J.R.R. Tolkien")
        self.assertEqual(site.nome_proprio("bell hooks"), "bell hooks")                       # só mexe no que é todo maiúsculo
        self.assertEqual(site.nome_proprio("SUN TZU"), "Sun Tzu")
        self.assertEqual(site.limpar_titulo("Pride and Prejudice (English Edition)"), ("Pride and Prejudice", "Inglês"))
        self.assertEqual(site.limpar_titulo("Livro (Portuguese Edition)"), ("Livro", ""))
        self.assertEqual(site.limpar_titulo("Livro (Collector's Edition)"), ("Livro (Collector's Edition)", ""))
        self.assertEqual(site.titulo_base("Dom Casmurro: Edição comentada"), "dom casmurro")
        self.assertEqual(site.titulo_base("Metro: Level 3"), "metro: level 3")              # outro volume, não outra edição
        self.assertEqual(site.titulo_base("O Hobbit (Capa dura) - edição de luxo"), "o hobbit")

    def test_arquivos_do_app_levam_a_versao(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
        site.construir([self.d / "a.db"], self.d / "out")
        html = (self.d / "out/index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'src="app\.js\?v=[0-9a-f]{10}"')
        self.assertRegex(html, r'href="estilo\.css\?v=[0-9a-f]{10}"')

    def test_cli_site(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
        r = subprocess.run(["python", "-m", "comparador", "site", str(self.d / "a.db"), "--saida", str(self.d / "s")],
                           cwd=RAIZ, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 livros", r.stdout)

    @unittest.skipUnless(NODE, "node não instalado")
    def test_testes_da_lista_e_da_busca_em_javascript(self):
        for nome in ("lista.test.js", "busca.test.js"):
            r = subprocess.run([NODE, os.path.join(RAIZ, "tests", nome)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(navegador(), "navegador não instalado")
class TestSiteNoNavegador(unittest.TestCase):
    def _servir(self, itens, aviso=None, avaliacoes=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        banco(d / "a.db", itens, aviso)
        if avaliacoes:
            c = sqlite3.connect(d / "a.db")
            c.executemany("UPDATE catalogo SET avaliacoes = ? WHERE asin = ?", [(n, a) for a, n in avaliacoes.items()])
            c.execute("UPDATE catalogo SET obra = 'R000000001' WHERE asin LIKE 'R%'")
            c.commit()
            c.close()
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
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.clear()")
            pg.goto(f"{base}/?o=preco")                                                  # ordenar sozinho já lista tudo
            pg.wait_for_selector("#res .row")
            titulos = lambda: pg.eval_on_selector_all("#res .row .tt", "e => e.map(x => x.textContent)")
            esperar = lambda n: pg.wait_for_function(f"document.querySelectorAll('#res .row').length === {n}")
            self.assertEqual(titulos(), ["Beta", "Epsilon", "Delta", "Alfa", "Gama"])
            pg.select_option("#ord", "preco_desc")
            self.assertEqual(titulos(), ["Gama", "Alfa", "Delta", "Epsilon", "Beta"])
            pg.select_option("#ord", "desconto")
            self.assertEqual(titulos()[:2], ["Alfa", "Epsilon"])                         # 50% e 50%, empate por título
            pg.select_option("#ord", "titulo")
            self.assertEqual(titulos(), ["Alfa", "Beta", "Delta", "Epsilon", "Gama"])
            self.assertIn("3", pg.inner_text('[data-fam="f"]'))                          # contagem no filtro
            pg.click('[data-fam="f"]')                                                   # livro físico: capa comum e dura
            self.assertEqual(titulos(), ["Alfa", "Delta", "Gama"])
            self.assertIn("f=f", pg.url)
            pg.reload()                                                                  # filtros ficam no endereço
            pg.wait_for_selector("#res .row")
            self.assertEqual(titulos(), ["Alfa", "Delta", "Gama"])
            pg.click('[data-acao="limpar-filtros"]')
            esperar(5)
            pg.click('[data-acao="preco"]')
            pg.fill("#de", "20")
            pg.fill("#ate", "50")
            esperar(3)
            self.assertEqual(titulos(), ["Alfa", "Delta", "Epsilon"])                    # R$ 20 a R$ 50
            pg.fill("#q", "ep")
            esperar(1)
            self.assertEqual(titulos(), ["Epsilon"])
            pg.click("#res .row")
            pg.wait_for_selector("[data-salvar]")
            pg.click("[data-salvar]")
            self.assertEqual(pg.inner_text("#cont"), "1")
            pg.go_back()                                                                 # volta para a mesma busca
            pg.wait_for_selector("#res .row")
            self.assertEqual(titulos(), ["Epsilon"])
            self.assertEqual(pg.input_value("#q"), "ep")
            self.assertEqual(pg.locator("#res .salvo").count(), 1)
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
        base = f"http://127.0.0.1:{srv.server_port}"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.setItem('lista_v1', JSON.stringify(['A000000002']))")
            pg.goto(f"{base}/?q=saiu")
            pg.wait_for_function("document.querySelector('#res').textContent.includes('Nenhum livro')")  # sumiu da busca
            pg.click(".hdr-lista")
            pg.wait_for_selector("#lst .row b")
            self.assertIn("último preço visto em 05/10/2026", pg.inner_text("#lst"))      # mas segue na lista, com o último preço
            self.assertIn("R$ 30,00", pg.inner_text("#lst"))
            b.close()

    def test_indice_em_partes_busca_sem_dizer_que_nao_achou_antes_da_hora(self):
        from playwright.sync_api import sync_playwright
        h = lambda p: [("2026-10-01", "2026-10-20", p, None)]
        itens = [(f"P00000000{i}", f"Popular {i}", "Capa comum", h(1000 + i)) for i in range(1, 6)]
        itens += [("R000000001", "Raridade escondida", "Capa comum", h(3000)), ("R000000002", "Raridade escondida", "Kindle", h(900))]
        with mock.patch.object(site, "PARTE_INICIAL", 2), mock.patch.object(site, "PARTE", 2):   # 3 partes, a raridade na última
            base = self._servir(itens, avaliacoes={f"P00000000{i}": 1000 - i for i in range(1, 6)})
        self.assertTrue(base)
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros, presos, pedidos = [], [], []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("request", lambda r: pedidos.append(r.url))
            pg.route("**/dados/indice-2.json*", lambda route: presos.append(route))      # a última parte demora
            pg.goto(f"{base}/?q=raridade")
            pg.wait_for_selector("#res .carregando")
            self.assertNotIn("Nenhum livro", pg.inner_text("#res"))
            pg.fill("#q", "popular")                                                    # o que já chegou aparece logo
            pg.wait_for_function("document.querySelectorAll('#res .row').length === 4")
            self.assertIn("4 livros até agora", pg.inner_text("#ferr"))
            pg.fill("#q", "raridade")
            pg.wait_for_function("location.search.includes('raridade') && document.querySelector('#res .carregando')"
                                 " && !document.querySelector('#res .row')")
            self.assertNotIn("Nenhum livro", pg.inner_text("#res"))
            pg.click('[data-acao="preco"]')                                            # a pessoa está digitando um preço...
            pg.fill("#de", "5")
            presos[0].continue_()                                                       # ...quando chega a última parte
            pg.wait_for_function("document.querySelector('#res').textContent.includes('Raridade escondida')")
            self.assertEqual(pg.evaluate("document.activeElement.id"), "de")            # o campo não foi refeito
            self.assertEqual(pg.input_value("#de"), "5")
            pg.click('[data-acao="limpar-filtros"]')
            self.assertEqual(pg.locator("#res .carregando").count(), 0)
            pg.fill("#q", "xyzw")
            pg.wait_for_selector("#res .vazio")                                         # agora sim: nada encontrado
            # a página de um livro não baixa o índice: formatos vêm do histórico do próprio livro
            pg2 = b.new_page()
            pedidos2 = []
            pg2.on("request", lambda r: pedidos2.append(r.url))
            pg2.goto(f"{base}/?livro=R000000002")
            pg2.wait_for_selector("#graf svg")
            self.assertEqual(pg2.locator("#fmts .fmt").count(), 2)
            self.assertIn("R$ 30,00", pg2.inner_text("#fmts"))
            self.assertFalse([u for u in pedidos2 if "indice-" in u], pedidos2)
            b.close()
        self.assertEqual(erros, [])

    def test_buscar_salvar_na_lista_e_abrir_historico(self):
        from playwright.sync_api import sync_playwright
        base = self._servir([("8535902775", "A paciente silenciosa", "Capa comum", [("2026-10-01", "2026-10-20", 3499, 6490)]),
                             ("B0ABCDEFGH", "Outro livro", "Kindle", [("2026-10-01", "2026-10-20", 1999, None)])])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/index.html")
            pg.wait_for_selector(".boas h1")
            pg.fill("#q", "silenciósa PACIENTE")                                         # sem acento e ordem trocada também acha
            pg.wait_for_selector("#res .row")
            self.assertIn("A paciente silenciosa", pg.inner_text("#res"))
            self.assertNotIn("Outro livro", pg.inner_text("#res"))
            pg.click("#res .row")
            pg.wait_for_selector("#graf svg")
            self.assertIn("A paciente silenciosa", pg.inner_text("h1"))
            self.assertIn("R$ 34,99", pg.inner_text(".preco-g"))
            pg.click("[data-salvar]")
            self.assertEqual(pg.get_attribute("[data-salvar]", "aria-pressed"), "true")
            pg.click(".hdr-lista")
            pg.wait_for_selector("#lst .row b")
            self.assertIn("R$ 34,99", pg.inner_text("#lst"))
            self.assertEqual(pg.inner_text("#cont"), "1")
            pg.click("#lst .tt")
            pg.wait_for_selector("#graf svg")
            pg.goto(f"{base}/?q=978-85-359-0277-8")
            pg.wait_for_selector("#res .row")
            self.assertIn("A paciente silenciosa", pg.inner_text("#res"))
            pg.goto(f"{base}/livro.html?asin=8535902775")                                # endereço antigo ainda funciona
            pg.wait_for_selector("#graf svg")
            self.assertIn("livro=8535902775", pg.url)
            pg.goto(f"{base}/?livro=ZZZZZZZZZZ")
            pg.wait_for_selector(".vazio h2")
            self.assertIn("Livro não encontrado", pg.inner_text("main"))
            b.close()
        self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main()
