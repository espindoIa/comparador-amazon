"""Testes do ciclo de leitura (uma passada completa a cada 3, 6, 12 ou 24 h) e do anel de execuções.

A simulação no fim roda vários dias de execuções com relógio falso (o tempo só anda quando a coleta dorme), o mesmo
`varredura.executar` que a linha de comando usa e o mesmo `scripts/proximo_ciclo.py` que o workflow usa para marcar a próxima
leitura, e confere as propriedades que importam: o volume sobe em rampa, nenhuma fatia fica mais de 2 ciclos sem leitura,
nunca há duas leituras coladas, e depois de um bloqueio a coleta espera horas e alarga o ciclo.
"""

import importlib.util
import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from comparador import db, ritmo, varredura

try:
    from .test_varredura import CACHORROS, FAIXAS_TESTE, AmazonRealista
except ImportError:                          # rodando com `discover -s tests`, os módulos são de nível raiz
    from test_varredura import CACHORROS, FAIXAS_TESTE, AmazonRealista

_spec = importlib.util.spec_from_file_location("proximo_ciclo", Path(__file__).resolve().parent.parent / "scripts" / "proximo_ciclo.py")
proximo_ciclo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proximo_ciclo)

UTC = timezone.utc


def brasilia(dia, hora=0, minuto=0, mes=10):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=db.BRASILIA).astimezone(UTC)


class Mundo:
    """Relógio falso: o tempo só anda quando alguém dorme ou quando o teste o avança."""

    def __init__(self, inicio: datetime, escala: float = 1.0):
        self.t = inicio
        self.escala = escala        # > 1: câmera lenta (rede lenta, ritmo baixo): cada segundo de espera vale `escala`

    def agora(self) -> str:
        return self.t.isoformat(timespec="seconds")

    def hoje_brasil(self):
        return self.t.astimezone(db.BRASILIA).date()

    def dormir(self, s: float) -> None:
        self.t += timedelta(seconds=s * self.escala)

    def relogio(self) -> float:
        return self.t.timestamp()

    def instalar(self, teste: unittest.TestCase) -> None:
        for nome, funcao in (("agora", self.agora), ("hoje_brasil", self.hoje_brasil)):
            p = mock.patch.object(db, nome, funcao)
            p.start()
            teste.addCleanup(p.stop)


class TestInicioDoCiclo(unittest.TestCase):
    def test_janelas_partem_da_meia_noite_de_brasilia(self):
        # (hora, minuto) -> início esperado da janela, em horas de Brasília
        casos = {3: [(0, 0, 0), (2, 59, 0), (3, 0, 3), (8, 30, 6), (23, 30, 21)],
                 6: [(0, 0, 0), (5, 59, 0), (6, 0, 6), (17, 30, 12), (23, 30, 18)],
                 12: [(0, 0, 0), (11, 59, 0), (12, 0, 12), (23, 30, 12)],
                 24: [(0, 0, 0), (23, 30, 0)]}
        for horas, trios in casos.items():
            for hora, minuto, inicio in trios:
                self.assertEqual(varredura.inicio_do_ciclo(horas, brasilia(14, hora, minuto)),
                                 brasilia(14, inicio).isoformat(timespec="seconds"), (horas, hora, minuto))

    def test_ciclo_de_24_h_e_o_dia(self):
        agora = brasilia(14, 17, 5)
        self.assertEqual(varredura.inicio_do_ciclo(24, agora),
                         datetime.fromisoformat(varredura.inicio_do_dia(agora.astimezone(db.BRASILIA).date())).isoformat(timespec="seconds"))

    def test_o_limite_exato_pertence_a_janela_nova(self):
        self.assertEqual(varredura.inicio_do_ciclo(3, brasilia(14, 3, 0)), brasilia(14, 3).isoformat(timespec="seconds"))
        self.assertEqual(varredura.inicio_do_ciclo(3, brasilia(14, 2, 59) + timedelta(seconds=59)), brasilia(14, 0).isoformat(timespec="seconds"))


