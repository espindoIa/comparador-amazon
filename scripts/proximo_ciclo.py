"""Decide quando começa a próxima leitura de uma sequência de coleta (o "anel" de execuções de varredura.yml).

Uso: python scripts/proximo_ciclo.py BANCO --alvo vendidos --inicio-run INSTANTE_UTC
Escreve duas linhas: o instante (UTC, ISO) em que a próxima leitura deve começar e o motivo (ou, com --json, um objeto com os dois).

O catálogo é lido por inteiro uma vez por ciclo (3, 6, 12 ou 24 h; ver comparador/ritmo.py). Cada ciclo é uma janela
que parte da meia-noite de Brasília, e a leitura de cada sequência começa um pouco depois do início da janela (10 min
de defasagem por sequência, mais um sorteio de até 10 min), para as três não baterem na Amazon juntas nem a cada
ciclo no mesmo segundo. Só se continua agora, sem esperar a próxima janela, se a janela atual não fechou e esta
execução terminou limpa depois de ler páginas de verdade (o orçamento de tempo acabou); depois de um problema, quem
decide é a próxima janela (depois de um bloqueio também: recomeçar logo seria, na prática, trocar de servidor e de IP por
causa do bloqueio). Uma pausa gravada no banco antes de 15/10/2026 ainda vale, e se a publicação falhou o que foi lido se perdeu, então
a próxima leitura espera também algumas horas (senão a Amazon seria consultada de novo, todo ciclo, à toa).
"""

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comparador import db, ritmo, varredura  # noqa: E402

MIN_PAGINAS = 500            # menos que isto e a execução "não andou": não vale continuar já
ENTRE_EXECUCOES_MIN = 10     # distância mínima entre o começo de duas execuções seguidas (nunca um laço apertado)
DEFASAGEM_MIN = 10           # cada sequência começa tantos minutos depois da anterior
SORTEIO_S = 600


def defasagem(alvo: str) -> timedelta:
    nomes = list(varredura.PARTICOES_VENDIDOS)
    return timedelta(minutes=DEFASAGEM_MIN * (nomes.index(alvo) if alvo in nomes else 0))


def decidir(conn: sqlite3.Connection, alvo: str, inicio_run: datetime, agora: datetime,
            sorteio=random.uniform, publicacao_falhou: bool = False) -> tuple[datetime, str]:
    """(instante da próxima leitura, motivo). Se a publicação falhou, o que foi lido se perdeu: ler de novo logo só
    repetiria o pedido à Amazon, então espera pelo menos ritmo.PAUSA_BASE_H horas."""
    config = varredura.ler_config(conn)
    ciclo = ritmo.ciclo_guardado(config)
    janela = datetime.fromisoformat(varredura.inicio_do_ciclo(ciclo, agora))
    fim = janela + timedelta(hours=ciclo)
    incompleta = varredura.proxima_fatia(conn, varredura.GRUPO_VENDIDOS, janela.isoformat(timespec="seconds")) is not None
    e = conn.execute("SELECT paginas, bloqueios, observacao FROM execucoes WHERE iniciada_em >= ? "
                     "ORDER BY id DESC LIMIT 1", (inicio_run.isoformat(timespec="seconds"),)).fetchone()
    obs = (e["observacao"] if e else None) or ""
    limpa = e is not None and not e["bloqueios"] and "interrompida" not in obs and varredura.AVISO_LAYOUT not in obs
    if incompleta and limpa and e["paginas"] >= MIN_PAGINAS and fim - agora >= timedelta(minutes=varredura.FOLGA_JANELA_MIN):
        quando, motivo = agora, f"o ciclo de {ciclo} h não fechou; continua"
    else:
        quando = fim + defasagem(alvo) + timedelta(seconds=sorteio(0, SORTEIO_S))
        motivo = f"próximo ciclo de {ciclo} h (janela das {fim.astimezone(varredura.db.BRASILIA):%d/%m %H:%M} de Brasília)"
    if (pausa := ritmo.pausa_ate(config)) and pausa > quando:
        quando, motivo = pausa, f"pausa depois de bloqueio, até {pausa.astimezone(varredura.db.BRASILIA):%d/%m %H:%M} de Brasília"
    if publicacao_falhou and quando < agora + timedelta(hours=ritmo.PAUSA_BASE_H):
        quando, motivo = agora + timedelta(hours=ritmo.PAUSA_BASE_H), "a publicação falhou; espera para não repetir a leitura logo"
    minimo = inicio_run + timedelta(minutes=ENTRE_EXECUCOES_MIN)
    if quando < minimo:
        quando, motivo = minimo, motivo + f" (e pelo menos {ENTRE_EXECUCOES_MIN} min depois do começo desta)"
    return quando, motivo


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("banco", type=Path)
    p.add_argument("--alvo", required=True)
    p.add_argument("--inicio-run", required=True, help="instante (UTC, ISO) em que esta execução começou")
    p.add_argument("--publicacao-falhou", action="store_true", help="a publicação do banco desta execução falhou")
    p.add_argument("--json", action="store_true", help='escreve {"quando": ..., "motivo": ...} em vez das duas linhas')
    a = p.parse_args()
    conn = db.abrir_leitura(a.banco, "catálogo")
    conn.row_factory = sqlite3.Row
    try:
        quando, motivo = decidir(conn, a.alvo, datetime.fromisoformat(a.inicio_run), datetime.now(timezone.utc),
                                  publicacao_falhou=a.publicacao_falhou)
    finally:
        conn.close()
    quando_utc = quando.astimezone(timezone.utc).isoformat(timespec="seconds")
    if a.json:
        print(json.dumps({"quando": quando_utc, "motivo": motivo}, ensure_ascii=False))
    else:
        print(quando_utc)
        print(motivo)


if __name__ == "__main__":
    main()
