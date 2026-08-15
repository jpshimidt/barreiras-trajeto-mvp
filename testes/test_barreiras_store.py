"""Testes de persistência do cadastro de barreiras."""

from __future__ import annotations

import json

import pytest
from shapely.geometry import LineString

from core.barreiras import Barreira
from core.barreiras_geojson import (
    barreiras_de_geojson,
    geojson_de_barreiras,
    geometria_de_coords_json,
)
from core.barreiras_store import ArquivoBarreirasStore
from core.erros import ErroExterno

LINHA = LineString([(-46.63, -23.51), (-46.62, -23.51)])


def barreira_exemplo(**kwargs) -> Barreira:
    base = dict(
        id="teste-1",
        nome="Marginal Tietê",
        tipo="via expressa",
        geometria=LINHA,
    )
    base.update(kwargs)
    return Barreira(**base)


def test_roundtrip_geojson():
    original = [barreira_exemplo(numero_inicio=100, numero_fim=500, paridade="par")]
    colecao = geojson_de_barreiras(original)
    restauradas = barreiras_de_geojson(colecao)
    assert len(restauradas) == 1
    assert restauradas[0].nome == "Marginal Tietê"
    assert restauradas[0].numero_inicio == 100
    assert restauradas[0].numero_fim == 500
    assert restauradas[0].paridade == "par"


def test_geometria_de_lista_coords():
    geom = geometria_de_coords_json("[[-46.63, -23.51], [-46.62, -23.51]]")
    assert list(geom.coords) == [(-46.63, -23.51), (-46.62, -23.51)]


def test_arquivo_store_crud(tmp_path):
    caminho = tmp_path / "barreiras.geojson"
    store = ArquivoBarreirasStore(caminho)
    b1 = barreira_exemplo()
    b2 = barreira_exemplo(id="teste-2", nome="Av. Paulista")
    store.criar(b1)
    store.criar(b2)
    assert len(store.listar()) == 2

    b1_atual = barreira_exemplo(nome="Marginal Tietê (trecho sul)")
    store.atualizar(b1_atual)
    assert store.obter("teste-1").nome == "Marginal Tietê (trecho sul)"

    store.remover(b1.id)
    assert len(store.listar()) == 1
    assert store.obter("teste-2") is not None


def test_nao_remove_ultima_barreira(tmp_path):
    caminho = tmp_path / "barreiras.geojson"
    store = ArquivoBarreirasStore(caminho)
    store.criar(barreira_exemplo())
    with pytest.raises(ErroExterno):
        store.remover("teste-1")


def test_grava_json_legivel(tmp_path):
    caminho = tmp_path / "barreiras.geojson"
    store = ArquivoBarreirasStore(caminho)
    store.criar(barreira_exemplo())
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["type"] == "FeatureCollection"
    assert dados["features"][0]["properties"]["nome"] == "Marginal Tietê"
