"""Testes dos subgêneros: `busca.parse_subnos` e `comparador/subgeneros.py` (descoberta da árvore, rotulagem, custo).
Rodar: python -m unittest discover -s tests

Fixtures REAIS (14/out/2026, trechos da página 1 dos mais vendidos com o filtro "vendido pela Amazon", sem os tokens de sessão):
`subnos_genero.html` (Fantasia, Horror e Ficção Científica: 4 filhos), `subnos_filho.html` (Fantasia: 21 filhos) e
`subnos_folha.html` (Épica: folha, 634 resultados). Nenhum teste pede nada à Amazon: as sessões são falsas.
"""

import contextlib
import gzip
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

from comparador import __main__ as cli
from comparador import busca, rede, subgeneros
from tests.test_relatorio import RAIZ
from tests.test_site import banco

FIXTURES = Path(__file__).with_name("fixtures")
ler = lambda nome: (FIXTURES / nome).read_text(encoding="utf-8")  # noqa: E731


class Resposta:
    def __init__(self, texto, status=200):
        self.text, self.status_code, self.url = texto, status, ""


BLOQUEIO = Resposta('<html><body><form action="/errors/validateCaptcha"></form></body></html>', 503)
NAO_ACHADO = Resposta("<html><body>nada</body></html>", 404)


def asin(no, pagina, i):
    return f"B{int(no) % 1000:03d}{pagina:02d}{i:04d}"


def card(a, formatos=()):
    def preco(x, v):
        return (f'<a href="/x/dp/{x}/ref=sr"><span class="a-price" data-a-color="base">'
                f'<span class="a-offscreen">R$&nbsp;{v},00</span></span></a>')
    return (f'<div data-component-type="s-search-result" data-asin="{a}"><h2><span>Livro {a}</span></h2>'
            f'{preco(a, 30)}{"".join(preco(f, 20) for f in formatos)}</div>')


def pagina_no(no, nome, pais=(), filhos=(), total=16, pagina=1, exato=True):
    """A página `pagina` dos mais vendidos de `no`, como a Amazon a monta: navegação "Departamento" (pais, nó atual e filhos),
    barra de resultados, cards e paginação. `pais` e `filhos` são listas de (nó, nome)."""
    pai = ('<li id="n/{0}" class="a-spacing-micro"><span class="a-list-item"><a class="a-link-normal s-navigation-item" href="/s?x">'
           '<span class="s-back-arrow aok-inline-block"></span><span>{1}</span></a></span></li>')
    filho = ('<li id="n/{0}" class="a-spacing-micro s-navigation-indent-2"><span class="a-list-item">'
             '<a class="a-link-normal s-navigation-item" href="/s?x"><span>{1}</span></a></span></li>')
    atual = (f'<li id="n/{no}" class="a-spacing-micro s-navigation-indent-1"><span class="a-list-item">'
             f'<span class="a-text-bold">{nome}</span></span></li>')
    navegacao = "".join(pai.format(*p) for p in pais) + atual + "".join(filho.format(*f) for f in filhos)
    ultima = max(1, math.ceil(total / 16))
    n = max(0, min(16, total - 16 * (pagina - 1)))
    primeiro = 16 * (pagina - 1) + 1
    barra = (f"{primeiro}-{primeiro + n - 1} de {'' if exato else 'mais de '}{total:,}".replace(",", ".") + " resultados"
             if total > 16 else f"{total} resultados")
    cards = "".join(card(asin(no, pagina, i), [asin(no, pagina, 9000)] if i == 0 else []) for i in range(n))
    paginacao = "".join(f'<span class="s-pagination-item">{k}</span>' for k in range(1, ultima + 1)) if total else ""
    return (f'<html><body><div id="departments"><ul>{navegacao}</ul></div>'
            f'<div data-component-type="s-result-info-bar"><h2>{barra}</h2></div>{cards}'
            f'<span class="s-pagination-strip">{paginacao}</span></body></html>')


class Relogio:
    def __init__(self):
        self.t, self.dormiu = 100.0, []

    def __call__(self):
        return self.t

    def dormir(self, segundos):
        self.dormiu.append(segundos)
        self.t += segundos


# Uma árvore pequena: dois gêneros (100, 200); 110 é interno; 130 não tem livros da Amazon.
ARVORE = {
    "100": ("Gênero A", ["110", "120", "130"]),
    "110": ("Sub A1", ["111", "112"]),
    "111": ("Folha A11", []),
    "112": ("Folha A12", []),
    "120": ("Folha A2", []),
    "130": ("Sem livros", []),
    "200": ("Gênero B", ["210"]),
    "210": ("Folha B1", []),
}
TOTAIS = {"100": 6000, "110": 56, "111": 40, "112": 16, "120": 20, "200": 100, "210": 100}
PAGINAS = {"111": 3, "112": 1, "120": 2, "210": 7}      # ceil(total / 16) das folhas