class Base(unittest.TestCase):
    """Dois gêneros pequenos, três faixas: ~12 páginas por passada."""

    def setUp(self):
        random.seed(int(os.environ.get("SEMENTE_SIMULACAO", 20261014)))                # o ritmo sorteia os intervalos entre as requisições; a simulação tem de repetir
        self.mundo = Mundo(brasilia(14, 0, 5))
        self.mundo.instalar(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.conectar(Path(self.tmp.name) / "c.db")
        self.addCleanup(self.conn.close)
        varredura.criar_schema(self.conn)
        # o catálogo de teste é ~200 vezes menor que o de verdade: as exigências de "evidência" encolhem junto
        for alvo, nome, valor in ((varredura, "FAIXAS_VENDIDOS", FAIXAS_TESTE), (ritmo, "PAGINAS_MIN_EVIDENCIA", 10),
                                  (proximo_ciclo, "MIN_PAGINAS", 5)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        livros = {"1": [(f"G1{i:08d}", 500 + i * 100) for i in range(70)],
                  "2": [(f"G2{i:08d}", 600 + i * 100) for i in range(70)]}
        self.amazon = AmazonRealista(livros)

    def executar(self, **kw):
        kw.setdefault("minutos", 165)
        return varredura.executar(self.conn, self.amazon, vendidos=["1", "2"], teto_auto_max=45.0,
                                  dormir=self.mundo.dormir, relogio=self.mundo.relogio, log=lambda *a: None, **kw)

    def config(self):
        return varredura.ler_config(self.conn)


class TestJanelasDeLeitura(Base):
    def test_uma_passada_por_janela_e_o_dia_fecha_na_primeira(self):
        r = self.executar(ciclo_horas=3)
        self.assertTrue(r.completou)
        self.assertIsNotNone(r.exec_id)
        self.assertEqual({x[0] for x in self.conn.execute("SELECT dia FROM dias")}, {"2026-10-14"})   # o dia fecha com 1 passada
        paginas = self.conn.execute("SELECT paginas FROM execucoes").fetchone()[0]
        self.assertGreater(paginas, 5)
        self.assertIsNone(self.executar(ciclo_horas=3).exec_id)                                       # mesma janela: nada a fazer
        self.mundo.t = brasilia(14, 3, 10)                                                            # janela seguinte
        r = self.executar(ciclo_horas=3)
        self.assertIsNotNone(r.exec_id)
        self.assertEqual(self.conn.execute("SELECT paginas FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()[0], paginas)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dias").fetchone()[0], 1)             # o dia só fecha uma vez

    def test_ciclo_de_12_h_nao_le_de_novo_na_mesma_metade_do_dia(self):
        self.executar(ciclo_horas=12)
        self.mundo.t = brasilia(14, 9)
        self.assertIsNone(self.executar(ciclo_horas=12).exec_id)
        self.mundo.t = brasilia(14, 12, 5)
        self.assertIsNotNone(self.executar(ciclo_horas=12).exec_id)

    def test_atravessar_o_fim_do_ciclo_recomeca_as_passadas_em_andamento(self):
        self.mundo.t = brasilia(14, 2, 59) + timedelta(seconds=50)       # a janela das 03:00 chega no meio da leitura
        r = self.executar(ciclo_horas=3, minutos=20)
        obs = self.conn.execute("SELECT observacao FROM execucoes WHERE id = ?", (r.exec_id,)).fetchone()[0]
        self.assertIn("atravessou o fim do ciclo", obs)
        desde = varredura.inicio_do_ciclo(3)
        self.assertTrue(r.completou)
        self.assertTrue(all(f[0] >= desde and f[1] >= desde for f in
                            self.conn.execute("SELECT passada_iniciada_em, ultima_passada FROM fatias WHERE ativa = 1")))

    def test_o_dia_so_fecha_quando_todas_as_fatias_tiveram_passada_inteira_dentro_dele(self):
        self.mundo.t = brasilia(14, 23, 59) + timedelta(seconds=40)      # a meia-noite chega no meio da passada
        self.executar(ciclo_horas=3, minutos=30)
        self.assertEqual({x[0] for x in self.conn.execute("SELECT dia FROM dias")}, {"2026-10-15"})   # o dia 14 não fechou


class TestFrescor(Base):
    def test_cobertura_conta_fatias_atrasadas_pelo_ciclo(self):
        self.executar(ciclo_horas=12)
        self.conn.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES ('ciclo_horas', '12')")
        self.conn.commit()
        c = varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS)
        self.assertEqual((c.ciclo_horas, c.atrasadas, c.nunca_lidas), (12, 0, 0))
        self.assertLess(c.mais_antiga_h, 1)
        self.mundo.t += timedelta(hours=2 * 12 + 1)                      # 25 h depois: ainda dentro de 2 ciclos + 2 h
        self.assertEqual(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).atrasadas, 0)
        self.mundo.t += timedelta(hours=2)                               # 27 h
        c = varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS)
        self.assertEqual(c.atrasadas, c.fatias)
        self.assertEqual(varredura.limite_atraso(3), 8)

    def test_fatia_que_nunca_foi_lida_nao_e_atrasada_mas_aparece(self):
        varredura.criar_schema(self.conn)
        varredura.semear_vendidos(self.conn, ["1"])
        c = varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS)
        self.assertEqual((c.atrasadas, c.nunca_lidas, c.mais_antiga_h), (0, c.fatias, None))


