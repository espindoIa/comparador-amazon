import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from comparador import site, varredura
from tests.test_relatorio import NODE, RAIZ, navegador


def banco(caminho, itens, aviso=None):
    c = sqlite3.connect(caminho)
    varredura.criar_schema(c)
    for asin, titulo, formato, trechos in itens:
        c.execute("INSERT INTO catalogo (asin, titulo, formato, no, primeiro_visto, ultimo_visto) VALUES (?,?,?,?,?,?)", (asin, titulo, formato, "n", "2026-10-01T12:00:00+00:00",
                                                              (trechos[-1][1] if trechos else "2026-10-01") + "T12:00:00+00:00"))
        for desde, ate, preco, capa in trechos:
            c.execute("INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) VALUES (?,?,?,?,?)",
                      (asin, preco, capa, desde + "T12:00:00+00:00", ate + "T12:00:00+00:00"))
    if aviso:
        c.execute("CREATE TABLE aviso (texto TEXT)")
        c.execute("INSERT INTO aviso VALUES (?)", (aviso,))
    c.commit()
    c.close()


def indice(saida):
    """(parte 0 do índice v3, todas as obras de todas as partes)."""
    dados = Path(saida) / "dados"
    p0 = json.loads((dados / "indice-0.json").read_text(encoding="utf-8"))
    obras = []
    for n in range(p0["partes"]):
        obras += json.loads((dados / f"indice-{n}.json").read_text(encoding="utf-8"))["o"]
    return p0, obras


def edicoes(saida):
    """{asin: (obra, edição)} do índice v3."""
    return {e[0]: (o, e) for o in indice(saida)[1] for e in o[8]}


def historico(saida, asin):
    return json.loads((Path(saida) / f"dados/h/{site.fragmento(asin)}.json").read_text(encoding="utf-8"))[asin]


class TestSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_juntar_trechos(self):
        t = site.juntar_trechos([[10, 20, 5000, None], [15, 30, 5000, 8000], [31, 40, 4000, None], [60, 70, 4000, None]])
        self.assertEqual(t, [[10, 30, 5000, 8000], [31, 40, 4000, None], [60, 70, 4000, None]])   # 20 dias de buraco: não junta

    def test_construir_dois_bancos_com_livro_repetido(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Capa comum", [("2026-10-01", "2026-10-05", 5000, 8000)]),
                                ("B000000002", "Só no A", None, [("2026-10-01", "2026-10-01", 1000, None)])], aviso="SIMULADO")
        banco(self.d / "b.db", [("B000000001", "Livro Um", "Capa comum", [("2026-10-05", "2026-10-09", 5000, None)]),
                                ("B000000003", "Sem preço", None, [])])
        meta = site.construir([self.d / "a.db", self.d / "b.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        self.assertEqual(meta["itens"], 2)                       # o sem preço fica de fora
        self.assertEqual(meta["aviso"], "SIMULADO")
        for nome in site.ARQUIVOS_WEB:
            self.assertTrue((self.d / "out" / nome).exists(), nome)
        ind = indice(self.d / "out")[0]
        o, e = edicoes(self.d / "out")["B000000001"]
        self.assertEqual(o[0], "Livro Um")
        self.assertEqual([ind["fmt"][e[1]], e[2], e[3]], ["Capa comum", 5000, 8000])
        self.assertEqual(ind["hoje"], meta["ultima_coleta"])
        self.assertEqual(e[4], 0)                                # visto na última coleta
        h = json.loads((self.d / f"out/dados/h/{site.fragmento('B000000001')}.json").read_text(encoding="utf-8"))
        self.assertEqual(len(h["B000000001"]["h"]), 1)           # os dois históricos viraram um trecho só
        self.assertEqual(len(json.loads((self.d / "out/dados/eventos.json").read_text())), 2)

    def test_livro_que_muda_de_sequencia_de_coleta_mantem_o_historico_e_ganha_o_preco_novo(self):
        # "vendidos" lia todos os gêneros; depois da divisão, "vendidos-b" lê o de X e o de Y e o antigo para de vê-los
        banco(self.d / "vendidos.db", [("B000000001", "Livro X", "Capa comum", [("2026-10-01", "2026-10-05", 5000, None)]),
                                       ("B000000002", "Livro Y", "Capa comum", [("2026-10-01", "2026-10-05", 4000, None)]),
                                       ("B000000003", "Livro Z", "Capa comum", [("2026-10-01", "2026-10-12", 3000, None)])])
        banco(self.d / "vendidos-b.db", [("B000000001", "Livro X", "Capa comum", [("2026-10-12", "2026-10-12", 5000, None)]),
                                         ("B000000002", "Livro Y", "Capa comum", [("2026-10-12", "2026-10-12", 3500, None)])])
        meta = site.construir([self.d / "vendidos.db", self.d / "vendidos-b.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        self.assertEqual(meta["itens"], 3)
        ed = edicoes(self.d / "out")
        self.assertEqual(len(historico(self.d / "out", "B000000001")["h"]), 1)         # mesmo preço: um trecho só
        self.assertEqual([t[2] for t in historico(self.d / "out", "B000000002")["h"]], [4000, 3500])
        self.assertEqual([ed["B000000002"][1][2], ed["B000000002"][1][4]], [3500, 0])  # preço do banco que lê hoje
        self.assertEqual(ed["B000000003"][1][4], 0)                                    # o que o banco antigo ainda lê

    def test_detalhes_da_leitura_mais_nova_valem_em_qualquer_ordem_dos_bancos(self):
        # o banco "velho" parou de ler o livro no dia 5; o "novo" o lê todo dia (e hoje veio sem capa e sem autor)
        banco(self.d / "velho.db", [("B000000001", "Título velho", "Capa comum", [("2026-10-01", "2026-10-05", 5000, None)])])
        banco(self.d / "novo.db", [("B000000001", "Título novo", "Capa comum", [("2026-10-12", "2026-10-12", 5000, None)])])
        for nome, sql in (("velho", "UPDATE catalogo SET avaliacoes = 10, nota = 40, autor = 'Ana', imagem = 'img-velha'"),
                          ("novo", "UPDATE catalogo SET avaliacoes = 500, nota = 45, autor = NULL, imagem = NULL")):
            c = sqlite3.connect(self.d / f"{nome}.db")
            c.execute(sql)
            c.commit()
            c.close()
        for ordem in (("velho", "novo"), ("novo", "velho")):
            saida = self.d / f"out-{ordem[0]}"
            site.construir([self.d / f"{n}.db" for n in ordem], saida, Path(RAIZ) / "eventos.csv")
            obra, _ = edicoes(saida)["B000000001"]
            # título, nota e avaliações do mais novo; o que ele não trouxe (autor, capa) vem do mais velho
            self.assertEqual((obra[0], obra[1], obra[2], obra[6], obra[7]), ("Título novo", "Ana", "img-velha", 45, 500), ordem)

    def test_mesmo_livro_lido_por_duas_sequencias_em_dias_diferentes_tem_uma_queda_so(self):
        # as duas leram R$ 50 até o dia 6; a sequência B viu o preço novo no dia 7 e a A só no dia 8
        a = [("2026-10-01", "2026-10-06", 5000, None), ("2026-10-08", "2026-10-08", 4000, None)]
        b = [("2026-10-01", "2026-10-06", 5000, None), ("2026-10-07", "2026-10-08", 4000, None)]
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Capa comum", a)])
        banco(self.d / "b.db", [("B000000001", "Livro Um", "Capa comum", b)])
        site.construir([self.d / "a.db", self.d / "b.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        h = historico(self.d / "out", "B000000001")["h"]
        self.assertEqual([t[2] for t in h], [5000, 4000])                        # uma mudança só
        destaques = json.loads((self.d / "out/dados/destaques.json").read_text(encoding="utf-8"))
        self.assertEqual([b[0] for b in destaques["baixa"]], ["B000000001"])     # e a queda aparece uma vez
        self.assertEqual(edicoes(self.d / "out")["B000000001"][1][2], 4000)

    def test_varias_leituras_por_dia_oscilacao_no_mesmo_dia_nao_e_queda_nem_menor_registrado(self):
        # R$ 50 por 20 dias; no último dia o preço foi a R$ 40 de manhã, voltou a R$ 50 à tarde e fechou em R$ 50
        base = [("2026-10-01", "2026-10-20", 5000, None), ("2026-10-21", "2026-10-21", 4000, None), ("2026-10-21", "2026-10-21", 5000, None)]
        # outro livro: R$ 50 por 20 dias; no último dia, R$ 50 → R$ 40 de manhã e continuou em R$ 40: queda de verdade
        queda = [("2026-10-01", "2026-10-20", 5000, None), ("2026-10-21", "2026-10-21", 4000, None)]
        banco(self.d / "a.db", [("B000000001", "Oscila", "Capa comum", base), ("B000000002", "Cai", "Capa comum", queda)])
        site.construir([self.d / "a.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        ed = edicoes(self.d / "out")
        self.assertEqual([ed["B000000001"][1][2], ed["B000000001"][1][6]], [5000, 5000])     # o de R$ 40 de algumas horas não conta
        self.assertEqual([ed["B000000002"][1][2], ed["B000000002"][1][6]], [4000, 4000])
        destaques = json.loads((self.d / "out/dados/destaques.json").read_text(encoding="utf-8"))
        self.assertEqual([b[0] for b in destaques["baixa"]], ["B000000002"])
        self.assertEqual(site.queda([[1, 20, 5000, None], [21, 21, 4000, None], [21, 21, 5000, None]], 21), None)
        self.assertEqual(site.queda([[1, 20, 5000, None], [21, 21, 4000, None]], 21), (5000, 21))

    def test_meta_traz_ate_quando_os_precos_foram_lidos_pelo_banco_mais_atrasado(self):
        banco(self.d / "a.db", [("B000000001", "Um", "Capa comum", [("2026-10-01", "2026-10-13", 5000, None)])])
        banco(self.d / "b.db", [("B000000002", "Dois", "Capa comum", [("2026-10-01", "2026-10-12", 5000, None)])])
        meta = site.construir([self.d / "a.db", self.d / "b.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        self.assertEqual(meta["lido_ate"], "2026-10-12T12:00:00+00:00")        # o banco que parou antes
        self.assertEqual(json.loads((self.d / "out/dados/meta.json").read_text(encoding="utf-8"))["lido_ate"], meta["lido_ate"])

    def test_detalhes_do_livro_vao_para_o_indice_e_o_historico(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Capa dura", [("2026-10-01", "2026-10-05", 5000, None)]),
                                ("B000000002", "Livro Dois", "Kindle", [("2026-10-01", "2026-10-05", 900, None)])])
        c = sqlite3.connect(self.d / "a.db")
        c.execute("UPDATE catalogo SET autor='Ana', imagem='img1', publicado='2024-08-05', idioma='Português', "
                  "obra='B000000001' WHERE asin='B000000001'")
        c.commit()
        c.close()
        site.construir([self.d / "a.db"], self.d / "out", Path(RAIZ) / "eventos.csv")
        ed = edicoes(self.d / "out")
        idi = indice(self.d / "out")[0]["idi"]
        self.assertEqual(ed["B000000001"][0][:5], ["Livro Um", "Ana", "img1", 2024, idi.index("Português") + 1])
        self.assertEqual(ed["B000000002"][0][:5], ["Livro Dois", "", "", 0, 0])           # livro ainda sem detalhes
        h = json.loads((self.d / f"out/dados/h/{site.fragmento('B000000001')}.json").read_text(encoding="utf-8"))
        self.assertEqual(h["B000000001"]["autor"], "Ana")

    def test_banco_antigo_sem_colunas_de_detalhe_ainda_vira_site(self):
        c = sqlite3.connect(self.d / "velho.db")
        c.executescript(
            "CREATE TABLE catalogo (asin TEXT PRIMARY KEY, titulo TEXT, formato TEXT, no TEXT, "
            "primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL);"
            "CREATE TABLE historico (id INTEGER PRIMARY KEY, asin TEXT, preco_centavos INTEGER, preco_capa_centavos INTEGER, "
            "desde TEXT, ate TEXT, vezes INTEGER DEFAULT 1);"
            "INSERT INTO catalogo VALUES ('B000000001','Velho','Capa comum','n','2026-10-01T12:00:00+00:00','2026-10-02T12:00:00+00:00');"
            "INSERT INTO historico (asin, preco_centavos, desde, ate) VALUES ('B000000001', 100, '2026-10-01T12:00:00+00:00', '2026-10-02T12:00:00+00:00');")
        c.commit()
        c.close()
        self.assertEqual(site.construir([self.d / "velho.db"], self.d / "out", Path(RAIZ) / "eventos.csv")["itens"], 1)

    def test_esconde_o_que_nao_foi_visto_depois_do_filtro_da_amazon(self):
        itens = [("B000000001", "Vendido pela Amazon", None, [("2026-10-01", "2026-10-20", 5000, None)]),
                 ("B000000002", "De vendedor de fora", None, [("2026-10-01", "2026-10-08", 3000, None)])]
        banco(self.d / "a.db", itens)
        c = sqlite3.connect(self.d / "a.db")
        c.execute("UPDATE catalogo SET ultimo_visto = '2026-10-08T12:00:00+00:00' WHERE asin = 'B000000002'")
        c.execute("INSERT INTO config VALUES ('so_amazon_desde', '2026-10-10T12:00:00+00:00')")
        c.commit()
        # antes de uma varredura completa com o filtro: nada é escondido
        site.construir([self.d / "a.db"], self.d / "s1")
        self.assertEqual(len(edicoes(self.d / "s1")), 2)
        c.execute("INSERT INTO dias VALUES ('vendidos', '2026-10-11', '2026-10-11T20:00:00+00:00')")
        c.commit()
        c.close()
        site.construir([self.d / "a.db"], self.d / "s2")
        self.assertEqual(list(edicoes(self.d / "s2")), ["B000000001"])
        h = json.loads((self.d / f"s2/dados/h/{site.fragmento('B000000002')}.json").read_text())
        self.assertIn("B000000002", h)                          # o histórico segue disponível (lista de desejos)

    def test_formatos_da_mesma_obra_viram_um_item(self):
        h = lambda p: [("2026-10-01", "2026-10-05", p, None)]
        banco(self.d / "a.db", [("B000000001", "Livro Um", "Kindle", h(1900)), ("B000000002", "Livro Um", "Capa comum", h(4000)),
                                ("B000000003", "Livro Um", "Capa dura", h(9000)), ("B000000004", "Outro", "Capa comum", h(3000)),
                                ("B000000005", "Agenda 2027", "Agenda ou Calendário", h(2000))])
        c = sqlite3.connect(self.d / "a.db")
        # a capa dura apareceu no card da capa comum, que apareceu no card do Kindle: tudo uma obra só
        c.execute("UPDATE catalogo SET obra='B000000001', autor='Ana' WHERE asin IN ('B000000001','B000000002')")
        c.execute("UPDATE catalogo SET obra='B000000002' WHERE asin='B000000003'")
        c.commit()
        c.close()
        meta = site.construir([self.d / "a.db"], self.d / "out")
        obras = indice(self.d / "out")[1]
        self.assertEqual((meta["itens"], meta["obras"]), (4, 2))       # a agenda não é livro
        um = next(o for o in obras if o[0] == "Livro Um")
        self.assertEqual([e[0] for e in um[8]], ["B000000002", "B000000003", "B000000001"])   # físicos primeiro, do mais barato
        self.assertEqual(um[1], "Ana")
        self.assertIn("B000000005", json.loads((self.d / f"out/dados/h/{site.fragmento('B000000005')}.json").read_text()))

    def test_preco_mais_comum_so_com_dias_suficientes(self):
        d = date(2026, 10, 1).toordinal()
        self.assertIsNone(site.mais_comum([[d, d + 12, 5000, None]], d + 12))          # 13 dias
        self.assertEqual(site.mais_comum([[d, d + 9, 5000, None], [d + 10, d + 13, 3000, None]], d + 13), 5000)
        velho = [[d, d + 99, 1000, None], [d + 100, d + 119, 2000, None]]
        self.assertEqual(site.mais_comum(velho, d + 119), 1000)                  # 70 dias a 1000 e 20 a 2000 na janela
        self.assertEqual(site.mais_comum(velho, d + 200), None)                  # nada nos últimos 90 dias

    def test_baixaram_de_preco(self):
        h = {"B000000001": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 4000, None)],   # -20%: entra
             "B000000002": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 4900, None)],   # -2%: não
             "B000000003": [("2026-10-01", "2026-10-03", 5000, None), ("2026-10-04", "2026-10-09", 3000, None)],   # caiu há dias
             "B000000004": [("2026-10-01", "2026-10-08", 3000, None), ("2026-10-09", "2026-10-09", 5000, None)],   # subiu
             "B000000005": [("2026-10-01", "2026-10-08", 5000, None), ("2026-10-09", "2026-10-09", 2500, None)]}   # -50%
        banco(self.d / "a.db", [(a, a, "Capa comum", t) for a, t in h.items()])
        site.construir([self.d / "a.db"], self.d / "out")
        baixa = json.loads((self.d / "out/dados/destaques.json").read_text())["baixa"]
        self.assertEqual(baixa, [["B000000005", 5000, date(2026, 10, 9).toordinal()], ["B000000001", 5000, date(2026, 10, 9).toordinal()]])

    def _detalhar(self, nome, sql, *args):
        c = sqlite3.connect(self.d / nome)
        c.execute(sql, args)
        c.commit()
        c.close()

    def test_partes_do_indice_vao_das_mais_avaliadas_para_as_menos(self):
        h = [("2026-10-01", "2026-10-05", 1000, None)]
        banco(self.d / "a.db", [(f"B00000000{i}", f"Livro {i}", "Capa comum", h) for i in range(1, 6)])
        for i, av in ((1, 10), (2, 5000), (3, None), (4, 300), (5, 90)):
            self._detalhar("a.db", "UPDATE catalogo SET avaliacoes = ?, nota = 45 WHERE asin = ?", av, f"B00000000{i}")
        with mock.patch.object(site, "PARTE_INICIAL", 2), mock.patch.object(site, "PARTE", 2):
            meta = site.construir([self.d / "a.db"], self.d / "out")
        p0, obras = indice(self.d / "out")
        self.assertEqual(p0["partes"], 3)
        self.assertEqual([o[0] for o in p0["o"]], ["Livro 2", "Livro 4"])
        self.assertEqual([o[0] for o in obras], ["Livro 2", "Livro 4", "Livro 5", "Livro 1", "Livro 3"])  # sem avaliações no fim
        self.assertEqual([o[6:8] for o in obras[:2]], [[45, 5000], [45, 300]])
        self.assertEqual(meta["itens"], 5)                       # conta todas as partes (a trava do site compara isto)
        self.assertNotIn("fmt", json.loads((self.d / "out/dados/indice-1.json").read_text()))   # tabelas só na parte 0

    def test_generos_vem_da_tabela_e_do_primeiro_no(self):
        h = [("2026-10-01", "2026-10-05", 1000, None)]
        banco(self.d / "a.db", [("B000000001", "Romance e fantasia", "Capa comum", h), ("B000000002", "Só no ranking", "Kindle", h)])
        self._detalhar("a.db", "UPDATE catalogo SET no = '7882388011' WHERE asin = 'B000000001'")
        self._detalhar("a.db", "UPDATE catalogo SET no = ? WHERE asin = 'B000000002'", varredura.NO_LIVROS)
        self._detalhar("a.db", "INSERT INTO generos VALUES ('B000000001', '7841775011')")
        site.construir([self.d / "a.db"], self.d / "out")
        p0, _ = indice(self.d / "out")
        ed = edicoes(self.d / "out")
        self.assertEqual(sorted(p0["gen"][g][1] for g in ed["B000000001"][0][5]), ["Fantasia, Horror e Ficção Científica", "Romance"])
        self.assertEqual(ed["B000000002"][0][5], [])
        self.assertEqual(historico(self.d / "out", "B000000001")["gen"],
                         [["7841775011", "Fantasia, Horror e Ficção Científica"], ["7882388011", "Romance"]])
        ngen = json.loads((self.d / "out/dados/destaques.json").read_text())["ngen"]
        self.assertEqual(ngen[[g[0] for g in p0["gen"]].index("7882388011")], 1)

    def test_some_da_busca_quem_nao_aparece_ha_duas_semanas(self):
        banco(self.d / "a.db", [("B000000001", "Atual", None, [("2026-10-01", "2026-10-20", 1000, None)]),
                                ("B000000002", "Sumiu", None, [("2026-10-01", "2026-10-06", 1000, None)]),
                                ("B000000003", "Quase", None, [("2026-10-01", "2026-10-07", 1000, None)])])
        site.construir([self.d / "a.db"], self.d / "out")
        self.assertEqual(sorted(edicoes(self.d / "out")), ["B000000001", "B000000003"])
        self.assertEqual(historico(self.d / "out", "B000000002")["h"][0][2], 1000)    # o histórico continua lá

    def test_formatos_e_outras_edicoes_vao_para_o_historico(self):
        h = lambda p: [("2026-10-01", "2026-10-05", p, None)]
        banco(self.d / "a.db", [("B000000001", "Dom Casmurro", "Capa comum", h(2000)), ("B000000002", "Dom Casmurro", "Kindle", h(500)),
                                ("B000000003", "Dom Casmurro: Edição comentada", "Capa dura", h(6000)),
                                ("B000000004", "Dom Casmurro (Volume 2)", "Capa comum", h(3000)),
                                ("B000000005", "Dom Casmurro", "Capa comum", h(1000))])
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'MACHADO DE ASSIS', obra = 'B000000001' WHERE asin IN ('B000000001', 'B000000002')")
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'Machado de Assis' WHERE asin IN ('B000000003', 'B000000004')")
        self._detalhar("a.db", "UPDATE catalogo SET autor = 'Não informado' WHERE asin = 'B000000005'")
        site.construir([self.d / "a.db"], self.d / "out")
        um = historico(self.d / "out", "B000000002")
        self.assertEqual(um["autor"], "Machado de Assis")                          # estava todo em maiúsculas
        self.assertEqual(um["eds"], [["B000000001", "Capa comum", 2000], ["B000000002", "Kindle", 500]])
        self.assertEqual(um["outras"], [["B000000003", "Dom Casmurro: Edição comentada", "", "Capa dura", 6000]])  # volume 2 e autor genérico, não
        self.assertNotIn("eds", historico(self.d / "out", "B000000003"))
        self.assertEqual(historico(self.d / "out", "B000000003")["outras"][0][0], "B000000001")

    def test_mais_do_mesmo_autor_vai_para_o_historico(self):
        h = [("2026-10-01", "2026-10-05", 1000, None)]
        livros = [(f"B00000000{i}", f"Livro {i}", "Capa comum", h) for i in range(1, 6)]
        banco(self.d / "a.db", livros)
        for asin, autor, av in (("B000000001", "Machado de Assis", 50), ("B000000002", "Machado de Assis, Fulano e outros.", 900),
                                ("B000000003", "MACHADO DE ASSIS", 10), ("B000000004", "Outra Pessoa", 5), ("B000000005", "Não informado", 1)):
            self._detalhar("a.db", "UPDATE catalogo SET autor = ?, avaliacoes = ? WHERE asin = ?", autor, av, asin)
        site.construir([self.d / "a.db"], self.d / "out")
        um = historico(self.d / "out", "B000000001")
        self.assertEqual(um["autor1"], "Machado de Assis")
        self.assertEqual([x[0] for x in um["mesmo_autor"]], ["B000000002", "B000000003"])   # mais avaliados primeiro
        self.assertNotIn("mesmo_autor", historico(self.d / "out", "B000000004"))
        self.assertNotIn("mesmo_autor", historico(self.d / "out", "B000000005"))             # autor genérico não junta

    def test_baixaram_de_preco_por_familia_e_menor_preco_registrado(self):
        h = lambda a, b: [("2026-09-20", "2026-10-08", a, None), ("2026-10-09", "2026-10-09", b, None)]
        banco(self.d / "a.db", [("B000000001", "Físico 1", "Capa comum", h(5000, 2500)), ("B000000002", "Físico 2", "Capa comum", h(5000, 4000)),
                                ("B000000003", "Kindle 1", "Kindle", h(5000, 500)), ("B000000004", "Kindle 2", "Kindle", h(5000, 1000)),
                                ("B000000005", "Parado", "Capa comum", [("2026-09-20", "2026-10-09", 3000, None)])])
        with mock.patch.object(site, "MAX_BAIXA", 1):
            site.construir([self.d / "a.db"], self.d / "out")
        d = json.loads((self.d / "out/dados/destaques.json").read_text())
        self.assertEqual([b[0] for b in d["baixa"]], ["B000000001", "B000000003"])          # a maior queda de cada família
        self.assertEqual(sorted(d["menor"]), ["B000000001", "B000000002", "B000000003", "B000000004"])   # o parado não
        self.assertEqual(sorted(e[0] for o in d["o"] for e in o[8]), ["B000000001", "B000000002", "B000000003", "B000000004"])
        self.assertEqual(edicoes(self.d / "out")["B000000001"][1][6], 2500)                  # menor preço registrado

    def test_nomes_e_titulos(self):
        self.assertEqual(site.nome_proprio("ELIO D'ANNA"), "Elio D'Anna")
        self.assertEqual(site.nome_proprio("FERNANDO J. DE LUCCA"), "Fernando J. de Lucca")
        self.assertEqual(site.nome_proprio("J.R.R. TOLKIEN"), "J.R.R. Tolkien")
        self.assertEqual(site.nome_proprio("bell hooks"), "bell hooks")                       # só mexe no que é todo maiúsculo
        self.assertEqual(site.nome_proprio("SUN TZU"), "Sun Tzu")
        self.assertEqual(site.limpar_titulo("Pride and Prejudice (English Edition)"), ("Pride and Prejudice", "Inglês"))
        self.assertEqual(site.limpar_titulo("Livro (Portuguese Edition)"), ("Livro", ""))
        self.assertEqual(site.limpar_titulo("Livro (Collector's Edition)"), ("Livro (Collector's Edition)", ""))
        self.assertEqual(site.titulo_base("Dom Casmurro: Edição comentada"), "dom casmurro")
        self.assertEqual(site.titulo_base("Metro: Level 3"), "metro: level 3")              # outro volume, não outra edição
        self.assertEqual(site.titulo_base("O Hobbit (Capa dura) - edição de luxo"), "o hobbit")

    def test_arquivos_do_app_levam_a_versao(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
        site.construir([self.d / "a.db"], self.d / "out")
        html = (self.d / "out/index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'src="app\.js\?v=[0-9a-f]{10}"')
        self.assertRegex(html, r'href="estilo\.css\?v=[0-9a-f]{10}"')

    def test_cli_site(self):
        banco(self.d / "a.db", [("B000000001", "Livro Um", None, [("2026-10-01", "2026-10-05", 5000, None)])])
        r = subprocess.run(["python", "-m", "comparador", "site", str(self.d / "a.db"), "--saida", str(self.d / "s")],
                           cwd=RAIZ, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 livros", r.stdout)

    @unittest.skipUnless(NODE, "node não instalado")
    def test_testes_da_lista_e_da_busca_em_javascript(self):
        for nome in ("lista.test.js", "busca.test.js"):
            r = subprocess.run([NODE, os.path.join(RAIZ, "tests", nome)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestIconesEManifesto(unittest.TestCase):
    """O app instalado precisa de ícone PNG (o iOS ignora SVG no apple-touch-icon) e de um maskable com folga."""

    def png(self, nome):
        dados = (site.WEB / nome).read_bytes()
        self.assertEqual(dados[:8], b"\x89PNG\r\n\x1a\n", nome)
        largura, altura, _, tipo = struct.unpack(">IIBB", dados[16:26])
        return largura, altura, tipo                                        # tipo: 2 = RGB (opaco), 6 = RGBA

    def test_tamanhos_e_transparencia_de_cada_icone(self):
        self.assertEqual(self.png("icone-180.png"), (180, 180, 2))            # apple-touch-icon: quadrado, sem transparência
        self.assertEqual(self.png("icone-192.png"), (192, 192, 6))
        self.assertEqual(self.png("icone-512.png"), (512, 512, 6))
        self.assertEqual(self.png("icone-maskable-512.png"), (512, 512, 2))   # maskable: o Android recorta; sem transparência

    def test_manifesto_lista_so_arquivos_que_existem_e_tem_um_maskable(self):
        m = json.loads((site.WEB / "manifest.json").read_text(encoding="utf-8"))
        for icone in m["icons"]:
            self.assertTrue((site.WEB / icone["src"]).exists(), icone["src"])
            if icone["type"] == "image/png":
                lado = int(icone["sizes"].split("x")[0])
                self.assertEqual(self.png(icone["src"])[:2], (lado, lado), icone["src"])
        self.assertIn("maskable", [i["purpose"] for i in m["icons"]])
        self.assertIn("any", [i["purpose"] for i in m["icons"] if i["type"] == "image/png"])
        self.assertEqual(m["theme_color"], m["background_color"])             # o HTML já usa a cor da página nos dois temas

    def test_site_gerado_leva_os_icones_e_o_apple_touch_icon_versionado(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            banco(d / "a.db", [("B000000001", "Livro", "Capa comum", [("2026-10-01", "2026-10-05", 5000, None)])])
            site.construir([d / "a.db"], d / "out", Path(RAIZ) / "eventos.csv")
            for nome in ("icone-180.png", "icone-192.png", "icone-512.png", "icone-maskable-512.png"):
                self.assertTrue((d / "out" / nome).exists(), nome)
            html = (d / "out" / "index.html").read_text(encoding="utf-8")
            self.assertRegex(html, r'rel="apple-touch-icon" href="icone-180\.png\?v=[0-9a-f]{10}"')


class TestFolhaDeEstilo(unittest.TestCase):
    """Regras da folha que quebrariam em silêncio: tokens, hover em tela de toque, área segura."""

    def setUp(self):
        self.css = (site.WEB / "estilo.css").read_text(encoding="utf-8")
        self.html = (site.WEB / "index.html").read_text(encoding="utf-8")
        self.claro = re.search(r":root\{(.*?)color-scheme", self.css, re.S).group(1)
        self.escuro = re.search(r"prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", self.css, re.S).group(1)

    @staticmethod
    def tokens(bloco):
        return set(re.findall(r"(--[a-z0-9]+):", bloco))

    def test_toda_cor_do_tema_claro_e_redefinida_no_escuro(self):
        cores = {t for t in self.tokens(self.claro) if not t.startswith(("--fs-", "--r")) and t not in ("--f", "--serif", "--display")}
        self.assertEqual(cores - self.tokens(self.escuro), set(), "token de cor sem versão escura")

    def test_todo_var_usado_existe_e_todo_token_definido_e_usado(self):
        usados = set(re.findall(r"var\((--[a-z0-9]+)\)", self.css))
        definidos = self.tokens(self.claro) | self.tokens(self.escuro)
        self.assertEqual(usados - definidos - {"--h"}, set(), "var() sem definição")               # --h vem inline, de app.js
        self.assertEqual(definidos - usados, set(), "token definido e nunca usado")

    def test_borda_de_campo_usa_o_token_proprio_e_nao_a_linha_decorativa(self):
        for seletor in (".busca input{", ".sel select{", ".faixa-preco input{", ".alvo-f input{"):
            regra = self.css[self.css.index(seletor):].split("}", 1)[0]
            self.assertIn("border:1px solid var(--ln3)", regra, seletor)

    def test_nenhum_hover_fora_do_media_de_ponteiro_com_hover(self):
        fora, nivel, i = [], 0, 0
        css = self.css
        while i < len(css):                                              # tira os blocos @media(hover:hover){...}, com chaves balanceadas
            if css.startswith("@media(hover:hover){", i):
                i = css.index("{", i)
                prof = 0
                while True:
                    prof += (css[i] == "{") - (css[i] == "}")
                    i += 1
                    if prof == 0:
                        break
                continue
            fora.append(css[i]); i += 1
        for regra in re.findall(r"(?:^|\})\s*([^{}@]*:hover[^{}]*)\{", "".join(fora)):
            self.fail(f"regra de :hover fora de @media(hover:hover): {regra.strip()}")
        self.assertIn("@media(hover:hover){", self.css)

    def test_tamanho_de_fonte_e_raio_vem_da_escala(self):
        sem_capa = "\n".join(l for l in self.css.splitlines() if ".cv.ph span" not in l and ".cv.p.ph span" not in l)
        self.assertEqual(re.findall(r"font-size:[\d.]+px", sem_capa), [], "font-size em px fora da escala (--fs-N)")
        self.assertEqual(re.findall(r"font:[^;}]*[\d.]px", sem_capa), [], "font: com px fora da escala (--fs-N)")
        raios = [r for r in re.findall(r"border-radius:\d+px(?=[;}])", self.css) if r != "border-radius:999px"]       # 999px = pílula
        self.assertEqual(raios, [], "raio em px fora dos tokens --r0..--r3")
        passos = self.re_tokens("--fs-")
        self.assertEqual(len(passos), 12)                                       # eram 27 tamanhos soltos
        self.assertEqual(passos, sorted(passos))                                # a escala só cresce

    def re_tokens(self, prefixo):
        return [int(v) for v in re.findall(prefixo + r"\d+:(\d+)px", self.claro)]

    def test_estilos_inline_dos_modelos_nao_escrevem_tamanho_de_fonte_em_px(self):
        for nome in ("app.js", "livro.js", "lista.js", "busca.js"):
            texto = (site.WEB / nome).read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"style=\\?[\"'][^\"']*font-size:\d+px", texto), [], nome)

    def test_botao_ao_lado_de_campo_tem_a_altura_do_campo_no_toque(self):
        toque = self.css[self.css.index("@media(pointer:coarse){"):].split("\n}", 1)[0]
        altura = lambda sel: re.search(re.escape(sel) + r"\{height:(\d+)px", toque).group(1)
        self.assertEqual(altura(".sel select,.faixa-preco input,.alvo-f input"), "44")
        self.assertEqual(altura(".lista-h .ctl .btn,.alvo-f .btn"), "44")

    def test_anel_do_link_so_some_onde_o_anel_da_linha_funciona(self):
        # sem :has, a regra da linha é descartada: se a que tira o anel do link valesse sozinha, o link ficaria sem foco visível
        self.assertIn("@supports selector(:has(*)){div.row:has(.esticar:focus-visible){", self.css)
        self.assertIn(".row .esticar:focus-visible{outline:none}}", self.css)

    def test_hover_de_campo_escurece_a_borda_em_vez_de_clarear(self):
        regra = re.search(r"\.sel select:hover[^{]*\{([^}]*)\}", self.css).group(1)
        self.assertEqual(regra, "border-color:var(--mu)")                     # --mu2 era mais claro que --ln3 no claro e igual a ele no escuro

    def test_contraste_dos_pares_de_texto_nos_dois_temas(self):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]

        def razao(a, b):
            a, b = lum(a), lum(b)
            return (max(a, b) + .05) / (min(a, b) + .05)

        def hexa(h):
            return "#" + "".join(ch * 2 for ch in h[1:]) if len(h) == 4 else h

        for nome, bloco in (("claro", self.claro), ("escuro", self.escuro)):
            t = {k: hexa(v) for k, v in re.findall(r"(--[a-z0-9]+):(#[0-9a-f]{3,6})(?=[;}])", bloco)}
            pares = [(f, b) for f in ("--fg", "--mu", "--ac", "--dn", "--up", "--wr", "--med") for b in ("--bg", "--sf", "--sf2")]
            pares += [("--dn", "--dns"), ("--up", "--ups"), ("--wr", "--wrs"), ("--ac", "--acs"), ("--prif", "--pri"), ("--tintaf", "--tinta"), ("--sf", "--ac")]                     # --sf sobre --ac: chip ligado e contador
            for f, b in pares:
                self.assertGreaterEqual(razao(t[f], t[b]), 4.5, f"{nome}: {f} sobre {b}")
            for b in ("--bg", "--sf"):                                            # contorno de campo: 3:1 (WCAG 1.4.11)
                self.assertGreaterEqual(razao(t["--ln3"], t[b]), 3, f"{nome}: --ln3 sobre {b}")

    def test_fontes_do_site_existem_sao_copiadas_e_trocam_sem_esperar(self):
        faces = re.findall(r"@font-face\{([^}]*)\}", self.css)
        self.assertEqual(len(faces), 4)
        for f in faces:
            arquivo = re.search(r"url\(([\w.-]+)\)", f).group(1)
            self.assertTrue((site.WEB / arquivo).exists(), arquivo)
            self.assertIn(arquivo, site.ARQUIVOS_WEB)
            self.assertIn("font-display:swap", f)
        self.assertIn("OFL.txt", site.ARQUIVOS_WEB)
        self.assertIn('href="cormorant-600.woff2" as="font" type="font/woff2" crossorigin', self.html)

    def test_area_segura_e_cobertura_nao_se_misturam(self):
        # viewport-fit=cover sem env(safe-area-inset-*) deixa o conteúdo sob o entalhe; sem o cover, o navegador cuida
        self.assertEqual("viewport-fit=cover" in self.html, "safe-area-inset" in self.css)


@unittest.skipUnless(navegador(), "navegador não instalado")
class TestSiteNoNavegador(unittest.TestCase):
    def _servir(self, itens, aviso=None, avaliacoes=None, generos=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        banco(d / "a.db", itens, aviso)
        if generos:
            c = sqlite3.connect(d / "a.db")
            c.executemany("INSERT INTO generos VALUES (?, ?)", list(generos.items()))
            c.commit()
            c.close()
        if avaliacoes:
            c = sqlite3.connect(d / "a.db")
            c.executemany("UPDATE catalogo SET avaliacoes = ? WHERE asin = ?", [(n, a) for a, n in avaliacoes.items()])
            c.execute("UPDATE catalogo SET obra = 'R000000001' WHERE asin LIKE 'R%'")
            c.commit()
            c.close()
        site.construir([d / "a.db"], d / "s", Path(RAIZ) / "eventos.csv")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d / "s")))
        srv.RequestHandlerClass.log_message = lambda *a, **k: None
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_filtros_e_ordenacao_da_busca(self):
        from playwright.sync_api import sync_playwright
        h = lambda p, c=None: [("2026-10-01", "2026-10-20", p, c)]
        base = self._servir([
            ("A000000001", "Alfa", "Capa comum", h(5000, 10000)),     # 50% de desconto
            ("A000000002", "Beta", "Kindle", h(1500)),
            ("A000000003", "Gama", "Capa dura", h(9000, 9500)),       # ~5%
            ("A000000004", "Delta", "Capa comum", h(3000)),
            ("A000000005", "Epsilon", "Audiolivro", h(2000, 4000))])  # 50%
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.clear()")
            pg.goto(f"{base}/?o=preco")                                                  # ordenar sozinho já lista tudo
            pg.wait_for_selector("#res .row")
            titulos = lambda: pg.eval_on_selector_all("#res .row .tt", "e => e.map(x => x.textContent)")
            esperar = lambda n: pg.wait_for_function(f"document.querySelectorAll('#res .row').length === {n}")
            self.assertEqual(titulos(), ["Beta", "Epsilon", "Delta", "Alfa", "Gama"])
            pg.select_option("#ord", "preco_desc")
            self.assertEqual(titulos(), ["Gama", "Alfa", "Delta", "Epsilon", "Beta"])
            pg.select_option("#ord", "desconto")
            self.assertEqual(titulos()[:2], ["Alfa", "Epsilon"])                         # 50% e 50%, empate por título
            pg.select_option("#ord", "titulo")
            self.assertEqual(titulos(), ["Alfa", "Beta", "Delta", "Epsilon", "Gama"])
            self.assertIn("3", pg.inner_text('[data-fam="f"]'))                          # contagem no filtro
            pg.click('[data-fam="f"]')                                                   # livro físico: capa comum e dura
            self.assertEqual(titulos(), ["Alfa", "Delta", "Gama"])
            self.assertIn("f=f", pg.url)
            pg.reload()                                                                  # filtros ficam no endereço
            pg.wait_for_selector("#res .row")
            self.assertEqual(titulos(), ["Alfa", "Delta", "Gama"])
            pg.click('[data-acao="limpar-filtros"]')
            esperar(5)
            pg.click('[data-acao="preco"]')
            pg.fill("#de", "20")
            pg.fill("#ate", "50")
            esperar(3)
            self.assertEqual(titulos(), ["Alfa", "Delta", "Epsilon"])                    # R$ 20 a R$ 50
            pg.fill("#q", "ep")
            esperar(1)
            self.assertEqual(titulos(), ["Epsilon"])
            pg.click("#res .row")
            pg.wait_for_selector("[data-salvar]")
            pg.click("[data-salvar]")
            self.assertEqual(pg.inner_text("#cont"), "1")
            pg.go_back()                                                                 # volta para a mesma busca
            pg.wait_for_selector("#res .row")
            self.assertEqual(titulos(), ["Epsilon"])
            self.assertEqual(pg.input_value("#q"), "ep")
            self.assertEqual(pg.locator("#res .salvo").count(), 1)
            b.close()
        self.assertEqual(erros, [])

    def test_livro_sem_coleta_recente_continua_na_lista(self):
        from playwright.sync_api import sync_playwright
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        banco(d / "a.db", [("A000000001", "Vendido pela Amazon", None, [("2026-10-01", "2026-10-20", 5000, None)]),
                           ("A000000002", "Saiu da Amazon", None, [("2026-10-01", "2026-10-05", 3000, None)])])
        c = sqlite3.connect(d / "a.db")
        c.execute("UPDATE catalogo SET ultimo_visto = '2026-10-05T12:00:00+00:00' WHERE asin = 'A000000002'")
        c.execute("INSERT INTO config VALUES ('so_amazon_desde', '2026-10-10T12:00:00+00:00')")
        c.execute("INSERT INTO dias VALUES ('vendidos', '2026-10-11', '2026-10-11T20:00:00+00:00')")
        c.commit()
        c.close()
        site.construir([d / "a.db"], d / "s")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d / "s")))
        srv.RequestHandlerClass.log_message = lambda *a, **k: None
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_port}"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.setItem('lista_v1', JSON.stringify(['A000000002']))")
            pg.goto(f"{base}/?q=saiu")
            pg.wait_for_function("document.querySelector('#res').textContent.includes('Nenhum livro')")  # sumiu da busca
            pg.click(".hdr-lista")
            pg.wait_for_selector("#lst .row b")
            self.assertIn("último preço visto em 05/10/2026", pg.inner_text("#lst"))      # mas segue na lista, com o último preço
            self.assertIn("R$ 30,00", pg.inner_text("#lst"))
            b.close()

    def test_indice_em_partes_busca_sem_dizer_que_nao_achou_antes_da_hora(self):
        from playwright.sync_api import sync_playwright
        h = lambda p: [("2026-10-01", "2026-10-20", p, None)]
        itens = [(f"P00000000{i}", f"Popular {i}", "Capa comum", h(1000 + i)) for i in range(1, 6)]
        itens += [("R000000001", "Raridade escondida", "Capa comum", h(3000)), ("R000000002", "Raridade escondida", "Kindle", h(900))]
        with mock.patch.object(site, "PARTE_INICIAL", 2), mock.patch.object(site, "PARTE", 2):   # 3 partes, a raridade na última
            base = self._servir(itens, avaliacoes={f"P00000000{i}": 1000 - i for i in range(1, 6)})
        self.assertTrue(base)
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros, presos, pedidos = [], [], []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("request", lambda r: pedidos.append(r.url))
            pg.route("**/dados/indice-2.json*", lambda route: presos.append(route))      # a última parte demora
            pg.goto(f"{base}/?q=raridade")
            pg.wait_for_selector("#res .carregando")
            self.assertNotIn("Nenhum livro", pg.inner_text("#res"))
            pg.fill("#q", "popular")                                                    # o que já chegou aparece logo
            pg.wait_for_function("document.querySelectorAll('#res .row').length === 4")
            self.assertIn("4 livros até agora", pg.inner_text("#ferr"))
            pg.fill("#q", "raridade")
            pg.wait_for_function("location.search.includes('raridade') && document.querySelector('#res .carregando')"
                                 " && !document.querySelector('#res .row')")
            self.assertNotIn("Nenhum livro", pg.inner_text("#res"))
            pg.click('[data-acao="preco"]')                                            # a pessoa está digitando um preço...
            pg.fill("#de", "5")
            presos[0].continue_()                                                       # ...quando chega a última parte
            pg.wait_for_function("document.querySelector('#res').textContent.includes('Raridade escondida')")
            self.assertEqual(pg.evaluate("document.activeElement.id"), "de")            # o campo não foi refeito
            self.assertEqual(pg.input_value("#de"), "5")
            pg.click('[data-acao="limpar-filtros"]')
            self.assertEqual(pg.locator("#res .carregando").count(), 0)
            pg.fill("#q", "xyzw")
            pg.wait_for_selector("#res .vazio")                                         # agora sim: nada encontrado
            # a página de um livro não baixa o índice: formatos vêm do histórico do próprio livro
            pg2 = b.new_page()
            pedidos2 = []
            pg2.on("request", lambda r: pedidos2.append(r.url))
            pg2.goto(f"{base}/?livro=R000000002")
            pg2.wait_for_selector("#graf svg")
            self.assertEqual(pg2.locator("#fmts .fmt").count(), 2)
            self.assertIn("R$ 30,00", pg2.inner_text("#fmts"))
            self.assertFalse([u for u in pedidos2 if "indice-" in u], pedidos2)
            b.close()
        self.assertEqual(erros, [])

    def test_estante_no_computador_tem_ver_todos_quando_esconde_livros(self):
        from playwright.sync_api import sync_playwright
        h = lambda a, b: [("2026-10-01", "2026-10-08", a, None), ("2026-10-09", "2026-10-09", b, None)]
        base = self._servir([(f"A0000000{i:02d}", f"Livro {i}", "Capa comum", h(5000, 3000 + i)) for i in range(10)])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            for largura, esperado in ((1280, True), (390, False)):
                pg = b.new_page(viewport={"width": largura, "height": 900})
                pg.goto(f"{base}/")
                pg.wait_for_selector("#baixa .cartao")
                pg.wait_for_timeout(200)
                visiveis = pg.eval_on_selector_all("#baixa .cartao", "e => e.filter(c => !c.inert).length")
                botao = pg.locator('#baixa [data-acao="abrir-estante"]')
                self.assertEqual(botao.count() == 1, esperado, largura)
                if esperado:
                    self.assertLess(visiveis, 10)                                       # uma fileira só...
                    botao.click()                                                       # ...e "Ver todos" mostra o resto
                    self.assertEqual(pg.eval_on_selector_all("#baixa .grade .cartao", "e => e.filter(c => !c.inert).length"), 10)
                else:
                    self.assertEqual(visiveis, 10)                                      # no celular a estante rola
                pg.close()
            b.close()

    def test_pagina_como_funciona_mostra_ate_quando_os_precos_foram_lidos_e_o_preco_do_dia(self):
        from playwright.sync_api import sync_playwright
        base = self._servir([("A000000001", "Livro", "Capa comum", [("2026-10-01", "2026-10-09", 5000, None)])])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/?sobre")
            pg.wait_for_selector(".prosa h1")
            texto = pg.inner_text(".prosa")
            self.assertRegex(texto, r"preços lidos até 09/10 às 09:00")          # 12:00 UTC, no horário de Brasília
            self.assertIn("Preço de cada dia", texto)
            self.assertEqual(erros, [])
            b.close()

    def test_genero_vistos_recentemente_e_preco_alvo(self):
        from playwright.sync_api import sync_playwright
        h = lambda p: [("2026-10-01", "2026-10-20", p, None)]
        base = self._servir([("A000000001", "Romance Um", "Capa comum", h(4000)), ("A000000002", "Romance Dois", "Capa comum", h(2500)),
                             ("A000000003", "Outro Gênero", "Kindle", h(900))], generos={"A000000001": "7882388011", "A000000002": "7882388011"})
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.clear()")
            pg.goto(f"{base}/")
            pg.click(".gens a:has-text('Romance')")                                      # explorar um gênero
            pg.wait_for_selector("#res .row")
            self.assertEqual(pg.inner_text("#bh"), "Romance")
            self.assertEqual(sorted(pg.eval_on_selector_all("#res .tt", "e => e.map(x => x.textContent)")), ["Romance Dois", "Romance Um"])
            pg.click("#res .row:has-text('Romance Um')")
            pg.wait_for_selector("#graf svg")
            self.assertIn("Romance", pg.inner_text(".l-gens"))
            pg.click("[data-salvar]")
            pg.goto(f"{base}/")                                                         # vistos recentemente, no início
            pg.wait_for_selector(".cartao")
            self.assertIn("Vistos recentemente", pg.inner_text("main"))
            pg.goto(f"{base}/?lista")                                                   # preço-alvo na lista
            pg.wait_for_selector("#lst .row b")
            pg.click("[data-alvo]")
            pg.fill(".alvo-f input", "35")
            pg.click(".alvo-f [type=submit]")
            pg.wait_for_selector(".alvo .mu")
            self.assertIn("Seu preço: R$ 35,00", pg.inner_text("#lst"))
            self.assertIn("faltam R$ 5,00", pg.inner_text("#lst"))
            pg.click("[data-alvo]")
            pg.fill(".alvo-f input", "40")
            pg.press(".alvo-f input", "Enter")
            pg.wait_for_selector(".alvo .pill.dn")
            self.assertIn("chegou no seu preço", pg.inner_text(".resumo"))
            b.close()
        self.assertEqual(erros, [])

    def test_buscar_salvar_na_lista_e_abrir_historico(self):
        from playwright.sync_api import sync_playwright
        base = self._servir([("8535902775", "A paciente silenciosa", "Capa comum", [("2026-10-01", "2026-10-20", 3499, 6490)]),
                             ("B0ABCDEFGH", "Outro livro", "Kindle", [("2026-10-01", "2026-10-20", 1999, None)])])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/index.html")
            pg.wait_for_selector(".boas h1")
            pg.fill("#q", "silenciósa PACIENTE")                                         # sem acento e ordem trocada também acha
            pg.wait_for_selector("#res .row")
            self.assertIn("A paciente silenciosa", pg.inner_text("#res"))
            self.assertNotIn("Outro livro", pg.inner_text("#res"))
            pg.click("#res .row")
            pg.wait_for_selector("#graf svg")
            self.assertIn("A paciente silenciosa", pg.inner_text("h1"))
            self.assertIn("R$ 34,99", pg.inner_text(".preco-g"))
            pg.click("[data-salvar]")
            self.assertEqual(pg.get_attribute("[data-salvar]", "aria-pressed"), "true")
            pg.click(".hdr-lista")
            pg.wait_for_selector("#lst .row b")
            self.assertIn("R$ 34,99", pg.inner_text("#lst"))
            self.assertEqual(pg.inner_text("#cont"), "1")
            pg.click("#lst .tt")
            pg.wait_for_selector("#graf svg")
            pg.goto(f"{base}/?q=978-85-359-0277-8")
            pg.wait_for_selector("#res .row")
            self.assertIn("A paciente silenciosa", pg.inner_text("#res"))
            pg.goto(f"{base}/livro.html?asin=8535902775")                                # endereço antigo ainda funciona
            pg.wait_for_selector("#graf svg")
            self.assertIn("livro=8535902775", pg.url)
            pg.goto(f"{base}/?livro=ZZZZZZZZZZ")
            pg.wait_for_selector(".vazio h1")
            self.assertIn("Livro não encontrado", pg.inner_text("main"))
            b.close()
        self.assertEqual(erros, [])

    def test_teclado_e_leitor_de_tela(self):
        from playwright.sync_api import sync_playwright
        base = self._servir([("8535902775", "A paciente silenciosa", "Capa comum",
                              [("2026-09-01", "2026-09-20", 3999, 6490), ("2026-09-21", "2026-10-20", 3499, 6490)]),
                             ("B0ABCDEFGH", "Outro livro", "Kindle", [("2026-10-01", "2026-10-20", 1999, None)])])
        ativo = "(() => { const a = document.activeElement; return a.id || a.className || a.tagName; })()"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"])
            pg = b.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{base}/")
            pg.evaluate("localStorage.clear()")
            pg.goto(f"{base}/")
            pg.wait_for_selector(".boas h1")
            pg.keyboard.press("Tab")                                                     # o primeiro Tab chega no link de pular
            self.assertEqual(pg.evaluate(ativo), "pular")
            pg.keyboard.press("Enter")
            self.assertEqual(pg.evaluate("document.activeElement.textContent"), pg.inner_text(".boas h1"))
            pg.fill("#q", "paciente")                                                    # digitar não tira o foco do campo
            pg.wait_for_selector("#res .row")
            self.assertEqual(pg.evaluate(ativo), "q")
            pg.wait_for_function("document.querySelector('#cont-res').textContent === '1 livro encontrado'")
            pg.focus("[data-fam=k]")                                                     # o chip recriado pela barra mantém o foco
            pg.keyboard.press("Enter")
            pg.wait_for_selector("[data-fam=k][aria-pressed=true]")
            self.assertEqual(pg.evaluate("document.activeElement.dataset.fam"), "k")
            pg.keyboard.press("Enter")
            pg.click("#res .row")                                                        # trocar de tela leva o foco ao título
            pg.wait_for_selector("#graf svg")
            pg.wait_for_function("document.activeElement.matches('.livro[role=region]')")    # a região do livro, nomeada pelo h1
            self.assertIn("paciente", pg.evaluate("document.getElementById(document.activeElement.getAttribute('aria-labelledby')).textContent"))
            pg.keyboard.press("Tab")                                                     # o Tab seguinte chega na ação principal
            self.assertIn("Ver na Amazon", pg.evaluate("document.activeElement.textContent"))
            self.assertIn("menor R$ 34,99", pg.get_attribute("#graf svg", "aria-label"))   # resumo do gráfico em texto
            pg.focus("#graf .graf")                                                      # gráfico pelo teclado
            pg.keyboard.press("End")
            self.assertFalse(pg.is_hidden("#graf .tip"))
            self.assertIn("R$ 34,99", pg.inner_text("#graf .tip"))
            pg.keyboard.press("Home")
            self.assertIn("R$ 39,99", pg.inner_text("#graf [aria-live]"))
            pg.click("[data-salvar]")                                                    # aviso rápido fecha com Esc
            pg.wait_for_selector("#toast.on")
            pg.keyboard.press("Escape")
            pg.wait_for_selector("#toast:not(.on)", state="attached")
            pg.goto(f"{base}/?lista")                                                    # preço-alvo inválido não apaga o alvo
            pg.wait_for_selector("#lst .row b")
            pg.click("[data-alvo]")
            pg.fill(".alvo-f input", "30")
            pg.press(".alvo-f input", "Enter")
            pg.wait_for_selector(".alvo .mu")
            self.assertEqual(pg.evaluate("document.activeElement.dataset.alvo"), "8535902775")   # o foco volta ao botão
            pg.click("[data-alvo]")
            pg.fill(".alvo-f input", "0")
            pg.press(".alvo-f input", "Enter")
            pg.wait_for_selector(".erro-campo")
            self.assertEqual(pg.get_attribute(".alvo-f input", "aria-invalid"), "true")
            self.assertEqual(pg.get_attribute(".erro-campo", "role"), "alert")             # o erro é anunciado
            pg.goto(f"{base}/?lista")
            pg.wait_for_selector("#lst .row b")
            self.assertIn("Seu preço: R$ 30,00", pg.inner_text("#lst"))
            pg.evaluate("localStorage.setItem('lista_v1', JSON.stringify(['8535902775', 'B0ABCDEFGH']))")
            pg.goto(f"{base}/?lista")                                                    # remover leva o foco à linha vizinha
            pg.wait_for_selector("#lst [data-remover='8535902775']")
            pg.focus("[data-remover='8535902775']")
            pg.keyboard.press("Enter")
            pg.wait_for_function("document.activeElement.dataset.remover === 'B0ABCDEFGH'")
            pg.keyboard.press("Control+z")                                               # Ctrl+Z desfaz sem ir até o aviso
            pg.wait_for_function("document.querySelectorAll('#lst [data-remover]').length === 2")
            pg.wait_for_function("document.activeElement.dataset.remover === '8535902775'")
            pg.goto(f"{base}/?lista=,")                                                  # link de lista sem livros
            pg.wait_for_selector(".vazio h1")
            self.assertIn("Lista não encontrada", pg.inner_text("main"))
            b.close()
        self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main()
