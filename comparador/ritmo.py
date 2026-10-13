"""Ritmo da coleta: quantas páginas por minuto, em quantas requisições ao mesmo tempo, e quando recuar.

O ritmo que a Amazon enxerga é o programado aqui (espaçamento uniforme entre as requisições, com um
pouco de variação), não uma rajada. Ele sobe aos poucos enquanto tudo dá certo, até um teto, e
recua ao primeiro sinal de falha: bloqueio, erro, ou página que veio curta demais (ver
`varredura.CARDS_MIN_PAGINA`).

Dois tipos de recuo, porque falhas isoladas acontecem (1 página curta em ~2.200 medidas, que voltou
inteira na leitura seguinte) e não devem corroer o ritmo do dia:
- falha leve e isolada (página curta, erro de rede, layout): o ritmo cai pela metade e volta a subir;
- bloqueio (captcha, HTTP 500/503) ou falha leve repetida (outra em menos de `JANELA_REPETIDA` páginas
  boas): o ritmo cai para o mínimo e o teto passa a ser 70% do ritmo em que ela aconteceu.

O ritmo é "programado": cada lote espera a requisição mais lenta, então o real fica abaixo (~10% a 60 programadas,
~15% a 90 com 6 pistas). Medido: 120 programadas com 3 pistas = ~80 reais; 60 programadas com 2 pistas = ~55 reais.
"""

from __future__ import annotations

import math
import random

PPM_BASE = 21.0          # medido em out/2026 com pausa de 1–3 s: 0 bloqueios em ~11 mil páginas
PPM_RECUO = 8.0          # depois de um bloqueio: parecido com a pausa 3x maior que existia antes
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
        """`grave`: bloqueio (captcha, 500/503). Uma falha leve só é tratada como grave se for repetida."""
        repetida = self.falhas > 0 and self.boas_desde_falha < JANELA_REPETIDA
        self.falhas += 1
        self.boas_desde_falha = 0
        self.boas = 0
        if grave or repetida:
            self.teto = max(PPM_RECUO, min(self.teto, self.ppm * FATOR_TETO_APOS_FALHA))
            self.ppm = min(self.ppm, PPM_RECUO)
        else:
            self.ppm = max(PPM_RECUO, self.ppm / 2)


# ---------- teto que se ajusta de um dia para o outro ----------
# O teto não é fixo: fica guardado no banco (tabela config, que viaja na release) e sobe 25% por dia em que a
# coleta rodou limpa no teto, até PPM_TETO_AUTO_MAX. Depois de um bloqueio (ou de falha repetida) cai para o
# que o freio da execução deixou e fica parado por DIAS_DE_ESPERA dias. Assim cada dia de coleta (~4,4 mil
# páginas por sequência) é a evidência para o próximo passo, e quem roda pode baixar o teto com `--ritmo-max`.
PASSO_TETO = 1.25
DIAS_DE_ESPERA = 3
PAGINAS_MIN_EVIDENCIA = 2000     # páginas lidas na execução para ela valer como evidência de subida
FALHAS_LEVES_POR_MIL = 0.5       # erros + páginas curtas por mil páginas aceitos numa execução "limpa" (medido: 0,2)
AO_RETOMAR = 0.8                 # a execução seguinte começa a 80% do último ritmo limpo (e sobe de novo)


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
             leves: int, maximo: float = PPM_TETO_AUTO_MAX) -> dict:
    """Novos valores de config depois de uma execução. `hoje` = AAAA-MM-DD (Brasília). Só devolve o que mudou.
    O teto sobe sozinho até `maximo`, no máximo."""
    novo: dict = {}
    if ritmo.teto < teto_inicial - 1e-9 or bloqueios:
        novo["ritmo_teto"] = f"{max(PPM_RECUO, min(ritmo.teto, teto_inicial)):.1f}"
        novo["ritmo_espera_ate"] = _somar_dias(hoje, DIAS_DE_ESPERA)
        novo["ritmo_ultimo_limpo"] = ""
        return novo
    limpa = paginas >= PAGINAS_MIN_EVIDENCIA and leves * 1000 <= FALHAS_LEVES_POR_MIL * paginas
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
