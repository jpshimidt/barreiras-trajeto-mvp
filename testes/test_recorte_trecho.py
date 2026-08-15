"""Testes de recorte de barreira por faixa de número."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString

from core.recorte_trecho import (
    MarcaNumero,
    RegistroTrecho,
    fracao_por_numero,
    parse_linha_trecho,
    recortar_linha_por_numeros,
    rotulo_trecho,
)


def test_parse_linha_rua_inteira():
    trecho = parse_linha_trecho("Marginal Tietê")
    assert trecho == RegistroTrecho("Marginal Tietê")
    assert not trecho.tem_faixa()


def test_parse_linha_com_faixa_e_paridade():
    trecho = parse_linha_trecho("Av. Inajar;100;500;par")
    assert trecho.nome == "Av. Inajar"
    assert trecho.numero_inicio == 100
    assert trecho.numero_fim == 500
    assert trecho.paridade == "par"


def test_recorte_entre_dois_numeros():
    linha = LineString([(0, 0), (10, 0)])
    marcas = [MarcaNumero(100, 0.0), MarcaNumero(200, 0.5), MarcaNumero(300, 1.0)]
    recortada = recortar_linha_por_numeros(linha, marcas, 150, 250)
    assert recortada is not None
    assert recortada.length == pytest.approx(5.0, rel=0.01)


def test_recorte_sem_marcas_retorna_none():
    linha = LineString([(0, 0), (10, 0)])
    assert recortar_linha_por_numeros(linha, [], 100, 200) is None


def test_rotulo_trecho_com_faixa():
    assert rotulo_trecho("Av. X", 100, 500) == "Av. X (nº 100–500)"


def test_fracao_por_numero_interpola():
    marcas = [MarcaNumero(100, 0.0), MarcaNumero(200, 1.0)]
    assert fracao_por_numero(marcas, 150) == pytest.approx(0.5)
