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

import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .busca import SEM_TETO, ItemBusca, LayoutDesconhecido, parse_busca, url_busca
from .rede import PAUSA_APOS_BLOQUEIO, baixar_lote, guardar_html
from .ritmo import Ritmo

COLUNAS_DETALHE = ("autor", "imagem", "publicado", "idioma", "obra")
SCHEMA = Path(__file__).with_name("schema_catalogo.sql")

NO_HQ_MANGA = "7842710011"  # Livros > HQs, Mangás e Graphic Novels
MAX_PAGINAS_FATIA = 100       # bem abaixo do limite de 400 da Amazon
LIMITE_PAGINAS_AMAZON = 400
# Na ordem "mais vendidos" a Amazon só mostra 75 páginas (1.200 cards), embora a paginação
# anuncie 400 (medido em out/2026, igual na categoria Livros e em cada gênero). Mas cada faixa de
# preço (filtro p_36) tem o seu próprio ranking de 75 páginas, na mesma ordem relativa.
LIMITE_PAGINAS_VENDIDOS = 75
# Por isso cada categoria é lida em faixas de preço (centavos, inclusive), cada uma até
# LIVROS_POR_FAIXA livros. Os 2.000 mais vendidos da categoria estão todos na união das faixas
# desde que nenhuma faixa tenha mais de LIVROS_POR_FAIXA deles (com 3 faixas, ~670 cada em média).
# Lê até ~3.000 por categoria. A faixa vale para o card: entra se algum formato está nela.
FAIXAS_VENDIDOS = [(0, 3999), (4000, 7999), (8000, SEM_TETO)]
# Quantos livros disponíveis (com preço de compra) lemos por faixa na ordem "mais vendidos".
# Livros sem preço (indisponíveis, só Kindle Unlimited) não contam: a leitura segue até completar
# esta quantidade ou até o limite de páginas acima.
LIVROS_POR_FAIXA = 1000
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
PRECO_MAXIMO = SEM_TETO       # centavos: teto da última fatia
FAIXAS_INICIAIS = [0, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000, 8000,
                   10000, 15000, 20000, 50000]
BURACO = timedelta(days=10)   # sem observação por mais que isso: novo intervalo no histórico
LIMITE_FALHAS_SEGUIDAS = 3
# Ritmo: ver ritmo.py. Medido em out/2026, com pausa de 1–3 s (~21 páginas/min), 0 bloqueios em ~11 mil
# páginas.
# "Sem erro" não é só "sem HTTP 503": sob limitação a Amazon pode devolver 200 com resultado ralo, e a
# varredura daria a fatia por lida. Por isso uma página do meio da fatia com menos de CARDS_MIN_PAGINA
# resultados (as normais têm ~16) conta como falha, é relida depois de uma pausa e só é aceita se vier
# com o mesmo número de novo (aí é assim mesmo). O mesmo vale para a página 1 que vem vazia numa fatia
# que tinha PAGINAS_MIN_VAZIA páginas ou mais na passada anterior.
CARDS_MIN_PAGINA = 8
PAGINAS_MIN_VAZIA = 5
# No fim de uma fatia, avisa se leu menos de QUEDA_LIVROS da quantidade de livros da passada anterior.
QUEDA_LIVROS = 0.8
LIVROS_MIN_AVISO = 50


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
    paginas: int | None = None    # páginas da fatia: contadas na página 1 desta passada (ou, antes dela, na anterior)

    @classmethod
    def de(cls, r) -> "Fatia":
        return cls(r["id"], r["grupo"], r["no"], r["ordem"], r["preco_min"], r["preco_max"],
                   r["proxima_pagina"], r["ultima_passada"], r["paginas"])


