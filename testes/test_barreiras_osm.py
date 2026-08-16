"""Testes de busca OSM para cadastro de barreiras."""

from __future__ import annotations

import pytest
import requests

from core.barreiras_osm import (
    OVERPASS_ENDPOINTS,
    OverpassIndisponivel,
    aplicar_metadados,
    barreira_de_cliques,
    buscar_barreira_entre_links,
    buscar_barreira_entre_pontos,
    buscar_barreiras_rua,
    clique_distinto,
    colar_clique_na_via,
    comprimento_m,
    consultar_overpass,
    buscar_features_google_rota,
    coords_eixo_entre_pinos,
    extremos_latlon,
    extremos_preview,
    feature_de_way,
    fundir_coords,
    nome_via_de_entrada,
    nucleo_nome_via,
    overpass_para_geojson,
    recortar_linha_entre_pinos,
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
    assert nome_via_de_entrada(texto) == "Rua Borges"


def test_nome_via_sem_numero_estilo_maps():
    texto = "R. Cruz de Malta - Parada Inglesa, São Paulo - SP, Brasil"
    assert nome_via_de_entrada(texto) == "Rua Cruz de Malta"


def test_nome_via_de_link_maps_completo():
    url = (
        "https://www.google.com/maps/place/R.+Cruz+de+Malta+-+Parada+Inglesa,"
        "+S%C3%A3o+Paulo+-+SP/@-23.478,-46.608,17z"
    )
    assert nome_via_de_entrada(url) == "Rua Cruz de Malta"


def test_nome_via_mantem_texto_simples():
    assert nome_via_de_entrada("Marginal Tietê") == "Marginal Tietê"


def test_buscar_barreiras_rua_sem_rede(monkeypatch):
    resposta = {"elements": [way(1, "Marginal Tietê")]}

    def falso_overpass(sessao, consulta):
        return resposta

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", falso_overpass)
    monkeypatch.setattr("core.barreiras_osm.buscar_features_google_rota", lambda *a, **k: [])

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
    monkeypatch.setattr("core.barreiras_osm.buscar_features_google_rota", lambda *a, **k: [])

    barreiras = buscar_barreiras_rua("Marginal Tietê")
    assert chamadas == [False, True]
    assert len(barreiras) == 1
    assert "Tietê" in barreiras[0].nome


def test_buscar_barreiras_falha_clara(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.consultar_overpass",
        lambda sessao, consulta: {"elements": []},
    )
    monkeypatch.setattr("core.barreiras_osm.buscar_features_google_rota", lambda *a, **k: [])
    monkeypatch.setattr("core.barreiras_osm.buscar_features_nominatim", lambda *a, **k: [])
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
    monkeypatch.setattr("core.barreiras_osm.buscar_features_google_rota", lambda *a, **k: [])
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_nominatim",
        lambda sessao, nome, trecho=None: [feature_nominatim],
    )

    barreiras = buscar_barreiras_rua("Rua Cruz de Malta")
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"


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
            "id": "rua-cruz-de-malta-osm-eixo",
            "nome": "Rua Cruz de Malta",
            "tipo": "rua",
            "municipio": "São Paulo",
            "origem": "osm-eixo",
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


def test_buscar_barreiras_google_primeiro(monkeypatch):
    feature_google = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-46.60, -23.48], [-46.59, -23.48]],
        },
        "properties": {
            "id": "rua-cruz-de-malta-osm-eixo",
            "nome": "Rua Cruz de Malta",
            "tipo": "avenida",
            "municipio": "São Paulo",
            "origem": "osm-eixo",
        },
    }
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_google_rota",
        lambda *a, **k: [feature_google],
    )

    def overpass_nao_deve_ser_chamado(*args, **kwargs):
        raise AssertionError("Overpass não deveria ser consultado se o Google achou a via")

    monkeypatch.setattr("core.barreiras_osm.consultar_overpass", overpass_nao_deve_ser_chamado)

    barreiras = buscar_barreiras_rua(
        "R. Cruz de Malta - Parada Inglesa, São Paulo - SP, Brasil",
        tipo="avenida",
    )
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"
    assert barreiras[0].tipo == "avenida"


