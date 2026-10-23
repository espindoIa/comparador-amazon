"""Ritmo da coleta: quantas páginas por minuto, em quantas requisições ao mesmo tempo, e quando recuar.

O ritmo que a Amazon enxerga é o programado aqui (espaçamento uniforme entre as requisições, com um
pouco de variação), não uma rajada. Ele sobe aos poucos enquanto tudo dá certo, até um teto, e
recua ao primeiro sinal de falha: erro ou página que veio curta demais (ver
`varredura.CARDS_MIN_PAGINA`).

Dois tipos de recuo, porque falhas isoladas acontecem (1 página curta em ~2.200 medidas, que voltou
inteira na leitura seguinte) e não devem corroer o ritmo do dia:
- falha leve e isolada (página curta, erro de rede, layout): o ritmo cai pela metade e volta a subir;
- falha leve repetida (outra em menos de `JANELA_REPETIDA` páginas
  boas): o ritmo cai para o mínimo e o teto passa a ser 70% do ritmo em que ela aconteceu.

O ritmo é "programado": cada lote espera a requisição mais lenta, então o real fica abaixo (~10% a 60 programadas,
~15% a 90 com 6 pistas). Medido: 120 programadas com 3 pistas = ~80 reais; 60 programadas com 2 pistas = ~55 reais.
"""

from __future__ import annotations

import math
import random

PPM_BASE = 21.0          # medido em out/2026 com pausa de 1–3 s: 0 bloqueios em ~11 mil páginas
PPM_RECUO = 8.0          # piso do ritmo depois de falhas leves
PPM_TETO_PADRAO = 60.0   # ~46 páginas/min reais; o limpo medido foi 120 programadas (~80 reais) por ~9 min
# Cada lote começa uma requisição por pista, espaçadas no tempo, e só o lote seguinte começa quando a mais
# lenta termina. Se a requisição leva mais que o intervalo entre elas (~0,9 s contra 0,67 s a 90 por minuto),
# o lote estoura e o ritmo real fica abaixo do programado; com mais pistas por lote a perda diminui (simulado com
# a latência medida: a 90 programadas, 2 pistas dão ~68 reais e 6 dão ~78; a 60, 2 dão ~53 e 4 dão ~54).
# As requisições continuam espaçadas: não são rajada, e o ritmo que a Amazon vê é o programado, no máximo.
PPM_POR_PISTA = 15.0
PISTAS_MAX = 8
PPM_MAXIMO = 120.0       # limite absoluto, qualquer que seja a configuração
PPM_TETO_AUTO_MAX = 90.0  # até onde o teto sobe sozinho, de dia em dia (ver `aprender`); o resto é decisão de quem roda
SUBIDA = 1.25            # a cada `a_cada` páginas boas seguidas, o ritmo sobe 25%
A_CADA = 100
FATOR_TETO_APOS_FALHA = 0.7
JANELA_REPETIDA = 500    # outra falha leve em menos de tantas páginas boas conta como repetida
VARIACAO = 0.3           # cada intervalo varia ±30% (a média é a programada)


