import json
import os
import random
import subprocess
import sys
import unittest
import unittest.mock

from comparador import parecidos
from comparador.parecidos import Obra, Semente

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_GEN = 29
FICCAO = frozenset(range(0, 10))          # nos dados sintéticos, os gêneros 0–9 são de ficção
BALDE = frozenset({28})                    # e o 28, o de idioma
PALAVRAS = ["python", "dados", "investimento", "direito", "constitucional", "ansiedade", "principe", "dragao", "amor",
            "historia", "humanidade", "estoicismo", "receita", "jardim"]


def sinteticas(semente_aleatoria: int, n: int = 300) -> list[Obra]:
    """Obras ao acaso, com o que costuma dar errado: autores repetidos, invertidos e genéricos, títulos que dividem
    palavras e começos, empates de avaliações, sem gênero."""
    r = random.Random(semente_aleatoria)
    autores = ["Machado de Assis", "Assis, Machado de", "J.K. Rowling", "Rowling J.K", "Fulano", "", "Vários autores",
               "Editora Europa", "Beltrano"] + [f"Autor {i}" for i in range(30)]
    obras = []
    for i in range(n):
        k = r.choice([0, 1, 1, 1, 2, 3])
        gen = tuple(sorted(r.sample(range(N_GEN), k)))
        titulo = " ".join(r.sample(PALAVRAS, r.choice([1, 2, 3]))) + r.choice(["", ": um guia", " (capa dura)", " vol. 2"])
        obras.append(Obra(i, titulo.capitalize(), r.choice(autores), gen, r.choice(["", "", "Português", "Inglês"]),
                          r.choice([0, 0, 5, 10, 100, 1000, r.randrange(50000)]), titulo.split(":")[0].split(" (")[0]))
    return obras


def sementes_de(obras: list[Obra], r: random.Random, n: int) -> list[Semente]:
    out = []
    for _ in range(n):
        o = r.choice(obras)
        excluir = frozenset(r.sample(range(len(obras)), r.choice([0, 0, 3])))
        out.append(Semente(o.gen, o.idioma, o.autor, o.pos if r.random() < .8 else None, excluir, o.titulo, o.base))
    out.append(Semente((), "", "Ninguém", titulo="python"))                    # sem gênero: nada
    out.append(Semente((10, 11, 12, 13, 14), "Inglês", "", titulo="python dados investimento direito"))
    return out


