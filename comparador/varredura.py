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

Modo diário: cada fatia precisa ser lida por inteiro uma vez por dia (horário de
Brasília). Uma execução lê as fatias que ainda faltam hoje, salva o progresso a cada
página e para quando o dia fica completo ou o tempo acaba; a execução seguinte continua
dali. Medido: HQs e mangás = 33 fatias, ~2.050 páginas, ~1h40 a ~20 páginas/min, sem
bloqueios, então um servidor por dia basta.
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
from .coletor import PAUSA_APOS_BLOQUEIO, _baixar, _guardar_html

SCHEMA = Path(__file__).with_name("schema_catalogo.sql")

NO_HQ_MANGA = "7842710011"  # Livros > HQs, Mangás e Graphic Novels
MAX_PAGINAS_FATIA = 100       # bem abaixo do limite de 400 da Amazon
LIMITE_PAGINAS_AMAZON = 400
# Na ordem "mais vendidos" a Amazon só mostra 75 páginas (1.200 itens), embora a paginação
# anuncie 400 (medido em out/2026, igual na categoria Livros e em cada gênero).
LIMITE_PAGINAS_VENDIDOS = 75
GRUPO_VENDIDOS = "vendidos"
NO_LIVROS = "6740748011"
# Gêneros de Livros (subcategorias diretas), lidos da página da Amazon em out/2026.
GENEROS = {
    "7872854011": "Administração, Negócios e Economia", "7841296011": "Arte, Cinema e Fotografia",
    "7841521011": "Artesanato, Casa e Estilo de Vida", "7841720011": "Autoajuda",
    "7841731011": "Biografias e Histórias Reais", "7841795011": "Ciências",
    "7842641011": "Computação, Informática e Mídias Digitais", "7843925011": "Crônicas, Humor e Entretenimento",
    "7874340011": "Direito", "7842837011": "Educação, Referência e Didáticos",
    "12764254011": "Engenharia e Transporte", "7843058011": "Erótico", "7842741011": "Esportes e Lazer",
    "7841775011": "Fantasia, Horror e Ficção Científica", "7872552011": "Gastronomia e Culinária",
    "7843068011": "História", "7842710011": "HQs, Mangás e Graphic Novels", "7844001011": "Infantil",
    "7843064011": "LGBTQ+", "7872687011": "Literatura e Ficção", "7874461011": "Medicina",
    "7872829011": "Policial, Suspense e Mistério", "7873971011": "Política, Filosofia e Ciências Sociais",
    "7874675011": "Religião e Espiritualidade", "7882388011": "Romance", "7882415011": "Saúde e Família",
    "7882554011": "Turismo e Guias de Viagem", "7882627011": "Livros Internacionais",
    "7841279011": "Jovens e Adolescentes",
}
PRECO_MAXIMO = 99_999_999     # centavos: teto da última fatia
FAIXAS_INICIAIS = [0, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000, 8000,
                   10000, 15000, 20000, 50000]
BURACO = timedelta(days=10)   # sem observação por mais que isso: novo intervalo no histórico
LIMITE_FALHAS_SEGUIDAS = 3
# Medido em out/2026: 1,5–3 s → 18 páginas/min e 0,3–1 s → 36 páginas/min, ambos sem
# bloqueio. 1–3 s fica no meio, com folga. Depois de um bloqueio, fica 3x mais lento.
PAUSA_VARREDURA = (1.0, 3.0)
FATOR_LENTO = 3.0


@dataclass
class Fatia:
    id: int
    grupo: str
    no: str
    ordem: str
    preco_min: int
    preco_max: int
    proxima_pagina: int
    ultima_passada: str | None

    @classmethod
    def de(cls, r) -> "Fatia":
        return cls(r["id"], r["grupo"], r["no"], r["ordem"], r["preco_min"], r["preco_max"],
                   r["proxima_pagina"], r["ultima_passada"])


def criar_schema(conn: sqlite3.Connection) -> None:
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(fatias)")}
    if colunas and "grupo" not in colunas:  # banco criado antes dos grupos
        conn.execute("ALTER TABLE fatias ADD COLUMN grupo TEXT")
        conn.execute("ALTER TABLE fatias ADD COLUMN ordem TEXT NOT NULL DEFAULT 'preco'")
        conn.execute("UPDATE fatias SET grupo = no")
        conn.commit()
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def semear(conn: sqlite3.Connection, no: str) -> None:
    """Cria as fatias iniciais da varredura por preço da categoria, se ainda não existirem."""
    if conn.execute("SELECT 1 FROM fatias WHERE grupo = ?", (no,)).fetchone():
        return
    limites = FAIXAS_INICIAIS + [PRECO_MAXIMO + 1]
    agora = db.agora()
    conn.executemany(
        "INSERT INTO fatias (grupo, no, preco_min, preco_max, criada_em) VALUES (?, ?, ?, ?, ?)",
        [(no, no, a, b - 1, agora) for a, b in zip(limites, limites[1:])],
    )
    conn.commit()