class AmazonFalsa:
    """As páginas de mais vendidos de uma árvore {nó: (nome, [filhos])}. `totais`: resultados de cada nó (padrão 16, uma
    página); `vazios`: nós sem resultado; `redireciona`: {nó pedido: nó que a Amazon mostra}; `programa`: {n-ésimo pedido:
    resposta} para falhas. `chamadas` guarda (nó, página) de cada pedido."""

    def __init__(self, arvore=ARVORE, totais=TOTAIS, vazios=("130",), redireciona=None, programa=None, relogio=None, passo=1.5):
        self.arvore, self.totais, self.vazios = arvore, totais, set(vazios)
        self.redireciona, self.programa = redireciona or {}, dict(programa or {})
        self.relogio, self.passo, self.chamadas = relogio, passo, []

    def pais(self, no):
        for pai, (nome, filhos) in self.arvore.items():
            if no in filhos:
                return self.pais(pai) + [(pai, nome)]
        return [("1", "Livros")]

    def get(self, url, timeout=30):
        q = parse_qs(urlparse(url).query)
        no, pagina = re.search(r"n:(\d+)", unquote(q["rh"][0])).group(1), int(q["page"][0])
        self.chamadas.append((no, pagina))
        if self.relogio:
            self.relogio.t += self.passo
        if (r := self.programa.get(len(self.chamadas))) is not None:
            return r
        if no in self.vazios:
            return Resposta(ler("busca_vazia.html"))
        real = self.redireciona.get(no, no)
        nome, filhos = self.arvore[real]
        total = self.totais.get(real, 16)
        return Resposta(pagina_no(real, nome, self.pais(real), [(f, self.arvore[f][0]) for f in filhos], total, pagina,
                                  exato=total <= 1000))

    def nos(self):
        return [n for n, _ in self.chamadas]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name) / "sg"
        self.cache = subgeneros.Cache(self.pasta)

    def leitor(self, amazon, **kw):
        kw.setdefault("pausa", 0)
        kw.setdefault("dormir", lambda s: None)
        return subgeneros.Leitor(amazon, self.cache, **kw)

    def descobrir(self, amazon=None, raizes=("100", "200"), profundidade=None, **kw):
        amazon = amazon or AmazonFalsa()
        leitor = self.leitor(amazon, **kw)
        return amazon, leitor, subgeneros.descobrir(leitor, list(raizes), profundidade)


class TestParseSubnos(unittest.TestCase):
    def test_genero_real(self):
        d = busca.parse_subnos(ler("subnos_genero.html"))
        self.assertEqual(d.atual, busca.Subno("7841775011", "Fantasia, Horror e Ficção Científica"))
        self.assertEqual(d.pais, [busca.Subno("6740748011", "Livros")])
        self.assertEqual([(f.no, f.nome) for f in d.filhos], [("7841787011", "Fantasia"), ("7841776011", "Ficção Científica"),
                                                              ("7872746011", "Horror"), ("7843981011", "RPG")])

    def test_filho_real_do_mais_alto_ao_mais_proximo(self):
        d = busca.parse_subnos(ler("subnos_filho.html"))
        self.assertEqual(d.atual.nome, "Fantasia")
        self.assertEqual([p.nome for p in d.pais], ["Livros", "Fantasia, Horror e Ficção Científica"])
        self.assertEqual(len(d.filhos), 21)
        self.assertIn(busca.Subno("7841794011", "Épica"), d.filhos)
        self.assertEqual(d.filhos[-1], busca.Subno("202412671011", "Paranormal e Urbana"))

    def test_folha_real_nao_tem_filhos(self):
        d = busca.parse_subnos(ler("subnos_folha.html"))
        self.assertEqual((d.atual.nome, d.filhos), ("Épica", []))
        self.assertEqual([p.nome for p in d.pais], ["Livros", "Fantasia, Horror e Ficção Científica", "Fantasia"])

    def test_fatia_vazia_nao_e_erro(self):
        self.assertEqual(busca.parse_subnos(ler("busca_vazia.html")), busca.Departamento())

    def test_cards_sem_a_navegacao_sao_layout_desconhecido(self):
        with self.assertRaises(busca.LayoutDesconhecido):
            busca.parse_subnos(ler("busca_fatia.html"))

    def test_so_entram_nos_numericos(self):
        html = pagina_no("100", "A", [("1", "Livros")], [("110", "B")]).replace(
            "</ul>", '<li id="n/abc" class="s-navigation-indent-2"><a href="/s?x">C</a></li></ul>')
        self.assertEqual([f.no for f in busca.parse_subnos(html).filhos], ["110"])