class Ritmo:
    def __init__(self, ppm: float = PPM_BASE, teto: float | None = None, subida: float = SUBIDA,
                 a_cada: int = A_CADA, sorteio=random.uniform):
        self.teto = min(PPM_MAXIMO, max(ppm, teto) if teto is not None else ppm)
        self.ppm = min(ppm, self.teto)
        self.subida, self.a_cada, self._sorteio = subida, a_cada, sorteio
        self.boas = 0          # páginas boas desde a última mudança de ritmo
        self.boas_desde_falha = 0
        self.falhas = 0

    @property
    def pistas(self) -> int:
        """Quantas requisições podem estar em andamento ao mesmo tempo."""
        if self.ppm <= PPM_BASE:           # o ritmo de sempre (medido uma de cada vez): uma pista só
            return 1
        return min(PISTAS_MAX, max(2, math.ceil(self.ppm / PPM_POR_PISTA)))

    @property
    def intervalo(self) -> float:
        """Segundos entre o início de duas requisições seguidas, em média."""
        return 60.0 / self.ppm

    def _variar(self, x: float) -> float:
        return x * self._sorteio(1 - VARIACAO, 1 + VARIACAO)

    def atrasos(self, n: int) -> list[float]:
        """Instantes (s, a partir do início do lote) em que começa cada uma das `n` requisições."""
        t, saida = 0.0, []
        for i in range(n):
            if i:
                t += self._variar(self.intervalo)
            saida.append(t)
        return saida

    def espera(self, n: int, decorrido: float) -> float:
        """Quanto esperar depois de um lote de `n` requisições que levou `decorrido` s, para o ritmo
        médio ser o programado (as `n` requisições ocupam `n` intervalos)."""
        return max(0.0, self._variar(n * self.intervalo) - decorrido)

    def pagina_boa(self) -> None:
        self.boas += 1
        self.boas_desde_falha += 1
        if self.boas >= self.a_cada and self.ppm < self.teto:
            self.ppm = min(self.teto, self.ppm * self.subida)
            self.boas = 0

    def falha(self, grave: bool = False) -> None:
        """`grave`: bloqueio (captcha, 500/503). Bloqueio não muda o ritmo (a proteção contra bloqueio foi tirada a
        pedido de quem mantém o repositório, em 15/10/2026); só a falha leve recua."""
        if grave:
            return
        repetida = self.falhas > 0 and self.boas_desde_falha < JANELA_REPETIDA
        self.falhas += 1
        self.boas_desde_falha = 0
        self.boas = 0
        if repetida:
            self.teto = max(PPM_RECUO, min(self.teto, self.ppm * FATOR_TETO_APOS_FALHA))
            self.ppm = min(self.ppm, PPM_RECUO)
        else:
            self.ppm = max(PPM_RECUO, self.ppm / 2)


# ---------- teto que se ajusta de um dia para o outro ----------
# O teto não é fixo: fica guardado no banco (tabela config, que viaja na release) e sobe 25% por dia em que a
# coleta rodou limpa no teto, até PPM_TETO_AUTO_MAX. Depois de falha leve repetida cai para o que o freio da execução
# deixou e fica parado por DIAS_DE_ESPERA dias (bloqueio não baixa o teto: ver Ritmo.falha). Assim cada dia de coleta (~4,4 mil
# páginas por sequência) é a evidência para o próximo passo, e quem roda pode baixar o teto com `--ritmo-max`.
PASSO_TETO = 1.25
DIAS_DE_ESPERA = 3
PAGINAS_MIN_EVIDENCIA = 2000     # páginas lidas na execução para ela valer como evidência de subida
FALHAS_LEVES_POR_MIL = 0.5       # erros + páginas curtas por mil páginas aceitos numa execução "limpa" (medido: 0,2)
AO_RETOMAR = 0.8                 # a execução seguinte começa a 80% do último ritmo limpo (e sobe de novo)
# A evidência de dia limpo é a soma das execuções do dia (Brasília), não uma execução só: a 8 páginas/min (o recuo que um
# bloqueio causava até 15/10/2026) uma execução de 165 minutos lê ~1.300 páginas, e com a evidência por execução o teto nunca voltava a
# subir nem o ciclo a descer (medido nas três sequências de 13 a 15/10: 6 execuções limpas cada, nenhuma contada).


# O que a proteção contra bloqueio deixou no banco: o teto que caiu, a espera, o ciclo que subiu e a pausa. Apagado uma
# vez, quando a proteção saiu (varredura.esquecer_bloqueios): o teto e o ciclo recomeçam dos valores iniciais.
CHAVES_DE_BLOQUEIO = ("ritmo_teto", "ritmo_espera_ate", "ritmo_ultimo_limpo", "ritmo_subiu_em", "ritmo_pausa_ate",
                      "bloqueios_seguidos", "ciclo_horas", "ciclo_desde", "ciclo_espera_ate")
MARCA_SEM_BLOQUEIO = "protecao_bloqueio_removida"


def ritmo_guardado(config: dict, padrao_teto: float, base: float = PPM_BASE,
                   maximo: float = PPM_TETO_AUTO_MAX) -> tuple[float, float]:
    """(ritmo inicial, teto) para uma execução, a partir de `config` (chave -> texto). O teto guardado nunca
    passa de `maximo`: quem baixa o limite (várias sequências em paralelo) vale mesmo sobre um teto já guardado."""
    def num(k, d):
        try:
            return float(config[k])
        except (KeyError, ValueError):
            return d
    teto = min(PPM_MAXIMO, maximo, max(PPM_RECUO, num("ritmo_teto", padrao_teto)))
    inicio = num("ritmo_ultimo_limpo", 0.0) * AO_RETOMAR
    return min(teto, max(base, inicio)), teto


