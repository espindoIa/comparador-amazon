"""Decide se esta execução da varredura deve disparar a próxima, sem esperar o horário agendado.

Uso: python scripts/encadear.py BANCO --desde INSTANTE_UTC [--encadeadas N]

O GitHub atrasa as execuções agendadas em horas, e um dia de coleta pode levar mais de uma execução
(cada sequência de coleta lê ~3 mil páginas por dia; a execução tem 165 min). Encadear leva o dia até o fim
em sequência, sem esperar. Cada sequência (banco) decide por conta própria. Sai com 0 e escreve
"sim" se deve encadear; com 10 e escreve o motivo se não deve. Só encadeia se TUDO isto vale:
- o dia (Brasília) ainda não está completo;
- esta execução (a que começou depois de --desde) leu páginas de verdade e terminou limpa: 0 bloqueios, sem
  "interrompida", sem aviso de layout (depois de um problema, quem decide é o próximo horário agendado);
- ainda não houve MAX_ENCADEADAS execuções seguidas encadeadas (o contador viaja na própria execução).
O dia só é considerado completo pelo banco: se ele não mudou, não há execução nova e não se encadeia.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comparador import varredura  # noqa: E402

MAX_ENCADEADAS = 5
MIN_PAGINAS = 500


def decidir(conn: sqlite3.Connection, desde: str, encadeadas: int = 0, agora: str | None = None) -> str | None:
    """None = encadear; senão, o motivo para não encadear."""
    if encadeadas >= MAX_ENCADEADAS:
        return f"já foram {encadeadas} execuções seguidas encadeadas; o próximo horário agendado continua"
    dia = varredura.inicio_do_dia()
    if varredura.proxima_fatia(conn, varredura.GRUPO_VENDIDOS, dia) is None:
        return "o dia está completo"
    e = conn.execute("SELECT paginas, bloqueios, observacao FROM execucoes WHERE iniciada_em >= ? "
                     "ORDER BY id DESC LIMIT 1", (desde,)).fetchone()
    if e is None:
        return "esta execução não leu nada"
    paginas, bloqueios, obs = e
    obs = obs or ""
    if paginas < MIN_PAGINAS:
        return f"esta execução leu só {paginas} páginas"
    if bloqueios:
        return f"esta execução teve {bloqueios} bloqueios"
    for sinal in ("interrompida", varredura.AVISO_LAYOUT):
        if sinal in obs:
            return f"esta execução avisou: {obs}"
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("banco", type=Path)
    p.add_argument("--desde", required=True, help="instante (UTC, ISO) em que esta execução começou")
    p.add_argument("--encadeadas", type=int, default=0)
    a = p.parse_args()
    conn = sqlite3.connect(f"file:{a.banco}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        motivo = decidir(conn, a.desde, a.encadeadas)
    finally:
        conn.close()
    if motivo:
        print(f"não encadeia: {motivo}")
        sys.exit(10)
    print("sim")


if __name__ == "__main__":
    main()