class TestLerNo(unittest.TestCase):
    def test_paginas_reais(self):
        genero = subgeneros.ler_no(ler("subnos_genero.html"), "7841775011")
        self.assertEqual((genero["status"], genero["total"], genero["exato"], genero["paginas"]), ("interno", 6000, False, 75))
        self.assertEqual(len(genero["filhos"]), 4)
        filho = subgeneros.ler_no(ler("subnos_filho.html"), "7841787011")
        self.assertEqual((filho["status"], filho["total"], len(filho["filhos"])), ("interno", 3000, 21))
        folha = subgeneros.ler_no(ler("subnos_folha.html"), "7841794011")
        self.assertEqual((folha["status"], folha["nome"], folha["total"], folha["exato"], folha["paginas"]),
                         ("folha", "Épica", 634, True, 40))
        self.assertEqual(folha["pais"][-1], ["7841787011", "Fantasia"])

    def test_outro_no_nao_e_folha(self):
        i = subgeneros.ler_no(ler("subnos_folha.html"), "7841787011")        # pediu a Fantasia, a Amazon mostrou a Épica
        self.assertEqual(i["status"], "outro_no")
        self.assertIn("7841794011", i["detalhe"])

    def test_sem_resultado_e_vazio_e_nao_folha(self):
        i = subgeneros.ler_no(ler("busca_vazia.html"), "130")
        self.assertEqual((i["status"], i["total"], i["paginas"], i["filhos"]), ("vazio", 0, 0, []))

    def test_layout_desconhecido_e_erro_e_guarda_o_motivo(self):
        for html in ("<html><body>vitrine</body></html>", ler("busca_fatia.html")):
            i = subgeneros.ler_no(html, "100")
            self.assertEqual(i["status"], "erro")
            self.assertTrue(i["detalhe"])
            self.assertEqual((i["filhos"], i["total"], i["paginas"]), ([], None, 0))      # mesmas chaves de um nó lido

    def test_cards_com_a_navegacao_sem_o_no_atual_e_erro(self):
        html = re.sub(r'<li id="n/100".*?</li>', "", pagina_no("100", "A", [("1", "Livros")], [("110", "B")]), flags=re.S)
        i = subgeneros.ler_no(html, "100")
        self.assertEqual((i["status"], i["detalhe"]), ("erro", "navegação sem o nó atual"))

    def test_poucos_resultados_vem_sem_o_de(self):
        i = subgeneros.ler_no(pagina_no("111", "F", [("1", "Livros")], total=12), "111")
        self.assertEqual((i["status"], i["total"], i["exato"], i["paginas"]), ("folha", 12, True, 1))


class TestCache(Base):
    def test_grava_e_le_o_html_inteiro_e_conta(self):
        self.assertEqual((self.cache.ler("7", 1), len(self.cache), self.cache.nos()), (None, 0, []))
        self.cache.gravar("7", 1, "<p>açaí</p>")
        self.cache.gravar("7", 2, "<p>2</p>")
        self.cache.gravar("8", 1, "<p>8</p>")
        self.assertEqual((self.cache.ler("7", 1), len(self.cache), self.cache.nos()), ("<p>açaí</p>", 3, ["7", "8"]))
        self.assertTrue(self.cache.existe("7", 2) and not self.cache.existe("8", 2))
        self.assertEqual(sorted(f.suffix for f in (self.pasta / "paginas").iterdir()), [".gz"] * 3)    # sem arquivo provisório

    def test_arquivo_pela_metade_conta_como_ausente(self):
        self.cache.gravar("7", 1, "<p>x</p>" * 100)
        arq = self.pasta / "paginas" / "no-7-p1.html.gz"
        arq.write_bytes(arq.read_bytes()[:20])
        self.assertIsNone(self.cache.ler("7", 1))


