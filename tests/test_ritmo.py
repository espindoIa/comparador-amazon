"""Testes do controlador de ritmo da coleta. Rodar: python -m unittest discover -s tests"""

import unittest
from datetime import datetime, timedelta, timezone

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

    def test_bloqueio_nao_muda_o_ritmo(self):
        # a proteção contra bloqueio saiu (15/10/2026): nem o ritmo nem o teto caem
        x = Ritmo(60, teto=100)
        for _ in range(5):
            x.falha(grave=True)
        self.assertEqual((x.ppm, x.teto, x.falhas), (60, 100, 0))
        x.falha()                                       # a falha leve continua recuando, e não conta como repetida
        self.assertEqual((x.ppm, x.teto), (30.0, 100))

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
            x.falha()
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
    def execucao(self, cfg, *, ppm=60.0, teto=60.0, inicial=60.0, paginas=8000, bloqueios=0, leves=1, hoje="2026-10-13",
                 maximo=r.PPM_TETO_AUTO_MAX):
        x = Ritmo(ppm, teto)
        x.ppm = ppm
        return r.aprender(cfg, hoje, x, inicial, paginas, bloqueios, leves, maximo)

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

    def test_evidencia_do_dia_soma_execucoes_curtas(self):
        # depois de um bloqueio (8 páginas/min) cada execução lê ~1.300 páginas: sozinha, nunca seria evidência
        x = Ritmo(8, 8)
        x.ppm = 8
        n = r.aprender({}, "2026-10-16", x, 8.0, 1300, 0, 0)
        self.assertEqual(n, {})
        n = r.aprender({}, "2026-10-16", x, 8.0, 1300, 0, 0, evidencia=(3900, 1))           # 3 execuções no dia
        self.assertEqual((n["ritmo_teto"], n["ritmo_ultimo_limpo"]), ("10.0", "8.0"))
        self.assertNotIn("ritmo_teto", r.aprender({}, "2026-10-16", x, 8.0, 1300, 0, 0, evidencia=(3900, 5)))   # falhas demais
        # bloqueio não baixa o teto nem tira a evidência do dia
        x.falha(grave=True)
        n = r.aprender({}, "2026-10-16", x, 8.0, 1300, 1, 0, evidencia=(9000, 0))
        self.assertEqual((n["ritmo_teto"], "ritmo_espera_ate" in n), ("10.0", False))

    def test_bloqueio_nao_baixa_o_teto_e_falha_leve_repetida_baixa_e_segura_a_subida(self):
        x = Ritmo(60, 75)
        x.falha(grave=True)
        n = r.aprender({}, "2026-10-13", x, 75.0, 3000, 1, 0)
        self.assertNotIn("ritmo_espera_ate", n)
        self.assertEqual(n["ritmo_ultimo_limpo"], "60.0")
        x.falha()                                                                           # 60 -> 30
        x.falha()                                                                           # repetida: teto 70% de 30
        n = r.aprender({}, "2026-10-13", x, 75.0, 3000, 0, 2)
        self.assertEqual((n["ritmo_teto"], n["ritmo_espera_ate"], n["ritmo_ultimo_limpo"]), ("21.0", "2026-10-16", ""))
        # nos dias de espera, uma execução limpa guarda o ritmo mas não sobe
        espera = {"ritmo_espera_ate": "2026-10-16"}
        self.assertNotIn("ritmo_teto", self.execucao(espera, ppm=42, teto=42, inicial=42, hoje="2026-10-14"))
        self.assertIn("ritmo_teto", self.execucao(espera, ppm=42, teto=42, inicial=42, hoje="2026-10-16"))

    def test_limite_menor_vale_sobre_o_teto_guardado_e_o_teto_nao_passa_dele(self):
        # várias sequências em paralelo: cada uma sobe no máximo até o limite (60), mesmo que o banco tenha 75 guardado
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "75", "ritmo_ultimo_limpo": "70"}, 60.0, maximo=60.0), (56.0, 60.0))
        self.assertEqual(r.ritmo_guardado({"ritmo_teto": "45"}, 60.0, maximo=60.0)[1], 45.0)   # o que é menor continua
        self.assertEqual(r.ritmo_guardado({}, 60.0, maximo=50.0)[1], 50.0)
        self.assertNotIn("ritmo_teto", self.execucao({}, maximo=60.0))                         # limpo no limite: não sobe
        self.assertIn("ritmo_ultimo_limpo", self.execucao({}, maximo=60.0))
        # abaixo do limite continua subindo, e para nele
        self.assertEqual(self.execucao({}, ppm=45, teto=45, inicial=45, maximo=60.0)["ritmo_teto"], "56.2")
        self.assertEqual(self.execucao({}, ppm=56, teto=56, inicial=56, maximo=60.0)["ritmo_teto"], "60.0")


