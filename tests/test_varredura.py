"""Testes da varredura por páginas de busca. Rodar: python -m unittest discover -s tests

Fixtures REAIS (out/2026, trechos de páginas de busca da categoria HQs e Mangás):
`busca_fatia.html`, `busca_formatos.html` e `busca_fim.html` (última página, vazia).
"""

import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from comparador import db, varredura
from comparador.busca import ItemBusca, LayoutDesconhecido, parse_busca, url_busca

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

    def test_url_mais_vendidos(self):
        self.assertEqual(url_busca("6740748011", 0, 1, 2, "vendidos"),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A6740748011"
                         "&s=exact-aware-popularity-rank&page=2")

    def test_url_da_fatia(self):
        self.assertEqual(url_busca("7842710011", 2000, 2499, 3),
                         "https://www.amazon.com.br/s?i=stripbooks&rh=n%3A7842710011%2Cp_36%3A2000-2499"
                         "&s=price-asc-rank&page=3")


def card(asin, preco, patrocinado=False):
    reais, cent = divmod(preco, 100)
    return f"""<div data-component-type="s-search-result" data-asin="{asin}">
      {'<span class="puis-sponsored-label-text">Patrocinado</span>' if patrocinado else ''}
      <h2><span>Livro {asin}</span></h2>
      <a href="/x/dp/{asin}/ref=sr">Capa Comum</a>
      <a href="/x/dp/{asin}/ref=sr"><span class="a-price" data-a-color="base">
        <span class="a-offscreen">R$&nbsp;{reais},{cent:02d}</span></span></a></div>"""


def pagina_busca(itens, *, ultima, total, primeiro=1, patrocinado=False):
    paginacao = "".join(f'<span class="s-pagination-item">{n}</span>' for n in range(1, (ultima or 0) + 1))
    return f"""<html><title>Amazon.com.br</title><body>
      <div data-component-type="s-result-info-bar"><h2>{primeiro}-{primeiro + len(itens) - 1} de
        {total} resultados</h2></div>
      {''.join(card(a, p, patrocinado) for a, p in itens)}
      <span class="s-pagination-strip">{paginacao}</span></body></html>"""


class Resposta:
    def __init__(self, texto, status=200):
        self.text, self.status_code, self.url = texto, status, ""


class AmazonFalsa:
    """Simula a busca: filtro p_36 (centavos, inclusive), ordem por preço, 16 por página,
    no máximo 400 páginas, e a página 400 vem incompleta como na real."""

    POR_PAGINA = 16

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
        return Resposta(pagina_busca([(a, p) for p, a in fatia], ultima=ultima, total=len(itens), primeiro=ini + 1))


class AmazonFalsaVendidos(AmazonFalsa):
    """Ordem "mais vendidos": por nó, na ordem dada; só 75 páginas, mas anuncia 400."""

    def __init__(self, por_no: dict[str, list[tuple[str, int]]], falhas=None):
        super().__init__({}, falhas)
        self.por_no = por_no

    def mais_vendidos(self, q):
        no = re.search(r"n:(\d+)", unquote(q["rh"][0])).group(1)
        pag = int(q["page"][0])
        ini = (pag - 1) * self.POR_PAGINA
        itens = self.por_no.get(no, [])[ini:ini + self.POR_PAGINA] if pag <= 75 else []
        return Resposta(pagina_busca(itens, ultima=400, total=90000, primeiro=ini + 1))


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
        self.assertIn("p_36%3A2000-2499&s=price-asc-rank&page=1", " ".join(amazon.chamadas))

    def test_lacunas_e_bloqueio_desde_o_primeiro_dia(self):
        cachorros = Resposta("<html><head><title>Amazon.com.br Algo deu errado</title></head></html>", 503)
        self.varrer(AmazonFalsa({"A000000001": 1000}, falhas=[cachorros] * 3))
        self.para_ontem()
        c = varredura.cobertura(self.conn, "1")
        self.assertEqual(c.lacunas, [db.hoje_brasil() - timedelta(days=1)])
        self.assertFalse(c.dia_completo)


class TestMaisVendidos(unittest.TestCase):
    def setUp(self):
        self.conn = db.conectar(":memory:")
        self.addCleanup(self.conn.close)

    def test_le_ate_75_paginas_por_genero_sem_dividir(self):
        # Gênero 1: 1.300 livros (só os 1.200 primeiros aparecem); gênero 2: 50 livros,
        # 10 deles também no gênero 1.
        g1 = [(f"G1{i:08d}", 1000 + i) for i in range(1300)]
        g2 = [(f"G2{i:08d}", 2000 + i) for i in range(40)] + g1[:10]
        amazon = AmazonFalsaVendidos({"1": g1, "2": g2})
        eid = varredura.varrer(self.conn, amazon, vendidos=["1", "2"], minutos=10_000, dormir=lambda s: None)
        vistos = {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")}
        self.assertEqual(vistos, {a for a, _ in g1[:1200]} | {a for a, _ in g2})
        self.assertEqual(len([u for u in amazon.chamadas if "n%3A1&" in u]), 75)  # nem 76, nem 400
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fatias").fetchone()[0], 2)  # sem divisão
        self.assertTrue(varredura.cobertura(self.conn, varredura.GRUPO_VENDIDOS).dia_completo)
        e = self.conn.execute("SELECT observacao FROM execucoes WHERE id = ?", (eid,)).fetchone()[0]
        self.assertIn("dia completo", e)
        # Gênero novo na lista: entra sem refazer os outros no mesmo dia.
        amazon.por_no["3"] = [("G300000001", 999)]
        varredura.varrer(self.conn, amazon, vendidos=["1", "2", "3"], minutos=10_000, dormir=lambda s: None)
        self.assertIn("G300000001", {r[0] for r in self.conn.execute("SELECT asin FROM catalogo")})

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