class TestLeitor(Base):
    def test_pausa_entre_pedidos_e_nenhuma_para_o_cache_nem_antes_do_primeiro(self):
        relogio = Relogio()
        amazon = AmazonFalsa(relogio=relogio, passo=0.7)
        leitor = self.leitor(amazon, pausa=4, dormir=relogio.dormir, relogio=relogio)
        self.assertIsNotNone(leitor.pagina("111", 1))
        self.assertEqual(relogio.dormiu, [])
        relogio.t += 1.5                                         # o tempo que se gastou com a página antes de pedir a próxima
        leitor.pagina("120", 1)
        self.assertEqual(relogio.dormiu, [2.5])                  # 4 s entre o fim de um pedido e o começo do outro
        leitor.pagina("111", 1)                                  # no cache: nem pede, nem espera
        leitor.pagina("210", 1)
        self.assertEqual((relogio.dormiu, amazon.nos()), ([2.5, 4.0], ["111", "120", "210"]))

    def test_o_pedido_e_o_da_lista_de_mais_vendidos_com_o_filtro_do_coletor(self):
        amazon = AmazonFalsa()
        self.leitor(amazon).pagina("111", 3)
        self.assertEqual(amazon.chamadas, [("111", 3)])

    def test_primeiro_bloqueio_para_tudo_e_guarda_a_pagina(self):
        amazon = AmazonFalsa(programa={2: BLOQUEIO})
        leitor = self.leitor(amazon)
        leitor.pagina("111", 1)
        self.assertIsNone(leitor.pagina("120", 1))
        self.assertEqual(leitor.parou, "bloqueio")
        self.assertIn("bloqueado", leitor.erro)
        self.assertIsNone(leitor.pagina("210", 1))
        self.assertEqual(len(amazon.chamadas), 2)                # nada depois do bloqueio, nem nova tentativa
        self.assertIsNotNone(leitor.pagina("111", 1))            # o que está no cache continua saindo
        self.assertFalse(self.cache.existe("120", 1))
        self.assertEqual(len(list((self.pasta / "problemas").rglob("no-120-p1-*.html.gz"))), 1)

    def test_teto_conta_as_paginas_que_ja_estao_em_disco(self):
        self.cache.gravar("900", 1, "<p>x</p>")
        self.cache.gravar("901", 1, "<p>x</p>")
        amazon = AmazonFalsa()
        leitor = self.leitor(amazon, max_paginas=3)
        self.assertIsNotNone(leitor.pagina("111", 1))
        self.assertIsNone(leitor.pagina("120", 1))
        self.assertEqual((leitor.parou, amazon.nos(), leitor.usadas), ("teto de 3 páginas", ["111"], 3))

    def test_erros_seguidos_param_mas_um_erro_so_nao(self):
        amazon = AmazonFalsa(programa={1: NAO_ACHADO, 3: NAO_ACHADO})
        leitor = self.leitor(amazon)
        self.assertIsNone(leitor.pagina("111", 1))
        self.assertEqual((leitor.parou, leitor.erro), (None, "erro_http: HTTP 404"))
        self.assertIsNotNone(leitor.pagina("111", 1))
        self.assertIsNone(leitor.pagina("112", 1))               # 3º pedido: falha de novo, mas a anterior deu certo
        self.assertIsNone(leitor.parou)
        amazon.programa = {n: NAO_ACHADO for n in range(4, 9)}
        for no in ("120", "210", "111"):
            self.assertIsNone(leitor.pagina(no, 2))
        self.assertEqual(leitor.parou, "3 erros seguidos")
        self.assertEqual(len(amazon.chamadas), 5)                # o 6º pedido nem saiu


