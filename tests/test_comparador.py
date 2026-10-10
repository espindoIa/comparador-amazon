"""Testes com HTML SINTÉTICO que imita a estrutura esperada da página da Amazon.

Eles provam que a lógica do parser e do coletor está coerente, mas não que os
seletores batem com as páginas reais: isso só se confirma com a primeira coleta.
Rodar: python -m unittest discover -s tests
"""

import gzip
import tempfile
import unittest
from pathlib import Path

from comparador import coletor, db
from comparador.parser import parse_preco, parse_produto


def pagina(
    *,
    titulo="Um Livro",
    bloco_preco="",
    vendedor="",
    estoque="",
    extra="",
):
    return f"""<html><body>
    <span id="productTitle"> {titulo} </span>
    <div id="bylineInfo"><span class="author"><a>Fulana de Tal</a></span></div>
    {bloco_preco}{vendedor}
    <div id="availability"><span>{estoque}</span></div>
    {extra}
    </body></html>"""


PRECO_COM_CAPA = """<div id="corePrice_feature_div">
  <span class="a-price priceToPay"><span class="a-offscreen">R$&nbsp;39,90</span></span>
  <span class="a-price a-text-price"><span class="a-offscreen">R$&nbsp;1.059,00</span></span>
</div>"""

CARROSSEL = """<div id="similarities"><span class="a-price"><span class="a-offscreen">R$ 9,99</span></span></div>"""


