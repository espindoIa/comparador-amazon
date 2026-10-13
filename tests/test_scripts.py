"""Testes dos scripts de manutenção dos workflows (poda das cópias do banco e conferência do site)."""

import gzip
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "scripts"


def carregar(nome):
    spec = importlib.util.spec_from_file_location(nome, PASTA / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


podar_copias = carregar("podar_copias")
catalogo_release = carregar("catalogo_release")
verificar_precos = carregar("verificar_precos")
proximo_ciclo = carregar("proximo_ciclo")
espera = carregar("espera")
vigia = carregar("vigia")
conferir_site = carregar("conferir_site")


class TestPodarCopias(unittest.TestCase):
    def test_fica_com_as_recentes_e_a_ultima_de_cada_dia(self):
        nomes = [f"catalogo-vendidos-2026-10-{d:02d}-{h:02d}41.db.gz" for d in range(1, 13) for h in (3, 9, 15, 21)]
        nomes += ["catalogo-7842710011-2026-10-01-0341.db.gz", "catalogo-2026-09-30-1200.db.gz", "outro.txt"]
        apagar = podar_copias.podar(nomes, "vendidos", date(2026, 10, 12), recentes=6, dias=5)
        ficam = sorted(set(n for n in nomes if n.startswith("catalogo-vendidos")) - set(apagar))
        self.assertEqual(ficam, [
            "catalogo-vendidos-2026-10-07-2141.db.gz", "catalogo-vendidos-2026-10-08-2141.db.gz",   # última do dia
            "catalogo-vendidos-2026-10-09-2141.db.gz", "catalogo-vendidos-2026-10-10-2141.db.gz",
            "catalogo-vendidos-2026-10-11-1541.db.gz", "catalogo-vendidos-2026-10-11-2141.db.gz",   # 6 recentes
            "catalogo-vendidos-2026-10-12-0341.db.gz", "catalogo-vendidos-2026-10-12-0941.db.gz",
            "catalogo-vendidos-2026-10-12-1541.db.gz", "catalogo-vendidos-2026-10-12-2141.db.gz",
        ])
        self.assertIn("catalogo-2026-09-30-1200.db.gz", apagar)                 # teste antigo, sem categoria
        self.assertNotIn("catalogo-7842710011-2026-10-01-0341.db.gz", apagar)   # outra categoria: não mexe

    def test_cada_sequencia_poda_so_as_proprias_copias(self):
        # três sequências de coleta na mesma release: o passo de publicação de uma não pode apagar as da outra
        alvos = ("vendidos", "vendidos-b", "vendidos-c")
        nomes = [f"catalogo-{a}-2026-10-{d:02d}-{h:02d}41.db.gz" for a in alvos for d in range(1, 13) for h in (3, 9, 15, 21)]
        for alvo in alvos:
            apagar = podar_copias.podar(nomes, alvo, date(2026, 10, 12), recentes=6, dias=5)
            self.assertTrue(apagar, alvo)
            self.assertTrue(all(n.startswith(f"catalogo-{alvo}-2") for n in apagar), (alvo, apagar))

    def test_padrao_nunca_apaga_a_mais_recente(self):
        nomes = ["catalogo-vendidos-2020-01-01-0341.db.gz"]
        self.assertEqual(podar_copias.podar(nomes, "vendidos", date(2026, 10, 12)), [])


class TestConferirSite(unittest.TestCase):
    def test_recusa_site_que_encolheu_demais(self):
        self.assertIsNone(conferir_site.conferir({"itens": 80}, {"itens": 100}))
        self.assertIn("forcar", conferir_site.conferir({"itens": 60}, {"itens": 100}))
        self.assertIsNone(conferir_site.conferir({"itens": 60}, {"itens": 100}, minimo=0.5))

    def test_sem_site_no_ar_passa_mas_site_vazio_nunca(self):
        self.assertIsNone(conferir_site.conferir({"itens": 5}, None))
        self.assertIsNotNone(conferir_site.conferir({"itens": 0}, None))
        self.assertIsNotNone(conferir_site.conferir(None, {"itens": 100}))

    def test_le_meta_invalido_como_ausente(self):
        self.assertIsNone(conferir_site.ler("/nao/existe.json"))


def banco_gz(pasta: Path, nome: str, bom: bool = True, linhas: int = 3) -> Path:
    """Cria um catalogo-*.db.gz; com bom=False, o arquivo é cortado no meio (upload interrompido)."""
    db = pasta / "x.db"
    db.unlink(missing_ok=True)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE catalogo (asin TEXT)")
    c.executemany("INSERT INTO catalogo VALUES (?)", [(str(i),) for i in range(linhas)])
    c.commit()
    c.close()
    gz = pasta / nome
    gz.write_bytes(gzip.compress(db.read_bytes()))
    if not bom:
        gz.write_bytes(gz.read_bytes()[:-30])
    return gz


class GhFalso:
    """Release na memória: nome -> bytes. `falhas_download`/`envios_ruins` simulam problemas de rede."""

    def __init__(self, pasta: Path, ativos: dict | None = None, falhas_download: int = 0, envios_ruins: int = 0):
        self.pasta, self.ativos, self.criada = pasta, dict(ativos or {}), ativos is not None
        self.falhas_download, self.envios_ruins, self.baixados, self.apagados = falhas_download, envios_ruins, [], []

    def assets(self):
        return [{"name": n, "size": len(b), "state": "uploaded"} for n, b in self.ativos.items()] if self.criada else None

    def baixar(self, nome, pasta):
        self.baixados.append(nome)
        if self.falhas_download:
            self.falhas_download -= 1
            raise RuntimeError("timeout")
        (pasta / nome).write_bytes(self.ativos[nome])
        return pasta / nome

    def criar_release(self):
        self.criada = True

    def enviar(self, arquivo):
        dados = arquivo.read_bytes()
        if self.envios_ruins:
            self.envios_ruins -= 1
            dados = dados[:-5]                          # chegou cortado
        self.ativos[arquivo.name] = dados

    def apagar(self, nome):
        self.apagados.append(nome)
        self.ativos.pop(nome, None)


class TestCatalogoRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.log = []

    def baixar(self, gh):
        return catalogo_release.baixar("vendidos", self.d / "saida.db", gh, dormir=lambda s: None, log=self.log.append)

    def test_cai_para_a_copia_anterior_quando_a_mais_nova_esta_cortada(self):
        gh = GhFalso(self.d, {"catalogo-vendidos-2026-10-13-0300.db.gz": banco_gz(self.d, "a.gz", linhas=2).read_bytes(),
                              "catalogo-vendidos-2026-10-13-0900.db.gz": banco_gz(self.d, "b.gz", bom=False).read_bytes()})
        self.assertEqual(self.baixar(gh), 0)
        self.assertEqual(gh.baixados, ["catalogo-vendidos-2026-10-13-0900.db.gz", "catalogo-vendidos-2026-10-13-0300.db.gz"])
        c = sqlite3.connect(self.d / "saida.db")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0], 2)    # a de 03:00, a boa
        c.close()

    def test_tenta_de_novo_o_download_e_nao_recomeca_do_zero_se_nada_serve(self):
        bom = banco_gz(self.d, "a.gz").read_bytes()
        gh = GhFalso(self.d, {"catalogo-vendidos-2026-10-13-0300.db.gz": bom}, falhas_download=2)
        self.assertEqual(self.baixar(gh), 0)                                              # 3ª tentativa passa
        ruim = GhFalso(self.d, {"catalogo-vendidos-2026-10-13-0300.db.gz": b"lixo"})
        self.assertEqual(self.baixar(ruim), 1)                                            # existe, mas não serve: falha
        self.assertFalse((self.d / "saida.db").exists())

    def test_sem_release_ou_sem_copia_do_alvo_comeca_do_zero(self):
        self.assertEqual(self.baixar(GhFalso(self.d)), 0)
        self.assertEqual(self.baixar(GhFalso(self.d, {"catalogo-7842710011-2026-10-13-0300.db.gz": b"x"})), 0)
        self.assertFalse((self.d / "saida.db").exists())

    def test_cada_sequencia_baixa_so_a_propria_copia(self):
        bom = banco_gz(self.d, "a.gz").read_bytes()
        gh = GhFalso(self.d, {"catalogo-vendidos-b-2026-10-13-0900.db.gz": bom, "catalogo-vendidos-c-2026-10-13-0900.db.gz": bom})
        self.assertEqual(self.baixar(gh), 0)                                              # "vendidos" não tem cópia: do zero
        self.assertEqual((gh.baixados, (self.d / "saida.db").exists()), ([], False))
        self.assertEqual(catalogo_release.baixar("vendidos-b", self.d / "b.db", gh, dormir=lambda s: None, log=self.log.append), 0)
        self.assertEqual(gh.baixados, ["catalogo-vendidos-b-2026-10-13-0900.db.gz"])
        self.assertTrue((self.d / "b.db").exists())

    def test_publicar_confere_o_tamanho_e_repete_o_envio_cortado(self):
        banco = banco_gz(self.d, "a.gz").parent / "x.db"
        gh = GhFalso(self.d, {}, envios_ruins=1)
        r = catalogo_release.publicar("vendidos", banco, gh, dormir=lambda s: None, log=self.log.append)
        self.assertEqual(r, 0)
        self.assertEqual(len(gh.apagados), 1)                                             # o cortado foi apagado
        (nome,) = gh.ativos
        self.assertRegex(nome, r"^catalogo-vendidos-\d{4}-\d{2}-\d{2}-\d{4}\.db\.gz$")
        self.assertIsNone(catalogo_release.descompactar_e_conferir(self.d / "a.gz", self.d / "y.db"))

    def test_publicar_falha_sem_deixar_arquivo_cortado(self):
        banco = banco_gz(self.d, "a.gz").parent / "x.db"
        gh = GhFalso(self.d, {}, envios_ruins=9)
        self.assertEqual(catalogo_release.publicar("vendidos", banco, gh, dormir=lambda s: None, log=self.log.append), 1)
        self.assertEqual(gh.ativos, {})