class TestDescobrir(Base):
    def test_le_em_largura_e_separa_folha_interno_vazio(self):
        amazon, leitor, arvore = self.descobrir()
        self.assertEqual(amazon.nos(), ["100", "200", "110", "120", "130", "210", "111", "112"])
        status = {no: i["status"] for no, i in arvore["nos"].items()}
        self.assertEqual(status, {"100": "interno", "200": "interno", "110": "interno", "120": "folha", "130": "vazio",
                                  "210": "folha", "111": "folha", "112": "folha"})
        self.assertTrue(arvore["completa"])
        self.assertIsNone(arvore["parou"])
        self.assertEqual(arvore["nos"]["111"]["pais"], [["1", "Livros"], ["100", "Gênero A"], ["110", "Sub A1"]])
        self.assertEqual({no: i["paginas"] for no, i in arvore["nos"].items() if i["status"] == "folha"}, PAGINAS)
        self.assertEqual(subgeneros.nao_lidos(arvore), set())

    def test_profundidade_limita_os_niveis_e_a_busca_seguinte_continua_dai(self):
        amazon, _, arvore = self.descobrir(profundidade=0)
        self.assertEqual(amazon.nos(), ["100", "200"])
        self.assertEqual(subgeneros.nao_lidos(arvore), {"110", "120", "130", "210"})
        self.assertTrue(arvore["completa"])                      # a busca terminou: o que falta é o que não se pediu
        amazon2, _, arvore = self.descobrir(profundidade=1)
        self.assertEqual(amazon2.nos(), ["110", "120", "130", "210"])                  # os gêneros saem do disco
        self.assertEqual(subgeneros.nao_lidos(arvore), {"111", "112"})
        amazon3, _, arvore = self.descobrir()
        self.assertEqual(amazon3.nos(), ["111", "112"])
        self.assertEqual(subgeneros.nao_lidos(arvore), set())

    def test_no_que_tem_dois_pais_e_lido_uma_vez(self):
        arvore = {**ARVORE, "100": ("Gênero A", ["110", "120", "130", "210"])}          # 210 também é filho do gênero A
        amazon, _, resultado = self.descobrir(AmazonFalsa(arvore))
        self.assertEqual(sorted(amazon.nos()), sorted(set(amazon.nos())))
        self.assertEqual(len(amazon.nos()), 8)
        self.assertEqual(resultado["nos"]["210"]["status"], "folha")
        # a página de 210 mostra um caminho só (pelo gênero A), mas ele também está abaixo do gênero B
        self.assertEqual(resultado["nos"]["210"]["pais"][-1][0], "100")
        self.assertIn("210", subgeneros.folhas_de(resultado, "200"))
        self.assertIn("210", subgeneros.folhas_de(resultado, "100"))
        self.assertEqual(subgeneros.abaixo_de(resultado, "200"), {"200", "210"})

    def test_so_as_raizes_pedidas_mas_a_arvore_traz_tudo_o_que_esta_em_disco(self):
        self.descobrir(raizes=("100",))
        amazon, _, arvore = self.descobrir(raizes=("200",))
        self.assertEqual(amazon.nos(), ["200", "210"])
        self.assertEqual(set(arvore["nos"]), {"100", "110", "111", "112", "120", "130", "200", "210"})

    def test_bloqueio_para_no_meio_e_a_retomada_pede_so_o_que_falta(self):
        amazon, leitor, parcial = self.descobrir(AmazonFalsa(programa={4: BLOQUEIO}))
        self.assertEqual(amazon.nos(), ["100", "200", "110", "120"])
        self.assertEqual((parcial["parou"], parcial["completa"]), ("bloqueio", False))
        self.assertEqual(set(parcial["nos"]), {"100", "200", "110"})                   # o nó bloqueado não entra
        retomada, _, final = self.descobrir()
        self.assertEqual(retomada.nos(), ["120", "130", "210", "111", "112"])
        with tempfile.TemporaryDirectory() as d:                 # a mesma busca sem interrupção dá a mesma árvore
            sem_parar = subgeneros.Leitor(AmazonFalsa(), subgeneros.Cache(d), pausa=0, dormir=lambda s: None)
            self.assertEqual(final["nos"], subgeneros.descobrir(sem_parar, ["100", "200"])["nos"])

    def test_pagina_que_falha_vira_erro_no_resultado_e_e_pedida_de_novo_depois(self):
        amazon, _, arvore = self.descobrir(AmazonFalsa(programa={3: NAO_ACHADO}))
        self.assertEqual(arvore["nos"]["110"]["status"], "erro")
        self.assertIn("404", arvore["nos"]["110"]["detalhe"])
        self.assertEqual(set(subgeneros.folhas_de(arvore)), {"120", "210"})              # 111 e 112 não foram alcançados
        retomada, _, arvore = self.descobrir()
        self.assertEqual(retomada.nos(), ["110", "111", "112"])
        self.assertEqual(arvore["nos"]["110"]["status"], "interno")

    def test_redirecionamento_para_outro_no_nao_vira_folha_nem_e_seguido(self):
        arvore = {**ARVORE, "300": ("Isolado", ["301"]), "301": ("Neto do isolado", [])}   # ninguém lista o 300
        amazon, _, resultado = self.descobrir(AmazonFalsa(arvore, redireciona={"120": "300"}))
        self.assertEqual(resultado["nos"]["120"]["status"], "outro_no")
        self.assertIn("300", resultado["nos"]["120"]["detalhe"])
        self.assertNotIn("120", subgeneros.folhas_de(resultado))
        self.assertNotIn("301", amazon.nos())                    # os filhos da página de outro nó não entram na busca

    def test_arvore_se_refaz_do_html_sem_pedir_nada(self):
        self.descobrir()
        class SemRede:
            def get(self, *a, **k):
                raise AssertionError("pediu à Amazon")
        antes = subgeneros.descobrir(self.leitor(SemRede()), ["100", "200"])
        self.assertTrue(antes["completa"])
        # um conserto no parser vale sem pedir de novo: o status vem do HTML, não do JSON
        arq = self.pasta / "paginas" / "no-120-p1.html.gz"
        arq.write_bytes(gzip.compress(pagina_no("120", "Folha A2", [("1", "Livros"), ("100", "Gênero A")], [("121", "Neta")]).encode()))
        depois = subgeneros.descobrir(self.leitor(AmazonFalsa(arvore={**ARVORE, "121": ("Neta", []), "120": ("Folha A2", ["121"])})),
                                      ["100", "200"])
        self.assertEqual(depois["nos"]["120"]["status"], "interno")
        self.assertIn("121", depois["nos"])

    def test_salvar_recebe_a_arvore_a_cada_no_novo_e_no_fim(self):
        salvos = []
        leitor = self.leitor(AmazonFalsa())
        subgeneros.descobrir(leitor, ["200"], salvar=lambda a: salvos.append((len(a["nos"]), a["completa"])))
        self.assertEqual(salvos, [(1, False), (2, True), (2, True)])


