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
        self.assertIn("<svg", h)
        self.assertIn("Mediana", h)
        self.assertIn("SIMULADO", h)
        for palavra in ("NÃO é desconto", "desconto real", "Desconto real", "inflado"):
            self.assertNotIn(palavra, h)

    def test_pagina_com_lacuna_e_um_so_dia(self):
        relatorio.pagina("L", "X", [mk(5000, "2026-01-01", "2026-01-05"), mk(5200, "2026-03-01", "2026-03-02")], [])
        relatorio.pagina("L", "X", [mk(5000, "2026-01-01", "2026-01-01", None)], [])


if __name__ == "__main__":
    unittest.main()
