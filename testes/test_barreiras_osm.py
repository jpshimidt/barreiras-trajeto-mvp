"""Testes de busca OSM para cadastro de barreiras."""

from __future__ import annotations

import pytest

from core.barreiras_osm import (
    buscar_barreiras_rua,
    feature_de_way,
    nome_via_de_entrada,
    overpass_para_geojson,
)
from core.erros import ErroExterno
from core.recorte_trecho import RegistroTrecho


def way(id_: int, nome: str, highway: str = "trunk", coords=((-46.63, -23.51), (-46.62, -23.51))):
    return {
        "type": "way",
        "id": id_,
        "tags": {"name": nome, "highway": highway},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in coords],
    }


def test_nome_via_de_endereco_maps():
    texto = "R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000"
    assert nome_via_de_entrada(texto) == "R. Borges"


def test_nome_via_mantem_texto_simples():
    assert nome_via_de_entrada("Marginal Tietê") == "Marginal Tietê"


def test_buscar_barreiras_rua_sem_rede(monkeypatch):
    resposta = {"elements": [way(1, "Marginal Tietê")]}

    def falso_overpass(sessao, consulta):
        return resposta

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", falso_overpass)

    barreiras = buscar_barreiras_rua("Marginal Tietê")
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Marginal Tietê"
    assert barreiras[0].tipo == "via expressa"


def test_buscar_barreiras_tenta_regex_quando_nome_exato_falha(monkeypatch):
    chamadas: list[bool] = []

    def falso_overpass(sessao, consulta):
        regex = '"name"~' in consulta
        chamadas.append(regex)
        if not regex:
            return {"elements": []}
        return {"elements": [way(2, "Via Marginal Tietê")]}

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", falso_overpass)

    barreiras = buscar_barreiras_rua("Marginal Tietê")
    assert chamadas == [False, True]
    assert len(barreiras) == 1
    assert "Tietê" in barreiras[0].nome


def test_buscar_barreiras_falha_clara(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.consultar_overpass",
        lambda sessao, consulta: {"elements": []},
    )
    with pytest.raises(ErroExterno, match="Nenhum trecho encontrado"):
        buscar_barreiras_rua("Rua Inexistente XYZ", regex=True)


def test_overpass_para_geojson_trecho_inteiro():
    geojson = overpass_para_geojson(
        {"elements": [way(10, "Av. Paulista")]},
        trechos=[RegistroTrecho("Av. Paulista")],
    )
    assert len(geojson["features"]) == 1
    assert geojson["features"][0]["properties"]["nome"] == "Av. Paulista"


def test_feature_de_way_preserva_tipo_osm():
    props = feature_de_way(way(1, "Rua Teste", highway="residential"), "2026-01-01")["properties"]
    assert props["tipo"] == "rua"