class TestParecidos(unittest.TestCase):
    def test_conta_rapida_igual_a_obra_por_obra(self):
        for semente_aleatoria in range(6):
            obras = sinteticas(semente_aleatoria)
            sementes = sementes_de(obras, random.Random(100 + semente_aleatoria), 80)
            for n in (3, 10):
                rapido = parecidos.calcular(obras, N_GEN, sementes, n, processos=1, ficcao=FICCAO, balde=BALDE)
                for s, lista in zip(sementes, rapido):
                    self.assertEqual(lista, parecidos.bruto(obras, N_GEN, s, n, FICCAO, BALDE), (semente_aleatoria, n, s))

    def test_mesmo_resultado_com_mais_processos_e_outra_ordem_de_sets(self):
        # em outro processo: o fork não deve acontecer dentro da suíte (que pode ter threads de servidor no ar), e cada
        # PYTHONHASHSEED muda a ordem dos sets; as palavras empatadas não podem depender dela
        codigo = (
            "import json, random, sys\n"
            "sys.path.insert(0, %r)\n"
            "from tests.test_parecidos import sinteticas, sementes_de, FICCAO, BALDE\n"
            "from comparador import parecidos\n"
            "obras = sinteticas(7, 400); sementes = sementes_de(obras, random.Random(7), 200)\n"
            "print(json.dumps([parecidos.calcular(obras, 29, sementes, 10, processos=p, ficcao=FICCAO, balde=BALDE) for p in (1, 2, 3)]))\n"
            % RAIZ)
        saidas = []
        for semente_hash in ("1", "2"):
            r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120,
                               env={**os.environ, "PYTHONHASHSEED": semente_hash})
            self.assertEqual(r.returncode, 0, r.stderr)
            um, dois, tres = json.loads(r.stdout)
            self.assertEqual(um, dois)
            self.assertEqual(um, tres)
            saidas.append(um)
        self.assertEqual(saidas[0], saidas[1])

    def test_regras_de_genero_idioma_e_autor(self):
        o = lambda i, t, a, gen, idi="", av=0: Obra(i, t, a, gen, idi, av)
        obras = [o(0, "Hobbit", "J.R.R. Tolkien", (0, 1), "Português", 900), o(1, "Silmarillion", "Tolkien, J.R.R.", (0,), "Português", 800),
                 o(2, "Duna", "Frank Herbert", (0,), "Português", 700), o(3, "Messias de Duna", "Herbert Frank", (0,), "Português", 600),
                 o(4, "Filhos de Duna", "FRANK HERBERT", (0,), "Português", 500), o(5, "Dune", "Outro", (0,), "Inglês", 100000),
                 o(6, "Código Civil", "Fulano", (2,), "", 10 ** 6), o(7, "Sem gênero", "Beltrano", (), "", 10 ** 6),
                 o(8, "Raro", "Sicrano", (1,), "", 0), o(9, "Contos", "Vários autores", (0,), "", 10),
                 o(10, "Mais contos", "Vários autores", (0,), "", 9), o(11, "Ainda contos", "Vários autores", (0,), "", 8)]
        s = Semente((0, 1), "Português", "Machado", obra=0, excluir=frozenset({8}), titulo="Hobbit")
        lista = parecidos.calcular(obras, 3, [s], 12, processos=1)[0]
        self.assertNotIn(0, lista)                                    # a própria obra
        self.assertNotIn(8, lista)                                    # excluída (outras edições)
        self.assertEqual([j for j in lista if j in (2, 3, 4)], [2, 3])   # 2 por autor, com o nome escrito de 3 jeitos
        self.assertEqual([j for j in lista if j in (9, 10, 11)], [9, 10])  # autor genérico também tem limite
        self.assertNotIn(6, lista)                                    # nenhum gênero em comum
        self.assertNotIn(7, lista)
        self.assertLess(lista.index(2), lista.index(5))               # Dune em inglês vale 0,3: vem depois
        # o mesmo autor sai, escrito de outro jeito; autor genérico não tira os outros do mesmo "autor"
        s = Semente((0,), "Português", "Tolkien, J. R. R., Christopher", titulo="Contos inacabados")
        self.assertNotIn(1, parecidos.calcular(obras, 3, [s], 12, processos=1)[0])
        s = Semente((0,), "", "Vários autores", titulo="Outros contos")
        self.assertIn(9, parecidos.calcular(obras, 3, [s], 12, processos=1)[0])
        self.assertEqual(parecidos.chave_autor("J.K. Rowling e Fulano"), parecidos.chave_autor("Rowling J.K"))
        self.assertEqual(parecidos.chave_autor("Machado de Assis"), parecidos.chave_autor("Machado Assis e Editora Itatiaia"))
        self.assertEqual(parecidos.chave_autor("Kiyosaki Robert T"), parecidos.chave_autor("Robert T. Kiyosaki"))
        self.assertTrue(parecidos.autor_generico("Editora Europa") and parecidos.autor_generico("Vários autores, Fulano"))
        self.assertFalse(parecidos.autor_generico("Machado de Assis"))

    def test_o_mesmo_livro_nao_e_parecido(self):
        o = lambda i, t, a, base, av: Obra(i, t, a, (0,), "", av, base)
        obras = [o(0, "Dom Casmurro", "Machado de Assis", "dom casmurro", 100),
                 o(1, "Dom Casmurro - Edição de Luxo", "Outra Editora", "dom casmurro", 90),        # mesmo título-base: fora
                 o(2, "Dom Casmurro comentado", "", "dom casmurro comentado", 80),                # mesmo começo, sem autor: fora
                 o(3, "Dom Casmurro (Volume 2)", "Outro Autor", "dom casmurro (volume 2)", 70),   # mesmo começo, outro autor: fica
                 o(4, "Iracema", "José de Alencar", "iracema", 60),
                 o(5, "Iracema - edição de bolso", "Alencar José", "iracema", 50),      # edição de 4 (título-base igual): uma vez só
                 o(6, "Senhora", "José de Alencar", "senhora", 40)]
        s = Semente((0,), "", "Machado de Assis", obra=0, titulo="Dom Casmurro", base="dom casmurro")
        self.assertEqual(parecidos.calcular(obras, 1, [s], 10, processos=1)[0], [3, 4, 6])

    def test_tema_so_com_palavras_de_assunto(self):
        # gênero 1 é ficção; 2 e 3, não ficção; 4 é o balde de idioma
        obras = [Obra(0, "Python fluente", "A", (2,), "", 10), Obra(1, "Python para dados", "B", (2,), "", 5),
                 Obra(2, "Aprenda Python", "C", (2,), "", 1), Obra(3, "Banco de dados", "D", (2,), "", 100),
                 Obra(4, "Python em inglês", "E", (4,), "", 1),
                 Obra(5, "O príncipe dragão", "F", (1,), "", 10), Obra(6, "O príncipe", "G", (1, 3), "", 1),
                 Obra(7, "Príncipe da Pérsia", "H", (1,), "", 1), Obra(8, "Dragão e príncipe", "I", (1,), "", 9000)]
        args = dict(ficcao=frozenset({1}), balde=frozenset({4}))
        with unittest.mock.patch.object(parecidos, "DF_TEMA", (2, 100)):
            ind = parecidos._Indice(obras, 5, args["ficcao"], args["balde"])
            self.assertIn("python", ind.palavras.idf)                  # não ficção: assunto
            self.assertNotIn("principe", ind.palavras.idf)             # ficção: nome de personagem
            s = Semente((2,), "", "Z", obra=0, titulo="Python fluente")
            lista = parecidos.calcular(obras, 5, [s], 3, processos=1, **args)[0]
            self.assertEqual(lista[:2], [1, 2])                        # "python" passa na frente do mais avaliado (3)
            self.assertEqual(lista, parecidos.bruto(obras, 5, s, 3, **args))
            s = Semente((1,), "", "Z", obra=5, titulo="O príncipe dragão")
            self.assertEqual(parecidos.calcular(obras, 5, [s], 1, processos=1, **args)[0], [8])   # sem tema: o mais avaliado

    def test_palavras(self):
        self.assertEqual(parecidos.palavras("Investimentos inteligentes (Edição revista e atualizada) - Volume 2"),
                         {"investimento", "inteligente"})
        self.assertEqual(parecidos.palavras("O Hobbit + pôster"), {"hobbit"})
        self.assertEqual(parecidos.chave_titulo("O Último Desejo - The Witcher"), "ultimo desejo")
        self.assertEqual(parecidos.chave_autor("Cury Augusto Cury"), parecidos.chave_autor("Augusto Cury"))

    def test_palavras_da_semente_vem_do_titulo_principal(self):
        obras = [Obra(i, t, "A", (2,), "", 0) for i, t in enumerate(
            ["hábito atômico", "hábito", "hábito", "comprovado", "comprovado", "comprovado", "atômico", "atômico",
             "humanidade", "humanidade", "humanidade", "aquarela", "aquarela", "aquarela", "breve", "breve", "breve"])]
        with unittest.mock.patch.object(parecidos, "DF_TEMA", (2, 100)):
            ind = parecidos._Indice(obras, 3, frozenset(), frozenset())
            sem = ind.palavras.da_semente
            # o título principal primeiro, mesmo com palavras mais raras no subtítulo
            self.assertEqual(sem("Hábitos Atômicos: um método comprovado"), ("atomico", "habito", "comprovado"))
            self.assertEqual(sem("Sapiens: uma breve história da humanidade")[:2], ("breve", "humanidade"))
            # subtítulo que descreve a edição não conta
            self.assertEqual(sem("O Pequeno Príncipe: tradução original com aquarelas"), ())

    def _chaves(self, *pares):
        """as chaves de "Mais de …" para (autor, título-base) em ordem"""
        return parecidos.chaves_do_autor([a for a, _ in pares], [b for _, b in pares])

    def test_chaves_do_autor_mesma_ordem_e_pessoas_diferentes(self):
        k = self._chaves(("F. Scott Fitzgerald", "gatsby"), ("F Scott FITZGERALD", "paraiso"), ("Mozart Fialho Jr", "word"),
                         ("Mozart Fialho Junior", "excel"), ("Fabio Fabio Guerrini", "obras"), ("Fabio Guerrini", "diario"),
                         ("Fitzgerald, F. Scott e Fulano", "alma"))
        self.assertEqual(k[0], k[1])                                  # maiúsculas, pontos
        self.assertEqual(k[2], k[3])                                  # Jr = Junior
        self.assertEqual(k[4], k[5])                                  # palavra repetida
        self.assertNotEqual(k[0], k[6])                               # "Fitzgerald, F. Scott": 1º autor é só "Fitzgerald"
        # partículas e sufixos separam pessoas diferentes
        k = self._chaves(("Paula Di Carvalho", "romance"), ("Paula Carvalho", "direito"), ("Ricardo Ramos", "presenca"),
                         ("Ricardo Ramos Filho", "maria"), ("Alvaro de Campos", "poemas"), ("Álvaro Campos", "bola"))
        self.assertEqual(len(set(k)), 6)
        # acento e maiúsculas não separam
        k = self._chaves(("José Saramago", "ensaio"), ("JOSE SARAMAGO", "cegueira"))
        self.assertEqual(k[0], k[1])

    def test_chaves_do_autor_ordem_trocada_so_com_prova(self):
        # sem prova: duas pessoas, ou ninguém sabe
        k = self._chaves(("Maya Grace", "magia"), ("Grace Maya", "coquetel"), ("Maria José Santos", "a"),
                         ("José Maria Santos", "b"), ("Benjamin Cesar", "matematica"), ("Cesar Benjamin", "darwin"))
        self.assertEqual(len(set(k)), 6)
        # prova 1: o mesmo título-base
        k = self._chaves(("Joel Osteen", "eu declaro"), ("Osteen Joel", "eu declaro"))
        self.assertEqual(k[0], k[1])
        # prova 2: a mesma série (começo do título, antes do número)
        k = self._chaves(("Yuto Sano", "gokurakugai 05"), ("Sano Yuto", "gokurakugai 06"),
                         ("Kurtis J Wiebe", "rat queens volume 1"), ("J Wiebe Kurtis", "rat queens os tentaculos"))
        self.assertEqual(k[0], k[1])
        self.assertEqual(k[2], k[3])
        # prova 3: uma ordem com 8 vezes as obras da outra, que tem poucas (nome invertido)
        k = self._chaves(*[("Nora Roberts", f"livro {i}") for i in range(8)], ("Roberts Nora", "ilha"))
        self.assertEqual(len(set(k)), 1)
        k = self._chaves(*[("Joseph Frank", f"estudo {i}") for i in range(5)], ("Frank Joseph", "atlantida"))   # 5 contra 1
        self.assertEqual(len(set(k)), 2)
        k = self._chaves(*[("Nora Roberts", f"livro {i}") for i in range(40)], *[("Roberts Nora", f"outro {i}") for i in range(5)])
        self.assertEqual(len(set(k)), 2)                                                                          # a minoria tem mais de 3
        # séries curtas demais não provam nada
        self.assertEqual(parecidos.serie("o guia"), "")
        self.assertEqual(parecidos.serie("quero te amar ate o fim 01"), "quero te")
        self.assertEqual(parecidos.serie("gokurakugai 05"), "gokurakugai")

    def test_chaves_do_autor_sem_chave_e_ordem_das_obras(self):
        k = self._chaves(("Vários autores", "x"), ("Editora Europa", "y"), ("", "z"), ("Ana", "w"), ("&#1606;&#1608;&#1601;", "v"),
                         ("Edições SM", "u"), ("Machado de Assis", "t"))
        self.assertEqual(k[:6], [None] * 6)                           # genérico, editora, sem nome, curto, só números
        self.assertIsNotNone(k[6])
        # o mesmo agrupamento em qualquer ordem de entrada
        pares = [("Joel Osteen", "eu declaro"), ("Osteen Joel", "eu declaro"), ("Maya Grace", "a"), ("Grace Maya", "b"),
                 ("Nora Roberts", "c"), ("Nora Roberts", "d"), ("Fulano de Tal", "e")]
        def classes(ordem):
            k = self._chaves(*[pares[i] for i in ordem])
            return {frozenset(ordem[j] for j in range(len(k)) if k[j] == x) for x in set(k)}
        base = classes(range(len(pares)))
        for ordem in ([6, 5, 4, 3, 2, 1, 0], [3, 1, 5, 0, 6, 2, 4]):
            self.assertEqual(classes(ordem), base)


if __name__ == "__main__":
    unittest.main()
