"""
Testes da interface, via AppTest do Streamlit. Sem navegador e sem rede: a
geocodificação e o roteamento são substituídos por dublês.

`app.py` é re-executado a cada `run()`, e faz `from core.geocode import geocodificar`
no topo — então trocar o atributo no MÓDULO alcança o que a página usa.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString
from streamlit.testing.v1 import AppTest

import core.geocode
import core.routing
from core.geocode import EXEMPLO_ENDERECO_MAPS, Local
from core.routing import Rota

APP = str(Path(__file__).resolve().parent.parent / "app.py")

# Santana -> Bom Retiro: atravessa a Marginal Tietê do cadastro à mão.
CASA = Local("casa", "R. Voluntários da Pátria, 1000 — Santana", -23.5100, -46.6280, 0.9, adequacao=100)
ESCOLA = Local("escola", "Av. Rudge, 700 — Bom Retiro", -23.5265, -46.6440, 0.9, adequacao=100)

# Santana -> Santana: não encosta em barreira nenhuma.
ESCOLA_PERTO = Local("escola", "R. Alfredo Pujol, 500 — Santana", -23.4995, -46.6260, 0.9, adequacao=100)


def rota_entre(a: Local, b: Local) -> Rota:
    return Rota(LineString([(a.lon, a.lat), (b.lon, b.lat)]), 2451.0, 1800.0)


@pytest.fixture
def app(monkeypatch):
    """Página com chave de brinquedo e serviços externos dublados."""
    monkeypatch.setenv("ORS_API_KEY", "chave-de-teste")

    def geocode_falso(texto, api_key, cep=None):
        if "voluntários" in texto.lower():
            return [CASA]
        return [ESCOLA]

    monkeypatch.setattr(core.geocode, "geocodificar", geocode_falso)
    monkeypatch.setattr(core.routing, "rota_a_pe", lambda o, d, k: rota_entre(o, d))
    return AppTest.from_file(APP, default_timeout=30)


def preencher(at: AppTest) -> AppTest:
    at.text_input[0].set_value(EXEMPLO_ENDERECO_MAPS)
    at.text_input[1].set_value("Av. Rudge, 700 - Bom Retiro, São Paulo - SP, 01133-000")
    return at.run()


def texto_da_pagina(at: AppTest) -> str:
    return " ".join(
        [*(m.value for m in at.markdown), *(s.value for s in at.success), *(e.value for e in at.error)]
    )


# --------------------------------------------------------------------------- #


def test_pagina_sobe_sem_excecao(app):
    at = app.run()

    assert not at.exception
    assert at.title[0].value.endswith("Elegibilidade a transporte escolar")


def test_cadastro_de_barreiras_aparece_na_lateral(app):
    at = app.run()

    assert at.sidebar.metric[0].value == "3"


def test_calcular_so_habilita_com_os_dois_enderecos(app):
    at = app.run()
    assert at.button[0].disabled is True

    at = preencher(at)
    assert at.button[0].disabled is False


def test_endereco_formatado_volta_para_conferencia(app):
    """A proteção mais eficaz contra erro de geocodificação."""
    at = preencher(app.run())

    assert "R. Voluntários da Pátria, 1000 — Santana" in texto_da_pagina(at)
    assert "Av. Rudge, 700 — Bom Retiro" in texto_da_pagina(at)


def test_rota_que_atravessa_barreira_da_direito(app):
    at = preencher(app.run())
    at.button[0].click()
    at = at.run()

    assert not at.exception
    pagina = texto_da_pagina(at)
    assert "COM DIREITO" in pagina
    assert "Marginal Tietê" in pagina


def test_rota_sem_barreira_nao_da_direito(app, monkeypatch):
    monkeypatch.setattr(core.routing, "rota_a_pe", lambda o, d, k: rota_entre(CASA, ESCOLA_PERTO))
    at = preencher(app.run())
    at.button[0].click()
    at = at.run()

    assert "SEM DIREITO" in texto_da_pagina(at)
    assert "não passa por nenhuma barreira" in texto_da_pagina(at)


def test_flag_da_escola_decide_sem_gastar_chamada_de_rota(app, monkeypatch):
    """
    A responsável escolheu a escola: o resultado já está definido. Chamar o
    roteador seria queimar cota para uma resposta que não muda.
    """

    def nao_deve_ser_chamado(*args, **kwargs):
        raise AssertionError("rota_a_pe foi chamada apesar da flag 'escolheu a escola'")

    monkeypatch.setattr(core.routing, "rota_a_pe", nao_deve_ser_chamado)

    at = preencher(app.run())
    at.checkbox[0].set_value(True)
    at = at.run()
    at.button[0].click()
    at = at.run()

    assert not at.exception
    pagina = texto_da_pagina(at)
    assert "SEM DIREITO" in pagina
    assert "A responsável escolheu esta escola." in pagina


def test_falha_do_ors_nao_vira_sem_direito(app, monkeypatch):
    """Serviço fora do ar é 'não sei responder'. O texto tem de deixar isso claro."""
    from core.erros import ErroExterno

    def cai(*args, **kwargs):
        raise ErroExterno("cota do OpenRouteService estourada (HTTP 429).")

    monkeypatch.setattr(core.routing, "rota_a_pe", cai)

    at = preencher(app.run())
    at.button[0].click()
    at = at.run()

    pagina = texto_da_pagina(at)
    assert "429" in pagina
    assert "**não** significa 'sem direito'" in pagina
    assert "SEM DIREITO" not in pagina
    assert "COM DIREITO" not in pagina


def test_sem_cep_avisa(app):
    at = app.run()
    at.text_input[0].set_value("Rua Borges, 353 - Parada Inglesa, São Paulo - SP")
    at.text_input[1].set_value("R. da Grota, 483 - Vila Gustavo, São Paulo - SP")
    at = at.run()

    assert any("CEP" in w.value for w in at.warning)


def test_candidatos_empatados_viram_escolha_do_usuario(app, monkeypatch):
    """Em SP nome de rua repete entre distritos; a página não pode escolher sozinha."""
    outro = Local("casa", "R. Voluntários da Pátria — Perus", -23.40, -46.75, 0.88, adequacao=95)
    monkeypatch.setattr(core.geocode, "geocodificar", lambda t, k, c=None: [CASA, outro])

    at = preencher(app.run())

    assert at.radio
    assert "Perus" in str(at.radio[0].options)
    assert at.button[0].disabled is True