def aprender(config: dict, hoje: str, ritmo: "Ritmo", teto_inicial: float, paginas: int, bloqueios: int,
             leves: int, maximo: float = PPM_TETO_AUTO_MAX, evidencia: tuple[int, int] | None = None) -> dict:
    """Novos valores de config depois de uma execução. `hoje` = AAAA-MM-DD (Brasília). Só devolve o que mudou.
    O teto sobe sozinho até `maximo`, no máximo. `evidencia`: (páginas, falhas leves) do dia inteiro, que decide se
    houve coleta limpa (sem ela, só a execução). `bloqueios` não muda nada (ver Ritmo.falha)."""
    novo: dict = {}
    if ritmo.teto < teto_inicial - 1e-9:       # falha leve repetida (bloqueio não conta: ver Ritmo.falha)
        novo["ritmo_teto"] = f"{max(PPM_RECUO, min(ritmo.teto, teto_inicial)):.1f}"
        novo["ritmo_espera_ate"] = _somar_dias(hoje, DIAS_DE_ESPERA)
        novo["ritmo_ultimo_limpo"] = ""
        return novo
    paginas_ev, leves_ev = evidencia or (paginas, leves)
    limpa = paginas_ev >= PAGINAS_MIN_EVIDENCIA and leves_ev * 1000 <= FALHAS_LEVES_POR_MIL * paginas_ev
    if limpa:
        novo["ritmo_ultimo_limpo"] = f"{ritmo.ppm:.1f}"
    no_teto = ritmo.ppm >= 0.95 * ritmo.teto
    esperando = config.get("ritmo_espera_ate", "") > hoje
    if limpa and no_teto and not esperando and config.get("ritmo_subiu_em", "") < hoje and ritmo.teto < maximo:
        novo["ritmo_teto"] = f"{min(maximo, ritmo.teto * PASSO_TETO):.1f}"
        novo["ritmo_subiu_em"] = hoje
    return novo


def _somar_dias(dia: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(dia) + timedelta(days=n)).isoformat()


# ---------- frequência das passadas (ciclo) ----------
# Quantas vezes por dia o catálogo inteiro é lido. O objetivo é CICLOS[0] (uma passada a cada 3 h, 8 por dia, ~105 mil
# páginas por dia no total), mas nunca se mediu esse volume: o mais alto sem bloqueio foi 12,6 mil páginas por dia. Por
# isso o ciclo é um degrau que se guarda no banco, como o teto de ritmo: começa em CICLO_INICIAL e desce UM degrau por dia
# limpo (12 → 6 → 3 h) e sobe um degrau a cada sinal de aperto (páginas curtas) ou janela estourada.
#
# Bloqueio não pausa a coleta nem sobe o ciclo: a proteção contra bloqueio (pausa de horas, ciclo diário, teto que cai)
# foi tirada a pedido de quem mantém o repositório em 15/10/2026. A chave `ritmo_pausa_ate` continua sendo lida, mas nada
# mais a grava.
CICLOS = (3, 6, 12, 24)
CICLO_INICIAL = 12
PAUSA_BASE_H = 3                 # espera depois de uma publicação que falhou (scripts/proximo_ciclo.py)
LEVES_POR_MIL_RUIM = 2.0         # acima disto (páginas curtas e erros por mil) o ciclo sobe
# O ciclo só desce se a passada couber no degrau de baixo: sem isso ele desceria mais rápido que o teto sobe (um degrau
# por dia contra 25%), a passada estouraria a janela e o ciclo voltaria a subir, com mais 3 dias de espera.
REAL_SOBRE_PROGRAMADO = 0.9      # páginas reais por minuto / programadas (ver o começo deste arquivo)
OCUPACAO_MAX = 0.85              # fração do ciclo que a passada pode ocupar (as execuções se emendam com alguns minutos entre elas)


def horas_da_passada(paginas: int, teto: float) -> float:
    """Horas para ler `paginas` no `teto` (páginas programadas por minuto)."""
    return paginas / (max(teto, 1e-9) * REAL_SOBRE_PROGRAMADO) / 60


