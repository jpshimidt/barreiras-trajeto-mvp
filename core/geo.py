"""
Projeção métrica.

Aplicar `.buffer(5)` direto em geometria WGS84 cria um buffer de 5 GRAUS —
centenas de quilômetros. Tudo que envolve distância passa por aqui antes.
"""

from __future__ import annotations

from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.ops import transform as shapely_transform


def crs_utm_local(lon: float, lat: float) -> CRS:
    """Zona UTM WGS84 do ponto. São Paulo capital cai na 23S (EPSG:32723)."""
    zona = int((lon + 180) // 6) + 1
    epsg = (32700 if lat < 0 else 32600) + zona
    return CRS.from_epsg(epsg)


@lru_cache(maxsize=8)
def _transformador(epsg_destino: int) -> Transformer:
    return Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg_destino), always_xy=True)


def para_metrico(geom, crs_destino: CRS):
    """Projeta de WGS84 (graus) para o CRS métrico informado."""
    return shapely_transform(_transformador(crs_destino.to_epsg()).transform, geom)
