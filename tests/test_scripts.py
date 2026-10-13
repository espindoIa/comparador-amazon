"""Testes dos scripts de manutenção dos workflows (poda das cópias do banco e conferência do site)."""

import gzip
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "scripts"


def carregar(nome):
    spec = importlib.util.spec_from_file_location(nome, PASTA / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


podar_copias = carregar("podar_copias")
catalogo_release = carregar("catalogo_release")
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


if __name__ == "__main__":
    unittest.main()