class TestVerificarPrecos(unittest.TestCase):
    def banco(self, nome, precos, formato="Capa comum"):
        caminho = Path(self.tmp.name) / nome
        caminho.unlink(missing_ok=True)
        c = sqlite3.connect(caminho)
        c.executescript("CREATE TABLE catalogo (asin TEXT PRIMARY KEY, formato TEXT);"
                        "CREATE TABLE historico (id INTEGER PRIMARY KEY, asin TEXT, preco_centavos INTEGER);")
        for i, p in enumerate(precos):
            c.execute("INSERT INTO catalogo VALUES (?, ?)", (f"A{i:09d}", formato if i % 5 else "Kindle"))
            c.execute("INSERT INTO historico (asin, preco_centavos) VALUES (?, ?)", (f"A{i:09d}", p))
        c.commit()
        c.close()
        return caminho

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.antes = [3000 + i for i in range(3000)]

    def veredito(self, depois):
        return verificar_precos.problema(verificar_precos.medir(self.banco("n.db", depois), self.banco("a.db", self.antes)))

    def test_dia_normal_passa(self):
        depois = [p + 100 if i % 8 == 0 else p for i, p in enumerate(self.antes)]      # 12% mudaram
        self.assertIsNone(self.veredito(depois))
        self.assertIsNone(self.veredito(self.antes))

    def test_erro_de_leitura_de_preco_recusa(self):
        self.assertIn("mudaram de uma vez", self.veredito([p * 100 for p in self.antes]))      # reais lidos como centavos
        self.assertIn("fora de R$", self.veredito([max(1, p // 100) for p in self.antes]))     # o contrário
        self.assertIn("mudaram de uma vez", self.veredito([p * 2 for p in self.antes]))        # preço de capa no lugar do preço
        extremos = [p * 10 if i % 31 == 1 else p for i, p in enumerate(self.antes)]            # ~3% em mais de 5x
        self.assertIn("5x", self.veredito(extremos))

    def test_so_livros_fisicos_contam(self):
        # o Kindle (1 em cada 5) pode mudar tudo: ofertas do dia
        depois = [p * 3 if i % 5 == 0 else p for i, p in enumerate(self.antes)]
        self.assertIsNone(self.veredito(depois))

    def test_poucos_livros_comparaveis_nao_bastam_para_recusar_mas_faixa_sim(self):
        pequeno = verificar_precos.medir(self.banco("p.db", [p * 100 for p in self.antes[:200]]),
                                         self.banco("q.db", self.antes[:200]))
        self.assertIsNone(verificar_precos.problema({**pequeno, "fora_da_faixa": 0.0}))   # 200 < 1000
        self.assertIn("fora de", verificar_precos.problema({**pequeno, "fora_da_faixa": 0.5}))


class TestProximoCiclo(unittest.TestCase):
    """Janelas de 12 h de Brasília: 00:00–12:00 e 12:00–24:00 (03:00–15:00 e 15:00–03:00 em UTC)."""

    def setUp(self):
        from comparador import db, varredura
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.varredura = varredura
        self.conn = db.conectar(":memory:")
        self.addCleanup(self.conn.close)
        varredura.criar_schema(self.conn)
        varredura.semear_vendidos(self.conn, ["1"], [(0, 3999), (4000, varredura.SEM_TETO)])
        self.inicio = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)      # a execução começou às 07:00 de Brasília
        self.agora = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)       # e acaba às 10:00 de Brasília

    def decidir(self, alvo="vendidos", agora=None, inicio=None):
        return proximo_ciclo.decidir(self.conn, alvo, inicio or self.inicio, agora or self.agora, sorteio=lambda a, b: 0)

    def execucao(self, paginas=3000, bloqueios=0, obs=None, quando=None):
        self.conn.execute("INSERT INTO execucoes (iniciada_em, paginas, bloqueios, observacao) VALUES (?, ?, ?, ?)",
                          (quando or "2026-10-14T10:00:00+00:00", paginas, bloqueios, obs))

    def completar_a_janela(self, inicio="2026-10-14T05:00:00+00:00", fim="2026-10-14T06:00:00+00:00"):
        self.conn.execute("UPDATE fatias SET ultima_passada = ?, passada_iniciada_em = ?", (fim, inicio))

    def config(self, **kw):
        for k, v in kw.items():
            self.conn.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)", (k, v))

    def test_continua_agora_se_a_janela_nao_fechou_e_a_execucao_foi_limpa(self):
        self.execucao()
        quando, motivo = self.decidir()
        self.assertEqual(quando, self.agora)
        self.assertIn("não fechou", motivo)

    def test_com_a_janela_completa_espera_a_proxima_com_a_defasagem_de_cada_sequencia(self):
        self.execucao()
        self.completar_a_janela()
        fim = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)                 # 12:00 de Brasília
        for alvo, minutos in (("vendidos", 0), ("vendidos-b", 10), ("vendidos-c", 20)):
            self.assertEqual(self.decidir(alvo)[0], fim + timedelta(minutes=minutos), alvo)

    def test_o_sorteio_so_atrasa_a_leitura_da_janela_nunca_antecipa(self):
        self.execucao()
        self.completar_a_janela()
        quando, _ = proximo_ciclo.decidir(self.conn, "vendidos", self.inicio, self.agora, sorteio=lambda a, b: b)
        self.assertEqual(quando, datetime(2026, 10, 14, 15, 10, tzinfo=timezone.utc))

    def test_depois_de_bloqueio_aviso_de_layout_ou_execucao_curta_espera_a_proxima_janela(self):
        proxima = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
        for kw in (dict(bloqueios=1), dict(obs="interrompida após 3 falhas seguidas"),
                   dict(obs=f"poucos itens com capa: {self.varredura.AVISO_LAYOUT}"), dict(paginas=120)):
            self.conn.execute("DELETE FROM execucoes")
            self.execucao(**kw)
            self.assertEqual(self.decidir()[0], proxima, kw)

    def test_a_pausa_depois_de_bloqueio_vale_mesmo_depois_da_proxima_janela(self):
        self.execucao(bloqueios=2)
        self.config(ritmo_pausa_ate="2026-10-14T21:00:00+00:00")
        quando, motivo = self.decidir()
        self.assertEqual(quando, datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc))
        self.assertIn("pausa", motivo)
        self.config(ritmo_pausa_ate="2026-10-14T14:00:00+00:00")             # pausa que acaba antes da janela: a janela manda
        self.assertEqual(self.decidir()[0], datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc))

    def test_nunca_menos_de_10_minutos_depois_do_comeco_da_execucao(self):
        self.execucao(quando="2026-10-14T14:55:00+00:00")
        self.completar_a_janela()
        quando, _ = self.decidir(agora=datetime(2026, 10, 14, 14, 56, tzinfo=timezone.utc),
                                 inicio=datetime(2026, 10, 14, 14, 55, tzinfo=timezone.utc))
        self.assertEqual(quando, datetime(2026, 10, 14, 15, 5, tzinfo=timezone.utc))      # a janela seria às 15:00

    def test_sobrando_pouco_tempo_na_janela_nao_continua_ja(self):
        self.execucao()
        quando, _ = self.decidir(agora=datetime(2026, 10, 14, 14, 50, tzinfo=timezone.utc))
        self.assertEqual(quando, datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc))

    def test_so_conta_a_execucao_desta_rodada(self):
        self.execucao(quando="2026-10-14T05:00:00+00:00")                       # uma execução antiga e limpa não vale
        self.assertEqual(self.decidir()[0], datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc))

    def test_publicacao_que_falhou_espera_horas_em_vez_de_ler_de_novo_logo(self):
        self.execucao()                                                       # janela incompleta, execução limpa: continuaria já
        quando, motivo = proximo_ciclo.decidir(self.conn, "vendidos", self.inicio, self.agora, sorteio=lambda a, b: 0,
                                               publicacao_falhou=True)
        self.assertEqual(quando, self.agora + timedelta(hours=3))
        self.assertIn("publicação falhou", motivo)
        self.completar_a_janela()                                             # janela completa: a próxima janela já é mais tarde
        quando, _ = proximo_ciclo.decidir(self.conn, "vendidos", self.inicio, self.agora, sorteio=lambda a, b: 0,
                                          publicacao_falhou=True)
        self.assertEqual(quando, datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc))

    def test_o_ciclo_guardado_define_a_janela(self):
        self.config(ciclo_horas="3")
        self.execucao()
        self.completar_a_janela("2026-10-14T15:30:00+00:00", "2026-10-14T15:55:00+00:00")
        agora = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)            # 13:00 de Brasília: janela das 12:00 às 15:00
        self.assertEqual(self.decidir(agora=agora)[0], datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc))
        self.config(ciclo_horas="24")                                         # janela do dia inteiro: a de 12 h acima não vale
        self.completar_a_janela("2026-10-14T05:00:00+00:00", "2026-10-14T15:55:00+00:00")
        self.assertEqual(self.decidir(agora=agora)[0], datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc))

    def test_linha_de_comando_com_um_banco_de_verdade(self):
        import subprocess
        import sys
        arquivo = Path(self.tmp.name) / "c.db"
        disco = sqlite3.connect(arquivo)
        self.conn.backup(disco)
        disco.close()
        r = subprocess.run([sys.executable, str(PASTA / "proximo_ciclo.py"), str(arquivo), "--alvo", "vendidos-b",
                            "--inicio-run", "2000-01-01T00:00:00+00:00"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        quando, motivo = r.stdout.splitlines()
        self.assertTrue(datetime.fromisoformat(quando) > datetime.now(timezone.utc))
        self.assertIn("ciclo", motivo)


class TestEspera(unittest.TestCase):
    def test_dorme_ate_a_hora_e_dispara(self):
        agora = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(espera.plano(agora + timedelta(minutes=90), agora), ("disparar", 5400))
        self.assertEqual(espera.plano(agora - timedelta(minutes=5), agora), ("disparar", 0))      # já passou da hora

    def test_espera_longa_vira_saltos_que_se_reencadeiam(self):
        agora = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
        quando = agora + timedelta(hours=24)
        passos = 0
        while True:
            acao, dorme = espera.plano(quando, agora)
            self.assertLessEqual(dorme, espera.SALTO_MAX_S)
            self.assertLess(dorme, 6 * 3600)                                 # cabe num job do GitHub
            agora += timedelta(seconds=dorme + 30)                           # + o tempo de disparar a espera seguinte
            passos += 1
            if acao == "disparar":
                break
        self.assertGreaterEqual(passos, 5)
        self.assertLessEqual(passos, 6)
        self.assertGreaterEqual(agora, quando)


class TestVigia(unittest.TestCase):
    AGORA = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    ALVOS = ["vendidos", "vendidos-b", "vendidos-c"]

    def run_(self, titulo, status="in_progress", minutos=300):
        criada = (self.AGORA - timedelta(minutes=minutos)).isoformat().replace("+00:00", "Z")
        return {"displayTitle": titulo, "status": status, "createdAt": criada}

    def test_sequencia_com_execucao_em_andamento_ou_esperando_nao_e_reiniciada(self):
        execs = [self.run_("varredura vendidos"), self.run_("espera vendidos-b até 2026-10-14T13:00:00+00:00", "queued"),
                 self.run_("varredura vendidos-c", "completed", minutos=5)]
        self.assertEqual(vigia.sem_anel(self.ALVOS, execs, self.AGORA), [])

    def test_sequencia_sem_nada_em_andamento_e_reiniciada_sem_confundir_nomes_parecidos(self):
        execs = [self.run_("varredura vendidos-b"), self.run_("varredura vendidos-c", "completed", minutos=300)]
        self.assertEqual(vigia.sem_anel(self.ALVOS, execs, self.AGORA), ["vendidos", "vendidos-c"])

    def test_execucao_das_tres_cobre_todas_e_execucao_recem_criada_ainda_vale(self):
        self.assertEqual(vigia.sem_anel(self.ALVOS, [self.run_("varredura todas")], self.AGORA), [])
        self.assertEqual(vigia.sem_anel(self.ALVOS, [self.run_("varredura todas", "completed")], self.AGORA), self.ALVOS)
        self.assertEqual(vigia.sem_anel(["vendidos"], [self.run_("varredura vendidos", "completed", minutos=10)], self.AGORA), [])

    def test_linha_de_comando(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "r.json"
            arq.write_text(json.dumps([{"displayTitle": "varredura vendidos", "status": "in_progress",
                                        "createdAt": "2026-10-14T06:00:00Z"}]), encoding="utf-8")
            r = subprocess.run([sys.executable, str(PASTA / "vigia.py"), str(arq), "--alvos", *self.ALVOS],
                               capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.split()), (0, ["vendidos-b", "vendidos-c"]), r.stderr)


if __name__ == "__main__":
    unittest.main()
