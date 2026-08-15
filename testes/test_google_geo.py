"""Testes do geocodificador Google (sem rede)."""

from __future__ import annotations

from core.endereco_maps import Local, parse_endereco_maps
from core.google_geo import (
    PlacesApiNovaIndisponivel,
    buscar_sugestoes_endereco,
    extrair_coordenadas_maps_url,
    local_de_selecao_widget,
)


def test_extrair_coordenadas_de_link_maps():
    url = "https://www.google.com/maps/place/Test/@-23.484082,-46.600658,17z/data=!3d-23.484082!4d-46.600658"
    coords = extrair_coordenadas_maps_url(url)
    assert coords is not None
    lat, lon = coords
    assert round(lat, 6) == -23.484082
    assert round(lon, 6) == -46.600658


def test_local_de_widget_confirma_numero():
    endereco = parse_endereco_maps("R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000")
    local = local_de_selecao_widget(
        {
            "formatted_address": "R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000",
            "lat": -23.484,
            "lon": -46.600,
            "street": "R. Borges",
            "number": "353",
        },
        endereco.texto,
    )
    assert local.numero_informado == "353"
    assert local.numero_confirmado is True
    assert local.adequacao == 100


def test_local_de_widget_sem_numero_google_nao_confirma():
    local = local_de_selecao_widget(
        {
            "formatted_address": "R. Borges - Parada Inglesa, São Paulo - SP",
            "lat": -23.484,
            "lon": -46.600,
            "street": "R. Borges",
            "number": "",
        },
        "R. Borges, 353 - Parada Inglesa, São Paulo - SP, 02247-000",
    )
    assert local.numero_informado == "353"
    assert local.numero_confirmado is False
    assert local.adequacao == 75


def test_buscar_sugestoes_cai_para_geocoding_quando_places_nova_indisponivel(monkeypatch):
    local_legacy = Local(
        "consulta",
        "R. Borges, 353 - Parada Inglesa, São Paulo - SP",
        -23.484,
        -46.600,
        1.0,
        adequacao=100,
    )

    def autocomplete_falha(*args, **kwargs):
        raise PlacesApiNovaIndisponivel("403 disabled")

    monkeypatch.setattr("core.google_geo.autocomplete_sugestoes", autocomplete_falha)
    monkeypatch.setattr(
        "core.google_geo._geocode_legacy",
        lambda texto, api_key, endereco: [local_legacy],
    )

    sugestoes = buscar_sugestoes_endereco("R. Borges, 353", "chave-teste")

    assert len(sugestoes) == 1
    assert sugestoes[0]["local"] is local_legacy
    assert sugestoes[0]["place_id"] is None
    assert "Borges" in sugestoes[0]["texto"]
