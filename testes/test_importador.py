"""
Testes do importador de barreiras. Nenhum chama o Overpass: a resposta é montada
à mão, no mesmo formato que `out geom;` devolve.
"""

from __future__ import annotations

import pytest

from core.barreiras import carregar_barreiras
from scripts.importar_barreiras import (
    area_id,
    contar_por_rua,
    feature_de_way,
    montar_consulta,
    overpass_para_geojson,
    ruas_sem_resultado,
    slug,
)


def way(id_: int, nome: str, highway: str = "trunk", coords=((-46.63, -23.51), (-46.62, -23.51))):
    return {
        "type": "way",
        "id": id_,
        "tags": {"name": nome, "highway": highway},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in coords],
    }


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


def test_area_sai_do_id_da_relacao():
    assert area_id(298285) == 3600298285


def test_consulta_filtra_por_highway_e_pede_geometria():
    """
    Sem ["highway"] a consulta casa trilhos, cursos d'água e limites administrativos.
    Sem `out geom` seria preciso uma segunda consulta para resolver os nós.
    """
    consulta = montar_consulta(["Avenida Inajar de Souza"], 298285)

    assert '["highway"]' in consulta
    assert '["name"="Avenida Inajar de Souza"]' in consulta
    assert "out geom;" in consulta


def test_consulta_usa_id_da_area_nao_o_nome():
    """area["name"="São Paulo"] pegaria o estado ou várias áreas ao mesmo tempo."""
    consulta = montar_consulta(["Marginal Tietê"], 298285)

    assert "area(3600298285)->.sp;" in consulta
    assert 'area["name"' not in consulta


def test_uma_linha_por_rua():
    consulta = montar_consulta(["Rua A", "Rua B", "Rua C"], 1)

    assert consulta.count("way(area.sp)") == 3


def test_modo_regex_ignora_acento_e_caixa():
    consulta = montar_consulta(["Tietê"], 298285, regex=True)

    assert '["name"~"Tietê",i]' in consulta


def test_aspas_no_nome_sao_escapadas():
    """Nome com aspas quebraria a sintaxe da consulta."""
    assert '\\"' in montar_consulta(['Rua "Apelido"'], 1)


# --------------------------------------------------------------------------- #
# Conversão para GeoJSON
# --------------------------------------------------------------------------- #


def test_way_vira_linestring_em_lon_lat():
    """O Overpass devolve {lat, lon}; o GeoJSON exige [lon, lat] nessa ordem."""
    feature = feature_de_way(way(123, "Marginal Tietê"), "2026-08-15")

    assert feature["geometry"]["type"] == "LineString"
    assert feature["geometry"]["coordinates"] == [[-46.63, -23.51], [-46.62, -23.51]]


def test_propriedades_de_auditoria_sao_preenchidas():
    """Seis meses depois é preciso saber qual cadastro valia quando se decidiu."""
    props = feature_de_way(way(123, "Marginal Tietê"), "2026-08-15")["properties"]

    assert props["nome"] == "Marginal Tietê"
    assert props["osm_way_id"] == 123
    assert props["origem"] == "overpass"
    assert props["importado_em"] == "2026-08-15"
    assert props["municipio"] == "São Paulo"


def test_id_junta_slug_e_way_id():
    """Ways diferentes da mesma avenida não podem colidir de id."""
    a = feature_de_way(way(1, "Avenida Inajar de Souza"), "2026-08-15")["properties"]["id"]
    b = feature_de_way(way(2, "Avenida Inajar de Souza"), "2026-08-15")["properties"]["id"]

    assert (a, b) == ("avenida-inajar-de-souza-1", "avenida-inajar-de-souza-2")


@pytest.mark.parametrize(
    "highway, tipo",
    [("motorway", "rodovia"), ("trunk", "via expressa"), ("primary", "avenida"), ("residential", "rua")],
)
def test_highway_vira_rotulo_legivel(highway, tipo):
    assert feature_de_way(way(1, "X", highway), "2026-08-15")["properties"]["tipo"] == tipo


def test_highway_desconhecido_mantem_o_valor_do_osm():
    assert feature_de_way(way(1, "X", "living_street"), "2026-08-15")["properties"]["tipo"] == "living_street"


def test_way_com_um_ponto_so_e_descartado():
    assert feature_de_way(way(1, "X", coords=((-46.63, -23.51),)), "2026-08-15") is None


def test_elementos_que_nao_sao_way_sao_ignorados():
    resposta = {"elements": [{"type": "node", "id": 9, "lat": -23.5, "lon": -46.6}, way(1, "X")]}

    assert len(overpass_para_geojson(resposta, "2026-08-15")["features"]) == 1


def test_slug_tira_acento_e_pontuacao():
    assert slug("Avenida Engenheiro Caetano Álvares") == "avenida-engenheiro-caetano-alvares"


# --------------------------------------------------------------------------- #
# Relatório de validação
# --------------------------------------------------------------------------- #


def test_conta_ways_por_rua():
    """Uma avenida vem fragmentada em dezenas de ways; isso é esperado."""
    resposta = {
        "elements": [way(1, "Marginal Tietê"), way(2, "Marginal Tietê"), way(3, "Avenida Santos Dumont")]
    }
    contagem = contar_por_rua(overpass_para_geojson(resposta, "2026-08-15"))

    assert contagem == {"Marginal Tietê": 2, "Avenida Santos Dumont": 1}


def test_rua_pedida_que_nao_voltou_e_denunciada():
    """
    O falso negativo mais perigoso do projeto: barreira que não entrou no cadastro
    vira 'sem direito' errado, em silêncio.
    """
    geojson = overpass_para_geojson({"elements": [way(1, "Marginal Tietê")]}, "2026-08-15")

    assert ruas_sem_resultado(["Marginal Tietê", "Avenida Fantasma"], geojson) == ["Avenida Fantasma"]


def test_nome_pedido_por_regex_casa_com_nome_completo():
    """Pedindo 'Tietê' com --regex, o OSM devolve 'Marginal Tietê' — não é falta."""
    geojson = overpass_para_geojson({"elements": [way(1, "Marginal Tietê")]}, "2026-08-15")

    assert ruas_sem_resultado(["Tietê"], geojson) == []


# --------------------------------------------------------------------------- #
# O que sai daqui tem de entrar no app
# --------------------------------------------------------------------------- #


def test_geojson_gerado_e_lido_pelo_core(tmp_path):
    """Contrato entre o importador e `core.barreiras` — os dois lados do arquivo."""
    import json

    resposta = {"elements": [way(1, "Marginal Tietê"), way(2, "Avenida Inajar de Souza", "primary")]}
    caminho = tmp_path / "barreiras.geojson"
    caminho.write_text(
        json.dumps(overpass_para_geojson(resposta, "2026-08-15"), ensure_ascii=False), encoding="utf-8"
    )

    barreiras = carregar_barreiras(caminho)

    assert {b.nome for b in barreiras} == {"Marginal Tietê", "Avenida Inajar de Souza"}
    assert {b.tipo for b in barreiras} == {"via expressa", "avenida"}