def semear_vendidos(conn: sqlite3.Connection, nos) -> None:
    """Uma fatia "mais vendidos" por categoria; acrescenta as que faltarem."""
    agora = db.agora()
    conn.executemany(
        "INSERT OR IGNORE INTO fatias (grupo, no, ordem, preco_min, preco_max, criada_em) "
        "VALUES (?, ?, 'vendidos', 0, ?, ?)",
        [(GRUPO_VENDIDOS, no, PRECO_MAXIMO, agora) for no in nos],
    )
    conn.commit()


def inicio_do_dia(dia=None) -> str:
    """Meia-noite (Brasília) do dia, em UTC ISO: fatias lidas depois disso contam para o dia."""
    dia = dia or db.hoje_brasil()
    return datetime(dia.year, dia.month, dia.day, tzinfo=db.BRASILIA).astimezone(timezone.utc).isoformat(
        timespec="seconds")


def proxima_fatia(conn: sqlite3.Connection, grupo: str, desde: str) -> Fatia | None:
    """Próxima fatia que ainda não foi lida inteira desde `desde` (passada em andamento primeiro)."""
    r = conn.execute(
        "SELECT * FROM fatias WHERE grupo = ? AND ativa = 1 AND (ultima_passada IS NULL OR ultima_passada < ?) "
        "ORDER BY proxima_pagina = 1, preco_min, id LIMIT 1",
        (grupo, desde),
    ).fetchone()
    return Fatia.de(r) if r else None


def _fechar_dia_se_completo(conn: sqlite3.Connection, grupo: str, desde: str) -> bool:
    if proxima_fatia(conn, grupo, desde) is not None:
        return False
    conn.execute("INSERT OR IGNORE INTO dias (no, dia, completo_em) VALUES (?, ?, ?)",
                 (grupo, db.dia_brasil(desde).isoformat(), db.agora()))
    conn.commit()
    return True


