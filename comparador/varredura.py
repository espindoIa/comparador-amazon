"""Varredura de uma categoria inteira (ex.: HQs, Mangás e Graphic Novels) pelas páginas de busca.

Por que assim (medido em out/2026):
- Uma página de busca traz ~16 livros com preço e, quando há desconto, o preço de capa.
  É ~16x mais barato que consultar livro por livro.
- A Amazon mostra no máximo 400 páginas por busca, e as mais fundas vêm incompletas.
  A categoria tem mais de 30 mil itens, então ela é dividida em FATIAS por faixa de
  preço (filtro p_36, em centavos). Uma fatia com mais de MAX_PAGINAS_FATIA páginas é
  dividida ao meio, automaticamente, até caber. Um preço exato comum (R$ 29,90) tem
  ~45 páginas, então sempre cabe.
- O filtro de preço vale para qualquer formato do card, então as fatias se sobrepõem:
  o mesmo ASIN pode aparecer em mais de uma. Isso só gera observações repetidas, que
  o histórico por intervalos absorve.

Cada execução tem um orçamento de tempo e retoma de onde a anterior parou (a página
seguinte de cada fatia fica salva no banco). As fatias são visitadas da mais
desatualizada para a mais recente, então execuções curtas e diárias cobrem a
categoria inteira em rodízio.
"""

from __future__ import annotations

import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .busca import ItemBusca, LayoutDesconhecido, parse_busca, url_busca
from .coletor import PAUSA_APOS_BLOQUEIO, PAUSA_PADRAO, _baixar, _guardar_html

SCHEMA = Path(__file__).with_name("schema_catalogo.sql")

NO_HQ_MANGA = "7842710011"  # Livros > HQs, Mangás e Graphic Novels
MAX_PAGINAS_FATIA = 100       # bem abaixo do limite de 400 da Amazon
LIMITE_PAGINAS_AMAZON = 400
PRECO_MAXIMO = 99_999_999     # centavos: teto da última fatia
FAIXAS_INICIAIS = [0, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000, 8000,
                   10000, 15000, 20000, 50000]
BURACO = timedelta(days=10)   # sem observação por mais que isso: novo intervalo no histórico
LIMITE_FALHAS_SEGUIDAS = 3


@dataclass
class Fatia:
    id: int
    no: str
    preco_min: int
    preco_max: int
    proxima_pagina: int
    ultima_passada: str | None

    @classmethod
    def de(cls, r) -> "Fatia":
        return cls(r["id"], r["no"], r["preco_min"], r["preco_max"], r["proxima_pagina"], r["ultima_passada"])


def criar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def semear(conn: sqlite3.Connection, no: str) -> None:
    """Cria as fatias iniciais da categoria, se ela ainda não tiver nenhuma."""
    if conn.execute("SELECT 1 FROM fatias WHERE no = ?", (no,)).fetchone():
        return
    limites = FAIXAS_INICIAIS + [PRECO_MAXIMO + 1]
    agora = db.agora()
    conn.executemany(
        "INSERT INTO fatias (no, preco_min, preco_max, criada_em) VALUES (?, ?, ?, ?)",
        [(no, a, b - 1, agora) for a, b in zip(limites, limites[1:])],
    )
    conn.commit()


def proxima_fatia(conn: sqlite3.Connection, no: str) -> Fatia | None:
    """Passada em andamento primeiro; depois a fatia mais desatualizada (nunca visitada antes)."""
    r = conn.execute(
        "SELECT * FROM fatias WHERE no = ? AND ativa = 1 "
        "ORDER BY proxima_pagina = 1, ultima_passada IS NOT NULL, ultima_passada, preco_min LIMIT 1",
        (no,),
    ).fetchone()
    return Fatia.de(r) if r else None


