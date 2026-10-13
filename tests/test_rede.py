"""Testes do acesso à Amazon (cliente HTTP, bloqueios, preço) e das datas."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from comparador import cliente_http, db, rede
from comparador.rede import parece_bloqueio, parse_preco

PAGINA_CACHORROS = "<html><head><title>Amazon.com.br Algo deu errado</title></head><body></body></html>"


class TestParsePreco(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(parse_preco("R$ 39,90"), 3990)
        self.assertEqual(parse_preco("R$\xa01.234,56"), 123456)
        self.assertEqual(parse_preco("R$ 1234,56"), 123456)
        self.assertIsNone(parse_preco("sem preço"))
        self.assertIsNone(parse_preco(None))


class TestBloqueio(unittest.TestCase):
    def test_marcas_de_bloqueio(self):
        self.assertTrue(parece_bloqueio('<form action="/errors/validateCaptcha"></form>'))
        self.assertTrue(parece_bloqueio('<script>window.location.replace("https://www.amazon.com.br/error/500");</script>'))
        self.assertTrue(parece_bloqueio(PAGINA_CACHORROS))
        self.assertFalse(parece_bloqueio("<html><body>Algo deu errado e não pode ser removido</body></html>"))  # aviso oculto de páginas normais

    def test_dia_e_contado_em_brasilia(self):
        # 01:30 UTC de 11/10 ainda é 22:30 de 10/10 em Brasília.
        self.assertEqual(db.dia_brasil("2026-10-11T01:30:00+00:00"), date(2026, 10, 10))
        self.assertEqual(db.dia_brasil("2026-10-11T03:00:00+00:00"), date(2026, 10, 11))

    def test_sessao_requests_sem_cabecalhos_padrao(self):
        s = cliente_http.nova_sessao("requests")
        self.assertNotIn("Connection", s.headers)
        self.assertEqual(list(s.headers), list(cliente_http.HEADERS))


class _Servidor(BaseHTTPRequestHandler):
    recebidos: list = []
    tempos: list = []      # (caminho, instante em que chegou)

    def do_GET(self):
        _Servidor.recebidos.append(dict(self.headers))
        _Servidor.tempos.append((self.path, time.monotonic()))
        if self.path == "/redireciona":
            self.send_response(302)
            self.send_header("Location", "/hz/wishlist/ls/ABCDEFGH1234")
            self.end_headers()
            return
        corpo = ("ação ok" if self.path != "/erro" else "fora").encode("utf-8")
        self.send_response(503 if self.path == "/erro" else 200)
        if self.path == "/define-cookie":
            self.send_header("Set-Cookie", "session-id=123-456; Path=/")
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

    def test_cliente_curl_explicito(self):
        self.assertIsInstance(cliente_http.nova_sessao("curl"), cliente_http.ClienteCurl)

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

    def test_guarda_cookies_entre_requisicoes(self):
        cliente = cliente_http.nova_sessao("curl")
        cliente.get(self.base + "/define-cookie")
        cliente.get(self.base + "/pagina2")
        self.assertIn("session-id=123-456", _Servidor.recebidos[-1].get("Cookie", ""))

    def test_falha_de_conexao_vira_erro_http(self):
        porta_fechada = "http://127.0.0.1:9/"
        status, html, erro = rede.baixar(self.cliente, porta_fechada)
        self.assertEqual(erro.status, "erro_http")


class _Falsa:
    """Sessão sem get_lote: guarda os instantes em que cada URL foi pedida."""

    def __init__(self, relogio):
        self.relogio, self.pedidos = relogio, []

    def get(self, url, timeout=30):
        self.pedidos.append((url, self.relogio()))
        return cliente_http.Resposta(503 if url.endswith("erro") else 200, "ok", url)


class TestBaixarLote(unittest.TestCase):
    def test_classificar(self):
        R = cliente_http.Resposta
        self.assertIsNone(rede.classificar(R(200, "<html>ok</html>", "u"))[2])
        self.assertEqual(rede.classificar(R(503, "x", "u"))[2].status, "bloqueado")
        self.assertEqual(rede.classificar(R(200, PAGINA_CACHORROS, "u"))[2].status, "bloqueado")
        self.assertEqual(rede.classificar(R(404, "x", "u"))[2].status, "erro_http")
        status, html, erro = rede.classificar(R(0, "TypeError: Failed to fetch", "u"))   # nem chegou
        self.assertEqual((status, html, erro.status), (None, None, "erro_http"))
        self.assertIn("Failed to fetch", erro.detalhe)

    def test_sem_get_lote_respeita_os_atrasos_e_a_ordem(self):
        agora = [0.0]
        dormidas = []

        def dormir(x):
            dormidas.append(x)
            agora[0] += x

        sessao = _Falsa(lambda: agora[0])
        saida = rede.baixar_lote(sessao, ["a", "b/erro", "c"], [0.0, 1.0, 2.5], dormir, relogio=lambda: agora[0])
        self.assertEqual([u for u, _ in sessao.pedidos], ["a", "b/erro", "c"])
        self.assertEqual([t for _, t in sessao.pedidos], [0.0, 1.0, 2.5])
        self.assertEqual([e.status if e else None for _, _, e in saida], [None, "bloqueado", None])
        self.assertEqual(dormidas, [1.0, 1.5])

    def test_get_lote_que_falha_derruba_so_o_lote(self):
        import requests

        class Quebrada:
            def get_lote(self, urls, atrasos, timeout=30):
                raise requests.ConnectionError("navegador: caiu")

        saida = rede.baixar_lote(Quebrada(), ["a", "b"], [0.0, 1.0])
        self.assertEqual([e.status for _, _, e in saida], ["erro_http", "erro_http"])


def _navegador_disponivel() -> bool:
    if not cliente_http._playwright_instalado():
        return False
    try:
        cliente_http.ClienteNavegador().fechar()
        return True
    except Exception:
        return False


@unittest.skipUnless(_navegador_disponivel(), "Playwright ou navegador não instalado")
class TestClienteNavegador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Servidor)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.cliente = cliente_http.ClienteNavegador()
        self.addCleanup(self.cliente.fechar)

    def test_navegacao_depois_fetch_com_cookies(self):
        r1 = self.cliente.get(self.base + "/define-cookie")  # 1ª: navegação real
        self.assertEqual(r1.status_code, 200)
        self.assertIn("ação ok", r1.text)
        r2 = self.cliente.get(self.base + "/pagina2")  # 2ª: fetch na mesma sessão
        self.assertEqual((r2.status_code, r2.text), (200, "ação ok"))
        self.assertIn("session-id=123-456", _Servidor.recebidos[-1].get("Cookie", ""))

    def test_status_de_erro_e_redirecionamento(self):
        self.cliente.get(self.base + "/pagina")
        self.assertEqual(self.cliente.get(self.base + "/erro").status_code, 503)
        self.assertTrue(self.cliente.get(self.base + "/redireciona").url.endswith("/hz/wishlist/ls/ABCDEFGH1234"))

    def test_falha_de_conexao_vira_erro_http(self):
        self.cliente.get(self.base + "/pagina")
        _, _, erro = rede.baixar(self.cliente, "http://127.0.0.1:9/")
        self.assertEqual(erro.status, "erro_http")

    def test_lote_escalonado_na_ordem_e_em_andamento_ao_mesmo_tempo(self):
        self.cliente.get(self.base + "/pagina")
        _Servidor.tempos.clear()
        r = self.cliente.get_lote([f"{self.base}/l{i}" for i in range(4)], [0.0, 0.3, 0.6, 0.9])
        self.assertEqual([(x.status_code, x.text) for x in r], [(200, "ação ok")] * 4)
        self.assertTrue(all(x.ms > 0 for x in r))
        chegadas = {c: t for c, t in _Servidor.tempos}
        self.assertEqual(set(chegadas), {"/l0", "/l1", "/l2", "/l3"})
        ordem = sorted(chegadas, key=chegadas.get)
        self.assertEqual(ordem, ["/l0", "/l1", "/l2", "/l3"])
        self.assertGreater(chegadas["/l3"] - chegadas["/l0"], 0.7)        # escalonadas, não em rajada
        self.assertLess(chegadas["/l3"] - chegadas["/l0"], 3.0)

    def test_lote_na_primeira_chamada_navega_primeiro(self):
        r = self.cliente.get_lote([self.base + "/define-cookie", self.base + "/pagina2"], [0.0, 0.2])
        self.assertEqual([x.status_code for x in r], [200, 200])
        self.assertIn("session-id=123-456", _Servidor.recebidos[-1].get("Cookie", ""))   # a 2ª já usa a sessão da 1ª

    def test_pagina_ou_navegador_que_cai_e_reaberto_e_a_proxima_requisicao_funciona(self):
        self.cliente.get(self.base + "/pagina")
        self.cliente._pagina.close()                                       # a página morre
        saida = rede.baixar_lote(self.cliente, [self.base + "/ok", self.base + "/ok2"], [0.0, 0.1])
        self.assertEqual([e.status for _, _, e in saida], ["erro_http", "erro_http"])   # esta leva falha...
        self.assertEqual(self.cliente.reaberturas, 1)
        r = self.cliente.get(self.base + "/define-cookie")                 # ...e a seguinte já navega de novo
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.cliente.get(self.base + "/pagina2").text, "ação ok")
        self.cliente._navegador.close()                                    # agora o navegador inteiro cai
        with self.assertRaises(Exception):
            self.cliente.get(self.base + "/pagina")
        self.assertEqual(self.cliente.get(self.base + "/pagina").status_code, 200)
        self.assertEqual(self.cliente.reaberturas, 2)

    def test_lote_erro_de_rede_vira_status_0_e_os_outros_seguem(self):
        self.cliente.get(self.base + "/pagina")
        saida = rede.baixar_lote(self.cliente, [self.base + "/ok", "http://127.0.0.1:9/", self.base + "/erro"],
                                 [0.0, 0.1, 0.2])
        self.assertEqual([e.status if e else None for _, _, e in saida], [None, "erro_http", "bloqueado"])


if __name__ == "__main__":
    unittest.main()