def dividir(conn: sqlite3.Connection, f: Fatia) -> None:
    meio = (f.preco_min + f.preco_max) // 2
    conn.execute("UPDATE fatias SET ativa = 0 WHERE id = ?", (f.id,))
    for a, b in ((f.preco_min, meio), (meio + 1, f.preco_max)):
        conn.execute(
            "INSERT INTO fatias (grupo, no, preco_min, preco_max, criada_em) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (no, preco_min, preco_max) DO UPDATE SET ativa = 1, proxima_pagina = 1",
            (f.grupo, f.no, a, b, db.agora()),
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
    vendidos=None,
    minutos: float = 60,
    max_paginas: int | None = None,
    pausa: tuple[float, float] = PAUSA_VARREDURA,
    dormir=time.sleep,
    relogio=time.monotonic,
    pasta_html: Path | None = None,
) -> int:
    """Lê as fatias que faltam hoje até completar o dia ou acabar o tempo (ou `max_paginas`).

    Por padrão, a categoria `no` inteira, fatiada por preço. Com `vendidos` (lista de nós),
    os mais vendidos de cada um desses nós (até 1.200 por nó).
    Devolve o id da execução, ou None se o dia já estava completo (nada a fazer).
    """
    criar_schema(conn)
    if vendidos is not None:
        grupo = GRUPO_VENDIDOS
        semear_vendidos(conn, vendidos)
    else:
        grupo = no
        semear(conn, no)
    desde = inicio_do_dia()
    if _fechar_dia_se_completo(conn, grupo, desde):
        return None
    # Passada que começou antes de hoje recomeça da página 1: todos os preços do dia
    # precisam ser do dia.
    conn.execute("UPDATE fatias SET proxima_pagina = 1 WHERE grupo = ? AND proxima_pagina > 1 "
                 "AND passada_iniciada_em < ?", (grupo, desde))
    exec_id = conn.execute("INSERT INTO execucoes (iniciada_em) VALUES (?)", (db.agora(),)).lastrowid
    conn.commit()
    inicio = relogio()
    paginas = itens = bloqueios = erros = falhas_seguidas = 0
    fator = 1.0
    avisos: list[str] = []

    while relogio() - inicio < minutos * 60 and (max_paginas is None or paginas + bloqueios + erros < max_paginas):
        f = proxima_fatia(conn, grupo, desde)
        if f is None:
            avisos.append("dia completo")
            break
        if paginas + bloqueios + erros:
            dormir(random.uniform(*pausa) * fator + (PAUSA_APOS_BLOQUEIO if falhas_seguidas else 0))

        pag = f.proxima_pagina
        url = url_busca(f.no, f.preco_min, f.preco_max, pag, f.ordem)
        rotulo = (f"[{GENEROS.get(f.no, f.no)} p{pag}]" if f.ordem == "vendidos"
                  else f"[fatia {f.id} R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f} p{pag}]")
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
                fator = FATOR_LENTO  # daqui em diante, mais devagar
                print(f"{rotulo} bloqueado; diminuindo o ritmo")
            else:
                erros += 1
                print(f"{rotulo} {erro.detalhe if erro else erro_txt}")
                if erro is None:
                    avisos.append(erro_txt)
            if falhas_seguidas >= LIMITE_FALHAS_SEGUIDAS:
                avisos.append(f"interrompida após {falhas_seguidas} falhas seguidas")
                break
            continue  # tenta a mesma página de novo (o progresso não avançou)
        falhas_seguidas = 0
        paginas += 1

        limite = LIMITE_PAGINAS_VENDIDOS if f.ordem == "vendidos" else LIMITE_PAGINAS_AMAZON
        if pag == 1:
            n_pag = min(pagina.ultima_pagina or (1 if pagina.cards else 0), limite)
            if f.ordem == "preco" and n_pag > MAX_PAGINAS_FATIA and f.preco_max > f.preco_min:
                print(f"[fatia {f.id}] R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f}: "
                      f"{n_pag} páginas, dividindo")
                dividir(conn, f)
                continue
            if f.ordem == "preco" and n_pag > MAX_PAGINAS_FATIA:
                avisos.append(f"fatia {f.id} (preço único) tem {n_pag} páginas; parte pode ficar de fora")
            conn.execute("UPDATE fatias SET paginas = ?, total = ?, passada_iniciada_em = ? WHERE id = ?",
                         (n_pag, pagina.total, db.agora(), f.id))

        quando = db.agora()
        for item in pagina.itens:
            registrar(conn, item, f.no, quando)
        itens += len(pagina.itens)

        ultima = min(pagina.ultima_pagina or pag, limite)
        fim = pagina.cards == 0 or pag >= ultima
        if fim:
            conn.execute("UPDATE fatias SET proxima_pagina = 1, ultima_passada = ? WHERE id = ?", (quando, f.id))
        else:
            conn.execute("UPDATE fatias SET proxima_pagina = ? WHERE id = ?", (pag + 1, f.id))
        conn.execute("UPDATE execucoes SET paginas = ?, itens = ?, bloqueios = ?, erros = ? WHERE id = ?",
                     (paginas, itens, bloqueios, erros, exec_id))
        conn.commit()
        print(f"{rotulo[:-1]}/{ultima}] {len(pagina.itens)} preços" + (" (fim)" if fim else ""))

    _fechar_dia_se_completo(conn, grupo, desde)
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
    vistos_hoje: int
    fatias: int
    fatias_hoje: int        # fatias já lidas por inteiro hoje
    dia_completo: bool
    lacunas: list           # dias (date) sem varredura completa, da primeira execução até ontem


def cobertura(conn: sqlite3.Connection, grupo: str = NO_HQ_MANGA) -> Cobertura:
    """Progresso do grupo hoje (cada banco guarda um grupo: um nó ou "vendidos")."""
    criar_schema(conn)
    desde = inicio_do_dia()
    um = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    completos = {datetime.fromisoformat(r[0]).date() for r in conn.execute("SELECT dia FROM dias WHERE no = ?", (grupo,))}
    # Lacunas contam a partir do primeiro dia com execução (mesmo que nenhum dia tenha
    # completado: bloqueio desde o início também é lacuna).
    primeira = conn.execute("SELECT MIN(iniciada_em) FROM execucoes").fetchone()[0]
    inicios = [d for d in (min(completos, default=None), primeira and db.dia_brasil(primeira)) if d]
    lacunas = []
    if inicios:
        dia, ontem = min(inicios), db.hoje_brasil() - timedelta(days=1)
        while dia <= ontem:
            if dia not in completos:
                lacunas.append(dia)
            dia += timedelta(days=1)
    return Cobertura(
        itens=um("SELECT COUNT(*) FROM catalogo"),
        vistos_hoje=um("SELECT COUNT(*) FROM catalogo WHERE ultimo_visto >= ?", desde),
        fatias=um("SELECT COUNT(*) FROM fatias WHERE grupo = ? AND ativa = 1", grupo),
        fatias_hoje=um("SELECT COUNT(*) FROM fatias WHERE grupo = ? AND ativa = 1 AND ultima_passada >= ?",
                       grupo, desde),
        dia_completo=db.hoje_brasil() in completos,
        lacunas=lacunas,
    )
