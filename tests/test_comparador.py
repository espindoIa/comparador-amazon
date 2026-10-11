"""Testes. Rodar: python -m unittest discover -s tests

Fixtures REAIS da Amazon (out/2026): `ofertas_8501116432.html` (lista de ofertas) e
`lista_desejos_p1.html` (trecho anonimizado da 1ª página de uma lista de desejos).
As demais páginas de lista são sintéticas, com a mesma estrutura.
"""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from comparador import cliente_http, coletor, db
from comparador.lista_desejos import ListaIndisponivel, extrair_id, parse_pagina
from comparador.parser import parece_bloqueio, parse_ofertas, parse_preco

FIXTURES = Path(__file__).with_name("fixtures")
OFERTAS_REAL = (FIXTURES / "ofertas_8501116432.html").read_text(encoding="utf-8")
LISTA_REAL = (FIXTURES / "lista_desejos_p1.html").read_text(encoding="utf-8")
PAGINA_CACHORROS = "<html><head><title>Amazon.com.br Algo deu errado</title></head><body></body></html>"


def oferta_sintetica(*, preco="R$ 39,90", capa="R$ 59,90", heading="Novo", vendedor="Amazon.com.br"):
    capa_html = (
        f'<span class="a-price a-text-price apex-basisprice-value"><span class="a-offscreen">{capa}</span></span>'
        if capa else ""
    )
    return f"""<div id="aod-offer-heading">{heading}</div>
      <span class="a-price apex-pricetopay-value"><span class="a-offscreen">{preco}</span></span>
      {capa_html}
      <div id="aod-offer-soldBy"><div class="a-col-right">
        <span class="a-size-small a-color-base">{vendedor}</span><a>Política de devolução</a>
      </div></div>"""


def pagina_ofertas(*, principal="", lista="", total=5, titulo="Um Livro"):
    return f"""<html><body><h5 id="aod-asin-title-text"> {titulo} </h5>
      <input id="aod-total-offer-count" type="hidden" value="{total}"/>
      {f'<div id="aod-pinned-offer">{principal}</div>' if principal else ''}
      <div id="aod-offer-list">{lista}</div></body></html>"""


def item_lista(asin, preco, titulo="Livro", item_id=None):
    item_id = item_id or f"I{asin}"
    params = json.dumps({"itemExternalId": f"ASIN:{asin}|A2Q3Y263D00KWC", "listType": "WishList"})
    return f"""<li data-itemid="{item_id}" data-price="{preco}" class="g-item-sortable"
        data-reposition-action-params='{params}'>
      <a id="itemName_{item_id}" title="{titulo}" href="/dp/{asin}/?coliid=x">{titulo}</a>
      <span id="item-byline-{item_id}">por Fulana de Tal (Capa comum)</span></li>"""


def pagina_lista(itens, proxima=None):
    fim = '<div id="endOfListMarker"></div>' if proxima is None else (
        f'<input type="hidden" name="showMoreUrl" class="showMoreUrl" value="{proxima}">'
    )
    return f"<html><body><ul id='g-items'>{''.join(itens)}</ul>{fim}</body></html>"


