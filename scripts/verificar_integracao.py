#!/usr/bin/env python3
"""
Smoke test da integração real com o OpenRouteService.

Uso:
    export ORS_API_KEY="sua-chave"
    python scripts/verificar_integracao.py

Códigos de saída:
    0 — geocodificação e roteamento ok
    1 — chave presente, mas a API falhou
    2 — chave não encontrada
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.erros import ErroExterno
from core.geocode import geocodificar
from core.ors import ler_api_key
from core.routing import rota_a_pe

# Endereço fixo do caso 1 do marco1.py — Santana, SP
TEXTO_CASA = "Rua Voluntários da Pátria, 1000, Santana, São Paulo, SP"
CEP_CASA = "02011-000"
TEXTO_ESCOLA = "Avenida Rudge, 700, Bom Retiro, São Paulo, SP"
CEP_ESCOLA = "01133-000"


def main() -> int:
    try:
        chave = ler_api_key()
    except ErroExterno as exc:
        print(exc, file=sys.stderr)
        print(
            "\nConfigure a chave em .streamlit/secrets.toml ou export ORS_API_KEY.",
            file=sys.stderr,
        )
        return 2

    print("Chave encontrada. Testando geocodificação...")
    try:
        casa = geocodificar(TEXTO_CASA, chave, cep=CEP_CASA)[0]
        escola = geocodificar(TEXTO_ESCOLA, chave, cep=CEP_ESCOLA)[0]
    except ErroExterno as exc:
        print(f"Falha na geocodificação: {exc}", file=sys.stderr)
        return 1

    print(f"  Casa  : {casa.endereco_formatado}")
    print(f"          ({casa.lat:.6f}, {casa.lon:.6f})")
    print(f"  Escola: {escola.endereco_formatado}")
    print(f"          ({escola.lat:.6f}, {escola.lon:.6f})")

    print("\nTestando roteamento a pé...")
    try:
        rota = rota_a_pe(casa, escola, api_key=chave)
    except ErroExterno as exc:
        print(f"Falha no roteamento: {exc}", file=sys.stderr)
        return 1

    print(f"  Distância: {rota.distancia_m:.0f} m")
    print(f"  Duração  : {rota.duracao_s:.0f} s")
    print("\nIntegração OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
