"""Testes de limites geográficos e geometria."""

from __future__ import annotations

import pytest

from core.barreiras_geojson import geometria_de_coords_json
from core.erros import ErroExterno
from core.geo_limites import coordenada_em_sao_paulo, exigir_coordenada_em_sao_paulo


def test_coordenada_dentro_de_sp():
    assert coordenada_em_sao_paulo(-23.55, -46.63) is True


def test_coordenada_fora_de_sp():
    assert coordenada_em_sao_paulo(-22.9, -43.2) is False


def test_exigir_coordenada_fora_de_sp_estoura():
    with pytest.raises(ErroExterno):
        exigir_coordenada_em_sao_paulo(-22.9, -43.2)


def test_geometria_rejeita_fora_de_sp():
    with pytest.raises(ErroExterno):
        geometria_de_coords_json("[[-43.2, -22.9], [-43.1, -22.8]]")


def test_geometria_aceita_linestring_em_sp():
    geom = geometria_de_coords_json("[[-46.63, -23.51], [-46.62, -23.51]]")
    assert len(geom.coords) == 2
