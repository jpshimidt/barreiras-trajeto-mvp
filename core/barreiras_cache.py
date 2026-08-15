"""Cache compartilhado do cadastro de barreiras (consulta + admin)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.barreiras import Barreira
from core.barreiras_store import BarreirasStore, descricao_store, obter_store
from core.erros import ErroExterno
from core.seguranca import em_ambiente_streamlit_cloud

ARQUIVO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"


@st.cache_resource(show_spinner=False)
def store_barreiras(caminho: str | Path | None = None) -> BarreirasStore:
    destino = Path(caminho) if caminho else ARQUIVO_PADRAO
    return obter_store(destino)


@st.cache_resource(show_spinner="Carregando o cadastro de barreiras...")
def barreiras_carregadas(caminho: str | Path | None = None) -> list[Barreira]:
    destino = Path(caminho) if caminho else ARQUIVO_PADRAO
    store = store_barreiras(destino)
    barreiras = store.listar()
    if not barreiras:
        if em_ambiente_streamlit_cloud():
            raise ErroExterno(
                "Cadastro de barreiras vazio ou indisponível. "
                "Configure `[github_barreiras]` nos Secrets do Streamlit Cloud."
            )
        raise ErroExterno(
            f"Nenhuma barreira em {destino}. "
            "Rode o importador ou use a página de cadastro."
        )
    return barreiras


def descricao_cadastro(caminho: str | Path | None = None) -> str:
    return descricao_store(store_barreiras(caminho))


def invalidar_cache_barreiras() -> None:
    barreiras_carregadas.clear()
    store_barreiras.clear()
