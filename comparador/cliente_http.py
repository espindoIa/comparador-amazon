"""Clientes HTTP, do mais robusto ao mais simples.

1. Navegador (Playwright + Chrome/Edge/Chromium): abre a primeira página de verdade e
   faz as seguintes com `fetch` dentro dela, com a mesma sessão. Nos testes, do mesmo IP
   em que curl e requests recebiam 503, leu os 82 itens (9 páginas) de uma lista e as
   ofertas de cada livro, tudo com 200.
2. curl do sistema: passou onde o requests falhava (2 de 3 contra 0 de 3), mas a
   paginação da lista recebeu 503 em todas as tentativas.
3. requests: alternativa final, com cabeçalhos mínimos.

`--cliente auto` usa só o navegador: se ele não abre, a coleta para e diz por quê, em vez de cair em silêncio no curl ou
no requests (que a Amazon bloqueia, e um bloqueio grava no banco uma pausa de horas). Eles só valem se pedidos
(`--cliente curl`, `--cliente requests`).
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
    status_code: int      # 0 = a requisição nem chegou (rede, tempo esgotado)
    text: str
    url: str
    ms: float = 0.0       # tempo da requisição (só o navegador mede)


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


# Cada requisição tem tempo máximo (AbortSignal.timeout): sem isso, uma conexão pendurada travaria a
# varredura inteira. Erro de rede vira status 0, em vez de derrubar o lote todo.
_FETCH_JS = """async ([u, ms]) => {
    const t0 = performance.now();
    try {
        const r = await fetch(u, {credentials: 'include', signal: AbortSignal.timeout(ms)});
        return [r.status, await r.text(), r.url, performance.now() - t0];
    } catch (e) {
        return [0, String(e), u, performance.now() - t0];
    }
}"""

# Várias páginas ao mesmo tempo: a i-ésima só começa depois de `atraso` segundos, o que espalha as
# requisições do lote no tempo (o ritmo que a Amazon enxerga é o programado, sem rajadas).
_LOTE_JS = """async ([urls, atrasos, ms]) => Promise.all(urls.map(async (u, i) => {
    if (atrasos[i] > 0) await new Promise(ok => setTimeout(ok, atrasos[i] * 1000));
    const t0 = performance.now();
    try {
        const r = await fetch(u, {credentials: 'include', signal: AbortSignal.timeout(ms)});
        return [r.status, await r.text(), r.url, performance.now() - t0];
    } catch (e) {
        return [0, String(e), u, performance.now() - t0];
    }
}))"""


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
        self._contexto = None
        self._criar_pagina()
        self.reaberturas = 0
        self._final = weakref.finalize(self, _fechar_playwright, self._navegador, self._pw)

    def _criar_pagina(self) -> None:
        """Contexto e página novos; a próxima requisição é uma navegação de verdade (cria a sessão)."""
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self._contexto = self._navegador.new_context(
            locale="pt-BR",
            user_agent=None,  # o do próprio navegador
            # Só para ambientes com proxy que intercepta TLS (ex.: sandbox de testes).
            ignore_https_errors=os.environ.get("COMPARADOR_IGNORAR_TLS") == "1",
            **({"proxy": _proxy(proxy)} if proxy else {}),
        )
        self._pagina = self._contexto.new_page()
        self._aberta = False

    def _reabrir(self) -> None:
        """Recuperação de queda do navegador ou da página (não de bloqueio: isso continua parando a execução).
        Abre contexto e página novos, e o navegador de novo se ele morreu."""
        self.reaberturas += 1
        try:
            self._contexto.close()
        except Exception:
            pass
        try:
            if not self._navegador.is_connected():
                self._final.detach()
                _fechar_playwright(self._navegador, None)
                self._navegador = self._abrir_navegador()
                self._final = weakref.finalize(self, _fechar_playwright, self._navegador, self._pw)
            self._criar_pagina()
        except Exception:
            pass   # a próxima requisição falha de novo e a execução para depois de 3 lotes com falha

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
            status, texto, url_final, ms = self._pagina.evaluate(_FETCH_JS, [url, timeout * 1000])
            return Resposta(int(status), texto, url_final or url, ms)
        except Exception as e:
            if "Timeout" in type(e).__name__:
                raise requests.Timeout(str(e)) from e
            self._reabrir()
            raise requests.ConnectionError(f"navegador: {e}") from e

    def get_lote(self, urls: list[str], atrasos: list[float], timeout: float = 30) -> list[Resposta]:
        """Várias páginas em andamento ao mesmo tempo, a i-ésima começando `atrasos[i]` s depois."""
        if not self._aberta:
            # A primeira é navegação de verdade (cria a sessão); as outras vêm depois dela.
            primeira = self.get(urls[0], timeout)
            if len(urls) == 1:
                return [primeira]
            base = atrasos[1]
            return [primeira, *self.get_lote(urls[1:], [a - base for a in atrasos[1:]], timeout)]
        try:
            self._pagina.set_default_timeout((timeout + max(atrasos, default=0)) * 1000)
            brutas = self._pagina.evaluate(_LOTE_JS, [urls, atrasos, timeout * 1000])
        except Exception as e:
            if "Timeout" in type(e).__name__:
                raise requests.Timeout(str(e)) from e
            self._reabrir()
            raise requests.ConnectionError(f"navegador: {e}") from e
        return [Resposta(int(st), txt, u or url, ms) for (st, txt, u, ms), url in zip(brutas, urls)]

    def fechar(self) -> None:
        _fechar_playwright(self._navegador, self._pw)


def _proxy(servidor: str) -> dict:
    """Proxy do ambiente, respeitando NO_PROXY como curl e requests fazem."""
    excecoes = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    excecoes = ",".join(x for x in {*excecoes.split(","), "localhost", "127.0.0.1"} if x.strip())
    return {"server": servidor, "bypass": excecoes}


def _fechar_playwright(navegador, pw) -> None:
    for acao in [navegador.close] + ([pw.stop] if pw else []):
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


def problema_do_cliente(cliente: str) -> str | None:
    """Por que `nova_sessao(cliente)` nem chega a tentar o cliente (módulo ou programa ausente), ou None. Não abre
    nada: o navegador ainda pode falhar na hora, se não houver Chrome, Edge nem Chromium."""
    if cliente in ("auto", "navegador") and not _playwright_instalado():
        return "o módulo playwright não está instalado (pip install -r requirements.txt)"
    if cliente == "curl" and not shutil.which("curl"):
        return "curl não encontrado no sistema; use --cliente requests"
    return None


def nova_sessao(cliente: str = "auto"):
    """cliente: 'auto' (só o navegador; sem ele, para), 'navegador', 'curl' ou 'requests'. O curl e o requests só
    são usados quando pedidos: nos testes, o curl recebeu 503 na paginação da lista e o requests, captcha ou 503."""
    if cliente in ("auto", "navegador"):
        motivo = problema_do_cliente(cliente)
        if motivo is None:
            try:
                return ClienteNavegador()
            except Exception as e:
                motivo = str(e)
        mensagem = f"não consegui abrir o navegador: {motivo}"
        if cliente == "auto":
            mensagem += ("\nO cliente automático só usa o navegador: o curl recebeu 503 na paginação da lista e o "
                         "requests, captcha ou 503, e um bloqueio grava no banco uma pausa de horas. "
                         "Para ler assim mesmo, use --cliente curl ou --cliente requests.")
        raise SystemExit(mensagem)
    if cliente == "curl":
        if motivo := problema_do_cliente(cliente):
            raise SystemExit(motivo)
        return ClienteCurl(shutil.which("curl"))
    return sessao_requests()
