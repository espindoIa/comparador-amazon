import sqlite3
import unittest
from datetime import date

from comparador import relatorio, varredura
from comparador.relatorio import Evento


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
        t = relatorio.serie(c, "B1")
        self.assertEqual([x.preco for x in t], [5000, 6000, 4500, 6000])

    def test_veredito_desconto_real_e_falso(self):
        t = relatorio.serie(banco(), "B1")
        ev = Evento("BF", date(2026, 11, 27), date(2026, 11, 27))
        v = relatorio.veredito(t, ev)
        self.assertEqual((v.preco_evento, v.normal), (4500, 6000))  # 60 dias antes: 5000 (20d) e 6000 (37d)
        self.assertIn("menor preço", v.texto)
        falso = relatorio.veredito([x for x in t if x.preco != 4500] , ev)
        self.assertIn("sem observação", falso.texto)

    def test_nao_e_desconto(self):
        t = relatorio.serie(banco(), "B1")
        v = relatorio.veredito(t, Evento("X", date(2026, 11, 28), date(2026, 12, 1)))
        self.assertIn("NÃO é desconto", v.texto)

    def test_preco_inflado_antes_da_promocao(self):
        ev = Evento("BF", date(2026, 11, 27), date(2026, 11, 27))
        mk = lambda p, a, b: relatorio.Trecho(date.fromisoformat(a), date.fromisoformat(b), p, 8000)
        inflado = [mk(5000, "2026-09-28", "2026-11-05"), mk(6500, "2026-11-06", "2026-11-26"), mk(5100, "2026-11-27", "2026-11-27")]
        self.assertEqual(relatorio.veredito(inflado, ev).categoria, "inflado")
        ja_baixo = [mk(6000, "2026-09-28", "2026-11-10"), mk(5000, "2026-11-11", "2026-11-26"), mk(5000, "2026-11-27", "2026-11-27")]
        self.assertEqual(relatorio.veredito(ja_baixo, ev).categoria, "antes_do_evento")
        pequeno = [mk(5000, "2026-09-28", "2026-11-26"), mk(4900, "2026-11-27", "2026-11-27")]
        self.assertEqual(relatorio.veredito(pequeno, ev).categoria, "pequeno")

    def test_mediana_movel_90_dias(self):
        mk = lambda p, a, b: relatorio.Trecho(date.fromisoformat(a), date.fromisoformat(b), p, None)
        # 100 dias a 5000 e depois 10 dias a 9000: os últimos 90 dias ainda têm mediana 5000
        tr = [mk(5000, "2026-01-01", "2026-04-10"), mk(9000, "2026-04-11", "2026-04-20")]
        m = relatorio.mediana_movel(tr)
        self.assertEqual(m[0], (date(2026, 1, 1), 5000))
        self.assertEqual(m[-1], (date(2026, 4, 20), 5000))
        # janela de 10 dias: o preço novo domina
        self.assertEqual(relatorio.mediana_movel(tr, 10)[-1][1], 9000)
        # dias antigos saem da janela
        self.assertEqual(relatorio.mediana_movel([mk(100, "2026-01-01", "2026-03-01"), mk(300, "2026-03-02", "2026-06-30")])[-1][1], 300)

    def test_pagina_html(self):
        h = relatorio.pagina("Livro", "B1", relatorio.serie(banco(), "B1"),
                             [Evento("BF", date(2026, 11, 27), date(2026, 11, 27))])
        self.assertIn("<svg", h)
        self.assertIn("BF", h)


if __name__ == "__main__":
    unittest.main()