class TestParsePreco(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(parse_preco("R$ 39,90"), 3990)
        self.assertEqual(parse_preco("R$\xa01.234,56"), 123456)
        self.assertEqual(parse_preco("R$ 1234,56"), 123456)
        self.assertIsNone(parse_preco("sem preço"))
        self.assertIsNone(parse_preco(None))


class TestParseOfertas(unittest.TestCase):
    def test_pagina_real(self):
        o = parse_ofertas(OFERTAS_REAL)
        self.assertEqual(o.status, "ok")
        self.assertEqual(o.titulo, "A paciente silenciosa")
        self.assertEqual(o.preco_centavos, 3499)
        self.assertEqual(o.preco_capa_centavos, 6490)
        self.assertEqual(o.vendido_por, "Amazon")
        self.assertEqual(o.condicao, "novo")

    def test_vendedor_terceiro_e_usado(self):
        o = parse_ofertas(pagina_ofertas(principal=oferta_sintetica(heading="Usado - Bom", vendedor="Sebo Y", capa=None)))
        self.assertEqual((o.vendido_por, o.condicao, o.preco_capa_centavos), ("Sebo Y", "usado", None))

    def test_sem_oferta_principal_usa_primeira_nova(self):
        lista = (f'<div id="aod-offer">{oferta_sintetica(heading="Usado - Bom", preco="R$ 10,00")}</div>'
                 f'<div id="aod-offer">{oferta_sintetica(preco="R$ 45,00")}</div>')
        o = parse_ofertas(pagina_ofertas(lista=lista))
        self.assertEqual((o.status, o.preco_centavos, o.condicao), ("ok", 4500, "novo"))
        self.assertIn("sem oferta principal", o.detalhe)

    def test_sem_ofertas(self):
        o = parse_ofertas(pagina_ofertas(total=0))
        self.assertEqual(o.status, "indisponivel")

    def test_bloqueios(self):
        self.assertEqual(parse_ofertas('<form action="/errors/validateCaptcha"></form>').status, "bloqueado")
        pagina_500 = '<script>window.location.replace("https://www.amazon.com.br/error/500");</script>'
        self.assertEqual(parse_ofertas(pagina_500).status, "bloqueado")

    def test_resposta_estranha(self):
        self.assertEqual(parse_ofertas("<html><body>nada</body></html>").status, "erro_parse")


class TestListaDesejos(unittest.TestCase):
    def test_extrair_id(self):
        self.assertEqual(extrair_id("https://www.amazon.com.br/hz/wishlist/ls/2ABCDEF123XYZ?ref_=x"), "2ABCDEF123XYZ")
        self.assertEqual(extrair_id("https://www.amazon.com.br/registry/wishlist/2ABCDEF123XYZ"), "2ABCDEF123XYZ")
        self.assertIsNone(extrair_id("https://www.amazon.com.br/dp/8535902775"))

    def test_parse_pagina(self):
        html = pagina_lista(
            [item_lista("8501116432", "34.99", "A paciente silenciosa"), item_lista("B0ABCDEFGH", "-Infinity")],
            proxima="/hz/wishlist/slv/items?paginationToken=abc",
        )
        itens, prox = parse_pagina(html)
        self.assertEqual([(i.asin, i.preco_centavos) for i in itens], [("8501116432", 3499), ("B0ABCDEFGH", None)])
        self.assertEqual(itens[0].titulo, "A paciente silenciosa")
        self.assertEqual(itens[0].autor, "Fulana de Tal")
        self.assertEqual(prox, "https://www.amazon.com.br/hz/wishlist/slv/items?paginationToken=abc")

    def test_pagina_real(self):
        itens, prox = parse_pagina(LISTA_REAL)
        self.assertEqual(
            [(i.asin, i.titulo, i.preco_centavos) for i in itens],
            [("8551013335", "Namorando com um vampiro", 3754), ("8551010654", "Morando com um vampiro", 3790)],
        )
        self.assertEqual(itens[0].autor, "Jenna Levine, Lígia Azevedo")
        self.assertIn("/hz/wishlist/slv/items?", prox)
        self.assertIn("paginationToken=TOKEN2", prox)

    def test_aviso_oculto_da_lista_nao_e_bloqueio(self):
        # A página real tem um alerta escondido "Algo deu errado e não pode ser removido..."
        self.assertFalse(parece_bloqueio(LISTA_REAL))
        self.assertTrue(parece_bloqueio(PAGINA_CACHORROS))

    def test_fim_da_lista(self):
        _, prox = parse_pagina(pagina_lista([item_lista("8501116432", "10.5")]))
        self.assertIsNone(prox)

    def test_item_sem_asin_ignorado(self):
        html = pagina_lista(['<li data-itemid="X1" data-price="5.0"><span>uma ideia</span></li>'])
        self.assertEqual(parse_pagina(html)[0], [])


class TestArquivos(unittest.TestCase):
    def test_extrair_asin(self):
        self.assertEqual(coletor.extrair_asin("b0abcdefgh"), "B0ABCDEFGH")
        self.assertEqual(coletor.extrair_asin("https://www.amazon.com.br/Nome/dp/8535902775/ref=x"), "8535902775")
        self.assertIsNone(coletor.extrair_asin("lixo"))

    def test_ler_lista(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "livros.txt"
            f.write_text("# c\n8535902775  # x\n\n8535902775\nB0ABCDEFGH\nlixo\n", encoding="utf-8")
            self.assertEqual(coletor.ler_lista(f), ["8535902775", "B0ABCDEFGH"])


class Resposta:
    def __init__(self, texto, status=200, url=""):
        self.text, self.status_code, self.url = texto, status, url


class SessaoFalsa:
    """Responde por trecho de URL; cada valor é uma Resposta ou uma lista consumida em ordem."""

    def __init__(self, rotas):
        self.rotas, self.chamadas = rotas, []

    def get(self, url, **kw):
        self.chamadas.append(url)
        for trecho, resp in self.rotas.items():
            if trecho in url:
                return resp.pop(0) if isinstance(resp, list) else resp
        raise AssertionError(f"URL inesperada: {url}")


LISTA = "https://www.amazon.com.br/hz/wishlist/ls/2ABCDEF123XYZ"


class TestColetor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.conectar(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.conn.close)
        db.criar_schema(self.conn)
        self.pausas = []

    def rodar(self, asins, rotas, *, listas=(), detalhar="auto", pasta_html=None):
        sessao = SessaoFalsa(rotas)
        cid = coletor.coletar(self.conn, asins, listas_desejos=list(listas), detalhar=detalhar,
                              sessao=sessao, pasta_html=pasta_html, dormir=self.pausas.append)
        return self.conn.execute("SELECT * FROM coletas WHERE id=?", (cid,)).fetchone(), sessao

    def linhas(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT asin, fonte, status, preco_centavos FROM precos ORDER BY id")]

    def test_livro_avulso_usa_ofertas(self):
        c, _ = self.rodar(["8501116432"], {"aodAjaxMain": Resposta(OFERTAS_REAL)})
        self.assertEqual(self.linhas(), [("8501116432", "ofertas", "ok", 3499)])
        self.assertEqual(self.conn.execute("SELECT titulo FROM livros").fetchone()[0], "A paciente silenciosa")
        self.assertEqual((c["tentados"], c["sucesso"], c["falhas"]), (1, 1, 0))

    def test_lista_paginada_e_detalhes(self):
        p1 = pagina_lista([item_lista("8501116432", "34.99")], proxima="/hz/wishlist/slv/items?paginationToken=t2")
        p2 = pagina_lista([item_lista("B0ABCDEFGH", "-Infinity")])
        rotas = {"wishlist/ls/": Resposta(p1), "paginationToken=t2": Resposta(p2),
                 "aodAjaxMain": [Resposta(OFERTAS_REAL), Resposta(pagina_ofertas(total=0))]}
        c, sessao = self.rodar([], rotas, listas=[LISTA])
        self.assertEqual(self.linhas(), [
            ("8501116432", "lista_desejos", "ok", 3499),
            ("B0ABCDEFGH", "lista_desejos", "indisponivel", None),
            ("8501116432", "ofertas", "ok", 3499),
            ("B0ABCDEFGH", "ofertas", "indisponivel", None),
        ])
        self.assertEqual(len(sessao.chamadas), 4)
        self.assertEqual(self.conn.execute("SELECT autor FROM livros WHERE asin='8501116432'").fetchone()[0], "Fulana de Tal")

    def test_auto_pula_ofertas_quando_preco_nao_mudou(self):
        lista = pagina_lista([item_lista("8501116432", "34.99")])
        self.rodar([], {"wishlist/ls/": Resposta(lista), "aodAjaxMain": Resposta(OFERTAS_REAL)}, listas=[LISTA])
        # Segundo dia, mesmo preço: só a lista é lida.
        _, sessao = self.rodar([], {"wishlist/ls/": Resposta(lista)}, listas=[LISTA])
        self.assertEqual(len(sessao.chamadas), 1)
        # Terceiro dia, preço caiu: consulta as ofertas de novo.
        lista2 = pagina_lista([item_lista("8501116432", "29.90")])
        _, sessao = self.rodar([], {"wishlist/ls/": Resposta(lista2), "aodAjaxMain": Resposta(OFERTAS_REAL)}, listas=[LISTA])
        self.assertEqual(len(sessao.chamadas), 2)

    def test_detalhar_nenhum(self):
        lista = pagina_lista([item_lista("8501116432", "34.99")])
        _, sessao = self.rodar([], {"wishlist/ls/": Resposta(lista)}, listas=[LISTA], detalhar="nenhum")
        self.assertEqual(len(sessao.chamadas), 1)

    def test_lista_privada_nao_derruba_coleta(self):
        rotas = {"wishlist/ls/": Resposta('<form action="/ap/signin"></form>'),
                 "aodAjaxMain": Resposta(OFERTAS_REAL)}
        c, _ = self.rodar(["8501116432"], rotas, listas=[LISTA])
        self.assertIn("privada", c["observacao"])
        self.assertEqual(self.linhas(), [("8501116432", "ofertas", "ok", 3499)])

    def test_link_de_login_no_menu_nao_e_lista_privada(self):
        menu = '<a href="https://www.amazon.com.br/ap/signin?openid.return_to=x">Faça login</a>'
        lista = pagina_lista([menu, item_lista("8501116432", "34.99")])
        c, _ = self.rodar([], {"wishlist/ls/": Resposta(lista)}, listas=[LISTA], detalhar="nenhum")
        self.assertIsNone(c["observacao"])
        self.assertEqual(self.linhas(), [("8501116432", "lista_desejos", "ok", 3499)])

    def test_lista_bloqueada(self):
        c, sessao = self.rodar([], {"wishlist/ls/": Resposta(PAGINA_CACHORROS, 503)}, listas=[LISTA])
        self.assertIn("página 1", c["observacao"])
        self.assertEqual(len(sessao.chamadas), coletor.TENTATIVAS_PAGINA_LISTA)

    def test_lista_real_com_503_intermitente(self):
        p2 = pagina_lista([item_lista("6581339202", "73.53")])
        rotas = {
            "wishlist/ls/": [Resposta(PAGINA_CACHORROS, 503), Resposta(LISTA_REAL)],
            "paginationToken=TOKEN2": [Resposta(PAGINA_CACHORROS, 503), Resposta(p2)],
        }
        c, _ = self.rodar([], rotas, listas=[LISTA], detalhar="nenhum")
        self.assertIsNone(c["observacao"])
        self.assertEqual([r[0] for r in self.linhas()], ["8551013335", "8551010654", "6581339202"])

    def test_lista_parcial_quando_pagina_do_meio_falha(self):
        rotas = {"wishlist/ls/": Resposta(LISTA_REAL), "paginationToken=TOKEN2": Resposta(PAGINA_CACHORROS, 503)}
        c, _ = self.rodar([], rotas, listas=[LISTA], detalhar="nenhum")
        self.assertIn("lista incompleta (2 itens lidos)", c["observacao"])
        self.assertEqual(len(self.linhas()), 2)  # os itens da página 1 não se perdem

    def test_lista_vazia_ou_layout_novo(self):
        c, _ = self.rodar([], {"wishlist/ls/": Resposta("<html><body>?</body></html>")}, listas=[LISTA])
        self.assertIn("nenhum item", c["observacao"])

    def test_paginacao_em_loop_para(self):
        p = pagina_lista([item_lista("8501116432", "34.99")], proxima="/hz/wishlist/slv/items?paginationToken=t")
        rotas = {"wishlist/ls/": Resposta(p), "paginationToken=t": Resposta(p), "aodAjaxMain": Resposta(OFERTAS_REAL)}
        _, sessao = self.rodar([], rotas, listas=[LISTA])
        self.assertEqual(len(sessao.chamadas), 3)  # lista p1, p2 (repete o token), ofertas

    def test_para_apos_bloqueios_seguidos(self):
        asins = [f"AAAAAAAAA{i}" for i in range(6)]
        c, sessao = self.rodar(asins, {"aodAjaxMain": Resposta("", 503)})
        self.assertEqual(len(sessao.chamadas), coletor.LIMITE_BLOQUEIOS)
        self.assertIn("interrompida", c["observacao"])
        self.assertTrue(any(p >= coletor.PAUSA_APOS_BLOQUEIO for p in self.pausas))

    def test_guarda_html_comprimido(self):
        pasta = Path(self.tmp.name) / "html"
        self.rodar(["8501116432"], {"aodAjaxMain": Resposta(OFERTAS_REAL)}, pasta_html=pasta)
        arq = self.conn.execute("SELECT html_arquivo FROM precos").fetchone()[0]
        self.assertEqual(gzip.decompress(Path(arq).read_bytes()).decode(), OFERTAS_REAL)

    def test_migra_banco_antigo(self):
        antigo = db.conectar(Path(self.tmp.name) / "antigo.db")
        self.addCleanup(antigo.close)
        antigo.executescript(
            "CREATE TABLE precos (id INTEGER PRIMARY KEY, asin TEXT, coleta_id INTEGER, "
            "coletado_em TEXT, status TEXT); INSERT INTO precos VALUES (1,'X',1,'2026-01-01','ok');")
        db.criar_schema(antigo)
        self.assertEqual(antigo.execute("SELECT fonte FROM precos").fetchone()[0], "ofertas")

    def test_sessao_requests_sem_cabecalhos_padrao(self):
        s = cliente_http.nova_sessao("requests")
        self.assertNotIn("Connection", s.headers)
        self.assertEqual(list(s.headers), list(cliente_http.HEADERS))

    def test_eventos_importar_e_atualizar(self):
        csv = Path(self.tmp.name) / "e.csv"
        csv.write_text("nome,inicio,fim\nBlack Friday,2026-11-27,2026-11-27\n", encoding="utf-8")
        db.importar_eventos(self.conn, csv)
        csv.write_text("nome,inicio,fim\nBlack Friday,2026-11-27,2026-11-30\n", encoding="utf-8")
        db.importar_eventos(self.conn, csv)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT fim FROM eventos")], ["2026-11-30"])


class _Servidor(BaseHTTPRequestHandler):
    recebidos: list = []

    def do_GET(self):
        _Servidor.recebidos.append(dict(self.headers))
        if self.path == "/redireciona":
            self.send_response(302)
            self.send_header("Location", "/hz/wishlist/ls/ABCDEFGH1234")
            self.end_headers()
            return
        corpo = ("ação ok" if self.path != "/erro" else "fora").encode("utf-8")
        self.send_response(503 if self.path == "/erro" else 200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


@unittest.skipUnless(shutil.which("curl"), "curl não instalado")
class TestClienteCurl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Servidor)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.cliente = cliente_http.nova_sessao("curl")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_auto_prefere_curl(self):
        self.assertIsInstance(cliente_http.nova_sessao("auto"), cliente_http.ClienteCurl)

    def test_get_ok_utf8_e_cabecalhos(self):
        r = self.cliente.get(self.base + "/pagina")
        self.assertEqual((r.status_code, r.text), (200, "ação ok"))
        h = _Servidor.recebidos[-1]
        self.assertEqual(h["User-Agent"], cliente_http.USER_AGENT)
        self.assertEqual(h["Accept-Language"], "pt-BR,pt;q=0.9")

    def test_status_de_erro_e_redirecionamento(self):
        self.assertEqual(self.cliente.get(self.base + "/erro").status_code, 503)
        r = self.cliente.get(self.base + "/redireciona")
        self.assertTrue(r.url.endswith("/hz/wishlist/ls/ABCDEFGH1234"))

    def test_falha_de_conexao_vira_erro_http(self):
        porta_fechada = "http://127.0.0.1:9/"
        status, html, erro = coletor._baixar(self.cliente, porta_fechada)
        self.assertEqual(erro.status, "erro_http")


if __name__ == "__main__":
    unittest.main()
