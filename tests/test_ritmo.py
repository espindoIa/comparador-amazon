"""Testes do controlador de ritmo da coleta. Rodar: python -m unittest discover -s tests"""

import unittest

from comparador import ritmo as r
from comparador.ritmo import Ritmo

EXATO = lambda a, b: 1.0  # noqa: E731  (sem variação aleatória)


class TestRitmo(unittest.TestCase):
    def test_padrao_e_o_ritmo_ja_medido_sem_subida(self):
        x = Ritmo()
        self.assertEqual((x.ppm, x.teto, x.pistas), (r.PPM_BASE, r.PPM_BASE, 1))
        for _ in range(1000):
            x.pagina_boa()
        self.assertEqual(x.ppm, r.PPM_BASE)            # teto = ritmo inicial: não acelera sozinho

    def test_sobe_a_cada_n_paginas_boas_ate_o_teto(self):
        x = Ritmo(20, teto=60, a_cada=100)
        vistos = [x.ppm]
        for _ in range(600):
            x.pagina_boa()
            if x.ppm != vistos[-1]:
                vistos.append(x.ppm)
        self.assertEqual([round(v) for v in vistos], [20, 25, 31, 39, 49, 60])
        self.assertEqual(x.ppm, 60)

    def test_nunca_passa_do_maximo_absoluto(self):
        self.assertEqual(Ritmo(500, teto=900).ppm, r.PPM_MAXIMO)
        self.assertEqual(Ritmo(500, teto=900).teto, r.PPM_MAXIMO)

    def test_pistas_acompanham_o_ritmo(self):
        # acima de PPM_MAXIMO (120) o ritmo é cortado, então 3 é o máximo na prática
        self.assertEqual([Ritmo(p).pistas for p in (8, 21, 45, 46, 90, 91, 135, 400)], [1, 1, 1, 2, 2, 3, 3, 3])

    def test_falha_recua_e_baixa_o_teto(self):
        x = Ritmo(60, teto=100)
        x.falha()
        self.assertEqual((x.ppm, x.teto, x.pistas, x.falhas), (r.PPM_RECUO, 42.0, 1, 1))
        for _ in range(300):                            # a subida recomeça devagar, de baixo, e para no teto novo
            x.pagina_boa()
        self.assertLess(x.ppm, 42.0 + 1e-9)
        self.assertGreater(x.ppm, r.PPM_RECUO)
        x.falha()                                       # nova falha: teto cai de novo (70% do ritmo em que falhou)
        self.assertLess(x.teto, 42.0)

    def test_falha_nunca_leva_o_teto_abaixo_do_recuo(self):
        x = Ritmo(10)
        for _ in range(5):
            x.falha()
        self.assertEqual((x.ppm, x.teto), (r.PPM_RECUO, r.PPM_RECUO))

    def test_falha_zera_a_contagem_de_paginas_boas(self):
        x = Ritmo(20, teto=60, a_cada=100)
        for _ in range(99):
            x.pagina_boa()
        x.falha()
        x.pagina_boa()
        self.assertEqual(x.ppm, r.PPM_RECUO)            # a página 100 "boa" não conta: contou de novo do zero

    def test_atrasos_escalonados_no_intervalo_do_ritmo(self):
        x = Ritmo(60, sorteio=EXATO)
        self.assertEqual(x.atrasos(1), [0.0])
        self.assertEqual(x.atrasos(3), [0.0, 1.0, 2.0])

    def test_atrasos_com_variacao_ficam_em_ordem_e_perto_da_media(self):
        x = Ritmo(60)
        for _ in range(200):
            a = x.atrasos(4)
            self.assertEqual(a, sorted(a))
            self.assertEqual(a[0], 0.0)
            for p, q in zip(a, a[1:]):
                self.assertTrue(0.7 - 1e-9 <= q - p <= 1.3 + 1e-9)

    def test_espera_completa_o_tempo_do_lote(self):
        x = Ritmo(60, sorteio=EXATO)
        self.assertEqual(x.espera(1, 0.85), 0.15000000000000002)    # 1 requisição ocupa 1 s
        self.assertEqual(x.espera(2, 0.5), 1.5)
        self.assertEqual(x.espera(1, 5.0), 0.0)                     # nunca negativa

    def test_ritmo_medio_e_o_programado(self):
        x = Ritmo(30)                                               # com variação ±30%
        total = sum(x.espera(1, 0.0) for _ in range(5000))
        self.assertAlmostEqual(total / 5000, 2.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
