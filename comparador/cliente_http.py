"""Clientes HTTP, do mais robusto ao mais simples.

1. Navegador (Playwright + Chrome/Edge/Chromium): abre a primeira página de verdade e
   faz as seguintes com `fetch` dentro dela, com a mesma sessão. Nos testes, do mesmo IP
   em que curl e requests recebiam 503, leu os 82 itens (9 páginas) de uma lista e as
   ofertas de cada livro, tudo com 200.
2. curl do sistema: passou onde o requests falhava (2 de 3 contra 0 de 3), mas a
   paginação da lista recebeu 503 em todas as tentativas.
3. requests: alternativa final, com cabeçalhos mínimos.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Exatamente estes cabeçalhos, nesta ordem. Os padrões do `requests` (com
# "Connection: keep-alive") levavam a captcha em todas as requisições nos testes.
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


@dataclass
class Resposta:
    status_code: int
    text: str
    url: str


class ClienteCurl:
    """Interface mínima igual à do requests.Session (get -> .status_code/.text/.url).

    Guarda os cookies entre requisições, como um navegador: a paginação da lista de
    desejos usa um token que provavelmente depende da sessão criada pela página 1.
    """

    def __init__(self, executavel: str):
        self.executavel = executavel
        fd, self.cookies = tempfile.mkstemp(prefix="comparador-cookies-", suffix=".txt")
        os.close(fd)
        weakref.finalize(self, _apagar, self.cookies)

    def get(self, url: str, timeout: float = 30) -> Resposta:
        with tempfile.TemporaryDirectory() as d:
            corpo = Path(d) / "corpo"
            cmd = [
                self.executavel, "-sS", "-L", "--compressed",
                "--max-time", str(int(timeout)),
                "-b", self.cookies, "-c", self.cookies,
                "-A", USER_AGENT,
                "-H", "Accept-Language: pt-BR,pt;q=0.9",
                "-o", str(corpo),
                "-w", "%{http_code} %{url_effective}",
                url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
            except subprocess.TimeoutExpired as e:
                raise requests.Timeout(f"curl excedeu {timeout}s") from e
            if proc.returncode != 0:
                raise requests.ConnectionError(f"curl saiu com código {proc.returncode}: {proc.stderr.strip()}")
            codigo, _, url_final = proc.stdout.strip().partition(" ")
            texto = corpo.read_text(encoding="utf-8", errors="replace") if corpo.exists() else ""
            return Resposta(int(codigo), texto, url_final or url)


def _apagar(caminho: str) -> None:
    try:
        os.remove(caminho)
    except OSError:
        pass


def sessao_requests() -> requests.Session:
    s = requests.Session()
    s.headers.clear()
    s.headers.update(HEADERS)
    return s


_FETCH_JS = """async u => {
    const r = await fetch(u, {credentials: 'include'});
    return [r.status, await r.text(), r.url];
}"""


class ClienteNavegador:
    """Mesma interface do requests.Session, usando um navegador real.

    O navegador é escolhido nesta ordem: COMPARADOR_NAVEGADOR (caminho do executável),
    Google Chrome instalado, Microsoft Edge instalado, Chromium do Playwright
    (`python -m playwright install chromium`).
    """

    def __init__(self):
        from playwright.sync_api import sync_playwright  # importa só se for usado

        self._pw = sync_playwright().start()
        try:
            self._navegador = self._abrir_navegador()
        except Exception:
            self._pw.stop()
            raise
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        contexto = self._navegador.new_context(
            locale="pt-BR",
            user_agent=None,  # o do próprio navegador
            # Só para ambientes com proxy que intercepta TLS (ex.: sandbox de testes).
            ignore_https_errors=os.environ.get("COMPARADOR_IGNORAR_TLS") == "1",
            **({"proxy": _proxy(proxy)} if proxy else {}),
        )
        self._pagina = contexto.new_page()
        self._aberta = False
        weakref.finalize(self, _fechar_playwright, self._navegador, self._pw)

    def _abrir_navegador(self):
        tipo = self._pw.chromium
        caminho = os.environ.get("COMPARADOR_NAVEGADOR")
        if caminho:
            return tipo.launch(executable_path=caminho)
        erros = []
        for canal in ("chrome", "msedge", None):
            try:
                return tipo.launch(channel=canal) if canal else tipo.launch()
            except Exception as e:  # navegador não instalado: tenta o próximo
                erros.append(f"{canal or 'chromium do playwright'}: {str(e).splitlines()[0]}")
        raise RuntimeError(
            "nenhum navegador encontrado. Instale o Chrome ou rode "
            "`python -m playwright install chromium`. Detalhes: " + " | ".join(erros)
        )

    def get(self, url: str, timeout: float = 30) -> Resposta:
        try:
            if not self._aberta:
                # Primeira requisição: navegação real, que cria a sessão (cookies etc.).
                resp = self._pagina.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                self._aberta = True
                return Resposta(resp.status if resp else 0, self._pagina.content(), self._pagina.url)
            self._pagina.set_default_timeout(timeout * 1000)
            status, texto, url_final = self._pagina.evaluate(_FETCH_JS, url)
            return Resposta(int(status), texto, url_final or url)
        except Exception as e:
            if "Timeout" in type(e).__name__:
                raise requests.Timeout(str(e)) from e
            raise requests.ConnectionError(f"navegador: {e}") from e

    def fechar(self) -> None:
        _fechar_playwright(self._navegador, self._pw)


def _proxy(servidor: str) -> dict:
    """Proxy do ambiente, respeitando NO_PROXY como curl e requests fazem."""
    excecoes = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    excecoes = ",".join(x for x in {*excecoes.split(","), "localhost", "127.0.0.1"} if x.strip())
    return {"server": servidor, "bypass": excecoes}


def _fechar_playwright(navegador, pw) -> None:
    for acao in (navegador.close, pw.stop):
        try:
            acao()
        except Exception:
            pass


def _playwright_instalado() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def nova_sessao(cliente: str = "auto"):
    """cliente: 'auto' (navegador > curl > requests), 'navegador', 'curl' ou 'requests'."""
    if cliente == "navegador" or (cliente == "auto" and _playwright_instalado()):
        try:
            return ClienteNavegador()
        except Exception as e:
            if cliente == "navegador":
                raise SystemExit(f"não consegui abrir o navegador: {e}")
            print(f"aviso: navegador indisponível ({e}); usando curl/requests")
    if cliente in ("auto", "curl"):
        curl = shutil.which("curl")
        if curl:
            return ClienteCurl(curl)
        if cliente == "curl":
            raise SystemExit("curl não encontrado no sistema; use --cliente requests")
    return sessao_requests()