class TestParsePreco(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(parse_preco("R$ 39,90"), 3990)
        self.assertEqual(parse_preco("R$\xa01.234,56"), 123456)
        self.assertEqual(parse_preco("R$ 1234,56"), 123456)
        self.assertIsNone(parse_preco("sem preço"))
        self.assertIsNone(parse_preco(None))


class TestParseProduto(unittest.TestCase):
    def test_preco_e_capa(self):
        html = pagina(
            bloco_preco=PRECO_COM_CAPA,
            vendedor='<div id="merchant-info">Enviado por Amazon e vendido por Amazon.com.br.</div>',
            estoque="Em estoque",
        )
        o = parse_produto(html)
        self.assertEqual(o.status, "ok")
        self.assertEqual(o.preco_centavos, 3990)
        self.assertEqual(o.preco_capa_centavos, 105900)
        self.assertEqual(o.vendido_por, "Amazon")
        self.assertEqual(o.condicao, "novo")
        self.assertTrue(o.em_estoque)
        self.assertEqual(o.titulo, "Um Livro")
        self.assertEqual(o.autor, "Fulana de Tal")

    def test_vendedor_terceiro(self):
        html = pagina(
            bloco_preco=PRECO_COM_CAPA,
            vendedor='<div id="merchant-info">Vendido por Livraria X e entregue pela Amazon.</div>',
        )
        self.assertEqual(parse_produto(html).vendido_por, "Livraria X")

    def test_vendedor_tabela(self):
        html = pagina(
            bloco_preco=PRECO_COM_CAPA,
            vendedor='<div id="tabular-buybox"><span class="tabular-buybox-text" '
            'tabular-attribute-name="Vendido por"><a>Sebo Y</a></span></div>',
        )
        self.assertEqual(parse_produto(html).vendido_por, "Sebo Y")

    def test_capa_por_texto(self):
        bloco = """<div id="corePrice_feature_div">
          <span class="a-price priceToPay"><span class="a-offscreen">R$ 50,00</span></span>
          <span>Preço de capa: R$ 80,00</span></div>"""
        self.assertEqual(parse_produto(pagina(bloco_preco=bloco)).preco_capa_centavos, 8000)

    def test_ignora_preco_de_carrossel(self):
        o = parse_produto(pagina(extra=CARROSSEL))
        self.assertNotEqual(o.preco_centavos, 999)
        self.assertEqual(o.status, "sem_preco")

    def test_indisponivel(self):
        o = parse_produto(pagina(estoque="Atualmente indisponível."))
        self.assertEqual(o.status, "indisponivel")
        self.assertFalse(o.em_estoque)

    def test_bloqueado(self):
        o = parse_produto('<form action="/errors/validateCaptcha">Digite os caracteres</form>')
        self.assertEqual(o.status, "bloqueado")

    def test_layout_inesperado(self):
        self.assertEqual(parse_produto("<html><body>nada</body></html>").status, "erro_parse")


class TestLista(unittest.TestCase):
    def test_extrair_asin(self):
        self.assertEqual(coletor.extrair_asin("b0abcdefgh"), "B0ABCDEFGH")
        self.assertEqual(coletor.extrair_asin("https://www.amazon.com.br/Nome/dp/8535902775/ref=x"), "8535902775")
        self.assertIsNone(coletor.extrair_asin("lixo"))

    def test_ler_lista(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "livros.txt"
            f.write_text("# c\n8535902775  # x\n\n8535902775\nB0ABCDEFGH\nlixo\n", encoding="utf-8")
            self.assertEqual(coletor.ler_lista(f), ["8535902775", "B0ABCDEFGH"])


class RespostaFalsa:
    def __init__(self, texto, status=200):
        self.text, self.status_code = texto, status


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas, self.chamadas = respostas, []

    def get(self, url, **kw):
        self.chamadas.append(url)
        return self.respostas[len(self.chamadas) - 1]


class TestColetor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.conectar(Path(self.tmp.name) / "t.db")
        db.criar_schema(self.conn)
        self.pausas = []

    def rodar(self, asins, respostas, pasta_html=None):
        sessao = SessaoFalsa(respostas)
        cid = coletor.coletar(
            self.conn, asins, sessao=sessao, pasta_html=pasta_html, dormir=self.pausas.append
        )
        return cid, sessao

    def test_grava_preco_e_atualiza_livro(self):
        ok = RespostaFalsa(pagina(bloco_preco=PRECO_COM_CAPA, estoque="Em estoque"))
        cid, _ = self.rodar(["8535902775"], [ok])
        p = self.conn.execute("SELECT * FROM precos").fetchone()
        self.assertEqual((p["status"], p["preco_centavos"], p["preco_capa_centavos"]), ("ok", 3990, 105900))
        self.assertEqual(self.conn.execute("SELECT titulo FROM livros").fetchone()[0], "Um Livro")
        c = self.conn.execute("SELECT * FROM coletas WHERE id=?", (cid,)).fetchone()
        self.assertEqual((c["tentados"], c["sucesso"], c["falhas"]), (1, 1, 0))
        self.assertIsNotNone(c["finalizada_em"])

    def test_falhas_ficam_registradas(self):
        cid, _ = self.rodar(
            ["AAAAAAAAAA", "BBBBBBBBBB"],
            [RespostaFalsa("", 404), RespostaFalsa("<html>nada</html>")],
        )
        st = [r[0] for r in self.conn.execute("SELECT status FROM precos ORDER BY id")]
        self.assertEqual(st, ["erro_http", "erro_parse"])
        c = self.conn.execute("SELECT * FROM coletas WHERE id=?", (cid,)).fetchone()
        self.assertEqual((c["sucesso"], c["falhas"]), (0, 2))
        self.assertEqual(len(self.pausas), 1)  # pausa só entre livros, não antes do primeiro

    def test_para_apos_bloqueios_seguidos(self):
        bloq = RespostaFalsa("", 503)
        asins = [f"AAAAAAAAA{i}" for i in range(6)]
        cid, sessao = self.rodar(asins, [bloq] * 6)
        self.assertEqual(len(sessao.chamadas), coletor.LIMITE_BLOQUEIOS)
        c = self.conn.execute("SELECT * FROM coletas WHERE id=?", (cid,)).fetchone()
        self.assertEqual(c["tentados"], coletor.LIMITE_BLOQUEIOS)
        self.assertIn("interrompida", c["observacao"])

    def test_bloqueio_isolado_nao_interrompe(self):
        ok = RespostaFalsa(pagina(bloco_preco=PRECO_COM_CAPA))
        _, sessao = self.rodar(["AAAAAAAAAA", "BBBBBBBBBB", "CCCCCCCCCC"], [RespostaFalsa("", 503), ok, ok])
        self.assertEqual(len(sessao.chamadas), 3)

    def test_guarda_html_comprimido(self):
        html = pagina(bloco_preco=PRECO_COM_CAPA)
        pasta = Path(self.tmp.name) / "html"
        self.rodar(["8535902775"], [RespostaFalsa(html)], pasta_html=pasta)
        arq = self.conn.execute("SELECT html_arquivo FROM precos").fetchone()[0]
        self.assertEqual(gzip.decompress(Path(arq).read_bytes()).decode(), html)

    def test_eventos_importar_e_atualizar(self):
        csv = Path(self.tmp.name) / "e.csv"
        csv.write_text("nome,inicio,fim\nBlack Friday,2026-11-27,2026-11-27\n", encoding="utf-8")
        db.importar_eventos(self.conn, csv)
        csv.write_text("nome,inicio,fim\nBlack Friday,2026-11-27,2026-11-30\n", encoding="utf-8")
        db.importar_eventos(self.conn, csv)
        rows = self.conn.execute("SELECT fim FROM eventos").fetchall()
        self.assertEqual([r[0] for r in rows], ["2026-11-30"])


if __name__ == "__main__":
    unittest.main()