class TestRotular(Base):
    def setUp(self):
        super().setUp()
        self.amazon, self.leitor_, self.arvore = self.descobrir()

    def paginas_por_folha(self, k=75, de=None):
        return {no: len(r["paginas"]) for no, r in subgeneros.rotulos(self.cache, self.arvore, k, de).items()}

    def test_uma_rodada_por_pagina_entre_as_folhas(self):
        depois = len(self.amazon.chamadas)
        subgeneros.rotular(self.leitor_, self.arvore, 4)
        self.assertEqual(self.amazon.chamadas[depois:], [("111", 2), ("120", 2), ("210", 2), ("111", 3), ("210", 3), ("210", 4)])
        self.assertEqual(self.paginas_por_folha(4), {"111": 3, "112": 1, "120": 2, "210": 4})

    def test_bloqueio_no_meio_da_rodada_deixa_as_folhas_com_uma_pagina_de_diferenca(self):
        n = len(self.amazon.chamadas)
        self.amazon.programa = {n + 2: BLOQUEIO}
        subgeneros.rotular(self.leitor_, self.arvore, 4)
        self.assertEqual(self.leitor_.parou, "bloqueio")
        por_folha = self.paginas_por_folha(4)
        self.assertEqual(por_folha, {"111": 2, "112": 1, "120": 1, "210": 1})
        self.assertLessEqual(max(por_folha.values()) - min(por_folha.values()), 1)

    def test_rotulos_vem_do_cache_do_mais_vendido_ao_menos_e_juntam_os_formatos_do_card(self):
        subgeneros.rotular(self.leitor_, self.arvore, 2)
        r = subgeneros.rotulos(self.cache, self.arvore, 2)
        self.assertEqual(set(r), {"111", "112", "120", "210"})
        folha = r["111"]
        self.assertEqual((folha["nome"], folha["total"], folha["exato"], len(folha["paginas"])), ("Folha A11", 40, True, 2))
        self.assertEqual(folha["paginas"][0][0], [asin("111", 1, 0), asin("111", 1, 9000)])    # o do card primeiro, depois os formatos
        self.assertEqual(folha["paginas"][0][1], [asin("111", 1, 1)])
        self.assertEqual([len(p) for p in folha["paginas"]], [16, 16])
        self.assertEqual(len(r["112"]["paginas"]), 1)                                       # só tem uma página
        self.assertEqual(list(subgeneros.rotulos(self.cache, self.arvore, 2, de="110")), ["111", "112"])

    def test_buraco_no_cache_corta_a_lista_da_folha(self):
        subgeneros.rotular(self.leitor_, self.arvore, 3)
        (self.pasta / "paginas" / "no-210-p2.html.gz").unlink()
        self.assertEqual(self.paginas_por_folha(3)["210"], 1)

    def test_k_pelo_orcamento_conta_so_o_que_falta_ler(self):
        livres = len(self.cache) + 3
        self.assertEqual(subgeneros.k_pelo_orcamento(self.arvore, self.cache, None, livres), 2)      # K=2 custa 3; K=3 custaria 5
        self.assertEqual(subgeneros.k_pelo_orcamento(self.arvore, self.cache, None, len(self.cache)), 1)   # a página 1 já está em disco
        self.assertEqual(subgeneros.k_pelo_orcamento(self.arvore, self.cache, None, 1000), 7)             # mais que isso não há
        self.assertEqual(subgeneros.k_pelo_orcamento(self.arvore, self.cache, "110", 1000), 3)
        self.assertEqual(subgeneros.k_pelo_orcamento(self.arvore, self.cache, "999", 1000), 0)


class TestCusto(Base):
    def setUp(self):
        super().setUp()
        _, _, self.arvore = self.descobrir()

    def test_custo_soma_o_minimo_de_k_e_das_paginas_de_cada_folha(self):
        self.assertEqual([subgeneros.custo(self.arvore, k) for k in (1, 2, 5, 75)], [4, 7, 11, 13])
        self.assertEqual(subgeneros.custo(self.arvore, 2, de="110"), 3)

    def test_so_folha_entra(self):
        self.assertEqual(set(subgeneros.folhas_de(self.arvore)), {"111", "112", "120", "210"})
        self.assertEqual(set(subgeneros.folhas_de(self.arvore, "100")), {"111", "112", "120"})
        self.assertEqual(set(subgeneros.folhas_de(self.arvore, "120")), {"120"})

    def test_nos_ainda_nao_lidos_nao_entram_no_custo_e_aparecem_a_parte(self):
        with tempfile.TemporaryDirectory() as d:
            cache = subgeneros.Cache(d)
            arvore = subgeneros.descobrir(subgeneros.Leitor(AmazonFalsa(), cache, pausa=0, dormir=lambda s: None), ["100"], 0)
        self.assertEqual((subgeneros.custo(arvore, 5), subgeneros.nao_lidos(arvore)), (0, {"110", "120", "130"}))
        self.assertIn("3 subcategorias listadas e ainda não lidas", subgeneros.texto_resumo(arvore))

    def test_cobertura_pelos_totais(self):
        linhas = {c["no"]: c for c in subgeneros.cobertura_por_totais(self.arvore)}
        self.assertEqual((linhas["110"]["total"], linhas["110"]["soma_filhos"], linhas["110"]["filhos"]), (56, 56, 2))
        self.assertTrue(linhas["110"]["exato"] and linhas["110"]["filhos_exatos"])
        self.assertEqual((linhas["100"]["total"], linhas["100"]["soma_filhos"], linhas["100"]["exato"]), (6000, 76, False))   # 130, vazio, soma 0

    def test_resumo_em_texto(self):
        texto = subgeneros.texto_resumo(self.arvore, (2, 5))
        self.assertIn("8 nós lidos (4 folhas, 3 internos, 1 vazios)", texto)
        self.assertIn("rotular as 2 primeiras páginas de cada folha: 7 páginas", texto)
        self.assertIn("rotular as 5 primeiras páginas de cada folha: 11 páginas", texto)
        self.assertIn("uma por dia (ciclo de 24 h, ~7 por semana)", texto)
        self.assertIn("Gênero A: 3 subcategorias diretas", texto)