def dividir(conn: sqlite3.Connection, f: Fatia) -> None:
    meio = (f.preco_min + f.preco_max) // 2
    conn.execute("UPDATE fatias SET ativa = 0 WHERE id = ?", (f.id,))
    for a, b in ((f.preco_min, meio), (meio + 1, f.preco_max)):
        conn.execute(
            "INSERT INTO fatias (no, preco_min, preco_max, criada_em) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (no, preco_min, preco_max) DO UPDATE SET ativa = 1, proxima_pagina = 1",
            (f.no, a, b, db.agora()),
        )
    conn.commit()


def _instante(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def registrar(conn: sqlite3.Connection, item: ItemBusca, no: str, quando: str) -> None:
    conn.execute(
        "INSERT INTO catalogo (asin, titulo, formato, no, primeiro_visto, ultimo_visto) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (asin) DO UPDATE SET "
        "titulo = COALESCE(excluded.titulo, titulo), formato = COALESCE(excluded.formato, formato), "
        "ultimo_visto = excluded.ultimo_visto",
        (item.asin, item.titulo, item.formato, no, quando, quando),
    )
    ultimo = conn.execute(
        "SELECT id, preco_centavos, preco_capa_centavos, ate FROM historico "
        "WHERE asin = ? ORDER BY id DESC LIMIT 1", (item.asin,)
    ).fetchone()
    mesmo_preco = (
        ultimo is not None
        and ultimo["preco_centavos"] == item.preco_centavos
        and (item.preco_capa_centavos is None or ultimo["preco_capa_centavos"] in (None, item.preco_capa_centavos))
        and _instante(quando) - _instante(ultimo["ate"]) <= BURACO
    )
    if mesmo_preco:
        conn.execute(
            "UPDATE historico SET ate = ?, vezes = vezes + 1, "
            "preco_capa_centavos = COALESCE(preco_capa_centavos, ?) WHERE id = ?",
            (max(quando, ultimo["ate"]), item.preco_capa_centavos, ultimo["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO historico (asin, preco_centavos, preco_capa_centavos, desde, ate) "
            "VALUES (?, ?, ?, ?, ?)",
            (item.asin, item.preco_centavos, item.preco_capa_centavos, quando, quando),
        )


def varrer(
    conn: sqlite3.Connection,
    sessao,
    *,
    no: str = NO_HQ_MANGA,
    minutos: float = 60,
    max_paginas: int | None = None,
    pausa: tuple[float, float] = PAUSA_PADRAO,
    dormir=time.sleep,
    relogio=time.monotonic,
    pasta_html: Path | None = None,
) -> int:
    """Visita páginas de busca até acabar o tempo (ou `max_paginas`). Devolve o id da execução."""
    criar_schema(conn)
    semear(conn, no)
    inicio_iso = db.agora()
    exec_id = conn.execute("INSERT INTO execucoes (iniciada_em) VALUES (?)", (inicio_iso,)).lastrowid
    conn.commit()
    inicio = relogio()
    paginas = itens = bloqueios = erros = falhas_seguidas = 0
    avisos: list[str] = []

    while relogio() - inicio < minutos * 60 and (max_paginas is None or paginas + bloqueios + erros < max_paginas):
        f = proxima_fatia(conn, no)
        if f is None or (f.proxima_pagina == 1 and f.ultima_passada and f.ultima_passada >= inicio_iso):
            avisos.append("todas as fatias foram visitadas nesta execução")
            break
        if paginas + bloqueios + erros:
            dormir(random.uniform(*pausa) + (PAUSA_APOS_BLOQUEIO if falhas_seguidas else 0))

        pag = f.proxima_pagina
        url = url_busca(f.no, f.preco_min, f.preco_max, pag)
        _, html, erro = _baixar(sessao, url)
        pagina = erro_txt = None
        if erro is None:
            try:
                pagina = parse_busca(html)
            except LayoutDesconhecido as e:
                arq = _guardar_html(pasta_html, f"busca-{f.id}-{pag}", html)
                erro_txt = f"layout desconhecido em {url}: {e}" + (f" (HTML em {arq})" if arq else "")
                pagina = None
        if erro is not None or pagina is None:
            falhas_seguidas += 1
            if erro is not None and erro.status == "bloqueado":
                bloqueios += 1
                print(f"[fatia {f.id} p{pag}] bloqueado")
            else:
                erros += 1
                print(f"[fatia {f.id} p{pag}] {erro.detalhe if erro else erro_txt}")
                if erro is None:
                    avisos.append(erro_txt)
            if falhas_seguidas >= LIMITE_FALHAS_SEGUIDAS:
                avisos.append(f"interrompida após {falhas_seguidas} falhas seguidas")
                break
            continue  # tenta a mesma página de novo (o progresso não avançou)
        falhas_seguidas = 0
        paginas += 1

        if pag == 1:
            n_pag = pagina.ultima_pagina or (1 if pagina.cards else 0)
            if n_pag > MAX_PAGINAS_FATIA and f.preco_max > f.preco_min:
                print(f"[fatia {f.id}] R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f}: "
                      f"{n_pag} páginas, dividindo")
                dividir(conn, f)
                continue
            if n_pag > MAX_PAGINAS_FATIA:
                avisos.append(f"fatia {f.id} (preço único) tem {n_pag} páginas; parte pode ficar de fora")
            conn.execute("UPDATE fatias SET paginas = ?, total = ?, passada_iniciada_em = ? WHERE id = ?",
                         (n_pag, pagina.total, db.agora(), f.id))

        quando = db.agora()
        for item in pagina.itens:
            registrar(conn, item, f.no, quando)
        itens += len(pagina.itens)

        ultima = pagina.ultima_pagina or pag
        fim = pagina.cards == 0 or pag >= min(ultima, LIMITE_PAGINAS_AMAZON)
        if fim:
            conn.execute("UPDATE fatias SET proxima_pagina = 1, ultima_passada = ? WHERE id = ?", (quando, f.id))
        else:
            conn.execute("UPDATE fatias SET proxima_pagina = ? WHERE id = ?", (pag + 1, f.id))
        conn.execute("UPDATE execucoes SET paginas = ?, itens = ?, bloqueios = ?, erros = ? WHERE id = ?",
                     (paginas, itens, bloqueios, erros, exec_id))
        conn.commit()
        print(f"[fatia {f.id} R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f} p{pag}/{ultima}] "
              f"{len(pagina.itens)} preços" + (" (fim da fatia)" if fim else ""))

    conn.execute(
        "UPDATE execucoes SET finalizada_em = ?, paginas = ?, itens = ?, bloqueios = ?, erros = ?, "
        "observacao = ? WHERE id = ?",
        (db.agora(), paginas, itens, bloqueios, erros, "; ".join(dict.fromkeys(avisos)) or None, exec_id),
    )
    conn.commit()
    return exec_id


@dataclass
class Cobertura:
    itens: int
    vistos_recentes: int
    fatias: int
    fatias_atrasadas: int
    pendentes_iniciais: int  # fatias novas que ainda não completaram a primeira passada


def cobertura(conn: sqlite3.Connection, no: str = NO_HQ_MANGA, dias: int = 8) -> Cobertura:
    criar_schema(conn)
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
    um = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    return Cobertura(
        itens=um("SELECT COUNT(*) FROM catalogo WHERE no = ?", no),
        vistos_recentes=um("SELECT COUNT(*) FROM catalogo WHERE no = ? AND ultimo_visto >= ?", no, limite),
        fatias=um("SELECT COUNT(*) FROM fatias WHERE no = ? AND ativa = 1", no),
        # Atrasada: passou do prazo sem passada completa (as novas têm `dias` de carência).
        fatias_atrasadas=um(
            "SELECT COUNT(*) FROM fatias WHERE no = ? AND ativa = 1 AND "
            "COALESCE(ultima_passada, criada_em) < ?", no, limite),
        pendentes_iniciais=um(
            "SELECT COUNT(*) FROM fatias WHERE no = ? AND ativa = 1 AND ultima_passada IS NULL", no),
    )
