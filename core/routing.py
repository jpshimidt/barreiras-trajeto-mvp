"""Coordenadas -> menor caminho a pé (ORS, perfil foot-walking)."""

from __future__ import annotations

from dataclasses import dataclass

import requests
from shapely.geometry import LineString, shape

from core.erros import ErroExterno
from core.geo import crs_utm_local, para_metrico
from core.geocode import Local
from core.ors import TIMEOUT_S, erro_http

URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"


@dataclass
class Rota:
    linha: LineString  # EPSG:4326, ordem (lon, lat)
    distancia_m: float
    duracao_s: float


def rota_de_geojson(resposta: dict) -> Rota:
    """Extrai a rota da resposta do ORS. Separado da chamada HTTP para poder testar."""
    features = resposta.get("features") or []
    if not features:
        raise ErroExterno("O OpenRouteService não achou rota a pé entre os dois pontos.")

    feature = features[0]
    resumo = ((feature.get("properties") or {}).get("summary")) or {}
    linha = shape(feature["geometry"])
    if linha.is_empty:
        raise ErroExterno("O OpenRouteService devolveu uma rota vazia.")

    return Rota(
        linha=linha,
        distancia_m=float(resumo.get("distance", 0.0)),
        duracao_s=float(resumo.get("duration", 0.0)),
    )


def rota_a_pe(origem: Local, destino: Local, api_key: str) -> Rota:
    """
    Sempre a rota mais curta. A existência de um desvio alternativo sem barreira
    não altera a decisão — não se pede rota alternativa.
    """
    corpo = {"coordinates": [[origem.lon, origem.lat], [destino.lon, destino.lat]]}
    cabecalhos = {"Authorization": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(URL, json=corpo, headers=cabecalhos, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroExterno(f"Roteamento falhou na rede: {e}") from e
    if resp.status_code != 200:
        raise erro_http(resp, "Roteamento")
    return rota_de_geojson(resp.json())


def rota_reta(origem: Local, destino: Local) -> Rota:
    """
    Linha reta entre A e B, sem chamar a API.

    NÃO é o menor caminho a pé: serve para exercitar projeção, buffer e interseção
    sem chave e sem rede. Quem usa isso tem de deixar claro na saída que o resultado
    não vale como decisão real.
    """
    linha = LineString([(origem.lon, origem.lat), (destino.lon, destino.lat)])
    crs = crs_utm_local(*linha.centroid.coords[0])
    return Rota(linha=linha, distancia_m=para_metrico(linha, crs).length, duracao_s=0.0)
