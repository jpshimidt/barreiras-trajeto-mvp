"""Limites geográficos e validação de coordenadas — São Paulo capital."""

from __future__ import annotations

# Bounding box generoso do município de São Paulo (EPSG:4326).
SP_MIN_LON = -46.95
SP_MIN_LAT = -23.98
SP_MAX_LON = -46.35
SP_MAX_LAT = -23.35


def coordenada_em_sao_paulo(lat: float, lon: float) -> bool:
    return SP_MIN_LAT <= lat <= SP_MAX_LAT and SP_MIN_LON <= lon <= SP_MAX_LON


def exigir_coordenada_em_sao_paulo(lat: float, lon: float) -> None:
    from core.erros import ErroExterno

    if not coordenada_em_sao_paulo(lat, lon):
        raise ErroExterno(
            "As coordenadas estão fora do município de São Paulo. "
            "Este app só avalia endereços na capital."
        )
