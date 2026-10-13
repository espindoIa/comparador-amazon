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
from . import ritmo as modulo_ritmo
from .busca import SEM_TETO, ItemBusca, LayoutDesconhecido, parse_busca, url_busca
from .rede import PAUSA_APOS_BLOQUEIO, baixar_lote, guardar_html
from .ritmo import Ritmo

COLUNAS_DETALHE = {"autor": "TEXT", "imagem": "TEXT", "publicado": "TEXT", "idioma": "TEXT", "obra": "TEXT",
                   "nota": "INTEGER", "avaliacoes": "INTEGER"}
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
# desde que nenhuma faixa tenha mais de LIVROS_POR_FAIXA deles. Com 9 faixas (R$ 0–19,99; 20–29,99;
# 30–39,99; 40–49,99; 50–59,99; 60–79,99; 80–119,99; 120–199,99; 200+), a leitura vai até ~9.000
# livros por categoria, bem além dos 2.000 mais vendidos, e as faixas mais largas ficam onde há
# menos livros. Medido em 7 gêneros: 63,7 mil livros lidos contra ~24 mil com 3 faixas. A faixa vale
# para o card: entra se algum formato está nela (por isso as faixas se sobrepõem um pouco).
FAIXAS_VENDIDOS = [(0, 1999), (2000, 2999), (3000, 3999), (4000, 4999), (5000, 5999), (6000, 7999),
                   (8000, 11999), (12000, 19999), (20000, SEM_TETO)]
