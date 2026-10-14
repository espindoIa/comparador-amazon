"""Baixa e publica na release "catalogo" o snapshot dos subgêneros e o estado da coleta recorrente.

    python scripts/subgeneros_release.py baixar-snapshot DESTINO.json
    python scripts/subgeneros_release.py publicar-snapshot SNAPSHOT.json
    python scripts/subgeneros_release.py baixar-estado DESTINO.json.gz
    python scripts/subgeneros_release.py publicar-estado ESTADO.json.gz

Os dois têm o nome com data e hora (`subgeneros-AAAA-MM-DD-HHMM.json.gz` e `subgeneros-estado-AAAA-MM-DD-HHMM.json.gz`) e a
publicação confere no GitHub o estado e o tamanho antes de apagar as cópias antigas (ficam as MANTER mais recentes), como
`catalogo_release.py`. Os downloads usam a cópia mais recente que se lê.

baixar-snapshot: o snapshot é opcional para o site. Sem release, sem cópia ou sem nenhuma que sirva, sai com 0 e sem arquivo
(o site sai sem subgêneros). baixar-estado: sem cópia, sai com 0 e sem arquivo (começar do zero é correto); com cópias e
nenhuma que sirva, sai com 1 (recomeçar apagaria a pausa depois de bloqueio e o que o ciclo já leu).
publicar-*: sai com 1 se não conseguiu, e então nada é apagado.
"""

import argparse
import gzip
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
sys.path.insert(0, str(PASTA.parent))
from catalogo_release import ESPERA, TENTATIVAS, Gh  # noqa: E402
from comparador.subgeneros import Estado, ler_snapshot  # noqa: E402

MANTER = 4          # cópias de cada tipo que ficam na release
CANDIDATAS = 3      # quantas cópias, da mais nova para a mais velha, tenta antes de desistir
SNAPSHOT = "subgeneros"
ESTADO = "subgeneros-estado"


def nomes_de(assets: list[dict], prefixo: str) -> list[str]:
    """Cópias do tipo `prefixo`, da mais nova para a mais velha (o nome tem data e hora)."""
    padrao = re.compile(rf"^{re.escape(prefixo)}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{4}}\.json\.gz$")
    return sorted((a["name"] for a in assets if padrao.match(a["name"])), reverse=True)


def _snapshot_bom(gz: Path, destino: Path) -> str | None:
    try:
        with gzip.open(gz, "rb") as e, open(destino, "wb") as s:
            shutil.copyfileobj(e, s)
        ler_snapshot(destino)
    except (OSError, EOFError, ValueError) as e:
        destino.unlink(missing_ok=True)
        return str(e)
    return None


def _estado_bom(gz: Path, destino: Path) -> str | None:
    try:
        Estado.ler(gz)
    except ValueError as e:
        return str(e)
    shutil.copyfile(gz, destino)
    return None


def baixar(prefixo: str, destino: Path, conferir, gh=None, dormir=time.sleep, log=print) -> int | None:
    """Baixa a cópia mais recente de `prefixo` que `conferir(gz, destino)` aceita (devolve o problema, ou None se serve).
    0: baixou; None: não há cópia nenhuma; 1: há cópias e nenhuma serviu."""
    gh = gh or Gh()
    assets = gh.assets()
    nomes = nomes_de(assets, prefixo) if assets is not None else []
    if not nomes:
        log(f"release sem cópia de {prefixo}")
        return None
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
            problema = conferir(gz, destino)
            if problema is None:
                log(f"baixado: {nome}")
                return 0
            log(f"{nome}: {problema}; tentando a cópia anterior")
    log(f"nenhuma das {min(len(nomes), CANDIDATAS)} cópias mais recentes de {prefixo} serviu")
    return 1


def publicar(prefixo: str, arquivo: Path, gh=None, dormir=time.sleep, log=print, agora=time.gmtime, tentativas: int = TENTATIVAS) -> int:
    gh = gh or Gh()
    nome = f"{prefixo}-{time.strftime('%Y-%m-%d-%H%M', agora())}.json.gz"
    with tempfile.TemporaryDirectory() as tmp:
        gz = Path(tmp) / nome
        if arquivo.suffix == ".gz":                          # o estado já vem compactado
            shutil.copyfile(arquivo, gz)
        else:
            with open(arquivo, "rb") as e, gzip.open(gz, "wb") as s:
                shutil.copyfileobj(e, s)
        tamanho = gz.stat().st_size
        if gh.assets() is None:
            gh.criar_release()
        for t in range(tentativas):
            try:
                gh.enviar(gz)
                feito = next((a for a in (gh.assets() or []) if a["name"] == nome), None)
                if feito and feito.get("state") == "uploaded" and feito.get("size") == tamanho:
                    log(f"publicado: {nome} ({tamanho / 1e3:.0f} KB)")
                    for velho in nomes_de(gh.assets() or [], prefixo)[MANTER:]:
                        gh.apagar(velho)
                    return 0
                log(f"{nome}: o GitHub devolveu {feito and (feito.get('state'), feito.get('size'))}, esperado ('uploaded', {tamanho}); "
                    f"tentativa {t + 1} de {tentativas}")
            except RuntimeError as e:
                log(f"{nome}: envio falhou ({e}); tentativa {t + 1} de {tentativas}")
            gh.apagar(nome)                                  # não deixa um arquivo cortado como "o mais recente"
            if t + 1 < tentativas:
                dormir(ESPERA * 2 ** t)
    log(f"não consegui publicar {prefixo}; as cópias antigas ficam como estão")
    return 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for nome in ("baixar-snapshot", "baixar-estado"):
        sub.add_parser(nome).add_argument("destino", type=Path)
    for nome in ("publicar-snapshot", "publicar-estado"):
        sub.add_parser(nome).add_argument("arquivo", type=Path)
    a = p.parse_args()
    if a.cmd == "baixar-snapshot":
        r = baixar(SNAPSHOT, a.destino, _snapshot_bom)
        if r:                                             # nenhuma serviu: o site sai sem subgêneros, mas o aviso aparece
            print("::warning::nenhum snapshot de subgêneros serviu; o site sai sem eles")
        sys.exit(0)
    if a.cmd == "baixar-estado":
        sys.exit(baixar(ESTADO, a.destino, _estado_bom) or 0)
    sys.exit(publicar(SNAPSHOT if a.cmd == "publicar-snapshot" else ESTADO, a.arquivo))


if __name__ == "__main__":
    main()
