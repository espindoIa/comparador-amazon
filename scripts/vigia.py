"""Quais sequências de coleta ficaram sem anel de execuções e precisam ser reiniciadas (vigia.yml).

Uso: python scripts/vigia.py RUNS.json [RUNS2.json ...] --alvos vendidos vendidos-b vendidos-c
Cada arquivo é a saída de `gh run list --json status,displayTitle,createdAt`. Escreve, um por linha, os alvos sem nenhuma
execução (de varredura ou de espera) em andamento ou criada há pouco. O título de cada execução termina com o alvo, ou é
"todas" (disparo manual das três).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

ATIVAS = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
RECENTE_MIN = 20     # uma execução criada há menos que isto ainda pode estar agendando a próxima


def sem_anel(alvos: list[str], execucoes: list[dict], agora: datetime) -> list[str]:
    def cobre(e: dict, alvo: str) -> bool:
        palavras = (e.get("displayTitle") or "").split()
        return alvo in palavras or "todas" in palavras

    def viva(e: dict) -> bool:
        criada = datetime.fromisoformat(e["createdAt"].replace("Z", "+00:00"))
        return e.get("status") in ATIVAS or agora - criada < timedelta(minutes=RECENTE_MIN)

    return [a for a in alvos if not any(cobre(e, a) and viva(e) for e in execucoes)]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("arquivos", nargs="+")
    p.add_argument("--alvos", nargs="+", required=True)
    a = p.parse_args()
    execucoes = []
    for arq in a.arquivos:
        with open(arq, encoding="utf-8") as f:
            execucoes += json.load(f)
    for alvo in sem_anel(a.alvos, execucoes, datetime.now(timezone.utc)):
        print(alvo)


if __name__ == "__main__":
    main()
