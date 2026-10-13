"""Espera até o instante da próxima leitura, em saltos curtos (espera.yml).

Uso: python scripts/espera.py INSTANTE_UTC
Dorme até o instante e escreve "disparar"; se falta mais que um salto (um job do GitHub vive no máximo 6 h), dorme só um
salto e escreve "reencadear": o workflow então agenda uma espera nova com o mesmo instante.
"""

import argparse
import sys
import time
from datetime import datetime, timezone

SALTO_MAX_S = 4 * 3600 + 55 * 60


def plano(quando: datetime, agora: datetime, salto_max: float = SALTO_MAX_S) -> tuple[str, float]:
    """("disparar" | "reencadear", segundos a dormir)."""
    falta = (quando - agora).total_seconds()
    if falta > salto_max:
        return "reencadear", salto_max
    return "disparar", max(0.0, falta)


def instante(texto: str) -> datetime:
    """ISO 8601 com fuso (aceita o "Z" do fim). Sem fuso não dá para saber quanto falta, então é recusado."""
    try:
        quando = datetime.fromisoformat(texto.replace("Z", "+00:00") if texto.endswith("Z") else texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{texto!r} não é um instante ISO 8601 (ex.: 2026-10-13T18:00:00+00:00)") from None
    if quando.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{texto!r} não tem fuso; use por exemplo 2026-10-13T18:00:00+00:00 (ou terminado em Z)")
    return quando


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("instante", type=instante, help="instante UTC até o qual esperar, ISO 8601 com fuso (ex.: 2026-10-13T18:00:00+00:00)")
    a = p.parse_args()
    acao, segundos = plano(a.instante, datetime.now(timezone.utc))
    print(f"{acao}: dormindo {segundos:.0f} s", file=sys.stderr, flush=True)
    time.sleep(segundos)
    print(acao)


if __name__ == "__main__":
    main()
