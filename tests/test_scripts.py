"""Testes dos scripts de manutenção dos workflows (poda das cópias do banco e conferência do site)."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