class TestExecutar(Base):
    def test_primeira_execucao_guarda_o_ponto_de_partida_e_o_teto_respeita_o_limite(self):
        self.conn.execute("INSERT INTO config (chave, valor) VALUES ('ritmo_teto', '75')")
        self.conn.commit()
        r = self.executar()
        self.assertEqual((r.ciclo_horas, r.teto), (12, 45.0))                  # sem nada guardado: 12 h; teto limitado a 45
        self.assertEqual((self.config()["ciclo_horas"], self.config()["ciclo_desde"]), ("12", "2026-10-14"))

    def test_ciclo_fixo_na_linha_de_comando_nao_guarda_nada(self):
        self.executar(ciclo_horas=3)
        self.assertNotIn("ciclo_horas", self.config())

    def test_bloqueio_pausa_por_horas_alarga_o_ciclo_e_a_execucao_seguinte_nem_comeca(self):
        self.conn.execute("INSERT INTO config (chave, valor) VALUES ('ciclo_horas', '3'), ('ciclo_desde', '2026-10-10')")
        self.conn.commit()
        self.amazon.falhas = [CACHORROS] * 40
        r = self.executar()
        e = self.conn.execute("SELECT bloqueios, paginas FROM execucoes WHERE id = ?", (r.exec_id,)).fetchone()
        self.assertGreaterEqual(e["bloqueios"], 1)
        self.assertEqual(self.config()["ciclo_horas"], "6")
        pausa = ritmo.pausa_ate(self.config())
        self.assertGreaterEqual(pausa - self.mundo.t, timedelta(hours=2, minutes=50))     # horas, não minutos
        chamadas = len(self.amazon.chamadas)
        self.mundo.t += timedelta(hours=2)
        r2 = self.executar()
        self.assertEqual((r2.exec_id, r2.pausa_ate), (None, pausa))
        self.assertEqual(len(self.amazon.chamadas), chamadas)                              # não pediu nada à Amazon
        self.mundo.t = pausa + timedelta(minutes=1)
        self.assertIsNotNone(self.executar().exec_id)                                      # passada a pausa, volta a ler

    def test_ignorar_a_pausa_so_por_pedido_explicito(self):
        self.conn.execute("INSERT INTO config (chave, valor) VALUES ('ritmo_pausa_ate', ?)",
                          ((self.mundo.t + timedelta(hours=3)).isoformat(),))
        self.conn.commit()
        self.assertIsNone(self.executar().exec_id)
        self.assertIsNotNone(self.executar(ignorar_pausa=True).exec_id)