class TestCiclo(unittest.TestCase):
    """O ciclo (horas entre passadas completas) é um degrau guardado no banco: rampa para baixo, recuo para cima."""

    def t(self, dia, hora=12):
        return datetime(2026, 10, dia, hora, 0, tzinfo=timezone.utc)

    def aprende(self, cfg, dia, **kw):
        a = dict(paginas=3000, bloqueios=0, leves=1, interrompida=False, completou=True)
        a.update(kw)
        novo = r.aprender_ciclo(cfg, self.t(dia), a["paginas"], a["bloqueios"], a["leves"], a["interrompida"], a["completou"])
        return {**cfg, **novo}, novo

    def test_sem_nada_guardado_comeca_em_12_h_e_valor_invalido_tambem(self):
        self.assertEqual(r.ciclo_guardado({}), 12)
        self.assertEqual((r.ciclo_guardado({"ciclo_horas": "lixo"}), r.ciclo_guardado({"ciclo_horas": "5"})), (12, 12))
        self.assertEqual(r.ciclo_guardado({"ciclo_horas": "3"}), 3)

    def test_saude_da_execucao(self):
        self.assertEqual(r.saude(3000, 0, 1), "limpa")
        self.assertEqual(r.saude(3000, 0, 4), "alerta")            # 1,3 por mil: mais que o limpo, menos que o aperto
        self.assertEqual(r.saude(3000, 0, 7), "ruim")              # 2,3 por mil: aperto
        self.assertEqual(r.saude(3000, 5, 1), "limpa")             # bloqueio não conta
        self.assertEqual(r.saude(500, 0, 0), "neutra")             # pouca evidência
        self.assertEqual(r.saude(1200, 0, 5), "ruim")              # com metade da evidência, o aperto já conta

    def test_rampa_desce_um_degrau_por_dia_limpo_ate_3_h(self):
        cfg, novo = self.aprende({}, 14)                           # 1ª execução: só guarda o ponto de partida
        self.assertEqual((cfg["ciclo_horas"], cfg["ciclo_desde"]), ("12", "2026-10-14"))
        cfg, novo = self.aprende(cfg, 14)                          # mesmo dia: segura
        self.assertNotIn("ciclo_horas", novo)
        cfg, novo = self.aprende(cfg, 15)                          # um dia inteiro limpo em 12 h: desce
        self.assertEqual((novo["ciclo_horas"], novo["ciclo_desde"]), ("6", "2026-10-15"))
        cfg, novo = self.aprende(cfg, 15)                          # no mesmo dia não desce de novo
        self.assertNotIn("ciclo_horas", novo)
        cfg, novo = self.aprende(cfg, 16)
        self.assertEqual(novo["ciclo_horas"], "3")
        cfg, novo = self.aprende(cfg, 17)                          # 3 h é o piso
        self.assertNotIn("ciclo_horas", novo)

    def test_so_desce_com_passada_completa_e_limpa(self):
        cfg = {"ciclo_horas": "12", "ciclo_desde": "2026-10-14"}
        self.assertNotIn("ciclo_horas", self.aprende(cfg, 15, completou=False)[1])
        self.assertNotIn("ciclo_horas", self.aprende(cfg, 15, leves=4)[1])           # neutra
        self.assertNotIn("ciclo_horas", self.aprende(cfg, 15, paginas=1500, leves=0)[1])   # pouca evidência

    def test_alerta_recomeca_o_dia_no_degrau_e_janela_estourada_sobe_o_ciclo(self):
        cfg = {"ciclo_horas": "6", "ciclo_desde": "2026-10-14"}
        _, novo = self.aprende(cfg, 15, leves=4)                           # manhã com sinal de alerta: não desce e recomeça o dia
        self.assertEqual(novo, {"ciclo_desde": "2026-10-15"})
        cfg2 = {**cfg, **novo}
        self.assertNotIn("ciclo_horas", self.aprende(cfg2, 15)[1])         # e a passada limpa da tarde não desce no mesmo dia
        self.assertEqual(self.aprende(cfg2, 16)[1]["ciclo_horas"], "3")    # no dia seguinte, limpo, desce
        # a sequência não deu conta da passada no tempo do ciclo: sobe um degrau, sem pausa, e segura a descida
        novo = r.aprender_ciclo(cfg, self.t(15), 3000, 0, 0, False, False, True)
        self.assertEqual((novo["ciclo_horas"], novo["ciclo_espera_ate"]), ("12", "2026-10-18"))
        self.assertNotIn("ritmo_pausa_ate", novo)

    def test_bloqueio_nao_pausa_nem_sobe_o_ciclo(self):
        cfg = {"ciclo_horas": "3", "ciclo_desde": "2026-10-10"}
        for _ in range(4):
            cfg, novo = self.aprende(cfg, 15, paginas=400, bloqueios=2, interrompida=True, completou=False)
            self.assertEqual(novo, {})
        self.assertIsNone(r.pausa_ate(cfg))
        self.assertEqual(cfg["ciclo_horas"], "3")

    def test_a_descida_espera_o_fim_da_espera_do_degrau(self):
        cfg = {"ciclo_horas": "24", "ciclo_desde": "2026-10-15", "ciclo_espera_ate": "2026-10-18"}
        self.assertEqual(self.aprende(cfg, 16)[1], {})
        self.assertEqual(self.aprende(cfg, 17)[1], {})
        self.assertEqual(self.aprende(cfg, 18)[1]["ciclo_horas"], "12")                  # acabou a espera: desce um degrau

    def test_aperto_sobe_o_ciclo_sem_pausa(self):
        cfg = {"ciclo_horas": "6", "ciclo_desde": "2026-10-10"}
        cfg2, novo = self.aprende(cfg, 15, leves=9)
        self.assertEqual(novo["ciclo_horas"], "12")
        self.assertNotIn("ritmo_pausa_ate", novo)

    def test_dia_limpo_soma_as_execucoes_mas_punicao_e_so_da_execucao(self):
        cfg = {"ciclo_horas": "24", "ciclo_desde": "2026-10-13", "ciclo_espera_ate": "2026-10-16"}
        curta = (cfg, self.t(16), 1300, 0, 0, False, True)
        self.assertEqual(r.aprender_ciclo(*curta), {})                                     # 1.300 páginas: neutra
        self.assertEqual(r.aprender_ciclo(*curta, evidencia=(3900, 1))["ciclo_horas"], "12")
        # uma execução ruim de manhã sobe o ciclo; a da tarde, normal, não sobe de novo nem desce no mesmo dia
        cfg = {"ciclo_horas": "6", "ciclo_desde": "2026-10-10"}
        cfg = {**cfg, **r.aprender_ciclo(cfg, self.t(15), 1500, 0, 5, False, False)}
        self.assertEqual(cfg["ciclo_horas"], "12")
        self.assertEqual(r.aprender_ciclo(cfg, self.t(15, 18), 1300, 0, 0, False, True, evidencia=(2800, 5)), {})

    def test_so_desce_para_um_ciclo_em_que_a_passada_cabe(self):
        cfg = {"ciclo_horas": "24", "ciclo_desde": "2026-10-15"}
        passada = r.horas_da_passada(4340, 8.0)                                            # ~10 h a 8 páginas/min
        self.assertAlmostEqual(passada, 10.05, places=2)
        self.assertEqual(r.aprender_ciclo(cfg, self.t(16), 3000, 0, 0, False, True, passada_h=passada)["ciclo_horas"], "12")
        cfg = {"ciclo_horas": "12", "ciclo_desde": "2026-10-15"}
        self.assertNotIn("ciclo_horas", r.aprender_ciclo(cfg, self.t(16), 3000, 0, 0, False, True, passada_h=passada))
        passada = r.horas_da_passada(4340, 15.6)
        self.assertNotIn("ciclo_horas", r.aprender_ciclo(cfg, self.t(16), 3000, 0, 0, False, True, passada_h=passada))
        passada = r.horas_da_passada(4340, 16.0)                                           # ~5 h: cabe em 6 h
        self.assertEqual(r.aprender_ciclo(cfg, self.t(16), 3000, 0, 0, False, True, passada_h=passada)["ciclo_horas"], "6")

    def test_ritmo_pausa_ate_invalido_ou_ausente(self):
        self.assertIsNone(r.pausa_ate({}))
        self.assertIsNone(r.pausa_ate({"ritmo_pausa_ate": "ontem"}))


if __name__ == "__main__":
    unittest.main()
