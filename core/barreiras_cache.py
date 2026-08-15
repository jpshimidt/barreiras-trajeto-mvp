"""Cache compartilhado do cadastro de barreiras (consulta + admin)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.barreiras import Barreira
from core.barreiras_store import obter_store

ARQUIVO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "barreiras.geojson"


@st.cache_resource(show_spinner="Carregando o cadastro de barreiras...")
def barreiras_carregadas(caminho: str | Path | None = None) -> list[Barreira]:
    destino = Path(caminho) if caminho else ARQUIVO_PADRAO
    return obter_store(destino).listar()


def invalidar_cache_barreiras() -> None:
    barreiras_carregadas.clear()