# Quantos livros disponíveis (com preço de compra) lemos por faixa na ordem "mais vendidos".
# Livros sem preço (indisponíveis, só Kindle Unlimited) não contam: a leitura segue até completar
# esta quantidade ou até o limite de páginas acima.
LIVROS_POR_FAIXA = 1000
GRUPO_VENDIDOS = "vendidos"
# Ranking geral de Livros. Não é mais lido por padrão: custava 675 páginas por passada (4,9%) para 565 livros (0,29% do
# catálogo) que não estão em nenhum gênero. Continua aceito em --generos.
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
# Os 29 gêneros divididos em três sequências de coleta, uma por servidor do GitHub (job da matrix de varredura.yml).
# O nome é o do alvo: cada sequência tem o seu banco (catalogo-<nome>-<data>.db.gz) e o site junta os três pelo ASIN.
# Divisão pelas páginas de uma passada completa (banco de 13/10/2026, passada completa: 13.795 páginas, 675 delas no
# ranking geral): 4.387, 4.395 e 4.338 para as três sequências, cada uma com um terço da passada.
# Os nomes terminam em letra: um sufixo numérico casaria com o padrão de nomes dos outros alvos nos scripts da release.
PARTICOES_VENDIDOS = {
    "vendidos": ("7872854011", "7841296011", "7841731011", "7843925011", "7842837011",
                 "12764254011", "7842741011", "7843068011", "7843064011", "7882627011"),
    "vendidos-b": ("7841795011", "7842641011", "7872552011", "7842710011", "7872687011",
                   "7874461011", "7882388011", "7882415011", "7882554011", "7841279011"),
    "vendidos-c": ("7841521011", "7841720011", "7874340011", "7843058011", "7841775011",
                   "7844001011", "7872829011", "7873971011", "7874675011"),
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
# Capa, autor e obra vêm em quase todo card (medido em out/2026: ~100%). Se numa execução com pelo menos
# ITENS_MIN_PREENCHIMENTO itens menos de PREENCHIMENTO_MIN deles vierem com um desses detalhes, é provável
# que a Amazon tenha mudado o layout; a execução avisa. (O catálogo guarda o último valor não vazio, então
# só a leitura do dia mostra a falha; a data e o idioma não vêm em todo card e ficam de fora.)
CAMPOS_ESPERADOS = ("imagem", "autor", "obra")
AVISO_LAYOUT = "o layout da página de busca pode ter mudado"
PREENCHIMENTO_MIN = 0.8
ITENS_MIN_PREENCHIMENTO = 200
# Aviso de que a janela do ciclo acabou com fatias sem ler: a sequência não dá conta de uma passada no tempo do ciclo
# (ritmo baixo, começo atrasado). O ciclo sobe um degrau (ritmo.aprender_ciclo), em vez de repetir a tentativa.
JANELA_ESTOUROU = "a janela do ciclo terminou com fatias sem ler"
FOLGA_JANELA_MIN = 20     # com menos que isto sobrando na janela, uma passada incompleta não terminará nela


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
    for coluna, tipo in COLUNAS_DETALHE.items():        # banco anterior aos detalhes do livro
        if coluna not in existentes:
            conn.execute(f"ALTER TABLE catalogo ADD COLUMN {coluna} {tipo}")
    if not conn.execute("SELECT 1 FROM generos LIMIT 1").fetchone():
        # Banco anterior à tabela de gêneros: começa pelo gênero em que cada livro foi visto primeiro.
        conn.execute("INSERT OR IGNORE INTO generos (asin, no) SELECT asin, no FROM catalogo "
                     "WHERE no IS NOT NULL AND no != ?", (NO_LIVROS,))
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


def nos_vendidos(generos: str | None = None, particao: str | None = None) -> list[str]:
    """Nós lidos na varredura dos mais vendidos: os 29 gêneros (sem o ranking geral de Livros), só os de uma
    `particao` (ver PARTICOES_VENDIDOS) ou só os de `generos` (códigos separados por vírgula; aqui o ranking
    geral ainda pode ser pedido)."""
    if generos and particao:
        raise ValueError("use só uma das opções: gêneros ou partição")
    if particao:
        if particao not in PARTICOES_VENDIDOS:
            raise ValueError(f"partição desconhecida: {particao}")
        return list(PARTICOES_VENDIDOS[particao])
    if not generos:
        return list(GENEROS)
    pedidos = [g.strip() for g in generos.split(",") if g.strip()]
    desconhecidos = [g for g in pedidos if g != NO_LIVROS and g not in GENEROS]
    if desconhecidos:
        raise ValueError(f"gênero desconhecido: {', '.join(desconhecidos)}")
    return pedidos


def semear_vendidos(conn: sqlite3.Connection, nos, faixas=None) -> None:
    """Uma fatia "mais vendidos" por categoria de `nos` e faixa de `faixas` (padrão FAIXAS_VENDIDOS);
    acrescenta as que faltarem e deixa ativas só as desses nós e dessas faixas (o histórico e as fatias
    desativadas ficam no banco: se um nó voltar à lista, a fatia dele volta a valer)."""
    nos = list(nos)
    faixas = list(faixas or FAIXAS_VENDIDOS)
    agora = db.agora()
    conn.executemany(
        "INSERT OR IGNORE INTO fatias (grupo, no, ordem, preco_min, preco_max, criada_em) "
        "VALUES (?, ?, 'vendidos', ?, ?, ?)",
        [(GRUPO_VENDIDOS, no, a, b, agora) for no in nos for a, b in faixas],
    )
    atual = "(" + " OR ".join(["(preco_min = ? AND preco_max = ?)"] * len(faixas)) + ")"
    valores = [v for f in faixas for v in f]
    conn.execute(f"UPDATE fatias SET ativa = {atual} AND no IN ({', '.join('?' * len(nos))}) "
                 "WHERE grupo = ? AND ordem = 'vendidos'",
                 (*valores, *nos, GRUPO_VENDIDOS))
    conn.commit()


def inicio_do_dia(dia=None) -> str:
    """Meia-noite (Brasília) do dia, em UTC ISO: fatias lidas depois disso contam para o dia."""
    dia = dia or db.hoje_brasil()
    return datetime(dia.year, dia.month, dia.day, tzinfo=db.BRASILIA).astimezone(timezone.utc).isoformat(
        timespec="seconds")


def inicio_do_ciclo(horas: int, agora: datetime | None = None) -> str:
    """Início (UTC ISO) da janela de `horas` horas que contém `agora`. As janelas partem da meia-noite de Brasília
    (`horas` divide 24), então a primeira de cada dia começa junto com o dia."""
    agora = agora or datetime.fromisoformat(db.agora())
    local = agora.astimezone(db.BRASILIA)
    meia_noite = local.replace(hour=0, minute=0, second=0, microsecond=0)
    k = int((local - meia_noite).total_seconds() // (horas * 3600))
    return (meia_noite + timedelta(hours=k * horas)).astimezone(timezone.utc).isoformat(timespec="seconds")


# Uma fatia só conta como lida no dia se a passada COMEÇOU e terminou nele: uma passada que atravessa a
# meia-noite tem as primeiras páginas (as dos livros mais vendidos) no dia anterior.
_FEITA_NO_DIA = "ultima_passada >= :d AND (passada_iniciada_em IS NULL OR passada_iniciada_em >= :d)"


def janela_estourou(conn: sqlite3.Connection, grupo: str, desde: str, horas: int) -> bool:
    """A janela que começou em `desde` tem fatias sem ler e a primeira passada dela começou na primeira metade (um início
    mais tarde é culpa da fila ou de uma pausa, não do ritmo): a sequência não dá conta de uma passada no tempo do ciclo."""
    if proxima_fatia(conn, grupo, desde) is None:
        return False
    primeira = conn.execute("SELECT MIN(passada_iniciada_em) FROM fatias WHERE grupo = ? AND ativa = 1 "
                            "AND passada_iniciada_em >= ?", (grupo, desde)).fetchone()[0]
    return primeira is not None and datetime.fromisoformat(primeira) - datetime.fromisoformat(desde) <= timedelta(hours=horas / 2)


def proximas_fatias(conn: sqlite3.Connection, grupo: str, desde: str, n: int = 1) -> list[Fatia]:
    """Até `n` fatias distintas que ainda não foram lidas inteiras desde `desde`: as passadas em andamento primeiro,
    depois as que estão há mais tempo sem passada completa (as nunca lidas antes de todas). Sem essa ordem, uma sequência
    que não termina a janela recomeçaria sempre pelas faixas baratas e nunca chegaria às caras."""
    return [Fatia.de(r) for r in conn.execute(
        f"SELECT * FROM fatias WHERE grupo = :g AND ativa = 1 AND (ultima_passada IS NULL OR NOT ({_FEITA_NO_DIA})) "
        "ORDER BY proxima_pagina = 1, ultima_passada IS NOT NULL, ultima_passada, preco_min, id LIMIT :n",
        {"g": grupo, "d": desde, "n": n},
    )]


def proxima_fatia(conn: sqlite3.Connection, grupo: str, desde: str) -> Fatia | None:
    """Próxima fatia que ainda não foi lida inteira desde `desde` (passada em andamento primeiro)."""
    return next(iter(proximas_fatias(conn, grupo, desde, 1)), None)


def _recomecar_passadas_antigas(conn: sqlite3.Connection, grupo: str, desde: str) -> None:
    """Passada que começou antes do dia recomeça da página 1: todos os preços do dia precisam ser do dia."""
    conn.execute("UPDATE fatias SET proxima_pagina = 1 WHERE grupo = ? AND proxima_pagina > 1 "
                 "AND passada_iniciada_em < ?", (grupo, desde))
    conn.commit()


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
        "INSERT INTO catalogo (asin, titulo, formato, autor, imagem, publicado, idioma, obra, nota, avaliacoes, no, "
        "primeiro_visto, ultimo_visto) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (asin) DO UPDATE SET "
        "titulo = COALESCE(excluded.titulo, titulo), formato = COALESCE(excluded.formato, formato), "
        "autor = COALESCE(excluded.autor, autor), imagem = COALESCE(excluded.imagem, imagem), "
        "publicado = COALESCE(excluded.publicado, publicado), idioma = COALESCE(excluded.idioma, idioma), "
        "obra = COALESCE(excluded.obra, obra), nota = COALESCE(excluded.nota, nota), "
        "avaliacoes = COALESCE(excluded.avaliacoes, avaliacoes), ultimo_visto = excluded.ultimo_visto",
        (item.asin, item.titulo, item.formato, item.autor, item.imagem, item.publicado, item.idioma,
         item.obra, item.nota, item.avaliacoes, no, quando, quando),
    )
    if no != NO_LIVROS:   # o ranking geral não é gênero; um livro pode estar em vários gêneros
        conn.execute("INSERT OR IGNORE INTO generos (asin, no) VALUES (?, ?)", (item.asin, no))
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
    com: dict = field(default_factory=dict)   # itens lidos com cada detalhe esperado (ver CAMPOS_ESPERADOS)

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
    ciclo_horas: int | None = None,
) -> int:
    """Lê as fatias que faltam hoje até completar o dia ou acabar o tempo (ou `max_paginas`).

    `ciclo_horas`: em vez do dia, a janela é de tantas horas (ver `inicio_do_ciclo`): uma fatia está "lida" se a passada
    dela começou e terminou na janela atual. O dia (Brasília) fecha quando cada fatia teve uma passada completa dentro dele.

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
    janela = (lambda: inicio_do_ciclo(ciclo_horas)) if ciclo_horas else inicio_do_dia
    dia = inicio_do_dia()
    _fechar_dia_se_completo(conn, grupo, dia)              # o dia pode já estar completo pelas passadas anteriores
    desde = janela()
    if proxima_fatia(conn, grupo, desde) is None:
        return None
    _recomecar_passadas_antigas(conn, grupo, desde)
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
            for c in CAMPOS_ESPERADOS:
                pl.com[c] = pl.com.get(c, 0) + bool(getattr(item, c))
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
        hoje = inicio_do_dia()
        if hoje != dia:              # a execução atravessou a meia-noite (Brasília): começa o dia novo
            _fechar_dia_se_completo(conn, grupo, dia)     # o que ficou completo antes da virada vale para o dia que acabou
            dia = hoje
        nova = janela()
        if nova != desde:            # começou outra janela: as passadas em andamento valeriam metade em cada uma
            if ciclo_horas and janela_estourou(conn, grupo, desde, ciclo_horas):
                pl.avisos.append(JANELA_ESTOUROU)
            desde = nova
            _recomecar_passadas_antigas(conn, grupo, desde)
            pl.avisos.append("a execução atravessou a meia-noite; as passadas em andamento recomeçaram" if not ciclo_horas
                             else "a execução atravessou o fim do ciclo; as passadas em andamento recomeçaram")
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

    if ciclo_horas and janela() != desde and janela_estourou(conn, grupo, desde, ciclo_horas):
        pl.avisos.append(JANELA_ESTOUROU)          # a janela acabou durante o último lote
    _fechar_dia_se_completo(conn, grupo, dia)
    if falta := detalhes_em_falta(pl.itens, pl.com):
        pl.avisos.append(f"poucos itens com {', '.join(falta)}: {AVISO_LAYOUT}")
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
    ciclo_horas: int = 0
    mais_antiga_h: float | None = None   # idade, em horas, da passada completa mais velha entre as fatias ativas
    atrasadas: int = 0      # fatias ativas cuja última passada completa passou de limite_atraso(ciclo_horas)
    nunca_lidas: int = 0


CAMPOS_PREENCHIMENTO = {"imagem": "capa", "autor": "autor", "publicado": "data", "idioma": "idioma",
                        "obra": "obra", "avaliacoes": "avaliações"}


def preenchimento(conn: sqlite3.Connection, desde: str) -> tuple[int, dict[str, float]]:
    """Itens lidos desde `desde` e a fração deles com cada detalhe (capa, autor...) no catálogo."""
    colunas = ", ".join(f"COUNT({c})" for c in CAMPOS_PREENCHIMENTO)
    r = conn.execute(f"SELECT COUNT(*), {colunas} FROM catalogo WHERE ultimo_visto >= ?", (desde,)).fetchone()
    n = r[0]
    return n, {c: (r[i + 1] / n if n else 0.0) for i, c in enumerate(CAMPOS_PREENCHIMENTO)}


def detalhes_em_falta(n: int, com: dict[str, int]) -> list[str]:
    """Detalhes que deveriam vir em quase todo card e vieram em poucos dos `n` itens lidos (`com[campo]`
    = quantos vieram com ele): sinal de que a Amazon mudou o layout e o parser deixou de achá-los."""
    if n < ITENS_MIN_PREENCHIMENTO:
        return []
    return [CAMPOS_PREENCHIMENTO[c] for c in CAMPOS_ESPERADOS if com.get(c, 0) < PREENCHIMENTO_MIN * n]


def ler_config(conn: sqlite3.Connection) -> dict:
    return {r[0]: r[1] for r in conn.execute("SELECT chave, valor FROM config")}





def pausa_vigente(conn: sqlite3.Connection, agora: datetime | None = None) -> datetime | None:
    """Até quando a coleta está em pausa depois de um bloqueio, ou None se não está."""
    pausa = modulo_ritmo.pausa_ate(ler_config(conn))
    return pausa if pausa and pausa > (agora or datetime.fromisoformat(db.agora())) else None


def aprender_ciclo_no_banco(conn: sqlite3.Connection, execucao, completou: bool, agora: datetime | None = None,
                            estourou_no_fim: bool = False) -> dict:
    """Guarda no banco o ciclo e a pausa para a próxima execução (ver ritmo.aprender_ciclo)."""
    agora = agora or datetime.fromisoformat(db.agora())
    novo = modulo_ritmo.aprender_ciclo(
        ler_config(conn), agora, execucao["paginas"], execucao["bloqueios"], execucao["erros"] + execucao["curtas"],
        "interrompida" in (execucao["observacao"] or ""), completou,
        estourou_no_fim or JANELA_ESTOUROU in (execucao["observacao"] or ""))
    for chave, valor in novo.items():
        conn.execute("INSERT INTO config (chave, valor) VALUES (?, ?) "
                     "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (chave, valor))
    conn.commit()
    return novo


@dataclass
class Resultado:
    exec_id: int | None = None          # None: nada a fazer (a janela já estava completa) ou em pausa
    pausa_ate: datetime | None = None   # não leu: há uma pausa depois de bloqueio
    ciclo_horas: int = 0
    ppm_inicial: float = 0.0
    teto: float = 0.0
    config_ritmo: dict = field(default_factory=dict)    # o que a execução mudou no teto guardado
    config_ciclo: dict = field(default_factory=dict)    # ... e no ciclo e na pausa
    completou: bool = False             # a janela (ciclo) ficou completa


def ritmo_da_execucao(config: dict, *, ritmo_inicial: float | None = None, ritmo_max: float | None = None,
                      teto_auto_max: float = modulo_ritmo.PPM_TETO_AUTO_MAX, subir_a_cada: int = modulo_ritmo.A_CADA) -> Ritmo:
    """O ritmo com que uma execução começa: o teto e o ritmo guardados no banco (`config`), a não ser que
    `ritmo_max` fixe o teto e `ritmo_inicial` o ritmo de partida."""
    if ritmo_max is None:
        inicio, teto = modulo_ritmo.ritmo_guardado(config, modulo_ritmo.PPM_TETO_PADRAO, maximo=teto_auto_max)
    else:
        inicio, teto = ritmo_inicial or modulo_ritmo.PPM_BASE, ritmo_max
    if ritmo_inicial is not None:
        inicio = ritmo_inicial
    return Ritmo(inicio, teto, a_cada=subir_a_cada)


def descrever_ritmo(r: Ritmo, teto_guardado: bool, ciclo: int, ciclo_guardado: bool) -> str:
    """A linha "ritmo: ..." que a execução (e o --dry-run) mostra."""
    return (f"ritmo: começa em {r.ppm:.0f} páginas/min, teto {r.teto:.0f}" + (" (teto guardado no banco)" if teto_guardado else "")
            + f"; ciclo de {ciclo} h" + (" (guardado no banco)" if ciclo_guardado else ""))


def executar(conn: sqlite3.Connection, sessao, *, no: str = NO_HQ_MANGA, vendidos=None, minutos: float = 60,
             max_paginas: int | None = None, faixas=None, ritmo_inicial: float | None = None,
             ritmo_max: float | None = None, teto_auto_max: float = modulo_ritmo.PPM_TETO_AUTO_MAX,
             subir_a_cada: int = modulo_ritmo.A_CADA, ciclo_horas: int | None = None, ignorar_pausa: bool = False,
             parar_na_falha: bool = False, pasta_html: Path | None = None, dormir=time.sleep,
             relogio=time.monotonic, log=print) -> Resultado:
    """Uma execução completa da coleta: confere a pausa depois de bloqueio, lê o que está na vez (`varrer`) e
    guarda no banco o que aprendeu (teto de ritmo, ciclo, pausa). Sem `ritmo_max`/`ciclo_horas`, esses valores vêm do
    banco e são aprendidos; com eles, ficam fixos e nada é guardado."""
    criar_schema(conn)
    config = ler_config(conn)
    auto = ritmo_max is None
    ciclo = ciclo_horas or modulo_ritmo.ciclo_guardado(config)
    res = Resultado(ciclo_horas=ciclo)
    if ciclo_horas is None and not ignorar_pausa and (pausa := pausa_vigente(conn)):
        res.pausa_ate = pausa
        return res
    r = ritmo_da_execucao(config, ritmo_inicial=ritmo_inicial, ritmo_max=ritmo_max, teto_auto_max=teto_auto_max,
                          subir_a_cada=subir_a_cada)
    res.ppm_inicial, res.teto = r.ppm, r.teto
    log(descrever_ritmo(r, auto, ciclo, ciclo_horas is None))
    res.exec_id = varrer(conn, sessao, no=no, vendidos=vendidos, minutos=minutos, faixas=faixas, max_paginas=max_paginas,
                         pasta_html=pasta_html, ritmo=r, parar_na_falha=parar_na_falha, dormir=dormir, relogio=relogio,
                         ciclo_horas=ciclo)
    grupo = GRUPO_VENDIDOS if vendidos is not None else no
    res.completou = proxima_fatia(conn, grupo, inicio_do_ciclo(ciclo)) is None
    if res.exec_id is None or parar_na_falha or max_paginas is not None:
        return res
    e = conn.execute("SELECT * FROM execucoes WHERE id = ?", (res.exec_id,)).fetchone()
    if auto:
        res.config_ritmo = aprender_ritmo(conn, r, res.teto, e, teto_auto_max)
    if ciclo_horas is None:
        # a janela está para acabar com a passada incompleta, sem que um bloqueio ou falha seja a causa
        agora = datetime.fromisoformat(db.agora())
        desde = inicio_do_ciclo(ciclo, agora)
        fim = datetime.fromisoformat(desde) + timedelta(hours=ciclo)
        limpa = not e["bloqueios"] and "interrompida" not in (e["observacao"] or "")
        no_fim = limpa and fim - agora < timedelta(minutes=FOLGA_JANELA_MIN) and janela_estourou(conn, grupo, desde, ciclo)
        res.config_ciclo = aprender_ciclo_no_banco(conn, e, res.completou, agora, estourou_no_fim=no_fim)
    return res


def aprender_ritmo(conn: sqlite3.Connection, r: Ritmo, teto_inicial: float, execucao,
                   maximo: float | None = None) -> dict:
    """Guarda no banco o teto e o último ritmo limpo para a próxima execução (ver ritmo.aprender)."""
    novo = modulo_ritmo.aprender(ler_config(conn), db.hoje_brasil().isoformat(), r, teto_inicial,
                                 execucao["paginas"], execucao["bloqueios"], execucao["erros"] + execucao["curtas"],
                                 **({"maximo": maximo} if maximo is not None else {}))
    for chave, valor in novo.items():
        conn.execute("INSERT INTO config (chave, valor) VALUES (?, ?) "
                     "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (chave, valor))
    conn.commit()
    return novo


def limite_atraso(ciclo_horas: int) -> float:
    """Horas sem passada completa a partir das quais uma fatia está atrasada: dois ciclos mais folga para a passada."""
    return 2 * ciclo_horas + 2


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
    ciclo = modulo_ritmo.ciclo_guardado(ler_config(conn))
    agora = datetime.fromisoformat(db.agora())
    idades = [(agora - datetime.fromisoformat(r[0])).total_seconds() / 3600 for r in conn.execute(
        "SELECT ultima_passada FROM fatias WHERE grupo = ? AND ativa = 1 AND ultima_passada IS NOT NULL", (grupo,))]
    return Cobertura(
        ciclo_horas=ciclo,
        mais_antiga_h=max(idades, default=None),
        atrasadas=sum(1 for h in idades if h > limite_atraso(ciclo)),
        nunca_lidas=um("SELECT COUNT(*) FROM fatias WHERE grupo = ? AND ativa = 1 AND ultima_passada IS NULL", grupo),
        itens=um("SELECT COUNT(*) FROM catalogo"),
        vistos_hoje=um("SELECT COUNT(*) FROM catalogo WHERE ultimo_visto >= ?", desde),
        fatias=um("SELECT COUNT(*) FROM fatias WHERE grupo = ? AND ativa = 1", grupo),
        fatias_hoje=conn.execute(f"SELECT COUNT(*) FROM fatias WHERE grupo = :g AND ativa = 1 AND {_FEITA_NO_DIA}",
                                 {"g": grupo, "d": desde}).fetchone()[0],
        dia_completo=db.hoje_brasil() in completos,
        lacunas=lacunas,
    )
