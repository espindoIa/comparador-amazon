"""Ritmo da coleta: quantas páginas por minuto, em quantas requisições ao mesmo tempo, e quando recuar.

O ritmo que a Amazon enxerga é o programado aqui (espaçamento uniforme entre as requisições, com um
pouco de variação), não uma rajada. Ele sobe aos poucos enquanto tudo dá certo, até um teto, e
recua no primeiro sinal de falha: bloqueio, erro, ou página que veio curta demais (ver
`varredura.CARDS_MIN_PAGINA`). Depois de uma falha, o teto passa a ser 70% do ritmo em que ela
aconteceu e a subida recomeça devagar, a partir do ritmo de recuo.
"""

from __future__ import annotations

import math
import random

PPM_BASE = 21.0          # medido em out/2026 com pausa de 1–3 s: 0 bloqueios em ~11 mil páginas
PPM_RECUO = 8.0          # depois de uma falha: parecido com a pausa 3x maior que existia antes
PPM_POR_PISTA = 45.0     # uma requisição por vez dá até ~45 páginas/min (cada uma leva ~0,9 s)
PISTAS_MAX = 4
PPM_MAXIMO = 120.0       # limite absoluto, qualquer que seja a configuração
SUBIDA = 1.25            # a cada `a_cada` páginas boas seguidas, o ritmo sobe 25%
A_CADA = 100
FATOR_TETO_APOS_FALHA = 0.7
VARIACAO = 0.3           # cada intervalo varia ±30% (a média é a programada)


class Ritmo:
    def __init__(self, ppm: float = PPM_BASE, teto: float | None = None, subida: float = SUBIDA,
                 a_cada: int = A_CADA, sorteio=random.uniform):
        self.teto = min(PPM_MAXIMO, max(ppm, teto) if teto is not None else ppm)
        self.ppm = min(ppm, self.teto)
        self.subida, self.a_cada, self._sorteio = subida, a_cada, sorteio
        self.boas = 0          # páginas boas desde a última mudança de ritmo
        self.falhas = 0

    @property
    def pistas(self) -> int:
        """Quantas requisições podem estar em andamento ao mesmo tempo."""
        return min(PISTAS_MAX, max(1, math.ceil(self.ppm / PPM_POR_PISTA)))

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
        if self.boas >= self.a_cada and self.ppm < self.teto:
            self.ppm = min(self.teto, self.ppm * self.subida)
            self.boas = 0

    def falha(self) -> None:
        self.falhas += 1
        self.teto = max(PPM_RECUO, min(self.teto, self.ppm * FATOR_TETO_APOS_FALHA))
        self.ppm = min(self.ppm, PPM_RECUO)
        self.boas = 0