class TestSnapshot(Base):
    """O que o site lê: por folha, o nome, o total e os ASINs das primeiras páginas."""

    def setUp(self):
        super().setUp()
        _, leitor, self.arvore = self.descobrir()
        subgeneros.rotular(leitor, self.arvore, 2)
        self.snap = subgeneros.montar_snapshot(self.arvore, subgeneros.rotulos(self.cache, self.arvore, 2), 2, ["100", "200"],
                                               "2026-10-14T00:00:00+00:00")

    def test_monta_do_que_foi_rotulado(self):
        self.assertEqual((self.snap["v"], self.snap["k"], self.snap["generos"], self.snap["gerado_em"]),
                         (1, 2, ["100", "200"], "2026-10-14T00:00:00+00:00"))
        folhas = {f["no"]: f for f in self.snap["folhas"]}
        self.assertEqual(set(folhas), {"111", "112", "120", "210"})
        f = folhas["111"]
        self.assertEqual((f["nome"], f["total"], f["exato"]), ("Folha A11", 40, True))
        self.assertEqual(len(f["asins"]), len(set(f["asins"])))                       # sem repetir
        self.assertEqual(f["asins"][:2], [asin("111", 1, 0), asin("111", 1, 9000)])     # o do card e o do formato dele
        self.assertEqual(len(f["asins"]), 34)                                           # duas páginas de 16 cards, 1 deles com 2 ASINs

    def test_folha_sem_nenhum_livro_nao_entra(self):
        sem = subgeneros.montar_snapshot(self.arvore, {"999": {"nome": "Vazia", "total": 0, "exato": True, "paginas": [[]]}}, 1, [])
        self.assertEqual(sem["folhas"], [])

    def test_le_de_volta_em_json_e_em_gz(self):
        for nome, escrever in (("s.json", lambda p, b: p.write_bytes(b)), ("s.json.gz", lambda p, b: p.write_bytes(gzip.compress(b)))):
            arq = Path(self.tmp.name) / nome
            escrever(arq, json.dumps(self.snap).encode())
            self.assertEqual(subgeneros.ler_snapshot(arq)["folhas"], self.snap["folhas"])

    def test_snapshot_ruim_diz_o_que_esta_errado(self):
        d = Path(self.tmp.name)
        casos = {"nao-existe.json": None, "quebrado.json": b"{", "lista.json": b"[1]",
                 "versao.json": json.dumps({"v": 2, "folhas": self.snap["folhas"]}).encode(),
                 "vazio.json": json.dumps({"v": 1, "folhas": []}).encode(),
                 "mal-formado.json": json.dumps({"v": 1, "folhas": [{"no": 1, "nome": "x", "asins": ["A"]}, {"no": "2", "nome": "x", "asins": []},
                                                                  {"no": "3", "nome": "x", "total": "9", "asins": ["A"]}]}).encode()}
        for nome, conteudo in casos.items():
            if conteudo is not None:
                (d / nome).write_bytes(conteudo)
            with self.assertRaises(ValueError, msg=nome):
                subgeneros.ler_snapshot(d / nome)
        (d / "meio.json").write_text(json.dumps({"v": 1, "folhas": [{"no": 1}] + self.snap["folhas"][:1]}), encoding="utf-8")
        self.assertEqual(len(subgeneros.ler_snapshot(d / "meio.json")["folhas"]), 1)       # descarta só as folhas ruins


