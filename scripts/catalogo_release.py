"""Baixa e publica o banco do catálogo na release "catalogo", com tentativas e conferências.

    python scripts/catalogo_release.py baixar  ALVO DESTINO.db
    python scripts/catalogo_release.py publicar ALVO BANCO.db [--tentativas 3]

baixar: usa a cópia mais recente que passa em três conferências (gzip inteiro, SQLite íntegro, tabela
`catalogo` presente); se a mais nova estiver quebrada (upload cortado, por exemplo), cai para a anterior.
Cada download tem até 3 tentativas, com espera crescente. Sai com 0 e sem arquivo quando a release ou as
cópias do ALVO não existem (começar do zero é correto); com 1 se existem cópias e nenhuma serve (não
começar do zero por engano).
publicar: compacta, envia e confere no GitHub se o arquivo ficou com estado "uploaded" e o mesmo
tamanho; se não, apaga o pedaço e tenta de novo. Sai com 1 se não conseguiu (a poda das cópias antigas só
deve rodar depois de uma publicação confirmada).
"""

import argparse
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RELEASE = "catalogo"
CANDIDATAS = 5          # quantas cópias, da mais nova para a mais velha, tenta antes de desistir
TENTATIVAS = 3
ESPERA = 5              # segundos; dobra a cada tentativa


class Gh:
    """O `gh` do GitHub CLI. Em testes, uma classe com a mesma interface o substitui."""

    def __init__(self, repo: str | None = None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")

    def _rodar(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", *args], capture_output=True, text=True)

    def assets(self) -> list[dict] | None:
        """[{name, size, state}] da release, ou None se a release não existe."""
        r = self._rodar("api", f"repos/{self.repo}/releases/tags/{RELEASE}")
        if r.returncode != 0:
            if "Not Found" in r.stderr or "404" in r.stderr:
                return None
            raise RuntimeError(r.stderr.strip() or "gh api falhou")
        return json.loads(r.stdout)["assets"]

    def baixar(self, nome: str, pasta: Path) -> Path:
        r = self._rodar("release", "download", RELEASE, "--pattern", nome, "--dir", str(pasta), "--clobber")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "gh release download falhou")
        return pasta / nome

    def enviar(self, arquivo: Path) -> None:
        r = self._rodar("release", "upload", RELEASE, str(arquivo), "--clobber")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "gh release upload falhou")

    def criar_release(self) -> None:
        self._rodar("release", "create", RELEASE, "--latest=false", "--title", "Catálogo (dados da varredura)",
                    "--notes", "Bancos SQLite gerados pelo workflow varredura, um por categoria. Baixe o mais recente.")

    def apagar(self, nome: str) -> None:
        self._rodar("release", "delete-asset", RELEASE, nome, "--yes")


def nomes_do_alvo(assets: list[dict], alvo: str) -> list[str]:
    """Cópias do ALVO, da mais nova para a mais velha (o nome tem data e hora)."""
    padrao = re.compile(rf"^catalogo-{re.escape(alvo)}-[0-9-]+\.db\.gz$")
    return sorted((a["name"] for a in assets if padrao.match(a["name"])), reverse=True)


def descompactar_e_conferir(gz: Path, destino: Path) -> str | None:
    """Descompacta `gz` em `destino`. Devolve o problema encontrado, ou None se o banco está bom."""
    try:
        with gzip.open(gz, "rb") as e, open(destino, "wb") as s:
            shutil.copyfileobj(e, s)                       # o CRC do gzip é conferido ao ler até o fim
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        return f"gzip quebrado ({e})"
    try:
        c = sqlite3.connect(f"file:{destino}?mode=ro", uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "SQLite corrompido"
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'catalogo'").fetchone():
                return "sem a tabela catalogo"
        finally:
            c.close()
    except sqlite3.DatabaseError as e:
        return f"não é um SQLite válido ({e})"
    return None


def baixar(alvo: str, destino: Path, gh=None, dormir=time.sleep, log=print) -> int:
    gh = gh or Gh()
    assets = gh.assets()
    if assets is None:
        log("release catalogo ainda não existe; começando do zero")
        return 0
    nomes = nomes_do_alvo(assets, alvo)
    if not nomes:
        log("release sem banco desta categoria; começando do zero")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        for nome in nomes[:CANDIDATAS]:
            gz = None
            for t in range(TENTATIVAS):
                try:
                    gz = gh.baixar(nome, Path(tmp))
                    break
                except RuntimeError as e:
                    log(f"{nome}: download falhou ({e}); tentativa {t + 1} de {TENTATIVAS}")
                    if t + 1 < TENTATIVAS:
                        dormir(ESPERA * 2 ** t)
            if gz is None:
                continue
            problema = descompactar_e_conferir(gz, destino)
            if problema is None:
                log(f"baixado: {nome}")
                return 0
            log(f"{nome}: {problema}; tentando a cópia anterior")
            destino.unlink(missing_ok=True)
    log(f"nenhuma das {min(len(nomes), CANDIDATAS)} cópias mais recentes serviu; não vou começar do zero")
    return 1


def publicar(alvo: str, banco: Path, gh=None, dormir=time.sleep, log=print, agora=time.gmtime,
             tentativas: int = TENTATIVAS) -> int:
    gh = gh or Gh()
    nome = f"catalogo-{alvo}-{time.strftime('%Y-%m-%d-%H%M', agora())}.db.gz"
    with tempfile.TemporaryDirectory() as tmp:
        gz = Path(tmp) / nome
        with open(banco, "rb") as e, gzip.open(gz, "wb") as s:
            shutil.copyfileobj(e, s)
        tamanho = gz.stat().st_size
        if gh.assets() is None:
            gh.criar_release()
        for t in range(tentativas):
            try:
                gh.enviar(gz)
                feito = next((a for a in (gh.assets() or []) if a["name"] == nome), None)
                if feito and feito.get("state") == "uploaded" and feito.get("size") == tamanho:
                    log(f"publicado: {nome} ({tamanho / 1e6:.1f} MB)")
                    return 0
                log(f"{nome}: o GitHub devolveu {feito and (feito.get('state'), feito.get('size'))}, esperado "
                    f"('uploaded', {tamanho}); tentativa {t + 1} de {tentativas}")
            except RuntimeError as e:
                log(f"{nome}: envio falhou ({e}); tentativa {t + 1} de {tentativas}")
            gh.apagar(nome)                                 # não deixa um arquivo cortado como "o mais recente"
            if t + 1 < tentativas:
                dormir(ESPERA * 2 ** t)
    log("não consegui publicar o banco; as cópias antigas ficam como estão")
    return 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baixar")
    b.add_argument("alvo")
    b.add_argument("destino", type=Path)
    u = sub.add_parser("publicar")
    u.add_argument("alvo")
    u.add_argument("banco", type=Path)
    u.add_argument("--tentativas", type=int, default=TENTATIVAS)
    a = p.parse_args()
    if a.cmd == "baixar":
        sys.exit(baixar(a.alvo, a.destino))
    sys.exit(publicar(a.alvo, a.banco, tentativas=a.tentativas))


if __name__ == "__main__":
    main()
