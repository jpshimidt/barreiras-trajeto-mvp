"""Testes do geocodificador Google (sem rede)."""

from __future__ import annotations

from core.endereco_maps import Local, parse_endereco_maps
from core.google_geo import (
    PlacesApiNovaIndisponivel,
    buscar_sugestoes_endereco,
    endereco_de_link_maps,
    extrair_coordenadas_maps_url,
    extrair_nome_de_url_maps,
    local_de_selecao_widget,
    parece_link_maps,
)


def test_extrair_coordenadas_de_link_maps():
    url = "https://www.google.com/maps/place/Test/@-23.484082,-46.600658,17z/data=!3d-23.484082!4d-46.600658"
    coords = extrair_coordenadas_maps_url(url)
    assert coords is not None
    lat, lon = coords
    assert round(lat, 6) == -23.484082
    assert round(lon, 6) == -46.600658


def test_parece_link_maps():
    assert parece_link_maps("https://maps.app.goo.gl/abc123")
    assert parece_link_maps(
        "https://www.google.com/maps/place/R.+Cruz+de+Malta/@-23.48,-46.60,17z"
    )
    assert not parece_link_maps("R. Cruz de Malta - Parada Inglesa, São Paulo")


def test_extrair_nome_de_url_place():
    url = (
        "https://www.google.com/maps/place/R.+Cruz+de+Malta+-+Parada+Inglesa,"
        "+S%C3%A3o+Paulo+-+SP/@-23.478,-46.608,17z"
    )
    assert extrair_nome_de_url_maps(url) == "R. Cruz de Malta - Parada Inglesa, São Paulo - SP"


def test_endereco_de_link_maps_sem_rede():
    url = (
        "https://www.google.com/maps/place/R.+Cruz+de+Malta+-+Parada+Inglesa,"
        "+S%C3%A3o+Paulo+-+SP/@-23.478,-46.608,17z"
    )
    assert "Cruz de Malta" in endereco_de_link_maps(url)


def test_pin_de_link_maps_usa_coordenadas_do_url():
    from core.google_geo import pin_de_link_maps

    url = "https://www.google.com/maps/place/R.+Cruz+de+Malta/@-23.478123,-46.608456,17z"
    lat, lon = pin_de_link_maps(url)
    assert round(lat, 6) == -23.478123
    assert round(lon, 6) == -46.608456


def test_endereco_de_link_curto_segue_redirect(monkeypatch):
    class Resp:
        url = (
            "https://www.google.com/maps/place/R.+Cruz+de+Malta+-+Tucuruvi,"
            "+S%C3%A3o+Paulo+-+SP/@-23.478,-46.608,17z"
        )

    class Sessao:
        def get(self, url, **kwargs):
            assert "goo.gl" in url
            return Resp()

    texto = endereco_de_link_maps("https://maps.app.goo.gl/abc123", Sessao())
    assert "Cruz de Malta" in texto


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
