"""Testes da varredura por páginas de busca. Rodar: python -m unittest discover -s tests

Fixtures REAIS (out/2026, trechos de páginas de busca da categoria HQs e Mangás):
`busca_fatia.html`, `busca_formatos.html` e `busca_fim.html` (última página, vazia).
"""

import re
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from comparador import db, varredura
from comparador.busca import ItemBusca, LayoutDesconhecido, parse_busca, url_busca
from comparador.ritmo import PPM_RECUO, Ritmo

# Os testes de mecanismo usam 3 faixas largas; as faixas de produção têm o seu próprio teste.
FAIXAS_PRODUCAO = list(varredura.FAIXAS_VENDIDOS)
FAIXAS_TESTE = [(0, 3999), (4000, 7999), (8000, varredura.SEM_TETO)]

FIXTURES = Path(__file__).with_name("fixtures")
ler = lambda nome: (FIXTURES / nome).read_text(encoding="utf-8")  # noqa: E731


class TestParseBusca(unittest.TestCase):
    def test_formatos_separados_e_parcelas_ignoradas(self):
        p = parse_busca(ler("busca_formatos.html"))
        itens = {i.asin: i for i in p.itens}
        self.assertEqual((p.cards, p.total, p.total_exato, p.ultima_pagina), (3, 70000, False, 400))
        # Mesmo card: capa comum e Kindle com ASINs e preços próprios.
        self.assertEqual((itens["8577870405"].formato, itens["8577870405"].preco_centavos,
                          itens["8577870405"].preco_capa_centavos), ("Capa comum", 2750, 4390))
        self.assertEqual((itens["B07TZNQB5S"].formato, itens["B07TZNQB5S"].preco_centavos,
                          itens["B07TZNQB5S"].preco_capa_centavos), ("Kindle", 1290, None))
        # "em até 2x de R$ 21,73" não vira preço nem preço de capa.
        self.assertEqual((itens["8577876853"].preco_centavos, itens["8577876853"].preco_capa_centavos), (4346, 6990))

    def test_autor_capa_data_idioma_e_obra(self):
        itens = {i.asin: i for i in parse_busca(ler("busca_formatos.html")).itens}
        fisico, kindle = itens["8577870405"], itens["B07TZNQB5S"]
        self.assertEqual((fisico.autor, fisico.imagem, fisico.publicado, fisico.idioma),
                         ("Yoshihiro Togashi", "61NPpt5HC6L", "2024-08-05", "Português"))
        self.assertEqual((kindle.obra, fisico.obra), ("8577870405", "8577870405"))   # mesmo card = mesma obra
        self.assertEqual(itens["8577876853"].autor, "Tsugumi Ohba e Takeshi Obata")
        outros = {i.asin: i for i in parse_busca(ler("busca_fatia.html")).itens}
        self.assertEqual(outros["B0GRJPWPF2"].autor, "Corbeyran, Roy Allan Martinez, e outros.")
        self.assertEqual((outros["B0GRJPWPF2"].publicado, outros["B0GRJPWPF2"].idioma), ("2026-04-16", None))
        self.assertEqual(outros["658991284X"].obra, "B09HNF5J57")       # o card é do Kindle; a capa dura é a mesma obra

    def test_nota_e_avaliacoes_valem_para_todos_os_formatos_do_card(self):
        itens = {i.asin: i for i in parse_busca(ler("busca_formatos.html")).itens}
        self.assertEqual((itens["8577870405"].nota, itens["8577870405"].avaliacoes), (49, 2713))
        self.assertEqual((itens["B07TZNQB5S"].nota, itens["B07TZNQB5S"].avaliacoes), (49, 2713))   # Kindle do mesmo card
        outros = {i.asin: i for i in parse_busca(ler("busca_fatia.html")).itens}
        self.assertEqual((outros["658991284X"].nota, outros["658991284X"].avaliacoes), (46, 1801))  # "1.801"
        self.assertEqual((outros["B0GRJPWPF2"].nota, outros["B0GRJPWPF2"].avaliacoes), (48, 75))

    def test_card_sem_avaliacoes(self):
        html = ler("busca_formatos.html")
        sem = re.sub(r'aria-label="[\d.,]+ (de 5 estrelas[^"]*|classificaç[^"]*)"', 'aria-label="x"', html)
        item = parse_busca(sem).itens[0]
        self.assertEqual((item.nota, item.avaliacoes), (None, None))

    def test_card_do_kindle_com_fisico_secundario_e_kindle_unlimited(self):
        itens = {i.asin: i for i in parse_busca(ler("busca_fatia.html")).itens}
        # Card B09HNF5J57 é do Kindle (R$ 0,00 = Kindle Unlimited, descartado); o físico vale.
        self.assertNotIn("B09HNF5J57", itens)
        self.assertEqual((itens["658991284X"].formato, itens["658991284X"].preco_centavos), ("Capa dura", 5508))
        # Card 6555946806: capa comum sem preço ("Ver opções"), só o Kindle tem preço.
        self.assertNotIn("6555946806", itens)
        self.assertEqual(itens["B0GGDSD6DH"].preco_centavos, 1490)
        self.assertEqual(itens["6554482016"].preco_capa_centavos, 11490)

    def test_rotulos_de_formato(self):
        from comparador.busca import _formato
        self.assertEqual(_formato("Capa Comum"), "Capa comum")
        self.assertEqual(_formato("Canoa, Grampeado ou Costurado"), "Canoa, Grampeado ou Costurado")
        for nao in ("(463)", "Ver opções", "Mais opções de compra", "Menor preço em 365 dias", ""):
            self.assertIsNone(_formato(nao), nao)
        self.assertIsNone(_formato("Nana", titulo="Nana"))

    def test_ultima_pagina_vazia(self):
        p = parse_busca(ler("busca_fim.html"))
        self.assertEqual((p.cards, p.itens), (0, []))

    def test_fatia_vazia_nao_e_erro(self):
        p = parse_busca(ler("busca_vazia.html"))  # real: filtro sem nenhum resultado
        self.assertEqual((p.cards, p.itens), (0, []))

    def test_vitrine_sem_resultados_e_layout_desconhecido(self):
        with self.assertRaises(LayoutDesconhecido):
            parse_busca("<html><title>Livros de HQs</title><body><div>vitrine</div></body></html>")

    def test_patrocinado_ignorado(self):
        html = pagina_busca([("AAAAAAAAAA", 1000)], ultima=1, total=1, patrocinado=True)
        self.assertEqual(parse_busca(html).cards, 0)

    def test_livros_sem_preco_nao_entram_nem_contam(self):
        p = parse_busca(pagina_busca([("AAAAAAAAAA", 1000), ("BBBBBBBBBB", None), ("CCCCCCCCCC", 0), ("DDDDDDDDDD", 2500)],
                                     ultima=1, total=4))
        self.assertEqual(p.cards, 4)
        self.assertEqual(p.livros, 2)                       # sem preço e Kindle Unlimited (R$ 0,00) ficam de fora
        self.assertEqual({i.asin for i in p.itens}, {"AAAAAAAAAA", "DDDDDDDDDD"})

    def test_url_mais_vendidos(self):
        self.assertEqual(url_busca("6740748011", 4000, 7999, 2, "vendidos"),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A6740748011%2Cp_36%3A4000-7999"
                         "%2Cp_6%3AA1ZZFT5FULY4LN&s=exact-aware-popularity-rank&page=2")
        self.assertEqual(url_busca("6740748011", 0, 99_999_999, 2, "vendidos"),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A6740748011%2Cp_6%3AA1ZZFT5FULY4LN"
                         "&s=exact-aware-popularity-rank&page=2")
        self.assertEqual(url_busca("6740748011", 0, 99_999_999, 2, "vendidos", so_amazon=False),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A6740748011&s=exact-aware-popularity-rank&page=2")

    def test_url_da_fatia(self):
        self.assertEqual(url_busca("7842710011", 2000, 2499, 3),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A7842710011%2Cp_36%3A2000-2499%2Cp_6%3AA1ZZFT5FULY4LN"
                         "&s=price-asc-rank&page=3")


def card(asin, preco, patrocinado=False, detalhes=True):
    """`preco=None`: livro sem preço de compra (indisponível); 0: Kindle Unlimited (R$ 0,00).
    `detalhes`: capa e autor como no layout real; sem eles, como se o layout tivesse mudado."""
    reais, cent = divmod(preco or 0, 100)
    link_preco = "" if preco is None else (
        f'<a href="/x/dp/{asin}/ref=sr"><span class="a-price" data-a-color="base">'
        f'<span class="a-offscreen">R$&nbsp;{reais},{cent:02d}</span></span></a>')
    titulo = f"<h2><span>Livro {asin}</span></h2>"
    if detalhes:
        titulo = (f'<img class="s-image" src="https://m.media-amazon.com/images/I/C{asin}._AC_UY218_.jpg">'
                  f'<div class="s-title-instructions-style">{titulo}'
                  f'<div class="a-row a-color-secondary"><span>por Autor {asin}</span></div></div>')
    return f"""<div data-component-type="s-search-result" data-asin="{asin}">
      {'<span class="puis-sponsored-label-text">Patrocinado</span>' if patrocinado else ''}
      {titulo}
      <a href="/x/dp/{asin}/ref=sr">Capa Comum</a>
      {link_preco}</div>"""


def pagina_busca(itens, *, ultima, total, primeiro=1, patrocinado=False, detalhes=True):
    paginacao = "".join(f'<span class="s-pagination-item">{n}</span>' for n in range(1, (ultima or 0) + 1))
    return f"""<html><title>Amazon.com.br</title><body>
      <div data-component-type="s-result-info-bar"><h2>{primeiro}-{primeiro + len(itens) - 1} de
        {total} resultados</h2></div>
      {''.join(card(a, p, patrocinado, detalhes) for a, p in itens)}
      <span class="s-pagination-strip">{paginacao}</span></body></html>"""


class Resposta:
    def __init__(self, texto, status=200):
        self.text, self.status_code, self.url = texto, status, ""


class AmazonFalsa:
    """Simula a busca: filtro p_36 (centavos, inclusive), ordem por preço, 16 por página,
    no máximo 400 páginas, e a página 400 vem incompleta como na real."""

    POR_PAGINA = 16
    detalhes = True     # False: cards sem capa e sem autor (layout mudou)

    def __init__(self, precos: dict[str, int], falhas: list[Resposta] | None = None):
        self.precos, self.falhas, self.chamadas = precos, list(falhas or []), []

    def get(self, url, **kw):
        self.chamadas.append(url)
        if self.falhas:
            return self.falhas.pop(0)
        q = parse_qs(urlparse(url).query)
        if q["s"][0] == "exact-aware-popularity-rank":
            return self.mais_vendidos(q)
        lo, hi = map(int, re.search(r"p_36:(\d+)-(\d+)", unquote(q["rh"][0])).groups())
        pag = int(q["page"][0])
        itens = sorted(((p, a) for a, p in self.precos.items() if lo <= p <= hi))
        ultima = min(400, -(-len(itens) // self.POR_PAGINA))
        ini = (pag - 1) * self.POR_PAGINA
        fatia = itens[ini:ini + self.POR_PAGINA] if pag <= ultima else []
        if pag == 400:
            fatia = fatia[:6]
        return Resposta(pagina_busca([(a, p) for p, a in fatia], ultima=ultima, total=len(itens), primeiro=ini + 1,
                                     detalhes=self.detalhes))


class AmazonFalsaVendidos(AmazonFalsa):
    """Ordem "mais vendidos": por nó, na ordem dada, filtrado pela faixa p_36 se houver (livro
    sem preço não passa no filtro de preço); só 75 páginas (por faixa), mas anuncia 400."""

    def __init__(self, por_no: dict[str, list[tuple[str, int]]], falhas=None):
        super().__init__({}, falhas)
        self.por_no = por_no

    def mais_vendidos(self, q):
        rh = unquote(q["rh"][0])
        no = re.search(r"n:(\d+)", rh).group(1)
        faixa = re.search(r"p_36:(\d+)-(\d+)", rh)
        lo, hi = map(int, faixa.groups()) if faixa else (0, 10**12)
        lista = [(a, p) for a, p in self.por_no.get(no, []) if (p is None and not faixa) or (p is not None and lo <= p <= hi)]
        pag = int(q["page"][0])
        ini = (pag - 1) * self.POR_PAGINA
        itens = lista[ini:ini + self.POR_PAGINA] if pag <= 75 else []
        return Resposta(pagina_busca(itens, ultima=400, total=90000, primeiro=ini + 1, detalhes=self.detalhes))


class TestVarredura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.conectar(Path(self.tmp.name) / "c.db")
        self.addCleanup(self.conn.close)
        varredura.criar_schema(self.conn)

    def varrer(self, amazon, **kw):
        kw.setdefault("minutos", 10_000)
        eid = varredura.varrer(self.conn, amazon, no="1", dormir=lambda s: None, **kw)
        if eid is None:
            return None
        return self.conn.execute("SELECT * FROM execucoes WHERE id = ?", (eid,)).fetchone()

    def para_ontem(self, *colunas):
        """Simula que o que foi feito hoje aconteceu ontem."""
        ontem = (datetime.fromisoformat(varredura.inicio_do_dia()) - timedelta(hours=1)).isoformat(timespec="seconds")
        for c in colunas:
            self.conn.execute(f"UPDATE fatias SET {c} = ? WHERE {c} IS NOT NULL", (ontem,))
        self.conn.execute("UPDATE execucoes SET iniciada_em = ?", (ontem,))
        self.conn.execute("UPDATE dias SET dia = ?", (db.dia_brasil(ontem).isoformat(),))
        self.conn.commit()

    def vistos(self):
        return {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}

    def test_cobre_tudo_dividindo_fatias_grandes(self):
        # 3.000 itens a R$ 29,90 (preço único, 188 páginas: não dá para dividir) +
        # 2.500 espalhados entre R$ 20 e R$ 25 (157 páginas: precisa dividir).
        precos = {f"U{i:09d}": 2990 for i in range(3000)}
        precos |= {f"E{i:09d}": 2000 + (i * 7) % 500 for i in range(2500)}
        precos["CARO000001"] = 1_500_000  # R$ 15.000: cai na última fatia
        e = self.varrer(AmazonFalsa(precos))
        self.assertEqual(self.vistos(), set(precos))
        self.assertIn("dia completo", e["observacao"])
        self.assertIsNone(self.varrer(AmazonFalsa(precos)))  # mesmo dia: nada a fazer
        self.assertTrue(varredura.cobertura(self.conn, "1").dia_completo)
        self.assertIn("preço único", e["observacao"])
        grandes = self.conn.execute(
            "SELECT COUNT(*) FROM fatias WHERE ativa = 1 AND paginas > ? AND preco_min < preco_max",
            (varredura.MAX_PAGINAS_FATIA,)).fetchone()[0]
        self.assertEqual(grandes, 0)

    def test_retoma_de_onde_parou(self):
        precos = {f"A{i:09d}": 2000 + i for i in range(100)}  # 7 páginas numa fatia
        amazon = AmazonFalsa(precos)
        self.varrer(amazon, max_paginas=6)  # 3 fatias vazias (R$ 0–20) + 3 páginas
        self.assertEqual(len(self.vistos()), 48)
        self.varrer(amazon)
        self.assertEqual(self.vistos(), set(precos))
        # Nenhuma página foi lida duas vezes na mesma passada.
        paginas = [u for u in amazon.chamadas if "p_36%3A2000-2499" in u]
        self.assertEqual(len(paginas), len(set(paginas)))

    def test_bloqueio_repete_a_pagina_e_para_depois_de_3(self):
        cachorros = Resposta("<html><head><title>Amazon.com.br Algo deu errado</title></head></html>", 503)
        amazon = AmazonFalsa({"A000000001": 1000}, falhas=[cachorros] * 3)
        e = self.varrer(amazon)
        self.assertEqual((e["bloqueios"], e["paginas"]), (3, 0))
        self.assertIn("3 falhas seguidas", e["observacao"])
        self.assertEqual(len(set(amazon.chamadas)), 1)  # sempre a mesma página
        e = self.varrer(amazon)  # depois do bloqueio, segue normal
        self.assertEqual(self.vistos(), {"A000000001"})

    def test_layout_desconhecido_conta_como_erro(self):
        amazon = AmazonFalsa({"A000000001": 1000}, falhas=[Resposta("<html><body>vitrine</body></html>")])
        e = self.varrer(amazon)
        self.assertEqual(e["erros"], 1)
        self.assertIn("layout desconhecido", e["observacao"])
        self.assertEqual(self.vistos(), {"A000000001"})

    def test_dia_seguinte_le_tudo_de_novo(self):
        amazon = AmazonFalsa({"A000000001": 1000})
        self.varrer(amazon)
        self.para_ontem("ultima_passada", "passada_iniciada_em")
        self.assertIsNotNone(self.varrer(amazon))  # novo dia: tudo de novo
        c = varredura.cobertura(self.conn, "1")
        self.assertEqual((c.dia_completo, c.fatias_hoje, c.fatias, c.lacunas), (True, 15, 15, []))

    def test_passada_de_ontem_recomeca_da_pagina_1(self):
        precos = {f"A{i:09d}": 2000 + i for i in range(100)}  # 7 páginas
        amazon = AmazonFalsa(precos)
        self.varrer(amazon, max_paginas=6)  # parou na página 4 da fatia R$ 20–25
        self.para_ontem("passada_iniciada_em")
        amazon.chamadas.clear()
        self.varrer(amazon)
        self.assertIn("p_36%3A2000-2499%2Cp_6%3AA1ZZFT5FULY4LN&s=price-asc-rank&page=1", " ".join(amazon.chamadas))

    def test_lacunas_e_bloqueio_desde_o_primeiro_dia(self):
        cachorros = Resposta("<html><head><title>Amazon.com.br Algo deu errado</title></head></html>", 503)
        self.varrer(AmazonFalsa({"A000000001": 1000}, falhas=[cachorros] * 3))
        self.para_ontem()
        c = varredura.cobertura(self.conn, "1")
        self.assertEqual(c.lacunas, [db.hoje_brasil() - timedelta(days=1)])
        self.assertFalse(c.dia_completo)


class TestFaixasDeProducao(unittest.TestCase):
    def test_contiguas_sem_buraco_nem_sobreposicao_e_cobrem_todos_os_precos(self):
        f = FAIXAS_PRODUCAO
        self.assertEqual(len(f), 9)
        self.assertEqual(f[0][0], 0)
        self.assertEqual(f[-1][1], varredura.SEM_TETO)
        for (_, fim), (inicio, _) in zip(f, f[1:]):
            self.assertEqual(inicio, fim + 1)
        self.assertEqual(varredura.faixas_de_precos([0, 20, 30, 40, 50, 60, 80, 120, 200]), f)

    def test_banco_com_as_3_faixas_antigas_passa_para_as_novas_sem_perder_historico(self):
        conn = db.conectar(":memory:")
        self.addCleanup(conn.close)
        varredura.criar_schema(conn)
        varredura.semear_vendidos(conn, ["1"], FAIXAS_TESTE)
        conn.execute("UPDATE fatias SET ultima_passada = '2999-01-01T00:00:00+00:00'")
        varredura.semear_vendidos(conn, ["1"])                       # padrão: as 9 faixas
        ativas = [tuple(r) for r in conn.execute("SELECT preco_min, preco_max FROM fatias WHERE ativa = 1 ORDER BY preco_min")]
        self.assertEqual(ativas, FAIXAS_PRODUCAO)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM fatias WHERE ativa = 0").fetchone()[0], 3)  # as antigas ficam, inativas


class TestMaisVendidos(unittest.TestCase):
    def setUp(self):
        self.conn = db.conectar(":memory:")
        self.addCleanup(self.conn.close)
        p = mock.patch.object(varredura, "FAIXAS_VENDIDOS", FAIXAS_TESTE)
        p.start()
        self.addCleanup(p.stop)

    def test_le_ate_1000_livros_por_faixa_sem_dividir(self):
        # Gênero 1: 1.300 livros (só os 1.200 primeiros aparecem); gênero 2: 50 livros,
        # 10 deles também no gênero 1.
        g1 = [(f"G1{i:08d}", 1000 + i) for i in range(1300)]
        g2 = [(f"G2{i:08d}", 2000 + i) for i in range(40)] + g1[:10]
        g2 = g2[:40]
        amazon = AmazonFalsaVendidos({"1": g1, "2": g2})
        eid = varredura.varrer(self.conn, amazon, vendidos=["1", "2"], minutos=10_000, dormir=lambda s: None)
        vistos = {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}
        self.assertEqual(vistos, {a for a, _ in g1[:1008]} | {a for a, _ in g2})   # 63 páginas de 16 = 1.008
        self.assertEqual(len([u for u in amazon.chamadas if "n%3A1%2Cp_36%3A0-" in u]), 63)  # para ao completar 1.000 livros
        self.assertTrue(all("p_6%3AA1ZZFT5FULY4LN" in u for u in amazon.chamadas))    # só vendidos pela Amazon
        self.assertIsNotNone(self.conn.execute("SELECT valor FROM config WHERE chave = 'so_amazon_desde'").fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fatias").fetchone()[0], 6)  # 3 faixas por gênero, sem divisão
        self.assertTrue(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).dia_completo)
        e = self.conn.execute("SELECT observacao FROM execucoes WHERE id = ?", (eid,)).fetchone()[0]
        self.assertIn("dia completo", e)
        # Gênero novo na lista: entra sem refazer os outros no mesmo dia.
        amazon.por_no["3"] = [("G300000001", 999)]
        varredura.varrer(self.conn, amazon, vendidos=["1", "2", "3"], minutos=10_000, dormir=lambda s: None)
        self.assertIn("G300000001", {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")})

    def test_livros_sem_preco_nao_contam_e_aparecem_quando_voltam(self):
        # a cada 10 livros, 1 sem preço: 15 de 16 por página têm preço
        g = [(f"G{i:09d}", None if i % 10 == 9 else 1000 + i) for i in range(1300)]
        amazon = AmazonFalsaVendidos({"1": g})
        varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        vistos = {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}
        self.assertFalse(any(a in vistos for a, p in g if p is None))      # sem preço: nunca entra
        com_preco = [a for a, p in g if p is not None]
        self.assertGreaterEqual(len(vistos), 1000)
        self.assertLess(len(vistos), 1000 + 16)                           # lê até completar 1.000 com preço, não 75 páginas
        self.assertEqual(self.conn.execute("SELECT SUM(livros) FROM fatias").fetchone()[0], len(vistos))
        self.assertLess(len([u for u in amazon.chamadas]), 75 + 2)          # + 1 página vazia em cada outra faixa
        # no dia seguinte, alguns voltam a ter preço (e outros saem do topo): quem voltou entra na base
        indisponiveis = [a for a, p in g if p is None][:5]
        amazon.por_no["1"] = [(a, 1500 if a in indisponiveis else p) for a, p in g]
        self.conn.execute("UPDATE fatias SET ultima_passada = '2000-01-01T00:00:00+00:00'")
        self.conn.execute("DELETE FROM dias")
        varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        vistos2 = {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}
        self.assertTrue(set(indisponiveis) <= vistos2)
        self.assertTrue(vistos <= vistos2)                                # o que já estava na base continua lá

    def test_faixas_de_preco_cobrem_os_2000_mais_vendidos(self):
        # 3.000 livros com preços alternando entre as 3 faixas: o ranking inteiro só mostraria
        # 1.200; por faixa, os 1.000 primeiros de cada uma juntos são os 3.000 mais vendidos.
        precos = (1990, 5990, 12990)
        g = [(f"G{i:09d}", precos[i % 3]) for i in range(3000)]
        amazon = AmazonFalsaVendidos({"1": g})
        varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        vistos = {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}
        self.assertTrue({a for a, _ in g[:2000]} <= vistos)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fatias WHERE ultima_passada IS NOT NULL").fetchone()[0], 3)

    def test_banco_antigo_troca_a_fatia_inteira_pelas_faixas(self):
        varredura.criar_schema(self.conn)
        self.conn.execute("INSERT INTO fatias (grupo, no, ordem, preco_min, preco_max, criada_em, ultima_passada) "
                          "VALUES ('vendidos', '1', 'vendidos', 0, 99999999, 'x', '2999-01-01T00:00:00+00:00')")
        amazon = AmazonFalsaVendidos({"1": [("G000000001", 2500), ("G000000002", 9000)]})
        varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        ativas = self.conn.execute("SELECT preco_min, preco_max FROM fatias WHERE ativa = 1 ORDER BY preco_min").fetchall()
        self.assertEqual([tuple(r) for r in ativas], varredura.FAIXAS_VENDIDOS)
        self.assertEqual({r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}, {"G000000001", "G000000002"})
        self.assertTrue(all("p_36" in u for u in amazon.chamadas))

    def test_migra_banco_da_varredura_antiga(self):
        self.conn.executescript(
            "CREATE TABLE fatias (id INTEGER PRIMARY KEY, no TEXT NOT NULL, preco_min INTEGER NOT NULL, "
            "preco_max INTEGER NOT NULL, ativa INTEGER NOT NULL DEFAULT 1, paginas INTEGER, total INTEGER, "
            "proxima_pagina INTEGER NOT NULL DEFAULT 1, passada_iniciada_em TEXT, ultima_passada TEXT, "
            "criada_em TEXT NOT NULL, UNIQUE (no, preco_min, preco_max));"
            "INSERT INTO fatias (no, preco_min, preco_max, criada_em) VALUES ('7842710011', 0, 999, 'x');")
        varredura.criar_schema(self.conn)
        r = self.conn.execute("SELECT grupo, ordem FROM fatias").fetchone()
        self.assertEqual(tuple(r), ("7842710011", "preco"))


    def test_banco_sem_detalhes_ganha_as_colunas_e_nao_perde_o_que_ja_tinha(self):
        self.conn.executescript(
            "CREATE TABLE catalogo (asin TEXT PRIMARY KEY, titulo TEXT, formato TEXT, no TEXT, "
            "primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL);"
            "INSERT INTO catalogo VALUES ('A000000001', 'X', 'Capa comum', '1', 'a', 'b');")
        varredura.criar_schema(self.conn)
        varredura.criar_schema(self.conn)                                # idempotente
        item = ItemBusca("A000000001", "Capa comum", "X", 500, autor="Fulano", imagem="abc", obra="A000000001")
        varredura.registrar(self.conn, item, "1", "2026-10-02T12:00:00+00:00")
        varredura.registrar(self.conn, ItemBusca("A000000001", "Capa comum", "X", 500), "1", "2026-10-03T12:00:00+00:00")
        r = self.conn.execute("SELECT autor, imagem, obra, primeiro_visto FROM catalogo").fetchone()
        self.assertEqual(tuple(r), ("Fulano", "abc", "A000000001", "a"))   # leitura sem detalhes não apaga


    def test_banco_sem_generos_comeca_pelo_no_de_cada_livro(self):
        self.conn.executescript(
            "CREATE TABLE catalogo (asin TEXT PRIMARY KEY, titulo TEXT, formato TEXT, no TEXT, "
            "primeiro_visto TEXT NOT NULL, ultimo_visto TEXT NOT NULL);"
            f"INSERT INTO catalogo VALUES ('A000000001', 'X', 'Capa comum', '7882388011', 'a', 'b'),"
            f"('A000000002', 'Y', 'Kindle', '{varredura.NO_LIVROS}', 'a', 'b');")
        varredura.criar_schema(self.conn)
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT asin, no FROM generos")], [("A000000001", "7882388011")])
        cols = {c[1]: c[2] for c in self.conn.execute("PRAGMA table_info(catalogo)")}
        self.assertEqual((cols["nota"], cols["avaliacoes"]), ("INTEGER", "INTEGER"))

    def test_generos_acumulam_e_avaliacoes_ficam_com_a_ultima_lida(self):
        varredura.criar_schema(self.conn)
        q = "2026-10-02T12:00:00+00:00"
        varredura.registrar(self.conn, ItemBusca("A000000001", "Kindle", "X", 500, nota=46, avaliacoes=100), "7882388011", q)
        varredura.registrar(self.conn, ItemBusca("A000000001", "Kindle", "X", 500, nota=47, avaliacoes=120), "7872687011", q)
        varredura.registrar(self.conn, ItemBusca("A000000001", "Kindle", "X", 500), varredura.NO_LIVROS, q)
        varredura.registrar(self.conn, ItemBusca("A000000001", "Kindle", "X", 500), "7882388011", q)
        self.assertEqual(tuple(self.conn.execute("SELECT nota, avaliacoes, no FROM catalogo").fetchone()),
                         (47, 120, "7882388011"))
        self.assertEqual({r[0] for r in self.conn.execute("SELECT no FROM generos")}, {"7882388011", "7872687011"})

    def test_preenchimento_dos_detalhes_no_catalogo(self):
        varredura.criar_schema(self.conn)
        hoje = varredura.inicio_do_dia()
        for i in range(4):
            com = i < 2
            varredura.registrar(self.conn, ItemBusca(f"A{i:09d}", "Capa comum", "X", 500, autor="F" if com else None,
                                                     imagem="abc" if com else None, obra=f"A{i:09d}",
                                                     avaliacoes=3), "1", hoje)
        n, fracoes = varredura.preenchimento(self.conn, hoje)
        self.assertEqual((n, fracoes["imagem"], fracoes["obra"], fracoes["idioma"]), (4, 0.5, 1.0, 0.0))
        self.assertEqual(varredura.preenchimento(self.conn, "2999-01-01T00:00:00+00:00"), (0, {
            c: 0.0 for c in varredura.CAMPOS_PREENCHIMENTO}))

    def test_execucao_avisa_quando_os_cards_param_de_trazer_capa_e_autor(self):
        livros = [(f"G{i:09d}", 1000 + i) for i in range(300)]
        amazon = AmazonFalsaVendidos({"1": livros})
        eid = varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        obs = self.conn.execute("SELECT observacao FROM execucoes WHERE id = ?", (eid,)).fetchone()[0]
        self.assertNotIn("layout", obs)
        self.assertEqual(self.conn.execute("SELECT imagem, autor FROM catalogo WHERE asin = 'G000000007'").fetchone()[:],
                         ("CG000000007", "Autor G000000007"))
        self.conn.execute("UPDATE fatias SET ultima_passada = '2000-01-01T00:00:00+00:00'")   # dia seguinte
        self.conn.execute("DELETE FROM dias")
        amazon.detalhes = False
        eid = varredura.varrer(self.conn, amazon, vendidos=["1"], minutos=10_000, dormir=lambda s: None)
        obs = self.conn.execute("SELECT observacao FROM execucoes WHERE id = ?", (eid,)).fetchone()[0]
        self.assertIn("poucos itens com capa, autor: o layout da página de busca pode ter mudado", obs)
        self.assertEqual(self.conn.execute("SELECT imagem FROM catalogo WHERE asin = 'G000000007'").fetchone()[0],
                         "CG000000007")    # o que já se sabia continua lá


CACHORROS = Resposta("<html><head><title>Amazon.com.br Algo deu errado</title></head></html>", 503)


class AmazonRealista(AmazonFalsaVendidos):
    """Como a real: anuncia a última página de verdade (até 75) e pode devolver páginas ralas.

    `ralas[(nó, página)]` é uma fila de quantos resultados a página traz em cada leitura (a primeira
    leitura toma o primeiro número, e assim por diante); sem fila, a página vem normal.
    Com `lote=True` tem `get_lote` como o cliente do navegador e guarda os lotes em `lotes`.
    """

    def __init__(self, por_no, ralas=None, falhas=None, lote=False):
        super().__init__(por_no, falhas)
        self.ralas = {k: list(v) for k, v in (ralas or {}).items()}
        self.lotes: list[list[str]] = []
        if lote:
            self.get_lote = self._get_lote

    def _get_lote(self, urls, atrasos, timeout=30):
        self.lotes.append(list(urls))
        assert len(urls) == len(atrasos) and atrasos[0] == 0 and atrasos == sorted(atrasos)
        return [self.get(u) for u in urls]

    def mais_vendidos(self, q):
        rh = unquote(q["rh"][0])
        no = re.search(r"n:(\d+)", rh).group(1)
        faixa = re.search(r"p_36:(\d+)-(\d+)", rh)
        lo, hi = map(int, faixa.groups()) if faixa else (0, 10**12)
        lista = [(a, p) for a, p in self.por_no.get(no, []) if p is not None and lo <= p <= hi]
        pag = int(q["page"][0])
        ini = (pag - 1) * self.POR_PAGINA
        itens = lista[ini:ini + self.POR_PAGINA] if pag <= 75 else []
        fila = self.ralas.get((no, pag))
        if fila and (lo, hi) == (0, 3999):
            itens = itens[:fila.pop(0)]
        return Resposta(pagina_busca(itens, ultima=min(75, -(-len(lista) // self.POR_PAGINA)) or None,
                                     total=len(lista), primeiro=ini + 1))


class TestRitmoNaVarredura(unittest.TestCase):
    """Lotes (várias fatias ao mesmo tempo), recuo no primeiro sinal e páginas "magras"."""

    def setUp(self):
        self.conn = db.conectar(":memory:")
        self.addCleanup(self.conn.close)
        self.pausas = []
        p = mock.patch.object(varredura, "FAIXAS_VENDIDOS", FAIXAS_TESTE)
        p.start()
        self.addCleanup(p.stop)

    def varrer(self, amazon, nos=("1",), **kw):
        kw.setdefault("minutos", 10_000)
        eid = varredura.varrer(self.conn, amazon, vendidos=list(nos), dormir=self.pausas.append, **kw)
        return self.conn.execute("SELECT * FROM execucoes WHERE id = ?", (eid,)).fetchone()

    def vistos(self):
        return {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}

    def novo_dia(self):
        self.conn.execute("UPDATE fatias SET ultima_passada = '2000-01-01T00:00:00+00:00'")
        self.conn.execute("DELETE FROM dias")
        self.conn.commit()

    def livros(self, n, prefixo="G", preco0=1000):
        return [(f"{prefixo}{i:09d}", preco0 + i) for i in range(n)]

    def test_le_varias_fatias_por_lote_sem_repetir_pagina_nem_misturar_a_ordem(self):
        por_no = {no: self.livros(160, prefixo=chr(64 + int(no))) for no in "123"}   # ASIN = 10 caracteres
        amazon = AmazonRealista(por_no, lote=True)
        e = self.varrer(amazon, nos="123", ritmo=Ritmo(100, teto=100))
        self.assertEqual(self.vistos(), {a for l in por_no.values() for a, _ in l})
        self.assertGreater(max(len(l) for l in amazon.lotes), 1)
        self.assertLessEqual(max(len(l) for l in amazon.lotes), 3)
        for lote in amazon.lotes:           # no máximo uma página por fatia em cada lote
            fatias = [re.sub(r"&page=\d+", "", u) for u in lote]
            self.assertEqual(len(fatias), len(set(fatias)))
        por_fatia = {}
        for u in amazon.chamadas:
            por_fatia.setdefault(re.sub(r"&page=\d+", "", u), []).append(int(re.search(r"page=(\d+)", u).group(1)))
        for u, paginas in por_fatia.items():
            if "p_36%3A0-3999" in u:
                self.assertEqual(paginas, list(range(1, 11)), u)     # 10 páginas em ordem, cada uma uma vez
        self.assertEqual((e["bloqueios"], e["erros"], e["curtas"]), (0, 0, 0))
        self.assertIsNotNone(e["ppm"])

    def test_sem_get_lote_le_uma_de_cada_vez_nos_mesmos_instantes(self):
        por_no = {no: self.livros(48, prefixo=chr(64 + int(no))) for no in "12"}
        amazon = AmazonRealista(por_no, lote=False)
        self.varrer(amazon, nos="12", ritmo=Ritmo(100, teto=100))
        self.assertEqual(self.vistos(), {a for l in por_no.values() for a, _ in l})
        self.assertTrue(any(0 < p < 5 for p in self.pausas))        # escalonou com dormir()

    def test_pagina_magra_e_relida_depois_de_pausa_e_o_ritmo_recua(self):
        g = self.livros(80)                                          # 5 páginas
        amazon = AmazonRealista({"1": g}, ralas={("1", 3): [2]})
        ritmo = Ritmo(40, teto=40)
        e = self.varrer(amazon, ritmo=ritmo)
        self.assertEqual(self.vistos(), {a for a, _ in g})           # nada se perdeu
        self.assertEqual((e["curtas"], e["bloqueios"], e["erros"]), (1, 0, 0))
        self.assertEqual(len([u for u in amazon.chamadas if "p_36%3A0-3999" in u and u.endswith("page=3")]), 2)
        self.assertEqual((ritmo.falhas, ritmo.ppm, ritmo.teto), (1, 20.0, 40))   # leve e isolada: metade, e o teto fica
        self.assertTrue(any(p >= varredura.PAUSA_APOS_BLOQUEIO for p in self.pausas))      # pausa longa antes de reler
        self.assertEqual(e["observacao"], "dia completo")

    def test_pagina_curta_que_se_repete_e_aceita_e_avisada(self):
        g = self.livros(80)
        amazon = AmazonRealista({"1": g}, ralas={("1", 3): [2, 2]})
        e = self.varrer(amazon)
        self.assertEqual(e["curtas"], 1)                             # só a primeira leitura conta como falha
        self.assertIn("confirmado em duas leituras", e["observacao"])
        self.assertEqual(len(self.vistos()), 80 - 14)                # a página 3 só trouxe 2 dos 16
        self.assertTrue(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).dia_completo)

    def test_pagina_1_vazia_numa_fatia_que_tinha_muitas_paginas_e_suspeita(self):
        g = self.livros(160)
        amazon = AmazonRealista({"1": g})
        self.varrer(amazon)
        self.novo_dia()
        amazon.ralas[("1", 1)] = [0]
        e = self.varrer(amazon)
        self.assertEqual(e["curtas"], 1)
        self.assertEqual(self.conn.execute(
            "SELECT livros_ant FROM fatias WHERE preco_min = 0 AND ordem = 'vendidos'").fetchone()[0], 160)
        self.assertEqual(len(self.vistos()), 160)

    def test_fatia_realmente_vazia_nao_e_suspeita(self):
        e = self.varrer(AmazonRealista({"1": []}))
        self.assertEqual((e["curtas"], e["erros"], e["bloqueios"]), (0, 0, 0))

    def test_parar_na_falha_para_na_primeira_e_diz_em_que_ritmo(self):
        amazon = AmazonRealista({"1": self.livros(80)}, falhas=[CACHORROS])
        e = self.varrer(amazon, ritmo=Ritmo(50, teto=50), parar_na_falha=True)
        # 50 páginas/min = 2 ao mesmo tempo: uma foi bloqueada e a outra passou, e não houve um segundo lote
        self.assertEqual((e["bloqueios"], e["paginas"], len(amazon.chamadas)), (1, 1, 2))
        self.assertIn("parada na primeira falha, programada a 50 páginas/min", e["observacao"])

    def test_falha_em_lote_conta_uma_vez_e_derruba_para_uma_pista(self):
        amazon = AmazonRealista({n: self.livros(160, prefixo=chr(64 + int(n))) for n in "123"},
                                falhas=[CACHORROS] * 10, lote=True)
        ritmo = Ritmo(100, teto=100)
        e = self.varrer(amazon, nos="123", ritmo=ritmo)
        self.assertEqual([len(l) for l in amazon.lotes[:1]], [3])
        self.assertEqual(e["bloqueios"], 5)                          # lote de 3, depois 1 e 1: 3 lotes com falha
        self.assertIn("interrompida após 3 falhas seguidas", e["observacao"])
        self.assertEqual((ritmo.falhas, ritmo.ppm, ritmo.pistas), (3, PPM_RECUO, 1))
        self.assertLess(ritmo.teto, 100)                             # bloqueio é grave: o teto desce

    def test_queda_de_livros_entre_passadas_e_avisada(self):
        amazon = AmazonRealista({"1": self.livros(300)})
        self.varrer(amazon)
        self.novo_dia()
        amazon.por_no["1"] = self.livros(200)
        e = self.varrer(amazon)
        self.assertIn("leu 200 livros; na passada anterior, 300", e["observacao"])
        self.novo_dia()
        e = self.varrer(amazon)                                      # igual à anterior: sem aviso
        self.assertNotIn("passada anterior", e["observacao"] or "")

    def test_faixas_de_preco_configuraveis(self):
        faixas = varredura.faixas_de_precos([0, 20, 50])
        self.assertEqual(faixas, [(0, 1999), (2000, 4999), (5000, varredura.SEM_TETO)])
        g = [(f"G{i:09d}", 500 + 700 * i) for i in range(10)]          # R$ 5, 12, 19, 26, 33, 40, 47, 54, 61, 68
        amazon = AmazonRealista({"1": g})
        self.varrer(amazon, faixas=faixas)
        ativas = [tuple(r) for r in self.conn.execute(
            "SELECT preco_min, preco_max FROM fatias WHERE ativa = 1 ORDER BY preco_min")]
        self.assertEqual(ativas, faixas)
        self.assertEqual(self.vistos(), {a for a, _ in g})
        self.varrer(amazon, faixas=[(0, 3999), (4000, varredura.SEM_TETO)])                    # outras faixas: troca as ativas
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fatias WHERE ativa = 1").fetchone()[0], 2)

    def test_faixas_invalidas(self):
        for ruim in ([], [10, 20], [0, 20, 20], [0, 30, 20]):
            with self.assertRaises(ValueError, msg=ruim):
                varredura.faixas_de_precos(ruim)

    def test_nos_vendidos(self):
        todos = varredura.nos_vendidos()
        self.assertEqual((todos[0], len(todos)), (varredura.NO_LIVROS, 1 + len(varredura.GENEROS)))
        self.assertEqual(varredura.nos_vendidos(" 7841720011, 7844001011 "), ["7841720011", "7844001011"])
        with self.assertRaises(ValueError):
            varredura.nos_vendidos("7841720011,000")

    def test_migra_banco_sem_as_colunas_de_medicao(self):
        self.conn.executescript(
            "CREATE TABLE execucoes (id INTEGER PRIMARY KEY, iniciada_em TEXT NOT NULL, finalizada_em TEXT, "
            "paginas INTEGER NOT NULL DEFAULT 0, itens INTEGER NOT NULL DEFAULT 0, bloqueios INTEGER NOT NULL DEFAULT 0, "
            "erros INTEGER NOT NULL DEFAULT 0, observacao TEXT);"
            "INSERT INTO execucoes (iniciada_em) VALUES ('x');")
        varredura.criar_schema(self.conn)
        varredura.criar_schema(self.conn)
        r = self.conn.execute("SELECT curtas, ppm FROM execucoes").fetchone()
        self.assertEqual(tuple(r), (0, None))
        self.assertIn("livros_ant", {c[1] for c in self.conn.execute("PRAGMA table_info(fatias)")})


class TestHistorico(unittest.TestCase):
    def setUp(self):
        self.conn = db.conectar(":memory:")
        self.addCleanup(self.conn.close)
        varredura.criar_schema(self.conn)

    def ver(self, preco, quando, capa=None):
        varredura.registrar(self.conn, ItemBusca("A000000001", "Capa comum", "X", preco, capa), "1", quando)

    def linhas(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT preco_centavos, preco_capa_centavos, desde, ate, vezes FROM historico ORDER BY id")]

    def test_intervalos(self):
        self.ver(2990, "2026-10-01T00:00:00+00:00")
        self.ver(2990, "2026-10-02T00:00:00+00:00", capa=4490)  # mesmo preço: estende e completa a capa
        self.ver(1990, "2026-10-03T00:00:00+00:00", capa=4490)  # promoção: novo intervalo
        self.ver(1990, "2026-10-03T12:00:00+00:00")             # sem "De:" na página: continua igual
        self.ver(1990, "2026-10-20T00:00:00+00:00")             # 16 dias sem ver: buraco, novo intervalo
        self.assertEqual(self.linhas(), [
            (2990, 4490, "2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00", 2),
            (1990, 4490, "2026-10-03T00:00:00+00:00", "2026-10-03T12:00:00+00:00", 2),
            (1990, None, "2026-10-20T00:00:00+00:00", "2026-10-20T00:00:00+00:00", 1),
        ])

    def test_mesma_execucao_em_fatias_sobrepostas_nao_duplica(self):
        self.ver(2990, "2026-10-01T00:00:00+00:00")
        self.ver(2990, "2026-10-01T00:00:00+00:00")
        self.assertEqual(len(self.linhas()), 1)


if __name__ == "__main__":
    unittest.main()