class TestComandoSubgeneros(Base):
    def rodar(self, *args, amazon=None):
        saida, erro, codigo = io.StringIO(), io.StringIO(), 0
        with mock.patch.object(sys, "argv", ["comparador", *args]), \
                mock.patch.object(rede, "nova_sessao", return_value=amazon or AmazonFalsa()) as sessao, \
                mock.patch.object(subgeneros, "PAUSA", 0.01), \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            try:
                cli.main()
            except SystemExit as e:
                codigo = e.code if isinstance(e.code, int) else 1
                if not isinstance(e.code, int):
                    print(e.code, file=erro)
        return codigo, saida.getvalue(), erro.getvalue(), sessao

    def test_a_pausa_minima_e_de_4_segundos(self):
        codigo, _, erro, _ = self.rodar("subgeneros", "descobrir", "--pausa", "0.001", "--pasta", str(self.pasta))
        self.assertEqual(codigo, 2)
        self.assertIn("a pausa mínima é", erro)

    def test_custo_sem_arvore_diz_o_que_fazer_e_nao_abre_sessao(self):
        codigo, _, erro, sessao = self.rodar("subgeneros", "custo", "--pasta", str(self.pasta))
        self.assertEqual(codigo, 1)
        self.assertIn("subgeneros descobrir", erro)
        sessao.assert_not_called()

    def test_descobrir_grava_a_arvore_e_o_html_e_custo_le_o_disco(self):
        codigo, saida, _, sessao = self.rodar("subgeneros", "descobrir", "--nos", "100,200", "--pasta", str(self.pasta), "--ks", "2,5")
        self.assertEqual(codigo, 0)
        self.assertIn("8 nós lidos", saida)
        self.assertIn("rotular as 2 primeiras páginas de cada folha: 7 páginas", saida)
        arvore = json.loads((self.pasta / "arvore.json").read_text(encoding="utf-8"))
        self.assertEqual(arvore["nos"]["111"]["status"], "folha")
        self.assertEqual(len(self.cache), 8)
        codigo, saida, _, sessao = self.rodar("subgeneros", "custo", "--pasta", str(self.pasta), "--ks", "5")
        self.assertEqual(codigo, 0)
        self.assertIn("rotular as 5 primeiras páginas de cada folha: 11 páginas", saida)
        sessao.assert_not_called()

    def test_parada_por_teto_sai_com_erro_e_diz_por_que(self):
        codigo, saida, erro, _ = self.rodar("subgeneros", "descobrir", "--nos", "100,200", "--pasta", str(self.pasta), "--max-paginas", "3")
        self.assertEqual(codigo, 1)
        self.assertIn("parou: teto de 3 páginas", erro)
        self.assertIn("3 nós lidos", saida)
        self.assertEqual(len(self.cache), 3)

    def test_rotular_sem_k_usa_o_que_cabe_no_teto_e_recusa_menos_de_3(self):
        self.rodar("subgeneros", "descobrir", "--nos", "100,200", "--pasta", str(self.pasta))
        codigo, _, erro, _ = self.rodar("subgeneros", "rotular", "--pasta", str(self.pasta), "--max-paginas", "9")     # 8 em disco: K = 1
        self.assertEqual(codigo, 1)
        self.assertIn("K abaixo de 3", erro)
        self.assertEqual(len(self.cache), 8)
        codigo, saida, _, _ = self.rodar("subgeneros", "rotular", "--pasta", str(self.pasta), "-k", "2")
        self.assertEqual(codigo, 0)
        self.assertIn("K = 2 páginas por folha", saida)
        r = json.loads((self.pasta / "rotulos.json").read_text(encoding="utf-8"))
        self.assertEqual((r["k"], {no: len(f["paginas"]) for no, f in r["folhas"].items()}), (2, {"111": 2, "112": 1, "120": 2, "210": 2}))

    def test_rotular_so_abaixo_de_um_no(self):
        self.rodar("subgeneros", "descobrir", "--nos", "100,200", "--pasta", str(self.pasta))
        codigo, _, _, _ = self.rodar("subgeneros", "rotular", "--pasta", str(self.pasta), "-k", "3", "--de", "110")
        self.assertEqual(codigo, 0)
        r = json.loads((self.pasta / "rotulos.json").read_text(encoding="utf-8"))
        self.assertEqual(list(r["folhas"]), ["111", "112"])


class TestSiteSemPlaywright(unittest.TestCase):
    """O site.yml instala só requests e beautifulsoup4: nenhum módulo novo pode importar o Playwright ao carregar."""

    def test_cli_site_roda_com_o_playwright_indisponivel(self):
        with tempfile.TemporaryDirectory() as d:
            banco(Path(d) / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
            codigo = ("import runpy, sys; sys.modules['playwright'] = None; "
                      f"sys.argv = ['comparador', 'site', {str(Path(d) / 'a.db')!r}, '--saida', {str(Path(d) / 's')!r}]; "
                      "runpy.run_module('comparador', run_name='__main__')")
            r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("1 livros", r.stdout)
            self.assertTrue((Path(d) / "s" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
