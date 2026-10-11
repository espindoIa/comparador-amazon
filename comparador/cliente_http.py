"""Clientes HTTP.

Nos testes, o `requests` levava 503/captcha onde o `curl`, na mesma URL e no mesmo
minuto, recebia a página normal (2 de 3 contra 0 de 3 numa comparação intercalada).
Por isso o padrão é usar o curl do sistema (incluso no Windows 10+, macOS e Linux),
com o `requests` como alternativa.
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


def nova_sessao(cliente: str = "auto"):
    """cliente: 'auto' (curl se existir, senão requests), 'curl' ou 'requests'."""
    if cliente in ("auto", "curl"):
        curl = shutil.which("curl")
        if curl:
            return ClienteCurl(curl)
        if cliente == "curl":
            raise SystemExit("curl não encontrado no sistema; use --cliente requests")
    return sessao_requests()