class Anel:
    """O anel de execuções de uma sequência, como em varredura.yml: executa, marca a próxima hora e espera por ela."""

    def __init__(self, teste: Base, alvo="vendidos", fila=lambda: 0, minutos=165):
        self.t, self.alvo, self.fila, self.minutos = teste, alvo, fila, minutos
        self.quando = teste.mundo.t
        self.execucoes: list[dict] = []

    def passo(self):
        m = self.t.mundo
        m.t = max(m.t, self.quando) + timedelta(minutes=self.fila())          # o GitHub põe a execução na fila
        inicio = m.t
        r = self.t.executar(minutos=self.minutos)
        fim = m.t
        self.quando, motivo = proximo_ciclo.decidir(self.t.conn, self.alvo, inicio, m.t, sorteio=lambda a, b: 0)
        e = self.t.conn.execute("SELECT paginas, bloqueios FROM execucoes WHERE id = ?", (r.exec_id,)).fetchone() if r.exec_id else None
        self.execucoes.append({"inicio": inicio, "fim": fim, "res": r, "proxima": self.quando, "motivo": motivo,
                               "paginas": e["paginas"] if e else 0, "bloqueios": e["bloqueios"] if e else 0})
        return self.execucoes[-1]

    def ate(self, limite: datetime):
        while self.quando < limite:
            self.passo()
        return self.execucoes


