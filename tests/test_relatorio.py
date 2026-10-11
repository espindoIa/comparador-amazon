import sqlite3
import unittest
from datetime import date

from comparador import relatorio, varredura
from comparador.relatorio import Evento, Trecho

BF = Evento("BF", date(2026, 11, 27), date(2026, 11, 27))


def mk(p, a, b, capa=8000):
    return Trecho(date.fromisoformat(a), date.fromisoformat(b), p, capa)


def banco():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    varredura.criar_schema(c)
    c.execute("INSERT INTO catalogo VALUES ('B1','Livro Teste','Capa comum','n','2026-09-01','2026-12-01')")
    for preco, capa, d0, d1 in [(5000, 8000, "2026-09-01", "2026-10-20"), (6000, 8000, "2026-10-21", "2026-11-26"),
                                (4500, 8000, "2026-11-27", "2026-11-27"), (6000, 8000, "2026-11-28", "2026-12-01")]:
        c.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) VALUES ('B1',?,?,?,?)",
                  (preco, capa, d0 + "T15:00:00+00:00", d1 + "T15:00:00+00:00"))
    return c


class TestRelatorio(unittest.TestCase):
    def test_serie_e_busca(self):
        c = banco()
        self.assertEqual(relatorio.buscar(c, "teste")[0][0], "B1")
        self.assertEqual([x.preco for x in relatorio.serie(c, "B1")], [5000, 6000, 4500, 6000])

    def test_fatos_do_evento(self):
        f = relatorio.fatos_evento(relatorio.serie(banco(), "B1"), BF)
        self.assertEqual(f.preco, 4500)
        self.assertEqual(f.ate, date(2026, 11, 26))
        self.assertEqual((f.minimo, f.maximo), (5000, 6000))
        self.assertEqual(f.dia_minimo, date(2026, 10, 20))     # empate no mínimo: vale o dia mais recente
        self.assertEqual(f.mediana, 5000)                      # 50 dias a 5000 contra 37 a 6000
        self.assertEqual(f.pico_recente, 6000)
        self.assertIsNone(f.ultima_vez_igual_ou_menor)         # nunca esteve a R$ 45 antes
        self.assertEqual(f.dias_observados, 87)

    def test_sem_coleta_no_evento(self):
        self.assertIsNone(relatorio.fatos_evento([mk(5000, "2026-09-01", "2026-11-20")], BF))
        self.assertIn("sem coleta", relatorio.resumo_evento(BF, None))

    def test_ultima_vez_igual_ou_menor(self):
        t = [mk(4000, "2026-09-01", "2026-09-10"), mk(6000, "2026-09-11", "2026-11-26"), mk(4500, "2026-11-27", "2026-11-27")]
        self.assertEqual(relatorio.fatos_evento(t, BF).ultima_vez_igual_ou_menor, date(2026, 9, 10))

    def test_janela_de_90_dias(self):
        tr = [mk(5000, "2026-01-01", "2026-04-10"), mk(9000, "2026-04-11", "2026-04-20")]
        m = relatorio.janela_movel(relatorio.por_dia(tr))
        self.assertEqual(m[0], (date(2026, 1, 1), 5000, 5000, 5000))
        self.assertEqual(m[-1][2], 5000)                        # 10 dias a 9000 não mudam a mediana
        self.assertEqual(relatorio.janela_movel(relatorio.por_dia(tr), 10)[-1][2], 9000)
        velho = [mk(100, "2026-01-01", "2026-03-01"), mk(300, "2026-03-02", "2026-06-30")]
        self.assertEqual(relatorio.janela_movel(relatorio.por_dia(velho))[-1][2], 300)  # dias antigos saem

    def test_quartis(self):
        tr = [mk(1000, "2026-01-01", "2026-01-10"), mk(2000, "2026-01-11", "2026-01-20")]
        _, q1, med, q3 = relatorio.janela_movel(relatorio.por_dia(tr))[-1]
        self.assertTrue(q1 <= med <= q3)
        self.assertEqual((q1, q3), (1000, 2000))

    def test_pagina_sem_conclusoes_e_com_numeros(self):
        h = relatorio.pagina("Livro", "B1", relatorio.serie(banco(), "B1"), [BF], aviso="SIMULADO")
        self.assertIn("graf-box", h)
        self.assertIn("data-per", h)
        self.assertIn("Preço mais comum", h)
        self.assertIn("Mais barato", h)
        self.assertIn("SIMULADO", h)
        for palavra in ("NÃO é desconto", "desconto real", "Desconto real", "inflado"):
            self.assertNotIn(palavra, h)

    def test_dados_do_grafico_e_controles(self):
        h = relatorio.pagina("L", "B1", relatorio.serie(banco(), "B1"), [BF])
        for chave in ("data-per", 'data-z="1"', 'data-pan', 'data-op="faixa"', 'data-op="capa"', 'data-ev="0"'):
            self.assertIn(chave, h)
        d = relatorio._dados_js(relatorio.serie(banco(), "B1"), [BF, Evento("Antigo", date(2020, 1, 1), date(2020, 1, 1))])
        self.assertEqual(len(d["ev"]), 1)                          # evento distante não entra
        self.assertEqual(d["ev"][0][3], 4500)
        self.assertEqual(d["def"][0], d["full"][0])                # menos de 120 dias: abre mostrando tudo
        longo = relatorio._dados_js([mk(5000, "2026-01-01", "2026-12-31")], [])
        self.assertEqual(longo["def"][1] - longo["def"][0], 89)    # histórico longo: abre nos últimos 90 dias

    def test_cli_grafico(self):
        import contextlib, io, os, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as d:
            c = sqlite3.connect(f"{d}/c.db")
            varredura.criar_schema(c)
            c.execute("INSERT INTO catalogo VALUES ('B1','Livro Teste','Capa comum','n','2026-09-01','2026-12-01')")
            c.execute("INSERT INTO historico (asin, preco_centavos, desde, ate) VALUES ('B1', 5000, "
                      "'2026-10-01T12:00:00+00:00', '2026-10-05T12:00:00+00:00')")
            c.commit(); c.close()
            raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            r = subprocess.run([sys.executable, "-m", "comparador", "--db", f"{d}/c.db", "grafico", "teste",
                                "--saida", f"{d}/g.html", "--eventos", f"{raiz}/eventos.csv"],
                               cwd=raiz, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("gráfico em", r.stdout)
            self.assertIn("Livro Teste", open(f"{d}/g.html", encoding="utf-8").read())
            r = subprocess.run([sys.executable, "-m", "comparador", "--db", f"{d}/c.db", "grafico", "inexistente"],
                               cwd=raiz, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(r.returncode, 0)

    def test_pagina_com_lacuna_e_um_so_dia(self):
        relatorio.pagina("L", "X", [mk(5000, "2026-01-01", "2026-01-05"), mk(5200, "2026-03-01", "2026-03-02")], [])
        relatorio.pagina("L", "X", [mk(5000, "2026-01-01", "2026-01-01", None)], [])


if __name__ == "__main__":
    unittest.main()
