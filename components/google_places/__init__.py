"""Widget de autocomplete do Google Maps para Streamlit."""

from __future__ import annotations

import os
from typing import Any

import streamlit.components.v1 as components

_PARENT = os.path.dirname(os.path.abspath(__file__))
_component = components.declare_component("google_places_autocomplete", path=os.path.join(_PARENT, "frontend"))


def google_places_input(
    api_key: str,
    *,
    placeholder: str = "Digite o endereço...",
    default: str = "",
    key: str | None = None,
) -> dict[str, Any] | None:
    """
    Campo com sugestões do Google Places.

    Retorna dict com formatted_address, lat, lon, street, number quando o usuário
    escolhe uma sugestão; None se ainda não escolheu.
    """
    valor = _component(
        api_key=api_key,
        placeholder=placeholder,
        default=default,
        key=key,
        height=60,
    )
    if not valor or not isinstance(valor, dict):
        return None
    if "lat" not in valor or "lon" not in valor:
        return None
    return valor
