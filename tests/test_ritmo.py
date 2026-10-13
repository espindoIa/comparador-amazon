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
        self.assertEqual([Ritmo(p).pistas for p in (8, 15, 21, 22, 30, 31, 60, 61, 90, 91, 120, 400)], [1, 1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 8])

    def test_bloqueio_recua_para_o_minimo_e_baixa_o_teto(self):
        x = Ritmo(60, teto=100)
        x.falha(grave=True)
        self.assertEqual((x.ppm, x.teto, x.pistas, x.falhas), (r.PPM_RECUO, 42.0, 1, 1))
        for _ in range(300):                            # a subida recomeça devagar, de baixo, e para no teto novo
            x.pagina_boa()
        self.assertLess(x.ppm, 42.0 + 1e-9)
        self.assertGreater(x.ppm, r.PPM_RECUO)
        x.falha(grave=True)                             # novo bloqueio: teto cai de novo (70% do ritmo em que falhou)
        self.assertLess(x.teto, 42.0)

    def test_falha_leve_isolada_so_corta_o_ritmo_pela_metade(self):
        x = Ritmo(60, teto=60, a_cada=100)
        x.falha()
        self.assertEqual((x.ppm, x.teto), (30.0, 60))   # o teto fica: uma página curta ao acaso não corrói o dia
        for _ in range(400):
            x.pagina_boa()
        self.assertEqual(x.ppm, 60)                     # e o ritmo volta ao teto em 4 degraus (400 páginas)

    def test_falhas_leves_isoladas_pelo_dia_nao_corroem_o_teto(self):
        x = Ritmo(60, teto=60, a_cada=100)
        for _ in range(8):                              # uma a cada 600 páginas boas
            for _ in range(600):
                x.pagina_boa()
            x.falha()
            self.assertEqual(x.teto, 60)
        self.assertEqual(x.falhas, 8)

    def test_falha_leve_repetida_baixa_o_teto(self):
        x = Ritmo(60, teto=60, a_cada=100)
        x.falha()                                       # 60 -> 30
        for _ in range(150):                            # menos de JANELA_REPETIDA páginas boas depois: repetida
            x.pagina_boa()
        ppm = x.ppm
        x.falha()
        self.assertEqual((x.ppm, x.teto), (r.PPM_RECUO, ppm * 0.7))

    def test_a_primeira_falha_nunca_e_repetida(self):
        x = Ritmo(60, teto=60)
        x.falha()
        self.assertEqual(x.teto, 60)

    def test_falha_nunca_leva_o_teto_abaixo_do_recuo(self):
        x = Ritmo(10)
        for _ in range(5):
            x.falha(grave=True)
        self.assertEqual((x.ppm, x.teto), (r.PPM_RECUO, r.PPM_RECUO))
        y = Ritmo(10)
        y.falha()
        self.assertEqual(y.ppm, r.PPM_RECUO)            # a metade de 10 seria 5: não passa do mínimo

    def test_falha_zera_a_contagem_de_paginas_boas(self):
        x = Ritmo(20, teto=60, a_cada=100)
        for _ in range(99):
            x.pagina_boa()
        x.falha()
        ppm = x.ppm
        x.pagina_boa()
        self.assertEqual(x.ppm, ppm)                    # a página 100 "boa" não conta: contou de novo do zero

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


class TestTetoQueSeAjusta(unittest.TestCase):
    def execucao(self, cfg, *, ppm=60.0, teto=60.0, inicial=60.0, paginas=8000, bloqueios=0, leves=1, hoje="2026-10-13"):
        x = Ritmo(ppm, teto)
        x.ppm = ppm
        return r.aprender(cfg, hoje, x, inicial, paginas, bloqueios, leves)

    def test_sem_nada_guardado_comeca_no_padrao(self):
        self.assertEqual(r.ritmo_guardado({}, r.PPM_TETO_PADRAO), (r.PPM_BASE, r.PPM_TETO_PADRAO))
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "lixo"}, 60.0)[1], 60.0)

    def test_retoma_perto_do_ultimo_ritmo_limpo_sem_passar_do_teto(self):
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "75", "ritmo_ultimo_limpo": "70"}, 60.0), (56.0, 75.0))
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "50", "ritmo_ultimo_limpo": "70"}, 60.0), (50.0, 50.0))
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "75", "ritmo_ultimo_limpo": ""}, 60.0)[0], r.PPM_BASE)

    def test_dia_limpo_no_teto_sobe_25_por_cento_uma_vez_por_dia_ate_o_maximo(self):
        n = self.execucao({})
        self.assertEqual((n["ritmo_teto"], n["ritmo_subiu_em"], n["ritmo_ultimo_limpo"]), ("75.0", "2026-10-13", "60.0"))
        # mesmo dia de novo: não sobe outra vez
        self.assertNotIn("ritmo_teto", self.execucao({"ritmo_subiu_em": "2026-10-13"}, ppm=75, teto=75, inicial=75))
        # dia seguinte: sobe, e para em 90
        self.assertEqual(self.execucao({"ritmo_subiu_em": "2026-10-13"}, ppm=75, teto=75, inicial=75, hoje="2026-10-14")["ritmo_teto"], "90.0")
        self.assertNotIn("ritmo_teto", self.execucao({}, ppm=90, teto=90, inicial=90, hoje="2026-10-15"))

    def test_so_sobe_com_evidencia(self):
        self.assertNotIn("ritmo_teto", self.execucao({}, paginas=1500))                    # poucas páginas
        self.assertNotIn("ritmo_teto", self.execucao({}, leves=10))                        # 1,25 falha leve por mil páginas
        self.assertNotIn("ritmo_teto", self.execucao({}, ppm=40))                          # não chegou a rodar no teto
        self.assertIn("ritmo_ultimo_limpo", self.execucao({}, ppm=40))                     # mas guardou o ritmo limpo

    def test_bloqueio_baixa_o_teto_e_segura_a_subida(self):
        x = Ritmo(60, 75)
        x.falha(grave=True)                                                                 # o freio da execução: teto 70% de 60
        n = r.aprender({}, "2026-10-13", x, 75.0, 3000, 1, 0)
        self.assertEqual((n["ritmo_teto"], n["ritmo_espera_ate"], n["ritmo_ultimo_limpo"]), ("42.0", "2026-10-16", ""))
        # nos dias de espera, uma execução limpa guarda o ritmo mas não sobe
        espera = {"ritmo_espera_ate": "2026-10-16"}
        self.assertNotIn("ritmo_teto", self.execucao(espera, ppm=42, teto=42, inicial=42, hoje="2026-10-14"))
        self.assertIn("ritmo_teto", self.execucao(espera, ppm=42, teto=42, inicial=42, hoje="2026-10-16"))


if __name__ == "__main__":
    unittest.main()