def criar_schema(conn: sqlite3.Connection) -> None:
    colunas = {r[1] for r in conn.execute("PRAGMA table_info(fatias)")}
    if colunas and "grupo" not in colunas:  # banco criado antes dos grupos
        conn.execute("ALTER TABLE fatias ADD COLUMN grupo TEXT")
        conn.execute("ALTER TABLE fatias ADD COLUMN ordem TEXT NOT NULL DEFAULT 'preco'")
        conn.execute("UPDATE fatias SET grupo = no")
        conn.commit()
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    if "livros" not in {r[1] for r in conn.execute("PRAGMA table_info(fatias)")}:  # banco anterior a esta coluna
        conn.execute("ALTER TABLE fatias ADD COLUMN livros INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    for tabela, coluna, tipo in (("fatias", "livros_ant", "INTEGER"), ("execucoes", "curtas", "INTEGER NOT NULL DEFAULT 0"),
                                 ("execucoes", "ppm", "REAL")):    # bancos anteriores à medição do ritmo
        if coluna not in {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(catalogo)")}
    for coluna in COLUNAS_DETALHE:                      # banco anterior aos detalhes do livro
        if coluna not in existentes:
            conn.execute(f"ALTER TABLE catalogo ADD COLUMN {coluna} TEXT")
    conn.commit()


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


def faixas_de_precos(bordas_em_reais) -> list[tuple[int, int]]:
    """[0, 20, 30, 40] -> [(0, 1999), (2000, 2999), (3000, 3999), (4000, SEM_TETO)] (centavos, inclusive)."""
    b = [round(float(x) * 100) for x in bordas_em_reais]
    if not b or b[0] != 0 or any(y <= x for x, y in zip(b, b[1:])):
        raise ValueError("as bordas das faixas começam em 0 e crescem: 0,20,30,40")
    return [(x, y - 1) for x, y in zip(b, b[1:])] + [(b[-1], SEM_TETO)]


def nos_vendidos(generos: str | None = None) -> list[str]:
    """Nós lidos na varredura dos mais vendidos: o ranking geral e todos os gêneros, ou só os de `generos`
    (códigos separados por vírgula)."""
    todos = [NO_LIVROS, *GENEROS]
    if not generos:
        return todos
    pedidos = [g.strip() for g in generos.split(",") if g.strip()]
    desconhecidos = [g for g in pedidos if g not in todos]
    if desconhecidos:
        raise ValueError(f"gênero desconhecido: {', '.join(desconhecidos)}")
    return pedidos


def semear_vendidos(conn: sqlite3.Connection, nos, faixas=None) -> None:
    """Uma fatia "mais vendidos" por categoria e faixa de `faixas` (padrão FAIXAS_VENDIDOS); acrescenta
    as que faltarem e desativa as de faixas que não estão mais na lista (o histórico fica)."""
    faixas = list(faixas or FAIXAS_VENDIDOS)
    agora = db.agora()
    conn.executemany(
        "INSERT OR IGNORE INTO fatias (grupo, no, ordem, preco_min, preco_max, criada_em) "
        "VALUES (?, ?, 'vendidos', ?, ?, ?)",
        [(GRUPO_VENDIDOS, no, a, b, agora) for no in nos for a, b in faixas],
    )
    atual = "(" + " OR ".join(["(preco_min = ? AND preco_max = ?)"] * len(faixas)) + ")"
    valores = [v for f in faixas for v in f]
    conn.execute(f"UPDATE fatias SET ativa = {atual} WHERE grupo = ? AND ordem = 'vendidos'",
                 (*valores, GRUPO_VENDIDOS))
    conn.commit()


def inicio_do_dia(dia=None) -> str:
    """Meia-noite (Brasília) do dia, em UTC ISO: fatias lidas depois disso contam para o dia."""
    dia = dia or db.hoje_brasil()
    return datetime(dia.year, dia.month, dia.day, tzinfo=db.BRASILIA).astimezone(timezone.utc).isoformat(
        timespec="seconds")


def proximas_fatias(conn: sqlite3.Connection, grupo: str, desde: str, n: int = 1) -> list[Fatia]:
    """Até `n` fatias distintas que ainda não foram lidas inteiras desde `desde` (passadas em andamento primeiro)."""
    return [Fatia.de(r) for r in conn.execute(
        "SELECT * FROM fatias WHERE grupo = ? AND ativa = 1 AND (ultima_passada IS NULL OR ultima_passada < ?) "
        "ORDER BY proxima_pagina = 1, preco_min, id LIMIT ?",
        (grupo, desde, n),
    )]


def proxima_fatia(conn: sqlite3.Connection, grupo: str, desde: str) -> Fatia | None:
    """Próxima fatia que ainda não foi lida inteira desde `desde` (passada em andamento primeiro)."""
    return next(iter(proximas_fatias(conn, grupo, desde, 1)), None)


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


def _faixa(f: Fatia) -> str:
    if f.preco_max >= PRECO_MAXIMO:
        return f"R$ {f.preco_min / 100:.0f}+"
    return f"R$ {f.preco_min / 100:.0f}–{f.preco_max / 100:.2f}"


def _instante(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def registrar(conn: sqlite3.Connection, item: ItemBusca, no: str, quando: str) -> None:
    conn.execute(
        "INSERT INTO catalogo (asin, titulo, formato, autor, imagem, publicado, idioma, obra, no, "
        "primeiro_visto, ultimo_visto) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (asin) DO UPDATE SET "
        "titulo = COALESCE(excluded.titulo, titulo), formato = COALESCE(excluded.formato, formato), "
        "autor = COALESCE(excluded.autor, autor), imagem = COALESCE(excluded.imagem, imagem), "
        "publicado = COALESCE(excluded.publicado, publicado), idioma = COALESCE(excluded.idioma, idioma), "
        "obra = COALESCE(excluded.obra, obra), ultimo_visto = excluded.ultimo_visto",
        (item.asin, item.titulo, item.formato, item.autor, item.imagem, item.publicado, item.idioma,
         item.obra, no, quando, quando),
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


@dataclass
class Placar:
    """Contagens de uma execução. `curtas`: páginas que vieram com resultado ralo (ver CARDS_MIN_PAGINA)."""
    paginas: int = 0
    itens: int = 0
    bloqueios: int = 0
    erros: int = 0
    curtas: int = 0
    falhas_seguidas: int = 0     # lotes seguidos com alguma falha
    avisos: list = field(default_factory=list)

    @property
    def tentativas(self) -> int:
        return self.paginas + self.bloqueios + self.erros + self.curtas


def varrer(
    conn: sqlite3.Connection,
    sessao,
    *,
    no: str = NO_HQ_MANGA,
    vendidos=None,
    minutos: float = 60,
    max_paginas: int | None = None,
    faixas=None,
    ritmo: Ritmo | None = None,
    parar_na_falha: bool = False,
    dormir=time.sleep,
    relogio=time.monotonic,
    pasta_html: Path | None = None,
) -> int:
    """Lê as fatias que faltam hoje até completar o dia ou acabar o tempo (ou `max_paginas`).

    Por padrão, a categoria `no` inteira, fatiada por preço. Com `vendidos` (lista de nós),
    os mais vendidos de cada um desses nós (até LIVROS_POR_FAIXA por faixa de preço), sem contar os
    que não têm preço de compra.
    `faixas`: faixas de preço dos mais vendidos (padrão FAIXAS_VENDIDOS), ver `faixas_de_precos`.
    `ritmo` define páginas por minuto e quantas fatias são lidas ao mesmo tempo (uma página por fatia
    de cada vez); ele recua sozinho a cada falha. Com `parar_na_falha`, a execução termina na primeira
    falha (para medir o ritmo máximo sem insistir).
    Devolve o id da execução, ou None se o dia já estava completo (nada a fazer).
    """
    criar_schema(conn)
    if vendidos is not None:
        grupo = GRUPO_VENDIDOS
        semear_vendidos(conn, vendidos, faixas)
    else:
        grupo = no
        semear(conn, no)
    # A varredura só lê livros vendidos pela Amazon (filtro da busca). O marco serve ao site, que
    # esconde o que não foi visto desde então (vendedores de fora que entraram antes do filtro).
    conn.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES ('so_amazon_desde', ?)", (db.agora(),))
    conn.commit()
    desde = inicio_do_dia()
    if _fechar_dia_se_completo(conn, grupo, desde):
        return None
    # Passada que começou antes de hoje recomeça da página 1: todos os preços do dia
    # precisam ser do dia.
    conn.execute("UPDATE fatias SET proxima_pagina = 1 WHERE grupo = ? AND proxima_pagina > 1 "
                 "AND passada_iniciada_em < ?", (grupo, desde))
    exec_id = conn.execute("INSERT INTO execucoes (iniciada_em) VALUES (?)", (db.agora(),)).lastrowid
    conn.commit()
    ritmo = ritmo or Ritmo()
    inicio = relogio()
    pl = Placar()
    curtas_vistas: dict[tuple[int, int], int] = {}   # (fatia, página) -> resultados da página curta já vista

    def ler(f: Fatia, url: str, html: str | None, erro) -> str:
        """Processa uma resposta. Devolve "ok", "leve" ou "grave" (bloqueio). Numa falha, a mesma página
        será tentada de novo."""
        pag = f.proxima_pagina
        rotulo = (f"[{GENEROS.get(f.no, f.no)} {_faixa(f)} p{pag}]" if f.ordem == "vendidos"
                  else f"[fatia {f.id} R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f} p{pag}]")
        pagina = erro_txt = None
        if erro is None:
            try:
                pagina = parse_busca(html)
            except LayoutDesconhecido as e:
                arq = guardar_html(pasta_html, f"busca-{f.id}-{pag}", html)
                erro_txt = f"layout desconhecido em {url}: {e}" + (f" (HTML em {arq})" if arq else "")
        if erro is not None or pagina is None:
            if erro is not None and erro.status == "bloqueado":
                pl.bloqueios += 1
                print(f"{rotulo} bloqueado; diminuindo o ritmo")
                return "grave"
            pl.erros += 1
            print(f"{rotulo} {erro.detalhe if erro else erro_txt}")
            if erro is None:
                pl.avisos.append(erro_txt)
            return "leve"

        esperada = f.paginas or 0     # páginas da fatia (a passada anterior, se esta é a página 1)
        curta = ((pag == 1 and pagina.cards == 0 and esperada >= PAGINAS_MIN_VAZIA)
                 or (pag > 1 and pagina.cards < CARDS_MIN_PAGINA and pag < esperada))
        if curta and curtas_vistas.get((f.id, pag)) != pagina.cards:
            curtas_vistas[(f.id, pag)] = pagina.cards
            pl.curtas += 1
            arq = guardar_html(pasta_html, f"curta-{f.id}-{pag}", html)
            titulo = re.search(r"<title[^>]*>([^<]*)", html)
            print(f"{rotulo} veio com {pagina.cards} resultados (esperava ~16); relendo depois de uma pausa "
                  f"[título: {titulo.group(1).strip()[:80] if titulo else '?'}; {len(html)} bytes"
                  + (f"; HTML em {arq}" if arq else "") + "]")
            return "leve"
        if curta:
            pl.avisos.append(f"{rotulo} tem só {pagina.cards} resultados, confirmado em duas leituras")

        limite = LIMITE_PAGINAS_VENDIDOS if f.ordem == "vendidos" else LIMITE_PAGINAS_AMAZON
        if pag == 1:
            n_pag = min(pagina.ultima_pagina or (1 if pagina.cards else 0), limite)
            if f.ordem == "preco" and n_pag > MAX_PAGINAS_FATIA and f.preco_max > f.preco_min:
                print(f"[fatia {f.id}] R$ {f.preco_min / 100:.2f}–{f.preco_max / 100:.2f}: "
                      f"{n_pag} páginas, dividindo")
                dividir(conn, f)
                pl.paginas += 1
                return "ok"
            if f.ordem == "preco" and n_pag > MAX_PAGINAS_FATIA:
                pl.avisos.append(f"fatia {f.id} (preço único) tem {n_pag} páginas; parte pode ficar de fora")
            conn.execute("UPDATE fatias SET paginas = ?, total = ?, passada_iniciada_em = ?, livros = 0 WHERE id = ?",
                         (n_pag, pagina.total, db.agora(), f.id))
        pl.paginas += 1

        quando = db.agora()
        for item in pagina.itens:
            registrar(conn, item, f.no, quando)
        pl.itens += len(pagina.itens)

        ultima = min(pagina.ultima_pagina or pag, limite)
        conn.execute("UPDATE fatias SET livros = livros + ? WHERE id = ?", (pagina.livros, f.id))
        lidos, anteriores = conn.execute("SELECT livros, livros_ant FROM fatias WHERE id = ?", (f.id,)).fetchone()
        completou = f.ordem == "vendidos" and lidos >= LIVROS_POR_FAIXA
        fim = pagina.cards == 0 or pag >= ultima or completou
        if fim:
            if (anteriores or 0) >= LIVROS_MIN_AVISO and not completou and lidos < QUEDA_LIVROS * anteriores:
                pl.avisos.append(f"{rotulo[:-1]}] leu {lidos} livros; na passada anterior, {anteriores}")
            conn.execute("UPDATE fatias SET proxima_pagina = 1, ultima_passada = ?, livros_ant = ? WHERE id = ?",
                         (quando, lidos, f.id))
        else:
            conn.execute("UPDATE fatias SET proxima_pagina = ? WHERE id = ?", (pag + 1, f.id))
        conn.execute("UPDATE execucoes SET paginas = ?, itens = ?, bloqueios = ?, erros = ?, curtas = ? WHERE id = ?",
                     (pl.paginas, pl.itens, pl.bloqueios, pl.erros, pl.curtas, exec_id))
        conn.commit()
        print(f"{rotulo[:-1]}/{ultima}] {len(pagina.itens)} preços"
              + (f", {lidos} livros" if f.ordem == "vendidos" else "")
              + (" (fim)" if fim else ""))
        return "ok"

    marco = 0
    while relogio() - inicio < minutos * 60:
        pistas = ritmo.pistas
        if max_paginas is not None:
            if pl.tentativas >= max_paginas:
                break
            pistas = min(pistas, max_paginas - pl.tentativas)
        lote = proximas_fatias(conn, grupo, desde, pistas)
        if not lote:
            pl.avisos.append("dia completo")
            break
        urls = [url_busca(f.no, f.preco_min, f.preco_max, f.proxima_pagina, f.ordem) for f in lote]
        t0 = relogio()
        respostas = baixar_lote(sessao, urls, ritmo.atrasos(len(lote)), dormir)
        resultados = [ler(f, url, html, erro) for f, url, (_, html, erro) in zip(lote, urls, respostas)]
        if all(r == "ok" for r in resultados):
            pl.falhas_seguidas = 0
            for _ in resultados:
                ritmo.pagina_boa()
        else:
            pl.falhas_seguidas += 1
            ppm_da_falha = ritmo.ppm
            ritmo.falha(grave="grave" in resultados)
            if parar_na_falha:
                pl.avisos.append(f"parada na primeira falha, programada a {ppm_da_falha:.0f} páginas/min")
                break
            if pl.falhas_seguidas >= LIMITE_FALHAS_SEGUIDAS:
                pl.avisos.append(f"interrompida após {pl.falhas_seguidas} falhas seguidas")
                break
        if pl.paginas // 100 > marco:
            marco = pl.paginas // 100
            minutos_corridos = max((relogio() - inicio) / 60, 1e-9)
            print(f"ritmo: programado {ritmo.ppm:.0f} páginas/min ({ritmo.pistas} ao mesmo tempo); "
                  f"medido {pl.paginas / minutos_corridos:.0f}; {pl.paginas} páginas, "
                  f"{pl.bloqueios} bloqueios, {pl.erros} erros, {pl.curtas} curtas")
        espera = ritmo.espera(len(lote), relogio() - t0) + (PAUSA_APOS_BLOQUEIO if pl.falhas_seguidas else 0)
        if espera > 0:
            dormir(espera)

    _fechar_dia_se_completo(conn, grupo, desde)
    corridos = max((relogio() - inicio) / 60, 1e-9)
    conn.execute(
        "UPDATE execucoes SET finalizada_em = ?, paginas = ?, itens = ?, bloqueios = ?, erros = ?, curtas = ?, "
        "ppm = ?, observacao = ? WHERE id = ?",
        (db.agora(), pl.paginas, pl.itens, pl.bloqueios, pl.erros, pl.curtas, round(pl.paginas / corridos, 1),
         "; ".join(dict.fromkeys(pl.avisos)) or None, exec_id),
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
