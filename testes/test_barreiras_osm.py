"""Testes de busca OSM para cadastro de barreiras."""

from __future__ import annotations

import pytest
import requests

from core.barreiras_osm import (
    OVERPASS_ENDPOINTS,
    OverpassIndisponivel,
    buscar_barreiras_rua,
    consultar_overpass,
    decodificar_polyline,
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


def test_consultar_overpass_tenta_proximo_mirror(monkeypatch):
    urls_tentadas: list[str] = []

    class RespostaFalsa:
        status_code = 200

        @staticmethod
        def json():
            return {"elements": []}

    def post_falso(self, url, **kwargs):
        urls_tentadas.append(url)
        if "overpass-api.de" in url:
            raise requests.exceptions.ConnectionError("Connection refused")
        return RespostaFalsa()

    monkeypatch.setattr("core.barreiras_osm.ler_overpass_urls", lambda: list(OVERPASS_ENDPOINTS))
    monkeypatch.setattr(requests.Session, "post", post_falso)

    resultado = consultar_overpass(requests.Session(), "[out:json];way(1);out;")
    assert resultado == {"elements": []}
    assert urls_tentadas[0].endswith("overpass-api.de/api/interpreter")
    assert any("kumi.systems" in u for u in urls_tentadas)


def test_buscar_barreiras_usa_nominatim_quando_overpass_indisponivel(monkeypatch):
    def overpass_falha(sessao, consulta):
        raise OverpassIndisponivel("todos os mirrors falharam")

    feature_nominatim = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-46.63, -23.51], [-46.62, -23.51]],
        },
        "properties": {
            "id": "rua-cruz-de-malta-nominatim-1",
            "nome": "Rua Cruz de Malta",
            "tipo": "rua",
            "municipio": "São Paulo",
            "origem": "nominatim",
        },
    }

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", overpass_falha)
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_nominatim",
        lambda sessao, nome, trecho=None: [feature_nominatim],
    )

    barreiras = buscar_barreiras_rua("Rua Cruz de Malta")
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"


def test_decodificar_polyline_google():
    # Linha (38.5, -120.2) → (40.7, -120.95) → (43.252, -126.453) do exemplo do Google
    coords = decodificar_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert len(coords) == 3
    assert coords[0] == pytest.approx((-120.2, 38.5), abs=1e-4)


def test_buscar_barreiras_usa_google_quando_nominatim_falha(monkeypatch):
    def overpass_falha(sessao, consulta):
        raise OverpassIndisponivel("todos os mirrors falharam")

    feature_google = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-46.60, -23.48], [-46.59, -23.48]],
        },
        "properties": {
            "id": "rua-cruz-de-malta-google-directions",
            "nome": "Rua Cruz de Malta",
            "tipo": "rua",
            "municipio": "São Paulo",
            "origem": "google-directions",
        },
    }

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", overpass_falha)
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_nominatim",
        lambda *args, **kwargs: (_ for _ in ()).throw(ErroExterno("Nominatim bloqueado")),
    )
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_google_rota",
        lambda *args, **kwargs: [feature_google],
    )

    barreiras = buscar_barreiras_rua("Rua Cruz de Malta")
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"
