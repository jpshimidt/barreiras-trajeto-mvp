"""Testes do cache de barreiras."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.barreiras_geojson import geojson_de_barreiras
from core.barreiras_store import ArquivoBarreirasStore
from core.erros import ErroExterno
from testes.test_barreiras_store import barreira_exemplo


def test_store_vazio_lista_zero(tmp_path):
    store = ArquivoBarreirasStore(tmp_path / "vazio.geojson")
    assert store.listar() == []


def test_barreiras_de_geojson_rejeita_vazio():
    from core.barreiras_geojson import barreiras_de_geojson

    with pytest.raises(ErroExterno):
        barreiras_de_geojson({"type": "FeatureCollection", "features": []})


def test_arquivo_valido_carrega(tmp_path):
    caminho = tmp_path / "ok.geojson"
    caminho.write_text(json.dumps(geojson_de_barreiras([barreira_exemplo()])), encoding="utf-8")
    store = ArquivoBarreirasStore(caminho)
    assert len(store.listar()) == 1
