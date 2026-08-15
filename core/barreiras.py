"""Carga do GeoJSON de barreiras e verificação de interseção com a rota."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from core.erros import ErroExterno
from core.geo import crs_utm_local, para_metrico
from core.routing import Rota

BUFFER_M_PADRAO = 5.0

# ~1,1 km em graus. Descarta barreiras longe da rota antes de projetar — uma via
# como a Marginal sozinha traz milhares de vértices, e projetar tudo custa caro.
# Folga imensa diante de um buffer de 5 m, então não gera falso negativo.
RAIO_PREFILTRO_GRAUS = 0.01


@dataclass
class Barreira:
    id: str
    nome: str
    tipo: str
    geometria: BaseGeometry  # LineString ou MultiLineString, EPSG:4326


def carregar_barreiras(caminho: str | Path) -> list[Barreira]:
    """
    Lê o FeatureCollection em EPSG:4326. Erro se o arquivo não render nenhuma
    barreira: um cadastro vazio produziria "sem direito" para todo mundo, em
    silêncio, e isso não pode passar por resposta válida.
    """
    caminho = Path(caminho)
    try:
        with open(caminho, encoding="utf-8") as f:
            colecao = json.load(f)
    except FileNotFoundError as e:
        raise ErroExterno(f"Arquivo de barreiras não encontrado: {caminho}") from e
    except json.JSONDecodeError as e:
        raise ErroExterno(f"Arquivo de barreiras não é JSON válido: {caminho} — {e}") from e

    barreiras: list[Barreira] = []
    for i, feature in enumerate(colecao.get("features") or []):
        geometria = feature.get("geometry")
        if not geometria:
            continue
        geom = shape(geometria)
        if geom.is_empty:
            continue
        props = feature.get("properties") or {}
        barreiras.append(
            Barreira(
                id=str(props.get("id") or f"feature-{i}"),
                nome=props.get("nome") or "(sem nome)",
                tipo=props.get("tipo") or "(sem tipo)",
                geometria=geom,
            )
        )

    if not barreiras:
        raise ErroExterno(f"Nenhuma barreira utilizável em {caminho}")
    return barreiras


def proximas_da_rota(
    rota: Rota, barreiras: list[Barreira], margem_graus: float = RAIO_PREFILTRO_GRAUS
) -> list[Barreira]:
    """
    Barreiras cujo bounding box encosta no da rota, com folga.

    Serve a dois propósitos: evitar projetar o cadastro inteiro a cada consulta, e
    desenhar no mapa só o que está por perto — o GeoJSON real tem megabytes, e jogar
    tudo no Folium trava o navegador.
    """
    minx, miny, maxx, maxy = rota.linha.bounds
    minx -= margem_graus
    miny -= margem_graus
    maxx += margem_graus
    maxy += margem_graus

    perto = []
    for barreira in barreiras:
        bminx, bminy, bmaxx, bmaxy = barreira.geometria.bounds
        if bmaxx < minx or bminx > maxx or bmaxy < miny or bminy > maxy:
            continue
        perto.append(barreira)
    return perto


def barreiras_atingidas(
    rota: Rota, barreiras: list[Barreira], buffer_m: float = BUFFER_M_PADRAO
) -> list[Barreira]:
    """
    Projeta rota e barreiras para a UTM local, aplica o buffer em METROS na barreira
    e devolve as que a rota intersecta.

    `intersects` booleano puro: caminhar ao longo da barreira e atravessá-la dão o
    mesmo resultado. Não se conta cruzamento nem se analisa ângulo.
    """
    if buffer_m < 0:
        raise ValueError("buffer_m não pode ser negativo")

    crs = crs_utm_local(*rota.linha.centroid.coords[0])
    rota_m = para_metrico(rota.linha, crs)

    atingidas: list[Barreira] = []
    for barreira in proximas_da_rota(rota, barreiras):
        area_influencia = para_metrico(barreira.geometria, crs).buffer(buffer_m)
        if rota_m.intersects(area_influencia):
            atingidas.append(barreira)
    return atingidas
