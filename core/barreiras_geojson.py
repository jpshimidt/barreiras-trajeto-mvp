"""Serialização de barreiras em GeoJSON FeatureCollection."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from core.barreiras import Barreira, _int_ou_none
from core.erros import ErroExterno
from core.geo_limites import coordenada_em_sao_paulo

MUNICIPIO_PADRAO = "São Paulo"
MAX_GEOM_JSON_CHARS = 50_000
MAX_VERTICES_LINHA = 500


def barreira_de_feature(feature: dict, indice: int = 0) -> Barreira | None:
    geometria = feature.get("geometry")
    if not geometria:
        return None
    geom = shape(geometria)
    if geom.is_empty:
        return None
    props = feature.get("properties") or {}
    return Barreira(
        id=str(props.get("id") or f"feature-{indice}"),
        nome=props.get("nome") or "(sem nome)",
        tipo=props.get("tipo") or "(sem tipo)",
        geometria=geom,
        numero_inicio=_int_ou_none(props.get("numero_inicio")),
        numero_fim=_int_ou_none(props.get("numero_fim")),
        paridade=props.get("paridade") or None,
    )


def barreiras_de_geojson(colecao: dict) -> list[Barreira]:
    barreiras: list[Barreira] = []
    for i, feature in enumerate(colecao.get("features") or []):
        barreira = barreira_de_feature(feature, i)
        if barreira:
            barreiras.append(barreira)
    if not barreiras:
        raise ErroExterno("Nenhuma barreira utilizável no GeoJSON")
    return barreiras


def barreira_para_feature(barreira: Barreira, *, origem: str = "app") -> dict:
    props: dict[str, Any] = {
        "id": barreira.id,
        "nome": barreira.nome,
        "tipo": barreira.tipo,
        "municipio": MUNICIPIO_PADRAO,
        "origem": origem,
        "atualizado_em": date.today().isoformat(),
    }
    if barreira.numero_inicio is not None:
        props["numero_inicio"] = barreira.numero_inicio
    if barreira.numero_fim is not None:
        props["numero_fim"] = barreira.numero_fim
    if barreira.paridade:
        props["paridade"] = barreira.paridade
    return {
        "type": "Feature",
        "geometry": mapping(barreira.geometria),
        "properties": props,
    }


def geojson_de_barreiras(barreiras: list[Barreira], *, nome: str = "barreiras") -> dict:
    return {
        "type": "FeatureCollection",
        "name": nome,
        "features": [barreira_para_feature(b) for b in barreiras],
    }


def geojson_para_texto(colecao: dict) -> str:
    return json.dumps(colecao, ensure_ascii=False, indent=1)


def texto_para_geojson(texto: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErroExterno(f"GeoJSON inválido: {e}") from e


def geometria_de_coords_json(texto: str) -> BaseGeometry:
    """Aceita coordenadas ``[[lon, lat], ...]`` ou um Feature/Geometry GeoJSON."""
    if len(texto) > MAX_GEOM_JSON_CHARS:
        raise ErroExterno(f"Geometria muito grande (máx. {MAX_GEOM_JSON_CHARS} caracteres).")
    try:
        bruto = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErroExterno(f"JSON inválido: {e}") from e

    if isinstance(bruto, list):
        geom = shape({"type": "LineString", "coordinates": bruto})
    elif isinstance(bruto, dict):
        if bruto.get("type") == "Feature":
            geom = shape(bruto["geometry"])
        else:
            geom = shape(bruto)
    else:
        raise ErroExterno("Formato de geometria não reconhecido — use [[lon, lat], ...] ou GeoJSON.")

    if geom.geom_type != "LineString":
        raise ErroExterno(f"Apenas LineString é aceita (recebido: {geom.geom_type}).")
    if len(geom.coords) < 2:
        raise ErroExterno("A linha precisa de pelo menos dois pontos.")
    if len(geom.coords) > MAX_VERTICES_LINHA:
        raise ErroExterno(f"Máximo de {MAX_VERTICES_LINHA} vértices por trecho.")

    for lon, lat in geom.coords:
        if not coordenada_em_sao_paulo(lat, lon):
            raise ErroExterno("Todos os vértices devem estar dentro do município de São Paulo.")
    return geom
