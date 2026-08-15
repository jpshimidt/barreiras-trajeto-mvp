"""
A tabela de decisão, e nada além dela.

| Responsável escolheu a escola | Caminho a pé toca barreira | Resultado    |
|-------------------------------|----------------------------|--------------|
| Sim                           | irrelevante                | Sem direito  |
| Não                           | Sim                        | Com direito  |
| Não                           | Não                        | Sem direito  |

Não entram no critério: distância percorrida, idade, turno, série, vaga ou veículo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.barreiras import Barreira
from core.routing import Rota


@dataclass
class Resultado:
    tem_direito: bool
    motivo: str  # texto para o usuário final
    distancia_m: float | None
    barreiras_atingidas: list[str] = field(default_factory=list)


def decidir(rota: Rota | None, atingidas: list[Barreira], escolheu_escola: bool) -> Resultado:
    if escolheu_escola:
        return Resultado(False, "A responsável escolheu esta escola.", None, [])

    distancia = rota.distancia_m if rota else None

    if atingidas:
        # Uma mesma avenida vem fragmentada em dezenas de ways: o usuário lê o nome
        # da rua uma vez, não uma vez por trecho.
        nomes = sorted({b.nome for b in atingidas})
        return Resultado(
            True,
            f"O menor caminho a pé passa por: {', '.join(nomes)}.",
            distancia,
            nomes,
        )

    return Resultado(
        False,
        "O menor caminho a pé não passa por nenhuma barreira física.",
        distancia,
        [],
    )
