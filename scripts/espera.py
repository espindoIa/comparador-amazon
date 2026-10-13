"""Espera até o instante da próxima leitura, em saltos curtos (espera.yml).

Uso: python scripts/espera.py INSTANTE_UTC
Dorme até o instante e escreve "disparar"; se falta mais que um salto (um job do GitHub vive no máximo 6 h), dorme só um
salto e escreve "reencadear": o workflow então agenda uma espera nova com o mesmo instante.
"""

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


def main() -> None:
    quando = datetime.fromisoformat(sys.argv[1])
    acao, segundos = plano(quando, datetime.now(timezone.utc))
    print(f"{acao}: dormindo {segundos:.0f} s", file=sys.stderr, flush=True)
    time.sleep(segundos)
    print(acao)


if __name__ == "__main__":
    main()
