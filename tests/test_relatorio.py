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

    def test_pagina_html(self):
        h = relatorio.pagina("Livro", "B1", relatorio.serie(banco(), "B1"),
                             [Evento("BF", date(2026, 11, 27), date(2026, 11, 27))])
        self.assertIn("<svg", h)
        self.assertIn("BF", h)


if __name__ == "__main__":
    unittest.main()