def _numero(config: dict, chave: str, padrao: int) -> int:
    try:
        return int(config[chave])
    except (KeyError, ValueError):
        return padrao


def ciclo_guardado(config: dict) -> int:
    """Horas entre passadas completas, a partir de `config` (chave -> texto); sem valor válido, CICLO_INICIAL."""
    c = _numero(config, "ciclo_horas", CICLO_INICIAL)
    return c if c in CICLOS else CICLO_INICIAL


def pausa_ate(config: dict):
    """Instante (aware) até o qual não se lê (pausa gravada antes de 15/10/2026, quando bloqueio ainda pausava), ou None."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(config["ritmo_pausa_ate"])
    except (KeyError, ValueError):
        return None


def saude(paginas: int, bloqueios: int, leves: int) -> str:
    """"ruim" (aperto; `bloqueios` não conta), "limpa" (evidência suficiente e quase nenhuma falha), "alerta" (evidência suficiente e
    mais falhas que o limpo, menos que o ruim) ou "neutra" (pouca evidência)."""
    if paginas >= PAGINAS_MIN_EVIDENCIA // 2 and leves * 1000 > LEVES_POR_MIL_RUIM * paginas:   # bloqueio não conta
        return "ruim"
    if paginas >= PAGINAS_MIN_EVIDENCIA:
        return "limpa" if leves * 1000 <= FALHAS_LEVES_POR_MIL * paginas else "alerta"
    return "neutra"


def aprender_ciclo(config: dict, agora, paginas: int, bloqueios: int, leves: int, interrompida: bool,
                   completou: bool, estourou: bool = False, evidencia: tuple[int, int] | None = None,
                   passada_h: float | None = None) -> dict:
    """Novos valores de config para o ciclo depois de uma execução. `agora`: datetime com fuso. Só devolve o que mudou.
    `bloqueios` e `interrompida` não mudam nada (ver o comentário de CICLOS).

    - aperto (muitas páginas curtas) ou janela que acabou com fatias sem ler (`estourou`: a sequência não dá conta de
      uma passada no tempo do ciclo): o ciclo sobe um degrau e fica parado, sem pausa;
    - alerta (mais falhas leves que o limpo, menos que o aperto): o ciclo fica onde está e o dia no degrau recomeça;
    - passada completa e dia limpo, depois de um dia inteiro no degrau e do fim da espera: o ciclo desce um degrau, se
      a passada (`passada_h` horas no teto atual) ocupar até OCUPACAO_MAX dele.
    `evidencia`: (páginas, falhas leves) do dia inteiro, que decide se o dia foi limpo (sem ela, só a execução). As
    punições (aperto, alerta, janela estourada) olham sempre só a execução.
    """
    from .db import BRASILIA
    hoje = agora.astimezone(BRASILIA).date().isoformat()
    ciclo = ciclo_guardado(config)
    nivel = CICLOS.index(ciclo)
    novo: dict = {}
    if "ciclo_horas" not in config:
        novo["ciclo_horas"] = str(ciclo)
    if "ciclo_desde" not in config:
        novo["ciclo_desde"] = hoje
    situacao = saude(paginas, bloqueios, leves)
    dia_limpo = saude(evidencia[0], 0, evidencia[1]) == "limpa" if evidencia else situacao == "limpa"
    if situacao == "ruim" or estourou:
        degrau = min(nivel + 1, len(CICLOS) - 1)
        if degrau != nivel:
            novo["ciclo_horas"] = str(CICLOS[degrau])
            novo["ciclo_desde"] = hoje
        novo["ciclo_espera_ate"] = _somar_dias(hoje, DIAS_DE_ESPERA)
    elif situacao == "alerta":
        novo["ciclo_desde"] = hoje
    elif completou and dia_limpo:
        desde = novo.get("ciclo_desde", config.get("ciclo_desde", hoje))
        cabe = passada_h is None or nivel == 0 or passada_h <= OCUPACAO_MAX * CICLOS[nivel - 1]
        if nivel > 0 and desde < hoje and config.get("ciclo_espera_ate", "") <= hoje and cabe:
            novo["ciclo_horas"] = str(CICLOS[nivel - 1])
            novo["ciclo_desde"] = hoje
    return novo
