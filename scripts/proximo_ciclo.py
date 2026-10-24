"""Decide quando começa a próxima leitura de uma sequência de coleta (o "anel" de execuções de varredura.yml).

Uso: python scripts/proximo_ciclo.py BANCO --alvo vendidos --inicio-run INSTANTE_UTC
Escreve duas linhas: o instante (UTC, ISO) em que a próxima leitura deve começar e o motivo (ou, com --json, um objeto com os dois).

O catálogo é lido por inteiro duas vezes por dia (ciclo de 12 h; ver comparador/ritmo.py). A leitura de cada
sequência começa num horário fixo de Brasília — 03:10, para a passada da manhã caber antes das 8h, e 18:10, para a
da tarde começar depois das 18h — mais 10 min de defasagem por sequência e um sorteio de até 10 min, para as três
não baterem na Amazon juntas. O cron do Actions é só rede de segurança; quem marca a hora é este script.

Continua agora, sem esperar o próximo horário, em dois casos: a janela atual não fechou e esta execução terminou
limpa depois de ler páginas de verdade (o orçamento de tempo acabou); ou a execução parou por bloqueio ou por
falhas seguidas e ainda há fatias por ler. Nesse segundo caso a pausa de horas guardada no banco vale primeiro
(não se retenta em minutos: cada execução cai num IP novo). Aviso de layout ou execução curta, sem bloqueio,
esperam o próximo horário, para um parser quebrado não virar um laço. Se a publicação falhou, o que foi lido se
perdeu, então a próxima leitura espera também algumas horas.
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
# Hora de Brasília em que cada passada pode começar (antes da defasagem). 03:10 para a da manhã caber antes das 8h
# no teto de ~15 páginas/min; 18:10 para a da tarde começar depois das 18h. O cron do Actions está em UTC.
AGENDA_BRT = ((3, 10), (18, 10))


def defasagem(alvo: str) -> timedelta:
    nomes = list(varredura.PARTICOES_VENDIDOS)
    return timedelta(minutes=DEFASAGEM_MIN * (nomes.index(alvo) if alvo in nomes else 0))


def proximos_da_agenda(agora: datetime, atraso: timedelta, n: int = 4) -> list[datetime]:
    """Os próximos `n` horários da agenda estritamente depois de `agora`, já com `atraso` (defasagem e sorteio)."""
    local = agora.astimezone(db.BRASILIA)
    meia_noite = local.replace(hour=0, minute=0, second=0, microsecond=0)
    saida = []
    for dia in range(3):
        for hora, minuto in AGENDA_BRT:
            instante = (meia_noite + timedelta(days=dia, hours=hora, minutes=minuto) + atraso).astimezone(timezone.utc)
            if instante > agora:
                saida.append(instante)
                if len(saida) == n:
                    return saida
    return saida


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
    parada = e is not None and bool(e["bloqueios"] or "interrompida" in obs)
    atraso = defasagem(alvo) + timedelta(seconds=sorteio(0, SORTEIO_S))
    if incompleta and limpa and e["paginas"] >= MIN_PAGINAS and fim - agora >= timedelta(minutes=varredura.FOLGA_JANELA_MIN):
        quando, motivo = agora, f"o ciclo de {ciclo} h não fechou; continua"
    elif incompleta and parada:
        quando, motivo = agora, "a execução parou com fatias por ler; retoma assim que a pausa acaba"
    elif ciclo >= ritmo.CICLO_OPERACIONAL:
        horarios = proximos_da_agenda(agora, atraso)
        # Janela já fechada: um horário que ainda cai dentro dela não leria nada. Pula para o da janela seguinte.
        quando = horarios[0] if incompleta else next(h for h in horarios if h >= fim)
        motivo = (f"próxima leitura do ciclo de {ciclo} h "
                  f"({quando.astimezone(db.BRASILIA):%d/%m %H:%M} de Brasília)")
    else:
        quando = fim + atraso
        motivo = f"próximo ciclo de {ciclo} h (janela das {fim.astimezone(db.BRASILIA):%d/%m %H:%M} de Brasília)"
    if (pausa := ritmo.pausa_ate(config)) and pausa > quando:
        quando, motivo = pausa, f"pausa depois de bloqueio, até {pausa.astimezone(db.BRASILIA):%d/%m %H:%M} de Brasília"
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