class TestAnel(Base):
    def paginas_por_dia(self, anel):
        por_dia = {}
        for x in anel.execucoes:
            d = x["inicio"].astimezone(db.BRASILIA).date()
            por_dia[d] = por_dia.get(d, 0) + x["paginas"]
        return por_dia

    def test_rampa_sem_falhas_12_6_3_h_com_volume_dobrando_por_dia(self):
        anel = Anel(self)
        atrasadas = []
        fim = brasilia(18, 0)
        while anel.quando < fim:
            x = anel.passo()
            atrasadas.append(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).atrasadas)
        self.assertEqual(sum(atrasadas), 0)                                       # nunca passou de 2 ciclos + 2 h
        passada = self.paginas_por_dia(anel)[brasilia(14).date()] / 2             # 2 passadas no dia 14 (12 h)
        por_dia = self.paginas_por_dia(anel)
        dias = sorted(por_dia)
        n = [round(por_dia[d] / passada) for d in dias[:4]]
        self.assertEqual(n, [2, 4, 8, 8])                                         # 12 h → 6 h → 3 h, e fica em 3 h
        self.assertEqual(self.config()["ciclo_horas"], "3")
        for a, b in zip(anel.execucoes, anel.execucoes[1:]):
            self.assertGreaterEqual(b["inicio"] - a["inicio"], timedelta(minutes=proximo_ciclo.ENTRE_EXECUCOES_MIN))

    def test_atrasos_da_fila_do_github_nao_deixam_fatia_velha(self):
        atrasos = iter([5, 60, 0, 130, 20, 90, 0, 45] * 40)
        anel = Anel(self, fila=lambda: next(atrasos))
        fim = brasilia(18, 0)
        while anel.quando < fim:
            anel.passo()
            self.assertEqual(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).atrasadas, 0)
        self.assertGreater(len(anel.execucoes), 10)

    def test_orcamento_curto_continua_logo_sem_laco_apertado(self):
        self.conn.execute("INSERT INTO config (chave, valor) VALUES ('ciclo_horas', '12'), ('ciclo_desde', '2026-10-14')")
        self.conn.commit()
        anel = Anel(self, minutos=0.4)                                            # cada execução só dá conta de ~9 páginas
        anel.ate(brasilia(14, 11))
        continuadas = [x for x in anel.execucoes if "continua" in x["motivo"]]
        self.assertGreaterEqual(len(continuadas), 1)
        self.assertTrue(anel.execucoes[-1]["res"].completou)                      # a janela fechou, em mais de uma execução
        self.assertTrue(all(x["paginas"] >= proximo_ciclo.MIN_PAGINAS for x in continuadas))
        self.assertLess(len(anel.execucoes), 6)                                   # e sem laço de execuções vazias
        self.assertNotIn("continua", anel.execucoes[-1]["motivo"])                # fechada a janela, espera a próxima

    def test_passada_mais_lenta_que_a_janela_chega_a_todas_as_faixas_e_o_ciclo_sobe(self):
        self.mundo.escala = 450            # a passada leva ~5 h, mais que a janela de 3 h
        self.conn.execute("INSERT INTO config (chave, valor) VALUES ('ciclo_horas', '3'), ('ciclo_desde', '2026-10-10')")
        self.conn.commit()
        anel = Anel(self)
        fim = brasilia(17, 0)
        while anel.quando < fim:
            anel.passo()
            c = varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS)
            if anel.execucoes[-1]["inicio"] >= brasilia(15, 0):
                self.assertEqual((c.nunca_lidas, c.atrasadas), (0, 0), anel.execucoes[-1]["inicio"])
        estouros = [x for x in anel.execucoes if x["res"].ciclo_horas == 3 and x["res"].config_ciclo.get("ciclo_horas") == "6"]
        self.assertTrue(estouros)                                        # a janela estourou e o ciclo subiu
        self.assertGreaterEqual(int(self.config()["ciclo_horas"]), 6)
        # depois de subir, as janelas fecham (em mais de uma execução, mas fecham) e o ciclo não sobe sem parar
        self.assertGreaterEqual(sum(x["res"].completou for x in anel.execucoes[-8:]), 3)
        self.assertLessEqual(int(self.config()["ciclo_horas"]), 12)

    def test_bloqueios_alargam_o_ciclo_com_pausas_que_dobram_e_a_rampa_volta_depois(self):
        anel = Anel(self)
        anel.ate(brasilia(17, 0))
        self.assertEqual(self.config()["ciclo_horas"], "3")
        # a Amazon passa a bloquear
        self.amazon.falhas = [CACHORROS] * 400
        inicio_bloqueio = len(anel.execucoes)
        anel.ate(brasilia(18, 12))
        bloqueadas = [x for x in anel.execucoes[inicio_bloqueio:] if x["bloqueios"]]
        self.assertGreaterEqual(len(bloqueadas), 3)
        pausas = [x["proxima"] - x["fim"] for x in bloqueadas]
        self.assertTrue(all(p >= timedelta(hours=2, minutes=50) for p in pausas), pausas)          # sempre horas
        self.assertGreater(pausas[2], pausas[0])                                                    # e crescendo
        self.assertEqual(self.config()["ciclo_horas"], "24")                                         # bloqueios seguidos: diário
        # durante a pausa não houve leitura: o início de cada execução é depois do fim da pausa anterior
        for a, b in zip(anel.execucoes[inicio_bloqueio:], anel.execucoes[inicio_bloqueio + 1:]):
            self.assertGreaterEqual(b["inicio"], a["proxima"])
        # a Amazon volta ao normal: a rampa recomeça de 24 h e desce um degrau por dia, depois dos 3 dias de espera
        self.amazon.falhas = []
        ciclos = []
        for d in (21, 24, 25, 26, 27):
            anel.ate(brasilia(d, 0))
            ciclos.append(self.config()["ciclo_horas"])
        self.assertEqual(ciclos[0], "24")                                                           # ainda na espera
        self.assertEqual(self.config()["ciclo_horas"], "3")
        self.assertEqual(ciclos, sorted(ciclos, key=int, reverse=True))                             # só desceu

    def test_pausa_nao_e_pulada_nem_pelo_vigia_reiniciando_a_sequencia(self):
        anel = Anel(self)
        self.amazon.falhas = [CACHORROS] * 400
        x = anel.passo()
        self.assertTrue(x["bloqueios"])
        pausa = ritmo.pausa_ate(self.config())
        chamadas = len(self.amazon.chamadas)
        for horas in (0.5, 1, 2, 2.9):                    # o vigia reinicia a sequência várias vezes durante a pausa
            self.mundo.t = x["fim"] + timedelta(hours=horas)
            self.assertIsNone(self.executar().exec_id)
        self.assertEqual(len(self.amazon.chamadas), chamadas)
        self.assertGreater(pausa, self.mundo.t)


if __name__ == "__main__":
    unittest.main()
