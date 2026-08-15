"""Limites de uso por sessão — protege cotas de APIs pagas."""

from __future__ import annotations

import time

from core.erros import ErroExterno

# Limites conservadores para MVP (~dezenas de consultas/dia esperadas).
MAX_CALCULOS_POR_HORA = 30
MAX_GEOCODIFICACOES_POR_HORA = 60
MAX_TENTATIVAS_LOGIN_POR_HORA = 20
MAX_BUSCAS_BARREIRA_OSM_POR_HORA = 15
JANELA_S = 3600


def _historico(chave: str) -> list[float]:
    import streamlit as st

    campo = f"_rate_{chave}"
    return st.session_state.setdefault(campo, [])


def _registrar(chave: str) -> None:
    agora = time.time()
    hist = _historico(chave)
    hist[:] = [t for t in hist if agora - t < JANELA_S]
    hist.append(agora)


def verificar_limite(chave: str, maximo: int, *, rotulo: str) -> None:
    agora = time.time()
    hist = _historico(chave)
    hist[:] = [t for t in hist if agora - t < JANELA_S]
    if len(hist) >= maximo:
        raise ErroExterno(
            f"Limite de {maximo} {rotulo} por hora nesta sessão. "
            "Aguarde um pouco ou fale com o administrador."
        )


def consumir_calculo() -> None:
    verificar_limite("calcular", MAX_CALCULOS_POR_HORA, rotulo="cálculos")
    _registrar("calcular")


def consumir_geocodificacao() -> None:
    verificar_limite("geocode", MAX_GEOCODIFICACOES_POR_HORA, rotulo="buscas de endereço")
    _registrar("geocode")


def registrar_tentativa_login_falha() -> None:
    verificar_limite("login_fail", MAX_TENTATIVAS_LOGIN_POR_HORA, rotulo="tentativas de login")
    _registrar("login_fail")


def consumir_busca_barreira_osm() -> None:
    verificar_limite("osm_barreira", MAX_BUSCAS_BARREIRA_OSM_POR_HORA, rotulo="buscas de rua no mapa")
    _registrar("osm_barreira")
