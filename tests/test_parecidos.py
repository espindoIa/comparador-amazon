import json
import os
import random
import subprocess
import sys
import unittest

from comparador import parecidos
from comparador.parecidos import Obra, Semente

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_GEN = 29


def sinteticas(semente_aleatoria: int, n: int = 300) -> list[Obra]:
    """Obras ao acaso, com o que costuma dar errado: autores repetidos e genéricos, empates de avaliações, sem gênero."""
    r = random.Random(semente_aleatoria)
    autores = ["Machado de Assis", "J.K. Rowling", "J. K. Rowling e Fulano", "Fulano", "", "Beltrano"] + [f"Autor {i}" for i in range(40)]
    obras = []
    for i in range(n):
        k = r.choice([0, 1, 1, 1, 2, 3])
        gen = tuple(sorted(r.sample(range(N_GEN), k)))
        obras.append(Obra(i, f"Livro {r.randrange(60)}", r.choice(autores), gen, r.choice(["", "", "Português", "Inglês"]),
                          r.choice([0, 0, 5, 10, 100, 1000, r.randrange(50000)])))
    return obras


def sementes_de(obras: list[Obra], r: random.Random, n: int) -> list[Semente]:
    out = []
    for _ in range(n):
        o = r.choice(obras)
        excluir = frozenset(r.sample(range(len(obras)), r.choice([0, 0, 3])))
        out.append(Semente(o.gen, o.idioma, o.autor, o.pos if r.random() < .8 else None, excluir))
    out.append(Semente((), "", "Ninguém"))                                   # sem gênero: nada
    out.append(Semente((0, 1, 2, 3, 4), "Inglês", ""))                        # muitos gêneros, sem autor
    return out


class TestParecidos(unittest.TestCase):
    def test_conta_rapida_igual_a_obra_por_obra(self):
        for semente_aleatoria in range(6):
            obras = sinteticas(semente_aleatoria)
            sementes = sementes_de(obras, random.Random(100 + semente_aleatoria), 80)
            for n in (3, 10):
                rapido = parecidos.calcular(obras, N_GEN, sementes, n, processos=1)
                for s, lista in zip(sementes, rapido):
                    self.assertEqual(lista, parecidos.bruto(obras, N_GEN, s, n), (semente_aleatoria, n, s))

    def test_mais_processos_dao_o_mesmo_resultado(self):
        # em outro processo: o fork não deve acontecer dentro da suíte (que pode ter threads de servidor no ar)
        codigo = (
            "import json, random, sys\n"
            "sys.path.insert(0, %r)\n"
            "from tests.test_parecidos import sinteticas, sementes_de\n"
            "from comparador import parecidos\n"
            "obras = sinteticas(7, 400); sementes = sementes_de(obras, random.Random(7), 200)\n"
            "print(json.dumps([parecidos.calcular(obras, 29, sementes, 10, processos=p) for p in (1, 2, 3)]))\n" % RAIZ)
        r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        um, dois, tres = json.loads(r.stdout)
        self.assertEqual(um, dois)
        self.assertEqual(um, tres)

    def test_regras(self):
        o = lambda i, t, a, gen, idi="", av=0: Obra(i, t, a, gen, idi, av)
        obras = [o(0, "Hobbit", "J.R.R. Tolkien", (0, 1), "Português", 900), o(1, "Silmarillion", "Tolkien, J.R.R.", (0,), "Português", 800),
                 o(2, "Duna", "Frank Herbert", (0,), "Português", 700), o(3, "Duna 2", "Frank Herbert", (0,), "Português", 600),
                 o(4, "Duna 3", "Frank Herbert", (0,), "Português", 500), o(5, "Dune", "Outro", (0,), "Inglês", 100000),
                 o(6, "Código Civil", "Fulano", (2,), "", 10 ** 6), o(7, "Sem gênero", "Beltrano", (), "", 10 ** 6),
                 o(8, "Raro", "Sicrano", (1,), "", 0), o(9, "Hobbit (outra edição)", "", (0, 1), "Português", 50)]
        # a própria obra e as excluídas (outras edições) ficam de fora; no máximo 2 por autor; idioma diferente cai
        s = Semente((0, 1), "Português", "Machado", obra=0, excluir=frozenset({9}))
        lista = parecidos.calcular(obras, 3, [s], 10, processos=1)[0]
        self.assertNotIn(0, lista)
        self.assertNotIn(9, lista)
        self.assertEqual([j for j in lista if obras[j].a == "frank herbert"], [2, 3])
        self.assertNotIn(6, lista)                                   # nenhum gênero em comum
        self.assertNotIn(7, lista)
        self.assertLess(lista.index(4 if 4 in lista else 2), lista.index(5))   # Dune em inglês vale 0,3: vem depois
        self.assertEqual(lista[0], 8)                                # gênero raro (1) pesa mais que o comum (0)
        # o mesmo autor sai, com outra grafia ("J.R.R. Tolkien" e "J.R.R. Tolkien, Christopher" casam)
        s = Semente((0,), "Português", "J.R.R. Tolkien, Christopher", obra=None)
        self.assertNotIn(0, parecidos.calcular(obras, 3, [s], 10, processos=1)[0])
        self.assertEqual(parecidos.chave_autor("J.K. Rowling e Fulano"), "j k rowling")
        self.assertEqual(parecidos.chave_autor("C.S. Lewis, Pauline Baynes"), "c s lewis")


if __name__ == "__main__":
    unittest.main()
