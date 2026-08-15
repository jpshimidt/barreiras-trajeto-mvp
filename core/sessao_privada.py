"""Limpeza de dados pessoais na sessão Streamlit (server-side)."""

from __future__ import annotations

_PREFIXOS_ENDERECO = ("casa_", "escola_")
_CHAVES_RESULTADO = ("resultado_salvo", "escolheu_escola")


def limpar_dados_pessoais_sessao() -> None:
    """Remove endereços e resultados da memória da sessão no servidor."""
    import streamlit as st

    for chave in list(st.session_state.keys()):
        if any(chave.startswith(p) for p in _PREFIXOS_ENDERECO):
            del st.session_state[chave]
        if chave in _CHAVES_RESULTADO:
            del st.session_state[chave]