def test_buscar_barreiras_aplica_faixa_e_paridade(monkeypatch):
    feature_google = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-46.60, -23.48], [-46.59, -23.48]],
        },
        "properties": {
            "id": "rua-cruz-de-malta-osm-eixo",
            "nome": "Rua Cruz de Malta",
            "tipo": "rua",
            "municipio": "São Paulo",
            "origem": "osm-eixo",
        },
    }
    monkeypatch.setattr(
        "core.barreiras_osm.buscar_features_google_rota",
        lambda *a, **k: [feature_google],
    )
    barreiras = buscar_barreiras_rua(
        "https://www.google.com/maps/place/R.+Cruz+de+Malta+-+Parada+Inglesa,"
        "+S%C3%A3o+Paulo+-+SP/@-23.478,-46.608,17z",
        numero_inicio=100,
        numero_fim=800,
        paridade="impar",
        tipo="rua",
    )
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"
    assert barreiras[0].numero_inicio == 100
    assert barreiras[0].numero_fim == 800
    assert barreiras[0].paridade == "impar"


def test_buscar_barreira_entre_pontos(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.coords_eixo_entre_pinos",
        lambda nome, origem, destino, api_key=None: (
            [(-46.60, -23.48), (-46.59, -23.48)],
            "osm-eixo",
        ),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")
    barreiras = buscar_barreira_entre_pontos(
        "R. Cruz de Malta",
        (-23.48, -46.60),
        (-23.48, -46.59),
        tipo="rua",
    )
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"


def test_buscar_barreira_entre_links(monkeypatch):
    monkeypatch.setattr(
        "core.google_geo.pin_de_link_maps",
        lambda url, sessao=None: (
            (-23.480, -46.610) if "ini" in url else (-23.476, -46.606)
        ),
    )
    monkeypatch.setattr(
        "core.barreiras_osm.coords_eixo_entre_pinos",
        lambda nome, origem, destino, api_key=None: (
            [(-46.610, -23.480), (-46.606, -23.476)],
            "osm-eixo",
        ),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")
    barreiras = buscar_barreira_entre_links(
        "Rua Cruz de Malta",
        "https://maps.google.com/ini",
        "https://maps.google.com/fim",
        tipo="rua",
        numero_inicio=1,
        numero_fim=400,
        paridade="ambos",
    )
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"
    assert barreiras[0].numero_inicio == 1
    assert barreiras[0].numero_fim == 400


def test_aplicar_metadados_e_comprimento():
    from shapely.geometry import LineString

    from core.barreiras import Barreira

    barreira = Barreira(
        id="x",
        nome="R. Cruz de Malta",
        tipo="avenida",
        geometria=LineString([(-46.60, -23.48), (-46.599, -23.48)]),
    )
    aplicar_metadados(
        [barreira],
        nome="Rua Cruz de Malta",
        tipo="rua",
        numero_inicio=10,
        numero_fim=200,
        paridade="ambos",
    )
    assert barreira.nome == "Rua Cruz de Malta"
    assert barreira.tipo == "rua"
    assert barreira.numero_inicio == 10
    assert barreira.paridade is None
    assert comprimento_m(barreira) > 50


def test_nucleo_nome_via():
    assert nucleo_nome_via("Rua Cruz de Malta") == "Cruz de Malta"
    assert nucleo_nome_via("R. Cruz de Malta") == "Cruz de Malta"


def test_recortar_linha_entre_pinos():
    from shapely.geometry import LineString

    linha = LineString([(-46.6015, -23.4812), (-46.6005, -23.4860), (-46.5992, -23.4916)])
    recorte = recortar_linha_entre_pinos(linha, (-23.4812, -46.6015), (-23.4916, -46.5992))
    assert recorte is not None
    assert recorte.length > 0


def test_buscar_features_google_rota_usa_eixo_a_pe(monkeypatch):
    """Cadastro traça o eixo da via — nunca Google Directions de carro."""
    chamado = {"eixo": False}

    def fake_eixo(nome, origem, destino, api_key=None):
        chamado["eixo"] = True
        return [(-46.60, -23.48), (-46.59, -23.48)], "osm-eixo"

    monkeypatch.setattr("core.barreiras_osm.coords_eixo_entre_pinos", fake_eixo)
    monkeypatch.setattr(
        "core.barreiras_osm._pontos_google_para_rota",
        lambda *a, **k: ((-23.48, -46.60), (-23.48, -46.59)),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")

    features = buscar_features_google_rota("Rua Cruz de Malta")
    assert chamado["eixo"]
    assert len(features) == 1
    assert features[0]["properties"]["origem"] == "osm-eixo"


def test_coords_eixo_cai_na_reta_se_osm_e_roads_falham(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.eixo_osm_entre_pinos",
        lambda *a, **k: (_ for _ in ()).throw(OverpassIndisponivel("off")),
    )
    monkeypatch.setattr("core.barreiras_osm.eixo_snap_roads", lambda *a, **k: [])
    coords, origem = coords_eixo_entre_pinos(
        "Rua Cruz de Malta", (-23.481, -46.601), (-23.491, -46.599), api_key="x"
    )
    assert origem == "eixo-reto"
    assert coords[0] == (-46.601, -23.481)
    assert coords[-1] == (-46.599, -23.491)


def test_filtrar_barreiras_perto_descarta_homonima():
    from shapely.geometry import LineString

    from core.barreiras import Barreira
    from core.barreiras_osm import filtrar_barreiras_perto, refinar_preview

    tucuruvi = Barreira(
        id="sp",
        nome="Rua Cruz de Malta",
        tipo="rua",
        geometria=LineString([(-46.608, -23.478), (-46.607, -23.477)]),
    )
    guarulhos = Barreira(
        id="gru",
        nome="Rua Cruz de Malta",
        tipo="rua",
        geometria=LineString([(-46.48, -23.44), (-46.479, -23.439)]),
    )
    perto = filtrar_barreiras_perto([tucuruvi, guarulhos], -23.478, -46.608, raio_m=2500)
    assert [b.id for b in perto] == ["sp"]

    filtradas, removidos = refinar_preview(
        [tucuruvi, guarulhos], ancora=(-23.478, -46.608)
    )
    assert [b.id for b in filtradas] == ["sp"]
    assert removidos == 1


def test_extremos_latlon_e_preview():
    from shapely.geometry import LineString, MultiLineString

    from core.barreiras import Barreira

    linha = LineString([(-46.61, -23.48), (-46.60, -23.47)])
    assert extremos_latlon(linha) == ((-23.48, -46.61), (-23.47, -46.60))

    multi = MultiLineString(
        [
            LineString([(-46.61, -23.48), (-46.605, -23.475)]),
            LineString([(-46.605, -23.475), (-46.60, -23.47)]),
        ]
    )
    assert extremos_latlon(multi) == ((-23.48, -46.61), (-23.47, -46.60))

    a = Barreira(id="a", nome="Rua X", tipo="rua", geometria=linha)
    b = Barreira(
        id="b",
        nome="Rua X",
        tipo="rua",
        geometria=LineString([(-46.60, -23.47), (-46.59, -23.46)]),
    )
    assert extremos_preview([a, b]) == ((-23.48, -46.61), (-23.46, -46.59))


def test_clique_distinto_ignora_rerun_do_mesmo_ponto():
    evento = {"lat": -23.48, "lng": -46.61}
    primeiro = clique_distinto(None, evento)
    assert primeiro == (-23.48, -46.61)
    assert clique_distinto(primeiro, evento) is None
    assert clique_distinto(primeiro, {"lat": -23.49, "lon": -46.60}) == (-23.49, -46.60)
    assert clique_distinto(None, {}) is None


def test_fundir_coords_nao_repete_emenda():
    a = [(-46.61, -23.48), (-46.605, -23.475)]
    b = [(-46.605, -23.475), (-46.60, -23.47)]
    assert fundir_coords([a, b]) == [
        (-46.61, -23.48),
        (-46.605, -23.475),
        (-46.60, -23.47),
    ]


def test_barreira_de_cliques_dois_pontos(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.coords_eixo_entre_pinos",
        lambda nome, origem, destino, api_key=None: (
            [(origem[1], origem[0]), (destino[1], destino[0])],
            "osm-eixo",
        ),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")
    barreiras = barreira_de_cliques(
        "R. Cruz de Malta",
        [(-23.480, -46.610), (-23.476, -46.606)],
        tipo="rua",
    )
    assert len(barreiras) == 1
    assert barreiras[0].nome == "Rua Cruz de Malta"
    assert list(barreiras[0].geometria.coords)[0] == (-46.610, -23.480)


def test_barreira_de_cliques_tres_pontos_concatena(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.coords_eixo_entre_pinos",
        lambda nome, origem, destino, api_key=None: (
            [(origem[1], origem[0]), (destino[1], destino[0])],
            "osm-eixo",
        ),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")
    barreiras = barreira_de_cliques(
        "Rua Cruz de Malta",
        [(-23.480, -46.610), (-23.478, -46.608), (-23.476, -46.606)],
    )
    coords = list(barreiras[0].geometria.coords)
    assert coords == [
        (-46.610, -23.480),
        (-46.608, -23.478),
        (-46.606, -23.476),
    ]


def test_barreira_de_cliques_cai_na_polilinha_se_eixo_falha(monkeypatch):
    monkeypatch.setattr(
        "core.barreiras_osm.coords_eixo_entre_pinos",
        lambda *a, **k: ([], "vazio"),
    )
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: None)
    barreiras = barreira_de_cliques(
        "Rua Cruz de Malta",
        [(-23.480, -46.610), (-23.476, -46.606)],
    )
    assert list(barreiras[0].geometria.coords) == [
        (-46.610, -23.480),
        (-46.606, -23.476),
    ]


def test_barreira_de_cliques_exige_dois_pontos():
    with pytest.raises(ErroExterno, match="início e o fim"):
        barreira_de_cliques("Rua Cruz de Malta", [(-23.48, -46.61)])


def test_colar_clique_na_via_gruda_se_perto(monkeypatch):
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")

    class Resp:
        status_code = 200

        def json(self):
            return {
                "snappedPoints": [
                    {"location": {"latitude": -23.4801, "longitude": -46.6101}}
                ]
            }

    monkeypatch.setattr("core.barreiras_osm.requests.get", lambda *a, **k: Resp())
    assert colar_clique_na_via(-23.4800, -46.6100) == (-23.4801, -46.6101)


def test_colar_clique_na_via_ignora_asfalto_longe(monkeypatch):
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: "fake")

    class Resp:
        status_code = 200

        def json(self):
            return {
                "snappedPoints": [
                    {"location": {"latitude": -23.50, "longitude": -46.65}}
                ]
            }

    monkeypatch.setattr("core.barreiras_osm.requests.get", lambda *a, **k: Resp())
    assert colar_clique_na_via(-23.4800, -46.6100) == (-23.4800, -46.6100)


def test_colar_clique_na_via_sem_chave_devolve_clique(monkeypatch):
    monkeypatch.setattr("core.google_geo.ler_google_api_key", lambda: None)
    assert colar_clique_na_via(-23.48, -46.61) == (-23.48, -46.61)
